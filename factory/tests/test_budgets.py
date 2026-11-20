"""Controls of spec §6 « Budgets et arrêts », enforced by `factory/bin/job`.

- Retry budget (config `retry_budget`): each gate FAIL or review CHANGES spends
  one; it never refills, not even after a human's feedback. The failure that
  spends the last one sends the job to needs-human with a precise question.
- Cost and duration caps (config `max_cost_usd`, `max_duration_minutes`),
  checked before every step: over a cap, the job stops (needs-human) with the
  reason written in decision.md and posted on the forge.
- Inconclusive gate: doesn't spend the budget; the gate runs once more, then
  the job escalates.
- Every stop is one of five exits, in job.json `exit`: success, failure,
  timeout, budget, human.

Forge calls go through the real factory/bin/forge, backed by the fake gh.
"""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone

from helpers import SPEC_MD, review_md, FactoryCase, write

JOB = "001-test"
EXITS = {"success", "failure", "timeout", "budget", "human"}


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class BudgetCase(FactoryCase):
    scripts = ("job",)

    def setUp(self):
        super().setUp()
        self.world = self.use_fake_forge()
        self.issue = self.world.ticket("Test", labels=["factory"])
        self.worktree = self.tmp / "wt"
        self.worktree.mkdir()
        self.git(self.worktree, "init", "-q")
        write(self.worktree / "a.txt", "a\n")
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-q", "-m", "a")
        self.head = self.git(self.worktree, "rev-parse", "HEAD")

    def job(self, **fields):
        base = dict(issue=self.issue, worktree=str(self.worktree),
                    agents={"reviewers": {"code": "haiku", "spec": "sonnet"}})
        base.update(fields)
        d = self.make_job(JOB, **base)
        if base.get("round"):
            (d / f"round-{base['round']}").mkdir(exist_ok=True)
        return d

    def gate_verdict(self, verdict, rnd=1):
        write(self.jobs / JOB / f"round-{rnd}" / "checks.md",
              f"GATE: {verdict}\nCOMMIT: {self.head}\n\n## Summary\n- checks\n")

    def reviews(self, rnd=1, **verdicts):
        for r, v in verdicts.items():
            write(self.jobs / JOB / f"round-{rnd}" / f"review-{r}.md",
                  review_md(v, fail=(1,) if v == "CHANGES" else (), untested="none" if r == "spec" else None))
        write(self.jobs / JOB / "spec.md", SPEC_MD)

    def advance(self, stage):
        return self.bin("job", "advance", JOB, stage)

    def ok(self, res):
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return res

    def refused(self, res, says=None):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        if says:
            self.assertIn(says, res.stderr)
        return res

    def decision(self):
        return (self.jobs / JOB / "decision.md").read_text()

    def spend_transcript(self, usd):
        """A subagent transcript tied to this job, worth `usd` at opus input price."""
        mangled = "".join(c if c.isalnum() else "-" for c in str(self.root))
        path = self.tmp / "claude-config" / "projects" / mangled / "s1" / "subagents" / "agent-1.jsonl"
        first = {"message": {"content": f"Job: {JOB}. Job folder: {self.jobs / JOB}/. Worktree: x."}}
        price = self.config["prices_usd_per_mtok"]["claude-opus-5-5"]["input"]
        msg = {"type": "assistant", "message": {"id": "m1", "model": "claude-opus-5-5",
                                                "usage": {"input_tokens": int(usd / price * 1e6), "output_tokens": 0}}}
        write(path, json.dumps(first) + "\n" + json.dumps(msg) + "\n")


class RetryBudget(BudgetCase):
    # ---- neighbours that pass ----

    def test_gate_failure_spends_one_retry(self):
        self.job(stage="gate", round=1, retries_left=3)
        self.gate_verdict("FAIL")
        self.ok(self.advance("build"))
        job = self.read_job(JOB)
        self.assertEqual((job["stage"], job["round"], job["retries_left"]), ("build", 2, 2))

    def test_review_changes_spend_one_retry(self):
        self.job(stage="review", round=1, retries_left=2, reviews={"code": "pending", "spec": "pending"})
        self.reviews(code="CHANGES", spec="PASS")
        self.ok(self.advance("build"))
        self.assertEqual(self.read_job(JOB)["retries_left"], 1)

    def test_passing_gate_spends_nothing(self):
        self.job(stage="gate", round=1, retries_left=1)
        self.gate_verdict("PASS")
        self.ok(self.advance("review"))
        self.assertEqual(self.read_job(JOB)["retries_left"], 1)

    # ---- blocked ----

    def test_spending_the_last_retry_goes_to_a_human_with_a_question(self):
        self.job(stage="review", round=3, retries_left=1, reviews={"code": "pending", "spec": "pending"})
        self.reviews(rnd=3, code="CHANGES", spec="CHANGES")
        before = self.read_job(JOB)
        self.refused(self.advance("build"), says="retry budget")
        self.assertEqual(self.read_job(JOB), before)
        self.ok(self.advance("needs-human"))
        job = self.read_job(JOB)
        self.assertEqual((job["stage"], job["retries_left"], job["exit"]), ("needs-human", 0, "budget"))
        text = self.decision()
        self.assertTrue(text.startswith("ESCALATE\n"))
        self.assertIn("## Question", text)
        self.assertIn("code, spec", text)
        self.assertTrue(any("needs a human" in c for c in self.world.comments(self.issue)))
        self.assertIn("factory:needs-human", self.world.labels(self.issue))

    def test_budget_never_refills_after_feedback(self):
        self.job(stage="needs-human", round=3, retries_left=0, exit="budget",
                 ended="2026-11-19T01:00:00Z", running_since=None)
        write(self.jobs / JOB / "decision.md", "ESCALATE\n\n## Why\nspent\n")
        self.ok(self.bin("job", "feedback", JOB, stdin="Do it this way.\n"))
        job = self.read_job(JOB)
        self.assertEqual((job["stage"], job["round"], job["retries_left"], job["exit"]), ("build", 4, 0, None))
        # The next failure goes straight back to a human.
        write(self.jobs / JOB / "round-4" / "checks.md", f"GATE: FAIL\nCOMMIT: {self.head}\n")
        job["stage"] = "gate"
        (self.jobs / JOB / "job.json").write_text(json.dumps(job))
        self.refused(self.advance("build"), says="retry budget")
        self.ok(self.advance("needs-human"))
        self.assertEqual(self.read_job(JOB)["exit"], "budget")

    # ---- input not understood ----

    def test_malformed_retry_budget_is_refused(self):
        for bad in ("3", 0, -1, 1.5, True, None):
            with self.subTest(retry_budget=bad):
                self.config["retry_budget"] = bad
                self.write_config()
                self.job(stage="gate", round=1, retries_left=3)
                self.gate_verdict("FAIL")
                before = self.read_job(JOB)
                self.refused(self.advance("build"), says="retry_budget")
                self.assertEqual(self.read_job(JOB), before)

    def test_job_without_a_budget_is_refused(self):
        d = self.job(stage="gate", round=1)
        job = self.read_job(JOB)
        del job["retries_left"]
        write(d / "job.json", json.dumps(job))
        self.gate_verdict("FAIL")
        self.refused(self.advance("build"), says="retries_left")
        self.assertNotIn("retries_left", self.read_job(JOB))


class Caps(BudgetCase):
    def spec_job(self, **fields):
        d = self.job(stage="spec", **fields)
        write(d / "spec.md", "# Spec\n")
        return d

    # ---- blocked ----

    def test_cost_over_the_cap_stops_the_job(self):
        self.config["max_cost_usd"] = 2
        self.write_config()
        self.spec_job()
        self.spend_transcript(4.0)
        res = self.refused(self.advance("build"), says="cost")
        job = self.read_job(JOB)
        self.assertEqual((job["stage"], job["exit"]), ("needs-human", "budget"))
        self.assertIn("max_cost_usd", self.decision())
        self.assertIn("stopped", res.stderr)
        self.assertTrue(any("max_cost_usd" in c for c in self.world.comments(self.issue)))

    def test_duration_over_the_cap_stops_the_job(self):
        self.config["max_duration_minutes"] = 60
        self.write_config()
        self.spec_job(running_since=iso(datetime.now(timezone.utc) - timedelta(minutes=61)))
        self.refused(self.advance("build"), says="duration")
        job = self.read_job(JOB)
        self.assertEqual((job["stage"], job["exit"]), ("needs-human", "timeout"))
        self.assertIn("max_duration_minutes", self.decision())

    def test_feedback_cannot_restart_a_job_over_its_cap(self):
        self.config["max_duration_minutes"] = 60
        self.write_config()
        self.job(stage="needs-human", round=1, exit="timeout", active_seconds=3700, running_since=None,
                 ended="2026-11-19T01:00:00Z")
        write(self.jobs / JOB / "decision.md", "ESCALATE\n\n## Why\nslow\n")
        before = self.read_job(JOB)
        self.refused(self.bin("job", "feedback", JOB, stdin="Go on.\n"), says="max_duration_minutes")
        self.assertEqual(self.read_job(JOB), before)

    # ---- neighbours that pass ----

    def test_under_both_caps_the_step_starts(self):
        self.config["max_cost_usd"] = 5
        self.write_config()
        self.spec_job()
        self.spend_transcript(1.0)
        self.ok(self.advance("build"))
        self.assertEqual(self.read_job(JOB)["exit"], None)

    def test_waiting_time_does_not_count(self):
        self.config["max_duration_minutes"] = 60
        self.write_config()
        self.spec_job(started="2000-01-01T00:00:00Z", active_seconds=600)
        self.ok(self.advance("build"))

    def test_waiting_resets_the_running_clock(self):
        self.job(stage="needs-human", round=1, retries_left=2, exit="human", running_since=None,
                 active_seconds=120, ended="2026-11-19T01:00:00Z")
        write(self.jobs / JOB / "decision.md", "ESCALATE\n\n## Why\nx\n")
        self.ok(self.bin("job", "feedback", JOB, stdin="Go on.\n"))
        job = self.read_job(JOB)
        self.assertEqual(job["active_seconds"], 120)
        self.assertIsNotNone(job["running_since"])

    # ---- input not understood ----

    def test_malformed_caps_are_refused(self):
        original = dict(self.config)
        for key in ("max_cost_usd", "max_duration_minutes"):
            for bad in ("25", 0, -1, True, None):
                with self.subTest(key=key, value=bad):
                    self.config = dict(original)
                    self.config[key] = bad
                    self.write_config()
                    self.spec_job()
                    before = self.read_job(JOB)
                    self.refused(self.advance("build"), says=key)
                    self.assertEqual(self.read_job(JOB), before)
                    self.assertEqual(self.gh_calls(), [])

    def test_unreadable_clock_is_refused(self):
        self.spec_job(running_since="yesterday")
        before = self.read_job(JOB)
        self.refused(self.advance("build"), says="running_since")
        self.assertEqual(self.read_job(JOB), before)


class Inconclusive(BudgetCase):
    # ---- neighbour that passes ----

    def test_first_inconclusive_reruns_the_gate_without_spending(self):
        self.job(stage="gate", round=1, retries_left=1)
        self.gate_verdict("INCONCLUSIVE")
        self.ok(self.advance("gate"))
        job = self.read_job(JOB)
        self.assertEqual((job["stage"], job["round"], job["retries_left"], job["inconclusive"]),
                         ("gate", 1, 1, 1))
        rd = self.jobs / JOB / "round-1"
        self.assertFalse((rd / "checks.md").exists(), "the next advance needs a fresh gate run")
        self.assertTrue((rd / "checks-inconclusive-1.md").exists())

    # ---- blocked ----

    def test_second_inconclusive_escalates(self):
        self.job(stage="gate", round=1, retries_left=2, inconclusive=1)
        self.gate_verdict("INCONCLUSIVE")
        before = self.read_job(JOB)
        self.refused(self.advance("gate"), says="once")
        self.refused(self.advance("build"), says="INCONCLUSIVE")
        self.assertEqual(self.read_job(JOB), before)
        self.ok(self.advance("needs-human"))
        job = self.read_job(JOB)
        self.assertEqual((job["stage"], job["retries_left"], job["exit"]), ("needs-human", 2, "human"))
        self.assertIn("inconclusive", self.decision())

    def test_inconclusive_cannot_escalate_before_its_rerun(self):
        self.job(stage="gate", round=1)
        self.gate_verdict("INCONCLUSIVE")
        self.refused(self.advance("needs-human"), says="run the gate once more")

    def test_a_new_round_gets_a_new_rerun(self):
        self.job(stage="gate", round=1, retries_left=3, inconclusive=1)
        self.gate_verdict("FAIL")
        self.ok(self.advance("build"))
        self.assertEqual(self.read_job(JOB)["inconclusive"], 0)

    # ---- input not understood ----

    def test_unknown_gate_verdict_is_refused(self):
        for verdict in ("MAYBE", "inconclusive", ""):
            with self.subTest(verdict=verdict):
                self.job(stage="gate", round=1)
                self.gate_verdict(verdict)
                before = self.read_job(JOB)
                for target in ("gate", "build", "review", "needs-human"):
                    self.refused(self.advance(target))
                self.assertEqual(self.read_job(JOB), before)


class FiveExits(BudgetCase):
    def job(self, **fields):
        # No worktree: a terminal stage would remove it from the main checkout.
        fields.setdefault("worktree", str(self.tmp / "no-worktree"))
        return super().job(**fields)

    def test_each_stop_names_its_exit(self):
        # human: the builder is blocked.
        self.job(stage="build", round=1)
        write(self.jobs / JOB / "build.md", "STATUS: BLOCKED\n\n## Blocked\nno access\n")
        self.ok(self.advance("needs-human"))
        self.assertEqual(self.read_job(JOB)["exit"], "human")
        # failure: a human rejects it.
        self.ok(self.bin("job", "reject", JOB, stdin="Not worth it.\n"))
        self.assertEqual(self.read_job(JOB)["exit"], "failure")

    def test_merged_is_success(self):
        self.use_origin()  # the merged job is archived there
        n, head = self.world.mr()
        self.world.edit(lambda s: s["pulls"][str(n)].update(merged=True, state="closed"))
        self.job(stage="review", round=1, pr=n)
        self.ok(self.advance("merged"))
        job = self.read_job(JOB)
        self.assertEqual(job["exit"], "success")
        self.assertIsNone(job["running_since"])

    def test_intake_needs_info_is_a_human_exit(self):
        d = self.job(stage="intake")
        write(d / "intake.md", "DECISION: NEEDS-INFO\nRISK: low\nSURFACES: none\nRESCOPED: no\n\nWhich page?\n")
        self.ok(self.advance("needs-info"))
        self.assertEqual(self.read_job(JOB)["exit"], "human")

    def test_running_job_has_no_exit_and_summary_shows_exits(self):
        self.job(stage="spec")
        self.assertIsNone(self.read_job(JOB)["exit"])
        res = self.ok(self.bin("job", "summary"))
        self.assertIn("exit", res.stdout.splitlines()[0])

    def test_unknown_stored_exit_is_refused(self):
        self.job(stage="needs-human", round=1, exit="maybe", running_since=None)
        write(self.jobs / JOB / "decision.md", "ESCALATE\n\n## Why\nx\n")
        self.refused(self.bin("job", "feedback", JOB, stdin="x\n"), says="exit")


if __name__ == "__main__":
    unittest.main()
