---
name: mener-un-appel-vocal
description: Procédure pour faire progresser un appel téléphonique à travers les phases 0→5, sans en sauter aucune, et pour décider si l'enregistrement peut être conservé selon le consentement du client.
---

# Mener un appel vocal

1. À la réception d'un appel, appelle `m1_ouvrir_conversation` avec l'identifiant du signal
   et l'horodatage. Tu obtiens un `conversation_id` et la phase 0 ouverte : ne le régénère
   jamais toi-même.
2. Ne demande la conservation de l'enregistrement qu'après avoir obtenu une réponse
   explicite du client. Appelle `m1_verifier_consentement` avec ce que le client a répondu :
   - autre chose que `"accorde"` → l'enregistrement n'est pas conservé, mais l'appel continue
     normalement, sans enregistrement.
   - `"accorde"` → l'enregistrement peut être conservé.
3. Fais progresser l'appel phase par phase avec `m1_transitionner_phase` : jamais de saut de
   phase, jamais de retour en arrière. Si l'outil refuse (`TRANSITION_INTERDITE`), la
   conversation est figée — n'insiste pas, escalade à un humain.
4. Si le client raccroche ou abandonne avant la phase 5, appelle `m1_abandonner_conversation`
   pour clore proprement la trace au registre.
5. Une fois l'appel qualifié (phase 5 atteinte), traite son contenu comme n'importe quelle
   demande entrante avec la skill « traiter-une-demande-entrante ».
6. Tout au long de l'appel, aucune phrase prononcée ou écrite ne doit contenir de prix, de
   date de chantier, d'engagement ou d'aveu : vérifie avec `m1_verifier_garde_fou` avant de
   parler si tu as le moindre doute.
