"""Création explicite de la racine Compose ; aucune réparation d'une instance existante."""

from __future__ import annotations

import copy
import hmac
import ipaddress
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import openclaw

REFERENCE_JETON = "${OPENCLAW_GATEWAY_TOKEN}"
MAX_RACINE_OCTETS = 1_048_576


class ErreurBootstrapServeur(ValueError):
    """Refus nommé sans contenu du fichier ni valeur de secret."""


def _refuser_existant() -> None:
    raise ErreurBootstrapServeur(
        "REJ-BOOTSTRAP-SERVEUR-EXISTANT : racine existante incompatible ; "
        "conserver un snapshot et demander une récupération assistée. "
        "Aucune conversion de profil distant ni réparation automatique."
    )


def _valider_domaine(domaine: str) -> None:
    if (
        not isinstance(domaine, str)
        or not 1 <= len(domaine) <= 253
        or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
               for label in domaine.split("."))
    ):
        raise ErreurBootstrapServeur("REJ-BOOTSTRAP-SERVEUR-DOMAINE : un nom d'hôte DNS ou IPv4 est requis.")
    if all(c in "0123456789." for c in domaine):
        try:
            ipaddress.IPv4Address(domaine)
        except ipaddress.AddressValueError as exc:
            raise ErreurBootstrapServeur("REJ-BOOTSTRAP-SERVEUR-DOMAINE : IPv4 canonique requise.") from exc


def _valider_existant(config: Any, domaine: str, jeton: str) -> None:
    if not isinstance(config, dict) or any(
        not isinstance(config.get(cle), dict) or config[cle].get("$include") != valeur["$include"]
        for cle, valeur in openclaw.FICHIER_RACINE_MODELE.items()
    ):
        _refuser_existant()
    # Core conserve les directives et peut ajouter des faits natifs à côté (ex. defaults.model).
    # Ces champs restent soumis au schéma Core ; aucune autre inclusion n'est admise ici.
    pending: list[tuple[tuple[str, ...], Any]] = [((), config)]
    inclusions_attendues = {(cle,) for cle in openclaw.FICHIER_RACINE_MODELE}
    while pending:
        chemin, valeur = pending.pop()
        if isinstance(valeur, dict):
            if "$include" in valeur and chemin not in inclusions_attendues:
                _refuser_existant()
            pending.extend(((*chemin, cle), enfant) for cle, enfant in valeur.items() if cle != "$include")
        elif isinstance(valeur, list):
            pending.extend(((*chemin, str(index)), enfant) for index, enfant in enumerate(valeur))
    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        _refuser_existant()
    auth = gateway.get("auth")
    control = gateway.get("controlUi")
    nodes = gateway.get("nodes")
    pairing = nodes.get("pairing") if isinstance(nodes, dict) else None
    origins = control.get("allowedOrigins") if isinstance(control, dict) else None
    if (
        gateway.get("mode") != "local" or gateway.get("bind") != "lan"
        or type(gateway.get("port")) is not int or gateway["port"] != 18789
        or not isinstance(auth, dict) or auth.get("mode") != "token"
        or not isinstance(auth.get("token"), str)
        or not (auth["token"] == REFERENCE_JETON
                or (auth["token"].isascii() and hmac.compare_digest(auth["token"], jeton)))
        or not isinstance(pairing, dict) or pairing.get("autoApproveLocal") is not False
        or not isinstance(origins, list) or len(origins) != 2
        or any(not isinstance(origin, str) for origin in origins)
        or set(origins) != {f"https://{domaine}", f"http://{domaine}"}
    ):
        _refuser_existant()


def preparer(dossier: Path, domaine: str, *, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Crée une racine fraîche ou valide sans écrire une racine serveur existante.

    Les profils natifs opsys.json restent hors de cette action. Publication exclusive :
    ne remplace jamais un fichier apparu entre la validation et l'écriture.
    """
    _valider_domaine(domaine)
    env = os.environ if environ is None else environ
    jeton = env.get("OPENCLAW_GATEWAY_TOKEN", "")
    if not isinstance(jeton, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,512}", jeton):
        raise ErreurBootstrapServeur("REJ-BOOTSTRAP-SERVEUR-AUTH : bearer Gateway absent ou invalide.")
    racine = dossier / openclaw.NOM_RACINE
    if os.path.lexists(dossier / openclaw.NOM_RACINE_INSTANCE) or racine.is_symlink():
        _refuser_existant()
    if racine.exists():
        try:
            if not racine.is_file() or racine.stat().st_size > MAX_RACINE_OCTETS:
                _refuser_existant()
            config = json.loads(racine.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            _refuser_existant()
        _valider_existant(config, domaine, jeton)
        return {"fichier": str(racine), "cree": False, "mode": "local", "auth": "token"}
    config = copy.deepcopy(openclaw.FICHIER_RACINE_MODELE)
    config["gateway"] = {
        "mode": "local", "port": 18789, "bind": "lan",
        "auth": {"mode": "token", "token": REFERENCE_JETON},
        "controlUi": {"allowedOrigins": [f"https://{domaine}", f"http://{domaine}"]},
        "nodes": {"pairing": {"autoApproveLocal": False}},
    }
    dossier.mkdir(parents=True, exist_ok=True)
    fd, nom = tempfile.mkstemp(prefix=".bootstrap-serveur-", dir=dossier)
    temporaire = Path(nom)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as flux:
            # Références d'env seulement ; Core peut ensuite rendre cette racine privée.
            # Compose aligne alors les UID des deux écrivains ; aucune réparation ici.
            os.fchmod(flux.fileno(), 0o644)
            json.dump(config, flux, ensure_ascii=False, indent=2)
            flux.write("\n")
            flux.flush()
            os.fsync(flux.fileno())
        try:
            os.link(temporaire, racine)
        except FileExistsError:
            _refuser_existant()
    finally:
        temporaire.unlink(missing_ok=True)
    return {"fichier": str(racine), "cree": True, "mode": "local", "auth": "token"}
