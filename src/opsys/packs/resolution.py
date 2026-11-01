"""Trouver les packs installés et résoudre le pack ACTIF depuis le profil d'entreprise.

Le profil de l'instance, `$OPSYS_HOME/entreprise.yaml` (le même fichier que les services, les équipes, la météo et
les avatars), porte la clé `pack` : l'identifiant du pack sectoriel de CETTE entreprise. Sans cette clé, le pack actif
est `generique-pme`, vide de secteur : un cœur qui ne suppose rien. Un pack nommé mais absent ou invalide est un refus
typé (`REJ-PACK-NON-INSTALLE`, `REJ-PACK-…`), jamais un repli silencieux sur le pack générique : une entreprise
dont le pack est cassé ne doit pas se retrouver, sans le savoir, avec des agents qui ne connaissent plus
son métier.

Les packs vivent dans `packs/` à la racine du dépôt ou de l'installation (`OPSYS_PACKS` le remplace), comme
`departments/` (`opsys.departements.racine_departements`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .. import taxonomie
from .codes import RefusPack
from .manifeste import ID_PACK, NOM_MANIFESTE, Pack, calculer_empreinte, charger_dossier

CLE_PACK = "pack"
PACK_PAR_DEFAUT = "generique-pme"


def racine_packs() -> Path:
    """Dossier `packs/` du dépôt ou de l'installation (`OPSYS_PACKS` le remplace)."""
    env = os.environ.get("OPSYS_PACKS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "packs"


def ids_installes(racine: Path | None = None) -> tuple[str, ...]:
    """Identifiants des dossiers de `packs/` qui portent un manifeste, triés (un dossier sans manifeste est ignoré ici
    et refusé par `verifier_packs`)."""
    base = racine or racine_packs()
    if not base.is_dir():
        return ()
    return tuple(sorted(d.name for d in base.iterdir() if d.is_dir() and (d / NOM_MANIFESTE).exists()))


def charger_pack(identifiant: str, racine: Path | None = None) -> Pack:
    """Le pack `identifiant`, validé. `REJ-PACK-ID-INVALIDE` avant toute lecture si l'identifiant n'a pas la forme
    d'un identifiant de pack (aucun chemin construit depuis une entrée libre)."""
    if not isinstance(identifiant, str) or not ID_PACK.fullmatch(identifiant) or len(identifiant) > 64:
        raise RefusPack("REJ-PACK-ID-INVALIDE", "identifiant de pack attendu : minuscules, chiffres et tirets", "pack")
    base = racine or racine_packs()
    dossier = base / identifiant
    if not dossier.is_dir():
        raise RefusPack("REJ-PACK-NON-INSTALLE",
                        f"le pack {identifiant!r} n'est pas installé "
                        f"(installés : {list(ids_installes(base)) or 'aucun'})",
                        "pack")
    return charger_dossier(dossier, id_attendu=identifiant)


def pack_declare(profil: Path | None = None) -> str | None:
    """L'identifiant déclaré dans le profil (clé `pack`), ou `None` si le fichier ou la clé est absent."""
    fichier = profil or taxonomie.fichier_profil()
    try:
        brut: Any = taxonomie._valeur_du_profil(CLE_PACK, fichier)
    except taxonomie.ProfilInvalide as exc:
        raise RefusPack("REJ-PACK-PROFIL-INVALIDE", f"profil d'entreprise illisible : {exc}",
                        str(fichier.name)) from exc
    if brut is None:
        return None
    if not isinstance(brut, str) or not brut.strip():
        raise RefusPack("REJ-PACK-PROFIL-INVALIDE", f"`{CLE_PACK}` doit être l'identifiant d'un pack installé (texte)",
                        str(fichier.name))
    return brut.strip()


def pack_actif(profil: Path | None = None, racine: Path | None = None) -> Pack:
    """Le pack de l'instance : celui du profil, sinon `generique-pme`. Refus typé, jamais de repli."""
    return charger_pack(pack_declare(profil) or PACK_PAR_DEFAUT, racine)


def enregistrer_pack(identifiant: str, profil: Path | None = None, par: str | None = None,
                     racine: Path | None = None) -> Path:
    """Écrit `pack: <identifiant>` dans le profil, sans toucher aux autres clés, après avoir chargé (validé) le pack.

    Signée par `par`, la modification est inscrite au journal d'audit (même patron que les services). C'est le point
    d'appui de l'onboarding : il propose un pack, un humain le confirme, cette fonction l'écrit.
    """
    pack = charger_pack(identifiant, racine)
    try:
        return taxonomie._ecrire_cle_du_profil(CLE_PACK, pack.id, profil, par, "entreprise.pack",
                                               {"pack": pack.id, "version": pack.version, "empreinte": pack.empreinte})
    except taxonomie.ProfilInvalide as exc:
        raise RefusPack("REJ-PACK-PROFIL-INVALIDE", str(exc), "entreprise.yaml") from exc


def termes_sectoriels_installes(racine: Path | None = None) -> tuple[str, ...]:
    """Union des termes sectoriels de tous les packs installés (pour garder un pack générique de toute fuite)."""
    termes: list[str] = []
    for identifiant in ids_installes(racine):
        for terme in charger_pack(identifiant, racine).termes_sectoriels:
            if terme not in termes:
                termes.append(terme)
    return tuple(termes)


def verifier_packs(profil: Path | None = None, racine: Path | None = None) -> list[str]:
    """Problèmes des packs installés et du pack du profil (`opsys-metier verifier`) ; vide si tout est cohérent."""
    problemes: list[str] = []
    base = racine or racine_packs()
    if not base.is_dir():
        return [f"dossier des packs introuvable : {base}"]
    for dossier in sorted(d for d in base.iterdir() if d.is_dir()):
        try:
            charger_dossier(dossier)
        except RefusPack as exc:
            problemes.append(str(exc))
    if PACK_PAR_DEFAUT not in ids_installes(base):
        problemes.append(f"le pack par défaut {PACK_PAR_DEFAUT!r} n'est pas installé")
    try:
        pack_actif(profil, base)
    except RefusPack as exc:
        problemes.append(f"pack du profil d'entreprise : {exc}")
    return problemes


__all__ = ["CLE_PACK", "PACK_PAR_DEFAUT", "calculer_empreinte", "charger_pack", "enregistrer_pack", "ids_installes",
           "pack_actif", "pack_declare", "racine_packs", "termes_sectoriels_installes", "verifier_packs"]
