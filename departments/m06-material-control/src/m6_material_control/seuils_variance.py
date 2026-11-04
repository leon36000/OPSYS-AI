"""C7 — les seuils de variance de chantier DÉCLARÉS, par matériau, par catégorie et avec des planchers.

Avant C7, un seul nombre global vivait dans `department.yaml` (`seuil_variance_chantier_pourcentage`) : un
consommable de plus et un autre composant de plus déclenchaient la même revue, et un écart de 0,1 unité sur un article
à valeur élevée était traité comme 0,1 unité sur un article à valeur faible. Un non-développeur ne pouvait changer ces
valeurs sans éditer le manifeste, et rien ne gardait QUI avait changé QUOI.

Ce module porte :
- la sélection du seuil applicable : **matériau > catégorie > global** ; une catégorie n'est appliquée que si le
  matériau est explicitement rattaché à elle (aucune catégorie devinée depuis un préfixe de SKU) ;
- deux **planchers** DÉCLARÉS : une quantité minimale et un montant minimal en dollars. Un écart sous l'un des deux ne
  déclenche pas la revue, même au-dessus du pourcentage. Le montant est calculé en décimal exact, au cent
  (ROUND_HALF_UP), à partir d'une valeur unitaire FOURNIE (jamais inventée) ;
- un **registre append-only et chaîné** des décisions : version, avant/après, auteur, rôle, motif, horodatage,
  empreinte et empreinte du précédent. L'édition est réservée à `admin` et `nathan_owner` (une décision de personne,
  N3) ; un `manager`, un employé ou un agent est refusé nommément.

Fail-closed :
- une configuration incomplète (un plancher `None`, une clé inconnue, un pourcentage hors bornes) est REFUSÉE à
  l'écriture, jamais réparée par un défaut ;
- une chaîne retouchée ne sert plus AUCUNE valeur (`config_en_vigueur` rend `None`) : le département retombe sur
  « seuils à configurer », jamais sur un seuil modifié à la main ;
- un plancher en dollars sans valeur unitaire connue ne fait pas semblant d'être évalué : l'écart est marqué critique
  (`plancher_dollars_non_evalue`) — la revue humaine est le côté sûr — et l'attente de coût de sortie dit quoi déclarer.

Le mode « hérité » (aucune décision au registre) conserve exactement le comportement d'avant : seul le seuil global du
manifeste / des réglages de direction CFG-1 décide, sans plancher. C7 ne s'active qu'à la première décision d'une
personne, avec ses deux planchers déclarés.

Module PUR : aucun import `opsys`, aucune horloge, aucun accès réseau. L'horodatage, l'auteur et le registre sont
fournis par l'appelant (`outils.py`, la console).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

__all__ = [
    "REGISTRE",
    "SEUILS_REFUSES",
    "SeuilsRefuses",
    "config_en_vigueur",
    "config_heritee",
    "critique",
    "dernier",
    "enregistrer",
    "seuil_pour",
    "valider_config",
    "verifier_chaine",
]

REGISTRE = "seuils_variance_chantier"
TYPE_ENTREE = "seuils_variance_chantier"
ROLES_EDITEURS = frozenset({"admin", "nathan_owner"})
CHAMPS_CONFIG = frozenset({
    "global_pourcentage", "par_categorie", "par_materiau", "categories", "plancher_quantite", "plancher_dollars",
})
_POURCENTAGE_MIN = Decimal("0.01")
_POURCENTAGE_MAX = Decimal("5")
_PLANCHER_MIN = Decimal("0")
_PLANCHER_MAX = Decimal("1000000000000")
_CENT = Decimal("0.01")

SEUILS_REFUSES = frozenset({
    "REJ-SEUILS-STRUCTURE", "REJ-SEUILS-POURCENTAGE", "REJ-SEUILS-PLANCHER", "REJ-SEUILS-CATEGORIE",
    "REJ-SEUILS-MOTIF", "REJ-SEUILS-ROLE", "REJ-SEUILS-AUTEUR", "REJ-SEUILS-HORODATAGE", "REJ-SEUILS-VERSION",
    "REJ-SEUILS-CHAINE", "REJ-SEUILS-APPROBATION",
})


class SeuilsRefuses(ValueError):
    """Refus typé : `code` stable (`REJ-SEUILS-…`), `detail` lisible. Jamais de secret ni de personne dans le détail."""

    def __init__(self, code: str, detail: str):
        if code not in SEUILS_REFUSES:  # pragma: no cover - garde de programmation
            raise ValueError(f"code de refus inconnu : {code!r}")
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail


def _texte(valeur: Any, maximum: int) -> bool:
    return isinstance(valeur, str) and bool(valeur) and len(valeur) <= maximum and valeur == valeur.strip() \
        and all(caractere.isprintable() for caractere in valeur)


def _decimal(valeur: Any, code: str, detail: str) -> Decimal:
    """Un texte décimal (ou un entier non booléen) FINI ; jamais un float : la représentation binaire d'un prix ou
    d'un seuil ne doit pas entrer dans une décision d'affaires."""
    if isinstance(valeur, bool) or not isinstance(valeur, (str, int, Decimal)):
        raise SeuilsRefuses(code, detail)
    if isinstance(valeur, str) and (not valeur.strip() or len(valeur.strip()) > 40):
        raise SeuilsRefuses(code, detail)
    try:
        lu = Decimal(str(valeur).strip())
    except (InvalidOperation, ValueError):
        raise SeuilsRefuses(code, detail) from None
    if not lu.is_finite():
        raise SeuilsRefuses(code, detail)
    return lu


def _texte_decimal(valeur: Decimal) -> str:
    if valeur.is_zero():
        return "0"
    return format(valeur.normalize(), "f")


def _borne(valeur: Decimal, minimum: Decimal, maximum: Decimal, code: str, detail: str) -> Decimal:
    if valeur < minimum or valeur > maximum:
        raise SeuilsRefuses(code, f"{detail} : entre {minimum} et {maximum}")
    return valeur


def _mappage(valeur: Any, code: str, detail: str) -> dict[str, Any]:
    if not isinstance(valeur, Mapping):
        raise SeuilsRefuses(code, detail)
    return dict(valeur)


def valider_config(config: Any) -> dict[str, Any]:
    """La configuration COMPLÈTE normalisée (textes décimaux canoniques), ou `SeuilsRefuses`.

    Une configuration C7 est complète par construction : les deux planchers sont OBLIGATOIRES. Un plancher `None` est
    une absence, pas un zéro implicite — un zéro se déclare (`"0"`) et se lit comme tel.
    """
    if not isinstance(config, Mapping) or set(config) != CHAMPS_CONFIG:
        raise SeuilsRefuses(
            "REJ-SEUILS-STRUCTURE", "exactement : global_pourcentage, par_categorie, par_materiau, categories, "
                                   "plancher_quantite, plancher_dollars")
    global_pourcentage = _borne(
        _decimal(config["global_pourcentage"], "REJ-SEUILS-POURCENTAGE", "global_pourcentage : texte décimal"),
        _POURCENTAGE_MIN, _POURCENTAGE_MAX, "REJ-SEUILS-POURCENTAGE", "global_pourcentage hors bornes")
    par_categorie = _mappage(
        config["par_categorie"], "REJ-SEUILS-CATEGORIE", "par_categorie : objet catégorie -> seuil")
    par_materiau = _mappage(
        config["par_materiau"], "REJ-SEUILS-CATEGORIE", "par_materiau : objet matériau -> seuil")
    categories = _mappage(
        config["categories"], "REJ-SEUILS-CATEGORIE", "categories : objet matériau -> catégorie")
    for nom, mappage in (("par_categorie", par_categorie), ("par_materiau", par_materiau)):
        for cle, valeur in mappage.items():
            if not _texte(cle, 200):
                raise SeuilsRefuses("REJ-SEUILS-CATEGORIE", f"{nom} : clé texte non vide, 200 caractères au plus")
            _borne(
                _decimal(valeur, "REJ-SEUILS-POURCENTAGE", f"{nom}.{cle} : texte décimal"),
                _POURCENTAGE_MIN, _POURCENTAGE_MAX, "REJ-SEUILS-POURCENTAGE", f"{nom}.{cle} hors bornes")
    for materiau, categorie in categories.items():
        if not _texte(materiau, 200) or not _texte(categorie, 200):
            raise SeuilsRefuses(
                "REJ-SEUILS-CATEGORIE",
                "categories : matériau et catégorie, textes non vides de 200 caractères au plus")
    plancher_quantite = _borne(
        _decimal(config["plancher_quantite"], "REJ-SEUILS-PLANCHER", "plancher_quantite : texte décimal"),
        _PLANCHER_MIN, _PLANCHER_MAX, "REJ-SEUILS-PLANCHER", "plancher_quantite hors bornes")
    plancher_dollars = _borne(
        _decimal(config["plancher_dollars"], "REJ-SEUILS-PLANCHER", "plancher_dollars : texte décimal"),
        _PLANCHER_MIN, _PLANCHER_MAX, "REJ-SEUILS-PLANCHER", "plancher_dollars hors bornes")
    return {
        "mode": "adopte",
        "global_pourcentage": _texte_decimal(global_pourcentage),
        "par_categorie": {cle: _texte_decimal(_decimal(valeur, "REJ-SEUILS-POURCENTAGE", "seuil"))
                          for cle, valeur in sorted(par_categorie.items())},
        "par_materiau": {cle: _texte_decimal(_decimal(valeur, "REJ-SEUILS-POURCENTAGE", "seuil"))
                         for cle, valeur in sorted(par_materiau.items())},
        "categories": {materiau: categorie for materiau, categorie in sorted(categories.items())},
        "plancher_quantite": _texte_decimal(plancher_quantite),
        "plancher_dollars": _texte_decimal(plancher_dollars),
    }


def config_heritee(seuil_pourcentage: Any) -> dict[str, Any]:
    """Mode d'avant C7 : le seul seuil global DÉCLARÉ (manifeste ou CFG-1), aucun plancher ni seuil par matériau.

    Ce n'est pas une valeur inventée : `outils.py` ne l'appelle qu'avec un seuil déjà validé par
    `validation.valider_seuil_variance_chantier` (absent ou invalide -> `None`, statut `seuil_absent`)."""
    # Le seuil hérité vient d'un float déjà validé (`validation.valider_seuil_variance_chantier`) : `str` donne sa
    # représentation décimale exacte, jamais le bruit binaire d'un calcul.
    valeur = _decimal(str(seuil_pourcentage), "REJ-SEUILS-POURCENTAGE", "seuil hérité illisible")
    _borne(valeur, _POURCENTAGE_MIN, _POURCENTAGE_MAX, "REJ-SEUILS-POURCENTAGE", "seuil hérité hors bornes")
    return {
        "mode": "herite",
        "global_pourcentage": _texte_decimal(valeur),
        "par_categorie": {},
        "par_materiau": {},
        "categories": {},
        "plancher_quantite": None,
        "plancher_dollars": None,
    }


def _seuil(valeur: Any) -> float:
    return float(Decimal(str(valeur)))


def seuil_pour(materiau_id: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    """Le seuil applicable à ce matériau : le sien, sinon celui de SA catégorie déclarée, sinon le global."""
    if isinstance(materiau_id, str) and materiau_id in config.get("par_materiau", {}):
        return {"seuil_pourcentage": _seuil(config["par_materiau"][materiau_id]), "origine": "materiau"}
    categorie = config.get("categories", {}).get(materiau_id) if isinstance(materiau_id, str) else None
    if categorie is not None and categorie in config.get("par_categorie", {}):
        return {"seuil_pourcentage": _seuil(config["par_categorie"][categorie]), "origine": "categorie"}
    return {"seuil_pourcentage": _seuil(config["global_pourcentage"]), "origine": "global"}


def _montant_ecart(ecart: Any, valeur_unitaire: float) -> Decimal | None:
    try:
        quantite = Decimal(str(ecart))
        valeur = Decimal(str(valeur_unitaire))
    except (InvalidOperation, ValueError):
        return None
    if not quantite.is_finite() or not valeur.is_finite() or valeur <= 0:
        return None
    return (abs(quantite) * valeur).quantize(_CENT, rounding=ROUND_HALF_UP)


def critique(
    verdict: Mapping[str, Any], config: Mapping[str, Any], valeur_unitaire: float | None = None
) -> dict[str, Any]:
    """La criticité d'UN verdict matériau, planchers compris.

    Le pourcentage non défini (`NON_PREVU`, `INDETERMINE`) ou ILLISIBLE (texte, NaN, infini, objet hostile) ne
    déclenche jamais la revue à lui seul : il reste visible dans le verdict, mais aucun ratio ne peut être comparé.
    La comparaison porte sur l'AMPLEUR de l'écart (`abs`) : une sous-consommation au-delà du seuil est aussi critique
    qu'une hausse. En mode hérité, seul le pourcentage décide (comportement d'avant C7) ; en mode C7, les DEUX
    planchers déclarés s'appliquent en plus.
    """
    seuil = seuil_pour(verdict.get("materiau_id"), config)
    ratio = verdict.get("ecart_pourcentage")
    if ratio is None:
        return {"critique": False, "motif": "ratio_non_defini", **seuil}
    try:
        ratio_decimal = Decimal(str(ratio))
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return {"critique": False, "motif": "ratio_non_defini", **seuil}
    if not ratio_decimal.is_finite():
        return {"critique": False, "motif": "ratio_non_defini", **seuil}
    if abs(ratio_decimal) < Decimal(str(seuil["seuil_pourcentage"])):
        return {"critique": False, "motif": "sous_seuil", **seuil}
    if config.get("mode") == "herite":
        return {"critique": True, "motif": "au_dessus_du_seuil", **seuil}

    plancher_quantite = Decimal(str(config["plancher_quantite"]))
    ecart = abs(Decimal(str(verdict.get("ecart", 0))))
    if ecart < plancher_quantite:
        return {"critique": False, "motif": "sous_plancher_quantite", **seuil}
    plancher_dollars = Decimal(str(config["plancher_dollars"]))
    if plancher_dollars > 0:
        if valeur_unitaire is None:
            # Fail-closed : ne pas pouvoir calculer le plancher ne veut pas dire « tout va bien ». La revue humaine est
            # le côté sûr ; l'attente de coût de sortie dit quel prix déclarer.
            return {"critique": True, "motif": "plancher_dollars_non_evalue", **seuil}
        montant = _montant_ecart(verdict.get("ecart", 0), valeur_unitaire)
        if montant is None:
            return {"critique": True, "motif": "plancher_dollars_non_evalue", **seuil}
        if montant < plancher_dollars:
            return {"critique": False, "motif": "sous_plancher_dollars", **seuil}
        return {"critique": True, "motif": "au_dessus_des_seuils", **seuil}
    return {"critique": True, "motif": "au_dessus_du_seuil", **seuil}


# ---------------------------------------------------------------------------------------------------------
# Registre d'audit
# ---------------------------------------------------------------------------------------------------------
def _empreinte(maillon: Mapping[str, Any]) -> str:
    contenu = {cle: valeur for cle, valeur in maillon.items() if cle != "empreinte"}
    return hashlib.sha256(
        json.dumps(contenu, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def dernier(registre: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    dernier_vu = None
    for maillon in registre:
        if isinstance(maillon, Mapping) and maillon.get("type_entree") == TYPE_ENTREE:
            dernier_vu = maillon
    return dernier_vu


def verifier_chaine(registre: Iterable[Mapping[str, Any]]) -> bool:
    """La chaîne complète : versions 1..N, empreinte recalculée, lien au précédent, `avant` = `apres` du précédent."""
    precedent = None
    precedent_apres = None
    version_attendue = 1
    for maillon in registre:
        if not isinstance(maillon, Mapping) or maillon.get("type_entree") != TYPE_ENTREE:
            return False
        if set(maillon) != {
            "type_entree", "version", "apres", "avant", "auteur", "role", "motif", "horodatage", "approbation_id",
            "precedent", "empreinte",
        }:
            return False
        if maillon["version"] != version_attendue or maillon["precedent"] != precedent:
            return False
        if maillon["avant"] != (None if version_attendue == 1 else precedent_apres):
            return False
        try:
            recalculee = _empreinte(maillon)
        except (TypeError, ValueError, OverflowError):
            # Un maillon retouché (NaN, objet non sérialisable) rend la chaîne invalide : jamais une exception.
            return False
        if maillon["empreinte"] != recalculee:
            return False
        precedent_apres = maillon["apres"]
        precedent = maillon["empreinte"]
        version_attendue += 1
    return True


def config_en_vigueur(registre: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """La configuration adoptée, ou `None` : registre vide, chaîne invalide, ou dernier maillon illisible."""
    maillons = list(registre)
    if not maillons:
        return None
    if not verifier_chaine(maillons):
        return None
    dernier_maillon = dernier(maillons)
    if dernier_maillon is None:
        return None
    try:
        config = valider_config({cle: dernier_maillon["apres"][cle] for cle in CHAMPS_CONFIG})
    except (SeuilsRefuses, KeyError, TypeError):
        return None
    return {
        **config,
        "version": dernier_maillon["version"],
        "auteur": dernier_maillon["auteur"],
        "role": dernier_maillon["role"],
        "horodatage": dernier_maillon["horodatage"],
    }


def _horodatage_valide(valeur: Any) -> bool:
    if not isinstance(valeur, str) or not valeur or len(valeur) > 50:
        return False
    try:
        instant = datetime.fromisoformat(valeur)
    except ValueError:
        return False
    return instant.tzinfo is not None


def enregistrer(
    config: Any,
    *,
    auteur: Any,
    role: Any,
    motif: Any,
    horodatage: Any,
    registre_cible: Any,
    version_attendue: Any = 0,
    approbation_id: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Écrit UN maillon d'audit, ou refuse nommément sans rien écrire.

    Idempotent : réenregistrer exactement la configuration en vigueur rend `deja_en_vigueur` sans nouveau maillon.
    `version_attendue` empêche une mise à jour perdue entre deux admins. Le registre est append-only : ce module ne
    modifie ni ne supprime jamais un maillon existant.
    """
    if role not in ROLES_EDITEURS:
        return None, "REJ-SEUILS-ROLE"
    if not _texte(auteur, 200):
        return None, "REJ-SEUILS-AUTEUR"
    if not _texte(motif, 500):
        return None, "REJ-SEUILS-MOTIF"
    if not _horodatage_valide(horodatage):
        return None, "REJ-SEUILS-HORODATAGE"
    if approbation_id is not None and not _texte(approbation_id, 200):
        return None, "REJ-SEUILS-APPROBATION"
    if isinstance(version_attendue, bool) or not isinstance(version_attendue, int) or version_attendue < 0:
        return None, "REJ-SEUILS-VERSION"
    maillons = list(registre_cible)
    if not verifier_chaine(maillons):
        return None, "REJ-SEUILS-CHAINE"
    courant = dernier(maillons)
    version_courante = courant["version"] if courant is not None else 0
    if version_attendue != version_courante:
        return None, "REJ-SEUILS-VERSION"
    try:
        apres = valider_config({cle: config[cle] for cle in CHAMPS_CONFIG if cle in config})
    except SeuilsRefuses:
        raise
    if courant is not None and courant["apres"] == apres:
        return {"deja_en_vigueur": True, "version": version_courante, "maillon": dict(courant)}, None
    maillon: dict[str, Any] = {
        "type_entree": TYPE_ENTREE,
        "version": version_courante + 1,
        "apres": apres,
        "avant": courant["apres"] if courant is not None else None,
        "auteur": auteur,
        "role": role,
        "motif": motif,
        "horodatage": horodatage,
        "approbation_id": approbation_id,
        "precedent": courant["empreinte"] if courant is not None else None,
    }
    maillon["empreinte"] = _empreinte(maillon)
    registre_cible.append(maillon)
    return maillon, None
