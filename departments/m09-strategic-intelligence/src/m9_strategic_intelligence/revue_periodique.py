"""Revues périodiques M9.6–7 : rapport hebdomadaire, revues mensuelle et trimestrielle, publiées en versions immuables.

Module pur. Une revue est une fonction DÉTERMINISTE de ce que M9 connaît : les captures de producteurs (M9.1) reçues
jusqu'à
l'instant de connaissance, les sessions de conseil (M9.4) et leurs issues. Elle ne reconstruit jamais le passé : elle
dit ce
que M9 savait ou avait reçu, quand, et ce qui manquait ; une capture arrivée après la clôture de la période n'entre pas
dans la
revue publiée à l'époque, et une nouvelle publication de la MÊME période est une nouvelle version qui conserve
l'ancienne.

Bases temporelles — jamais confondues : la PÉRIODE est un intervalle ``[début, fin)`` en heure locale du fuseau demandé
(minuit local, heure d'été comprise) ; les captures sont rattachées par leur RÉCEPTION (``recu_a``), les sessions par
leur
ouverture ; l'instant métier déclaré par un producteur n'est cité que pour dire si son étendue chevauche la période.

Les « tendances » comparent ce que M9 sait à la période précédente de même granularité (captures reçues, sessions,
couverture,
contradictions) : des tendances de la CONNAISSANCE de M9, jamais des tendances de l'entreprise, que seuls les
producteurs
mesurent. Aucune quantité n'est calculée ici : les nombres rendus sont des dénombrements.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import capture_strategique as cs
from . import catalogue_producteurs as cat
from . import rapport_direction

VERSION = "2026-10-28.1"
GRANULARITES = ("hebdomadaire", "mensuelle", "trimestrielle")
MAX_CAPTURES_PERIODE = 2000
_LIMITES = (
    "Revue de la CONNAISSANCE de M9 : captures reçues et sessions ouvertes dans la période, couverture et manques ; "
    "aucune mesure d'entreprise n'est calculée ici.",
    "Une arrivée tardive n'est pas réécrite : elle entre dans la version suivante de la même période, jamais dans "
    "l'ancienne.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _fuseau(nom: object) -> ZoneInfo:
    try:
        if type(nom) is not str or not nom or len(nom) > 64:
            raise ZoneInfoNotFoundError
        return ZoneInfo(nom)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise _refus("REJ-REVUE-FUSEAU", "fuseau IANA connu requis (ex. America/Toronto)") from exc


def _utc(jour: date, fuseau: ZoneInfo) -> datetime:
    return datetime(jour.year, jour.month, jour.day, tzinfo=fuseau).astimezone(UTC)  # minuit local


def bornes(granularite: str, ancre: str, fuseau: str) -> dict:
    """Période ``[début, fin)`` de la date locale ``ancre`` : semaine ISO (lundi), mois ou trimestre civils."""
    if granularite not in GRANULARITES:
        raise _refus("REJ-REVUE-GRANULARITE", f"granularité parmi {GRANULARITES}")
    zone = _fuseau(fuseau)
    try:
        jour = date.fromisoformat(ancre)
    except (TypeError, ValueError) as exc:
        raise _refus("REJ-REVUE-ANCRE", "date locale AAAA-MM-JJ requise") from exc
    if len(ancre) != 10:
        raise _refus("REJ-REVUE-ANCRE", "date locale AAAA-MM-JJ requise")
    if granularite == "hebdomadaire":
        debut = jour - timedelta(days=jour.weekday())
        fin = debut + timedelta(days=7)
    elif granularite == "mensuelle":
        debut = jour.replace(day=1)
        fin = (debut + timedelta(days=32)).replace(day=1)
    else:
        mois = 3 * ((jour.month - 1) // 3) + 1
        debut = date(jour.year, mois, 1)
        fin = date(jour.year + (mois == 10), 1 if mois == 10 else mois + 3, 1)
    return {
        "granularite": granularite,
        "fuseau": fuseau,
        "debut_local": debut.isoformat(),
        "fin_local": fin.isoformat(),
        "debut": _utc(debut, zone).isoformat().replace("+00:00", "Z"),
        "fin": _utc(fin, zone).isoformat().replace("+00:00", "Z"),
    }


def precedente(periode: Mapping) -> dict:
    """Période de même granularité qui précède immédiatement ``periode``."""
    veille = date.fromisoformat(periode["debut_local"]) - timedelta(days=1)
    return bornes(periode["granularite"], veille.isoformat(), periode["fuseau"])


def _dans(valeur: str, periode: Mapping) -> bool:
    instant = cs.instant(valeur)
    return instant is not None and cs.instant(periode["debut"]) <= instant < cs.instant(periode["fin"])  # type: ignore[operator]


def _chevauche(capture: Mapping, periode: Mapping) -> str:
    temps = capture["instants_metier"]
    if not temps["declares"] or temps["min"] is None:
        return "NON_DECLARE"
    debut, fin = cs.instant(periode["debut"]), cs.instant(periode["fin"])
    bas, haut = cs.instant(temps["min"]), cs.instant(temps["max"])
    return "OUI" if bas < fin and haut >= debut else "NON"  # type: ignore[operator]


def _resume_periode(
    captures: Sequence[Mapping], sessions: Sequence[Mapping], periode: Mapping, connaissance: str
) -> dict:
    recues = [c for c in captures if _dans(c["recu_a"], periode)]
    if len(recues) > MAX_CAPTURES_PERIODE:
        raise _refus(
            "REJ-REVUE-BORNE",
            f"plus de {MAX_CAPTURES_PERIODE} captures dans la période : publier par période plus courte",
        )
    ouvertes = [e for e in sessions if e["type"] == "OUVERTURE" and _dans(e["recu_a"], periode)]
    closes = [e for e in sessions if e["type"] == "CLOTURE" and _dans(e["recu_a"], periode)]
    couverture = cs.evaluer_couverture(
        captures,
        reference=periode["fin"],
        connaissance=connaissance,
        attendues=[lecture.id for lecture in cat.LECTURES],
    )
    statuts: dict[str, int] = {}
    for entree in couverture["lectures"]:
        statuts[entree["statut"]] = statuts.get(entree["statut"], 0) + 1
    return {
        "captures_recues": len(recues),
        "refusees_ou_en_erreur": sum(1 for c in recues if c["verdict"] != "ACCEPTEE"),
        "partielles": sum(1 for c in recues if c["verdict"] == "ACCEPTEE" and not c["complete"]),
        "sessions_ouvertes": len(ouvertes),
        "sessions_closes": len(closes),
        "recommandations": sum(1 for e in closes if e["issue"] == "RECOMMANDATION"),
        "abstentions": sum(1 for e in closes if e["issue"] == "ABSTENTION"),
        "contradictions": len(couverture["contradictions"]),
        "lectures_non_presentes": len(couverture["lectures_non_presentes"]),
        "statuts_couverture": dict(sorted(statuts.items())),
    }


def composer(
    captures: Sequence[Mapping],
    sessions: Sequence[Mapping],
    *,
    granularite: str,
    ancre: str,
    fuseau: str,
    connaissance: str,
    plans: Sequence[Mapping] = (),
    actions: Sequence[Mapping] = (),
    experiences: Sequence[Mapping] = (),
) -> dict:
    """Revue de la période contenant ``ancre``, telle que M9 la connaît à ``connaissance`` (réception ≤).

    ``connaissance`` ne peut pas précéder la fin de la période : une revue publiée avant la fin n'est pas une revue de
    la période."""
    periode = bornes(granularite, ancre, fuseau)
    connu = cs.instant(connaissance)
    if connu is None:
        raise _refus("REJ-REVUE-TEMPS", "instant de connaissance avec fuseau explicite requis")
    if connu < cs.instant(periode["fin"]):  # type: ignore[operator]
        raise _refus(
            "REJ-REVUE-PRECOCE", "la connaissance précède la fin de la période : la revue n'est pas encore une revue"
        )
    # La revue d'une période décrit ce que M9 avait reçu À SA FIN : stable pour toujours. Ce qui arrive ensuite et
    # concerne la
    # période (étendue métier déclarée qui la chevauche) figure à part, comme arrivée tardive, et fait une version
    # suivante.
    fin = periode["fin"]
    visibles = cs.connues_a(captures, fin)
    sessions_connues = [e for e in sessions if cs.instant(e["recu_a"]) <= cs.instant(fin)]  # type: ignore[operator]
    tardives = [
        c
        for c in captures
        if cs.instant(fin) < cs.instant(c["recu_a"]) <= connu and _chevauche(c, periode) == "OUI"  # type: ignore[operator]
    ]
    precedent = precedente(periode)
    courante = _resume_periode(visibles, sessions_connues, periode, fin)
    ancienne = _resume_periode(visibles, sessions_connues, precedent, fin)
    tendances = {
        cle: {"precedente": ancienne[cle], "courante": courante[cle], "ecart": courante[cle] - ancienne[cle]}
        for cle in (
            "captures_recues",
            "refusees_ou_en_erreur",
            "sessions_ouvertes",
            "sessions_closes",
            "contradictions",
            "lectures_non_presentes",
        )
    }
    couverture = cs.evaluer_couverture(
        visibles,
        reference=fin,
        connaissance=fin,
        attendues=[lecture.id for lecture in cat.LECTURES],
    )
    captures_periode = [
        {
            "lecture_id": c["lecture_id"],
            "index": c["index"],
            "hash_maillon": c["hash_maillon"],
            "recu_a": c["recu_a"],
            "verdict": c["verdict"],
            "complete": c["complete"],
            "etendue_metier_chevauche": _chevauche(c, periode),
        }
        for c in visibles
        if _dans(c["recu_a"], periode)
    ]
    decisions = [
        {
            "session_id": e["session_id"],
            "rapport_id": e["rapport_id"],
            "issue": e["issue"],
            "recu_a": e["recu_a"],
            "actions_sensibles": sum(
                1 for a in (e["gouvernance"] or {}).get("actions", []) if a["verdict"] == "VALIDATION_HUMAINE_REQUISE"
            ),
        }
        for e in sessions_connues
        if e["type"] == "CLOTURE" and _dans(e["recu_a"], periode)
    ]
    revue = {
        "type": "REVUE_PERIODIQUE",
        "version_contrat": VERSION,
        "periode": periode,
        "connaissance": connaissance,
        "bases_temporelles": {
            "periode": "intervalle [début, fin) en heure locale du fuseau demandé",
            "captures": "rattachées par l'instant de RÉCEPTION par M9, jusqu'à la fin de la période",
            "arrivees_tardives": "reçues après la fin, dont l'étendue métier déclarée chevauche la période",
            "metier": "étendue déclarée par le producteur, citée seulement pour son chevauchement",
        },
        "synthese": courante,
        "tendances_de_la_connaissance": tendances,
        "couverture": {
            "complete": couverture["complete"],
            "lectures": [
                {k: e[k] for k in ("lecture_id", "statut") if k in e} | ({"age_s": e["age_s"]} if "age_s" in e else {})
                for e in couverture["lectures"]
            ],
        },
        "contradictions": couverture["contradictions"],
        "captures_de_la_periode": captures_periode,
        "arrivees_tardives": [
            {
                "lecture_id": c["lecture_id"],
                "index": c["index"],
                "hash_maillon": c["hash_maillon"],
                "recu_a": c["recu_a"],
            }
            for c in tardives
        ],
        "decisions": decisions,
        "sections_direction": rapport_direction.sections(
            captures=captures, sessions=sessions, plans=plans, actions=actions, experiences=experiences, periode=periode
        ),
        "tete_captures": visibles[-1]["hash_maillon"] if visibles else cs.HASH_INITIAL,
        "limites": list(_LIMITES),
    }
    revue["revue_id"] = identifiant(revue)
    return revue


def identifiant(revue: Mapping) -> str:
    """Empreinte du CONTENU de la revue. L'instant de connaissance n'y entre pas : deux publications faites à des
    heures différentes, sans rien de nouveau connu, ont le même contenu (rejeu) ; il reste dans la revue, pour la
    preuve."""
    contenu = {k: v for k, v in revue.items() if k not in ("revue_id", "connaissance")}
    return hashlib.sha256(json.dumps(contenu, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


# ---------------------------------------------------------------------------------------------------- publications
SCHEMA_PUBLICATION = "opsys.m9.publication_revue/v1"


def _cle(revue: Mapping) -> tuple[str, str, str]:
    periode = revue["periode"]
    return periode["granularite"], periode["fuseau"], periode["debut"]


def _empreinte(valeur: object) -> str:
    return hashlib.sha256(json.dumps(valeur, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def valider_chaine(publications: Sequence[Mapping]) -> tuple[bool, str]:
    precedent = ""
    for rang, p in enumerate(publications):
        try:
            if (
                p["schema"] != SCHEMA_PUBLICATION
                or p["index"] != rang
                or p["hash_precedent"] != precedent
                or p["hash_maillon"] != _empreinte({k: v for k, v in p.items() if k != "hash_maillon"})
                or p["revue"]["revue_id"] != identifiant(p["revue"])
            ):
                return False, f"publication invalide à l'index {rang}"
        except (KeyError, TypeError):
            return False, f"publication invalide à l'index {rang}"
        precedent = p["hash_maillon"]
    return True, ""


def publier(publications: Sequence[Mapping], revue: Mapping, *, publie_a: str) -> dict | None:
    """Publication à ajouter, ou ``None`` si la dernière version de cette période a exactement ce contenu (rejeu).

    Une version suivante cite la précédente et les captures arrivées depuis : l'ancienne reste intacte."""
    if cs.instant(publie_a) is None or cs.instant(publie_a) < cs.instant(revue["connaissance"]):  # type: ignore[operator]
        raise _refus("REJ-REVUE-TEMPS", "publication datée avec fuseau explicite, jamais avant la connaissance")
    cle = _cle(revue)
    siennes = [p for p in publications if _cle(p["revue"]) == cle]
    if siennes and siennes[-1]["revue"]["revue_id"] == revue["revue_id"]:
        return None
    precedente_pub = siennes[-1] if siennes else None
    corps = {
        "schema": SCHEMA_PUBLICATION,
        "index": len(publications),
        "hash_precedent": publications[-1]["hash_maillon"] if publications else "",
        "version": len(siennes) + 1,
        "remplace_version": precedente_pub["version"] if precedente_pub else None,
        "publie_a": publie_a,
        "arrivees_tardives_ajoutees": (
            len(
                {c["hash_maillon"] for c in revue["arrivees_tardives"]}
                - {c["hash_maillon"] for c in precedente_pub["revue"]["arrivees_tardives"]}
            )
            if precedente_pub
            else None
        ),
        "revue": dict(revue),
    }
    corps["hash_maillon"] = _empreinte(corps)
    return corps
