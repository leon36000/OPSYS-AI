"""Manifeste d'un pack sectoriel (`packs/<id>/pack.yaml`, schéma `opsys.pack/v1`), sa validation et son empreinte.

Un pack est le SEUL endroit où vit ce qui dépend du secteur d'activité : vocabulaire, services, glossaire, gabarits de
documents, barèmes à fournir, exemples, bloc injecté dans le prompt de chaque département. Le cœur n'en sait rien.

La validation est fermée, comme celle du gabarit d'évaluation : une clé inconnue, un type faux, un doublon, une
valeur de barème inventée, un fichier non déclaré, un lien symbolique ou une empreinte qui ne colle pas est un refus
typé (`RefusPack`, `REJ-PACK-…`) avec le chemin du champ fautif. Jamais un champ ignoré en silence, jamais de repli.

Empreinte : `packs/<id>/EMPREINTE.sha256` (`sha256:<hex>`) couvre TOUS les fichiers du dossier sauf elle-même
(chemin relatif + sha256 du contenu, triés). Modifier un mot du pack sans régénérer l'empreinte
(`opsys-metier pack empreinte <id> --ecrire`) est un refus `REJ-PACK-EMPREINTE` au chargement : l'empreinte dit QUEL
pack est actif (elle figure dans le bloc injecté au prompt), elle ne remplace pas la revue du changement.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .. import taxonomie
from .codes import RefusPack

SCHEMA_PACK = "opsys.pack/v1"
NOM_MANIFESTE = "pack.yaml"
NOM_EMPREINTE = "EMPREINTE.sha256"
TAILLE_MANIFESTE_MAX = 256 * 1024
TAILLE_GABARIT_MAX = 32 * 1024

# Les dix départements, dans l'ordre. Clés de `blocs` et de `exemples[].departement`.
DEPARTEMENTS = tuple(f"m{n:02d}" for n in range(1, 11))
# Vocabulaire du pack : les seuls jetons `{{…}}` que le cœur peut employer dans un texte (SOUL.md, skills).
JETONS_VOCABULAIRE = ("secteur", "qualificatif_secteur")
# Appellations du métier : le vocabulaire GÉNÉRIQUE d'une PME (client, chantier, soumission, équipe, matériaux) tel que
# CE secteur le dit. Le cœur emploie ces mots-là ; le pack ne les remplace pas, il les précise.
APPELLATIONS = ("client", "chantier", "soumission", "equipe", "materiaux")
SECTIONS_BLOC = ("services", "glossaire", "baremes", "appellations")
STATUTS_BAREME = ("a_fournir_par_entreprise", "exemple_fictif")
STATUT_GABARIT = "exemple"

ID_PACK = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_LANGUE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_IDENTIFIANT = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_CHEMIN_GABARIT = re.compile(r"^[a-z0-9][a-z0-9_./-]{0,127}\.md$")
_EMPREINTE = re.compile(r"^sha256:([0-9a-f]{64})$")
_CONTROLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_CLES_RACINE = {"schema", "id", "version", "nom", "langue", "description", "sectoriel", "fictif", "vocabulaire",
                "appellations", "services", "glossaire", "gabarits", "baremes", "exemples", "blocs",
                "termes_sectoriels", "propositions_profil"}
# Seule clé facultative : un pack peut ne rien proposer au profil de réception (le pack générique n'en propose pas).
_CLES_RACINE_FACULTATIVES = frozenset({"propositions_profil"})
STATUT_PROPOSITION = "a_valider"
# Éléments du profil d'entreprise qu'un pack peut proposer (liste fermée, dans l'ordre) : ce que M1 lit pour qualifier.
ELEMENTS_PROPOSES = (
    taxonomie.CLE_QUESTIONS_QUALIFICATION, taxonomie.CLE_SIGNAUX_PLAINTE, taxonomie.CLE_DESTINATAIRES_TRANSFERT,
    taxonomie.CLE_FENETRE_CONVERSATION, taxonomie.CLE_POIDS_SCORE_LEAD,
)


@dataclass(frozen=True)
class ServicePack:
    code: str
    libelle: str
    mots_cles: tuple[str, ...] = ()


@dataclass(frozen=True)
class TermeGlossaire:
    terme: str
    definition: str


@dataclass(frozen=True)
class Gabarit:
    id: str
    document: str
    fichier: str
    statut: str
    contenu: str
    sha256: str


@dataclass(frozen=True)
class Bareme:
    id: str
    libelle: str
    unite: str
    statut: str
    valeur: str | None
    ou_fournir: str


@dataclass(frozen=True)
class Exemple:
    id: str
    departement: str
    demande: str


@dataclass(frozen=True)
class BlocDepartement:
    ligne: str
    inclure: tuple[str, ...] = ()


@dataclass(frozen=True)
class PropositionsProfil:
    """Ce qu'un pack PROPOSE au profil d'entreprise (rien n'est actif). `elements` : élément -> valeur NORMALISÉE par le
    validateur du profil (celle que `opsys.taxonomie` écrirait), donc adoptable telle quelle."""

    source: str
    elements: Mapping[str, Any]


@dataclass(frozen=True)
class Pack:
    id: str
    version: str
    nom: str
    langue: str
    description: str
    sectoriel: bool
    vocabulaire: Mapping[str, str]
    appellations: Mapping[str, str]
    services: tuple[ServicePack, ...]
    glossaire: tuple[TermeGlossaire, ...]
    gabarits: tuple[Gabarit, ...]
    baremes: tuple[Bareme, ...]
    exemples: tuple[Exemple, ...]
    blocs: Mapping[str, BlocDepartement]
    termes_sectoriels: tuple[str, ...]
    empreinte: str
    dossier: Path = field(compare=False)
    propositions_profil: PropositionsProfil | None = None

    @property
    def generique(self) -> bool:
        return not self.sectoriel


# ============================================================================================ utilitaires de validation
def _texte(valeur: Any, chemin: str, *, maxi: int, mini: int = 1, multiligne: bool = False) -> str:
    if not isinstance(valeur, str) or isinstance(valeur, bool):
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "une chaîne est attendue", chemin)
    brut = valeur.strip()
    if len(brut) < mini or len(brut) > maxi:
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", f"longueur attendue de {mini} à {maxi} caractères", chemin)
    if _CONTROLE.search(brut) or (not multiligne and ("\n" in brut or "\r" in brut)):
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "caractère de contrôle ou saut de ligne interdit", chemin)
    if "{{" in brut or "}}" in brut:
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "les accolades doubles sont réservées aux jetons du cœur", chemin)
    return brut


def _vide_ou_texte(valeur: Any, chemin: str, *, maxi: int) -> str:
    if valeur == "":
        return ""
    return _texte(valeur, chemin, maxi=maxi)


def _objet(valeur: Any, chemin: str, permises: set[str] | frozenset[str], *, requises: set[str] | None = None
           ) -> Mapping[str, Any]:
    if not isinstance(valeur, Mapping):
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "un objet est attendu", chemin)
    inconnues = sorted(map(str, set(valeur) - set(permises)))
    if inconnues:
        raise RefusPack("REJ-PACK-CLE-INCONNUE", f"clés inconnues {inconnues} (permises : {sorted(permises)})", chemin)
    manquantes = sorted((requises if requises is not None else set(permises)) - set(valeur))
    if manquantes:
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", f"clés manquantes {manquantes}", chemin)
    return valeur


def _liste(valeur: Any, chemin: str, *, maxi: int) -> list[Any]:
    if not isinstance(valeur, list):
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "une liste est attendue", chemin)
    if len(valeur) > maxi:
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", f"au plus {maxi} éléments", chemin)
    return valeur


def _booleen(valeur: Any, chemin: str) -> bool:
    if not isinstance(valeur, bool):
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "un booléen est attendu", chemin)
    return valeur


def _sans_doublon(valeurs: list[str], chemin: str, quoi: str) -> None:
    vus: set[str] = set()
    for valeur in valeurs:
        cle = valeur.casefold()
        if cle in vus:
            raise RefusPack("REJ-PACK-DOUBLON", f"{quoi} déclaré deux fois : {valeur!r}", chemin)
        vus.add(cle)


# ============================================================================================ lecture YAML stricte
class _Chargeur(yaml.SafeLoader):
    """`SafeLoader` qui refuse une clé en double (PyYAML garde sinon la dernière, en silence)."""


def _construire_objet(chargeur: _Chargeur, noeud: yaml.MappingNode, profond: bool = False) -> dict[Any, Any]:
    chargeur.flatten_mapping(noeud)
    objet: dict[Any, Any] = {}
    for cle_noeud, valeur_noeud in noeud.value:
        cle = chargeur.construct_object(cle_noeud, deep=profond)
        if cle in objet:
            raise yaml.YAMLError(f"clé en double : {cle!r}")
        objet[cle] = chargeur.construct_object(valeur_noeud, deep=profond)
    return objet


_Chargeur.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construire_objet)


def lire_yaml_strict(octets: bytes, chemin: str) -> Any:
    """YAML sûr, sans clé en double ni alias (`&`/`*` : expansion en cascade), borné en taille."""
    if len(octets) > TAILLE_MANIFESTE_MAX:
        raise RefusPack("REJ-PACK-ILLISIBLE", f"manifeste de plus de {TAILLE_MANIFESTE_MAX} octets", chemin)
    try:
        texte = octets.decode("utf-8")
        if any(isinstance(e, yaml.AliasEvent) for e in yaml.parse(texte, Loader=_Chargeur)):
            raise RefusPack("REJ-PACK-ILLISIBLE", "alias YAML interdit", chemin)
        return yaml.load(texte, Loader=_Chargeur)  # noqa: S506 — _Chargeur dérive de SafeLoader
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RefusPack("REJ-PACK-ILLISIBLE", f"YAML illisible : {exc}".splitlines()[0], chemin) from exc


# ============================================================================================ empreinte
def _fichiers_du_pack(dossier: Path) -> list[Path]:
    """Tous les fichiers du dossier (récursif), triés ; un lien symbolique ou un fichier spécial est un refus."""
    trouves: list[Path] = []
    for chemin in sorted(dossier.rglob("*")):
        relatif = chemin.relative_to(dossier).as_posix()
        if chemin.is_symlink():
            raise RefusPack("REJ-PACK-FICHIER-INVALIDE", "lien symbolique interdit", relatif)
        if chemin.is_dir():
            continue
        if not chemin.is_file():
            raise RefusPack("REJ-PACK-FICHIER-INVALIDE", "fichier spécial interdit", relatif)
        if any(partie.startswith(".") or partie == "__pycache__" for partie in chemin.relative_to(dossier).parts):
            raise RefusPack("REJ-PACK-FICHIER-INVALIDE", "fichier caché ou de cache interdit", relatif)
        trouves.append(chemin)
    return trouves


def calculer_empreinte(dossier: Path) -> str:
    """`sha256:<hex>` du contenu du pack (tous les fichiers sauf `EMPREINTE.sha256`)."""
    resume = hashlib.sha256()
    for chemin in _fichiers_du_pack(dossier):
        relatif = chemin.relative_to(dossier).as_posix()
        if relatif == NOM_EMPREINTE:
            continue
        contenu = hashlib.sha256(chemin.read_bytes()).hexdigest()
        resume.update(relatif.encode("utf-8") + b"\0" + contenu.encode() + b"\n")
    return f"sha256:{resume.hexdigest()}"


def _verifier_empreinte(dossier: Path) -> str:
    fichier = dossier / NOM_EMPREINTE
    if not fichier.is_file() or fichier.is_symlink():
        raise RefusPack("REJ-PACK-EMPREINTE-ABSENTE",
                        "pas d'empreinte : `opsys-metier pack empreinte <id> --ecrire` après revue", NOM_EMPREINTE)
    declaree = fichier.read_text(encoding="utf-8").strip()
    if not _EMPREINTE.fullmatch(declaree):
        raise RefusPack("REJ-PACK-EMPREINTE", "empreinte mal formée (attendu : sha256:<64 hexadécimaux>)",
                        NOM_EMPREINTE)
    reelle = calculer_empreinte(dossier)
    if declaree != reelle:
        raise RefusPack("REJ-PACK-EMPREINTE",
                        "le contenu du pack ne correspond plus à son empreinte : il a été modifié sans revue",
                        NOM_EMPREINTE)
    return reelle


# ============================================================================================ validation des blocs
def _valider_services(brut: Any) -> tuple[ServicePack, ...]:
    services = []
    for i, entree in enumerate(_liste(brut, "services", maxi=60)):
        chemin = f"services[{i}]"
        o = _objet(entree, chemin, {"code", "libelle", "mots_cles"}, requises={"code", "libelle"})
        code = _texte(o["code"], f"{chemin}.code", maxi=64)
        if not _CODE.fullmatch(code):
            raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "code attendu : [a-z][a-z0-9_]*", f"{chemin}.code")
        mots = tuple(_texte(m, f"{chemin}.mots_cles[{j}]", maxi=80)
                     for j, m in enumerate(_liste(o.get("mots_cles", []), f"{chemin}.mots_cles", maxi=20)))
        services.append(ServicePack(code, _texte(o["libelle"], f"{chemin}.libelle", maxi=120), mots))
    _sans_doublon([s.code for s in services], "services", "service")
    return tuple(services)


def _valider_glossaire(brut: Any) -> tuple[TermeGlossaire, ...]:
    termes = []
    for i, entree in enumerate(_liste(brut, "glossaire", maxi=200)):
        chemin = f"glossaire[{i}]"
        o = _objet(entree, chemin, {"terme", "definition"})
        termes.append(TermeGlossaire(_texte(o["terme"], f"{chemin}.terme", maxi=80),
                                     _texte(o["definition"], f"{chemin}.definition", maxi=400)))
    _sans_doublon([t.terme for t in termes], "glossaire", "terme")
    return tuple(termes)


def _lire_gabarit(dossier: Path, relatif: str, chemin: str) -> tuple[str, str]:
    if not _CHEMIN_GABARIT.fullmatch(relatif) or ".." in PurePosixPath(relatif).parts:
        raise RefusPack("REJ-PACK-FICHIER-INVALIDE", "chemin relatif en minuscules, sans `..`, terminé par .md", chemin)
    cible = dossier / relatif
    if cible.is_symlink() or not cible.is_file():
        raise RefusPack("REJ-PACK-FICHIER-INVALIDE", "fichier déclaré absent (ou lien symbolique)", chemin)
    octets = cible.read_bytes()
    if len(octets) > TAILLE_GABARIT_MAX:
        raise RefusPack("REJ-PACK-FICHIER-INVALIDE", f"plus de {TAILLE_GABARIT_MAX} octets", chemin)
    try:
        contenu = octets.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RefusPack("REJ-PACK-FICHIER-INVALIDE", "UTF-8 attendu", chemin) from exc
    return contenu, hashlib.sha256(octets).hexdigest()


def _valider_gabarits(brut: Any, dossier: Path) -> tuple[Gabarit, ...]:
    gabarits = []
    for i, entree in enumerate(_liste(brut, "gabarits", maxi=40)):
        chemin = f"gabarits[{i}]"
        o = _objet(entree, chemin, {"id", "document", "fichier", "statut"})
        identifiant = _texte(o["id"], f"{chemin}.id", maxi=64)
        if not _IDENTIFIANT.fullmatch(identifiant):
            raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "identifiant attendu : [a-z][a-z0-9_-]*", f"{chemin}.id")
        if o["statut"] != STATUT_GABARIT:
            raise RefusPack("REJ-PACK-CHAMP-INVALIDE", f"statut attendu : {STATUT_GABARIT!r} (un gabarit est un point "
                            "de départ à revoir par l'entreprise, jamais un texte validé)", f"{chemin}.statut")
        relatif = _texte(o["fichier"], f"{chemin}.fichier", maxi=128)
        contenu, empreinte = _lire_gabarit(dossier, relatif, f"{chemin}.fichier")
        gabarits.append(Gabarit(identifiant, _texte(o["document"], f"{chemin}.document", maxi=80), relatif,
                                STATUT_GABARIT, contenu, empreinte))
    _sans_doublon([g.id for g in gabarits], "gabarits", "gabarit")
    _sans_doublon([g.fichier for g in gabarits], "gabarits", "fichier de gabarit")
    return tuple(gabarits)


def _valeur_bareme(valeur: Any, chemin: str) -> str:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float, str)):
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "un nombre est attendu", chemin)
    try:
        nombre = Decimal(str(valeur))
    except InvalidOperation as exc:
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "un nombre est attendu", chemin) from exc
    if not nombre.is_finite() or nombre < 0:
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "un nombre fini et positif ou nul est attendu", chemin)
    return format(nombre, "f")


def _valider_baremes(brut: Any) -> tuple[Bareme, ...]:
    baremes = []
    for i, entree in enumerate(_liste(brut, "baremes", maxi=100)):
        chemin = f"baremes[{i}]"
        o = _objet(entree, chemin, {"id", "libelle", "unite", "statut", "valeur", "ou_fournir"})
        identifiant = _texte(o["id"], f"{chemin}.id", maxi=64)
        if not _IDENTIFIANT.fullmatch(identifiant):
            raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "identifiant attendu : [a-z][a-z0-9_-]*", f"{chemin}.id")
        ou_fournir = _texte(o["ou_fournir"], f"{chemin}.ou_fournir", maxi=160)
        statut = o["statut"]
        if statut not in STATUTS_BAREME:
            raise RefusPack("REJ-PACK-CHAMP-INVALIDE", f"statut attendu parmi {list(STATUTS_BAREME)}",
                            f"{chemin}.statut")
        if statut == "a_fournir_par_entreprise":
            # Fail-closed (AGENTS.md) : jamais une valeur par défaut inventée pour un chiffre à fournir.
            if o["valeur"] is not None:
                raise RefusPack("REJ-PACK-BAREME-INVENTE",
                                "un barème « à fournir par l'entreprise » ne porte aucune valeur (null)",
                                f"{chemin}.valeur")
            valeur = None
        else:
            valeur = _valeur_bareme(o["valeur"], f"{chemin}.valeur")
        baremes.append(Bareme(identifiant, _texte(o["libelle"], f"{chemin}.libelle", maxi=160),
                              _texte(o["unite"], f"{chemin}.unite", maxi=40), statut, valeur, ou_fournir))
    _sans_doublon([b.id for b in baremes], "baremes", "barème")
    return tuple(baremes)


def _valider_exemples(brut: Any) -> tuple[Exemple, ...]:
    exemples = []
    for i, entree in enumerate(_liste(brut, "exemples", maxi=100)):
        chemin = f"exemples[{i}]"
        o = _objet(entree, chemin, {"id", "departement", "demande", "fictif"})
        if o["fictif"] is not True:
            raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "`fictif: true` est obligatoire : aucune donnée réelle",
                            f"{chemin}.fictif")
        identifiant = _texte(o["id"], f"{chemin}.id", maxi=64)
        if not _IDENTIFIANT.fullmatch(identifiant):
            raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "identifiant attendu : [a-z][a-z0-9_-]*", f"{chemin}.id")
        if o["departement"] not in DEPARTEMENTS:
            raise RefusPack("REJ-PACK-CHAMP-INVALIDE", f"département attendu parmi {list(DEPARTEMENTS)}",
                            f"{chemin}.departement")
        exemples.append(Exemple(identifiant, o["departement"], _texte(o["demande"], f"{chemin}.demande", maxi=400)))
    _sans_doublon([e.id for e in exemples], "exemples", "exemple")
    return tuple(exemples)


def _valider_blocs(brut: Any, sectoriel: bool) -> dict[str, BlocDepartement]:
    if not isinstance(brut, Mapping):
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "un objet est attendu", "blocs")
    if not sectoriel:
        if brut:
            raise RefusPack("REJ-PACK-GENERIQUE-NON-VIDE", "un pack non sectoriel ne porte aucun bloc de département",
                            "blocs")
        return {}
    inconnus = sorted(map(str, set(brut) - set(DEPARTEMENTS)))
    if inconnus:
        raise RefusPack("REJ-PACK-CLE-INCONNUE", f"départements inconnus {inconnus}", "blocs")
    absents = [d for d in DEPARTEMENTS if d not in brut]
    if absents:
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", f"un pack sectoriel dit explicitement chacun des dix départements ; "
                        f"absents : {absents}", "blocs")
    blocs = {}
    for code in DEPARTEMENTS:
        chemin = f"blocs.{code}"
        o = _objet(brut[code], chemin, {"ligne", "inclure"})
        inclure = []
        for j, section in enumerate(_liste(o["inclure"], f"{chemin}.inclure", maxi=len(SECTIONS_BLOC))):
            if section not in SECTIONS_BLOC:
                raise RefusPack("REJ-PACK-CHAMP-INVALIDE", f"section attendue parmi {list(SECTIONS_BLOC)}",
                                f"{chemin}.inclure[{j}]")
            inclure.append(section)
        _sans_doublon(inclure, f"{chemin}.inclure", "section")
        blocs[code] = BlocDepartement(_texte(o["ligne"], f"{chemin}.ligne", maxi=600), tuple(inclure))
    return blocs


def _valider_termes(brut: Any) -> tuple[str, ...]:
    termes = [_texte(t, f"termes_sectoriels[{i}]", maxi=60, mini=3)
              for i, t in enumerate(_liste(brut, "termes_sectoriels", maxi=200))]
    _sans_doublon(termes, "termes_sectoriels", "terme")
    return tuple(termes)


# ============================================================================================ propositions de profil
ETIQUETTE_RECOMMANDATION = "recommandation, non validée"


def _statut_a_valider(entree: Mapping[str, Any], chemin: str) -> None:
    """Un pack ne livre jamais un élément « validé » : seule l'adoption d'une personne rend un élément actif."""
    if entree.get("statut") != STATUT_PROPOSITION:
        raise RefusPack("REJ-PACK-PROPOSITION-VALIDEE",
                        f"`statut: {STATUT_PROPOSITION}` obligatoire (un pack propose, une personne adopte ; reçu "
                        f"{entree.get('statut')!r})", f"{chemin}.statut")


def _normaliser_profil(fn, valeur: Any, chemin: str) -> Any:
    """Le validateur du PROFIL juge la proposition : une valeur qu'il refuserait ne sera jamais adoptable."""
    try:
        return fn(valeur)
    except taxonomie.ProfilInvalide as exc:
        raise RefusPack("REJ-PACK-PROPOSITION-INVALIDE", str(exc), chemin) from exc


def _entree_propre(brut: Any, chemin: str, cles: set[str], requises: set[str]) -> Mapping[str, Any]:
    entree = _objet(brut, chemin, cles | {"statut"}, requises=requises)
    _statut_a_valider(entree, chemin)
    return entree


def _valider_questions_proposees(brut: Any, codes_services: set[str], base: str) -> Any:
    if not isinstance(brut, Mapping) or not brut:
        raise RefusPack("REJ-PACK-PROPOSITION-INVALIDE", "un objet {service: [questions]} non vide est attendu", base)
    propres: dict[str, Any] = {}
    for service, liste in brut.items():
        chemin = f"{base}.{service}"
        if service not in codes_services:
            raise RefusPack("REJ-PACK-PROPOSITION-INVALIDE",
                            f"service {service!r} absent des services du pack ({sorted(codes_services)})", chemin)
        brutes = []
        for i, q in enumerate(_liste(liste, chemin, maxi=50)):
            entree = _entree_propre(q, f"{chemin}[{i}]", {"code", "question", "mots_cles", "photos"},
                                    {"code", "question"})
            brutes.append({cle: v for cle, v in entree.items() if cle != "statut"})
        propres.update(_normaliser_profil(taxonomie.normaliser_questions_qualification, {service: brutes}, chemin))
    return propres


def _valider_signaux_proposes(brut: Any, base: str) -> Any:
    if not isinstance(brut, Mapping):
        raise RefusPack("REJ-PACK-PROPOSITION-INVALIDE", "un objet {catégorie: {termes}} est attendu", base)
    bruts: dict[str, Any] = {}
    for categorie, entree in brut.items():
        o = _entree_propre(entree, f"{base}.{categorie}", {"termes"}, {"termes"})
        bruts[categorie] = o["termes"]
    return _normaliser_profil(taxonomie.normaliser_signaux_plainte, bruts, base)


def _valider_destinataires_proposes(brut: Any, base: str) -> Any:
    if not isinstance(brut, Mapping):
        raise RefusPack("REJ-PACK-PROPOSITION-INVALIDE", "un objet {type: {role}} est attendu", base)
    bruts: dict[str, Any] = {}
    for type_transfert, entree in brut.items():
        o = _entree_propre(entree, f"{base}.{type_transfert}", {"role"}, {"role"})
        bruts[type_transfert] = o["role"]
    return _normaliser_profil(taxonomie.normaliser_destinataires_transfert, bruts, base)


def _valider_valeur_chiffree(brut: Any, base: str, cle_valeur: str, normaliser) -> Any:
    """Fenêtre et poids : une valeur chiffrée n'est qu'une recommandation illustrative, dite telle et justifiée."""
    o = _entree_propre(brut, base, {cle_valeur, "etiquette", "justification"},
                       {cle_valeur, "etiquette", "justification"})
    if o["etiquette"] != ETIQUETTE_RECOMMANDATION:
        raise RefusPack("REJ-PACK-PROPOSITION-INVALIDE",
                        f"étiquette attendue : {ETIQUETTE_RECOMMANDATION!r} (une valeur chiffrée n'est jamais "
                        "présentée comme validée)", f"{base}.etiquette")
    _texte(o["justification"], f"{base}.justification", maxi=600, multiligne=True)
    return _normaliser_profil(normaliser, o[cle_valeur], base)


def _valider_propositions(brut: Any, services: tuple[ServicePack, ...]) -> PropositionsProfil:
    base = "propositions_profil"
    o = _objet(brut, base, {"source", *ELEMENTS_PROPOSES}, requises={"source"})
    source = _texte(o["source"], f"{base}.source", maxi=600, multiligne=True)
    elements: dict[str, Any] = {}
    for element in ELEMENTS_PROPOSES:
        if element not in o:
            continue
        chemin = f"{base}.{element}"
        if element == taxonomie.CLE_QUESTIONS_QUALIFICATION:
            valeur = _valider_questions_proposees(o[element], {s.code for s in services}, chemin)
        elif element == taxonomie.CLE_SIGNAUX_PLAINTE:
            valeur = _valider_signaux_proposes(o[element], chemin)
        elif element == taxonomie.CLE_DESTINATAIRES_TRANSFERT:
            valeur = _valider_destinataires_proposes(o[element], chemin)
        elif element == taxonomie.CLE_FENETRE_CONVERSATION:
            valeur = _valider_valeur_chiffree(o[element], chemin, "valeur", taxonomie.normaliser_fenetre_conversation)
        else:
            valeur = _valider_valeur_chiffree(o[element], chemin, "valeurs", taxonomie.normaliser_poids_score_lead)
        elements[element] = valeur
    if not elements:
        raise RefusPack("REJ-PACK-PROPOSITION-INVALIDE", "au moins un élément est proposé (ou retire la clé)", base)
    return PropositionsProfil(source, elements)


# ============================================================================================ chargement
def charger_dossier(dossier: Path, *, id_attendu: str | None = None, verifier_empreinte: bool = True) -> Pack:
    """Charge et valide le pack du `dossier` ; l'identifiant du manifeste doit être le nom du dossier.

    `verifier_empreinte=False` ne sert qu'à REGÉNÉRER l'empreinte après revue (`opsys-metier pack empreinte --ecrire`) :
    tout le reste est validé, l'empreinte rendue est celle du contenu actuel.
    """
    manifeste = dossier / NOM_MANIFESTE
    if dossier.is_symlink() or not dossier.is_dir() or manifeste.is_symlink() or not manifeste.is_file():
        raise RefusPack("REJ-PACK-INTROUVABLE", f"pas de {NOM_MANIFESTE} dans {dossier.name!r}", dossier.name)
    donnees = lire_yaml_strict(manifeste.read_bytes(), f"{dossier.name}/{NOM_MANIFESTE}")
    if not isinstance(donnees, Mapping):
        raise RefusPack("REJ-PACK-ILLISIBLE", "un objet YAML est attendu à la racine", NOM_MANIFESTE)
    if donnees.get("schema") != SCHEMA_PACK:
        raise RefusPack("REJ-PACK-SCHEMA", f"schema attendu : {SCHEMA_PACK!r}", "schema")
    o = _objet(donnees, "", _CLES_RACINE, requises=set(_CLES_RACINE - _CLES_RACINE_FACULTATIVES))
    identifiant = _texte(o["id"], "id", maxi=64)
    if not ID_PACK.fullmatch(identifiant) or identifiant != (id_attendu or dossier.name):
        raise RefusPack("REJ-PACK-ID-INVALIDE", f"l'identifiant {identifiant!r} doit être le nom du dossier "
                        f"({(id_attendu or dossier.name)!r}), en minuscules et tirets", "id")
    version = _texte(o["version"], "version", maxi=32)
    if not _VERSION.fullmatch(version):
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "version sémantique attendue (x.y.z)", "version")
    langue = _texte(o["langue"], "langue", maxi=10)
    if not _LANGUE.fullmatch(langue):
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "langue attendue au format fr-CA", "langue")
    sectoriel = _booleen(o["sectoriel"], "sectoriel")
    if _booleen(o["fictif"], "fictif") is not True:
        raise RefusPack("REJ-PACK-CHAMP-INVALIDE", "`fictif: true` est obligatoire : les exemples et barèmes d'un pack "
                        "ne viennent d'aucune entreprise réelle", "fictif")

    vocab = _objet(o["vocabulaire"], "vocabulaire", set(JETONS_VOCABULAIRE))
    vocabulaire = {cle: (_texte(vocab[cle], f"vocabulaire.{cle}", maxi=120) if sectoriel
                         else _vide_ou_texte(vocab[cle], f"vocabulaire.{cle}", maxi=120))
                   for cle in JETONS_VOCABULAIRE}
    if not sectoriel and any(vocabulaire.values()):
        raise RefusPack("REJ-PACK-GENERIQUE-NON-VIDE", "un pack non sectoriel a un vocabulaire de secteur vide",
                        "vocabulaire")
    appel = _objet(o["appellations"], "appellations", set(APPELLATIONS))
    appellations = {cle: _texte(appel[cle], f"appellations.{cle}", maxi=160) for cle in APPELLATIONS}

    services = _valider_services(o["services"])
    glossaire = _valider_glossaire(o["glossaire"])
    gabarits = _valider_gabarits(o["gabarits"], dossier)
    baremes = _valider_baremes(o["baremes"])
    exemples = _valider_exemples(o["exemples"])
    blocs = _valider_blocs(o["blocs"], sectoriel)
    termes = _valider_termes(o["termes_sectoriels"])
    if not sectoriel:
        for nom, contenu in (("services", services), ("glossaire", glossaire), ("gabarits", gabarits),
                             ("baremes", baremes), ("exemples", exemples), ("termes_sectoriels", termes)):
            if contenu:
                raise RefusPack("REJ-PACK-GENERIQUE-NON-VIDE",
                                f"un pack non sectoriel ne porte aucun contenu de secteur ({nom})", nom)
        if "propositions_profil" in o:
            raise RefusPack("REJ-PACK-GENERIQUE-NON-VIDE",
                            "un pack non sectoriel ne propose aucun élément de profil", "propositions_profil")
    elif not termes:
        raise RefusPack("REJ-PACK-TERMES-ABSENTS", "un pack sectoriel liste ses termes : sans eux, la garde du cœur "
                        "n'a rien à garder", "termes_sectoriels")

    propositions = _valider_propositions(o["propositions_profil"], services) if "propositions_profil" in o else None
    # Fichiers : seuls le manifeste, l'empreinte et les gabarits déclarés ; rien de plus (rien n'échappe à la revue).
    declares = {NOM_MANIFESTE, NOM_EMPREINTE, *(g.fichier for g in gabarits)}
    for chemin in _fichiers_du_pack(dossier):
        relatif = chemin.relative_to(dossier).as_posix()
        if relatif not in declares:
            raise RefusPack("REJ-PACK-FICHIER-INVALIDE", "fichier non déclaré dans le manifeste", relatif)
    empreinte = _verifier_empreinte(dossier) if verifier_empreinte else calculer_empreinte(dossier)
    return Pack(
        id=identifiant, version=version, nom=_texte(o["nom"], "nom", maxi=120), langue=langue,
        description=_texte(o["description"], "description", maxi=600, multiligne=True), sectoriel=sectoriel,
        vocabulaire=vocabulaire, appellations=appellations, services=services, glossaire=glossaire,
        gabarits=gabarits, baremes=baremes, exemples=exemples, blocs=blocs, termes_sectoriels=termes,
        empreinte=empreinte, dossier=dossier, propositions_profil=propositions,
    )
