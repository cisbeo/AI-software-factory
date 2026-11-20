"""The gate runs twice (spec §7.1, §7.4): before the reviews, then in `job
merge`, after syncing the branch with the base, just before the merge. Only the
commit that passed that second gate is merged.

Fixture: a bare `origin.git`, a main checkout holding factory/bin/{job,gate},
config.json (auto_merge `approved`) and checks.sh, and the job's worktree. The
forge is a stub `factory/bin/forge` that keeps one merge request in a JSON
file and, like GitHub, refuses `mr merge --head SHA` unless SHA is the tip of
the job's branch on origin.

checks.sh fails when src/a.txt and src/b.txt both exist (a change on the base
that breaks the branch only once they meet), and answers exit 75 (a tool
unavailable) as many times as the number in `<ctl>/flaky`.
"""

import json
import unittest

from helpers import SPEC_MD, FactoryCase, review_md, write

JOB = "001-test"
PR = 7

CHECKS = """#!/usr/bin/env bash
ctl="CTL"
if [ -e src/a.txt ] && [ -e src/b.txt ]; then
  echo "src/a.txt and src/b.txt clash: remove one" >&2
  exit 1
fi
if [ -e "$ctl/flaky" ]; then
  n=$(cat "$ctl/flaky")
  if [ "$n" -gt 0 ]; then
    echo $((n - 1)) > "$ctl/flaky"
    echo "tool unavailable" >&2
    exit 75
  fi
fi
echo BASE-CHECKS ok
"""

FORGE = r'''#!/usr/bin/env python3
import json, subprocess, sys
STATE, ORIGIN, BRANCH = "STATE_PATH", "ORIGIN_PATH", "BRANCH_NAME"
args = sys.argv[1:]
with open(STATE) as f:
    s = json.load(f)
s["calls"].append(args)
out = None
code = 0
if args[:1] == ["whoami"]:
    out = {"login": "operator"}
elif args[:2] == ["mr", "view"]:
    out = {"number": int(args[2]), "state": s["state"], "body": s["body"], "draft": s["draft"]}
elif args[:2] == ["mr", "edit"]:
    s["body"] = args[args.index("--body") + 1]
elif args[:2] == ["mr", "ready"]:
    s["draft"] = False
elif args[:2] in (["mr", "comment"], ["ticket", "comment"], ["ticket", "label"]):
    pass
elif args[:2] == ["mr", "merge"]:
    head = args[args.index("--head") + 1]
    tip = subprocess.run(["git", "--git-dir", ORIGIN, "rev-parse", "refs/heads/" + BRANCH],
                         capture_output=True, text=True).stdout.strip()
    if head != tip:
        print(f"forge: head of the merge request is {tip[:7]}, not {head[:7]}", file=sys.stderr)
        code = 1
    else:
        s.update(state="merged", merged_head=head)
else:
    print(f"forge stub: unexpected {args}", file=sys.stderr)
    code = 1
with open(STATE, "w") as f:
    json.dump(s, f)
if out is not None:
    print(json.dumps(out))
sys.exit(code)
'''

STUB_GATE = """#!/usr/bin/env bash
# A gate that says it passed, and leaves a merge-checks.md that says otherwise.
mkdir -p "JOBDIR/round-1"
printf 'GATE: PASS\\nCOMMIT: %s\\n\\n## Summary\\n- stub\\n' "WHICH" > "JOBDIR/round-1/merge-checks.md"
echo "GATE: PASS (stub)"
"""


class MergeCase(FactoryCase):
    scripts = ("job", "gate")

    def setUp(self):
        super().setUp()
        self.config["auto_merge"] = "approved"
        self.write_config()
        self.origin = self.tmp / "origin.git"
        self.ctl = self.tmp / "ctl"
        self.ctl.mkdir()
        self.git(self.tmp, "init", "--bare", "-q", str(self.origin))
        write(self.root / ".gitignore", "/factory/jobs/\n/.worktrees/\n")
        write(self.factory / "checks.sh", CHECKS.replace("CTL", str(self.ctl)), mode=0o755)
        write(self.root / "src" / "app.txt", "hello\n")
        write(self.root / ".claude" / "agents" / "builder.md", "---\nname: builder\n---\n")
        self.state = self.tmp / "forge.json"
        self.state.write_text(json.dumps({"state": "open", "body": "Closes #1", "draft": True,
                                          "merged_head": None, "calls": []}))
        write(self.factory / "bin" / "forge",
              FORGE.replace("STATE_PATH", str(self.state)).replace("ORIGIN_PATH", str(self.origin))
              .replace("BRANCH_NAME", f"factory/{JOB}"), mode=0o755)
        self.git(self.root, "init", "-q")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "base")
        self.git(self.root, "remote", "add", "origin", str(self.origin))
        self.git(self.root, "push", "-q", "origin", "HEAD:main")
        self.git(self.root, "fetch", "-q", "origin")
        self.worktree = self.root / ".worktrees" / JOB
        self.git(self.root, "worktree", "add", "-q", "-b", f"factory/{JOB}", str(self.worktree), "origin/main")
        self.reviewed = self.commit_on_branch({"src/a.txt": "a\n"})
        self.job("gate")
        (self.jobs / JOB / "round-1").mkdir()
        res = self.bin("gate", JOB)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    # ---- fixtures ----

    def job(self, stage):
        self.make_job(JOB, stage=stage, round=1, pr=PR, pr_url="https://forge.invalid/pr/7",
                      worktree=str(self.worktree),
                      intake={"decision": "ACCEPT", "rescoped": False, "risk": "low", "surfaces": []},
                      agents={"reviewers": {"code": "haiku"}})

    def commit_on_branch(self, files, push=True):
        for rel, text in files.items():
            write(self.worktree / rel, text)
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-q", "-m", "change\n\n" + self.trailers(JOB))
        if push:
            self.git(self.worktree, "push", "-q", "origin", f"factory/{JOB}")
        return self.git(self.worktree, "rev-parse", "HEAD")

    def approved(self):
        self.job("approve")
        write(self.jobs / JOB / "round-1" / "review-code.md", review_md())
        write(self.jobs / JOB / "spec.md", SPEC_MD)
        write(self.jobs / JOB / "decision.md", "APPROVE\n\nFine.\n")

    def main_moves(self, files):
        for rel, text in files.items():
            write(self.root / rel, text)
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "main moves")
        self.git(self.root, "push", "-q", "origin", "HEAD:main")

    def merge(self):
        return self.bin("job", "merge", JOB)

    def forge_state(self):
        return json.loads(self.state.read_text())

    def merge_calls(self):
        return [c for c in self.forge_state()["calls"] if c[:2] == ["mr", "merge"]]

    def gate_traces(self):
        path = self.jobs / JOB / "trace.jsonl"
        return [t for t in map(json.loads, path.read_text().splitlines()) if t.get("control") == "gate"]

    def header(self, name):
        lines = (self.jobs / JOB / "round-1" / f"{name}.md").read_text().split("\n\n", 1)[0]
        return dict(line.split(": ", 1) for line in lines.splitlines())

    def assert_not_merged(self, res, says):
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.read_job(JOB)["stage"], "needs-human", res.stdout)
        self.assertEqual(self.merge_calls(), [])
        self.assertIsNone(self.forge_state()["merged_head"])
        self.assertIn(says, (self.jobs / JOB / "decision.md").read_text())

    def assert_merged(self, res):
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.read_job(JOB)["stage"], "merged", res.stdout + res.stderr)
        [call] = self.merge_calls()
        head = call[call.index("--head") + 1]
        self.assertEqual(self.forge_state()["merged_head"], head)
        self.assertEqual(self.header("merge-checks"), {"GATE": "PASS", "COMMIT": head})
        return head


class SecondGate(MergeCase):
    # ---- blocked ----

    def test_base_that_breaks_the_branch_is_not_merged(self):
        self.approved()
        self.main_moves({"src/b.txt": "b\n"})
        res = self.merge()
        self.assert_not_merged(res, "The gate failed after syncing with main")
        self.assertEqual(self.header("merge-checks")["GATE"], "FAIL")
        first, second = self.gate_traces()
        self.assertEqual((first["merge"], first["verdict"], first["commit"]), (False, "PASS", self.reviewed))
        self.assertEqual((second["merge"], second["verdict"]), (True, "FAIL"))

    def test_commit_pushed_after_the_reviews_is_not_merged(self):
        self.approved()
        late = self.commit_on_branch({"src/late.txt": "unreviewed\n"})
        res = self.merge()
        self.assert_not_merged(res, f"{late[:7]} isn't the commit the gate passed before the reviews")
        self.assertEqual([t["merge"] for t in self.gate_traces()], [False])

    # ---- neighbours that pass ----

    def test_base_that_moved_elsewhere_merges_the_gated_merge_commit(self):
        self.approved()
        self.main_moves({"src/c.txt": "c\n"})
        head = self.assert_merged(self.merge())
        self.assertNotEqual(head, self.reviewed)
        parents = self.git(self.root, "--git-dir", str(self.origin), "rev-list", "--parents", "-n", "1", head).split()
        self.assertIn(self.reviewed, parents[1:])
        first, second = self.gate_traces()
        self.assertEqual((first["merge"], first["commit"]), (False, self.reviewed))
        self.assertEqual((second["merge"], second["verdict"], second["commit"]), (True, "PASS", head))

    def test_base_that_did_not_move_merges_the_reviewed_commit(self):
        self.approved()
        self.assertEqual(self.assert_merged(self.merge()), self.reviewed)

    # ---- input not understood: no merge ----

    def test_gate_that_passes_for_another_commit_does_not_merge(self):
        self.approved()
        self.main_moves({"src/c.txt": "c\n"})
        jobdir = str(self.jobs / JOB)
        write(self.factory / "bin" / "gate",
              STUB_GATE.replace("JOBDIR", jobdir).replace("WHICH", self.reviewed), mode=0o755)
        res = self.merge()
        self.assert_not_merged(res, "merge-checks.md")

    def test_gate_that_passes_without_a_verdict_file_does_not_merge(self):
        self.approved()
        write(self.factory / "bin" / "gate", "#!/usr/bin/env bash\necho 'GATE: PASS'\n", mode=0o755)
        res = self.merge()
        self.assert_not_merged(res, "merge-checks.md")

    def test_stale_merge_checks_from_an_earlier_attempt_are_not_trusted(self):
        self.approved()
        write(self.jobs / JOB / "round-1" / "merge-checks.md", f"GATE: PASS\nCOMMIT: {self.reviewed}\n\n")
        write(self.factory / "bin" / "gate", "#!/usr/bin/env bash\necho 'GATE: PASS'\n", mode=0o755)
        res = self.merge()
        self.assert_not_merged(res, "merge-checks.md")


class SecondGateInconclusive(MergeCase):
    # ---- inconclusive twice: a human, never a merge ----

    def test_twice_inconclusive_after_sync_goes_to_a_human(self):
        self.approved()
        (self.ctl / "flaky").write_text("2\n")
        res = self.merge()
        self.assert_not_merged(res, "The gate was inconclusive twice after syncing with main")
        self.assertEqual([t["verdict"] for t in self.gate_traces() if t["merge"]], ["INCONCLUSIVE", "INCONCLUSIVE"])
        self.assertNotEqual(self.read_job(JOB)["exit"], "budget")

    # ---- neighbour: once inconclusive, then a verdict ----

    def test_once_inconclusive_then_pass_merges(self):
        self.approved()
        (self.ctl / "flaky").write_text("1\n")
        self.assert_merged(self.merge())
        self.assertEqual([t["verdict"] for t in self.gate_traces() if t["merge"]], ["INCONCLUSIVE", "PASS"])

    def test_inconclusive_is_not_a_failure(self):
        self.approved()
        (self.ctl / "flaky").write_text("2\n")
        self.merge()
        self.assertNotIn("The gate failed", (self.jobs / JOB / "decision.md").read_text())


class FirstGate(MergeCase):
    """review → approve only while HEAD is the commit the first gate passed."""

    def reviewed_job(self):
        self.job("review")
        write(self.jobs / JOB / "round-1" / "review-code.md", review_md())
        write(self.jobs / JOB / "spec.md", SPEC_MD)

    # ---- blocked ----

    def test_commit_after_the_gate_blocks_approval(self):
        self.reviewed_job()
        self.commit_on_branch({"src/late.txt": "unreviewed\n"})
        res = self.bin("job", "advance", JOB, "approve")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("isn't the commit the gate passed", res.stderr)
        self.assertEqual(self.read_job(JOB)["stage"], "review")

    # ---- neighbour ----

    def test_gated_commit_is_approved(self):
        self.reviewed_job()
        res = self.bin("job", "advance", JOB, "approve")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.read_job(JOB)["stage"], "approve")

    # ---- input not understood ----

    def test_unreadable_checks_md_blocks_approval(self):
        self.reviewed_job()
        for text in ("", "GATE: PASS\n", f"GATE: pass\nCOMMIT: {self.reviewed}\n", f"GATE: FAIL\nCOMMIT: {self.reviewed}\n"):
            with self.subTest(text=text):
                write(self.jobs / JOB / "round-1" / "checks.md", text)
                res = self.bin("job", "advance", JOB, "approve")
                self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
                self.assertEqual(self.read_job(JOB)["stage"], "review")


if __name__ == "__main__":
    unittest.main()
