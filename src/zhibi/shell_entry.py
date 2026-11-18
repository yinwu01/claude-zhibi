"""Persist a native application command in supported user shells, reversibly."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

from .models import InputError
from .project import private_read
from .sandbox import checked_directory


def files_for(shell):
    home = Path.home()
    if shell == 'bash':
        login = next((home / n for n in ('.bash_profile', '.bash_login', '.profile') if (home / n).exists()), home / '.profile')
        return [home / '.bashrc', login]
    if shell == 'zsh':
        root = Path(os.environ.get('ZDOTDIR', str(home))).expanduser().absolute()
        return [root / '.zshrc', root / '.zprofile']
    raise InputError('持久命令入口目前支持 bash / zsh。')


def read_rc(path):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise InputError('Shell 配置不能经过符号链接；请由 Agent 检查实际目标。')
    if not path.exists():
        return ''
    if not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022:
        raise InputError('Shell 配置必须由当前用户拥有且不可由其他用户写入。')
    return path.read_text()


def write_rc(path, expected, text, existed):
    if not existed and not text:
        if read_rc(path) != expected:
            raise InputError('Shell 配置在修改期间发生变化。')
        path.unlink()
        return
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        staged = Path(stream.name)
        try:
            stream.write(text)
            stream.close()
            staged.chmod(mode)
            if read_rc(path) != expected:
                raise InputError('Shell 配置在修改期间发生变化。')
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def verify_entry(shell, name, entry):
    executable = shutil.which(shell)
    if not executable:
        raise InputError('找不到所选的 shell。')
    token = shlex.quote(name)
    # Compare the shell's normalized alias value, not the spelling used
    # when writing it. Bash and Zsh display the same alias differently.
    probe = '__zhibi_entry_check'
    assignment = shlex.quote(shlex.quote(str(entry)))
    script = (
        f'actual=$(alias {token}) && alias {probe}={assignment} && '
        f'expected=$(alias {probe}) && '
        f'[ "${{actual#*{token}=}}" = "${{expected#*{probe}=}}" ]'
    )
    try:
        done = subprocess.run([executable, '-lic', script], capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise InputError('新登录 shell 验证超时。') from None
    if done.returncode:
        raise InputError('新登录 shell 未命中包裹入口；检查同名 alias/function 或 PATH 重写。')


def run(args):
    root = checked_directory(args.workspace)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.name):
        raise InputError('应用命令名无效。')
    entry = root / 'bin' / args.name
    if args.action == 'install' and (
            not entry.is_file() or entry.is_symlink() or not os.access(entry, os.X_OK)):
        raise InputError('先创建 process-entry，再启用原生命令。')
    key = hashlib.sha256(str(entry).encode()).hexdigest()[:16]
    receipt = root / ('shell-' + key + '.private.json')
    token = shlex.quote(args.name)
    assignment = shlex.quote(shlex.quote(str(entry)))
    block = (
        f'\n# cc-zhibi {key} begin\nexport PATH={shlex.quote(str(entry.parent))}:"$PATH"\n'
        f'if ! alias {token} >/dev/null 2>&1 && ! typeset -f {token} >/dev/null 2>&1; then\n'
        f'    alias {token}={assignment}\n'
        f'fi\n# cc-zhibi {key} end\n'
    )
    paths = files_for(args.shell)
    if args.action == 'restore':
        data = json.loads(private_read(receipt))
        if data['entry'] != str(entry) or data['shell'] != args.shell or data['block'] != block:
            raise InputError('恢复记录与命令入口不符。')
        edits = []
        for item in data['files']:
            path = Path(item['path'])
            if path not in paths:
                raise InputError('Shell 配置位置已改变，未恢复。')
            text = read_rc(path)
            if text.count(block) != 1:
                raise InputError('受管理的 shell 配置块已改变，未恢复。')
            edits.append((path, text, item['existed']))
        if args.apply:
            restored = []
            try:
                for path, text, existed in edits:
                    after = text.replace(block, '', 1)
                    write_rc(path, text, after, existed)
                    restored.append((path, after, text))
            except BaseException:
                for path, after, text in reversed(restored):
                    write_rc(path, after, text, True)
                raise
            receipt.unlink()
        return {'applied': args.apply, 'restored': args.apply, 'command': args.name}
    if receipt.exists():
        data = json.loads(private_read(receipt))
        if data.get('block') != block or any(read_rc(Path(i['path'])).count(block) != 1 for i in data['files']):
            raise InputError('已保存的入口配置与现场不一致。')
        if args.apply:
            verify_entry(args.shell, args.name, entry)
        return {'applied': False, 'already_enabled': True, 'entry': str(entry),
                'fresh_shell_verified': args.apply}
    items = []
    for path in paths:
        text = read_rc(path)
        if '# cc-zhibi ' + key in text:
            raise InputError('发现无回执或已修改的配置块。')
        items.append({'path': str(path), 'existed': path.exists(), 'before': text})
    if not args.apply:
        return {'applied': False, 'entry': str(entry), 'startup_files': [str(p) for p in paths]}
    data = {'entry': str(entry), 'shell': args.shell, 'block': block,
            'files': [{k: item[k] for k in ('path', 'existed')} for item in items]}
    fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream)
    changed = []
    try:
        for item in items:
            path = Path(item['path'])
            path.parent.mkdir(parents=True, exist_ok=True)
            write_rc(path, item['before'], item['before'] + block, True)
            changed.append(item)
        verify_entry(args.shell, args.name, entry)
    except BaseException:
        for item in reversed(changed):
            path = Path(item['path'])
            current = read_rc(path)
            if current.count(block) != 1:
                raise InputError('启动文件在验证期间被修改；请根据保留的回执检查。')
            write_rc(path, current, current.replace(block, '', 1), item['existed'])
        receipt.unlink(missing_ok=True)
        raise
    return {'applied': True, 'entry': str(entry), 'fresh_shell_verified': True,
            'notice': '新终端直接输入应用名；当前已打开的 shell 需重新登录。', 'receipt': str(receipt)}


def register(sub):
    p = sub.add_parser('process-activate', help='在新登录 shell 中直接使用已包裹的原应用名')
    p.add_argument('action', choices=('install', 'restore'))
    p.add_argument('--workspace', required=True)
    p.add_argument('--name', required=True)
    p.add_argument('--shell', choices=('bash', 'zsh'), required=True)
    p.add_argument('--apply', action='store_true')
