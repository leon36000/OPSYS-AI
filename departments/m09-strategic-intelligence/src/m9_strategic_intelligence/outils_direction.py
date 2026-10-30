"""Outils M9.5–7 : salle de guerre quotidienne et revues périodiques publiées en versions immuables.

Adaptateur seul : ``revue_periodique`` (module pur) compose et versionne ; ce fichier lit les registres (captures,
sessions,
publications), exige l'admin authentifié (console ou appareil) et borne les sorties. Aucune lecture ne recalcule un
producteur ;
aucune publication n'écrit hors du registre ``publications_revue`` (T1/N2, effet interne seulement).

La salle de guerre est une LECTURE : elle ne planifie, n'exécute et ne décide rien. Sa ``vue`` est l'empreinte de tout
ce qu'elle
montre ; une reprise avec une vue périmée est refusée (jamais une page de l'ancien monde posée sur le nouveau).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import catalogue_producteurs as cat
from . import experiences as exp_module
from . import orchestrateur, revue_periodique, sessions_conseil
from . import plans as plans_module
from . import risques as rk
from .outils_tissu import DEPARTEMENT, MAX_PAGE_OCTETS, borner, exiger_admin_strict

REGISTRE_PUBLICATIONS = "publications_revue"
REGISTRE_CAPTURES = "captures_strategiques"
REGISTRE_SESSIONS = "sessions_conseil"
REGISTRE_PLANS = "plans"
REGISTRE_ACTIONS = "actions"
REGISTRE_EXPERIENCES = "experiences"
MAX_ITEMS_SALLE = 5
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _empreinte(valeur: object) -> str:
    return hashlib.sha256(json.dumps(valeur, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def construire_outils(
    *,
    budget_sortie: int,
    sources_briefing: Callable[[], tuple[list[dict], list[dict], list[dict]]],
    fenetre_alertes_jours: Callable[[], int],
    captures_cible: Any = None,
    sessions_cible: Any = None,
    publications_cible: Any = None,
    plans_cible: Any = None,
    actions_cible: Any = None,
    experiences_cible: Any = None,
) -> tuple[Outil, ...]:
    def lire(cible: Any, registre: str) -> Any:
        return cible if cible is not None else stockage.maillons(DEPARTEMENT, registre)

    def captures() -> list[dict]:
        chaine = list(lire(captures_cible, REGISTRE_CAPTURES))
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        return chaine

    def sessions() -> list[dict]:
        evenements = list(lire(sessions_cible, REGISTRE_SESSIONS))
        ok, raison = sessions_conseil.valider_chaine(evenements)
        if not ok:
            raise _refus("REJ-SESSION-CHAINE-INVALIDE", f"registre des sessions invalide ({raison})")
        return evenements

    def registre_verifie(cible: Any, registre: str, validateur: Callable, code: str) -> list[dict]:
        liste = list(lire(cible, registre))
        ok, raison = validateur(liste)
        if not ok:
            raise _refus(code, f"registre « {registre} » invalide ({raison})")
        return liste

    def publications() -> list[dict]:
        liste = list(lire(publications_cible, REGISTRE_PUBLICATIONS))
        ok, raison = revue_periodique.valider_chaine(liste)
        if not ok:
            raise _refus("REJ-REVUE-CHAINE-INVALIDE", f"registre des publications invalide ({raison})")
        return liste

    def tranche(objet: object, depart: int, longueur: int) -> dict:
        if type(depart) is not int or depart < 0 or type(longueur) is not int or not 1 <= longueur <= MAX_PAGE_OCTETS:
            raise _refus("REJ-TISSU-DEPART", "départ et longueur bornés requis")
        texte = cs.canonique(objet)
        if depart > len(texte):
            raise _refus("REJ-TISSU-DEPART", "départ au-delà du contenu")
        fin = min(len(texte), depart + longueur)
        return {
            "taille": len(texte),
            "depart": depart,
            "contenu_json": texte[depart:fin],
            "prochain_depart": fin if fin < len(texte) else None,
            "sha256": _empreinte(objet),
        }

    def resume(revue: Mapping) -> dict:
        return {
            "revue_id": revue["revue_id"],
            "periode": revue["periode"],
            "connaissance": revue["connaissance"],
            "synthese": revue["synthese"],
            "couverture_complete": revue["couverture"]["complete"],
            "contradictions": len(revue["contradictions"]),
            "decisions": len(revue["decisions"]),
            "captures_de_la_periode": len(revue["captures_de_la_periode"]),
            "sections_direction": {
                s: sum(1 for x in revue["sections_direction"]["sections"].values() if x["statut"] == s)
                for s in ("RENSEIGNEE", "PARTIELLE", "NON_DISPONIBLE")
            },
        }

    def composer(granularite: str, ancre: str, fuseau: str, connaissance: str) -> dict:
        return revue_periodique.composer(
            captures(),
            sessions(),
            granularite=granularite,
            ancre=ancre,
            fuseau=fuseau,
            connaissance=connaissance,
            plans=registre_verifie(
                plans_cible, REGISTRE_PLANS, plans_module.valider_chaine, "REJ-PLAN-CHAINE-INVALIDE"
            ),
            actions=registre_verifie(
                actions_cible, REGISTRE_ACTIONS, orchestrateur.valider_chaine, "REJ-ACTION-CHAINE-INVALIDE"
            ),
            experiences=registre_verifie(
                experiences_cible, REGISTRE_EXPERIENCES, exp_module.valider_chaine, "REJ-EXPERIENCE-CHAINE-INVALIDE"
            ),
        )

    def apercu_revue(
        granularite: str, ancre: str, fuseau: str, connaissance: str, depart: int = 0, longueur: int = MAX_PAGE_OCTETS
    ) -> dict[str, Any]:
        exiger_admin_strict()
        revue = composer(granularite, ancre, fuseau, connaissance)
        return borner(
            {"accepte": True, "type": "APERCU_REVUE", **resume(revue), **tranche(revue, depart, longueur)},
            budget_sortie,
        )

    def publier_revue(granularite: str, ancre: str, fuseau: str, horodatage: str) -> dict[str, Any]:
        exiger_admin_strict()
        revue = composer(granularite, ancre, fuseau, horodatage)
        existantes = publications()
        publication = revue_periodique.publier(existantes, revue, publie_a=horodatage)
        if publication is not None:
            lire(publications_cible, REGISTRE_PUBLICATIONS).append(publication, rang_attendu=publication["index"])
        courante = (
            publication
            if publication is not None
            else next(p for p in reversed(existantes) if p["revue"]["revue_id"] == revue["revue_id"])
        )
        return borner(
            {
                "accepte": True,
                "rejoue": publication is None,
                "index": courante["index"],
                "version": courante["version"],
                "remplace_version": courante["remplace_version"],
                "arrivees_tardives_ajoutees": courante["arrivees_tardives_ajoutees"],
                **resume(courante["revue"]),
            },
            budget_sortie,
        )

    def lister_revues(depart: int = 0, granularite: str | None = None, vue: str | None = None) -> dict[str, Any]:
        exiger_admin_strict()
        if granularite is not None and granularite not in revue_periodique.GRANULARITES:
            raise _refus("REJ-REVUE-GRANULARITE", "granularité inconnue")
        liste = publications()
        tete = liste[-1]["hash_maillon"] if liste else ""
        if vue is not None and vue != tete:
            raise _refus("REJ-VUE-PERIMEE", "le registre des publications a changé : reprendre à 0")
        retenues = [
            p for p in reversed(liste) if granularite is None or p["revue"]["periode"]["granularite"] == granularite
        ]
        if type(depart) is not int or not 0 <= depart <= len(retenues):
            raise _refus("REJ-TISSU-DEPART", "départ entre 0 et le total requis ; reprendre à 0")
        page: list[dict] = []
        for p in retenues[depart:]:
            ligne = {"index": p["index"], "version": p["version"], "publie_a": p["publie_a"], **resume(p["revue"])}
            if len(cs.canonique([*page, ligne])) > budget_sortie - 600:
                break
            page.append(ligne)
        if retenues[depart:] and not page:
            raise _refus("REJ-TISSU-BORNE", "une ligne dépasse la borne")
        suivant = depart + len(page)
        return {
            "accepte": True,
            "type": "REVUES_PUBLIEES",
            "revues": page,
            "total": len(retenues),
            "depart": depart,
            "prochain_depart": suivant if suivant < len(retenues) else None,
            "vue": tete,
            "ordre": "la plus récente d'abord",
        }

    def lire_revue(index: int, depart: int = 0, longueur: int = MAX_PAGE_OCTETS) -> dict[str, Any]:
        exiger_admin_strict()
        liste = publications()
        if type(index) is not int or not 0 <= index < len(liste):
            raise _refus("REJ-TISSU-INDEX", "rang de publication inconnu")
        publication = liste[index]
        entete = {k: publication[k] for k in ("index", "version", "remplace_version", "publie_a", "hash_maillon")}
        return borner({"accepte": True, **entete, **tranche(publication["revue"], depart, longueur)}, budget_sortie)

    def salle_de_guerre(reference: str, vue_attendue: str | None = None) -> dict[str, Any]:
        exiger_admin_strict()
        if cs.instant(reference) is None:
            raise _refus("REJ-CAPTURE-TEMPS", "référence avec fuseau explicite requise")
        chaine, evenements = captures(), sessions()
        decisions, alertes, _ = sources_briefing()
        couverture = cs.evaluer_couverture(
            chaine, reference=reference, connaissance=reference, attendues=[lecture.id for lecture in cat.LECTURES]
        )
        ouvertes, closes = {}, []
        for evenement in evenements:
            if evenement["type"] == "OUVERTURE":
                ouvertes[evenement["session_id"]] = evenement
            elif evenement["type"] == "CLOTURE":
                closes.append(evenement)
        cloturees = {e["session_id"] for e in closes}
        en_cours = []
        for session_id in sorted(set(ouvertes) - cloturees):
            projection = sessions_conseil.etat(evenements, session_id)
            en_cours.append(
                {
                    "session_id": session_id,
                    "question": projection["question"],
                    "en_attente": [t["role"] for t in projection["tours"] if t["statut"] == "EN_ATTENTE"],
                    "echecs": [t["role"] for t in projection["tours"] if t["statut"] == "ECHEC"],
                }
            )
        a_valider = [
            {
                "session_id": e["session_id"],
                "rapport_id": e["rapport_id"],
                "actions": [
                    a["action"]
                    for a in (e["gouvernance"] or {}).get("actions", [])
                    if a["verdict"] == "VALIDATION_HUMAINE_REQUISE"
                ],
            }
            for e in closes
            if e["issue"] == "RECOMMANDATION"
        ]
        a_valider = [e for e in a_valider if e["actions"]][-MAX_ITEMS_SALLE:]
        fenetre = fenetre_alertes_jours()
        limite = cs.instant(reference)
        alertes_proches = [
            a
            for a in alertes
            if (instant := cs.instant(str(a.get("horodatage_reference", "")))) is not None
            and 0 <= (limite - instant).total_seconds() <= (fenetre + 1) * 86400  # type: ignore[operator]
        ]
        radar = rk.evaluer(chaine, connaissance=reference)
        veille = rk.delta(chaine, connaissance=reference)
        maintenant = cs.instant(reference)
        nouvelles = sum(
            1
            for c in chaine
            if (recu := cs.instant(c["recu_a"])) is not None and 0 < (maintenant - recu).total_seconds() <= 86400  # type: ignore[operator]
        )
        presents = [r for r in radar["risques"] if r["statut"] != "LEVE"]
        contenu = {
            "type": "SALLE_DE_GUERRE",
            "reference": reference,
            "risques": {
                "actifs": sum(1 for r in presents if r["statut"] == "ACTIF"),
                "a_reconfirmer": sum(1 for r in presents if r["statut"] == "A_RECONFIRMER"),
                "leves": sum(1 for r in radar["risques"] if r["statut"] == "LEVE"),
                "regles_non_evaluees": len(radar["regles_non_evaluees"]),
                "premiers": [
                    {k: r[k] for k in ("regle", "sujet", "gravite", "statut")} for r in presents[:MAX_ITEMS_SALLE]
                ],
                "detail": "m9_radar_risques",
                "grille": radar["grille"]["statut"],
            },
            "changements_depuis_la_veille": {
                "connaissance_precedente": veille["connaissance_precedente"],
                "risques_apparus": veille["apparus"][:MAX_ITEMS_SALLE],
                "risques_apparus_total": len(veille["apparus"]),
                "risques_leves": veille["leves"][:MAX_ITEMS_SALLE],
                "risques_leves_total": len(veille["leves"]),
                "gravite_changee": veille["gravite_changee"][:MAX_ITEMS_SALLE],
                "captures_nouvelles": nouvelles,
            },
            "decisions_en_attente": {
                "total": len(decisions),
                "premieres": [
                    {k: d.get(k) for k in ("type", "id", "resume", "niveau", "depuis", "action_proposee")}
                    for d in decisions[:MAX_ITEMS_SALLE]
                ],
                "reste": max(0, len(decisions) - MAX_ITEMS_SALLE),
            },
            "alertes_m8": {
                "total": len(alertes_proches),
                "fenetre_jours": fenetre,
                "reste_a_lire": "m9_lire_alertes_m8",
            },
            "couverture": {
                "complete": couverture["complete"],
                "lectures_non_presentes": couverture["lectures_non_presentes"],
                "statuts": {
                    s: sum(1 for e in couverture["lectures"] if e["statut"] == s)
                    for s in sorted({e["statut"] for e in couverture["lectures"]})
                },
            },
            "contradictions": len(couverture["contradictions"]),
            "conseils_en_cours": en_cours[:MAX_ITEMS_SALLE],
            "conseils_en_cours_total": len(en_cours),
            "recommandations_a_valider_par_un_humain": a_valider,
            "manques": [
                {"lecture_id": e["lecture_id"], "statut": e["statut"], "manque": e.get("manque")}
                for e in couverture["lectures"]
                if e["statut"] != "PRESENTE"
            ],
            "responsabilites": "M9 propose ; toute décision sensible reste au propriétaire ; aucun effet ici",
            "limites": [
                "Lecture seule : aucune planification, aucun effet, aucune décision n'est créée par cette vue."
            ],
        }
        vue = _empreinte(
            {k: v for k, v in contenu.items() if k != "reference"}
            | {
                "tete_captures": chaine[-1]["hash_maillon"] if chaine else "",
                "tete_sessions": evenements[-1]["hash_maillon"] if evenements else "",
            }
        )
        if vue_attendue is not None and vue_attendue != vue:
            raise _refus("REJ-VUE-PERIMEE", "la salle de guerre a changé depuis la vue donnée : relire sans vue")
        contenu["vue"] = vue
        return borner({"accepte": True, **contenu}, budget_sortie)

    admin = frozenset({"admin"})
    tranche_p = {
        "depart": {"type": "integer", "minimum": 0},
        "longueur": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_OCTETS},
    }
    periode_p = {
        "granularite": {"type": "string", "enum": list(revue_periodique.GRANULARITES)},
        "ancre": {"type": "string", "description": "Date locale AAAA-MM-JJ dans la période voulue."},
        "fuseau": {"type": "string", "maxLength": 64, "description": "Fuseau IANA, ex. America/Toronto."},
    }

    def outil(nom, description, proprietes, requis, fonction, *, ecriture=False):
        return Outil(
            nom=nom,
            description=description,
            parametres={"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False},
            fonction=fonction,
            autonomie=Autonomie.T1 if ecriture else Autonomie.T0,
            niveau=Niveau.N2 if ecriture else Niveau.N0,
            roles_appareil=admin,
        )

    return (
        outil(
            "m9_salle_de_guerre",
            "Vue quotidienne en lecture seule : décisions en attente, alertes M8, couverture et manques, "
            "contradictions, conseils "
            "en cours et recommandations à valider par un humain. Rend une `vue` : une reprise avec une vue périmée "
            "est refusée.",
            {"reference": _INSTANT, "vue_attendue": {"type": "string", "maxLength": 64}},
            ["reference"],
            salle_de_guerre,
        ),
        outil(
            "m9_apercu_revue",
            "Compose sans rien écrire la revue hebdomadaire, mensuelle ou trimestrielle d'une période (heure locale "
            "du fuseau), telle "
            "que M9 la connaît à l'instant de connaissance (jamais avant la fin de la période), par tranches bornées.",
            {**periode_p, "connaissance": _INSTANT, **tranche_p},
            ["granularite", "ancre", "fuseau", "connaissance"],
            apercu_revue,
        ),
        outil(
            "m9_publier_revue",
            "Publie la revue d'une période en version immuable : mêmes entrées, même version (rejeu) ; une arrivée "
            "tardive ajoute une "
            "version suivante qui cite la précédente. Effet interne seulement.",
            {**periode_p, "horodatage": _INSTANT},
            ["granularite", "ancre", "fuseau", "horodatage"],
            publier_revue,
            ecriture=True,
        ),
        outil(
            "m9_lister_revues",
            "Liste par pages bornées les revues publiées (la plus récente d'abord), avec la vue du registre.",
            {
                "depart": {"type": "integer", "minimum": 0},
                "granularite": {"type": "string", "enum": list(revue_periodique.GRANULARITES)},
                "vue": {"type": "string", "maxLength": 64},
            },
            [],
            lister_revues,
        ),
        outil(
            "m9_lire_revue",
            "Relit, par tranches bornées, le JSON canonique exact d'une revue publiée (aucune troncature : suivre "
            "prochain_depart).",
            {"index": {"type": "integer", "minimum": 0}, **tranche_p},
            ["index"],
            lire_revue,
        ),
    )
