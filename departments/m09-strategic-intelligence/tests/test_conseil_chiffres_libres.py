"""M9.23 — régression : un modèle ne produit aucun montant, pourcentage ou date absent de ses citations (fictif).

Défaut prouvé par le corpus métier (mkt-A03, mkt-A06, mkt-V02, vil-A07) : une hypothèse, une inférence ou la décision
recommandée contenant « 0 $ » pour une absence, « 5 000 $ » ou un revenu inventé était ADMISE (statut seulement
« non validée »), contre la règle « le code calcule, le modèle explique »."""

import json
from pathlib import Path

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import conseil
from m9_strategic_intelligence import dossier_strategique as ds
from m9_strategic_intelligence import sessions_conseil as sc

FICTIF = True
REF = "2026-10-21T12:00:00Z"
SOLDE = "m5.comptes_a_payer#0:p0.resultat.resultat.total"
SOURCES = {SOLDE: "8400.00", "m5.comptes_a_payer#0:p0.resultat.resultat.echeance": "2026-11-09"}
REELLES = Path(__file__).parent / "sorties_reelles"


def _obs(valeur="8400.00", ref=SOLDE):
    return {"id": "A1", "nature": "observation_source", "reference": ref, "valeur": valeur}


def _admettre(*affirmations):
    return conseil.admettre_proposition({"affirmations": list(affirmations)}, sources=SOURCES)


@pytest.mark.parametrize(
    "texte, citees, attendu",
    [
        ("le budget est de 0 $", ["DEPENSES_NON_BRANCHEES"], ["0 $"]),
        ("hausse de 5 000 $", ["8400.00"], ["5 000 $"]),
        ("hausse de 5 000 $", ["5000.00"], []),
        ("solde de 8 400,00 $", ["8400.00"], []),
        ("total de 11 400,00 $", ["8400.00", "3000.00"], ["11 400,00 $"]),
        ("coût de 0,00 $", [], ["0,00 $"]),
        ("marge de 3.5 %", ["3.5 %"], []),
        ("marge de 35 %", ["3.5 %"], ["35 %"]),
        ("solde 4200.00", [], ["4200.00"]),
        ("échéance le 2026-11-09", ["2026-11-09"], []),
        ("échéance le 2026-12-31", ["2026-11-09"], ["2026-12-31"]),
        ("3 leads dont lead-2 et la lecture m6", [], []),
        ("la lecture est horodatée 2026-10-20T16:00:00Z", ["2026-10-20T16:00:00Z"], []),
        ("budget de 0 $", ["2026-10-20T16:00:00Z"], ["0 $"]),
    ],
)
def test_chiffres_libres_matrice(texte, citees, attendu):
    assert conseil.chiffres_libres(texte, citees) == attendu


@pytest.mark.parametrize("nature", ["hypothese", "inference"])
def test_un_montant_libre_est_refuse_dans_une_hypothese_ou_une_inference(nature):
    libre = {"id": "X1", "nature": nature, "enonce": "le solde sera de 1 250,00 $ dans six semaines"}
    if nature == "inference":
        libre["premisses"] = ["A1"]
    with pytest.raises(ValueError, match="REJ-CONSEIL-CHIFFRE-LIBRE"):
        _admettre(_obs(), libre)


def test_un_calcul_de_modele_est_refuse_mais_la_valeur_citee_reprise_est_admise():
    somme = {"id": "I1", "nature": "inference", "enonce": "les dettes totalisent 11 400,00 $", "premisses": ["A1"]}
    with pytest.raises(ValueError, match="REJ-CONSEIL-CHIFFRE-LIBRE"):
        _admettre(_obs(), somme)
    reprise = {"id": "I1", "nature": "inference", "enonce": "les dettes sont de 8 400,00 $", "premisses": ["A1"]}
    assert _admettre(_obs(), reprise)["affirmations"][1]["statut"] == "INFERENCE_NON_VALIDEE"


def test_une_valeur_citee_n_est_pas_modifiee_et_les_entiers_nus_restent_permis():
    texte = {"id": "H1", "nature": "hypothese", "enonce": "3 leads attendent une réponse (lead-2 et m6 inclus)"}
    assert _admettre(_obs(), texte)["type"] == "PROPOSITION_ADMISE"
    zero = {"affirmations": [_obs("0.00"), {"id": "H1", "nature": "hypothese", "enonce": "solde cité de 0,00 $"}]}
    assert conseil.admettre_proposition(zero, sources={SOLDE: "0.00"})["type"] == "PROPOSITION_ADMISE"


@pytest.mark.parametrize("fichier", ["ronde2-contraintes_inventaire.json", "ronde3-croissance_marketing.json"])
def test_les_sorties_reelles_deja_admises_le_restent(fichier):
    sortie = json.loads((REELLES / fichier).read_text(encoding="utf-8"))
    sources = {a["reference"]: a["valeur"] for a in sortie["affirmations"] if a["nature"] == "observation_source"}
    assert conseil.admettre_proposition(sortie, sources=sources)["type"] == "PROPOSITION_ADMISE"


def test_la_recommandation_reelle_de_la_ronde3_reste_admise():
    sortie = json.loads((REELLES / "ronde3-conseiller_pdg.json").read_text(encoding="utf-8"))
    rec = sortie["recommandation"]
    citees = [a["valeur"] for a in sortie["affirmations"] if a["nature"] == "observation_source"]
    conseil.exiger_chiffres_sources([rec["decision"], *(a["description"] for a in rec["actions"])], citees)


def _session():
    capture = cs.construire(
        cat.obtenir("m5.comptes_a_payer"),
        {},
        [{"ok": True, "resultat": {"accepte": True, "resultat": {"total": "8400.00"}}}],
        recu_a=REF,
        reference=None,
        index=0,
        hash_precedent="",
    )
    dossier = ds.construire(
        [capture],
        question="Que décider sur la dette fournisseur ?",
        domaines=["strategie"],
        reference=REF,
        connaissance=REF,
        attendues=["m5.comptes_a_payer"],
    )
    ouverture, session_id = sc.ouvrir([], dossier=dossier, importance="courante", budget_tokens=100_000, recu_a=REF)
    return [ouverture], session_id


def _recommandation(decision, description):
    return {
        "affirmations": [_obs()],
        "recommandation": {
            "decision": decision,
            "refs": ["A1"],
            "actions": [{"id": "a1", "type": "depense_reelle", "description": description}],
        },
    }


@pytest.mark.parametrize(
    "decision, description",
    [
        ("Payer 5 000 $ au fournisseur", "paiement partiel"),
        ("Payer le fournisseur", "virement de 5 000 $"),
        ("Revenu attendu de 250 000,00 $ par an", "suivi"),
    ],
)
def test_une_decision_ou_une_action_avec_un_montant_libre_est_un_depot_refuse(decision, description):
    evenements, session_id = _session()
    evenement = sc.deposer(
        evenements,
        session_id,
        "conseiller_pdg",
        _recommandation(decision, description),
        reservation_id="r1",
        tokens_reels=0,
        recu_a=REF,
    )
    assert evenement["issue"] == "REFUSE" and evenement["code"] == "REJ-CONSEIL-CHIFFRE-LIBRE"
    assert evenement["proposition"] is None


def test_une_decision_qui_reprend_le_montant_cite_est_admise_et_gouvernee():
    evenements, session_id = _session()
    evenement = sc.deposer(
        evenements,
        session_id,
        "conseiller_pdg",
        _recommandation("Soumettre à Nathan le paiement de 8 400,00 $", "paiement à valider"),
        reservation_id="r1",
        tokens_reels=0,
        recu_a=REF,
    )
    assert evenement["issue"] == "ADMIS"
    verdict = conseil.gouverner(evenement["proposition"]["recommandation"])
    assert verdict["actions"][0]["verdict"] == "VALIDATION_HUMAINE_REQUISE" and verdict["autorite_d_effet"] is False
