"""Nexora Creative : fournisseur EXTERNE optionnel (outil interne de Nathan), par API ou MCP, derrière un PORT.

R5 §7.3 (contrat générique ; AUCUNE information privée sur Nexora n'a été consultée) :
  - Option A, REST/OpenAPI : `GET /v1/capabilities`, `POST /v1/jobs` (idempotent), `GET /v1/jobs/{id}`,
    `GET /v1/jobs/{id}/artifacts` ; jeton par locataire dans le coffre ; webhooks signés HMAC (non utilisés ici).
  - Option B, MCP : `generate_image`, `edit_image`, `render_video`, `vectorize`, `list_models`, `get_job`. En
  production on
    passe par la file de travaux d'OPSYS (quotas, journal, contrôle qualité, licence) plutôt que d'appeler l'outil MCP à
    la main.

Ce module ne contient QUE le contrat : `PortNexora` (le transport, REST ou MCP, à écrire), `NexoraDouble` (test, aucun
réseau), `GenerateurNexora` (adaptateur qui fait de Nexora un `GenerateurImage` du registre) et la conversion des
capacités annoncées en DÉCLARATIONS de fournisseur. Règles de gouvernance :
  - les capacités annoncées ne s'activent JAMAIS seules : chaque modèle devient une déclaration personnalisée
    `verification="a_lire"`, `residence="inconnue"` (EFVP requise), qu'un administrateur lit, complète et active sous le
    moteur de politique habituel ; rien n'est vérifié par Nexora lui-même ;
  - chaque artefact doit déclarer son modèle et sa licence ; un artefact d'un AUTRE modèle que celui demandé est refusé
    (un fournisseur ne remplace pas en silence un modèle conforme par un autre) ;
  - PNG seulement pour une image (pas de JPEG pour l'impression) ; aucune donnée personnelle dans l'invite (l'invite du
    studio n'en contient jamais) ;
  - le basculement vers un autre fournisseur se fait par configuration (sélection du registre), sans changer de code.
Jamais exécuté contre le vrai service : le transport réel n'existe pas.

Module sans entrée-sortie propre.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from . import png
from .generation import (
    NATURE_DOUBLE,
    DemandeGeneration,
    ErreurGeneration,
    GenerateurImageDouble,
    SortieGeneration,
)

REJ_NEXORA = "REJ-STUDIO-NEXORA"
REJ_NEXORA_MODELE = "REJ-STUDIO-NEXORA-MODELE-DIFFERENT"
REJ_NEXORA_LICENCE = "REJ-STUDIO-NEXORA-LICENCE-NON-DECLAREE"
_TERRITOIRES = {"EU": "UE", "UE": "UE", "UK": "UK", "KR": "KR", "US": "US", "CA": "CA", "CN": "CN"}
_SERVICE_TIERS = {"allowed": "autorise", "forbidden": "interdit", "unclear": "incertain"}


class PortNexora(Protocol):
    nature: str

    def capacites(self) -> list[dict[str, Any]]:
        """`GET /v1/capabilities` : modèles, types, résolutions max, licences et drapeaux, coûts."""

    def soumettre(self, travail: Mapping[str, Any], cle_idempotence: str) -> str:
        """`POST /v1/jobs` : un travail (brief structuré, graine, modèle demandé) ; rend l'identifiant du travail."""

    def statut(self, travail_id: str) -> str:
        """`GET /v1/jobs/{id}` : `en_cours`, `termine` ou `echec`."""

    def artefacts(self, travail_id: str) -> list[dict[str, Any]]:
        """`GET /v1/jobs/{id}/artifacts` : `{nom, format, octets_base64, modele, licence_id}` par sortie."""


def declarations_depuis_capacites(capacites: Sequence[Mapping[str, Any]], point_acces: str) -> list[dict[str, Any]]:
    """Une déclaration de fournisseur (pour `registre.configurer(declaration=…)`) par modèle annoncé. Les drapeaux de
    licence sont ceux que Nexora DÉCLARE ; la déclaration reste `a_lire` : un administrateur les relit avant
    activation."""
    sortie = []
    for cap in capacites:
        genre = "video" if str(cap.get("kind", "")).startswith("video") else "image"
        licence = cap.get("license") or {}
        commercial = licence.get("commercial")
        plafond = licence.get("revenue_cap_usd")
        if commercial is False:
            usage = "interdit"
        elif commercial is True and plafond:
            usage = "sous_seuil"
        elif commercial is True:
            usage = "autorise"
        else:
            usage = "inconnu"
        modele_id = str(cap["id"]).lower().replace("_", "-")
        sortie.append(
            {
                "identifiant": f"{genre}.nexora.{modele_id}.api",
                "capacite": genre,
                "mode": "api",
                "modele": f"{cap.get('name', cap['id'])} (via Nexora Creative)",
                "point_acces": point_acces,
                "residence_donnees": "inconnue",
                "licence": {
                    "code": None,
                    "poids": str(licence.get("id") or "non déclarée"),
                    "usage_commercial": usage,
                    "seuil_revenu_usd": int(plafond) if usage == "sous_seuil" else None,
                    "territoires_exclus": [
                        t
                        for t in dict.fromkeys(
                            _TERRITOIRES.get(x, "AUTRE") for x in licence.get("excluded_territories") or []
                        )
                    ],
                    "service_tiers": _SERVICE_TIERS.get(licence.get("service_to_third_parties"), "incertain"),
                    "mention_obligatoire": licence.get("attribution"),
                    "integration": "api",
                    "verification": "a_lire",
                    "source": "Nexora Creative /v1/capabilities (déclaré par le fournisseur, non vérifié)",
                    "note": "capacité annoncée par Nexora : à lire, compléter (contrat, EFVP) et activer par un "
                    "administrateur",
                },
            }
        )
    return sortie


class GenerateurNexora:
    """Adaptateur : un `GenerateurImage` qui délègue à Nexora par le port. Sa nature est celle du transport."""

    def __init__(self, port: PortNexora, modele_id: str) -> None:
        self._port, self._modele_id = port, modele_id
        self.nature = port.nature

    def generer(self, demande: DemandeGeneration) -> SortieGeneration:
        if demande.genre != "image":
            raise ErreurGeneration(REJ_NEXORA, "cet adaptateur ne génère que des images")
        travail = {
            "modele": self._modele_id,
            "invite": demande.invite,
            "invite_negative": demande.invite_negative,
            "largeur": demande.largeur,
            "hauteur": demande.hauteur,
            "graine": demande.graine,
            "format_sortie": "png",
        }
        travail_id = self._port.soumettre(travail, demande.empreinte()[:32])
        statut = self._port.statut(travail_id)
        if statut != "termine":
            raise ErreurGeneration(REJ_NEXORA, f"travail Nexora non terminé ({statut})")
        artefacts = self._port.artefacts(travail_id)
        if len(artefacts) != 1:
            raise ErreurGeneration(REJ_NEXORA, "un seul artefact attendu")
        a = artefacts[0]
        if not a.get("modele") or not a.get("licence_id"):
            raise ErreurGeneration(REJ_NEXORA_LICENCE, "Nexora doit déclarer le modèle et la licence de chaque sortie")
        if a["modele"] != self._modele_id:
            raise ErreurGeneration(
                REJ_NEXORA_MODELE,
                f"modèle demandé {self._modele_id!r}, sortie produite par "
                f"{a['modele']!r} : refusé (aucun remplacement silencieux)",
            )
        if a.get("format") != "png":
            raise ErreurGeneration(REJ_NEXORA, "PNG exigé (pas de JPEG pour l'impression)")
        try:
            octets = base64.b64decode(a["octets_base64"], validate=True)
            largeur, hauteur = png.dimensions(octets)
        except (binascii.Error, KeyError, TypeError, png.PngInvalide):
            raise ErreurGeneration(REJ_NEXORA, "artefact illisible") from None
        return SortieGeneration(
            octets,
            "png",
            largeur,
            hauteur,
            a["modele"],
            str(a.get("version", "inconnue")),
            a.get("poids_ref"),
            demande.graine,
            demande.invite,
            self.nature,
            {"nexora": {"travail": travail_id, "licence_id": a["licence_id"]}},
        )


class NexoraDouble:
    """Double de test du service : capacités fixes, travaux synchrones et déterministes, AUCUN réseau."""

    nature = NATURE_DOUBLE
    CAPACITES = [
        {
            "id": "nexora-fond-1",
            "name": "Nexora Fond 1",
            "kind": "image.t2i",
            "max_mp": 2,
            "license": {
                "id": "Nexora-Commercial",
                "commercial": True,
                "revenue_cap_usd": None,
                "excluded_territories": [],
                "service_to_third_parties": "unclear",
            },
        },
        {
            "id": "nexora-nc",
            "name": "Nexora NC",
            "kind": "image.t2i",
            "max_mp": 2,
            "license": {
                "id": "CC-BY-NC-4.0",
                "commercial": False,
                "excluded_territories": [],
                "service_to_third_parties": "forbidden",
            },
        },
        {
            "id": "nexora-seuil",
            "name": "Nexora Seuil",
            "kind": "image.t2i",
            "max_mp": 1,
            "license": {
                "id": "Community-1M",
                "commercial": True,
                "revenue_cap_usd": 1_000_000,
                "excluded_territories": ["EU", "UK"],
                "service_to_third_parties": "forbidden",
                "attribution": "Powered by Nexora",
            },
        },
    ]

    def __init__(self, modele_reel_different: str | None = None, format_sortie: str = "png") -> None:
        self._travaux: dict[str, dict[str, Any]] = {}
        self._remplacement, self._format = modele_reel_different, format_sortie
        self.appels: list[str] = []

    def capacites(self) -> list[dict[str, Any]]:
        self.appels.append("capacites")
        return [dict(c) for c in self.CAPACITES]

    def soumettre(self, travail: Mapping[str, Any], cle_idempotence: str) -> str:
        self.appels.append("soumettre")
        travail_id = "job-" + hashlib.sha256(cle_idempotence.encode()).hexdigest()[:12]
        if travail_id not in self._travaux:
            sortie = GenerateurImageDouble().generer(
                DemandeGeneration(
                    travail_id,
                    "b",
                    "e" * 64,
                    "image",
                    travail["invite"],
                    travail["invite_negative"],
                    travail["largeur"],
                    travail["hauteur"],
                    travail["graine"],
                )
            )
            self._travaux[travail_id] = {"modele": self._remplacement or travail["modele"], "octets": sortie.octets}
        return travail_id

    def statut(self, travail_id: str) -> str:
        self.appels.append("statut")
        return "termine" if travail_id in self._travaux else "echec"

    def artefacts(self, travail_id: str) -> list[dict[str, Any]]:
        self.appels.append("artefacts")
        t = self._travaux[travail_id]
        return [
            {
                "nom": "fond.png",
                "format": self._format,
                "octets_base64": base64.b64encode(t["octets"]).decode(),
                "modele": t["modele"],
                "licence_id": "Nexora-Commercial",
                "version": "2026.11",
            }
        ]
