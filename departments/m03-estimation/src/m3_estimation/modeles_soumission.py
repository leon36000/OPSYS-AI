"""Catalogue textuel versionné, séparé des devis et sans horloge ni effet externe.

Le journal est une liste ou un support durable compatible. Les hashes détectent
les altérations partielles et la validation contrôle les invariants métier;
ils ne prouvent pas l'authenticité d'une chaîne entièrement réécrite.
L'adaptateur doit revalider l'admin et fournir heure et intention serveur.
"""

import json
import re
import unicodedata
from copy import deepcopy
from datetime import datetime

from .devis_durable import _ajouter
from .registre import _encoder_canonique

REGISTRE = "modeles_soumission"
TYPE = "modele_soumission"
MAX_SOURCES = 1000
BORNE_SORTIE = 65536
_IDENTIFIANT = re.compile(r"[A-Za-z0-9_.:@-]{1,200}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})")
_ARGUMENTS = ("modele_id", "titre", "description", "clauses", "revision_attendue")
_PUBLIC = ("modele_id", "titre", "description", "clauses", "revision", "source_id", "auteur", "horodatage")
_META = ("modele_id", "titre", "revision", "source_id", "auteur", "horodatage")
_CLES = set(_ARGUMENTS) | {"type_entree", "rang", "precedent", "revision", "source_id", "auteur",
                         "mutation", "horodatage"}


class Refus(Exception):
    def __init__(self, suffixe):
        self.suffixe = suffixe
        super().__init__(suffixe)


def refuser(suffixe):
    return {"accepte": False, "verdict": {"code": "REJ-MODELE-" + suffixe}}


def _identifiant(valeur, maximum=200):
    return type(valeur) is str and len(valeur) <= maximum and _IDENTIFIANT.fullmatch(valeur) is not None


def _texte(valeur, maximum, *, vide=False, multiligne=False):
    return (type(valeur) is str and len(valeur) <= maximum and (vide or bool(valeur.strip()))
            and not any(unicodedata.category(c) in {"Cc", "Cf", "Cs"}
                        and not (multiligne and c in "\t\r\n") for c in valeur))


def _arguments(modele_id, titre, description, clauses, revision_attendue):
    if (not _identifiant(modele_id, 100) or modele_id in {".", ".."} or not _texte(titre, 120)
            or not _texte(description, 4000, multiligne=True)
            or not _texte(clauses, 12000, vide=True, multiligne=True)
            or type(revision_attendue) is not int or not 0 <= revision_attendue <= MAX_SOURCES):
        raise Refus("ARGUMENTS")
    return dict(zip(_ARGUMENTS, (modele_id, titre, description, clauses, revision_attendue), strict=True))


def _auteur(auteur):
    if (type(auteur) is not dict or set(auteur) != {"personne", "role"}
            or not _identifiant(auteur["personne"]) or type(auteur["role"]) is not str
            or auteur["role"] != "admin"):
        raise Refus("IDENTITE")


def _mutation(mutation, arguments):
    if (type(mutation) is not dict or set(mutation) != {"appareil", "cle", "empreinte_arguments"}
            or not _identifiant(mutation["appareil"]) or not _identifiant(mutation["cle"])
            or type(mutation["empreinte_arguments"]) is not str
            or mutation["empreinte_arguments"] != _encoder_canonique(arguments)):
        raise Refus("ARGUMENTS")


def _horodatage(valeur):
    try:
        if type(valeur) is not str or _DATE.fullmatch(valeur) is None:
            raise ValueError("heure serveur absente")
        instant = datetime.fromisoformat(valeur)
        if instant.utcoffset() is None:
            raise ValueError("heure sans fuseau")
    except (ValueError, OverflowError):
        raise Refus("HORODATAGE-INVALIDE") from None


def verifier_borne(reponse, limite_sortie):
    """Borne la réponse complète avant append, enveloppe du répartiteur comprise."""
    if type(limite_sortie) is not int or limite_sortie < 1:
        raise Refus("SORTIE-TROP-VOLUMINEUSE")
    enveloppe = {"ok": True, "resultat": reponse, "rejoue": False}
    if len(json.dumps(enveloppe, ensure_ascii=False).encode("utf-8")) > limite_sortie:
        raise Refus("SORTIE-TROP-VOLUMINEUSE")


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
            revision = dernieres[m["modele_id"]]["revision"] if m["modele_id"] in dernieres else 0
            cle = (m["mutation"]["appareil"], m["mutation"]["cle"])
            if (type(m["type_entree"]) is not str or m["type_entree"] != TYPE
                    or type(m["rang"]) is not int or m["rang"] != rang
                    or m["precedent"] != precedent or m["revision_attendue"] != revision
                    or type(m["revision"]) is not int or m["revision"] != revision + 1
                    or cle in mutations or type(m["source_id"]) is not str
                    or m["source_id"] != _encoder_canonique({k: v for k, v in m.items() if k != "source_id"})):
                raise Refus("SOURCE-INVALIDE")
            dernieres[m["modele_id"]] = m
            mutations[cle] = m
            precedent = m["source_id"]
        except (Refus, KeyError, TypeError, ValueError, RecursionError):
            raise Refus("SOURCE-INVALIDE") from None
    return maillons, dernieres, mutations, precedent


def _public(maillon, champs=_PUBLIC):
    return deepcopy({cle: maillon[cle] for cle in champs})


def enregistrer(journal, modele_id, titre, description, clauses, revision_attendue, *, auteur, mutation,
                horodatage, limite_sortie=BORNE_SORTIE):
    arguments = _arguments(modele_id, titre, description, clauses, revision_attendue)
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
    revision = dernieres[modele_id]["revision"] if modele_id in dernieres else 0
    if revision_attendue != revision:
        raise Refus("REVISION-PERIMEE")
    if len(maillons) == MAX_SOURCES:
        raise Refus("SOURCES-TROP-VOLUMINEUSES")
    m = {**arguments, "type_entree": TYPE, "rang": len(maillons), "precedent": tete,
         "revision": revision + 1, "auteur": deepcopy(auteur), "mutation": deepcopy(mutation),
         "horodatage": horodatage}
    m["source_id"] = _encoder_canonique(m)
    reponse = {"accepte": True, "resultat": _public(m), "rejoue": False}
    verifier_borne(reponse, limite_sortie)
    _ajouter(m, journal, len(maillons))
    return reponse


def lire(journal, modele_id, version=0, limite_sortie=BORNE_SORTIE):
    if (not _identifiant(modele_id, 100) or modele_id in {".", ".."}
            or type(version) is not int or not 0 <= version <= MAX_SOURCES):
        raise Refus("ARGUMENTS")
    maillons, dernieres, _, _ = _charger(journal)
    if modele_id not in dernieres:
        raise Refus("INTROUVABLE")
    courant = dernieres[modele_id]
    choisi = (courant if version == 0 else
              next((m for m in maillons if m["modele_id"] == modele_id and m["revision"] == version), None))
    if choisi is None:
        raise Refus("INTROUVABLE")
    reponse = {"accepte": True, "resultat": {**_public(choisi), "revision_courante": courant["revision"]}}
    verifier_borne(reponse, limite_sortie)
    return reponse


def lister(journal, decalage=0, source_attendue="", limite_sortie=BORNE_SORTIE):
    if (type(decalage) is not int or not 0 <= decalage <= MAX_SOURCES or decalage % 25
            or type(source_attendue) is not str
            or (source_attendue and re.fullmatch(r"[0-9a-f]{64}", source_attendue) is None)
            or (decalage > 0 and not source_attendue)):
        raise Refus("ARGUMENTS")
    _, dernieres, _, tete = _charger(journal)
    empreinte = _encoder_canonique(REGISTRE, tete)
    if source_attendue and source_attendue != empreinte:
        raise Refus("SOURCE-MODIFIEE")
    selection = sorted(dernieres)
    total = len(selection)
    if decalage and decalage >= total:
        raise Refus("ARGUMENTS")
    reponse = {"accepte": True, "resultat": {
        "modeles": [_public(dernieres[cle], _META) for cle in selection[decalage:decalage + 25]],
        "decalage": decalage, "decalage_suivant": decalage + 25 if decalage + 25 < total else None,
        "total": total, "source_empreinte": empreinte}}
    verifier_borne(reponse, limite_sortie)
    return reponse
