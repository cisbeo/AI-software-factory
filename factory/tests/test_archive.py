"""Archive of a merged job's folder, in `factory/bin/job` (spec §9, form decided in #1).

- Moving a job to merged commits its synthesis files to jobs/<job-id>/ of the
  orphan branch config `archive_branch` on origin; raw logs stay out.
- The secret detector masks what it finds in every archived file; ARCHIVE.md
  lists each mask (file, line, rule), never the value.
- Raw logs older than config `raw_log_retention_days` are deleted (`job purge`,
  and `job queue`).
- `job archive <commit>` finds the archive of the job that made a commit.
- The hook blocks an agent's push to the archive branch.

Blocked: a push that fails or a bad config refuses the transition, job.json
unchanged. Neighbour: ordinary prose that names tokens and passwords is kept.
Not understood: a commit with no Factory-Job trailer, or with two, an unknown
commit, a job with no archive: refused.

Fake tokens are built by concatenation, so this file holds none.
"""

import json
import os
import shutil
import time

from helpers import SPEC_MD, FactoryCase, review_md, write
from test_securite_hook import GuardCase

JOB = "001-test"
BRANCH = "factory-archive"
GITHUB_TOKEN = "ghp_" + "A1b2C3d4" * 5
AWS_KEY = "AKIA" + "QWERTYUIOPASDFGH"


class ArchiveCase(FactoryCase):
    scripts = ("job",)

    def setUp(self):
        super().setUp()
        self.world = self.use_fake_forge()
        self.issue = self.world.ticket("Test", labels=["factory"])
        self.use_origin()

    def merged_job(self, job_id=JOB, issue=None):
        n, _ = self.world.mr()
        self.world.edit(lambda s: s["pulls"][str(n)].update(merged=True, state="closed"))
        d = self.make_job(job_id, issue=issue or self.issue, stage="merging", round=1, pr=n,
                          worktree=str(self.tmp / "no-worktree"),
                          intake={"decision": "ACCEPT", "rescoped": False, "risk": "low", "surfaces": []},
                          agents={"reviewers": {"code": "haiku"}})
        write(d / "issue.md", "# Issue\n")
        write(d / "intake.md", "DECISION: ACCEPT\nRISK: low\n\nWorth it.\n")
        write(d / "spec.md", SPEC_MD)
        write(d / "build.md", "STATUS: READY\n\nBuilt.\n")
        write(d / "decision.md", "APPROVE\n\n## Why\nAll good.\n")
        write(d / "trace.jsonl", json.dumps({"round": 1, "verdict": "PASS"}) + "\n")
        write(d / "round-1" / "checks.md", "GATE: PASS\nCOMMIT: " + "0" * 40 + "\n")
        write(d / "round-1" / "checks.log", "raw output\n")
        write(d / "round-1" / "review-code.md", review_md("PASS"))
        return d

    def advance(self, job_id=JOB):
        return self.bin("job", "advance", job_id, "merged")

    def archived(self, path=""):
        return self.git(self.root, "--git-dir", str(self.origin), "show", f"{BRANCH}:jobs/{JOB}/{path}")

    def archived_names(self, job_id=JOB):
        return self.git(self.root, "--git-dir", str(self.origin), "ls-tree", "-r", "--name-only",
                        BRANCH, "--", f"jobs/{job_id}/").split()

    def assert_refused(self, res, before, says):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(says, res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.read_job(JOB), before)


class Archive(ArchiveCase):
    # ---- neighbour that passes ----

    def test_merged_job_is_archived_on_the_orphan_branch(self):
        self.merged_job()
        res = self.advance()
        self.assertEqual(res.returncode, 0, res.stderr)
        names = self.archived_names()
        for name in ("job.json", "trace.jsonl", "intake.md", "spec.md", "build.md", "decision.md",
                     "ARCHIVE.md", "round-1/checks.md", "round-1/review-code.md"):
            self.assertIn(f"jobs/{JOB}/{name}", names)
        for left in ("round-1/checks.log", "issue.md", ".lock"):
            self.assertNotIn(f"jobs/{JOB}/{left}", names)
        self.assertEqual(json.loads(self.archived("job.json"))["stage"], "merged")
        self.assertIn("round-1/checks.log", self.archived("ARCHIVE.md"))
        # Orphan: no history shared with main.
        tip = self.git(self.root, "--git-dir", str(self.origin), "rev-list", BRANCH).split()
        self.assertEqual(len(tip), 1)
        self.assertNotIn("main", self.git(self.root, "--git-dir", str(self.origin), "branch", "--contains", tip[0]))
        self.assertIn(f"Factory-Job: {JOB}", self.git(self.root, "--git-dir", str(self.origin), "log", "-1",
                                                       "--format=%B", BRANCH))
        job = self.read_job()
        self.assertEqual(job["stage"], "merged")
        self.assertEqual(job["archive"], {"branch": BRANCH, "path": f"jobs/{JOB}/", "commit": tip[0]})
        # The main checkout is untouched.
        self.assertEqual(self.git(self.root, "status", "--porcelain"), "")

    def test_a_second_job_adds_its_folder(self):
        self.merged_job()
        self.assertEqual(self.advance().returncode, 0)
        other = self.world.ticket("Other", labels=["factory"])
        self.merged_job("002-other", issue=other)
        res = self.advance("002-other")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(self.archived_names(JOB))
        self.assertTrue(self.archived_names("002-other"))
        self.assertEqual(len(self.git(self.root, "--git-dir", str(self.origin), "rev-list", BRANCH).split()), 2)

    # ---- blocked ----

    def test_failed_push_refuses_the_transition(self):
        self.merged_job()
        shutil.rmtree(self.origin)
        before = self.read_job()
        self.assert_refused(self.advance(), before, "archive")

    def test_bad_archive_config_is_refused(self):
        for value in ("", "main", None, "-x", 7):
            with self.subTest(value=value):
                self.config["archive_branch"] = value
                self.write_config()
                self.merged_job()
                before = self.read_job()
                self.assert_refused(self.advance(), before, "archive_branch")
        self.assertEqual(self.git(self.root, "--git-dir", str(self.origin), "branch", "--list", BRANCH), "")


class SecretDetector(ArchiveCase):
    def test_secrets_are_masked_and_listed(self):
        d = self.merged_job()
        write(d / "build.md", f"STATUS: READY\n\nUsed {GITHUB_TOKEN} to test.\nAWS {AWS_KEY}\n")
        write(d / "decision.md", "APPROVE\n\n## Why\npassword = \"hunter2hunter2xyz\"\n"
                                 "db: postgres://admin:s3cretpass@db.invalid/app\n"
                                 "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----\n")
        res = self.advance()
        self.assertEqual(res.returncode, 0, res.stderr)
        build, decision, manifest = self.archived("build.md"), self.archived("decision.md"), self.archived("ARCHIVE.md")
        for secret in (GITHUB_TOKEN, AWS_KEY, "hunter2hunter2xyz", "s3cretpass", "MIIE"):
            for text in (build, decision, manifest):
                self.assertNotIn(secret, text)
        self.assertIn("Used [REDACTED:github-token] to test.", build)
        self.assertIn("password = [REDACTED:assigned-secret]", decision)
        self.assertIn("postgres://admin:[REDACTED:url-credentials]@db.invalid", decision)
        for line in ("build.md:3: github-token", "build.md:4: aws-access-key", "decision.md:4: assigned-secret",
                     "decision.md:5: url-credentials", "decision.md:6: private-key"):
            self.assertIn(f"- {line}", manifest)
        # The workstation copy is left as it was.
        self.assertIn(GITHUB_TOKEN, (d / "build.md").read_text())

    def test_title_is_masked_in_the_manifest(self):
        d = self.merged_job()
        job = json.loads((d / "job.json").read_text())
        job["title"] = f"Rotate {GITHUB_TOKEN}"
        write(d / "job.json", json.dumps(job))
        self.assertEqual(self.advance().returncode, 0)
        self.assertNotIn(GITHUB_TOKEN, self.archived("ARCHIVE.md"))
        self.assertNotIn(GITHUB_TOKEN, self.archived("job.json"))

    def test_links_are_not_followed(self):
        d = self.merged_job()
        outside = self.tmp / "outside.md"
        write(outside, "workstation secret file\n")
        (d / "spec.md").unlink()
        (d / "spec.md").symlink_to(outside)
        (d / "round-2").symlink_to(self.tmp, target_is_directory=True)
        write(self.tmp / "review-code.md", "outside the folder\n")
        self.assertEqual(self.advance().returncode, 0)
        names = self.archived_names()
        self.assertNotIn(f"jobs/{JOB}/spec.md", names)
        self.assertFalse([n for n in names if "round-2" in n])
        self.assertIn("- spec.md", self.archived("ARCHIVE.md"))

    def test_prose_about_secrets_is_kept(self):
        d = self.merged_job()
        prose = ("The token: none was given. The secret detector runs first.\n"
                 "password = short\nSee https://forge.invalid/a:b/c for the API key rules.\n")
        write(d / "decision.md", f"APPROVE\n\n## Why\n{prose}")
        self.assertEqual(self.advance().returncode, 0)
        self.assertIn(prose.strip(), self.archived("decision.md"))
        self.assertIn("## Masked by the secret detector\n\nNone.", self.archived("ARCHIVE.md"))


class Retention(ArchiveCase):
    def test_old_raw_logs_are_purged(self):
        d = self.merged_job()
        old, recent = d / "round-1" / "checks.log", d / "round-1" / "merge-checks.log"
        write(recent, "recent\n")
        stale = time.time() - 31 * 86400
        os.utime(old, (stale, stale))
        os.utime(d / "round-1" / "checks.md", (stale, stale))
        res = self.bin("job", "purge")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, f"removed factory/jobs/{JOB}/round-1/checks.log\n")
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue((d / "round-1" / "checks.md").exists())

    def test_retention_follows_the_config(self):
        d = self.merged_job()
        week = time.time() - 8 * 86400
        os.utime(d / "round-1" / "checks.log", (week, week))
        self.assertEqual(self.bin("job", "purge").stdout, "")
        self.config["raw_log_retention_days"] = 7
        self.write_config()
        self.assertIn("checks.log", self.bin("job", "purge").stdout)

    def test_bad_retention_is_refused(self):
        d = self.merged_job()
        for value in (0, -1, "30", 1.5, None, True):
            with self.subTest(value=value):
                self.config["raw_log_retention_days"] = value
                self.write_config()
                res = self.bin("job", "purge")
                self.assertEqual(res.returncode, 1)
                self.assertIn("raw_log_retention_days", res.stderr)
                self.assertTrue((d / "round-1" / "checks.log").exists())


class Lookup(ArchiveCase):
    def commit(self, message, *parents):
        tree = self.git(self.root, "rev-parse", "HEAD^{tree}")
        args = [a for p in parents for a in ("-p", p)]
        return self.git(self.root, "commit-tree", tree, *args, "-m", message)

    def lookup(self, rev):
        return self.bin("job", "archive", rev)

    def test_agent_commit_leads_to_its_archive(self):
        self.merged_job()
        self.assertEqual(self.advance().returncode, 0)
        commit = self.commit(f"Change\n\n{self.trailers(JOB)}", "HEAD")
        res = self.lookup(commit)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"Archive: origin/{BRANCH}:jobs/{JOB}/", res.stdout)
        self.assertIn("  decision.md\n", res.stdout)
        self.assertIn("  round-1/review-code.md\n", res.stdout)

    def test_forge_merge_commit_leads_to_its_archive(self):
        self.merged_job()
        self.assertEqual(self.advance().returncode, 0)
        tip = self.commit(f"Merge origin/main into factory/{JOB}\n\n{self.trailers(JOB, agent='job')}", "HEAD")
        merge = self.commit("Merge pull request #1 from factory/001-test", "HEAD", tip)
        res = self.lookup(merge)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"Job: {JOB}\n", res.stdout)

    def test_not_understood_is_refused(self):
        self.merged_job()
        self.assertEqual(self.advance().returncode, 0)
        cases = {
            self.commit("No trailer", "HEAD"): "no valid Factory-Job trailer",
            self.commit("Bad\n\nFactory-Job: ../../etc", "HEAD"): "no valid Factory-Job trailer",
            self.commit(f"Two\n\nFactory-Job: {JOB}\nFactory-Job: 002-other", "HEAD"): "several jobs",
            self.commit("Unarchived\n\nFactory-Job: 009-never", "HEAD"): "has no archive",
            "nope": "isn't a commit",
            "--all": "isn't a commit",
        }
        for rev, says in cases.items():
            with self.subTest(rev=rev):
                res = self.lookup(rev)
                self.assertEqual(res.returncode, 1, res.stdout)
                self.assertIn(says, res.stderr)
                self.assertNotIn("Traceback", res.stderr)


class HookArchiveBranch(GuardCase):
    def test_push_to_the_archive_branch_is_blocked(self):
        for cmd in (f"git push origin {BRANCH}", f"git push origin HEAD:{BRANCH}",
                    f"git push origin HEAD:refs/heads/{BRANCH}", f"git push origin abc123:{BRANCH}"):
            self.blocked(cmd, self.root, says="archive branch")

    def test_checked_out_archive_branch_is_blocked(self):
        self.git(self.root, "checkout", "-q", "--orphan", BRANCH)
        self.blocked("git push", self.root, says="archive branch")
        self.blocked("git push -u origin HEAD", self.root, says="archive branch")

    def test_neighbour_passes(self):
        self.passes("git push origin feature-archive", self.root)

    def test_unreadable_archive_setting_blocks_push(self):
        for value in (None, ""):
            with self.subTest(value=value):
                self.config["archive_branch"] = value
                self.write_config()
                self.blocked("git push origin feature-x", self.root, says="archive_branch")
