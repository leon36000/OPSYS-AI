"""Paquets de contexte en couches pour une affaire (PLAN T3.3, P11 — économie de tokens).

Assemble un paquet en QUATRE couches ORDONNÉES pour une affaire (``lead_id``) :

1. ``regles_entreprise``   — décisions M10 de portée générale actuellement ``validee`` (dernier
                              statut connu, ``decisions.decisions_par_statut``) ;
2. ``faits_affaire``       — faits durables de l'affaire, produits par la consolidation nocturne
                              (``consolidation.py``) ;
3. ``evenements_recents``  — événements bruts de l'affaire au registre Événements : les faits de l'amont (lead
                              qualifié, client associé, devis accepté, devis sans réponse, PLAN T4.18), le WCT, la
                              variance. Chacun porte l'heure de l'ÉVÉNEMENT, jamais celle de M10 ;
4. ``signaux_non_resolus`` — signaux critiques de l'affaire avec leur cycle de vie (``signaux.py``) :
                              les OUVERTS d'abord, puis les pris en compte, puis les derniers CLOS avec
                              qui les a clos et pourquoi. Un signal ne sort de « ouvert » que par un humain
                              identifié (ou par la règle écrite de ``signaux.py``), jamais par le modèle.

Chaque couche est bornée par un budget de CARACTÈRES calculé par le code (jamais estimé par un
modèle, AGENTS.md) ; une couche qui dépasse son budget ou son nombre maximal de faits est tronquée
et le DIT explicitement (``tronque``, ``nb_omis``). Une couche sans fait est déclarée VIDE
(``vide: true``), jamais silencieusement absente. Chaque fait porte sa provenance : ``source``,
``horodatage``, ``identifiant`` — rien n'est inventé — et son niveau de ``confidentialite``.

Le BUDGET, tel que ce module le calcule (PLAN T4.18-b : il est documenté ici, dans le README de M10 et dans
ADR-0010, et un test lit ces deux textes contre le code) :

- le paquet a un budget de ``BUDGET_CARACTERES_DEFAUT`` = 4 000 caractères, partagé également entre les quatre couches
  (``budget_par_couche`` : 1 000 chacune, division entière) ; une couche compte au plus
  ``NB_FAITS_MAX_PAR_COUCHE_DEFAUT`` = 5 faits. Ce budget mesure les FAITS seuls : le cadrage (les blocs ci-dessous,
  les titres que le core ajoute) n'en fait pas partie ;
- une couche garde ses faits du PLUS RÉCENT au plus ancien, et s'arrête au premier des deux plafonds atteint (5 faits,
  ou 1 000 caractères). Un fait pèse ce que pèse son JSON : 180 à 270 caractères pour un fait de l'historique avec des
  identifiants de 64 caractères, donc quatre tiennent presque toujours (cinq seulement avec les faits les plus
  courts) : c'est le plafond des caractères qui coupe, rarement celui des 5 faits ;
- le PREMIER fait d'une couche est toujours gardé, même s'il dépasse le budget de sa couche : une couche n'est jamais
  vide alors que des faits existent ;
- ce qui ne tient pas est OMIS par le bout ANCIEN, compté (``nb_omis``) et jamais rendu. Dans la couche des événements,
  c'est l'historique de l'affaire qui s'amenuise : une affaire complète (lead, client, devis envoyé, accepté, sans
  réponse, travaux terminés, variance) compte six à huit faits visibles selon l'agent et le nombre de devis, et son
  ORIGINE, le plus ancien, sort la première.
  D'où deux blocs ci-dessous : l'un garde l'origine que la troncature a omise, l'autre dit ce qu'elle a omis.

Blocs de synthèse, calculés sur TOUS les éléments, jamais sur ce que la troncature a laissé :
- ``signaux`` : nombre de signaux ouverts, pris en compte, clos. Le core s'y fie pour bloquer une action
  N3 ou plus tant qu'un signal est ouvert, même si la couche a dû en omettre un ;
- ``confidentialite`` : l'agent pour qui le paquet est assemblé, la version de la règle
  (``confidentialite.py``) et le NOMBRE d'éléments retenus faute de besoin d'en connaître. Un élément
  retenu n'est jamais rendu, ni son contenu ni son identifiant. Sans agent nommé, la vue est la plus
  restrictive ;
- ``affaire`` (PLAN T4.18-b) : ``{connue, origine_recue, origine, verdict}``, ce que M10 sait de l'affaire elle-même
  (``amont.situation``). Une affaire dont il n'a reçu aucun fait est dite INCONNUE (``AMONT-AFFAIRE-INCONNUE``), au
  lieu de quatre couches vides qu'on lirait comme « rien à signaler » ; une affaire dont il n'a pas reçu l'étape qui
  l'ouvre est dite sans origine (``AMONT-ORIGINE-NON-RECUE``). Vocabulaire fermé, aucun renseignement personnel ;
- ``consolidation`` (PLAN T4.18-b) : ``{a_consolider, nb_a_consolider}``. Quand la couche des événements omet des
  faits, les jours de ces faits qu'aucun fait durable ne résume : au plus ``NB_JOURS_A_CONSOLIDER_MAX`` entrées
  ``{affaire_id, jour}``, les plus anciennes d'abord, ``nb_a_consolider`` disant le total. Chaque entrée est
  l'argument exact de ``m10_consolider_affaire``. Seuls comptent les faits que CET agent aurait pu voir : un fait
  retenu par confidentialité ne donne pas son jour.

Ces deux derniers blocs sont ADDITIFS : les quatre couches et leur ordre ne changent pas (le core les valide).

Module pur (DA-M10-08) : aucun import d'``opsys``. Les deux registres sont injectés par
l'appelant (``outils.py``), comme partout ailleurs dans ce paquet.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from . import affaire, amont, classification, confidentialite, consolidation, decisions, etapes, signaux

BUDGET_CARACTERES_DEFAUT = 4000
NB_FAITS_MAX_PAR_COUCHE_DEFAUT = 5
NB_JOURS_A_CONSOLIDER_MAX = 10
RESUME_MAX_CARACTERES = 200

COUCHE_REGLES_ENTREPRISE = "regles_entreprise"
COUCHE_FAITS_AFFAIRE = "faits_affaire"
COUCHE_EVENEMENTS_RECENTS = "evenements_recents"
COUCHE_SIGNAUX_NON_RESOLUS = "signaux_non_resolus"

_COUCHES_ORDRE = (COUCHE_REGLES_ENTREPRISE, COUCHE_FAITS_AFFAIRE, COUCHE_EVENEMENTS_RECENTS, COUCHE_SIGNAUX_NON_RESOLUS)


def budget_par_couche(budget_caracteres: int = BUDGET_CARACTERES_DEFAUT) -> int:
    """Budget de caractères de CHAQUE couche : celui du paquet, partagé également entre les quatre couches (division
    entière : 4 000 donnent 1 000, un reste n'est jamais dépensé)."""
    return budget_caracteres // len(_COUCHES_ORDRE)


def _resume_borne(texte: Any) -> str:
    texte = "" if texte is None else str(texte)
    if len(texte) <= RESUME_MAX_CARACTERES:
        return texte
    return texte[: RESUME_MAX_CARACTERES - 1] + "…"


def _fait(identifiant: str, horodatage: str, source: str, resume: Any, niveau: str) -> dict[str, str]:
    return {
        "identifiant": identifiant,
        "horodatage": horodatage,
        "source": source,
        "resume": _resume_borne(resume),
        "confidentialite": niveau,
    }


def _tri_recent_dabord(maillons: list[dict]) -> list[dict]:
    """Plus récent d'abord. Comparaison par datetime PARSÉ (pas par tri lexicographique du texte
    ISO) : deux horodatages à décalages horaires différents (ex. EDT/EST) ne se comparent pas
    correctement en texte brut."""
    return sorted(maillons, key=lambda m: datetime.fromisoformat(m["horodatage"]), reverse=True)


def _tronquer_couche(nom: str, faits: list[dict], budget_caracteres: int, n_max: int) -> dict[str, Any]:
    """Coupe ``faits`` (déjà triés) pour tenir dans ``budget_caracteres`` ET au plus ``n_max`` —
    dit TOUJOURS ce qu'elle a coupé (``nb_omis``), jamais un silence sur la troncature."""
    total_avant = len(faits)
    retenus: list[dict] = []
    caracteres = 0
    for fait in faits[:n_max]:
        taille = len(json.dumps(fait, ensure_ascii=False, sort_keys=True))
        if retenus and caracteres + taille > budget_caracteres:
            break
        retenus.append(fait)
        caracteres += taille
    nb_omis = total_avant - len(retenus)
    return {
        "nom": nom,
        "vide": len(retenus) == 0,
        "tronque": nb_omis > 0,
        "nb_total": total_avant,
        "nb_inclus": len(retenus),
        "nb_omis": nb_omis,
        "caracteres": caracteres,
        "faits": retenus,
    }


def _candidats_regles_entreprise(registre_affaires: Any) -> list[dict]:
    validees = _tri_recent_dabord(decisions.decisions_par_statut(registre_affaires, "validee"))
    return [
        _fait(m["ligne_id"], m["horodatage"], "m10:decision", m.get("raison"), confidentialite.niveau_de(m))
        for m in validees
    ]


def _candidats_faits_affaire(affaire_id: str, maillons_affaires: list[dict]) -> list[dict]:
    bruts = [
        m
        for m in maillons_affaires
        if m.get("type_entree") == consolidation.TYPE_ENTREE_FAIT and m.get("affaire_id") == affaire_id
    ]
    return [
        _fait(
            m["ligne_id"],
            m["horodatage"],
            "m10:consolidation",
            f"{m.get('jour')} : {m.get('resume')}",
            confidentialite.niveau_de(m),
        )
        for m in _tri_recent_dabord(bruts)
    ]


def _resume_evenement(maillon: dict, type_evenement: str | None, identifiant: str | None) -> str:
    if type_evenement == classification.TYPE_WCT:
        resume = f"WCT {identifiant} : durée réelle {maillon.get('duree_reelle_minutes')} min"
        if maillon.get("ecart_signale"):
            resume += ", écart signalé"
        return resume
    if type_evenement == classification.TYPE_VARIANCE:
        resume = f"Variance {identifiant} : {maillon.get('statut_variance')}"
        if maillon.get("signal_critique"):
            resume += ", signal critique"
        return resume
    if type_evenement == classification.TYPE_RENTABILITE:
        # Jamais un montant : l'entrée est FINANCIAL et ne sort dans aucun paquet ; ce résumé n'en porte pas
        # non plus, pour qu'un marquage manquant ne puisse pas devenir une fuite.
        return f"Rentabilité {identifiant} : {maillon.get('verdict')}"
    # Un fait de l'amont (PLAN T4.18) : son résumé est écrit dans `etapes.py`, sans montant ni texte libre.
    return etapes.resume(maillon) or "événement non classifié"


def _fait_evenement(maillon: dict) -> dict[str, str]:
    type_evenement = classification.type_evenement(maillon)
    # L'identifiant PUBLIC (wct_id / evenement_id), pas ligne_id (interne au registre) — même
    # convention que classification.py et audit.py. Repli sur ligne_id seulement si le maillon
    # n'a pas pu être classifié (defensive, ne devrait pas arriver ici : le registre Événements
    # ne contient que des WCT et des variances).
    identifiant = classification.identifiant(maillon) or maillon["ligne_id"]
    source = type_evenement or "inconnu"
    return _fait(
        identifiant,
        maillon["horodatage"],
        source,
        _resume_evenement(maillon, type_evenement, identifiant),
        confidentialite.niveau_de(maillon),
    )


def _candidats_signaux(signaux_de_laffaire: list[dict]) -> list[dict]:
    """Un fait par signal : provenance, état, qui l'a traité et quand ; le résumé dit aussi pourquoi."""
    candidats = []
    for signal in signaux_de_laffaire:
        fait = _fait(
            signal["signal_id"],
            signal["horodatage"],
            classification.TYPE_VARIANCE,
            signaux.resume(signal),
            signal["confidentialite"],
        )
        fait.update(etat=signal["etat"], traite_par=signal["traite_par"], traite_le=signal["traite_le"])
        candidats.append(fait)
    return candidats


def _candidats_evenements_recents(affaire_id: str, maillons_evenements: list[dict]) -> list[dict]:
    evenements = _tri_recent_dabord(classification.evenements_de_laffaire(affaire_id, maillons_evenements))
    return [_fait_evenement(m) for m in evenements]


def _couche(
    nom: str, agent: str | None, candidats: list[dict], budget: int, n_max: int
) -> tuple[dict[str, Any], int, list[dict]]:
    """Filtre par confidentialité AVANT la troncature (un élément retenu ne prend pas la place d'un autre et
    n'est pas compté comme omis par le budget), puis tronque. Rend ``(couche, nb_retenus, omis)`` : ``omis`` sont les
    faits que le budget a coupés (la troncature garde un PRÉFIXE de la liste triée, le plus récent d'abord)."""
    admis, nb_retenus = confidentialite.filtrer(nom, agent, candidats)
    couche = _tronquer_couche(nom, admis, budget, n_max)
    return couche, nb_retenus, admis[couche["nb_inclus"] :]


def _a_consolider(affaire_id: str, omis: list[dict], maillons_affaires: list[dict]) -> dict[str, Any]:
    """Les jours dont la couche des événements a omis un fait et qu'aucun fait durable ne résume (PLAN T4.18-b).

    Le jour est celui de l'événement tel qu'il est écrit (``consolidation.jour_de``), le critère de « consolidé » celui
    de ``consolider_affaire`` : chaque entrée est un appel valide de ``m10_consolider_affaire``, et le jour sort de la
    liste dès que l'appel est fait. Bornée à ``NB_JOURS_A_CONSOLIDER_MAX`` (les plus anciens d'abord) ; le total dit le
    reste."""
    jours = consolidation.jours_non_consolides(
        affaire_id, [consolidation.jour_de(fait["horodatage"]) for fait in omis], maillons_affaires
    )
    return {
        "a_consolider": [{"affaire_id": affaire_id, "jour": jour} for jour in jours[:NB_JOURS_A_CONSOLIDER_MAX]],
        "nb_a_consolider": len(jours),
    }


def _valider_entrees(
    affaire_id: Any, horodatage: Any, budget_caracteres: Any, n_faits_max_par_couche: Any, agent: Any
) -> None:
    if not affaire.valide(affaire_id):
        raise ValueError(
            "affaire_id invalide : le lead_id de l'affaire, ou <lead>~opp~<wct_id> pour l'opportunité que M2 ouvre "
            "(lettres, chiffres et ._:-, 197 caractères au plus)"
        )
    if not horodatage or not isinstance(horodatage, str):
        raise ValueError("horodatage requis (chaîne non vide)")
    if not isinstance(budget_caracteres, int) or isinstance(budget_caracteres, bool) or budget_caracteres <= 0:
        raise ValueError("budget_caracteres doit être un entier strictement positif")
    if (
        not isinstance(n_faits_max_par_couche, int)
        or isinstance(n_faits_max_par_couche, bool)
        or n_faits_max_par_couche <= 0
    ):
        raise ValueError("n_faits_max_par_couche doit être un entier strictement positif")
    if agent is not None and not confidentialite.agent_valide(agent):
        raise ValueError(f"agent invalide {agent!r} : un identifiant de département (ex. m03-estimation) ou rien")


def assembler_paquet_contexte(
    affaire_id: str,
    horodatage: str,
    registre_evenements: Any,
    registre_affaires: Any,
    *,
    budget_caracteres: int = BUDGET_CARACTERES_DEFAUT,
    n_faits_max_par_couche: int = NB_FAITS_MAX_PAR_COUCHE_DEFAUT,
    agent: str | None = None,
) -> dict[str, Any]:
    """Rend le paquet complet : ``{affaire_id, horodatage, budget_caracteres, caracteres_utilises,
    couches: [4 couches ordonnées], signaux, confidentialite, affaire, consolidation}``. Lève ``ValueError``
    (refus_metier, via ``outils.executer``) sur une entrée structurellement invalide — jamais une valeur inventée.
    ``affaire_id`` a la forme d'affaire commune au core et à M10 (``affaire.py``) : un lead, ou l'opportunité
    ``<lead>~opp~<wct_id>`` que M2 ouvre.

    ``agent`` : le département qui recevra le paquet, fixé par la plateforme (le moteur de contexte du core
    le lit dans la clé de session), jamais par un texte. Absent : la vue la plus restrictive."""
    _valider_entrees(affaire_id, horodatage, budget_caracteres, n_faits_max_par_couche, agent)

    maillons_evenements = registre_evenements.lire()
    maillons_affaires = registre_affaires.lire()
    tous_les_signaux = signaux.signaux_de_laffaire(affaire_id, maillons_evenements, maillons_affaires)

    entrees = (
        (COUCHE_REGLES_ENTREPRISE, _candidats_regles_entreprise(registre_affaires)),
        (COUCHE_FAITS_AFFAIRE, _candidats_faits_affaire(affaire_id, maillons_affaires)),
        (COUCHE_EVENEMENTS_RECENTS, _candidats_evenements_recents(affaire_id, maillons_evenements)),
        (COUCHE_SIGNAUX_NON_RESOLUS, _candidats_signaux(tous_les_signaux)),
    )
    couches: list[dict[str, Any]] = []
    nb_retenus = 0
    omis_evenements: list[dict] = []
    for nom, candidats in entrees:
        couche, retenus, omis = _couche(
            nom, agent, candidats, budget_par_couche(budget_caracteres), n_faits_max_par_couche
        )
        couches.append(couche)
        nb_retenus += retenus
        if nom == COUCHE_EVENEMENTS_RECENTS:
            omis_evenements = omis
    return {
        "affaire_id": affaire_id,
        "horodatage": horodatage,
        "budget_caracteres": budget_caracteres,
        "caracteres_utilises": sum(c["caracteres"] for c in couches),
        "couches": couches,
        "signaux": signaux.decompte(tous_les_signaux),
        "confidentialite": {
            "agent": agent,
            "regle": confidentialite.REGLE_VERSION,
            "nb_retenus": nb_retenus,
        },
        "affaire": amont.situation(affaire_id, maillons_evenements),
        "consolidation": _a_consolider(affaire_id, omis_evenements, maillons_affaires),
    }
