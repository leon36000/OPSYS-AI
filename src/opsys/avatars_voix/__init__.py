"""Voix et visages des avatars : registre par client, politique de disponibilité et contrat de session voix.

Couche de GOUVERNANCE et de CONTRAT, pas des moteurs : aucun transport (LiveKit), aucun modèle (Chatterbox, Voxtral,
TalkingHead...) n'est installé ni appelé ici. Voir docs/architecture/AVATARS-VOIX.md.

- `registre`   : entrées voix/visage par client (SQLite), consentements écrits révocables, qualifications exécutées ;
- `politique`  : un canal voix ou audiovisuel n'est « disponible » que si toutes les conditions tiennent ;
- `session`    : machine d'états d'une session voix et règles de gouvernance (REJ-VOIX-*), données seulement ;
- `actions`    : le pont vers le sas d'approbation existant (jamais d'exécution sur la seule parole) ;
- `lecture`    : état de chaque avatar, en lecture, pour la CLI et la console.
"""
