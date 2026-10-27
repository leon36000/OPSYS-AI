"""Pages indépendantes de cédule, attachées à une tête de registre stable."""
import re
from datetime import datetime, timedelta

from . import annotations_calendrier as sources
from . import apercu_mois
from . import calendrier_civil as calendrier
from .registre import VerificationError

MAX_SOURCES = 10000
TAILLE_PAGE = 25
BORNE_SORTIE = 65536
Refus = sources.Refus


def refuser(suffixe):
    return {"accepte": False, "verdict": {"code": "REJ-PAGE-CEDULE-" + suffixe}}


def _arguments(debut_semaine, offset_interventions, offset_sans_date, source_attendue):
    if (type(debut_semaine) is not str
            or any(type(o) is not int or not 0 <= o <= 10000 or o % TAILLE_PAGE
                   for o in (offset_interventions, offset_sans_date))
            or (source_attendue is not None and (type(source_attendue) is not str
                or re.fullmatch(r"[0-9a-f]{64}", source_attendue) is None))
            or ((offset_interventions or offset_sans_date) and source_attendue is None)):
        raise Refus("ARGUMENTS")
    try:
        jour = calendrier._date(debut_semaine)
        if jour.weekday() != 0:
            raise ValueError("lundi requis")
        return (calendrier.instant_local(jour.isoformat(), 0),
                calendrier.instant_local((jour + timedelta(days=7)).isoformat(), 0))
    except (TypeError, ValueError, OverflowError):
        raise Refus("ARGUMENTS") from None


def lire(reg, debut_semaine, offset_interventions=0, offset_sans_date=0, source_attendue=None,
         limite_sortie=BORNE_SORTIE):
    debut, fin = _arguments(debut_semaine, offset_interventions, offset_sans_date, source_attendue)
    try:
        if reg.taille() > MAX_SOURCES:
            raise Refus("SOURCES-TROP-VOLUMINEUSES")
        maillons, lignes, sans_date, index_sources = apercu_mois._instantane(reg)
        tete = maillons[-1]["ligne_id"] if maillons else None
        if source_attendue is not None and source_attendue != tete:
            raise Refus("SOURCE-MODIFIEE")
        lignes = sorted((ligne for ligne in lignes if datetime.fromisoformat(ligne["debut"]) < fin
                         and datetime.fromisoformat(ligne["fin"]) > debut),
                        key=lambda ligne: (ligne["debut"], ligne["equipe_id"], ligne["intervention_id"]))
        sans_date = sorted(sans_date, key=lambda ligne: ligne["intervention_id"])
        for offset, total in ((offset_interventions, len(lignes)), (offset_sans_date, len(sans_date))):
            if offset and offset >= total:
                raise Refus("ARGUMENTS")
        page = lignes[offset_interventions:offset_interventions + TAILLE_PAGE]
        non_datees = sans_date[offset_sans_date:offset_sans_date + TAILLE_PAGE]
        for ligne in page:
            ancre = {k: ligne[k] for k in sources._CLES_ANCRE}
            creneau = sources._creneau(index_sources, ancre)
            if (ligne["debut"] != creneau["debut"] or ligne["fin"] != creneau["fin"]
                    or ligne["equipe_id"] != creneau["equipe_id"]
                    or type(ligne["revision"]) is not int or ligne["revision"] != creneau["revision_calendrier"]):
                raise Refus("SOURCE-INVALIDE")
        reponse = {"accepte": True, "resultat": {
            "debut_semaine": debut_semaine, "fuseau": calendrier.FUSEAU,
            "interventions": page, "total_interventions": len(lignes),
            "sans_date": non_datees, "total_sans_date": len(sans_date),
            "tronque": len(lignes) > len(page) or len(sans_date) > len(non_datees),
            "avertissements": list(calendrier.AVERTISSEMENTS),
            "source_tete": tete, "source_nombre": len(maillons), "taille_page": TAILLE_PAGE,
            "offset_interventions": offset_interventions, "offset_sans_date": offset_sans_date}}
        sources.verifier_borne(reponse, limite_sortie)
        return reponse
    except (VerificationError, KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise Refus("SOURCE-INVALIDE") from None
