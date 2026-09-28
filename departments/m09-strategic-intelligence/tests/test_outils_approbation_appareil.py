"""Les deux outils d'approbation de l'app du propriétaire (PLAN T1.4-f, étape 6) : leur déclaration.

La logique (identité, plafond N3/N4, N5 jamais, rejeu, trace) est celle de `opsys.approbations_appareil` et se
prouve dans `tests/test_approbations_appareil.py` du socle, par ces mêmes outils. Ici : ce que M9 déclare.
"""

from __future__ import annotations

import pytest
from m9_strategic_intelligence.outils import outils
from m9_strategic_intelligence.registre import RegistreSnapshots

from opsys.outils import Autonomie, Niveau, executer

LISTER = "m9_lister_demandes_approbation"
DECIDER = "m9_decider_demande_approbation"


@pytest.fixture(scope="module")
def par_nom():
    return {o.nom: o for o in outils(RegistreSnapshots(), alertes_cible=[])}


def test_liste_lecture_pure_et_decision_n2_pas_le_n3_par_defaut(par_nom):
    assert par_nom[LISTER].autonomie is Autonomie.T0
    assert par_nom[LISTER].niveau_effectif is Niveau.N0
    # T1 (écriture interne) mais N2 : l'outil EST la décision humaine, jamais lui-même mis en attente.
    assert par_nom[DECIDER].autonomie is Autonomie.T1
    assert par_nom[DECIDER].niveau_effectif is Niveau.N2


def test_admin_seulement_et_jamais_une_frontiere_humaine(par_nom):
    for nom in (LISTER, DECIDER):
        assert par_nom[nom].roles_appareil == frozenset({"admin"})
        assert par_nom[nom].frontiere_humaine is False


@pytest.mark.parametrize("nom", [LISTER, DECIDER])
def test_aucun_parametre_ne_designe_le_decideur_et_les_parametres_inconnus_sont_refuses(par_nom, nom):
    schema = par_nom[nom].parametres
    assert schema["additionalProperties"] is False
    for interdit in ("personne", "identifiant", "role", "decide_par", "appareil", "par", "utilisateur"):
        assert interdit not in schema["properties"]
    reponse = executer(par_nom[nom], {"personne": "quelqu-un"})
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"


def test_la_decision_n_offre_que_les_deux_decisions_de_la_console(par_nom):
    schema = par_nom[DECIDER].parametres
    assert schema["properties"]["decision"]["enum"] == ["approuver", "refuser"]
    assert schema["required"] == ["demande_id", "decision"]
    assert set(schema["properties"]) == {"demande_id", "decision", "motif"}


def test_les_outils_de_l_agent_m9_ne_sont_pas_touches(par_nom):
    """Les six outils d'avant restent tels quels : ni portée ni niveau modifiés."""
    assert par_nom["m9_etat_consolide"].roles_appareil == frozenset()
    assert par_nom["m9_produire_briefing_matin"].roles_appareil == frozenset({"admin"})
