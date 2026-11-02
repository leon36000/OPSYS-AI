# Passerelle de modèles : rôles, politique d'économie et LiteLLM intégré

Besoin du propriétaire (2026-11-02) : installer OPSYS-AI chez des clients, sur leur infrastructure ou dans le nuage, et le
connecter à tous les modèles requis **sans câbler chaque API**. Une clé OpenRouter (ou des clés directes) saisie une fois, des
rôles qui disent à quoi sert chaque modèle, et une consigne d'économie : Haiku au maximum, Sonnet par défaut, Opus
seulement si vraiment nécessaire.

Code : `src/opsys/roles_modeles/`, console `src/opsys/console/modeles_ui.py`, outils M10
`departments/m10-memoire/src/m10_memoire/modeles_roles.py`, migration `0086_modeles_roles`. Il **étend** le registre de
fournisseurs ([FOURNISSEURS-ET-SECRETS.md](FOURNISSEURS-ET-SECRETS.md)) : licence, EFVP, coffre et politique ne sont pas
recopiés, ils sont appelés.

## 1. Les dix rôles

| Rôle | Capacité du registre | Sert à | Suggestion de départ (recommandation, non validée) |
|---|---|---|---|
| `llm_rapide` | `llm` | classification, extraction, résumé court, normalisation, routage | Haiku 5.5 |
| `llm_fort` | `llm` | rédaction, analyse, outils complexes, conversation | Sonnet 5.5 |
| `llm_raisonnement` | `llm` | **escalade explicite seulement** | Opus 5.5 |
| `embeddings` | `embeddings` | recherche sémantique (M10) | multilingual-e5-large (à mesurer) |
| `reranker` | `reranker` | reclassement (point d'extension M10) | — |
| `ocr` | `ocr` | reconnaissance de texte | Tesseract (seul moteur raccordé) |
| `vl` | `llm` | lecture de photos et de documents numérisés | Qwen3-VL |
| `stt`, `tts`, `image` | `stt`, `tts`, `image` | voix et images | — |

Un rôle affecté porte : le fournisseur du registre, le **nom du modèle à appeler** (alias de passerelle), des **replis
ordonnés** (4 au plus), des **plafonds** (jetons par jour, budget en USD par mois), des **coûts déclarés** (lus du catalogue de
la passerelle quand il les donne, sinon saisis avec leur source, sinon « non déclaré »), les drapeaux de licence du registre
(usage commercial, service à des tiers, vérification, résidence, EFVP, contrat), et son état **mesuré / non mesuré**.
Un rôle **sans affectation est inerte** : aucun appel, aucune valeur par défaut.

*Mesuré* veut dire « qualifié par une mesure locale » (français québécois, documents réels) : ce n'est jamais le cas
aujourd'hui. Le test de connexion écrit autre chose : « connexion testée » (statut, latence, dimension des embeddings).

`vl` est un LLM qui accepte des images ; la capacité « vision » du registre (détection/segmentation d'objets) est autre chose.

## 2. Politique d'économie (en données)

`economie.CLASSES` : classe de tâche → rôle, version `2026-11-02/recommandation`, **toute ligne étiquetée
`recommandation_non_validee`** (la console l'affiche). Invariants testés :

- une classe **inconnue est refusée** (`REJ-MODELES-CLASSE-INCONNUE`) : jamais d'aiguillage par défaut vers un rôle fort ;
- seule la classe `escalade_raisonnement` mène à `llm_raisonnement`, et elle exige une approbation ;
- un palier historique ne mène jamais au raisonnement : `rapide` ← `llm_rapide` ; `standard` et `fort` ← `llm_fort`.

## 3. Une seule porte d'écriture, des niveaux d'approbation

`service.appliquer(cnx, acteur, operation, parametres, niveau_confirme, motif)` est **l'unique** fonction qui écrit la
configuration des modèles (le registre de « réglages de direction » d'une autre branche s'y branchera). Elle exige une personne
active `nathan_owner`/`admin` relue en base, valide tout avant d'écrire, et inscrit l'état d'avant et d'après dans
`modeles_historique` (append-only, déclencheurs SQLite et PostgreSQL), sans aucune valeur de secret.

| Opération | Niveau |
|---|---|
| `passerelle.configurer`, `passerelle.retirer` | **N3** |
| `role.affecter` (changer de fournisseur ou de modèle), `role.retirer`, `role.replis` | **N3** |
| `raisonnement.activer` (avec motif) | **N3 explicite** |
| `revenir` (retour arrière) | **N3** |
| `role.plafonds`, `role.couts`, `raisonnement.desactiver` | N2 |

« N3 » veut dire : la case de confirmation de la console, ou `--confirmer-n3` de la CLI, sinon refus
`REJ-MODELES-CONFIRMATION-N3-REQUISE`. Aucun agent n'a ces gestes : les outils MCP sont en lecture et en test seulement.

**Retour arrière** : `revenir` rétablit l'état d'avant le dernier changement d'une cible (`role:<rôle>`, `passerelle`,
`raisonnement`), après **revalidation complète** (le fournisseur peut être devenu inactif ou non conforme depuis) ; refaire
`revenir` annule l'annulation.

**Raisonnement** : en plus de l'activation N3, il n'a **aucun repli**, sa cible (fournisseur + modèle, et modèle d'amont) ne peut
être la cible d'aucun autre rôle, son alias n'existe dans la configuration LiteLLM générée **que s'il est activé**, il n'est
jamais dans les clés virtuelles des départements, et chaque appel exige une `Escalade` (personne admin active + motif de 10 à
300 caractères) et se journalise.

## 4. Appel routé

`appel.completer / plonger / reclasser` : classe → rôle → affectation → cibles ordonnées. Pour chaque cible, relus à chaque appel :
fournisseur actif et conforme à la politique de licence ; puis, pour le **principal seulement**, plafond de jetons du jour (usage
+ entrée estimée + sortie demandée) et budget du mois (exige des coûts connus, sinon `BUDGET_NON_VERIFIABLE`). Un repli est tenté
sur panne retentable (délai, 429, 5xx, hôte injoignable), plafond atteint ou fournisseur inutilisable ; **jamais** sur une
erreur 400/401/403/404 (la requête ou la configuration est en cause). Chaque tentative est rendue (`tentatives`). Si rien n'est
utilisable : `REJ-MODELES-PLAFOND-ATTEINT`, `-APPEL-ECHEC` ou `-FOURNISSEUR-REFUSE`. L'usage de l'amont est compté ; sans
`usage` rapporté, on compte une borne haute (jamais un sous-comptage) et le résultat le dit (`estime`). Aucune transaction n'est
tenue pendant le réseau.

Le **test de connexion** d'un rôle est UN appel minuscule au principal (≤ 8 jetons de sortie ; un texte pour les embeddings,
qui mesure la dimension ; une image 1×1 pour `vl` ; `/v1/rerank`), jamais de repli ; un agent ne peut le lancer qu'une fois par
rôle par minute et jamais pour le raisonnement.

## 5. Passerelle LiteLLM intégrée

Deux modes (`passerelle.configurer`) :

- **intégrée** : le profil `litellm` de `deploy/` (défaut de `deploy/install.sh`). OPSYS génère la configuration LiteLLM de tous
  les rôles ;
- **existante** : le LiteLLM du client (`OPSYS_PASSERELLE_EXTERNE=1`, URL + clé en coffre). OPSYS ne génère rien : les alias sont
  ceux du catalogue découvert.

Le fournisseur d'un alias de passerelle est déclaré dans le registre, **un par alias** (`<capacité>.passerelle.<alias>`, point
d'accès `passerelle:litellm`), pour que licence, EFVP et empreinte d'espace vectoriel suivent le modèle réellement appelé. Sa
licence déclarée : cœur LiteLLM MIT (fichier LICENSE lu le 2026-11-02 ; le dossier `enterprise/` relève d'une licence
distincte, ni utilisé ni redistribué), conditions du modèle d'amont = contrat du client (`sur_contrat` : référence de contrat
exigée), service à des tiers `incertain` (refusé si le client héberge pour des tiers). Les données quittent le Québec par
OpenRouter : une **EFVP** (Loi 25) est exigée. Un modèle local (vLLM, Ollama) se choisit dans le catalogue du registre, avec sa
propre licence de poids.

- **URL** : https, ou http seulement vers la boucle locale ou un réseau privé que le propriétaire a **confirmé** ; jamais
  d'identifiants, de paramètres, d'adresse link-local (métadonnées infonuagiques) ni non spécifiée.
- **Test de connexion et catalogue** : `GET /v1/models` et `/model/info` ; seuls nom, mode, vision, coût par million de jetons
  et modèle d'amont sont retenus (jamais `litellm_params`). Un coût rapporté à `0` n'est pas retenu : LiteLLM rapporte 0 pour un
  modèle absent de sa table de prix, ce qui n'est pas « gratuit ».
- **Configuration générée** (`opsys-metier modeles passerelle config` ; aussi `passerelle config` de l'entrypoint) : une
  entrée par rôle servi par la passerelle, les alias de palier que lisent les agents, les replis locaux comme entrées et comme
  `litellm_settings.fallbacks` natifs, aucune clé (`os.environ/…`). Les rôles l'emportent sur un palier de `paliers.yaml` de même
  alias (deux entrées de même nom seraient équilibrées en charge). Les rôles fournissent aussi leurs paliers à
  `openclaw configurer` et à la sonde de santé, sans toucher `paliers.yaml`.
- **Clés virtuelles par département** avec plafond : inchangé (`passerelle cles`), mais la liste des alias vient des rôles, sans
  raisonnement ni repli. La clé d'administration vient du coffre (passerelle connectée), sinon de `LITELLM_MASTER_KEY`.
- **Secrets** : saisis une fois dans le coffre (`coffre definir passerelle.openrouter`). `modeles passerelle importer-cle`
  copie, côté serveur, une variable d'environnement **autorisée** (la clé maître générée par l'installateur) vers le coffre,
  sans l'afficher. Le conteneur LiteLLM lit ses clés dans son environnement : `modeles passerelle ecrire-env` matérialise,
  depuis le coffre, un fichier 0600 `NOM=valeur` (création atomique, refus d'un lien symbolique ou d'un dossier accessible à
  tous) dans le volume partagé ; c'est le **seul** endroit où une valeur est écrite hors du coffre. L'overlay
  `deploy/docker-compose.passerelle-coffre.yml` le charge au démarrage. Aucune clé dans git, les journaux, les messages
  d'erreur ni la page (un test balaie le dépôt, les journaux, les tables et les sorties).
- **Hors ligne / local** : un fournisseur `local` du registre (vLLM, Ollama sur GB10) est un repli de première classe : appelé
  directement par OPSYS, et publié dans la configuration LiteLLM comme repli natif. Pour un fournisseur `local`, `http://` est
  permis vers un réseau privé (10/8, 172.16/12, 192.168/16, fc00::/7) ou un nom de service sans point ; jamais pour une API.

## 6. Console et outils

Console : **Plateforme → Modèles et rôles** (`/plateforme/modeles`, JSON `/api/plateforme/modeles`) : passerelle (connexion,
test, catalogue), escalade, un tableau des dix rôles (affectation, licence, conformité, replis, plafonds et usage du jour, coût
et sa source, mesuré ou non, dernier test), politique d'économie, historique. Mêmes protections que « Plateforme » (session,
rôle relu en base, CSRF, `no-store`, CSP, contrôle anti-fuite avant de servir la page).

Outils M10 : `m10_lire_roles_modeles` (T0/N0) et `m10_tester_role_modele` (T1/N2). Aucun rôle d'appareil. Registre MCP scellé
(révision 14).

CLI : `opsys-metier modeles {etat, economie, passerelle {connecter, retirer, tester, importer-cle, config, ecrire-env},
role {connecter, affecter, retirer, plafonds, tester, revenir}, raisonnement {activer, desactiver}}`.

## 7. Raccord des consommateurs (sans changer le comportement par défaut)

- **Embeddings de M10** : `ports.resoudre_embeddeur` trouve l'adaptateur du rôle `embeddings` quand rien n'est raccordé par
  identifiant. Il exige la **dimension mesurée** par un test de connexion (sinon `REJ-CONN-EMBEDDINGS-NON-RACCORDE`), porte le
  modèle réellement appelé (changer d'alias change l'espace vectoriel et impose la réindexation) et passe par l'appel routé. Le
  rôle n'accepte **aucun repli** (autre espace vectoriel). Dans une transaction d'outil, le secret est résolu dans un point de
  sauvegarde (`coffre.utiliser(dans_transaction=True)`, réservé à ces adaptateurs).
- **Reranker** : point d'extension `/v1/rerank`, facultatif comme avant.
- **OCR** : si le rôle `ocr` est affecté à un autre moteur que `ocr.tesseract-5.5.local`, l'extraction d'un PDF scanné est refusée
  (`REJ-ING-OCR-INDISPONIBLE`) au lieu d'utiliser Tesseract en silence. Sans rôle : inchangé.
- **STT, TTS, vision-langage, image** : le rôle et son test existent, aucun consommateur n'y est encore raccordé.

## 8. Ce qui n'est pas prouvé

Voir [LIMITES-CONNUES](../utilisation/LIMITES-CONNUES.md). En bref : tout est prouvé contre un faux serveur compatible OpenAI ;
le test contre la vraie passerelle est opt-in (`OPSYS_LITELLM_TEST_URL`, `OPSYS_LITELLM_TEST_KEY_FILE`). Aucune installation
réelle chez un client, aucun vLLM/GB10, aucun OCR ni VL réel, aucune mesure de qualité ni de coût réel, PostgreSQL non exercé
pour ces tables (le schéma est portable, la migration contient les déclencheurs PostgreSQL, mais aucun test PostgreSQL n'a été
lancé pour 0086).
