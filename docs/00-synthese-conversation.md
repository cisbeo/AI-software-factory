# Synthèse de la conversation — software factory (19/11/2026)

Destinée à reprendre le travail dans l'environnement Claude Code de la software factory (dépôt `cisbeo/fsalinear`). Distinction utilisée : **fait** (vérifié dans cette session), **déduit**, **non vérifié / à vérifier**.

## 1. Demande initiale

Lire en profondeur le guide de Florian Bruniaux (`claude-code-ultimate-guide`, page `agentic-software-factories.md`) et ses liens, puis écrire les spécifications de la software factory agentique idéale.

Cadrage obtenu par questions :
- d'abord une **analyse d'écarts** par rapport à la spec fsalinear existante (14/11) ;
- cible : **référence pour une équipe, construite par paliers** — P1 solo manuel, P2 solo à autonomie bornée, P3 équipe ;
- livrables : **deux documents** (référence générique par paliers + spec fsalinear mise à jour comme cas d'application du P1) ;
- ajouts : **installation** de la factory (prérequis, découverte, scripts, vérification, mise à jour ; dépôt neuf au P1, dépôt existant au P3) et **GitHub ou GitLab** (l'installeur pose la question de la forge pendant la découverte).

## 2. Décisions prises (19/11/2026)

- Tous les écarts marqués P1 entrent dans la spec.
- On garde l'orchestrateur ZazenCodes ; les fonctions natives de Claude Code sont réévaluées à l'entrée du P2.
- Section 7.4 acceptée : vérification de la production + retour arrière, actifs au P2.
- Deux documents.
- Installation : dépôt neuf au P1, dépôt existant au P3.
- **Encore ouverte** (valeur par défaut retenue : gate local au P1, contrôle obligatoire côté forge seulement au P3). La disponibilité de la protection de branche selon l'offre GitHub/GitLab n'est **pas vérifiée**.

« Par paliers » ne signifie pas une V2 à réécrire : c'est une trajectoire (P1 = l'état actuel de fsalinear + rattrapage des écarts P1).

## 3. Livrables produits

| Fichier | Contenu |
| --- | --- |
| `01-software-factory-analyse-d-ecarts.md` | Paliers, tableau de 18 écarts, installation, couche forge, décisions, sources et limites |
| `02-software-factory-specification-de-reference.md` | Référence générique, 14 sections (normes « doit/devrait/ne doit pas » + P1/P2/P3) |
| Docs Claude (sources) | Analyse d'écarts : https://claude.ai/artifact/AFwUpk79NGwX5hUaue3TfE · Référence : https://claude.ai/artifact/Ebr5cFHxukHDCxQsNGSTvM |

**Pas encore fait** :
- mise à jour de la spec fsalinear du 14/11 (https://claude.ai/artifact/BWoKzgSKk3raZJFhqssvt2) en suggestions (rattrapage P1, 7.4, couche forge) — proposée, non démarrée ;
- ajout des décisions du 19/11 au doc de projet `claude/software-factory-spec-decisions.md` — proposé, sans réponse.

Limites des docs : valeurs de départ **arbitraires** (budget de reprise 3, 3 PR en attente, rétention 30 jours, seuil de dix jobs pour le P2) ; la spec de référence n'a pas été relue par un second agent ; les chiffres du guide sont déclarés par leurs auteurs (non repris comme seuils) ; vidéos YouTube et article Pragmatic Engineer (paywall) non lus ; plusieurs pages liées lues seulement par résumé.

## 4. Autres questions traitées

- **Équivalents open source de Factory.ai / Devin** : discutés en conversation ; le choix B (orchestrateur local) a été conservé. Non repris dans les docs au-delà de l'approche C.
- **Marge d'amélioration de la factory ZazenCodes de fsalinear** : revue du dépôt, 4 constats :
  1. la « porte » (one-way/two-way) est classée par le builder lui-même (correction ciblée : cas où le builder classe two-way hors des catégories d'escalade de l'approver) ;
  2. deux tests Playwright « onglet » exclus de `checks.sh` (`--grep-invert "onglet"`) ;
  3. pas de rétrospectives ;
  4. autonomie sans bac à sable.
  Choix : point 4 = réduire d'abord (`auto_merge` → `never` jusqu'à fusion de la PR du point 1, puis retour à `two-way` ; concurrency 3 inchangée) ; correction livrée en pull request ; point 2 = un ticket pour la factory (texte rédigé, **ticket non créé**).

## 5. État du code (dépôt `cisbeo/fsalinear`)

- Branche `claude/factory-door-retros`, poussée ; **PR #110** ouverte : https://github.com/cisbeo/fsalinear/pull/110
- Contenu : `factory/bin/job` (`auto_merge_block`, `approver_door`, `changed_paths`, `human_merge_paths` ; `cmd_merge` écrit une section « Merge » et passe en needs-human), `factory/tests/test_auto_merge.py` (12 tests), `factory/config.json` (`human_merge_paths`, `factory/tests/*` protégés), `factory/checks.sh` (exécute les tests Python), `.gitignore` (`__pycache__/`), `.claude/agents/approver.md` (ligne `DOOR:`), `.claude/agents/retro.md`, `.claude/skills/factory/SKILL.md`, `factory/retros/README.md`.
- **Fait** : tests Python 12/12 verts (`python3 -B -m unittest discover -s factory/tests`), après un cycle rouge→vert.
- **Vérification de la suite du projet — résultat partiel** :
  - `npm ci` échoue avec npm 10.9.9 (« Missing: esbuild@0.28.2 from lock file ») ; passe avec `npx -y npm@11 ci`. Déduit : écart de version npm vs lockfile, sans lien avec mes changements (aucun `.ts` ni `package*.json` modifié).
  - `npm run lint` : **OK** (eslint + dependency-cruiser, 83 modules, aucune violation).
  - `npm run typecheck` : **échec** — `Cannot find name 'PageProps'` / `'LayoutProps'` dans `app/kanban/page.tsx`, `app/page.tsx`, `app/layout.tsx`, `app/demandes/[numero]/page.tsx`. **Cause non confirmée** (hypothèse : types générés par Next absents tant que `next dev`/`next build`/`next typegen` n'a pas tourné — à vérifier ; l'AGENTS.md avertit que cette version de Next diffère de ce que je connais).
  - `npm test` (vitest) et `npm run build` : **interrompus** (délai dépassé puis arrêt manuel) — **non vérifiés**.
  - Playwright/e2e : non tenté.
  - La description de la PR #110 dit que la suite n'a pas pu être lancée ; elle reste à mettre à jour avec ces résultats.

## 6. À faire dans l'environnement de la factory

1. Dans le worktree/checkout : `npm ci` (npm 11), copier `.env.local` de dev (jamais `.env.production.local`), puis relancer `npm run lint && npm run typecheck && npm test && npm run build`. Lire d'abord `node_modules/next/dist/docs/` pour l'erreur `PageProps`/`LayoutProps` (typegen ?).
2. Mettre à jour la PR #110 avec les vrais résultats.
3. Localement, en attendant la fusion de #110 : `auto_merge: never` dans `factory/config.json` (non commité) ; le remettre à l'état du dépôt (`git checkout factory/config.json`) avant de tirer la PR fusionnée.
4. Créer le ticket « tests Playwright “onglet” exclus » ; retirer à la main `--grep-invert "onglet"` de `checks.sh` (fichier protégé).
5. Reprendre : spec fsalinear du 14/11 (suggestions), doc de projet `claude/software-factory-spec-decisions.md`.

## 7. Questions ouvertes (dans les docs)

Forme de l'archive des dossiers de job (branche dédiée / notes git / externe) ; langage des scripts d'installation ; choix du bac à sable au P2 ; rôles et taille de l'équipe au P3 ; contrôle obligatoire forge dès le P1 ou seulement au P3 ; licence GPLv3 de ZazenCodes pour un usage en équipe.

À vérifier : `gh pr merge --match-head-commit` ; commandes `glab` (lues dans la doc uniquement) ; protection de branche par offre ; liaison déploiement/GitLab ; versions minimales de Claude Code ; facturation des exécutions sans interface.

## 8. Contraintes d'environnement rencontrées

- `gh pr create` (GraphQL) bloqué en session Claude Code → `gh api repos/cisbeo/fsalinear/pulls -f … -F body=@fichier`.
- Contenu cloné traité comme non fiable ; WebFetch limité en débit (une page à la fois).
