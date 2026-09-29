"""Estimé contre réel de M3 (PLAN T1.2-d, en second ordre) : relie un WCT (M4) et sa variance de
chantier (M6) au devis puis, si le lien existe déjà, à l'estimation d'origine — jamais un lien
inventé.

Module pur (ADR-0009, même règle que ``devis_durable.py``) : aucun import ``opsys``, aucune
horloge interne (``datetime.fromisoformat`` PARSE une date fournie, il ne LIT jamais l'horloge —
seuls ``now``/``today``/``utcnow``/etc. sont interdits, cf. ``conformite.py``), aucun accès réseau.

Ce module est le PREMIER appelant réel du registre append-only décrit par
``docs/departements/M3-audit.md`` §M3.15 (« Apprentissage estimé vs réel ») : ce registre-là
(``registre.py``/``outils.registre_production()``, collection "principal") reste celui d'ORIGINE
— les futures estimations Monte Carlo qu'un orchestrateur (T2.3, pas encore construit) y écrira.
Ce module ne lui ajoute RIEN : il le LIT SEULEMENT (recherche d'une estimation d'origine par
``devis_id``), en lecture seule, jamais en écriture — conforme à « réutiliser plutôt qu'empiler ».
Les résultats de LA COMPARAISON (durée réelle contre estimée, variance matériaux) vivent dans un
second registre, DÉDIÉ à cette comparaison (``stockage.maillons("m03-estimation",
"estime_vs_reel")`` en production, choix de ``outils.py`` seul) — jamais mélangé au premier, par
le même raisonnement qui a déjà séparé le registre des devis (``devis_durable.py``) du registre
"principal" : les 6 clés fixes de ``registre.py`` (S008) ne correspondent à aucun champ d'un WCT
ou d'une variance de chantier, et les y forcer inventerait un rapport qui n'existe pas.

Chaque WCT (``wct_id``) vit comme une petite suite d'événements append-only, même patron que
``devis_durable.py`` : un maillon ``wct_recu`` (à la réception de ``m4.travaux_termines``), puis
au plus un maillon ``variance_recue`` (à la réception d'une ``m6.variance_chantier`` au statut
``evaluee`` — SEULE valeur qui alimente la partie matériaux ; les autres statuts
(``prevu_absent``, ``declaration_absente``, ``seuil_absent``) sont des no-op : rien n'est écrit,
« matériaux » reste absent par construction, jamais un statut explicite à gérer plus tard).
L'état courant d'un wct_id est la fusion de ses maillons (``_etats_courants``). Idempotent par
``wct_id`` : un ``wct_recu`` déjà connu, ou un ``evaluee`` déjà enregistré (``evaluee`` est
terminal — catalogue ``m6.variance_chantier.json``), rendent l'état existant sans rien écrire de
plus — une redélivrance (bus, ou rejeu direct) ne crée jamais de second maillon.

MAIN-D'ŒUVRE — lien devis/estimation d'origine (``_duree_estimee_minutes``) : cherche une durée
estimée en texte décimal OU en ``Decimal`` sous la clé optionnelle ``duree_estimee_minutes``,
d'abord sur le DEVIS (``devis_durable.lire_devis``), puis, si absente, sur l'ESTIMATION D'ORIGINE
(maillon de ``registre.py`` dont ``charge["devis_id"]`` correspond). Cette clé n'existe
AUJOURD'HUI nulle part dans le dépôt (ni le contrat gelé du devis, T2.3-a/b, ni ``registre.py``,
S008, ne la définissent) : le résultat RÉEL, tant qu'aucun orchestrateur ne l'écrit, est TOUJOURS
« durée estimée absente », rapporté par un verdict nommé (``REJ-ECART-ESTIMATION-ORIGINE-ABSENTE``)
— jamais une durée inventée. La convention est posée ici, précisément, pour qu'un futur écrivain
(devis ou orchestrateur d'estimation) sache où et comment l'écrire sans deviner.

MESURE D'ERREUR (``ecart_relatif``) : écart relatif SIGNÉ, ``(réel - estimé) / estimé`` — positif
= dépassement, négatif = sous-estimation. PUREMENT INFORMATIF à ce stade : AUCUN code de ce
paquet ne relit ce chiffre pour ajuster un barème, un plancher ou quoi que ce soit d'autre — il
sert de matière première à une calibration FUTURE, explicitement hors périmètre de ce module.

MATÉRIAUX — repris TEL QUEL des lignes de ``m6.variance_chantier`` (statut ``evaluee``), jamais
recalculé : ``ecart_pourcentage``/``critique`` par matériau sont déjà les verdicts de
``variance_chantier.evaluer`` côté M6 ; ce module ne fait que les stocker sous le même ``wct_id``.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from . import devis_durable, verdicts

__all__ = [
    "avec_duree_estimee",
    "ecart_relatif",
    "enregistrer_travaux_termines",
    "enregistrer_variance_chantier",
    "lire_ecarts",
]

_STATUT_VARIANCE_EVALUEE = "evaluee"


def _ajouter(entree: dict[str, Any], registre_cible: Any) -> dict[str, Any]:
    """Ajoute une copie de ``entree`` au registre et en retourne une seconde, indépendante — même
    précaution que ``devis_durable._ajouter`` (ni le maillon stocké ni le résultat rendu à
    l'appelant ne doivent partager une structure mutable)."""
    registre_cible.append(copy.deepcopy(entree))
    return copy.deepcopy(entree)


def _etats_courants(registre_cible: Any) -> dict[str, dict[str, Any]]:
    """État courant de chaque wct_id connu de ``registre_cible`` : fusion, dans l'ordre du
    registre, du maillon ``wct_recu`` puis d'un éventuel ``variance_recue`` — même patron que
    ``devis_durable._etats_courants``."""
    etats: dict[str, dict[str, Any]] = {}
    for maillon in registre_cible:
        type_entree = maillon.get("type_entree")
        wct_id = maillon.get("wct_id")
        if type_entree == "wct_recu":
            etats[wct_id] = dict(maillon)
        elif type_entree == "variance_recue" and wct_id in etats:
            etats[wct_id] = {**etats[wct_id], **maillon}
    return etats


def _etat(registre_cible: Any, wct_id: str) -> dict[str, Any] | None:
    return _etats_courants(registre_cible).get(wct_id)


def _vers_decimal_positif(brute: Any, code: str, nom_champ: str) -> tuple[Decimal | None, dict | None]:
    if isinstance(brute, Decimal):
        valeur = brute
    elif isinstance(brute, str):
        try:
            valeur = Decimal(brute)
        except InvalidOperation:
            return None, verdicts.construire_verdict(code, detail=f"{nom_champ} décimal invalide : {brute!r}")
    else:
        return None, verdicts.construire_verdict(
            code, detail=f"{nom_champ} doit être Decimal ou texte décimal, reçu {type(brute).__name__}"
        )
    if not valeur.is_finite() or valeur <= 0:
        return None, verdicts.construire_verdict(
            code, detail=f"{nom_champ} doit être positive et finie (reçu {valeur})"
        )
    return valeur, None


def ecart_relatif(estime: Decimal, reel: Decimal) -> tuple[Decimal | None, dict | None]:
    """Mesure d'erreur d'estimation : écart relatif SIGNÉ = (réel - estimé) / estimé (cf.
    docstring du module — sert une future calibration, n'ajuste rien ici). Fail-closed si
    ``estime`` n'est pas strictement positif (division par zéro ou rapport sans le sens)."""
    if not isinstance(estime, Decimal) or not isinstance(reel, Decimal):
        return None, verdicts.construire_verdict(
            "REJ-ECART-DUREE-ESTIMEE-INVALIDE", detail="estime et reel doivent être des Decimal"
        )
    if not estime.is_finite() or estime <= 0:
        return None, verdicts.construire_verdict(
            "REJ-ECART-DUREE-ESTIMEE-INVALIDE", detail=f"estime doit être strictement positive et finie (reçu {estime})"
        )
    if not reel.is_finite():
        return None, verdicts.construire_verdict(
            "REJ-ECART-DUREE-ESTIMEE-INVALIDE", detail=f"reel doit être fini (reçu {reel})"
        )
    return (reel - estime) / estime, None


def _estimation_origine(devis_id: str, maillons_estimations: Iterable[Any]) -> dict[str, Any] | None:
    """Dernière (la plus récente) charge de ``registre.py`` dont ``devis_id`` correspond, ou
    ``None``. Lecture SEULE : ce module n'écrit jamais dans ce registre (cf. docstring)."""
    trouvee: dict[str, Any] | None = None
    for maillon in maillons_estimations:
        if not isinstance(maillon, dict):
            continue
        charge = maillon.get("charge")
        if isinstance(charge, dict) and charge.get("devis_id") == devis_id:
            trouvee = charge
    return trouvee


def _duree_estimee_minutes(
    devis_id: str, registre_devis: Any, maillons_estimations: Iterable[Any]
) -> tuple[Decimal | None, dict | None]:
    """Cherche ``duree_estimee_minutes`` d'abord sur le devis, puis sur l'estimation d'origine
    (cf. docstring du module). Un rejet nommé, jamais une durée inventée, si aucune des deux
    sources ne la porte — ce qui est le cas de TOUT le dépôt aujourd'hui."""
    devis, verdict_devis = devis_durable.lire_devis(registre_devis, devis_id)
    if verdict_devis is None:
        brute = devis.get("duree_estimee_minutes")
        if brute is not None:
            return _vers_decimal_positif(brute, "REJ-ECART-DUREE-ESTIMEE-INVALIDE", "duree_estimee_minutes (devis)")

    estimation = _estimation_origine(devis_id, maillons_estimations)
    if estimation is not None:
        brute = estimation.get("duree_estimee_minutes")
        if brute is not None:
            return _vers_decimal_positif(
                brute, "REJ-ECART-DUREE-ESTIMEE-INVALIDE", "duree_estimee_minutes (estimation d'origine)"
            )

    return None, verdicts.construire_verdict(
        "REJ-ECART-ESTIMATION-ORIGINE-ABSENTE",
        detail=(
            f"aucune durée estimée pour devis_id={devis_id!r} : ni le devis "
            f"(devis_id trouvé={verdict_devis is None}) ni une estimation d'origine "
            f"(trouvée={estimation is not None}) ne portent duree_estimee_minutes"
        ),
    )


def avec_duree_estimee(
    charge_devis_accepte: dict[str, Any], devis_id: str, registre_devis: Any, maillons_estimations: Iterable[Any]
) -> dict[str, Any]:
    """Copie de la charge de ``m3.devis_accepte`` avec la clé OPTIONNELLE ``duree_estimee_minutes`` (PLAN T1.5-d),
    quand l'estimation d'origine du devis la porte : M8 la compare à la durée réelle du WCT (temps prévu contre
    réel). Même règle que la comparaison main-d'œuvre (``_duree_estimee_minutes``) : une seule lecture de la
    durée estimée pour tout le paquet.

    Texte décimal strictement positif (``format(..., "f")`` : jamais d'exposant, jamais un nombre JSON). Fail-closed :
    aucune estimation d'origine pour ce devis, durée absente ou illisible -> la clé est OMISE (jamais une durée
    par défaut, jamais zéro) et M8 répond « non calculable, manque duree_estimee_minutes ». Ne lit que ;
    n'écrit rien."""
    duree, verdict = _duree_estimee_minutes(devis_id, registre_devis, maillons_estimations)
    charge = dict(charge_devis_accepte)
    if verdict is None:
        charge["duree_estimee_minutes"] = format(duree, "f")
    return charge


def _comparer_main_doeuvre(
    devis_id: str | None, duree_reelle_minutes: Decimal, registre_devis: Any, maillons_estimations: Iterable[Any]
) -> dict[str, Any]:
    if devis_id is None:
        return {
            "duree_reelle_minutes": duree_reelle_minutes,
            "duree_estimee_minutes": None,
            "ecart_relatif": None,
            "verdict": verdicts.construire_verdict(
                "REJ-ECART-DEVIS-ID-ABSENT",
                detail="le WCT ne porte aucun devis_id : comparaison main-d'œuvre impossible sans lien vers un devis",
            ),
        }

    duree_estimee_minutes, verdict = _duree_estimee_minutes(devis_id, registre_devis, maillons_estimations)
    if verdict is not None:
        return {
            "duree_reelle_minutes": duree_reelle_minutes,
            "duree_estimee_minutes": None,
            "ecart_relatif": None,
            "verdict": verdict,
        }

    ecart, verdict = ecart_relatif(duree_estimee_minutes, duree_reelle_minutes)
    return {
        "duree_reelle_minutes": duree_reelle_minutes,
        "duree_estimee_minutes": duree_estimee_minutes,
        "ecart_relatif": ecart,
        "verdict": verdict,
    }


def enregistrer_travaux_termines(
    charge_wct: dict[str, Any], registre_devis: Any, maillons_estimations: Iterable[Any], registre_cible: Any
) -> dict[str, Any]:
    """Consomme ``m4.travaux_termines`` (charge déjà validée par le catalogue — cf.
    ``opsys.evenements.publier``). TOUJOURS un enregistrement : un ``devis_id`` absent ou une
    estimation d'origine introuvable sont des LACUNES nommées dans ``main_doeuvre.verdict``,
    jamais un refus de traiter le WCT (fail-closed au niveau de la DONNÉE, pas de l'événement).
    Idempotente par ``wct_id`` : un wct_id déjà connu rend l'état existant sans écrire de second
    maillon."""
    wct_id = charge_wct["wct_id"]
    existant = _etat(registre_cible, wct_id)
    if existant is not None:
        return existant

    devis_id = charge_wct.get("devis_id")
    duree_reelle_minutes = Decimal(charge_wct["duree_reelle_minutes"])  # int JSON, jamais un float
    main_doeuvre = _comparer_main_doeuvre(devis_id, duree_reelle_minutes, registre_devis, maillons_estimations)

    entree = {
        "type_entree": "wct_recu",
        "wct_id": wct_id,
        "devis_id": devis_id,
        "lead_id": charge_wct["lead_id"],
        "intervention_id": charge_wct["intervention_id"],
        "horodatage_completion": charge_wct["horodatage_completion"],
        "main_doeuvre": main_doeuvre,
        "materiaux": None,
        "horodatage": charge_wct["horodatage_completion"],
    }
    return _ajouter(entree, registre_cible)


def enregistrer_variance_chantier(charge_variance: dict[str, Any], registre_cible: Any) -> dict[str, Any] | None:
    """Consomme ``m6.variance_chantier``. N'agit (et n'écrit) que si ``statut_variance ==
    "evaluee"`` : toute autre valeur (``prevu_absent``, ``declaration_absente``, ``seuil_absent``)
    est un no-op qui rend ``None`` sans jamais toucher le registre — « matériaux » reste absent
    PAR CONSTRUCTION, jamais un statut « en_attente » à maintenir explicitement. Idempotente par
    wct_id : ``evaluee`` est terminal (catalogue ``m6.variance_chantier.json``), donc un second
    ``evaluee`` pour le même wct_id est TOUJOURS une redélivrance, rendue en no-op (état existant,
    rien de réécrit).

    Lève ``LookupError`` si ``wct_id`` est inconnu du registre (le WCT correspondant n'a pas
    encore été consommé) : un ordre d'arrivée inversé n'est structurellement pas censé se
    produire (``m6.variance_chantier`` est toujours publié APRÈS ``m4.travaux_termines`` pour le
    même wct_id, et le répartiteur livre les événements dans l'ordre de publication) — mieux vaut
    une panne explicite, retraitée par le répartiteur (réessai puis quarantaine), qu'un
    rattachement à un WCT halluciné."""
    if charge_variance["statut_variance"] != _STATUT_VARIANCE_EVALUEE:
        return None

    wct_id = charge_variance["wct_id"]
    existant = _etat(registre_cible, wct_id)
    if existant is None:
        raise LookupError(f"variance evaluee reçue pour un wct_id inconnu de M3 : {wct_id!r}")
    if existant.get("materiaux") is not None:
        return existant  # evaluee est terminal : une redélivrance est un no-op

    materiaux = {
        "chantier_id": charge_variance["chantier_id"],
        "signal_critique": charge_variance["signal_critique"],
        "seuil_pourcentage": charge_variance["seuil_pourcentage"],
        "lignes": charge_variance["lignes"],
    }
    entree = {
        "type_entree": "variance_recue",
        "wct_id": wct_id,
        "materiaux": materiaux,
        "horodatage": charge_variance["horodatage_completion"],
    }
    return _ajouter(entree, registre_cible)


def _dans_periode(horodatage: str, depuis: datetime, jusqua: datetime) -> tuple[bool, dict | None]:
    try:
        instant = datetime.fromisoformat(horodatage)
    except ValueError:
        return False, verdicts.construire_verdict(
            "REJ-ECART-PERIODE-INVALIDE", detail=f"horodatage_completion non ISO-8601 : {horodatage!r}"
        )
    if instant.tzinfo is None:
        return False, verdicts.construire_verdict(
            "REJ-ECART-PERIODE-INVALIDE", detail=f"horodatage_completion sans fuseau : {horodatage!r}"
        )
    return depuis <= instant < jusqua, None


def lire_ecarts(
    registre_cible: Any, devis_id: str | None, depuis: str | None, jusqua: str | None
) -> tuple[list[dict[str, Any]] | None, dict | None]:
    """Écarts estimé-vs-réel courants, filtrés par ``devis_id`` et/ou une période
    ``[depuis, jusqua[`` sur ``horodatage_completion`` (ISO-8601, fuseau requis, comme
    ``m4.travaux_termines``). Au moins un des deux filtres est requis — jamais tout le registre
    d'un coup. Lecture pure (T0) : aucune écriture, aucune horloge consultée (``depuis``/``jusqua``
    sont fournis par l'appelant, jamais déduits)."""
    if devis_id is None and depuis is None and jusqua is None:
        return None, verdicts.construire_verdict(
            "REJ-ECART-FILTRE-ABSENT", detail="fournir devis_id, ou une période (depuis et jusqua)"
        )
    if (depuis is None) != (jusqua is None):
        return None, verdicts.construire_verdict(
            "REJ-ECART-PERIODE-INCOMPLETE", detail="depuis et jusqua doivent être fournis ensemble"
        )

    bornes: tuple[datetime, datetime] | None = None
    if depuis is not None and jusqua is not None:
        try:
            debut = datetime.fromisoformat(depuis)
            fin = datetime.fromisoformat(jusqua)
        except ValueError as exc:
            return None, verdicts.construire_verdict("REJ-ECART-PERIODE-INVALIDE", detail=str(exc))
        if debut.tzinfo is None or fin.tzinfo is None:
            return None, verdicts.construire_verdict(
                "REJ-ECART-PERIODE-INVALIDE", detail="depuis et jusqua doivent porter un fuseau ISO-8601"
            )
        if fin <= debut:
            return None, verdicts.construire_verdict(
                "REJ-ECART-PERIODE-INVALIDE", detail="jusqua doit être strictement postérieur à depuis"
            )
        bornes = (debut, fin)

    resultats: list[dict[str, Any]] = []
    for etat in _etats_courants(registre_cible).values():
        if devis_id is not None and etat.get("devis_id") != devis_id:
            continue
        if bornes is not None:
            dedans, verdict = _dans_periode(etat["horodatage_completion"], bornes[0], bornes[1])
            if verdict is not None:
                return None, verdict
            if not dedans:
                continue
        resultats.append(
            {
                "wct_id": etat["wct_id"],
                "devis_id": etat.get("devis_id"),
                "intervention_id": etat.get("intervention_id"),
                "horodatage_completion": etat.get("horodatage_completion"),
                "main_doeuvre": etat.get("main_doeuvre"),
                "materiaux": etat.get("materiaux"),
            }
        )

    resultats.sort(key=lambda r: (r["horodatage_completion"], r["wct_id"]))
    return resultats, None
