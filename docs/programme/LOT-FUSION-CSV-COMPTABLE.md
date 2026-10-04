# Fusion opérationnelle : premier lot comptable CSV durable

Mandat du 1er octobre 2026, Toronto. Tranche du lot 3 : ingestion concrète et reprenable,
classée `FINANCIAL`, donnant des propositions de rapprochement M5 et une provenance M10.
Cette tranche ne qualifie pas encore PDF/OCR, import massif multi-format ou apprentissage des modèles.

## Choix de réutilisation

Le parser pur `m5_financecore.reconciliation_bancaire_csv.previsualiser_releve_csv` et la
lecture complète/hashée des factures dans `console.banque_metier` sont les sources existantes.
Réutiliser leurs plafonds, mapping explicite, CAD, montants décimaux et contrôles de snapshot.
Les dépôts CAS de photos ont un contrat mobile JPEG/PNG fixe : ne pas l'étendre implicitement
aux documents comptables. Les lots CSV ont leur source protégée et leur propre cycle de vie.
La chaîne de registre M10 existante est réutilisée pour une provenance documentaire typée.

Protection de la source : AES-256-GCM de **cryptography 50.0.2**, version déjà retenue par
`uv.lock` et le verrou runtime. Le venv de vérification, initialement en 50.0.1, est maintenant
en 50.0.2 depuis la roue correspondant au hash du verrou; le Python global n'est pas ce venv.
Notices Apache-2.0/BSD-3-Clause relues dans la distribution
et le dépôt primaire; conserver aussi la notice de la version 50.0.2 effectivement utilisée.
GitHub pyca est le primaire; la recherche GitLab retrouve l'emballage Debian Salsa, dont l'accès
direct est refusé par une page de contrôle. Aucun fork Debian ni autre coffre n'est adopté.
Ajouter l'extra `ingestion` pinning cette version; import tardif avec refus explicite si absent.
Conserver les notices et dépendances dans la recherche. Aucun chiffrement maison.

## Parcours vertical

1. Admin/owner importe un fichier CSV UTF-8 (upload borné ou JSON équivalent), sélectionne un
   compte interne allowlisté et les trois colonnes date/montant/référence; indique un `mutation_id`.
2. Contrôler identité/CSRF, corps, format, limites, compte et disponibilité de la clé avant écriture.
3. Conserver le CSV chiffré, SHA-256, taille, mapping, auteur et classe `FINANCIAL` dans le lot.
4. Extraire avec le parser M5 existant contre un snapshot complet validé et figé. Un refus est
   mémorisé sans recopier ses cellules; la source reste protégée et disponible pour reprise/revue.
5. Le traitement avance par tranches de 100 lignes maximum avec curseur et révision attendue,
   sans modifier factures, paiements, soldes ou ledger. Les propositions restent préparatoires.
6. Une page Fusion opérationnelle montre lots, lignes traitées, états, refus et reprise. Afficher
   l'avancement de ce lot CSV, pas un pourcentage de connaissance globale de l'entreprise.
7. À l'achèvement, mémoriser idempotemment dans M10 les références/source/hash/classe/état,
   auteur, compte interne et nombre de lignes/propositions, sans cellules ni montants du CSV.
La source financière n'est jamais envoyée aux embeddings, LLM ou fournisseurs par cet import.

## Persistance et reprise

Tables SQLAlchemy propres aux lots et segments/propositions, migration Alembic après la révision
0016 du connecteur STT (0017 si aucune révision concurrente n'est ajoutée). Pas de duplication de
facturation M5. Source chiffrée en base, nonce aléatoire 96 bits; AAD lie identifiant de lot, SHA et
version de format. Clé 32 octets fournie par référence de variable serveur, jamais en base ou trace.
La référence par défaut est `OPSYS_INGESTION_CLE`; `OPSYS_INGESTION_CLE_REFERENCE` choisit un autre
nom serveur pour les nouveaux lots. Absence/invalide → refus explicite, aucune clé
générée silencieusement. Rotation : les anciens lots gardent leur référence, sans réchiffrement
implicite; documenter conservation des anciennes références pour lecture/reprise/restauration.

Unité isolée : base d'une instance OPSYS, pas un faux multi-tenant. Les identités admin/owner sont
révérifiées à chaque opération; clients/employés/agents système n'accèdent pas aux sources.
Au plus 64 lots et 64 Mio de chiffrés binaires (sources, résultats complets et segments inclus)
par instance dans cette première version; base64/métadonnées ajoutent du stockage. Admission SQL
atomique pour empêcher le dépassement concurrent. Source ≤1 Mio et ≤2 000 lignes selon M5.
Stocker état, curseur, révision, source/snapshot SHA, erreur stable, dates et références M10.
Résultats/propositions financiers stockés chiffrés également; pas de montants en historique/journal.

Idempotence de mutation scoped à l'identité; même mutation/payload restitue le lot existant,
payload différent refuse. Déduplication du même source/compte/mapping/snapshot sans faux cumul.
Reprise du même lot après redémarrage, sans nouvelle source ni doubles propositions/trace M10.
Une facture modifiée après le snapshot interrompt/refuse toute nouvelle proposition; une nouvelle
évaluation exige un nouveau lot explicitement lié à la source, sans modifier l'ancien résultat.
Une erreur ou panne de tranche annule sa transaction et conserve le dernier curseur validé.
Corruption de la source/cipher/AAD et clé absente ne deviennent jamais des résultats vides.

Précisions issues de la revue du design : revalider le snapshot avant **chaque tranche et à la
clôture**. Si obsolète, état `SNAPSHOT_OBSOLETE`, résultats chiffrés conservés comme brouillons
non consommables; la lecture des propositions refuse aussi un résultat dont le snapshot a changé.
Source/résultats/curseur/révision de tranche changent atomiquement; unicité lot/numéro de ligne,
et compare-and-swap de révision empêchent les doublons concurrents. Ne pas append des lots partiels
au registre de rapprochement M5 : le résultat préparatoire appartient à sa table de lot.

La provenance M10 est un document autonome, pas une affaire M1/M2 inventée. Genre fixe
`m5.releve_bancaire_csv`, registre documentaire dédié et lecteur privé admin/owner; pas d'inclusion
automatique aux contextes clients ou embeddings. Champs : identifiant lot, source SHA, référence
opaque locale, classe, auteur, snapshot M5, compte interne, compteurs, état et date. Chaîne M10
validée avant écriture/lecture, unicité/idempotence explicites, aucun montant ni cellule.

Décision de sécurité : le coffre de crypto-shredding existant conserve les clés dans la même
base. Il n'est pas retenu pour chiffrer ces sources financières contre le vol de la base/sauvegarde.
La clé externe référencée reste le choix de ce pilote; une sauvegarde sans cette clé est inutilisable
pour reprendre/déchiffrer les lots. Des clés enveloppées par document et leur effacement contrôlé
pourront compléter ce choix, sans faire croire que le pilote possède déjà ce mécanisme.

## Interfaces et surface

Page `/fusion-operationnelle`, API privée liste/détail des lots et POST création/traitement.
Les payloads sont fermés et bornés; références/états exposés, aucun brut ni nonce/cipher/clé.
Ce pilote refuse explicitement hors SQLite; PostgreSQL nécessite sa propre qualification.
Uploader HTML avec fichier réel, CSRF et mapping; le traitement/reprise n'effectue aucun réseau.
La mémoire doit permettre de retrouver la provenance du lot via un lecteur privé M10; définir
la référence et l'accès dans ce contrat, réutiliser les registres et vérifications de chaîne.
Source code : nouveau service socle d'ingestion et UI, tables/migration, module purement documentaire
M10; montage et navigation. Garder les routes et outils finance actuels compatibles.

## Preuves requises

Avant code : route absente et scénario lot durable absent. Puis upload CSV réel → progression
partielle → nouvelle connexion/processus → reprise → propositions préparatoires + mémoire M10.
Tester identité/rôle/CSRF, mapping/devise/compte, taille/quotas/concurrence, mutation/rejeu, source
corrompue, mauvaise clé, retrait de droits, révision/snapshot périmés, panne au milieu, source et
résultats chiffrés, aucune fuite dans réponses/journaux, absence d'écriture comptable finale et
aucun appel LLM/HTTP. Régresser parser M5, banque console, stockage/migrations et M10.
Chaque capacité est décrite avec sa limite; pas de label ingestion massive générale par ce pilote.
