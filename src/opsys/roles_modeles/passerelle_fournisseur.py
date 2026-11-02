"""Fournisseurs du registre qui représentent la passerelle LiteLLM (un par alias de modèle).

La passerelle n'est pas un modèle : elle sert des modèles d'amont (OpenRouter, clés directes) sous des ALIAS. Pour
que la
politique de licence, l'EFVP (Loi 25) et l'empreinte d'espace vectoriel des embeddings suivent le modèle réellement
appelé, chaque alias est déclaré comme un fournisseur distinct `<capacité>.passerelle.<alias>`, de point d'accès
`passerelle:litellm` (l'URL vient du réglage `passerelle`, jamais d'une valeur copiée) et de modèle = l'alias.

Licence déclarée (lue le 2026-11-02 dans le fichier LICENSE de BerriAI/litellm) : le cœur est MIT, le dossier
`enterprise/` relève d'une licence distincte et n'est ni utilisé ni redistribué ici. Les conditions du MODÈLE d'amont
sont celles du contrat du client avec son fournisseur (OpenRouter, Anthropic…) : `sur_contrat`, donc une référence de
contrat est exigée à l'activation ; le droit de service à des tiers n'est pas établi (`incertain`). Un modèle local
(vLLM, Ollama) se choisit dans le catalogue du registre : sa licence de poids est celle du modèle, pas celle de LiteLLM.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Connection

from ..fournisseurs import registre
from ..fournisseurs.modele import Licence
from . import codes
from . import roles as lex
from .codes import ModelesErreur

POINT_ACCES = "passerelle:litellm"
SOURCE_LICENCE = (
    "github.com/BerriAI/litellm/LICENSE (lu le 2026-11-02) ; conditions du modèle d'amont = contrat du client"
)
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def licence_passerelle() -> Licence:
    return Licence(
        code="MIT (cœur LiteLLM ; dossier enterprise/ exclu)",
        poids=None,
        usage_commercial="sur_contrat",
        service_tiers="incertain",
        integration="service_separe",
        verification="verifiee",
        source=SOURCE_LICENCE,
        note="Les conditions d'usage du modèle servi sont celles du contrat du client avec son fournisseur d'amont.",
    )


def identifiant(role: str, alias: str) -> str:
    capacite = lex.CAPACITE_DU_ROLE[role]
    slug = re.sub(r"[^a-z0-9._-]+", "-", alias.lower()).strip("-.")[:50]
    return f"{capacite}.passerelle.{slug}"


def declarer(
    cnx: Connection,
    *,
    acteur: str,
    role: str,
    alias: str,
    secret_cle: str,
    efvp_ref: str | None,
    contrat_ref: str | None,
    residence: str = "inconnue",
) -> dict[str, Any]:
    """Déclare (ou retrouve) le fournisseur d'un alias de passerelle, puis tente de l'activer sous la politique.
    Rend `{identifiant, active, refus}` : un refus est rendu tel quel, rien d'autre n'est activé à la place."""
    lex.verifier_role(role)
    if not isinstance(alias, str) or not _ALIAS.fullmatch(alias):
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "alias de passerelle invalide", 422)
    ident = identifiant(role, alias)
    try:
        vue = registre.vue(cnx, ident)
        revision = vue["revision"] if vue["configure"] else 0
    except registre.RegistreErreur:
        vue, revision = None, 0
    modifications = {
        "efvp_ref": efvp_ref or "",
        "contrat_ref": contrat_ref or "",
        "residence_donnees": residence,
        "reference_secret": f"coffre:{secret_cle}",
    }
    try:
        if vue is None:
            declaration = {
                "capacite": lex.CAPACITE_DU_ROLE[role],
                "mode": "api",
                "modele": alias,
                "point_acces": POINT_ACCES,
                "licence": licence_passerelle().vers_json(),
                "residence_donnees": residence,
                "efvp_ref": efvp_ref or None,
                "contrat_ref": contrat_ref or None,
                "reference_secret": f"coffre:{secret_cle}",
                "note": f"Alias « {alias} » servi par la passerelle LiteLLM (rôle {role}).",
            }
            registre.configurer(cnx, acteur=acteur, identifiant=ident, declaration=declaration)
        else:
            registre.configurer(
                cnx, acteur=acteur, identifiant=ident, modifications=modifications, revision_attendue=revision
            )
        decision = registre.activer(cnx, acteur=acteur, identifiant=ident)
    except registre.RegistreErreur as exc:
        raise ModelesErreur(
            codes.FOURNISSEUR_REFUSE, f"{exc.code} : {exc.detail}", exc.statut_http, exc.codes
        ) from None
    return {"identifiant": ident, "active": decision.conforme, "refus": [r.code for r in decision.refus]}
