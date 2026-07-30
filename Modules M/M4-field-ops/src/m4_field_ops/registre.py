"""Registre chaîné, append-only, déterministe et immuable pour le module M4 (Field Operations).

Chaque maillon enregistré porte un identifiant unique (ligne_id) qui incorpore
cryptographiquement l'identifiant du maillon précédent. Ce chaînage garantit
la détection de toute suppression, insertion ou altération d'une entrée.
L'intégrité complète est vérifiable via l'ancre (tête de chaîne) et le recalcul
déterministe de l'empreinte globale, offrant ainsi une piste d'audit append-only.
"""
import copy
from datetime import datetime

from . import encodage

__all__ = ["Registre", "VerificationError"]


# Énumération fermée des types d'entrée acceptés pour M4.
_TYPE_ENTREE_VALIDES = {
    "intervention_inscrite",
    "transition_statut",
    "pointage",
    "demande_revue",
    "resolution_revue",
}


class VerificationError(Exception):
    """Exception levée par assert_chaine en cas d'intégrité compromise."""


def _valider_horodatage_local(chaine: str) -> None:
    """Validation minimale d'horodatage : ISO-8601 avec timezone, lève ValueError sinon."""
    try:
        dt = datetime.fromisoformat(chaine)
    except Exception:
        raise ValueError("horodatage invalide (format ISO 8601 avec timezone requis)")
    if dt.tzinfo is None:
        raise ValueError("horodatage invalide (timezone absente)")


class Registre:
    """Journal immuable chaîné par empreintes cryptographiques (M4)."""

    def __init__(self):
        self._chain = []
        # Empreinte de la chaîne vide, sert de référence pour valider_chaine.
        self._empreinte = encodage.empreinte()

    # ----------------------------------------------------------------
    # API publique
    # ----------------------------------------------------------------
    def ajouter(self, entree: dict) -> str:
        """Ajoute une entrée validée, retourne son identifiant unique (ligne_id)."""
        if not isinstance(entree, dict):
            raise TypeError("L'entrée doit être un dictionnaire.")

        # --- Validation type_entree ---
        type_entree = entree.get("type_entree")
        if type_entree not in _TYPE_ENTREE_VALIDES:
            raise ValueError(
                f"type_entree non reconnu : {type_entree!r}. "
                f"Attendu l'un de {sorted(_TYPE_ENTREE_VALIDES)}."
            )

        # --- Validation horodatage (locale et minimale) ---
        if "horodatage" not in entree:
            raise KeyError("horodatage")
        try:
            _valider_horodatage_local(entree["horodatage"])
        except ValueError as e:
            raise ValueError(f"horodatage invalide : {e}") from None

        # --- Copie profonde pour immuabilité ---
        entree_copy = copy.deepcopy(entree)
        # Supprime toute trace d'identifiants internes qui aurait pu être fournie.
        entree_copy.pop("ligne_id", None)
        entree_copy.pop("precedent_ligne_id", None)

        # --- Chaînage ---
        precedent = self._chain[-1]["ligne_id"] if self._chain else None
        ligne_id = encodage.empreinte(entree_copy, precedent)

        maillon = dict(entree_copy)
        maillon["ligne_id"] = ligne_id
        maillon["precedent_ligne_id"] = precedent

        self._chain.append(maillon)
        # Mise à jour de l'empreinte globale
        self._empreinte = _hash_chaine(self._chain)

        return ligne_id

    def lire(self, depuis=None):
        """Retourne une copie de tout ou partie du registre, à partir d'un ligne_id."""
        if depuis is None:
            return copy.deepcopy(self._chain)
        for i, m in enumerate(self._chain):
            if m["ligne_id"] == depuis:
                return copy.deepcopy(self._chain[i:])
        raise ValueError(f"ligne_id {depuis!r} introuvable dans le registre.")

    def tete(self):
        """Identifiant du dernier maillon (None si vide)."""
        return self._chain[-1]["ligne_id"] if self._chain else None

    def taille(self):
        """Nombre d'entrées enregistrées."""
        return len(self._chain)

    def valider_chaine(self, ancre=None):
        """
        Vérifie l'intégrité complète de la chaîne.

        Recalcule ligne par ligne et compare l'empreinte globale, puis
        vérifie optionnellement que la tête correspond à l'ancre fournie.
        **Limitation** : sans ancre externe, une réécriture complète de la
        chaîne (tous les maillons remplacés par une autre chaîne valide)
        ne sera pas détectée.
        """
        ok, _ = self._diagnostiquer(ancre)
        return ok

    def assert_chaine(self, ancre=None):
        """Lève VerificationError si la chaîne est corrompue, avec un diagnostic précis."""
        ok, msg = self._diagnostiquer(ancre)
        if not ok:
            raise VerificationError(msg)

    def _diagnostiquer(self, ancre=None):
        """Retourne (bool, str) : True + '' si valide, sinon False + message explicatif."""
        # 1) Empreinte globale
        if _hash_chaine(self._chain) != self._empreinte:
            return False, "chaîne invalide ou altérée (empreinte globale incohérente)"
        # 2) Vérification de chaque maillon
        prec_attendu = None
        for idx, m in enumerate(self._chain):
            if m["precedent_ligne_id"] != prec_attendu:
                return False, (
                    f"chaîne invalide ou altérée : maillon {idx} a un precedent_ligne_id incohérent "
                    f"(attendu {prec_attendu!r}, reçu {m['precedent_ligne_id']!r})"
                )
            entree_pure = {
                k: v for k, v in m.items() if k not in ("ligne_id", "precedent_ligne_id")
            }
            try:
                calc_id = encodage.empreinte(entree_pure, prec_attendu)
            except Exception:
                return False, (
                    f"chaîne invalide ou altérée : échec du recalcul du ligne_id pour le maillon {idx}"
                )
            if m["ligne_id"] != calc_id:
                return False, (
                    f"chaîne invalide ou altérée : ligne_id du maillon {idx} incohérent"
                )
            prec_attendu = m["ligne_id"]
        # 3) Ancre externe
        if ancre is not None and self.tete() != ancre:
            return False, (
                f"L'ancre fournie ({ancre!r}) ne correspond pas à la tête actuelle "
                f"({self.tete()!r}). Réécriture complète possible de la chaîne."
            )
        return True, ""


# -----------------------------------------------------------------
# Helper interne (ne modifie pas la liste, donc pas de .append ici)
# -----------------------------------------------------------------
def _hash_chaine(chaine_list):
    """Calcule l'empreinte de la liste des ligne_id."""
    return encodage.empreinte(*[m["ligne_id"] for m in chaine_list])
