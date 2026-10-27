"""Repères visuels admin, dans une collection distincte du planning et des notes M4."""
from copy import deepcopy

from . import annotations_calendrier as sources
from . import encodage
from .registre import VerificationError

REGISTRE = "couleurs_calendrier"
TYPE = "couleur_calendrier"
MAX_SOURCES = 10000
BORNE_SORTIE = 131072
PALETTE = {"aucune": "Sans repère", "bleu": "Bleu", "violet": "Violet", "vert": "Vert",
           "rose": "Rose", "ambre": "Ambre", "gris": "Gris"}
Refus = sources.Refus
verifier_borne = sources.verifier_borne


def refuser(suffixe):
    return {"accepte": False, "verdict": {"code": "REJ-COULEUR-CALENDRIER-" + suffixe}}


def _arguments(ancre, couleur, revision_attendue):
    sources._ancre(ancre)
    if type(couleur) is not str or couleur not in PALETTE or not sources._entier(revision_attendue):
        raise Refus("ARGUMENTS")
    return {"ancre": deepcopy(ancre), "couleur": couleur, "revision_attendue": revision_attendue}


def _charger(principal, couleurs):
    if principal is couleurs:
        raise Refus("REGISTRE-INVALIDE")
    if principal.taille() > MAX_SOURCES or couleurs.taille() > MAX_SOURCES:
        raise Refus("SOURCES-TROP-VOLUMINEUSES")
    index = sources._sources(principal)
    try:
        maillons = couleurs.lire()
        if len(maillons) > MAX_SOURCES:
            raise Refus("SOURCES-TROP-VOLUMINEUSES")
        couleurs.assert_chaine()
        precedentes, mutations, creneaux = {}, set(), {}
        cles = {"type_entree", "ancre", "couleur", "revision", "revision_precedente", "auteur",
                "horodatage", "mutation", "creneau", "ligne_id", "precedent_ligne_id"}
        for m in maillons:
            if type(m) is not dict or set(m) != cles or m["type_entree"] != TYPE or not sources._entier(m["revision"]):
                raise Refus("REGISTRE-INVALIDE")
            arguments = _arguments(m["ancre"], m["couleur"], m["revision"] - 1)
            sources._auteur(m["auteur"])
            sources._instant(m["horodatage"])
            sources._mutation(m["mutation"], arguments)
            precedente = precedentes.get(m["ancre"]["intervention_id"])
            if (m["revision"] != (precedente["revision"] + 1 if precedente else 1)
                    or m["revision_precedente"] != (precedente["ligne_id"] if precedente else None)):
                raise Refus("REGISTRE-INVALIDE")
            cle = sources._cle(m["ancre"])
            if cle not in creneaux:
                creneaux[cle] = sources._creneau(index, m["ancre"])
            if encodage.empreinte(m["creneau"]) != encodage.empreinte(creneaux[cle]):
                raise Refus("REGISTRE-INVALIDE")
            intention = (m["mutation"]["appareil"], m["mutation"]["cle"])
            if intention in mutations:
                raise Refus("REGISTRE-INVALIDE")
            mutations.add(intention)
            precedentes[m["ancre"]["intervention_id"]] = m
        return index, maillons, precedentes
    except (VerificationError, KeyError, TypeError, ValueError):
        raise Refus("REGISTRE-INVALIDE") from None


def _accuse(m, rejoue=False):
    return {"accepte": True, "resultat": {
        "couleur_id": m["ligne_id"], "intervention_id": m["ancre"]["intervention_id"],
        "revision": m["revision"], "ancre": deepcopy(m["ancre"]), "horodatage": m["horodatage"]},
        "rejoue": rejoue}


def enregistrer(principal, couleurs, ancre, couleur, revision_attendue, auteur, mutation, horodatage,
                limite_sortie=BORNE_SORTIE):
    arguments = _arguments(ancre, couleur, revision_attendue)
    sources._auteur(auteur)
    sources._mutation(mutation, arguments)
    sources._instant(horodatage)
    index, maillons, precedentes = _charger(principal, couleurs)
    ancien = sources._retrouver(maillons, auteur, mutation)
    if ancien is not None:
        reponse = _accuse(ancien, rejoue=True)
        verifier_borne(reponse, limite_sortie)
        return reponse
    creneau = sources._creneau(index, ancre)
    if sources._cle(ancre) not in index[1]:
        raise Refus("SOURCE-REMPLACEE")
    precedente = precedentes.get(ancre["intervention_id"])
    if revision_attendue != (precedente["revision"] if precedente else 0):
        raise Refus("REVISION-PERIMEE")
    if len(maillons) >= MAX_SOURCES:
        raise Refus("SOURCES-TROP-VOLUMINEUSES")
    m = {"type_entree": TYPE, "ancre": deepcopy(ancre), "couleur": couleur,
         "revision": revision_attendue + 1, "revision_precedente": precedente["ligne_id"] if precedente else None,
         "auteur": deepcopy(auteur), "mutation": deepcopy(mutation), "horodatage": horodatage, "creneau": creneau}
    preview = {**m, "ligne_id": encodage.empreinte(m, couleurs.tete())}
    reponse = _accuse(preview)
    verifier_borne(reponse, limite_sortie)
    couleurs.ajouter(m)
    return reponse


def resumer(principal, couleurs, ancres, limite_sortie=BORNE_SORTIE):
    if type(ancres) is not list or len(ancres) > 200:
        raise Refus("ARGUMENTS")
    for ancre in ancres:
        sources._ancre(ancre)
    if len({sources._cle(a) for a in ancres}) != len(ancres):
        raise Refus("ARGUMENTS")
    index, maillons, precedentes = _charger(principal, couleurs)
    dernieres = {sources._cle(m["ancre"]): m for m in maillons}
    lignes = []
    for ancre in ancres:
        creneau = sources._creneau(index, ancre)
        cle = sources._cle(ancre)
        courant, derniere = index[1].get(cle), dernieres.get(cle)
        precedente = precedentes.get(ancre["intervention_id"])
        lignes.append({"ancre": deepcopy(ancre), "couleur": derniere["couleur"] if derniere else "aucune",
                       "revision_courante": precedente["revision"] if precedente else 0,
                       "source_courante": courant is not None, "creneau": creneau,
                       "validite": courant["validite"] if courant else "historique"})
    reponse = {"accepte": True, "resultat": {"couleurs": lignes}}
    verifier_borne(reponse, limite_sortie)
    return reponse


def lire(principal, couleurs, intervention_id, limite=20, decalage=0, revision_max=None, limite_sortie=BORNE_SORTIE):
    if (not sources._texte(intervention_id) or not sources._entier(limite, 20) or limite == 0
            or not sources._entier(decalage) or (revision_max is not None and not sources._entier(revision_max))):
        raise Refus("ARGUMENTS")
    index, maillons, precedentes = _charger(principal, couleurs)
    if not any(m.get("intervention_id") == intervention_id and m["type_entree"] == "intervention_inscrite"
               for _, m in index[0].values()):
        raise Refus("INTERVENTION-INCONNUE")
    courante = precedentes[intervention_id]["revision"] if intervention_id in precedentes else 0
    plafond = courante if revision_max is None else revision_max
    if plafond > courante:
        raise Refus("REVISION-PERIMEE")
    selection = [m for m in maillons if m["ancre"]["intervention_id"] == intervention_id and m["revision"] <= plafond]
    lignes = []
    for m in selection[decalage:decalage + limite]:
        courant = index[1].get(sources._cle(m["ancre"]))
        lignes.append({"couleur_id": m["ligne_id"], "revision": m["revision"], "ancre": deepcopy(m["ancre"]),
                       "creneau": deepcopy(m["creneau"]), "couleur": m["couleur"],
                       "auteur": deepcopy(m["auteur"]), "horodatage": m["horodatage"],
                       "source_courante": courant is not None,
                       "validite": courant["validite"] if courant else "historique"})
    suivant = decalage + len(lignes)
    reponse = {"accepte": True, "resultat": {"intervention_id": intervention_id, "revision_max": plafond,
        "revision_courante": courante, "total": len(selection), "decalage": decalage,
        "suivant": suivant if suivant < len(selection) else None, "couleurs": lignes}}
    verifier_borne(reponse, limite_sortie)
    return reponse
