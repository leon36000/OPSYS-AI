"""CRM-01 : registre SQLite M4 réel, références M2 et grille HTML via TestClient. Tout est fictif."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops.outils import outils

from opsys import identite


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _charger("fixture_crm_cedule", Path(__file__).with_name("test_console_crm.py"))
terrain = _charger("fixture_terrain_cedule", Path(__file__).parents[1] /
                   "departments/m04-field-ops/tests/test_cedule_tournees_outils.py")
client_crm = base.client_crm
FICTIF = True
SEMAINE = "/crm/cedule?debut_semaine=2030-06-03"


@pytest.fixture
def planning(client_crm):
    par_nom = {o.nom: o for o in outils()}
    ids = {}
    for rang, lead_id in enumerate(["lead-fictif-001", "lead-fictif-002", "orphelin-fictif"]):
        lead = {**terrain.SCENARIO["leads"][rang], "lead_id": lead_id}
        ids[lead_id] = terrain._inscrire(par_nom, lead, f"2030-01-01T00:00:0{rang}+00:00")
        terrain._resultat(terrain._confirmer(par_nom, lead))
    plan = terrain._resultat(terrain._proposer(par_nom, ids))["plan_id"]
    terrain._resultat(terrain._appliquer(par_nom, plan))
    confirmation = terrain._resultat(terrain._appeler(par_nom, "m4_confirmer_dates_cedule", {
        "plan_id": plan, "calendrier": {"0": "2030-06-03"}, "revision_attendue": 0}, terrain.ADMIN))
    sans_date = terrain._inscrire(par_nom, {**terrain.SCENARIO["leads"][0], "lead_id": "sans-date-fictif"})
    return par_nom, ids, confirmation, sans_date


def test_vraie_cedule_m4_affichee_avec_liens_m2_et_sans_ecriture(client_crm, planning, session):
    _, ids, confirmation, sans_date = planning
    base._connecter(client_crm, "admin.fictif")
    avant = base._instantane_base(session)
    page = client_crm.get(SEMAINE)
    assert page.status_code == 200, page.text
    assert "America/Montreal" in page.text and "Équipes × jours" in page.text
    assert 'data-jour="2030-06-03"' in page.text and 'data-jour="2030-06-09"' in page.text
    for iid in ids.values():
        assert f'data-intervention="{iid}"' in page.text
    assert confirmation["ligne_id"] in page.text and "Révision 1" in page.text
    assert f'href="{base.PREFIXE}/crm/lead/lead-fictif-001"' in page.text
    assert f'href="{base.PREFIXE}/crm/lead/orphelin-fictif"' not in page.text
    assert "Dossier M2 non relié" in page.text
    assert sans_date in page.text and "Sans date — tout le carnet" in page.text
    assert "aucune disponibilité" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert base._instantane_base(session) == avant


def test_acces_admin_et_revocation(client_crm, session):
    assert client_crm.get(SEMAINE, follow_redirects=False).status_code == 303
    for personne in ["employe", "nathan"]:
        base._connecter(client_crm, personne)
        assert client_crm.get(SEMAINE).status_code == 403
    base._connecter(client_crm, "admin.fictif")
    with session() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    assert client_crm.get(SEMAINE).status_code in {303, 403}


@pytest.mark.parametrize("requete", ["2030-06-04", "2030-02-30", "9999-12-31", "20300603", "x" * 5000])
def test_date_invalide_necrit_pas(client_crm, session, requete):
    base._connecter(client_crm, "admin.fictif")
    avant = base._instantane_base(session)
    assert client_crm.get("/crm/cedule", params={"debut_semaine": requete}).status_code == 400
    assert base._instantane_base(session) == avant


def test_navigation_semaines_vide_et_aucune_mutation(client_crm, planning, session):
    base._connecter(client_crm, "admin.fictif")
    avant = base._instantane_base(session)
    page = client_crm.get(SEMAINE)
    assert f'href="{base.PREFIXE}/crm/cedule?debut_semaine=2030-05-27"' in page.text
    assert f'href="{base.PREFIXE}/crm/cedule?debut_semaine=2030-06-10"' in page.text
    suivante = client_crm.get("/crm/cedule?debut_semaine=2030-06-10")
    assert suivante.status_code == 200 and "Aucun créneau daté dans cette semaine" in suivante.text
    assert 'data-intervention=' not in suivante.text
    assert "aucune disponibilité" in suivante.text and "Sans date — tout le carnet" in suivante.text
    assert client_crm.get("/crm/cedule").status_code == 200
    assert client_crm.get("/crm/cedule?autre=x").status_code == 400
    assert client_crm.get(SEMAINE + "&debut_semaine=2030-06-10").status_code == 400
    assert f'href="{base.PREFIXE}/crm/cedule"' in client_crm.get("/crm").text
    csrf = client_crm.get("/api/session").json()["csrf"]
    assert client_crm.post("/crm/cedule", headers={"x-csrf-token": csrf}).status_code == 405
    assert base._instantane_base(session) == avant


def test_report_et_retour_planifie_restent_visuellement_a_reconfirmer(client_crm, planning, session):
    from m4_field_ops import etats

    _, ids, _, _ = planning
    iid = ids["lead-fictif-001"]
    with session():
        reg = terrain._registre()
        assert etats.transitionner(iid, "reportee", reg, terrain.RECU_LE.isoformat(), motif="meteo")[1] is None
        assert etats.transitionner(iid, "planifiee", reg, terrain.RECU_LE.isoformat())[1] is None
    base._connecter(client_crm, "admin.fictif")
    page = client_crm.get(SEMAINE)
    assert page.status_code == 200
    assert f'class="cedule-job cedule-perimee" data-intervention="{iid}"' in page.text
    assert "À reconfirmer — ancien créneau" in page.text


def test_admin_avec_role_owner_cumule_reste_admin_pour_m4(client_crm, session):
    with session() as cnx:
        identite.ajouter_role(cnx, "admin.fictif", "nathan_owner")
    base._connecter(client_crm, "admin.fictif")
    assert client_crm.get(SEMAINE).status_code == 200


def _vue_source(planning):
    par_nom, _, _, _ = planning
    return terrain._resultat(terrain._appeler(par_nom, "m4_lire_cedule_semaine",
                                             {"debut_semaine": "2030-06-03"}, terrain.ADMIN))


def test_rendu_echappe_donnees_et_explicitement_tronque(planning):
    from opsys.console import cedule_ui

    vue = _vue_source(planning)
    vue["interventions"][0]["equipe_id"] = '<script>alert("FICTIF")</script>'
    vue["interventions"][0]["plan_id"] = '<img src=x onerror=alert(1)>'
    vue["avertissements"] = ['<svg onload=alert(1)>']
    vue["total_interventions"] = 250
    vue["total_sans_date"] = 75
    vue["tronque"] = True
    html = cedule_ui.contenu(vue, set(), base.PREFIXE)
    assert '<script>' not in html and '<img' not in html and '<svg' not in html
    assert '&lt;script&gt;' in html and '&lt;img' in html and '&lt;svg' in html
    assert 'Vue incomplète' in html and 'sur 250' in html and 'sur 75' in html


def test_source_corrompue_ne_devient_pas_semaine_vide(client_crm, planning, monkeypatch):
    from opsys.console import metier

    vue = _vue_source(planning)
    vue["interventions"][0]["debut"] = "2030-06-03T09:00:00"  # sans fuseau : source invalide
    original = metier.executer

    def faux_lecteur(cnx, deps, session, nom, arguments, **kwargs):
        if nom == "m4_lire_cedule_semaine":
            return {"ok": True, "resultat": {"accepte": True, "resultat": vue}}
        return original(cnx, deps, session, nom, arguments, **kwargs)

    monkeypatch.setattr(metier, "executer", faux_lecteur)
    base._connecter(client_crm, "admin.fictif")
    page = client_crm.get(SEMAINE)
    assert page.status_code == 503
    assert "Aucun créneau" not in page.text
