# AI-software-factory

Une software factory agentique pour [Claude Code](https://code.claude.com) : elle prend des tickets étiquetés, les fait passer par intake → spec → construction → gate → revues → approbation, et livre une demande de fusion vérifiée par ticket.

Elle se construit **par paliers** : chaque palier n'ouvre qu'après la preuve que la vérification du précédent tient.

| Palier | Qui lance | Qui fusionne |
| --- | --- | --- |
| P1. Solo, manuel | Un humain | L'humain, toujours |
| P2. Solo, autonomie bornée | Humain, puis un déclencheur | La factory pour le risque faible |
| P3. Équipe | Plusieurs auteurs d'intention | Selon le risque |

## État

Amorce. Le code est celui de la factory du projet fsalinear (dérivée de ZazenCodes v2), copié tel quel le 19/11/2026. Le travail consiste à le rendre conforme au palier 1 de la [spécification de référence](docs/02-specification-de-reference.md) : couche `forge` (GitHub, puis GitLab), budgets, traçabilité par trailers, suite de vérification, installation par script (`factory doctor / install / verify`).

## Lire

1. [Spécification de référence](docs/02-specification-de-reference.md)
2. [Analyse d'écarts](docs/01-analyse-d-ecarts.md)
3. [Synthèse de départ](docs/00-synthese-conversation.md)
4. [Décisions](docs/adr/)

## Licence

GPLv3 — voir [LICENSE](LICENSE) et [CREDITS.md](CREDITS.md).
