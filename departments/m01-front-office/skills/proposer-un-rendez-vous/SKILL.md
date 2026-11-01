---
name: proposer-un-rendez-vous
description: "Proposer, retenir et préparer un rendez-vous à partir de la capacité et de la cédule de M4, sans jamais donner une date toi-même."
---

# Proposer un rendez-vous

Tu ne donnes ni ne confirmes une date : elle appartient à M4.

1. `m1_proposer_fenetres_rdv` lit la capacité de M4 pour des semaines candidates et rend des minutes libres par semaine
   (granularité : la semaine). « Non calculable, manque X » veut dire que M4 ne sait pas : tu le dis, tu n'inventes rien.
2. `m1_retenir_fenetre_rdv` retient une semaine (engagement INTERNE de 48 h). Au client : « nous vous revenons avec une date »,
   jamais un rendez-vous ferme.
3. Une personne fait dater la cédule de M4, puis confirme (`m1_confirmer_rendez_vous`, depuis l'app admin) ; l'heure vient de M4.
4. Seulement alors, `m1_preparer_messages_rdv` prépare la confirmation et les rappels (brouillons) ; leur envoi passe par le sas.
