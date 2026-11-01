"""« Ce qui a changé depuis hier » : la différence entre ce que M9 SAVAIT à deux instants, avec un reçu vérifiable.

Module pur, sans horloge. Deux ensembles de captures sont comparés — celles que M9 connaissait à ``depuis`` et celles
qu'il connaît à ``maintenant`` (une capture reçue plus tard ne figure pas dans l'état d'hier : la chaîne de réception
est monotone). Pour chaque lecture :

* l'état de la lecture (absente, refusée, partielle, contradictoire, établie) avant et après ;
* si les deux côtés sont établis ET ont été lus avec les MÊMES arguments : les faits citables modifiés, nouveaux ou
  disparus (valeur avant/après en texte exact, statut de certitude de chacun) ; avec des arguments différents la
  comparaison est déclarée impossible, jamais devinée ;
* aucun fait « volatil » (l'âge, l'instant de lecture) : il change chaque jour sans rien dire de l'entreprise.

Le REÇU (``opsys.m9.recu_changements/v1``) lie l'intervalle, les maillons de captures utilisés de chaque côté et
l'empreinte du résultat ; ``verifier_recu`` refait la comparaison depuis la chaîne et dit si le reçu est encore vrai.
Aucun chiffre n'est calculé : seuls des textes de faits sont mis côte à côte.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import timedelta

from . import capture_strategique as cs
from . import catalogue_producteurs as cat
from . import certitude as ct
from . import dossier_strategique

VERSION = "2026-11-01.1"
SCHEMA_RECU = "opsys.m9.recu_changements/v1"
DUREE_DEFAUT_S = 86400
MAX_PAR_LECTURE = 20
_VOLATILS = (".age_s", ".aujourd_hui", ".maintenant")


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _iso(valeur) -> str:
    return valeur.isoformat().replace("+00:00", "Z")


def _empreinte(valeur: object) -> str:
    return hashlib.sha256(json.dumps(valeur, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _faits_par_chemin(capture: Mapping) -> tuple[dict[str, str], dict[str, str]]:
    """``(chemin → texte, chemin → statut)`` des faits citables d'une capture, sans les faits volatils."""
    faits, _ = dossier_strategique.faits_citables([capture], max_faits=10**6)
    classes = ct.classer_faits(capture)
    prefixe = f"{capture['lecture_id']}#{capture['index']}:p"
    textes: dict[str, str] = {}
    statuts: dict[str, str] = {}
    for adresse, texte in faits.items():
        reste = adresse[len(prefixe) :]
        page, chemin = reste.split(".", 1)
        if chemin.endswith(_VOLATILS):
            continue
        cle = f"p{page}.{chemin}"
        textes[cle] = texte
        statuts[cle] = ct.statut_du_fait(classes, chemin)
    return textes, statuts


def _arguments_comparables(capture: Mapping) -> dict:
    """Les arguments d'une lecture SANS son instant de référence : « où en est-on au… » change chaque jour sans que la
    question posée au producteur change. Deux lectures de jours différents se comparent si elles posent la même
    question."""
    lecture = cat.PAR_ID[capture["lecture_id"]]
    return {k: v for k, v in capture["arguments"].items() if k != lecture.reference}


def _etat(connues: Sequence[Mapping], lecture_id: str) -> dict:
    etat = ct.etat_lecture(connues, lecture_id)
    capture = etat["capture"]
    return {
        "certitude": etat["certitude"],
        "code": etat["code"],
        "capture": None
        if capture is None
        else {"index": capture["index"], "hash_maillon": capture["hash_maillon"], "recu_a": capture["recu_a"]},
        "_capture": capture,
    }


def comparer(
    captures: Sequence[Mapping], *, maintenant: str, depuis: str | None = None, duree_s: int = DUREE_DEFAUT_S
) -> dict:  # fmt: skip
    """La différence entre l'état connu à ``depuis`` (par défaut ``maintenant`` − ``duree_s``) et celui de
    ``maintenant``."""
    fin = cs.instant(maintenant)
    if fin is None:
        raise _refus("REJ-CHANGEMENTS-TEMPS", "instant de référence avec fuseau explicite requis")
    if depuis is None:
        if type(duree_s) is not int or not 60 <= duree_s <= 90 * 86400:
            raise _refus("REJ-CHANGEMENTS-DUREE", "durée entière de 60 secondes à 90 jours requise")
        debut = fin - timedelta(seconds=duree_s)
    else:
        debut = cs.instant(depuis)
        if debut is None:
            raise _refus("REJ-CHANGEMENTS-TEMPS", "instant de départ avec fuseau explicite requis")
    if not debut < fin:
        raise _refus("REJ-CHANGEMENTS-TEMPS", "le départ doit précéder la référence")
    avant_connu = cs.connues_a(captures, _iso(debut))
    apres_connu = cs.connues_a(captures, _iso(fin))
    lecture_ids = sorted({c["lecture_id"] for c in apres_connu})
    changements: list[dict] = []
    utilisees_avant: list[dict] = []
    utilisees_apres: list[dict] = []
    for lecture_id in lecture_ids:
        avant, apres = _etat(avant_connu, lecture_id), _etat(apres_connu, lecture_id)
        entree: dict = {
            "lecture_id": lecture_id,
            "avant": {k: v for k, v in avant.items() if k != "_capture"},
            "apres": {k: v for k, v in apres.items() if k != "_capture"},
        }
        for etat, liste in ((avant, utilisees_avant), (apres, utilisees_apres)):
            if etat["capture"] is not None:
                liste.append({"lecture_id": lecture_id, **{k: etat["capture"][k] for k in ("index", "hash_maillon")}})
        if avant["certitude"] == ct.ABSENT:
            entree["nature"] = "PREMIERE_LECTURE"
        elif avant["certitude"] != apres["certitude"]:
            entree["nature"] = "ETAT_DE_LA_LECTURE_CHANGE"
        else:
            entree["nature"] = "MEME_ETAT"
        if avant["certitude"] == ct.ETABLI and apres["certitude"] == ct.ETABLI:
            if _arguments_comparables(avant["_capture"]) != _arguments_comparables(apres["_capture"]):
                entree["faits"] = {
                    "comparaison": "IMPOSSIBLE",
                    "raison": "lectures posant des questions différentes (arguments autres que l'instant de référence)",
                }
            else:
                av_t, av_s = _faits_par_chemin(avant["_capture"])
                ap_t, ap_s = _faits_par_chemin(apres["_capture"])
                modifies = [
                    {"chemin": c, "avant": av_t[c], "apres": ap_t[c], "statut_avant": av_s[c], "statut_apres": ap_s[c]}
                    for c in sorted(set(av_t) & set(ap_t))
                    if av_t[c] != ap_t[c] or av_s[c] != ap_s[c]
                ]
                nouveaux = [
                    {"chemin": c, "apres": ap_t[c], "statut_apres": ap_s[c]} for c in sorted(set(ap_t) - set(av_t))
                ]
                disparus = [
                    {"chemin": c, "avant": av_t[c], "statut_avant": av_s[c]} for c in sorted(set(av_t) - set(ap_t))
                ]
                entree["faits"] = {
                    "comparaison": "FAITE",
                    "modifies_total": len(modifies),
                    "nouveaux_total": len(nouveaux),
                    "disparus_total": len(disparus),
                    "modifies": modifies[:MAX_PAR_LECTURE],
                    "nouveaux": nouveaux[:MAX_PAR_LECTURE],
                    "disparus": disparus[:MAX_PAR_LECTURE],
                }
                entree["nature"] = "FAITS_CHANGES" if (modifies or nouveaux or disparus) else "AUCUN_CHANGEMENT_DE_FAIT"
        elif apres["certitude"] == ct.ETABLI:
            entree["faits"] = {"comparaison": "IMPOSSIBLE", "raison": "la lecture d'avant n'était pas établie"}
        changements.append(entree)
    reste = [c for c in changements if c["nature"] not in ("MEME_ETAT", "AUCUN_CHANGEMENT_DE_FAIT")]
    resultat = {
        "type": "CHANGEMENTS_DEPUIS",
        "version": VERSION,
        "depuis": _iso(debut),
        "jusqua": _iso(fin),
        "lectures_comparees": len(changements),
        "lectures_changees": len(reste),
        "changements": changements,
        "limites": [
            "Différence entre deux états de CONNAISSANCE de M9 (instants de réception), pas entre deux états de "
            "l'entreprise.",
            "Les faits volatils (âge, instant de lecture) sont exclus : ils changent chaque jour sans rien dire.",
        ],
    }
    recu = {
        "schema": SCHEMA_RECU,
        "depuis": resultat["depuis"],
        "jusqua": resultat["jusqua"],
        "captures_avant": sorted(utilisees_avant, key=lambda c: (c["lecture_id"], c["index"])),
        "captures_apres": sorted(utilisees_apres, key=lambda c: (c["lecture_id"], c["index"])),
        "catalogue_version": cat.CATALOGUE_VERSION,
        "empreinte_resultat": _empreinte(resultat),
    }
    recu["empreinte"] = _empreinte(recu)
    return {**resultat, "recu": recu}


def verifier_recu(captures: Sequence[Mapping], recu: object) -> dict:
    """Refait la comparaison de l'intervalle du reçu depuis la chaîne ; dit si l'empreinte et les maillons
    concordent."""
    cles = {
        "schema", "depuis", "jusqua", "captures_avant", "captures_apres", "catalogue_version", "empreinte_resultat",
        "empreinte",
    }  # fmt: skip
    if not isinstance(recu, Mapping) or set(recu) != cles or recu["schema"] != SCHEMA_RECU:
        return {"valide": False, "raison": "reçu mal formé"}
    sans = {k: v for k, v in recu.items() if k != "empreinte"}
    if recu["empreinte"] != _empreinte(sans):
        return {"valide": False, "raison": "empreinte du reçu incohérente (reçu modifié)"}
    try:
        refait = comparer(captures, maintenant=recu["jusqua"], depuis=recu["depuis"])
    except ValueError as exc:
        return {"valide": False, "raison": str(exc)[:200]}
    if refait["recu"]["empreinte"] != recu["empreinte"]:
        return {"valide": False, "raison": "la chaîne de captures ne redonne pas ce résultat"}
    return {"valide": True, "raison": None}
