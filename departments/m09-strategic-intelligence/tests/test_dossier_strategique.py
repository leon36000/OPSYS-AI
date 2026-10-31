"""M9 — dossier stratégique : faits citables adressés, manques nommés, arrivée tardive, bornes (fictif)."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import conseil
from m9_strategic_intelligence import dossier_strategique as ds

FICTIF = True
REF = "2026-10-21T12:00:00Z"


def _cap(lecture_id, reponse, *, index, precedent="", recu_a=REF, arguments=None):
    return cs.construire(
        cat.obtenir(lecture_id),
        arguments or {},
        [reponse],
        recu_a=recu_a,
        reference=None,
        index=index,
        hash_precedent=precedent,
    )


def _chaine():
    a = _cap(
        "m6.disponibilite", {"ok": True, "resultat": {"accepte": True, "resultat": {"stock": 12, "ok": True}}}, index=0
    )
    b = _cap(
        "m2.leads",
        {"ok": True, "resultat": {"accepte": True, "resultat": {"total": 3, "leads": [], "suivant": None}}},
        index=1,
        precedent=a["hash_maillon"],
        arguments={"horodatage": REF},
    )
    c = _cap(
        "m4.interventions", {"ok": False, "erreur": "producteur_indisponible"}, index=2, precedent=b["hash_maillon"]
    )
    return [a, b, c]


def test_faits_adresses_en_texte_exact_et_manques_nommes():
    dossier = ds.construire(
        _chaine(),
        question="Que faire du stock ?",
        domaines=["stock", "cash"],
        reference=REF,
        connaissance=REF,
        attendues=["m6.disponibilite", "m2.leads", "m4.interventions", "m5.comptes_a_payer"],
    )
    assert dossier["faits"]["m6.disponibilite#0:p0.resultat.resultat.stock"] == "12"
    assert dossier["faits"]["m6.disponibilite#0:p0.resultat.resultat.ok"] == "true"
    assert dossier["faits"]["m2.leads#1:p0.resultat.resultat.total"] == "3"
    assert not any(
        adresse.startswith("m4.interventions") for adresse in dossier["faits"]
    )  # refusée : aucun fait citable
    statuts = {m["lecture_id"]: m["statut"] for m in dossier["manques"]}
    assert statuts["m4.interventions"] == "REFUSEE" and statuts["m5.comptes_a_payer"] == "ABSENTE"
    assert dossier["couverture"]["complete"] is False


def test_les_faits_du_dossier_sont_exactement_les_sources_admissibles_du_conseil():
    dossier = ds.construire(
        _chaine(), question="Q", domaines=["stock"], reference=REF, connaissance=REF, attendues=["m6.disponibilite"]
    )
    sortie = {
        "affirmations": [
            {
                "id": "A",
                "nature": "observation_source",
                "reference": "m6.disponibilite#0:p0.resultat.resultat.stock",
                "valeur": "12",
            }
        ]
    }
    assert (
        conseil.admettre_proposition(sortie, sources=dossier["faits"])["affirmations"][0]["statut"]
        == "SOURCE_CONCORDANTE"
    )
    sortie["affirmations"][0]["valeur"] = "12.0"
    with pytest.raises(ValueError, match="REJ-CONSEIL-CITATION"):
        conseil.admettre_proposition(sortie, sources=dossier["faits"])


def test_arrivee_tardive_absente_du_dossier_connu_avant():
    chaine = _chaine()
    tardive = _cap(
        "m6.disponibilite",
        {"ok": True, "resultat": {"accepte": True, "resultat": {"stock": 3}}},
        index=3,
        precedent=chaine[2]["hash_maillon"],
        recu_a="2026-10-22T09:00:00Z",
    )
    avant = ds.construire(
        [*chaine, tardive],
        question="Q",
        domaines=["stock"],
        reference=REF,
        connaissance=REF,
        attendues=["m6.disponibilite"],
    )
    apres = ds.construire(
        [*chaine, tardive],
        question="Q",
        domaines=["stock"],
        reference=REF,
        connaissance="2026-10-22T10:00:00Z",
        attendues=["m6.disponibilite"],
    )
    assert avant["faits"]["m6.disponibilite#0:p0.resultat.resultat.stock"] == "12"
    assert apres["faits"]["m6.disponibilite#3:p0.resultat.resultat.stock"] == "3"
    assert not any(
        adresse.startswith("m6.disponibilite#0") for adresse in apres["faits"]
    )  # remplacé par la plus récente
    assert avant["dossier_id"] != apres["dossier_id"]


def test_bornes_comptees_jamais_tronquees_en_silence_et_dossier_reproductible():
    dossier = ds.construire(
        _chaine(),
        question="Q",
        domaines=["stock"],
        reference=REF,
        connaissance=REF,
        attendues=["m6.disponibilite", "m2.leads"],
        max_faits=2,
    )
    assert len(dossier["faits"]) == 2 and dossier["faits_non_retenus"] >= 1
    pareil = ds.construire(
        _chaine(),
        question="Q",
        domaines=["stock"],
        reference=REF,
        connaissance=REF,
        attendues=["m6.disponibilite", "m2.leads"],
        max_faits=2,
    )
    assert pareil["dossier_id"] == dossier["dossier_id"]


@pytest.mark.parametrize("question", ["", "   ", "x" * 2049, None, 3])
def test_question_invalide_refusee(question):
    with pytest.raises(ValueError, match="REJ-DOSSIER-QUESTION"):
        ds.construire([], question=question, domaines=["stock"], reference=REF, connaissance=REF)


def test_capture_partielle_donne_ses_faits_reels_et_reste_nommee_partielle():
    cedule = cs.construire(
        cat.obtenir("m4.cedule_semaine"),
        {"debut_semaine": "2026-11-02"},
        [
            {
                "ok": True,
                "resultat": {"accepte": True, "resultat": {"interventions": [{"revision": 1}], "tronque": True}},
            }
        ],
        recu_a=REF,
        reference=None,
        index=0,
        hash_precedent="",
    )
    dossier = ds.construire(
        [cedule], question="Q", domaines=["capacite"], reference=REF, connaissance=REF, attendues=["m4.cedule_semaine"]
    )
    assert dossier["lectures_partielles"] == ["m4.cedule_semaine"]
    assert dossier["faits"]["m4.cedule_semaine#0:p0.resultat.resultat.interventions[0].revision"] == "1"
    assert dossier["faits"]["m4.cedule_semaine#0:p0.resultat.resultat.tronque"] == "true"
    assert dossier["couverture"]["complete"] is False
