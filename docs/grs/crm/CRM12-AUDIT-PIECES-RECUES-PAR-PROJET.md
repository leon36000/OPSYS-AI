# CRM12 — Audit préalable des pièces reçues par projet

Date : 28 octobre 2026 UTC. Source auditée : `7f1249971fdd06898a42f39dbb404f7782227b2c`.
Statut : **PARTIAL — capacité de dépôt absente avant ce chantier**.

## Besoin et résultat attendu

La secrétaire doit conserver une photo ou un PDF reçu dans le dossier du projet exact,
avant une soumission acceptée ou une fin de travaux. Un client peut avoir plusieurs projets.
Le fichier original doit rester consultable avec sa source, son auteur et sa date de réception.
Le téléchargement ne constitue ni une analyse du contenu, ni une preuve de signature, ni une
validation comptable. Le CRM reste le support visuel des départements M2/M3/M4, sans recréer leur vérité.

## Existant inspecté et limites de réutilisation

- `src/opsys/console/documents_chantier.py` relie les documents M3 et les photos de fin de travaux M4.
  Cette galerie exige un devis accepté et son ancre M4; elle ne reçoit aucun fichier arbitraire.
- `src/opsys/fichiers.py` conserve JPEG/PNG dans un CAS partagé, avec SHA et bornes natives.
  Les octets sont en base sans chiffrement applicatif. Le hash ne fournit aucune autorité projet.
  Le tuple MIME alimente directement le contrat DEVICE M4 : lui ajouter PDF élargirait ce contrat.
- `src/opsys/fusion_pdf.py`, son worker et son interface traitent des sources **FINANCIAL** chiffrées,
  bornées à 1 Mio et analysées dans un worker Linux isolé. Leur table contraint cette classe et
  `pdf_natif`. Un document client quelconque ne doit pas être faussement classé financier.
  Le parseur financier refuse aussi les PDF scannés : ce n’est pas une bibliothèque de pièces reçues.
- `departments/m10-memoire/src/m10_memoire/documents_affaire.py` et les adaptateurs
  `src/opsys/documents_affaire_*` sont un pilote de documents **texte** avec identité DEVICE.
  Ne pas simuler cette identité pour contourner leurs permissions.
- `src/opsys/fusion_csv.py` fournit le modèle AES-GCM; sa clé et son AAD appartiennent à l’ingestion.
  Réutiliser la dépendance cryptographique déjà qualifiée, pas sa table, sa classe ou sa clé métier.
- `src/opsys/cles_chiffrement.py` conserve ses clés dans la même base; cela ne protège pas une copie
  intégrale de cette base. Son effacement courant n’atteste pas l’effacement des sauvegardes.
- Le moteur `src/opsys/stockage/moteur.py` utilise déjà SQLite WAL, clés étrangères,
  `BEGIN IMMEDIATE` et transactions/savepoints. Ne pas recréer un verrou transactionnel parallèle.
- M2 possède les identités canoniques lead/client dans son registre; aucun catalogue binaire M2
  n’a été trouvé. `m2_trouver_client_de_lead` est la lecture native à conserver pour l’ancrage.

## Briques examinées

Recherche GitHub et GitLab réalisée avant implantation. Réutilisation retenue : SQLAlchemy/Alembic,
lecteur M2, autorité SQL de la console et `cryptography` **50.0.2** déjà épinglé dans `uv.lock` et
qualifié dans `docs/research/INGREDIENTS.md` (double licence Apache-2.0/BSD-3-Clause, avis existants).
[Licence primaire cryptography](https://github.com/pyca/cryptography/blob/main/LICENSE).
La branche principale consultée ne remplace pas la version verrouillée.
[Mayan EDMS sur GitLab](https://gitlab.com/mayan-edms/manual/tree/master/docs) et ses forks documentent
un gestionnaire Django plus large : aucun code, service ou paquet adopté pour ce petit raccord.
Paperless-ngx, Docling et les autres candidats déjà consignés restent des alternatives à qualifier
pour une future gestion documentaire/OCR complète. Aucun gain chiffré inventé, aucune installation.

## Patch minimal décidé

1. Introduire un stockage privé de pièces reçues, distinct du CAS, de Fusion et de M10 texte.
   Une migration additive, aucun changement des tables existantes et aucune suppression exposée.
2. Contrat interne console SQLite : déposer, lister une page, lire l’original. Admin actif relu en SQL,
   session non expirée, connexion courante; ancrage M2 exact revérifié avant et après l’opération.
   Pas de nouveau droit employé, agent, MCP ou appareil. Pas de faux devis/WCT obligatoire.
3. Identifiant opaque de pièce et clé de saisie idempotente par auteur. Même saisie et mêmes arguments :
   même reçu; autre projet, titre, type ou octets : conflit. Pas de déduplication inter-projets.
4. AES-256-GCM avec nonce aléatoire, AAD propre liant métadonnées/projet/pièce; clé externe dédiée
   fournie explicitement au port privé, jamais en SQL ni dans Git. Titre chiffré avec l’original.
   Clé manquante/invalide ou authentification du chiffré impossible : refus fermé.
5. JPEG/PNG/PDF reçus : 1 Mio maximum par original; vérification du type déclaré, de la signature
   minimale et du SHA. Ce contrôle **ne certifie pas l’innocuité** du document. Aucune extraction,
   conversion, exécution, OCR ou requête réseau. Téléchargement forcé dans la future interface HTTP.
6. Bornes globales explicites (128 pièces / 32 Mio de chiffrés), pages de 20, mesures SQL avant lecture
   des chiffrés. Transaction atomique : ancre, fichier chiffré et reçu indissociables, aucun blob orphelin.
7. Étape suivante : routes/formulaire privé avec CSRF, configuration de clé externe, navigation dossier,
   masquage journaux et preuve navigateur. Le port seul ne sera pas annoncé comme ce parcours livré.

## Données, sécurité et rétention

Le projet, l’auteur, la date, le MIME, la taille et le SHA restent des métadonnées SQL privées.
Le chiffrement ne remplace ni les droits du serveur ni ceux des sauvegardes. Aucun contenu ou titre
n’est envoyé à un modèle. Les pièces sont immuables dans cette tranche. Versions, retrait logique,
rotation de clé, antivirus/CDR, politique de conservation, purge et effacement de sauvegardes restent
à concevoir et qualifier; leur absence ne devient pas une promesse Loi 25. Aucun effacement dur.
Une clé externe perdue rend les originaux illisibles : sauvegarde et exploitation doivent être
qualifiées avant mise en production. PostgreSQL, multi-instance et mobile non qualifiés ici.

## Tests requis et critères de passage

Démontrer d’abord l’absence du port avec une assertion explicite; puis dépôt/lecture après
reconnexion SQL, absence de titre/octets en clair, rejet autre projet et source M2 absente,
rôle révoqué/expiré, rejeu identique/conflit, corruption chiffrée/métadonnées, refus avant décodage
hors quotas, rollback après écriture et migration nouvelle/base antérieure. Contrôler que le contrat
M4 JPEG/PNG reste identique. Vérification intégrée ciblée, lint et vérificateur natif; pas de somme
de populations de tests recoupées. Les vérifications et limites réellement observées seront consignées.

## Autorisations et suite

Développement réversible et QA fictive privée autorisés par Nathan. Aucun déploiement, migration de
production, donnée réelle, paiement, achat ou élargissement de droits. Préflight M10 privé frais et
borné avant modification du port; une mémoire de développement vide ne vaut pas mémoire projet.
Root seul propriétaire Source/Git. Audits statiques indépendants terminés, sans modification.
Prochaine action : port et migration additifs avec preuves négatives, puis raccord HTTP séparé.

## Qualification du port après cet audit

Le [port privé](CRM12-PIECES-RECUES.md) est maintenant implémenté et qualifié localement : 160 tests,
lint et vérificateur natif. La revue a trouvé le rejet des opportunités M2 `~opp~` : régression native
reproduite puis corrigée. Cela ne qualifie pas encore le formulaire HTTP ni une configuration réelle.
