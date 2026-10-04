from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from m10_memoire.apprentissage import ApercuRefuse, analyser_candidats

CUTOFF = datetime(2026, 10, 2, tzinfo=UTC)
OUTILS = {"m3_creer_devis"}
CODES = {"REJ-CONTRAT-INVALIDE"}


def fait(cle: str, affaire: str, *, outil: str = "m3_creer_devis", resultat: str = "ok",
         code: str | None = None, dept: str = "m03-estimation", jour: str = "2026-09-20",
         ligne: str | None = None) -> dict:
    return {
        "type_entree": "fait_candidat", "cle_depot": cle, "affaire_id": affaire,
        "departement_source": dept, "outil": outil, "resultat": resultat, "code": code,
        "horodatage": f"{jour}T12:00:00+00:00", "ligne_id": ligne or hashlib.sha256(cle.encode()).hexdigest(),
    }


def analyser(maillons: list[dict]) -> dict:
    return analyser_candidats(
        maillons, cutoff_utc=CUTOFF, tete_affaires="a" * 64, tete_evenements="b" * 64,
        outils_m03=OUTILS, codes_m3=CODES,
    )


def test_trois_affaires_deduplique_et_hash_reproductible_sans_afficher_identifiants():
    maillons = [fait(f"k{i}", f"client-secret-{i}") for i in range(3)]
    maillons.extend(fait(f"retry-{i}", "client-secret-0") for i in range(4))
    maillons.append(fait("k0", "client-secret-0", ligne=hashlib.sha256(b"rejeu").hexdigest()))
    premier = analyser(maillons)
    second = analyser(maillons)
    assert len(premier["propositions"]) == 1
    proposition = premier["propositions"][0]
    assert proposition["affaires_distinctes"] == 3
    assert proposition["observations"] == 7
    assert "client-secret" not in repr(premier)
    assert premier["rapport_sha256"] == second["rapport_sha256"]


def test_moins_de_trois_affaires_n_est_pas_une_proposition():
    rapport = analyser([fait("1", "a"), fait("2", "b")])
    assert rapport["propositions"] == []


def test_domaines_autres_que_m03_et_evenements_sont_exclus():
    rapport = analyser([
        fait("a", "1", dept="m04-field-ops"),
        fait("b", "2", dept="m04-field-ops"),
        fait("c", "3", dept="m04-field-ops"),
        {"type_entree": "evenement_memorise", "corps": "private"},
    ])
    assert rapport["propositions"] == []


def test_resultats_discordants_restent_deux_groupes_sans_conclusion():
    rapport = analyser([fait("1", "a"), fait("2", "b"), fait("3", "c"),
                        fait("4", "d", resultat="refus", code="REJ-CONTRAT-INVALIDE"),
                        fait("5", "e", resultat="refus", code="REJ-CONTRAT-INVALIDE"),
                        fait("6", "f", resultat="refus", code="REJ-CONTRAT-INVALIDE")])
    assert {(p["resultat"], p["code"]) for p in rapport["propositions"]} == {
        ("ok", None), ("refus", "REJ-CONTRAT-INVALIDE")}
    assert all("confiance" not in p and "cause" not in p for p in rapport["propositions"])


def test_reutilisation_conflictuelle_de_cle_refuse():
    with pytest.raises(ApercuRefuse, match="clé de dépôt"):
        analyser([fait("same", "affaire-a"), fait("same", "affaire-b")])


def test_outil_et_code_hors_catalogue_sont_omis_sans_rendre_leurs_textes():
    rapport = analyser([
        fait(f"u{i}", f"lead-u{i}", outil="m3_private-client-id") for i in range(3)
    ] + [
        fait(f"c{i}", f"lead-c{i}", code=f"client-ssn-{i}") for i in range(3)
    ])
    rendu = repr(rapport)
    assert not rapport["propositions"]
    assert rapport["maillons_outil_hors_catalogue_omis"] == 3
    assert rapport["maillons_code_hors_catalogue_omis"] == 3
    assert "private-client" not in rendu and "ssn" not in rendu


@pytest.mark.parametrize("bad", [
    fait("1", "a", resultat="weird"),
    fait("1", "a", resultat=[]),
    {**fait("1", "a"), "horodatage": "2026-09-20T12:00:00"},
])
def test_fait_m03_malforme_refuse(bad: dict):
    with pytest.raises(ApercuRefuse):
        analyser([bad])


def test_plafond_maillons_et_cutoff_timezone_sont_fail_closed():
    with pytest.raises(ApercuRefuse, match="plafond"):
        analyser_candidats([{}] * 10_001, cutoff_utc=CUTOFF, tete_affaires=None, tete_evenements=None,
                           outils_m03=OUTILS, codes_m3=CODES)
    with pytest.raises(ApercuRefuse, match="cutoff"):
        analyser_candidats([], cutoff_utc=datetime(2026, 10, 2), tete_affaires=None, tete_evenements=None,
                           outils_m03=OUTILS, codes_m3=CODES)
