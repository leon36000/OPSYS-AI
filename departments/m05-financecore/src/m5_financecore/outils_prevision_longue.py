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
Le calcul charge les lignes de ses registres d'entrée avec un seul SELECT. Cette portée n'inclut pas les fichiers de
configuration/plan comptable ni les autres tables ; elle ne transforme pas en transaction unique les opérations métier
séparées, dont le mouvement d'encaissement et le passage d'une facture à PAYEE.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil

from . import (
    analyse,
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
from .outils_operations import _BUDGET, _appareil_refuse, accepte, refuse

__all__ = ["outils_prevision_longue", "prevoir_tresorerie_longue", "rejouer_prevision_longue"]

_NOM_REGISTRE_BUDGETS = "budgets_declares"
_LIMITE_DEFAUT, _LIMITE_MAX = 12, 24
_NOTE_ENTREES_OMISES = "reçu compact : vérifiable, rejeu hors ligne impossible"
_TRANSPORT_ALGORITHME = "json-canonique-concat-v1"
_PORTEE_RECU = (
    "Le reçu atteste le calcul de ses entrées normalisées et l'intégrité de son contenu ; il ne revalide pas "
    "l'état courant des registres ni la provenance (`sources`) affichée par une projection."
)
_CHAMPS_DEVIS = frozenset({"devis_id", "lead_id", "chantier_id", "lignes", "prix_total", "horodatage_acceptation"})
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
    """La provenance d'un registre : nom, taille et tête de chaîne tronquée. Un registre reçu de M3 n'est pas chaîné :
    sa tête est absente, jamais un identifiant ni un texte libre."""
    taille = registre.taille() if hasattr(registre, "taille") else len(registre)
    tete = registre.tete() if hasattr(registre, "tete") else None
    return {
        "registre": nom,
        "taille": taille,
        **({"tete": tete[:8]} if isinstance(tete, str) else {}),
    }


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
    plan: Mapping[str, Any], mois_projetes: list[str], maillons: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Le budget actif, ramené aux mois de l'horizon : produits et charges par mois, ou le refus nommé."""
    if not _o._stockage_durable_actif:
        return None, _verdict("REJ-PREVISION-LONGUE-STOCKAGE-NON-DURABLE", "registre durable des budgets requis")
    registre = _o.registre_module.Registre(
        maillons=(maillons if maillons is not None
                 else stockage.maillons(_o._DEPARTEMENT, _NOM_REGISTRE_BUDGETS))
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


def _valider_devis(devis: list[Any]) -> dict[str, Any] | None:
    """La même garde fail-closed que `m5_prevoir_tresorerie_contrats` : structure, identifiant et unicité des devis
    reçus de M3. Aucun identifiant ni texte libre ne sort dans le détail du refus."""
    if any(not isinstance(item, dict) or not item.keys() >= _CHAMPS_DEVIS for item in devis):
        return _verdict(
            "REJ-PREVISION-LONGUE-CARNET-INVALIDE",
            "un devis M3 reçu a une structure absente ou invalide : le carnet ne peut pas être projeté",
        )
    if any(not isinstance(item["devis_id"], str) or not item["devis_id"].strip() for item in devis):
        return _verdict(
            "REJ-PREVISION-LONGUE-CARNET-INVALIDE",
            "un devis M3 reçu porte un identifiant invalide : le carnet ne peut pas être projeté",
        )
    identifiants = [item["devis_id"] for item in devis]
    if len(identifiants) != len(set(identifiants)):
        return _verdict(
            "REJ-PREVISION-LONGUE-CARNET-INVALIDE",
            "le registre des devis reçus contient plusieurs événements pour un même devis : "
            "le carnet ne peut pas être projeté",
        )
    return None


def _lire_carnet(
    fin_horizon: date, instantane: Mapping[str, list[dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Les échéances valides jusqu'à `fin_horizon`, la provenance des registres lus et l'incomplétude qualifiée."""
    if not _o._stockage_durable_actif:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-STOCKAGE-NON-DURABLE", "registre durable des échéanciers requis"
        )
    nom_echeanciers = _o._NOM_REGISTRE_ECHEANCIERS_CONTRATS
    nom_devis = _o._NOM_REGISTRE_DEVIS_RECUS
    nom_factures = _o._NOM_REGISTRE_FACTURES
    registre = (
        _o.registre_module.Registre(maillons=instantane[nom_echeanciers])
        if instantane is not None
        else _o._registre_echeanciers_contrats()
    )
    assert registre is not None
    valide, raison = registre.valider_chaine()
    if not valide:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-CHAINE-INVALIDE", f"échéanciers de contrats : {raison}"
        )
    etats, refus = echeanciers_contrats.etats_courants(registre)
    if refus is not None:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-ECHEANCIER-INVALIDE", refus.get("detail", "échéanciers illisibles")
        )
    contrats = [
        etat for etat in etats.values() if etat.get("type_entree") == echeanciers_contrats.TYPE_ENREGISTRE
    ]
    devis = (
        instantane[nom_devis]
        if instantane is not None
        else list(stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_DEVIS_RECUS))
    )
    refus = _valider_devis(devis)
    if refus is not None:
        return None, refus
    factures = (
        _o.registre_module.Registre(maillons=instantane[nom_factures])
        if instantane is not None
        else _o._registre_factures(None)
    )
    valide, raison = factures.valider_chaine()
    if not valide:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-CHAINE-INVALIDE", f"factures : {raison}"
        )
    flux, _inclus, sans_echeancier, incomplet, bloques = echeanciers_contrats.flux_prevision(
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
    incompletude: list[str] = []
    if sans_echeancier:
        incompletude = [
            f"{len(sans_echeancier)} devis accepté(s) sans échéancier contractuel : aucun montant n'est projeté "
            "pour eux (un devis accepté n'est ni un contrat signé ni un encaissement)."
        ]
    if codes:
        incompletude = [
            *incompletude,
            f"{len(codes)} code(s) de contrat bloqué : {', '.join(codes)} ; aucun montant partiel n'est projeté.",
        ]
    return {
        "echeances": carnet,
        "incomplet": bool(incomplet),
        "devis_sans_echeancier": len(sans_echeancier),
        "contrats_bloques": codes,
        "incompletude": incompletude,
        "devis": devis,
        "factures": factures,
    }, None


def _contexte() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    refus = _appareil_refuse()
    if refus is not None:
        return None, refus
    if not _o._stockage_durable_actif:
        ctx, refus = _o._contexte_grand_livre()
        if refus is not None:
            code = refus.get("code")
            if code == "REJ-GL-CHAINE-INVALIDE":
                return None, _verdict("REJ-PREVISION-LONGUE-CHAINE-INVALIDE", refus.get("detail", "grand livre altéré"))
            if code == "REJ-GL-STOCKAGE-NON-DURABLE":
                return None, _verdict(
                    "REJ-PREVISION-LONGUE-STOCKAGE-NON-DURABLE", refus.get("detail", "stockage requis")
                )
            return None, _verdict("REJ-PREVISION-LONGUE-PLAN-INVALIDE", refus.get("detail", "plan comptable illisible"))
        return None, _verdict("REJ-PREVISION-LONGUE-STOCKAGE-NON-DURABLE", "instantané durable requis")
    noms = (
        _o._NOM_REGISTRE_GRAND_LIVRE,
        _o._NOM_REGISTRE_MOUVEMENTS,
        _NOM_REGISTRE_BUDGETS,
        _o._NOM_REGISTRE_ECHEANCIERS_CONTRATS,
        _o._NOM_REGISTRE_DEVIS_RECUS,
        _o._NOM_REGISTRE_FACTURES,
    )
    instantane = stockage.lire_instantane_maillons(_o._DEPARTEMENT, noms)
    registre_gl_snapshot = _o.registre_module.Registre(maillons=instantane[_o._NOM_REGISTRE_GRAND_LIVRE])
    ctx, refus = _o._contexte_grand_livre(registre_cible=registre_gl_snapshot)
    if refus is not None:
        code = refus.get("code")
        if code == "REJ-GL-CHAINE-INVALIDE":
            return None, _verdict("REJ-PREVISION-LONGUE-CHAINE-INVALIDE", refus.get("detail", "grand livre altéré"))
        if code == "REJ-GL-STOCKAGE-NON-DURABLE":
            return None, _verdict("REJ-PREVISION-LONGUE-STOCKAGE-NON-DURABLE", refus.get("detail", "stockage requis"))
        return None, _verdict("REJ-PREVISION-LONGUE-PLAN-INVALIDE", refus.get("detail", "plan comptable illisible"))
    assert ctx is not None
    registre_gl, plan = ctx
    registre_mouvements = _o.registre_module.Registre(maillons=instantane[_o._NOM_REGISTRE_MOUVEMENTS])
    valide, raison = registre_mouvements.valider_chaine()
    if not valide:
        return None, _verdict("REJ-PREVISION-LONGUE-CHAINE-INVALIDE", f"mouvements : {raison}")
    return {
        "etat": grand_livre.etat_grand_livre(registre_gl.lire()),
        "plan": plan,
        "registre_gl": registre_gl,
        "registre_mouvements": registre_mouvements,
        "solde": soldes.calculer_solde(registre_mouvements),
        "instantane": instantane,
    }, None


def _sortie(
    complet: Mapping[str, Any],
    *,
    scenario: Any,
    depart: int,
    limite: int,
    sources: list[dict[str, Any]],
    couverture_extra: Mapping[str, Any],
    transport_pagine: bool = False,
    empreinte_resultat: str | None = None,
    offset_transport: int | None = None,
) -> dict[str, Any]:
    """La page la plus grande qui tient sous le budget de sortie : reçu complet d'abord, compact ensuite.

    En mode résumé (`scenario is None`), la page est réduite d'un scénario à la fois : chaque page rend son total et
    son `prochain_depart`, donc aucun scénario n'est perdu ni tronqué. En mode détaillé, la pagination des lignes
    garde sa réduction par moitié, déjà contractuelle.
    """
    resume = scenario is None
    while True:
        vue, verdict = prevision_longue.vue(complet, scenario=scenario, depart=depart, limite=limite)
        if verdict is not None:
            return refuse(verdict)
        assert vue is not None
        vue["couverture"].update(couverture_extra)
        vue["sources"] = sources
        if transport_pagine:
            # Reprendre exactement la visibilité du chemin public existant : reçu complet s'il tient,
            # compact sinon. Le mode transport ne révèle jamais des entrées que le budget aurait masquées.
            for recu, note in ((complet["recu"], None), (recu_calcul.compacter(complet["recu"]), _NOTE_ENTREES_OMISES)):
                corps_transport = analyse.avec_mention_comptable(
                    {**vue, "recu": recu, **({"entrees_omises": note} if note else {})}
                )
                if accepte(corps_transport)["accepte"]:
                    return _transport_pagine(
                        corps_transport, empreinte_resultat=empreinte_resultat, offset=offset_transport
                    )
            corps_transport = analyse.avec_mention_comptable(
                {**vue, "recu": recu_calcul.compacter(complet["recu"]), "entrees_omises": _NOTE_ENTREES_OMISES}
            )
            return _transport_pagine(
                corps_transport, empreinte_resultat=empreinte_resultat, offset=offset_transport
            )
        for recu, note in ((complet["recu"], None), (recu_calcul.compacter(complet["recu"]), _NOTE_ENTREES_OMISES)):
            corps = {**vue, "recu": recu, **({"entrees_omises": note} if note else {})}
            reponse = accepte(corps)
            if reponse["accepte"]:
                return reponse
        if limite <= 1:
            if resume:
                return refuse(
                    _verdict(
                        "REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE",
                        "la réponse dépasse le budget même avec un seul résumé de scénario : réduire l'horizon ou "
                        "le nombre de scénarios déclarés ; aucune page partielle n'est rendue",
                    )
                )
            return refuse(
                _verdict(
                    "REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE",
                    "la réponse dépasse le budget même avec une ligne : réduire l'horizon ou choisir un scénario",
                )
            )
        limite = limite - 1 if resume else max(1, limite // 2)


def _transport_pagine(
    corps: Mapping[str, Any], *, empreinte_resultat: str | None, offset: int | None
) -> dict[str, Any]:
    """Découpe sans perte le JSON complet sous le budget; empreinte de cohérence, pas d'authenticité."""
    texte = json.dumps(corps, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    empreinte = hashlib.sha256(texte.encode("utf-8")).hexdigest()
    position = 0 if offset is None else offset
    if empreinte_resultat is not None and empreinte_resultat != empreinte:
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE",
            "le résultat recalculé a changé; recommencer le transport depuis sa première page",
        ))
    if position >= len(texte):
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE", "offset_transport hors du résultat calculé"
        ))
    gauche, droite = 1, len(texte) - position
    meilleure: dict[str, Any] | None = None
    while gauche <= droite:
        taille = (gauche + droite) // 2
        fin = position + taille
        enveloppe = {
            "transport": _TRANSPORT_ALGORITHME,
            "empreinte_resultat": empreinte,
            "longueur_caracteres": len(texte),
            "offset_transport": position,
            "fragment": texte[position:fin],
            "prochain_offset": fin if fin < len(texte) else None,
            "note_empreinte": "cohérence de fragments uniquement; aucune preuve d'authenticité",
        }
        reponse = accepte(enveloppe)
        if reponse["accepte"] and len(json.dumps(reponse, ensure_ascii=False, default=str)) <= _BUDGET:
            meilleure = reponse
            gauche = taille + 1
        else:
            droite = taille - 1
    if meilleure is None:
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE",
            "l'enveloppe de transport ne tient pas sous le budget de sortie",
        ))
    return meilleure


def prevoir_tresorerie_longue(
    aujourd_hui: str,
    horizon_mois: int,
    scenario: str | None = None,
    depart: int | None = None,
    limite: int | None = None,
    recu_complet: bool | None = None,
    transport_pagine: bool | None = None,
    empreinte_resultat: str | None = None,
    offset_transport: int | None = None,
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
    if transport_pagine is not None and type(transport_pagine) is not bool:
        return refuse(_verdict("REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE", "transport_pagine : booléen ou null"))
    if transport_pagine is True:
        premiere = empreinte_resultat is None and offset_transport in (None, 0)
        suite = (
            isinstance(empreinte_resultat, str)
            and re.fullmatch(r"[0-9a-f]{64}", empreinte_resultat) is not None
            and type(offset_transport) is int
            and offset_transport > 0
        )
        if not (premiere or suite):
            return refuse(_verdict(
                "REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE",
                "première page sans curseur, ou suite avec empreinte SHA-256 et offset positif requis",
            ))
    elif empreinte_resultat is not None or offset_transport is not None:
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE",
            "empreinte_resultat et offset_transport exigent transport_pagine=true",
        ))
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
    budget, refus = _lire_budget(ctx["plan"], mois, ctx["instantane"][_NOM_REGISTRE_BUDGETS])
    if refus is not None:
        return refuse(refus)
    carnet, refus = _lire_carnet(fin_horizon, ctx["instantane"])
    if refus is not None:
        return refuse(refus)
    assert historique is not None and budget is not None and carnet is not None
    complet, verdict = prevision_longue.calculer(
        aujourd_hui=aujourd_hui,
        horizon_mois=horizon_mois,
        solde_initial=format(ctx["solde"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
        historique=historique,
        budget=budget,
        carnet=carnet["echeances"],
        configuration=configuration,
    )
    if verdict is not None:
        return refuse(verdict)
    assert complet is not None
    if recu_complet is True:
        # Le mode reçu complet ne rend aucune ligne, mais il valide quand même le scénario demandé : un nom inconnu
        # est refusé, jamais ignoré. Un scénario valide ne change pas le reçu (il n'y a pas de lignes à filtrer).
        _, verdict = prevision_longue.vue(complet, scenario=scenario, depart=depart, limite=limite)
        if verdict is not None:
            return refuse(verdict)
        corps_recu = {
            "type": "PREVISION_LONGUE",
            "statut": "BROUILLON",
            "aujourd_hui": aujourd_hui,
            "horizon_mois": horizon_mois,
            "recu": complet["recu"],
            "portee": _PORTEE_RECU,
            "note": "reçu complet pour m5_rejouer_prevision_longue ; aucune ligne de projection rendue",
        }
        if transport_pagine is True:
            return _transport_pagine(
                analyse.avec_mention_comptable(corps_recu),
                empreinte_resultat=empreinte_resultat,
                offset=offset_transport,
            )
        reponse = accepte(corps_recu)
        if reponse["accepte"]:
            return reponse
        # Un reçu complet ne se tronque jamais : s'il ne tient pas sous le budget, on refuse avec le code de CE
        # catalogue, jamais avec un code d'un autre outil.
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE",
            "le reçu complet dépasse le budget de réponse même sans ligne de projection : aucune troncature, "
            "réduire l'horizon ou le nombre de scénarios",
        ))
    sources = [
        _source("mouvements", ctx["registre_mouvements"]),
        _source("grand_livre", ctx["registre_gl"]),
        _source("budgets_declares", _o.registre_module.Registre(
            maillons=ctx["instantane"][_NOM_REGISTRE_BUDGETS]
        )),
        _source("echeanciers_contrats_tresorerie", _o.registre_module.Registre(
            maillons=ctx["instantane"][_o._NOM_REGISTRE_ECHEANCIERS_CONTRATS]
        )),
        _source("devis_recus", carnet["devis"]),
        _source("factures", carnet["factures"]),
    ]
    return _sortie(
        complet,
        scenario=scenario,
        depart=depart,
        limite=limite,
        sources=sources,
        transport_pagine=transport_pagine is True,
        empreinte_resultat=empreinte_resultat,
        offset_transport=offset_transport,
        couverture_extra={
            "carnet_incomplet": carnet["incomplet"],
            **({"contrats_bloques": carnet["contrats_bloques"]} if carnet["contrats_bloques"] else {}),
            **({"devis_sans_echeancier": carnet["devis_sans_echeancier"]}
               if carnet["devis_sans_echeancier"] else {}),
            **({"incompletude": carnet["incompletude"]} if carnet["incompletude"] else {}),
        },
    )


def rejouer_prevision_longue(recu: dict[str, Any]) -> dict[str, Any]:
    """`m5_rejouer_prevision_longue` (T0) : vérifie un reçu et le REFAIT depuis ses entrées normalisées."""
    refus = _appareil_refuse()
    if refus is not None:
        return refuse(refus)
    valide, raison = recu_calcul.verifier(recu)
    if not valide:
        return refuse(_verdict("REJ-PREVISION-LONGUE-RECU-INVALIDE", raison))
    # Le vérificateur générique ne connaît que le format : l'outil de CE moteur exige explicitement son moteur et sa
    # version avant de présenter le reçu comme valide pour lui. Un reçu compact du même moteur reste vérifiable.
    if recu.get("moteur") != prevision_longue.MOTEUR or recu.get("version_moteur") != prevision_longue.VERSION:
        return refuse(_verdict(
            "REJ-PREVISION-LONGUE-RECU-INVALIDE",
            f"reçu du moteur {recu.get('moteur')!r} version {recu.get('version_moteur')!r} : "
            f"attendu {prevision_longue.MOTEUR!r} version {prevision_longue.VERSION!r}",
        ))
    rejoue, raison = prevision_longue.rejouer(recu)
    if not rejoue and "entrees" in recu:
        return refuse(_verdict("REJ-PREVISION-LONGUE-REJEU-DIFFERENT", raison))
    return accepte({
        "recu_valide": True,
        "rejoue": rejoue,
        "moteur": recu["moteur"],
        "version_moteur": recu["version_moteur"],
        "empreinte": recu["empreinte"],
        "note": None if rejoue else raison,
        "portee": _PORTEE_RECU,
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
                "exclu et dit ; mois historique sans écriture définitive refusé. Sans `scenario`, résumé PAGINÉ des "
                "scénarios (`depart`, `limite`, total et suite) ; avec, série de lignes paginée. `recu_complet` rend "
                "le reçu complet rejouable. Transport facultatif : fragments sous budget, reprise par empreinte. "
                "Lecture pure, portée d'appareil fermée."
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
                        "description": "Nom exact d'un scénario déclaré ; omis : résumé paginé de tous les scénarios.",
                    },
                    "depart": {
                        "type": ["integer", "null"],
                        "minimum": 0,
                        "description": (
                            "Première ligne du scénario choisi, ou premier résumé en mode résumé (0 par défaut)."
                        ),
                    },
                    "limite": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": _LIMITE_MAX,
                        "description": (
                            f"Lignes par page du scénario choisi, ou résumés en mode résumé ({_LIMITE_DEFAUT} "
                            f"par défaut, {_LIMITE_MAX} au plus) ; la page peut être réduite pour tenir sous le "
                            "budget, et `scenarios_affiches` avec `prochain_depart` le disent."
                        ),
                    },
                    "recu_complet": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Vrai : rend SEULEMENT le reçu complet (avec `entrees`) pour le rejeu hors ligne, sans "
                            "aucune ligne ; la projection normale rend un reçu compact sous le budget."
                        ),
                    },
                    "transport_pagine": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Mode additif de fragments JSON canoniques; réassembler fragment par fragment. La suite "
                            "exige l'empreinte et l'offset retournés; l'empreinte ne prouve pas l'authenticité."
                        ),
                    },
                    "empreinte_resultat": {
                        "type": ["string", "null"],
                        "pattern": "^[0-9a-f]{64}$",
                        "description": "Empreinte renvoyée par la page précédente (cohérence, non-authenticité).",
                    },
                    "offset_transport": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "description": "prochain_offset de la page précédente; absent seulement sur la première page.",
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
