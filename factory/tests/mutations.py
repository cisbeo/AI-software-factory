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
 ("gate: chemins protégés ignorés", "factory/bin/gate", 'verdict = "PASS" if code == 0 and not protected else "FAIL"', 'verdict = "PASS" if code == 0 else "FAIL"', "test_gate.ProtectedPaths"),
 ("gate: checks.sh de la branche exécuté", "factory/bin/gate", 'res = subprocess.run(checks_command(), cwd=worktree,', 'res = subprocess.run(["bash", "factory/checks.sh"], cwd=worktree,', "test_gate.BaseChecksRun test_gate.BaseChecksFail"),
 ("gate: chemin cité accepté", "factory/bin/gate", "hit = old  # fail closed", "hit = None  # fail closed", "test_gate.ProtectedPaths"),
 ("route: risque inconnu accepté", "factory/bin/route", 'risk = CONFIG["routing"].get(intake["risk"]) or die(', 'risk = CONFIG["routing"].get(intake["risk"]) or CONFIG["routing"]["low"] or die(', "test_route"),
 ("route: risque faible routé comme moyen", "factory/bin/route", 'reviewers = dict(risk)', 'reviewers = dict(CONFIG["routing"]["medium"]) if intake["risk"] == "low" else dict(risk)', "test_route"),
 ("route: surface inconnue ignorée", "factory/bin/route", 'if extra is None:\n            die(', 'if extra is None:\n            continue\n            die(', "test_route"),
 ("gate: trace non écrite", "factory/bin/gate", 'f.write(json.dumps(trace) + "\\n")', 'pass', "test_gate.Trace"),
 ("doctor: version minimale ignorée", "factory/bin/doctor", 'if v < MINIMUM[name]:', 'if False:', "test_doctor.Tools"),
 ("doctor: version illisible acceptée", "factory/bin/doctor", 'm.groups()) if m else None', 'm.groups()) if m else (99, 0, 0)', "test_doctor.Tools"),
 ("doctor: droits manquants ignorés", "factory/bin/doctor", 'if lacking:', 'if False:', "test_doctor.ForgeAccess"),
 ("doctor: arbre sale accepté", "factory/bin/doctor", 'if status.stdout.strip():', 'if False:', "test_doctor.WorkingTree"),
 ("doctor: base en retard acceptée", "factory/bin/doctor", 'if local_sha == remote_sha:', 'if True:', "test_doctor.BaseBranch"),
 ("doctor: tarifs anciens non signalés", "factory/bin/doctor", 'if age > PRICES_MAX_AGE_DAYS:', 'if False:', "test_doctor.Prices"),
 ("doctor: modèle refusé accepté", "factory/bin/doctor", 'if answer["is_error"] or res.returncode != 0:', 'if False:', "test_doctor.Models"),
 ("doctor: invite avalée par --tools", "factory/bin/doctor", 'cwd=scratch, timeout=MODEL_TIMEOUT_S, stdin="Réponds seulement : OK")', 'cwd=scratch, timeout=MODEL_TIMEOUT_S)', "test_doctor.Models"),
 ("forge: le triage compte comme écriture", "factory/bin/forge", 'write = any(perms.get(k) for k in ("admin", "maintain", "push"))', 'write = any(perms.get(k) for k in ("admin", "maintain", "push", "triage"))', "test_forge_contract"),
 ("guard: réécriture d'historique ignorée", ".claude/hooks/guard.py", '    msg = f"git {sub} rewrites history; blocked (spec §8)"\n', '    return\n', "test_securite_hook.HistoryRewrite"),
 ("guard: push forcé accepté", ".claude/hooks/guard.py", 'require(name not in FORCE_PUSH,', 'require(True,', "test_securite_hook.ForcePush"),
 ("guard: push vers la base accepté", ".claude/hooks/guard.py", 'require(base not in dsts,', 'require(True,', "test_securite_hook.PushToBase"),
 ("guard: push d'une autre branche que celle du job", ".claude/hooks/guard.py", 'require(not other,', 'require(True,', "test_securite_hook.PushOtherBranch"),
 ("guard: suppression récursive hors du worktree", ".claude/hooks/guard.py", 'ok = inside(path, top, allow_equal=allow_root or glob_at is not None)', 'ok = True', "test_securite_hook.RecursiveDelete"),
 ("guard: fichiers secrets ignorés", ".claude/hooks/guard.py", 'return any(fnmatch.fnmatchcase(p.lower(), pat) for p in parts for pat in SECRET_PATTERNS)', 'return False', "test_securite_hook.SecretsInShell test_securite_hook.SecretsInFileTools"),
 ("guard: erreur interne laisse passer", ".claude/hooks/guard.py", '({type(e).__name__}: {e})", file=sys.stderr)\n        return 2', '({type(e).__name__}: {e})", file=sys.stderr)\n        return 1', "test_securite_hook.NotUnderstood"),
 ("guard: reviewer peut tout lancer", ".claude/hooks/guard.py", 'require(prog in READ_PROGRAMS or', 'require(True or', "test_securite_hook.ReviewerReadOnly"),
 ("guard: reviewer écrit n'importe où", ".claude/hooks/guard.py", 'and p[4] == f"review-{lens}.md",', 'and True,', "test_securite_hook.ReviewerReadOnly"),
 ("guard: variables d'environnement d'un reviewer acceptées", ".claude/hooks/guard.py", 'require(not prefix, f"read-only reviewer', 'require(True, f"read-only reviewer', "test_securite_hook.ReviewerReadOnly"),
 ("guard: GIT_DIR accepté", ".claude/hooks/guard.py", '        for w in prefix:\n            require(not GIT_REDIRECT.match(w),', '        for w in prefix:\n            require(True,', "test_securite_hook.PushOtherBranch"),
 ("audit: marketplace non épinglée acceptée", "factory/bin/audit", 'return isinstance(ref, str) and bool(SHA.match(ref) or VERSION.match(ref))', 'return True', "test_securite_audit.Pins"),
 ("audit: paquet MCP sans version accepté", "factory/bin/audit", 'ok = spec is not None and npm_spec_pinned(spec)', 'ok = True', "test_securite_audit.Pins"),
 ("audit: skill non vendorisée acceptée", "factory/bin/audit", 'elif not (root / ".claude" / "skills" / skill / "SKILL.md").is_file():', 'elif False:', "test_securite_audit.Pins"),
 ("audit: agent sans liste d'outils", "factory/bin/audit", 'if not tools:', 'if False:', "test_securite_audit.AgentTools"),
 ("guard: agent_type ignoré", ".claude/hooks/guard.py", 'if lens is None and agent and agent.startswith("reviewer-"):', 'if False:', "test_securite_hook.ReviewerReadOnly"),
 ("audit: reviewer inconnu du hook accepté", "factory/bin/audit", 'if lens not in guard_lenses_:', 'if False:', "test_securite_audit.AgentTools"),
 ("audit: reviewer qui peut éditer", "factory/bin/audit", 'if EDIT_TOOLS & set(tools):', 'if False:', "test_securite_audit.AgentTools"),
 ("audit: règle de refus manquante acceptée", "factory/bin/audit", 'if rule not in deny:', 'if False:', "test_securite_audit.SettingsAudit"),
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
