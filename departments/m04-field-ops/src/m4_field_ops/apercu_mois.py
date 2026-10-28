"""Trois mois civils, agrégés depuis un seul instantané M4, sans effet de bord."""
import re
from calendar import monthrange
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import annotations_calendrier as sources
from . import calendrier_civil as calendrier
from . import etats
from .registre import Registre, VerificationError

MAX_SOURCES = 10000
BORNE_SORTIE = 131072
Refus = sources.Refus


def refuser(suffixe):
    return {"accepte": False, "verdict": {"code": "REJ-APERCU-MOIS-" + suffixe}}


def valider_mois(premier_mois):
    if type(premier_mois) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}", premier_mois) is None:
        raise Refus("ARGUMENTS")
    try:
        jour = date.fromisoformat(premier_mois + "-01")
    except ValueError:
        raise Refus("ARGUMENTS") from None
    if not date(1900, 1, 1) <= jour <= date(2199, 10, 1):
        raise Refus("ARGUMENTS")
    return jour


def _compteurs(**identifiant):
    return {**identifiant, "total": 0, "date_confirmee": 0, "a_reconfirmer": 0}


def _instantane(principal):
    nombre = principal.taille()
    if type(nombre) is not int or nombre < 0 or nombre > MAX_SOURCES:
        raise Refus("SOURCES-TROP-VOLUMINEUSES")
    principal.assert_chaine()
    maillons = principal.lire()
    if type(maillons) is not list or len(maillons) != nombre:
        raise Refus("SOURCE-INVALIDE")
    ids = [m["ligne_id"] for m in maillons]
    inscriptions = [m["intervention_id"] for m in maillons if m["type_entree"] == etats.TYPE_INSCRIPTION]
    if len(set(ids)) != len(ids) or len(set(inscriptions)) != len(inscriptions):
        raise Refus("SOURCE-INVALIDE")
    index = calendrier._index(Registre(maillons))
    lignes, sans_date = calendrier._projection(index)
    ancres, interventions, courantes = set(), set(), {}
    for ligne in lignes:
        ancre = {k: ligne[k] for k in sources._CLES_ANCRE}
        sources._ancre(ancre)
        cle, iid = sources._cle(ancre), ancre["intervention_id"]
        if (cle in ancres or iid in interventions or ligne["validite"] not in {"date_confirmee", "a_reconfirmer"}
                or ligne["statut"] not in etats.ETATS):
            raise Refus("SOURCE-INVALIDE")
        ancres.add(cle)
        interventions.add(iid)
        courantes[cle] = ligne
    for ligne in sans_date:
        iid = ligne["intervention_id"]
        if iid in interventions or not sources._texte(iid) or ligne["statut"] not in etats.ETATS:
            raise Refus("SOURCE-INVALIDE")
        interventions.add(iid)
    # Une intervention active ne doit pas disparaître entre l'état et les visites de son plan.
    if any(iid not in interventions and info["statut"] not in etats.ETATS_TERMINAUX
           for iid, info in index[5].items()):
        raise Refus("SOURCE-INVALIDE")
    par_id = {m["ligne_id"]: (rang, m) for rang, m in enumerate(maillons)}
    return maillons, lignes, sans_date, (par_id, courantes)


def lire(principal, premier_mois, limite_sortie=BORNE_SORTIE):
    premier = valider_mois(premier_mois)
    try:
        maillons, lignes, sans_date, index_sources = _instantane(principal)
        mois, par_jour, par_mois = [], {}, {}
        for decalage in range(3):
            absolu = premier.year * 12 + premier.month - 1 + decalage
            annee, index_mois = divmod(absolu, 12)
            numero_mois = index_mois + 1
            cle_mois = f"{annee:04d}-{numero_mois:02d}"
            compte = _compteurs(mois=cle_mois)
            compte["jours"] = []
            for numero_jour in range(1, monthrange(annee, numero_mois)[1] + 1):
                jour = _compteurs(jour=date(annee, numero_mois, numero_jour).isoformat())
                compte["jours"].append(jour)
                par_jour[jour["jour"]] = jour
            mois.append(compte)
            par_mois[cle_mois] = compte
        for ligne in lignes:
            debut = datetime.fromisoformat(ligne["debut"])
            if debut.utcoffset() is None:
                raise Refus("SOURCE-INVALIDE")
            jour = debut.astimezone(ZoneInfo(calendrier.FUSEAU)).date().isoformat()
            if jour not in par_jour:
                continue
            ancre = {k: ligne[k] for k in sources._CLES_ANCRE}
            creneau = sources._creneau(index_sources, ancre)
            if (ligne["debut"] != creneau["debut"] or ligne["fin"] != creneau["fin"]
                    or ligne["equipe_id"] != creneau["equipe_id"]
                    or type(ligne["revision"]) is not int or ligne["revision"] != creneau["revision_calendrier"]):
                raise Refus("SOURCE-INVALIDE")
            for compte in (par_jour[jour], par_mois[jour[:7]]):
                compte["total"] += 1
                compte[ligne["validite"]] += 1
        reponse = {"accepte": True, "resultat": {
            "premier_mois": premier_mois, "fuseau": calendrier.FUSEAU, "mois": mois,
            "total_interventions": sum(m["total"] for m in mois), "total_sans_date": len(sans_date),
            "source_tete": maillons[-1]["ligne_id"] if maillons else None, "source_nombre": len(maillons),
            "avertissements": [*calendrier.AVERTISSEMENTS,
                "Un jour vide ne prouve aucune disponibilité. Les interventions sans date concernent tout le carnet."]}}
        sources.verifier_borne(reponse, limite_sortie)
        return reponse
    except (VerificationError, KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise Refus("SOURCE-INVALIDE") from None
