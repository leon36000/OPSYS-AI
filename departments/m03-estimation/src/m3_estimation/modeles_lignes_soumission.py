"""Lignes réutilisables liées à une version textuelle exacte, sans prix ni quantité.

Journal distinct des modèles textuels et des devis. L'adaptateur revalide
l'admin, la provenance du modèle et les références M6; ce domaine ne consulte
aucune autre source. Un hash ne prouve pas l'authenticité d'une réécriture
cohérente du journal entier.
"""

import re
from copy import deepcopy

from .devis_durable import _ajouter
from .modeles_soumission import (
    BORNE_SORTIE,
    MAX_SOURCES,
    Refus,
    _auteur,
    _horodatage,
    _identifiant,
    _mutation,
    _texte,
    refuser,
    verifier_borne,
)
from .registre import _encoder_canonique

__all__ = ["REGISTRE", "MAX_SOURCES", "Refus", "enregistrer", "lire", "refuser", "verifier_borne"]

REGISTRE = "modeles_lignes_soumission"
TYPE = "modele_lignes_soumission"
_ARGUMENTS = ("modele_id", "modele_source", "lignes", "revision_attendue")
_PUBLIC = ("modele_id", "modele_source", "lignes", "revision", "source_id", "auteur", "horodatage")
_CLES = set(_ARGUMENTS) | {"type_entree", "rang", "precedent", "revision", "source_id", "auteur",
                         "mutation", "horodatage"}
_CLES_LIGNE = {"ligne_id", "description", "materiau_id", "unite"}


def _ancre(modele_id, modele_source):
    if (not _identifiant(modele_id, 100) or modele_id in {".", ".."}
            or type(modele_source) is not str or re.fullmatch(r"[0-9a-f]{64}", modele_source) is None):
        raise Refus("ARGUMENTS")
    return modele_id, modele_source


def _arguments(modele_id, modele_source, lignes, revision_attendue):
    _ancre(modele_id, modele_source)
    if (type(lignes) is not list or not 1 <= len(lignes) <= 20
            or type(revision_attendue) is not int or not 0 <= revision_attendue <= MAX_SOURCES):
        raise Refus("ARGUMENTS")
    identifiants = set()
    for ligne in lignes:
        if (type(ligne) is not dict or set(ligne) != _CLES_LIGNE
                or not _identifiant(ligne["ligne_id"], 100) or ligne["ligne_id"] in {".", ".."}
                or ligne["ligne_id"] in identifiants
                or not _texte(ligne["description"], 500, multiligne=True)
                or not _texte(ligne["materiau_id"], 200) or not _texte(ligne["unite"], 40)):
            raise Refus("ARGUMENTS")
        identifiants.add(ligne["ligne_id"])
    return {"modele_id": modele_id, "modele_source": modele_source, "lignes": deepcopy(lignes),
            "revision_attendue": revision_attendue}


def _charger(journal):
    if len(journal) > MAX_SOURCES:
        raise Refus("SOURCES-TROP-VOLUMINEUSES")
    maillons = list(journal)
    if len(maillons) > MAX_SOURCES:
        raise Refus("SOURCES-TROP-VOLUMINEUSES")
    dernieres, mutations = {}, {}
    precedent = None
    for rang, m in enumerate(maillons):
        try:
            if type(m) is not dict or set(m) != _CLES:
                raise Refus("SOURCE-INVALIDE")
            arguments = _arguments(*(m[c] for c in _ARGUMENTS))
            _auteur(m["auteur"])
            _mutation(m["mutation"], arguments)
            _horodatage(m["horodatage"])
            ancre = (m["modele_id"], m["modele_source"])
            revision = dernieres[ancre]["revision"] if ancre in dernieres else 0
            cle = (m["mutation"]["appareil"], m["mutation"]["cle"])
            if (type(m["type_entree"]) is not str or m["type_entree"] != TYPE
                    or type(m["rang"]) is not int or m["rang"] != rang
                    or m["precedent"] != precedent or m["revision_attendue"] != revision
                    or type(m["revision"]) is not int or m["revision"] != revision + 1
                    or cle in mutations or type(m["source_id"]) is not str
                    or m["source_id"] != _encoder_canonique({k: v for k, v in m.items() if k != "source_id"})):
                raise Refus("SOURCE-INVALIDE")
            dernieres[ancre] = m
            mutations[cle] = m
            precedent = m["source_id"]
        except (Refus, KeyError, TypeError, ValueError, RecursionError):
            raise Refus("SOURCE-INVALIDE") from None
    return maillons, dernieres, mutations, precedent


def _public(maillon):
    return deepcopy({cle: maillon[cle] for cle in _PUBLIC})


def enregistrer(journal, modele_id, modele_source, lignes, revision_attendue, *, auteur, mutation,
                horodatage, limite_sortie=BORNE_SORTIE):
    arguments = _arguments(modele_id, modele_source, lignes, revision_attendue)
    _auteur(auteur)
    _mutation(mutation, arguments)
    _horodatage(horodatage)
    maillons, dernieres, mutations, tete = _charger(journal)
    existante = mutations.get((mutation["appareil"], mutation["cle"]))
    if existante is not None:
        if (existante["auteur"] != auteur or existante["mutation"] != mutation
                or any(existante[c] != arguments[c] for c in _ARGUMENTS)):
            raise Refus("MUTATION-CONFLIT")
        reponse = {"accepte": True, "resultat": _public(existante), "rejoue": True}
        verifier_borne(reponse, limite_sortie)
        return reponse
    ancre = (modele_id, modele_source)
    revision = dernieres[ancre]["revision"] if ancre in dernieres else 0
    if revision_attendue != revision:
        raise Refus("REVISION-PERIMEE")
    if len(maillons) == MAX_SOURCES:
        raise Refus("SOURCES-TROP-VOLUMINEUSES")
    maillon = {**arguments, "type_entree": TYPE, "rang": len(maillons), "precedent": tete,
               "revision": revision + 1, "auteur": deepcopy(auteur), "mutation": deepcopy(mutation),
               "horodatage": horodatage}
    maillon["source_id"] = _encoder_canonique(maillon)
    reponse = {"accepte": True, "resultat": _public(maillon), "rejoue": False}
    verifier_borne(reponse, limite_sortie)
    _ajouter(maillon, journal, len(maillons))
    return reponse


def lire(journal, modele_id, modele_source, version=0, limite_sortie=BORNE_SORTIE):
    ancre = _ancre(modele_id, modele_source)
    if type(version) is not int or not 0 <= version <= MAX_SOURCES:
        raise Refus("ARGUMENTS")
    maillons, dernieres, _, _ = _charger(journal)
    if ancre not in dernieres:
        raise Refus("INTROUVABLE")
    courant = dernieres[ancre]
    choisi = (courant if version == 0 else next((m for m in maillons
              if (m["modele_id"], m["modele_source"]) == ancre and m["revision"] == version), None))
    if choisi is None:
        raise Refus("INTROUVABLE")
    reponse = {"accepte": True, "resultat": {**_public(choisi), "revision_courante": courant["revision"]}}
    verifier_borne(reponse, limite_sortie)
    return reponse
