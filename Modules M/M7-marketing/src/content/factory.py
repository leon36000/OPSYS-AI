import hashlib
import json
import uuid
from pathlib import Path
import yaml

# Import plat du module validation situé dans le même dossier (ajouté au sys.path par les tests)
import validation


def build_content_item(
    brand: dict,
    surface: str,
    type: str,
    sujet: dict,
    timestamp: str,
) -> dict:
    """Construit un item de contenu conforme au contrat content-item.v1.

    Retourne un dict déterministe (mêmes paramètres -> même id et contenu).
    """
    base_dir = Path(__file__).resolve().parents[2]

    # Chemins des contrats/fichiers de connaissance
    brand_contract_path = base_dir / "contracts" / "brand-contract.v1.yaml"
    seo_knowledge_path = base_dir / "docs" / "seo-knowledge.v1.yaml"
    templates_dir = Path(__file__).resolve().parent / "templates"

    # Calcul des empreintes (brand_ref, seo_knowledge_ref)
    brand_ref = hashlib.sha256(
        brand_contract_path.read_bytes()
    ).hexdigest()
    seo_knowledge_ref = hashlib.sha256(
        seo_knowledge_path.read_bytes()
    ).hexdigest()

    # Chargement du seo-knowledge pour extraire les tactiques de la surface
    with open(seo_knowledge_path, encoding="utf-8") as fh:
        seo_knowledge = yaml.safe_load(fh)
    surface_tactics = []
    surfaces = seo_knowledge.get("surfaces", {})
    if surface in surfaces:
        for t in surfaces[surface].get("tactiques", []):
            # On copie uniquement les clés attendues
            surface_tactics.append(
                {
                    "tactique": t["tactique"],
                    "statut": t["statut"],
                    "source": t["source"],
                }
            )

    # Pillar déduit du type
    pillar_map = {
        "post_social": "social",
        "page_seo": "seo",
        "fiche_gbp": "seo",
        "article_blog": "seo",
    }
    pillar = pillar_map.get(type, "seo")

    # Chargement et application du template pour titre et corps
    template_file = templates_dir / f"{type}.yaml"
    if template_file.is_file():
        with open(template_file, encoding="utf-8") as fh:
            template = yaml.safe_load(fh)
    else:
        # Fallback minimal pour éviter de casser si le template n'existe pas
        template = {
            "title_template": "{brand_name} - {sujet_titre}",
            "body_template": "{brand_tagline}\n{sujet_description}",
        }

    context = {
        "brand_name": brand["name"],
        "brand_tagline": brand["tagline"],
        "sujet_titre": sujet["titre"],
        "sujet_description": sujet["description"],
        # Pas d'usage de tactiques ici pour rester dans l'esprit de la composition sans LLM
    }
    title = template["title_template"].format(**context)
    body = template["body_template"].format(**context)

    # ID déterministe
    canonique = json.dumps(
        {
            "brand": brand,
            "surface": surface,
            "type": type,
            "sujet": sujet,
            "timestamp": timestamp,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    item_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonique))

    item = {
        "id": item_id,
        "version": "1.0.0",
        "brand_ref": brand_ref,
        "seo_knowledge_ref": seo_knowledge_ref,
        "surface": surface,
        "pillar": pillar,
        "type": type,
        "title": title,
        "body": body,
        "tactics_applied": surface_tactics,
        "timestamp": timestamp,
        "approval_status": "PROPOSE",
        "approver": "",
        "approval_timestamp": "",
    }

    # Validation avant retour (fail-closed)
    validation.validate_content_item(item)
    return item
