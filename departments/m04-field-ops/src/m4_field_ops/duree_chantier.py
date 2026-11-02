"""Durée d'un chantier à planifier, et découpage en visites (P4-01, P4-02).

Module pur (stdlib ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun flottant, aucun réseau ; un test le
vérifie par analyse du code). Il répond à une seule question : « combien de minutes ce chantier prend-il sur site, et
d'où vient ce chiffre ? ».

D'où vient la durée (ordre de préférence, jamais un mélange)
    1. ``estimation_m3`` : la durée sur site de l'ESTIMATION de M3 pour ce devis, portée par ``m3.devis_accepte``
       (``duree_estimee_minutes``) et retenue à l'inscription de l'intervention (``retenir_estimation``) : M4 ne la
       recalcule jamais. Quand une version apprise ou une calibration est APPLIQUÉE à l'estimation, c'est déjà la durée
       corrigée que M3 publie (M3 dit ``duree_origine.origine = "calibration"`` et laisse sa trace) : M4 la reprend
       telle
       quelle et le dit. Elle n'est retenue que si M3 déclare sa sémantique exacte, ``duree_ecoulee_intervention``
       (durée écoulée sur site, pauses validées et déplacement exclus) : une durée dont on ignore si elle compte le
       déplacement ou des heures-personnes n'est jamais utilisée (``ecartee``).
    2. ``profil_service`` / ``surcharge_service`` : REPLI explicite, la durée par service que l'entreprise déclare
       (profil des équipes, ou argument de l'appelant). Il est DIT (``repli: true`` et sa raison), jamais silencieux.
    3. rien : « durée à déclarer ». Aucune durée n'est jamais inventée.
Le déplacement n'est jamais dans cette durée : M4 le calcule à part (matrice de distances de la cédule).

Une durée décimale de M3 devient des minutes ENTIÈRES par arrondi vers le HAUT (on ne sous-estime jamais un chantier).

Découpage (``decouper``) : un chantier plus long que ``visite_max_minutes`` (règle d'entreprise, déclarée, jamais
supposée) se découpe en ``ceil(durée / visite_max_minutes)`` visites de durées presque égales dont la somme est
EXACTEMENT
la durée du chantier ; chaque visite est une journée de travail de la même équipe (``tournees.py``).
"""

from __future__ import annotations

import re
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from . import tournees

SEMANTIQUE_QUALIFIEE = "duree_ecoulee_intervention"

SOURCE_ESTIMATION_M3 = "estimation_m3"
SOURCE_PROFIL = "profil_service"
SOURCE_SURCHARGE = "surcharge_service"

STATUT_RETENUE = "retenue"
STATUT_ABSENTE = "absente"
STATUT_ECARTEE = "ecartee"

ORIGINE_BAREME = "bareme"
ORIGINE_CALIBRATION = "calibration"
ORIGINE_INCONNUE = "inconnue"
ORIGINES = (ORIGINE_BAREME, ORIGINE_CALIBRATION)

CLES_MULTIJOURS = ("visite_max_minutes", "jours_consecutifs")
DUREE_MAX_MINUTES = tournees.MAX_VISITES * tournees.MINUTES_PAR_JOUR

__all__ = [
    "SEMANTIQUE_QUALIFIEE",
    "SOURCE_ESTIMATION_M3",
    "SOURCE_PROFIL",
    "SOURCE_SURCHARGE",
    "CLES_MULTIJOURS",
    "COMMENT_DECLARER_LA_DUREE",
    "DUREE_MAX_MINUTES",
    "retenir_estimation",
    "minutes_entieres",
    "lire_multijours",
    "decouper",
    "resoudre",
    "libelle",
]

COMMENT_DECLARER_LA_DUREE = (
    "déclarer la durée du service dans le profil des équipes (clé equipes.services.<service>.duree_min, "
    "`opsys-metier equipes declarer`) ou fournir durees_par_service à m4_proposer_cedule"
)
_DECLARER_MULTIJOURS = (
    "déclarer les règles des chantiers de plusieurs jours dans le profil des équipes (clé equipes.cedule.multijours : "
    "visite_max_minutes, jours_consecutifs ; `opsys-metier equipes declarer`)"
)


# ---------------------------------------------------------------------------
# Ce que le devis accepté dit de la durée, retenu à l'inscription
# ---------------------------------------------------------------------------
_FORME_DECIMALE = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,12})?")


def _decimal_positif(texte):
    """``Decimal`` strictement positif et fini, ou ``None``. Un texte décimal seulement, sans exposant ni signe (la
    forme
    du catalogue, ``format(x, "f")`` de M3), jamais un nombre JSON."""
    if not isinstance(texte, str) or _FORME_DECIMALE.fullmatch(texte) is None:
        return None
    try:
        valeur = Decimal(texte)
    except InvalidOperation:
        return None
    if not valeur.is_finite() or valeur <= 0:
        return None
    return valeur


def retenir_estimation(charge):
    """Ce que ``m3.devis_accepte`` dit de la durée, à ranger à l'inscription : un bloc ``{statut, ...}``.

    ``retenue`` (minutes, sémantique, origine, version de calibration) seulement si M3 donne une durée décimale
    positive ET déclare la sémantique ``duree_ecoulee_intervention`` ; ``absente`` si M3 ne donne rien ; ``ecartee``
    si ce que M3 donne n'est pas utilisable (sémantique absente ou différente, durée illisible ou hors bornes). Rien
    n'est recalculé : la durée est celle de M3, telle quelle. Ne lève jamais."""
    if not isinstance(charge, dict):
        return {"statut": STATUT_ABSENTE, "motif": "charge illisible"}
    duree = charge.get("duree_estimee_minutes")
    if duree is None:
        return {
            "statut": STATUT_ABSENTE,
            "motif": "le devis accepté ne porte aucune durée (barème sans durée, ou devis sans estimation "
                     "d'origine liée)",
        }
    if charge.get("semantique_temps") != SEMANTIQUE_QUALIFIEE:
        return {
            "statut": STATUT_ECARTEE,
            "motif": (
                f"semantique_temps absente ou différente de {SEMANTIQUE_QUALIFIEE!r} : une durée dont on ignore "
                "si elle compte le déplacement ou des heures-personnes n'est pas utilisée"
            ),
        }
    valeur = _decimal_positif(duree)
    if valeur is None or valeur > DUREE_MAX_MINUTES:
        return {
            "statut": STATUT_ECARTEE,
            "motif": f"duree_estimee_minutes illisible ou hors bornes (texte décimal de 0 exclu à {DUREE_MAX_MINUTES})",
        }
    origine = charge.get("duree_origine")
    version = None
    if isinstance(origine, dict) and origine.get("origine") in ORIGINES:
        nature = origine["origine"]
        if nature == ORIGINE_CALIBRATION and isinstance(origine.get("calibration_version_id"), str):
            version = origine["calibration_version_id"]
    else:
        nature = ORIGINE_INCONNUE
    return {
        "statut": STATUT_RETENUE, "minutes": duree, "semantique": SEMANTIQUE_QUALIFIEE, "origine": nature,
        "calibration_version_id": version,
    }


def minutes_entieres(texte):
    """Minutes entières d'une durée décimale de M3, arrondies vers le HAUT. ``None`` si illisible ou hors bornes."""
    valeur = _decimal_positif(texte)
    if valeur is None or valeur > DUREE_MAX_MINUTES:
        return None
    return int(valeur.to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Règles des chantiers de plusieurs jours (déclarées par l'entreprise)
# ---------------------------------------------------------------------------
def lire_multijours(brut):
    """``({visite_max_minutes, jours_consecutifs}, None)`` ou ``(None, motif)``. Aucune valeur par défaut."""
    if not isinstance(brut, dict):
        return None, "multijours : un objet est attendu (visite_max_minutes, jours_consecutifs)"
    inconnues = sorted(str(cle) for cle in brut if cle not in CLES_MULTIJOURS)
    manquantes = [cle for cle in CLES_MULTIJOURS if brut.get(cle) is None]
    if inconnues or manquantes:
        morceaux = []
        if manquantes:
            morceaux.append("manquant : " + ", ".join(manquantes))
        if inconnues:
            morceaux.append("clés inconnues : " + ", ".join(inconnues))
        return None, "multijours : " + " ; ".join(morceaux)
    cap, consecutifs = brut["visite_max_minutes"], brut["jours_consecutifs"]
    if type(cap) is not int or not 1 <= cap <= tournees.MINUTES_PAR_JOUR:
        return None, f"multijours.visite_max_minutes : entier de 1 à {tournees.MINUTES_PAR_JOUR}"
    if type(consecutifs) is not bool:
        return None, "multijours.jours_consecutifs : booléen explicite"
    return {"visite_max_minutes": cap, "jours_consecutifs": consecutifs}, None


def decouper(duree_minutes, visite_max_minutes):
    """Durées des visites d'un chantier de ``duree_minutes`` : ``[duree]`` si elle tient dans une visite, sinon
    ``ceil(duree / visite_max_minutes)`` visites presque égales (les premières portent le reste), dont la somme est
    exactement ``duree_minutes``. ``None`` si le chantier exigerait plus de ``MAX_VISITES`` visites."""
    if duree_minutes <= visite_max_minutes:
        return [duree_minutes]
    nombre = -(-duree_minutes // visite_max_minutes)
    if nombre > tournees.MAX_VISITES:
        return None
    base, reste = divmod(duree_minutes, nombre)
    return [base + 1 if rang < reste else base for rang in range(nombre)]


# ---------------------------------------------------------------------------
# Durée d'une intervention
# ---------------------------------------------------------------------------
def _motif_sans_estimation(inscription):
    bloc = inscription.get("duree_m3")
    if isinstance(bloc, dict) and bloc.get("statut") in (STATUT_ABSENTE, STATUT_ECARTEE):
        return f"estimation M3 {bloc['statut']} : {bloc.get('motif', 'sans détail')}"
    return "aucune estimation M3 n'a été retenue pour cette intervention (inscription sans devis, ou antérieure)"


def estimation_retenue(inscription):
    """Le bloc ``retenue`` de l'inscription, ou ``None``."""
    bloc = inscription.get("duree_m3") if isinstance(inscription, dict) else None
    if isinstance(bloc, dict) and bloc.get("statut") == STATUT_RETENUE:
        return bloc
    return None


def resoudre(inscription, duree_table, source_table, multijours):
    """``(bloc, None)`` ou ``(None, détail)`` : la durée effective d'une intervention.

    ``duree_table`` : minutes entières déclarées pour son service (profil ou surcharge, ``source_table`` le dit), ou
    ``None``. ``multijours`` : les règles lues par ``lire_multijours``, ou ``None`` si l'entreprise n'en a pas déclaré.
    Le bloc porte ``minutes`` (entières, arrondies vers le haut), ``source``, ``repli`` (vrai si la durée du service
    tient
    lieu d'estimation, avec ``raison_repli``), ``origine_m3`` et ``calibration_version_id`` (la durée de M3 est-elle
    corrigée par une version appliquée ?), ``ecart_profil_min`` (durée de M3 moins durée du service, signé) et
    ``visites`` (liste des durées, ou ``None`` pour un chantier d'une seule journée)."""
    retenue = estimation_retenue(inscription)
    bloc = {
        "minutes": None, "source": None, "repli": False, "raison_repli": None, "origine_m3": None,
        "calibration_version_id": None, "ecart_profil_min": None, "visites": None,
    }
    if retenue is not None:
        minutes = minutes_entieres(retenue["minutes"])
        if minutes is None:
            return None, f"durée retenue à l'inscription illisible ({retenue['minutes']!r})"
        bloc.update(
            minutes=minutes, source=SOURCE_ESTIMATION_M3, origine_m3=retenue["origine"],
            calibration_version_id=retenue.get("calibration_version_id"),
            ecart_profil_min=None if duree_table is None else minutes - duree_table,
        )
    elif duree_table is not None:
        bloc.update(minutes=duree_table, source=source_table, repli=True,
                    raison_repli=_motif_sans_estimation(inscription))
    else:
        return None, (
            "aucune durée : " + _motif_sans_estimation(inscription)
            + " et aucune durée déclarée pour ce service ou ce type de travaux (jamais une durée par défaut)"
        )
    minutes = bloc["minutes"]
    if multijours is not None:
        visites = decouper(minutes, multijours["visite_max_minutes"])
        if visites is None:
            return None, (
                f"durée de {minutes} min : plus de {tournees.MAX_VISITES} visites de "
                f"{multijours['visite_max_minutes']} min au plus ; relire la durée ou la durée maximale d'une visite"
            )
        if len(visites) > 1:
            bloc["visites"] = visites
    elif minutes > tournees.MINUTES_PAR_JOUR:
        return None, (
            f"durée de {minutes} min : plus d'une journée, mais les règles des chantiers de plusieurs jours ne "
            "sont pas déclarées ; " + _DECLARER_MULTIJOURS
        )
    return bloc, None


def libelle(bloc):
    """Phrase lisible qui dit d'où vient la durée (pour un verdict ou un volet de préparation)."""
    if bloc["source"] == SOURCE_ESTIMATION_M3:
        corrigee = ", corrigée par une version apprise appliquée" if bloc["origine_m3"] == ORIGINE_CALIBRATION else ""
        texte = f"{bloc['minutes']} min sur site (estimation M3{corrigee})"
    else:
        texte = f"{bloc['minutes']} min (durée du service, REPLI : {bloc['raison_repli']})"
    if bloc["visites"]:
        texte += f", {len(bloc['visites'])} visites de {' + '.join(str(v) for v in bloc['visites'])} min"
    return texte
