"""Outils d'expériences et ROI M9.18 : définir, évaluer (avec trace de résultat), lire. Aucun chiffre n'est fabriqué."""

from __future__ import annotations

from typing import Any

from opsys import contexte, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import dossier_strategique, experiences
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_EXPERIENCES = "experiences"
REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}
_ID = {"type": "string", "minLength": 1, "maxLength": 128}


def construire_outils(
    *, budget_sortie: int, experiences_cible: Any = None, captures_cible: Any = None
) -> tuple[Outil, ...]:
    def registre() -> Any:
        if experiences_cible is not None:
            return experiences_cible
        return stockage.maillons(DEPARTEMENT, REGISTRE_EXPERIENCES)

    def chaine() -> list[dict]:
        liste = list(registre())
        ok, raison = experiences.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-EXPERIENCE-CHAINE-INVALIDE : registre des expériences invalide ({raison})")
        return liste

    def captures() -> list[dict]:
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        liste = list(source)
        ok, raison = cs.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-CAPTURE-CHAINE-INVALIDE : registre des captures invalide ({raison})")
        return liste

    def personne() -> str:
        appelante = contexte.identite_appelante()
        return appelante.personne if appelante is not None else "inconnu"

    def definir(
        experience: dict[str, Any], reference: str, horodatage: str, motif_revision: str | None = None
    ) -> dict[str, Any]:
        exiger_admin_strict()
        liste = chaine()
        faits = dossier_strategique.construire(
            captures(), question="Expérience", domaines=["strategie"], reference=reference, connaissance=horodatage
        )["faits"]
        maillon = experiences.definir(
            liste, experience, faits, recu_a=horodatage, par=personne(), motif_revision=motif_revision
        )
        registre().append(maillon, rang_attendu=len(liste))
        return {
            "accepte": True,
            "experience_id": maillon["experience_id"],
            "version": maillon["version"],
            "revision": maillon["version"] > 1,
        }

    def evaluer(experience_id: str, horodatage: str) -> dict[str, Any]:
        exiger_admin_strict()
        liste = chaine()
        projection = experiences.vue(liste, captures(), connaissance=horodatage)
        courante = next((e for e in projection["experiences"] if e["experience_id"] == experience_id), None)
        if courante is None:
            raise ValueError("REJ-EXPERIENCE-INCONNUE : expérience jamais définie")
        maillon = experiences.enregistrer_resultat(
            liste, experience_id, courante["evaluation"], recu_a=horodatage, par=personne()
        )
        if maillon is not None:
            registre().append(maillon, rang_attendu=len(liste))
        return borner(
            {
                "accepte": True,
                "resultat_ajoute": maillon is not None,
                "experience": courante,
                "limites": projection["limites"],
            },
            budget_sortie,
        )

    def lire(connaissance: str, experience_id: str | None = None) -> dict[str, Any]:
        exiger_admin_strict()
        projection = experiences.vue(chaine(), captures(), connaissance=connaissance)
        if experience_id is not None:
            projection["experiences"] = [e for e in projection["experiences"] if e["experience_id"] == experience_id]
        return borner({"accepte": True, **projection}, budget_sortie)

    def outil(nom, description, proprietes, requis, fonction, *, ecriture=False):
        return Outil(
            nom=nom,
            description=description,
            parametres={"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False},
            fonction=fonction,
            autonomie=Autonomie.T1 if ecriture else Autonomie.T0,
            niveau=Niveau.N2 if ecriture else Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        )

    return (
        outil(
            "m9_definir_experience",
            "Définit (ou révise avec motif) une expérience : hypothèse, design, mesures citées par adresse de fait "
            "(référence, exposé, coût, effectif) et contre-exemples. Aucun chiffre n'est produit à la définition.",
            {
                "experience": {"type": "object"},
                "reference": _INSTANT,
                "horodatage": _INSTANT,
                "motif_revision": {"type": "string", "maxLength": 300},
            },
            ["experience", "reference", "horodatage"],
            definir,
            ecriture=True,
        ),
        outil(
            "m9_evaluer_experience",
            "Relit les mesures chez leurs propriétaires et rend gain mesuré, ROI (ou ROI non calculable avec ce qui "
            "manque), association ou causalité plausible, lacunes ; ajoute un résultat si les entrées ont changé.",
            {"experience_id": _ID, "horodatage": _INSTANT},
            ["experience_id", "horodatage"],
            evaluer,
            ecriture=True,
        ),
        outil(
            "m9_lire_experiences",
            "Expériences à un instant : version courante, évaluation sur les captures connues, "
            "historique des résultats.",
            {"connaissance": _INSTANT, "experience_id": _ID},
            ["connaissance"],
            lire,
        ),
    )
