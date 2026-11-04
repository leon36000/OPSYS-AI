"""M5-PREV-2, lot B : frontières de dates, de sources, de solde et de pagination.

Ce fichier complète `test_prevision_longue.py` sans le modifier. Il exerce des frontières
laissées sans test par le lot précédent, avec des données fictives et des résultats calculés à
la main dans les docstrings :

- inclusion du premier jour du premier mois et du dernier jour du dernier mois dans l'horizon ;
- exclusion de la veille et du lendemain de l'horizon, comptées séparément ;
- message « mois récurrents » uniquement quand une source manque réellement ;
- zéro de trésorerie, qui n'est pas un « mois sous zéro » ;
- bornes de pagination de `vue` (depart = 0, limite = 1 et 24) et refus des types malformés.

Aucune valeur d'affaires n'est proposée ici : les hypothèses sont déclarées et fictives.
"""

from __future__ import annotations

from m5_financecore import prevision_longue

AUJOURD_HUI = "2026-09-29"
MOIS_HISTORIQUE = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
MOIS_PROJETES = ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
SCENARIO = {
    "nom": "base",
    "croissance_revenus_mensuelle": "0",
    "croissance_charges_mensuelle": "0",
    "saisonnalite": ["1"] * 12,
    "delai_encaissement_jours": 0,
    "delai_paiement_jours": 0,
}


def _historique(produits="1000.00", charges="800.00"):
    return [
        {"mois": m, "produits": produits, "charges": charges, "ecritures": 1, "brouillons": 0}
        for m in MOIS_HISTORIQUE
    ]


def _config():
    return {"mois_historique": 6, "scenarios": [dict(SCENARIO)]}


def _calculer(*, historique=None, budget=(), carnet=(), solde="5000.00"):
    return prevision_longue.calculer(
        aujourd_hui=AUJOURD_HUI,
        horizon_mois=6,
        solde_initial=solde,
        historique=_historique() if historique is None else historique,
        budget=list(budget),
        carnet=list(carnet),
        configuration=_config(),
    )


def _echeance(jour, montant, contrat="CTR-1", rang="1"):
    return {"date": jour, "montant": montant, "contrat_id": contrat, "echeance": rang}


def _scenario(resultat):
    return resultat["scenarios"][0]


def _solde(resultat):
    return [ligne["solde_projete"] for ligne in _scenario(resultat)["lignes"]]


def _limites_recurrentes(resultat):
    return [limite for limite in resultat["limites"] if "mois sans échéance ni budget" in limite]


# ===================================================================== 1. bornes exactes de l'horizon
def test_le_premier_jour_du_premier_mois_appartient_a_l_horizon():
    """2026-10-01 est le premier jour d'octobre, donc dans l'horizon : 500 de carnet, pas une échéance échue.

    5000 + (500 − 800) = 4700 en octobre ; les cinq mois suivants valent 200 chacun : 4900 à 5700.
    """
    resultat, verdict = _calculer(carnet=[_echeance("2026-10-01", "500.00")])

    assert verdict is None, verdict
    octobre = _scenario(resultat)["lignes"][0]
    assert octobre["mois"] == "2026-10"
    assert octobre["contrats"] == "500.00"
    assert octobre["revenus"] == "500.00"
    assert octobre["sources_produits"] == ["carnet"]
    assert resultat["couverture"]["echeances_echues"] == {"nombre": 0, "montant": "0.00"}
    assert resultat["couverture"]["echeances_hors_horizon"] == {"nombre": 0, "montant": "0.00"}
    assert _solde(resultat) == ["4700.00", "4900.00", "5100.00", "5300.00", "5500.00", "5700.00"]


def test_le_dernier_jour_du_dernier_mois_appartient_a_l_horizon():
    """2027-03-31 est le dernier jour de mars, donc dans l'horizon : 500 de carnet, pas hors horizon.

    Le solde final vaut 5000 + 5 × 200 + (500 − 800) = 5700 ; l'échéance n'est ni échue ni hors horizon.
    """
    resultat, verdict = _calculer(carnet=[_echeance("2027-03-31", "500.00")])

    assert verdict is None, verdict
    mars = _scenario(resultat)["lignes"][-1]
    assert mars["mois"] == "2027-03"
    assert mars["contrats"] == "500.00"
    assert mars["revenus"] == "500.00"
    assert mars["sources_produits"] == ["carnet"]
    assert resultat["couverture"]["echeances_echues"] == {"nombre": 0, "montant": "0.00"}
    assert resultat["couverture"]["echeances_hors_horizon"] == {"nombre": 0, "montant": "0.00"}
    assert _solde(resultat) == ["5200.00", "5400.00", "5600.00", "5800.00", "6000.00", "5700.00"]


def test_la_veille_et_le_lendemain_de_l_horizon_sont_exclus_et_dits():
    """2026-09-30 est échue, 2027-04-01 est hors horizon ; aucun des deux n'entre dans la projection.

    La projection reste celle de l'historique seul (200 par mois), et la couverture porte
    exactement 300 échus et 700 hors horizon.
    """
    carnet = [_echeance("2026-09-30", "300.00", rang="1"), _echeance("2027-04-01", "700.00", rang="2")]
    resultat, verdict = _calculer(carnet=carnet)

    assert verdict is None, verdict
    assert _solde(resultat) == ["5200.00", "5400.00", "5600.00", "5800.00", "6000.00", "6200.00"]
    assert resultat["couverture"]["echeances_echues"] == {"nombre": 1, "montant": "300.00"}
    assert resultat["couverture"]["echeances_hors_horizon"] == {"nombre": 1, "montant": "700.00"}


# ===================================================================== 2. sources et message récurrent
def test_aucun_mois_recurrent_quand_produits_et_charges_sont_budgetes():
    """Six mois de budget couvrent produits et charges : aucun message de repli sur l'historique.

    Le message n'est autorisé que si un mois tire réellement une source de la moyenne du grand livre.
    """
    budget = [{"mois": m, "produits": "1000.00", "charges": "800.00"} for m in MOIS_PROJETES]
    resultat, verdict = _calculer(budget=budget)

    assert verdict is None, verdict
    assert _limites_recurrentes(resultat) == []
    assert all(ligne["sources_produits"] == ["budget"] for ligne in _scenario(resultat)["lignes"])
    assert all(ligne["sources_charges"] == ["budget"] for ligne in _scenario(resultat)["lignes"])


def test_un_mois_avec_carnet_et_charges_historiques_reste_recurrent():
    """Un carnet daté couvre les produits, mais les charges viennent de l'historique : le mois est récurrent.

    Le message est dû dès qu'UNE des deux sources est l'historique, pas seulement quand les deux le sont.
    """
    carnet = [_echeance(f"{m}-15", "100.00", contrat=f"CTR-{i}", rang="1") for i, m in enumerate(MOIS_PROJETES, 1)]
    resultat, verdict = _calculer(carnet=carnet)

    assert verdict is None, verdict
    assert len(_limites_recurrentes(resultat)) == 1
    assert all(ligne["sources_produits"] == ["carnet"] for ligne in _scenario(resultat)["lignes"])
    assert all(ligne["sources_charges"] == ["historique"] for ligne in _scenario(resultat)["lignes"])


# ===================================================================== 3. zéro de trésorerie
def test_un_solde_projete_a_zero_n_est_pas_sous_zero():
    """800 − 800 = 0 chaque mois : le solde minimal est 0.00 et aucun mois n'est « sous zéro ».

    La règle est stricte (`< 0`) : un solde nul est connu et sain, pas un découvert.
    """
    resultat, verdict = _calculer(solde="0.00", historique=_historique(produits="800.00", charges="800.00"))

    assert verdict is None, verdict
    assert _solde(resultat) == ["0.00"] * 6
    assert _scenario(resultat)["solde_final"] == "0.00"
    assert _scenario(resultat)["solde_minimal"] == "0.00"
    assert _scenario(resultat)["mois_sous_zero"] == []


def test_un_solde_positif_inferieur_a_un_dollar_n_est_pas_sous_zero():
    """0.50 reste positif : il ne doit pas être classé sous zéro par une borne à 1.00."""
    resultat, verdict = _calculer(solde="0.50", historique=_historique(produits="800.00", charges="800.00"))

    assert verdict is None, verdict
    assert _solde(resultat) == ["0.50"] * 6
    assert _scenario(resultat)["solde_minimal"] == "0.50"
    assert _scenario(resultat)["mois_sous_zero"] == []


# ===================================================================== 4. pagination de la vue
def _complet():
    resultat, verdict = _calculer()
    assert verdict is None, verdict
    return resultat


def test_la_vue_accepte_un_depart_a_zero():
    """depart = 0 est la première page légitime : la borne basse est 0, pas 1."""
    corps, verdict = prevision_longue.vue(_complet(), scenario="base", depart=0, limite=2)

    assert verdict is None, verdict
    assert corps["scenario"]["lignes"][0]["mois"] == "2026-10"
    assert len(corps["scenario"]["lignes"]) == 2
    assert corps["scenario"]["lignes_total"] == 6
    assert corps["scenario"]["prochain_depart"] == 2


def test_la_vue_accepte_une_limite_de_un():
    """limite = 1 est la page minimale déclarée (1 à 24) et rend exactement une ligne."""
    corps, verdict = prevision_longue.vue(_complet(), scenario="base", depart=1, limite=1)

    assert verdict is None, verdict
    assert [ligne["mois"] for ligne in corps["scenario"]["lignes"]] == ["2026-11"]
    assert corps["scenario"]["prochain_depart"] == 2


def test_la_vue_accepte_une_limite_de_vingt_quatre():
    """limite = 24 est la borne haute déclarée : elle est acceptée même si l'horizon a six lignes.

    La tranche rend les cinq lignes restantes après depart = 1, sans erreur et sans ligne inventée.
    """
    corps, verdict = prevision_longue.vue(_complet(), scenario="base", depart=1, limite=24)

    assert verdict is None, verdict
    assert len(corps["scenario"]["lignes"]) == 5
    assert corps["scenario"]["lignes"][-1]["mois"] == "2027-03"
    assert corps["scenario"]["lignes_total"] == 6
    assert corps["scenario"]["prochain_depart"] is None


def test_la_vue_refuse_les_bornes_et_types_malformes():
    """Un depart négatif ou un type non entier, une limite hors 1–24 ou non entière : refus explicite.

    Aucun de ces cas ne rend une page partielle ni une valeur par défaut.
    """
    for depart in (-1, True, "0", 1.0):
        corps, verdict = prevision_longue.vue(_complet(), scenario="base", depart=depart, limite=2)
        assert corps is None
        assert verdict is not None and verdict["code"] == "REJ-PREVISION-LONGUE-LIMITE-INVALIDE"

    for limite in (0, 25, True, 1.0):
        corps, verdict = prevision_longue.vue(_complet(), scenario="base", depart=1, limite=limite)
        assert corps is None
        assert verdict is not None and verdict["code"] == "REJ-PREVISION-LONGUE-LIMITE-INVALIDE"


# ===================================================================== 5. entrées de carnet malformées
def test_une_echeance_au_premier_jour_avec_une_date_malformee_est_refusee():
    """La date de frontière ne doit pas être acceptée par approximation : seule AAAA-MM-JJ exacte passe."""
    for jour in ("2026-10-1", "2026-10-01T00:00:00", "2026-13-01", "2026-02-30", 20261001):
        resultat, verdict = _calculer(carnet=[_echeance(jour, "500.00")])
        assert resultat is None
        assert verdict is not None and verdict["code"] == "REJ-PREVISION-LONGUE-CARNET-DATE-INVALIDE"


def test_une_echeance_au_premier_jour_avec_un_montant_malforme_ou_nul_est_refusee():
    """Un montant de carnet doit être un texte décimal strictement positif ; 0, un flottant ou 3 décimales refusent."""
    for montant in ("0.00", "-1.00", "1.234", 500.0, "abc"):
        resultat, verdict = _calculer(carnet=[_echeance("2026-10-01", montant)])
        assert resultat is None
        assert verdict is not None and verdict["code"] == "REJ-PREVISION-LONGUE-CARNET-INVALIDE"


def test_une_echeance_sans_toutes_ses_cles_est_refusee():
    """La forme du carnet est fermée : une clé absente ou inconnue refuse l'échéance, elle n'est pas corrigée."""
    incomplete = {"date": "2026-10-01", "montant": "500.00", "contrat_id": "CTR-1"}
    inconnue = {**_echeance("2026-10-01", "500.00"), "client": "fictif"}

    for entree in (incomplete, inconnue):
        resultat, verdict = _calculer(carnet=[entree])
        assert resultat is None
        assert verdict is not None and verdict["code"] == "REJ-PREVISION-LONGUE-CARNET-INVALIDE"
