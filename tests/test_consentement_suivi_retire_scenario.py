"""Scénario de bout en bout M4 -> bus -> M1 : le retrait du consentement de suivi atteint le sas d'envoi.

Producteur ET consommateur RÉELS : les outils de M4 (consentement par une personne dans la file N3, message d'arrivée,
retrait), le vrai bus, le vrai consommateur de M1, le vrai sas d'envoi et sa file d'approbation. Seuls le réseau et les
serveurs de courrier sont des doubles. Le lead est celui que M1 a créé d'un vrai courriel reçu ; l'intervention de M4
est inscrite pour ce même `lead_id` (la clé de contact pseudonyme que les deux départements portent). Fictif.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import cablage_qa as cq
import lea_rosalie_qa as lr
import pytest
import yaml
from m1_front_office import message_client_m4 as mc
from m4_field_ops import outils_adequation_eta as adaptateur
from m4_field_ops.outils import outils as outils_m4
from sqlalchemy import select

from opsys import approbations, identite, stockage
from opsys.courriel_connecteurs import envoi
from opsys.evenements import schemas
from opsys.stockage.schema import EVENEMENTS_SORTANTS

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "eta_m4_pour_scenario", RACINE / "departments/m04-field-ops/tests/test_outils_adequation_eta.py"
)
eta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eta)
aide = eta.aide

FICTIF = True
M1, M4 = "m01-front-office", "m04-field-ops"
CLIENT = "cliente.fictive@example.test"
RETRAIT_LE = "2030-06-01T08:00:00-04:00"
NOUVEAU_CONSENTEMENT_LE = "2030-06-01T20:00:00-04:00"
DECIDE_APRES = "2030-06-02T10:00:00+00:00"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    w = lr.monter(tmp_path, monkeypatch, (M1, M4))
    with stockage.transaction() as cnx:
        for personne, role in (("admin.fictif", "admin"), ("marie.fictif", "admin"), ("marc.fictif", "employee")):
            identite.creer_personne(cnx, personne, personne, f"mot-de-passe-{personne}-12345", [role])
    monkeypatch.setattr(approbations, "_maintenant", lambda: eta.DECIDE_LE)
    monkeypatch.setattr(adaptateur, "_parametres_adequation", lambda: json.loads(json.dumps(eta.POIDS)))
    monkeypatch.setattr(adaptateur, "_parametres_eta", lambda: dict(eta.REGLAGES_ETA))
    # M1 crée le lead d'un vrai courriel reçu ; M4 inscrit ses interventions (dont une pour CE lead).
    reponse = w.appeler(
        "m1_recevoir_message_canal",
        canal="courriel",
        expediteur=CLIENT,
        message_id="msg-1",
        recu_le="2026-10-30T14:00:00-04:00",
        texte="Bonjour, mes gouttières fuient à Laval.",
        objet="Fuite",
    )
    assert reponse.get("ok"), reponse
    lead_m1 = reponse["resultat"]["lead"]["lead_id"]
    par_nom = {o.nom: o for o in outils_m4()}
    leads = [dict(lead) for lead in aide.SCENARIO["leads"]]
    leads[0]["lead_id"] = lead_m1
    interventions = {}
    for rang, lead in enumerate(leads):
        interventions[lead["lead_id"]] = aide._inscrire(par_nom, lead, f"2030-01-01T00:00:0{rang}+00:00")
        aide._resultat(aide._confirmer(par_nom, lead))
    plan = aide._resultat(aide._proposer(par_nom, interventions))["plan_id"]
    aide._resultat(aide._appliquer(par_nom, plan))
    aide._resultat(
        aide._appeler(
            par_nom,
            "m4_confirmer_dates_cedule",
            {"plan_id": plan, "calendrier": {"0": eta.LUNDI}, "revision_attendue": 0},
            aide.ADMIN,
        )
    )
    # Le profil des équipes (semaine type) est écrit dans le dossier d'état de l'instance.
    # Le profil des équipes (semaine type) est fusionné au profil d'entreprise (la zone desservie y reste).
    (tmp_path / "equipes" / "home").mkdir(parents=True)
    eta._ecrire_profil(tmp_path / "equipes")
    equipes = yaml.safe_load((tmp_path / "equipes" / "home" / "entreprise.yaml").read_text(encoding="utf-8"))
    fichier = stockage.dossier_opsys() / "entreprise.yaml"
    existant = yaml.safe_load(fichier.read_text(encoding="utf-8")) if fichier.exists() else {}
    fichier.write_text(yaml.safe_dump({**(existant or {}), **equipes}, allow_unicode=True), encoding="utf-8")
    yield w, par_nom, interventions[lead_m1], lead_m1
    cq.demonter()


def _decider(w, par_nom, nom, arguments):
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, M4, nom, arguments, niveau=eta.Niveau.N3)
    return w.decider(demande, True, par="admin.fictif")


def _consentir(w, par_nom, iid, canal="courriel", recueilli_le="2030-05-30T10:00:00-04:00"):
    return _decider(
        w,
        par_nom,
        "m4_enregistrer_consentement_suivi_client",
        {
            "intervention_id": iid,
            "canal": canal,
            "enonce_version": "suivi-fr-CA-v1",
            "preuve": {"fictif": True, "reference": "formulaire-42"},
            "recueilli_le": recueilli_le,
        },
    )


def _preparer(par_nom, iid, canal="courriel", retards=()):
    return aide._appeler(
        par_nom, "m4_preparer_message_eta_client", eta._arguments_message(iid, canal=canal, retards=retards)
    )


def _retirer(par_nom, iid, canal="courriel", horodatage=RETRAIT_LE):
    return aide._appeler(
        par_nom,
        "m4_retirer_consentement_suivi_client",
        {"intervention_id": iid, "canal": canal, "source": "client_stop", "horodatage": horodatage},
    )


def _dernier(w):
    return list(mc._dernier_par_cle(w.registre(M1, mc.REGISTRE)).values())


def _sas(brouillon_id):
    with stockage.transaction() as cnx:
        return envoi.statut_brouillon(cnx, brouillon_id)


def _attentes(w):
    with stockage.transaction() as cnx:
        return [
            a for a in approbations.file_proprietaire(cnx, w.capacites.departements) if a["type"] == mc.TYPE_ATTENTE
        ]


def _sortants(type_evenement):
    with stockage.transaction() as cnx:
        return cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
        ).all()


def test_de_bout_en_bout_le_retrait_de_m4_neutralise_la_demande_d_envoi_ouverte_chez_m1(monde):
    w, par_nom, iid, lead = monde
    aide._resultat(
        aide._appeler(
            par_nom,
            "m4_lire_consentement_suivi_client",
            {"intervention_id": iid, "canal": "courriel", "horodatage_reference": eta.REFERENCE},
        )
    )
    assert _consentir(w, par_nom, iid)["statut"] == "executee"
    aide._resultat(_preparer(par_nom, iid))
    w.repartir()
    (message,) = _dernier(w)
    assert message["statut"] == "brouillon"
    demande = w.appeler(
        "m1_demander_envoi_courriel", brouillon_id=message["brouillon_id"], contexte="Fenêtre d'arrivée estimée"
    )["resultat"]["resultat"]["demande_id"]
    assert _sas(message["brouillon_id"])["statut"] == "DEMANDE"

    retrait = aide._resultat(_retirer(par_nom, iid))
    assert retrait["etat"] == "retire" and retrait["evenement_publie"] is True
    [ligne] = _sortants("m4.consentement_suivi_retire")
    charge = json.loads(ligne.charge)
    assert schemas.erreurs_charge("m4.consentement_suivi_retire", charge) == []
    assert charge["lead_id"] == lead and charge["intervention_id"] == iid and charge["canal"] == "courriel"
    assert (
        charge["consentement_ligne_id"] == message["consentement_ligne_id"]
    )  # le retrait vise le consentement du message
    for interdit in (CLIENT, "@", "telephone", "Client Fictif", "client_stop"):
        assert interdit not in ligne.charge

    resume = w.repartir()
    assert resume["quarantaines"] == 0 and resume["echecs"] == 0
    assert _dernier(w)[0]["statut"] == mc.STATUT_RETIRE
    assert _sas(message["brouillon_id"])["statut"] == "BROUILLON"
    (attente,) = _attentes(w)
    assert attente["id"] == demande
    assert w.decider(demande, True)["statut"] == "echec"
    assert len(w.c.monde.gmail.envoyes) == 0
    # M4 refuse de préparer un nouveau message : le retrait est effectif des deux côtés.
    assert aide._code_refus(_preparer(par_nom, iid, retards=[30])) == "REJ-ETA-CONSENTEMENT-RETIRE"


def test_de_bout_en_bout_ordre_inverse_le_brouillon_publie_avant_le_retrait_arrive_apres(monde, monkeypatch):
    w, par_nom, iid, lead = monde
    _consentir(w, par_nom, iid)
    aide._resultat(_preparer(par_nom, iid))
    aide._resultat(_retirer(par_nom, iid))
    # Le brouillon est publié avant le retrait ; une panne de M1 le fait arriver après.
    reel = mc._compte_d_envoi
    monkeypatch.setattr(mc, "_compte_d_envoi", lambda: None)
    w.repartir(passes=1)
    assert [m["type_entree"] for m in w.registre(M1, mc.REGISTRE)] == [mc.TYPE_RETRAIT]
    monkeypatch.setattr(mc, "_compte_d_envoi", reel)
    from opsys import evenements

    evenements.repartir(
        w.capacites.departements, maintenant=(dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat()
    )
    (message,) = _dernier(w)
    assert message["statut"] == mc.STATUT_RETIRE and "brouillon_id" not in message
    with stockage.transaction() as cnx:
        from opsys.stockage.schema import COURRIEL_BROUILLONS

        assert cnx.execute(select(COURRIEL_BROUILLONS)).all() == []


def test_de_bout_en_bout_un_nouveau_consentement_apres_le_retrait_est_servi_puis_un_second_retrait_le_retire(
    monde, monkeypatch
):
    w, par_nom, iid, lead = monde
    _consentir(w, par_nom, iid)
    aide._resultat(_preparer(par_nom, iid))
    aide._resultat(_retirer(par_nom, iid))
    w.repartir()
    assert [m["statut"] for m in _dernier(w)] == [mc.STATUT_RETIRE]
    # Le client consent de nouveau, APRÈS le retrait : M4 prépare un autre message, que le premier retrait ne vise pas.
    monkeypatch.setattr(approbations, "_maintenant", lambda: DECIDE_APRES)
    assert _consentir(w, par_nom, iid, recueilli_le=NOUVEAU_CONSENTEMENT_LE)["statut"] == "executee"
    aide._resultat(_preparer(par_nom, iid, retards=[45]))
    w.repartir()
    statuts = sorted(m["statut"] for m in _dernier(w))
    assert statuts == ["brouillon", mc.STATUT_RETIRE]
    nouveau = next(m for m in _dernier(w) if m["statut"] == "brouillon")
    # Un second retrait vise le nouveau consentement et le nouveau brouillon.
    aide._resultat(_retirer(par_nom, iid, horodatage="2030-06-02T08:00:00-04:00"))
    w.repartir()
    assert [m["statut"] for m in _dernier(w)] == [mc.STATUT_RETIRE, mc.STATUT_RETIRE]
    assert _sas(nouveau["brouillon_id"])["statut"] == "BROUILLON"


def test_de_bout_en_bout_le_retrait_d_un_canal_ne_touche_pas_l_autre(monde):
    w, par_nom, iid, lead = monde
    _consentir(w, par_nom, iid, canal="courriel")
    _consentir(w, par_nom, iid, canal="sms")
    aide._resultat(_preparer(par_nom, iid, canal="courriel"))
    aide._resultat(_preparer(par_nom, iid, canal="sms"))
    w.repartir()
    assert sorted(m["statut"] for m in _dernier(w)) == ["brouillon", "sms_a_reprendre"]
    aide._resultat(_retirer(par_nom, iid, canal="sms"))
    w.repartir()
    par_canal = {m["canal"]: m["statut"] for m in _dernier(w)}
    assert par_canal == {"courriel": "brouillon", "sms": mc.STATUT_RETIRE}


def test_la_panne_du_bus_a_la_publication_annule_aussi_le_retrait_de_m4(monde, monkeypatch):
    """Retrait et événement sont dans la même transaction : si la publication échoue, le retrait n'est pas posé (il
    sera redemandé), jamais un retrait que M1 ne saurait pas."""
    w, par_nom, iid, lead = monde
    _consentir(w, par_nom, iid)

    def panne(*args, **kwargs):
        raise RuntimeError("bus indisponible")

    monkeypatch.setattr(adaptateur.evenements, "publier", panne)
    with pytest.raises(RuntimeError, match="bus indisponible"):
        _retirer(par_nom, iid)
    assert [m for m in aide._maillons() if m["type_entree"] == "retrait_suivi_client"] == []
