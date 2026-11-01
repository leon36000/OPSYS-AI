"""Le tour d'ingestion : lire une source de données propres, page par page, et l'écrire au registre — sans
doublon, sans trou.

Pour chaque flux d'un compte :
1. REPRENDRE ou OUVRIR : une fenêtre non terminée reprend à son curseur persisté ; sinon la prochaine fenêtre est
calculée du
   repère `watermark` (relecture des derniers jours, car les fournisseurs révisent) ;
2. LIRE une page (le quota local réserve la requête avant l'envoi ; le jeton sort du coffre le temps de l'appel, HORS
de toute
   transaction — le coffre refuse sinon) ;
3. ÉCRIRE, dans UNE transaction : les faits de la page (idempotents, révisés si le fournisseur a changé une valeur), les
   relevés de dépense que ces faits établissent (connecteurs publicitaires, comptes réels seulement), le curseur
   ATTEINT et le
   compte de requêtes du jour. Un échec entre la lecture et l'écriture rejoue la page ; il ne la saute jamais ;
4. à la FIN d'une fenêtre : le repère avance, la lecture réussie est datée (c'est elle qui définit la fraîcheur) et le
fait
   `m7.signaux_marketing_constates` est annoncé au bus (M8), avec les relevés de dépense totaux
   (`m7.depenses_marketing_constatees`,
   M5 et M8) — jamais une valeur de mesure, un texte ou un renseignement personnel.

Un échec typé (limite de débit, jeton refusé, fournisseur indisponible, coffre fermé) ne détruit rien : il est inscrit à
l'état du flux (code et instant), le curseur reste, et le tour rend un résultat `echec` (reprenable ou non). Un arrêt
demandé
s'applique entre deux pages. Aucune exception ne sort du tour sauf une faute de programmation.

Ce module ne contacte rien lui-même : le transport est un port injecté dans le connecteur. Aucun planificateur ne
l'appelle
dans cette version (voir `docs/architecture/M7-SIGNAUX.md`, « Ce qui n'est PAS prouvé »).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from opsys import evenements, stockage

from .. import depenses_marketing
from . import curseurs, modele, registre
from .base import ConnecteurLecture
from .erreurs import ErreurSignaux

PRODUCTEUR = "m07-marketing"
TYPE_SIGNAUX = "m7.signaux_marketing_constates"
TYPE_DEPENSES = "m7.depenses_marketing_constatees"
PAGES_MAX_PAR_TOUR = 200


@dataclasses.dataclass
class ResultatFlux:
    flux: str
    statut: str  # termine | interrompu | echec | rien_de_nouveau
    fenetre: str | None = None
    pages: int = 0
    faits_nouveaux: int = 0
    faits_revises: int = 0
    faits_inchanges: int = 0
    ignores: int = 0
    releves_ecrits: int = 0
    releves_non_ecrits: int = 0
    erreur: dict[str, Any] | None = None

    def publique(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _horodatage(maintenant: datetime) -> str:
    return maintenant.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _fenetre_depuis(texte: str) -> modele.Fenetre:
    debut, _, fin = texte.partition("/")
    return modele.Fenetre(modele.date_iso(debut), modele.date_iso(fin))


def _ecrire_releves(connecteur: ConnecteurLecture, faits: list[dict[str, Any]], resultat: ResultatFlux) -> list[dict]:
    """Relevés de dépense établis par ces faits. Un compte FICTIF n'en écrit jamais : une dépense fictive ne doit jamais
    devenir un fait que M5, M8 ou M9 liraient. Un relevé refusé par M7 (devise non CAD, chevauchement) est compté,
    jamais
    forcé ni converti."""
    releves = connecteur.releves_depenses(faits)
    ecrits = []
    if connecteur.compte.fictif:
        resultat.releves_non_ecrits += len(releves)
        return ecrits
    for releve in releves:
        try:
            ack = depenses_marketing.enregistrer_releve(releve)
        except ValueError:
            resultat.releves_non_ecrits += 1
            continue
        if not ack["deja_present"]:
            resultat.releves_ecrits += 1
            ecrits.append(releve)
    return ecrits


def _annoncer_depenses(releves: list[dict[str, Any]]) -> None:
    for r in releves:
        if r["campagne_ref"] is not None:
            continue  # seuls les totaux de canal voyagent : aucun libellé de campagne au bus
        evenements.publier(
            TYPE_DEPENSES,
            PRODUCTEUR,
            {
                "releve_id": r["releve_id"],
                "revision": r["revision"],
                "canal": r["canal"],
                "periode_debut": r["periode_debut"],
                "periode_fin": r["periode_fin"],
                "montant_cad": r["montant_cad"],
                "devise": "CAD",
                "base_taxes": r["base_taxes"],
                "source": r["source"],
                "releve_le": r["releve_le"],
            },
            evenement_id=f"m7-depense-{r['releve_id']}-r{r['revision']}",
        )


def tour_flux(
    connecteur: ConnecteurLecture,
    flux: str,
    *,
    maintenant: Callable[[], datetime],
    arret: Callable[[], bool] | None = None,
    pages_max: int = PAGES_MAX_PAR_TOUR,
) -> ResultatFlux:
    """Un tour pour UN flux d'un compte. Voir le module."""
    compte, source = connecteur.compte, connecteur.SOURCE
    cle = curseurs.cle_etat(source, compte.compte_ref, flux)
    etats = curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))
    etat = etats.get(cle) or curseurs.EtatIngestion(cle, source, compte.compte_ref, flux)
    # le compte de requêtes du jour est celui du COMPTE (tous les flux) : le plus élevé gagne
    for autre in etats.values():
        if autre.source == source and autre.compte_ref == compte.compte_ref:
            connecteur.limiteur.restaurer(autre.jour_quota, autre.appels_jour)
    resultat = ResultatFlux(flux, "rien_de_nouveau")
    if etat.fenetre and not etat.termine:
        fenetre, curseur = _fenetre_depuis(etat.fenetre), etat.curseur
    else:
        watermark = date.fromisoformat(etat.watermark) if etat.watermark else None
        fenetre, curseur = connecteur.fenetre_suivante(watermark, maintenant().astimezone(UTC).date()), None
        if fenetre is None:
            return resultat
    resultat.fenetre = fenetre.cle()
    fraicheur_h = modele.SOURCES[source].fraicheur_h
    pages = 0
    while True:
        if arret is not None and arret():
            resultat.statut = "interrompu"
            resultat.erreur = {"code": "REJ-SIGNAUX-ARRET-DEMANDE", "reprenable": True}
            return resultat
        if pages >= pages_max:
            resultat.statut = "interrompu"
            resultat.erreur = {
                "code": "REJ-SIGNAUX-QUOTA-LOCAL",
                "reprenable": True,
                "detail": "nombre de pages du tour atteint : reprise au curseur",
            }
            return resultat
        try:
            page = connecteur.lire_page(flux, fenetre, curseur)
            jour_quota, appels = connecteur.limiteur.compte_du_jour
            instant = _horodatage(maintenant())
            with stockage.transaction():
                bilan = registre.enregistrer(stockage.maillons(*registre.REGISTRE), page.faits, instant)
                releves = _ecrire_releves(connecteur, [dict(f) for f in page.faits], resultat)
                nouvel = dataclasses.replace(
                    etat,
                    fenetre=fenetre.cle(),
                    curseur=page.curseur_suivant,
                    termine=page.termine,
                    jour_quota=jour_quota,
                    appels_jour=appels,
                    dernier_echec=None,
                )
                if page.termine:
                    nouvel = dataclasses.replace(
                        nouvel,
                        watermark=fenetre.fin.isoformat(),
                        derniere_lecture_reussie_le=instant,
                        donnees_jusqu_au=page.donnees_jusqu_au or fenetre.fin.isoformat(),
                    )
                curseurs.ecrire_etat(stockage.maillons(*registre.REGISTRE_CURSEURS), nouvel, instant)
                _annoncer_depenses(releves)
                resultat.faits_nouveaux += bilan["nouveaux"]
                resultat.faits_revises += bilan["revisions"]
                resultat.faits_inchanges += bilan["inchanges"]
                if page.termine:
                    evenements.publier(
                        TYPE_SIGNAUX,
                        PRODUCTEUR,
                        {
                            "source": source,
                            "compte_ref": compte.compte_ref,
                            "flux": flux,
                            "mode": "api_lecture",
                            "periode_debut": fenetre.debut.isoformat(),
                            "periode_fin": fenetre.fin.isoformat(),
                            "faits_nouveaux": resultat.faits_nouveaux,
                            "faits_revises": resultat.faits_revises,
                            "faits_inchanges": resultat.faits_inchanges,
                            "derniere_lecture_reussie_le": instant,
                            "donnees_jusqu_au": nouvel.donnees_jusqu_au,
                            "fraicheur_fenetre_h": fraicheur_h,
                            "fictif": compte.fictif,
                        },
                        evenement_id=f"m7-signaux-{source}-{compte.compte_ref}-{flux}-{fenetre.cle()}-"
                        f"{page.empreinte_reponse[:16]}-{instant}",
                    )
        except ErreurSignaux as erreur:
            _noter_echec(connecteur, etat, fenetre, curseur, erreur, maintenant)
            resultat.statut, resultat.erreur = "echec", erreur.publique()
            return resultat
        pages += 1
        resultat.pages, resultat.ignores = pages, resultat.ignores + page.ignores
        etat, curseur = nouvel, page.curseur_suivant
        if page.termine:
            resultat.statut = "termine"
            return resultat


def _noter_echec(
    connecteur: ConnecteurLecture,
    etat: curseurs.EtatIngestion,
    fenetre: modele.Fenetre,
    curseur: str | None,
    erreur: ErreurSignaux,
    maintenant: Callable[[], datetime],
) -> None:
    """Inscrit l'échec typé à l'état du flux : le curseur reste, rien n'avance."""
    jour_quota, appels = connecteur.limiteur.compte_du_jour
    instant = _horodatage(maintenant())
    nouvel = dataclasses.replace(
        etat,
        fenetre=fenetre.cle(),
        curseur=curseur,
        termine=False,
        jour_quota=jour_quota,
        appels_jour=appels,
        dernier_echec=(("code", erreur.code), ("le", instant)),
    )
    with stockage.transaction():
        curseurs.ecrire_etat(stockage.maillons(*registre.REGISTRE_CURSEURS), nouvel, instant)


def tour_ingestion(
    connecteur: ConnecteurLecture,
    *,
    maintenant: Callable[[], datetime],
    arret: Callable[[], bool] | None = None,
    pages_max: int = PAGES_MAX_PAR_TOUR,
) -> dict[str, Any]:
    """Un tour pour tous les flux du compte. Rend un bilan par flux ; un flux en échec n'empêche pas les autres, SAUF un
    refus d'authentification ou de permission (le jeton est le même pour tous les flux : on s'arrête)."""
    bilans = []
    for flux in connecteur.FLUX:
        bilan = tour_flux(connecteur, flux, maintenant=maintenant, arret=arret, pages_max=pages_max)
        bilans.append(bilan.publique())
        code = (bilan.erreur or {}).get("code")
        if bilan.statut == "interrompu" and code == "REJ-SIGNAUX-ARRET-DEMANDE":
            break
        if code in (
            "REJ-SIGNAUX-AUTH-REFUSEE",
            "REJ-SIGNAUX-PERMISSION-REFUSEE",
            "REJ-SIGNAUX-TRANSPORT-NON-BRANCHE",
            "REJ-SIGNAUX-COFFRE-INDISPONIBLE",
        ):
            break
    return {"source": connecteur.SOURCE, "compte_ref": connecteur.compte.compte_ref, "flux": bilans}


__all__ = ["PRODUCTEUR", "ResultatFlux", "TYPE_DEPENSES", "TYPE_SIGNAUX", "tour_flux", "tour_ingestion"]
