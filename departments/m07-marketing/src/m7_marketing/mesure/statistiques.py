"""Statistiques déterministes en `Decimal`, sans flottant ni dépendance : loi normale, intervalle de Wilson.

Servent le rapport de performance honnête (médias payants), la visibilité dans les réponses d'IA (taux de mention) et la
conception des tests marketing. Tout est calculé en précision décimale fixe (90 chiffres), arrondi explicitement à la
sortie : le même calcul donne le même texte sur toute machine (un reçu de calcul `recu-calcul.v1` le rejoue à
l'identique).

- `phi(z)` : fonction de répartition de la loi normale centrée réduite, par la série de Taylor de la fonction d'erreur
  (|z| <= 8 ; au-delà, 0 ou 1 à la précision de la sortie) ;
- `quantile(p)` : son inverse, par la méthode de Newton à partir d'une première approximation ;
- `wilson(k, n, niveau)` : l'intervalle de Wilson d'une proportion `k` sur `n` (le bon choix pour de petits
effectifs, là où
  l'intervalle de Wald trompe) ;
- `ecart_proportions(k1, n1, k2, n2, niveau)` : la différence de deux proportions et son intervalle de Newcombe (méthode
  hybride de Wilson).

Limites dites : ces intervalles décrivent l'incertitude d'ÉCHANTILLONNAGE d'une proportion observée ; ils ne
corrigent ni un
biais de mesure, ni une dépendance entre observations, ni une comparaison faite après coup. Module pur.
"""

from __future__ import annotations

import statistics
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

PRECISION = 90
_PI = Decimal("3.14159265358979323846264338327950288419716939937510582097494459230781640628620899862803482534211706798")
SORTIE = Decimal("0.000001")
NIVEAUX_PERMIS = (Decimal("0.80"), Decimal("0.90"), Decimal("0.95"), Decimal("0.99"))


def _contexte() -> Context:
    return Context(prec=PRECISION)


def texte(valeur: Decimal, quantum: Decimal = SORTIE) -> str:
    """Texte décimal arrondi (ROUND_HALF_UP) sans zéros inutiles ; jamais `-0`."""
    with localcontext(_contexte()):
        t = format(valeur.quantize(quantum, rounding=ROUND_HALF_UP), "f")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return "0" if t in ("-0", "") else t


def phi(z: Decimal) -> Decimal:
    """Φ(z) en précision décimale. Lève `ValueError` hors de [-8,3 ; 8,3] (la loi y vaut 0 ou 1 à 1e-16)."""
    if not isinstance(z, Decimal) or not z.is_finite():
        raise ValueError("z : Decimal fini attendu")
    if abs(z) > Decimal("8.3"):
        return Decimal(0) if z < 0 else Decimal(1)
    with localcontext(_contexte()) as ctx:
        x = z / Decimal(2).sqrt()
        x2 = x * x
        terme, somme, n = x, x, 0
        while abs(terme) > Decimal(10) ** -(PRECISION - 12) or n < 5:
            n += 1
            terme = -terme * x2 / n
            somme += terme / (2 * n + 1)
            if n > 4000:
                raise ValueError("série de la fonction d'erreur non convergente")
        erf = 2 * somme / _PI.sqrt()
        return ctx.divide(1 + erf, Decimal(2))


def _densite(z: Decimal) -> Decimal:
    with localcontext(_contexte()):
        return (-(z * z) / 2).exp() / (2 * _PI).sqrt()


def quantile(p: Decimal) -> Decimal:
    """z tel que Φ(z) = p, pour 0 < p < 1 (Newton ; 12 décimales exactes)."""
    if not isinstance(p, Decimal) or not Decimal(0) < p < Decimal(1):
        raise ValueError("p : Decimal strictement entre 0 et 1 attendu")
    with localcontext(_contexte()):
        z = Decimal(repr(statistics.NormalDist().inv_cdf(float(p))))  # point de départ seulement
        for _ in range(8):
            z = z - (phi(z) - p) / _densite(z)
        return z.quantize(Decimal(1).scaleb(-12), rounding=ROUND_HALF_UP)


def z_pour_niveau(niveau: Decimal) -> Decimal:
    """z bilatéral d'un niveau de confiance (0,95 -> 1,959964)."""
    if niveau not in NIVEAUX_PERMIS:
        raise ValueError(f"niveau de confiance attendu parmi {[str(n) for n in NIVEAUX_PERMIS]}")
    return quantile((1 + niveau) / 2)


def wilson(k: int, n: int, niveau: Decimal = Decimal("0.95")) -> tuple[Decimal, Decimal]:
    """Intervalle de Wilson de la proportion k/n (bornes dans [0,1]). `n` doit être >= 1 et 0 <= k <= n."""
    if type(k) is not int or type(n) is not int or n < 1 or not 0 <= k <= n:
        raise ValueError("wilson : entiers n >= 1 et 0 <= k <= n attendus")
    z = z_pour_niveau(niveau)
    with localcontext(_contexte()):
        p, nn = Decimal(k) / Decimal(n), Decimal(n)
        z2 = z * z
        denominateur = 1 + z2 / nn
        centre = (p + z2 / (2 * nn)) / denominateur
        demi = z * (p * (1 - p) / nn + z2 / (4 * nn * nn)).sqrt() / denominateur
        return max(Decimal(0), centre - demi), min(Decimal(1), centre + demi)


def ecart_proportions(
    k1: int, n1: int, k2: int, n2: int, niveau: Decimal = Decimal("0.95")
) -> tuple[Decimal, Decimal, Decimal]:
    """(différence p1 - p2, borne basse, borne haute) par la méthode hybride de Newcombe-Wilson."""
    l1, u1 = wilson(k1, n1, niveau)
    l2, u2 = wilson(k2, n2, niveau)
    with localcontext(_contexte()):
        p1, p2 = Decimal(k1) / Decimal(n1), Decimal(k2) / Decimal(n2)
        d = p1 - p2
        bas = d - ((p1 - l1) ** 2 + (u2 - p2) ** 2).sqrt()
        haut = d + ((u1 - p1) ** 2 + (p2 - l2) ** 2).sqrt()
        return d, bas, haut


__all__ = ["NIVEAUX_PERMIS", "PRECISION", "ecart_proportions", "phi", "quantile", "texte", "wilson", "z_pour_niveau"]
