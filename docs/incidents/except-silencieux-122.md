# Fermeture des 6 `except`-silencieux révélés par le gate no-stub v2

Issue : #122. Origine : balayage des 140 `.py` du dépôt par le vérificateur AST du gate
no-stub v2 (`~/proof-method`, story NOSTUB-V2) — 9 signalements, dont 3 de la classe légitime
`log_message` (documentée au README du gate) et **6 `except Exception: pass`** traités ici.

## Les deux défauts réels : des tests qui avalaient l'échec de l'appel testé

**M1 `test_digest.py`** — `try/except Exception` autour de `statut(id_inconnu)` : le test
passait quel que soit le comportement. Contrats **mesurés** : le moteur réel retourne
`'STATUT_INCONNU'` et ne lève jamais ; le mock lève `LookupError`. Deux contrats **divergents** —
c'est précisément pourquoi l'auteur avait posé un except fourre-tout au lieu de choisir.
Correctif : une assertion **explicite par implémentation** (`pytest.raises(LookupError)` pour le
mock, égalité stricte pour le réel).

**core `test_vault_unit.py`** — `load_settings` sous `except Exception: pass`, toutes les
assertions conditionnées à `settings is not None` : un crash quelconque faisait passer le test
**vide**. Mesuré : la branche réelle du contrat « rejette OU caviarde » est le **rejet**
(`SettingsError`). Correctif : `except cfg.settings.SettingsError` explicite, assertion
inconditionnelle `rejete or settings is not None`, toute autre exception fatale.

Preuve par mutation, dans les deux cas : faire lever l'appel testé (RuntimeError) rend le test
**rouge** — l'ancien `except` l'avalait.

## Les quatre `except` larges rétrécis (fail-soft conservé, masquage supprimé)

| Site | Avant | Après |
|---|---|---|
| `aeo_engine.py` (JSON-LD) | `except Exception` | `except ValueError` (JSONDecodeError en est une sous-classe) |
| `consensus_run.py` (sonde cache) | `except Exception` | `except (OSError, ValueError)` |
| `consensus_run.py` (archive brute) | `except Exception: pass` | `except OSError` + **avertissement stderr** — l'archive est un artefact de preuve, sa perte doit être visible |
| `dashboard_server.py` (config) | `except Exception` | `except (OSError, yaml.YAMLError)` — c'est du **YAML** (l'issue supposait JSON) et la garde `isinstance` rend KeyError/TypeError impossibles |

## Incident crew

Sur 6 blocs AVANT exigés verbatim, le crew en a **fabriqué 5** (variables inventées :
`cache_path`, `archive_path`, `config_path` ; indentation fausse). Greffe refusée en bloc ;
application mécanique sur les vrais ancrages avec les contrats mesurés de la spec. Et son
correctif du site 1 appelait `statut()` inconditionnellement — il aurait planté en ERROR sur le
mock ; corrigé après mesure du mock.

## Critère d'acceptation

Le balayage du gate v2 sur le dépôt ne rapporte plus que les 3 `log_message` (classe légitime).
Toutes les suites vertes : M1 331, core/config 16, M7 432, M2 533, scripts 10, e2e 10,
dashboard 38.
