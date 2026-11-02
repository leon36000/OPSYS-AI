"""Radar de risques M9.12 : des signaux déjà mesurés par leurs propriétaires, datés, gradués, contestables.

Module pur. Chaque risque vient d'une RÈGLE versionnée appliquée à des captures complètes (M9.1) : le signal est la
valeur même que le propriétaire a publiée (alerte de seuil de M5, réservation partielle de M6, incident bloqué de M4,
écart de marge de M8, plaintes de M1, capacité de M4, dépenses de M7, intervalle de M2, filet SLA de M2, cash libre
constaté par M5 et repris par M8…). M9 n'invente ni seuil ni cause :

* le SEUIL d'une règle quantitative est DÉCLARÉ par la direction (couche des réglages de direction, ``REGLAGES``) ; une
  règle dont un seuil n'est pas déclaré n'est PAS évaluée : elle est listée avec ce qu'il faut déclarer, jamais comptée
  comme « aucun risque » ;
* la GRAVITÉ vient d'une grille versionnée (``GRILLE``), PROPOSÉE et non validée par Nathan ; elle est rendue avec
chaque
  risque. ``CRITIQUE`` n'existe que par un dépassement DÉCLARÉ (le seuil multiplié par ``multiple_seuil_critique``) ou
  par un fait structurel du propriétaire (cash libre négatif) ; sans le multiple déclaré, aucun dépassement n'est dit
  critique (et le radar le dit) ;
* chaque risque dit POURQUOI (``raison``), la MESURE du propriétaire et le SEUIL déclaré qu'elle franchit, et cite ses
  preuves (adresses de faits de captures) ;
* une règle dont la lecture est absente, refusée, partielle ou contradictoire n'est PAS évaluée : elle est listée comme
  donnée manquante (« risque inconnu »), jamais comptée comme « aucun risque » ;
* un risque présent dans une version plus ancienne de la lecture mais absent de la plus récente est LEVÉ (faux positif
  possible) : les deux preuves sont citées ;
* un risque dont la source est plus ancienne que la péremption demandée est À RECONFIRMER, non affirmé ;
* ``origine_etablie`` reste faux : le radar ne dit jamais pourquoi (la cause), il dit quoi, quand, combien et d'où.

M9 ne calcule aucun chiffre d'affaires ici : il COMPARE une mesure publiée à un seuil déclaré (comparaison exacte en
``Decimal``, croisée pour les rapports de minutes — aucune division).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs
from . import catalogue_producteurs as cat

VERSION = "2026-11-02.1"
GRILLE_STATUT = "PROPOSEE_NON_VALIDEE_PAR_NATHAN"
GRADES = ("FAIBLE", "MOYEN", "ELEVE", "CRITIQUE", "INCONNU")
EXPLICATION = "origine non établie par M9 : le signal est publié par son propriétaire, sans cause"
DOMAINE_AVIS = "Réglages de direction"
_LIMITES = (
    "Signaux des propriétaires ; gravité selon une grille proposée, non validée.",
    "Une règle non évaluée (lecture manquante ou seuil non déclaré) est un risque INCONNU, jamais nul.",
    "Aucun prix de fournisseur n'est lu par M9 : sa hausse n'est pas évaluée (seule la surconsommation de M6 l'est).",
)
_R = "resultat.resultat"


# ----------------------------------------------------------------------------------------------- réglages déclarés
@dataclass(frozen=True)
class Reglage:
    nom: str  # nom court (clé de ``seuils``) ; la clé de direction est ``m9.<nom>``
    libelle: str
    unite: str
    nature: str  # "entier" | "decimal"

    @property
    def cle(self) -> str:
        return f"m9.{self.nom}"


REGLAGES: Mapping[str, Reglage] = {
    r.nom: r
    for r in (
        Reglage(
            "plaintes_seuil_nombre",
            "Nombre de plaintes déclarées dans la période lue qui déclenche un risque",
            "plaintes",
            "entier",
        ),
        Reglage(
            "capacite_utilisation_seuil_pct",
            "Part des heures de quart déclarées d'une équipe déjà planifiée qui déclenche un risque de surcharge",
            "%",
            "decimal",
        ),
        Reglage(
            "depense_marketing_plafond_cad", "Plafond de dépense marketing pour la période lue de M7", "CAD", "decimal"
        ),
        Reglage(
            "leads_plancher_par_semaine",
            "Nombre de leads par semaine sous lequel la borne haute de la prévision de M2 signale une baisse",
            "leads/semaine",
            "entier",
        ),
        Reglage(
            "estimation_ecart_relatif_max",
            "Dépassement relatif de la durée estimée (0,25 = 25 %) qui signale une erreur d'estimation",
            "fraction",
            "decimal",
        ),
        Reglage(
            "retard_chantier_jours",
            "Nombre de jours de report d'un chantier qui en fait un retard prolongé",
            "jours",
            "entier",
        ),
        Reglage(
            "donnees_perimees_jours",
            "Âge, en jours, au-delà duquel une lecture n'est plus considérée à jour",
            "jours",
            "entier",
        ),
        Reglage(
            "cash_libre_plancher_cad", "Cash libre minimal toléré (en dessous, un risque est signalé)", "CAD", "decimal"
        ),
        Reglage(
            "multiple_seuil_critique",
            "Multiple d'un seuil à partir duquel un dépassement est dit critique (escalade interne)",
            "× le seuil",
            "decimal",
        ),
    )
}


def _dec(valeur: object) -> Decimal | None:
    """Un nombre publié par un propriétaire (texte décimal, entier ou flottant JSON) ; jamais un booléen."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float, str)):
        return None
    try:
        lu = Decimal(str(valeur).strip())
    except (InvalidOperation, ValueError):
        return None
    return lu if lu.is_finite() else None


def _texte(valeur: Decimal) -> str:
    return format(valeur.normalize(), "f") if not valeur.is_zero() else "0"


@dataclass(frozen=True)
class Contexte:
    """Ce que le signal d'une règle a le droit de savoir en plus de sa ligne : les seuils DÉCLARÉS, l'instant de
    connaissance et le multiple critique (``None`` : non déclaré)."""

    seuils: Mapping[str, Decimal]
    maintenant: datetime | None
    multiple: Decimal | None

    def seuil(self, nom: str) -> Decimal:
        return self.seuils[nom]

    def bloc_seuil(self, nom: str, *, critique: bool = True) -> dict:
        valeur = self.seuils[nom]
        bloc = {"reglage": REGLAGES[nom].cle, "valeur": _texte(valeur), "unite": REGLAGES[nom].unite}
        if critique:
            bloc["critique_si_au_moins"] = None if self.multiple is None else _texte(valeur * self.multiple)
        return bloc


@dataclass(frozen=True)
class Signal:
    gravite: str
    sujet: str
    champs: tuple[str, ...]
    raison: str
    mesure: Mapping | None = None
    seuil: Mapping | None = None


@dataclass(frozen=True)
class Regle:
    id: str
    domaine: str
    lecture_id: str
    lignes: str  # chemin vers la liste de lignes à examiner, ou vers l'objet racine
    signal: Callable[..., Signal | Sequence[Signal] | None]
    seuils: tuple[str, ...] = ()  # noms de ``REGLAGES`` requis ; absent : la règle n'est pas évaluée
    amont: Callable[[Mapping], list[dict]] | None = None  # règles non évaluées PAR LE PROPRIÉTAIRE (page lue)

    def __post_init__(self) -> None:
        if not self.id or not self.domaine or not self.lignes or not set(self.seuils) <= set(REGLAGES):
            raise ValueError("règle de risque incomplète")


# -------------------------------------------------------------------------------------- règles historiques (sans seuil)
def _signal_alerte_cash(ligne: Mapping, ctx: Contexte) -> Signal | None:
    alerte = ligne.get("alerte")
    if not isinstance(alerte, Mapping) or alerte.get("statut") != "ALERTE":
        return None
    deficit = ligne.get("premiere_semaine_en_deficit") is not None
    return Signal(
        "ELEVE" if deficit else "MOYEN", "tresorerie", ("alerte.statut", "premiere_semaine_en_deficit"),
        "la prévision de trésorerie de M5 est en alerte" + (" et annonce une semaine en déficit" if deficit else ""),
    )  # fmt: skip


def _signal_cash_inconnu(ligne: Mapping, ctx: Contexte) -> Signal | None:
    alerte = ligne.get("alerte") if isinstance(ligne.get("alerte"), Mapping) else {}
    if ligne.get("calculable") is False or alerte.get("statut") in ("NON_EVALUEE", "SEUIL_A_CONFIGURER"):
        return Signal(
            "INCONNU", "tresorerie", ("calculable", "alerte.statut"),
            "la prévision de trésorerie de M5 n'est pas évaluable (seuil à configurer ou donnée manquante chez M5)",
        )  # fmt: skip
    return None


def _signal_reservation(ligne: Mapping, ctx: Contexte) -> Signal | None:
    statut = ligne.get("statut")
    if statut not in ("partiel", "a_commander") or type(ligne.get("devis_id")) is not str:
        return None
    return Signal(
        "ELEVE" if statut == "a_commander" else "MOYEN", f"devis:{ligne['devis_id']}", ("statut", "devis_id"),
        "la réservation de matériaux d'un devis est " + ("à commander" if statut == "a_commander" else "partielle"),
    )  # fmt: skip


def _signal_incident(ligne: Mapping, ctx: Contexte) -> Signal | None:
    if type(ligne.get("demande_id")) is not str:
        return None
    bloquee = ligne.get("bloquee") is True
    return Signal(
        "ELEVE" if bloquee else "FAIBLE", f"incident:{ligne['demande_id']}", ("bloquee", "demande_id"),
        "un incident de chantier est ouvert chez M4" + (" et bloque le chantier" if bloquee else ""),
    )  # fmt: skip


def _signal_report(ligne: Mapping, ctx: Contexte) -> Signal | None:
    if type(ligne.get("intervention_id")) is not str or ligne.get("motif") == "meteo":
        return None
    return Signal("FAIBLE", f"report:{ligne['intervention_id']}", ("motif",), "une intervention est reportée chez M4")


def _signal_meteo(ligne: Mapping, ctx: Contexte) -> Signal | None:
    if type(ligne.get("intervention_id")) is not str or ligne.get("motif") != "meteo":
        return None
    return Signal(
        "MOYEN", f"report:{ligne['intervention_id']}", ("motif",), "une intervention est reportée pour la météo"
    )


def _signal_ecart_marge(ligne: Mapping, ctx: Contexte) -> Signal | None:
    if ligne.get("metric_id") != "m8_ecart_marge_cad":
        return None
    valeur = _dec(ligne.get("valeur")) if type(ligne.get("valeur")) is str else None
    if valeur is None or valeur >= 0:
        return None
    return Signal(
        "MOYEN", "rentabilite_chantier", ("metric_id", "valeur"),
        "l'écart de marge d'un chantier mesuré par M8 est négatif",
        mesure={"valeur": ligne["valeur"], "unite": "CAD"},
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------ règles à seuil déclar
def _signal_plaintes_afflux(ligne: Mapping, ctx: Contexte) -> Signal | None:
    comptes = ligne.get("comptes")
    declarees = comptes.get("declarees") if isinstance(comptes, Mapping) else None
    if type(declarees) is not int or ligne.get("etat") == "NON_BRANCHEE":
        return None
    seuil = ctx.seuil("plaintes_seuil_nombre")
    if declarees < seuil:
        return None
    periode = ligne.get("periode") if isinstance(ligne.get("periode"), Mapping) else {}
    jours = periode.get("jours") if type(periode.get("jours")) is int else None
    critique = ctx.multiple is not None and Decimal(declarees) >= seuil * ctx.multiple
    return Signal(
        "CRITIQUE" if critique else "ELEVE", "plaintes_periode", ("comptes.declarees", "periode.jours"),
        f"{declarees} plainte(s) déclarée(s) par M1 sur la période lue, au seuil déclaré ou au-delà",
        mesure={"valeur": str(declarees), "unite": "plaintes", "periode_jours": jours},
        seuil=ctx.bloc_seuil("plaintes_seuil_nombre"),
    )  # fmt: skip


_CATEGORIES_SENSIBLES = frozenset({"avocat", "securite"})


def _signal_plainte_sensible(ligne: Mapping, ctx: Contexte) -> Signal | None:
    categories = ligne.get("categories")
    if (
        ligne.get("statut") != "ouvert"
        or type(ligne.get("plainte_id")) is not str
        or not isinstance(categories, list)
        or not _CATEGORIES_SENSIBLES & {c for c in categories if type(c) is str}
    ):
        return None
    return Signal(
        "ELEVE", f"plainte:{ligne['plainte_id']}", ("categories", "statut"),
        "une plainte ouverte relève d'une catégorie sensible (avocat ou sécurité) selon M1",
    )  # fmt: skip


def _signal_surcharge(ligne: Mapping, ctx: Contexte) -> Signal | None:
    planifiees, disponibles = ligne.get("minutes_planifiees"), ligne.get("minutes_disponibles")
    if (
        type(planifiees) is not int
        or type(disponibles) is not int
        or type(ligne.get("equipe_id")) is not str
        or planifiees <= 0
        or disponibles < 0
    ):
        return None
    seuil = ctx.seuil("capacite_utilisation_seuil_pct")
    # planifié / disponible ≥ seuil/100, sans division : une équipe sans heure déclarée mais planifiée dépasse tout
    # seuil.
    if Decimal(planifiees) * 100 < seuil * disponibles:
        return None
    critique = ctx.multiple is not None and Decimal(planifiees) * 100 >= seuil * ctx.multiple * disponibles
    return Signal(
        "CRITIQUE" if critique else "ELEVE", f"equipe:{ligne['equipe_id']}",
        ("equipe_id", "minutes_planifiees", "minutes_disponibles"),
        "les heures planifiées de la cédule d'une équipe atteignent le seuil déclaré de ses heures de quart déclarées",
        mesure={"heures_planifiees": ligne.get("heures_planifiees"),
                "heures_disponibles": ligne.get("heures_disponibles"), "unite": "heures_declarees"},
        seuil=ctx.bloc_seuil("capacite_utilisation_seuil_pct"),
    )  # fmt: skip


def _signal_depense_marketing(ligne: Mapping, ctx: Contexte) -> Signal | None:
    if ligne.get("statut") != "CONNUE":
        return None
    total = _dec(ligne.get("total_cad")) if type(ligne.get("total_cad")) is str else None
    plafond = ctx.seuil("depense_marketing_plafond_cad")
    if total is None or total <= plafond:
        return None
    periode = ligne.get("periode") if isinstance(ligne.get("periode"), Mapping) else {}
    critique = ctx.multiple is not None and total >= plafond * ctx.multiple
    return Signal(
        "CRITIQUE" if critique else "ELEVE", "depense_marketing_periode", ("statut", "total_cad", "periode.debut"),
        "la dépense marketing établie par M7 pour la période lue dépasse le plafond déclaré",
        mesure={"valeur": ligne["total_cad"], "unite": "CAD", "periode": {"debut": periode.get("debut"),
                                                                           "fin": periode.get("fin")}},
        seuil=ctx.bloc_seuil("depense_marketing_plafond_cad"),
    )  # fmt: skip


def _signal_leads_plancher(ligne: Mapping, ctx: Contexte) -> list[Signal] | None:
    serie = ligne.get("serie")
    periodes = ligne.get("par_periode")
    if not isinstance(serie, Mapping) or serie.get("nom") != "leads_ingeres" or not isinstance(periodes, list):
        return None
    plancher = ctx.seuil("leads_plancher_par_semaine")
    trouves: list[Signal] = []
    for rang, periode in enumerate(periodes):
        intervalle = periode.get("intervalle") if isinstance(periode, Mapping) else None
        haut = _dec(intervalle.get("haut")) if isinstance(intervalle, Mapping) else None
        if haut is None or haut >= plancher or type(periode.get("periode")) not in (str, int):
            continue
        trouves.append(Signal(
            "MOYEN", f"periode:{periode['periode']}", (f"par_periode[{rang}].intervalle.haut",),
            "même la borne haute de l'intervalle de prévision de M2 reste sous le plancher déclaré de leads/semaine",
            mesure={"borne_haute": _texte(haut), "unite": "leads/semaine", "niveau_intervalle": "déclaré par M2"},
            seuil=ctx.bloc_seuil("leads_plancher_par_semaine", critique=False),
        ))  # fmt: skip
    return trouves or None


def _signal_estimation(ligne: Mapping, ctx: Contexte) -> Signal | None:
    main = ligne.get("main_doeuvre")
    ecart = _dec(main.get("ecart_relatif")) if isinstance(main, Mapping) else None
    seuil = ctx.seuil("estimation_ecart_relatif_max")
    if ecart is None or type(ligne.get("wct_id")) is not str or ecart < seuil:
        return None
    critique = ctx.multiple is not None and ecart >= seuil * ctx.multiple
    return Signal(
        "CRITIQUE" if critique else "ELEVE", f"wct:{ligne['wct_id']}", ("wct_id", "main_doeuvre.ecart_relatif"),
        "la durée réelle d'un chantier dépasse la durée estimée de M3 d'au moins le seuil déclaré",
        mesure={"ecart_relatif": _texte(ecart), "unite": "fraction"},
        seuil=ctx.bloc_seuil("estimation_ecart_relatif_max"),
    )  # fmt: skip


def _signal_variance_materiaux(ligne: Mapping, ctx: Contexte) -> Signal | None:
    materiaux = ligne.get("materiaux")
    if not isinstance(materiaux, Mapping) or materiaux.get("signal_critique") is not True:
        return None
    if type(ligne.get("wct_id")) is not str:
        return None
    return Signal(
        "ELEVE", f"wct:{ligne['wct_id']}", ("wct_id", "materiaux.signal_critique"),
        "M6 signale une surconsommation de matériaux critique sur un chantier terminé (seuil propre à M6)",
        mesure={"seuil_pourcentage_m6": materiaux.get("seuil_pourcentage")},
    )  # fmt: skip


def _signal_stock_negatif(ligne: Mapping, ctx: Contexte) -> Signal | None:
    disponible = _dec(ligne.get("disponible")) if type(ligne.get("disponible")) is str else None
    if disponible is None or disponible >= 0 or type(ligne.get("materiau_id")) is not str:
        return None
    return Signal(
        "ELEVE", f"materiau:{ligne['materiau_id']}", ("materiau_id", "disponible"),
        "la quantité réservée d'un matériau dépasse ce qu'il y a en main chez M6 (disponible négatif)",
        mesure={"disponible": ligne["disponible"]},
    )  # fmt: skip


def _signal_retard_prolonge(ligne: Mapping, ctx: Contexte) -> Signal | None:
    depuis = cs.instant(ligne.get("depuis"))
    if depuis is None or ctx.maintenant is None or type(ligne.get("intervention_id")) is not str:
        return None
    seuil = ctx.seuil("retard_chantier_jours")
    age = (ctx.maintenant - depuis).days
    if Decimal(age) < seuil:
        return None
    critique = ctx.multiple is not None and Decimal(age) >= seuil * ctx.multiple
    return Signal(
        "CRITIQUE" if critique else "ELEVE", f"retard:{ligne['intervention_id']}", ("intervention_id", "depuis"),
        "une intervention est reportée depuis au moins le nombre de jours déclaré",
        mesure={"valeur": str(age), "unite": "jours"}, seuil=ctx.bloc_seuil("retard_chantier_jours"),
    )  # fmt: skip


def _signal_cash_libre_deficit(ligne: Mapping, ctx: Contexte) -> Signal | None:
    constat = ligne.get("constat")
    if not isinstance(constat, Mapping) or constat.get("statut") != "CALCULE":
        return None
    montant = _dec(constat.get("cash_libre_cad")) if type(constat.get("cash_libre_cad")) is str else None
    if montant is None or montant >= 0:
        return None
    return Signal(
        "CRITIQUE", "cash_libre", ("constat.statut", "constat.cash_libre_cad"),
        "le cash libre constaté par M5 est négatif (déficit réel)",
        mesure={"valeur": constat["cash_libre_cad"], "unite": "CAD"},
    )  # fmt: skip


def _signal_cash_libre_inconnu(ligne: Mapping, ctx: Contexte) -> Signal | None:
    constat = ligne.get("constat")
    if ligne.get("statut") == "manque" or (isinstance(constat, Mapping) and constat.get("statut") != "CALCULE"):
        return Signal(
            "INCONNU", "cash_libre", ("statut",),
            "M5 n'a publié aucun cash libre calculé : l'argent réellement libre est inconnu, non nul",
        )  # fmt: skip
    return None


def _signal_cash_libre_plancher(ligne: Mapping, ctx: Contexte) -> Signal | None:
    constat = ligne.get("constat")
    if not isinstance(constat, Mapping) or constat.get("statut") != "CALCULE":
        return None
    montant = _dec(constat.get("cash_libre_cad")) if type(constat.get("cash_libre_cad")) is str else None
    plancher = ctx.seuil("cash_libre_plancher_cad")
    if montant is None or montant < 0 or montant >= plancher:
        return None  # un déficit est dit par ``cash_libre_deficit`` ; ici, le sous-plancher non négatif
    return Signal(
        "ELEVE", "cash_libre", ("constat.statut", "constat.cash_libre_cad"),
        "le cash libre constaté par M5 est sous le plancher déclaré",
        mesure={"valeur": constat["cash_libre_cad"], "unite": "CAD"}, seuil=ctx.bloc_seuil(
            "cash_libre_plancher_cad", critique=False),
    )  # fmt: skip


_SLA_GRAVES = frozenset({"lead_chaud_non_contacte", "plainte_non_escaladee"})


def _signal_sla(ligne: Mapping, ctx: Contexte) -> Signal | None:
    violations = ligne.get("violations")
    if ligne.get("etat") == "non_evaluee" or type(violations) is not int or violations <= 0:
        return None
    regle = ligne.get("regle")
    if type(regle) is not str:
        return None
    return Signal(
        "ELEVE" if regle in _SLA_GRAVES else "MOYEN", f"sla:{regle}", ("regle", "violations"),
        "le filet anti-perte de M2 compte des violations d'un délai (SLA) déclaré par M2",
        mesure={"valeur": str(violations), "unite": "violations"},
    )  # fmt: skip


def _amont_sla(page: Mapping) -> list[dict]:
    """Les règles SLA que M2 dit NON évaluées (son délai n'est pas déclaré chez lui) : un risque inconnu, pas nul."""
    sorties = []
    for ligne in cs.extraire(page, f"{_R}.regles[*]"):
        if isinstance(ligne, Mapping) and ligne.get("etat") == "non_evaluee" and type(ligne.get("regle")) is str:
            sorties.append({
                "regle": f"filet_sla_violation:{ligne['regle']}", "domaine": "ventes",
                "raison": "NON_EVALUEE_PAR_LE_PROPRIETAIRE", "a_declarer_chez": "m02-revenue-crm",
            })  # fmt: skip
    return sorties


REGLES: tuple[Regle, ...] = (
    Regle("cash_alerte_seuil", "cash", "m5.prevision_tresorerie", _R, _signal_alerte_cash),
    Regle("cash_non_evaluable", "cash", "m5.prevision_tresorerie", _R, _signal_cash_inconnu),
    Regle("materiaux_reservation_incomplete", "materiaux", "m6.disponibilite",
          f"{_R}.reservations_actives[*]", _signal_reservation),
    Regle("capacite_incident_ouvert", "capacite", "m4.retards_incidents", f"{_R}.incidents.liste[*]", _signal_incident),
    Regle("capacite_report_en_cours", "capacite", "m4.retards_incidents", f"{_R}.reports.liste[*]", _signal_report),
    Regle("meteo_report_en_cours", "meteo", "m4.retards_incidents", f"{_R}.reports.liste[*]", _signal_meteo),
    Regle("qualite_ecart_marge_negatif", "qualite", "m8.mesures_chantier", "resultat.mesures[*]", _signal_ecart_marge),
    # --- Règles à seuil DÉCLARÉ ou à fait structurel du propriétaire (2026-11-02) ---
    Regle("plaintes_afflux", "plaintes", "m1.plaintes_structurees", _R, _signal_plaintes_afflux,
          ("plaintes_seuil_nombre",)),
    Regle("plaintes_sensibles_ouvertes", "reputation", "m1.plaintes_structurees", f"{_R}.plaintes[*]",
          _signal_plainte_sensible),
    Regle("capacite_surcharge_cedule", "capacite", "m4.capacite_equipe", f"{_R}.equipes[*]", _signal_surcharge,
          ("capacite_utilisation_seuil_pct",)),
    Regle("depense_marketing_plafond", "marketing", "m7.depenses_marketing", "resultat", _signal_depense_marketing,
          ("depense_marketing_plafond_cad",)),
    Regle("leads_sous_plancher", "ventes", "m2.prevision_pipeline", _R, _signal_leads_plancher,
          ("leads_plancher_par_semaine",)),
    Regle("estimation_ecart_main_doeuvre", "estimation", "m3.ecarts", f"{_R}[*]", _signal_estimation,
          ("estimation_ecart_relatif_max",)),
    Regle("materiaux_variance_critique", "materiaux", "m3.ecarts", f"{_R}[*]", _signal_variance_materiaux),
    Regle("materiaux_disponible_negatif", "materiaux", "m6.disponibilite", f"{_R}.articles[*]", _signal_stock_negatif),
    Regle("chantier_retard_prolonge", "chantiers", "m4.retards_incidents", f"{_R}.reports.liste[*]",
          _signal_retard_prolonge, ("retard_chantier_jours",)),
    Regle("cash_libre_deficit", "cash", "m8.vue_executive", "resultat.cash_libre", _signal_cash_libre_deficit),
    Regle("cash_libre_non_calculable", "cash", "m8.vue_executive", "resultat.cash_libre", _signal_cash_libre_inconnu),
    Regle("cash_libre_sous_plancher", "cash", "m8.vue_executive", "resultat.cash_libre", _signal_cash_libre_plancher,
          ("cash_libre_plancher_cad",)),
    Regle("filet_sla_violation", "ventes", "m2.sla_filet", f"{_R}.regles[*]", _signal_sla, amont=_amont_sla),
    # Règle transversale : l'âge des lectures que les autres règles consomment (traitée à part dans ``evaluer``).
    Regle("donnees_perimees", "donnees", "*", _R, lambda ligne, ctx: None, ("donnees_perimees_jours",)),
)  # fmt: skip

# Dimensions autorisées par règle : un test impose que chaque risque rendu reste dans le domaine de sa règle.
DOMAINES = {regle.id: regle.domaine for regle in REGLES}


# ---------------------------------------------------------------------------------------------------------- évaluation
def _normaliser_seuils(seuils: Mapping | None) -> dict[str, Decimal]:
    propres: dict[str, Decimal] = {}
    for nom, valeur in (seuils or {}).items():
        reglage = REGLAGES.get(nom)
        lu = _dec(valeur)
        if reglage is None or lu is None or lu <= 0 or (reglage.nature == "entier" and lu != lu.to_integral_value()):
            raise ValueError(f"REJ-RISQUE-SEUIL : réglage {nom!r} inconnu ou valeur invalide")
        propres[nom] = lu
    return propres


def _a_declarer(regle: Regle, seuils: Mapping[str, Decimal]) -> list[str]:
    """Les clés de réglage de direction que la règle exige et que la direction n'a pas (valablement) déclarées."""
    return [REGLAGES[nom].cle for nom in regle.seuils if nom not in seuils]


def _reglages_a_declarer(non_evaluees: list[dict], multiple, refuses: Mapping[str, str]) -> dict:
    """Une fois chacun : ce que la direction doit déclarer (clé -> libellé, unité, refus éventuel), et où."""
    cles = {cle for n in non_evaluees for cle in n.get("a_declarer", ())}
    if multiple is None:
        cles.add(REGLAGES["multiple_seuil_critique"].cle)
    par_cle = {r.cle: r for r in REGLAGES.values()}
    nom_de = {r.cle: r.nom for r in REGLAGES.values()}
    return {
        cle: {
            "libelle": par_cle[cle].libelle,
            "unite": par_cle[cle].unite,
            "ou": DOMAINE_AVIS,
            **({"refus": refuses[nom_de[cle]]} if nom_de[cle] in refuses else {}),
        }
        for cle in sorted(cles)
    }


def _groupe(capture: Mapping) -> str:
    """Les captures d'une même lecture qui ne diffèrent que par l'instant ou le jour de RÉFÉRENCE de la lecture lisent
    la
    même chose à des moments différents : la plus récente fait foi, une plus ancienne dont le signal a disparu est
    LEVÉE.
    Deux périodes ou deux filtres différents (autre mois, autre semaine) restent des lectures distinctes."""
    lecture = cat.PAR_ID.get(capture["lecture_id"])
    arguments = capture.get("arguments")
    if lecture is None or lecture.reference is None or not isinstance(arguments, Mapping):
        return capture["arguments_sha256"]
    return cs.empreinte({cle: valeur for cle, valeur in arguments.items() if cle != lecture.reference})


def _adresse(capture: Mapping, numero_page: int, lignes: str, rang: int, champ: str | None) -> str:
    base = lignes[:-3] + f"[{rang}]" if lignes.endswith("[*]") else lignes
    suffixe = f".{champ}" if champ else ""
    return f"{capture['lecture_id']}#{capture['index']}:p{numero_page}.{base}{suffixe}"


def _signaux(resultat: object) -> list[Signal]:
    if resultat is None:
        return []
    return [resultat] if isinstance(resultat, Signal) else list(resultat)  # type: ignore[arg-type]


def _occurrences(regle: Regle, capture: Mapping, ctx: Contexte) -> dict[str, dict]:
    trouvees: dict[str, dict] = {}
    for numero_page, page in enumerate(capture["pages"]):
        for rang, ligne in enumerate(cs.extraire(page, regle.lignes)):
            if not isinstance(ligne, Mapping):
                continue
            for signal in _signaux(regle.signal(ligne, ctx)):
                trouvees.setdefault(
                    signal.sujet,
                    {
                        "gravite": signal.gravite,
                        "preuves": [_adresse(capture, numero_page, regle.lignes, rang, c) for c in signal.champs],
                        "raison": signal.raison,
                        "mesure": None if signal.mesure is None else dict(signal.mesure),
                        "seuil": None if signal.seuil is None else dict(signal.seuil),
                    },
                )
    return trouvees


def _age_jours(capture: Mapping, connaissance_dt) -> int | None:
    recu = cs.instant(capture["recu_a"])
    return (connaissance_dt - recu).days if recu is not None and connaissance_dt is not None else None


def evaluer(
    captures: Sequence[Mapping],
    *,
    connaissance: str,
    perime_apres_jours: int | None = None,
    seuils: Mapping | None = None,
    seuils_refuses: Mapping[str, str] | None = None,
) -> dict:
    """Le radar à l'instant ``connaissance``.

    ``seuils`` : ``{nom court: valeur}`` des seuils DÉCLARÉS par la direction (``REGLAGES``) ; un nom absent n'est pas
    déclaré. ``seuils_refuses`` : ``{nom: raison}`` des seuils lus mais refusés par leur déclaration (hors bornes,
    mauvais type) : traités comme non déclarés, avec la raison."""
    if perime_apres_jours is not None and (type(perime_apres_jours) is not int or not 0 <= perime_apres_jours <= 3650):
        raise ValueError("REJ-RISQUE-PEREMPTION : entier de 0 à 3650 jours ou absent")
    declares = _normaliser_seuils(seuils)
    refuses = dict(seuils_refuses or {})
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    maintenant = cs.instant(connaissance)
    multiple = declares.get("multiple_seuil_critique")
    # Péremption : l'argument l'emporte ; à défaut, l'âge que la direction a DÉCLARÉ (``donnees_perimees_jours``) ;
    # sinon aucune.
    origine_peremption = "argument" if perime_apres_jours is not None else None
    if perime_apres_jours is None and "donnees_perimees_jours" in declares:
        perime_apres_jours, origine_peremption = int(declares["donnees_perimees_jours"]), "reglage"
    if multiple is not None and multiple < 1:
        raise ValueError("REJ-RISQUE-SEUIL : multiple_seuil_critique doit valoir au moins 1")
    ctx = Contexte({k: v for k, v in declares.items() if k != "multiple_seuil_critique"}, maintenant, multiple)
    risques: list[dict] = []
    non_evaluees: list[dict] = []
    evaluees: list[str] = []

    def non_evaluee(regle: Regle, raison: str, **plus) -> None:
        entree = {"regle": regle.id, "domaine": regle.domaine, "raison": raison, **plus}
        manquants = _a_declarer(regle, ctx.seuils)
        if manquants:
            entree["a_declarer"] = manquants
        if entree not in non_evaluees:
            non_evaluees.append(entree)

    for regle in REGLES:
        if regle.lecture_id == "*":
            continue
        lues = [c for c in connues if c["lecture_id"] == regle.lecture_id]
        if not lues:
            non_evaluee(regle, "ABSENTE")
            continue
        par_arguments: dict[str, list[Mapping]] = {}
        for capture in lues:
            par_arguments.setdefault(_groupe(capture), []).append(capture)
        evaluee = False
        seuil_manquant = bool(_a_declarer(regle, ctx.seuils))
        for groupe in par_arguments.values():
            utilisables = [
                c
                for c in groupe
                if c["verdict"] == "ACCEPTEE"
                and c["complete"]
                and (c["lecture_id"], c["arguments_sha256"]) not in en_conflit
            ]
            derniere = groupe[-1]
            if not utilisables or utilisables[-1] is not derniere:
                if derniere["verdict"] != "ACCEPTEE":
                    raison = "REFUSEE"
                elif (derniere["lecture_id"], derniere["arguments_sha256"]) in en_conflit:
                    raison = "CONTRADICTOIRE"
                else:
                    raison = "PARTIELLE"
                non_evaluee(regle, raison, capture=derniere["index"])
                continue
            courante = utilisables[-1]
            if regle.amont is not None:
                for page in courante["pages"]:
                    for entree in regle.amont(page):
                        if entree not in non_evaluees:
                            non_evaluees.append(entree)
            if seuil_manquant:
                continue
            evaluee = True
            actuels = _occurrences(regle, courante, ctx)
            for sujet, trouve in actuels.items():
                age = _age_jours(courante, maintenant)
                perime = perime_apres_jours is not None and age is not None and age > perime_apres_jours
                risques.append(
                    _risque(regle, sujet, trouve, courante, "A_RECONFIRMER" if perime else "ACTIF", age, [], perime)
                )
            # Versions plus anciennes du même jeu d'arguments : un signal disparu est LEVÉ (faux positif possible).
            deja = set(actuels)
            for ancienne in reversed(utilisables[:-1]):
                for sujet, trouve in _occurrences(regle, ancienne, ctx).items():
                    if sujet in deja:
                        continue
                    deja.add(sujet)
                    contraire = {
                        "capture": courante["index"],
                        "constat": "signal absent de la lecture plus récente",
                        "recu_a": courante["recu_a"],
                    }
                    risques.append(
                        _risque(
                            regle, sujet, trouve, ancienne, "LEVE", _age_jours(ancienne, maintenant), [contraire], False
                        )
                    )
        if evaluee:
            evaluees.append(regle.id)
        elif seuil_manquant and not any(n["regle"] == regle.id for n in non_evaluees):
            non_evaluee(regle, "SEUIL_NON_DECLARE")
        elif not any(n["regle"] == regle.id for n in non_evaluees):  # pragma: no cover - garde
            non_evaluees.append({"regle": regle.id, "domaine": regle.domaine, "raison": "INCONNUE"})
    _donnees_perimees(connues, ctx, refuses, maintenant, risques, non_evaluees, evaluees)
    ordre = {"ACTIF": 0, "A_RECONFIRMER": 1, "LEVE": 2}
    risques.sort(
        key=lambda r: (
            ordre[r["statut"]],
            -GRADES.index(r["gravite"]) if r["gravite"] != "INCONNU" else 1,
            r["risque_id"],
        )
    )
    resultat = {
        "type": "RADAR_RISQUES",
        "version": VERSION,
        "grille": {"statut": GRILLE_STATUT, "grades": list(GRADES)},
        "connaissance": connaissance,
        "perime_apres_jours": perime_apres_jours,
        "perime_origine": origine_peremption,
        "risques": risques,
        "regles_evaluees": sorted(evaluees),
        "regles_non_evaluees": non_evaluees,
        "reglages_a_declarer": _reglages_a_declarer(non_evaluees, multiple, refuses),
        "seuils_declares": {REGLAGES[n].cle: _texte(v) for n, v in sorted(declares.items())},
        "escalade": {
            "multiple_declare": None if multiple is None else _texte(multiple),
            "dit": "Sans le multiple m9.multiple_seuil_critique, aucun dépassement n'est dit critique."
            if multiple is None
            else "Un dépassement est critique au multiple déclaré du seuil.",
        },
        "limites": list(_LIMITES),
    }
    resultat["radar_id"] = hashlib.sha256(
        json.dumps(resultat, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return resultat


def _donnees_perimees(connues, ctx, refuses, maintenant, risques, non_evaluees, evaluees) -> None:
    """Règle transversale : une lecture consommée dont la dernière réponse acceptée est plus vieille que le seuil."""
    regle = next(r for r in REGLES if r.id == "donnees_perimees")
    manquants = _a_declarer(regle, ctx.seuils)
    if manquants:
        non_evaluees.append({"regle": regle.id, "domaine": regle.domaine, "raison": "SEUIL_NON_DECLARE",
                             "a_declarer": manquants})  # fmt: skip
        return
    seuil = ctx.seuil("donnees_perimees_jours")
    evaluees.append(regle.id)
    surveillees = sorted({r.lecture_id for r in REGLES if r.lecture_id != "*"})
    for lecture_id in surveillees:
        acceptees = [c for c in connues if c["lecture_id"] == lecture_id and c["verdict"] == "ACCEPTEE"]
        if not acceptees:
            continue  # lecture jamais obtenue : déjà dite « ABSENTE » par les règles qui la consomment
        derniere = acceptees[-1]
        age = _age_jours(derniere, maintenant)
        if age is None or Decimal(age) <= seuil:
            continue
        trouve = {
            "gravite": "MOYEN",
            "preuves": [f"{derniere['lecture_id']}#{derniere['index']}:recu_a"],
            "raison": "la dernière réponse acceptée de cette lecture est plus ancienne que l'âge déclaré",
            "mesure": {"valeur": str(age), "unite": "jours"},
            "seuil": ctx.bloc_seuil("donnees_perimees_jours", critique=False),
        }
        risques.append(_risque(regle, f"lecture:{lecture_id}", trouve, derniere, "ACTIF", age, [], False))


def _risque(regle, sujet, trouve, capture, statut, age, contraires, perime) -> dict:
    identifiant = hashlib.sha256(f"{regle.id}|{sujet}|{capture['hash_maillon']}".encode()).hexdigest()[:20]
    manquants = ["source plus ancienne que la péremption demandée : à reconfirmer"] if perime else []
    return {
        "risque_id": identifiant,
        "regle": regle.id,
        "domaine": regle.domaine,
        "sujet": sujet,
        "gravite": trouve["gravite"],
        "statut": statut,
        "raison": trouve["raison"],
        "mesure": trouve["mesure"],
        "seuil": trouve["seuil"],
        "source": {
            "lecture_id": capture["lecture_id"],
            "capture": capture["index"],
            "hash": capture["hash_maillon"],
            "recu_a": capture["recu_a"],
            "age_jours": age,
        },
        "preuves": trouve["preuves"],
        "elements_contraires": contraires,
        "donnees_manquantes": manquants,
        "origine_etablie": False,
        "explication": EXPLICATION,
    }


def delta(
    captures: Sequence[Mapping],
    *,
    connaissance: str,
    jours: int = 1,
    perime_apres_jours: int | None = None,
    seuils: Mapping | None = None,
    seuils_refuses: Mapping[str, str] | None = None,
) -> dict:
    """Ce qui a changé entre ``connaissance`` moins ``jours`` jours et ``connaissance`` : apparus, levés, restés.

    Les deux radars sont calculés sur ce que M9 connaissait à chaque instant (``cs.connues_a``) : une capture reçue
    après l'instant précédent n'y figure pas. Un risque absent hier et présent aujourd'hui est APPARU ; présent hier,
    absent ou LEVÉ aujourd'hui, il est LEVÉ ; un changement de gravité est nommé. Rien n'est expliqué : le radar ne dit
    jamais pourquoi."""
    if type(jours) is not int or not 1 <= jours <= 31:
        raise ValueError("REJ-RISQUE-DELTA : nombre de jours entier de 1 à 31 requis")
    maintenant = cs.instant(connaissance)
    if maintenant is None:
        raise ValueError("REJ-RISQUE-DELTA : instant avec fuseau explicite requis")
    avant = (maintenant - timedelta(days=jours)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    radar_avant = evaluer(
        captures,
        connaissance=avant,
        perime_apres_jours=perime_apres_jours,
        seuils=seuils,
        seuils_refuses=seuils_refuses,
    )
    radar_apres = evaluer(
        captures,
        connaissance=connaissance,
        perime_apres_jours=perime_apres_jours,
        seuils=seuils,
        seuils_refuses=seuils_refuses,
    )

    ordre = {"INCONNU": -1, "FAIBLE": 0, "MOYEN": 1, "ELEVE": 2, "CRITIQUE": 3}

    def presents(radar: Mapping) -> dict[tuple[str, str], Mapping]:
        """Un sujet cité par deux lectures aux arguments différents garde sa gravité la plus haute."""
        retenus: dict[tuple[str, str], Mapping] = {}
        for r in radar["risques"]:
            cle = (r["regle"], r["sujet"])
            if r["statut"] != "LEVE" and (cle not in retenus or ordre[r["gravite"]] > ordre[retenus[cle]["gravite"]]):
                retenus[cle] = r
        return retenus

    hier, aujourd_hui = presents(radar_avant), presents(radar_apres)
    leves_par_le_radar = {(r["regle"], r["sujet"]) for r in radar_apres["risques"] if r["statut"] == "LEVE"}

    def ligne(r: Mapping) -> dict:
        return {"regle": r["regle"], "sujet": r["sujet"], "domaine": r["domaine"], "gravite": r["gravite"]}

    apparus = [ligne(aujourd_hui[k]) for k in sorted(aujourd_hui.keys() - hier.keys())]
    leves = [ligne(hier[k]) for k in sorted(hier.keys() - aujourd_hui.keys())]
    change = [
        {**ligne(aujourd_hui[k]), "gravite_precedente": hier[k]["gravite"]}
        for k in sorted(hier.keys() & aujourd_hui.keys())
        if hier[k]["gravite"] != aujourd_hui[k]["gravite"]
    ]
    resultat = {
        "type": "DELTA_RISQUES",
        "version": VERSION,
        "connaissance": connaissance,
        "connaissance_precedente": avant,
        "apparus": apparus,
        "leves": leves,
        "gravite_changee": change,
        "inchanges": len(hier.keys() & aujourd_hui.keys()) - len(change),
        "leves_par_le_radar": len(leves_par_le_radar),
        "regles_non_evaluees_precedent": len(radar_avant["regles_non_evaluees"]),
        "regles_non_evaluees": len(radar_apres["regles_non_evaluees"]),
        "limites": [
            "Comparaison de deux états connus de M9, pas de deux états du monde : une règle non évaluée d'un côté peut "
            "faire apparaître ou disparaître un risque sans que rien n'ait changé chez le propriétaire.",
            "Le radar ne dit jamais pourquoi un risque est apparu ou levé.",
        ],
    }
    return resultat


__all__ = ["DOMAINES", "GRADES", "REGLAGES", "REGLES", "Contexte", "Regle", "Reglage", "Signal", "delta", "evaluer"]
