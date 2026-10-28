"""Annotations admin de créneaux M4 : registre séparé, sources immuables, aucune horloge."""
import json
import re
import unicodedata
from copy import deepcopy
from datetime import datetime

from . import calendrier_civil as calendrier
from . import cedule_tournees, encodage, etats
from .registre import VerificationError

REGISTRE = "annotations_calendrier"
TYPE = "annotation_calendrier"
MAX_SOURCES = 10000
MAX_TEXTE = 2000
BORNE_SORTIE = 131072
_CLES_ANCRE = {"intervention_id", "plan_id", "source_application_id", "source_ligne_id"}
_HEX = re.compile(r"[0-9a-f]{64}")


class Refus(Exception):
    def __init__(self, suffixe):
        self.suffixe = suffixe
        super().__init__(suffixe)


def refuser(suffixe):
    return {"accepte": False, "verdict": {"code": "REJ-ANNOTATION-CALENDRIER-" + suffixe}}


def _texte(valeur, maximum=256, multiligne=False):
    return (type(valeur) is str and bool(valeur.strip()) and len(valeur) <= maximum
            and not any(unicodedata.category(c) in {"Cc", "Cs"}
                        and not (multiligne and c in "\r\n\t") for c in valeur))


def _entier(valeur, maximum=MAX_SOURCES):
    return type(valeur) is int and 0 <= valeur <= maximum


def _ancre(ancre):
    if type(ancre) is not dict or set(ancre) != _CLES_ANCRE or not _texte(ancre["intervention_id"]):
        raise Refus("ANCRE-INVALIDE")
    if any(type(ancre[k]) is not str or _HEX.fullmatch(ancre[k]) is None
           for k in _CLES_ANCRE - {"intervention_id"}):
        raise Refus("ANCRE-INVALIDE")


def _auteur(auteur):
    if (type(auteur) is not dict or set(auteur) != {"personne", "role"}
            or not _texte(auteur["personne"]) or type(auteur["role"]) is not str or auteur["role"] != "admin"):
        raise Refus("AUTEUR-INVALIDE")


def _instant(horodatage):
    try:
        if not _texte(horodatage, 64) or datetime.fromisoformat(horodatage).utcoffset() is None:
            raise ValueError("instant sans fuseau")
    except (ValueError, TypeError):
        raise Refus("HORODATAGE-INVALIDE") from None


def _arguments(ancre, texte_libre, revision_attendue):
    _ancre(ancre)
    if not _texte(texte_libre, MAX_TEXTE, multiligne=True) or not _entier(revision_attendue):
        raise Refus("ARGUMENTS")
    return {"ancre": deepcopy(ancre), "texte_libre": texte_libre, "revision_attendue": revision_attendue}


def _mutation(mutation, arguments):
    if (type(mutation) is not dict or set(mutation) != {"appareil", "cle", "empreinte_arguments"}
            or not _texte(mutation["appareil"]) or not _texte(mutation["cle"], 200)
            or type(mutation["empreinte_arguments"]) is not str
            or mutation["empreinte_arguments"] != encodage.empreinte(arguments)):
        raise Refus("MUTATION-INVALIDE")


def verifier_borne(reponse, limite_sortie):
    if type(limite_sortie) is not int or limite_sortie <= 0:
        raise Refus("SORTIE-TROP-VOLUMINEUSE")
    if any(len(json.dumps({"ok": True, "resultat": reponse, "rejoue": rejoue}, ensure_ascii=False))
           > limite_sortie for rejoue in (False, True)):
        raise Refus("SORTIE-TROP-VOLUMINEUSE")


def _cle(ancre):
    return tuple(ancre[k] for k in sorted(_CLES_ANCRE))


def _sources(principal):
    try:
        if principal.taille() > MAX_SOURCES:
            raise Refus("SOURCES-TROP-VOLUMINEUSES")
        index = calendrier._index(principal)
        maillons = index[0]
        par_id = {m["ligne_id"]: (rang, m) for rang, m in enumerate(maillons)}
        if len(par_id) != len(maillons):
            raise Refus("SOURCE-INVALIDE")
        courantes = {_cle({k: ligne[k] for k in _CLES_ANCRE}): ligne
                     for ligne in calendrier._projection(index)[0]}
        return par_id, courantes
    except (VerificationError, KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise Refus("SOURCE-INVALIDE") from None


def _creneau(sources, ancre):
    """Résout aussi une ancienne confirmation sans lui substituer le calendrier courant."""
    _ancre(ancre)
    par_id, _ = sources
    try:
        rang_date, datee = par_id[ancre["source_ligne_id"]]
        rang_app, application = par_id[ancre["source_application_id"]]
        if (datee["type_entree"] != calendrier.TYPE_DATEE
                or application["type_entree"] != cedule_tournees.TYPE_APPLIQUEE
                or datee["plan_id"] != ancre["plan_id"] or application["plan_id"] != ancre["plan_id"]
                or datee["source_application_id"] != ancre["source_application_id"] or rang_app >= rang_date
                or not _entier(datee["revision"]) or datee["revision"] == 0):
            raise Refus("SOURCE-INVALIDE")
        propositions = [(rang, m) for rang, m in par_id.values()
                        if m["type_entree"] == cedule_tournees.TYPE_PROPOSEE and m["plan_id"] == ancre["plan_id"]]
        if len(propositions) != 1 or propositions[0][0] >= rang_app:
            raise Refus("SOURCE-INVALIDE")
        proposition = propositions[0][1]
        cedule_tournees.verifier_empreintes_plan_applique(proposition, application)
        applications = [m for _, m in par_id.values()
                        if m["type_entree"] == cedule_tournees.TYPE_APPLIQUEE and m["plan_id"] == ancre["plan_id"]]
        if len(applications) != 1:
            raise Refus("SOURCE-INVALIDE")
        dates = [m for rang, m in par_id.values() if rang <= rang_date
                 and m["type_entree"] == calendrier.TYPE_DATEE and m["plan_id"] == ancre["plan_id"]]
        if any(type(m["revision"]) is not int or m["revision"] != i + 1
               or m["source_application_id"] != ancre["source_application_id"]
               for i, m in enumerate(dates)):
            raise Refus("SOURCE-INVALIDE")
        toutes_visites = list(calendrier._visites(proposition))
        jours = sorted({r["jour"] for r, _ in toutes_visites})
        civil = datee["calendrier"]
        if (type(civil) is not dict or set(civil) != {str(j) for j in jours}
                or datee["fuseau"] != calendrier.FUSEAU):
            raise Refus("SOURCE-INVALIDE")
        valeurs = [calendrier._date(civil[str(j)]).isoformat() for j in jours]
        if valeurs != sorted(set(valeurs)):
            raise Refus("SOURCE-INVALIDE")
        visites = [(r, v) for r, v in toutes_visites if v["chantier"] == ancre["intervention_id"]]
        assignations = [a for a in application["assignations"] if a["intervention_id"] == ancre["intervention_id"]]
        if len(visites) != 1 or len(assignations) != 1:
            raise Refus("SOURCE-INVALIDE")
        route, visite = visites[0]
        if (assignations[0]["technicien_id"] != route["equipe"] or not _texte(route["equipe"])
                or type(route["jour"]) is not int or route["jour"] < 0
                or any(type(visite[k]) is not int for k in ("debut_min", "fin_min"))
                or not 0 <= visite["debut_min"] < visite["fin_min"] <= 1440):
            raise Refus("SOURCE-INVALIDE")
        avant_date = [m for rang, m in par_id.values() if rang < rang_date]
        etat = {i["intervention_id"]: i for i in
                etats.lister_interventions(cedule_tournees._Instantane(avant_date))}
        info = etat.get(ancre["intervention_id"])
        detentrices = [m for m in avant_date if m["type_entree"] == cedule_tournees.TYPE_APPLIQUEE
                       and any(a["intervention_id"] == ancre["intervention_id"] for a in m["assignations"])]
        if (not info or info["statut"] != "planifiee" or info["technicien_assigne"] != route["equipe"]
                or not detentrices or detentrices[-1]["ligne_id"] != application["ligne_id"]):
            raise Refus("SOURCE-INVALIDE")
        debut, fin = calendrier._creneau(route, visite, datee["calendrier"])
        return {"equipe_id": route["equipe"], "jour": route["jour"], "debut_min": visite["debut_min"],
                "fin_min": visite["fin_min"], "debut": debut, "fin": fin,
                "revision_calendrier": datee["revision"], "source_proposition_id": proposition["ligne_id"]}
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise Refus("SOURCE-INVALIDE") from None


def _charger(principal, notes):
    if principal is notes:
        raise Refus("REGISTRE-INVALIDE")
    sources = _sources(principal)
    try:
        if notes.taille() > MAX_SOURCES:
            raise Refus("SOURCES-TROP-VOLUMINEUSES")
        maillons = notes.lire()
        if len(maillons) > MAX_SOURCES:
            raise Refus("SOURCES-TROP-VOLUMINEUSES")
        notes.assert_chaine()
        precedentes, mutations, creneaux = {}, set(), {}
        cles = {"type_entree", "ancre", "texte_libre", "revision", "revision_precedente", "auteur",
                "horodatage", "mutation", "creneau", "ligne_id", "precedent_ligne_id"}
        for m in maillons:
            if type(m) is not dict or set(m) != cles or m["type_entree"] != TYPE or not _entier(m["revision"]):
                raise Refus("REGISTRE-INVALIDE")
            arguments = _arguments(m["ancre"], m["texte_libre"], m["revision"] - 1)
            _auteur(m["auteur"])
            _instant(m["horodatage"])
            _mutation(m["mutation"], arguments)
            iid = m["ancre"]["intervention_id"]
            precedente = precedentes.get(iid)
            if (m["revision"] != (precedente["revision"] + 1 if precedente else 1)
                    or m["revision_precedente"] != (precedente["ligne_id"] if precedente else None)):
                raise Refus("REGISTRE-INVALIDE")
            cle = _cle(m["ancre"])
            if cle not in creneaux:
                creneaux[cle] = _creneau(sources, m["ancre"])
            if encodage.empreinte(m["creneau"]) != encodage.empreinte(creneaux[cle]):
                raise Refus("REGISTRE-INVALIDE")
            intention = (m["mutation"]["appareil"], m["mutation"]["cle"])
            if intention in mutations:
                raise Refus("REGISTRE-INVALIDE")
            mutations.add(intention)
            precedentes[iid] = m
        return sources, maillons, precedentes
    except (VerificationError, KeyError, TypeError, ValueError):
        raise Refus("REGISTRE-INVALIDE") from None


def _accuse(m, rejoue=False):
    return {"accepte": True, "resultat": {
        "annotation_id": m["ligne_id"], "intervention_id": m["ancre"]["intervention_id"],
        "revision": m["revision"], "ancre": deepcopy(m["ancre"]), "horodatage": m["horodatage"]},
        "rejoue": rejoue}


def _retrouver(maillons, auteur, mutation):
    for m in maillons:
        if (m["mutation"]["appareil"], m["mutation"]["cle"]) == (mutation["appareil"], mutation["cle"]):
            if m["mutation"] != mutation or m["auteur"] != auteur:
                raise Refus("MUTATION-CONFLIT")
            return m
    return None


def retrouver_rejeu(principal, notes, arguments, auteur, mutation, limite_sortie=BORNE_SORTIE):
    if type(arguments) is not dict or set(arguments) != {"ancre", "texte_libre", "revision_attendue"}:
        raise Refus("ARGUMENTS")
    arguments = _arguments(**arguments)
    _auteur(auteur)
    _mutation(mutation, arguments)
    _, maillons, _ = _charger(principal, notes)
    m = _retrouver(maillons, auteur, mutation)
    if m is None:
        return None
    reponse = _accuse(m, rejoue=True)
    verifier_borne(reponse, limite_sortie)
    return reponse


def enregistrer(principal, notes, ancre, texte_libre, revision_attendue, auteur, mutation, horodatage,
                limite_sortie=BORNE_SORTIE):
    arguments = _arguments(ancre, texte_libre, revision_attendue)
    _auteur(auteur)
    _mutation(mutation, arguments)
    _instant(horodatage)
    sources, maillons, precedentes = _charger(principal, notes)
    ancien = _retrouver(maillons, auteur, mutation)
    if ancien is not None:
        reponse = _accuse(ancien, rejoue=True)
        verifier_borne(reponse, limite_sortie)
        return reponse
    creneau = _creneau(sources, ancre)
    if _cle(ancre) not in sources[1]:
        raise Refus("SOURCE-REMPLACEE")
    precedente = precedentes.get(ancre["intervention_id"])
    if revision_attendue != (precedente["revision"] if precedente else 0):
        raise Refus("REVISION-PERIMEE")
    if len(maillons) >= MAX_SOURCES:
        raise Refus("SOURCES-TROP-VOLUMINEUSES")
    m = {"type_entree": TYPE, **arguments, "revision": revision_attendue + 1,
         "revision_precedente": precedente["ligne_id"] if precedente else None,
         "auteur": deepcopy(auteur), "mutation": deepcopy(mutation), "horodatage": horodatage,
         "creneau": creneau}
    del m["revision_attendue"]
    preview = {**m, "ligne_id": encodage.empreinte(m, notes.tete())}
    reponse = _accuse(preview)
    verifier_borne(reponse, limite_sortie)
    notes.ajouter(m)
    return reponse


def lire(principal, notes, intervention_id, limite=20, decalage=0, revision_max=None, limite_sortie=BORNE_SORTIE):
    if (not _texte(intervention_id) or not _entier(limite, 20) or limite == 0 or not _entier(decalage)
            or (revision_max is not None and not _entier(revision_max))):
        raise Refus("ARGUMENTS")
    sources, maillons, precedentes = _charger(principal, notes)
    if not any(m.get("intervention_id") == intervention_id and m["type_entree"] == "intervention_inscrite"
               for _, m in sources[0].values()):
        raise Refus("INTERVENTION-INCONNUE")
    courante = precedentes[intervention_id]["revision"] if intervention_id in precedentes else 0
    plafond = courante if revision_max is None else revision_max
    if plafond > courante:
        raise Refus("REVISION-PERIMEE")
    selection = [m for m in maillons if m["ancre"]["intervention_id"] == intervention_id and m["revision"] <= plafond]
    lignes = []
    for m in selection[decalage:decalage + limite]:
        courant = sources[1].get(_cle(m["ancre"]))
        lignes.append({"annotation_id": m["ligne_id"], "revision": m["revision"], "ancre": deepcopy(m["ancre"]),
                       "creneau": deepcopy(m["creneau"]), "texte_libre": m["texte_libre"],
                       "auteur": deepcopy(m["auteur"]), "horodatage": m["horodatage"],
                       "source_courante": courant is not None,
                       "validite": courant["validite"] if courant else "historique"})
    suivant = decalage + len(lignes)
    reponse = {"accepte": True, "resultat": {"intervention_id": intervention_id, "revision_max": plafond,
        "revision_courante": courante, "total": len(selection), "decalage": decalage,
        "suivant": suivant if suivant < len(selection) else None, "annotations": lignes}}
    verifier_borne(reponse, limite_sortie)
    return reponse


def resumer(principal, notes, ancres, limite_sortie=BORNE_SORTIE):
    if type(ancres) is not list or len(ancres) > 200:
        raise Refus("ARGUMENTS")
    for ancre in ancres:
        _ancre(ancre)
    if len({_cle(a) for a in ancres}) != len(ancres):
        raise Refus("ARGUMENTS")
    sources, maillons, precedentes = _charger(principal, notes)
    badges = []
    for ancre in ancres:
        creneau = _creneau(sources, ancre)
        courant = sources[1].get(_cle(ancre))
        iid = ancre["intervention_id"]
        propres = [m for m in maillons if m["ancre"]["intervention_id"] == iid]
        nombre = sum(m["ancre"] == ancre for m in propres)
        badges.append({"ancre": deepcopy(ancre), "total_ancre": nombre, "total_historique": len(propres) - nombre,
                       "revision_max": precedentes[iid]["revision"] if iid in precedentes else 0,
                       "revision_courante": precedentes[iid]["revision"] if iid in precedentes else 0,
                       "source_courante": courant is not None, "creneau": creneau,
                       "validite": courant["validite"] if courant else "historique"})
    reponse = {"accepte": True, "resultat": {"annotations": badges}}
    verifier_borne(reponse, limite_sortie)
    return reponse
