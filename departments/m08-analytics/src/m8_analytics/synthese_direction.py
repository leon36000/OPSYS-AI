"""Synthèse de direction de M8 : le score de santé ET les mesures du catalogue, en UNE lecture compacte pour M9
(Athéna).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge, aucun calcul. Il ne fait que PROJETER, dans une forme
fermée et bornée, ce que ``moteur_mesures`` / ``fraicheur_mesures`` (les mesures) et ``sante`` (le score) ont déjà
produit. La raison d'être : M9 lit ses producteurs par un port qui exige une identité d'admin ; les lectures
``m8_lire_mesures`` et ``m8_lire_sante_entreprise`` sont FERMÉES à toute identité (outils d'agent), donc inaccessibles
à ce port. Cette lecture dédiée n'ajoute aucun droit : elle expose seulement, à l'admin authentifié relu en base, ce
que ces deux outils exposent déjà aux agents de M8.

Ce qui est gardé : la valeur exacte (texte) ou ``None``, l'unité, la fraîcheur et l'âge, la version de définition, les
manques NOMMÉS (noms de champs du code, jamais le texte libre d'un autre département), le statut du score et ce qui
empêche de noter. Ce qui n'est PAS gardé : le détail libre d'un manque, la source en texte, le propriétaire, la
sensibilité, l'historique.

Un score ``determine`` dont les pondérations ne sont pas validées par le propriétaire reste une PROPOSITION : le
champ ``ponderations.validee`` le dit, et le consommateur ne peut pas le présenter comme établi.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "opsys.m8.synthese_direction/v1"
MENTION = "Indicateur préparatoire. À valider auprès d'un comptable (CPA) / professionnel qualifié."
_MESURES_MAX = 40


def projeter_sante(sante: dict[str, Any]) -> dict[str, Any]:
    """Le jugement de ``sante.evaluer`` sans texte libre : statut, score, composantes, manques nommés, pondérations."""
    ponderations = sante["ponderations"]
    return {
        "statut": sante["statut"],
        "score": sante["score"],
        "ponderations": {
            "validee": bool(ponderations["validee"]),
            "declaree_par": ponderations["declaree_par"],
            "validee_par": ponderations["validee_par"],
        },
        "version_definition": sante["version_definition"],
        "composantes": [
            {
                "id": c["id"],
                "libelle": c["libelle"],
                "poids": c["poids"],
                "statut": c["statut"],
                "score": c["score"],
            }
            for c in sante["composantes"]
        ],
        "manques": [
            {"composante": m["composante"], "metric_id": m["metric_id"], "raison": m["raison"]}
            for m in sante["manques"]
        ],
        "bornes_invalides": len(sante["configuration"]["bornes_invalides"]),
    }


def projeter_mesures(mesures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Les mesures lues AVEC leur fraîcheur, projetées : jamais une valeur sans son statut ni son âge."""
    if len(mesures) > _MESURES_MAX:
        raise ValueError("REJ-SYNTHESE-TROP-DE-MESURES : le catalogue fermé dépasse la borne de la synthèse")
    return [
        {
            "metric_id": m["metric_id"],
            "domaine": m["domaine"],
            "unite": m["unite"],
            "statut": m["statut"],
            "valeur": m["valeur"],
            "fraicheur": m["fraicheur"]["statut"],
            "age_s": m["fraicheur"]["age_s"],
            "fenetre_s": m["fraicheur"]["fenetre_s"],
            "dernier_fait_le": m["dernier_fait_le"],
            "version_definition": m["version_definition"][:16],
            "manque": [x["champ"] for x in m["manque"]],
        }
        for m in mesures
    ]


def construire(
    *,
    maintenant: str,
    mesures: list[dict[str, Any]],
    sante: dict[str, Any],
    version_catalogue: str,
    empreinte_registres: str,
    avertissements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """La synthèse complète. ``avertissements`` : les réglages de fraîcheur refusés ou ignorés (dits, jamais
    corrigés)."""
    return {
        "type": "SYNTHESE_DIRECTION",
        "schema": SCHEMA,
        "maintenant": maintenant,
        "version_catalogue": version_catalogue,
        "empreinte_registres": empreinte_registres,
        "sante": projeter_sante(sante),
        "mesures": projeter_mesures(mesures),
        "avertissements": dict(avertissements or {}),
        "mention": MENTION,
    }
