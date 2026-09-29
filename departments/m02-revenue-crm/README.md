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

