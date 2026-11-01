"""Consentement de suivi du client (Loi 25) et enregistrements d'arrivée estimée (M4.14). Module pur. Données
fictives."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m4_field_ops import suivi_client as sc  # noqa: E402

FICTIF = True
EDT = timezone(timedelta(hours=-4))


def _t(jour, h=9, m=0, mois=6):
    return datetime(2030, mois, jour, h, m, tzinfo=EDT).isoformat()


def _consentement(maillons=(), **plus):
    args = dict(
        intervention_id="int-1",
        lead_id="lead-1",
        canal="sms",
        enonce_version="suivi-fr-CA-v1",
        preuve={"fictif": True, "reference": "formulaire-42"},
        recueilli_le=_t(3),
        recueilli_par="vendeur.fictif",
        approbation_ref="appr-1",
        enregistre_le=_t(3, 9, 5),
        validite_jours=7,
        maillons=list(maillons),
    )
    args.update(plus)
    return sc.construire_consentement(**args)


def _avec_ligne_id(maillon, n):
    return {**maillon, "ligne_id": f"l{n}"}


def test_un_consentement_valide_porte_qui_quand_quoi_et_jusqu_a_quand_sans_contact_ni_position():
    maillon, verdict = _consentement()
    assert verdict is None
    assert maillon["type_entree"] == sc.TYPE_CONSENTEMENT and maillon["finalite"] == "fenetre_arrivee"
    assert maillon["recueilli_par"] == "vendeur.fictif" and maillon["approbation_ref"] == "appr-1"
    assert maillon["valide_jusqu_au"] == _t(10, 9, 5) and maillon["horodatage"] == _t(3, 9, 5)
    texte = str(maillon).lower()
    for interdit in ("latitude", "longitude", "telephone", "courriel@", "@", "adresse", "nom_client"):
        assert interdit not in texte
    assert set(maillon["preuve"]) == {"fictif", "reference"}


def test_actif_puis_expire_exactement_a_la_borne():
    maillon, _ = _consentement()
    maillons = [_avec_ligne_id(maillon, 1)]
    avant = sc.etat_du_consentement(maillons, "int-1", "sms", datetime.fromisoformat(_t(10, 9, 4)))
    assert avant["etat"] == "actif" and avant["lead_id"] == "lead-1" and avant["ligne_id"] == "l1"
    pile = sc.etat_du_consentement(maillons, "int-1", "sms", datetime.fromisoformat(_t(10, 9, 5)))
    assert pile["etat"] == "expire" and pile["valide_jusqu_au"] == _t(10, 9, 5)
    apres = sc.etat_du_consentement(maillons, "int-1", "sms", datetime.fromisoformat(_t(20)))
    assert apres["etat"] == "expire"


def test_absent_pour_un_autre_chantier_ou_un_autre_canal():
    maillon, _ = _consentement()
    maillons = [_avec_ligne_id(maillon, 1)]
    ref = datetime.fromisoformat(_t(4))
    assert sc.etat_du_consentement(maillons, "int-2", "sms", ref)["etat"] == "absent"
    assert sc.etat_du_consentement(maillons, "int-1", "courriel", ref)["etat"] == "absent"
    assert sc.etat_du_consentement([], "int-1", "sms", ref)["etat"] == "absent"


def test_un_retrait_est_effectif_tout_de_suite_et_le_dernier_fait_gagne():
    consent, _ = _consentement()
    retrait, verdict = sc.construire_retrait(
        intervention_id="int-1", canal="sms", source="client_stop", retire_le=_t(4, 10)
    )
    assert verdict is None and retrait["type_entree"] == sc.TYPE_RETRAIT and retrait["finalite"] == "fenetre_arrivee"
    maillons = [_avec_ligne_id(consent, 1), _avec_ligne_id(retrait, 2)]
    etat = sc.etat_du_consentement(maillons, "int-1", "sms", datetime.fromisoformat(_t(4, 10)))
    assert etat["etat"] == "retire" and etat["source"] == "client_stop" and etat["retire_le"] == _t(4, 10)
    # le retrait d'un canal ne touche pas l'autre
    autre, _ = _consentement(canal="courriel")
    mixte = maillons + [_avec_ligne_id(autre, 3)]
    assert sc.etat_du_consentement(mixte, "int-1", "courriel", datetime.fromisoformat(_t(4)))["etat"] == "actif"
    assert sc.etat_du_consentement(mixte, "int-1", "sms", datetime.fromisoformat(_t(4)))["etat"] == "retire"


def test_un_consentement_anterieur_ou_egal_a_un_retrait_ne_le_leve_pas():
    consent, _ = _consentement()
    retrait, _ = sc.construire_retrait(
        intervention_id="int-1", canal="sms", source="client_demande", retire_le=_t(5, 10)
    )
    maillons = [_avec_ligne_id(consent, 1), _avec_ligne_id(retrait, 2)]
    for recueilli in (_t(5, 9), _t(5, 10)):  # avant ou à l'instant même du retrait
        nouveau, verdict = _consentement(maillons, recueilli_le=recueilli, enregistre_le=_t(5, 11))
        assert (
            nouveau is None and verdict["code"] == "REJ-SUIVI-CONSENTEMENT-INVALIDE" and "retrait" in verdict["detail"]
        )
    # après : le client consent de nouveau
    ok, verdict = _consentement(maillons, recueilli_le=_t(5, 10, 1), enregistre_le=_t(5, 11))
    assert verdict is None
    relevee = maillons + [_avec_ligne_id(ok, 3)]
    assert sc.etat_du_consentement(relevee, "int-1", "sms", datetime.fromisoformat(_t(5, 12)))["etat"] == "actif"


@pytest.mark.parametrize(
    "modif",
    [
        {"canal": "pigeon"},
        {"canal": None},
        {"intervention_id": ""},
        {"intervention_id": "a b"},
        {"lead_id": 3},
        {"enonce_version": "v 1"},
        {"enonce_version": ""},
        {"recueilli_par": ""},
        {"approbation_ref": "a b"},
        {"preuve": {"fictif": True}},
        {"preuve": {"fictif": "oui", "reference": "x"}},
        {"preuve": {"fictif": True, "reference": "x y"}},
        {"preuve": {"fictif": True, "reference": "x", "document": "contenu"}},
        {"preuve": "formulaire"},
        {"recueilli_le": "hier"},
        {"recueilli_le": "2030-06-03T09:00:00"},
        {"enregistre_le": "2030-06-03T09:05:00"},
        {"recueilli_le": _t(4), "enregistre_le": _t(3)},  # recueilli après l'enregistrement
        {"validite_jours": 0},
        {"validite_jours": 31},
        {"validite_jours": True},
        {"validite_jours": 1.5},
    ],
)
def test_consentement_mal_forme_refuse_sans_rien_construire(modif):
    maillon, verdict = _consentement(**modif)
    assert maillon is None and verdict["code"] == "REJ-SUIVI-CONSENTEMENT-INVALIDE"


def test_la_validite_ne_depasse_jamais_le_plafond_du_code():
    maillon, verdict = _consentement(validite_jours=sc.VALIDITE_MAX_JOURS)
    assert (
        verdict is None
        and maillon["valide_jusqu_au"]
        == (datetime.fromisoformat(_t(3, 9, 5)) + timedelta(days=sc.VALIDITE_MAX_JOURS)).isoformat()
    )
    assert _consentement(validite_jours=sc.VALIDITE_MAX_JOURS + 1)[1] is not None


@pytest.mark.parametrize(
    "modif",
    [
        {"canal": "x"},
        {"source": "inconnue"},
        {"intervention_id": ""},
        {"retire_le": "hier"},
        {"retire_le": "2030-06-03T09:00:00"},
    ],
)
def test_retrait_mal_forme_refuse(modif):
    args = dict(intervention_id="int-1", canal="sms", source="client_stop", retire_le=_t(4))
    args.update(modif)
    maillon, verdict = sc.construire_retrait(**args)
    assert maillon is None and verdict["code"] == "REJ-SUIVI-CONSENTEMENT-INVALIDE"


def test_un_consentement_dont_la_date_de_fin_est_alteree_est_traite_comme_expire():
    maillon, _ = _consentement()
    maillon = {**maillon, "valide_jusqu_au": "n'importe quoi", "ligne_id": "l1"}
    assert sc.etat_du_consentement([maillon], "int-1", "sms", datetime.fromisoformat(_t(4)))["etat"] == "expire"


def test_enregistrement_d_arrivee_estimee_borne_sa_conservation_et_ne_garde_aucune_position():
    fenetre = {"debut": _t(4, 9), "fin": _t(4, 10)}
    entree = sc.construire_enregistrement_eta(
        intervention_id="int-1",
        canal="sms",
        fenetre=fenetre,
        message_empreinte="a" * 64,
        consentement_ligne_id="l1",
        prepare_le=_t(4, 8),
        conservation_heures=48,
    )
    assert entree["type_entree"] == sc.TYPE_ETA and entree["conserve_jusqu_au"] == _t(6, 10)
    assert set(entree) == {
        "type_entree",
        "horodatage",
        "intervention_id",
        "canal",
        "fenetre_debut",
        "fenetre_fin",
        "message_empreinte",
        "consentement_ligne_id",
        "conserve_jusqu_au",
    }
    # préparé APRÈS la fin de la fenêtre (rejeu tardif) : la conservation part de l'instant le plus tardif
    tardif = sc.construire_enregistrement_eta(
        intervention_id="int-1",
        canal="sms",
        fenetre=fenetre,
        message_empreinte="a" * 64,
        consentement_ligne_id=None,
        prepare_le=_t(4, 12),
        conservation_heures=1,
    )
    assert tardif["conserve_jusqu_au"] == _t(4, 13)
    with pytest.raises(ValueError):
        sc.construire_enregistrement_eta(
            intervention_id="int-1",
            canal="sms",
            fenetre=fenetre,
            message_empreinte="pas-un-sha",
            consentement_ligne_id=None,
            prepare_le=_t(4, 8),
            conservation_heures=1,
        )


def test_le_compte_des_messages_prepares_est_par_chantier_et_par_canal():
    fenetre = {"debut": _t(4, 9), "fin": _t(4, 10)}
    base = dict(
        fenetre=fenetre,
        message_empreinte="b" * 64,
        consentement_ligne_id=None,
        prepare_le=_t(4, 8),
        conservation_heures=1,
    )
    maillons = [
        sc.construire_enregistrement_eta(intervention_id="int-1", canal="sms", **base),
        sc.construire_enregistrement_eta(intervention_id="int-1", canal="sms", **base),
        sc.construire_enregistrement_eta(intervention_id="int-1", canal="courriel", **base),
        sc.construire_enregistrement_eta(intervention_id="int-2", canal="sms", **base),
    ]
    assert sc.compter_messages(maillons, "int-1", "sms") == 2
    assert (
        sc.compter_messages(maillons, "int-1", "courriel") == 1 and sc.compter_messages(maillons, "int-9", "sms") == 0
    )


def test_construire_ne_modifie_pas_les_maillons_fournis():
    maillon, _ = _consentement()
    maillons = [_avec_ligne_id(maillon, 1)]
    avant = copy.deepcopy(maillons)
    _consentement(maillons, recueilli_le=_t(5), enregistre_le=_t(5, 9, 5))
    assert maillons == avant
