# Pont minimal audio → visèmes (proposition, non implémenté)

## Contrat constaté
- `core/ui/src/pages/chat/components/chat-audio-player.ts`: le player détient son `HTMLAudioElement`; play/pause, `timeupdate`, `ended`, `error`, seek, changement de source et `disconnectedCallback` sont déjà centralisés. `sourceIdentity` est une identité interne, souvent dérivée d’une URL; ne jamais la republier.
- `chat-audio-coordinator.ts`: singleton existant impose un seul média audio actif et appelle `onSuperseded`; l’étendre comme propriétaire des événements/cues évite un deuxième arbitre sonore.
- `chat-message-attachments.ts` fournit session/agent au player. `chat-pane-header.ts` rend l’avatar dans le même light DOM du `ChatPane`; le scope doit donc être la paire opaque `(pane/session generation, agent)` et non le seul agent (panes concurrentes).
- `chat-agent-3d-avatar.ts` ne dessine qu’une fois après chargement; possède déjà `generation`, annulation et nettoyage à fermeture, changement d’agent/modèle/connexion, Gateway reset et déconnexion. Un RAF seulement pendant audio actif suffit.

## Proposition — petite tranche future, pas promesse lipsync
- Surfaces: (1) `chat-audio-coordinator.ts` reçoit/publie un état propriétaire typé et borné, scindé par scope opaque; (2) `chat-audio-player.ts` publie l’horloge média et reçoit/annule les cues via son claim existant; (3) composition `chat-message-attachments.ts` + header fournit le même scope au player/avatar, puis `chat-agent-3d-avatar.ts` consomme uniquement le scope exact. Éviter tout event global non scopé.
- État: `{ownerToken, scopeToken, state, currentTimeSec, durationSec}`; tokens aléatoires en mémoire, jamais URLs, session textuelle, transcript, audio ou identifiants de fournisseur. Horloge `media.currentTime` authoritative, durée finie positive requise; notifications sur play/pause/seeking/seeked/timeupdate/durationchange/ended/error/source change/disconnect/supersession. Coalescer via un seul RAF tant que playing; annuler ailleurs.
- Le producteur de cues est distinct de la lecture: fournir ultérieurement un artefact local finalisé et consentement/politique TTS appropriés; pas de microphone, nouvelle requête fournisseur, transcription ni extraction de parole en direct. Sans cues valides, avatar reste statique/neutre.
- Format fermé: version, durée, au plus 1 000 frames triées strictement, `atMs` entier dans `[0,duration]`, visème dans l’enum exact des 14 noms `viseme_*`, intensité finie `[0,1]`; rejeter NaN, unknown keys, frames hors plage et identité différente. À `t`, appliquer une seule visème active + `jawOpen` borné; aucune valeur fournie ou fin de clip remet les 15 canaux à zéro.
- Propriétaire unique: nouveau claim invalide l’ancien avant pause; pause garde la position sans continuer; seek annule le RAF puis sélectionne la frame correspondant à la nouvelle position; ended/error/source change/disconnect/supersession, collapse, unload modèle ou changement session/agent incrementent la génération, annulent RAF/cues et remettent les morphs au neutre. Les callbacks tardifs exigent `ownerToken`, `scopeToken`, génération et identité de modèle courants.
- L’actif MPFB CC0 qualifié contient les canaux, pas de clip d’animation. Rhubarb 1.14.0 (`9b9573c…`) est identifié MIT pour le code mais GitHub marque la licence `NOASSERTION`; dépendances à avis séparés. Il travaille hors ligne sur clip finalisé, non temps réel, et son alphabet A–H/X n’a pas encore de mapping rig vérifié. Évaluation fr-CA non qualifiée: ne pas assimiler sortie anglaise à précision fr-CA ni livrer lipsync avant comparaison annotée humaine.

## Oracles prioritaires quand ROOT autorisera l’application
- Tests player/coordinator: claim A puis B donne uniquement B; pause/seeking/seeked/end/error/disconnect/source swap annulent callbacks et aucune notification de l’ancien token ne traverse; durée infinie/0 ne produit aucun cue.
- Tests cue/renderer: valider refus des frames malformées, ordre/limites, mapping exact des quatorze canaux; à `t=0`, entre frames, seek arrière et fin, morph attendu puis retour neutre; aucune modification des commandes ou états audio existants.
- E2E TTS: réutiliser `core/ui/src/e2e/chat-tts-supplement.real-gateway.e2e.test.ts` (audio réellement joint et lecture par clic), vérifier une phrase fr-CA annotée, pause/seek et qu’aucun autoplay ou audio concurrent ne se déclenche. Pas de mesure qualité tant que jeu fr-CA humainement annoté et seuil d’acceptation ne sont pas définis.

## État de décision ROOT

Proposition conservée comme conception; aucun validateur isolé sans consommateur
n’est adopté. Le producteur TTS actuel fournit audio et texte parlé, sans piste
horodatée qualifiée. La lecture, les permissions et le consentement existants
restent les propriétaires à étendre; un clip finalisé et un mapping visème évalué
sont nécessaires avant de qualifier la synchronisation audio.

## Comparaison primaire des moteurs audio

# Recherche RO : TTS → cues avatar — 2026-10-03

## État OPSYS observé
- `core/src/tts/tts-runtime-types.ts`: `TtsResult` retourne notamment `audioPath`; pas de timecodes, visèmes ou sidecar. `core/src/tts/tts-payload.ts` persiste l’audio puis expose `mediaUrl`, `spokenText` et `trustedLocalMedia`.
- Le GLB MPFB retenu est CC0 et possède 14 morphs Oculus `viseme_*` + `jawOpen`; ce droit d’actif ne couvre ni moteurs ni modèles IA. Renderer existant garde Three/WebGL et le propriétaire audio existant demeure l’unique source d’horloge.

## Solutions comparées
- **TalkingHead v1.7.0**, publié 2025-12-08; dépôt mis à jour 2026-06-02, branche `main` observée : [README](https://github.com/met4citizen/TalkingHead), [LICENSE MIT](https://github.com/met4citizen/TalkingHead/blob/main/LICENSE). Code MIT; licence des voix/TTS, dépendances et avatars reste distincte. `speakAudio` prend AudioBuffer/PCM et des mots+timestamps ou visèmes Oculus avec durées; ses 14 codes OVR non-silence correspondent aux noms MPFB; `sil` devient neutre et `jawOpen` reste distinct. Le README annonce français, pas une qualification fr-CA. Option d’adaptation la plus légère : réutiliser le format/mapping de cues sans remplacer le renderer. Le TTS OPSYS actuel ne fournit pas les timestamps requis.
- **Rhubarb Lip Sync v1.14.0**, publié 2025-04-03, HEAD vérifié `9b9573cd21b253c9ba58739bbd1aa0b50b991bff`: [README](https://github.com/DanielSWolf/rhubarb-lip-sync), [LICENSE.md](https://github.com/DanielSWolf/rhubarb-lip-sync/blob/master/LICENSE.md). Le texte de licence amont déclare MIT pour code et dépendances permissives, GitHub API classe le fichier `NOASSERTION`; vérifier notices binaires si distribution. CLI hors ligne sur clip finalisé, produit formes 2D A–H/X (temps relatif en secondes, export TSV/XML/JSON, précision de timestamp 10 ms). PocketSphinx est anglais; le moteur phonétique non anglophone est moins précis. Mapping formes→visèmes MPFB et fr-CA restent à qualifier; aucun poids/taille binaire ni coût/performance n’a été mesuré.
- **NVIDIA Audio2Face-3D** : [SDK C++/CUDA](https://github.com/NVIDIA/Audio2Face-3D-SDK), HEAD `1ca0f02535ed774f5dbcd724a31cd486368dc783` (2025-08-28). Lecture littérale de [`LICENSE.txt`](https://github.com/NVIDIA/Audio2Face-3D-SDK/blob/main/LICENSE.txt), 1 097 octets, Git blob `16794f6fdb340c805f4f2f9ef8dfbc7e5250b88b`: MIT (Copyright 2025 NVIDIA); ce droit porte sur le code SDK. Les poids James/Claire v2.3.1 sont séparés, sous [NVIDIA Open Model License](https://huggingface.co/nvidia/Audio2Face-3D-v2.3.1-James), dont la carte annonce usage commercial/non commercial sous ses conditions. [NIM docs 2.0](https://docs.nvidia.com/ace/audio2face-3d-microservice/2.0/text/interacting/a2f-rpc.html) décrivent audio PCM mono 16-bit et animation gRPC bidirectionnelle à timecodes en secondes. L’en-tête contient des noms de blendshapes ARKit (JawOpen, MouthFunnel, etc.), pas les 14 Oculus MPFB : retarget visage requis, aucune correspondance plug-and-play établie.

## Coûts, intégration, décision
- A2F est l’option premium: SDK documenté CUDA 12.8+/TensorRT 10.13, RAM 8 GB, VRAM 4 GB recommandée; NIM 2.0 docs indiquent souvent 5–6 GB VRAM par défaut, 0.9 GB possible en profil mono-flux. Il faut hôte GPU NVIDIA, NGC/container/key et exploitation du service. Tarif d’appel hébergé spécifique, coût OPSYS GPU, latence et débit mesurés: absents. Le prix NVIDIA AI Enterprise général ne prouve pas qu’il soit exigé pour ce NIM/modèle.
- Le TTS courant produit un fichier fini sans cues. TalkingHead exige timestamps/visèmes de son TTS ou un mapping texte→temps; Rhubarb exige un passage CPU local sur le clip; A2F exige conversion/stream PCM vers NIM puis adaptation des blendshapes. Dans les trois cas, un sidecar doit être borné et lié à l’identité/durée du fichier réellement lu, puis servi au scope opaque pane/session/agent et au propriétaire audio courant.
- Le fait que le modèle NVIDIA traite l’audio plutôt que le texte ne qualifie pas fr-CA; TalkingHead et Rhubarb documentent des lacunes précises ci-dessus. Aucun corpus annoté, score fr-CA, coût ou SLA OPSYS n’existe dans ces preuves.
- **Décision : aucune adoption audio/cue et aucun validateur isolé à intégrer.** Première tranche future : choisir une source cue compatible OVR autorisée, produire les cues depuis le même TTS final, mesurer sur fr-CA annoté, puis raccorder le seul propriétaire audio. Garder avatar statique si cues absents/invalides.

## Sources primaires
- TalkingHead README/LICENSE: https://github.com/met4citizen/TalkingHead ; version et date dans GitHub Releases (`v1.7.0`).
- Rhubarb README/LICENSE/release: https://github.com/DanielSWolf/rhubarb-lip-sync ; v1.14.0, commit/date ci-dessus. Preuve licence et métadonnées conservées dans `/workspace/poursuite-opsys-2026-10-02-r1/voix-avatar-audio-comparison-r1/`.
- NVIDIA SDK README/LICENSE et [NIM getting started](https://docs.nvidia.com/ace/audio2face-3d-microservice/2.0/text/getting-started/getting-started.html); carte modèle v2.3.1 ci-dessus. Licence SDK lue dans la capture GitHub primaire `/workspace/poursuite-opsys-2026-10-02-r1/voix-avatar-preuves/reponses/github-NVIDIA-Audio2Face-3D-SDK-license.body`.
