"""Connecteur de LECTURE de Bing Webmaster Tools (API JSON) : les requêtes réelles du site du client dans Bing.

Trois flux d'une propriété déclarée par le client (R4 §3.2 : indexation et requêtes, gratuit) :
- `jour` : clics et impressions par jour (`GetRankAndTrafficStats`), un fait `performance_recherche_jour` par jour ;
l'API ne rend pas de position moyenne par jour, le fait n'en porte donc pas ;
- `requetes` : les 100 premières requêtes de chaque SEMAINE complète (`GetQueryStats`) ;
- `pages` : les 100 premières pages de chaque semaine complète (`GetPageStats`).

Ce que l'API rend et ce que le connecteur en fait : l'API rend des lignes PAR DATE sur un historique glissant, sans
pagination ni paramètre de période. Le connecteur ne demande donc qu'UNE requête par flux et par tour, ignore les
dates hors fenêtre et AGRÈGE lui-même les lignes d'une même requête (ou page) sur la semaine, en Decimal : clics et
impressions s'additionnent ; la position moyenne est la moyenne des positions d'impression PONDÉRÉE par les
impressions (simple moyenne si aucune impression) ; le taux de clic est clics ÷ impressions (absent si aucune
impression). Une réponse de plus de 20 000 lignes est refusée (`REJ-SIGNAUX-REPONSE-TROP-GROSSE`), jamais tronquée.
Les dates arrivent au format `/Date(ms)/` : décodées en jour UTC ; tout autre format est refusé.

Le rapport « AI Performance » de Bing n'a pas d'API documentée (R4 §10, INCONNU) : il n'est PAS lu ici, il entre par
import manuel (`import_manuel.py`).

La clé d'API voyage comme paramètre nommé `apikey` (l'API Bing l'exige ainsi) : le connecteur la confie à
`Authentification`, le transport la place ; elle n'est jamais dans l'URL ni dans les paramètres du connecteur. Seuls
des points d'accès de lecture sont dans la liste blanche (`SubmitUrl`, `AddSite`… ne sont pas appelables).

AVERTISSEMENT : la forme des requêtes et des réponses reprend la documentation publique telle que la recherche R4 et la
connaissance générale la rapportent (champ `Query` pour l'URL de la page dans `GetPageStats`, notamment) ; elle n'a
JAMAIS été exercée contre le vrai service (aucun réseau).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

from . import modele
from .base import ConnecteurLecture, PageLue, champ, liste, nombre_texte
from .curseurs import decoder_curseur
from .erreurs import refus
from .minimisation import chemin_de_page, texte_minimise
from .quotas import Quota
from .search_console import semaines_completes
from .transport import Authentification

HOTE = "ssl.bing.com"
BASE = f"https://{HOTE}/webmaster/api.svc/json/"
POINT_JOUR = "GetRankAndTrafficStats"
POINT_REQUETES = "GetQueryStats"
POINT_PAGES = "GetPageStats"
LIGNES_TOP = 100
LIGNES_REPONSE_MAX = 20_000
_DATE_MS = re.compile(r"^/Date\((-?[0-9]{1,15})(?:[+-][0-9]{4})?\)/$")


def jour_depuis_ms(valeur: object) -> date:
    """`/Date(1696118400000)/` -> jour civil UTC. Tout autre format est une réponse invalide."""
    correspondance = _DATE_MS.fullmatch(valeur) if isinstance(valeur, str) else None
    if correspondance is None:
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "date de la réponse au format inattendu (/Date(ms)/ attendu)", 502)
    try:
        return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(correspondance.group(1)))).date()
    except (OverflowError, ValueError):
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "date de la réponse hors bornes", 502) from None


def _positif(valeur: object, decimales: int = 0) -> Decimal:
    texte = nombre_texte(valeur, decimales)
    nombre = Decimal(texte)
    if nombre < 0:
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "valeur négative dans la réponse du fournisseur", 502)
    return nombre


class ConnecteurBingWebmaster(ConnecteurLecture):
    SOURCE = modele.BING_WEBMASTER
    FOURNISSEUR = "microsoft"
    VERSION_API = "webmaster/api.svc/json"
    LIMITES = Quota(par_minute=30, par_jour=500,
                    source="R4 §3.2 (gratuit, H ; aucune valeur officielle retenue) ; plafond interne prudent")
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({POINT_JOUR, POINT_REQUETES, POINT_PAGES})
    HOTES: ClassVar[frozenset[str]] = frozenset({HOTE})
    FLUX: ClassVar[tuple[str, ...]] = ("jour", "requetes", "pages")
    HISTORIQUE_JOURS = 35
    RELECTURE_JOURS = 14

    def _authentification(self, principal: str, annexes: dict[str, str]) -> Authentification:
        return Authentification("parametre", principal, nom="apikey")

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        if flux not in self.FLUX:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"flux inconnu {flux!r}", 422)
        if curseur is not None:
            decoder_curseur(self.SOURCE, curseur)
            raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "ce connecteur n'émet aucun curseur : la réponse n'est pas "
                        "paginée", 422)
        semaines = [] if flux == "jour" else semaines_completes(fenetre)
        if flux != "jour" and not semaines:
            return PageLue((), None, True, self._instant(), None, "0" * 64, appels=0)
        point = {"jour": POINT_JOUR, "requetes": POINT_REQUETES, "pages": POINT_PAGES}[flux]
        reponse, empreinte = self._appeler(point, "GET", BASE + point, params={"siteUrl": self.compte.ressource})
        lignes = liste(reponse, "d", maximum=LIGNES_REPONSE_MAX)
        faits = self._faits_jour(lignes, fenetre, empreinte) if flux == "jour" \
            else self._faits_top(flux, lignes, semaines, empreinte)
        return PageLue(tuple(faits[0]), None, True, self._instant(), fenetre.fin.isoformat(), empreinte,
                       ignores=faits[1])

    def _faits_jour(self, lignes: list, fenetre: modele.Fenetre, empreinte: str):
        par_jour: dict[date, tuple[Decimal, Decimal]] = {}
        for ligne in lignes:
            jour = jour_depuis_ms(champ(ligne, "Date", types=(str,)))
            if not fenetre.debut <= jour <= fenetre.fin:
                continue
            if jour in par_jour:
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "jour répété dans la réponse du fournisseur", 502)
            impressions = _positif(champ(ligne, "Impressions", types=(int, float)))
            clics = _positif(champ(ligne, "Clicks", types=(int, float)))
            if clics > impressions:
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "plus de clics que d'impressions", 502)
            par_jour[jour] = (impressions, clics)
        faits = []
        for jour in sorted(par_jour):
            impressions, clics = par_jour[jour]
            mesures = {"clics": nombre_texte(clics, 0), "impressions": nombre_texte(impressions, 0)}
            if impressions > 0:
                mesures["ctr"] = nombre_texte(clics / impressions, 6)
            faits.append(modele.brouillon_fait(
                source=self.SOURCE, compte_ref=self.compte.compte_ref, nature="performance_recherche_jour",
                portee_type="site", portee_ref="propriete", debut=jour.isoformat(), fin=jour.isoformat(),
                mesures=mesures, observe_le=self._instant(), fictif=self.compte.fictif,
                provenance=self._provenance(POINT_JOUR, empreinte, 0), echantillon={"nature": "complet", "n": None}))
        return faits, 0

    def _faits_top(self, flux: str, lignes: list, semaines: list[tuple[date, date]], empreinte: str):
        # par semaine, par clé brute : [impressions, clics, somme(impressions × position), somme(positions), lignes]
        cumuls: list[dict[str, list[Decimal]]] = [{} for _ in semaines]
        for ligne in lignes:
            jour = jour_depuis_ms(champ(ligne, "Date", types=(str,)))
            indice = (jour - semaines[0][0]).days // 7
            if not 0 <= indice < len(semaines):
                continue
            cle = champ(ligne, "Query", types=(str,))
            impressions = _positif(champ(ligne, "Impressions", types=(int, float)))
            clics = _positif(champ(ligne, "Clicks", types=(int, float)))
            position = _positif(champ(ligne, "AvgImpressionPosition", types=(int, float)), 2)
            if clics > impressions:
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "plus de clics que d'impressions", 502)
            c = cumuls[indice].setdefault(cle, [Decimal(0)] * 5)
            c[0] += impressions
            c[1] += clics
            c[2] += impressions * position
            c[3] += position
            c[4] += 1
        nature, portee_type = ("requetes_periode", "requete") if flux == "requetes" else ("pages_periode", "page")
        echantillon = {"nature": "anonymise_partiel" if flux == "requetes" else "echantillonne", "n": None}
        faits, ignores = [], 0
        for (debut, fin), semaine in zip(semaines, cumuls, strict=True):
            vus: set[str] = set()
            classes = sorted(semaine.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))[:LIGNES_TOP]
            for cle, (impr, clics, pondere, somme, n) in classes:
                ref = texte_minimise(self._masqueur, cle, 200) if flux == "requetes" \
                    else chemin_de_page(self._masqueur, cle)
                if ref in vus:
                    ignores += 1
                    continue
                vus.add(ref)
                moyenne = pondere / impr if impr > 0 else somme / n
                mesures = {"clics": nombre_texte(clics, 0), "impressions": nombre_texte(impr, 0),
                           "position": nombre_texte(moyenne, 2)}
                if impr > 0:
                    mesures["ctr"] = nombre_texte(clics / impr, 6)
                faits.append(modele.brouillon_fait(
                    source=self.SOURCE, compte_ref=self.compte.compte_ref, nature=nature, portee_type=portee_type,
                    portee_ref=ref, debut=debut.isoformat(), fin=fin.isoformat(), mesures=mesures,
                    observe_le=self._instant(), fictif=self.compte.fictif,
                    provenance=self._provenance(POINT_REQUETES if flux == "requetes" else POINT_PAGES, empreinte, 0),
                    echantillon=echantillon))
        return faits, ignores


__all__ = ["ConnecteurBingWebmaster", "jour_depuis_ms"]
