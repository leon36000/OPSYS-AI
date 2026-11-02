"""Ports d'embeddings et de reranker, et leur résolution par le registre de fournisseurs.

Aucun appel réseau ici. Un fournisseur du registre (capacité `embeddings` ou `reranker`) n'est appelé que par un
ADAPTATEUR raccordé à son identifiant (`_ADAPTATEURS_*`). Cette tranche n'en raccorde AUCUN de réel : un fournisseur
conforme mais non raccordé est `REJ-CONN-EMBEDDINGS-NON-RACCORDE` et la recherche reste lexicale, avec l'avertissement
(jamais un repli silencieux). Les tests raccordent les doubles de `doubles.py`.

**Espace vectoriel.** Un vecteur n'a de sens que dans l'espace du modèle qui l'a produit. Chaque `ProfilEmbeddings`
porte le fournisseur, le modèle, la dimension, la normalisation, les préfixes et l'EMPREINTE DE CONFIGURATION du
fournisseur dans le registre (`empreinte_configuration`) ; son sha256 est l'identifiant de l'espace. Changer de modèle,
de point d'accès ou de préfixe change l'espace : les anciens vecteurs ne sont plus lus, la base demande une
réindexation. Un adaptateur dont le profil ne correspond pas à la configuration du registre est refusé.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from ..fournisseurs import registre
from ..fournisseurs.modele import Fournisseur
from . import vecteurs
from .codes import (
    EMBEDDINGS_INVALIDE,
    EMBEDDINGS_NON_RACCORDE,
    FOURNISSEUR_REFUSE,
    RERANKER_INVALIDE,
    ErreurConnaissances,
)

CAPACITE_EMBEDDINGS = "embeddings"
CAPACITE_RERANKER = "reranker"


def empreinte_configuration(fournisseur: Fournisseur) -> str:
    """sha256 de ce qui détermine ce que le fournisseur produit : identifiant, mode, modèle, point d'accès et licence
    des
    poids. Ni quota, ni coût, ni note, ni référence de secret (la rotation d'une clé ne change pas l'espace)."""
    donnees = {"identifiant": fournisseur.identifiant, "capacite": fournisseur.capacite, "mode": fournisseur.mode,
               "modele": fournisseur.modele, "point_acces": fournisseur.point_acces, "poids": fournisseur.licence.poids}
    return hashlib.sha256(json.dumps(donnees, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclasses.dataclass(frozen=True)
class ProfilEmbeddings:
    fournisseur_id: str
    modele: str
    dimension: int
    config_sha256: str
    normalisation: str = "l2"
    prefixe_requete: str = ""
    prefixe_document: str = ""
    revision_adaptateur: str = "1"

    def __post_init__(self) -> None:
        if (not isinstance(self.fournisseur_id, str) or not self.fournisseur_id or not isinstance(self.modele, str)
                or not self.modele or type(self.dimension) is not int or not 2 <= self.dimension <= 8192
                or not isinstance(self.config_sha256, str) or len(self.config_sha256) != 64
                or self.normalisation != "l2"):
            raise ErreurConnaissances(EMBEDDINGS_INVALIDE, "profil d'embeddings invalide")

    def canonique(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @property
    def espace_id(self) -> str:
        return hashlib.sha256(self.canonique().encode("utf-8")).hexdigest()


class PortEmbeddings(Protocol):
    def profil(self) -> ProfilEmbeddings: ...

    def plonger_documents(self, textes: Sequence[str]) -> list[list[float]]: ...

    def plonger_requete(self, texte: str) -> list[float]: ...


@dataclasses.dataclass(frozen=True)
class IdentiteReranker:
    fournisseur_id: str
    modele: str
    config_sha256: str


class PortReranker(Protocol):
    def identite(self) -> IdentiteReranker: ...

    def noter(self, requete: str, passages: Sequence[str]) -> list[float]: ...


def plonger_documents(port: PortEmbeddings, textes: Sequence[str]) -> list[list[float]]:
    """Vecteurs normalisés et validés d'une liste de textes : la sortie d'un adaptateur n'est jamais crue."""
    profil = port.profil()
    try:
        brut = port.plonger_documents(list(textes))
    except ErreurConnaissances:
        raise
    except Exception as exc:  # noqa: BLE001 — la panne d'un adaptateur ne doit jamais fuir son contenu
        raise ErreurConnaissances(EMBEDDINGS_INVALIDE,
            f"adaptateur d'embeddings en échec ({type(exc).__name__})") from None
    if not isinstance(brut, (list, tuple)) or len(brut) != len(textes):
        raise ErreurConnaissances(EMBEDDINGS_INVALIDE, "un vecteur par texte était attendu")
    return [vecteurs.normaliser(vecteurs.valider(v, profil.dimension)) for v in brut]


def plonger_requete(port: PortEmbeddings, texte: str) -> list[float]:
    profil = port.profil()
    try:
        brut = port.plonger_requete(texte)
    except ErreurConnaissances:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErreurConnaissances(EMBEDDINGS_INVALIDE,
            f"adaptateur d'embeddings en échec ({type(exc).__name__})") from None
    return vecteurs.normaliser(vecteurs.valider(brut, profil.dimension))


def noter(port: PortReranker, requete: str, passages: Sequence[str]) -> list[float]:
    try:
        notes = port.noter(requete, list(passages))
    except Exception as exc:  # noqa: BLE001
        raise ErreurConnaissances(RERANKER_INVALIDE,
            f"adaptateur de reranker en échec ({type(exc).__name__})") from None
    if (not isinstance(notes, (list, tuple)) or len(notes) != len(passages)
            or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in notes)):
        raise ErreurConnaissances(RERANKER_INVALIDE, "une note finie par passage était attendue")
    return [float(n) for n in notes]


# -- résolution par le registre
# -----------------------------------------------------------------------------------------
FabriqueEmbeddings = Callable[[Fournisseur], PortEmbeddings]
FabriqueReranker = Callable[[Fournisseur], PortReranker]
# identifiant du fournisseur -> fabrique. VIDES en production dans cette tranche (voir la docstring du module).
_ADAPTATEURS_EMBEDDINGS: dict[str, FabriqueEmbeddings] = {}
_ADAPTATEURS_RERANKER: dict[str, FabriqueReranker] = {}


def _resoudre(cnx: Any, capacite: str, departement: str) -> Fournisseur:
    try:
        return registre.resoudre(cnx, capacite, departement).fournisseur
    except registre.RegistreErreur as exc:
        refus = f" ({', '.join(exc.codes)})" if exc.codes else ""
        raise ErreurConnaissances(
            FOURNISSEUR_REFUSE, f"registre de fournisseurs ({capacite}) : {exc.code}{refus} ; aucun repli"
        ) from None


def resoudre_embeddeur(cnx: Any, departement: str) -> PortEmbeddings:
    """Le port d'embeddings que le registre retient pour `departement`, vérifié contre sa configuration."""
    fournisseur = _resoudre(cnx, CAPACITE_EMBEDDINGS, departement)
    fabrique = _ADAPTATEURS_EMBEDDINGS.get(fournisseur.identifiant)
    if fabrique is None:  # rôle `embeddings` de la passerelle de modèles (rien d'affecté : None, comportement d'avant)
        from ..roles_modeles import adaptateurs

        fabrique = adaptateurs.fabrique_embeddings(cnx, fournisseur)
    if fabrique is None:
        raise ErreurConnaissances(
            EMBEDDINGS_NON_RACCORDE,
            f"{fournisseur.identifiant} est conforme mais aucun adaptateur d'embeddings n'y est raccordé dans cette "
            "tranche (aucun appel réseau) : recherche lexicale seulement",
        )
    port = fabrique(fournisseur)
    profil = port.profil()
    if profil.fournisseur_id != fournisseur.identifiant or profil.config_sha256 != empreinte_configuration(fournisseur):
        raise ErreurConnaissances(
            EMBEDDINGS_INVALIDE,
            "le profil de l'adaptateur ne correspond pas à la configuration du fournisseur dans le registre",
        )
    return port


def resoudre_reranker(cnx: Any, departement: str) -> PortReranker:
    fournisseur = _resoudre(cnx, CAPACITE_RERANKER, departement)
    fabrique = _ADAPTATEURS_RERANKER.get(fournisseur.identifiant)
    if fabrique is None:
        from ..roles_modeles import adaptateurs

        fabrique = adaptateurs.fabrique_reranker(cnx, fournisseur)
    if fabrique is None:
        raise ErreurConnaissances(
            EMBEDDINGS_NON_RACCORDE,
                f"{fournisseur.identifiant} est conforme mais aucun adaptateur de reranker n'y est "
            "raccordé dans cette tranche")
    port = fabrique(fournisseur)
    identite = port.identite()
    if (identite.fournisseur_id != fournisseur.identifiant
            or identite.config_sha256 != empreinte_configuration(fournisseur)):
        raise ErreurConnaissances(
            RERANKER_INVALIDE, "l'identité de l'adaptateur ne correspond pas à la configuration du registre")
    return port


def embeddeur_disponible(cnx: Any, departement: str) -> tuple[PortEmbeddings | None, ErreurConnaissances | None]:
    """`(port, None)` ou `(None, refus)` : le refus est rendu à l'appelant, qui le dit dans la réponse, jamais avalé."""
    try:
        return resoudre_embeddeur(cnx, departement), None
    except ErreurConnaissances as exc:
        return None, exc


def reranker_disponible(cnx: Any, departement: str) -> tuple[PortReranker | None, ErreurConnaissances | None]:
    """Le reranker est FACULTATIF : aucun fournisseur sélectionné n'est pas un avertissement. Un fournisseur sélectionné
    mais refusé (inactif, non conforme) ou non raccordé l'est : il est rendu à l'appelant."""
    try:
        return resoudre_reranker(cnx, departement), None
    except ErreurConnaissances as exc:
        if exc.code == FOURNISSEUR_REFUSE and "AUCUN_FOURNISSEUR" in exc.detail:
            return None, None
        return None, exc
