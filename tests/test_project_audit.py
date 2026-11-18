import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zhibi import project_audit as audit
from zhibi.models import InputError, now


def observation(ip=None, execution="ok"):
    return {"execution": execution, "egress": {"state": "observed", "ip": ip} if ip else {"state": "error"}}


class OutageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.script = Path(self.tmp.name) / "control"
        self.script.write_text("true\n"); self.script.chmod(0o600)
        self.before = observation("203.0.113.1")

    def run_cycle(self, during, after=None):
        with patch.object(audit, "control", return_value=True), patch.object(audit, "measure", side_effect=[during, after or self.before]):
            return audit.outage({}, self.before, self.script, self.script)

    def test_live_probe_sees_network_fail_and_restore(self):
        self.assertEqual(self.run_cycle(observation())["state"], "ok")

    def test_lost_ssh_is_not_evidence_of_network_blocking(self):
        self.assertEqual(self.run_cycle(observation(execution="error"))["state"], "not_measured")

    def test_direct_fallback_or_unbroken_tunnel_fails(self):
        self.assertEqual(self.run_cycle(observation("203.0.113.2"))["state"], "fail")

    def test_ipv6_reachability_during_an_ipv4_outage_fails(self):
        during = observation()
        during["egress_ipv6"] = {"state": "observed", "ip": "2001:db8::8"}
        self.assertEqual(self.run_cycle(during)["reason"], "network_still_reachable_during_outage")

    def test_restoration_must_use_original_exit(self):
        self.assertEqual(self.run_cycle(observation(), observation("203.0.113.3"))["reason"], "exit_changed_after_restoration")

    def test_restore_runs_even_if_measurement_raises(self):
        with patch.object(audit, "control", return_value=True) as control, \
                patch.object(audit, "measure", side_effect=[RuntimeError("failed"), self.before]):
            with self.assertRaises(RuntimeError):
                audit.outage({}, self.before, self.script, self.script)
        self.assertEqual(control.call_count, 2)

    def test_no_baseline_no_disconnection(self):
        with patch.object(audit, "control", side_effect=AssertionError("disconnected")):
            result = audit.outage({}, observation(), self.script, self.script)
        self.assertEqual(result["state"], "not_measured")

    def test_missing_browser_or_runner_never_passes(self):
        args = SimpleNamespace(network=True, expected_ip="203.0.113.1", browser=None,
            disconnect_file=None, reconnect_file=None, out=None)
        with patch.object(audit, "measure", return_value=self.before):
            result = audit.audit(args, {"backend": "remote"})
        self.assertEqual(result["checks"]["egress"]["state"], "ok")
        self.assertEqual(result["checks"]["application_scope"]["state"], "not_measured")
        self.assertFalse(result["complete"])
        with patch.object(audit, "measure", return_value=self.before):
            legacy = audit.audit(args, {"backend": "remote", "probe_prefix": ["env"]})
        self.assertEqual(legacy["checks"]["application_scope"]["state"], "not_measured")

    def test_offline_audit_never_connects(self):
        with patch.object(audit, "measure", side_effect=AssertionError("network")):
            self.assertFalse(audit.audit(SimpleNamespace(network=False), {})["attempted"])

    def test_outage_import_rejects_other_bindings_and_old_results(self):
        path = Path(self.tmp.name) / "audit.json"
        binding = {"backend": "remote", "project": "/work/project"}
        report = {"version": 1, "at": now(), "binding_sha256": audit.binding_fingerprint(binding),
                  "checks": {"egress": {"ip": "203.0.113.1"}, "outage": {"state": "ok", "reason": "restored"}}}
        path.write_text(json.dumps(report))
        path.chmod(0o600)
        self.assertEqual(audit.read_outage(path, binding)["baseline_ip"], "203.0.113.1")
        with self.assertRaisesRegex(InputError, "不属于当前项目绑定"):
            audit.read_outage(path, {**binding, "project": "/work/other"})
        report["at"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(InputError, "已过期"):
            audit.read_outage(path, binding)
