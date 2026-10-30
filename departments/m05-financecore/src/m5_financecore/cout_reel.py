"""Coût réel et rentabilité d'un chantier (M5.9, PLAN T1.5-d, DEFINITION-PRODUIT §6 « travaux terminés »).

Module pur (ADR-0009, même règle que `facturation.py`) : aucun import `opsys`, aucun import d'un
autre département (DA-M5-04), aucune horloge, aucun aléa, aucun réseau. Il reçoit des pièces déjà
LUES à la source par `outils.py` (l'adaptateur, seul) et n'en produit que des calculs :

- le WCT reçu de M4 (`wct_recus.py`) : la durée pointée du chantier ;
- le signal `m6.variance_chantier` reçu du bus (`variance_recus.py`) : les matériaux RÉELLEMENT utilisés,
  ligne par ligne ;
- le livre de prix de M6, lu en lecture seule ;
- le taux horaire configuré (`department.yaml/configuration`) ;
- la facture du devis (BROUILLON, ENVOYEE ou PAYEE) et le devis accepté reçu de M3 (`cout_total`, `prix_total`,
  `taux_marge`).

RIEN de tout cela ne vient d'un argument d'outil : ni un modèle ni l'appelant ne fournissent une quantité, un
prix, un taux ou une durée (AGENTS.md, « le code calcule, le LLM orchestre »).

FAIL-CLOSED. Une pièce absente ou illisible ne devient JAMAIS une valeur par défaut : elle devient une entrée
de la liste `manque` (un verdict nommé de `validation.py` qui dit quoi demander), et le coût qui en dépend est
présenté comme PARTIEL. Un prix absent du livre donne une ligne « prix non disponible », jamais un prix inventé,
jamais le prix d'un autre matériau. Deux fournisseurs au livre avec des prix différents pour un même matériau :
« prix ambigu » (le matériau vient du stock, on ne sait pas de quel fournisseur), jamais une moyenne.

ARRONDI (un seul mode, `ROUND_HALF_UP`, le même que `facturation.py` et M3) :
- chaque ligne de matériau : quantité × prix unitaire, arrondi au cent ; le coût des matériaux est la somme de ces
  lignes arrondies (comme une ligne de facture) ;
- la main-d'oeuvre issue d'une ventilation : arrondi au cent par ligne (voir `ventilation_couts_visites.py`) ;
- une marge en pourcentage est le rapport marge ÷ prix, arrondi à 4 décimales (0.2500 = 25 %) ; c'est la marge
  SUR LE PRIX, pas la majoration sur le coût que porte `taux_marge` du devis (recopiée telle quelle, à part).

Le prix facturé est le montant AVANT TAXES de la facture : la TPS et la TVQ sont perçues pour l'État, jamais un
revenu du chantier. Une facture BROUILLON donne un prix provisoire (`prix_definitif` faux) ; une facture
annulée n'est pas une facture active (`facturation.facture_active_pour_devis`).

`entrees` (et `version_entrees`, l'empreinte de ce que le calcul a réellement consommé) rendent le calcul
rejouable et permettent à `outils.py` de tracer un état une seule fois par version des pièces.

ÉVÉNEMENT `m5.rentabilite_chantier` (`charge_evenement`) : ce que M5 dit au bus quand sa trace change. C'est une
LISTE BLANCHE de champs, construite à la main, jamais une copie de la rentabilité : totaux en CAD (textes
décimaux), `wct_id`, `devis_id`, et les CODES de ce qui manque. Ni prix unitaire, ni taux horaire, ni quantité,
ni ligne de matériau, ni donnée de client n'y entrent (le schéma du catalogue est fermé et le refuse aussi). Un
coût PARTIEL ne porte JAMAIS de marge : ni réelle, ni écart ; ce que M5 chiffre déjà est un plancher
(`cout_connu_cad`), jamais un total.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import encodage, validation, validation_projection_visites, ventilation_couts_visites

__all__ = [
    "TYPE_EVENEMENT_RENTABILITE",
    "calculer_cout_reel",
    "calculer_rentabilite",
    "charge_evenement",
    "construire_trace",
    "masquer_montants",
    "resumer",
    "valider_taux_horaire",
]

# Type du catalogue du socle (`src/opsys/evenements/catalogue/m5.rentabilite_chantier.json`) : M5 en est le
# seul producteur. Le nom seulement : la publication (`opsys.evenements`) reste dans `outils.py`.
TYPE_EVENEMENT_RENTABILITE = "m5.rentabilite_chantier"

_CENT = Decimal("0.01")
_QUATRE_DECIMALES = Decimal("0.0001")
_DEVISE = "CAD"
# Ordre de grandeur au-delà duquel une valeur lue (montant, quantité, prix, durée) est illisible : 10^12.
# Un chantier de rénovation n'en approche jamais ; ce plafond garde tout calcul dans la précision de
# `decimal` (jamais une exception d'arithmétique sur une pièce absurde : elle devient un manque).
_EXPOSANT_MAX = 11

_STATUT_PRIX_LIVRE = "PRIX_LIVRE"
_STATUT_PRIX_NON_DISPONIBLE = "PRIX_NON_DISPONIBLE"
_STATUT_PRIX_AMBIGU = "PRIX_AMBIGU"
_STATUT_LIGNE_INDETERMINEE = "LIGNE_INDETERMINEE"

_ARRONDI = (
    "ROUND_HALF_UP au cent : chaque ligne de matériau (quantité x prix unitaire), puis la main-d'oeuvre "
    "(une ligne ventilée par visite et équipe) ; marges en pourcentage du prix, à 4 décimales "
    "(0.2500 = 25 %)"
)

# Ce que le calcul suppose sans pouvoir le vérifier : dit à voix haute dans chaque résultat (P2).
_HYPOTHESES = (
    "les matériaux sont valorisés au tarif M6 éligible à la date civile de complétion du WCT "
    "(dans sa zone déclarée), avec unité identique confirmée ; ce tarif ne prouve pas le coût du lot acheté",
    "le WCT scalaire ne permet pas de vérifier les équipes présentes à chaque visite : une ventilation "
    "certifiée et des taux sourcés sont nécessaires pour chiffrer la main-d'oeuvre",
    "le coût réel ne compte que les matériaux et la main-d'oeuvre sur site : ni déplacements, ni frais généraux",
)


def _en_decimal(valeur: Any, *, autoriser_nombre: bool = False) -> Decimal | None:
    """Décimal fini depuis un texte (ou un nombre, si permis) ; `None` si illisible.

    Un nombre JSON passe par `str()` (jamais `Decimal(float)`, qui importerait l'imprécision binaire)."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, Decimal):
        resultat = valeur
    elif isinstance(valeur, str):
        try:
            resultat = Decimal(valeur.strip())
        except InvalidOperation:
            return None
    elif autoriser_nombre and isinstance(valeur, (int, float)):
        try:
            resultat = Decimal(str(valeur))
        except InvalidOperation:
            return None
    else:
        return None
    if not resultat.is_finite() or resultat.adjusted() > _EXPOSANT_MAX:
        return None
    return resultat


def _au_cent(valeur: Decimal) -> Decimal | None:
    """Arrondi au cent, `ROUND_HALF_UP` ; `None` si le résultat sort de la précision de `decimal`."""
    try:
        return valeur.quantize(_CENT, rounding=ROUND_HALF_UP)
    except ArithmeticError:
        return None


def _pourcentage_du_prix(marge: Decimal, prix: Decimal) -> Decimal | None:
    """Marge ÷ prix à 4 décimales ; `None` si le prix n'est pas strictement positif (jamais une division
    par zéro ni un ratio inventé) ou si le rapport sort de la précision de `decimal`."""
    if prix <= 0:
        return None
    try:
        return (marge / prix).quantize(_QUATRE_DECIMALES, rounding=ROUND_HALF_UP)
    except ArithmeticError:
        return None


def _manque(code: str, detail: str, **reference: Any) -> dict[str, Any]:
    return {**validation.construire_verdict(code, detail=detail), **reference}


def valider_taux_horaire(brut: Any) -> tuple[Decimal | None, dict[str, Any] | None]:
    """`(taux, None)` si la configuration porte un taux horaire strictement positif, sinon
    `(None, verdict)` : `REJ-COUT-TAUX-HORAIRE-A-CONFIGURER`. Absent ou illisible, jamais un taux par défaut."""
    if brut is None:
        return None, validation.construire_verdict(
            "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER",
            detail="taux_horaire_main_d_oeuvre absent de department.yaml/configuration",
        )
    taux = _en_decimal(brut, autoriser_nombre=True)
    if taux is None or taux <= 0:
        return None, validation.construire_verdict(
            "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER",
            detail="taux_horaire_main_d_oeuvre doit être un nombre strictement positif (dollars par heure)",
        )
    return taux, None


# --------------------------------------------------------------------------------- matériaux
def _date_tarif(brute: Any) -> date | None:
    """Date civile ISO explicite ; aucune date inventée ni horloge pour compléter une pièce."""
    if not isinstance(brute, str) or len(brute) != 10 or brute[4:5] != "-" or brute[7:8] != "-":
        return None
    try:
        return date.fromisoformat(brute)
    except ValueError:
        return None


def _date_completion(wct_recu: Mapping[str, Any] | None) -> date | None:
    brute = wct_recu.get("horodatage_completion") if wct_recu is not None else None
    if not isinstance(brute, str):
        return None
    try:
        completion = datetime.fromisoformat(brute)
    except ValueError:
        return None
    return completion.date() if completion.tzinfo is not None else None


def _resoudre_prix(
    materiau: str, unite: str, livre_de_prix: Iterable[Mapping[str, Any]], date_completion: date | None,
) -> dict[str, Any]:
    """Le prix unitaire du livre de prix M6 pour ce matériau, ou pourquoi il n'y en a pas.

    Pour chaque fournisseur, le DERNIER maillon écrit ÉLIGIBLE à la date du WCT fait foi : les tarifs
    futurs sont exclus, puis la priorité append-only de M6 est conservée entre les révisions éligibles.
    Une date illisible ou une unité inconnue/incompatible empêche de conclure, sans repli silencieux.
    Une entrée dont le prix est illisible ou
    non strictement positif, ou dont la devise n'est pas CAD, est écartée et dite. Plusieurs fournisseurs au même
    prix : ce prix. Prix différents : ambigu."""
    if date_completion is None:
        return {"statut": _STATUT_PRIX_NON_DISPONIBLE, "prix_unitaire": None, "sources": [],
                "detail": "horodatage de complétion du WCT absent ou illisible (date et zone requises)"}
    derniere: dict[str, Mapping[str, Any]] = {}
    for entree in livre_de_prix:
        if isinstance(entree, Mapping) and entree.get("materiau_id") == materiau:
            effet = _date_tarif(entree.get("date_effet"))
            if effet is not None and effet > date_completion:
                continue
            derniere[str(entree.get("fournisseur_id"))] = entree
    if not derniere:
        return {"statut": _STATUT_PRIX_NON_DISPONIBLE, "prix_unitaire": None, "sources": [],
                "detail": "aucune entrée pour ce matériau au livre de prix M6 à la date du WCT"}

    utilisables: dict[str, tuple[Decimal, Mapping[str, Any]]] = {}
    ecartees: list[str] = []
    for fournisseur in sorted(derniere):
        entree = derniere[fournisseur]
        if _date_tarif(entree.get("date_effet")) is None:
            return {"statut": _STATUT_PRIX_NON_DISPONIBLE, "prix_unitaire": None, "sources": [],
                    "detail": f"{fournisseur} : date_effet absente ou illisible ; demander une date civile ISO"}
        unite_prix = entree.get("unite")
        if not isinstance(unite_prix, str) or not unite_prix.strip() or unite_prix.strip() != unite.strip():
            return {"statut": _STATUT_PRIX_NON_DISPONIBLE, "prix_unitaire": None, "sources": [],
                    "detail": f"{fournisseur} : unité du prix absente ou incompatible ; "
                              f"confirmer le tarif dans l'unité déclarée {unite!r}"}
        prix = _en_decimal(entree.get("prix_unitaire"), autoriser_nombre=True)
        devise = entree.get("devise")
        if prix is None or prix <= 0:
            ecartees.append(f"{fournisseur} : prix illisible")
        elif not isinstance(devise, str) or devise.strip().upper() != _DEVISE:
            ecartees.append(f"{fournisseur} : devise {devise!r} au lieu de {_DEVISE}")
        else:
            utilisables[fournisseur] = (prix, entree)
    if not utilisables:
        return {"statut": _STATUT_PRIX_NON_DISPONIBLE, "prix_unitaire": None, "sources": [],
                "detail": "entrée(s) inutilisable(s) au livre de prix M6 : " + "; ".join(ecartees)}

    distincts = {prix for prix, _ in utilisables.values()}
    sources = [
        {"fournisseur_id": fournisseur, "date_effet": entree.get("date_effet"),
         "source_document": entree.get("source_document"), "unite": entree.get("unite")}
        for fournisseur, (_, entree) in sorted(utilisables.items())
    ]
    if len(distincts) > 1:
        return {"statut": _STATUT_PRIX_AMBIGU, "prix_unitaire": None, "sources": sources,
                "detail": "prix différents selon le fournisseur (" + "; ".join(
                    f"{fournisseur} : {prix}" for fournisseur, (prix, _) in sorted(utilisables.items())
                ) + ") : le fournisseur du stock utilisé n'est pas connu"}
    (prix_unique,) = distincts
    return {"statut": _STATUT_PRIX_LIVRE, "prix_unitaire": prix_unique, "sources": sources, "detail": ""}


def _ligne_materiau(
    brute: Any, livre_de_prix: Iterable[Mapping[str, Any]], date_completion: date | None,
) -> tuple[dict[str, Any], dict | None]:
    """Une ligne du signal de variance -> une ligne de coût, et le manque qu'elle porte (ou `None`)."""
    materiau = brute.get("materiau") if isinstance(brute, Mapping) else None
    if not isinstance(materiau, str) or not materiau.strip():
        ligne = {"materiau": None, "unite": None, "quantite_reelle": None, "prix_unitaire": None, "cout": None,
                 "statut": _STATUT_LIGNE_INDETERMINEE, "sources_prix": []}
        return ligne, _manque("REJ-COUT-LIGNE-INDETERMINEE", "ligne de variance sans identifiant de matériau")

    unite = brute.get("unite")
    quantite = _en_decimal(brute.get("quantite_reelle"))
    ligne = {"materiau": materiau, "unite": unite, "quantite_reelle": quantite, "prix_unitaire": None,
             "cout": None, "statut": _STATUT_LIGNE_INDETERMINEE, "sources_prix": []}
    if not isinstance(unite, str) or not unite.strip():
        return ligne, _manque(
            "REJ-COUT-LIGNE-INDETERMINEE",
            "unité prévue et unité déclarée incohérentes : la quantité réelle n'est pas exprimable",
            materiau=materiau,
        )
    if quantite is None or quantite < 0:
        return ligne, _manque(
            "REJ-COUT-LIGNE-INDETERMINEE", "quantité réelle illisible ou négative", materiau=materiau
        )

    prix = _resoudre_prix(materiau, unite, livre_de_prix, date_completion)
    ligne["statut"] = prix["statut"]
    ligne["sources_prix"] = prix["sources"]
    if prix["statut"] == _STATUT_PRIX_LIVRE:
        cout = _au_cent(quantite * prix["prix_unitaire"])
        if cout is None:
            ligne["statut"] = _STATUT_LIGNE_INDETERMINEE
            return ligne, _manque(
                "REJ-COUT-LIGNE-INDETERMINEE", "quantité x prix hors des limites de calcul", materiau=materiau
            )
        ligne["prix_unitaire"] = prix["prix_unitaire"]
        ligne["cout"] = cout
        return ligne, None
    code = "REJ-COUT-PRIX-AMBIGU" if prix["statut"] == _STATUT_PRIX_AMBIGU else "REJ-COUT-PRIX-NON-DISPONIBLE"
    return ligne, _manque(code, prix["detail"], materiau=materiau)


def _materiaux(
    signal: Mapping[str, Any] | None, livre_de_prix: Iterable[Mapping[str, Any]], date_completion: date | None,
) -> dict[str, Any]:
    zero = Decimal("0")
    vide = {"statut": "non_disponible", "lignes": [], "cout_connu": zero, "source_quantites": None, "manque": []}
    if signal is None:
        vide["manque"].append(_manque(
            "REJ-COUT-MATERIAUX-REELS-ABSENTS",
            "aucun signal m6.variance_chantier reçu pour ce WCT : les matériaux réellement utilisés sont inconnus",
        ))
        return vide
    source = {"evenement": "m6.variance_chantier", "statut_variance": signal.get("statut_variance"),
              "signal_critique": signal.get("signal_critique")}
    vide["source_quantites"] = source
    lignes_brutes = signal.get("lignes")
    if signal.get("statut_variance") != "evaluee":
        vide["manque"].append(_manque(
            "REJ-COUT-MATERIAUX-REELS-ABSENTS",
            f"variance M6 non évaluée (statut {signal.get('statut_variance')!r}) : "
            "pas de détail des matériaux réellement utilisés",
        ))
        return vide
    if not isinstance(lignes_brutes, list):
        vide["manque"].append(_manque(
            "REJ-COUT-MATERIAUX-REELS-ABSENTS",
            "signal de variance évalué reçu sans le détail par matériau",
        ))
        return vide

    livre = list(livre_de_prix)
    lignes: list[dict[str, Any]] = []
    manques: list[dict[str, Any]] = []
    cout_connu = zero
    for brute in lignes_brutes:
        ligne, manque = _ligne_materiau(brute, livre, date_completion)
        lignes.append(ligne)
        if manque is not None:
            manques.append(manque)
        elif ligne["cout"] is not None:
            cout_connu += ligne["cout"]
    return {"statut": "complet" if not manques else "partiel", "lignes": lignes, "cout_connu": cout_connu,
            "source_quantites": source, "manque": manques}


# --------------------------------------------------------------------------------- main-d'oeuvre
def _main_d_oeuvre(wct_recu: Mapping[str, Any] | None, taux_brut: Any) -> dict[str, Any]:
    manques: list[dict[str, Any]] = []
    duree = wct_recu.get("duree_reelle_minutes") if wct_recu is not None else None
    if (
        isinstance(duree, bool) or not isinstance(duree, int) or duree <= 0
        or Decimal(duree).adjusted() > _EXPOSANT_MAX
    ):
        detail = (
            "durée pointée absente du WCT reçu" if duree is None
            else "durée pointée illisible ou nulle dans le WCT reçu"
        )
        manques.append(_manque("REJ-COUT-TEMPS-POINTE-ABSENT", detail))
        duree = None
    taux, verdict_taux = valider_taux_horaire(taux_brut)
    if verdict_taux is not None:
        manques.append(dict(verdict_taux))
    cout = None
    if duree is not None:
        manques.append(_manque(
            "REJ-COUT-TEMPS-POINTE-ABSENT",
            "durée WCT scalaire sans preuve de présence par visite et équipe ; "
            "demander la ventilation certifiée M4 et les taux applicables sourcés",
        ))
    return {"statut": "complet" if cout is not None else "non_disponible", "minutes": duree,
            "taux_horaire": taux, "cout": cout, "manque": manques}


def _main_d_oeuvre_ventilee(
    wct: Mapping[str, Any] | None, projection: Any, tarifs: Any,
    instance_id: Any, source_attendue: Any, sources_actuelles: Any, source_relue: Any = None,
) -> dict[str, Any]:
    """Utilise des pièces obtenues et revalidées par un adaptateur propriétaire autorisé.

    Cette fonction pure ne peut pas établir l'autorité des paramètres fournis.
    Aucun chemin public ne doit y relayer des arguments d'un appelant comme des faits.
    """
    resultat = {"statut": "non_disponible", "minutes": None, "taux_horaire": None,
                "cout": None, "cout_connu": None, "lignes": [], "manque": [], "projection_empreinte": None,
                "tarifs_empreinte": None}
    wct_id = wct.get("wct_id") if wct is not None else None
    if isinstance(projection, dict) and projection.get("version") == "opsys.m4.temps_certifies.v3":
        controle = validation_projection_visites.valider_projection_v3(
            projection, instance_id=instance_id, wct_id=wct_id, source_attendue=source_attendue,
            source_relue=source_relue, sources_actuelles=sources_actuelles,
        )
    else:
        controle = validation_projection_visites.valider_projection(
            projection, instance_id=instance_id, wct_id=wct_id,
            source_attendue=source_attendue, sources_actuelles=sources_actuelles,
        )
    if not controle["valide"]:
        resultat["manque"].append(_manque("REJ-COUT-TEMPS-POINTE-ABSENT", "; ".join(controle["raisons"])))
        return resultat
    piece = projection["wct"]
    if wct is None or any((
        wct.get("intervention_id") != projection["intervention_id"],
        wct.get("duree_reelle_minutes") != piece["duree_reelle_minutes"],
        wct.get("horodatage_completion") != piece["horodatage_completion"],
        wct.get("hash_maillon") != piece["hash_maillon"],
    )):
        resultat["manque"].append(_manque(
            "REJ-COUT-TEMPS-POINTE-ABSENT", "WCT et projection non réconciliés : pièce source complète requise",
        ))
        return resultat
    resultat["projection_empreinte"] = projection["empreinte"]
    resultat["minutes"] = piece["duree_reelle_minutes"]
    if not controle["exploitable"]:
        resultat["manque"].append(_manque(
            "REJ-COUT-TEMPS-POINTE-ABSENT", "revue finale ou équipes pointées à vérifier avant imputation",
        ))
        return resultat
    if isinstance(tarifs, list) and len(tarifs) <= 10000:
        try:
            resultat["tarifs_empreinte"] = encodage.empreinte("m5.tarifs-equipes.v1", tarifs)
        except (TypeError, ValueError, OverflowError, RecursionError):
            resultat["manque"].append(_manque(
                "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER", "instantané des tarifs illisible",
            ))
            return resultat
    economie = ventilation_couts_visites.chiffrer_visites(projection["visites"], tarifs)
    resultat["lignes"] = economie["lignes"]
    if not economie["complet"]:
        resultat["manque"].append(_manque(
            "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER", "; ".join(economie["raisons"]),
        ))
    if controle["exploitable"] and economie["cout_connu"] is not None:
        resultat["cout_connu"] = economie["cout_connu"]
        resultat["statut"] = "partiel"
    if controle["exploitable"] and economie["complet"]:
        resultat["cout"] = economie["cout_total"]
        resultat["statut"] = "complet"
    return resultat


# --------------------------------------------------------------------------------- coût réel
def calculer_cout_reel(
    wct_recu: Mapping[str, Any] | None,
    signal_variance: Mapping[str, Any] | None,
    livre_de_prix: Iterable[Mapping[str, Any]],
    taux_horaire: Any,
    autres_wct: Iterable[str] = (),
    *,
    projection: Any = None,
    tarifs_equipes: Any = None,
    instance_id: Any = None,
    source_attendue: Any = None,
    sources_actuelles: Any = None,
    source_relue: Any = None,
) -> dict[str, Any]:
    """Le coût réel d'un chantier, tel que les pièces lues à la source le permettent.

    `complet` n'est vrai que si les matériaux ET la main-d'oeuvre sont chiffrés ; sinon `cout_total` est `None`
    (jamais une somme partielle prise pour un total), `cout_total_connu` porte ce qui est chiffré, et `manque`
    liste tout ce qui empêche de conclure. Ne lève pas sur une pièce mal formée : elle devient un manque.

    `autres_wct` : les identifiants des AUTRES travaux terminés reçus pour le même devis. Le modèle de M5 est un
    devis, un WCT, une facture : si un second existe, le coût d'un seul est connu, l'autre non. Le coût est alors
    dit partiel (`REJ-COUT-PLUSIEURS-WCT`) plutôt que présenté comme le total d'un chantier plus long."""
    livre = list(livre_de_prix)
    autres = sorted({str(identifiant) for identifiant in autres_wct})
    materiaux = _materiaux(signal_variance, livre, _date_completion(wct_recu))
    main_d_oeuvre = (
        _main_d_oeuvre(wct_recu, taux_horaire) if projection is None else
        _main_d_oeuvre_ventilee(wct_recu, projection, tarifs_equipes, instance_id, source_attendue,
                                sources_actuelles, source_relue)
    )
    manque = [*materiaux["manque"], *main_d_oeuvre["manque"]]
    if autres:
        manque.append(_manque(
            "REJ-COUT-PLUSIEURS-WCT",
            f"{len(autres) + 1} travaux terminés reçus pour ce devis : seul le premier est chiffré "
            f"(autres : {', '.join(autres)})",
        ))
    complet = materiaux["statut"] == "complet" and main_d_oeuvre["statut"] == "complet" and not autres
    cout_main_d_oeuvre = main_d_oeuvre["cout"]
    if cout_main_d_oeuvre is None:
        cout_main_d_oeuvre = main_d_oeuvre.get("cout_connu")
    if cout_main_d_oeuvre is None:
        cout_main_d_oeuvre = Decimal("0")
    cout_connu = materiaux["cout_connu"] + cout_main_d_oeuvre

    entrees = {
        "wct": {
            "wct_id": wct_recu.get("wct_id") if wct_recu is not None else None,
            "horodatage_completion": wct_recu.get("horodatage_completion") if wct_recu is not None else None,
            "duree_reelle_minutes": main_d_oeuvre["minutes"],
        },
        "variance": {
            "statut_variance": signal_variance.get("statut_variance") if signal_variance is not None else None,
            "lignes": [
                [ligne["materiau"], ligne["unite"], ligne["quantite_reelle"]] for ligne in materiaux["lignes"]
            ],
        },
        "prix": [
            [ligne["materiau"], ligne["statut"], ligne["prix_unitaire"], ligne["sources_prix"]]
            for ligne in materiaux["lignes"]
        ],
        "taux_horaire": main_d_oeuvre["taux_horaire"],
        "autres_wct": autres,
    }
    if projection is not None:
        entrees["ventilation"] = {
            "empreinte": main_d_oeuvre.get("projection_empreinte"),
            "tarifs_empreinte": main_d_oeuvre.get("tarifs_empreinte"),
            "lignes": main_d_oeuvre.get("lignes", []),
            "statut": main_d_oeuvre["statut"],
            "manque": main_d_oeuvre["manque"],
        }
    return {
        "devise": _DEVISE,
        "complet": complet,
        "materiaux": {cle: valeur for cle, valeur in materiaux.items() if cle != "manque"},
        "main_d_oeuvre": {cle: valeur for cle, valeur in main_d_oeuvre.items() if cle != "manque"},
        "cout_total": cout_connu if complet else None,
        "cout_total_connu": cout_connu,
        "manque": manque,
        "hypotheses": list(_HYPOTHESES),
        "arrondi": _ARRONDI,
        "entrees": entrees,
    }


# --------------------------------------------------------------------------------- rentabilité
def _marge_prevue(devis_recu: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """La marge prévue du devis accepté (`cout_total` et `prix_total` de M3, recopiés), ou pourquoi elle manque."""
    vide = {"cout_prevu": None, "prix_prevu": None, "marge_prevue": None, "marge_prevue_pct_du_prix": None,
            "taux_marge_devis": None}
    if devis_recu is None:
        return vide, _manque("REJ-RENTABILITE-MARGE-PREVUE-ABSENTE", "devis accepté non reçu")
    cout_prevu = _en_decimal(devis_recu.get("cout_total"))
    prix_prevu = _en_decimal(devis_recu.get("prix_total"))
    if cout_prevu is None or prix_prevu is None:
        return vide, _manque(
            "REJ-RENTABILITE-MARGE-PREVUE-ABSENTE",
            "cout_total ou prix_total absent du devis reçu (devis reçu sans coût prévu)",
        )
    marge = prix_prevu - cout_prevu
    return {
        "cout_prevu": cout_prevu, "prix_prevu": prix_prevu, "marge_prevue": marge,
        "marge_prevue_pct_du_prix": _pourcentage_du_prix(marge, prix_prevu),
        "taux_marge_devis": devis_recu.get("taux_marge"),
    }, None


def calculer_rentabilite(
    cout: Mapping[str, Any],
    facture: Mapping[str, Any] | None,
    devis_recu: Mapping[str, Any] | None,
    *,
    devis_id: str,
    chantier_id: str | None,
) -> dict[str, Any]:
    """Prix facturé moins coût réel, marge réelle contre marge prévue. Ne lit et n'écrit rien d'autre.

    `verdict` : `CALCULEE` seulement si le coût est complet ET qu'une facture existe ; sinon `PARTIELLE`, avec
    `manque`. Coût partiel : `marge_reelle` reste `None` ; `marge_partielle_plafond` (prix moins le coût CONNU)
    est un plafond, jamais la marge : ce qui manque n'y est pas soustrait."""
    prix = _en_decimal(facture.get("montant_avant_taxes")) if facture is not None else None
    manque = list(cout["manque"])
    if prix is None:
        manque.append(_manque(
            "REJ-RENTABILITE-FACTURE-ABSENTE",
            "aucune facture active pour ce devis : le prix facturé est inconnu" if facture is None
            else "montant avant taxes de la facture illisible",
        ))
    prevue, manque_prevue = _marge_prevue(devis_recu)
    if manque_prevue is not None:
        manque.append(manque_prevue)

    marge_reelle = marge_reelle_pct = marge_plafond = marge_plafond_pct = None
    if prix is not None:
        if cout["complet"]:
            marge_reelle = prix - cout["cout_total"]
            marge_reelle_pct = _pourcentage_du_prix(marge_reelle, prix)
        else:
            marge_plafond = prix - cout["cout_total_connu"]
            marge_plafond_pct = _pourcentage_du_prix(marge_plafond, prix)

    ecart_marge = ecart_points = None
    if marge_reelle is not None and prevue["marge_prevue"] is not None:
        ecart_marge = marge_reelle - prevue["marge_prevue"]
        if marge_reelle_pct is not None and prevue["marge_prevue_pct_du_prix"] is not None:
            ecart_points = marge_reelle_pct - prevue["marge_prevue_pct_du_prix"]

    statut_facture = facture.get("statut") if facture is not None else None
    verdict = "CALCULEE" if cout["complet"] and prix is not None else "PARTIELLE"
    version = encodage.empreinte({
        "cout": cout["entrees"],
        "facture": [facture.get("facture_id"), statut_facture, prix] if facture is not None else None,
        "devis": [devis_recu.get("cout_total"), devis_recu.get("prix_total"), devis_recu.get("taux_marge")]
        if devis_recu is not None else None,
    })
    return {
        "devis_id": devis_id,
        "chantier_id": chantier_id,
        "wct_id": cout["entrees"]["wct"]["wct_id"],
        "verdict": verdict,
        "devise": cout["devise"],
        "facture_id": facture.get("facture_id") if facture is not None else None,
        "statut_facture": statut_facture,
        "prix_definitif": statut_facture in ("ENVOYEE", "PAYEE"),
        "prix_facture": prix,
        "cout_reel": {cle: valeur for cle, valeur in cout.items() if cle != "entrees"},
        "marge_reelle": marge_reelle,
        "marge_reelle_pct_du_prix": marge_reelle_pct,
        "marge_partielle_plafond": marge_plafond,
        "marge_partielle_plafond_pct_du_prix": marge_plafond_pct,
        "en_perte": marge_reelle is not None and marge_reelle < 0,
        **prevue,
        "ecart_marge": ecart_marge,
        "ecart_marge_points": ecart_points,
        "manque": manque,
        "version_entrees": version,
    }


def construire_trace(rentabilite: Mapping[str, Any], horodatage: Any) -> dict[str, Any]:
    """Le maillon qui trace un état calculé (registre `rentabilite`, dérivé : ni le grand livre, ni les
    factures). `horodatage` est celui du WCT reçu : M5 n'a pas d'horloge (DA-M5-06). Les deux textes constants
    du code (`hypotheses`, `arrondi`) n'y sont pas recopiés : ils ne varient qu'avec la version du code."""
    return {
        "type_entree": "rentabilite_calculee",
        "devis_id": rentabilite["devis_id"],
        "chantier_id": rentabilite["chantier_id"],
        "wct_id": rentabilite["wct_id"],
        "version_entrees": rentabilite["version_entrees"],
        "verdict": rentabilite["verdict"],
        "horodatage": horodatage,
        "rentabilite": {
            cle: ({sous: v for sous, v in valeur.items() if sous not in ("hypotheses", "arrondi")}
                  if cle == "cout_reel" else valeur)
            for cle, valeur in rentabilite.items() if cle != "version_entrees"
        },
    }


def _texte_decimal(valeur: Decimal | None) -> str | None:
    """Texte décimal exact d'un montant (jamais un nombre JSON, jamais un arrondi de plus), `None` si absent.
    Un zéro est écrit sans signe (pas de « -0.00 »)."""
    if valeur is None:
        return None
    return format(valeur.copy_abs() if valeur == 0 else valeur, "f")


def charge_evenement(rentabilite: Mapping[str, Any], sequence: int, horodatage: Any) -> dict[str, Any]:
    """La charge de `m5.rentabilite_chantier` pour un état qui vient d'être tracé (voir la docstring du module).

    `sequence` : le rang de la trace pour ce devis (1 pour la première). Il entre dans l'identifiant : un retour
    à une version antérieure des entrées ne doit pas être avalé par l'idempotence du bus, qui laisserait les
    consommateurs sur l'état précédent. `horodatage` : celui du WCT (M5 n'a pas d'horloge).

    Fail-closed, en plus de ce que le schéma impose : la marge réelle et l'écart ne sortent que pour un verdict
    `CALCULEE` dont le coût est complet ; sinon ils sont `None`, même si `rentabilite` en portait une par erreur.
    Ne lève pas sur une rentabilité produite par `calculer_rentabilite` (le catalogue valide la charge à la
    publication)."""
    cout = rentabilite["cout_reel"]
    calculee = (
        rentabilite["verdict"] == "CALCULEE" and cout["complet"] is True and rentabilite["marge_reelle"] is not None
    )
    marge_reelle = rentabilite["marge_reelle"] if calculee else None
    ecart = rentabilite["ecart_marge"] if calculee else None
    version = rentabilite["version_entrees"]
    return {
        "evenement_id": f"m5-rentabilite-{rentabilite['devis_id']}-{sequence}-{version[:16]}",
        "devis_id": rentabilite["devis_id"],
        "chantier_id": rentabilite["chantier_id"],
        "wct_id": rentabilite["wct_id"],
        "sequence": sequence,
        "version_entrees": version,
        "horodatage_completion": horodatage,
        "verdict": "CALCULEE" if calculee else "PARTIELLE",
        "devise": rentabilite["devise"],
        "prix_definitif": rentabilite["prix_definitif"] is True,
        "cout_reel_complet": cout["complet"] is True,
        "cout_reel_cad": _texte_decimal(cout["cout_total"]) if cout["complet"] is True else None,
        "cout_connu_cad": _texte_decimal(cout["cout_total_connu"]),
        "marge_reelle_cad": _texte_decimal(marge_reelle),
        "marge_prevue_cad": _texte_decimal(rentabilite["marge_prevue"]),
        "ecart_marge_cad": _texte_decimal(ecart),
        "manque": sorted({entree["code"] for entree in rentabilite["manque"]}),
    }


def masquer_montants(rentabilite: Mapping[str, Any]) -> dict[str, Any]:
    """La vue d'un appelant qui n'a pas le droit de voir les coûts (`autorise_couts` faux) : identifiants,
    verdict et codes de manque, AUCUN montant ni détail (un détail de manque peut citer un prix
    fournisseur). Même règle que `etat_financier` : sans droit, rien de chiffré."""
    return {
        "devis_id": rentabilite["devis_id"],
        "chantier_id": rentabilite["chantier_id"],
        "verdict": rentabilite["verdict"],
        "statut_facture": rentabilite["statut_facture"],
        "cout_reel_complet": rentabilite["cout_reel"]["complet"],
        "manque": [entree["code"] for entree in rentabilite["manque"]],
        "montants_masques": True,
    }


def resumer(rentabilite: Mapping[str, Any]) -> dict[str, Any]:
    """Une ligne par chantier pour une liste (économie de jetons, P11) : le verdict, les montants qui
    comptent et les codes de manque ; le détail (lignes de matériaux, sources de prix) reste à la lecture
    d'un chantier précis. Sans `devis_id` ni `chantier_id` : l'appelant les porte déjà à côté."""
    return {
        "verdict": rentabilite["verdict"],
        "statut_facture": rentabilite["statut_facture"],
        "prix_facture": rentabilite["prix_facture"],
        "cout_reel_complet": rentabilite["cout_reel"]["complet"],
        "cout_total": rentabilite["cout_reel"]["cout_total"],
        "cout_total_connu": rentabilite["cout_reel"]["cout_total_connu"],
        "marge_reelle": rentabilite["marge_reelle"],
        "marge_prevue": rentabilite["marge_prevue"],
        "ecart_marge": rentabilite["ecart_marge"],
        "manque": [entree["code"] for entree in rentabilite["manque"]],
    }
