"""Rappels et rendez-vous via la cédule de M4 (M1.9) : la logique pure.

M1 ne donne et ne confirme jamais une date (règle dure du produit) : la date d'un rendez-vous est celle que M4 a
DATÉE et qu'un admin a confirmée dans la cédule. M1 fait trois choses :

1. **Proposer des fenêtres** : à partir de la capacité M4 de semaines candidates (contrat `m4.capacite_equipe` v1, lu
   par le port de M1), il calcule, en minutes entières et sans aucune devinette, les minutes d'équipe libres de
   chaque semaine, moins ce que M1 a déjà RETENU (conflit), et dit quelles semaines peuvent accueillir la durée
   demandée. Une semaine non calculable côté M4 reste « non calculable, manque X » : jamais zéro, jamais une valeur
   par défaut. La granularité est la SEMAINE : M4 n'expose pas de créneau libre à l'heure près, donc M1 n'en invente
   aucun. 2. **Retenir** une fenêtre (soft hold interne, durée de vie bornée, jamais communiquée au client comme ferme).
3. **Confirmer** : seulement une PERSONNE (admin), seulement si la cédule de M4 contient réellement, pour l'intervention
   nommée, un créneau daté et valide (`date_confirmee`, intervention `planifiee`) ; l'heure du rendez-vous est lue de
   M4, jamais fournie par M1 ni par l'agent. Sans ce créneau : aucune confirmation, aucun message de confirmation.

Module pur : aucune horloge (l'instant est fourni), aucune entrée-sortie.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

MOTIFS = ("visite_evaluation", "rendez_vous_chantier", "rappel_telephonique")
DUREE_MIN, DUREE_MAX = 15, 1440
SEMAINES_MAX = 4
HORIZON_JOURS = 120
RETENUE_HEURES = 48
RETENUE_MAX_HEURES = 168
ECHEANCES_RAPPEL_MIN = (2880, 1440, 120)  # 48 h, 24 h et 2 h avant
TYPE_PROPOSE = "rdv_propose"
TYPE_RETENU = "rdv_retenu"
TYPE_CONFIRME = "rdv_confirme"
TYPE_ANNULE = "rdv_annule"
TYPE_MESSAGE = "rdv_message_prepare"
ETATS = ("proposee", "retenue", "confirmee", "annulee", "expiree", "passee")


class RefusRdv(ValueError):
    """Refus typé `REJ-M1-RDV-…` : le message commence par le code."""


def _t(v: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(v)
    if d.tzinfo is None:
        raise RefusRdv("REJ-M1-RDV-HORODATAGE: instant avec fuseau requis")
    return d


def identifiant_rdv(cle: str) -> str:
    return "rdv-" + hashlib.sha256(("m1-rdv|" + cle).encode()).hexdigest()[:16]


def valider_semaines(semaines: Sequence[str], maintenant: str) -> list[str]:
    """1 à 4 lundis ISO distincts, ni passés (avant la semaine courante) ni au-delà de l'horizon."""
    if not isinstance(semaines, (list, tuple)) or not 1 <= len(semaines) <= SEMAINES_MAX:
        raise RefusRdv(f"REJ-M1-RDV-SEMAINES: 1 à {SEMAINES_MAX} semaines (lundis AAAA-MM-JJ)")
    now = _t(maintenant).date()
    debut_courante = now - dt.timedelta(days=now.weekday())
    res: list[str] = []
    for s in semaines:
        try:
            d = dt.date.fromisoformat(s)
        except (TypeError, ValueError):
            raise RefusRdv(f"REJ-M1-RDV-SEMAINES: date invalide {s!r}") from None
        if d.weekday() != 0:
            raise RefusRdv(f"REJ-M1-RDV-SEMAINES: {s} n'est pas un lundi")
        if d < debut_courante or d > now + dt.timedelta(days=HORIZON_JOURS):
            raise RefusRdv(f"REJ-M1-RDV-SEMAINES: {s} hors de l'horizon (semaine courante à {HORIZON_JOURS} jours)")
        if s in res:
            raise RefusRdv(f"REJ-M1-RDV-SEMAINES: semaine en double {s}")
        res.append(s)
    return res


def verifier_capacite(charge: Mapping[str, Any], semaine: str) -> None:
    """Contrôle de forme du contrat `m4.capacite_equipe` v1 avant tout calcul (fail-closed)."""
    if not isinstance(charge, Mapping) or charge.get("contrat") != "m4.capacite_equipe" or charge.get("version") != 1:
        raise RefusRdv("REJ-M1-RDV-CAPACITE: contrat m4.capacite_equipe v1 attendu")
    if charge.get("semaine_debut") != semaine:
        raise RefusRdv("REJ-M1-RDV-CAPACITE: la capacité lue ne porte pas sur la semaine demandée")
    if charge.get("unite") != "heures_declarees":
        raise RefusRdv("REJ-M1-RDV-CAPACITE: unité inattendue (heures_declarees requise) : aucune conversion")
    if charge.get("calculable") is not True:
        if not isinstance(charge.get("manque"), list) or not charge["manque"]:
            raise RefusRdv("REJ-M1-RDV-CAPACITE: une capacité non calculable doit nommer ce qui manque")
        return
    equipes = charge.get("equipes")
    if not isinstance(equipes, list) or not equipes:
        raise RefusRdv("REJ-M1-RDV-CAPACITE: capacité calculable sans équipe")
    for e in equipes:
        for cle in ("minutes_disponibles", "minutes_planifiees"):
            v = e.get(cle) if isinstance(e, Mapping) else None
            if type(v) is not int or v < 0:
                raise RefusRdv(f"REJ-M1-RDV-CAPACITE: {cle} entier positif ou nul requis par équipe")
        if not isinstance(e.get("equipe_id"), str) or not e["equipe_id"]:
            raise RefusRdv("REJ-M1-RDV-CAPACITE: equipe_id requis")


def minutes_retenues(
    lignes: Iterable[Mapping[str, Any]], semaine: str, maintenant: str, sauf: str | None = None
) -> int:
    """Minutes que M1 a déjà RETENUES (non expirées, non annulées, non confirmées-puis-annulées) pour cette semaine.
    Un rendez-vous CONFIRMÉ est déjà dans la cédule de M4 : il n'est pas compté deux fois."""
    total = 0
    for rdv_id, info in etats(lignes, maintenant).items():
        if rdv_id == sauf or info["etat"] != "retenue" or info["semaine"] != semaine:
            continue
        total += info["duree_minutes"]
    return total


def options(
    charges: Mapping[str, Mapping[str, Any]],
    duree: int,
    lignes: Iterable[Mapping[str, Any]],
    maintenant: str,
    sauf: str | None = None,
) -> list[dict[str, Any]]:
    """Une option par semaine : minutes libres de M4, minutes retenues par M1, verdict. Calcul entier."""
    lignes = list(lignes)
    res: list[dict[str, Any]] = []
    for semaine, charge in charges.items():
        verifier_capacite(charge, semaine)
        if charge["calculable"] is not True:
            res.append(
                {
                    "semaine": semaine,
                    "statut": "non_calculable",
                    "manque": list(charge["manque"])[:10],
                    "minutes_libres": None,
                    "minutes_retenues_m1": None,
                    "equipes_possibles": [],
                }
            )
            continue
        retenues = minutes_retenues(lignes, semaine, maintenant, sauf)
        libres_par_equipe = {
            e["equipe_id"]: e["minutes_disponibles"] - e["minutes_planifiees"] for e in charge["equipes"]
        }
        libres = sum(max(v, 0) for v in libres_par_equipe.values())
        possibles = sorted(k for k, v in libres_par_equipe.items() if v >= duree)
        net = libres - retenues
        res.append(
            {
                "semaine": semaine,
                "statut": "disponible" if net >= duree and possibles else "complet",
                "minutes_libres": libres,
                "minutes_retenues_m1": retenues,
                "minutes_nettes": net,
                "equipes_possibles": possibles,
                "duree_demandee": duree,
                "source": {
                    "profil_empreinte": (charge.get("sources") or {}).get("profil_empreinte"),
                    "registre_tete": (charge.get("sources") or {}).get("registre_tete"),
                },
            }
        )
    return res


def etats(lignes: Iterable[Mapping[str, Any]], maintenant: str) -> dict[str, dict[str, Any]]:
    """L'état de chaque rendez-vous, rejoué depuis le registre."""
    now = _t(maintenant)
    res: dict[str, dict[str, Any]] = {}
    for m in lignes:
        t, rid = m.get("type_entree"), m.get("rdv_id")
        if t == TYPE_PROPOSE:
            res[rid] = {
                "rdv_id": rid,
                "etat": "proposee",
                "motif": m["motif"],
                "duree_minutes": m["duree_minutes"],
                "semaine": None,
                "signal_id": m["signal_id"],
                "options": m["options"],
                "confirme": None,
                "retenue_expire_le": None,
                "messages": [],
            }
        elif rid in res:
            r = res[rid]
            if t == TYPE_RETENU and r["etat"] in ("proposee", "retenue", "expiree"):
                r.update(etat="retenue", semaine=m["semaine"], retenue_expire_le=m["expire_le"])
            elif t == TYPE_CONFIRME and r["etat"] == "retenue":
                r.update(etat="confirmee", confirme=m)
            elif t == TYPE_ANNULE and r["etat"] not in ("annulee",):
                r.update(etat="annulee", motif_annulation=m["motif"])
            elif t == TYPE_MESSAGE:
                r["messages"].append(m)
    for r in res.values():
        if r["etat"] == "retenue" and now > _t(r["retenue_expire_le"]):
            r["etat"] = "expiree"
        if r["etat"] == "confirmee" and now > _t(r["confirme"]["fin"]):
            r["etat"] = "passee"
    return res


def creneau_depuis_cedule(cedule: Mapping[str, Any], intervention_id: str, semaine: str, duree: int) -> dict[str, Any]:
    """Le créneau daté de M4 pour cette intervention, ou `RefusRdv`. La semaine lue est celle de la fenêtre retenue ; le
    créneau doit être `date_confirmee`, l'intervention `planifiee`, et durer au moins la durée demandée."""
    if not isinstance(cedule, Mapping) or cedule.get("debut_semaine") != semaine:
        raise RefusRdv("REJ-M1-RDV-CEDULE: la cédule lue ne porte pas sur la semaine retenue")
    lignes = [x for x in cedule.get("interventions", []) if x.get("intervention_id") == intervention_id]
    if not lignes:
        raise RefusRdv(
            "REJ-M1-RDV-CEDULE-ABSENTE: aucun créneau daté de la cédule M4 pour cette intervention dans cette "
            "semaine : rien n'est confirmé (M4 doit d'abord dater la cédule)"
        )
    ok = [x for x in lignes if x.get("validite") == "date_confirmee" and x.get("statut") == "planifiee"]
    if not ok:
        raise RefusRdv(
            "REJ-M1-RDV-CEDULE-A-RECONFIRMER: le créneau de M4 est à reconfirmer ou l'intervention n'est plus "
            "planifiée : rien n'est confirmé"
        )
    c = sorted(ok, key=lambda x: x["debut"])[0]
    minutes = int((_t(c["fin"]) - _t(c["debut"])).total_seconds() // 60)
    if minutes < duree:
        raise RefusRdv(f"REJ-M1-RDV-DUREE: le créneau de M4 dure {minutes} min, {duree} demandées")
    return {
        "intervention_id": intervention_id,
        "debut": c["debut"],
        "fin": c["fin"],
        "equipe_id": c.get("equipe_id"),
        "plan_id": c.get("plan_id"),
        "revision": c.get("revision"),
        "source_ligne_id": c.get("source_ligne_id"),
    }


def echeances_rappel(debut: str, maintenant: str, decalages: Sequence[int] = ECHEANCES_RAPPEL_MIN) -> list[str]:
    """Instants de rappel ISO (début moins le décalage), seulement ceux qui sont encore à venir."""
    now, d = _t(maintenant), _t(debut)
    res = []
    for m in sorted(set(decalages), reverse=True):
        if type(m) is not int or not 5 <= m <= 14 * 24 * 60:
            raise RefusRdv("REJ-M1-RDV-DECALAGE: décalage entier de 5 minutes à 14 jours")
        quand = d - dt.timedelta(minutes=m)
        if quand > now:
            res.append(quand.isoformat())
    return res


MOIS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def texte_date(instant: str) -> str:
    d = _t(instant)
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}"


def texte_heure(instant: str) -> str:
    d = _t(instant)
    return f"{d.hour} h {d.minute:02d}"
