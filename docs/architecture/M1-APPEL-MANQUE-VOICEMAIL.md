# M1 — Appel manqué complet (M1-C, M1.4) et messagerie vocale intelligente (M1-F, M1.5)

Statut (2026-11-03) : **livré et prouvé sur SQLite, avec des données fictives, le vrai registre anti-perte, le vrai bus,
le vrai sas d'approbation N4 et les vrais outils de M1.** Aucun fournisseur téléphonique, aucun envoi SMS, aucun STT réel.

> **Ce que ce document ne dit pas : que le téléphone ou le STT fonctionnent.** L'appel manqué est importé par l'hôte ou
> manuellement depuis un export nommé ; le message vocal est une transcription déjà produite (le plus souvent par un
> double STT local). Le brouillon SMS n'est pas une preuve de livraison : « envoyé » voudra dire « approuvé par une
> personne et remis au transport », jamais « reçu par le client ».

## 1. M1-C — appel manqué complet

### 1.1 Les pièces

| Pièce | Fichier | Rôle |
|---|---|---|
| Gabarit `sms_appel_manque` | `departments/m01-front-office/src/m1_front_office/gabarits.py` | Texte FIXE, variante `{entreprise}`, divulgation « assistant virtuel (intelligence artificielle) » + « Nous avons manqué votre appel » + STOP. Versionné, passé au garde-fou de sortie. |
| État SMS étendu | `assistant_sms.py` | Un appel entrant (`signal` de canal `telephone`) ouvre la fenêtre de réponse de 24 h au même titre qu'un SMS. `appel_manque_le` et `REJ-SMS-AUCUN-APPEL` empêchent d'utiliser ce gabarit sur une conversation sans appel. |
| Préparation à l'import | `outils._preparer_brouillon_appel_manque`, appelé par `_importer_appel` | Prépare le brouillon dans le registre `sms_assistant` par `assistant_sms_outils.preparer_message_sms`, donc avec TOUTE la gouvernance existante (STOP, fenêtre, un seul brouillon). |
| Demande N4 | `assistant_sms_outils.demander_envoi_sms` (existant) | Le brouillon est soumis au sas N4 (`m1_emettre_notification`) avec le TEXTE EXACT. Aucun envoi par l'outil d'import. |
| Clôture mesurée | `outils.consigner_contact_reussi` / `m1_consigner_contact_reussi` | Une PERSONNE déclare le contact réussi ; la tâche sort de « À voir » et le délai appel → décision est mesuré en secondes exactes. |
| Tests | `departments/m01-front-office/tests/test_appel_manque_complet.py` | 15 tests, dont STOP, numéro déjà retiré, rejeu, horodatage antérieur, transfert sans appel. |

Aucune migration : le registre `sms_assistant` existe. Aucun nouvel évènement : le brouillon et la demande N4 restent
internes, aucun contact ne part au bus.

### 1.2 La séquence prouvée

1. `m1_importer_appel_manuellement` reçoit un appel `manque` avec `nom_entreprise`.
2. Le signal d'appel est écrit au registre anti-perte (comme avant), puis un **brouillon** `sms_appel_manque` est
   préparé : `statut=BROUILLON`, texte exact, aucune demande d'approbation, rien d'envoyé.
3. `m1_sms_demander_envoi` dépose une demande **N4** sur `m1_emettre_notification`, avec le texte exact du brouillon.
4. Une personne approuve. `garde_execution` relit le registre : un STOP arrivé entre-temps annule (échec), un texte qui
   n'est pas le brouillon demandé est refusé.
5. `m1_consigner_contact_reussi` (N3, humain) clôt le rappel et inscrit `issue=contact_reussi`, `delai_rappel_s`,
   `appel_recu_le`. Un transfert sans appel réel rend `REJ-RAPPEL-SANS-APPEL` ; une heure antérieure à l'appel rend
   `REJ-RAPPEL-HORODATAGE-ANTERIEUR`.

### 1.3 Ce qui est fail-closed

- **Pas de nom d'entreprise** : aucun brouillon n'est inventé ; la réponse porte
  `REJ-M1-APPEL-ENTREPRISE` et ce qu'il faut fournir.
- **Correspondant retiré (STOP)** : `REJ-SMS-RETRAIT`, aucun brouillon.
- **Aucun appel entrant** : le gabarit est refusé (`REJ-SMS-AUCUN-APPEL`) même si un SMS existe.
- **Fenêtre de 24 h échue** : `REJ-SMS-FENETRE`.
- **Rejeu du même appel** : la réponse d'origine est rendue telle quelle ; aucun second brouillon.

## 2. M1-F — messagerie vocale intelligente

### 2.1 Les pièces

| Pièce | Fichier | Rôle |
|---|---|---|
| Analyse pure | `voicemail_intelligent.py` | Résumé déterministe, extraction bornée, champs manquants, demande de rappel. Aucune horloge, aucune base, aucun réseau. |
| Import enrichi | `outils._importer_appel` | Analyse seulement si le texte est conservé (`consentement=accorde`, confiance non faible), ajoute `voicemail`, `resume_voicemail`, `audio_ref`, `confiance_transcription` au registre et à la réponse. |
| STT | `voicemail_stt.py` | Transmet `audio_ref` et `confiance_transcription` à l'import canonique ; l'audio reste en mémoire le temps de l'appel et n'est jamais écrit. |
| Tests | `departments/m01-front-office/tests/test_voicemail_intelligent.py` | 29 tests : extraction, résumé, adresse hostile, confiance faible, consentement, audio, rejeu. |

### 2.2 Les règles d'extraction (déterministes)

- **Nom** : seulement après `je m'appelle`, `mon nom est`, `mon nom c'est`, `c'est` ou `ici`, 2 à 4 mots
  capitalisés, mots non-nom retirés (Bonjour, Urgent, Gouttières, Laval…). Sinon `null`.
- **Téléphone** : celui de l'appel (E.164) ; un numéro différent écrit dans le message est normalisé (`+1` si dix
  chiffres) et porté à part (`telephone_mentionne`), jamais confondu avec l'appelant.
- **Service / ville** : mêmes règles que la qualification (`qualification.diagnostiquer`, services et zone du profil).
  Plusieurs services ou aucun : `service=null`, jamais un choix arbitraire.
- **Adresse** : numéro civique + type de voie connu, suite bornée à 120 caractères ; la ville reconnue est retirée de la
  suite. Une adresse plus longue ou sans type de voie n'est pas reconnue.
- **Urgence** : uniquement un marqueur explicite (urgent, urgence, au plus vite, dégât d'eau, fuite), jamais inférée.
- **Demande de rappel** : formules explicites (`rappelez-moi`, `rappeler`, `retour d'appel`, `demande un rappel`).

Le `resume` est composé de phrases fixes à partir de ces seuls faits : il ne contient aucun extrait du texte de
l'appelant, donc une consigne hostile (« ignore les instructions… ») ne peut pas devenir le résumé.

### 2.3 Lead et tâche de rappel

- Un message vocal qualifié part vers M2 par `m1.lead_qualifie` (contrat v2 gelé, inchangé).
- Une **demande explicite de rappel** ouvre en plus une tâche humaine `ventes` même quand le lead est déjà transmis :
  le client a demandé qu'on le rappelle, ce fait ne se perd pas.
- Sans service/ville/contact établis, ou avec une confiance `faible`, aucun lead n'est inventé : la tâche humaine est
  ouverte, la réponse dit que la transcription n'a pas été exploitée (`motif=confiance_faible`).
- Sans consentement `accorde`, le texte n'est ni conservé ni analysé ; seul le fait d'appel et la tâche subsistent.
- `audio_ref` n'accepte qu'un lien http(s) ou un identifiant opaque ; `data:`, `file:`, les espaces et les chaînes de
  plus de 500 caractères sont refusés (`REJ-AUDIO-REFERENCE`). Aucun octet audio n'est écrit ; la réponse dit
  `conserve=false`, `politique="non validée"`.

## 3. Preuves et commandes

- `./t.sh departments/m01-front-office/tests/test_appel_manque_complet.py` : **15 passed**.
- `./t.sh departments/m01-front-office/tests/test_voicemail_intelligent.py` : **29 passed**.
- Suite du département : voir le rapport de la vague ; les tests existants de l'import, du STT et de la composition
  restent verts.
- Mutations (`python3 mutkit.py sweep … -- ./.tmp/t-clean.sh …`, cache Python vidé avant chaque mutant) : **199 mutants
  tués sur 219**, 20 survivants tous équivalents et justifiés dans le `RAPPORT.md` de la vague. Les 20 survivants sont
  des constantes de version de gabarits préexistants, la borne `MAX_ADRESSE` inatteignable (suite limitée à 70
  caractères), les bornes basses d'un nom (deux mots ⇒ au moins trois caractères), l'ordre de retrait de deux villes
  (le `.*$` consomme la fin), `maxsplit` sans second séparateur, `frozen=True` d'une dataclasse, un `or` redondant avec
  la regex de variable, et une branche défensive d'un numéro à 11 chiffres que l'extraction ne produit jamais.

## 4. Limites, dites sans euphémisme

- **Aucun transport réel** : ni Twilio/SIP, ni SMS sortant. Le brouillon et la demande N4 sont prouvés ; la livraison
  ne l'est pas.
- **Aucun STT réel** : les transcriptions sont fictives ; la qualité fr-CA, le bruit, les accents et les coupures ne
  sont pas mesurés.
- **L'extraction est lexicale, pas sémantique** : un nom sans formule explicite, une adresse sans type de voie, une
  urgence dite par périphrase ou un service non déclaré au profil ne sont pas reconnus. Les faux positifs restent
  possibles sur des tournures ambiguës ; ils sont bornés et visibles.
- **L'adresse est un renseignement personnel** : elle n'est lue que si le texte est conservé avec consentement, reste
  au registre interne de l'instance et n'est envoyée à aucun évènement. La rétention/effacement Loi 25 de ce registre
  n'est pas couverte par ce chantier.
- **Le contact réussi est une DÉCLARATION humaine** : le code mesure le délai entre l'appel et la décision, pas la
  réalité de l'appel sortant ; aucun appel n'est passé par OPSYS.
- **Aucun envoi automatique** : même le brouillon « Nous avons manqué votre appel » exige la politique SMS et une
  approbation N4 avant tout envoi réel.
