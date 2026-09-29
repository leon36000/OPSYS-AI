---
name: traiter-une-demande-entrante
description: Procédure pour recevoir et qualifier une demande entrante (courriel, formulaire, texte ou message vocal déjà transcrit), sans jamais inventer une ville, un service ou une urgence.
---

# Traiter une demande entrante

Pour un message qu'un canal du core te livre (SMS, courriel), utilise plutôt la skill
`recevoir-un-message-de-canal` : la plateforme fournit l'identité et l'heure, tu ne les fournis pas.
Cette procédure reste celle d'une voix transcrite ou d'une saisie manuelle.

1. Réunis : le contenu brut du message, le canal (`telephone`, `courriel`, `formulaire` ou
   `texte`), un identifiant de conversation, l'horodatage (fourni par le système, jamais
   deviné) et la zone desservie (villes couvertes par l'entreprise — donnée de configuration,
   jamais inventée). S'il en manque une, demande-la avant de continuer.
2. Appelle `m1_traiter_demande_entrante` une seule fois avec toutes ces données. L'outil
   filtre la provenance, inscrit le signal au registre anti-perte, vérifie le consentement si
   le canal est `telephone`, puis qualifie par règles déterministes.
3. Lis la réponse :
   - `qualifie: false` → un `verdict_qualification` explique ce qui manque (service, ville
     dans la zone desservie, ou coordonnées de contact). Le service est UN des services
     déclarés par l'entreprise : si la demande en évoque plusieurs ou aucun, le détail du
     verdict le dit, et tu demandes lequel traiter. Rédige une demande de précision courte
     et polie ; ne présente jamais cela comme un refus définitif.
   - Refus `REJ-SERVICE-NON-CONFIGURE` (ou `REJ-PROFIL-INVALIDE`) → l'entreprise n'a pas
     déclaré ses services : rien n'a été écrit et il n'y a rien à demander au client. Dis au
     propriétaire quoi configurer (le message de l'outil l'indique) et arrête.
   - `qualifie: true` → le lead (contrat v2, avec son `service`) est transmis à M2 (`decision: "TRANSMETTRE_M2"`). Confirme au
     client que sa demande est prise en charge, sans donner de prix ni de date.
4. Avant d'envoyer tout message au client, fais-le vérifier par `m1_verifier_garde_fou`. Si le
   verdict n'est pas `OK`, réécris le message : ne l'envoie jamais tel quel.
5. L'envoi effectif du message est une action externe (T2) : en mode ombre, elle attend une
   approbation humaine. Ne dis jamais au client que c'est fait avant que ce soit confirmé.
