"""Ingestion d'onboarding (chantier 4, tranche 1) : dépôt massif -> classement -> extraction -> brouillons.

Le client dépose ses documents (factures, soumissions, contrats, listes de clients) ; OPSYS les ingère, les classe,
en extrait les champs et PEUPLE EN BROUILLON les comptes à payer (M5) et le CRM (M2). Aucune donnée financière ni
aucune fiche client n'est définitive sans validation humaine (outils de M5 et de M2). Contrat, états et codes :
docs/architecture/INGESTION-ONBOARDING.md.

- `depot` : lecture par nom, types fermés, archive ZIP gardée ;
- `taches` : table de tâches durable (SQLite), interface `PortTaches` prête pour DBOS/PostgreSQL ;
- `scellement` : chiffrement au repos (clé externe du pilote Fusion) ;
- `extraction_texte`, `classement`, `port_extraction` : les étapes ;
- `service` : dépôt, avancement, lecture, décision sur un brouillon.
"""
