"""Paliers de modèles : `local`, `rapide`, `standard`, `fort`.

Les départements déclarent un palier par usage (manifeste `modeles`), jamais un modèle
précis. L'installation associe chaque palier à un fournisseur et un modèle, cloud ou local,
dans `$OPSYS_HOME/paliers.yaml`, modifiable depuis le dashboard. Changer de fournisseur ne
touche donc aucun département.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .departements import PALIERS
from .etat import dossier_opsys


def fichier_paliers() -> Path:
    return dossier_opsys() / "paliers.yaml"


def charger_paliers(chemin: Path | None = None) -> dict[str, dict[str, Any]]:
    fichier = chemin or fichier_paliers()
    if not fichier.is_file():
        return {}
    donnees = yaml.safe_load(fichier.read_text(encoding="utf-8")) or {}
    paliers = donnees.get("paliers", {})
    if not isinstance(paliers, dict):
        raise ValueError(f"{fichier} : 'paliers' doit être un objet")
    return valider_paliers(paliers)


def valider_paliers(paliers: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    resultat = {nom: valider_palier(nom, conf) for nom, conf in paliers.items()}
    _valider_replis(resultat)
    return resultat


def valider_palier(nom: str, conf: Any) -> dict[str, Any]:
    if nom not in PALIERS:
        raise ValueError(f"palier inconnu {nom!r} (attendu : {', '.join(PALIERS)})")
    if not isinstance(conf, Mapping):
        raise ValueError(f"palier {nom} : configuration objet attendue")
    fournisseur = conf.get("provider")
    modele = conf.get("model")
    if (
        not isinstance(fournisseur, str)
        or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", fournisseur)
        or not isinstance(modele, str)
        or not modele.strip()
    ):
        raise ValueError(f"palier {nom} : 'provider' et 'model' sont requis")
    inconnues = set(conf) - {"provider", "model", "base_url", "api_key_env", "fallbacks"}
    if inconnues:
        raise ValueError(f"palier {nom} : champ(s) inconnu(s) : {sorted(inconnues)}")
    resultat: dict[str, Any] = {"provider": fournisseur, "model": modele}
    base_url = conf.get("base_url")
    if base_url is not None:
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            raise ValueError(f"palier {nom} : base_url doit être une URL http(s)")
        resultat["base_url"] = base_url
    api_key_env = conf.get("api_key_env")
    if api_key_env is not None:
        if not isinstance(api_key_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", api_key_env):
            raise ValueError(f"palier {nom} : api_key_env doit être un nom de variable d'environnement valide")
        resultat["api_key_env"] = api_key_env
    fallbacks = conf.get("fallbacks", [])
    if not isinstance(fallbacks, list) or not all(isinstance(x, str) for x in fallbacks):
        raise ValueError(f"palier {nom} : fallbacks doit être une liste de noms de paliers")
    if len(set(fallbacks)) != len(fallbacks) or nom in fallbacks:
        raise ValueError(f"palier {nom} : fallbacks doit être sans doublon et ne peut contenir le palier lui-même")
    if any(x not in PALIERS for x in fallbacks):
        raise ValueError(f"palier {nom} : fallbacks doit contenir seulement {', '.join(PALIERS)}")
    if fallbacks:
        resultat["fallbacks"] = fallbacks
    if fournisseur == "custom" and "base_url" not in resultat:
        raise ValueError(f"palier {nom} : un fournisseur 'custom' (Ollama, vLLM, llama.cpp) exige base_url")
    return resultat


def _valider_replis(paliers: Mapping[str, Mapping[str, Any]]) -> None:
    for nom, conf in paliers.items():
        absents = sorted(set(conf.get("fallbacks", [])) - set(paliers))
        if absents:
            raise ValueError(f"palier {nom} : paliers de repli non configurés : {absents}")
    visites: set[str] = set()
    pile: set[str] = set()

    def visiter(nom: str) -> None:
        if nom in pile:
            raise ValueError(f"cycle de paliers de repli détecté à {nom!r}")
        if nom in visites:
            return
        pile.add(nom)
        for repli in paliers[nom].get("fallbacks", []):
            visiter(repli)
        pile.remove(nom)
        visites.add(nom)

    for nom in paliers:
        visiter(nom)


def enregistrer_paliers(
    paliers: Mapping[str, Mapping[str, Any]], chemin: Path | None = None, par: str | None = None
) -> Path:
    """Écrit les paliers validés ; signé par `par`, le changement est inscrit au journal d'audit."""
    propres = {nom: valider_palier(nom, conf) for nom, conf in paliers.items()}
    _valider_replis(propres)
    fichier = chemin or fichier_paliers()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(yaml.safe_dump({"paliers": propres}, allow_unicode=True, sort_keys=True), encoding="utf-8")
    if par:
        from .etat import journaliser, session

        with session() as cnx:
            journaliser(cnx, par, "modeles.paliers", str(fichier), propres)
    return fichier


def section_modele_hermes(palier: str, paliers: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    """Section `model:` du config.yaml Hermes pour un palier configuré."""
    conf = paliers.get(palier)
    if conf is None:
        raise ValueError(
            f"palier {palier!r} non configuré : renseigne-le dans le dashboard (onglet Modèles) "
            f"ou dans {fichier_paliers()}"
        )
    section = {"provider": conf["provider"], "default": conf["model"]}
    if "base_url" in conf:
        section["base_url"] = conf["base_url"]
    return section
