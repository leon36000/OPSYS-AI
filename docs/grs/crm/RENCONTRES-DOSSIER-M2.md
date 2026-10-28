# CRM05 — rencontres dans le dossier du projet

## Objectif et pourquoi
Le secrétariat retrouve les visites commerciales du projet sélectionné sans rechercher chaque ancien vendeur.
Une réassignation ne déplace ni ne supprime les rendez-vous précédents. Deux projets du même client restent distincts.
Audit préalable : [AUDIT-RENCONTRES-DOSSIER.md](AUDIT-RENCONTRES-DOSSIER.md).

## État, architecture et fichiers
CRM05 reste **PARTIAL**. Cette tranche raccorde uniquement les rencontres internes M2.
Le registre append-only `agenda_vendeurs` et le registre principal M2 sont relus et validés, sans deuxième stockage.
Le domaine `agenda_vendeurs.lire_rencontres_lead` retourne la révision courante de chaque rendez-vous, actif ou annulé.
`outils.lire_rencontres_lead` confirme l'identité SQL; `console/metier.py` ouvre le port privé admin.
`console/rencontres_ui.py` rend les lignes échappées; `console/crm_ui.py` les intègre au dossier.
`capacites.py` refuse les appels génériques et les profils avant leur dispatch.

## Routes et données
- `GET /crm/lead/{lead_id}` : première page des rencontres du projet exact.
- `GET /crm/lead/{lead_id}/rencontres` : lecture paginée dédiée.
- `GET /crm/agenda/rendez-vous/{id}` : historique existant, accessible depuis chaque ligne.
- Outil privé `m2_lire_rencontres_lead(lead_id, decalage, source_attendue)`.

Chaque ligne fournit titre, vendeur d'origine, créneau Montréal avec offset, statut, révision et source.
Le drapeau de propriété courante indique une réassignation; il ne supprime pas l'ancienne visite.
Le titre n'est pas interprété en HTML. Les identifiants Unicode déjà admis par le dossier restent lisibles;
cette compatibilité ne change pas les contraintes des écritures agenda.
Le total est le nombre de rendez-vous distincts du projet (annulés inclus), pas celui de leurs révisions.
Une planification n'atteste ni un courriel envoyé, ni une confirmation client, ni une rencontre réalisée.

## Workflow et pagination
Ouvrir le dossier, consulter les 25 premières rencontres chronologiques, suivre « Page suivante » ou l'historique.
L'empreinte de lecture lie le lead aux deux têtes M2 (principal et agenda), avec version de contrat.
Le décalage est un entier multiple de 25, de 0 à 10 000. Toute continuation exige l'empreinte reçue.
Un changement de source, y compris une réassignation, renvoie HTTP409 avec lien pour recommencer.
Il n'existe pas de snapshot historique stocké par ce lecteur; un changement sans rapport peut aussi invalider la page.
Sources limitées à 10 000 maillons chacune; quota de sortie vérifié, aucun résultat tronqué silencieusement.
Un projet inconnu est refusé. Source invalide/indisponible : HTTP503 sur la page dédiée,
avertissement explicite dans le dossier qui conserve ses autres sections; jamais un faux zéro.
Paramètres inconnus, dupliqués, mal typés ou continuation sans empreinte : HTTP400.

## Permissions, intégrations et gates
Session admin active en base, rôle revérifié à chaque lecture; owner sans rôle admin, vendeur, employé et appareil exclus.
Aucun nouveau grant, écriture, notification, import Google, coût, facture ou événement M10.
Les URL utilisent le préfixe de déploiement; les réponses authentifiées restent no-store.
La synchronisation Google, accès console vendeur, M10 et mobile sont des tranches distinctes ouvertes.
L'écriture agenda PostgreSQL demeure fermée; cette QA ne certifie pas une instance PostgreSQL ni un navigateur natif.

## Tests, risques et prochaines étapes
Les tests utilisent ingestion, qualification, réassignation, registre et stockage SQL réels sur données fictives.
Ils vérifient isolation des projets d'un même client, ancien/nouveau vendeur, annulation, liens d'historique,
26 rendez-vous sur deux pages, invalidation par chacune des sources, quota, corruption, refus d'accès et base inchangée.
La panne de source au raccord HTTP est injectée; la corruption de registre est vérifiée séparément dans le domaine.
Reçu de qualification : `work/chantier-opsys-20261010/crm-rencontres-qa-20261027-r1` dans le workspace de chantier.
Qualification locale du 27 octobre 2026 : 315 tests PASS, 0 FAIL, 0 SKIP (integration-v2), Ruff et vérificateur
278 outils/173 déclarés valides. Cette population recoupe les 287 tests CRM03 et ne doit pas être additionnée.
Premier passage conservé : 314 tests PASS et 7 erreurs Ruff corrigées; cas de compatibilité Unicode ajouté.
Une réussite locale ne qualifie pas les autres sections CRM05.
Poursuivre les modèles et clauses de soumission versionnés CRM07 après réconciliation des travaux et CI actifs.
