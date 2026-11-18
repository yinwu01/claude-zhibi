#!/usr/bin/env python3
"""Real Linux bwrap/command-entry integration; no account or global changes."""
import json
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from zhibi.sandbox import prepare, install_entry
from zhibi import connect, project, project_audit, remote, shell_entry


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
        # Run the same shell command and audit prefix that SSH receives in production.
        start = root / 'start.sh'
        start.write_text('demo-app "a b"')
        start.chmod(0o600)
        binding = SimpleNamespace(project=str(work), state_dir=str(root / 'state'), backend='remote',
                                  host='example.org', user=None, port=None, identity=None, workdir=str(subdir),
                                  local_port=10818, command_file=str(start), resume_file=None,
                                  runtime_workspace=str(profile), no_browser_proxy=True, interactive=False,
                                  action='start', apply=False)
        project.bind(binding)
        data, _ = project.load(binding)
        assert str(profile / 'run.py') in data['runtime_prefix']
        command = []
        with patch.object(connect, 'run', side_effect=lambda options: command.extend(connect.argv(options)) or {}):
            project.run(binding)
        started = subprocess.run(['sh', '-c', command[-1]], env=env, capture_output=True, text=True, timeout=20)
        assert started.returncode == 7, started.stderr

        def execute(_target, command, timeout):
            process = subprocess.run(['sh', '-c', command], env=env, capture_output=True, text=True, timeout=timeout)
            return {'state': 'ok' if process.returncode == 0 else 'error', 'value': process.stdout}

        probe = 'import json, os; print(json.dumps(dict(execution="ok", egress={}, cwd=os.getcwd(), home=os.environ["HOME"])))'
        with patch.object(remote, 'execute', side_effect=execute), patch.object(project_audit, 'PROBE', probe):
            measured = project_audit.measure(data)
            expected_context = {key: json.loads(started.stdout)[key] for key in ('cwd', 'home')}
            assert {key: measured[key] for key in expected_context} == expected_context
            runner = profile / 'run.py'
            original = runner.read_bytes()
            runner.write_bytes(original + b'\n# changed after binding\n')
            assert hashlib.sha256(runner.read_bytes()).hexdigest() not in data['runtime_prefix']
            assert project_audit.measure(data)['execution'] == 'error'
            assert subprocess.run(['sh', '-c', command[-1]], env=env, capture_output=True, timeout=20).returncode != 0
            runner.write_bytes(original)
        # Simulate missing bwrap without modifying any system installation.
        env['PATH'] = str(profile / 'bin')
        failed = subprocess.run([entry['entry']], env=env, cwd=work, capture_output=True, timeout=20)
        assert failed.returncode == 125, failed
        activation.action = 'restore'
        with patch.dict(os.environ, HOME=str(home)):
            shell_entry.run(activation)
        assert not (home / '.profile').exists() and not (home / '.bashrc').exists()
        print(json.dumps({'status': 'passed', 'application_replacement': True,
                          'bound_start_and_probe_share_workspace': True, 'modified_runner_fails_closed': True,
                          'child_environment': True, 'literal_arguments': True,
                          'exit_status': True, 'missing_bwrap_fails_closed': True,
                          'fresh_login_shell': True, 'host_file_not_mounted': True}))


if __name__ == '__main__':
    main()
