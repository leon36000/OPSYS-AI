"""M9.16 — plans/OKR par le vrai dispatcher : résultat mesuré chez M2, source changée, révision, annulation (fictif)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m2_revenue_crm import outils as m2
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.stockage.schema import META

_SPEC = importlib.util.spec_from_file_location("m9_producteurs_a", Path(__file__).with_name("m9_producteurs_a.py"))
A = importlib.util.module_from_spec(_SPEC)
sys.modules["m9_producteurs_a"] = A
_SPEC.loader.exec_module(A)

FICTIF = True
M9, M2 = "m09-strategic-intelligence", "m02-revenue-crm"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
REF = "2026-10-21T13:00:00Z"


@pytest.fixture
def cap(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'plans.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
    assert m2.ingerer_lead(
        {"lead_id": "lead-1", "conversation_id": "c-1", "contact": {"nom": "C", "courriel": "c@example.test"},
         "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone"},
        "2026-09-01T09:00:00-04:00",
    )["accepte"]  # fmt: skip
    yield Capacites(charger_departements(), stockage.transaction, filtre={M9, M2}, memoire=False)
    m2.reinitialiser_registre()
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


def capturer(cap, recu):
    return ok(
        appel(
            cap,
            "m9_capturer_producteur",
            {"lecture_id": "m2.leads", "arguments": {"horodatage": "2026-10-21T12:00:00Z"}, "horodatage": recu},
        )
    )


def adresse_statut(cap, reference):
    faits = ok(
        appel(
            cap,
            "m9_apercu_dossier_strategique",
            {"question": "Plan", "domaines": ["strategie"], "reference": reference},
        )
    )["faits"]
    (adresse,) = [a for a in faits if a.endswith("leads[0].statut")]
    return adresse, faits[adresse]


def le_plan(adresse):
    return {
        "plan_id": "qualifier-lead-1",
        "objectif": "Qualifier le premier lead de la semaine",
        "porteur": "vendeur.fictif",
        "echeance": "2026-10-25",
        "resultats_cles": [
            {
                "id": "lead_qualifie",
                "libelle": "Le lead est qualifié chez M2",
                "lecture": "m2.leads",
                "chemin": "resultat.resultat.leads[*].statut",
                "operateur": "==",
                "cible": "qualifie",
            }
        ],
        "sources": [adresse],
        "decision_ref": "decision-3",
    }


def lire(cap, jour, connaissance="2026-10-26T12:00:00Z"):
    return ok(appel(cap, "m9_lire_plans", {"connaissance": connaissance, "jour": jour}))["plans"][0]


def test_parcours_mesure_retard_source_changee_revision_et_annulation(cap):
    capturer(cap, "2026-10-21T12:00:01Z")
    adresse, statut_initial = adresse_statut(cap, REF)
    assert statut_initial == "nouveau"
    depose = ok(
        appel(
            cap,
            "m9_enregistrer_plan",
            {"plan": le_plan(adresse), "reference": REF, "horodatage": "2026-10-21T13:00:00Z"},
        )
    )
    assert depose["version"] == 1 and depose["revision"] is False
    avant = lire(cap, "2026-10-22")
    assert avant["statut"] == "EN_COURS" and avant["resultats_cles"][0]["mesure"]["statut"] == "NON_SATISFAIT"
    assert lire(cap, "2026-10-27")["statut"] == "EN_RETARD"
    # Un suivi n'est pas un effet : le résultat reste non satisfait.
    suivi = ok(
        appel(
            cap,
            "m9_noter_suivi_plan",
            {
                "plan_id": "qualifier-lead-1",
                "resultat_id": "lead_qualifie",
                "note": "client rappelé",
                "horodatage": "2026-10-22T09:00:00Z",
            },
        )
    )
    assert suivi["effet_realise"] is False
    assert lire(cap, "2026-10-22")["resultats_cles"][0]["mesure"]["statut"] == "NON_SATISFAIT"
    # Le producteur change l'état réel ; M9 recapture : la mesure et la source changée le montrent.
    A.geste(
        A.outils_departement(M2),
        "m2_transitionner_statut",
        {"lead_id": "lead-1", "statut_cible": "qualifie", "horodatage": "2026-10-23T12:00:00-04:00",
         "owner": "vendeur.fictif",
         "prochaine_action": {"description": "Appeler", "echeance": "2026-10-24T09:00:00-04:00"}},
    )  # fmt: skip
    capturer(cap, "2026-10-23T18:00:00Z")
    apres = lire(cap, "2026-10-24")
    assert apres["resultats_cles"][0]["mesure"]["statut"] == "SATISFAIT" and apres["statut"] == "ATTEINT_MESURE"
    assert (
        apres["sources_changees"][0]["avant"] == "nouveau" and apres["sources_changees"][0]["maintenant"] == "qualifie"
    )
    assert apres["version"] == 1, "le plan lui-même n'a pas été réécrit"
    # Révision (motif obligatoire) puis annulation : l'historique reste.
    revise = {**le_plan(adresse), "echeance": "2026-11-05"}
    assert refuse(
        appel(cap, "m9_enregistrer_plan", {"plan": revise, "reference": REF, "horodatage": "2026-10-24T10:00:00Z"}),
        "REJ-PLAN-REVISION",
    )
    deux = ok(
        appel(
            cap,
            "m9_enregistrer_plan",
            {
                "plan": revise,
                "reference": REF,
                "horodatage": "2026-10-24T10:00:00Z",
                "motif_revision": "nouvelle échéance",
            },
        )
    )
    assert deux["version"] == 2 and deux["revision"] is True
    ok(
        appel(
            cap,
            "m9_annuler_plan",
            {"plan_id": "qualifier-lead-1", "motif": "projet abandonné", "horodatage": "2026-10-25T10:00:00Z"},
        )
    )
    fin = lire(cap, "2026-10-26", "2026-10-26T12:00:00Z")
    assert fin["statut"] == "ANNULE" and [h["version"] for h in fin["historique"]] == [1, 2]
    assert refuse(
        appel(
            cap,
            "m9_annuler_plan",
            {"plan_id": "qualifier-lead-1", "motif": "encore", "horodatage": "2026-10-26T10:00:00Z"},
        ),
        "REJ-PLAN-ANNULE",
    )


def test_source_hors_dossier_identites_et_chaine_falsifiee(cap):
    capturer(cap, "2026-10-21T12:00:01Z")
    adresse, _ = adresse_statut(cap, REF)
    inventee = {**le_plan(adresse), "sources": ["m2.leads#0:p0.resultat.resultat.leads[0].inventee"]}
    assert refuse(
        appel(cap, "m9_enregistrer_plan", {"plan": inventee, "reference": REF, "horodatage": "2026-10-21T13:00:00Z"}),
        "REJ-PLAN-SOURCE",
    )
    vendeur = IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    for identite_appelante in (vendeur, None):
        assert refuse(
            appel(
                cap,
                "m9_enregistrer_plan",
                {"plan": le_plan(adresse), "reference": REF, "horodatage": "2026-10-21T13:00:00Z"},
                identite_appelante,
            )
        )
        assert refuse(appel(cap, "m9_lire_plans", {"connaissance": REF, "jour": "2026-10-22"}, identite_appelante))
    ok(
        appel(
            cap,
            "m9_enregistrer_plan",
            {"plan": le_plan(adresse), "reference": REF, "horodatage": "2026-10-21T13:00:00Z"},
        )
    )
    with stockage.transaction() as cnx:
        table = META.tables["registres_maillons"]
        ligne = cnx.execute(select(table).where(table.c.registre == "plans")).first()
        cnx.execute(
            table.update()
            .where((table.c.registre == "plans") & (table.c.rang == ligne.rang))
            .values(maillon=ligne.maillon.replace("Qualifier le premier lead", "Qualifier AUCUN lead"))
        )
    assert refuse(appel(cap, "m9_lire_plans", {"connaissance": REF, "jour": "2026-10-22"}), "REJ-PLAN-CHAINE-INVALIDE")
