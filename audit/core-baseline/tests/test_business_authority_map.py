"""Chore — Tests RED→GREEN pour la carte d'autorité MÉTIER M1-M10 (agrégats
fins), qui débloque C03-002.

Contexte (revue d'architecture dédiée avant ce chore, Claude Opus 5 natif,
6 questions fermées) : `audit/core-baseline/AUTHORITY-MAP.csv` (C00-004,
déjà ratifié) cartographie des CHEMINS — `aggregate` y est TOUJOURS égal
au nom du module lui-même (tautologique par conception,
`test_construire_carte_autorites_10_modules_plus_4_core` l'exige :
`len == 14`, cf. `test_path_and_authority_map.py`). Cette carte-ci
cartographie des AGRÉGATS MÉTIER FINS (`ledger`, `clients`,
`stock movements`, ...) — la seule donnée capable de satisfaire non
trivialement le cas RED obligatoire #1 de C03-002 (« M5 finance, M6
stock, M2 CRM restent propriétaires »). Les deux cartes restent des
artefacts SÉPARÉS (clés `owner` différentes : `M5` ici vs
`M5-financecore` dans AUTHORITY-MAP.csv — jointure future via une table
d'alias, hors périmètre de ce chore).

Source : `sources/continuity/matrices/RF01-W11-AUTHORITY-MAP-M1-M10.csv`
du pack (catalogue `RESEARCH_CONTINUITY`, jamais un livrable de tâche
ratifié en tant que tel) — copiée localement dans
`audit/core-baseline/sources/`, sha256 vérifié À L'EXÉCUTION
(867969610e9d8a442aeb9879818b9165877952f2ca3cede7d8236d44bb8c3648,
`12-SOURCE-INVENTORY.csv:121` du pack) plutôt que supposé une fois pour
toutes — même discipline que `InventaireDeriveRefuse` en C00-004.

Règle de découpage — RATIFIÉE PAR CE CHORE, pas par l'algorithme seul :
split de la colonne `authoritative_for` sur `,` UNIQUEMENT (jamais `/` ni
`and`, qui apparaissent dans des cellules ambiguës : `AR/AP`,
`predicted costs/margins`, `assets/rights`, `cash and financial truth`).
`test_extraits_cas_red_c03_002` ancre des valeurs concrètes pour que la
revue scellée puisse les vérifier une à une, pas seulement l'algorithme."""
from __future__ import annotations

import csv
import hashlib
import io
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE))
import custody
import business_authority_map as bam
from business_authority_map import (
    BusinessAuthorityRecord,
    SourceSha256Divergente,
    ReversibiliteRefusee,
    AgregatDuplique,
    SOURCE_CSV,
    SOURCE_SHA256_ATTENDU,
    construire_carte_autorite_metier,
    produire_sortie,
)

SOURCE_CSV_REEL = BASE / "sources" / "RF01-W11-AUTHORITY-MAP-M1-M10.csv"


# ---------------------------------------------------------------------------
# Provenance de la copie locale — la garantie que le reste de ce fichier
# raisonne sur les VRAIES 11 lignes du pack, pas une transcription altérée.
# ---------------------------------------------------------------------------


def test_copie_locale_sha256_attendu():
    reel = hashlib.sha256(SOURCE_CSV_REEL.read_bytes()).hexdigest()
    assert reel == SOURCE_SHA256_ATTENDU == (
        "867969610e9d8a442aeb9879818b9165877952f2ca3cede7d8236d44bb8c3648"
    )


def test_constante_source_csv_pointe_la_copie_reelle():
    assert SOURCE_CSV.resolve() == SOURCE_CSV_REEL.resolve()


# ---------------------------------------------------------------------------
# construire_carte_autorite_metier — sur la VRAIE source (63 lignes / 11
# owners attendus, calculé manuellement par split virgule avant ce chore :
# CORE=6, M1=5, M2=5, M3=5, M4=7, M5=7, M6=7, M7=6, M8=5, M9=5, M10=5).
# ---------------------------------------------------------------------------


def test_carte_63_lignes_11_owners():
    carte = construire_carte_autorite_metier()
    assert len(carte) == 63
    owners = {r.owner for r in carte}
    assert owners == {"CORE", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10"}
    assert len(owners) == 11


def test_repartition_exacte_par_owner():
    carte = construire_carte_autorite_metier()
    compte = {}
    for r in carte:
        compte[r.owner] = compte.get(r.owner, 0) + 1
    assert compte == {
        "CORE": 6, "M1": 5, "M2": 5, "M3": 5, "M4": 7,
        "M5": 7, "M6": 7, "M7": 6, "M8": 5, "M9": 5, "M10": 5,
    }


def test_reversibilite_sur_la_vraie_source():
    """Regrouper les aggregates par owner (dans l'ordre de production) et
    les rejoindre avec ', ' doit reproduire EXACTEMENT la cellule
    `authoritative_for` d'origine — preuve que le split n'a rien perdu ni
    déformé, sur les 11 lignes réelles, pas seulement en théorie."""
    carte = construire_carte_autorite_metier()
    par_owner: dict[str, list[str]] = {}
    for r in carte:
        par_owner.setdefault(r.owner, []).append(r.aggregate)

    with SOURCE_CSV_REEL.open("r", encoding="utf-8", newline="") as f:
        lignes_source = {ligne["module"]: ligne["authoritative_for"] for ligne in csv.DictReader(f)}

    assert set(par_owner) == set(lignes_source)
    for owner, cellule_originale in lignes_source.items():
        assert ", ".join(par_owner[owner]) == cellule_originale


def test_aucun_slash_ou_and_sur_decoupe():
    """Cas RED explicite du plan verrouillé : les tokens contenant `/` ou
    ` and ` DOIVENT rester un seul agrégat intact, jamais sur-découpés."""
    carte = construire_carte_autorite_metier()
    aggregates = {r.aggregate for r in carte}
    for attendu in ("AR/AP", "predicted costs/margins", "assets/rights", "cash and financial truth"):
        assert attendu in aggregates, f"{attendu!r} absent — sur-découpage suspecté sur / ou and"


def test_extraits_cas_red_c03_002():
    """Ancrage direct au cas RED obligatoire #1 de C03-002 : « M5 finance,
    M6 stock, M2 CRM restent propriétaires » — valeurs vérifiables une à
    une par la revue scellée, pas seulement l'algorithme de split."""
    carte = {(r.aggregate, r.owner) for r in construire_carte_autorite_metier()}
    attendus = {
        ("ledger", "M5"), ("invoices", "M5"), ("payments", "M5"),
        ("materials catalog", "M6"), ("stock movements", "M6"), ("reservations", "M6"),
        ("clients", "M2"), ("leads", "M2"), ("pipeline", "M2"),
    }
    assert attendus <= carte


def test_aucun_agregat_duplique_entre_owners():
    carte = construire_carte_autorite_metier()
    vu: dict[str, str] = {}
    for r in carte:
        assert r.aggregate not in vu or vu[r.aggregate] == r.owner, (
            f"agrégat {r.aggregate!r} revendiqué par {vu.get(r.aggregate)!r} ET {r.owner!r}"
        )
        vu[r.aggregate] = r.owner


def test_chaque_record_reference_le_bon_numero_de_ligne_source():
    """`source_row` doit correspondre au numéro de ligne 1-indexé (hors
    en-tête) de la ligne `module` d'origine dans le CSV source — traçable
    sans ambiguïté vers la source, pas un simple doublon de `owner`."""
    with SOURCE_CSV_REEL.open("r", encoding="utf-8", newline="") as f:
        numero_par_module = {ligne["module"]: i for i, ligne in enumerate(csv.DictReader(f), start=1)}
    carte = construire_carte_autorite_metier()
    for r in carte:
        assert r.source_row == numero_par_module[r.owner]


def test_tous_les_source_sha256_identiques_et_attendus():
    carte = construire_carte_autorite_metier()
    assert {r.source_sha256 for r in carte} == {SOURCE_SHA256_ATTENDU}


# ---------------------------------------------------------------------------
# Cas RED sur données SYNTHÉTIQUES — isolent chaque garde sans dépendre
# (ni risquer d'altérer) le vrai fichier source.
# ---------------------------------------------------------------------------


def _ecrire_csv_synthetique(tmp_path: Path, lignes: list[tuple[str, str]]) -> Path:
    chemin = tmp_path / "source-synthetique.csv"
    with chemin.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["module", "authoritative_for", "prohibited_authority"])
        for module, authoritative_for in lignes:
            writer.writerow([module, authoritative_for, "n/a"])
    return chemin


def test_source_sha256_divergent_refuse(tmp_path):
    chemin = _ecrire_csv_synthetique(tmp_path, [("X", "a, b")])
    sha_reel = hashlib.sha256(chemin.read_bytes()).hexdigest()
    with pytest.raises(SourceSha256Divergente):
        construire_carte_autorite_metier(
            chemin_source=chemin,
            sha256_attendu="0" * 64,
        )
    # confirme que le sha256 RÉEL (non forcé à divergence) aurait, lui,
    # été accepté — la garde teste bien la comparaison, pas un refus
    # systématique déguisé.
    assert construire_carte_autorite_metier(chemin_source=chemin, sha256_attendu=sha_reel)


def test_reversibilite_refusee_sur_espacement_irregulier(tmp_path):
    """Une cellule avec un espacement irrégulier autour d'une virgule
    (`"a,  b"`, double espace) ne peut pas survivre à un split+strip+join
    strict — cas RED réel, pas fabriqué : preuve que la garde de
    réversibilité mord vraiment sur une entrée plausible, pas seulement
    en théorie."""
    chemin = _ecrire_csv_synthetique(tmp_path, [("X", "a,  b")])
    sha_reel = hashlib.sha256(chemin.read_bytes()).hexdigest()
    with pytest.raises(ReversibiliteRefusee):
        construire_carte_autorite_metier(chemin_source=chemin, sha256_attendu=sha_reel)


def test_agregat_duplique_entre_deux_owners_refuse(tmp_path):
    chemin = _ecrire_csv_synthetique(tmp_path, [("X", "shared, only_x"), ("Y", "shared, only_y")])
    sha_reel = hashlib.sha256(chemin.read_bytes()).hexdigest()
    with pytest.raises(AgregatDuplique):
        construire_carte_autorite_metier(chemin_source=chemin, sha256_attendu=sha_reel)


def test_meme_owner_repete_le_meme_agregat_nest_pas_un_conflit(tmp_path):
    """Un agrégat déjà vu POUR LE MÊME owner (doublon intra-ligne, ex.
    cellule mal écrite deux fois) n'est pas le cas RED « deux writers » —
    seul un owner DIFFÉRENT sur le même agrégat doit être refusé."""
    chemin = _ecrire_csv_synthetique(tmp_path, [("X", "a, a, b")])
    sha_reel = hashlib.sha256(chemin.read_bytes()).hexdigest()
    carte = construire_carte_autorite_metier(chemin_source=chemin, sha256_attendu=sha_reel)
    assert [r.aggregate for r in carte] == ["a", "a", "b"]


# ---------------------------------------------------------------------------
# BusinessAuthorityRecord — garde de forme, indépendante du CSV.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("champ,valeur", [
    ("aggregate", ""), ("aggregate", "   "),
    ("owner", ""), ("owner", "   "),
])
def test_record_refuse_champ_texte_vide(champ, valeur):
    kwargs = dict(aggregate="a", owner="M1", source_row=1, source_sha256=SOURCE_SHA256_ATTENDU)
    kwargs[champ] = valeur
    with pytest.raises(ValueError):
        BusinessAuthorityRecord(**kwargs)


@pytest.mark.parametrize("source_row", [0, -1, True, "1"])
def test_record_refuse_source_row_invalide(source_row):
    with pytest.raises(ValueError):
        BusinessAuthorityRecord(
            aggregate="a", owner="M1", source_row=source_row,
            source_sha256=SOURCE_SHA256_ATTENDU,
        )


@pytest.mark.parametrize("sha", ["", "pasunhash", "0" * 63, "g" * 64])
def test_record_refuse_sha256_mal_forme(sha):
    with pytest.raises(ValueError):
        BusinessAuthorityRecord(aggregate="a", owner="M1", source_row=1, source_sha256=sha)


# ---------------------------------------------------------------------------
# produire_sortie — écriture confinée (custody), déterminisme octet pour
# octet, en-tête exacte.
# ---------------------------------------------------------------------------


class TestProduireSortie:
    """`sortie_dir` ET `worktree` sont tous deux un `tmp_path` arbitraire
    ici (même régime que C00-002/003, cf. commentaire dans
    test_path_and_authority_map.py) — cette fonction ne vérifie aucun
    chemin RÉEL du disque produit, contrairement à `path_and_authority_map`
    (C00-004) qui, lui, exige le vrai worktree."""

    def test_entete_exacte_et_63_lignes(self, tmp_path):
        chemin = produire_sortie(sortie_dir=tmp_path, worktree=tmp_path)
        with chemin.open("r", encoding="utf-8", newline="") as f:
            lecteur = csv.DictReader(f)
            assert lecteur.fieldnames == ["aggregate", "owner", "source_row", "source_sha256"]
            lignes = list(lecteur)
        assert len(lignes) == 63

    def test_deterministe_octet_pour_octet(self, tmp_path):
        chemin_a = produire_sortie(sortie_dir=tmp_path / "a", worktree=tmp_path)
        chemin_b = produire_sortie(sortie_dir=tmp_path / "b", worktree=tmp_path)
        assert chemin_a.read_bytes() == chemin_b.read_bytes()

    def test_refuse_symlink_via_custody(self, tmp_path):
        """`produire_sortie` doit refuser d'écrire à travers un symlink —
        preuve qu'elle passe réellement par `custody.ecrire_sans_suivre_symlink`,
        pas une écriture maison qui contournerait la garde anti-symlink."""
        cible_hors_confinement = tmp_path.parent / "hors-confinement.csv"
        lien = tmp_path / "BUSINESS-AUTHORITY-MAP-M1-M10.csv"
        lien.symlink_to(cible_hors_confinement)
        with pytest.raises(custody.EcritureViaSymlinkRefusee):
            produire_sortie(sortie_dir=tmp_path, worktree=tmp_path)
        assert not cible_hors_confinement.exists()
