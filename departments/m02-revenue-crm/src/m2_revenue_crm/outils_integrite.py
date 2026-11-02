"""Outils du FILET ANTI-PERTE de M2 (M2-C1) : scan SLA, audit d'intégrité, plan de réparation, constat planifié pour M8.

Quatre outils, une couture mince entre les registres de M2 et les modules purs (`sla.py`, `integrite.py`,
`reparation.py`,
`filet.py`, `constat_filet.py`) :

  - `m2_scanner_sla` (N0) : les violations des sept règles SLA, avec leur raison, et les règles NON ÉVALUÉES avec ce qui
    reste à déclarer (seuils de `configuration.sla`) ;
  - `m2_auditer_integrite` (N0) : les huit contrôles d'intégrité des données, les anomalies et les doublons probables,
    en lecture seule ;
  - `m2_planifier_reparations` (N0) : le plan de réparation par lead, des actions PROPOSÉES jamais exécutées ; une
  action
    qui passe par un outil de niveau N3 ou plus dit qu'elle demande l'approbation d'une personne ;
  - `m2_constater_filet` (N2, agent seulement) : publie au bus (`m2.filet_anti_perte_constate`) les COMPTES du scan et
  de
    l'audit pour M8, déclenchés par le planificateur durable (`constats_planifies` du manifeste).

Aucun de ces outils n'écrit dans un registre de M2, n'envoie un message, ne change un statut ni ne fusionne quoi que ce
soit. Aucun n'a de droit d'appareil : le périmètre est celui de TOUS les leads (agent ou administrateur). Registres lus
:
`principal`, `relances_devis_recues`, `devis_envoyes_recus`, `devis_acceptes_recus`, `relances_preparees`,
`satisfactions_recues`, `profils_propriete`.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from opsys import evenements, stockage
from opsys.outils import Outil

from . import (
    acces,
    constat_filet,
    filet,
    integrite,
    propriete,
    relances,
    reparation,
    sla,
    suggestions,
)
from . import outils as _o
from .verdicts_commercial import construire_verdict as _verdict_commercial

__all__ = ["outils_integrite"]

_REGISTRES_DEVIS = ("relances_devis_recues", "devis_envoyes_recus", "devis_acceptes_recus")
_REGISTRE_PREPAREES = "relances_preparees"
_LIMITE_SCAN_DEFAUT, _LIMITE_SCAN_MAX = 15, 50
_LIMITE_PLAN_DEFAUT, _LIMITE_PLAN_MAX = 8, 30
_TEXTE_SUR = re.compile(r"[^A-Za-z0-9_.:~-]")


def _refus(code: str, detail: str) -> dict[str, Any]:
    return _o._refus(_verdict_commercial(code, detail=detail))


def _sur(texte: Any, longueur: int = 60) -> str:
    """Un texte tiré d'un registre (donnée non fiable) réduit à des caractères d'identifiant : une consigne glissée dans
    un statut illisible ne traverse jamais vers le modèle."""
    return _TEXTE_SUR.sub("?", str(texte))[:longueur]


# ---------------------------------------------------------------------------------------------- lecture des registres
def _perimetre_global() -> dict[str, Any] | None:
    """Un refus si l'appelant n'est pas l'agent ou un administrateur : le filet porte sur TOUS les leads, un périmètre
    partiel (un vendeur) serait faux."""
    acteur, refus = _o._acteur_appareil(acces.ROLES_LEADS)
    if refus is not None:
        return _o._refus(refus)
    if acteur is not None and acteur.role != acces.ROLE_ADMIN:
        return _refus(
            "REJ-FILET-PERIMETRE-GLOBAL", "le filet anti-perte porte sur tous les leads : agent ou admin seulement"
        )
    return None


def _durable() -> dict[str, Any] | None:
    if not _o._stockage_durable_actif or stockage.connexion_courante() is None:
        return _refus(
            "REJ-PREV-BUS-INDISPONIBLE",
            "le registre de M2 n'est pas adossé au stockage durable de l'instance : aucun registre n'est lisible, donc "
            "rien n'est calculé",
        )
    return None


def _instant(horodatage: Any) -> tuple[str | None, dict[str, Any] | None]:
    verdict = relances.verifier_instant(horodatage)
    if verdict is not None:
        return None, _o._refus(verdict)
    return _o._horodatage_faisant_foi(horodatage), None


def _lire_registres() -> dict[str, Any]:
    """Tous les registres du filet, lus UNE fois, sans rien écrire."""
    maillons = _o._obtenir_registre().lire()
    sans_reponse = list(stockage.maillons(_o._DEPARTEMENT, "relances_devis_recues"))
    envoyes = list(stockage.maillons(_o._DEPARTEMENT, "devis_envoyes_recus"))
    acceptes = list(stockage.maillons(_o._DEPARTEMENT, "devis_acceptes_recus"))
    return {
        "maillons": maillons,
        "devis": relances.devis_connus(sans_reponse, envoyes),
        "devis_integrite": [*sans_reponse, *envoyes, *acceptes],
        "preparees": [
            m
            for m in stockage.maillons(_o._DEPARTEMENT, _REGISTRE_PREPAREES)
            if m.get("type_entree") == relances.TYPE_ENTREE
        ],
        "satisfactions": _o._satisfactions_recues(),
        "propriete": list(stockage.maillons(_o._DEPARTEMENT, propriete.REGISTRE)),
    }


def _rapport(instant: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """`(rapport du filet, maillons)` : le scan SLA et l'audit d'intégrité sur les registres lus, avec les réglages
    relus
    à chaque appel (`department.yaml`, jamais mis en cache)."""
    lus = _lire_registres()
    reglages = sla.lire_reglages(_o._bloc_configuration("sla"), _o._seuils_segments())
    rapport = filet.produire(
        lus["maillons"],
        maintenant=instant,
        reglages=reglages,
        devis=lus["devis"],
        preparees=lus["preparees"],
        satisfactions=lus["satisfactions"],
        maillons_propriete=lus["propriete"],
        devis_integrite=lus["devis_integrite"],
    )
    return rapport, lus["maillons"]


# ---------------------------------------------------------------------------------------------- pagination bornée
def _page(
    sortie: dict[str, Any], cle: str, elements: list[Any], decalage: int, limite: int, *, total: int | None = None
) -> dict[str, Any]:
    """Une page de `elements` sous `cle`, bornée par la TAILLE sérialisée mesurée (jamais estimée), toujours un élément
    au
    moins. `suivant` : le décalage à demander ensuite (`None` à la fin) ; `reste` compte ce qui suit la page. `total` :
    quand `elements` n'est déjà que la fenêtre demandée (à partir de `decalage`), le nombre total d'éléments."""
    fenetre = elements[:limite] if total is not None else elements[decalage : decalage + limite]
    ensemble = total if total is not None else len(elements)
    nombre = len(fenetre)
    while True:
        apres = decalage + nombre
        page = {
            **sortie,
            cle: fenetre[:nombre],
            "total": ensemble,
            "decalage": decalage,
            "affichees": nombre,
            "reste": ensemble - apres if apres < ensemble else 0,
            "suivant": apres if apres < ensemble else None,
        }
        if nombre <= 1 or len(json.dumps(page, ensure_ascii=False)) <= _o.BUDGET_SORTIE:
            return page
        nombre -= 1


def _valider_pagination(decalage: Any, limite: Any, maximum: int) -> dict[str, Any] | None:
    if isinstance(decalage, bool) or not isinstance(decalage, int) or decalage < 0:
        return _o._refus(
            _o.verdicts.construire_verdict(
                "REJ-PAGINATION-INVALIDE", detail="decalage : un entier supérieur ou égal à 0 est attendu"
            )
        )
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= maximum:
        return _o._refus(
            _o.verdicts.construire_verdict(
                "REJ-PAGINATION-INVALIDE", detail=f"limite : un entier de 1 à {maximum} est attendu"
            )
        )
    return None


# ---------------------------------------------------------------------------------------------- les outils
def scanner_sla(horodatage: str, decalage: int = 0, limite: int = _LIMITE_SCAN_DEFAUT) -> dict[str, Any]:
    """`m2_scanner_sla` (N0) : les violations des sept règles SLA, une page à la fois, et l'état de chaque règle. Une
    règle
    dont le seuil n'est pas déclaré est NON ÉVALUÉE et dit quoi déclarer : une liste vide ne se lit jamais « tout va
    bien ». Lecture pure."""
    refus = _perimetre_global()
    if refus is not None:
        return refus
    refus = _valider_pagination(decalage, limite, _LIMITE_SCAN_MAX)
    if refus is not None:
        return refus
    instant, refus = _instant(horodatage)
    if refus is not None:
        return refus
    absent = _durable()
    if absent is not None:
        return absent
    rapport, _maillons = _rapport(instant)
    scan = rapport["sla"]
    violations = [
        {
            **v,
            "proprietaire": _sur(v["proprietaire"]) if v["proprietaire"] else None,
            "lead_id": _sur(v["lead_id"], 120),
        }
        for v in scan["violations"]
    ]
    cites = sorted({v["regle"] for v in violations}, key=sla.ORDRE_REGLES.index)
    sortie = {
        "reference": instant,
        "leads_examines": scan["examines"],
        "regles": scan["regles"],
        "regles_non_evaluees": [r["regle"] for r in scan["regles"] if r["etat"] == sla.ETAT_NON_EVALUEE],
        "enonces": {r: sla.REGLES[r] for r in cites},
    }
    return {"accepte": True, "resultat": _page(sortie, "violations", violations, decalage, limite)}


def auditer_integrite(horodatage: str, decalage: int = 0, limite: int = _LIMITE_SCAN_DEFAUT) -> dict[str, Any]:
    """`m2_auditer_integrite` (N0) : les huit contrôles d'intégrité des données de M2, les anomalies (une page à la
    fois)
    et les doublons probables. Rien n'est corrigé, rien n'est fusionné. Lecture pure."""
    refus = _perimetre_global()
    if refus is not None:
        return refus
    refus = _valider_pagination(decalage, limite, _LIMITE_SCAN_MAX)
    if refus is not None:
        return refus
    instant, refus = _instant(horodatage)
    if refus is not None:
        return refus
    absent = _durable()
    if absent is not None:
        return absent
    rapport, _maillons = _rapport(instant)
    audit = rapport["integrite"]
    anomalies = [_assainir(a) for a in audit["anomalies"]]
    sortie = {
        "reference": instant,
        "leads_examines": audit["leads_examines"],
        "maillons_examines": audit["maillons_examines"],
        "controles": audit["controles"],
        "doublons_en_attente": audit["doublons_en_attente"],
        "doublons_probables": audit["doublons_probables"][:5],
        "doublons_tronques": audit["doublons_tronques"] or len(audit["doublons_probables"]) > 5,
        "enonces": {c: integrite.ENONCES[c] for c in integrite.CONTROLES if any(a["controle"] == c for a in anomalies)},
    }
    return {"accepte": True, "resultat": _page(sortie, "anomalies", anomalies, decalage, limite)}


def _assainir(anomalie: dict[str, Any]) -> dict[str, Any]:
    """Les textes d'une anomalie viennent d'un registre : réduits à des caractères d'identifiant."""

    def propre(valeur: Any) -> Any:
        if isinstance(valeur, str):
            return _sur(valeur, 120)
        if isinstance(valeur, list):
            return [propre(v) for v in valeur]
        if isinstance(valeur, dict):
            return {_sur(k): propre(v) for k, v in valeur.items()}
        return valeur

    return {
        **anomalie,
        "lead_id": propre(anomalie["lead_id"]),
        "client_id": propre(anomalie["client_id"]),
        "donnee": propre(anomalie["donnee"]),
    }


def _niveaux_des_outils() -> dict[str, str]:
    """`{nom d'outil: niveau}` relu des outils RÉELS de M2 : un plan ne recopie jamais un niveau."""
    return {o.nom: o.niveau_effectif.value for o in _o.outils()}


def planifier_reparations(horodatage: str, decalage: int = 0, limite: int = _LIMITE_PLAN_DEFAUT) -> dict[str, Any]:
    """`m2_planifier_reparations` (N0) : le plan de réparation, une cible à la fois, par urgence. Des actions PROPOSÉES
    (`execute: False`) ; une action qui passe par un outil N3 demande l'approbation d'une personne. La prochaine
    meilleure action existante (`m2_suggerer_prochaine_action`) accompagne chaque lead. Lecture pure : rien ne
    s'exécute."""
    refus = _perimetre_global()
    if refus is not None:
        return refus
    refus = _valider_pagination(decalage, limite, _LIMITE_PLAN_MAX)
    if refus is not None:
        return refus
    instant, refus = _instant(horodatage)
    if refus is not None:
        return refus
    absent = _durable()
    if absent is not None:
        return absent
    rapport, _maillons = _rapport(instant)
    niveaux = _niveaux_des_outils()
    plan_brut = reparation.planifier(rapport["sla"]["violations"], rapport["integrite"]["anomalies"], niveaux=niveaux)
    reg = (
        _o._obtenir_registre()
    )  # la lecture complète du registre : les règles de suggestion lisent la tête de la chaîne
    plan = []
    for entree in plan_brut[decalage : decalage + limite]:
        suggestion = None
        if entree["cible"]["type"] == "lead":
            resultat, _verdict = suggestions.suggerer(reg, entree["cible"]["id"], instant)
            suggestion = {k: resultat[k] for k in ("regle", "suggestion", "motif")} if resultat is not None else None
        plan.append({**entree, "prochaine_action_suggeree": suggestion})
    # les identifiants viennent d'un registre : réduits à des caractères d'identifiant, comme le scan
    plan = [
        {
            **e,
            "cible": {"type": e["cible"]["type"], "id": _sur(e["cible"]["id"], 120)},
            "proprietaire": _sur(e["proprietaire"]) if e["proprietaire"] else None,
        }
        for e in plan
    ]
    sortie = {
        "reference": instant,
        "execute": False,
        "avertissement": (
            "Ce plan ne fait rien : chaque action est une proposition. Les actions marquées approbation_requise "
            "passent par une personne dans le sas d'approbation (niveau N3). Aucun message n'est envoyé, aucune fusion "
            "n'est faite."
        ),
        "regles_non_evaluees": [r["regle"] for r in rapport["sla"]["regles"] if r["etat"] == sla.ETAT_NON_EVALUEE],
        "controles_non_evalues": [
            c["controle"] for c in rapport["integrite"]["controles"] if c["etat"] == "non_evalue"
        ],
    }
    return {"accepte": True, "resultat": _page(sortie, "plan", plan, decalage, limite, total=len(plan_brut))}


def constater_filet(horodatage: str) -> dict[str, Any]:
    """`m2_constater_filet` (N2, agent seulement) : établit le scan SLA et l'audit d'intégrité de TOUS les leads et
    PUBLIE
    leurs comptes (`m2.filet_anti_perte_constate`) pour M8, qui n'appelle aucun outil de M2. Ni lead, ni client, ni
    contact, ni vendeur, ni devis ne part. Une règle non évaluée (seuil non déclaré) part en `null`, jamais en zéro.
    Une version par instant de constat : rejouer le même constat (même horodatage) ne publie rien de plus."""
    refus = _perimetre_global()
    if refus is not None:
        return refus
    instant, refus = _instant(horodatage)
    if refus is not None:
        return refus
    absent = _durable()
    if absent is not None:
        return absent
    rapport, _maillons = _rapport(instant)
    jour = datetime.fromisoformat(instant).astimezone(ZoneInfo("America/Montreal")).date().isoformat()
    charge = constat_filet.charge_filet(rapport, jour, instant)
    evenements.publier("m2.filet_anti_perte_constate", _o._DEPARTEMENT, charge, evenement_id=charge["evenement_id"])
    return {
        "accepte": True,
        "resultat": {
            "publie": True,
            "evenement_id": charge["evenement_id"],
            "date_reference": jour,
            "version_donnees": charge["version_donnees"],
            "leads_examines": charge["leads_examines"],
            "violations_total": charge["violations_total"],
            "anomalies_total": charge["anomalies_total"],
            "regles_non_evaluees": charge["regles_non_evaluees"],
        },
    }


# ---------------------------------------------------------------------------------------------- déclaration
def outils_integrite() -> tuple[Outil, ...]:
    """Les quatre outils du filet anti-perte."""
    horodatage = _o._HORODATAGE

    def schema(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": proprietes, "required": requis}

    pagination = {
        "decalage": {"type": "integer", "minimum": 0},
        "limite": {"type": "integer", "minimum": 1, "maximum": _LIMITE_SCAN_MAX},
    }
    from opsys.outils import Autonomie, Niveau

    return (
        Outil(
            nom="m2_scanner_sla",
            description=(
                "M2.13 : scan SLA du filet anti-perte sur TOUS les leads (agent ou admin). Sept règles : prochaine "
                "action "
                "obligatoire, lead chaud contacté vite, photos reçues, soumission relancée, plainte escaladée, lead "
                "avec "
                "propriétaire, tâche en retard. Chaque violation dit sa règle, sa raison, depuis quand. Les délais "
                "sont "
                "DÉCLARÉS par le propriétaire (configuration.sla) : une règle sans délai déclaré est NON ÉVALUÉE et "
                "dit "
                "quoi déclarer, jamais « aucune violation ». Lecture pure : rien n'est écrit ni envoyé."
            ),
            parametres=schema({"horodatage": horodatage, **pagination}, ["horodatage"]),
            fonction=scanner_sla,
        ),
        Outil(
            nom="m2_auditer_integrite",
            description=(
                "M2.1 : audit d'intégrité des données du CRM (agent ou admin) : leads sans statut, clients sans "
                "contact, "
                "tâches sans propriétaire, soumissions orphelines, activités sans lead, leads sans client, pipeline "
                "incohérent, doublons probables (lecture seule, aucune fusion). Rien n'est corrigé. Lecture pure."
            ),
            parametres=schema({"horodatage": horodatage, **pagination}, ["horodatage"]),
            fonction=auditer_integrite,
        ),
        Outil(
            nom="m2_planifier_reparations",
            description=(
                "M2.13 : plan de réparation du filet anti-perte (agent ou admin) : par lead, les actions PROPOSÉES "
                "pour "
                "corriger les violations SLA et les anomalies d'intégrité, par urgence, avec la prochaine meilleure "
                "action existante. Rien n'est exécuté ; une action sensible (outil N3) demande l'approbation d'une "
                "personne. Aucun message n'est envoyé, aucune fusion. Lecture pure."
            ),
            parametres=schema(
                {
                    "horodatage": horodatage,
                    "decalage": {"type": "integer", "minimum": 0},
                    "limite": {"type": "integer", "minimum": 1, "maximum": _LIMITE_PLAN_MAX},
                },
                ["horodatage"],
            ),
            fonction=planifier_reparations,
        ),
        Outil(
            nom="m2_constater_filet",
            description=(
                "M2.13/D2 : fait CONSTATER le filet anti-perte de TOUS les leads et le PUBLIE au bus "
                "(m2.filet_anti_perte_constate) pour M8 : violations par règle SLA, anomalies par contrôle "
                "d'intégrité, "
                "règles non évaluées (seuil non déclaré : null, jamais zéro). Aucun lead, aucun contact, aucun vendeur "
                "ne part. Rejouer le même constat (même horodatage) ne publie rien de plus. Déclenché par le "
                "planificateur "
                "durable (constats_planifies), jamais par un agent seul. horodatage : instant de lecture (ISO 8601 "
                "avec "
                "fuseau)."
            ),
            parametres=schema({"horodatage": horodatage}, ["horodatage"]),
            fonction=constater_filet,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
    )
