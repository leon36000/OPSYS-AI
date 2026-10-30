"""Plans d'exécution et OKR M9.16 : objectifs, porteurs, échéances et résultats reliés à leurs sources, avec historique.

Module pur. Un plan est un événement chaîné ``PLAN`` (objectif, porteur, échéance, résultats clés, sources citées avec
leur
valeur d'alors, décision liée). Le réviser ajoute une version, jamais une réécriture ; l'annuler ajoute une
``ANNULATION`` ;
un suivi est une note ``SUIVI`` déclarée par une personne.

* un résultat clé MESURABLE se lit sur les captures des propriétaires (``criteres.evaluer``) : SATISFAIT, NON_SATISFAIT
ou
  INCONNU ; un résultat clé ``manuel`` reste à juger. **Un suivi enregistré ne vaut jamais effet réalisé** : seul le
  critère
  mesuré, ou le jugement de la personne hors M9, fait « atteint » ;
* le RETARD est calculé du jour de connaissance contre l'échéance (jour civil fourni, M9 n'a pas d'horloge) ;
* une SOURCE CHANGÉE est détectée en relisant, dans la dernière capture complète de la même lecture, la valeur au même
chemin
  que celle citée au dépôt du plan : le plan n'est pas modifié, le constat est rendu, la révision reste une décision
  humaine.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs
from . import chainage, criteres

SCHEMA = "m9.plans.v1"
TYPES = frozenset({"PLAN", "ANNULATION", "SUIVI"})
MAX_RESULTATS = 12
MAX_SOURCES = 12
_ID = re.compile(r"[a-z0-9][a-z0-9_.\-]{0,63}")
_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}")
ADRESSE = re.compile(r"(?P<lecture>[a-z0-9_.]+)#(?P<rang>\d+):p(?P<page>\d+)\.(?P<chemin>[A-Za-z0-9_.\[\]]+)")
_SEGMENT = re.compile(r"([A-Za-z0-9_]+)(?:\[(\d+)\])?")
_CHAMPS_RESULTAT = frozenset({"id", "libelle", "lecture", "chemin", "operateur", "cible"})
_LIMITES = (
    "Un suivi enregistré n'est pas un effet réalisé : un résultat clé n'est atteint que mesuré chez son propriétaire.",
    "Une source changée est signalée, jamais corrigée en silence : réviser le plan est une décision de la personne.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def valider_chaine(chaine: Sequence[Mapping]) -> tuple[bool, str]:
    return chainage.valider(SCHEMA, TYPES, chaine)


def _jour(valeur: object, nom: str) -> dt.date:
    if type(valeur) is not str or not _JOUR.fullmatch(valeur):
        raise _refus("REJ-PLAN-DATE", f"{nom} : jour AAAA-MM-JJ requis")
    try:
        return dt.date.fromisoformat(valeur)
    except ValueError as exc:
        raise _refus("REJ-PLAN-DATE", f"{nom} : jour impossible") from exc


def _resultat(brut: object) -> dict:
    if not isinstance(brut, Mapping) or not {"id", "libelle", "operateur"} <= set(brut) <= _CHAMPS_RESULTAT:
        raise _refus("REJ-PLAN-RESULTAT", "résultat clé {id, libelle, operateur[, lecture, chemin, cible]} requis")
    if type(brut["id"]) is not str or not _ID.fullmatch(brut["id"]):
        raise _refus("REJ-PLAN-RESULTAT", "identifiant minuscule sobre requis")
    if type(brut["libelle"]) is not str or not brut["libelle"].strip() or len(brut["libelle"]) > 300:
        raise _refus("REJ-PLAN-RESULTAT", "libellé borné requis")
    if brut["operateur"] not in criteres.OPERATEURS:
        raise _refus("REJ-PLAN-RESULTAT", f"opérateur parmi {sorted(criteres.OPERATEURS)}")
    if brut["operateur"] == "manuel":
        return {
            "id": brut["id"],
            "libelle": brut["libelle"],
            "operateur": "manuel",
            "lecture": None,
            "chemin": None,
            "cible": None,
        }
    if type(brut.get("lecture")) is not str or type(brut.get("chemin")) is not str:
        raise _refus("REJ-PLAN-RESULTAT", "un résultat mesurable cite une lecture et un chemin")
    cible = brut.get("cible")
    if cible is not None and (type(cible) is not str or len(cible) > 40):
        raise _refus("REJ-PLAN-RESULTAT", "cible textuelle bornée ou absente")
    return {
        "id": brut["id"],
        "libelle": brut["libelle"],
        "operateur": brut["operateur"],
        "lecture": brut["lecture"],
        "chemin": brut["chemin"],
        "cible": cible,
    }


def etat_plans(chaine: Sequence[Mapping]) -> dict[str, dict]:
    plans: dict[str, dict] = {}
    for evenement in chaine:
        courant = plans.setdefault(
            evenement["plan_id"], {"plan_id": evenement["plan_id"], "versions": [], "annule": None, "suivis": []}
        )
        if evenement["type"] == "PLAN":
            courant["versions"].append(evenement)
        elif evenement["type"] == "ANNULATION":
            courant["annule"] = {"motif": evenement["motif"], "recu_a": evenement["recu_a"], "par": evenement["par"]}
        else:
            courant["suivis"].append({k: evenement[k] for k in ("resultat_id", "note", "recu_a", "par")})
    return plans


def enregistrer(
    chaine: Sequence[Mapping],
    plan: Mapping,
    faits: Mapping[str, str],
    *,
    recu_a: str,
    par: str,
    motif_revision: str | None = None,
) -> dict:
    """Maillon PLAN (version 1) ou révision (version n+1, ``motif_revision`` obligatoire)."""
    champs = {"plan_id", "objectif", "porteur", "echeance", "resultats_cles", "sources", "decision_ref"}
    if (
        not isinstance(plan, Mapping)
        or not {"plan_id", "objectif", "porteur", "echeance", "resultats_cles"} <= set(plan) <= champs
    ):
        raise _refus("REJ-PLAN-CHAMP", f"plan {sorted(champs)} requis")
    plan_id = plan["plan_id"]
    if type(plan_id) is not str or not _ID.fullmatch(plan_id):
        raise _refus("REJ-PLAN-CHAMP", "identifiant minuscule sobre requis")
    for nom in ("objectif", "porteur"):
        if type(plan[nom]) is not str or not plan[nom].strip() or len(plan[nom]) > 300:
            raise _refus("REJ-PLAN-CHAMP", f"{nom} : texte borné requis")
    echeance = _jour(plan["echeance"], "echeance")
    resultats = plan["resultats_cles"]
    if type(resultats) is not list or not 1 <= len(resultats) <= MAX_RESULTATS:
        raise _refus("REJ-PLAN-RESULTAT", f"1 à {MAX_RESULTATS} résultats clés requis")
    propres = [_resultat(r) for r in resultats]
    if len({r["id"] for r in propres}) != len(propres):
        raise _refus("REJ-PLAN-RESULTAT", "identifiants de résultats distincts requis")
    sources = plan.get("sources", [])
    if type(sources) is not list or len(sources) > MAX_SOURCES:
        raise _refus("REJ-PLAN-SOURCE", f"au plus {MAX_SOURCES} sources")
    courant = etat_plans(chaine).get(plan_id)
    # Une révision peut conserver une source déjà citée par la version précédente (sa valeur d'alors reste figée) ;
    # toute NOUVELLE source doit être un fait citable du dossier courant.
    anciennes = courant["versions"][-1]["plan"]["sources"] if courant is not None and courant["versions"] else {}
    instantane = {}
    for adresse in sources:
        if type(adresse) is not str or not ADRESSE.fullmatch(adresse):
            raise _refus("REJ-PLAN-SOURCE", "source : adresse de fait invalide")
        if adresse in anciennes:
            instantane[adresse] = anciennes[adresse]
        elif adresse in faits:
            instantane[adresse] = faits[adresse]
        else:
            raise _refus("REJ-PLAN-SOURCE", "source : adresse absente des faits citables du dossier")
    decision = plan.get("decision_ref")
    if decision is not None and (type(decision) is not str or not _ID.fullmatch(decision)):
        raise _refus("REJ-PLAN-CHAMP", "decision_ref : identifiant sobre ou absent")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    if courant is not None and courant["annule"] is not None:
        raise _refus("REJ-PLAN-ANNULE", "plan annulé : un nouvel identifiant est requis")
    version = len(courant["versions"]) + 1 if courant is not None else 1
    if version > 1 and (type(motif_revision) is not str or not motif_revision.strip() or len(motif_revision) > 300):
        raise _refus("REJ-PLAN-REVISION", "motif de révision borné requis")
    if version == 1 and motif_revision is not None:
        raise _refus("REJ-PLAN-REVISION", "un premier dépôt n'a pas de motif de révision")
    if version > 1 and courant["versions"][-1]["plan"] == {  # type: ignore[index]
        "objectif": plan["objectif"], "porteur": plan["porteur"], "echeance": echeance.isoformat(),
        "resultats_cles": propres, "decision_ref": decision, "sources": instantane,
    }:  # fmt: skip
        raise _refus("REJ-PLAN-REVISION", "aucun changement : une révision identique n'ajoute rien")
    return chainage.suivant(
        SCHEMA,
        chaine,
        {
            "type": "PLAN",
            "plan_id": plan_id,
            "version": version,
            "plan": {
                "objectif": plan["objectif"],
                "porteur": plan["porteur"],
                "echeance": echeance.isoformat(),
                "resultats_cles": propres,
                "decision_ref": decision,
                "sources": instantane,
            },
            "motif_revision": motif_revision,
            "recu_a": recu_a,
            "par": par,
        },
    )


def annuler(chaine: Sequence[Mapping], plan_id: str, motif: str, *, recu_a: str, par: str) -> dict:
    courant = etat_plans(chaine).get(plan_id)
    if courant is None:
        raise _refus("REJ-PLAN-INCONNU", "plan jamais déposé")
    if courant["annule"] is not None:
        raise _refus("REJ-PLAN-ANNULE", "plan déjà annulé")
    if type(motif) is not str or not motif.strip() or len(motif) > 300:
        raise _refus("REJ-PLAN-MOTIF", "motif borné requis")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    return chainage.suivant(
        SCHEMA, chaine, {"type": "ANNULATION", "plan_id": plan_id, "motif": motif, "recu_a": recu_a, "par": par}
    )


def noter_suivi(chaine: Sequence[Mapping], plan_id: str, resultat_id: str, note: str, *, recu_a: str, par: str) -> dict:
    courant = etat_plans(chaine).get(plan_id)
    if courant is None or courant["annule"] is not None:
        raise _refus("REJ-PLAN-INCONNU", "plan inconnu ou annulé")
    if resultat_id not in {r["id"] for r in courant["versions"][-1]["plan"]["resultats_cles"]}:
        raise _refus("REJ-PLAN-RESULTAT", "résultat clé inconnu de la version courante")
    if type(note) is not str or not note.strip() or len(note) > 500:
        raise _refus("REJ-PLAN-MOTIF", "note bornée requise")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    return chainage.suivant(
        SCHEMA,
        chaine,
        {"type": "SUIVI", "plan_id": plan_id, "resultat_id": resultat_id, "note": note, "recu_a": recu_a, "par": par},
    )


def valeur_a(page: object, chemin: str) -> object:
    courant = page
    for segment in chemin.split("."):
        trouve = _SEGMENT.fullmatch(segment)
        if trouve is None or not isinstance(courant, Mapping) or trouve.group(1) not in courant:
            return None
        courant = courant[trouve.group(1)]
        if trouve.group(2) is not None:
            rang = int(trouve.group(2))
            if not isinstance(courant, list) or rang >= len(courant):
                return None
            courant = courant[rang]
    return courant


def sources_changees(version: Mapping, captures: Sequence[Mapping], *, connaissance: str) -> list[dict]:
    """Sources citées dont la valeur, relue dans la dernière capture complète de la même lecture, diffère."""
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    changees = []
    for adresse, ancienne in version["plan"]["sources"].items():
        parties = ADRESSE.fullmatch(adresse)
        if parties is None:  # adresse validée au dépôt : garde défensive
            continue
        utilisables = [
            c
            for c in connues
            if c["lecture_id"] == parties["lecture"]
            and c["verdict"] == "ACCEPTEE"
            and c["complete"]
            and (c["lecture_id"], c["arguments_sha256"]) not in en_conflit
        ]
        if not utilisables:
            changees.append(
                {"source": adresse, "avant": ancienne, "maintenant": None, "raison": "lecture non disponible"}
            )
            continue
        page = int(parties["page"])
        pages = utilisables[-1]["pages"]
        valeur = valeur_a(pages[page], parties["chemin"]) if page < len(pages) else None
        courant = criteres.texte(valeur) if valeur is not None else None
        if courant != ancienne:
            changees.append(
                {
                    "source": adresse,
                    "avant": ancienne,
                    "maintenant": courant,
                    "capture": utilisables[-1]["index"],
                    "raison": "valeur différente" if courant is not None else "valeur disparue",
                }
            )
    return changees


def vue(chaine: Sequence[Mapping], captures: Sequence[Mapping], *, connaissance: str, jour: str) -> dict:
    """Plans à ``connaissance`` : versions, retard, résultats mesurés, sources changées (``jour`` : jour civil)."""
    aujourd_hui = _jour(jour, "jour")
    limite = cs.instant(connaissance)
    if limite is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant de connaissance avec fuseau explicite requis")
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    sortie = []
    for plan_id, courant in sorted(
        etat_plans([e for e in chaine if (cs.instant(e["recu_a"]) or limite) <= limite]).items()
    ):
        if not courant["versions"]:
            continue
        version = courant["versions"][-1]
        resultats = []
        for resultat in version["plan"]["resultats_cles"]:
            suivis = [s for s in courant["suivis"] if s["resultat_id"] == resultat["id"]]
            if resultat["operateur"] == "manuel":
                mesure = {"statut": "A_JUGER_PAR_LA_PERSONNE"}
            else:
                mesure = criteres.evaluer({**resultat, "id": resultat["id"]}, connues, en_conflit)
            resultats.append({**resultat, "mesure": mesure, "suivis_declares": len(suivis)})
        echeance = dt.date.fromisoformat(version["plan"]["echeance"])
        atteint = all(r["mesure"]["statut"] == "SATISFAIT" for r in resultats)
        if courant["annule"] is not None:
            statut = "ANNULE"
        elif atteint:
            statut = "ATTEINT_MESURE"
        elif echeance < aujourd_hui:
            statut = "EN_RETARD"
        else:
            statut = "EN_COURS"
        sortie.append(
            {
                "plan_id": plan_id,
                "version": version["version"],
                "versions_total": len(courant["versions"]),
                "statut": statut,
                "objectif": version["plan"]["objectif"],
                "porteur": version["plan"]["porteur"],
                "echeance": version["plan"]["echeance"],
                "decision_ref": version["plan"]["decision_ref"],
                "resultats_cles": resultats,
                "sources_changees": sources_changees(version, captures, connaissance=connaissance),
                "annulation": courant["annule"],
                "historique": [
                    {"version": v["version"], "recu_a": v["recu_a"], "motif_revision": v["motif_revision"]}
                    for v in courant["versions"]
                ],
            }
        )
    return {"type": "PLANS_M9", "connaissance": connaissance, "jour": jour, "plans": sortie, "limites": list(_LIMITES)}
