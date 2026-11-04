"""P4-04 + P4-05, preuve de bout en bout (vrais outils, base migrée, bus, file N3).

Chaîne, monde Repentigny→Joliette daté au lundi 2030-06-03 :
  1. sans tolérance déclarée : `m4_lire_retards_incidents` rend `retards_cedule` « non évalué »
     et la file du propriétaire porte l'attente `tolerance_retard_a_configurer` (quoi déclarer) ;
  2. tolérance déclarée (30 min) : le même outil mesure le retard daté (en retard, minutes exactes) ;
  3. le retard mesuré alimente `m4_preparer_message_eta_client` (retards_declares_minutes) : brouillon
     PUBLIÉ à M1 (jamais envoyé par M4), consentement actif exigé, aucun nom d'employé ni position ;
  4. `m4_replanifier_intervention` (N3) : une reportée revient `planifiee` puis est reproposée et
     appliquée (même solveur), avec historique des reports et plan de secours en cas de refus.

Données fictives (`fictif: true`).
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from m4_field_ops import outils as outils_m4
from m4_field_ops.outils import outils
from sqlalchemy import select

from opsys import approbations, stockage
from opsys import equipes as equipes_entreprise
from opsys.capacites import outils_executables
from opsys.departements import charger_departements
from opsys.evenements import schemas
from opsys.outils import Niveau
from opsys.stockage.schema import EVENEMENTS_SORTANTS

_spec = importlib.util.spec_from_file_location(
    "fixture_p4_e2e", Path(__file__).with_name("test_equipes_cedule.py")
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
_spec_eta = importlib.util.spec_from_file_location(
    "fixture_p4_e2e_eta", Path(__file__).with_name("test_outils_adequation_eta.py")
)
eta_aide = importlib.util.module_from_spec(_spec_eta)
_spec_eta.loader.exec_module(eta_aide)
adaptateur = eta_aide.adaptateur

FICTIF = True
M4 = "m04-field-ops"
LUNDI = "2030-06-03"
DECIDE_LE = "2030-05-30T14:00:00+00:00"
REFERENCE_TARD = "2030-06-03T18:00:00-04:00"  # après les fins datées, tolérance 30 min
REFERENCE_MESSAGE = "2030-06-02T09:30:00-04:00"  # avant le créneau : la fenêtre n'est pas dépassée
REGLAGES_ETA = dict(eta_aide.REGLAGES_ETA)
ADMIN = aide.ADMIN


def _ecrire_profil(maison, **retirer):
    def _plages(*couples):
        return [{"debut": debut, "fin": fin} for debut, fin in couples]

    def _semaine(*jours):
        jour = _plages(("07:00", "15:00"))
        return {"fuseau": "America/Montreal", **{j: copy.deepcopy(jour) for j in jours},
                "samedi": [], "dimanche": []}

    liste = []
    for equipe in aide._equipes():
        liste.append({**equipe,
                      "membres": [f"{equipe['id'].replace('-', '.')}.fictif",
                                  f"second.{equipe['id'].replace('-', '.')}.fictif"],
                      "semaine_type": _semaine("lundi", "mardi", "mercredi", "jeudi", "vendredi")})
    brut = {
        "liste": liste,
        "feries": {"annees": [2030], "jours": []},
        "services": {t: {"duree_min": d, "competences": list(aide.SCENARIO["competences_par_type_travaux"][t])}
                     for t, d in aide.SCENARIO["durees_par_type_travaux"].items()},
        "cedule": dict(aide.SCENARIO["parametres"]),
    }
    for cle in retirer:
        brut.pop(cle, None)
    (maison / "home" / "entreprise.yaml").write_text(
        yaml.safe_dump({"equipes": equipes_entreprise.normaliser_equipes(brut)}, allow_unicode=True),
        encoding="utf-8")


@pytest.fixture
def monde(par_nom, instance, interventions, futurs_ok, capsys):
    """Profil déclaré, cédule appliquée et datée au lundi 2030-06-03 ; réglages ETA figés."""
    aide._declarer_le_profil(instance / "a", capsys=capsys)
    aide._confirmer_les_positions(par_nom)
    plan = aide._resultat(aide._proposer_depuis_le_profil(par_nom))["plan_id"]
    aide._resultat(aide._appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": plan, "horodatage": aide.HORODATAGE, "confirme_par": "admin.fictif"}))
    aide._resultat(aide._appeler(par_nom, "m4_confirmer_dates_cedule",
                                 {"plan_id": plan, "calendrier": {"0": LUNDI}, "revision_attendue": 0},
                                 aide.ADMIN))
    return interventions


@pytest.fixture(autouse=True)
def _horloge_et_reglages(monkeypatch):
    monkeypatch.setattr(approbations, "_maintenant", lambda: DECIDE_LE)
    monkeypatch.setattr(adaptateur, "_parametres_eta", lambda: dict(REGLAGES_ETA))


@pytest.fixture
def futurs_ok(monkeypatch):
    import m4_field_ops.preparation as preparation_module

    def ok(_registre, _inscription, _lire_position, _lire_equipes, _lire_meteo):
        return {"statut": "ok", "manque": None, "detail": "simulé par le test"}

    monkeypatch.setattr(preparation_module, "_VOLETS", tuple(
        (nom, ok if nom in ("materiel", "meteo") else fonction)
        for nom, fonction in preparation_module._VOLETS))


@pytest.fixture
def instance(tmp_path, monkeypatch):
    aide._monter(tmp_path / "a", monkeypatch)
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def par_nom(instance):
    return {o.nom: o for o in outils()}


@pytest.fixture
def interventions():
    return aide._naitre()


def _appeler(par_nom, nom, arguments, acteur=None):
    return aide._appeler(par_nom, nom, arguments, acteur)


def _releve(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _decider(par_nom, nom, arguments, personne="admin.fictif", approuver=True):
    departements = charger_departements()
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, M4, nom, arguments, niveau=Niveau.N3)
    with stockage.transaction() as cnx:
        outils_exec = outils_executables(departements, lambda: contextlib.nullcontext(cnx))
        return demande, approbations.decider(cnx, demande, approuver, personne, outils_exec, departements)


def _consentir(par_nom, iid):
    return _decider(par_nom, "m4_enregistrer_consentement_suivi_client", {
        "intervention_id": iid, "canal": "sms", "enonce_version": "suivi-fr-CA-v1",
        "preuve": {"fictif": True, "reference": "formulaire-42"},
        "recueilli_le": "2030-05-30T10:00:00-04:00"})


def _evenements(type_evenement="m4.message_client_brouillon_pret"):
    with stockage.transaction() as cnx:
        return cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)).all()


# P4-04 : sans tolérance, non évalué + attente qui dit quoi déclarer
def test_sans_tolerance_le_releve_dit_non_evalue_et_la_file_dit_quoi_declarer(par_nom, monde, monkeypatch):
    monkeypatch.setattr(outils_m4, "_tolerance_retard_cedule", lambda: None)
    releve = _releve(_appeler(par_nom, "m4_lire_retards_incidents",
                              {"horodatage_reference": REFERENCE_TARD}, aide.ADMIN))
    assert releve["retards_cedule"]["statut"] == "non_evalue"
    assert "tolerance_minutes" in releve["retards_cedule"]["manque"]
    assert "aucun retard" not in json.dumps(releve, ensure_ascii=False).lower()
    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, {M4: charger_departements()[M4]})
    [attente] = [a for a in file if a["id"] == "tolerance_retard_a_configurer"]
    assert attente["niveau"] == "N2" and "tolerance" in attente["resume"].lower()
    assert "N3" in attente["action_proposee"]


# P4-04 : tolérance déclarée, retard mesuré, puis brouillon consenti qui reprend le retard
def test_tolerance_declaree_le_retard_est_mesure_et_nourrit_le_brouillon_consenti(par_nom, monde, monkeypatch):
    monkeypatch.setattr(outils_m4, "_tolerance_retard_cedule", lambda: 30)
    releve = _releve(_appeler(par_nom, "m4_lire_retards_incidents",
                              {"horodatage_reference": REFERENCE_TARD}, aide.ADMIN))
    bloc = releve["retards_cedule"]
    assert bloc["statut"] == "evalue" and bloc["tolerance_minutes"] == 30
    assert bloc["en_retard"] >= 1
    mesure = next(r["minutes_retard"] for r in bloc["lignes"] if r["statut_retard"] == "en_retard")
    assert type(mesure) is int and mesure >= 1
    for ligne in bloc["lignes"]:
        assert set(ligne) >= {"intervention_id", "lead_id", "plan_id", "equipe_id", "debut", "fin",
                              "statut", "statut_retard", "minutes_retard", "tolerance_minutes", "confirme_le"}
    assert "marc.fictif" not in json.dumps(bloc, ensure_ascii=False)

    iid = next(iter(monde.values()))
    _consentir(par_nom, iid)
    retards = [min(mesure, 480)]
    brouillon = aide._resultat(_appeler(par_nom, "m4_preparer_message_eta_client", {
        "intervention_id": iid, "canal": "sms", "horodatage_reference": REFERENCE_MESSAGE,
        "retards_declares_minutes": retards, "depart": None}))
    assert brouillon["statut"] == "brouillon" and brouillon["envoi"] == "n3_requis_via_m1"
    assert brouillon["evenement_publie"] is True
    [ligne] = _evenements()
    charge = json.loads(ligne.charge)
    assert schemas.erreurs_charge("m4.message_client_brouillon_pret", charge) == []
    assert charge["texte"] == brouillon["message"] and charge["statut"] == "brouillon"
    for interdit in ("latitude", "microdeg", "Client Fictif", "technicien", "eq-a", "eq-b", "adresse", "10 rue"):
        assert interdit not in ligne.charge, interdit


def test_sans_consentement_le_retard_mesure_ne_fait_pas_de_brouillon(par_nom, monde, monkeypatch):
    monkeypatch.setattr(outils_m4, "_tolerance_retard_cedule", lambda: 30)
    releve = _releve(_appeler(par_nom, "m4_lire_retards_incidents",
                              {"horodatage_reference": REFERENCE_TARD}, aide.ADMIN))
    assert releve["retards_cedule"]["en_retard"] >= 1
    iid = next(iter(monde.values()))
    reponse = _appeler(par_nom, "m4_preparer_message_eta_client", {
        "intervention_id": iid, "canal": "sms", "horodatage_reference": REFERENCE_MESSAGE,
        "retards_declares_minutes": [30], "depart": None})
    assert aide._code_refus(reponse) == "REJ-ETA-CONSENTEMENT-ABSENT"
    assert _evenements() == []


# P4-05 : replanification N3 d'une reportée, via la file, avec historique
def test_replanifier_une_reportee_la_remet_en_planifiee_reproposee_et_appliquee(
        par_nom, monde, monkeypatch):
    import m4_field_ops.preparation as preparation_module

    outil = par_nom["m4_replanifier_intervention"]
    assert outil.niveau_effectif is Niveau.N3 and outil.roles_appareil == frozenset({"admin"})
    iid = next(iter(monde.values()))
    aide._resultat(_appeler(par_nom, "m4_signaler_report", {
        "intervention_id": iid, "motif": "meteo", "horodatage": "2030-06-01T08:00:00-04:00"}, aide.ADMIN))
    prete = {"pret": True, "a_fournir": [], "statut": "pret"}
    monkeypatch.setattr(preparation_module, "evaluer", lambda *a, **k: (dict(prete), None))
    _, decision = _decider(par_nom, "m4_replanifier_intervention", {
        "intervention_id": iid, "horodatage": "2030-06-01T09:00:00-04:00",
        "confirme_par": "admin.fictif"})
    assert decision["statut"] == "executee", decision
    with stockage.transaction():
        from m4_field_ops import etats
        from m4_field_ops import registre as registre_m4
        assert etats.statut_courant(registre_m4.Registre(stockage.maillons(M4, "principal")), iid) == "planifiee"
    resultat = decision["reponse"]["resultat"]["resultat"]
    assert resultat["intervention_id"] == iid
    assert resultat["historique_reports"] and resultat["historique_reports"][0]["motif"] == "meteo"
    assert resultat["proposition"] and resultat["application"]
    assert "secours" not in decision["reponse"]["resultat"]
