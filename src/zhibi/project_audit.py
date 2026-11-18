"""Live evidence from the bound execution environment, with an optional outage drill."""
import hashlib
import ipaddress
import json
import shlex
import subprocess
import sys
from pathlib import Path

from . import consistency, remote
from .models import InputError, now, timestamp

PROBE = r'''
import ipaddress,json,socket,urllib.error,urllib.request
from pathlib import Path
r={'execution':'ok','dns':{'state':'not_measured'},'ipv6':{'state':'not_measured'}}
try:
    socket.setdefaulttimeout(6)
    r['dns']={'state':'observed','addresses':sorted({x[4][0] for x in socket.getaddrinfo('api.ipify.org',443,socket.AF_INET)})}
except Exception:
    r['dns']={'state':'error'}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

opener=urllib.request.build_opener(NoRedirect())
for family,endpoint in ENDPOINTS.items():
    key='egress' if family==4 else 'egress_ipv6'
    r[key]={'state':'error'}
    try:
        with opener.open(endpoint,timeout=8) as response:
            ip=ipaddress.ip_address(json.loads(response.read(128))['ip'])
        if ip.version!=family:
            raise ValueError('unexpected address family')
        r[key]={'state':'observed','ip':str(ip)}
    except (TimeoutError,urllib.error.URLError,OSError) as error:
        if isinstance(error,TimeoutError) or isinstance(getattr(error,'reason',None),TimeoutError):
            r[key]['state']='timeout'
    except (ValueError,TypeError,KeyError):
        r[key]['state']='invalid_response'
try:
    values={p.parent.name:p.read_text().strip() for p in Path('/proc/sys/net/ipv6/conf').glob('*/disable_ipv6')}
    boot_disabled='ipv6.disable=1' in Path('/proc/cmdline').read_text().split() and not values
    r['ipv6']={'state':'observed','disabled':boot_disabled or bool(values) and {'all','default','lo'} <= values.keys() and all(v=='1' for v in values.values()),'interfaces':values}
except OSError:
    pass
print(json.dumps(r))
'''


def measure(data):
    expression = "python3 -c " + shlex.quote("ENDPOINTS = " + repr(consistency.ENDPOINTS) + "\n" + PROBE)
    prefix = data.get("runtime_prefix") or (data.get("probe_prefix", []) if data["backend"] != "pvm" else [])
    if prefix:
        expression = " ".join(shlex.quote(item) for item in prefix) + " " + expression
    if data["backend"] in ("remote", "ssh-vm"):
        outcome = remote.execute(remote.target(**data["target"]), expression, timeout=45)
        text = outcome["value"] if outcome["state"] == "ok" else ""
    else:
        from . import pvm_backend as pvm
        _, vm = pvm.load(data["vm_workspace"])
        try:
            done = subprocess.run(pvm.guest_command(vm, expression), env=pvm.environment(vm),
                                  capture_output=True, text=True, timeout=45)
            text = done.stdout if done.returncode == 0 else ""
        except subprocess.TimeoutExpired:
            text = ""
    try:
        result = json.loads(text)
        if result.get("execution") != "ok" or not isinstance(result.get("egress"), dict):
            raise ValueError()
        if result["egress"].get("ip"):
            ipaddress.ip_address(result["egress"]["ip"])
        return result
    except (ValueError, AttributeError, TypeError):
        return {"execution": "error", "egress": {"state": "not_measured"}}


def connected(observation):
    return observation.get("execution") == "ok" and any(
        observation.get(key, {}).get("state") == "observed" for key in ("egress", "egress_ipv6"))


def binding_fingerprint(data):
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_outage(path, data):
    from .project import private_read

    report = json.loads(private_read(Path(path).expanduser()))
    if not isinstance(report, dict) or report.get("binding_sha256") != binding_fingerprint(data):
        raise InputError("断线报告不属于当前项目绑定；请用当前绑定重新演练。")
    if not -60 <= (timestamp(now()) - timestamp(report.get("at"))).total_seconds() <= 900:
        raise InputError("断线报告已过期；请使用 15 分钟内的报告。")
    checks = report.get("checks", {})
    outage = checks.get("outage", {})
    if (report.get("version") != 1 or not outage.get("reason")
            or outage.get("state") not in ("ok", "fail", "not_measured")):
        raise InputError("文件没有有效的项目断线演练结果。")
    return {"at": report["at"], "baseline_ip": checks.get("egress", {}).get("ip"),
            "baseline_ipv6": checks.get("egress_ipv6", {}).get("ip"), "result": outage}


def control(path):
    from .connect import command_text
    # Read/validate both control scripts before the outage starts. No shell filename
    # interpolation; script text is an explicitly supplied private action.
    text = command_text(path)
    try:
        done = subprocess.run(["sh", "-c", text], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=45)
        return done.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def outage(data, before, disconnect, reconnect):
    from .connect import command_text
    command_text(disconnect)
    command_text(reconnect)
    if not connected(before):
        return {"state": "not_measured", "reason": "baseline_not_connected"}
    result = {"state": "not_measured", "reason": "disconnect_not_confirmed"}
    try:
        result["disconnect_succeeded"] = control(disconnect)
        if result["disconnect_succeeded"]:
            result["during"] = measure(data)
    finally:
        result["reconnect_succeeded"] = control(reconnect)
        result["after"] = measure(data)
    during = result.get("during", {})
    after = result["after"]
    if not result["reconnect_succeeded"] or not connected(after):
        result.update(state="fail", reason="restoration_failed")
    elif any(before.get(key, {}).get("ip") and after.get(key, {}).get("ip") != before[key]["ip"]
             for key in ("egress", "egress_ipv6")):
        result.update(state="fail", reason="exit_changed_after_restoration")
    elif connected(during):
        result.update(state="fail", reason="network_still_reachable_during_outage")
    elif during.get("execution") != "ok":
        if result["disconnect_succeeded"]:
            result.update(state="not_measured", reason="probe_unreachable_during_outage")
    elif all(during.get(key, {}).get("state") in ("error", "timeout")
             for key in ("egress", "egress_ipv6") if before.get(key, {}).get("ip")):
        result.update(state="ok", reason="https_failed_during_outage_and_recovered")
    return result


def audit(args, data):
    if not args.network:
        return {"attempted": False, "recipient": "api.ipify.org", "complete": False,
                "binding_sha256": binding_fingerprint(data)}
    if bool(args.disconnect_file) != bool(args.reconnect_file):
        raise InputError("断网演练必须同时提供断开和恢复脚本。")
    expected = str(ipaddress.ip_address(args.expected_ip)) if args.expected_ip else None
    before = measure(data)
    sampled_at = now()
    checks = {}
    for family, key in ((4, "egress"), (6, "egress_ipv6")):
        sample = consistency.sample(family, {"at": sampled_at, "endpoint": consistency.ENDPOINTS[family],
                                             **before.get(key, {})})
        ip = consistency.address(sample)
        target = expected if expected and ipaddress.ip_address(expected).version == family else None
        checks[key] = {**sample, "state": "not_measured" if not ip else "observed" if not target else
                       "ok" if ip == target else "fail", "expected_ip": target}
    application_context = bool(data.get("runtime_prefix") or data["backend"] == "pvm")
    detail = ("shared Zhibi process workspace" if data.get("runtime_prefix") else
              "whole VM" if data["backend"] == "pvm" else
              "custom probe prefix; unbound to application startup" if data.get("probe_prefix") else "server host only")
    checks["application_scope"] = {"state": "ok" if application_context and before.get("execution") == "ok" else "not_measured",
                                   "detail": detail}
    checks["dns_resolution"] = before.get("dns", {"state": "not_measured"})
    checks["dns_route"] = {"state": "not_measured"}
    checks["udp"] = {"state": "not_measured"}
    checks["ipv6"] = before.get("ipv6", {"state": "not_measured"})
    checks["browser_exit"] = {"state": "not_measured"}
    if args.browser:
        from .flow import browser_readings, browser_exits
        readings = browser_readings(args.browser)
        exits = browser_exits(readings)
        for family, key, browser_key in ((4, "egress", "browser_exit"), (6, "egress_ipv6", "browser_exit_ipv6")):
            comparison = (consistency.compare(family, checks[key], exits[family]) if application_context
                          else {"state": "not_measured", "reason": "application_not_measured"})
            checks[browser_key] = {**comparison, "ip": exits[family]["ip"]}
    checks["outage"] = outage(data, before, args.disconnect_file, args.reconnect_file) if args.disconnect_file else {"state": "not_measured"}
    report = {"version": 1, "at": now(), "backend": data["backend"], "checks": checks,
              "binding_sha256": binding_fingerprint(data),
              "complete": False, "scope": "selected HTTPS endpoint and imported browser observations",
              "notice": "DNS 解析成功不证明解析路径；IPv6 sysctl 不证明无泄漏；单一 HTTPS 断网演练不覆盖所有协议。"}
    if data["backend"] == "pvm":
        from . import pvm_backend as pvm
        from types import SimpleNamespace
        report["pvm"] = pvm.dispatch(SimpleNamespace(action="audit", workspace=data["vm_workspace"], network=True))
    report["requires_attention"] = (any(item["state"] in ("fail", "error") for item in checks.values())
                                    or ("pvm" in report and not report["pvm"]["protocol_checks_passed"]))
    if args.out:
        from .project import save
        save(Path(args.out).expanduser(), json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
