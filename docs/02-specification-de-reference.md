# Software factory agentique — spécification de référence

19/11/2026 · Cédric

Cette factory transforme des tickets en demandes de fusion vérifiées, sur GitHub ou GitLab, et gagne en autonomie par paliers : chaque palier n'ouvre qu'après la preuve que la vérification du précédent tient. Elle vise une équipe, et commence par un usage solo.

## 1. Intention et périmètre

L'équipe décrit ce qu'elle veut construire ; la factory livre des demandes de fusion qu'on peut accepter en confiance, et dit ce qu'elles ont coûté. Les humains quittent l'exécution répétitive et gardent trois responsabilités : l'intention, les exceptions, les changements irréversibles.

Ce document est la référence générique. La [spécification fsalinear](https://claude.ai/artifact/BWoKzgSKk3raZJFhqssvt2) en est le cas d'application au palier 1.

**Objectifs**

- Transformer un ticket en demande de fusion vérifiée, sans intervention entre le lancement et la demande.
- Bloquer un défaut par le contrôle le moins cher capable de le voir, et prouver que ce contrôle s'exécute.
- Pouvoir reconstituer, pour tout commit, qui l'a produit, avec quel modèle, sous quelle configuration, et qui l'a approuvé.
- S'installer par script sur un dépôt GitHub ou GitLab, et se vérifier seule après installation.
- Mesurer la valeur livrée, pas seulement le débit.

**Non-objectifs**

- Remplacer la décision de ce qui vaut d'être construit.
- Corriger seule un incident de production.
- Fonctionner sur une autre forge que GitHub ou GitLab.
- Orchestrer plusieurs dépôts dans un même job.

**Ce qui serait un échec même si tout fonctionne**

- Les relecteurs relisent chaque ligne parce qu'ils ne font pas confiance aux contrôles.
- Le débit augmente et personne ne sait dire si le taux de défauts a bougé.
- Le code grossit plus vite que la capacité de quiconque à l'expliquer.
- Un contrôle figure dans la documentation et ne tourne pas.

**Vocabulaire.** Les exigences sont notées « doit », « devrait » ou « ne doit pas », suivies du palier où elles s'appliquent (P1, P2, P3). « Demande de fusion » désigne une pull request GitHub ou une merge request GitLab.

## 2. Approches envisagées et choix

Trois façons de bâtir la factory. La deuxième est retenue (décision du 19/11/2026).

| Approche | Principe | Avantage | Limite |
| --- | --- | --- | --- |
| A. Fonctions natives de Claude Code | `/goal`, `/autofix-pr`, workflows dynamiques, pipeline plan-validate-execute du guide | Moins de code maison ; c'est la voie que le guide de Florian Bruniaux recommande à petite échelle | Les sessions cloud et `/autofix-pr` exigent GitHub : GitLab est exclu. Pas d'état durable entre exécutions sans le construire |
| **B. Orchestrateur local sur fichiers** | Ossature ZazenCodes v2 : un orchestrateur, des scripts déterministes, l'état de chaque job sur disque | Fonctionne sur les deux forges ; reprise après interruption ; déjà spécifié pour fsalinear | Code à maintenir ; licence GPLv3 à réexaminer avant toute diffusion hors usage personnel |
| C. Plateforme fermée | Factory.ai, Devin ou équivalent | Gouvernance empaquetée | Aucun résultat mesuré par un tiers selon le guide ; dépendance à un éditeur ; hors de propos pour un usage solo |

Le choix B n'est pas définitif : l'approche A est réévaluée à l'entrée du palier 2, sur un même ticket traité des deux façons. Le guide penche pour A en précisant que ce jugement n'est pas mesuré.

## 3. Modèle opératoire

Une factory est d'abord une répartition de responsabilités. Chaque ligne nomme un propriétaire et la preuve qu'il doit pouvoir produire. Au palier 1, une seule personne tient tous les rôles humains.

| Responsabilité | Propriétaire | Preuve exigée |
| --- | --- | --- |
| Intention, périmètre, tolérance au risque | Auteur de l'intention (humain nommé) | Spec versionnée, critères d'acceptation vérifiables, signal d'usage attendu |
| Exécution bornée | Agents, sous le contrôle de l'orchestrateur | Fichier par étape, budget consommé, raison d'arrêt |
| Vérification mécanique | Contrôles du dépôt (scripts) | Commande, sortie, code de retour, commit vérifié |
| Vérification sémantique | Reviewers à contexte neuf | Un verdict par critère d'acceptation, avec sa preuve |
| Exception, changement à fort impact, fusion | Humain nommé, ou politique écrite à l'avance | Verdict, références aux preuves, exception enregistrée |
| Valeur réellement livrée | Auteur de l'intention | Signal d'usage relu après la mise en production |
| Évolution de la factory | Propriétaire de la factory | Modification versionnée, rejouée sur le jeu de tickets de référence |

**Règles**

- Une exception de fusion ne doit jamais être approuvée en silence (P1).
- Un agent ne doit pas approuver son propre travail (P1).
- Le fait qu'une boucle s'arrête ne prouve pas que le résultat est suffisant : l'acceptation est une décision distincte, avec son propriétaire (P1).
- Un humain à qui on demande de trancher doit recevoir un dossier lisible : ce qui a été vérifié, ce qui ne l'a pas été, les désaccords entre reviewers (P1).

## 4. Paliers

L'autonomie et le parallélisme ne s'ajoutent qu'après la preuve que la vérification et la reprise tiennent au palier courant. Les seuils chiffrés ci-dessous sont arbitraires et à ajuster sur données ; aucune source ne les fournit.

| Palier | Qui lance | Qui fusionne | Ce qui s'ajoute | Preuve pour y entrer |
| --- | --- | --- | --- | --- |
| P1. Solo, manuel | Un humain, par commande | L'humain, toujours | Pipeline complet, contrôles, traçabilité, installation par script, dépôt neuf | Point de départ |
| P2. Solo, autonomie bornée | Humain, puis un seul déclencheur automatique | La factory pour le risque faible ; l'humain pour le reste | Bac à sable, vérification de la production et retour arrière, jeu de tickets de référence, test anti-triche | Chaque contrôle a son test ; retour arrière essayé à blanc ; dix jobs à risque faible fusionnés sans correction ; reprise après interruption testée |
| P3. Équipe | Plusieurs auteurs d'intention, déclencheurs | Selon le risque : factory, un humain, ou deux | CI bloquante sur la forge, rôles séparés, dépôts existants, agent d'incident qui propose, métriques produit | Taux de défauts échappés mesuré sur P2 pendant une période convenue ; capacité de relecture nommée ; classement du risque audité sur un échantillon |

**Règles de passage**

- Le passage d'un palier est une décision écrite, datée, avec ses preuves ; ce n'est pas un réglage par défaut.
- Un incident causé par une fusion automatique fait redescendre la politique de fusion d'un cran, jusqu'à la retro.
- Un seul déclencheur automatique est ajouté à la fois.

## 5. Composants

Quatre couches, à ne pas confondre : c'est la distinction centrale du guide. Chaque couche possède une chose et une seule.

| Couche | Réalisation | Ce qu'elle possède | Ce qu'elle ne fait pas |
| --- | --- | --- | --- |
| Modèle | Modèles Claude, choisis par rôle dans la configuration | Le raisonnement | Décider d'une transition ou d'une fusion |
| Harness d'exécution | Claude Code : sessions, sous-agents, permissions, hooks | La boucle outil-observation de chaque agent | Garder l'état d'un job entre deux sessions |
| Harness de dépôt | Instructions (`AGENTS.md`, glossaire, standards, ADR), script de contrôles, verrouillage des dépendances | Ce qui rend le dépôt lisible et vérifiable | Orchestrer |
| Orchestrateur | Skill `factory` et scripts `job`, `gate`, `route`, `forge` | La file, la machine à états, les budgets, le routage | Écrire du code, une spec ou une revue |

**Exigences**

- L'orchestrateur ne doit écrire ni code, ni spec, ni revue : il lance des agents et appelle des scripts (P1).
- L'état d'un job doit vivre sur disque, écrit par un seul script qui refuse toute transition illégale (P1).
- Les types d'étapes, les transitions, les permissions et les budgets sont fixés dans une configuration relue ; les agents ne créent que des données dans ce cadre (P1).
- `AGENTS.md` devrait rester une table des matières courte qui renvoie vers les autres documents (P1).
- Tout ce qu'un agent doit savoir doit être dans le dépôt : une décision restée dans une messagerie n'existe pas pour lui (P1).
- Une correction humaine qui se répète doit devenir un contrôle exécutable ; la prose est réservée à ce qui ne peut pas être vérifié mécaniquement (P1).

## 6. Pipeline par ticket

Un ticket éligible devient un job, avec son worktree et sa branche. Le job traverse huit étapes ; chacune écrit un seul fichier et rend une issue parmi une liste fermée.

### Phase amont, avec l'auteur de l'intention

1. Aligner : l'agent interroge l'auteur jusqu'à lever les ambiguïtés, et met à jour glossaire et ADR.
2. Spécifier : problème, solution, critères d'acceptation vérifiables, périmètre exclu, signal d'usage attendu.
3. Découper : des tickets en tranches verticales, chacun démontrable seul, avec ses dépendances.
4. Mettre en file : un label posé par un humain autorisé. Le label est la frontière de confiance.

Une spec doit être refusée en file si ses critères d'acceptation ne sont pas testables ou si son périmètre n'est pas borné (P1).

### Étapes du job

| # | Étape | Acteur | Sortie | Issues possibles |
| --- | --- | --- | --- | --- |
| 1 | Intake | Agent sans shell | Décision, périmètre, risque, surfaces touchées | Accepté, information demandée, rejeté |
| 2 | Routage | Script | Reviewers et modèles du job, raison du routage | |
| 3 | Spec du job | Agent | Exigences, critères d'acceptation, coutures de test | |
| 4 | Construction | Agent, en TDD | Commits, demande de fusion en brouillon, preuve par critère | Prêt, bloqué |
| 5 | Gate | Script | Verdict et sortie des contrôles | Passe, échoue, non concluant |
| 6 | Revues | Agents à contexte neuf, en parallèle | Un verdict par critère et par angle | Passe, corrections |
| 7 | Approbation | Agent, puis humain selon le risque | Décision motivée | Approuvé, escaladé |
| 8 | Fusion | Humain, ou script selon la politique | Demande fusionnée, ticket fermé | |

### Budgets et arrêts

- Un job doit avoir un budget de reprise : il baisse à chaque échec du gate ou des revues et ne se recharge pas, même après un retour humain. À zéro, le job s'arrête et passe à un humain avec une question précise (P1). Valeur de départ : 3.
- Un job doit avoir un plafond de coût et un plafond de durée, vérifiés par l'orchestrateur avant chaque étape, et non laissés à l'appréciation d'un agent (P1).
- Toute boucle doit avoir cinq sorties écrites : succès, échec, délai dépassé, budget épuisé, escalade humaine. « Réessayer jusqu'à ce que ça marche » est interdit (P1).
- Un verdict « non concluant » (outil indisponible, test instable) ne doit pas être traité comme un échec ni consommer le budget de reprise ; il relance l'étape une fois, puis escalade (P1).

### Admission

- Un ticket ne démarre que si tous ses bloqueurs sont fusionnés (P1).
- La factory ne doit pas démarrer de nouveau job quand le nombre de demandes de fusion en attente d'un humain atteint une limite fixée par le relecteur (P1). Valeur de départ : 3.
- Le parallélisme commence à 1 job. Il n'augmente qu'une fois la reprise et la revue prouvées sur un job seul (P1).

### Reprise

- Une session interrompue doit reprendre chaque job à son étape par la même commande de lancement (P1).
- Une opération distante (créer une demande, commenter, fusionner) doit être rejouable sans doublon : l'orchestrateur vérifie l'état sur la forge avant de réessayer (P1).
- La reprise doit être testée en interrompant réellement une exécution, avant d'entrer au palier 2 (P1).

## 7. Portes et vérification

Seul un contrôle déterministe a l'autorité de bloquer ; un avis de modèle informe, il ne tranche pas seul. Trois niveaux, du moins cher au plus cher.

### 7.1 Contrôles déterministes

- Un script unique doit sortir en 0 seulement si la branche mérite une revue : installation reproductible, types, lint, tests, build (P1).
- Le gate doit exécuter la copie du script située sur la branche de base : une branche ne peut pas modifier les contrôles qui la jugent (P1).
- Toute branche qui modifie un chemin protégé (contrôles, configuration de la factory, CI) doit échouer au gate (P1).
- Le gate tourne deux fois : avant les revues, puis après synchronisation avec la branche de base, juste avant la fusion (P1).
- Des règles d'architecture doivent être vérifiées mécaniquement : frontières de modules, taille maximale de fichier, absence de deux implémentations parallèles d'un même composant sans date de bascule écrite (P1).
- Les messages d'erreur des contrôles devraient dire à l'agent comment corriger (P1).
- Test anti-triche : un test ajouté par l'agent doit échouer sur le code d'avant le correctif et passer après. Un test qui passe dans les deux cas est rejeté (P2).
- Au palier 3, ces contrôles doivent aussi tourner en CI et être déclarés obligatoires sur la branche protégée. Une CI qui signale sans bloquer ne compte pas (P3).

### 7.2 Preuve qu'un contrôle s'exécute

Un fichier présent, ou même importé, ne prouve pas qu'il tourne. Pour chaque contrôle, hook et reviewer :

- un cas qui doit être bloqué, un cas voisin valide qui doit passer, et le comportement attendu quand le contrôle ne comprend pas l'entrée (P1) ;
- une trace d'exécution dans le dossier du job : commande, code de retour, commit vérifié (P1) ;
- un propriétaire et une condition de retrait ; avant de retirer un contrôle, on rejoue le cas qu'il couvrait (P1).

Ces cas forment la suite de vérification de la factory, rejouée à l'installation et après chaque mise à jour (section 11).

### 7.3 Revue par un vérificateur indépendant

- Un reviewer doit recevoir les exigences, le diff et les preuves, mais pas le raisonnement de l'agent qui a construit (P1).
- Il doit rendre un verdict par critère d'acceptation, avec sa preuve, et non une note globale (P1).
- Un reviewer doit lister les critères d'acceptation qu'aucun test n'exerce. Cette liste va à l'auteur de l'intention ; c'est un constat à juger, pas une approbation (P1).
- Le nombre et le type de reviewers sont choisis par le risque et les surfaces touchées : un seul pour le risque faible, deux axes (fidélité à la spec, standards du dépôt) à partir du risque moyen, plus les angles sécurité et interface selon les surfaces (P1).
- L'indépendance se mesure : faux acceptés, faux rejets, verdicts renversés par un humain. Un contexte neuf n'en est pas la preuve (P2).
- Pour le risque élevé, un reviewer devrait utiliser un modèle d'une autre famille (P3).

### 7.4 Approbation et fusion

- Tout changement touchant l'authentification, les permissions, une migration destructrice, la CI, le déploiement ou les dépendances doit être escaladé à un humain, quel que soit le palier (P1).
- Le classement du risque est un contrôle de sécurité : les exclusions du risque faible sont écrites en dur dans le script de routage, pas laissées à l'agent (P1).
- La factory ne fusionne que le commit qui a passé le gate et l'approbation (P1).
- Politique de fusion à trois valeurs : jamais automatique (P1), automatique pour le risque faible (P2), automatique pour tout ce qui est approuvé hors exclusions (P3, sur décision écrite).

## 8. Isolation et sécurité

Un worktree git sépare des fichiers ; il n'isole ni les processus, ni le réseau, ni les identifiants. La sécurité repose donc sur des barrières techniques, pas sur des consignes écrites dans un prompt.

**Entrées non fiables**

- Seuls les tickets portant le label de la factory s'exécutent ; poser ce label exige un droit d'écriture sur le dépôt (P1).
- Le texte d'un ticket ne doit jamais entrer dans un prompt comme instruction : il est copié dans un fichier et présenté comme donnée citée (P1).
- Le premier agent qui lit ce texte n'a pas de shell (P1).
- La suite de vérification devrait contenir des tickets hostiles : instruction cachée, caractères invisibles, demande d'accès aux secrets (P2).

**Permissions et commandes**

- Des règles de refus doivent interdire la lecture et l'écriture des fichiers de secrets (`.env*`, clés, certificats), par les outils de fichiers comme par le shell (P1).
- Un hook doit bloquer les commandes destructrices : réécriture d'historique, push forcé, push vers la branche de base, suppression récursive hors du worktree (P1).
- Les agents ne poussent que la branche de leur job (P1).
- Chaque sous-agent reçoit une liste d'outils explicite ; un reviewer est en lecture seule (P1).

**Secrets et données**

- Aucun identifiant de production ne doit être accessible à une session d'agent. Les agents travaillent sur une base de test jetable (P1).
- Aucun fichier lu par les agents ne contient l'adresse de la base de production (P1).
- Les journaux et transcriptions sont traités comme du code sensible : passés au détecteur de secrets, jamais exportés bruts (P1).

**Bac à sable**

- Avant tout déclencheur automatique ou toute exécution sans surveillance, les agents doivent tourner dans un bac à sable au niveau du système ou d'un conteneur : écriture limitée au worktree, réseau limité aux hôtes nécessaires, identifiants limités à la tâche (P2).
- Le bac à sable ne doit pas être optionnel ni désactivé par défaut une fois le palier 2 atteint (P2).

**Chaîne d'approvisionnement**

- Skills, plugins, serveurs MCP et scripts de la factory doivent être épinglés à un commit ou une version exacte, jamais à « latest » (P1).
- Toute mise à jour est relue comme une première installation, répertoire entier compris (P1).
- Avant d'ouvrir un dépôt inconnu, ses réglages Claude et ses tâches d'éditeur sont inspectés : des hooks de démarrage s'exécutent avant tout prompt (P3, dépôts existants).
- Au palier 3, les commits des agents devraient être signés sous une identité dédiée (P3).

**Commentaires sur la forge.** Si un commentaire peut déclencher une automatisation (déploiement, infrastructure), un agent qui commente détient ce pouvoir par une porte dérobée. L'installation recense ces automatisations et la factory ne commente pas là où elles existent (P1).

## 9. Traçabilité et observabilité

Pour tout commit fusionné, on doit pouvoir répondre en une lecture : quel job, quel agent, quel modèle, quelle version de la factory, quels verdicts, qui a approuvé.

**Ce qui est enregistré, et où**

| Information | Support durable | Palier |
| --- | --- | --- |
| Agent et modèle ayant produit le commit | Trailers du message de commit | P1 |
| Identifiant du job, version de la factory et de sa configuration | Trailers du commit et corps de la demande de fusion | P1 |
| Verdicts du gate et des reviewers, par tour | Résumé dans la demande de fusion ; détail dans le dossier du job | P1 |
| Approbation humaine ou politique appliquée | Demande de fusion (approbation sur la forge) | P1 |
| Raison du routage, reprises, budget consommé, verdicts renversés par un humain | Dossier du job, puis archive | P1 |
| Coût et durée par étape | Dossier du job, tableau de bord | P1 |
| Journal d'audit consolidé, interrogeable | Stockage hors du poste de travail | P3 |

**Exigences**

- Le dossier d'un job fusionné doit être archivé à la fusion, et non rester dans un répertoire ignoré par git et effaçable (P1). Forme de l'archive à décider : branche dédiée, notes git ou stockage externe.
- Chaque résultat distingue ce qui a été consulté, invoqué, exécuté avec succès et jugé utile : quatre observations, quatre preuves (P1).
- Les traces enregistrent les transitions et les verdicts, pas seulement les tokens : un coût n'explique pas une mauvaise route (P1).
- Le contenu complet des prompts et des sorties d'outils ne doit pas être exporté par défaut ; les champs sensibles sont masqués et la liste des champs retirés est documentée (P1).
- Une durée de rétention est fixée pour les journaux bruts (P1). Valeur de départ : 30 jours.
- Le coût est suivi par ticket accepté, tentatives échouées comprises (P1).

**La spec reste la référence**

- La spec amont et la spec de chaque job sont versionnées avec le code ou archivées avec le job (P1).
- Quand tous les tickets d'une spec sont fusionnés, une revue compare le code à la spec complète ; chaque écart devient un ticket ou une correction de la spec (P2).
- La dérive entre spec et code reste un problème ouvert : cette exigence la détecte, elle ne l'empêche pas.

## 10. Couche forge : GitHub ou GitLab

Aucun script ni agent n'appelle `gh` ou `glab` directement : ils passent par une commande `forge`, qui a une implémentation par forge. L'installation ne pose que celle de la forge choisie.

**Opérations de l'interface**

| Opération | Usage dans le pipeline |
| --- | --- |
| Lister les tickets éligibles et leurs bloqueurs | File d'attente, admission |
| Lire un ticket et les commentaires de ses auteurs autorisés | Intake |
| Commenter un ticket, changer ses labels | Demande d'information, escalade |
| Créer et mettre à jour une demande de fusion en brouillon | Construction |
| Lire l'état des contrôles et des approbations d'une demande | Approbation |
| Fusionner une demande à condition que sa tête soit un commit donné | Fusion |
| Lire la protection de la branche de base | Découverte, diagnostic |

**Différences connues**

| Sujet | GitHub | GitLab |
| --- | --- | --- |
| Ligne de commande | `gh` | `glab` |
| Dépendances entre tickets | Relation « bloqué par » | Relation de blocage réservée aux offres Premium et Ultimate ([documentation](https://docs.gitlab.com/user/work_items/linked_items/)) ; sinon convention « Bloqué par #n » dans le ticket |
| Fusion liée à un commit | `gh pr merge --match-head-commit` (vérifié, gh 2.104.0) ; l’adaptateur utilise son équivalent REST, le paramètre `sha` de `PUT /pulls/{n}/merge` | `glab mr merge --sha` ([documentation](https://docs.gitlab.com/cli/mr/merge/)) |
| CI | GitHub Actions | GitLab CI |
| Instance | github.com | gitlab.com ou auto-hébergée : l'adresse est un paramètre |
| Sessions cloud de Claude Code et `/autofix-pr` | Disponibles | Indisponibles : elles exigent GitHub ([documentation](https://code.claude.com/docs/en/claude-code-on-the-web#limitations)) |

**Exigences**

- Le vocabulaire des agents, des fichiers et des messages est neutre : « demande de fusion », « ticket » (P1).
- Les dépendances entre tickets doivent fonctionner sans fonction payante : la convention écrite est le mécanisme de repli, lu par l'adaptateur (P1).
- Les deux adaptateurs passent la même suite de tests de contrat, jouée contre un dépôt d'essai de chaque forge (P1 pour GitHub, au premier dépôt GitLab pour GitLab).
- L'adaptateur GitHub est construit au palier 1. L'adaptateur GitLab est spécifié au palier 1 et construit au premier dépôt GitLab.
- Aucune fonction du pipeline ne doit dépendre d'un service réservé à une seule forge (P1).

## 11. Installation

L'installation est une commande en cinq phases, rejouable, qui montre ce qu'elle va faire avant de le faire. Un installeur exécute du code et pose des hooks : il est lisible, épinglé, et ne télécharge rien qu'il n'annonce.

### 11.1 Prérequis (`factory doctor`)

Diagnostic en lecture seule. Il s'arrête au premier manque, avec la correction à faire.

- Outils et versions minimales : Claude Code, git, python3, l'environnement d'exécution du projet (P1).
- Ligne de commande de la forge installée et authentifiée, avec le droit de pousser, d'étiqueter et de fusionner (P1).
- Accès aux modèles listés dans la configuration ; tarifs de la configuration datés et signalés s'ils sont anciens (P1).
- Répertoire de travail propre, branche de base à jour (P1).
- Bac à sable disponible (P2).

Le diagnostic se relance à tout moment ; il est aussi la première étape de chaque exécution de la factory.

### 11.2 Découverte

Relevé en lecture seule du dépôt et de son environnement, suivi des questions que le relevé ne peut pas trancher.

**Relevé automatique**

- Forge et instance, déduites de `git remote` (P1).
- Dépôt neuf ou existant ; pile, gestionnaire de paquets, commandes d'installation, de test, de lint et de build (P1).
- Présence d'instructions pour agents, de réglages Claude, de hooks git, de CI (P1).
- Protection de la branche de base et droits du compte (P1).
- Automatisations déclenchées par commentaire (P1).
- Fichiers de secrets suivis par git (P1).
- Pour un dépôt existant : durée et stabilité de la suite de tests, couverture, taille des plus gros fichiers, tests instables (P3).

**Questions posées**

1. Forge : GitHub ou GitLab ? La valeur détectée est proposée, à confirmer.
2. Pour GitLab : gitlab.com ou instance auto-hébergée, et son adresse.
3. Offre de la forge : elle décide du mécanisme de dépendances et de la protection de branche.
4. Palier visé : il décide des composants installés (bac à sable, CI bloquante, déclencheurs).
5. Cible de déploiement, s'il y en a une : elle décide des composants de la section 12.
6. Limites de départ : budget de reprise, plafond de coût par job, nombre de demandes en attente.

**Sortie** : un rapport d'aptitude (ce qui est prêt, ce qui bloque, ce qui est risqué) et un plan d'installation listant chaque fichier créé ou modifié. Les réponses sont écrites dans un fichier versionné, pour que l'installation soit rejouable sans questions.

### 11.3 Installation (`factory install`)

- Elle applique le plan issu de la découverte et rien d'autre (P1).
- Mode à blanc : affiche le plan sans rien écrire (P1).
- Rejouable : une seconde exécution ne crée aucun doublon et ne signale que les écarts (P1).
- Elle ne doit écraser aucun fichier existant sans accord explicite, fichier par fichier (P1).
- Composants posés selon les réponses : adaptateur de la forge choisie, labels, modèle de CI de cette forge, agents, scripts, configuration, hooks, règles de refus (P1). Rien de l'autre forge n'est installé.
- Toutes les sources externes sont épinglées à un commit ; la version installée de la factory est inscrite dans le dépôt (P1).
- Désinstallation : une commande retire ce que l'installation a posé, d'après son propre journal (P1).

### 11.4 Vérification après installation (`factory verify`)

- Elle rejoue la suite de vérification de la section 7.2 : chaque contrôle bloque son cas interdit et laisse passer son cas voisin (P1).
- Un ticket factice traverse tout le pipeline sur une branche jetable, jusqu'à une demande de fusion fermée sans être fusionnée (P1).
- Deux tickets pièges : l'un doit être rejeté, l'autre mis en attente d'information (P1).
- Une interruption provoquée en cours de job est suivie d'une reprise correcte (P1).
- L'installation n'est déclarée réussie que si cette vérification passe ; sinon elle indique quoi corriger.

### 11.5 Mise à jour (`factory upgrade`)

- Elle compare la version inscrite dans le dépôt à la version cible et affiche les changements avant de les appliquer (P2).
- Elle migre la configuration sans perdre les réglages locaux (P2).
- Elle relance la vérification, puis le jeu de tickets de référence de la section 13 (P2).

### 11.6 Dépôt neuf, dépôt existant

- Palier 1 : dépôt neuf seulement. L'installeur peut créer le squelette du projet, dont les contrôles passent dès le premier commit.
- Palier 3 : dépôt existant. L'installation commence par un rapport d'aptitude ; si les tests sont absents, lents ou instables, elle s'arrête et liste le travail préalable. Sur du code hérité, des tests de caractérisation du comportement actuel précèdent toute modification par un agent.

## 12. Après la fusion

Une factory qui s'arrête à la fusion est une chaîne de production de code. Cette section couvre ce qui suit ; elle est plus mince que les autres, car les sources publiques décrivent ce qu'OpenAI fait sans dire comment le reproduire, et sans chiffre de qualité.

**Déploiement et vérification (P2)**

- Avant toute fusion automatique, une route de santé qui interroge la base existe, et le retour arrière a été essayé à blanc.
- Après une fusion automatique, la factory attend le déploiement, appelle la route de santé, puis rejoue les parcours clés.
- En cas d'échec, elle revient au déploiement précédent, repasse la politique de fusion à « jamais automatique » et ouvre un ticket.
- Les migrations de base ne sont jamais appliquées par la factory en production.
- La commande de retour arrière dépend de la cible de déploiement ; elle est fournie par un adaptateur, comme pour la forge.

**Observation par changement (P3)**

- Pour un changement à risque moyen ou élevé, la spec nomme les signaux qui doivent bouger et ceux qui ne doivent pas. Un agent les suit pendant le déploiement.
- Ce suivi a une durée de vie : ses constats sont versés dans les tableaux de bord permanents ou supprimés. Sans cette règle, les tableaux de bord prolifèrent.

**Incidents (P3)**

- Un agent d'incident rassemble le contexte et propose des remèdes. Il ne doit jamais en exécuter un : un humain choisit et déclenche.
- Tout incident doit produire une cause et un changement planifié, avec un propriétaire humain. Aucune source ne montre cette boucle automatisée, et l'analyse après incident reste un travail humain.
- Le changement planifié rentre dans la factory comme un ticket ordinaire.

**Retour vers le développement**

- Tout défaut trouvé après fusion est rattaché au job qui l'a introduit et au contrôle qui aurait dû le voir (P1). C'est l'entrée de la retro (section 13).

## 13. Mesure et amélioration

Un indicateur n'est suivi que s'il peut déclencher une décision. Les comparaisons se font avec l'historique du même dépôt, jamais avec des chiffres publiés ailleurs.

**Indicateurs**

| Famille | Indicateur | Palier |
| --- | --- | --- |
| Flux | Travaux en cours, débit, âge des tickets, délai entre mise en file et fusion | P1 |
| Flux | Temps d'attente d'un humain par job, et sa raison | P1 |
| Qualité | Part des jobs fusionnés sans correction humaine ; tours par job | P1 |
| Qualité | Défauts trouvés après fusion, rapportés au nombre de fusions | P1 |
| Qualité | Faux acceptés et faux rejets des reviewers ; verdicts renversés | P2 |
| Coût | Coût et durée par ticket accepté, par niveau de risque | P1 |
| Produit | Signal d'usage nommé dans la spec, relu après la mise en production | P1 |
| Produit | Délai jusqu'à la première valeur, adoption d'une fonction, satisfaction par fonction | P3 |

Le débit seul ne dit rien : toute publication du débit s'accompagne du taux de défauts échappés de la même période.

**Évaluation de la factory**

- Un jeu de tickets de référence, avec le résultat attendu de chacun, est rejoué après tout changement de modèle, d'agent, de script ou de configuration (P2).
- Ce jeu contient des cas réservés que la factory ne peut pas modifier, et des tickets pièges (P2).
- Chaque résultat enregistre le couple modèle et version de la factory : un résultat attribué au modèle seul n'est pas reproductible (P2).
- Il est rejoué aussi à intervalle fixe, car un modèle peut changer sans changer de nom (P2).
- Une différence non significative est notée « non concluante », pas « sans régression » (P2).

**Amélioration continue**

- Une retro est lancée après tout job escaladé, tout job de plus d'un tour et tout défaut trouvé après fusion (P1).
- Elle préfère un contrôle déterministe à une consigne écrite, placé le plus tôt possible dans le pipeline (P1).
- Un nouveau contrôle n'est adopté qu'avec sa preuve : le cas fautif est bloqué, un cas voisin valide passe (P1).
- Un contrôle qui coûte plus d'attente ou d'entretien que le défaut qu'il évite est révisé ou retiré par son propriétaire (P1).
- Un entretien périodique de l'architecture produit de petits tickets de refactoring, traités par le pipeline ordinaire (P1).
- Toute modification de la factory par elle-même passe par un humain ; un changement qui affaiblit une permission, masque une trace ou contourne un contrôle est refusé d'office (P1).

## 14. Questions ouvertes, points à vérifier, sources

**Mes choix, à corriger si besoin**

- Noms des commandes : `factory doctor`, `install`, `verify`, `upgrade`, et la commande `forge`.
- Valeurs de départ : budget de reprise de 3, limite de 3 demandes en attente, rétention de 30 jours, seuil de dix jobs pour le palier 2. Toutes arbitraires.
- Un verdict « non concluant » distinct de l'échec.
- Adaptateur de déploiement séparé de l'adaptateur de forge.

**Questions ouvertes**

- [ ] Forme de l'archive du dossier d'un job : branche dédiée, notes git ou stockage externe ?
- [ ] Langage des scripts d'installation : celui de ZazenCodes (python et shell) ou un autre ?
- [ ] Bac à sable au palier 2 : celui de Claude Code, un conteneur, ou une machine jetable ?
- [ ] Qui tient les rôles du palier 3 dans l'équipe visée, et quelle est sa taille ?
- [ ] Contrôle obligatoire sur la forge dès le palier 1 ou seulement au palier 3 ? Choix par défaut : palier 3.
- [ ] Licence : la GPLv3 de ZazenCodes a été acceptée pour un usage personnel. Un usage en équipe ou une diffusion demande un nouvel examen, que je ne peux pas trancher.

**À vérifier avant de construire**

- L'option `--match-head-commit` de `gh pr merge` ; les commandes `glab` n'ont été lues que dans leur documentation.
- La protection de branche selon l'offre, sur GitHub et sur GitLab.
- La liaison de la cible de déploiement avec GitLab.
- Les versions minimales de Claude Code exigées par ZazenCodes v2 et par les fonctions citées.
- La facturation des exécutions sans interface selon l'offre.

**Ce que cette spécification ne prouve pas.** Elle rassemble des pratiques recommandées par un guide communautaire et par deux récits d'entreprise. Aucune de ces sources ne publie de taux de défauts ; rien ici n'est validé par une mesure indépendante. Les paliers servent à produire ces mesures sur ton propre dépôt.

**Sources** (lues le 19/11/2026 ; détail et limites de lecture dans l'[analyse d'écarts](https://claude.ai/artifact/AFwUpk79NGwX5hUaue3TfE))

- Florian Bruniaux, [Agentic software factories: Orientation map](https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/main/guide/workflows/agentic-software-factories.md), et les pages liées du même dépôt : agent-harness, loop-graph-engineering, spec-first, security-hardening, agent-evaluation, observability, team-metrics, évaluation de Fusion (`docs/resource-evaluations/fusion-multi-agent-orchestrator.md`)
- OpenAI, [Harness engineering](https://openai.com/index/harness-engineering/)
- Anthropic, [Agentic coding is straining CI](https://claude.com/blog/agentic-coding-is-straining-ci-heres-how-we-scaled-test-impact-analysis-at-anthropic)
- Documentation Claude Code : [/goal](https://code.claude.com/docs/en/goal), [sessions cloud et auto-fix](https://code.claude.com/docs/en/claude-code-on-the-web)
- Documentation GitLab : [linked items](https://docs.gitlab.com/user/work_items/linked_items/), [glab mr merge](https://docs.gitlab.com/cli/mr/merge/)
- [Spécification fsalinear](https://claude.ai/artifact/BWoKzgSKk3raZJFhqssvt2) du 14/11/2026, pour l'ossature ZazenCodes et la discipline de Matt Pocock
