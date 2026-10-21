---
name: mener-un-appel-vocal
description: "Procédure des phases vocales 0→5 et des appels manqués/voicemails fournis par l’hôte, avec consentements, refus et reprise STT sans second rappel; ne prouve pas une ligne téléphonique live."
---

# Phases vocales et réception de voicemail

Ces phases constituent une machine à états locale, pas un transport téléphonique
branché. N’annonce aucun appel pris, média enregistré ou message livré sans reçu
correspondant. Les parcours de production dépendent de la configuration hôte.

1. À la réception d'un appel, appelle `m1_ouvrir_conversation` avec l'identifiant du signal
   et l'horodatage. Tu obtiens un `conversation_id` et la phase 0 ouverte : ne le régénère
   jamais toi-même.
2. Ne demande la conservation de l'enregistrement qu'après avoir obtenu une réponse
   explicite du client. Appelle `m1_verifier_consentement` avec ce que le client a répondu :
   - autre chose que `"accorde"` → la conservation est refusée; suivre la voie sans contenu enregistré.
   - `"accorde"` → le verdict permet la conservation selon la politique.
   Ce vérificateur ne capture ni ne supprime à lui seul un fichier audio et ne prouve
   pas l'accord distinct de transfert STT externe.
3. Fais progresser l'appel phase par phase avec `m1_transitionner_phase` : jamais de saut de
   phase, jamais de retour en arrière. Retransmets `conversation`, l'objet entier retourné par l'ouverture ou la dernière transition,
   sans le reconstruire. `REJ-PHASE-SAUTE` fige la conversation; un refus de conversation
   non canonique demande sa lecture courante. Ne contourne pas un refus en inventant un état;
   signale la cause à un humain.
4. Si le client raccroche ou abandonne avant la phase 5, appelle `m1_abandonner_conversation`
   pour clore proprement la trace au registre.
5. Une fois la phase 5 atteinte, l’état vocal est clos, sans preuve de qualification commerciale. Traite son contenu comme n'importe quelle
   demande entrante avec la skill « traiter-une-demande-entrante ».
6. Tout au long de l'appel, aucune phrase prononcée ou écrite ne doit contenir de prix, de
   date de chantier, d'engagement, d'aveu ni d'avis légal : vérifie avec `m1_verifier_garde_fou`
   avant de parler si tu as le moindre doute.

## Appel manqué ou voicemail déjà traité par l’hôte

1. Lis le résultat du pipeline avant un nouvel appel d'outil. Le STT hôte exige
   l'accord explicite à conserver/transcrire et, pour un endpoint externe, l'accord
   distinct de transfert. L'accord générique à l'enregistrement n'autorise pas ce
   transfert. Les clés, la configuration fournisseur et l'audio restent hors du prompt.
2. Consentement absent ou panne STT : aucun texte n'est inventé. Le pipeline peut
   importer l'événement sans transcription et préparer le rappel humain. Son statut
   STT `refuse` ne prouve pas l'échec de l'import M1 : lis `m1` et son résultat réel.
   Un refus de l'import peut aussi empêcher la trace; ne prétends pas qu'un rappel
   existe sans référence retournée.
3. L'import manuel `m1_importer_appel_manuellement` n'accepte aucun audio. Il exige
   source, `evenement_id`, `appel_id`, `recu_le`, téléphone et statut `manque` ou
   `voicemail` provenant de l'export/journal livré. Ne génère aucun de ces faits.
   Une transcription doit venir du parcours autorisé, avec consentement explicite;
   elle n'est pas une synthèse de ce que le client aurait dit.
4. Après panne STT, la reprise appartient au pipeline canonique avec les mêmes
   identités/source et sa preuve exacte. Respecte doublon, état ambigu, contenu
   divergent ou refus de preuve. N'utilise pas l'ouverture de conversation ni le
   traitement manuel d'une nouvelle demande pour contourner ce refus.
5. Une transcription enrichie conserve le transfert humain initial; ne le clos
   pas et n'ouvre pas un second lead/rappel. Lis la décision M1 avant toute suite
   CRM. Aucun appel sortant, SMS ou courriel n'est exécuté par cet import.
