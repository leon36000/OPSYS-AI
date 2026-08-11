"""Tests pour core/src/opsys_core/compat/{authz,config}.py (C04-003)
— shims de compatibilité encapsulant authz/ et config/ existants sans
les déplacer, imposés par le modular monolith (C04-001).

Couvre les 3 cas RED obligatoires de tasks/C04-003.md :
  1. tests historiques authz/config restent verts (mesurés hors ce
     fichier, cf. REPLAY.md — 45 tests dans core/src/{authz,config}/tests
     avant toute modification de ce tour) — CE fichier prouve en plus
     l'ÉQUIVALENCE comportementale à travers la surface neuve (cas _1).
  2. aucun renommage massif (cas _2 : identité d'objet + signatures
     gelées des symboles hérités).
  3. le shim signale les limitations au lieu de les masquer (cas _3).

Conception revue par architecture AVANT code (subagent `architecte`,
Claude Opus 5 natif) — verdict complet dans l'Evidence Bundle. DEUX
points de sa revue ont été vérifiés PUIS CORRIGÉS avant ce code (jamais
appliqués sur la seule autorité du reviewer, cf. CLAIMS UNVERIFIED) :
  - Le point « BLOQUANT » sur une collision de nom de module mypy sans
    `compat/__init__.py` a été réfuté empiriquement : `mypy --ignore-
    missing-imports core/` (argv exact du gate, mypy 2.1.0, aucune
    config namespace_packages dans ce dépôt) ne produit AUCUNE erreur
    avec ou sans `__init__.py` dans compat/ (namespace packages PEP 420
    implicites par défaut sur cette version). `compat/__init__.py` est
    néanmoins conservé, pour la SEULE raison de cohérence avec
    ports/authority/status (tous ont un __init__.py) — pas pour éviter
    une collision qui n'existe pas.
  - Le point sur core-ci.yml qui n'exécuterait « aucun job » sur
    core/tests/architecture/ décrivait l'état PRÉ-C04-002 : C04-002
    (déjà mergé, commit de base de cette tâche) a câblé
    `core/tests/architecture` dans le job `tests` de core-ci.yml (SANS
    continue-on-error) — ce fichier de test s'exécute donc déjà
    bloquant en CI dès son ajout, aucune extension supplémentaire
    requise sur ce point.
  - Restent vrais et vérifiés indépendamment : le test d'union exacte
    des couches de test_dependency_rules.py (orphelins) exige que
    core/src/opsys_core/compat/ soit déclaré dans dependency-rules.toml
    (sinon rouge sur un test déjà mergé, hors périmètre de ce fichier
    de test) ; les tests historiques authz/config ne sont exécutés en
    CI QUE via le job `e2e` de ci.yml, qui porte `continue-on-error:
    true` — aucun garde-fou CI bloquant sur le cas RED 1 aujourd'hui,
    la preuve vient de l'exécution locale capturée (REPLAY.md).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Aucun conftest.py sous core/ (mesuré) : chaque fichier de test qui a
# besoin de opsys_core.* insère core/src lui-même, comme
# test_dependency_rules.py:58 — jamais de dépendance à l'ordre de
# collecte des autres fichiers de test.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from authz.domain_api import DomainAuthz
from authz.engine import LocalAuthzEngine
from authz.model import ObjectRef, ObjectType, Relation, TenantScope
from config.settings import Settings, SettingsError, load_settings
from config.vault import EnvSecretProvider, SecretProvider

from opsys_core.compat.authz import LegacyAuthzAdapter, PermissionLegacyNonSupportee
from opsys_core.compat.config import LegacyConfigAdapter

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORE_SRC = _REPO_ROOT / "core" / "src"


# ---------------------------------------------------------------------------
# Fixtures partagées
# ---------------------------------------------------------------------------


@pytest.fixture
def scope():
    return TenantScope("tenant-c04-003")


@pytest.fixture
def obj():
    return ObjectRef(ObjectType.DASHBOARD, "dash-c04-003")


@pytest.fixture
def engine():
    return LocalAuthzEngine()


@pytest.fixture
def domain(engine):
    return DomainAuthz(engine)


@pytest.fixture
def adapter(domain):
    return LegacyAuthzAdapter(domain)


# ---------------------------------------------------------------------------
# Cas RED 1 — snapshot d'équivalence (authz)
# ---------------------------------------------------------------------------


def test_encapsuler_authz_et_config_existants_par_compatibilit_1(engine, domain, adapter, scope, obj):
    """Le shim n'ajoute ni ne retire rien : pour les 4 relations × les 4
    permissions, adapter.authorize(...) est identique (is) à l'appel
    direct de la méthode peut_* correspondante ET à la valeur littérale
    attendue (snapshot, pas seulement une équivalence relative — sans
    la valeur littérale, une panne identique des deux côtés passerait).
    Inclut le cas 'aucun tuple' et les entrées non nominales user=None
    et user=''. Ligne EDITOR incluse spécifiquement parce que
    lire=True/administrer=False DIVERGENT — sans cette ligne, une
    inversion de deux entrées de _DISPATCH resterait invisible
    (mutation invisible si la source est déjà triée)."""
    engine.add_tuple("owner", Relation.OWNER, obj, scope)
    engine.add_tuple("editor", Relation.EDITOR, obj, scope)
    engine.add_tuple("viewer", Relation.VIEWER, obj, scope)
    engine.add_tuple("admin", Relation.ADMIN, obj, scope)

    matrice = {
        ("owner", "lire"): True, ("owner", "ecrire"): True,
        ("owner", "administrer"): True, ("owner", "voir_couts"): True,
        ("editor", "lire"): True, ("editor", "ecrire"): True,
        ("editor", "administrer"): False, ("editor", "voir_couts"): False,
        ("viewer", "lire"): True, ("viewer", "ecrire"): False,
        ("viewer", "administrer"): False, ("viewer", "voir_couts"): False,
        ("admin", "lire"): True, ("admin", "ecrire"): True,
        ("admin", "administrer"): True, ("admin", "voir_couts"): True,
        ("inconnu", "lire"): False, ("inconnu", "ecrire"): False,
        ("inconnu", "administrer"): False, ("inconnu", "voir_couts"): False,
    }
    for (user, permission), attendu in matrice.items():
        via_adapter = adapter.authorize(user, permission, obj, scope)
        via_domain = getattr(domain, f"peut_{permission}")(user, obj, scope)
        assert via_adapter is attendu, f"{user}/{permission}: adapter={via_adapter!r} attendu={attendu!r}"
        assert via_domain is attendu, f"{user}/{permission}: domain={via_domain!r} attendu={attendu!r} (le moteur a changé, pas le shim)"
        assert via_adapter is via_domain, f"{user}/{permission}: adapter et domain divergent"

    # Entrées non nominales : deny-by-default du moteur préservé verbatim.
    assert adapter.authorize(None, "lire", obj, scope) is False
    assert adapter.authorize("", "lire", obj, scope) is False


# ---------------------------------------------------------------------------
# Cas RED 2 — aucun renommage massif, aucun déplacement
# ---------------------------------------------------------------------------


def test_encapsuler_authz_et_config_existants_par_compatibilit_2():
    """Aucun renommage massif, aucun déplacement — deux preuves
    indissociables sur deux mécanismes différents :
    (a) Le symbole manipulé par compat/ EST celui du module hérité —
    un import, jamais une copie/un fork. Preuve directe de 'ajouter
    adapters sans déplacer l'ancien code' (comparaison `is`, pas ==).
    (b) Signatures et noms publics des symboles encapsulés épinglés
    via inspect.signature — un renommage dans authz/ ou config/ casse
    ce test. Aucun test hérité ne vérifie les signatures (ils vérifient
    le comportement) : zéro doublon de couverture avec les tests
    historiques."""
    import inspect

    import authz.domain_api as authz_domain_api_direct
    import config.settings as config_settings_direct
    import opsys_core.compat.authz as compat_authz
    import opsys_core.compat.config as compat_config

    # (a) identité d'objet, pas copie.
    assert compat_authz.DomainAuthz is authz_domain_api_direct.DomainAuthz
    assert compat_config.load_settings is config_settings_direct.load_settings

    # (b) signatures et noms publics gelés.
    params_check = list(inspect.signature(type(LocalAuthzEngine()).check).parameters)
    assert params_check == ["self", "user", "permission", "obj", "scope"]

    params_load = list(inspect.signature(load_settings).parameters)
    assert params_load == ["yaml_path", "provider"]

    for methode in ("peut_lire", "peut_ecrire", "peut_administrer", "peut_voir_couts"):
        assert hasattr(DomainAuthz, methode), f"DomainAuthz.{methode} absente — renommage détecté"


# ---------------------------------------------------------------------------
# Cas RED 3 — limitation signalée, jamais un refus masqué
# ---------------------------------------------------------------------------


def test_encapsuler_authz_et_config_existants_par_compatibilit_3(engine, domain, adapter, scope, obj):
    """Quatre assertions indissociables (chacune seule est insuffisante) :
    (a) permission inconnue -> exception dédiée qui ÉNUMÈRE les
    permissions supportées (signale) ; (b) le MÊME moteur, sondé
    directement, garde son deny-by-default sans exception (l'historique
    n'est pas cassé — deux surfaces différentes) ; (c) contrôle négatif :
    un refus LÉGITIME (permission connue, utilisateur sans rôle) ne lève
    PAS — sinon un shim qui lèverait sur tout passerait (a) sans rien
    prouver ; (d) garde de dérive comportementale : OWNER est autorisé
    sur exactement les 4 permissions connues du moteur et refusé
    (sans lever) sur toute permission inconnue de lui — prouve que
    _DISPATCH == vocabulaire réel du moteur SANS jamais importer le nom
    privé _PERMISSION_RELATIONS (l'import serait lui-même un accès privé
    inter-paquet, contraire à la mission de la phase C04)."""
    engine.add_tuple("owner", Relation.OWNER, obj, scope)

    # (a) signale, message énumère les permissions supportées.
    with pytest.raises(PermissionLegacyNonSupportee, match="voir_couts") as exc_info:
        adapter.authorize("owner", "supprimer", obj, scope)
    for permission_connue in ("lire", "ecrire", "administrer", "voir_couts"):
        assert permission_connue in str(exc_info.value)

    # (b) même moteur, sondé directement : deny-by-default intact, sans exception.
    assert engine.check("owner", "supprimer", obj, scope) is False

    # (c) contrôle négatif : refus légitime, PAS de levée.
    assert adapter.authorize("personne-sans-role", "administrer", obj, scope) is False

    # (d) garde de dérive : OWNER traverse les 4 permissions connues sans lever.
    for permission_connue in ("lire", "ecrire", "administrer", "voir_couts"):
        resultat = adapter.authorize("owner", permission_connue, obj, scope)
        assert resultat is True, f"OWNER devrait être autorisé sur {permission_connue}"
    for permission_inconnue in ("supprimer", "exporter", "archiver"):
        with pytest.raises(PermissionLegacyNonSupportee):
            adapter.authorize("owner", permission_inconnue, obj, scope)


# ---------------------------------------------------------------------------
# Config — symétrique de _1/_2/_3, mêmes disciplines
# ---------------------------------------------------------------------------


def test_config_adapter_identique_a_l_appel_direct(tmp_path, monkeypatch):
    """Symétrique du cas _1 côté config : LegacyConfigAdapter(provider)
    .load(p) rend un Settings dont les 4 champs sont identiques à
    load_settings(p, provider), et le MÊME SecretRef (SecretRef.__eq__
    compare nom+valeur, vault.py) — pas une resource distincte."""
    monkeypatch.setenv("OPSYS_LITELLM_KEY", "valeur-a-rediger-test-c04-003")
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(
        "mode: dev\nendpoint: http://localhost:9000\ntimeout: 42\nlitellm_key: litellm_key\n"
    )

    provider_direct = EnvSecretProvider()
    settings_direct = load_settings(yaml_path, provider_direct)

    provider_adapter = EnvSecretProvider()
    adapter_config = LegacyConfigAdapter(provider_adapter)
    settings_via_adapter = adapter_config.load(yaml_path)

    assert isinstance(settings_via_adapter, Settings)
    assert settings_via_adapter.mode == settings_direct.mode
    assert settings_via_adapter.endpoint == settings_direct.endpoint
    assert settings_via_adapter.timeout == settings_direct.timeout
    assert settings_via_adapter.litellm_key == settings_direct.litellm_key


def test_config_adapter_provider_au_constructeur_prouve_par_l_etat_du_provider(tmp_path, monkeypatch):
    """Le provider est STATEFUL (vault.py: _cache accumule les secrets
    résolus). Preuve DIRECTE sur l'état du provider lui-même — pas
    indirecte via un message d'erreur (une version antérieure de ce
    test asserte l'absence du secret dans un message d'erreur « secret
    absent », qui ne contient JAMAIS de valeur de secret par
    construction quel que soit l'état du cache : l'assertion était
    vraie même avec un provider neuf par appel, donc ne prouvait rien
    — objection Kimi-K3 tour 1, confirmée par relecture de
    load_settings/safe_traceback, corrigée ici)."""
    monkeypatch.setenv("OPSYS_LITELLM_KEY", "secret-a-rediger-c04-003")
    yaml_ok = tmp_path / "ok.yaml"
    yaml_ok.write_text("mode: dev\nendpoint: http://localhost:9000\ntimeout: 1\nlitellm_key: litellm_key\n")
    yaml_manquant = tmp_path / "manquant.yaml"
    yaml_manquant.write_text("mode: dev\nendpoint: http://localhost:9000\ntimeout: 1\nlitellm_key: absent_du_provider\n")

    provider = EnvSecretProvider()
    adapter_config = LegacyConfigAdapter(provider)

    assert provider.known_secret_values() == [], "rien ne devrait être résolu avant le premier load"

    settings = adapter_config.load(yaml_ok)
    assert settings.litellm_key.reveal("test-c04-003") == "secret-a-rediger-c04-003"
    assert "secret-a-rediger-c04-003" in provider.known_secret_values(), (
        "le premier load doit résoudre et mettre en cache le secret sur LE provider de l'adapter"
    )

    with pytest.raises(SettingsError):
        adapter_config.load(yaml_manquant)
    # Preuve du lien constructeur : le cache du PREMIER load survit au
    # SECOND appel .load() (même en échec) — c'est le même objet
    # provider, jamais recréé par appel. Un provider neuf par appel
    # repartirait avec un cache VIDE : cette assertion échouerait.
    assert "secret-a-rediger-c04-003" in provider.known_secret_values(), (
        "le cache du premier secret a disparu — le provider n'a pas survécu entre les deux appels"
    )


def test_config_adapter_signale_fichier_absent_sans_le_masquer_en_settingserror(tmp_path):
    """Limitation signalée, pas masquée (même discipline que le cas RED
    3 côté authz) : load_settings lève FileNotFoundError HORS du bloc
    try/except qui rédige (settings.py) — le shim NE reclasse PAS cette
    exception en SettingsError, il la laisse passer telle quelle. La
    reclasser masquerait une asymétrie déjà présente dans le code
    hérité ; documentée dans docs/core/COMPATIBILITY-SHIMS.md plutôt
    que corrigée (le code encapsulé n'est pas modifié par cette tâche)."""
    adapter_config = LegacyConfigAdapter(EnvSecretProvider())
    chemin_absent = tmp_path / "n-existe-pas.yaml"
    with pytest.raises(FileNotFoundError):
        adapter_config.load(chemin_absent)


def test_config_limitations_documentees_sont_reellement_exercees(tmp_path, monkeypatch):
    """Objection Kimi-K3 tour 1 confirmée : le test de croisement
    code<->doc ci-dessous ne vérifiait que la PRÉSENCE de 6 termes
    génériques dans COMPATIBILITY-SHIMS.md, jamais que les limitations
    du tableau soient réellement EXERCÉES par un test — 4 des 5 ne
    l'étaient par aucun test du fichier. Fermé ici, 4 assertions
    indépendantes, une par limitation documentée non encore exercée."""
    monkeypatch.setenv("OPSYS_LITELLM_KEY", "secret-a-rediger-c04-003")
    adapter_config = LegacyConfigAdapter(EnvSecretProvider())

    # (a) Schéma figé à 4 champs : une 5e clé YAML est SILENCIEUSEMENT
    # ignorée (Settings.__slots__ n'a que mode/endpoint/timeout/
    # litellm_key — aucune trace de la clé en trop, ni erreur ni attribut).
    yaml_extra = tmp_path / "extra.yaml"
    yaml_extra.write_text(
        "mode: dev\nendpoint: http://localhost:9000\ntimeout: 1\n"
        "litellm_key: litellm_key\nclef_inconnue_ignoree: valeur\n"
    )
    settings = adapter_config.load(yaml_extra)
    assert not hasattr(settings, "clef_inconnue_ignoree"), (
        "une 5e clé YAML a fui sur l'objet Settings — le schéma n'est plus figé à 4 champs"
    )
    assert settings.__slots__ == ("mode", "endpoint", "timeout", "litellm_key"), (
        "Settings.__slots__ a changé — (b) un seul secret nommé en dur (litellm_key) n'est plus vrai"
    )

    # (c) Chaîne d'exception supprimée : `raise SettingsError(...) from
    # None` — objection Kimi-K3 tour 2 CONFIRMÉE par mesure directe
    # (interpréteur) : `__cause__ is None` est vrai à la fois pour
    # `from None` ET pour un `raise` nu (sans from du tout) dans un
    # except — ça ne discriminait rien. Le marqueur sémantique RÉEL de
    # `from None` est `__suppress_context__ is True` (vérifié :
    # `from None` -> suppress_context=True ; `raise` nu ->
    # suppress_context=False, les deux avec cause=None). `__context__`
    # non-None prouve en plus qu'une exception d'origine existait bien
    # (le mécanisme s'est déclenché, pas un cas où rien n'a été levé).
    yaml_secret_absent = tmp_path / "absent.yaml"
    yaml_secret_absent.write_text(
        "mode: dev\nendpoint: http://localhost:9000\ntimeout: 1\nlitellm_key: jamais_resolu\n"
    )
    with pytest.raises(SettingsError) as exc_info:
        adapter_config.load(yaml_secret_absent)
    assert exc_info.value.__cause__ is None, (
        "SettingsError porte encore sa cause d'origine explicite"
    )
    assert exc_info.value.__suppress_context__ is True, (
        "'from None' devrait activer __suppress_context__ — sans lui, un raise nu produirait le même __cause__ is None"
    )
    assert exc_info.value.__context__ is not None, (
        "aucune exception d'origine détectée — le mécanisme redact/wrap ne s'est pas déclenché"
    )

    # (d) Heuristique len(secret_name) > 40 : rejette un NOM de secret
    # légitimement long (pas sa VALEUR) comme s'il s'agissait d'une
    # valeur inline suspecte. Objection Kimi-K3 tour 2 CONFIRMÉE par
    # mesure directe : un pytest.raises(SettingsError) nu ne discrimine
    # PAS cette branche de la branche "secret introuvable" (les deux
    # lèvent SettingsError) — le message texte, lui, diffère
    # ("Inline secret value" pour l'heuristique vs "Secret '...' not
    # found" pour l'absence), mesuré directement sur load_settings.
    nom_secret_trop_long = "x" * 41
    yaml_nom_long = tmp_path / "nom_long.yaml"
    yaml_nom_long.write_text(
        f"mode: dev\nendpoint: http://localhost:9000\ntimeout: 1\nlitellm_key: {nom_secret_trop_long}\n"
    )
    with pytest.raises(SettingsError, match="Inline secret value"):
        adapter_config.load(yaml_nom_long)


# ---------------------------------------------------------------------------
# Croisement code <-> doc, garde de layer, non-régression du gate d'union
# ---------------------------------------------------------------------------


def test_compatibility_shims_md_existe_et_documente_les_limitations_reelles():
    """Croisement DOCUMENTAIRE (présence des termes), complémentaire du
    test d'EXERCICE ci-dessus (test_config_limitations_documentees_
    sont_reellement_exercees) — les deux sont nécessaires, ni l'un ni
    l'autre ne suffit seul (objection Kimi-K3 tour 1 : le docstring
    précédent prétendait que CE test-ci exerçait les limitations, ce
    qu'il n'a jamais fait — corrigé en scindant clairement les deux
    responsabilités)."""
    doc = (_REPO_ROOT / "docs" / "core" / "COMPATIBILITY-SHIMS.md").read_text(encoding="utf-8")
    for terme_attendu in (
        "LegacyAuthzAdapter",
        "LegacyConfigAdapter",
        "PermissionLegacyNonSupportee",
        "FileNotFoundError",
        "auth/",
        "legacy_pre_core",
    ):
        assert terme_attendu in doc, f"COMPATIBILITY-SHIMS.md ne mentionne pas {terme_attendu!r}"


def test_dependency_rules_toml_declare_compat_sous_adapters():
    """R1 de la revue d'architecture, vérifié réel avant application
    (test_dependency_rules.py::test_union_des_couches_couvre_
    exactement_tous_les_py_de_core_src, déjà mergé C04-001) : sans
    'opsys_core/compat/' dans [layers.adapters].paths, ce test devient
    rouge dès que compat/*.py existe (fichiers orphelins). Vérifié ici
    depuis CE fichier de test aussi, pour que la panne future pointe
    directement vers dependency-rules.toml plutôt que vers un test
    d'une autre tâche."""
    import tomllib

    regles = tomllib.loads((_REPO_ROOT / "core" / "dependency-rules.toml").read_text(encoding="utf-8"))
    chemins_adapters = regles["layers"]["adapters"]["paths"]
    assert any(p.rstrip("/") == "opsys_core/compat" for p in chemins_adapters), (
        f"'opsys_core/compat/' absent de [layers.adapters].paths : {chemins_adapters}"
    )
    # Le littéral 'C04-003' doit survivre dans exception_resorption —
    # test_dependency_rules.py:487 l'exige déjà pour l'exception
    # legacy_pre_core (test d'une autre tâche, gate mécanique).
    assert "C04-003" in regles["layers"]["adapters"].get("exception_resorption", "")


def test_aucun_import_absolu_opsys_core_dans_kernel_domain_ports():
    """Effet de bord nommé par la revue d'architecture (pas un piège
    actif aujourd'hui — mesuré 0 occurrence — mais latent) : ajouter
    'opsys_core/compat/' à la couche adapters fait entrer le préfixe
    top-level 'opsys_core' dans les noms considérés comme la couche
    adapters par test_dependency_rules.py (noms_adapters_top_level =
    prefixe.split('/')[0]). Si kernel/domain/ports se mettaient à
    importer 'opsys_core.X' en ABSOLU (au lieu de relatif, convention
    actuelle à 100 %), ce test échouerait avec un message trompeur
    ('kernel importe adapters') au lieu de pointer cette décision.
    Cette garde nomme le piège directement : kernel/domain/ports
    restent 100% imports relatifs pour tout ce qui touche opsys_core.

    Les chemins des 3 couches sont LUS depuis dependency-rules.toml
    (jamais codés en dur) — objection Kimi-K3 tour 1 confirmée : une
    liste figée saute silencieusement tout fichier renommé/ajouté à
    une couche sans que ce test le sache. Garde de non-vacuité incluse
    (assert fichiers) : un dependency-rules.toml vidé par erreur ferait
    autrement passer ce test à vide, sans rien vérifier."""
    import ast
    import tomllib

    regles = tomllib.loads((_REPO_ROOT / "core" / "dependency-rules.toml").read_text(encoding="utf-8"))
    fichiers: list[Path] = []
    for nom_couche in ("kernel", "domain", "ports"):
        for prefixe in regles["layers"][nom_couche]["paths"]:
            cible = _CORE_SRC / prefixe
            if cible.is_file():
                fichiers.append(cible)
            elif cible.is_dir():
                fichiers.extend(sorted(cible.rglob("*.py")))
    assert fichiers, "aucun fichier trouvé pour kernel/domain/ports — dependency-rules.toml vide/incohérent, la mesure serait aveugle"

    violations = []
    for fichier in fichiers:
        arbre = ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier))
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    if alias.name == "opsys_core" or alias.name.startswith("opsys_core."):
                        violations.append(f"{fichier}: import {alias.name}")
            elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
                if noeud.module == "opsys_core" or noeud.module.startswith("opsys_core."):
                    violations.append(f"{fichier}: from {noeud.module} import ...")
    assert not violations, (
        f"import ABSOLU de opsys_core détecté dans kernel/domain/ports (devrait être relatif) : {violations}"
    )
