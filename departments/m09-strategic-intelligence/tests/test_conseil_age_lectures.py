"""M9.23 — régression : l'âge de chaque lecture est visible du conseil, sans péremption inventée (fictif).

Défaut prouvé par le corpus métier (lea-A08) : le dossier calculait l'écart signé entre la référence et le dernier
instant métier de chaque lecture, mais l'entrée du tour ne donnait au modèle que faits, manques et contradictions :
une lecture vieille de dix-neuf mois et une lecture d'hier étaient indiscernables (« jamais masquer l'incertitude »)."""

from datetime import UTC, datetime

from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import dossier_strategique as ds
from m9_strategic_intelligence import sessions_conseil as sc

FICTIF = True
REF = "2026-10-21T12:00:00Z"


def _lead(ingere):
    return {
        "lead_id": "lead-1",
        "statut": "nouveau",
        "ville": "Québec",
        "travaux": "toiture",
        "urgence_declaree": False,
        "ingere_le": ingere,
        "derniere_activite": ingere,
    }


def _page(inner):
    return {"ok": True, "resultat": {"accepte": True, "resultat": inner}}


def _session(importance="courante"):
    leads = cs.construire(
        cat.obtenir("m2.leads"),
        {"horodatage": REF},
        [_page({"total": 1, "leads": [_lead("2025-03-01T09:00:00-04:00")]})],
        recu_a=REF,
        reference=REF,
        index=0,
        hash_precedent="",
    )
    stock = cs.construire(
        cat.obtenir("m6.disponibilite"),
        {},
        [_page({"tronque": False})],
        recu_a=REF,
        reference=None,
        index=1,
        hash_precedent=leads["hash_maillon"],
    )
    dossier = ds.construire(
        [leads, stock],
        question="Les leads reçus sont-ils encore actuels ?",
        domaines=["leads", "stock", "strategie"],
        reference=REF,
        connaissance=REF,
        attendues=["m2.leads", "m6.disponibilite", "m5.comptes_a_payer"],
    )
    ouverture, session_id = sc.ouvrir([], dossier=dossier, importance=importance, budget_tokens=100_000, recu_a=REF)
    return [ouverture], session_id


def test_l_age_signe_de_chaque_lecture_est_donne_au_conseil_tel_que_calcule_a_la_main():
    evenements, session_id = _session()
    entree = sc.entree_tour(evenements, session_id, "croissance_marketing")
    couverture = entree["donnees"]["couverture"]
    assert couverture["reference"] == REF and couverture["connaissance"] == REF
    par_lecture = {e["lecture_id"]: e for e in couverture["lectures"]}
    attendu = int(
        (datetime(2026, 10, 21, 12, 0, tzinfo=UTC) - datetime(2025, 3, 1, 13, 0, tzinfo=UTC)).total_seconds()
    )  # 09:00-04:00 = 13:00Z
    assert par_lecture["m2.leads"]["age_s"] == attendu and attendu > 365 * 86_400
    assert par_lecture["m2.leads"]["statut"] == "PRESENTE" and par_lecture["m2.leads"]["fraicheur"] == "NON_EVALUEE"


def test_aucune_peremption_n_est_inventee_pour_une_lecture_sans_instant_ou_absente():
    evenements, session_id = _session()
    par_lecture = {
        e["lecture_id"]: e
        for e in sc.entree_tour(evenements, session_id, "croissance_marketing")["donnees"]["couverture"]["lectures"]
    }
    assert par_lecture["m6.disponibilite"]["statut"] == "TEMPS_METIER_NON_DECLARE"
    assert "age_s" not in par_lecture["m6.disponibilite"] and "fraicheur" not in par_lecture["m6.disponibilite"]
    assert par_lecture["m5.comptes_a_payer"] == {"lecture_id": "m5.comptes_a_payer", "statut": "ABSENTE"}


def test_le_critique_recoit_la_meme_couverture_et_la_consigne_dit_comment_la_lire():
    evenements, session_id = _session(importance="majeure")
    specialiste = sc.entree_tour(evenements, session_id, "croissance_marketing")
    explication = specialiste["consigne"]["age_des_lectures"]
    assert "NON_EVALUEE" in explication and "jamais à déduire" in explication
    projection = sc.etat(evenements, session_id)
    assert "critique_decisions" in {t["role"] for t in projection["tours"]}
    assert specialiste["donnees"]["couverture"] == sc._donnees(  # noqa: SLF001
        evenements[0], projection, "critique_decisions"
    )["couverture"]
