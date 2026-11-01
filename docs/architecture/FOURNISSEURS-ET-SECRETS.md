# Registre de fournisseurs et coffre de secrets

Socle « plateforme configurable » (DECISIONS-ARCHITECTE r1 §6–§7, FEUILLE-DE-ROUTE-TECHNO r2 tableau A,
B.2, B.3, B.5). Code : `src/opsys/fournisseurs/`, `src/opsys/secrets_coffre/`, console
`src/opsys/console/plateforme_ui.py`, migration `0037_fournisseurs_coffre` (après `0036_operateur_politiques_reconciliateur`).

« Fournisseur » désigne ici un fournisseur de **capacité technique** (modèle, service). Les fournisseurs de
matériaux de M6 restent dans `console/fournisseurs_ui.py` (`/crm/fournisseurs`).

Les voix et visages des avatars (`tts`, `avatar`, `stt`) s'appuient sur ce registre sans le dupliquer : le registre par
client des voix et visages, ses consentements et sa politique de disponibilité des canaux appellent `politique.evaluer`
et `registre.tester` d'ici. Voir [AVATARS-VOIX.md](AVATARS-VOIX.md).

## 1. Modèle de données

| Table | Rôle |
|---|---|
| `fournisseurs_profil` | Profil de licence du client (singleton, révision) : usage commercial, revenu annuel **en USD** (affiliés compris, `NULL` = inconnu), territoires du client et de l’hébergement, hébergement pour tiers (multi-locataire). |
| `fournisseurs_configurations` | Définition figée (JSON canonique) d’un fournisseur configuré, `actif`, révision, dernier test. Aucune valeur de secret : seulement `coffre:<nom>`. |
| `fournisseurs_selections` | (capacité, portée) → fournisseur ; portée `*` = défaut global, sinon code de département. |
| `coffre_secrets` | Métadonnées : nom, service, état `actif`/`revoque`, version active, auteurs et dates. |
| `coffre_versions` | Chiffré d’une version : nonce + clé de donnée enveloppée, nonce + valeur chiffrée, empreinte de la clé maîtresse. Une version `remplacee`/`revoquee` n’a plus aucun octet chiffré (contrainte CHECK). |
| `coffre_jetons` | Empreinte SHA-256 d’un jeton opaque, porteur, usage, expiration, révocation. Le jeton lui-même n’est jamais stocké. |
| `coffre_acces` | Journal d’accès **append-only** (déclencheurs SQLite et PostgreSQL) : action, acteur, usage, résultat, code. Ni valeur ni jeton. |

Un fournisseur (`fournisseurs.modele.Fournisseur`) porte : identifiant, capacité (`llm`, `embeddings`,
`reranker`, `ocr`, `stt`, `tts`, `avatar`, `image`, `video`, `recherche_web`, `courriel`), mode (`local`/`api`), point
d’accès (`https://…`, `http://127.0.0.1…`, `module:…`, `binaire:…`, `appareil:…`), modèle, référence de secret,
quotas déclarés, coût unitaire déclaré (chaîne décimale + devise + unité + source), résidence des données,
références EFVP et contrat, statut catalogue (`adopte`, `repli`, `conditionnel`, `ecarte`, `declare`),
qualification (`a_mesurer` tant qu’aucune mesure locale n’existe) et un **bloc licence** : licence du code,
licence des poids, usage commercial (`autorise`, `interdit`, `sous_seuil`, `sur_contrat`, `inconnu`), seuil de
revenu (USD), territoires exclus, droit de service à des tiers (`autorise`, `interdit`, `incertain`), mention
obligatoire, intégration (`bibliotheque`, `service_separe`, `api`, `appareil`), vérification (`verifiee`,
`a_lire`), source documentaire.

## 2. Moteur de politique et codes de refus

`politique.evaluer(fournisseur, profil)` est pur et rend **tous** les refus, dans un ordre stable :

| Code | Condition |
|---|---|
| `PROFIL_CLIENT_ABSENT` | Aucun profil de licence déclaré. |
| `FOURNISSEUR_ECARTE` | Écarté par la feuille de route (raison citée). |
| `LICENCE_NON_COMMERCIALE` | Usage commercial interdit et client commercial. |
| `LICENCE_INCONNUE` | Droit d’usage commercial non qualifié. |
| `LICENCE_A_VERIFIER` | Texte intégral non lu ; se lève quand un admin consigne sa lecture (`licence_lue`). |
| `CONTRAT_REQUIS` | Usage sur contrat/conditions payantes sans référence de contrat. |
| `SEUIL_REVENU_DEPASSE` | Revenu déclaré ≥ seuil de la licence. |
| `REVENU_CLIENT_INCONNU` | Licence à seuil et revenu non déclaré. |
| `TERRITOIRE_EXCLU` | Territoire du client ou de l’hébergement exclu. |
| `TERRITOIRE_CLIENT_INCONNU` | Licence à exclusions et territoires non déclarés. |
| `SERVICE_TIERS_INTERDIT` | Hébergement pour tiers et licence qui l’interdit. |
| `SERVICE_TIERS_INCERTAIN` | Hébergement pour tiers et droit non établi (avis juridique, B.6). |
| `COPYLEFT_INTEGRE` | GPL/AGPL intégrée comme bibliothèque (service séparé seulement, §7). |
| `MENTION_NON_CONFIRMEE` | Mention obligatoire dont l’affichage n’est pas confirmé. |
| `EFVP_REQUISE` | API avec données hors Québec sans référence d’EFVP (Loi 25, B.5). |

**Aucun repli silencieux** : un refus d’activation est journalisé (`fournisseurs.activation.refusee`) et rendu ;
rien d’autre n’est activé. `registre.resoudre(capacité, département)` prend la sélection du département, sinon le
défaut global ; si la sélection retenue est inactive ou devenue non conforme (ex. revenu passé au-dessus du
seuil), c’est `FOURNISSEUR_INACTIF` ou `REFUS_POLITIQUE`, jamais le défaut global ni un autre fournisseur ;
sans sélection : `AUCUN_FOURNISSEUR`. Autres codes du registre : `ADMIN_REQUIS`, `CONFLIT_REVISION`,
`CHAMP_NON_MODIFIABLE` (licence du catalogue immuable), `DECLARATION_INVALIDE`, `SECRET_INDISPONIBLE`,
`NON_CONFIGURE`, `CAPACITE_INCOMPATIBLE`, `DEPARTEMENT_INVALIDE`, `PROFIL_INVALIDE`.

## 3. Catalogue initial

`fournisseurs/catalogue.py` : 66 entrées (57 reprises des recherches R1, R3, R4, R5, R6 avec la ligne citée, 4 de courriel, 5 de
vision hors recherche) ; toutes `a_mesurer`. L'audit ligne par ligne (code et poids, seuils, territoires, service à des tiers, niveau de
vérification à la source) est dans [REGISTRE-FOURNISSEURS-LICENCES](../compliance/REGISTRE-FOURNISSEURS-LICENCES.md).

- **Adoptés** : Mistral Small 4, gpt-oss-120b, Nemotron 3.5 Lightning (OpenMDW à lire) ; bge-m3,
  Qwen3-Embedding ; bge-reranker-v2-m3, Qwen3-Reranker ; Docling (modèles internes à lire), Tesseract 5.5,
  PaddleOCR ; Voxtral Mini Realtime ; Chatterbox Multilingual ; TalkingHead ; FLUX.2 klein 4B, Qwen-Image-2512,
  Qwen-Image-Edit-2511, Qwen-Image-Layered, Z-Image-Turbo, SeedVR2 ; Wan 2.2 ; API officielle de recherche web.
- **Replis** : mxbai-rerank-v2 ; Mistral OCR 3 (API) ; Kyutai STT, Parakeet v3, pyannote (CC-BY : mention) ;
  Kyutai TTS, Azure fr-CA (API) ; Audio2Face-3D, MuseTalk 1.5 ; Recraft V4.1 (API).
- **Conditionnel** : FLUX 3 Image Klein (seuil 5 M$ US, service à des tiers incertain, licence lue en résumé).
- **Écartés** (refusés par la politique, raison citée) : Jina embeddings/rerankers (NC) ; Marker, Surya (seuil),
  Chandra 2 (seuil + non-concurrence), PyMuPDF, Ghostscript (AGPL), Nougat, GOT-OCR2 (NC/recherche) ; XTTS-v2
  (CPML), F5-TTS, Voxtral TTS (NC), Fish Speech (seuil 500 k$, service hébergé interdit) ; NVIDIA ACE complet
  (NVAIE), Wav2Lip, InsightFace, SadTalker (NC), Duix (licence discrétionnaire) ; FLUX.1/2 dev et Kontext dev,
  Qwen-Image 2.1, Bria Fibo dev (NC) ; HunyuanVideo, MiniMax H3 (territoires) ; Remotion (licence maison) ;
  scraping de Google/IA (conditions d’utilisation).

## 4. Coffre de secrets

- **Algorithme** (`aes-256-gcm/enveloppe/v1`) : par version, clé de donnée aléatoire de 32 octets ; valeur
  chiffrée AES-256-GCM (nonce 96 bits) ; clé de donnée enveloppée AES-256-GCM par une KEK dérivée de la clé
  maîtresse (HKDF-SHA256, `opsys-coffre/kek/v1`) ; AAD = algorithme, nom, version et partie, donc un chiffré
  déplacé ne se déchiffre pas. Primitive : `cryptography` (AESGCM), déjà utilisée par l’ingestion et la
  réception courriel ; absente → `COFFRE_CHIFFREMENT_INDISPONIBLE` (installer l’extra `ingestion`).
- **Clé maîtresse hors base** : `OPSYS_COFFRE_CLE_FICHIER` (recommandé : chemin absolu, fichier ordinaire non
  lien, propriétaire courant, mode 0600, dossier parent non inscriptible par d’autres, hors de tout dépôt Git)
  ou `OPSYS_COFFRE_CLE` (base64, environnement du serveur seulement, jamais celui des agents). Les deux à la fois
  → `COFFRE_CLE_CONFLIT` ; aucune → `COFFRE_CLE_MAITRESSE_ABSENTE` ; mauvaise clé → `COFFRE_CLE_MAITRESSE_DIFFERENTE`.
  Création : `opsys-metier coffre generer-cle-maitresse --fichier /chemin/hors/depot/coffre.cle` (O_EXCL, 0600).
  L’export d’instance (`instance exporter`) ne prend que `opsys.db`, `paliers.yaml`, `entreprise.yaml` : il
  contient des chiffrés, jamais la clé. L'archive elle-même est en clair : `python -m opsys.sauvegarde_chiffree` la
  chiffre (AES-256-GCM) avec une clé de SAUVEGARDE distincte de la clé maîtresse, elle aussi hors de la sauvegarde et de
  l'instance (docs/qualification/QUALIFICATION-CONTENEUR.md, « Sauvegarde et restauration »).
- **Agents** : ils reçoivent un jeton opaque `opsys-jeton:v1:…` (`coffre jeton`), lié à un porteur et à un usage
  (`fournisseur:<id>`, `connecteur:<nom>`), avec expiration. Seul `coffre.utiliser(...)`, côté serveur, au moment
  de l’appel et hors transaction métier, le résout ; la valeur n’existe en clair que dans ce bloc et y est
  masquée dans tous les journaux du processus (fabrique `logging` masquante).
- **Rotation** : nouvelle version ; les octets de l’ancienne sont détruits dans la même transaction ; les jetons
  suivent le nom. **Rotation de la clé maîtresse** : `coffre rechiffrer --nouvelle-cle-fichier …` ré-enveloppe
  toutes les clés de donnée, tout ou rien.
- **Révocation** : immédiate et définitive (octets détruits, `secure_delete` SQLite, jetons révoqués, nom clos).
- **Export** : toujours refusé (`COFFRE_EXPORT_INTERDIT`), journalisé ; la console et la CLI n’ont aucune lecture
  de valeur.
- **Journal** : chaque définition, rotation, révocation, émission de jeton, résolution (acceptée ou refusée),
  tentative d’export et refus d’administration.

## 5. Console et CLI

Console (onglet « Plateforme », rôle `nathan_owner`/`admin` relu en base à chaque requête, CSRF, `no-store`,
CSP stricte) : `/plateforme/fournisseurs` (profil de licence, sélections par capacité et département, tableau par
capacité : licence complète, verdict de politique avec codes et motifs, état, qualification, dernier test ;
configurer, activer, désactiver, tester) ; `/plateforme/secrets` (métadonnées, saisie unique par champ mot de
passe, rotation, révocation confirmée, journal d’accès). Lecture JSON : `/api/plateforme/fournisseurs`,
`/api/plateforme/secrets` ; `/api/plateforme/secrets/<nom>/valeur` répond toujours 403.

CLI (`opsys-metier …` ou `opsys metier …` depuis le core ; le nom `opsys` reste celui du core). Le groupe des
secrets s’appelle `coffre` : `secrets` est déjà une commande du core, et une sous-commande du moteur ne peut pas
porter le nom d’une commande du core (`tests/test_commande_metier.py`) :

```bash
opsys-metier fournisseurs lister [--capacite ocr] [--json]
opsys-metier fournisseurs profil --usage-commercial oui --revenu-usd 1500000 --territoire CA --heberge-pour-tiers non --par nathan
opsys-metier fournisseurs configurer ocr.mistral-ocr-3.api --point-acces https://… --secret coffre:mistral.ocr \
    --efvp-ref EFVP-2026-01 --contrat-ref CONTRAT-… --par nathan
opsys-metier fournisseurs activer|desactiver|tester <id> --par nathan
opsys-metier fournisseurs selectionner image image.qwen-image-2512.local --departement m07-marketing --par nathan
opsys-metier coffre lister | journal [nom]
opsys-metier coffre definir <nom> --service google_ads --par nathan    # valeur saisie deux fois, sans écho
opsys-metier coffre rotation <nom> --par nathan
opsys-metier coffre revoquer <nom> --confirmer --par nathan
opsys-metier coffre jeton <nom> --porteur m07-marketing --usage connecteur:google-ads --duree-s 3600 --par nathan
```

Une valeur passée en argument (`--valeur`, positionnel) est refusée sans être recopiée dans l’erreur.

Premier consommateur des capacités `image` et `video` : le studio créatif de M7 ([M7-STUDIO-CREATIF.md](M7-STUDIO-CREATIF.md)) ;
il appelle `registre.resoudre` et `politique.evaluer` (aucune copie), refuse tout repli, fige un instantané de licence sans le
revenu du client dans la provenance et revérifie la licence à chaque étape. Aucun adaptateur de modèle réel n'est encore branché.

## 6. Limites connues

- Les consommateurs existants (passerelle LiteLLM et paliers, STT M1, embeddings M10, OCR) ne lisent pas encore
  le registre : la résolution existe, le raccordement est le chantier suivant. Premier consommateur : le port
  d'extraction de facture de l'ingestion d'onboarding ([INGESTION-ONBOARDING.md](INGESTION-ONBOARDING.md), capacité
  `llm` de M5, refus typé sans repli), sans adaptateur réseau raccordé dans sa première tranche.
- Quotas et coûts sont **déclarés et affichés**, pas encore comptés ni appliqués à l’appel.
- Aucune mesure locale : tout reste `a_mesurer` (B.4). Les licences sont celles des recherches au 2026-10-31 ;
  une revue trimestrielle reste à planifier (R5 §7.1).
- Le profil de licence est déclaré par un humain ; la question du « licencié » en multi-locataire (B.6) reste
  juridique.
- La révocation ne nettoie pas les sauvegardes, instantanés ou WAL déjà copiés : tourner alors la clé maîtresse.
- Le masquage reconnaît la valeur exacte et des formes usuelles ; une valeur transformée (découpée, encodée) par
  un tiers n’est pas reconnue.
- La sonde HTTP réelle n’est jamais exécutée en QA ; son comportement réseau est prouvé par des ouvertures
  simulées seulement.
- L’émission de jetons est faite par un admin (CLI) ; la remise automatique d’un jeton à un agent configuré n’est
  pas encore câblée.
- **Raccordement au core en attente** : `tests/test_commande_metier.py` exige que chaque sous-commande du moteur
  figure dans `OPSYS_METIER_MOVED_COMMANDS` (`core/src/cli/opsys-metier-argv.ts`) et dans
  `tests/installateur/faux_core.py`. `core/` étant hors du périmètre de ce chantier, l’ajout de `fournisseurs`
  et `coffre` à ces deux listes reste à faire (deux lignes) ; d’ici là ce test échoue. `opsys metier fournisseurs …`
  fonctionne déjà : le core transmet toute commande après `metier` sans liste d’autorisation.

## Capacité « courriel » (connecteurs Gmail, Graph, IMAP, mbox)

Quatre entrées au catalogue (`courriel.gmail.api`, `courriel.graph.api`, `courriel.imap.generique`, `courriel.mbox.local`), toutes
`a_mesurer`. Gmail et Graph sont `sur_contrat` (contrat du client requis) et exigent une EFVP (Loi 25) hors Québec. Les jetons OAuth et
mots de passe d'application des comptes passent par ce coffre (`courriel.<compte>.g<génération>`, service `google`, `microsoft` ou `autre`),
jamais par `reference_secret` d'un fournisseur. Voir [CONNECTEURS-COURRIEL.md](CONNECTEURS-COURRIEL.md).

## Consommateur : bases de connaissances (M10)

Les capacités `embeddings` et `reranker` sont consommées par `opsys.connaissances` (`ports.resoudre_embeddeur`,
`ports.resoudre_reranker`) : la sélection du département de la base, sinon le défaut global ; une sélection inactive ou non conforme est
un refus, jamais un repli. L'**empreinte de configuration** d'un fournisseur (identifiant, mode, modèle, point d'accès, licence des
poids) identifie l'espace vectoriel : la modifier (ex. changer `modele`) invalide les vecteurs de la base jusqu'à la réindexation.
Aucun adaptateur réel n'est raccordé dans cette tranche. Voir [CONNAISSANCES.md](CONNAISSANCES.md).

## Capacité « vision » (M3.3 et M3.5)

La capacité `vision` (détection et segmentation d'objets sur photo) rejoint les onze autres (migration 0049 : la contrainte
`fournisseurs_configurations.capacite` s'élargit, aucune table). Le catalogue porte cinq entrées (Grounding DINO et SAM 2
« adoptés » au sens de la pile visée par DEFINITION-PRODUIT §7 M3.5 ; Florence-2 et OWLv2 en repli ; YOLO d'Ultralytics écarté
pour sa licence AGPL). Aucune recherche R1-R6 ne couvre la vision : toutes les licences viennent de la connaissance de l'agent au
2026-11-01, sans réseau ni lecture du texte intégral ; elles sont donc **toutes `a_lire`** (activation refusée tant qu'un
administrateur n'a pas lu et consigné la licence du code et celle de chaque jeu de poids), sans point d'accès (aucun poids n'est
fourni ni téléchargé par OPSYS) et `a_mesurer`. « Adopté » n'est pas « qualifié » : voir
[M3-M4-MATHIS-GABRIEL.md](M3-M4-MATHIS-GABRIEL.md).
