# Installation VPS — OPSYS clé en main

> État au 30 septembre : le Compose courant démarre le fork Core local et utilise les fournisseurs
> natifs par défaut. PostgreSQL et LiteLLM sont des profils optionnels. Les sauvegardes v3 sont
> testées sur des volumes Docker QA éphémères, mais le parcours complet n'est pas certifié sur un
> VPS de production. Voir le [plan courant](../programme/RESTRUCTURATION-2026-09-30.md).


Public : opérateur qui installe OPSYS sur un VPS neuf. Architecture détaillée :
[`docs/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md), décision Core :
[ADR-0007](../decisions/ADR-0007-core-openclaw.md), remplacée par le fork
[ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md). Provenance du fork :
[`core/PROVENANCE.md`](../../core/PROVENANCE.md). Ce guide est l'option serveur : Docker Compose construit
l'image du Core depuis le fork local; les images des services tiers sont épinglées. Pour un poste ou un serveur sans Docker, l'installateur une commande
(PLAN T0.11) est décrit dans [`../exploitation/INSTALLATION.md`](../exploitation/INSTALLATION.md).

## 1. Prérequis

- **VPS** : Ubuntu 22.04/24.04 ou Debian 12/13, 4 vCPU, 8–16 Go RAM, sans GPU (profil `ollama`
  optionnel reste utilisable en CPU-only pour de petits modèles, mais lentement).
- **Accès root** (ou `sudo`) en SSH.
- **Nom de domaine** dont vous contrôlez la zone DNS, avec **deux** enregistrements `A` (et `AAAA`
  si IPv6) pointant vers l'adresse IP publique du VPS, propagés **avant** l'installation (Caddy
  émet un certificat Let's Encrypt automatiquement au premier démarrage pour chacun — un DNS non
  propagé fait échouer cette émission ; réessayer plus tard fonctionne, Caddy retente seul) :

  | Enregistrement | Cible | Sert |
  |---|---|---|
  | `opsys.exemple.ca` (`OPSYS_DOMAINE`) | IP du VPS | Control UI OpenClaw |
  | `console.opsys.exemple.ca` | IP du VPS | Console OPSYS |

  Deux sous-domaines = deux origines web distinctes, volontairement séparées (cookies de session
  isolés entre la console et le Control UI) — voir `deploy/Caddyfile`.
- Au moins une clé API de fournisseur de modèle cloud (Anthropic, OpenAI, DeepSeek, Gemini,
  OpenRouter, Mistral, xAI, Groq ou Moonshot) — ou un serveur Ollama accessible pour un usage
  100 % local (voir §4).
- Un endpoint d'embeddings OpenAI-compatible déclaré par l'opérateur, accessible depuis
  `opsys` et `openclaw-gateway`, avec son nom de modèle exact. La mémoire native Couche A
  exige cette configuration ; une clé de modèle de chat ou un serveur Ollama sans modèle
  d'embeddings ne la fournit pas. Le backend local R41 reste une option explicite nécessitant
  des assets vérifiés ; aucun modèle, téléchargement ou secret d'embeddings n'est créé par
  l'installateur. Un endpoint distant doit être déclaré explicitement, avec les règles de
  confidentialité de [RAG-PREMIUM.md](../memory/RAG-PREMIUM.md).
- **Loi 25 (Québec)** : privilégiez un VPS hébergé au Canada (voir
  [EXPLOITATION.md](EXPLOITATION.md#loi-25--hébergement)).

## 2. Récupérer le dépôt

```bash
git clone <url-du-depot> /opt/opsys-src
cd /opt/opsys-src
```

## 3. Configurer `deploy/.env`

```bash
cp deploy/.env.example deploy/.env
$EDITOR deploy/.env
```

Renseignez au minimum :

| Variable | Valeur |
|---|---|
| `OPSYS_DOMAINE` | votre domaine DNS déjà pointé vers ce VPS (ex. `opsys.exemple.ca`) |
| `ACME_EMAIL` | courriel pour les notifications Let's Encrypt |
| au moins une clé `..._API_KEY` | clé du fournisseur de modèle cloud choisi |
| `OPSYS_EMBEDDINGS_URL` | base URL OpenAI-compatible du backend d'embeddings choisi |
| `OPSYS_EMBEDDINGS_MODELE` | nom exact du modèle servi par ce backend |
| `OPSYS_EMBEDDINGS_LOCAL` | `1` seulement si le backend tourne effectivement sur le VPS |
| `OPSYS_EMBEDDINGS_CLE` | secret privé du backend si celui-ci exige une authentification |

Laissez les secrets internes vides : `deploy/install.sh` les génère automatiquement avec
`openssl rand` au premier lancement (idempotent — il ne régénère jamais un secret déjà en place).
Les clés fournisseurs et la configuration d'embeddings sont fournies par l'opérateur.

## 4. Lancer l'installation

```bash
sudo bash deploy/install.sh
```

Le script (voir `deploy/install.sh`, section par section) :

1. vérifie l'OS et les ressources (vCPU, RAM, espace disque) ;
2. installe Docker Engine depuis le dépôt apt officiel s'il est absent ;
3. crée un utilisateur dédié `opsys-deploy` (groupe `docker`) ;
4. génère les secrets manquants dans `.env` (`chmod 600`) ;
5. configure `ufw` (deny in / allow 22, 80, 443) et `fail2ban` ;
6. construit les images locales `opsys` et `opsys-core:local`, puis démarre le mode natif :
   `opsys` (SQLite, migrations, configuration et readiness) → `openclaw-gateway` → `caddy` ;
   PostgreSQL (`database`) et la compatibilité LiteLLM (`litellm`, qui inclut PostgreSQL et Valkey)
   s'activent explicitement ;
7. affiche les URL et les prochaines étapes.

La durée dépend du téléchargement des images tierces et de la construction locale du Core et du moteur.
Le code de sortie `3` signifie exclusivement qu'une configuration opérateur manque (paliers,
embeddings ou secrets), avec le schéma et la console vérifiés : le gateway reste suspendu.
Le bilan dit « en attente de configuration ». Un échec de santé d'OPSYS, du gateway ou de Caddy,
une configuration invalide ou un échec de build retourne un code non nul d'erreur, sans bilan
de réussite. Le code `0` valide les contrôles locaux décrits ici ; il ne certifie ni un tour
agent, ni la sandbox, ni un VPS de production.

## 5. Première configuration des modèles

Dans le conteneur `opsys`, la CLI du moteur s'appelle **`opsys-metier`** (PLAN T0.7 lot 2 : `opsys` est la commande du
core, qui n'est pas dans cette image). Une ancienne commande `opsys personnes creer ...` répond par un message qui donne
la nouvelle et sort avec le code 2.

Le mode natif est le défaut. L'initialisation attend les migrations, une configuration valide des
paliers, les paramètres d'embeddings et les clés d'API dont les noms sont référencés par cette configuration; le gateway attend
ensuite le readiness `healthy` d'`opsys`. LiteLLM n'est activé que si le mode et le profil de
compatibilité sont choisis explicitement.

1. Amorçage, une seule fois (ADR-0009 §5 : plus de mot de passe partagé, chaque personne a le
   sien) — créez la première personne, `nathan_owner` :
   ```
   docker compose -f deploy/docker-compose.yml exec opsys \
     opsys-metier personnes creer nathan --nom "Nathan" --role nathan_owner
   ```
   Le mot de passe est demandé sans écho (jamais en argument de ligne de commande) ; gardez-le en
   lieu sûr avec l'identifiant (`nathan`). D'autres personnes et rôles ensuite : `opsys-metier personnes
   creer <identifiant> --nom "…" --role <rôle>` (rôles : `nathan_owner`, `admin`, `finance`,
   `manager`, `seller`, `employee`, `client`, `system_agent` — ADR-0009 §5).
2. Ouvrez `https://console.<OPSYS_DOMAINE>` (console OPSYS, sous-domaine dédié — voir §1) et
   connectez-vous avec cet identifiant et ce mot de passe.
3. Onglet **Modèles** : associez au moins le palier `standard` à un fournisseur natif.
   - **Cloud** : fournisseur (`anthropic`, `openai`, `deepseek`, `gemini`, `openrouter`,
     `mistral`, `xai`, `groq`, `moonshot`) + nom de modèle exact. La clé API correspondante doit
     déjà être dans `deploy/.env` (`ANTHROPIC_API_KEY`, etc.) — après ajout, recréez `opsys`,
     attendez son état `healthy`, puis démarrez le gateway.
   - **Local (Ollama)** : démarrez le profil optionnel —
     `docker compose -f deploy/docker-compose.yml --profile ollama up -d ollama`, puis
     `docker compose -f deploy/docker-compose.yml exec ollama ollama pull <modele>` — et associez le
     palier au fournisseur `ollama` (URL interne `http://ollama:11434`, jamais `/v1`).
4. Les paliers `local`, `rapide` et `fort` sont optionnels ; un département sans palier
   spécifique dédié utilise `standard`.
5. Vérifiez le backend d'embeddings déclaré en §3. Après changement de ses variables ou ajout
   d'une clé fournisseur, recréez `opsys` pour recharger son environnement et régénérer ses
   fragments, puis attendez son état `healthy` avant de démarrer le gateway. La présence
   d'anciens fichiers ne suffit pas : readiness compare le catalogue et la mémoire générés à
   la configuration courante. Ce contrôle valide les paramètres et fichiers, sans appel modèle.

L'initialisation génère la configuration native d'OpenClaw. Pour une instance qui a choisi
explicitement LiteLLM, définissez `OPSYS_MODE_FOURNISSEUR=litellm` et
`OPSYS_PASSERELLE_URL=http://litellm:4000/v1` dans `deploy/.env`, puis activez le profil :

```bash
docker compose --profile litellm -f deploy/docker-compose.yml up -d
```

## 6. Se connecter au Control UI OpenClaw

Ouvrez `https://<OPSYS_DOMAINE>/` et collez `OPENCLAW_GATEWAY_TOKEN` (`deploy/.env`) dans l'invite de
connexion. Les agents dont les paliers et permissions sont configurés apparaissent dans le roster
**Agents** après le démarrage du gateway.

## 7. Activer les départements

Dans la console OPSYS (`https://console.<OPSYS_DOMAINE>`, onglet **Départements**), chaque département démarre en mode
`ombre` (aucune action externe). Faites-le passer en `supervisé` (approbation humaine sur les
actions T2/T3) puis, une fois confiant, `autonome` — jamais pour les actions T3 (paiement,
publication, suppression, engagement), qui restent toujours soumises à approbation quel que soit
le mode (voir `AGENTS.md`, principe **F**).

## 8. Vérifications de fin d'installation

```bash
cd deploy
docker compose ps                              # services activés par le profil choisi
curl -fsS --max-time 10 https://<OPSYS_DOMAINE>/healthz         # vie de Caddy seulement
curl -fsS --max-time 10 https://console.<OPSYS_DOMAINE>/healthz # vie de Caddy seulement
curl -fsS --max-time 10 https://<OPSYS_DOMAINE>/startupz        # démarrage du Core, 503 si incomplet
curl -fsS --max-time 10 https://console.<OPSYS_DOMAINE>/connexion # page réellement servie par OPSYS
docker compose logs opsys --tail=50            # configuration, readiness et moteur métier
```

Les deux `/healthz` publics sont des réponses statiques de Caddy : ils restent verts même si
les services en amont sont absents. Ils ne prouvent ni TLS public valide hors de cette requête,
ni santé du Core, ni connexion d'une personne. Les sondes `/sante` du MCP et de la console sont
également publiques et attestent seulement la vie HTTP ; les routes MCP métier exigent le
bearer dédié. La qualification métier doit encore vérifier authentification, catalogue des
dix modules et tour agent avec sandbox obligatoire. Le Compose de base ne raccorde pas le
daemon nécessaire à cette sandbox ; le [profil rootless candidat](SERVEUR-ROOTLESS.md) et son
parcours TLS restent à qualifier séparément. Ne désactivez pas la garde pour obtenir un état vert.

## Suite

- Exploitation courante, sauvegardes, mises à jour, sécurité : [EXPLOITATION.md](EXPLOITATION.md).
- Ce qui reste à valider sur ce premier VPS réel (dépendances non exécutables depuis le bac à
  sable de développement) : [EXPLOITATION.md § Validation de premier déploiement](EXPLOITATION.md#validation-de-premier-déploiement).
