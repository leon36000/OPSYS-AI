"""Amorçage VIDE des fournisseurs connus (Gentek, Royal Solution de Bâtiment, O.A.M., Kaycan) : leurs NOMS seulement.

Le produit nomme quatre fournisseurs (DEFINITION-PRODUIT §7 M6) ; l'entreprise n'a fourni ni courriel de commande, ni
contact, ni numéro de compte, ni grille tarifaire, ni délais, ni conditions. Aucune de ces données n'est devinée, ni
amorcée, ni fictive-mais-réelle : `department.yaml` (`configuration.fournisseurs_a_fournir`) liste les NOMS attendus et
ce qu'il faut fournir pour chacun ; ce module dit lesquels n'ont encore AUCUNE fiche, pour que l'écran « Fournisseurs »
de la console les montre « à fournir » (sans les créer). Déclarer un fournisseur reste le geste d'une personne
(`m6_enregistrer_fournisseur` ou l'écran « Fournisseurs »), puis son import de tarifs passe par l'écran de confirmation.

Module pur (AGENTS.md, ADR-0009) : aucune entrée-sortie ; l'appelant lit le manifeste et les fiches.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["a_fournir", "lire_configuration"]


def _cle(nom: Any) -> str:
    """Le nom sans accent ni casse ni ponctuation : « Royal Solution de Bâtiment » et « royal solution de batiment »
    sont le même fournisseur ; « O.A.M. » et « OAM » aussi."""
    decompose = unicodedata.normalize("NFKD", str(nom or ""))
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", sans_accent.lower())


def lire_configuration(configuration: Any) -> tuple[list[str], list[str]]:
    """`(noms attendus, ce qu'il faut fournir pour chacun)` du bloc `configuration.fournisseurs_a_fournir`. Un bloc
    absent ou illisible donne deux listes vides (rien n'est affiché), jamais des noms inventés."""
    bloc = configuration.get("fournisseurs_a_fournir") if isinstance(configuration, Mapping) else None
    if not isinstance(bloc, Mapping):
        return [], []
    noms = [n for n in bloc.get("noms", ()) if isinstance(n, str) and n.strip()] if isinstance(
        bloc.get("noms"), list) else []
    exigences = [e for e in bloc.get("pour_chacun", ()) if isinstance(e, str) and e.strip()] if isinstance(
        bloc.get("pour_chacun"), list) else []
    return noms, exigences


def a_fournir(noms_attendus: Iterable[str], fiches: Iterable[Mapping[str, Any]]) -> list[str]:
    """Les noms attendus qui n'ont AUCUNE fiche (nom équivalent, accents et ponctuation ignorés), dans l'ordre déclaré.
    Une fiche au nom proche mais différent (« Gentek (fictif) ») ne compte pas : le rapprochement est un nom, pas une
    ressemblance."""
    connus = {_cle(fiche.get("nom")) for fiche in fiches}
    return [nom for nom in noms_attendus if _cle(nom) not in connus]
