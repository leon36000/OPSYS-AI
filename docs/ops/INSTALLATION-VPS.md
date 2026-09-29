# Installation VPS — OPSYS clé en main

Public : opérateur qui installe OPSYS sur un VPS neuf. Architecture détaillée :
[`docs/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md), décision Core :
[ADR-0007](../decisions/ADR-0007-core-openclaw.md), remplacée par le fork
[ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md). Provenance du fork :
[`core/PROVENANCE.md`](../../core/PROVENANCE.md). Ce guide est l'option serveur : Docker Compose, image officielle
épinglée de la release d'origine. Pour un poste ou un serveur sans Docker, l'installateur une commande
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
- **Loi 25 (Québec)** : privilégiez un VPS hébergé au Canada (voir
  [EXPLOITATION.md](EXPLOITATION.md#loi-25--hébergement)).

## 2. Récupérer le dépôt

```bash
git clone <url-du-depot> /opt/opsys-src
cd /opt/opsys-src
```

## 3. Configurer `deploy/.env`

```bash
cd deploy
cp .env.example .env
$EDITOR .env
```

Renseignez au minimum :

| Variable | Valeur |
|---|---|
| `OPSYS_DOMAINE` | votre domaine DNS déjà pointé vers ce VPS (ex. `opsys.exemple.ca`) |
| `ACME_EMAIL` | courriel pour les notifications Let's Encrypt |
| au moins une clé `..._API_KEY` | clé du fournisseur de modèle cloud choisi |

Laissez tous les secrets `changeme...` tels quels : `install.sh` les génère automatiquement avec
`openssl rand` au premier lancement (idempotent — il ne régénère jamais un secret déjà en place).

## 4. Lancer l'installation

```bash
sudo bash install.sh
```

Le script (voir `deploy/install.sh`, section par section) :

1. vérifie l'OS et les ressources (vCPU, RAM, espace disque) ;
2. installe Docker Engine depuis le dépôt apt officiel s'il est absent ;
3. crée un utilisateur dédié `opsys-deploy` (groupe `docker`) ;
4. génère les secrets manquants dans `.env` (`chmod 600`) ;
5. configure `ufw` (deny in / allow 22, 80, 443) et `fail2ban` ;
6. construit l'image `opsys` et démarre la pile dans l'ordre requis : `postgres` → `opsys`
   (écrit la config LiteLLM) → `litellm` → synchronisation des clés virtuelles et de la config
   des agents OpenClaw → `openclaw-gateway` → `caddy` ;
7. affiche les URL et les prochaines étapes.

Durée typique : quelques minutes (installation Docker + construction de l'image + téléchargement
des images officielles `ghcr.io/openclaw/openclaw` et `ghcr.io/berriai/litellm-database`).

## 5. Première configuration des modèles

OPSYS ne peut générer la configuration des agents OpenClaw tant qu'aucun **palier de modèle**
n'est associé à un fournisseur — c'est un choix délibéré (fail-closed) : mieux vaut un message
clair « configurez les modèles » qu'un agent pointant vers un modèle inexistant.

1. Amorçage, une seule fois (ADR-0009 §5 : plus de mot de passe partagé, chaque personne a le
   sien) — créez la première personne, `nathan_owner` :
   ```
   docker compose -f deploy/docker-compose.yml exec opsys \
     opsys personnes creer nathan --nom "Nathan" --role nathan_owner
   ```
   Le mot de passe est demandé sans écho (jamais en argument de ligne de commande) ; gardez-le en
   lieu sûr avec l'identifiant (`nathan`). D'autres personnes et rôles ensuite : `opsys personnes
   creer <identifiant> --nom "…" --role <rôle>` (rôles : `nathan_owner`, `admin`, `finance`,
   `manager`, `seller`, `employee`, `client`, `system_agent` — ADR-0009 §5).
2. Ouvrez `https://console.<OPSYS_DOMAINE>` (console OPSYS, sous-domaine dédié — voir §1) et
   connectez-vous avec cet identifiant et ce mot de passe.
3. Onglet **Modèles** : associez au moins le palier `standard` à un fournisseur.
   - **Cloud** : fournisseur (`anthropic`, `openai`, `deepseek`, `gemini`, `openrouter`,
     `mistral`, `xai`, `groq`, `moonshot`) + nom de modèle exact. La clé API correspondante doit
     déjà être dans `deploy/.env` (`ANTHROPIC_API_KEY`, etc.) — redémarrez `litellm` si vous
     l'ajoutez après coup : `docker compose -f docker-compose.yml restart litellm`.
   - **Local (Ollama)** : démarrez le profil optionnel —
     `docker compose -f docker-compose.yml --profile ollama up -d ollama`, puis
     `docker compose -f docker-compose.yml exec ollama ollama pull <modele>` — et associez le
     palier au fournisseur `ollama` (URL interne `http://ollama:11434`, jamais `/v1`).
4. Les paliers `local`, `rapide` et `fort` sont optionnels ; un département sans palier
   spécifique dédié utilise `standard`.

La synchronisation reprend automatiquement dans les 5 minutes (`OPSYS_SYNC_INTERVAL_SECONDS`), ou
immédiatement :

```bash
docker compose -f deploy/docker-compose.yml exec opsys sh -c \
  'opsys passerelle cles --url http://litellm:4000 && opsys openclaw configurer --config-dir /openclaw-config'
```

## 6. Se connecter au Control UI OpenClaw

Ouvrez `https://<OPSYS_DOMAINE>/` et collez `OPENCLAW_GATEWAY_TOKEN` (`deploy/.env`) dans l'invite de
connexion. Les agents des départements (un par `OPSYS_CLE_Mx` configuré à l'étape 5) apparaissent
dans le roster **Agents** une fois la synchronisation passée.

## 7. Activer les départements

Dans la console OPSYS (`https://console.<OPSYS_DOMAINE>`, onglet **Départements**), chaque département démarre en mode
`ombre` (aucune action externe). Faites-le passer en `supervisé` (approbation humaine sur les
actions T2/T3) puis, une fois confiant, `autonome` — jamais pour les actions T3 (paiement,
publication, suppression, engagement), qui restent toujours soumises à approbation quel que soit
le mode (voir `AGENTS.md`, principe **F**).

## 8. Vérifications de fin d'installation

```bash
cd deploy
docker compose ps                              # tous les services "healthy" (sauf ollama si non démarré)
curl -fsS https://<OPSYS_DOMAINE>/healthz              # "ok" (Control UI OpenClaw)
curl -fsS https://console.<OPSYS_DOMAINE>/healthz      # "ok" (console OPSYS)
docker compose logs opsys --tail=50            # confirme la synchro LiteLLM/OpenClaw/budgets
```

## Suite

- Exploitation courante, sauvegardes, mises à jour, sécurité : [EXPLOITATION.md](EXPLOITATION.md).
- Ce qui reste à valider sur ce premier VPS réel (dépendances non exécutables depuis le bac à
  sable de développement) : [EXPLOITATION.md § Validation de premier déploiement](EXPLOITATION.md#validation-de-premier-déploiement).
