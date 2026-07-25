import re
from datetime import datetime
from pathlib import Path
import yaml


def validate_content_item(item: dict) -> bool:
    """Valide un item de contenu contre le contrat content-item.v1.yaml.
    
    Lève ValueError en français si une règle n'est pas respectée.
    Retourne True si l'item est parfaitement conforme.
    """
    # Charger le contrat pour connaître la liste des champs obligatoires
    contract_path = (
        Path(__file__).resolve().parents[2] / "contracts" / "content-item.v1.yaml"
    )
    with open(contract_path, encoding="utf-8") as fh:
        contract = yaml.safe_load(fh)

    required_fields = list(contract.keys())
    # Filtrer la clé technique "schema_version" qui n'est pas un champ de l'item
    required_fields = [
        f
        for f in required_fields
        if f not in ("schema_version",)
    ]
    for field in required_fields:
        if field not in item:
            raise ValueError(f"Champ obligatoire manquant : {field}")

    # Validation individuelle des champs

    # id : uniquement le format canonique UUID avec tirets (8-4-4-4-12)
    id_val = item["id"]
    if not re.fullmatch(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        id_val,
    ):
        raise ValueError("id invalide")

    # version
    if item["version"] != "1.0.0":
        raise ValueError("version invalide")

    # surface
    surfaces_ok = {"google_aio", "perplexity", "assistants_ia"}
    if item["surface"] not in surfaces_ok:
        raise ValueError("surface invalide")

    # pillar
    pillars_ok = {"seo", "ppc", "social"}
    if item["pillar"] not in pillars_ok:
        raise ValueError("pillar invalide")

    # type
    types_ok = {"post_social", "page_seo", "fiche_gbp", "article_blog"}
    if item["type"] not in types_ok:
        raise ValueError("type invalide")

    # title : chaîne non vide, max 100
    title = item["title"]
    if not isinstance(title, str) or not (1 <= len(title) <= 100):
        raise ValueError("title invalide")

    # body : chaîne non vide, max 5000
    body = item["body"]
    if not isinstance(body, str) or not (1 <= len(body) <= 5000):
        raise ValueError("body invalide")

    # timestamp : doit être interprétable comme date ISO 8601 avec timezone
    try:
        dt = datetime.fromisoformat(item["timestamp"])
        if dt.tzinfo is None:
            raise ValueError("horodatage sans timezone")
    except ValueError as e:
        raise ValueError("timestamp invalide") from e

    # approval_status
    status_ok = {"PROPOSE", "APPROVED", "REJECTED"}
    if item["approval_status"] not in status_ok:
        raise ValueError("approval_status invalide")

    # approver obligatoire si statut différent de PROPOSE
    if item["approval_status"] != "PROPOSE" and not item["approver"]:
        raise ValueError("approver invalide")

    # approval_timestamp : si non vide, mêmes exigences que timestamp
    approval_ts = item.get("approval_timestamp")
    if approval_ts is not None and approval_ts != "":
        try:
            dt = datetime.fromisoformat(approval_ts)
            if dt.tzinfo is None:
                raise ValueError("horodatage sans timezone")
        except ValueError as e:
            raise ValueError("approval_timestamp invalide") from e

    # tactics_applied : liste de dicts avec les clés tactique, statut, source
    tactics = item["tactics_applied"]
    if not isinstance(tactics, list):
        raise ValueError("tactics_applied invalide")
    for entry in tactics:
        if not isinstance(entry, dict):
            raise ValueError("tactics_applied element must be dict")
        if "tactique" not in entry:
            raise ValueError("tactique manquant dans tactics_applied")
        if "statut" not in entry:
            raise ValueError("statut manquant dans tactics_applied")
        if "source" not in entry:
            raise ValueError("source manquant dans tactics_applied")

        # Règle 7 : les trois valeurs doivent être des str non vides
        if not isinstance(entry["tactique"], str) or entry["tactique"] == "":
            raise ValueError(
                "tactique dans tactics_applied doit être une chaîne non vide"
            )
        if not isinstance(entry["statut"], str) or entry["statut"] == "":
            raise ValueError(
                "statut dans tactics_applied doit être une chaîne non vide"
            )
        if not isinstance(entry["source"], str) or entry["source"] == "":
            raise ValueError(
                "source dans tactics_applied doit être une chaîne non vide"
            )

    return True
