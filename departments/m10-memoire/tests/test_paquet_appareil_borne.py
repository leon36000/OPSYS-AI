"""Identités fictives : rôle courant et enveloppe de lecture avant tout registre M10."""
from unittest.mock import Mock

import pytest
from m10_memoire import outils as module

from opsys import contexte, identite, stockage
from opsys.contexte import IdentiteAppelante
from opsys.outils import executer_atomique

FICTIF = True
ARGS = {"affaire_id": "affaire-fictive", "horodatage": "2026-10-08T08:00:00-04:00"}


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm10-identites-fictives.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(identite, "hacher_mot_de_passe", lambda _: "fictif-non-authentifiable")
    with stockage.transaction() as cnx:
        for personne, role, actif in [
            ("admin.fictif", "admin", True), ("employe.fictif", "employee", True),
            ("vendeur.fictif", "seller", True), ("ancien.fictif", "admin", False),
        ]:
            identite.creer_personne(cnx, personne, personne, "fictif-mot-de-passe", [role], actif=actif)
    yield
    stockage.liberer()


@pytest.fixture
def outil():
    return next(o for o in module.outils() if o.nom == "m10_lire_paquet_affaire_appareil")


@pytest.mark.parametrize("appelante", [
    IdentiteAppelante("employe.fictif", "employee"), IdentiteAppelante("vendeur.fictif", "seller"),
    IdentiteAppelante("employe.fictif", "admin"), IdentiteAppelante("ancien.fictif", "admin"),
    IdentiteAppelante("inconnu.fictif", "admin"), IdentiteAppelante("admin.fictif", "employee"),
])
def test_refuse_avant_assemblage_et_registres(base, outil, monkeypatch, appelante):
    assemble = Mock(side_effect=AssertionError("paquet lu avant validation du rôle"))
    monkeypatch.setattr(module.paquets, "assembler_paquet_contexte", assemble)
    with contexte.appele_par_appareil(appelante):
        r = executer_atomique(outil, ARGS)
    assert r["ok"] is True and r["resultat"]["accepte"] is False, r
    assert r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assemble.assert_not_called()


def test_revoque_ancien_jeton_avant_lecture(base, outil, monkeypatch):
    assemble = Mock(side_effect=AssertionError("lecture après révocation"))
    monkeypatch.setattr(module.paquets, "assembler_paquet_contexte", assemble)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        r = executer_atomique(outil, ARGS)
    assert r["ok"] is True and r["resultat"]["accepte"] is False, r
    assert r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assemble.assert_not_called()


def test_appareil_hors_transaction_refuse(base, monkeypatch):
    assemble = Mock(side_effect=AssertionError("lecture hors transaction"))
    monkeypatch.setattr(module.paquets, "assembler_paquet_contexte", assemble)
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        r = module.lire_paquet_affaire_appareil(**ARGS)
    assert r["accepte"] is False and r["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assemble.assert_not_called()


@pytest.mark.parametrize("origine", ["m01-front-office", "m02-revenue-crm", "m10-memoire"])
def test_vue_appareil_restrictive_independamment_de_origine_fiable(base, outil, origine):
    with (
        contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")),
        contexte.appeler_en_tant_que("m10-memoire", origine=origine),
    ):
        r = executer_atomique(outil, ARGS)
    assert r["ok"] is True, r
    assert r["resultat"]["confidentialite"]["agent"] is None
    assert [c["nom"] for c in r["resultat"]["couches"]] == [
        "regles_entreprise", "faits_affaire", "evenements_recents", "signaux_non_resolus",
    ]


@pytest.mark.parametrize("origine", ["m01-front-office", "m02-revenue-crm"])
def test_origine_agents_legitimes_preservee(base, origine):
    outil = next(o for o in module.outils() if o.nom == "m10_paquet_contexte_affaire")
    with contexte.appeler_en_tant_que("m10-memoire", origine=origine):
        r = executer_atomique(outil, ARGS)
    assert r["ok"] is True, r
    assert r["resultat"]["confidentialite"]["agent"] == origine


def test_paquet_oversized_refuse_avant_fallback_artefact(base, outil, monkeypatch):
    # Injection explicitement synthétique pour la garde de sortie, pas une capture métier.
    assemble = Mock(return_value={"fictif": True, "resume": "X" * 7000})
    monkeypatch.setattr(module.paquets, "assembler_paquet_contexte", assemble)
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        r = executer_atomique(outil, ARGS)
    assert r["ok"] is True and r["resultat"]["accepte"] is False, r
    assert r["resultat"]["verdict"]["code"] == "REJ-PAQUET-AFFAIRE-SORTIE-TROP-VOLUMINEUSE"
    assemble.assert_called_once()


@pytest.mark.parametrize("origine", [None, "m01-front-office", "m02-revenue-crm"])
def test_facade_exige_identite_appareil_meme_pour_agent(base, outil, monkeypatch, origine):
    assemble = Mock(side_effect=AssertionError("lecture sans identité appareil"))
    monkeypatch.setattr(module.paquets, "assembler_paquet_contexte", assemble)
    with contexte.appeler_en_tant_que("m10-memoire", origine=origine):
        r = executer_atomique(outil, ARGS)
    assert r["ok"] is True and r["resultat"]["accepte"] is False, r
    assert r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assemble.assert_not_called()
