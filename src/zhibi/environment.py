"""Private workflow checkpoints and the delivery-time network reference."""
import hashlib
import json
import time
import uuid
from pathlib import Path

from . import consistency
from .models import InputError, now
from .project import private_read, state_root
from .storage import create_run, write

FILENAME = "environment.private.json"
WORKFLOW = "zhibi-workflow-1"
DELIVERY = "zhibi-delivery-1"
NEXT = {
    "start": "在实际环境执行 check 或 session。",
    "check": "按选定路线配置，或验收已有环境。",
    "session": "保留浏览器导出文件；配置好后重新采集并验收。",
    "configure": "根据已记录的配置目录确认运行入口，再运行 accept。",
    "build": "核对配置结果，再运行 accept。",
    "browse": "在实际浏览器重新采集，然后运行 accept。",
    "accept": "通过后运行 deliver；有异常或未测项先看验收报告。",
    "deliver": "查看交付目录的先读我.md；用同目录的 reproduce.sh 复查。",
}


def load(folder):
    folder = Path(folder).expanduser().absolute()
    if folder.is_symlink() or not folder.is_dir():
        raise InputError("指定已有的知彼环境目录。")
    folder = folder.resolve(strict=True)
    state_root(folder)  # Existing, privately owned directory.
    path = folder / FILENAME
    state = json.loads(private_read(path))
    if not isinstance(state, dict) or state.get("format") not in (WORKFLOW, DELIVERY):
        raise InputError("不是受支持的知彼环境记录。")
    return folder, state


def workflow(folder):
    path, state = load(folder)
    if state["format"] != WORKFLOW:
        raise InputError("请使用 environment init 创建的过程目录记录步骤。")
    return path


def record(folder, step, result):
    verification = result.get("verification", {}).get("state") or result.get("status")
    if step == "build":
        verification = "applied" if result.get("applied") else "plan_or_incomplete"
    # Keep paths and step outcomes. Never copy configuration or evidence into these records.
    entry = {"step": step, "at": now(), "result": verification, "artifact": result.get("directory")}
    if result.get("route"):
        entry["route"] = result["route"]
    nonce = uuid.uuid4().hex
    transient = folder / (".record-" + nonce)
    write(transient, entry)
    transient.rename(folder / f"event-{time.time_ns():020d}-{nonce}.json")


def dispatch(args):
    if args.action == "init":
        folder = create_run(args.folder)
        state = {"format": WORKFLOW, "route": args.route, "at": now(), "stage": "start"}
        write(folder / FILENAME, state)
    else:
        folder, state = load(args.folder)
    if args.action == "checkpoint":
        if state["format"] != WORKFLOW:
            raise InputError("交付记录已固定；请在过程目录添加配置记录。")
        artifact = Path(args.artifact).expanduser().resolve(strict=True)
        record(folder, "configure", {"status": "declared", "directory": str(artifact), "route": args.route})
    if state["format"] == DELIVERY:
        return {"directory": str(folder), **state, "next": NEXT["deliver"]}
    events = [json.loads(private_read(path)) for path in sorted(folder.glob("event-*.json"))]
    stage = events[-1]["step"] if events else state["stage"]
    route = next((entry["route"] for entry in reversed(events) if "route" in entry), state["route"])
    return {"directory": str(folder), "route": route, "stage": stage,
            "next": NEXT[stage], "events": events}


def register(sub):
    parser = sub.add_parser("environment", help="保存或查看本机流程进度")
    actions = parser.add_subparsers(dest="action", required=True)
    start = actions.add_parser("init", help="创建私人过程记录目录")
    start.add_argument("--folder", required=True)
    start.add_argument("--route", required=True, choices=("web", "remote", "pvm", "undecided"))
    actions.add_parser("status", help="从过程记录或交付目录恢复上下文").add_argument("--folder", required=True)
    checkpoint = actions.add_parser("checkpoint", help="记录实际完成的配置，引用已有本机文件或目录")
    checkpoint.add_argument("--folder", required=True)
    checkpoint.add_argument("--artifact", required=True)
    checkpoint.add_argument("--route", choices=("web", "remote", "pvm"))


def scope_key(project, target, port, browser):
    value = json.dumps([project, target, port, browser], sort_keys=True).encode()
    return hashlib.sha256(value).hexdigest()


def addresses(network):
    return {f"{side}:IPv{row['family']}": ip for row in network.get("rows", [])
            for side in ("browser", "runtime") if (ip := consistency.address(row[side]))}


def manifest(report, policy):
    request = report["acceptance_request"]
    audit = report.get("project_audit", {})
    project = report.get("project_context", {})
    route = project.get("backend") or ("web" if request["browser"] else "remote")
    state = report.get("verification", {}).get("state")
    network = report.get("network_consistency", {})
    return {"format": DELIVERY, "route": route, "stage": "deliver", "at": report.get("at"),
            "verification": state, "exit_policy": policy,
            "scope_sha256": scope_key(audit.get("binding_sha256"), report["connection"],
                                      request["proxy_port"], request["browser"]),
            "browser_required": request["browser"],
            "baseline": addresses(network) if state == "ok" else {},
            "launch": sorted(report["handover"]["launch"]), "recheck": "reproduce.sh"}


def baseline(folder, expected_scope):
    _, state = load(folder)
    if state["format"] != DELIVERY or state.get("scope_sha256") != expected_scope:
        raise InputError("环境记录与当前复查的浏览器或运行环境范围不一致。")
    return state


def drift(saved, network):
    actual = addresses(network)
    fixed = saved["exit_policy"] == "fixed"
    labels = {"browser": "浏览器", "runtime": "运行环境"}
    result = []
    for key, before in saved["baseline"].items():
        side, family = key.split(":", 1)
        after = actual.get(key)
        state = ("not_measured" if not after else "ok" if after == before else "fail" if fixed else "warn")
        result.append({"key": f"{labels[side]} {family} 出口历史对照", "measured": after,
                       "expected": before, "state": state, "required": fixed})
    return result
