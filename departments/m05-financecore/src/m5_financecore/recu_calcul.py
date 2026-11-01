"""Le reçu de calcul du moteur M5 (tranche 1, `docs/moteur-calcul.md`) : ce qui rend un chiffre rejouable.

Un agent ne calcule jamais « de tête » (SOUL.md) : il appelle un moteur déterministe qui rend un REÇU. Le reçu dit
tout ce qu'il faut pour refaire le calcul et constater qu'on obtient la même chose :

- `moteur` et `version_moteur` : quelle fonction, à quelle version (une formule qui change change de version) ;
- `methode` : la formule ou l'algorithme, en une phrase ; `precision` : chiffres significatifs et arrondis déclarés ;
- `parametres` : les réglages du calcul (convention, graine, nombre de tirages, tolérance...) ;
- `entrees` : les entrées NORMALISÉES (textes décimaux canoniques), et `empreinte_entrees`, leur SHA-256 ;
- `resultat` : ce que le moteur a rendu, en textes décimaux (jamais un flottant) ;
- `avertissements` : ce que le calcul ne sait pas ou ne garantit pas ; `mention` : « À valider auprès d'un comptable
  (CPA) / professionnel qualifié. » ;
- `empreinte` : SHA-256 (forme canonique injective d'`encodage.py`) de tout le reste SAUF `entrees`, couvertes par
  `empreinte_entrees`. Un reçu « compact » (sans `entrees`, quand elles dépassent le budget d'une réponse) reste donc
  vérifiable : son empreinte ne dépend que de ce qu'il montre.

Un reçu ne contient que des types JSON (texte, entier, booléen, nul, liste, objet) : il traverse une réponse d'outil
et revient intact, et sa vérification ne dépend pas d'un `Decimal` ou d'une `date` reconstruits. Un flottant lève :
un montant ne passe jamais par l'imprécision binaire. Module pur : aucune horloge, aucun registre.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import encodage
from .analyse import MENTION_COMPTABLE

__all__ = ["FORMAT", "construire", "compacter", "verifier"]

FORMAT = "recu-calcul.v1"
_CHAMPS = (
    "type", "format", "moteur", "version_moteur", "methode", "precision", "parametres", "empreinte_entrees",
    "resultat", "avertissements", "mention",
)


def _controler_json(valeur: Any, chemin: str = "recu") -> None:
    """Lève `TypeError` sur tout ce qui n'est pas un type JSON exact : c'est une erreur du code, pas une donnée."""
    if valeur is None or type(valeur) in (str, bool, int):
        return
    if isinstance(valeur, list):
        for index, element in enumerate(valeur):
            _controler_json(element, f"{chemin}[{index}]")
        return
    if isinstance(valeur, dict):
        for cle, element in valeur.items():
            if type(cle) is not str:
                raise TypeError(f"{chemin} : clé non textuelle {cle!r}")
            _controler_json(element, f"{chemin}.{cle}")
        return
    raise TypeError(f"{chemin} : type {type(valeur).__name__} interdit dans un reçu (texte décimal exigé)")


def _empreinte_du_corps(recu: Mapping[str, Any]) -> str:
    return encodage.empreinte(FORMAT, {cle: recu[cle] for cle in _CHAMPS})


def construire(
    *, moteur: str, version_moteur: str, methode: str, precision: Mapping[str, Any], parametres: Mapping[str, Any],
    entrees: Mapping[str, Any], resultat: Mapping[str, Any], avertissements: list[str],
) -> dict[str, Any]:
    """Le reçu complet (avec `entrees`) et ses deux empreintes. Lève `TypeError` si une valeur n'est pas JSON."""
    recu: dict[str, Any] = {
        "type": "RECU_CALCUL",
        "format": FORMAT,
        "moteur": moteur,
        "version_moteur": version_moteur,
        "methode": methode,
        "precision": dict(precision),
        "parametres": dict(parametres),
        "empreinte_entrees": encodage.empreinte(FORMAT, "entrees", dict(entrees)),
        "resultat": dict(resultat),
        "avertissements": list(avertissements),
        "mention": MENTION_COMPTABLE,
    }
    _controler_json(recu)
    _controler_json(dict(entrees), "recu.entrees")
    return {**recu, "entrees": dict(entrees), "empreinte": _empreinte_du_corps(recu)}


def compacter(recu: Mapping[str, Any]) -> dict[str, Any]:
    """Le reçu sans ses `entrees` (gardées par `empreinte_entrees`) : même `empreinte`, toujours vérifiable."""
    return {cle: valeur for cle, valeur in recu.items() if cle != "entrees"}


def verifier(recu: Any) -> tuple[bool, str]:
    """`(True, "")` si le reçu est bien formé et que ses empreintes correspondent à son contenu ; `(False, raison)`
    sinon. Ne rejoue PAS le calcul (c'est `moteur_calcul.rejouer`) : il prouve seulement que rien n'a été retouché."""
    if not isinstance(recu, Mapping):
        return False, "le reçu doit être un objet"
    attendus = set(_CHAMPS) | {"empreinte"}
    presents = set(recu)
    if not attendus <= presents or presents - attendus - {"entrees"}:
        return False, f"champs attendus : {sorted(attendus)} (et `entrees` facultatif)"
    if recu["type"] != "RECU_CALCUL" or recu["format"] != FORMAT:
        return False, f"type ou format inconnu (attendu RECU_CALCUL, {FORMAT})"
    try:
        _controler_json(dict(recu))
    except TypeError as exc:
        return False, str(exc)
    if "entrees" in recu:
        if not isinstance(recu["entrees"], dict):
            return False, "entrees : objet attendu"
        if encodage.empreinte(FORMAT, "entrees", recu["entrees"]) != recu["empreinte_entrees"]:
            return False, "empreinte_entrees ne correspond pas aux entrées (retouchées ?)"
    if _empreinte_du_corps(recu) != recu["empreinte"]:
        return False, "empreinte ne correspond pas au contenu du reçu (retouché ?)"
    return True, ""
