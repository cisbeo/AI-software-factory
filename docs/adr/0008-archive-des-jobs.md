# 0008 — Archive des jobs fusionnés sur une branche orpheline `factory-archive`

Date : 19/11/2026 · Statut : accepté (décision de l'issue #1)

Le dossier d'un job fusionné est archivé sur une branche orpheline dédiée, `factory-archive`, dans `jobs/<job-id>/` (spec §9).

- Contenu : synthèses seulement (intake, spec, verdicts du gate et des reviewers, décision, trace d'exécution, coût). Journaux bruts et transcriptions exclus : ils restent sur le poste, rétention 30 jours.
- Écrite par `factory/bin/job` seul, après passage au détecteur de secrets ; le hook interdit aux agents de pousser sur cette branche.
- Le trailer `Factory-Job` mène d'un commit à son dossier.

Écartés : les notes git (ni GitHub ni GitLab ne les affichent, et elles ne sont pas poussées par défaut) ; un stockage externe (palier 3, avec le journal d'audit). Mise en œuvre : issue #14.
