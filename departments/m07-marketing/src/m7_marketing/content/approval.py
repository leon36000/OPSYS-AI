"""File d'approbation 0-6 pour les content-items.

La file conserve une copie indépendante de chaque proposition. L'identifiant désigne
la proposition enregistrée ; le corps transmis à une transition doit encore être
identique à cette version. Cette primitive en mémoire ne remplace pas les contrôles
d'identité et de consentement du service durable.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime

_QUEUE: dict[str, dict] = {}
_FINGERPRINTS: dict[str, str] = {}


def _acteur_proposant_confirme() -> str:
    """Acteur de proposition issu du contexte serveur M7, jamais de l'argument historique `actor`."""
    from ..usine.service import _qui_appelle

    return _qui_appelle()[0]


def _horodatage_serveur() -> str:
    """Heure de réception posée par le transport, ou horloge UTC locale; aucun horodatage d'outil ne fait foi."""
    from opsys import contexte

    reception = contexte.horodatage_reception()
    return reception.recu_le.isoformat() if reception is not None else datetime.now(UTC).isoformat()


def _acteur_approbateur_proprietaire() -> str:
    """Identité propriétaire revérifiée en base pendant une transaction OPSYS serveur."""
    from opsys import stockage

    if stockage.connexion_courante() is None:
        raise PermissionError("approbation refusée : transaction et identité serveur propriétaire requises")
    from ..usine.service import _proprietaire_qui_decide

    acteur, refus = _proprietaire_qui_decide("m7_legacy_content_approval")
    if acteur is None:
        detail = refus.get("detail", "identité propriétaire non vérifiée") if refus else "identité requise"
        raise PermissionError(f"approbation refusée : {detail}")
    return acteur["par"]


def _copie(item: dict) -> dict:
    return copy.deepcopy(item)


def _empreinte(item: dict, *, etat: bool = True) -> str:
    contenu = _copie(item)
    if not etat:
        for cle in ("approval_status", "approver", "approval_timestamp"):
            contenu.pop(cle, None)
    canonique = json.dumps(contenu, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def reset():
    """Vide la file (utilisé par les tests pour isolation)."""
    _QUEUE.clear()
    _FINGERPRINTS.clear()


def propose(item: dict, actor: str, timestamp: str = "") -> dict:
    """Enregistre une copie et une empreinte; le champ actor historique n'est pas une preuve d'identité."""
    en_file = _copie(item)
    en_file["proposer"] = _acteur_proposant_confirme()
    en_file["propose_timestamp"] = _horodatage_serveur()
    en_file["approval_status"] = "PROPOSE"
    en_file["approval_timestamp"] = ""
    item_id = en_file["id"]
    _QUEUE[item_id] = en_file
    _FINGERPRINTS[item_id] = _empreinte(en_file, etat=False)
    return _copie(en_file)


def _exiger_item_propose(item: dict, verbe: str) -> dict:
    """Relit la proposition et refuse les objets forgés, modifiés ou déjà tranchés."""
    item_id = item.get("id")
    en_file = _QUEUE.get(item_id)
    if en_file is None or en_file.get("approval_status") != "PROPOSE":
        raise ValueError(f"item jamais proposé ou déjà tranché : {verbe} refusé pour id={item_id!r}")
    if _empreinte(item, etat=False) != _FINGERPRINTS[item_id]:
        raise ValueError(f"contenu ou identité modifié depuis la proposition : {verbe} refusé pour id={item_id!r}")
    return _copie(en_file)


def approve(item: dict, actor: str, timestamp: str = "") -> dict:
    """Approuve la copie exacte en file via identité propriétaire M7 confirmée; `actor` est ignoré."""
    approbateur = _acteur_approbateur_proprietaire()
    en_file = _exiger_item_propose(item, "approbation")
    if approbateur == en_file.get("proposer"):
        raise ValueError("auto-approbation interdite")
    en_file.update(approval_status="APPROVED", approver=approbateur, approval_timestamp=_horodatage_serveur())
    _QUEUE[en_file["id"]] = en_file
    return _copie(en_file)


def reject(item: dict, actor: str, timestamp: str = "") -> dict:
    """Rejette la copie exacte via identité propriétaire M7 confirmée; `actor` est ignoré."""
    approbateur = _acteur_approbateur_proprietaire()
    en_file = _exiger_item_propose(item, "rejet")
    if approbateur == en_file.get("proposer"):
        raise ValueError("auto-rejet interdit")
    en_file.update(approval_status="REJECTED", approver=approbateur, approval_timestamp=_horodatage_serveur())
    _QUEUE[en_file["id"]] = en_file
    return _copie(en_file)


def list_items(status: str | None = None) -> list[dict]:
    """Retourne des copies isolées de la file, éventuellement filtrées par statut."""
    return [
        _copie(item)
        for item in _QUEUE.values()
        if status is None or item.get("approval_status") == status
    ]


def publish(item: dict) -> None:
    """Garde de démonstration: vérifie l'état/hachage; cette primitive ne publie jamais rien."""
    item_id = item.get("id")
    en_file = _QUEUE.get(item_id)
    if en_file is None or en_file.get("approval_status") != "APPROVED":
        raise RuntimeError("APPROVED requis dans la file")
    if _empreinte(item, etat=False) != _FINGERPRINTS[item_id]:
        raise RuntimeError("le contenu ne correspond pas à la version approuvée en file")
