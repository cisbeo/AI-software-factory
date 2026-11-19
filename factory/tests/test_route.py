"""Control: `factory/bin/route` picks reviewers from intake's risk and surfaces.

Spec §7.3: one reviewer for low risk, two axes (spec fidelity, repo standards)
from medium risk, plus security and interface lenses by surface.

Blocked: a job intake didn't ACCEPT, an unknown risk, an unknown surface; each
leaves `agents` unset, so `job advance <job> spec` stays refused.
Neighbour: each known risk, with and without surfaces, routes as configured.
Not understood: a missing or malformed RISK/SURFACES header, a missing intake.md.
"""

import unittest

from helpers import FactoryCase, write


class Route(FactoryCase):
    scripts = ("job", "route")

    def intake(self, risk="low", surfaces="none", decision="ACCEPT", raw=None):
        self.make_job(stage="intake")
        text = raw if raw is not None else (
            f"DECISION: {decision}\nRISK: {risk}\nSURFACES: {surfaces}\n\n## Why\nTest.\n")
        write(self.jobs / "001-test" / "intake.md", text)

    def route(self):
        return self.bin("route", "001-test")

    def assert_routed(self, reviewers):
        res = self.route()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read_job()["agents"], {"reviewers": reviewers})

    def assert_refused(self, res, says):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(says, res.stderr)
        self.assertIsNone(self.read_job()["agents"])
        self.assertEqual(self.forge_calls(), [])

    # ---- neighbour that passes ----

    def test_low_risk_gets_one_reviewer(self):
        self.intake(risk="low")
        self.assert_routed({"code": "haiku"})

    def test_medium_and_high_risk_get_spec_and_standards(self):
        for risk in ("medium", "high"):
            with self.subTest(risk=risk):
                self.intake(risk=risk)
                self.assert_routed({"spec": "sonnet", "standards": "sonnet"})

    def test_surfaces_add_their_lenses(self):
        self.intake(risk="medium", surfaces="ui, security")
        self.assert_routed({"spec": "sonnet", "standards": "sonnet",
                            "ux": "sonnet", "ui": "haiku", "security": "opus"})

    def test_routing_follows_config(self):
        self.config["routing"]["low"] = {"code": "sonnet"}
        self.write_config()
        self.intake(risk="low")
        self.assert_routed({"code": "sonnet"})

    # ---- blocked ----

    def test_unaccepted_intake_is_refused(self):
        for decision in ("REJECT", "NEEDS-INFO"):
            with self.subTest(decision=decision):
                self.intake(decision=decision)
                self.assert_refused(self.route(), "route only an intake job that intake ACCEPTed")

    def test_unknown_risk_is_refused(self):
        self.intake(risk="trivial")
        self.assert_refused(self.route(), "risk 'trivial' isn't in config.json routing")

    def test_unknown_surface_is_refused(self):
        self.intake(risk="low", surfaces="billing")
        self.assert_refused(self.route(), "surface 'billing' isn't in config.json surface_reviewers")

    # ---- input not understood ----

    def test_missing_risk_is_refused(self):
        self.intake(raw="DECISION: ACCEPT\nSURFACES: none\n\n## Why\nTest.\n")
        self.assert_refused(self.route(), "risk None isn't in config.json routing")

    def test_risk_with_wrong_case_is_refused(self):
        self.intake(risk="LOW")
        self.assert_refused(self.route(), "risk 'LOW' isn't in config.json routing")

    def test_missing_intake_is_refused(self):
        self.make_job(stage="intake")
        self.assert_refused(self.route(), "has no intake.md")

    def test_unknown_job_is_refused(self):
        res = self.bin("route", "999-nope")
        self.assertEqual(res.returncode, 1)
        self.assertIn("no job 999-nope", res.stderr)


if __name__ == "__main__":
    unittest.main()
