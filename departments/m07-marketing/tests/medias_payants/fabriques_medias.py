"""Fabriques des tests des médias payants : plan valide, studio fictif (résolveur de créatifs), politique, masqueur.
Données FICTIVES."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from m7_marketing.sas_social.politique import PolitiqueSas

from opsys.observabilite.pii import MasqueurMotifs

MAINTENANT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
HORODATAGE = "2026-11-01T12:00:00+00:00"
CLE = "cle-plan-media-0123456789"
POLITIQUE = PolitiqueSas()
EMPREINTE_VISUEL = "e" * 64


def masqueur() -> MasqueurMotifs:
    return MasqueurMotifs(b"\x05" * 32)


class StudioFictif:
    """Le résolveur de créatifs de test : `approuves` = actif_id -> empreinte_actif. Un actif absent est refusé comme le
    ferait `studio.actifs.media_pour_sas` pour un visuel non approuvé."""

    def __init__(self, approuves: dict[str, str] | None = None) -> None:
        self.approuves = {"visuel-1": EMPREINTE_VISUEL} if approuves is None else dict(approuves)
        self.appels: list[str] = []

    def __call__(self, actif_id: str) -> dict[str, Any]:
        self.appels.append(actif_id)
        if actif_id not in self.approuves:
            return {
                "accepte": False,
                "refus": [{"code": "REJ-STUDIO-ETAT", "chemin": "$.actif_id", "detail": "visuel non approuvé"}],
            }
        return {
            "accepte": True,
            "empreinte_actif": self.approuves[actif_id],
            "media": {
                "reference": f"{actif_id}-png",
                "sha256": "a" * 64,
                "realiste": False,
                "ia_generee": False,
                "format": "png",
                "octets": 1000,
                "largeur": 1200,
                "hauteur": 630,
            },
        }

    def revoquer(self, actif_id: str) -> None:
        del self.approuves[actif_id]


def plan_brut(**modif: Any) -> dict[str, Any]:
    """Un plan VALIDE (Meta, dix jours à compter du 10 novembre 2026, 20 $ par jour, 200 $ au total)."""
    plan = {
        "nom": "Soumissions automne",
        "canal": "meta",
        "objectif": "leads",
        "budget": {
            "montant_total_cents": 20000,
            "plafond_quotidien_cents": 2000,
            "duree_jours": 10,
            "date_debut": "2026-11-10",
        },
        "ciblage": {
            "zones": ["Laval", "Terrebonne"],
            "rayon_km": 25,
            "langues": ["fr-CA"],
            "mots_cles": ["soumission travaux"],
            "mots_cles_negatifs": ["gratuit"],
        },
        "creatifs": [
            {
                "actif_id": "visuel-1",
                "textes": [
                    {
                        "langue": "fr-CA",
                        "titre": "Demandez une soumission",
                        "description": "Un estimateur vous contacte pour planifier une visite.",
                    }
                ],
            }
        ],
        "utm_campagne": "contenu-automne-2026",
        "divulgation_texte_ia": True,
        "comptes_sas": [{"reseau": "facebook", "compte": "page-horizon"}],
    }
    plan.update(copy.deepcopy(modif))
    return plan


def controles(studio: StudioFictif | None = None, *, maintenant: datetime = MAINTENANT, controle_marques=None) -> dict:
    return {
        "politique": POLITIQUE,
        "maintenant": maintenant,
        "resolveur": studio or StudioFictif(),
        "masqueur": masqueur(),
        "controle_marques": controle_marques,
    }
