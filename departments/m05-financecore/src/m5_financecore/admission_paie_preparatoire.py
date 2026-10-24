"""Admission documentaire préparatoire, sans calcul ni autorité fiscale.

`capacite` et `racine_captures` doivent venir d'une configuration serveur de confiance,
jamais des arguments d'un outil ou d'un agent. Les empreintes courantes sont obtenues
par le serveur : liaison du calculateur et de ses dépendances, snapshot de paramètres.
Ce contrôle ne prouve ni l'origine des octets, ni une identité, ni un droit d'outil.
Il ne modifie pas le catalogue documentaire ou les statuts de qualification fiscale.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

_SCHEMA = "opsys.admission-paie-preparatoire/v1"
_SHA = re.compile(r"[0-9a-f]{64}")
_MAX_CAPTURE = 16 * 1024 * 1024
_SOURCES = frozenset({"arc_jan2026", "arc_jul2026", "rq_f2026", "rq_tr26_2026"})
_PORTEE = {"annee": 2026, "juridiction": "QC", "frequence": "bihebdomadaire", "periodes_annuelles": 26, "pm": 12}
_FENETRES = frozenset({
    ("2026-01-01", "2026-06-30", 1, 1, "P1"),
    ("2026-01-01", "2026-06-30", 2, 26, "YTD"),
    ("2026-07-01", "2026-12-31", 2, 26, "YTD"),
})


def _sha_valide(valeur: object) -> bool:
    return isinstance(valeur, str) and _SHA.fullmatch(valeur) is not None


def _capacite_valide(capacite: object) -> bool:
    if type(capacite) is not dict or set(capacite) != {
        "schema", "qualification_regles", "actions_financieres_bloquees", "fenetres", "sources", *_PORTEE,
    }:
        return False
    if (capacite["schema"] != _SCHEMA or capacite["qualification_regles"] != "NON_QUALIFIEE_POUR_PAIE"
            or capacite["actions_financieres_bloquees"] is not True):
        return False
    if any(type(capacite[k]) is not type(v) or capacite[k] != v for k, v in _PORTEE.items()):
        return False
    sources, fenetres = capacite["sources"], capacite["fenetres"]
    if type(sources) is not dict or set(sources) != _SOURCES or type(fenetres) is not list or len(fenetres) != 3:
        return False
    for source in sources.values():
        if type(source) is not dict or set(source) != {"capture", "sha256", "format"}:
            return False
        if not isinstance(source["capture"], str) or not _sha_valide(source["sha256"]) or source["format"] != "PDF":
            return False
    identites = []
    for fenetre in fenetres:
        if type(fenetre) is not dict or set(fenetre) != {
            "debut", "fin", "periode_min", "periode_max", "methode", "calculateur_sha256", "parametres_sha256",
        }:
            return False
        if type(fenetre["periode_min"]) is not int or type(fenetre["periode_max"]) is not int:
            return False
        if not all(isinstance(fenetre[k], str) for k in ("debut", "fin", "methode")):
            return False
        identites.append(tuple(fenetre[k] for k in ("debut", "fin", "periode_min", "periode_max", "methode")))
        if not _sha_valide(fenetre["calculateur_sha256"]) or not _sha_valide(fenetre["parametres_sha256"]):
            return False
    return set(identites) == _FENETRES


def _fenetre(capacite: dict[str, Any], contexte: object) -> dict[str, Any] | None:
    if type(contexte) is not dict or set(contexte) != {
        "annee", "date_paie", "juridiction", "frequence", "periode_annuelle", "pm",
    }:
        return None
    for cle in ("annee", "juridiction", "frequence", "pm"):
        if type(contexte[cle]) is not type(_PORTEE[cle]) or contexte[cle] != _PORTEE[cle]:
            return None
    periode, jour = contexte["periode_annuelle"], contexte["date_paie"]
    if type(periode) is not int or not isinstance(jour, str):
        return None
    try:
        if date.fromisoformat(jour).isoformat() != jour:
            return None
    except ValueError:
        return None
    return next((f for f in capacite["fenetres"] if f["debut"] <= jour <= f["fin"]
                 and f["periode_min"] <= periode <= f["periode_max"]), None)


def _verifier_capture(racine: Path, source: dict[str, str]) -> str | None:
    relatif = source["capture"]
    chemin = PurePosixPath(relatif)
    if (not relatif or not chemin.parts or len(relatif) > 240 or "\\" in relatif or chemin.is_absolute()
            or chemin.as_posix() != relatif or any(p in {"..", "."} for p in chemin.parts)):
        return "CHEMIN_NON_CONFINE"
    descripteurs = []
    try:
        # openat + NOFOLLOW sur chaque segment, y compris les répertoires.
        fd = os.open(racine, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descripteurs.append(fd)
        for segment in chemin.parts[:-1]:
            fd = os.open(segment, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descripteurs.append(fd)
        fd = os.open(chemin.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        descripteurs.append(fd)
        avant = os.fstat(fd)
        if not stat.S_ISREG(avant.st_mode) or not 5 <= avant.st_size <= _MAX_CAPTURE:
            return "TYPE_OU_TAILLE_INVALIDE"
        empreinte, taille, debut = hashlib.sha256(), 0, b""
        while bloc := os.read(fd, 65536):
            taille += len(bloc)
            if taille > _MAX_CAPTURE:
                return "TYPE_OU_TAILLE_INVALIDE"
            if not debut:
                debut = bloc[:5]
            empreinte.update(bloc)
        apres = os.fstat(fd)
        attributs = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if taille != avant.st_size or any(getattr(avant, k) != getattr(apres, k) for k in attributs):
            return "CAPTURE_MODIFIEE_PENDANT_LECTURE"
        if debut != b"%PDF-":
            return "FORMAT_PDF_INVALIDE"
        if empreinte.hexdigest() != source["sha256"]:
            return "EMPREINTE_INCOMPATIBLE"
    except (OSError, ValueError):
        return "CAPTURE_INDISPONIBLE_OU_LIEE"
    finally:
        for fd in reversed(descripteurs):
            os.close(fd)
    return None


def verifier_admission_preparatoire(
    *, racine_captures: Path, capacite: object, contexte: object,
    empreinte_calculateur: str, empreinte_parametres: str,
) -> dict[str, Any]:
    """Vérifie une configuration de confiance; aucun calcul, SQL, réseau ou droit accordé.

    Les fenêtres bornent le support technique, pas la validité légale des documents.
    `admissible` signifie uniquement des identités documentaires compatibles avec le
    snapshot déclaré. La fonction n'authentifie pas les attestations ni les acteurs.
    """
    resultat: dict[str, Any] = {
        "schema": _SCHEMA, "admissible": False, "sources_verifiees": [], "empreintes_sources": {}, "motifs": [],
        "qualification_regles": "NON_QUALIFIEE_POUR_PAIE", "actions_financieres_bloquees": True,
        "autorisation_outil_ou_acteur": False,
    }
    if not _capacite_valide(capacite):
        resultat["motifs"] = ["CAPACITE_INVALIDE"]
        return resultat
    fenetre = _fenetre(capacite, contexte)
    if fenetre is None:
        resultat["motifs"] = ["CONTEXTE_HORS_CAPACITE"]
        return resultat
    if (not _sha_valide(empreinte_calculateur) or not _sha_valide(empreinte_parametres)
            or empreinte_calculateur != fenetre["calculateur_sha256"]
            or empreinte_parametres != fenetre["parametres_sha256"]):
        resultat["motifs"] = ["SNAPSHOT_INCOMPATIBLE"]
        return resultat
    requis = _SOURCES if contexte["date_paie"] >= "2026-07-01" else _SOURCES - {"arc_jul2026"}
    for identifiant in sorted(requis):
        cause = _verifier_capture(racine_captures, capacite["sources"][identifiant])
        if cause is not None:
            resultat["motifs"].append(f"{identifiant}:{cause}")
        else:
            resultat["sources_verifiees"].append(identifiant)
            resultat["empreintes_sources"][identifiant] = capacite["sources"][identifiant]["sha256"]
    resultat["admissible"] = not resultat["motifs"]
    return resultat


def verifier_admission_federale_preparatoire(
    *, racine_captures: Path, capacite: object, contexte: object, empreinte_calculateur: str,
) -> dict[str, Any]:
    """Lie les captures au snapshot courant de l'API documentaire fédérale.

    Racine, capacité et empreinte de génération calculateur/dépendances proviennent
    du serveur de confiance. Cette fonction n'authentifie pas cette génération :
    sa garde d'immutabilité reste la responsabilité de l'appelant serveur.
    Aucun hash de paramètres fourni par une requête n'est accepté comme courant.
    """
    empreinte_parametres = ""
    if _capacite_valide(capacite) and _fenetre(capacite, contexte) is not None:
        from .impot_federal_qc_2026 import obtenir_snapshot_retenue_federale_qc_preparatoire

        snapshot, refus = obtenir_snapshot_retenue_federale_qc_preparatoire(contexte=contexte)
        if refus is None and snapshot is not None:
            empreinte_parametres = snapshot["hash_parametres"]
    return verifier_admission_preparatoire(
        racine_captures=racine_captures, capacite=capacite, contexte=contexte,
        empreinte_calculateur=empreinte_calculateur, empreinte_parametres=empreinte_parametres,
    )
