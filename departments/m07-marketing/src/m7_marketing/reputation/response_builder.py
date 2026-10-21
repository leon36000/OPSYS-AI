"""Construction de réponses PROPOSÉES à partir des gabarits Brand Core.

Doctrine :
  - Statut toujours PROPOSE — JAMAIS auto-publié (D-043, acceptance M7-S009).
  - Niveau de validation dans la file 0-6.
  - Gabarits déterministes (texte fixe + variable {brand_name}).
  - Zéro réseau.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import yaml

from . import classifier as _classifier

# ---------------------------------------------------------------------------
# Gabarits par catégorie (Brand Core — ton professionnel, signature nom marque)
# ---------------------------------------------------------------------------

_GABARITS: dict[str, str] = {
    "litige": (
        "Bonjour,\n\n"
        "Nous avons bien reçu votre signalement et le traitons avec la plus grande attention. "
        "Notre équipe vous contactera dans les meilleurs délais pour résoudre cette situation.\n\n"
        "Cordialement,\n{brand_name}"
    ),
    "urgence": (
        "Bonjour,\n\n"
        "Nous prenons note de votre retour et nous nous excusons sincèrement pour les désagréments "
        "rencontrés. Votre demande est traitée en priorité.\n\n"
        "Cordialement,\n{brand_name}"
    ),
    "eloge": (
        "Bonjour,\n\n"
        "Merci beaucoup pour votre retour positif — cela nous touche et motive toute notre équipe. "
        "Nous espérons avoir le plaisir de vous accueillir à nouveau bientôt.\n\n"
        "Cordialement,\n{brand_name}"
    ),
    "neutre": (
        "Bonjour,\n\n"
        "Merci pour votre retour. Nous en prenons note et restons à votre disposition "
        "pour tout complément d'information.\n\n"
        "Cordialement,\n{brand_name}"
    ),
}

# Niveau de validation par défaut dans la file 0-6 (T2 : validation humaine requise)
_NIVEAU_VALIDATION_DEFAUT: int = 1

# Chemin canonique vers le profil Brand Core
# parents[0]=reputation/ parents[1]=m7_marketing/ (paquet parent commun)
_BRAND_PROFILE_DEFAULT = (
    Path(__file__).resolve().parents[1] / "brand" / "profile.yaml"
)


def charger_brand(chemin: Path | None = None) -> dict:
    """Charge le profil Brand Core (lecture seule).

    Paramètres
    ----------
    chemin : Path optionnel — surcharge du chemin en test.

    Retourne
    --------
    dict : contenu du profil YAML (name, tagline, tone, colors, langue, …).
    """
    path = Path(chemin) if chemin is not None else _BRAND_PROFILE_DEFAULT
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Profil brand invalide : {path}")
    return data


def construire_reponse(
    avis: dict,
    categorie: str,
    brand: dict,
    niveau_validation: int = _NIVEAU_VALIDATION_DEFAUT,
) -> dict:
    """Construit une réponse PROPOSÉE pour un avis.

    La réponse porte systématiquement ``approval_status = "PROPOSE"`` et
    n'est JAMAIS publiée automatiquement.

    Paramètres
    ----------
    avis             : dict de l'avis (doit porter ``id``).
    categorie        : 'litige' | 'urgence' | 'eloge' | 'neutre'.
    brand            : dict du profil Brand Core (doit porter ``name``).
    niveau_validation: int 0-6 (défaut 1 — validation humaine requise).

    Retourne
    --------
    dict avec les clés :
        id               : UUID déterministe (uuid5)
        avis_id          : identifiant de l'avis source
        categorie        : catégorie classifiée
        texte            : réponse formatée à partir du gabarit Brand Core
        brand_name       : nom de la marque utilisé dans la réponse
        approval_status  : "PROPOSE" (invariant — jamais modifié ici)
        niveau_validation: int 0-6

    Lève
    ----
    ValueError : si ``avis`` manque d'``id``, si ``categorie`` est inconnue,
                 ou si ``brand`` manque de ``name``.
    """
    avis_id = avis.get("id")
    if not avis_id:
        raise ValueError("L'avis doit porter un identifiant 'id'.")

    if categorie not in _classifier.CATEGORIES:
        raise ValueError(
            f"Catégorie inconnue : {categorie!r} (attendu : {sorted(_classifier.CATEGORIES)})"
        )

    brand_name = brand.get("name", "").strip()
    if not brand_name:
        raise ValueError("Le profil brand doit porter un champ 'name' non vide.")

    gabarit = _GABARITS[categorie]
    texte_reponse = gabarit.format(brand_name=brand_name)

    # Identifiant déterministe : uuid5 sur (avis_id, categorie)
    canonique = json.dumps(
        {"avis_id": avis_id, "categorie": categorie},
        sort_keys=True,
        ensure_ascii=False,
    )
    reponse_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonique))

    return {
        "id": reponse_id,
        "avis_id": avis_id,
        "categorie": categorie,
        "texte": texte_reponse,
        "brand_name": brand_name,
        "approval_status": "PROPOSE",  # invariant — JAMAIS auto-publié
        "niveau_validation": niveau_validation,
    }
