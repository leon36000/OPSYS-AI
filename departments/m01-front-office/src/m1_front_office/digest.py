"""Produit un digest texte agrégé, déterministe et sans fuite de données sensibles."""

import collections

CANAUX = ["telephone", "courriel", "formulaire", "texte"]
TYPES = ["signal", "transition_phase", "lead_emis", "chiffrage_emis", "alerte"]
# Le suivi des conversations ouvertes (PLAN T4.4, `suivi.py`) n'est pas un type de la grille canal x type : il a ses
# propres lignes, écrites seulement quand le registre en porte.
TYPE_SUIVI = "suivi_conversation"


def _canal_de(entree: dict) -> str:
    """Canal d'une entrée : premier niveau prioritaire, replié sur payload.canal.

    Correctif d'audit : les entrées réellement écrites par le pipeline (ex. les
    transitions de phase composées par le tool layer) ne portent pas toujours le
    canal au premier niveau. S'en tenir au seul premier niveau les classait
    systématiquement en « non classées », même quand l'information existait.
    """
    canal = entree.get("canal")
    if not canal:
        payload = entree.get("payload")
        if isinstance(payload, dict):
            canal = payload.get("canal")
    return canal or ""


def _correspond_a_la_date(entree: dict, date_reference: str) -> bool:
    """Vrai si l'entrée compte pour cette date_reference.

    Correctif d'audit : date_reference ne servait qu'à l'en-tête du digest, sans
    jamais filtrer les entrées — un registre contenant plusieurs jours voyait
    tout compté dans n'importe quel digest, quelle que soit la date demandée.
    Une entrée SANS horodatage n'est jamais exclue (compatibilité avec les
    appelants historiques qui n'en fournissent pas) ; une entrée horodatée un
    autre jour que date_reference est exclue, car c'est précisément le filtre
    que la date de référence est censée appliquer.
    """
    horodatage = entree.get("horodatage")
    if not isinstance(horodatage, str) or not horodatage:
        return True
    return horodatage[:10] == date_reference


def _lignes_de_suivi(entrees: list[dict], date_reference: str) -> list[str]:
    """Les conversations ouvertes, relues des lignes `suivi_conversation` (une par message, la dernière dit où en est la
    conversation ; une conversation est identifiée par son client et son heure d'ouverture).

    - « à suivre » : conversations écrites ce jour dont la dernière ligne demande encore une action ;
    - « sans suivi » : conversations dont la fenêtre se termine ce jour (`a_faire_avant`) et dont la dernière ligne
      demande toujours une action : le client n'a jamais eu de suite. Chacune n'apparaît que dans le digest du jour de
      son échéance. Aucune horloge : la date de référence est fournie.

    Aucune ligne de suivi dans le registre : rien n'est ajouté au digest (sortie inchangée)."""
    derniere: dict[tuple, dict] = {}
    ecrites_ce_jour: set[tuple] = set()
    for entree in entrees:
        if entree.get("type_entree") != TYPE_SUIVI:
            continue
        conversation = (entree.get("conversation_id"), entree.get("ouverte_le"))
        derniere[conversation] = entree
        if _correspond_a_la_date(entree, date_reference):
            ecrites_ce_jour.add(conversation)
    if not derniere:
        return []
    ouvertes = {c: e for c, e in derniere.items() if e.get("statut") == "ouverte" and e.get("prochaine_action")}
    a_suivre = sum(1 for c in ouvertes if c in ecrites_ce_jour)
    sans_suivi = sum(
        1 for e in ouvertes.values() if str(e["prochaine_action"].get("a_faire_avant", ""))[:10] == date_reference)
    return [
        f"- conversations ouvertes à suivre : {a_suivre}",
        f"- conversations sans suivi à l'échéance de leur fenêtre : {sans_suivi}",
    ]


def produire_digest(entrees: list[dict], date_reference: str) -> str:
    """Génère un rapport agrégé en français pour la période de référence.

    * Byte-identique pour les mêmes entrées et date_reference.
    * Indépendant de l'ordre des entrées.
    * Ne contient jamais de prix ni de date d'engagement issus des payloads.
    * Pour une liste vide, produit un texte non‑vide signalant l'absence.
    * Une entrée horodatée un autre jour que date_reference n'est comptée
      dans aucune case : date_reference filtre réellement la période.
    * Les entrées dont le canal ou le type_entree ne sont pas reconnus sont
      comptabilisées séparément sous la rubrique "entrées non classées".
    * Les lignes `suivi_conversation` (conversations ouvertes, PLAN T4.4) ne sont jamais « non classées » : elles
      donnent deux lignes de plus, seulement si le registre en porte (voir `_lignes_de_suivi`). Les compteurs restent
      indépendants de l'ordre ; le suivi, lui, lit l'ordre du registre (la dernière ligne d'une conversation fait foi).
    """
    if not entrees:
        return f"Absence d'activité enregistrée pour la période de référence {date_reference}."

    compteur = collections.Counter()
    non_classes = 0
    for entree in entrees:
        if entree.get("type_entree") == TYPE_SUIVI:
            continue  # compté à part (`_lignes_de_suivi`), jamais parmi les « entrées non classées »
        if not _correspond_a_la_date(entree, date_reference):
            continue
        canal = _canal_de(entree)
        type_entree = entree.get("type_entree", "")
        if canal in CANAUX and type_entree in TYPES:
            compteur[(canal, type_entree)] += 1
        else:
            non_classes += 1

    lignes = [f"DIGEST - Période de référence : {date_reference}"]
    for canal in CANAUX:
        for type_ in TYPES:
            nb = compteur.get((canal, type_), 0)
            lignes.append(f"- {canal}: {type_}: {nb}")
    lignes.extend(_lignes_de_suivi(entrees, date_reference))
    lignes.append(f"- entrées non classées : {non_classes}")
    return "\n".join(lignes)
