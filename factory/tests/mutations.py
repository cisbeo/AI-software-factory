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
 ("gate: chemins protégés ignorés", "factory/bin/gate", 'verdict = "PASS" if code == 0 and not protected and not untraced and not oversized else "FAIL"', 'verdict = "PASS" if code == 0 and not untraced and not oversized else "FAIL"', "test_gate.ProtectedPaths"),
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
 ("gate: trailers ignorés", "factory/bin/gate", 'verdict = "PASS" if code == 0 and not protected and not untraced and not oversized else "FAIL"', 'verdict = "PASS" if code == 0 and not protected and not oversized else "FAIL"', "test_gate.Trailers"),
 ("gate: trailer d\'un autre job accepté", "factory/bin/gate", 'if "Factory-Job" in one and one["Factory-Job"] != job_id:', 'if False:', "test_gate.Trailers"),
 ("gate: agent script hors commit de fusion", "factory/bin/gate", 'if len(parents) < 2:', 'if False:', "test_gate.Trailers"),
 ("job: résumé non écrit dans la demande", "factory/bin/job", '    update_summary(job)\n    return job', '    return job', "test_traceability.Summary"),
 ("job: version sans empreinte de config", "factory/bin/job", 'return f"{version.strip()}+config.{digest}"', 'return f"{version.strip()}+config.000000000000"', "test_traceability.TrailersCommand"),
 ("gate: taille de fichier ignorée", "factory/bin/gate", 'verdict = "PASS" if code == 0 and not protected and not untraced and not oversized else "FAIL"', 'verdict = "PASS" if code == 0 and not protected and not untraced else "FAIL"', "test_gate.FileSize"),
 ("gate: limite de taille illisible acceptée", "factory/bin/gate", 'if type(value) is not int or value < 1:', 'if False:', "test_gate.FileSize"),
 ("gate: dernière ligne sans saut non comptée", "factory/bin/gate", '+ (1 if data and not data.endswith(b"\\n") else 0)', '+ 0', "test_gate.FileSize"),
 ("job: commit non passé au gate approuvé", "factory/bin/job", 'require(gated and all(h == gated for h in heads),', 'require(True,', "test_gate_twice.FirstGate"),
 ("job: commit non revu synchronisé et fusionné", "factory/bin/job", 'if not gated or late is not None:', 'if False:', "test_gate_twice.SecondGate"),
 ("job: merge-checks.md non vérifié", "factory/bin/job", 'if gated_commit(job, "merge-checks") != head:', 'if False:', "test_gate_twice.SecondGate"),
 ("job: verdict d'une tentative antérieure réutilisé", "factory/bin/job", 'merge_checks.unlink(missing_ok=True)', 'pass', "test_gate_twice.SecondGate"),
 ("job: second gate non relancé après non concluant", "factory/bin/job", 'if gate.returncode != 3:\n            break', 'break', "test_gate_twice.SecondGateInconclusive"),
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
 ("audit: action de workflow non épinglée acceptée", "factory/bin/audit", 'return bool(ACTION_AT_SHA.match(value))', 'return True', "test_securite_audit.WorkflowPins"),
 ("audit: règle de refus manquante acceptée", "factory/bin/audit", 'if rule not in deny:', 'if False:', "test_securite_audit.SettingsAudit"),
 ('installer: --dry-run écrit quand même', 'factory/bin/installer', 'if args.dry_run:\n        say("INSTALL: OK (à blanc', 'if False:\n        say("INSTALL: OK (à blanc', 'test_install.DryRun test_install.Overwrite.test_dry_run_asks_no_consent'),
 ('installer: doctor sauté', 'factory/bin/installer', '    run_doctor(target, early', '    (lambda *a: None)(target, early', 'test_install.DryRun'),
 ('installer: fichier existant écrasé sans accord', 'factory/bin/installer', 'if not (it.state == "create" or (it.state == "conflict" and it.consent)):\n            continue', 'if it.state not in ("create", "conflict"):\n            continue', 'test_install.Overwrite'),
 ("installer: réponse d'accord incomprise prise pour oui", 'factory/bin/installer', 'it.consent = (line or "").strip().lower() in ("o", "oui")', 'it.consent = bool((line or "").strip())', 'test_install.Overwrite'),
 ('installer: lignes .gitignore en double', 'factory/bin/installer', 'missing = [l for l in GITIGNORE_LINES if l not in present]', 'missing = list(GITIGNORE_LINES)', 'test_install.Replay'),
 ('installer: label existant recréé', 'factory/bin/installer', '"description": LABEL_TEXT.get(key, ""), "exists": name in present})', '"description": LABEL_TEXT.get(key, ""), "exists": False})', 'test_install.Replay'),
 ("installer: composant de l'autre forge posé", 'factory/bin/installer', 'items.append(Item(".github/workflows/factory-checks.yml", workflow_text(answers).encode()))', 'items += [Item(".github/workflows/factory-checks.yml", workflow_text(answers).encode()), Item(".gitlab-ci.yml", b"")]', 'test_install.Install'),
 ('installer: GitLab installé sans adaptateur', 'factory/bin/installer', 'if answers.get("forge") == "gitlab":', 'if False:', 'test_install.SurveyBlocks test_install.Discovery'),
 ('installer: checks.sh sans les commandes relevées', 'factory/bin/installer', 'lines += [f"echo {quote_sh(f\'== {kind} : {cmds[kind]}\')} >&2", cmds[kind], ""]', 'lines += [f"echo {quote_sh(f\'== {kind} : {cmds[kind]}\')} >&2", ""]', 'test_install.Install'),
 ('installer: source non épinglée acceptée', 'factory/bin/installer', 'if dirty.returncode != 0 or dirty.stdout.strip():', 'if False:', 'test_install.Install'),
 ('installer: action externe non épinglée', 'factory/bin/installer', '"commit": "3d3c42e5aac5ba805825da76410c181273ba90b1"', '"commit": "v7"', 'test_install.Install'),
 ('installer: lien symbolique suivi', 'factory/bin/installer', 'if real != target / rel or path.is_symlink():', 'if False:', 'test_install.Install'),
 ('installer: secrets suivis ignorés', 'factory/bin/installer', 'facts["secrets"] = [f for f in files', 'facts["secrets"] = [f for f in []', 'test_install.SurveyBlocks'),
 ('installer: automatisation par commentaire ignorée', 'factory/bin/installer', 'if text is not None and COMMENT_EVENTS.search(text):', 'if False:', 'test_install.SurveyBlocks'),
 ('installer: dépôt existant accepté', 'factory/bin/installer', 'return facts["commits"] <= MAX_NEW_COMMITS and len(files) <= MAX_NEW_FILES, len(files)', 'return True, len(files)', 'test_install.SurveyBlocks'),
 ('installer: aucune commande de test acceptée', 'factory/bin/installer', 'if "test" not in cmds:', 'if False:', 'test_install.SurveyBlocks'),
 ('installer: relevé illisible ignoré', 'factory/bin/installer', 'blocking += facts["unreadable"]', 'pass', 'test_install.SurveyBlocks'),
 ('installer: valeur détectée non proposée', 'factory/bin/installer', 'value = line.strip() or default', 'value = line.strip()', 'test_install.Discovery'),
 ('installer: fichier de réponses incompris accepté', 'factory/bin/installer', '    raise ValueError("une clé connue")', '    return text', 'test_install.Discovery'),
 ('installer: fichier modifié retiré à la désinstallation', 'factory/bin/installer', 'if sha256_bytes(path.read_bytes()) != f["sha256"]:', 'if False:', 'test_install.Uninstall'),
 ('installer: journal hors du dépôt accepté', 'factory/bin/installer', 'if not isinstance(f, dict) or safe_rel(f.get("path")) is None or f["path"] in seen:', 'if not isinstance(f, dict) or f["path"] in seen:', 'test_install.Uninstall'),
 ('installer: label préexistant retiré', 'factory/bin/installer', 'labels = [l for l in journal["labels"] if l["created"] and l["name"] in (present or set())]', 'labels = [l for l in journal["labels"] if l["name"] in (present or set())]', 'test_install.Uninstall'),
 ('installer: fichier remplacé non restauré', 'factory/bin/installer', 'path.write_bytes(backup.read_bytes())', 'path.unlink()', 'test_install.Uninstall'),
 ('installer: désinstallation à blanc qui retire', 'factory/bin/installer', 'if args.dry_run:\n        say("UNINSTALL: OK', 'if False:\n        say("UNINSTALL: OK', 'test_install.Uninstall'),
 ('forge: label existant recréé sans erreur', 'factory/bin/forge', 'if e.status == 422 and "already_exists" in str(e):', 'if False:', 'test_forge_contract'),
 ('doctor: --base ignoré', 'factory/bin/doctor', 'config.get("base_branch") if args.base is None else args.base', 'config.get("base_branch")', 'test_doctor.BaseBranch'),
 ('forge: ticket fermé comme fait', 'factory/bin/forge', '{"state": "closed", "state_reason": "not_planned"}', '{"state": "closed", "state_reason": "completed"}', 'test_forge_contract'),
 ('installer: installation déclarée réussie sans verify', 'factory/bin/installer', 'say("INSTALL: POSÉE — pas encore vérifiée")', 'say("INSTALL: OK")', 'test_install.Install.test_install_is_not_declared_successful_before_verify'),
 ('forge: demande de fusion fermée comme ticket', 'factory/bin/forge', 'if "pull_request" in self.issue(number):', 'if False:', 'test_forge_contract'),
 ('verify: configuration Claude étrangère acceptée', 'factory/bin/verify', '    if extra:\n        fail(f"configuration Claude', '    if False:\n        fail(f"configuration Claude', 'test_verify.Preconditions.test_claude_configuration_beyond_the_install_is_refused'),
 ('verify: plafonds illisibles acceptés', 'factory/bin/verify', '        if not num(config.get(key)):', '        if False:', 'test_verify.Preconditions.test_caps_the_sessions_cannot_read_are_refused'),
 ('verify: auto_merge autre que never accepté', 'factory/bin/verify', 'if config.get("auto_merge", "never") != "never":', 'if False:', 'test_verify.Preconditions.test_auto_merge_other_than_never_is_refused'),
 ('verify: composant modifié accepté', 'factory/bin/verify', 'if not path.is_file() or path.is_symlink() or path.read_bytes() != it.data:', 'if False:', 'test_verify.Preconditions.test_a_component_changed_since_install_is_refused'),
 ('verify: installation hors de la base acceptée', 'factory/bin/verify', 'if shown.returncode != 0 or shown.stdout != it.data:', 'if False:', 'test_verify.Preconditions.test_an_install_not_merged_into_the_base_branch_is_refused'),
 ('verify: suite de vérification en échec ignorée', 'factory/bin/verify', 'if suite.returncode != 0:', 'if False:', 'test_verify.SuiteFails'),
 ('verify: piège mal traité accepté', 'factory/bin/verify', 'if job["stage"] != want:', 'if False:', 'test_verify.Failures.test_a_trap_that_ends_in_the_wrong_waiting_stage_fails_verify'),
 ('verify: piège laissé construire', 'factory/bin/verify', 'if allowed and job and job["stage"] not in allowed:', 'if False:', 'test_verify.Failures.test_a_trap_that_intake_accepts_fails_verify_and_is_cleaned_up'),
 ('verify: pipeline incomplet accepté', 'factory/bin/verify', 'if job["stage"] != "needs-human" or first != "APPROVE" or not job["pr"]:', 'if False:', 'test_verify.Failures.test_a_dummy_ticket_that_stops_short_of_approval_fails_verify'),
 ('verify: reprise sans progrès acceptée', 'factory/bin/verify', 'if after == before:', 'if False:', 'test_verify.Failures.test_a_resume_that_does_not_move_the_job_fails_verify'),
 ("verify: interruption qui n'arrête pas la session", 'factory/bin/verify', 'os.killpg(proc.pid, sig)', 'pass', 'test_verify.Verify.test_an_interruption_mid_job_is_resumed_by_factory_run'),
 ('verify: job en attente non terminé', 'factory/bin/verify', 'if job and job["stage"] in WAITING:', 'if False:', 'test_verify.Verify.test_the_dummy_ticket_crosses_the_pipeline_and_its_merge_request_is_closed_unmerged'),
 ('verify: tickets laissés ouverts', 'factory/bin/verify', 'self.try_forge(left, "ticket", "close", n)', 'pass', 'test_verify.Verify.test_one_trap_is_rejected_and_the_other_waits_for_information'),
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
