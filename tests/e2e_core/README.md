# E2E avec le vrai core (PLAN T1.5-b)

`tests/e2e/` prouve le moteur, avec la porte d'appareil du core refaite en Python. Ici, le trajet est réel :
**app → Gateway OPSYS-CORE → moteur métier**. Le script génère la configuration du core par `opsys openclaw
configurer`, démarre le Gateway (qui lance le moteur par le superviseur T0.10), appaire un appareil de test comme
l'app le fait (défi signé Ed25519, approbation par la CLI du core), puis appelle `GET /opsys/identite` et
`POST /tools/invoke` avec son jeton, en chronométrant chaque appel.

## Lancer

```bash
pip install -e ".[dev]"
(cd core && pnpm install --frozen-lockfile && pnpm build)      # Node 24
python tests/e2e_core/scenario.py                # le Gateway lance le moteur ; --moteur direct : le script le lance
```

Le job CI est `.github/workflows/e2e-core.yml`. Le code de sortie est 0 seulement si chaque constat est vrai ;
sinon le message dit lequel, et le script imprime la fin des journaux du Gateway et du moteur
(`<travail>/journaux/`). Les latences vont dans le journal, dans `<travail>/mesures.json` et dans le résumé du job.

## Commandes du core utilisées

| Étape | Commande ou réglage | Source dans le fork |
|---|---|---|
| Configuration acceptée | `openclaw config validate` | `core/src/cli/config-cli.ts:465` |
| Gateway (mode local, port, liaison) | `openclaw gateway run --bind loopback --port P` | `core/src/cli/gateway-cli/run-command.ts:24`, garde `gateway.mode=local` : `pre-bootstrap.ts:48` |
| Prêt | `GET /startupz` | `core/src/gateway/gateway-http-route-contracts.ts:7` |
| Code d'appairage | `openclaw qr --json --url ws://127.0.0.1:P` | `core/src/cli/qr-cli.ts:107,118` |
| Demandes en attente | `openclaw devices list --json` | `core/src/cli/devices-cli.ts:37`, `devices-cli.runtime.ts:753` |
| Approbation sans interface | `openclaw devices approve <requestId> --json` | `core/src/cli/devices-cli.ts:82`, `devices-cli.runtime.ts:943` |
| Approbation explicite en local | `gateway.nodes.pairing.autoApproveLocal=false` | `core/src/config/zod-schema.gateway.ts:473`, `handshake-auth-helpers.ts:114` |
| Moteur supervisé | `opsys/metier.json` | `core/src/gateway/opsys-metier-config.ts:1` |

## Fichiers

| Fichier | Rôle |
|---|---|
| `scenario.py` | Orchestration : configuration, donnée, processus, appairage, attribution, trajet. |
| `trajet.py` | Ce que l'app appelle par HTTP, et ce que le moteur en garde (base lue). |
| `appairer.mjs` | Poignée de main de l'app, en Node sans dépendance. `--autotest` : vecteurs de la charge v3. |
| `test_repetition_sans_core.py` | `pytest` : le script joué sans le core (passerelle factice). |

## Différences voulues avec un vrai téléphone

- La connexion vient de 127.0.0.1, que le core approuverait en silence : `gateway.nodes.pairing.autoApproveLocal`
  est à `false`, ce qui impose l'approbation explicite d'un téléphone distant.
- L'identité de l'appareil est neuve à chaque exécution ; l'attente entre deux tentatives est pilotée par le script.
- Le fournisseur de modèles et les embeddings pointent vers un port fermé : aucun tour d'agent n'est joué, seule la
  porte d'appareil est exercée.

## Ce que `pytest tests/e2e_core` prouve, et ne prouve pas

Il joue tout ce qui est Python pour de vrai (commandes du socle, chantier, moteur en processus, trajet HTTP) contre
une passerelle factice. Il ne prouve rien du core : le démarrage du Gateway, `openclaw qr`, la poignée de main,
l'approbation et le comportement réel des deux routes ne sont prouvés que par la CI du core.
