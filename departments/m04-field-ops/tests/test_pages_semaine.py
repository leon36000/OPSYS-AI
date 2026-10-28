"""Pagination sur vrais registres et plans DP, données exclusivement fictives."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import calendrier_civil, cedule_tournees, etats
from m4_field_ops import pages_semaine as pages
from m4_field_ops.registre import Registre

_spec = importlib.util.spec_from_file_location(
    "fixture_pages_semaine", Path(__file__).with_name("test_calendrier_civil.py"))
pur = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pur)
FICTIF = True
SEMAINE = "2030-06-03"


def _registre_grand_carnet(nb_dates=206, nb_sans_date=61):
    """Vraies inscriptions/plans/applications/dates; chaque lot utilise ses propres équipes."""
    reg = Registre()
    aide = pur._aide
    for debut in range(0, nb_dates, 6):
        leads = [f"pagination-fictive-{i:04d}" for i in range(debut, min(debut + 6, nb_dates))]
        ids = {lead: aide._inscrire(reg, lead) for lead in leads}
        positions = aide.Positions({lead: aide.SITES["ch-01"] for lead in leads})
        equipes = aide._equipes()
        for equipe in equipes:
            equipe["id"] = f"lot-fictif-{debut:04d}-{equipe['id']}"
        args = aide._arguments(ids, equipes=equipes, intervention_ids=list(ids.values()),
                               durees_par_type_travaux={"extension": 60, "ravalement": 60})
        plan = pur._reussi(pur._proposer(reg, ids, positions, args))["plan_id"]
        pur._reussi(cedule_tournees.appliquer(reg, plan, positions, pur.HORODATAGE, "admin.fictif"))
        calendrier_civil.confirmer(reg, plan, {"0": SEMAINE}, 0, "admin.fictif", pur.HORODATAGE)
    for i in range(nb_sans_date):
        aide._inscrire(reg, f"sans-date-pagination-fictive-{i:04d}")
    return reg


@pytest.fixture(scope="module")
def grand_carnet():
    return _registre_grand_carnet()


def lire(reg, **options):
    return pages.lire(reg, SEMAINE, **options)["resultat"]


def test_parcours_complet_deux_listes_independantes_sans_duplication(grand_carnet):
    reg = grand_carnet
    avant = reg.lire()
    premiere = lire(reg)
    tete = premiere["source_tete"]
    assert premiere["total_interventions"] == 206 and premiere["total_sans_date"] == 61
    assert premiere["taille_page"] == 25 and premiere["source_nombre"] == reg.taille()
    assert len(premiere["interventions"]) == len(premiere["sans_date"]) == 25
    dates, non_datees = [], []
    for offset in range(0, 206, 25):
        vue = lire(reg, offset_interventions=offset, source_attendue=tete)
        assert vue["source_tete"] == tete and vue["offset_interventions"] == offset
        assert vue["offset_sans_date"] == 0 and vue["sans_date"] == premiere["sans_date"]
        assert vue["tronque"] is True
        dates.extend(vue["interventions"])
    for offset in range(0, 61, 25):
        vue = lire(reg, offset_sans_date=offset, source_attendue=tete)
        assert vue["offset_interventions"] == 0 and vue["interventions"] == premiere["interventions"]
        non_datees.extend(vue["sans_date"])
    assert len({i["intervention_id"] for i in dates}) == len(dates) == 206
    assert len({i["intervention_id"] for i in non_datees}) == len(non_datees) == 61
    assert dates == sorted(dates, key=lambda i: (i["debut"], i["equipe_id"], i["intervention_id"]))
    assert non_datees == sorted(non_datees, key=lambda i: i["intervention_id"])
    dernieres = lire(reg, offset_interventions=200, offset_sans_date=50, source_attendue=tete)
    assert len(dernieres["interventions"]) == 6 and len(dernieres["sans_date"]) == 11
    assert reg.lire() == avant


def test_mutation_refuse_source_ancienne_avant_hors_fin():
    reg, _, plan = pur.monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": SEMAINE}, 0, "admin.fictif", pur.HORODATAGE)
    tete = reg.tete()
    pur._aide._inscrire(reg, "nouvelle-source-fictive")
    avant = reg.lire()
    for options in [{"offset_interventions": 25}, {"offset_sans_date": 25},
                    {"offset_interventions": 10000}, {}]:
        with pytest.raises(pages.Refus, match="SOURCE-MODIFIEE"):
            lire(reg, source_attendue=tete, **options)
    assert reg.lire() == avant
    assert lire(reg)["source_tete"] == reg.tete()


def test_petites_listes_vides_et_compatibilite_legacy():
    vide = lire(Registre())
    assert vide["source_tete"] is None and vide["source_nombre"] == 0
    assert vide["interventions"] == vide["sans_date"] == [] and vide["tronque"] is False
    reg, _, plan = pur.monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": SEMAINE}, 0, "admin.fictif", pur.HORODATAGE)
    vue = lire(reg)
    legacy = calendrier_civil.lire_semaine(reg, SEMAINE)
    assert {k: vue[k] for k in legacy} == legacy
    assert pages.refuser("SOURCE-MODIFIEE")["verdict"]["code"] == "REJ-PAGE-CEDULE-SOURCE-MODIFIEE"
    with pytest.raises(pages.Refus, match="ARGUMENTS"):
        lire(reg, offset_interventions=25, source_attendue=reg.tete())
    with pytest.raises(pages.Refus, match="ARGUMENTS"):
        lire(reg, offset_sans_date=25, source_attendue=reg.tete())
    with pytest.raises(pages.Refus, match="SOURCE-MODIFIEE"):
        lire(Registre(), offset_interventions=25, source_attendue="0" * 64)


@pytest.mark.parametrize("offset", [True, -25, 1, 24, 26, 10025, "25", 25.0, None])
def test_offsets_stricts_avant_lecture(offset):
    class NePasLire:
        def taille(self):
            raise AssertionError("entrée invalide avant source")

    for champ in ["offset_interventions", "offset_sans_date"]:
        with pytest.raises(pages.Refus, match="ARGUMENTS"):
            lire(NePasLire(), **{champ: offset}, source_attendue="0" * 64)


@pytest.mark.parametrize("source", ["", "X" * 64, "0" * 63, True, 4, {}, "0" * 64 + "\n"])
def test_tete_stricte(source):
    with pytest.raises(pages.Refus, match="ARGUMENTS"):
        lire(Registre(), source_attendue=source)


def test_continuation_sans_tete_refusee():
    for options in [{"offset_interventions": 25}, {"offset_sans_date": 25}]:
        with pytest.raises(pages.Refus, match="ARGUMENTS"):
            lire(Registre(), **options)


@pytest.mark.parametrize("semaine", [None, True, "2030-6-3", "2030-06-04", "1899-12-25", "2199-12-30"])
def test_lundi_et_bornes_stricts(semaine):
    with pytest.raises(pages.Refus, match="ARGUMENTS"):
        pages.lire(Registre(), semaine)


def test_une_lecture_principal_et_quota_sans_mutation():
    reg, _, plan = pur.monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": SEMAINE}, 0, "admin.fictif", pur.HORODATAGE)

    class LectureUnique(Registre):
        appels = 0

        def lire(self, depuis=None):
            self.appels += 1
            assert self.appels == 1
            return super().lire(depuis)

    avant = reg.lire()
    source = LectureUnique(avant)
    assert lire(source)["source_tete"] == reg.tete() and source.appels == 1
    for quota in [0, True, 10]:
        with pytest.raises(pages.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
            lire(reg, limite_sortie=quota)
    assert reg.lire() == avant


def test_plafond_avant_chargement_corruption_et_sources_forgees():
    class TropGrand:
        def taille(self):
            return 10001

        def lire(self):
            raise AssertionError("ne pas charger")

    with pytest.raises(pages.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        lire(TropGrand())
    reg, _, plan = pur.monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": SEMAINE}, 0, "admin.fictif", pur.HORODATAGE)
    brise = reg.lire()
    brise[-1]["revision"] = 99
    with pytest.raises(pages.Refus, match="SOURCE-INVALIDE"):
        lire(Registre(brise))
    faux, correspondances = Registre(), {}
    for m in reg.lire():
        ancien = m["ligne_id"]
        if m["type_entree"] == cedule_tournees.TYPE_APPLIQUEE:
            m["empreinte_sortie"] = "0" * 64
        if m["type_entree"] == calendrier_civil.TYPE_DATEE:
            m["source_application_id"] = correspondances[m["source_application_id"]]
        correspondances[ancien] = faux.ajouter(m)
    assert faux.valider_chaine()
    with pytest.raises(pages.Refus, match="SOURCE-INVALIDE"):
        lire(faux)


def test_report_reste_orange_et_autre_semaine_ne_duplique_pas_sans_date():
    reg, ids, plan = pur.monde_date()
    calendrier_civil.confirmer(reg, plan, {"0": SEMAINE}, 0, "admin.fictif", pur.HORODATAGE)
    pur._aide._inscrire(reg, "sans-date-fictive")
    pur._reussi(etats.transitionner(next(iter(ids.values())), "reportee", reg, pur.HORODATAGE, motif="meteo"))
    premiere = lire(reg)
    autre = pages.lire(reg, "2030-06-10")["resultat"]
    assert sum(i["validite"] == "a_reconfirmer" for i in premiere["interventions"]) == 1
    assert autre["interventions"] == [] and autre["total_sans_date"] == premiere["total_sans_date"] == 1


def test_index_civil_reutilise_un_instantane_sans_recopier_par_intervention():
    reg, _, _ = pur.monde_date()

    class LectureComptee(Registre):
        lectures = 0

        def lire(self, depuis=None):
            self.lectures += 1
            return super().lire(depuis)

    copie = LectureComptee(reg.lire())
    index = calendrier_civil._index(copie)
    assert copie.lectures == 1, copie.lectures
    assert list(index[5].values()) == etats.lister_interventions(reg)
