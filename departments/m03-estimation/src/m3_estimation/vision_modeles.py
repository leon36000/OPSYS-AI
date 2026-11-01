"""Registre des modèles de vision (M3.3, M3.5) : lecture du registre de fournisseurs de la plateforme, capacité «
vision ».

Réutilise ``opsys.fournisseurs`` (catalogue, politique de licence, configuration et activation par un administrateur)
: rien n'est recréé. Ce module ne télécharge AUCUN poids, n'installe rien et ne branche aucun détecteur : il dit
seulement ce que le registre sait, avec les drapeaux de licence, et conclut honnêtement.

STATUT GLOBAL. « ``contrat_pret_aucun_modele_qualifie`` » tant qu'aucun fournisseur de la capacité ``vision`` n'est à
  la fois
``qualifie`` (mesure sur de vraies photos consenties, annotées par des personnes : ce que le harnais synthétique ne
peut pas faire), ACTIF et conforme à la politique de licence du client. Aujourd'hui, tous sont ``a_mesurer`` et leur
licence est ``a_lire`` : aucun n'est activable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

from opsys.fournisseurs import registre

__all__ = ["STATUT_AUCUN_QUALIFIE", "STATUT_DISPONIBLE", "modeles_qualifies", "synthese", "vues"]

STATUT_AUCUN_QUALIFIE = "contrat_pret_aucun_modele_qualifie"
STATUT_DISPONIBLE = "modele_qualifie_actif"


def vues(cnx: Connection) -> list[dict[str, Any]]:
    """Les fournisseurs de capacité ``vision`` (catalogue + configurés), avec leur évaluation de licence."""
    return registre.lister(cnx, "vision")


def modeles_qualifies(liste: list[dict[str, Any]]) -> frozenset[str]:
    """Identifiants à la fois qualifiés, ACTIFS et conformes à la politique de licence : seuls ceux-là traitent une
    photo réelle."""
    return frozenset(
        v["identifiant"]
        for v in liste
        if v["actif"] and v["qualification"] == "qualifie" and v["politique"]["conforme"]
    )


def synthese(liste: list[dict[str, Any]]) -> dict[str, Any]:
    modeles = []
    for v in liste:
        licence = v["licence"]
        modeles.append(
            {
                "identifiant": v["identifiant"],
                "modele": v["modele"],
                "statut_catalogue": v["statut_catalogue"],
                "qualification": v["qualification"],
                "configure": v["configure"],
                "actif": v["actif"],
                "licence": {
                    "code": licence["code"],
                    "poids": licence["poids"],
                    "usage_commercial": licence["usage_commercial"],
                    "verification": licence["verification"],
                    "source": licence["source"],
                },
                "conforme_a_la_politique": v["politique"]["conforme"],
                "refus_de_licence": [r["code"] for r in v["politique"]["refus"]],
                "poids_fournis_par_opsys": False,
            }
        )
    qualifies = modeles_qualifies(liste)
    return {
        "statut": STATUT_DISPONIBLE if qualifies else STATUT_AUCUN_QUALIFIE,
        "modeles_qualifies_actifs": sorted(qualifies),
        "modeles": modeles,
        "mise_en_garde": (
            "Aucun poids n'est téléchargé ni fourni. Le harnais synthétique ne qualifie jamais un modèle "
            ": la "
            "qualification exige des photos réelles consenties et une politique photos validée."
        ),
    }
