"""M5-PREV-2, lot A de frontières : mutants 12, 18, 19, 25, 26, 31, 34, 38, 43, 44, 45, 46, 47 et 51.

Ce fichier ne remplace aucun test existant : il ajoute les cas de frontière qui manquaient au balayage indépendant de
`prevision_longue.py`. Les données sont entièrement FICTIVES (AGENTS.md) : 1 000,00 $ de produits, 800,00 $ de charges,
5 000,00 $ de solde de départ, une croissance nulle et une saisonnalité neutre. Aucune valeur d'affaires, aucun nom de
client, aucun montant réel.

Deux familles de cas :

- des comportements PUBLICS (`calculer`) : un montant de 1,00 $ rendu « 0,00 » par une comparaison fautive, une date
  non textuelle qui doit être refusée sans lever, un mois de budget non textuel qui doit être refusé, les bornes d'année
  1900 et 2999 d'un calcul complet ;
- des frontières du LECTEUR de mois (`_mois_valide`), la seule voie observable pour les constantes 1900/2999 et les
  bornes 1/12 : ces constantes ne changent aucun refus public sur une entrée normale, mais elles décident de la
  normalisation interne d'un mois. Un test qui les couvre est donc un test de comportement du lecteur, pas un test
  d'implémentation d'un calcul.

Les mutants 18, 19 et 34 ne changent aucun résultat observable : leur équivalence est prouvée dans RAPPORT.md, pas
seulement affirmée. Les autres mutants doivent faire échouer un test pour le comportement attendu, jamais pour une
erreur de mise en place du test.
"""

from __future__ import annotations

from decimal import Decimal

from m5_financecore import prevision_longue

AUJOURD_HUI = "2026-09-29"
MOIS_HISTORIQUE = ["2026-06", "2026-07", "2026-08"]
SCENARIO = {
    "nom": "base",
    "croissance_revenus_mensuelle": "0",
    "croissance_charges_mensuelle": "0",
    "saisonnalite": ["1"] * 12,
    "delai_encaissement_jours": 0,
    "delai_paiement_jours": 0,
}


def _historique(*, produits="1000.00", charges="800.00", mois=None, ecritures=1, brouillons=0):
    return [
        {
            "mois": m,
            "produits": produits,
            "charges": charges,
            "ecritures": ecritures,
            "brouillons": brouillons,
        }
        for m in (MOIS_HISTORIQUE if mois is None else mois)
    ]


def _config(*scenarios, mois_historique=3):
    return {"mois_historique": mois_historique, "scenarios": list(scenarios) or [dict(SCENARIO)]}


def _calculer(
    *,
    aujourd_hui=AUJOURD_HUI,
    config=None,
    historique=None,
    budget=(),
    carnet=(),
    horizon=6,
    solde="5000.00",
):
    return prevision_longue.calculer(
        aujourd_hui=aujourd_hui,
        horizon_mois=horizon,
        solde_initial=solde,
        historique=_historique() if historique is None else historique,
        budget=list(budget),
        carnet=list(carnet),
        configuration=_config() if config is None else config,
    )


def _code(verdict):
    assert verdict is not None and verdict["code"].startswith("REJ-PREVISION-LONGUE-")
    return verdict["code"]


# ===================================================================================== 12. un montant de 1,00 $
def test_un_montant_de_un_dollar_reste_un_dollar():
    """Un solde de 1,00 $ ne doit jamais être rendu « 0.00 » : 1,00 n'est pas le zéro connu du mois.

    Le grand livre fictif est à zéro ; le solde reste donc exactement 1,00 $ sur les six lignes. La mutation
    `arrondi == 0 -> == 1` transforme ce 1,00 en « 0.00 » dès l'affichage.
    """
    resultat, verdict = _calculer(
        config=_config(mois_historique=3),
        historique=_historique(produits="0.00", charges="0.00"),
        solde="1.00",
    )

    assert verdict is None, verdict
    scenario = resultat["scenarios"][0]
    assert resultat["solde_initial"] == "1.00"
    assert scenario["lignes"][0]["solde_projete"] == "1.00"
    assert scenario["solde_final"] == "1.00"


# ===================================================================================== 18, 19. plafond des montants
def test_le_plafond_des_montants_reste_hors_de_portee_du_motif():
    """Le plus grand montant admis par le motif est 999 999 999 999,99 : il reste sous 1 000 000 000 000.

    Ce test fixe la frontière et sert de preuve exécutable à l'équivalence des mutants 18 (`or -> and`) et 19
    (`> -> >=`) : le motif `_MONTANT` n'accepte que douze chiffres entiers, donc la branche `abs(valeur) >
    _MONTANT_MAX` n'est jamais atteinte, et la bascule `>=` ne l'est pas davantage.
    """
    assert Decimal("1000000000000") == prevision_longue._MONTANT_MAX
    borne_motif = prevision_longue._montant("999999999999.99")
    assert borne_motif == Decimal("999999999999.99")
    assert abs(borne_motif) < prevision_longue._MONTANT_MAX
    assert prevision_longue._montant("1000000000000.00") is None
    assert prevision_longue._montant("1000000000000") is None


# ===================================================================================== 25, 26. plafond des taux
def test_le_lecteur_de_taux_borne_a_cent_inclus():
    """Le lecteur de taux refuse au-delà de 100 (valeur absolue) et accepte exactement 100.

    C'est une garde défensive du lecteur : les bornes métier restent plus strictes (croissance ]-1, 1],
    saisonnalité 0 à 3). Elle est néanmoins observable sur le lecteur, et c'est elle que les mutants 25 (`or -> and`)
    et 26 (`> -> >=`) déplacent.
    """
    assert prevision_longue._taux("100") == Decimal("100")
    assert prevision_longue._taux("-100") == Decimal("-100")
    assert prevision_longue._taux("100.000001") is None
    assert prevision_longue._taux("-100.000001") is None


def test_un_taux_absurde_reste_refuse_par_les_bornes_metier():
    """Même si le lecteur laissait passer 100,000001, les bornes métier le refusent toujours.

    La croissance est bornée à ]-1, 1] et la saisonnalité à 0–3. Ce test public documente que les mutants 25 et 26 ne
    changent pas le refus d'affaires : leur différence est confinée au lecteur, et c'est le test du lecteur qui les tue.
    """
    scenario = {**SCENARIO, "croissance_revenus_mensuelle": "100.000001"}
    resultat, verdict = _calculer(config=_config(scenario))
    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-CROISSANCE-INVALIDE"

    saisonnalite = ["1"] * 12
    saisonnalite[0] = "100.000001"
    scenario = {**SCENARIO, "saisonnalite": saisonnalite}
    resultat, verdict = _calculer(config=_config(scenario))
    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-SAISONNALITE-INVALIDE"


# ===================================================================================== 31. date non textuelle
def test_une_date_non_textuelle_est_refusee_sans_lever():
    """Une date qui n'est pas un texte doit produire le refus DATE-INVALIDE, jamais une exception Python.

    `None`, un entier et des octets sont des entrées malformées : le module doit rester fail-closed et dire quoi
    corriger. La mutation 31 retire le contrôle de longueur du chemin des non-textes et fait lever `len(None)` (ou
    `date.fromisoformat(bytes)`), ce qui casse ce contrat.
    """
    for brut in (None, 20260929, b"2026-09-29"):
        resultat, verdict = _calculer(aujourd_hui=brut)
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-DATE-INVALIDE"


def test_une_date_compacte_ou_non_ascii_reste_refusee():
    """Les formes compacte, semaine ISO et à chiffres non ASCII ne sont pas le format AAAA-MM-JJ exigé.

    `date.fromisoformat` sait lire « 20260929 » ou « 2026-W01-1 », mais le module exige le texte canonique de dix
    caractères : la comparaison finale `valeur.isoformat() == brut` rejette ces formes. C'est aussi ce qui rend le
    mutant 34 (`or -> and`) équivalent pour tout texte ordinaire : il saute le contrôle de longueur, mais la
    comparaison canonique refuse la même entrée.
    """
    for brut in ("20260929", "2026-W01-1", "٢٠٢٦-٠١-٠١"):
        resultat, verdict = _calculer(aujourd_hui=brut)
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-DATE-INVALIDE"


# ===================================================================================== 38. mois non textuel
def test_un_mois_non_textuel_du_budget_est_refuse():
    """Un mois de budget qui n'est pas un texte doit être refusé, pas provoquer `len()` ou `re.fullmatch()` sur un type.

    La mutation 38 (`or -> and`) fait passer un entier dans `isascii()` (AttributeError) et des octets dans
    `re.fullmatch` (TypeError) : le refus BUDGET-INVALIDE attendu disparaît.
    """
    for mois in (202610, b"2026-10"):
        budget = [{"mois": mois, "produits": "100.00", "charges": None}]
        resultat, verdict = _calculer(budget=budget)
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-BUDGET-INVALIDE"


# ===================================================================================== 43, 44, 45. bornes 1900/2999
def test_l_annee_1900_est_acceptee_comme_borne_basse():
    """Un mois de janvier 1900 est normalisable, et un calcul complet peut partir de juin 1900.

    L'historique fictif de mars à mai 1900 et le solde de 5 000,00 $ donnent 6 × 200,00 $ = 6 200,00 $. Les mutants
    43 (1900 -> 1901) et 44 (`1900 <= annee` -> `<`) rejettent 1900 et faussent la fenêtre historique.
    """
    assert prevision_longue._mois_valide("1900-01") == (1900, 1)
    resultat, verdict = _calculer(
        aujourd_hui="1900-06-15",
        config=_config(mois_historique=3),
        historique=_historique(mois=["1900-03", "1900-04", "1900-05"]),
    )

    assert verdict is None, verdict
    assert resultat["premier_mois"] == "1900-07"
    assert resultat["scenarios"][0]["solde_final"] == "6200.00"


def test_l_annee_2999_est_acceptee_comme_borne_haute():
    """Un mois de décembre 2999 est normalisable, et un calcul complet peut partir de juin 2999.

    Le calcul reste dans l'année 2999 (juillet à décembre). Le mutant 45 (`annee <= 2999` -> `<`) rejette 2999 et
    casse la fenêtre historique ; les mutants 46, 47 et 51 ne touchent pas cette borne.
    """
    assert prevision_longue._mois_valide("2999-12") == (2999, 12)
    resultat, verdict = _calculer(
        aujourd_hui="2999-06-15",
        config=_config(mois_historique=3),
        historique=_historique(mois=["2999-03", "2999-04", "2999-05"]),
    )

    assert verdict is None, verdict
    assert resultat["premier_mois"] == "2999-07"
    assert resultat["scenarios"][0]["solde_final"] == "6200.00"


# ===================================================================================== 46, 47, 51. années et mois
def test_les_annees_hors_1900_2999_sont_refusees():
    """Le lecteur de mois borne l'année à 1900–2999 : 1899, 3000, 0000 et 9999 sont hors domaine.

    Le mutant 46 (2999 -> 3000) accepte 3000-01 ; le mutant 47 (`and -> or`) accepte toute année dont le mois est
    valide, donc 1899-12, 0000-01 et 9999-12.
    """
    for mois in ("1899-12", "3000-01", "0000-01", "9999-12"):
        assert prevision_longue._mois_valide(mois) is None


def test_le_mois_13_est_refuse_et_le_mois_12_accepte():
    """Le lecteur de mois borne le numéro à 1–12 : décembre passe, le mois 13 et le mois 0 sont refusés.

    Le mutant 51 (12 -> 13) accepte 2026-13 ; le mutant 47 l'accepte aussi par sa disjonction, mais il est déjà tué
    par le test des années hors bornes.
    """
    assert prevision_longue._mois_valide("2026-12") == (2026, 12)
    assert prevision_longue._mois_valide("2026-13") is None
    assert prevision_longue._mois_valide("2026-00") is None
