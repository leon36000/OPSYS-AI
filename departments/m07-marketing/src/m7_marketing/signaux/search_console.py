"""Connecteur de LECTURE de Google Search Console (API Search Analytics) : les requêtes réelles du site du client.

Lit trois flux d'une propriété déclarée par le client (R4 §3.2 : la meilleure source pour un site existant) :
- `jour` : clics, impressions, taux de clic et position moyenne, un fait par jour (dimension `date`) ;
- `requetes` : les 100 premières requêtes de chaque SEMAINE complète (dimension `query`), requêtes masquées contre les
  renseignements personnels ;
- `pages` : les 100 premières pages de chaque semaine complète (dimension `page`), chemins sans paramètres.

Ce que le fournisseur dit de ses chiffres est repris tel quel : les requêtes rares sont anonymisées et les lignes sont
tronquées aux premières (`anonymise_partiel`), les jours sont révisables (`dataState: final`, retard de quelques jours).
Le rapport « IA générative » n'est PAS lu ici : son exposition par l'API n'est pas documentée (R4 §10, INCONNU) ; il
entre
par import manuel (`import_manuel.py`).

Quota (R4 §3.2 « V ») : 1 200 requêtes par minute par site et par utilisateur ; le plafond local est plus bas. Une seule
méthode est appelée (`searchAnalytics.query`, un POST de lecture) : aucune méthode d'écriture (`sites.add`,
`sitemaps.submit`)
n'est dans la liste de lecture.

AVERTISSEMENT : la forme des requêtes et des réponses reprend la documentation publique telle que la recherche R4 la
rapporte ; elle n'a JAMAIS été exercée contre le vrai service (aucun réseau).
"""

from __future__ import annotations

import urllib.parse
from datetime import date, timedelta
from typing import ClassVar

from . import modele
from .base import ConnecteurLecture, PageLue, champ, liste, nombre_texte
from .curseurs import decoder_curseur, encoder_curseur
from .erreurs import refus
from .minimisation import chemin_de_page, texte_minimise
from .quotas import Quota

HOTE = "searchconsole.googleapis.com"
LIGNES_JOUR = 1000
LIGNES_TOP = 100
POINT_ACCES = "searchAnalytics.query"


def semaines_completes(fenetre: modele.Fenetre) -> list[tuple[date, date]]:
    """Les semaines ISO (lundi à dimanche) ENTIÈREMENT comprises dans la fenêtre."""
    lundi = fenetre.debut + timedelta(days=(7 - fenetre.debut.weekday()) % 7)
    semaines = []
    while lundi + timedelta(days=6) <= fenetre.fin:
        semaines.append((lundi, lundi + timedelta(days=6)))
        lundi += timedelta(days=7)
    return semaines


class ConnecteurSearchConsole(ConnecteurLecture):
    SOURCE = modele.SEARCH_CONSOLE
    FOURNISSEUR = "google"
    VERSION_API = "webmasters/v3"
    LIMITES = Quota(
        par_minute=60,
        par_jour=2000,
        source="R4 §3.2 (V : 1 200 QPM par site et par utilisateur) ; plafond local prudent",
    )
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({POINT_ACCES})
    HOTES: ClassVar[frozenset[str]] = frozenset({HOTE})
    FLUX: ClassVar[tuple[str, ...]] = ("jour", "requetes", "pages")
    HISTORIQUE_JOURS = 35
    RELECTURE_JOURS = 14

    def _url(self) -> str:
        site = urllib.parse.quote(self.compte.ressource, safe="")
        return f"https://{HOTE}/webmasters/v3/sites/{site}/searchAnalytics/query"

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        if flux not in self.FLUX:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"flux inconnu {flux!r}", 422)
        etat = decoder_curseur(self.SOURCE, curseur) if curseur else {"s": 0, "r": 0}
        indice, ligne0 = etat.get("s"), etat.get("r")
        if type(indice) is not int or type(ligne0) is not int or indice < 0 or ligne0 < 0:
            raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "curseur de lecture illisible", 422)
        if flux == "jour":
            periode, dimension, limite = (fenetre.debut, fenetre.fin), "date", LIGNES_JOUR
            derniere_tranche = True
        else:
            semaines = semaines_completes(fenetre)
            if not semaines:
                return PageLue((), None, True, self._instant(), None, "0" * 64, appels=0)
            if indice >= len(semaines):
                raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "curseur hors de la fenêtre", 422)
            periode, dimension, limite = semaines[indice], "query" if flux == "requetes" else "page", LIGNES_TOP
            derniere_tranche = indice == len(semaines) - 1
        corps = {
            "startDate": periode[0].isoformat(),
            "endDate": periode[1].isoformat(),
            "dimensions": [dimension],
            "rowLimit": limite,
            "startRow": ligne0,
            "dataState": "final",
            "type": "web",
        }
        reponse, empreinte = self._appeler(POINT_ACCES, "POST", self._url(), corps=corps)
        lignes = liste(reponse, "rows") if isinstance(reponse, dict) and "rows" in reponse else []
        faits, vus, ignores = [], set(), 0
        for ligne in lignes:
            cle = champ(ligne, "keys", 0, types=(str,))
            mesures = {
                "clics": nombre_texte(champ(ligne, "clicks", types=(int, float)), 0),
                "impressions": nombre_texte(champ(ligne, "impressions", types=(int, float)), 0),
                "ctr": nombre_texte(champ(ligne, "ctr", types=(int, float)), 6),
                "position": nombre_texte(champ(ligne, "position", types=(int, float)), 2),
            }
            if flux == "jour":
                jour = modele.date_iso(cle, "date de la réponse")
                if not periode[0] <= jour <= periode[1]:
                    raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "jour hors de la période demandée", 502)
                debut = fin = jour.isoformat()
                nature, portee = "performance_recherche_jour", ("site", "propriete")
                echantillon = {"nature": "complet", "n": None}
            else:
                debut, fin = periode[0].isoformat(), periode[1].isoformat()
                if flux == "requetes":
                    nature, echantillon = "requetes_periode", {"nature": "anonymise_partiel", "n": None}
                    portee = ("requete", texte_minimise(self._masqueur, cle, 200))
                else:
                    nature, echantillon = "pages_periode", {"nature": "echantillonne", "n": None}
                    portee = ("page", chemin_de_page(self._masqueur, cle))
            if (nature, portee[1], debut) in vus:
                # deux lignes pour un même jour : le fournisseur se contredit, rien n'est choisi pour lui
                if flux == "jour":
                    raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "jour répété dans la réponse du fournisseur", 502)
                # requêtes/pages qui se confondent après minimisation ou troncature : la première (la plus haute) reste
                ignores += 1
                continue
            vus.add((nature, portee[1], debut))
            faits.append(
                modele.brouillon_fait(
                    source=self.SOURCE,
                    compte_ref=self.compte.compte_ref,
                    nature=nature,
                    portee_type=portee[0],
                    portee_ref=portee[1],
                    debut=debut,
                    fin=fin,
                    mesures=mesures,
                    observe_le=self._instant(),
                    fictif=self.compte.fictif,
                    provenance=self._provenance(POINT_ACCES, empreinte, ligne0 // limite),
                    echantillon=echantillon,
                )
            )
        pleine = len(lignes) == limite and flux == "jour"  # le tronc des requêtes/pages est borné à dessein
        if pleine:
            suivant, termine = encoder_curseur(self.SOURCE, {"s": indice, "r": ligne0 + len(lignes)}), False
        elif flux != "jour" and not derniere_tranche:
            suivant, termine = encoder_curseur(self.SOURCE, {"s": indice + 1, "r": 0}), False
        else:
            suivant, termine = None, True
        return PageLue(
            tuple(faits), suivant, termine, self._instant(), fenetre.fin.isoformat(), empreinte, ignores=ignores
        )


__all__ = ["ConnecteurSearchConsole", "semaines_completes"]
