"""Brouillon de temps — pont M4 -> M5 (T1.1-c#3/#4, M4.4, M4.23).

Agrège, pour une période donnée, les pointages des interventions déjà
COMPLÉTÉES (celles qui ont un WCT — ``outbox.lire_outbox``) en lignes
``{technicien_id, intervention_id, date, minutes_travail, minutes_deplacement,
minutes_pause}``. AGENTS.md : « le code calcule, le LLM orchestre » — ce
brouillon ne porte AUCUN taux ni montant (garde structurelle ci-dessous, sur
le modèle de ``m6_material_control.contrats_sortie.CLES_MONETAIRES_INTERDITES``) ;
M5 validera la paie plus tard.

Module pur : aucun import d'``opsys``, aucune horloge — la période est fournie
par l'appelant (déterminisme, cf. ``digest.py``).
"""
from datetime import datetime
from typing import Any

from . import outbox, verdicts

# T1.1-c#3 : garde structurelle contre toute fuite d'un taux ou d'un montant
# dans le brouillon de temps — sur le modèle EXACT de
# m6_material_control.contrats_sortie.CLES_MONETAIRES_INTERDITES (lu, jamais
# importé : M4 ne dépend pas de M6). M4 rapporte des MINUTES ; convertir des
# minutes en argent est une décision de paie qui appartient à M5 seul.
CLES_PAIE_INTERDITES = frozenset({
    "taux", "taux_horaire", "montant", "cout", "salaire", "prix", "solde",
    "remuneration",
})

CLES_LIGNE_TEMPS = (
    "technicien_id", "intervention_id", "date",
    "minutes_travail", "minutes_deplacement", "minutes_pause",
)

__all__ = [
    "CLES_PAIE_INTERDITES",
    "CLES_LIGNE_TEMPS",
    "produire_brouillon_temps",
    "depassement_detecte",
]


def _verifier_absence_cles_paie(valeur: Any) -> None:
    """Lève ValueError si une clé de CLES_PAIE_INTERDITES apparaît, à
    n'importe quelle profondeur, dans ``valeur``. Invariant INTERNE (le
    brouillon est entièrement construit par ce module, jamais par l'appelant)
    — une violation ici est un bogue de ce fichier, pas une entrée rejetable."""
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            if cle in CLES_PAIE_INTERDITES:
                raise ValueError(f"Clé de paie interdite détectée : {cle}")
            _verifier_absence_cles_paie(sous_valeur)
    elif isinstance(valeur, list):
        for element in valeur:
            _verifier_absence_cles_paie(element)


def _valider_periode(periode: Any) -> tuple[bool, dict | None]:
    """Valide ``periode`` = {debut, fin}, deux dates AAAA-MM-JJ, bornes
    incluses, debut <= fin. Même rigueur que ``digest.produire_digest`` pour
    ``date_cible`` : fromisoformat seul accepterait une date-heure, ce qui
    fausserait le filtre par préfixe de date des WCT."""
    if not isinstance(periode, dict) or set(periode.keys()) != {"debut", "fin"}:
        return False, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="periode doit être {debut, fin}"
        )
    for cle in ("debut", "fin"):
        valeur = periode[cle]
        if not isinstance(valeur, str) or valeur == "":
            return False, verdicts.construire_verdict(
                "REJ-CHAMP-VIDE", detail=f"periode.{cle} vide"
            )
        try:
            jour = datetime.fromisoformat(valeur).date()
        except (ValueError, TypeError):
            return False, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE", detail=f"periode.{cle} mal formée"
            )
        if jour.isoformat() != valeur:
            return False, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail=f"periode.{cle} doit être exactement AAAA-MM-JJ, sans heure ni fuseau",
            )
    if periode["fin"] < periode["debut"]:
        return False, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="periode.fin antérieure à periode.debut"
        )
    return True, None


def depassement_detecte(minutes_totales: int, seuil_minutes: int) -> bool:
    """M4.4 — signale un dépassement d'heures : compare un TOTAL de minutes
    déjà calculé à un SEUIL fourni par l'appelant, jamais une constante de ce
    module (T1.1-c#4). Un seuil d'heures est légal ou contractuel, propre à
    chaque contexte (équipe, convention) — jamais universel, jamais codé en
    dur ici.

    Returns:
        bool : minutes_totales > seuil_minutes.

    Raises:
        ValueError: si l'un des deux arguments n'est pas un entier positif —
        les deux sont déjà produits par du code déterministe en amont
        (``produire_brouillon_temps`` ou l'appelant), jamais saisis librement.
    """
    for nom, valeur in (("minutes_totales", minutes_totales), ("seuil_minutes", seuil_minutes)):
        if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < 0:
            raise ValueError(f"{nom} doit être un entier positif : {valeur!r}")
    return minutes_totales > seuil_minutes


def produire_brouillon_temps(registre_cible, periode, seuil_minutes=None):
    """
    Brouillon de temps agrégé par intervention COMPLÉTÉE, pour la période
    donnée (T1.1-c#3).

    Args:
        registre_cible: instance de Registre.
        periode: {"debut": "AAAA-MM-JJ", "fin": "AAAA-MM-JJ"}, bornes incluses
            — la date de chaque ligne est celle de la complétion
            (wct.horodatage_completion, préfixe de date).
        seuil_minutes: optionnel (T1.1-c#4). Fourni, chaque technicien dont le
            total de minutes_travail sur la période dépasse ce seuil est
            signalé dans "depassements" (``depassement_detecte``). Omis
            (None), aucun dépassement n'est signalé — jamais un seuil par
            défaut inventé.

    Returns:
        (brouillon, None) ou (None, verdict). ``brouillon`` =
        {"periode": {...}, "lignes": [...], "depassements": [...]}. Chaque
        ligne : {technicien_id, intervention_id, date, minutes_travail,
        minutes_deplacement, minutes_pause} — AUCUNE autre clé (garde
        structurelle ci-dessus).
    """
    ok_periode, verdict_periode = _valider_periode(periode)
    if not ok_periode:
        return None, verdict_periode

    seuil_invalide = seuil_minutes is not None and (
        isinstance(seuil_minutes, bool) or not isinstance(seuil_minutes, int) or seuil_minutes < 0
    )
    if seuil_invalide:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="seuil_minutes doit être un entier positif ou null"
        )

    lignes = []
    totaux_par_technicien = {}
    for _, wct in outbox.lire_outbox(registre_cible):
        date_wct = wct["horodatage_completion"][:10]
        if not (periode["debut"] <= date_wct <= periode["fin"]):
            continue

        intervention_id = wct["intervention_id"]
        technicien_id = wct["technicien_id"]
        minutes_travail = wct["duree_reelle_minutes"]

        minutes_deplacement, code_deplacement = outbox.calculer_minutes_deplacement(
            registre_cible, intervention_id
        )
        if minutes_deplacement is None:
            return None, verdicts.construire_verdict(
                code_deplacement,
                detail=f"temps de déplacement indéterminable pour {intervention_id}",
            )
        minutes_pause, code_pause = outbox.calculer_minutes_pause(registre_cible, intervention_id)
        if minutes_pause is None:
            return None, verdicts.construire_verdict(
                code_pause,
                detail=f"temps de pause indéterminable pour {intervention_id}",
            )

        lignes.append({
            "technicien_id": technicien_id,
            "intervention_id": intervention_id,
            "date": date_wct,
            "minutes_travail": minutes_travail,
            "minutes_deplacement": minutes_deplacement,
            "minutes_pause": minutes_pause,
        })
        totaux_par_technicien[technicien_id] = (
            totaux_par_technicien.get(technicien_id, 0) + minutes_travail
        )

    # Ordre déterministe, indépendant de l'ordre d'écriture du registre.
    lignes.sort(key=lambda ligne: (ligne["date"], ligne["technicien_id"], ligne["intervention_id"]))

    depassements = []
    if seuil_minutes is not None:
        for technicien_id in sorted(totaux_par_technicien):
            total = totaux_par_technicien[technicien_id]
            depassements.append({
                "technicien_id": technicien_id,
                "minutes_totales": total,
                "depassement_detecte": depassement_detecte(total, seuil_minutes),
            })

    brouillon = {
        "periode": {"debut": periode["debut"], "fin": periode["fin"]},
        "lignes": lignes,
        "depassements": depassements,
    }
    _verifier_absence_cles_paie(brouillon)  # garde structurelle, jamais seulement documentée
    return brouillon, None
