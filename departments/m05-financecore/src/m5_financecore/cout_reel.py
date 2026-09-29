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
- la main-d'oeuvre : minutes × taux horaire ÷ 60, UN SEUL arrondi au cent, sur le produit exact ;
- une marge en pourcentage est le rapport marge ÷ prix, arrondi à 4 décimales (0.2500 = 25 %) ; c'est la marge
  SUR LE PRIX, pas la majoration sur le coût que porte `taux_marge` du devis (recopiée telle quelle, à part).

Le prix facturé est le montant AVANT TAXES de la facture : la TPS et la TVQ sont perçues pour l'État, jamais un
revenu du chantier. Une facture BROUILLON donne un prix provisoire (`prix_definitif` faux) ; une facture
annulée n'est pas une facture active (`facturation.facture_active_pour_devis`).

`entrees` (et `version_entrees`, l'empreinte de ce que le calcul a réellement consommé) rendent le calcul
rejouable et permettent à `outils.py` de tracer un état une seule fois par version des pièces.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import encodage, validation

__all__ = [
    "calculer_cout_reel",
    "calculer_rentabilite",
    "construire_trace",
    "masquer_montants",
    "resumer",
    "valider_taux_horaire",
]

_CENT = Decimal("0.01")
_QUATRE_DECIMALES = Decimal("0.0001")
_MINUTES_PAR_HEURE = Decimal("60")
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
    "(minutes x taux horaire / 60, un seul arrondi) ; marges en pourcentage du prix, à 4 décimales "
    "(0.2500 = 25 %)"
)

# Ce que le calcul suppose sans pouvoir le vérifier : dit à voix haute dans chaque résultat (P2).
_HYPOTHESES = (
    "le prix unitaire du livre de prix M6 est exprimé dans l'unité déclarée du matériau "
    "(le livre ne porte pas d'unité)",
    "la main-d'oeuvre est la durée pointée sur site du WCT (pauses déduites) multipliée par le taux horaire "
    "configuré ; le WCT ne porte pas l'effectif : ce taux est celui de l'équipe intervenante, par heure sur site",
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
def _resoudre_prix(materiau: str, livre_de_prix: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Le prix unitaire du livre de prix M6 pour ce matériau, ou pourquoi il n'y en a pas.

    Pour chaque fournisseur, le DERNIER maillon écrit fait foi (l'ordre d'écriture, comme
    `livre_prix.prix_en_vigueur` de M6 : aucune comparaison de dates). Une entrée dont le prix est illisible ou
    non strictement positif, ou dont la devise n'est pas CAD, est écartée et dite. Plusieurs fournisseurs au même
    prix : ce prix. Prix différents : ambigu."""
    derniere: dict[str, Mapping[str, Any]] = {}
    for entree in livre_de_prix:
        if isinstance(entree, Mapping) and entree.get("materiau_id") == materiau:
            derniere[str(entree.get("fournisseur_id"))] = entree
    if not derniere:
        return {"statut": _STATUT_PRIX_NON_DISPONIBLE, "prix_unitaire": None, "sources": [],
                "detail": "aucune entrée pour ce matériau dans le livre de prix M6"}

    utilisables: dict[str, tuple[Decimal, Mapping[str, Any]]] = {}
    ecartees: list[str] = []
    for fournisseur in sorted(derniere):
        entree = derniere[fournisseur]
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
         "source_document": entree.get("source_document")}
        for fournisseur, (_, entree) in sorted(utilisables.items())
    ]
    if len(distincts) > 1:
        return {"statut": _STATUT_PRIX_AMBIGU, "prix_unitaire": None, "sources": sources,
                "detail": "prix différents selon le fournisseur (" + "; ".join(
                    f"{fournisseur} : {prix}" for fournisseur, (prix, _) in sorted(utilisables.items())
                ) + ") : le fournisseur du stock utilisé n'est pas connu"}
    (prix_unique,) = distincts
    return {"statut": _STATUT_PRIX_LIVRE, "prix_unitaire": prix_unique, "sources": sources, "detail": ""}


def _ligne_materiau(brute: Any, livre_de_prix: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], dict | None]:
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

    prix = _resoudre_prix(materiau, livre_de_prix)
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


def _materiaux(signal: Mapping[str, Any] | None, livre_de_prix: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
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
        ligne, manque = _ligne_materiau(brute, livre)
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
    if duree is not None and taux is not None:
        cout = _au_cent(Decimal(duree) * taux / _MINUTES_PAR_HEURE)
        if cout is None:
            manques.append(_manque("REJ-COUT-TEMPS-POINTE-ABSENT", "durée x taux hors des limites de calcul"))
    return {"statut": "complet" if cout is not None else "non_disponible", "minutes": duree,
            "taux_horaire": taux, "cout": cout, "manque": manques}


# --------------------------------------------------------------------------------- coût réel
def calculer_cout_reel(
    wct_recu: Mapping[str, Any] | None,
    signal_variance: Mapping[str, Any] | None,
    livre_de_prix: Iterable[Mapping[str, Any]],
    taux_horaire: Any,
    autres_wct: Iterable[str] = (),
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
    materiaux = _materiaux(signal_variance, livre)
    main_d_oeuvre = _main_d_oeuvre(wct_recu, taux_horaire)
    manque = [*materiaux["manque"], *main_d_oeuvre["manque"]]
    if autres:
        manque.append(_manque(
            "REJ-COUT-PLUSIEURS-WCT",
            f"{len(autres) + 1} travaux terminés reçus pour ce devis : seul le premier est chiffré "
            f"(autres : {', '.join(autres)})",
        ))
    complet = materiaux["statut"] == "complet" and main_d_oeuvre["statut"] == "complet" and not autres
    cout_main_d_oeuvre = main_d_oeuvre["cout"] if main_d_oeuvre["cout"] is not None else Decimal("0")
    cout_connu = materiaux["cout_connu"] + cout_main_d_oeuvre

    entrees = {
        "wct": {
            "wct_id": wct_recu.get("wct_id") if wct_recu is not None else None,
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
