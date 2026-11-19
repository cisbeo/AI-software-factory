#!/usr/bin/env python3
"""Prove each control's tests can fail: break the control, run its tests, restore.

Usage: python3 -B factory/tests/mutations.py

Each mutation rewrites one line of a factory script, runs the tests that cover
that control, and restores the file. Exits 1 if a mutation survives (its tests
still pass), meaning the suite no longer watches that control. Run it before
removing or changing a control (spec §7.2).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "factory" / "tests"

# (control broken, file, original text, mutated text, tests that must fail)
MUTATIONS = [
 ("job: table des transitions ignorée", "factory/bin/job", 'require(stage in TRANSITIONS.get(old, set()) or', 'require(True or', "test_job_transitions"),
 ("job: fichier justificatif ignoré", "factory/bin/job", 'require((d / "spec.md").exists(), "spec.md doesn\'t exist")', 'pass', "test_job_transitions"),
 ("gate: chemins protégés ignorés", "factory/bin/gate", 'verdict = "PASS" if code == 0 and not protected and not untraced else "FAIL"', 'verdict = "PASS" if code == 0 and not untraced else "FAIL"', "test_gate.ProtectedPaths"),
 ("gate: checks.sh de la branche exécuté", "factory/bin/gate", 'res = subprocess.run(checks_command(), cwd=worktree,', 'res = subprocess.run(["bash", "factory/checks.sh"], cwd=worktree,', "test_gate.BaseChecksRun test_gate.BaseChecksFail"),
 ("gate: chemin cité accepté", "factory/bin/gate", "hit = old  # fail closed", "hit = None  # fail closed", "test_gate.ProtectedPaths"),
 ("route: risque inconnu accepté", "factory/bin/route", 'risk = CONFIG["routing"].get(intake["risk"]) or die(', 'risk = CONFIG["routing"].get(intake["risk"]) or CONFIG["routing"]["low"] or die(', "test_route"),
 ("route: risque faible routé comme moyen", "factory/bin/route", 'reviewers = dict(risk)', 'reviewers = dict(CONFIG["routing"]["medium"]) if intake["risk"] == "low" else dict(risk)', "test_route"),
 ("route: surface inconnue ignorée", "factory/bin/route", 'if extra is None:\n            die(', 'if extra is None:\n            continue\n            die(', "test_route"),
 ("job: surface sérialisée partagée", "factory/bin/job", 'require(not busy, f"serial surface {surface}', 'require(True, f"serial surface {surface}', "test_serial_surfaces"),
 ("job: serial_surfaces malformé accepté", "factory/bin/job", 'if not isinstance(value, list) or not all(', 'if False and not all(', "test_serial_surfaces"),
 ("job: budget de reprise jamais dépensé", "factory/bin/job", 'left = max(0, job["retries_left"] - 1)', 'left = max(1, job["retries_left"])', "test_budgets.RetryBudget"),
 ("job: plafond de coût ignoré", "factory/bin/job", 'if job["cost_usd"] >= max_cost:', 'if False:', "test_budgets.Caps"),
 ("job: plafond de durée ignoré", "factory/bin/job", 'if minutes >= max_minutes:', 'if False:', "test_budgets.Caps"),
 ("job: non concluant relancé sans fin", "factory/bin/job", 'require(job["inconclusive"] < 1,', 'require(True,', "test_budgets.Inconclusive"),
 ("job: sortie non écrite", "factory/bin/job", 'job["exit"] = exit_kind or {', 'job["exit"] = None and {', "test_budgets.FiveExits test_budgets.RetryBudget"),
 ("gate: non concluant compté comme échec", "factory/bin/gate", 'verdict = "INCONCLUSIVE"', 'verdict = "FAIL"', "test_gate.Inconclusive"),
 ("job: demandes de fusion des autres comptées", "factory/bin/job", 'if not m["draft"] and m["author"] == operator()]', 'if not m["draft"]]', "test_admission.ReviewCapacity"),
 ("job: capacité de relecture ignorée", "factory/bin/job", 'if len(waiting) < limit:', 'if True:', "test_admission.ReviewCapacity"),
 ("job: brouillons comptés comme en attente", "factory/bin/job", 'if not m["draft"] and m["author"] == operator()]', 'if m["author"] == operator()]', "test_admission.ReviewCapacity"),
 ("forge: bloqueur fermé sans être fait accepté", "factory/bin/forge", 'return issue["state"] == "closed" and issue.get("state_reason") == "completed"', 'return issue["state"] == "closed"', "test_forge_contract test_admission.Blockers"),
 ("job: bloqueurs ignorés à la création", "factory/bin/job", 'if blockers:\n        die(f"issue #{number} is {blocked_note(blockers)}', 'if False:\n        die(f"issue #{number} is {blocked_note(blockers)}', "test_admission.Blockers"),
 ("gate: trailers ignorés", "factory/bin/gate", 'verdict = "PASS" if code == 0 and not protected and not untraced else "FAIL"', 'verdict = "PASS" if code == 0 and not protected else "FAIL"', "test_gate.Trailers"),
 ("gate: trailer d\'un autre job accepté", "factory/bin/gate", 'if "Factory-Job" in one and one["Factory-Job"] != job_id:', 'if False:', "test_gate.Trailers"),
 ("gate: agent script hors commit de fusion", "factory/bin/gate", 'if len(parents) < 2:', 'if False:', "test_gate.Trailers"),
 ("job: résumé non écrit dans la demande", "factory/bin/job", '    update_summary(job)\n    return job', '    return job', "test_traceability.Summary"),
 ("job: version sans empreinte de config", "factory/bin/job", 'return f"{version.strip()}+config.{digest}"', 'return f"{version.strip()}+config.000000000000"', "test_traceability.TrailersCommand"),
 ("gate: trace non écrite", "factory/bin/gate", 'f.write(json.dumps(trace) + "\\n")', 'pass', "test_gate.Trace"),
]


def main():
    survivors = []
    for name, rel, old, new, tests in MUTATIONS:
        path = ROOT / rel
        orig = path.read_text()
        if orig.count(old) != 1:
            print(f"### {name}: the text to mutate isn't in {rel} exactly once; update MUTATIONS")
            survivors.append(name)
            continue
        path.write_text(orig.replace(old, new))
        try:
            res = subprocess.run([sys.executable, "-B", "-m", "unittest", *tests.split()],
                                 cwd=TESTS, capture_output=True, text=True)
        finally:
            path.write_text(orig)
        caught = res.returncode != 0
        print(f"### {'caught' if caught else 'SURVIVED'}: {name}")
        for line in res.stderr.splitlines():
            if line.startswith(("FAIL:", "ERROR:", "Ran ", "FAILED", "OK")):
                print(line)
        print()
        if not caught:
            survivors.append(name)
    if survivors:
        print("Mutations not caught: " + "; ".join(survivors))
        sys.exit(1)
    print(f"All {len(MUTATIONS)} mutations caught.")


if __name__ == "__main__":
    main()
