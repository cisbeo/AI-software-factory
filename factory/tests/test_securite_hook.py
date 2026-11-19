"""Control: the PreToolUse hook `.claude/hooks/guard.py` (spec §8).

The hook reads the JSON Claude Code sends on stdin before a tool runs and
exits 2 to block it. Any other exit code lets the call through, so the hook
must exit 2 whenever it does not understand its input (fail closed).

Blocked: history rewrite, force push, push to the base branch, push of another
branch than `factory/<job-id>` from a job worktree, recursive delete outside
the worktree, secret files (`.env*`, keys, certificates) named in a shell
command or targeted by a file tool.
Neighbour: the same commands in their harmless form pass.
In a reviewer-<lens> subagent (`agent_type` in the input) or with
`--reviewer <lens>`, anything that writes, except the reviewer's own review file.
Not understood: bad JSON, missing fields, unbalanced quotes, an unknown
directory or a detached HEAD where the decision depends on it, an unknown
reviewer: blocked.

Fixture: a bare `origin.git`, a main checkout `main/` on `main` holding
factory/config.json, and the job worktree `main/.worktrees/001-test` on
`factory/001-test`.
"""

import json
import shutil
import sys
import unittest

from helpers import SOURCE, FactoryCase, run, write

JOB = "001-test"
BRANCH = f"factory/{JOB}"


class GuardCase(FactoryCase):
    scripts = ()

    def setUp(self):
        super().setUp()
        self.guard = self.root / ".claude" / "hooks" / "guard.py"
        self.guard.parent.mkdir(parents=True)
        shutil.copy2(SOURCE / ".claude" / "hooks" / "guard.py", self.guard)
        origin = self.tmp / "origin.git"
        self.git(self.tmp, "init", "--bare", "-q", str(origin))
        write(self.root / ".gitignore", "/factory/jobs/\n/.worktrees/\n")
        write(self.root / "src" / "app.txt", "hello\n")
        self.git(self.root, "init", "-q")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "base")
        self.git(self.root, "remote", "add", "origin", str(origin))
        self.git(self.root, "push", "-q", "origin", "HEAD:main")
        self.git(self.root, "fetch", "-q", "origin")
        self.wt = self.root / ".worktrees" / JOB
        self.git(self.root, "worktree", "add", "-q", "-b", BRANCH, str(self.wt), "origin/main")
        self.env["CLAUDE_PROJECT_DIR"] = str(self.root)

    def hook(self, payload, *args):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        return run([sys.executable, "-B", str(self.guard), *args], cwd=self.root, env=self.env, stdin=stdin)

    def bash(self, command, cwd=None, *args):
        return self.hook({
            "session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "cwd": str(cwd or self.root), "permission_mode": "default",
            "tool_input": {"command": command, "description": "test"},
        }, *args)

    def tool(self, name, tool_input, *args):
        return self.hook({
            "session_id": "s", "hook_event_name": "PreToolUse", "tool_name": name,
            "cwd": str(self.root), "tool_input": tool_input,
        }, *args)

    def assertBlocked(self, res, says=None):
        self.assertEqual(res.returncode, 2, f"not blocked: {res.stdout}{res.stderr}")
        self.assertTrue(res.stderr.strip(), "a block must say why on stderr")
        if says:
            self.assertIn(says, res.stderr)

    def assertPasses(self, res):
        self.assertEqual(res.returncode, 0, f"blocked: {res.stderr}")

    def blocked(self, command, cwd=None, says=None):
        with self.subTest(command=command):
            self.assertBlocked(self.bash(command, cwd), says)

    def passes(self, command, cwd=None):
        with self.subTest(command=command):
            self.assertPasses(self.bash(command, cwd))


class HistoryRewrite(GuardCase):
    def test_blocked(self):
        for cmd in ("git rebase main", f"cd {self.wt} && git rebase -i HEAD~2",
                    "git commit --amend -m x", "git commit --amend --no-edit",
                    "git reset --hard HEAD~1", "git reset --soft HEAD~1", "git reset HEAD~1",
                    "git filter-branch --tree-filter true HEAD", "git filter-repo --path x",
                    "git update-ref refs/heads/main HEAD~1", "git reflog expire --all",
                    "git branch -f main HEAD~1", "git checkout -B main", "git replace a b",
                    f"git -C {self.wt} rebase main", "/usr/bin/git rebase main",
                    "FOO=1 git rebase main", "env git rebase main", "bash -c 'git rebase main'",
                    "echo $(git commit --amend -m x)", "git status; git rebase main",
                    "git status\ngit rebase main"):
            self.blocked(cmd, self.wt, says="history")

    def test_neighbours_pass(self):
        for cmd in ("git commit -m 'rebase later'", "git reset HEAD src/app.txt", "git reset",
                    "git reset -- src/app.txt", "git log --oneline main..HEAD", "git status",
                    "git rebase --abort", "git branch --show-current", "git checkout -b other",
                    "echo 'git rebase main'"):
            self.passes(cmd, self.wt)


class ForcePush(GuardCase):
    def test_blocked(self):
        for cmd in (f"git push -f origin {BRANCH}", f"git push --force origin {BRANCH}",
                    f"git push --force-with-lease origin {BRANCH}", f"git push -fu origin {BRANCH}",
                    f"git push origin +{BRANCH}", f"git push --force-if-includes origin {BRANCH}",
                    f"git push origin --delete {BRANCH}", f"git push origin :{BRANCH}",
                    "git push --mirror origin", f"sh -c \"git push -f origin {BRANCH}\""):
            self.blocked(cmd, self.wt)

    def test_neighbour_passes(self):
        self.passes(f"git push -u origin {BRANCH}", self.wt)


class PushToBase(GuardCase):
    def test_blocked(self):
        for cmd in ("git push origin main", "git push origin HEAD:main",
                    "git push origin HEAD:refs/heads/main", "git push", "git push origin HEAD",
                    "git push --all origin", f"git push origin {BRANCH}:main"):
            self.blocked(cmd, self.root)

    def test_neighbour_passes(self):
        # Outside a job worktree, a push to another branch than the base is the forge's business.
        self.passes("git push origin feature-x", self.root)
        self.passes("git push -u origin HEAD:feature-x", self.root)


class PushOtherBranch(GuardCase):
    def test_blocked(self):
        for cmd in ("git push origin factory/002-other", "git push origin HEAD:other",
                    "git push origin v1.0", "git push --tags origin",
                    f"git push origin {BRANCH} factory/002-other",
                    f"git push origin {BRANCH}:factory/002-other"):
            self.blocked(cmd, self.wt, says=BRANCH)
        # The job context follows `cd` and `git -C`, not just the hook's cwd.
        self.blocked(f"cd {self.wt} && git push origin HEAD:other", self.root)
        self.blocked(f"git -C {self.wt} push origin HEAD:other", self.root)

    def test_neighbours_pass(self):
        for cmd in (f"git push -u origin {BRANCH}", "git push origin HEAD", "git push",
                    f"git push origin HEAD:refs/heads/{BRANCH}", f"git push origin {BRANCH}:{BRANCH}"):
            self.passes(cmd, self.wt)
        self.passes(f"cd {self.wt} && git push -u origin {BRANCH}", self.root)
        self.passes(f"git -C {self.wt} push origin HEAD", self.root)

    def test_upstream_elsewhere_is_blocked(self):
        # `git push` with no refspec goes where the push config says, not where the name says.
        self.git(self.wt, "config", "push.default", "upstream")
        self.git(self.wt, "branch", "--set-upstream-to", "origin/main")
        self.blocked("git push", self.wt)


class RecursiveDelete(GuardCase):
    def test_blocked(self):
        other = self.tmp / "other"
        self.git(self.tmp, "init", "-q", str(other))
        for cwd, cmd in ((self.wt, "rm -rf /"), (self.wt, "rm -rf ~"), (self.wt, "rm -rf ~/projects"),
                         (self.wt, "rm -rf .."), (self.wt, f"rm -r -- {self.root}"),
                         (self.wt, "rm -rf $HOME/x"), (self.wt, "rm -fr .git"), (self.wt, f"rm -rf {self.wt}"),
                         (self.wt, "rm -R ../../src"), (self.wt, "rm --recursive /tmp/x"),
                         (self.wt, "cd /tmp && rm -rf x"), (self.wt, f"cd {other} && rm -rf src"),
                         (self.wt, "ls | xargs rm -rf"), (self.wt, "ls | xargs -n 1 rm -rf"),
(self.wt, "find / -name x -delete"),
                         (self.wt, "find .. -exec rm -rf {} +"), (self.wt, "sudo rm -rf build"),
                         (self.tmp, "rm -rf build")):
            self.blocked(cmd, cwd, says="delete")

    def test_neighbours_pass(self):
        for cmd in ("rm -rf build", "rm -rf node_modules dist", "rm -rf ./build/*",
                    "rm /tmp/not-recursive.txt", "rm -f src/app.txt", "find . -name '*.pyc' -delete",
                    f"rm -rf {self.wt}/build"):
            self.passes(cmd, self.wt)
        self.passes(f"cd {self.wt} && rm -rf build", self.root)


class SecretsInShell(GuardCase):
    def test_blocked(self):
        for cmd in ("cat .env", "head -5 config/.env.local", "cp server.key /tmp/",
                    "python3 -c \"print(open('.env').read())\"", "less ~/.ssh/id_ed25519",
                    "openssl x509 -in certs/site.crt -text", "base64 < keystore.p12",
                    "grep TOKEN .env.production", "cat $HOME/.envrc", "echo x >> .env"):
            self.blocked(cmd, self.wt, says="secret")

    def test_neighbours_pass(self):
        for cmd in ("cat docs/env.md", "source .venv/bin/activate",
                    "node -e 'console.log(process.env.HOME)'", "cat src/keys.py",
                    "git commit -m 'ne lit jamais .env'", "ls certificates/"):
            self.passes(cmd, self.wt)

    def test_heredoc_body_is_data(self):
        self.passes("git commit -F - <<'EOF'\nN'ouvre jamais .env ni git push -f.\nEOF", self.wt)


class SecretsInFileTools(GuardCase):
    def test_blocked(self):
        for name, inp in (("Read", {"file_path": f"{self.wt}/.env"}),
                          ("Read", {"file_path": "/elsewhere/app/.env.production"}),
                          ("Write", {"file_path": f"{self.wt}/certs/server.pem", "content": "x"}),
                          ("Edit", {"file_path": f"{self.wt}/id_rsa", "old_string": "a", "new_string": "b"}),
                          ("MultiEdit", {"file_path": f"{self.wt}/deploy.key", "edits": []}),
                          ("NotebookEdit", {"notebook_path": f"{self.wt}/.env.ipynb", "new_source": "x"}),
                          ("Grep", {"pattern": "TOKEN", "path": f"{self.wt}/.env"}),
                          ("Grep", {"pattern": "TOKEN", "glob": ".env*"})):
            with self.subTest(tool=name, input=inp):
                self.assertBlocked(self.tool(name, inp), says="secret")

    def test_neighbours_pass(self):
        for name, inp in (("Read", {"file_path": f"{self.wt}/README.md"}),
                          ("Write", {"file_path": f"{self.wt}/src/environment.py", "content": "x"}),
                          ("Read", {"file_path": f"{self.wt}/src/keys.py"}),
                          ("Grep", {"pattern": "TOKEN", "path": f"{self.wt}/src"}),
                          ("Glob", {"pattern": "**/*.py"})):
            with self.subTest(tool=name, input=inp):
                self.assertPasses(self.tool(name, inp))


class NotUnderstood(GuardCase):
    def test_bad_input_is_blocked(self):
        for payload in ("", "not json", "[1, 2]", json.dumps({"tool_name": "Bash"}),
                        json.dumps({"tool_name": "Bash", "tool_input": {"command": 3}}),
                        json.dumps({"tool_name": "Bash", "tool_input": "git status"}),
                        json.dumps({"tool_input": {"command": "ls"}}),
                        json.dumps({"tool_name": "Read", "tool_input": {}})):
            with self.subTest(payload=payload):
                self.assertBlocked(self.hook(payload))

    def test_unparsable_command_is_blocked(self):
        self.blocked("git push \"origin", self.wt, says="understand")

    def test_unknown_directory_blocks_push_and_delete(self):
        self.blocked("git push origin HEAD", self.tmp / "missing")
        self.blocked("cd $SOMEWHERE && rm -rf build", self.wt)
        self.blocked("cd $SOMEWHERE && git push origin HEAD", self.wt)

    def test_detached_head_push_is_blocked(self):
        self.git(self.wt, "checkout", "-q", "--detach")
        self.blocked("git push origin HEAD", self.wt)

    def test_missing_config_blocks_push(self):
        (self.factory / "config.json").unlink()
        self.blocked(f"git push -u origin {BRANCH}", self.wt, says="config")

    def test_unknown_tool_passes(self):
        # Tools the hook doesn't guard are left to the permission rules.
        self.assertPasses(self.tool("WebSearch", {"query": "x"}))


class ReviewerReadOnly(GuardCase):
    def review_file(self, lens="code"):
        return str(self.jobs / JOB / "round-1" / f"review-{lens}.md")

    def test_blocked(self):
        for name, inp in (("Write", {"file_path": self.review_file("spec"), "content": "x"}),
                          ("Write", {"file_path": f"{self.wt}/src/app.txt", "content": "x"}),
                          ("Write", {"file_path": str(self.jobs / JOB / "decision.md"), "content": "x"}),
                          ("Write", {"file_path": str(self.jobs / JOB / "round-1" / ".." / ".." / "x" / "round-1"
                                                      / "review-code.md"), "content": "x"}),
                          ("Edit", {"file_path": self.review_file(), "old_string": "a", "new_string": "b"}),
                          ("NotebookEdit", {"notebook_path": f"{self.wt}/n.ipynb", "new_source": "x"})):
            with self.subTest(tool=name, input=inp):
                self.assertBlocked(self.tool(name, inp, "--reviewer", "code"), says="read-only")
        for cmd in ("git commit -m x", "git checkout -- src/app.txt", "git stash", "git add src",
                    "echo x > src/app.txt", "cat src/app.txt | tee out.txt", "sed -i s/a/b/ src/app.txt",
                    "rm src/app.txt", "mv a b", "npm run lint -- --fix", "touch x", "git diff --output=x",
                    "git -c core.pager=sh log", "python3 -c 'open(\"x\",\"w\")'", "find . -delete",
                    "npm run dev"):
            with self.subTest(command=cmd):
                self.assertBlocked(self.bash(cmd, self.wt, "--reviewer", "code"), says="read-only")

    def test_neighbours_pass(self):
        self.assertPasses(self.tool("Write", {"file_path": self.review_file(), "content": "VERDICT: PASS\n"},
                                    "--reviewer", "code"))
        self.assertPasses(self.tool("Read", {"file_path": f"{self.wt}/src/app.txt"}, "--reviewer", "code"))
        for cmd in (f"cd {self.wt} && git diff main...HEAD", "git log --oneline main..HEAD",
                    "git show HEAD --stat", "git status --porcelain", "ls -la src", "cat src/app.txt",
                    "grep -rn hello src", "git diff main...HEAD 2>/dev/null | head -50",
                    "git branch --show-current", "find . -name '*.txt'", "wc -l src/app.txt"):
            with self.subTest(command=cmd):
                self.assertPasses(self.bash(cmd, self.wt, "--reviewer", "code"))

    def test_interface_lenses_can_run_the_app(self):
        for lens in ("ui", "ux"):
            for cmd in ("npm run dev -- --port 5101", "pnpm dev --port 5101", "agent-browser --session x open http://localhost:5101",
                        "lsof -tiTCP:5101 -sTCP:LISTEN", "kill 1234", "sleep 2", "curl -s http://localhost:5101/"):
                with self.subTest(lens=lens, command=cmd):
                    self.assertPasses(self.bash(cmd, self.wt, "--reviewer", lens))
            self.assertBlocked(self.bash("npm install left-pad", self.wt, "--reviewer", lens))

    def test_still_applies_the_common_rules(self):
        self.assertBlocked(self.bash("cat .env", self.wt, "--reviewer", "code"), says="secret")

    def test_agent_type_selects_the_lens(self):
        # Claude Code adds agent_type to the input inside a subagent (checked on 2.1.285).
        def call(agent, name, inp):
            return self.hook({"tool_name": name, "cwd": str(self.wt), "agent_type": agent, "tool_input": inp})
        self.assertBlocked(call("reviewer-code", "Bash", {"command": "touch x"}), says="read-only")
        self.assertBlocked(call("reviewer-code", "Write", {"file_path": self.review_file("spec"), "content": "x"}))
        self.assertPasses(call("reviewer-code", "Write", {"file_path": self.review_file("code"), "content": "x"}))
        self.assertPasses(call("reviewer-ux", "Bash", {"command": "npm run dev -- --port 5101"}))
        self.assertPasses(call("builder", "Bash", {"command": "touch x"}))
        self.assertBlocked(call("reviewer-perf", "Bash", {"command": "git status"}), says="reviewer-perf")
        self.assertBlocked(call(3, "Bash", {"command": "git status"}))

    def test_bad_lens_is_blocked(self):
        for args in (("--reviewer",), ("--reviewer", "../x"), ("--reviewer", ""), ("--bogus",)):
            with self.subTest(args=args):
                self.assertBlocked(self.bash("git status", self.wt, *args))


if __name__ == "__main__":
    unittest.main()
