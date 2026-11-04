"""P4-05 : régressions de la relecture adverse (défauts A1, A2, A7, A8).

Repris de `tests_relecture/` (assertions conservées) et complétés par les cas voisins qui ne doivent PAS changer :
une `planifiee` SANS créneau confirmé reste replanifiable, et la garde du créneau se teste aussi sur le module pur.

- A1 : replanifier une `planifiee` à date confirmée ne déplace pas le créneau (refus avant écriture).
- A2 : un refus après la transition `reportee` -> `planifiee` est atomique (statut et registre inchangés).
- A7 : sur refus, le plan de secours garde le report réel et son motif.
- A8 : l'historique des reports suit l'HEURE, pas l'ordre d'append ; le secours suit le plus récent.

Données fictives (`fictif: true`).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from m4_field_ops import cedule_tournees, etats, preparation, replanification, verdicts
from m4_field_ops.registre import Registre

from opsys import contexte, stockage
from opsys.outils import executer_atomique

_TESTS = Path(__file__).resolve().parent


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


e2e = _charger("rev_replan_e2e", _TESTS / "test_p4_e2e_preuve.py")
aide = e2e.aide
_cedule = _charger("rev_replan_cedule", _TESTS / "test_cedule_tournees.py")
_aide_p4 = _charger("rev_replan_p4", _TESTS / "test_p4_retard_replanification.py")


def _futurs_ok(monkeypatch):
    def ok(_registre, _inscription, _lire_position, _lire_equipes, _lire_meteo):
        return {"statut": "ok", "manque": None, "detail": "simulé par le test de relecture"}

    monkeypatch.setattr(preparation, "_VOLETS", tuple(
        (nom, ok if nom in ("materiel", "meteo") else fonction)
        for nom, fonction in preparation._VOLETS))


def _monde_date(tmp_path, monkeypatch):
    _futurs_ok(monkeypatch)
    aide._monter(tmp_path / "a", monkeypatch)
    aide._declarer_le_profil(tmp_path / "a")
    par_nom = {o.nom: o for o in e2e.outils()}
    aide._confirmer_les_positions(par_nom)
    interventions = aide._naitre()
    plan = aide._resultat(aide._proposer_depuis_le_profil(par_nom))["plan_id"]
    aide._resultat(aide._appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": plan, "horodatage": aide.HORODATAGE, "confirme_par": "admin.fictif"}))
    aide._resultat(aide._appeler(par_nom, "m4_confirmer_dates_cedule",
                                 {"plan_id": plan, "calendrier": {"0": e2e.LUNDI},
                                  "revision_attendue": 0}, aide.ADMIN))
    return par_nom, interventions


def _monde(tmp_path, monkeypatch):
    _futurs_ok(monkeypatch)
    aide._monter(tmp_path / "a", monkeypatch)
    aide._declarer_le_profil(tmp_path / "a")
    par_nom = {o.nom: o for o in e2e.outils()}
    aide._confirmer_les_positions(par_nom)
    interventions = aide._naitre()
    plan = aide._resultat(aide._proposer_depuis_le_profil(par_nom))["plan_id"]
    aide._resultat(aide._appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": plan, "horodatage": aide.HORODATAGE, "confirme_par": "admin.fictif"}))
    return par_nom, interventions


def _projection(iid):
    from m4_field_ops import calendrier_civil

    with stockage.transaction():
        reg = Registre(stockage.maillons(e2e.M4, "principal"))
        lignes, sans_date = calendrier_civil._projection(calendrier_civil._index(reg))
    return [ligne for ligne in lignes if ligne["intervention_id"] == iid], sans_date


def _statut(iid):
    with stockage.transaction():
        reg = Registre(stockage.maillons(e2e.M4, "principal"))
        return etats.statut_courant(reg, iid)


def _maillons(type_entree):
    with stockage.transaction():
        reg = Registre(stockage.maillons(e2e.M4, "principal"))
        return [m for m in reg.lire() if m.get("type_entree") == type_entree]


# =========================================================================================
# A1 — un créneau daté confirmé n'est jamais déplacé
# =========================================================================================
def test_replanifier_une_planifiee_datee_ne_deplace_pas_le_creneau_confirme(tmp_path, monkeypatch):
    par_nom, interventions = _monde_date(tmp_path, monkeypatch)
    iid = next(iter(interventions.values()))
    avant, _ = _projection(iid)
    assert len(avant) == 1 and avant[0]["validite"] == "date_confirmee"

    reponse = aide._appeler(par_nom, "m4_replanifier_intervention", {
        "intervention_id": iid, "horodatage": "2030-06-01T09:00:00-04:00",
        "confirme_par": "admin.fictif"})
    resultat = reponse["resultat"]

    apres, sans_date = _projection(iid)
    assert apres and apres[0]["validite"] == "date_confirmee", (
        "créneau confirmé perdu après une replanification acceptée : "
        f"avant={avant[0]['debut']}..{avant[0]['fin']}, après={apres}, sans_date={sans_date}, "
        f"accepte={resultat.get('accepte')}, verdict={resultat.get('verdict')}")
    assert apres[0]["fin"] == avant[0]["fin"], (
        f"créneau confirmé déplacé : avant={avant[0]['debut']}..{avant[0]['fin']}, "
        f"après={apres[0]['debut']}..{apres[0]['fin']}")
    # Le refus est nommé AVANT toute écriture, et il nomme le créneau.
    assert resultat["accepte"] is False, resultat
    assert resultat["verdict"]["code"] == "REJ-REPLANIFICATION-REFUS", resultat
    assert "confirmé" in resultat["verdict"]["detail"], resultat


def test_verifier_refuse_un_creneau_confirme_avec_le_lecteur():
    reg, ids, _positions = _cedule._monde()
    iid = next(iter(ids.values()))
    creneau = {"debut": "2030-06-03T08:00:00-04:00", "fin": "2030-06-03T10:00:00-04:00"}
    dossier, verdict = replanification.verifier(
        reg, iid, lambda _r, _l: (None, None), lire_creneau_confirme=lambda _r, _i: creneau)
    assert dossier is None and verdict["code"] == "REJ-REPLANIFICATION-REFUS"
    assert "confirmé" in verdict["detail"]


def test_creneau_confirme_rend_la_ligne_de_l_intervention_demandee():
    from m4_field_ops import calendrier_civil

    reg, ids, _plan = _aide_p4._monde_date()
    iid = next(iter(ids.values()))
    ligne = calendrier_civil.creneau_confirme(reg, iid)
    assert ligne["intervention_id"] == iid
    assert ligne["validite"] == "date_confirmee"
    assert calendrier_civil.creneau_confirme(reg, "intervention-inconnue") is None


def test_creneau_confirme_ne_rend_pas_un_creneau_a_reconfirmer():
    from m4_field_ops import calendrier_civil

    reg, ids, _plan = _aide_p4._monde_date()
    iid = next(iter(ids.values()))
    _cedule._reussi(etats.transitionner(
        iid, "reportee", reg, "2030-06-03T09:00:00-04:00", motif="meteo"))
    assert calendrier_civil.creneau_confirme(reg, iid) is None


def test_une_planifiee_sans_creneau_confirme_reste_replanifiable(monkeypatch):
    import m4_field_ops.preparation as preparation_module

    reg, ids, _positions = _cedule._monde()
    iid = list(ids.values())[1]
    monkeypatch.setattr(preparation_module, "evaluer",
                        lambda *a, **k: ({"pret": True, "a_fournir": [], "statut": "pret"}, None))
    dossier, verdict = replanification.verifier(
        reg, iid, lambda _r, _l: (None, None),
        lire_creneau_confirme=lambda _r, _i: None)
    assert verdict is None
    assert dossier["prochaine_etape"] == "reproposer_cedule"


# =========================================================================================
# A2 — un refus est atomique : rien ne reste (statut ET proposition)
# =========================================================================================
def test_un_refus_apres_la_transition_laisse_l_intervention_reportee(tmp_path, monkeypatch):
    par_nom, interventions = _monde(tmp_path, monkeypatch)
    iid = next(iter(interventions.values()))
    aide._resultat(aide._appeler(par_nom, "m4_signaler_report", {
        "intervention_id": iid, "motif": "meteo",
        "horodatage": "2030-06-01T08:00:00-04:00"}, aide.ADMIN))
    assert _statut(iid) == "reportee"
    avant = len(_maillons("cedule_proposee"))

    reponse = aide._appeler(par_nom, "m4_replanifier_intervention", {
        "intervention_id": iid, "horodatage": "2030-06-01T09:00:00-04:00",
        "confirme_par": "admin.fictif", "moteur": "pyvrp"}, aide.ADMIN)
    resultat = reponse["resultat"]
    assert reponse["ok"] is True and resultat["accepte"] is False, reponse
    assert resultat["verdict"]["code"] == "REJ-TOURNEES-SOLVEUR-ABSENT", resultat
    assert len(_maillons("cedule_proposee")) == avant, "un refus ne doit pas laisser de proposition"

    apres = _statut(iid)
    assert apres == "reportee", (
        "refus de replanification laissant une écriture partielle : "
        f"statut après refus = {apres!r}, attendu 'reportee' (verdict {resultat['verdict']['code']})")


def test_une_reportee_prete_redevient_planifiee_et_recoit_un_plan(tmp_path, monkeypatch):
    # Cas voisin de A2 : le chemin nominal de la reportée n'est pas cassé par la transaction de replanification.
    par_nom, interventions = _monde(tmp_path, monkeypatch)
    iid = next(iter(interventions.values()))
    aide._resultat(aide._appeler(par_nom, "m4_signaler_report", {
        "intervention_id": iid, "motif": "meteo",
        "horodatage": "2030-06-01T08:00:00-04:00"}, aide.ADMIN))
    reponse = aide._appeler(par_nom, "m4_replanifier_intervention", {
        "intervention_id": iid, "horodatage": "2030-06-01T09:00:00-04:00",
        "confirme_par": "admin.fictif"}, aide.ADMIN)
    assert reponse["resultat"]["accepte"] is True, reponse
    assert _statut(iid) == "planifiee"
    assert len(_maillons("cedule_proposee")) >= 2


def test_la_portee_de_replanification_n_ouvre_une_transaction_que_si_elle_existe(monkeypatch):
    # La portée atomique suit le registre : durable -> une transaction (réelle ou point de sauvegarde) ;
    # registre EN MÉMOIRE hors transaction -> aucune base ouverte par surprise.
    import contextlib

    from m4_field_ops import outils as m4_outils

    ouvertes = []

    @contextlib.contextmanager
    def fausse_transaction():
        ouvertes.append(True)
        yield

    monkeypatch.setattr(stockage, "transaction", fausse_transaction)
    for registre, connexion, attendu in (
        (None, object(), [True]),          # durable, transaction du socle : point de sauvegarde
        (None, None, [True, True]),        # durable, appel direct : transaction réelle
        (object(), object(), [True, True, True]),  # mémoire, transaction active : point de sauvegarde
        (object(), None, [True, True, True]),      # mémoire, aucune transaction : rien à ouvrir
    ):
        monkeypatch.setattr(stockage, "connexion_courante", lambda valeur=connexion: valeur)
        with m4_outils._transaction_de_replanification(registre):
            pass
        assert ouvertes == attendu


def test_un_employe_ne_replanifie_pas(tmp_path, monkeypatch):
    par_nom, interventions = _monde(tmp_path, monkeypatch)
    iid = next(iter(interventions.values()))
    marc = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
    reponse = aide._appeler(par_nom, "m4_replanifier_intervention", {
        "intervention_id": iid, "horodatage": "2030-06-01T09:00:00-04:00",
        "confirme_par": "marc.fictif"}, marc)
    assert reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE", reponse
    assert _statut(iid) == "planifiee"


def test_un_appel_sans_reception_utilise_l_horodatage_fourni(tmp_path, monkeypatch):
    # Appel d'agent/console (aucune réception d'appareil) : le texte fourni fait foi, et aucun
    # `horodatage_appareil` n'est inventé dans la réponse.
    par_nom, interventions = _monde(tmp_path, monkeypatch)
    iid = next(iter(interventions.values()))
    aide._resultat(aide._appeler(par_nom, "m4_signaler_report", {
        "intervention_id": iid, "motif": "meteo",
        "horodatage": "2030-06-01T08:00:00-04:00"}, aide.ADMIN))
    reponse = executer_atomique(par_nom["m4_replanifier_intervention"], {
        "intervention_id": iid, "horodatage": "2030-06-01T09:00:00-04:00",
        "confirme_par": "admin.fictif"})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert "horodatage_appareil" not in reponse["resultat"]["resultat"]


def test_un_refus_de_transition_est_atomique(tmp_path, monkeypatch):
    par_nom, interventions = _monde(tmp_path, monkeypatch)
    iid = next(iter(interventions.values()))
    aide._resultat(aide._appeler(par_nom, "m4_signaler_report", {
        "intervention_id": iid, "motif": "meteo",
        "horodatage": "2030-06-01T08:00:00-04:00"}, aide.ADMIN))
    refus = verdicts.construire_verdict("REJ-REPLANIFICATION-REFUS", detail="refus de test")
    monkeypatch.setattr(etats, "transitionner", lambda *_a, **_k: (None, refus))
    reponse = aide._appeler(par_nom, "m4_replanifier_intervention", {
        "intervention_id": iid, "horodatage": "2030-06-01T09:00:00-04:00",
        "confirme_par": "admin.fictif"}, aide.ADMIN)
    assert reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"] == refus
    assert _statut(iid) == "reportee"


def test_un_refus_d_application_est_atomique(tmp_path, monkeypatch):
    par_nom, interventions = _monde(tmp_path, monkeypatch)
    iid = next(iter(interventions.values()))
    aide._resultat(aide._appeler(par_nom, "m4_signaler_report", {
        "intervention_id": iid, "motif": "meteo",
        "horodatage": "2030-06-01T08:00:00-04:00"}, aide.ADMIN))
    avant = len(_maillons("cedule_proposee"))
    refus = verdicts.construire_verdict("REJ-CEDULE-ENTREE-CHANGEE", detail="refus de test")
    monkeypatch.setattr(cedule_tournees, "appliquer", lambda *_a, **_k: (None, refus))
    reponse = aide._appeler(par_nom, "m4_replanifier_intervention", {
        "intervention_id": iid, "horodatage": "2030-06-01T09:00:00-04:00",
        "confirme_par": "admin.fictif"}, aide.ADMIN)
    assert reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"] == refus
    assert _statut(iid) == "reportee"
    assert len(_maillons("cedule_proposee")) == avant, (
        "un refus à l'application doit annuler la proposition écrite dans la même transaction")


# =========================================================================================
# A7 — sur refus, le secours garde le report et son motif
# =========================================================================================
def test_un_refus_garde_le_motif_du_report_dans_le_secours(tmp_path, monkeypatch):
    par_nom, interventions = _monde(tmp_path, monkeypatch)
    iid = next(iter(interventions.values()))
    aide._resultat(aide._appeler(par_nom, "m4_signaler_report", {
        "intervention_id": iid, "motif": "meteo",
        "horodatage": "2030-06-01T08:00:00-04:00"}, aide.ADMIN))

    def materiel_manquant(_registre, _inscription, _lire_position, _lire_equipes, _lire_meteo):
        return {"statut": "manque", "manque": "matériel non prêt (test)",
                "detail": "ligne de matériel manquante"}

    monkeypatch.setattr(preparation, "_VOLETS", tuple(
        (nom, materiel_manquant if nom == "materiel" else fonction)
        for nom, fonction in preparation._VOLETS))
    reponse = aide._appeler(par_nom, "m4_replanifier_intervention", {
        "intervention_id": iid, "horodatage": "2030-06-01T09:00:00-04:00",
        "confirme_par": "admin.fictif"}, aide.ADMIN)
    resultat = reponse["resultat"]
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-REPLANIFICATION-NON-PRETE", resultat
    secours = resultat["secours"]
    assert secours["reports_passes"] == 1, (
        "le refus oublie le report déjà inscrit : "
        f"reports_passes={secours['reports_passes']}, conseil={secours['conseil']!r}")
    assert "meteo" in secours["conseil"], (
        "le plan de secours ne nomme pas le motif du report qu'il prétend garder : "
        f"{secours['conseil']!r}")


# =========================================================================================
# A8 — l'historique suit l'heure, pas l'append ; le secours suit le plus récent
# =========================================================================================
def test_l_historique_est_ordonne_par_horodatage_et_le_secours_suit_le_dernier():
    reg, ids, _positions = _cedule._monde()
    iid = next(iter(ids.values()))
    _cedule._reussi(etats.transitionner(
        iid, "reportee", reg, "2030-06-03T09:00:00-04:00", motif="meteo"))
    _cedule._reussi(etats.transitionner(
        iid, "planifiee", reg, "2030-06-03T10:00:00-04:00"))
    _cedule._reussi(etats.transitionner(
        iid, "reportee", reg, "2030-06-02T09:00:00-04:00", motif="client_absent"))

    historique = replanification.historique_reports(reg, iid)
    heures = [entree["horodatage"] for entree in historique]
    assert heures == sorted(heures), (
        "l'historique suit l'ordre d'append, pas l'heure des reports : "
        f"{historique}")

    secours = replanification.plan_de_secours(
        {"statut": "reportee", "historique": historique, "preparation": {"a_fournir": []}}, "")
    assert "meteo" in secours["conseil"], (
        "le secours prend le dernier maillon appendé (client_absent antidaté) au lieu du report "
        f"le plus récent (meteo) : {secours['conseil']!r}")
    assert secours["reports_passes"] == 2
