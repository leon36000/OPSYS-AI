# M1-front-office

Front Office IA — reception omnicanale, voix 0->5, qualification, adjointe

Statut: PARTIAL (EPIC E — vague 1 livrée en mode ombre : registre, machine à états des phases
voix 0->5, garde-fou des interdits absolus, qualification, adaptateurs, digest.)

## Canaux du core (PLAN T2.1-a)

M1 reçoit le public par le canal SMS d'OPSYS-CORE : `m1_recevoir_message_canal` qualifie le message (taxonomie des
services et zone du profil d'entreprise, expéditeur comme contact), l'inscrit au registre anti-perte et publie le lead
v2 au bus (`m1.lead_qualifie`, `source` = le canal). Le canal est désactivé tant que ses identifiants et la validation
écrite des politiques ne sont pas fournis ; aucune réponse n'est envoyée au client sans approbation humaine.
Conception, configuration générée, garde-fous et greffes du core à faire : [M1-canaux](../../docs/departements/M1-canaux.md).

M2 consomme ce lead pour de vrai depuis T2.1-b (`evenements.consomme` de M2, sans greffe) : ingestion complète, idempotente ;
un refus lève, le répartiteur réessaie puis met en quarantaine.

## Qualification par conversation (PLAN T2.1-b)

Un client qui écrit le service dans un message et la ville dans le suivant donne un lead complet : `conversation.py` (module
pur) rassemble les messages d'une même conversation dans la fenêtre que le profil d'entreprise déclare
(`fenetre_conversation_minutes`, jamais une durée par défaut) et le lead naît quand service et ville sont connus, un seul
par conversation ouverte. Un message rejoué ne compte pas deux fois ; STOP ferme la conversation ; une fenêtre expirée
n'est plus rassemblée. Sans fenêtre déclarée, la qualification reste message par message et la réponse le dit
(`conversation.verdict`). Ce qui est demandé au client est un brouillon (`brouillon_reponse`, `envoye: false`) : il ne part que
par `m1_emettre_notification` (N4), après approbation. Règles et limites : [M1-canaux](../../docs/departements/M1-canaux.md) §8.
