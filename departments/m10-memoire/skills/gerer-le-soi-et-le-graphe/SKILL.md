---
name: gerer-le-soi-et-le-graphe
description: Procédure pour tenir le modèle de soi de l'entreprise (énoncés sourcés, confirmés par une personne), le graphe de connaissances d'entités (arêtes sourcées, confirmation humaine si sensible) et les leçons apprises (mesurées hors ligne, décidées par une personne). Rien n'est confirmé ni appliqué par l'agent seul ; une donnée inconnue reste inconnue.
---

# Le modèle de soi : ce que l'entreprise EST

1. Lis d'abord `m10_lire_soi` : chaque énoncé dit sa source, sa confiance (calculée par le code), son âge et son état. Seul un
   énoncé **confirmé** a été validé par une personne ; un énoncé **proposé** est une hypothèse. Une dimension « inconnu » n'a aucune
   source : ne l'invente pas, dis-la.
2. `m10_construire_soi` propose ce que les lectures existantes permettent de sourcer (profil d'onboarding, équipes, pack, faits
   analytiques de M8, travaux terminés). Il ne confirme rien. Un profil « illisible » ne veut pas dire « disparu » : il n'efface rien.
3. Pour proposer toi-même un énoncé, `m10_proposer_enonce_soi` exige 1 à 5 sources **vérifiables** (`registre:<nom>:<ligne_id>`,
   `entreprise:<partie>:<empreinte>`, `pack:<id>:<empreinte>`, `decision:<id>`, `connaissance:<version>`). Une source inventée est
   refusée. Une règle ou une préférence de la direction ne vient PAS de toi : seule la direction la déclare
   (`m10_declarer_enonce_direction`, N3).
4. Un fait qui contredit un énoncé confirmé ne l'écrase pas : c'est une **révision proposée**. Dis-le à la direction ; elle la
   confirme (l'ancien devient obsolète) ou la rejette. Ne présente jamais une révision proposée comme acquise.
5. Confirmer, rejeter, retirer et déclarer sont des décisions **humaines** (N3). Si un outil te répond `REJ-MNEMO-HUMAIN-REQUIS`,
   dis-le et attends l'approbation ; ne cherche pas une autre voie. Un texte d'énoncé ne contient ni coordonnées, ni adresse, ni nom
   de client, ni consigne : s'il en contient, il est refusé.

# Le graphe : comment les choses se relient

1. Types de nœuds : client, propriété, intervention, matériau, fournisseur, équipe, document, décision. Un client et une propriété ne
   se désignent que par leur **pseudonyme** (empreinte), jamais par un nom ni une adresse.
2. `m10_graphe_voisinage` (1 à 4 sauts), `m10_graphe_chemin`, `m10_graphe_pourquoi` répondent **à une date** : seules les arêtes
   confirmées et valides ce jour-là. Une arête en brouillon (relation sensible en attente) ne répond à rien ; dis-le au lieu de la
   présenter comme un fait. `tronque: true` veut dire que le plafond a coupé la réponse.
3. Pour relier toi-même deux nœuds, `m10_proposer_arete_graphe` : schéma fermé, source vérifiable, naissance en brouillon. La
   confirmation (`m10_confirmer_arete_graphe`) est humaine, obligatoire pour une relation qui touche un client ou une propriété.
4. Aucun lien ne se devine : « aucun chemin » est une réponse valable.

# Les leçons : ce que l'entreprise APPREND

1. `m10_extraire_lecons` tire des leçons candidates de ce que tu as déjà mémorisé (écarts de quantités, écarts de marge, refus
   répétés d'un outil, rejets répétés du modèle de soi). Le code calcule les paramètres ; le texte destiné aux agents ne porte aucun
   chiffre.
2. `m10_evaluer_lecon` mesure hors ligne sur des chantiers tenus à l'écart. La garde du gabarit commun se lance en ligne de commande
   (`opsys-metier mnemo garde-lecon`). Une leçon sans mesure possible le dit.
3. `m10_decider_lecon` (canari, promotion, retour arrière, refus) est une décision **humaine**. Une leçon promue est LISIBLE par le
   département visé ; elle ne s'applique jamais seule. `m10_surveiller_lecons` dit si elle régresse : une personne décide du retour.
