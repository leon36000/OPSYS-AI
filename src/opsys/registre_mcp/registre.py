"""Registre MCP en liste blanche : ce qui est exposé, avec son empreinte, scellé par une révision approuvée.

**Empreinte.** Pour chaque outil, `sha256` du JSON canonique du triplet {nom, description, schéma d'entrée} (clés
triées,
sans espace, UTF-8 sans normalisation : un homoglyphe ou un caractère invisible change l'empreinte). C'est ce que le
modèle LIT : changer la description d'un outil après son approbation (« rug pull », empoisonnement d'outil) change
l'empreinte, et l'outil est REFUSÉ (`REJ-MCP-EMPREINTE-DERIVE`) jusqu'à une nouvelle révision approuvée par un humain
(`opsys-metier registre-mcp sceller --par …`). Le niveau d'approbation N0–N5 est comparé à part
(`REJ-MCP-NIVEAU-DERIVE`) : abaisser un niveau retire une approbation, c'est aussi une dérive. Un outil absent
du registre est refusé (`REJ-MCP-OUTIL-INCONNU`).

**Révisions.** Le fichier du registre porte la révision courante, l'historique chaîné (qui a scellé, quand, quels outils
ajoutés / modifiés / retirés / changés de niveau, empreinte de chaque révision et de la précédente) et un sceau :
`sha256` de l'empreinte de la révision (détecte une édition à la main), ou `hmac-sha256` avec la clé locale
(détecte une édition par quelqu'un qui ne la détient pas). L'entrée garde la description et le schéma APPROUVÉS : on
voit
exactement ce qui a été relu, et ce qui a changé (`parties`).

Limites : sans clé HMAC, quiconque écrit le fichier ET modifie l'outil peut resceller (la revue de la révision dans Git
est alors la barrière). Une description vérifiée sûre par motifs (`inspecter_description`) n'est pas prouvée sûre.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..outils import vers_json

SCHEMA = "opsys.mcp.registre/v1"
SURFACES = ("departement", "contexte", "runtime")
NIVEAUX = ("N0", "N1", "N2", "N3", "N4", "N5")
RANG = {n: i for i, n in enumerate(NIVEAUX)}
CODES_MCP = (
    "REJ-MCP-EMPREINTE-DERIVE", "REJ-MCP-NIVEAU-DERIVE", "REJ-MCP-OUTIL-INCONNU", "REJ-MCP-REGISTRE-ABSENT",
    "REJ-MCP-REGISTRE-ALTERE", "REJ-MCP-REGISTRE-SCEAU", "REJ-MCP-REGISTRE-RETRAIT", "REJ-MCP-DESCRIPTION-SUSPECTE",
    "REJ-MCP-RULE-OF-TWO", "REJ-MCP-SURFACE-NON-FIABLE", "REJ-MCP-EXPOSITION-INVALIDE", "REJ-MCP-ARGUMENT-INVALIDE",
)
_NOM_OUTIL = re.compile(r"^(?:m(?:10|[1-9])|opsys)_[a-z][a-z0-9_]{1,60}$")
_PAR = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_EMPREINTE = re.compile(r"^sha256:[0-9a-f]{64}$")


class RefusMCP(Exception):
    """Refus typé du registre MCP : `code` (catalogue fermé), `outil`, `detail` lisible, sans valeur sensible."""

    def __init__(self, code: str, detail: str, outil: str | None = None, **contexte: Any) -> None:
        if code not in CODES_MCP:
            raise ValueError(f"code MCP hors catalogue : {code!r}")
        self.code, self.detail, self.outil, self.contexte = code, detail, outil, contexte
        super().__init__(f"{code} : {detail}")

    def enveloppe(self) -> dict[str, Any]:
        """Réponse d'outil au format du socle (`{ok, erreur, details}`), comprise telle quelle par le Core."""
        return {"ok": False, "erreur": self.code, "details": self.detail}


def _canonique(donnees: Any) -> str:
    return json.dumps(donnees, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(donnees: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonique(donnees).encode("utf-8")).hexdigest()


def empreinte_triplet(nom: str, description: str, schema: Mapping[str, Any]) -> str:
    """Empreinte du triplet que le modèle lit : nom + description + schéma d'entrée."""
    return _sha({"nom": nom, "description": description, "schema": vers_json(schema)})


def empreintes_parties(nom: str, description: str, schema: Mapping[str, Any]) -> dict[str, str]:
    return {"nom": _sha(nom), "description": _sha(description), "schema": _sha(vers_json(schema))}


@dataclasses.dataclass(frozen=True)
class DefinitionOutil:
    """Un outil tel qu'il est exposé maintenant (ou tel que le code le déclare)."""

    nom: str
    description: str
    schema_entree: Mapping[str, Any]
    departement: str
    niveau: str
    surface: str = "departement"

    def __post_init__(self) -> None:
        if not _NOM_OUTIL.match(self.nom):
            raise RefusMCP("REJ-MCP-ARGUMENT-INVALIDE", f"nom d'outil invalide : {self.nom!r}")
        if self.niveau not in NIVEAUX or self.surface not in SURFACES:
            raise RefusMCP("REJ-MCP-ARGUMENT-INVALIDE", f"{self.nom} : niveau ou surface invalide")

    @property
    def empreinte(self) -> str:
        return empreinte_triplet(self.nom, self.description, self.schema_entree)

    @classmethod
    def depuis_outil(cls, outil: Any, departement: str, surface: str = "departement") -> DefinitionOutil:
        return cls(outil.nom, outil.description, vers_json(outil.parametres), departement,
                   outil.niveau_effectif.value, surface)


@dataclasses.dataclass(frozen=True)
class EntreeRegistre:
    nom: str
    departement: str
    niveau: str
    surface: str
    description: str
    schema_entree: Mapping[str, Any]
    empreinte: str
    version: int  # 1 à l'ajout, +1 à chaque révision qui change l'empreinte ou le niveau de CET outil
    parties: Mapping[str, str]

    def vers_dict(self) -> dict[str, Any]:
        return {"nom": self.nom, "departement": self.departement, "niveau": self.niveau, "surface": self.surface,
                "description": self.description, "schema_entree": vers_json(self.schema_entree),
                "empreinte": self.empreinte, "version": self.version, "parties": dict(self.parties)}


@dataclasses.dataclass(frozen=True)
class Registre:
    revision: int
    entrees: Mapping[str, EntreeRegistre]
    historique: tuple[Mapping[str, Any], ...]
    scelle_par: str
    scelle_le: str
    empreinte: str
    sceau: Mapping[str, str]

    def vers_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "revision": self.revision, "scelle_par": self.scelle_par, "scelle_le": self.scelle_le,
                "outils": {n: e.vers_dict() for n, e in sorted(self.entrees.items())},
                "historique": [dict(h) for h in self.historique], "empreinte_registre": self.empreinte,
                "sceau": dict(self.sceau)}


# --- Inspection des descriptions -------------------------------------------------------------------------------------
_INJECTION = re.compile(
    r"(?i)ignore[zr]?\s+(?:all|any|the|toutes?|les)?\s*(?:previous|prior|above|pr[ée]c[ée]dentes?|ant[ée]rieures?)\s+"
    r"(?:instructions?|consignes?)|ignore[zr]?\s+(?:toutes?\s+)?(?:les\s+)?(?:instructions?|consignes?)\s+"
    r"(?:pr[ée]c[ée]dentes?|ant[ée]rieures?)|<\s*/?\s*(?:important|system|instructions?)\s*>|"
    r"do not (?:tell|inform|mention)|"
    r"ne (?:le )?(?:dis|dites|mentionne|r[ée]v[èe]le)[a-z]* pas (?:à|a) l['’]utilisateur|"
    r"n['’]informe[z]? pas l['’]utilisateur|"
    r"avant d['’]utiliser cet outil,? (?:tu dois|vous devez)|before using this tool"
)
_BLOB = re.compile(r"[A-Za-z0-9+/]{160,}={0,2}")


def inspecter_description(description: str) -> list[str]:
    """Constats sur une description d'outil (empoisonnement probable). Vide = rien de suspect par motifs."""
    constats: list[str] = []
    invisibles = {c for c in description if unicodedata.category(c) in ("Cf", "Co", "Cs") or
                  (unicodedata.category(c) == "Cc" and c not in "\n\t")}
    if invisibles:
        codes = ", ".join(sorted(f"U+{ord(c):04X}" for c in invisibles))
        constats.append(f"caractères invisibles ou de contrôle ({codes})")
    if _INJECTION.search(description):
        constats.append("formulation d'instruction adressée au modèle ou cachée à l'utilisateur")
    if _BLOB.search(description):
        constats.append("longue suite opaque (base64 probable)")
    return constats


# --- Scellement ------------------------------------------------------------------------------------------------------

def _empreinte_revision(revision: int, entrees: Mapping[str, Mapping[str, Any]], precedent: str | None) -> str:
    return _sha({"schema": SCHEMA, "revision": revision, "outils": {n: entrees[n] for n in sorted(entrees)},
                 "precedent": precedent})


def _empreinte_historique(historique: Iterable[Mapping[str, Any]]) -> str:
    """Empreinte de TOUTES les fiches d'historique (qui a scellé, quand, quels outils ajoutés, modifiés, retirés)."""
    return _sha([dict(fiche) for fiche in historique])


def _sceau(empreinte: str, revision: int, par: str, le: str, cle: bytes | None,
           historique: Iterable[Mapping[str, Any]] | None = None) -> dict[str, str]:
    """Sceau de la révision. Avec `historique`, le sceau porte aussi l'empreinte des fiches (champ `historique`, dans
    la charge scellée) : retoucher une fiche sans la clé casse le HMAC. Sans lui, c'est le sceau d'avant (lisible)."""
    charge = f"{empreinte}|{revision}|{par}|{le}"
    marque = None
    if historique is not None:
        marque = _empreinte_historique(historique)
        charge += f"|{marque}"
    if cle is None:
        sceau = {"algo": "sha256", "valeur": hashlib.sha256(charge.encode()).hexdigest()}
    else:
        sceau = {"algo": "hmac-sha256", "valeur": hmac.new(cle, charge.encode(), hashlib.sha256).hexdigest()}
    if marque is not None:
        sceau["historique"] = marque
    return sceau


def sceller(definitions: Iterable[DefinitionOutil], ancien: Registre | None, *, par: str, maintenant: dt.datetime,
            cle: bytes | None = None, autoriser_retraits: bool = False,
            inspecter: bool = True) -> Registre:
    """Nouvelle révision du registre à partir des définitions COURANTES. Rend `ancien` tel quel s'il n'y a rien à
    changer.

    `par` : la personne qui approuve la révision (identifiant, jamais un agent). Une description suspecte bloque le
    scellement. Les outils absents des définitions ne sont retirés qu'avec `autoriser_retraits`. `inspecter=False`
    n'existe que pour
    fabriquer une garde FAUTIVE dans l'évaluation (`garde_complaisante`)."""
    if not isinstance(par, str) or not _PAR.fullmatch(par):
        raise RefusMCP("REJ-MCP-ARGUMENT-INVALIDE", "approbateur invalide (identifiant de personne attendu)")
    courantes: dict[str, DefinitionOutil] = {}
    for d in definitions:
        if d.nom in courantes and courantes[d.nom].empreinte != d.empreinte:
            raise RefusMCP("REJ-MCP-ARGUMENT-INVALIDE", f"{d.nom} : deux définitions différentes au même nom", d.nom)
        courantes[d.nom] = d
    for d in courantes.values() if inspecter else ():
        constats = inspecter_description(d.description)
        if constats:
            raise RefusMCP("REJ-MCP-DESCRIPTION-SUSPECTE", f"{d.nom} : " + " ; ".join(constats), d.nom)
    anciennes = dict(ancien.entrees) if ancien else {}
    retires = sorted(set(anciennes) - set(courantes))
    if retires and not autoriser_retraits:
        raise RefusMCP("REJ-MCP-REGISTRE-RETRAIT",
                       f"{len(retires)} outil(s) scellé(s) absent(s) ({', '.join(retires[:5])}…) : retrait à approuver "
                       "explicitement (--retirer)")
    entrees: dict[str, EntreeRegistre] = {}
    ajoutes, modifies, niveaux = [], [], []
    for nom, d in sorted(courantes.items()):
        avant = anciennes.get(nom)
        if avant is not None and avant.empreinte == d.empreinte and avant.niveau == d.niveau \
                and avant.departement == d.departement and avant.surface == d.surface:
            entrees[nom] = avant
            continue
        if avant is None:
            ajoutes.append(nom)
        else:
            if avant.empreinte != d.empreinte or avant.departement != d.departement or avant.surface != d.surface:
                modifies.append(nom)
            if avant.niveau != d.niveau:
                niveaux.append(nom)
        entrees[nom] = EntreeRegistre(
            nom=nom, departement=d.departement, niveau=d.niveau, surface=d.surface, description=d.description,
            schema_entree=vers_json(d.schema_entree), empreinte=d.empreinte,
            version=(avant.version + 1) if avant else 1,
            parties=empreintes_parties(d.nom, d.description, d.schema_entree))
    if ancien is not None and not (ajoutes or modifies or niveaux or retires):
        return ancien
    revision = (ancien.revision if ancien else 0) + 1
    le = maintenant.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    dicts = {n: e.vers_dict() for n, e in entrees.items()}
    empreinte = _empreinte_revision(revision, dicts, ancien.empreinte if ancien else None)
    fiche = {"revision": revision, "par": par, "le": le, "ajoutes": ajoutes, "modifies": modifies,
             "niveaux_changes": sorted(set(niveaux)), "retires": retires, "outils": len(entrees),
             "empreinte_registre": empreinte, "precedent": ancien.empreinte if ancien else None}
    historique = (*(ancien.historique if ancien else ()), fiche)
    return Registre(revision, entrees, historique, par, le, empreinte,
                    _sceau(empreinte, revision, par, le, cle, historique))


# --- Lecture, écriture, intégrité ------------------------------------------------------------------------------------

def depuis_dict(donnees: Mapping[str, Any], *, cle: bytes | None = None) -> Registre:
    """Reconstruit un registre ET vérifie son intégrité (empreinte de la révision, chaîne d'historique, sceau)."""
    try:
        if donnees["schema"] != SCHEMA:
            raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", "schéma de registre inconnu")
        entrees = {}
        for nom, e in donnees["outils"].items():
            entree = EntreeRegistre(nom=e["nom"], departement=e["departement"], niveau=e["niveau"],
                                    surface=e["surface"],
                                    description=e["description"], schema_entree=e["schema_entree"],
                                    empreinte=e["empreinte"], version=int(e["version"]), parties=dict(e["parties"]))
            if (nom != entree.nom or not _NOM_OUTIL.match(nom) or entree.niveau not in NIVEAUX
                    or entree.surface not in SURFACES or not _EMPREINTE.match(entree.empreinte)):
                raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", f"entrée mal formée : {nom!r}")
            if entree.empreinte != empreinte_triplet(entree.nom, entree.description, entree.schema_entree):
                raise RefusMCP("REJ-MCP-REGISTRE-ALTERE",
                               f"{nom} : l'empreinte ne correspond plus à la description et au schéma consignés", nom)
            entrees[nom] = entree
        historique = tuple(donnees["historique"])
        revision = int(donnees["revision"])
        registre = Registre(revision, entrees, historique, donnees["scelle_par"], donnees["scelle_le"],
                            donnees["empreinte_registre"], dict(donnees["sceau"]))
    except RefusMCP:
        raise
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", "registre mal formé") from None
    derniere = historique[-1] if historique else {}
    if derniere.get("revision") != revision or derniere.get("empreinte_registre") != registre.empreinte:
        raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", "historique incohérent avec la révision courante")
    # La dernière fiche DIT ce que le sceau atteste : qui, quand, combien d'outils (sinon l'audit se réécrit).
    if (derniere.get("par") != registre.scelle_par or derniere.get("le") != registre.scelle_le
            or derniere.get("outils") != len(entrees)):
        raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", "la dernière fiche d'historique contredit le sceau de la révision")
    for avant, apres in zip(historique, historique[1:], strict=False):
        if apres.get("precedent") != avant.get("empreinte_registre") or apres.get("revision") != avant.get("revision",
                                                                                                           0) + 1:
            raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", "chaîne d'historique rompue")
    attendue = _empreinte_revision(revision, {n: e.vers_dict() for n, e in entrees.items()},
                                   historique[-2]["empreinte_registre"] if len(historique) > 1 else None)
    if attendue != registre.empreinte:
        raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", "empreinte de la révision invalide : registre modifié à la main")
    sceau = registre.sceau
    if sceau.get("algo") == "hmac-sha256":
        if cle is None:
            raise RefusMCP("REJ-MCP-REGISTRE-SCEAU", "registre scellé par HMAC : la clé de scellement est requise")
    elif sceau.get("algo") != "sha256":
        raise RefusMCP("REJ-MCP-REGISTRE-SCEAU", "algorithme de sceau inconnu")
    elif cle is not None:
        raise RefusMCP("REJ-MCP-REGISTRE-SCEAU",
                       "une clé de scellement est configurée mais le registre n'est scellé que par sha256")
    marque = sceau.get("historique")
    if marque is not None:
        try:
            historique_intact = isinstance(marque, str) and marque == _empreinte_historique(historique)
        except (TypeError, ValueError):
            historique_intact = False
        if not historique_intact:
            raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", "historique modifié : son empreinte ne correspond plus au sceau")
    attendu = _sceau(registre.empreinte, revision, registre.scelle_par, registre.scelle_le,
                     cle if sceau.get("algo") == "hmac-sha256" else None, historique if marque is not None else None)
    if not hmac.compare_digest(str(sceau.get("valeur", "")), attendu["valeur"]):
        raise RefusMCP("REJ-MCP-REGISTRE-SCEAU", "sceau invalide : registre modifié ou scellé avec une autre clé")
    return registre


def serialiser(registre: Registre) -> str:
    """JSON stable, UN OUTIL PAR LIGNE : une modification d'outil est une ligne de diff dans la revue de code."""
    donnees = registre.vers_dict()

    def ligne(valeur: Any) -> str:
        return json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(", ", ": "))

    outils = ",\n".join(f"  {json.dumps(nom, ensure_ascii=False)}: {ligne(e)}" for nom, e in donnees["outils"].items())
    historique = ",\n".join(f"  {ligne(h)}" for h in donnees["historique"])
    return (
        "{\n"
        f' "empreinte_registre": {ligne(donnees["empreinte_registre"])},\n'
        f' "historique": [\n{historique}\n ],\n'
        f' "outils": {{\n{outils}\n }},\n'
        f' "revision": {donnees["revision"]},\n'
        f' "sceau": {ligne(donnees["sceau"])},\n'
        f' "schema": {ligne(donnees["schema"])},\n'
        f' "scelle_le": {ligne(donnees["scelle_le"])},\n'
        f' "scelle_par": {ligne(donnees["scelle_par"])}\n'
        "}\n"
    )


def ecrire(chemin: Path, registre: Registre) -> None:
    """Écriture atomique (fichier temporaire puis remplacement)."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(f".{chemin.name}.{os.getpid()}.tmp")
    temporaire.write_text(serialiser(registre), encoding="utf-8")
    os.replace(temporaire, chemin)


def charger(chemin: Path, *, cle: bytes | None = None) -> Registre:
    chemin = Path(chemin)
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RefusMCP("REJ-MCP-REGISTRE-ABSENT", f"registre introuvable : {chemin}") from None
    except (OSError, ValueError):
        raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", "registre illisible ou JSON invalide") from None
    if not isinstance(donnees, dict):
        raise RefusMCP("REJ-MCP-REGISTRE-ALTERE", "registre mal formé")
    return depuis_dict(donnees, cle=cle)


# --- Comparaison avec le catalogue courant ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Derive:
    nom: str
    parties: tuple[str, ...]  # parmi nom, description, schema
    attendue: str
    obtenue: str


@dataclasses.dataclass(frozen=True)
class RapportVerification:
    revision: int
    outils_courants: int
    derives: tuple[Derive, ...] = ()
    niveaux: tuple[tuple[str, str, str], ...] = ()  # (nom, scellé, courant)
    inconnus: tuple[str, ...] = ()
    absents: tuple[str,
                   ...] = ()  # scellés mais non exposés ici (ex. mémoire sans psycopg) : information, jamais un refus

    @property
    def ok(self) -> bool:
        return not (self.derives or self.niveaux or self.inconnus)

    @property
    def en_quarantaine(self) -> frozenset[str]:
        return frozenset({d.nom for d in self.derives} | {n for n, _, _ in self.niveaux} | set(self.inconnus))


def verifier_definition(registre: Registre, d: DefinitionOutil,
                        surfaces: frozenset[str] | None = None) -> RefusMCP | None:
    """Refus si CET outil, tel qu'exposé maintenant, n'est pas celui qui a été scellé."""
    entree = registre.entrees.get(d.nom)
    if entree is None or (surfaces is not None and entree.surface not in surfaces):
        return RefusMCP("REJ-MCP-OUTIL-INCONNU",
                        f"L'outil {d.nom} n'est pas au registre MCP scellé (révision {registre.revision}) : refusé.",
                        d.nom)
    obtenue = d.empreinte
    if obtenue != entree.empreinte:
        parties = tuple(p for p, h in empreintes_parties(d.nom, d.description, d.schema_entree).items()
                        if h != entree.parties.get(p))
        return RefusMCP(
            "REJ-MCP-EMPREINTE-DERIVE",
            f"L'outil {d.nom} a changé depuis son scellement ({' et '.join(parties) or 'définition'} modifié"
            f"{'s' if len(parties) > 1 else ''}; version {entree.version}, révision {registre.revision}) : refusé "
            "jusqu'à une nouvelle révision approuvée (opsys-metier registre-mcp sceller).", d.nom,
            attendue=entree.empreinte, obtenue=obtenue, parties=parties)
    if d.niveau != entree.niveau:
        return RefusMCP("REJ-MCP-NIVEAU-DERIVE",
                        f"Le niveau d'approbation de {d.nom} est {d.niveau} au lieu de {entree.niveau} scellé : refusé "
                        "jusqu'à une nouvelle révision approuvée.", d.nom, scelle=entree.niveau, courant=d.niveau)
    return None


def comparer(registre: Registre, definitions: Sequence[DefinitionOutil],
             surfaces: frozenset[str] | None = None) -> RapportVerification:
    derives, niveaux, inconnus = [], [], []
    vus = set()
    for d in definitions:
        vus.add(d.nom)
        refus = verifier_definition(registre, d, surfaces)
        if refus is None:
            continue
        if refus.code == "REJ-MCP-OUTIL-INCONNU":
            inconnus.append(d.nom)
        elif refus.code == "REJ-MCP-NIVEAU-DERIVE":
            niveaux.append((d.nom, refus.contexte["scelle"], refus.contexte["courant"]))
        else:
            derives.append(Derive(d.nom, refus.contexte["parties"], refus.contexte["attendue"],
                                  refus.contexte["obtenue"]))
    absents = sorted(n for n, e in registre.entrees.items()
                     if n not in vus and (surfaces is None or e.surface in surfaces))
    return RapportVerification(registre.revision, len(vus), tuple(derives), tuple(niveaux), tuple(sorted(inconnus)),
                               tuple(absents))
