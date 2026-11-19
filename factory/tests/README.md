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
| `route` choisit les reviewers par risque et surfaces | `test_route.py` | intake non ACCEPT, risque inconnu (`trivial`), surface inconnue (`billing`) : refus, `agents` reste vide (donc `job advance … spec` reste refusé) | risque faible → un reviewer ; moyen et élevé → `spec` + `standards` ; surfaces `ui`, `security` ajoutent leurs angles ; la table suit `config.json` | `RISK` absent, `RISK: LOW` (casse), `intake.md` absent, job inexistant : refus, code 1 | quand le routage est porté par un autre script qui reprend ces cas (dont les exclusions du risque faible, §7.4) |
| `doctor` : prérequis (§11.1), arrêt au premier manque avec la correction | `test_doctor.py` | Claude Code, git ou python3 absent ou trop ancien ; CLI de la forge absente ou non authentifiée ; compte lecteur ou trieur (ne peut pas pousser ni fusionner) ; arbre modifié ou fichier non suivi ; base en retard, en avance, absente du distant, pas d'`origin` ; tarifs non datés ou datés du futur ; modèle refusé | dépôt prêt : `DOCTOR: OK`, rien d'écrit ; versions au minimum ; fichiers ignorés ; base à jour depuis une autre branche ; tarifs de 90 jours (91 : `warn` sans arrêt) ; chaque modèle de la config essayé une fois | version illisible, identité ou droits illisibles, réponse de modèle illisible, modèle qui n'est pas un nom, `prices_as_of` mal formé, `config.json` invalide, hors d'un dépôt git : échec, code 1, aucun modèle essayé si une vérification antérieure échoue | quand `factory install`/`verify` (#19, #20) portent ces vérifications avec des cas équivalents |
| `forge permissions` : droits du compte | `test_forge_contract.py` | lecteur : rien ; trieur : étiqueter seulement | écrivain : pousser, étiqueter, fusionner | droits absents de la réponse ou non booléens : échec fermé | quand un autre adaptateur porte le même contrat |

## Non couvert pour l'instant

- `gate --hook` (hook SubagentStop du builder) et les reviewers : à ajouter par les tickets qui les reprennent.
- Les transitions qui appellent la forge (intake → spec, needs-human, merged…) : leurs cas viendront avec la commande `forge` (issue #10), qui permettra une doublure plus fidèle.
- La copie « de la base » est celle du checkout principal, pas `origin/<base>` : un checkout principal modifié localement fait foi.

Tout ticket qui ajoute un contrôle ajoute ici sa ligne, ses cas, et une mutation dans `mutations.py`.
