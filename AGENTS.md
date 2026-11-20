# AI-software-factory

Software factory agentique pour Claude Code : transforme des tickets en demandes de fusion vérifiées, sur GitHub ou GitLab, et gagne en autonomie par paliers (P1 solo manuel, P2 solo à autonomie bornée, P3 équipe).

Ce fichier est une table des matières. La référence fait foi.

## Documents

- [docs/02-specification-de-reference.md](docs/02-specification-de-reference.md) — la spécification (exigences « doit / devrait / ne doit pas », par palier).
- [docs/01-analyse-d-ecarts.md](docs/01-analyse-d-ecarts.md) — écarts entre la factory fsalinear du 14/11/2026 et la référence.
- [docs/00-synthese-conversation.md](docs/00-synthese-conversation.md) — contexte de départ et état au 19/11/2026.
- [GLOSSARY.md](GLOSSARY.md) — vocabulaire.
- [docs/adr/](docs/adr/) — décisions.

## Code

- `factory/bin/job` — seul écrivain de l'état des jobs (`factory/jobs/`, ignoré par git).
- `factory/bin/gate`, `factory/bin/route` — gate déterministe et routage des reviewers.
- `factory/checks.sh` — contrôles du dépôt cible ; modèle vide à configurer.
- `.claude/settings.json`, `.claude/hooks/guard.py` — règles de refus des secrets et hook PreToolUse qui bloque les commandes destructrices (§8).
- `factory/bin/factory` — point d'entrée : `doctor`, `discover`, `install`, `uninstall`, `verify`, `audit`. L'installeur (`factory/bin/installer`) pose la factory sur un dépôt neuf, d'après `factory/answers.json`, et tient son journal `factory/install-log.json`. `factory/bin/verify` est le test de fumée après installation (§11.4) : seul `VERIFY: OK` déclare l'installation réussie.
- `factory/bin/audit` — vérifie l'épinglage des skills, plugins et serveurs MCP, et les outils des agents.
- `factory/config.json` — politique : `auto_merge: never`, `concurrency: 1` (palier 1).
- `.claude/agents/`, `.claude/skills/factory/` — agents et orchestrateur.

État : amorce copiée depuis la factory de fsalinear (dérivée de ZazenCodes v2). Les exigences P1 de la référence ne sont pas encore implémentées ; elles sont suivies en issues.

## Règles

- Vocabulaire neutre vis-à-vis de la forge : « ticket », « demande de fusion ».
- Ne jamais lire ni écrire de fichier `.env*`.
- Toute modification de `factory/`, `.claude/`, `AGENTS.md` ou `CLAUDE.md` passe par un humain.
- Ne pas pousser sur `main` sans demande de fusion.
