"""Raccord M9 -> M1 : `m1.plaintes_structurees` du VRAI M1 (registre durable, vocabulaire des plaintes), port privé.

M1 est alimenté par sa propre réception de messages (`recevoir_message_canal`) et par la configuration de vocabulaire de
ses fixtures fictives ; M9 capture ensuite la lecture par le port privé `opsys.lecteurs_m9` (admin console).
Données fictives
(numéros en 555, vocabulaire `fictif: true`)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml
from m1_front_office import outils as m1
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import dossier_strategique as ds

from opsys import taxonomie
from opsys.contexte import IdentiteAppelante

RACINE = Path(__file__).resolve().parents[1]


def _charger_aide():
    spec = importlib.util.spec_from_file_location("m9_producteurs_b", Path(__file__).with_name("m9_producteurs_b.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


H = _charger_aide()
FICTIF = True
LECTURE = "m1.plaintes_structurees"
JOUR = "2031-01-15"
ARGS = {"date_reference": JOUR, "jours": 7}
DEBUT = dt.datetime(2031, 1, 15, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
CORPUS = yaml.safe_load((RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml").read_text("utf-8"))
RECU = "2031-01-15T23:00:00Z"
FACTS = f"{LECTURE}#0:p0.resultat.resultat"


@pytest.fixture
def base(tmp_path, monkeypatch):
    H.installer_base(tmp_path, monkeypatch)
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    yield tmp_path
    H.desinstaller_base()


def _vocabulaire():
    assert CORPUS["fictif"] is True
    taxonomie.enregistrer_signaux_plainte(CORPUS["signaux_plainte"])


def _sms(texte, message_id, minutes, numero):
    reponse = m1.recevoir_message_canal(
        canal="sms", expediteur=numero, message_id=message_id,
        recu_le=(DEBUT + dt.timedelta(minutes=minutes)).isoformat(), texte=texte)  # fmt: skip
    return reponse


def _capture(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["capture"]


def _dossier(captures, connaissance="2031-01-16T00:00:00Z"):
    return ds.construire(captures, question="Où en sont les plaintes ?", domaines=["plaintes"],
                         reference="2031-01-15T23:00:00Z", connaissance=connaissance, attendues=[LECTURE])  # fmt: skip


def test_m1_sans_vocabulaire_reel_est_non_branchee_comptes_nuls_jamais_zero(base):
    _sms("Je suis très déçu : vos gars ont abîmé ma gouttière.", "SM-1", 0, "+15145550101")
    capture = _capture(H.capturer(H.capacites(H.M1), H.ADMIN, LECTURE, dict(ARGS), RECU))
    assert (capture["verdict"], capture["complete"]) == ("ACCEPTEE", False)
    charge = H.page(0)["resultat"]["resultat"]
    assert charge["etat"] == "NON_BRANCHEE" and charge["comptes"]["declarees"] is None
    dossier = _dossier(H.captures_stockees())
    assert dossier["faits"][f"{FACTS}.etat"] == "NON_BRANCHEE"
    assert not [a for a in dossier["faits"] if ".comptes." in a] and "0" not in dossier["faits"].values()
    assert dossier["couverture"]["lectures"][0]["statut"] == "PARTIELLE"


def test_m1_aucune_declaree_reel_se_cite_comme_etat_jamais_comme_zero_plainte(base):
    _vocabulaire()
    _sms("Bonjour, je veux une soumission pour des gouttières à Laval.", "SM-1", 0, "+15145550102")
    capture = _capture(H.capturer(H.capacites(H.M1), H.ADMIN, LECTURE, dict(ARGS), RECU))
    assert (capture["verdict"], capture["complete"]) == ("ACCEPTEE", True)
    charge = H.page(0)["resultat"]["resultat"]
    assert charge["etat"] == "AUCUNE_DECLAREE_PAR_SOURCE" and charge["comptes"]["declarees"] == 0
    dossier = _dossier(H.captures_stockees())
    assert dossier["faits"][f"{FACTS}.etat"] == "AUCUNE_DECLAREE_PAR_SOURCE"
    assert not [a for a in dossier["faits"] if ".comptes." in a] and "0" not in dossier["faits"].values()


def test_m1_connue_reel_donne_des_comptes_citables_sans_pseudonyme_ni_zero(base):
    _vocabulaire()
    _sms("Je suis très déçu : vos gars ont abîmé ma gouttière.", "SM-1", 0, "+15145550103")
    _sms("Danger : un fil électrique pend sur le balcon, j'ai peur.", "SM-2", 10, "+15145550104")
    _sms("Bonjour, je veux une soumission pour des gouttières à Laval.", "SM-3", 20, "+15145550105")
    capture = _capture(H.capturer(H.capacites(H.M1), H.ADMIN, LECTURE, dict(ARGS), RECU))
    assert (capture["verdict"], capture["complete"]) == ("ACCEPTEE", True) and capture["instants_metier"]["nombre"] == 2
    dossier = _dossier(H.captures_stockees())
    assert dossier["faits"][f"{FACTS}.etat"] == "CONNUE" and dossier["faits"][f"{FACTS}.comptes.declarees"] == "2"
    assert dossier["faits"][f"{FACTS}.comptes.par_type.urgence"] == "1"
    assert not [a for a in dossier["faits"] if "plaintes[" in a or "revision" in a]
    assert "pl-" not in "".join(dossier["faits"].values()) and "0" not in dossier["faits"].values()
    assert dossier["couverture"]["lectures"][0]["statut"] == "PRESENTE"


def test_m1_contradiction_reelle_signalee_et_simple_rafraichissement_non_signale(base):
    _vocabulaire()
    cap = H.capacites(H.M1)
    _sms("Je suis très déçu : vos gars ont abîmé ma gouttière.", "SM-1", 0, "+15145550106")
    _capture(H.capturer(cap, H.ADMIN, LECTURE, dict(ARGS), "2031-01-15T23:00:00Z"))
    # Rafraîchissement : un message sans plainte change la tête du registre, pas le contenu de la période lue.
    _sms("Bonjour, je veux une soumission pour des gouttières à Laval.", "SM-2", 30, "+15145550107")
    _capture(H.capturer(cap, H.ADMIN, LECTURE, dict(ARGS), "2031-01-15T23:10:00Z"))
    chaine = H.captures_stockees()
    premiere, seconde = (c["pages"][0]["resultat"]["resultat"]["revision"] for c in chaine)
    assert (
        premiere["empreinte_contenu"] == seconde["empreinte_contenu"]
        and premiere["registre_tete"] != seconde["registre_tete"]
    )
    assert cs.contradictions(chaine) == []
    # Contradiction : une plainte arrive tardivement pour la même période déjà lue ; chaque lecture garde sa vérité.
    _sms("Danger : un fil électrique pend sur le balcon, j'ai peur.", "SM-3", 40, "+15145550108")
    _capture(H.capturer(cap, H.ADMIN, LECTURE, dict(ARGS), "2031-01-15T23:20:00Z"))
    chaine = H.captures_stockees()
    conflits = cs.contradictions(chaine)
    assert {(c["index_a"], c["index_b"]) for c in conflits} == {(0, 2), (1, 2)}
    assert all(c["regle"] == cs.REGLE_CONTRADICTION_CONTENU for c in conflits)
    dossier = _dossier(chaine, connaissance="2031-01-16T12:00:00Z")
    assert dossier["couverture"]["lectures"][0]["statut"] == "CONTRADICTOIRE" and dossier["faits"] == {}


@pytest.mark.parametrize(
    "identite",
    [
        None,
        IdentiteAppelante("vendeur.fictif", "seller", source="console"),
        IdentiteAppelante("employe.fictif", "employee", source="console"),
        IdentiteAppelante("ancien.admin", "admin", source="console"),
    ],
)
def test_m1_refus_d_identite_avant_toute_lecture(base, identite):
    reponse = H.capturer(H.capacites(H.M1), identite, LECTURE, dict(ARGS), RECU)
    assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    assert H.captures_stockees() == []


def test_m1_arguments_hors_catalogue_et_periode_invalide(base):
    cap = H.capacites(H.M1)
    assert H.capturer(cap, H.ADMIN, LECTURE, {**ARGS, "role": "admin"}, RECU)["ok"] is False
    invalide = _capture(H.capturer(cap, H.ADMIN, LECTURE, {"date_reference": JOUR, "jours": 400}, RECU))
    assert invalide["verdict"] in {"REFUSEE", "ERREUR"} and invalide["complete"] is False
    assert _dossier(H.captures_stockees())["faits"] == {}
