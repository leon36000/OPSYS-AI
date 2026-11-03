"""Achat sur place (C6, M6.17) : urgent, tracé, limité, transmis à M5 sans jamais payer.

Un employé achète un matériau en quincaillerie (article inédit ou rupture terrain) : la déclaration
porte le fournisseur (libre), le montant EXACT en texte décimal (jamais un float), la raison/urgence,
le chantier et la photo du reçu CAS OBLIGATOIRE (`fichier:sha256:`, déclarée, jamais authentifiée
ici). Un plafond DÉCLARÉ (direction, CFG-1, jamais un nombre codé en dur) décide : sous le plafond
(ou à la borne), accepté ; au-delà, ou plafond absent (fail-closed), attente admin N3 AVANT toute
entrée au stock. L'achat accepté donne une attente M5 « dépense terrain à saisir » : M5 décide,
M6 ne paie ni ne rembourse jamais.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge, aucun aléa, aucun réseau.
Le montant est comparé en `Decimal` exact sur son texte (`Decimal(str)`), jamais en flottant : 150.00
est sous le plafond de 150, 150.01 est au-delà.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

__all__ = ["decider", "enregistrer", "attente_m5", "valider_achat"]

# Photo du reçu : même contrat que `preuves_pertes_bris.REFERENCE_CAS` (déclarée, non authentifiée).
_REFERENCE_CAS = re.compile(r"fichier:sha256:[0-9a-f]{64}\Z")

# Rôles d'appareil autorisés à déclarer (ROLES.md) : l'achat sur place est un geste terrain.
_ROLES_AUTORISES = frozenset({"employee", "admin"})

_CHAMPS_REQUIS = frozenset(
    {"materiau_id", "quantite", "montant", "devise", "fournisseur", "raison", "chantier_id", "recu"}
)


def _montant(texte: Any) -> Decimal | None:
    """Le montant en décimal exact depuis son TEXTE (jamais un float) ; `None` sinon."""
    if isinstance(texte, bool) or not isinstance(texte, str):
        return None
    try:
        montant = Decimal(texte)
    except InvalidOperation:
        return None
    if not montant.is_finite() or montant <= 0:
        return None
    return montant


def valider_achat(achat: Any, role: str = "employee") -> tuple[dict[str, Any] | None, str | None]:
    """`(achat, None)` pour un achat déclarable, ou `(None, code)` fail-closed.

    Refuse : rôle hors terrain, forme incomplète, quantité non positive, montant non décimal
    (un float n'est pas une donnée de caisse), devise absente, reçu photo non CAS
    (`REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`, même code que le formulaire de fin de chantier).
    Aucun plafond ici : c'est `decider` qui le lit.
    """
    if role not in _ROLES_AUTORISES:
        return None, "REJ-ACHAT-TERRAIN-ROLE-INTERDIT"
    if not isinstance(achat, Mapping) or not (_CHAMPS_REQUIS - {"recu"}).issubset(set(achat.keys())):
        return None, "REJ-ACHAT-TERRAIN-STRUCTURE-INVALIDE"
    if not isinstance(achat.get("materiau_id"), str) or not achat["materiau_id"]:
        return None, "REJ-ACHAT-TERRAIN-STRUCTURE-INVALIDE"
    quantite = achat.get("quantite")
    if isinstance(quantite, bool) or not isinstance(quantite, (int, float)) or quantite <= 0:
        return None, "REJ-ACHAT-TERRAIN-QUANTITE-INVALIDE"
    montant = _montant(achat.get("montant"))
    if montant is None:
        return None, "REJ-ACHAT-TERRAIN-MONTANT-INVALIDE"
    if not isinstance(achat.get("devise"), str) or not achat["devise"].strip():
        return None, "REJ-ACHAT-TERRAIN-DEVISE-INVALIDE"
    if not isinstance(achat.get("fournisseur"), str) or not achat["fournisseur"].strip():
        return None, "REJ-ACHAT-TERRAIN-FOURNISSEUR-INVALIDE"
    if not isinstance(achat.get("raison"), str) or not achat["raison"].strip():
        return None, "REJ-ACHAT-TERRAIN-RAISON-INVALIDE"
    if not isinstance(achat.get("chantier_id"), str) or not achat["chantier_id"]:
        return None, "REJ-ACHAT-TERRAIN-STRUCTURE-INVALIDE"
    recu = achat.get("recu")
    if not isinstance(recu, str) or _REFERENCE_CAS.fullmatch(recu) is None:
        return None, "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE"
    copie = dict(achat)
    copie["montant"] = format(montant, "f")
    return copie, None


def decider(achat: Mapping[str, Any], plafond: Any) -> dict[str, Any]:
    """Sous le plafond (borne incluse) : accepté ; au-delà, ou plafond absent/illisible : attente admin N3.

    Le plafond est le texte décimal DÉCLARÉ par la direction (CFG-1) ; absent ou illisible, aucune
    valeur de repli n'est inventée : l'achat attend (`plafond_absent`). M6 ne paie jamais : même
    accepté, l'achat n'est qu'une entrée tracée et une attente pour M5.
    """
    montant = _montant(achat.get("montant"))
    limite: Decimal | None = None
    if isinstance(plafond, str):
        try:
            candidat = Decimal(plafond)
            limite = candidat if candidat.is_finite() and candidat > 0 else None
        except InvalidOperation:
            limite = None
    if montant is None or limite is None:
        return {
            "statut": "en_attente_approbation",
            "niveau": "N3",
            "motif": "plafond_absent",
            "action_proposee": "L'admin adopte un plafond puis approuve ou refuse cet achat.",
        }
    if montant <= limite:
        return {"statut": "accepte", "approbation_requise": False}
    return {
        "statut": "en_attente_approbation",
        "niveau": "N3",
        "motif": "plafond_depasse",
        "montant": format(montant, "f"),
        "plafond": format(limite, "f"),
        "action_proposee": "L'admin approuve ou refuse cet achat avant son entrée au stock.",
    }


def attente_m5(achat: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que M5 doit saisir : une attente « dépense terrain à saisir », jamais un paiement.

    Ni `paiement`, ni `remboursement`, ni ordre : M5 (et un humain) décide(nt). L'employé ne voit
    aucun montant d'une autre ligne : cette attente porte le sien seul, sans marge.
    """
    return {
        "type": "depense_terrain_a_saisir",
        "materiau_id": achat["materiau_id"],
        "quantite": achat["quantite"],
        "montant": achat["montant"],
        "devise": achat["devise"],
        "fournisseur": achat["fournisseur"],
        "raison": achat["raison"],
        "chantier_id": achat["chantier_id"],
        "recu": achat["recu"],
        "source_prix": "RECU_TERRAIN",
    }


def enregistrer(achat: Mapping[str, Any], registre: list[dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
    """Trace l'achat accepté dans le registre en mémoire (idempotent par reçu + matériau + chantier).

    Un second dépôt du même reçu pour le même matériau et chantier est refusé
    (`REJ-ACHAT-TERRAIN-DEJA-DECLARE`) : la même photo ne paie pas deux fois. Rend le mouvement
    tracé (`ACHAT_TERRAIN`, montant et reçu dits) et le registre tel qu'il est après ajout.
    """
    cle = (achat.get("recu"), achat.get("materiau_id"), achat.get("chantier_id"))
    for mouvement in registre:
        if (mouvement.get("recu"), mouvement.get("materiau_id"), mouvement.get("chantier_id")) == cle:
            return {"registre": registre}, "REJ-ACHAT-TERRAIN-DEJA-DECLARE"
    mouvement = {
        "type_entree": "achat_terrain_declare",
        "chantier_id": achat["chantier_id"],
        "materiau_id": achat["materiau_id"],
        "quantite": achat["quantite"],
        "montant": achat["montant"],
        "devise": achat["devise"],
        "fournisseur": achat["fournisseur"],
        "raison": achat["raison"],
        "recu": achat["recu"],
        "source_prix": "RECU_TERRAIN",
    }
    return {"mouvement": mouvement, "registre": [*registre, mouvement]}, None
