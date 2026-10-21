"""Clôture interne fictive : bus M8/SQLite/approbation réels, aucun effet terrain."""
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import update

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

_spec = importlib.util.spec_from_file_location(
    "_suivi_cloture_base", Path(__file__).with_name("test_suivi_decisions.py"))
b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b)
installation = b.installation
PREPARER = "m9_preparer_cloture_suivi_decision"
CLORE = "m9_clore_suivi_decision"


def _clotures():
    with stockage.transaction():
        return list(stockage.maillons(b.DEPARTEMENT, "clotures_suivi_decisions"))


def _proposer(installation, **modifications):
    cap, _, suivi_id, alerte = b._proposer(installation)
    assert b._decider(cap, suivi_id, "ouvrir-avant-cloture")["resultat"]["resultat"]["statut"] == "executee"
    assert PREPARER in cap.index and CLORE in cap.index, "M9_CLOTURE_CAPACITE_ABSENTE"
    prep = b._lire(cap, PREPARER, {"suivi_id": suivi_id, "evenement_id": alerte["evenement_id"]})
    assert prep["accepte"] is True and prep["preuve"]["alerte"] == alerte
    arguments = {"suivi_id": suivi_id, "empreinte_suivi": prep["empreinte_suivi"],
                 "evenement_id": alerte["evenement_id"], "empreinte_preuve": prep["preuve"]["empreinte_source"],
                 "bilan": "Revue humaine fictive des causes, sans attester une action terrain."} | modifications
    prop = cap.appeler(CLORE, arguments)
    assert prop["statut"] == "en_attente_approbation", prop
    assert _clotures() == []
    return cap, suivi_id, prop["demande_id"], arguments, alerte


def _metier_hors_cloture():
    tables = b._metier()
    tables[REGISTRES.name] = [x for x in tables[REGISTRES.name]
                             if (json.loads(x)["departement"], json.loads(x)["registre"])
                             != (b.DEPARTEMENT, "clotures_suivi_decisions")]
    return tables


def test_cloture_approuvee_persistante_sans_second_effet(installation):
    cap, suivi_id, demande_id, args, alerte = _proposer(installation)
    plan = b._suivis()
    avant = _metier_hors_cloture()
    decision = b._decider(cap, demande_id, "clore-revue-fictive")
    assert decision["resultat"]["resultat"]["statut"] == "executee", decision
    assert b._suivis() == plan and _metier_hors_cloture() == avant
    resultat = b._lire(cap, b.LIRE, {"suivi_id": suivi_id})
    assert resultat["suivi"] == plan[0]
    assert resultat["etat_suivi"] == "cloturee_par_revue_humaine"
    cloture = resultat["cloture"]
    assert cloture["schema"] == 1 and cloture["suivi_id"] == suivi_id
    assert cloture["statut"] == "cloturee_par_revue_humaine"
    assert cloture["empreinte_suivi"] == args["empreinte_suivi"]
    assert cloture["preuve"]["alerte"] == alerte and cloture["bilan"] == args["bilan"]
    assert cloture["decision"]["demande_id"] == demande_id
    assert cloture["decision"]["decide_par"] == b.PROPRIO.personne
    assert cloture["decision"]["decide_role"] == "nathan_owner"
    assert cloture["decision"]["decide_le"] == decision["resultat"]["resultat"]["decide_le"]
    assert _clotures() == [cloture]
    stockage.liberer()
    cap = b._capacites(installation)
    assert b._lire(cap, b.LIRE, {"suivi_id": suivi_id}) == resultat
    avant_rejeu = b._tables()
    assert b._decider(cap, demande_id, "clore-revue-fictive")["rejoue"] is True
    assert b._tables() == avant_rejeu
    autre = cap.appeler(CLORE, args)
    if autre.get("statut") == "en_attente_approbation":
        assert "executee" not in json.dumps(b._decider(cap, autre["demande_id"], "seconde-cloture"))
    assert _clotures() == [cloture] and b._suivis() == plan


@pytest.mark.parametrize("cause", ["empreinte_suivi", "empreinte_preuve", "bilan_vide", "bilan_long",
                                  "preuve_absente", "preuve_alteree", "chantier_etranger"])
def test_refus_cloture_avant_effet(installation, cause):
    changements = {"empreinte_suivi": {"empreinte_suivi": "0" * 64},
                   "empreinte_preuve": {"empreinte_preuve": "0" * 64},
                   "bilan_vide": {"bilan": " "}, "bilan_long": {"bilan": "a" * 2001}}.get(cause, {})
    cap, suivi_id, demande_id, args, alerte = _proposer(installation, **changements)
    with stockage.transaction() as cnx:
        if cause in {"preuve_absente", "preuve_alteree"}:
            replacement = alerte | {"quoi": "preuve fictive changée"}
            if cause == "preuve_absente":
                replacement["evenement_id"] = "autre-evenement"
            cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == b.DEPARTEMENT,
                        REGISTRES.c.registre == "alertes_m8").values(maillon=codec.encoder(replacement)))
        elif cause == "chantier_etranger":
            replacement = alerte | {"preuve": alerte["preuve"] | {"wct_id": "autre-chantier-fictif"}}
            cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == b.DEPARTEMENT,
                        REGISTRES.c.registre == "alertes_m8").values(maillon=codec.encoder(replacement)))
    avant = _metier_hors_cloture()
    plan = b._suivis()
    decision = b._decider(cap, demande_id, "refus-cloture-" + cause)
    assert "executee" not in json.dumps(decision), decision
    assert _clotures() == [] and b._suivis() == plan and _metier_hors_cloture() == avant


def test_appel_direct_et_approbation_ouverture_inoperants(installation):
    cap, suivi_id, _, args, _ = _proposer(installation)
    outil = cap.index[CLORE][1]
    avant = b._tables()
    with contexte.appele_par_appareil(b.PROPRIO):
        direct = executer_atomique(outil, args)
    assert direct["resultat"]["accepte"] is False
    assert b._tables() == avant
    with contexte.executer_demande_approuvee(suivi_id):
        refus = executer_atomique(outil, args)
    assert refus["resultat"]["accepte"] is False
    assert b._tables() == avant and _clotures() == []


def test_proprietaire_revoque_ne_clot_pas(installation):
    cap, _, demande_id, _, _ = _proposer(installation)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, b.PROPRIO.personne, "nathan_owner")
    avant = _metier_hors_cloture()
    assert "executee" not in json.dumps(b._decider(cap, demande_id, "cloture-revoquee"))
    assert _clotures() == [] and _metier_hors_cloture() == avant


def test_preparation_refuse_preuve_reelle_autre_chantier_sans_mutation(installation):
    cap, suivi_id, _, _, _ = _proposer(installation)
    autre = b._recevoir_preuve_m8(installation, suffix="-autre-chantier")
    avant = b._tables()
    with contexte.appele_par_appareil(b.PROPRIO):
        resultat = cap.appeler(PREPARER, {"suivi_id": suivi_id, "evenement_id": autre["evenement_id"]})
    assert not (resultat.get("ok") is True and resultat.get("resultat", {}).get("accepte") is True), resultat
    assert b._tables() == avant and _clotures() == []


def test_budget_verifie_avant_append_cloture(installation, monkeypatch):
    from m9_strategic_intelligence import outils
    cap, _, demande_id, _, _ = _proposer(installation)
    monkeypatch.setattr(outils, "BUDGET_SORTIE", 100)
    avant = _metier_hors_cloture()
    decision = b._decider(cap, demande_id, "cloture-hors-budget")
    assert "executee" not in json.dumps(decision), decision
    assert _clotures() == [] and _metier_hors_cloture() == avant


def test_preuve_etrangere_empreinte_correcte_refusee_meme_apres_approbation(installation):
    cap, suivi_id, _, args, _ = _proposer(installation)
    autre = b._recevoir_preuve_m8(installation, suffix="-preuve-valide-etrangere")
    arguments = args | {"evenement_id": autre["evenement_id"], "empreinte_preuve": b.empreinte(autre)}
    proposition = cap.appeler(CLORE, arguments)
    assert proposition["statut"] == "en_attente_approbation", proposition
    avant = _metier_hors_cloture()
    plan = b._suivis()
    decision = b._decider(cap, proposition["demande_id"], "preuve-etrangere-correctement-hashee")
    assert "executee" not in json.dumps(decision), decision
    assert _clotures() == [] and b._suivis() == plan and _metier_hors_cloture() == avant


@pytest.mark.parametrize("avec_meta", [False, True])
def test_mcp_generique_sans_cible_ne_propose_pas_la_cloture(installation, avec_meta):
    from opsys import idempotence
    cap, _, _, args, _ = _proposer(installation)
    avant = b._tables()
    meta = idempotence.Meta(cle="mcp-cloture-fictive", appareil="agent-fictif",
                            horodatage_appareil="2026-10-19T00:00:00Z") if avec_meta else None
    with contexte.transport_mcp():
        refus = cap.appeler(CLORE, args, meta)
    assert refus.get("erreur") == "ticket_cible_requis", refus
    assert b._tables() == avant and _clotures() == []


def test_deux_demandes_concurrentes_ne_creent_qu_une_cloture(installation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    cap, suivi_id, premiere, args, _ = _proposer(installation)
    seconde = cap.appeler(CLORE, args)
    assert seconde["statut"] == "en_attente_approbation", seconde
    plan = b._suivis()
    avant = _metier_hors_cloture()
    barriere = Barrier(2)

    def decider(item):
        demande, cle = item
        propre_cap = b._capacites(installation)
        barriere.wait(timeout=5)
        return b._decider(propre_cap, demande, cle)

    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(decider, [(premiere, "cloture-concurrente-a"),
                                            (seconde["demande_id"], "cloture-concurrente-b")]))
    statuts = [d["resultat"]["resultat"]["statut"] for d in decisions]
    assert sorted(statuts) == ["echec", "executee"], decisions
    assert len(_clotures()) == 1 and _clotures()[0]["suivi_id"] == suivi_id
    assert b._suivis() == plan and _metier_hors_cloture() == avant
