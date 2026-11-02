"""Génération de la configuration LiteLLM depuis les rôles, et du fichier d'environnement de ses clés d'amont.

- `config_depuis_roles` : une entrée `model_list` par rôle servi par la passerelle intégrée (alias = `modele_appel`,
modèle
  d'amont = `amont`), les alias de PALIER que lisent les agents (`opsys-rapide` ← llm_rapide ; `opsys-standard` et
  `opsys-fort` ← llm_fort : un palier n'aiguille JAMAIS vers le raisonnement), les replis locaux comme entrées et comme
  `fallbacks` natifs. L'alias du raisonnement n'existe dans la configuration QUE si le propriétaire l'a activé (N3).
- Aucune clé dans le YAML : `os.environ/<NOM>`. `ecrire_env` matérialise depuis le coffre, côté serveur, un fichier 0600
  `NOM=valeur` pour le conteneur LiteLLM (seul endroit où une valeur est écrite hors du coffre ; voir
  PASSERELLE-DE-MODELES).
- `alias_pour_cles_departements` : les alias que les clés virtuelles des départements peuvent appeler (jamais le
raisonnement).
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from .. import passerelle as passerelle_litellm
from ..fournisseurs import registre
from ..passerelle import _CLE_ENV_FOURNISSEUR
from ..secrets_coffre import coffre, masquage
from ..secrets_coffre.erreurs import CoffreErreur
from . import codes, service
from . import roles as lex
from .acces import ACTEUR_SYSTEME, FabriqueConnexion
from .codes import ModelesErreur


def _entree_passerelle(ligne: dict[str, Any], nom: str) -> dict[str, Any] | None:
    amont = ligne.get("amont")
    if not amont:
        return None
    env = _CLE_ENV_FOURNISSEUR.get(amont["fournisseur"])
    if env is None:
        return None
    return {
        "model_name": nom,
        "litellm_params": {"model": f"{amont['fournisseur']}/{amont['modele']}", "api_key": f"os.environ/{env}"},
    }


def entrees_et_replis(cnx: Connection) -> tuple[list[dict[str, Any]], list[dict[str, list[str]]]]:
    lignes = service.toutes_les_lignes(cnx)
    actif = service.raisonnement_actif(cnx)
    entrees: dict[str, dict[str, Any]] = {}
    fallbacks: dict[str, list[str]] = {}

    def servi_par_passerelle(identifiant: str) -> bool:
        f = registre.definition(cnx, identifiant)
        return f is not None and (f.point_acces or "").startswith("passerelle:")

    for role, ligne in lignes.items():
        if role == lex.ROLE_RAISONNEMENT and not actif:
            continue
        if not servi_par_passerelle(ligne["fournisseur_id"]):
            continue
        base = _entree_passerelle(ligne, ligne["modele_appel"])
        if base is None:
            continue
        entrees[ligne["modele_appel"]] = base
        noms_exposes = [ligne["modele_appel"]]
        for palier, role_palier in lex.PALIER_VERS_ROLE.items():
            if role_palier == role:
                alias = passerelle_litellm.alias_palier(palier)
                entrees[alias] = _entree_passerelle(ligne, alias)  # type: ignore[assignment]
                noms_exposes.append(alias)
        for rang, repli in enumerate(ligne["replis"], start=1):
            f = registre.definition(cnx, repli["fournisseur"])
            if f is None or f.mode != "local" or not (f.point_acces or "").startswith(("http://", "https://")):
                continue  # replis hors passerelle (API, module, appareil) : repli côté OPSYS seulement
            nom_repli = f"{ligne['modele_appel']}-repli{rang}"
            entrees[nom_repli] = {
                "model_name": nom_repli,
                "litellm_params": {"model": f"openai/{repli['modele']}", "api_base": f.point_acces, "api_key": "local"},
            }
            for nom in noms_exposes:
                fallbacks.setdefault(nom, []).append(nom_repli)
    return list(entrees.values()), [{k: v} for k, v in sorted(fallbacks.items())]


def config_depuis_roles(
    cnx: Connection, paliers: dict[str, dict[str, str]], hote_cache: str = "valkey"
) -> dict[str, Any]:
    entrees, fallbacks = entrees_et_replis(cnx)
    return passerelle_litellm.config_litellm(paliers, hote_cache, entrees=entrees, fallbacks=fallbacks)


def alias_pour_cles_departements(cnx: Connection, paliers: dict[str, dict[str, str]]) -> list[str]:
    """Alias d'une clé virtuelle de département : paliers et rôles, JAMAIS le raisonnement ni un repli."""
    entrees, _ = entrees_et_replis(cnx)
    interdit = {
        ligne["modele_appel"] for r, ligne in service.toutes_les_lignes(cnx).items() if r == lex.ROLE_RAISONNEMENT
    }
    noms = {e["model_name"] for e in entrees} - interdit
    noms |= {passerelle_litellm.alias_palier(p) for p in paliers}
    return sorted(noms)


def paliers_depuis_roles(cnx: Connection) -> dict[str, dict[str, str]]:
    """Paliers (`rapide`, `standard`, `fort`) fournis par des rôles servis par la passerelle, en paliers valides.

    En mode LiteLLM, un agent ne lit que le NOM d'un palier (alias `opsys-<palier>`) : l'entrée synthétique n'a de sens
    que pour la validation et la liste des modèles de l'agent. Rien n'est écrit dans `paliers.yaml`."""
    reglage = service.passerelle(cnx)
    if reglage is None:
        return {}
    lignes = service.toutes_les_lignes(cnx)
    sortie: dict[str, dict[str, str]] = {}
    for palier, role in lex.PALIER_VERS_ROLE.items():
        ligne = lignes.get(role)
        if ligne is None:
            continue
        fournisseur = registre.definition(cnx, ligne["fournisseur_id"])
        if fournisseur is None or not (fournisseur.point_acces or "").startswith("passerelle:"):
            continue
        sortie[palier] = {"provider": "custom", "model": passerelle_litellm.alias_palier(palier),
                          "base_url": reglage["url_base"]}
    return sortie


def paliers_effectifs(cnx: Connection, legacy: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """`paliers.yaml` complété par les paliers des rôles (les rôles l'emportent, comme pour les alias)."""
    return {**legacy, **paliers_depuis_roles(cnx)}


def ecrire_env(fabrique: FabriqueConnexion, chemin: Path) -> list[str]:
    """Écrit `NOM=valeur` (clés d'amont et clé maîtresse) depuis le coffre dans un fichier 0600, de façon atomique.
    Rend les NOMS écrits, jamais une valeur. Refuse un chemin dans un lien symbolique ou un dossier accessible à
    d'autres."""
    with fabrique() as cnx:
        reglage = service.passerelle(cnx)
    if reglage is None:
        raise ModelesErreur(codes.PASSERELLE_ABSENTE, "la passerelle n'est pas configurée", 409)
    if reglage["mode"] != "integree":
        raise ModelesErreur(codes.PASSERELLE_ABSENTE, "passerelle existante : ses clés sont gérées chez le client", 409)
    chemin = Path(chemin).absolute()
    parent = chemin.parent
    if chemin.is_symlink() or not parent.is_dir() or (parent.stat().st_mode & stat.S_IWOTH):
        raise ModelesErreur(
            codes.DECLARATION_INVALIDE,
            "dossier de destination invalide (existant, non inscriptible "
            "par d'autres) et fichier non lien symbolique requis",
            422,
        )
    sources = {
        "LITELLM_MASTER_KEY": reglage["secret_cle"],
        **{_CLE_ENV_FOURNISSEUR[f]: nom for f, nom in reglage["secrets_amont"].items()},
    }
    lignes: list[str] = []
    for variable, nom in sources.items():
        try:
            with coffre.utiliser(
                nom=nom, usage="passerelle:environnement", acteur=ACTEUR_SYSTEME, fabrique=fabrique
            ) as valeur:
                if "\n" in valeur or "\r" in valeur or "\x00" in valeur:
                    raise ModelesErreur(
                        codes.DECLARATION_INVALIDE, f"valeur de {nom} non écrivable en environnement", 422
                    )
                lignes.append(f"{variable}={valeur}")
        except CoffreErreur as exc:
            raise ModelesErreur(codes.SECRET_INDISPONIBLE, f"secret {nom} indisponible ({exc.code})", 409) from None
    descripteur, temporaire = tempfile.mkstemp(dir=parent, prefix=".litellm-env-")
    try:
        os.fchmod(descripteur, 0o600)
        with os.fdopen(descripteur, "w", encoding="utf-8") as sortie:
            sortie.write("\n".join(lignes) + "\n")
        os.replace(temporaire, chemin)
    except BaseException:
        Path(temporaire).unlink(missing_ok=True)
        raise
    finally:
        lignes.clear()
    masquage.installer()
    return sorted(sources)
