# Coding standards

Modèle. Copiez ce fichier à la racine du dépôt cible et remplacez chaque section par les règles du projet. `reviewer-standards` cite ces règles dans ses constats ; une règle absente d'ici ne peut pas motiver une demande de corrections. Si le dépôt cible n'a pas ce fichier, le reviewer juge d'après `AGENTS.md`, le glossaire, les ADR et le code voisin, et le signale.

Chaque règle tient en une ligne vérifiable, avec, si besoin, un exemple court. Ce qu'un outil vérifie déjà (formateur, linter, `factory/checks.sh`) n'a pas besoin d'être répété ici.

## Langage et style

- <langage, version, formateur et linter qui font foi>

## Nommage

- <conventions de noms : fichiers, modules, types, fonctions, tests>
- Les termes métier sont ceux de `GLOSSARY.md`.

## Structure

- <découpage en modules, frontières à ne pas franchir, où vont les nouveaux fichiers>

## Erreurs

- <comment signaler, propager et journaliser une erreur ; ce qui ne doit jamais être avalé>

## Tests

- <framework, emplacement, nommage ; ce qui doit être testé avant fusion>

## Dépendances

- <comment ajouter une dépendance ; ce qui demande un ADR>

## Commits et demandes de fusion

- <format des messages ; une demande de fusion par ticket>
