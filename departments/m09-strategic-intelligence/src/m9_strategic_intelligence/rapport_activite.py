"""Composition pure et bornée des trois lectures M9, sans instantané métier commun.

Les flux natifs sont intégralement matérialisés avant toute page composite : une
preuve tardive invalide ou trop volumineuse refuse donc aussi la première page.
"""
from __future__ import annotations

import copy
from typing import Any

from .bilan_suivis import bilan_suivis_decision
from .echeancier_suivis import _EMPREINTE, _taille
from .encodage import empreinte
from .observations_chantier import lister_observations_chantier
from .rapport_periode import assembler_rapport_periode

__all__ = ["assembler_rapport_activite"]

_TYPE = "RAPPORT_ACTIVITE_PERIODE"
_COMPTEURS = ("ouverts_periode", "clotures_periode", "ouverts_fin")
_ORDRE = "observations, puis alertes, puis suivis ; ordre natif dans chaque section"
_BASES = {
    "observations": "instant métier d'origine dans [debut, fin), observations connues à la lecture",
    "alertes": "horodatage_reference chantier dans [debut, fin), alertes connues à la lecture",
    "suivis": "décisions humaines signées ; état juste avant fin, clôture à fin ou après non rendue",
}
_MANQUES = (
    {"section": "authentification_producteur", "verifie": "NON_PROUVEE",
     "constat": "source_bus_liee seulement : liaison exacte à la première publication, aucune signature M8"},
    {"section": "snapshots_generiques", "verifie": "NON_COUVERT",
     "constat": "compte global hors période comprise ; dates non lues, aucun fait de période déduit"},
    {"section": "reception_et_historique", "verifie": "NON_COUVERT",
     "constat": "aucun instant de réception ni as-of commun ; ne dit pas ce qui était connu à fin"},
    {"section": "decisions_en_attente_periode", "verifie": "NON_COUVERT",
     "constat": "file courante non historisée et non lue"},
    {"section": "couverture", "verifie": "NON_COUVERT",
     "constat": "premiers WCT durables après activation seulement, sans rattrapage ; ni finance, ni M1-M8 "
                "complet, ni rapport exécutif hebdomadaire complet ; "
                "aucune action terrain, cause ou amélioration attestée"},
)


def _refus(detail: str) -> ValueError:
    return ValueError("REJ-ACTIVITE-PAGINATION : " + detail)


def _entier(valeur: Any) -> bool:
    return type(valeur) is int and valeur >= 0


def _materialiser(lecteur, arguments, section, maximum, debut, fin, budget):
    """Consomme au plus N+1 pages ; conserve et compare tout en-tête natif invariant."""
    lignes = []
    premier = None
    entete = None
    curseur = 0
    vue = None
    for _ in range(maximum + 1):
        page = lecteur(*arguments, debut, fin, curseur, vue, budget_caracteres=budget)
        if not isinstance(page, dict):
            raise _refus(section + " : page non objet")
        bloc = page.get("alertes_periode") if section == "alertes" else page
        cle = {"observations": "observations", "alertes": "alertes", "suivis": "suivis"}[section]
        if (not isinstance(bloc, dict) or not isinstance(bloc.get(cle), list)
                or "prochain_depart" not in bloc):
            raise _refus(section + " : lignes ou curseur terminal natifs absents")
        total, nombre, reste = (bloc.get(champ) for champ in ("total", "affichees", "reste"))
        depart_page, prochain = bloc.get("depart"), bloc.get("prochain_depart")
        if not all(_entier(v) for v in (total, nombre, reste, depart_page)):
            raise _refus(section + " : compteurs non entiers exacts")
        if (total > maximum or depart_page != curseur or nombre != len(bloc[cle])
                or curseur + nombre > total or reste != total - curseur - nombre):
            raise _refus(section + " : compteurs ou curseur incohérents")
        if reste:
            if not nombre or not _entier(prochain) or prochain != curseur + nombre or not curseur < prochain <= total:
                raise _refus(section + " : absence de progression stricte")
        elif prochain is not None:
            raise _refus(section + " : curseur terminal non nul")
        if section == "observations":
            generiques = page.get("snapshots_generiques_non_couverts")
            if not _entier(generiques) or generiques > maximum:
                raise _refus(section + " : compte global non entier exact ou hors registre")
        if section in ("suivis", "alertes"):
            porteur = page if section == "suivis" else page.get("suivis")
            if not isinstance(porteur, dict) or not _entier(porteur.get("total")):
                raise _refus(section + " : total du bilan non entier exact")
            compteurs = porteur.get("compteurs")
            if (not isinstance(compteurs, dict) or set(compteurs) != set(_COMPTEURS)
                    or not all(_entier(v) and v <= porteur["total"] for v in compteurs.values())):
                raise _refus(section + " : compteurs du bilan non entiers exacts ou incohérents")
            if section == "alertes" and (not isinstance(porteur.get("vue_bilan"), str)
                    or not _EMPREINTE.fullmatch(porteur["vue_bilan"])):
                raise _refus(section + " : vue du bilan invalide")
        vue_page = page.get("vue")
        if not isinstance(vue_page, str) or not _EMPREINTE.fullmatch(vue_page):
            raise _refus(section + " : vue native invalide")
        types = {"observations": "OBSERVATIONS_CHANTIER_PERIODE", "alertes": "RAPPORT_PERIODE",
                 "suivis": "BILAN_SUIVIS_DECISION"}
        if page.get("type") != types[section] or page.get("debut") != debut or page.get("fin") != fin:
            raise _refus(section + " : type ou bornes natives incohérents")
        if _taille(page) > budget:
            raise _refus(section + " : budget natif dépassé")
        stable = copy.deepcopy(page)
        stable_bloc = stable["alertes_periode"] if section == "alertes" else stable
        for champ in (cle, "depart", "affichees", "reste", "prochain_depart"):
            stable_bloc.pop(champ, None)
        if premier is None:
            premier, entete, vue = copy.deepcopy(page), stable, vue_page
        elif stable != entete or vue_page != vue:
            raise _refus(section + " : en-tête ou vue natifs ont changé")
        if not all(isinstance(ligne, dict) for ligne in bloc[cle]):
            raise _refus(section + " : preuve native non objet")
        lignes.extend(copy.deepcopy(bloc[cle]))
        if not reste:
            if len(lignes) != total:
                raise _refus(section + " : flux incomplet")
            return premier, lignes
        curseur = prochain
    raise _refus(section + " : nombre maximal d'appels dépassé")


def assembler_rapport_activite(
    suivis, clotures, alertes, maillons, publications, debut, fin,
    depart=0, vue_attendue=None, *, budget_caracteres,
) -> dict[str, Any]:
    """Page à curseur global ; preuves natives complètes copiées, budget entier fourni inchangé."""
    if not _entier(depart):
        raise ValueError("REJ-ACTIVITE-ARGUMENT : depart entier supérieur ou égal à 0 attendu")
    if not _entier(budget_caracteres) or budget_caracteres == 0:
        raise ValueError("REJ-ACTIVITE-ARGUMENT : budget_caracteres entier strictement positif attendu")
    if vue_attendue is not None and (not isinstance(vue_attendue, str) or not _EMPREINTE.fullmatch(vue_attendue)):
        raise ValueError("REJ-ACTIVITE-ARGUMENT : vue_attendue empreinte hexadécimale de 64 caractères attendue")
    if depart > 0 and vue_attendue is None:
        raise ValueError("REJ-ACTIVITE-VUE : vue_attendue requise pour depart > 0")
    if not all(isinstance(source, (list, tuple)) for source in (suivis, clotures, alertes, maillons)):
        raise ValueError("REJ-ACTIVITE-ARGUMENT : quatre registres complets attendus")
    if not isinstance(publications, dict):
        raise ValueError("REJ-ACTIVITE-ARGUMENT : correspondance des publications attendue")
    suivis, clotures, alertes, maillons, publications = copy.deepcopy(
        (suivis, clotures, alertes, maillons, publications)
    )
    # Aucune exception native n'est interceptée, y compris sur les dernières pages.
    obs, lignes_obs = _materialiser(lister_observations_chantier, (maillons, publications),
                                  "observations", len(maillons), debut, fin, budget_caracteres)
    ancien, lignes_alertes = _materialiser(assembler_rapport_periode, (suivis, clotures, alertes),
                                         "alertes", len(alertes), debut, fin, budget_caracteres)
    bilan, lignes_suivis = _materialiser(bilan_suivis_decision, (suivis, clotures),
                                       "suivis", len(suivis), debut, fin, budget_caracteres)
    compteurs_bilan = bilan.get("compteurs")
    if (not isinstance(compteurs_bilan, dict) or set(compteurs_bilan) != set(_COMPTEURS)
            or not all(_entier(v) and v <= bilan["total"] for v in compteurs_bilan.values())):
        raise _refus("compteurs du bilan invalides")
    if ancien.get("suivis") != {"compteurs": compteurs_bilan, "total": bilan["total"], "vue_bilan": bilan["vue"]}:
        raise _refus("compteurs ou vue du bilan divergents dans le rapport natif")
    generiques = obs.get("snapshots_generiques_non_couverts")
    if not _entier(generiques) or generiques > len(maillons):
        raise _refus("compte global des snapshots génériques invalide")
    vue = empreinte({"type": _TYPE, "debut": debut, "fin": fin, "suivis": list(suivis),
                     "clotures": list(clotures), "alertes": list(alertes), "maillons": list(maillons),
                     "publications": publications})
    if vue_attendue is not None and vue_attendue != vue:
        raise ValueError("REJ-ACTIVITE-VUE-PERIMEE : sources ou bornes modifiées ; reprendre à depart=0")
    lignes = [
        {"section": section, "preuve": copy.deepcopy(ligne)}
        for section, source in (("observations", lignes_obs), ("alertes", lignes_alertes), ("suivis", lignes_suivis))
        for ligne in source
    ]
    total = len(lignes)
    if depart > total:
        raise ValueError("REJ-ACTIVITE-ARGUMENT : depart au-delà de la fin")
    compteurs = {"observations": obs["total"], "alertes": ancien["alertes_periode"]["total"],
                 "suivis": bilan["total"], **compteurs_bilan}

    def page(curseur, preuves):
        dernier = curseur + len(preuves)
        reste = total - dernier
        return {"type": _TYPE, "debut": debut, "fin": fin, "vue": vue,
                "compteurs": dict(compteurs), "snapshots_generiques_non_couverts": generiques,
                "total": total, "depart": curseur, "affichees": len(preuves), "reste": reste,
                "prochain_depart": dernier if reste else None, "ordre": _ORDRE,
                "lignes": copy.deepcopy(preuves), "bases_temporelles": dict(_BASES),
                "manques": copy.deepcopy(list(_MANQUES)), "statut": "NON_VALIDE",
                "actualite_metier": "NON_EVALUEE", "rapport_complet": False}

    # Toute ligne, même d'une section ultérieure, doit tenir avec son en-tête réel.
    if _taille(page(total, [])) > budget_caracteres or _taille(page(0, [])) > budget_caracteres:
        raise ValueError("REJ-ACTIVITE-BORNE : en-tête et manques au-delà du budget fourni")
    for rang, ligne in enumerate(lignes):
        if _taille(page(rang, [ligne])) > budget_caracteres:
            raise ValueError("REJ-ACTIVITE-BORNE : une preuve complète dépasse le budget fourni, aucune troncature")
    nombre = 0
    while depart + nombre < total and _taille(page(depart, lignes[depart:depart + nombre + 1])) <= budget_caracteres:
        nombre += 1
    return page(depart, lignes[depart:depart + nombre])
