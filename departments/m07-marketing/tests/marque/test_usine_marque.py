"""La porte qualité de l'usine à contenu applique le profil v2 : refus nommés, score rangé, mentions validées
(M7-MARQUE).

Vrais outils du vrai manifeste sur une base SQLite temporaire migrée. Données fictives.
"""

from __future__ import annotations

import copy

import pytest

from opsys import stockage

FICTIF = True
HORO = "2026-11-02T09:00:00-05:00"
BON_FB = (
    "Chantier terminé à Repentigny : gouttières et descentes. Vous avez un projet semblable ? "
    "Écrivez-nous pour demander une soumission, nous vous répondrons avec plaisir."
)


def metier(reponse):
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def proposer(appeler, wct_id, textes=None):
    arguments = {"wct_id": wct_id}
    if textes is not None:
        arguments["textes"] = textes
    return metier(appeler("m7_proposer_contenus_chantier", **arguments))


def par_plateforme(resultat):
    return {c["plateforme"]: c for c in resultat["contenus"]}


def lire(nom):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def test_sans_profil_la_porte_est_fail_closed_et_rien_n_est_ecrit(base_durable, appeler, semer_wct, charge):
    wct = semer_wct(charge)
    resultat = proposer(appeler, wct)
    assert resultat["statut"] == "profil_marque_non_configure" and resultat["contenus"] == []
    assert lire("contenus_chantier") == []


def test_un_contenu_conforme_est_propose_avec_son_score_et_le_range(
    base_durable, appeler, semer_wct, charge, v2, enregistrer_marque
):
    assert enregistrer_marque(v2)["statut"] == "configure"
    wct = semer_wct(charge)
    resultat = proposer(appeler, wct, {"facebook": BON_FB})
    fb = par_plateforme(resultat)["facebook"]
    assert fb["statut"] == "propose" and fb["conformite"]["verdict"] == "conforme"
    assert fb["conformite"]["score_global"] == 100 and fb["conformite"]["sous_scores"]["mots_interdits"] == 100
    stocke = next(p for p in lire("contenus_chantier") if p["plateforme"] == "facebook")
    assert stocke["conformite"] == fb["conformite"]
    # la file de lecture (bornée à 6 000 caractères) ne porte pas le score : il se lit dans la proposition rangée et par
    # l'outil d'audit
    liste = metier(appeler("m7_lister_contenus_chantier", wct_id=wct))["contenus"]
    assert "conformite" not in next(c for c in liste if c["plateforme"] == "facebook")


@pytest.mark.parametrize(
    ("texte", "regle"),
    [
        (
            "Chantier terminé : du travail pas cher. Écrivez-nous pour demander une soumission, merci beaucoup.",
            "REJ-MARQUE-MOT-INTERDIT",
        ),
        (
            "Chantier terminé. Garantie de dix ans sur tout le revêtement. Écrivez-nous pour demander une soumission.",
            "REJ-MARQUE-PROMESSE-NON-VALIDEE",
        ),
        (
            "Chantier terminé. Installation dès 500 $ seulement. Écrivez-nous pour demander une soumission, merci.",
            "REJ-PRIX",
        ),
        (
            "Chantier terminé : vous ne trouverez pas mieux ailleurs. Écrivez-nous pour demander une soumission.",
            "REJ-MARQUE-MESSAGE-INTERDIT",
        ),
        (
            "Chantier terminé. Tu peux nous écrire pour demander une soumission, toi aussi, avec plaisir et confiance.",
            "REJ-MARQUE-TON",
        ),
    ],
)
def test_un_texte_non_conforme_est_refuse_nomme_et_jamais_enregistre(
    base_durable, appeler, semer_wct, charge, v2, enregistrer_marque, texte, regle
):
    enregistrer_marque(v2)
    wct = semer_wct(charge)
    resultat = proposer(appeler, wct, {"facebook": texte})
    fb = par_plateforme(resultat)["facebook"]
    assert fb["statut"] == "refuse"
    assert regle in [r["regle"] for r in fb["regles"]]
    assert fb["conformite"]["verdict"] == "refuse" and fb["conformite"]["score_global"] < 100
    assert all(p["plateforme"] != "facebook" for p in lire("contenus_chantier"))
    assert resultat["statut"] == "partiel"  # les autres plateformes (gabarits du code) sont proposées


def test_les_gabarits_du_code_passent_la_porte_du_profil_v2(
    base_durable, appeler, semer_wct, charge, v2, enregistrer_marque
):
    enregistrer_marque(v2)
    resultat = proposer(appeler, semer_wct(charge))
    assert resultat["statut"] == "propose" and len(resultat["contenus"]) == 5
    assert {c["conformite"]["verdict"] for c in resultat["contenus"]} <= {"conforme", "conforme_avec_reserves"}


def test_mentions_validees_sont_ajoutees_aux_textes_publics_seulement(
    base_durable, appeler, semer_wct, charge, v2, enregistrer_marque
):
    mention = "Licence RBQ 514-555-0199 (fictive)"
    v2["mentions_requises"] = [mention]
    v2["validation_champs"]["mentions_requises"] = {"statut": "valide", "par": "nathan", "le": "2026-11-02"}
    assert enregistrer_marque(v2)["statut"] == "configure"
    resultat = proposer(appeler, semer_wct(charge))
    assert resultat["statut"] == "propose", resultat
    textes = {p["plateforme"]: p["texte"] for p in lire("contenus_chantier")}
    assert all(textes[p].endswith(mention) for p in ("facebook", "instagram", "fiche_google", "video_courte"))
    assert mention not in textes["demande_temoignage"]


def test_mentions_non_validees_ne_sont_pas_ajoutees_et_les_textes_publics_sont_refuses_avec_la_raison(
    base_durable, appeler, semer_wct, charge, v2, enregistrer_marque
):
    v2["mentions_requises"] = ["Licence RBQ fictive"]
    enregistrer_marque(v2)
    resultat = proposer(appeler, semer_wct(charge))
    publics = [c for c in resultat["contenus"] if c["plateforme"] != "demande_temoignage"]
    assert all(
        c["statut"] == "refuse" and "REJ-MARQUE-MENTION-REQUISE" in [r["regle"] for r in c["regles"]] for c in publics
    )
    assert par_plateforme(resultat)["demande_temoignage"]["statut"] == "propose"
    lu = metier(appeler("m7_lire_matiere_chantier", wct_id=charge["wct_id"]))
    assert any("pas encore validées" in a for a in lu["avertissements"])
    assert lu["matiere"]["regles_marque"]["mentions_validees"] is False


def test_la_matiere_dit_a_la_redaction_les_regles_du_profil(
    base_durable, appeler, semer_wct, charge, v2, enregistrer_marque
):
    enregistrer_marque(v2)
    regles = metier(appeler("m7_lire_matiere_chantier", wct_id=semer_wct(charge)))["matiere"]["regles_marque"]
    assert regles["mots_interdits"] == ["pas cher", "bas de gamme"] and regles["voix"]["adresse"] == "vous"
    assert regles["garanties_a_valider"] == ["Garantie de dix ans sur tout le revêtement"]
    assert (
        "avantages" not in regles and "promesse" not in regles
    )  # un énoncé positif n'est pas une consigne de rédaction


def test_un_profil_modifie_apres_la_proposition_bloque_l_approbation_par_la_porte(
    base_durable, proprietaire, appeler, semer_wct, charge, v2, enregistrer_marque
):
    enregistrer_marque(v2)
    wct = semer_wct(charge)
    proposer(appeler, wct, {"facebook": BON_FB})
    contenu_id = next(p["contenu_id"] for p in lire("contenus_chantier") if p["plateforme"] == "facebook")
    plus_strict = copy.deepcopy(v2)
    plus_strict["mots_interdits"] = [*v2["mots_interdits"], "soumission"]
    assert enregistrer_marque(plus_strict)["revision"] == 2
    refus = appeler(
        "m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id, decision="approuver", horodatage=HORO
    )
    assert refus["ok"] is True and refus["resultat"]["accepte"] is False
    assert refus["resultat"]["verdict"]["code"] == "REJ-TEXTE-NON-CONFORME"
    assert "REJ-MARQUE-MOT-INTERDIT" in refus["resultat"]["verdict"]["detail"]
    assert lire("decisions_contenu") == []  # rien d'approuvé


def test_un_profil_v1_garde_le_comportement_d_avant_et_dit_les_dimensions_non_evaluables(
    base_durable, appeler, semer_wct, charge, v1, enregistrer_marque
):
    enregistrer_marque(v1)
    resultat = proposer(appeler, semer_wct(charge))
    assert resultat["statut"] == "propose"
    assert {c["conformite"]["verdict"] for c in resultat["contenus"]} == {"conforme"}
    assert "mots_interdits" in resultat["contenus"][0]["conformite"]["non_evaluables"]
