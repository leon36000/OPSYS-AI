# Inventaire des licences et chaîne d'approvisionnement

Relevé du 2026-11-01, base `5208490a4`, **hors ligne**. Ce document décrit ce que le dépôt contient réellement ; il
n'est pas un avis juridique (voir [QUESTIONS-AVOCAT](QUESTIONS-AVOCAT.md)). Une licence n'est dite « connue » que si une
source la porte : métadonnées d'un paquet installé, champ `license` d'un verrou npm, ou déclaration écrite d'un
document du dépôt. **Aucune licence n'a été revérifiée sur son site d'origine** (aucun accès réseau).

## Ce qui est produit et ce qui le contrôle

| Élément | Fichier | Rôle |
|---|---|---|
| SBOM CycloneDX 1.5 | [`sbom.cdx.json`](sbom.cdx.json) | Composants, portée (`required` / `optional` / `excluded`), licence et **niveau de vérification** de chacun |
| Générateur | `scripts/compliance/generer_sbom.py` | Stdlib, sans horloge ni réseau ; `--ecrire`, `--verifier`, `--rapport` |
| Relevé de licences installées | `scripts/compliance/collecter_constats.py` | Lit les `METADATA` et `package.json` d'une machine ; écrit [`donnees/constats-licences.json`](donnees/constats-licences.json) |
| Politique | [`donnees/politique-licences.json`](donnees/politique-licences.json) | Classes de licences, motifs interdits, décisions, écarts ouverts, services séparés |
| Hors gestionnaires | [`donnees/composants-hors-gestionnaire.json`](donnees/composants-hors-gestionnaire.json) | Images Docker, paquets système, plugin WordPress, notices du core |
| Dette visible | [`donnees/non-verifiees-reconnues.json`](donnees/non-verifiees-reconnues.json) | Composants de production dont aucune source ne porte la licence |
| Registre des fournisseurs | [`REGISTRE-FOURNISSEURS-LICENCES.md`](REGISTRE-FOURNISSEURS-LICENCES.md) | Audit du catalogue de modèles et d'outils |
| Garde | `tests/test_conformite_licences.py`, `tests/test_registre_fournisseurs_licences.py` | Échouent sur une dérive |

Régénérer après un changement de verrou : `python scripts/compliance/generer_sbom.py --ecrire`. Si un composant de
production nouveau n'a aucune licence connue, le test échoue : relever sa licence (`collecter_constats.py` sur une machine
qui l'a installé) ou, en dernier recours et avec une raison, `--reconnaitre-non-verifiees` (voir l'aide du script).

## Chiffres du relevé

| Écosystème | Portée | Composants | Dont licence non vérifiée |
|---|---|---:|---:|
| Python (`pypi`) | production (`requirements-runtime.lock.txt`) | 60 | 11 |
| Python (`pypi`) | optionnel (extras `embeddings-local`, `ingestion-pdf`) | 18 | 5 |
| Python (`pypi`) | développement (pytest, ruff, pluggy…) | 5 | 0 |
| OPSYS-CORE (`npm-core`) | production (fermeture de `core/pnpm-lock.yaml`) | 927 | 67 |
| OPSYS-CORE (`npm-core`) | développement | 607 | 146 |
| Mobile (`npm-mobile`) | production du verrou (inclut l'outillage Expo) | 546 | 0 |
| Mobile (`npm-mobile`) | développement | 223 | 1 |
| Hors gestionnaire | images, paquets système, notices, plugin | 22 | 7 |

Total : **2 386** composants de gestionnaires et **22** composants hors gestionnaire dans le SBOM.

« Non vérifiée » veut dire qu'aucune source locale ne porte la licence : c'est une **dette**, pas une licence acceptable.
Pour OPSYS-CORE, 66 des 67 n'étaient pas installés sur la machine du relevé (binaires propres à une plateforme comme koffi, lancedb ou
node-pty, et une quinzaine de versions plus récentes que celles de l'autre copie de travail, surtout des correctifs de sécurité comme
`undici`, `zod`, `qs`, `joi`), et le dernier est `khroma`, sans champ `license`. Pour Python, ce sont
`matplotlib` et ses dépendances (tirées par `pyvrp`), `huggingface-hub` et ses dépendances, `pywin32`, `pyreadline3`, `tzdata`,
`vrplib`, `httpx2-jsfetch`.

## Sources de l'information

- **Python** : fichiers `METADATA` des `*.dist-info` du venv du dépôt, du cache `uv` de la session et des caches `uv` de
  l'utilisateur, à version identique à celle du verrou (63 sur 83 versions). `numpy`, `onnxruntime`, `tokenizers` et `pyvrp`
  sont déclarés par `docs/research/INGREDIENTS.md` (niveau `documentation_depot`, non revérifié). Les verrous `uv.lock` et
  `requirements*.lock.txt` ne portent **aucune** licence.
- **OPSYS-CORE** : `package.json` d'un magasin pnpm installé dans une autre copie de travail, nom et version identiques à ceux du
  verrou (1 322 versions). `pnpm-lock.yaml` ne porte aucune licence.
- **Mobile** : le champ `license` de `mobile/package-lock.json`.
- **Images Docker** : déclarations de `docs/research/INGREDIENTS.md` et commentaires des fichiers Compose ; les images de base
  n'ont **aucun** inventaire.

## Risques par classe (production et optionnel)

| Classe | Composants | Règle de la politique |
|---|---|---|
| Permissive (MIT, Apache-2.0, BSD, ISC…) | 1 443 | Respecter avis et attribution |
| Copyleft faible (MPL-2.0, LGPL) | 24 | Décision écrite par composant (`decisions_copyleft_faible`) |
| Copyleft fort (GPL, AGPL, SSPL) | 1 | **Écart ouvert** : `libsignal` |
| Usage restreint (BSL, CC-NC, « non commercial ») | 0 | Interdit |
| Licence inconnue | 83 | Dette visible |

Détail à connaître :

- **`libsignal@6.0.0` (GPL-3.0)** : dépendance transitive `extensions/whatsapp → baileys → libsignal` du verrou du core. Le relevé
  n'établit pas si l'image livrée embarque cette extension. Contraire à la règle AGENTS.md si elle l'embarque. **Écart ouvert, non
  corrigé** : décision de l'architecte ou du propriétaire (retirer l'extension, l'isoler, ou obtenir un avis).
- **LGPL** : `psycopg` et `psycopg-binary` 3.2.3 (LGPL-3.0, extra `postgres` du runtime), `codec-parser` (LGPL-3.0 ou ultérieure, via
  WhatsApp). Toléré par AGENTS.md pour une dépendance dynamique non modifiée.
- **MPL-2.0** : `certifi`, `tqdm`, `@novnc/novnc` (**patché localement**), `@ubjs/*`, `mediabunny`, `web-push`, `lightningcss` (outillage mobile).
- **Doubles licences** : `jszip` et `@zone-eu/mailsplit` (MIT choisi), `cryptography` (BSD-3-Clause choisi), `packaging`, `node-forge` du mobile.
- **Identifiants non SPDX** : `BSD` (mpmath, sympy), `Apache` (sqlite-vec « MIT OR Apache »), `BSD` sans variante (colorama, reportlab) ;
  acceptés comme permissifs par la politique, **à normaliser**.
- **`khroma@2.1.0`** : aucun champ `license` dans son `package.json` (dépendance de `mermaid`).

## Usage

- **Exécution** : Python et OPSYS-CORE s'exécutent sur le serveur du client.
- **Distribution** : l'image Docker, l'installateur et l'application mobile sont livrés à des tiers (le client, ses employés). La
  distribution est ce qui déclenche les obligations de licence.
- **Service à des tiers** : c'est le cas des modèles de génération (registre des fournisseurs, colonne « service à des tiers »),
  et il reste `incertain` pour toute licence maison.

## Écarts avec les notices et documents de licence existants

- Le brief de cette tâche cite `docs/LICENCES.md` et « 239 notices tierces ». **Aucun de ces deux éléments n'existe** dans le dépôt
  à cette base. Les notices tierces existantes sont : `core/NOTICE`, `core/THIRD_PARTY_NOTICES.md` (**3 notices** : Pi/pi-mono, GitHub
  Octicons, Three.js), `core/ui/public/licenses/three-MIT.txt`, `core/ui/public/provider-icons/ATTRIBUTION.md`,
  `mobile/vendor/PROVENANCE.json` et les `LICENSE` de `mobile/vendor/*`. Aucun fichier ne regroupe les avis de droit d'auteur des
  quelque 1 500 paquets de production : question B13 de [QUESTIONS-AVOCAT](QUESTIONS-AVOCAT.md).
- **Licence du dépôt** : `LICENSE` est Apache-2.0, ADR-0003 décide « propriétaire », `README.md` dit que les deux se contredisent.
  Écart ouvert, décision du propriétaire.
- `core/THIRD_PARTY_NOTICES.md` dit lui-même que le contenu du paquet construit contenant Three.js n'a pas été vérifié.
- Les 52 icônes `ProviderIcon-*.svg` copiées de CodexBar : attribution sans licence recopiée.
- Les recherches de licences antérieures (`docs/research/R22`, `R35`, `AVATAR-AUDIO-LICENCES-2026-10-02.md`) sont des preuves datées de
  leur sujet ; elles ne remplacent pas ce relevé.

## Plugin WordPress (GPL-2.0-or-later, isolé)

`integrations/wordpress/opsys-connect/` est distribué hors du paquet Python, sans import de code Python, et dialogue en HTTP signé.
La politique l'admet **parce que** le composant déclare son isolement ; c'est une position de politique, à confirmer (B6).

## Polices et modèles

- Aucune police n'est livrée ; le studio n'accepte que `OFL-1.1` (`polices.py`).
- Les modèles et outils du catalogue sont dans le [registre](REGISTRE-FOURNISSEURS-LICENCES.md) : code et poids, seuils, territoires,
  service à des tiers, source, date. 30 des 66 lignes sont **non vérifiées à la source**.

## Limites

- Les relevés viennent d'une machine, à un moment : une autre résolution de verrou peut changer des versions.
- Les roues binaires et images contiennent des composants que ces métadonnées ne détaillent pas.
- Le classement `production` du verrou mobile et du verrou pnpm suit les dépendances déclarées ; il ne prouve pas ce que contient
  l'artefact final.
- Rien ici ne remplace la lecture des textes de licence par une personne qualifiée.
