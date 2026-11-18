"""Private, persistent browser connection using launchd or systemd user services."""
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import time


def private_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('Expected an owner-only regular configuration file.')
    return json.loads(path.read_text())


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def unit_arg(text):
    if any(c in text for c in '\0\n\r'):
        raise ValueError('Invalid service argument.')
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def export(args):
    from . import connect
    from importlib.resources import files
    system = platform.system()
    if system not in ('Darwin', 'Linux'):
        raise ValueError('Persistent browser connection currently supports macOS and Linux.')
    if not re.fullmatch(r'zhibi-[a-zA-Z0-9][a-zA-Z0-9-]{0,50}', args.name):
        raise ValueError('Choose a unique zhibi- service name.')
    gateway_socket = getattr(args, 'gateway_socket', None)
    if bool(gateway_socket) == getattr(args, 'vps_egress', False):
        raise ValueError('Choose a private gateway socket or the VPS existing egress explicitly.')
    from argparse import Namespace
    connection = Namespace(**vars(args))
    connection.command_file = None
    connection.workdir = None
    connection.interactive = False
    argv = connect.argv(connection)
    # An independent process, never a shared SSH control master.
    argv[1:1] = ['-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                 '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no', '-o', 'RequestTTY=no']
    root = Path(args.out).expanduser().absolute()
    if any(p.is_symlink() for p in root.parents):
        raise ValueError('Service directory cannot contain symlink ancestors.')
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    label = 'io.cc-zhibi.' + args.name
    if system == 'Darwin':
        target = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
        content = plistlib.dumps({'Label': label, 'ProgramArguments': argv, 'RunAtLoad': True,
            'KeepAlive': True, 'ThrottleInterval': 5, 'ExitTimeOut': 10,
            'StandardOutPath': str(root / 'connection.log'), 'StandardErrorPath': str(root / 'connection.log')})
    else:
        target = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user' / (args.name + '.service')
        content = ('[Unit]\nDescription=cc-zhibi persistent browser connection\n'
            '[Service]\nExecStart=' + ' '.join(unit_arg(x) for x in argv)
            + '\nRestart=always\nRestartSec=5\nUMask=0077\nKillMode=control-group\n'
              '[Install]\nWantedBy=default.target\n').encode()
    source = root / target.name
    write_private(source, content)
    config = {'format': 'zhibi-connection-service-1', 'system': system, 'label': label,
        'name': args.name, 'target': str(target), 'source': source.name,
        'unit_sha256': hashlib.sha256(content).hexdigest(), 'local_port': args.local_port,
        'gateway_socket': gateway_socket, 'argv': argv}
    write_private(root / 'service.private.json', json.dumps(config).encode())
    write_private(root / 'manage.py', files('zhibi').joinpath('connection_service.py').read_bytes())
    return {'directory': str(root), 'manager': str(root / 'manage.py'), 'installed': False,
            'proxy': {'type': 'socks5', 'host': '127.0.0.1', 'port': args.local_port},
            'egress': 'private-gateway' if gateway_socket else 'vps-existing-route',
            'notice': '安装后随用户登录启动并自动重连。保存至浏览器后，核验实际出口与断线行为。'}


def run_cmd(argv, check=True):
    return subprocess.run(argv, check=check, capture_output=True, text=True, timeout=30)


def job(config):
    return 'gui/' + str(os.getuid()) + '/' + config['label']


def status(config):
    if config['system'] == 'Darwin':
        result = run_cmd(['launchctl', 'print', job(config)], False)
        match = re.search(r'^\s*pid = (\d+)$', result.stdout, re.M)
        pid = int(match.group(1)) if match else 0
        loaded = result.returncode == 0
    else:
        result = run_cmd(['systemctl', '--user', 'show', config['name'], '-p', 'LoadState,MainPID'], False)
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        pid = int(fields.get('MainPID', '0'))
        loaded = fields.get('LoadState') not in (None, 'not-found')
    ready = False
    if pid:
        try:
            with socket.create_connection(('127.0.0.1', config['local_port']), timeout=2) as sock:
                sock.sendall(b'\x05\x01\x00')
                data = b''
                while len(data) < 2:
                    part = sock.recv(2 - len(data))
                    if not part: break
                    data += part
                ready = data == b'\x05\x00'
        except OSError:
            pass
    return {'loaded': loaded, 'pid': pid, 'proxy_ready': ready,
            'network_verified': False, 'local_port': config['local_port']}


def validate_target(config):
    path = Path(config['target'])
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Service target cannot contain symlinks.')
    return path


def rollback(root, config):
    receipt_path = root / 'receipt.private.json'
    receipt = private_json(receipt_path)
    if receipt != {'target': config['target'], 'unit_sha256': config['unit_sha256']}:
        raise ValueError('Deployment receipt does not match.')
    target = validate_target(config)
    exists = target.exists()
    if exists and hashlib.sha256(target.read_bytes()).hexdigest() != config['unit_sha256']:
        raise ValueError('Service changed after installation; refusing to remove it.')
    loaded = status(config)['loaded']
    if not exists and loaded:
        raise ValueError('Service is still loaded but its unit is missing; inspect it before removing the receipt.')
    if exists:
        if config['system'] == 'Darwin':
            if loaded:
                run_cmd(['launchctl', 'bootout', job(config)])
        else:
            if loaded:
                extra = run_cmd(['systemctl', '--user', 'show', config['name'], '-p', 'DropInPaths', '--value']).stdout.strip()
                if extra:
                    raise ValueError('Service has new drop-ins; refusing to change it.')
                run_cmd(['systemctl', '--user', 'disable', '--now', config['name']])
        target.unlink()
        if config['system'] == 'Linux':
            run_cmd(['systemctl', '--user', 'daemon-reload'])
    receipt_path.unlink()
    return {'removed': True, 'name': config['name']}


def install(root, config):
    target = validate_target(config)
    if target.exists() or status(config)['loaded'] or (root / 'receipt.private.json').exists():
        raise ValueError('Existing service or receipt found; do not replace it.')
    # Refuse an occupied proxy port rather than claim someone else's endpoint.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', config['local_port']))
    source = root / config['source']
    content = source.read_bytes()
    if source.is_symlink() or hashlib.sha256(content).hexdigest() != config['unit_sha256']:
        raise ValueError('Generated service changed.')
    if config['system'] == 'Linux':
        run_cmd(['systemctl', '--user', 'show-environment'])
        run_cmd(['systemd-analyze', '--user', 'verify', str(source)])
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt = root / 'receipt.private.json'
    write_private(receipt, json.dumps({'target': str(target), 'unit_sha256': config['unit_sha256']}).encode())
    created = False
    try:
        write_private(target, content)
        created = True
        if config['system'] == 'Darwin':
            run_cmd(['launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(target)])
        else:
            run_cmd(['systemctl', '--user', 'daemon-reload'])
            run_cmd(['systemctl', '--user', 'enable', '--now', config['name']])
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            state = status(config)
            if state['proxy_ready']:
                return dict(state, installed=True)
            time.sleep(0.5)
        raise ValueError('Connection did not become ready; new service rolled back.')
    except BaseException:
        if created:
            rollback(root, config)
        else:
            receipt.unlink(missing_ok=True)
        raise


def register(sub):
    p = sub.add_parser('connection-service', help='导出随登录启动、自动重连的浏览器私人连接服务')
    p.add_argument('--host', required=True)
    p.add_argument('--user')
    p.add_argument('--port', type=int)
    p.add_argument('--identity')
    p.add_argument('--ssh-config')
    p.add_argument('--local-port', type=int, default=10818)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--gateway-socket', help='与应用共用的远端私人 SOCKS 网关 socket')
    mode.add_argument('--vps-egress', action='store_true', help='仅浏览器时使用 VPS 的现有出口')
    p.add_argument('--name', required=True)
    p.add_argument('--out', required=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'status', 'rollback'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    config = private_json(root / 'service.private.json')
    if config.get('format') != 'zhibi-connection-service-1' or config['system'] != platform.system():
        raise SystemExit('Service configuration does not match this platform.')
    result = {'install': lambda: install(root, config), 'status': lambda: status(config),
              'rollback': lambda: rollback(root, config)}[args.action]()
    print(json.dumps(result, indent=2))
