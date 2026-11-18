"""Local HTML view of the acceptance evidence and the actions it supports."""
from html import escape
from importlib.resources import files

from . import consistency
from .models import timestamp


READING_STATES = {"ok": "通过", "observed": "有读数", "fail": "不一致", "warn": "需核对", "error": "请求失败",
                  "timeout": "超时", "invalid_response": "响应无效", "not_measured": "待确认", "stale": "读数过期",
                  "skipped": "未测", "unverified": "待确认", "configuration_required": "需要观测配置",
                  "no_record": "观测端没有记录", "unsupported": "不支持"}
REASONS = {"different_endpoint": "采样端点不同", "different_measurement_time": "采样相差超过 5 分钟",
           "network_still_reachable_during_outage": "断开期间仍取得公网出口",
           "exit_changed_after_restoration": "恢复后的出口与断开前不同", "restoration_failed": "未能恢复原连接",
           "https_failed_during_outage_and_recovered": "断开期间请求失败，恢复后重新取得出口",
           "probe_unreachable_during_outage": "断开时探针无法运行", "baseline_not_connected": "断开前未取得出口",
           "disconnect_not_confirmed": "断开操作未确认", "current_application_exit_not_confirmed": "本次出口无法与演练基线核对"}


def h(value):
    return escape(str(value))


def pill(label, tone):
    return f'<span class="tag {tone}">{h(label)}</span>'


def table(headers, rows, label):
    return (f'<div class="table-wrap" role="region" aria-label="{h(label)}" tabindex="0"><table><thead><tr>'
            + "".join(f'<th scope="col">{h(header)}</th>' for header in headers) + '</tr></thead><tbody>'
            + "".join('<tr><th scope="row">' + h(row[0]) + '</th>'
                      + ''.join(f'<td data-label="{h(header)}">{cell}</td>' for header, cell in zip(headers[1:], row[1:])) + '</tr>'
                      for row in rows) + '</tbody></table></div>')


def network_table(network):
    if not network:
        return '<p class="muted">本报告没有出口对照读数。</p>'
    runtime = network["runtime_context"]
    show_expected = any(row["expected"] for row in network["rows"])
    columns = ["地址族", *(["预期出口"] if show_expected else []), *([runtime] if runtime else []), "实际浏览器", "结论"]
    rows = []
    for row in network["rows"]:
        left, right = row["runtime"], row["browser"]
        cells = [f"IPv{row['family']}"]
        if show_expected:
            cells.append(f'<code>{h(row["expected"])}</code>' if row["expected"] else "未指定")
        for reading in (left, right) if runtime else (right,):
            label = READING_STATES.get(reading["status"], "未测")
            status = "读数过期" if reading["status"] == "stale" else ""
            value = f'<code>{h(reading["ip"])}</code>' if reading["ip"] else h(label)
            if status:
                value += f'<small>{status}</small>'
            cells.append(value)
        result = row["comparison"]
        tone = {"ok": "good", "fail": "fail"}.get(result["state"], "open")
        if False in row["expected_matches"].values():
            conclusion, tone = "与预期出口不同", "fail"
        elif not runtime and row["expected_matches"]["browser"]:
            conclusion, tone = "与预期出口一致", "good"
        elif runtime and bool(consistency.address(left)) != bool(consistency.address(right)):
            conclusion = "只有运行路径取得地址" if consistency.address(left) else "只有浏览器取得地址"
        else:
            conclusion = REASONS.get(result.get("reason"), {"ok": "一致", "fail": "不一致"}.get(result["state"], "待确认"))
        cells.append(pill(conclusion, tone))
        rows.append(cells)
    return table(columns, rows, "IPv4 与 IPv6 并排对照")


def evidence(value):
    if not isinstance(value, dict):
        return str(value) if value is not None else "没有有效读数"
    if value.get("reason") in REASONS:
        return REASONS[value["reason"]]
    if value.get("detail"):
        return str(value["detail"])
    if isinstance(value.get("disabled"), bool):
        return "内核配置显示已禁用" if value["disabled"] else "内核配置未显示禁用"
    for field, label in (("resolvers", "解析器"), ("addresses", "解析结果")):
        if value.get(field):
            return label + " · " + "、".join(value[field])
    return READING_STATES.get(value.get("state", value.get("status")), "没有有效读数")


def guidance(key, row):
    if "出口历史对照" in key:
        if row.get("state") == "warn":
            return "动态出口已变化。确认是否是你预期的换线，再查看本次两端读数是否一致。"
        return "与交付时的地址对照。固定线路发生变化时，核对后台连接和线路配置后重新验收。"
    if row.get("reason") in ("different_endpoint", "different_measurement_time"):
        return "在实际浏览器重新导出结果，并立刻重跑验收，让两端使用同一端点和相近的采集时间。"
    if "断线" in key:
        return "只对本次配置的连接做断开和恢复演练，记录哪些协议仍能访问、恢复后是否回到原出口。"
    if "WebRTC" in key:
        return "核对这个浏览器的 WebRTC 网络设置，重新采集，比较公网候选地址和同地址族的 HTTPS 出口。"
    if "DNS" in key:
        return "在对应运行环境复测解析。要确认 DNS 走哪条路，使用已配置的 DNS 观测端查看实际解析器。"
    if "IPv6" in key and "策略" in key:
        return "核对该运行环境的 IPv6 配置与实际出站请求，分别记录配置状态和请求结果。"
    if any(word in key for word in ("出口", "IPv4", "IPv6", "对外身份")):
        return "核对当前浏览器配置和绑定的运行路径，再在同一次验收里重测这个地址族。"
    if key in ("时区", "语言", "timezone", "locale"):
        return "核对该环境的实际设置和你预先指定的值，保存后用同一环境重新采集。"
    if "UDP" in key:
        return "选择适用于该环境、已知可达的 UDP 测试端点，分别核对正常和断开时的结果。"
    if key.startswith("PVM"):
        return "查看这台虚拟机的路由及协议明细，在同一实例重新运行 VM 验收。"
    return "在交付时记录的同一环境重新检查，确认有实际读数后再下结论。"


def check_groups(report):
    verification = report.get("verification") or {}
    failures = set(verification.get("failed", ()))
    pending = set(verification.get("missing", ())) | set(verification.get("pending", ()))
    groups = {"fail": [], "open": [], "good": []}
    seen = set()
    for row in report.get("local", []) + report.get("application_checks", []) + report.get("remote", {}).get("checks", []):
        key, state = row["key"], row["state"]
        if key in seen:
            continue
        seen.add(key)
        if key in failures or state in ("fail", "error"):
            groups["fail"].append(row)
        elif key in pending or state in ("warn", "unverified"):
            groups["open"].append(row)
        elif state in ("ok", "observed"):
            groups["good"].append(row)
    def priority(row):
        key = row["key"]
        ordered = ("断线", "对外身份", "IPv", "WebRTC", "DNS", "出口")
        return next((rank for rank, word in enumerate(ordered) if word in key), len(ordered))

    for rows in groups.values():
        rows.sort(key=priority)
    return groups


def check_list(rows, tone):
    result = []
    names = {"对外身份": "主要 HTTPS 出口", "unit": "后台服务", "timezone": "服务器时区", "locale": "服务器语言"}
    for row in rows:
        key = row["key"]
        note = REASONS.get(row.get("reason")) or evidence(row.get("measured"))
        expected = row.get("expected")
        reference = "交付时" if "出口历史对照" in key else "预期"
        reading = h(note) if expected is None else f'{reference} <code>{h(expected)}</code> · 实测 <code>{h(note)}</code>'
        observation = row.get("observation") or {}
        if "WebRTC" in key and observation:
            reading += " · " + h("公网候选 " + "、".join(observation["addresses"]) if observation["addresses"]
                                 else "未取得可比较的公网候选")
        label = "已确认异常" if tone == "fail" else READING_STATES.get(row["state"], "待确认")
        result.append(f'<li><div><h3>{h(names.get(key, key))}</h3><p class="reading">{reading}</p></div>'
                      f'{pill(label, tone)}<p class="advice">{h(guidance(key, row))}</p></li>')
    return '<ul class="check-list">' + ''.join(result) + '</ul>'


def render(report):
    score = report["score"]
    verification = report.get("verification") or {}
    groups = check_groups(report)
    labels = {"fail": "需处理", "open": "待确认", "good": "已验证或有读数"}
    counts = ''.join(f'<a href="#{target}">{label} <b>{len(groups[tone])}</b></a>'
                     for (tone, label), target in zip(labels.items(), ("fail", "open-checks", "good-checks")))
    banner = {"fail": "发现需要处理的检查项", "ok": "本次必验项已通过", "not_measured": "还缺少必要读数"}
    headline = banner.get(verification.get("state"), score["label"])
    scope = verification.get("scope", "环境准备检查")
    sample = "合成示例 · 非真实测量" if report.get("sample") else "本地报告"
    at = report.get("at")
    when = timestamp(at).astimezone().strftime("%Y-%m-%d %H:%M %Z") if at else "时间未记录"
    primary = groups["fail"] or groups["open"]
    next_step = (guidance(primary[0]["key"], primary[0]) if primary else
                 "保留这次结果。浏览器配置或网络线路变动后，从同一入口复查。")
    sections = []
    for tone in ("fail", "open", "good"):
        if tone == "fail":
            content = check_list(groups[tone], tone) if groups[tone] else '<p class="muted">所测项目中没有发现已确认的异常。</p>'
            sections.append(f'<section id="fail"><h2>{labels[tone]}</h2>{content}</section>')
        else:
            content = check_list(groups[tone], tone) if groups[tone] else '<p class="muted">本次没有此类检查项。</p>'
            sections.append(f'<details id="{tone}"><summary>{labels[tone]} <span>{len(groups[tone])} 项</span></summary>'
                            f'<div id="{tone}-checks">{content}</div></details>')
    background = sorted(score["dimensions"], key=lambda row: (row["state"] == "not_measured", -row["score"]))
    background_html = table(["维度", "配置分", "依据"], [[row["label"],
        str(row["score"]) + " / 100" if row["state"] != "not_measured" else "未测",
        h(" ".join(row["reasons"]))] for row in background], "背景配置分")
    network = report.get("network_consistency") or {}
    historical = network.get("baseline")
    history_html = ""
    if historical:
        changed = [row["key"].removesuffix(" 出口历史对照") for row in historical["checks"] if row["state"] in ("warn", "fail")]
        policy = "固定出口" if historical["exit_policy"] == "fixed" else "动态出口"
        message = ("有变化 · " + "、".join(changed) if changed else
                   "交付时没有通过验收的出口记录" if not historical["recorded"] else
                   "部分历史地址缺少本次读数" if any(row["state"] == "not_measured" for row in historical["checks"]) else "与交付时一致")
        history_html = f'<p>{h(policy)}历史对照 · {h(message)}</p>'
    facts = report.get("facts") or {}
    facts_html = table(["字段", "读数"], [[key, h(value)] for key, value in sorted(facts.items())], "服务器观测") if facts else ""
    css = files("zhibi").joinpath("assets").joinpath("scan-report.css").read_text(encoding="utf-8")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>知彼 · 环境准备记录</title><style>{css}</style></head><body>
<main><header><div class="page-label"><span class="brand">知彼</span><h1>出口验收</h1></div><span class="edition">{h(sample)}</span></header>
<div class="report-meta"><p>{h(scope)}</p><p><time datetime="{h(at or '')}">{h(when)}</time></p></div>
<section id="exits"><h2>出口对照</h2>{network_table(report.get('network_consistency'))}
<p class="muted">IPv4 与 IPv6 分开比较。请求失败或超时意味着本次没有取得地址。</p>{history_html}</section>
<section class="result-line" aria-label="验收结论"><p>{h(headline)}</p><nav aria-label="按状态查看检查">{counts}</nav></section>
<section class="next-action"><h2>先做这一步</h2><p>{h(next_step)}</p></section>
{''.join(sections)}
<details><summary>背景配置分与原始读数</summary><p class="muted">按已测配置分从高到低排列，未测项列在最后。配置分描述环境检查。</p>{background_html}{facts_html}</details>
<footer>本报告保存在本机。分享前请检查其中的 IP 和环境读数。</footer></main></body></html>'''
