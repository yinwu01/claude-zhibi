"""The delivery folder and the user-facing wording are the product surface. Test both."""
import json
import io
import os
import shlex
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zhibi import browser_workspace, flow, project_audit, remote, score as s
from zhibi.models import InputError, now, timestamp

FACTS = {"os": "Ubuntu 24.04", "tz": "Europe/Berlin", "lc_all": "en_US.UTF-8", "ntp": "yes",
         "systemd": "yes", "nameservers": "10.0.0.1 ", "egress_ip": "203.0.113.9",
         "egress_org": "Example Telecom Broadband", "nproc": "2", "mem_mb": "2048"}


def build_report():
    result = s.score(egress=flow._egress(FACTS), facts=FACTS, expect_tz="Europe/Berlin",
                     expect_locale="en_US.UTF-8", dns=flow._dns(FACTS),
                     service={"active": True, "enabled": True})
    return {"host": "203.0.113.9", "at": "2026-11-05T00:00:00Z", "facts": FACTS,
            "score": result, "remote": {"checks": []}, "headline": flow._headline({"score": result})}


class HeadlineTests(unittest.TestCase):
    def test_headline_is_three_plain_sentences(self):
        lines = flow._headline(build_report())
        self.assertEqual(len(lines), 3)
        self.assertIn("先不下结论", lines[0])

    def test_headline_never_leaks_internal_ids(self):
        report = build_report()
        text = " ".join(flow._headline(report))
        for identifier in ("reputation", "not_measured", "consistency", "leakage"):
            self.assertNotIn(identifier, text)

    def test_headline_names_missing_items_in_chinese(self):
        text = " ".join(flow._headline(build_report()))
        self.assertIn("信誉读数", text)
        self.assertIn("不算通过", text)

    def test_insufficient_evidence_refuses_a_verdict(self):
        result = s.score()
        lines = flow._headline({"score": result})
        self.assertIn("先不下结论", lines[0])


class BrowserAcceptanceTests(unittest.TestCase):
    def run_accept(self, arguments, browser_ip, host_facts=None):
        from zhibi.cli import main
        output = io.StringIO()
        with redirect_stdout(output), patch.object(flow, "browser_readings", return_value={"egress_ip": browser_ip}), \
                patch.object(remote, "check", return_value=host_facts or FACTS) as host:
            status = main(["accept", *arguments])
        return status, json.loads(output.getvalue()), host

    def test_mismatched_browser_cannot_receive_passing_summary(self):
        status, report, _ = self.run_accept(["--host", "example.org", "--egress", "--browser", "fresh"],
                                            "198.51.100.7")
        self.assertEqual(status, 1)
        self.assertEqual(report["verification"]["state"], "fail")
        self.assertIn("未通过", report["headline"][0])
        self.assertNotIn("100 分", flow.render_html(report))

    def test_browser_only_uses_measured_route_baseline_without_host(self):
        status, report, host = self.run_accept(["--expected-ip", "198.51.100.7", "--browser", "fresh"],
                                               "198.51.100.7")
        self.assertEqual(status, 0)
        self.assertEqual(report["verification"]["state"], "ok")
        host.assert_not_called()

    def test_project_comparison_uses_application_scope_and_target(self):
        binding = {"project": "/tmp/test project", "backend": "remote", "workdir": "/workspace",
                   "target": remote.target("example.org")}
        checks = {"egress": {"state": "observed", "ip": "198.51.100.7"},
                  "application_scope": {"state": "ok"}}
        args = ["--project", "bound", "--browser", "fresh", "--egress"]
        with patch.object(flow, "project_evidence", return_value=(binding, {"checks": checks})):
            status, report, host = self.run_accept(args, "198.51.100.7")
            self.assertEqual(status, 0)
            self.assertEqual(report["local"][2]["expected"], "198.51.100.7")
            host.assert_not_called()
            status, report, _ = self.run_accept(args + ["--expected-ip", "192.0.2.8"], "198.51.100.7")
            self.assertEqual(status, 1)
            self.assertIn("浏览器预期出口", report["verification"]["failed"])
            checks["application_scope"]["state"] = "not_measured"
            status, report, _ = self.run_accept(args, "198.51.100.7")
            self.assertEqual(status, 1)
            self.assertEqual(report["verification"]["state"], "not_measured")

    def test_real_export_shape_and_webrtc_match(self):
        from test_scan import browser_bundle
        bundle = browser_bundle(ip="8.8.8.8")
        bundle["network"]["webrtc"]["candidates"][0]["address"] = "8.8.8.8"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "browser.json"
            path.write_text(json.dumps(bundle))
            result = flow.browser_readings(path)
        self.assertEqual(result["timezone"], "Asia/Shanghai")
        self.assertEqual(result["language"], "zh-CN")
        self.assertEqual(result["egress_ip"], "8.8.8.8")
        self.assertIs(result["webrtc_leak"], False)

    def test_browser_ipv6_is_preserved_without_assuming_a_path(self):
        from test_scan import browser_bundle
        from zhibi.cli import main

        bundle = browser_bundle(ip="8.8.8.8")
        bundle["network"]["webrtc"]["candidates"][0]["address"] = "8.8.8.8"
        bundle["network"]["ipv6"].update(status="ok", ip="2001:db8::8")
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as output:
            path = Path(tmp) / "browser.json"
            path.write_text(json.dumps(bundle))
            self.assertEqual(main(["accept", "--expected-ip", "8.8.8.8", "--browser", str(path)]), 0)
        report = json.loads(output.getvalue())
        row = next(c for c in report["local"] if c["key"] == "浏览器 IPv6 路径")
        self.assertEqual(row["observation"], bundle["network"]["ipv6"])
        self.assertEqual(row["state"], "unverified")
        self.assertIn(row["key"], report["verification"]["pending"])
        self.assertIn("2001:db8::8", flow.render_html(report))

    def test_proxy_and_browser_compare_each_family_and_keep_real_addresses(self):
        from test_scan import browser_bundle
        from zhibi.cli import main

        bundle = browser_bundle()
        bundle["network"]["webrtc"]["candidates"][0]["address"] = "8.8.8.8"
        bundle["network"]["ipv6"].update(status="ok", ip="2001:db8::8")

        def route(config, family):
            self.assertEqual(config, {"proxy_url": "socks5h://127.0.0.1:10818"})
            address = "8.8.8.8" if family == 4 else "2001:db8::9"
            return {"status": "ok", "at": now(), "facts": {"ip": address}}

        with tempfile.TemporaryDirectory() as tmp, patch("zhibi.diagnostics.route", side_effect=route) as probe:
            path = Path(tmp) / "browser.json"
            path.write_text(json.dumps(bundle))
            args = ["accept", "--proxy-port", "10818", "--browser", str(path)]
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([*args, "--egress"]), 1)
            self.assertEqual([call.kwargs["family"] for call in probe.call_args_list], [4, 6])
            report = json.loads(output.getvalue())
            ipv4, ipv6 = report["network_consistency"]["rows"]
            self.assertEqual(ipv4["comparison"]["state"], "ok")
            self.assertEqual(ipv6["comparison"]["state"], "fail")
            self.assertEqual((ipv6["runtime"]["ip"], ipv6["browser"]["ip"]), ("2001:db8::9", "2001:db8::8"))
            self.assertIn("浏览器 IPv6 路径", report["verification"]["failed"])
            html = flow.render_html(report)
            self.assertIn("后台 SOCKS 连接", html)
            self.assertIn("2001:db8::9", html)

            bundle["network"]["ipv6"]["at"] = (timestamp(now()) - timedelta(minutes=6)).isoformat()
            path.write_text(json.dumps(bundle))
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([*args, "--egress"]), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["network_consistency"]["rows"][1]["comparison"]["reason"], "different_measurement_time")
            self.assertIn("浏览器 IPv6 路径", report["verification"]["pending"])

    def test_project_uses_the_bound_runtime_ipv6_as_a_second_reference(self):
        from zhibi.cli import main

        binding = {"project": "/tmp/fixture", "backend": "remote", "workdir": "/workspace", "runtime_workspace": "/private/workspace",
                   "target": remote.target("example.org")}
        audit = {"checks": {"application_scope": {"state": "ok"}, "egress": {"ip": "203.0.113.9"},
                             "egress_ipv6": {"ip": "2001:db8::8", "status": "observed"}}}
        browser = {"egress_ip": "203.0.113.9", "ipv6": {"ip": "2001:db8::8", "status": "ok"}}
        with redirect_stdout(io.StringIO()) as output, \
                patch.object(flow, "project_evidence", return_value=(binding, audit)), \
                patch.object(flow, "browser_readings", return_value=browser):
            self.assertEqual(main(["accept", "--project", "bound", "--egress", "--browser", "fresh",
                                   "--expected-ipv6", "2001:db8:0:0:0:0:0:8"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["network_consistency"]["runtime_context"], "知彼进程工作区")
        self.assertEqual(report["network_consistency"]["rows"][1]["expected_matches"], {"runtime": True, "browser": True})

    def test_acceptance_keeps_network_protocol_evidence_and_explains_next_step(self):
        from test_optional_modules import bundle4
        from zhibi.cli import main

        browser = bundle4()
        browser["extras"]["checks"]["dns"] = {"status": "ok", "facts": {"observer": "https://observer.example",
            "resolvers": ["192.0.2.53"], "ecs": [], "transport_from_browser": "not_observable"}}
        binding = {"project": "/tmp/fixture", "backend": "remote", "workdir": "/workspace",
                   "target": remote.target("example.org")}
        audit = {"checks": {"application_scope": {"state": "ok"}, "egress": {"ip": "8.8.8.8"}}}
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as output, \
                patch.object(flow, "project_evidence", return_value=(binding, audit)):
            path = Path(tmp) / "browser.json"
            path.write_text(json.dumps(browser))
            self.assertEqual(main(["accept", "--project", "bound", "--egress", "--browser", str(path)]), 1)
        report = json.loads(output.getvalue())
        self.assertIn("WebRTC 与 HTTPS 出口", report["verification"]["failed"])
        dns = next(row for row in report["local"] if row["key"] == "浏览器 DNS 路径")
        self.assertEqual(dns["state"], "observed")
        self.assertEqual(dns["measured"]["resolvers"], ["192.0.2.53"])
        page = flow.render_html(report)
        self.assertIn("公网候选 1.1.1.1", page)
        self.assertIn("192.0.2.53", page)
        self.assertIn("<h2>先做这一步</h2>", page)

    def test_project_failures_and_incomplete_pvm_checks_reach_summary(self):
        binding = {"project": "/tmp/fixture", "backend": "pvm", "workdir": "/workspace", "target": None}
        checks = {"egress": {"ip": "203.0.113.9"}, "application_scope": {"state": "ok"},
                  "dns_resolution": {"state": "error"}, "outage": {"state": "not_measured"}}
        protocols = {"protocol_checks_passed": False, "checks": {"route": {"state": "warn"}}}
        with patch.object(flow, "project_evidence", return_value=(binding, {"checks": checks, "pvm": protocols})):
            status, report, _ = self.run_accept(["--project", "bound", "--browser", "fresh", "--egress"], "203.0.113.9")
            self.assertEqual(status, 1)
            self.assertEqual(report["verification"]["state"], "fail")
            self.assertIn("应用 DNS 解析", report["verification"]["failed"])
            self.assertIn("应用断线与恢复", report["verification"]["pending"])
            checks["dns_resolution"]["state"] = "observed"
            status, report, _ = self.run_accept(["--project", "bound", "--egress"], None)
            self.assertEqual(status, 1)
            self.assertEqual(report["verification"]["state"], "not_measured")
            self.assertIn("PVM 协议验收", report["verification"]["missing"])
            protocols["checks"]["route"]["state"] = "fail"
            status, report, _ = self.run_accept(["--project", "bound", "--egress"], None)
            self.assertEqual(status, 1)
            self.assertIn("PVM 出口路由", report["verification"]["failed"])

    def test_automated_or_stale_export_cannot_pass(self):
        from test_scan import browser_bundle
        for automated in (True, False):
            bundle = browser_bundle(automated=automated)
            if not automated:
                for observation in bundle["observations"]:
                    observation["at"] = "2020-01-01T00:00:00Z"
                for observation in bundle["network"].values():
                    observation["at"] = "2020-01-01T00:00:00Z"
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "browser.json"
                path.write_text(json.dumps(bundle))
                self.assertEqual(flow.browser_readings(path), {})

    def test_deliver_preserves_browser_checks(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        report = build_report()
        report["local"] = [{"key": "browser-proof", "state": "fail", "measured": "different"}]
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(host="203.0.113.9", user="root", port=22, identity=None,
                                   out=tmp, unit=None, timezone=None, locale=None)
            with patch.object(flow, "accept", return_value=report), patch.object(flow, "create_run", return_value=Path(tmp)):
                result = flow.deliver(args)
            folder = Path(result["directory"])
            saved = json.loads((folder / "verification.json").read_text())
            self.assertEqual(saved["local"], report["local"])
            self.assertIn("browser-proof", (folder / "报告.html").read_text())


class StagePersistenceTests(unittest.TestCase):
    def test_check_out_saves_actual_stage_without_reexecuting(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(command="check", out=str(Path(tmp) / "stage"))
            with patch.object(flow, "check", return_value={"host": "example.com", "facts": {"ntp": "yes"}}) as check:
                result = flow.dispatch(args)
            check.assert_called_once_with(args)
            saved = json.loads((Path(result["directory"]) / "check.private.json").read_text())
            self.assertEqual(saved["facts"], {"ntp": "yes"})


class DeliverTests(unittest.TestCase):
    def test_delivery_imports_the_outage_check_without_running_controls_again(self):
        from zhibi.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            start = root / "start"
            start.write_text("true\n")
            start.chmod(0o600)
            prefix = root / "prefix"
            prefix.write_text('["python3", "/tmp/workspace/run.py", "--"]')
            prefix.chmod(0o600)
            state = root / "bindings"
            common = ["--project", str(root), "--state-dir", str(state)]
            result = root / "outage.json"
            connected = {"execution": "ok", "egress": {"state": "observed", "ip": "203.0.113.9"}}
            fallback = {"execution": "ok", "egress": {"state": "observed", "ip": "192.0.2.8"}}
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["project", "bind", *common, "--host", "example.org", "--workdir", "/workspace",
                                       "--command-file", str(start), "--probe-prefix-file", str(prefix)]), 0)
                with patch.object(project_audit, "measure", side_effect=[connected, fallback, connected]), \
                        patch.object(project_audit, "control", return_value=True):
                    status = main(["project", "audit", *common, "--network", "--out", str(result),
                                   "--disconnect-file", str(start), "--reconnect-file", str(start)])
                self.assertEqual(status, 1)
            with redirect_stdout(io.StringIO()) as output, patch.object(project_audit, "measure", return_value=connected), \
                    patch.object(project_audit, "control", side_effect=AssertionError("control repeated")), \
                    patch.object(flow, "create_run", return_value=root):
                status = main(["deliver", *common, "--egress", "--outage-report", str(result), "--out", str(root)])
            delivery = json.loads(output.getvalue())
            self.assertEqual(status, 1)
            self.assertIn("应用断线与恢复", delivery["verification"]["failed"])
            folder = Path(delivery["directory"])
            saved = json.loads((folder / "verification.json").read_text())
            self.assertEqual(saved["project_audit"]["checks"]["outage"]["reason"], "network_still_reachable_during_outage")
            self.assertNotIn("--outage-report", (folder / "reproduce.sh").read_text())

    @unittest.skipUnless(os.name == "posix", "POSIX browser connection launch")
    def test_chromium_launch_script_opens_the_exact_profile_from_another_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            browser = root / "fake-browser"
            launched = root / "launched.txt"
            browser.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" >" + shlex.quote(str(launched)) + "\n")
            browser.chmod(0o700)
            workspace = root / "my browser"
            browser_workspace.create(SimpleNamespace(browser_binary=str(browser), local_port=10818, out=workspace))
            args = SimpleNamespace(host="example.org", user="root", port=22, identity=None, unit=None,
                                   timezone=None, locale=None, out=str(root), browser_workspace=str(workspace))
            with patch.object(flow, "accept", return_value=build_report()), patch.object(flow, "create_run", return_value=root):
                packet = flow.deliver(args)
            folder = Path(packet["directory"])
            subprocess.run(["sh", str(folder / "open-browser.sh")], cwd=root, check=True, timeout=10)
            self.assertIn("--user-data-dir=" + str(workspace / "profile"), launched.read_text())
            self.assertIn("open-browser.sh", (folder / "先读我.md").read_text())

    @unittest.skipUnless(os.name == "posix", "PVM is supported on macOS and Linux")
    def test_pvm_handover_supplies_project_and_desktop_entry_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            report = build_report()
            project = root / "my work"
            vm = root / "vm"
            state = root / "custom bindings"
            report.update(connection=None, project_context={"path": str(project), "workdir": "/workspace",
                          "backend": "pvm", "vm_workspace": str(vm), "state_dir": str(state)})
            args = SimpleNamespace(unit=None, timezone=None, locale=None, out=str(root), vm_browser=True,
                                   browser_profile="Guest Chromium", app_entry="/workspace/bin/test")
            with patch.object(flow, "accept", return_value=report), patch.object(flow, "create_run", return_value=root), \
                    patch("zhibi.handover.cli_command", return_value=["printf", "%s\\n"]):
                result = flow.deliver(args)
            folder = Path(result["directory"])
            expected = {"open-project.sh": ["project", "start", "--project", str(project), "--state-dir", str(state), "--apply"],
                        "open-vm-desktop.sh": ["vm", "desktop", "--workspace", str(vm), "--apply"]}
            for filename, command in expected.items():
                done = subprocess.run(["sh", str(folder / filename)], cwd=root, capture_output=True,
                                      text=True, check=True, timeout=10)
                self.assertEqual(done.stdout.splitlines(), command)
            self.assertIn("Guest Chromium", (folder / "先读我.md").read_text())

    def test_native_delivery_keeps_real_handles_and_runs_browser_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            manager = root / "manage.py"
            actions = root / "actions"
            manager.write_text("import sys\nfrom pathlib import Path\n"
                               f"Path({str(actions)!r}).write_text(sys.argv[1])\n")
            receipt = {"target": str(root / "test.plist"), "unit_sha256": "0" * 64}
            for file, data in (("receipt.private.json", receipt),
                               ("service.private.json", {**receipt, "format": "zhibi-connection-service-1",
                                                         "name": "zhibi-test", "local_port": 10818})):
                path = root / file
                path.write_text(json.dumps(data))
                path.chmod(0o600)
            report = build_report()
            args = SimpleNamespace(host="example.org", user="root", port=22, identity=None, unit=None,
                                   timezone=None, locale=None, out=str(root), browser_profile="Work Profile",
                                   browser_service=str(root), runtime_service="/home/dev/gateway",
                                   app_entry="/home/dev/workspace/bin/demo", shell="bash",
                                   remote_skill_entry="/home/dev/skill/scripts/zhibi.py")
            with patch.object(flow, "accept", side_effect=AssertionError("measurement attempted")):
                with self.assertRaisesRegex(InputError, "验收端口"):
                    flow.deliver(SimpleNamespace(**vars(args), proxy_port=10819))
            # Exercise the rollback script with a recorder in place of SSH.
            with patch.object(flow, "accept", return_value=report), \
                    patch.object(flow, "create_run", return_value=root), \
                    patch("zhibi.remote.ssh_argv", side_effect=lambda target, cmd: ["printf", "%s\\n", cmd]):
                result = flow.deliver(args)
            folder = Path(result["directory"])
            readme = (folder / "先读我.md").read_text()
            self.assertIn("Work Profile", readme)
            self.assertIn("/home/dev/workspace/bin/demo", readme)
            result = subprocess.run(["sh", str(folder / "rollback.sh")], check=True,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(actions.read_text(), "rollback")
            self.assertIn("process-activate restore", result.stdout)
            self.assertIn("/home/dev/gateway/manage.py rollback", result.stdout)

    def test_folder_contains_everything_the_user_keeps(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "out"
            flow.deliver_files(folder, build_report(), unit="svc",
                               timezone="Europe/Berlin", locale="en_US.UTF-8")
            names = sorted(p.name for p in folder.iterdir())
            self.assertEqual(names, sorted(["先读我.md", "报告.html", "verification.json",
                                            "remote.md", "browser.md", "reproduce.sh"]))

    def test_scripts_are_executable_and_reference_the_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "out"
            flow.deliver_files(folder, build_report(), unit="svc",
                               timezone="Europe/Berlin", locale="en_US.UTF-8")
            reproduce = (folder / "reproduce.sh").read_text()
            self.assertIn("zhibi check --host 203.0.113.9", reproduce)
            self.assertFalse((folder / "rollback.sh").exists())
            self.assertIn("没有可自动恢复", (folder / "先读我.md").read_text())

    def test_readme_states_the_stop_command_and_no_guarantee(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "out"
            flow.deliver_files(folder, build_report(), unit="svc",
                               timezone="Europe/Berlin", locale="en_US.UTF-8")
            text = (folder / "先读我.md").read_text()
            self.assertIn("systemctl stop svc", text)
            self.assertNotIn("不会被限制", text)

    def test_html_is_self_contained(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "out"
            flow.deliver_files(folder, build_report(), unit="svc",
                               timezone="Europe/Berlin", locale="en_US.UTF-8")
            html = (folder / "报告.html").read_text()
            self.assertNotIn("http://", html)
            self.assertNotIn("https://", html)
            self.assertIn("环境准备记录", html)

    def test_delivery_keeps_connection_identity_and_observed_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = build_report()
            report["connection"] = {"host": "203.0.113.9", "user": "worker", "port": 2222, "identity": None}
            report["local"] = [{"key": "出口", "measured": "different", "state": "fail"}]
            folder = Path(tmp) / "out"
            flow.deliver_files(folder, report, unit="svc")
            recheck = (folder / "reproduce.sh").read_text()
            self.assertIn("--user worker --port 2222", recheck)
            self.assertIn("worker@203.0.113.9", (folder / "先读我.md").read_text())
            browser = (folder / "browser.md").read_text()
            self.assertIn("different", browser)
            self.assertNotIn("跟随通道", browser)

    def test_existing_folder_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "out"
            flow.deliver_files(folder, build_report(), unit="svc",
                               timezone="Europe/Berlin", locale="en_US.UTF-8")
            with self.assertRaises(FileExistsError):
                flow.deliver_files(folder, build_report(), unit="svc",
                                   timezone="Europe/Berlin", locale="en_US.UTF-8")


class RemoteContractTests(unittest.TestCase):
    def test_doctor_reports_missing_ssh_before_deploying_a_selected_route(self):
        from zhibi.cli import main

        with patch("zhibi.cli.shutil.which", return_value=None), patch("zhibi.cli.platform.system", return_value="Darwin"):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["doctor", "--route", "web"]), 1)
            self.assertIn("ssh", json.loads(output.getvalue())["missing_tools"])
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["doctor"]), 0)
            self.assertFalse(json.loads(output.getvalue())["local_tools"]["ssh"])

    def test_build_cli_dispatches_with_or_without_application_command(self):
        from zhibi.cli import main
        for extra in ([], ["--command", "/usr/bin/true"]):
            with self.subTest(extra=extra), redirect_stdout(io.StringIO()) as output, \
                    patch.object(remote, "check", return_value=FACTS), \
                    patch.object(remote, "execute", side_effect=AssertionError("write or SSH")):
                self.assertEqual(main(["build", "--host", "example.org", *extra]), 0)
            plan = json.loads(output.getvalue())
            self.assertEqual(plan["step"], "build")
            self.assertFalse(plan["applied"])
            self.assertEqual(plan["service"] is not None, bool(extra))

    def test_check_cli_preserves_explicit_ssh_configuration(self):
        from zhibi.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "private-config"
            config.write_text("Host alias\n  HostName 192.0.2.2\n")
            config.chmod(0o600)
            with redirect_stdout(io.StringIO()), patch.object(remote, "check", return_value=FACTS) as check:
                self.assertEqual(main(["check", "--host", "alias", "--ssh-config", str(config)]), 0)
            self.assertEqual(check.call_args.args[0]["ssh_config"], str(config.absolute()))

    def test_facts_parse_and_findings_flag_public_dns(self):
        text = "tz=UTC\nntp=no\nnameservers=8.8.8.8 \nlocales=3\nsystemd=yes\n"
        facts = remote.parse_facts(text)
        keys = {item["key"]: item["state"] for item in remote.findings(facts)}
        self.assertEqual(keys["remote.dns"], "observed")
        self.assertEqual(keys["remote.clock"], "changed_unverified")

    def test_wrap_rejects_newline_injection(self):
        with self.assertRaises(Exception):
            remote.unit("svc", "ok\nExecStart=/bin/sh")

    def test_wrap_unit_uses_the_users_command_verbatim(self):
        body = remote.unit("svc", "/usr/bin/env codex --profile work")
        self.assertIn("ExecStart=/usr/bin/env codex --profile work", body)
        self.assertIn("Restart=on-failure", body)

    def test_verify_marks_missing_service_as_unmeasured(self):
        result = remote.verify(FACTS, "Europe/Berlin", "en_US.UTF-8")
        unit = [c for c in result["checks"] if c["key"] == "unit"][0]
        self.assertEqual(unit["state"], "not_measured")


if __name__ == "__main__":
    unittest.main()
