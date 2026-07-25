import hashlib
import json
import string
import uuid
from pathlib import Path
import yaml

# Import plat du module validation situé dans le même dossier (ajouté au sys.path par les tests)
import validation


# Constante des surfaces autorisées
SURFACES_AUTORISEES = {"google_aio", "perplexity", "assistants_ia"}

# Constante des types autorisés
TYPES_AUTORISES = {"post_social", "page_seo", "fiche_gbp", "article_blog"}

# Variables de gabarit autorisées
VARIABLES_GABARIT_AUTORISEES = {
    "brand_name",
    "brand_tagline",
    "brand_tone",
    "brand_langue",
    "sujet_titre",
    "sujet_description",
    "sujet_mots_cles",
    "tactiques",
}


def _extraire_placeholders(template_str: str) -> set:
    """Extrait les placeholders {nom} d'une chaîne de gabarit Python."""
    placeholders = set()
    for _, field_name, _, _ in string.Formatter().parse(template_str):
        if field_name is not None:
            placeholders.add(field_name)
    return placeholders


def _verifier_gabarit(template: dict) -> None:
    """Vérifie que tous les placeholders du gabarit sont autorisés."""
    for cle in ("title_template", "body_template"):
        template_str = template.get(cle, "")
        placeholders = _extraire_placeholders(template_str)
        inconnus = placeholders - VARIABLES_GABARIT_AUTORISEES
        if inconnus:
            raise ValueError(
                f"variable de gabarit non autorisée : {', '.join(sorted(inconnus))}"
            )


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
    # Pré-validation de surface et type (avant toute lecture de fichier)
    if surface not in SURFACES_AUTORISEES:
        raise ValueError(
            f"surface invalide : '{surface}' "
            f"(autorisées : {', '.join(sorted(SURFACES_AUTORISEES))})"
        )
    if type not in TYPES_AUTORISES:
        raise ValueError(
            f"type invalide : '{type}' "
            f"(autorisés : {', '.join(sorted(TYPES_AUTORISES))})"
        )

    base_dir = Path(__file__).resolve().parents[2]

    # Chemins des contrats/fichiers de connaissance
    brand_contract_path = base_dir / "contracts" / "brand-contract.v1.yaml"
    seo_knowledge_path = base_dir / "docs" / "seo-knowledge.v1.yaml"
    templates_dir = Path(__file__).resolve().parent / "templates"

    # Lecture des fichiers avec gestion FileNotFoundError → ValueError
    try:
        brand_ref = hashlib.sha256(
            brand_contract_path.read_bytes()
        ).hexdigest()
    except FileNotFoundError as e:
        raise ValueError(
            f"fichier brand-contract.v1.yaml introuvable : {brand_contract_path}"
        ) from e

    try:
        seo_knowledge_ref = hashlib.sha256(
            seo_knowledge_path.read_bytes()
        ).hexdigest()
    except FileNotFoundError as e:
        raise ValueError(
            f"fichier seo-knowledge.v1.yaml introuvable : {seo_knowledge_path}"
        ) from e

    # Chargement du seo-knowledge pour extraire les tactiques de la surface
    try:
        with open(seo_knowledge_path, encoding="utf-8") as fh:
            seo_knowledge = yaml.safe_load(fh)
    except FileNotFoundError as e:
        raise ValueError(
            f"fichier seo-knowledge.v1.yaml introuvable : {seo_knowledge_path}"
        ) from e

    surface_tactics = []
    surfaces = seo_knowledge.get("surfaces", {})
    if surface in surfaces:
        for t in surfaces[surface].get("tactiques", []):
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
        template = {
            "title_template": "{brand_name} - {sujet_titre}",
            "body_template": "{brand_tagline}\n{sujet_description}",
        }

    # Vérification anti-dérive des gabarits
    _verifier_gabarit(template)

    # Construction du contexte enrichi avec toutes les variables autorisées
    tactiques_noms = ", ".join(
        t["tactique"] for t in surface_tactics
    )
    context = {
        "brand_name": brand.get("name", ""),
        "brand_tagline": brand.get("tagline", ""),
        "brand_tone": brand.get("tone", ""),
        "brand_langue": brand.get("langue", ""),
        "sujet_titre": sujet.get("titre", ""),
        "sujet_description": sujet.get("description", ""),
        "sujet_mots_cles": ", ".join(sujet.get("mots_cles", [])),
        "tactiques": tactiques_noms,
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
