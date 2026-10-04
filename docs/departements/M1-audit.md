# Audit M1 — Front Office IA

> Audit historique du 28 septembre 2026, conservé pour traçabilité. Les évolutions ultérieures
> ne sont pas inventoriées ici. Consulter le [plan de consolidation](../programme/RESTRUCTURATION-2026-09-30.md)
> et les [recherches actuelles](../research/R16-2026-09-30/README.md) pour M1/M5/M7/M10. Un statut
> ancien et un nombre de tests ne certifient pas le périmètre cible complet.

## Mise à jour du 30 septembre 2026 — adaptateur de voicemail

Un adaptateur Python `m1_front_office.voicemail_stt` accepte des octets audio déjà lus et une
extension validée, contrôle taille/durée, envoie le média à un endpoint STT OpenAI-compatible
configuré par l'opérateur, puis appelle `m1_importer_appel_manuellement`. Il n'écrit pas l'audio,
exige le consentement d'enregistrement avant l'envoi et exige un accord distinct si l'endpoint
n'est pas configuré local. Si le consentement, la configuration, l'endpoint ou la réponse manque,
l'import canonique reçoit l'appel sans transcription et conserve le chemin de rappel M1. Un diagnostic
HTTP est seulement indicatif; `/models` n'est pas requis et ne prouve pas que la transcription marche.

Le test utilise un serveur local OpenAI-compatible avec une réponse de transcription fictive
explicitement identifiée par les fixtures; aucun fournisseur STT réel, clé de production, canal
téléphonique ou chargement sécurisé de fichiers n'a été validé. Le module n'est pas encore câblé à
une route d'upload ni au runtime `voice-call`; un intégrateur doit faire la lecture bornée du fichier
et passer les octets. Les tests M1 ciblés couvrent le succès via l'import canonique, le rejeu, les
refus de consentement, les échecs STT et la durée. Cette tranche rend le point d'adaptation utilisable,
mais ne livre pas M1.5 complet ni une réception vocale opérationnelle. Vérification du 30 septembre :
la suite `departments/m01-front-office/tests` passe après actualisation de trois attentes historiques
de statut d'approbation refusée; Ruff passe sur les fichiers Python touchés.


**Date de l'audit :** 2026-09-28. **Portée :** `departments/m01-front-office/` seulement, en lecture.
**Référence produit :** `docs/produit/DEFINITION-PRODUIT.md` §1, §5, §6, §7 (M1), §8, §9, §10, §13.
**Méthode :** lecture intégrale des 12 modules de `src/m1_front_office/`, des 11 fichiers de tests, des
2 contrats gelés, des 2 skills, des 3 docs BMAD (brief/PRD/architecture), de `docs/research/R6-m1-m2.md`
et `INGREDIENTS.md` (déjà datés du jour), du socle `src/opsys/`, de `core/UPSTREAM.md`,
`docs/architecture/MOBILE.md`, des politiques `docs/compliance/politiques/*.md`, et du clone superficiel
d'OpenClaw (`extensions/`, `docs/channels`, `docs/web/webchat.md`). Une seule commande de test exécutée
(voir PREUVE) ; recherche web ciblée pour compléter R6. Aucun fichier modifié hors ce document.

**Verdict global.** La **fondation** de M1 (registre anti-perte hash-chaîné, machine à états des phases
voix 0→5, garde-fou déterministe des interdits absolus, filtre de provenance anti-injection R-015,
consentement fail-closed, deux contrats gelés) est nettement plus solide et testée (366 tests, 100 %
verts) que ce que l'étiquette `STUB` de juin 2026 dans `DEFINITION-PRODUIT.md` §7 laisse deviner. Mais
c'est une **couche de garde-fous et de FSM en mode ombre, pas encore un front office qui reçoit de
vraies demandes** : aucun canal réel n'est câblé, le lead qualifié produit n'est jamais transmis à M2
(confirmé aussi côté M2, `docs/departements/M2-audit.md` §2), et 9 des 13 fonctions M1.1–M1.13 n'ont
aucun code. Découverte structurante : OPSYS-CORE (le fork OpenClaw épinglé) fournit déjà, sans code
neuf, la quasi-totalité de la couche canal/voix que `docs/research/R6-m1-m2.md` proposait de reconstruire
avec Pipecat — l'écart réel est le **câblage**, pas l'absence de brique (§3).

---

## 1. Inventaire M1.1 – M1.13

| # | Fonction | Statut | Preuve (fichiers / tests) |
|---|---|---|---|
| M1.1 | Hub d'intake omnicanal | **PARTIEL** | `outils.traiter_demande_entrante()` (provenance→registre→consentement→qualification, une ligne registre garantie même si non qualifié, M1-R-10) ; `test_outils_agent.py` (24 tests). Aucun canal réel n'y envoie quoi que ce soit. |
| M1.2 | Agent vocal de réception | **PARTIEL** | `phases_voix.py` (FSM 0→5 strictement linéaire), `garde_fou.py`, `consentement.py` ; `test_phases_voix.py` (22), `test_garde_fou.py` (27+ def), `test_consentement.py` (14). Zéro STT/TTS/téléphonie réels — mais le fork fournit déjà `voice-call` non câblé (§3.1). |
| M1.3 | Qualification par service | **PARTIEL** | `qualification.py` (166 lignes, zéro LLM, zéro ville codée en dur) ; `test_qualification.py` (34 cas collectés). `type_travaux` = `renovation_totale/extension/ravalement/isolation_thermique/autre` — **ne couvre aucun des 4 services réels de GRS** (gouttières, revêtement, soffite/fascia, réparation). Pas de score de lead, pas de demande de photos. |
| M1.4 | Sauvetage d'appel manqué | **ABSENT** | `consentement.rescue_autorise()` existe (fail-closed, booléen strict) mais n'est appelée par aucun outil exposé ni aucun test d'intégration ; aucune détection d'appel manqué, aucune tâche de rappel. |
| M1.5 | Messagerie vocale intelligente | **ABSENT** | Aucune transcription/résumé/extraction depuis un fichier audio ; les fixtures partent d'un texte déjà transcrit. |
| M1.6 | Tri des courriels | **ABSENT** | `qualification.py` ne catégorise pas (facture/fournisseur/plainte/spam/emploi/partenariat) ; extrait seulement type de travaux/ville/urgence/contact. |
| M1.7 | Assistant SMS/messages (opt-in) | **ABSENT** | Aucun opt-in SMS distinct du consentement voix ; aucune table de consentement, aucune gestion STOP. |
| M1.8 | Bureau des plaintes et escalades | **ABSENT** | Aucune détection d'intention « plainte », aucun gabarit de ton dédié, aucune escalade codée (le garde-fou bloque bien les aveux de responsabilité, ce qui est un prérequis mais pas la fonction elle-même). |
| M1.9 | Rappels et rendez-vous (via M4) | **ABSENT** | Aucun appel à M4 (lui-même `STUB` selon §11). |
| M1.10 | Statut aux clients existants | **ABSENT** | Aucun pont de lecture vers M2/M3/M5. |
| M1.11 | Adjointe administrative (digest) | **PARTIEL** | `digest.py` (75 lignes, sortie byte-identique, filtrée par `date_reference`) ; `test_digest.py`. Câblé à la planification `digest-front-office` (`department.yaml`, cron `0 7 * * 1-5`). Contenu = compteurs canal×type_entree, pas « leads sans suivi » ni « documents manquants ». |
| M1.12 | Transfert humain avec contexte | **ABSENT** | Aucun outil, aucune typologie de transfert (ventes/estimation/admin/finance/plainte/urgence/technique/propriétaire). |
| M1.13 | Boucle d'apprentissage | **ABSENT** | Aucune mesure de temps de réponse, de conversion ni de question fréquente. |
| — | Contrats gelés M1↔M2/M3 | **PARTIEL** | `contrats.py` (149 lignes) valide les deux schémas ; seul `LeadQualifie` est réellement produit par le pipeline. `DemandeChiffrage` (M1↔M3) n'est jamais émis : `qualifier()` ne construit pas de `description_factuelle`. |
| — | Câblage M1 → M2 (`m2_ingerer_lead`) | **ABSENT** | Confirmé dans les deux sens : `docs/departements/M2-audit.md` §2 constate par `grep` qu'aucun outil M1 n'appelle `m2_ingerer_lead` ; côté M1, aucune référence à M2 dans `src/m1_front_office/`. |
| — | M6.6 — courriel de bon de commande via M1 | **ABSENT** | Aucune référence à M6 dans le code M1. |

Chiffres vérifiés : 12 fichiers `src/m1_front_office/*.py` (2 006 lignes) ; 11 fichiers de tests
(3 574 lignes) ; **366 tests exécutés, 0 échec** (voir PREUVE — le `README.md` du département annonce
« 331 tests », chiffre périmé) ; 10 outils agent dans `outils()` ; 2 skills ; 2 contrats gelés ; 5
fixtures (`fictif: true`) ; 122 avertissements `ruff` (81 auto-corrigibles, surtout E501). Les 366 tests
couvrent fidèlement les 7 stories BMAD S001–S007 (mode ombre) — pas les fonctions produit M1.4–M1.10 et
M1.12–M1.13, qui n'existent simplement pas encore.

---

## 2. Écarts

### 2.1 Modèle de données

Entités présentes (dicts Python purs, non persistés) : signal entrant (champs assemblés dans le
registre), `Conversation`/`Phase` (`phases_voix.py`), `LeadQualifie` (`contrats.py`), `EntreeRegistre`
hash-chaînée (`registre.py`). Champs manquants au regard du produit : score de lead (M1.3, M2.4),
confiance de transcription STT (§7 : « faible confiance de transcription → redemander »), type de
plainte/transfert, et surtout **`source`/`utm`/`campagne`** : §6 dit que M1 « reçoit de M7 (source, UTM,
campagne) », mais `contracts/m1-lead-qualifie.v1.yaml` ne porte aucun de ces champs. Corriger le contrat
gelé exige une v2 (règle P5 ; l'en-tête du fichier lui-même est explicite : « CONTRAT GELÉ — modification
interdite ; évolution = v2 »), jamais un patch in-place.

### 2.2 API

**ABSENTE.** Aucune route HTTP spécifique à M1. Le seul serveur web du socle
(`src/opsys/console/application.py`, FastAPI) expose Départements/Approbations/Budgets/Modèles
génériquement — rien sur le registre, les leads ou le digest de M1. La décision de l'ingénieur en chef
prévoit pourtant des moteurs « exposés aux agents comme outils et à l'app/dashboard par API » : ce second
contrat n'existe pas pour M1, seul le premier (outils MCP) est livré.

### 2.3 Événements (§6)

Pas de bus d'événements au niveau du Core : seuls les deux contrats dict (§2.1) tiennent lieu de message,
et un seul (`LeadQualifie`) est réellement produit. Aucune écriture M10 (P4 « mémoire avant, mémoire
après » non respecté), aucune métrique vers M8 malgré deux KPI déjà déclarés dans `department.yaml`
(`taux_signaux_qualifies_pct`, `taux_interdits_bloques_pct`), aucune réception réelle de M7
(`source`/`utm` absents du contrat, §2.1). `adaptateurs.py` simule un `BusNotifications` in-memory,
jamais un vrai canal — voir la nuance précise en §2.4.

### 2.4 Outils d'agent

10 outils bien formés (contrat `Outil` du socle : nom `m1_*`, schéma JSON validé, `Autonomie` déclarée),
tous testés par `test_outils_agent.py`. Répartition : 5 en `T0` (`m1_filtrer_provenance`,
`m1_qualifier_signal`, `m1_verifier_garde_fou`, `m1_verifier_consentement`, `m1_produire_digest`), 4 en
`T1` (`m1_traiter_demande_entrante`, `m1_ouvrir_conversation`, `m1_transitionner_phase`,
`m1_abandonner_conversation`), 1 en `T2` (`m1_emettre_notification`).

**Trouvaille précise.** Le socle a une vraie file d'approbation persistée (`src/opsys/approbations.py`,
SQLite) et un vrai gate transport (`src/opsys/capacites.py::Capacites.appeler()`, ligne 153,
`approbation_requise(outil.autonomie, mode)`) qui intercepte déjà tout outil `T1+` d'un département en
mode `ombre` (le mode déclaré par `department.yaml` de M1) **avant** que le code du département
s'exécute, et le rend visible dans la file générique du dashboard
(`tableau_de_bord.lister_approbations`/`decider_approbation`). M1 n'a donc **pas besoin** de son propre
moteur d'approbation. Mais `test_outils_agent.py` importe `opsys.outils.executer` (l'exécuteur nu, sans
gate) et `opsys.departements.lire_manifeste`, jamais `opsys.capacites.Capacites` — **aucun test, ni dans
M1 ni dans `tests/` du socle, ne vérifie que les outils M1 traversent réellement ce gate** quand ils sont
appelés par le vrai point d'entrée MCP. Par ailleurs, une fois `m1_emettre_notification` approuvé,
l'exécution retombe sur le faux bus in-memory de `adaptateurs.py` (`creer_bus`) : rien n'est envoyé à un
canal réel. L'écart n'est donc pas l'approbation (déjà réglée au socle) mais (a) la preuve d'intégration
du gate et (b) l'envoi réel après approbation. Manquent aussi : outils plainte/transfert, outil de
lecture de statut (M2/M5), outil rescue.

### 2.5 Écrans mobiles par profil (§9.3–9.6)

**ABSENTS.** `docs/architecture/MOBILE.md` Phase 1 (sans développement) ne prévoit pour M1 que « Talk /
mot d'éveil vers l'agent M1 » via l'app officielle OpenClaw repackagée comme nœud — aucun écran dédié. Sa
Phase 2 (fork rebrandé, non commencée) ne sketche qu'un seul écran « Réception : file des demandes »,
bien en-deçà de la spec produit : inbox omnicanal, appels manqués, plaintes, transferts, « prendre en
charge »/« rappeler »/« envoyer la réponse approuvée » (admin) ; leads + résumé de conversation
(vendeur) ; signaler une info client ou une plainte terrain (employé) ; soumettre une demande, envoyer
des photos, voir le statut (client). Écart d'ambition à trancher explicitement avec Nathan avant
d'investir dans la Phase 2 mobile (voir §5).

### 2.6 Vues du dashboard

**ABSENTES.** `src/opsys/tableau_de_bord.py` n'expose que des vues génériques par département (statut,
mode, budget, paliers, file d'approbation) — aucune vue du registre, du digest ou des leads captés par
M1.

### 2.7 Portes fermées et replis (§10)

| Porte | État réel |
|---|---|
| Identifiants Twilio, SIP réel | Coût d'ouverture réduit : `extensions/voice-call` et `extensions/sms` du fork OpenClaw (MIT, déjà vendorisés dans OPSYS-CORE) gèrent Twilio/Telnyx/Plivo/SMS — reste de la configuration et un compte, pas du code de téléphonie neuf. |
| Politique d'enregistrement d'appels | Rédigée (`docs/compliance/politiques/POLITIQUE-enregistrements-appels.md`) mais **statut « PROPOSITION », non validée par Nathan (T3)** ; le code (`consentement.verifier_consentement`) ne modélise qu'un booléen `accorde`/reste, pas l'annonce en début d'appel ni la désactivation en cours d'appel qu'exige la politique (§4 de la politique). |
| Opt-in SMS | Politique rédigée (`POLITIQUE-consentement-sms.md`), **non validée** ; aucun code (`consent_sms`, STOP, fenêtre de retrait 48 h). Canal SMS lui-même **désactivé par défaut** (feature-flag OFF, ADR-0003 Q3a, cité par la politique). |
| Repli manuel documenté | Absent. Le seul « repli » actuel est l'inertie du mode ombre (les adaptateurs in-memory échouent en `REJ-ADAPTATEUR-INDISPONIBLE` hors mode ombre) — aucune procédure manuelle écrite pour l'équipe si un canal réel est indisponible. |

### 2.8 E2E exigés par la « Preuve de complétion » (§7)

| Scénario attendu | État |
|---|---|
| Appel de soumission | PARTIEL — couvert en unitaire (`traiter_demande_entrante`), aucun scénario voix réel |
| Appel manqué | ABSENT |
| Courriel de revêtement | PARTIEL/à risque — « revêtement » n'est même pas dans l'enum `type_travaux` actuel (§1, §2.1) |
| Plainte | ABSENT |
| Demande de facture | ABSENT |
| Bac à sable vocal | ABSENT (aucun mode bac à sable avec faux clients) |

---

## 3. Briques

Le fork OpenClaw épinglé (`v2026.9.6`, MIT, `core/UPSTREAM.md`, vérifié le 2026-09-28) couvre déjà une
grande partie du besoin canal — **objectif ici : câbler, pas dupliquer.** `docs/research/R6-m1-m2.md`
(daté du jour même) a déjà vérifié la licence de chaque brique candidate en lisant son fichier `LICENSE`
brut ; les tableaux ci-dessous reprennent ses verdicts et les complètent par ce que le fork fournit déjà
— un angle que R6 n'avait pas couvert (il proposait de reconstruire un pipeline Pipecat sans avoir
inspecté `extensions/voice-call`, `extensions/sms` ni `extensions/imap`).

### 3.1 Déjà fourni par OPSYS-CORE (à configurer/brancher, aucune brique à ajouter)

| Besoin M1 | Fourni par le fork | Verdict |
|---|---|---|
| Téléphonie/SIP/appels | `extensions/voice-call` (Twilio, Telnyx, Plivo, mock ; transcription temps réel enfichable via `streaming.provider` ; TTS via config `tts` du core ; anti-rejeu webhook ; gestion du barge-in ; outil `voice_call`, actions `initiate_call/continue_call/speak_to_user/end_call/get_status`) | **ADOPTER** — configurer + brancher `phases_voix.transitionner()`/`garde_fou.verifier_sortie()`/`consentement.verifier_consentement()` comme hooks avant le nœud TTS |
| SMS/MMS | `extensions/sms` (Twilio, canal officiel) | **ADOPTER**, seulement après validation Nathan de la politique opt-in (§2.7) |
| WhatsApp, Telegram, Signal, MS Teams, Slack | `extensions/{whatsapp,telegram,signal,msteams,slack}` | **ADOPTER** (au-delà du besoin M1 immédiat de GRS) |
| Courriel entrant | `extensions/imap` (déclenche un agent lecteur isolé et restreint ; **ne renvoie pas de réponse**, lecture seule) | **ADOPTER** en amont de `provenance.filtrer()` ; prévoir un canal séparé pour la réponse sortante |
| TTS local gratuit (repli GPL-safe) | `extensions/tts-local-cli` (sous-processus générique, pas d'`import`) | **ADOPTER** — résout déjà la contrainte « Piper (`piper1-gpl`, GPL-3.0) jamais importé » sans code neuf |
| TTS/STT cloud déjà branchables | `extensions/{elevenlabs,deepgram,azure-speech,fish-audio-speech}` | Référence — voix Québec natives confirmées côté ElevenLabs (R6) ; à garder en option, pas par défaut (Loi 25, §3.2) |
| Chat interne opérateur | WebChat natif (`docs/web/webchat.md`) | Référence — chat de la Gateway pour l'opérateur, **pas** un widget public pour le site vitrine (§3.3) |

### 3.2 STT souverain (Loi 25), à brancher dans `voice-call`

Aucun des fournisseurs STT déjà branchables dans le fork (§3.1) n'est auto-hébergé : tous sont des
services SaaS hors Québec, ce qui déclenche une EFVP sous la Loi 25 pour tout flux voix qui y transite
(`docs/research/R6-m1-m2.md` §9). Le repli local reste donc à ajouter.

| Brique | Licence (vérifiée) | Version / maturité | Verdict |
|---|---|---|---|
| **faster-whisper** (SYSTRAN) | MIT (R6, lu sur `raw.githubusercontent.com`) | v1.2.1 (GitHub Releases, actif), ~25,6k★ (vérifié aujourd'hui) | **ADAPTER** — écrire un plugin OpenClaw fin exposant l'interface « realtime-transcription provider » attendue par `voice-call` ; le pipeline audio existe déjà dans le fork, inutile de reconstruire Pipecat |
| Checkpoint communautaire `whisper-large-v3-turbo-fr-quebecois` | licence du fine-tune non vérifiée ligne à ligne (dérivé Whisper) | publié 2026, WER 6,65 % sur du français québécois vs ~19,5 % pour un modèle générique (R6, arXiv 2508.21193) | **ADAPTER**, à valider sur un corpus interne avant mise en production |
| Deepgram / ElevenLabs / Azure Speech / Fish Audio (déjà dans le fork) | SaaS propriétaire | matures, prêts à l'emploi | **REJETER par défaut** pour la voix client — sortie de données hors Québec ; garder en filet de secours cloud si la charge locale sature (§9 R6) |

### 3.3 Canaux non couverts par le fork

| Brique | Licence | Version / maturité | Apport | Verdict |
|---|---|---|---|---|
| **Chatwoot CE** | MIT (cœur ; dossier `enterprise/` sous licence séparée, R6) | ~37k★, très actif | Widget web public (formulaire/webchat client, absent du fork — §3.1) + inbox omnicanale ; supporte aussi **Facebook Messenger et Instagram nativement** (vérifié aujourd'hui sur `developers.chatwoot.com` : guides de configuration dédiés ; migration Instagram-via-Facebook-Login annoncée en fin de vie à partir de la v4.1, à surveiller) | **ADOPTER en sidecar docker, jamais modifié** — ferme d'un coup formulaire web, Facebook et Instagram, les trois canaux du §7 M1 absents du fork |
| Google Business Profile (messagerie) | API Google, propriétaire | — | Aucune brique OSS mûre trouvée (ni R6 ni recherche complémentaire) ; volume attendu faible pour une PME régionale | **REJETER une brique dédiée** — intégration directe API si le volume le justifie un jour, sinon repli manuel documenté (réponse dans l'app GBP par un humain) |

### 3.4 Garde-fous et conformité (roadmap, hors chemin critique)

| Brique | Licence | Apport | Verdict |
|---|---|---|---|
| NeMo Guardrails (NVIDIA) | Apache-2.0 | second rail conversationnel (dérive de sujet/ton), cas ambigus seulement | **ADOPTER en option**, jamais sur le chemin bloquant des interdits absolus — `garde_fou.py` reste la référence gratuite et déterministe (R6 §2.8) |
| Microsoft Presidio + spaCy `fr_core_news_*` | MIT (les deux) | masquage des renseignements personnels dans les transcriptions stockées (renfort Loi 25) | **ADOPTER**, phase de renforcement, après la persistance du registre (§4 Phase 1) |

### 3.5 Pas des briques — correctifs de code internes

- **Persistance du registre** : pas une nouvelle dépendance, un second adaptateur PostgreSQL respectant
  l'interface déjà découplée de `Registre` (`ajouter/lire/tete/valider_chaine`) — PostgreSQL est déjà la
  base retenue par le projet (R6 §5.2).
- **Taxonomie `type_travaux`** alignée sur les 4 services réels de GRS : correctif de `qualification.py`,
  pas une brique.
- **Bascule de `m1_emettre_notification`** du faux bus in-memory vers un vrai canal du fork (§3.1) :
  câblage, pas une brique.

---

## 4. Plan de construction par phases

Chaque phase se rattache au flux principal de §6 (`M7 attire → M1 capte et qualifie → M2 structure`).
Chaque tâche est petite, testable, avec une commande de preuve exécutable.

### Phase 1 — Tranche verticale minimale : un canal réel jusqu'à M2

1. Câbler `extensions/imap` (déjà dans le fork) en amont de `provenance.filtrer()` : un courriel réel
   devient un `contenu_brut`. Preuve : test d'intégration avec une boîte de test, contenu qui ressort
   filtré et sain.
2. Écrire `RegistrePostgres` (même interface que `Registre`) ; remplacer le singleton mémoire
   `_registre` d'`outils.py`. Preuve : `valider_chaine()` verte après redémarrage du processus.
3. Corriger `qualification.type_travaux` sur les 4 services réels de GRS (gouttières, revêtement,
   soffite/fascia, réparation) et leurs synonymes courants. Preuve : `test_qualification.py` étendu,
   cas « revêtement » qui qualifie enfin.
4. Publier une v2 du contrat `m1-lead-qualifie` avec `source`/`utm`/`campagne` optionnels, sans casser
   la v1 (règle P5/BMAD §2). Preuve : `hash_contrat("m1-lead-qualifie.v2.yaml")` distinct, test
   consommateur vert sur les deux versions.
5. Câbler l'appel sortant vers `m2_ingerer_lead` (existe côté M2, jamais appelé — §1, §2.3, confirmé par
   `docs/departements/M2-audit.md` §2) depuis `traiter_demande_entrante` une fois `qualifie: true`.
   Preuve : test d'intégration M1→M2 nouveau, un lead réel traverse sans recopie manuelle,
   `accepte: true` des deux côtés.
6. Ajouter un test qui invoque un outil M1 `T1+` via `opsys.capacites.Capacites.appeler()` (pas
   `executer()` nu) et vérifie `statut: en_attente_approbation` (§2.4). Preuve : ce test, vert.

### Phase 2 — Qualité de qualification et score de lead

7. Score de lead simple par règles (urgence, ville, complétude du contact) — pas de ML au départ.
   Preuve : `test_qualification.py`, cas bas/moyen/haut.
8. Verdict de qualification nommant le champ manquant, au lieu du seul `REJ-QUALIF-INSUFFISANTE`
   global. Preuve : verdict qui identifie le champ précis dans chaque cas de fixture.

### Phase 3 — SMS avec opt-in réel + tri des courriels

9. Implémenter le gate opt-in SMS conforme à `POLITIQUE-consentement-sms.md` (table `consent_sms`,
   STOP, fenêtre de retrait 48 h) — **après validation écrite de Nathan (T3)** de cette politique
   (§2.7, §5). Preuve : test refusant tout envoi sans « accorde » daté ; test STOP qui coupe l'envoi
   suivant.
10. Câbler `extensions/sms` et brancher enfin `m1_emettre_notification` sur un vrai canal (§2.4).
    Preuve : SMS de test visible dans la file d'approbation réelle, jamais envoyé sans décision
    humaine.
11. Catégorisation des courriels (facture/fournisseur/plainte/spam/emploi/partenariat) au-dessus de
    `garde_fou.py`/`provenance.py` existants. Preuve : une fixture par catégorie, 100 % classées.

### Phase 4 — Voix (bac à sable avant client réel)

12. Écrire le plugin OpenClaw « realtime-transcription provider » pour faster-whisper + checkpoint
    québécois (§3.2) ; brancher `phases_voix.transitionner()` comme callback à chaque tour de
    `voice-call`. Preuve : appel simulé (provider `mock` de `voice-call`), 0 phase sautée sur 100 tours
    aléatoires.
13. Brancher `garde_fou.verifier_sortie()` juste avant le nœud TTS. **Après validation Nathan (T3)** de
    `POLITIQUE-enregistrements-appels.md`, implémenter l'annonce de début d'appel et la désactivation en
    cours d'appel (au-delà du simple booléen actuel de `consentement.py`). Preuve : aucun texte interdit
    ne sort en TTS sur le corpus adversarial existant (`fixtures/interdits/adversariaux.v1.yaml`).
14. Bac à sable avec faux clients, conforme à la montée en charge du §7 (audit → messagerie vocale →
    bac à sable → hors heures → live assisté → production). Preuve : E2E « bac à sable vocal » vert.

### Phase 5 — Plaintes, transfert humain, statut client

15. Détection d'intention « plainte » (règles, gabarit de réponse au ton empathique imposé) + outil
    `m1_escalader_plainte`. Preuve : fixture de plaintes, 100 % escaladées, garde-fou toujours vert
    (aucun aveu).
16. Outil `m1_transferer` avec typologie (ventes/estimation/admin/finance/plainte/urgence/technique/
    propriétaire) et résumé de conversation joint. Preuve : contexte non vide sur chaque transfert
    simulé.
17. Lecture seule de statut (pipeline M2, facture M5) dès que ces départements exposent les outils
    correspondants ; sinon repli explicite « je vais vérifier avec l'équipe » (jamais d'invention,
    P2).

### Phase 6 — Mémoire, métriques, apprentissage, mobile/dashboard

18. Écriture M10 après chaque décision significative (P4). 19. Émission réelle des deux KPI déjà
    déclarés dans `department.yaml` vers M8. 20. M1.13 : mesure du temps de réponse et des raisons de
    perte à partir du registre persistant. 21. Vue dashboard M1 (inbox, digest, plaintes) dans
    `tableau_de_bord.py`. 22. Écrans mobiles détaillés (Phase 2 de `MOBILE.md`) une fois l'ambition
    tranchée avec Nathan (§5).

---

## 5. Risques et points ouverts

- **Loi 25 / EFVP majeure non soldée.** Les deux politiques propres à M1 (enregistrements d'appels,
  SMS) restent au statut « PROPOSITION » — aucune ne doit être traitée comme validée avant l'écrit de
  Nathan (T3). Câbler la voix ou le SMS avant cette validation violerait P8.
- **Décalage de taxonomie métier.** `type_travaux` ne couvre aucun des 4 services réels de l'entreprise
  — risque silencieux de perte de leads si câblé tel quel sur un vrai canal (un courriel « revêtement »
  peut échouer la qualification aujourd'hui même).
- **Contrat gelé M1→M2 sans `source`/`utm`/`campagne`.** Bloque la boucle de rétroaction M1/M2→M7
  prévue en §6 tant qu'une v2 n'est pas publiée (§4 Phase 1, tâche 4).
- **Registre 100 % en mémoire.** Aucune donnée ne survit à un redémarrage du processus — ne pas
  dépasser le mode ombre/fixtures avant la persistance PostgreSQL (§4 Phase 1, tâche 2).
- **Consentement voix binaire.** Le code actuel ne modélise ni l'annonce en début d'appel ni la
  désactivation en cours d'appel qu'exige `POLITIQUE-enregistrements-appels.md` — écart politique/code à
  fermer avant toute captation réelle (§4 Phase 4, tâche 13).
- **Gate d'approbation non prouvé bout en bout.** Le socle gate déjà les outils `T1+` de M1
  (`capacites.py`, §2.4), mais aucun test existant ne l'exerce à travers ce chemin réel — risque qu'une
  régression future du socle passe inaperçue côté M1 faute de test d'intégration (§4 Phase 1, tâche 6).
- **Ambition mobile désalignée.** `docs/architecture/MOBILE.md` prévoit beaucoup moins d'écrans M1 que
  `DEFINITION-PRODUIT.md` §9.3–9.6 (un seul écran « Réception : file des demandes » vs. inbox/plaintes/
  transferts détaillés par profil) — à trancher explicitement avec Nathan plutôt que de laisser l'écart
  implicite jusqu'à la Phase 2 mobile.
- **Nom commercial non tranché** (point ouvert n° 4 de `DEFINITION-PRODUIT.md`) : affecte directement
  les scripts et gabarits de message que M1 enverra aux clients (SMS, courriels, annonces vocales).
- **Bilinguisme (P12).** `garde_fou.py` et `qualification.py` sont strictement en français ; aucun
  repli anglais n'existe si un client l'exige.
- **Code mort à ne pas laisser dériver.** `adaptateurs.py` (bus/approbation in-memory) et
  `consentement.conserver_enregistrement()` ne sont appelés par aucun outil exposé aujourd'hui — soit
  les brancher (§4 Phase 1/3), soit les retirer explicitement pour ne pas laisser croire qu'un canal réel
  existe déjà.
- **Hygiène lint.** 122 avertissements `ruff` (81 auto-corrigibles) à nettoyer avant le prochain commit
  (AGENTS.md : « Avant chaque commit : … `ruff check src tests` »).

---

PREUVE: `/opt/opsys-venv/bin/python -m pytest departments/m01-front-office/tests -q --import-mode=importlib -p no:cacheprovider`
→ **366 passed**, exit code 0 (0 échec, 0 erreur, sur 11 fichiers de tests). Vérification complémentaire en
lecture seule (non exigée mais utile à l'audit, aucun fichier modifié) :
`/opt/opsys-venv/bin/python -m ruff check departments/m01-front-office/src departments/m01-front-office/tests`
→ 122 erreurs, 81 auto-corrigibles, aucune bloquante. Comptages vérifiés par commande : `wc -l` sur
`src/m1_front_office/*.py` (2 006 lignes/12 fichiers) et `tests/*.py` (3 574 lignes/11 fichiers) ;
`grep -c 'nom="m1_'` sur `outils.py` (10 outils) ; `grep -rc "def test_"` sur `tests/*.py` (236 fonctions
de test, 366 cas réellement collectés une fois les fixtures paramétrées comptées). Lecture intégrale de
tous les modules `src/m1_front_office/{registre,contrats,phases_voix,garde_fou,qualification,provenance,
consentement,digest,adaptateurs,horodatage,verdicts,outils}.py`, des 11 fichiers de tests, des 2 contrats
gelés, des 2 skills, de `department.yaml`/`SOUL.md`/`README.md`, des 3 docs BMAD, de
`docs/produit/DEFINITION-PRODUIT.md` (intégral), de `docs/research/R6-m1-m2.md` et `INGREDIENTS.md`
(intégral), de `core/UPSTREAM.md`, `docs/architecture/MOBILE.md`, `docs/compliance/politiques/{POLITIQUE-
consentement-sms,POLITIQUE-enregistrements-appels}.md`, de `src/opsys/{outils,capacites,politiques,
approbations,tableau_de_bord,console/application}.py`, et de `docs/departements/M2-audit.md` §2 pour la
confirmation croisée de l'absence de câblage M1→M2. Extensions OpenClaw lues (README, et pour
`voice-call` la documentation de configuration complète) : `voice-call`, `sms`, `imap`, `whatsapp`,
`telegram`, `signal`, `msteams`, `slack`, `tts-local-cli`, `elevenlabs`, `deepgram` ; docs `docs/channels/
channel-routing.md`, `docs/web/webchat.md`. Recherches web complémentaires à R6 (déjà daté du jour même) :
licence et version de `faster-whisper` (GitHub, MIT, v1.2.1) ; support natif Facebook Messenger et
Instagram de Chatwoot CE (`developers.chatwoot.com`, guides de configuration dédiés, changement d'API
Instagram signalé à partir de la v4.1).
