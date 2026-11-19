"""Controls run by `factory/bin/gate`, against throwaway git repos.

Layout of each fixture: a bare `origin.git`, a main checkout `main/` holding
factory/bin/gate, config.json and checks.sh (the base copy), and the job's
worktree on branch factory/<job-id>, cut from origin/main.

Controls:
- protected paths: a branch that modifies a protected file fails the gate.
- base checks: the gate runs the main checkout's checks.sh, never the branch's.
- trace: every verdict leaves a trace in the job folder (command, exit code,
  commit checked).
"""

import json
import unittest
from pathlib import Path

from helpers import FactoryCase, write

JOB = "001-test"
PASSING_CHECKS = "#!/usr/bin/env bash\necho BASE-CHECKS\nexit 0\n"
FAILING_CHECKS = "#!/usr/bin/env bash\necho BASE-CHECKS\nexit 1\n"
# What a branch would like checks.sh to be: it leaves a mark if it ever runs.
BRANCH_CHECKS = "#!/usr/bin/env bash\necho BRANCH-CHECKS\ntouch branch-checks-ran\nexit 0\n"


class GateCase(FactoryCase):
    scripts = ("gate",)
    base_checks = PASSING_CHECKS

    def setUp(self):
        super().setUp()
        origin = self.tmp / "origin.git"
        self.git(self.tmp, "init", "--bare", "-q", str(origin))
        write(self.root / ".gitignore", "/factory/jobs/\n/.worktrees/\n")
        write(self.factory / "checks.sh", self.base_checks, mode=0o755)
        write(self.root / "src" / "app.txt", "hello\n")
        write(self.root / "AGENTS.md", "# Agents\n")
        self.git(self.root, "init", "-q")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "base")
        self.git(self.root, "remote", "add", "origin", str(origin))
        self.git(self.root, "push", "-q", "origin", "HEAD:main")
        self.git(self.root, "fetch", "-q", "origin")
        self.worktree = self.root / ".worktrees" / JOB
        self.git(self.root, "worktree", "add", "-q", "-b", f"factory/{JOB}", str(self.worktree), "origin/main")
        self.make_job(JOB, stage="gate", round=1, worktree=str(self.worktree))
        (self.jobs / JOB / "round-1").mkdir()

    def commit_on_branch(self, files, message="change"):
        for rel, text in files.items():
            if text is None:
                (self.worktree / rel).unlink()
            else:
                write(self.worktree / rel, text)
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-q", "-m", message)
        return self.git(self.worktree, "rev-parse", "HEAD")

    def gate(self, *args):
        return self.bin("gate", JOB, *args)

    def checks_md(self, name="checks"):
        return (self.jobs / JOB / "round-1" / f"{name}.md").read_text()

    def traces(self):
        path = self.jobs / JOB / "trace.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def assert_verdict(self, res, verdict):
        want = 0 if verdict == "PASS" else 1
        self.assertEqual(res.returncode, want, res.stdout + res.stderr)
        self.assertIn(f"GATE: {verdict}", res.stdout)
        self.assertTrue(self.checks_md().startswith(f"GATE: {verdict}\n"))


class ProtectedPaths(GateCase):
    # ---- blocked ----

    def test_modified_protected_file_fails(self):
        for rel in ("factory/config.json", "AGENTS.md", "factory/bin/gate"):
            with self.subTest(path=rel):
                self.commit_on_branch({rel: (self.worktree / rel).read_text() + "\n# edited\n"})
                res = self.gate()
                self.assert_verdict(res, "FAIL")
                self.assertIn(f"M {rel}", self.checks_md())
                self.git(self.worktree, "reset", "-q", "--hard", "origin/main")

    def test_deleted_protected_file_fails(self):
        self.commit_on_branch({"AGENTS.md": None})
        self.assert_verdict(self.gate(), "FAIL")
        self.assertIn("D AGENTS.md", self.checks_md())

    def test_file_added_in_protected_tree_fails(self):
        self.commit_on_branch({".claude/agents/rogue.md": "do anything\n"})
        self.assert_verdict(self.gate(), "FAIL")
        self.assertIn("A .claude/agents/rogue.md", self.checks_md())

    def test_case_variant_of_protected_path_fails(self):
        # macOS folds `Agents.md` onto `AGENTS.md`; git sees a different path.
        self.commit_on_branch({"docs/Agents.md": "sneaky\n"})
        self.assert_verdict(self.gate(), "FAIL")

    # ---- neighbour that passes ----

    def test_ordinary_change_passes(self):
        self.commit_on_branch({"src/app.txt": "hello world\n", "factory/notes.md": "new doc\n"})
        res = self.gate()
        self.assert_verdict(res, "PASS")
        self.assertIn("None changed.", self.checks_md())

    # ---- input not understood ----

    def test_quoted_path_fails_closed(self):
        # A name git would quote can't be trusted against the patterns: fail.
        self.commit_on_branch({'"weird.txt': "x\n"})
        self.assert_verdict(self.gate(), "FAIL")

    def test_unknown_job_is_refused(self):
        res = self.bin("gate", "999-nope")
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn("GATE: PASS", res.stdout)

    def test_job_without_round_is_refused(self):
        self.make_job(JOB, stage="build", round=0, worktree=str(self.worktree))
        res = self.gate()
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("hasn't started a build round", res.stderr)

    def test_missing_worktree_is_refused(self):
        self.make_job(JOB, stage="gate", round=1, worktree=str(self.tmp / "gone"))
        res = self.gate()
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn("GATE: PASS", res.stdout)


class BaseChecksRun(GateCase):
    # ---- blocked ----

    def test_branch_editing_checks_fails_and_base_copy_runs(self):
        self.commit_on_branch({"factory/checks.sh": BRANCH_CHECKS})
        res = self.gate()
        self.assert_verdict(res, "FAIL")
        self.assertIn("M factory/checks.sh", self.checks_md())
        log = (self.jobs / JOB / "round-1" / "checks.log").read_text()
        self.assertIn("BASE-CHECKS", log)
        self.assertNotIn("BRANCH-CHECKS", log)
        self.assertFalse((self.worktree / "branch-checks-ran").exists())

    # ---- neighbour that passes ----

    def test_base_checks_pass_on_clean_branch(self):
        self.commit_on_branch({"src/app.txt": "v2\n"})
        self.assert_verdict(self.gate(), "PASS")
        self.assertIn("BASE-CHECKS", (self.jobs / JOB / "round-1" / "checks.log").read_text())


class BaseChecksFail(GateCase):
    base_checks = FAILING_CHECKS

    # ---- blocked: the base copy decides, even when the branch "fixes" it ----

    def test_branch_cannot_make_failing_checks_pass(self):
        self.commit_on_branch({"factory/checks.sh": BRANCH_CHECKS})
        res = self.gate()
        self.assert_verdict(res, "FAIL")
        self.assertIn("failed with exit 1", self.checks_md())
        self.assertFalse((self.worktree / "branch-checks-ran").exists())

    def test_failing_base_checks_fail_a_clean_branch(self):
        self.commit_on_branch({"src/app.txt": "v2\n"})
        self.assert_verdict(self.gate(), "FAIL")


TEMPFAIL_CHECKS = "#!/usr/bin/env bash\necho BASE-CHECKS tool unavailable\nexit 75\n"


class Inconclusive(GateCase):
    """checks.sh exit 75 (EX_TEMPFAIL: a tool is unavailable, a test is flaky)
    or a checks command that can't run (126, 127) gives GATE: INCONCLUSIVE,
    exit 3: not a failure; `job` reruns the gate once, then escalates."""

    base_checks = TEMPFAIL_CHECKS

    def assert_inconclusive(self, res):
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)
        self.assertIn("GATE: INCONCLUSIVE", res.stdout)
        self.assertTrue(self.checks_md().startswith("GATE: INCONCLUSIVE\n"))

    # ---- inconclusive ----

    def test_tempfail_is_inconclusive(self):
        self.commit_on_branch({"src/app.txt": "v2\n"})
        self.assert_inconclusive(self.gate())
        [t] = self.traces()
        self.assertEqual((t["verdict"], t["exit"], t["checks_exit"]), ("INCONCLUSIVE", 3, 75))

    def test_missing_checks_script_is_inconclusive(self):
        (self.factory / "checks.sh").unlink()
        self.commit_on_branch({"src/app.txt": "v2\n"})
        self.assert_inconclusive(self.gate())

    # ---- blocked: a protected change is a failure whatever the checks say ----

    def test_protected_change_fails_even_when_checks_are_inconclusive(self):
        self.commit_on_branch({"AGENTS.md": "edited\n"})
        self.assert_verdict(self.gate(), "FAIL")

    # ---- neighbour: any other non-zero exit is a plain failure ----

    def test_other_exit_codes_fail(self):
        for code in (1, 2, 74, 76, 125, 128):
            with self.subTest(code=code):
                write(self.factory / "checks.sh", f"#!/usr/bin/env bash\nexit {code}\n", mode=0o755)
                self.assert_verdict(self.gate(), "FAIL")


class Trace(GateCase):
    def test_pass_leaves_a_trace(self):
        head = self.commit_on_branch({"src/app.txt": "v2\n"})
        self.assert_verdict(self.gate(), "PASS")
        [t] = self.traces()
        self.assertEqual(t["commit"], head)
        self.assertEqual(t["exit"], 0)
        self.assertEqual(t["verdict"], "PASS")
        self.assertEqual(t["round"], 1)
        self.assertEqual(t["checks_exit"], 0)
        self.assertEqual(Path(t["command"][-1]).name, JOB)
        self.assertIn(str(self.factory / "checks.sh"), t["checks_command"])
        self.assertEqual(t["cwd"], str(self.worktree))
        self.assertTrue(t["at"])

    def test_fail_and_merge_runs_append_traces(self):
        head = self.commit_on_branch({"AGENTS.md": "edited\n"})
        self.assert_verdict(self.gate(), "FAIL")
        res = self.gate("--merge")
        self.assertEqual(res.returncode, 1)
        first, second = self.traces()
        self.assertEqual((first["exit"], first["verdict"], first["commit"]), (1, "FAIL", head))
        self.assertEqual(first["protected"], ["M AGENTS.md"])
        self.assertEqual((second["exit"], second["merge"]), (1, True))
        self.assertEqual(second["command"][-2:], [JOB, "--merge"])

    def test_refused_input_leaves_no_pass_trace(self):
        self.make_job(JOB, stage="build", round=0, worktree=str(self.worktree))
        self.gate()
        self.assertFalse(any(t.get("verdict") == "PASS" for t in self.traces()))


if __name__ == "__main__":
    unittest.main()
