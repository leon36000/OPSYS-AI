"""PLAN T4.12 : le profil des équipes, la cédule et la sortie de `a_planifier`, par les VRAIS outils, le VRAI bus et le
VRAI fichier `entreprise.yaml` (déclaré par `opsys-metier equipes declarer`), sur une base SQLite migrée.

La démonstration Repentigny à Joliette de T4.1-d (`fixtures/scenario_cedule_repentigny_joliette.json`) est rejouée ici
comme PROFIL (`fixtures/equipes_repentigny_joliette.json`, `fictif: true`) : les six chantiers naissent de six devis
acceptés (`m3.devis_accepte`, intervention `a_planifier`), les équipes, durées et réglages viennent du profil seul, et
le plan a les mêmes octets que celui proposé avec les mêmes valeurs en arguments, y compris sur une seconde instance.

Les volets matériel (charge `m6.materiel_pret`, T4.14-b) et météo (profil météo, T4.13) se lisent désormais à leur
source ;
leurs preuves de bout en bout sont `test_materiel_pret_recu.py`, `test_meteo_outil.py` et
`tests/e2e/test_meteo_bloquante_appareil.py`.
Les tests de sortie de ce module les SIMULENT (`futurs_ok`) pour ne prouver ici que la plomberie de la cédule, sans
monter
un M6 ni un profil météo ; `test_aujourd_hui_...` prouve que la porte reste fermée sans eux.
"""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import json
from pathlib import Path

import pytest
import yaml
from m4_field_ops import encodage, etats, preparation
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import outils
from sqlalchemy import select

from opsys import cli, contexte, evenements, identite, stockage, taxonomie
from opsys import equipes as equipes_entreprise
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import CLES_CHIFFREMENT

FICTIF = True
_FIXTURES = Path(__file__).parent / "fixtures"
SCENARIO = json.loads((_FIXTURES / "scenario_cedule_repentigny_joliette.json").read_text(encoding="utf-8"))
EQUIPES = json.loads((_FIXTURES / "equipes_repentigny_joliette.json").read_text(encoding="utf-8"))
M4 = "m04-field-ops"
HORODATAGE = "2030-01-01T00:00:00+00:00"
ACCEPTE_LE = "2030-01-01T10:00:00-05:00"
RECU_LE = dt.datetime(2030, 6, 2, 9, 0, 0, tzinfo=dt.UTC)
HORLOGE_APPAREIL_DEREGLEE = dt.datetime(2000, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
DEBUT_BUS = dt.datetime(2030, 1, 2, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
LEADS = {lead["lead_id"]: lead for lead in SCENARIO["leads"]}
PERSONNES = (
    ("admin.fictif", ["admin"]), ("marie.fictif", ["admin"]), ("luc.fictif", ["employee"]),
    ("marc.fictif", ["employee"]), ("nadia.fictif", ["employee"]), ("vendeur.fictif", ["seller"]),
)


# -- installation -----------------------------------------------------------------------------------
def _monter(dossier: Path, monkeypatch) -> None:
    """Base SQLite migrée, dossier d'état, services propres du scénario et personnes fictives."""
    (dossier / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPSYS_HOME", str(dossier / "home"))
    url = f"sqlite:///{dossier / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    taxonomie.enregistrer_services(EQUIPES["services_propres"])
    with stockage.transaction() as cnx:
        for identifiant, roles in PERSONNES:
            identite.creer_personne(cnx, identifiant, identifiant.title(), "mot-de-passe-fictif-1234", roles)


@pytest.fixture
def instance(tmp_path, monkeypatch):
    _monter(tmp_path / "a", monkeypatch)
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def par_nom(instance):
    return {o.nom: o for o in outils()}


@pytest.fixture
def futurs_ok(monkeypatch):
    """Simule le matériel (T4.14-b) et la météo (T4.13) : deux volets vérifiés. Prouve la plomberie de la cédule ; les
    vrais
    volets sont prouvés ailleurs (voir le docstring du module)."""
    def ok(_registre, _inscription, _lire_position, _lire_equipes, _lire_meteo):
        return {"statut": "ok", "manque": None, "detail": "simulé par le test"}

    monkeypatch.setattr(preparation, "_VOLETS", tuple(
        (nom, ok if nom in ("materiel", "meteo") else fonction) for nom, fonction in preparation._VOLETS))


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
            pile.enter_context(contexte.receptionne_de(contexte.HorodatageAppareil(
                appareil="tel-fictif-t4-12", horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE, recu_le=RECU_LE)))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=ADMIN):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _resultat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _plat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _code_refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _detail_refus(reponse):
    return reponse["resultat"]["verdict"]["detail"]


def _registre():
    return registre_m4.Registre(stockage.maillons(M4, "principal"))


def _maillons():
    with stockage.transaction():
        return _registre().lire()


def _du_type(type_entree):
    return [m for m in _maillons() if m["type_entree"] == type_entree]


def _cles():
    with stockage.transaction() as cnx:
        return sorted(tuple(ligne) for ligne in cnx.execute(select(
            CLES_CHIFFREMENT.c.portee, CLES_CHIFFREMENT.c.identifiant, CLES_CHIFFREMENT.c.cle)).all())


def _etat():
    return _maillons(), _cles()


def _statut(intervention_id):
    with stockage.transaction():
        return etats.statut_courant(_registre(), intervention_id)


def _technicien(intervention_id):
    with stockage.transaction():
        return etats.technicien_assigne(_registre(), intervention_id)


def _octets(objet) -> str:
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


# -- le profil, déclaré par la commande ----------------------------------------------------------------
def _declarer_le_profil(dossier: Path, profil: dict | None = None, capsys=None) -> None:
    fichier = dossier / "equipes-declarees.yaml"
    fichier.write_text(yaml.safe_dump(EQUIPES["profil"] if profil is None else profil, allow_unicode=True),
                       encoding="utf-8")
    assert cli.main(["equipes", "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0
    if capsys is not None:
        capsys.readouterr()


# -- le bus : six devis acceptés, six interventions à planifier -----------------------------------------
def _lead_v2(lead_id: str) -> dict:
    lead = LEADS[lead_id]
    return {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": f"sms-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "+15145550142"}, "service": lead["type_travaux"],
        "ville": lead["secteur"], "urgence_declaree": lead["urgence_declaree"], "canal": "texte", "source": "sms",
    }


def _publier_lead(lead_id: str) -> None:
    evenements.publier(
        "m1.lead_qualifie", "m01-front-office",
        {"lead": _lead_v2(lead_id), "horodatage": HORODATAGE, "signal_id": f"sms:{lead_id}"},
        evenement_id=f"m1-lead-qualifie-{lead_id}")


def _charge_devis(devis_id: str, lead_id: str) -> dict:
    return {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{
            "reference_ligne": f"{devis_id}-L0", "description": "Travaux (fictif)", "quantite": "1",
            "unite": "forfait", "prix_unitaire": "100.00", "prix_ligne": "100.00", "reference_besoin_materiau": None,
        }],
        "cout_total": "80.00", "prix_total": "100.00", "taux_marge": "0.25", "horodatage_acceptation": ACCEPTE_LE,
    }


def _publier_devis(devis_id: str, lead_id: str, evenement_id: str | None = None) -> str:
    identifiant = evenement_id or f"m3-devis-accepte-{devis_id}"
    evenements.publier("m3.devis_accepte", "m03-estimation", _charge_devis(devis_id, lead_id),
                       evenement_id=identifiant)
    return identifiant


def _repartir(tours: int = 3) -> dict[str, int]:
    """Livre à M4 seul (les autres départements n'écoutent pas ici) ; intervalles de 100 s entre les tours."""
    deps = {M4: charger_departements()[M4]}
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(tours):
        resume = evenements.repartir(deps, maintenant=(DEBUT_BUS + dt.timedelta(seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    return total


def _naitre(lead_ids=tuple(LEADS)) -> dict[str, str]:
    """Un devis accepté par lead : ``{lead_id: intervention_id}`` des interventions nées du bus (`a_planifier`)."""
    for lead_id in lead_ids:
        _publier_lead(lead_id)
        _publier_devis(f"DEVIS-{lead_id}", lead_id)
    total = _repartir()
    assert total["echecs"] == 0 and total["quarantaines"] == 0 and total["traites"] == len(lead_ids), total
    with stockage.transaction():
        liste = etats.lister_interventions(_registre(), statut="a_planifier")
    par_lead = {ligne["lead_id"]: ligne["intervention_id"] for ligne in liste}
    assert sorted(par_lead) == sorted(lead_ids)
    return par_lead


def _confirmer_les_positions(par_nom, lead_ids=tuple(LEADS)) -> None:
    for lead_id in lead_ids:
        lead = LEADS[lead_id]
        _resultat(_appeler(par_nom, "m4_confirmer_localisation", {
            "chantier_id": lead_id, "action": "confirmee", "horodatage": HORODATAGE, "confirme_par": "admin.fictif",
            "adresse": {"numero_municipal": "10", "odonyme": "rue Fictive", "municipalite": lead["secteur"]},
            "source": "manuel", "motif": "", "latitude_microdegres": lead["latitude_microdegres"],
            "longitude_microdegres": lead["longitude_microdegres"]}))


def _arguments_ecrits_a_la_main(interventions: dict[str, str]) -> dict:
    """Les valeurs du profil, écrites comme arguments : la surcharge complète (la démonstration de T4.1-d)."""
    profil = EQUIPES["profil"]
    return {
        "horodatage": HORODATAGE,
        "equipes": [{cle: copy.deepcopy(e[cle]) for cle in ("id", "competences", "depot", "quarts")}
                    for e in profil["liste"]],
        "durees_par_service": {s: v["duree_min"] for s, v in profil["services"].items()},
        "competences_par_service": {s: list(v["competences"]) for s, v in profil["services"].items()},
        "chantiers": [{"intervention_id": iid, "fenetre": dict(SCENARIO["fenetre_client"]), "creneau_fige": None}
                      for _lead, iid in sorted(interventions.items())],
        "parametres": dict(SCENARIO["parametres"]),
    }


# =========================================================================================
# 1. Le profil est la démonstration de T4.1-d réécrite : aucun chiffre n'a dérivé
# =========================================================================================
def test_le_profil_est_la_demonstration_de_t4_1_d_reecrite():
    assert EQUIPES["fictif"] is True and SCENARIO["fictif"] is True
    profil = EQUIPES["profil"]
    assert equipes_entreprise.normaliser_equipes(profil) == profil, "la fixture est déjà canonique"
    assert profil["cedule"] == SCENARIO["parametres"]
    assert profil["fenetre_par_defaut"] == SCENARIO["fenetre_client"]
    assert {s: v["duree_min"] for s, v in profil["services"].items()} == SCENARIO["durees_par_type_travaux"]
    assert {s: v["competences"] for s, v in profil["services"].items()} == {
        t: sorted(c) for t, c in SCENARIO["competences_par_type_travaux"].items()}
    assert [(e["id"], e["competences"], e["depot"]["id"], e["quarts"]) for e in profil["liste"]] == [
        (e["id"], sorted(e["competences"]), e["depot"], [SCENARIO["quart"]]) for e in SCENARIO["equipes"]]
    assert {e["depot"]["id"]: {k: v for k, v in e["depot"].items() if k != "id"} for e in profil["liste"]} == \
        SCENARIO["depots"]
    assert sorted(s["code"] for s in EQUIPES["services_propres"]) == sorted(SCENARIO["durees_par_type_travaux"])


# =========================================================================================
# 2. La démonstration Repentigny-Joliette, depuis le profil seul : les mêmes octets
# =========================================================================================
def test_la_demonstration_rejouee_depuis_le_profil_seul_donne_les_memes_octets_de_plan(
    instance, par_nom, futurs_ok, monkeypatch, capsys,
):
    # -- instance A : le profil est déclaré, mais la cédule est proposée avec TOUTES les valeurs en arguments ------
    _declarer_le_profil(instance / "a", capsys=capsys)
    interventions_a = _naitre()
    _confirmer_les_positions(par_nom)
    par_arguments = _resultat(_appeler(par_nom, "m4_proposer_cedule", _arguments_ecrits_a_la_main(interventions_a)))
    assert par_arguments["deja_proposee"] is False and par_arguments["non_pretes"] == []
    assert {v for k, v in par_arguments["provenance"].items() if k != "chantiers"} == {"surcharge"}
    maillon_a = _du_type("cedule_proposee")[0]
    assert maillon_a["empreinte_profil"] is None

    # -- même instance : AUCUN argument, tout vient du profil : le même plan, reconnu par son identifiant ---------
    par_profil = _resultat(_appeler(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE}))
    assert par_profil["deja_proposee"] is True and par_profil["plan_id"] == par_arguments["plan_id"]
    assert par_profil["empreinte_entree"] == par_arguments["empreinte_entree"]
    assert par_profil["empreinte_sortie"] == par_arguments["empreinte_sortie"]
    assert {v for k, v in par_profil["provenance"].items() if k != "chantiers"} == {"profil"}
    assert set(par_profil["provenance"]["chantiers"].values()) == {"profil"}
    assert len(_du_type("cedule_proposee")) == 1

    # -- instance B, neuve : la SEULE source est le profil ; le plan est calculé de zéro, aux mêmes octets ---------
    stockage.liberer()
    _monter(instance / "b", monkeypatch)
    _declarer_le_profil(instance / "b", capsys=capsys)
    interventions_b = _naitre()
    assert interventions_b == interventions_a, "l'identifiant d'une intervention ne dépend que du lead et du devis"
    par_nom_b = {o.nom: o for o in outils()}
    _confirmer_les_positions(par_nom_b)
    seul = _resultat(_appeler(par_nom_b, "m4_proposer_cedule", {"horodatage": HORODATAGE}))
    assert seul["deja_proposee"] is False
    maillon_b = _du_type("cedule_proposee")[0]
    assert _octets(maillon_b["sortie"]) == _octets(maillon_a["sortie"]), "le plan : les mêmes octets"
    assert _octets(maillon_b["entree"]) == _octets(maillon_a["entree"])
    assert seul["empreinte_entree"] == par_arguments["empreinte_entree"]
    assert seul["empreinte_sortie"] == par_arguments["empreinte_sortie"]
    assert seul["plan"] == par_arguments["plan"] and seul["totaux"] == par_arguments["totaux"]
    assert maillon_b["empreinte_profil"] == encodage.empreinte("profil-equipes", EQUIPES["profil"])
    # C'est bien la démonstration de T4.1-d : mêmes équipes, mêmes grappes, mêmes kilomètres (26 785 m).
    routes = {r["equipe"]: {v["chantier"] for v in r["visites"]} for r in seul["plan"]}
    assert routes == {
        "eq-a": {interventions_b[k] for k in ("L-E2E-01", "L-E2E-02", "L-E2E-03")},
        "eq-b": {interventions_b[k] for k in ("L-E2E-10", "L-E2E-11", "L-E2E-12")},
    }
    assert seul["totaux"]["distance_m"] == 26785 and seul["non_cedulees"] == []
    assert seul["mode_bride"] is True and "mode bridé" in seul["avertissement"]
    assert seul["urgences"][interventions_b["L-E2E-11"]] == 1


# =========================================================================================
# 3. Sortie de a_planifier : proposer, appliquer, par les vrais outils
# =========================================================================================
def _proposer_depuis_le_profil(par_nom, **arguments):
    return _appeler(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE, **arguments})


def test_appliquer_fait_sortir_les_six_interventions_de_a_planifier_et_les_assigne(
    instance, par_nom, futurs_ok, capsys,
):
    _declarer_le_profil(instance / "a", capsys=capsys)
    interventions = _naitre()
    _confirmer_les_positions(par_nom)
    verdict = _resultat(_appeler(par_nom, "m4_verifier_preparation",
                                 {"intervention_id": interventions["L-E2E-01"]}))
    assert verdict["pret"] is True and verdict["statut"] == "pret" and verdict["a_fournir"] == []
    assert verdict["volets"]["equipe"]["detail"] == "équipes admissibles pour ravalement : eq-a, eq-b"

    proposition = _resultat(_proposer_depuis_le_profil(par_nom))
    assert {_statut(i) for i in interventions.values()} == {"a_planifier"}, "proposer n'assigne ni ne fait sortir"
    assert _du_type("cedule_appliquee") == []

    application = _resultat(_appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": proposition["plan_id"], "horodatage": HORODATAGE, "confirme_par": "admin.fictif"}))
    routes = {v["chantier"]: r["equipe"] for r in proposition["plan"] for v in r["visites"]}
    assert application["deja_appliquee"] is False and application["appliquee_par"] == "admin.fictif"
    assert application["horodatage_appareil"], "l'heure du serveur fait foi, celle de l'appareil est déréglée"
    assert {a["transition"] for a in application["assignations"]} == {"a_planifier->planifiee"}
    for iid in interventions.values():
        assert _statut(iid) == "planifiee" and _technicien(iid) == routes[iid]
    passages = [m for m in _du_type("transition_statut") if m["statut"] == "planifiee"]
    assert len(passages) == 6 and all(m["empreinte_preparation"] for m in passages)
    with stockage.transaction():
        assert _registre().valider_chaine()
        liste = etats.lister_interventions(_registre(), statut="planifiee")
    assert {ligne["intervention_id"]: ligne["technicien_assigne"] for ligne in liste} == routes

    # rejouer n'écrit rien de plus
    avant = _etat()
    rejeu = _resultat(_appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": proposition["plan_id"], "horodatage": HORODATAGE, "confirme_par": "admin.fictif"}))
    assert rejeu["deja_appliquee"] is True and _etat() == avant


def test_les_membres_d_une_equipe_voient_et_prennent_les_chantiers_que_la_cedule_lui_assigne(
    instance, par_nom, futurs_ok, capsys,
):
    """De bout en bout : la cédule assigne à l'ÉQUIPE ; ses membres (personnes OPSYS du profil) voient ses chantiers,
    pas ceux de l'autre équipe ; celui qui part devient le technicien."""
    _declarer_le_profil(instance / "a", capsys=capsys)
    interventions = _naitre()
    _confirmer_les_positions(par_nom)
    proposition = _resultat(_proposer_depuis_le_profil(par_nom))
    _resultat(_appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": proposition["plan_id"], "horodatage": HORODATAGE, "confirme_par": "admin.fictif"}))
    luc = contexte.IdentiteAppelante(personne="luc.fictif", role="employee")
    nadia = contexte.IdentiteAppelante(personne="nadia.fictif", role="employee")
    equipe_a = {interventions[k] for k in ("L-E2E-01", "L-E2E-02", "L-E2E-03")}
    equipe_b = {interventions[k] for k in ("L-E2E-10", "L-E2E-11", "L-E2E-12")}
    def vues(identite_appelante):
        reponse = _appeler(par_nom, "m4_lister_interventions", {}, identite_appelante)
        return {ligne["intervention_id"] for ligne in reponse["resultat"]}

    assert vues(luc) == equipe_a and vues(nadia) == equipe_b
    depart = _appeler(par_nom, "m4_demarrer_route", {
        "intervention_id": interventions["L-E2E-01"], "technicien_id": "luc.fictif", "horodatage": HORODATAGE}, luc)
    assert depart["resultat"]["accepte"] is True, depart
    assert _technicien(interventions["L-E2E-01"]) == "luc.fictif" and _statut(interventions["L-E2E-01"]) == "en_route"
    refus = _appeler(par_nom, "m4_demarrer_route", {
        "intervention_id": interventions["L-E2E-10"], "technicien_id": "luc.fictif", "horodatage": HORODATAGE}, luc)
    assert refus["resultat"]["accepte"] is False
    assert refus["resultat"]["verdict"]["code"] == "REJ-INTERVENTION-NON-ASSIGNEE"


def test_aujourd_hui_la_porte_reste_fermee_faute_de_materiel_et_de_meteo(instance, par_nom, capsys):
    """Sans les volets simulés : le profil et l'adresse suffisent à ce qu'ils vérifient, pas à « prêt ». Sans charge de
    M6
    (T4.14-b) le matériel est non vérifiable ; sans règles météo (T4.13) la météo manque."""
    _declarer_le_profil(instance / "a", capsys=capsys)
    interventions = _naitre()
    _confirmer_les_positions(par_nom)
    verdict = _resultat(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": interventions["L-E2E-01"]}))
    assert verdict["pret"] is False and verdict["statut"] == "bloque"
    assert [f["volet"] for f in verdict["a_fournir"]] == ["materiel", "meteo"]
    assert verdict["volets"]["materiel"]["statut"] == "non_verifiable"
    assert verdict["volets"]["meteo"]["statut"] == "manque"
    assert "opsys-metier meteo declarer" in verdict["volets"]["meteo"]["manque"]
    assert verdict["volets"]["soumission"]["statut"] == verdict["volets"]["adresse"]["statut"] == "ok"
    assert verdict["volets"]["equipe"]["statut"] == "ok"
    avant = _etat()
    reponse = _proposer_depuis_le_profil(par_nom)
    assert _code_refus(reponse) == "REJ-CEDULE-RIEN-A-PLANIFIER"
    assert "a_planifier non prêtes" in _detail_refus(reponse) and "materiel, meteo" in _detail_refus(reponse)
    reponse = _proposer_depuis_le_profil(par_nom, intervention_ids=[interventions["L-E2E-01"]])
    assert _code_refus(reponse) == "REJ-CEDULE-PREPARATION-NON-PRETE"
    assert _etat() == avant, "aucune écriture"
    assert {_statut(i) for i in interventions.values()} == {"a_planifier"}


def test_sans_profil_le_verdict_dit_quoi_declarer_jamais_un_repli(instance, par_nom, futurs_ok, capsys):
    interventions = _naitre()  # aucun profil n'a été déclaré
    _confirmer_les_positions(par_nom)
    avant = _etat()
    verdict = _resultat(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": interventions["L-E2E-01"]}))
    assert verdict["pret"] is False and verdict["statut"] == "bloque"
    equipe = verdict["volets"]["equipe"]
    assert equipe["statut"] == "manque" and equipe["detail"] == "REJ-EQUIPES-NON-CONFIGUREES"
    assert "opsys-metier equipes declarer --depuis" in equipe["manque"]
    assert str(taxonomie.fichier_profil()) in equipe["manque"]
    reponse = _proposer_depuis_le_profil(par_nom)
    assert _code_refus(reponse) == "REJ-CEDULE-RIEN-A-PLANIFIER" and "equipe" in _detail_refus(reponse)
    assert "opsys-metier equipes declarer --depuis" in _detail_refus(reponse), (
        "le verdict dit quoi déclarer, et comment")
    assert _etat() == avant


def test_profil_retire_ou_casse_apres_la_proposition_verdict_jamais_un_repli(instance, par_nom, futurs_ok, capsys):
    _declarer_le_profil(instance / "a", capsys=capsys)
    interventions = _naitre()
    _confirmer_les_positions(par_nom)
    proposition = _resultat(_proposer_depuis_le_profil(par_nom))
    avant = _etat()
    fichier = taxonomie.fichier_profil()
    complet = yaml.safe_load(fichier.read_text(encoding="utf-8"))

    # -- retiré : plus aucune équipe, plus de cédule ; l'application d'un plan lu dans le profil est refusée --------
    sans_equipes = {k: v for k, v in complet.items() if k != "equipes"}
    fichier.write_text(yaml.safe_dump(sans_equipes, allow_unicode=True), encoding="utf-8")
    reponse = _proposer_depuis_le_profil(par_nom)
    assert _code_refus(reponse) == "REJ-CEDULE-RIEN-A-PLANIFIER" and "equipe" in _detail_refus(reponse)
    reponse = _appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": proposition["plan_id"], "horodatage": HORODATAGE, "confirme_par": "admin.fictif"})
    assert _code_refus(reponse) == "REJ-CEDULE-PREPARATION-NON-PRETE"
    verdict = _resultat(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": interventions["L-E2E-01"]}))
    assert verdict["volets"]["equipe"]["detail"] == "REJ-EQUIPES-NON-CONFIGUREES"

    # -- cassé : REJ-PROFIL-INVALIDE, jamais lu comme absent, jamais un repli sur des valeurs ------------------------
    casse = copy.deepcopy(complet)
    casse["equipes"]["liste"][0]["salaire"] = 1
    fichier.write_text(yaml.safe_dump(casse, allow_unicode=True), encoding="utf-8")
    verdict = _resultat(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": interventions["L-E2E-01"]}))
    assert verdict["volets"]["equipe"]["statut"] == "manque"
    assert verdict["volets"]["equipe"]["detail"] == "REJ-PROFIL-INVALIDE"
    assert "clés inconnues" in verdict["volets"]["equipe"]["manque"]
    assert cli.main(["verifier"]) == 1, "`opsys-metier verifier` le signale aussi"
    assert _etat() == avant, "aucune écriture pendant tout cela"
    assert {_statut(i) for i in interventions.values()} == {"a_planifier"}


def test_un_profil_qui_change_apres_la_proposition_refuse_l_application_sans_rien_ecrire(
    instance, par_nom, futurs_ok, capsys,
):
    _declarer_le_profil(instance / "a", capsys=capsys)
    interventions = _naitre()
    _confirmer_les_positions(par_nom)
    proposition = _resultat(_proposer_depuis_le_profil(par_nom))
    avant = _etat()
    change = copy.deepcopy(EQUIPES["profil"])
    change["cedule"]["iterations"] = 501  # rien d'admissibilité : seul le profil lu par le plan a bougé
    _declarer_le_profil(instance / "a", change, capsys)
    reponse = _appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": proposition["plan_id"], "horodatage": HORODATAGE, "confirme_par": "admin.fictif"})
    assert _code_refus(reponse) == "REJ-CEDULE-ENTREE-CHANGEE"
    assert "le profil des équipes a changé" in _detail_refus(reponse)
    journal_avant = [m for m in avant[0] if m["type_entree"] != "cedule_appliquee"]
    assert [m for m in _maillons() if m["type_entree"] != "cedule_appliquee"] == journal_avant
    assert {_statut(i) for i in interventions.values()} == {"a_planifier"} and _du_type("cedule_appliquee") == []
    # proposer de nouveau (nouveau profil, nouveau plan) rend l'application possible
    nouvelle = _resultat(_proposer_depuis_le_profil(par_nom))
    assert nouvelle["plan_id"] != proposition["plan_id"]
    _resultat(_appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": nouvelle["plan_id"], "horodatage": HORODATAGE, "confirme_par": "admin.fictif"}))
    assert {_statut(i) for i in interventions.values()} == {"planifiee"}


def test_une_adresse_retiree_apres_la_proposition_refuse_l_application_et_nomme_l_intervention(
    instance, par_nom, futurs_ok, capsys,
):
    _declarer_le_profil(instance / "a", capsys=capsys)
    interventions = _naitre()
    _confirmer_les_positions(par_nom)
    proposition = _resultat(_proposer_depuis_le_profil(par_nom))
    _resultat(_appeler(par_nom, "m4_confirmer_localisation", {
        "chantier_id": "L-E2E-10", "action": "retiree", "horodatage": HORODATAGE, "confirme_par": "admin.fictif",
        "motif": "adresse contestée par le client (fictif)"}))
    avant = _etat()
    reponse = _appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": proposition["plan_id"], "horodatage": HORODATAGE, "confirme_par": "admin.fictif"})
    assert _code_refus(reponse) == "REJ-CEDULE-PREPARATION-NON-PRETE"
    assert interventions["L-E2E-10"] in _detail_refus(reponse) and "adresse" in _detail_refus(reponse)
    assert _etat() == avant


def test_un_employe_ne_propose_ni_n_applique_et_l_identite_est_celle_de_l_appareil(
    instance, par_nom, futurs_ok, capsys,
):
    _declarer_le_profil(instance / "a", capsys=capsys)
    interventions = _naitre()
    _confirmer_les_positions(par_nom)
    proposition = _resultat(_proposer_depuis_le_profil(par_nom))
    marc = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
    avant = _etat()
    reponse = _appeler(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE}, marc)
    assert _code_refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    reponse = _appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": proposition["plan_id"], "horodatage": HORODATAGE, "confirme_par": "marc.fictif"}, marc)
    assert _code_refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    reponse = _appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": proposition["plan_id"], "horodatage": HORODATAGE, "confirme_par": "marie.fictif"})
    assert _code_refus(reponse) == "REJ-IDENTITE-FOURNIE-DIFFERENTE", "l'admin ne signe pas au nom d'une autre"
    assert _etat() == avant
    reponse = _appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": proposition["plan_id"], "horodatage": HORODATAGE, "confirme_par": "agent.fictif"}, None)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, "sans identité d'appareil : l'agent"
    assert _etat() != avant and {_statut(i) for i in interventions.values()} == {"planifiee"}


def test_un_argument_est_une_surcharge_tracee_au_maillon(instance, par_nom, futurs_ok, capsys):
    _declarer_le_profil(instance / "a", capsys=capsys)
    _naitre()
    _confirmer_les_positions(par_nom)
    parametres = {**SCENARIO["parametres"], "iterations": 77}
    proposition = _resultat(_proposer_depuis_le_profil(par_nom, parametres=parametres))
    assert proposition["provenance"]["parametres"] == "surcharge" and proposition["provenance"]["equipes"] == "profil"
    maillon = _du_type("cedule_proposee")[0]
    assert maillon["provenance"] == proposition["provenance"]
    assert maillon["entree"]["parametres"]["iterations"] == 77
    assert maillon["empreinte_profil"] == encodage.empreinte("profil-equipes", EQUIPES["profil"])
    assert proposition["propose_par"] == "admin.fictif"


def test_le_registre_ne_garde_ni_membre_ni_coordonnee_de_chantier(instance, par_nom, futurs_ok, capsys):
    _declarer_le_profil(instance / "a", capsys=capsys)
    _naitre()
    _confirmer_les_positions(par_nom)
    _resultat(_proposer_depuis_le_profil(par_nom))
    texte = json.dumps(_maillons(), ensure_ascii=False)
    for interdit in ("luc.fictif", "marc.fictif", "nadia.fictif", "membres", "45742000", "-73450000", "Client Fictif",
                     "+15145550142"):
        assert interdit not in texte, interdit


# =========================================================================================
# 4. Plus de doublon : le bus et la planification à la main, dans les DEUX ordres
# =========================================================================================
def _contrat_v1(lead_id: str) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": f"C-{lead_id}", "type_travaux": "renovation_totale",
        "ville": "Repentigny", "canal": "telephone", "contact": {"nom": "Dupont", "telephone": "0102030405"},
        "urgence_declaree": False,
    }


def _planifier_a_la_main(par_nom, lead_id: str, devis_id: str | None, horodatage: str = HORODATAGE):
    return _appeler(par_nom, "m4_planifier_intervention", {
        "contrat": _contrat_v1(lead_id),
        "marqueur": {"readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
                     "horodatage": "2030-01-01T00:00:00+00:00", "empreinte": "ab" * 32},
        "horodatage": horodatage, "sel": "sel-fictif", "techniciens_disponibles": ["luc.fictif"],
        "fenetres_disponibles": [{"debut": "2030-01-07T07:00:00+00:00", "fin": "2030-01-07T19:00:00+00:00"}],
        "devis_id": devis_id})


def _inscriptions():
    return [m for m in _maillons() if m["type_entree"] == "intervention_inscrite"]


def test_ordre_1_le_bus_d_abord_puis_la_main_avec_le_meme_devis_est_refusee(instance, par_nom):
    (iid,) = _naitre(("L-E2E-01",)).values()
    avant = _etat()
    reponse = _planifier_a_la_main(par_nom, "L-E2E-01", "DEVIS-L-E2E-01")
    assert _code_refus(reponse) == "REJ-TRANSITION-ILLEGALE"
    assert iid in _detail_refus(reponse) and "un devis n'a qu'une intervention" in _detail_refus(reponse)
    assert _etat() == avant, "rien n'est écrit : ni inscription, ni assignation, ni clé"
    assert [m["intervention_id"] for m in _inscriptions()] == [iid]


def test_ordre_2_la_main_d_abord_puis_le_bus_reconnait_l_intervention_et_n_en_cree_pas_de_seconde(instance, par_nom):
    plan = _plat(_planifier_a_la_main(par_nom, "L-E2E-01", "DEVIS-L-E2E-01"))
    _publier_lead("L-E2E-01")
    evenement_id = _publier_devis("DEVIS-L-E2E-01", "L-E2E-01")
    total = _repartir()
    assert total["traites"] == 1 and total["echecs"] == 0 and total["quarantaines"] == 0, total
    assert [m["intervention_id"] for m in _inscriptions()] == [plan["intervention_id"]]
    with stockage.transaction():
        (ligne,) = etats.lister_interventions(_registre())
    assert ligne["intervention_id"] == plan["intervention_id"] and ligne["statut"] == "planifiee"
    assert evenement_id.startswith("m3-devis-accepte-")


def test_l_evenement_en_vol_et_la_main_dans_les_deux_ordres_donnent_toujours_une_seule_intervention(instance, par_nom):
    """Le devis est publié (en vol), et la main planifie AVANT la livraison : le bus reconnaît celle de la main. Puis un
    second devis : le bus livre AVANT la main, qui est refusée. Deux devis, deux interventions, jamais quatre."""
    _publier_lead("L-E2E-01")
    _publier_devis("DEVIS-L-E2E-01", "L-E2E-01")  # en vol
    plan = _plat(_planifier_a_la_main(par_nom, "L-E2E-01", "DEVIS-L-E2E-01"))  # la main passe la première
    _publier_lead("L-E2E-02")
    _publier_devis("DEVIS-L-E2E-02", "L-E2E-02")
    assert _repartir()["echecs"] == 0  # le bus livre les deux devis
    refus = _planifier_a_la_main(par_nom, "L-E2E-02", "DEVIS-L-E2E-02")  # la main passe la seconde
    assert _code_refus(refus) == "REJ-TRANSITION-ILLEGALE"
    par_devis = {m["devis_id"]: m["intervention_id"] for m in _inscriptions()}
    assert sorted(par_devis) == ["DEVIS-L-E2E-01", "DEVIS-L-E2E-02"]
    assert par_devis["DEVIS-L-E2E-01"] == plan["intervention_id"]
    assert len(_inscriptions()) == 2


def test_sans_devis_id_la_main_ne_contourne_pas_la_garde_et_un_autre_devis_reste_possible(instance, par_nom):
    (iid,) = _naitre(("L-E2E-01",)).values()
    avant = _etat()
    reponse = _planifier_a_la_main(par_nom, "L-E2E-01", None)
    assert _code_refus(reponse) == "REJ-TRANSITION-ILLEGALE" and "sans devis_id" in _detail_refus(reponse)
    assert _etat() == avant
    assert _plat(_planifier_a_la_main(par_nom, "L-E2E-01", "DEVIS-AUTRE"))["statut"] == "planifiee"
    assert len(_inscriptions()) == 2 and iid in [m["intervention_id"] for m in _inscriptions()]


def test_le_repli_manuel_reste_ouvert_pour_un_lead_sans_intervention_nee_du_bus(instance, par_nom):
    """Un lead saisi dans M2 sans M1 part en quarantaine chez M4 : `m4_planifier_intervention` reste son repli."""
    _publier_devis("DEVIS-DIRECT", "L-DIRECT")  # aucun m1.lead_qualifie : M4 n'invente ni service ni ville
    total = _repartir(tours=8)
    assert total["quarantaines"] == 1 and _inscriptions() == []
    assert _plat(_planifier_a_la_main(par_nom, "L-DIRECT", "DEVIS-DIRECT"))["statut"] == "planifiee"
    assert len(_inscriptions()) == 1
