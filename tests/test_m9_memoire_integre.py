"""M9.20 — mémoire M10 effective : consigner par la file native, vérifier, corriger, détecter le fantôme (fictif)."""

from __future__ import annotations

import json

import pytest

from opsys import approbations, contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.stockage.schema import META

FICTIF = True
M9, M10 = "m09-strategic-intelligence", "m10-memoire"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
REF = "2026-10-21T13:00:00Z"
T = "2026-10-21T14:00:00Z"
CONNAISSANCE = "2026-10-28T13:00:00Z"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'memoire.db'}")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
        identite.creer_personne(cnx, "nathan.fictif", "Nathan", "mot-de-passe-nathan-12345", ["nathan_owner"])
    departements = charger_departements()
    cap = Capacites(departements, stockage.transaction, filtre={M9, M10}, memoire=False)
    executables = outils_executables({M10: departements[M10]}, stockage.transaction)
    yield cap, departements, executables
    stockage.liberer()


def appel(cap, nom, arguments, identite_appelante=ADMIN):
    if identite_appelante is None:
        return cap.appeler(nom, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return cap.appeler(nom, arguments)


def ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def refuse(reponse, code=None):
    echec = reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    return echec and (code is None or code in json.dumps(reponse))


def session_close(cap):
    ouverture = ok(
        appel(
            cap,
            "m9_ouvrir_conseil",
            {
                "question": "Faut-il relancer les devis sans réponse ?",
                "domaines": ["strategie"],
                "importance": "courante",
                "budget_tokens": 100_000,
                "reference": REF,
                "horodatage": T,
            },
        )
    )
    for tour in ouverture["tours"]:
        ok(
            appel(
                cap,
                "m9_abandonner_tour_conseil",
                {
                    "session_id": ouverture["session_id"],
                    "role": tour["role"],
                    "raison": "budget indisponible",
                    "horodatage": T,
                },
            )
        )
    cloture = ok(appel(cap, "m9_cloturer_conseil", {"session_id": ouverture["session_id"], "horodatage": T}))
    assert cloture["cloture"]["issue"] == "ABSTENTION"
    return ouverture["session_id"], cloture["cloture"]["rapport_id"]


def proposer(cap, a_proposer, horodatage):
    return ok(
        appel(
            cap,
            "m9_proposer_action",
            {**a_proposer, "motif": "consigner la décision de la Direction IA", "horodatage": horodatage},
        )
    )


def approuver(demande_id, departements, executables, approuve=True):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande_id, approuve, "nathan.fictif", executables, departements, "ok", role="nathan_owner"
        )


def capturer_statut(cap, decision_id, recu):
    capture = ok(
        appel(
            cap,
            "m9_capturer_producteur",
            {"lecture_id": "m10.statut_decision", "arguments": {"decision_id": decision_id}, "horodatage": recu},
        )
    )["capture"]
    assert capture["verdict"] == "ACCEPTEE" and capture["complete"] is True, capture
    return capture


def verifier(cap, decision_id, attendu, action_id, connaissance=CONNAISSANCE):
    arguments = {"decision_id": decision_id, "connaissance": connaissance, "attendu": attendu, "action_id": action_id}
    return ok(appel(cap, "m9_verifier_memoire_decision", {k: v for k, v in arguments.items() if v is not None}))


def test_consigner_verifier_corriger_et_detecter_la_memoire_fantome(monde):
    cap, departements, executables = monde
    session_id, rapport_id = session_close(cap)
    prepare = ok(
        appel(
            cap,
            "m9_preparer_memoire_decision",
            {"session_id": session_id, "statut": "indetermine", "horodatage": "2026-10-22T09:00:00Z"},
        )
    )
    assert (
        prepare["ecrit"] is False
        and prepare["decision_id"] == f"m9:{session_id}"
        and prepare["rapport_id"] == rapport_id
    )
    # Avant toute action : M10 n'a rien, M9 ne prétend rien (NON_ENREGISTREE, jamais fantôme).
    capturer_statut(cap, prepare["decision_id"], "2026-10-22T09:05:00Z")
    assert (
        verifier(cap, prepare["decision_id"], "indetermine", None, "2026-10-22T10:00:00Z")["verdict"]
        == "NON_ENREGISTREE"
    )
    # Proposition à la file native, puis approbation humaine : M10 exécute avec ces arguments exacts.
    proposee = proposer(cap, prepare["a_proposer"], "2026-10-22T09:10:00Z")
    assert proposee["etat"] == "EN_ATTENTE_APPROBATION" and proposee["niveau"] == "N3"
    assert approuver(proposee["demande_id"], departements, executables)["statut"] == "executee"
    ok(appel(cap, "m9_reconcilier_action", {"action_id": proposee["action_id"], "horodatage": "2026-10-22T09:20:00Z"}))
    capturer_statut(cap, prepare["decision_id"], "2026-10-22T09:30:00Z")
    coherent = verifier(cap, prepare["decision_id"], "indetermine", proposee["action_id"], "2026-10-22T10:00:00Z")
    assert coherent["verdict"] == "COHERENT" and coherent["memoire"]["statut"] == "indetermine"
    # Correction : même identifiant, nouveau statut, motif cité ; M10 reste append-only.
    correction = ok(
        appel(
            cap,
            "m9_preparer_memoire_decision",
            {
                "session_id": session_id,
                "statut": "annulee",
                "horodatage": "2026-10-23T09:00:00Z",
                "motif": "question retirée",
                "correction": True,
            },
        )
    )
    assert correction["decision_id"] == prepare["decision_id"]
    deux = proposer(cap, correction["a_proposer"], "2026-10-23T09:10:00Z")
    assert approuver(deux["demande_id"], departements, executables)["statut"] == "executee"
    ok(appel(cap, "m9_reconcilier_action", {"action_id": deux["action_id"], "horodatage": "2026-10-23T09:20:00Z"}))
    capturer_statut(cap, prepare["decision_id"], "2026-10-23T09:30:00Z")
    apres = verifier(cap, prepare["decision_id"], "annulee", deux["action_id"], "2026-10-23T10:00:00Z")
    assert apres["verdict"] == "COHERENT" and apres["memoire"]["statut"] == "annulee"
    # Divergence : M9 attendait « indetermine », M10 porte « annulee ».
    assert (
        verifier(cap, prepare["decision_id"], "indetermine", deux["action_id"], "2026-10-23T10:00:00Z")["verdict"]
        == "DIVERGENT"
    )
    # MÉMOIRE FANTÔME : la trace M10 disparaît (effacement du registre) alors que M9 croit l'avoir consignée.
    with stockage.transaction() as cnx:
        table = META.tables["registres_maillons"]
        cnx.execute(table.delete().where((table.c.departement == M10) & (table.c.registre == "affaires")))
    capturer_statut(cap, prepare["decision_id"], "2026-10-24T09:30:00Z")
    fantome = verifier(cap, prepare["decision_id"], "annulee", deux["action_id"], "2026-10-24T10:00:00Z")
    assert fantome["verdict"] == "MEMOIRE_FANTOME" and fantome["memoire"]["statut"] is None
    # Connaissance antérieure : l'effacement n'était pas encore connu de M9.
    assert (
        verifier(cap, prepare["decision_id"], "annulee", deux["action_id"], "2026-10-23T10:00:00Z")["verdict"]
        == "COHERENT"
    )


def test_refus_nommes_et_identites(monde):
    cap, _d, _e = monde
    session_id, _ = session_close(cap)
    base = {"session_id": session_id, "horodatage": "2026-10-22T09:00:00Z"}
    assert refuse(appel(cap, "m9_preparer_memoire_decision", {**base, "statut": "validee"}), "REJ-MEMOIRE-VALIDATION")
    assert refuse(appel(cap, "m9_preparer_memoire_decision", {**base, "statut": "proposee"}), "REJ-MEMOIRE-STATUT")
    assert refuse(appel(cap, "m9_preparer_memoire_decision", {**base, "statut": "annulee"}), "REJ-MEMOIRE-MOTIF")
    assert refuse(
        appel(cap, "m9_preparer_memoire_decision", {**base, "session_id": "f" * 32, "statut": "indetermine"}),
        "REJ-SESSION-INCONNUE",
    )
    # Une session non close ne se consigne pas.
    ouverte = ok(
        appel(
            cap,
            "m9_ouvrir_conseil",
            {
                "question": "Autre question ?",
                "domaines": ["strategie"],
                "importance": "courante",
                "budget_tokens": 100_000,
                "reference": REF,
                "horodatage": T,
            },
        )
    )
    assert refuse(
        appel(
            cap, "m9_preparer_memoire_decision", {**base, "session_id": ouverte["session_id"], "statut": "indetermine"}
        ),
        "REJ",
    )
    vendeur = IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    for identite_appelante in (vendeur, None):
        assert refuse(appel(cap, "m9_preparer_memoire_decision", {**base, "statut": "indetermine"}, identite_appelante))
        assert refuse(
            appel(
                cap,
                "m9_verifier_memoire_decision",
                {"decision_id": "m9:x", "connaissance": CONNAISSANCE},
                identite_appelante,
            )
        )
    # Sans lecture capturée, la vérification est INCONNUE, jamais fantôme.
    inconnu = verifier(cap, f"m9:{session_id}", "indetermine", None)
    assert inconnu["verdict"] == "INCONNU" and inconnu["memoire"]["lecture"] == "ABSENTE"
