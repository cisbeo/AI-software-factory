"""Controls run by `factory/bin/audit`, and the deny rules of .claude/settings.json (spec §8).

Each case copies this repo's .claude/settings.json, agents and skills into a
throwaway root, breaks one thing, and runs `audit --root <tmp>`.

Blocked: a skill, plugin, marketplace or MCP server not pinned to a commit or
exact version ("latest", a branch, no version, a remote server); an agent
without an explicit tool list, an intake with a shell, a reviewer that can
edit or that the read-only hook doesn't know; settings without the deny rules or
the hook.
Neighbour: the same entries pinned (sha, v1.2.3, pkg@1.2.3, pkg==1.2.3,
image@sha256, a local script), and this repo as it is: OK.
Not understood: unreadable JSON, unknown source types, malformed entries or
frontmatter: a problem, exit 1.
"""

import json
import os
import re
import shutil
import sys
import unittest
from pathlib import Path

from helpers import FACTORY_SRC, SOURCE, FactoryCase, run, write

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
DIGEST = "sha256:" + "0" * 64


class AuditCase(FactoryCase):
    scripts = ("audit",)

    def setUp(self):
        super().setUp()
        shutil.copytree(SOURCE / ".claude" / "agents", self.root / ".claude" / "agents")
        shutil.copytree(SOURCE / ".claude" / "skills", self.root / ".claude" / "skills")
        shutil.copy2(SOURCE / ".claude" / "settings.json", self.root / ".claude" / "settings.json")
        shutil.copytree(SOURCE / ".claude" / "hooks", self.root / ".claude" / "hooks")

    def audit(self):
        return self.bin("audit", "--root", str(self.root))

    def settings(self, **extra):
        path = self.root / ".claude" / "settings.json"
        data = json.loads(path.read_text())
        data.update(extra)
        write(path, json.dumps(data))
        return data

    def mcp(self, servers):
        write(self.root / ".mcp.json", json.dumps({"mcpServers": servers}))

    def agent(self, name, edit):
        path = self.root / ".claude" / "agents" / f"{name}.md"
        text = path.read_text()
        new = edit(text)
        self.assertNotEqual(new, text, "the edit didn't apply")
        path.write_text(new)

    def assertProblem(self, says):
        res = self.audit()
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(says, res.stderr)

    def assertOK(self):
        res = self.audit()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("audit: OK", res.stdout)


class ThisRepo(unittest.TestCase):
    def test_this_repo_passes(self):
        res = run([sys.executable, "-B", str(FACTORY_SRC / "bin" / "audit")])
        self.assertEqual(res.returncode, 0, res.stderr)


class Pins(AuditCase):
    def test_baseline_passes(self):
        self.assertOK()

    def test_unpinned_marketplaces_are_blocked(self):
        for src in ({"source": "github", "repo": "o/r"}, {"source": "github", "repo": "o/r", "ref": "main"},
                    {"source": "github", "repo": "o/r", "ref": "latest"}, {"source": "git", "url": "https://x/r.git", "ref": "v1"},
                    {"source": "github", "repo": "o/r", "sha": SHA[:7]}, {"source": "directory", "path": "/abs/market"},
                    {"source": "directory", "path": "../market"}, {"source": "url", "url": "https://x/marketplace.json"}):
            with self.subTest(source=src):
                self.settings(extraKnownMarketplaces={"m": {"source": src}})
                self.assertProblem("marketplace m")

    def test_pinned_marketplaces_pass(self):
        for src in ({"source": "github", "repo": "o/r", "sha": SHA}, {"source": "github", "repo": "o/r", "ref": "v1.2.3"},
                    {"source": "git", "url": "https://x/r.git", "ref": SHA}, {"source": "directory", "path": "./plugins"}):
            with self.subTest(source=src):
                self.settings(extraKnownMarketplaces={"m": {"source": src}}, enabledPlugins={"p@m": True})
                self.assertOK()

    def test_plugin_from_unpinned_marketplace_is_blocked(self):
        self.settings(enabledPlugins={"superpowers@claude-plugins-official": True})
        self.assertProblem("superpowers@claude-plugins-official")
        self.settings(enabledPlugins={"superpowers@claude-plugins-official": False})
        self.assertOK()

    def test_unpinned_mcp_servers_are_blocked(self):
        for server in ({"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github@latest"]},
                       {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
                       {"command": "npx", "args": ["some-server@^1.2.0"]},
                       {"command": "npx some-server"},
                       {"command": "uvx", "args": ["mcp-server-git"]},
                       {"command": "uvx", "args": ["mcp-server-git>=0.6"]},
                       {"command": "docker", "args": ["run", "-i", "--rm", "ghcr.io/o/server:latest"]},
                       {"command": "docker", "args": ["run", "-i", "ghcr.io/o/server:1.2.3"]},
                       {"command": "deno", "args": ["run", "https://example.com/server.ts"]},
                       {"type": "http", "url": "https://mcp.example.com/mcp"},
                       {"type": "sse", "url": "https://mcp.example.com/sse"}):
            with self.subTest(server=server):
                self.mcp({"s": server})
                self.assertProblem(".mcp.json s")

    def test_pinned_mcp_servers_pass(self):
        self.mcp({
            "a": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github@2025.4.8"]},
            "b": {"command": "npx", "args": ["some-server@1.2.3", "--flag"]},
            "c": {"command": "uvx", "args": ["mcp-server-git==0.6.2", "--repository", "."]},
            "d": {"command": "uvx", "args": ["--from", "mcp-server-git==0.6.2", "mcp-server-git"]},
            "e": {"command": "docker", "args": ["run", "-i", "--rm", f"ghcr.io/o/server@{DIGEST}"]},
            "f": {"command": "python3", "args": ["tools/mcp_server.py"]},
            "g": {"type": "stdio", "command": "pnpm", "args": ["dlx", "some-server@0.1.0"]},
        })
        self.assertOK()

    def test_agent_skills_must_be_vendored_or_pinned(self):
        self.agent("builder", lambda t: t.replace("  - tdd\n", "  - tdd\n  - brainstorming\n"))
        self.assertProblem("skill brainstorming")

    def test_plugin_skill_needs_pinned_plugin(self):
        self.agent("builder", lambda t: t.replace("  - tdd\n", "  - tdd\n  - superpowers:brainstorming\n"))
        self.assertProblem("plugin superpowers")
        self.settings(extraKnownMarketplaces={"m": {"source": {"source": "github", "repo": "o/r", "sha": SHA}}},
                      enabledPlugins={"superpowers@m": True})
        self.assertOK()

    def test_linked_skill_is_blocked(self):
        os.symlink(self.tmp, self.root / ".claude" / "skills" / "linked")
        self.assertProblem("skills/linked")

    def test_not_understood(self):
        cases = [
            lambda: write(self.root / ".claude" / "settings.json", "{not json"),
            lambda: write(self.root / ".mcp.json", "[]"),
            lambda: write(self.root / ".mcp.json", "{"),
            lambda: self.mcp([]),
            lambda: self.mcp({"s": {"args": ["x"]}}),
            lambda: self.mcp({"s": "npx x@1.0.0"}),
            lambda: self.settings(extraKnownMarketplaces={"m": {"source": {"source": "npm", "package": "x"}}}),
            lambda: self.settings(extraKnownMarketplaces={"m": "github:o/r"}),
            lambda: self.settings(enabledPlugins={"no-marketplace": True}),
            lambda: self.agent("approver", lambda t: t.replace("---\n", "", 1)),
        ]
        settings = (self.root / ".claude" / "settings.json").read_text()
        approver = (self.root / ".claude" / "agents" / "approver.md").read_text()
        for i, breakage in enumerate(cases):
            with self.subTest(case=i):
                write(self.root / ".claude" / "settings.json", settings)
                write(self.root / ".claude" / "agents" / "approver.md", approver)
                (self.root / ".mcp.json").unlink(missing_ok=True)
                breakage()
                res = self.audit()
                self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
                self.assertNotIn("Traceback", res.stderr)


class WorkflowPins(AuditCase):
    """Each `uses:` of .github/workflows/ names a full commit, a local path or an image digest."""

    def setUp(self):
        super().setUp()
        shutil.copytree(SOURCE / ".github" / "workflows", self.root / ".github" / "workflows")

    def workflow(self, steps, name="w.yml"):
        write(self.root / ".github" / "workflows" / name,
              "on: pull_request\njobs:\n  t:\n    runs-on: ubuntu-24.04\n    steps:\n" + steps)

    def test_this_repo_workflows_pass(self):
        self.assertTrue(list((self.root / ".github" / "workflows").glob("*.yml")))
        self.assertOK()

    def test_unpinned_actions_are_blocked(self):
        for uses in ("actions/checkout@v7", "actions/checkout@v7.0.1", "actions/checkout@main",
                     "actions/checkout", f"actions/checkout@{SHA[:7]}", f"actions/checkout@{SHA.upper()}",
                     f"'actions/checkout@{SHA[:39]}'", "o/r/.github/workflows/ci.yml@main",
                     "docker://alpine:3.20", "docker://alpine"):
            with self.subTest(uses=uses):
                self.workflow(f"      - uses: {uses}\n")
                self.assertProblem(".github/workflows/w.yml:6")

    def test_unpinned_reusable_workflow_job_is_blocked(self):
        write(self.root / ".github" / "workflows" / "w.yaml",
              "on: push\njobs:\n  call:\n    uses: o/r/.github/workflows/ci.yml@v1\n")
        self.assertProblem(".github/workflows/w.yaml:4")

    def test_pinned_neighbours_pass(self):
        self.workflow(f"      - uses: actions/checkout@{SHA} # v7.0.1\n"
                      f"      - name: x\n        uses: \"actions/setup-python@{SHA}\"\n"
                      f"      - uses: o/r/sub/dir@{SHA}\n"
                      "      - uses: ./.github/actions/local\n"
                      f"      - uses: docker://alpine@{DIGEST}\n"
                      "      - run: echo the word uses is fine here\n")
        self.assertOK()

    def test_not_understood(self):
        for steps in ("      - uses:\n",
                      "      - uses: >\n          actions/checkout@v7\n",
                      "      - uses: ${{ matrix.action }}\n",
                      f"      - {{ uses: actions/checkout@{SHA} }}\n",
                      f"      - \"uses\": actions/checkout@{SHA}\n",
                      "      - run: echo x; uses: y\n"):
            with self.subTest(steps=steps):
                self.workflow(steps)
                self.assertProblem(".github/workflows/w.yml")
        (self.root / ".github" / "workflows" / "w.yml").write_bytes(b"\xff\xfe uses: x\n")
        res = self.audit()
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertNotIn("Traceback", res.stderr)


class AgentTools(AuditCase):
    def test_every_agent_lists_its_tools(self):
        for path in sorted((SOURCE / ".claude" / "agents").glob("*.md")):
            with self.subTest(agent=path.name):
                self.assertRegex(path.read_text(), r"(?m)^tools: \w")

    def test_missing_tool_list_is_blocked(self):
        self.agent("builder", lambda t: re.sub(r"(?m)^tools: .*\n", "", t))
        self.assertProblem("builder.md: no explicit tools list")

    def test_unknown_tool_is_blocked(self):
        self.agent("builder", lambda t: re.sub(r"(?m)^tools: .*$", "tools: *", t))
        self.assertProblem("tools not understood: *")

    def test_intake_without_shell(self):
        self.agent("intake", lambda t: t.replace("tools: Read, Grep, Glob, Write", "tools: Read, Grep, Glob, Bash, Write"))
        self.assertProblem("intake")

    def test_reviewer_with_edit_is_blocked(self):
        self.agent("reviewer-code", lambda t: t.replace("tools: Read, Grep, Glob, Bash, Write", "tools: Read, Grep, Glob, Bash, Write, Edit"))
        self.assertProblem("reviewer-code.md: a reviewer is read-only")

    def test_reviewer_unknown_to_the_guard_is_blocked(self):
        path = self.root / ".claude" / "agents" / "reviewer-perf.md"
        write(path, "---\nname: reviewer-perf\ndescription: x\ntools: Read, Grep, Glob, Bash, Write\n---\nx\n")
        self.assertProblem("no read-only rules for reviewer-perf")

    def test_missing_guard_is_blocked(self):
        self.assertOK()
        (self.root / ".claude" / "hooks" / "guard.py").unlink()
        self.assertProblem("guard.py: missing")

    def test_agent_mcp_servers_are_blocked(self):
        self.agent("builder", lambda t: t.replace("model: opus\n", "model: opus\nmcpServers:\n  - github\n", 1))
        self.assertProblem("mcpServers")

    def test_neighbour_builder_may_edit(self):
        self.assertIn("Edit", (self.root / ".claude" / "agents" / "builder.md").read_text().split("---")[1])
        self.assertOK()


class SettingsAudit(AuditCase):
    def test_missing_deny_rule_is_blocked(self):
        data = json.loads((self.root / ".claude" / "settings.json").read_text())
        data["permissions"]["deny"].remove("Edit(**/*.pem)")
        write(self.root / ".claude" / "settings.json", json.dumps(data))
        self.assertProblem("missing deny rule Edit(**/*.pem)")

    def test_hook_not_on_every_tool_is_blocked(self):
        data = json.loads((self.root / ".claude" / "settings.json").read_text())
        data["hooks"]["PreToolUse"][0]["matcher"] = "Bash|Read|Edit|Write|MultiEdit|NotebookEdit|Glob"
        write(self.root / ".claude" / "settings.json", json.dumps(data))
        self.assertProblem("isn't a PreToolUse hook for Grep")

    def test_missing_settings_is_blocked(self):
        (self.root / ".claude" / "settings.json").unlink()
        self.assertProblem("settings.json: missing")


# ---- The deny rules as Claude Code reads them -------------------------------------------
# Permission paths follow gitignore syntax: `//` is the filesystem root, `~/` the home
# directory, anything else is relative to the project. Edit rules also cover Write.

def rule_regex(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def denied(rules, tool, path, project):
    for rule in rules:
        m = re.fullmatch(r"(Read|Edit|Bash)\((.+)\)", rule)
        if not m:
            raise ValueError(f"rule not understood: {rule}")
        rtool, pattern = m.groups()
        if rtool != tool:
            continue
        if pattern.startswith("//"):
            target, pattern = path, pattern[1:]
        elif pattern.startswith("~/"):
            home = str(Path.home())
            if not path.startswith(home + "/"):
                continue
            target, pattern = path[len(home):], pattern[1:]
        else:
            if not path.startswith(project + "/"):
                continue
            target, pattern = path[len(project) + 1:], pattern.lstrip("./")
        if rule_regex(pattern).match(target):
            return True
    return False


class DenyRules(unittest.TestCase):
    project = "/work/repo"
    rules = json.loads((SOURCE / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    home = str(Path.home())

    def test_secrets_are_denied_to_read_and_edit(self):
        for path in (".env", "config/.env.local", ".env.production", "certs/server.pem", "deploy.key",
                     "a/b/site.crt", "store.p12", "keystore.jks"):
            for full in (f"{self.project}/{path}", f"/elsewhere/{path}"):
                for tool in ("Read", "Edit"):
                    with self.subTest(tool=tool, path=full):
                        self.assertTrue(denied(self.rules, tool, full, self.project))
        for tool in ("Read", "Edit"):
            self.assertTrue(denied(self.rules, tool, f"{self.home}/.ssh/id_ed25519", self.project))
            self.assertTrue(denied(self.rules, tool, f"{self.home}/.ssh/config", self.project))

    def test_neighbours_are_allowed(self):
        for path in ("docs/env.md", "src/environment.py", ".venv/bin/activate", "src/keys.py",
                     "certificates/README.md", "src/app.ts"):
            for tool in ("Read", "Edit"):
                with self.subTest(tool=tool, path=path):
                    self.assertFalse(denied(self.rules, tool, f"{self.project}/{path}", self.project))

    def test_rules_are_understood(self):
        denied(self.rules, "Read", f"{self.project}/x", self.project)  # raises on a malformed rule
        with self.assertRaises(ValueError):
            denied(["Read .env"], "Read", f"{self.project}/.env", self.project)
        with self.assertRaises(ValueError):
            denied(["Write(.env)"], "Read", f"{self.project}/.env", self.project)  # Write rules don't exist: use Edit


if __name__ == "__main__":
    unittest.main()
