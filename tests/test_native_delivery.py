import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from zhibi import shell_entry, connection_service, sandbox, connect
from zhibi.models import InputError


@unittest.skipUnless(os.name == 'posix', 'POSIX native command')
class ShellTests(unittest.TestCase):
    def test_fresh_shell_literal_arguments_and_reversible_rc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); home = root / 'home'; home.mkdir()
            profile = root / 'profile'; profile.mkdir(mode=0o700)
            (profile / 'run.py').write_text('import json,sys;print(json.dumps(sys.argv[1:]));sys.exit(17)\n')
            sandbox.install_entry(profile, 'native-demo', '/opt/app/demo', preserve_cwd=True)
            (home / '.bash_profile').write_text('# existing login settings\n')
            args = SimpleNamespace(workspace=str(profile), name='native-demo', shell='bash', action='install', apply=True)
            with patch.dict(os.environ, HOME=str(home)):
                result = shell_entry.run(args)
                self.assertTrue(result['fresh_shell_verified'])
                done = subprocess.run(['bash','-lic', "native-demo 'a b' '$(false)'"], cwd=home, capture_output=True, text=True)
                self.assertEqual(done.returncode, 17)
                self.assertEqual(json.loads(done.stdout), ['--cwd',str(home),'--','/opt/app/demo','a b','$(false)'])
                with (home / '.bash_profile').open('a') as f:f.write('# later user settings\n')
                (profile / 'bin' / args.name).unlink()
                alternate = home / 'native-demo'
                alternate.write_text('#!/bin/sh\nprintf unsafe-fallback\n')
                alternate.chmod(0o700)
                result = subprocess.run(
                    ['bash', '-lic', 'PATH="$HOME:$PATH"; native-demo'],
                    cwd=home, capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('unsafe-fallback', result.stdout)
                args.action='restore'; shell_entry.run(args)
                self.assertEqual((home / '.bash_profile').read_text(), '# existing login settings\n# later user settings\n')
                self.assertFalse((home / '.bashrc').exists())

    def test_alias_collision_rolls_back_only_own_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();home=root/'home';home.mkdir();profile=root/'profile';profile.mkdir(mode=0o700)
            (profile/'run.py').write_text('pass\n');sandbox.install_entry(profile,'native-demo','/bin/true')
            original="alias native-demo='echo existing'\n";(home/'.bash_profile').write_text(original)
            args=SimpleNamespace(workspace=str(profile),name='native-demo',shell='bash',action='install',apply=True)
            with patch.dict(os.environ,HOME=str(home)),self.assertRaises(InputError):shell_entry.run(args)
            self.assertEqual((home/'.bash_profile').read_text(),original)
            self.assertFalse((home/'.bashrc').exists())

    def test_cwd_mapped_only_within_configured_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();work=root/'work';work.mkdir();(work/'sub dir').mkdir()
            sandbox.prepare(root/'profile',work)
            with patch('sys.platform','linux'),patch('shutil.which',return_value='/usr/bin/bwrap'):
                argv=sandbox.command(root/'profile',['/bin/pwd'],str(work/'sub dir'))
                self.assertEqual(argv[argv.index('--chdir')+1],'/workspace/sub dir')
                with self.assertRaises(ValueError):sandbox.command(root/'profile',['/bin/pwd'],str(root))


    def test_stale_gateway_stops_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            endpoint = root / 'gateway.sock'
            binary = root / 'proxy'
            binary.write_bytes(b'test fixture')
            binary.chmod(0o700)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(endpoint))
                sandbox.prepare(root / 'profile', root, network='proxy', graftcp=binary,
                                graftcp_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                                proxy_socket=endpoint)
            self.assertTrue(endpoint.is_socket())
            with patch('sys.platform', 'linux'), patch('shutil.which', return_value='/usr/bin/bwrap'):
                with self.assertRaisesRegex(ValueError, '网关未就绪'):
                    sandbox.command(root / 'profile', ['/bin/true'])


@unittest.skipUnless(os.name == 'posix', 'POSIX user services')
class ConnectionTests(unittest.TestCase):
    def args(self,root):
        return SimpleNamespace(host='example.com',user='dev',port=22,identity=None,ssh_config=None,
            local_port=10819,gateway_socket='/private/gateway.sock',name='zhibi-test',out=str(root/'service'))

    def test_private_forward_and_no_control_master(self):
        with tempfile.TemporaryDirectory() as tmp,patch('platform.system',return_value='Darwin'):
            root=Path(tmp).resolve();result=connection_service.export(self.args(root))
            data=connection_service.private_json(Path(result['directory'])/'service.private.json')
            self.assertIn('127.0.0.1:10819:/private/gateway.sock',data['argv'])
            self.assertNotIn('-D',data['argv']);self.assertIn('ControlMaster=no',data['argv'])
            self.assertEqual((Path(result['directory'])/'service.private.json').stat().st_mode&0o777,0o600)

    def test_occupied_port_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp,patch('platform.system',return_value='Darwin'):
            root=Path(tmp).resolve();a=self.args(root)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));a.local_port=sock.getsockname()[1]
                result=connection_service.export(a);folder=Path(result['directory']);data=connection_service.private_json(folder/'service.private.json')
                data['target']=str(root/'target.plist')
                with patch.object(connection_service,'status',return_value={'loaded':False}), self.assertRaises(OSError):
                    connection_service.install(folder,data)
                self.assertFalse((root/'target.plist').exists());self.assertFalse((folder/'receipt.private.json').exists())

    def test_modified_unit_is_not_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();target=root/'test';target.write_text('changed')
            data={'target':str(target),'unit_sha256':'original','name':'zhibi-test'}
            connection_service.write_private(root/'receipt.private.json',json.dumps({'target':str(target),'unit_sha256':'original'}).encode())
            with self.assertRaises(ValueError):connection_service.rollback(root,data)
            self.assertEqual(target.read_text(),'changed')
