"""Rehearse the delivered Skill outside the checkout with an isolated home and no pip."""
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from build_skill import ROOT, build


def verify():
    with tempfile.TemporaryDirectory(prefix="zhibi-skill-") as tmp:
        base = Path(tmp).resolve()
        package = build(base / "artifacts")
        with zipfile.ZipFile(package["skill"]) as archive:
            assert all(name.startswith("zhibi/") and ".." not in Path(name).parts for name in archive.namelist())
            archive.extractall(base / "installed")
        skill = base / "installed" / "zhibi"
        entry = skill / "scripts" / "zhibi.py"
        environment = dict(os.environ)
        for key in list(environment):
            if key in {"PYTHONPATH", "PYTHONHOME"} or key.startswith("ZHIBI_"):
                environment.pop(key)
        home = base / "home"
        home.mkdir()
        environment["HOME"] = str(home)
        bootstrap = "import pathlib,runpy,sys; user_dir=pathlib.Path(sys.argv[1]); pathlib.Path.home=classmethod(lambda cls:user_dir); sys.argv=sys.argv[2:]; runpy.run_path(sys.argv[0],run_name='__main__')"
        def run(*args):
            result = subprocess.run([sys.executable, "-I", "-c", bootstrap, str(home), str(entry), *map(str, args)], cwd=base,
                                    env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)
        connection = run("connect", "--host", "example.com")
        assert connection["browser_proxy"]["host"] == "127.0.0.1"
        assert connection["applied"] is False
        exported_connection = run("connect", "--host", "example.com", "--export-out", base / "connection")
        assert Path(exported_connection["launcher"]).is_file()
        assert exported_connection["verified"] is False
        if sys.platform in {"darwin", "linux"}:
            service = run("connection-service", "--host", "example.com", "--name", "zhibi-verify",
                          "--vps-egress", "--out", base / "browser-service")
            assert service["installed"] is False
            assert service["egress"] == "vps-existing-route"
            assert Path(service["manager"]).is_file()
        assert (skill / "references/runtime.md").is_file()
        assert (skill / "references/local-vm.md").is_file()
        assert (skill / "references/audit.md").is_file()
        project_dir = base / "project"; project_dir.mkdir()
        start_script = base / "start.sh"; start_script.write_text("true\n"); start_script.chmod(0o600)
        common = ["--project", project_dir, "--state-dir", base / "bindings"]
        run("project", "bind", *common, "--host", "example.com", "--workdir", "/srv/project", "--command-file", start_script)
        assert run("project", "status", *common)["backend"] == "remote"
        assert not run("project", "audit", *common)["attempted"]
        delivery_scenarios = []
        # Browser-only delivery from the archive, followed by the user running
        # the generated repro script from a different working directory.
        if os.name == "posix":
            source_parent = base / "source-install"
            source_parent.mkdir()
            alternate_parent = base / "source-install-alias"
            alternate_parent.symlink_to(source_parent, target_is_directory=True)
            source_skill = alternate_parent / "zhibi"
            install = [sys.executable, str(ROOT / "scripts/install_skill.py"), "--dest", str(source_skill)]

            def local(*args, check=True):
                return subprocess.run(args, cwd=base, env=environment, capture_output=True,
                                      text=True, encoding="utf-8", check=check, timeout=30)

            local(*install)
            marker = source_skill / "version-marker"
            marker.write_text("previous", encoding="utf-8")
            assert local(*install, check=False).returncode == 2
            upgraded = local(*install, "--replace")
            previous = next(line.split("：", 1)[1] for line in upgraded.stdout.splitlines() if line.startswith("已保留旧版："))
            local(sys.executable, str(source_skill / "scripts/zhibi.py"), "skill-rollback",
                  "--dest", str(source_skill.resolve()), "--previous", previous)
            assert marker.read_text(encoding="utf-8") == "previous"
            delivery_scenarios.append("source_install_upgrade_and_rollback")

            at = datetime.now(timezone.utc).isoformat()
            ip = "8.8.8.8"
            browser = base / "synthetic-browser.json"
            browser_fixture = {"schema_version": "1", "context": "user_opened_browser",
                "observations": [
                    {"check_id": "browser.context", "status": "ok", "at": at,
                     "facts": {"timezone": "Etc/UTC", "language": "en-US", "cookies_enabled": True,
                               "storage_available": True, "automated": False}},
                    {"check_id": "browser.egress", "status": "ok", "at": at, "facts": {
                        "ip": ip, "family": 4, "endpoint": "https://api.ipify.org?format=json"}},
                ]}
            browser.write_text(json.dumps(browser_fixture), encoding="utf-8")
            fake = base / "no-network"
            fake.mkdir()
            fake_curl = fake / "curl"
            fake_ip = fake / "proxy-ip"
            fake_ip.write_text(ip)
            fake_curl.write_text("#!/bin/sh\ncase \"$(cat)\" in\n  *socks5h://127.0.0.1:10818*) ;;\n  *) exit 99 ;;\nesac\n"
                                 "case \"$*\" in\n  *' -4 '*) printf '{\"ip\":\"%s\"}\\n' \"$(cat \"${0%/*}/proxy-ip\")\" ;;\n"
                                 "  *) exit 7 ;;\nesac\n")
            fake_curl.chmod(0o700)
            old_path = environment["PATH"]
            environment["PATH"] = str(fake) + os.pathsep + old_path
            try:
                workflow = base / "workflow"
                assert run("environment", "init", "--folder", workflow, "--route", "undecided")["stage"] == "start"
                checkpoint = run("environment", "checkpoint", "--folder", workflow, "--route", "web", "--artifact", browser)
                assert checkpoint["stage"] == "configure" and checkpoint["route"] == "web"
                common_web = ("--proxy-port", 10818, "--egress", "--browser", browser)
                packet = run("deliver", *common_web, "--browser-profile", "Synthetic profile", "--exit-policy", "fixed",
                             "--environment", workflow, "--out", base / "deliveries")
                folder = Path(packet["directory"])
                dynamic = Path(run("deliver", *common_web, "--exit-policy", "dynamic", "--out", base / "dynamic")["directory"])
                assert packet["verification"]["state"] == "ok"
                assert "Synthetic profile" in (folder / "先读我.md").read_text()
                assert not (folder / "rollback.sh").exists()
                assert run("environment", "status", "--folder", workflow)["events"][-1]["artifact"] == str(folder)
                status = run("environment", "status", "--folder", folder)
                assert status["exit_policy"] == "fixed" and status["baseline"] == {"browser:IPv4": ip, "runtime:IPv4": ip}
                reproduced = subprocess.run(["sh", str(folder / "reproduce.sh"), str(browser)], cwd=base,
                                            env=environment, capture_output=True, text=True, check=True, timeout=30)
                recheck = json.loads(reproduced.stdout)
                assert recheck["verification"]["state"] == "ok"
                assert recheck["network_consistency"]["rows"][0]["comparison"]["state"] == "ok"
                assert recheck["network_consistency"]["rows"][1]["comparison"]["state"] == "not_measured"
                changed = "9.9.9.9"
                fake_ip.write_text(changed)
                browser_fixture["observations"][1]["facts"]["ip"] = changed
                browser.write_text(json.dumps(browser_fixture), encoding="utf-8")
                for delivery, exit_code, state in ((folder, 1, "fail"), (dynamic, 0, "warn")):
                    done = local("sh", str(delivery / "reproduce.sh"), str(browser), check=False)
                    assert done.returncode == exit_code, done.stderr
                    recheck = json.loads(done.stdout)
                    assert recheck["network_consistency"]["rows"][0]["comparison"]["state"] == "ok"
                    assert [row["state"] for row in recheck["network_consistency"]["baseline"]["checks"]] == [state, state]
                    assert "出口历史对照" in (Path(recheck["directory"]) / "报告.html").read_text()
                browser_fixture["observations"][1]["facts"]["ip"] = ip
                browser.write_text(json.dumps(browser_fixture), encoding="utf-8")
            finally:
                environment["PATH"] = old_path
            delivery_scenarios.append("installed_browser_delivery_recheck")
            delivery_scenarios.append("installed_environment_checkpoint_and_egress_drift")
            # Exercise the project route without opening a network connection.
            # The fake SSH transport only responds when called via the bound runner.
            run("project", "unbind", *common, "--apply")
            run("project", "bind", *common, "--host", "example.com", "--workdir", "/srv/project",
                "--command-file", start_script, "--no-browser-proxy", "--runtime-workspace", "/private/workspace")
            assert run("project", "start", *common)["browser_proxy"] is None
            fake_ssh = fake / "ssh"
            probe = json.dumps({"execution": "ok", "egress": {"state": "observed", "ip": ip}})
            fake_ssh.write_text("#!/bin/sh\ncase \"$*\" in\n  *'sh -c'*/private/workspace/run.py*) ;;\n  */private/workspace/run.py*) printf '%s\\n' '"
                                + probe + "' ;;\n  *'test -d /srv/project'*) ;;\n  *) exit 99 ;;\nesac\n")
            fake_ssh.chmod(0o700)
            old_path = environment["PATH"]
            environment["PATH"] = str(fake) + os.pathsep + old_path
            try:
                accepted = run("accept", *common, "--egress", "--browser", browser)
                assert accepted["verification"]["state"] == "ok"
                assert accepted["local"][2]["expected"] == ip
                assert accepted["facts"] == {}
                packet = run("deliver", *common, "--egress", "--browser", browser, "--out", base / "project-delivery")
                folder = Path(packet["directory"])
                opened = subprocess.run(["sh", str(folder / "open-project.sh")], cwd=base, env=environment,
                                        capture_output=True, text=True, check=True, timeout=30)
                assert json.loads(opened.stdout)["applied"]
                delivery_scenarios.append("installed_project_runner_acceptance_and_launch")
            finally:
                environment["PATH"] = old_path
        assert run("doctor")["runtime_dependencies"] == []
        assert "scan" in run("capabilities")["commands"]
        assert all(not p["configured"] for p in run("providers")["providers"])
        reputation = run("scan", "--network", "--reputation", "--dry-run")
        assert reputation["providers"] == ["ipwhois", "proxycheck", "ipquery", "stopforumspam"]
        assert all(not s.get("requires_key") for s in reputation["external_services"])
        offline = run("scan", "--out", base / "offline")
        assert offline["summary"]["contacted_services"] == []
        dns = run("dns", "--out", base / "dns")
        assert dns["summary"]["status"] == "skipped" and not dns["summary"]["attempted"]
        assert run("dns", "--dry-run")["context"] == "dig_default_resolver"
        for scenario in ("conflicting-sources", "missing-coverage", "provider-outage"):
            demo = run("scan-demo", "--scenario", scenario, "--out", base / scenario)
            assert demo["summary"]["sample"] is True
            assert len(demo["summary"]["providers"]) == 4
            exported = run("export", base / scenario / "report.json")
            assert "8.8.8.8" not in json.dumps(exported)
        config = base / "synthetic-ipv6-config.txt"
        config.write_text("Synthetic dedicated-environment IPv6 outbound block.\n", encoding="utf-8")
        confirmed = run("confirm-ipv6", base / "provider-outage", "--evidence", config,
                        "--configuration", "blocked", "--method", "local_config", "--reviewed",
                        "--out", base / "ipv6-confirmed")
        assert next(r for r in confirmed["summary"]["assessment"]["overview"]["table_rows"]
                    if r["label"] == "IPv6 出站策略")["result"] == "通过"
        run("browser", "--advanced", "--out", base / "probe.html")
        page = (base / "probe.html").read_text()
        assert "probeBrowserExit" in page and "Permission is hereby granted" in page
        assert 'schema_version:"4"' in page and 'id="detail-fonts"' in page and "ZhibiDetails.collect" in page
        assert "ZhibiExtras.collect" in page and 'id="extra-dns"' in page
        assert len(run("modules")) >= 13
        suite = run("suite", "--preset", "custom", "--module", "browser-extras", "--out", base / "suite")
        assert suite["summary"]["recipients"] == [] and not suite["summary"]["environment_modified"]
        assert suite["summary"]["modules"]["browser-extras"]["status"] == "blocked_dependency"
        run("suite-share", base / "suite", "--out", base / "share")
        assert "ZHIBI_NETWORK_MODULE" not in page
        assert (skill / "licenses/CCBaga-MIT.txt").is_file()
        assert (skill / "licenses/CheckCC-MIT.txt").is_file()
        for path in skill.rglob("*.md"):
            content = path.read_text(encoding="utf-8")
            assert str(Path(__file__).resolve().parents[1]) not in content
            for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
                if "://" not in link and not link.startswith("#"):
                    assert (path.parent / link.split("#")[0]).is_file(), (path.name, link)
        return {"result": "passed", "scenarios": ["isolated_install", "connection_plan", "offline_scan", "provider_catalog", "keyless_reputation_plan", "conflicting_sources",
                "missing_coverage", "provider_outage", "summary_export", "scoped_ipv6_confirmation", "advanced_browser_v4", "optional_suite", "redacted_suite_share", "dns_offline_and_plan", "third_party_licenses", *delivery_scenarios],
                "python": sys.version.split()[0], "host_natural_language_selection": "not_tested"}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
