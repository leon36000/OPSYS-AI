"""Connecteurs de LECTURE des rapports publicitaires du client : Google Ads et Meta Ads (Marketing API, insights).

Ce que M7 lit : combien la plateforme dit avoir DÉPENSÉ, et ce qu'elle dit avoir obtenu (impressions, clics,
conversions), par jour, pour le compte entier (`compte_jour`) et par campagne (`campagne_jour`). Ce que M7 ne fait
JAMAIS ici : créer, modifier, mettre en pause ou financer une campagne. Les listes de points d'accès ne contiennent
que la lecture (`googleAds:search`, un POST de lecture ; `GET /insights`) : `googleAds:mutate`, `campaigns:mutate`
ou toute écriture Meta sont refusés par la base (`REJ-SIGNAUX-ECRITURE-INTERDITE`). Tout engagement de dépense reste
une décision N4 de la direction (sas social).

DÉPENSES : les faits `compte_jour` établissent des RELEVÉS de dépense TOTAUX (un par canal et par jour) et les faits
`campagne_jour` des relevés de campagne, inscrits au registre `depenses_marketing` (source `RELEVE_PLATEFORME`) par
`releves_depenses`. Règles : CAD seulement (une autre devise donne un fait avec sa devise et la mesure
`cout_devise`, jamais un relevé : M7 ne convertit rien) ; HORS TAXES (les rapports de coût des plateformes sont
avant taxes — à revérifier) ; un compte FICTIF n'écrit jamais de relevé (`ingestion._ecrire_releves`) ; une
relecture au même montant ne change rien, un montant révisé par la plateforme est la révision suivante du relevé.

GOOGLE ADS (REST, forme publique rapportée) : `POST /v17/customers/{id}/googleAds:search` avec `{query: GAQL, pageSize,
pageToken}` → `{results: [{campaign: {id, name}, metrics: {costMicros, impressions, clicks, conversions}, segments:
{date}, customer: {currencyCode}}], nextPageToken}`. Deux secrets : le jeton d'accès et le jeton de développeur
(secret annexe `jeton_developpeur`, en-tête `developer-token`), tous deux seulement en en-tête d'authentification.
`costMicros` est un texte entier : le coût est EXACT (micros / 1 000 000), arrondi au cent ROUND_HALF_UP pour la
mesure `cout_cad` (`cout_micros` conserve la valeur exacte).

META ADS (forme publique rapportée) : `GET /v21.0/act_N/insights?level&time_increment=1&time_range&fields&limit&after` →
`{data: [{campaign_id, campaign_name, spend, impressions, clicks, actions, account_currency, date_start, date_stop}],
paging: {cursors: {after}, next}}`. `paging.next` est une URL complète que l'on ne suit JAMAIS : seul `after` entre
dans le curseur. Une limite de débit Meta arrive en HTTP 400 avec un code d'erreur (4, 17, 32, 613, 80000 à 80014) :
ce n'est pas une requête invalide, c'est `REJ-SIGNAUX-LIMITE-DEBIT` (reprenable) ; le code 190 est un jeton refusé.
Conversions : le type `lead` est le TOTAL des prospects (les types `onsite_conversion.lead_grouped` et
`offsite_conversion.fb_pixel_lead` en sont des ventilations) ; on prend `lead` s'il existe, sinon la somme des deux
ventilations — jamais les trois ensemble (double compte). Si le champ `actions` est ABSENT, les conversions sont
inconnues : la mesure est omise, pas mise à zéro.

AVERTISSEMENT : ces formes reprennent la documentation publique telle que la recherche R4 la rapporte ; elles n'ont
JAMAIS été
exercées contre les vrais services (aucun réseau, aucun compte). Les versions d'API (v17, v21.0) sont à revérifier.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar

from opsys import stockage

from .. import depenses_marketing
from . import modele
from .base import ConnecteurLecture, PageLue, champ, liste, nombre_texte
from .curseurs import decoder_curseur, encoder_curseur
from .erreurs import refus
from .minimisation import texte_minimise
from .quotas import Quota
from .transport import Authentification, ReponseHttp

HOTE_GOOGLE_ADS = "googleads.googleapis.com"
HOTE_META = "graph.facebook.com"
POINT_ACCES_GOOGLE = "googleAds:search"
POINT_ACCES_META = "act.insights"
TAILLE_PAGE_GOOGLE = 1000
TAILLE_PAGE_META = 500
DEVISES = ("CAD", "USD", "EUR")
CENT = Decimal("0.01")
_ID_NUMERIQUE = re.compile(r"^[0-9]{1,20}$")
_MICROS = re.compile(r"^[0-9]{1,15}$")
_DECIMAL_META = re.compile(r"^[0-9]{1,12}(?:\.[0-9]{1,8})?$")
# Types d'action Meta comptés comme prospects : `lead` est le total, les deux autres en sont des ventilations.
ACTION_PROSPECT_TOTAL = "lead"
ACTIONS_PROSPECT_VENTILEES = ("onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")
CODES_META_LIMITE = frozenset({4, 17, 32, 613, *range(80000, 80015)})
CODES_META_JETON = frozenset({190})
CODES_META_PERMISSION = frozenset({10, *range(200, 300)})


def cout_en_texte(cout: Decimal) -> str:
    """Le coût au cent près, ROUND_HALF_UP (arrondi commercial, explicite), en texte décimal."""
    return format(cout.quantize(CENT, rounding=ROUND_HALF_UP), "f")


def _objet(reponse: Any) -> Mapping[str, Any]:
    if not isinstance(reponse, dict):
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "objet JSON attendu dans la réponse", 502)
    return reponse


def _jour(texte: Any, fenetre: modele.Fenetre) -> date:
    jour = modele.date_iso(texte, "date de la réponse")
    if not fenetre.debut <= jour <= fenetre.fin:
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "jour hors de la période demandée", 502)
    return jour


class _ConnecteurPublicite(ConnecteurLecture):
    """Ce que Google Ads et Meta Ads partagent : les flux, la relecture des jours récents (les plateformes révisent la
    dépense : clics invalides, ajustements) et la fabrication des relevés de dépense."""

    CANAL: ClassVar[str]
    PREFIXE_CAMPAGNE: ClassVar[str]
    FLUX: ClassVar[tuple[str, ...]] = ("compte", "campagnes")
    RELECTURE_JOURS = 7

    # -- faits ------------------------------------------------------------------------------------------------------
    def _fait(self, *, flux: str, jour: date, devise: str, cout: Decimal, autres: Mapping[str, str],
        campagne: str | None,
              nom: str | None, empreinte: str, point_acces: str, page: int) -> dict[str, Any]:
        mesures = {"cout_cad" if devise == "CAD" else "cout_devise": cout_en_texte(cout), **autres}
        if flux == "compte":
            nature, portee = "compte_jour", ("compte", self.compte.ressource)
        else:
            nature, portee = "campagne_jour", ("campagne", f"{self.PREFIXE_CAMPAGNE}-{campagne}")
        texte = texte_minimise(self._masqueur, nom, 120) or None if nom is not None else None
        return modele.brouillon_fait(
            source=self.SOURCE, compte_ref=self.compte.compte_ref, nature=nature, portee_type=portee[0],
            portee_ref=portee[1], debut=jour.isoformat(), fin=jour.isoformat(), mesures=dict(sorted(mesures.items())),
            observe_le=self._instant(), fictif=self.compte.fictif, devise=devise,
            provenance=self._provenance(point_acces, empreinte, page), texte=texte)

    # -- dépenses ---------------------------------------------------------------------------------------------------
    def _releve_id(self, campagne_ref: str | None, jour: str) -> str:
        naturel = "-".join(p for p in (self.CANAL, self.compte.compte_ref, campagne_ref, jour) if p)
        if len(naturel) <= 80:
            return naturel
        # trop long : empreinte du couple (compte, campagne). Le « : » n'existe dans aucun identifiant naturel (compte,
        # campagne, canal), donc une forme empreinte ne peut jamais en recouvrir une naturelle.
        cle = hashlib.sha256(f"{self.compte.compte_ref}\x1f{campagne_ref or ''}".encode()).hexdigest()[:20]
        return f"{self.CANAL}-h:{cle}-{jour}"

    @staticmethod
    def _releves_courants() -> dict[str, dict[str, Any]]:
        try:
            chaine = depenses_marketing._decoder_chaine(list(stockage.maillons(*depenses_marketing.REGISTRE)))
            courants = depenses_marketing._courants(chaine)
        except ValueError:
            raise refus("REJ-SIGNAUX-REGISTRE-INVALIDE", "le registre des dépenses est incohérent : aucun relevé n'est "
                        "établi", 500) from None
        return {r["releve_id"]: r for r in courants}

    def releves_depenses(self, faits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Les relevés de dépense que ces faits établissent. Jamais de conversion de devise : un fait non CAD n'en donne
        aucun. Une relecture au même montant rend le relevé DÉJÀ inscrit (idempotent) ; un montant différent rend la
        révision suivante, avec l'instant de l'observation."""
        existants = self._releves_courants()
        sortie = []
        for brut in faits:
            fait = modele.normaliser_fait(brut)
            if fait["source"] != self.SOURCE or fait["nature"] not in ("compte_jour", "campagne_jour"):
                continue
            if fait["devise"] != "CAD" or "cout_cad" not in fait["mesures"] \
                    or fait["periode_debut"] != fait["periode_fin"]:
                continue
            total = fait["nature"] == "compte_jour"
            campagne_ref = None if total else fait["portee"]["ref"]
            identifiant = self._releve_id(campagne_ref, fait["periode_debut"])
            voulu = {
                "releve_id": identifiant, "revision": 1, "canal": self.CANAL, "campagne_ref": campagne_ref,
                "libelle_campagne": None if total else fait["texte"], "periode_debut": fait["periode_debut"],
                "periode_fin": fait["periode_fin"], "montant_cad": fait["mesures"]["cout_cad"], "devise": "CAD",
                "base_taxes": "HORS_TAXES", "source": "RELEVE_PLATEFORME",
                "source_ref": f"{self.FOURNISSEUR}:{fait['provenance']['empreinte_reponse'][:16]}",
                "releve_le": fait["observe_le"],
            }
            courant = existants.get(identifiant)
            if courant is None:
                sortie.append(voulu)
                continue
            cles = ("canal", "campagne_ref", "libelle_campagne", "periode_debut", "periode_fin", "montant_cad",
                "devise",
                    "base_taxes", "source")
            if all(courant[c] == voulu[c] for c in cles):
                sortie.append(dict(courant))
            else:
                sortie.append({**voulu, "revision": courant["revision"] + 1})
        return sortie


# ======================================================================================================================
class ConnecteurGoogleAds(_ConnecteurPublicite):
    SOURCE = modele.GOOGLE_ADS
    CANAL = "google_ads"
    PREFIXE_CAMPAGNE = "gads"
    FOURNISSEUR = "google"
    VERSION_API = "googleads/v17"
    LIMITES = Quota(par_minute=60, par_jour=1500,
                    source="R4 §5.2 (V : Basic 15 000 opérations/jour, Explorer 2 880) ; plafond local prudent")
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({POINT_ACCES_GOOGLE})
    HOTES: ClassVar[frozenset[str]] = frozenset({HOTE_GOOGLE_ADS})

    def _authentification(self, principal: str, annexes: Mapping[str, str]) -> Authentification:
        return Authentification("bearer", principal, annexes=(("developer-token", annexes["jeton_developpeur"]),))

    def _url(self) -> str:
        return f"https://{HOTE_GOOGLE_ADS}/v17/customers/{self.compte.ressource}/googleAds:search"

    @staticmethod
    def _gaql(flux: str, fenetre: modele.Fenetre) -> str:
        """Une requête de LECTURE (GAQL SELECT). Les dates viennent d'objets `date` : jamais un texte de l'appelant."""
        d, f = fenetre.debut.isoformat(), fenetre.fin.isoformat()
        metriques = ("metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, "
                     "customer.currency_code, segments.date")
        if flux == "compte":
            return (f"SELECT {metriques} FROM customer WHERE segments.date BETWEEN '{d}' AND '{f}' "
                    "ORDER BY segments.date")
        return (f"SELECT campaign.id, campaign.name, {metriques} FROM campaign WHERE segments.date BETWEEN '{d}' AND "
                f"'{f}' ORDER BY segments.date, campaign.id")

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        if flux not in self.FLUX:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"flux inconnu {flux!r}", 422)
        jeton_page = None
        if curseur:
            jeton_page = decoder_curseur(self.SOURCE, curseur).get("t")
            if not isinstance(jeton_page, str) or not 1 <= len(jeton_page) <= 1000:
                raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "curseur de lecture illisible", 422)
        corps: dict[str, Any] = {"query": self._gaql(flux, fenetre), "pageSize": TAILLE_PAGE_GOOGLE}
        if jeton_page is not None:
            corps["pageToken"] = jeton_page
        reponse, empreinte = self._appeler(POINT_ACCES_GOOGLE, "POST", self._url(), corps=corps)
        lignes = liste(reponse, "results") if "results" in _objet(reponse) else []
        faits, vus, ignores = [], set(), 0
        for ligne in lignes:
            jour = _jour(champ(ligne, "segments", "date", types=(str,)), fenetre)
            devise = champ(ligne, "customer", "currencyCode", types=(str,))
            if devise not in DEVISES:
                ignores += 1
                continue
            metriques = champ(ligne, "metrics", types=(dict,))
            micros = str(champ(metriques, "costMicros", types=(str, int)))
            if not _MICROS.fullmatch(micros):
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "costMicros : entier positif en texte attendu", 502)
            campagne = nom = None
            if flux == "campagnes":
                campagne = str(champ(ligne, "campaign", "id", types=(str, int)))
                if not _ID_NUMERIQUE.fullmatch(campagne):
                    raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "identifiant de campagne invalide", 502)
                nom = champ(ligne, "campaign", "name", types=(str,))
            cle = (jour, campagne)
            if cle in vus:
                ignores += 1
                continue
            vus.add(cle)
            autres = {
                "cout_micros": micros,
                "impressions": nombre_texte(champ(metriques, "impressions", types=(str, int)), 0),
                "clics": nombre_texte(champ(metriques, "clicks", types=(str, int)), 0),
                "conversions": nombre_texte(champ(metriques, "conversions", types=(int, float, str)), 2),
            }
            faits.append(self._fait(
                flux=flux, jour=jour, devise=devise, cout=Decimal(micros) / Decimal(1_000_000), autres=autres,
                campagne=campagne, nom=nom, empreinte=empreinte, point_acces=POINT_ACCES_GOOGLE, page=0))
        suivant = _objet(reponse).get("nextPageToken")
        if suivant is not None and (not isinstance(suivant, str) or not suivant):
            raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "nextPageToken illisible", 502)
        return PageLue(tuple(faits), encoder_curseur(self.SOURCE, {"t": suivant}) if suivant else None, not suivant,
                       self._instant(), fenetre.fin.isoformat(), empreinte, ignores=ignores)


# ======================================================================================================================
class ConnecteurMetaAds(_ConnecteurPublicite):
    SOURCE = modele.META_ADS
    CANAL = "meta"
    PREFIXE_CAMPAGNE = "meta"
    FOURNISSEUR = "meta"
    VERSION_API = "graph/v21.0"
    LIMITES = Quota(par_minute=30, par_jour=1000,
                    source="plafond interne prudent (R4 §10 : niveaux d'accès Meta à revérifier)")
    POINTS_ACCES: ClassVar[frozenset[str]] = frozenset({POINT_ACCES_META})
    HOTES: ClassVar[frozenset[str]] = frozenset({HOTE_META})

    def _url(self) -> str:
        return f"https://{HOTE_META}/v21.0/{self.compte.ressource}/insights"

    def _lire_reponse(self, reponse: Any) -> tuple[Any, str]:
        """Meta signale ses limites de débit et ses jetons refusés par un HTTP 400 portant un code d'erreur : on les
        traduit AVANT la base, qui verrait une requête invalide."""
        if isinstance(reponse, ReponseHttp) and reponse.statut in (400, 401, 403) and isinstance(reponse.corps, dict):
            erreur = reponse.corps.get("error")
            code = erreur.get("code") if isinstance(erreur, dict) else None
            if type(code) is int:
                attente = 60
                for nom, valeur in (reponse.en_tetes or {}).items():
                    if isinstance(nom, str) and nom.lower() == "retry-after" and str(valeur).strip().isdigit():
                        attente = min(max(int(str(valeur).strip()), 1), 86400)
                if code in CODES_META_LIMITE:
                    raise refus("REJ-SIGNAUX-LIMITE-DEBIT", "limite de débit de Meta", 429, reprenable=True,
                                reessayer_apres_s=attente)
                if code in CODES_META_JETON:
                    raise refus("REJ-SIGNAUX-AUTH-REFUSEE", "jeton refusé, expiré ou révoqué : le renouveler dans le "
                                "coffre", 401)
                if code in CODES_META_PERMISSION:
                    raise refus("REJ-SIGNAUX-PERMISSION-REFUSEE", "permission refusée : le jeton n'a pas accès à ce "
                                "compte publicitaire", 403)
        return super()._lire_reponse(reponse)

    @staticmethod
    def _conversions(actions: Any) -> str | None:
        """Les prospects du jour, ou `None` si le champ `actions` est absent (inconnu, jamais zéro)."""
        if actions is None:
            return None
        if not isinstance(actions, list):
            raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "actions : liste attendue", 502)
        valeurs: dict[str, Decimal] = {}
        for action in actions:
            type_action = champ(action, "action_type", types=(str,))
            if type_action == ACTION_PROSPECT_TOTAL or type_action in ACTIONS_PROSPECT_VENTILEES:
                texte = str(champ(action, "value", types=(str, int)))
                if not _MICROS.fullmatch(texte):
                    raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "valeur d'action invalide", 502)
                valeurs[type_action] = valeurs.get(type_action, Decimal(0)) + Decimal(texte)
        total = valeurs.get(ACTION_PROSPECT_TOTAL)
        if total is None:
            total = sum((valeurs.get(t, Decimal(0)) for t in ACTIONS_PROSPECT_VENTILEES), Decimal(0))
        return nombre_texte(total, 0)

    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        if flux not in self.FLUX:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"flux inconnu {flux!r}", 422)
        apres = None
        if curseur:
            apres = decoder_curseur(self.SOURCE, curseur).get("a")
            if not isinstance(apres, str) or not 1 <= len(apres) <= 1000:
                raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "curseur de lecture illisible", 422)
        champs = "date_start,date_stop,spend,impressions,clicks,actions,account_currency"
        champs += ",campaign_id,campaign_name" if flux == "campagnes" else ""
        params = {
            "level": "account" if flux == "compte" else "campaign", "time_increment": "1",
            "time_range": json.dumps({"since": fenetre.debut.isoformat(), "until": fenetre.fin.isoformat()},
                                     separators=(",", ":")),
            "fields": champs, "limit": str(TAILLE_PAGE_META),
        }
        if apres is not None:
            params["after"] = apres
        reponse, empreinte = self._appeler(POINT_ACCES_META, "GET", self._url(), params=params)
        lignes = liste(reponse, "data") if "data" in _objet(reponse) else []
        faits, vus, ignores = [], set(), 0
        for ligne in lignes:
            debut = _jour(champ(ligne, "date_start", types=(str,)), fenetre)
            if champ(ligne, "date_stop", types=(str,)) != debut.isoformat():
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "ligne sur plusieurs jours avec time_increment=1", 502)
            devise = champ(ligne, "account_currency", types=(str,))
            if devise not in DEVISES:
                ignores += 1
                continue
            depense = str(champ(ligne, "spend", types=(str, int, float)))
            if not _DECIMAL_META.fullmatch(depense):
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "spend : décimal positif en texte attendu", 502)
            campagne = nom = None
            if flux == "campagnes":
                campagne = str(champ(ligne, "campaign_id", types=(str, int)))
                if not _ID_NUMERIQUE.fullmatch(campagne):
                    raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "identifiant de campagne invalide", 502)
                nom = champ(ligne, "campaign_name", types=(str,))
            cle = (debut, campagne)
            if cle in vus:
                ignores += 1
                continue
            vus.add(cle)
            autres = {"impressions": nombre_texte(champ(ligne, "impressions", types=(str, int)), 0)}
            if "clicks" in ligne:
                autres["clics"] = nombre_texte(champ(ligne, "clicks", types=(str, int)), 0)
            conversions = self._conversions(ligne.get("actions"))
            if conversions is not None:
                autres["conversions"] = conversions
            faits.append(self._fait(
                flux=flux, jour=debut, devise=devise, cout=Decimal(depense), autres=autres, campagne=campagne, nom=nom,
                empreinte=empreinte, point_acces=POINT_ACCES_META, page=0))
        paging = _objet(reponse).get("paging")
        suivant = None
        if isinstance(paging, dict) and paging.get("next"):
            # `paging.next` est une URL complète : on ne la suit JAMAIS ; seul le curseur `after` sert.
            suivant = champ(paging, "cursors", "after", types=(str,))
        return PageLue(tuple(faits), encoder_curseur(self.SOURCE, {"a": suivant}) if suivant else None, not suivant,
                       self._instant(), fenetre.fin.isoformat(), empreinte, ignores=ignores)


__all__ = ["ConnecteurGoogleAds", "ConnecteurMetaAds", "cout_en_texte"]
