# 0005 — Une couche forge unique pour GitHub et GitLab

Date : 19/11/2026 · Statut : accepté

Aucun script ni agent n'appelle `gh` ou `glab` directement : tout passe par une commande `forge`. L'installeur demande la forge pendant la découverte et n'installe que son adaptateur. Adaptateur GitHub construit au palier 1 ; adaptateur GitLab spécifié au palier 1, construit au premier dépôt GitLab (spec §10).

Ouvert : contrôle obligatoire côté forge dès P1 ou seulement au P3 (défaut : P3, gate local au P1).
