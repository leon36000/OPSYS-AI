"""Cycle de vie d'une version : brouillon → revu → publié, et retrait motivé. Append-only : rien n'est écrasé.

- **Revue** (`reviser`) : contrôles déterministes de forme et de provenance. Une revue réussie n'est PAS une
publication.
- **Publication** (`publier`) : une version `revu` devient `publie`. Pour un domaine réglementé (comptabilité,
fiscalité,
  juridique, investissement), elle exige une PERSONNE identifiée (revue humaine, pas l'ingestionneur) : un agent seul
  est refusé, y compris en mode « autonome ». Une version `suspecte` (le filtre anti-injection a touché son texte)
  exige aussi une personne. Publier une nouvelle version d'une source REMPLACE la précédente dans la recherche sans la
  supprimer (la précédente reste lisible et recherchable « à la date » où elle était publiée).
- **Retrait** (`retirer`) : une raison obligatoire (10 à 500 caractères) ; le retrait d'une source retire TOUTES ses
  versions (pas de résurrection d'une version plus ancienne) ; rien n'est détruit, le texte reste lisible pour l'audit.

Module pur de décision : l'identité de l'acteur est établie par l'appelant (outil d'agent, approbation, CLI) et passée
ici.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, select

from .. import etat as journal
from ..stockage.schema import CONNAISSANCES_SOURCES, CONNAISSANCES_VERSIONS
from . import etats, index
from .codes import (
    ENTREE_INVALIDE,
    REVUE_HUMAINE_REQUISE,
    REVUE_INCOMPLETE,
    SEPARATION_DES_ROLES,
    SOURCE_INCONNUE,
    TRANSITION_INTERDITE,
    VERSION_INCONNUE,
    ErreurConnaissances,
)
from .modele import (
    DOMAINES_REGLEMENTES,
    ETAT_BROUILLON,
    ETAT_PUBLIE,
    ETAT_RETIRE,
    ETAT_REVU,
    MODES_ACTEUR,
    instant_iso,
)

AUTORITES_ADMISES_REGLEMENTE = ("officielle", "fictive")


@dataclasses.dataclass(frozen=True)
class Acteur:
    par: str
    mode: str  # humain | agent | systeme
    role: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.par, str) or not self.par.strip() or self.mode not in MODES_ACTEUR:
            raise ErreurConnaissances(ENTREE_INVALIDE, "acteur invalide")
        if self.mode == "humain" and not self.role:
            raise ErreurConnaissances(ENTREE_INVALIDE, "un acteur humain porte son rôle")


def charger_version(cnx: Connection, version_id: str, departement: str | None = None) -> Mapping[str, Any]:
    ligne = cnx.execute(
        select(CONNAISSANCES_VERSIONS, CONNAISSANCES_SOURCES.c.departement, CONNAISSANCES_SOURCES.c.cle,
               CONNAISSANCES_SOURCES.c.titre, CONNAISSANCES_SOURCES.c.domaine)
        .join(CONNAISSANCES_SOURCES, CONNAISSANCES_SOURCES.c.source_id == CONNAISSANCES_VERSIONS.c.source_id)
        .where(CONNAISSANCES_VERSIONS.c.version_id == version_id)).mappings().first()
    if ligne is None or (departement is not None and ligne["departement"] != departement):
        raise ErreurConnaissances(VERSION_INCONNUE, "version inconnue dans cette base")
    return ligne


def _controles(cnx: Connection, v: Mapping[str, Any], aujourd_hui: str) -> dict[str, dict[str, Any]]:
    defauts = index.verifier_integrite(cnx, v["version_id"])
    reglemente = v["domaine"] in DOMAINES_REGLEMENTES
    controles: dict[str, dict[str, Any]] = {
        "integrite": {"ok": not defauts, "detail": "; ".join(defauts[:3]) or "texte, pages et fragments recoupés"},
        "licence": {"ok": v["licence_reutilisation"] != "inconnue",
                    "detail": "licence de réutilisation à identifier" if v["licence_reutilisation"] == "inconnue"
                    else v["licence_reutilisation"]},
        "non_expiree": {"ok": v["expire_le"] is None or v["expire_le"] >= aujourd_hui,
                        "detail": f"expire le {v['expire_le']}" if v["expire_le"] else "sans échéance déclarée"},
    }
    if reglemente:
        manque = []
        if v["type_autorite"] not in AUTORITES_ADMISES_REGLEMENTE:
            manque.append("source officielle identifiée requise")
        if not v["date_publication"]:
            manque.append("date de publication requise")
        if not v["expire_le"] and not v["revision_due_le"]:
            manque.append("échéance (expire_le ou revision_due_le) requise")
        controles["domaine_reglemente"] = {"ok": not manque,
            "detail": "; ".join(manque) or f"domaine {v['domaine']} conforme"}
    return controles


def _echecs(controles: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return [f"{nom} ({c['detail']})" for nom, c in controles.items() if not c["ok"]]


def reviser(cnx: Connection, version_id: str, *, acteur: Acteur, maintenant: dt.datetime,
            departement: str | None = None) -> dict[str, Any]:
    """brouillon → revu, si les contrôles passent. Les contrôles sont enregistrés avec l'événement."""
    quand = instant_iso(maintenant)
    v = charger_version(cnx, version_id, departement)
    controles = _controles(cnx, v, quand[:10])
    echecs = _echecs(controles)
    if echecs:
        raise ErreurConnaissances(REVUE_INCOMPLETE, "contrôles non satisfaits : " + " ; ".join(echecs))
    if v["suspect"] and acteur.mode != "humain":
        raise ErreurConnaissances(
            REVUE_HUMAINE_REQUISE, "le texte de cette version a déclenché le filtre anti-injection : une personne doit "
            "la lire et la réviser elle-même")
    etats.ajouter_etat(cnx, version_id, ETAT_REVU, attendu=ETAT_BROUILLON, par=acteur.par, mode=acteur.mode,
                       role=acteur.role, raison=None, controles=controles, quand=quand)
    journal.journaliser(cnx, acteur.par, "connaissances.reviser", f"{v['departement']}/{v['cle']}#{v['numero']}",
                        {"version_id": version_id, "mode": acteur.mode})
    return {"version_id": version_id, "etat": ETAT_REVU, "controles": controles}


def publier(cnx: Connection, version_id: str, *, acteur: Acteur, maintenant: dt.datetime,
            departement: str | None = None, raison: str | None = None) -> dict[str, Any]:
    """revu → publie. Réexamine les contrôles (une revue ancienne ne vaut pas pour un texte devenu périmé). Une
    validation HUMAINE dit pourquoi (`raison`, 10 à 500 caractères) : c'est la trace de la revue par un
    professionnel."""
    quand = instant_iso(maintenant)
    raison = etats.valider_raison(raison, requise=acteur.mode == "humain")
    v = charger_version(cnx, version_id, departement)
    if etats.etat_courant(cnx, version_id) != ETAT_REVU:
        raise ErreurConnaissances(TRANSITION_INTERDITE, "seule une version revue peut être publiée")
    if v["domaine"] in DOMAINES_REGLEMENTES:
        if acteur.mode != "humain":
            raise ErreurConnaissances(
                REVUE_HUMAINE_REQUISE, f"le domaine « {v['domaine']} » est réglementé : une personne (rôle admin ou "
                "propriétaire) doit valider la publication. À valider auprès d'un comptable (CPA) / professionnel "
                "qualifié")
        if acteur.par == v["cree_par"]:
            raise ErreurConnaissances(SEPARATION_DES_ROLES, "celui qui a ingéré la source ne peut pas la valider")
    if v["suspect"] and acteur.mode != "humain":
        raise ErreurConnaissances(REVUE_HUMAINE_REQUISE, "version suspecte (injection) : publication humaine seulement")
    echecs = _echecs(_controles(cnx, v, quand[:10]))
    if echecs:
        raise ErreurConnaissances(REVUE_INCOMPLETE, "contrôles non satisfaits à la publication : " + " ; ".join(echecs))
    precedente = etats.versions_eligibles(cnx, [v["departement"]], [ETAT_PUBLIE], quand)
    remplace = next((p["numero"] for p in precedente if p["source_id"] == v["source_id"]), None)
    etats.ajouter_etat(cnx, version_id, ETAT_PUBLIE, attendu=ETAT_REVU, par=acteur.par, mode=acteur.mode,
                       role=acteur.role, raison=raison, controles=None, quand=quand)
    journal.journaliser(cnx, acteur.par, "connaissances.publier", f"{v['departement']}/{v['cle']}#{v['numero']}",
                        {"version_id": version_id, "mode": acteur.mode, "role": acteur.role, "remplace": remplace})
    return {"version_id": version_id, "etat": ETAT_PUBLIE, "numero": v["numero"], "remplace_version": remplace}


def retirer(cnx: Connection, *, departement: str, raison: str, acteur: Acteur, maintenant: dt.datetime,
            source_id: str | None = None, version_id: str | None = None) -> dict[str, Any]:
    """Retire une source (toutes ses versions non retirées) ou, pour une version jamais publiée, cette version seule."""
    quand = instant_iso(maintenant)
    raison = etats.valider_raison(raison, requise=True)  # type: ignore[assignment]
    if (source_id is None) == (version_id is None):
        raise ErreurConnaissances(ENTREE_INVALIDE, "indiquer source_id OU version_id")
    if version_id is not None:
        v = charger_version(cnx, version_id, departement)
        courant = etats.etat_courant(cnx, version_id)
        if courant not in (ETAT_BROUILLON, ETAT_REVU):
            raise ErreurConnaissances(
                TRANSITION_INTERDITE, "une version publiée se retire avec sa source entière (source_id) ; une version "
                "déjà retirée ne se retire pas deux fois")
        cibles = [(version_id, courant, v)]
    else:
        source = cnx.execute(select(CONNAISSANCES_SOURCES).where(
            CONNAISSANCES_SOURCES.c.source_id == source_id,
            CONNAISSANCES_SOURCES.c.departement == departement)).mappings().first()
        if source is None:
            raise ErreurConnaissances(SOURCE_INCONNUE, "source inconnue dans cette base")
        cibles = []
        for ligne in cnx.execute(select(CONNAISSANCES_VERSIONS.c.version_id).where(
                CONNAISSANCES_VERSIONS.c.source_id == source_id).order_by(CONNAISSANCES_VERSIONS.c.numero)):
            courant = etats.etat_courant(cnx, ligne[0])
            if courant != ETAT_RETIRE:
                cibles.append((ligne[0], courant, {"cle": source["cle"], "numero": None}))
        if not cibles:
            raise ErreurConnaissances(TRANSITION_INTERDITE, "toutes les versions de cette source sont déjà retirées")
    for vid, courant, _ in cibles:
        etats.ajouter_etat(cnx, vid, ETAT_RETIRE, attendu=courant, par=acteur.par, mode=acteur.mode, role=acteur.role,
                           raison=raison, controles=None, quand=quand)
    journal.journaliser(cnx, acteur.par, "connaissances.retirer", f"{departement}/{source_id or version_id}", {
        "versions": [c[0] for c in cibles], "mode": acteur.mode, "raison_longueur": len(raison)})
    return {"retire": [c[0] for c in cibles], "etat": ETAT_RETIRE}
