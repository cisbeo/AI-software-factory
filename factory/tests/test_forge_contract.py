"""Contract tests for factory/bin/forge (spec §10, ADR 0005).

Every forge adapter must pass this suite. By default it runs offline against
a fake `gh` (factory/tests/fake_gh.py). To play it against a real throwaway
repository, opt in:

    FORGE_CONTRACT_REPO=owner/name python3 -B -m unittest factory/tests/test_forge_contract.py

The repository must have a `main` branch, and the authenticated `gh` must be
allowed to create tickets, branches and merge requests there, and to merge
them. Tests that need what a single account can't set up on a real forge
(another author, checks, approvals, protection) are skipped in that mode.
Everything a live run creates is closed or deleted at the end.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

TESTS = Path(__file__).resolve().parent
FORGE = TESTS.parent / "bin" / "forge"
LIVE_REPO = os.environ.get("FORGE_CONTRACT_REPO")

# Keys a neutral output must never use (spec §10: « ticket », « demande de fusion »).
FORGE_WORDS = re.compile(r"pull|issue|^pr$|^pr_|merge_request|^mr_|^iid$", re.I)


def keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from keys(v)


class FakeWorld:
    """In-memory GitHub behind the fake gh."""

    live = False
    user = "operator"

    def __init__(self, tmp):
        self.state_path = Path(tmp) / "state.json"
        bindir = Path(tmp) / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(f'#!/bin/sh\nexec python3 -B "{TESTS / "fake_gh.py"}" "$@"\n')
        gh.chmod(0o755)
        self.log = Path(tmp) / "gh.log"
        self.bindir = bindir
        self.save({"user": self.user, "next": 0, "issues": {}, "comments": {}, "deps": {},
                   "pulls": {}, "check_runs": {}, "statuses": {}, "reviews": {},
                   "protection": {}, "rules": {}})

    def env(self):
        env = dict(os.environ)
        env.pop("FORGE_REPO", None)
        env.update(PATH=f"{self.bindir}:{env['PATH']}", FAKE_GH_STATE=str(self.state_path),
                   FAKE_GH_LOG=str(self.log), FORGE="github")
        return env

    def load(self):
        return json.loads(self.state_path.read_text())

    def save(self, state):
        self.state_path.write_text(json.dumps(state))

    def edit(self, fn):
        state = self.load()
        out = fn(state)
        self.save(state)
        return out

    def ticket(self, title, body="", labels=(), author=None):
        def add(s):
            s["next"] += 1
            n = s["next"]
            s["issues"][str(n)] = {"number": n, "title": title, "body": body,
                                   "user": {"login": author or self.user}, "state": "open",
                                   "labels": [{"name": l} for l in labels],
                                   "html_url": f"https://github.test/o/r/issues/{n}"}
            return n
        return self.edit(add)

    def comment(self, n, body, author=None):
        def add(s):
            cs = s["comments"].setdefault(str(n), [])
            cs.append({"user": {"login": author or self.user}, "body": body,
                       "created_at": f"2026-11-19T09:{len(cs):02d}:00Z"})
        self.edit(add)

    def close(self, n, reason="completed"):
        self.edit(lambda s: s["issues"][str(n)].update(state="closed", state_reason=reason))

    def block(self, n, by):
        self.edit(lambda s: s["deps"].setdefault(str(n), []).append(by))

    def without_native_dependencies(self, code=404):
        self.edit(lambda s: s.update(deps_unavailable=code))

    def rules_unreadable(self):
        self.edit(lambda s: s.update(rules_error=500))

    def mr(self, title="Change", body="", draft=True):
        head = f"forge-test-{uuid.uuid4().hex[:8]}"

        def add(s):
            s["next"] += 1
            n = s["next"]
            sha = f"{n:040x}"
            s["pulls"][str(n)] = {"number": n, "title": title, "body": body, "draft": draft,
                                  "state": "open", "merged": False, "merged_at": None,
                                  "user": {"login": self.user},
                                  "head": {"ref": head, "sha": sha}, "base": {"ref": "main"},
                                  "html_url": f"https://github.test/o/r/pull/{n}"}
            s["issues"][str(n)] = {"number": n, "title": title, "body": body,
                                   "user": {"login": self.user}, "state": "open", "labels": [],
                                   "html_url": f"https://github.test/o/r/pull/{n}",
                                   "pull_request": {"url": "x"}}
            return n
        return self.edit(add), head

    def branch(self):
        return f"forge-test-{uuid.uuid4().hex[:8]}"

    def push(self, n):
        def move(s):
            s["next"] += 1
            s["pulls"][str(n)]["head"]["sha"] = f"{s['next']:040x}"
        self.edit(move)

    def head_sha(self, n):
        return self.load()["pulls"][str(n)]["head"]["sha"]

    def is_merged(self, n):
        return self.load()["pulls"][str(n)]["merged"]

    def labels(self, n):
        return {l["name"] for l in self.load()["issues"][str(n)]["labels"]}

    def comments(self, n):
        return [c["body"] for c in self.load()["comments"].get(str(n), [])]

    def mr_field(self, n, key):
        return self.load()["pulls"][str(n)][key]

    def check(self, sha, name, status, conclusion=None):
        self.edit(lambda s: s["check_runs"].setdefault(sha, []).append(
            {"name": name, "status": status, "conclusion": conclusion}))

    def status(self, sha, context, state):
        self.edit(lambda s: s["statuses"].setdefault(sha, []).append({"context": context, "state": state}))

    def review(self, n, author, state, commit=None):
        sha = commit or self.head_sha(n)
        self.edit(lambda s: s["reviews"].setdefault(str(n), []).append(
            {"user": {"login": author}, "state": state, "commit_id": sha}))

    def protect(self, branch, protection):
        self.edit(lambda s: s["protection"].update({branch: protection}))


class LiveWorld:
    """A real GitHub repository, through the real gh."""

    live = True

    def __init__(self, case, repo):
        self.case, self.repo = case, repo
        self.user = self.api("user")["login"]

    def env(self):
        env = dict(os.environ)
        env.update(FORGE_REPO=self.repo, FORGE="github")
        return env

    def api(self, path, method="GET", payload=None):
        cmd = ["gh", "api", "-X", method, path]
        if payload is not None:
            cmd += ["--input", "-"]
        res = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None,
                             capture_output=True, text=True)
        if res.returncode != 0:
            raise AssertionError(f"{' '.join(cmd)}: {res.stderr.strip()}")
        return json.loads(res.stdout) if res.stdout.strip() else None

    def r(self, rest):
        return f"repos/{self.repo}/{rest}"

    def skip(self, why):
        raise unittest.SkipTest(f"not settable on a live forge: {why}")

    def ticket(self, title, body="", labels=(), author=None):
        if author:
            self.skip("another author")
        n = self.api(self.r("issues"), "POST", {"title": title, "body": body, "labels": list(labels)})["number"]
        self.case.addCleanup(self.api, self.r(f"issues/{n}"), "PATCH", {"state": "closed"})
        return n

    def comment(self, n, body, author=None):
        if author:
            self.skip("another author")
        self.api(self.r(f"issues/{n}/comments"), "POST", {"body": body})

    def close(self, n, reason="completed"):
        self.api(self.r(f"issues/{n}"), "PATCH", {"state": "closed", "state_reason": reason})

    def block(self, n, by):
        issue_id = self.api(self.r(f"issues/{by}"))["id"]
        self.api(self.r(f"issues/{n}/dependencies/blocked_by"), "POST", {"issue_id": issue_id})

    def without_native_dependencies(self, code=404):
        self.skip("native dependencies can't be switched off")

    def rules_unreadable(self):
        self.skip("rulesets can't be made unreadable")

    def branch(self):
        head = f"forge-test-{uuid.uuid4().hex[:8]}"
        base = self.api(self.r("git/ref/heads/main"))["object"]["sha"]
        self.api(self.r("git/refs"), "POST", {"ref": f"refs/heads/{head}", "sha": base})
        self.case.addCleanup(subprocess.run, ["gh", "api", "-X", "DELETE", self.r(f"git/refs/heads/{head}")],
                             capture_output=True)
        self._commit(head)
        return head

    def _commit(self, head):
        name = f"forge-test/{uuid.uuid4().hex[:8]}.txt"
        content = base64.b64encode(name.encode()).decode()
        self.api(self.r(f"contents/{name}"), "PUT", {"message": f"forge contract test: {name}",
                                                    "content": content, "branch": head})

    def mr(self, title="Change", body="", draft=True):
        head = self.branch()
        pull = self.api(self.r("pulls"), "POST", {"title": title, "body": body, "head": head,
                                                 "base": "main", "draft": draft})
        self.case.addCleanup(subprocess.run, ["gh", "api", "-X", "PATCH", self.r(f"pulls/{pull['number']}"),
                                              "-f", "state=closed"], capture_output=True)
        return pull["number"], head

    def push(self, n):
        self._commit(self.api(self.r(f"pulls/{n}"))["head"]["ref"])

    def head_sha(self, n):
        return self.api(self.r(f"pulls/{n}"))["head"]["sha"]

    def is_merged(self, n):
        return self.api(self.r(f"pulls/{n}"))["merged"]

    def labels(self, n):
        return {l["name"] for l in self.api(self.r(f"issues/{n}"))["labels"]}

    def comments(self, n):
        return [c["body"] for c in self.api(self.r(f"issues/{n}/comments"))]

    def mr_field(self, n, key):
        return self.api(self.r(f"pulls/{n}"))[key]

    def check(self, *a, **k):
        self.skip("check runs need a GitHub App")

    def status(self, *a, **k):
        self.skip("statuses are left alone on a shared repository")

    def review(self, *a, **k):
        self.skip("an author can't approve their own merge request")

    def protect(self, *a, **k):
        self.skip("branch protection is left alone")


class ForgeContract(unittest.TestCase):
    def setUp(self):
        if LIVE_REPO:
            self.world = LiveWorld(self, LIVE_REPO)
        else:
            tmp = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, tmp)
            self.world = FakeWorld(tmp)
        self.label = f"forge-test-{uuid.uuid4().hex[:6]}"

    def forge(self, *args, stdin=None):
        return subprocess.run([str(FORGE), *args], input=stdin, capture_output=True, text=True,
                              env=self.world.env())

    def forge_json(self, *args, stdin=None):
        res = self.forge(*args, stdin=stdin)
        self.assertEqual(res.returncode, 0, f"forge {' '.join(args)}: {res.stderr}")
        out = json.loads(res.stdout)
        bad = [k for k in keys(out) if FORGE_WORDS.search(k)]
        self.assertEqual(bad, [], "output must use neutral vocabulary")
        return out

    def forge_ok(self, *args, stdin=None):
        res = self.forge(*args, stdin=stdin)
        self.assertEqual(res.returncode, 0, f"forge {' '.join(args)}: {res.stderr}")
        return res

    def forge_fails(self, *args, stdin=None):
        res = self.forge(*args, stdin=stdin)
        self.assertNotEqual(res.returncode, 0, f"forge {' '.join(args)} should fail")
        self.assertTrue(res.stderr.startswith("forge: "), res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        return res

    # ---- identity -----------------------------------------------------------

    def test_whoami_gives_the_operator_login(self):
        self.assertEqual(self.forge_json("whoami"), {"login": self.world.user})

    # ---- tickets and blockers ----------------------------------------------

    def test_tickets_lists_open_labeled_tickets_only(self):
        a = self.world.ticket("A", labels=[self.label])
        self.world.ticket("unlabeled")
        c = self.world.ticket("closed", labels=[self.label])
        self.world.close(c)
        self.world.mr()  # merge requests are never tickets
        rows = self.forge_json("tickets", "--label", self.label)
        self.assertEqual([r["number"] for r in rows], [a])
        self.assertEqual(rows[0]["title"], "A")
        self.assertEqual(rows[0]["blockers"], [])

    def test_tickets_include_open_native_blockers(self):
        b1 = self.world.ticket("blocker open")
        b2 = self.world.ticket("blocker closed")
        n = self.world.ticket("blocked", labels=[self.label])
        self.world.block(n, b1)
        self.world.block(n, b2)
        self.world.close(b2)
        rows = self.forge_json("tickets", "--label", self.label)
        self.assertEqual(rows[0]["blockers"], [b1])
        self.assertEqual(self.forge_json("blockers", str(n)), [b1])

    def test_blockers_read_the_written_convention(self):
        b1 = self.world.ticket("blocker one")
        b2 = self.world.ticket("blocker two")
        b3 = self.world.ticket("blocker closed")
        self.world.close(b3)
        n = self.world.ticket("blocked", body=f"Some text.\n\nBloqué par #{b1}, #{b2}\nbloqué par #{b3}\n")
        self.assertEqual(self.forge_json("blockers", str(n)), sorted([b1, b2]))

    def test_blockers_merge_native_and_written(self):
        b1 = self.world.ticket("native")
        b2 = self.world.ticket("written")
        n = self.world.ticket("blocked", body=f"Bloqué par #{b2}")
        self.world.block(n, b1)
        self.assertEqual(self.forge_json("blockers", str(n)), sorted([b1, b2]))

    def test_blockers_fall_back_to_the_convention_without_native_relation(self):
        b = self.world.ticket("blocker")
        n = self.world.ticket("blocked", body=f"Bloqué par #{b}")
        self.world.without_native_dependencies()
        self.assertEqual(self.forge_json("blockers", str(n)), [b])

    def test_unreadable_native_relation_fails_closed(self):
        b = self.world.ticket("blocker")
        n = self.world.ticket("blocked", labels=[self.label])
        self.world.block(n, b)
        self.world.without_native_dependencies(code=403)
        self.forge_fails("blockers", str(n))
        self.forge_fails("tickets", "--label", self.label)

    def test_unknown_written_blocker_counts_as_blocking(self):
        n = self.world.ticket("blocked", body="Bloqué par #99999")
        self.assertEqual(self.forge_json("blockers", str(n)), [99999])

    def test_blocker_closed_without_being_done_still_blocks(self):
        # A blocker counts as done only when closed as completed: « not planned »
        # or « duplicate » leaves the work it stood for undone.
        native = self.world.ticket("native, not planned")
        written = self.world.ticket("written, duplicate")
        done = self.world.ticket("done")
        n = self.world.ticket("blocked", body=f"Bloqué par #{written}, #{done}", labels=[self.label])
        self.world.block(n, native)
        self.world.close(native, "not_planned")
        self.world.close(written, "duplicate")
        self.world.close(done)
        self.assertEqual(self.forge_json("blockers", str(n)), sorted([native, written]))
        self.assertEqual(self.forge_json("tickets", "--label", self.label)[0]["blockers"], sorted([native, written]))

    def test_text_that_only_mentions_a_ticket_is_not_a_blocker(self):
        other = self.world.ticket("other")
        n = self.world.ticket("not blocked", body=f"See #{other}. Not « bloqué par » anything.")
        self.assertEqual(self.forge_json("blockers", str(n)), [])

    # ---- reading a ticket ---------------------------------------------------

    def test_ticket_view_gives_neutral_fields(self):
        n = self.world.ticket("Title", body="Body", labels=[self.label])
        t = self.forge_json("ticket", "view", str(n))
        self.assertEqual((t["number"], t["title"], t["body"], t["state"]), (n, "Title", "Body", "open"))
        self.assertEqual(t["author"], self.world.user)
        self.assertEqual(t["labels"], [self.label])
        self.assertTrue(t["url"].startswith("https://"))
        self.assertEqual(t["comments"], [])

    def test_ticket_view_keeps_only_authorized_authors_comments(self):
        n = self.world.ticket("T", author="alice")
        self.world.comment(n, "from alice", author="alice")
        self.world.comment(n, "from mallory", author="mallory")
        self.world.comment(n, "from operator")
        self.world.comment(n, "from bob", author="bob")
        t = self.forge_json("ticket", "view", str(n))
        self.assertEqual([c["body"] for c in t["comments"]], ["from alice", "from operator"])
        self.assertEqual(set(t["comments"][0]), {"author", "body", "created_at"})
        t = self.forge_json("ticket", "view", str(n), "--allow", "bob")
        self.assertEqual([c["body"] for c in t["comments"]], ["from alice", "from operator", "from bob"])

    def test_ticket_view_refuses_a_merge_request_number(self):
        n, _ = self.world.mr()
        self.forge_fails("ticket", "view", str(n))

    def test_ticket_view_of_a_missing_ticket_fails_cleanly(self):
        self.forge_fails("ticket", "view", "99999")

    def test_closed_ticket_reads_closed(self):
        n = self.world.ticket("T")
        self.world.close(n)
        self.assertEqual(self.forge_json("ticket", "view", str(n))["state"], "closed")

    # ---- writing on a ticket ------------------------------------------------

    def test_ticket_comment_from_option_or_stdin(self):
        n = self.world.ticket("T")
        self.forge_ok("ticket", "comment", str(n), "--body", "first")
        self.forge_ok("ticket", "comment", str(n), stdin="second\nline")
        self.assertEqual(self.world.comments(n), ["first", "second\nline"])

    def test_ticket_label_adds_and_removes(self):
        n = self.world.ticket("T", labels=[self.label])
        extra = self.label + "-x"
        self.forge_ok("ticket", "label", str(n), "--add", extra, "--remove", self.label)
        self.assertEqual(self.world.labels(n), {extra})

    def test_removing_an_absent_label_is_not_an_error(self):
        n = self.world.ticket("T")
        self.forge_ok("ticket", "label", str(n), "--remove", f"{self.label}-a,{self.label}-b")

    def test_ticket_create(self):
        out = self.forge_json("ticket", "create", "--title", "New", "--body", "Text", "--label", self.label)
        if self.world.live:
            self.addCleanup(self.world.close, out["number"])
        self.assertTrue(out["url"].startswith("https://"))
        t = self.forge_json("ticket", "view", str(out["number"]))
        self.assertEqual((t["title"], t["body"], t["labels"]), ("New", "Text", [self.label]))

    # ---- merge requests -----------------------------------------------------

    def test_mr_create_opens_a_draft_found_by_its_branch(self):
        head = self.world.branch()
        self.assertIsNone(self.forge_json("mr", "find", "--head", head))
        out = self.forge_json("mr", "create", "--head", head, "--base", "main",
                              "--title", "Change", "--body", "Closes #1")
        self.addCleanup(self.forge, "mr", "close", str(out["number"]))
        self.assertEqual(self.forge_json("mr", "find", "--head", head), out)
        mr = self.forge_json("mr", "view", str(out["number"]))
        self.assertEqual((mr["state"], mr["draft"], mr["head"], mr["base"], mr["body"], mr["title"]),
                         ("open", True, head, "main", "Closes #1", "Change"))
        self.assertRegex(mr["head_sha"], r"^[0-9a-f]{40}$")

    def test_mr_create_reads_the_body_from_a_file(self):
        head = self.world.branch()
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("From a file\n")
        self.addCleanup(os.unlink, f.name)
        out = self.forge_json("mr", "create", "--head", head, "--base", "main",
                              "--title", "T", "--body-file", f.name)
        self.addCleanup(self.forge, "mr", "close", str(out["number"]))
        self.assertEqual(self.forge_json("mr", "view", str(out["number"]))["body"], "From a file\n")

    def test_mr_edit_ready_comment_close(self):
        n, _ = self.world.mr(body="old")
        self.forge_ok("mr", "edit", str(n), "--body", "new", "--title", "Renamed")
        self.forge_ok("mr", "ready", str(n))
        self.forge_ok("mr", "comment", str(n), "--body", "note")
        mr = self.forge_json("mr", "view", str(n))
        self.assertEqual((mr["body"], mr["title"], mr["draft"]), ("new", "Renamed", False))
        self.assertEqual(self.world.comments(n), ["note"])
        self.forge_ok("mr", "close", str(n))
        self.assertEqual(self.forge_json("mr", "view", str(n))["state"], "closed")

    def test_mrs_lists_open_merge_requests_with_their_draft_flag(self):
        ready, ready_head = self.world.mr(title="Ready", draft=False)
        draft, _ = self.world.mr(title="Draft")
        closed, _ = self.world.mr(title="Closed", draft=False)
        self.forge_ok("mr", "close", str(closed))
        rows = {r["number"]: r for r in self.forge_json("mrs")}
        self.assertIn(ready, rows)
        self.assertIn(draft, rows)
        self.assertNotIn(closed, rows)
        self.assertEqual((rows[ready]["draft"], rows[ready]["head"], rows[ready]["title"]), (False, ready_head, "Ready"))
        self.assertTrue(rows[draft]["draft"])
        self.assertEqual(set(rows[ready]), {"number", "title", "url", "draft", "head", "author"})

    def test_mrs_when_the_forge_refuses_fails_cleanly(self):
        if self.world.live:
            self.world.skip("a real forge can't be made to refuse")
        self.world.edit(lambda s: s.update(pulls_error=502))
        self.forge_fails("mrs")

    def test_mr_view_of_a_missing_request_fails_cleanly(self):
        self.forge_fails("mr", "view", "99999")

    def test_mr_status_normalizes_checks_and_approvals(self):
        n, _ = self.world.mr()
        sha = self.world.head_sha(n)
        self.world.check(sha, "test", "completed", "success")
        self.world.check(sha, "lint", "completed", "failure")
        self.world.check(sha, "slow", "in_progress")
        self.world.check(sha, "docs", "completed", "skipped")
        self.world.status(sha, "ci/legacy", "pending")
        self.world.review(n, "alice", "APPROVED")
        self.world.review(n, "bob", "APPROVED")
        self.world.review(n, "bob", "CHANGES_REQUESTED")
        self.world.review(n, "carol", "CHANGES_REQUESTED")
        self.world.review(n, "carol", "COMMENTED")
        self.world.review(n, "carol", "APPROVED")
        st = self.forge_json("mr", "status", str(n))
        self.assertEqual(st["head_sha"], sha)
        self.assertEqual({c["name"]: c["state"] for c in st["checks"]},
                         {"test": "pass", "lint": "fail", "slow": "pending", "docs": "skipped",
                          "ci/legacy": "pending"})
        self.assertEqual(st["approved_by"], ["alice", "carol"])
        self.assertEqual(st["changes_requested_by"], ["bob"])

    def test_mr_status_counts_only_approvals_of_the_current_head(self):
        n, _ = self.world.mr()
        old = self.world.head_sha(n)
        self.world.review(n, "alice", "APPROVED")
        self.world.push(n)
        self.world.review(n, "bob", "APPROVED")
        st = self.forge_json("mr", "status", str(n))
        self.assertEqual(st["approved_by"], ["bob"])
        self.assertEqual(st["stale_approved_by"], ["alice"])
        self.assertNotEqual(st["head_sha"], old)

    def test_mr_status_of_a_request_without_checks(self):
        n, _ = self.world.mr()
        st = self.forge_json("mr", "status", str(n))
        self.assertEqual((st["checks"], st["approved_by"], st["changes_requested_by"]), ([], [], []))

    def test_merge_requires_the_head_commit(self):
        n, _ = self.world.mr(draft=False)
        self.assertEqual(self.forge("mr", "merge", str(n)).returncode, 2)
        self.assertFalse(self.world.is_merged(n))

    def test_merge_refuses_a_head_that_is_not_a_full_commit_sha(self):
        n, _ = self.world.mr(draft=False)
        for head in ("", "main", self.world.head_sha(n)[:7], "HEAD"):
            res = self.forge("mr", "merge", str(n), "--head", head)
            self.assertNotEqual(res.returncode, 0, head)
        self.assertFalse(self.world.is_merged(n))

    def test_merge_refuses_when_the_head_moved(self):
        n, _ = self.world.mr(draft=False)
        seen = self.world.head_sha(n)
        self.world.push(n)
        res = self.forge_fails("mr", "merge", str(n), "--head", seen)
        self.assertIn("tête", res.stderr)
        self.assertFalse(self.world.is_merged(n))

    def test_merge_at_the_expected_head(self):
        n, _ = self.world.mr(draft=False)
        out = self.forge_json("mr", "merge", str(n), "--head", self.world.head_sha(n), "--method", "squash")
        self.assertTrue(out["merged"])
        self.assertTrue(self.world.is_merged(n))
        self.assertEqual(self.forge_json("mr", "view", str(n))["state"], "merged")

    def test_merge_rejects_an_unknown_method(self):
        n, _ = self.world.mr(draft=False)
        res = self.forge("mr", "merge", str(n), "--head", self.world.head_sha(n), "--method", "octopus")
        self.assertEqual(res.returncode, 2)
        self.assertFalse(self.world.is_merged(n))

    # ---- protection ---------------------------------------------------------

    def test_protection_of_an_unprotected_branch(self):
        if self.world.live:
            self.skipTest("depends on the live repository's settings")
        p = self.forge_json("protection", "main")
        self.assertEqual((p["branch"], p["protected"], p["required_checks"], p["required_approvals"]),
                         ("main", False, [], 0))

    def test_protection_reads_required_checks_and_approvals(self):
        self.world.protect("main", {
            "required_status_checks": {"strict": True, "contexts": ["gate"], "checks": [{"context": "gate"}, {"context": "test"}]},
            "required_pull_request_reviews": {"required_approving_review_count": 1},
            "enforce_admins": {"enabled": True},
        })
        p = self.forge_json("protection", "main")
        self.assertEqual((p["protected"], p["required_checks"], p["required_approvals"], p["enforce_admins"]),
                         (True, ["gate", "test"], 1, True))

    def test_unreadable_rulesets_fail_closed(self):
        self.world.rules_unreadable()
        self.forge_fails("protection", "main")

    # ---- adapters -----------------------------------------------------------

    def test_unknown_forge_is_refused(self):
        env = self.world.env()
        env["FORGE"] = "gitea"
        res = subprocess.run([str(FORGE), "whoami"], capture_output=True, text=True, env=env)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("gitea", res.stderr)

    def test_usage_error_exits_2(self):
        self.assertEqual(self.forge("frobnicate").returncode, 2)


if __name__ == "__main__":
    unittest.main()
