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
from postiz_adapter import PostizAdapter, SocialPost, Canal, NotAutorise, AdapterDisabled

__all__ = ["orchestrer_chantier_vers_social"]


def _charger_brand():
    """Charge le brand RÉEL depuis src/brand/profile.yaml."""
    brand_path = _SRC / "brand" / "profile.yaml"
    with open(brand_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def orchestrer_chantier_vers_social(
    chemin_chantier: str,
    timestamp: str,
    acteur_propose: str,
    acteur_approuve: str,
    adapter_config: dict | None = None,
) -> dict:
    """Point d'entrée unique du workflow chantier -> contenu social.

    Args:
        chemin_chantier: Chemin vers le fichier chantier.yaml.
        timestamp: Horodatage ISO-8601 fourni par l'appelant.
        acteur_propose: Identifiant de l'acteur proposant le contenu.
        acteur_approuve: Identifiant de l'acteur approuvant le contenu (doit être différent).
        adapter_config: Configuration pour PostizAdapter (défaut: {"enabled": True, "dry_run": False}).

    Returns:
        Un dictionnaire contenant chantier_slug, etapes et metriques.

    Raises:
        ValueError: Si la fixture n'a pas ``fictif: true``.
    """
    # ------------------------------------------------------------------
    # 1. Chargement et validation de la fixture
    # ------------------------------------------------------------------
    chemin = Path(chemin_chantier)
    with open(chemin, "r", encoding="utf-8") as f:
        chantier = yaml.safe_load(f)

    if not chantier.get("fictif"):
        raise ValueError("La fixture doit avoir 'fictif: true'")

    # Validation de l'énumération type_travaux
    types_valides = {"renovation_totale", "extension", "ravalement", "isolation_thermique"}
    type_travaux = chantier.get("type_travaux")
    if type_travaux not in types_valides:
        raise ValueError(
            f"type_travaux invalide : {type_travaux!r} "
            f"(attendus : {', '.join(sorted(types_valides))})"
        )

    slug = chemin.parent.name  # slug du chantier (ex: residence-quebec-2026)

    # Charger le brand une fois pour toutes
    brand = _charger_brand()

    # Initialisation des métriques et de la liste d'étapes
    metriques = {
        "chantiers_traites": 0,
        "contenus_proposes": 0,
        "publications_bloquees_gated": 0,
    }
    etapes: list[dict] = []

    # ------------------------------------------------------------------
    # 2. Étape charge (le chargement a réussi, on trace l'étape)
    # ------------------------------------------------------------------
    etapes.append(
        {
            "nom": "charge",
            "statut": "SUCCES",
            "detail": "Chantier chargé avec succès",
        }
    )

    # ------------------------------------------------------------------
    # 3. Étape compose
    # ------------------------------------------------------------------
    try:
        sujet = {
            "titre": f"{chantier['type_travaux'].replace('_', ' ').capitalize()} à {chantier['ville']}",
            "description": chantier["description_factuelle"],
            "mots_cles": [chantier["type_travaux"], chantier["ville"]],
        }
        item = build_content_item(
            brand,
            surface="google_aio",
            type="post_social",
            sujet=sujet,
            timestamp=timestamp,
        )
        etapes.append({"nom": "compose", "statut": "SUCCES", "detail": item})
    except Exception as e:
        etapes.append({"nom": "compose", "statut": "ECHEC", "detail": str(e)})
        metriques["chantiers_traites"] = 1
        return {
            "chantier_slug": slug,
            "etapes": etapes,
            "metriques": metriques,
        }

    # ------------------------------------------------------------------
    # 4. Étape propose
    # ------------------------------------------------------------------
    try:
        item = approval.propose(item, acteur_propose, timestamp)
        etapes.append(
            {"nom": "propose", "statut": "SUCCES", "detail": item}
        )
        metriques["contenus_proposes"] = 1
    except Exception as e:
        etapes.append({"nom": "propose", "statut": "ECHEC", "detail": str(e)})
        metriques["chantiers_traites"] = 1
        return {
            "chantier_slug": slug,
            "etapes": etapes,
            "metriques": metriques,
        }

    # ------------------------------------------------------------------
    # 5. Étape approuve
    # ------------------------------------------------------------------
    try:
        item = approval.approve(item, acteur_approuve, timestamp)
        etapes.append(
            {"nom": "approuve", "statut": "SUCCES", "detail": item}
        )
    except Exception as e:
        etapes.append({"nom": "approuve", "statut": "ECHEC", "detail": str(e)})
        metriques["chantiers_traites"] = 1
        return {
            "chantier_slug": slug,
            "etapes": etapes,
            "metriques": metriques,
        }

    # ------------------------------------------------------------------
    # 6. Étape publication (gating)
    # ------------------------------------------------------------------
    if adapter_config is None:
        adapter_config = {"enabled": True, "dry_run": False}

    try:
        adapter = PostizAdapter(adapter_config)
        post = SocialPost(
            canal=Canal.GBP.value,
            texte=item["body"],
            media=chantier.get("photos", []),
            niveau_validation=1,
        )
        pub_result = adapter.publier(post)
        etapes.append(
            {"nom": "publication", "statut": "SUCCES", "detail": pub_result}
        )
    except NotAutorise as e:
        etapes.append(
            {
                "nom": "publication",
                "statut": "SUCCES",
                "detail": f"NotAutorise capturé : {e}",
            }
        )
        metriques["publications_bloquees_gated"] = 1
    except AdapterDisabled as e:
        etapes.append(
            {
                "nom": "publication",
                "statut": "ECHEC",
                "detail": f"AdapterDisabled : {e}",
            }
        )
        # publications_bloquees_gated reste à 0
    except Exception as e:
        etapes.append(
            {
                "nom": "publication",
                "statut": "ECHEC",
                "detail": str(e),
            }
        )
        # publications_bloquees_gated reste à 0

    metriques["chantiers_traites"] = 1
    return {
        "chantier_slug": slug,
        "etapes": etapes,
        "metriques": metriques,
    }
