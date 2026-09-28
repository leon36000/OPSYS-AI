"""Paliers de modèles : `local`, `rapide`, `standard`, `fort`.

Les départements déclarent un palier par usage (manifeste `modeles`), jamais un modèle
précis. L'installation associe chaque palier à un fournisseur et un modèle, cloud ou local,
dans `$OPSYS_HOME/paliers.yaml`, modifiable depuis le dashboard. Changer de fournisseur ne
touche donc aucun département.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .departements import PALIERS
from .etat import dossier_opsys


def fichier_paliers() -> Path:
    return dossier_opsys() / "paliers.yaml"


def charger_paliers(chemin: Path | None = None) -> dict[str, dict[str, str]]:
    fichier = chemin or fichier_paliers()
    if not fichier.is_file():
        return {}
    donnees = yaml.safe_load(fichier.read_text(encoding="utf-8")) or {}
    paliers = donnees.get("paliers", {})
    if not isinstance(paliers, dict):
        raise ValueError(f"{fichier} : 'paliers' doit être un objet")
    return {nom: valider_palier(nom, conf) for nom, conf in paliers.items()}


def valider_palier(nom: str, conf: Any) -> dict[str, str]:
    if nom not in PALIERS:
        raise ValueError(f"palier inconnu {nom!r} (attendu : {', '.join(PALIERS)})")
    if not isinstance(conf, Mapping):
        raise ValueError(f"palier {nom} : configuration objet attendue")
    fournisseur = conf.get("provider")
    modele = conf.get("model")
    if not isinstance(fournisseur, str) or not fournisseur or not isinstance(modele, str) or not modele:
        raise ValueError(f"palier {nom} : 'provider' et 'model' sont requis")
    resultat = {"provider": fournisseur, "model": modele}
    base_url = conf.get("base_url")
    if base_url is not None:
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            raise ValueError(f"palier {nom} : base_url doit être une URL http(s)")
        resultat["base_url"] = base_url
    if fournisseur == "custom" and "base_url" not in resultat:
        raise ValueError(f"palier {nom} : un fournisseur 'custom' (Ollama, vLLM, llama.cpp) exige base_url")
    return resultat


def enregistrer_paliers(
    paliers: Mapping[str, Mapping[str, str]], chemin: Path | None = None, par: str | None = None
) -> Path:
    """Écrit les paliers validés ; signé par `par`, le changement est inscrit au journal d'audit."""
    propres = {nom: valider_palier(nom, conf) for nom, conf in paliers.items()}
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
