"""Paquet manuel d'un contenu approuvé (PLAN T4.17, M7.2 : « paquet manuel : texte, mots-clics, média, heure,
instructions »).

Les API officielles de publication sont des portes fermées (DEFINITION-PRODUIT §10 : approbations Meta, TikTok,
YouTube, Google Business Profile ; audit M7 §2.7 : le paquet manuel est le chemin principal). Le paquet est ce
que le propriétaire copie et publie LUI-MÊME : M7 ne publie jamais, n'appelle aucune API de plateforme, ne
programme rien.

Ce que le paquet dit, sans jamais le présenter comme plus sûr qu'il n'est :
  - Les médias sont les références des photos du WCT, jamais des fichiers. Aucun média flouté n'existe dans
    ce dépôt : le floutage de T4.3 rend un RAPPORT (zones détectées et floutées), pas un fichier, et le
    détecteur réel de visages et de plaques n'est pas installé (OpenCV absent, politique « photos »). Tout
    média est donc « à flouter à la main » ; le rapport de T4.3, s'il existe pour cette référence, est joint
    à titre d'information, avec la réserve que l'absence de détection ne prouve rien.
  - L'heure suggérée vient du profil de marque (`heures_publication`, décision du client) ; sans elle, le
    paquet le dit et ne propose aucune heure : aucun « meilleur moment » n'est inventé.
  - La demande de témoignage est un message privé au client : elle ne s'envoie que si le client a consenti à
    être contacté (`consentement_demande_avis` prouvé), et le paquet dit ce qu'il en est.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from ..reputation.demande_avis import CLES_PREUVE
from . import plateformes, retrait, verdicts

STATUT_MEDIA_A_FLOUTER = "a_flouter_a_la_main"
PUBLICATION_MANUELLE = "manuelle : M7 ne publie jamais, le propriétaire publie lui-même"

_HEURE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def contact_client(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Peut-on écrire au client ? Seulement s'il a consenti à être contacté pour un avis
    (`consentement_demande_avis`, DISTINCT de `consentement_marketing`), preuve à l'appui (Loi 25)."""
    prouve = all(isinstance(charge.get(cle), str) and charge[cle].strip() for cle in CLES_PREUVE)
    if charge.get("consentement_demande_avis") is True and prouve:
        return {"autorise": True, "consentement": {
            "recueilli_par": charge["consentement_recueilli_par"],
            "recueilli_le": charge["consentement_recueilli_le"],
            "version_texte": charge["consentement_version_texte"],
        }}
    return {
        "autorise": False,
        "detail": "le client n'a pas consenti à être contacté (consentement_demande_avis absent ou sans preuve) : "
                  "ne lui envoie pas ce message",
    }


def heure_suggeree(profil: Mapping[str, Any], plateforme_code: str) -> dict[str, str] | None:
    """L'heure locale que le profil de marque déclare pour cette plateforme, ou `None` (jamais inventée)."""
    heures = profil.get("heures_publication")
    valeur = heures.get(plateforme_code) if isinstance(heures, dict) else None
    if isinstance(valeur, str) and _HEURE.fullmatch(valeur):
        return {"heure_locale": valeur, "source": "profil de marque (heures_publication)"}
    return None


def medias_du_contenu(
    contenu: Mapping[str, Any], brouillons_contenu_public: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Un média par photo du WCT : sa référence, « à flouter à la main », et le rapport de floutage de T4.3
    quand il existe pour cette référence (information, jamais une garantie)."""
    rapports: dict[str, Mapping[str, Any]] = {}
    for brouillon in brouillons_contenu_public:
        if brouillon.get("wct_id") == contenu["wct_id"]:
            for photo in brouillon.get("photos", []):
                rapports[photo["reference"]] = photo
    medias = []
    for reference in contenu["photos"]:
        rapport = rapports.get(reference)
        medias.append({
            "reference": reference,
            "statut": STATUT_MEDIA_A_FLOUTER,
            "instruction": (
                "Photo originale : flouter à la main les visages, plaques d'immatriculation et numéros civiques "
                "avant toute publication. Aucun média flouté n'a été produit."
            ),
            "rapport_detecteur": None if rapport is None else {
                "zones_detectees": len(rapport["detections"]),
                "zones_floutees": sum(1 for d in rapport["detections"] if d["floutee"]),
                "revue_humaine_requise": rapport["revue_humaine_requise"],
                "reserve": "l'absence de détection ne prouve pas l'absence de visage ou de plaque",
            },
        })
    return medias


def composer_paquet(
    contenu: Mapping[str, Any], charge: Mapping[str, Any], brouillons_contenu_public: Iterable[Mapping[str, Any]],
    profil: Mapping[str, Any],
) -> dict[str, Any]:
    """Le paquet manuel d'un contenu APPROUVÉ (`contenu` : la vue de `registre.vue`, avec sa décision)."""
    plateforme = plateformes.plateforme(contenu["plateforme"])
    decision = contenu["decision"]
    copie = [contenu["texte"]]
    if plateforme.lien_dans_le_texte and contenu["lien_utm"]:
        copie.append(contenu["lien_utm"])
    if contenu["mots_clics"]:
        copie.append(" ".join(contenu["mots_clics"]))
    heure = heure_suggeree(profil, plateforme.code) if plateforme.public else None
    instructions = list(plateforme.instructions)
    if plateforme.public:
        instructions.append(plateformes.VERIFICATION_AVANT_PUBLICATION)
    paquet: dict[str, Any] = {
        "contenu_id": contenu["contenu_id"],
        "plateforme": plateforme.code,
        "libelle": plateforme.libelle,
        "public": plateforme.public,
        "texte": contenu["texte"],
        "mots_clics": contenu["mots_clics"],
        "lien_utm": contenu["lien_utm"],
        "texte_a_copier": "\n\n".join(copie),
        "medias": medias_du_contenu(contenu, brouillons_contenu_public) if plateforme.public else [],
        "heure_suggeree": heure,
        "a_configurer": [] if heure is not None or not plateforme.public else [
            f"heures_publication.{plateforme.code} dans le profil de marque : aucune heure suggérée"
        ],
        "instructions": instructions,
        "avertissements": list(contenu["avertissements"]),
        "approuve_par": decision["par"],
        "approuve_le": decision["horodatage"],
        "publication": PUBLICATION_MANUELLE,
    }
    if not plateforme.public:
        paquet["contact_client"] = contact_client(charge)
    return paquet


def construire_export(
    contenu: Mapping[str, Any], exporte_par: str, horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(maillon d'export, None)` ou `(None, verdict)` : la trace qu'un paquet a été remis au propriétaire
    (l'étape « mesure » de M7.3 sait ainsi ce qui est sorti). Un export par contenu, jamais un doublon."""
    if not retrait.horodatage_valide(horodatage):
        return None, verdicts.verdict(verdicts.REJ_HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis")
    canonique = json.dumps({"contenu_id": contenu["contenu_id"], "type": "export_paquet"}, sort_keys=True)
    return {
        "export_id": str(uuid.uuid5(uuid.NAMESPACE_URL, canonique)),
        "contenu_id": contenu["contenu_id"],
        "wct_id": contenu["wct_id"],
        "plateforme": contenu["plateforme"],
        "empreinte_texte": contenu["empreinte_texte"],
        "exporte_par": exporte_par,
        "horodatage": horodatage,
    }, None
