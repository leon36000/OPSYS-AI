import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent  # src/workflows
_SRC = _HERE.parent  # src

_content_path = str(_SRC / "content")
_social_path = str(_SRC / "social")
if _content_path not in sys.path:
    sys.path.insert(0, _content_path)
if _social_path not in sys.path:
    sys.path.insert(0, _social_path)

import yaml
from factory import build_content_item
import approval
from datetime import date

__all__ = ["planifier_campagne_saisonniere"]


def _charger_brand():
    """Charge le brand RÉEL depuis src/brand/profile.yaml."""
    brand_path = _SRC / "brand" / "profile.yaml"
    with open(brand_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _charger_calendrier(chemin: str) -> dict:
    with open(chemin, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("calendrier invalide : clé 'fenetres_marketing' manquante")
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"schema_version invalide : {schema_version} (attendu : 1)")
    if "fenetres_marketing" not in data:
        raise ValueError("calendrier invalide : clé 'fenetres_marketing' manquante")
    return data


def _fenetres_actives(calendrier: dict, mois_ref: int) -> list:
    fenetres = calendrier["fenetres_marketing"]
    actives = []
    for fw in fenetres:
        debut = fw["mois_debut"]
        fin = fw["mois_fin"]
        if debut <= fin:
            if debut <= mois_ref <= fin:
                actives.append(fw)
        else:
            if mois_ref >= debut or mois_ref <= fin:
                actives.append(fw)
    actives.sort(key=lambda f: f["id"])
    return actives


def _construire_sujet(fenetre: dict, theme: str) -> dict:
    nom = fenetre["nom"]
    titre = f"{nom} — {theme}"
    description = f"Campagne saisonnière pour le thème « {theme} » de la fenêtre « {nom} »."
    # mots clés normalisés minuscules sans ponctuation
    trans = str.maketrans('', '', '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~ \t\n\r\f\v')
    mots_cles = [mot.translate(trans).lower() for mot in (nom, theme)]
    return {"titre": titre, "description": description, "mots_cles": mots_cles}


def _proposer_item(brand: dict, fenetre: dict, theme: str, timestamp: str) -> dict:
    sujet = _construire_sujet(fenetre, theme)
    content_item = build_content_item(
        brand,
        surface="google_aio",
        type="post_social",
        sujet=sujet,
        timestamp=timestamp,
    )
    # C'est le CONTENT-ITEM (porteur de l'id) qui entre en file 0-6 — pas le wrapper.
    content_item = approval.propose(content_item, "workflow-campagne-saisonniere", timestamp)
    return {
        "content_item": content_item,
        "fenetre_id": fenetre["id"],
        "theme_source": theme,
        "statut": "proposed",
    }


def planifier_campagne_saisonniere(date_reference: str, chemin_calendrier: str) -> dict:
    # mois de la date de référence
    d = date.fromisoformat(date_reference.split("T")[0])
    mois_ref = d.month

    brand = _charger_brand()
    calendrier = _charger_calendrier(chemin_calendrier)
    fenetres = _fenetres_actives(calendrier, mois_ref)

    items = []
    for fw in fenetres:
        for theme in fw["themes"]:
            items.append(_proposer_item(brand, fw, theme, date_reference))

    # tri déterministe par (fenetre_id, theme_source)
    items.sort(key=lambda it: (it["fenetre_id"], it["theme_source"]))

    return {
        "date_reference": date_reference,
        "fenetres_actives": fenetres,
        "items_proposes": items,
        "compteurs": {
            "fenetres_actives": len(fenetres),
            "items_proposes": len(items),
            "themes_couverts": len(items),
        },
    }
