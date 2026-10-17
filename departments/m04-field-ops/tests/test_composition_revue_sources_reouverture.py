"""R3, composition (hypothèse, pas un bug affirmé) : une vraie proposition N4 de revue de complétion est en attente,
le classement de sa source est corrigé durablement, le stockage et `Capacites` sont rouverts, puis Nathan — dont les
droits restent valides — décide. Il ne doit pas vérifier sur des sources remplacées ; une proposition fraîche, elle,
doit aboutir.

Réutilise le monde SQLite natif de `test_revue_completion_sources.py` (producteurs M4/M6 et publications réelles,
classements par l'API canonique M6) et le patron de `tests/test_revue_completion_sources_atomique.py`, ici composé
dans une seule chaîne avec réouverture et positif frais. Contexte DEVICE injecté : aucun Gateway, aucune provenance
humaine réelle. La décision refusée laisse un audit légitime (demande `echec`, journal, réclamation) ; seules les
tables d'affaires servent d'oracle métier. Fictif.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from m4_field_ops import registre as registre_m4
from sqlalchemy import select

from opsys import approbations, contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "fixture_m4_revue_sources_r3", Path(__file__).with_name("test_revue_completion_sources.py"))
_fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fx)
monde = _fx.monde
sqlfx = _fx.sqlfx
PROPOSITION = _fx.ECRIRE
LECTURE = _fx.LIRE
DECIDER = "m9_decider_demande_approbation"
NATHAN = contexte.IdentiteAppelante("nathan", "admin", source="appareil")
PERIMEES = "REJ-M4-REVUE-SOURCES-PERIMEES"


def _cap():
    return Capacites(charger_departements(RACINE_DEPARTEMENTS), stockage.transaction, limite_sortie=5400)


def _appeler(cap, appelante, nom, arguments, cle=None, appareil=None):
    meta = None if cle is None else idempotence.Meta(cle, appareil, _fx.DATE)
    with contexte.appele_par_appareil(appelante):
        return cap.appeler(nom, arguments, meta=meta)


def _dossier(cap, iid):
    lecture = _appeler(cap, sqlfx.ADMIN, LECTURE, {"intervention_id": iid, "demande_id": None})
    assert lecture["ok"] and lecture["resultat"]["accepte"], lecture
    return lecture["resultat"]["resultat"]


def _proposer(cap, iid, sources, cle):
    arguments = {"intervention_id": iid, "decision": "verifiee", "horodatage": _fx.DATE,
                 "motif": "FICTIF : revue de complétion", "sources": sources}
    proposition = _appeler(cap, sqlfx.ADMIN, PROPOSITION, arguments, cle, "APP-P-R3-FICTIF")
    assert proposition["ok"] and proposition["statut"] == "en_attente_approbation", proposition
    return arguments, proposition


def _decider(cap, demande_id, cle):
    return _appeler(cap, NATHAN, DECIDER, {"demande_id": demande_id, "decision": "approuver"}, cle, "APP-D-R3-FICTIF")


def _nathan_valide():
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, NATHAN.personne)
        assert personne is not None and {"admin", "nathan_owner"} <= personne.roles
        assert approbations.signataire_valide(cnx, NATHAN) == NATHAN


def _affaires():
    with stockage.transaction() as cnx:
        return {t.name: [dict(r) for r in cnx.execute(select(t).order_by(*t.primary_key.columns)).mappings()]
                for t in (REGISTRES, EVENEMENTS_SORTANTS)}


def _maillons_m4():
    return [r for r in _affaires()["registres_maillons"] if r["departement"] == "m04-field-ops"]


def _demande(ident):
    with stockage.transaction() as cnx:
        return dict(cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == ident)).mappings().one())


def test_sources_corrigees_apres_proposition_puis_reouverture_nathan_refuse_perime_puis_frais_aboutit(monde):
    a = sqlfx.preparer()
    premier = sqlfx.executer(sqlfx.ECRIRE, sqlfx.demande(a))["resultat"]
    assert premier["accepte"], premier
    iid = a["formulaire"]["intervention_id"]
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, NATHAN.personne, "Nathan fictif", "mot-de-passe-fictif-12345",
                               ["admin", "nathan_owner"])
    cap = _cap()
    sources_1 = _dossier(cap, iid)["sources"]
    _, p1 = _proposer(cap, iid, sources_1, "P1-R3-FICTIF")

    # Correction durable du MÊME classement, par l'API canonique M6, avec motif, après la proposition.
    reference_1 = sources_1["classements"][0]["reference"]
    correction = sqlfx.executer(sqlfx.ECRIRE, {
        "selection": {"wct_id": sources_1["wct_id"], "reference_variance": sources_1["reference_variance"],
                      "position_ligne": 0, "materiau_id": sources_1["classements"][0]["materiau_id"]},
        "cause": "breakage", "motif": "FICTIF : correction durable après proposition",
        "classement_attendu": reference_1, "references_pieces": [],
    })["resultat"]
    assert correction["accepte"], correction
    assert correction["resultat"]["reference"] != reference_1

    # Réouverture du pool et d'une Capacites neuve avant la décision.
    moteur_avant = stockage.moteur()
    stockage.liberer()
    cap = _cap()
    assert stockage.moteur() is not moteur_avant
    _nathan_valide()

    tables_avant, affaires_avant = sqlfx.fx.fx._tables(), _affaires()
    d1 = _decider(cap, p1["demande_id"], "D1-R3-FICTIF")
    assert d1["ok"] is True and d1["rejoue"] is False, d1
    decision_1 = d1["resultat"]["resultat"]
    assert decision_1["statut"] == "echec" and decision_1["preuve_completion"] is None, decision_1
    assert decision_1["decide_par"] == NATHAN.personne, "refus métier, pas un refus d'identité ou de montage"
    demande_1 = _demande(p1["demande_id"])
    assert (demande_1["statut"], demande_1["decide_par"], demande_1["decide_role"]) == (
        "echec", NATHAN.personne, "nathan_owner")
    verdict_1 = json.loads(demande_1["resultat"])["resultat"]["verdict"]
    assert verdict_1["code"] == PERIMEES, verdict_1
    assert _affaires() == affaires_avant, "aucun maillon de résolution, aucun WCT, aucun événement"
    tables_apres = sqlfx.fx.fx._tables()
    assert {n for n in tables_avant if tables_avant[n] != tables_apres[n]} == {
        "approbations", "journal", "mutations_appliquees"}, "seul l'audit légitime de la décision change"
    _nathan_valide()

    # Le classement récent reste exactement le courant ; les sources actuelles en découlent.
    dossier_2 = _dossier(cap, iid)
    assert dossier_2["lignes_critiques"][0]["classement_courant"] == correction["resultat"]
    sources_2 = dossier_2["sources"]
    assert sources_2 != sources_1 and sources_2["classements"][0]["reference"] == correction["resultat"]["reference"]

    # Positif frais dans la même chaîne : nouvelle proposition, vraie décision de Nathan, une seule résolution.
    _, p2 = _proposer(cap, iid, sources_2, "P2-R3-FICTIF")
    assert p2["demande_id"] != p1["demande_id"]
    m4_avant = _maillons_m4()
    d2 = _decider(cap, p2["demande_id"], "D2-R3-FICTIF")
    decision_2 = d2["resultat"]["resultat"]
    assert d2["ok"] and decision_2["statut"] == "executee", d2
    preuve = decision_2["preuve_completion"]
    assert preuve["wct_id"] == sources_2["wct_id"] and preuve["approuve_par"] == NATHAN.personne
    assert preuve["association_decision"]["intention_uuid"] == "D2-R3-FICTIF"
    m4_apres = _maillons_m4()
    assert m4_apres[:len(m4_avant)] == m4_avant and len(m4_apres) == len(m4_avant) + 1
    with stockage.transaction():
        resolution = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")).lire()[-1]
    assert resolution["statut"] == "completed_verified" and resolution["intervention_id"] == iid
    assert resolution["sources"] == sources_2, "liée aux nouvelles références, pas aux sources de P1"
    assert resolution["demande_approbation_id"] == p2["demande_id"]
    assert _demande(p2["demande_id"])["statut"] == "executee"
    assert _demande(p1["demande_id"]) == demande_1, "l'ancienne demande ne reçoit pas cette preuve"

    # Rejeu historique propre de D2 : identique, sans aucune écriture. Le socle ne restitue qu'une décision
    # `executee` (`approbations_completion_m4.verifier_rejeu_decision`) : le rejeu de D1 reste une issue inconnue
    # fermée, jamais un positif ni une preuve, et n'écrit rien non plus.
    tables = sqlfx.fx.fx._tables()
    assert _decider(cap, p2["demande_id"], "D2-R3-FICTIF") == {**d2, "rejoue": True}
    rejeu_1 = _decider(cap, p1["demande_id"], "D1-R3-FICTIF")
    assert rejeu_1.get("ok") is False and rejeu_1.get("issue") == "inconnue", rejeu_1
    assert "preuve_completion" not in json.dumps(rejeu_1)
    assert sqlfx.fx.fx._tables() == tables
    _nathan_valide()
