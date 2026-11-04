"""Outils MCP de la prévision financière longue de M5 (M5-PREV-2) : 6, 12 et 24 mois.

Adaptateur (comme `outils_rapports.py`) : il lit les registres réels (mouvements, grand livre, budgets déclarés,
échéanciers de contrats), normalise les entrées, puis délègue TOUT le calcul à `prevision_longue.py`, qui est pur. Il ne
nomme jamais le registre des mouvements : une projection ne fait bouger aucun argent (la garde AST
`conformite.verifier_aucun_decaissement` le vérifie en mode strict).

Qui décide quoi.

* LIRE la projection et REJOUER un reçu : T0, lecture pure, aucune écriture, aucun appareil (portée fermée). La
  projection est un BROUILLON préparatoire et porte les deux mentions de M5.
* Les hypothèses (croissance, saisonnalité, délais de paiement, nombre de mois historiques) et les NOMS des scénarios
  sont DÉCLARÉS par la direction dans `configuration.prevision_longue` (`department.yaml`) ; l'outil ne les reçoit
  jamais en argument et n'en suppose aucun. Absents ou illisibles : refus nommé qui dit quoi déclarer.
* Aucun paiement, aucune remise, aucune déclaration, aucun envoi, aucune écriture. Aucune donnée de client, aucun nom,
  aucun texte libre ne sort : identifiants de contrat seulement, dans le reçu, jamais dans la réponse lisible.

Aucune migration : les budgets et les échéanciers sont déjà des registres append-only sur `stockage.maillons`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil

from . import (
    budgets,
    echeanciers_contrats,
    grand_livre,
    prevision,
    prevision_longue,
    rapports_financiers,
    recu_calcul,
    soldes,
    verdicts_prevision_longue,
)
from . import outils as _o
from .outils_operations import _appareil_refuse, accepte, refuse

__all__ = ["outils_prevision_longue", "prevoir_tresorerie_longue", "rejouer_prevision_longue"]

_NOM_REGISTRE_BUDGETS = "budgets_declares"
_LIMITE_DEFAUT, _LIMITE_MAX = 12, 24
_NOTE_ENTREES_OMISES = "reçu compact : empreinte vérifiable, rejeu hors ligne impossible"
_A_DECLARER = (
    "aucune hypothèse de prévision longue n'est déclarée : écrire configuration.prevision_longue avec mois_historique "
    "(3 à 24) et au moins un scénario nommé (croissance_revenus_mensuelle, croissance_charges_mensuelle, saisonnalite "
    "de douze coefficients, delai_encaissement_jours, delai_paiement_jours). M5 n'en suppose aucune."
)


def _verdict(code: str, detail: str = "") -> dict[str, Any]:
    return verdicts_prevision_longue.construire_verdict(code, detail=detail)


def _configuration() -> Any:
    return _o._configuration_manifeste().get("prevision_longue")


def _source(nom: str, registre: Any) -> dict[str, Any]:
    taille = registre.taille() if hasattr(registre, "taille") else len(registre)
    tete = registre.tete() if hasattr(registre, "tete") else None
    return {"registre": nom, "taille": taille, "tete": tete[:16] if isinstance(tete, str) else tete}


def _premier_et_dernier(mois: str) -> tuple[date, date]:
    annee, numero = int(mois[:4]), int(mois[5:7])
    debut = date(annee, numero, 1)
    suivant = date(annee + (numero == 12), numero % 12 + 1, 1)
    return debut, suivant - timedelta(days=1)


def _mois_projetes(aujourd_hui: date, horizon: int) -> list[str]:
    premier = _mois_suivant(f"{aujourd_hui.year:04d}-{aujourd_hui.month:02d}")
    return [_mois_plus(premier, indice) for indice in range(horizon)]


def _mois_suivant(mois: str) -> str:
    return _mois_plus(mois, 1)


def _mois_plus(mois: str, decalage: int) -> str:
    indice = int(mois[:4]) * 12 + int(mois[5:7]) - 1 + decalage
    return f"{indice // 12:04d}-{indice % 12 + 1:02d}"


def _mois_historique(aujourd_hui: date, nombre: int) -> list[str]:
    courant = f"{aujourd_hui.year:04d}-{aujourd_hui.month:02d}"
    return [_mois_plus(courant, -decalage) for decalage in range(nombre, 0, -1)]


def _net(ligne: Mapping[str, Any]) -> Decimal:
    debit, credit = Decimal(ligne["debit"]), Decimal(ligne["credit"])
    return debit - credit if ligne["type"] in ("actif", "charges") else credit - debit


def _lire_historique(
    etat_gl: Mapping[str, Any], plan: Mapping[str, Any], mois: list[str]
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Les produits et charges des écritures DÉFINITIVES de chaque mois, ou le refus nommé (plan, chaîne)."""
    if etat_gl["anomalies"]:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-CHAINE-INVALIDE",
            "grand livre : " + "; ".join(etat_gl["anomalies"][:3]),
        )
    historique: list[dict[str, Any]] = []
    for un_mois in mois:
        debut, fin = _premier_et_dernier(un_mois)
        mouvements, refus = rapports_financiers.extraire_mouvements(etat_gl, plan, debut, fin)
        if refus is not None:
            code = (
                "REJ-PREVISION-LONGUE-PLAN-INVALIDE"
                if refus.get("code") == "REJ-RAPPORT-COMPTE-HORS-PLAN"
                else "REJ-PREVISION-LONGUE-HISTORIQUE-INVALIDE"
            )
            return None, _verdict(code, refus.get("detail", "mois historique illisible"))
        produits = sum(
            (_net(ligne) for ligne in mouvements["comptes"] if ligne["type"] == "produits"), Decimal("0.00")
        )
        charges = sum(
            (_net(ligne) for ligne in mouvements["comptes"] if ligne["type"] == "charges"), Decimal("0.00")
        )
        historique = [
            *historique,
            {
                "mois": un_mois,
                "produits": format(produits.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
                "charges": format(charges.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
                "ecritures": mouvements["ecritures_definitives"],
                "brouillons": mouvements["brouillons"],
            },
        ]
    return historique, None


def _lire_budget(
    plan: Mapping[str, Any], mois_projetes: list[str]
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Le budget actif, ramené aux mois de l'horizon : produits et charges par mois, ou le refus nommé."""
    if not _o._stockage_durable_actif:
        return None, _verdict("REJ-PREVISION-LONGUE-STOCKAGE-NON-DURABLE", "registre durable des budgets requis")
    registre = _o.registre_module.Registre(
        maillons=stockage.maillons(_o._DEPARTEMENT, _NOM_REGISTRE_BUDGETS)
    )
    valide, raison = registre.valider_chaine()
    if not valide:
        return None, _verdict("REJ-PREVISION-LONGUE-CHAINE-INVALIDE", f"budgets déclarés : {raison}")
    etat = budgets.etat_budgets(registre.lire())
    refus = budgets.refus_anomalies(etat)
    if refus is not None:
        return None, _verdict("REJ-PREVISION-LONGUE-CHAINE-INVALIDE", refus.get("detail", "budgets altérés"))
    actif = budgets.budget_actif(etat)
    if actif is None:
        return [], None
    autorises = set(mois_projetes)
    par_mois: dict[str, dict[str, Decimal | None]] = {}
    for ligne in actif["lignes"]:
        if ligne["mois"] not in autorises:
            continue
        fiche = plan["comptes"].get(ligne["compte"])
        if fiche is None or fiche["type"] not in ("produits", "charges"):
            return None, _verdict(
                "REJ-PREVISION-LONGUE-BUDGET-HORS-PLAN",
                f"le budget porte le compte {ligne['compte']!r}, absent du plan courant ou hors produits/charges : "
                "le corriger avant de projeter",
            )
        montant = Decimal(ligne["montant"])
        entree = par_mois.setdefault(ligne["mois"], {"produits": None, "charges": None})
        if fiche["type"] == "produits":
            entree["produits"] = (entree["produits"] or Decimal("0.00")) + montant
        else:
            entree["charges"] = (entree["charges"] or Decimal("0.00")) + montant
    def _texte_ou_none(valeur: Decimal | None) -> str | None:
        return None if valeur is None else format(valeur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")

    return [
        {
            "mois": mois,
            "produits": _texte_ou_none(valeurs["produits"]),
            "charges": _texte_ou_none(valeurs["charges"]),
        }
        for mois, valeurs in sorted(par_mois.items())
    ], None


def _lire_carnet(
    fin_horizon: date,
) -> tuple[list[dict[str, Any]] | None, bool, list[str], dict[str, Any] | None]:
    """Les échéances contractuelles valides jusqu'à `fin_horizon`, plus l'incomplétude et les codes de blocage."""
    if not _o._stockage_durable_actif:
        return None, False, [], _verdict(
            "REJ-PREVISION-LONGUE-STOCKAGE-NON-DURABLE", "registre durable des échéanciers requis"
        )
    registre = _o._registre_echeanciers_contrats()
    assert registre is not None
    valide, raison = registre.valider_chaine()
    if not valide:
        return None, False, [], _verdict(
            "REJ-PREVISION-LONGUE-CHAINE-INVALIDE", f"échéanciers de contrats : {raison}"
        )
    etats, refus = echeanciers_contrats.etats_courants(registre)
    if refus is not None:
        return None, False, [], _verdict(
            "REJ-PREVISION-LONGUE-ECHEANCIER-INVALIDE", refus.get("detail", "échéanciers illisibles")
        )
    contrats = [
        etat for etat in etats.values() if etat.get("type_entree") == echeanciers_contrats.TYPE_ENREGISTRE
    ]
    devis = list(stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_DEVIS_RECUS))
    factures = _o._registre_factures(None)
    valide, raison = factures.valider_chaine()
    if not valide:
        return None, False, [], _verdict(
            "REJ-PREVISION-LONGUE-CHAINE-INVALIDE", f"factures : {raison}"
        )
    flux, _inclus, _sans, incomplet, bloques = echeanciers_contrats.flux_prevision(
        contrats, devis, factures, fin_horizon=fin_horizon
    )
    carnet = []
    for item in flux:
        if item["nature"] != "echeancier_contrat" or item["sens"] != prevision.ENTREE:
            continue
        if item["date"] is None or item["montant"] is None or "contrat_id" not in item:
            continue
        carnet = [
            *carnet,
            {
                "date": item["date"].isoformat(),
                "montant": format(item["montant"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
                "contrat_id": item["contrat_id"],
                "echeance": str(item["id"]).rsplit(":", 1)[-1],
            },
        ]
    codes = sorted({
        str(bloque.get("code"))
        for bloque in bloques
        if isinstance(bloque, Mapping) and bloque.get("code")
    })
    return carnet, bool(incomplet), codes, None


def _contexte() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    refus = _appareil_refuse()
    if refus is not None:
        return None, refus
    ctx, refus = _o._contexte_grand_livre()
    if refus is not None:
        code = refus.get("code")
        if code == "REJ-GL-CHAINE-INVALIDE":
            return None, _verdict("REJ-PREVISION-LONGUE-CHAINE-INVALIDE", refus.get("detail", "grand livre altéré"))
        if code == "REJ-GL-STOCKAGE-NON-DURABLE":
            return None, _verdict("REJ-PREVISION-LONGUE-STOCKAGE-NON-DURABLE", refus.get("detail", "stockage requis"))
        return None, _verdict("REJ-PREVISION-LONGUE-PLAN-INVALIDE", refus.get("detail", "plan comptable illisible"))
    assert ctx is not None
    registre_gl, plan = ctx
    registre_mouvements = _o._registre_mouvements(None)
    valide, raison = registre_mouvements.valider_chaine()
    if not valide:
        return None, _verdict("REJ-PREVISION-LONGUE-CHAINE-INVALIDE", f"mouvements : {raison}")
    return {
        "etat": grand_livre.etat_grand_livre(registre_gl.lire()),
        "plan": plan,
        "registre_gl": registre_gl,
        "registre_mouvements": registre_mouvements,
        "solde": soldes.calculer_solde(registre_mouvements),
    }, None


def _sortie(
    complet: Mapping[str, Any],
    *,
    scenario: Any,
    depart: int,
    limite: int,
    sources: list[dict[str, Any]],
    couverture_extra: Mapping[str, Any],
) -> dict[str, Any]:
    """La page la plus grande qui tient sous le budget de sortie : reçu complet d'abord, compact ensuite."""
    while True:
        vue, verdict = prevision_longue.vue(complet, scenario=scenario, depart=depart, limite=limite)
        if verdict is not None:
            return refuse(verdict)
        assert vue is not None
        vue["couverture"].update(couverture_extra)
        vue["sources"] = sources
        for recu, note in ((complet["recu"], None), (recu_calcul.compacter(complet["recu"]), _NOTE_ENTREES_OMISES)):
            corps = {**vue, "recu": recu, **({"entrees_omises": note} if note else {})}
            reponse = accepte(corps)
            if reponse["accepte"]:
                return reponse
        if limite <= 1:
            return refuse(
                _verdict(
                    "REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE",
                    "la réponse dépasse le budget même avec une ligne : réduire l'horizon ou choisir un scénario",
                )
            )
        limite = max(1, limite // 2)


def prevoir_tresorerie_longue(
    aujourd_hui: str,
    horizon_mois: int,
    scenario: str | None = None,
    depart: int | None = None,
    limite: int | None = None,
    recu_complet: bool | None = None,
) -> dict[str, Any]:
    """`m5_prevoir_tresorerie_longue` (T0) : la projection longue, ou le résumé des scénarios nommés."""
    refus = _appareil_refuse()
    if refus is not None:
        return refuse(refus)
    try:
        jour = date.fromisoformat(aujourd_hui) if isinstance(aujourd_hui, str) and len(aujourd_hui) == 10 else None
    except ValueError:
        jour = None
    if jour is None or jour.isoformat() != aujourd_hui:
        return refuse(_verdict("REJ-PREVISION-LONGUE-DATE-INVALIDE", f"{aujourd_hui!r} : AAAA-MM-JJ exigé"))
    if type(horizon_mois) is not int or horizon_mois not in prevision_longue.HORIZONS:
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-HORIZON-INVALIDE",
            f"horizon_mois : l'un de {', '.join(str(h) for h in sorted(prevision_longue.HORIZONS))}",
        ))
    if recu_complet is not None and type(recu_complet) is not bool:
        return refuse(_verdict("REJ-PREVISION-LONGUE-LIMITE-INVALIDE", "recu_complet : booléen ou null"))
    depart = 0 if depart is None else depart
    limite = _LIMITE_DEFAUT if limite is None else limite
    if type(depart) is not int or depart < 0 or type(limite) is not int or not 1 <= limite <= _LIMITE_MAX:
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-LIMITE-INVALIDE",
            f"depart entier positif ou nul, limite de 1 à {_LIMITE_MAX}",
        ))
    configuration = _configuration()
    if configuration is None:
        return refuse(_verdict("REJ-PREVISION-LONGUE-A-DECLARER", _A_DECLARER))
    nombre_historique = configuration.get("mois_historique") if isinstance(configuration, Mapping) else None
    if type(nombre_historique) is not int or not 3 <= nombre_historique <= 24:
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-MOIS-HISTORIQUE-INVALIDE",
            "mois_historique : entier de 3 à 24 (mois complets avant le mois courant)",
        ))
    if not prevision_longue._fenetre_dates_valide(jour, horizon_mois, nombre_historique):
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-DATE-INVALIDE",
            "la fenêtre historique et l'horizon doivent rester entre 1900-01 et 2999-12",
        ))
    ctx, refus = _contexte()
    if refus is not None:
        return refuse(refus)
    assert ctx is not None
    mois = _mois_projetes(jour, horizon_mois)
    _, fin_horizon = _premier_et_dernier(mois[-1])
    historique, refus = _lire_historique(ctx["etat"], ctx["plan"], _mois_historique(jour, nombre_historique))
    if refus is not None:
        return refuse(refus)
    budget, refus = _lire_budget(ctx["plan"], mois)
    if refus is not None:
        return refuse(refus)
    carnet, incomplet, codes, refus = _lire_carnet(fin_horizon)
    if refus is not None:
        return refuse(refus)
    assert historique is not None and budget is not None and carnet is not None
    complet, verdict = prevision_longue.calculer(
        aujourd_hui=aujourd_hui,
        horizon_mois=horizon_mois,
        solde_initial=format(ctx["solde"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
        historique=historique,
        budget=budget,
        carnet=carnet,
        configuration=configuration,
    )
    if verdict is not None:
        return refuse(verdict)
    assert complet is not None
    if recu_complet is True:
        return accepte({
            "type": "PREVISION_LONGUE",
            "statut": "BROUILLON",
            "aujourd_hui": aujourd_hui,
            "horizon_mois": horizon_mois,
            "recu": complet["recu"],
            "note": "reçu complet pour m5_rejouer_prevision_longue ; aucune ligne de projection rendue",
        })
    sources = [
        _source("mouvements", ctx["registre_mouvements"]),
        _source("grand_livre", ctx["registre_gl"]),
        _source("budgets_declares", _o.registre_module.Registre(
            maillons=stockage.maillons(_o._DEPARTEMENT, _NOM_REGISTRE_BUDGETS)
        )),
        _source("echeanciers_contrats_tresorerie", _o._registre_echeanciers_contrats()),
    ]
    return _sortie(
        complet,
        scenario=scenario,
        depart=depart,
        limite=limite,
        sources=sources,
        couverture_extra={"carnet_incomplet": incomplet, "contrats_bloques": codes},
    )


def rejouer_prevision_longue(recu: dict[str, Any]) -> dict[str, Any]:
    """`m5_rejouer_prevision_longue` (T0) : vérifie un reçu et le REFAIT depuis ses entrées normalisées."""
    refus = _appareil_refuse()
    if refus is not None:
        return refuse(refus)
    valide, raison = recu_calcul.verifier(recu)
    if not valide:
        return refuse(_verdict("REJ-PREVISION-LONGUE-RECU-INVALIDE", raison))
    rejoue, raison = prevision_longue.rejouer(recu)
    if not rejoue and "entrees" in recu:
        return refuse(_verdict("REJ-PREVISION-LONGUE-REJEU-DIFFERENT", raison))
    return accepte({
        "recu_valide": True,
        "rejoue": rejoue,
        "moteur": recu["moteur"],
        "empreinte": recu["empreinte"],
        "note": None if rejoue else raison,
    })


def outils_prevision_longue() -> tuple[Outil, ...]:
    mention = " Porte la mention « À valider auprès d'un comptable (CPA) / professionnel qualifié »."
    brouillon = (
        " BROUILLON : hypothèses DÉCLARÉES, non validées par un CPA ; ni taxes, ni paies, ni dettes, ni impôts, ni "
        "pipeline."
    )
    return (
        Outil(
            nom="m5_prevoir_tresorerie_longue",
            description=(
                "Prévision LONGUE (6/12/24 mois complets) du solde depuis le carnet de contrats daté, le budget "
                "déclaré et la moyenne du grand livre, avec des scénarios NOMMÉS. Hypothèses (croissances "
                "mensuelles, douze coefficients de saisonnalité, délais de paiement) DÉCLARÉES dans le manifeste, "
                "jamais reçues en argument. Priorité par mois : échéance contractuelle, sinon budget, sinon moyenne ; "
                "budget de produits ignoré sous une échéance COMPTÉ. Échéance échue non comptée, flux hors horizon "
                "exclu et dit ; mois historique sans écriture définitive refusé. Sans `scenario`, résumé des "
                "scénarios ; avec, série paginée. `recu_complet` rend le reçu complet rejouable. Lecture pure, portée "
                "d'appareil fermée."
                + brouillon
                + mention
            ),
            parametres={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "aujourd_hui": {
                        "type": "string",
                        "description": "Jour de départ AAAA-MM-JJ (M5 n'a pas d'horloge).",
                    },
                    "horizon_mois": {
                        "type": "integer",
                        "enum": sorted(prevision_longue.HORIZONS),
                        "description": "6, 12 ou 24 mois complets APRÈS le mois courant.",
                    },
                    "scenario": {
                        "type": ["string", "null"],
                        "description": "Nom exact d'un scénario déclaré ; omis : résumé de tous les scénarios.",
                    },
                    "depart": {
                        "type": ["integer", "null"],
                        "minimum": 0,
                        "description": "Première ligne rendue (0 par défaut), pour un scénario choisi.",
                    },
                    "limite": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": _LIMITE_MAX,
                        "description": f"Lignes par page ({_LIMITE_DEFAUT} par défaut, {_LIMITE_MAX} au plus).",
                    },
                    "recu_complet": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Vrai : rend SEULEMENT le reçu complet (avec `entrees`) pour le rejeu hors ligne, sans "
                            "aucune ligne ; la projection normale rend un reçu compact sous le budget."
                        ),
                    },
                },
                "required": ["aujourd_hui", "horizon_mois"],
            },
            fonction=prevoir_tresorerie_longue,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_rejouer_prevision_longue",
            description=(
                "Vérifie un reçu de prévision longue (empreintes SHA-256) et, s'il porte ses entrées, REFAIT le calcul "
                "et compare bit pour bit. Un reçu compact se vérifie sans se rejouer hors ligne. Lecture pure."
                + mention
            ),
            parametres={
                "type": "object",
                "additionalProperties": False,
                "properties": {"recu": {"type": "object", "description": "Le reçu tel que rendu (champ `recu`)."}},
                "required": ["recu"],
            },
            fonction=rejouer_prevision_longue,
            autonomie=Autonomie.T0,
        ),
    )
