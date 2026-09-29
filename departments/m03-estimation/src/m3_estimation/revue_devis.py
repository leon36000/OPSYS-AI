"""Revue d'un devis avant son envoi (PLAN T4.7, DEFINITION-PRODUIT §7 M3.14).

« Validation humaine obligatoire si : confiance sous le seuil, montant au-dessus du seuil, marge sous
le seuil, photos insuffisantes, mesure incertaine, service complexe, client à risque, chantier éloigné,
prix sous le minimum rentable, donnée fournisseur absente. » Ce module dit, pour UN devis, lesquels de
ces motifs s'appliquent et lesquels il ne peut pas juger. Il ne décide de rien : le propriétaire décide
(N4, ``m3_demander_envoi_devis``) ; la revue lui dit POURQUOI regarder ce devis.

Trois sources, jamais une quatrième, et chaque motif nomme la sienne (``donnee.source``) :

- ``devis`` : ce que M3 a déjà calculé et gardé (``prix_total``, ``taux_marge``) ;
- ``contexte_revue`` : des faits que M3 ne détient pas et que l'appelant recopie de la réponse de
  ``m3_estimer_projet`` (``niveau_confiance_hierarchie``, ``verdict_estimation``, ``alerte_plancher``)
  ou qu'une personne connaît (complexité du service, risque du client, distance, données fournisseur) ;
- ``configuration`` : les seuils de ``department.yaml`` (``configuration.revue_devis``).

Fail-closed, jamais une valeur inventée :

- un seuil VIDE ou invalide ne devient jamais un chiffre par défaut : le critère est « non évaluable »
  et le dit (``seuil à configurer : marge_minimale``) ;
- un fait ABSENT ne passe jamais pour « rien à signaler » : le critère est « non évaluable » et dit
  quoi fournir. Rien n'est déduit du silence ;
- un fait fourni de travers (clé inconnue, type faux) refuse toute la revue
  (``REJ-REVUE-CONTEXTE-INVALIDE``), plutôt que d'être ignoré.

Deux motifs sont ROUGES : le prix du devis sous le minimum rentable, et l'alerte de plancher que
l'estimation a déjà levée (« jamais sous le minimum rentable sans alerte rouge et validation de
Nathan », §7 M3.11). Rouge veut dire « à regarder en premier », jamais « refusé » : la décision reste
humaine.

Le motif « mesure incertaine » n'a pas de seuil : il découle de la hiérarchie ratifiée
(``hierarchie_echelle.NIVEAUX_CONFIANCE``), où une seule photo sans échelle donne des bornes larges et
où « indéterminé » veut dire que M3 ne sait pas classer la mesure (§5 P2).

Module pur (ADR-0009, même règle que ``plancher.py``/``devis_relance.py``) : aucun import ``opsys``,
aucune horloge, aucun accès réseau. Les montants sont des ``Decimal`` construits depuis du texte ou
un nombre lu tel qu'écrit, jamais un calcul en virgule flottante.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from . import contrats, hierarchie_echelle, verdicts

__all__ = [
    "CHAMPS_CONTEXTE",
    "CHAMPS_SEUILS",
    "CODES_MOTIFS",
    "GRAVITE_PAR_MOTIF",
    "GRAVITE_REVUE",
    "GRAVITE_ROUGE",
    "LIMITE_RESUME",
    "SEUIL_A_CONFIGURER",
    "abreger",
    "evaluer_revue",
    "resume_attente",
    "synthese",
]

SOURCE_DEVIS = "devis"
SOURCE_CONTEXTE = "contexte_revue"
SOURCE_CONFIGURATION = "configuration"

GRAVITE_ROUGE = "rouge"
GRAVITE_REVUE = "revue"

# Le texte que rend un seuil vide (PLAN T4.6/T4.7 : « seuil à configurer », patron de M6 et de M8).
SEUIL_A_CONFIGURER = "seuil à configurer"

# Motifs, dans l'ordre où ils sont jugés et rendus (les rouges passent devant, voir `evaluer_revue`).
PRIX_SOUS_MINIMUM_RENTABLE = "PRIX_SOUS_MINIMUM_RENTABLE"
PLANCHER_ESTIMATION_FRANCHI = "PLANCHER_ESTIMATION_FRANCHI"
CONFIANCE_SOUS_SEUIL = "CONFIANCE_SOUS_SEUIL"
MESURE_INCERTAINE = "MESURE_INCERTAINE"
PHOTOS_INSUFFISANTES = "PHOTOS_INSUFFISANTES"
MONTANT_AU_DESSUS_SEUIL = "MONTANT_AU_DESSUS_SEUIL"
MARGE_SOUS_SEUIL = "MARGE_SOUS_SEUIL"
CHANTIER_ELOIGNE = "CHANTIER_ELOIGNE"
SERVICE_COMPLEXE = "SERVICE_COMPLEXE"
CLIENT_A_RISQUE = "CLIENT_A_RISQUE"
DONNEE_FOURNISSEUR_ABSENTE = "DONNEE_FOURNISSEUR_ABSENTE"

# La gravité de chaque motif, dans l'ordre où ils sont jugés et rendus. Deux sont ROUGES : le prix sous le
# minimum rentable et l'alerte de plancher que l'estimation a déjà levée. Un dictionnaire, pas un énuméré de
# domaine : ce n'est pas une classification d'une mesure incertaine (aucun motif « indéterminé » n'existe : ce qu'on
# ne peut pas juger est un critère « non évaluable », voir `evaluer_revue`), et `conformite.py` n'a donc pas à
# y exiger d'échappatoire.
GRAVITE_PAR_MOTIF = {
    PRIX_SOUS_MINIMUM_RENTABLE: GRAVITE_ROUGE,
    PLANCHER_ESTIMATION_FRANCHI: GRAVITE_ROUGE,
    CONFIANCE_SOUS_SEUIL: GRAVITE_REVUE,
    MESURE_INCERTAINE: GRAVITE_REVUE,
    PHOTOS_INSUFFISANTES: GRAVITE_REVUE,
    MONTANT_AU_DESSUS_SEUIL: GRAVITE_REVUE,
    MARGE_SOUS_SEUIL: GRAVITE_REVUE,
    CHANTIER_ELOIGNE: GRAVITE_REVUE,
    SERVICE_COMPLEXE: GRAVITE_REVUE,
    CLIENT_A_RISQUE: GRAVITE_REVUE,
    DONNEE_FOURNISSEUR_ABSENTE: GRAVITE_REVUE,
}
CODES_MOTIFS = tuple(GRAVITE_PAR_MOTIF)

# Faits que l'appelant peut fournir : ensemble FERMÉ, une clé inconnue refuse la revue.
CHAMPS_CONTEXTE = (
    "niveau_confiance_hierarchie",
    "verdict_estimation",
    "alerte_plancher",
    "service_complexe",
    "client_a_risque",
    "distance_km",
    "donnees_fournisseur_completes",
)
_CLES_BOOLEENNES = ("alerte_plancher", "service_complexe", "client_a_risque", "donnees_fournisseur_completes")

# Seuils de `department.yaml/configuration/revue_devis`. Aucun n'a de valeur par défaut ici.
CHAMPS_SEUILS = (
    "confiance_minimale",
    "montant_maximal_cad",
    "marge_minimale",
    "distance_maximale_km",
    "minimum_rentable_cad",
)

# Niveaux qu'un seuil de confiance peut nommer : les trois niveaux qui classent une mesure, jamais
# « indéterminé » (un minimum « indéterminé » n'exigerait rien). Dérivés du tuple ratifié, pas recopiés.
_NIVEAUX = hierarchie_echelle.NIVEAUX_CONFIANCE
_NIVEAUX_DE_SEUIL = _NIVEAUX[:3]
_NIVEAUX_MESURE_INCERTAINE = _NIVEAUX[2:]

LIMITE_RESUME = 240  # l'app du propriétaire (approbations_appareil.LIMITE_RESUME_ATTENTE) coupe au-delà


def abreger(texte: str, limite: int) -> str:
    """``texte`` réduit à ``limite`` caractères, ``…`` compris s'il a été coupé."""
    if len(texte) <= limite:
        return texte
    return texte[: limite - 1].rstrip() + "…"


def _decimal(valeur: Any) -> Decimal | None:
    """Un ``Decimal`` fini lu tel qu'écrit (texte, entier, flottant ou ``Decimal``), sinon ``None``.
    Un booléen n'est jamais un nombre. Le flottant passe par sa représentation décimale
    (``str(0.2)`` donne ``0.2``), jamais par son codage binaire."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, Decimal):
        lu = valeur
    elif isinstance(valeur, (int, float, str)):
        try:
            lu = Decimal(str(valeur).strip())
        except InvalidOperation:
            return None
    else:
        return None
    return lu if lu.is_finite() else None


def _texte(valeur: Decimal) -> str:
    return format(valeur, "f")


def _est_texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _lire_devis(devis: Any) -> tuple[tuple[str, Decimal, Decimal] | None, dict | None]:
    """``(devis_id, prix_total, taux_marge)`` du devis, ou un verdict s'il est inexploitable."""
    if not isinstance(devis, dict) or not _est_texte_non_vide(devis.get("devis_id")):
        return None, verdicts.construire_verdict(
            "REJ-REVUE-DEVIS-INVALIDE", detail="le devis doit être un dictionnaire portant un devis_id non vide"
        )
    prix_total = _decimal(devis.get("prix_total"))
    taux_marge = _decimal(devis.get("taux_marge"))
    if prix_total is None or taux_marge is None:
        return None, verdicts.construire_verdict(
            "REJ-REVUE-DEVIS-INVALIDE",
            detail=f"le devis {devis['devis_id']!r} doit porter prix_total et taux_marge, deux nombres décimaux finis",
        )
    return (devis["devis_id"], prix_total, taux_marge), None


def _lire_contexte(contexte: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """Les faits fournis, sans les valeurs nulles (un fait nul est un fait absent), ou un verdict.
    Toutes les fautes sont nommées d'un coup : l'appelant les corrige en un seul tour."""
    if contexte is None:
        return {}, None
    if not isinstance(contexte, dict):
        return None, verdicts.construire_verdict(
            "REJ-REVUE-CONTEXTE-INVALIDE", detail="contexte_revue doit être un objet (ou null)"
        )
    fautes = [f"clé inconnue : {cle!r}" for cle in sorted(set(contexte) - set(CHAMPS_CONTEXTE), key=str)]
    faits: dict[str, Any] = {}
    for cle in CHAMPS_CONTEXTE:
        valeur = contexte.get(cle)
        if valeur is None:
            continue
        if cle == "niveau_confiance_hierarchie" and valeur not in _NIVEAUX:
            fautes.append(f"{cle} : l'un de {list(_NIVEAUX)} est attendu")
        elif cle == "verdict_estimation" and valeur not in contrats.VERDICTS_ESTIMATION:
            fautes.append(f"{cle} : l'un de {list(contrats.VERDICTS_ESTIMATION)} est attendu")
        elif cle in _CLES_BOOLEENNES and not isinstance(valeur, bool):
            fautes.append(f"{cle} : un booléen est attendu")
        elif cle == "distance_km":
            distance = _decimal(valeur)
            if distance is None or distance < 0:
                fautes.append(f"{cle} : un nombre décimal fini, zéro ou plus, est attendu (kilomètres)")
                continue
            valeur = distance
        faits[cle] = valeur
    if fautes:
        return None, verdicts.construire_verdict("REJ-REVUE-CONTEXTE-INVALIDE", detail=" ; ".join(fautes))
    return faits, None


def _valider_seuil(cle: str, brut: Any) -> tuple[Any, str | None]:
    """``(valeur, None)`` d'un seuil présent et valide, ``(None, problème)`` sinon."""
    if cle == "confiance_minimale":
        if isinstance(brut, str) and brut in _NIVEAUX_DE_SEUIL:
            return brut, None
        return None, f"seuil invalide : {cle} doit être l'un de {list(_NIVEAUX_DE_SEUIL)}"
    valeur = _decimal(brut)
    if valeur is not None and (valeur >= 0 if cle == "marge_minimale" else valeur > 0):
        return valeur, None
    exigence = "zéro ou plus" if cle == "marge_minimale" else "strictement positif"
    return None, f"seuil invalide : {cle} doit être un nombre décimal fini, {exigence}"


def _lire_seuils(seuils: Any) -> dict[str, tuple[Any, str | None]]:
    """Pour chaque seuil : ``(valeur, None)`` ou ``(None, problème)``. Vide : ``seuil à configurer``."""
    if seuils is None:
        seuils = {}
    if not isinstance(seuils, dict):
        illisible = "seuil invalide : la configuration de la revue (configuration.revue_devis) est illisible"
        return {cle: (None, illisible) for cle in CHAMPS_SEUILS}
    lus: dict[str, tuple[Any, str | None]] = {}
    for cle in CHAMPS_SEUILS:
        brut = seuils.get(cle)
        lus[cle] = (None, f"{SEUIL_A_CONFIGURER} : {cle}") if brut is None else _valider_seuil(cle, brut)
    return lus


class _Entrees:
    """Ce dont un critère a besoin, lu une fois : les deux nombres du devis, les faits, les seuils."""

    def __init__(
        self, prix_total: Decimal, taux_marge: Decimal, faits: dict[str, Any],
        seuils: dict[str, tuple[Any, str | None]],
    ) -> None:
        self.prix_total = prix_total
        self.taux_marge = taux_marge
        self.faits = faits
        self.seuils = seuils


Manque = tuple[list[str], list[str]]  # (ce qui manque, quoi faire)


def _manques(entrees: _Entrees, faits: tuple[str, ...] = (), seuils: tuple[str, ...] = ()) -> Manque | None:
    """Ce qui empêche de juger un critère (faits absents, seuils vides ou invalides), ou ``None``."""
    manque: list[str] = []
    a_faire: list[str] = []
    for cle in faits:
        if cle not in entrees.faits:
            manque.append(f"donnée à fournir : {cle}")
            a_faire.append(f"fournir {cle} dans contexte_revue")
    for cle in seuils:
        probleme = entrees.seuils[cle][1]
        if probleme is not None:
            manque.append(probleme)
            a_faire.append(f"renseigner {cle} dans department.yaml, configuration, revue_devis")
    return (manque, a_faire) if manque else None


def _motif(
    code: str, donnee: tuple[str, str, str], explication: str, seuil: tuple[str, str] | None = None,
) -> dict[str, Any]:
    nom, valeur, source = donnee
    return {
        "code": code,
        "gravite": GRAVITE_PAR_MOTIF[code],
        "donnee": {"nom": nom, "valeur": valeur, "source": source},
        "seuil": None if seuil is None else {"nom": seuil[0], "valeur": seuil[1], "source": SOURCE_CONFIGURATION},
        "explication": explication,
    }


Critere = Callable[[_Entrees], tuple[dict[str, Any] | None, Manque | None]]

# Critères qui comparent UN nombre à UN seuil : (code, donnée, source de la donnée, clé du seuil,
# comparaison qui déclenche, gabarit de l'explication). Les comparaisons sont STRICTES : un devis
# exactement au seuil ne déclenche rien (même règle que `plancher.confronter_au_plancher`).
_SEUILS_DECIMAUX = (
    (PRIX_SOUS_MINIMUM_RENTABLE, "prix_total", SOURCE_DEVIS, "minimum_rentable_cad", operator.lt,
     "prix {donnee} $ sous le minimum rentable {seuil} $"),
    (MONTANT_AU_DESSUS_SEUIL, "prix_total", SOURCE_DEVIS, "montant_maximal_cad", operator.gt,
     "montant {donnee} $ au-dessus de {seuil} $"),
    (MARGE_SOUS_SEUIL, "taux_marge", SOURCE_DEVIS, "marge_minimale", operator.lt,
     "marge {donnee} sous {seuil}"),
    (CHANTIER_ELOIGNE, "distance_km", SOURCE_CONTEXTE, "distance_maximale_km", operator.gt,
     "chantier à {donnee} km (max {seuil} km)"),
)

# Critères qui lisent UN fait booléen : (code, clé du fait, valeur qui déclenche, explication).
_FAITS_BOOLEENS = (
    (PLANCHER_ESTIMATION_FRANCHI, "alerte_plancher", True, "plancher de rentabilité franchi (alerte de l'estimation)"),
    (SERVICE_COMPLEXE, "service_complexe", True, "service complexe"),
    (CLIENT_A_RISQUE, "client_a_risque", True, "client à risque"),
    (DONNEE_FOURNISSEUR_ABSENTE, "donnees_fournisseur_completes", False, "donnée fournisseur absente"),
)


def _critere_seuil_decimal(
    code: str, nom_donnee: str, source: str, cle_seuil: str, compare: Callable[[Decimal, Decimal], bool],
    gabarit: str,
) -> Critere:
    def juger(entrees: _Entrees) -> tuple[dict[str, Any] | None, Manque | None]:
        lus_du_devis = {"prix_total": entrees.prix_total, "taux_marge": entrees.taux_marge}
        donnee = lus_du_devis[nom_donnee] if source == SOURCE_DEVIS else entrees.faits.get(nom_donnee)
        manque = _manques(entrees, faits=() if source == SOURCE_DEVIS else (nom_donnee,), seuils=(cle_seuil,))
        if manque is not None:
            return None, manque
        seuil = entrees.seuils[cle_seuil][0]
        if not compare(donnee, seuil):
            return None, None
        return _motif(
            code, (nom_donnee, _texte(donnee), source),
            gabarit.format(donnee=_texte(donnee), seuil=_texte(seuil)), (cle_seuil, _texte(seuil)),
        ), None

    return juger


def _critere_fait_booleen(code: str, cle: str, declenche: bool, explication: str) -> Critere:
    def juger(entrees: _Entrees) -> tuple[dict[str, Any] | None, Manque | None]:
        manque = _manques(entrees, faits=(cle,))
        if manque is not None:
            return None, manque
        valeur = entrees.faits[cle]
        if valeur is not declenche:
            return None, None
        return _motif(code, (cle, "vrai" if valeur else "faux", SOURCE_CONTEXTE), explication), None

    return juger


def _juger_confiance_sous_seuil(entrees: _Entrees) -> tuple[dict[str, Any] | None, Manque | None]:
    manque = _manques(entrees, faits=("niveau_confiance_hierarchie",), seuils=("confiance_minimale",))
    if manque is not None:
        return None, manque
    niveau = entrees.faits["niveau_confiance_hierarchie"]
    minimum = entrees.seuils["confiance_minimale"][0]
    if _NIVEAUX.index(niveau) <= _NIVEAUX.index(minimum):  # 0 = le mieux classé
        return None, None
    return _motif(
        CONFIANCE_SOUS_SEUIL, ("niveau_confiance_hierarchie", niveau, SOURCE_CONTEXTE),
        f"confiance {niveau} sous {minimum}", ("confiance_minimale", minimum),
    ), None


def _juger_mesure_incertaine(entrees: _Entrees) -> tuple[dict[str, Any] | None, Manque | None]:
    manque = _manques(entrees, faits=("niveau_confiance_hierarchie",))
    if manque is not None:
        return None, manque
    niveau = entrees.faits["niveau_confiance_hierarchie"]
    if niveau not in _NIVEAUX_MESURE_INCERTAINE:
        return None, None
    return _motif(
        MESURE_INCERTAINE, ("niveau_confiance_hierarchie", niveau, SOURCE_CONTEXTE), "mesure incertaine"
    ), None


def _juger_photos_insuffisantes(entrees: _Entrees) -> tuple[dict[str, Any] | None, Manque | None]:
    manque = _manques(entrees, faits=("verdict_estimation",))
    if manque is not None:
        return None, manque
    verdict = entrees.faits["verdict_estimation"]
    if verdict != contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE:
        return None, None
    return _motif(
        PHOTOS_INSUFFISANTES, ("verdict_estimation", verdict, SOURCE_CONTEXTE),
        "photos insuffisantes (verdict de l'estimation)",
    ), None


def _criteres() -> dict[str, Critere]:
    criteres: dict[str, Critere] = {
        CONFIANCE_SOUS_SEUIL: _juger_confiance_sous_seuil,
        MESURE_INCERTAINE: _juger_mesure_incertaine,
        PHOTOS_INSUFFISANTES: _juger_photos_insuffisantes,
    }
    for code, nom_donnee, source, cle_seuil, compare, gabarit in _SEUILS_DECIMAUX:
        criteres[code] = _critere_seuil_decimal(code, nom_donnee, source, cle_seuil, compare, gabarit)
    for code, cle, declenche, explication in _FAITS_BOOLEENS:
        criteres[code] = _critere_fait_booleen(code, cle, declenche, explication)
    return criteres


def evaluer_revue(
    devis: Any, contexte: Any, seuils: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """La revue d'un devis : ``(revue, None)``, ou ``(None, verdict)`` si le devis ou le contexte est
    inexploitable. ``revue`` porte exactement :

    - ``devis_id`` ;
    - ``alerte_rouge`` : vrai si un motif rouge s'applique ;
    - ``motifs`` : les critères qui s'appliquent, les rouges d'abord, puis dans l'ordre de
      ``CODES_MOTIFS``. Chacun : ``code``, ``gravite``, ``donnee`` (``nom``, ``valeur``, ``source``),
      ``seuil`` (``nom``, ``valeur``, ``source``, ou ``None`` quand le critère n'en a pas) et
      ``explication`` ;
    - ``non_evaluables`` : les critères qu'un fait absent ou un seuil vide empêche de juger. Chacun :
      ``code``, ``manque`` (ce qui manque, dont « seuil à configurer : <clé> »), ``a_faire`` ;
    - ``aucun_motif`` : vrai seulement si TOUS les critères sont jugés et qu'aucun ne s'applique. Un
      devis dont des critères ne sont pas jugés n'est jamais présenté comme sans motif.

    ``devis`` : l'état courant d'un devis durable (``prix_total`` et ``taux_marge`` lus tels quels,
    jamais recalculés). ``contexte`` : les faits fournis (``CHAMPS_CONTEXTE``), ou ``None``.
    ``seuils`` : ``configuration.revue_devis`` de ``department.yaml`` (``CHAMPS_SEUILS``), ou ``None``."""
    lu, verdict = _lire_devis(devis)
    if verdict is not None:
        return None, verdict
    devis_id, prix_total, taux_marge = lu
    faits, verdict = _lire_contexte(contexte)
    if verdict is not None:
        return None, verdict
    entrees = _Entrees(prix_total, taux_marge, faits, _lire_seuils(seuils))

    motifs: list[dict[str, Any]] = []
    non_evaluables: list[dict[str, Any]] = []
    criteres = _criteres()
    for code in CODES_MOTIFS:
        motif, manque = criteres[code](entrees)
        if motif is not None:
            motifs.append(motif)
        if manque is not None:
            non_evaluables.append({"code": code, "manque": manque[0], "a_faire": manque[1]})
    motifs.sort(key=lambda m: (m["gravite"] != GRAVITE_ROUGE, CODES_MOTIFS.index(m["code"])))
    return {
        "devis_id": devis_id,
        "alerte_rouge": any(m["gravite"] == GRAVITE_ROUGE for m in motifs),
        "motifs": motifs,
        "non_evaluables": non_evaluables,
        "aucun_motif": not motifs and not non_evaluables,
    }, None


def synthese(revue: dict[str, Any]) -> dict[str, Any]:
    """Ce qu'on garde au registre du devis : l'alerte et les CODES, jamais les valeurs (le taux de marge
    et le prix vivent déjà dans le devis ; la trace de ce qu'on a regardé n'en fait pas une seconde copie)."""
    return {
        "alerte_rouge": revue["alerte_rouge"],
        "motifs": [m["code"] for m in revue["motifs"]],
        "non_evaluables": [n["code"] for n in revue["non_evaluables"]],
    }


def resume_attente(revue: dict[str, Any], limite: int = LIMITE_RESUME) -> str:
    """Le texte de l'attente du propriétaire : le devis, l'alerte rouge en premier, les autres motifs,
    puis le nombre de critères non évaluables. Borné à ``limite`` caractères (l'app coupe à 240) : ce
    qui compte le plus est dit d'abord, et ce qui ne tient pas est compté (``+ 2 autres``), jamais coupé
    au milieu d'un motif ni passé sous silence."""
    tete = f"Envoi du devis {revue['devis_id']} à approuver"
    rouges = [m["explication"] for m in revue["motifs"] if m["gravite"] == GRAVITE_ROUGE]
    parties: list[str] = []
    if rouges:
        parties.append("ALERTE ROUGE : " + " ; ".join(rouges))
    parties.extend(m["explication"] for m in revue["motifs"] if m["gravite"] != GRAVITE_ROUGE)
    nombre = len(revue["non_evaluables"])
    if nombre:
        pluriel = "s" if nombre > 1 else ""
        parties.append(f"{nombre} critère{pluriel} non évaluable{pluriel} (seuil à configurer ou donnée à fournir)")
    if not parties:
        return abreger(f"{tete} : aucun motif de revue.", limite)
    for gardees in range(len(parties), 0, -1):
        reste = len(parties) - gardees
        suite = f" ; + {reste} autre{'s' if reste > 1 else ''}" if reste else ""
        texte = f"{tete} : " + " ; ".join(parties[:gardees]) + suite
        if len(texte) <= limite:
            return texte
    return abreger(f"{tete} : {parties[0]}", limite)
