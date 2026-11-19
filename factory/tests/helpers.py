"""Shared fixtures for the factory's verification suite.

Each test copies the scripts under test into a throwaway `factory/` inside a
temporary directory, so `factory/jobs/` and the config live there, never in
this checkout. Forge commands (`gh`, `forge`) are replaced on PATH by a stub
that logs its arguments and fails: a control that reaches the forge when it
should refuse first shows up in the log.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]  # this checkout
FACTORY_SRC = SOURCE / "factory"

FORGE_STUB = """#!/bin/sh
printf '%s\\n' "$(basename "$0") $*" >> "$FORGE_LOG"
echo "forge stub: no network in tests" >&2
exit 1
"""


def run(cmd, cwd=None, env=None, stdin=None):
    return subprocess.run(cmd, cwd=cwd, env=env, input=stdin, capture_output=True, text=True)


def write(path, text, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode is not None:
        path.chmod(mode)


class FactoryCase(unittest.TestCase):
    """A temporary repo root holding a copy of factory/bin/* and config.json."""

    scripts = ("job", "gate", "route")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="factory-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "main"
        self.factory = self.root / "factory"
        (self.factory / "bin").mkdir(parents=True)
        for name in self.scripts:
            shutil.copy2(FACTORY_SRC / "bin" / name, self.factory / "bin" / name)
        self.config = json.loads((FACTORY_SRC / "config.json").read_text())
        self.write_config()
        self.jobs = self.factory / "jobs"
        self.jobs.mkdir()

        stubs = self.tmp / "stubs"
        for name in ("gh", "forge"):
            write(stubs / name, FORGE_STUB, mode=0o755)
        self.forge_log = self.tmp / "forge.log"
        self.env = dict(os.environ)
        self.env.update({
            "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
            "FORGE_LOG": str(self.forge_log),
            "CLAUDE_CONFIG_DIR": str(self.tmp / "claude-config"),  # no real transcripts
            "GIT_CONFIG_GLOBAL": str(self.tmp / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        write(self.tmp / "gitconfig",
              "[user]\n\tname = Factory Test\n\temail = test@example.invalid\n"
              "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n")

    def write_config(self):
        write(self.factory / "config.json", json.dumps(self.config, indent=2))

    def bin(self, name, *args, stdin=None):
        return run([sys.executable, "-B", str(self.factory / "bin" / name), *args],
                   cwd=self.root, env=self.env, stdin=stdin)

    def use_fake_forge(self):
        """Put the real factory/bin/forge in the job's bin, backed by the fake
        `gh` of the contract tests (an in-memory GitHub). Returns that world:
        create tickets and merge requests there, read what the job did there."""
        from test_forge_contract import FakeWorld
        shutil.copy2(FACTORY_SRC / "bin" / "forge", self.factory / "bin" / "forge")
        (self.tmp / "world").mkdir(exist_ok=True)
        world = FakeWorld(self.tmp / "world")
        env = world.env()
        self.env.update(PATH=f"{world.bindir}{os.pathsep}{self.env['PATH']}",
                        FAKE_GH_STATE=env["FAKE_GH_STATE"], FAKE_GH_LOG=env["FAKE_GH_LOG"], FORGE="github")
        self.env.pop("FORGE_REPO", None)
        return world

    def gh_calls(self):
        log = self.tmp / "world" / "gh.log"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    def forge_calls(self):
        return self.forge_log.read_text().splitlines() if self.forge_log.exists() else []

    def git(self, cwd, *args):
        res = run(["git", *args], cwd=cwd, env=self.env)
        if res.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed in {cwd}: {res.stderr}")
        return res.stdout.strip()

    # ---- Jobs ---------------------------------------------------------------

    def make_job(self, job_id="001-test", **fields):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        job = {
            "id": job_id, "issue": 1, "title": "Test", "issue_url": "https://forge.invalid/1",
            "pr": None, "pr_url": None, "branch": f"factory/{job_id}",
            "worktree": str(self.root / ".worktrees" / job_id),
            "stage": "intake", "round": 0,
            "retries_left": self.config["retry_budget"], "inconclusive": 0, "exit": None,
            "intake": None, "agents": None, "gate": None, "reviews": {},
            "cost_usd": 0.0, "started": now, "ended": None,
            "active_seconds": 0, "running_since": now,
        }
        job.update(fields)
        d = self.jobs / job_id
        d.mkdir(parents=True, exist_ok=True)
        write(d / "job.json", json.dumps(job, indent=2) + "\n")
        return d

    def read_job(self, job_id="001-test"):
        return json.loads((self.jobs / job_id / "job.json").read_text())
