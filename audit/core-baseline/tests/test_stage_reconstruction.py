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
    SourceHorsConfinementRefusee,
    construire_stage_state,
    rejouer_stade,
    _produire_sorties_stage,
    _sha256_source_confinee,
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
    # etat.source_hashes est un tuple (immuabilité, cf. StageState) ;
    # stage_json["source_hashes"] vient du JSON, toujours une list — list()
    # explicite avant comparaison, sinon list == tuple est toujours False
    # même à éléments identiques (mesuré).
    assert stage_json["source_hashes"] == list(etat.source_hashes)

    with (sortie_dir / "STAGE-EVIDENCE.csv").open(encoding="utf-8", newline="") as f:
        lignes = list(csv.DictReader(f))
    assert len(lignes) == 5
    assert [l["source"] for l in lignes] == list(SOURCES_CANONIQUES)
    assert [l["sha256"] for l in lignes] == list(etat.source_hashes)

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


# ---------------------------------------------------------------------------
# Revue scellée C00-002 tour 1 (APPROVE 0/3, 2 CRITIQUE + 3 MAJEURE) —
# 3 tests fermant chacun un défaut mesuré fondé.
# ---------------------------------------------------------------------------


def test_instanciation_directe_est_aussi_gardee():
    """Gemini-3.1-Pro, CRITIQUE, C00-002 tour 1 (mesurée fondée) :
    `StageState(...)` instancié DIRECTEMENT (pas via construire_stage_state)
    contournait totalement les 3 gardes — `__post_init__` les exécute
    désormais quel que soit le chemin de construction. Les 3 sous-cas
    reproduisent EXACTEMENT l'exemple donné par Gemini puis les 2 autres
    gardes, chacun via l'appel direct au constructeur du dataclass."""
    # Reproduction exacte de la preuve Gemini : StageState(program_stage='',
    # modules={'M1': 'DONE'}, core_status='', source_hashes=[]).
    with pytest.raises(ModuleNonPartielRefuse):
        StageState(program_stage="", modules={"M1": "DONE"}, core_status="", source_hashes=[])

    # Modules valides, core_status vide → garde 2 (interface différée),
    # atteinte cette fois puisque la garde 1 passe.
    with pytest.raises(InterfaceFinaleNonDifferee):
        StageState(
            program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
            core_status="", source_hashes=[],
        )

    # Modules valides, interface différée, absence non requalifiée → garde 3.
    with pytest.raises(AbsenceFinaleRequalifieeEnDefaut):
        StageState(
            program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
            core_status="INTERFACE_FINALE=DERNIER_CHANTIER", source_hashes=[],
        )

    # Contre-exemple obligatoire : instanciation directe avec les VRAIES
    # valeurs sourcées ne doit PAS lever (les gardes ne sont pas juste
    # punitives, elles laissent passer un état valide).
    etat = StageState(
        program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
        core_status=CORE_STATUS_SOURCE, source_hashes=["a" * 64],
    )
    assert etat.program_stage == PROGRAM_STAGE_SOURCE


def test_stage_state_modules_et_source_hashes_sont_immuables():
    """Gemini-3.1-Pro, MAJEURE, C00-002 tour 1 (mesurée fondée) :
    `frozen=True` empêche `etat.x = y` mais PAS la mutation d'un conteneur
    référencé — `etat.modules['M1'] = 'DONE'` réussissait silencieusement
    après construction, rouvrant le trou que les gardes venaient de fermer.
    Reproduction EXACTE de la preuve Gemini : doit désormais lever
    TypeError (MappingProxyType/tuple, pas dict/list)."""
    etat = construire_stage_state(
        program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
        core_status=CORE_STATUS_SOURCE, source_hashes=["a" * 64],
    )
    with pytest.raises(TypeError):
        etat.modules["M1"] = "DONE"
    with pytest.raises(TypeError):
        etat.source_hashes[0] = "b" * 64
    # Le dict/list ORIGINAL passé à la construction n'est pas non plus
    # partagé par référence — le muter après coup ne doit rien changer.
    modules_appelant = dict(MODULES_STATUTS_SOURCE)
    hashes_appelant = ["a" * 64]
    etat2 = construire_stage_state(
        program_stage=PROGRAM_STAGE_SOURCE, modules=modules_appelant,
        core_status=CORE_STATUS_SOURCE, source_hashes=hashes_appelant,
    )
    modules_appelant["M1"] = "DONE"
    hashes_appelant.append("c" * 64)
    assert etat2.modules["M1"] == MODULES_STATUTS_SOURCE["M1"], (
        "la mutation du dict APPELANT après construction a fuité dans l'état gelé"
    )
    assert len(etat2.source_hashes) == 1, (
        "la mutation de la liste APPELANTE après construction a fuité dans l'état gelé"
    )


def test_sha256_source_refuse_un_symlink(tmp_path):
    """Qwen3.7-Max, MAJEURE, C00-002 tour 1 (mesurée fondée, CWE-59) :
    `_sha256` (avant correctif) suivait aveuglément un symlink placé sur
    une source canonique, hachant un fichier hors périmètre tout en le
    déclarant comme la source légitime dans STAGE-EVIDENCE.csv. Reproduit
    directement : un faux pack_root où une "source" est un symlink vers un
    fichier externe doit être refusé AVANT lecture — jamais hacher la
    cible."""
    faux_pack_root = tmp_path / "faux_pack"
    faux_pack_root.mkdir()
    (faux_pack_root / "sources").mkdir()
    cible_hors_perimetre = tmp_path / "secret_hors_perimetre.txt"
    cible_hors_perimetre.write_text("contenu sensible hors périmètre", encoding="utf-8")
    lien = faux_pack_root / "sources" / "audit.md"
    lien.symlink_to(cible_hors_perimetre)

    with pytest.raises(SourceHorsConfinementRefusee):
        _sha256_source_confinee(lien, faux_pack_root)


def test_rejouer_stade_refuse_reellement_si_une_source_est_symlinkee(tmp_path):
    """Bout en bout : rejouer_stade() sur un pack_root dont UNE des 5
    sources canoniques est un symlink refuse — pas seulement l'utilitaire
    isolé (même piège fermé qu'en C00-001 : tester l'utilitaire seul ne
    prouve rien du site d'appel réel)."""
    faux_pack_root = tmp_path / "faux_pack2"
    for rel in SOURCES_CANONIQUES:
        chemin = faux_pack_root / rel
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text("contenu de remplacement", encoding="utf-8")
    cible_hors_perimetre = tmp_path / "secret2.txt"
    cible_hors_perimetre.write_text("secret", encoding="utf-8")
    premiere_source = faux_pack_root / SOURCES_CANONIQUES[0]
    premiere_source.unlink()
    premiere_source.symlink_to(cible_hors_perimetre)

    with pytest.raises(SourceHorsConfinementRefusee):
        rejouer_stade(faux_pack_root)


# ---------------------------------------------------------------------------
# Revue scellée C00-002 tour 2 (APPROVE 2/3, 1 MAJEURE non résolue) —
# 1 test fermant le défaut mesuré fondé.
# ---------------------------------------------------------------------------


def test_source_hashes_chaine_est_refusee_pas_reduite_en_caracteres():
    """Gemini-3.1-Pro, MAJEURE, C00-002 tour 2 (mesurée fondée) : le type
    hint de `source_hashes` avait été perdu sur `construire_stage_state`
    (restauré), et `tuple(x)` sur une chaîne ne lève JAMAIS — il la réduit
    SILENCIEUSEMENT en un tuple d'un caractère par élément, corrompant
    STAGE-EVIDENCE.csv/STAGE.json sans erreur explicite. Reproduction
    EXACTE du risque décrit : passer une chaîne au lieu d'une séquence de
    hash doit désormais lever TypeError, jamais réduire en tuple de
    caractères."""
    with pytest.raises(TypeError, match="list ou un tuple"):
        construire_stage_state(
            program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
            core_status=CORE_STATUS_SOURCE, source_hashes="a" * 64,
        )
    # Contre-exemple : une VRAIE séquence de hash (list ou tuple) continue
    # de fonctionner normalement.
    etat = construire_stage_state(
        program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
        core_status=CORE_STATUS_SOURCE, source_hashes=["a" * 64, "b" * 64],
    )
    assert etat.source_hashes == ("a" * 64, "b" * 64)


# ---------------------------------------------------------------------------
# Revue scellée C00-002 tour 3 (APPROVE 1/3, 2 MAJEURE convergentes) —
# la garde liste-noire (str/bytes) ne fermait pas la classe du défaut.
# ---------------------------------------------------------------------------


def test_source_hashes_liste_blanche_ferme_toute_la_classe_pas_seulement_str():
    """Gemini-3.1-Pro + Qwen3.7-Max, MAJEURE CONVERGENTE, C00-002 tour 3
    (mesurée fondée) : une liste NOIRE (str/bytes seuls refusés) laissait
    passer d'AUTRES itérables dégénérés qui subissent la MÊME corruption
    silencieuse via tuple(...). Chaque cas ci-dessous est la reproduction
    EXACTE d'un exemple donné en revue — tous doivent désormais lever
    TypeError AVANT toute conversion."""
    cas_refuses = [
        bytearray(b"hash"),  # réduit en tuple d'entiers : (104, 97, 115, 104)
        {"h1" * 32, "h2" * 32},  # ordre non déterministe
        (x for x in []),  # générateur déjà épuisé -> () silencieux
        123,  # non itérable du tout — doit aussi être refusé, pas planter ailleurs
    ]
    for cas in cas_refuses:
        with pytest.raises(TypeError, match="list ou un tuple"):
            construire_stage_state(
                program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
                core_status=CORE_STATUS_SOURCE, source_hashes=cas,
            )


def test_source_hashes_element_non_str_est_refuse():
    """Défense complémentaire (pas explicitement demandée par la revue, mais
    ferme un trou adjacent évident) : une list/tuple qui passe la garde de
    CONTENEUR mais contient des éléments non-str (ex. des entiers) doit
    aussi être refusée — un hash SHA-256 est toujours une str."""
    with pytest.raises(TypeError):
        construire_stage_state(
            program_stage=PROGRAM_STAGE_SOURCE, modules=dict(MODULES_STATUTS_SOURCE),
            core_status=CORE_STATUS_SOURCE, source_hashes=[123, 456],
        )
