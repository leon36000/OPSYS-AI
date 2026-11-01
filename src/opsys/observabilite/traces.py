"""Traces d'exécution des agents : modèle de span, journal local append-only à chaîne d'intégrité, traceur masquant.

Une trace regroupe des `Span` : un **tour d'agent** (`tour_agent` : modèle, jetons, coût estimé) et chaque **appel
d'outil** (`appel_outil` : département, agent, outil, niveau d'approbation, durée, issue, code de refus, lien vers la
demande d'approbation). Un `refus_mcp` consigne un refus du registre MCP (dérive d'empreinte, Rule of Two).

Garanties, prouvées par `tests/test_traces_journal.py` :
- **masquage AVANT écriture** : tout texte d'un span passe par un `MasqueurPII` avant d'être sérialisé ; les champs
  d'identifiants sont de plus validés par forme (un champ qui ne ressemble pas à son identifiant est écarté) ;
- **pas de contenu** : un span n'a ni corps de courriel, ni prompt, ni sortie d'outil. Les `attributs` libres sont
bornés
  (20 clés, 200 caractères) et une clé qui nomme un contenu (`corps`, `contenu`, `prompt`, `sortie`…) est refusée ;
- **append-only** : un fichier par jour UTC (`traces-AAAAMMJJ.jsonl`, 0600), écrit en `O_APPEND` sous verrou ; chaque
  enregistrement porte `seq`, `prev` et `h` = HMAC-SHA256 (clé locale, usage `traces/chaine/v1`) du précédent : toute
  modification, suppression ou insertion au milieu est détectée par `verifier()` ;
- **rétention bornée** : au plus `retention_jours` jours et `taille_max_octets` octets ; le dépassement supprime les
  plus anciens SEGMENTS ENTIERS (jamais une ligne), et chaque purge est consignée dans `purges.jsonl` ;
- **la télémétrie ne casse jamais l'appel** : une panne d'écriture est journalisée (classe d'exception seulement) et
  l'outil continue.

Limites : une chaîne HMAC détecte l'altération par quelqu'un qui n'a pas la clé locale, pas la troncature de la FIN du
journal ni sa réécriture complète par un processus qui lit la clé. Le journal n'est pas dans l'export d'instance
(`exportation.py` : liste blanche fermée) : c'est de la télémétrie, pas une donnée d'affaires.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import cle_locale
from .erreurs import ErreurObservabilite
from .pii import CLE_SECRETE, MasqueurPII

try:  # verrou inter-processus POSIX ; ailleurs : verrou de processus seulement (limite documentée)
    import fcntl
except ImportError:  # pragma: no cover — Windows
    fcntl = None  # type: ignore[assignment]

_LOG = logging.getLogger(__name__)

VERSION_FORMAT = 1
TYPES_SPAN = ("appel_outil", "tour_agent", "refus_mcp")
ISSUES = ("ok", "refus", "attente_approbation", "erreur")
NIVEAUX = ("N0", "N1", "N2", "N3", "N4", "N5")
LIGNE_MAX = 16_384
ATTRIBUTS_MAX = 20
VALEUR_ATTRIBUT_MAX = 200
RETENTION_JOURS_DEFAUT = 30
TAILLE_MAX_DEFAUT = 256 * 1024 * 1024
_SEGMENT = re.compile(r"^traces-(\d{8})\.jsonl$")
_HEX = re.compile(r"^[0-9a-f]{16,64}$")
_OUTIL = re.compile(r"^(?:m(?:10|[1-9])|opsys)_[a-z][a-z0-9_]{1,60}$")
_DEPARTEMENT = re.compile(r"^(?:m(?:0[1-9]|10)-[a-z0-9-]{1,40}|opsys)$")
_AGENT = re.compile(r"^[a-z][a-z0-9_:-]{1,63}$")
_CODE = re.compile(r"^(?:REJ-[A-Z0-9-]{2,80}|REFUS-[A-Z0-9-]{2,60}|[a-z][a-z0-9_]{1,60})$")
_LIEN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_MODELE = re.compile(r"^[A-Za-z0-9_.:/-]{1,80}$")
_CLE_ATTRIBUT = re.compile(r"^[a-z][a-z0-9_.]{0,47}$")
# Une clé d'attribut qui nomme un CONTENU est refusée, quel que soit ce qu'elle contient.
_CLES_CONTENU = re.compile(
    r"(?:^|[_.])(?:corps|contenu|content|body|texte|text|message|courriel|email|mail|prompt|sortie|output|reponse|"
    r"response|input|entree|arguments|resultat|result|piece_jointe|attachment|transcription)(?:$|[_.])"
)


@dataclasses.dataclass(frozen=True)
class Tarif:
    """Prix d'un modèle en USD par million de jetons. Fourni par la configuration : aucun prix n'est codé ici."""

    modele: str
    entree_usd_par_million: Decimal
    sortie_usd_par_million: Decimal


def estimer_cout(jetons_entree: int | None, jetons_sortie: int | None, tarif: Tarif | None) -> Decimal | None:
    """Coût estimé en USD (6 décimales), ou None si les jetons ou le tarif sont inconnus : jamais une valeur
    inventée."""
    if tarif is None or jetons_entree is None or jetons_sortie is None:
        return None
    total = (Decimal(jetons_entree) * tarif.entree_usd_par_million
             + Decimal(jetons_sortie) * tarif.sortie_usd_par_million)
    return (total / Decimal(1_000_000)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)


@dataclasses.dataclass(frozen=True)
class Span:
    trace_id: str
    span_id: str
    type: str
    debut: str  # ISO 8601 UTC, millisecondes, suffixe Z
    duree_ms: int
    departement: str
    agent: str
    issue: str
    parent_id: str | None = None
    outil: str | None = None
    niveau: str | None = None
    code_refus: str | None = None
    approbation_id: str | None = None
    jetons_entree: int | None = None
    jetons_sortie: int | None = None
    cout_estime_usd: str | None = None  # Decimal en chaîne : jamais un flottant
    modele: str | None = None
    attributs: Mapping[str, str | int | bool] = dataclasses.field(default_factory=dict)

    def vers_dict(self) -> dict[str, Any]:
        donnees = dataclasses.asdict(self)
        donnees["attributs"] = dict(self.attributs)
        return donnees

    @classmethod
    def depuis_dict(cls, donnees: Mapping[str, Any]) -> Span:
        champs = {f.name for f in dataclasses.fields(cls)}
        inconnus = set(donnees) - champs
        if inconnus:
            raise ErreurObservabilite("REJ-OBS-TRACE-INVALIDE", f"champs inconnus : {sorted(inconnus)}")
        return cls(**{k: donnees[k] for k in donnees})


def instant_iso(maintenant: dt.datetime) -> str:
    return maintenant.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{maintenant.microsecond // 1000:03d}Z"


def _entier_borne(valeur: Any, maximum: int = 2**40) -> int | None:
    return valeur if type(valeur) is int and 0 <= valeur <= maximum else None


def _forme(valeur: Any, motif: re.Pattern[str]) -> str | None:
    return valeur if isinstance(valeur, str) and motif.fullmatch(valeur) else None


def _canonique(donnees: Any) -> str:
    return json.dumps(donnees, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


# --- Journal -------------------------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Enregistrement:
    segment: str
    seq: int
    span: Span


@dataclasses.dataclass(frozen=True)
class RapportIntegrite:
    ok: bool
    segments: int
    enregistrements: int
    problemes: tuple[str, ...] = ()


class JournalTraces:
    """Journal local append-only (un fichier JSONL par jour UTC) à chaîne d'intégrité HMAC et rétention bornée."""

    def __init__(self, dossier: Path, cle: bytes, *, retention_jours: int = RETENTION_JOURS_DEFAUT,
                 taille_max_octets: int = TAILLE_MAX_DEFAUT,
                 maintenant: Callable[[], dt.datetime] | None = None) -> None:
        if not isinstance(cle, bytes) or len(cle) != 32:
            raise ErreurObservabilite("REJ-OBS-CLE-INVALIDE",
                                      "clé de chaîne : 32 octets attendus (usage traces/chaine/v1)")
        if not 1 <= retention_jours <= 3650 or not 1 <= taille_max_octets <= 2**42:
            raise ErreurObservabilite("REJ-OBS-JOURNAL-RETENTION", "rétention hors bornes (1–3650 jours, taille > 0)")
        self.dossier = Path(dossier)
        self._cle = cle
        self.retention_jours = retention_jours
        self.taille_max_octets = taille_max_octets
        self._maintenant = maintenant or (lambda: dt.datetime.now(dt.UTC))
        self._verrou = threading.Lock()
        self._lecture_seule = False

    @classmethod
    def lecture_seule(cls, dossier: Path) -> JournalTraces:
        """Journal ouvert pour LIRE seulement (console, tableaux) : sans clé, il ne peut ni écrire, ni purger, ni
        vérifier."""
        journal = cls(dossier, b"\0" * 32)
        journal._lecture_seule = True
        return journal

    def _exiger_ecriture(self) -> None:
        if self._lecture_seule:
            raise ErreurObservabilite("REJ-OBS-ARGUMENT-INVALIDE", "journal ouvert en lecture seule")

    def __repr__(self) -> str:
        return f"JournalTraces({str(self.dossier)!r})"

    # -- fichiers --------------------------------------------------------------------------------------------------
    def _preparer(self) -> None:
        self.dossier.mkdir(mode=0o700, parents=True, exist_ok=True)

    def segments(self) -> list[Path]:
        if not self.dossier.is_dir():
            return []
        return sorted(p for p in self.dossier.iterdir()
                      if _SEGMENT.match(p.name) and p.is_file() and not p.is_symlink())

    def _chaine(self, prev: str, seq: int, span: Mapping[str, Any]) -> str:
        charge = f"{prev}|{seq}|{_canonique(span)}".encode()
        return hmac.new(self._cle, charge, hashlib.sha256).hexdigest()

    @staticmethod
    def _derniere_ligne(chemin: Path) -> dict[str, Any] | None:
        try:
            taille = chemin.stat().st_size
        except FileNotFoundError:
            return None
        with chemin.open("rb") as f:
            f.seek(max(0, taille - 2 * LIGNE_MAX))
            lignes = [ligne for ligne in f.read().split(b"\n") if ligne.strip()]
        for ligne in reversed(lignes):
            try:
                enr = json.loads(ligne)
            except ValueError:
                continue
            if isinstance(enr, dict) and isinstance(enr.get("h"), str) and type(enr.get("seq")) is int:
                return enr
        return None

    @contextlib.contextmanager
    def _verrou_fichier(self) -> Iterator[None]:
        with self._verrou:
            self._preparer()
            if fcntl is None:  # pragma: no cover — Windows
                yield
                return
            descripteur = os.open(self.dossier / ".verrou", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(descripteur, fcntl.LOCK_EX)
                yield
            finally:
                os.close(descripteur)  # libère aussi le verrou

    # -- écriture --------------------------------------------------------------------------------------------------
    def ajouter(self, span: Span) -> Enregistrement:
        """Ajoute un span DÉJÀ MASQUÉ (le traceur masque ; le journal refuse seulement ce qui est trop gros)."""
        self._exiger_ecriture()
        donnees = span.vers_dict()
        maintenant = self._maintenant()
        nom = f"traces-{maintenant.astimezone(dt.UTC):%Y%m%d}.jsonl"
        with self._verrou_fichier():
            chemin = self.dossier / nom
            nouveau_segment = not chemin.exists()
            if nouveau_segment:
                precedents = [p for p in self.segments() if p.name < nom]
                derniere = self._derniere_ligne(precedents[-1]) if precedents else None
                prev = derniere["h"] if derniere else "0" * 64
                seq = 1
            else:
                derniere = self._derniere_ligne(chemin)
                prev, seq = (derniere["h"], derniere["seq"] + 1) if derniere else ("0" * 64, 1)
            ligne = _canonique({"v": VERSION_FORMAT, "seq": seq, "prev": prev, "span": donnees,
                                "h": self._chaine(prev, seq, donnees)}) + "\n"
            if len(ligne.encode()) > LIGNE_MAX:
                raise ErreurObservabilite("REJ-OBS-TRACE-INVALIDE", "enregistrement trop gros pour le journal")
            descripteur = os.open(chemin, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                if not nouveau_segment and chemin.stat().st_size and not self._finit_par_saut_de_ligne(chemin):
                    os.write(descripteur, b"\n")  # écriture interrompue avant : on isole la ligne tronquée
                os.write(descripteur, ligne.encode())
            finally:
                os.close(descripteur)
            if nouveau_segment:
                self._appliquer_retention_sous_verrou(maintenant)
        return Enregistrement(nom, seq, span)

    @staticmethod
    def _finit_par_saut_de_ligne(chemin: Path) -> bool:
        with chemin.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            return f.read(1) == b"\n"

    # -- lecture ---------------------------------------------------------------------------------------------------
    def lire(self) -> Iterator[Enregistrement]:
        """Tous les enregistrements lisibles, du plus ancien au plus récent (une ligne illisible est ignorée ici ;
        `verifier()` la signale)."""
        for chemin in self.segments():
            with chemin.open("rb") as f:
                for ligne in f:
                    try:
                        enr = json.loads(ligne)
                        yield Enregistrement(chemin.name, int(enr["seq"]), Span.depuis_dict(enr["span"]))
                    except (ValueError, KeyError, TypeError, ErreurObservabilite):
                        continue

    def verifier(self) -> RapportIntegrite:
        """Relit la chaîne HMAC de bout en bout. Le premier segment peut commencer après un segment purgé."""
        self._exiger_ecriture()  # la vérification de la chaîne exige la clé
        problemes: list[str] = []
        total = 0
        precedent_h: str | None = None
        segments = self.segments()
        for chemin in segments:
            attendu_seq = 1
            with chemin.open("rb") as f:
                lignes = f.read().split(b"\n")
            for numero, brut in enumerate(lignes, 1):
                if not brut.strip():
                    continue
                try:
                    enr = json.loads(brut)
                    seq, prev, h, span = enr["seq"], enr["prev"], enr["h"], enr["span"]
                    if type(seq) is not int or not isinstance(prev, str) or not isinstance(h, str):
                        raise ValueError("types")
                except (ValueError, KeyError, TypeError):
                    problemes.append(f"{chemin.name}:{numero}: ligne illisible ou tronquée")
                    precedent_h = None
                    continue
                if seq != attendu_seq:
                    problemes.append(f"{chemin.name}:{numero}: séquence {seq} au lieu de {attendu_seq}")
                    attendu_seq = seq
                if precedent_h is not None and prev != precedent_h:
                    problemes.append(f"{chemin.name}:{numero}: maillon précédent rompu")
                if not hmac.compare_digest(self._chaine(prev, seq, span), h):
                    problemes.append(f"{chemin.name}:{numero}: empreinte invalide (enregistrement modifié)")
                precedent_h, attendu_seq, total = h, attendu_seq + 1, total + 1
        return RapportIntegrite(not problemes, len(segments), total, tuple(problemes))

    # -- rétention -------------------------------------------------------------------------------------------------
    def appliquer_retention(self, *, a_blanc: bool = False) -> list[str]:
        """Supprime les segments hors rétention (âge, puis taille totale), jamais le segment du jour. Rend leurs
        noms."""
        self._exiger_ecriture()
        with self._verrou_fichier():
            return self._appliquer_retention_sous_verrou(self._maintenant(), a_blanc=a_blanc)

    def _appliquer_retention_sous_verrou(self, maintenant: dt.datetime, *, a_blanc: bool = False) -> list[str]:
        aujourd_hui = maintenant.astimezone(dt.UTC).date()
        limite = aujourd_hui - dt.timedelta(days=self.retention_jours)
        segments = self.segments()
        a_supprimer: list[tuple[Path, str]] = []
        restants = []
        for chemin in segments:
            jour = dt.datetime.strptime(_SEGMENT.match(chemin.name).group(1), "%Y%m%d").date()  # type: ignore[union-attr]
            if jour < limite:
                a_supprimer.append((chemin, "age"))
            else:
                restants.append(chemin)
        taille = sum(p.stat().st_size for p in restants)
        while len(restants) > 1 and taille > self.taille_max_octets:
            ancien = restants.pop(0)
            taille -= ancien.stat().st_size
            a_supprimer.append((ancien, "taille"))
        noms = [chemin.name for chemin, _ in a_supprimer]
        if a_blanc or not a_supprimer:
            return noms
        derniere = self._derniere_ligne(a_supprimer[-1][0])
        with (self.dossier / "purges.jsonl").open("ab") as f:
            os.chmod(f.fileno(), 0o600)
            f.write((_canonique({"quand": instant_iso(maintenant), "segments": noms,
                                 "raisons": sorted({r for _, r in a_supprimer}),
                                 "dernier_maillon": derniere["h"] if derniere else None}) + "\n").encode())
        for chemin, _ in a_supprimer:
            chemin.unlink()
        return noms

    def purges(self) -> list[dict[str, Any]]:
        chemin = self.dossier / "purges.jsonl"
        if not chemin.is_file():
            return []
        return [json.loads(ligne) for ligne in chemin.read_text(encoding="utf-8").splitlines() if ligne.strip()]


# --- Traceur ---------------------------------------------------------------------------------------------------------

class SpanEnCours:
    """Ce qu'un appelant renseigne pendant qu'un span est ouvert ; le traceur le fige, le masque et l'écrit à la
    sortie."""

    def __init__(self) -> None:
        self.issue = "ok"
        self.code_refus: str | None = None
        self.approbation_id: str | None = None
        self.jetons_entree: int | None = None
        self.jetons_sortie: int | None = None
        self.modele: str | None = None
        self.cout_usd: Decimal | None = None
        self.attributs: dict[str, Any] = {}

    def conclure(self, issue: str, *, code: str | None = None, approbation_id: str | None = None) -> None:
        self.issue, self.code_refus, self.approbation_id = issue, code, approbation_id

    def jetons(self, entree: int | None, sortie: int | None, *, modele: str | None = None,
               cout_usd: Decimal | None = None) -> None:
        self.jetons_entree, self.jetons_sortie, self.modele, self.cout_usd = entree, sortie, modele, cout_usd

    def attribut(self, cle: str, valeur: Any) -> None:
        self.attributs[cle] = valeur


class Traceur:
    """Fabrique et écrit des spans : mesure la durée, estime le coût, MASQUE, valide, puis écrit."""

    def __init__(self, journal: JournalTraces, masqueur: MasqueurPII, *, tarifs: Mapping[str, Tarif] | None = None,
                 maintenant: Callable[[], dt.datetime] | None = None, chrono: Callable[[], float] = time.perf_counter,
                 nouvel_id: Callable[[int], str] | None = None) -> None:
        if not isinstance(masqueur, MasqueurPII):
            raise ErreurObservabilite("REJ-OBS-MASQUEUR", "un masqueur conforme à MasqueurPII est obligatoire")
        self.journal, self.masqueur = journal, masqueur
        self._tarifs = dict(tarifs or {})
        self._maintenant = maintenant or (lambda: dt.datetime.now(dt.UTC))
        self._chrono = chrono
        self._id = nouvel_id or (lambda n: uuid.uuid4().hex[:n])
        self.ecartes = 0  # champs ou attributs écartés par la validation (jamais leur valeur)

    # -- nettoyage : masquer, puis valider par forme ------------------------------------------------------------------
    def _masquer(self, texte: Any) -> Any:
        return self.masqueur.masquer(texte).texte if isinstance(texte, str) else texte

    def nettoyer(self, span: Span) -> Span:
        """Copie du span dont chaque texte est masqué puis validé. Un champ de forme inattendue est écarté (None)."""
        if span.type not in TYPES_SPAN or span.issue not in ISSUES:
            raise ErreurObservabilite("REJ-OBS-TRACE-INVALIDE", "type ou issue de span inconnu")
        ecartes = 0

        def champ(valeur: Any, motif: re.Pattern[str]) -> str | None:
            nonlocal ecartes
            if valeur is None:
                return None
            masque = _forme(self._masquer(valeur), motif)
            if masque is None:
                ecartes += 1
            return masque

        attributs: dict[str, str | int | bool] = {}
        for cle, valeur in list(span.attributs.items())[:ATTRIBUTS_MAX]:
            if (not isinstance(cle, str) or not _CLE_ATTRIBUT.fullmatch(cle) or _CLES_CONTENU.search(cle)
                    or CLE_SECRETE.search(cle)
                    or not isinstance(valeur, (str, int, bool))):
                ecartes += 1
                continue
            if isinstance(valeur, str):
                valeur = self._masquer(valeur)[:VALEUR_ATTRIBUT_MAX]  # on masque AVANT de couper
            attributs[cle] = valeur
        ecartes += max(0, len(span.attributs) - ATTRIBUTS_MAX)
        self.ecartes += ecartes
        niveau = span.niveau if span.niveau in NIVEAUX else None
        cout = None
        if span.cout_estime_usd is not None:
            try:
                cout = str(Decimal(span.cout_estime_usd).quantize(Decimal("0.000001")))
            except (InvalidOperation, ValueError):
                cout = None
        return dataclasses.replace(
            span,
            trace_id=_forme(span.trace_id, _HEX) or self._id(32), span_id=_forme(span.span_id, _HEX) or self._id(16),
            parent_id=_forme(span.parent_id, _HEX), outil=champ(span.outil, _OUTIL),
            departement=champ(span.departement, _DEPARTEMENT) or "inconnu",
            agent=champ(span.agent, _AGENT) or "inconnu", niveau=niveau, code_refus=champ(span.code_refus, _CODE),
            approbation_id=champ(span.approbation_id, _LIEN), modele=champ(span.modele, _MODELE),
            jetons_entree=_entier_borne(span.jetons_entree), jetons_sortie=_entier_borne(span.jetons_sortie),
            duree_ms=_entier_borne(span.duree_ms, 2**31) or 0, cout_estime_usd=cout, attributs=attributs,
        )

    def enregistrer(self, span: Span) -> Span | None:
        """Masque, valide, écrit. Ne lève JAMAIS vers l'appelant : une panne de télémétrie ne casse pas un outil."""
        try:
            propre = self.nettoyer(span)
            self.journal.ajouter(propre)
            return propre
        except Exception as exc:  # noqa: BLE001 — la télémétrie échoue en silence côté appelant, pas dans le journal d'erreurs
            _LOG.warning("trace non enregistrée (%s)", type(exc).__name__)
            return None

    # -- fabriques --------------------------------------------------------------------------------------------------
    @contextlib.contextmanager
    def _span(self, type_: str, *, departement: str, agent: str, outil: str | None, niveau: str | None,
              trace_id: str | None, parent_id: str | None) -> Iterator[SpanEnCours]:
        en_cours = SpanEnCours()
        debut = self._maintenant()
        t0 = self._chrono()
        try:
            yield en_cours
        except BaseException as exc:
            en_cours.issue = "erreur"
            en_cours.code_refus = "exception_" + re.sub(r"[^a-z0-9]+", "_", type(exc).__name__.lower())[:40]
            raise
        finally:
            duree = max(0, int((self._chrono() - t0) * 1000))
            tarif = self._tarifs.get(en_cours.modele or "")
            cout = en_cours.cout_usd if en_cours.cout_usd is not None else estimer_cout(
                en_cours.jetons_entree, en_cours.jetons_sortie, tarif)
            self.enregistrer(Span(
                trace_id=trace_id or self._id(32), span_id=self._id(16), parent_id=parent_id, type=type_,
                debut=instant_iso(debut), duree_ms=duree, departement=departement, agent=agent, outil=outil,
                niveau=niveau, issue=en_cours.issue, code_refus=en_cours.code_refus,
                approbation_id=en_cours.approbation_id, jetons_entree=en_cours.jetons_entree,
                jetons_sortie=en_cours.jetons_sortie, cout_estime_usd=str(cout) if cout is not None else None,
                modele=en_cours.modele, attributs=dict(en_cours.attributs)))

    def appel_outil(self, *, outil: str, departement: str, agent: str, niveau: str | None,
                    trace_id: str | None = None, parent_id: str | None = None):
        return self._span("appel_outil", departement=departement, agent=agent, outil=outil, niveau=niveau,
                          trace_id=trace_id, parent_id=parent_id)

    def tour_agent(self, *, departement: str, agent: str, trace_id: str | None = None, parent_id: str | None = None):
        return self._span("tour_agent", departement=departement, agent=agent, outil=None, niveau=None,
                          trace_id=trace_id, parent_id=parent_id)

    def refus(self, *, outil: str | None, departement: str, agent: str, niveau: str | None, code: str,
              attributs: Mapping[str, Any] | None = None) -> Span | None:
        """Consigne un refus du registre MCP (dérive, Rule of Two) comme span `refus_mcp`."""
        return self.enregistrer(Span(
            trace_id=self._id(32), span_id=self._id(16), type="refus_mcp", debut=instant_iso(self._maintenant()),
            duree_ms=0, departement=departement, agent=agent, outil=outil, niveau=niveau, issue="refus",
            code_refus=code, attributs=dict(attributs or {})))


def traceur_local(dossier: Path | None = None, *, masqueur: MasqueurPII | None = None, retention_jours: int =
                  RETENTION_JOURS_DEFAUT, tarifs: Mapping[str, Tarif] | None = None) -> Traceur:
    """Traceur de l'instance : journal sous `<OPSYS_HOME>/traces`, clés dérivées de la clé locale (créée au besoin)."""
    from ..stockage.moteur import dossier_opsys
    from .pii import MasqueurMotifs

    graine = cle_locale.charger(creer=True)
    journal = JournalTraces(dossier or dossier_opsys() / "traces", cle_locale.deriver(graine, "traces/chaine/v1"),
                            retention_jours=retention_jours)
    return Traceur(journal, masqueur or MasqueurMotifs(cle_locale.deriver(graine, "pii/v1")), tarifs=tarifs)


def lire_spans(journal: JournalTraces, *, depuis: str | None = None) -> list[Span]:
    """Spans du journal (option : depuis un instant ISO), du plus ancien au plus récent."""
    return [e.span for e in journal.lire() if depuis is None or e.span.debut >= depuis]

