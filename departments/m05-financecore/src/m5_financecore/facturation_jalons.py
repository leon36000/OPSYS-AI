"""Facturation par jalons et acomptes (M5-FACT-1) : plan de facturation déterministe, factures de jalon, numérotation
séquentielle sans trou ni doublon, échéance.

Module pur (même règle que `facturation.py` et `grand_livre.py`) : aucun import d'`opsys`, aucune horloge, aucun accès
réseau. Il reçoit des registres déjà construits (duck-typés : `ajouter`, `lire`, `tete`) que l'adaptateur
(`outils_facturation.py`) adosse aux registres durables DÉDIÉS `plans_facturation` et `numerotation_factures`
(append-only, hash-chaînés ; aucune migration, comme le grand livre). Il ne nomme jamais le registre des mouvements :
facturer ne fait bouger aucun argent.

Ce que ce module décide, et ce qu'il laisse au propriétaire.

* Le PLAN est DÉCLARÉ par une personne (N3, `m5_declarer_plan_facturation`) : jalons, déclencheurs, pourcentages OU
  montants. Rien n'est inventé : sans jalons, sans somme qui tombe juste ou sans délai de paiement déclaré, le refus dit
  QUOI déclarer. La somme des montants avant taxes des jalons égale le prix du devis au cent, exactement.
* Le code CALCULE, jamais un modèle : en mode « pourcentage », chaque jalon sauf le dernier vaut
  `prix × pourcentage ÷ 100`, arrondi au cent (ROUND_HALF_UP, comme les lignes de facture) ; le DERNIER jalon (le solde)
  vaut `prix − somme des précédents`, donc la somme tombe toujours juste ; l'écart d'arrondi qu'il absorbe est écrit au
  plan. Les taxes (TPS/TVQ) de chaque facture sont celles du moteur fiscal existant (`taxes.py`, taux versionnés et
  sourcés) : aucun taux n'est écrit ici. Les taxes arrondies facture par facture peuvent différer de quelques cents de
  celles du total ; l'écart est rendu tel quel (`resume_plan`), à valider auprès d'un comptable (CPA).
* La facture d'un jalon est un BROUILLON (`facturation.creer_facture_brouillon`, rattachement au plan) ; son ENVOI
  est la
  décision humaine N4 du socle, jamais ce module. Le numéro et l'échéance sont fixés à l'ÉMISSION, dans le même maillon
  que le statut.
* La NUMÉROTATION est un registre append-only : le rang du maillon EST la suite (premier numéro déclaré + rang), donc la
  clé primaire du registre interdit deux fois le même numéro, et aucun trou n'est possible tant que chaque attribution
  s'écrit dans la transaction de l'émission. Attribuer deux fois à la même facture rend le même numéro (reprise après
  panne). `verifier_numerotation` relit la suite et dit tout trou ou doublon.

Toute sortie d'avis comptable ou fiscal : « À valider auprès d'un comptable (CPA) / professionnel qualifié ».
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

from . import encodage, facturation, taxes, verdicts_facturation

__all__ = [
    "ajouter_plan",
    "attribuer_numero",
    "construire_plan",
    "etat_plans",
    "lire_conditions_paiement",
    "lire_numerotation",
    "plan_actif_pour_devis",
    "preparer_facture_jalon",
    "resume_plan",
    "revoquer_plan",
    "verifier_numerotation",
]

_CENT = Decimal("0.01")
_CENT_ZERO = Decimal("0.00")
_CENT_POURCENT = Decimal("100")
_MONTANT_MAX = Decimal("999999999999.99")
_VERSION_REGLES = "m5.plan_facturation.v1"
_JALONS_MIN = 2
_JALONS_MAX = 12
_DELAI_MAX = 365
_DECIMALES_POURCENTAGE = 4
_LIBELLE_MAX = 80
_MOTIF_MAX = 300
_DECLENCHEURS = {"acceptation": 0, "chantier": 1, "fin_travaux": 2}
_CHAMPS_JALON = frozenset({"libelle", "declencheur", "pourcentage", "montant_avant_taxes", "delai_paiement_jours"})
_PREFIXE = re.compile(r"^[A-Za-z0-9_/-]{0,12}$")
_CONTROLES = re.compile(r"[\x00-\x1f\x7f]")
_TYPE_PLAN = "plan_facturation_declare"
_TYPE_REVOCATION = "plan_facturation_revoque"
_TYPE_NUMERO = "numero_facture_attribue"
_A_DECLARER_NUMEROTATION = (
    "déclarer configuration.facturation.numerotation : prefixe (0 à 12 caractères : lettres, chiffres, _ / -), "
    "premier_numero (entier de 1 à 999999999 : le numéro de la PREMIÈRE facture émise par OPSYS, à reprendre de la "
    "dernière facture de l'ancien système + 1) et largeur (entier de 1 à 12 : nombre de chiffres, zéros devant) — "
    "décision du propriétaire, jamais supposée"
)
_A_DECLARER_CONDITIONS = (
    "déclarer configuration.facturation.conditions_paiement.delai_jours (entier de 0 à 365 : jours entre l'émission "
    "et l'échéance ; 0 = payable à la réception), ou delai_paiement_jours sur CHAQUE jalon du plan — décision du "
    "propriétaire, jamais supposée"
)


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_facturation.construire_verdict(code, detail=detail)


def _texte_ligne(valeur: Any, maximum: int) -> str | None:
    """Une ligne de texte libre : non vide, une seule ligne, sans caractère de contrôle, bornée. Sinon `None`."""
    if not isinstance(valeur, str):
        return None
    propre = valeur.strip()
    if not propre or len(propre) > maximum or _CONTROLES.search(propre):
        return None
    return propre


def _decimal_texte(valeur: Any, *, decimales: int) -> Decimal | None:
    """Un décimal fini depuis un TEXTE (jamais un nombre JSON), d'au plus `decimales` décimales."""
    if isinstance(valeur, bool) or not isinstance(valeur, str):
        return None
    try:
        decimal = Decimal(valeur.strip())
    except InvalidOperation:
        return None
    if not decimal.is_finite() or decimal.as_tuple().exponent < -decimales:
        return None
    return decimal


def _txt(valeur: Decimal) -> str:
    return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


# --------------------------------------------------------------------------------------------- configuration déclarée
def lire_conditions_paiement(brut: Any) -> tuple[dict[str, int] | None, dict[str, str] | None]:
    """Les conditions de paiement déclarées par le propriétaire (`configuration.facturation.conditions_paiement`) : le
    nombre de jours entre l'émission et l'échéance. Absentes ou mal formées : refus qui dit quoi déclarer."""
    if not isinstance(brut, Mapping) or set(brut) != {"delai_jours"}:
        return None, _verdict("REJ-CONDITIONS-A-DECLARER", _A_DECLARER_CONDITIONS)
    delai = brut["delai_jours"]
    if type(delai) is not int or not 0 <= delai <= _DELAI_MAX:
        return None, _verdict("REJ-CONDITIONS-A-DECLARER", "delai_jours : entier de 0 à 365. " + _A_DECLARER_CONDITIONS)
    return {"delai_jours": delai}, None


def lire_numerotation(brut: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """La numérotation déclarée (`configuration.facturation.numerotation`) : préfixe, premier numéro, largeur. Absente
    ou mal formée : refus qui dit quoi déclarer ; aucun numéro n'est jamais supposé."""
    if not isinstance(brut, Mapping) or set(brut) != {"prefixe", "premier_numero", "largeur"}:
        return None, _verdict("REJ-NUMEROTATION-A-DECLARER", _A_DECLARER_NUMEROTATION)
    prefixe, premier, largeur = brut["prefixe"], brut["premier_numero"], brut["largeur"]
    if not isinstance(prefixe, str) or not _PREFIXE.fullmatch(prefixe):
        return None, _verdict("REJ-NUMEROTATION-A-DECLARER", "prefixe invalide. " + _A_DECLARER_NUMEROTATION)
    if type(premier) is not int or not 1 <= premier <= 999999999:
        return None, _verdict("REJ-NUMEROTATION-A-DECLARER", "premier_numero invalide. " + _A_DECLARER_NUMEROTATION)
    if type(largeur) is not int or not 1 <= largeur <= 12:
        return None, _verdict("REJ-NUMEROTATION-A-DECLARER", "largeur invalide. " + _A_DECLARER_NUMEROTATION)
    return {"prefixe": prefixe, "premier_numero": premier, "largeur": largeur}, None


# --------------------------------------------------------------------------------------------------------------- plan
def identifiant_plan(devis_id: str, version: int) -> str:
    """L'identifiant déterministe du plan d'un devis, à sa `version` (un plan révoqué est remplacé par la version
    suivante) : même devis et même version, même identifiant, sur toute machine."""
    return "pf-" + encodage.empreinte("m5.plan_facturation", devis_id)[:16] + f"-v{version}"


def identifiant_facture_jalon(plan_id: str, rang: int) -> str:
    return f"fac-{plan_id}-J{rang}"


def _lire_jalon(brut: Any, index: int) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if not isinstance(brut, Mapping) or not set(brut) <= _CHAMPS_JALON:
        return None, _verdict(
            "REJ-PLAN-JALONS-INVALIDES", f"jalon {index} : structure invalide (clés permises {sorted(_CHAMPS_JALON)})"
        )
    libelle = _texte_ligne(brut.get("libelle"), _LIBELLE_MAX)
    if libelle is None:
        return None, _verdict("REJ-PLAN-ENTREE-INVALIDE", f"jalon {index} : libelle d'une ligne, 80 caractères au plus")
    declencheur = brut.get("declencheur")
    if declencheur not in _DECLENCHEURS:
        return None, _verdict(
            "REJ-PLAN-ENTREE-INVALIDE",
            f"jalon {index} : declencheur parmi {sorted(_DECLENCHEURS, key=_DECLENCHEURS.get)}",
        )
    pourcentage, montant = brut.get("pourcentage"), brut.get("montant_avant_taxes")
    if (pourcentage is None) == (montant is None):
        return None, _verdict(
            "REJ-PLAN-JALON-MONTANT-AMBIGU",
            f"jalon {index} : déclarer UN SEUL de pourcentage ou montant_avant_taxes (texte décimal)",
        )
    delai = brut.get("delai_paiement_jours")
    if delai is not None and (type(delai) is not int or not 0 <= delai <= _DELAI_MAX):
        return None, _verdict("REJ-PLAN-ENTREE-INVALIDE", f"jalon {index} : delai_paiement_jours entier de 0 à 365")
    return {
        "libelle": libelle,
        "declencheur": declencheur,
        "pourcentage": pourcentage,
        "montant": montant,
        "delai": delai,
    }, None


def construire_plan(
    devis_recu: Mapping[str, Any],
    jalons_bruts: Any,
    *,
    chantier_declare: Any,
    client_id: str,
    version: int,
    delai_defaut: int | None,
    humain: Mapping[str, str],
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le corps du plan de facturation d'un devis ACCEPTÉ, calculé, ou le refus qui dit quoi déclarer. Aucune écriture.

    `devis_recu` : le devis accepté tel que M5 l'a reçu de M3 (`devis_recus.py`) ; son `prix_total` (avant taxes) est le
    total que les jalons doivent égaler au cent. `chantier_declare` : le chantier, SEULEMENT si le devis n'en porte pas
    encore (jamais inventé). `delai_defaut` : les conditions de paiement déclarées (ou `None`)."""
    devis_id = devis_recu.get("devis_id")
    total = _decimal_texte(devis_recu.get("prix_total"), decimales=2)
    if not isinstance(devis_id, str) or total is None or total < _CENT or total > _MONTANT_MAX:
        return None, _verdict("REJ-PLAN-ENTREE-INVALIDE", "devis accepté reçu sans prix_total lisible au cent")
    chantier_devis = devis_recu.get("chantier_id")
    chantier_devis = chantier_devis.strip() if isinstance(chantier_devis, str) else ""
    chantier_texte = chantier_declare.strip() if isinstance(chantier_declare, str) else ""
    if chantier_devis and chantier_texte and chantier_devis != chantier_texte:
        return None, _verdict(
            "REJ-PLAN-CHANTIER-A-DECLARER", "le devis porte déjà son chantier : ne pas en déclarer un autre"
        )
    chantier_id = chantier_devis or chantier_texte
    if not chantier_id or len(chantier_id) > 128 or _CONTROLES.search(chantier_id):
        return None, _verdict(
            "REJ-PLAN-CHANTIER-A-DECLARER",
            "le devis accepté n'a pas encore de chantier : déclarer chantier_id (jamais inventé)",
        )

    if not isinstance(jalons_bruts, (list, tuple)) or not _JALONS_MIN <= len(jalons_bruts) <= _JALONS_MAX:
        return None, _verdict(
            "REJ-PLAN-JALONS-INVALIDES", f"déclarer de {_JALONS_MIN} à {_JALONS_MAX} jalons (acompte, chantier, solde)"
        )
    lus: list[dict[str, Any]] = []
    for index, brut in enumerate(jalons_bruts, start=1):
        jalon, refus = _lire_jalon(brut, index)
        if refus is not None:
            return None, refus
        lus.append(jalon)
    ordres = [_DECLENCHEURS[j["declencheur"]] for j in lus]
    if ordres != sorted(ordres) or ordres.count(_DECLENCHEURS["fin_travaux"]) > 1:
        return None, _verdict(
            "REJ-PLAN-JALONS-INVALIDES",
            "ordre des jalons : acompte(s) à l'acceptation, jalon(s) de chantier, puis au plus un solde à la fin des "
            "travaux, dans cet ordre",
        )

    mode_pourcentage = lus[0]["pourcentage"] is not None
    if any((j["pourcentage"] is not None) != mode_pourcentage for j in lus):
        return None, _verdict(
            "REJ-PLAN-MODE-MIXTE", "tous les jalons en pourcentage, ou tous en montant, pas un mélange"
        )

    montants: list[Decimal] = []
    pourcentages: list[Decimal | None] = [None] * len(lus)
    ecart_arrondi: Decimal | None = None
    with localcontext() as contexte:
        contexte.prec = 60
        if mode_pourcentage:
            for index, jalon in enumerate(lus):
                pourcentage = _decimal_texte(jalon["pourcentage"], decimales=_DECIMALES_POURCENTAGE)
                if pourcentage is None or not Decimal("0") < pourcentage <= _CENT_POURCENT:
                    return None, _verdict(
                        "REJ-PLAN-ENTREE-INVALIDE",
                        f"jalon {index + 1} : pourcentage en texte décimal, plus de 0 et au plus 100, "
                        f"{_DECIMALES_POURCENTAGE} décimales au plus",
                    )
                pourcentages[index] = pourcentage
            somme_pourcentages = sum(pourcentages, Decimal("0"))
            if somme_pourcentages != _CENT_POURCENT:
                return None, _verdict(
                    "REJ-PLAN-SOMME-POURCENTAGES",
                    f"les pourcentages totalisent {format(somme_pourcentages, 'f')} au lieu de 100",
                )
            for pourcentage in pourcentages[:-1]:
                montants.append((total * pourcentage / _CENT_POURCENT).quantize(_CENT, rounding=ROUND_HALF_UP))
            solde = total - sum(montants, Decimal("0"))
            exact_dernier = total * pourcentages[-1] / _CENT_POURCENT
            ecart_arrondi = solde - exact_dernier
            montants.append(solde)
        else:
            for index, jalon in enumerate(lus):
                montant = _decimal_texte(jalon["montant"], decimales=2)
                if montant is None or montant > _MONTANT_MAX:
                    return None, _verdict(
                        "REJ-PLAN-ENTREE-INVALIDE", f"jalon {index + 1} : montant_avant_taxes en texte décimal au cent"
                    )
                montants.append(montant)
            if any(m < _CENT for m in montants):
                return None, _verdict("REJ-PLAN-JALON-NUL", "chaque jalon vaut au moins 0.01 $")
            somme = sum(montants, Decimal("0"))
            if somme != total:
                return None, _verdict(
                    "REJ-PLAN-SOMME-INCORRECTE",
                    f"les jalons totalisent {format(somme, 'f')} $ au lieu de {format(total, 'f')} $ "
                    f"(écart {format(somme - total, 'f')} $) : la somme doit tomber juste au cent",
                )
    if any(m < _CENT for m in montants):
        return None, _verdict("REJ-PLAN-JALON-NUL", "un jalon vaudrait moins d'un cent : revoir les pourcentages")

    plan_id = identifiant_plan(devis_id, version)
    jalons: list[dict[str, Any]] = []
    sans_delai: list[int] = []
    for index, (jalon, montant) in enumerate(zip(lus, montants, strict=True), start=1):
        delai = jalon["delai"] if jalon["delai"] is not None else delai_defaut
        if delai is None:
            sans_delai.append(index)
            continue
        entree = {
            "rang": index,
            "jalon_id": f"{plan_id}-J{index}",
            "libelle": jalon["libelle"],
            "declencheur": jalon["declencheur"],
            "pourcentage": None if pourcentages[index - 1] is None else format(pourcentages[index - 1], "f"),
            "montant_avant_taxes": _txt(montant),
            "delai_paiement_jours": delai,
            "delai_source": "jalon" if jalon["delai"] is not None else "conditions_paiement",
        }
        if index == len(lus) and ecart_arrondi is not None:
            entree["ecart_arrondi_absorbe"] = format(ecart_arrondi, "f")
        jalons.append(entree)
    if sans_delai:
        return None, _verdict(
            "REJ-PLAN-DELAI-A-DECLARER",
            f"jalon(s) {sans_delai} sans délai de paiement : " + _A_DECLARER_CONDITIONS,
        )
    corps = {
        "plan_id": plan_id,
        "version": version,
        "devis_id": devis_id,
        "chantier_id": chantier_id,
        "client_id": client_id,
        "devise": "CAD",
        "total_avant_taxes": _txt(total),
        "mode": "pourcentage" if mode_pourcentage else "montant",
        "jalons": jalons,
        "declare_par": {"par": humain["par"], "role": humain["role"]},
        "version_regles": _VERSION_REGLES,
    }
    corps["empreinte_plan"] = encodage.empreinte("m5.plan_facturation.contenu.v1", corps)
    return corps, None


def signature_plan(corps: Mapping[str, Any]) -> str:
    """Ce qui fait le CONTENU d'un plan, sans son identifiant, sa version ni la personne : deux déclarations de même
    signature sont le même plan (rejouer une déclaration ne crée rien)."""
    return encodage.empreinte(
        "m5.plan_facturation.signature.v1",
        corps["devis_id"],
        corps["chantier_id"],
        corps["total_avant_taxes"],
        corps["mode"],
        [
            (j["libelle"], j["declencheur"], j["pourcentage"], j["montant_avant_taxes"], j["delai_paiement_jours"])
            for j in corps["jalons"]
        ],
    )


def etat_plans(maillons: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """L'état relu du registre des plans : `plans` (identifiant -> plan, avec `statut` ACTIF ou REVOQUE et sa
    `revocation`), `par_devis` (identifiants dans l'ordre d'écriture) et `anomalies` (maillon étranger, contenu altéré,
    révocation d'un plan inconnu, deux plans actifs pour un devis). Une anomalie fait refuser toute lecture."""
    plans: dict[str, dict[str, Any]] = {}
    par_devis: dict[str, list[str]] = {}
    anomalies: list[str] = []
    for maillon in maillons:
        type_entree = maillon.get("type_entree") if isinstance(maillon, Mapping) else None
        try:
            if type_entree == _TYPE_PLAN:
                corps = {
                    k: v
                    for k, v in maillon.items()
                    if k not in ("type_entree", "ligne_id", "precedent_ligne_id", "horodatage")
                }
                attendu = encodage.empreinte(
                    "m5.plan_facturation.contenu.v1", {k: v for k, v in corps.items() if k != "empreinte_plan"}
                )
                plan_id = maillon["plan_id"]
                if maillon["empreinte_plan"] != attendu:
                    anomalies.append(f"plan {plan_id} : contenu altéré")
                elif plan_id in plans:
                    anomalies.append(f"plan {plan_id} déclaré deux fois")
                else:
                    plans[plan_id] = {**dict(maillon), "statut": "ACTIF", "revocation": None}
                    par_devis.setdefault(maillon["devis_id"], []).append(plan_id)
            elif type_entree == _TYPE_REVOCATION:
                plan = plans.get(maillon["plan_id"])
                if plan is None or plan["statut"] != "ACTIF":
                    anomalies.append(f"révocation du plan {maillon.get('plan_id')!r} sans plan actif")
                else:
                    plan["statut"] = "REVOQUE"
                    plan["revocation"] = dict(maillon)
            else:
                anomalies.append(f"maillon de type {type_entree!r} étranger aux plans de facturation")
        except (KeyError, TypeError):
            anomalies.append(f"maillon {type_entree!r} illisible")
    for devis_id, identifiants in par_devis.items():
        if sum(1 for i in identifiants if plans[i]["statut"] == "ACTIF") > 1:
            anomalies.append(f"devis {devis_id!r} : plusieurs plans actifs")
    return {"plans": plans, "par_devis": par_devis, "anomalies": anomalies}


def refus_anomalies(etat: Mapping[str, Any]) -> dict[str, str] | None:
    if etat["anomalies"]:
        return _verdict("REJ-PLAN-CHAINE-INVALIDE", "; ".join(etat["anomalies"][:3]))
    return None


def plan_actif_pour_devis(etat: Mapping[str, Any], devis_id: str) -> dict[str, Any] | None:
    for plan_id in etat["par_devis"].get(devis_id, ()):
        if etat["plans"][plan_id]["statut"] == "ACTIF":
            return etat["plans"][plan_id]
    return None


def ajouter_plan(
    registre_plans: Any, etat: Mapping[str, Any], corps: Mapping[str, Any], horodatage: str
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Écrit le plan, ou le reconnaît s'il est déjà actif avec la même signature (rien n'est écrit). Un autre plan actif
    pour le même devis est un refus : le révoquer d'abord (seulement s'il n'a aucune facture)."""
    actif = plan_actif_pour_devis(etat, corps["devis_id"])
    if actif is not None:
        if signature_plan(actif) == signature_plan(corps):
            return {"statut": "deja", "plan": actif}, None
        return None, _verdict(
            "REJ-PLAN-DEJA-DECLARE",
            f"le devis porte déjà le plan actif {actif['plan_id']} (contenu différent) : le révoquer d'abord "
            "(possible seulement tant qu'aucune facture n'en est issue)",
        )
    ligne_id = registre_plans.ajouter({"type_entree": _TYPE_PLAN, **dict(corps), "horodatage": horodatage})
    for maillon in registre_plans.lire():
        if maillon["ligne_id"] == ligne_id:
            return {"statut": "ecrit", "plan": {**maillon, "statut": "ACTIF", "revocation": None}}, None
    raise RuntimeError("maillon du plan ajouté introuvable")


def revoquer_plan(
    registre_plans: Any,
    etat: Mapping[str, Any],
    plan_id: str,
    motif: Any,
    humain: Mapping[str, str],
    etats_factures: Iterable[Mapping[str, Any]],
    horodatage: str,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Révoque un plan qui n'a donné AUCUNE facture (pas même un brouillon : un brouillon ne s'annule pas encore)."""
    plan = etat["plans"].get(plan_id)
    if plan is None:
        return None, _verdict("REJ-PLAN-INTROUVABLE", f"plan inconnu : {plan_id!r}")
    if plan["statut"] != "ACTIF":
        return None, _verdict("REJ-PLAN-DEJA-REVOQUE", f"le plan {plan_id} est déjà révoqué")
    motif_propre = _texte_ligne(motif, _MOTIF_MAX)
    if motif_propre is None:
        return None, _verdict("REJ-PLAN-ENTREE-INVALIDE", "motif d'une ligne exigé (300 caractères au plus)")
    existantes = [e["facture_id"] for e in etats_factures if e.get("plan_id") == plan_id]
    if existantes:
        return None, _verdict(
            "REJ-PLAN-REVOCATION-IMPOSSIBLE",
            f"le plan a déjà donné {len(existantes)} facture(s) (par exemple {existantes[0]}) : il ne se révoque plus",
        )
    registre_plans.ajouter(
        {
            "type_entree": _TYPE_REVOCATION,
            "plan_id": plan_id,
            "devis_id": plan["devis_id"],
            "motif": motif_propre,
            "revoque_par": {"par": humain["par"], "role": humain["role"]},
            "horodatage": horodatage,
        }
    )
    return {"plan_id": plan_id, "statut": "REVOQUE", "devis_id": plan["devis_id"]}, None


# ---------------------------------------------------------------------------------------------- facture d'un jalon
def preparer_facture_jalon(
    plan: Mapping[str, Any],
    rang: Any,
    etats_factures: Sequence[Mapping[str, Any]],
    *,
    travaux_termines: bool,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """La facture BROUILLON du jalon `rang` : `{facture_id, lignes, rattachement}`, ou le refus.

    Gardes (toutes relues des factures ÉCRITES, pas du plan) : le jalon existe ; les jalons précédents ont une facture
    (ordre) ; un jalon « fin des travaux » attend `m4.travaux_termines` ; aucune facture globale ne coexiste ; le jalon
    n'est facturé qu'une fois ; le total facturé n'excède JAMAIS le prix du devis."""
    if type(rang) is not int or rang < 1:
        return None, _verdict("REJ-PLAN-JALON-INCONNU", "rang du jalon : entier de 1 au nombre de jalons")
    jalons = plan["jalons"]
    jalon = next((j for j in jalons if j["rang"] == rang), None)
    if jalon is None:
        return None, _verdict(
            "REJ-PLAN-JALON-INCONNU", f"le plan {plan['plan_id']} a {len(jalons)} jalon(s), pas le {rang}"
        )
    facture_id = identifiant_facture_jalon(plan["plan_id"], rang)
    du_devis = [e for e in etats_factures if e.get("devis_id") == plan["devis_id"] and e.get("statut") != "ANNULEE"]
    if any(e.get("plan_id") != plan["plan_id"] for e in du_devis):
        return None, _verdict(
            "REJ-PLAN-DEVIS-DEJA-FACTURE", "une facture globale existe déjà pour ce devis : pas de facture de jalon"
        )
    du_plan = [e for e in du_devis if e.get("plan_id") == plan["plan_id"]]
    deja = [e for e in du_plan if e.get("jalon_rang") == rang]
    if deja and deja[0]["facture_id"] != facture_id:
        return None, _verdict(
            "REJ-PLAN-JALON-DEJA-FACTURE", f"le jalon {rang} porte déjà la facture {deja[0]['facture_id']}"
        )
    if not deja:
        presents = {e.get("jalon_rang") for e in du_plan}
        manquants = [r for r in range(1, rang) if r not in presents]
        if manquants:
            return None, _verdict(
                "REJ-PLAN-JALON-HORS-ORDRE",
                f"facturer d'abord le(s) jalon(s) {manquants} : les jalons se facturent dans l'ordre",
            )
        if jalon["declencheur"] == "fin_travaux" and not travaux_termines:
            return None, _verdict(
                "REJ-PLAN-TRAVAUX-NON-TERMINES",
                "jalon « fin des travaux » : attendre m4.travaux_termines pour ce devis (jamais facturé d'avance)",
            )
    montant = Decimal(jalon["montant_avant_taxes"])
    deja_facture = sum(
        (Decimal(str(e["montant_avant_taxes"])) for e in du_plan if e.get("jalon_rang") != rang), Decimal("0")
    )
    if deja_facture + montant > Decimal(plan["total_avant_taxes"]):
        return None, _verdict(
            "REJ-PLAN-DEPASSEMENT",
            f"facturer ce jalon ({format(montant, 'f')} $) porterait le facturé à "
            f"{format(deja_facture + montant, 'f')} $ avant taxes, au-delà du prix du devis "
            f"({plan['total_avant_taxes']} $)",
        )
    description = f"{jalon['libelle']} (jalon {rang} de {len(jalons)})"
    return {
        "facture_id": facture_id,
        "lignes": [
            {
                "description": description,
                "quantite": "1",
                "unite": "forfait",
                "prix_unitaire": jalon["montant_avant_taxes"],
                "reference_ligne_devis": jalon["jalon_id"],
            }
        ],
        "rattachement": {
            "plan_id": plan["plan_id"],
            "jalon_id": jalon["jalon_id"],
            "jalon_rang": rang,
            "jalons_total": len(jalons),
            "libelle_jalon": jalon["libelle"],
            "plan_total_avant_taxes": plan["total_avant_taxes"],
            "delai_paiement_jours": jalon["delai_paiement_jours"],
        },
    }, None


def resume_plan(
    plan: Mapping[str, Any],
    etats_factures: Sequence[Mapping[str, Any]],
    dictionnaire_taux: Mapping[str, Any],
    aujourd_hui: date | None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le plan et où il en est : chaque jalon avec sa facture (statut, numéro, échéance, retard si la date du jour est
    fournie) ou « à facturer » avec ses taxes calculées par le moteur fiscal ; le facturé, le solde à facturer, et
    l'écart d'arrondi des taxes (taxes facture par facture moins taxes sur le total). Lecture pure."""
    du_plan = {
        e["jalon_rang"]: e
        for e in etats_factures
        if e.get("plan_id") == plan["plan_id"] and e.get("statut") != "ANNULEE"
    }
    total = Decimal(plan["total_avant_taxes"])
    lignes: list[dict[str, Any]] = []
    facture_avant_taxes = Decimal("0")
    taxes_des_jalons = Decimal("0")
    for jalon in plan["jalons"]:
        montant = Decimal(jalon["montant_avant_taxes"])
        facture = du_plan.get(jalon["rang"])
        if facture is not None:
            facture_avant_taxes += Decimal(str(facture["montant_avant_taxes"]))
            taxes_jalon = Decimal(str(facture["total_taxes"]))
            vue = (
                facturation.statut_effectif(facture, aujourd_hui)
                if aujourd_hui is not None
                else {
                    "statut_effectif": facture["statut"],
                    "echeance": facture.get("echeance"),
                    "jours_de_retard": None,
                    "retard_calculable": False,
                }
            )
            ligne_facture = {
                "facture_id": facture["facture_id"],
                "statut": facture["statut"],
                "numero_facture": facture.get("numero_facture"),
                **vue,
            }
            etat_jalon = facture["statut"]
        else:
            calcul, refus = taxes.calculer_taxes(montant, dictionnaire_taux)
            if refus is not None:
                return None, refus
            taxes_jalon = calcul["total_taxes"]
            ligne_facture = {"facture_id": None}
            etat_jalon = "A_FACTURER"
        taxes_des_jalons += taxes_jalon
        lignes.append(
            {
                "rang": jalon["rang"],
                "libelle": jalon["libelle"],
                "declencheur": jalon["declencheur"],
                "montant_avant_taxes": jalon["montant_avant_taxes"],
                "taxes": _txt(taxes_jalon),
                "montant_apres_taxes": _txt(montant + taxes_jalon),
                "delai_paiement_jours": jalon["delai_paiement_jours"],
                "etat": etat_jalon,
                **ligne_facture,
            }
        )
    sur_total, refus = taxes.calculer_taxes(total, dictionnaire_taux)
    if refus is not None:
        return None, refus
    return {
        "plan_id": plan["plan_id"],
        "devis_id": plan["devis_id"],
        "statut": plan["statut"],
        "mode": plan["mode"],
        "total_avant_taxes": plan["total_avant_taxes"],
        "facture_avant_taxes": _txt(facture_avant_taxes),
        "solde_a_facturer_avant_taxes": _txt(total - facture_avant_taxes),
        "jalons": lignes,
        "taxes_des_jalons": _txt(taxes_des_jalons),
        "taxes_sur_le_total": _txt(sur_total["total_taxes"]),
        "ecart_arrondi_taxes": _txt(taxes_des_jalons - sur_total["total_taxes"]),
        "note_taxes": (
            "taxes arrondies facture par facture ; l'écart avec les taxes calculées sur le total est un effet "
            "d'arrondi — À valider auprès d'un comptable (CPA) / professionnel qualifié"
        ),
    }, None


# ------------------------------------------------------------------------------------------------- numérotation
def _numero_texte(numerotation: Mapping[str, Any], sequence: int) -> str:
    return numerotation["prefixe"] + str(sequence).zfill(numerotation["largeur"])


def verifier_numerotation(maillons: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Relit la suite des numéros : `ok` seulement si elle est contiguë (aucun trou), sans doublon de numéro ni de
    facture, et si chaque numéro est bien « préfixe + séquence sur la largeur ». Dit chaque défaut, jamais un résumé."""
    trous: list[int] = []
    doublons: list[str] = []
    anomalies: list[str] = []
    factures: set[str] = set()
    sequences: set[int] = set()
    premier: int | None = None
    attendu: int | None = None
    dernier: int | None = None
    nombre = 0
    for maillon in maillons:
        try:
            if maillon.get("type_entree") != _TYPE_NUMERO:
                anomalies.append(f"maillon {maillon.get('type_entree')!r} étranger à la numérotation")
                continue
            sequence, facture_id = maillon["sequence"], maillon["facture_id"]
            if type(sequence) is not int:
                raise TypeError
            nombre += 1
            if premier is None:
                premier = maillon["premier_numero"]
                attendu = premier
            elif maillon["premier_numero"] != premier:
                anomalies.append(f"séquence {sequence} : premier_numero différent de celui du premier maillon")
            if facture_id in factures:
                doublons.append(f"facture {facture_id} numérotée deux fois")
            if sequence in sequences:
                doublons.append(f"numéro {sequence} écrit deux fois")
            elif sequence > attendu:
                trous.extend(range(attendu, sequence))
                attendu = sequence + 1
            elif sequence < attendu:
                anomalies.append(f"séquence {sequence} hors de l'ordre attendu ({attendu})")
            else:
                attendu = sequence + 1
            if maillon["numero_facture"] != _numero_texte(maillon, sequence):
                anomalies.append(f"séquence {sequence} : numéro {maillon['numero_facture']!r} incohérent")
            factures.add(facture_id)
            sequences.add(sequence)
            dernier = sequence if dernier is None else max(dernier, sequence)
        except (KeyError, TypeError, AttributeError):
            anomalies.append("maillon de numérotation illisible")
    return {
        "ok": not (trous or doublons or anomalies),
        "nombre": nombre,
        "premier": premier,
        "dernier": dernier,
        "trous": trous[:50],
        "doublons": doublons[:50],
        "anomalies": anomalies[:50],
    }


def attribuer_numero(
    registre_numeros: Any, numerotation: Mapping[str, Any], facture_id: str, horodatage: str
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le numéro de `facture_id` : celui déjà attribué (reprise après panne : rien n'est écrit), sinon le suivant de la
    suite. Le rang du maillon est la séquence ; deux attributions simultanées visent le même rang et le registre n'en
    garde qu'une. Rend `({"statut": "nouveau"|"deja", "numero": maillon}, None)` ou le refus (suite altérée, premier
    numéro changé)."""
    maillons = registre_numeros.lire()
    verification = verifier_numerotation(maillons)
    if not verification["ok"]:
        return None, _verdict(
            "REJ-NUMEROTATION-CHAINE-INVALIDE",
            f"suite des numéros altérée (trous {verification['trous'][:5]}, doublons {verification['doublons'][:3]}, "
            f"anomalies {verification['anomalies'][:3]}) : aucun numéro n'est attribué avant correction",
        )
    for maillon in maillons:
        if maillon["facture_id"] == facture_id:
            return {"statut": "deja", "numero": maillon}, None
    if maillons and maillons[0]["premier_numero"] != numerotation["premier_numero"]:
        return None, _verdict(
            "REJ-NUMEROTATION-PREMIER-CHANGE",
            f"la suite a commencé à {maillons[0]['premier_numero']} : le premier numéro déclaré "
            f"({numerotation['premier_numero']}) ne peut plus changer",
        )
    sequence = numerotation["premier_numero"] + len(maillons)
    ligne_id = registre_numeros.ajouter(
        {
            "type_entree": _TYPE_NUMERO,
            "facture_id": facture_id,
            "sequence": sequence,
            "numero_facture": _numero_texte(numerotation, sequence),
            "prefixe": numerotation["prefixe"],
            "largeur": numerotation["largeur"],
            "premier_numero": numerotation["premier_numero"],
            "horodatage": horodatage,
        }
    )
    for maillon in registre_numeros.lire():
        if maillon["ligne_id"] == ligne_id:
            return {"statut": "nouveau", "numero": maillon}, None
    raise RuntimeError("maillon de numérotation ajouté introuvable")
