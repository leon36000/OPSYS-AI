"""Détail calendrier : registres réels et outils SQL, données fictives seulement."""
import importlib.util
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest
from m4_field_ops import calendrier_civil, cedule_tournees, etats
from m4_field_ops.outils import outils
from m4_field_ops.registre import Registre, VerificationError

from opsys import identite, stockage
from opsys.outils import Autonomie


def _charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(fichier))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pur = _charger("fixture_calendrier_detail_pur", "test_calendrier_civil.py")
sql = _charger("fixture_calendrier_detail_sql", "test_cedule_tournees_outils.py")
instance, par_nom, interventions = sql.instance, sql.par_nom, sql.interventions
FICTIF = True


def _lire(par_nom, plan, acteur=sql.ADMIN):
    return sql._appeler(par_nom, "m4_lire_calendrier_plan", {"plan_id": plan}, acteur)


def test_plan_applique_sans_dates_sources_et_aucune_mutation():
    reg, ids, plan = pur.monde_date()
    avant = reg.lire()
    resultat = calendrier_civil.lire_plan(reg, plan)
    assert resultat["revision"] == 0
    assert resultat["calendrier"] == {} and resultat["source_ligne_id"] is None
    assert resultat["jours"] == [0] and resultat["total_jours"] == 1
    assert resultat["total_visites"] == len(ids) == len(resultat["visites"])
    assert {v["intervention_id"] for v in resultat["visites"]} == set(ids.values())
    assert not resultat["tronque"] and resultat["bloquants"] == []
    for typ, champ in [(cedule_tournees.TYPE_PROPOSEE, "source_proposition_id"),
                       (cedule_tournees.TYPE_APPLIQUEE, "source_application_id")]:
        assert resultat[champ] == next(m["ligne_id"] for m in avant if m["type_entree"] == typ)
    assert set(resultat["visites"][0]) == {
        "intervention_id", "equipe_id", "jour", "debut_min", "fin_min", "statut", "bloquants"}
    assert reg.lire() == avant


def test_date_et_revision_explicitement_courantes_sans_mutation():
    reg, _, plan = pur.monde_date()
    for revision, jour in enumerate(["2030-06-03", "2030-06-10"]):
        source = calendrier_civil.confirmer(reg, plan, {"0": jour}, revision, "admin.fictif", pur.HORODATAGE)
        avant = reg.lire()
        resultat = calendrier_civil.lire_plan(reg, plan)
        assert resultat["calendrier"] == {"0": jour}
        assert resultat["revision"] == revision + 1
        assert resultat["source_ligne_id"] == source["ligne_id"]
        assert reg.lire() == avant


def test_inconnu_propose_seulement_et_identifiant_invalide_refuses():
    reg, ids, positions = pur._monde()
    plan = pur._reussi(pur._proposer(reg, ids, positions))["plan_id"]
    avant = reg.lire()
    for valeur in [plan, "inconnu", None, [], True]:
        with pytest.raises(ValueError, match="plan appliqué"):
            calendrier_civil.lire_plan(reg, valeur)
    assert reg.lire() == avant


@pytest.mark.parametrize("changement,code", [("annulee", "intervention_non_planifiee"),
                                              ("reportee", "intervention_non_planifiee"),
                                              ("equipe", "equipe_reassignee")])
def test_blocages_courants_et_refus_mutation_apres_lecture(changement, code):
    reg, ids, plan = pur.monde_date()
    assert calendrier_civil.lire_plan(reg, plan)["bloquants"] == []
    iid = next(iter(ids.values()))
    if changement == "equipe":
        pur._reussi(etats.assigner_technicien(iid, "equipe-autre.fictive", reg, pur.HORODATAGE))
    else:
        pur._reussi(etats.transitionner(iid, changement, reg, pur.HORODATAGE,
                                        **({"motif": "meteo"} if changement == "reportee" else {})))
    avant = reg.lire()
    resultat = calendrier_civil.lire_plan(reg, plan)
    assert code in resultat["bloquants"]
    assert code in next(v for v in resultat["visites"] if v["intervention_id"] == iid)["bloquants"]
    with pytest.raises(ValueError):
        calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", pur.HORODATAGE)
    assert reg.lire() == avant


def test_plan_remplace_conserve_ses_sources_et_signale_blocage():
    reg, ids, positions = pur._monde()
    plan = pur._reussi(pur._proposer(reg, ids, positions))["plan_id"]
    pur._reussi(cedule_tournees.appliquer(reg, plan, positions, pur.HORODATAGE, "admin.fictif"))
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", pur.HORODATAGE)
    args = pur._aide._arguments(ids)
    for chantier in args["chantiers"]:
        chantier["fenetre"]["debut_min"] = 600
    autre = pur._reussi(pur._proposer(reg, ids, positions, args))["plan_id"]
    pur._reussi(cedule_tournees.appliquer(reg, autre, positions, pur.HORODATAGE, "admin.fictif"))
    avant = reg.lire()
    resultat = calendrier_civil.lire_plan(reg, plan)
    assert "plan_remplace" in resultat["bloquants"]
    assert all("plan_remplace" in v["bloquants"] for v in resultat["visites"])
    assert resultat["calendrier"] == {"0": "2030-06-03"} and resultat["revision"] == 1
    assert calendrier_civil.lire_plan(reg, autre)["revision"] == 0
    assert reg.lire() == avant


@pytest.mark.parametrize("nombre,jours,tronque", [(200, 31, False), (201, 1, True), (32, 32, True)])
def test_bornes_independantes_registre_chaine(nombre, jours, tronque):
    # Historique volumineux fictif importé dans le VRAI registre, sans solveur simulé.
    reg, _, plan = pur.monde_date()
    proposition = next(m for m in reg.lire() if m["type_entree"] == cedule_tournees.TYPE_PROPOSEE)
    application = next(m for m in reg.lire() if m["type_entree"] == cedule_tournees.TYPE_APPLIQUEE)
    route = proposition["sortie"]["plan"][0]
    visite = route["visites"][0]
    proposition["plan_id"] = application["plan_id"] = "plan-volume-fictif"
    proposition["sortie"]["plan"] = [
        {**deepcopy(route), "jour": n % jours,
         "visites": [{**deepcopy(visite), **({"chantier": "absent-fictif"} if n == 200 else {})}]}
        for n in range(nombre)]
    # Un jour inutilisé ne doit pas créer un champ de date dans l'interface.
    proposition["sortie"]["plan"].append({**deepcopy(route), "jour": 999, "visites": []})
    reg.ajouter(proposition)
    reg.ajouter(application)
    calendrier = {str(j): (date(2030, 6, 1) + timedelta(days=j)).isoformat() for j in range(jours)}
    reg.ajouter({"type_entree": calendrier_civil.TYPE_DATEE, "plan_id": "plan-volume-fictif",
                 "horodatage": pur.HORODATAGE, "revision": 1, "calendrier": calendrier,
                 "source_application_id": reg.tete()})
    avant = reg.lire()
    resultat = calendrier_civil.lire_plan(reg, "plan-volume-fictif")
    assert resultat["total_visites"] == nombre and len(resultat["visites"]) == min(nombre, 200)
    assert resultat["total_jours"] == jours and resultat["jours"] == list(range(min(jours, 31)))
    assert resultat["tronque"] is tronque and len(resultat["calendrier"]) <= 31
    assert resultat["calendrier"] == {str(j): calendrier[str(j)] for j in range(min(jours, 31))}
    assert "999" not in resultat["calendrier"]
    if nombre == 201:
        assert "intervention_non_planifiee" in resultat["bloquants"]
        assert all(not v["bloquants"] for v in resultat["visites"])
    assert reg.valider_chaine() and reg.lire() == avant


def test_chaine_alteree_refusee():
    reg, _, plan = pur.monde_date()
    maillons = reg.lire()
    maillons[-1]["plan_id"] = "alteration-fictive"
    with pytest.raises(VerificationError):
        calendrier_civil.lire_plan(Registre(maillons), plan)


def test_outil_sql_t0_admin_lecture_sans_changement_et_reouverture(par_nom, interventions):
    outil = par_nom["m4_lire_calendrier_plan"]
    assert outil.autonomie == Autonomie.T0 and outil.roles_appareil == frozenset({"admin"})
    plan = sql._resultat(sql._proposer(par_nom, interventions))["plan_id"]
    avant = sql._etat()
    assert sql._code_refus(_lire(par_nom, plan)) == "REJ-CONTRAT-INVALIDE"
    assert sql._etat() == avant
    sql._resultat(sql._appliquer(par_nom, plan))
    avant = sql._etat()
    resultat = sql._resultat(_lire(par_nom, plan))
    assert resultat["revision"] == 0 and resultat["total_visites"] == 6
    assert sql._etat() == avant
    stockage.liberer()
    assert sql._resultat(_lire({o.nom: o for o in outils()}, plan)) == resultat
    assert sql._etat() == avant
    confirmation = sql._resultat(sql._appeler(par_nom, "m4_confirmer_dates_cedule", {
        "plan_id": plan, "calendrier": {"0": "2030-06-03"}, "revision_attendue": 0}, sql.ADMIN))
    avant = sql._etat()
    datee = sql._resultat(_lire(par_nom, plan))
    assert datee["revision"] == 1 and datee["calendrier"] == {"0": "2030-06-03"}
    assert datee["source_ligne_id"] == confirmation["ligne_id"]
    assert sql._etat() == avant


@pytest.mark.parametrize("acteur", [None, sql.MARC, sql.VENDEUR, sql.FANTOME])
def test_outil_sql_non_admin_refuse_sans_changement(par_nom, acteur):
    avant = sql._etat()
    assert sql._code_refus(_lire(par_nom, "inconnu", acteur)) in {
        "REJ-HUMAIN-REQUIS", "REJ-IDENTITE-APPAREIL-INVALIDE"}
    assert sql._etat() == avant


def test_outil_sql_role_admin_revoque_revalide_chaque_lecture(par_nom, interventions):
    plan = sql._resultat(sql._proposer(par_nom, interventions))["plan_id"]
    sql._resultat(sql._appliquer(par_nom, plan))
    assert sql._resultat(_lire(par_nom, plan))["plan_id"] == plan
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, sql.ADMIN.personne, "admin")
    avant = sql._etat()
    assert sql._code_refus(_lire(par_nom, plan)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert sql._etat() == avant
