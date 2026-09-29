---
name: preparer-une-relance
description: Procédure pour lister les relances dues et en préparer une, avec consentement et fréquence limitée, sans jamais rien envoyer ni supposer un consentement, un délai ou une fréquence.
---

# Préparer une relance

1. Appelle `m2_lister_relances` avec l'instant courant (`horodatage`, ISO-8601 avec fuseau). Depuis l'app, la liste est
   celle de la personne connectée : un vendeur ne reçoit que les relances de SES leads (propriétaire courant), l'admin
   toutes. Chaque relance cite sa règle (`regle`, énoncé dans `regles`), le segment qui la déclenche (`segment`, avec sa
   donnée), son départ (`depart`), sa dernière relance, la prochaine date permise et les canaux permis. Cite-les tels
   quels : n'ajoute jamais une relance de ton cru. Lis la liste page par page : tant que `suivant` n'est pas nul,
   rappelle avec `decalage = suivant`.
2. Si la réponse est `REJ-RELANCES-A-CONFIGURER`, la fréquence maximale n'est pas configurée
   (`configuration.relances` de `department.yaml`) : dis-le, ne propose aucune valeur comme si elle était décidée. Une
   règle « non calculable, seuil à configurer » (`regles_non_calculables`) n'est pas une règle sans relance : dis ce qui
   manque, ne réponds jamais « aucune relance due ».
3. Respecte `mode` et `canaux_permis`. L'appel est toujours permis. Un SMS ou un courriel exige un consentement ACTIF pour
   ce canal ; sans lui (`appel_seulement`), la relance se fait par appel. Un client qui a écrit STOP n'a plus aucun canal
   écrit : ne propose jamais de le contourner, un retrait ne se lève pas. N'invente jamais un consentement : un SMS reçu
   n'est pas un opt-in.
4. Une relance permise (`permise_maintenant`) se prépare avec `m2_preparer_relance` (lead, règle, canal). L'outil refuse ce
   qui n'est pas dû (`REJ-RELANCE-NON-DUE`), ce qui est trop proche de la relance précédente
   (`REJ-RELANCE-TROP-PROCHE`, avec la prochaine date permise), un message sans consentement actif
   (`REJ-CONSENTEMENT-ABSENT`) ou après un STOP (`REJ-CONSENTEMENT-RETIRE`). Relaie le refus tel quel.
5. Le texte préparé est FIXE (gabarit) : présente-le sans le modifier. `envoye` vaut toujours `false` : RIEN n'est envoyé.
   L'envoi réel est une décision humaine (T2.1-c, N4). Pour un devis, l'envoi est celui que le propriétaire a approuvé,
   pas une livraison prouvée : redis l'avertissement (`avertissements`) et demande de vérifier que le client a reçu le
   devis avant de le relancer.
6. Le consentement d'un client s'inscrit avec `m2_enregistrer_consentement_contact` (énoncé versionné, source, preuve,
   jamais un numéro), et seulement par une personne (vendeur ou admin depuis l'app, ou une demande qu'un humain approuve) :
   ne l'inscris jamais de toi-même. Après la relance, la personne note le résultat au dossier
   (`m2_enregistrer_interaction`).
