"""M9.17 — actions proposées à la file native : exactes, non exécutées par M9, non rejouées (fictif)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m2_revenue_crm import outils as m2
from sqlalchemy import select

from opsys import approbations, contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.stockage.schema import APPROBATIONS

_SPEC = importlib.util.spec_from_file_location("m9_producteurs_a", Path(__file__).with_name("m9_producteurs_a.py"))
A = importlib.util.module_from_spec(_SPEC)
sys.modules["m9_producteurs_a"] = A
_SPEC.loader.exec_module(A)

FICTIF = True
M9, M2, M4 = "m09-strategic-intelligence", "m02-revenue-crm", "m04-field-ops"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
T1 = "2026-10-27T12:00:00Z"
SOURCE = "m2.leads#0:p0.resultat.resultat.leads[0].lead_id"
RELANCE = {
    "lead_id": "lead-1",
    "regle": "relance_lead_dormant",
    "canal": "appel",
    "horodatage": "2026-10-27T09:00:00-04:00",
}
ARGUMENTS = {
    "lead_id": "lead-1",
    "nouveau_proprietaire": "vendeuse.fictive",
    "motif": "Répartition de la charge entre vendeuses",
    "horodatage": "2026-10-27T09:00:00-04:00",
}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'actions.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
        identite.creer_personne(cnx, "vendeuse.fictive", "Vendeuse", "mot-de-passe-vendeuse-123", ["seller"])
        identite.creer_personne(cnx, "nathan.fictif", "Nathan", "mot-de-passe-nathan-12345", ["nathan_owner"])
    assert m2.ingerer_lead(
        {"lead_id": "lead-1", "conversation_id": "c-1", "contact": {"nom": "C", "courriel": "c@example.test"},
         "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone"},
        "2026-09-01T09:00:00-04:00",
    )["accepte"]  # fmt: skip
    departements = charger_departements()
    cap = Capacites(departements, stockage.transaction, filtre={M9, M2, M4}, memoire=False)
    A.geste(  # le lead est qualifié et confié à un vendeur par l'admin (geste d'appareil, par le vrai outil)
        A.outils_departement(M2),
        "m2_transitionner_statut",
        {
            "lead_id": "lead-1",
            "statut_cible": "qualifie",
            "horodatage": "2026-09-18T12:00:00-04:00",
            "owner": "vendeur.fictif",
            "prochaine_action": {"description": "Appeler le client", "echeance": "2026-09-20T09:00:00-04:00"},
        },
    )
    executables = outils_executables({k: departements[k] for k in (M2, M4)}, stockage.transaction)
    yield cap, departements, executables
    m2.reinitialiser_registre()
    stockage.liberer()


def appel(cap, nom, arguments, identite_appelante=ADMIN):
    if identite_appelante is None:
        return cap.appeler(nom, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return cap.appeler(nom, arguments)


def proposer(cap, arguments=ARGUMENTS, outil="m2_reassigner_lead", departement=M2, **extra):
    return appel(
        cap,
        "m9_proposer_action",
        {
            "departement": departement,
            "outil": outil,
            "arguments": arguments,
            "sources": [SOURCE],
            "motif": "lead dormant",
            "horodatage": T1,
            **extra,
        },
    )


def ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def refuse(reponse, code=None):
    echec = reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    return echec and (code is None or code in json.dumps(reponse))


def ligne_native(demande_id):
    with stockage.transaction() as cnx:
        return dict(cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == demande_id)).mappings().one())


def decider(demande_id, executables, departements, approuver=True):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx,
            demande_id,
            approuver,
            "nathan.fictif",
            executables,
            departements,
            "décision fictive",
            role="nathan_owner",
        )


def test_proposition_exacte_non_executee_puis_approbation_humaine_et_reconciliation(monde):
    cap, departements, executables = monde
    proposee = ok(proposer(cap))
    assert proposee["etat"] == "EN_ATTENTE_APPROBATION" and proposee["execute"] is False and proposee["niveau"] == "N3"
    natif = ligne_native(proposee["demande_id"])
    assert natif["statut"] == "en_attente" and natif["departement"] == M2 and natif["outil"] == "m2_reassigner_lead"
    assert json.loads(natif["arguments"]) == ARGUMENTS, "les arguments exacts sont ceux que l'humain approuvera"
    leads = ok(appel(cap, "m2_lister_leads", {"horodatage": "2026-10-27T12:00:00Z"}))["resultat"]["leads"]
    assert [lead["proprietaire"] for lead in leads] == ["vendeur.fictif"], "M9 n'a rien exécuté"
    attente = ok(
        appel(cap, "m9_reconcilier_action", {"action_id": proposee["action_id"], "horodatage": "2026-10-27T12:05:00Z"})
    )
    assert attente["etat"] == "EN_ATTENTE_APPROBATION" and attente["constat_ajoute"] is False
    # Rejeu pendant l'attente : refusé, une seule demande native existe.
    assert refuse(proposer(cap), "REJ-ACTION-REJEU")
    with stockage.transaction() as cnx:
        assert len(approbations.lister(cnx, "en_attente")) == 1
    # Un humain approuve : l'outil du producteur s'exécute avec ces arguments exacts, sous sa politique.
    decision = decider(proposee["demande_id"], executables, departements)
    assert decision["statut"] == "executee", json.dumps(decision, ensure_ascii=False)[:900]
    final = ok(
        appel(cap, "m9_reconcilier_action", {"action_id": proposee["action_id"], "horodatage": "2026-10-27T12:10:00Z"})
    )
    assert final["etat"] == "EXECUTEE_CONFIRMEE" and final["rejeu_autorise"] is False
    assert refuse(proposer(cap), "REJ-ACTION-REJEU"), "une action exécutée ne se repropose pas"
    leads = ok(appel(cap, "m2_lister_leads", {"horodatage": "2026-10-27T12:00:00Z"}))["resultat"]["leads"]
    assert [lead["proprietaire"] for lead in leads] == ["vendeuse.fictive"], "l'effet réel est chez le producteur M2"
    # Réconcilier de nouveau ne change rien (idempotent).
    encore = ok(
        appel(cap, "m9_reconcilier_action", {"action_id": proposee["action_id"], "horodatage": "2026-10-27T12:20:00Z"})
    )
    assert encore["constat_ajoute"] is False and encore["etat"] == final["etat"]
    vue = ok(appel(cap, "m9_lire_actions", {}))
    (action,) = vue["actions"]
    assert (
        action["demande_id"] == proposee["demande_id"]
        and "arguments" not in action
        and len(action["arguments_sha256"]) == 64
    )


def test_refus_humain_permet_une_nouvelle_tentative_numerotee(monde):
    cap, departements, executables = monde
    premiere = ok(proposer(cap))
    decider(premiere["demande_id"], executables, departements, approuver=False)
    constat = ok(
        appel(cap, "m9_reconcilier_action", {"action_id": premiere["action_id"], "horodatage": "2026-10-27T12:10:00Z"})
    )
    assert constat["etat"] == "REFUSEE" and constat["rejeu_autorise"] is True
    seconde = ok(proposer(cap, horodatage="2026-10-27T13:00:00Z"))
    assert seconde["action_id"] == premiere["action_id"] and seconde["tentative"] == 2
    assert seconde["demande_id"] != premiere["demande_id"]


def test_effet_inconnu_ne_se_rejoue_jamais(monde):
    cap, departements, executables = monde
    proposee = ok(proposer(cap))
    with (
        stockage.transaction() as cnx
    ):  # la demande native disparaît (corruption, purge) : l'effet n'est plus vérifiable
        cnx.execute(APPROBATIONS.delete().where(APPROBATIONS.c.id == proposee["demande_id"]))
    inconnu = ok(
        appel(cap, "m9_reconcilier_action", {"action_id": proposee["action_id"], "horodatage": "2026-10-27T12:10:00Z"})
    )
    assert inconnu["etat"] == "INCONNU" and inconnu["rejeu_autorise"] is False
    assert refuse(proposer(cap, horodatage="2026-10-27T13:00:00Z"), "REJ-ACTION-REJEU")
    with stockage.transaction() as cnx:
        assert approbations.lister(cnx, "en_attente") == []


def test_arguments_modifies_apres_coup_donnent_un_constat_inconnu(monde):
    cap, _departements, _executables = monde
    proposee = ok(proposer(cap))
    with stockage.transaction() as cnx:
        cnx.execute(
            APPROBATIONS.update()
            .where(APPROBATIONS.c.id == proposee["demande_id"])
            .values(arguments=json.dumps({**ARGUMENTS, "canal": "sms"}))
        )
    assert (
        ok(
            appel(
                cap, "m9_reconcilier_action", {"action_id": proposee["action_id"], "horodatage": "2026-10-27T12:10:00Z"}
            )
        )["etat"]
        == "INCONNU"
    )


@pytest.mark.parametrize(
    "extra, code",
    [
        ({"outil": "m2_ingerer_lead"}, "REJ-ACTION-NON-AUTORISEE"),  # hors liste blanche
        ({"departement": M4}, "REJ-ACTION-NON-AUTORISEE"),  # outil d'un autre département
        ({"outil": "m5_payer_facture", "departement": "m05-financecore"}, "REJ-ACTION-NON-AUTORISEE"),
        ({"arguments": {"lead_id": "lead-1"}}, "REJ-ACTION-REFUSEE"),  # schéma de l'outil cible violé
        ({"arguments": {**ARGUMENTS, "champ_inconnu": 1}}, "REJ-ACTION-REFUSEE"),
        ({"sources": []}, "REJ-ACTION-SOURCES"),
        ({"sources": ["n'importe quoi"]}, "REJ-ACTION-SOURCES"),
        ({"motif": " "}, "REJ-ACTION-MOTIF"),
    ],
)
def test_refus_nommes_sans_demande_native_ni_trace(monde, extra, code):
    cap, _d, _e = monde
    reponse = proposer(cap, **extra)
    assert refuse(reponse, code)
    with stockage.transaction() as cnx:
        assert approbations.lister(cnx) == []
    vue = ok(appel(cap, "m9_lire_actions", {}))
    assert vue["total"] == 0, "un refus n'écrit rien dans le registre"


def test_identites_non_admin_et_voie_d_agent_refusees(monde):
    cap, _d, _e = monde
    vendeur = IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    for identite_appelante in (vendeur, None):
        assert refuse(proposer_avec(cap, identite_appelante))
        assert refuse(appel(cap, "m9_lire_actions", {}, identite_appelante))
        assert refuse(appel(cap, "m9_reconcilier_action", {"action_id": "x", "horodatage": T1}, identite_appelante))
    with stockage.transaction() as cnx:
        assert approbations.lister(cnx) == []


def proposer_avec(cap, identite_appelante):
    return appel(
        cap,
        "m9_proposer_action",
        {"departement": M2, "outil": "m2_reassigner_lead", "arguments": ARGUMENTS, "sources": [SOURCE], "motif": "x",
         "horodatage": T1},
        identite_appelante,
    )  # fmt: skip


def test_echec_d_ecriture_du_registre_annule_aussi_la_demande_native(monde, monkeypatch):
    """Demande native et proposition M9 sont dans la même transaction : l'une ne survit jamais sans l'autre."""
    from m9_strategic_intelligence import orchestrateur

    cap, _d, _e = monde

    def panne(*_args, **_kwargs):
        raise ValueError("REJ-TEST-PANNE : écriture du registre impossible")

    monkeypatch.setattr(orchestrateur, "proposition", panne)
    assert refuse(proposer(cap), "REJ-TEST-PANNE")
    with stockage.transaction() as cnx:
        assert approbations.lister(cnx) == [], "aucune demande orpheline dans la file native"


def test_refus_du_producteur_est_un_echec_confirme_qui_autorise_une_nouvelle_tentative(monde):
    """Le producteur (M2) refuse la relance : fréquence maximale non configurée par le propriétaire (fail-closed)."""
    cap, departements, executables = monde
    proposee = ok(proposer(cap, arguments=RELANCE, outil="m2_preparer_relance"))
    decision = decider(proposee["demande_id"], executables, departements)
    assert decision["statut"] == "echec" and "REJ-RELANCES-A-CONFIGURER" in json.dumps(decision)
    constat = ok(
        appel(cap, "m9_reconcilier_action", {"action_id": proposee["action_id"], "horodatage": "2026-10-27T12:10:00Z"})
    )
    assert constat["etat"] == "ECHEC" and constat["rejeu_autorise"] is True
    suivante = ok(proposer(cap, arguments=RELANCE, outil="m2_preparer_relance", horodatage="2026-10-27T13:00:00Z"))
    assert suivante["tentative"] == 2 and suivante["etat"] == "EN_ATTENTE_APPROBATION"


def test_liste_blanche_du_socle_et_de_m9_identiques():
    from m9_strategic_intelligence import orchestrateur

    from opsys import actions_m9

    assert {d: set(o) for d, o in actions_m9.ACTIONS_AUTORISEES.items()} == {
        d: set(o) for d, o in orchestrateur.ACTIONS.items()
    }
    departements = charger_departements()
    for departement, outils in actions_m9.ACTIONS_AUTORISEES.items():
        reels = {o.nom: o for o in departements[departement].charger_outils()}
        for nom in outils:
            assert reels[nom].niveau_effectif.value in {"N3", "N4", "N5"}, (
                "chaque action proposable exige une approbation"
            )
