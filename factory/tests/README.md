# Suite de vérification de la factory

Spec de référence, §7.2 : pour chaque contrôle, hook et reviewer, un cas qui doit être bloqué, un cas voisin qui doit passer, et le comportement attendu quand l'entrée n'est pas comprise.

## Lancer

```bash
python3 -B -m unittest discover -s factory/tests
```

Bibliothèque standard seulement, sans réseau. Chaque test copie les scripts testés dans un dossier temporaire (`factory/jobs/` n'est jamais touché) ; les cas du gate montent un dépôt `origin.git`, un checkout principal et le worktree du job. Les commandes de forge (`gh`, `forge`) sont remplacées dans le `PATH` par une doublure qui journalise ses arguments et échoue : un refus qui atteindrait la forge se voit dans ce journal.

Pour prouver que les tests savent échouer :

```bash
python3 -B factory/tests/mutations.py
```

Le script casse chaque contrôle à tour de rôle (une ligne réécrite), rejoue ses tests, restaure le fichier, et sort en 1 si une mutation survit. **Avant de retirer ou de modifier un contrôle, rejouer ses cas ici et dans `mutations.py`** (§7.2).

## Contrôles couverts

Propriétaire : le mainteneur du dépôt (`cisbeo`) tant que la factory est au palier 1 ; il valide toute modification de `factory/` (voir `AGENTS.md`).

| Contrôle | Fichier de tests | Bloqué | Voisin qui passe | Entrée incomprise | Condition de retrait |
| --- | --- | --- | --- | --- | --- |
| `job advance` refuse les transitions illégales | `test_job_transitions.py` | sauts d'étape (spec → merging, approve, review, gate), job terminal qui repart, spec → build sans `spec.md`, spec → merged sans demande de fusion fusionnée | spec → build avec `spec.md` : round 1 ouvert | étape cible inconnue (`banana`, vide, casse ou espace différents), étape enregistrée inconnue, job inexistant : refus, code 1, `job.json` inchangé, aucun appel à la forge | quand l'état des jobs n'est plus écrit par `factory/bin/job` (remplacé par un autre écrivain unique qui porte ses propres cas) |
| Gate : chemin protégé modifié → échec | `test_gate.py` (`ProtectedPaths`) | modification de `factory/config.json`, `AGENTS.md`, `factory/bin/gate` ; suppression d'`AGENTS.md` ; ajout sous `.claude/` ; variante de casse `docs/Agents.md` | changement ordinaire (`src/`, nouveau fichier sous `factory/`) : PASS | nom que git citerait (commence par `"`) : échec, fermé par défaut ; job inexistant, job sans round (code 2), worktree absent : jamais PASS | quand la protection des chemins passe dans une règle de branche de la forge vérifiée par la factory, avec cas équivalents |
| Gate : c'est la copie de la base de `checks.sh` qui s'exécute | `test_gate.py` (`BaseChecksRun`, `BaseChecksFail`) | branche qui réécrit `checks.sh` : échec, le journal montre la copie de base, la version de la branche ne tourne pas ; base en échec que la branche « répare » : échec | branche propre et base qui passe : PASS, journal de la copie de base | (couvert par les cas incompris du gate ci-dessus) | quand les contrôles s'exécutent hors du dépôt (CI imposée par la forge sur la configuration de la base) |
| Gate : trace d'exécution dans le dossier du job | `test_gate.py` (`Trace`) | — (une trace manquante fait échouer `Trace`) | PASS et FAIL, puis `--merge` : une ligne par exécution dans `factory/jobs/<job>/trace.jsonl` (commande du gate, commande et dossier de `checks.sh`, codes de retour, verdict, commit vérifié complet, round) | entrée refusée (job sans round) : aucune trace PASS | quand une trace équivalente est écrite par un composant commun à tous les contrôles |
| `job advance … build` : un seul job à la fois sur une surface sérialisée (`serial_surfaces`, défaut `migration`) | `test_serial_surfaces.py` | second job `migration` qui entre en build pendant qu'un autre est en revue | job `ui` en parallèle ; second job `migration` une fois le premier fusionné ; `serial_surfaces` vide | `serial_surfaces` qui n'est pas une liste de surfaces connues de `surface_reviewers` (chaîne, nombre, vide, `billing`, `null`) : refus, code 1, `job.json` inchangé | quand l'outil de migration du dépôt cible sérialise lui-même les changements de schéma, vérifié par `checks.sh` |
| Aucun reste du projet d'origine dans `factory/` et `.claude/` | `test_repo_hygiene.py` | nom du projet d'origine ou de sa pile (ORM, base, hébergeur) hors `CREDITS.md` | le même nom dans un `CREDITS.md` | fichier qui n'est pas du texte UTF-8 : signalé, pas ignoré | quand la factory n'a plus de code copié d'un autre projet |
| `job` : budget de reprise (`retry_budget`), jamais rechargé | `test_budgets.py` (`RetryBudget`) | échec qui dépense la dernière unité : `build` refusé, `needs-human` avec `## Question` et sortie `budget` ; retour humain : budget toujours à 0, l'échec suivant repart vers un humain | gate FAIL ou revues CHANGES avec du budget : round suivant, une unité de moins ; gate PASS : rien de dépensé | `retry_budget` non entier positif (`"3"`, 0, -1, 1.5, `true`, `null`), `retries_left` absent de `job.json` : refus, `job.json` inchangé | quand le budget est porté par un autre écrivain d'état qui reprend ces cas |
| `job` : plafonds de coût et de durée vérifiés avant chaque étape | `test_budgets.py` (`Caps`) | coût ≥ `max_cost_usd` ou temps actif ≥ `max_duration_minutes` : arrêt, `needs-human`, sortie `budget` ou `timeout`, raison dans `decision.md` et sur la forge ; `job feedback` refusé tant que le plafond est atteint | sous les deux plafonds : l'étape démarre ; temps d'attente d'un humain non compté | plafond non nombre positif, horodatage `running_since` illisible : refus, aucun appel à la forge | quand la forge ou l'hôte imposent ces plafonds et que la factory le vérifie |
| `job` + `gate` : verdict « non concluant » | `test_budgets.py` (`Inconclusive`), `test_gate.py` (`Inconclusive`) | deuxième INCONCLUSIVE dans un round : relance refusée, `build` refusé, `needs-human` (sortie `human`) ; changement protégé : FAIL même si les contrôles sont non concluants | premier INCONCLUSIVE : le gate est relancé une fois sans dépenser le budget ; exit 75, 126, 127 de `checks.sh` : INCONCLUSIVE (code 3) ; autres codes non nuls : FAIL | verdict inconnu dans `checks.md` (`MAYBE`, casse différente, vide) : toute transition refusée | quand le gate distingue lui-même les causes d'indisponibilité |
| `job` : cinq sorties écrites | `test_budgets.py` (`FiveExits`) | — | fusion → `success`, rejet → `failure`, builder bloqué ou question à l'auteur → `human`, budget → `budget`, durée → `timeout` ; job en cours : pas de sortie | sortie enregistrée inconnue : refus | jamais : c'est l'exigence §6 |
| Admission : bloqueurs fusionnés (`forge blockers`, `job create`, `job queue`) | `test_admission.py` (`Blockers`), `test_forge_contract.py` | bloqueur ouvert, ou fermé « not planned » / « duplicate » : `job create` refusé, ligne `blocked` avec « (not merged) » | bloqueur fermé comme terminé (`completed`) : ligne `new`, job créé | relation native illisible (403) : refus, aucun job | quand la forge refuse elle-même de démarrer un ticket bloqué |
| Admission : demandes de fusion en attente d'un humain (`max_waiting_for_human`, défaut 3) | `test_admission.py` (`ReviewCapacity`) | 3 demandes ouvertes hors brouillon : `job create` refusé, ligne `hold` qui donne le compte, la limite et les numéros ; limite 1 depuis la config | brouillons non comptés ; un job déjà lancé reprend (`resume`) à la limite | limite non entier positif (`"3"`, 0, -1, 1.5, `true`, `null`), `forge mrs` en erreur : `create` et `queue` refusent, aucun job | quand le relecteur fixe la limite ailleurs et que la factory la lit |
| `route` choisit les reviewers par risque et surfaces | `test_route.py` | intake non ACCEPT, risque inconnu (`trivial`), surface inconnue (`billing`) : refus, `agents` reste vide (donc `job advance … spec` reste refusé) | risque faible → un reviewer ; moyen et élevé → `spec` + `standards` ; surfaces `ui`, `security` ajoutent leurs angles ; la table suit `config.json` | `RISK` absent, `RISK: LOW` (casse), `intake.md` absent, job inexistant : refus, code 1 | quand le routage est porté par un autre script qui reprend ces cas (dont les exclusions du risque faible, §7.4) |

## Non couvert pour l'instant

- `gate --hook` (hook SubagentStop du builder) et les reviewers : à ajouter par les tickets qui les reprennent.
- Les transitions qui appellent la forge sont couvertes en partie (needs-human, merged, reject, create, queue) par `test_budgets.py` et `test_admission.py`, avec le vrai `factory/bin/forge` devant le faux `gh` (`FactoryCase.use_fake_forge`) ; intake → spec (worktree) et `job merge` restent à couvrir.
- La copie « de la base » est celle du checkout principal, pas `origin/<base>` : un checkout principal modifié localement fait foi.

Tout ticket qui ajoute un contrôle ajoute ici sa ligne, ses cas, et une mutation dans `mutations.py`.
