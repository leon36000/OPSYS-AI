# Soumissions du dossier — consultation admin

Statut : PARTIAL pour CRM-05/CRM-07. Cette tranche relie les soumissions existantes de M3 au projet
sélectionné dans le dossier. Elle ne construit ni éditeur, ni modèles de clauses, ni envoi, ni PDF.
Le besoin métier reste la consultation manuelle de la vérité produite par les départements IA.

## Audit et architecture

M2 Client 360 donne les opportunités du client sans liste de devis. `m3_lister_devis` est réservé au
vendeur authentifié et à ses leads ; ses droits et son comportement restent inchangés.
`m3_lire_devis` sait déjà projeter un devis pour un admin SQL actif. Le nouveau lecteur T0
`m3_lister_devis_lead_admin` réutilise `devis_durable.lister_devis` et sa projection existante :
aucune nouvelle base, aucun import direct de M2, aucun calcul de prix dans le cockpit.

La liste exige un `lead_id` explicite (1–200 caractères, non blanc), une limite entière de 1 à 50 et
un décalage entier de 0 à 1 000 000. Elle renvoie des sommaires triés par identifiant, les prix
canoniques, l’heure du devis et le décalage suivant. Les lignes détaillées restent sur le lecteur
existant. Une page vide signifie seulement aucun devis M3 correspondant : le lecteur M3 ne prétend
pas vérifier l’existence du lead M2. La console fait cette vérification avant chaque page.

La pagination borne la réponse, pas le coût de lecture du registre : le lecteur durable existant
reconstruit les états courants avant filtrage. Une projection indexée et une mesure de charge restent
nécessaires pour qualifier de gros historiques. Le décalage ne garantit pas un snapshot stable si
des devis sont créés entre deux pages ; chaque page dit l’état courant relu.

## Routes et données

- `GET /crm/lead/{lead_id}/soumissions` : page de vingt sommaires, décalage borné, lien détail ;
- `GET /crm/lead/{lead_id}/soumissions/{devis_id}` : lignes, quantités, unités et prix M3.

Le préfixe de la console est conservé. Le dossier offre un lien de consultation pour le projet actif
à l’écran ; il ne présente pas les devis des autres projets comme ceux de ce projet. Avant un détail,
la réponse M3 doit porter exactement le `lead_id` de l’URL ; sinon HTTP 404. Les montants CAD sont
rendus tels quels, sans ajout de taxes ni recalcul. `envoye` signifie ici « approuvé pour envoi —
livraison non attestée », conformément au contrat durable M3, et non une preuve de réception client.

Fichiers : `departments/m03-estimation/src/m3_estimation/outils.py`,
`src/opsys/console/metier.py`, `src/opsys/console/crm_ui.py`, `tests/test_console_crm.py`.

## Permissions, risques et gates Nathan

Les lectures passent par la liste fermée du service console, une session valide et l’admin actif en
SQL. Le nouveau lecteur M3 refuse un appel sans identité, seller, employee, nathan_owner seul, ou un
rôle admin révoqué. Aucun compte ni jeton réel n’est modifié. Les textes sont échappés, les pages
privées ne sont pas mises en cache. Les GET n’écrivent pas de note, d’événement ni de nouvelle soumission.

La validation humaine d’un envoi, d’une acceptation client ou d’une modification financière reste
inchangée. Il n’existe aucun bouton de mutation commerciale sur ces pages. Le profil secrétariat
restreint reste à concevoir : cette tranche ne lui attribue pas implicitement les droits admin.

## Vérification et suites

Les tests de routes utilisent les vrais outils M2/M3 sur SQLite fictif : montant source, contenu
échappé, absence de formulaire de mutation, rattachement du devis, refus des autres profils, rôle
révoqué, bornes de pagination, statut d’envoi honnête et base inchangée avant/après lecture.
Les tests du lecteur admin couvrent pagination, page vide et identité. Les tests de propriété des
vendeurs et du stockage durable M3 restent nécessaires dans le lot de qualification associé.

Les reçus distincts du chantier `crm-root-qa-20261027-r1/quote-*` conservent résultats et reprises ;
le rapport de qualification précise les nombres sans additionner les populations recoupées.
Aucun parcours navigateur, déploiement ni E2E client réel n’est revendiqué ici. Prochaines capacités :
coordonnées éditables avec historique et recherche client ; édition de soumissions/clauses exige un
contrat M3 versionné avant création d’un écran.
