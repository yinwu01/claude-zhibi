"""Export an opt-in OpenSSH profile and project details without opening an editor."""
from pathlib import Path
import shlex
import shutil

from . import remote
from .models import InputError
from .storage import create_run, write


def ssh_path(value):
    # Keep the generated paths literal, even for Include glob patterns.
    text = str(Path(value).expanduser().absolute())
    if any(ord(char) < 32 or char in '"\\$%*?[]' for char in text):
        raise InputError("SSH 路径含有配置特殊字符；请改用普通的本机路径。")
    return '"' + text + '"'


def export(out, binding):
    if binding["backend"] == "pvm":
        raise InputError("PVM 项目可直接用本机编辑器打开共享目录；独立 SSH 工作机和已有 SSH 虚拟机可导出此配置。")
    target = remote.target(**binding["target"])
    project = binding["workdir"]
    if any(ord(char) < 32 for char in project):
        raise InputError("远端项目目录含有控制字符，无法导出编辑器配置。")
    host = target["host"]
    config = [
        "Host " + host,
        "    StrictHostKeyChecking yes",
        "    ForwardAgent no",
        "    ForwardX11 no",
        "    PermitLocalCommand no",
        "    RemoteCommand none",
        "    ControlMaster no",
        "    ControlPath none",
    ]
    if target["user"] is not None:
        config.append("    User " + target["user"])
    if target["port"] is not None:
        config.append("    Port " + str(target["port"]))
    if target["identity"]:
        config.append("    IdentityFile " + ssh_path(target["identity"]))
    if target.get("ssh_config"):
        # Match the original hostname in the explicitly supplied config so
        # existing ProxyJump and known_hosts settings continue to work.
        config += ["Host *", "    Include " + ssh_path(target["ssh_config"])]
    folder = create_run(out)
    try:
        path = folder / "ssh_config"
        write(path, "\n".join(config) + "\n")
        write(folder / "editor-settings.private.json", {"remote.SSH.configFile": str(path)})
        target_host = remote.destination(target)
        shell_command = "cd -- " + shlex.quote(project) + ' && case "${SHELL##*/}" in ' \
            'bash|zsh) exec "$SHELL" -il ;; *) printf "%s\\n" "Select Bash or Zsh on the remote host." >&2; exit 2 ;; esac'
        terminal = shlex.join(["ssh", "-F", str(path), "-o", "ClearAllForwardings=yes",
                               "-tt", "--", target_host, shell_command])
        write(folder / "open-terminal.sh", "#!/bin/sh\nexec " + terminal + "\n")
        write(folder / "说明.md", "\n".join([
            "# 远程项目入口",
            "",
            "在编辑器中为支持 Remote SSH 的扩展选择此目录的 ssh_config（配置项见 editor-settings.private.json）。",
            "用 SSH 主机名连接后，打开下方项目目录。在远端集成终端按交付说明确认隔离入口，再运行应用。",
            "SSH 需要受信任的服务器主机公钥。侧重文件编辑时，从扩展界面连接即可。",
            "",
            "SSH 主机：" + host,
            "远端目录：" + project,
            "终端快捷入口：sh " + shlex.quote(str(folder / "open-terminal.sh")),
            "",
            "此导出仅用于打开项目，配置没有复制身份文件和账号凭据。",
            "撤销时先恢复编辑器里的 SSH 配置文件选项，再移除这次导出的目录。",
            "",
        ]))
    except BaseException:
        shutil.rmtree(folder)
        raise
    return {"directory": str(folder), "ssh_config": str(path), "host": host, "workdir": project,
            "terminal_launcher": str(folder / "open-terminal.sh"), "connected": False}
