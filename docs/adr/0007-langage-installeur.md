# 0007 — L'installeur en Python (bibliothèque standard) et shell

Date : 19/11/2026 · Statut : accepté (décision de l'issue #2)

L'installeur (`factory discover`, `install`, `uninstall`, puis `verify` et `upgrade`) est écrit en Python, bibliothèque standard seulement, avec du shell là où il suffit, comme les scripts existants de `factory/bin/`. Prérequis déjà exigés par `doctor` (python3 ≥ 3.9, git) ; rien à télécharger pour l'installer, donc rien à épingler en plus (spec §8, §11).

Conséquences : `factory/bin/factory` répartit les commandes ; `factory/bin/installer` lit les composants dans le commit de la factory (`git show`), jamais dans un brouillon ; les tests tournent hors réseau sur des dépôts git temporaires (`factory/tests/test_install.py`).
