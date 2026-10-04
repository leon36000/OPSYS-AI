# Confidentialité des journaux TTS locaux — 2 octobre 2026

Deux chemins du fournisseur CLI journalisent désormais la longueur au lieu du texte à prononcer. Qualification ROOT indépendante : 30 tests réels, zéro échec, erreur ou saut; les deux tests de sentinelle/Unicode sont inclus. Pic RSS 609 878 016 octets, marge cgroup minimale 1 804 111 872 octets; douze empreintes inchangées et aucun nouvel OOM.

[Archive](TTS-CONFIDENTIALITE-R1.tar.gz), [inventaire](CAPSULE-MANIFEST.json). La tentative préalable via wrapper a été interrompue pendant la compilation : elle demeure conservée sans verdict de test. Le CLI Vitest direct a ensuite exécuté uniquement le fichier du propriétaire canonique. Cette preuve couvre les journaux debug des deux chemins et les fixtures CLI existantes, pas une voix ou un modèle réel, ni tous les autres fournisseurs.
