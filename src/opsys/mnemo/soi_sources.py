"""D'où viennent les énoncés du modèle de soi : les ports de lecture EXISTANTS, rien d'autre.

Aucun département n'est interrogé ici et aucun droit n'est élargi : on lit ce que le socle expose déjà.

| Dimension | Lecture existante | Source citée |
|---|---|---|
| services, zones | profil d'entreprise de l'onboarding (`opsys.taxonomie`) | `entreprise:services:<empreinte>` |
| équipes, capacité | profil des équipes (`opsys.equipes`) : semaine type DÉCLARÉE | `entreprise:equipes:<empreinte>` |
| vocabulaire | pack sectoriel actif (`opsys.packs`) | `pack:<id>:<empreinte>` |
| marges observées | faits analytiques de M8 mémorisés dans le registre `faits_analytiques` de M10 |
`registre:faits_analytiques:<ligne_id>` |
| saisonnalité | travaux terminés (WCT de M4) mémorisés dans le registre Événements de M10 |
`registre:evenements:<ligne_id>` |

Une partie du profil illisible ou absente ne produit AUCUN énoncé et n'en fait disparaître aucun : « je ne sais pas
lire » n'est pas « le service n'existe plus ». La capacité vient de la semaine type que le propriétaire a DÉCLARÉE ;
un jour non déclaré rend la semaine inconnue (jamais zéro). La saisonnalité exige au moins 30 travaux terminés
répartis sur six mois distincts : en deçà, elle reste inconnue.

Ce module ne lit aucune horloge : l'instant observé est passé par l'appelant.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from . import soi

SAISON_OBSERVATIONS_MIN = 30
SAISON_MOIS_DISTINCTS_MIN = 6
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
PARTIES_PROFIL = ("services", "zone_desservie", "equipes", "pack")


def empreinte_courte(objet: Any) -> str:
    texte = json.dumps(objet, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=list)
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:16]


@dataclasses.dataclass(frozen=True)
class Observation:
    dimension: str
    cle: str
    valeur: dict[str, Any]
    sources: tuple[dict[str, Any], ...]


@dataclasses.dataclass
class Profil:
    """Ce que le profil de l'instance dit aujourd'hui. `erreurs[partie]` : la partie existe mais n'est pas lisible."""

    services: tuple[Any, ...] = ()
    zone: tuple[str, ...] = ()
    equipes: Mapping[str, Any] | None = None
    pack: Any = None
    erreurs: dict[str, str] = dataclasses.field(default_factory=dict)

    def empreinte_partie(self, partie: str) -> str | None:
        if partie == "services" and "services" not in self.erreurs:
            return empreinte_courte(sorted((s.code, s.libelle) for s in self.services))
        if partie == "zone_desservie" and "zone_desservie" not in self.erreurs:
            return empreinte_courte(sorted(self.zone))
        if partie == "equipes" and "equipes" not in self.erreurs and self.equipes is not None:
            return empreinte_courte(self.equipes)
        return None


def lire_profil() -> Profil:
    """Lit le profil de l'instance par les modules du socle. Une partie illisible est notée, jamais lue comme vide."""
    from .. import equipes, packs, taxonomie

    profil = Profil()
    try:
        profil.services = taxonomie.lire_services()
    except taxonomie.ProfilInvalide as exc:
        profil.erreurs["services"] = str(exc)[:200]
    try:
        profil.zone = taxonomie.lire_zone_desservie()
    except taxonomie.ProfilInvalide as exc:
        profil.erreurs["zone_desservie"] = str(exc)[:200]
    try:
        profil.equipes = equipes.lire_equipes()
    except taxonomie.ProfilInvalide as exc:
        profil.erreurs["equipes"] = str(exc)[:200]
    try:
        profil.pack = packs.pack_actif()
    except packs.RefusPack as exc:
        profil.erreurs["pack"] = f"{exc.code}"[:200]
    return profil


# -- capacité
# --------------------------------------------------------------------------------------------------------------
def _minutes(heure: str) -> int:
    h, m = heure.split(":")
    return int(h) * 60 + int(m)


def capacite_minutes(semaine_type: Mapping[str, Any] | None) -> int | None:
    """Minutes d'équipe de la semaine type DÉCLARÉE ; `None` si un jour n'est pas déclaré (une semaine incomplète est
    inconnue, pas plus courte). `[]` est un jour fermé : zéro minute déclaré."""
    if not isinstance(semaine_type, Mapping):
        return None
    total = 0
    for jour in JOURS:
        if jour not in semaine_type:
            return None
        for plage in semaine_type[jour]:
            total += _minutes(plage["fin"]) - _minutes(plage["debut"])
    return total


def _heures(minutes: int) -> str:
    return str((Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01")))


# -- observations du profil
# --------------------------------------------------------------------------------------------------
def observations_profil(profil: Profil, observe_le: str) -> tuple[list[Observation], dict[str, set[str]]]:
    """`(observations, couvertes)`. `couvertes[dimension]` : les clés que le profil donne aujourd'hui, pour les seules
    dimensions que le profil énumère en entier ET qu'il a été possible de lire."""
    observations: list[Observation] = []
    couvertes: dict[str, set[str]] = {}

    def source(partie: str, h: str) -> tuple[dict[str, Any], ...]:
        return ({"type": "onboarding", "ref": f"entreprise:{partie}:{h}", "observe_le": observe_le},)

    h = profil.empreinte_partie("services")
    if h is not None and profil.services:
        for s in profil.services:
            observations.append(Observation("services", s.code, {"libelle": s.libelle}, source("services", h)))
        couvertes["services"] = {s.code for s in profil.services}
    elif h is not None:
        couvertes["services"] = set()
    h = profil.empreinte_partie("zone_desservie")
    if h is not None and profil.zone:
        observations.append(
            Observation("zones", "zone_desservie", {"villes": list(profil.zone)}, source("zone_desservie", h))
        )
        couvertes["zones"] = {"zone_desservie"}
    elif h is not None:
        couvertes["zones"] = set()
    h = profil.empreinte_partie("equipes")
    if h is not None and profil.equipes:
        liste = profil.equipes.get("liste", [])
        connues: list[int | None] = []
        for e in liste:  # les membres (des personnes) ne sont JAMAIS recopiés : l'identifiant d'équipe suffit
            effectif = e.get("effectif_planifie")
            observations.append(
                Observation(
                    "equipes",
                    e["id"],
                    {"competences": list(e.get("competences", [])), "effectif_planifie": effectif},
                    source("equipes", h),
                )
            )
            minutes = capacite_minutes(e.get("semaine_type"))
            connues.append(minutes)
            observations.append(
                Observation(
                    "capacite",
                    e["id"],
                    {
                        "minutes_semaine_type": minutes,
                        "heures_par_semaine": None if minutes is None else _heures(minutes),
                        "effectif_planifie": effectif,
                    },
                    source("equipes", h),
                )
            )
        total = None if not connues or any(m is None for m in connues) else sum(m for m in connues if m is not None)
        observations.append(
            Observation(
                "capacite",
                "entreprise",
                {
                    "minutes_semaine_type": total,
                    "heures_par_semaine": None if total is None else _heures(total),
                    "effectif_planifie": None,
                },
                source("equipes", h),
            )
        )
        couvertes["equipes"] = {e["id"] for e in liste}
        couvertes["capacite"] = {e["id"] for e in liste} | {"entreprise"}
    pack = profil.pack
    if pack is not None and "pack" not in profil.erreurs and pack.appellations:
        hp = pack.empreinte.split(":")[-1][:16]
        src = ({"type": "onboarding", "ref": f"pack:{pack.id}:{hp}", "observe_le": observe_le},)
        for cle, terme in sorted(pack.appellations.items()):
            observations.append(Observation("vocabulaire", cle, {"terme": terme}, src))
        couvertes["vocabulaire"] = set(pack.appellations)
    return observations, couvertes


# -- observations des registres de M10
# ---------------------------------------------------------------------------------------
def observations_marges(faits_analytiques: Iterable[Mapping[str, Any]]) -> list[Observation]:
    """La dernière valeur CALCULÉE de chaque mesure de marge de M8, telle que M8 l'a publiée (jamais recalculée)."""
    derniere: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for maillon in faits_analytiques:
        if maillon.get("type_entree") != "fait_analytique":
            continue
        for mesure in maillon["mesures"]:
            if "marge" in mesure["metric_id"] and mesure["statut"] == "calculee" and mesure["valeur"] is not None:
                derniere[mesure["metric_id"]] = (maillon, mesure)
    sortie = []
    for metric_id in sorted(derniere):
        maillon, mesure = derniere[metric_id]
        sortie.append(
            Observation(
                "marges_observees",
                metric_id,
                {
                    "valeur": mesure["valeur"],
                    "unite": mesure["unite"],
                    "version_definition": mesure["version_definition"],
                },
                (
                    {
                        "type": "fait_departement",
                        "ref": f"registre:faits_analytiques:{maillon['ligne_id']}",
                        "departement": "m08-analytics",
                        "observe_le": maillon["horodatage"],
                    },
                ),
            )
        )
    return sortie


def observations_saisonnalite(completions: Sequence[tuple[str, str]]) -> list[Observation]:
    """`completions` : (ligne_id, horodatage ISO) des travaux terminés mémorisés. Inconnue sous les seuils."""
    mois = [c[1][5:7] for c in completions]
    if len(completions) < SAISON_OBSERVATIONS_MIN or len(set(mois)) < SAISON_MOIS_DISTINCTS_MIN:
        return []
    compte = {f"{m:02d}": 0 for m in range(1, 13)}
    for m in mois:
        compte[m] += 1
    derniere = max(completions, key=lambda c: c[1])
    return [
        Observation(
            "saisonnalite",
            "charge_mensuelle",
            {"par_mois": compte, "observations": len(completions)},
            (
                {
                    "type": "fait_departement",
                    "ref": f"registre:evenements:{completions[-1][0]}",
                    "departement": "m04-field-ops",
                    "observe_le": derniere[1],
                },
            ),
        )
    ]


# -- vérification des sources
# ---------------------------------------------------------------------------------------------------
def verificateur(
    registres: Mapping[str, Any], profil: Profil, connaissance_existe: Callable[[str], bool] = lambda _v: False
) -> soi.Verificateur:
    """Le port qui rend une source VÉRIFIABLE : elle existe, et elle dit ce que l'énoncé prétend."""

    def verifier(source: Mapping[str, Any]) -> bool:
        genre, _, reste = source["ref"].partition(":")
        if genre == "registre":
            nom, _, ligne_id = reste.partition(":")
            registre = registres.get(nom)
            if registre is None or not ligne_id:
                return False
            if nom == "faits_analytiques" and source.get("departement") not in (None, "m08-analytics"):
                return False
            return any(m.get("ligne_id") == ligne_id for m in registre.lire())
        if genre == "entreprise":
            partie, _, h = reste.partition(":")
            return partie in PARTIES_PROFIL and profil.empreinte_partie(partie) == h and bool(h)
        if genre == "pack":
            ident, _, h = reste.partition(":")
            pack = profil.pack
            return (
                pack is not None
                and "pack" not in profil.erreurs
                and pack.id == ident
                and pack.empreinte.split(":")[-1][:16] == h
            )
        if genre == "decision":
            return any(
                m.get("type_entree") == "decision_enregistree" and m.get("decision_id") == reste
                for m in registres["affaires"].lire()
            )
        if genre == "connaissance":
            return connaissance_existe(reste)
        return False

    return verifier


# -- orchestration
# -------------------------------------------------------------------------------------------------------------
def construire(
    registre: Any,
    observations: Sequence[Observation],
    couvertes: Mapping[str, set[str]],
    *,
    verificateur_sources: soi.Verificateur,
    par: str,
    horodatage: str,
) -> dict[str, Any]:
    """Propose chaque observation (jamais ne confirme), ouvre un signal pour ce qui a disparu de ce que le profil
    énumère, lève ceux que la source soutient de nouveau. Rend le décompte et la liste des dérives (pour
    l'événement)."""
    decompte: dict[str, int] = {}
    revisions: list[dict[str, Any]] = []
    for o in observations:
        r = soi.proposer(
            registre,
            dimension=o.dimension,
            cle=o.cle,
            valeur=o.valeur,
            sources=list(o.sources),
            par=par,
            horodatage=horodatage,
            verificateur=verificateur_sources,
        )
        decompte[r["statut"]] = decompte.get(r["statut"], 0) + 1
        if r["statut"] == "revision_proposee":
            revisions.append(
                {
                    "dimension": o.dimension,
                    "cle": o.cle,
                    "enonce_id": r["enonce"]["enonce_id"],
                    "revise": r["revise"],
                    "nature": "valeur_differente",
                }
            )
    disparues: list[dict[str, Any]] = []
    levees = 0
    st = soi.etat(registre)
    observees = {(o.dimension, o.cle) for o in observations}
    for dimension, cles in couvertes.items():
        for ident in st.ordre:
            e = st.enonces[ident]
            if e["dimension"] != dimension or e["etat"] != "confirme":
                continue
            if e["cle"] in cles and (dimension, e["cle"]) in observees:
                if soi.lever_derive(registre, dimension, e["cle"], horodatage=horodatage):
                    levees += 1
            elif e["cle"] not in cles:
                ref = f"entreprise:{dimension}:constat-{empreinte_courte([dimension, sorted(cles)])}"
                if soi.signaler_source_disparue(registre, dimension, e["cle"], ref_constat=ref, horodatage=horodatage):
                    disparues.append(
                        {
                            "dimension": dimension,
                            "cle": e["cle"],
                            "enonce_id": e["enonce_id"],
                            "nature": "source_disparue",
                        }
                    )
    return {"decompte": decompte, "revisions": revisions, "sources_disparues": disparues, "derives_levees": levees}
