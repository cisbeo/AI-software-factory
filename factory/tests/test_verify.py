"""Cases for factory verify, the smoke test after installation (spec §11.4, ADR 0004).

Each case installs the factory, from a committed throwaway source, on a new
target repository (the worlds of test_install), merges the install into the
base branch, then runs `factory verify` there, without network:
- the source's suite of verification is a stand-in `factory/tests/` (one test
  that passes, or fails), so verify doesn't replay this very suite;
- `claude` is FAKE_ORCHESTRATOR: it answers doctor's version and model checks,
  and for `/factory run <n>` it drives the real installed scripts (job, route,
  gate, forge on the fake gh) the way the factory skill does, with canned
  agents. Its intake decides from the ticket's title.
"""

import json
import os
import signal
import sys
from pathlib import Path

from helpers import run, write
from test_install import ANSWERS, InstallCase

COMMANDS = ("command.install=aucune", "command.lint=aucune", "command.typecheck=aucune",
            "command.test=true", "command.build=aucune")

PASSING_SUITE = """import unittest


class Control(unittest.TestCase):
    def test_blocks_and_lets_through(self):
        self.assertTrue(True)
"""
FAILING_SUITE = PASSING_SUITE.replace("assertTrue(True)", "assertTrue(False, 'contrôle cassé')")

FAKE_ORCHESTRATOR = r'''#!PYTHON -B
"""claude double: doctor's checks, and a canned /factory run that drives the real scripts.

FAKE_ORCH_DIR       its log (launches.log) and markers
FAKE_ORCH_HANG      stage where a job's first launch hangs (30 s, then exit 1), e.g. build
FAKE_ORCH_ACCEPT_ALL  intake accepts every ticket, traps included
FAKE_ORCH_STALL     a launch that finds the job already started does nothing
FAKE_ORCH_ESCALATE  the approver escalates instead of approving
FAKE_ORCH_SWAP      intake asks for information where it should reject, and the reverse
"""
import json, os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
if args[:1] == ["--version"]:
    print(os.environ.get("FAKE_CLAUDE_VERSION", "9.0.0 (Claude Code)"))
    sys.exit(0)
prompt = args[-1] if args else ""
if not prompt.startswith("/factory run "):
    sys.stdin.read()
    print('{"type":"result","is_error":false,"result":"OK"}')
    sys.exit(0)

out = Path(os.environ["FAKE_ORCH_DIR"])
with open(out / "launches.log", "a") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "pgid": os.getpgid(0), "pid": os.getpid()}) + "\n")
ROOT = Path.cwd()
BIN = ROOT / "factory" / "bin"
JOBS = ROOT / "factory" / "jobs"


def sh(*cmd, cwd=ROOT, check=True):
    res = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)
    print(f"$ {' '.join(str(c) for c in cmd)}\n{res.stdout}{res.stderr}", flush=True)
    if check and res.returncode != 0:
        sys.exit(1)
    return res.stdout.strip()


def job_of(n):
    for p in sorted(JOBS.glob("*/job.json")) if JOBS.exists() else []:
        j = json.loads(p.read_text())
        if j["issue"] == n:
            return j
    return None


n = int(prompt.split()[2])
job = job_of(n)
if job and os.environ.get("FAKE_ORCH_STALL"):
    sys.exit(0)
jid = job["id"] if job else sh(BIN / "job", "create", n)
d = JOBS / jid
config = json.loads((ROOT / "factory" / "config.json").read_text())
model = sorted(config["prices_usd_per_mtok"])[0]
while True:
    job = json.loads((d / "job.json").read_text())
    stage = job["stage"]
    if stage == "intake":
        title = job["title"]
        decision = "ACCEPT"
        if not os.environ.get("FAKE_ORCH_ACCEPT_ALL"):
            if "rejeter" in title:
                decision = "REJECT"
            elif "information" in title:
                decision = "NEEDS-INFO"
            if os.environ.get("FAKE_ORCH_SWAP") and decision != "ACCEPT":
                decision = {"REJECT": "NEEDS-INFO", "NEEDS-INFO": "REJECT"}[decision]
        (d / "intake.md").write_text(f"DECISION: {decision}\nRISK: low\nSURFACES: none\n\n## Why\nCanned.\n")
        if decision == "ACCEPT":
            sh(BIN / "route", jid)
            sh(BIN / "job", "advance", jid, "spec")
        else:
            sh(BIN / "job", "advance", jid, {"REJECT": "rejected", "NEEDS-INFO": "needs-info"}[decision])
    elif stage == "spec":
        (d / "spec.md").write_text("# Spec\n\n## Acceptance criteria\n1. The file exists.\n")
        sh(BIN / "job", "advance", jid, "build")
    elif stage == "build":
        marker = out / f"hung-{jid}"
        if os.environ.get("FAKE_ORCH_HANG") == "build" and not marker.exists():
            marker.touch()
            time.sleep(30)
            sys.exit(1)
        wt = job["worktree"]
        Path(wt, f"verify-{jid}.md").write_text("ok\n")
        sh("git", "add", "-A", cwd=wt)
        trailers = sh(BIN / "job", "trailers", jid, "--agent", "builder", "--model", model)
        sh("git", "commit", "-q", "-m", f"Add verify-{jid}.md\n\n{trailers}", cwd=wt)
        sh("git", "push", "-q", "origin", job["branch"], cwd=wt)
        if sh(BIN / "forge", "mr", "find", "--head", job["branch"]) == "null":
            sh(BIN / "forge", "mr", "create", "--head", job["branch"], "--base", config["base_branch"],
               "--title", job["title"], "--body", f"Closes #{n}")
        (d / "build.md").write_text("STATUS: READY\n\nDone.\n")
        sh(BIN / "job", "advance", jid, "gate")
    elif stage == "gate":
        sh(BIN / "gate", jid)
        sh(BIN / "job", "advance", jid, "review")
    elif stage == "review":
        for r in job["agents"]["reviewers"]:
            (d / f"round-{job['round']}" / f"review-{r}.md").write_text(
                "VERDICT: PASS\n\n## Criteria\n1. PASS — the file is in the diff\n"
                + ("\n## Untested criteria\nNone.\n" if r == "spec" else ""))
        sh(BIN / "job", "advance", jid, "approve")
    elif stage == "approve":
        if os.environ.get("FAKE_ORCH_ESCALATE"):
            (d / "decision.md").write_text("ESCALATE\n\nCanned.\n")
            sh(BIN / "job", "advance", jid, "needs-human")
        else:
            (d / "decision.md").write_text("APPROVE\n\nCanned.\n")
            sh(BIN / "job", "merge", jid)
    else:
        break
'''


class VerifyCase(InstallCase):
    suite = PASSING_SUITE

    def make_source(self):
        write(self.src / "factory/tests/test_control.py", self.suite)
        super().make_source()

    def setUp(self):
        super().setUp()
        write(self.tmp / "bin" / "claude", FAKE_ORCHESTRATOR.replace("PYTHON", sys.executable), mode=0o755)
        self.orch = self.tmp / "orch"
        self.orch.mkdir()
        self.env.update(FAKE_ORCH_DIR=str(self.orch), FAKE_ORCH_HANG="build")
        self.addCleanup(self.kill_leftovers)

        self.make_target(files={"README.md": "# demo\n", "AGENTS.md": "# demo\n"})
        self.ok(self.install(*self.answered(*COMMANDS)), "INSTALL: POSÉE")
        self.commit_all()
        self.git(self.target, "switch", "-q", "main")
        self.git(self.target, "merge", "-q", "--ff-only", "factory-install")
        self.git(self.target, "branch", "-q", "-D", "factory-install")
        self.git(self.target, "push", "-q", "origin", "main")

    def kill_leftovers(self):
        """A hung double the verify under test failed to stop must not outlive the case."""
        for launch in self.launches():
            try:
                os.killpg(launch["pgid"], signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def factory(self, *args, stdin="", cwd=None, script=None):
        """factory/bin/factory of the source checkout, or of `script` (another checkout)."""
        return run([sys.executable, "-B", str((script or self.src) / "factory/bin/factory"), *args],
                   cwd=cwd or self.target, env=self.env, stdin=stdin)

    def verify(self, *args):
        return self.factory("verify", *args)

    def launches(self):
        log = self.orch / "launches.log"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    def gh(self):
        return self.world.load()

    def issues(self):
        """Tickets only: the fake gh keeps each pull request as an issue too, as GitHub does."""
        return [i for i in self.gh()["issues"].values() if "pull_request" not in i]

    def commit_on_main(self, rel, text, message="local change"):
        write(self.target / rel, text)
        self.git(self.target, "add", "-A")
        self.git(self.target, "commit", "-q", "-m", message)
        self.git(self.target, "push", "-q", "origin", "main")

    def jobs(self):
        return {json.loads(p.read_text())["issue"]: json.loads(p.read_text())
                for p in (self.target / "factory/jobs").glob("*/job.json")}

    def assert_nothing_left_open(self):
        """Every ticket verify created is closed as not planned, every merge request closed unmerged."""
        state = self.gh()
        for issue in self.issues():
            self.assertEqual((issue["state"], issue.get("state_reason")), ("closed", "not_planned"), issue["title"])
        for pull in state["pulls"].values():
            self.assertEqual(pull["state"], "closed", pull["title"])
            self.assertFalse(pull.get("merged"), pull["title"])


class Verify(VerifyCase):
    def test_the_dummy_ticket_crosses_the_pipeline_and_its_merge_request_is_closed_unmerged(self):
        res = self.ok(self.verify(), "VERIFY: OK")
        self.assertIn("installation réussie", res.stdout)
        jobs = self.jobs()
        dummy = [j for j in jobs.values() if "factice" in j["title"]]
        self.assertEqual(len(dummy), 1, jobs)
        dummy = dummy[0]
        # It went through approve: decision.md is the approver's APPROVE, and
        # with auto_merge never it stopped for a human, then verify rejected it.
        d = self.target / "factory/jobs" / dummy["id"]
        self.assertEqual((d / "decision.md").read_text().splitlines()[0], "APPROVE")
        self.assertEqual(dummy["stage"], "rejected")
        self.assertTrue((d / "rejection.md").exists())
        pulls = list(self.gh()["pulls"].values())
        self.assertEqual(len(pulls), 1, pulls)
        self.assertEqual(pulls[0]["head"]["ref"], dummy["branch"])
        self.assertIn(f"demande de fusion #{pulls[0]['number']} fermée sans être fusionnée", res.stdout)
        self.assert_nothing_left_open()
        # The throwaway branch is gone from origin.
        self.assertEqual(self.git(self.target, "ls-remote", "origin", dummy["branch"]), "")

    def test_one_trap_is_rejected_and_the_other_waits_for_information(self):
        res = self.ok(self.verify(), "VERIFY: OK")
        jobs = self.jobs()
        reject = [j for j in jobs.values() if "rejeter" in j["title"]]
        info = [j for j in jobs.values() if "information" in j["title"]]
        self.assertEqual((len(reject), len(info)), (1, 1), jobs)
        self.assertIn(f"#{reject[0]['issue']} → rejected", res.stdout)
        self.assertIn(f"#{info[0]['issue']} → needs-info", res.stdout)
        # Intake's own decisions, not verify's cleanup.
        for j, want in ((reject[0], "REJECT"), (info[0], "NEEDS-INFO")):
            intake = (self.target / "factory/jobs" / j["id"] / "intake.md").read_text()
            self.assertTrue(intake.startswith(f"DECISION: {want}"), intake)
        self.assertEqual(len(self.issues()), 3)
        self.assert_nothing_left_open()

    def test_an_interruption_mid_job_is_resumed_by_factory_run(self):
        res = self.ok(self.verify(), "VERIFY: OK")
        dummy = [j for j in self.jobs().values() if "factice" in j["title"]][0]
        runs = [l for l in self.launches() if l["args"][-1] == f"/factory run {dummy['issue']}"]
        # The first session hung in build and was stopped; the same command resumed the job.
        self.assertEqual(len(runs), 2, runs)
        self.assertIn("session 1 interrompue à l'étape build", res.stdout)
        self.assertTrue((self.orch / f"hung-{dummy['id']}").exists())
        # Every session runs unattended in the target, capped by the job's cost cap.
        for l in self.launches():
            self.assertEqual(Path(l["cwd"]).resolve(), self.target)
            self.assertEqual(l["args"][:5], ["-p", "--permission-mode", "bypassPermissions",
                                             "--max-budget-usd", "10"])

    def test_the_suite_of_verification_is_replayed(self):
        res = self.ok(self.verify(), "VERIFY: OK")
        self.assertIn("== suite de vérification", res.stdout)
        self.assertRegex(res.stdout, r"Ran 1 test")


class SuiteFails(VerifyCase):
    suite = FAILING_SUITE

    def test_a_broken_control_stops_verify_before_any_ticket(self):
        res = self.refused(self.verify(), "VERIFY: FAIL", "suite de vérification en échec", "contrôle cassé")
        self.assertIn("Correction :", res.stdout)
        self.assertEqual(self.issues(), [])
        self.assertEqual(self.launches(), [])


class Preconditions(VerifyCase):
    def test_auto_merge_other_than_never_is_refused(self):
        config = json.loads((self.target / "factory/config.json").read_text())
        config["auto_merge"] = "low"
        self.commit_on_main("factory/config.json", json.dumps(config, indent=2) + "\n")
        res = self.refused(self.verify(), "VERIFY: FAIL", "auto_merge")
        self.assertIn("Correction :", res.stdout)
        self.assertEqual(self.issues(), [])

    def test_claude_configuration_beyond_the_install_is_refused(self):
        for rel in (".claude/settings.local.json", ".mcp.json"):
            write(self.target / rel, "{}\n")
            res = self.refused(self.verify(), "VERIFY: FAIL", "configuration Claude hors de la factory", rel)
            self.assertIn("Correction :", res.stdout)
            (self.target / rel).unlink()
        self.assertEqual(self.issues(), [])

    def test_caps_the_sessions_cannot_read_are_refused(self):
        config = json.loads((self.target / "factory/config.json").read_text())
        config["max_cost_usd"] = "1e9"
        self.commit_on_main("factory/config.json", json.dumps(config, indent=2) + "\n")
        self.refused(self.verify(), "VERIFY: FAIL", "max_cost_usd")
        self.assertEqual(self.issues(), [])

    def test_a_component_changed_since_install_is_refused(self):
        gate = self.target / "factory/bin/gate"
        self.commit_on_main("factory/bin/gate", gate.read_text() + "\n# local change\n")
        res = self.refused(self.verify(), "VERIFY: FAIL", "différents du commit", "factory/bin/gate")
        self.assertIn("Correction :", res.stdout)
        self.assertEqual(self.issues(), [])

    def test_an_install_not_merged_into_the_base_branch_is_refused(self):
        # The install stays on its branch; main goes back to before it.
        self.git(self.target, "branch", "-q", "factory-install")
        self.git(self.target, "reset", "-q", "--hard", "HEAD~1")
        self.git(self.target, "push", "-q", "-f", "origin", "main")
        self.git(self.target, "switch", "-q", "factory-install")
        res = self.refused(self.verify(), "VERIFY: FAIL", "pas encore fusionnée dans origin/main")
        self.assertEqual(self.issues(), [])

    def test_a_target_without_install_journal_is_refused(self):
        self.git(self.target, "rm", "-q", "factory/install-log.json")
        self.git(self.target, "commit", "-q", "-m", "drop journal")
        self.git(self.target, "push", "-q", "origin", "main")
        self.refused(self.verify(), "VERIFY: FAIL", "factory install")
        self.assertEqual(self.issues(), [])

    def test_the_installed_copy_cannot_verify_itself(self):
        res = self.refused(self.factory("verify", cwd=self.target, script=self.target), "VERIFY: FAIL",
                           "clone de la factory")
        self.assertEqual(self.issues(), [])


class Failures(VerifyCase):
    def test_a_trap_that_intake_accepts_fails_verify_and_is_cleaned_up(self):
        self.env["FAKE_ORCH_ACCEPT_ALL"] = "1"  # its job also hangs in build, long enough to be seen
        res = self.refused(self.verify(), "VERIFY: FAIL", "session arrêtée avant toute construction", "rejected")
        self.assertIn("Correction :", res.stdout)
        # Stopped as soon as the job left intake for spec: nothing built, nothing pushed.
        self.assertEqual(self.gh()["pulls"], {})
        trap = [j for j in self.jobs().values() if "rejeter" in j["title"]][0]
        self.assertIn(trap["stage"], {"spec", "build"})
        self.assertIn(f"reste : job {trap['id']} laissé à l'étape", res.stdout)
        self.assert_nothing_left_open()

    def test_a_trap_that_ends_in_the_wrong_waiting_stage_fails_verify(self):
        self.env["FAKE_ORCH_SWAP"] = "1"
        res = self.refused(self.verify(), "VERIFY: FAIL", "finit en needs-info, pas en rejected")
        self.assertIn("Correction :", res.stdout)
        self.assert_nothing_left_open()

    def test_a_dummy_ticket_that_stops_short_of_approval_fails_verify(self):
        self.env["FAKE_ORCH_ESCALATE"] = "1"
        res = self.refused(self.verify(), "VERIFY: FAIL", "ne va pas au bout", "décision ESCALATE")
        self.assertIn("Correction :", res.stdout)
        self.assert_nothing_left_open()

    def test_a_resume_that_does_not_move_the_job_fails_verify(self):
        self.env["FAKE_ORCH_STALL"] = "1"
        res = self.refused(self.verify(), "VERIFY: FAIL",
                           "la reprise après l'interruption n'a pas fait avancer le job (étape build)")
        self.assertIn("Correction :", res.stdout)
        self.assert_nothing_left_open()
