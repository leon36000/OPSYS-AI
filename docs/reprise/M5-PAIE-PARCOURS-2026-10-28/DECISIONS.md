# Décisions

1. **Aperçu sans écriture, puis conservation liée à l'empreinte de l'aperçu.** L'humain conserve exactement ce qu'il a vu ; une source modifiée entre-temps refuse la conservation.
2. **Les entrées sont des déclarations, jamais des résultats.** Attestations booléennes explicites (case décochée = non attesté), crédits et cumuls explicites, pièces référencées. « Tout nul » est une case explicite qui écrit 0.00.
3. **Hors domaine → aucun calcul.** L'ordre est période → couverture → admission → moteurs ; une étape refusée laisse les postes inconnus.
4. **Totaux conditionnels, sans somme partielle.** Le motif de l'inconnu est nommé poste par poste.
5. **Employeur sans valeur par défaut.** FSS, CNESST, normes et FDRCMO exigent une déclaration avec référence ; sinon inconnu.
6. **Journal append-only chiffré.** Une correction est une version ; une réouverture est un événement ; aucune suppression. Clé par dossier (destruction possible par décision humaine, hors de cette mission).
7. **Nonce déterministe (HMAC de l'identifiant, du rang et du clair).** Le paquet M5 interdit l'aléa système ; un couple (clé, nonce) ne chiffre jamais deux clairs différents, même après rollback et reprise.
8. **Commandes à reçu minimal.** L'idempotence partagée est en clair ; les montants ne sortent que des lectures.
9. **Refus = exception = rollback.** `DossierErreur(ValueError)` annule toute la transaction ; le verdict voyage en JSON dans `details`.
10. **Export reproductible et audité.** Pas d'horloge ni d'aléa dans l'export ; l'événement EXPORT conserve son empreinte ; la lecture refuse tout contenu non audité.
11. **Pas d'accès agent.** `roles_appareil` vide, aucun grant Core demandé ; refus démontré par dispatcher et serveur MCP HTTP.
12. **Cumul simulé recalculé par le serveur.** Les valeurs de l'appelant sont écrasées ; la version source doit être la version courante.
13. **Sources employeur sans capture binaire.** Statut `TEXTE_OFFICIEL_LU_SANS_CAPTURE_BINAIRE` visible dans l'export et la matrice ; ne qualifie rien.
