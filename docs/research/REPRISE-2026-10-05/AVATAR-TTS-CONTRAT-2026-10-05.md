# Raccord audiovisuel des départements — recherche et contrat cible

Statut : recherche documentée; aucune dépendance, modèle ou fonction de synchronisation adoptée.

## Recherche de raccord avatar/TTS — complément du 5 octobre, non adopté

Complément à l’étude audiovisuelle du 4 octobre, fondé sur les captures locales épinglées dans le manifeste `evidence/CAPTURES.json` dans la [capsule de recherche](preuves/AVATAR-TTS-RECHERCHE-r2.tar.xz). Recherche uniquement : aucun paquet, modèle, TTS ou service n’a été adopté ou qualifié.

Le renderer chat existant valide et rend un modèle Three.js, mais n’anime pas les morphs et ne reçoit ni audio ni horloge. Le lecteur TTS existant possède déjà un unique `HTMLAudioElement`, son `currentTime` et les commandes lecture/seek; aucun événement de synchronisation n’est exposé au renderer. Sources locales et SHA-256 : `chat-agent-3d-avatar.ts` `942b0b63246ec8fb7c49dc751712980941ef0d1b5d52c59907f4ad53d4c398de`; `chat-audio-player.ts` `ddeefb7db7dd1cf68a33885bfe3c1c24deaae009ee50aea2a5628239933da90f`; catalogue de modèles `assistant-avatar-model-catalog.ts` `4af1932afe3be380c24f8002730f8ddd30908934e436674bf03c8b31ca1bb280` (reçus dans `evidence/LOCAL-SOURCES.json`).

**Décision recommandée :** raccorder d’abord le renderer existant au lecteur audio existant, avant toute nouvelle dépendance. Une réponse TTS unique associe même identité/source, clip et cues de visèmes; le temps média audio est l’horloge. `timeupdate` et seek recalculent le morph correspondant depuis `currentTime`; pause fige, interruption/changement de source/erreur invalide la génération, arrête l’audio et remet le visage au neutre. Fallback : conserver texte et lecteur normaux, plus un portrait HTML explicitement statique si le WebGL est indisponible. Aucun TTS supplémentaire, mouvement par amplitude, ou animation « parlante » fictive.

| Piste (non adoptée) | Version, code/modèle et preuve exacte | Limite déterminante |
|---|---|---|
| TalkingHead | `1.7.0`, commit `b3e277b3b46f88e557bf28a2c5612a5b04e075c3`; code MIT, fichier `LICENSE` 1 075 octets, SHA-256 `a168d1f90b70b313fb594ddb07e03c9dea08fe2a43df2b4f607db6920ce69cfa`. `speakAudio` accepte AudioBuffer/PCM et cues, `streamInterrupt()` existe. MPFB d’exemple déclaré CC0 dans README de même commit; brunette distincte CC BY-NC 4.0. | Three `^0.180.0`, WebGL navigateur, morphs Oculus/ARKit requis. Français générique documenté; fr-CA et qualité réelle non mesurés. |
| Rhubarb | `1.14.0`, commit `9b9573cd21b253c9ba58739bbd1aa0b50b991bff`; MIT dans `LICENSE.md`, 27 808 octets, SHA-256 `c9a10d99959990ec6802c5e2d519fb23665affa7ba32abbdea5b251ee5f93af6`. | CLI CPU hors ligne pour WAV final, cues A–H/X à 10 ms; pas de lecteur/avatar/seek. PocketSphinx anglais; `phonetic` non spécifique à une langue mais moins précis. fr-CA non qualifié. |
| NVIDIA Audio2Face-3D | SDK commit `1ca0f02535ed774f5dbcd724a31cd486368dc783`; MIT `LICENSE.txt`, 1 097 octets, SHA-256 `211c1b442d1d55e2989de4344d63e9e6b8896cb3bd91289a92da708597087dd6`. Modèle Audio2Face-3D-v3.0, révision HF `b74132732fd9a9d29b237bec193ded64c9745e91`; carte SHA-256 `cb824ad69b31f99e91f7f9b93ff0c19b5f00f296fdf0834ed359bb6191925905`, licence distincte NVIDIA Open Model License. API de métadonnées SHA-256 `119c700f950a0a12bc731afa9ba7a4f8ed40537ac35f1af75f1cceb0969084df`. | CUDA 12.8+, TensorRT 10.13, Python 3.8–3.10; 8 GB RAM, 4 GB+ VRAM recommandé, 10 GB disque. Diffusion prend 1 s et produit 0,5 s central; latence totale inconnue. GPU VPS/coût, retarget et qualité fr-CA non mesurés. La révision modèle est épinglée; aucun digest individuel des poids n’a été capturé. |

Aucun candidat n’a de latence end-to-end mesurée sur OPSYS ni de validation fr-CA. Les captures complètes (README/licences/modèle, en-têtes HTTP et SHA), l’historique de requêtes et les limites sont conservés dans cette même capsule, sous `research/evidence/`. La recherche GitLab a trouvé PassTheMic, spécification AGPL-3.0+, mais aucune implémentation/version utilisable prouvée; elle n’est pas retenue.

ROOT a vérifié les 13 corps capturés et chaque entrée de la capsule. Les licences et versions décrivent les actifs capturés; elles ne qualifient pas des poids non téléchargés ou des actifs tiers. La compilation, le rendu synchronisé et les mesures fr-CA sont des travaux distincts.

Publication : le README TalkingHead contient un JWT public d’exemple expurgé dans la capsule r2.
Son manifeste conserve le hash original et le hash expurgé. La capture brute r1 reste locale, exclue de publication.
