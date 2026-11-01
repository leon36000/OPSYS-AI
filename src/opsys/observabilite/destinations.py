"""Export des traces vers une destination externe, derrière un port : double de test et adaptateur Langfuse (non
exécuté).

`DestinationTraces` est le contrat. Rien ici n'ouvre de connexion réseau : l'adaptateur Langfuse CONSTRUIT une requête
(`RequeteHTTP`) et la confie à un `TransportHTTP` fourni par l'appelant ; sans transport, il refuse
(`REJ-OBS-DESTINATION-NON-CONFIGUREE`). Le format du lot suit l'API d'ingestion publique de Langfuse telle que connue
(`POST /api/public/ingestion`, authentification Basic clé publique/clé secrète) ; il n'a JAMAIS été exécuté contre un
vrai Langfuse (voir docs/architecture/OBSERVABILITE-MCP.md, « Ce qui n'est pas prouvé »).

Garde de sortie : avant d'envoyer, `exporter` revérifie CHAQUE span avec le masqueur ; un span qui contiendrait encore
un
renseignement personnel n'est pas envoyé (`refuses_pii`). Le curseur n'avance qu'APRÈS un envoi réussi : un échec se
rejoue sans perte ni doublon (les identifiants d'événements sont déterministes, Langfuse déduplique).
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import json
import os
import urllib.parse
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .erreurs import ErreurObservabilite
from .pii import MasqueurPII
from .traces import JournalTraces, Span

_ESPACE_NOMS = uuid.UUID("6f0a2d8e-4a8b-5c1d-9e3f-0b7a1c2d3e4f")  # constante : identifiants déterministes
TAILLE_LOT_DEFAUT = 100


@runtime_checkable
class DestinationTraces(Protocol):
    nom: str

    def envoyer(self, spans: Sequence[Span]) -> None:
        """Envoie un lot ; lève `ErreurObservabilite("REJ-OBS-DESTINATION-REFUSEE")` si la destination ne l'a pas
        pris."""


class DestinationMemoire:
    """Double de test : garde les lots reçus ; `en_panne` simule une destination qui refuse."""

    nom = "memoire"

    def __init__(self) -> None:
        self.lots: list[list[Span]] = []
        self.en_panne = False

    def envoyer(self, spans: Sequence[Span]) -> None:
        if self.en_panne:
            raise ErreurObservabilite("REJ-OBS-DESTINATION-REFUSEE", "destination en panne (double de test)")
        self.lots.append(list(spans))

    @property
    def spans(self) -> list[Span]:
        return [s for lot in self.lots for s in lot]


@dataclasses.dataclass(frozen=True)
class RequeteHTTP:
    url: str
    methode: str
    entetes: dict[str, str] = dataclasses.field(repr=False)  # contient l'autorisation : jamais affiché
    corps: bytes = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class ReponseHTTP:
    statut: int


@runtime_checkable
class TransportHTTP(Protocol):
    def envoyer(self, requete: RequeteHTTP) -> ReponseHTTP: ...


def _iso_fin(span: Span) -> str:
    debut = dt.datetime.strptime(span.debut, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.UTC)
    fin = debut + dt.timedelta(milliseconds=span.duree_ms)
    return fin.strftime("%Y-%m-%dT%H:%M:%S.") + f"{fin.microsecond // 1000:03d}Z"


class DestinationLangfuse:
    """Traduit des spans en lot d'ingestion Langfuse. Non exécutée ici : le transport réel est à fournir et à
    qualifier."""

    nom = "langfuse"

    def __init__(self, url_base: str, cles: Callable[[], tuple[str, str]],
                 transport: TransportHTTP | None = None) -> None:
        analyse = urllib.parse.urlsplit(url_base)
        if (analyse.scheme not in ("http", "https") or not analyse.hostname or analyse.username or analyse.password
                or analyse.query or analyse.fragment):
            raise ErreurObservabilite("REJ-OBS-ARGUMENT-INVALIDE",
                                      "URL Langfuse : http(s)://hôte[:port][/chemin] sans identifiants ni requête")
        self._url = url_base.rstrip("/") + "/api/public/ingestion"
        self._cles, self._transport = cles, transport

    def __repr__(self) -> str:
        return f"DestinationLangfuse({self._url!r})"

    @staticmethod
    def _evenement(genre: str, span_id: str, horodatage: str, corps: dict[str, Any]) -> dict[str, Any]:
        return {"id": str(uuid.uuid5(_ESPACE_NOMS, f"{genre}:{span_id}")), "type": genre, "timestamp": horodatage,
                "body": corps}

    def construire_lot(self, spans: Sequence[Span]) -> dict[str, Any]:
        evenements: list[dict[str, Any]] = []
        traces_vues: set[str] = set()
        for s in spans:
            if s.trace_id not in traces_vues:
                traces_vues.add(s.trace_id)
                evenements.append(self._evenement("trace-create", s.trace_id, s.debut, {
                    "id": s.trace_id, "timestamp": s.debut, "name": s.outil or s.type, "tags": [s.departement],
                    "metadata": {"departement": s.departement, "agent": s.agent}}))
            meta = {"departement": s.departement, "agent": s.agent, "niveau": s.niveau, "issue": s.issue,
                    "code_refus": s.code_refus, "approbation_id": s.approbation_id,
                    "cout_estime_usd": s.cout_estime_usd, **dict(s.attributs)}
            niveau_log = {"ok": "DEFAULT", "attente_approbation": "WARNING", "refus": "WARNING",
                          "erreur": "ERROR"}[s.issue]
            commun = {"id": s.span_id, "traceId": s.trace_id, "parentObservationId": s.parent_id,
                      "name": s.outil or s.type, "startTime": s.debut, "endTime": _iso_fin(s), "metadata": meta,
                      "level": niveau_log, "statusMessage": s.code_refus}
            if s.type == "tour_agent":
                evenements.append(self._evenement("generation-create", s.span_id, s.debut, {
                    **commun, "model": s.modele,
                    "usage": {"input": s.jetons_entree, "output": s.jetons_sortie, "unit": "TOKENS"}}))
            else:
                evenements.append(self._evenement("span-create", s.span_id, s.debut, commun))
        return {"batch": evenements, "metadata": {"source": "opsys-observabilite/1"}}

    def construire_requete(self, spans: Sequence[Span]) -> RequeteHTTP:
        publique, secrete = self._cles()
        jeton = base64.b64encode(f"{publique}:{secrete}".encode()).decode("ascii")
        corps = json.dumps(self.construire_lot(spans), sort_keys=True, ensure_ascii=False).encode()
        return RequeteHTTP(self._url, "POST", {"Authorization": f"Basic {jeton}", "Content-Type": "application/json"},
                           corps)

    def envoyer(self, spans: Sequence[Span]) -> None:
        if self._transport is None:
            raise ErreurObservabilite("REJ-OBS-DESTINATION-NON-CONFIGUREE",
                                      "aucun transport HTTP configuré : Langfuse n'est pas branché sur cette instance")
        reponse = self._transport.envoyer(self.construire_requete(spans))
        if not 200 <= reponse.statut < 300:  # 207 (multi-statut) compris : le détail par événement n'est pas relu ici
            raise ErreurObservabilite("REJ-OBS-DESTINATION-REFUSEE", f"Langfuse a répondu {reponse.statut}")


# --- Export incrémental ----------------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class RapportExport:
    destination: str
    envoyes: int
    refuses_pii: int
    lots: int
    erreur: str | None = None


def _lire_curseur(chemin: Path) -> tuple[str, int] | None:
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        return str(donnees["segment"]), int(donnees["seq"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _ecrire_curseur(chemin: Path, segment: str, seq: int) -> None:
    chemin.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(f".{os.getpid()}.tmp")
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descripteur, json.dumps({"segment": segment, "seq": seq}).encode())
    finally:
        os.close(descripteur)
    os.replace(temporaire, chemin)


def exporter(journal: JournalTraces, destination: DestinationTraces, masqueur: MasqueurPII, *,
             taille_lot: int = TAILLE_LOT_DEFAUT, a_blanc: bool = False) -> RapportExport:
    """Envoie à `destination` les spans non encore exportés, par lots, puis avance le curseur (après succès
    seulement)."""
    if not 1 <= taille_lot <= 1000:
        raise ErreurObservabilite("REJ-OBS-ARGUMENT-INVALIDE", "taille de lot : 1 à 1000")
    chemin = journal.dossier / "curseurs" / f"{destination.nom}.json"
    depuis = _lire_curseur(chemin)
    en_attente = [e for e in journal.lire() if depuis is None or (e.segment, e.seq) > depuis]
    envoyes = refuses = lots = 0
    for debut in range(0, len(en_attente), taille_lot):
        morceau = en_attente[debut:debut + taille_lot]
        sains = [e for e in morceau
                 if not masqueur.contient_pii(json.dumps(e.span.vers_dict(), ensure_ascii=False, sort_keys=True))]
        refuses += len(morceau) - len(sains)
        if sains and not a_blanc:
            try:
                destination.envoyer([e.span for e in sains])
            except ErreurObservabilite as exc:
                return RapportExport(destination.nom, envoyes, refuses, lots, exc.code)
            lots += 1
        envoyes += len(sains)
        if not a_blanc:
            dernier = morceau[-1]
            _ecrire_curseur(chemin, dernier.segment, dernier.seq)
    return RapportExport(destination.nom, envoyes, refuses, lots)
