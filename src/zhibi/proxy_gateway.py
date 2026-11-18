"""Private Unix SOCKS5 gateway with direct or explicitly chained TCP egress.

No public listener, destination logging or UDP relay.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import select
import signal
import socket
import socketserver
import stat
import struct
import threading
from contextlib import ExitStack


def exact(sock, count):
    value = b''
    while len(value) < count:
        chunk = sock.recv(count - len(value))
        if not chunk:
            raise EOFError()
        value += chunk
    return value


def connect_ipv4(host, port):
    """Resolve only A records and never fall back to IPv6 (including literals)."""
    error = OSError('No IPv4 address available')
    for family, kind, proto, _, address in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        target = socket.socket(family, kind, proto)
        try:
            target.settimeout(15)
            target.connect(address)
            return target
        except OSError as exc:
            error = exc
            target.close()
    raise error


def load_upstream(path):
    """Read a bounded, owner-only configuration without exposing its values."""
    fd = os.open(Path(path).expanduser(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r', encoding='utf-8') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Upstream configuration must be an owner-only regular file.')
        if info.st_size > 4096:
            raise ValueError('Upstream configuration is too large.')
        text = source.read(4097)
    if len(text) > 4096:
        raise ValueError('Upstream configuration is too large.')
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) - {'type', 'host', 'port', 'username', 'password'}:
        raise ValueError('Invalid upstream configuration fields.')
    host, port = value.get('host'), value.get('port')
    if (value.get('type') != 'socks5' or not isinstance(host, str) or not host or len(host) > 253
            or not all(c.isascii() and (c.isalnum() or c in '.-') for c in host)
            or type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('Upstream must specify a SOCKS5 host and port.')
    credentials = None
    if {'username', 'password'} & value.keys():
        pair = (value.get('username'), value.get('password'))
        if any(not isinstance(item, str) or not 1 <= len(item.encode('utf-8')) <= 255 for item in pair):
            raise ValueError('Upstream needs both valid username and password fields.')
        credentials = tuple(item.encode('utf-8') for item in pair)
    return host, port, credentials


def open_upstream(config):
    host, port, credentials = config
    target = connect_ipv4(host, port)
    try:
        method = b'\x02' if credentials else b'\x00'
        target.sendall(b'\x05\x01' + method)
        if exact(target, 2) != b'\x05' + method:
            raise OSError('Upstream rejected the selected SOCKS method.')
        if credentials:
            user, password = credentials
            target.sendall(b'\x01' + bytes([len(user)]) + user + bytes([len(password)]) + password)
            if exact(target, 2) != b'\x01\x00':
                raise OSError('Upstream authentication failed.')
        return target
    except BaseException:
        target.close()
        raise


def upstream_connect(target, address, port):
    # Forward the request address verbatim. For domain requests the upstream
    # resolves it; this VPS only resolves the upstream server's own name.
    target.sendall(b'\x05\x01\x00' + address + port)
    version, result, reserved, kind = exact(target, 4)
    if (version, result, reserved) != (5, 0, 0):
        raise OSError('Upstream refused the destination.')
    if kind == 1:
        length = 4
    elif kind == 3:
        length = exact(target, 1)[0]
    elif kind == 4:
        length = 16
    else:
        raise OSError('Invalid upstream address type.')
    exact(target, length + 2)


def relay(left, right):
    readers = [left, right]
    while readers:
        ready, _, _ = select.select(readers, [], [], 600)
        if not ready:
            return
        for source in ready:
            target = right if source is left else left
            data = source.recv(65536)
            if data:
                target.sendall(data)
            else:
                readers.remove(source)
                try:
                    target.shutdown(socket.SHUT_WR)
                except OSError:
                    pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(15)
        with ExitStack() as resources:
            stage = 'greeting'
            try:
                version, count = exact(client, 2)
                if version != 5:
                    return
                if 0 not in exact(client, count):
                    client.sendall(b'\x05\xff')
                    return
                # A readiness handshake must fail when the selected upstream is unavailable.
                target = resources.enter_context(open_upstream(self.server.upstream)) if self.server.upstream else None
                client.sendall(b'\x05\x00')
                stage = 'request'
                version, command, reserved, kind = exact(client, 4)
                if version != 5 or command != 1 or reserved != 0:
                    client.sendall(b'\x05\x07\x00\x01' + b'\x00' * 6)
                    return
                if kind == 1:
                    raw = exact(client, 4)
                    address = b'\x01' + raw
                    host = socket.inet_ntop(socket.AF_INET, raw)
                elif kind == 3:
                    raw = exact(client, exact(client, 1)[0])
                    host = raw.decode('ascii')
                    if not host or '\0' in host or ':' in host:
                        raise ValueError('Invalid destination name.')
                    address = bytes([3, len(raw)]) + raw
                else:
                    client.sendall(b'\x05\x08\x00\x01' + b'\x00' * 6)
                    return
                port = exact(client, 2)
                if target is None:
                    target = resources.enter_context(connect_ipv4(host, struct.unpack('!H', port)[0]))
                else:
                    upstream_connect(target, address, port)
                bound, bound_port = target.getsockname()[:2]
                client.sendall(b'\x05\x00\x00\x01' + socket.inet_aton(bound) + struct.pack('!H', bound_port))
                stage = 'relay'
                client.settimeout(30)
                target.settimeout(30)
                relay(client, target)
            except (OSError, EOFError, ValueError, UnicodeError):
                failure = {'greeting': b'\x05\xff', 'request': b'\x05\x01\x00\x01' + b'\x00' * 6}.get(stage)
                if failure:
                    try:
                        client.sendall(failure)
                    except OSError:
                        pass


class Gateway(socketserver.ThreadingMixIn, getattr(socketserver, 'UnixStreamServer', socketserver.TCPServer)):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, path, upstream=None):
        if not hasattr(os, 'getuid'):
            raise ValueError('Unix gateway requires a POSIX system.')
        self.path = Path(path).expanduser().absolute()
        parent = self.path.parent
        if (not parent.is_dir() or any(p.is_symlink() for p in (parent, *parent.parents))
                or parent.stat().st_uid != os.getuid() or parent.stat().st_mode & 0o077):
            raise ValueError('Socket parent must be an existing owner-only directory without symlink ancestors.')
        if self.path.exists() or self.path.is_symlink():
            raise FileExistsError('Socket path already exists; inspect the old gateway before removing it.')
        self.slots = threading.BoundedSemaphore(64)
        self.upstream = upstream
        self.inode = None
        super().__init__(str(self.path), Handler)
        self.inode = self.path.stat().st_ino
        self.path.chmod(0o600)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def server_close(self):
        super().server_close()
        if self.inode is not None:
            try:
                if self.path.lstat().st_ino == self.inode:
                    self.path.unlink()
            except FileNotFoundError:
                pass


def serve(path, upstream_file=None):
    upstream = load_upstream(upstream_file) if upstream_file else None
    def stop(signum, frame):
        raise SystemExit(0)
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with Gateway(path, upstream) as server:
            for sig in previous:
                signal.signal(sig, stop)
            print(json.dumps({'status': 'ready', 'socket': str(server.path),
                              'egress': 'upstream-socks5' if upstream else 'server-existing-route',
                              'protocol': 'SOCKS5 CONNECT', 'client_ipv6_literals': 'disabled',
                              'ipv6': 'upstream-controlled' if upstream else 'disabled'}), flush=True)
            server.serve_forever(poll_interval=0.2)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--upstream-file')
    args = parser.parse_args()
    try:
        serve(args.socket, args.upstream_file)
    except (OSError, ValueError):
        parser.exit(2, 'Gateway could not start. Check the private socket and upstream configuration.\n')
