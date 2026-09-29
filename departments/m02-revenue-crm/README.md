# M2-revenue-crm

Revenue CRM — Client 360, pipeline, scoring, anti-doublons

Statut: PARTIAL (EPIC F — vague 1 livrée en mode ombre : registre hash-chaîné, contrat gelé
LeadQualifie (+ source/utm/campagne optionnels, PLAN T2.2), machine à états du cycle de vie
(nouveau/qualifie/perdu, puis converti/cédule/chantier/facture/paiement/avis — PLAN T1.1-a),
interactions et readiness gate, anti-doublons, Client 360 (identité, vue compacte, réouverture
d'opportunité pour affaire répétée — PLAN T2.2), suggestion de prochaine action (M2.6), digest,
adaptateurs fail-closed.)

Identité authentifiée (PLAN T1.4-k2, `src/m2_revenue_crm/acces.py`, docs/architecture/ROLES.md) : pour un
appel d'appareil, `auteur` de `m2_enregistrer_interaction` vient de la personne du jeton, confirmée en base
(un `auteur` différent est refusé, `REJ-IDENTITE-FOURNIE-DIFFERENTE`), et un vendeur ne voit et n'agit que
sur ses leads (`owner` de la qualification ; Client 360 limité à ses opportunités ; le même refus,
`REJ-LEAD-NON-ASSIGNE`, pour un lead d'un autre, sans propriétaire ou inconnu). L'admin voit tout. La
qualification depuis un appareil exige que `owner` soit l'identifiant d'une personne active (seller ou
admin) et publie `m2.lead_assigne`, que M3 relit. Sans identité d'appareil (agent, console, consommateurs
d'événements) : comportement d'avant, `owner` en texte libre. Voir « Ce que T1.4-k2 laisse ouvert »
(pas de réassignation, leads qualifiés avant ce changement).

## Le lead d'un canal arrive par le bus (PLAN T2.1-b)

M2 consomme `m1.lead_qualifie` (`evenements.consomme` de `department.yaml`, `_recevoir_lead_qualifie` dans
`outils.py`) : le lead v2 que M1 qualifie à partir d'un message de canal du core (SMS) est ingéré par la chaîne complète
(`ingerer_lead` : contrat, frontières, unicité, doublons probables signalés, Client 360, `m2.client_associe`), avec l'heure
de réception de la plateforme. Un lead refusé (service retiré du profil depuis la qualification, contrat invalide) lève
`LeadRefuse` : le répartiteur réessaie, puis met l'événement en quarantaine, sans écriture ; jamais d'acceptation silencieuse.
Un événement rejoué, ou le même lead sous un autre identifiant d'événement, ne crée ni second lead ni seconde opportunité
(`deja_applique`) ; le même `lead_id` avec un autre contenu lève aussi. Voir
[M1-canaux](../../docs/departements/M1-canaux.md) §7, et `tests/test_consommer_lead_de_m1.py`.

## Une soumission acceptée convertit le lead par le bus (PLAN T4.10-a)

M2 consomme `m3.devis_accepte` (`evenements.consomme` de `department.yaml`, `_recevoir_devis_accepte` dans
`outils.py` ; DEFINITION-PRODUIT §6 « soumission acceptée → M4 planifie », §7 M2.8). Avant, le lead restait `qualifie`
après l'acceptation. Maintenant, sans qu'un humain l'écrive :
- lead `qualifie` : transition `qualifie → converti` avec `reference_devis_m3` = le devis, à l'heure de l'acceptation
  fournie par M3 (jamais une horloge de M2) ; la **prochaine action** « planifier le chantier » (règle
  `planifier_chantier`, `suggestions.prochaine_action_planifier_chantier`, texte fixe qui cite sa règle, échéance =
  l'heure réelle de l'acceptation) est portée par la transition, donc lue par le Client 360 ; une **activité** système
  (`system:m3`) rattache le fait au dossier. `m2_suggerer_prochaine_action` d'un lead `converti` rend la même règle.
  Aucune date ni aucun créneau n'est promis au client : c'est M4 qui planifie (§7 M2, règles dures) ;
- lead déjà `converti` (ou plus loin) par CE devis : rien à refaire (`deja_converti`), c'est le flux d'avant où un humain
  convertissait avant l'acceptation ;
- lead `perdu` : le fait est gardé (`ignore: lead_clos`), sans conversion, interaction ni quarantaine (patron de
  `m3.devis_sans_reponse`) ;
- lead inconnu : `LeadIntrouvable` ; lead jamais qualifié (`nouveau`), ou déjà converti par UN AUTRE devis :
  `AcceptationIncompatible`. Le répartiteur réessaie, puis met l'événement en quarantaine, sans écriture, visible d'un
  humain (`opsys evenements etat`) : aucune transition n'est fabriquée sans propriétaire ni décision.

Un événement rejoué, ou le même devis sous un autre identifiant d'événement, ne convertit pas deux fois
(registre `devis_acceptes_recus`, clé `devis_id`). La conversion et son activité sont dans la même transaction : si
l'une échoue, l'autre est annulée. Aucun prix, coût ni marge du devis n'est lu ni gardé (M2 n'est pas la source de vérité
financière). `statuts.transitionner` accepte désormais, sans l'exiger, une `prochaine_action` à la conversion ; sans
elle le maillon reste celui d'avant, octet pour octet. Preuve : `tests/test_consommer_devis_accepte.py` (22 tests, dont
le rejeu, l'ordre inversé et l'atomicité) et, avec M4, M5, M6 et M8 par le même bus, `tests/test_cascade_devis_accepte.py`
du socle.
