import os
from pathlib import Path
import socket
import socketserver
import struct
import tempfile
import threading
import unittest

from zhibi.proxy_gateway import Gateway, exact, connect_ipv4
from unittest.mock import patch


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        data = bytearray()
        while True:
            chunk = self.request.recv(65536)
            if not chunk:
                break
            data.extend(chunk)
        self.request.sendall(bytes(data)[::-1])


@unittest.skipUnless(hasattr(os, 'getuid') and hasattr(socket, 'AF_UNIX'), 'Unix sockets')
class GatewayTests(unittest.TestCase):
    def test_large_transfer_half_close_private_socket_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / 'proxy.sock'
            with socketserver.TCPServer(('127.0.0.1', 0), Echo) as destination, Gateway(path) as gateway:
                threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (destination, gateway)]
                for thread in threads:
                    thread.start()
                try:
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    with self.assertRaises(FileExistsError):
                        Gateway(path)
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(5); client.connect(str(path))
                        client.sendall(b'\x05\x01\x00')
                        self.assertEqual(exact(client, 2), b'\x05\x00')
                        client.sendall(b'\x05\x01\x00\x03\x09localhost' + struct.pack('!H', destination.server_address[1]))
                        self.assertEqual(exact(client, 4), b'\x05\x00\x00\x01')
                        exact(client, 6)
                        data = bytes(range(256)) * 1024
                        client.sendall(data); client.shutdown(socket.SHUT_WR)
                        self.assertEqual(exact(client, len(data)), data[::-1])
                        self.assertEqual(client.recv(1), b'')
                finally:
                    destination.shutdown(); gateway.shutdown()
                    for thread in threads:
                        thread.join(timeout=5)
            self.assertFalse(path.exists())

    def test_public_parent_refused_without_touching_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); root.chmod(0o755)
            try:
                with self.assertRaises(ValueError):
                    Gateway(root / 'proxy.sock')
                self.assertFalse((root / 'proxy.sock').exists())
            finally:
                root.chmod(0o700)

    def test_ipv6_socks_requests_rejected_before_connect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / 'proxy.sock'
            with Gateway(path) as gateway:
                thread = threading.Thread(target=gateway.serve_forever, daemon=True); thread.start()
                try:
                    with patch('zhibi.proxy_gateway.connect_ipv4', side_effect=AssertionError('connected')):
                        with socket.socket(socket.AF_UNIX) as client:
                            client.settimeout(5); client.connect(str(path)); client.sendall(b'\x05\x01\x00')
                            exact(client, 2)
                            client.sendall(b'\x05\x01\x00\x04' + socket.inet_pton(socket.AF_INET6, '::1') + struct.pack('!H', 443))
                            self.assertEqual(exact(client, 10), b'\x05\x08\x00\x01' + b'\x00' * 6)
                finally:
                    gateway.shutdown(); thread.join(timeout=5)

    def test_ipv6_literal_in_domain_cannot_bypass_policy(self):
        with self.assertRaises(OSError):
            connect_ipv4('::1', 443)

    def test_authenticated_upstream_resolves_destination_itself(self):
        case = self
        address = b'\x03\x0fexample.invalid'

        class Upstream(socketserver.BaseRequestHandler):
            def handle(self):
                client = self.request
                client.settimeout(3)
                case.assertEqual(exact(client, 3), b'\x05\x01\x02')
                client.sendall(b'\x05\x02')
                case.assertEqual(exact(client, 9), b'\x01\x03foo\x03bar')
                client.sendall(b'\x01\x00')
                request = b'\x05\x01\x00' + address + b'\x01\xbb'
                case.assertEqual(exact(client, len(request)), request)
                client.sendall(b'\x05\x00\x00\x03\x04edge\x00\x00')
                case.assertEqual(exact(client, 4), b'ping')
                client.sendall(b'pong')

        with tempfile.TemporaryDirectory() as tmp, socketserver.TCPServer(('127.0.0.1', 0), Upstream) as upstream:
            path = Path(tmp).resolve() / 'proxy.sock'
            with Gateway(path, (*upstream.server_address, (b'foo', b'bar'))) as gateway:
                servers = (upstream, gateway)
                threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
                for thread in threads:
                    thread.start()
                try:
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(3)
                        client.connect(str(path))
                        client.sendall(b'\x05\x01\x00')
                        self.assertEqual(exact(client, 2), b'\x05\x00')
                        client.sendall(b'\x05\x01\x00' + address + b'\x01\xbb')
                        self.assertEqual(exact(client, 4), b'\x05\x00\x00\x01')
                        exact(client, 6)
                        client.sendall(b'ping')
                        self.assertEqual(exact(client, 4), b'pong')
                finally:
                    for server in servers:
                        server.shutdown()
                    for thread in threads:
                        thread.join(timeout=5)

    def test_upstream_failure_cannot_fall_back_to_direct(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / 'proxy.sock'
            with Gateway(path, ('127.0.0.1', 1080, None)) as gateway:
                thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                thread.start()
                try:
                    with patch('zhibi.proxy_gateway.open_upstream', side_effect=OSError('unavailable')), \
                            patch('zhibi.proxy_gateway.connect_ipv4', side_effect=AssertionError('unexpected direct connection')):
                        with socket.socket(socket.AF_UNIX) as client:
                            client.settimeout(3)
                            client.connect(str(path))
                            client.sendall(b'\x05\x01\x00')
                            self.assertEqual(exact(client, 2), b'\x05\xff')
                            self.assertEqual(client.recv(1), b'')
                finally:
                    gateway.shutdown()
                    thread.join(timeout=5)
