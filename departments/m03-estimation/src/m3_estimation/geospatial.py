"""Estimation géospatiale du Québec (M3.7) : modèle de données, PORTS (cadastre, rôle d'évaluation, imagerie) et
doubles.

ÉTAT HONNÊTE. Aucune donnée géospatiale réelle n'est installée ici et il n'y a pas de réseau : les ports ne sont
branchés à RIEN en production (``PortAbsent`` : « source non configurée »), et les doubles ne portent que des données
FICTIVES. Ce module fixe la FORME des données, ce qu'on en retient, et ce qu'on refuse. Les sources publiques
candidates sont listées avec leurs licences présumées, TOUTES « à vérifier » (``sources_candidates``) : aucune n'a été
lue ni utilisée.

CE QUE L'AGRÉGATION GARANTIT.

* Une source absente ou muette donne « non_configure » ou « introuvable », jamais une valeur.
* La surface d'un lot vient du moteur déterministe (``geometrie_polygone``, formule du lacet, reçu), jamais de la
  valeur qu'un port affirme.
* Chaque fait garde sa source (identifiant, millésime, date de réception, licence) ; ``faits_pour_contexte`` reprend
  la forme d'un profil de propriété (``contexte_site``) pour que le contexte du site détecte un conflit avec M2 ou une
  déclaration.
* L'imagerie (Street View compris) est du CONTEXTE seulement : ``usage`` vaut toujours ``contexte_seulement`` et ne
  remplace jamais les photos du client (DEFINITION-PRODUIT §7 M3.7).
* Une donnée fictive le dit (``fictif``) jusque dans le contexte produit.

Normalisation d'adresse : le Référentiel québécois des adresses (RQA) est indexé par M4 (``localisation.py``) ; M3
n'importe pas un autre département. Ce module normalise seulement la CLÉ de recherche (sans accents, sans casse,
espaces réduits) que les ports reçoivent ; la proposition de coordonnées reste celle de M4.

Module pur : aucune horloge, aucun aléa, aucun réseau, aucun import ``opsys``.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from . import geometrie_polygone, journal_site, verdicts

__all__ = [
    "Adresse",
    "CadastreDouble",
    "ImagerieDouble",
    "LotCadastral",
    "PortAbsent",
    "PortCadastre",
    "PortImagerie",
    "PortRoleEvaluation",
    "ReferenceImagerie",
    "RoleEvaluationDouble",
    "SourceDonnee",
    "SourceNonConfiguree",
    "UniteEvaluation",
    "agreger",
    "normaliser_adresse",
    "sources_candidates",
]

SCHEMA = "m3.geospatial/v1"
_CODE_POSTAL = re.compile(r"^[A-Z][0-9][A-Z] ?[0-9][A-Z][0-9]$")
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,119}$")
_TEXTE_MAX = 80


class SourceNonConfiguree(Exception):
    """Un port de production sans source branchée : le résultat est « non configuré », jamais une valeur."""


@dataclasses.dataclass(frozen=True)
class Adresse:
    numero_civique: str
    odonyme: str
    municipalite: str
    code_postal: str | None

    @property
    def cle(self) -> str:
        """Clé de recherche stable : sans accents, en minuscules, espaces réduits."""
        return "|".join(_cle(x) for x in (self.numero_civique, self.odonyme, self.municipalite))


def _cle(texte: str) -> str:
    sans_accent = "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))
    return re.sub(r"[\s'’\-]+", " ", sans_accent).strip().casefold()


def normaliser_adresse(brut: Any) -> tuple[Adresse | None, dict[str, Any] | None]:
    if (
        not isinstance(brut, Mapping)
        or set(brut) - {"numero_civique", "odonyme", "municipalite", "code_postal"}
        or not {"numero_civique", "odonyme", "municipalite"} <= set(brut)
    ):
        return None, verdicts.construire_verdict(
            "REJ-GEO-ENTREE-INVALIDE",
            "adresse : numero_civique, odonyme et municipalite requis (code_postal facultatif)",
        )
    for cle in ("numero_civique", "odonyme", "municipalite"):
        valeur = brut[cle]
        if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > _TEXTE_MAX or not valeur.isprintable():
            return None, verdicts.construire_verdict(
                "REJ-GEO-ENTREE-INVALIDE", f"adresse.{cle} : texte imprimable de 80 caractères"
            )
    postal = brut.get("code_postal")
    if postal is not None and (not isinstance(postal, str) or not _CODE_POSTAL.fullmatch(postal.upper())):
        return None, verdicts.construire_verdict(
            "REJ-GEO-ENTREE-INVALIDE", "adresse.code_postal : forme canadienne A1A 1A1"
        )
    return Adresse(
        brut["numero_civique"].strip(),
        brut["odonyme"].strip(),
        brut["municipalite"].strip(),
        None if postal is None else postal.upper(),
    ), None


@dataclasses.dataclass(frozen=True)
class SourceDonnee:
    """D'où vient un fait : source, millésime, réception, licence (référence), fictif ou non."""

    source_id: str
    millesime: str
    recu_le: str
    licence: str
    fictif: bool


@dataclasses.dataclass(frozen=True)
class LotCadastral:
    numero_lot: str
    municipalite: str
    sommets: tuple[tuple[str, str], ...]  # (latitude, longitude) en degrés décimaux, textes
    source: SourceDonnee


@dataclasses.dataclass(frozen=True)
class UniteEvaluation:
    matricule: str
    annee_construction: int | None
    nombre_etages: int | None
    superficie_terrain_m2: str | None
    aire_batiment_m2: str | None
    usage_code: str | None
    source: SourceDonnee


@dataclasses.dataclass(frozen=True)
class ReferenceImagerie:
    identifiant: str
    millesime: str
    resolution_m: str | None
    source: SourceDonnee


class PortCadastre(Protocol):
    def lot_par_adresse(self, adresse: Adresse) -> LotCadastral | None: ...


class PortRoleEvaluation(Protocol):
    def unite_par_adresse(self, adresse: Adresse) -> UniteEvaluation | None: ...


class PortImagerie(Protocol):
    def imagerie_pour(self, adresse: Adresse) -> Sequence[ReferenceImagerie]: ...


class PortAbsent:
    """Le port de production tant qu'aucune source n'est branchée (aucune donnée, aucun appel externe)."""

    def lot_par_adresse(self, adresse: Adresse) -> LotCadastral | None:
        raise SourceNonConfiguree("cadastre")

    def unite_par_adresse(self, adresse: Adresse) -> UniteEvaluation | None:
        raise SourceNonConfiguree("role_evaluation")

    def imagerie_pour(self, adresse: Adresse) -> Sequence[ReferenceImagerie]:
        raise SourceNonConfiguree("imagerie")


def _exiger_fictif(source: SourceDonnee) -> None:
    if source.fictif is not True:
        raise ValueError("un double ne porte que des données fictives")


class CadastreDouble:
    def __init__(self, lots: Mapping[str, LotCadastral]) -> None:
        for lot in lots.values():
            _exiger_fictif(lot.source)
        self._lots = dict(lots)

    def lot_par_adresse(self, adresse: Adresse) -> LotCadastral | None:
        return self._lots.get(adresse.cle)


class RoleEvaluationDouble:
    def __init__(self, unites: Mapping[str, UniteEvaluation]) -> None:
        for unite in unites.values():
            _exiger_fictif(unite.source)
        self._unites = dict(unites)

    def unite_par_adresse(self, adresse: Adresse) -> UniteEvaluation | None:
        return self._unites.get(adresse.cle)


class ImagerieDouble:
    def __init__(self, references: Mapping[str, Sequence[ReferenceImagerie]]) -> None:
        for liste in references.values():
            for ref in liste:
                _exiger_fictif(ref.source)
        self._references = {k: tuple(v) for k, v in references.items()}

    def imagerie_pour(self, adresse: Adresse) -> Sequence[ReferenceImagerie]:
        return self._references.get(adresse.cle, ())


def _lire(appel: Any, nom: str) -> tuple[str, Any]:
    """``(statut, valeur)`` : ``ok``, ``introuvable``, ``non_configure`` ou ``echec`` (le détail d'une panne n'est
    pas recopié)."""
    try:
        valeur = appel()
    except SourceNonConfiguree:
        return "non_configure", None
    except Exception:  # noqa: BLE001 - un port externe est hors confiance : seul le statut compte
        return "echec", None
    if valeur is None or (isinstance(valeur, (list, tuple)) and not valeur):
        return "introuvable", None
    return "ok", valeur


def _source(s: SourceDonnee) -> dict[str, Any]:
    return {
        "source_id": s.source_id,
        "millesime": s.millesime,
        "recu_le": s.recu_le,
        "licence": s.licence,
        "fictif": s.fictif,
    }


def agreger(
    adresse_brute: Any, cadastre: Any, role: Any, imagerie: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(resultat, None)`` ou ``(None, verdict)``. Un port en échec ou absent ne bloque pas les autres."""
    adresse, verdict = normaliser_adresse(adresse_brute)
    if verdict is not None:
        return None, verdict
    assert adresse is not None
    statuts: dict[str, str] = {}
    donnees: dict[str, Any] = {"lot": None, "unite_evaluation": None, "imagerie": []}
    avertissements: list[str] = []
    sources: list[dict[str, Any]] = []

    statuts["cadastre"], lot = _lire(lambda: cadastre.lot_par_adresse(adresse), "cadastre")
    if statuts["cadastre"] == "ok":
        recu, verdict_geo = (
            geometrie_polygone.calculer({"systeme": "geographique", "sommets": [list(p) for p in lot.sommets]})
            if isinstance(lot, LotCadastral)
            else (None, None)
        )
        if not isinstance(lot, LotCadastral) or verdict_geo is not None or recu is None:
            statuts["cadastre"] = "invalide"
            avertissements.append(
                "le lot rendu par le cadastre est illisible ou son polygone est refusé : "
                + ("sortie du port de type inattendu" if not isinstance(lot, LotCadastral) else verdict_geo["code"])
            )
        else:
            donnees["lot"] = {
                "numero_lot": lot.numero_lot,
                "municipalite": lot.municipalite,
                "surface_m2": recu["resultat"]["aire_m2"],
                "perimetre_m": recu["resultat"]["perimetre_m"],
                "recu_geometrie": recu["empreinte"],
            }
            sources.append(_source(lot.source))

    statuts["role_evaluation"], unite = _lire(lambda: role.unite_par_adresse(adresse), "role_evaluation")
    if statuts["role_evaluation"] == "ok":
        if not isinstance(unite, UniteEvaluation):
            statuts["role_evaluation"] = "invalide"
            avertissements.append("l'unité d'évaluation rendue est illisible (sortie du port de type inattendu)")
        else:
            donnees["unite_evaluation"] = {
                "matricule": unite.matricule,
                "annee_construction": unite.annee_construction,
                "nombre_etages": unite.nombre_etages,
                "superficie_terrain_m2": unite.superficie_terrain_m2,
                "aire_batiment_m2": unite.aire_batiment_m2,
                "usage_code": unite.usage_code,
            }
            sources.append(_source(unite.source))

    statuts["imagerie"], refs = _lire(lambda: imagerie.imagerie_pour(adresse), "imagerie")
    if statuts["imagerie"] == "ok":
        valides = [r for r in refs if isinstance(r, ReferenceImagerie)]
        donnees["imagerie"] = [
            {
                "identifiant": r.identifiant,
                "millesime": r.millesime,
                "resolution_m": r.resolution_m,
                "usage": "contexte_seulement",
                "source": _source(r.source),
            }
            for r in valides
        ]
        sources.extend(_source(r.source) for r in valides)
        if len(valides) != len(refs):
            avertissements.append("des références d'imagerie illisibles ont été ignorées")

    faits: dict[str, Any] = {}
    if donnees["unite_evaluation"] is not None:
        if unite.annee_construction is not None:
            faits["age"] = {"annee_construction": unite.annee_construction}
        if unite.nombre_etages is not None:
            faits["hauteur"] = {"etages": unite.nombre_etages}
    faits_pour_contexte = None
    if faits and donnees["unite_evaluation"] is not None:
        faits_pour_contexte = {
            "identifiant": "geospatial-role-evaluation",
            "version": unite.source.millesime,
            "recu_le": unite.source.recu_le,
            "faits": faits,
        }
    fictif = bool(sources) and all(s["fictif"] for s in sources)
    resultat = {
        "schema": SCHEMA,
        "adresse_cle": journal_site.empreinte_canonique(adresse.cle)[:24],
        "municipalite": adresse.municipalite,
        "statuts": statuts,
        "donnees": donnees,
        "sources": sources,
        "faits_pour_contexte": faits_pour_contexte,
        "avertissements": avertissements,
        "fictif": fictif,
        "mention": "Données de sources externes à vérifier ; l'imagerie est du contexte seulement, jamais une mesure.",
    }
    resultat["empreinte"] = journal_site.empreinte_canonique(resultat)
    return resultat, None


def sources_candidates() -> list[dict[str, Any]]:
    """Sources publiques CANDIDATES du Québec. TOUTES « à vérifier » : licences présumées de la connaissance de
    l'agent au
    2026-11-01, sans accès réseau ni lecture des conditions ; aucune n'est utilisée ni téléchargée ici."""

    def s(identifiant, nom, donnee, port, licence, note, statut="a_verifier"):
        return {
            "identifiant": identifiant,
            "nom": nom,
            "donnee": donnee,
            "port": port,
            "licence_presumee": licence,
            "verification": statut,
            "lue_par": None,
            "note": note,
        }

    return [
        s(
            "quebec.role-evaluation-fonciere",
            "Rôles d'évaluation foncière (MAMH, Données Québec)",
            "unités d'évaluation : année de construction, étages, superficies, usage",
            "PortRoleEvaluation",
            "CC-BY 4.0 (à vérifier)",
            "diffusion par municipalité ; vérifier la fraîcheur du rôle et les champs réellement publiés",
        ),
        s(
            "quebec.cadastre",
            "Cadastre du Québec (lots rénovés)",
            "numéros de lot et géométrie",
            "PortCadastre",
            "CC-BY 4.0 présumée pour les données ouvertes (à vérifier) ; diffusion par Infolot ou le Registre foncier "
            "sous "
            "d'autres conditions",
            "vérifier ce qui est ouvert, sa mise à jour et la précision de la géométrie",
        ),
        s(
            "quebec.rqa",
            "Référentiel québécois des adresses (RQA)",
            "adresses géocodées",
            "PortCadastre (clé d'adresse)",
            "CC-BY 4.0 (fiche lue le 2026-09-28 selon docs/research/INGREDIENTS.md) ; attribution à afficher",
            "déjà indexé par M4 (localisation.py) ; la recherche d'adresse reste celle de M4",
            "deja_documentee",
        ),
        s(
            "quebec.orthophotographies",
            "Orthophotographies aériennes du Québec",
            "imagerie aérienne géoréférencée",
            "PortImagerie",
            "CC-BY 4.0 présumée (à vérifier)",
            "contexte seulement ; vérifier millésime et résolution",
        ),
        s(
            "osm.openstreetmap",
            "OpenStreetMap",
            "bâtiments, voirie",
            "PortCadastre / PortImagerie",
            "ODbL 1.0 : partage à l'identique des bases dérivées (à faire analyser avant tout usage)",
            "qualité variable ; ne donne ni lot cadastral ni propriétaire",
        ),
        s(
            "ville-montreal.donnees-ouvertes",
            "Données ouvertes de la Ville de Montréal",
            "évaluation foncière, bâtiments",
            "PortRoleEvaluation",
            "CC-BY 4.0 présumée (à vérifier)",
            "couverture limitée à Montréal",
        ),
        s(
            "google.street-view",
            "Google Street View / Maps (API)",
            "imagerie de rue, géocodage",
            "PortImagerie",
            "Conditions commerciales de Google (à lire) ; budget d'API non décidé",
            "CONTEXTE SEULEMENT, jamais un remplacement "
            "des photos du client ; porte fermée tant que le budget n'est pas décidé",
            "ferme_budget_et_conditions",
        ),
    ]
