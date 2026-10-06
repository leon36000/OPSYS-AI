"""Opt-in OCR choisi uniquement par l'opérateur du serveur, sans accès disque."""
from collections.abc import Mapping
from pathlib import Path

ENV_BUNDLE = "OPSYS_INGESTION_OCR_BUNDLE"
_MESSAGE = "configuration OCR invalide : chemin absolu administré requis"


def valider_choix(bundle: Path | None) -> Path | None:
    if bundle is None:
        return None
    if not isinstance(bundle, Path):
        raise ValueError(_MESSAGE)
    texte = str(bundle)
    if (
        not bundle.is_absolute() or ".." in bundle.parts
        or not texte.isprintable() or "\\" in texte
        or len(texte.encode("utf-8")) > 1024
    ):
        raise ValueError(_MESSAGE)
    return bundle


def chemin_bundle(environ: Mapping[str, str]) -> Path | None:
    valeur = environ.get(ENV_BUNDLE, "")
    if not isinstance(valeur, str):
        raise ValueError(_MESSAGE)
    if not valeur.strip():
        return None
    if not valeur.isprintable():
        raise ValueError(_MESSAGE)
    return valider_choix(Path(valeur.strip()))
