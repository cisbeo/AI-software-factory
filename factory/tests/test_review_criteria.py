"""Reviews give a verdict per acceptance criterion (spec §7.3), in `factory/bin/job`.

Every review-<r>.md carries a `## Criteria` section with one line per numbered
criterion of spec.md's `## Acceptance criteria`: `<n>. PASS|FAIL — <evidence>`.
review-spec.md also carries `## Untested criteria`: the criteria no test
exercises (`- <n>: <why>`), or `None.`. `job` refuses to leave the review stage
on a review without them; the untested list goes into the merge request's
factory block, which the human reads before merging.

Reviewers get the requirements, the diff and the evidence (the gate's
checks.md and checks.log), never build.md: their prompts don't send them there.
"""

import json
import re
import unittest

from helpers import FACTORY_SRC, SOURCE, SPEC_MD, FactoryCase, review_md, write

JOB = "001-test"
START = "<!-- factory:summary -->"


class ReviewCase(FactoryCase):
    scripts = ("job",)

    def setUp(self):
        super().setUp()
        self.d = self.make_job(JOB, stage="review", round=1, retries_left=3,
                               agents={"reviewers": {"code": "haiku", "spec": "sonnet"}},
                               reviews={"code": "pending", "spec": "pending"})
        write(self.d / "spec.md", SPEC_MD)
        (self.d / "round-1").mkdir()

    def reviews(self, code, spec):
        write(self.d / "round-1" / "review-code.md", code)
        write(self.d / "round-1" / "review-spec.md", spec)

    def assert_refused(self, stage, *says):
        before = self.read_job(JOB)
        res = self.bin("job", "advance", JOB, stage)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        for text in says:
            self.assertIn(text, res.stderr)
        self.assertEqual(self.read_job(JOB), before)
        self.assertEqual(self.forge_calls(), [])


class Criteria(ReviewCase):
    # ---- blocked ----

    def test_review_without_criteria_is_refused(self):
        self.reviews("VERDICT: CHANGES\n\n## Findings\n1. x\n", review_md(untested="none"))
        self.assert_refused("build", "review-code.md", "## Criteria", "1, 2, 3")

    def test_missing_criterion_is_refused(self):
        self.reviews(review_md("CHANGES", n=2, fail=(1,)), review_md(untested="none"))
        self.assert_refused("build", "review-code.md", "no verdict for criterion 3")

    def test_criterion_without_evidence_is_refused(self):
        text = review_md("CHANGES", fail=(1,)).replace("2. PASS — tests/test_x.py::test_2 in checks.log", "2. PASS")
        self.reviews(text, review_md(untested="none"))
        self.assert_refused("build", "review-code.md", "criterion 2")

    def test_unknown_or_repeated_or_foreign_criterion_is_refused(self):
        good = review_md("CHANGES", fail=(1,))
        for bad, says in (
            (good.replace("2. PASS", "2. MAYBE"), "criterion 2"),
            (good.replace("2. PASS", "2. pass"), "criterion 2"),
            (good + "\n## Criteria\n", "## Criteria"),
            (good.replace("3. PASS — tests/test_x.py::test_3 in checks.log",
                          "3. PASS — ok\n3. PASS — again"), "criterion 3"),
            (good.replace("3. PASS — tests/test_x.py::test_3 in checks.log",
                          "3. PASS — ok\n4. PASS — no such criterion"), "criterion 4"),
        ):
            with self.subTest(says=says, bad=bad[-80:]):
                self.reviews(bad, review_md(untested="none"))
                self.assert_refused("build", "review-code.md", says)

    def test_failed_criterion_under_a_pass_verdict_is_refused(self):
        self.reviews(review_md("PASS", fail=(2,)), review_md("CHANGES", fail=(1,), untested="none"))
        self.assert_refused("build", "review-code.md", "criterion 2 is FAIL", "VERDICT: PASS")

    def test_spec_without_numbered_criteria_is_refused(self):
        write(self.d / "spec.md", "# Spec\n\n## Acceptance criteria\nIt works.\n")
        self.reviews(review_md("CHANGES", fail=(1,)), review_md(untested="none"))
        self.assert_refused("build", "spec.md", "## Acceptance criteria")

    # ---- neighbours that pass ----

    def test_reviews_with_a_verdict_per_criterion_go_back_to_build(self):
        self.reviews(review_md("CHANGES", fail=(2,)), review_md(untested=[3]))
        res = self.bin("job", "advance", JOB, "build")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        job = self.read_job(JOB)
        self.assertEqual((job["stage"], job["round"]), ("build", 2))

    def test_criteria_checks_pass_on_the_way_to_approve(self):
        # Approval also needs the gated commit (#17); the criteria are not what stops it.
        self.reviews(review_md(), review_md(untested="none"))
        res = self.bin("job", "advance", JOB, "approve")
        self.assertNotIn("riteri", res.stderr)

    def test_continuation_lines_and_dash_separators_are_read(self):
        text = review_md("CHANGES", fail=(1,)).replace(
            "1. FAIL — tests/test_x.py::test_1 in checks.log",
            "1. FAIL - src/make.py:12 writes nothing\n   and no test covers it")
        self.reviews(text, review_md(untested="none"))
        self.assertEqual(self.bin("job", "advance", JOB, "build").returncode, 0)


class Untested(ReviewCase):
    # ---- blocked ----

    def test_spec_review_without_untested_list_is_refused(self):
        self.reviews(review_md("CHANGES", fail=(1,)), review_md())
        self.assert_refused("build", "review-spec.md", "## Untested criteria")

    def test_other_reviewers_need_no_untested_list(self):
        self.reviews(review_md("CHANGES", fail=(1,)), review_md(untested="none"))
        self.assertEqual(self.bin("job", "advance", JOB, "build").returncode, 0)

    # ---- input not understood ----

    def test_unreadable_untested_list_is_refused(self):
        for bad, says in (("- 7: no such criterion", "criterion 7"), ("some are", "## Untested criteria"),
                          ("", "## Untested criteria")):
            with self.subTest(bad=bad):
                spec = review_md(untested="none").replace("None.", bad)
                self.reviews(review_md("CHANGES", fail=(1,)), spec)
                self.assert_refused("build", "review-spec.md", says)


class UntestedInTheMergeRequest(FactoryCase):
    """The human reads the untested criteria in the merge request's factory block."""

    scripts = ("job",)

    def setUp(self):
        super().setUp()
        self.world = self.use_fake_forge()
        self.issue = self.world.ticket("Test", labels=["factory"])

    def job(self, untested):
        n, _ = self.world.mr(body="Closes #1")
        d = self.make_job(JOB, issue=self.issue, stage="review", round=1, pr=n, retries_left=3,
                          agents={"reviewers": {"spec": "sonnet"}, "reason": "risk medium → spec"},
                          reviews={"spec": "pending"})
        write(d / "spec.md", SPEC_MD)
        write(d / "round-1" / "review-spec.md", review_md("CHANGES", fail=(1,), untested=untested))
        res = self.bin("job", "advance", JOB, "build")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        body = self.world.mr_field(n, "body")
        return body[body.index(START):]

    def test_untested_criteria_are_listed_for_the_human(self):
        block = self.job([1, 3])
        self.assertIn("- Criteria no test exercises (reviewer-spec, round 1): 1, 3", block)

    def test_none_untested_says_none(self):
        self.assertIn("- Criteria no test exercises (reviewer-spec, round 1): none", self.job("none"))


class ReviewerPrompts(unittest.TestCase):
    """What the reviewers are sent to read (spec §7.3)."""

    agents = sorted((SOURCE / ".claude" / "agents").glob("reviewer-*.md"))

    def test_there_are_reviewers(self):
        self.assertGreaterEqual(len(self.agents), 6)

    def test_reviewers_are_never_sent_to_build_md(self):
        for path in self.agents:
            with self.subTest(agent=path.name):
                self.assertNotIn("build.md", path.read_text())

    def test_the_review_step_of_the_skill_does_not_send_build_md(self):
        skill = (SOURCE / ".claude" / "skills" / "factory" / "SKILL.md").read_text()
        # The reviewers' part of the step, up to the verdicts (the rest resumes the builder).
        review = re.search(r"^\*\*review\.\*\*(.*?)When every reviewer has", skill, re.M | re.S).group(1)
        self.assertNotIn("build.md", review)

    def test_reviewers_are_asked_for_a_verdict_per_criterion(self):
        for path in self.agents:
            with self.subTest(agent=path.name):
                self.assertIn("## Criteria", path.read_text())
        self.assertIn("## Untested criteria", (SOURCE / ".claude" / "agents" / "reviewer-spec.md").read_text())


if __name__ == "__main__":
    unittest.main()
