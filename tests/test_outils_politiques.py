from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from opsys.outils import Autonomie, Outil, depuis_couple, executer, valider_arguments, vers_json
from opsys.politiques import approbation_requise

_SCHEMA = {
    "type": "object",
    "properties": {"n": {"type": "integer"}, "mode": {"type": "string", "enum": ["a", "b"]}},
    "required": ["n"],
    "additionalProperties": False,
}


def _outil(fonction, **kw):
    return Outil("m1_test", "Outil de test.", _SCHEMA, fonction, **kw)


def test_nom_invalide_refuse():
    with pytest.raises(ValueError, match="nom d'outil invalide"):
        Outil("mauvais-nom", "x", _SCHEMA, print)


def test_parametres_requis_doivent_etre_decrits():
    schema = {"type": "object", "properties": {}, "required": ["absent"]}
    with pytest.raises(ValueError, match="requis non décrits"):
        Outil("m1_test", "x", schema, print)


def test_prefixe_departement():
    assert _outil(print).departement_code == "m1"
    assert Outil("opsys_x_y", "x", {"type": "object"}, print).departement_code == "opsys"


@pytest.mark.parametrize(
    ("arguments", "attendu"),
    [
        ({"n": 1}, []),
        ({}, ["paramètre requis manquant : n"]),
        ({"n": True}, ["n : type attendu integer"]),
        ({"n": 1, "x": 2}, ["paramètre inconnu : x"]),
        ({"n": 1, "mode": "c"}, ["mode : valeur hors liste ['a', 'b']"]),
    ],
)
def test_validation_arguments(arguments, attendu):
    assert valider_arguments(_SCHEMA, arguments) == attendu


def test_vers_json_ne_perd_pas_la_precision_monetaire():
    donnees = {"montant": Decimal("10.05"), "jour": dt.date(2026, 9, 28), "liste": (1, 2)}
    assert vers_json(donnees) == {"montant": "10.05", "jour": "2026-09-28", "liste": [1, 2]}


def test_executer_enveloppes():
    ok = executer(_outil(lambda n, mode="a": {"double": n * 2}), {"n": 4})
    assert ok == {"ok": True, "resultat": {"double": 8}}

    invalide = executer(_outil(lambda n: n), {"n": "4"})
    assert invalide["erreur"] == "arguments_invalides"

    def refuse(n):
        raise ValueError("n trop grand")

    refus = executer(_outil(refuse), {"n": 99})
    assert refus == {"ok": False, "erreur": "refus_metier", "details": "n trop grand"}


def test_depuis_couple():
    assert depuis_couple(({"x": 1}, None)) == {"accepte": True, "resultat": {"x": 1}}
    assert depuis_couple((None, {"code": "REJ"})) == {"accepte": False, "verdict": {"code": "REJ"}}


@pytest.mark.parametrize(
    ("autonomie", "ombre", "supervise", "autonome"),
    [
        (Autonomie.T0, False, False, False),
        (Autonomie.T1, True, False, False),
        (Autonomie.T2, True, True, False),
        (Autonomie.T3, True, True, True),
    ],
)
def test_matrice_approbation(autonomie, ombre, supervise, autonome):
    assert approbation_requise(autonomie, "ombre") is ombre
    assert approbation_requise(autonomie, "supervise") is supervise
    assert approbation_requise(autonomie, "autonome") is autonome


def test_mode_inconnu_refuse():
    with pytest.raises(ValueError, match="mode de département inconnu"):
        approbation_requise(Autonomie.T0, "libre")
