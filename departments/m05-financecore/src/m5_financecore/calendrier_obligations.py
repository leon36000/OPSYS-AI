"""Calendrier préparatoire des obligations déclarées, sans calcul de paie ni règle implicite.

Les montants viennent des obligations M5 déjà déclarées, les dates d'échéance de la configuration de
prévision et les métadonnées de période/autorité/source du calendrier déclaré. Une source dont la fenêtre
de validité déclarée ne couvre pas toute la période reste visible mais n'est pas utilisable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from . import analyse, validation

__all__ = ["lire_obligations_documentees"]

_CLES = ("paies", "das", "dettes")
_CHAMPS = frozenset(
    {
        "autorite",
        "periode_debut",
        "periode_fin",
        "echeance_source",
        "source_consultee_le",
        "source_applicable_du",
        "source_applicable_jusqu_au",
        "annee",
        "version",
    }
)
_MONTANT = re.compile(r"^[0-9]{1,12}(?:\.[0-9]{1,2})?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_NOMS = {"paies": "Paies", "das": "Déductions à la source (DAS)", "dettes": "Dettes déclarées"}


def _jour(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or _DATE.fullmatch(valeur) is None:
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def _texte(valeur: Any) -> str | None:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > 240:
        return None
    return valeur.strip()


def lire_obligations_documentees(
    aujourd_hui: Any,
    obligations_declarees: Any,
    echeances_obligations: Any,
    calendrier_obligations: Any,
) -> dict[str, Any]:
    """Rend les trois obligations connues par M5 et nomme chaque pièce qui manque.

    ``calendrier_obligations`` n'est pas une table de règles. Ses valeurs doivent venir d'une déclaration
    ou d'une source officielle revue; le module n'infère ni fréquence, autorité, montant ni date récurrente.
    """
    jour = _jour(aujourd_hui)
    if jour is None:
        raise ValueError("aujourd_hui doit être une date AAAA-MM-JJ")
    donnees = obligations_declarees if isinstance(obligations_declarees, Mapping) else {}
    dates = echeances_obligations if isinstance(echeances_obligations, Mapping) else {}
    calendrier = calendrier_obligations if isinstance(calendrier_obligations, Mapping) else {}
    lignes = []
    for cle in _CLES:
        manque: list[dict[str, str]] = []
        declaration = donnees.get(cle)
        declaration = declaration if isinstance(declaration, Mapping) else {}
        montant = declaration.get("montant")
        if not isinstance(montant, str) or not _MONTANT.fullmatch(montant):
            montant = None
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-MONTANT-ABSENT",
                    detail=f"montant {cle} absent ou invalide dans configuration.obligations_declarees.{cle}",
                )
            )
        source_montant = _texte(declaration.get("source"))
        au = _jour(declaration.get("au"))
        if source_montant is None or au is None:
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-SOURCE-MONTANT-ABSENTE",
                    detail=f"source et date de la déclaration {cle} requises",
                )
            )

        echeance = _jour(dates.get(cle))
        if echeance is None:
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-ECHEANCE-ABSENTE",
                    detail=f"échéance {cle} à déclarer dans configuration.prevision.echeances_obligations.{cle}",
                )
            )

        meta = calendrier.get(cle)
        if not isinstance(meta, Mapping) or set(meta) != _CHAMPS:
            meta = {}
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-PERIODE-SOURCE-ABSENTE",
                    detail=f"autorité, période, source d'échéance, année et version à déclarer pour {cle}",
                )
            )
        autorite = _texte(meta.get("autorite"))
        periode_debut = _jour(meta.get("periode_debut"))
        periode_fin = _jour(meta.get("periode_fin"))
        source_echeance = _texte(meta.get("echeance_source"))
        source_consultee_le = _jour(meta.get("source_consultee_le"))
        source_applicable_du = _jour(meta.get("source_applicable_du"))
        source_applicable_jusqu_au = _jour(meta.get("source_applicable_jusqu_au"))
        annee = meta.get("annee")
        version = _texte(meta.get("version"))
        if autorite is None or source_echeance is None or version is None:
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-SOURCE-INVALIDE",
                    detail="autorité, source d'échéance et version explicites exigées",
                )
            )
        if (
            source_applicable_du is not None
            and source_applicable_jusqu_au is not None
            and source_applicable_jusqu_au < source_applicable_du
        ):
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-SOURCE-INVALIDE",
                    detail="fenêtre de validité de la source inversée",
                )
            )
        if periode_debut is None or periode_fin is None or periode_fin < periode_debut:
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-PERIODE-INVALIDE",
                    detail="période de début et de fin valide exigée",
                )
            )
        if source_consultee_le is None or source_applicable_du is None or source_applicable_jusqu_au is None:
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-DATE-SOURCE-INVALIDE",
                    detail="dates de consultation et de validité déclarée de la source d'échéance exigées",
                )
            )
        if isinstance(annee, bool) or not isinstance(annee, int) or periode_fin is None or annee != periode_fin.year:
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-ANNEE-VERSION-INVALIDE",
                    detail="année déclarée entière et égale à l'année de fin de période exigée",
                )
            )

        source_perimee = bool(
            periode_debut is not None
            and periode_fin is not None
            and source_applicable_du is not None
            and source_applicable_jusqu_au is not None
            and (source_applicable_du > periode_debut or source_applicable_jusqu_au < periode_fin)
        )
        if source_perimee:
            manque.append(
                validation.construire_verdict(
                    f"REJ-CALENDRIER-{cle.upper()}-SOURCE-PERIMEE",
                    detail="la fenêtre de validité déclarée de la source ne couvre pas toute la période",
                )
            )

        if source_perimee:
            statut = "SOURCE_PERIMEE"
        elif manque:
            statut = "INCOMPLETE"
        elif echeance is not None and echeance < jour:
            statut = "ECHEANCE_PASSEE_A_VERIFIER"
        else:
            statut = "DOCUMENTEE_A_VALIDER"
        lignes.append(
            {
                "id": cle,
                "nom": _NOMS[cle],
                "autorite": autorite,
                "periode": {
                    "debut": periode_debut.isoformat() if periode_debut else None,
                    "fin": periode_fin.isoformat() if periode_fin else None,
                },
                "echeance": echeance.isoformat() if echeance else None,
                "montant": montant,
                "devise": "CAD" if montant is not None else None,
                "source_montant": {"description": source_montant, "au": au.isoformat() if au else None},
                "source_echeance": {
                    "description": source_echeance,
                    "consultee_le": source_consultee_le.isoformat() if source_consultee_le else None,
                    "applicable_du": source_applicable_du.isoformat() if source_applicable_du else None,
                    "applicable_jusqu_au": source_applicable_jusqu_au.isoformat()
                    if source_applicable_jusqu_au
                    else None,
                },
                "annee": annee if type(annee) is int else None,
                "version": version,
                "montant_utilisable": montant
                if montant is not None and source_montant is not None and au is not None and not source_perimee
                else None,
                "echeance_statut": (
                    "NON_DECLAREE" if echeance is None else "PASSEE_A_VERIFIER" if echeance < jour else "A_VENIR"
                ),
                "statut": statut,
                "manque": manque,
            }
        )
    return analyse.avec_mention(
        {
            "type": "CALENDRIER_PREPARATOIRE_OBLIGATIONS",
            "aujourd_hui": jour.isoformat(),
            "obligations": lignes,
            "limites": [
                "les dates, périodes, montants, autorités et sources viennent des déclarations explicites",
                "une échéance passée signifie à vérifier; OPSYS ne sait pas si elle a été payée ou déclarée",
                "aucune formule de paie, retenue, cotisation, intérêt ou pénalité n'est calculée",
                "aucune remise, déclaration, transmission ou paiement n'est effectué",
            ],
        }
    )
