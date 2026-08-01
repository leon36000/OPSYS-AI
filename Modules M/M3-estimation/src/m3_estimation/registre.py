"""Registre append-only hash-chaîné des estimations M3.

Le registre garantit que chaque maillon conserve une charge indépendante, un
prédécesseur explicite et un hash déterministe calculé sur son rang, sa charge
et ce prédécesseur. Le rang entre dans le hachage afin qu'un retrait, une
duplication ou une permutation de maillons ne puisse pas rester indétecté.
Il ne garantit pas la véracité métier de la charge ni son origine : il garantit
uniquement son intégrité depuis son ajout dans cette instance.

Aucune horloge n'est consultée ici : tout horodatage éventuel relève de la
charge fournie par l'appelant, ce qui préserve le déterminisme du registre.
Chaque maillon réserve explicitement ``cout_reel`` à ``None`` : M5/M6 pourront
le renseigner ultérieurement sans confondre une place prévue avec une donnée
absente. Ce module produit le ``hash_maillon`` transmis ensuite à ``devis.py``
comme paramètre ; il n'importe pas ce module afin d'éviter toute dépendance
circulaire.
"""

import copy
import hashlib
import json

from . import verdicts

__all__ = ["HASH_PREDECESSEUR_INITIAL", "Registre"]


HASH_PREDECESSEUR_INITIAL = (
    "0000000000000000000000000000000000000000000000000000000000000000"
)

_CLES_CHARGE_REQUISES = frozenset(
    {
        "devis_id",
        "lead_id",
        "empreinte_marqueur_m2",
        "niveau_confiance",
        "bareme_version",
        "graine_monte_carlo",
    }
)
_CLES_MAILLON = frozenset(
    {"rang", "charge", "hash_precedent", "hash_maillon", "cout_reel"}
)


def _normaliser(objet):
    """Retourne une représentation JSON déterministe et injective."""
    if isinstance(objet, dict):
        elements = [
            (_normaliser(cle), _normaliser(valeur))
            for cle, valeur in objet.items()
        ]
        elements.sort(
            key=lambda paire: json.dumps(
                paire[0], separators=(",", ":"), ensure_ascii=True
            )
        )
        return ["__dict__", [[cle, valeur] for cle, valeur in elements]]
    if isinstance(objet, set):
        elements = [_normaliser(element) for element in objet]
        elements.sort(
            key=lambda element: json.dumps(
                element, separators=(",", ":"), ensure_ascii=True
            )
        )
        return ["__set__", elements]
    if isinstance(objet, frozenset):
        elements = [_normaliser(element) for element in objet]
        elements.sort(
            key=lambda element: json.dumps(
                element, separators=(",", ":"), ensure_ascii=True
            )
        )
        return ["__frozenset__", elements]
    if isinstance(objet, list):
        return ["__list__", [_normaliser(element) for element in objet]]
    if isinstance(objet, tuple):
        return ["__tuple__", [_normaliser(element) for element in objet]]
    if isinstance(objet, (str, int, float, bool)) or objet is None:
        return objet
    if isinstance(objet, bytes):
        return ["__bytes__", objet.hex()]
    if isinstance(objet, bytearray):
        return ["__bytearray__", bytes(objet).hex()]
    if isinstance(objet, complex):
        return ["__complex__", [repr(objet.real), repr(objet.imag)]]
    raise TypeError(f"Type non supporté dans le registre : {type(objet).__name__}")


def _encoder_canonique(*valeurs):
    """Encode des valeurs normalisées dans un flux SHA-256 déterministe."""
    segments = []
    for valeur in valeurs:
        serialise = json.dumps(
            _normaliser(valeur), separators=(",", ":"), ensure_ascii=True
        )
        segments.append(f"{len(serialise)}:{serialise}")
    return hashlib.sha256("".join(segments).encode("utf-8")).hexdigest()


def _charge_est_valide(charge):
    """Vérifie la forme minimale et la sérialisabilité canonique d'une charge."""
    if not isinstance(charge, dict):
        return False
    try:
        if not _CLES_CHARGE_REQUISES.issubset(charge):
            return False
        _encoder_canonique(charge)
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return False
    return True


def _verdict_refus(detail):
    """Construit le refus fermé commun aux entrées non exploitables."""
    return verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail)


def _hash_maillon(rang, hash_precedent, charge, cout_reel):
    """Calcule le hash d'un maillon en incluant explicitement son rang."""
    return _encoder_canonique(
        {
            "rang": rang,
            "hash_precedent": hash_precedent,
            "charge": charge,
            "cout_reel": cout_reel,
        }
    )


class Registre:
    """Journal en mémoire append-only des charges d'estimation M3."""

    def __init__(self):
        self._maillons = []

    def ajouter(self, charge):
        """Ajoute une charge valide et retourne ``(maillon, None)``.

        Une charge invalide ne modifie jamais le journal et retourne
        ``(None, verdict)``.
        """
        if not _charge_est_valide(charge):
            return None, _verdict_refus("Charge d'estimation invalide.")

        try:
            charge_copiee = copy.deepcopy(charge)
            rang = len(self._maillons)
            hash_precedent = (
                HASH_PREDECESSEUR_INITIAL
                if rang == 0
                else self._maillons[-1]["hash_maillon"]
            )
            cout_reel = None
            hash_courant = _hash_maillon(
                rang, hash_precedent, charge_copiee, cout_reel
            )
            maillon = {
                "rang": rang,
                "charge": charge_copiee,
                "hash_precedent": hash_precedent,
                "hash_maillon": hash_courant,
                "cout_reel": cout_reel,
            }
            self._maillons.append(maillon)
            return copy.deepcopy(maillon), None
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            RecursionError,
        ):
            return None, _verdict_refus("Charge d'estimation non canonique.")

    def lire(self):
        """Retourne une copie profonde, jamais une référence interne vivante."""
        return copy.deepcopy(self._maillons)

    def valider_chaine(self):
        """Contrôle l'intégrité complète de la chaîne et localise le rang fautif."""
        for rang, maillon in enumerate(self._maillons):
            try:
                if not isinstance(maillon, dict):
                    return False, f"Maillon invalide au rang {rang}"
                if set(maillon) != _CLES_MAILLON:
                    return False, f"Maillon invalide au rang {rang}"
                if not _charge_est_valide(maillon["charge"]):
                    return False, f"Maillon invalide au rang {rang}"
                if maillon["cout_reel"] is not None:
                    return False, f"Maillon invalide au rang {rang}"

                hash_recalcule = _hash_maillon(
                    maillon["rang"],
                    maillon["hash_precedent"],
                    maillon["charge"],
                    maillon["cout_reel"],
                )
                if maillon["hash_maillon"] != hash_recalcule:
                    return False, f"Maillon invalide au rang {rang}"
            except (
                AttributeError,
                KeyError,
                TypeError,
                ValueError,
                RecursionError,
            ):
                return False, f"Maillon invalide au rang {rang}"

        hash_attendu_precedent = HASH_PREDECESSEUR_INITIAL
        for rang, maillon in enumerate(self._maillons):
            try:
                # L'intégrité propre est vérifiée avant le chaînage : vérifier
                # le chaînage d'abord accuserait le maillon suivant de la faute
                # de son prédécesseur corrompu.
                if maillon["rang"] != rang:
                    return False, f"Maillon invalide au rang {rang}"
                if maillon["hash_precedent"] != hash_attendu_precedent:
                    return False, f"Maillon invalide au rang {rang}"
                hash_attendu_precedent = maillon["hash_maillon"]
            except (
                AttributeError,
                KeyError,
                TypeError,
                ValueError,
                RecursionError,
            ):
                return False, f"Maillon invalide au rang {rang}"

        return True, ""
