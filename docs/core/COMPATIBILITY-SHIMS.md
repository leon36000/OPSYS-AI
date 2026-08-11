# Compatibility shims — authz/ et config/ (C04-003)

## Pourquoi

Le modular monolith (C04-001, `core/dependency-rules.toml`) interdit
les accès privés intermodules et impose des ports provider-neutral.
`auth/`, `authz/`, `config/` pré-existent avant la phase C03 et ne sont
pas encore encapsulés derrière ces ports — exception `legacy_pre_core`
documentée dans `dependency-rules.toml`. C04-003 résorbe cette
exception **partiellement** : `authz/` et `config/` seulement.

`auth/` (`admin_gate.py`, `totp.py`) **reste hors périmètre** — ni dans
les Sorties exactes ni dans les Interfaces de `tasks/C04-003.md`.
Raison technique mesurée : `auth/admin_gate.py` fait `import totp`
(absolu, sans paquet) et `auth/` n'a pas de `__init__.py` — ce n'est
pas un paquet importable aujourd'hui. L'encapsuler exigerait de
modifier ce code hérité (ajouter un `__init__.py`, réparer l'import),
ce que C04-003 s'interdit explicitement (« ajouter adapters sans
déplacer l'ancien code »). Reste dans l'exception `legacy_pre_core`,
**aucune tâche ne le résorbe à ce jour**.

## `LegacyAuthzAdapter` (`core/src/opsys_core/compat/authz.py`)

Encapsule `authz.domain_api.DomainAuthz` (import direct, jamais copié
ni déplacé) derrière une surface unique :

```python
adapter = LegacyAuthzAdapter(DomainAuthz(LocalAuthzEngine()))
adapter.authorize(user, "lire", obj, scope)  # -> bool
```

- `permission` ∈ `{"lire", "ecrire", "administrer", "voir_couts"}` —
  dispatch vers la méthode `peut_*` correspondante de `DomainAuthz`.
- **Deny-by-default préservé verbatim** : utilisateur sans rôle,
  `user` vide/`None`, tenant différent → `False` sans exception (c'est
  le comportement HISTORIQUE et TESTÉ du moteur encapsulé, pas une
  décision du shim).
- **Permission hors vocabulaire → `PermissionLegacyNonSupportee`**
  (jamais un `False` silencieux) : un `False` masquerait
  l'incapacité du shim à traduire l'appel derrière un refus légitime.
  Le message énumère les permissions supportées.
- Ne journalise pas les décisions : `DomainAuthz._log_decision` le
  fait déjà (hash tronqué de l'utilisateur, jamais l'id en clair).

## `LegacyConfigAdapter` (`core/src/opsys_core/compat/config.py`)

Encapsule `config.settings.load_settings` derrière une surface unique.
Le `SecretProvider` est lié au **constructeur**, jamais passé par
appel :

```python
adapter = LegacyConfigAdapter(EnvSecretProvider())
settings = adapter.load(Path("settings.yaml"))  # -> Settings
```

Le provider est **stateful** (`EnvSecretProvider._cache` accumule les
secrets résolus) — ce cache est ce que `load_settings`/`safe_traceback`
consultent pour rédiger les secrets dans les erreurs **futures**. Un
provider neuf par appel repartirait avec un cache vide : régression de
sécurité mesurable, pas un choix de style.

### Limitations du code encapsulé (documentées, jamais corrigées en silence)

| Limitation | Comportement du shim |
|---|---|
| `FileNotFoundError` levée par `load_settings` **hors** de son bloc try/except qui rédige | Traverse le shim **telle quelle**, jamais reclassée en `SettingsError` — reclasser masquerait une asymétrie déjà présente dans le code hérité |
| Schéma figé à 4 champs (`mode`, `endpoint`, `timeout`, `litellm_key`) | Toute autre clé YAML est silencieusement ignorée par le code hérité — non corrigé |
| Un seul secret résolu, nom `litellm_key` codé en dur | Non corrigé |
| `raise SettingsError(...) from None` supprime la chaîne d'exception d'origine | Non corrigé — le type d'origine est irrécupérable par l'appelant |
| Heuristique `len(secret_name) > 40` rejette un **nom** de secret légitimement long | Non corrigé |

Aucune de ces limitations n'est réparée par ce shim : « ajouter
adapters sans déplacer l'ancien code » interdit de modifier le
comportement du code encapsulé. Un durcissement réel de `config/`
serait une tâche future dédiée, avec son propre cas RED.

## Ports — volontairement non implémentés

`LegacyAuthzAdapter`/`LegacyConfigAdapter` n'implémentent aucun des 3
`Protocol` de `core/src/opsys_core/ports/contracts.py`
(`DomainPort`/`ProviderPort`/`ModulePort`) : `tasks/C04-003.md` ne les
cite ni dans ses Sources ni dans ses Interfaces, et les 3 Protocol ne
portent aujourd'hui qu'une propriété d'identifiant, aucune méthode
métier (peuplés par C04-004 et suivantes, jamais devinés en avance —
même discipline anti-sur-spécification que C04-001). Si un besoin réel
apparaît (ex. C04-004 introduit un registre de providers), la
conformité à un port sera une décision de cette tâche future, prise
avec son besoin sous les yeux.

## Portée de la résorption

| Composant | Statut |
|---|---|
| `authz/` | Résorbé (ce shim) |
| `config/` | Résorbé (ce shim) |
| `auth/` (`admin_gate.py`, `totp.py`) | **Non résorbé** — reste dans l'exception `legacy_pre_core`, aucune tâche assignée à ce jour |
