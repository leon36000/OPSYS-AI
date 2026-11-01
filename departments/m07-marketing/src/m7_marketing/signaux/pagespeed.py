"""Connecteurs de LECTURE de PageSpeed Insights (API v5) et du Chrome UX Report (CrUX).

Deux sources distinctes, deux classes, un seul patron (`base.ConnecteurLecture`) :
- `ConnecteurPageSpeed` : une analyse Lighthouse (LABO : un seul passage, donc un échantillon de taille 1) par stratégie
  (`mobile`, `desktop`) et, si Google en a, les données de TERRAIN de la même réponse (`loadingExperience`, CrUX sur
  28 jours glissants) ;
- `ConnecteurCrux` : l'API CrUX interrogée directement pour l'ORIGINE du client, par appareil (`phone`, `desktop`).

Une absence n'est JAMAIS un zéro : un site trop peu visité n'a pas de données de terrain, la réponse n'en porte pas
et le connecteur n'écrit alors AUCUN fait de terrain. Pour CrUX, un 404 (« données introuvables ») n'est pas une
panne : la page est vide, sans fait et sans échec. Limite assumée : ce 404 ne distingue pas « origine trop peu
visitée » de « origine mal déclarée » ; la fraîcheur du compte reste `a_jour` même sans donnée de terrain, et
c'est l'absence de fait qui le dit.

Cadence : un tour par SEMAINE (R4 §3.2 : « chaque semaine »), aucune relecture avant sept jours pleins.

Lecture seule : un seul point d'accès par source (`runPagespeed`, `records:queryRecord`). La clé d'API voyage comme
`Authentification("parametre", clé, nom="key")` : le transport la place dans la requête ; elle n'est jamais dans l'URL
ni dans les paramètres que ce module construit.

Mesures (TEXTE décimal) :
- labo `vitesse_page_labo` : `score_performance` (0 à 100), `lcp_ms`, `cls` (3 décimales), `tbt_ms`, `fcp_ms`,
  `speed_index_ms` ; une audit sans valeur numérique est omise.
- terrain `terrain_cwv` : `lcp_p75_ms`, `cls_p75`, `inp_p75_ms`, `fcp_p75_ms`, `ttfb_p75_ms` (+ `lcp_bon`, `inp_bon`,
  `cls_bon`, `ttfb_bon` pour CrUX : densité du premier bac, la part « bonne »), et les catégories codées `*_categorie`
  et `global_categorie` : 1 = FAST (bon), 2 = AVERAGE (à améliorer), 3 = SLOW (mauvais).
Le fait d'une page porte `@mobile` / `@desktop` (PageSpeed) ou `@phone` / `@desktop` (CrUX) après son chemin, pour que
deux stratégies ne soient jamais le même fait.

AVERTISSEMENT : la forme des requêtes et des réponses reprend la documentation publique telle que la recherche R4
(§3.2) la rapporte ; elle n'a JAMAIS été exercée contre le vrai service (aucun réseau). Quotas : R4 rapporte environ
25 000 requêtes par jour pour PageSpeed (niveau S, chiffres variables) et ne chiffre pas CrUX ; le plafond local est
volontairement bien plus bas, il s'ajoute à celui du fournisseur.
"""

from __future__ import annotations

from datetime import UTC, date, timedelta
from decimal import Decimal
from typing import Any, ClassVar

from . import modele
from .base import ConnecteurLecture, PageLue, champ, empreinte_reponse, liste, nombre_texte
from .erreurs import ErreurSignaux, refus
from .minimisation import chemin_de_page
from .quotas import Quota
from .transport import Authentification

HOTE_PAGESPEED = "www.googleapis.com"
URL_PAGESPEED = f"https://{HOTE_PAGESPEED}/pagespeedonline/v5/runPagespeed"
POINT_ACCES_PAGESPEED = "runPagespeed"
HOTE_CRUX = "chromeuxreport.googleapis.com"
URL_CRUX = f"https://{HOTE_CRUX}/v1/records:queryRecord"
POINT_ACCES_CRUX = "records:queryRecord"
JOURS_ENTRE_LECTURES = 7
JOURS_TERRAIN = 28
CATEGORIES = {"FAST": "1", "AVERAGE": "2", "SLOW": "3"}
_QUOTA = Quota(par_minute=10, par_jour=200,
               source="R4 §3.2 (S : environ 25 000 requêtes par jour, non revérifié) ; plafond local prudent")

# (audit Lighthouse, mesure, décimales)
_AUDITS = (
    ("largest-contentful-paint", "lcp_ms", 0),
    ("cumulative-layout-shift", "cls", 3),
    ("total-blocking-time", "tbt_ms", 0),
    ("first-contentful-paint", "fcp_ms", 0),
    ("speed-index", "speed_index_ms", 0),
)
# (métrique PageSpeed `loadingExperience`, mesure, centièmes ?, décimales)
_TERRAIN_PSI = (
    ("LARGEST_CONTENTFUL_PAINT_MS", "lcp", False, 0),
    ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "cls", True, 3),
    ("INTERACTION_TO_NEXT_PAINT", "inp", False, 0),
    ("FIRST_CONTENTFUL_PAINT_MS", "fcp", False, 0),
    ("EXPERIMENTAL_TIME_TO_FIRST_BYTE", "ttfb", False, 0),
)
_UNITES_P75 = {"lcp": "lcp_p75_ms", "cls": "cls_p75", "inp": "inp_p75_ms", "fcp": "fcp_p75_ms", "ttfb": "ttfb_p75_ms"}
# (métrique CrUX, préfixe de mesure, décimales du p75)
_METRIQUES_CRUX = (
    ("largest_contentful_paint", "lcp", 0),
    ("interaction_to_next_paint", "inp", 0),
    ("cumulative_layout_shift", "cls", 3),
    ("experimental_time_to_first_byte", "ttfb", 0),
)
FORMES_CRUX = {"phone": "PHONE", "desktop": "DESKTOP"}


class _ConnecteurHebdomadaire(ConnecteurLecture):
    """Cadence commune : un tour par semaine, la fenêtre est le jour même."""

    def fenetre_suivante(self, watermark: date | None, aujourd_hui: date) -> modele.Fenetre | None:
        if watermark is not None and (aujourd_hui - watermark).days < JOURS_ENTRE_LECTURES:
            return None
        return modele.Fenetre(aujourd_hui, aujourd_hui)

    def _authentification(self, principal: str, annexes: Any) -> Authentification:
        return Authentification("parametre", principal, nom="key")

    def _verifier_appel(self, flux: str, curseur: str | None) -> None:
        if flux not in self.FLUX:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"flux inconnu {flux!r}", 422)
        if curseur is not None:
            raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "cette source n'a qu'une page : aucun curseur n'existe", 422)


def _reponse_invalide(detail: str) -> ErreurSignaux:
    return refus("REJ-SIGNAUX-REPONSE-INVALIDE", detail, 502)


def _categorie(valeur: Any) -> str:
    if not isinstance(valeur, str) or valeur not in CATEGORIES:
        raise _reponse_invalide("catégorie de métrique inconnue dans la réponse du fournisseur")
    return CATEGORIES[valeur]


class ConnecteurPageSpeed(_ConnecteurHebdomadaire):
    SOURCE = modele.PAGESPEED
    FOURNISSEUR = "google"
    VERSION_API = "pagespeedonline/v5"
    LIMITES = _QUOTA
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({POINT_ACCES_PAGESPEED})
    HOTES: ClassVar[frozenset[str]] = frozenset({HOTE_PAGESPEED})
    FLUX: ClassVar[tuple[str, ...]] = ("mobile", "desktop")

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        self._verifier_appel(flux, curseur)
        params = {"url": self.compte.ressource, "strategy": flux, "category": "performance"}
        reponse, empreinte = self._appeler(POINT_ACCES_PAGESPEED, "GET", URL_PAGESPEED, params=params)
        try:
            jour = modele.instant_rfc3339(champ(reponse, "analysisUTCTimestamp", types=(str,)),
                                          "analysisUTCTimestamp").astimezone(UTC).date()
        except ErreurSignaux as erreur:
            if erreur.code == "REJ-SIGNAUX-REPONSE-INVALIDE":
                raise
            raise _reponse_invalide("horodatage d'analyse illisible dans la réponse") from None
        if jour > fenetre.fin:
            raise _reponse_invalide("analyse datée du futur dans la réponse")
        portee = f"{chemin_de_page(self._masqueur, self.compte.ressource, 180)}@{flux}"
        faits = [self._fait_labo(reponse, flux, jour, portee, empreinte)]
        terrain = self._fait_terrain(reponse, flux, jour, portee, empreinte)
        if terrain is not None:
            faits.append(terrain)
        return PageLue(tuple(faits), None, True, self._instant(), fenetre.fin.isoformat(), empreinte)

    def _fait_labo(self, reponse: Any, flux: str, jour: date, portee: str, empreinte: str) -> dict[str, Any]:
        score = champ(reponse, "lighthouseResult", "categories", "performance", "score", types=(int, float))
        centiemes = Decimal(str(score)) * 100
        if not Decimal(0) <= centiemes <= Decimal(100):
            raise _reponse_invalide("score de performance hors de 0 à 1 dans la réponse")
        mesures = {"score_performance": nombre_texte(centiemes, 2)}
        audits = champ(reponse, "lighthouseResult", "audits", types=(dict,))
        for audit, mesure, decimales in _AUDITS:
            entree = audits.get(audit)
            if isinstance(entree, dict) and "numericValue" in entree:
                mesures[mesure] = nombre_texte(champ(entree, "numericValue", types=(int, float)), decimales)
        return modele.brouillon_fait(
            source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="vitesse_page_labo", portee_type="page",
            portee_ref=portee, debut=jour.isoformat(), fin=jour.isoformat(), mesures=mesures,
            observe_le=self._instant(), fictif=self.compte.fictif,
            provenance=self._provenance(POINT_ACCES_PAGESPEED, empreinte, 0),
            echantillon={"nature": "echantillonne", "n": 1})

    def _fait_terrain(self, reponse: Any, flux: str, jour: date, portee: str, empreinte: str) -> dict[str, Any] | None:
        experience = reponse.get("loadingExperience")
        if experience is None:
            return None
        if not isinstance(experience, dict):
            raise _reponse_invalide("loadingExperience : objet attendu")
        metriques = experience.get("metrics")
        if metriques is None:
            return None
        if not isinstance(metriques, dict):
            raise _reponse_invalide("loadingExperience.metrics : objet attendu")
        mesures: dict[str, str] = {}
        for nom, prefixe, centiemes, decimales in _TERRAIN_PSI:
            entree = metriques.get(nom)
            if entree is None:
                continue
            percentile = champ(entree, "percentile", types=(int, float))
            valeur = Decimal(str(percentile)) / 100 if centiemes else percentile
            mesures[_UNITES_P75[prefixe]] = nombre_texte(valeur, decimales)
            mesures[f"{prefixe}_categorie"] = _categorie(champ(entree, "category", types=(str,)))
        if not mesures:
            return None  # une absence de métrique n'est pas un zéro
        if experience.get("overall_category") not in (None, "NONE"):  # « NONE » : pas de catégorie globale, pas un zéro
            mesures["global_categorie"] = _categorie(experience["overall_category"])
        debut = jour - timedelta(days=JOURS_TERRAIN - 1)
        return modele.brouillon_fait(
            source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="terrain_cwv", portee_type="page",
            portee_ref=portee, debut=debut.isoformat(), fin=jour.isoformat(), mesures=mesures,
            observe_le=self._instant(), fictif=self.compte.fictif,
            provenance=self._provenance(POINT_ACCES_PAGESPEED, empreinte, 0),
            echantillon={"nature": "echantillonne", "n": None})


def _date_crux(valeur: Any) -> date:
    try:
        return date(champ(valeur, "year", types=(int,)), champ(valeur, "month", types=(int,)),
                    champ(valeur, "day", types=(int,)))
    except ValueError:
        raise _reponse_invalide("date de période CrUX invalide") from None


class ConnecteurCrux(_ConnecteurHebdomadaire):
    SOURCE = modele.CRUX
    FOURNISSEUR = "google"
    VERSION_API = "crux/v1"
    LIMITES = Quota(par_minute=10, par_jour=200,
                    source="R4 §3.2 (aucun chiffre officiel retenu pour CrUX) ; plafond local prudent")
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({POINT_ACCES_CRUX})
    HOTES: ClassVar[frozenset[str]] = frozenset({HOTE_CRUX})
    FLUX: ClassVar[tuple[str, ...]] = ("phone", "desktop")

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        self._verifier_appel(flux, curseur)
        corps = {"origin": self.compte.ressource, "formFactor": FORMES_CRUX[flux],
                 "metrics": [nom for nom, _, _ in _METRIQUES_CRUX]}
        try:
            reponse, empreinte = self._appeler(POINT_ACCES_CRUX, "POST", URL_CRUX, corps=corps)
        except ErreurSignaux as erreur:
            if erreur.code != "REJ-SIGNAUX-INTROUVABLE":
                raise
            # « données introuvables » : pas de donnée de terrain, ce n'est pas une panne
            return PageLue((), None, True, self._instant(), fenetre.fin.isoformat(),
                           empreinte_reponse({"introuvable": True}))
        record = champ(reponse, "record", types=(dict,))
        metriques = champ(record, "metrics", types=(dict,))
        mesures: dict[str, str] = {}
        for nom, prefixe, decimales in _METRIQUES_CRUX:
            entree = metriques.get(nom)
            if entree is None:
                continue
            mesures[_UNITES_P75[prefixe]] = nombre_texte(champ(entree, "percentiles", "p75",
                                                                types=(int, float, str)), decimales)
            if "histogram" in entree:
                bacs = liste(entree, "histogram", maximum=10)
                mesures[f"{prefixe}_bon"] = nombre_texte(champ(bacs, 0, "density", types=(int, float)), 4)
        if not mesures:
            return PageLue((), None, True, self._instant(), fenetre.fin.isoformat(), empreinte)
        periode = champ(record, "collectionPeriod", types=(dict,))
        debut, fin = _date_crux(champ(periode, "firstDate", types=(dict,))), \
            _date_crux(champ(periode, "lastDate", types=(dict,)))
        if debut > fin or (fin - debut).days > 366:
            raise _reponse_invalide("période de collecte CrUX incohérente")
        portee = f"{chemin_de_page(self._masqueur, self.compte.ressource, 180)}@{flux}"
        fait = modele.brouillon_fait(
            source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="terrain_cwv", portee_type="site",
            portee_ref=portee, debut=debut.isoformat(), fin=fin.isoformat(), mesures=mesures,
            observe_le=self._instant(), fictif=self.compte.fictif,
            provenance=self._provenance(POINT_ACCES_CRUX, empreinte, 0),
            echantillon={"nature": "echantillonne", "n": None})
        return PageLue((fait,), None, True, self._instant(), fenetre.fin.isoformat(), empreinte)


__all__ = ["CATEGORIES", "ConnecteurCrux", "ConnecteurPageSpeed", "FORMES_CRUX"]
