"""Livre de prix de M6 (M6.3, PLAN T2.4) : prix FOURNIS (jamais calculés ni inventés), versionnés
(chaque entrée est un maillon append-only de plus, jamais une réécriture d'une entrée antérieure),
datés (``date_effet``) et PAR FOURNISSEUR (``fournisseur_id``).

Distinct de ``catalogue.py`` (résolution de prix à la RÉCEPTION : ``CatalogueMateriaux`` fourni à
l'appel -> historique du registre de mouvements -> ``INDETERMINE``, §DA-M6-10) : ``catalogue.py``
reste inchangé (audit M6 §2, M6.3, « vocabulaire différent de celui du produit, à trancher » —
pas ici, hors PLAN T2.4). ``livre_prix.py`` sert un besoin DIFFÉRENT et nouveau : le prix ATTENDU
d'un PO AVANT réception (``bons_commande.py``), par fournisseur, avec un historique daté
consultable (hausses, versions) — ce que ``catalogue.py`` ne porte pas (il n'a aucune notion de
fournisseur ni de date).

Module pur (AGENTS.md, ADR-0009) : aucun import ``opsys``/SQLAlchemy, aucune horloge interne
(``date_effet`` fourni par l'appelant), aucun aléa, aucun réseau. ``registre_cible`` est
duck-typé (itérable, ``append``) : une liste Python en mémoire dans les tests,
``opsys.stockage.maillons("m06-material-control", "livre_prix")`` en production (choix
d'``outils.py`` seul).

Sélection du prix « en vigueur » : le DERNIER maillon ajouté pour le couple ``(materiau_id,
fournisseur_id)`` — JAMAIS une comparaison de ``date_effet`` entre elles. Même raisonnement que
DA-M6-10 (``catalogue.py``) : M6 n'a aucune horloge pour arbitrer deux dates fournies par
l'appelant, potentiellement égales ou dans le désordre ; l'ORDRE D'ÉCRITURE (déterministe, non
falsifiable) est la seule autorité déterministe. ``date_effet`` reste une information affichée et
tracée pour l'audit humain, jamais un axe de tri.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from . import contrats, frontieres, verdicts

__all__ = ["enregistrer_prix", "prix_en_vigueur", "resoudre_prix_po", "marquage_source_document"]

_VERDICT_PRIX_LIVRE, _VERDICT_PRIX_INDETERMINE = contrats.VERDICT_PRIX_PO


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def marquage_source_document(source_document: Any) -> str:
    """Classify a declared reference; a nonempty string does not authenticate a document."""
    declaree, fallback, _, _ = contrats.MARQUAGE_SOURCE_PRIX
    return declaree if _texte_non_vide(source_document) else fallback


def enregistrer_prix(
    materiau_id: Any,
    fournisseur_id: Any,
    prix_unitaire: Any,
    devise: Any,
    date_effet: Any,
    registre_cible: Any,
    source_document: Any = None,
    unite: Any = None,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Ajoute une NOUVELLE entrée de prix (jamais une modification d'une entrée existante :
    append-only, PLAN T2.4 « versionnés »). Fail-closed : ``prix_unitaire`` doit être un nombre
    fini strictement positif fourni par l'appelant (jamais un défaut inventé) ; ``materiau_id``/
    ``fournisseur_id``/``devise``/``date_effet`` des chaînes non vides. ``source_document`` est
    optionnel (``None`` si absent — jamais fabriqué : référence une facture ou un PO d'origine
    quand elle existe, M6.3 « factures et PO liés »). ``unite`` est optionnelle pour préserver
    les anciens appels : fournie, elle doit être une chaîne non vide ; absente, aucune unité
    n'est inférée ni ajoutée au registre (M5 garde alors la valorisation matérielle partielle)."""
    entree = {
        "materiau_id": materiau_id,
        "fournisseur_id": fournisseur_id,
        "prix_unitaire": prix_unitaire,
        "devise": devise,
        "date_effet": date_effet,
        "source_document": source_document,
    }
    if unite is not None:
        entree["unite"] = unite
    ok, code = frontieres.verifier_frontieres(entree)
    if not ok:
        return None, verdicts.construire_verdict(code)

    for champ in sorted(contrats.CHAMPS_ENTREE_PRIX_REQUIS - {"prix_unitaire"}):
        if not _texte_non_vide(entree[champ]):
            return None, verdicts.construire_verdict(
                "REJ-PRIX-STRUCTURE-INVALIDE", detail=f"{champ} requis, non vide"
            )
    if source_document is not None and not _texte_non_vide(source_document):
        return None, verdicts.construire_verdict(
            "REJ-PRIX-STRUCTURE-INVALIDE", detail="source_document doit être une chaîne non vide ou None"
        )
    if unite is not None and not _texte_non_vide(unite):
        return None, verdicts.construire_verdict(
            "REJ-PRIX-STRUCTURE-INVALIDE", detail="unite doit être une chaîne non vide ou None"
        )
    if isinstance(prix_unitaire, bool) or not isinstance(prix_unitaire, (int, float)):
        return None, verdicts.construire_verdict("REJ-PRIX-INVALIDE", detail="prix_unitaire doit être un nombre")
    if isinstance(prix_unitaire, float) and not math.isfinite(prix_unitaire):
        return None, verdicts.construire_verdict("REJ-PRIX-INVALIDE", detail="prix_unitaire doit être fini")
    if prix_unitaire <= 0:
        return None, verdicts.construire_verdict(
            "REJ-PRIX-INVALIDE", detail="prix_unitaire doit être strictement positif"
        )

    registre_cible.append(dict(entree))
    return dict(entree), None


def _entrees_pour(
    materiau_id: Any, fournisseur_id: Any, registre_cible: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    return [
        dict(entree)
        for entree in registre_cible
        if entree.get("materiau_id") == materiau_id and entree.get("fournisseur_id") == fournisseur_id
    ]


def prix_en_vigueur(
    materiau_id: Any, fournisseur_id: Any, registre_cible: Iterable[Mapping[str, Any]]
) -> dict[str, Any] | None:
    """La DERNIÈRE entrée ajoutée pour ce couple ``(materiau_id, fournisseur_id)``, ou ``None`` si
    aucune n'existe — jamais une comparaison de ``date_effet`` (voir la docstring du module)."""
    entrees = _entrees_pour(materiau_id, fournisseur_id, registre_cible)
    return entrees[-1] if entrees else None


def resoudre_prix_po(
    materiau_id: Any, fournisseur_id: Any, registre_cible: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Le prix qu'un PO doit porter pour cette ligne (PLAN T2.5 point 3, T2.4) : ``PRIX_LIVRE`` si
    le livre de prix en a un pour ce couple, sinon ``INDETERMINE`` — un VERDICT qui DEMANDE un
    prix, jamais un prix inventé (0, le dernier prix d'un AUTRE fournisseur, ou une moyenne)."""
    entree = prix_en_vigueur(materiau_id, fournisseur_id, registre_cible)
    if entree is None:
        return {
            "verdict_prix": _VERDICT_PRIX_INDETERMINE,
            "prix_unitaire": None,
            "devise": None,
            "date_effet": None,
            "source_document": None,
            "marquage_source": None,
        }
    return {
        "verdict_prix": _VERDICT_PRIX_LIVRE,
        "prix_unitaire": entree["prix_unitaire"],
        "devise": entree["devise"],
        "date_effet": entree["date_effet"],
        "source_document": entree.get("source_document"),
        "marquage_source": marquage_source_document(entree.get("source_document")),
    }
