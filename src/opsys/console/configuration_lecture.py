"""Projection privée et bornée des canons existants, sans réseau ni nouvelle configuration."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection, LargeBinary, case, cast, func, or_, select

from opsys import approbations, modeles, openclaw
from opsys.departements import PALIERS, Departement
from opsys.stockage.schema import AGENTS_CONFIGURABLES, AGENTS_POLITIQUE_ENTREPRISE

MAX_OCTETS = 64 * 1024
MAX_DEPARTEMENTS = 16
MAX_PROFILS = 50
_ID = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")


class ConfigurationLectureErreur(ValueError):
    """Diagnostic public sans chemin, URL, secret ni contenu du fichier fautif."""

    def __init__(self, code: str, *, statut: int = 409):
        self.code = code
        self.statut = statut
        super().__init__(code)


class _PaliersLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        resultat = {}
        for cle_node, valeur_node in node.value:
            cle = self.construct_object(cle_node, deep=deep)
            if not isinstance(cle, str) or cle in resultat:
                raise ConfigurationLectureErreur("paliers_schema_invalide")
            resultat[cle] = self.construct_object(valeur_node, deep=deep)
        return resultat


def _arbre_valide(donnees: Any) -> None:
    pile = [(donnees, 0, frozenset())]
    noeuds = 0
    while pile:
        valeur, profondeur, ancetres = pile.pop()
        noeuds += 1
        if noeuds > 512 or profondeur > 16:
            raise ConfigurationLectureErreur("paliers_structure_excessive")
        if isinstance(valeur, float) and not math.isfinite(valeur):
            raise ConfigurationLectureErreur("paliers_nombre_non_fini")
        if isinstance(valeur, (dict, list)):
            ident = id(valeur)
            if ident in ancetres:
                raise ConfigurationLectureErreur("paliers_structure_cyclique")
            enfants = list(valeur.items()) if isinstance(valeur, dict) else list(enumerate(valeur))
            for cle, enfant in enfants:
                if isinstance(valeur, dict) and not isinstance(cle, str):
                    raise ConfigurationLectureErreur("paliers_schema_invalide")
                pile.append((enfant, profondeur + 1, ancetres | {ident}))
        elif valeur is not None and type(valeur) not in (str, int, float, bool):
            raise ConfigurationLectureErreur("paliers_type_invalide")


def _lire_paliers(chemin: Path | None) -> dict[str, dict[str, Any]]:
    fichier = chemin if chemin is not None else modeles.fichier_paliers()
    try:
        with fichier.open("rb") as flux:
            brut = flux.read(MAX_OCTETS + 1)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigurationLectureErreur("paliers_indisponibles") from exc
    if len(brut) > MAX_OCTETS:
        raise ConfigurationLectureErreur("paliers_trop_volumineux", statut=413)
    try:
        texte = brut.decode("utf-8")
        profondeur = 0
        for nombre, evenement in enumerate(yaml.parse(texte), 1):
            if isinstance(evenement, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                profondeur += 1
            elif isinstance(evenement, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                profondeur -= 1
            if nombre > 1024 or profondeur > 16:
                raise ConfigurationLectureErreur("paliers_structure_excessive")
        donnees = yaml.load(texte, Loader=_PaliersLoader)
        _arbre_valide(donnees)
        if not isinstance(donnees, dict) or set(donnees) != {"paliers"}:
            raise ConfigurationLectureErreur("paliers_schema_invalide")
        if not isinstance(donnees["paliers"], dict) or len(donnees["paliers"]) > len(PALIERS):
            raise ConfigurationLectureErreur("paliers_schema_invalide")
        return modeles.valider_paliers(donnees["paliers"])
    except ConfigurationLectureErreur:
        raise
    except (UnicodeError, yaml.YAMLError, ValueError, TypeError, RecursionError) as exc:
        raise ConfigurationLectureErreur("paliers_schema_invalide") from exc


def _entier(valeur: Any, minimum: int = 0) -> int:
    if type(valeur) is not int or not minimum <= valeur <= 2**63 - 1:
        raise ConfigurationLectureErreur("registre_agents_invalide")
    return valeur


def _profils(cnx: Connection, deps: Mapping[str, Departement]) -> dict[str, Any]:
    table = AGENTS_CONFIGURABLES
    visible = table.c.supprime.is_(False)
    total = _entier(cnx.scalar(select(func.count()).select_from(table).where(visible)))
    # Les champs libres outils/déclencheurs/responsabilité/historique ne sont jamais sélectionnés.
    trop_long = or_(*(func.length(cast(col, LargeBinary)) > maximum for col, maximum in (
        (table.c.id, 64), (table.c.departement, 64), (table.c.palier_modele, 16),
    )))
    if cnx.scalar(select(func.count()).select_from(table).where(visible, trop_long)):
        raise ConfigurationLectureErreur("registre_agents_invalide")
    par_departement = {
        row.departement: {"total": int(row.total), "actifs": int(row.actifs or 0)}
        for row in cnx.execute(select(
            table.c.departement, func.count().label("total"),
            func.sum(case((table.c.actif.is_(True), 1), else_=0)).label("actifs"),
        ).where(visible, table.c.departement.in_(list(deps))).group_by(table.c.departement))
    }
    items = []
    for row in cnx.execute(select(
        table.c.id, table.c.departement, table.c.palier_modele, table.c.actif, table.c.revision,
        table.c.budget_jour, table.c.budget_mois,
        table.c.limite_tours, table.c.limite_reessais, table.c.limite_concurrence,
    ).where(visible).order_by(table.c.id).limit(MAX_PROFILS)).mappings():
        if not all(isinstance(row[key], str) and _ID.fullmatch(row[key]) for key in ("id", "departement")):
            raise ConfigurationLectureErreur("registre_agents_invalide")
        if row["palier_modele"] not in PALIERS or type(row["actif"]) is not bool:
            raise ConfigurationLectureErreur("registre_agents_invalide")
        items.append({
            "id": row["id"], "departement": row["departement"], "palier": row["palier_modele"],
            "actif": row["actif"], "revision": _entier(row["revision"], 1),
            **{key: _entier(row[key], 0 if key == "limite_reessais" else 1) for key in (
                "budget_jour", "budget_mois", "limite_tours", "limite_reessais", "limite_concurrence",
            )},
            "declencheurs": "declares_non_raccordes", "runtime": "non_observe",
        })
    return {"total": total, "retournes": len(items), "omis": total - len(items),
            "items": items, "par_departement": par_departement}


def verifier_sortie(brut: bytes) -> None:
    if len(brut) > MAX_OCTETS:
        raise ConfigurationLectureErreur("configuration_sortie_trop_volumineuse", statut=413)


def lire(
    cnx: Connection, deps: Mapping[str, Departement], environ: Mapping[str, str],
    chemin_paliers: Path | None = None,
) -> dict[str, Any]:
    """Identité vérifiée par le transport avant/après lecture et rendu ; aucun effet ici."""
    if len(deps) > MAX_DEPARTEMENTS:
        raise ConfigurationLectureErreur("configuration_trop_de_departements", statut=413)
    paliers = _lire_paliers(chemin_paliers)
    profils = _profils(cnx, deps)
    tiers = []
    for nom in PALIERS:
        conf = paliers.get(nom)
        requis = openclaw.secrets_modeles_manquants({nom: conf}, {}) if conf else []
        absentes = openclaw.secrets_modeles_manquants({nom: conf}, environ) if conf else []
        tiers.append({
            "nom": nom, "fournisseur": conf["provider"] if conf else None,
            "statut": "non_configure" if conf is None else "references_manquantes" if absentes else "presence_declaree",
            "references_requises": requis, "references_absentes": absentes,
            "authentification_distante": "non_verifiee",
        })
    departements = []
    for dep in sorted(deps.values(), key=lambda d: d.numero):
        compte = profils["par_departement"].get(dep.id, {"total": 0, "actifs": 0})
        departements.append({
            "id": dep.id, "code": dep.code, "nom": dep.nom,
            "mode": approbations.mode_effectif(cnx, dep.id, dep.mode),
            "paliers_requis": sorted(set(dep.modeles.values())),
            "specialistes": {**compte, "inactifs": compte["total"] - compte["actifs"]},
            "tokens": {"jour": _entier(dep.budget.tokens_jour, 1),
                       "mois": _entier(dep.budget.tokens_mois, 1)},
            "dependances": list(dep.dependances),
            "evenements_declares": {"publie": list(dep.evenements_publie), "consomme": list(dep.evenements_consomme)},
            "memoire_declaree": {"lecture": list(dep.memoire_lecture), "ecriture": list(dep.memoire_ecriture)},
            "permissions": "outils_du_departement_et_politiques_metier", "inventaire_api": "partiel",
        })
    politique = cnx.execute(select(
        AGENTS_POLITIQUE_ENTREPRISE.c.budget_jour, AGENTS_POLITIQUE_ENTREPRISE.c.budget_mois,
        AGENTS_POLITIQUE_ENTREPRISE.c.revision,
    ).where(AGENTS_POLITIQUE_ENTREPRISE.c.id == 1)).mappings().first()
    resultat = {
        "schema": "opsys.configuration_dashboard/v1", "departements": departements, "paliers": tiers,
        "profils": {k: v for k, v in profils.items() if k != "par_departement"},
        "plafonds_specialistes": {k: _entier(v, 1) for k, v in politique.items()} if politique else None,
        "verification_runtime": "non_observee", "cout_financier": "inconnu",
        "limites": {"octets": MAX_OCTETS, "departements": MAX_DEPARTEMENTS,
                    "paliers": len(PALIERS), "profils": MAX_PROFILS},
    }
    verifier_sortie(json.dumps(resultat, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return resultat
