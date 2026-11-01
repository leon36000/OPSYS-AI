"""Le modèle des signaux de marché et de performance : sources déclarées, fait normalisé, fenêtre de lecture.

Un SIGNAL est un fait observé chez une source de DONNÉES PROPRES du client (Search Console, PageSpeed, Bing, analytique
auto-hébergée, fiche Google, rapports publicitaires) ou importé à la main depuis un export. Il a toujours :
- sa SOURCE et son COMPTE (l'étiquette que le client a donnée à sa propriété), sa NATURE et sa PORTÉE (site, page,
  requête, campagne…), la PÉRIODE qu'il couvre ;
- ses MESURES en texte décimal (jamais un flottant JSON), l'ÉCHANTILLON (une donnée échantillonnée le dit) ;
- sa PROVENANCE (fournisseur, point d'accès, version d'API déclarée, mode `api_lecture` ou `import_manuel`, empreinte de
  la réponse) et l'instant d'observation.

Une absence n'est jamais un zéro : un fait qui n'a pas été lu n'existe pas (la fraîcheur le dit, `fraicheur.py`). Aucun
champ ne porte un renseignement personnel : les requêtes de recherche, les extraits d'avis et les libellés passent par
le
masqueur d'observabilité (`minimisation.py`) AVANT d'entrer ici ; le nom d'un auteur d'avis n'entre jamais.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from .erreurs import refus

SCHEMA_FAIT = "opsys.m7.signal_marketing/v1"

# -- sources ----------------------------------------------------------------------------------------------------------
SEARCH_CONSOLE = "search_console"
PAGESPEED = "pagespeed"
CRUX = "crux"
BING_WEBMASTER = "bing_webmaster"
UMAMI = "umami"
MATOMO = "matomo"
GBP_AVIS = "gbp_avis"
GBP_INSIGHTS = "gbp_insights"
GOOGLE_ADS = "google_ads"
META_ADS = "meta_ads"
# Sources qui n'existent que par import manuel d'un export ou d'un journal (aucune API de lecture documentée au moment
# d'écrire : R4 §10 « INCONNU » 1 et 2).
SEARCH_CONSOLE_IA = "search_console_ia"
BING_AI_PERFORMANCE = "bing_ai_performance"
JOURNAUX_SERVEUR = "journaux_serveur"

NATURES = (
    "performance_recherche_jour",
    "requetes_periode",
    "pages_periode",
    "vitesse_page_labo",
    "terrain_cwv",
    "audience_jour",
    "referents_periode",
    "avis",
    "insights_fiche_jour",
    "campagne_jour",
    "compte_jour",
    "rapport_ia_impressions",
    "visites_robots_ia",
)
TYPES_PORTEE = ("site", "page", "requete", "campagne", "fiche", "avis", "referent", "robot_ia", "compte")
ECHANTILLONS = ("complet", "echantillonne", "anonymise_partiel", "inconnu")
MODES = ("api_lecture", "import_manuel")


@dataclasses.dataclass(frozen=True)
class SourceDecl:
    """Ce que le dépôt sait d'une source SANS la joindre. Les fenêtres de fraîcheur sont des DÉFAUTS déclarés par M7
    (à confirmer avec M8 et le client) : `fraicheur_h` est le délai après lequel une lecture réussie n'est plus
    « à jour », `retard_donnees_jours` le retard habituel de la donnée elle-même chez le fournisseur."""

    id: str
    libelle: str
    famille: str
    natures: tuple[str, ...]
    fraicheur_h: int
    retard_donnees_jours: int
    canal_depenses: str | None = None
    auto_heberge: bool = False
    import_seulement: bool = False
    secrets_annexes: tuple[str, ...] = ()


SOURCES: Mapping[str, SourceDecl] = {
    s.id: s
    for s in (
        SourceDecl(
            SEARCH_CONSOLE,
            "Google Search Console",
            "recherche",
            ("performance_recherche_jour", "requetes_periode", "pages_periode"),
            72,
            3,
        ),
        SourceDecl(PAGESPEED, "PageSpeed Insights", "performance_web", ("vitesse_page_labo", "terrain_cwv"), 192, 0),
        SourceDecl(CRUX, "Chrome UX Report", "performance_web", ("terrain_cwv",), 192, 0),
        SourceDecl(
            BING_WEBMASTER,
            "Bing Webmaster Tools",
            "recherche",
            ("performance_recherche_jour", "requetes_periode", "pages_periode"),
            72,
            2,
        ),
        SourceDecl(
            UMAMI,
            "Umami (auto-hébergé)",
            "analytique",
            ("audience_jour", "referents_periode"),
            36,
            0,
            auto_heberge=True,
        ),
        SourceDecl(
            MATOMO,
            "Matomo (auto-hébergé)",
            "analytique",
            ("audience_jour", "referents_periode"),
            36,
            0,
            auto_heberge=True,
        ),
        SourceDecl(GBP_AVIS, "Fiche d'établissement Google : avis", "reputation", ("avis",), 72, 0),
        SourceDecl(
            GBP_INSIGHTS, "Fiche d'établissement Google : performance", "reputation", ("insights_fiche_jour",), 96, 3
        ),
        SourceDecl(
            GOOGLE_ADS,
            "Google Ads (rapports en lecture)",
            "publicite",
            ("campagne_jour", "compte_jour"),
            36,
            1,
            canal_depenses="google_ads",
            secrets_annexes=("jeton_developpeur",),
        ),
        SourceDecl(
            META_ADS,
            "Meta Ads (rapports en lecture)",
            "publicite",
            ("campagne_jour", "compte_jour"),
            36,
            1,
            canal_depenses="meta",
        ),
        SourceDecl(
            SEARCH_CONSOLE_IA,
            "Search Console : rapport IA générative (export)",
            "recherche",
            ("rapport_ia_impressions",),
            24 * 35,
            3,
            import_seulement=True,
        ),
        SourceDecl(
            BING_AI_PERFORMANCE,
            "Bing : rapport AI Performance (export)",
            "recherche",
            ("rapport_ia_impressions",),
            24 * 35,
            3,
            import_seulement=True,
        ),
        SourceDecl(
            JOURNAUX_SERVEUR,
            "Journaux d'accès du serveur du client",
            "analytique",
            ("visites_robots_ia",),
            24 * 35,
            0,
            import_seulement=True,
        ),
    )
}
SOURCES_LECTURE = tuple(s.id for s in SOURCES.values() if not s.import_seulement)
SOURCES_IMPORT = tuple(SOURCES)

# -- format d'un fait ------------------------------------------------------------------------------------------------
CHAMPS_FAIT = (
    "fait_id",
    "revision",
    "source",
    "compte_ref",
    "nature",
    "portee",
    "periode_debut",
    "periode_fin",
    "mesures",
    "devise",
    "echantillon",
    "texte",
    "observe_le",
    "fictif",
    "provenance",
)
MAX_MESURES = 24
MAX_OCTETS_FAIT = 4096
TEXTE_MAX = 300

_COMPTE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_MESURE_NOM = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_DECIMAL = re.compile(r"^-?[0-9]{1,15}(?:\.[0-9]{1,8})?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")
_FAIT_ID = re.compile(r"^[0-9a-f]{32}$")
_VERSION_API = re.compile(r"^[A-Za-z0-9._/-]{1,40}$")


def compte_valide(valeur: Any) -> bool:
    return isinstance(valeur, str) and _COMPTE.fullmatch(valeur) is not None


def decimal_valide(valeur: Any) -> bool:
    return isinstance(valeur, str) and _DECIMAL.fullmatch(valeur) is not None


def date_iso(valeur: Any, champ: str = "date") -> date:
    if not isinstance(valeur, str) or not _DATE.fullmatch(valeur):
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"{champ} attendu AAAA-MM-JJ", 422)
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"{champ} n'est pas une date civile", 422) from None


def instant_rfc3339(valeur: Any, champ: str = "instant") -> datetime:
    """Un instant RFC 3339 AVEC fuseau ; sans fuseau il est refusé, jamais supposé UTC."""
    if not isinstance(valeur, str) or len(valeur) > 40:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"{champ} attendu en RFC 3339 avec fuseau", 422)
    try:
        instant = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"{champ} n'est pas un instant RFC 3339", 422) from None
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"{champ} sans fuseau : refusé, jamais supposé UTC", 422)
    return instant


def _texte_propre(valeur: Any, maximum: int, champ: str) -> str:
    if not isinstance(valeur, str):
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"{champ} attendu : texte", 422)
    texte = unicodedata.normalize("NFC", valeur).strip()
    if not 1 <= len(texte) <= maximum or any(unicodedata.category(c).startswith("C") for c in texte):
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"{champ} vide, trop long ou avec caractère de contrôle", 422)
    return texte


def identifiant_fait(source: str, compte_ref: str, nature: str, portee: Mapping[str, Any], debut: str, fin: str) -> str:
    """Identité d'un fait : la même source, le même compte, la même nature, la même portée et la même période désignent
    le MÊME fait (ses valeurs peuvent être révisées par le fournisseur ; l'identité, jamais)."""
    corps = json.dumps(
        [source, compte_ref, nature, portee["type"], portee["ref"], debut, fin],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(corps.encode("utf-8")).hexdigest()[:32]


def normaliser_fait(brut: Mapping[str, Any]) -> dict[str, Any]:
    """Forme canonique d'un fait (seule forme stockée) ou `ErreurSignaux(REJ-SIGNAUX-FAIT-INVALIDE)`. Aucune valeur par
    défaut : un champ absent ou inconnu est refusé. `fait_id` est RECALCULÉ, jamais cru."""
    if not isinstance(brut, Mapping):
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", "fait attendu : objet", 422)
    manquants, inconnus = sorted(set(CHAMPS_FAIT) - set(brut)), sorted(set(brut) - set(CHAMPS_FAIT))
    if manquants or inconnus:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"champs manquants {manquants}, champs inconnus {inconnus}", 422)
    source = brut["source"]
    if source not in SOURCES:
        raise refus("REJ-SIGNAUX-SOURCE-INCONNUE", f"source attendue parmi {list(SOURCES)}", 422)
    if not compte_valide(brut["compte_ref"]):
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", "compte_ref invalide", 422)
    nature = brut["nature"]
    if nature not in NATURES or nature not in SOURCES[source].natures:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"nature {nature!r} non prise en charge par {source}", 422)
    portee = brut["portee"]
    if not isinstance(portee, Mapping) or set(portee) != {"type", "ref"} or portee["type"] not in TYPES_PORTEE:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"portee : {{type parmi {list(TYPES_PORTEE)}, ref}} attendu", 422)
    ref = _texte_propre(portee["ref"], 200, "portee.ref")
    debut, fin = date_iso(brut["periode_debut"], "periode_debut"), date_iso(brut["periode_fin"], "periode_fin")
    if debut > fin or (fin - debut).days > 366:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", "période inversée ou de plus de 367 jours", 422)
    revision = brut["revision"]
    if type(revision) is not int or revision < 1:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", "revision attendue : entier >= 1", 422)
    mesures = brut["mesures"]
    if not isinstance(mesures, Mapping) or not 1 <= len(mesures) <= MAX_MESURES:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"mesures : 1 à {MAX_MESURES} entrées attendues", 422)
    for nom, valeur in mesures.items():
        if not isinstance(nom, str) or not _MESURE_NOM.fullmatch(nom) or not decimal_valide(valeur):
            raise refus(
                "REJ-SIGNAUX-FAIT-INVALIDE",
                f"mesure {nom!r} : nom en snake_case et valeur en TEXTE décimal (jamais un nombre JSON)",
                422,
            )
    devise = brut["devise"]
    if devise is not None and devise not in ("CAD", "USD", "EUR"):
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", "devise : CAD, USD, EUR ou null", 422)
    ech = brut["echantillon"]
    if not isinstance(ech, Mapping) or set(ech) != {"nature", "n"} or ech["nature"] not in ECHANTILLONS:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"echantillon : {{nature parmi {list(ECHANTILLONS)}, n}} attendu", 422)
    if ech["n"] is not None and (type(ech["n"]) is not int or ech["n"] < 0):
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", "echantillon.n : entier >= 0 ou null", 422)
    texte = brut["texte"]
    if texte is not None:
        texte = _texte_propre(texte, TEXTE_MAX, "texte")
    instant_rfc3339(brut["observe_le"], "observe_le")
    if type(brut["fictif"]) is not bool:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", "fictif : booléen attendu", 422)
    prov = brut["provenance"]
    champs_prov = {"fournisseur", "point_acces", "version_api", "mode", "empreinte_reponse", "page"}
    if not isinstance(prov, Mapping) or set(prov) != champs_prov:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"provenance : champs {sorted(champs_prov)} attendus", 422)
    if (
        prov["mode"] not in MODES
        or not isinstance(prov["version_api"], str)
        or not _VERSION_API.fullmatch(prov["version_api"])
        or not isinstance(prov["empreinte_reponse"], str)
        or not _EMPREINTE.fullmatch(prov["empreinte_reponse"])
        or type(prov["page"]) is not int
        or prov["page"] < 0
        or not all(isinstance(prov[c], str) and 1 <= len(prov[c]) <= 80 for c in ("fournisseur", "point_acces"))
    ):
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", "provenance invalide (mode, version_api, empreinte, page)", 422)
    canonique = {
        "fait_id": identifiant_fait(
            source, brut["compte_ref"], nature, {"type": portee["type"], "ref": ref}, debut.isoformat(), fin.isoformat()
        ),
        "revision": revision,
        "source": source,
        "compte_ref": brut["compte_ref"],
        "nature": nature,
        "portee": {"type": portee["type"], "ref": ref},
        "periode_debut": debut.isoformat(),
        "periode_fin": fin.isoformat(),
        "mesures": {k: mesures[k] for k in sorted(mesures)},
        "devise": devise,
        "echantillon": {"nature": ech["nature"], "n": ech["n"]},
        "texte": texte,
        "observe_le": brut["observe_le"],
        "fictif": brut["fictif"],
        "provenance": {k: prov[k] for k in sorted(prov)},
    }
    if brut["fait_id"] != canonique["fait_id"]:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", "fait_id ne correspond pas à l'identité du fait (recalculé)", 422)
    if len(json.dumps(canonique, ensure_ascii=False).encode("utf-8")) > MAX_OCTETS_FAIT:
        raise refus("REJ-SIGNAUX-FAIT-INVALIDE", f"fait de plus de {MAX_OCTETS_FAIT} octets", 422)
    return canonique


def sans_provenance_variable(fait: Mapping[str, Any]) -> dict[str, Any]:
    """Ce qui fait la VALEUR d'un fait (pour décider d'une révision) : ni la page lue, ni l'empreinte de la réponse, ni
    l'instant d'observation ne comptent ; les mesures, l'échantillon, le texte et la devise comptent."""
    return {k: fait[k] for k in ("fait_id", "mesures", "devise", "echantillon", "texte", "fictif")}


def brouillon_fait(
    *,
    source: str,
    compte_ref: str,
    nature: str,
    portee_type: str,
    portee_ref: str,
    debut: str,
    fin: str,
    mesures: Mapping[str, str],
    observe_le: str,
    fictif: bool,
    provenance: Mapping[str, Any],
    echantillon: Mapping[str, Any] | None = None,
    devise: str | None = None,
    texte: str | None = None,
) -> dict[str, Any]:
    """Assemble un fait de révision 1 avec son `fait_id` : ce que les connecteurs produisent avant `normaliser_fait`."""
    ref = unicodedata.normalize("NFC", portee_ref).strip()
    portee = {"type": portee_type, "ref": ref}
    return {
        "fait_id": identifiant_fait(source, compte_ref, nature, portee, debut, fin),
        "revision": 1,
        "source": source,
        "compte_ref": compte_ref,
        "nature": nature,
        "portee": portee,
        "periode_debut": debut,
        "periode_fin": fin,
        "mesures": dict(mesures),
        "devise": devise,
        "echantillon": dict(echantillon or {"nature": "complet", "n": None}),
        "texte": texte,
        "observe_le": observe_le,
        "fictif": fictif,
        "provenance": dict(provenance),
    }


@dataclasses.dataclass(frozen=True)
class Fenetre:
    """Les jours [debut, fin] (inclus) qu'un tour de lecture couvre."""

    debut: date
    fin: date

    def __post_init__(self) -> None:
        if (
            not isinstance(self.debut, date)
            or not isinstance(self.fin, date)
            or isinstance(self.debut, datetime)
            or isinstance(self.fin, datetime)
            or self.debut > self.fin
            or (self.fin - self.debut).days > 366
        ):
            raise refus("REJ-SIGNAUX-FENETRE-INVALIDE", "fenêtre : dates civiles, début <= fin, 367 jours au plus", 422)

    def cle(self) -> str:
        return f"{self.debut.isoformat()}/{self.fin.isoformat()}"


__all__ = [
    "BING_AI_PERFORMANCE",
    "BING_WEBMASTER",
    "CHAMPS_FAIT",
    "CRUX",
    "ECHANTILLONS",
    "GBP_AVIS",
    "GBP_INSIGHTS",
    "GOOGLE_ADS",
    "JOURNAUX_SERVEUR",
    "MATOMO",
    "META_ADS",
    "MODES",
    "NATURES",
    "PAGESPEED",
    "SCHEMA_FAIT",
    "SEARCH_CONSOLE",
    "SEARCH_CONSOLE_IA",
    "SOURCES",
    "SOURCES_IMPORT",
    "SOURCES_LECTURE",
    "UMAMI",
    "Fenetre",
    "SourceDecl",
    "brouillon_fait",
    "compte_valide",
    "date_iso",
    "decimal_valide",
    "identifiant_fait",
    "instant_rfc3339",
    "normaliser_fait",
    "sans_provenance_variable",
]
