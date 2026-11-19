"""Control: `factory/bin/job advance` refuses illegal transitions.

Blocked: a jump the transition table doesn't allow, or a legal edge whose
justifying file is missing. Neighbour: spec → build with spec.md present.
Not understood: an unknown target stage, a job whose stored stage is unknown,
a job id that doesn't exist. Every refusal leaves job.json untouched and never
reaches the forge.
"""

import unittest

from helpers import FactoryCase, write


class JobTransitions(FactoryCase):
    scripts = ("job",)

    def assert_refused(self, res, job_id="001-test", before=None, says=None):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        if says:
            self.assertIn(says, res.stderr)
        if before is not None:
            self.assertEqual(self.read_job(job_id), before)
        self.assertEqual(self.forge_calls(), [], "a refused transition must not reach the forge")

    # ---- blocked ----

    def test_skipping_stages_is_refused(self):
        self.make_job(stage="spec")
        write(self.jobs / "001-test" / "spec.md", "# Spec\n")
        before = self.read_job()
        for target in ("merging", "approve", "review", "gate", "merged"):
            with self.subTest(target=target):
                res = self.bin("job", "advance", "001-test", target)
                if target == "merged":
                    # spec → merged is allowed only once the PR is merged; no PR here.
                    self.assert_refused(res, before=before, says="the PR isn't merged")
                else:
                    self.assert_refused(res, before=before, says="is not a legal transition")

    def test_terminal_job_cannot_move(self):
        self.make_job(stage="merged", ended="2026-11-19T01:00:00Z")
        before = self.read_job()
        for target in ("build", "intake", "needs-human", "merged"):
            with self.subTest(target=target):
                self.assert_refused(self.bin("job", "advance", "001-test", target),
                                    before=before, says="is not a legal transition")

    def test_legal_edge_without_its_file_is_refused(self):
        self.make_job(stage="spec")
        before = self.read_job()
        self.assert_refused(self.bin("job", "advance", "001-test", "build"),
                            before=before, says="spec.md doesn't exist")

    # ---- neighbour that passes ----

    def test_spec_to_build_with_spec_passes(self):
        self.make_job(stage="spec")
        write(self.jobs / "001-test" / "spec.md", "# Spec\n")
        res = self.bin("job", "advance", "001-test", "build")
        self.assertEqual(res.returncode, 0, res.stderr)
        job = self.read_job()
        self.assertEqual((job["stage"], job["round"]), ("build", 1))
        self.assertTrue((self.jobs / "001-test" / "round-1").is_dir())
        self.assertEqual(self.forge_calls(), [])

    # ---- input not understood ----

    def test_unknown_target_stage_is_refused(self):
        self.make_job(stage="spec")
        write(self.jobs / "001-test" / "spec.md", "# Spec\n")
        before = self.read_job()
        for target in ("banana", "", "BUILD", "build "):
            with self.subTest(target=target):
                self.assert_refused(self.bin("job", "advance", "001-test", target),
                                    before=before, says="is not a legal transition")

    def test_unknown_stored_stage_is_refused(self):
        self.make_job(stage="limbo")
        before = self.read_job()
        for target in ("build", "spec", "needs-human"):
            with self.subTest(target=target):
                self.assert_refused(self.bin("job", "advance", "001-test", target),
                                    before=before, says="is not a legal transition")

    def test_missing_job_is_refused(self):
        self.assert_refused(self.bin("job", "advance", "999-nope", "build"), says="no job 999-nope")


if __name__ == "__main__":
    unittest.main()
