"""Dates civiles explicites des plans appliqués M4 (CRM-01).

Pur : ni horloge ni SQL. L'adaptateur fournit l'admin authentifié et l'heure serveur.
La date confirme une planification interne, jamais un rendez-vous client ou un dispatch.
"""
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import cedule_tournees, etats

TYPE_DATEE = "cedule_datee"
FUSEAU = "America/Montreal"
AVERTISSEMENTS = [
    "Planification interne : confirmation client, météo et matériel non attestés par ces dates.",
    "Disponibilités externes et trajets entre plans distincts non vérifiés.",
    "Les créneaux à reconfirmer sont historiques et ne constituent pas une promesse.",
]


def _date(valeur):
    if not isinstance(valeur, str):
        raise ValueError("date ISO AAAA-MM-JJ requise")
    jour = date.fromisoformat(valeur)
    if not 1900 <= jour.year <= 2199 or jour.isoformat() != valeur:
        raise ValueError("date ISO AAAA-MM-JJ requise")
    return jour


def instant_local(jour, minute):
    """Refuse heures sautées ou répétées, jamais un choix implicite de fold."""
    if type(minute) is not int or not 0 <= minute <= 1440:
        raise ValueError("minute hors journée")
    local = datetime.combine(_date(jour), time.min) + timedelta(minutes=minute)
    zone = ZoneInfo(FUSEAU)
    candidats = {local.replace(tzinfo=zone, fold=f).astimezone(UTC) for f in (0, 1)
                 if local.replace(tzinfo=zone, fold=f).astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local}
    if len(candidats) != 1:
        raise ValueError("heure locale inexistante ou ambiguë au changement d'heure")
    return candidats.pop().astimezone(zone)


def _index(reg):
    reg.assert_chaine()
    maillons = reg.lire()
    propositions, applications, dates, detenteurs = {}, {}, {}, {}
    for rang, m in enumerate(maillons):
        typ = m["type_entree"]
        if typ == cedule_tournees.TYPE_PROPOSEE:
            propositions[m["plan_id"]] = m
        elif typ == cedule_tournees.TYPE_APPLIQUEE:
            applications[m["plan_id"]] = m
            for a in m["assignations"]:
                detenteurs[a["intervention_id"]] = m["plan_id"]
        elif typ == TYPE_DATEE:
            dates[m["plan_id"]] = (rang, m)
    etat = {i["intervention_id"]: i for i in etats.lister_interventions(reg)}
    return maillons, propositions, applications, dates, detenteurs, etat


def _visites(proposition):
    for route in proposition["sortie"]["plan"]:
        for visite in route["visites"]:
            yield route, visite


def _creneau(route, visite, calendrier):
    jour = calendrier[str(route["jour"])]
    debut = instant_local(jour, visite["debut_min"])
    fin = instant_local(jour, visite["fin_min"])
    duree = visite["fin_min"] - visite["debut_min"]
    if duree <= 0 or (fin.astimezone(UTC) - debut.astimezone(UTC)).total_seconds() != duree * 60:
        raise ValueError("durée du créneau altérée au changement d'heure")
    return debut.isoformat(), fin.isoformat()


def _projection(index):
    maillons, propositions, _, dates, detenteurs, etat = index
    lignes, sans_date = [], []
    for iid, info in sorted(etat.items()):
        plan = detenteurs.get(iid)
        proposition = propositions.get(plan)
        origine = dates.get(plan)
        if proposition is None or origine is None:
            if info["statut"] not in etats.ETATS_TERMINAUX:
                sans_date.append({"intervention_id": iid, "plan_id": plan,
                                  "statut": info["statut"], "raison": "aucune_date_civile_confirmee"})
            continue
        rang, source = origine
        for route, visite in _visites(proposition):
            if visite["chantier"] != iid:
                continue
            debut, fin = _creneau(route, visite, source["calendrier"])
            invalide = info["technicien_assigne"] != route["equipe"] or info["statut"] in {
                "reportee", "annulee", "a_planifier"}
            # Même si le chantier revient à planifiee, un report/réassignation ne ressuscite pas la date.
            invalide |= any(m.get("intervention_id") == iid and (
                m["type_entree"] == "assignation_technicien" or
                (m["type_entree"] == "transition_statut" and m["statut"] in {"reportee", "annulee"})
            ) for m in maillons[rang + 1:])
            lignes.append({"intervention_id": iid, "lead_id": info["lead_id"], "plan_id": plan,
                           "equipe_id": route["equipe"], "technicien_actuel": info["technicien_assigne"],
                           "debut": debut, "fin": fin, "statut": info["statut"],
                           "validite": "a_reconfirmer" if invalide else "date_confirmee",
                           "revision": source["revision"], "source_ligne_id": source["ligne_id"],
                           "source_application_id": source["source_application_id"],
                           "confirme_le": source["horodatage"]})
    return sorted(lignes, key=lambda ligne: (ligne["debut"], ligne["equipe_id"], ligne["intervention_id"])), sans_date


def confirmer(reg, plan_id, calendrier, revision_attendue, confirme_par, horodatage):
    """Écriture unique après validation complète. L'adaptateur sérialise via SQLite BEGIN IMMEDIATE."""
    index = _index(reg)
    _, propositions, applications, dates, detenteurs, etat = index
    if not isinstance(plan_id, str) or plan_id not in applications or plan_id not in propositions:
        raise ValueError("plan appliqué requis")
    if type(revision_attendue) is not int or revision_attendue < 0:
        raise ValueError("revision attendue entière positive ou nulle requise")
    revision = dates[plan_id][1]["revision"] if plan_id in dates else 0
    if revision_attendue != revision:
        raise ValueError("revision périmée : relire avant confirmation")
    if not isinstance(confirme_par, str) or not confirme_par.strip():
        raise ValueError("admin confirmant requis")
    if not isinstance(calendrier, dict) or not calendrier:
        raise ValueError("calendrier explicite requis")
    normalise = {}
    for cle, valeur in calendrier.items():
        if type(cle) is int and cle >= 0:
            cle = str(cle)
        if not isinstance(cle, str) or not cle.isascii() or not cle.isdigit() or str(int(cle)) != cle:
            raise ValueError("jour numérique canonique requis")
        if cle in normalise:
            raise ValueError("jour dupliqué")
        normalise[cle] = _date(valeur).isoformat()
    visites = list(_visites(propositions[plan_id]))
    jours = sorted({route["jour"] for route, _ in visites})
    if not jours or set(normalise) != {str(j) for j in jours}:
        raise ValueError("dater exactement les jours comportant des visites")
    civil = [normalise[str(j)] for j in jours]
    if civil != sorted(set(civil)):
        raise ValueError("dates distinctes et strictement croissantes requises")
    nouveaux = []
    for route, visite in visites:
        iid = visite["chantier"]
        info = etat.get(iid)
        if detenteurs.get(iid) != plan_id or not info or info["statut"] != "planifiee":
            raise ValueError("plan remplacé ou intervention non planifiée : nouvelle proposition requise")
        if info["technicien_assigne"] != route["equipe"]:
            raise ValueError("équipe réassignée : nouvelle proposition requise")
        debut, fin = _creneau(route, visite, normalise)
        nouveaux.append({"plan_id": plan_id, "equipe_id": route["equipe"], "debut": debut, "fin": fin})
    existants, _ = _projection(index)
    compares = [ligne for ligne in existants if ligne["plan_id"] != plan_id and ligne["validite"] == "date_confirmee"]
    for nouveau in nouveaux:
        for autre in compares:
            if nouveau["equipe_id"] == autre["equipe_id"] and (
                datetime.fromisoformat(nouveau["debut"]) < datetime.fromisoformat(autre["fin"]) and
                datetime.fromisoformat(autre["debut"]) < datetime.fromisoformat(nouveau["fin"])
            ):
                raise ValueError("conflit : équipe déjà occupée dans un créneau daté")
        compares.append(nouveau)
    entree = {"type_entree": TYPE_DATEE, "plan_id": plan_id, "calendrier": normalise,
              "revision": revision + 1, "confirme_par": confirme_par, "horodatage": horodatage,
              "fuseau": FUSEAU, "source_application_id": applications[plan_id]["ligne_id"]}
    ligne_id = reg.ajouter(entree)
    return {"plan_id": plan_id, "revision": revision + 1, "ligne_id": ligne_id,
            "calendrier": dict(normalise), "fuseau": FUSEAU, "avertissements": list(AVERTISSEMENTS)}


def lire_plan(reg, plan_id):
    """Détail borné d'un plan appliqué, sans date déduite ni autorisation de mutation.

    Les blocages portent sur toutes les visites, même celles omises de la réponse.
    La confirmation doit toujours revalider l'état courant et la révision dans sa transaction.
    """
    _, propositions, applications, dates, detenteurs, etat = _index(reg)
    if not isinstance(plan_id, str) or plan_id not in applications or plan_id not in propositions:
        raise ValueError("plan appliqué requis")
    source = dates[plan_id][1] if plan_id in dates else None
    jours, visites, bloquants, total = set(), [], set(), 0
    for route, visite in _visites(propositions[plan_id]):
        jour = route["jour"]
        if type(jour) is not int or jour < 0:
            raise ValueError("jour numérique positif ou nul requis")
        jours.add(jour)
        total += 1
        iid = visite["chantier"]
        info = etat.get(iid)
        raisons = []
        if detenteurs.get(iid) != plan_id:
            raisons.append("plan_remplace")
        if not info or info["statut"] != "planifiee":
            raisons.append("intervention_non_planifiee")
        if info and info["technicien_assigne"] != route["equipe"]:
            raisons.append("equipe_reassignee")
        bloquants.update(raisons)
        if len(visites) < 200:
            visites.append({"intervention_id": iid, "equipe_id": route["equipe"], "jour": jour,
                            "debut_min": visite["debut_min"], "fin_min": visite["fin_min"],
                            "statut": info["statut"] if info else None, "bloquants": raisons})
    jours_affiches = sorted(jours)[:31]
    return {"plan_id": plan_id, "fuseau": FUSEAU, "revision": source["revision"] if source else 0,
            "calendrier": {str(j): source["calendrier"][str(j)] for j in jours_affiches
                           if source and str(j) in source["calendrier"]},
            "source_application_id": applications[plan_id]["ligne_id"],
            "source_proposition_id": propositions[plan_id]["ligne_id"],
            "source_ligne_id": source["ligne_id"] if source else None,
            "jours": jours_affiches, "total_jours": len(jours),
            "visites": visites, "total_visites": total, "bloquants": sorted(bloquants),
            "tronque": total > 200 or len(jours) > 31,
            "avertissements": [*AVERTISSEMENTS,
                "Confirmation indisponible si le détail est tronqué; toute mutation revalide l'état courant."]}


def lire_semaine(reg, debut_semaine):
    """Projection bornée sans contacts ; sans_date concerne tout le carnet, pas une semaine devinée."""
    jour = _date(debut_semaine)
    if jour.weekday() != 0:
        raise ValueError("debut_semaine doit être un lundi")
    debut = instant_local(jour.isoformat(), 0)
    fin = instant_local((jour + timedelta(days=7)).isoformat(), 0)
    lignes, sans_date = _projection(_index(reg))
    lignes = [ligne for ligne in lignes if datetime.fromisoformat(ligne["debut"]) < fin
              and datetime.fromisoformat(ligne["fin"]) > debut]
    return {"debut_semaine": debut_semaine, "fuseau": FUSEAU, "interventions": lignes[:200],
            "total_interventions": len(lignes), "sans_date": sans_date[:50], "total_sans_date": len(sans_date),
            "tronque": len(lignes) > 200 or len(sans_date) > 50, "avertissements": list(AVERTISSEMENTS)}
