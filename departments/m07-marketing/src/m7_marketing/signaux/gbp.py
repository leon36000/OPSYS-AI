"""Connecteurs de LECTURE de la fiche d'établissement Google (Google Business Profile) : avis et performance.

Deux sources distinctes (deux jetons de portée, deux quotas) :
- `ConnecteurGbpAvis` : les avis de la fiche (API v4 des avis, R4 §3.4 : accès sur demande, 300 QPM une fois
approuvé — V).
  `GET /v4/accounts/N/locations/M/reviews?pageSize&pageToken` → `{reviews: [{reviewId, reviewer, starRating, comment,
  createTime, updateTime, reviewReply}], nextPageToken}`.
- `ConnecteurGbpInsights` : la performance quotidienne de la fiche (API Business Profile Performance). Un appel par
métrique,
  `GET /v1/locations/N:getDailyMetricsTimeSeries?dailyMetric&dailyRange.startDate.year…` →
  `{timeSeries: {datedValues: [{date: {year, month, day}, value}]}}` (la valeur est un TEXTE entier ; elle est ABSENTE
  quand le fournisseur n'en donne pas : un jour sans valeur est un TROU, jamais un zéro).

MINIMISATION (Loi 25) : le nom de l'auteur d'un avis (`reviewer`) n'est JAMAIS lu ni gardé. Un avis devient un fait
`avis` (identité = empreinte du `reviewId`, jamais le texte), avec sa note, s'il a une réponse et la longueur de son
texte. Le texte n'est conservé que si le client l'a demandé (option de compte `extraits_avis`) : un extrait de 280
caractères au plus, masqué par le masqueur d'observabilité, marqué non fiable (c'est un texte de tiers). Le masqueur
à motifs ne reconnaît pas un nom propre sans civilité : c'est pourquoi l'option est fermée par défaut.

Les avis arrivent du plus récent au plus ancien (`updateTime` décroissant) : la pagination s'arrête dès qu'une page
ne contient plus rien de mis à jour dans la fenêtre. Le fournisseur ne dédupliquant pas, un avis déjà vu est
identique (inchangé) ou révisé (une réponse ajoutée change `a_reponse`).

AVERTISSEMENT : la forme des requêtes et des réponses reprend la documentation publique telle que la recherche R4 la
rapporte ; elle n'a JAMAIS été exercée contre le vrai service (aucun réseau). Aucune méthode d'écriture
(`updateReply`, `deleteReply`,
localPosts) n'est dans la liste de lecture : répondre à un avis reste un geste de la direction, hors de ce module.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date
from typing import ClassVar

from . import modele
from .base import ConnecteurLecture, PageLue, champ, liste, nombre_texte
from .curseurs import decoder_curseur, encoder_curseur
from .erreurs import refus
from .minimisation import texte_minimise
from .quotas import Quota

HOTE_AVIS = "mybusiness.googleapis.com"
HOTE_PERFORMANCE = "businessprofileperformance.googleapis.com"
POINT_ACCES_AVIS = "accounts.locations.reviews.list"
POINT_ACCES_PERFORMANCE = "locations.getDailyMetricsTimeSeries"
TAILLE_PAGE_AVIS = 50
EXTRAIT_MAX = 280
NOTES = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
# métrique du fournisseur → nom de la mesure du fait
METRIQUES = {
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": "impressions_maps_ordinateur",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS": "impressions_maps_mobile",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": "impressions_recherche_ordinateur",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": "impressions_recherche_mobile",
    "CALL_CLICKS": "appels",
    "BUSINESS_DIRECTION_REQUESTS": "itineraires",
    "WEBSITE_CLICKS": "clics_site",
}


def _jour_de(instant_texte: str, champ_nom: str) -> date:
    return modele.instant_rfc3339(instant_texte, champ_nom).astimezone(UTC).date()


class ConnecteurGbpAvis(ConnecteurLecture):
    SOURCE = modele.GBP_AVIS
    FOURNISSEUR = "google"
    VERSION_API = "mybusiness/v4"
    LIMITES = Quota(par_minute=60, par_jour=3000,
                    source="R4 §3.4 (V : 300 QPM une fois l'accès approuvé) ; plafond local prudent")
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({POINT_ACCES_AVIS})
    HOTES: ClassVar[frozenset[str]] = frozenset({HOTE_AVIS})
    FLUX: ClassVar[tuple[str, ...]] = ("principal",)

    def _url(self) -> str:
        return f"https://{HOTE_AVIS}/v4/{self.compte.ressource}/reviews"

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        if flux not in self.FLUX:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"flux inconnu {flux!r}", 422)
        jeton_page = None
        if curseur:
            jeton_page = decoder_curseur(self.SOURCE, curseur).get("t")
            if not isinstance(jeton_page, str) or not 1 <= len(jeton_page) <= 1000:
                raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "curseur de lecture illisible", 422)
        params = {"pageSize": str(TAILLE_PAGE_AVIS)}
        if jeton_page is not None:
            params["pageToken"] = jeton_page
        reponse, empreinte = self._appeler(POINT_ACCES_AVIS, "GET", self._url(), params=params)
        avis = liste(reponse, "reviews") if isinstance(reponse, dict) and "reviews" in reponse else []
        garder_extraits = self.compte.option("extraits_avis")
        faits, vus, ignores, tous_plus_anciens = [], set(), 0, bool(avis)
        for a in avis:
            identifiant = champ(a, "reviewId", types=(str,))
            cree = _jour_de(champ(a, "createTime", types=(str,)), "createTime")
            mis_a_jour = _jour_de(champ(a, "updateTime", types=(str,)), "updateTime")
            if mis_a_jour >= fenetre.debut:
                tous_plus_anciens = False
            if not fenetre.debut <= cree <= fenetre.fin:
                continue
            note = NOTES.get(champ(a, "starRating", types=(str,)))
            if note is None:  # STAR_RATING_UNSPECIFIED ou valeur nouvelle : jamais une note devinée
                ignores += 1
                continue
            ref = hashlib.sha256(identifiant.encode("utf-8")).hexdigest()[:16]
            if ref in vus:
                ignores += 1
                continue
            vus.add(ref)
            commentaire = a.get("comment")
            texte = None
            if commentaire is not None:
                if not isinstance(commentaire, str):
                    raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "commentaire d'avis illisible", 502)
                if garder_extraits:
                    texte = texte_minimise(self._masqueur, commentaire, EXTRAIT_MAX) or None
            reponse_de_l_etablissement = a.get("reviewReply")
            if reponse_de_l_etablissement is not None and not isinstance(reponse_de_l_etablissement, dict):
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "réponse d'avis illisible", 502)
            mesures = {"note": str(note), "a_reponse": "1" if reponse_de_l_etablissement else "0",
                       "longueur_texte": str(len(commentaire) if isinstance(commentaire, str) else 0)}
            faits.append(modele.brouillon_fait(
                source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="avis", portee_type="avis",
                portee_ref=ref, debut=cree.isoformat(), fin=cree.isoformat(), mesures=mesures,
                observe_le=self._instant(), fictif=self.compte.fictif,
                provenance=self._provenance(POINT_ACCES_AVIS, empreinte, 0), texte=texte))
        suivant = reponse.get("nextPageToken") if isinstance(reponse, dict) else None
        if suivant is not None and (not isinstance(suivant, str) or not suivant):
            raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "nextPageToken illisible", 502)
        termine = suivant is None or tous_plus_anciens
        return PageLue(tuple(faits), None if termine else encoder_curseur(self.SOURCE, {"t": suivant}), termine,
                       self._instant(), fenetre.fin.isoformat(), empreinte, ignores=ignores)


class ConnecteurGbpInsights(ConnecteurLecture):
    SOURCE = modele.GBP_INSIGHTS
    FOURNISSEUR = "google"
    VERSION_API = "businessprofileperformance/v1"
    LIMITES = Quota(par_minute=60, par_jour=3000,
                    source="plafond interne prudent (aucune valeur officielle retenue pour l'API Performance)")
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({POINT_ACCES_PERFORMANCE})
    HOTES: ClassVar[frozenset[str]] = frozenset({HOTE_PERFORMANCE})
    FLUX: ClassVar[tuple[str, ...]] = ("principal",)

    def _url(self) -> str:
        return f"https://{HOTE_PERFORMANCE}/v1/{self.compte.ressource}:getDailyMetricsTimeSeries"

    @staticmethod
    def _params(metrique: str, fenetre: modele.Fenetre) -> dict[str, str]:
        return {
            "dailyMetric": metrique,
            "dailyRange.startDate.year": str(fenetre.debut.year),
                "dailyRange.startDate.month": str(fenetre.debut.month),
            "dailyRange.startDate.day": str(fenetre.debut.day),
            "dailyRange.endDate.year": str(fenetre.fin.year), "dailyRange.endDate.month": str(fenetre.fin.month),
            "dailyRange.endDate.day": str(fenetre.fin.day),
        }

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        """Une « page » = TOUTES les métriques de la fenêtre (une requête par métrique, chacune réservée au quota) :
        un échec
        au milieu rejoue la page entière, sans effet (les faits sont idempotents)."""
        if flux not in self.FLUX:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"flux inconnu {flux!r}", 422)
        if curseur:
            raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "ce flux n'a pas de curseur de page", 422)
        par_jour: dict[date, dict[str, str]] = {}
        empreintes: list[str] = []
        for metrique, nom in METRIQUES.items():
            reponse, empreinte = self._appeler(POINT_ACCES_PERFORMANCE, "GET", self._url(),
                                               params=self._params(metrique, fenetre))
            empreintes.append(empreinte)
            valeurs = liste(reponse, "timeSeries", "datedValues") if "datedValues" in champ(
                reponse, "timeSeries", types=(dict,)) else []
            for v in valeurs:
                d = champ(v, "date", types=(dict,))
                try:
                    jour = date(champ(d, "year", types=(int,)), champ(d, "month", types=(int,)),
                                champ(d, "day", types=(int,)))
                except ValueError:
                    raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "date civile invalide dans la réponse", 502) from None
                if not fenetre.debut <= jour <= fenetre.fin:
                    raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "jour hors de la période demandée", 502)
                if "value" not in v or v["value"] is None:
                    continue  # un jour sans valeur est un TROU : aucune mesure, jamais un zéro
                texte = champ(v, "value", types=(str, int))
                par_jour.setdefault(jour, {})[nom] = nombre_texte(texte, 0)
        empreinte_totale = hashlib.sha256("|".join(empreintes).encode("ascii")).hexdigest()
        faits = [
            modele.brouillon_fait(
                source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="insights_fiche_jour",
                    portee_type="fiche",
                portee_ref=self.compte.ressource, debut=jour.isoformat(), fin=jour.isoformat(),
                mesures=dict(sorted(mesures.items())), observe_le=self._instant(), fictif=self.compte.fictif,
                provenance=self._provenance(POINT_ACCES_PERFORMANCE, empreinte_totale, 0))
            for jour, mesures in sorted(par_jour.items())
        ]
        return PageLue(tuple(faits), None, True, self._instant(), fenetre.fin.isoformat(), empreinte_totale,
                       appels=len(METRIQUES))


__all__ = ["ConnecteurGbpAvis", "ConnecteurGbpInsights", "METRIQUES"]
