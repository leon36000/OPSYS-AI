"""Notes d'achat internes, versionnées : aucun PO, stock, prix ou envoi.

Module pur : identité, horloge, contexte de mutation et stockage appartiennent à outils.py.
"""

from __future__ import annotations

import copy
import json
import unicodedata
from datetime import datetime

from . import encodage

REGISTRE = "notes_commande"
ECRIRE = "m6_enregistrer_note_commande"
LIRE = "m6_lire_note_commande"
LISTER = "m6_lister_notes_commande"
MAX_TEXTE = 20000
MAX_SOURCES = 10000
BORNE_SORTIE = 131072


class Refus(Exception):
    def __init__(self, suffixe):
        self.suffixe = suffixe
        super().__init__(suffixe)


def refuser(suffixe):
    return {"accepte": False, "verdict": {"code": "REJ-NOTE-COMMANDE-" + suffixe}}


def texte(valeur, maximum=200, *, multiligne=False):
    return (
        type(valeur) is str and bool(valeur.strip()) and len(valeur) <= maximum
        and not any(
            unicodedata.category(c) == "Cs"
            or (unicodedata.category(c) == "Cc" and not (multiligne and c in "\r\n\t"))
            for c in valeur
        )
    )


def entier(valeur, minimum=0):
    return type(valeur) is int and minimum <= valeur <= 1000000


def valider_arguments(note_id, devis_id, texte_libre, revision_attendue):
    if not (
        texte(note_id) and texte(devis_id) and texte(texte_libre, MAX_TEXTE, multiligne=True)
        and entier(revision_attendue) and revision_attendue < 1000000
    ):
        raise Refus("ARGUMENTS")


def instant(valeur):
    try:
        if type(valeur) is not str or datetime.fromisoformat(valeur).utcoffset() is None:
            raise ValueError("instant sans fuseau")
    except (ValueError, TypeError):
        raise Refus("REGISTRE-INVALIDE") from None


def valider_registre(maillons):
    derniers, intentions = {}, set()
    precedent = ""
    cles = {
        "note_id", "devis_id", "chantier_id", "texte_libre", "revision", "auteur", "enregistree_le",
        "index", "hash_precedent", "hash_maillon", "revision_precedente", "mutation", "statut",
    }
    for index, m in enumerate(maillons):
        if type(m) is not dict or set(m) != cles:
            raise Refus("REGISTRE-INVALIDE")
        try:
            valider_arguments(m["note_id"], m["devis_id"], m["texte_libre"], m["revision"] - 1)
            ancien = derniers.get(m["note_id"])
            auteur, mutation = m["auteur"], m["mutation"]
            if not (
                texte(m["chantier_id"]) and entier(m["revision"], 1)
                and type(m["index"]) is int and m["index"] == index
                and m["statut"] == "note_interne" and m["hash_precedent"] == precedent
                and type(auteur) is dict and set(auteur) == {"personne", "role"}
                and texte(auteur["personne"], 256) and auteur["role"] == "admin"
                and type(mutation) is dict and set(mutation) == {"appareil", "cle", "empreinte_arguments"}
                and texte(mutation["appareil"], 256) and texte(mutation["cle"])
                and mutation["empreinte_arguments"] == encodage.empreinte({
                    "note_id": m["note_id"], "devis_id": m["devis_id"], "texte_libre": m["texte_libre"],
                    "revision_attendue": m["revision"] - 1,
                })
                and m["revision"] == (ancien["revision"] + 1 if ancien else 1)
                and m["revision_precedente"] == (ancien["index"] if ancien else None)
                and (ancien is None or (m["devis_id"], m["chantier_id"]) == (
                    ancien["devis_id"], ancien["chantier_id"]))
                and m["hash_maillon"] == encodage.empreinte({k: v for k, v in m.items() if k != "hash_maillon"})
            ):
                raise Refus("REGISTRE-INVALIDE")
            instant(m["enregistree_le"])
            cle = (mutation["appareil"], mutation["cle"])
            if cle in intentions:
                raise Refus("REGISTRE-INVALIDE")
            intentions.add(cle)
        except (KeyError, TypeError, ValueError, Refus):
            raise Refus("REGISTRE-INVALIDE") from None
        derniers[m["note_id"]] = m
        precedent = m["hash_maillon"]


def lire(maillons, note_id, revision=None):
    if not texte(note_id) or (revision is not None and not entier(revision, 1)):
        raise Refus("ARGUMENTS")
    trouves = [m for m in maillons if m["note_id"] == note_id
               and (revision is None or m["revision"] == revision)]
    return copy.deepcopy(trouves[-1]) if trouves else None


def retrouver_mutation(maillons, mutation, auteur):
    for m in maillons:
        if (m["mutation"]["appareil"], m["mutation"]["cle"]) == (mutation["appareil"], mutation["cle"]):
            if m["mutation"] != mutation or m["auteur"] != auteur:
                raise Refus("MUTATION-CONFLIT")
            return copy.deepcopy(m)
    return None


def construire(maillons, arguments, chantier_id, auteur, mutation, maintenant):
    ancien = lire(maillons, arguments["note_id"])
    if ancien is not None and (ancien["devis_id"], ancien["chantier_id"]) != (
        arguments["devis_id"], chantier_id
    ):
        raise Refus("ANCRAGE-DIFFERENT")
    if arguments["revision_attendue"] != (ancien["revision"] if ancien else 0):
        raise Refus("REVISION-PERIMEE")
    m = {
        "note_id": arguments["note_id"], "devis_id": arguments["devis_id"], "chantier_id": chantier_id,
        "texte_libre": arguments["texte_libre"], "revision": arguments["revision_attendue"] + 1,
        "auteur": dict(auteur), "enregistree_le": maintenant, "statut": "note_interne",
        "index": len(maillons), "hash_precedent": maillons[-1]["hash_maillon"] if maillons else "",
        "revision_precedente": ancien["index"] if ancien else None, "mutation": dict(mutation),
    }
    m["hash_maillon"] = encodage.empreinte(m)
    return m


def reponse(m, *, rejoue=False):
    champs = ("note_id", "devis_id", "chantier_id", "texte_libre", "revision", "auteur", "enregistree_le", "statut")
    note = {k: copy.deepcopy(m[k]) for k in champs}
    note["source"] = {
        "departement": "m06-material-control", "registre": REGISTRE,
        "index": m["index"], "hash_maillon": m["hash_maillon"],
    }
    return {"accepte": True, "note": note, "rejoue": rejoue}


def verifier_borne(resultat, limite):
    # Inclut l'enveloppe réelle du socle et les deux valeurs de rejeu possibles.
    if any(len(json.dumps({"ok": True, "resultat": resultat, "rejoue": flag}, ensure_ascii=False)) > limite
           for flag in (True, False)):
        raise Refus("SORTIE-TROP-VOLUMINEUSE")


def valider_pagination(devis_id, limite, decalage):
    if not (
        texte(devis_id) and type(limite) is int and 1 <= limite <= 20
        and type(decalage) is int and 0 <= decalage <= 10000
    ):
        raise Refus("ARGUMENTS")


def lister(maillons, devis_id, chantier_id, limite=20, decalage=0):
    """Projection d'un registre déjà validé : métadonnées courantes, jamais de texte.

    L'ancrage fourni vient des besoins M6 relus par l'adaptateur. La cohérence est
    vérifiée avant pagination, y compris pour une note qui n'est pas sur la page.
    """
    valider_pagination(devis_id, limite, decalage)
    derniers = {}
    for m in maillons:
        if m["devis_id"] == devis_id:
            if m["chantier_id"] != chantier_id:
                raise Refus("ANCRAGE-DIFFERENT")
            derniers[m["note_id"]] = m
    ids = sorted(derniers)
    notes = []
    for note_id in ids[decalage:decalage + limite]:
        m = derniers[note_id]
        notes.append({
            "note_id": m["note_id"], "revision": m["revision"], "auteur": copy.deepcopy(m["auteur"]),
            "enregistree_le": m["enregistree_le"],
            "source": {
                "departement": "m06-material-control", "registre": REGISTRE,
                "index": m["index"], "hash_maillon": m["hash_maillon"],
            },
        })
    suivant = decalage + len(notes)
    return {"accepte": True, "resultat": {
        "devis_id": devis_id, "chantier_id": chantier_id, "notes": notes, "total": len(ids),
        "decalage": decalage, "suivant": suivant if suivant < len(ids) else None,
    }}
