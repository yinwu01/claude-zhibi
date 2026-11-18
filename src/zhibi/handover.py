"""Describe the actual launch and recovery entries without making changes."""
import json
import re
import shlex
import sys
from pathlib import Path

from . import remote
from .models import InputError
from .project import private_read


def remote_path(value):
    if not value.startswith("/") or ".." in Path(value).parts or any(ord(c) < 32 for c in value):
        raise InputError("远端交付路径必须是无控制字符的绝对路径。")
    return Path(value)


def ssh_command(target, argv):
    return shlex.join(remote.ssh_argv(target, shlex.join(argv)))


def cli_command():
    """Use the installed Skill archive when running inside it."""
    core = Path(__file__).parents[1]
    if core.is_file():
        return [sys.executable, str(core.resolve())]
    return ["env", "PYTHONPATH=" + str(core.resolve()), sys.executable, "-m", "zhibi"]


def connection_args(target):
    args = ["--host", target["host"]]
    for key, flag in (("user", "--user"), ("port", "--port"), ("identity", "--identity"), ("ssh_config", "--ssh-config")):
        if target.get(key) is not None:
            args += [flag, str(target[key])]
    return args


def browser_launcher(directory, port):
    folder = Path(directory).expanduser().absolute()
    launcher = folder / "start-browser.py"
    if any(path.is_symlink() for path in (launcher, *launcher.parents)) or not launcher.is_file():
        raise InputError("指定目录缺少知彼生成的 Chromium 启动器。")
    controls = json.loads(private_read(folder / "controls.json"))
    config = json.loads(private_read(folder / "browser.private.json"))
    if controls.get("format") != "zhibi-browser-controls-1":
        raise InputError("指定目录不是知彼生成的 Chromium 工作区。")
    if port and "--proxy-server=socks5://127.0.0.1:" + str(port) not in config.get("flags", []):
        raise InputError("Chromium 工作区使用的代理端口与本次交付的后台连接不一致。")
    return [sys.executable, str(launcher)]


def browser_service(directory, tested_port):
    folder = Path(directory).expanduser().absolute()
    manager = folder / "manage.py"
    if any(p.is_symlink() for p in (manager, *manager.parents)) or not manager.is_file():
        raise InputError("浏览器后台服务目录缺少可信的管理脚本。")
    config = json.loads(private_read(folder / "service.private.json"))
    receipt = json.loads(private_read(folder / "receipt.private.json"))
    if config.get("format") != "zhibi-connection-service-1" or receipt != {
            "target": config.get("target"), "unit_sha256": config.get("unit_sha256")}:
        raise InputError("浏览器后台服务部署回执不匹配。")
    if tested_port is not None and tested_port != config["local_port"]:
        raise InputError("验收端口与交付的浏览器后台服务不一致。")
    return {"name": config["name"], "local_port": config["local_port"]}, manager


def describe(args, target, project=None):
    browser = getattr(args, "browser_profile", None)
    browser_dir = getattr(args, "browser_service", None)
    browser_workspace = getattr(args, "browser_workspace", None)
    vm_browser = getattr(args, "vm_browser", False)
    runtime = getattr(args, "runtime_service", None)
    entry = getattr(args, "app_entry", None)
    shell = getattr(args, "shell", None)
    shell_tool = getattr(args, "remote_skill_entry", None)
    plan = {"browser_profile": browser, "app_entry": None, "launch": {}, "status": [], "rollback": []}
    vm = project.get("vm_workspace") if project and project["backend"] == "pvm" else None
    if vm_browser and not (vm and browser and not browser_workspace):
        raise InputError("VM 内浏览器需要已绑定的 PVM 项目和浏览器名称；本机 Chromium 工作区请单独交付。")
    if browser and any(ord(c) < 32 for c in browser):
        raise InputError("浏览器配置名含控制字符。")
    port = getattr(args, "proxy_port", None)
    if browser_dir:
        plan["browser_connection"], manager = browser_service(browser_dir, port)
        port = plan["browser_connection"]["local_port"]
        for action in ("status", "rollback"):
            plan[action].append(shlex.join([sys.executable, str(manager), action]))
    if browser_workspace:
        plan["launch"]["open-browser.sh"] = browser_launcher(browser_workspace, port)
    if project:
        command = cli_command() + ["project", "start", "--project", project["path"]]
        if project.get("state_dir"):
            command += ["--state-dir", project["state_dir"]]
        plan["launch"]["open-project.sh"] = command + ["--apply"]
    if vm:
        plan["vm_stop"] = shlex.join(cli_command() + ["vm", "stop", "--workspace", vm, "--apply"])
    if vm_browser:
        plan["launch"]["open-vm-desktop.sh"] = cli_command() + ["vm", "desktop", "--workspace", vm, "--apply"]
    if not target and (runtime or shell or shell_tool or (entry and not vm)):
        raise InputError("远端交付信息需要 SSH 目标；可使用已绑定的 SSH 项目。")
    if entry:
        entry = remote_path(entry)
        workspace = project.get("runtime_workspace") if project else None
        if workspace and entry.parent != Path(workspace) / "bin":
            raise InputError("交付的应用入口不在项目绑定的进程工作区中。")
        plan["app_entry"] = str(entry)
    if shell or shell_tool:
        if not (shell and shell_tool and entry and entry.parent.name == "bin"
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", entry.name)):
            raise InputError("恢复原生命令需要 --shell、--remote-skill-entry 和工作区 bin 内的 --app-entry。")
        plan["rollback"].append(ssh_command(target, [
            "python3", str(remote_path(shell_tool)), "process-activate", "restore",
            "--workspace", str(entry.parent.parent), "--name", entry.name, "--shell", shell, "--apply",
        ]))
    if runtime:
        manager = str(remote_path(runtime) / "manage.py")
        plan["runtime_manager"] = manager
        for action in ("status", "rollback"):
            plan[action].append(ssh_command(target, ["python3", manager, action]))
    return plan
