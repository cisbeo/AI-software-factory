"""Cases for factory discover, install and uninstall (spec §11.2, §11.3, §11.6, ADR 0004).

Each run works on throwaway git repositories, without network:
- a source checkout of the factory, committed, so the installer has a commit to pin;
- a new target repository whose `origin` says github.com but, through git's
  `insteadOf`, is a local bare repository;
- the fake `gh` of the forge contract tests (factory/tests/fake_gh.py) and the
  `claude` double of the doctor tests, first on PATH.
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SOURCE, run, write
from test_doctor import FAKE_CLAUDE
from test_forge_contract import FakeWorld

# What the source checkout needs (the installer reads its components from there).
SOURCE_PARTS = ("factory/bin", "factory/VERSION", "factory/config.json", "factory/dashboard.html",
                "factory/checks.sh", ".claude/agents", ".claude/hooks", ".claude/skills",
                ".claude/settings.json", "LICENSE")

PACKAGE_JSON = json.dumps({
    "name": "demo", "version": "0.0.0",
    "scripts": {"test": "node --test", "lint": "eslint .", "build": "tsc -p ."},
}, indent=2) + "\n"

# Answers to every question of §11.2, given on the command line.
ANSWERS = ("forge=github", "forge_plan=free", "tier=1", "deploy_target=aucune", "retry_budget=2",
           "max_cost_usd=10", "max_waiting_for_human=1", "base_branch=main")
QUESTIONS_GITHUB = 8  # forge, plan, tier, deploy target, three limits, base branch


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class InstallCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="factory-install-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = dict(os.environ)
        for k in ("FORGE", "FORGE_REPO", "GIT_DIR", "GIT_WORK_TREE"):
            self.env.pop(k, None)
        write(self.tmp / "gitconfig",
              "[user]\n\tname = Factory Test\n\temail = test@example.invalid\n"
              "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n"
              f'[url "file://{self.tmp}/origin.git"]\n\tinsteadOf = https://github.com/o/r.git\n'
              f'[url "file://{self.tmp}/origin.git"]\n\tinsteadOf = git@github.com:o/r.git\n'
              f'[url "file://{self.tmp}/origin.git"]\n\tinsteadOf = https://gitlab.example.com/g/p.git\n'
              f'[url "file://{self.tmp}/origin.git"]\n\tinsteadOf = https://example.org/o/r.git\n')
        self.env.update(GIT_CONFIG_GLOBAL=str(self.tmp / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
                        PYTHONDONTWRITEBYTECODE="1", CLAUDE_CONFIG_DIR=str(self.tmp / "claude-config"))

        (self.tmp / "world").mkdir()
        self.world = FakeWorld(self.tmp / "world")
        bindir = self.tmp / "bin"
        write(bindir / "claude", FAKE_CLAUDE, mode=0o755)
        self.env.update(PATH=f"{self.world.bindir}{os.pathsep}{bindir}{os.pathsep}{self.env['PATH']}",
                        FAKE_GH_STATE=str(self.world.state_path), FAKE_GH_LOG=str(self.world.log),
                        FAKE_CLAUDE_VERSION="9.0.0 (Claude Code)", FAKE_CLAUDE_LOG=str(self.tmp / "claude.log"))

        self.src = self.tmp / "src"
        self.make_source()
        self.target = self.tmp / "target"

    # ---- worlds -------------------------------------------------------------

    def git(self, cwd, *args):
        res = run(["git", *args], cwd=cwd, env=self.env)
        if res.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed in {cwd}: {res.stderr}")
        return res.stdout.strip()

    def make_source(self):
        for part in SOURCE_PARTS:
            src = SOURCE / part
            if src.is_dir():
                shutil.copytree(src, self.src / part, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                (self.src / part).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, self.src / part)
        config = json.loads((self.src / "factory/config.json").read_text())
        config["prices_as_of"] = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
        write(self.src / "factory/config.json", json.dumps(config, indent=2) + "\n")
        self.git(self.tmp, "init", "-q", str(self.src))
        self.git(self.src, "add", "-A")
        self.git(self.src, "commit", "-q", "-m", "factory source")

    def make_target(self, files=None, remote="https://github.com/o/r.git", branch="factory-install"):
        files = {"README.md": "# demo\n", "package.json": PACKAGE_JSON, "package-lock.json": "{}\n"} \
            if files is None else files
        self.git(self.tmp, "init", "-q", "--bare", "origin.git")
        self.git(self.tmp, "init", "-q", str(self.target))
        for name, text in files.items():
            write(self.target / name, text)
        self.git(self.target, "add", "-A")
        self.git(self.target, "commit", "-q", "--allow-empty", "-m", "init")
        if remote:
            self.git(self.target, "remote", "add", "origin", remote)
            self.git(self.target, "push", "-q", "origin", "main")
        if branch:
            self.git(self.target, "switch", "-q", "-c", branch)

    def commit_all(self, message="factory install"):
        self.git(self.target, "add", "-A")
        self.git(self.target, "commit", "-q", "-m", message)

    def factory(self, *args, stdin="", cwd=None):
        return run([sys.executable, "-B", str(self.src / "factory/bin/factory"), *args],
                   cwd=cwd or self.target, env=self.env, stdin=stdin)

    def answered(self, *extra):
        return [a for pair in (*ANSWERS, *extra) for a in ("--answer", pair)]

    def install(self, *args, stdin=""):
        return self.factory("install", *args, stdin=stdin)

    def ok(self, res, word="INSTALL: OK"):
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(word, res.stdout)
        self.assertNotIn("Traceback", res.stderr)
        return res

    def refused(self, res, *words, code=1):
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        for w in words:
            self.assertIn(w, res.stdout + res.stderr)
        return res

    def snapshot(self):
        """Every file of the target (outside .git), with its content and mode, and the forge's state."""
        files = {}
        for p in sorted(self.target.rglob("*")):
            if ".git" in p.relative_to(self.target).parts:
                continue
            if p.is_symlink():
                files[str(p.relative_to(self.target))] = ("link", os.readlink(p))
            elif p.is_file():
                files[str(p.relative_to(self.target))] = (p.read_bytes(), p.stat().st_mode)
        index = self.git(self.target, "status", "--porcelain", "--ignored")
        return files, index, self.world.load().get("labels")

    def journal(self):
        return json.loads((self.target / "factory/install-log.json").read_text())



# ---- discovery (§11.2) -----------------------------------------------------------

class Discovery(InstallCase):
    def test_survey_reports_every_item_and_writes_the_answers(self):
        self.make_target()
        write(self.target / ".git/hooks/pre-commit", "#!/bin/sh\nexit 0\n", mode=0o755)
        res = self.factory("discover", stdin="\n" * QUESTIONS_GITHUB)
        self.ok(res, "DISCOVER: OK")
        out = res.stdout
        for line in ("forge", "github", "o/r", "dépôt", "neuf", "pile", "node (npm)",
                     "install `npm ci`", "test `npm test`", "lint `npm run lint`", "build `npm run build`",
                     "CI", "instructions", "réglages Claude", "hooks git", "pre-commit",
                     "protection", "main non protégée", "droits", "pousser, étiqueter, fusionner",
                     "automatisations par commentaire", "secrets suivis"):
            self.assertIn(line, out)
        answers = json.loads((self.target / "factory/answers.json").read_text())["answers"]
        self.assertEqual(answers["forge"], "github")
        self.assertEqual(answers["tier"], 1)
        self.assertEqual(answers["retry_budget"], 3)
        self.assertEqual(answers["base_branch"], "main")
        # Read-only otherwise: only the answers file appears; nothing on the forge.
        self.assertEqual(self.git(self.target, "status", "--porcelain"), "?? factory/")
        self.assertEqual(self.world.load()["labels"], [])

    def test_discover_dry_run_writes_nothing(self):
        self.make_target()
        before = self.snapshot()
        self.ok(self.factory("discover", "--dry-run", stdin="\n" * QUESTIONS_GITHUB), "DISCOVER: OK")
        self.assertEqual(self.snapshot(), before)

    def test_each_question_proposes_the_detected_value(self):
        self.make_target(remote="git@github.com:o/r.git")
        res = self.ok(self.factory("discover", "--dry-run", stdin="\n" * QUESTIONS_GITHUB), "DISCOVER: OK")
        self.assertIn("Forge (github|gitlab) [github]", res.stdout)
        self.assertIn("Offre de la forge (free|pro|team|enterprise) [free]", res.stdout)
        self.assertIn("Palier visé (1|2|3) [1]", res.stdout)
        self.assertIn("Branche de base [main]", res.stdout)

    def test_gitlab_remote_asks_for_the_instance(self):
        self.make_target(remote="https://gitlab.example.com/g/p.git")
        res = self.factory("discover", "--dry-run", stdin="\n" * (QUESTIONS_GITHUB + 1))
        self.assertIn("Forge (github|gitlab) [gitlab]", res.stdout)
        self.assertIn("Instance GitLab [https://gitlab.example.com]", res.stdout)
        self.assertIn("(free|premium|ultimate)", res.stdout)
        self.refused(res, "GitLab")  # specified but not built: it blocks

    def test_replay_asks_nothing(self):
        self.make_target()
        self.ok(self.factory("discover", stdin="\n" * QUESTIONS_GITHUB), "DISCOVER: OK")
        res = self.ok(self.factory("discover", stdin=""), "DISCOVER: OK")
        self.assertNotIn("? ", res.stdout)
        self.assertIn("factory/answers.json", res.stdout)

    def test_answers_on_the_command_line(self):
        self.make_target()
        self.ok(self.factory("discover", *self.answered(), stdin=""), "DISCOVER: OK")
        answers = json.loads((self.target / "factory/answers.json").read_text())["answers"]
        self.assertEqual((answers["retry_budget"], answers["max_cost_usd"], answers["max_waiting_for_human"]),
                         (2, 10, 1))

    def test_a_missing_answer_fails_and_writes_nothing(self):
        self.make_target()
        before = self.snapshot()
        self.refused(self.factory("discover", stdin="\n\n"), "réponse manquante")
        self.assertEqual(self.snapshot(), before)

    def test_a_misunderstood_answer_is_asked_again(self):
        self.make_target()
        res = self.ok(self.factory("discover", stdin="bitbucket\n" + "\n" * QUESTIONS_GITHUB), "DISCOVER: OK")
        self.assertIn("réponse incomprise", res.stdout)
        self.assertEqual(json.loads((self.target / "factory/answers.json").read_text())["answers"]["forge"], "github")

    def test_unknown_forge_host_has_no_default(self):
        self.make_target(remote="https://example.org/o/r.git")
        res = self.factory("discover", "--dry-run", stdin="\n")
        self.assertIn("Forge (github|gitlab) : ", res.stdout)
        self.refused(res, "réponse manquante")

    def test_answers_file_that_is_not_understood_fails(self):
        self.make_target()
        complete = dict(a.split("=", 1) for a in ANSWERS)
        write(self.target / "factory/answers.json", json.dumps({"schema": 1, "answers": complete}))
        self.ok(self.factory("discover", stdin=""), "DISCOVER: OK")  # the neighbour: understood
        complete = dict(a.split("=", 1) for a in ANSWERS)
        for text in ("{", json.dumps({"schema": 1, "answers": dict(complete, colour="red")}),
                     json.dumps({"schema": 1, "answers": dict(complete, forge="bitbucket")}),
                     json.dumps({"schema": 1, "answers": dict(complete, tier="deux")}),
                     json.dumps({"schema": 1, "answers": {"forge": "github"}}),
                     json.dumps({"schema": 9, "answers": {}}), json.dumps([1])):
            write(self.target / "factory/answers.json", text)
            self.refused(self.factory("discover", stdin="\n" * QUESTIONS_GITHUB), "factory/answers.json")
            self.assertEqual((self.target / "factory/answers.json").read_text(), text)

    def test_answer_flag_cannot_contradict_the_answers_file(self):
        self.make_target()
        self.ok(self.factory("discover", stdin="\n" * QUESTIONS_GITHUB), "DISCOVER: OK")
        self.refused(self.factory("discover", "--answer", "tier=1", stdin=""), "factory/answers.json")

    def test_unknown_answer_key_is_a_usage_error(self):
        self.make_target()
        self.refused(self.factory("discover", "--answer", "colour=red"), "colour", code=2)
        self.refused(self.factory("discover", "--answer", "noequals"), code=2)


class SurveyBlocks(InstallCase):
    """What the survey finds that stops the install (fail closed), with its passing neighbour."""

    def blocked(self, *words):
        before = self.snapshot()
        res = self.refused(self.install(*self.answered()), "bloque", "INSTALL: FAIL", *words)
        self.assertEqual(self.snapshot(), before)
        return res

    def test_tracked_secret_blocks(self):
        self.make_target({"README.md": "x\n", "package.json": PACKAGE_JSON, "package-lock.json": "{}\n",
                          "deploy/server.key": "not a real key\n"})
        self.blocked("secrets suivis", "deploy/server.key")

    def test_names_close_to_secrets_pass(self):
        self.make_target({"README.md": "x\n", "package.json": PACKAGE_JSON, "package-lock.json": "{}\n",
                          "src/keys.py": "", "docs/env.md": "", "certificates/README.md": ""})
        res = self.ok(self.install("--dry-run", *self.answered()))
        self.assertIn("secrets suivis : aucun", res.stdout)

    def test_comment_triggered_automation_blocks(self):
        self.make_target({"README.md": "x\n", "package.json": PACKAGE_JSON, "package-lock.json": "{}\n",
                          ".github/workflows/deploy.yml": "on:\n  issue_comment:\n    types: [created]\n"})
        self.blocked("automatisations par commentaire", ".github/workflows/deploy.yml")

    def test_ci_on_push_is_reported_not_blocking(self):
        self.make_target({"README.md": "x\n", "package.json": PACKAGE_JSON, "package-lock.json": "{}\n",
                          ".github/workflows/ci.yml": "on:\n  push:\n  pull_request:\n"})
        res = self.ok(self.install("--dry-run", *self.answered()))
        self.assertIn("GitHub Actions (ci.yml)", res.stdout)
        self.assertIn("automatisations par commentaire : aucune", res.stdout)

    def test_unreadable_workflow_blocks(self):
        self.make_target({"README.md": "x\n", "package.json": PACKAGE_JSON, "package-lock.json": "{}\n"})
        (self.target / ".github/workflows").mkdir(parents=True)
        (self.target / ".github/workflows/odd.yml").write_bytes(b"on: \xff\xfe\n")
        self.commit_all("odd workflow")
        self.blocked("illisible", "odd.yml")

    def test_existing_repository_blocks(self):
        files = {f"src/f{i}.js": "" for i in range(60)}
        files.update({"package.json": PACKAGE_JSON, "package-lock.json": "{}\n"})
        self.make_target(files)
        self.blocked("dépôt existant", "ADR 0004")

    def test_small_new_repository_passes(self):
        files = {f"src/f{i}.js": "" for i in range(10)}
        files.update({"package.json": PACKAGE_JSON, "package-lock.json": "{}\n"})
        self.make_target(files)
        self.assertIn("neuf", self.ok(self.install("--dry-run", *self.answered())).stdout)

    def test_no_test_command_blocks(self):
        self.make_target({"README.md": "x\n", "package.json": json.dumps(
            {"name": "d", "scripts": {"test": 'echo "Error: no test specified" && exit 1'}})})
        self.blocked("aucune commande de test")

    def test_test_command_given_as_an_answer_passes(self):
        self.make_target({"README.md": "x\n"})
        res = self.ok(self.install("--dry-run", *self.answered("command.test=make check")))
        self.assertIn("test `make check`", res.stdout)

    def test_unreadable_manifest_blocks(self):
        self.make_target({"README.md": "x\n", "package.json": "{ not json"})
        self.blocked("package.json illisible")

    def test_unreadable_protection_blocks(self):
        self.make_target()
        self.world.rules_unreadable()
        self.blocked("protection", "illisible")

    def test_protected_base_is_reported(self):
        self.make_target()
        self.world.protect("main", {"required_pull_request_reviews": {"required_approving_review_count": 1}})
        res = self.ok(self.install("--dry-run", *self.answered()))
        self.assertIn("main protégée", res.stdout)
        self.assertIn("1 approbation", res.stdout)

    def test_gitlab_is_refused_until_its_adapter_exists(self):
        self.make_target(remote="https://gitlab.example.com/g/p.git")
        gitlab = [p for p in ANSWERS if not p.startswith("forge")] + \
            ["forge=gitlab", "forge_instance=https://gitlab.example.com", "forge_plan=premium"]
        before = self.snapshot()
        res = self.refused(self.install(*[a for p in gitlab for a in ("--answer", p)]),
                           "bloque", "GitLab", "ADR 0005", "INSTALL: FAIL")
        self.assertNotIn("== doctor", res.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_forge_answer_is_a_usage_error(self):
        self.make_target()
        self.refused(self.install("--answer", "forge=bitbucket"), "bitbucket", code=2)

    def test_later_tier_is_refused(self):
        self.make_target()
        res = self.install(*[a for p in ANSWERS if not p.startswith("tier=") for a in ("--answer", p)],
                           "--answer", "tier=2")
        self.refused(res, "palier 2")

    def test_no_origin_blocks(self):
        self.make_target(remote=None)
        self.refused(self.install(*self.answered()), "origin")


# ---- install (§11.3) -----------------------------------------------------------------

class DryRun(InstallCase):
    def test_dry_run_prints_the_plan_and_writes_nothing(self):
        self.make_target()
        before = self.snapshot()
        res = self.ok(self.install("--dry-run", *self.answered()), "INSTALL: OK (à blanc")
        self.assertEqual(self.snapshot(), before)
        for line in ("créer      factory/bin/job", "créer      factory/checks.sh", "créer      factory/config.json",
                     "créer      .claude/settings.json", "créer      .github/workflows/factory-checks.yml",
                     "créer      .gitignore", "créer      factory/answers.json", "créer      factory/install-log.json",
                     "label      créer factory:needs-human"):
            self.assertIn(line, res.stdout)
        self.assertNotIn("POST", "".join(self.world.log.read_text().splitlines()) if self.world.log.exists() else "")

    def test_dry_run_runs_the_doctor_first(self):
        self.make_target()
        res = self.ok(self.install("--dry-run", *self.answered()))
        self.assertLess(res.stdout.index("DOCTOR: OK"), res.stdout.index("== découverte"))

    def test_failing_doctor_stops_before_anything(self):
        self.make_target()
        write(self.target / "scratch.txt", "dirty\n")
        before = self.snapshot()
        self.refused(self.install(*self.answered()), "DOCTOR: FAIL", "INSTALL: FAIL")
        self.assertEqual(self.snapshot(), before)

    def test_unknown_option_is_a_usage_error(self):
        self.make_target()
        before = self.snapshot()
        self.refused(self.install("--dry-runn"), code=2)
        self.assertEqual(self.snapshot(), before)


class Install(InstallCase):
    def setUp(self):
        super().setUp()
        self.make_target()

    def test_install_poses_the_components_of_the_chosen_forge(self):
        res = self.ok(self.install(*self.answered()))
        t = self.target
        for path in ("factory/bin/job", "factory/bin/gate", "factory/bin/route", "factory/bin/forge",
                     "factory/bin/doctor", "factory/bin/audit", "factory/bin/factory", "factory/bin/installer",
                     "factory/VERSION", "factory/config.json", "factory/checks.sh", "factory/LICENSE",
                     ".claude/agents/builder.md", ".claude/hooks/guard.py", ".claude/settings.json",
                     ".claude/skills/factory/SKILL.md", ".claude/skills/tdd/SKILL.md",
                     ".github/workflows/factory-checks.yml", ".gitignore",
                     "factory/answers.json", "factory/install-log.json"):
            self.assertTrue((t / path).is_file(), path)
        self.assertTrue(os.access(t / "factory/bin/job", os.X_OK))
        self.assertTrue(os.access(t / "factory/checks.sh", os.X_OK))
        # Nothing of the other forge.
        everything = [str(p.relative_to(t)) for p in t.rglob("*") if ".git" not in p.relative_to(t).parts[:1]]
        self.assertEqual([p for p in everything if "gitlab" in p.lower()], [])
        config = json.loads((t / "factory/config.json").read_text())
        self.assertEqual((config["forge"], config["base_branch"], config["retry_budget"],
                          config["max_cost_usd"], config["max_waiting_for_human"]), ("github", "main", 2, 10, 1))
        for p in ("factory/answers.json", "factory/install-log.json", ".github/workflows/*"):
            self.assertIn(p, config["protected_paths"])
        self.assertEqual(self.world.repo_labels(), {"factory", "factory:needs-info", "factory:needs-human"})
        self.assertIn(".github/workflows/factory-checks.yml", res.stdout)

    def test_version_and_source_commit_are_written_in_the_target(self):
        self.ok(self.install(*self.answered()))
        self.assertEqual((self.target / "factory/VERSION").read_text(), (self.src / "factory/VERSION").read_text())
        journal = self.journal()
        self.assertEqual(journal["factory_version"], (self.src / "factory/VERSION").read_text().strip())
        self.assertEqual(journal["source_commit"], self.git(self.src, "rev-parse", "HEAD"))

    def test_external_sources_are_pinned_to_a_commit(self):
        self.ok(self.install(*self.answered()))
        workflow = (self.target / ".github/workflows/factory-checks.yml").read_text()
        uses = re.findall(r"uses:\s*(\S+)", workflow)
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r"@[0-9a-f]{40}$")
        for source in self.journal()["sources"]:
            self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
        audit = run([sys.executable, "-B", str(self.target / "factory/bin/audit"), "--root", str(self.target)],
                    env=self.env)
        self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)

    def test_journal_lists_every_posed_file_once(self):
        self.ok(self.install(*self.answered()))
        journal = self.journal()
        paths = [f["path"] for f in journal["files"]]
        self.assertEqual(len(paths), len(set(paths)))
        for entry in journal["files"]:
            self.assertEqual(entry["sha256"], sha256(self.target / entry["path"]), entry["path"])
            self.assertEqual(entry["action"], "created")
        self.assertIn("factory/checks.sh", paths)
        self.assertEqual({l["name"] for l in journal["labels"] if l["created"]},
                         {"factory", "factory:needs-info", "factory:needs-human"})

    def test_checks_sh_runs_the_surveyed_commands_in_order(self):
        self.ok(self.install(*self.answered()))
        text = (self.target / "factory/checks.sh").read_text()
        positions = [text.index(c) for c in ("npm ci", "npm run lint", "npm test", "npm run build")]
        self.assertEqual(positions, sorted(positions))

    def test_checks_sh_fails_when_a_command_fails(self):
        for test, code in (("true", 0), ("false", 1)):
            with self.subTest(test=test):
                shutil.rmtree(self.target)
                shutil.rmtree(self.tmp / "origin.git")
                self.make_target({"README.md": "x\n"})
                self.ok(self.install(*self.answered(f"command.test={test}")))
                res = run(["bash", "factory/checks.sh"], cwd=self.target, env=self.env)
                self.assertEqual(res.returncode, code, res.stdout + res.stderr)

    def test_command_answer_on_several_lines_is_not_understood(self):
        self.refused(self.install(*self.answered("command.test=true\nrm -rf ~")), "command.test", code=2)

    def test_source_with_uncommitted_changes_is_not_pinned(self):
        with open(self.src / "factory/bin/job", "a") as f:
            f.write("# local change\n")
        before = self.snapshot()
        self.refused(self.install(*self.answered()), "épingl", "factory/bin/job")
        self.assertEqual(self.snapshot(), before)

    def test_source_outside_git_is_refused(self):
        shutil.rmtree(self.src / ".git")
        before = self.snapshot()
        self.refused(self.install(*self.answered()), "épingl")
        self.assertEqual(self.snapshot(), before)

    def test_install_into_the_factory_itself_is_refused(self):
        self.refused(self.factory("install", "--dry-run", *self.answered(), cwd=self.src), "elle-même")

    def test_symlink_out_of_the_target_is_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        os.symlink(outside, self.target / ".claude")
        self.commit_all("link")
        self.refused(self.install(*self.answered()), ".claude")
        self.assertEqual(list(outside.iterdir()), [])


class Replay(InstallCase):
    def setUp(self):
        super().setUp()
        self.make_target()
        self.ok(self.install(*self.answered()))
        self.commit_all()

    def test_second_run_creates_no_duplicate_and_reports_no_drift(self):
        journal = (self.target / "factory/install-log.json").read_text()
        gitignore = (self.target / ".gitignore").read_text()
        calls = len(self.world.log.read_text().splitlines())
        res = self.ok(self.install(stdin=""))  # answers come from factory/answers.json
        self.assertIn("aucun écart", res.stdout)
        self.assertNotIn("créer ", res.stdout)
        self.assertNotIn("? ", res.stdout)
        self.assertEqual((self.target / "factory/install-log.json").read_text(), journal)
        self.assertEqual((self.target / ".gitignore").read_text(), gitignore)
        self.assertEqual(self.git(self.target, "status", "--porcelain"), "")
        new_calls = [json.loads(l) for l in self.world.log.read_text().splitlines()[calls:]]
        self.assertEqual([c for c in new_calls if "POST" in c or "DELETE" in c], [])
        self.assertEqual(len(self.world.load()["labels"]), 3)

    def test_second_run_reports_only_the_drift(self):
        write(self.target / "factory/checks.sh", "#!/bin/sh\nexit 0\n", mode=0o755)
        (self.target / "factory/dashboard.html").unlink()
        self.commit_all("local edits")
        res = self.refused(self.install(stdin=""), "INSTALL: INCOMPLET")
        plan = res.stdout[res.stdout.index("== plan"):]
        self.assertIn("garder     factory/checks.sh", plan)
        self.assertIn("créer      factory/dashboard.html", plan)
        self.assertNotIn("factory/bin/job", plan)
        self.assertEqual((self.target / "factory/checks.sh").read_text(), "#!/bin/sh\nexit 0\n")
        self.assertTrue((self.target / "factory/dashboard.html").exists())

    def test_label_removed_on_the_forge_is_posed_again(self):
        self.world.edit(lambda s: s.update(labels=[l for l in s["labels"] if l["name"] != "factory"]))
        res = self.ok(self.install(stdin=""))
        self.assertIn("label      créer factory", res.stdout)
        self.assertEqual(len(self.world.load()["labels"]), 3)


class Overwrite(InstallCase):
    """No existing file is replaced without its own explicit consent."""

    USER_SETTINGS = '{"permissions": {"allow": ["Bash(npm test)"]}}\n'
    USER_GITIGNORE = "node_modules/\n"

    def setUp(self):
        super().setUp()
        self.make_target({"README.md": "x\n", "package.json": PACKAGE_JSON, "package-lock.json": "{}\n",
                          ".claude/settings.json": self.USER_SETTINGS, ".gitignore": self.USER_GITIGNORE,
                          "factory/LICENSE": (self.src / "LICENSE").read_text()})

    def test_without_consent_existing_files_are_kept(self):
        res = self.refused(self.install(*self.answered(), stdin=""), "INSTALL: INCOMPLET")
        self.assertIn("missing deny rule", res.stdout)  # the audit says what keeping it costs
        self.assertEqual((self.target / ".claude/settings.json").read_text(), self.USER_SETTINGS)
        self.assertEqual((self.target / ".gitignore").read_text(), self.USER_GITIGNORE)
        self.assertIn("garder     .claude/settings.json", res.stdout)
        self.assertIn("garder     .gitignore", res.stdout)
        self.assertTrue((self.target / "factory/bin/job").exists())  # the rest is posed

    def test_consent_is_given_file_by_file(self):
        res = self.refused(self.install(*self.answered(), "--overwrite", ".gitignore", stdin=""),
                           "INSTALL: INCOMPLET")
        self.assertEqual((self.target / ".claude/settings.json").read_text(), self.USER_SETTINGS)
        gitignore = (self.target / ".gitignore").read_text()
        self.assertTrue(gitignore.startswith(self.USER_GITIGNORE))
        self.assertIn("/factory/jobs/", gitignore)
        self.assertIn("remplacer  .gitignore", res.stdout)
        entry = {f["path"]: f for f in self.journal()["files"]}[".gitignore"]
        self.assertEqual(entry["action"], "replaced")
        self.assertEqual((self.target / entry["backup"]).read_text(), self.USER_GITIGNORE)

    def test_interactive_consent_asks_each_file(self):
        res = self.refused(self.install(*self.answered(), stdin="o\nn\n"), "INSTALL: INCOMPLET")
        self.assertEqual(res.stdout.count("écraser ?"), 2)
        replaced = [p for p, text in ((".claude/settings.json", self.USER_SETTINGS), (".gitignore", self.USER_GITIGNORE))
                    if (self.target / p).read_text() != text]
        self.assertEqual(len(replaced), 1)

    def test_consent_answer_not_understood_is_a_refusal(self):
        self.refused(self.install(*self.answered(), stdin="peut-être\nouais\n"), "INSTALL: INCOMPLET")
        self.assertEqual((self.target / ".claude/settings.json").read_text(), self.USER_SETTINGS)
        self.assertEqual((self.target / ".gitignore").read_text(), self.USER_GITIGNORE)

    def test_identical_existing_file_is_left_and_not_journaled(self):
        self.install(*self.answered(), stdin="")
        self.assertNotIn("factory/LICENSE", [f["path"] for f in self.journal()["files"]])

    def test_overwrite_of_a_path_without_conflict_is_a_usage_error(self):
        before = self.snapshot()
        self.refused(self.install(*self.answered(), "--overwrite", "README.md"), "README.md", code=2)
        self.refused(self.install(*self.answered(), "--overwrite", "../x"), "../x", code=2)
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_asks_no_consent(self):
        before = self.snapshot()
        res = self.ok(self.install("--dry-run", *self.answered(), stdin="o\no\n"), "à blanc")
        self.assertNotIn("écraser ?", res.stdout)
        self.assertIn("remplacer? .gitignore (accord requis)", res.stdout)
        self.assertEqual(self.snapshot(), before)


# ---- uninstall (§11.3) ---------------------------------------------------------------

class Uninstall(InstallCase):
    USER_GITIGNORE = "node_modules/\n"

    def setUp(self):
        super().setUp()
        self.make_target({"README.md": "x\n", "package.json": PACKAGE_JSON, "package-lock.json": "{}\n",
                          ".gitignore": self.USER_GITIGNORE})
        self.world.edit(lambda s: s["labels"].append({"name": "factory", "color": "000000", "description": "mine"}))
        self.before = self.snapshot()
        self.ok(self.install(*self.answered(), "--overwrite", ".gitignore"))
        self.commit_all()

    def uninstall(self, *args):
        return self.factory("uninstall", *args)

    def test_uninstall_removes_what_install_posed(self):
        self.ok(self.uninstall(), "UNINSTALL: OK")
        files, _, labels = self.snapshot()
        self.assertEqual(files, self.before[0])
        self.assertEqual([l["name"] for l in labels], ["factory"])  # existed before: kept

    def test_uninstall_from_the_installed_copy(self):
        res = run([sys.executable, "-B", str(self.target / "factory/bin/factory"), "uninstall"],
                  cwd=self.target, env=self.env)
        self.ok(res, "UNINSTALL: OK")
        self.assertEqual(self.snapshot()[0], self.before[0])

    def test_uninstall_dry_run_removes_nothing(self):
        before = self.snapshot()
        res = self.ok(self.uninstall("--dry-run"), "UNINSTALL: OK (à blanc")
        self.assertIn("retirer     factory/bin/job", res.stdout)
        self.assertIn("restaurer   .gitignore", res.stdout)
        self.assertIn("label       retirer factory:needs-info", res.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_file_changed_since_install_is_kept(self):
        write(self.target / "factory/checks.sh", "#!/bin/sh\nexit 0\n", mode=0o755)
        res = self.refused(self.uninstall(), "UNINSTALL: INCOMPLET", "factory/checks.sh")
        self.assertTrue((self.target / "factory/checks.sh").exists())
        self.assertFalse((self.target / "factory/bin/job").exists())
        self.assertEqual([f["path"] for f in self.journal()["files"]], ["factory/checks.sh"])
        self.assertIn("garder", res.stdout)

    def test_without_journal_nothing_is_removed(self):
        (self.target / "factory/install-log.json").unlink()
        before = self.snapshot()
        self.refused(self.uninstall(), "UNINSTALL: FAIL", "factory/install-log.json")
        self.assertEqual(self.snapshot(), before)

    def test_journal_not_understood_removes_nothing(self):
        outside = self.tmp / "outside.txt"
        outside.write_text("keep me\n")
        journal = self.journal()
        good = journal["files"][0]
        for bad in ({"path": "../outside.txt", "sha256": sha256(outside), "action": "created"},
                    {"path": str(outside), "sha256": sha256(outside), "action": "created"},
                    {"path": ".git/config", "sha256": "0" * 64, "action": "created"},
                    {"path": good["path"], "sha256": good["sha256"], "action": "shredded"},
                    {"path": good["path"], "sha256": "abc", "action": "created"},
                    {"path": ".gitignore", "sha256": sha256(self.target / ".gitignore"), "action": "replaced",
                     "backup": "../outside.txt"}):
            with self.subTest(bad=bad):
                broken = dict(journal, files=journal["files"] + [bad])
                write(self.target / "factory/install-log.json", json.dumps(broken))
                before = self.snapshot()
                self.refused(self.uninstall(), "UNINSTALL: FAIL", "factory/install-log.json")
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(outside.read_text(), "keep me\n")
        write(self.target / "factory/install-log.json", "{")
        self.refused(self.uninstall(), "UNINSTALL: FAIL")


if __name__ == "__main__":
    unittest.main()
