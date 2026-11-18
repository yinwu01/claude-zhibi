#!/usr/bin/env python3
"""Real Linux bwrap/command-entry integration; no account or global changes."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from zhibi.sandbox import prepare, install_entry
from zhibi import shell_entry


def main():
    if not sys.platform.startswith('linux'):
        raise SystemExit('This integration check requires Linux and working bwrap.')
    with tempfile.TemporaryDirectory(prefix='zhibi-process-check-') as tmp:
        root = Path(tmp).resolve()
        app = root / 'application'; app.mkdir()
        work = root / 'work'; work.mkdir()
        subdir = work / 'nested'; subdir.mkdir()
        home = root / 'shell-home'; home.mkdir()
        private_file = home / 'synthetic-private'
        private_file.write_text('host only')
        profile = root / 'profile'
        prepare(profile, work, app_dir=app, timezone='America/Los_Angeles')
        entry = install_entry(profile, 'demo-app', '/opt/app/demo-app', preserve_cwd=True)
        env = dict(os.environ, HOME=str(home), ZHIBI_HOST_PRIVATE_MARKER='must-not-be-inherited')
        activation = SimpleNamespace(workspace=str(profile), name='demo-app', shell='bash',
                                     action='install', apply=True)
        with patch.dict(os.environ, HOME=str(home)):
            shell_entry.run(activation)
        program = app / 'demo-app'
        for version in ('first', 'upgraded'):
            replacement = app / 'replacement'
            replacement.write_text('#!/usr/bin/python3\n' +
                'import json, os, sys, subprocess\n' +
                'print(json.dumps({"version": ' + repr(version) +
                ', "home": os.environ.get("HOME"), "tz": os.environ.get("TZ"), "cwd": os.getcwd(),'
                ' "host_file": os.path.exists(' + repr(str(private_file)) + '),'
                ' "private": os.environ.get("ZHIBI_HOST_PRIVATE_MARKER"),'
                ' "args": sys.argv[1:], "child_home": subprocess.check_output('
                '["/bin/sh", "-c", "printf %s \\\"$HOME\\\""]).decode()}))\n'
                'sys.exit(7)\n')
            replacement.chmod(0o700)
            replacement.replace(program)
            result = subprocess.run(['bash', '-lic', shlex.join(['demo-app', 'a b', '$(literal)'])], env=env, cwd=subdir,
                                    capture_output=True, text=True, timeout=20)
            assert result.returncode == 7, (result.returncode, result.stderr)
            data = json.loads(result.stdout)
            assert data == {'version': version, 'home': '/home/app',
                            'tz': 'America/Los_Angeles', 'private': None, 'cwd': '/workspace/nested',
                            'host_file': False,
                            'args': ['a b', '$(literal)'], 'child_home': '/home/app'}, data
        # Simulate missing bwrap without modifying any system installation.
        env['PATH'] = str(profile / 'bin')
        failed = subprocess.run([entry['entry']], env=env, cwd=work, capture_output=True, timeout=20)
        assert failed.returncode == 125, failed
        activation.action = 'restore'
        with patch.dict(os.environ, HOME=str(home)):
            shell_entry.run(activation)
        assert not (home / '.profile').exists() and not (home / '.bashrc').exists()
        print(json.dumps({'status': 'passed', 'application_replacement': True,
                          'child_environment': True, 'literal_arguments': True,
                          'exit_status': True, 'missing_bwrap_fails_closed': True,
                          'fresh_login_shell': True, 'host_file_not_mounted': True}))


if __name__ == '__main__':
    main()
