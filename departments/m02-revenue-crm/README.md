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
