"""Registre append-only hash-chaîné des estimations M3.

Le registre garantit l'intégrité cohérente des maillons qu'il conserve et
détecte toute altération partielle d'un maillon suivi d'au moins un autre
maillon. Il ne garantit ni l'authenticité métier des charges, ni leur origine,
ni la réécriture cohérente du dernier maillon, ni la réécriture cohérente de
la chaîne entière : sans ancre externe ni secret, une personne pouvant
réécrire toute la structure peut recalculer les hashes.

Mesure explicitement connue :
    intacte                                          -> (True, '')
    reecriture coherente du DERNIER maillon          -> (True, '')
    reecriture coherente d un maillon du MILIEU      -> (False, 'rang 2')
    reecriture coherente de TOUTE la chaine          -> (True, '')

La mitigation prévue est l'épinglage externe de ``hash_tete()`` dans un
registre de dépôt, un journal externe ou toute autre ancre indépendante. Le
module expose cette tête en lecture seule, mais ne peut pas appliquer lui-même
une ancre située hors de son instance.

Aucune horloge, aucun aléa et aucun réseau ne sont consultés. Chaque maillon
réserve ``cout_reel`` à ``None`` pour M5/M6 ; le mécanisme qui permettra de le
renseigner viendra avec ces modules. Jusque-là, toute valeur non nulle est
refusée fail-closed par la validation.
"""

import copy
import hashlib
import json
import math

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
    """Retourne une représentation JSON déterministe des seuls types admis."""
    if isinstance(objet, dict):
        elements = []
        for cle, valeur in objet.items():
            if not isinstance(cle, str):
                raise TypeError("Les clés de charge doivent être des chaînes.")
            elements.append((cle, _normaliser(valeur)))
        elements.sort(key=lambda paire: paire[0])
        return ["__dict__", [[cle, valeur] for cle, valeur in elements]]
    if isinstance(objet, list):
        return ["__list__", [_normaliser(element) for element in objet]]
    if isinstance(objet, str):
        return objet
    if type(objet) is bool or objet is None:
        return objet
    if type(objet) is int:
        return objet
    if type(objet) is float:
        if not math.isfinite(objet):
            raise TypeError("Les flottants non finis sont interdits.")
        return objet
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
    """Vérifie la forme minimale et les types canoniques admis d'une charge."""
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
    """Journal append-only des charges d'estimation M3.

    Module pur (ADR-0009) : aucun import d'``opsys`` ni de SQLAlchemy. ``Registre`` ignore où
    vivent ses maillons — une liste Python en mémoire par défaut (perdue à l'arrêt du
    processus, comportement historique), ou tout objet qui s'en comporte comme une (``len``,
    index positif et négatif, tranche, itération, ``append``), notamment
    ``opsys.stockage.MaillonsDurables`` : c'est l'appelant (l'adaptateur de production dans
    ``outils.py``, jamais ce module) qui fait ce choix. Aucun état dérivé n'est mis en cache :
    ``hash_tete()`` et ``valider_chaine()`` relisent ``self._maillons`` à chaque appel, donc une
    instance rouverte sur un registre durable déjà peuplé (redémarrage du processus) reflète
    l'état réel dès son premier appel, sans jamais supposer une chaîne vide.
    """

    def __init__(self, maillons=None):
        """``maillons`` : le support où vivent les maillons (protocole liste, cf. docstring de
        la classe). ``None`` (par défaut) garde le comportement historique : une liste Python en
        mémoire, vide au départ."""
        self._maillons = maillons if maillons is not None else []

    def ajouter(self, charge):
        """Ajoute une charge valide et retourne ``(maillon, None)``."""
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
            # Le rang et la tête lus ci-dessus fondent le hash : un support durable refuse l'ajout si un
            # autre appel a écrit depuis (``rang_attendu`` du socle, ``EcritureConcurrente``), plutôt que
            # d'enchaîner deux maillons au même prédécesseur et de casser la chaîne. Une liste n'a pas
            # d'autre écrivain.
            if isinstance(self._maillons, list):
                self._maillons.append(maillon)
            else:
                self._maillons.append(maillon, rang_attendu=rang)
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

    def hash_tete(self):
        """Retourne la tête à épingler hors du registre, sans exposer son état."""
        if not self._maillons:
            return HASH_PREDECESSEUR_INITIAL
        return self._maillons[-1]["hash_maillon"]

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
                if type(maillon["rang"]) is not int:
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
                if type(maillon["rang"]) is not int or maillon["rang"] != rang:
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
