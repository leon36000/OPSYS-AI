"""Profil canonique versionné ; YAML historique seulement en l'absence de lignes DB.

Les lignes historiques sans empreinte restent lisibles après validation de leur forme.
Les nouvelles lignes sont chaînées ; ce contrôle détecte une altération, pas un auteur OS
qui remplace puis recalcule toute la chaîne. Aucune vérité externe n'est attestée.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

import yaml
from sqlalchemy import func, select

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

from . import brand_schema, profil_client

DEPARTEMENT = "m07-marketing"
REGISTRE = "brand_profiles"
MAX_PROFIL_OCTETS = 65536
MAX_VERSIONS = 4096
MAX_JOURNAL_OCTETS = 8 * 1024 * 1024
OPTIONS = frozenset({"site_url", "garanties_validees", "heures_publication", "hashtags", "mentions"})
PLATEFORMES = frozenset({"facebook", "instagram", "fiche_google", "video_courte", "demande_temoignage"})
_MODIFICATION_CONSOLE: ContextVar[tuple[int | None] | None] = ContextVar("modification_marque_console", default=None)


@contextmanager
def preserver_options_console(revision_attendue: int | None):
    """Conservation explicite serveur CAS, sans métadonnée/autorité acceptée par l'outil."""
    if revision_attendue is not None and (
        type(revision_attendue) is not int or not 0 <= revision_attendue < MAX_VERSIONS
    ):
        raise ValueError("révision attendue invalide")
    token = _MODIFICATION_CONSOLE.set((revision_attendue,))
    try:
        yield
    finally:
        _MODIFICATION_CONSOLE.reset(token)


def _json(valeur: Any) -> str:
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def empreinte(valeur: Any) -> str:
    return hashlib.sha256(_json(valeur).encode("utf-8")).hexdigest()


def valider_profil(profil: Any) -> dict[str, Any]:
    """Contrat Brand v1 plus types bornés des seules options consommées par l'usine."""
    valide = brand_schema.validate_profile(profil)
    if not valide["name"].strip():
        raise ValueError("nom commercial vide")
    texte = _json(valide)
    if len(texte.encode("utf-8")) > MAX_PROFIL_OCTETS or json.loads(texte) != valide:
        raise ValueError("profil JSON trop grand ou non natif")
    for cle in ("name", "tagline", "tone", "langue"):
        if len(valide[cle]) > 2000:
            raise ValueError(f"{cle} trop long")
    if not 1 <= len(valide["colors"]) <= 32 or any(len(c) > 100 for c in valide["colors"]):
        raise ValueError("colors : 1 à 32 textes de 100 caractères")
    if "site_url" in valide:
        url = valide["site_url"]
        if not isinstance(url, str) or len(url) > 2000:
            raise ValueError("site_url invalide")
        analyse = urlsplit(url)
        _port = analyse.port  # refuse aussi une déclaration de port malformée
        if (
            analyse.scheme != "https"
            or not analyse.hostname
            or analyse.username
            or analyse.password
            or analyse.query
            or analyse.fragment
            or any(c.isspace() for c in url)
        ):
            raise ValueError("site_url : URL HTTPS publique sans identifiants, query ni fragment")
    for cle in ("garanties_validees", "hashtags", "mentions"):
        if cle in valide and (
            not isinstance(valide[cle], list)
            or len(valide[cle]) > 32
            or any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in valide[cle])
        ):
            raise ValueError(f"{cle} : au plus 32 textes non vides de 500 caractères")
    if "heures_publication" in valide:
        heures = valide["heures_publication"]
        if (
            not isinstance(heures, dict)
            or set(heures) - PLATEFORMES
            or any(
                not isinstance(v, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", v)
                for v in heures.values()
            )
        ):
            raise ValueError("heures_publication : plateformes connues et heures HH:MM")
    return valide


def _versions() -> tuple[list[dict[str, Any]], list[str]]:
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise RuntimeError("lecture de marque hors transaction")
    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == REGISTRE)
    nombre, volume, taille_max = cnx.execute(
        select(
            func.count(), func.sum(func.length(REGISTRES.c.maillon)), func.max(func.length(REGISTRES.c.maillon))
        ).where(filtre)
    ).one()
    if nombre > MAX_VERSIONS or (volume or 0) > MAX_JOURNAL_OCTETS or (taille_max or 0) > MAX_PROFIL_OCTETS + 2048:
        raise ValueError("registre de marque hors limites de lecture")
    versions = []
    precedent = None
    chaine_commencee = False
    historique = False
    for rang, texte in cnx.execute(
        select(REGISTRES.c.rang, REGISTRES.c.maillon).where(filtre).order_by(REGISTRES.c.rang)
    ):
        ligne = codec.decoder(texte)
        requis = {"type", "revision", "profil", "configure_par", "horodatage"}
        if (
            not isinstance(ligne, dict)
            or not requis.issubset(ligne)
            or set(ligne) - requis - {"hash_maillon", "hash_precedent"}
        ):
            raise ValueError("ligne de marque invalide")
        if (
            rang != len(versions)
            or type(ligne["revision"]) is not int
            or ligne["revision"] != len(versions) + 1
            or ligne["type"] not in {"brand_profile", "brand_profile_v2"}
            or any(
                not isinstance(ligne[c], str) or not ligne[c].strip() or len(ligne[c]) > 200
                for c in ("configure_par", "horodatage")
            )
        ):
            raise ValueError("révision de marque incohérente")
        valider_profil(ligne["profil"])
        propre, motif = profil_client.verifier_profil_configure(ligne["profil"])
        if propre is None:
            raise ValueError(motif or "profil non configuré")
        charge = {c: v for c, v in ligne.items() if c != "hash_maillon"}
        attendu = empreinte(charge)
        if "hash_maillon" in ligne:
            if ligne.get("hash_precedent") != precedent or ligne["hash_maillon"] != attendu:
                raise ValueError("empreinte ou lien de marque invalide")
            chaine_commencee = True
        elif chaine_commencee or "hash_precedent" in ligne or ligne["type"] == "brand_profile_v2":
            raise ValueError("empreinte de marque manquante")
        else:
            historique = True
        precedent = attendu
        versions.append(ligne)
    avertissements = (
        ["Révisions historiques sans empreinte persistée : intégrité historique non attestée."] if historique else []
    )
    return versions, avertissements


_ERREURS_DONNEES = (
    OSError,
    brand_schema.ProfileError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    ArithmeticError,
    UnicodeError,
    RecursionError,
)


def courant() -> dict[str, Any]:
    with stockage.transaction():
        try:
            versions, _avertissements = _versions()
        except _ERREURS_DONNEES:
            return {"statut": "refuse", "profil": None, "motif": "registre de marque invalide"}
        if not versions:
            return {"statut": "a_configurer", "profil": None, "revision": None}
        dernier = versions[-1]
        return {
            "statut": "configure",
            "profil": dernier["profil"],
            "revision": dernier["revision"],
            "configure_par": dernier["configure_par"],
        }


def lire_snapshot_marque() -> dict[str, Any]:
    with stockage.transaction():
        try:
            versions, avertissements = _versions()
        except _ERREURS_DONNEES:
            return {"statut": "refuse", "profil": None, "motif": "registre de marque invalide ; aucun repli YAML"}
        if versions:
            profil = versions[-1]["profil"]
            revision, source = versions[-1]["revision"], "brand_profiles"
        else:
            try:
                if profil_client._PROFIL_PAR_DEFAUT.stat().st_size > MAX_PROFIL_OCTETS:
                    raise ValueError("YAML trop grand")
                profil, motif = profil_client.charger_profil_client()
                if profil is None:
                    return {"statut": "a_configurer", "profil": None, "motif": motif}
                profil = valider_profil(profil)
            except (OSError, yaml.YAMLError, *_ERREURS_DONNEES):
                return {"statut": "refuse", "profil": None, "motif": "profil YAML historique illisible ou invalide"}
            revision, source = None, "yaml_legacy"
            avertissements = ["Marque issue du YAML historique, sans révision canonique DB."]
        return {
            "statut": "configure",
            "profil": profil,
            "preuve": {"source": source, "revision": revision, "sha256": empreinte(profil)},
            "avertissements": avertissements,
        }


def enregistrer(profil: dict[str, Any], signataire: str, horodatage: str) -> dict[str, Any]:
    try:
        valide = valider_profil(profil)
    except _ERREURS_DONNEES as exc:
        return {"statut": "profil_invalide", "motif": str(exc)}
    propre, motif = profil_client.verifier_profil_configure(valide)
    if propre is None:
        return {"statut": "a_configurer", "motif": motif}
    with stockage.transaction():
        try:
            versions, _avertissements = _versions()
        except _ERREURS_DONNEES:
            return {"statut": "refuse", "motif": "registre de marque invalide ; aucune nouvelle révision"}
        modification = _MODIFICATION_CONSOLE.get()
        if modification is not None:
            attendu = modification[0]
            courant = versions[-1]["profil"] if versions else {}
            extras = {c: v for c, v in courant.items() if c not in brand_schema.REQUIRED_FIELDS and c not in propre}
            if attendu is None and versions:
                return {"statut": "refuse", "motif": "Modification existante : fournir la révision attendue."}
            if attendu is not None and attendu != len(versions):
                return {
                    "statut": "refuse",
                    "motif": "Conflit de révision de marque : recharger le profil avant modification.",
                }
            propre = {**extras, **propre}
            # Les options conservées viennent uniquement de ce snapshot validé, dans la transaction.
            try:
                valider_profil(propre)
            except _ERREURS_DONNEES:
                return {"statut": "profil_invalide", "motif": "profil conservé hors limites"}
        revision = len(versions) + 1
        precedent = empreinte({c: v for c, v in versions[-1].items() if c != "hash_maillon"}) if versions else None
        maillon = {
            "type": "brand_profile_v2",
            "revision": revision,
            "profil": propre,
            "configure_par": signataire,
            "horodatage": horodatage,
            "hash_precedent": precedent,
        }
        maillon["hash_maillon"] = empreinte(maillon)
        stockage.maillons(DEPARTEMENT, REGISTRE).append(maillon, rang_attendu=len(versions))
    return {"statut": "configure", "profil": propre, "revision": revision, "configure_par": signataire}
