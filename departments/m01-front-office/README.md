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
