# CRM07 — rattacher un modèle figé à une nouvelle soumission

Audit avant code, source 2267acb7, 27 octobre 2026.
Le catalogue versionné existe. `devis_durable.creer_devis` ne porte ni clauses ni modèle; son idempotence
compare une liste de champs fixe. `soumission.contenu_client` est la liste blanche commune HTML/PDF.
Le cockpit ne crée pas encore de devis. Les lignes/prix sont calculés par M3; les taxes restent M5.
Réutilisation : audit initial modèles (InvoicePlane GitHub, okane GitLab), registre et transactions OPSYS,
ReportLab déjà épinglé et qualifié dans INGREDIENTS. Aucune nouvelle dépendance ou copie externe.

## Contrat de cette tranche
- Domaine : paramètre optionnel `modele_soumission` de creer_devis, absent pour les anciens appels.
  Snapshot fermé de six clés : modele_id, revision (positive), source_id (SHA256), titre, description, clauses.
  Validation stricte par helper `valider_modele_fige` dans modeles_soumission, erreur explicite.
  Comparaison idempotente inclut le snapshot; copies profondes; transitions conservent le texte.
- Liste blanche client reprend uniquement titre/description/clauses, pas auteur ni référence interne.
  HTML échappe le texte et respecte les lignes; PDF vérifie les caractères puis affiche texte échappé multiligne.
  Les anciens documents sans modèle restent inchangés. Aucun accès au catalogue au rendu.
- Nouveau port privé admin `m3_creer_devis_depuis_modele` : identifiant devis, lead, chantier optionnel,
  lignes (1..20), taux_marge, modele_id, modele_revision exacte, modele_source exacte. Heure serveur.
  Relire source M2 et version M3 dans transaction. Refus source absente/différente, pas de dernière version implicite.
  Idempotence socle : empreinte arguments et petit reçu sans textes ni coûts. Audit transactionnel.
  Même intention/autre charge refusée. Admin actif/SQLite/port console uniquement, aucun grant ajouté.
- UI : parcours depuis projet, choix modèle paginé puis version exacte, formulaire lignes explicites
  sans prix/quantités inventés. Route dédiée hors route détail devis; CSRF/champs fermés/corps borné.
  Création BROUILLON; consultation et téléchargement de brouillons HTML/PDF explicitement sans envoi.
- QA : création réelle, modèle révisé puis ancienne version utilisée, prix par M3, devis accepté inchangé,
  aucun coût/marge dans document, caractères/HTML, mutation/CAS/source/quota/révocation/audit rollback.

## Propriétaires et limites
Agent domaine : devis_durable.py, modeles_soumission.py, soumission.py, soumission_pdf.py et nouveau test pur.
Root : outils.py, console, permissions, tests HTTP, docs, QA bornée. Aucun runtime agent.
Les modèles de lignes préremplies, mobile, writer PostgreSQL, navigateur natif et M10 restent distincts et ouverts.
