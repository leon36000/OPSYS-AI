"""Catalogue de subventions et de crédits : structure, gouvernance et appariement déterministe règles -> explication
citée
(`docs/architecture/BASE-FISCALE.md`).

Doctrine :

- Le catalogue est une DONNÉE CURÉE (`contracts/catalogue_subventions.v1.yaml`), jamais un souvenir du modèle. Il est
livré
  VIDE : aucune mesure réelle. Les seuls exemples (`fictif: true`, identifiants `FICTIF-…`) vivent dans les tests.
- Une mesure déclare son organisme, son programme, son admissibilité en RÈGLES DÉCLARATIVES évaluables (champ,
opérateur,
  valeur, source citée), sa période, son montant ou plafond (avec source), ses documents requis, son statut de
  vérification, sa date de dernière vérification et son expiration.
- L'appariement est déterministe et à TROIS ÉTATS par critère : `satisfait`, `non_satisfait`, `inconnu` (un fait absent
  n'est jamais « non »). JAMAIS « admissible » si un critère est inconnu : le verdict est `a_verifier`, avec la
  question à
  poser. Un critère non satisfait ferme la mesure (`non_admissible`). Chaque état porte une explication qui CITE la
  source
  du critère.
- Une mesure périmée (expiration, fin de période) est EXCLUE et dite telle ; une mesure fictive est refusée en mode
  officiel. Une mesure non vérifiée, ou dont la vérification a expiré, ne peut pas être « admissible » non plus.
- Rien n'est calculé : aucun montant estimé, aucun pourcentage appliqué. Le montant d'une mesure est celui du
catalogue, avec
  sa source, ou « inconnu — source requise ».
- Sortie = BROUILLON de dossier (documents à fournir, questions ouvertes) : M5 ne dépose, ne soumet et ne signe rien
  (décision humaine, N3 ou plus). Toute sortie porte « À valider auprès d'un comptable (CPA) / professionnel qualifié ».

Module pur : aucune horloge (la date du jour est un argument), aucun réseau, aucune écriture.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from . import analyse, verdicts_fiscal
from .base_fiscale import _ChargeurStrict

__all__ = [
    "CHEMIN_CATALOGUE_PAR_DEFAUT",
    "MODE_ESSAI",
    "MODE_OFFICIEL",
    "RESERVE",
    "SCHEMA",
    "Catalogue",
    "apparier",
    "charger_catalogue",
    "evaluer_critere",
    "resume_catalogue",
]

SCHEMA = "opsys.catalogue-subventions/v1"
MODE_OFFICIEL = "officiel"
MODE_ESSAI = "essai"
_MODES = frozenset({MODE_OFFICIEL, MODE_ESSAI})
CHEMIN_CATALOGUE_PAR_DEFAUT = Path(__file__).resolve().parents[2] / "contracts" / "catalogue_subventions.v1.yaml"
RESERVE = (
    "Admissibilité selon les faits déclarés et le contenu du catalogue, à la date indiquée ; elle ne vaut ni "
    "acceptation "
    "ni engagement de l'organisme. " + analyse.MENTION_COMPTABLE
)
_TAILLE_MAX = 2 * 1024 * 1024
_TYPES_CHAMP = frozenset({"texte", "decimal", "booleen", "date"})
_OPERATEURS = {
    "texte": frozenset({"eq", "ne", "in", "not_in"}),
    "decimal": frozenset({"eq", "ne", "gte", "gt", "lte", "lt", "between"}),
    "booleen": frozenset({"vrai", "faux"}),
    "date": frozenset({"eq", "gte", "gt", "lte", "lt", "between"}),
}
_MOTS = {
    "eq": "est égal à",
    "ne": "est différent de",
    "in": "fait partie de",
    "not_in": "ne fait pas partie de",
    "gte": "est supérieur ou égal à",
    "gt": "est supérieur à",
    "lte": "est inférieur ou égal à",
    "lt": "est inférieur à",
    "between": "est compris entre",
    "vrai": "est vrai",
    "faux": "est faux",
}
_TYPES_MESURE = frozenset({"subvention", "credit_impot", "pret", "remboursement"})
_NATURES_MONTANT = frozenset({"montant_maximum", "pourcentage", "inconnu"})
_RE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_RE_CHAMP = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_RE_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,12})?$")
# Texte d'un fait : une courte valeur, sans retour de ligne ni balisage. Un fait est une DONNÉE, jamais une consigne.
_RE_FAIT_TEXTE = re.compile(r"^[\w .,'’/()&+-]{1,80}$")
_CHAMPS_SOURCE = frozenset({"organisme", "titre", "url", "consulte_le", "reference"})
_CHAMPS_MESURE = frozenset(
    {
        "id",
        "fictif",
        "organisme",
        "programme",
        "titre",
        "juridiction",
        "type",
        "admissibilite",
        "periode",
        "expiration",
        "montant",
        "documents_requis",
        "sources",
        "verification",
    }
)


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


def _decimal(valeur: Any) -> Decimal | None:
    if not isinstance(valeur, str) or _RE_DECIMAL.fullmatch(valeur) is None:
        return None
    try:
        return Decimal(valeur)
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class Catalogue:
    champs: Mapping[str, Mapping[str, str]]
    mesures: tuple[Mapping[str, Any], ...]
    mode: str


# ---------------------------------------------------------------------------------------- chargement
def _valider_source(source: Any, *, fictif: bool, contexte: str) -> dict[str, str] | None:
    if (
        not isinstance(source, dict)
        or not {"organisme", "titre", "url", "consulte_le"} <= set(source) <= _CHAMPS_SOURCE
    ):
        return _v("REJ-SUBV-CRITERE-INVALIDE", f"{contexte} : source {{organisme, titre, url, consulte_le}} requise")
    if not _texte(source["organisme"]) or not _texte(source["titre"]):
        return _v("REJ-SUBV-CRITERE-INVALIDE", f"{contexte} : la source exige un organisme et un titre")
    if not fictif:
        url = source["url"]
        if not isinstance(url, str) or not url.startswith("https://") or _date_iso(source["consulte_le"]) is None:
            return _v("REJ-SUBV-CRITERE-INVALIDE", f"{contexte} : source réelle = URL https et date de consultation")
    elif source["consulte_le"] is not None and _date_iso(source["consulte_le"]) is None:
        return _v("REJ-SUBV-CRITERE-INVALIDE", f"{contexte} : date de consultation invalide")
    return None


def _valeur_critere(type_champ: str, operateur: str, valeur: Any) -> bool:
    if operateur in {"vrai", "faux"}:
        return valeur is None
    if operateur == "between":
        return (
            isinstance(valeur, list)
            and len(valeur) == 2
            and all(_valeur_scalaire(type_champ, x) for x in valeur)
            and _comparable(type_champ, valeur[0]) <= _comparable(type_champ, valeur[1])
        )
    if operateur in {"in", "not_in"}:
        return isinstance(valeur, list) and bool(valeur) and all(_valeur_scalaire(type_champ, x) for x in valeur)
    return _valeur_scalaire(type_champ, valeur)


def _valeur_scalaire(type_champ: str, valeur: Any) -> bool:
    if type_champ == "texte":
        return isinstance(valeur, str) and _RE_FAIT_TEXTE.fullmatch(valeur) is not None
    if type_champ == "decimal":
        return _decimal(valeur) is not None
    if type_champ == "date":
        return _date_iso(valeur) is not None
    return False


def _comparable(type_champ: str, valeur: str) -> Any:
    return _decimal(valeur) if type_champ == "decimal" else _date_iso(valeur) if type_champ == "date" else valeur


def _valider_critere(
    critere: Any, champs: Mapping[str, Any], ids: set[str], *, fictif: bool, mesure: str, dans_groupe: bool = False
) -> dict[str, str] | None:
    contexte = f"{mesure}"
    if (
        not isinstance(critere, dict)
        or not _RE_ID.fullmatch(str(critere.get("id", "")))
        or not _texte(critere.get("libelle"))
    ):
        return _v("REJ-SUBV-CRITERE-INVALIDE", f"{contexte} : critère sans identifiant lisible ou sans libellé")
    contexte = f"{mesure}/{critere['id']}"
    if critere["id"] in ids:
        return _v("REJ-SUBV-CRITERE-INVALIDE", f"{contexte} : identifiant de critère en double")
    ids.add(critere["id"])
    refus = _valider_source(critere.get("source"), fictif=fictif, contexte=contexte)
    if refus is not None:
        return refus
    if "un_parmi" in critere:
        if (
            dans_groupe
            or set(critere) != {"id", "libelle", "source", "un_parmi"}
            or not isinstance(critere["un_parmi"], list)
            or len(critere["un_parmi"]) < 2
        ):
            return _v(
                "REJ-SUBV-CRITERE-INVALIDE",
                f"{contexte} : groupe `un_parmi` = au moins deux critères, sans imbrication",
            )
        for sous in critere["un_parmi"]:
            refus = _valider_critere(sous, champs, ids, fictif=fictif, mesure=mesure, dans_groupe=True)
            if refus is not None:
                return refus
        return None
    if (
        not {"id", "libelle", "source", "champ", "operateur"}
        <= set(critere)
        <= {"id", "libelle", "source", "champ", "operateur", "valeur"}
    ):
        return _v(
            "REJ-SUBV-CRITERE-INVALIDE", f"{contexte} : clés id, libelle, source, champ, operateur[, valeur] seulement"
        )
    champ = champs.get(critere["champ"]) if isinstance(critere["champ"], str) else None
    if champ is None:
        return _v(
            "REJ-SUBV-CRITERE-INVALIDE", f"{contexte} : champ {critere['champ']!r} absent du vocabulaire du catalogue"
        )
    if critere["operateur"] not in _OPERATEURS[champ["type"]]:
        return _v(
            "REJ-SUBV-CRITERE-INVALIDE",
            f"{contexte} : opérateur {critere['operateur']!r} impossible sur un champ {champ['type']}",
        )
    if not _valeur_critere(champ["type"], critere["operateur"], critere.get("valeur")):
        return _v("REJ-SUBV-CRITERE-INVALIDE", f"{contexte} : valeur du critère illisible pour le type {champ['type']}")
    return None


def _valider_mesure(mesure: Any, champs: Mapping[str, Any], mode: str) -> dict[str, str] | None:
    ident = mesure.get("id", "?") if isinstance(mesure, dict) else "?"

    def invalide(detail: str) -> dict[str, str]:
        return _v("REJ-SUBV-MESURE-INVALIDE", f"{ident} : {detail}")

    if not isinstance(mesure, dict) or set(mesure) != _CHAMPS_MESURE:
        return invalide(f"clés exigées : {sorted(_CHAMPS_MESURE)}")
    if not isinstance(ident, str) or _RE_ID.fullmatch(ident) is None or type(mesure["fictif"]) is not bool:
        return invalide("identifiant illisible ou `fictif` non booléen")
    fictif = mesure["fictif"]
    if fictif and not ident.startswith("FICTIF-"):
        return invalide("une mesure fictive porte un identifiant « FICTIF-… »")
    if not fictif and ident.startswith("FICTIF-"):
        return invalide("l'identifiant « FICTIF-… » est réservé aux mesures marquées `fictif: true`")
    if fictif and mode == MODE_OFFICIEL:
        return _v("REJ-SUBV-FICTIF-REFUSE", f"{ident} : mesure fictive dans un catalogue chargé en mode officiel")
    if (
        any(not _texte(mesure[c]) for c in ("organisme", "programme", "titre"))
        or mesure["juridiction"] not in {"FED", "QC"}
        or mesure["type"] not in _TYPES_MESURE
    ):
        return invalide("organisme, programme, titre, juridiction (FED, QC) ou type illisible")
    periode = mesure["periode"]
    debut = _date_iso(periode.get("debut")) if isinstance(periode, dict) and set(periode) == {"debut", "fin"} else None
    fin = _date_iso(periode.get("fin")) if debut is not None else None
    if debut is None or fin is None or fin < debut:
        return invalide("période {debut, fin} invalide")
    expiration = _date_iso(mesure["expiration"])
    if expiration is None:
        return invalide("expiration invalide (une mesure sans expiration n'existe pas)")
    sources = mesure["sources"]
    if not isinstance(sources, list) or not sources:
        return invalide("au moins une source de la mesure")
    for source in sources:
        refus = _valider_source(source, fictif=fictif, contexte=ident)
        if refus is not None:
            return refus
    refus = _valider_montant(ident, mesure["montant"], fictif)
    if refus is not None:
        return refus
    documents = mesure["documents_requis"]
    if not isinstance(documents, list) or any(
        not isinstance(d, dict) or set(d) != {"id", "libelle"} or not _texte(d["id"]) or not _texte(d["libelle"])
        for d in documents
    ):
        return invalide("documents_requis = liste de {id, libelle}")
    verification = mesure["verification"]
    if not isinstance(verification, dict) or set(verification) != {"statut", "par", "le", "valide_jusqu_au"}:
        return invalide("verification {statut, par, le, valide_jusqu_au} exigée")
    if verification["statut"] == "verifiee":
        if (
            not _texte(verification["par"])
            or _date_iso(verification["le"]) is None
            or _date_iso(verification["valide_jusqu_au"]) is None
            or _date_iso(verification["valide_jusqu_au"]) < _date_iso(verification["le"])
        ):
            return invalide("une mesure vérifiée dit qui, quand, et jusqu'à quand la vérification vaut")
    elif verification["statut"] != "non_verifiee" or any(
        verification[c] is not None for c in ("par", "le", "valide_jusqu_au")
    ):
        return invalide("verification.statut = non_verifiee (champs nuls) ou verifiee")
    criteres = mesure["admissibilite"]
    if not isinstance(criteres, list) or not criteres:
        return invalide("admissibilite = liste non vide de critères")
    ids: set[str] = set()
    for critere in criteres:
        refus = _valider_critere(critere, champs, ids, fictif=fictif, mesure=ident)
        if refus is not None:
            return refus
    return None


def _valider_montant(ident: str, montant: Any, fictif: bool) -> dict[str, str] | None:
    def invalide(detail: str) -> dict[str, str]:
        return _v("REJ-SUBV-MESURE-INVALIDE", f"{ident} : montant — {detail}")

    if not isinstance(montant, dict) or set(montant) != {"nature", "valeur", "unite", "plafond", "source"}:
        return invalide("{nature, valeur, unite, plafond, source} exigés")
    if montant["nature"] not in _NATURES_MONTANT:
        return invalide(f"nature parmi {sorted(_NATURES_MONTANT)}")
    if montant["nature"] == "inconnu":
        if any(montant[c] is not None for c in ("valeur", "unite", "plafond", "source")):
            return invalide("un montant inconnu n'a ni valeur, ni unité, ni plafond, ni source")
        return None
    valeur = _decimal(montant["valeur"])
    attendu_unite = "CAD" if montant["nature"] == "montant_maximum" else "ratio"
    if valeur is None or valeur < 0 or montant["unite"] != attendu_unite or (attendu_unite == "ratio" and valeur > 1):
        return invalide(f"valeur texte décimale et unité {attendu_unite} exigées")
    if montant["plafond"] is not None and (_decimal(montant["plafond"]) is None or _decimal(montant["plafond"]) < 0):
        return invalide("plafond illisible")
    refus = _valider_source(montant["source"], fictif=fictif, contexte=f"{ident}/montant")
    return None if refus is None else _v("REJ-SUBV-MESURE-INVALIDE", refus["detail"])


def _valider_champs(brut: Any) -> tuple[dict[str, dict[str, str]] | None, dict[str, str] | None]:
    if not isinstance(brut, dict) or not brut:
        return None, _v("REJ-SUBV-CATALOGUE-INVALIDE", "vocabulaire `champs` non vide exigé")
    champs: dict[str, dict[str, str]] = {}
    for nom, fiche in brut.items():
        if (
            not isinstance(nom, str)
            or _RE_CHAMP.fullmatch(nom) is None
            or not isinstance(fiche, dict)
            or set(fiche) != {"type", "libelle", "question"}
            or fiche["type"] not in _TYPES_CHAMP
            or not _texte(fiche["libelle"])
            or not _texte(fiche["question"])
        ):
            return None, _v("REJ-SUBV-CATALOGUE-INVALIDE", f"champ {nom!r} : {{type, libelle, question}} exigés")
        champs[nom] = dict(fiche)
    return champs, None


def charger_catalogue(
    chemin: Path | str | None = None, *, contenu_octets: bytes | None = None, mode: Any = None
) -> tuple[Catalogue | None, dict[str, str] | None]:
    """Charge ET valide le catalogue. Le mode est EXPLICITE : en `officiel`, une mesure fictive refuse tout le
    catalogue."""
    if not isinstance(mode, str) or mode not in _MODES:
        return None, _v("REJ-SUBV-MODE-INVALIDE", "mode explicite requis : « officiel » ou « essai »")
    try:
        if contenu_octets is None:
            cible = Path(chemin) if chemin is not None else CHEMIN_CATALOGUE_PAR_DEFAUT
            if cible.stat().st_size > _TAILLE_MAX:
                return None, _v("REJ-SUBV-CATALOGUE-INVALIDE", "catalogue démesuré")
            contenu_octets = cible.read_bytes()
        if len(contenu_octets) > _TAILLE_MAX:
            return None, _v("REJ-SUBV-CATALOGUE-INVALIDE", "catalogue démesuré")
        contenu = yaml.load(contenu_octets.decode("utf-8", errors="strict"), Loader=_ChargeurStrict)
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError, RecursionError) as erreur:
        return None, _v("REJ-SUBV-CATALOGUE-INVALIDE", f"catalogue illisible ({type(erreur).__name__})")
    if (
        not isinstance(contenu, dict)
        or set(contenu) != {"schema", "statut_catalogue", "champs", "mesures"}
        or contenu["schema"] != SCHEMA
        or not _texte(contenu["statut_catalogue"])
        or not isinstance(contenu["mesures"], list)
    ):
        return None, _v("REJ-SUBV-CATALOGUE-INVALIDE", f"schéma {SCHEMA}, statut_catalogue, champs et mesures exigés")
    champs, refus = _valider_champs(contenu["champs"])
    if refus is not None:
        return None, refus
    assert champs is not None
    ids: set[str] = set()
    for mesure in contenu["mesures"]:
        refus = _valider_mesure(mesure, champs, mode)
        if refus is not None:
            return None, refus
        if mesure["id"] in ids:
            return None, _v("REJ-SUBV-MESURE-INVALIDE", f"{mesure['id']} : identifiant de mesure en double")
        ids.add(mesure["id"])
    figees = tuple(json.loads(json.dumps(m)) for m in sorted(contenu["mesures"], key=lambda m: m["id"]))
    return Catalogue(champs=champs, mesures=figees, mode=mode), None


# ------------------------------------------------------------------------------------------ évaluation
def _valider_faits(
    faits: Any, champs: Mapping[str, Mapping[str, str]]
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if not isinstance(faits, dict):
        return None, _v("REJ-SUBV-FAITS-INVALIDES", "les faits sont un objet {champ: valeur}")
    propres: dict[str, Any] = {}
    for nom, valeur in faits.items():
        champ = champs.get(nom) if isinstance(nom, str) else None
        if champ is None:
            return None, _v("REJ-SUBV-FAITS-INVALIDES", f"fait inconnu du vocabulaire : {nom!r}")
        if valeur is None:
            continue  # un fait nul est un fait inconnu
        type_champ = champ["type"]
        bon = (type(valeur) is bool) if type_champ == "booleen" else _valeur_scalaire(type_champ, valeur)
        if not bon:
            return None, _v("REJ-SUBV-FAITS-INVALIDES", f"fait {nom!r} : valeur illisible pour le type {type_champ}")
        propres[nom] = valeur
    return propres, None


def _citation(source: Mapping[str, Any]) -> str:
    morceaux = [source["organisme"], source["titre"]]
    if source.get("reference"):
        morceaux.append(str(source["reference"]))
    return ", ".join(morceaux)


def _texte_valeur(critere: Mapping[str, Any]) -> str:
    valeur = critere.get("valeur")
    if isinstance(valeur, list):
        return " et ".join(valeur) if critere["operateur"] == "between" else ", ".join(valeur)
    return "" if valeur is None else str(valeur)


def evaluer_critere(
    critere: Mapping[str, Any], champs: Mapping[str, Mapping[str, str]], faits: Mapping[str, Any]
) -> dict[str, Any]:
    """L'état d'UN critère (`satisfait`, `non_satisfait`, `inconnu`) avec son explication citée."""
    source = critere["source"]
    if "un_parmi" in critere:
        sous = [evaluer_critere(c, champs, faits) for c in critere["un_parmi"]]
        etats = {s["etat"] for s in sous}
        etat = "satisfait" if "satisfait" in etats else "inconnu" if "inconnu" in etats else "non_satisfait"
        mot = {"satisfait": "Satisfait", "non_satisfait": "Non satisfait", "inconnu": "À vérifier"}[etat]
        return {
            "id": critere["id"],
            "libelle": critere["libelle"],
            "etat": etat,
            "sous_criteres": sous,
            "explication": (
                f"{mot} : {critere['libelle']} (au moins un parmi {len(sous)} critères). "
                f"Source : {_citation(source)}."
            ),
            "source": dict(source),
        }
    champ = critere["champ"]
    type_champ = champs[champ]["type"]
    base = {"id": critere["id"], "libelle": critere["libelle"], "champ": champ, "source": dict(source)}
    if champ not in faits:
        question = champs[champ]["question"]
        return {
            **base,
            "etat": "inconnu",
            "fait": None,
            "question": question,
            "explication": (
                f"À vérifier : {critere['libelle']} — le fait « {champ} » n'est pas connu. "
                f"Question à poser : {question} Source : {_citation(source)}."
            ),
        }
    fait = faits[champ]
    operateur = critere["operateur"]
    valeur = critere.get("valeur")
    if type_champ == "booleen":
        ok = fait is (operateur == "vrai")
    else:
        a, b = _comparable(type_champ, fait), None
        if operateur in {"in", "not_in"}:
            presente = any(a == _comparable(type_champ, x) for x in valeur)
            ok = presente if operateur == "in" else not presente
        elif operateur == "between":
            ok = _comparable(type_champ, valeur[0]) <= a <= _comparable(type_champ, valeur[1])
        else:
            b = _comparable(type_champ, valeur)
            ok = {"eq": a == b, "ne": a != b, "gte": a >= b, "gt": a > b, "lte": a <= b, "lt": a < b}[operateur]
    etat = "satisfait" if ok else "non_satisfait"
    cible = f" {_texte_valeur(critere)}" if _texte_valeur(critere) else ""
    return {
        **base,
        "etat": etat,
        "fait": fait,
        "explication": (
            f"{'Satisfait' if ok else 'Non satisfait'} : {critere['libelle']} — le fait « {champ} » vaut "
            f"{fait} ; critère : {_MOTS[operateur]}{cible}. Source : {_citation(source)}."
        ),
    }


def _montant_dit(mesure: Mapping[str, Any]) -> dict[str, Any]:
    m = mesure["montant"]
    if m["nature"] == "inconnu":
        return {"nature": "inconnu", "dit": "Montant inconnu — source officielle requise.", "calcule": False}
    return {
        "nature": m["nature"],
        "valeur": m["valeur"],
        "unite": m["unite"],
        "plafond": m["plafond"],
        "source": dict(m["source"]),
        "calcule": False,
        "dit": "Montant tel que le catalogue le cite : aucune estimation n'est faite pour cette entreprise.",
    }


def apparier(catalogue: Catalogue, faits: Any, aujourd_hui: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Apparie les faits aux mesures. `aujourd_hui` est un ARGUMENT (M5 n'a pas d'horloge)."""
    jour = _date_iso(aujourd_hui)
    if jour is None:
        return None, _v("REJ-SUBV-DATE-INVALIDE", "date du jour attendue au format AAAA-MM-JJ réel")
    propres, refus = _valider_faits(faits, catalogue.champs)
    if refus is not None:
        return None, refus
    assert propres is not None
    resultats: list[dict[str, Any]] = []
    exclues: list[dict[str, Any]] = []
    for mesure in catalogue.mesures:
        debut, fin = _date_iso(mesure["periode"]["debut"]), _date_iso(mesure["periode"]["fin"])
        expiration = _date_iso(mesure["expiration"])
        raison = None
        if jour > expiration:
            raison = "expiree"
        elif jour > fin:
            raison = "periode_terminee"
        elif jour < debut:
            raison = "periode_non_ouverte"
        if raison is not None:
            exclues.append(
                {
                    "mesure_id": mesure["id"],
                    "programme": mesure["programme"],
                    "raison": raison,
                    "explication": {
                        "expiree": f"Exclue : l'entrée du catalogue a expiré le {mesure['expiration']}.",
                        "periode_terminee": (
                            f"Exclue : la période du programme s'est terminée le {mesure['periode']['fin']}."
                        ),
                        "periode_non_ouverte": (
                            f"Exclue : la période du programme ne s'ouvre que le {mesure['periode']['debut']}."
                        ),
                    }[raison],
                }
            )
            continue
        criteres = [evaluer_critere(c, catalogue.champs, propres) for c in mesure["admissibilite"]]
        etats = {c["etat"] for c in criteres}
        verification = mesure["verification"]
        verifiee = verification["statut"] == "verifiee" and jour <= _date_iso(verification["valide_jusqu_au"])
        if "non_satisfait" in etats:
            verdict, motif = "non_admissible", "Au moins un critère n'est pas satisfait."
        elif "inconnu" in etats:
            verdict, motif = (
                "a_verifier",
                "Au moins un critère est inconnu : jamais « admissible » sur un fait manquant.",
            )
        elif not verifiee:
            verdict = "a_verifier"
            motif = (
                "Tous les critères sont satisfaits, mais la mesure n'est pas vérifiée dans le catalogue."
                if verification["statut"] != "verifiee"
                else f"Tous les critères sont satisfaits, mais la vérification du catalogue a expiré le "
                f"{verification['valide_jusqu_au']}."
            )
        else:
            verdict, motif = "admissible", "Tous les critères du catalogue sont satisfaits par les faits déclarés."
        entree: dict[str, Any] = {
            "mesure_id": mesure["id"],
            "organisme": mesure["organisme"],
            "programme": mesure["programme"],
            "titre": mesure["titre"],
            "type": mesure["type"],
            "fictif": mesure["fictif"],
            "verdict": verdict,
            "motif": motif,
            "criteres": criteres,
            "montant": _montant_dit(mesure),
            "verification": dict(verification),
            "sources": [dict(s) for s in mesure["sources"]],
            "periode": dict(mesure["periode"]),
            "expiration": mesure["expiration"],
        }
        if verdict in {"admissible", "a_verifier"}:
            entree["brouillon_dossier"] = {
                "statut": "BROUILLON_NON_SOUMIS",
                "niveau": "N2",
                "documents_a_fournir": [dict(d, etat="a_fournir") for d in mesure["documents_requis"]],
                "questions_ouvertes": [c["question"] for c in _inconnus(criteres)],
                "soumission": "Hors de M5 : le dépôt d'une demande est une décision humaine (N3 ou plus).",
            }
        resultats.append(entree)
    compte = {v: sum(1 for r in resultats if r["verdict"] == v) for v in ("admissible", "a_verifier", "non_admissible")}
    return {
        "schema": "m5-appariement-subventions/1",
        "mode": catalogue.mode,
        "essai": catalogue.mode == MODE_ESSAI,
        "date": jour.isoformat(),
        "mesures_examinees": len(catalogue.mesures),
        "resultats": resultats,
        "exclues": exclues,
        "compte": compte,
        "catalogue_vide": not catalogue.mesures,
        "message": (
            "Catalogue vide : aucune mesure n'est renseignée — sources officielles et curation requises."
            if not catalogue.mesures
            else None
        ),
        "reserve": RESERVE,
    }, None


def _inconnus(criteres: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trouves = []
    for c in criteres:
        if "sous_criteres" in c:
            if c["etat"] == "inconnu":
                trouves.extend(s for s in c["sous_criteres"] if s["etat"] == "inconnu")
        elif c["etat"] == "inconnu":
            trouves.append(c)
    return trouves


def resume_catalogue(catalogue: Catalogue) -> dict[str, Any]:
    return {
        "mesures": len(catalogue.mesures),
        "champs": sorted(catalogue.champs),
        "mode": catalogue.mode,
        "fictives": sum(1 for m in catalogue.mesures if m["fictif"]),
        "verifiees": sum(1 for m in catalogue.mesures if m["verification"]["statut"] == "verifiee"),
    }
