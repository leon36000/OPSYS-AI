"""Questions obligatoires par service (PLAN T4.4, `docs/departements/M1-canaux.md` §9).

Ce que M1 demande au client pour qualifier un lead n'est PAS dans ce code : le propriétaire l'écrit, par service,
dans le profil d'entreprise (`questions_qualification`, lu par `opsys.taxonomie`). Ce module ne fait que deux choses,
par des règles :

- reconnaître, dans les messages rassemblés d'une conversation, les questions auxquelles le client a déjà répondu :
  une question est répondue quand un de ses `mots_cles` (déclarés dans le profil) figure dans le texte, avec les mêmes
  règles de lecture que les mots-clés d'un service (mot entier, pluriel admis, accents et casse ignorés) ;
- dire ce qui reste à demander, dans l'ordre écrit par le propriétaire.

Fail-closed : sans service établi, on ne sait pas quelles questions poser ; sans question déclarée pour le service, le
statut le dit (`non_configurees`, avec le verdict qui dit où les écrire) et aucune question n'est jamais inventée. Une
question de photos (`photos: true`) n'est jamais « répondue » par du texte et ne se propose qu'une fois la politique
« photos » validée (`photos.py`).

Module pur : aucune horloge, aucun accès à la base ni au réseau.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from opsys import taxonomie
from opsys.taxonomie import QuestionQualification

from . import qualification

STATUT_SERVICE_A_PRECISER = "service_a_preciser"
STATUT_NON_CONFIGUREES = "non_configurees"
STATUT_PROFIL_INVALIDE = "profil_invalide"
STATUT_A_POSER = "a_poser"
STATUT_AUCUNE_RESTANTE = "aucune_restante"


@dataclass(frozen=True)
class EtatQuestions:
    """Où en sont les questions du service de la conversation."""

    statut: str
    service: str | None
    repondues: tuple[QuestionQualification, ...]
    restantes: tuple[QuestionQualification, ...]  # texte à poser, pas encore répondues
    photos: tuple[QuestionQualification, ...]  # demandes de photos déclarées (fermées ou non : voir `photos.py`)
    verdict: dict[str, str] | None  # pourquoi il n'y a pas de question (non configurées, profil invalide)

    def bloc(self) -> dict[str, Any]:
        """Le bloc `questions` de la réponse de l'outil (les textes viennent du profil)."""
        bloc: dict[str, Any] = {
            "statut": self.statut,
            "service": self.service,
            "repondues": [q.code for q in self.repondues],
            "restantes": [{"code": q.code, "question": q.question} for q in self.restantes],
        }
        if self.verdict is not None:
            bloc["verdict"] = self.verdict
        return bloc


def reconnues(questions: Sequence[QuestionQualification], contenu: str) -> list[str]:
    """Codes des questions de texte auxquelles le contenu répond (un de leurs `mots_cles` y figure)."""
    texte = qualification.sans_accent(qualification.contenu_utile(contenu))
    codes = []
    for question in questions:
        motif = None if question.photos else qualification.motif_de_termes(question.mots_cles)
        if motif is not None and motif.search(texte):
            codes.append(question.code)
    return codes


def evaluer(
    service: str | None,
    questions: Sequence[QuestionQualification],
    verdict_profil: dict[str, str] | None,
    contenu: str,
) -> EtatQuestions:
    """L'état des questions du `service` pour le `contenu` rassemblé de la conversation.

    `questions`, `verdict_profil` : le résultat de `taxonomie.charger_questions_du_service(service)` (l'appelant lit le
    profil, ce module reste pur). `service` est `None` tant que la conversation n'a pas établi son service.
    """
    if service is None:
        return EtatQuestions(STATUT_SERVICE_A_PRECISER, None, (), (), (), None)
    if verdict_profil is not None:
        statut = (
            STATUT_NON_CONFIGUREES
            if verdict_profil["code"] == taxonomie.VERDICT_QUESTIONS_NON_CONFIGUREES
            else STATUT_PROFIL_INVALIDE
        )
        return EtatQuestions(statut, service, (), (), (), verdict_profil)
    photos = tuple(q for q in questions if q.photos)
    texte = tuple(q for q in questions if not q.photos)
    repondues_codes = set(reconnues(texte, contenu))
    repondues = tuple(q for q in texte if q.code in repondues_codes)
    restantes = tuple(q for q in texte if q.code not in repondues_codes)
    statut = STATUT_A_POSER if restantes else STATUT_AUCUNE_RESTANTE
    return EtatQuestions(statut, service, repondues, restantes, photos, None)
