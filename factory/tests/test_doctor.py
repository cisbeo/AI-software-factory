"""Cases for factory/bin/doctor (spec §11.1, issue #18).

Each check gets a case that must fail (with the fix to make), a neighbouring
case that passes, and the case where the input isn't understood (fail closed).
The world is built from scratch: PATH holds only this test's `git`,
`python3`, `gh` (factory/tests/fake_gh.py) and `claude` doubles, plus /bin
and /usr/bin, so the real forge and the real Claude Code are never reached.
"""

import datetime
import json
import shutil
import sys
from pathlib import Path

from helpers import FACTORY_SRC, FactoryCase, run, write

TESTS = Path(__file__).resolve().parent
REAL_GIT = shutil.which("git")

FAKE_CLAUDE = """#!/bin/sh
# claude double: version from FAKE_CLAUDE_VERSION, models refused when named in FAKE_CLAUDE_DENY.
if [ "$1" = "--version" ]; then echo "$FAKE_CLAUDE_VERSION"; exit 0; fi
printf '%s\\n' "claude $*" >> "$FAKE_CLAUDE_LOG"
model=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--model" ]; then model="$2"; fi
  shift
done
if [ -n "$FAKE_CLAUDE_RAW" ]; then echo "$FAKE_CLAUDE_RAW"; exit 0; fi
case " $FAKE_CLAUDE_DENY " in
  *" $model "*) echo '{"type":"result","is_error":true,"result":"model not available"}'; exit 1;;
esac
echo '{"type":"result","is_error":false,"result":"OK"}'
"""


def wrapper(real, version_var):
    """A double that answers `--version` from an env var when set, else runs the real tool."""
    return (f'#!/bin/sh\nif [ "$1" = "--version" ] && [ -n "${version_var}" ]; then '
            f'echo "${version_var}"; exit 0; fi\nexec "{real}" "$@"\n')


class DoctorCase(FactoryCase):
    scripts = ("doctor", "forge")

    def setUp(self):
        super().setUp()
        self.config["prices_as_of"] = self.days_ago(10)
        self.write_config()

        # The repository under diagnosis, with its remote, in sync and clean.
        self.git(self.tmp, "init", "-q", "--bare", "origin.git")
        self.git(self.root, "init", "-q")
        write(self.root / ".gitignore", "factory/jobs/\n*.log\n")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "init")
        self.git(self.root, "remote", "add", "origin", str(self.tmp / "origin.git"))
        self.git(self.root, "push", "-q", "origin", "main")

        self.bindir = self.tmp / "doctor-bin"
        write(self.bindir / "git", wrapper(REAL_GIT, "FAKE_GIT_VERSION"), mode=0o755)
        write(self.bindir / "python3", wrapper(sys.executable, "FAKE_PYTHON_VERSION"), mode=0o755)
        write(self.bindir / "gh", f'#!/bin/sh\nexec "{sys.executable}" -B "{TESTS / "fake_gh.py"}" "$@"\n',
              mode=0o755)
        write(self.bindir / "claude", FAKE_CLAUDE, mode=0o755)
        self.gh_state = self.tmp / "gh-state.json"
        self.gh_state.write_text(json.dumps({
            "user": "operator", "next": 0, "issues": {}, "comments": {}, "deps": {}, "pulls": {},
            "check_runs": {}, "statuses": {}, "reviews": {}, "protection": {}, "rules": {}}))
        self.claude_log = self.tmp / "claude.log"
        self.env.update({
            "PATH": f"{self.bindir}:/bin:/usr/bin",
            "FAKE_GH_STATE": str(self.gh_state),
            "FAKE_CLAUDE_VERSION": "9.0.0 (Claude Code)",
            "FAKE_CLAUDE_LOG": str(self.claude_log),
            "FORGE": "github",
        })
        self.env.pop("FORGE_REPO", None)

    # ---- helpers ------------------------------------------------------------

    @staticmethod
    def days_ago(n):
        return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()

    def gh_edit(self, **change):
        state = json.loads(self.gh_state.read_text())
        state.update(change)
        self.gh_state.write_text(json.dumps(state))

    def doctor(self):
        return self.bin("doctor")

    def passes(self):
        res = self.doctor()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("DOCTOR: OK", res.stdout)
        self.assertNotIn("Traceback", res.stderr)
        return res

    def fails(self, *words):
        """Doctor stops with exit 1, names the problem and gives a fix; no later check runs."""
        res = self.doctor()
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("DOCTOR: FAIL", res.stdout)
        self.assertIn("Correction :", res.stdout)
        self.assertNotIn("Traceback", res.stderr)
        for w in words:
            self.assertIn(w, res.stdout)
        return res

    def checked_models(self):
        return self.claude_log.read_text().splitlines() if self.claude_log.exists() else []


class AllGood(DoctorCase):
    def test_a_ready_repository_passes_every_check(self):
        out = self.passes().stdout
        for name in ("claude", "git", "python3", "forge", "droits", "propre", "à jour", "tarifs", "modèles"):
            self.assertIn(name, out)

    def test_doctor_writes_nothing(self):
        before = self.git(self.root, "status", "--porcelain", "--ignored")
        config = (self.factory / "config.json").read_text()
        state = self.gh_state.read_text()
        self.passes()
        self.assertEqual(self.git(self.root, "status", "--porcelain", "--ignored"), before)
        self.assertEqual((self.factory / "config.json").read_text(), config)
        self.assertEqual(json.loads(self.gh_state.read_text()), json.loads(state))

    def test_unknown_argument_is_a_usage_error(self):
        self.assertEqual(self.bin("doctor", "--frobnicate").returncode, 2)


class Tools(DoctorCase):
    # Claude Code
    def test_missing_claude_fails(self):
        (self.bindir / "claude").unlink()
        self.fails("claude", "introuvable")

    def test_old_claude_fails(self):
        self.env["FAKE_CLAUDE_VERSION"] = "2.0.99 (Claude Code)"
        self.fails("claude", "2.0.99")

    def test_claude_at_a_recent_version_passes(self):
        self.env["FAKE_CLAUDE_VERSION"] = "12.3.4 (Claude Code)"
        self.assertIn("12.3.4", self.passes().stdout)

    def test_unreadable_claude_version_fails(self):
        self.env["FAKE_CLAUDE_VERSION"] = "Claude Code nightly"
        self.fails("claude", "illisible")

    # git
    def test_old_git_fails(self):
        self.env["FAKE_GIT_VERSION"] = "git version 2.16.0"
        self.fails("git", "2.16.0")

    def test_git_at_the_minimum_passes(self):
        self.env["FAKE_GIT_VERSION"] = "git version 2.17.0"
        self.passes()

    def test_unreadable_git_version_fails(self):
        self.env["FAKE_GIT_VERSION"] = "git version banana"
        self.fails("git", "illisible")

    # python3
    def test_old_python_fails(self):
        self.env["FAKE_PYTHON_VERSION"] = "Python 3.8.18"
        self.fails("python3", "3.8.18")

    def test_python_at_the_minimum_passes(self):
        self.env["FAKE_PYTHON_VERSION"] = "Python 3.9.0"
        self.passes()

    def test_unreadable_python_version_fails(self):
        self.env["FAKE_PYTHON_VERSION"] = "Python three"
        self.fails("python3", "illisible")


class ForgeAccess(DoctorCase):
    def test_missing_forge_cli_fails(self):
        (self.bindir / "gh").unlink()
        self.fails("forge", "gh")

    def test_unauthenticated_forge_cli_fails(self):
        self.gh_edit(unauthenticated=True)
        self.fails("gh auth login")

    def test_authenticated_forge_cli_passes_with_its_login(self):
        self.assertIn("operator", self.passes().stdout)

    def test_unknown_identity_fails(self):
        self.gh_edit(user=None)
        self.fails("forge", "illisible")

    def test_reader_cannot_push(self):
        self.gh_edit(permissions={"admin": False, "maintain": False, "push": False, "triage": False, "pull": True})
        self.fails("pousser")

    def test_triager_cannot_push(self):
        self.gh_edit(permissions={"admin": False, "maintain": False, "push": False, "triage": True, "pull": True})
        res = self.fails("pousser")
        self.assertIn("fusionner", res.stdout)

    def test_writer_passes(self):
        self.gh_edit(permissions={"admin": False, "maintain": False, "push": True, "triage": False, "pull": True})
        self.passes()

    def test_unreadable_permissions_fail(self):
        self.gh_edit(permissions=None)
        self.fails("droits", "illisible")


class WorkingTree(DoctorCase):
    def test_modified_file_fails(self):
        write(self.root / ".gitignore", "changed\n")
        self.fails("propre", ".gitignore", "git status")

    def test_untracked_file_fails(self):
        write(self.root / "notes.txt", "x")
        self.fails("propre", "notes.txt")

    def test_ignored_files_pass(self):
        write(self.root / "debug.log", "x")
        self.passes()

    def test_outside_a_git_repository_fails(self):
        shutil.rmtree(self.root / ".git")
        self.fails("dépôt git")


class BaseBranch(DoctorCase):
    def push_from_elsewhere(self):
        other = self.tmp / "other"
        self.git(self.tmp, "clone", "-q", str(self.tmp / "origin.git"), str(other))
        write(other / "new.txt", "x")
        self.git(other, "add", "-A")
        self.git(other, "commit", "-q", "-m", "elsewhere")
        self.git(other, "push", "-q", "origin", "main")

    def test_base_behind_the_remote_fails(self):
        self.push_from_elsewhere()
        self.fails("main", "en retard", "git pull --ff-only")

    def test_base_ahead_of_the_remote_fails(self):
        write(self.root / "local.txt", "x")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "local")
        self.fails("main", "en avance")

    def test_base_in_sync_from_another_branch_passes(self):
        self.git(self.root, "switch", "-q", "-c", "feature")
        self.passes()

    def test_base_missing_on_the_remote_fails(self):
        self.config["base_branch"] = "trunk"
        self.write_config()
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "trunk")
        self.git(self.root, "push", "-q", "origin", "main")
        self.fails("trunk", "origin")

    def test_without_an_origin_remote_fails(self):
        self.git(self.root, "remote", "remove", "origin")
        self.fails("origin")


class Prices(DoctorCase):
    def commit_config(self):
        self.write_config()
        self.git(self.root, "commit", "-q", "-am", "config")
        self.git(self.root, "push", "-q", "origin", "main")

    def test_prices_older_than_90_days_are_flagged_without_stopping(self):
        self.config["prices_as_of"] = self.days_ago(91)
        self.commit_config()
        res = self.passes()
        self.assertIn("91 jours", res.stdout)
        self.assertIn("warn", res.stdout)

    def test_prices_of_exactly_90_days_are_not_flagged(self):
        self.config["prices_as_of"] = self.days_ago(90)
        self.commit_config()
        self.assertNotIn("warn", self.passes().stdout)

    def test_undated_prices_fail(self):
        del self.config["prices_as_of"]
        self.commit_config()
        self.fails("prices_as_of")

    def test_unreadable_price_date_fails(self):
        self.config["prices_as_of"] = "14/11/2026"
        self.commit_config()
        self.fails("prices_as_of", "illisible")

    def test_price_date_in_the_future_fails(self):
        self.config["prices_as_of"] = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
        self.commit_config()
        self.fails("prices_as_of", "futur")


class Models(DoctorCase):
    def test_every_configured_model_is_tried_once(self):
        self.passes()
        tried = sorted(line.split("--model ")[1].split()[0] for line in self.checked_models())
        self.assertEqual(tried, ["haiku", "opus", "sonnet"])

    def test_refused_model_fails_and_names_it(self):
        self.env["FAKE_CLAUDE_DENY"] = "opus"
        self.fails("opus")

    def test_unreadable_model_answer_fails(self):
        self.env["FAKE_CLAUDE_RAW"] = "<html>proxy error</html>"
        self.fails("modèle", "illisible")

    def test_model_that_is_not_a_name_fails(self):
        self.config["routing"]["low"] = {"code": 3}
        self.write_config()
        self.git(self.root, "commit", "-q", "-am", "config")
        self.git(self.root, "push", "-q", "origin", "main")
        self.fails("routing")
        self.assertEqual(self.checked_models(), [])

    def test_models_are_not_tried_when_an_earlier_check_fails(self):
        write(self.root / "notes.txt", "x")
        self.fails("propre")
        self.assertEqual(self.checked_models(), [])


class Config(DoctorCase):
    def test_unreadable_config_fails(self):
        write(self.factory / "config.json", "{not json")
        self.fails("config.json")
