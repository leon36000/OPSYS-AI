"""Aperçu civil sur vrais registres et solveur M4; données exclusivement fictives."""
import importlib.util
import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from m4_field_ops import apercu_mois as apercu
from m4_field_ops import calendrier_civil, cedule_tournees, etats
from m4_field_ops.registre import Registre

_spec = importlib.util.spec_from_file_location(
    "fixture_apercu_mois", Path(__file__).with_name("test_calendrier_civil.py"))
pur = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pur)
FICTIF = True


def monde(dates=("2030-05-31", "2030-06-01", "2030-07-01")):
    reg, ids, positions = pur._monde()
    args = pur._aide._arguments(ids, equipes=pur._aide._equipes(jours=(0, 1, 2)))
    for i, chantier in enumerate(args["chantiers"]):
        chantier["fenetre"]["jours"] = [i]
    plan = pur._reussi(pur._proposer(reg, ids, positions, args))["plan_id"]
    pur._reussi(cedule_tournees.appliquer(reg, plan, positions, pur.HORODATAGE, "admin.fictif"))
    calendrier_civil.confirmer(reg, plan, {str(i): jour for i, jour in enumerate(dates)}, 0,
                              "admin.fictif", pur.HORODATAGE)
    return reg, ids, plan


def lire(reg, premier="2030-05", **options):
    return apercu.lire(reg, premier, **options)["resultat"]


def jours(vue):
    return {j["jour"]: j for mois in vue["mois"] for j in mois["jours"]}


def test_trois_mois_depuis_snapshot_unique_sans_contact_ni_ecriture():
    reg, ids, _ = monde()

    class LectureUnique(Registre):
        appels = 0

        def lire(self, depuis=None):
            self.appels += 1
            assert self.appels == 1
            return super().lire(depuis)

    avant = reg.lire()
    source = LectureUnique(avant)
    vue = lire(source)
    assert source.appels == 1
    assert [m["mois"] for m in vue["mois"]] == ["2030-05", "2030-06", "2030-07"]
    assert [len(m["jours"]) for m in vue["mois"]] == [31, 30, 31]
    assert [m["total"] for m in vue["mois"]] == [1, 1, 1]
    assert vue["total_interventions"] == len(ids) == 3 and vue["total_sans_date"] == 0
    assert vue["source_nombre"] == reg.taille() and vue["source_tete"] == reg.tete()
    assert vue["fuseau"] == "America/Montreal" and vue["avertissements"]
    par_jour = jours(vue)
    assert par_jour["2030-05-31"]["total"] == par_jour["2030-06-01"]["total"] == 1
    assert par_jour["2030-05-30"]["total"] == 0
    for mois in vue["mois"]:
        assert mois["total"] == mois["date_confirmee"] + mois["a_reconfirmer"]
        assert mois["total"] == sum(j["total"] for j in mois["jours"])
    serialise = json.dumps(vue)
    assert all(iid not in serialise and lead not in serialise for lead, iid in ids.items())
    assert all(mot not in serialise for mot in ["lead_id", "contact", "Client Fictif", "equipe_id", "couleur"])
    assert reg.lire() == avant


@pytest.mark.parametrize("dates,premier,attendus", [
    (("2030-12-31", "2031-01-01", "2031-02-01"), "2030-12", [31, 31, 28]),
    (("2032-01-31", "2032-02-29", "2032-03-01"), "2032-01", [31, 29, 31]),
    (("2000-01-31", "2000-02-29", "2000-03-01"), "2000-01", [31, 29, 31]),
])
def test_annee_et_bissextile(dates, premier, attendus):
    reg, _, _ = monde(dates)
    vue = lire(reg, premier)
    assert [len(m["jours"]) for m in vue["mois"]] == attendus
    assert vue["total_interventions"] == 3
    assert all(jours(vue)[j]["date_confirmee"] == 1 for j in dates)


def test_report_et_redatation_sans_double_compte():
    reg, ids, plan = monde()
    iid = next(iter(ids.values()))
    pur._reussi(etats.transitionner(iid, "reportee", reg, pur.HORODATAGE, motif="meteo"))
    vue = lire(reg)
    assert sum(m["a_reconfirmer"] for m in vue["mois"]) == 1
    assert sum(m["date_confirmee"] for m in vue["mois"]) == 2
    pur._reussi(etats.transitionner(iid, "planifiee", reg, pur.HORODATAGE))
    assert sum(m["a_reconfirmer"] for m in lire(reg)["mois"]) == 1
    calendrier_civil.confirmer(reg, plan, {"0": "2030-08-01", "1": "2030-09-01", "2": "2030-10-01"},
                              1, "admin.fictif", pur.HORODATAGE)
    assert lire(reg)["total_interventions"] == 0
    nouvelle = lire(reg, "2030-08")
    assert nouvelle["total_interventions"] == 3 and sum(m["a_reconfirmer"] for m in nouvelle["mois"]) == 0


def test_sans_date_global_une_fois_et_hors_periode():
    reg, _, _ = monde()
    pur._aide._inscrire(reg, "sans-date-fictif", instant=50)
    avant = reg.lire()
    assert lire(reg)["total_sans_date"] == 1
    vue = lire(reg, "2031-01")
    assert vue["total_interventions"] == 0 and vue["total_sans_date"] == 1
    assert reg.lire() == avant
    sans_plan, ids, _ = pur._monde()
    assert lire(sans_plan)["total_sans_date"] == len(ids)


def test_vide_reel_et_bornes_du_calendrier():
    vide = Registre()
    vue = lire(vide, "1900-01")
    assert vue["source_tete"] is None and vue["source_nombre"] == 0
    assert vue["total_interventions"] == vue["total_sans_date"] == 0
    assert [len(m["jours"]) for m in vue["mois"]] == [31, 28, 31]
    assert jours(lire(vide, "2199-10"))["2199-12-31"]["total"] == 0
    assert apercu.valider_mois("2032-02") == date(2032, 2, 1)
    assert apercu.refuser("ARGUMENTS")["verdict"]["code"] == "REJ-APERCU-MOIS-ARGUMENTS"


@pytest.mark.parametrize("valeur", [None, True, 203001, "", "2030-1", "2030-01-01", "2030-00", "2030-13",
                                  " 2030-01", "2030-01\n", "２０３０-０１", "1899-12", "2199-11", "2200-01"])
def test_mois_strict_avant_lecture(valeur):
    class AucuneLecture:
        def taille(self):
            raise AssertionError("ne doit pas lire")

    with pytest.raises(apercu.Refus, match="ARGUMENTS"):
        apercu.lire(AucuneLecture(), valeur)


def test_limite_sources_avant_chargement_et_limite_sortie_sans_mutation():
    class TropGrand:
        def taille(self):
            return 10001

        def lire(self):
            raise AssertionError("ne doit pas charger")

        def assert_chaine(self):
            raise AssertionError("ne doit pas vérifier")

    with pytest.raises(apercu.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        lire(TropGrand())
    reg, _, _ = monde()
    avant = reg.lire()
    for quota in [10, 0, True]:
        with pytest.raises(apercu.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
            lire(reg, limite_sortie=quota)
    assert reg.lire() == avant


def test_corruption_et_inscription_dupliquee_ne_deviennent_pas_calendrier_vide():
    reg, _, _ = monde()
    corrompu = reg.lire()
    corrompu[-1]["revision"] = 99
    with pytest.raises(apercu.Refus, match="SOURCE-INVALIDE"):
        lire(Registre(corrompu))
    faux = Registre(reg.lire())
    faux.ajouter(next(m for m in reg.lire() if m["type_entree"] == etats.TYPE_INSCRIPTION))
    assert faux.valider_chaine()
    with pytest.raises(apercu.Refus, match="SOURCE-INVALIDE"):
        lire(faux)


@pytest.mark.parametrize("defaut", ["application", "visite_dupliquee", "fuseau", "revision"])
def test_source_forgee_rechainee_refusee(defaut):
    reg, _, _ = monde()
    faux, correspondances = Registre(), {}
    for m in reg.lire():
        ancien_id = m["ligne_id"]
        if defaut == "application" and m["type_entree"] == cedule_tournees.TYPE_APPLIQUEE:
            m["empreinte_sortie"] = "0" * 64
        if defaut == "visite_dupliquee" and m["type_entree"] == cedule_tournees.TYPE_PROPOSEE:
            route = next(r for r in m["sortie"]["plan"] if r["visites"])
            route["visites"].append(deepcopy(route["visites"][0]))
        if m["type_entree"] == calendrier_civil.TYPE_DATEE:
            m["source_application_id"] = correspondances[m["source_application_id"]]
            if defaut == "fuseau":
                m["fuseau"] = "UTC"
            if defaut == "revision":
                m["revision"] = 2
        correspondances[ancien_id] = faux.ajouter(m)
    assert faux.valider_chaine()
    with pytest.raises(apercu.Refus, match="SOURCE-INVALIDE"):
        lire(faux)


@pytest.mark.parametrize("defaut", ["validite", "fin", "doublon", "sans_date_duplique"])
def test_projection_incoherente_refusee(monkeypatch, defaut):
    reg, _, _ = monde()
    pur._aide._inscrire(reg, "sans-date-fictif", instant=50)
    projection = calendrier_civil._projection

    def alterer(index):
        lignes, sans_date = projection(index)
        if defaut == "validite":
            lignes[0]["validite"] = "pret"
        elif defaut == "fin":
            lignes[0]["fin"] = "2030-06-02T00:00:00-04:00"
        elif defaut == "doublon":
            lignes.append(deepcopy(lignes[0]))
        else:
            sans_date.append(deepcopy(sans_date[0]))
        return lignes, sans_date

    monkeypatch.setattr(calendrier_civil, "_projection", alterer)
    with pytest.raises(apercu.Refus, match="SOURCE-INVALIDE"):
        lire(reg)
