"""M2.4 — le modèle PUR de score de lead : poids déclarés, explication, déterminisme, équité, classement.

Aucun registre, aucune base : des faits d'entrée (booléens et compteurs) et le score qui en sort. Données fictives."""

from __future__ import annotations

import copy
import inspect
import json
from decimal import Decimal
from fractions import Fraction

import pytest
from m2_revenue_crm import calibration_scoring, scoring

FICTIF = True
BASE = {
    "contact_courriel": True,
    "contact_telephone": True,
    "contact_nom": True,
    "ville": True,
    "service": True,
    "canal_connu": True,
    "source_connue": False,
    "completude_propriete_pct": 40,
    "urgence_declaree": False,
    "jours_depuis_ingestion": 3,
    "statut": "qualifie",
    "interactions_humaines": 2,
    "jours_depuis_activite": 2,
    "devis_envoye": False,
    "readiness_proprietaire": True,
    "readiness_service": True,
    "readiness_ville": True,
    "readiness_interaction": True,
    "profil_propriete_confirme": False,
    "photos_liees": 0,
    "valeur_declaree_cents": None,
    "bandes_valeur_cents": None,
    "doublon_en_attente": False,
    "retrait_consentement": False,
    "seuil_dormant_jours": 30,
}


def _calculer(**surcharge):
    resultat, verdict = scoring.calculer({**BASE, **surcharge})
    assert verdict is None, verdict
    return resultat


def _score(**surcharge):
    return Decimal(_calculer(**surcharge)["score"])


def test_le_modele_declare_ses_poids_et_chaque_facteur_totalise_cent_points():
    assert sum(f["poids"] for f in scoring.FACTEURS.values()) == 100
    for nom, facteur in scoring.FACTEURS.items():
        assert sum(points for _, points, _ in facteur["signaux"]) == 100, nom
    assert list(scoring.FACTEURS) == ["qualite", "urgence", "conversion", "rentabilite", "preparation", "risque"]
    declaration = scoring.declaration_modele()
    assert declaration["id"] == "m2-score-lead" and declaration["version"] == "1.0.0"
    assert declaration["empreinte"] == scoring.empreinte_modele() and len(declaration["empreinte"]) == 64
    assert [f["poids"] for f in declaration["facteurs"]] == [20, 15, 25, 15, 15, 10]
    assert all(s["regle"] for f in declaration["facteurs"] for s in f["signaux"])


def test_l_empreinte_du_modele_change_si_un_poids_ou_un_signal_change(monkeypatch):
    avant = scoring.empreinte_modele()
    modifie = {nom: {**f} for nom, f in scoring.FACTEURS.items()}
    modifie["qualite"] = {**modifie["qualite"], "poids": 21}
    monkeypatch.setattr(scoring, "FACTEURS", modifie)
    assert scoring.empreinte_modele() != avant
    autre = {nom: {**f} for nom, f in scoring.FACTEURS.items()}
    autre["urgence"] = {**autre["urgence"], "signaux": (("urgence_declaree", 50, "x"), ("fraicheur", 50, "y"))}
    monkeypatch.setattr(scoring, "FACTEURS", autre)
    assert scoring.empreinte_modele() != avant


def test_le_score_est_exact_deterministe_et_dans_zero_cent():
    a, b = _calculer(), _calculer()
    assert a["score"] == b["score"] and a["facteurs"] == b["facteurs"]
    assert 0 <= Decimal(a["score"]) <= 100
    assert "_score_exact" in a and isinstance(a["_score_exact"], Fraction)
    assert "_score_exact" not in scoring.sans_exact(a)
    json.dumps(scoring.sans_exact(a))  # aucun flottant ni Fraction ne traverse un reçu


def test_les_extremes_du_modele():
    pire = _score(
        contact_courriel=False,
        contact_telephone=False,
        contact_nom=False,
        ville=False,
        service=False,
        canal_connu=False,
        source_connue=False,
        completude_propriete_pct=0,
        urgence_declaree=False,
        jours_depuis_ingestion=400,
        statut="nouveau",
        interactions_humaines=0,
        jours_depuis_activite=400,
        devis_envoye=False,
        readiness_proprietaire=False,
        readiness_service=False,
        readiness_ville=False,
        readiness_interaction=False,
        doublon_en_attente=True,
        retrait_consentement=True,
    )
    meilleur = _score(
        source_connue=True,
        completude_propriete_pct=100,
        urgence_declaree=True,
        jours_depuis_ingestion=0,
        interactions_humaines=5,
        jours_depuis_activite=0,
        devis_envoye=True,
        profil_propriete_confirme=True,
        photos_liees=3,
        valeur_declaree_cents=10**9,
        bandes_valeur_cents=[1, 2, 3],
    )
    assert meilleur == Decimal("100.00")
    assert pire < Decimal("10.00")


@pytest.mark.parametrize(
    ("champ", "bon", "mauvais"),
    [
        ("contact_courriel", True, False),
        ("contact_telephone", True, False),
        ("urgence_declaree", True, False),
        ("interactions_humaines", 3, 0),
        ("profil_propriete_confirme", True, False),
        ("devis_envoye", True, False),
        ("readiness_interaction", True, False),
        ("source_connue", True, False),
        ("service", True, False),
    ],
)
def test_un_signal_favorable_ne_baisse_jamais_le_score(champ, bon, mauvais):
    assert _score(**{champ: bon}) > _score(**{champ: mauvais}), champ


@pytest.mark.parametrize(
    ("champ", "bon", "mauvais"),
    [
        ("doublon_en_attente", False, True),
        ("retrait_consentement", False, True),
    ],
)
def test_un_risque_present_baisse_le_score(champ, bon, mauvais):
    assert _score(**{champ: bon}) > _score(**{champ: mauvais})


def test_la_fraicheur_et_l_activite_decroissent_par_paliers_exacts():
    assert [_score(jours_depuis_ingestion=j) for j in (0, 2, 3, 7, 8, 14, 15)] == sorted(
        [_score(jours_depuis_ingestion=j) for j in (0, 2, 3, 7, 8, 14, 15)], reverse=True
    )
    assert _score(jours_depuis_ingestion=2) > _score(jours_depuis_ingestion=3)
    assert _score(jours_depuis_ingestion=7) > _score(jours_depuis_ingestion=8)
    assert _score(jours_depuis_ingestion=14) > _score(jours_depuis_ingestion=15)
    assert _score(jours_depuis_activite=7) > _score(jours_depuis_activite=8)
    assert _score(jours_depuis_activite=30) >= _score(jours_depuis_activite=31)


def test_les_signaux_sans_donnee_sont_non_evalues_et_la_couverture_le_dit():
    r = _calculer()
    assert [x["facteur"] for x in r["facteurs_non_evalues"]] == ["rentabilite"]
    assert "bandes" in r["facteurs_non_evalues"][0]["manque"]
    assert r["couverture_poids"] == "0.85"
    nouveau = _calculer(
        statut="nouveau",
        readiness_proprietaire=None,
        readiness_service=None,
        readiness_ville=None,
        readiness_interaction=None,
        devis_envoye=None,
        seuil_dormant_jours=None,
    )
    manquants = {(x["facteur"], x["signal"]) for x in nouveau["signaux_non_evalues"]}
    assert manquants == {
        ("conversion", "devis_envoye"),
        ("preparation", "readiness_proprietaire"),
        ("preparation", "readiness_service"),
        ("preparation", "readiness_ville"),
        ("preparation", "readiness_interaction"),
        ("risque", "pas_dormant"),
        ("rentabilite", "valeur_declaree"),
    }
    assert all(x["manque"] for x in nouveau["signaux_non_evalues"])
    # un signal non évalué ne rapporte rien et ne pénalise pas : le sous-score est sur les points possibles
    assert Decimal(nouveau["score"]) > 0


def test_les_bandes_de_valeur_placent_la_valeur_a_25_50_75_100():
    bandes = [100, 200, 300]
    valeurs = {50: "25.00", 100: "50.00", 199: "50.00", 200: "75.00", 299: "75.00", 300: "100.00", 10**6: "100.00"}
    for valeur, attendu in valeurs.items():
        r = _calculer(valeur_declaree_cents=valeur, bandes_valeur_cents=bandes)
        rentabilite = next(f for f in r["facteurs"] if f["facteur"] == "rentabilite")
        assert rentabilite["sous_score"] == attendu, valeur


def test_les_contributions_somment_au_score_a_l_arrondi_pres():
    r = _calculer(valeur_declaree_cents=250, bandes_valeur_cents=[100, 200, 300])
    total = sum(Decimal(f["contribution_points"]) for f in r["facteurs"] if f["evalue"])
    assert abs(total - Decimal(r["score"])) <= Decimal("0.03")
    exact = (
        sum((Fraction(f["poids"]) * Fraction(f["sous_score"]) for f in r["facteurs"] if f["evalue"]), Fraction(0)) / 100
    )
    assert abs(Decimal(exact.numerator) / Decimal(exact.denominator) - Decimal(r["score"])) <= Decimal("0.05")


def test_aucun_champ_de_decision_ni_de_probabilite_dans_le_resultat():
    r = scoring.sans_exact(_calculer())
    json.dumps(r)  # sérialisable
    assert r["decision_humaine_requise"] is True
    for interdit in ("ecarter", "rejeter", "rejete", "ferme", "probabilite", "automatique", "decision"):
        assert interdit not in r, interdit
    assert "n'écarte" in r["avertissement"] and "ordonne" in r["avertissement"].lower()


# ---------------------------------------------------------------------------------------- équité
def test_la_liste_des_champs_interdits_ne_recoupe_ni_les_faits_ni_les_signaux():
    signaux = {s for f in scoring.FACTEURS.values() for s, _, _ in f["signaux"]}
    assert not scoring.CHAMPS_INTERDITS & set(scoring.CHAMPS_FAITS)
    assert not scoring.CHAMPS_INTERDITS & signaux
    for protege in (
        "age",
        "genre",
        "sexe",
        "origine",
        "ethnie",
        "religion",
        "langue",
        "handicap",
        "etat_civil",
        "orientation_sexuelle",
        "nationalite",
        "revenu",
        "code_postal",
        "adresse",
        "nom",
        "telephone",
        "courriel",
        "date_naissance",
    ):
        assert protege in scoring.CHAMPS_INTERDITS, protege


@pytest.mark.parametrize(
    "champ",
    [
        "age",
        "genre",
        "sexe",
        "origine",
        "religion",
        "langue",
        "handicap",
        "etat_civil",
        "code_postal",
        "adresse",
        "nom",
        "telephone",
        "courriel",
        "revenu",
        "Âge",
        "ORIGINE",
        "Code_Postal",
    ],
)
def test_un_attribut_protege_ou_un_identifiant_propose_comme_fait_est_refuse_nommement(champ):
    resultat, verdict = scoring.calculer({**BASE, champ: "valeur"})
    assert resultat is None and verdict["code"] == "REJ-SCORE-CHAMP-INTERDIT" and champ in verdict["detail"]


def test_un_fait_inconnu_manquant_ou_mal_type_est_refuse_pas_corrige():
    for faits in (
        {**BASE, "inconnu": 1},
        {k: v for k, v in BASE.items() if k != "ville"},
        {**BASE, "statut": "perdu"},
        {**BASE, "interactions_humaines": -1},
        {**BASE, "interactions_humaines": True},
        {**BASE, "completude_propriete_pct": 101},
        {**BASE, "contact_courriel": "oui"},
        {**BASE, "jours_depuis_ingestion": 1.5},
        {**BASE, "bandes_valeur_cents": [3, 2, 1]},
        {**BASE, "bandes_valeur_cents": [1, 2]},
        {**BASE, "valeur_declaree_cents": -1},
        None,
        [],
        "x",
    ):
        resultat, verdict = scoring.calculer(faits)
        assert resultat is None and verdict["code"] in ("REJ-SCORE-FAITS-INVALIDES", "REJ-SCORE-CHAMP-INTERDIT"), faits


def test_le_score_ne_depend_pas_de_l_ordre_des_cles_ni_de_la_copie():
    a = _calculer()
    inverse = dict(reversed(list(BASE.items())))
    b, verdict = scoring.calculer(inverse)
    assert verdict is None and b["score"] == a["score"]
    entree = copy.deepcopy(BASE)
    scoring.calculer(entree)
    assert entree == BASE, "l'entrée n'est pas modifiée"


def test_aucune_fonction_du_module_ne_touche_un_statut_ni_un_registre():
    source = inspect.getsource(scoring)
    for interdit in (
        "transitionner",
        "registre",
        "stockage",
        "open(",
        "requests",
        "socket",
        "random",
        "time.",
        "datetime.now",
    ):
        assert interdit not in source.replace("Registre", ""), interdit


# ---------------------------------------------------------------------------------------- classement
def test_le_classement_est_une_permutation_ordonnee_et_departage_de_facon_stable():
    notes = []
    for i, (lead, faits) in enumerate(
        (
            ("a", BASE),
            ("b", {**BASE, "urgence_declaree": True}),
            ("c", BASE),
            ("d", {**BASE, "statut": "nouveau", "interactions_humaines": 0}),
        )
    ):
        resultat, _ = scoring.calculer(faits)
        notes.append((lead, resultat, f"2026-0{i + 1}-01T00:00:00+00:00"))
    classe = scoring.classer(notes)
    assert sorted(e["lead_id"] for e in classe) == ["a", "b", "c", "d"] and len(classe) == 4
    assert [e["rang"] for e in classe] == [1, 2, 3, 4]
    assert classe[0]["lead_id"] == "b" and classe[-1]["lead_id"] == "d"
    # a et c ont le même score : le plus ancien d'abord, puis lead_id
    assert [e["lead_id"] for e in classe if e["lead_id"] in "ac"] == ["a", "c"]
    inverse = scoring.classer(list(reversed(notes)))
    assert [e["lead_id"] for e in inverse] == [e["lead_id"] for e in classe], "l'ordre d'arrivée ne compte pas"
    assert scoring.classer([]) == []


def test_resume_donne_deux_facteurs_dominants_et_les_non_evalues():
    r = _calculer()
    resume = scoring.resume(r)
    assert len(resume["facteurs_dominants"]) == 2 and resume["non_evalue"] == ["rentabilite"]
    contributions = [Decimal(f["contribution_points"]) for f in r["facteurs"] if f["evalue"]]
    assert Decimal(resume["facteurs_dominants"][0]["contribution_points"]) == max(contributions)


# ---------------------------------------------------------------------------------------- la mesure de calibration
def test_auc_valeurs_connues():
    f = Fraction
    assert calibration_scoring.auc([f(1), f(2), f(3), f(4)], [0, 0, 1, 1]) == 1
    assert calibration_scoring.auc([f(1), f(2), f(3), f(4)], [1, 1, 0, 0]) == 0
    assert calibration_scoring.auc([f(1), f(1), f(1), f(1)], [0, 1, 0, 1]) == Fraction(1, 2)
    # exemple à la main : positifs {3, 1}, négatifs {2, 0} -> paires (3>2, 3>0, 1<2, 1>0) = 3/4
    assert calibration_scoring.auc([f(3), f(1), f(2), f(0)], [1, 1, 0, 0]) == Fraction(3, 4)
    # ex æquo : positif 2 contre négatifs {2, 1} -> (0.5 + 1) / 2
    assert calibration_scoring.auc([f(2), f(2), f(1)], [1, 0, 0]) == Fraction(3, 4)
    assert calibration_scoring.auc([f(1), f(2)], [1, 1]) is None and calibration_scoring.auc([f(1)], [0]) is None


def test_auc_est_invariante_aux_transformations_monotones_et_a_l_ordre():
    scores = [Fraction(i * i, 7) for i in range(1, 21)]
    issues = [i % 3 == 0 or i % 7 == 0 for i in range(20)]
    issues = [int(x) for x in issues]
    base = calibration_scoring.auc(scores, issues)
    assert calibration_scoring.auc([s * 5 + 3 for s in scores], issues) == base
    paires = list(zip(scores, issues, strict=True))
    paires.reverse()
    assert calibration_scoring.auc([p[0] for p in paires], [p[1] for p in paires]) == base


def test_brier_valeurs_connues():
    f = Fraction
    assert calibration_scoring.brier([f(1), f(0)], [1, 0]) == 0
    assert calibration_scoring.brier([f(1), f(0)], [0, 1]) == 1
    assert calibration_scoring.brier([f(1, 2)] * 4, [0, 1, 0, 1]) == Fraction(1, 4)
    assert calibration_scoring.brier([f(3, 10), f(7, 10)], [0, 1]) == Fraction(9, 100)


def test_regression_isotone_est_monotone_et_conserve_la_moyenne():
    f = Fraction
    scores = [f(i) for i in range(1, 11)]
    issues = [0, 1, 0, 0, 1, 1, 0, 1, 1, 1]
    blocs = calibration_scoring.isotone(scores, issues)
    probabilites = [b[2] for b in blocs]
    assert probabilites == sorted(probabilites), "monotone croissante"
    assert sum(b[2] * b[3] for b in blocs) == sum(issues), "la moyenne globale est conservée"
    assert sum(b[3] for b in blocs) == len(issues)
    # cas d'école : 1, 0 (violation) -> un bloc de 1/2
    assert calibration_scoring.isotone([f(1), f(2)], [1, 0]) == [(f(1), f(2), f(1, 2), 2)]
    # taille minimale : les petits blocs sont fondus dans leur voisin, la monotonie reste
    gros = calibration_scoring.isotone(scores, issues, taille_min=4)
    assert all(b[3] >= 4 for b in gros) or len(gros) == 1
    assert [b[2] for b in gros] == sorted(b[2] for b in gros)


def test_la_calibration_est_reproductible_monotone_et_dit_qu_elle_est_fictive():
    r1, v1 = calibration_scoring.mesurer(11, 600)
    r2, v2 = calibration_scoring.mesurer(11, 600)
    assert v1 is None and v2 is None and r1 == r2
    assert (
        r1["jeu"]["nature"] == "fictif_synthetique"
        and r1["jeu"]["effectif_test"] + r1["jeu"]["effectif_entrainement"] == 600
    )
    assert 0.5 < float(r1["auc"]) < 1.0, "le score ordonne mieux que le hasard sur ce jeu fictif"
    assert float(r1["brier"]["calibre"]) < float(r1["brier"]["reference_taux_de_base"])
    assert float(r1["ece"]["calibree"]) < float(r1["ece"]["brute"]), "la calibration réduit l'écart de calibration"
    effectifs = [t["effectif"] for t in r1["courbe_calibration"]["calibree"]]
    assert len(effectifs) == 10 and sum(effectifs) == r1["jeu"]["effectif_test"]
    assert "MÉCANIQUE SEULEMENT" in r1["valeur_probante"] and "synthétique" in r1["valeur_probante"]
    autre, _ = calibration_scoring.mesurer(12, 600)
    assert autre["auc"] != r1["auc"] or autre["brier"] != r1["brier"]


@pytest.mark.parametrize("graine,n", [(-1, 600), (1, 10), (1, 10**6), ("a", 600), (1.5, 600), (True, 600), (1, True)])
def test_parametres_de_calibration_invalides_refuses(graine, n):
    r, v = calibration_scoring.mesurer(graine, n)
    assert r is None and v["code"] == "REJ-PREV-PARAMETRE-INVALIDE"


def test_le_jeu_fictif_ne_porte_aucune_donnee_personnelle_et_est_stable():
    jeu = calibration_scoring.jeu_fictif(3, 50)
    assert jeu == calibration_scoring.jeu_fictif(3, 50) and len(jeu) == 50
    for ligne in jeu:
        assert set(ligne["faits"]) == set(scoring.CHAMPS_FAITS) and ligne["issue"] in (0, 1)
        resultat, verdict = scoring.calculer(ligne["faits"])
        assert verdict is None
    assert calibration_scoring.jeu_fictif(4, 50) != jeu


def test_le_score_est_la_moyenne_ponderee_exacte_des_sous_scores_evalues():
    """Un facteur non évalué sort du calcul : le score est normalisé sur les poids évalués, sans pénalité ni bonus."""
    r = _calculer()  # rentabilité non évaluée : poids évalués = 85
    evalues = [f for f in r["facteurs"] if f["evalue"]]
    assert sum(f["poids"] for f in evalues) == 85
    exact = sum((Fraction(f["poids"]) * Fraction(f["sous_score"]) for f in evalues), Fraction(0)) / 85
    assert abs(Decimal(exact.numerator) / Decimal(exact.denominator) - Decimal(r["score"])) <= Decimal("0.05")
    complet = _calculer(valeur_declaree_cents=10**9, bandes_valeur_cents=[1, 2, 3])
    sous = {f["facteur"]: Fraction(f["sous_score"]) for f in complet["facteurs"]}
    attendu = sum(Fraction(f["poids"]) * sous[f["facteur"]] for f in complet["facteurs"]) / 100
    assert abs(Decimal(attendu.numerator) / Decimal(attendu.denominator) - Decimal(complet["score"])) <= Decimal("0.05")
    # un facteur à 100 non évalué ne change pas le score des autres : mêmes sous-scores, même normalisation
    assert all(Fraction(f["sous_score"]) == sous[f["facteur"]] for f in evalues)
