"""File d'approbation 0-6 pour les content-items."""

_QUEUE = {}


def reset():
    """Vide la file (utilisé par les tests pour isolation)."""
    _QUEUE.clear()


def propose(item: dict, actor: str) -> dict:
    """Propose un item à la file. Enregistre le proposer.

    Lève ValueError si actor est vide.
    """
    if not actor:
        raise ValueError("acteur obligatoire")

    item = dict(item)  # shallow copy pour éviter les effets de bord
    item["proposer"] = actor
    item["approval_status"] = "PROPOSE"
    _QUEUE[item["id"]] = item
    return item


def approve(item: dict, actor: str) -> dict:
    """Approuve un item. L'acteur doit être différent du proposer.

    Lève ValueError si actor est vide ou identique au proposer.
    """
    if not actor:
        raise ValueError("acteur obligatoire")
    if actor == item.get("proposer"):
        raise ValueError("auto-approbation interdite")

    item = dict(item)
    item["approval_status"] = "APPROVED"
    item["approver"] = actor
    _QUEUE[item["id"]] = item
    return item


def reject(item: dict, actor: str) -> dict:
    """Rejette un item. Enregistre l'approver."""
    if not actor:
        raise ValueError("acteur obligatoire")

    item = dict(item)
    item["approval_status"] = "REJECTED"
    item["approver"] = actor
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
