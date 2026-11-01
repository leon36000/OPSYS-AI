---
name: scorer-et-classer-les-leads
description: Procédure pour calculer le score expliqué d'un lead, classer la file des leads ouverts et lire la calibration du modèle, en rappelant que le score ordonne et ne décide jamais, qu'aucune probabilité n'est affirmée et qu'aucun lead n'est écarté.
---

# Scorer et classer les leads

Le score de lead 2.0 est un RANG explicable : six facteurs (qualité, urgence, conversion, rentabilité, préparation, risque), des
poids déclarés, une version de modèle. Il ORDONNE la file de travail ; un humain décide.

1. **Un lead.** `m2_calculer_score_lead` rend le score (0 à 100), la contribution de chaque facteur et de chaque signal, la
   couverture des poids, ce qui n'a pas pu être évalué (et ce qu'il manque) et la version du modèle. Cite l'explication, pas
   seulement le chiffre. `avec_recu` donne le reçu rejouable (`m2_rejouer_recu_commercial`).
2. **La file.** `m2_classer_file_leads` (page par page, `suivant`) liste les leads ouverts du plus prioritaire au moins
   prioritaire. `total_ouverts` est le nombre de leads ouverts : aucun n'est retiré. Un score bas veut dire « plus tard », jamais
   « écarte » : tu ne proposes pas de rejeter, de fermer ni d'ignorer un lead à cause de son score.
3. **« Non évalué » n'est pas zéro.** Un facteur sans donnée (bandes de valeur à configurer, aucune valeur déclarée, lead non
   qualifié, devis illisibles) sort du calcul et est nommé. Ne comble rien. La valeur d'une opportunité se déclare avec
   `m2_declarer_valeur_pipeline` (décision d'une personne, estimation commerciale, jamais un prix).
4. **Aucune probabilité.** La calibration (`m2_lire_modele_scoring` avec `avec_calibration`) est mesurée sur un jeu FICTIF : elle
   prouve l'outil de mesure (AUC, Brier, courbe), pas la valeur prédictive sur de vrais clients. Ne dis jamais « 70 % de chances ».
5. **Équité.** Aucun attribut protégé (âge, genre, origine, langue, état civil, santé…) ni identifiant personnel n'entre dans le
   score ; `m2_lire_modele_scoring` en donne la liste. Si on te demande de scorer selon l'un d'eux, refuse.
6. Un vendeur ne classe que SES leads. Un refus de droit arrête ce parcours.
