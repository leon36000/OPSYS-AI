"""P4-01 et P4-02 : la durée d'un chantier vient de l'estimation M3 (correction apprise comprise), et un chantier de
plusieurs jours se découpe en visites de la même équipe, par les VRAIS outils de M4, le VRAI bus et le VRAI profil
(`entreprise.yaml` déclaré par `opsys-metier equipes declarer`), sur une base SQLite migrée.

Tout est fictif (`fictif: true`). Les volets matériel et météo de la préparation sont simulés (`futurs_ok`) : leurs
preuves
sont ailleurs ; ce fichier prouve la durée, le découpage, la continuité d'équipe et la sortie de `a_planifier`. Le
moteur
est le repli EXACT (PyVRP n'est pas installé ici et ne résout pas ces chantiers). La preuve de bout en bout avec le
vrai M3 (estimation apprise, devis, M4) est `tests/test_m4_duree_multijours_bout_en_bout.py`.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from m4_field_ops import (
    annotations_calendrier,
    apercu_mois,
    duree_chantier,
    etats,
    journal_quotidien,
    pages_semaine,
    preparation,
    reserves_completion,
)
from m4_field_ops import registre as registre_m4

from opsys import cli, contexte, evenements, identite, stockage, taxonomie
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True
_FIXTURES = Path(__file__).parent / "fixtures"
SCENARIO = json.loads((_FIXTURES / "scenario_cedule_repentigny_joliette.json").read_text(encoding="utf-8"))
EQUIPES = json.loads((_FIXTURES / "equipes_repentigny_joliette.json").read_text(encoding="utf-8"))
M4 = "m04-field-ops"
HORODATAGE = "2030-01-01T00:00:00+00:00"
ACCEPTE_LE = "2030-01-01T10:00:00-05:00"
RECU_LE = dt.datetime(2030, 6, 2, 9, 0, 0, tzinfo=dt.UTC)
HORLOGE_APPAREIL = dt.datetime(2000, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
DEBUT_BUS = dt.datetime(2030, 1, 2, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
LEADS = {lead["lead_id"]: lead for lead in SCENARIO["leads"]}
TOIT, PETIT_1, PETIT_2 = "L-E2E-12", "L-E2E-01", "L-E2E-02"   # renovation_totale, ravalement, autre
VERSION_APPRISE = "a1" * 32
PERSONNES = (
    ("admin.fictif", ["admin"]), ("marie.fictif", ["admin"]), ("luc.fictif", ["employee"]),
    ("marc.fictif", ["employee"]), ("nadia.fictif", ["employee"]), ("vendeur.fictif", ["seller"]),
)


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def instance(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    taxonomie.enregistrer_services(EQUIPES["services_propres"])
    with stockage.transaction() as cnx:
        for identifiant, roles in PERSONNES:
            identite.creer_personne(cnx, identifiant, identifiant.title(), "mot-de-passe-fictif-1234", roles)
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def par_nom(instance):
    from m4_field_ops.outils import outils

    return {o.nom: o for o in outils()}


@pytest.fixture
def futurs_ok(monkeypatch):
    def ok(_registre, _inscription, _lire_position, _lire_equipes, _lire_meteo):
        return {"statut": "ok", "manque": None, "detail": "simulé par le test"}

    monkeypatch.setattr(preparation, "_VOLETS", tuple(
        (nom, ok if nom in ("materiel", "meteo") else fonction) for nom, fonction in preparation._VOLETS))


def _profil(jours_a=(0, 1, 2, 3), jours_b=(0, 1, 2, 3), multijours=None, services=None):
    """Le profil de la démonstration Repentigny-Joliette, avec des quarts sur plusieurs jours et des règles
    pluri-jours."""
    profil = copy.deepcopy(EQUIPES["profil"])
    for equipe, jours in zip(profil["liste"], (jours_a, jours_b), strict=True):
        equipe["quarts"] = [{"jour": jour, "debut_min": 480, "fin_min": 1020} for jour in jours]
    profil["fenetre_par_defaut"] = {"jours": [0, 1, 2, 3], "debut_min": 480, "fin_min": 1020}
    if multijours is not False:
        profil["cedule"]["multijours"] = multijours or {"visite_max_minutes": 480, "jours_consecutifs": False}
    if services is not None:
        profil["services"] = services
    return profil


def _declarer(dossier, profil, capsys):
    fichier = dossier / "equipes.yaml"
    fichier.write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    assert cli.main(["equipes", "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0
    capsys.readouterr()


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
            pile.enter_context(contexte.receptionne_de(contexte.HorodatageAppareil(
                appareil="tel-fictif-p4-02", horodatage_appareil=HORLOGE_APPAREIL, recu_le=RECU_LE)))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=ADMIN):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _registre():
    return registre_m4.Registre(stockage.maillons(M4, "principal"))


def _maillons():
    with stockage.transaction():
        return _registre().lire()


def _du_type(type_entree):
    return [m for m in _maillons() if m["type_entree"] == type_entree]


def _statut(intervention_id):
    with stockage.transaction():
        return etats.statut_courant(_registre(), intervention_id)


def _technicien(intervention_id):
    with stockage.transaction():
        return etats.technicien_assigne(_registre(), intervention_id)


# -- le bus : des devis acceptés qui portent (ou non) la durée de M3 ---------------------------------------
def _publier_lead(lead_id):
    lead = LEADS[lead_id]
    evenements.publier(
        "m1.lead_qualifie", "m01-front-office",
        {"lead": {
            "schema_version": 2, "lead_id": lead_id, "conversation_id": f"sms-{lead_id}",
            "contact": {"nom": "Client Fictif", "telephone": "+15145550142"}, "service": lead["type_travaux"],
            "ville": lead["secteur"], "urgence_declaree": lead["urgence_declaree"], "canal": "texte", "source": "sms"},
         "horodatage": HORODATAGE, "signal_id": f"sms:{lead_id}"},
        evenement_id=f"m1-lead-qualifie-{lead_id}")


def _publier_devis(lead_id, duree=None, semantique="duree_ecoulee_intervention", origine=None, evenement_id=None):
    devis_id = f"DEVIS-{lead_id}"
    charge = {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{"reference_ligne": f"{devis_id}-L0", "description": "Travaux (fictif)", "quantite": "1",
                    "unite": "forfait", "prix_unitaire": "100.00", "prix_ligne": "100.00",
                    "reference_besoin_materiau": None}],
        "cout_total": "80.00", "prix_total": "100.00", "taux_marge": "0.25", "horodatage_acceptation": ACCEPTE_LE,
    }
    if duree is not None:
        charge["duree_estimee_minutes"] = duree
    if semantique is not None and duree is not None:
        charge["semantique_temps"] = semantique
    if origine is not None:
        charge["duree_origine"] = origine
    evenements.publier("m3.devis_accepte", "m03-estimation", charge,
                       evenement_id=evenement_id or f"m3-devis-accepte-{devis_id}")


def _repartir(tours=3):
    deps = {M4: charger_departements()[M4]}
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(tours):
        resume = evenements.repartir(deps, maintenant=(DEBUT_BUS + dt.timedelta(seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    return total


def _naitre(durees):
    """``durees`` : ``{lead_id: dict d'arguments de _publier_devis}`` ; rend ``{lead_id: intervention_id}``."""
    for lead_id, arguments in durees.items():
        _publier_lead(lead_id)
        _publier_devis(lead_id, **arguments)
    total = _repartir()
    assert total["echecs"] == 0 and total["quarantaines"] == 0, total
    with stockage.transaction():
        liste = etats.lister_interventions(_registre(), statut="a_planifier")
    return {ligne["lead_id"]: ligne["intervention_id"] for ligne in liste}


def _confirmer_positions(par_nom, lead_ids):
    for lead_id in lead_ids:
        lead = LEADS[lead_id]
        _ok(_appeler(par_nom, "m4_confirmer_localisation", {
            "chantier_id": lead_id, "action": "confirmee", "horodatage": HORODATAGE, "confirme_par": "admin.fictif",
            "adresse": {"numero_municipal": "10", "odonyme": "rue Fictive", "municipalite": lead["secteur"]},
            "source": "manuel", "motif": "", "latitude_microdegres": lead["latitude_microdegres"],
            "longitude_microdegres": lead["longitude_microdegres"]}))


def _proposer(par_nom, **arguments):
    return _appeler(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE, **arguments})


def _appliquer(par_nom, plan_id):
    return _appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": plan_id, "horodatage": HORODATAGE, "confirme_par": "admin.fictif"})


def _visites_de(plan, intervention_id):
    return sorted(
        ((r["equipe"], r["jour"], v["debut_min"], v["fin_min"], v.get("visite")) for r in plan for v in r["visites"]
         if v["chantier"] == intervention_id),
        key=lambda t: t[1])


DEVIS_16H = {"duree": "960", "origine": {
    "origine": "calibration", "calibration_version_id": VERSION_APPRISE,
    "taux_minutes_par_unite_source": "30", "taux_minutes_par_unite": "34.2857"}}


# =========================================================================================
# 1. L'inscription retient ce que le devis dit de la durée (P4-01)
# =========================================================================================
def test_l_inscription_retient_la_duree_de_m3_et_sa_correction_apprise(instance, par_nom):
    iids = _naitre({TOIT: DEVIS_16H})
    inscription = next(m for m in _du_type("intervention_inscrite") if m["intervention_id"] == iids[TOIT])
    assert inscription["duree_m3"] == {
        "statut": "retenue", "minutes": "960", "semantique": "duree_ecoulee_intervention", "origine": "calibration",
        "calibration_version_id": VERSION_APPRISE}


@pytest.mark.parametrize("arguments, statut, morceau", [
    ({}, "absente", "ne porte aucune durée"),
    ({"duree": "960", "semantique": None}, "ecartee", "semantique_temps"),
])
def test_une_duree_absente_ou_sans_semantique_n_est_jamais_retenue(instance, par_nom, arguments, statut, morceau):
    iids = _naitre({TOIT: arguments})
    inscription = next(m for m in _du_type("intervention_inscrite") if m["intervention_id"] == iids[TOIT])
    assert inscription["duree_m3"]["statut"] == statut and morceau in inscription["duree_m3"]["motif"]
    assert "minutes" not in inscription["duree_m3"]


def test_le_catalogue_refuse_une_semantique_de_temps_inconnue_a_la_publication(instance):
    from opsys.evenements.bus import ChargeInvalide

    with pytest.raises(ChargeInvalide):
        _publier_lead(TOIT)
        _publier_devis(TOIT, duree="960", semantique="heures_personnes")


@pytest.mark.parametrize("texte", ["0", "-5", "abc", "", " 960", "1e3", "NaN", "14401"])
def test_une_duree_illisible_ou_hors_bornes_est_ecartee(texte):
    bloc = duree_chantier.retenir_estimation(
        {"duree_estimee_minutes": texte, "semantique_temps": "duree_ecoulee_intervention"})
    assert bloc["statut"] == "ecartee"


def test_la_duree_de_m3_est_arrondie_vers_le_haut_jamais_vers_le_bas():
    assert duree_chantier.minutes_entieres("840") == 840
    assert duree_chantier.minutes_entieres("840.0001") == 841
    assert duree_chantier.minutes_entieres("840.9") == 841
    assert duree_chantier.minutes_entieres("0.2") == 1
    assert duree_chantier.minutes_entieres("0") is None and duree_chantier.minutes_entieres("14401") is None


def test_une_redelivrance_du_devis_ne_change_pas_la_duree_retenue(instance, par_nom):
    iids = _naitre({TOIT: {"duree": "960"}})
    _publier_devis(TOIT, duree="100", evenement_id="m3-devis-accepte-redelivre")   # même devis, autre durée, autre id
    assert _repartir()["echecs"] == 0
    inscriptions = [m for m in _du_type("intervention_inscrite") if m["intervention_id"] == iids[TOIT]]
    assert len(inscriptions) == 1 and inscriptions[0]["duree_m3"]["minutes"] == "960"


# =========================================================================================
# 2. La cédule : durée de M3, repli dit, durée à déclarer (P4-01)
# =========================================================================================
def test_la_cedule_utilise_la_duree_de_m3_et_dit_d_ou_elle_vient(instance, par_nom, futurs_ok, capsys):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({TOIT: DEVIS_16H, PETIT_1: {"duree": "100.2"}})
    _confirmer_positions(par_nom, (TOIT, PETIT_1))
    proposition = _ok(_proposer(par_nom))
    toit = proposition["durees"][iids[TOIT]]
    assert toit["minutes"] == 960 and toit["source"] == "estimation_m3" and toit["repli"] is False
    assert toit["origine_m3"] == "calibration" and toit["calibration_version_id"] == VERSION_APPRISE
    assert "corrigée par une version apprise" in toit["libelle"]
    assert toit["ecart_profil_min"] == 960 - 180            # le service du profil dit 180 min
    petit = proposition["durees"][iids[PETIT_1]]
    assert petit["minutes"] == 101 and petit["source"] == "estimation_m3"      # 100,2 -> 101 (vers le haut)
    assert petit["visites"] is None and petit["ecart_profil_min"] == 101 - 120
    assert proposition["provenance"]["multijours"] == "profil"
    entree = _du_type("cedule_proposee")[0]["entree"]["chantiers"]
    assert {c["id"]: c["duree_min"] for c in entree} == {iids[TOIT]: 960, iids[PETIT_1]: 101}


def test_sans_estimation_la_duree_du_service_sert_de_repli_et_le_repli_est_dit(instance, par_nom, futurs_ok, capsys):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({PETIT_1: {}, PETIT_2: {"duree": "60", "semantique": None}})
    _confirmer_positions(par_nom, (PETIT_1, PETIT_2))
    proposition = _ok(_proposer(par_nom))
    sans = proposition["durees"][iids[PETIT_1]]
    assert sans["minutes"] == 120 and sans["source"] == "profil_service" and sans["repli"] is True
    assert "ne porte aucune durée" in sans["raison_repli"] and "REPLI" in sans["libelle"]
    ecartee = proposition["durees"][iids[PETIT_2]]
    assert ecartee["minutes"] == 90 and ecartee["repli"] is True and "semantique_temps" in ecartee["raison_repli"]
    assert ecartee["origine_m3"] is None and ecartee["ecart_profil_min"] is None


def test_aucune_duree_nulle_part_est_un_refus_lisible_jamais_une_duree_inventee(instance, par_nom, capsys):
    """Une intervention déjà `planifiee` (sans préparation) pour un service que ni le profil ni l'estimation ne
    chiffrent : la cédule refuse et dit quoi déclarer."""
    _declarer(instance, _profil(services={"ravalement": {"duree_min": 120, "competences": ["revetement"]}}), capsys)
    lead = LEADS[PETIT_2]            # service « autre » : pas au profil
    reponse = _appeler(par_nom, "m4_planifier_intervention", {
        "contrat": {"schema_version": 2, "lead_id": PETIT_2, "conversation_id": "C-1", "service": lead["type_travaux"],
                    "ville": lead["secteur"], "canal": "telephone", "contact": {"nom": "Client Fictif"},
                    "urgence_declaree": False},
        "marqueur": {"readiness_ok": True, "lead_id": PETIT_2, "hash_tete_registre": None, "horodatage": HORODATAGE,
                     "empreinte": "ab" * 32},
        "horodatage": HORODATAGE, "sel": "sel-fictif", "techniciens_disponibles": ["eq-a"],
        "fenetres_disponibles": [{"debut": "2030-01-07T08:00:00-05:00", "fin": "2030-01-07T17:00:00-05:00"}]})
    iid = reponse["resultat"]["intervention_id"]
    _confirmer_positions(par_nom, (PETIT_2,))
    refus = _refus(_proposer(par_nom, intervention_ids=[iid]))
    assert refus["code"] == "REJ-CHAMP-MANQUANT"
    assert "durée à déclarer" in refus["detail"] and iid in refus["detail"]
    assert "jamais une durée par défaut" in refus["detail"]
    assert _du_type("cedule_proposee") == []


def test_un_devis_sans_duree_pour_un_service_non_declare_ne_devient_pas_pret(instance, par_nom, futurs_ok, capsys):
    """Préparation : le volet équipe dit ce qui manque (la durée du service n'est déclarée nulle part)."""
    _declarer(instance, _profil(services={"ravalement": {"duree_min": 120, "competences": ["revetement"]}}), capsys)
    iids = _naitre({PETIT_2: {}})
    _confirmer_positions(par_nom, (PETIT_2,))
    verdict = _ok(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iids[PETIT_2]}))
    assert verdict["pret"] is False
    assert "non déclarées" in verdict["volets"]["equipe"]["manque"]


def test_l_argument_durees_par_service_remplace_le_profil_et_le_dit(instance, par_nom, futurs_ok, capsys):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({PETIT_1: {}})
    _confirmer_positions(par_nom, (PETIT_1,))
    proposition = _ok(_proposer(par_nom, durees_par_service={"ravalement": 75}))
    bloc = proposition["durees"][iids[PETIT_1]]
    assert bloc["minutes"] == 75 and bloc["source"] == "surcharge_service" and bloc["repli"] is True


# =========================================================================================
# 3. Un chantier de plusieurs jours : visites, même équipe, jours distincts (P4-02)
# =========================================================================================
def test_seize_heures_donnent_deux_journees_de_huit_heures_de_la_meme_equipe(instance, par_nom, futurs_ok, capsys):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({TOIT: DEVIS_16H, PETIT_1: {"duree": "120"}, PETIT_2: {"duree": "90"}})
    _confirmer_positions(par_nom, (TOIT, PETIT_1, PETIT_2))
    proposition = _ok(_proposer(par_nom))
    assert proposition["non_cedulees"] == []
    visites = _visites_de(proposition["plan"], iids[TOIT])
    assert [v[4] for v in visites] == [1, 2] and len({v[0] for v in visites}) == 1
    assert [v[3] - v[2] for v in visites] == [480, 480] and visites[0][1] < visites[1][1]
    assert proposition["durees"][iids[TOIT]]["visites"] == [480, 480]
    assert "2 visites de 480 + 480 min" in proposition["durees"][iids[TOIT]]["libelle"]
    # rien n'est assigné ni promis au client par la proposition
    assert {_statut(i) for i in iids.values()} == {"a_planifier"} and _du_type("cedule_appliquee") == []
    for route in proposition["plan"]:
        for visite in route["visites"]:
            assert set(visite) <= {"chantier", "arrivee_min", "debut_min", "fin_min", "visite", "visites_total"}


def test_appliquer_assigne_une_fois_l_intervention_et_garde_les_deux_visites(instance, par_nom, futurs_ok, capsys):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({TOIT: DEVIS_16H, PETIT_1: {"duree": "120"}})
    _confirmer_positions(par_nom, (TOIT, PETIT_1))
    proposition = _ok(_proposer(par_nom))
    equipe = _visites_de(proposition["plan"], iids[TOIT])[0][0]
    application = _ok(_appliquer(par_nom, proposition["plan_id"]))
    par_id = {a["intervention_id"]: a for a in application["assignations"]}
    assert par_id[iids[TOIT]]["technicien_id"] == equipe and par_id[iids[TOIT]]["visites"] == 2
    assert "visites" not in par_id[iids[PETIT_1]]
    assert {_statut(i) for i in iids.values()} == {"planifiee"} and _technicien(iids[TOIT]) == equipe
    assert len([m for m in _du_type("assignation_technicien") if m["intervention_id"] == iids[TOIT]]) == 1
    assert len([m for m in _du_type("transition_statut") if m["intervention_id"] == iids[TOIT]
                and m["statut"] == "planifiee"]) == 1
    avant = _maillons()
    assert _ok(_appliquer(par_nom, proposition["plan_id"]))["deja_appliquee"] is True and _maillons() == avant
    with stockage.transaction():
        assert _registre().valider_chaine()


def test_les_deux_visites_se_datent_jour_par_jour_par_une_personne(instance, par_nom, futurs_ok, capsys):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({TOIT: DEVIS_16H})
    _confirmer_positions(par_nom, (TOIT,))
    proposition = _ok(_proposer(par_nom))
    _ok(_appliquer(par_nom, proposition["plan_id"]))
    visites = _visites_de(proposition["plan"], iids[TOIT])
    jours = [v[1] for v in visites]
    calendrier = {str(jour): f"2030-06-0{3 + rang}" for rang, jour in enumerate(jours)}
    confirmation = _ok(_appeler(par_nom, "m4_confirmer_dates_cedule", {
        "plan_id": proposition["plan_id"], "calendrier": calendrier, "revision_attendue": 0}))
    assert confirmation["calendrier"] == calendrier
    semaine = _ok(_appeler(par_nom, "m4_lire_cedule_semaine", {"debut_semaine": "2030-06-03"}))
    lignes = [ligne for ligne in semaine["interventions"] if ligne["intervention_id"] == iids[TOIT]]
    assert len(lignes) == 2 and {ligne["validite"] for ligne in lignes} == {"date_confirmee"}
    assert sorted(ligne["debut"][:10] for ligne in lignes) == sorted(calendrier.values())


def test_appliquer_juge_l_admissibilite_de_l_equipe_sur_la_visite_et_non_sur_la_duree_du_service(
    instance, par_nom, futurs_ok, capsys,
):
    """Une proposition faite avec d'autres équipes (surcharge) ne contourne pas le profil : l'équipe qui reçoit
    l'intervention doit avoir un quart assez long pour la plus longue VISITE (480 min), pas seulement pour la durée du
    service (180 min). eq-b n'a que des quarts de 400 min au profil."""
    profil = _profil()
    profil["liste"][1]["quarts"] = [{"jour": jour, "debut_min": 480, "fin_min": 880} for jour in (0, 1, 2, 3)]
    _declarer(instance, profil, capsys)
    iids = _naitre({TOIT: DEVIS_16H})
    _confirmer_positions(par_nom, (TOIT,))
    equipe_b = copy.deepcopy(profil["liste"][1])
    equipe_b["quarts"] = [{"jour": jour, "debut_min": 360, "fin_min": 1080} for jour in (0, 1, 2, 3)]
    proposition = _ok(_proposer(par_nom, equipes=[{
        "id": "eq-b", "competences": [], "depot": equipe_b["depot"], "quarts": equipe_b["quarts"]}]))
    assert {v[0] for v in _visites_de(proposition["plan"], iids[TOIT])} == {"eq-b"}
    refus = _refus(_appliquer(par_nom, proposition["plan_id"]))
    assert refus["code"] == "REJ-TOURNEES-PLAN-INVALIDE" and "n'est pas admissible" in refus["detail"]
    assert _statut(iids[TOIT]) == "a_planifier" and _du_type("cedule_appliquee") == []


def test_les_lectures_du_calendrier_montrent_chaque_visite_d_un_chantier_de_plusieurs_jours(
    instance, par_nom, futurs_ok, capsys,
):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({TOIT: DEVIS_16H})
    _confirmer_positions(par_nom, (TOIT,))
    proposition = _ok(_proposer(par_nom))
    _ok(_appliquer(par_nom, proposition["plan_id"]))
    jours = [v[1] for v in _visites_de(proposition["plan"], iids[TOIT])]
    calendrier = {str(jours[0]): "2030-06-03", str(jours[1]): "2030-06-04"}
    _ok(_appeler(par_nom, "m4_confirmer_dates_cedule", {
        "plan_id": proposition["plan_id"], "calendrier": calendrier, "revision_attendue": 0}))
    plan = _ok(_appeler(par_nom, "m4_lire_calendrier_plan", {"plan_id": proposition["plan_id"]}))
    assert plan["total_visites"] == 2 and plan["total_jours"] == 2 and plan["bloquants"] == []
    assert [visite["intervention_id"] for visite in plan["visites"]] == [iids[TOIT]] * 2
    with stockage.transaction():
        reg = _registre()
        mois = apercu_mois.lire(reg, "2030-06")
        assert mois["accepte"] is True, mois
        jours = {j["jour"]: j for m in mois["resultat"]["mois"] for j in m["jours"]}
        assert jours["2030-06-03"]["total"] == 1 and jours["2030-06-04"]["total"] == 1
        page = pages_semaine.lire(reg, "2030-06-03")
        assert page["accepte"] is True, page
        lignes = [ligne for ligne in page["resultat"]["interventions"] if ligne["intervention_id"] == iids[TOIT]]
        assert [(ligne["visite"], ligne["visites_total"]) for ligne in lignes] == [(1, 2), (2, 2)]
        journal = journal_quotidien.lire(reg, "2030-06-03")
        previsions = [ligne for ligne in journal["lignes"] if ligne["type"] == "prevision"]
        assert [(p["visite"], p["visites_total"]) for p in previsions] == [(1, 2)]
        # une note ou une couleur se pose sur un créneau : l'ancre d'un chantier de plusieurs jours est ambiguë
        sources = annotations_calendrier._sources(reg)
        ancre = {cle: lignes[0][cle] for cle in annotations_calendrier._CLES_ANCRE}
        with pytest.raises(annotations_calendrier.Refus, match="ANCRE-MULTI-VISITES"):
            annotations_calendrier._creneau(sources, ancre)
        assert annotations_calendrier._creneau(sources, ancre, 2)["debut"] == lignes[1]["debut"]
    # un report ou une réassignation invalide les DEUX visites datées (la date ne ressuscite pas)
    _ok(_appeler(par_nom, "m4_signaler_report", {
        "intervention_id": iids[TOIT], "motif": "meteo", "horodatage": HORODATAGE}))
    semaine = _ok(_appeler(par_nom, "m4_lire_cedule_semaine", {"debut_semaine": "2030-06-03"}))
    lignes = [ligne for ligne in semaine["interventions"] if ligne["intervention_id"] == iids[TOIT]]
    assert len(lignes) == 2 and {ligne["validite"] for ligne in lignes} == {"a_reconfirmer"}


def test_l_absence_d_une_equipe_un_jour_est_respectee_et_la_meme_equipe_garde_tout(
    instance, par_nom, futurs_ok, capsys,
):
    """eq-a n'a aucun quart le jour 1 (absente) ; eq-b n'a que les jours 1 et 2. Jours consécutifs exigés : le chantier
    va EN ENTIER chez eq-b (jours 1 et 2) ; jamais une visite chez eq-a le jour 1, jamais un mélange d'équipes."""
    profil = _profil(jours_a=(0, 2, 3), jours_b=(1, 2),
                     multijours={"visite_max_minutes": 480, "jours_consecutifs": True})
    _declarer(instance, profil, capsys)
    iids = _naitre({TOIT: DEVIS_16H})
    _confirmer_positions(par_nom, (TOIT,))
    proposition = _ok(_proposer(par_nom))
    visites = _visites_de(proposition["plan"], iids[TOIT])
    assert {v[0] for v in visites} == {"eq-b"} and [v[1] for v in visites] == [1, 2]
    assert not any(r["equipe"] == "eq-a" and r["jour"] == 1 for r in proposition["plan"])


def test_sans_equipe_capable_de_deux_journees_le_chantier_n_est_pas_cedule_et_la_raison_est_dite(
    instance, par_nom, futurs_ok, capsys,
):
    profil = _profil(jours_a=(0,), jours_b=(1,))
    _declarer(instance, profil, capsys)
    iids = _naitre({TOIT: DEVIS_16H, PETIT_1: {"duree": "120"}})
    _confirmer_positions(par_nom, (TOIT, PETIT_1))
    proposition = _ok(_proposer(par_nom))
    assert _visites_de(proposition["plan"], iids[TOIT]) == []
    ligne = next(non for non in proposition["non_cedulees"] if non["chantier"] == iids[TOIT])
    assert ligne["code"] == "continuite_impossible" and "2 journées distinctes" in ligne["raison"]
    assert _visites_de(proposition["plan"], iids[PETIT_1])           # les autres chantiers sont cédulés
    application = _ok(_appliquer(par_nom, proposition["plan_id"]))
    assert _statut(iids[TOIT]) == "a_planifier"                      # jamais à moitié planifié
    assert iids[TOIT] in {non["chantier"] for non in application["non_cedulees"]}


def test_plus_d_une_journee_sans_regles_declarees_n_est_pas_pret_et_dit_quoi_declarer(
    instance, par_nom, futurs_ok, capsys,
):
    _declarer(instance, _profil(multijours=False), capsys)
    iids = _naitre({TOIT: DEVIS_16H})
    _confirmer_positions(par_nom, (TOIT,))
    verdict = _ok(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iids[TOIT]}))
    assert verdict["pret"] is False
    manque = verdict["volets"]["equipe"]["manque"]
    assert "plusieurs jours" in manque and "visite_max_minutes" in manque and "jours_consecutifs" in manque
    refus = _refus(_proposer(par_nom, intervention_ids=[iids[TOIT]]))
    assert refus["code"] == "REJ-CEDULE-PREPARATION-NON-PRETE"


def test_la_preparation_dit_la_duree_les_visites_et_le_repli_au_lieu_de_les_taire(instance, par_nom, futurs_ok, capsys):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({TOIT: DEVIS_16H, PETIT_1: {}})
    _confirmer_positions(par_nom, (TOIT, PETIT_1))
    toit = _ok(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iids[TOIT]}))
    assert toit["pret"] is True
    detail = toit["volets"]["equipe"]["detail"]
    assert "960 min sur site (estimation M3, corrigée par une version apprise appliquée)" in detail
    assert "2 visites de 480 + 480 min" in toit["volets"]["equipe"]["detail"]
    petit = _ok(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iids[PETIT_1]}))
    assert petit["volets"]["equipe"]["detail"] == "équipes admissibles pour ravalement : eq-a, eq-b"


def test_un_creneau_deja_confirme_n_est_pas_pris_en_charge_pour_un_chantier_de_plusieurs_jours(
    instance, par_nom, futurs_ok, capsys,
):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({TOIT: DEVIS_16H})
    _confirmer_positions(par_nom, (TOIT,))
    refus = _refus(_proposer(par_nom, chantiers=[{
        "intervention_id": iids[TOIT], "fenetre": {"jours": [0, 1, 2, 3], "debut_min": 480, "fin_min": 1020},
        "creneau_fige": {"equipe": "eq-a", "jour": 0, "debut_min": 480}}]))
    assert refus["code"] == "REJ-CONTRAT-INVALIDE" and "plusieurs jours" in refus["detail"]
    assert _du_type("cedule_proposee") == []


def test_la_duree_maximale_d_une_visite_se_declare_en_entier_ou_pas_du_tout(instance, par_nom, futurs_ok, capsys):
    _declarer(instance, _profil(), capsys)
    _naitre({TOIT: DEVIS_16H})
    _confirmer_positions(par_nom, (TOIT,))
    for invalide in (
        {"visite_max_minutes": 480}, {"jours_consecutifs": True},
        {"visite_max_minutes": 0, "jours_consecutifs": True},
        {"visite_max_minutes": "480", "jours_consecutifs": True},
        {"visite_max_minutes": 480, "jours_consecutifs": "oui"},
        {"visite_max_minutes": 480, "jours_consecutifs": True, "surprise": 1},
    ):
        refus = _refus(_proposer(par_nom, multijours=invalide))
        assert refus["code"] in ("REJ-CONTRAT-INVALIDE", "REJ-CHAMP-MANQUANT") and "multijours" in refus["detail"]
    assert _du_type("cedule_proposee") == []


def test_la_surcharge_multijours_remplace_le_profil_et_le_dit(instance, par_nom, futurs_ok, capsys):
    _declarer(instance, _profil(), capsys)
    iids = _naitre({TOIT: DEVIS_16H})
    _confirmer_positions(par_nom, (TOIT,))
    proposition = _ok(_proposer(par_nom, multijours={"visite_max_minutes": 320, "jours_consecutifs": True}))
    assert proposition["provenance"]["multijours"] == "surcharge"
    visites = _visites_de(proposition["plan"], iids[TOIT])
    assert [v[3] - v[2] for v in visites] == [320, 320, 320]
    jours = [v[1] for v in visites]
    assert jours == list(range(jours[0], jours[0] + 3))


def test_le_profil_refuse_des_regles_multijours_incompletes(instance, capsys, tmp_path):
    from opsys import equipes as equipes_entreprise

    for invalide in ({"visite_max_minutes": 480}, {"jours_consecutifs": False}, {"visite_max_minutes": 1441,
                                                                               "jours_consecutifs": False},
                     {"visite_max_minutes": 480, "jours_consecutifs": 1}):
        profil = _profil(multijours=invalide)
        with pytest.raises(equipes_entreprise.ProfilInvalide):
            equipes_entreprise.normaliser_equipes(profil)
    assert equipes_entreprise.normaliser_equipes(_profil())["cedule"]["multijours"] == {
        "visite_max_minutes": 480, "jours_consecutifs": False}


# =========================================================================================
# 4. Modules purs
# =========================================================================================
def test_decouper_garde_la_somme_exacte_et_respecte_le_maximum():
    for total in range(1, 2500):
        visites = duree_chantier.decouper(total, 480)
        if total > 4800:
            assert visites is None
            continue
        assert sum(visites) == total and max(visites) <= 480 and min(visites) >= 1
        assert len(visites) == -(-total // 480)
        assert max(visites) - min(visites) <= 1
        assert visites == sorted(visites, reverse=True)
    assert duree_chantier.decouper(960, 480) == [480, 480]
    assert duree_chantier.decouper(961, 480) == [321, 320, 320]
    assert duree_chantier.decouper(480, 480) == [480]


def test_resoudre_prefere_l_estimation_et_signale_l_ecart_avec_le_profil():
    inscription = {"duree_m3": {"statut": "retenue", "minutes": "125.5", "semantique": "duree_ecoulee_intervention",
                                "origine": "bareme", "calibration_version_id": None}}
    bloc, _ = duree_chantier.resoudre(inscription, 90, duree_chantier.SOURCE_PROFIL, None)
    assert bloc["minutes"] == 126 and bloc["source"] == "estimation_m3" and bloc["repli"] is False
    assert bloc["ecart_profil_min"] == 36 and bloc["origine_m3"] == "bareme"
    bloc, _ = duree_chantier.resoudre({}, 90, duree_chantier.SOURCE_PROFIL, None)
    assert bloc["minutes"] == 90 and bloc["repli"] is True and bloc["source"] == "profil_service"
    bloc, detail = duree_chantier.resoudre({}, None, duree_chantier.SOURCE_PROFIL, None)
    assert bloc is None and "aucune durée" in detail
    bloc, detail = duree_chantier.resoudre(
        {"duree_m3": {"statut": "retenue", "minutes": "2000", "semantique": "duree_ecoulee_intervention",
                      "origine": "bareme", "calibration_version_id": None}}, 90, "profil_service", None)
    assert bloc is None and "règles des chantiers de plusieurs jours" in detail
    bloc, detail = duree_chantier.resoudre(
        {"duree_m3": {"statut": "retenue", "minutes": "2000", "semantique": "duree_ecoulee_intervention",
                      "origine": "bareme", "calibration_version_id": None}}, 90, "profil_service",
        {"visite_max_minutes": 100, "jours_consecutifs": False})
    assert bloc is None and "plus de 10 visites" in detail


def test_les_modules_purs_n_importent_ni_opsys_ni_horloge_ni_alea_ni_flottant():
    for nom, permis in (("duree_chantier", {"decimal", "re", "__future__"}), ("reserves_completion", {"__future__"})):
        chemin = Path(__file__).resolve().parents[1] / "src" / "m4_field_ops" / f"{nom}.py"
        source = chemin.read_text(encoding="utf-8")
        for noeud in ast.walk(ast.parse(source)):
            if isinstance(noeud, ast.Import):
                assert {a.name for a in noeud.names} <= permis, (nom, [a.name for a in noeud.names])
            if isinstance(noeud, ast.ImportFrom):
                assert noeud.module in permis or noeud.level == 1, (nom, noeud.module)
            assert not (isinstance(noeud, ast.Constant) and isinstance(noeud.value, float)), nom
            assert not (isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Div)), nom
    assert Decimal  # le module de durée calcule en Decimal, jamais en flottant
    assert reserves_completion.CODES


# =========================================================================================
# 5. La météo juge CHAQUE visite d'un chantier de plusieurs journées (fournisseur manuel, aucun réseau)
# =========================================================================================
def _charger_fixtures_meteo():
    import importlib.util as iu

    spec = iu.spec_from_file_location("m4d_meteo_outil_aide", Path(__file__).with_name("test_meteo_outil.py"))
    module = iu.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_meteo = _charger_fixtures_meteo()
monde_meteo = _meteo.monde


def test_la_meteo_juge_chaque_visite_et_un_vent_fort_bloque_la_visite_du_jour_venteux(par_nom, monde_meteo):
    # on recoupe les trois chantiers de la fixture en visites d'au plus 60 min : les ravalements (120 min) en ont deux
    proposition = _meteo._resultat(_meteo._appeler(par_nom, "m4_proposer_cedule", {
        "horodatage": _meteo.HORODATAGE, "multijours": {"visite_max_minutes": 60, "jours_consecutifs": False}}))
    visites = [(v["chantier"], v.get("visite"), r["jour"]) for r in proposition["plan"] for v in r["visites"]]
    deux_visites = {iid for iid, rang, _ in visites if rang == 2}
    assert deux_visites, "au moins un chantier est découpé en deux visites"
    resultat = _meteo._resultat(_meteo._verifier(par_nom, proposition["plan_id"], _meteo._saisie()))
    assert resultat["statut"] == "ok"
    nombre_de_creneaux = len(resultat["creneaux"]) + sum(j["nombre"] for j in resultat.get("ok_resume", []))
    assert nombre_de_creneaux == len(visites)           # un créneau jugé par VISITE, aucune n'est perdue
    jour_venteux = next(jour for iid, rang, jour in visites if iid in deux_visites and rang == 1)
    venteux = _meteo._resultat(_meteo._verifier(
        par_nom, proposition["plan_id"], _meteo._saisie(dates_vent_fort=[_meteo._date_du_jour(jour_venteux)])))
    assert venteux["statut"] == "bloquant"
    bloques = [c for c in venteux["creneaux"] if c["statut"] == "bloquant"]
    assert bloques and {c["jour"] for c in bloques} == {jour_venteux}
    # l'autre visite du même chantier (un autre jour, calme) reste ok : on ne bloque pas le chantier entier à la légère
    autres_jours = [c for c in venteux["creneaux"] if c["intervention_id"] in {b["intervention_id"] for b in bloques}
                    and c["jour"] != jour_venteux]
    assert all(c["statut"] == "ok" for c in autres_jours)
    assert {r["intervention_id"] for r in venteux["reports_proposes"]} >= {b["intervention_id"] for b in bloques}
