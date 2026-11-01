"""Connecteurs courriel (chantier 5, tranche 1) : Gmail, Microsoft Graph, IMAP/SMTP et exports mbox.

Lecture / ingestion et envoi SOUS SAS D'APPROBATION. Contrat, scopes, erreurs et limites :
docs/architecture/CONNECTEURS-COURRIEL.md.

- `port` : le port `FournisseurCourriel` (boîtes, dossiers, synchronisation incrémentale par curseur, lecture, envoi
  d'un brouillon approuvé) ; `gmail`, `graph`, `imap`, `mbox` : les adaptateurs ;
- `transport` : le transport HTTP INJECTÉ (aucun réseau dans le code testé) ; `client_oauth` : 401 -> rafraîchissement,
  429 + Retry-After, 5xx, liens de pagination bornés à l'hôte du fournisseur ;
- `oauth`, `jetons` : cycle OAuth côté serveur (PKCE, `state` signé à usage unique, portées minimales, rotation) ;
  jetons chiffrés dans le coffre `opsys.secrets_coffre` uniquement ;
- `normalisation`, `isolation` : un modèle de message commun ; le corps est une DONNÉE NON FIABLE ;
- `comptes`, `ingestion` : état de connexion, journal append-only, alimentation de la file d'ingestion d'onboarding ;
- `envoi` : brouillon, empreinte, jeton d'approbation lié au contenu, vérifié contre le sas `opsys.approbations`.

Aucun appel réseau réel n'est fait par ce paquet dans ses tests : tout adaptateur est qualifié contre des doubles.
"""
