"""Vecteurs fictifs du codec pur ; aucune preuve de réception fournisseur."""

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from opsys.reception_sms_runtime import valider_commande

FIXTURE = json.loads((Path(__file__).parent / "fixtures/m1_sms_ingress_v1.json").read_text())


@pytest.mark.parametrize("vecteur", FIXTURE["vecteurs"], ids=lambda v: v["nom"])
def test_vecteurs_dores(vecteur):
    assert FIXTURE["fictif"] is True
    arguments = copy.deepcopy(vecteur["arguments"])
    capture = valider_commande(arguments, operation=vecteur["operation"])
    assert capture.commande == arguments["commande"]
    assert capture.permission == arguments["permission"]
    assert capture.operation == vecteur["operation"]
    for champ, valeur in vecteur["attendu"].items():
        assert getattr(capture, champ) == valeur


def test_capture_immutable_et_sans_alias():
    vecteur = FIXTURE["vecteurs"][0]
    arguments = copy.deepcopy(vecteur["arguments"])
    capture = valider_commande(arguments, operation=vecteur["operation"])
    arguments["commande"]["texte"] = "Autre texte fictif"
    arguments["permission"]["revision_profil"] = 3
    assert capture.commande == vecteur["arguments"]["commande"]
    assert capture.permission == vecteur["arguments"]["permission"]
    with pytest.raises(FrozenInstanceError):
        capture.operation = "autre"
    with pytest.raises(TypeError):
        capture.commande["texte"] = "autre"
    with pytest.raises(TypeError):
        capture.permission["revision_profil"] = 3


def _arguments():
    return copy.deepcopy(FIXTURE["vecteurs"][0]["arguments"])


def _refuse(arguments, operation="opsys_runtime_recevoir_sms"):
    with pytest.raises(ValueError, match="^REJ-M1-SMS-COMMANDE-INVALIDE$"):
        valider_commande(arguments, operation=operation)


@pytest.mark.parametrize("chemin,valeur", [
    (("version",), True), (("version",), 1.0), (("version",), 2), (("version",), "1"),
    (("permission", "revision_profil"), True), (("permission", "revision_profil"), 0),
    (("permission", "revision_profil"), -1), (("permission", "revision_profil"), 9007199254740992),
    (("permission", "revision_profil"), 2.0), (("permission", "revision_profil"), float("nan")),
    (("permission", "profil_id"), "a"), (("permission", "profil_id"), "M1-sms"),
    (("permission", "profil_id"), "autre-fictif"),
    (("permission", "outil_m1"), "opsys_m1__autre"),
    (("commande", "canal"), "voice"), (("commande", "provider"), "autre"),
    (("commande", "compte_id"), "Default"), (("commande", "compte_id"), "_default"),
    (("commande", "compte_id"), "a" * 65), (("commande", "compte_id"), "défaut"),
    (("commande", "compte_id"), "__proto__"), (("commande", "compte_id"), "prototype"),
    (("commande", "compte_id"), "constructor"),
    (("commande", "account_sid"), "AC" + "a" * 31),
    (("commande", "account_sid"), "AC" + "g" * 32),
    (("commande", "message_sid"), "MM" + "b" * 32),
    (("commande", "message_sid"), "SM" + "b" * 33),
    (("commande", "expediteur"), "+١٥١٤٥٥٥٠١٤٢"),
    (("commande", "expediteur"), "+05145550142"),
    (("commande", "expediteur"), "+123456"),
    (("commande", "destinataire"), "+1234567890123456"),
    (("commande", "session_key"), "agent:autre:sms:direct:+15145550142"),
    (("commande", "agent_id"), "opsys-agent-autre"),
    (("commande", "preuve_sha256"), "A" * 64),
    (("commande", "preuve_sha256"), "0" * 63),
    (("commande", "texte"), ""), (("commande", "texte"), " \t\n\u00a0"),
    (("commande", "texte"), "x" * 20001), (("commande", "texte"), "é" * 10001),
    (("commande", "texte"), "\ud800"), (("commande", "texte"), None),
    (("commande", "texte"), {"secret": "fictif"}),
    (("commande", "recu_le"), "2026-02-29T12:34:56.789Z"),
    (("commande", "recu_le"), "2026-10-10T24:34:56.789Z"),
    (("commande", "recu_le"), "2026-10-10T12:34:60.789Z"),
    (("commande", "recu_le"), "2026-10-10T12:34:56Z"),
    (("commande", "recu_le"), "2026-10-10T12:34:56.7890Z"),
    (("commande", "recu_le"), "2026-10-10T12:34:56.789+00:00"),
    (("commande", "recu_le"), "2026-10-10 12:34:56.789Z"),
    (("commande", "recu_le"), "0000-10-10T12:34:56.789Z"),
    (("commande", "recu_le"), "2026-13-10T12:34:56.789Z"),
    (("commande", "recu_le"), "2026-10-10T12:34:56.789Z\n"),
])
def test_refus_champs_sans_coercition(chemin, valeur):
    arguments = _arguments()
    cible = arguments
    for cle in chemin[:-1]:
        cible = cible[cle]
    cible[chemin[-1]] = valeur
    _refuse(arguments)


@pytest.mark.parametrize("niveau", [None, "commande", "permission"])
@pytest.mark.parametrize("modification", ["extra", "manquant", "cle_non_json", "liste", "null"])
def test_formes_fermees(niveau, modification):
    arguments = _arguments()
    cible = arguments if niveau is None else arguments[niveau]
    if modification == "extra":
        cible["secret_fictif_interdit"] = "NE-PAS-RECOPIER"
    elif modification == "manquant":
        del cible[next(iter(cible))]
    elif modification == "cle_non_json":
        cible[1] = "invalide"
    else:
        remplacement = [] if modification == "liste" else None
        if niveau is None:
            arguments = remplacement
        else:
            arguments[niveau] = remplacement
    _refuse(arguments)


@pytest.mark.parametrize(
    "operation", [None, "", "opsys_runtime_recevoir_sms ", "opsys_m1__m1_recevoir_message_canal", 1],
)
def test_operation_privee_fermee(operation):
    _refuse(_arguments(), operation)


class _DictionnaireHostile(dict):
    def __getitem__(self, key):
        raise AssertionError("Ne pas exécuter un objet non JSON")

    def keys(self):
        raise AssertionError("Ne pas exécuter un objet non JSON")


class _TexteHostile(str):
    def encode(self, *args, **kwargs):
        raise AssertionError("Ne pas exécuter un objet non JSON")


@pytest.mark.parametrize("niveau", [None, "commande", "permission"])
def test_refus_sous_classes_sans_executer(niveau):
    arguments = _arguments()
    if niveau is None:
        arguments = _DictionnaireHostile(arguments)
    else:
        arguments[niveau] = _DictionnaireHostile(arguments[niveau])
    _refuse(arguments)


def test_refus_chaine_sous_classee_sans_executer():
    arguments = _arguments()
    arguments["commande"]["texte"] = _TexteHostile("texte fictif")
    _refuse(arguments)


@pytest.mark.parametrize("texte", ["x" * 20000, "😀" * 5000, "x" + "\x00" * 19999, " \nRe\u0301paration\t "])
def test_texte_limite_utf8_preserve_sans_normalisation(texte):
    arguments = _arguments()
    arguments["commande"]["texte"] = texte
    capture = valider_commande(arguments, operation="opsys_runtime_recevoir_sms")
    assert capture.commande["texte"] == texte


@pytest.mark.parametrize("date", ["2024-02-29T00:00:00.000Z", "0001-01-01T00:00:00.001Z", "9999-12-31T23:59:59.999Z"])
def test_date_valide_sans_condition_de_fraicheur(date):
    arguments = _arguments()
    arguments["commande"]["recu_le"] = date
    assert valider_commande(arguments, operation="opsys_runtime_lire_reception_sms").commande["recu_le"] == date


def test_bornes_permission_et_identifiants_verbatim():
    arguments = _arguments()
    arguments["permission"]["revision_profil"] = 9007199254740991
    arguments["commande"]["compte_id"] = "a" * 64
    arguments["commande"]["account_sid"] = "AC" + "ABcd" * 8
    arguments["commande"]["message_sid"] = "SM" + "ABcd" * 8
    capture = valider_commande(arguments, operation="opsys_runtime_recevoir_sms")
    assert capture.commande == arguments["commande"]
    assert capture.permission == arguments["permission"]


def test_rejet_entree_tres_volumineuse_sans_echo():
    arguments = _arguments()
    arguments["commande"]["texte"] = "SECRET-FICTIF" * 131072
    _refuse(arguments)
