"""Monte-Carlo À GRAINE de la trésorerie hebdomadaire, à partir de la prévision EXISTANTE (`prevision.py`, M5.7).

Ce module ne prévoit rien de nouveau : il prend les flux CONNUS et DATÉS que `prevision.assembler` a placés, semaine
par semaine, et les PERTURBE selon des distributions DÉCLARÉES par l'appelant (aucune n'est choisie ici), nature par
nature de flux :
- montant : facteur multiplicatif tiré d'une loi TRIANGULAIRE (min, mode, max) ou NORMALE TRONQUÉE (moyenne,
  écart-type, min, max), appliqué au montant connu puis arrondi au cent (ROUND_HALF_UP) ;
- retard de paiement (encaissements seulement : retarder un décaissement serait optimiste) : BERNOULLI de probabilité
  p ; s'il survient, l'encaissement glisse de k semaines ; au-delà de l'horizon, il n'est pas compté (prudent).
Une nature sans distribution déclarée reste déterministe. Aucune vente, aucun flux nouveau n'est inventé.

REJOUABLE BIT POUR BIT : `random.Random(graine)` (Mersenne Twister, graine entière : suite stable entre versions de
Python), dont on ne lit que `getrandbits(53)` ; chaque uniforme est u = (2k + 1) / 2^54, dans ]0, 1[. Les lois sont
obtenues par INVERSION de la fonction de répartition, en `Decimal` (aucun flottant, aucune `libm` : les fonctions
`ln`, `exp`, `sqrt` de `decimal` sont déterministes) : triangulaire par formule fermée ; normale par l'algorithme AS241
de Wichura (1988, le même que `statistics.NormalDist.inv_cdf`), la troncature par Φ(z) = (1 + erf(z/√2))/2, erf par sa
série entière. Chaque flux consomme toujours le même nombre d'uniformes, dans un ordre total fixé (semaine, sens,
nature, identifiant) : même graine, mêmes entrées, même résultat.

SORTIES : pour chaque semaine, le solde de FIN de semaine en P5, P50, P95 (méthode du rang le plus proche : la valeur
de rang ⌈p·N⌉ des N tirages triés, sans interpolation), la moyenne, la probabilité d'un solde négatif (et sous le seuil
du propriétaire s'il est fourni) ; sur le chemin entier, la probabilité qu'au moins une semaine soit négative et les
percentiles du point le plus bas. Le solde DÉTERMINISTE de la prévision est rendu à côté (`solde_base`).

Module PUR : ni horloge, ni registre, ni réseau ; il lit et calcule. `conformite.verifier_aucun_decaissement` le
surveille en mode strict.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Any

__all__ = [
    "BUDGET_TIRAGES_X_FLUX", "FLUX_MAX", "NATURES_ENTREE", "NATURES_SORTIE", "SEMAINES_MAX", "TIRAGES_MAX",
    "inverse_normale", "repartition_normale", "simuler",
]

TIRAGES_MAX = 10_000
SEMAINES_MAX = 26
FLUX_MAX = 400
BUDGET_TIRAGES_X_FLUX = 400_000
GRAINE_MAX = 2**63 - 1
# Les natures de flux de `prevision.py` (et `echeanciers_contrats.py`) : liste fermée, une nature inconnue est refusée.
NATURES_ENTREE = frozenset({"facture_client", "echeancier_contrat"})
NATURES_SORTIE = frozenset({"facture_fournisseur", "attendu_fournisseur", "taxes", "paies", "das", "dettes"})

_CONTEXTE_TIRAGE = Context(prec=34, rounding=ROUND_HALF_EVEN, Emax=999_999, Emin=-999_999)
_CONTEXTE_ERF = Context(prec=90, rounding=ROUND_HALF_EVEN, Emax=999_999, Emin=-999_999)
_CONTEXTE_MONETAIRE = Context(prec=50, rounding=ROUND_HALF_EVEN)
_QUANTUM_FACTEUR = Decimal("1e-12")
_QUANTUM_PROBA = Decimal("0.0001")
_CENT = Decimal("0.01")
_DEUX_PUISSANCE_54 = Decimal(2**54)
_Z_MAX = Decimal(10)
_PI = Decimal("3.14159265358979323846264338327950288419716939937510582097494459230781640628620899862803482534211706")
_PERCENTILES = (("p5", Decimal("0.05")), ("p50", Decimal("0.50")), ("p95", Decimal("0.95")))

# AS241 (Wichura 1988), PPND16 : coefficients de l'article, identiques à `statistics._normal_dist_inv_cdf`.
_A = [Decimal(x) for x in (
    "3.3871328727963666080e0", "1.3314166789178437745e+2", "1.9715909503065514427e+3", "1.3731693765509461125e+4",
    "4.5921953931549871457e+4", "6.7265770927008700853e+4", "3.3430575583588128105e+4", "2.5090809287301226727e+3")]
_B = [Decimal(x) for x in (
    "1", "4.2313330701600911252e+1", "6.8718700749205790830e+2", "5.3941960214247511077e+3",
    "2.1213794301586595867e+4", "3.9307895800092710610e+4", "2.8729085735721942674e+4", "5.2264952788528545610e+3")]
_C = [Decimal(x) for x in (
    "1.42343711074968357734e0", "4.63033784615654529590e0", "5.76949722146069140550e0", "3.64784832476320460504e0",
    "1.27045825245236838258e0", "2.41780725177450611770e-1", "2.27238449892691845833e-2",
    "7.74545014278341407640e-4")]
_D = [Decimal(x) for x in (
    "1", "2.05319162663775882187e0", "1.67638483018380384940e0", "6.89767334985100004550e-1",
    "1.48103976427480074590e-1", "1.51986665636164571966e-2", "5.47593808499534494600e-4",
    "1.05075007164441684324e-9")]
_E = [Decimal(x) for x in (
    "6.65790464350110377720e0", "5.46378491116411436990e0", "1.78482653991729133580e0", "2.96560571828504891230e-1",
    "2.65321895265761230930e-2", "1.24266094738807843860e-3", "2.71155556874348757815e-5",
    "2.01033439929228813265e-7")]
_F = [Decimal(x) for x in (
    "1", "5.99832206555887937690e-1", "1.36929880922735805310e-1", "1.48753612908506148525e-2",
    "7.86869131145613259100e-4", "1.84631831751005468180e-5", "1.42151175831644588870e-7",
    "2.04426310338993978564e-15")]


def _poly(coefficients: Sequence[Decimal], x: Decimal) -> Decimal:
    acc = Decimal(0)
    for c in reversed(coefficients):
        acc = acc * x + c
    return acc


def inverse_normale(p: Decimal) -> Decimal:
    """Φ⁻¹(p) pour 0 < p < 1, AS241 en `Decimal` (précision de l'approximation : environ 1e-16)."""
    with localcontext(_CONTEXTE_TIRAGE):
        if not 0 < p < 1:
            raise ValueError("inverse_normale : 0 < p < 1 exigé")
        q = p - Decimal("0.5")
        if abs(q) <= Decimal("0.425"):
            r = Decimal("0.180625") - q * q
            return q * _poly(_A, r) / _poly(_B, r)
        r = p if q <= 0 else 1 - p
        r = (-r.ln()).sqrt()
        if r <= 5:
            r -= Decimal("1.6")
            x = _poly(_C, r) / _poly(_D, r)
        else:
            r -= 5
            x = _poly(_E, r) / _poly(_F, r)
        return -x if q < 0 else x


def _erf(x: Decimal) -> Decimal:
    """erf(x) par sa série entière, |x| ≤ 10/√2, en 90 chiffres (terme d'arrêt < 1e-60)."""
    with localcontext(_CONTEXTE_ERF):
        terme = x
        somme = x
        x2 = x * x
        n = 0
        seuil = Decimal("1e-60")
        while True:
            n += 1
            terme = -terme * x2 / n
            contribution = terme / (2 * n + 1)
            somme += contribution
            if abs(contribution) < seuil:
                break
        return 2 / _PI.sqrt() * somme


def repartition_normale(z: Decimal) -> Decimal:
    """Φ(z) ; z ramené dans [−10, 10] (l'erreur ainsi commise est inférieure à 1e-23)."""
    with localcontext(_CONTEXTE_ERF):
        z = max(-_Z_MAX, min(_Z_MAX, z))
        valeur = (1 + _erf(z / Decimal(2).sqrt())) / 2
    with localcontext(_CONTEXTE_TIRAGE):
        return +valeur


def _uniforme(generateur: random.Random) -> Decimal:
    with localcontext(_CONTEXTE_TIRAGE):
        return Decimal(2 * generateur.getrandbits(53) + 1) / _DEUX_PUISSANCE_54


def _preparer_loi(loi: Mapping[str, Any]) -> dict[str, Any]:
    if loi["loi"] == "triangulaire":
        a, c, b = loi["min"], loi["mode"], loi["max"]
        with localcontext(_CONTEXTE_TIRAGE):
            return {**loi, "_seuil": (c - a) / (b - a), "_ba_ca": (b - a) * (c - a), "_ba_bc": (b - a) * (b - c)}
    mu, sigma = loi["moyenne"], loi["ecart_type"]
    with localcontext(_CONTEXTE_TIRAGE):
        phi_a = repartition_normale((loi["min"] - mu) / sigma)
        phi_b = repartition_normale((loi["max"] - mu) / sigma)
    return {**loi, "_phi_a": phi_a, "_masse": phi_b - phi_a}


def masse_troncature(loi: Mapping[str, Any]) -> Decimal:
    """La probabilité de [min, max] sous la normale non tronquée (utile pour refuser une troncature dégénérée)."""
    return _preparer_loi(loi)["_masse"]


def _facteur(loi: Mapping[str, Any], u: Decimal) -> Decimal:
    with localcontext(_CONTEXTE_TIRAGE):
        if loi["loi"] == "triangulaire":
            a, b = loi["min"], loi["max"]
            x = a + (u * loi["_ba_ca"]).sqrt() if u < loi["_seuil"] else b - ((1 - u) * loi["_ba_bc"]).sqrt()
        else:
            p = loi["_phi_a"] + u * loi["_masse"]
            p = min(max(p, Decimal("1e-30")), 1 - Decimal("1e-30"))
            x = loi["moyenne"] + loi["ecart_type"] * inverse_normale(p)
        x = min(max(x, loi["min"]), loi["max"])
        return x.quantize(_QUANTUM_FACTEUR, rounding=ROUND_HALF_EVEN)


def _rang(valeurs_triees: Sequence[Decimal], p: Decimal) -> Decimal:
    """Rang le plus proche : la valeur de rang ⌈p·N⌉ (1 ≤ rang ≤ N)."""
    n = len(valeurs_triees)
    rang = int((p * n).to_integral_value(rounding="ROUND_CEILING"))
    return valeurs_triees[min(max(rang, 1), n) - 1]


def _proba(compte: int, total: int) -> Decimal:
    with localcontext(_CONTEXTE_MONETAIRE):
        return (Decimal(compte) / Decimal(total)).quantize(_QUANTUM_PROBA, rounding=ROUND_HALF_UP)


def _cle_flux(flux: Mapping[str, Any]) -> tuple[Any, ...]:
    return flux["semaine"], 0 if flux["sens"] == "SORTIE" else 1, flux["nature"], flux["id"]


def simuler(
    *, solde_initial: Decimal, flux: Sequence[Mapping[str, Any]], semaines: int,
    distributions: Mapping[str, Mapping[str, Any]], graine: int, tirages: int, seuil: Decimal | None = None,
) -> dict[str, Any]:
    """La simulation. `flux` : `{"id", "sens" (ENTREE|SORTIE), "nature", "semaine" (1..semaines), "montant"}` déjà
    validés ; `distributions` : nature → `{"montant": loi | None, "retard": {"probabilite", "semaines"} | None}`.
    Lève `ValueError` sur une entrée mal formée (erreur du code appelant : les refus typés sont dans
    `moteur_calcul`)."""
    if type(graine) is not int or not 0 <= graine <= GRAINE_MAX:
        raise ValueError("graine entière de 0 à 2^63 − 1 exigée")
    if type(tirages) is not int or not 1 <= tirages <= TIRAGES_MAX:
        raise ValueError(f"tirages de 1 à {TIRAGES_MAX}")
    if type(semaines) is not int or not 1 <= semaines <= SEMAINES_MAX:
        raise ValueError(f"semaines de 1 à {SEMAINES_MAX}")
    if len(flux) > FLUX_MAX:
        raise ValueError(f"au plus {FLUX_MAX} flux")
    ordonnes = sorted(flux, key=_cle_flux)
    lois = {nature: {"montant": None if spec.get("montant") is None else _preparer_loi(spec["montant"]),
                     "retard": spec.get("retard")} for nature, spec in distributions.items()}
    generateur = random.Random(graine)
    soldes: list[list[Decimal]] = [[] for _ in range(semaines)]
    minimums: list[Decimal] = []
    chemins_negatifs = 0
    chemins_sous_seuil = 0
    reportes_hors_horizon = 0

    with localcontext(_CONTEXTE_MONETAIRE):
        base_nets = [Decimal("0.00")] * semaines
        for f in ordonnes:
            signe = 1 if f["sens"] == "ENTREE" else -1
            base_nets[f["semaine"] - 1] += signe * f["montant"]
        solde_base = []
        courant = solde_initial
        for net in base_nets:
            courant += net
            solde_base.append(courant)

        for _ in range(tirages):
            nets = [Decimal("0.00")] * semaines
            for f in ordonnes:
                loi = lois.get(f["nature"])
                montant, semaine = f["montant"], f["semaine"]
                if loi is not None and loi["montant"] is not None:
                    facteur = _facteur(loi["montant"], _uniforme(generateur))
                    montant = (montant * facteur).quantize(_CENT, rounding=ROUND_HALF_UP)
                # L'uniforme du retard est tiré dès que la nature déclare un retard : ordre de consommation fixe.
                if (loi is not None and loi["retard"] is not None
                        and _uniforme(generateur) < loi["retard"]["probabilite"]):
                    semaine += loi["retard"]["semaines"]
                if semaine > semaines:
                    reportes_hors_horizon += 1
                    continue
                nets[semaine - 1] += montant if f["sens"] == "ENTREE" else -montant
            courant = solde_initial
            minimum = None
            for k, net in enumerate(nets):
                courant += net
                soldes[k].append(courant)
                minimum = courant if minimum is None or courant < minimum else minimum
            minimums.append(minimum)
            chemins_negatifs += minimum < 0
            if seuil is not None:
                chemins_sous_seuil += minimum < seuil

        par_semaine = []
        for k, valeurs in enumerate(soldes):
            triees = sorted(valeurs)
            negatifs = sum(1 for v in valeurs if v < 0)
            ligne = {
                "semaine": k + 1,
                "solde_base": solde_base[k],
                **{nom: _rang(triees, p) for nom, p in _PERCENTILES},
                "moyenne": (sum(valeurs, Decimal(0)) / tirages).quantize(_CENT, rounding=ROUND_HALF_UP),
                "tirages_negatifs": negatifs,
                "probabilite_negatif": _proba(negatifs, tirages),
            }
            if seuil is not None:
                sous = sum(1 for v in valeurs if v < seuil)
                ligne.update({"tirages_sous_seuil": sous, "probabilite_sous_seuil": _proba(sous, tirages)})
            par_semaine.append(ligne)
        minimums_tries = sorted(minimums)
        resultat = {
            "semaines": par_semaine,
            "plus_bas_du_chemin": {nom: _rang(minimums_tries, p) for nom, p in _PERCENTILES},
            "tirages_avec_semaine_negative": chemins_negatifs,
            "probabilite_au_moins_une_semaine_negative": _proba(chemins_negatifs, tirages),
            "encaissements_reportes_hors_horizon": reportes_hors_horizon,
        }
        if seuil is not None:
            resultat.update({"tirages_avec_semaine_sous_seuil": chemins_sous_seuil,
                             "probabilite_au_moins_une_semaine_sous_seuil": _proba(chemins_sous_seuil, tirages)})
        return resultat
