"""Outils M5 des RAPPORTS financiers, du BUDGET déclaré et du PRÉ-AUDIT (M5-RAPPORTS-1, M5-PRE-AUDIT).

Adaptateur (comme `outils_facturation.py`) : il lit les aides d'`outils.py` (registres, plan comptable, taux, manifeste)
et délègue tout calcul à `rapports_financiers.py`, `budgets.py` et `controleur_preaudit.py`, qui sont purs. Il ne nomme
jamais le registre des mouvements : produire un rapport ne fait bouger aucun argent
(`conformite.verifier_aucun_decaissement`, strict).

Qui décide quoi.

* LIRE (états des résultats, bilan, budget contre réel, rentabilité par axe, rapport de direction, contrôle de
  pré-audit,
  vérification d'un reçu) : T0, lecture pure, aucune écriture, tous en BROUILLON.
* DÉCLARER un budget (`m5_etablir_budget`) engage la direction : N3, une PERSONNE identifiée par le socle (propriétaire
  ou finance), jamais un argument ni un agent seul. Les montants sont ceux qu'elle déclare ; rien n'est supposé.
* CONSTATER le pré-audit (`m5_constater_preaudit`) publie au bus les seuls COMPTES de constats (`m5.preaudit_constate`,
  pour M8) : T1 / N2, sans droit d'appareil, déclenché par le planificateur durable (`constats_planifies`, inactif par
  défaut). Aucune action proposée par le contrôleur n'est exécutée : chacune passe par un outil du sas.

Aucune clôture de période, aucune écriture au grand livre, aucun envoi, aucun paiement. Portée d'appareil FERMÉE pour
tous (`roles_appareil` vide), refusée dans le code. Toute sortie porte la mention d'analyse ET la mention comptable
(« À valider auprès d'un comptable (CPA) / professionnel qualifié »), et les rapports la mention de brouillon.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from opsys import evenements, stockage
from opsys.outils import Autonomie, Niveau, Outil
from opsys.reglages import lecture as reglages_lecture

from . import (
    budgets,
    comptes_a_payer,
    constat_preaudit,
    controleur_preaudit,
    encodage,
    facturation,
    facturation_jalons,
    grand_livre,
    operations_registre,
    plan_comptable,
    rapports_financiers,
    recu_calcul,
    verdicts_rapports,
    wct_recus,
)
from . import outils as _o
from .outils_facturation import _copie, _ecrire
from .outils_operations import _HORODATAGE, _appareil_refuse, accepte, humain_requis, refuse

__all__ = ["outils_rapports"]

TYPE_EVENEMENT_PREAUDIT = "m5.preaudit_constate"
_NOM_REGISTRE_BUDGETS = "budgets_declares"
_LIMITE_DEFAUT, _LIMITE_MAX = 12, 40
_DATE = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "description": "Date AAAA-MM-JJ."}
_MOIS = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$", "description": "Mois AAAA-MM."}
_PAGINATION = {
    "depart": {"type": ["integer", "null"], "minimum": 0},
    "limite": {"type": ["integer", "null"], "minimum": 1, "maximum": _LIMITE_MAX},
}
_NOTE_ENTREES_OMISES = (
    "le reçu est compact (sans `entrees`, trop volumineuses pour une réponse) : son empreinte reste vérifiable "
    "(m5_rejouer_rapport_financier) ; pour le rejouer, rappeler l'outil sur les mêmes registres"
)
_FUSEAU = ZoneInfo("America/Montreal")


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_rapports.construire_verdict(code, detail=detail)


# ====================================================================================================== contextes
def _page(depart: Any, limite: Any) -> tuple[tuple[int, int] | None, dict[str, str] | None]:
    depart = 0 if depart is None else depart
    limite = _LIMITE_DEFAUT if limite is None else limite
    if type(depart) is not int or type(limite) is not int or depart < 0 or not 1 <= limite <= _LIMITE_MAX:
        return None, _verdict(
            "REJ-RAPPORT-LIMITE-INVALIDE", f"depart entier positif ou nul, limite de 1 à {_LIMITE_MAX}"
        )
    return (depart, limite), None


_TEXTE_SUR = re.compile(r"[^A-Za-z0-9_.:~/-]")


def _sur(valeur: Any, longueur: int = 60) -> str:
    """Un texte saisi par une personne (numéro de facture d'un fournisseur, référence de pièce) réduit à des caractères
    d'identifiant : une consigne glissée dans un numéro de facture ne traverse jamais vers le modèle qui lit un
    constat."""
    return _TEXTE_SUR.sub("?", str(valeur))[:longueur]


def _une_ligne(valeur: Any, longueur: int = 200) -> str:
    """Un texte produit par le code à partir d'un registre (détail d'une chaîne altérée, anomalie) sur une ligne, sans
    caractère de contrôle, borné : un registre retouché ne peut pas y loger un long texte."""
    return "".join(c if c.isprintable() else " " for c in " ".join(str(valeur).split()))[:longueur]


def _source(nom: str, registre: Any) -> dict[str, Any]:
    """Un registre lu, tel qu'un rapport le cite : son nom, sa taille et la tête de sa chaîne (un registre sans chaîne,
    comme celui des rentabilités tracées, cite l'empreinte de son dernier maillon)."""
    taille = registre.taille() if hasattr(registre, "taille") else len(registre)
    if hasattr(registre, "tete"):
        tete = registre.tete()
    else:
        maillons = list(registre)
        tete = maillons[-1].get("ligne_id") or encodage.empreinte(maillons[-1]) if maillons else None
    return {"registre": nom, "taille": taille, "tete": tete}


def _contexte() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Grand livre (état, plan) d'un rapport, ou le refus nommé : appareil, stockage non durable, plan illisible, chaîne
    altérée. Jamais un chiffre tiré d'une chaîne qui ne se rejoue pas."""
    refus = _appareil_refuse()
    if refus is not None:
        return None, refus
    ctx, refus = _o._contexte_grand_livre()
    if refus is not None:
        return None, refus
    registre_gl, plan = ctx
    return {
        "etat": grand_livre.etat_grand_livre(registre_gl.lire()),
        "plan": plan,
        "sources": [_source("grand_livre", registre_gl)],
    }, None


def _jour_ou_refus(valeur: Any) -> tuple[date | None, dict[str, str] | None]:
    if isinstance(valeur, str) and len(valeur) == 10 and valeur.isascii():
        try:
            return date.fromisoformat(valeur), None
        except ValueError:
            pass
    return None, _verdict("REJ-RAPPORT-DATE-INVALIDE", f"{valeur!r} : AAAA-MM-JJ exigé")


def _config_rapports() -> Mapping[str, Any]:
    bloc = _o._configuration_manifeste().get("rapports")
    return bloc if isinstance(bloc, Mapping) else {}


def _couts_directs(plan: Mapping[str, Any]) -> tuple[list[str] | None, dict[str, str] | None]:
    """Les comptes de charges que le propriétaire range dans les COÛTS DIRECTS (`configuration.rapports.
    comptes_couts_directs`), ou `None` (non déclarés : la marge brute est « non calculable »). Mal formés ou hors plan :
    un refus qui le dit, jamais une liste devinée."""
    brut = _config_rapports().get("comptes_couts_directs")
    if brut is None:
        return None, None
    if (
        not isinstance(brut, list)
        or not brut
        or not all(isinstance(c, str) for c in brut)
        or len(set(brut)) != len(brut)
    ):
        return None, _verdict(
            "REJ-RAPPORT-COUTS-DIRECTS-INVALIDES",
            "configuration.rapports.comptes_couts_directs : une liste de numéros de compte, sans doublon",
        )
    for compte in brut:
        fiche = plan["comptes"].get(compte)
        if fiche is None or fiche["type"] != "charges":
            return None, _verdict(
                "REJ-RAPPORT-COUTS-DIRECTS-INVALIDES", f"compte {compte!r} absent du plan ou ne portant pas des charges"
            )
    return sorted(brut), None


def _sortie(
    rapport: Mapping[str, Any],
    recu: Mapping[str, Any],
    cle_liste: str | None,
    depart: int,
    limite: int,
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Le rapport (liste paginée), son reçu et les mentions, sous la limite de sortie du socle : jamais tronqué. Un
    reçu trop
    gros perd ses `entrees` (même empreinte, vérifiable), puis la page rétrécit."""
    liste = list(rapport[cle_liste]) if cle_liste else []
    n = limite
    while True:
        corps = {cle: valeur for cle, valeur in rapport.items() if cle != cle_liste}
        if cle_liste:
            tranche = liste[depart : depart + n]
            corps[cle_liste] = tranche
            corps[cle_liste + "_total"] = len(liste)
            corps["prochain_depart"] = depart + n if depart + n < len(liste) else None
        corps.update(extras or {})
        for recu_sortie, note in ((recu, None), (recu_calcul.compacter(recu), _NOTE_ENTREES_OMISES)):
            reponse = accepte({**corps, "recu": recu_sortie, **({"entrees_omises": note} if note else {})})
            if reponse["accepte"]:
                return reponse
        if n <= 1:
            return refuse(
                _verdict("REJ-RAPPORT-LIMITE-INVALIDE", "la réponse dépasse le budget de sortie même à une ligne")
            )
        n = max(1, n // 2)


# ==================================================================================== états des résultats et bilan
def _construire_resultats(
    ctx: Mapping[str, Any], debut: date, fin: date
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    mouvements, refus = rapports_financiers.extraire_mouvements(ctx["etat"], ctx["plan"], debut, fin)
    if refus is not None:
        return None, refus
    couts, refus = _couts_directs(ctx["plan"])
    if refus is not None:
        return None, refus
    entrees = {
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "comptes": mouvements["comptes"],
        "couts_directs": couts,
        "ecritures_definitives": mouvements["ecritures_definitives"],
        "brouillons": mouvements["brouillons"],
        "periode_close": mouvements["periode_close"],
        "plan_comptable_version": mouvements["plan_comptable_version"],
        "sources": ctx["sources"],
    }
    return rapports_financiers.calculer_etat_des_resultats(
        entrees, {"debut": entrees["debut"], "fin": entrees["fin"]}
    ), None


def etat_des_resultats(debut: str, fin: str, depart: int | None = None, limite: int | None = None) -> dict[str, Any]:
    page, refus = _page(depart, limite)
    if refus is not None:
        return refuse(refus)
    ctx, refus = _contexte()
    if refus is not None:
        return refuse(refus)
    periode, refus = rapports_financiers.periode_en_dates(debut, fin)
    if refus is not None:
        return refuse(refus)
    resultat, refus = _construire_resultats(ctx, *periode)
    if refus is not None:
        return refuse(refus)
    return _sortie(resultat["etat"], resultat["recu"], "lignes", *page)


def _construire_bilan(ctx: Mapping[str, Any], au: date) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    mouvements, refus = rapports_financiers.extraire_mouvements(ctx["etat"], ctx["plan"], None, au)
    if refus is not None:
        return None, refus
    entrees = {
        "au": au.isoformat(),
        "comptes": mouvements["comptes"],
        "ecritures_definitives": mouvements["ecritures_definitives"],
        "brouillons": mouvements["brouillons"],
        "plan_comptable_version": mouvements["plan_comptable_version"],
        "sources": ctx["sources"],
    }
    return rapports_financiers.calculer_bilan(entrees, {"au": entrees["au"]}), None


def bilan_brouillon(au: str, depart: int | None = None, limite: int | None = None) -> dict[str, Any]:
    page, refus = _page(depart, limite)
    if refus is not None:
        return refuse(refus)
    ctx, refus = _contexte()
    if refus is not None:
        return refuse(refus)
    jour, refus = _jour_ou_refus(au)
    if refus is not None:
        return refuse(refus)
    resultat, refus = _construire_bilan(ctx, jour)
    if refus is not None:
        return refuse(refus)
    return _sortie(resultat["etat"], resultat["recu"], "lignes", *page)


# ============================================================================================================ budget
def _registre_budgets() -> Any | None:
    if not _o._stockage_durable_actif:
        return None
    return _o.registre_module.Registre(maillons=stockage.maillons(_o._DEPARTEMENT, _NOM_REGISTRE_BUDGETS))


def _etat_budgets() -> tuple[tuple[Any, dict[str, Any]] | None, dict[str, Any] | None]:
    registre = _registre_budgets()
    if registre is None:
        return None, _verdict("REJ-BUDGET-STOCKAGE-NON-DURABLE", "registre durable des budgets requis")
    valide, raison = registre.valider_chaine()
    if not valide:
        return None, _verdict("REJ-RAPPORT-CHAINE-INVALIDE", f"registre des budgets altéré : {raison}")
    etat = budgets.etat_budgets(registre.lire())
    refus = budgets.refus_anomalies(etat)
    return (None, refus) if refus is not None else ((registre, etat), None)


_A_DECLARER_BUDGET = (
    "aucun budget n'est déclaré : la direction le déclare avec m5_etablir_budget (N3), ligne par ligne — un "
    "compte de produits "
    "ou de charges du plan comptable, un mois AAAA-MM, un montant au cent. M5 n'en suppose aucun."
)


def _construire_budget_contre_reel(ctx: Mapping[str, Any], mois_debut: str, mois_fin: str):
    lecture, refus = _etat_budgets()
    if refus is not None:
        return None, refus
    actif = budgets.budget_actif(lecture[1])
    if actif is None:
        return None, _verdict("REJ-BUDGET-A-DECLARER", _A_DECLARER_BUDGET)
    mois = budgets.mois_entre(mois_debut, mois_fin)
    if mois is None or len(mois) > budgets.MOIS_MAX:
        return None, _verdict(
            "REJ-RAPPORT-PERIODE-INVALIDE",
            f"{mois_debut!r} -> {mois_fin!r} : mois AAAA-MM, début au plus tard à fin, {budgets.MOIS_MAX} au plus",
        )
    reel, refus = rapports_financiers.mouvements_par_mois(ctx["etat"], ctx["plan"], mois)
    if refus is not None:
        return None, refus
    premier = date.fromisoformat(mois[0] + "-01")
    dernier = rapports_financiers.fin_de_mois(mois[-1])
    mouvements, refus = rapports_financiers.extraire_mouvements(ctx["etat"], ctx["plan"], premier, dernier)
    if refus is not None:
        return None, refus
    lignes = [ligne for ligne in actif["lignes"] if ligne["mois"] in mois]
    fiches = []
    for compte in sorted({ligne["compte"] for ligne in lignes}):
        fiche = ctx["plan"]["comptes"].get(compte)
        if fiche is None:
            return None, _verdict(
                "REJ-RAPPORT-COMPTE-HORS-PLAN", f"le budget vise le compte {compte}, absent du plan courant"
            )
        fiches.append({"compte": compte, "nom": fiche["nom"], "type": fiche["type"]})
    entrees = {
        "mois": mois,
        "budget": {"budget_id": actif["budget_id"], "version": actif["version"], "lignes": lignes},
        "comptes_budget": fiches,
        "reel": reel,
        "ecritures_definitives": mouvements["ecritures_definitives"],
        "brouillons": mouvements["brouillons"],
        "sources": [*ctx["sources"], _source("budgets_declares", lecture[0])],
    }
    return rapports_financiers.calculer_budget_contre_reel(entrees, {"mois_debut": mois[0], "mois_fin": mois[-1]}), None


def budget_contre_reel(
    periode_debut: str, periode_fin: str, depart: int | None = None, limite: int | None = None
) -> dict[str, Any]:
    page, refus = _page(depart, limite)
    if refus is not None:
        return refuse(refus)
    ctx, refus = _contexte()
    if refus is not None:
        return refuse(refus)
    resultat, refus = _construire_budget_contre_reel(ctx, periode_debut, periode_fin)
    if refus is not None:
        return refuse(refus)
    return _sortie(resultat["etat"], resultat["recu"], "lignes", *page)


def etablir_budget(
    libelle: str, lignes: list[dict[str, str]], motif: str | None, version_attendue: int | None, horodatage: str
) -> dict[str, Any]:
    refus = _appareil_refuse()
    if refus is not None:
        return refuse(refus)
    registre = _registre_budgets()
    if registre is None:
        return refuse(_verdict("REJ-BUDGET-STOCKAGE-NON-DURABLE", "registre durable des budgets requis"))
    humain, refus = humain_requis("m5_etablir_budget", "déclarer le budget")
    if refus is not None:
        return refuse(_verdict("REJ-BUDGET-HUMAIN-REQUIS", refus["detail"]))
    try:
        instant = datetime.fromisoformat(horodatage) if isinstance(horodatage, str) else None
    except ValueError:
        instant = None
    if instant is None or instant.tzinfo is None:
        return refuse(_verdict("REJ-BUDGET-ENTREE-INVALIDE", "horodatage ISO 8601 avec fuseau requis"))
    lecture, refus = _etat_budgets()
    if refus is not None:
        return refuse(refus)
    _registre, etat = lecture
    plan, refus = _o._plan_comptable_effectif()
    if refus is not None:
        return refuse(refus)
    actif = budgets.budget_actif(etat)
    nombre = len(etat["versions"])
    if version_attendue is not None and version_attendue != nombre:
        return refuse(
            _verdict(
                "REJ-BUDGET-VERSION-ATTENDUE",
                f"version attendue {version_attendue}, mais {nombre} version(s) sont déjà déclarées",
            )
        )
    # Même contenu que le budget actif : rien à écrire (idempotent), motif ou non.
    ebauche, refus = budgets.construire_budget(
        lignes, libelle, plan, humain=humain, version=1, motif=None, remplace=None
    )
    if refus is not None:
        return refuse(refus)
    if actif is not None and actif["empreinte_budget"] == ebauche["empreinte_budget"]:
        return accepte({"statut": "deja", **_resume_budget(actif)})
    corps, refus = budgets.construire_budget(
        lignes,
        libelle,
        plan,
        humain=humain,
        version=nombre + 1,
        motif=motif,
        remplace=actif["budget_id"] if actif is not None else None,
    )
    if refus is not None:
        return refuse(refus)
    copie = _copie(registre)
    taille = copie.taille()
    resultat, refus = budgets.ajouter_budget(copie, etat, corps, horodatage)
    if refus is not None:
        return refuse(refus)
    _ecrire(stockage.maillons(_o._DEPARTEMENT, _NOM_REGISTRE_BUDGETS), copie, taille)
    return accepte(
        {
            "statut": resultat["statut"],
            **_resume_budget(resultat["budget"]),
            "a_faire": "lire le budget contre le réel avec m5_budget_contre_reel ; rien n'est comptabilisé ni payé",
        }
    )


def _resume_budget(budget: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "budget_id": budget["budget_id"],
        "version": budget["version"],
        "libelle": budget["libelle"],
        "mois_debut": budget["mois_debut"],
        "mois_fin": budget["mois_fin"],
        "lignes": len(budget["lignes"]),
        "plan_comptable_version": budget["plan_comptable_version"],
        "motif": budget["motif"],
        "declare_par": budget["declare_par"],
    }


def lire_budget(depart: int | None = None, limite: int | None = None) -> dict[str, Any]:
    page, refus = _page(depart, limite)
    if refus is not None:
        return refuse(refus)
    refus = _appareil_refuse()
    if refus is not None:
        return refuse(refus)
    lecture, refus = _etat_budgets()
    if refus is not None:
        return refuse(refus)
    etat = lecture[1]
    actif = budgets.budget_actif(etat)
    if actif is None:
        return refuse(_verdict("REJ-BUDGET-A-DECLARER", _A_DECLARER_BUDGET))
    lignes = actif["lignes"][page[0] : page[0] + page[1]]
    return accepte(
        {
            **_resume_budget(actif),
            "versions": [
                {"version": v["version"], "budget_id": v["budget_id"], "motif": v["motif"]} for v in etat["versions"]
            ],
            "lignes_page": lignes,
            "lignes_total": len(actif["lignes"]),
            "prochain_depart": page[0] + page[1] if page[0] + page[1] < len(actif["lignes"]) else None,
        }
    )


# ============================================================================================ rentabilité par axe
def _chantiers_rentabilite(debut: date | None, fin: date | None) -> list[dict[str, Any]]:
    """Une ligne par devis : la dernière rentabilité TRACÉE par la voie ordinaire (jamais une trace de la voie console),
    avec la dimension (service, ville) que M4 a publiée à la fin des travaux et que M5 a gardée. Un montant illisible
    rend la ligne « partielle » (None), jamais un zéro."""
    dernieres: dict[str, Mapping[str, Any]] = {}
    for trace in stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_RENTABILITE):
        if "provenance_v3" in trace or not isinstance(trace.get("rentabilite"), Mapping):
            continue
        dernieres[trace["devis_id"]] = trace
    wct_registre = stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_WCT_RECUS)
    lignes: list[dict[str, Any]] = []
    for devis_id in sorted(dernieres):
        trace = dernieres[devis_id]
        rent = trace["rentabilite"]
        jour = facturation.jour_de(trace.get("horodatage"))
        if (debut is not None and (jour is None or jour < debut)) or (fin is not None and (jour is None or jour > fin)):
            continue
        cout = rent.get("cout_reel") if isinstance(rent.get("cout_reel"), Mapping) else {}
        complet = (
            trace.get("verdict") == "CALCULEE" and cout.get("complet") is True and rent.get("marge_reelle") is not None
        )

        def texte(valeur: Any) -> str | None:
            try:
                return (
                    format(Decimal(str(valeur)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
                    if valeur is not None
                    else None
                )
            except (InvalidOperation, ValueError):
                return None

        marge, prix, total = (
            texte(rent.get("marge_reelle")),
            texte(rent.get("prix_facture")),
            texte(cout.get("cout_total")),
        )
        wct = wct_recus.pour_devis_id(devis_id, wct_registre) or {}
        lignes.append(
            {
                "devis_id": devis_id,
                "service": wct.get("service") if isinstance(wct.get("service"), str) and wct.get("service") else None,
                "ville": wct.get("ville") if isinstance(wct.get("ville"), str) and wct.get("ville") else None,
                "prix_definitif": rent.get("prix_definitif") is True,
                "prix_facture": prix if complet else None,
                "cout_reel": total if complet else None,
                "marge_reelle": marge if complet else None,
            }
        )
    return lignes


def _construire_rentabilite(axe: str, debut: date | None, fin: date | None):
    if axe not in rapports_financiers.AXES:
        return None, _verdict("REJ-RAPPORT-AXE-INVALIDE", f"axe {axe!r} : service ou ville")
    entrees = {
        "axe": axe,
        "debut": debut.isoformat() if debut else None,
        "fin": fin.isoformat() if fin else None,
        "chantiers": _chantiers_rentabilite(debut, fin),
        "sources": [
            _source("rentabilite", stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_RENTABILITE)),
            _source("wct_recus", stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_WCT_RECUS)),
        ],
    }
    return rapports_financiers.calculer_rentabilite_par_axe(
        entrees, {"axe": axe, "debut": entrees["debut"], "fin": entrees["fin"]}
    ), None


def rentabilite_par_axe(
    axe: str, debut: str | None = None, fin: str | None = None, depart: int | None = None, limite: int | None = None
) -> dict[str, Any]:
    page, refus = _page(depart, limite)
    if refus is not None:
        return refuse(refus)
    refus = _appareil_refuse()
    if refus is not None:
        return refuse(refus)
    if not _o._stockage_durable_actif:
        return refuse(_verdict("REJ-RAPPORT-STOCKAGE-NON-DURABLE", "registres durables requis"))
    jours = []
    for valeur in (debut, fin):
        if valeur is None:
            jours.append(None)
            continue
        jour, refus = _jour_ou_refus(valeur)
        if refus is not None:
            return refuse(refus)
        jours.append(jour)
    if None in jours and jours != [None, None]:
        return refuse(_verdict("REJ-RAPPORT-DATE-INVALIDE", "debut et fin vont ensemble (ou aucun des deux)"))
    resultat, refus = _construire_rentabilite(axe, *jours)
    if refus is not None:
        return refuse(refus)
    return _sortie(resultat["etat"], resultat["recu"], "groupes", *page)


# ==================================================================================================== pré-audit
def _preaudit_declare() -> Mapping[str, Any]:
    """`configuration.preaudit` de `department.yaml`, relu à chaque appel, avec par-dessus les réglages ADOPTÉS par la
    direction (couche unique `opsys.reglages`). Absent : `{}` ; aucun seuil n'est jamais supposé."""
    try:
        donnees = yaml.safe_load(_o._MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    configuration = donnees.get("configuration") if isinstance(donnees, dict) else None
    du_fichier = configuration.get("preaudit") if isinstance(configuration, dict) else None
    lu = reglages_lecture.superposer(donnees, ("configuration", "preaudit"), du_fichier)
    return lu if isinstance(lu, Mapping) else {}


def _txt(valeur: Any) -> str:
    return format(Decimal(str(valeur)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _normaliser_gl(etat: Mapping[str, Any]) -> list[dict[str, Any]]:
    ecritures = []
    for ident in etat["ordre"]:
        e = etat["ecritures"][ident]
        ecritures.append(
            {
                "id": e["ecriture_id"],
                "statut": e["statut"],
                "date_effet": e["date_effet"],
                "cle": e["cle_piece"],
                "piece_type": e["piece"]["type"],
                "piece_ref": _sur(e["piece"]["reference"], 120),
                "nature": e["nature"],
                "contre_passe": e["contre_passe"],
                "contre_passee_par": e.get("contre_passee_par"),
                "lignes": controleur_preaudit.normaliser_lignes(
                    [{"compte": li["compte"], "debit": li["debit"], "credit": li["credit"]} for li in e["lignes"]]
                ),
            }
        )
    return ecritures


def _ecarts_taxes(resultat: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Les écarts de TPS/TVQ du rapprochement du grand livre, en entrées normalisées. Un mouvement dont le NET est
    nul sur
    une pièce que plus aucune facture vivante ne vise (une écriture et sa contre-passation, après l'annulation de la
    facture) n'est pas un écart : la correction est faite. Le rapprochement le range pourtant parmi ses écarts (une
    ligne
    « sans facture » à 0,00 $) ; le contrôle ne le répète pas."""
    ecarts = []
    for role, bloc in resultat["taxes"].items():
        for e in bloc["ecarts"]:
            if e.get("attendu_taxes") is None and Decimal(str(e["au_grand_livre"])) == 0:
                continue
            ecarts.append(
                {
                    "cote": "clients",
                    "role": role,
                    "reference": e.get("facture_id"),
                    "raison": e["raison"],
                    "attendu": e.get("attendu_taxes"),
                    "sans_ecriture": e["raison"] == "sans écriture définitive",
                    "au_grand_livre": e["au_grand_livre"],
                }
            )
    for role, bloc in resultat["intrants"].items():
        for e in bloc["ecarts"]:
            if e.get("attendu_facture") is None and Decimal(str(e["au_grand_livre"])) == 0:
                continue
            ecarts.append(
                {
                    "cote": "intrants",
                    "role": role,
                    "reference": e.get("facture_fournisseur_id"),
                    "raison": e["raison"],
                    "sans_ecriture": e["raison"] == "sans écriture définitive",
                    "attendu": e.get("attendu_facture"),
                    "au_grand_livre": e["au_grand_livre"],
                }
            )
    return ecarts


def construire_dossier_preaudit(aujourd_hui: date) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Le dossier NORMALISÉ (types JSON) que `controleur_preaudit.controler` consomme : ce que les registres de M5
    portent
    aujourd'hui. Lecture seule. Une chaîne altérée n'arrête pas le contrôle : elle devient un constat et rend non
    évaluées les règles qui en dépendent."""
    refus = _appareil_refuse()
    if refus is not None:
        return None, refus
    if not _o._stockage_durable_actif:
        return None, _verdict("REJ-PREAUDIT-STOCKAGE-NON-DURABLE", "registres durables requis")
    plan, refus = _o._plan_comptable_effectif()
    if refus is not None:
        return None, refus
    seuils, problemes_seuils = controleur_preaudit.seuils_depuis(_preaudit_declare())
    chaines: list[dict[str, Any]] = []

    def chaine(nom: str, registre: Any) -> bool:
        valide, raison = registre.valider_chaine()
        chaines.append({"registre": nom, "ok": bool(valide), "detail": _une_ligne(raison or "")})
        return bool(valide)

    registre_gl = _o._registre_grand_livre()
    gl_chaine = chaine("grand_livre", registre_gl)
    etat_gl = grand_livre.etat_grand_livre(registre_gl.lire())
    gl_utilisable = gl_chaine and not etat_gl["anomalies"]
    registre_factures = _o._registre_factures(None)
    chaine("factures", registre_factures)
    registre_ap = _o._registre_comptes_a_payer()
    ap_chaine = chaine("comptes_a_payer", registre_ap)
    registre_ops = _o._registre_operations()
    ops_chaine = chaine("operations_comptables", registre_ops)
    registre_numeros = _o._registre_numerotation()
    chaine("numerotation_factures", registre_numeros)

    clients_bruts = facturation.etats_des_factures(registre_factures)
    clients = [
        {
            "facture_id": f["facture_id"],
            "statut": f["statut"],
            "numero": f.get("numero_facture"),
            "date_envoi": str(f["date_envoi"])[:10] if f.get("date_envoi") else None,
            "echeance": f.get("echeance"),
            "montant_avant_taxes": _txt(f["montant_avant_taxes"]),
            "montant_apres_taxes": _txt(f["montant_apres_taxes"]),
        }
        for f in clients_bruts
    ]
    ap_etats: list[dict[str, Any]] = []
    if ap_chaine:
        try:
            ap_etats = list(comptes_a_payer._etats_factures(registre_ap.lire()).values())
        except RuntimeError as exc:
            chaines.append({"registre": "comptes_a_payer", "ok": False, "detail": _une_ligne(exc)})
    fournisseurs = []
    for f in ap_etats:
        compte, _refus = plan_comptable.compte_de_charge(
            plan, po_id=f.get("po_id"), categorie=f.get("categorie_depense")
        )
        fournisseurs.append(
            {
                "id": f["facture_fournisseur_id"],
                "fournisseur_id": str(f["fournisseur_id"]),
                "numero": _sur(f["numero_facture"], 40),
                "date_facture": str(f["date_facture"])[:10],
                "montant_avant_taxes": _txt(f["montant_avant_taxes"]),
                "statut": f["statut"],
                "compte_charge": compte,
            }
        )
    depenses: list[dict[str, Any]] = []
    notes: list[str] = []
    pieces_liees: list[list[str]] = []
    if ops_chaine:
        etat_ops = operations_registre.etat_operations(registre_ops.lire())
        if etat_ops["anomalies"]:
            chaines.append(
                {"registre": "operations_comptables", "ok": False, "detail": "; ".join(etat_ops["anomalies"][:2])}
            )
        for d in etat_ops["par_type"]["op_depense_employe_proposee"].values():
            depenses.append({"id": d["depense_id"], "date": d["date_depense"], "montant": d["montant_avant_taxes"]})
        notes = [n["note_id"] for n in etat_ops["par_type"]["op_note_credit_proposee"].values()]
        pieces_liees = [[p["cible_type"], p["cible_id"]] for p in etat_ops["par_type"]["op_piece_liee"].values()]
    vivantes = [f for f in ap_etats if f["statut"] in ("SAISIE", "CORRIGEE")]
    emises = [f for f in clients_bruts if f["statut"] in ("ENVOYEE", "PAYEE")]
    # Les écritures qu'une facture ATTENDRAIT, recalculées depuis la pièce courante (la comparaison de
    # FACTURE_MODIFIEE).
    props_clients, ignorees_clients = grand_livre.propositions_factures_clients(clients_bruts, plan)
    props_fournisseurs, ignorees_fournisseurs = grand_livre.propositions_factures_fournisseurs(vivantes, plan)
    attendues = [
        {
            "cle": p["cle_piece"],
            "lignes": controleur_preaudit.normaliser_lignes(
                [{"compte": li["compte"], "debit": li["debit"], "credit": li["credit"]} for li in p["lignes_brutes"]]
            ),
        }
        for p in (*props_clients, *props_fournisseurs)
    ]
    illisibles = [
        {"registre": "factures", "reference": str(i["facture_id"]), "code": i["code"]} for i in ignorees_clients
    ]
    illisibles += [
        {"registre": "comptes_a_payer", "reference": str(i["facture_fournisseur_id"]), "code": i["code"]}
        for i in ignorees_fournisseurs
    ]
    taxes: dict[str, Any] = {"disponible": False, "raison": "grand livre non lisible", "ecarts": [], "illisibles": 0}
    if gl_utilisable:
        dictionnaire, refus_taux = _o._dictionnaire_taux()
        if refus_taux is not None:
            taxes["raison"] = f"taux fiscaux illisibles ({refus_taux['code']})"
        else:
            dates = [date.fromisoformat(e["date_effet"]) for e in etat_gl["ecritures"].values()]
            dates += [date.fromisoformat(f["date_envoi"]) for f in clients if f["date_envoi"]]
            dates += [
                date.fromisoformat(f["date_facture"]) for f in fournisseurs if f["statut"] in ("SAISIE", "CORRIGEE")
            ]
            debut = min([*dates, aujourd_hui])
            resultat, refus_gl = grand_livre.rapprocher(
                etat_gl,
                plan,
                emises,
                dictionnaire,
                debut=debut.isoformat(),
                fin=aujourd_hui.isoformat(),
                limite_ecarts=100000,
                factures_fournisseurs=vivantes,
                autres_pieces_taxees=_o._autres_pieces_taxees(),
            )
            if refus_gl is not None:
                taxes["raison"] = refus_gl["detail"]
            else:
                taxes = {
                    "disponible": True,
                    "raison": "",
                    "ecarts": _ecarts_taxes(resultat),
                    "illisibles": len(resultat["factures_illisibles"])
                    + len(resultat["factures_fournisseurs_illisibles"]),
                }
    verification = facturation_jalons.verifier_numerotation(registre_numeros.lire())
    defauts = [f"trou dans la suite : {n}" for n in verification["trous"]]
    defauts += verification["doublons"] + verification["anomalies"]
    numeros_attribues = {m["facture_id"]: m["numero_facture"] for m in registre_numeros.lire() if m.get("facture_id")}
    for f in clients_bruts:
        if f.get("numero_facture") and numeros_attribues.get(f["facture_id"]) != f["numero_facture"]:
            defauts.append(f"facture {f['facture_id']} numérotée hors du registre de numérotation")
    dossier = {
        "aujourd_hui": aujourd_hui.isoformat(),
        "gl_utilisable": gl_utilisable,
        "anomalies_gl": [_une_ligne(a) for a in etat_gl["anomalies"]],
        "plan": {
            "banque": plan["roles"]["banque"],
            "comptes_clients": plan["roles"]["comptes_clients"],
            "comptes_fournisseurs": plan["roles"].get("comptes_fournisseurs", ""),
            "types": {numero: fiche["type"] for numero, fiche in sorted(plan["comptes"].items())},
        },
        "ecritures": _normaliser_gl(etat_gl) if gl_utilisable else [],
        "factures_clients": clients,
        "factures_fournisseurs": fournisseurs,
        "depenses_employes": depenses,
        "notes_credit": notes,
        "pieces_liees": sorted(pieces_liees),
        "attendues": attendues,
        "pieces_illisibles": illisibles,
        "taxes": taxes,
        "chaines": chaines,
        "numerotation": {"ok": not defauts, "defauts": [_une_ligne(d) for d in defauts[:100]]},
        "seuils": seuils,
        "seuils_problemes": problemes_seuils,
        "sources": [
            _source("grand_livre", registre_gl),
            _source("factures", registre_factures),
            _source("comptes_a_payer", registre_ap),
            _source("operations_comptables", registre_ops),
            _source("numerotation_factures", registre_numeros),
        ],
    }
    return dossier, None


def _controler(aujourd_hui: date) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    dossier, refus = construire_dossier_preaudit(aujourd_hui)
    if refus is not None:
        return None, refus
    return controleur_preaudit.controler(dossier), None


def controler_preaudit(aujourd_hui: str, depart: int | None = None, limite: int | None = None) -> dict[str, Any]:
    page, refus = _page(depart, limite)
    if refus is not None:
        return refuse(refus)
    jour, refus = _jour_ou_refus(aujourd_hui)
    if refus is not None:
        return refuse(_verdict("REJ-PREAUDIT-DATE-INVALIDE", refus["detail"]))
    rapport, refus = _controler(jour)
    if refus is not None:
        return refuse(refus)
    corps = {
        "statut": "CONTROLE",
        "aujourd_hui": jour.isoformat(),
        "total": rapport["total"],
        "par_gravite": rapport["par_gravite"],
        "par_regle": rapport["par_regle"],
        "regles_non_evaluees": [
            {"regle": r["regle"], "manque": r["manque"]} for r in rapport["regles"] if r["etat"] == "NON_EVALUEE"
        ],
        "regles_partielles": [
            {"regle": r["regle"], "manque": r["manque"]} for r in rapport["regles"] if r["etat"] == "PARTIELLE"
        ],
        "constats": rapport["constats"],
    }
    dossier = rapport["recu"]["entrees"]["dossier"]
    corps["sources"] = dossier["sources"]
    if dossier["seuils_problemes"]:
        corps["seuils_problemes"] = dossier["seuils_problemes"]
    return _sortie(corps, rapport["recu"], "constats", *page)


def _instant(horodatage: Any) -> tuple[str | None, dict[str, str] | None]:
    try:
        instant = datetime.fromisoformat(horodatage) if isinstance(horodatage, str) else None
    except ValueError:
        instant = None
    if instant is None or instant.tzinfo is None:
        return None, _verdict("REJ-PREAUDIT-DATE-INVALIDE", "horodatage ISO 8601 avec fuseau requis")
    return horodatage, None


def constater_preaudit(aujourd_hui: str, horodatage: str) -> dict[str, Any]:
    """`m5_constater_preaudit` (N2, agent seulement) : fait CONTRÔLER le pré-audit et PUBLIE ses comptes
    (`m5.preaudit_constate`) pour M8, qui n'appelle aucun outil de M5. Ni facture, ni fournisseur, ni client, ni
    écriture, ni
    montant ne part. Une règle non évaluée part en `null`, jamais en zéro. Rejouer le même constat (même horodatage) ne
    publie rien de plus."""
    jour, refus = _jour_ou_refus(aujourd_hui)
    if refus is not None:
        return refuse(_verdict("REJ-PREAUDIT-DATE-INVALIDE", refus["detail"]))
    instant, refus = _instant(horodatage)
    if refus is not None:
        return refuse(refus)
    rapport, refus = _controler(jour)
    if refus is not None:
        return refuse(refus)
    charge = constat_preaudit.charge_preaudit(rapport, jour.isoformat(), instant)
    evenements.publier(TYPE_EVENEMENT_PREAUDIT, _o._DEPARTEMENT, charge, evenement_id=charge["evenement_id"])
    return accepte(
        {
            "publie": True,
            "evenement_id": charge["evenement_id"],
            "date_reference": charge["date_reference"],
            "version_donnees": charge["version_donnees"],
            "constats_total": charge["constats_total"],
            "constats_par_gravite": charge["constats_par_gravite"],
            "regles_non_evaluees": charge["regles_non_evaluees"],
            "regles_partielles": charge["regles_partielles"],
        }
    )


# =============================================================================================== rapport de direction
def _faits_resultats(resultat: Mapping[str, Any]) -> list[dict[str, Any]]:
    etat = resultat["etat"]
    return [
        {"libelle": "Produits du mois", "valeur_cad": etat["total_produits"]},
        {"libelle": "Charges du mois", "valeur_cad": etat["total_charges"]},
        {"libelle": "Résultat avant impôts du mois", "valeur_cad": etat["resultat_avant_impots"]},
    ]


def rapport_mensuel_direction(
    periode: str, au: str | None = None, depart: int | None = None, limite: int | None = None
) -> dict[str, Any]:
    page, refus = _page(depart, limite)
    if refus is not None:
        return refuse(refus)
    fin = rapports_financiers.fin_de_mois(periode)
    if fin is None:
        return refuse(_verdict("REJ-RAPPORT-PERIODE-INVALIDE", f"periode {periode!r} : AAAA-MM exigé"))
    debut = date.fromisoformat(periode + "-01")
    ctx, refus = _contexte()
    if refus is not None:
        return refuse(refus)
    if au is None:
        jour_audit = fin
    else:
        jour_audit, refus = _jour_ou_refus(au)
        if refus is not None:
            return refuse(refus)
    sections = []
    # 1. Résultats du mois (et mois précédent pour la variation)
    resultats, refus = _construire_resultats(ctx, debut, fin)
    if refus is not None:
        return refuse(refus)
    mois_precedent = (debut - timedelta(days=1)).strftime("%Y-%m")
    precedent, refus = _construire_resultats(ctx, date.fromisoformat(mois_precedent + "-01"), debut - timedelta(days=1))
    if refus is not None:
        return refuse(refus)
    faits = _faits_resultats(resultats)
    variation = Decimal(resultats["etat"]["resultat_avant_impots"]) - Decimal(
        precedent["etat"]["resultat_avant_impots"]
    )
    faits.append(
        {
            "libelle": f"Résultat avant impôts du mois précédent ({mois_precedent})",
            "valeur_cad": precedent["etat"]["resultat_avant_impots"],
        }
    )
    faits.append({"libelle": "Variation du résultat avant le mois précédent", "valeur_cad": _txt(variation)})
    manquantes = []
    marge = resultats["etat"]["marge_brute"]
    if marge["statut"] == "CALCULEE":
        faits.append(
            {
                "libelle": "Marge brute du mois",
                "valeur_cad": marge["montant"],
                "pourcentage_des_produits": marge["pourcentage_des_produits"],
            }
        )
    else:
        manquantes.append({"code": "COUTS_DIRECTS", "a_declarer": marge["manque"]})
    brouillons = resultats["etat"]["completude"]["brouillons_non_comptabilises"]
    sections.append(
        rapports_financiers.section(
            "resultats",
            "Résultats du mois",
            "PARTIEL" if manquantes or brouillons else "CALCULE",
            faits=faits,
            hypotheses=[
                "Écritures définitives seulement ; résultat avant impôts (aucun compte d'impôt au plan).",
                *([f"{brouillons} écriture(s) en brouillon du mois ne sont pas comptées."] if brouillons else []),
            ],
            manquantes=manquantes,
            recu=resultats["recu"],
        )
    )
    # 2. Bilan
    bilan, refus = _construire_bilan(ctx, fin)
    if refus is not None:
        return refuse(refus)
    b = bilan["etat"]
    sections.append(
        rapports_financiers.section(
            "bilan",
            "Bilan à la fin du mois (brouillon)",
            "CALCULE" if b["equilibre"] else "PARTIEL",
            faits=[
                {"libelle": "Total de l'actif", "valeur_cad": b["total_actif"]},
                {"libelle": "Total du passif", "valeur_cad": b["total_passif"]},
                {"libelle": "Capitaux propres", "valeur_cad": b["total_capitaux_propres"]},
                {"libelle": "Résultat cumulé non clos", "valeur_cad": b["resultat_cumule_non_clos"]},
                {"libelle": "Le bilan s'équilibre", "valeur": b["equilibre"]},
            ],
            hypotheses=[
                "Aucune écriture de clôture d'exercice au grand livre : le résultat cumulé est depuis le début du "
                "registre."
            ],
            recu=bilan["recu"],
        )
    )
    # 3. Budget contre réel
    budget, refus = _construire_budget_contre_reel(ctx, periode, periode)
    if refus is not None and refus["code"] != "REJ-BUDGET-A-DECLARER":
        return refuse(refus)
    if refus is not None:
        sections.append(
            rapports_financiers.section(
                "budget",
                "Budget contre réel",
                "NON_CALCULABLE",
                manquantes=[{"code": "BUDGET", "a_declarer": refus["detail"]}],
            )
        )
    else:
        eb = budget["etat"]
        if eb["statut"] == "CALCULEE":
            sections.append(
                rapports_financiers.section(
                    "budget",
                    "Budget contre réel",
                    "CALCULE",
                    faits=[
                        {
                            "libelle": "Résultat budgété (comptes budgétés)",
                            "valeur_cad": eb["totaux"]["resultat_budgete"],
                        },
                        {
                            "libelle": "Résultat réel (comptes budgétés)",
                            "valeur_cad": eb["totaux"]["resultat_reel_des_comptes_budgetes"],
                        },
                        {"libelle": "Écart du résultat", "valeur_cad": eb["totaux"]["ecart_resultat"]},
                        {
                            "libelle": "Comptes sans ligne de budget mais avec du réel",
                            "valeur": len(eb["non_budgetes"]),
                        },
                    ],
                    hypotheses=[f"Budget déclaré par la direction, version {eb['budget']['version']}."],
                    recu=budget["recu"],
                )
            )
        else:
            sections.append(
                rapports_financiers.section(
                    "budget",
                    "Budget contre réel",
                    "NON_CALCULABLE",
                    manquantes=[{"code": "BUDGET_DU_MOIS", "a_declarer": eb["manque"]}],
                    recu=budget["recu"],
                )
            )
    # 4. Rentabilité par service et par ville
    for axe in rapports_financiers.AXES:
        rent, _refus = _construire_rentabilite(axe, debut, fin)
        er = rent["etat"]
        if er["statut"] == "CALCULEE":
            sections.append(
                rapports_financiers.section(
                    f"rentabilite_{axe}",
                    f"Rentabilité par {axe}",
                    "CALCULE",
                    faits=[
                        {
                            "libelle": "Marge réelle totale des chantiers regroupés",
                            "valeur_cad": er["total"]["marge_reelle"],
                        },
                        {"libelle": "Chantiers regroupés", "valeur": er["total"]["chantiers"]},
                        {"libelle": "Chantiers exclus (coût partiel)", "valeur": er["exclus_cout_partiel"]},
                        {"libelle": f"Chantiers sans {axe}", "valeur": er["sans_dimension"]},
                    ],
                    hypotheses=[
                        "Rentabilité par chantier de M5 (matériaux, main-d'œuvre), distincte du résultat comptable."
                    ],
                    recu=rent["recu"],
                )
            )
        else:
            sections.append(
                rapports_financiers.section(
                    f"rentabilite_{axe}",
                    f"Rentabilité par {axe}",
                    "NON_CALCULABLE",
                    manquantes=[{"code": f"DIMENSION_{axe.upper()}", "a_declarer": er["manque"]}],
                    recu=rent["recu"],
                )
            )
    # 5. Pré-audit
    audit, refus = _controler(jour_audit)
    if refus is not None:
        return refuse(refus)
    non_evaluees = [r for r in audit["regles"] if r["etat"] == "NON_EVALUEE"]
    sections.append(
        rapports_financiers.section(
            "preaudit",
            "Pré-audit (contrôle interne)",
            "PARTIEL" if non_evaluees else "CALCULE",
            faits=[
                {"libelle": "Constats ouverts", "valeur": audit["total"]},
                {"libelle": "Constats de gravité haute", "valeur": audit["par_gravite"]["haute"]},
            ],
            hypotheses=["Un constat est une question posée à une personne, pas un verdict."],
            manquantes=[{"code": r["regle"], "a_declarer": "; ".join(r["manque"])} for r in non_evaluees],
            recu=audit["recu"],
        )
    )
    composition = rapports_financiers.composer_rapport_mensuel(
        periode, sections, {"periode": periode, "au": jour_audit.isoformat()}
    )
    return _sortie(composition["etat"], composition["recu"], "sections", *page)


# ============================================================================================================ rejeu
def rejouer_rapport_financier(recu: dict[str, Any]) -> dict[str, Any]:
    """Vérifie un reçu de rapport (empreintes) et le REJOUE (refait le calcul depuis ses `entrees`). Lecture pure."""
    refus = _appareil_refuse()
    if refus is not None:
        return refuse(refus)
    valide, raison = recu_calcul.verifier(recu)
    if not valide:
        return refuse(_verdict("REJ-RAPPORT-RECU-INVALIDE", raison))
    moteurs = {**rapports_financiers.MOTEURS, "preaudit_controle": controleur_preaudit.rejouer_controle}
    rejouable, raison = rapports_financiers.rejouer(recu, moteurs)
    if not rejouable and "entrees" in recu:
        return refuse(_verdict("REJ-RAPPORT-REJEU-DIFFERENT", raison))
    return accepte(
        {
            "recu_valide": True,
            "rejoue": rejouable,
            "moteur": recu["moteur"],
            "empreinte": recu["empreinte"],
            "note": None if rejouable else raison,
        }
    )


# ============================================================================================================ outils
def outils_rapports() -> tuple[Outil, ...]:
    mention = " Sortie comptable : porte la mention « À valider auprès d'un comptable (CPA) / professionnel qualifié »."
    brouillon = " BROUILLON PRÉPARATOIRE, à valider auprès d'un comptable (CPA) : écritures définitives seulement."
    objet = {"type": "object", "additionalProperties": False}
    return (
        Outil(
            nom="m5_etat_des_resultats",
            description=(
                "État des résultats (BROUILLON) d'une période, tiré du grand livre : produits, charges, résultat avant "
                "impôts, marge brute seulement si les comptes de coûts directs sont déclarés (sinon « non calculable, "
                "manque X »). Décimal exact, brouillons comptés à part. Reçu rejouable. Lecture pure."
                + brouillon
                + mention
            ),
            parametres={
                **objet,
                "properties": {"debut": _DATE, "fin": _DATE, **_PAGINATION},
                "required": ["debut", "fin"],
            },
            fonction=etat_des_resultats,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_bilan_brouillon",
            description=(
                "Bilan (BROUILLON) à une date, tiré du grand livre : actif, passif, capitaux propres, résultat "
                "cumulé non "
                "clos et la preuve actif = passif + capitaux + résultat. Reçu rejouable. Lecture pure."
                + brouillon
                + mention
            ),
            parametres={**objet, "properties": {"au": _DATE, **_PAGINATION}, "required": ["au"]},
            fonction=bilan_brouillon,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_budget_contre_reel",
            description=(
                "Budget DÉCLARÉ contre le réel du grand livre, mois par mois et compte par compte (écart, favorable ou "
                "défavorable). Aucun budget déclaré : refus qui dit quoi déclarer (m5_etablir_budget), jamais un "
                "budget "
                "supposé ; un mois sans budget est nommé, jamais comparé à zéro. Reçu rejouable. Lecture pure."
                + brouillon
                + mention
            ),
            parametres={
                **objet,
                "properties": {"periode_debut": _MOIS, "periode_fin": _MOIS, **_PAGINATION},
                "required": ["periode_debut", "periode_fin"],
            },
            fonction=budget_contre_reel,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_etablir_budget",
            description=(
                "DÉCLARE le budget de la direction : des lignes {compte de produits ou de charges, mois AAAA-MM, "
                "montant "
                "au cent}. Une version complète remplace la précédente (motif obligatoire, le passé reste lisible) ; "
                "redéclarer le même contenu ne crée rien. Compte inconnu, de bilan ou désactivé, montant à plus de "
                "deux "
                "décimales, ligne en double = refus qui dit quoi corriger. N3 : l'appel attend la décision du "
                "propriétaire "
                "ou de la finance ; un agent seul est refusé (REJ-BUDGET-HUMAIN-REQUIS)." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "libelle": {
                        "type": "string",
                        "description": "Une ligne, 80 caractères au plus (ex. « Budget 2026 »).",
                    },
                    "lignes": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": budgets.LIGNES_MAX,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "compte": {"type": "string"},
                                "mois": _MOIS,
                                "montant": {"type": "string", "description": 'Texte décimal au cent, ex. "1500.00".'},
                            },
                            "required": ["compte", "mois", "montant"],
                        },
                    },
                    "motif": {
                        "type": ["string", "null"],
                        "description": "Obligatoire pour remplacer un budget déjà déclaré.",
                    },
                    "version_attendue": {
                        "type": ["integer", "null"],
                        "minimum": 0,
                        "description": "Nombre de versions déjà déclarées, pour refuser une déclaration concurrente.",
                    },
                    "horodatage": _HORODATAGE,
                },
                "required": ["libelle", "lignes", "motif", "version_attendue", "horodatage"],
            },
            fonction=etablir_budget,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m5_lire_budget",
            description=(
                "Lit le budget déclaré actif : son libellé, ses mois, ses versions et ses lignes (paginées). Aucun "
                "budget "
                "déclaré : refus qui dit quoi déclarer. Lecture pure." + mention
            ),
            parametres={**objet, "properties": {**_PAGINATION}},
            fonction=lire_budget,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_rentabilite_par_axe",
            description=(
                "Marge réelle regroupée par SERVICE ou par VILLE, à partir des rentabilités de chantier de M5 "
                "(coût complet "
                "et prix définitif seulement ; le reste est exclu et compté) et de la dimension que M4 publie à la fin "
                "des travaux. Dimension absente de tous les chantiers : « non calculable, manque X », jamais zéro "
                "ni une "
                "ville devinée. Reçu rejouable. Lecture pure." + brouillon + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "axe": {"type": "string", "enum": list(rapports_financiers.AXES)},
                    "debut": {**_DATE, "type": ["string", "null"]},
                    "fin": {**_DATE, "type": ["string", "null"]},
                    **_PAGINATION,
                },
                "required": ["axe"],
            },
            fonction=rentabilite_par_axe,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_rapport_mensuel_direction",
            description=(
                "Rapport mensuel de direction (BROUILLON) : résultats du mois et variation, bilan, budget contre réel, "
                "rentabilité par service et par ville, pré-audit. Chaque section distingue FAITS (chiffres tirés d'un "
                "rapport, avec son reçu), HYPOTHÈSES et DONNÉES MANQUANTES ; aucune section ne devine ce qui manque. "
                "Aucune clôture, aucune écriture. Lecture pure." + brouillon + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "periode": _MOIS,
                    "au": {
                        **_DATE,
                        "type": ["string", "null"],
                        "description": "Date de référence du pré-audit (défaut : la fin du mois).",
                    },
                    **_PAGINATION,
                },
                "required": ["periode"],
            },
            fonction=rapport_mensuel_direction,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_controler_preaudit",
            description=(
                "Contrôleur de pré-audit, DÉTERMINISTE et en lecture seule : dix règles (factures sans paiement, "
                "paiements sans "
                "facture, dépenses sans reçu, taxes incohérentes selon le moteur fiscal versionné, doublons, "
                "transactions hors "
                "norme, factures modifiées, changement de compte inhabituel, piste d'audit incomplète, documents "
                "manquants). "
                "Sort une liste de constats (règle, raison, sources, action proposée JAMAIS exécutée). Une règle "
                "dont le seuil "
                "déclaré est absent est NON ÉVALUÉE et dit quoi déclarer. Reçu rejouable. Lecture pure." + mention
            ),
            parametres={**objet, "properties": {"aujourd_hui": _DATE, **_PAGINATION}, "required": ["aujourd_hui"]},
            fonction=controler_preaudit,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_constater_preaudit",
            description=(
                "Fait CONTRÔLER le pré-audit et PUBLIE au bus (m5.preaudit_constate) les seuls COMPTES de constats "
                "pour M8 : "
                "par règle (null pour une règle non évaluée, jamais zéro), par gravité. Ni facture, ni "
                "fournisseur, ni client, "
                "ni montant ne part. Rejouer le même constat (même horodatage) ne publie rien de plus. Déclenché "
                "par le "
                "planificateur durable (constats_planifies), jamais par un agent seul. aujourd_hui : jour du constat ; "
                "horodatage : instant (ISO 8601 avec fuseau)." + mention
            ),
            parametres={
                **objet,
                "properties": {"aujourd_hui": _DATE, "horodatage": _HORODATAGE},
                "required": ["aujourd_hui", "horodatage"],
            },
            fonction=constater_preaudit,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m5_rejouer_rapport_financier",
            description=(
                "Vérifie un reçu de rapport (état des résultats, bilan, budget contre réel, rentabilité par axe, "
                "rapport de "
                "direction, pré-audit) : ses empreintes, puis REFAIT le calcul depuis ses entrées et compare. Un "
                "reçu compact "
                "(sans entrées) se vérifie sans se rejouer hors ligne. Lecture pure." + mention
            ),
            parametres={**objet, "properties": {"recu": {"type": "object"}}, "required": ["recu"]},
            fonction=rejouer_rapport_financier,
            autonomie=Autonomie.T0,
        ),
    )
