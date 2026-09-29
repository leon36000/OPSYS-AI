"""Emplacements de stock (M6.9) et transferts audités (PLAN T4.14).

DEFINITION-PRODUIT §7 M6.9 : « dépôt principal, camion, remorque, chantier, employé, fournisseur, retour, rebut,
inconnu. Tout transfert est audité. » Ce module est la règle, écrite une fois : la liste FERMÉE des emplacements, la
validation d'un transfert, ce que chaque emplacement contient, et la chaîne d'audit des transferts.

DEUX CHOSES, UN REGISTRE À PART. Le registre de mouvements de stock (`registre.py`) ne change pas d'un octet :
aucun champ de plus sur ses maillons, aucun hachage qui bouge (une chaîne écrite avant T4.14 se valide encore, bit à
bit). Les transferts vivent dans leur propre registre append-only, `emplacements`, HASH-CHAÎNÉ à son tour : un
transfert ne crée ni ne détruit de stock, il DÉPLACE ce que le registre de mouvements dit être en main.

CE QUE CONTIENT UN EMPLACEMENT. Le stock d'un article (`stock.deriver_stock_articles`, tous lieux) se répartit en
emplacements NOMMÉS, par les transferts, et le reste — tout ce qu'aucun transfert n'a encore placé, donc tout le stock
d'avant T4.14 — est à l'emplacement `inconnu`. C'est un RÉSIDU, jamais une quantité stockée :
`inconnu = stock en main total - somme des emplacements nommés`. Un transfert depuis `inconnu` (« ranger au dépôt »)
est le geste qui localise. Après un transfert, AUCUNE quantité par emplacement n'est négative, `inconnu` compris :
on ne sort jamais d'un emplacement plus que ce qu'il contient, et on ne localise jamais plus que le stock qui existe.
Une sortie de stock non localisée (consommation, perte) diminue le total, donc le résidu : si elle fait dépasser le
stock localisé, le résidu devient négatif, et tout transfert est refusé (`REJ-TRANSFERT-STOCK-LOCALISE-INCOHERENT`)
tant qu'un humain n'a pas régularisé (transfert vers `inconnu`). Jamais une quantité devinée.

EN MAIN. `fournisseur`, `retour` et `rebut` ne sont PAS en main : ce qui s'y trouve n'est ni utilisable ni
réservable. `en main = stock total - ce qui est hors main`. Envoyer un article au rebut le retire donc de ce qu'on
peut réserver et commander de moins.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge (l'horodatage est fourni), aucun aléa, aucun
réseau. `outils.py` fait les entrées-sorties. Quantités en TEXTE décimal exact (`Decimal(str(x))`, jamais un
flottant), comme `evenement_reception.py`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from . import encodage, stock, verdicts

__all__ = [
    "EMPLACEMENTS",
    "EMPLACEMENTS_AVEC_REFERENCE",
    "EMPLACEMENTS_HORS_MAIN",
    "TYPE_TRANSFERT",
    "cle",
    "construire_transfert",
    "hash_tete",
    "hors_main_par_article",
    "normaliser",
    "repartition",
    "valider_chaine",
    "variation_en_main",
]

# La liste FERMÉE (M6.9). Un frozenset, comme les autres ensembles de valeurs légales de M6 : ce sont des noms de
# lieux du produit, pas un verdict que ce paquet invente. `inconnu` en fait partie, dit par la définition produit :
# ce qui n'est pas localisé n'est pas « nulle part », c'est à un lieu qu'on nomme.
EMPLACEMENTS = frozenset(
    {"depot", "camion", "remorque", "chantier", "employe", "fournisseur", "retour", "rebut", "inconnu"}
)
# Ceux qui demandent QUEL camion, QUELLE remorque, QUEL employé, QUEL chantier, QUEL fournisseur. Le dépôt est le
# dépôt principal, et retour, rebut et inconnu n'ont pas de sous-lieu.
EMPLACEMENTS_AVEC_REFERENCE = frozenset({"camion", "remorque", "employe", "chantier", "fournisseur"})
EMPLACEMENTS_HORS_MAIN = frozenset({"fournisseur", "retour", "rebut"})
INCONNU = "inconnu"
TYPE_TRANSFERT = "transfert"
_HASH_PRECEDENT_INITIAL = ""
_LONGUEUR_TEXTE_MAX = 40


_texte = stock.texte_canonique


def normaliser(emplacement: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`({"type", "reference"}, None)` pour un emplacement valide, ou `(None, verdict)`.

    Forme : un objet dont les seules clés sont `type` (dans la liste fermée) et `reference`. Une référence est
    REQUISE pour camion, remorque, employé, chantier et fournisseur, et INTERDITE pour les autres : jamais une
    référence devinée, jamais un emplacement à demi précis."""
    if not isinstance(emplacement, Mapping) or "type" not in emplacement or set(emplacement) - {"type", "reference"}:
        return None, verdicts.construire_verdict(
            "REJ-EMPLACEMENT-STRUCTURE-INVALIDE", detail="attendu : {type, reference} (reference seulement si requise)"
        )
    type_emplacement = emplacement["type"]
    if not isinstance(type_emplacement, str) or type_emplacement not in EMPLACEMENTS:
        return None, verdicts.construire_verdict(
            "REJ-EMPLACEMENT-INCONNU", detail=f"emplacement hors de la liste fermée : {sorted(EMPLACEMENTS)}"
        )
    reference = emplacement.get("reference")
    if type_emplacement in EMPLACEMENTS_AVEC_REFERENCE:
        if not isinstance(reference, str) or not reference.strip():
            return None, verdicts.construire_verdict(
                "REJ-EMPLACEMENT-REFERENCE-MANQUANTE", detail=f"{type_emplacement} : reference requise (lequel ?)"
            )
        return {"type": type_emplacement, "reference": reference.strip()}, None
    if reference is not None:
        return None, verdicts.construire_verdict(
            "REJ-EMPLACEMENT-REFERENCE-INATTENDUE", detail=f"{type_emplacement} : aucune reference (lieu unique)"
        )
    return {"type": type_emplacement, "reference": None}, None


def cle(emplacement: Mapping[str, Any]) -> str:
    """La clé canonique d'un emplacement normalisé : `depot`, `camion:CAM-1`, `chantier:CH-1`."""
    reference = emplacement.get("reference")
    return emplacement["type"] if reference is None else f"{emplacement['type']}:{reference}"


def _hors_main(cle_emplacement: str) -> bool:
    return cle_emplacement.split(":", 1)[0] in EMPLACEMENTS_HORS_MAIN


def _transferts(maillons: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [maillon for maillon in maillons if maillon.get("type_entree") == TYPE_TRANSFERT]


def _quantites_nommees(materiau_id: str, maillons: Iterable[Mapping[str, Any]]) -> dict[str, Decimal]:
    """Somme des entrées moins les sorties de chaque emplacement NOMMÉ pour cet article (jamais `inconnu`, résidu)."""
    nommees: dict[str, Decimal] = {}
    for maillon in _transferts(maillons):
        if maillon["materiau_id"] != materiau_id:
            continue
        quantite = Decimal(maillon["quantite"])
        origine, destination = cle(maillon["de"]), cle(maillon["vers"])
        if origine != INCONNU:
            nommees[origine] = nommees.get(origine, Decimal(0)) - quantite
        if destination != INCONNU:
            nommees[destination] = nommees.get(destination, Decimal(0)) + quantite
    return nommees


def repartition(materiau_id: str, stock_total: Decimal, maillons: Iterable[Mapping[str, Any]]) -> dict[str, Decimal]:
    """Où est le stock de cet article : `{clé d'emplacement: quantité}`, emplacements nommés non nuls plus
    TOUJOURS `inconnu` (le résidu, `stock_total` moins le stock localisé). La somme vaut `stock_total`."""
    nommees = {emplacement: quantite for emplacement, quantite in _quantites_nommees(materiau_id, maillons).items()
               if quantite != 0}
    resultat = dict(sorted(nommees.items()))
    resultat[INCONNU] = stock_total - sum(nommees.values(), Decimal(0))
    return resultat


def variation_en_main(origine: Mapping[str, Any], destination: Mapping[str, Any]) -> int:
    """Ce qu'un transfert fait à l'EN MAIN de l'article : `-1` s'il sort de la main (destination fournisseur, retour
    ou rebut, origine en main), `+1` s'il y revient, `0` sinon (entre deux emplacements en main, ou entre deux hors
    main). L'appelant en tire ce qu'il doit réconcilier (`reservations.reconcilier`)."""
    return (1 if _hors_main(cle(origine)) else 0) - (1 if _hors_main(cle(destination)) else 0)


def hors_main_par_article(maillons: Iterable[Mapping[str, Any]]) -> dict[str, Decimal]:
    """Ce qui est hors main (fournisseur, retour, rebut) pour chaque article qui a eu un transfert. Un article
    absent n'a rien hors main. Une passe sur le registre, pour tous les articles."""
    hors: dict[str, Decimal] = {}
    for maillon in _transferts(maillons):
        quantite = Decimal(maillon["quantite"])
        materiau_id = maillon["materiau_id"]
        if _hors_main(cle(maillon["de"])):
            hors[materiau_id] = hors.get(materiau_id, Decimal(0)) - quantite
        if _hors_main(cle(maillon["vers"])):
            hors[materiau_id] = hors.get(materiau_id, Decimal(0)) + quantite
    return hors


def _quantite_positive(valeur: Any) -> Decimal | None:
    """Décimal exact d'un nombre fini strictement positif (int ou float, jamais un booléen ni un texte), sinon
    `None`."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return None
    try:
        decimal = Decimal(str(valeur))
    except InvalidOperation:
        return None
    if decimal <= 0 or len(format(decimal, "f")) > _LONGUEUR_TEXTE_MAX:
        return None
    return decimal


def _identite(maillon: Mapping[str, Any]) -> tuple[Any, ...]:
    """Ce qui fait qu'un transfert est LE MÊME geste : article, quantité, origine, destination."""
    return (maillon["materiau_id"], maillon["quantite"], cle(maillon["de"]), cle(maillon["vers"]))


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def construire_transfert(
    transfert_id: Any,
    materiau_id: Any,
    quantite: Any,
    de: Any,
    vers: Any,
    acteur: Any,
    motif: Any,
    horodatage: Any,
    stock_total: Decimal,
    maillons: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`({"maillon", "deja_enregistre"}, None)` : le maillon d'audit à ajouter au registre `emplacements` ; ou
    `(None, verdict)`. Sans écriture : l'appelant ajoute le maillon rendu (seul point où `opsys.stockage` est touché).

    `stock_total` est le stock en main TOUS LIEUX de l'article (`stock.deriver_stock_articles`), que l'appelant lit.
    Refus, dans cet ordre, tous nommés et sans écriture : identifiants, quantité (finie, > 0), motif (M6.14 : chaque
    ajustement garde sa raison), horodatage, emplacements (liste fermée, référence), origine = destination, puis
    l'identifiant déjà utilisé, puis la quantité disponible à l'origine et la cohérence du stock localisé.

    Idempotent par `transfert_id`, comme `bons_commande.creer_brouillon` par `po_id` : le même identifiant avec le même
    geste rend le maillon existant (`deja_enregistre`), rien n'est réécrit ni déplacé deux fois ; le même identifiant
    avec un autre geste est refusé (`REJ-TRANSFERT-ID-DEJA-UTILISE`).

    Le maillon garde l'acteur, le motif, l'horodatage, la quantité déplacée, et pour chaque extrémité la quantité
    AVANT et APRÈS (M6.14) ; il est chaîné au précédent (`hash_precedent`, `hash_maillon`)."""
    for nom, valeur, code in (
        ("transfert_id", transfert_id, "REJ-TRANSFERT-ID-VIDE"),
        ("materiau_id", materiau_id, "REJ-TRANSFERT-MATERIAU-VIDE"),
    ):
        if not _texte_non_vide(valeur):
            return None, verdicts.construire_verdict(code, detail=f"{nom} requis, non vide")
    decimal = _quantite_positive(quantite)
    if decimal is None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSFERT-QUANTITE-INVALIDE",
            detail=f"quantite : un nombre fini strictement positif, de {_LONGUEUR_TEXTE_MAX} caractères au plus",
        )
    if not _texte_non_vide(motif):
        return None, verdicts.construire_verdict(
            "REJ-TRANSFERT-MOTIF-VIDE", detail="motif requis, non vide (chaque transfert garde sa raison)"
        )
    if not _texte_non_vide(horodatage) or not _texte_non_vide(acteur):
        return None, verdicts.construire_verdict(
            "REJ-TRANSFERT-HORODATAGE-VIDE", detail="horodatage et acteur requis, non vides"
        )
    origine, verdict = normaliser(de)
    if verdict is not None:
        return None, verdict
    destination, verdict = normaliser(vers)
    if verdict is not None:
        return None, verdict
    if cle(origine) == cle(destination):
        return None, verdicts.construire_verdict(
            "REJ-TRANSFERT-MEME-EMPLACEMENT", detail=f"origine et destination identiques : {cle(origine)}"
        )

    existants = _transferts(maillons)
    quantite_texte = _texte(decimal)
    candidat = {"materiau_id": materiau_id, "quantite": quantite_texte, "de": origine, "vers": destination}
    for existant in existants:
        if existant["transfert_id"] == transfert_id:
            if _identite(existant) == _identite(candidat):
                return {"maillon": dict(existant), "deja_enregistre": True}, None
            return None, verdicts.construire_verdict(
                "REJ-TRANSFERT-ID-DEJA-UTILISE",
                detail=f"transfert_id {transfert_id!r} déjà enregistré pour un autre geste",
            )

    avant = repartition(materiau_id, stock_total, maillons)
    apres = dict(avant)
    cle_origine, cle_destination = cle(origine), cle(destination)
    apres[cle_origine] = avant.get(cle_origine, Decimal(0)) - decimal
    apres[cle_destination] = avant.get(cle_destination, Decimal(0)) + decimal
    if apres[cle_origine] < 0:
        return None, verdicts.construire_verdict(
            "REJ-TRANSFERT-STOCK-INSUFFISANT",
            detail=(
                f"{cle_origine} contient {_texte(avant.get(cle_origine, Decimal(0)))} de {materiau_id!r} : "
                f"impossible d'en sortir {quantite_texte}"
            ),
        )
    incoherents = sorted(emplacement for emplacement, quantite in apres.items() if quantite < 0)
    if incoherents:
        return None, verdicts.construire_verdict(
            "REJ-TRANSFERT-STOCK-LOCALISE-INCOHERENT",
            detail=(
                f"le stock localisé de {materiau_id!r} dépasse le stock en main ({incoherents} négatif après ce "
                "transfert) : une sortie non localisée l'a diminué ; régulariser d'abord par un transfert vers "
                "« inconnu »"
            ),
        )

    index = len(existants)
    hash_precedent = existants[-1]["hash_maillon"] if existants else _HASH_PRECEDENT_INITIAL
    maillon = {
        "type_entree": TYPE_TRANSFERT,
        "index": index,
        "transfert_id": transfert_id,
        "materiau_id": materiau_id,
        "quantite": quantite_texte,
        "de": origine,
        "vers": destination,
        "acteur": acteur,
        "motif": motif,
        "horodatage": horodatage,
        "avant": {
            "de": _texte(avant.get(cle_origine, Decimal(0))),
            "vers": _texte(avant.get(cle_destination, Decimal(0))),
        },
        "apres": {"de": _texte(apres[cle_origine]), "vers": _texte(apres[cle_destination])},
        "hash_precedent": hash_precedent,
    }
    maillon["hash_maillon"] = _empreinte(maillon)
    return {"maillon": maillon, "deja_enregistre": False}, None


def _empreinte(maillon: Mapping[str, Any]) -> str:
    return encodage.empreinte(
        maillon["index"], maillon["transfert_id"], maillon["materiau_id"], maillon["quantite"],
        cle(maillon["de"]), cle(maillon["vers"]), maillon["acteur"], maillon["motif"], maillon["horodatage"],
        maillon["hash_precedent"],
    )


def hash_tete(maillons: Iterable[Mapping[str, Any]]) -> str:
    """Empreinte du dernier transfert, ou la chaîne vide quand aucun n'a été fait."""
    existants = _transferts(maillons)
    return existants[-1]["hash_maillon"] if existants else _HASH_PRECEDENT_INITIAL


def valider_chaine(maillons: Iterable[Mapping[str, Any]]) -> tuple[bool, str]:
    """`(True, "")` si la chaîne d'audit des transferts est intacte, sinon `(False, "maillon invalide à l'index N")` :
    l'index se suit, chaque maillon porte l'empreinte du précédent, et la sienne se recalcule. Modifier un transfert
    après coup (son acteur, son motif, sa quantité) se voit."""
    precedent = _HASH_PRECEDENT_INITIAL
    for position, maillon in enumerate(_transferts(maillons)):
        if maillon["index"] != position or maillon["hash_precedent"] != precedent:
            return False, f"maillon invalide à l'index {position}"
        if maillon["hash_maillon"] != _empreinte(maillon):
            return False, f"maillon invalide à l'index {position}"
        precedent = maillon["hash_maillon"]
    return True, ""
