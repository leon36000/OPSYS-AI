# Pilote ASR tiny/base — CPU, 2 octobre 2026

Archive de preuves : [VOIX-CPU-PILOTE-R1.tar.gz](VOIX-CPU-PILOTE-R1.tar.gz), inventaire [CAPSULE-MANIFEST.json](CAPSULE-MANIFEST.json).

Deux modèles whisper.cpp exécutés successivement sur les mêmes dix extraits DEV distincts, après exclusion des locuteurs et audios du corpus TEST R43. Vingt inférences réelles; aucun modèle adopté en production. tiny : WER 51/108 (47,22 %), p95 bout en bout 2,133 s. base : WER 43/108 (39,81 %), p95 3,033 s. Ces erreurs restent trop élevées pour qualifier une réception client; le corpus de lecture court ne mesure pas une conversation métier.

Les deux essais interrompus et la campagne réussie demeurent séparés dans l’archive. Leurs oracles privés, identifiants source, audios et poids sont exclus de l’archive publique. Les dix audios figés et l’oracle indépendant sont conservés séparément dans l’espace QA privé. Les licences, révisions et empreintes permettent de retrouver les poids; aucune voix TTS, animation ou synchronisation labiale n’a été qualifiée.
