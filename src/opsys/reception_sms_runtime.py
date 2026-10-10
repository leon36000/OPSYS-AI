"""Codec pur des intentions SMS privées ; ne prouve aucune réception fournisseur."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from types import MappingProxyType

from opsys.canaux import cle_session

_CHAMPS_COMMANDE = (
    "canal", "provider", "compte_id", "account_sid", "message_sid", "expediteur",
    "destinataire", "recu_le", "texte", "session_key", "agent_id", "preuve_sha256",
)

_OPERATIONS = frozenset({"opsys_runtime_lire_reception_sms", "opsys_runtime_recevoir_sms"})
_OUTIL_M1 = "opsys_m1__m1_recevoir_message_canal"
_ERREUR = "REJ-M1-SMS-COMMANDE-INVALIDE"


def _exiger(condition: bool) -> None:
    if not condition:
        raise ValueError(_ERREUR)


def _objet(valeur: object, champs: tuple[str, ...]) -> None:
    # Ne pas appeler les méthodes d'une sous-classe provenant d'un appel Python.
    _exiger(type(valeur) is dict)
    _exiger(all(type(cle) is str for cle in valeur))
    _exiger(set(valeur) == set(champs))


def _format(valeur: str, motif: str) -> bool:
    return re.fullmatch(motif, valeur, flags=re.ASCII) is not None


def _valider(arguments: dict, operation: str) -> None:
    _exiger(type(operation) is str and operation in _OPERATIONS)
    _objet(arguments, ("version", "commande", "permission"))
    _exiger(type(arguments["version"]) is int and arguments["version"] == 1)
    c, p = arguments["commande"], arguments["permission"]
    _objet(c, _CHAMPS_COMMANDE)
    _objet(p, ("profil_id", "revision_profil", "outil_m1"))
    _exiger(all(type(v) is str for v in c.values()))
    _exiger(type(p["profil_id"]) is str and type(p["outil_m1"]) is str)
    _exiger(all(len(v) <= 131072 for v in (*c.values(), p["profil_id"], p["outil_m1"])))
    _exiger(type(p["revision_profil"]) is int and 1 <= p["revision_profil"] <= 9007199254740991)
    # La représentation bornée est celle du JSON décodé, pas les octets HTTP
    # originaux ni leurs éventuelles clés dupliquées déjà perdues par le SDK.
    try:
        taille = len(json.dumps(arguments, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError(_ERREUR) from None
    _exiger(taille <= 131072)
    _exiger(c["canal"] == "sms" and c["provider"] == "twilio")
    _exiger(_format(c["compte_id"], r"[a-z0-9][a-z0-9_-]{0,63}"))
    _exiger(c["compte_id"] not in {"__proto__", "prototype", "constructor"})
    _exiger(_format(c["account_sid"], r"AC[0-9a-fA-F]{32}"))
    _exiger(_format(c["message_sid"], r"SM[0-9a-fA-F]{32}"))
    _exiger(_format(c["expediteur"], r"\+[1-9][0-9]{6,14}"))
    _exiger(_format(c["destinataire"], r"\+[1-9][0-9]{6,14}"))
    _exiger(_format(p["profil_id"], r"[a-z][a-z0-9-]{1,63}"))
    _exiger(p["outil_m1"] == _OUTIL_M1)
    _exiger(c["agent_id"] == "opsys-agent-" + p["profil_id"])
    _exiger(c["session_key"] == cle_session(c["agent_id"], "sms", c["expediteur"]))
    _exiger(_format(c["preuve_sha256"], r"[0-9a-f]{64}"))
    _exiger(bool(c["texte"].strip()) and len(c["texte"].encode("utf-8")) <= 20000)
    _exiger(_format(c["recu_le"], r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z"))
    try:
        datetime.fromisoformat(c["recu_le"])
    except ValueError:
        raise ValueError(_ERREUR) from None


@dataclass(frozen=True, slots=True)
class CommandeSmsValidee:
    commande: Mapping[str, str]
    permission: Mapping[str, str | int]
    operation: str
    intention_id: str
    commande_sha256: str
    arguments_sha256: str


def _empreinte(prefixe: bytes, valeurs: tuple[str, ...]) -> str:
    morceaux = []
    for valeur in valeurs:
        octets = valeur.encode("utf-8")
        morceaux.append(str(len(octets)).encode("ascii") + b":" + octets)
    return sha256(prefixe + b"".join(morceaux)).hexdigest()


def valider_commande(arguments: dict, *, operation: str) -> CommandeSmsValidee:
    """Valide un dict JSON décodé et capture son intention sans effet externe."""
    _valider(arguments, operation)
    commande = dict(arguments["commande"])
    permission = dict(arguments["permission"])
    valeurs = tuple(commande[champ] for champ in _CHAMPS_COMMANDE)
    return CommandeSmsValidee(
        commande=MappingProxyType(commande),
        permission=MappingProxyType(permission),
        operation=operation,
        intention_id="sms-v1:" + _empreinte(
            b"opsys:m1:sms:intention:v1:",
            (commande["provider"], commande["account_sid"], commande["message_sid"]),
        ),
        commande_sha256=_empreinte(b"opsys:m1:sms:commande:v1:", valeurs),
        arguments_sha256=_empreinte(
            b"opsys:m1:sms:arguments:v1:",
            (
                operation, "1", *valeurs, permission["profil_id"],
                str(permission["revision_profil"]), permission["outil_m1"],
            ),
        ),
    )
