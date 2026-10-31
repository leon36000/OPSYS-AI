"""Contrats des propriétaires : validation du contrat réel, absence nommée, aucune valeur fabriquée (fictif).

Les trois contrats attendus (M4, M7, M1) sont désormais publiés et branchés : la validation d'un
domaine est celle du contrat RÉEL de son propriétaire, rejouée par la capture. Les cas détaillés sont dans
test_raccord_m4_capacite.py, test_raccord_m7_depenses.py et test_raccord_m1_plaintes.py ; ce fichier tient la table des
contrats, le refus d'une charge qui n'est pas un objet et le refus d'une extrapolation présentée comme prévision."""

import pytest
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import contrats_attendus as ca
from m9_strategic_intelligence import tendances

FICTIF = True
DOMAINES = {"capacite_equipe", "depenses_marketing", "plaintes_structurees"}


def test_la_table_des_contrats_et_leur_etat_se_lisent_sur_le_catalogue():
    assert set(ca.CONTRATS) == DOMAINES
    etats = {r["domaine"]: r["etat"] for r in ca.resume()}
    assert set(etats.values()) == {"PUBLIE"}
    for domaine in DOMAINES:
        contrat = ca.CONTRATS[domaine]
        lecture = cat.PAR_ID[contrat["lecture_id"]]
        assert lecture.outil == contrat["outil_attendu"]
        assert contrat["proprietaire"] == lecture.departement
    assert all(r["limite"] and r["outil_attendu"] for r in ca.resume())


def test_un_contrat_dont_la_lecture_n_est_pas_au_catalogue_est_dit_absent_chez_le_proprietaire(monkeypatch):
    monkeypatch.delitem(cat.PAR_ID, "m7.depenses_marketing")
    assert ca.etat("depenses_marketing") == "ABSENT_CHEZ_LE_PROPRIETAIRE"
    assert ca.etat("capacite_equipe") == "PUBLIE"


@pytest.mark.parametrize("domaine", sorted(DOMAINES))
def test_une_charge_qui_n_est_pas_un_objet_n_est_jamais_conforme(domaine):
    for pas_objet in (None, [], "texte", 3, b""):
        verdict = ca.valider_charge(domaine, pas_objet)
        assert verdict["conforme"] is False and verdict["manques"] == ["charge"]


@pytest.mark.parametrize("domaine", sorted(DOMAINES))
def test_un_objet_vide_ou_etranger_au_contrat_est_refuse_sans_rien_completer(domaine):
    for charge in ({}, {"debut": "2026-10-01", "fin": "2026-10-31", "couverture": "COMPLETE"}):
        avant = dict(charge)
        verdict = ca.valider_charge(domaine, charge)
        assert verdict["conforme"] is False and verdict["erreurs"] and charge == avant


def test_les_categories_de_plainte_du_contrat_sont_celles_du_catalogue_de_m9():
    assert {"insatisfaction", "degat", "garantie", "avocat", "securite"} == ca.CATEGORIES_PLAINTE


def test_une_extrapolation_de_m9_n_est_jamais_une_prevision_de_proprietaire():
    assert tendances.ORIGINE == ca.ORIGINE_EXTRAPOLATION
    extrapolation = {"origine": tendances.ORIGINE, "methodes": []}
    with pytest.raises(ValueError, match="REJ-CONTRAT-EXTRAPOLATION"):
        ca.refuser_extrapolation(extrapolation, presentee_comme_prevision_de_proprietaire=True)
    # Dite pour ce qu'elle est, elle passe ; une vraie prévision de propriétaire n'est pas visée.
    ca.refuser_extrapolation(extrapolation, presentee_comme_prevision_de_proprietaire=False)
    ca.refuser_extrapolation({"prevision_id": "a" * 64}, presentee_comme_prevision_de_proprietaire=True)
