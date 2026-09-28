"""Registre chaîné, append-only, déterministe et immuable pour le module M4 (Field Operations).

Chaque maillon enregistré porte un identifiant unique (ligne_id) qui incorpore
cryptographiquement l'identifiant du maillon précédent. Ce chaînage garantit
la détection de toute suppression, insertion ou altération d'une entrée.
L'intégrité complète est vérifiable via l'ancre (tête de chaîne) et le recalcul
déterministe de l'empreinte globale, offrant ainsi une piste d'audit append-only.

Module pur (ADR-0009) : aucun import d'``opsys`` ni de SQLAlchemy. ``Registre`` ne sait pas où
vivent ses maillons — une liste Python en mémoire par défaut (perdue à l'arrêt du processus,
comportement historique), ou tout objet qui s'en comporte comme une (``len``, index positif et
négatif, tranche, itération, ``append``, ``extend``, copie profonde en liste), notamment
``opsys.stockage.MaillonsDurables`` — c'est `outils.py` (l'adaptateur, seul) qui fait ce choix pour
le registre de production. L'empreinte globale et tout état dérivé sont recalculés DEPUIS les
maillons reçus (jamais supposés vides), paresseusement au premier besoin réel (`ajouter()` ou
`valider_chaine()`/`assert_chaine()`) : construire un `Registre` ne lit rien au support, et une
instance rouverte sur un registre durable déjà peuplé (relecture après redémarrage) reflète l'état
réel dès sa première vérification.
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
    "variance_m6_recue",  # T1.3-b : trace du signal m6.variance_chantier reçu par M4 (outbox.py)
}


class VerificationError(Exception):
    """Exception levée par assert_chaine en cas d'intégrité compromise."""


def _valider_horodatage_local(chaine: str) -> None:
    """Validation minimale d'horodatage : ISO-8601 avec timezone, lève ValueError sinon."""
    try:
        dt = datetime.fromisoformat(chaine)
    except Exception:
        raise ValueError("horodatage invalide (format ISO 8601 avec timezone requis)") from None
    if dt.tzinfo is None:
        raise ValueError("horodatage invalide (timezone absente)")


class Registre:
    """Journal immuable chaîné par empreintes cryptographiques (M4)."""

    def __init__(self, maillons=None):
        """``maillons`` : la suite où vivent les maillons (protocole liste, cf. docstring du
        module). ``None`` (par défaut) garde le comportement historique : une liste Python en
        mémoire, vide au départ.

        L'empreinte globale n'est JAMAIS supposée être celle d'une chaîne vide : elle se calcule
        depuis ``maillons`` tel que reçu, au premier besoin (voir ``_empreinte_reference``), pour
        qu'une instance rouverte sur un registre durable déjà peuplé (redémarrage du processus)
        reflète un état exact dès sa première vérification — sans jamais supposer une chaîne
        vide. Calcul PARESSEUX, pas seulement pour l'efficacité : construire un ``Registre`` ne
        doit rien lire au support (utile à un appelant qui construit l'objet sans forcément s'en
        servir, ex. `charger_outils()` qui liste seulement les outils exposés).
        """
        self._chain = maillons if maillons is not None else []
        self._empreinte = None  # calculée au premier besoin, cf. _empreinte_reference

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
        # Mise à jour de l'empreinte globale : recalcul intégral depuis self._chain, PAS un
        # pliage incrémental (empreinte_precedente, nouveau ligne_id). Un pliage incrémental
        # serait correct (sha256 est un digest en flux, `_hash_chaine` ne fait que concaténer un
        # segment canonique par ligne_id avant de hacher), mais seulement en dupliquant, ici, la
        # forme exacte de ce segment — un détail interne et privé d'`encodage.encoder_canonique`
        # que ce module n'importe pas pour rester en accord avec lui (cf. docstring d'encodage.py
        # : cette même canonicalisation a déjà été corrigée à deux reprises ailleurs). Le
        # recalcul intégral reste O(n) par ajout, mais chaque lecture métier (`lire()`,
        # `statut_courant`, ...) est déjà O(n) par appel sur ce registre : ce n'est pas une
        # nouvelle classe de coût, et `valider_chaine()` relit de toute façon l'intégralité de
        # `self._chain` pour ce même calcul. Comportement inchangé, prouvé par
        # test_registre_durable.py (mêmes ligne_id, mêmes têtes, en mémoire et en durable).
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

    def _empreinte_reference(self) -> str:
        """Empreinte globale mémorisée (souvenir du dernier `ajouter()`), calculée depuis
        `self._chain` au premier besoin si aucun ajout n'a encore eu lieu sur cette instance —
        notamment une instance neuve rouverte sur un registre durable déjà peuplé, jamais
        supposée vide. Une fois calculée, elle n'est PAS recalculée ici : c'est le "avant" fixe
        auquel `_diagnostiquer` compare un recalcul frais, ce qui détecte une troncature de queue
        (cf. test_troncature_de_queue_detectee_sans_ancre) que `ajouter()` seul maintient à jour."""
        if self._empreinte is None:
            self._empreinte = _hash_chaine(self._chain)
        return self._empreinte

    def _diagnostiquer(self, ancre=None):
        """Retourne (bool, str) : True + '' si valide, sinon False + message explicatif."""
        # 1) Empreinte globale
        if _hash_chaine(self._chain) != self._empreinte_reference():
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
