"""File d'approbation 0-6 pour les content-items.

Chaque transition trace acteur + timestamp :
  propose → proposer / propose_timestamp
  approve / reject → approver / approval_timestamp
"""

_QUEUE = {}


def reset():
    """Vide la file (utilisé par les tests pour isolation)."""
    _QUEUE.clear()


def propose(item: dict, actor: str, timestamp: str = "") -> dict:
    """Propose un item à la file. Enregistre le proposer et l'horodatage.

    Lève ValueError si actor est vide.
    Le timestamp de proposition est conservé dans propose_timestamp ;
    approval_timestamp est remis à vide.
    """
    if not actor:
        raise ValueError("acteur obligatoire")

    item = dict(item)  # shallow copy pour éviter les effets de bord
    item["proposer"] = actor
    item["propose_timestamp"] = timestamp
    item["approval_status"] = "PROPOSE"
    item["approval_timestamp"] = ""
    _QUEUE[item["id"]] = item
    return item


def _exiger_item_propose(item: dict, verbe: str) -> None:
    """Fail-closed : refuse toute transition sur un item jamais entré dans la file
    (ou déjà tranché) en le comparant à l'état réellement enregistré par propose().
    Sans ce garde-fou, un item forgé (jamais proposé) pouvait être approuvé/rejeté."""
    item_id = item.get("id")
    en_file = _QUEUE.get(item_id)
    if en_file is None or en_file.get("approval_status") != "PROPOSE":
        raise ValueError(
            f"item jamais proposé ou déjà tranché : {verbe} refusé pour id={item_id!r}"
        )


def approve(item: dict, actor: str, timestamp: str = "") -> dict:
    """Approuve un item. L'acteur doit être différent du proposer.

    Lève ValueError si actor est vide ou identique au proposer, ou si l'item
    n'a jamais été proposé (n'est pas actuellement PROPOSE dans la file).
    Enregistre le timestamp d'approbation fourni (tel quel).
    """
    if not actor:
        raise ValueError("acteur obligatoire")
    _exiger_item_propose(item, "approbation")
    if actor == item.get("proposer"):
        raise ValueError("auto-approbation interdite")

    item = dict(item)
    item["approval_status"] = "APPROVED"
    item["approver"] = actor
    item["approval_timestamp"] = timestamp
    _QUEUE[item["id"]] = item
    return item


def reject(item: dict, actor: str, timestamp: str = "") -> dict:
    """Rejette un item. L'acteur doit être différent du proposer.

    Lève ValueError si actor est vide ou identique au proposer, ou si l'item
    n'a jamais été proposé (n'est pas actuellement PROPOSE dans la file).
    Enregistre le timestamp de rejet fourni (tel quel).
    """
    if not actor:
        raise ValueError("acteur obligatoire")
    _exiger_item_propose(item, "rejet")
    if actor == item.get("proposer"):
        raise ValueError("auto-rejet interdit")

    item = dict(item)
    item["approval_status"] = "REJECTED"
    item["approver"] = actor
    item["approval_timestamp"] = timestamp
    _QUEUE[item["id"]] = item
    return item


def list_items(status: str | None = None) -> list[dict]:
    """Retourne les items de la file, filtrés par statut optionnellement."""
    return [
        item
        for item in _QUEUE.values()
        if status is None or item.get("approval_status") == status
    ]


def publish(item: dict) -> None:
    """Publie l'item si son statut est APPROVED.

    Lève RuntimeError si le statut n'est pas APPROVED (fail-closed).
    """
    if item.get("approval_status") != "APPROVED":
        raise RuntimeError("APPROVED requis")
    # Publication réelle en mode ombre (rien à faire ici)
