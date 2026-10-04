"""Transcription de voicemail par endpoint OpenAI-compatible, puis import canonique M1.

L'audio est gardé en mémoire le temps de l'appel STT et n'est jamais écrit par ce module. Une panne
STT n'invente pas de texte : l'événement voicemail est tout de même remis à l'import M1 sans
transcription, qui peut créer la tâche de rappel durable déjà prévue.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import secrets
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import wave
from collections.abc import Mapping
from io import BytesIO
from typing import Any, Protocol

from opsys import stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements

ENV_URL = "OPSYS_M1_STT_URL"
ENV_MODELE = "OPSYS_M1_STT_MODELE"
ENV_CLE = "OPSYS_M1_STT_CLE"
ENV_LOCAL = "OPSYS_M1_STT_LOCAL"
ENV_DELAI = "OPSYS_M1_STT_DELAI_S"
MAX_AUDIO_OCTETS = 25 * 1024 * 1024
MAX_DUREE_S = 300
MAX_TRANSCRIPTION_CARACTERES = 5000
_TYPES_AUDIO = {
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


class ErreurVoicemail(ValueError):
    """Refus nommé de validation audio, de consentement ou de transport STT."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


class ImporteurM1(Protocol):
    """Frontière d'import injectée par une interface humaine authentifiée, si présente."""

    def __call__(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...


class _RefuserRedirection(urllib.request.HTTPRedirectHandler):
    """Le fournisseur choisi ne peut pas réexpédier une clé ou un fichier vers une autre URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirection STT refusée", headers, fp)


def _ouvrir(requete: urllib.request.Request, delai_s: float):
    return urllib.request.build_opener(_RefuserRedirection()).open(requete, timeout=delai_s)


@dataclasses.dataclass(frozen=True)
class ConfigurationSTT:
    """Endpoint configuré par l'administrateur; aucun modèle ni fournisseur n'est deviné."""

    base_url: str
    modele: str
    cle_api: str | None = dataclasses.field(default=None, repr=False)
    local: bool = False
    delai_s: float = 45.0
    taille_max_octets: int = MAX_AUDIO_OCTETS
    duree_max_s: int = MAX_DUREE_S

    def __post_init__(self) -> None:
        url = self.base_url.strip().rstrip("/")
        parties = urllib.parse.urlsplit(url)
        if (
            parties.scheme not in {"http", "https"}
            or not parties.hostname
            or parties.username
            or parties.password
            or parties.query
            or parties.fragment
        ):
            raise ErreurVoicemail("REJ-STT-CONFIG", f"{ENV_URL} doit être une URL http(s) sans identifiants")
        if not self.local and parties.scheme != "https":
            raise ErreurVoicemail("REJ-STT-CONFIG", "un endpoint hors machine doit utiliser HTTPS")
        if not self.modele.strip():
            raise ErreurVoicemail("REJ-STT-CONFIG", f"{ENV_MODELE} doit nommer le modèle STT")
        if (
            isinstance(self.delai_s, bool)
            or not isinstance(self.delai_s, (int, float))
            or not math.isfinite(self.delai_s)
            or not 0 < self.delai_s <= 120
            or type(self.taille_max_octets) is not int
            or not 0 < self.taille_max_octets <= MAX_AUDIO_OCTETS
            or type(self.duree_max_s) is not int
            or not 0 < self.duree_max_s <= MAX_DUREE_S
        ):
            raise ErreurVoicemail("REJ-STT-CONFIG", "délai, taille et durée doivent respecter les plafonds STT")
        object.__setattr__(self, "base_url", url)
        object.__setattr__(self, "modele", self.modele.strip())
        object.__setattr__(self, "cle_api", self.cle_api.strip() or None if self.cle_api else None)

    @classmethod
    def depuis_env(cls, environ: Mapping[str, str] | None = None) -> ConfigurationSTT | None:
        if environ is None:
            # Une ligne persistée est la source choisie par l'administrateur. Désactivée ou
            # incomplète, elle ne retombe jamais silencieusement sur la configuration historique.
            from opsys import connecteurs, stockage

            with stockage.transaction() as cnx:
                persistee = connecteurs.lire(cnx)
            if persistee is not None:
                if not persistee["actif"]:
                    return None
                return connecteurs.construire_configuration(persistee["references"], os.environ)
        env = os.environ if environ is None else environ
        url = env.get(ENV_URL, "").strip()
        if not url:
            return None
        modele = env.get(ENV_MODELE, "").strip()
        if not modele:
            raise ErreurVoicemail("REJ-STT-CONFIG", f"{ENV_MODELE} absent; aucun modèle par défaut")
        try:
            delai = float(env.get(ENV_DELAI, "45"))
        except ValueError as exc:
            raise ErreurVoicemail("REJ-STT-CONFIG", f"{ENV_DELAI} doit être numérique") from exc
        return cls(
            url,
            modele,
            cle_api=env.get(ENV_CLE),
            local=env.get(ENV_LOCAL, "").strip() == "1",
            delai_s=delai,
        )

    def verifier_connexion(self) -> dict[str, Any]:
        """Diagnostic indicatif de disponibilité, jamais une preuve de transcription.

        Un serveur compatible peut ne pas exposer `/models`; cette route n'est donc ni requise
        pour transcrire, ni utilisée pour valider le modèle configuré.
        """
        if not self.local and not self.cle_api:
            return {
                "connecte": None,
                "modele": self.modele,
                "statut": "identifiants_absents",
                "stt_verifie": False,
            }
        requete = urllib.request.Request(f"{self.base_url}/models", headers=self._entetes(), method="GET")
        try:
            with _ouvrir(requete, self.delai_s) as reponse:
                corps = reponse.read(128_000)
            # La route, si elle répond, ne prouve que l'accessibilité HTTP; son corps est ignoré.
            del corps
            return {
                "connecte": None,
                "modele": self.modele,
                "statut": "endpoint_rejoignable",
                "stt_verifie": False,
            }
        except urllib.error.HTTPError as exc:
            statut = "identifiants_refuses" if exc.code in {401, 403} else "diagnostic_indisponible"
            return {"connecte": None, "modele": self.modele, "statut": statut, "stt_verifie": False}
        except (urllib.error.URLError, TimeoutError, OSError):
            return {
                "connecte": None,
                "modele": self.modele,
                "statut": "diagnostic_indisponible",
                "stt_verifie": False,
            }

    def _entetes(self) -> dict[str, str]:
        entetes = {"Accept": "application/json"}
        if self.cle_api:
            entetes["Authorization"] = f"Bearer {self.cle_api}"
        return entetes

    def _transcrire(self, audio: bytes, suffixe: str) -> str:
        if not self.local and not self.cle_api:
            raise ErreurVoicemail("REJ-STT-IDENTIFIANTS", f"configurer {ENV_CLE} pour l'endpoint externe")
        borne = f"opsys-m1-{secrets.token_hex(16)}"
        morceaux = [
            _partie(borne, "model", self.modele.encode("utf-8")),
            _partie(
                borne,
                "file",
                audio,
                filename=f"voicemail{suffixe}",
                content_type=_TYPES_AUDIO[suffixe],
            ),
            f"--{borne}--\r\n".encode("ascii"),
        ]
        requete = urllib.request.Request(
            f"{self.base_url}/audio/transcriptions",
            data=b"".join(morceaux),
            headers={**self._entetes(), "Content-Type": f"multipart/form-data; boundary={borne}"},
            method="POST",
        )
        try:
            with _ouvrir(requete, self.delai_s) as reponse:
                corps = reponse.read(1_000_001)
        except urllib.error.HTTPError as exc:
            raise ErreurVoicemail("REJ-STT-HTTP", f"l'endpoint STT a répondu HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ErreurVoicemail("REJ-STT-INJOIGNABLE", "endpoint STT injoignable ou délai dépassé") from None
        if len(corps) > 1_000_000:
            raise ErreurVoicemail("REJ-STT-REPONSE", "réponse STT au-delà de la limite")
        try:
            resultat = json.loads(corps)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ErreurVoicemail("REJ-STT-REPONSE", "réponse STT non JSON") from None
        texte = resultat.get("text") if isinstance(resultat, dict) else None
        if not isinstance(texte, str) or not texte.strip():
            raise ErreurVoicemail("REJ-STT-REPONSE", "réponse STT sans transcription textuelle")
        texte = texte.strip()
        if len(texte) > MAX_TRANSCRIPTION_CARACTERES:
            raise ErreurVoicemail("REJ-STT-TRANSCRIPTION-LONGUE", "transcription au-delà de 5 000 caractères")
        return texte


def empreinte_requete_stt(
    audio: bytes,
    *,
    suffixe: str,
    source: str,
    evenement_id: str,
    appel_id: str,
    recu_le: str,
    telephone: str,
    consentement_enregistrement: str | None,
    consentement_transfert_externe: str | None,
    configuration: ConfigurationSTT | None,
) -> str | None:
    """Empreinte opaque d'une requête éligible; `None` signifie qu'aucun lookup n'est permis.

    Elle couvre audio exact, métadonnées, consentements et paramètres STT. La clé est consommée
    seulement dans le digest final, jamais copiée dans le journal ni exposée.
    """
    if configuration is None or consentement_enregistrement != "accorde":
        return None
    if not configuration.local and consentement_transfert_externe != "accorde":
        return None
    try:
        valider_metadonnees(source, evenement_id, appel_id, recu_le, telephone)
        audio_valide, suffixe_valide = _valider_audio(audio, suffixe, configuration)
        duree = _duree_audio(audio_valide, suffixe_valide)
        if duree > configuration.duree_max_s:
            return None
    except ErreurVoicemail:
        return None
    cle = configuration.cle_api
    donnees = {
        "version": 1,
        "sha256_audio": hashlib.sha256(audio_valide).hexdigest(),
        "suffixe": suffixe_valide,
        "metadonnees": {
            "source": source,
            "evenement_id": evenement_id,
            "appel_id": appel_id,
            "recu_le": recu_le,
            "telephone": telephone,
        },
        "consentements": {
            "enregistrement": consentement_enregistrement,
            "transfert_externe": consentement_transfert_externe,
        },
        "stt": {
            "base_url": configuration.base_url,
            "modele": configuration.modele,
            "local": configuration.local,
            "delai_s": configuration.delai_s,
            "taille_max_octets": configuration.taille_max_octets,
            "duree_max_s": configuration.duree_max_s,
            "cle_api_sha256": hashlib.sha256(cle.encode("utf-8")).hexdigest() if cle else None,
        },
    }
    canonique = json.dumps(donnees, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def transcrire_et_importer(
    audio: bytes,
    *,
    suffixe: str,
    source: str,
    evenement_id: str,
    appel_id: str,
    recu_le: str,
    telephone: str,
    consentement_enregistrement: str | None,
    capacites: Capacites | None = None,
    configuration: ConfigurationSTT | None = None,
    consentement_transfert_externe: str | None = None,
    importeur: ImporteurM1 | None = None,
) -> dict[str, Any]:
    """Transcrit si permis, puis utilise toujours l'import d'appel canonique M1.

    Le consentement à conserver le texte vocal est obligatoire avant tout envoi STT. Un endpoint
    non local exige aussi un accord distinct pour le transfert du fichier. Tout refus/panne produit
    un import voicemail sans transcription, qui laisse à M1 son rappel humain durable.
    """
    valider_metadonnees(source, evenement_id, appel_id, recu_le, telephone)
    args_m1: dict[str, Any] = {
        "source": source,
        "evenement_id": evenement_id,
        "appel_id": appel_id,
        "recu_le": recu_le,
        "telephone": telephone,
        "statut": "voicemail",
        "transcription": None,
        "consentement_enregistrement": None,
    }
    erreur: ErreurVoicemail | None = None
    empreinte_transcription: dict[str, Any] | None = None
    if consentement_enregistrement != "accorde":
        erreur = ErreurVoicemail(
            "REJ-CONSENTEMENT-ENREGISTREMENT", "le consentement à conserver la transcription est absent"
        )
    else:
        try:
            config = configuration if configuration is not None else ConfigurationSTT.depuis_env()
            if config is None:
                raise ErreurVoicemail("REJ-STT-NON-CONFIGURE", f"configurer {ENV_URL} et {ENV_MODELE}")
            if not config.local and consentement_transfert_externe != "accorde":
                raise ErreurVoicemail(
                    "REJ-CONSENTEMENT-TRANSFERT",
                    "un accord distinct est requis avant l'envoi vers l'endpoint externe",
                )
            audio_valide, suffixe_valide = _valider_audio(audio, suffixe, config)
            duree = _duree_audio(audio_valide, suffixe_valide)
            if duree > config.duree_max_s:
                raise ErreurVoicemail("REJ-DUREE-AUDIO", "audio au-delà de la durée maximale configurée")
            transcription = config._transcrire(audio_valide, suffixe_valide)
            empreinte_transcription = {
                "caracteres": len(transcription),
                "sha256": hashlib.sha256(transcription.encode("utf-8")).hexdigest(),
                "duree_s": round(duree, 3),
                "modele": config.modele,
            }
            args_m1["transcription"] = transcription
            args_m1["consentement_enregistrement"] = consentement_enregistrement
        except ErreurVoicemail as exc:
            erreur = exc
    m1 = _importer_m1(args_m1, capacites, importeur)
    if m1.get("ok") is not True:
        return {"statut": "refuse", "code": "REJ-IMPORT-M1", "m1": m1}
    if erreur is not None:
        return {"statut": "refuse", "code": erreur.code, "m1": m1}
    return {"statut": "transcrit", "transcription": empreinte_transcription, "m1": m1}


def valider_wav(audio: bytes) -> float:
    """Valide bornes et durée WAV avant tout STT, même sans configuration de fournisseur."""
    if not isinstance(audio, bytes):
        raise ErreurVoicemail("REJ-AUDIO-INVALIDE", "audio binaire déjà lu requis")
    if len(audio) == 0 or len(audio) > MAX_AUDIO_OCTETS:
        raise ErreurVoicemail("REJ-TAILLE-AUDIO", "audio vide ou au-delà de la limite configurée")
    duree = _duree_audio(audio, ".wav")
    if duree > MAX_DUREE_S:
        raise ErreurVoicemail("REJ-DUREE-AUDIO", "audio au-delà de la durée maximale configurée")
    return duree


def valider_metadonnees(source: str, evenement_id: str, appel_id: str, recu_le: str, telephone: str) -> None:
    if not isinstance(source, str) or not source.strip() or len(source) > 120:
        raise ErreurVoicemail("REJ-SOURCE-INVALIDE", "source explicite requise (120 caractères maximum)")
    for nom, valeur in (("evenement_id", evenement_id), ("appel_id", appel_id)):
        if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > 200:
            raise ErreurVoicemail(f"REJ-{nom.upper()}-INVALIDE", f"{nom} requis (200 caractères maximum)")
    try:
        date = dt.datetime.fromisoformat(recu_le.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise ErreurVoicemail("REJ-HORODATAGE-INVALIDE", "horodatage ISO-8601 avec fuseau requis") from None
    if date.tzinfo is None:
        raise ErreurVoicemail("REJ-HORODATAGE-INVALIDE", "horodatage ISO-8601 avec fuseau requis")
    if (
        not isinstance(telephone, str)
        or not telephone.startswith("+")
        or not telephone[1:].isdigit()
        or not 7 <= len(telephone) <= 16
        or telephone[1] == "0"
    ):
        raise ErreurVoicemail("REJ-TELEPHONE-INVALIDE", "numéro téléphonique E.164 requis")


def _valider_audio(audio: bytes, suffixe: str, config: ConfigurationSTT) -> tuple[bytes, str]:
    if not isinstance(suffixe, str):
        raise ErreurVoicemail("REJ-FORMAT-AUDIO", "suffixe textuel requis")
    suffixe = suffixe.lower()
    if suffixe not in _TYPES_AUDIO:
        raise ErreurVoicemail("REJ-FORMAT-AUDIO", "format audio non pris en charge")
    if not isinstance(audio, bytes):
        raise ErreurVoicemail("REJ-AUDIO-INVALIDE", "audio binaire déjà lu requis")
    if len(audio) == 0 or len(audio) > config.taille_max_octets:
        raise ErreurVoicemail("REJ-TAILLE-AUDIO", "audio vide ou au-delà de la limite configurée")
    return audio, suffixe


def _duree_audio(audio: bytes, suffixe: str) -> float:
    if suffixe == ".wav":
        try:
            with wave.open(BytesIO(audio), "rb") as source:
                frames, frequence = source.getnframes(), source.getframerate()
                canaux = source.getnchannels()
                if not 1 <= canaux <= 2 or not 8000 <= frequence <= 48000 or frames <= 0:
                    raise ErreurVoicemail("REJ-DUREE-AUDIO", "en-tête WAV invalide ou hors limites")
                return frames / frequence
        except (wave.Error, EOFError):
            raise ErreurVoicemail("REJ-DUREE-AUDIO", "en-tête WAV illisible") from None
    try:
        resultat = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                "-i",
                "pipe:0",
            ],
            input=audio,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=8,
        )
        donnees = json.loads(resultat.stdout)
        duree = float(donnees["format"]["duration"])
    except (FileNotFoundError, subprocess.SubprocessError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ErreurVoicemail("REJ-DUREE-AUDIO", "durée audio illisible; ffprobe est requis") from None
    if not math.isfinite(duree) or duree <= 0:
        raise ErreurVoicemail("REJ-DUREE-AUDIO", "durée audio absente ou invalide")
    return duree


def _partie(
    borne: str,
    nom: str,
    valeur: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> bytes:
    morceaux = [f'--{borne}\r\nContent-Disposition: form-data; name="{nom}"'.encode("ascii")]
    if filename is not None:
        morceaux.append(f'; filename="{filename}"'.encode("ascii"))
    morceaux.append(b"\r\n")
    if content_type is not None:
        morceaux.append(f"Content-Type: {content_type}\r\n".encode("ascii"))
    morceaux.extend([b"\r\n", valeur, b"\r\n"])
    return b"".join(morceaux)


def _importer_m1(
    arguments: Mapping[str, Any], capacites: Capacites | None, importeur: ImporteurM1 | None = None
) -> dict[str, Any]:
    if importeur is not None:
        reponse = importeur(arguments)
        if not isinstance(reponse, Mapping):
            return {"ok": False, "erreur": "REJ-IMPORT-M1", "details": "réponse d'import illisible"}
        return dict(reponse)
    if capacites is None:
        departements = charger_departements()
        capacites = Capacites(
            {"m01-front-office": departements["m01-front-office"]},
            stockage.transaction,
            memoire=False,
        )
    return capacites.appeler("m1_importer_appel_manuellement", arguments)
