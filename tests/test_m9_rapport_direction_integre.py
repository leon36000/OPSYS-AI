"""M9.6–7 — les vingt sections de direction de la revue hebdomadaire, par les vrais outils et registres (fictif)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m2_revenue_crm import outils as m2

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements

_SPEC = importlib.util.spec_from_file_location("m9_producteurs_a", Path(__file__).with_name("m9_producteurs_a.py"))
A = importlib.util.module_from_spec(_SPEC)
sys.modules["m9_producteurs_a"] = A
_SPEC.loader.exec_module(A)

FICTIF = True
M9, M2 = "m09-strategic-intelligence", "m02-revenue-crm"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
REF = "2026-10-21T13:00:00Z"
CONNAISSANCE = "2026-10-27T12:00:00Z"  # après la fin de la semaine du 19 au 25 octobre (heure de Toronto)
IDS_ATTENDUS = [
    "resume", "revenus_cash_marge", "pipeline_ventes", "estimations_soumissions", "production_cedule",
    "inventaire_fournisseurs", "marketing_visibilite", "clients_satisfaction", "risques", "opportunites",
    "ce_qui_a_fonctionne", "ce_qui_a_echoue", "lecons_apprises", "decisions_a_prendre", "plan_semaine_suivante",
    "objectifs_mesurables", "actions_par_departement", "previsions_4_semaines", "previsions_13_semaines",
    "recommandations",
]  # fmt: skip


@pytest.fixture
def cap(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'direction.db'}")
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


def _plan(plan_id, echeance, adresse):
    return {
        "plan_id": plan_id,
        "objectif": f"Qualifier le lead — {plan_id}",
        "porteur": "vendeur.fictif",
        "echeance": echeance,
        "resultats_cles": [
            {"id": "qualifie", "libelle": "Lead qualifié", "lecture": "m2.leads",
             "chemin": "resultat.resultat.leads[*].statut", "operateur": "==", "cible": "qualifie"},
        ],
        "sources": [adresse],
        "decision_ref": "decision-1",
    }  # fmt: skip


def _capturer_leads(cap):
    arguments = {"horodatage": "2026-10-21T12:00:00Z"}
    ok(
        appel(
            cap,
            "m9_capturer_producteur",
            {"lecture_id": "m2.leads", "arguments": arguments, "horodatage": "2026-10-21T12:00:01Z"},
        )
    )
    question = {"question": "Plan", "domaines": ["strategie"], "reference": REF}
    faits = ok(appel(cap, "m9_apercu_dossier_strategique", question))["faits"]
    (statut,) = [a for a in faits if a.endswith("leads[0].statut")]
    return statut


def _deposer(cap, plan_id, echeance, adresse, horodatage):
    arguments = {"plan": _plan(plan_id, echeance, adresse), "reference": REF, "horodatage": horodatage}
    return ok(appel(cap, "m9_enregistrer_plan", arguments))


def _revue(cap, connaissance=CONNAISSANCE, ancre="2026-10-21"):
    morceaux, depart = [], 0
    while depart is not None:
        page = ok(
            appel(
                cap,
                "m9_apercu_revue",
                {
                    "granularite": "hebdomadaire",
                    "ancre": ancre,
                    "fuseau": "America/Toronto",
                    "connaissance": connaissance,
                    "depart": depart,
                },
            )
        )
        morceaux.append(page["contenu_json"])
        depart = page["prochain_depart"]
    return json.loads("".join(morceaux))


def test_revue_hebdomadaire_porte_les_vingt_sections_de_direction_avec_manques_nommes(cap):
    statut = _capturer_leads(cap)
    _deposer(cap, "en-retard", "2026-10-24", statut, "2026-10-21T13:00:00Z")
    _deposer(cap, "abandonne", "2026-10-30", statut, "2026-10-21T13:00:01Z")
    annulation = {"plan_id": "abandonne", "motif": "priorité changée par Nathan", "horodatage": "2026-10-22T10:00:00Z"}
    ok(appel(cap, "m9_annuler_plan", annulation))
    revue = _revue(cap)
    direction = revue["sections_direction"]
    assert direction["ids"] == IDS_ATTENDUS and set(direction["sections"]) == set(IDS_ATTENDUS)
    s = direction["sections"]
    assert all(v["statut"] in ("RENSEIGNEE", "PARTIELLE", "NON_DISPONIBLE") and v["titre"] for v in s.values())
    # ce que M9 tient réellement : un plan en retard, un plan annulé, un lead capturé
    assert [p["plan_id"] for p in s["ce_qui_a_echoue"]["contenu"]["plans_en_retard"]] == ["en-retard"]
    assert s["ce_qui_a_echoue"]["statut"] == "RENSEIGNEE" and s["ce_qui_a_fonctionne"]["statut"] == "NON_DISPONIBLE"
    assert [x["resultat_id"] for x in s["objectifs_mesurables"]["contenu"]["resultats_cles"]] == ["qualifie"]
    assert s["objectifs_mesurables"]["contenu"]["resultats_cles"][0]["statut_mesure"] == "NON_SATISFAIT"
    assert [p["plan_id"] for p in s["plan_semaine_suivante"]["contenu"]["plans_a_echeance"]] == ["en-retard"]
    lecons = s["lecons_apprises"]["contenu"]["declarees"]
    assert lecons and lecons[0]["plan_id"] == "abandonne"
    assert lecons[0]["annulation"]["motif"] == "priorité changée par Nathan"
    # ce que M9 ne tient pas : nommé, jamais rempli
    assert s["revenus_cash_marge"]["statut"] in ("PARTIELLE", "NON_DISPONIBLE")
    assert any("revenue : aucune définition officielle" in m for m in s["revenus_cash_marge"]["manques"])
    assert s["pipeline_ventes"]["statut"] in ("PARTIELLE", "NON_DISPONIBLE") and s["pipeline_ventes"]["manques"]
    assert s["decisions_a_prendre"]["statut"] == "NON_DISPONIBLE" and s["recommandations"]["statut"] == "NON_DISPONIBLE"
    for identifiant in ("previsions_4_semaines", "previsions_13_semaines"):
        assert s[identifiant]["statut"] == "NON_DISPONIBLE"
        assert any("leads : AUCUNE_PREVISION_PRODUITE chez m02-revenue-crm" in m for m in s[identifiant]["manques"])
    resume = s["resume"]["contenu"]
    assert resume["plans"] == 2 and resume["plans_en_retard"] == 1 and resume["actions"] == 0
    assert resume["sections_renseignees"] + resume["sections_partielles"] + resume["sections_non_disponibles"] == 19
    # aucun chiffre d'entreprise n'est fabriqué : ni float, ni clé de montant dans la revue
    assert "float" not in json.dumps(revue) and "montant" not in json.dumps(s["revenus_cash_marge"])


def test_revue_est_figee_a_la_fin_de_la_periode_et_les_sections_ne_voient_pas_le_futur(cap):
    statut = _capturer_leads(cap)
    # Un plan déposé APRÈS la fin de la semaine n'existe pas pour cette revue (il fera partie de la suivante).
    _deposer(cap, "tardif", "2026-11-05", statut, "2026-10-28T10:00:00Z")
    avant = _revue(cap, connaissance="2026-10-29T12:00:00Z")
    assert avant["sections_direction"]["sections"]["resume"]["contenu"]["plans"] == 0
    assert avant["sections_direction"]["sections"]["objectifs_mesurables"]["statut"] == "NON_DISPONIBLE"
    suivante = _revue(cap, connaissance="2026-11-03T12:00:00Z", ancre="2026-10-28")
    assert suivante["sections_direction"]["sections"]["resume"]["contenu"]["plans"] == 1
    prochaine = suivante["sections_direction"]["sections"]["plan_semaine_suivante"]["contenu"]["plans_a_echeance"]
    assert [p["plan_id"] for p in prochaine] == ["tardif"]


def test_revue_est_refusee_aux_profils_non_admin_et_a_la_voie_d_agent(cap):
    vendeur = IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    arguments = {
        "granularite": "hebdomadaire",
        "ancre": "2026-10-21",
        "fuseau": "America/Toronto",
        "connaissance": CONNAISSANCE,
    }
    for qui in (vendeur, None):
        reponse = appel(cap, "m9_apercu_revue", arguments, qui)
        assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False
