"""Foreground SSH access: a loopback SOCKS endpoint and optional remote process."""
import os
import shlex
import subprocess
from pathlib import Path

from . import remote
from .models import InputError
from .lifecycle import foreground


def command_text(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise InputError("启动文件必须是小于 64 KiB 的普通文件。")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise InputError("启动文件权限需为 600，避免暴露命令内的私人信息。")
    text = path.read_text(encoding="utf-8")
    if not text.strip() or "\0" in text:
        raise InputError("启动文件为空或包含无效字符。")
    return text


def argv(args):
    item = remote.target(args.host, args.user, args.port, args.identity, getattr(args, "ssh_config", None))
    if not 1024 <= args.local_port <= 65535:
        raise InputError("本机端口需在 1024–65535。")
    # Reuse the SSH identity rules; no shell is involved on the local machine.
    ssh_command = remote.ssh_argv(item, "")
    base, destination = ssh_command[:-3], ssh_command[-2]
    base += ["-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
             "-o", "ServerAliveCountMax=3"]
    endpoint = getattr(args, "gateway_socket", None)
    ssh_only = getattr(args, "no_browser_proxy", False)
    if ssh_only:
        if not args.command_file or endpoint or getattr(args, "export_out", None):
            raise InputError("仅运行远端命令时需提供启动脚本，不能同时转发或导出浏览器代理。")
        base += ["-o", "ClearAllForwardings=yes"]
    elif endpoint:
        if not endpoint.startswith("/") or any(c in endpoint for c in "\0\n\r:"):
            raise InputError("远端私人网关 socket 需要不含冒号的绝对路径。")
        base += ["-L", "127.0.0.1:" + str(args.local_port) + ":" + endpoint]
    else:
        base += ["-D", "127.0.0.1:" + str(args.local_port)]
    if not args.command_file:
        return base + ["-N", "--", destination]
    text = command_text(args.command_file)
    runtime = getattr(args, "runtime_prefix", None)
    if runtime:
        text = "exec " + shlex.join([*runtime, "/bin/sh", "-e", "-c", text])
    if args.workdir:
        if not args.workdir.startswith("/") or "\0" in args.workdir:
            raise InputError("远端工作目录必须是绝对路径。")
        text = "cd -- " + shlex.quote(args.workdir) + " || exit\n" + text
    # POSIX shell semantics are explicit; unlike systemd ExecStart, pipelines work.
    command = ("sh -c " if runtime else "sh -lc ") + shlex.quote(text)
    return base + (["-tt"] if args.interactive else ["-T"]) + ["--", destination, command]


def run(args):
    command = argv(args)
    if getattr(args, "export_out", None):
        from .connection_bundle import export
        return export(args, command)
    ssh_only = getattr(args, "no_browser_proxy", False)
    plan = {"action": "connect", "host": args.host,
            "browser_proxy": None if ssh_only else {"type": "socks5", "host": "127.0.0.1", "port": args.local_port},
            "remote_process": bool(args.command_file), "interactive": args.interactive,
            "applied": False,
            "notice": "本连接只运行远端命令；浏览器由独立服务维护。" if ssh_only else
            "保持此连接运行。浏览器需使用代理解析域名；SSH SOCKS 不转发 UDP，WebRTC 必须单独配置并实测。应用出口以实际运行环境为准。"}
    if not args.apply:
        return plan
    if args.interactive and not os.isatty(0):
        raise InputError("交互进程需要终端。请由 Agent 分配 PTY，或在用户终端运行。")
    # Foreground ownership avoids orphaned tunnels and killing unrelated processes.
    try:
        status = foreground(command)
    except KeyboardInterrupt:
        status = 130
    except OSError as exc:
        raise InputError("SSH 未能启动。") from exc
    plan.update(applied=True, stopped=True, exit_status=status)
    return plan


def verify_route(args):
    from ipaddress import ip_address
    from .diagnostics import route
    if not 1024 <= args.local_port <= 65535:
        raise InputError("本机端口需在 1024–65535。")
    config = {"proxy_url": "socks5h://127.0.0.1:" + str(args.local_port)}
    family = getattr(args, "family", 4)
    if args.expected_ip:
        if ip_address(args.expected_ip).version != family:
            raise InputError("预期出口与选定地址族不一致。")
        config["expected_ip"] = args.expected_ip
    if not args.network:
        return {"attempted": False, "recipient": "api6.ipify.org" if family == 6 else "api.ipify.org",
                "local_port": args.local_port}
    return route(config, family=family)


def register(sub):
    verify = sub.add_parser("connection-check", help="通过运行中的本机 SOCKS 测出口，不回退直连")
    verify.add_argument("--local-port", type=int, default=10818)
    verify.add_argument("--family", type=int, choices=(4, 6), default=4)
    verify.add_argument("--expected-ip")
    verify.add_argument("--network", action="store_true", help="允许通过代理查询 ipify")

    p = sub.add_parser("connect", help="启动浏览器可用的本机 SOCKS 连接，可同时在 VPS 运行用户命令")
    p.add_argument("--host", required=True)
    p.add_argument("--user")
    p.add_argument("--port", type=int)
    p.add_argument("--identity")
    p.add_argument("--ssh-config", help="显式私人 SSH 配置，可配置 ProxyJump/ProxyCommand；默认不读用户配置")
    p.add_argument("--local-port", type=int, default=10818)
    forwarding = p.add_mutually_exclusive_group()
    forwarding.add_argument("--gateway-socket", help="转发服务器已有的私人 SOCKS 网关，共用应用出口")
    forwarding.add_argument("--no-browser-proxy", action="store_true", help="只运行远端命令，不创建浏览器代理")
    p.add_argument("--command-file", help="本机私人脚本文件；在远端用 sh 执行，不打印内容")
    p.add_argument("--workdir", help="远端绝对工作目录")
    p.add_argument("--interactive", action="store_true", help="为交互式进程分配远端终端")
    p.add_argument("--export-out", help="导出可独立启动的私人连接文件夹，不连接服务器")
    p.add_argument("--apply", action="store_true", help="启动前台连接；Ctrl-C 停止")
