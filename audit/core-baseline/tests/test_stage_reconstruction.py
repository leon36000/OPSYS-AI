"""C00-002 — Tests RED→GREEN pour rejouer le stade squelette-first."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

# Même convention de mesure qu'en C00-001 (test_target_custody.py) — pas de
# nouvelle hypothèse : parents[3] = racine réelle du worktree.
WORKTREE = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE))
import stage_reconstruction as sr
from stage_reconstruction import (
    StageState,
    ModuleNonPartielRefuse,
    InterfaceFinaleNonDifferee,
    AbsenceFinaleRequalifieeEnDefaut,
    construire_stage_state,
    rejouer_stade,
    _produire_sorties_stage,
    MODULES_STATUTS_SOURCE,
    PROGRAM_STAGE_SOURCE,
    CORE_STATUS_SOURCE,
    SOURCES_CANONIQUES,
)

PACK_ROOT = Path("/home/pc1/core-pack/OPSYS-AI-CORE-EXECUTION-PACK-v2.3.1-fusion")

# ---------------------------------------------------------------------------
# 3 cas RED obligatoires (noms imposés)
# ---------------------------------------------------------------------------


def test_rejouer_le_stade_squelette_first_1():
    """RED obligatoire : « les dix modules doivent rester PARTIAL ». Un statut
    de module mutant vers un marqueur de complétion totale, ou un module
    manquant sur les dix attendus, doit être REFUSÉ à la construction —
    jamais silencieusement accepté."""
    # Cas nominal : les 10 statuts réels (sourcés) construisent sans lever.
    etat = construire_stage_state(
        program_stage=PROGRAM_STAGE_SOURCE,
        modules=dict(MODULES_STATUTS_SOURCE),
        core_status=CORE_STATUS_SOURCE,
        source_hashes=["a" * 64],
    )
    assert set(etat.modules) == {"M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10"}

    # Cas 1 : un module marqué complet (DONE) doit être refusé.
    modules_mutes = dict(MODULES_STATUTS_SOURCE)
    modules_mutes["M7"] = "DONE"
    with pytest.raises(ModuleNonPartielRefuse, match="M7"):
        construire_stage_state(
            program_stage=PROGRAM_STAGE_SOURCE, modules=modules_mutes,
            core_status=CORE_STATUS_SOURCE, source_hashes=["a" * 64],
        )

    # Cas 2 : un module manquant (9 au lieu de 10) doit être refusé.
    modules_incomplets = dict(MODULES_STATUTS_SOURCE)
    del modules_incomplets["M9"]
    with pytest.raises(ModuleNonPartielRefuse, match="M9"):
        construire_stage_state(
            program_stage=PROGRAM_STAGE_SOURCE, modules=modules_incomplets,
            core_status=CORE_STATUS_SOURCE, source_hashes=["a" * 64],
        )

    # Cas 3 : un statut plausible mais NON reconnu (marqueur SHIPPED) refusé aussi.
    modules_mutes2 = dict(MODULES_STATUTS_SOURCE)
    modules_mutes2["M5"] = "SHIPPED_TO_PRODUCTION"
    with pytest.raises(ModuleNonPartielRefuse, match="M5"):
        construire_stage_state(
            program_stage=PROGRAM_STAGE_SOURCE, modules=modules_mutes2,
            core_status=CORE_STATUS_SOURCE, source_hashes=["a" * 64],
        )


def test_rejouer_le_stade_squelette_first_2():
    """RED obligatoire : « l'interface finale doit rester différée ». Le
    core_status DOIT porter explicitement le report de l'interface finale
    (§2 de la source : INTERFACE_FINALE = DERNIER CHANTIER) — sans ce
    marqueur, la construction est refusée."""
    etat = construire_stage_state(
        program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
        core_status=CORE_STATUS_SOURCE, source_hashes=["a" * 64],
    )
    assert "INTERFACE_FINALE=DERNIER_CHANTIER" in etat.core_status

    # Porte le marqueur de la garde 3 (ASSEMBLAGE_FINAL_ABSENT=...) pour
    # isoler STRICTEMENT la garde testée ici — sans lui, une neutralisation
    # de CETTE garde (2) serait masquée par la garde 3 qui lèverait à sa
    # place (mesuré : DID NOT RAISE devient un mauvais type d'exception).
    core_status_sans_report = (
        "PHASE_0_CORE=PARTIELLE_BLOQUEE_AVEC_CAUSE; "
        "ASSEMBLAGE_FINAL_ABSENT=ETAT_DE_STAGE_PAS_PREUVE_DE_DERIVE"
    )
    with pytest.raises(InterfaceFinaleNonDifferee):
        construire_stage_state(
            program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
            core_status=core_status_sans_report, source_hashes=["a" * 64],
        )


def test_rejouer_le_stade_squelette_first_3():
    """RED obligatoire : « une capacité finale absente ne devient pas
    automatiquement un défaut ». Le core_status DOIT porter explicitement
    cette requalification (§2 : ASSEMBLAGE_FINAL_ABSENT = ETAT_DE_STAGE, PAS
    PREUVE DE DERIVE) — sans ce marqueur, la construction est refusée."""
    etat = construire_stage_state(
        program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
        core_status=CORE_STATUS_SOURCE, source_hashes=["a" * 64],
    )
    assert "ASSEMBLAGE_FINAL_ABSENT=ETAT_DE_STAGE_PAS_PREUVE_DE_DERIVE" in etat.core_status

    core_status_sans_requalification = (
        "PHASE_0_CORE=PARTIELLE_BLOQUEE_AVEC_CAUSE; INTERFACE_FINALE=DERNIER_CHANTIER"
    )
    with pytest.raises(AbsenceFinaleRequalifieeEnDefaut):
        construire_stage_state(
            program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
            core_status=core_status_sans_requalification, source_hashes=["a" * 64],
        )


# ---------------------------------------------------------------------------
# Tests complémentaires : reconstruction réelle, production des sorties
# ---------------------------------------------------------------------------


def test_stage_state_est_gele():
    """StageState est un dataclass frozen — toute tentative de mutation
    post-construction doit lever, comme TargetCustody en C00-001."""
    etat = construire_stage_state(
        program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
        core_status=CORE_STATUS_SOURCE, source_hashes=["a" * 64],
    )
    with pytest.raises(Exception):
        etat.program_stage = "AUTRE"


def test_rejouer_stade_hache_les_5_sources_reelles():
    """rejouer_stade() doit hacher RÉELLEMENT les 5 sources canoniques —
    comparé indépendamment à hashlib.sha256(read_bytes()), jamais supposé."""
    import hashlib
    etat = rejouer_stade(PACK_ROOT)
    assert len(etat.source_hashes) == 5
    for rel, h in zip(SOURCES_CANONIQUES, etat.source_hashes):
        attendu = hashlib.sha256((PACK_ROOT / rel).read_bytes()).hexdigest()
        assert h == attendu, f"hash divergent pour {rel}"
        assert len(h) == 64


def test_produire_sorties_stage_ecrit_json_et_csv_reels(tmp_path):
    """Bout en bout réel : STAGE.json et STAGE-EVIDENCE.csv sont produits,
    contiennent les valeurs sourcées, et le CSV a exactement 5 lignes liées
    aux 5 sources canoniques. `_produire_sorties_stage` est DÉTERMINISTE
    (mêmes sources → mêmes octets) : ce test réécrit les sorties TRACKÉES
    avec un contenu IDENTIQUE, jamais ne les supprime — un `finally:
    unlink()` sur un fichier suivi par git le supprimerait réellement du
    dépôt à la prochaine régénération (défaut trouvé et corrigé avant
    soumission : mesuré via `git status --porcelain` montrant `D` après un
    premier run de la suite)."""
    sortie_dir = WORKTREE / "audit" / "core-baseline"
    avant = (sortie_dir / "STAGE.json").read_bytes() if (sortie_dir / "STAGE.json").exists() else None

    etat = _produire_sorties_stage(WORKTREE, sortie_dir, PACK_ROOT)

    stage_json = json.loads((sortie_dir / "STAGE.json").read_text(encoding="utf-8"))
    assert stage_json["program_stage"] == PROGRAM_STAGE_SOURCE
    assert stage_json["core_status"] == CORE_STATUS_SOURCE
    assert set(stage_json["modules"]) == set(MODULES_STATUTS_SOURCE)
    assert stage_json["source_hashes"] == etat.source_hashes

    with (sortie_dir / "STAGE-EVIDENCE.csv").open(encoding="utf-8", newline="") as f:
        lignes = list(csv.DictReader(f))
    assert len(lignes) == 5
    assert [l["source"] for l in lignes] == list(SOURCES_CANONIQUES)
    assert [l["sha256"] for l in lignes] == etat.source_hashes

    if avant is not None:
        assert (sortie_dir / "STAGE.json").read_bytes() == avant, (
            "régénération non déterministe — le contenu tracké a changé "
            "alors que les sources n'ont pas bougé"
        )


def test_produire_sorties_stage_refuse_sortie_dir_symlinke(tmp_path):
    """Le SITE D'APPEL réel de _produire_sorties_stage refuse un sortie_dir
    symlinké — pas seulement l'utilitaire testé isolément (piège fermé en
    C00-001 : un test qui n'exerce que l'utilitaire ne prouve rien du site
    d'appel réel)."""
    coffre_externe = tmp_path / "coffre_externe"
    coffre_externe.mkdir()
    faux_worktree = tmp_path / "faux_worktree"
    faux_worktree.mkdir()
    lien = faux_worktree / "sortie_symlinkee"
    lien.symlink_to(coffre_externe)

    with pytest.raises(sr.custody.EcritureViaSymlinkRefusee):
        _produire_sorties_stage(faux_worktree, lien, PACK_ROOT)

    assert list(coffre_externe.iterdir()) == [], (
        "un fichier a été créé dans le coffre externe malgré le refus attendu"
    )


def test_ecrire_csv_stage_echappe_correctement_une_virgule(tmp_path):
    """Défaut connu (trouvé par l'Orchestrateur lui-même en C00-001) : une
    construction manuelle du CSV par f-string n'échapperait pas une virgule.
    Vérifie que csv.DictWriter le fait correctement — round-trip."""
    lignes = [{"source": "chemin, avec virgule.md", "sha256": "b" * 64}]
    dest = tmp_path / "out.csv"
    sr._ecrire_csv_stage_sans_suivre_symlink(dest, lignes, tmp_path)
    with dest.open(encoding="utf-8", newline="") as f:
        lues = list(csv.DictReader(f))
    assert lues[0]["source"] == "chemin, avec virgule.md"
