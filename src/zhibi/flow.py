"""五步主线的上层编排：看、建、配、验、交。评分与交付都在这层完成。"""
import json
import ipaddress
import os
import shlex
import re
from argparse import Namespace
from pathlib import Path

from . import consistency, environment, handover, remote, score as scoring
from .acceptance_report import render as render_html
from .models import InputError, now
from .storage import create_run, write

STEPS = ("check", "build", "browse", "accept", "deliver")


def _target(args):
    item = remote.target(args.host, args.user, args.port, args.identity, getattr(args, "ssh_config", None))
    if item["identity"]:
        item["identity"] = str(Path(item["identity"]).absolute())
    return item


def _egress(facts):
    org = (facts.get("egress_org") or "").strip()
    return {"ip": (facts.get("egress_ip") or "").strip() or None,
            "org": org or None,
            "datacenter": scoring.looks_datacenter(org) if org else None}


def _dns(facts):
    nameservers = [n for n in (facts.get("nameservers") or "").split() if n]
    return {"nameservers": nameservers, "public": remote.PUBLIC_DNS}


def _headline(result):
    """Three plain sentences for the user. No jargon."""
    s = result["score"]
    verification = result.get("verification")
    if verification:
        state = verification["state"]
        first = {"ok": "已通过本次选定的验收项目。",
                 "fail": "本次验收未通过。",
                 "not_measured": "本次验收证据不足，暂不能确认通过。"}[state]
        issues = verification["failed"]
        second = "需要处理：" + "、".join(issues) + "。" if issues else "验收范围：" + verification["scope"] + "。"
        missing = verification["missing"] + verification.get("pending", [])
        third = "还未确认：" + "、".join(missing) + "。" if missing else "已记录本次验收结果。"
        return [first, second, third]
    if s["level"] == "insufficient":
        first = "这次能确认的东西还太少，先不下结论。"
    else:
        first = "总体判断：%s（%d 分，覆盖 %d%% 的检查项）。" % (s["label"], s["score"], s["coverage"])
    issues = [d for d in s["dimensions"] if d["state"] in ("fail", "warn")]
    if issues:
        second = "需要处理的：" + "；".join(d["label"] for d in issues) + "。"
    else:
        second = "已经测到的项目里，没有需要处理的问题。"
    labels = {d["id"]: d["label"] for d in s["dimensions"]}
    missing = [labels.get(key, key) for key in s["unmeasured"]]
    third = ("这几项还没测：" + "、".join(missing) + "，所以它们不算通过。") if missing else "全部检查项都已测到。"
    return [first, second, third]


def check(args):
    item = _target(args)
    facts = remote.check(item, egress=getattr(args, "egress", False))
    result_score = scoring.score(egress=_egress(facts), facts=facts,
                                 expect_tz=args.timezone, expect_locale=args.locale,
                                 dns=_dns(facts))
    result = {"step": "check", "host": item["host"], "facts": facts,
              "findings": remote.findings(facts), "score": result_score,
              "headline": _headline({"score": result_score}), "at": now()}
    return result


def build(args):
    """对齐时间与语言，并把用户给的命令变成常驻服务。默认只出计划。"""
    item = _target(args)
    facts = remote.check(item)
    plan = remote.align_plan(facts, args.timezone, args.locale)
    wrapped = None
    if args.application_command:
        service_args = (item, args.unit or "zhibi-service", args.application_command, args.run_user,
                        args.workdir, args.restart, args.memory_mb, args.cpu_percent)
        wrapped = remote.wrap_plan(*service_args, apply=False)
    directory = create_run(args.out) if args.apply else None
    if directory:
        write(directory / "before.private.json", {"target": item, "facts": facts, "alignment": plan})
    result = {"step": "build", "host": item["host"], "connection": item, "before": facts,
              "alignment": plan, "service": wrapped, "applied": False}
    try:
        if args.apply:
            for step in plan:
                outcome = remote.execute(item, "set -e\n" + step["command"])
                step["applied"] = outcome["state"] == "ok"
                if not step["applied"]:
                    raise InputError("环境设置失败，已保存原值和部分结果；请先恢复或处理错误。")
        if args.apply and wrapped:
            wrapped = remote.wrap_plan(*service_args, apply=True)
            result["service"] = wrapped
        result["applied"] = bool(args.apply) and (not wrapped or wrapped["applied"])
        result["summary"] = _build_summary(plan, wrapped, result["applied"])
        if args.apply:
            result["after"] = remote.check(item)
        return result
    finally:
        if directory:
            result["directory"] = str(directory)
            write(directory / "build.private.json", result)


def _build_summary(plan, wrapped, applied):
    lines = []
    if plan:
        lines.append("要改 %d 处：" % len(plan) + "、".join(
            {"timezone": "调整时间", "locale": "调整语言"}.get(s["id"], s["id"]) for s in plan))
    else:
        lines.append("时间与语言不需要改动。")
    if wrapped:
        state = "已经启动" if applied and wrapped.get("applied") else "还没启动"
        lines.append("你的命令会被交给系统托管，关机重启后自己起来（%s）。" % state)
    return " ".join(lines)


PATCH_FIELDS = ("timezone", "language", "webrtc")


def browse(args):
    """从服务器读数反推指纹浏览器该填什么。不代填，不推荐品牌。"""
    item = _target(args)
    facts = remote.check(item)
    timezone = args.timezone or facts.get("tz")
    locale = (facts.get("lc_all") if facts.get("lc_all") not in (None, "unset") else facts.get("lang")) or ""
    language = locale.split(".")[0].replace("_", "-") if "." in locale else locale.replace("_", "-")
    if not timezone and not language:
        raise InputError("服务器没有读到时间或语言，无法反推浏览器参数。")
    patch = {}
    if timezone:
        patch["timezone"] = timezone
    if language:
        patch["language"] = [language]
    patch["webrtc"] = "proxy"
    return {"step": "browse", "host": item["host"], "source_facts": facts, "patch": patch,
            "fields": [
                {"field": "时区（时间）", "value": timezone, "why": "和服务器认为的时间一致"},
                {"field": "语言", "value": language, "why": "和系统语言一致"},
                {"field": "网络通道", "value": "服务器", "why": "让浏览器从这里出去"},
                {"field": "WebRTC", "value": "跟随通道", "why": "堵住会把本地位置漏出去的便道"},
            ],
            "notice": "填完必须关掉浏览器再重开，然后重新测一遍才算生效。"}


def browser_readings(path):
    """Normalize validated probe exports; stale/automated observations cannot pass."""
    from .browser import parse_bundle
    from .models import timestamp
    from .scan import browser_paths
    with open(path, encoding="utf-8") as handle:
        bundle = parse_bundle(json.load(handle))
    context = next(o for o in bundle["observations"] if o["check_id"] == "browser.context")
    facts = context["facts"]
    fresh = lambda at: -60 <= (timestamp(now()) - timestamp(at)).total_seconds() <= 900
    if context["status"] != "ok" or facts.get("automated") or not fresh(context["at"]):
        return {}
    readings = {"timezone": facts.get("timezone"), "language": facts.get("language")}
    egress = next(o for o in bundle["observations"] if o["check_id"] == "browser.egress")
    readings["ipv4"] = {"status": egress["status"] if fresh(egress["at"]) else "stale",
                        "at": egress["at"], **egress["facts"]}
    if egress["status"] == "ok" and fresh(egress["at"]):
        readings["egress_ip"] = str(ipaddress.ip_address(egress["facts"]["ip"]))
    if bundle["network"]:
        v4 = bundle["network"]["ipv4"]
        readings["ipv4"] = {**v4, "status": v4["status"] if fresh(v4["at"]) else "stale"}
        observation = bundle["network"]["ipv6"].copy()
        if not fresh(observation["at"]):
            observation["status"] = "stale"
        if observation["ip"]:
            observation["ip"] = str(ipaddress.ip_address(observation["ip"]))
        readings["ipv6"] = observation
    paths, _, _ = browser_paths(bundle, [], {"route_intent": "proxy"})
    rtc = next((p for p in paths if p["id"] == "path:webrtc"), {})
    relation = rtc.get("https_relation")
    readings["webrtc_leak"] = {"different": True, "same_observed": False}.get(relation)
    if rtc and fresh(rtc["at"]):
        addresses = {ipaddress.ip_address(item["address"]) for item in bundle["network"]["webrtc"]["candidates"]
                     if item["type"] == "srflx" and item["address"]}
        readings["webrtc"] = {"status": rtc["status"], "at": rtc["at"], "candidate_count": rtc["candidate_count"],
                              "addresses": sorted(str(value) for value in addresses if value.is_global and not value.is_multicast)}
    extras = bundle.get("extras")
    if extras and fresh(extras["at"]):
        dns = extras["checks"]["dns"]
        readings["dns"] = {"status": dns["status"], "at": extras["at"], **(dns["facts"] or {})}
    return readings


def browser_exits(readings):
    legacy = readings.get("egress_ip")
    legacy = {ipaddress.ip_address(legacy).version: {"status": "ok", "ip": legacy}} if legacy else {}
    return {family: consistency.sample(family, readings.get("ipv" + str(family)) or legacy.get(family))
            for family in consistency.ENDPOINTS}


def _compare(key, expected, actual):
    state = "not_measured" if expected in (None, "") or actual in (None, "") else (
        "ok" if str(expected) == str(actual) else "fail")
    return {"key": key, "expected": expected, "measured": actual, "state": state}


def _verification(scope, required, checks, optional):
    failed = list(dict.fromkeys(row["key"] for row in checks if row["state"] in ("fail", "error")))
    measured = {"ok", "observed", "fail", "error"}
    missing = [row["key"] for row in required if row["state"] not in measured]
    pending = [row["key"] for row in optional if row["state"] not in measured and row["key"] not in missing]
    return {"scope": scope, "state": "fail" if failed else "not_measured" if missing or not required else "ok",
            "failed": failed, "missing": missing, "pending": pending}


def project_evidence(args):
    from . import project, project_audit
    options = Namespace(project=args.project, state_dir=getattr(args, "state_dir", None),
                        network=args.egress, expected_ip=getattr(args, "expected_ip", None), browser=None,
                        disconnect_file=None, reconnect_file=None, out=None)
    binding, _ = project.load(options)
    outage = project_audit.read_outage(args.outage_report, binding) if getattr(args, "outage_report", None) else None
    result = project_audit.audit(options, binding)
    if outage:
        evidence = outage["result"].copy()
        evidence["at"] = outage["at"]
        baselines = [(outage.get(field), result["checks"].get(key, {}).get("ip"))
                     for field, key in (("baseline_ip", "egress"), ("baseline_ipv6", "egress_ipv6"))]
        baseline_matches = (any(before for before, _ in baselines)
                            and all(before == after for before, after in baselines if before)
                            and result["checks"]["application_scope"]["state"] == "ok")
        if evidence["state"] == "ok" and not baseline_matches:
            evidence.update(state="not_measured", reason="current_application_exit_not_confirmed")
        result["checks"]["outage"] = evidence
        if evidence["state"] == "fail":
            result["requires_attention"] = True
    return binding, result


def project_checks(audit):
    """Keep failures and unfinished checks visible alongside the exit comparison."""
    labels = {"dns_resolution": "应用 DNS 解析", "dns_route": "应用 DNS 路径",
              "udp": "应用 UDP 路径", "ipv6": "应用 IPv6 策略", "outage": "应用断线与恢复"}
    rows = []
    for key, reading in audit.get("checks", {}).items():
        if key in labels:
            state = reading["state"]
            if key == "ipv6" and state == "observed" and not reading.get("disabled"):
                state = "unverified"
            rows.append({"key": labels[key], "state": state, "measured": reading})
    pvm = audit.get("pvm")
    if pvm is not None:
        names = {"vm": "状态", "route": "出口路由", "tcp": "TCP", "udp": "UDP", "icmp": "ICMP",
                 "dns": "DNS", "ipv6": "IPv6", "timezone": "时区", "locale": "语言环境"}
        for key, reading in pvm.get("checks", {}).items():
            # The configured guest IPv6 policy supersedes the raw upstream diagnostic.
            if key != "ipv6_upstream":
                rows.append({"key": "PVM " + names.get(key, key), "state": reading["state"], "measured": reading})
        if not pvm.get("protocol_checks_passed"):
            rows.append({"key": "PVM 协议验收", "state": "not_measured", "measured": pvm.get("upstream_exit_status")})
    return rows


def has_browser(args):
    return bool(getattr(args, "browser", None) or getattr(args, "browser_profile", None)
                or getattr(args, "browser_workspace", None)
                or getattr(args, "proxy_port", None) is not None
                or ((getattr(args, "expected_ip", None) or getattr(args, "expected_ipv6", None))
                    and not getattr(args, "project", None)))


def accept(args):
    """Compare against the declared browser-only route or measured project runtime."""
    selected = getattr(args, "project", None)
    proxy_port = getattr(args, "proxy_port", None)
    expected = getattr(args, "expected_ip", None)
    expected = ipaddress.ip_address(expected) if expected else None
    ipv6_target = getattr(args, "expected_ipv6", None)
    ipv6_target = ipaddress.IPv6Address(ipv6_target) if ipv6_target else None
    targets = {expected.version: str(expected)} if expected else {}
    if ipv6_target:
        if 6 in targets and targets[6] != str(ipv6_target):
            raise InputError("两处声明的预期 IPv6 地址不一致。")
        targets[6] = str(ipv6_target)
    primary_family = expected.version if expected else (6 if ipv6_target and not (selected or proxy_port) else 4)
    measured_browser = getattr(args, "browser", None)
    browser_required = has_browser(args)
    egress = getattr(args, "egress", False)
    outage_requested = getattr(args, "outage_report", None)
    if proxy_port is not None and not egress:
        raise InputError("测量浏览器后台连接需要同时指定 --egress。")
    if outage_requested and not (selected and egress):
        raise InputError("使用断线报告需要同时指定 --project 与 --egress。")
    binding, audit = project_evidence(args) if selected else (None, None)
    if binding:
        item = binding["target"]
    else:
        item = _target(args) if getattr(args, "host", None) else None
    if not (selected or item or targets or proxy_port is not None):
        raise InputError("请选择项目、SSH 主机，或提供仅浏览器路线的预期出口。")
    baseline_folder = getattr(args, "baseline", None)
    historical = (environment.baseline(baseline_folder, environment.scope_key(
        (audit or {}).get("binding_sha256"), item, proxy_port, browser_required)) if baseline_folder else None)
    facts = remote.check(item, egress=egress and not targets) if item and not selected else {}
    unit_state = enabled = None
    if args.unit and not item:
        raise InputError("检查服务需要 SSH 主机。")
    if args.unit:
        remote._check(remote.UNIT, args.unit, "服务名无效。")
        outcome = remote.execute(item, "systemctl is-active " + args.unit)
        unit_state = outcome["value"].strip() if outcome["state"] == "ok" else None
        outcome = remote.execute(item, "systemctl is-enabled " + args.unit)
        enabled = outcome["value"].strip() == "enabled" if outcome["state"] == "ok" else None
    far = remote.verify(facts, args.timezone if facts else None, args.locale if facts else None,
                        args.unit, unit_state)
    local_readings = {}
    if measured_browser:
        local_readings = browser_readings(args.browser)
    browser = browser_exits(local_readings)
    if binding:
        checks = audit.get("checks", {})
        scoped = checks.get("application_scope", {}).get("state") == "ok"
        runtime = {4: consistency.sample(4, checks.get("egress")),
                   6: consistency.sample(6, checks.get("egress_ipv6"))}
        runtime_label = ("PVM 内运行环境" if binding["backend"] == "pvm" else
                         "知彼进程工作区" if binding.get("runtime_workspace") else
                         "自定义探针（应用待验）" if binding.get("probe_prefix") else "SSH 宿主（应用待验）")
        scope = "项目与实际浏览器的 HTTPS 出口对比" if browser_required else "项目 HTTPS 出口"
    elif proxy_port is not None:
        from . import connect

        scoped = True
        runtime = {}
        for family, endpoint in consistency.ENDPOINTS.items():
            probe = connect.verify_route(Namespace(local_port=proxy_port, network=True, family=family, expected_ip=None))
            runtime[family] = consistency.sample(family, {"endpoint": endpoint, "at": probe.get("at"),
                                                          "status": probe["status"], **(probe.get("facts") or {})})
        runtime_label = "后台 SOCKS 连接"
        scope = "后台 SOCKS 连接与实际浏览器的 HTTPS 出口对比"
    else:
        scoped = False
        runtime = {4: consistency.sample(4, {"ip": facts.get("egress_ip"), "state": "observed"}
                                         if facts.get("egress_ip") else None), 6: consistency.sample(6)}
        runtime_label = "SSH 宿主" if item else None
        scope = ("实际浏览器的 HTTPS 出口与预期出口对比" if targets else
                 "SSH 主机" + ("与实际浏览器；仅覆盖宿主出口" if measured_browser else ""))

    exit_matrix = consistency.rows(browser, runtime, targets)
    routes = {row["family"]: row for row in exit_matrix}
    primary = routes[primary_family]
    browser_ip = consistency.address(primary["browser"])
    app_ip = consistency.address(primary["runtime"]) if scoped else None
    reference = app_ip if binding or proxy_port is not None else (targets.get(primary_family) or
                                                                  consistency.address(primary["runtime"]))
    exit_row = _compare("对外身份", reference, browser_ip)
    if scoped and exit_row["state"] != "not_measured":
        exit_row.update(primary["comparison"])
    required = [exit_row] if browser_required else []
    optional = []
    near = []
    for key, expect, measured in (
            ("时区", args.timezone, local_readings.get("timezone")),
            ("语言", args.language, local_readings.get("language")),
            ("WebRTC 与 HTTPS 出口", "一致", {True: "不同", False: "一致"}.get(local_readings.get("webrtc_leak")))):
        near.append(_compare(key, expect, measured))
    near.insert(2, exit_row)
    if browser_required:
        near[3]["observation"] = local_readings.get("webrtc", {})
        optional.append(near[3])
        dns = local_readings.get("dns", {"status": "not_measured"})
        dns_row = {"key": "浏览器 DNS 路径", "measured": dns,
                   "state": "observed" if dns["status"] == "ok" else "not_measured"}
        optional.append(dns_row)
        for family in consistency.ENDPOINTS:
            if family == primary_family:
                continue
            route = routes[family]
            observed = consistency.address(route["browser"])
            baseline = consistency.address(route["runtime"]) if scoped else targets.get(family)
            row = _compare(f"浏览器 IPv{family} 路径", baseline, observed)
            if scoped and baseline and observed:
                row.update(route["comparison"])
            if not baseline and observed:
                row["state"] = "unverified"
            row["observation"] = local_readings.get("ipv" + str(family), route["browser"])
            near.append(row)
            (required if family in targets else optional).append(row)
        near.append(dns_row)
    if binding or proxy_port is not None:
        runtime_name = "隔离应用" if binding else "后台 SOCKS"
        target = targets.get(primary_family)
        app_row = {"key": runtime_name + "出口", "expected": target, "measured": app_ip,
                   "state": "not_measured" if not app_ip else "fail" if target and app_ip != target else "ok"}
        near.append(app_row)
        required.append(app_row)
        for family, target in targets.items():
            if family != primary_family:
                actual = consistency.address(runtime[family]) if scoped else None
                target_row = _compare(f"{runtime_name} IPv{family} 预期出口", target, actual)
                near.append(target_row)
                required.append(target_row)
            if browser_required:
                label = "浏览器预期出口" if family == primary_family else f"浏览器 IPv{family} 预期出口"
                target_row = _compare(label, target, consistency.address(browser[family]))
                near.append(target_row)
                required.append(target_row)
    required.extend(row for row in near[:2] if measured_browser and row["expected"])
    required.extend(row for row in far["checks"] if row["key"] in ("timezone", "locale", "unit") and row["expected"])
    application_checks = project_checks(audit) if binding else []
    for row in application_checks:
        if row["key"] == "PVM 协议验收" or (outage_requested and row["key"] == "应用断线与恢复"):
            required.append(row)
        else:
            optional.append(row)
    network = {"runtime_context": runtime_label, "rows": exit_matrix}
    if historical:
        history_rows = environment.drift(historical, network)
        for row in history_rows:
            (required if row["required"] else optional).append(row)
        near += history_rows
        network["baseline"] = {"at": historical["at"], "exit_policy": historical["exit_policy"],
                               "recorded": bool(historical["baseline"]), "checks": history_rows}
    verification = _verification(scope, required, near + far["checks"] + application_checks, optional)
    result_score = scoring.score(
        egress=_egress(facts), facts=facts, expect_tz=args.timezone, expect_locale=args.locale,
        dns=_dns(facts), webrtc={"leak": local_readings.get("webrtc_leak")},
        service={"active": unit_state == "active" if unit_state else None,
                 "enabled": enabled})
    result_score["used_for_verification"] = False
    report = {"step": "accept", "host": item["host"] if item else ("local-vm" if binding else "browser"),
            "at": now(), "facts": facts, "remote": far, "local": near, "connection": item,
            "score": result_score, "verification": verification, "application_checks": application_checks,
            "network_consistency": network,
            "notice": "远端与本地分开计数；未测量的项不计入通过。"}
    if binding:
        state_dir = getattr(args, "state_dir", None)
        report["project_audit"] = audit
        report["project_context"] = {"path": binding["project"], "backend": binding["backend"],
                                     "workdir": binding["workdir"],
                                     "state_dir": str(Path(state_dir).expanduser().absolute()) if state_dir else None}
        if binding.get("runtime_workspace"):
            report["project_context"]["runtime_workspace"] = binding["runtime_workspace"]
        if binding["backend"] == "pvm" and binding.get("vm_workspace"):
            report["project_context"]["vm_workspace"] = binding["vm_workspace"]
    report["headline"] = _headline(report)
    return report


FIRST_READ = """# 先读我

这份文件夹是这次搭建留下的记录。

## 现在是什么状态

{summary}

## 日常怎么打开

{daily}

## 后台连接和恢复

{maintenance}

## 里面有什么

| 文件 | 内容 |
| --- | --- |
| 报告.html | 完整细节，双击就能看 |
| remote.md | 服务器上改了什么、日志在哪看 |
| browser.md | 浏览器每个字段填了什么、为什么 |
| verification.json | 两端读数与逐项结果 |
| reproduce.sh | 按本次验收范围重新检查 |
{environment_row}
{rollback_row}
"""


def recheck_script(report, target):
    request = report.get("acceptance_request", {})
    project = report.get("project_context")
    browser = request.get("browser", False)
    command = handover.cli_command()
    action = "accept" if request or project or browser or not target else "check"
    if project:
        command += [action, "--project", project["path"]]
        if project.get("state_dir"):
            command += ["--state-dir", project["state_dir"]]
    elif target:
        command += [action, *handover.connection_args(target)]
    elif request.get("proxy_port") is not None:
        command += [action, "--proxy-port", str(request["proxy_port"])]
    else:
        command += [action]
    if request.get("network", True):
        command += ["--egress"]
    if request.get("expected_ip"):
        command += ["--expected-ip", request["expected_ip"]]
    if request.get("expected_ipv6"):
        command += ["--expected-ipv6", request["expected_ipv6"]]
    for field, flag in (("timezone", "--timezone"), ("locale", "--locale"), ("language", "--language"), ("unit", "--unit")):
        if request.get(field) and (field != "language" or action == "accept"):
            command += [flag, request[field]]
    script = "#!/bin/sh\nset -e\n"
    if browser:
        script += 'if [ "$#" -ne 1 ]; then printf "%s\\n" "请传入当前实际浏览器新导出的 JSON 文件。" >&2; exit 2; fi\n'
    baseline = ""
    if report.get("environment_record"):
        script += 'folder=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        baseline = ' --baseline "$folder"'
    return script + "exec " + shlex.join(command) + baseline + (' --browser "$1"' if browser else "") + "\n"


def deliver_files(destination, report, unit=None, timezone=None, locale=None, facts=None):
    """Write the folder the user keeps. Pure file work, no network."""
    destination = Path(destination)
    s = report["score"]
    summary = "；".join(report.get("headline") or [s["label"]])
    target = report.get("connection") if "connection" in report else remote.target(report["host"])
    plan = report.get("handover", {})
    status_commands = list(plan.get("status", []))
    commands = list(plan.get("rollback", []))
    launch = plan.get("launch", {})
    local_shell = {name: "`" + shlex.join(["sh", str(destination.absolute() / name)]) + "`" for name in launch}
    daily = []
    if "open-browser.sh" in launch:
        daily.append("- 专用 Chromium：在你自己的电脑打开终端，执行 " + local_shell["open-browser.sh"] + "。")
    elif "open-vm-desktop.sh" in launch:
        daily.append("- VM 内的浏览器：在你自己的电脑打开终端，执行 " + local_shell["open-vm-desktop.sh"]
                     + "，再在虚拟机桌面打开「" + plan["browser_profile"] + "」。")
    elif plan.get("browser_profile"):
        daily.append("- 浏览器：打开「" + plan["browser_profile"] + "」。")
    project = report.get("project_context")
    if "open-project.sh" in launch:
        daily.append("- 命令行应用：在你自己的电脑打开终端，执行 " + local_shell["open-project.sh"] + "。")
    if project:
        location = "虚拟机内" if project["backend"] == "pvm" else "远程 Linux 上"
        daily.append("- " + location + "的项目目录：`" + project["workdir"] + "`。")
    if plan.get("app_entry"):
        daily.append("- 已配置的隔离入口：`" + shlex.quote(plan["app_entry"]) + "`。")
    if not daily:
        daily = ["本次交付未记录日常入口。"]
    stop = None
    logs = None
    if unit:
        remote._check(remote.UNIT, unit, "服务名无效。")
        stop = handover.ssh_command(target, ["systemctl", "stop", unit])
        logs = handover.ssh_command(target, ["journalctl", "-u", unit, "-n", "50", "--no-pager"])
    receipt = report.get("deployment") or {}
    saved_service = receipt.get("service") or {}
    recovery = saved_service.get("rollback") if saved_service.get("applied") else None
    if recovery and not re.fullmatch(r"sh /var/lib/zhibi/deployments/[a-f0-9]{32}/rollback\.sh", recovery):
        raise InputError("部署恢复路径无效。")
    if recovery:
        commands.append(handover.ssh_command(target, shlex.split(recovery)))
    for change in reversed(receipt.get("alignment", [])):
        if change.get("applied") and change.get("id") == "timezone":
            old = remote._check(remote.TZONE, change.get("before"), "原时区无效。")
            commands.append(handover.ssh_command(target, ["timedatectl", "set-timezone", old]))
    maintenance = []
    if status_commands:
        maintenance += ["查询本轮登记的后台服务：", "", *("    " + cmd for cmd in status_commands), ""]
    if stop:
        maintenance += ["停止本轮登记的系统服务：", "", "    " + stop, ""]
    if plan.get("vm_stop"):
        maintenance += ["在本机停止这台 VM（保留磁盘与项目）：", "", "    " + plan["vm_stop"], ""]
    if commands:
        maintenance += ["撤销已记录的改动：", "", "    bash rollback.sh", ""]
    else:
        maintenance += ["本次记录没有可自动恢复的配置。", ""]
    with_browser = report.get("acceptance_request", {}).get("browser", False)
    maintenance += ["重新检查：", "", "    bash reproduce.sh" + (" 新导出的浏览器.json" if with_browser else "")]
    if report.get("acceptance_request", {}).get("outage_recorded"):
        maintenance += ["", "断线演练结果在报告里。复查脚本只测正常连接；要重测断线，请按演练步骤操作。"]
    reproduce = recheck_script(report, target)
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    write(destination / "先读我.md", FIRST_READ.format(
        summary=summary, daily="\n".join(daily), maintenance="\n".join(maintenance),
        environment_row="| environment.private.json | 本次验收范围、出口策略与历史出口 |" if report.get("environment_record") else "",
        rollback_row="| rollback.sh | 撤销本轮记录中已提供恢复入口的改动 |" if commands else ""))
    if report.get("environment_record"):
        write(destination / environment.FILENAME, report["environment_record"])
    write(destination / "报告.html", render_html(report))
    write(destination / "verification.json", report)
    write(destination / "remote.md", "# 服务器观测与部署记录\n\n" + json.dumps(
        {"facts": report.get("facts") or facts or {}, "deployment": receipt, "project_audit": report.get("project_audit"),
         "stop": stop, "logs": logs, "managed": plan},
        ensure_ascii=False, indent=2) + "\n")
    write(destination / "browser.md", "# 浏览器实际验收\n\n" + json.dumps(
        {"checks": report.get("local", []), "timezone_target": timezone,
         "locale_target": locale, "notice": "这里只记录观测与目标，不代表已经修改配置。"},
        ensure_ascii=False, indent=2) + "\n")
    write(destination / "reproduce.sh", reproduce)
    for name, argv in launch.items():
        write(destination / name, "#!/bin/sh\nexec " + shlex.join(argv) + "\n")
    if commands:
        write(destination / "rollback.sh", "#!/bin/sh\nset -e\n" + "\n".join(commands) + "\n")
    if os.name == "posix":
        scripts = ["reproduce.sh", *launch]
        if commands:
            scripts.append("rollback.sh")
        for name in scripts:
            os.chmod(destination / name, 0o700)
    return destination


def deliver(args):
    browser_service = getattr(args, "browser_service", None)
    browser_workspace = getattr(args, "browser_workspace", None)
    port = getattr(args, "proxy_port", None)
    if browser_service:
        connection, _ = handover.browser_service(browser_service, port)
        port = connection["local_port"]
    if browser_workspace:
        handover.browser_launcher(browser_workspace, port)
    report = accept(args)
    item = report["connection"] if "connection" in report else _target(args)
    report["step"] = "deliver"
    facts, result_score = report["facts"], report["score"]
    report["connection"] = item
    report["handover"] = handover.describe(args, item, report.get("project_context"))
    report["acceptance_request"] = {"browser": has_browser(args),
                                    "outage_recorded": bool(getattr(args, "outage_report", None)),
                                    "network": getattr(args, "egress", False),
                                    "expected_ip": getattr(args, "expected_ip", None),
                                    "expected_ipv6": getattr(args, "expected_ipv6", None),
                                    "proxy_port": getattr(args, "proxy_port", None),
                                    "timezone": args.timezone, "locale": args.locale, "unit": args.unit,
                                    "language": getattr(args, "language", None)}
    request = report["acceptance_request"]
    policy = getattr(args, "exit_policy", None) or ("fixed" if request["expected_ip"] or request["expected_ipv6"] else "dynamic")
    report["environment_record"] = environment.manifest(report, policy)
    if getattr(args, "build_receipt", None):
        with open(args.build_receipt, encoding="utf-8") as handle:
            receipt = json.load(handle)
        if receipt.get("connection") != item or receipt.get("step") != "build":
            raise InputError("部署回执与当前目标不一致。")
        report["deployment"] = receipt
    base = Path(os.path.expanduser(args.out or "~/Desktop")).absolute()
    folder = base / ("zhibi-" + report["host"].replace(".", "-") + "-" + now()[:10])
    if folder.exists():
        raise InputError("目标文件夹已存在，请换一个输出目录。")
    destination = deliver_files(folder, report, args.unit, args.timezone, args.locale, facts)
    session = create_run(None)
    write(session / "report.json", report)
    return {"step": "deliver", "directory": str(destination), "score": result_score,
            "headline": report["headline"], "session": str(session),
            "verification": report.get("verification", {}),
            "network_consistency": report.get("network_consistency", {})}


def dispatch(args):
    workflow = environment.workflow(args.environment) if getattr(args, "environment", None) else None
    result = {"check": check, "build": build, "browse": browse,
              "accept": accept, "deliver": deliver}[args.command](args)
    if args.command in ("check", "browse", "accept") and (getattr(args, "out", None) or getattr(args, "baseline", None) or workflow):
        directory = create_run(getattr(args, "out", None))
        write(directory / (args.command + ".private.json"), result)
        if args.command == "accept":
            write(directory / "报告.html", render_html(result))
        result["directory"] = str(directory)
    if workflow:
        environment.record(workflow, args.command, result)
    return result


def register(sub):
    for name, text in (("check", "看服务器现状并给出评分，不改任何东西"),
                       ("build", "让命令常驻并对齐时间与语言；默认只出计划"),
                       ("browse", "算出指纹浏览器该填什么"),
                       ("accept", "核对实际应用、浏览器及目标出口"),
                       ("deliver", "把结果写成一个能留住的文件夹")):
        p = sub.add_parser(name, help=text)
        if name in ("accept", "deliver"):
            source = p.add_mutually_exclusive_group()
            source.add_argument("--host", help="服务器地址或 SSH 别名；此模式仅测宿主")
            source.add_argument("--project", help="绑定项目；从实际应用运行环境测量")
            source.add_argument("--proxy-port", type=int, help="仅浏览器路线：通过本机后台 SOCKS 连接分别测 IPv4 和 IPv6；需要 --egress")
            p.add_argument("--state-dir", help="绑定项目的私人状态目录")
            p.add_argument("--expected-ip", help="预期出口；只验浏览器时可单独指定")
            p.add_argument("--expected-ipv6", help="可选：同时核对明确指定的 IPv6 出口")
            p.add_argument("--outage-report", help="同一项目 15 分钟内的断线演练报告，只读导入")
        else:
            p.add_argument("--host", required=True, help="服务器地址或 SSH 别名")
        p.add_argument("--user", help="SSH 用户；未指定时沿用显式 SSH 配置，否则默认为 root")
        p.add_argument("--port", type=int, help="SSH 端口；未指定时沿用显式 SSH 配置，否则默认为 22")
        p.add_argument("--identity", help="私钥文件路径（权限 600）")
        p.add_argument("--ssh-config", help="已有私人 SSH 配置文件（权限 600）")
        p.add_argument("--timezone", help="目标时区，例如 Europe/Berlin")
        p.add_argument("--locale", help="目标 locale，例如 en_US.UTF-8")
        p.add_argument("--unit", help="服务名")
        p.add_argument("--out", help="交付目录，默认桌面")
        p.add_argument("--environment", help="将本步骤保存到 environment init 创建的私人过程目录")
        p.add_argument("--egress", action="store_true",
                       help="允许使用相关运行环境发起网络探测（项目测 IPv4 和 IPv6）")
        if name == "deliver":
            p.add_argument("--exit-policy", choices=("fixed", "dynamic"), help="固定出口历史变化不通过；动态出口仅提示")
            p.add_argument("--build-receipt", help="本轮 build.private.json，用于生成远端恢复步骤")
            p.add_argument("--browser-profile", help="实际交付的浏览器配置名称")
            p.add_argument("--browser-service", help="已安装的本机 connection-service 目录")
            browser_entry = p.add_mutually_exclusive_group()
            browser_entry.add_argument("--browser-workspace", help="browser-workspace 生成的本机 Chromium 目录")
            browser_entry.add_argument("--vm-browser", action="store_true", help="从 PVM 桌面打开 --browser-profile")
            p.add_argument("--runtime-service", help="SSH 目标上的 runtime-service 交付目录")
            p.add_argument("--app-entry", help="Linux 运行环境中已配置的应用入口绝对路径")
            p.add_argument("--shell", choices=("bash", "zsh"), help="已激活的应用命令所在 shell")
            p.add_argument("--remote-skill-entry", help="远端 Skill 的 scripts/zhibi.py 路径，用于恢复 shell")
        if name == "build":
            p.add_argument("--command", dest="application_command", help="要长期运行的命令，由用户提供，原样使用")
            p.add_argument("--run-user", default="root")
            p.add_argument("--workdir")
            p.add_argument("--restart", type=int, default=10)
            p.add_argument("--memory-mb", type=int)
            p.add_argument("--cpu-percent", type=int)
            p.add_argument("--apply", action="store_true", help="真正执行；默认只出计划")
        if name in ("accept", "deliver"):
            p.add_argument("--language", help="本地浏览器语言")
            p.add_argument("--browser", help="本地浏览器读数 JSON")
        if name == "accept":
            p.add_argument("--baseline", help="从已有交付目录读取本次复查的历史出口")
