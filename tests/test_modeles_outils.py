"""Outils M10 `m10_lire_roles_modeles` et `m10_tester_role_modele` : lecture sans secret, test borné, aucun appareil."""

from __future__ import annotations

import json

import pytest
from faux_litellm import CLE_FICTIVE
from m10_memoire import modeles_roles, outils
from modeles_aide import (
    ALIAS,
    AMONT,
    CLE_AMONT,
    PROPRIETAIRE,
    affecter,
)

from opsys import stockage
from opsys.contexte import IdentiteAppelante
from opsys.outils import Autonomie, Niveau
from opsys.roles_modeles import service
from opsys.roles_modeles.codes import ModelesErreur

FICTIF = True


def _tool(nom):
    return next(o for o in outils.outils() if o.nom == nom)


def test_declarations_niveaux_et_aucun_role_d_appareil():
    lire, tester = _tool("m10_lire_roles_modeles"), _tool("m10_tester_role_modele")
    assert (lire.autonomie, lire.niveau) == (Autonomie.T0, Niveau.N0)
    assert (tester.autonomie, tester.niveau) == (Autonomie.T1, Niveau.N2)
    assert not lire.roles_appareil and not tester.roles_appareil
    assert tester.parametres["properties"]["role"]["enum"][:3] == ["llm_rapide", "llm_fort", "llm_raisonnement"]
    assert tester.parametres["additionalProperties"] is False and lire.parametres["additionalProperties"] is False
    assert "Ne change aucun réglage" in tester.description


def test_lecture_installation_neuve_et_apres_affectation_sans_secret(pret, faux):
    with stockage.transaction():
        vue = modeles_roles.lire_roles_modeles()
    assert [r["etat"] for r in vue["roles"]] == ["inerte"] * 10
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"])
    with stockage.transaction():
        vue = modeles_roles.lire_roles_modeles()
    rapide = next(r for r in vue["roles"] if r["role"] == "llm_rapide")
    assert rapide["etat"] == "actif" and rapide["fournisseur"] == "llm.passerelle.opsys-haiku-5-5"
    assert rapide["mesure"] == "non mesuré" and rapide["connexion_testee"] is False
    assert vue["raisonnement_actif"] is False and vue["passerelle"]["configuree"] is True
    assert vue["politique_economie"]["classes"]["classification"] == "llm_rapide"
    assert vue["politique_economie"]["statut"] == "recommandation_non_validee"
    texte = json.dumps(vue)
    assert CLE_FICTIVE not in texte and CLE_AMONT not in texte and "secret_cle" not in texte


def test_test_par_un_agent_est_borne_et_rate_limite(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    with stockage.transaction():
        r = modeles_roles.tester_role_modele("llm_rapide")
    assert r["mesure"]["statut"] == "succes" and faux.appels_modele("opsys-haiku-5-5")[0]["max_tokens"] == 8
    with pytest.raises(ModelesErreur) as exc, stockage.transaction():
        modeles_roles.tester_role_modele("llm_rapide")  # une minute entre deux tests
    assert exc.value.code == "REJ-MODELES-APPEL-REFUSE" and len(faux.appels_modele("opsys-haiku-5-5")) == 1


def test_un_agent_ne_teste_jamais_le_raisonnement_ni_un_role_inconnu(pret, faux):
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    with pret() as cnx:
        service.appliquer(
            cnx,
            acteur=PROPRIETAIRE,
            operation=service.OP_RAISONNEMENT_ACTIVER,
            niveau_confirme="N3",
            parametres={},
            motif="Analyse contractuelle complexe du dossier fictif",
        )
    with pytest.raises(ModelesErreur) as exc, stockage.transaction():
        modeles_roles.tester_role_modele("llm_raisonnement")
    assert exc.value.code == "REJ-MODELES-ESCALADE-REFUSEE" and faux.appels_modele("opsys-opus-5-5") == []
    with pytest.raises(ModelesErreur) as exc, stockage.transaction():
        modeles_roles.tester_role_modele("llm_geant")
    assert exc.value.code == "REJ-MODELES-ROLE-INCONNU"


def test_un_appareil_est_refuse(pret, monkeypatch):
    identite = IdentiteAppelante.__new__(IdentiteAppelante)
    monkeypatch.setattr(modeles_roles, "identite_appelante", lambda: identite)
    with pytest.raises(ModelesErreur) as exc, stockage.transaction():
        modeles_roles.lire_roles_modeles()
    assert exc.value.code == "REJ-MODELES-ADMIN-REQUIS"
    with pytest.raises(ModelesErreur), stockage.transaction():
        modeles_roles.tester_role_modele("llm_rapide")


def test_lecture_hors_transaction_est_refusee():
    with pytest.raises(ModelesErreur):
        modeles_roles.lire_roles_modeles()
