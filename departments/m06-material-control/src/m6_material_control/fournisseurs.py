"""Registre des fournisseurs de M6 (M6.2, PLAN T2.5 point 2) : IDENTITÉ ET COORDONNÉES
SEULEMENT — Gentek, Royal Solution de Bâtiment, O.A.M., Kaycan (DEFINITION-PRODUIT.md §7 M6,
``docs/departements/M6-audit.md`` §2) sont les 4 fournisseurs initiaux cités, mais AUCUN de leurs
numéros de téléphone, courriels ou délais réels n'est connu de ce paquet : chaque fiche vient de
l'appelant (admin), qui fournit ce qu'il sait, jamais une valeur devinée pour combler un champ
optionnel manquant.

Distinct de ``livre_prix.py`` (prix par fournisseur) et de ``bons_commande.py`` (PO par
fournisseur) : ce registre porte uniquement l'IDENTITÉ (nom, coordonnées, catégories vendues) —
aucun prix, délai inventé, ni « fiabilité »/« historique d'erreurs » (M6.2 les nomme, mais ce
paquet ne peut pas les calculer sans historique opérationnel réel ; leur donner une valeur par
défaut ici serait une donnée inventée, AGENTS.md — hors périmètre PLAN T2.5, à faire quand une
vraie source existe).

Module pur (AGENTS.md, ADR-0009) : aucun import ``opsys``/SQLAlchemy, aucune horloge interne
(horodatage fourni par l'appelant), aucun aléa, aucun réseau. ``registre_cible`` est duck-typé
(itérable, ``append``), comme ``livre_prix.py``/``besoins_prevus.py``.

Un fournisseur est une fiche VIVANTE (contrairement à un devis/PO, document figé une fois créé) :
``enregistrer_fournisseur`` ACCEPTE une correction de coordonnées (un numéro qui change n'est pas
une erreur, contrairement à deux ``po_id``/``devis_id`` identiques pour un contenu différent).
Chaque appel ajoute un maillon (``fournisseur_cree`` la première fois, ``fournisseur_maj``
ensuite) ; l'état courant (``lire_fournisseur``) est la FUSION de tous les maillons d'un
``fournisseur_id``, dans l'ordre — jamais seulement le dernier maillon, pour qu'un champ posé à
la création et jamais corrigé reste visible. Un appel dont le contenu est IDENTIQUE à l'état
courant est un no-op (aucun maillon ajouté) : rejouer la même fiche ne grossit jamais le registre
pour rien.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from . import contrats, frontieres, verdicts

__all__ = ["enregistrer_fournisseur", "lire_fournisseur", "lister_fournisseurs"]

_CLES_CONTENU = tuple(sorted(contrats.CHAMPS_FOURNISSEUR_REQUIS | contrats.CHAMPS_FOURNISSEUR_OPTIONNELS))


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _etats_courants(registre_cible: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """État courant de chaque fournisseur connu : fusion, dans l'ordre du registre, de son
    maillon ``fournisseur_cree`` puis de chacun de ses ``fournisseur_maj`` (même patron que
    ``devis_durable._etats_courants`` de M3, copie-adaptation, #109)."""
    etats: dict[str, dict[str, Any]] = {}
    for maillon in registre_cible:
        type_entree = maillon.get("type_entree")
        fournisseur_id = maillon.get("fournisseur_id")
        if type_entree == "fournisseur_cree":
            etats[fournisseur_id] = dict(maillon)
        elif type_entree == "fournisseur_maj" and fournisseur_id in etats:
            etats[fournisseur_id] = {**etats[fournisseur_id], **maillon}
    return etats


def lire_fournisseur(registre_cible: Iterable[Mapping[str, Any]], fournisseur_id: Any) -> dict[str, Any] | None:
    """La fiche courante de ce fournisseur, ou ``None`` si jamais enregistré."""
    if not _texte_non_vide(fournisseur_id):
        return None
    return _etats_courants(registre_cible).get(fournisseur_id)


def lister_fournisseurs(registre_cible: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Tous les fournisseurs connus (état courant de chacun), triés par ``fournisseur_id`` pour un
    ordre déterministe — aucune horloge, aucun tri par date."""
    return [etat for _, etat in sorted(_etats_courants(registre_cible).items())]


def enregistrer_fournisseur(
    fournisseur_id: Any,
    nom: Any,
    horodatage: Any,
    registre_cible: Any,
    courriel_commande: Any = None,
    telephone: Any = None,
    categories_vendues: Any = None,
    delai_habituel_jours: Any = None,
    format_commande_prefere: Any = None,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Crée ou corrige la fiche d'un fournisseur (voir la docstring du module : fiche vivante, pas
    un document figé). Champs optionnels omis (``None``) : jamais devinés."""
    candidat = {
        "fournisseur_id": fournisseur_id,
        "nom": nom,
        "courriel_commande": courriel_commande,
        "telephone": telephone,
        "categories_vendues": categories_vendues,
        "delai_habituel_jours": delai_habituel_jours,
        "format_commande_prefere": format_commande_prefere,
    }
    ok, code = frontieres.verifier_frontieres(candidat)
    if not ok:
        return None, verdicts.construire_verdict(code)

    if not _texte_non_vide(fournisseur_id):
        return None, verdicts.construire_verdict("REJ-FOURNISSEUR-ID-VIDE", detail="fournisseur_id requis, non vide")
    if not _texte_non_vide(nom):
        return None, verdicts.construire_verdict("REJ-FOURNISSEUR-NOM-VIDE", detail="nom requis, non vide")
    if not _texte_non_vide(horodatage):
        return None, verdicts.construire_verdict(
            "REJ-FOURNISSEUR-HORODATAGE-VIDE", detail="horodatage requis, non vide"
        )

    if courriel_commande is not None and not _texte_non_vide(courriel_commande):
        return None, verdicts.construire_verdict(
            "REJ-FOURNISSEUR-CHAMP-INVALIDE", detail="courriel_commande doit être une chaîne non vide ou None"
        )
    if telephone is not None and not _texte_non_vide(telephone):
        return None, verdicts.construire_verdict(
            "REJ-FOURNISSEUR-CHAMP-INVALIDE", detail="telephone doit être une chaîne non vide ou None"
        )
    if format_commande_prefere is not None and not _texte_non_vide(format_commande_prefere):
        return None, verdicts.construire_verdict(
            "REJ-FOURNISSEUR-CHAMP-INVALIDE", detail="format_commande_prefere doit être une chaîne non vide ou None"
        )
    if categories_vendues is not None and (
        not isinstance(categories_vendues, list)
        or not all(_texte_non_vide(categorie) for categorie in categories_vendues)
    ):
        return None, verdicts.construire_verdict(
            "REJ-FOURNISSEUR-CHAMP-INVALIDE",
            detail="categories_vendues doit être une liste de chaînes non vides, ou None",
        )
    if delai_habituel_jours is not None and (
        isinstance(delai_habituel_jours, bool)
        or not isinstance(delai_habituel_jours, int)
        or delai_habituel_jours <= 0
    ):
        return None, verdicts.construire_verdict(
            "REJ-FOURNISSEUR-CHAMP-INVALIDE",
            detail="delai_habituel_jours doit être un entier strictement positif, ou None",
        )

    existant = lire_fournisseur(registre_cible, fournisseur_id)
    if existant is not None and all(existant.get(cle) == candidat[cle] for cle in _CLES_CONTENU):
        return existant, None

    type_entree = "fournisseur_maj" if existant is not None else "fournisseur_cree"
    maillon = {**candidat, "type_entree": type_entree, "horodatage": horodatage}
    registre_cible.append(dict(maillon))
    return lire_fournisseur(registre_cible, fournisseur_id), None
