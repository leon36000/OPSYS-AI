"""Base de règles fiscales versionnée par date d'effet, sourcée, revue par deux personnes
(`docs/architecture/BASE-FISCALE.md`).

Doctrine (AGENTS.md « fail-closed », « le code calcule, le LLM orchestre ») :

- Un paramètre fiscal est une LIGNE DE DONNÉES (`contracts/regles_fiscales.v1.yaml`), jamais une constante recopiée
  dans un calcul : identifiant, valeur en TEXTE décimal, unité, période d'effet, juridiction, sources officielles
  (organisme, titre, URL, date de consultation), saisie, revues, statut, empreinte.
- Le chargeur est STRICT : il refuse une clé inconnue, une clé YAML dupliquée, une valeur qui n'est pas un texte
  décimal canonique, un trou ou un chevauchement de dates, un paramètre sans source, une modification silencieuse
  (empreinte) et un statut que les revues ne prouvent pas.
- Le statut est PROUVÉ, pas déclaré : `approuve` = au moins DEUX réviseurs distincts (casse ignorée), autres que
  l'auteur de la saisie, dont chaque revue porte l'empreinte COURANTE du paramètre. Modifier une valeur change son
  empreinte : les revues antérieures ne comptent plus. L'identité d'un réviseur est DÉCLARATIVE dans le fichier ;
  l'authentification réelle est celle de la revue Git (voir `docs/architecture/BASE-FISCALE.md`, « Limites »).
- Deux modes, toujours EXPLICITES (aucun mode par défaut) : `officiel` ne sert qu'un paramètre `approuve` ; `essai`
  sert aussi les brouillons, mais tout résultat porte `essai: true` et un avertissement.
- Un paramètre sans valeur (`non_renseigne`) est une promesse de source, pas un chiffre : sa résolution est un refus
  typé dans les deux modes, jamais une valeur par défaut.

Module pur : aucune horloge (la date d'effet demandée est un argument), aucune écriture, aucun réseau.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from . import analyse, taxes, verdicts_fiscal

__all__ = [
    "AVERTISSEMENT_ESSAI",
    "CHEMIN_BASE_PAR_DEFAUT",
    "MODE_ESSAI",
    "MODE_OFFICIEL",
    "SCHEMA",
    "BaseFiscale",
    "Parametre",
    "calculer_taxes_selon_base",
    "charger_base",
    "charger_base_par_defaut",
    "diagnostiquer",
    "empreinte_parametre",
    "marquage_recu",
    "recu_regle",
    "resoudre",
    "resume_base",
    "taux_depuis_base",
]

SCHEMA = "opsys.regles-fiscales/v1"
MODE_OFFICIEL = "officiel"
MODE_ESSAI = "essai"
_MODES = frozenset({MODE_OFFICIEL, MODE_ESSAI})
AVERTISSEMENT_ESSAI = (
    "MODE ESSAI : au moins un paramètre n'a pas l'approbation de deux réviseurs distincts. Résultat pour essai "
    "seulement, jamais une retenue, une taxe ou une déclaration officielle."
)
CHEMIN_BASE_PAR_DEFAUT = Path(__file__).resolve().parents[2] / "contracts" / "regles_fiscales.v1.yaml"

_TAILLE_MAX = 2 * 1024 * 1024
_JURIDICTIONS = frozenset({"FED", "QC"})
_UNITES = frozenset({"CAD", "ratio", "nombre"})
_STATUTS = ("brouillon", "revu_1", "approuve")
_RE_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
_RE_VALEUR = re.compile(r"^-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,12})?$")
_RE_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")
_RE_PERSONNE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}$")
_CHAMPS_PARAMETRE = frozenset(
    {
        "id",
        "juridiction",
        "libelle",
        "valeur",
        "unite",
        "effet",
        "sources",
        "saisie",
        "revues",
        "statut",
        "empreinte",
        "note",
        "non_renseigne",
    }
)
_CHAMPS_REQUIS = frozenset(
    {
        "id",
        "juridiction",
        "libelle",
        "valeur",
        "unite",
        "effet",
        "sources",
        "saisie",
        "revues",
        "statut",
        "empreinte",
    }
)
_CHAMPS_EMPREINTE = (
    "id",
    "juridiction",
    "libelle",
    "valeur",
    "unite",
    "effet",
    "sources",
    "saisie",
    "note",
    "non_renseigne",
)
_CHAMPS_SOURCE = frozenset({"organisme", "titre", "url", "consulte_le", "reference", "sha256"})
_CHAMPS_SOURCE_REQUIS = frozenset({"organisme", "titre", "url", "consulte_le"})
_CHAMPS_REVUE = frozenset({"reviewer", "le", "decision", "empreinte"})
# Le pont TPS/TVQ : identifiants de `taux_fiscaux.v1.yaml` -> identifiants de la base.
_TAXES_BASE = {"tps_federale": "fed.tps.taux", "tvq_quebec": "qc.tvq.taux"}


def _v(code: str, detail: str) -> dict[str, str]:
    return verdicts_fiscal.construire_verdict(code, detail)


def _date_iso(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
        return None
    try:
        jour = date.fromisoformat(valeur)
    except ValueError:
        return None
    return jour if jour.isoformat() == valeur else None


def _texte(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


# --------------------------------------------------------------------------------------------- types
@dataclass(frozen=True)
class Parametre:
    identifiant: str
    juridiction: str
    libelle: str
    valeur: Decimal | None
    unite: str
    debut: date
    fin: date | None
    sources: tuple[Mapping[str, Any], ...]
    saisie: Mapping[str, str]
    statut: str
    empreinte: str
    non_renseigne: Mapping[str, str] | None
    note: str | None
    revues_valides: int

    def couvre(self, jour: date) -> bool:
        return self.debut <= jour and (self.fin is None or jour <= self.fin)


@dataclass(frozen=True)
class BaseFiscale:
    """`parametres` : identifiant -> versions triées par date de début, sans trou ni chevauchement."""

    parametres: Mapping[str, tuple[Parametre, ...]]
    empreinte: str


def empreinte_parametre(parametre: Mapping[str, Any]) -> str:
    """SHA-256 du contenu SUBSTANTIEL (identifiant, valeur, unité, effet, sources, saisie, note). Ni les revues ni le
    statut n'y entrent : ce sont elles qui se lient à cette empreinte."""
    corps = {cle: parametre[cle] for cle in _CHAMPS_EMPREINTE if cle in parametre}
    texte = json.dumps(corps, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------- chargement
class _ChargeurStrict(yaml.SafeLoader):
    """SafeLoader qui refuse une clé dupliquée : sinon la dernière gagnerait en silence."""


def _mapping_sans_doublon(chargeur: _ChargeurStrict, noeud: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    vues: set[Any] = set()
    for noeud_cle, _ in noeud.value:
        cle = chargeur.construct_object(noeud_cle, deep=deep)
        if cle in vues:
            raise yaml.constructor.ConstructorError(None, None, f"clé dupliquée : {cle!r}", noeud_cle.start_mark)
        vues.add(cle)
    return chargeur.construct_mapping(noeud, deep)


_ChargeurStrict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_sans_doublon)


def _parse_valeur(parametre: Mapping[str, Any]) -> tuple[Decimal | None, dict[str, str] | None]:
    ident = parametre["id"]
    valeur = parametre["valeur"]
    if valeur is None:
        return None, None
    if not isinstance(valeur, str):
        return None, _v("REJ-BASEFISC-VALEUR-INVALIDE", f"{ident} : la valeur doit être un texte décimal")
    if _RE_VALEUR.fullmatch(valeur) is None:
        return None, _v("REJ-BASEFISC-VALEUR-INVALIDE", f"{ident} : texte décimal canonique requis, reçu {valeur!r}")
    try:
        nombre = Decimal(valeur)
    except InvalidOperation:
        return None, _v("REJ-BASEFISC-VALEUR-INVALIDE", f"{ident} : valeur illisible")
    unite = parametre["unite"]
    if unite == "ratio" and not Decimal(0) <= nombre <= Decimal(1):
        return None, _v("REJ-BASEFISC-VALEUR-INVALIDE", f"{ident} : un ratio est une fraction entre 0 et 1")
    if unite in {"CAD", "nombre"} and nombre < 0:
        return None, _v("REJ-BASEFISC-VALEUR-INVALIDE", f"{ident} : valeur négative refusée pour l'unité {unite}")
    return nombre, None


def _valider_sources(parametre: Mapping[str, Any]) -> dict[str, str] | None:
    ident = parametre["id"]
    sources = parametre["sources"]
    if not isinstance(sources, list):
        return _v("REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : `sources` doit être une liste")
    if parametre["valeur"] is not None and not sources:
        return _v(
            "REJ-BASEFISC-SOURCE-ABSENTE", f"{ident} : aucune source officielle — un paramètre sans source est refusé"
        )
    for source in sources:
        if not isinstance(source, dict) or not _CHAMPS_SOURCE_REQUIS <= set(source) <= _CHAMPS_SOURCE:
            return _v(
                "REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : source mal formée (clés organisme, titre, url, consulte_le)"
            )
        if not _texte(source["organisme"]) or not _texte(source["titre"]):
            return _v(
                "REJ-BASEFISC-SOURCE-INCOMPLETE", f"{ident} : la source exige un organisme et un titre de document"
            )
        if source["url"] is not None and not isinstance(source["url"], str):
            return _v("REJ-BASEFISC-SOURCE-INCOMPLETE", f"{ident} : url illisible")
        if source["consulte_le"] is not None and _date_iso(source["consulte_le"]) is None:
            return _v("REJ-BASEFISC-DATE-INVALIDE", f"{ident} : date de consultation invalide")
        sha = source.get("sha256")
        if sha is not None and (not isinstance(sha, str) or _RE_EMPREINTE.fullmatch(sha) is None):
            return _v("REJ-BASEFISC-SOURCE-INCOMPLETE", f"{ident} : sha256 de capture mal formé")
    return None


def _valider_revues(parametre: Mapping[str, Any], saisie_le: date) -> tuple[int, dict[str, str] | None]:
    """Nombre de réviseurs VALIDES : distincts (casse ignorée), autres que l'auteur, sur l'empreinte courante."""
    ident = parametre["id"]
    revues = parametre["revues"]
    if not isinstance(revues, list):
        return 0, _v("REJ-BASEFISC-REVUE-INVALIDE", f"{ident} : `revues` doit être une liste")
    auteur = parametre["saisie"]["par"].casefold()
    valides: set[str] = set()
    for revue in revues:
        if not isinstance(revue, dict) or set(revue) != _CHAMPS_REVUE:
            return 0, _v(
                "REJ-BASEFISC-REVUE-INVALIDE", f"{ident} : revue mal formée (reviewer, le, decision, empreinte)"
            )
        if revue["decision"] != "approuve":
            return 0, _v("REJ-BASEFISC-REVUE-INVALIDE", f"{ident} : seule la décision « approuve » s'enregistre")
        if not isinstance(revue["reviewer"], str) or _RE_PERSONNE.fullmatch(revue["reviewer"]) is None:
            return 0, _v("REJ-BASEFISC-REVUE-INVALIDE", f"{ident} : identité du réviseur illisible")
        jour = _date_iso(revue["le"])
        if jour is None or jour < saisie_le:
            return 0, _v("REJ-BASEFISC-REVUE-INVALIDE", f"{ident} : date de revue invalide ou antérieure à la saisie")
        if not isinstance(revue["empreinte"], str):
            return 0, _v("REJ-BASEFISC-REVUE-INVALIDE", f"{ident} : empreinte de revue illisible")
        nom = revue["reviewer"].casefold()
        if revue["empreinte"] == parametre["empreinte"] and nom != auteur:
            valides.add(nom)
    return len(valides), None


def _valider_parametre(parametre: Any) -> tuple[Parametre | None, dict[str, str] | None]:
    if not isinstance(parametre, dict):
        return None, _v("REJ-BASEFISC-SCHEMA-INVALIDE", "un paramètre doit être un objet")
    ident = parametre.get("id", "?")
    cles = set(parametre)
    if not _CHAMPS_REQUIS <= cles <= _CHAMPS_PARAMETRE:
        return None, _v(
            "REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : clés inconnues ou manquantes ({sorted(cles ^ _CHAMPS_REQUIS)})"
        )
    if not isinstance(ident, str) or _RE_ID.fullmatch(ident) is None:
        return None, _v("REJ-BASEFISC-SCHEMA-INVALIDE", f"identifiant illisible : {ident!r}")
    if parametre["juridiction"] not in _JURIDICTIONS or parametre["unite"] not in _UNITES:
        return None, _v(
            "REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : juridiction (FED, QC) ou unité (CAD, ratio, nombre) inconnue"
        )
    if not _texte(parametre["libelle"]) or ("note" in parametre and not _texte(parametre["note"])):
        return None, _v("REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : libellé ou note vide")
    saisie = parametre["saisie"]
    if (
        not isinstance(saisie, dict)
        or set(saisie) != {"par", "le"}
        or not isinstance(saisie["par"], str)
        or _RE_PERSONNE.fullmatch(saisie["par"]) is None
    ):
        return None, _v("REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : saisie {{par, le}} mal formée")
    saisie_le = _date_iso(saisie["le"])
    if saisie_le is None:
        return None, _v("REJ-BASEFISC-DATE-INVALIDE", f"{ident} : date de saisie invalide")
    # non_renseigne <=> valeur absente
    marque = parametre.get("non_renseigne")
    if (parametre["valeur"] is None) != (marque is not None):
        return None, _v(
            "REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : `valeur` nulle exige `non_renseigne`, et inversement"
        )
    if marque is not None and (
        not isinstance(marque, dict)
        or set(marque) != {"raison", "source_requise"}
        or not _texte(marque["raison"])
        or not _texte(marque["source_requise"])
    ):
        return None, _v("REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : non_renseigne {{raison, source_requise}} mal formé")
    valeur, refus = _parse_valeur(parametre)
    if refus is not None:
        return None, refus
    effet = parametre["effet"]
    if not isinstance(effet, dict) or set(effet) != {"debut", "fin"}:
        return None, _v("REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : effet {{debut, fin}} mal formé")
    debut = _date_iso(effet["debut"])
    fin = _date_iso(effet["fin"]) if effet["fin"] is not None else None
    if debut is None or (effet["fin"] is not None and fin is None) or (fin is not None and fin < debut):
        return None, _v("REJ-BASEFISC-DATE-INVALIDE", f"{ident} : période d'effet invalide ou inversée")
    refus = _valider_sources(parametre)
    if refus is not None:
        return None, refus
    try:
        attendue = empreinte_parametre(parametre)
    except (TypeError, ValueError):
        return None, _v("REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : contenu non sérialisable (type inattendu)")
    if not isinstance(parametre["empreinte"], str) or parametre["empreinte"] != attendue:
        return None, _v(
            "REJ-BASEFISC-EMPREINTE-DIVERGENTE",
            f"{ident} ({effet['debut']}) : contenu modifié sans que l'empreinte suive — modification silencieuse",
        )
    nombre_revues, refus = _valider_revues(parametre, saisie_le)
    if refus is not None:
        return None, refus
    if valeur is None and parametre["revues"]:
        return None, _v("REJ-BASEFISC-REVUE-INVALIDE", f"{ident} : un paramètre non renseigné ne se revoit pas")
    prouve = _STATUTS[min(nombre_revues, 2)]
    if parametre["statut"] != prouve:
        return None, _v(
            "REJ-BASEFISC-STATUT-INCOHERENT",
            f"{ident} : statut déclaré {parametre['statut']!r}, les revues valides prouvent {prouve!r}",
        )
    if nombre_revues >= 1:
        for source in parametre["sources"]:
            url = source["url"]
            if not isinstance(url, str) or not url.startswith("https://") or source["consulte_le"] is None:
                return None, _v(
                    "REJ-BASEFISC-SOURCE-INCOMPLETE",
                    f"{ident} : une valeur revue exige, pour chaque source, une URL https et une date de consultation",
                )
    return Parametre(
        identifiant=ident,
        juridiction=parametre["juridiction"],
        libelle=parametre["libelle"],
        valeur=valeur,
        unite=parametre["unite"],
        debut=debut,
        fin=fin,
        sources=tuple(json.loads(json.dumps(s)) for s in parametre["sources"]),
        saisie=dict(saisie),
        statut=prouve,
        empreinte=parametre["empreinte"],
        non_renseigne=dict(marque) if marque else None,
        note=parametre.get("note"),
        revues_valides=nombre_revues,
    ), None


def _valider_tuilage(versions: list[Parametre]) -> dict[str, str] | None:
    versions.sort(key=lambda p: p.debut)
    ident = versions[0].identifiant
    for avant, apres in zip(versions, versions[1:], strict=False):
        if avant.juridiction != apres.juridiction or avant.unite != apres.unite:
            return _v(
                "REJ-BASEFISC-SCHEMA-INVALIDE", f"{ident} : juridiction et unité doivent rester celles du paramètre"
            )
        if avant.fin is None or apres.debut <= avant.fin:
            return _v("REJ-BASEFISC-CHEVAUCHEMENT", f"{ident} : deux versions valent le {apres.debut.isoformat()}")
        if apres.debut != avant.fin + timedelta(days=1):
            return _v(
                "REJ-BASEFISC-TROU-DE-DATES",
                f"{ident} : aucune version du {(avant.fin + timedelta(days=1)).isoformat()} au "
                f"{(apres.debut - timedelta(days=1)).isoformat()}",
            )
    return None


def _empreinte_base(versions_par_id: Mapping[str, tuple[Parametre, ...]]) -> str:
    lignes = [
        f"{ident}|{p.debut.isoformat()}|{p.empreinte}"
        for ident in sorted(versions_par_id)
        for p in versions_par_id[ident]
    ]
    return hashlib.sha256("\n".join(lignes).encode("utf-8")).hexdigest()


def _lire_contenu(chemin: Path | str | None, contenu_octets: bytes | None) -> tuple[Any, dict[str, str] | None]:
    try:
        if contenu_octets is None:
            cible = Path(chemin) if chemin is not None else CHEMIN_BASE_PAR_DEFAUT
            if cible.stat().st_size > _TAILLE_MAX:
                return None, _v("REJ-BASEFISC-FORMAT-INVALIDE", "fichier de règles démesuré")
            contenu_octets = cible.read_bytes()
        if not isinstance(contenu_octets, bytes):
            return None, _v("REJ-BASEFISC-FORMAT-INVALIDE", "octets attendus")
        if len(contenu_octets) > _TAILLE_MAX:
            return None, _v("REJ-BASEFISC-FORMAT-INVALIDE", "fichier de règles démesuré")
        return yaml.load(contenu_octets.decode("utf-8", errors="strict"), Loader=_ChargeurStrict), None
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError, RecursionError) as erreur:
        return None, _v("REJ-BASEFISC-FORMAT-INVALIDE", f"base illisible ({type(erreur).__name__})")


def diagnostiquer(contenu_octets: bytes) -> list[dict[str, str]]:
    """TOUS les refus d'un contenu (le chargeur n'en rend que le premier). Liste vide : la base est valide."""
    contenu, refus = _lire_contenu(None, contenu_octets)
    if refus is not None:
        return [refus]
    if (
        not isinstance(contenu, dict)
        or set(contenu) != {"schema", "parametres"}
        or contenu["schema"] != SCHEMA
        or not isinstance(contenu["parametres"], list)
    ):
        return [_v("REJ-BASEFISC-SCHEMA-INVALIDE", f"schéma {SCHEMA} attendu, clés schema et parametres seulement")]
    erreurs: list[dict[str, str]] = []
    versions: dict[str, list[Parametre]] = {}
    for brut in contenu["parametres"]:
        parametre, refus = _valider_parametre(brut)
        if refus is not None:
            erreurs.append(refus)
        elif parametre is not None:
            versions.setdefault(parametre.identifiant, []).append(parametre)
    for liste in versions.values():
        refus = _valider_tuilage(liste)
        if refus is not None:
            erreurs.append(refus)
    return erreurs


def charger_base(
    chemin: Path | str | None = None, *, contenu_octets: bytes | None = None
) -> tuple[BaseFiscale | None, dict[str, str] | None]:
    """Charge ET valide. `(base, None)` ou `(None, premier refus)`. Sans chemin : la base du dépôt."""
    contenu, refus = _lire_contenu(chemin, contenu_octets)
    if refus is not None:
        return None, refus
    if (
        not isinstance(contenu, dict)
        or set(contenu) != {"schema", "parametres"}
        or contenu["schema"] != SCHEMA
        or not isinstance(contenu["parametres"], list)
    ):
        return None, _v("REJ-BASEFISC-SCHEMA-INVALIDE", f"schéma {SCHEMA} attendu, clés schema et parametres seulement")
    versions: dict[str, list[Parametre]] = {}
    for brut in contenu["parametres"]:
        parametre, refus = _valider_parametre(brut)
        if refus is not None:
            return None, refus
        assert parametre is not None
        versions.setdefault(parametre.identifiant, []).append(parametre)
    for liste in versions.values():
        refus = _valider_tuilage(liste)
        if refus is not None:
            return None, refus
    figees = {ident: tuple(liste) for ident, liste in versions.items()}
    return BaseFiscale(parametres=figees, empreinte=_empreinte_base(figees)), None


def charger_base_par_defaut() -> tuple[BaseFiscale | None, dict[str, str] | None]:
    return charger_base(CHEMIN_BASE_PAR_DEFAUT)


# --------------------------------------------------------------------------------------- résolution
def resoudre(
    base: BaseFiscale, identifiant: str, date_effet: Any, *, mode: Any
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le paramètre EN VIGUEUR le `date_effet`. Jamais de mode par défaut, de valeur par défaut ni de dernière valeur
    connue : hors couverture, non renseigné ou (mode officiel) non approuvé = refus typé."""
    if not isinstance(mode, str) or mode not in _MODES:
        return None, _v("REJ-BASEFISC-MODE-INVALIDE", "mode explicite requis : « officiel » ou « essai »")
    jour = _date_iso(date_effet)
    if jour is None:
        return None, _v("REJ-BASEFISC-DATE-INVALIDE", "date d'effet attendue au format AAAA-MM-JJ réel")
    versions = base.parametres.get(identifiant) if isinstance(identifiant, str) else None
    if versions is None:
        return None, _v("REJ-BASEFISC-PARAMETRE-INCONNU", f"identifiant absent de la base : {identifiant!r}")
    version = next((p for p in versions if p.couvre(jour)), None)
    if version is None:
        return None, _v(
            "REJ-BASEFISC-HORS-COUVERTURE",
            f"{identifiant} : aucune version ne couvre le {jour.isoformat()} — source officielle requise",
        )
    if version.valeur is None or version.non_renseigne is not None:
        marque = version.non_renseigne or {}
        return None, _v(
            "REJ-BASEFISC-NON-RENSEIGNE",
            f"{identifiant} : non renseigné — source officielle requise ({marque.get('source_requise', '?')})",
        )
    if mode == MODE_OFFICIEL and version.statut != "approuve":
        return None, _v(
            "REJ-BASEFISC-NON-APPROUVE",
            f"{identifiant} : statut {version.statut}, deux réviseurs distincts exigés en mode officiel",
        )
    regle: dict[str, Any] = {
        "identifiant": identifiant,
        "valeur": version.valeur,
        "unite": version.unite,
        "juridiction": version.juridiction,
        "libelle": version.libelle,
        "effet": {"debut": version.debut.isoformat(), "fin": version.fin.isoformat() if version.fin else None},
        "date_demandee": jour.isoformat(),
        "mode": mode,
        "essai": mode == MODE_ESSAI,
        "statut_revue": version.statut,
        "empreinte": version.empreinte,
        "empreinte_base": base.empreinte,
        "sources": [dict(s) for s in version.sources],
    }
    if mode == MODE_ESSAI:
        regle["avertissement"] = AVERTISSEMENT_ESSAI
    return regle, None


def recu_regle(regle: Mapping[str, Any]) -> dict[str, Any]:
    """La règle résolue sous forme sûre pour JSON (valeur en texte), avec la mention comptable."""
    sortie = {cle: (str(valeur) if isinstance(valeur, Decimal) else valeur) for cle, valeur in regle.items()}
    sortie["schema"] = "m5-regle-fiscale-resolue/1"
    sortie["mention_comptable"] = analyse.MENTION_COMPTABLE
    return sortie


def marquage_recu(regles: list[Mapping[str, Any]], mode: str) -> dict[str, Any]:
    """Le bloc à joindre à TOUT reçu de calcul qui consomme la base : le mode (explicite), les empreintes et statuts
    des paramètres utilisés. Un seul paramètre non approuvé rend le reçu entier « essai »."""
    essai = mode == MODE_ESSAI or any(r.get("essai") or r.get("statut_revue") != "approuve" for r in regles)
    bloc: dict[str, Any] = {
        "mode": mode,
        "essai": essai,
        "parametres": [
            {
                "identifiant": r["identifiant"],
                "empreinte": r["empreinte"],
                "statut_revue": r["statut_revue"],
                "effet": r["effet"],
            }
            for r in regles
        ],
    }
    if essai:
        bloc["avertissement"] = AVERTISSEMENT_ESSAI
    return bloc


def resume_base(base: BaseFiscale) -> dict[str, Any]:
    """L'état honnête de la base : combien de valeurs, à quel statut, et ce qui reste sans source."""
    par_statut = {statut: 0 for statut in _STATUTS}
    renseignes = 0
    non_renseignes: list[dict[str, Any]] = []
    for ident in sorted(base.parametres):
        for p in base.parametres[ident]:
            if p.valeur is None:
                non_renseignes.append(
                    {
                        "identifiant": ident,
                        "libelle": p.libelle,
                        "juridiction": p.juridiction,
                        "effet": {"debut": p.debut.isoformat(), "fin": p.fin.isoformat() if p.fin else None},
                        "raison": (p.non_renseigne or {}).get("raison"),
                        "source_requise": (p.non_renseigne or {}).get("source_requise"),
                        "source_officielle_requise": True,
                    }
                )
            else:
                renseignes += 1
                par_statut[p.statut] += 1
    return {
        "parametres_renseignes": renseignes,
        "par_statut": par_statut,
        "non_renseignes": non_renseignes,
        "empreinte_base": base.empreinte,
        "approbation": f"{par_statut['approuve']}/{renseignes} valeurs approuvées par deux réviseurs distincts",
    }


# ------------------------------------------------------------------------------------ pont TPS/TVQ
def taux_depuis_base(
    base: BaseFiscale, date_effet: Any, *, mode: Any, ids: tuple[str, ...] = tuple(_TAXES_BASE)
) -> tuple[tuple[dict[str, Any], list[dict[str, Any]]] | None, dict[str, str] | None]:
    """Le dictionnaire de taux de la forme de `taux_fiscaux.charger_taux_fiscaux` (donc consommable tel quel par
    `taxes.calculer_taxes`) et les règles résolues. Un seul taux refusé refuse le tout."""
    dictionnaire: dict[str, Any] = {}
    regles: list[dict[str, Any]] = []
    for ident in ids:
        cible = _TAXES_BASE.get(ident)
        if cible is None:
            return None, _v("REJ-BASEFISC-PARAMETRE-INCONNU", f"taxe sans paramètre dans la base : {ident!r}")
        regle, refus = resoudre(base, cible, date_effet, mode=mode)
        if refus is not None:
            return None, refus
        assert regle is not None
        regles.append(regle)
        dictionnaire[ident] = {
            "id": ident,
            "nom": regle["libelle"],
            "taux": regle["valeur"],
            "version": f"base-fiscale:{regle['empreinte'][:12]}",
            "source": regle["sources"][0]["titre"],
        }
    return (dictionnaire, regles), None


def calculer_taxes_selon_base(
    montant_avant_taxes: Decimal, base: BaseFiscale, date_effet: Any, *, mode: Any
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """`taxes.calculer_taxes` (seul endroit qui multiplie un montant par un taux) alimenté par la base. Le résultat
    porte `base_fiscale` : mode, empreintes, statuts — et l'avertissement si c'est un essai."""
    pris, refus = taux_depuis_base(base, date_effet, mode=mode)
    if refus is not None:
        return None, refus
    assert pris is not None
    dictionnaire, regles = pris
    resultat, refus = taxes.calculer_taxes(montant_avant_taxes, dictionnaire)
    if refus is not None:
        return None, refus
    assert resultat is not None
    return {**resultat, "base_fiscale": marquage_recu(regles, mode)}, None


# ------------------------------------------------------------------------------------------------ CLI
def main(argv: list[str]) -> int:
    """`python -m m5_financecore.base_fiscale verifier [fichier]` ; `... empreintes [fichier]` (les empreintes
    attendues, à copier dans le fichier après une modification VOULUE — les revues devront être refaites)."""
    commande = argv[0] if argv else ""
    chemin = Path(argv[1]) if len(argv) > 1 else CHEMIN_BASE_PAR_DEFAUT
    if commande == "verifier":
        erreurs = diagnostiquer(chemin.read_bytes())
        for erreur in erreurs:
            print(f"{erreur['code']} : {erreur['detail']}")
        if not erreurs:
            base, _ = charger_base(chemin)
            assert base is not None
            print(resume_base(base)["approbation"])
        return 1 if erreurs else 0
    if commande == "empreintes":
        contenu = yaml.load(chemin.read_text(encoding="utf-8"), Loader=_ChargeurStrict)
        for parametre in contenu["parametres"]:
            print(f"{parametre['id']} {parametre['effet']['debut']} {empreinte_parametre(parametre)}")
        return 0
    print("usage : verifier|empreintes [fichier]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
