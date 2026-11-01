# Voix et visages des avatars : registre, politique et contrat de session voix

Statut : tranche 1 (2026-11-01). **Gouvernance et contrat, tout hors ligne.** Aucun moteur vocal, aucun transport, aucun
fichier de poids, aucun appel réseau n'est livré ni exécuté ici. La voix **n'est pas prouvée de bout en bout**.
Complète [AVATARS.md](AVATARS.md) (identité, canaux, projection dans le core) et
[FOURNISSEURS-ET-SECRETS.md](FOURNISSEURS-ET-SECRETS.md) (registre de fournisseurs, moteur de politique de licence).
Code : [`src/opsys/avatars_voix/`](../../src/opsys/avatars_voix/) · migration `0039` · tests
`tests/test_avatars_voix_*.py`.

## Ce qui est livré, ce qui est prévu, ce qui n'est pas prouvé

| Élément | État | Preuve |
|---|---|---|
| Registre par client des voix et visages (SQLite), migration 0039, montée et descente | **Livré** | `test_avatars_voix_registre.py` |
| Consentements écrits, révocables, empreinte du document signé | **Livré** | idem |
| Journal des qualifications EXÉCUTÉES (append-only), lié à l'empreinte du moteur | **Livré** | idem |
| Politique de disponibilité d'un canal (REJ-AVATAR-…), réutilisant le moteur de licence | **Livré** | idem |
| Contrat de session voix (états, divulgation, enregistrement, quotas, sas d'approbation) | **Livré** (données seulement) | `test_avatars_voix_session.py`, `test_avatars_voix_sas.py` |
| Lecture admin : `opsys-metier avatars`, page « Plateforme > Avatars » | **Livré** (lecture seule) | `test_avatars_voix_lecture.py` |
| Canaux voix et audiovisuel d'un département | **Prévus** : `CANAUX_REALISES = {messagerie}`, donc aucun canal vocal ne peut être déclaré disponible | tests de la politique |
| Transport LiveKit, worker vocal, VAD, STT, TTS, visage TalkingHead, SIP pour Léa | **Prévus, non installés, non appelés** | aucune |
| Qualité mesurée (WER fr-CA, accent, MOS, latence) | **Jamais mesurée** | aucune |
| Avis juridique (art. 36 C.c.Q., LCCJTI art. 44-45, divulgation d'une IA) | **Non obtenu** | aucune |

Ce que veut dire « qualifié » ici : **un test de connexion réel du serveur a réussi et a été journalisé** (par exemple,
« le module du moteur est présent sur ce serveur », ou « le point d'accès répond »). Ce n'est pas une qualité vocale
mesurée. Les moteurs réels du catalogue (Chatterbox, Voxtral, TalkingHead...) n'ont aucun point d'accès configuré par
défaut : ils sont « à mesurer ». Les tests de ce dépôt qualifient des moteurs FICTIFS dont le point d'accès est le module
standard `json` (sonde locale réelle, sans réseau).

## Architecture cible (décision de l'architecte, FEUILLE-DE-ROUTE r2 tableau A et R1 §7)

```
 appareil / navigateur / téléphone (SIP)
        │  WebRTC                      rendu du visage SUR l'appareil (TalkingHead, MIT)
        ▼
 LiveKit server (SFU, Apache-2.0)  ──►  LiveKit Agents (Python)  « un worker par session »
        │                                  VAD (Silero) → fin de tour (Smart Turn v3)
        │                                  → STT (Voxtral Mini Realtime)
        │                                  → pont LLM du Core (mêmes permissions que le chat)
        │                                  → TTS (Chatterbox Multilingual + voix québécoises sous contrat)
        ▼                                  → visèmes / émotion par data channel
 plan de contrôle (VPS) : gateway Core, LiveKit, agents, base       nœud d'inférence vocale (GPU) : STT, TTS
```

Ce dépôt livre la **couche de gouvernance** qui décidera, le jour venu, si ce pipeline a le droit de parler au nom d'un
département : qui est la voix, est-elle consentie, le moteur est-il sous licence pour CE client, a-t-il réellement été
testé, et que peut faire la session (jamais plus qu'un humain n'a approuvé).

## Matrice de licences par composant

Tirée de la recherche R1 (`recherche/R1-AVATARS-VOIX.md`, §3-§9) et de la feuille de route (tableau A, § B.2). Niveaux de preuve
de R1 : **[V]** vérifié sur la source, **[S]** source secondaire, **[H]** hypothèse. Les composants de transport n'ont pas
de capacité dans le registre de fournisseurs (`CAPACITES` : llm, embeddings, reranker, ocr, stt, tts, avatar, image, video,
recherche_web) : leur licence vit dans ce tableau, pas dans le registre. « Catalogue » = identifiant dans
`src/opsys/fournisseurs/catalogue.py`.

| Composant | Rôle | Licence du code | Licence des poids | Décision | Catalogue / remarque |
|---|---|---|---|---|---|
| LiveKit server | SFU WebRTC | Apache-2.0 [V] | sans poids | Adopté | image arm64 [V] ; hors registre |
| LiveKit Agents | orchestration voix (Python) | Apache-2.0 [V] | sans poids | Adopté | v1.8.10 (2026-10-28) [V] ; hors registre |
| LiveKit SIP | téléphonie de Léa | Apache-2.0 [V] | sans poids | Adopté (plan) | trunk canadien à choisir (inconnu n° 7) |
| Détecteur de fin de tour LiveKit | tour de parole | LiveKit Model License | « seulement avec LiveKit Agents » [V] | **Non retenu** | enferme dans LiveKit ; Smart Turn à la place |
| Silero VAD | détection de parole | MIT [V] | MIT | Adopté | CPU ; hors registre |
| Smart Turn v3 (Pipecat) | fin de tour, 23 langues dont fr | BSD-2 [V] | BSD-2 [V GitHub ; S HF] | Adopté | hors registre |
| Pipecat | orchestration de repli | BSD-2 [V] | sans poids | Repli | même transport LiveKit possible |
| Voxtral Mini 4B Realtime | STT temps réel | Apache-2.0 (vLLM) | Apache-2.0 [V] | Adopté | `stt.voxtral-mini-realtime.local` ; GPU ≥ 16 Go ; WER fr-CA inconnu |
| Kyutai STT 1B en_fr | STT de repli | MIT / Apache | **CC-BY-4.0** [V] | Repli | `stt.kyutai-stt.local` ; mention obligatoire (page Crédits) |
| Parakeet TDT 0.6B v3 | STT en lot | Apache-2.0 (NeMo) | **CC-BY-4.0** [V] | Repli | `stt.parakeet-tdt-v3.local` ; mention obligatoire |
| pyannote community-1 | diarisation (lot) | MIT | **CC-BY-4.0**, accès contrôlé [V] | Repli | `stt.pyannote-community-1.local` ; diarisation sans nom ≠ identification |
| Chatterbox Multilingual V3 | TTS + clonage zéro-shot | MIT [V] | MIT [V] | Adopté | `tts.chatterbox-multilingual.local` ; filigrane Perth ; voix québécoises SOUS CONTRAT |
| Kyutai TTS 1.6B en_fr | TTS de repli | MIT / Apache | **CC-BY-4.0** [V] | Repli | `tts.kyutai-tts.local` |
| Azure Neural TTS fr-CA | TTS API de repli | propriétaire (API) | — | Repli | `tts.azure-fr-ca.api` ; sur contrat ; **EFVP (Loi 25)** : transfert hors Québec |
| XTTS-v2 (Coqui) | TTS | MPL-2.0 | **CPML, non commercial, sorties comprises** [V] | **Écarté** | `tts.xtts-v2` |
| F5-TTS (poids) | TTS | MIT | **CC-BY-NC-4.0** [V] | **Écarté** | `tts.f5-tts` |
| Voxtral TTS 2603 (local) | TTS | Apache-2.0 (vLLM) | **CC-BY-NC-4.0** [V] | **Écarté** | `tts.voxtral-tts.local` ; seule l'API Mistral est commerciale |
| Fish Speech / OpenAudio | TTS | Fish Audio Community License | idem | **Écarté** | `tts.fish-speech` ; plafond 500 k$ US de revenus ; services hébergés interdits |
| Piper | TTS | **GPL-3.0** (piper1-gpl) | voix `tom` AGPLv3, `upmc` CC-BY-SA [V] | Non intégré | seulement en processus séparé et documenté (DECISIONS r1 §7) |
| TalkingHead (three.js) | visage 3D, rendu sur l'appareil | MIT [V] | sans poids | Adopté | `avatar.talkinghead` ; avatars d'exemple `brunette.glb` (CC-BY-NC) et `avatar.glb` (non commercial) **exclus** ; GLB propres à commander |
| Audio2Face-3D | visage premium (GPU) | MIT (SDK) [V] | NVIDIA Open Model License [V] | Repli | `avatar.audio2face-3d.local` ; aarch64/GB10 INCONNU ; Audio2Emotion : licence propre |
| MuseTalk 1.5 | visage vidéo 2D (GPU) | MIT [V] | « any purpose, even commercially » [V] | Repli | `avatar.musetalk-1.5.local` ; licence S3FD inconnue ; données de test non commerciales à ne pas embarquer |
| NVIDIA ACE complet (Tokkio, NIM) | pile intégrée | NVAIE | — | **Écarté** | `avatar.nvidia-ace-complet` ; NVAIE requis ; pas de fr-CA |
| Wav2Lip, InsightFace (LivePortrait), SadTalker (BFM), Duix | visage | divers | **non commerciaux** ou discrétionnaires [V]/[H] | **Écartés** | `avatar.wav2lip`, `avatar.insightface`, `avatar.sadtalker`, `avatar.duix` |

Garde-fou en code : `registre.lier_runtime` refuse un moteur dont `statut_catalogue = ecarte`
(`REJ-AVATAR-LICENCE-NON-CONFORME`) ; la politique rejoue `fournisseurs.politique.evaluer` à chaque lecture (seuil de
revenu, territoires, service à des tiers, copyleft, mention, EFVP, licence non lue).

## Le registre (migration 0039)

Quatre tables, préfixe `avatars_` (schéma : `src/opsys/stockage/schema.py`) :

| Table | Contenu | Garde |
|---|---|---|
| `avatars_entrees` | une ligne par identifiant LOGIQUE (`voix.lea.defaut`) : genre, langue (défaut `fr-CA`), accent, origine (`generique`, `clonee`, `ressemblance`), moteur lié (clé étrangère vers `fournisseurs_configurations`), manifeste figé et **empreinte SHA-256**, état `prevu` / `configure` / `qualifie`, drapeau d'empreinte vocale de tiers et sa déclaration | CHECK : `prevu` ⇔ aucun moteur ; origine permise par genre |
| `avatars_consentements` | consentement **écrit** : référence pseudonyme du locuteur, portée, référence et empreinte du contrat signé, signature, expiration, révocation | déclencheurs : ni modification ni suppression ; une seule révocation, irréversible |
| `avatars_qualifications` | chaque test de connexion exécuté : quand, qui, moteur, **empreinte du moteur testé**, `nature` (`reel` ou `double`), statut, détail masqué, latence | append-only (déclencheurs SQLite et PostgreSQL) |
| `avatars_canaux` | la décision « disponible » d'un département pour `voix` ou `audiovisuel`, avec les preuves | état effectif **recalculé** à chaque lecture |

La licence du code et celle des poids, les seuils de revenu, les territoires et le droit de service à des tiers
**vivent dans la définition du fournisseur** du registre 0037 ; ils ne sont pas recopiés. Le manifeste d'une entrée garde
ce qui identifie le moteur (modèle, mode, point d'accès, résidence des données, contrat, licence complète) ; son empreinte
sert à deux choses : la qualification est liée à CE moteur (un changement de modèle, de point d'accès ou de licence la
rend périmée, `REJ-AVATAR-MANIFESTE-MODIFIE`), et le consentement de départ se rattache à une entrée précise.

La rétrogradation (`alembic downgrade 0038`) est refusée dès qu'une ligne existe : elle détruirait des consentements ou la
preuve d'une qualification (suppression définitive = frontière humaine).

## La politique : quand un canal peut-il être « disponible » ?

`politique.evaluer_canal` (pure lecture) rend **tous** les refus applicables, dans l'ordre stable de `CODES_AVATAR`.
`politique.declarer_canal` n'écrit que si le verdict est conforme et rend sinon le verdict, journalisé, sans rien déclarer.

| Condition | Code(s) de refus |
|---|---|
| 0. un runtime de transport est livré pour ce canal (`avatars.CANAUX_REALISES`) | `REJ-AVATAR-CANAL-NON-REALISE` |
| a. entrée inscrite, moteur lié, de la bonne capacité (voix → `tts`, visage → `avatar`), **actif** | `…-ENTREE-ABSENTE`, `…-RUNTIME-ABSENT`, `…-RUNTIME-CAPACITE`, `…-RUNTIME-INACTIF` |
| a. moteur inchangé depuis la liaison | `…-MANIFESTE-MODIFIE` |
| a. test de connexion **réellement exécuté**, journalisé, réussi, sonde réelle | `…-QUALIFICATION-ABSENTE`, `…-ECHEC`, `…-SIMULEE` (un double de test ne qualifie jamais) |
| a. pour la voix : un STT sélectionné pour le département, actif, conforme, qualifié | `…-STT-INDISPONIBLE` et les codes de qualification (composant `stt`) |
| b. voix clonée ou ressemblance : consentement écrit, non révoqué, non expiré, portée suffisante | `…-CONSENTEMENT-ABSENT`, `-REVOQUE`, `-EXPIRE`, `-PORTEE` (`-NON-ECRIT` à l'enregistrement) |
| c. licence conforme au profil du client (moteur de `fournisseurs.politique`) | `REJ-AVATAR-LICENCE-NON-CONFORME` avec les sous-codes (`SEUIL_REVENU_DEPASSE`, `TERRITOIRE_EXCLU`, `SERVICE_TIERS_INCERTAIN`...) |
| d. empreinte vocale de tiers : déclarée à la CAI, 60 jours avant la mise en service | `…-BIOMETRIE-NON-DECLAREE` (refus par défaut), `…-BIOMETRIE-DELAI` |
| langue de la voix = `fr-CA` ; actif visuel à usage commercial autorisé | `…-LANGUE`, `…-ACTIF-NON-COMMERCIAL` |

Règles qui en découlent :

- **Aucune voix clonée sans consentement** : `lier_runtime` refuse de relier un moteur à une entrée `clonee` ou
  `ressemblance` sans consentement valide ; la politique le revérifie à chaque lecture.
- **Révocation immédiate** : un canal déclaré `disponible` devient `suspendu` dès qu'un consentement est révoqué (état
  recalculé), et `GestionnaireSessions.reverifier` ferme les sessions en cours.
- **Aucun repli** : un refus ne propose jamais un autre moteur ; c'est à l'administrateur de choisir.
- **Défaut rétrocompatible** : les `voix`/`visage` logiques de `department.yaml` et de `entreprise.yaml` ne changent pas ;
  les canaux du manifeste restent `messagerie: disponible`, `voix` et `audiovisuel: prevu`. Les tests d'avatars et de la
  projection dans le core sont inchangés. L'état effectif du registre se lit à côté, jamais à la place.
- **États d'un canal à la lecture** : `disponible` (décision + politique tenue), `suspendu` (décision, politique rompue),
  `qualifie`, `configure`, `prevu` (d'après le plus faible des composants).

Tant que `CANAUX_REALISES` ne contient que `messagerie`, la politique rend `REJ-AVATAR-CANAL-NON-REALISE` : **aucun
avatar ne peut être déclaré voix ou audiovisuel disponible dans le produit actuel**, quel que soit le registre. Cette
constante s'élargit dans le même diff que le worker vocal et sa preuve (AVATARS.md, « Étapes suivantes »).

### Loi 25 et droit québécois (à valider)

- **Voix et ressemblance** : consentement écrit, précis, révocable et contrat de comédien (C.c.Q. art. 35-36, **[H] non
  relu**). Le registre ne garde que la référence et l'empreinte du contrat.
- **Biométrie** : une banque de caractéristiques biométriques se déclare à la CAI **au moins 60 jours** avant sa mise en
  service (R1 §4, **[S]**). Une voix clonée à partir d'un enregistrement d'un tiers, ou toute identification du locuteur,
  entre dans cette règle. Par défaut : refus. La session voix interdit en plus d'ouvrir une identification du locuteur
  (`REJ-VOIX-BIOMETRIE-INTERDITE`).
- **Divulgation d'une IA** : annoncée à l'ouverture (bonne pratique [H] ; obligation légale précise à confirmer).
- Mention : **À valider auprès d'un avocat ou d'une avocate qualifié(e) (droit québécois de la vie privée)** avant toute
  mise en service avec de vraies personnes.

## Le contrat de session voix (`session.py`)

Code pur : aucun réseau, fichier, horloge, base ni modèle (le test `test_le_contrat_de_session_est_pur…` lit les
imports). Le futur worker pilote le contrat par des événements horodatés (`t`) et applique les `ordres` rendus.

États : `ouverte`, `tour_utilisateur`, `tour_avatar`, `interruption` (barge-in), `transfert_humain`, `fin`. La table des
transitions légales est épinglée par un test qui l'écrit à la main ; les 60 couples état × événement sont éprouvés (les
absents sont refusés sans changer l'état).

| Règle | Détail |
|---|---|
| **Divulgation d'abord** | le premier acte est la divulgation canonique (« assistant virtuel », « intelligence artificielle », « pas une personne », enregistrement désactivé, humain joignable), produite par `texte_divulgation`, jamais par un modèle. Interrompue, elle est à refaire en entier. Avant qu'elle soit livrée : ni parole, ni action, ni consentement (`REJ-VOIX-DIVULGATION-REQUISE`). |
| **Autorité** | l'avatar annonce et propose. Une action demandée à voix passe par le registre d'outils pour son niveau : N0-N2 exécutées par le registre sous sa propre gouvernance ; **N3 et plus : mises dans le sas d'approbation existant (`approbations.creer_demande`), jamais exécutées**, même si le département est en mode `autonome` (où le registre laisserait passer N3 et N4). Le niveau vient du registre d'outils, pas de la parole. Le pont (`actions.py`) ne contient aucun appel à `decider` ni à `executer_atomique` (test par lecture du code). |
| **Honnêteté** | l'avatar ne peut pas présenter comme faite une action en attente ou refusée (`REJ-VOIX-AFFIRMATION-NON-FONDEE`, heuristique de complément) ; une double soumission rappelle la demande en attente au lieu d'en créer une seconde. |
| **Enregistrement** | désactivé par défaut. Seul `consentir_enregistrement` (réponse explicite, après la divulgation) l'active, avec rétention de 1 à 90 jours (`REJ-VOIX-RETENTION-INVALIDE`) ; une transcription qui « dit oui » ne l'active pas ; `retirer_enregistrement` demande la purge. Le journal ne garde jamais le texte de l'utilisateur (longueur seulement) ni les arguments d'une action (empreinte seulement). |
| **Biométrie** | aucune identification du locuteur par empreinte. |
| **Limites** | durée maximale (30 s à 3 600 s, défaut 900 s), tours de l'avatar, actions par session, sessions simultanées par département et au total, sessions par jour par département (`GestionnaireSessions`, en mémoire). Une limite atteinte termine la session. |
| **Transfert à un humain** | légal à tout moment avant la fin ; ensuite l'avatar se tait. |
| **Canal** | aucune session ne s'ouvre si le verdict de la politique pour le canal n'est pas conforme. |

## Lecture admin

- `opsys-metier avatars etat [--departement ID] [--json]` : pour chaque avatar, messagerie (manifeste), voix et audiovisuel
  (politique) et les codes `REJ-AVATAR-…` qui manquent.
- `opsys-metier avatars registre [--json]` : le registre des voix et visages du client.
- Console : **Plateforme > Avatars** (`/plateforme/avatars`, `/api/plateforme/avatars`), même garde que le reste de la
  Plateforme (session + rôle d'administration relu en base, `Cache-Control: no-store`). Lecture seule.
- Aucun outil de département n'est ajouté, aucun droit d'appareil n'est élargi, les compteurs de [ROLES.md](ROLES.md)
  sont inchangés. Les écritures (inscrire une entrée, enregistrer ou révoquer un consentement, qualifier, déclarer un
  canal) passent par `opsys.avatars_voix.registre` et `politique` (administration authentifiée, journalisées au journal
  d'audit) ; **aucune commande d'écriture n'est exposée en CLI ni en console** pour l'instant.

## Codes de refus

`REJ-AVATAR-…` (registre et politique) :

| Code | Sens |
|---|---|
| `REJ-AVATAR-ADMIN-REQUIS` | écriture sans personne active `nathan_owner`/`admin` |
| `REJ-AVATAR-IDENTIFIANT-INVALIDE` | identifiant logique mal formé |
| `REJ-AVATAR-DECLARATION-INVALIDE` | champ invalide (langue, origine, portée, date, empreinte, motif...) |
| `REJ-AVATAR-CONFLIT-REVISION` | révision optimiste dépassée |
| `REJ-AVATAR-ENTREE-INCONNUE` | entrée absente du registre |
| `REJ-AVATAR-CONSENTEMENT-INCONNU` | consentement absent |
| `REJ-AVATAR-CONSENTEMENT-DEJA-REVOQUE` | révocation déjà faite |
| `REJ-AVATAR-RUNTIME-INCONNU` | fournisseur inconnu ou non configuré |
| `REJ-AVATAR-CANAL-INCONNU` | canal hors `voix`/`audiovisuel` |
| `REJ-AVATAR-CANAL-NON-REALISE` | aucun runtime de transport livré pour ce canal |
| `REJ-AVATAR-ENTREE-ABSENTE` | voix ou visage non inscrit |
| `REJ-AVATAR-RUNTIME-ABSENT` | aucun moteur lié |
| `REJ-AVATAR-RUNTIME-CAPACITE` | moteur de la mauvaise capacité |
| `REJ-AVATAR-RUNTIME-INACTIF` | moteur configuré mais non activé |
| `REJ-AVATAR-STT-INDISPONIBLE` | aucun STT utilisable pour le département |
| `REJ-AVATAR-MANIFESTE-MODIFIE` | moteur changé depuis la liaison |
| `REJ-AVATAR-QUALIFICATION-ABSENTE` | aucun test exécuté sur ce moteur |
| `REJ-AVATAR-QUALIFICATION-ECHEC` | dernier test échoué ou non vérifiable |
| `REJ-AVATAR-QUALIFICATION-SIMULEE` | dernier test réussi seulement avec un double |
| `REJ-AVATAR-CONSENTEMENT-ABSENT` | voix clonée ou ressemblance sans consentement |
| `REJ-AVATAR-CONSENTEMENT-REVOQUE` | tous les consentements révoqués |
| `REJ-AVATAR-CONSENTEMENT-EXPIRE` | tous les consentements expirés |
| `REJ-AVATAR-CONSENTEMENT-PORTEE` | portée consentie insuffisante |
| `REJ-AVATAR-CONSENTEMENT-NON-ECRIT` | consentement verbal ou non écrit |
| `REJ-AVATAR-LICENCE-NON-CONFORME` | le moteur de politique de licence refuse (sous-codes) ou moteur écarté |
| `REJ-AVATAR-BIOMETRIE-NON-DECLAREE` | empreinte vocale de tiers sans déclaration (Loi 25) |
| `REJ-AVATAR-BIOMETRIE-DELAI` | déclaration trop récente (60 jours) |
| `REJ-AVATAR-ACTIF-NON-COMMERCIAL` | actif visuel sans usage commercial autorisé |
| `REJ-AVATAR-LANGUE` | voix hors `fr-CA` |

`REJ-VOIX-…` (session) :

| Code | Sens |
|---|---|
| `REJ-VOIX-CANAL-NON-DISPONIBLE` | la politique du canal n'est pas conforme |
| `REJ-VOIX-PARAMETRES-INVALIDES` | paramètres ou limites hors bornes |
| `REJ-VOIX-BIOMETRIE-INTERDITE` | identification du locuteur demandée |
| `REJ-VOIX-QUOTA-SIMULTANE` | trop de sessions ouvertes |
| `REJ-VOIX-QUOTA-JOUR` | trop de sessions dans la journée |
| `REJ-VOIX-QUOTA-TOURS` | tours de l'avatar épuisés |
| `REJ-VOIX-QUOTA-ACTIONS` | actions de la session épuisées |
| `REJ-VOIX-DUREE-MAX` | durée maximale dépassée |
| `REJ-VOIX-TRANSITION-ILLEGALE` | événement illégal dans cet état |
| `REJ-VOIX-SESSION-TERMINEE` | session finie |
| `REJ-VOIX-HORLOGE-INVALIDE` | `t` invalide ou qui recule |
| `REJ-VOIX-TEXTE-INVALIDE` | texte vide, trop long ou de mauvais type |
| `REJ-VOIX-DIVULGATION-REQUISE` | divulgation non livrée |
| `REJ-VOIX-ENREGISTREMENT-NON-CONSENTI` | enregistrement non consenti ou portée invalide |
| `REJ-VOIX-RETENTION-INVALIDE` | rétention hors de 1 à 90 jours |
| `REJ-VOIX-AFFIRMATION-NON-FONDEE` | l'avatar prétend avoir fait une action en attente |
| `REJ-VOIX-ACTION-INCONNUE` | outil absent du registre |
| `REJ-VOIX-ACTION-HORS-PERIMETRE` | outil d'un autre département |
| `REJ-VOIX-ACTION-ARGUMENTS-INVALIDES` | arguments refusés par le schéma de l'outil |
| `REJ-VOIX-AUTORITE-CONTOURNEE` | le sas n'a pas confirmé la mise en attente (échec fermé) |

## Plan LiveKit / Agents (NON EXÉCUTÉ)

Ordre proposé, chaque étape avec ses critères de sortie (preuves exécutées, limites dites) :

0. **Conformité et actifs, avant le code** : EFVP Loi 25 (voix, enregistrement, transcription) ; politique de rétention ;
   contrats avec les comédiens québécois (licence de voix, cession pour le clonage, droit de retrait) ; commande des GLB
   sous licence commerciale ; décision consignée sur l'identification vocale ; jeu d'évaluation québécois consenti.
   → alimente `enregistrer_consentement` et `declarer_biometrie`.
1. **Qualification des moteurs sur la machine cible** (GB10) : compilation CUDA de vLLM/CTranslate2 pour sm_121 (inconnu
   n° 4), Voxtral, Chatterbox, Audio2Face-3D aarch64 (inconnu n° 3). Configurer un `point_acces` réel dans le registre de
   fournisseurs, puis `registre.qualifier` : un test réel remplace la sonde locale de ce dépôt.
2. **Mesure** sur le corpus fr-CA consenti : WER, accent, MOS, latence p50/p95, sessions simultanées (inconnus n° 1, 2, 5).
   La qualification de qualité n'existe pas encore dans ce code : elle exigera une colonne de mesure et un seuil, ajoutés
   avec la première mesure.
3. **Session LiveKit dans le gateway** : salle par conversation, jeton émis par le gateway, liaison à l'agent du
   département et aux **mêmes permissions que le chat** ; le gateway instancie `GestionnaireSessions` avec la politique
   réelle comme `verifier_canal` et `PortCapacites` comme port d'actions.
4. **Worker vocal** (LiveKit Agents) : VAD → Smart Turn → STT → pont LLM du Core → TTS → visèmes ; applique les `ordres`
   du contrat (barge-in : couper la synthèse, vider le tampon, figer les visèmes en moins de 200 ms, cible [H]).
5. **Rendu TalkingHead** dans la console web, puis Expo (development build, pas Expo Go).
6. **SIP pour Léa** : trunk canadien, divulgation d'ouverture, DTMF, transfert humain (SIP REFER).

À chaque étape livrée, `CANAUX_REALISES` s'élargit **dans le même diff que la preuve**, et la politique devient la seule
porte : un canal reste « prévu » tant que ses conditions ne tiennent pas.

## Limites (dites sans euphémisme)

- **La voix n'est pas prouvée de bout en bout.** Aucun son n'a été produit, reconnu ni transporté. Aucun worker, aucun
  appel LiveKit, aucun modèle, aucune ligne SIP n'existe dans ce dépôt.
- « Qualifié » = un test de connexion réel local (ou un point d'accès qui répond), journalisé. Pas une qualité vocale, pas
  un accent québécois mesuré, pas une latence.
- La `nature` (`reel` / `double`) d'une sonde est déclarée par le code appelant : c'est une garde de gouvernance contre
  l'étourderie, pas une preuve cryptographique ; un développeur qui injecte un double sans le déclarer n'est pas détecté
  (la fonction `qualifier` marque `double` dès qu'une sonde est injectée).
- La sonde réelle HTTP n'a jamais été exécutée contre un vrai moteur vocal ; seule la sonde `module:` (présence d'un module
  Python) a tourné, sur des moteurs fictifs. Un moteur rendu sur l'appareil (`appareil:`, TalkingHead) est `non_verifiable`
  côté serveur : il ne peut pas être qualifié par ce mécanisme, donc le canal audiovisuel de TalkingHead ne peut pas être
  déclaré disponible tant qu'une attestation d'appareil n'existe pas.
- Les règles de droit (60 jours, consentement, divulgation) sont reprises de R1 **[S]/[H]**, jamais validées par un juriste.
- Le consentement est une référence à un contrat signé : le registre ne vérifie ni le document ni l'identité du
  signataire. L'empreinte du document sert à détecter une substitution, pas à prouver une signature.
- Le détecteur d'affirmation (« c'est fait ») est une heuristique lexicale en français ; sa garde de fond est que rien
  n'est exécuté sans décision.
- Le gestionnaire de sessions est en mémoire (aucune persistance, aucun partage entre processus) : les quotas ne tiennent
  que dans un seul processus. La persistance viendra avec le gateway.
- Le nom d'entreprise de la divulgation est fourni par l'appelant ; l'enregistrement effectif et la purge selon la
  rétention sont des **ordres** que le worker devra exécuter (rien ne les exécute ici).
- Aucune écriture n'est exposée en CLI ni en console ; les mutations ne sont atteignables que par le code.
- PostgreSQL : les déclencheurs de la migration 0039 sont écrits pour PostgreSQL mais n'ont pas été exécutés ici
  (aucune instance PostgreSQL dans cette preuve) ; seule la voie SQLite a tourné.
