"""Raccord des consommateurs au registre des rôles : embeddings et reranker de M10, choix du moteur OCR.

Rien ne change tant qu'aucun rôle n'est configuré : sans affectation, `fabrique_*` rend `None` et le comportement
d'avant s'applique (fail-closed : « conforme mais non raccordé », recherche lexicale seule).

- **Embeddings** : l'adaptateur n'existe que pour le fournisseur AFFECTÉ au rôle `embeddings` et seulement si la
dimension a
  été MESURÉE par un test de connexion (un vecteur n'a de sens que dans son espace : la dimension n'est jamais
  supposée).
  Le profil porte le modèle réellement appelé et l'empreinte de configuration du registre : changer d'alias change
  l'espace et impose la réindexation. Les appels passent par l'appel routé (plafonds, politique de licence) ; le rôle
  n'accepte AUCUN repli.
- **Reranker** : même chemin, point d'extension `/v1/rerank` de la passerelle ; facultatif comme avant.
- **OCR** : `moteur_ocr_choisi` dit quel moteur le propriétaire a choisi ; seul le worker Tesseract isolé existe, tout
  autre choix est refusé (`REJ-ING-OCR-INDISPONIBLE`), jamais remplacé en silence par Tesseract.
- **STT, TTS, vision-langage, image** : documentés (PASSERELLE-DE-MODELES.md), pas encore raccordés à un consommateur.

Dans une transaction d'outil, le secret du coffre est résolu dans un point de sauvegarde (`dans_transaction=True`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import Connection
from sqlalchemy.exc import OperationalError, ProgrammingError

from .. import stockage
from ..connaissances import ports
from ..connaissances.codes import EMBEDDINGS_NON_RACCORDE, ErreurConnaissances
from ..fournisseurs.modele import Fournisseur
from . import appel, service
from .codes import ModelesErreur

OCR_RACCORDE = "ocr.tesseract-5.5.local"
LOT_MAX = 64


class _PortEmbeddings:
    def __init__(self, fournisseur: Fournisseur, modele: str, dimension: int, fabrique: Callable[[], Any]) -> None:
        self._fournisseur, self._modele, self._dimension, self._fabrique = fournisseur, modele, dimension, fabrique

    def profil(self) -> ports.ProfilEmbeddings:
        return ports.ProfilEmbeddings(
            fournisseur_id=self._fournisseur.identifiant,
            modele=self._modele,
            dimension=self._dimension,
            config_sha256=ports.empreinte_configuration(self._fournisseur),
        )

    def _plonger(self, textes: Sequence[str]) -> list[list[float]]:
        sortie: list[list[float]] = []
        for debut in range(0, len(textes), LOT_MAX):
            sortie.extend(
                appel.plonger(self._fabrique, textes=list(textes[debut : debut + LOT_MAX]), dans_transaction=True)[
                    "vecteurs"
                ]
            )
        return sortie

    def plonger_documents(self, textes: Sequence[str]) -> list[list[float]]:
        return self._plonger(textes)

    def plonger_requete(self, texte: str) -> list[float]:
        return self._plonger([texte])[0]


class _PortReranker:
    def __init__(self, fournisseur: Fournisseur, modele: str, fabrique: Callable[[], Any]) -> None:
        self._fournisseur, self._modele, self._fabrique = fournisseur, modele, fabrique

    def identite(self) -> ports.IdentiteReranker:
        return ports.IdentiteReranker(
            self._fournisseur.identifiant, self._modele, ports.empreinte_configuration(self._fournisseur)
        )

    def noter(self, requete: str, passages: Sequence[str]) -> list[float]:
        return appel.reclasser(self._fabrique, requete=requete, passages=list(passages), dans_transaction=True)["notes"]


def _ligne_du_fournisseur(cnx: Connection, role: str, fournisseur: Fournisseur) -> dict[str, Any] | None:
    ligne = service.ligne_role(cnx, role)
    if ligne is None or ligne["fournisseur_id"] != fournisseur.identifiant:
        return None
    return ligne


def fabrique_embeddings(
    cnx: Connection, fournisseur: Fournisseur
) -> Callable[[Fournisseur], ports.PortEmbeddings] | None:
    ligne = _ligne_du_fournisseur(cnx, "embeddings", fournisseur)
    if ligne is None:
        return None
    dimension = (ligne["mesures"] or {}).get("dimension")
    if type(dimension) is not int or (ligne["mesures"] or {}).get("statut") != "succes":
        raise ErreurConnaissances(
            EMBEDDINGS_NON_RACCORDE,
            f"{fournisseur.identifiant} est affecté au rôle embeddings mais sa dimension n'est pas mesurée : tester la "
            "connexion du rôle (console « Modèles et rôles »)",
        )
    return lambda f: _PortEmbeddings(f, ligne["modele_appel"], dimension, stockage.transaction)


def fabrique_reranker(cnx: Connection, fournisseur: Fournisseur) -> Callable[[Fournisseur], ports.PortReranker] | None:
    ligne = _ligne_du_fournisseur(cnx, "reranker", fournisseur)
    if ligne is None:
        return None
    return lambda f: _PortReranker(f, ligne["modele_appel"], stockage.transaction)


def est_raccorde(cnx: Connection, role: str, fournisseur: Fournisseur) -> bool:
    ligne = _ligne_du_fournisseur(cnx, role, fournisseur)
    if ligne is None:
        return False
    return role != "embeddings" or type((ligne["mesures"] or {}).get("dimension")) is int


def embeddings_raccordes() -> bool:
    """Rôle `embeddings` affecté ET dimension mesurée. Une base sans le registre des rôles (installation non migrée) dit
    « non raccordé » : jamais une erreur, jamais un raccordement supposé."""
    try:
        with stockage.transaction() as cnx:
            ligne = service.ligne_role(cnx, "embeddings")
    except (OperationalError, ProgrammingError):
        return False
    return bool(ligne and type((ligne["mesures"] or {}).get("dimension")) is int)


def moteur_ocr_choisi() -> str | None:
    """Fournisseur affecté au rôle `ocr`, ou `None` : rien de configuré, le comportement d'avant reste."""
    with stockage.transaction() as cnx:
        ligne = service.ligne_role(cnx, "ocr")
    return None if ligne is None else ligne["fournisseur_id"]


def refus_moteur_ocr(choix: str | None) -> str | None:
    """Message de refus si le moteur choisi n'est pas celui qui existe ; `None` si l'on peut continuer."""
    if choix is None or choix == OCR_RACCORDE:
        return None
    return (
        f"le moteur OCR choisi ({choix}) n'est pas raccordé : seul {OCR_RACCORDE} (worker isolé) l'est ; aucun autre "
        "moteur n'est utilisé à sa place"
    )


__all__ = ["ModelesErreur", "est_raccorde", "fabrique_embeddings", "fabrique_reranker", "moteur_ocr_choisi"]
