"""Tests pour core/src/opsys_core/{composition,provider_registry}.py
(C04-004) — registre de composition et injection explicite, DERNIÈRE
tâche de la phase C04 : peuple la couche `application`, déclarée VIDE
par C04-001 spécifiquement en attente de cette tâche
(core/dependency-rules.toml note, layers.application).

Couvre les 3 cas RED obligatoires de tasks/C04-004.md :
  1. aucun singleton global mutable
  2. provider manquant = blocker explicite
  3. une capacité n'a qu'une implémentation active

Conception revue par architecture AVANT code (subagent `architecte`,
Claude Opus 5 natif) — verdict complet dans l'Evidence Bundle. Points
vérifiés PUIS appliqués (jamais sur la seule autorité du reviewer,
CLAIMS UNVERIFIED) :
  - CoreConfig/CoreKernel/CoreStatus EXISTENT DÉJÀ dans opsys_core.kernel
    (C03-001) — importés en relatif, jamais redéfinis (vérifié :
    opsys_core/__init__.py les réexporte déjà de la même façon).
  - Le vocabulaire « capacité » du cas RED est réalisé ici par CorePlane
    (opsys_core.planes, 6 membres, C03-001) — PAS par
    opsys_core.status.model.CapabilityStatus.capability_id (str libre,
    C03-003), qui est une notion DISTINCTE et pré-existante. Choix de
    CorePlane motivé mécaniquement : c'est le SEUL porteur d'exigence
    dans la signature imposée build_core(config:CoreConfig,...) — via
    CoreConfig.required_planes — donc le seul candidat qui rend
    « provider manquant » décidable sans étendre CoreConfig (hors
    Sorties exactes) ni inventer une liste de capacités requises
    (donnée inventée, interdit).
  - « provider manquant » réutilise CoreStatus.BLOCKED_MISSING_
    PREREQUISITE (existant) plutôt qu'une exception dédiée : le
    domaine de retour de build_core (CoreKernel, PAS bool) a DÉJÀ une
    valeur pour « je ne peux pas activer » — contrairement à
    LegacyAuthzAdapter.authorize() (C04-003) dont le domaine bool à 2
    valeurs n'avait aucune place pour « limitation du shim », ce qui
    avait forcé une exception dédiée là-bas. Le même raisonnement
    donne ici une conclusion DIFFÉRENTE : le blocage doit rester
    LISIBLE sur le CoreKernel retourné, jamais masqué en silence (test
    _2 ci-dessous le prouve).
  - test_application_est_declaree_vide_explicitement (C04-001, déjà
    mergé, core/tests/architecture/test_dependency_rules.py) asserte
    littéralement paths == [] : MÉCANIQUEMENT INCOMPATIBLE avec cette
    tâche dont le but même est de peupler cette couche (note du TOML
    depuis C04-001 : « peuplée par C04-004 »). Amendé dans CE commit
    (hors Tests exacts de C04-004, mais imposé par un gate déjà mergé —
    même patron que C04-003 amendant dependency-rules.toml hors ses
    propres Sorties exactes) : la garde CAND-CA05-0004 reste vivante
    (note explicite TOUJOURS exigée, vide ou peuplée), seule
    l'assertion paths==[] devient paths!=[] avec justification.
"""
from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from opsys_core.kernel import CoreConfig, CoreKernel, CoreStatus
from opsys_core.planes import CorePlane
from opsys_core.composition import DiagnosticComposition, build_core, diagnostiquer
from opsys_core.provider_registry import CapaciteDejaFournie, ProviderSet

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORE_SRC = _REPO_ROOT / "core" / "src"
_FICHIERS_COMPOSITION = (
    _CORE_SRC / "opsys_core" / "composition.py",
    _CORE_SRC / "opsys_core" / "provider_registry.py",
)


class _ProviderFactice:
    """Provider minimal pour les tests — n'implémente aucun Protocol de
    ports/contracts.py (non requis : ni tasks/C04-004.md ni tasks/
    C04-003.md ne sourcent une conformité ProviderPort explicite pour
    ces objets, décision déjà tranchée en revue d'architecture C04-003
    et reconfirmée ici)."""

    def __init__(self, nom: str) -> None:
        self.nom = nom

    def __repr__(self) -> str:
        return f"_ProviderFactice({self.nom!r})"


# ---------------------------------------------------------------------------
# Cas RED 1 — aucun singleton global mutable
# ---------------------------------------------------------------------------


def _attributs_module_niveau(arbre: ast.Module) -> list[ast.Assign | ast.AnnAssign]:
    resultat = []
    for noeud in arbre.body:
        if isinstance(noeud, (ast.Assign, ast.AnnAssign)):
            resultat.append(noeud)
    return resultat


def _valeur_est_conteneur_mutable(valeur: ast.expr | None) -> bool:
    # None : cas d'une annotation SANS valeur (ex. `x: int`, AnnAssign.value
    # peut être None) — rien à évaluer, trivialement pas un conteneur mutable.
    if valeur is None:
        return False
    if isinstance(valeur, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    return False


def _cible_noms(noeud: ast.Assign | ast.AnnAssign) -> list[str]:
    if isinstance(noeud, ast.AnnAssign):
        return [noeud.target.id] if isinstance(noeud.target, ast.Name) else []
    return [t.id for t in noeud.targets if isinstance(t, ast.Name)]


def _scanner_singleton_global_mutable(chemin: Path) -> list[str]:
    """Détecteur AST : (a) aucun ast.Global/ast.Nonlocal nulle part ;
    (b) aucune affectation de MODULE dont la valeur est un conteneur
    mutable littéral (dict/list/set/comprehension) sous un nom
    NON-dunder ; (c) aucun décorateur lru_cache/cache sur une fonction
    de module."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
    violations: list[str] = []

    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Global, ast.Nonlocal)):
            violations.append(f"{chemin.name}:{noeud.lineno}: global/nonlocal détecté")

    for assignation in _attributs_module_niveau(arbre):
        if not _valeur_est_conteneur_mutable(assignation.value):
            continue
        for nom in _cible_noms(assignation):
            if nom.startswith("__") and nom.endswith("__"):
                continue  # __all__ etc. exclus explicitement (mais on ne les DÉCLARE jamais ici)
            violations.append(f"{chemin.name}:{assignation.lineno}: '{nom}' = conteneur mutable au niveau module")

    for noeud in arbre.body:
        if isinstance(noeud, ast.FunctionDef):
            for decorateur in noeud.decorator_list:
                nom_dec = decorateur.id if isinstance(decorateur, ast.Name) else getattr(decorateur, "attr", "")
                if nom_dec in ("lru_cache", "cache"):
                    violations.append(f"{chemin.name}:{noeud.lineno}: @{nom_dec} sur une fonction de module")

    return violations


def test_cr_er_le_registre_de_composition_et_l_injection_explicite_1():
    """Aucun singleton global mutable — 3 preuves indépendantes, chacune
    nécessaire (une seule ne suffit pas) :
    (a) garde AST statique sur les 2 fichiers RÉELS, ET vérifiée
        mordante sur une fixture synthétique contenant un singleton
        (sans quoi on ne saurait pas si le détecteur fonctionne — piège
        déjà nommé plusieurs fois dans test_dependency_rules.py) ;
    (b) garde runtime : aucun attribut non-dunder des 2 modules importés
        n'est une instance de (dict, list, set, bytearray) ;
    (c) contrôle d'identité : deux appels à build_core avec les MÊMES
        arguments ne retournent PAS le même objet (seul discriminant du
        piège lru_cache sur build_core lui-même)."""
    # (a1) fixture synthétique : le détecteur DOIT mordre sur du code cassé.
    fixture_cassee = (
        "_REGISTRE = {}\n"
        "\n"
        "def enregistrer(cle, valeur):\n"
        "    global _REGISTRE\n"
        "    _REGISTRE[cle] = valeur\n"
    )
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        chemin_fixture = Path(tmp) / "module_casse.py"
        chemin_fixture.write_text(fixture_cassee, encoding="utf-8")
        violations_fixture = _scanner_singleton_global_mutable(chemin_fixture)
        assert violations_fixture, (
            "le détecteur AST ne mord PAS sur un singleton synthétique connu — la garde (a) ne prouve rien"
        )
        assert any("global" in v for v in violations_fixture)
        assert any("_REGISTRE" in v for v in violations_fixture)

    # (a2) garde réelle sur les 2 fichiers de sortie de cette tâche.
    for chemin in _FICHIERS_COMPOSITION:
        violations = _scanner_singleton_global_mutable(chemin)
        assert not violations, f"singleton global mutable détecté : {violations}"

    # (b) garde runtime sur les modules réellement importés.
    import opsys_core.composition as mod_composition
    import opsys_core.provider_registry as mod_provider_registry

    for module in (mod_composition, mod_provider_registry):
        for nom in dir(module):
            if nom.startswith("__") and nom.endswith("__"):
                continue
            valeur = getattr(module, nom)
            assert not isinstance(valeur, (dict, list, set, bytearray)), (
                f"{module.__name__}.{nom} est un conteneur mutable au niveau module : {valeur!r}"
            )

    # (c) contrôle d'identité — pas de lru_cache déguisé.
    config = CoreConfig(required_planes=frozenset(), registered_planes=frozenset())
    providers = ProviderSet.depuis_paires([])
    premier = build_core(config, providers)
    second = build_core(config, providers)
    assert premier is not second, "build_core retourne le même objet entre deux appels — état partagé suspecté"
    assert premier == second, "deux CoreKernel équivalents devraient être égaux par valeur (dataclass frozen)"


# ---------------------------------------------------------------------------
# Cas RED 2 — provider manquant = blocker explicite
# ---------------------------------------------------------------------------


def test_cr_er_le_registre_de_composition_et_l_injection_explicite_2():
    """Provider manquant = blocker explicite, jamais masqué.

    Garde de non-vacuité + isolation de la cause : required_planes est
    non vide ET registered_planes ⊇ required_planes (donc
    CoreKernel.boot(config) SEUL, sans providers, rendrait déjà ACTIVE —
    contrôle explicite ci-dessous). Seul le PROVIDER manque. Si
    build_core ignorait entièrement les providers, ce test resterait
    vert pour la mauvaise raison — d'où le contrôle CoreKernel.boot
    séparé qui isole la cause."""
    plane_sans_provider = CorePlane.OBSERVABILITY_COST_SLO
    config = CoreConfig(
        required_planes=frozenset({plane_sans_provider}),
        registered_planes=frozenset({plane_sans_provider}),
    )
    # Contrôle : le kernel SEUL (sans notion de provider) dirait ACTIVE.
    assert CoreKernel.boot(config) == CoreStatus.ACTIVE, (
        "prérequis du test invalide : le config seul devrait déjà être ACTIVE côté plane"
    )

    providers_vides = ProviderSet.depuis_paires([])
    resultat = build_core(config, providers_vides)
    assert resultat.status == CoreStatus.BLOCKED_MISSING_PREREQUISITE, (
        f"provider manquant non signalé comme blocker explicite : status={resultat.status}"
    )

    # Contrôle positif : le MÊME config, avec le provider fourni, active.
    providers_complets = ProviderSet.depuis_paires([(plane_sans_provider, _ProviderFactice("obs"))])
    resultat_ok = build_core(config, providers_complets)
    assert resultat_ok.status == CoreStatus.ACTIVE, (
        f"provider fourni mais toujours bloqué : status={resultat_ok.status}"
    )


def test_diagnostic_expose_la_plane_manquante_sans_la_masquer():
    """« Exposer diagnostic de composition » (implémentation strictement
    bornée) : diagnostiquer() est la source UNIQUE dont build_core
    dérive son statut (jamais deux calculs séparés qui pourraient
    diverger) — vérifié en comparant le status du diagnostic à celui du
    CoreKernel retourné par build_core sur le MÊME cas."""
    plane_manquante = CorePlane.TOKEN_CONTEXT_CONTROL
    config = CoreConfig(
        required_planes=frozenset({plane_manquante}),
        registered_planes=frozenset({plane_manquante}),
    )
    diagnostic = diagnostiquer(config, ProviderSet.depuis_paires([]))
    assert isinstance(diagnostic, DiagnosticComposition)
    assert plane_manquante in diagnostic.planes_manquantes
    assert diagnostic.status == CoreStatus.BLOCKED_MISSING_PREREQUISITE

    resultat = build_core(config, ProviderSet.depuis_paires([]))
    assert resultat.status == diagnostic.status, (
        "build_core et diagnostiquer divergent sur le même cas — source de vérité dupliquée"
    )


# ---------------------------------------------------------------------------
# Cas RED 3 — une capacité n'a qu'une implémentation active
# ---------------------------------------------------------------------------


def test_cr_er_le_registre_de_composition_et_l_injection_explicite_3():
    """Une capacité (CorePlane) n'a qu'une implémentation active.

    Construit DEPUIS UNE SÉQUENCE de paires (jamais un dict littéral :
    {A: p1, A: p2} vaudrait déjà {A: p2} avant même d'atteindre le code
    testé — l'invariant deviendrait infalsifiable). Le doublon doit être
    refusé QUELLE QUE SOIT l'identité des objets (règle unique, testée
    explicitement avec le MÊME objet réenregistré deux fois)."""
    plane = CorePlane.RAG_MEMORY_FABRIC
    provider_a = _ProviderFactice("A")
    provider_b = _ProviderFactice("B")

    with pytest.raises(CapaciteDejaFournie) as exc_info:
        ProviderSet.depuis_paires([(plane, provider_a), (plane, provider_b)])
    assert "RAG_MEMORY_FABRIC" in str(exc_info.value) or plane.name in str(exc_info.value)

    # Même objet réenregistré deux fois : refusé aussi (pas d'exception cachée pour l'identité).
    with pytest.raises(CapaciteDejaFournie):
        ProviderSet.depuis_paires([(plane, provider_a), (plane, provider_a)])

    # Contrôle négatif : deux planes DIFFÉRENTES sont acceptées sans lever.
    providers = ProviderSet.depuis_paires([
        (CorePlane.RAG_MEMORY_FABRIC, provider_a),
        (CorePlane.TOKEN_CONTEXT_CONTROL, provider_b),
    ])
    assert providers.planes() == frozenset({CorePlane.RAG_MEMORY_FABRIC, CorePlane.TOKEN_CONTEXT_CONTROL})


# ---------------------------------------------------------------------------
# Garde de non-régression, croisement avec le harnais existant
# ---------------------------------------------------------------------------


def test_provider_set_est_immuable():
    """ProviderSet ne doit exposer aucune méthode de mutation post-
    construction (frozen dataclass + stockage MappingProxyType) — même
    discipline que CoreConfig/CoreKernel (kernel.py, frozen=True)."""
    providers = ProviderSet.depuis_paires([(CorePlane.EVENT_ACTION_FABRIC, _ProviderFactice("x"))])
    with pytest.raises(Exception):
        providers.planes_a_supprimer = frozenset()  # type: ignore[attr-defined]


def test_dependency_rules_toml_declare_composition_sous_application():
    """L'union exacte des couches (test_dependency_rules.py, déjà
    mergé C04-001) exige que composition.py/provider_registry.py soient
    déclarés dans UNE couche — application est la couche naturelle
    (c'est littéralement ce qu'elle attend depuis C04-001). Vérifié ici
    aussi pour que la panne future pointe directement vers
    dependency-rules.toml."""
    regles = tomllib.loads((_REPO_ROOT / "core" / "dependency-rules.toml").read_text(encoding="utf-8"))
    chemins_application = regles["layers"]["application"]["paths"]
    assert chemins_application, "layers.application.paths toujours vide après C04-004"
    noms_fichiers = {Path(p).name for p in chemins_application}
    assert "composition.py" in noms_fichiers
    assert "provider_registry.py" in noms_fichiers
    assert regles["layers"]["application"].get("note", "").strip(), (
        "couche application peuplée sans note explicite — garde CAND-CA05-0004 doit rester vivante"
    )
