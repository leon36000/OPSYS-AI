# Liaison transactionnelle des cibles M2/M3

État local du 30 septembre 2026 : implémentation en cours de vérification. Cette tranche porte
sur huit mutations unitaires, avec SQLite. Elle complète la garde de contexte du Core et les
approbations existantes; elle ne certifie pas toutes les cibles C02.

## Mutations couvertes

| Département | Outils |
|---|---|
| M2 | `m2_transitionner_statut`, `m2_reassigner_lead`, `m2_enregistrer_interaction`, `m2_preparer_relance`, `m2_enregistrer_consentement_contact`, `m2_marquer_chantier_termine` |
| M3 | `m3_marquer_devis_accepte`, `m3_demander_envoi_devis` |

La configuration générée par `opsys-metier openclaw configurer` déclare ces huit cibles avec
`type: ticket`. Il faut régénérer les fragments pour obtenir ce contrat. Une ancienne entrée
`inconnue` reste bloquante : le runtime ne la transforme pas automatiquement en autorisation.
Les autres cibles inconnues, les opérations batch et les objets dont le lien métier n'est pas
prouvé restent hors de cette tranche.

## Du contexte à l'effet métier

Le Core utilise la session courante d'un agent de département, son profil de contexte actif
et un paquet M10 frais. La session partagée `agent:<agent>:main` est refusée. Juste avant
`tools/call`, après les politiques qui peuvent modifier les arguments, il demande un ticket
au serveur de contexte privé du département. L'outil privé
`opsys_contexte_creer_ticket_cible` et `m10_paquet_contexte_affaire` sont absents des catalogues
publics. Le jeton de transport privé `OPSYS_CONTEXT_MCP_JETON` est distinct du jeton métier.

Python lit la liaison M10 active et les registres canoniques. Un lead cible doit être exactement
l'affaire liée. Un devis doit porter ce lead, déjà connu de M2; ses références de chantier
doivent aussi concorder. Une opportunité M10 ne reçoit aucune autorisation depuis le seul
préfixe de son lead. Le lien WCT manquant ou non prouvé produit un refus.

Le ticket opaque est lié au département, à l'agent, à la session, à l'affaire, à la ligne M10,
au nom de l'outil et à l'empreinte des arguments finaux. Il expire après 120 secondes tant
qu'il n'a pas été utilisé. Le Core le transmet uniquement dans `_meta["opsys/cibleTicket"]`.
Il n'ajoute aucun champ public au schéma de l'outil et ne met pas ce secret dans un prompt.
La base conserve son empreinte, jamais le secret brut.

Le dispatcher Python revalide la liaison et les références métier dans la transaction SQLite
qui produit l'effet, le reçu ou la demande d'approbation. Une lecture préalable réussie ne
vaut pas autorisation finale. Si le lead a été converti par un autre devis entre ces deux
instants, l'acceptation M3 doit être refusée avant sa mutation et sa publication d'événement.

## Approbations, rejeu et actions humaines

Une action d'agent qui exige une approbation scelle le ticket à la demande exacte. La demande
publique ne contient ni secret ni empreinte privée. Au clic humain, le système revalide le
signataire actif, la liaison M10 et la cible canonique dans la transaction d'exécution.
Le scellement permet une décision après le délai de 120 secondes; une liaison révoquée ou
remplacée invalide toujours cette exécution différée.

Le renvoi du même ticket avec le même outil et les mêmes arguments restitue la réponse déjà
enregistrée, sans second effet. Il ne crée pas une nouvelle autorisation et peut donc restituer
cette réponse après expiration. Des arguments ou une route différents sont refusés.
Un nouvel appel `callTool` du Core demande cependant un nouveau ticket. Cette tranche ne fournit
pas d'identifiant durable d'appel agent pour dédupliquer ce nouvel appel après perte d'une réponse;
les garanties métier propres à chaque outil restent applicables.

Les actions N3 d'un humain via un appareil apparié conservent leur chemin existant : Core
construit l'enveloppe d'identité et d'idempotence après authentification de l'appareil, puis
Python relit la personne active et son rôle avant l'écriture. Des arguments de modèle ne
peuvent pas fournir cette identité. La demande N4 d'envoi de devis reste accessible à un
vendeur authentifié dans la portée de son appareil : elle crée seulement une approbation,
même si le département est configuré en mode autonome. L'identité est relue dans cette
transaction avant le reçu. Le propriétaire décide ensuite de l'exécution. L'accès humain
générique conserve son contrat; une route de département explicitement différente est refusée.
Ce chemin ne remplace pas les approbations N4/N5.

## Révoquer une liaison

La commande humaine suivante demande l'identifiant et le mot de passe en terminal interactif :

```bash
python -m opsys.memoire_liaison --session '<clé privée>' --ligne '<ligne active>' --motif '<raison>'
```

La personne doit être active et porter `admin` ou `nathan_owner`. Le programme fournit l'heure
serveur et la source `cli`; aucun argument ne permet de nommer un acteur, un rôle ou une heure.
La révocation compare la ligne active attendue puis ajoute un maillon d'audit. Si une autre
liaison l'a remplacée, elle refuse de révoquer cette nouvelle liaison. Les anciens maillons
restent conservés.

## Stockage et limites

La migration `0013` ajoute `liaisons_tickets` et une empreinte privée facultative aux demandes
d'approbation. La rétrogradation est refusée pour conserver les traces d'autorisation.
Émission, consommation, approbation scellée et révocation sont désactivées sur PostgreSQL
dans cette première tranche : son verrouillage concurrent n'est pas encore démontré.

Cette protection ne remplace pas l'isolation des comptes système, les permissions des secrets,
les contrats métier, les règles financières ou l'authentification des canaux. Elle ne rend pas
les autres départements autonomes par simple déclaration de cible globale. L'inventaire restant
est conservé dans [C02](../research/R17-2026-09-30/C02-LIAISON-CIBLES-RESTANTES.md); ses formulations
sur le code décrivent l'audit initial, avant cette tranche.

La garde Core vérifie les agents et outils déclarés dans sa configuration active. Son ancien
comportement transparent pour les noms absents de cette configuration n'est pas une garantie
universelle sur les futurs outils. Python impose le ticket aux huit mutations listées,
indépendamment de cette projection; les autres cibles exigent leurs propres raccords.

## Sources et validation

Le code de référence est `src/opsys/liaison_cibles.py`, le répartiteur `capacites.py`,
`approbations.py`, la CLI `memoire_liaison.py`, les registres M2/M3/M10 et les helpers
`core/src/context-engine/opsys-contexte-cible-ticket.ts` et `opsys-contexte-cibles.ts`.
Le [plan initial](../research/R17-2026-09-30/C02-PLAN-LIAISON-CIBLES.md) décrit les critères négatifs.
Les preuves finales et les limites de l'intégration Core→Python seront liées ici après gel
et validation des sources; les résultats R17/R18 antérieurs ne certifient pas cette tranche.
