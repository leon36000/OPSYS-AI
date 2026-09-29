"""Liste des leads visibles, filtrée par statut et par segment, paginée (PLAN T4.6 ; DEFINITION-PRODUIT §9.4
« ses leads », §9.5 « pipeline, leads chauds » ; M2.11).

Module PUR (comme ``segments.py`` et ``acces.py`` : aucun import ``opsys``, aucune horloge). L'adaptateur
(``outils.py``) lit le registre UNE fois, confirme l'identité de l'appelant, calcule les leads qu'il peut voir
(``acces.leads_visibles``) et passe le tout ici. Ce module ne lit jamais l'identité.

QUI VOIT QUOI. ``visibles`` est ``None`` (admin, agent : tous les leads) ou l'ensemble des leads du vendeur.
Un lead hors de cet ensemble n'est ni listé, ni compté (``total``), ni lu par une règle de segment : rien ne
dit à un vendeur quels leads existent. ``past_customer`` ne lit que les opportunités visibles du client.

AUCUN MONTANT. Un item porte l'identité du lead, son statut, son propriétaire, ses travaux, sa ville, l'urgence
déclarée, deux dates, la prochaine action et ses segments : ni prix, ni coût, ni marge, ni valeur de client
(``high_value_customer`` est non calculable : M2 n'a pas ces montants). Ni contact : la fiche du client est au
Client 360.

ORDRE, stable et total (``ORDRE_LEADS``) : le plus ancien lead ingéré d'abord (instants comparés en UTC, jamais
alphabétiquement), puis ``lead_id`` croissant. La clé est l'heure d'ingestion, qui ne change jamais : un lead
qui reçoit une note ou une transition ne change pas de rang, et un lead ingéré après le début de la lecture
s'ajoute à la FIN, donc ne décale aucune page déjà lue.

PAGES. Même mécanisme que ``attentes_decalage`` du socle (``approbations_appareil.lister_demandes``) et que
``m9_lire_suite_briefing`` / ``m9_lire_alertes_m8`` (``lecture_alertes.py``) : ``decalage`` est le RANG du premier
lead rendu dans cet ordre (0 par défaut), la page tient dans ``budget_caracteres`` (taille sérialisée mesurée par
le code, jamais estimée) et dans ``limite`` leads, avec toujours un lead au moins (une page vide ne ferait jamais
progresser la lecture). ``suivant`` est le décalage à demander ensuite, ``None`` quand rien ne suit ; ``reste``
compte ce qui vient APRÈS la page. Un décalage au-delà de la fin rend une page vide et ``suivant: None``, jamais
une erreur ; seul un décalage qui n'est pas un entier ≥ 0 est refusé. Lues bout à bout dans un état qui ne
change pas, les pages se recollent sans doublon ni trou. Un décalage est un rang : si un lead change de statut
ou de segment entre deux pages (ce qui le fait entrer dans un filtre ou en sortir), un lead peut manquer ou se
répéter et ``total`` change : l'appelant relit depuis 0.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from . import acces, clients, contrats, readiness, segments, statuts, verdicts
from . import horodatage as _horodatage

__all__ = [
    "LIMITE_DEFAUT",
    "LIMITE_MAX",
    "ORDRE_LEADS",
    "Vue",
    "identifiants_des_leads",
    "lister",
]

ORDRE_LEADS = "ingestion croissante (le plus ancien d'abord, instants comparés en UTC), puis lead_id croissant"
LIMITE_DEFAUT = 20
LIMITE_MAX = 50
_LIMITE_TEXTE = 80
_LIMITE_ACTION = 160

# Types de maillon du registre lus ici (ceux de ingestion.py, statuts.py, interactions.py).
_TYPE_INGESTION = "lead_ingere"
_TYPE_TRANSITION = statuts.TYPE_ENTREE
_TYPE_INTERACTION = "interaction"
# Une écriture du système (`system:m3`, `system:m4`) n'est pas l'activité d'une personne : un identifiant de
# personne ne contient pas de « : » (`acces.py`).
_AUTEUR_SYSTEME = "system:"


class Vue:
    """Lecture seule d'une liste de maillons, avec l'interface de ``Registre.lire()`` : les fonctions du paquet
    qui prennent un registre (``statuts.statut_courant``, ``readiness.evaluer``, ``acces.proprietaires``…) ne
    lisent que ``lire()``. Passer la liste d'UN lead les fait travailler sur ses seuls maillons : la même règle,
    sans recopier le registre entier pour chaque lead."""

    def __init__(self, maillons: list[dict[str, Any]]) -> None:
        self._maillons = maillons

    def lire(self) -> list[dict[str, Any]]:
        return self._maillons


@dataclasses.dataclass(frozen=True)
class _Fiche:
    lead_id: str
    vue: Vue
    statut: str | None
    contrat: dict[str, Any]
    ingere_le: str
    derniere_activite: str | None
    prochaine_action: dict[str, Any] | None
    reference_devis_m3: str | None
    client_id: str | None


def identifiants_des_leads(maillons: list[dict[str, Any]]) -> list[str]:
    """Les ``lead_id`` de tous les leads ingérés, dans l'ordre du registre, sans répétition."""
    vus: list[str] = []
    deja = set()
    for maillon in maillons:
        lead_id = maillon.get("lead_id")
        if maillon.get("type_entree") == _TYPE_INGESTION and lead_id not in deja:
            deja.add(lead_id)
            vus.append(lead_id)
    return vus


def _derniere_activite(maillons: list[dict[str, Any]]) -> str | None:
    """Horodatage (tel qu'écrit) de la dernière activité humaine du lead : ingestion, transition, ou interaction
    d'une personne. Un maillon à l'horodatage illisible est ignoré ; aucun lisible : ``None``."""
    meilleur = None
    texte = None
    for maillon in maillons:
        type_entree = maillon.get("type_entree")
        if type_entree not in (_TYPE_INGESTION, _TYPE_TRANSITION, _TYPE_INTERACTION):
            continue
        if type_entree == _TYPE_INTERACTION and str(maillon.get("auteur", "")).startswith(_AUTEUR_SYSTEME):
            continue
        try:
            instant = segments.instant_utc(maillon.get("horodatage"))
        except (ValueError, TypeError):
            continue
        if meilleur is None or instant > meilleur:
            meilleur, texte = instant, maillon["horodatage"]
    return texte


def _derniere_prochaine_action(maillons: list[dict[str, Any]]) -> dict[str, Any] | None:
    trouve = None
    for maillon in maillons:
        if maillon.get("type_entree") == _TYPE_TRANSITION and maillon.get("prochaine_action") is not None:
            trouve = maillon["prochaine_action"]
    return trouve


def _fiches(maillons: list[dict[str, Any]]) -> dict[str, _Fiche]:
    """Une fiche par lead ingéré, en UN parcours du registre. Une ligne dont le ``lead_id`` n'a jamais été
    ingéré n'en fait pas un lead."""
    par_lead: dict[str, list[dict[str, Any]]] = {}
    for maillon in maillons:
        lead_id = maillon.get("lead_id")
        if isinstance(lead_id, str):
            par_lead.setdefault(lead_id, []).append(maillon)
    fiches: dict[str, _Fiche] = {}
    for lead_id, siens in par_lead.items():
        ingere = next((m for m in siens if m.get("type_entree") == _TYPE_INGESTION), None)
        if ingere is None:
            continue
        vue = Vue(siens)
        contrat = ingere.get("contrat")
        fiches[lead_id] = _Fiche(
            lead_id=lead_id,
            vue=vue,
            statut=statuts.statut_courant(vue, lead_id),
            contrat=contrat if isinstance(contrat, dict) else {},
            ingere_le=ingere["horodatage"],
            derniere_activite=_derniere_activite(siens),
            prochaine_action=_derniere_prochaine_action(siens),
            reference_devis_m3=statuts.reference_devis(vue, lead_id),
            client_id=clients.client_de_lead(vue, lead_id),
        )
    return fiches


def _opportunites_par_client(maillons: list[dict[str, Any]]) -> dict[str, list[str]]:
    """``{client_id: [lead_id, ...]}``, l'ordre et l'absence de répétition de ``clients.opportunites_du_client``
    (un test épingle l'égalité), en un seul parcours."""
    par_client: dict[str, list[str]] = {}
    for maillon in maillons:
        if maillon.get("type_entree") != clients.TYPE_ENTREE:
            continue
        opportunites = par_client.setdefault(maillon.get("client_id"), [])
        if maillon.get("lead_id") not in opportunites:
            opportunites.append(maillon.get("lead_id"))
    return par_client


def _cle_ordre(fiche: _Fiche) -> tuple[int, float, str]:
    """Clé de l'ordre : instant d'ingestion en UTC, puis ``lead_id``. Une ingestion à l'horodatage illisible
    (jamais par l'API publique) passe après toutes les autres, par ``lead_id``."""
    try:
        return 0, segments.instant_utc(fiche.ingere_le).timestamp(), fiche.lead_id
    except (ValueError, TypeError):
        return 1, 0.0, fiche.lead_id


def _court(valeur: Any, limite: int) -> Any:
    """Un texte de contrat borné (une valeur libre ne doit pas faire exploser la page) ; autre chose qu'un
    texte : tel quel."""
    if isinstance(valeur, str) and len(valeur) > limite:
        return valeur[: limite - 1] + "…"
    return valeur


def _taille(objet: Any) -> int:
    """Taille sérialisée EXACTE telle que ``Capacites._tronquer`` la mesure (``json.dumps`` sans échappement
    ASCII) : la borne se calcule sur ce que le modèle recevrait."""
    return len(json.dumps(objet, ensure_ascii=False))


@dataclasses.dataclass
class _Contexte:
    fiches: dict[str, _Fiche]
    proprietaires: dict[str, str]
    opportunites: dict[str, list[str]]
    devis_par_lead: dict[str, list[dict[str, Any]]] | None
    visibles: set[str] | None
    seuils: dict[str, dict[str, Any]]
    maintenant: str
    globaux: list[dict[str, str]]


def _opportunite_payee(fiche: _Fiche, contexte: _Contexte) -> str | None:
    """Le premier lead (par ``lead_id``) du même client au statut ``avis`` que l'appelant peut voir ; ``None``
    si le lead n'a pas de client ou si aucun n'est visible."""
    if fiche.client_id is None:
        return None
    for autre in sorted(contexte.opportunites.get(fiche.client_id, ())):
        voit = contexte.visibles is None or autre in contexte.visibles
        fiche_autre = contexte.fiches.get(autre)
        if voit and fiche_autre is not None and fiche_autre.statut == "avis":
            return autre
    return None


def _segmenter(fiche: _Fiche, contexte: _Contexte) -> dict[str, Any]:
    devis = None
    if contexte.devis_par_lead is not None:
        devis = contexte.devis_par_lead.get(fiche.lead_id, [])
    faits = {
        "maintenant": contexte.maintenant,
        # `readiness.evaluer` n'est lue que pour un lead qualifié (la règle d'`estimate_ready`) : les autres
        # statuts n'ont pas besoin de relire le profil d'entreprise.
        "pret_pour_m3": readiness.evaluer(fiche.vue, fiche.lead_id) if fiche.statut == "qualifie" else None,
        "devis_sans_reponse": devis,
        "opportunite_payee": _opportunite_payee(fiche, contexte),
    }
    lead = {
        "lead_id": fiche.lead_id,
        "statut": fiche.statut,
        "urgence_declaree": fiche.contrat.get("urgence_declaree"),
        "derniere_activite": fiche.derniere_activite,
        "reference_devis_m3": fiche.reference_devis_m3,
    }
    return segments.segmenter(lead, faits, contexte.seuils)


def _travaux(contrat: dict[str, Any]) -> Any:
    """Le service d'un lead v2, le type de travaux d'un lead v1 (la clé suit la version déclarée, comme la
    readiness). Absent : ``None``, jamais une valeur devinée."""
    cle = "service" if contrat.get("schema_version") == contrats.VERSION_CONTRAT_V2 else "type_travaux"
    return _court(contrat.get(cle), _LIMITE_TEXTE)


def _item(fiche: _Fiche, resultat: dict[str, Any], contexte: _Contexte) -> dict[str, Any]:
    action = fiche.prochaine_action
    item: dict[str, Any] = {
        "lead_id": fiche.lead_id,
        "statut": fiche.statut,
        "proprietaire": contexte.proprietaires.get(fiche.lead_id),
        "travaux": _travaux(fiche.contrat),
        "ville": _court(fiche.contrat.get("ville"), _LIMITE_TEXTE),
        "urgence_declaree": fiche.contrat.get("urgence_declaree"),
        "ingere_le": fiche.ingere_le,
        "derniere_activite": fiche.derniere_activite,
        "prochaine_action": (
            {"description": _court(action.get("description"), _LIMITE_ACTION), "echeance": action.get("echeance")}
            if isinstance(action, dict) else None
        ),
        "segments": resultat["segments"],
    }
    propres = [n for n in resultat["non_calculables"] if n not in contexte.globaux]
    if propres:
        item["non_calculables"] = propres
    return item


def _valider_demande(
    statut: Any, segment: Any, decalage: Any, limite: Any, maintenant: Any,
) -> dict[str, Any] | None:
    """Un verdict si un argument est invalide, sinon ``None``."""
    if statut is not None and statut not in statuts.STATUTS:
        return verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE", detail=f"statut {statut!r} hors de la liste {list(statuts.STATUTS)}")
    if segment is not None and segment not in segments.SEGMENTS:
        return verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE", detail=f"segment {segment!r} hors de la liste {list(segments.SEGMENTS)}")
    if isinstance(decalage, bool) or not isinstance(decalage, int) or decalage < 0:
        return verdicts.construire_verdict(
            "REJ-PAGINATION-INVALIDE", detail="decalage : un entier supérieur ou égal à 0 est attendu")
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= LIMITE_MAX:
        return verdicts.construire_verdict(
            "REJ-PAGINATION-INVALIDE", detail=f"limite : un entier de 1 à {LIMITE_MAX} est attendu")
    try:
        _horodatage.valider_horodatage(maintenant)
    except ValueError:
        return verdicts.construire_verdict(
            "REJ-HORODATAGE-INVALIDE", detail="horodatage : ISO-8601 avec fuseau attendu")
    return None


def _regles_citees(items: list[dict[str, Any]]) -> dict[str, str]:
    citees = {s["regle"] for item in items for s in item["segments"]}
    return {regle: segments.REGLES[regle] for regle in sorted(citees)}


def lister(
    maillons: list[dict[str, Any]],
    *,
    visibles: set[str] | None,
    relances_devis: list[dict[str, Any]] | None,
    seuils: dict[str, dict[str, Any]],
    horodatage: str,
    statut: str | None = None,
    segment: str | None = None,
    decalage: int = 0,
    limite: int = LIMITE_DEFAUT,
    budget_caracteres: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Une page de la liste des leads visibles, ``(page, None)`` ou ``(None, verdict)``.

    ``maillons`` : le registre de M2 (UNE lecture). ``visibles`` : ``None`` (tous) ou les leads que l'appelant
    peut voir (``acces.leads_visibles``). ``relances_devis`` : les faits ``m3.devis_sans_reponse`` reçus
    (registre ``relances_devis_recues``) ; ``None`` : illisibles, ``quote_stale`` devient non calculable.
    ``seuils`` : ``segments.lire_seuils(...)``. ``horodatage`` : l'instant de référence, fourni par l'appelant.

    Filtres : ``statut`` (un statut de ``statuts.STATUTS``) et ``segment`` (un des 14). Un segment non
    calculable (seuil absent, donnée que M2 n'a pas) est REFUSÉ avec ce qui manque, ``REJ-SEGMENT-NON-CALCULABLE`` :
    une liste vide se lirait « aucun lead ». Pour un lead dont ce segment n'a pas pu être calculé (donnée
    illisible), le lead n'est pas listé et ``indetermines`` le compte ; sans filtre, son ``non_calculables`` dit
    pourquoi.

    La page : ``leads`` (chacun avec ses ``segments`` : règle citée et donnée déclencheuse), ``regles`` (l'énoncé
    des règles citées), ``segments_non_calculables`` (ce qui manque pour tous les leads), ``total`` (les leads
    visibles qui passent les filtres), ``decalage``, ``affichees``, ``reste``, ``suivant``, ``message``."""
    verdict = _valider_demande(statut, segment, decalage, limite, horodatage)
    if verdict is not None:
        return None, verdict
    devis_lisibles = relances_devis is not None
    if segment is not None:
        manque = segments.manque_du_segment(segment, seuils, devis_lisibles)
        if manque is not None:
            return None, verdicts.construire_verdict(
                "REJ-SEGMENT-NON-CALCULABLE", detail=f"segment {segment} : {manque}")

    fiches = _fiches(maillons)
    devis_par_lead = None
    if relances_devis is not None:
        devis_par_lead = {}
        for fait in relances_devis:
            devis_par_lead.setdefault(fait.get("lead_id"), []).append(fait)
    contexte = _Contexte(
        fiches=fiches,
        proprietaires=acces.proprietaires(Vue(maillons)),
        opportunites=_opportunites_par_client(maillons),
        devis_par_lead=devis_par_lead,
        visibles=visibles,
        seuils=seuils,
        maintenant=horodatage,
        globaux=segments.segments_non_calculables(seuils, devis_lisibles),
    )

    ordonnes = sorted(fiches.values(), key=_cle_ordre)
    candidats = [
        f for f in ordonnes
        if (visibles is None or f.lead_id in visibles) and (statut is None or f.statut == statut)
    ]
    resultats: dict[str, dict[str, Any]] = {}
    indetermines = 0
    if segment is None:
        retenus = candidats
    else:
        retenus = []
        for fiche in candidats:
            resultat = _segmenter(fiche, contexte)
            resultats[fiche.lead_id] = resultat
            if any(s["segment"] == segment for s in resultat["segments"]):
                retenus.append(fiche)
            elif any(n["segment"] == segment for n in resultat["non_calculables"]):
                indetermines += 1

    total = len(retenus)
    fenetre = retenus[decalage: decalage + limite]
    items = []
    for fiche in fenetre:
        if fiche.lead_id not in resultats:
            resultats[fiche.lead_id] = _segmenter(fiche, contexte)
        items.append(_item(fiche, resultats[fiche.lead_id], contexte))

    def page(nombre: int) -> dict[str, Any]:
        affiches = items[:nombre]
        apres = min(total, decalage + nombre)
        reste = total - apres
        return {
            "ordre": ORDRE_LEADS,
            "filtre": {"statut": statut, "segment": segment},
            "total": total,
            "decalage": decalage,
            "affichees": nombre,
            "reste": reste,
            "suivant": apres if reste else None,
            "message": (
                None if not reste else
                (f"{reste} autres leads non affichés : poursuivre avec decalage={apres}." if reste > 1
                 else f"1 autre lead non affiché : poursuivre avec decalage={apres}.")
            ),
            "indetermines": indetermines,
            "leads": affiches,
            "regles": _regles_citees(affiches),
            "segments_non_calculables": contexte.globaux,
        }

    nombre = 0
    while nombre < len(items) and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if items and nombre == 0:
        nombre = 1
    return page(nombre), None
