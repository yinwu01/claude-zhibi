"""Exercise the exported macOS service against disposable loopback SSH and HTTP."""
import functools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from zhibi import browser_workspace, connection_service


MARKER = b"zhibi-local-fixture"


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(MARKER)


def poll(predicate, message):
    for _ in range(50):
        if predicate():
            return
        time.sleep(0.2)
    raise AssertionError(message)


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def spawn(argv, log):
    return subprocess.Popen(argv, stdout=log, stderr=log, start_new_session=True)


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def browser_read(root, args, url):
    binary = os.environ.get("CHROME_PATH")
    if not binary:
        return None
    profile = root / "browser"
    if not profile.exists():
        browser_workspace.create(SimpleNamespace(browser_binary=binary, local_port=args.local_port, out=str(profile)))
    flags = json.loads((profile / "browser.private.json").read_text())["flags"]
    argv = [binary, "--headless=new", "--disable-gpu", "--use-mock-keychain", "--timeout=6000",
            "--disable-background-networking",
            "--disable-component-update", "--host-resolver-rules=EXCLUDE 127.0.0.1, MAP * ~NOTFOUND",
            "--user-data-dir=" + str(profile / "profile"), *flags,
            # Treat the loopback fixture like an ordinary external URL for this test.
            "--proxy-bypass-list=<-loopback>", "--dump-dom", url]
    chrome = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        try:
            dom, stderr = chrome.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stop(chrome)
            dom, stderr = chrome.communicate(timeout=3)
        if MARKER in dom:
            return True
        if re.search(rb'"errorCode"\s*:\s*"ERR_[A-Z_]+"', dom):
            return False
        raise AssertionError(("browser did not report either a page or a network error",
                              re.findall(rb'ERR_[A-Z_]+', dom), stderr[-500:]))
    finally:
        stop(chrome)


def verify(root):
    for name in ("host", "identity"):
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f",
                        str(root / name)], check=True)
    ssh_port = port()
    host_key = (root / "host.pub").read_text().split()[:2]
    (root / "known_hosts").write_text(f"[127.0.0.1]:{ssh_port} " + " ".join(host_key) + "\n")
    client_path = root / "ssh_config"
    client_path.write_text(f"UserKnownHostsFile {root}/known_hosts\nStrictHostKeyChecking yes\n"
                           "IdentitiesOnly yes\nIdentityAgent none\n")
    client_path.chmod(0o600)
    server_path = root / "sshd_config"
    server_path.write_text(f"HostKey {root}/host\nListenAddress 127.0.0.1\nPort {ssh_port}\n"
                           f"AuthorizedKeysFile {root}/identity.pub\nPidFile {root}/pid\n"
                           "StrictModes no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n"
                           "AllowTcpForwarding yes\nAllowStreamLocalForwarding yes\n")
    endpoint = str(root / "gw.sock")
    with (root / "run.log").open("wb") as log, ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler) as http:
        thread = threading.Thread(target=http.serve_forever)
        thread.start()
        url = f"http://127.0.0.1:{http.server_port}/notice"
        server = spawn(["/usr/sbin/sshd", "-D", "-e", "-f", str(server_path)], log)
        start_gateway = functools.partial(spawn, [sys.executable, "-m", "zhibi.proxy_gateway", "--socket", endpoint], log)
        gateway = start_gateway()
        try:
            poll(lambda: Path(endpoint).is_socket(), "private gateway did not start")
            for web_only in (True, False):
                kind = "web" if web_only else "shared"
                home = root / kind
                home.mkdir()
                args = SimpleNamespace(host="127.0.0.1", user=pwd.getpwuid(os.getuid()).pw_name,
                    port=ssh_port, identity=str(root / "identity"), ssh_config=str(client_path),
                    local_port=port(), gateway_socket=None if web_only else endpoint,
                    vps_egress=web_only, name=f"zhibi-test-{os.getpid()}-{kind}", out=str(home / "service"))
                with patch("pathlib.Path.home", return_value=home):
                    exported = connection_service.export(args)
                directory = Path(exported["directory"])
                config = connection_service.private_json(directory / "service.private.json")

                def manage(action):
                    return subprocess.run([sys.executable, "-I", exported["manager"], action],
                                          check=True, text=True, capture_output=True, timeout=55)

                def read():
                    proc = subprocess.run(["/usr/bin/curl", "-q", "-fsS", "--max-time", "3",
                                           "--noproxy", "", "--proxy", exported["proxy"]["type"] + "h://127.0.0.1:" +
                                           str(args.local_port), url], capture_output=True, timeout=5)
                    return proc.returncode == 0 and proc.stdout == MARKER

                try:
                    state = json.loads(manage("install").stdout)
                    assert state["proxy_ready"] and read(), state
                    if web_only:
                        subprocess.run(["launchctl", "kill", "SIGTERM", connection_service.job(config)], check=True)
                        poll(lambda: connection_service.status(config)["pid"] not in (0, state["pid"]) and read(),
                             "SSH service did not reconnect")
                    else:
                        page = browser_read(home, args, url)
                        assert page is not False, "browser did not use the private gateway"
                        stop(gateway)
                        assert not read(), "client unexpectedly reached the fixture after losing its gateway"
                        if page:
                            assert browser_read(home, args, url) is False, "browser unexpectedly reached the fixture"
                        gateway = start_gateway()
                        poll(read, "private gateway did not recover")
                        if page:
                            assert browser_read(home, args, url), "browser did not recover"
                finally:
                    if (directory / "receipt.private.json").exists():
                        manage("rollback")
                assert not connection_service.status(config)["loaded"] and not read()
        finally:
            stop(gateway)
            stop(server)
            http.shutdown()
            thread.join()
    print(json.dumps({"result": "passed", "web_only_restart": True, "shared_gateway_loss_and_recovery": True,
                      "browser_reopen": bool(os.environ.get("CHROME_PATH")), "scope": "loopback fixture only"}))


if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit("This integration exercise requires a macOS GUI login and OpenSSH.")
    with tempfile.TemporaryDirectory(prefix="zhibi-native-", dir="/private/tmp") as temporary:
        verify(Path(temporary))
