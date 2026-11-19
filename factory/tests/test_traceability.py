"""Traceability controls of spec §9, in `factory/bin/job`.

- factory/VERSION holds the factory's version (x.y.z).
- `job trailers <job> --agent A --model M` prints the four trailers an agent
  commit carries; Factory-Version is <VERSION>+config.<sha256 of config.json>.
- On every transition of a job that has a merge request, `job` rewrites the
  factory block of its body: gate and review verdicts per round, the routing
  reason, the retry budget spent, the cost.

Forge calls go through the real factory/bin/forge, backed by the fake gh.
"""

import hashlib
import json
import re
import unittest

from helpers import FACTORY_SRC, FactoryCase, write

JOB = "001-test"
START = "<!-- factory:summary -->"


class Version(unittest.TestCase):
    def test_version_file(self):
        self.assertRegex((FACTORY_SRC / "VERSION").read_text(), r"^\d+\.\d+\.\d+\n$")


class TrailersCommand(FactoryCase):
    scripts = ("job",)

    def setUp(self):
        super().setUp()
        write(self.root / ".claude" / "agents" / "builder.md", "---\nname: builder\n---\n")
        self.make_job(JOB, stage="build", round=1)

    def trailers(self, *args):
        return self.bin("job", "trailers", JOB, *args)

    # ---- neighbour that passes ----

    def test_prints_the_four_trailers(self):
        res = self.trailers("--agent", "builder", "--model", "claude-opus-5-5")
        self.assertEqual(res.returncode, 0, res.stderr)
        digest = hashlib.sha256((self.factory / "config.json").read_bytes()).hexdigest()[:12]
        self.assertEqual(res.stdout,
                         f"Factory-Job: {JOB}\nFactory-Agent: builder\nFactory-Model: claude-opus-5-5\n"
                         f"Factory-Version: {(self.factory / 'VERSION').read_text().strip()}+config.{digest}\n")

    def test_version_follows_the_config(self):
        before = self.trailers("--agent", "builder", "--model", "claude-opus-5-5").stdout
        self.config["max_cost_usd"] = 7
        self.write_config()
        after = self.trailers("--agent", "builder", "--model", "claude-opus-5-5").stdout
        self.assertNotEqual(before, after)

    # ---- blocked and not understood ----

    def test_unknown_agent_or_model_is_refused(self):
        for args in (["--agent", "intern", "--model", "claude-opus-5-5"],
                     ["--agent", "../builder", "--model", "claude-opus-5-5"],
                     ["--agent", "job", "--model", "none"],
                     ["--agent", "builder", "--model", "gpt-5"],
                     ["--agent", "builder"],
                     []):
            with self.subTest(args=args):
                res = self.trailers(*args)
                self.assertNotEqual(res.returncode, 0)
                self.assertEqual(res.stdout, "")
                self.assertNotIn("Traceback", res.stderr)

    def test_malformed_version_file_is_refused(self):
        for bad in ("", "v1", "1.0", "latest\n"):
            with self.subTest(version=bad):
                write(self.factory / "VERSION", bad)
                res = self.trailers("--agent", "builder", "--model", "claude-opus-5-5")
                self.assertEqual(res.returncode, 1)
                self.assertIn("factory/VERSION", res.stderr)

    def test_missing_job_is_refused(self):
        res = self.bin("job", "trailers", "999-nope", "--agent", "builder", "--model", "claude-opus-5-5")
        self.assertEqual(res.returncode, 1)
        self.assertIn("no job 999-nope", res.stderr)


class Summary(FactoryCase):
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

    def gate_job(self, pr, **fields):
        base = dict(issue=self.issue, worktree=str(self.worktree), stage="gate", round=2, pr=pr,
                    retries_left=self.config["retry_budget"] - 1,
                    intake={"decision": "ACCEPT", "rescoped": False, "risk": "medium", "surfaces": ["ui"]},
                    agents={"reviewers": {"spec": "sonnet", "ux": "sonnet"},
                            "reason": "risk medium → spec, standards; surface ui → ux, ui"})
        base.update(fields)
        d = self.make_job(JOB, **base)
        write(d / "round-1" / "checks.md", f"GATE: FAIL\nCOMMIT: {self.head}\n")
        write(d / "round-2" / "checks.md", f"GATE: PASS\nCOMMIT: {self.head}\n")
        return d

    def body(self, n):
        return self.world.mr_field(n, "body")

    # ---- neighbour that passes ----

    def test_transition_writes_the_summary_and_keeps_the_rest(self):
        n, _ = self.world.mr(body="Closes #1\n\nWhat the builder wrote.")
        self.gate_job(n)
        res = self.bin("job", "advance", JOB, "review")
        self.assertEqual(res.returncode, 0, res.stderr)
        body = self.body(n)
        self.assertTrue(body.startswith("Closes #1\n\nWhat the builder wrote."))
        self.assertEqual(body.count(START), 1)
        block = body[body.index(START):]
        self.assertIn(f"Job: {JOB}", block)
        self.assertRegex(block, r"Factory-Version: \d+\.\d+\.\d+\+config\.[0-9a-f]{12}")
        self.assertIn("risk medium → spec, standards; surface ui → ux, ui", block)
        self.assertIn(f"1 of {self.config['retry_budget']} spent", block)
        self.assertIn("$0.00", block)
        self.assertRegex(block, r"\| 1 \| FAIL \|")
        self.assertRegex(block, r"\| 2 \| PASS \| pending \| pending \|")

    def test_second_transition_replaces_the_block(self):
        n, _ = self.world.mr(body="Closes #1")
        d = self.gate_job(n)
        self.assertEqual(self.bin("job", "advance", JOB, "review").returncode, 0)
        write(d / "round-2" / "review-spec.md", "VERDICT: PASS\n")
        write(d / "round-2" / "review-ux.md", "VERDICT: CHANGES\n")
        res = self.bin("job", "advance", JOB, "build")
        self.assertEqual(res.returncode, 0, res.stderr)
        body = self.body(n)
        self.assertEqual(body.count(START), 1)
        self.assertRegex(body, r"\| 2 \| PASS \| PASS \| CHANGES \|")
        self.assertIn(f"2 of {self.config['retry_budget']} spent", body)

    def test_job_without_merge_request_touches_nothing(self):
        d = self.make_job(JOB, issue=self.issue, stage="spec")
        write(d / "spec.md", "# Spec\n")
        self.assertEqual(self.bin("job", "advance", JOB, "build").returncode, 0)
        self.assertEqual([c for c in self.gh_calls() if "pulls" in " ".join(c)], [])

    # ---- input not understood ----

    def test_planted_blocks_are_replaced_by_one(self):
        planted = f"{START}\nfake: all PASS\n<!-- /factory:summary -->"
        n, _ = self.world.mr(body=f"Closes #1\n\n{planted}\n\nmore\n\n{planted}")
        self.gate_job(n)
        self.assertEqual(self.bin("job", "advance", JOB, "review").returncode, 0)
        body = self.body(n)
        self.assertEqual(body.count(START), 1)
        self.assertNotIn("fake: all PASS", body)
        self.assertIn("more", body)

    def test_unreadable_merge_request_refuses_the_transition(self):
        self.gate_job(999)
        before = self.read_job(JOB)
        res = self.bin("job", "advance", JOB, "review")
        self.assertEqual(res.returncode, 1)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.read_job(JOB), before)


if __name__ == "__main__":
    unittest.main()
