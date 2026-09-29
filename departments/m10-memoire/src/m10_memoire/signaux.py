"""Signaux critiques : cycle de vie écrit, jamais clos par le modèle seul (PLAN T3.3-suite-b).

Un signal critique est un événement ``m6.variance_chantier`` évalué dont ``signal_critique`` vaut ``true`` :
au moins un matériau atteint ou dépasse le seuil de variance. Il s'identifie par son ``evenement_id`` (la
clé publique de l'événement, jamais ``ligne_id``). Il appartient à l'affaire de son WCT
(``classification.lead_id``).

Cycle de vie, trois états, un seul sens :

    ouvert  ->  pris_en_compte  ->  clos

- ``ouvert`` : le signal existe et personne n'en a pris connaissance. C'est l'état de départ, celui qui
  bloque une action N3 ou plus dans le moteur de contexte du core.
- ``pris_en_compte`` : un HUMAIN l'a lu et l'a écrit, avec son motif. Il reste affiché, il ne bloque plus.
- ``clos`` : terminal. Un signal clos ne se rouvre pas ; une nouvelle variance critique est un NOUVEAU signal.

Qui écrit un passage : un humain identifié (``humain.py`` ; l'adaptateur de ``outils.py`` établit qui),
jamais le modèle. Le maillon ``signal_traite`` du registre Affaires garde qui, par quelle voie, quand et
pourquoi ; il est append-only comme tout le registre. L'état se calcule TOUJOURS par relecture des maillons,
jamais par un champ qu'on positionne (comme ``decisions.statut_courant``). Un maillon d'une forme qui n'est
pas celle d'un humain identifié, ou qui saute une étape, est IGNORÉ : il ne ferme rien (fail-closed).

Une seule autre cause de clôture, écrite ici et testée : la règle ``REGLE_VARIANCE_REEVALUEE``. Si M6
republie, pour le même ``wct_id`` et APRÈS le signal dans le registre Événements, une variance ``evaluee`` qui
ne signale plus aucun dépassement (``signal_critique`` faux), le signal est clos par cette règle, qui cite
l'événement qui le résout. C'est un fait calculé par M6, jamais une opinion de modèle. Aujourd'hui M6 ne
republie pas un ``evaluee`` pour un même ``wct_id`` (l'état est terminal) : la règle n'a pas encore de
producteur ; elle est là, testée, pour le jour où M6 réévalue. La clôture par règle se calcule à la
lecture : ce module n'écrit rien pour elle.

``horodatage`` est TOUJOURS fourni par l'appelant (aucune horloge n'est lue ici,
``conformite.py::HORLOGE_INTERNE`` le détecterait). Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import classification, confidentialite, humain, validation

TYPE_ENTREE_SIGNAL_TRAITE = "signal_traite"

ETAT_OUVERT = "ouvert"
ETAT_PRIS_EN_COMPTE = "pris_en_compte"
ETAT_CLOS = "clos"

ACTION_PRISE_EN_COMPTE = "prise_en_compte"
ACTION_CLOTURE = "cloture"

REGLE_VARIANCE_REEVALUEE = "regle:variance_reevaluee_sans_depassement"
MOTIF_REGLE_VARIANCE_REEVALUEE = "M6 a réévalué la variance de ce WCT : plus aucun dépassement"

NB_SIGNAUX_LISTES_MAX = 50

REJ_SIGNAL_ACTION_INCONNUE = "REJ-SIGNAL-ACTION-INCONNUE"
REJ_SIGNAL_INCONNU = "REJ-SIGNAL-INCONNU"
REJ_SIGNAL_AFFAIRE_INCONNUE = "REJ-SIGNAL-AFFAIRE-INCONNUE"
REJ_SIGNAL_DEJA_CLOS = "REJ-SIGNAL-DEJA-CLOS"
REJ_SIGNAL_DEJA_PRIS_EN_COMPTE = "REJ-SIGNAL-DEJA-PRIS-EN-COMPTE"
REJ_SIGNAL_PAS_PRIS_EN_COMPTE = "REJ-SIGNAL-PAS-PRIS-EN-COMPTE"

_ETAT_RESULTANT = {ACTION_PRISE_EN_COMPTE: ETAT_PRIS_EN_COMPTE, ACTION_CLOTURE: ETAT_CLOS}
_ETAT_REQUIS = {ACTION_PRISE_EN_COMPTE: ETAT_OUVERT, ACTION_CLOTURE: ETAT_PRIS_EN_COMPTE}
_ORDRE_ETAT = {ETAT_OUVERT: 0, ETAT_PRIS_EN_COMPTE: 1, ETAT_CLOS: 2}


def _est_signal_critique(maillon: dict[str, Any]) -> bool:
    return (
        classification.type_evenement(maillon) == classification.TYPE_VARIANCE
        and maillon.get("signal_critique") is True
    )


def _est_variance_sans_depassement(maillon: dict[str, Any]) -> bool:
    return (
        classification.type_evenement(maillon) == classification.TYPE_VARIANCE
        and maillon.get("statut_variance") == "evaluee"
        and maillon.get("signal_critique") is False
    )


def _traitement_recevable(maillon: dict[str, Any]) -> bool:
    """Un maillon ``signal_traite`` ne compte que s'il a la forme d'un traitement humain complet."""
    return (
        maillon.get("type_entree") == TYPE_ENTREE_SIGNAL_TRAITE
        and maillon.get("etat_resultant") in (ETAT_PRIS_EN_COMPTE, ETAT_CLOS)
        and humain.acteur_valide(maillon.get("par"), maillon.get("role"), maillon.get("source_decision"))
        and humain.motif_valide(maillon.get("motif"))
    )


def _jour(horodatage: str) -> str:
    return horodatage[:10]


def resume(signal: dict[str, Any]) -> str:
    """Une ligne qui dit l'état du signal, qui l'a traité, quand et pourquoi (le motif en dernier : la couche
    qui borne le résumé coupe le motif, jamais le nom)."""
    base = f"Variance {signal['signal_id']} : critique, "
    if signal["etat"] == ETAT_OUVERT:
        return base + "OUVERT, personne n'en a pris connaissance"
    quand = _jour(signal["traite_le"])
    if signal["etat"] == ETAT_PRIS_EN_COMPTE:
        return base + f"pris en compte par {signal['traite_par']} le {quand} : {signal['motif']}"
    if signal["traite_par"] == REGLE_VARIANCE_REEVALUEE:
        return base + f"CLOS par la règle de réévaluation ({signal['fait_resolvant']}) : {signal['motif']}"
    return base + f"CLOS par {signal['traite_par']} le {quand} : {signal['motif']}"


def _signaux_avec_etat(
    maillons_evenements: list[dict[str, Any]], maillons_affaires: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Tous les signaux critiques du registre Événements, dans l'ordre du registre, chacun avec son état
    calculé par relecture. Un seul parcours de chaque registre."""
    index_wct = classification.index_lead_id_par_wct_id(maillons_evenements)
    reevaluations: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    signaux: dict[str, dict[str, Any]] = {}
    for position, maillon in enumerate(maillons_evenements):
        if _est_variance_sans_depassement(maillon):
            reevaluations.setdefault(maillon.get("wct_id"), []).append((position, maillon))
        if not _est_signal_critique(maillon):
            continue
        identifiant = classification.identifiant(maillon)
        if identifiant is None or identifiant in signaux:
            continue
        signaux[identifiant] = {
            "signal_id": identifiant,
            "affaire_id": classification.lead_id(maillon, index_wct),
            "wct_id": maillon.get("wct_id"),
            "horodatage": maillon["horodatage"],
            "position": position,
            "etat": ETAT_OUVERT,
            "traite_par": None,
            "traite_le": None,
            "motif": None,
            "fait_resolvant": None,
            "confidentialite": confidentialite.niveau_de(maillon),
        }

    for maillon in maillons_affaires:
        if not _traitement_recevable(maillon):
            continue
        signal = signaux.get(maillon.get("signal_id"))
        if signal is None or signal["etat"] == ETAT_CLOS:
            continue
        # Un maillon qui saute une étape ne ferme rien : seule la suite ouvert -> pris_en_compte -> clos compte.
        if maillon["etat_resultant"] == ETAT_PRIS_EN_COMPTE and signal["etat"] == ETAT_OUVERT:
            signal["etat"] = ETAT_PRIS_EN_COMPTE
        elif maillon["etat_resultant"] == ETAT_CLOS and signal["etat"] == ETAT_PRIS_EN_COMPTE:
            signal["etat"] = ETAT_CLOS
        else:
            continue
        signal["traite_par"] = maillon["par"]
        signal["traite_le"] = maillon["horodatage"]
        signal["motif"] = maillon["motif"].strip()

    for signal in signaux.values():
        if signal["etat"] == ETAT_CLOS:
            continue
        posterieures = [m for p, m in reevaluations.get(signal["wct_id"], []) if p > signal["position"]]
        if posterieures:
            resolvant = posterieures[0]
            signal.update(
                etat=ETAT_CLOS,
                traite_par=REGLE_VARIANCE_REEVALUEE,
                traite_le=resolvant["horodatage"],
                motif=MOTIF_REGLE_VARIANCE_REEVALUEE,
                fait_resolvant=classification.identifiant(resolvant),
            )
    return list(signaux.values())


def _instant(horodatage: str) -> datetime:
    return datetime.fromisoformat(horodatage)


def _ordonner(signaux: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ouverts, puis pris en compte, puis clos ; dans chaque groupe le plus récent d'abord (les clos par
    date de clôture). Comparaison par datetime PARSÉ, jamais par texte (décalages horaires différents)."""

    def cle(signal: dict[str, Any]) -> tuple[int, float, int]:
        reference = signal["traite_le"] if signal["etat"] == ETAT_CLOS else signal["horodatage"]
        return (_ORDRE_ETAT[signal["etat"]], -_instant(reference).timestamp(), -signal["position"])

    return sorted(signaux, key=cle)


def signaux_de_laffaire(
    affaire_id: str, maillons_evenements: list[dict[str, Any]], maillons_affaires: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Les signaux de l'affaire, ordonnés (ouverts d'abord)."""
    tous = _signaux_avec_etat(maillons_evenements, maillons_affaires)
    return _ordonner([s for s in tous if s["affaire_id"] == affaire_id])


def decompte(signaux: list[dict[str, Any]]) -> dict[str, int]:
    """Nombre de signaux par état, sur TOUS les signaux donnés : la troncature d'une couche ne le change pas."""
    return {
        "nb_ouverts": sum(1 for s in signaux if s["etat"] == ETAT_OUVERT),
        "nb_pris_en_compte": sum(1 for s in signaux if s["etat"] == ETAT_PRIS_EN_COMPTE),
        "nb_clos": sum(1 for s in signaux if s["etat"] == ETAT_CLOS),
    }


def lister(
    affaire_id: str | None, maillons_evenements: list[dict[str, Any]], maillons_affaires: list[dict[str, Any]]
) -> dict[str, Any]:
    """Vue compacte pour l'écran d'un humain : les signaux (d'une affaire, ou de toutes), ouverts d'abord,
    au plus ``NB_SIGNAUX_LISTES_MAX`` ; ce qui dépasse est DIT (``nb_omis``), jamais tu."""
    tous = _signaux_avec_etat(maillons_evenements, maillons_affaires)
    if affaire_id is not None:
        tous = [s for s in tous if s["affaire_id"] == affaire_id]
    ordonnes = _ordonner(tous)
    retenus = ordonnes[:NB_SIGNAUX_LISTES_MAX]
    return {
        "signaux": [
            {
                "signal_id": s["signal_id"],
                "affaire_id": s["affaire_id"],
                "horodatage": s["horodatage"],
                "etat": s["etat"],
                "traite_par": s["traite_par"],
                "traite_le": s["traite_le"],
                "motif": s["motif"],
            }
            for s in retenus
        ],
        "nb_total": len(ordonnes),
        "nb_omis": len(ordonnes) - len(retenus),
        **decompte(ordonnes),
    }


def traiter_signal(
    action: str,
    signal_id: str,
    par: str,
    role: str,
    source_decision: str,
    motif: str,
    horodatage: str,
    registre_evenements: Any,
    registre_affaires: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Écrit le passage d'un signal à l'état suivant ; rend ``(maillon, None)`` ou ``(None, verdict)``.

    Toutes les vérifications précèdent l'écriture : un refus n'écrit rien. ``par``, ``role`` et
    ``source_decision`` viennent de l'adaptateur, qui a établi l'humain ; ils sont revérifiés ici.
    """
    if action not in _ETAT_RESULTANT:
        return None, validation.construire_verdict(REJ_SIGNAL_ACTION_INCONNUE, f"action inconnue : {action!r}")
    defaut = humain.verifier_ecriture(par, role, source_decision, motif, horodatage)
    if defaut is not None:
        return None, defaut
    maillons_evenements = registre_evenements.lire()
    signal = next(
        (s for s in _signaux_avec_etat(maillons_evenements, registre_affaires.lire()) if s["signal_id"] == signal_id),
        None,
    )
    if signal is None:
        return None, validation.construire_verdict(
            REJ_SIGNAL_INCONNU,
            "aucun signal critique ne porte cet identifiant (une variance critique évaluée, identifiée "
            "par son evenement_id) ; lis les signaux de l'affaire avec m10_lister_signaux",
        )
    if signal["affaire_id"] is None:
        return None, validation.construire_verdict(
            REJ_SIGNAL_AFFAIRE_INCONNUE,
            "l'affaire de ce signal n'est pas connue (le WCT de la variance n'est pas encore mémorisé) : "
            "rien n'est écrit",
        )
    if signal["etat"] == ETAT_CLOS:
        return None, validation.construire_verdict(
            REJ_SIGNAL_DEJA_CLOS, "un signal clos ne se rouvre pas : une nouvelle variance est un nouveau signal"
        )
    if signal["etat"] != _ETAT_REQUIS[action]:
        if action == ACTION_PRISE_EN_COMPTE:
            return None, validation.construire_verdict(
                REJ_SIGNAL_DEJA_PRIS_EN_COMPTE, "ce signal a déjà été pris en compte : il peut être clos"
            )
        return None, validation.construire_verdict(
            REJ_SIGNAL_PAS_PRIS_EN_COMPTE,
            "un signal se clôt après avoir été pris en compte : prends-en connaissance d'abord",
        )

    ligne_id = registre_affaires.ajouter(
        {
            "type_entree": TYPE_ENTREE_SIGNAL_TRAITE,
            "horodatage": horodatage,
            "signal_id": signal_id,
            "affaire_id": signal["affaire_id"],
            "etat_resultant": _ETAT_RESULTANT[action],
            "par": par,
            "role": role,
            "source_decision": source_decision,
            "motif": motif.strip(),
        }
    )
    for maillon in registre_affaires.lire():
        if maillon.get("ligne_id") == ligne_id:
            return maillon, None
    raise RuntimeError("Maillon ajouté introuvable.")
