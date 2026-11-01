"""Connecteurs de LECTURE de l'analytique AUTO-HÉBERGÉE du client : Umami et Matomo (R4 §3.1, mesure en première
partie).

Ces services tournent chez le client : aucun hôte n'est fixé par la classe ; l'unique hôte permis est celui de
l'adresse que le client a déclarée (`compte.base_url`, déjà validée : HTTPS, nom d'hôte public, sans identifiant ni
port ni paramètres). L'URL d'appel est cette adresse suivie d'un chemin d'API figé ; une URL tirée d'une réponse
n'est jamais suivie.

Umami (`ConnecteurUmami`, API v2/v3, jeton porteur) :
- `jour` : un fait `audience_jour` par jour (pages vues, visiteurs, visites, rebonds, durée totale) à partir d'UNE
requête `stats` par jour ; sept jours au plus par page (curseur `{j: index du jour}`), pour borner les requêtes d'un
tour ;
- `referents` : les 100 premiers référents de chaque SEMAINE complète (`metrics?type=referrer`), un fait
`referents_periode` par référent ; l'accès direct (référent vide) est nommé « (direct) ».
- La journée EN COURS n'est jamais lue (la fenêtre s'arrête à la veille, UTC) : l'analytique la complète encore.
- Le découpage des jours est en UTC : l'API accepte un fuseau en option, le connecteur ne le suppose pas. Un jour où
Umami rend 0 visite ET 0 page vue n'est PAS écrit : un compteur muet (balise absente ou en panne) ne se distingue pas
d'une journée creuse, et une absence n'est jamais un zéro (le jour est compté dans `ignores`).

Matomo (`ConnecteurMatomo`, Reporting API, `token_auth`) :
- `jour` : UNE requête `VisitsSummary.get` (période `day`, `date` = « début,fin ») ; un jour que Matomo rend `[]` est
un TROU, pas un zéro : aucun fait n'est émis ;
- `referents` : `Referrers.getWebsites` (période `range`) par SEMAINE complète, les 100 premiers sites référents.
- Le `token_auth` voyage dans le CORPS du POST (paramètre nommé confié à `Authentification`, placé par le transport),
jamais dans l'URL. Matomo répond HTTP 200 avec `{"result": "error"}` à une erreur d'accès ou de paramètre : traduit en
  `REJ-SIGNAUX-PERMISSION-REFUSEE`, sans recopier le message. Le point d'accès est la MÉTHODE d'API : seules
  `VisitsSummary.get` et `Referrers.getWebsites` sont dans la liste blanche (`SitesManager.addSite`,
  `UsersManager.*`… ne sont pas appelables).

AVERTISSEMENT : la forme des requêtes et des réponses reprend la documentation publique telle que la recherche R4 et la
connaissance générale la rapportent (forme `{value, prev}` d'Umami, clés `nb_*` de Matomo) ; elle n'a JAMAIS été exercée
contre un vrai Umami ni un vrai Matomo (aucun réseau).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar

from . import modele
from .base import ConnecteurLecture, PageLue, champ, empreinte_reponse, liste, nombre_texte
from .curseurs import decoder_curseur, encoder_curseur
from .erreurs import refus
from .minimisation import texte_minimise
from .quotas import Quota
from .search_console import semaines_completes
from .transport import Authentification

LIGNES_TOP = 100
JOURS_PAR_PAGE = 7


def _jours(fenetre: modele.Fenetre) -> list[date]:
    return [fenetre.debut + timedelta(days=i) for i in range((fenetre.fin - fenetre.debut).days + 1)]


def _ms(jour: date, *, fin_de_jour: bool = False) -> int:
    debut = int(datetime.combine(jour, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    return debut + 86_400_000 - 1 if fin_de_jour else debut


def _entier_curseur(donnees: dict[str, Any], cle: str, borne: int) -> int:
    valeur = donnees.get(cle, 0)
    if type(valeur) is not int or not 0 <= valeur < borne:
        raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "curseur de lecture illisible ou hors de la fenêtre", 422)
    return valeur


def _positif(valeur: object) -> Decimal:
    nombre = Decimal(nombre_texte(valeur, 0))
    if nombre < 0:
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "valeur négative dans la réponse du fournisseur", 502)
    return nombre


class _JourneeTerminee:
    """Une journée EN COURS n'est jamais lue : l'analytique la complète encore. La fenêtre s'arrête à la veille (UTC) ;
    la relecture des jours précédents rattrape toute révision."""

    def fenetre_suivante(self, watermark: date | None, aujourd_hui: date) -> modele.Fenetre | None:
        return super().fenetre_suivante(watermark, aujourd_hui - timedelta(days=1))  # type: ignore[misc]


class ConnecteurUmami(_JourneeTerminee, ConnecteurLecture):
    SOURCE = modele.UMAMI
    FOURNISSEUR = "umami"
    VERSION_API = "umami/v2"
    LIMITES = Quota(par_minute=60, par_jour=1000,
                    source="R4 §3.1 (API REST auto-hébergée, aucun quota officiel) ; plafond interne prudent")
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({"websites.stats", "websites.metrics"})
    FLUX: ClassVar[tuple[str, ...]] = ("jour", "referents")
    HISTORIQUE_JOURS = 28
    RELECTURE_JOURS = 14

    def _url(self, suffixe: str) -> str:
        return f"{self.compte.base_url}/api/websites/{self.compte.ressource}/{suffixe}"

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        if flux not in self.FLUX:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"flux inconnu {flux!r}", 422)
        donnees = decoder_curseur(self.SOURCE, curseur) if curseur else {}
        if flux == "jour":
            return self._page_jours(fenetre, _entier_curseur(donnees, "j", len(_jours(fenetre))))
        return self._page_referents(fenetre, _entier_curseur(donnees, "s", max(1, len(semaines_completes(fenetre)))))

    def _page_jours(self, fenetre: modele.Fenetre, depart: int) -> PageLue:
        jours = _jours(fenetre)
        lot = jours[depart:depart + JOURS_PAR_PAGE]
        faits, ignores, empreintes = [], 0, []
        for jour in lot:
            plage = {"startAt": str(_ms(jour)), "endAt": str(_ms(jour, fin_de_jour=True))}
            corps, empreinte = self._appeler("websites.stats", "GET", self._url("stats"), params=plage)
            empreintes.append(empreinte)
            valeurs = {nom: _positif(champ(corps, nom, "value", types=(int, float)))
                       for nom in ("pageviews", "visitors", "visits", "bounces", "totaltime")}
            if valeurs["bounces"] > valeurs["visits"]:
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "plus de rebonds que de visites", 502)
            if valeurs["visits"] == 0 and valeurs["pageviews"] == 0:
                ignores += 1  # aucune donnée : jamais un zéro
                continue
            faits.append(modele.brouillon_fait(
                source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="audience_jour", portee_type="site",
                portee_ref="propriete", debut=jour.isoformat(), fin=jour.isoformat(),
                mesures={"pages_vues": nombre_texte(valeurs["pageviews"], 0),
                         "visiteurs": nombre_texte(valeurs["visitors"], 0),
                         "visites": nombre_texte(valeurs["visits"], 0), "rebonds": nombre_texte(valeurs["bounces"], 0),
                         "duree_totale_s": nombre_texte(valeurs["totaltime"], 0)},
                observe_le=self._instant(), fictif=self.compte.fictif,
                provenance=self._provenance("websites.stats", empreinte, depart // JOURS_PAR_PAGE),
                echantillon={"nature": "complet", "n": None}))
        suite = depart + JOURS_PAR_PAGE
        termine = suite >= len(jours)
        return PageLue(tuple(faits), None if termine else encoder_curseur(self.SOURCE, {"j": suite}), termine,
                       self._instant(), fenetre.fin.isoformat(), empreinte_reponse(empreintes), appels=len(lot),
                       ignores=ignores)

    def _page_referents(self, fenetre: modele.Fenetre, indice: int) -> PageLue:
        semaines = semaines_completes(fenetre)
        if not semaines:
            return PageLue((), None, True, self._instant(), None, "0" * 64, appels=0)
        debut, fin = semaines[indice]
        corps, empreinte = self._appeler("websites.metrics", "GET", self._url("metrics"), params={
            "type": "referrer", "startAt": str(_ms(debut)), "endAt": str(_ms(fin, fin_de_jour=True)),
            "limit": str(LIGNES_TOP)})
        lignes = liste(corps)
        classes = sorted(((champ(ligne, "x", types=(str,)), _positif(champ(ligne, "y", types=(int, float))))
                          for ligne in lignes), key=lambda t: (-t[1], t[0]))[:LIGNES_TOP]
        faits, vus, ignores = [], set(), 0
        for x, visites in classes:
            ref = texte_minimise(self._masqueur, x, 200) if x else "(direct)"
            if ref in vus:
                ignores += 1
                continue
            vus.add(ref)
            faits.append(modele.brouillon_fait(
                source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="referents_periode",
                portee_type="referent", portee_ref=ref, debut=debut.isoformat(), fin=fin.isoformat(),
                mesures={"visites": nombre_texte(visites, 0)}, observe_le=self._instant(), fictif=self.compte.fictif,
                provenance=self._provenance("websites.metrics", empreinte, indice),
                echantillon={"nature": "echantillonne", "n": None}))
        dernier = indice == len(semaines) - 1
        return PageLue(tuple(faits), None if dernier else encoder_curseur(self.SOURCE, {"s": indice + 1}), dernier,
                       self._instant(), fenetre.fin.isoformat(), empreinte, ignores=ignores)


class ConnecteurMatomo(_JourneeTerminee, ConnecteurLecture):
    SOURCE = modele.MATOMO
    FOURNISSEUR = "matomo"
    VERSION_API = "matomo/reporting-api"
    LIMITES = Quota(par_minute=60, par_jour=1000,
                    source="R4 §3.1 (Reporting API auto-hébergée, aucun quota officiel) ; plafond interne prudent")
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({"VisitsSummary.get", "Referrers.getWebsites"})
    FLUX: ClassVar[tuple[str, ...]] = ("jour", "referents")
    HISTORIQUE_JOURS = 28
    RELECTURE_JOURS = 14

    def _authentification(self, principal: str, annexes: dict[str, str]) -> Authentification:
        return Authentification("parametre", principal, nom="token_auth")

    def _api(self, methode: str, periode: str, dates: str, **extra: str) -> tuple[Any, str]:
        corps = {"module": "API", "method": methode, "idSite": self.compte.ressource, "period": periode,
                 "date": dates, "format": "JSON", **extra}
        reponse, empreinte = self._appeler(methode, "POST", f"{self.compte.base_url}/index.php", corps=corps)
        if isinstance(reponse, dict) and reponse.get("result") == "error":
            raise refus("REJ-SIGNAUX-PERMISSION-REFUSEE", "erreur applicative de Matomo : accès ou site refusé", 403)
        return reponse, empreinte

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        if flux not in self.FLUX:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"flux inconnu {flux!r}", 422)
        donnees = decoder_curseur(self.SOURCE, curseur) if curseur else {}
        if flux == "jour":
            if donnees:
                raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "ce flux n'émet aucun curseur", 422)
            return self._page_jours(fenetre)
        return self._page_referents(fenetre, _entier_curseur(donnees, "s", max(1, len(semaines_completes(fenetre)))))

    def _page_jours(self, fenetre: modele.Fenetre) -> PageLue:
        dates = f"{fenetre.debut.isoformat()},{fenetre.fin.isoformat()}"
        reponse, empreinte = self._api("VisitsSummary.get", "day", dates)
        if isinstance(reponse, list) and reponse:
            raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "liste non vide là où un objet par jour est attendu", 502)
        faits, ignores = [], 0
        for cle in sorted(reponse if isinstance(reponse, dict) else {}):
            jour = modele.date_iso(cle, "jour de la réponse")
            if not fenetre.debut <= jour <= fenetre.fin:
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "jour hors de la fenêtre demandée", 502)
            valeur = reponse[cle]
            if isinstance(valeur, list) and not valeur:
                ignores += 1  # un trou : aucune donnée, jamais un zéro
                continue
            mesures = {nom: nombre_texte(_positif(champ(valeur, cle_api, types=(int, float))), 0)
                       for nom, cle_api in (("visites", "nb_visits"), ("visiteurs", "nb_uniq_visitors"),
                                            ("actions", "nb_actions"), ("rebonds", "bounce_count"),
                                            ("duree_totale_s", "sum_visit_length"))}
            faits.append(modele.brouillon_fait(
                source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="audience_jour", portee_type="site",
                portee_ref="propriete", debut=jour.isoformat(), fin=jour.isoformat(), mesures=mesures,
                observe_le=self._instant(), fictif=self.compte.fictif,
                provenance=self._provenance("VisitsSummary.get", empreinte, 0),
                echantillon={"nature": "complet", "n": None}))
        return PageLue(tuple(faits), None, True, self._instant(), fenetre.fin.isoformat(), empreinte, ignores=ignores)

    def _page_referents(self, fenetre: modele.Fenetre, indice: int) -> PageLue:
        semaines = semaines_completes(fenetre)
        if not semaines:
            return PageLue((), None, True, self._instant(), None, "0" * 64, appels=0)
        debut, fin = semaines[indice]
        reponse, empreinte = self._api("Referrers.getWebsites", "range", f"{debut.isoformat()},{fin.isoformat()}",
                                       filter_limit=str(LIGNES_TOP))
        lignes = liste(reponse)
        classes = sorted(((champ(ligne, "label", types=(str,)), _positif(champ(ligne, "nb_visits", types=(int, float))))
                          for ligne in lignes), key=lambda t: (-t[1], t[0]))[:LIGNES_TOP]
        faits, vus, ignores = [], set(), 0
        for label, visites in classes:
            ref = texte_minimise(self._masqueur, label, 200) if label else "(direct)"
            if ref in vus:
                ignores += 1
                continue
            vus.add(ref)
            faits.append(modele.brouillon_fait(
                source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="referents_periode",
                portee_type="referent", portee_ref=ref, debut=debut.isoformat(), fin=fin.isoformat(),
                mesures={"visites": nombre_texte(visites, 0)}, observe_le=self._instant(), fictif=self.compte.fictif,
                provenance=self._provenance("Referrers.getWebsites", empreinte, indice),
                echantillon={"nature": "echantillonne", "n": None}))
        dernier = indice == len(semaines) - 1
        return PageLue(tuple(faits), None if dernier else encoder_curseur(self.SOURCE, {"s": indice + 1}), dernier,
                       self._instant(), fenetre.fin.isoformat(), empreinte, ignores=ignores)


__all__ = ["ConnecteurMatomo", "ConnecteurUmami"]
