"""Postes employeur 2026 absents de la chaîne RRQ → QC → RQAP/AE → fédéral : RRQ employeur, FSS, CNESST, normes, FDRCMO.

Module pur, Decimal seulement, contexte isolé. Chaque règle porte sa source (autorité, document, millésime,
partie/page, date de lecture) dans un instantané haché ; aucune valeur n'est reconduite d'une autre année :
une date de paie hors 2026 rend le poste inconnu. Aucun taux employeur par défaut :
- FSS : secteur, base d'estimation et masse salariale déclarés par l'humain (avec référence) ;
- CNESST : taux de versement de la Décision de classification, déclaré avec référence ;
- normes du travail : assujettissement déclaré ;
- FDRCMO : masse salariale déclarée ; au-delà du seuil, la cotisation dépend de dépenses annuelles → inconnue.

Lecture des sources : texte extrait des PDF/pages officiels le 2026-10-28 par un service de lecture tiers ; les octets
des PDF n'ont PAS été re-hachés ici (réseau du bac à sable bloqué vers revenuquebec.ca / canada.ca / cnesst.gouv.qc.ca).
Les postes sont donc `CALCULE` sous un statut de source `TEXTE_OFFICIEL_LU_SANS_CAPTURE_BINAIRE` et jamais qualifiés.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Any

CENT = Decimal("0.01")
_MONTANT = re.compile(r"^(?:0|[1-9][0-9]{0,11})\.[0-9]{2}$")
_TAUX = re.compile(r"^(?:0|[1-9][0-9]?)\.[0-9]{2,4}$")
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SECTEURS_FSS = ("AUTRES", "PRIMAIRE_MANUFACTURIER", "SECTEUR_PUBLIC")
_BASES_FSS = ("ANNEE_PRECEDENTE", "CUMUL_NOUVEL_EMPLOYEUR")
_BASES_CNESST = ("ANNUELLE", "HEBDOMADAIRE")

STATUT_SOURCE = "TEXTE_OFFICIEL_LU_SANS_CAPTURE_BINAIRE"
_LECTURE = "firecrawl_pdf_texte_2026-10-28"

PARAMETRES: dict[str, Any] = {
    "schema": "m5-cotisations-employeur-preparatoires/1",
    "annee": 2026,
    "date_debut_inclusive": "2026-01-01",
    "date_fin_inclusive": "2026-12-31",
    "statut_source": STATUT_SOURCE,
    "arrondi_periode": (
        "centime, troisième décimale >= 5 vers le haut (FSS, TP-1015.F partie 5); "
        "même convention appliquée aux autres postes"
    ),
    "rrq_employeur": {"regle": "égale à la cotisation retenue sur l'employé (paliers 1 et 2)"},
    "fss": {
        "formule": "D2 = W × S2, arrondi au cent; W en % selon masse salariale totale et secteur",
        "autres": {
            "base": "1.2662",
            "pente": "0.3838",
            "s_min": "1",
            "s_max": "7.8",
            "forme": "W = 1.2662 + 0.3838 × S",
        },
        "primaire_manufacturier": {
            "base": "0.8074",
            "pente": "0.4426",
            "s_min": "1",
            "s_max": "7.8",
            "forme": "W = 0.8074 + 0.4426 × S",
        },
        "secteur_public_pct": "4.26",
        "s_unite_masse": "1000000",
        "estimation_periodique": {
            "ANNEE_PRECEDENTE": "taux de la masse salariale totale de l'année précédente (employeur établi)",
            "CUMUL_NOUVEL_EMPLOYEUR": (
                "taux de la masse salariale cumulée du début de l'année à la fin de la période (deux premières années)"
            ),
        },
    },
    "cnesst": {
        "salaire_maximum_annuel_assurable": "103000.00",
        "formule": "versement = (salaire assurable de la période − excédent du maximum) × taux de versement / 100",
        "taux": "Décision de classification de l'employeur; aucun taux par défaut",
        "base_excedent_supportee": "ANNUELLE",
    },
    "normes_travail": {
        "taux_pct": "0.06",
        "maximum_remuneration_assujettie": "103000.00",
        "paiement": "annuel, sommaire 1, fin février N+1",
    },
    "fdrcmo": {
        "seuil_masse_salariale": "2000000.00",
        "operateur": "strictement supérieur",
        "taux_pct": "1",
        "paiement": "annuel, sommaire 1",
    },
    "sources": [
        {
            "id": "rq_tp1015f_rrq_employeur",
            "autorite": "Revenu Québec",
            "document": "TP-1015.F",
            "edition": "2026-01",
            "sections": "Principaux changements p. 7; partie 3.2 « Cotisations de l'employeur » p. 40",
            "citation": (
                "Il n'y a pas de formule pour calculer les cotisations de l'employeur au RRQ. "
                "Celles-ci sont égales au total des sommes retenues"
            ),
            "lecture": _LECTURE,
        },
        {
            "id": "rq_tp1015f_fss",
            "autorite": "Revenu Québec",
            "document": "TP-1015.F",
            "edition": "2026-01",
            "sections": (
                "tableau p. 8; partie 5 « Formule pour le calcul de la cotisation au FSS » pp. 43-45 "
                "(pagination selon la table des matières)"
            ),
            "citation": "D2 = W × S2 › Le résultat doit être arrondi à la deuxième décimale",
            "lecture": _LECTURE,
        },
        {
            "id": "rq_tp1015g_fss",
            "autorite": "Revenu Québec",
            "document": "TP-1015.G",
            "edition": "2026-01",
            "sections": "partie 6 pp. 67-70",
            "citation": "taux FSS selon masse salariale totale et secteur",
            "lecture": _LECTURE,
        },
        {
            "id": "rq_tp1015g_normes",
            "autorite": "Revenu Québec",
            "document": "TP-1015.G",
            "edition": "2026-01",
            "sections": "partie 7 p. 74",
            "citation": "0,06 % du total des rémunérations assujetties; maximum 103 000 $ pour 2026",
            "lecture": _LECTURE,
        },
        {
            "id": "rq_tp1015g_fdrcmo",
            "autorite": "Revenu Québec",
            "document": "TP-1015.G",
            "edition": "2026-01",
            "sections": "partie 8 p. 75",
            "citation": "Si votre masse salariale de l'année dépasse 2 millions de dollars, vous devez participer",
            "lecture": _LECTURE,
        },
        {
            "id": "cnesst_guide_versement_2026",
            "autorite": "CNESST",
            "document": "Guide : Calcul du versement périodique",
            "edition": "2026",
            "sections": "sections 2, 2.1, 2.2",
            "citation": "multipliez la somme des salaires assurables versés par le taux de versement périodique",
            "lecture": _LECTURE,
        },
        {
            "id": "cnesst_salaire_max_2026",
            "autorite": "CNESST",
            "document": "Salaire maximum annuel assurable",
            "edition": "ligne 2026",
            "sections": "tableau",
            "citation": "Salaire maximum annuel assurable en 2026 : 103 000 $",
            "lecture": _LECTURE,
        },
    ],
    "limites": [
        "texte officiel lu sans re-hachage des octets des PDF (réseau bloqué) : statut de source non qualifié",
        "classement SCIAN de la rénovation dans « autres secteurs » = déclaration humaine, jamais inférée",
        "CNESST : base hebdomadaire de l'excédent (construction) non transcrite; taux employeur jamais défaut",
        "FDRCMO au-delà du seuil : dépend de dépenses de formation admissibles annuelles, non calculable par période",
        "définitions de « masse salariale » du sommaire 1 (RLZ-1.S.G) non lues",
        "CCQ : effets sur normes du travail et FDRCMO non lus; régime CCQ déclaré = hors couverture",
    ],
}
HASH_PARAMETRES = hashlib.sha256(
    json.dumps(PARAMETRES, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def _refus(code: str, detail: str) -> dict[str, str]:
    return {"code": f"REJ-DOSSIER-PAIE-{code}", "detail": detail}


def _ctx() -> Context:
    contexte = Context(prec=50, rounding=ROUND_HALF_UP, Emin=-999999, Emax=999999, clamp=0)
    for signal in contexte.traps:
        contexte.traps[signal] = False
    return contexte


def _fmt(montant: Decimal) -> str:
    return format(montant.quantize(CENT, rounding=ROUND_HALF_UP, context=_ctx()), "f")


def _reference_ok(valeur: object) -> bool:
    return isinstance(valeur, str) and _REFERENCE.fullmatch(valeur) is not None


def _montant_ok(valeur: object) -> bool:
    return isinstance(valeur, str) and _MONTANT.fullmatch(valeur) is not None


def valider_parametres_employeur(params: object) -> tuple[bool, dict[str, str] | None]:
    """Structure fermée; chaque bloc est `null` (inconnu) ou complet avec référence. Aucune valeur par défaut."""
    cles = {"fss", "cnesst", "normes_travail", "fdrcmo"}
    if not isinstance(params, Mapping) or set(params) != cles:
        return False, _refus(
            "STRUCTURE-INVALIDE", "parametres_employeur : fss, cnesst, normes_travail, fdrcmo (null si inconnu)"
        )
    fss = params["fss"]
    if fss is not None and not (
        isinstance(fss, Mapping)
        and set(fss) == {"secteur", "masse_salariale_estimative_cad", "base_estimation", "reference"}
        and fss["secteur"] in _SECTEURS_FSS
        and _montant_ok(fss["masse_salariale_estimative_cad"])
        and fss["base_estimation"] in _BASES_FSS
        and _reference_ok(fss["reference"])
    ):
        return False, _refus("STRUCTURE-INVALIDE", "parametres_employeur.fss invalide")
    cnesst = params["cnesst"]
    if cnesst is not None and not (
        isinstance(cnesst, Mapping)
        and set(cnesst) == {"taux_versement_pour_100", "base_excedent", "reference"}
        and isinstance(cnesst["taux_versement_pour_100"], str)
        and _TAUX.fullmatch(cnesst["taux_versement_pour_100"])
        and cnesst["base_excedent"] in _BASES_CNESST
        and _reference_ok(cnesst["reference"])
    ):
        return False, _refus("STRUCTURE-INVALIDE", "parametres_employeur.cnesst invalide")
    normes = params["normes_travail"]
    if normes is not None and not (
        isinstance(normes, Mapping)
        and set(normes) == {"assujetti", "reference"}
        and type(normes["assujetti"]) is bool
        and _reference_ok(normes["reference"])
    ):
        return False, _refus("STRUCTURE-INVALIDE", "parametres_employeur.normes_travail invalide")
    fdrcmo = params["fdrcmo"]
    if fdrcmo is not None and not (
        isinstance(fdrcmo, Mapping)
        and set(fdrcmo) == {"masse_salariale_annee_cad", "reference"}
        and _montant_ok(fdrcmo["masse_salariale_annee_cad"])
        and _reference_ok(fdrcmo["reference"])
    ):
        return False, _refus("STRUCTURE-INVALIDE", "parametres_employeur.fdrcmo invalide")
    return True, None


def poste(
    identifiant: str,
    libelle: str,
    porteur: str,
    autorite: str,
    etat: str,
    montant: str | None,
    *,
    moteur: str,
    manque: list[str] | None = None,
    source: dict[str, Any] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Un poste de la matrice : `montant` n'existe que pour CALCULE/DECLARE (jamais un zéro implicite)."""
    return {
        "id": identifiant,
        "libelle": libelle,
        "porteur": porteur,
        "autorite": autorite,
        "etat": etat,
        "montant": montant if etat in {"CALCULE", "DECLARE"} else None,
        "moteur": moteur,
        "manque": manque or [],
        "source": source,
        "note": note,
    }


def taux_fss_pct(secteur: str, masse: Decimal) -> Decimal:
    """W (en %) selon la masse salariale totale et le secteur; exact, sans arrondi intermédiaire."""
    with localcontext(_ctx()):
        if secteur == "SECTEUR_PUBLIC":
            return Decimal(PARAMETRES["fss"]["secteur_public_pct"])
        bloc = PARAMETRES["fss"]["autres" if secteur == "AUTRES" else "primaire_manufacturier"]
        unite = Decimal(PARAMETRES["fss"]["s_unite_masse"])
        s_min, s_max = Decimal(bloc["s_min"]), Decimal(bloc["s_max"])
        if masse <= s_min * unite:
            s = s_min
        elif masse >= s_max * unite:
            s = s_max
        else:
            s = masse / unite
        return Decimal(bloc["base"]) + Decimal(bloc["pente"]) * s


def evaluer_postes_employeur(
    *,
    rrq_employe: str | None,
    rqap_employeur: str | None,
    ae_employeur: str | None,
    brut_cad: str | None,
    cumuls_avant: Mapping[str, str],
    parametres_employeur: Mapping[str, Any] | None,
    date_paie: str,
    composition_disponible: bool,
    raison_blocage: str,
) -> list[dict[str, Any]]:
    """Postes employeur de la période. Sans composition des moteurs publics, tout reste inconnu et dit pourquoi."""
    dans_2026 = PARAMETRES["date_debut_inclusive"] <= date_paie <= PARAMETRES["date_fin_inclusive"]
    bloque_global = (not composition_disponible) or brut_cad is None
    manque_global = (
        [raison_blocage]
        if bloque_global
        else ([] if dans_2026 else ["date de paie hors millésime 2026 : aucune reconduction"])
    )

    def inconnu(identifiant: str, libelle: str, autorite: str, manque: list[str], moteur: str) -> dict[str, Any]:
        return poste(identifiant, libelle, "employeur", autorite, "INCONNU", None, moteur=moteur, manque=manque)

    postes: list[dict[str, Any]] = []
    # RRQ employeur : égale à la retenue sur l'employé.
    if bloque_global or not dans_2026 or rrq_employe is None:
        postes.append(
            inconnu(
                "rrq_employeur",
                "RRQ — cotisation de l'employeur",
                "Revenu Québec",
                manque_global or ["RRQ employé non calculé"],
                "cotisations_employeur_2026",
            )
        )
    else:
        postes.append(
            poste(
                "rrq_employeur",
                "RRQ — cotisation de l'employeur (égale à celle de l'employé)",
                "employeur",
                "Revenu Québec",
                "CALCULE",
                rrq_employe,
                moteur="cotisations_employeur_2026",
                source={
                    "id": "rq_tp1015f_rrq_employeur",
                    "edition": "TP-1015.F 2026-01",
                    "sections": "p. 7; partie 3.2 p. 40",
                },
            )
        )
    for ident, lib, autorite, montant, ed, sec in (
        (
            "rqap_employeur",
            "RQAP — cotisation de l'employeur",
            "Revenu Québec",
            rqap_employeur,
            "TP-1015.F 2026-01",
            "pages 41-42",
        ),
        (
            "ae_employeur",
            "Assurance-emploi — prime de l'employeur (1,4 × taux employé, taux QC)",
            "Agence du revenu du Canada",
            ae_employeur,
            "T4127 122e/123e",
            "chapitre 7",
        ),
    ):
        if montant is None or bloque_global or not dans_2026:
            postes.append(
                inconnu(
                    ident, lib, autorite, manque_global or ["moteur RQAP/AE non calculé"], "cotisations_rqap_ae_2026"
                )
            )
        else:
            postes.append(
                poste(
                    ident,
                    lib,
                    "employeur",
                    autorite,
                    "CALCULE",
                    montant,
                    moteur="cotisations_rqap_ae_2026",
                    source={"edition": ed, "sections": sec},
                )
            )
    params = parametres_employeur or {}
    brut = Decimal(brut_cad) if brut_cad is not None else None

    # FSS
    fss = params.get("fss")
    if bloque_global or not dans_2026 or fss is None:
        manque = manque_global or ["secteur, masse salariale et base d'estimation FSS non déclarés"]
        postes.append(
            inconnu(
                "fss",
                "FSS — cotisation de l'employeur au Fonds des services de santé",
                "Revenu Québec",
                manque,
                "cotisations_employeur_2026",
            )
        )
    else:
        assert brut is not None
        with localcontext(_ctx()):
            w = taux_fss_pct(fss["secteur"], Decimal(fss["masse_salariale_estimative_cad"]))
            cotisation = brut * w / Decimal(100)
        postes.append(
            poste(
                "fss",
                "FSS — cotisation de l'employeur au Fonds des services de santé",
                "employeur",
                "Revenu Québec",
                "CALCULE",
                _fmt(cotisation),
                moteur="cotisations_employeur_2026",
                source={
                    "id": "rq_tp1015f_fss",
                    "edition": "TP-1015.F 2026-01",
                    "sections": "partie 5 pp. 43-45",
                    "secteur_declare": fss["secteur"],
                    "base_estimation": fss["base_estimation"],
                    "reference_declaration": fss["reference"],
                    "taux_pct": format(w, "f"),
                },
                note="Taux estimatif de paiement périodique; le taux réel de l'année est fixé au sommaire 1.",
            )
        )
    # CNESST
    cnesst = params.get("cnesst")
    if bloque_global or not dans_2026 or cnesst is None or cnesst["base_excedent"] != "ANNUELLE":
        if bloque_global or not dans_2026:
            manque = manque_global
        elif cnesst is None:
            manque = ["taux de versement de la Décision de classification CNESST non déclaré (aucun taux par défaut)"]
        else:
            manque = ["base hebdomadaire de l'excédent CNESST non transcrite"]
        postes.append(
            inconnu("cnesst", "CNESST — versement périodique estimé", "CNESST", manque, "cotisations_employeur_2026")
        )
    else:
        assert brut is not None
        with localcontext(_ctx()):
            maximum = Decimal(PARAMETRES["cnesst"]["salaire_maximum_annuel_assurable"])
            reste = max(Decimal(0), maximum - Decimal(cumuls_avant["salaire_rrq_cumul_avant"]))
            assurable = min(brut, reste)
            versement = assurable * Decimal(cnesst["taux_versement_pour_100"]) / Decimal(100)
        postes.append(
            poste(
                "cnesst",
                "CNESST — versement périodique estimé",
                "employeur",
                "CNESST",
                "CALCULE",
                _fmt(versement),
                moteur="cotisations_employeur_2026",
                source={
                    "id": "cnesst_guide_versement_2026",
                    "edition": "Guide 2026",
                    "sections": "2, 2.1, 2.2",
                    "reference_declaration": cnesst["reference"],
                    "salaire_assurable_periode": _fmt(assurable),
                    "taux_pour_100": cnesst["taux_versement_pour_100"],
                },
                note="Estimation de versement périodique; la cotisation définitive est établie par la CNESST.",
            )
        )
    # Normes du travail
    normes = params.get("normes_travail")
    if bloque_global or not dans_2026 or normes is None:
        manque = manque_global or ["assujettissement à la cotisation des normes du travail non déclaré"]
        postes.append(
            inconnu(
                "normes_travail",
                "Normes du travail — cotisation de l'employeur (annuelle)",
                "Revenu Québec",
                manque,
                "cotisations_employeur_2026",
            )
        )
    elif normes["assujetti"] is False:
        postes.append(
            poste(
                "normes_travail",
                "Normes du travail — cotisation de l'employeur (annuelle)",
                "employeur",
                "Revenu Québec",
                "NON_APPLICABLE",
                None,
                moteur="cotisations_employeur_2026",
                source={"reference_declaration": normes["reference"]},
                note="Non-assujettissement déclaré par l'humain avec pièce; non vérifié.",
            )
        )
    else:
        assert brut is not None
        with localcontext(_ctx()):
            maximum = Decimal(PARAMETRES["normes_travail"]["maximum_remuneration_assujettie"])
            reste = max(Decimal(0), maximum - Decimal(cumuls_avant["salaire_rrq_cumul_avant"]))
            cotisation = min(brut, reste) * Decimal(PARAMETRES["normes_travail"]["taux_pct"]) / Decimal(100)
        postes.append(
            poste(
                "normes_travail",
                "Normes du travail — cotisation de l'employeur (provision par période; paiement annuel)",
                "employeur",
                "Revenu Québec",
                "CALCULE",
                _fmt(cotisation),
                moteur="cotisations_employeur_2026",
                source={
                    "id": "rq_tp1015g_normes",
                    "edition": "TP-1015.G 2026-01",
                    "sections": "partie 7 p. 74",
                    "reference_declaration": normes["reference"],
                },
            )
        )
    # FDRCMO
    fdrcmo = params.get("fdrcmo")
    if bloque_global or not dans_2026 or fdrcmo is None:
        manque = manque_global or ["masse salariale de l'année pour le seuil FDRCMO non déclarée"]
        postes.append(
            inconnu(
                "fdrcmo",
                "FDRCMO — cotisation de formation (annuelle)",
                "Revenu Québec",
                manque,
                "cotisations_employeur_2026",
            )
        )
    else:
        seuil = Decimal(PARAMETRES["fdrcmo"]["seuil_masse_salariale"])
        if Decimal(fdrcmo["masse_salariale_annee_cad"]) > seuil:
            postes.append(
                inconnu(
                    "fdrcmo",
                    "FDRCMO — cotisation de formation (annuelle)",
                    "Revenu Québec",
                    [
                        "masse salariale > 2 M$ : cotisation = 1 % − dépenses de formation "
                        "admissibles annuelles, non déclarées"
                    ],
                    "cotisations_employeur_2026",
                )
            )
        else:
            postes.append(
                poste(
                    "fdrcmo",
                    "FDRCMO — cotisation de formation (annuelle)",
                    "employeur",
                    "Revenu Québec",
                    "NON_APPLICABLE",
                    None,
                    moteur="cotisations_employeur_2026",
                    source={
                        "id": "rq_tp1015g_fdrcmo",
                        "edition": "TP-1015.G 2026-01",
                        "sections": "partie 8 p. 75",
                        "reference_declaration": fdrcmo["reference"],
                    },
                    note="Masse salariale déclarée ≤ 2 M$; la masse réelle de l'année peut changer l'obligation.",
                )
            )
    return postes
