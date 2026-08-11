"""Tests pour core/src/opsys_core (C03-001) — noyau constitutionnel.

Couvre les 3 cas RED obligatoires de tasks/C03-001.md :
  1. boot sans plan requis = BLOCKED_MISSING_PREREQUISITE
  2. aucun import de Modules M
  3. status ne peut pas être ACTIVE par défaut

Conception revue par architecture AVANT code (GPT-5.6-Terra-Pro, appel
direct --difficulty difficile) : CorePlane limité aux 6 planes doublement
sourcées (diagramme d'architecture ET workstream RF01 correspondant) —
TRUST (en amont du KERNEL, pas une arête KERNEL-->) et DATA (arête
KERNEL--> mais sans workstream RF01 correspondant) exclus, non fondés de
façon équivalente. boot() est une méthode STATIQUE (aucun état d'instance
non demandé par le spec). Les cas RED 1 et 3 sont deux mécanismes
DISTINCTS et indépendants (pas un seul artifice de config par défaut) :
RED 1 teste boot() avec un plan explicitement requis-mais-non-enregistré ;
RED 3 teste le statut par défaut d'un CoreKernel fraîchement construit,
AVANT tout appel à boot().
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from opsys_core import CoreConfig, CoreKernel, CorePlane, CoreStatus  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULES_M_ROOT = _REPO_ROOT / "Modules M"
_OPSYS_CORE_SRC = _REPO_ROOT / "core" / "src" / "opsys_core"


def _noms_modules_m_reels() -> set[str]:
    """Énumère les noms de paquets Python RÉELLEMENT importables sous
    Modules M/*/src/* (répertoires namespace-package ET fichiers .py de
    premier niveau) — jamais un pattern deviné. M7-marketing n'a PAS de
    paquet unique m7_marketing : 13 sous-paquets (ads, aeo, attribution,
    ...), un seul avec __init__.py (les autres sont des namespace packages
    PEP 420, importables sans __init__.py) — mesuré directement, pas
    supposé (cf. mémoire verifier-la-structure-pas-le-nom-suppose)."""
    noms: set[str] = set()
    for src_dir in _MODULES_M_ROOT.glob("*/src"):
        for entree in src_dir.iterdir():
            if entree.is_dir() and not entree.name.startswith((".", "__")):
                noms.add(entree.name)
            elif entree.is_file() and entree.suffix == ".py" and entree.stem != "__init__":
                noms.add(entree.stem)
    return noms


def _imports_dans(chemin: Path) -> set[str]:
    """Ensemble des noms de premier niveau importés (import X / from X
    import ...) dans un fichier Python, via AST — jamais un grep textuel
    (compile()/ast.parse plutôt que grepper, cf. mémoire verifier-la-
    structure-pas-le-nom-suppose)."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
    noms: set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                noms.add(alias.name.split(".")[0])
        elif isinstance(noeud, ast.ImportFrom):
            if noeud.module:
                noms.add(noeud.module.split(".")[0])
    return noms


# ---------------------------------------------------------------------------
# Cas RED 1 — boot sans plan requis = BLOCKED_MISSING_PREREQUISITE
# ---------------------------------------------------------------------------


def test_cr_er_le_package_opsys_core_et_le_registre_des_plans_1():
    """Cas RED #1 — un plan requis mais non enregistré bloque le boot."""
    config = CoreConfig(
        required_planes=frozenset({CorePlane.EVENT_ACTION_FABRIC}),
        registered_planes=frozenset(),
    )
    assert CoreKernel.boot(config) == CoreStatus.BLOCKED_MISSING_PREREQUISITE, (
        "GARDE RETIRÉE : un plan requis non enregistré doit bloquer le boot"
    )


def test_boot_avec_tous_les_plans_requis_enregistres_devient_active():
    """Contrôle symétrique : quand tous les plans requis SONT enregistrés,
    le boot devient ACTIVE — jamais un faux blocage sur un état sain."""
    planes = frozenset({CorePlane.EVENT_ACTION_FABRIC, CorePlane.CAPABILITY_MODEL_FABRIC})
    config = CoreConfig(required_planes=planes, registered_planes=planes)
    assert CoreKernel.boot(config) == CoreStatus.ACTIVE


def test_boot_avec_certains_plans_requis_enregistres_reste_bloque():
    """Un boot PARTIEL (certains plans enregistrés, pas tous) reste
    bloqué — jamais un ACTIVE partiel qui masquerait le manque réel."""
    config = CoreConfig(
        required_planes=frozenset({CorePlane.EVENT_ACTION_FABRIC, CorePlane.RAG_MEMORY_FABRIC}),
        registered_planes=frozenset({CorePlane.EVENT_ACTION_FABRIC}),
    )
    assert CoreKernel.boot(config) == CoreStatus.BLOCKED_MISSING_PREREQUISITE


def test_planes_enregistrees_en_surplus_des_requises_n_empechent_pas_active():
    """Des plans enregistrés EN PLUS des requises (surplus) ne doivent
    jamais faire échouer le boot — seul un MANQUE bloque."""
    config = CoreConfig(
        required_planes=frozenset({CorePlane.EVENT_ACTION_FABRIC}),
        registered_planes=frozenset({CorePlane.EVENT_ACTION_FABRIC, CorePlane.OBSERVABILITY_COST_SLO}),
    )
    assert CoreKernel.boot(config) == CoreStatus.ACTIVE


# ---------------------------------------------------------------------------
# Cas RED 2 — aucun import de Modules M
# ---------------------------------------------------------------------------


def test_cr_er_le_package_opsys_core_et_le_registre_des_plans_2():
    """Cas RED #2 — aucun fichier de opsys_core n'importe un paquet réel
    de Modules M/ (énuméré dynamiquement, jamais un pattern deviné)."""
    noms_m = _noms_modules_m_reels()
    assert noms_m, "aucun paquet Modules M détecté — la mesure elle-même serait aveugle"
    assert len(noms_m) >= 10, f"mesure suspecte : seulement {len(noms_m)} paquets Modules M détectés"
    for fichier in _OPSYS_CORE_SRC.glob("*.py"):
        imports = _imports_dans(fichier)
        collision = imports & noms_m
        assert not collision, f"GARDE RETIRÉE : {fichier.name} importe un paquet Modules M : {collision}"


def test_detecte_un_import_modules_m_sur_fixture_synthetique(tmp_path):
    """Preuve que le détecteur détecte VRAIMENT un import Modules M — pas
    seulement que le code réel est propre par construction (piège de
    coïncidence déjà rencontré C02-001..005 : un test sur le fichier réel
    seul passerait même si le détecteur était cassé, puisque le fichier
    réel est déjà correct)."""
    faux_fichier = tmp_path / "faux.py"
    faux_fichier.write_text("import m2_revenue_crm\nfrom m4_field_ops import x\n", encoding="utf-8")
    imports = _imports_dans(faux_fichier)
    assert "m2_revenue_crm" in imports
    assert "m4_field_ops" in imports


def test_ne_signale_pas_un_import_stdlib_ou_tiers_sur_fixture_synthetique(tmp_path):
    fichier = tmp_path / "propre.py"
    fichier.write_text(
        "from __future__ import annotations\nimport dataclasses\nfrom enum import Enum\nimport os.path\n",
        encoding="utf-8",
    )
    noms_m = _noms_modules_m_reels()
    assert not (_imports_dans(fichier) & noms_m)


def test_enumeration_modules_m_capture_les_sous_paquets_m7_sans_init(tmp_path):
    """M7-marketing n'a PAS de paquet unique m7_marketing — 13 sous-paquets
    à plat sous src/, dont 12 SANS __init__.py (namespace packages PEP
    420). L'énumération doit les capturer TOUS, pas seulement celui qui a
    un __init__.py — sinon la garde serait aveugle sur 12/13 des vrais
    paquets M7 importables."""
    noms_m = _noms_modules_m_reels()
    attendus_m7 = {"ads", "aeo", "attribution", "brand", "competitive", "content",
                   "reputation", "roi", "seo", "site", "social", "utm", "workflows"}
    manquants = attendus_m7 - noms_m
    assert not manquants, f"sous-paquets M7 non détectés par l'énumération : {manquants}"


# ---------------------------------------------------------------------------
# Cas RED 3 — status ne peut pas être ACTIVE par défaut
# ---------------------------------------------------------------------------


def test_cr_er_le_package_opsys_core_et_le_registre_des_plans_3():
    """Cas RED #3 — un CoreKernel fraîchement construit (AVANT tout appel
    à boot()) n'est JAMAIS ACTIVE par défaut."""
    assert CoreKernel().status != CoreStatus.ACTIVE, (
        "GARDE RETIRÉE : le statut par défaut d'un CoreKernel ne doit jamais être ACTIVE"
    )
    assert CoreKernel().status == CoreStatus.UNKNOWN, (
        "le statut par défaut attendu est UNKNOWN (CANON §12 : aucune erreur/absence "
        "ne devient un succès — un kernel jamais booté est de statut inconnu, pas actif)"
    )


def test_vocabulaire_corestatus_est_exactement_celui_du_canon():
    """CoreStatus doit être EXACTEMENT le vocabulaire du CANON §12 (7
    états), jamais un état inventé, jamais un état canon manquant."""
    attendu = {
        "ACTIVE", "DEGRADED", "BLOCKED_MISSING_PREREQUISITE",
        "BLOCKED_QUALITY_THRESHOLD", "BLOCKED_POLICY", "UNKNOWN", "QUARANTINED",
    }
    assert {s.name for s in CoreStatus} == attendu


def test_corekernel_est_gele():
    import pytest

    k = CoreKernel()
    with pytest.raises(Exception):
        k.status = CoreStatus.ACTIVE  # type: ignore[misc]


def test_coreconfig_est_gele():
    import pytest

    c = CoreConfig()
    with pytest.raises(Exception):
        c.required_planes = frozenset()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Package sans effet de bord à l'import
# ---------------------------------------------------------------------------


def test_reimport_du_package_ne_leve_aucune_exception():
    """Le package est déjà importé en haut de ce fichier sans exception —
    un ré-import (importlib.reload) ne doit pas non plus lever, preuve la
    plus directe possible qu'aucun effet de bord n'accumule d'état ni ne
    dépend d'une ressource externe consommée une seule fois."""
    import importlib

    import opsys_core

    importlib.reload(opsys_core)


def test_corplane_a_exactement_les_6_planes_doublement_sourcees():
    """CorePlane est limité aux 6 planes doublement sourcées (diagramme +
    workstream RF01 correspondant) — TRUST et DATA exclus (revue
    d'architecture AVANT code, question 1 : non fondés de façon
    équivalente aux 6 autres)."""
    attendu = {
        "EVENT_ACTION_FABRIC", "CAPABILITY_MODEL_FABRIC", "RAG_MEMORY_FABRIC",
        "TOKEN_CONTEXT_CONTROL", "FRAMEWORK_BRICK_FABRIC", "OBSERVABILITY_COST_SLO",
    }
    assert {p.name for p in CorePlane} == attendu
