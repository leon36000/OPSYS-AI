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


def _valider_brand_contre_contrat(brand: dict, contrat: dict) -> None:
    """le brand fourni est validé contre le SCHÉMA du contrat gelé (le contrat ne porte pas de
    valeurs) ; brand_ref trace le fichier de schéma qui a gouverné la validation"""
    # 1. Vérifier que le contrat définit bien profile_schema.required_fields
    try:
        required_fields = contrat["profile_schema"]["required_fields"]
    except (KeyError, TypeError):
        raise ValueError(
            "contrat brand-contract.v1.yaml invalide (profile_schema.required_fields absent)"
        )
    if not isinstance(required_fields, list):
        raise ValueError(
            "contrat brand-contract.v1.yaml invalide (profile_schema.required_fields absent)"
        )

    # 2. Valider chaque champ requis
    for field_def in required_fields:
        if not isinstance(field_def, dict) or "name" not in field_def:
            raise ValueError(
                "contrat brand-contract.v1.yaml invalide (entrée de required_fields sans 'name')"
            )

        field_name: str = field_def["name"]
        field_type: str = field_def.get("type", "")
        non_empty: bool = field_def.get("non_empty", False)
        items_type: str | None = field_def.get("items", None)
        min_items: int | None = field_def.get("min_items", None)

        # Présence de la clé dans brand
        if field_name not in brand:
            raise ValueError(f"champ requis manquant dans le brand : {field_name}")

        value = brand[field_name]

        # Validation selon le type
        if field_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"{field_name} doit être une chaîne de caractères")
            if non_empty and value.strip() == "":
                raise ValueError(f"{field_name} ne doit pas être vide")

        elif field_type == "array":
            if not isinstance(value, list):
                raise ValueError(f"{field_name} doit être une liste")
            if items_type == "string":
                for i, item in enumerate(value):
                    if not isinstance(item, str):
                        raise ValueError(
                            f"{field_name}[{i}] doit être une chaîne de caractères"
                        )
            if min_items is not None and len(value) < min_items:
                raise ValueError(
                    f"{field_name} doit contenir au moins {min_items} élément(s)"
                )

        # Les types de schéma inconnus sont ignorés (tolérance v1)


def build_content_item(
    brand: dict,
    surface: str,
    type: str,
    sujet: dict,
    timestamp: str,
) -> dict:
    """Construit un item de contenu conforme au contrat content-item.v1.

    Retourne un dict déterministe (mêmes paramètres -> même id et contenu).
    brand_ref trace le fichier contrat gelé du dépôt ; l'appelant fournit un
    brand issu de ce fichier.
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

    # Lecture unique du contrat de marque (bytes → hash + contenu)
    try:
        brand_bytes = brand_contract_path.read_bytes()
    except FileNotFoundError as e:
        raise ValueError(
            f"fichier brand-contract.v1.yaml introuvable : {brand_contract_path}"
        ) from e

    brand_ref = hashlib.sha256(brand_bytes).hexdigest()
    brand_contract = yaml.safe_load(brand_bytes.decode("utf-8"))

    # CORRECTIF R3.1 : le contrat gelé est un contrat de SCHÉMA — le brand fourni est
    # validé fail-closed contre profile_schema.required_fields (cf. _valider_brand_contre_contrat).
    _valider_brand_contre_contrat(brand, brand_contract)

    # Lecture unique du fichier seo-knowledge (bytes → hash + contenu)
    try:
        seo_bytes = seo_knowledge_path.read_bytes()
    except FileNotFoundError as e:
        raise ValueError(
            f"fichier seo-knowledge.v1.yaml introuvable : {seo_knowledge_path}"
        ) from e

    seo_knowledge_ref = hashlib.sha256(seo_bytes).hexdigest()
    seo_knowledge = yaml.safe_load(seo_bytes.decode("utf-8"))

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

    # Pillar déduit du type (type toujours valide grâce à la pré-validation)
    pillar_map = {
        "post_social": "social",
        "page_seo": "seo",
        "fiche_gbp": "seo",
        "article_blog": "seo",
    }
    pillar = pillar_map[type]

    # Chargement et application du template pour titre et corps
    template_file = templates_dir / f"{type}.yaml"
    if template_file.is_file():
        # CORRECTIF R3.2 : lecture uniforme via read_bytes()
        template_bytes = template_file.read_bytes()
        template = yaml.safe_load(template_bytes.decode("utf-8"))
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
