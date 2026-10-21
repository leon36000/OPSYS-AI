"""Admission locale, explicite et traçable de procédures internes Markdown/TXT."""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import MemoireEntreprise

OCTETS_MAX = 1_048_576
CHUNKS_MAX = 100
INDEXATION_LOT_MAX = 5
TAILLE_CHUNK_MAX = 12_000
EXTRACTEUR_VERSION = "procedures-1"


@dataclasses.dataclass(frozen=True)
class Chunk:
    texte: str
    debut_octets: int
    fin_octets: int
    ligne_debut: int
    ligne_fin: int
    section: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Admission:
    document_id: str
    sha256: str
    version_id: int
    etat: str


@dataclasses.dataclass(frozen=True)
class EtatDocument:
    document_id: str
    etat: str
    courante: str | None


@dataclasses.dataclass(frozen=True)
class VersionResume:
    sha256: str
    version: int
    etat: str
    auteur: str
    admise_le: str
    active: bool
    octets: int


@dataclasses.dataclass(frozen=True)
class PageSeries:
    total: int
    series: tuple[dict[str, object], ...]


@dataclasses.dataclass(frozen=True)
class SourceLot:
    position: int
    titre: str
    sha256: str
    serie_cible_id: str | None = None


@dataclasses.dataclass(frozen=True)
class EmplacementLot:
    position: int
    titre: str
    sha256: str
    serie_cible_id: str | None
    document_id: str | None
    etat: str
    active: bool


@dataclasses.dataclass(frozen=True)
class LotProcedure:
    cle_lot: str
    auteur: str
    emplacements: tuple[EmplacementLot, ...]


@dataclasses.dataclass(frozen=True)
class ResumeLot:
    reference: str
    nombre_emplacements: int
    attente: int
    recu: int
    indexe: int
    actifs: int


@dataclasses.dataclass(frozen=True)
class Position:
    debut_octets: int
    fin_octets: int
    ligne_debut: int
    ligne_fin: int
    section: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class CitationVerifiee:
    document_id: str
    sha256: str
    extracteur: str
    auteur_admission: str
    nombre_occurrences: int
    positions: tuple[Position, ...]


def _octets_jusqua(texte: str, caractere: int) -> int:
    return len(texte[:caractere].encode("utf-8"))


def extraire(contenu: bytes) -> tuple[Chunk, ...]:
    if not isinstance(contenu, bytes) or not contenu:
        raise ValueError("fichier UTF-8 non vide attendu")
    if len(contenu) > OCTETS_MAX:
        raise ValueError("source supérieure à 1 MiB")
    try:
        texte = contenu.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("source invalide : UTF-8 strict attendu") from exc
    if "\x00" in texte:
        raise ValueError("caractère NUL interdit")
    # Les entêtes sont gardées comme contexte, tandis que les plages citées sont du texte exact du corps.
    lignes = texte.splitlines(keepends=True)
    chunks: list[Chunk] = []
    section: list[str] = []
    niveaux_section: list[int] = []
    paragraph_start: int | None = None
    char_offset = 0

    def emettre() -> None:
        nonlocal paragraph_start
        if paragraph_start is None:
            return
        brut = texte[paragraph_start:char_offset]
        gauche = len(brut) - len(brut.lstrip())
        droit = len(brut.rstrip())
        propre = brut[gauche:droit]
        if propre:
            debut_char = paragraph_start + gauche
            fin_char = paragraph_start + droit
            while debut_char < fin_char:
                if len(chunks) >= CHUNKS_MAX:
                    raise ValueError("source doit produire de 1 à 100 chunks")
                fin_bout = min(fin_char, debut_char + TAILLE_CHUNK_MAX)
                if fin_bout < fin_char:
                    coupe = texte.rfind(" ", debut_char, fin_bout)
                    if coupe > debut_char:
                        fin_bout = coupe
                morceau = texte[debut_char:fin_bout]
                a = _octets_jusqua(texte, debut_char)
                b = a + len(morceau.encode("utf-8"))
                chunks.append(Chunk(unicodedata.normalize("NFC", morceau), a, b,
                                    contenu[:a].count(b"\n") + 1,
                                    contenu[:max(a, b - 1)].count(b"\n") + 1, tuple(section)))
                debut_char = fin_bout
                while debut_char < fin_char and texte[debut_char].isspace():
                    debut_char += 1
        paragraph_start = None

    for ligne in lignes:
        contenu_ligne = ligne.rstrip("\r\n")
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", contenu_ligne)
        if heading:
            emettre()
            if len(heading.group(2).strip()) > 300:
                raise ValueError("titre de section supérieur à 300 caractères")
            niveau = len(heading.group(1))
            while niveaux_section and niveaux_section[-1] >= niveau:
                niveaux_section.pop()
                section.pop()
            niveaux_section.append(niveau)
            section.append(heading.group(2).strip())
        elif contenu_ligne.strip():
            if paragraph_start is None:
                paragraph_start = char_offset
        else:
            emettre()
        char_offset += len(ligne)
    emettre()
    if not chunks or len(chunks) > CHUNKS_MAX:
        raise ValueError("source doit produire de 1 à 100 chunks")
    return tuple(chunks)


class IngestionProcedures:
    """Façade spécifique M03; toute persistance transactionnelle est dans MemoireEntreprise."""

    def __init__(self, memoire: MemoireEntreprise) -> None:
        self._memoire = memoire

    def admettre(self, contenu: bytes, titre: str, *, auteur: str, cle_admission: str,
                 document_id: str | None = None) -> Admission:
        return self._memoire._admettre_procedure(contenu, titre, auteur=auteur,
                                                  cle_admission=cle_admission, document_id=document_id)

    def creer_lot(self, cle_lot: str, sources: Sequence[SourceLot], *, auteur: str) -> LotProcedure:
        return self._memoire._creer_lot_procedure(cle_lot, sources, auteur=auteur)

    def admettre_emplacement(self, cle_lot: str, position: int, contenu: bytes, *, auteur: str) -> LotProcedure:
        return self._memoire._admettre_emplacement_lot(cle_lot, position, contenu, auteur=auteur)

    def lire_lot(self, cle_lot: str, *, auteur: str) -> LotProcedure:
        return self._memoire._lire_lot_procedure(cle_lot, auteur=auteur)

    def lister_lots(self, *, auteur: str) -> tuple[ResumeLot, ...]:
        return self._memoire._lister_lots_procedure(auteur=auteur)

    def lire_lot_reference(self, reference: str, *, auteur: str) -> LotProcedure:
        return self._memoire._lire_lot_reference(reference, auteur=auteur)

    def admettre_emplacement_reference(
        self, reference: str, position: int, contenu: bytes, *, auteur: str,
    ) -> LotProcedure:
        return self._memoire._admettre_emplacement_lot_reference(
            reference, position, contenu, auteur=auteur
        )

    def lister_recues(self, *, limite: int = INDEXATION_LOT_MAX) -> tuple[tuple[str, str], ...]:
        """Liste au plus cinq versions reçues dans un ordre stable, sans lire leur contenu."""
        return self._memoire._lister_versions_procedure_recues(limite=limite)

    def indexer(self, document_id: str, sha256: str) -> EtatDocument:
        return self._memoire._indexer_procedure(document_id, sha256)

    def activer(self, document_id: str, sha256: str, *, attendu_sha256: str | None, auteur: str) -> None:
        self._memoire._activer_procedure(document_id, sha256, attendu_sha256=attendu_sha256, auteur=auteur)

    def lire_etat(self, document_id: str, *, absent_ok: bool = False) -> EtatDocument | None:
        return self._memoire._etat_procedure(document_id, absent_ok=absent_ok)

    def oublier(self, document_id: str, *, demandeur: str, motif: str) -> int:
        return self._memoire._oublier_procedure(document_id, demandeur=demandeur, motif=motif)

    def lister_series(self, *, limite: int = 50, offset: int = 0) -> PageSeries:
        return self._memoire._lister_series_procedure(limite=limite, offset=offset)

    def lister_versions(self, document_id: str) -> tuple[VersionResume, ...]:
        return self._memoire._lister_versions_procedure(document_id)
