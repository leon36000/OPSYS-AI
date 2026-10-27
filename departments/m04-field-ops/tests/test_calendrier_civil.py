"""CRM-01, données fictives : vrai solveur DP, registre et dates civiles."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import calendrier_civil, cedule_tournees, etats

_spec = importlib.util.spec_from_file_location(
    "fixture_cedule_crm", Path(__file__).with_name("test_cedule_tournees.py"))
_aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_aide)
HORODATAGE, _monde, _proposer, _reussi = _aide.HORODATAGE, _aide._monde, _aide._proposer, _aide._reussi

FICTIF = True


def monde_date():
    reg, ids, positions = _monde()
    plan = _reussi(_proposer(reg, ids, positions))["plan_id"]
    _reussi(cedule_tournees.appliquer(reg, plan, positions, HORODATAGE, "admin.fictif"))
    return reg, ids, plan


def test_vrai_plan_applique_date_semaine_et_revision():
    reg, ids, plan = monde_date()
    avant = calendrier_civil.lire_semaine(reg, "2030-06-03")
    assert avant["interventions"] == [] and len(avant["sans_date"]) == len(ids)
    r = calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    assert r["revision"] == 1
    semaine = calendrier_civil.lire_semaine(reg, "2030-06-03")
    assert len(semaine["interventions"]) == len(ids) and not semaine["sans_date"]
    assert {i["intervention_id"] for i in semaine["interventions"]} == set(ids.values())
    assert all(i["debut"].startswith("2030-06-03T") and i["debut"].endswith("-04:00")
               and i["validite"] == "date_confirmee" for i in semaine["interventions"])
    assert calendrier_civil.lire_semaine(reg, "2030-06-10")["interventions"] == []
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-10"}, 1, "admin.fictif", HORODATAGE)
    assert calendrier_civil.lire_semaine(reg, "2030-06-03")["interventions"] == []
    assert len([m for m in reg.lire() if m["type_entree"] == "cedule_datee"]) == 2
    assert reg.valider_chaine()


@pytest.mark.parametrize("calendrier", [{}, {"1": "2030-06-03"}, {"0": "2030-02-30"},
    {"0": "20300603"}, {"0": "2030-06-03", "00": "2030-06-04"}, {True: "2030-06-03"}])
def test_calendrier_invalide_necrit_rien(calendrier):
    reg, _, plan = monde_date()
    avant = reg.lire()
    with pytest.raises(ValueError):
        calendrier_civil.confirmer(reg, plan, calendrier, 0, "admin.fictif", HORODATAGE)
    assert reg.lire() == avant


def test_proposition_seule_et_revision_perimee_refusees():
    reg, ids, positions = _monde()
    plan = _reussi(_proposer(reg, ids, positions))["plan_id"]
    with pytest.raises(ValueError):
        calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    reg, _, plan = monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    avant = reg.lire()
    with pytest.raises(ValueError, match="revision"):
        calendrier_civil.confirmer(reg, plan, {"0": "2030-06-10"}, 0, "admin.fictif", HORODATAGE)
    assert reg.lire() == avant


def test_annulation_conserve_trace_et_retire_validite():
    reg, ids, plan = monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    iid = next(iter(ids.values()))
    _reussi(etats.transitionner(iid, "annulee", reg, HORODATAGE))
    ligne = next(i for i in calendrier_civil.lire_semaine(reg, "2030-06-03")["interventions"]
                 if i["intervention_id"] == iid)
    assert ligne["statut"] == "annulee" and ligne["validite"] == "a_reconfirmer"
    assert ligne["source_ligne_id"]


@pytest.mark.parametrize("jour,minute", [("2030-03-10", 150), ("2030-11-03", 90)])
def test_dst_heure_inexistante_ou_ambigue_refusee(jour, minute):
    with pytest.raises(ValueError):
        calendrier_civil.instant_local(jour, minute)


def test_report_retour_planifie_ne_ressuscite_pas_la_date():
    reg, ids, plan = monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    iid = next(iter(ids.values()))
    _reussi(etats.transitionner(iid, "reportee", reg, HORODATAGE, motif="meteo"))
    _reussi(etats.transitionner(iid, "planifiee", reg, HORODATAGE))
    lignes = calendrier_civil.lire_semaine(reg, "2030-06-03")["interventions"]
    assert next(ligne for ligne in lignes if ligne["intervention_id"] == iid)["validite"] == "a_reconfirmer"
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-10"}, 1, "admin.fictif", HORODATAGE)
    assert all(ligne["validite"] == "date_confirmee"
               for ligne in calendrier_civil.lire_semaine(reg, "2030-06-10")["interventions"])


def test_reassignation_invalide_et_refuse_redatation():
    reg, ids, plan = monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    iid = next(iter(ids.values()))
    _reussi(etats.assigner_technicien(iid, "autre.fictif", reg, HORODATAGE))
    ligne = next(ligne for ligne in calendrier_civil.lire_semaine(reg, "2030-06-03")["interventions"]
                 if ligne["intervention_id"] == iid)
    assert ligne["validite"] == "a_reconfirmer" and ligne["technicien_actuel"] == "autre.fictif"
    with pytest.raises(ValueError, match="réassignée"):
        calendrier_civil.confirmer(reg, plan, {"0": "2030-06-10"}, 1, "admin.fictif", HORODATAGE)


def test_plan_remplacant_non_date_ne_ressuscite_pas_ancien_calendrier():
    reg, ids, positions = _monde()
    plan = _reussi(_proposer(reg, ids, positions))["plan_id"]
    _reussi(cedule_tournees.appliquer(reg, plan, positions, HORODATAGE, "admin.fictif"))
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    arguments = _aide._arguments(ids)
    for c in arguments["chantiers"]:
        c["fenetre"]["debut_min"] = 600
    nouveau = _reussi(_proposer(reg, ids, positions, arguments))["plan_id"]
    assert nouveau != plan
    _reussi(cedule_tournees.appliquer(reg, nouveau, positions, HORODATAGE, "admin.fictif"))
    semaine = calendrier_civil.lire_semaine(reg, "2030-06-03")
    assert semaine["interventions"] == [] and len(semaine["sans_date"]) == len(ids)
    with pytest.raises(ValueError, match="remplacé"):
        calendrier_civil.confirmer(reg, plan, {"0": "2030-06-10"}, 1, "admin.fictif", HORODATAGE)


def test_conflit_entre_deux_plans_meme_equipe_refuse_sans_ecriture():
    reg, ids, positions = _monde(leads=("ch-01",))
    args = _aide._arguments(ids, equipes=_aide._equipes()[:1])
    premier = _reussi(_proposer(reg, ids, positions, args))["plan_id"]
    _reussi(cedule_tournees.appliquer(reg, premier, positions, HORODATAGE, "admin.fictif"))
    calendrier_civil.confirmer(reg, premier, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    iid = ids["ch-01"]
    _reussi(etats.transitionner(iid, "en_route", reg, HORODATAGE,
                               assignation={"intervention_id": iid, "technicien_id": "eq-a"}))
    second_iid = _aide._inscrire(reg, "ch-02", "extension", False, 1)
    positions = _aide.Positions({lead: _aide.SITES[lead] for lead in ("ch-01", "ch-02")})
    args = _aide._arguments({"ch-02": second_iid}, equipes=_aide._equipes()[:1])
    second = _reussi(_proposer(reg, {"ch-02": second_iid}, positions, args))["plan_id"]
    _reussi(cedule_tournees.appliquer(reg, second, positions, HORODATAGE, "admin.fictif"))
    avant = reg.lire()
    with pytest.raises(ValueError, match="conflit"):
        calendrier_civil.confirmer(reg, second, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    assert reg.lire() == avant
    calendrier_civil.confirmer(reg, second, {"0": "2030-06-04"}, 0, "admin.fictif", HORODATAGE)


@pytest.mark.parametrize("valeur", ["2030-06-04", "2030-02-30", "9999-12-31", True, None])
def test_semaine_invalide(valeur):
    reg, _, _ = monde_date()
    with pytest.raises(ValueError):
        calendrier_civil.lire_semaine(reg, valeur)


def test_creneau_traversant_dst_refuse_meme_si_extremites_uniques():
    with pytest.raises(ValueError, match="durée"):
        calendrier_civil._creneau({"jour": 0}, {"debut_min": 30, "fin_min": 210}, {"0": "2030-03-10"})


def test_source_alteree_ferme_lecture():
    from m4_field_ops.registre import Registre, VerificationError

    reg, _, plan = monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    maillons = reg.lire()
    maillons[-1]["calendrier"]["0"] = "2030-06-04"
    with pytest.raises(VerificationError):
        calendrier_civil.lire_semaine(Registre(maillons), "2030-06-03")
