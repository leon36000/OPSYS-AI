"""Mathématiques financières déterministes en `Decimal` (tranche 1 du moteur de calcul, `docs/moteur-calcul.md`).

Module PUR : aucune horloge, aucun registre, aucun flottant. Il reçoit des `Decimal` (et des entiers) DÉJÀ validés par
`moteur_calcul.py` et lève `ValueError` sur une erreur d'appel du code ; les refus typés destinés à l'agent sont ceux
de `moteur_calcul.py`. Chaque fonction publique calcule dans son propre contexte (`CONTEXTE`, 50 chiffres
significatifs, arrondi interne ROUND_HALF_EVEN), indépendant de celui de l'appelant.

CONVENTIONS (toutes déclarées, aucune supposée en silence) :
- un taux est une fraction PAR PÉRIODE (« 0.05 » = 5 % par période) ; les flux sont en fin de période, le flux d'indice
  0 au temps 0 (non actualisé) ;
- montants monétaires arrondis au cent par ROUND_HALF_UP, et seulement là où la méthode le dit (versement d'un prêt,
  intérêt d'une période, montant affiché) ; tout le reste garde 50 chiffres significatifs ;
- TRI : racine de VAN(r) = 0 sur [TAUX_MIN_TRI, TAUX_MAX_TRI], par bissection protégée + Newton (pas de Newton accepté
  seulement s'il reste dans l'intervalle encadrant et s'il réduit assez l'erreur, sinon bissection). L'UNICITÉ n'est
  garantie que pour UN changement de signe des flux (règle de Descartes en x = 1/(1+r) : exactement une racine r > -1).
  Plusieurs changements de signe : balayage déterministe d'une grille, les racines trouvées sont dites, mais AUCUN TRI
  n'est rendu (statut MULTIPLE, NON_GARANTI ou INDEFINI) : jamais un nombre choisi parmi plusieurs ;
- amortissement : versement constant P·i / (1 − (1+i)^−n) arrondi au cent ; intérêt de chaque période arrondi au cent ;
  la DERNIÈRE échéance est ajustée pour que la somme des capitaux égale le principal au cent ; convention canadienne
  (Loi sur l'intérêt, taux hypothécaire composé semestriellement) : i = (1 + j/2)^(2/m) − 1.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Any

__all__ = [
    "CONTEXTE", "CONVENTIONS_TAUX", "FREQUENCES", "TAUX_MAX_TRI", "TAUX_MIN_TRI", "TOLERANCE_TRI",
    "TOLERANCE_VAN_RELATIVE", "amortir", "au_cent", "changements_de_signe", "comparer_credit_bail_achat",
    "delai_recuperation", "point_mort", "taux_periodique", "tri", "tri_modifie", "valeur_actuelle", "valeur_future",
    "van", "versement_constant",
]

PRECISION = 50
CONTEXTE = Context(prec=PRECISION, rounding=ROUND_HALF_EVEN, Emax=999_999, Emin=-999_999)
_CENT = Decimal("0.01")
_UN = Decimal(1)
_ZERO = Decimal(0)

FREQUENCES = {"mensuelle": 12, "aux_deux_semaines": 26, "hebdomadaire": 52}
# Listes fermées CHOISIES par l'appelant (comme `CLASSE_RETENTION`) : une valeur inconnue est un refus typé, jamais une
# classification que M5 déduirait ; d'où des ensembles, sans échappatoire D-032 (`conformite.verifier_conformite`).
CONVENTIONS_TAUX = frozenset({"nominal_compose_a_la_frequence", "canadienne_semestrielle", "effectif_annuel"})

TAUX_MIN_TRI = Decimal("-0.9999")
TAUX_MAX_TRI = Decimal("100")
TOLERANCE_TRI = Decimal("1e-32")  # largeur de l'intervalle encadrant à l'arrêt
QUANTUM_TRI = Decimal("1e-30")  # le TRI rendu, arrondi ROUND_HALF_EVEN
TOLERANCE_VAN_RELATIVE = Decimal("1e-20")  # |VAN(TRI)| ≤ 1e-20 × max(1, Σ|flux|)
ITERATIONS_MAX = 400
_QUANTUM_DELAI = Decimal("0.0001")


def au_cent(valeur: Decimal) -> Decimal:
    # Dans CONTEXTE (50 chiffres) et non dans celui de l'appelant : à 28 chiffres, un montant de plus de 26 chiffres
    # entiers (projet à 50 ans à 100 % de croissance) levait `InvalidOperation` au lieu d'un résultat.
    with localcontext(CONTEXTE):
        return valeur.quantize(_CENT, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------------------------------- valeurs et VAN
def valeur_actuelle(montant: Decimal, taux: Decimal, periodes: int) -> Decimal:
    """VA = montant / (1 + taux)^periodes (non arrondie)."""
    with localcontext(CONTEXTE):
        return montant / (_UN + taux) ** periodes


def valeur_future(montant: Decimal, taux: Decimal, periodes: int) -> Decimal:
    """VF = montant × (1 + taux)^periodes (non arrondie)."""
    with localcontext(CONTEXTE):
        return montant * (_UN + taux) ** periodes


def _van(taux: Decimal, flux: Sequence[Decimal]) -> Decimal:
    """Σ c_t / (1+r)^t par Horner en v = 1/(1+r) (dans le contexte courant)."""
    v = _UN / (_UN + taux)
    acc = _ZERO
    for c in reversed(flux):
        acc = acc * v + c
    return acc


def _derivee_van(taux: Decimal, flux: Sequence[Decimal]) -> Decimal:
    """dVAN/dr = Σ −t·c_t / (1+r)^(t+1)."""
    v = _UN / (_UN + taux)
    acc = _ZERO
    for t in range(len(flux) - 1, 0, -1):
        acc = acc * v - t * flux[t]
    # acc = Σ_{t≥1} −t c_t v^(t−1) ; il reste à multiplier par v².
    return acc * v * v


def van(taux: Decimal, flux: Sequence[Decimal]) -> Decimal:
    """VAN = Σ_{t=0..n} c_t / (1+taux)^t (flux 0 au temps 0), non arrondie."""
    with localcontext(CONTEXTE):
        return _van(taux, flux)


# ---------------------------------------------------------------------------------------------------- TRI
def changements_de_signe(flux: Sequence[Decimal]) -> int:
    """Nombre de changements de signe de la suite des flux NON NULS (les zéros sont ignorés)."""
    signes = [c > 0 for c in flux if c != 0]
    return sum(1 for a, b in zip(signes, signes[1:], strict=False) if a != b)


def _signe(x: Decimal) -> int:
    return (x > 0) - (x < 0)


def _racine(f: Callable[[Decimal], Decimal], df: Callable[[Decimal], Decimal], bas: Decimal, haut: Decimal,
            f_bas: Decimal) -> tuple[Decimal, int]:
    """Racine de f sur [bas, haut] où f change de signe : Newton protégé par l'intervalle encadrant (rtsafe)."""
    deux = Decimal(2)
    x = (bas + haut) / deux
    pas_precedent = haut - bas
    pas = pas_precedent
    s_bas = _signe(f_bas)
    for iteration in range(1, ITERATIONS_MAX + 1):
        fx = f(x)
        if fx == 0:
            return x, iteration
        if _signe(fx) == s_bas:
            bas = x
        else:
            haut = x
        if haut - bas <= TOLERANCE_TRI:
            return (bas + haut) / deux, iteration
        dfx = df(x)
        candidat = None
        if dfx != 0 and abs(deux * fx) < abs(pas_precedent * dfx):
            candidat = x - fx / dfx
            if not bas < candidat < haut:
                candidat = None
        pas_precedent = pas
        nouveau = (bas + haut) / deux if candidat is None else candidat
        pas = abs(nouveau - x)
        x = nouveau
        if pas <= TOLERANCE_TRI:
            return x, iteration
    return x, ITERATIONS_MAX


def _quantifier_tri(r: Decimal) -> Decimal:
    """Un taux rendu à QUANTUM_TRI (ROUND_HALF_EVEN), jamais « −0 »."""
    valeur = r.quantize(QUANTUM_TRI, rounding=ROUND_HALF_EVEN)
    return valeur.copy_abs() if valeur == 0 else valeur


def _encadre(f: Callable[[Decimal], Decimal], valeur: Decimal) -> bool:
    """Vrai si la VAN change de signe (ou s'annule) entre `valeur − QUANTUM_TRI` et `valeur + QUANTUM_TRI` : la racine
    est alors connue à un quantum près, même si le résidu |VAN(valeur)| dépasse la tolérance relative (là où la pente de
    la VAN est de 1e14, un écart d'un quantum vaut déjà 1e-16)."""
    return _signe(f(valeur - QUANTUM_TRI)) * _signe(f(valeur + QUANTUM_TRI)) <= 0


def _grille_tri() -> list[Decimal]:
    """Grille déterministe de balayage : pas de 0,01 de −0,9999 à 1, puis ×1,1 jusqu'à 100."""
    points = [TAUX_MIN_TRI]
    r = Decimal("-0.99")
    while r <= 1:
        points.append(r)
        r += Decimal("0.01")
    r = Decimal("1.1")
    while r < TAUX_MAX_TRI:
        points.append(r)
        r = (r * Decimal("1.1")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    points.append(TAUX_MAX_TRI)
    return points


def tri(flux: Sequence[Decimal]) -> dict[str, Any]:
    """Le TRI et son statut. Rend `{"statut", "tri", "racines", "changements_de_signe", "iterations",
    "van_au_tri", "tolerance_van"}` : `tri` n'est un nombre que si le statut est UNIQUE.

    Statuts : AUCUN_CHANGEMENT_DE_SIGNE (aucun TRI n'existe), UNIQUE, HORS_BORNES (un changement de signe, racine hors
    de [TAUX_MIN_TRI, TAUX_MAX_TRI]), MULTIPLE (au moins deux racines trouvées), NON_GARANTI (plusieurs changements de
    signe, une seule racine trouvée par le balayage : rien ne prouve qu'elle soit la seule), INDEFINI (plusieurs
    changements de signe, aucune racine trouvée : une racine double peut exister)."""
    with localcontext(CONTEXTE):
        flux = list(flux)
        k = changements_de_signe(flux)
        echelle = max(_UN, sum((abs(c) for c in flux), _ZERO))
        tolerance_van = TOLERANCE_VAN_RELATIVE * echelle
        base = {"changements_de_signe": k, "tolerance_van": format(tolerance_van, "E"), "iterations": 0}
        if k == 0:
            return {**base, "statut": "AUCUN_CHANGEMENT_DE_SIGNE", "tri": None, "racines": [], "van_au_tri": None}

        def f(r: Decimal) -> Decimal:
            return _van(r, flux)

        def df(r: Decimal) -> Decimal:
            return _derivee_van(r, flux)

        if k == 1:
            f_bas, f_haut = f(TAUX_MIN_TRI), f(TAUX_MAX_TRI)
            if f_bas == 0 or f_haut == 0:
                racine, iterations = (TAUX_MIN_TRI if f_bas == 0 else TAUX_MAX_TRI), 0
            elif _signe(f_bas) == _signe(f_haut):
                return {**base, "statut": "HORS_BORNES", "tri": None, "racines": [], "van_au_tri": None}
            else:
                racine, iterations = _racine(f, df, TAUX_MIN_TRI, TAUX_MAX_TRI, f_bas)
            valeur = _quantifier_tri(racine)
            residu = f(valeur)
            if abs(residu) > tolerance_van and not _encadre(f, valeur):
                raise ArithmeticError(f"TRI : |VAN(TRI)| = {residu} dépasse la tolérance {tolerance_van}")
            return {**base, "statut": "UNIQUE", "tri": valeur, "racines": [valeur], "iterations": iterations,
                    "van_au_tri": format(residu, "E")}

        grille = _grille_tri()
        valeurs = [f(r) for r in grille]
        racines: list[Decimal] = []
        iterations_total = 0
        for i in range(len(grille) - 1):
            r0, r1, v0, v1 = grille[i], grille[i + 1], valeurs[i], valeurs[i + 1]
            if v0 == 0:
                racines.append(_quantifier_tri(r0))
            elif v1 != 0 and _signe(v0) != _signe(v1):
                racine, iterations = _racine(f, df, r0, r1, v0)
                iterations_total += iterations
                racines.append(_quantifier_tri(racine))
        if valeurs[-1] == 0:
            racines.append(_quantifier_tri(grille[-1]))
        statut = "MULTIPLE" if len(racines) >= 2 else ("NON_GARANTI" if racines else "INDEFINI")
        return {**base, "statut": statut, "tri": None, "racines": racines, "iterations": iterations_total,
                "van_au_tri": None}


def tri_modifie(flux: Sequence[Decimal], taux_financement: Decimal, taux_reinvestissement: Decimal) -> Decimal | None:
    """TRIM = (VF des flux positifs au taux de réinvestissement / VA des flux négatifs au taux de financement)^(1/n)
    − 1, n = nombre de périodes. `None` s'il n'y a pas à la fois un flux positif et un flux négatif (indéfini)."""
    with localcontext(CONTEXTE):
        n = len(flux) - 1
        if n < 1:
            raise ValueError("TRI modifié : au moins deux flux")
        va_negatifs = sum((-c / (_UN + taux_financement) ** t for t, c in enumerate(flux) if c < 0), _ZERO)
        vf_positifs = sum((c * (_UN + taux_reinvestissement) ** (n - t) for t, c in enumerate(flux) if c > 0), _ZERO)
        if va_negatifs == 0 or vf_positifs == 0:
            return None
        return (vf_positifs / va_negatifs) ** (_UN / n) - _UN


def delai_recuperation(flux: Sequence[Decimal], taux: Decimal | None = None) -> dict[str, Any]:
    """Délai de récupération (simple si `taux` est `None`, actualisé sinon) : la première période où le cumul, d'abord
    négatif, devient ≥ 0, interpolée linéairement dans la période (flux répartis uniformément, convention déclarée).
    `{"statut": RECUPERE | NON_RECUPERE | SANS_INVESTISSEMENT, "periodes": Decimal | None,
    "redevient_negatif": bool}`."""
    with localcontext(CONTEXTE):
        valeurs = list(flux) if taux is None else [c / (_UN + taux) ** t for t, c in enumerate(flux)]
        cumul = valeurs[0]
        if cumul >= 0:
            return {"statut": "SANS_INVESTISSEMENT", "periodes": None, "redevient_negatif": False}
        resultat = None
        for t in range(1, len(valeurs)):
            precedent, cumul = cumul, cumul + valeurs[t]
            if resultat is None and precedent < 0 <= cumul:
                fraction = -precedent / valeurs[t]
                resultat = (Decimal(t - 1) + fraction).quantize(_QUANTUM_DELAI, rounding=ROUND_HALF_UP)
            elif resultat is not None and cumul < 0:
                return {"statut": "RECUPERE", "periodes": resultat, "redevient_negatif": True}
        if resultat is None:
            return {"statut": "NON_RECUPERE", "periodes": None, "redevient_negatif": False}
        return {"statut": "RECUPERE", "periodes": resultat, "redevient_negatif": False}


# ------------------------------------------------------------------------------------------ amortissement
def taux_periodique(taux_annuel: Decimal, frequence: str, convention: str) -> Decimal:
    """Taux par versement d'un taux annuel `taux_annuel`, selon la convention :
    nominal_compose_a_la_frequence : j/m ; canadienne_semestrielle : (1 + j/2)^(2/m) − 1 ; effectif_annuel :
    (1 + j)^(1/m) − 1."""
    m = FREQUENCES[frequence]
    with localcontext(CONTEXTE):
        if convention == "nominal_compose_a_la_frequence":
            return taux_annuel / m
        if convention == "canadienne_semestrielle":
            return (_UN + taux_annuel / 2) ** (Decimal(2) / m) - _UN
        if convention == "effectif_annuel":
            return (_UN + taux_annuel) ** (_UN / m) - _UN
    raise ValueError(f"convention inconnue : {convention!r}")


def versement_constant(principal: Decimal, taux: Decimal, n: int) -> Decimal:
    """Versement constant arrondi au cent (ROUND_HALF_UP) : P·i / (1 − (1+i)^−n), ou P/n si i = 0."""
    with localcontext(CONTEXTE):
        if taux == 0:
            return au_cent(principal / n)
        return au_cent(principal * taux / (_UN - (_UN + taux) ** -n))


def amortir(principal: Decimal, taux: Decimal, n: int) -> dict[str, Any]:
    """Tableau d'amortissement complet à versement constant. Chaque ligne : `periode`, `versement`, `interet`,
    `capital`, `solde` (au cent). L'intérêt d'une période est arrondi au cent ; la dernière échéance (la n-ième, ou plus
    tôt si l'arrondi du versement solde le prêt avant) rembourse exactement le solde restant : Σ capital = principal.

    Lève `ArithmeticError` si le versement arrondi ne couvre pas l'intérêt de la première période (amortissement
    négatif) : `moteur_calcul` le traduit en refus typé."""
    with localcontext(CONTEXTE):
        versement = versement_constant(principal, taux, n)
        if versement <= au_cent(principal * taux):
            raise ArithmeticError("le versement arrondi ne couvre pas l'intérêt de la première période")
        solde = principal
        lignes = []
        for periode in range(1, n + 1):
            interet = au_cent(solde * taux)
            if periode == n or versement - interet >= solde:
                capital = solde
                paye = capital + interet
            else:
                capital = versement - interet
                paye = versement
            solde -= capital
            lignes.append({"periode": periode, "versement": paye, "interet": interet, "capital": capital,
                           "solde": solde})
            if solde == 0:
                break
        total_capital = sum((ligne["capital"] for ligne in lignes), _ZERO)
        if total_capital != principal or solde != 0:
            raise ArithmeticError("somme des capitaux différente du principal")
        return {
            "versement": versement,
            "nombre_versements": len(lignes),
            "dernier_versement": lignes[-1]["versement"],
            "ajustement_dernier_versement": lignes[-1]["versement"] - versement,
            "total_versements": sum((ligne["versement"] for ligne in lignes), _ZERO),
            "total_interets": sum((ligne["interet"] for ligne in lignes), _ZERO),
            "total_capital": total_capital,
            "lignes": lignes,
        }


# ------------------------------------------------------------------------------------- crédit-bail, point mort
def comparer_credit_bail_achat(
    *, taux_mensuel: Decimal, mois: int, prix_achat: Decimal, frais_achat: Decimal, valeur_residuelle: Decimal,
    paiement_mensuel: Decimal, depot_initial: Decimal, paiements_en_debut_de_periode: bool,
    option_achat_finale: Decimal | None,
) -> dict[str, Decimal]:
    """Valeur actuelle des COÛTS de deux façons d'avoir l'actif pendant `mois` mois (convention déclarée) :
    achat comptant = prix + frais − VR/(1+i)^mois ; crédit-bail = dépôt + Σ paiements actualisés (en début de période :
    t = 0..mois−1 ; en fin : t = 1..mois) + (option d'achat − VR)/(1+i)^mois si l'option est exercée (rien sinon :
    l'actif est rendu)."""
    with localcontext(CONTEXTE):
        facteur_fin = (_UN + taux_mensuel) ** mois
        va_achat = prix_achat + frais_achat - valeur_residuelle / facteur_fin
        decalage = 0 if paiements_en_debut_de_periode else 1
        va_paiements = sum((paiement_mensuel / (_UN + taux_mensuel) ** (t + decalage) for t in range(mois)), _ZERO)
        va_option = _ZERO if option_achat_finale is None else (option_achat_finale - valeur_residuelle) / facteur_fin
        va_bail = depot_initial + va_paiements + va_option
        return {"va_cout_achat": va_achat, "va_cout_credit_bail": va_bail, "va_paiements_credit_bail": va_paiements,
                "va_option_nette": va_option, "ecart_credit_bail_moins_achat": va_bail - va_achat}


def point_mort(frais_fixes: Decimal, prix_unitaire: Decimal, cout_variable_unitaire: Decimal) -> dict[str, Decimal]:
    """Point mort : q* = F / (p − cv) unités (exact), arrondi à l'unité supérieure, et chiffre d'affaires p·q*.
    Lève `ArithmeticError` si la marge sur coût variable n'est pas strictement positive (aucun point mort)."""
    with localcontext(CONTEXTE):
        marge = prix_unitaire - cout_variable_unitaire
        if marge <= 0:
            raise ArithmeticError("marge sur coût variable non positive")
        quantite = frais_fixes / marge
        entiere = quantite.to_integral_value(rounding=ROUND_CEILING)
        return {"marge_unitaire": marge, "taux_de_marge": marge / prix_unitaire, "quantite_exacte": quantite,
                "quantite_entiere": entiere, "chiffre_affaires_exact": quantite * prix_unitaire,
                "chiffre_affaires_quantite_entiere": entiere * prix_unitaire}
