#!/usr/bin/env bash
# The repo's checks. Exit 0 only when the branch is fit to review.
#
# The gate runs this script from the main checkout with the job's worktree as
# the working directory. Keep it fast, deterministic and non-interactive: no
# watch modes, no prompts, nothing that rewrites files.
#
# Modèle à adapter au projet cible (spec de référence, §7.1) : installation
# reproductible, types, lint, tests, build. `factory install` écrira cette
# version à partir de la découverte du dépôt (§11.2).
set -euo pipefail

echo "factory/checks.sh n'est pas encore configuré pour ce dépôt." >&2
echo "Remplace ce bloc par les commandes d'installation, de lint, de types, de tests et de build." >&2
exit 1
