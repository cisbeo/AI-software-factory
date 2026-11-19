# Software factory — analyse d'écarts

19/11/2026 · Cédric

La spec du 14/11 couvre deux des cinq questions de gouvernance du guide de Florian Bruniaux, en couvre deux en partie et laisse la cinquième sans réponse. Les manques les plus lourds sont l'isolation des agents, la traçabilité durable, la preuve que chaque contrôle s'exécute, et tout ce qui se passe après la fusion.

## Paliers

Tu vises une référence pour une équipe, en commençant par paliers. Le découpage et les preuves de passage ci-dessous sont ma proposition ; le guide ne fixe aucun seuil chiffré.

| Palier | Périmètre | Preuve pour y entrer |
| --- | --- | --- |
| P1. Solo, manuel | La V1 actuelle : tu lances, tu fusionnes tout | Aucune : c'est le point de départ |
| P2. Solo, autonomie bornée | Fusion automatique du risque faible, premier déclencheur, vérification de la production | Bac à sable en place ; chaque contrôle a son test ; retour arrière essayé à blanc ; dix jobs à risque faible fusionnés sans correction (seuil arbitraire de ta spec) |
| P3. Équipe | Plusieurs auteurs d'intention, CI bloquante, revue routée par risque, suite après fusion | Taux de défauts échappés mesuré sur P2 ; traçabilité par commit ; capacité de relecture nommée et limitée |

Règle tirée du guide : n'ajouter de l'autonomie ou du parallélisme qu'après avoir prouvé la vérification et la reprise au palier courant.

## Écarts

La colonne « Spec du 14/11 » décrit le texte actuel de ta spec, sans les suggestions en attente. « Palier » indique où je placerais le rattrapage.

| Exigence du guide | Spec du 14/11 | Ce qui manque | Palier |
| --- | --- | --- | --- |
| Q1. Une porte non-LLM bloque la fusion | Couvert en local : `checks.sh`, gate exécuté depuis le checkout principal, chemins protégés | Rien n'empêche une fusion hors factory : pas de contrôle obligatoire côté GitHub. C'est le « piège de la CI décorative » du guide | P1 accepté, P3 obligatoire |
| Q2. Arrêt après N échecs | Couvert : 3 tours puis `needs-human` avec une question | Pas de plafond de coût ni de durée par job ; pas dit si le compteur repart après ton retour (le guide veut un budget qui ne se recharge pas) | P1 |
| Q3. Traçabilité de chaque décision | Partiel : un fichier par étape, mais dans `factory/jobs/`, ignoré par git | Lien durable entre un commit et l'agent, la version du modèle, la version de la configuration et ton approbation ; raison du routage et verdicts que tu as renversés | P1 (trailers, résumé dans la PR), P3 (journal d'audit) |
| Q4. La spec reste la référence | Partiel : spec amont en issue GitHub, `spec.md` du job non versionné | Aucun mécanisme ne resynchronise spec et code après fusion. Le guide classe ce point comme problème ouvert | P2 |
| Q5. La vérification annoncée s'exécute vraiment | Un seul cas testé : une branche qui modifie `checks.sh` doit échouer | Pour chaque contrôle, hook et reviewer : un cas qui doit être bloqué, un cas voisin qui doit passer, et la trace qu'il a tourné | P1 |
| Vérificateur indépendant du créateur | Partiel : reviewers à contexte neuf, l'`approver` vérifie un critère | Verdict par critère d'acceptation et non par angle ; liste des critères qu'aucun test n'exerce ; mesure des faux acceptés ; même famille de modèles partout | P1 (verdict par critère), P3 (mesure, autre modèle) |
| Tests qui prouvent quelque chose | TDD demandé au `builder`, tests affaiblis surveillés par un reviewer | Contrôle mécanique : un test ajouté doit échouer avant le correctif et passer après (idée du « double checkout » relevée dans l'étude de Fusion) | P2 |
| Isolation des agents | Worktree par job ; aucun secret ni base de production accessibles | Un worktree n'isole ni les processus, ni le réseau, ni les identifiants. Pas de bac à sable, pas de règles `deny`, versions des skills et plugins non épinglées | P1 (deny, hooks, épinglage), P2 (bac à sable avant tout déclencheur) |
| Admission selon la capacité de relecture | `concurrency` 1 puis 3 | Limite liée à ce que tu peux relire : pas de nouveau job tant que N PR t'attendent | P1 |
| Évaluation de la factory elle-même | Indicateurs hebdomadaires, deux tickets pièges | Jeu de tickets de référence rejoué après tout changement de modèle, d'agent ou de script ; coût par ticket accepté | P2 |
| Amélioration continue | Couvert : retro, défaut transformé en contrôle | Preuve avant adoption d'un contrôle, propriétaire et condition de retrait | P1 |
| Architecture qui reste lisible | Modules profonds, dependency-cruiser au jalon 3 | Limite de taille de fichier ; interdiction de deux implémentations parallèles sans date de bascule | P1 |
| Après la fusion : déploiement et retour arrière | En suggestion non acceptée (section 7.4) : route de santé, `vercel rollback` | Accepter ou refuser cette suggestion ; observation par changement | P2 |
| Incidents | Absent | Agent qui propose sans exécuter ; lien entre un incident et un correctif durable | P3 |
| Métriques produit | Absent ; seul « défauts trouvés après fusion » s'en approche | Un signal d'usage nommé avant le travail et relu après, par l'auteur de l'intention ; taux de défauts échappés | P1 (un signal par spec), P3 |
| Fonctions natives de Claude Code | Orchestrateur maison (skill et scripts de ZazenCodes) | Pas un manque, un choix à trancher : `/goal`, `/autofix-pr` et les workflows dynamiques recouvrent une partie du pipeline | P2 |
| Équipe : rôles, multi-dépôt, CI sous charge | Hors périmètre déclaré | Répartition des responsabilités, identités d'agents signées, CI dimensionnée pour le volume des agents | P3 |

Déjà solide et à garder tel quel : le ticket traité comme donnée citée, l'`intake` sans shell, le label comme frontière de confiance, la machine à états écrite par un seul script, le routage des reviewers par risque.

## Installation

Exigence ajoutée le 19/11 : la spec doit prévoir l'installation de la factory. Aujourd'hui elle n'existe que comme guide manuel en dix étapes, écrit pour un dépôt neuf nommé `fsalinear`. Le découpage ci-dessous est ma proposition.

| Volet | Existant | Ce qui manque | Palier |
| --- | --- | --- | --- |
| Prérequis | Liste dans le guide, vérifiée à la main (Claude Code, Node.js, git, `gh`, Vercel) | Un script de diagnostic qui vérifie versions, authentifications et droits, et s'arrête avec la correction à faire | P1 |
| Découverte du dépôt cible | Absent : le guide suppose un dépôt créé pour l'occasion | Un relevé en lecture seule : pile, commandes de test et de build, CI, protection de branche, hooks et réglages Claude déjà présents, secrets exposés. Il produit un rapport d'aptitude et la liste de ce que l'installation changera | P1 pour un dépôt neuf, P3 pour un dépôt existant |
| Scripts d'installation | Prompt d'installation de ZazenCodes, puis modifications à la main (étape 8 du guide) | Installation rejouable sans effet en double, mode à blanc, versions épinglées par commit, aucun fichier écrasé sans accord, désinstallation | P1 |
| Vérification après installation | Un « contrôle de fin d'étape » manuel par étape | Un test de fumée : un ticket factice traverse le pipeline, et chaque contrôle prouve qu'il bloque (répond aussi à la question 5) | P1 |
| Mise à jour | Absent | Version de la factory inscrite dans le dépôt, migration de la configuration, rejeu du jeu de tickets de référence après mise à jour | P2 |

Point de sécurité tiré du guide : un installeur exécute du code et pose des hooks. Il doit donc être lisible, épinglé, et montrer ce qu'il va faire avant de le faire.

Décision du 19/11 : l'installation vise un dépôt neuf au palier 1 ; l'installation dans un dépôt existant est spécifiée pour le palier 3.

## Forge : GitHub ou GitLab

Exigence ajoutée le 19/11 : la factory fonctionne avec GitHub ou GitLab, et l'installeur pose la question pendant la découverte pour installer les bons composants. La spec du 14/11 est écrite pour GitHub seul : issues, labels, CLI `gh`, `gh pr merge`.

Ma proposition : une couche d'adaptation unique. Aucun script ni agent n'appelle `gh` ou `glab` directement ; ils passent par une commande `forge` qui a deux implémentations.

| Fonction | GitHub | GitLab | Point d'attention |
| --- | --- | --- | --- |
| Ligne de commande | `gh` | `glab` | Authentification vérifiée par le diagnostic des prérequis |
| File d'attente | Issues et label `factory` | Issues et label `factory` | Équivalent |
| Dépendances entre tickets | Relation « bloqué par » | Relation « bloque » réservée aux offres Premium et Ultimate ([documentation](https://docs.gitlab.com/user/work_items/linked_items/)) | Sur l'offre gratuite GitLab : convention écrite dans le ticket (« Bloqué par #n »), lue par l'adaptateur |
| Demande de fusion | Pull request | Merge request | Vocabulaire neutre dans la spec : « demande de fusion » |
| Fusion liée au commit vérifié | `gh pr merge --match-head-commit` (à vérifier) | `glab mr merge --sha` ([documentation](https://docs.gitlab.com/cli/mr/merge/)) | Même garantie des deux côtés |
| CI bloquante (palier 3) | GitHub Actions | GitLab CI | Un modèle de pipeline par forge ; protection de branche selon l'offre, à vérifier pour les deux |
| Fonctions natives de Claude Code | `/autofix-pr` et sessions cloud disponibles | Non : elles exigent GitHub ([documentation](https://code.claude.com/docs/en/claude-code-on-the-web#limitations)) | Sur GitLab, seul l'orchestrateur local fonctionne. Cela conforte le choix de garder ZazenCodes |
| Déploiement | Vercel relié au dépôt | Liaison Vercel à vérifier | Sans effet sur le pipeline, mais sur la section 7.4 |

**Questions posées par l'installeur pendant la découverte**

1. Quelle forge ? Proposition détectée depuis `git remote`, à confirmer.
2. Pour GitLab : gitlab.com ou instance auto-hébergée, et son adresse.
3. Quelle offre ? Elle décide du mécanisme de dépendances et de la protection de branche.

L'installeur pose ensuite l'adaptateur, les labels et le modèle de CI de la forge choisie, et rien de l'autre.

**Palier.** Proposition : l'interface `forge` et l'adaptateur GitHub au palier 1 ; l'adaptateur GitLab spécifié au palier 1 et construit au premier dépôt GitLab. Non testé : je n'ai vérifié les commandes `glab` que dans leur documentation.

## Décisions à prendre

Tranchées le 19/11/2026 :

- **Rattrapage P1** : tous les écarts marqués P1 entrent dans la spec.
- **Ossature** : on garde l'orchestrateur ZazenCodes ; le natif est réévalué au palier 2.
- **Section 7.4** : acceptée (vérification de la production et retour arrière automatique, actifs au palier 2).
- **Forme** : deux documents. Une référence générique par paliers pour une équipe, et la spec fsalinear mise à jour comme cas d'application du palier 1.
- **Installation** : dépôt neuf au palier 1, dépôt existant au palier 3.

Encore ouverte, avec ma proposition par défaut : rester sur le gate local au palier 1 et n'exiger un contrôle obligatoire côté GitHub qu'au palier 3. Disponibilité de la protection de branche selon l'offre à vérifier.

## Sources et limites

Lues le 19/11/2026.

- Guide principal, lu en entier : [Agentic software factories: Orientation map](https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/main/guide/workflows/agentic-software-factories.md)
- Pages liées du même dépôt, lues par résumé ou extrait : spec-first, plan-pipeline, dynamic-workflows, agent-teams, agent-harness, loop-graph-engineering, agent-evaluation, observability, security-hardening, team-metrics, agentic-tools, agent-harness-landscape (toutes sous `guide/` du dépôt `FlorianBruniaux/claude-code-ultimate-guide`)
- Évaluations du dépôt (`docs/resource-evaluations/`) : Fusion, CI d'Anthropic, factory d'OpenAI
- Sources externes : [Harness engineering (OpenAI)](https://openai.com/index/harness-engineering/), [Agentic coding is straining CI (Anthropic)](https://claude.com/blog/agentic-coding-is-straining-ci-heres-how-we-scaled-test-impact-analysis-at-anthropic), [documentation de /goal](https://code.claude.com/docs/en/goal), [Auto-fix pull requests](https://code.claude.com/docs/en/claude-code-on-the-web#auto-fix-pull-requests)
- Ta spec : [Software factory — spécification détaillée](https://claude.ai/artifact/BWoKzgSKk3raZJFhqssvt2)

**Non lu ou lu en partie**

- Les deux vidéos YouTube de Pavan Belagatti : transcriptions inaccessibles.
- [Inside OpenAI's agentic software factory](https://newsletter.pragmaticengineer.com/p/openai-software-factory) : coupé par le paywall après la section 3.
- Dépôt refute-or-promote, page commerciale de l'auteur, évaluation « harness engineering » du 11/02 : non lus.
- `third-party-tools.md`, `ai-traceability.md`, `methodologies.md`, glossaire : survolés (titres et quelques sections).

Les chiffres du guide (coûts, volumes d'OpenAI et d'Anthropic) sont déclarés par leurs auteurs, sans mesure indépendante ; je n'en ai repris aucun comme seuil.
