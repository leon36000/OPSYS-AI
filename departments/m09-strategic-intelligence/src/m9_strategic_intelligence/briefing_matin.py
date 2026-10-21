"""Briefing du matin — assemblage déterministe, sourcé et BORNÉ (PLAN T3.2, T1.5-d,
DEFINITION-PRODUIT.md M9.5).

Module PUR (ADR-0009) : aucun import d'``opsys``. ``assembler_briefing_matin`` compose, pour un
instant de référence FOURNI (``maintenant``, RFC 3339 — jamais l'horloge : garde HORLOGE_INTERNE
de ``conformite.py``), quatre sections ORDONNÉES à partir de candidats DÉJÀ LUS par l'appelant
(``outils.py``, seul point de contact avec le socle, cf. ``docs/architecture/DEPARTEMENTS.md``) :

1. ``decisions_en_attente`` — la file du propriétaire (``opsys.approbations.file_proprietaire``),
   passée quasi telle quelle : c'est la forme que l'écran mobile admin ``strategy-decisions``
   (T1.4, DEFINITION-PRODUIT.md §9.8) consommera directement, jamais reformatée ici. Aucun filtre
   de date : la file est toujours « ce qui est actuellement en attente ».
2. ``alertes_m8`` — alertes proposées par M8 et reçues du bus (``m8.alerte_proposee``,
   ``outils._recevoir_alerte_proposee``), filtrées à la fenêtre de jours qui se termine au JOUR de
   ``maintenant`` (boucle M8 → M9 des preuves, ADR-0009 §3 : M9 ne lit jamais le registre M8
   directement). Fenêtre de 0 jour : le jour même, comportement historique. Une alerte de mesure de
   chantier porte l'instant du chantier, pas celui d'une évaluation du matin : sans fenêtre, celle
   d'un chantier fini la veille à 15 h n'aurait jamais paru le lendemain à 7 h.
3. ``faits_veille`` — derniers faits du bus déjà consolidés par M9 (registre de snapshots,
   alimenté en second ordre par les preuves de M8), filtrés à la VEILLE de ``maintenant``.
4. ``manques_pour_conclure`` — constat déterministe des sections 1 à 3 vides et des seuils que M8
   attend qu'on configure : jamais une interprétation, seulement le fait vérifiable qu'une source
   n'a rien rapporté (P2 DEFINITION-PRODUIT.md : « le système ose dire donnée pas fiable »).

Chaque section porte ``items`` (jamais fabriqué : une section sans donnée reste ``[]``, jamais
remplie) et ``vide`` (vrai seulement s'il n'existe AUCUN candidat, pas quand aucun n'est affiché).
Aucun texte libre n'est rédigé ici et aucun chiffre n'y est recalculé — v1 est un gabarit
déterministe, pas une rédaction (PLAN T3.2, point 3).

BORNE (T1.5-d) : la réponse d'un outil est tronquée par ``Capacites`` au-delà de
``jetons.LIMITE_SORTIE_DEFAUT`` (6 000 caractères) : au-delà d'environ 22 décisions en attente, le
briefing devenait illisible pour l'app. ``budget_caracteres`` (fourni par ``outils.py``, qui le tire
de la limite du socle) borne donc la taille SÉRIALISÉE, calculée par le code : les éléments sont
ajoutés à tour de rôle (alertes, décisions, faits) tant que le briefing entier tient. Ce qui ne
tient pas n'est JAMAIS perdu en silence : ``affichage`` dit combien d'éléments restent, où, et
comment les lire (``m9_lire_suite_briefing``, ``lire_suite_section``, à partir d'un ``depart``).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import encodage

__all__ = ["ORDRE_SECTIONS", "assembler_briefing_matin", "lire_suite_section"]

# Forme attendue de chaque candidat en entrée. Copie locale (jamais un import inter-département,
# DA-M9-04) des champs garantis par leur producteur respectif :
# - décision : `opsys.approbations.CHAMPS_ATTENTE` + `departement`, ajouté par `file_proprietaire`.
# - alerte : propriétés requises du catalogue `opsys.evenement/v1/m8.alerte_proposee`.
# - fait : `contrats.CHAMPS_SNAPSHOT_MODULE` (module_source, horodatage, valeurs) — le maillon du
#   registre M9 porte aussi `index`/`hash_maillon`, non requis ici mais jamais retiré (traçabilité).
_CHAMPS_DECISION = ("type", "id", "resume", "niveau", "depuis", "action_proposee", "departement")
_CHAMPS_ALERTE = (
    "evenement_id", "metric_id", "type_alerte", "quoi", "a_qui", "pourquoi", "preuve", "source",
    "horodatage_reference",
)
_CHAMPS_FAIT = ("module_source", "horodatage", "valeurs")

ORDRE_SECTIONS = ("decisions_en_attente", "alertes_m8", "faits_veille", "manques_pour_conclure")

# Sections qui portent une liste d'éléments (donc bornées et paginées), et ordre dans lequel le
# remplissage les sert : les alertes d'abord, qu'une pile de décisions ne doit jamais noyer.
_SECTIONS_A_ELEMENTS = ("decisions_en_attente", "alertes_m8", "faits_veille")
_ORDRE_REMPLISSAGE = ("alertes_m8", "decisions_en_attente", "faits_veille")

# Copie locale du type d'alerte de M8 (catalogue m8.alerte_proposee) : un rappel « seuil à configurer »
# n'est pas une alerte à lire mais un manque à combler ; il rejoint `manques_pour_conclure`.
_TYPE_ALERTE_SEUIL_A_CONFIGURER = "MESURE-SEUIL-A-CONFIGURER"
_OUTIL_SUITE = "m9_lire_suite_briefing"
_ESPACE_ID = "0" * 64  # gabarit de longueur d'une empreinte SHA-256 en hexadécimal


def _analyser_horodatage(horodatage: str) -> datetime:
    """Parse un horodatage ISO-8601, fuseau compris (copié-adapté de
    ``etat_consolide.py::_analyser_horodatage`` — même règle, patron M8 : sans fuseau explicite,
    traité comme UTC, jamais deviné autrement)."""
    valeur = horodatage[:-1] + "+00:00" if horodatage.endswith("Z") else horodatage
    analyse = datetime.fromisoformat(valeur)
    if analyse.tzinfo is None:
        analyse = analyse.replace(tzinfo=UTC)
    return analyse


def _jour_de(horodatage: str) -> date:
    """Date calendaire d'un horodatage, dans le fuseau où il est exprimé (aucune conversion vers
    un fuseau d'entreprise supposé — non déclaré ailleurs dans ce dépôt)."""
    return _analyser_horodatage(horodatage).date()


def _valider_champs(item: Any, champs: tuple[str, ...], contexte: str) -> dict[str, Any]:
    """Fail-closed (AGENTS.md) : un candidat sans les champs attendus est un refus nommé, jamais
    un élément ignoré en silence ni complété par une valeur devinée. Vérifie la PRÉSENCE des
    champs, jamais l'exhaustivité (un candidat peut porter des champs en plus, ex. `index` d'un
    maillon de registre — jamais rejeté pour ça, contrairement à `rapport_strategique.py`)."""
    if not isinstance(item, dict):
        raise ValueError(f"{contexte} : élément invalide, dict attendu, reçu {type(item).__name__}")
    manquants = [champ for champ in champs if champ not in item]
    if manquants:
        raise ValueError(f"{contexte} : champ(s) manquant(s) {manquants} dans {item!r}")
    return item


def _taille(objet: Any) -> int:
    """Taille sérialisée EXACTE telle que `Capacites._tronquer` la mesure (`json.dumps`, sans
    échappement ASCII) : la borne se calcule sur ce que le modèle recevrait, jamais une estimation."""
    return len(json.dumps(objet, ensure_ascii=False))


def _valider_fenetre(fenetre_alertes_jours: Any) -> int:
    invalide = (
        isinstance(fenetre_alertes_jours, bool)
        or not isinstance(fenetre_alertes_jours, int)
        or fenetre_alertes_jours < 0
    )
    if invalide:
        raise ValueError(f"fenetre_alertes_jours : entier positif ou nul attendu, reçu {fenetre_alertes_jours!r}")
    return fenetre_alertes_jours


def _preparer(
    maintenant: str,
    decisions_en_attente: list[dict[str, Any]],
    alertes_m8: list[dict[str, Any]],
    faits_bus: list[dict[str, Any]],
    fenetre_alertes_jours: int,
) -> dict[str, Any]:
    """Filtre et trie les candidats (déterministe, indépendant de l'ordre d'entrée) : les listes
    COMPLÈTES de chaque section, avant toute borne, et les manques."""
    fenetre = _valider_fenetre(fenetre_alertes_jours)
    jour = _jour_de(maintenant)
    veille = jour - timedelta(days=1)
    debut_alertes = jour - timedelta(days=fenetre)

    decisions = [_valider_champs(item, _CHAMPS_DECISION, "decisions_en_attente") for item in decisions_en_attente]
    decisions = sorted(decisions, key=lambda item: (item["depuis"], item["id"]))

    alertes = [_valider_champs(item, _CHAMPS_ALERTE, "alertes_m8") for item in alertes_m8]
    alertes = [item for item in alertes if debut_alertes <= _jour_de(item["horodatage_reference"]) <= jour]
    rappels = [item for item in alertes if item["type_alerte"] == _TYPE_ALERTE_SEUIL_A_CONFIGURER]
    alertes = sorted(
        (item for item in alertes if item["type_alerte"] != _TYPE_ALERTE_SEUIL_A_CONFIGURER),
        key=lambda item: item["evenement_id"],
    )

    faits = [_valider_champs(item, _CHAMPS_FAIT, "faits_bus") for item in faits_bus]
    faits = [item for item in faits if _jour_de(item["horodatage"]) == veille]
    faits = sorted(faits, key=lambda item: (item["module_source"], item["horodatage"]))

    listes = {"decisions_en_attente": decisions, "alertes_m8": alertes, "faits_veille": faits}

    manques: list[dict[str, str]] = []
    if not decisions:
        manques.append({
            "section": "decisions_en_attente",
            "constat": "aucune décision en attente dans la file du propriétaire",
            "verifie": "opsys.approbations.file_proprietaire",
        })
    if not alertes:
        periode = (
            f"le {jour.isoformat()}" if fenetre == 0
            else f"la période du {debut_alertes.isoformat()} au {jour.isoformat()}"
        )
        manques.append({
            "section": "alertes_m8",
            "constat": f"aucune alerte reçue de M8 (m8.alerte_proposee) pour {periode}",
            "verifie": "registre m09-strategic-intelligence/alertes_m8",
        })
    if not faits:
        manques.append({
            "section": "faits_veille",
            "constat": f"aucun fait consolidé reçu du bus pour la veille ({veille.isoformat()})",
            "verifie": "registre m09-strategic-intelligence/snapshots",
        })
    metriques_sans_seuil = sorted({item["metric_id"] for item in rappels})
    if metriques_sans_seuil:
        manques.append({
            "section": "alertes_m8",
            "constat": (
                f"seuil à configurer pour {len(metriques_sans_seuil)} métrique(s) de M8 "
                f"({', '.join(metriques_sans_seuil)}) : aucune alerte n'est possible tant que le seuil manque"
            ),
            "verifie": f"m8.alerte_proposee (type {_TYPE_ALERTE_SEUIL_A_CONFIGURER})",
        })
    return {"jour": jour, "veille": veille, "listes": listes, "manques": manques}


def _message_non_affiches(total: int, non_affiches: dict[str, int]) -> str:
    detail = ", ".join(f"{cle} : {reste}" for cle, reste in non_affiches.items() if reste)
    debut = "1 autre élément non affiché" if total == 1 else f"{total} autres éléments non affichés"
    return (
        f"{debut} ({detail}). Pour les lire, appeler {_OUTIL_SUITE} avec la section et le depart "
        "indiqués dans lire_la_suite."
    )


def _briefing(
    preparation: dict[str, Any], maintenant: str, affiches: dict[str, int], borne: int | None, taille: int,
    briefing_id: str | None,
) -> dict[str, Any]:
    """Le briefing pour un nombre d'éléments affichés par section. `briefing_id` `None` : calculé ;
    sinon imposé (gabarit de mesure, même longueur)."""
    listes = preparation["listes"]
    sections: dict[str, Any] = {
        cle: {"items": listes[cle][:affiches[cle]], "vide": not listes[cle]} for cle in _SECTIONS_A_ELEMENTS
    }
    manques = preparation["manques"]
    sections["manques_pour_conclure"] = {"items": manques, "vide": not manques}

    non_affiches = {cle: len(listes[cle]) - affiches[cle] for cle in _SECTIONS_A_ELEMENTS}
    total = sum(non_affiches.values())
    affichage = {
        "borne_caracteres": borne,
        "taille_caracteres": taille,
        "complet": total == 0,
        "n_non_affiches": total,
        "non_affiches": non_affiches,
        "message": _message_non_affiches(total, non_affiches) if total else None,
        "lire_la_suite": [
            {
                "section": cle, "reste": reste, "outil": _OUTIL_SUITE,
                "arguments": {"maintenant": maintenant, "section": cle, "depart": affiches[cle]},
            }
            for cle, reste in non_affiches.items() if reste
        ],
    }
    if briefing_id is None:
        briefing_id = encodage.empreinte("BRIEFING_MATIN", preparation["jour"].isoformat(), sections, non_affiches)
    return {
        "type": "BRIEFING_MATIN",
        "jour": preparation["jour"].isoformat(),
        "veille": preparation["veille"].isoformat(),
        "ordre_sections": list(ORDRE_SECTIONS),
        "sections": sections,
        "affichage": affichage,
        "briefing_id": briefing_id,
    }


def _repartir(preparation: dict[str, Any], maintenant: str, borne: int | None) -> dict[str, int]:
    """Nombre d'éléments affichés par section. Sans borne : tous. Avec borne : un élément à la fois,
    à tour de rôle (alertes, décisions, faits), tant que le briefing ENTIER — squelette, manques,
    message et consignes de lecture compris — tient sous la borne. Une section s'arrête à son premier
    élément qui ne tient pas (l'ordre est conservé, jamais un élément sauté)."""
    listes = preparation["listes"]
    if borne is None:
        return {cle: len(listes[cle]) for cle in _SECTIONS_A_ELEMENTS}

    def tient(affiches: dict[str, int]) -> bool:
        return _taille(_briefing(preparation, maintenant, affiches, borne, borne, _ESPACE_ID)) <= borne

    affiches = dict.fromkeys(_SECTIONS_A_ELEMENTS, 0)
    if not tient(affiches):
        raise ValueError(f"le squelette du briefing dépasse à lui seul la borne de {borne} caractères")
    actives = [cle for cle in _ORDRE_REMPLISSAGE if listes[cle]]
    while actives:
        for cle in list(actives):
            essai = {**affiches, cle: affiches[cle] + 1}
            if tient(essai):
                affiches = essai
                if essai[cle] == len(listes[cle]):
                    actives.remove(cle)
            else:
                actives.remove(cle)
    return affiches


def assembler_briefing_matin(
    maintenant: str,
    decisions_en_attente: list[dict[str, Any]],
    alertes_m8: list[dict[str, Any]],
    faits_bus: list[dict[str, Any]],
    *,
    budget_caracteres: int | None = None,
    fenetre_alertes_jours: int = 0,
) -> dict[str, Any]:
    """Assemble le briefing du matin pour ``maintenant`` (RFC 3339, fourni — jamais l'horloge).

    Chaque liste d'entrée est une liste de CANDIDATS déjà lus par l'appelant (``outils.py``) :
    cette fonction ne lit rien elle-même, ne filtre que par date et ne trie que pour la
    reproductibilité — elle n'ingère, n'invente ni ne résume aucun contenu.

    ``budget_caracteres`` : borne, en caractères, de la réponse SÉRIALISÉE (voir le docstring du
    module). ``None`` : aucune borne, tout est affiché. ``fenetre_alertes_jours`` : nombre de jours
    avant ``maintenant`` (inclus) dont les alertes de M8 sont lues ; 0 : le jour même.

    Retourne un dict portant, dans l'ordre de ``ORDRE_SECTIONS`` : ``jour``/``veille`` (dates
    calendaires ISO dérivées de ``maintenant``), ``sections`` (les quatre sections ci-dessus),
    ``affichage`` (borne, taille réelle, éléments non affichés et façon de les lire) et
    ``briefing_id`` (empreinte déterministe du contenu affiché, ``encodage.empreinte``).
    """
    if budget_caracteres is not None and (
        isinstance(budget_caracteres, bool) or not isinstance(budget_caracteres, int) or budget_caracteres < 1
    ):
        raise ValueError(f"budget_caracteres : entier strictement positif attendu, reçu {budget_caracteres!r}")
    preparation = _preparer(maintenant, decisions_en_attente, alertes_m8, faits_bus, fenetre_alertes_jours)
    affiches = _repartir(preparation, maintenant, budget_caracteres)

    # `taille_caracteres` fait partie de ce qu'elle mesure : point fixe, atteint en deux tours au plus
    # (seul le nombre de chiffres peut changer).
    taille = 0
    for _ in range(4):
        briefing = _briefing(preparation, maintenant, affiches, budget_caracteres, taille, None)
        mesuree = _taille(briefing)
        if mesuree == taille:
            return briefing
        taille = mesuree
    raise ValueError("la taille du briefing ne se stabilise pas")


def lire_suite_section(
    maintenant: str,
    section: str,
    depart: int,
    decisions_en_attente: list[dict[str, Any]],
    alertes_m8: list[dict[str, Any]],
    faits_bus: list[dict[str, Any]],
    *,
    budget_caracteres: int,
    fenetre_alertes_jours: int = 0,
) -> dict[str, Any]:
    """Les éléments d'UNE section du briefing à partir de ``depart`` (indice dans la liste complète,
    même filtre et même ordre que ``assembler_briefing_matin``), autant que la borne en laisse
    tenir. Rend ``prochain_depart`` (``None`` à la fin) : la suite se lit page après page, sans rien
    omettre. Fail-closed : section inconnue, ``depart`` invalide ou au-delà de la fin, ou un seul
    élément plus gros que la borne (une page vide ne ferait jamais progresser la lecture)."""
    if section not in _SECTIONS_A_ELEMENTS:
        raise ValueError(f"section : l'une de {list(_SECTIONS_A_ELEMENTS)} attendue, reçu {section!r}")
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        raise ValueError(f"depart : entier positif ou nul attendu, reçu {depart!r}")
    preparation = _preparer(maintenant, decisions_en_attente, alertes_m8, faits_bus, fenetre_alertes_jours)
    elements = preparation["listes"][section]
    total = len(elements)
    if depart > total:
        raise ValueError(f"depart {depart} au-delà de la fin de la section {section} ({total} éléments)")

    def page(nombre: int) -> dict[str, Any]:
        fin = depart + nombre
        reste = total - fin
        return {
            "type": "BRIEFING_MATIN_SUITE",
            "jour": preparation["jour"].isoformat(),
            "section": section,
            "depart": depart,
            "total": total,
            "affiches": nombre,
            "reste": reste,
            "prochain_depart": fin if reste else None,
            "message": (
                f"{reste} autres éléments non affichés dans cette section : poursuivre avec depart={fin}."
                if reste > 1 else (f"1 autre élément non affiché : poursuivre avec depart={fin}." if reste else None)
            ),
            "items": elements[depart:fin],
        }

    nombre = 0
    while depart + nombre < total and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if nombre == 0 and depart < total:
        raise ValueError(
            f"un seul élément de {section} dépasse la borne de {budget_caracteres} caractères : "
            "impossible de le lire par page"
        )
    return page(nombre)
