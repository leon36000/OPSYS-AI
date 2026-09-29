"""Comptes à payer (M5.2, PLAN T4.15 ; DEFINITION-PRODUIT §7 M5.2 « comptes à payer » et M6.16 « pont finance »).

Ce que l'entreprise doit à ses fournisseurs. Module pur (ADR-0009, même règle que `facturation.py`) : aucun import
`opsys`, aucun import d'un autre département (DA-M5-04), aucune horloge, aucun aléa, aucun réseau. `outils.py`
(l'adaptateur, seul) lit le bus, le registre durable et l'identité ; ce module ne fait que valider, calculer et
décider.

TROIS CHOSES, UN SEUL REGISTRE (`comptes_a_payer`, DÉDIÉ : ni les mouvements, ni les factures clients) :

1. Une RÉCEPTION REÇUE (`reception_recue`) : ce que `m6.reception_enregistree` dit être arrivé cette fois-là pour un
   bon de commande. M5 en tire l'« à payer ATTENDU » : quantité reçue × prix unitaire du PO, arrondie au cent par
   ligne. Une réception partielle donne un attendu partiel ; les livraisons d'un même PO se cumulent.
2. Une FACTURE FOURNISSEUR SAISIE (`facture_fournisseur_saisie`) : tapée par un humain (jamais lue par OCR : l'OCR est
   fermé, la saisie manuelle est le repli documenté), contre un PO déjà reçu au moins en partie. Les taxes sont
   RECALCULÉES depuis le montant avant taxes avec les taux versionnés (`taxes.calculer_taxes`, TPS et TVQ) ; un
   total imprimé sur la facture, s'il est fourni, doit concorder au cent près ou la saisie est refusée. Un doublon
   (même fournisseur, même numéro, même montant) est refusé.
3. Un RAPPROCHEMENT PO / réception / facture, PROPOSÉ avec ses écarts au moment de la lecture, jamais stocké, jamais
   appliqué : il n'existe aucun état « rapproché » ni « approuvé » dans ce module. Le vérifier et le décider reste un
   geste humain.

CE QUE CE MODULE NE FAIT JAMAIS : payer. Aucune écriture au registre des mouvements, aucun DECAISSEMENT, aucun
statut « payée » : payer un fournisseur est de l'argent réel (N5, Nathan ET le CPA, ADR-0009 §5) et n'existe pas ici.
Ce module n'importe même pas `registre.py` (le registre est reçu, duck-typé : `ajouter`/`lire`, comme
`facturation.py`), et `conformite.verifier_aucun_decaissement` le prouve par l'AST.

ARRONDI (un seul mode, `ROUND_HALF_UP`, le même que `facturation.py`, `cout_reel.py` et M3 ; règle citée dans
`taxes.py` : ARC RC4022 « Arrondir les montants fractionnaires » et Revenu Québec « Calcul des taxes ») : chaque
ligne (quantité × prix unitaire) au cent, le total est la somme de ces lignes arrondies ; les taxes sont celles de
`taxes.calculer_taxes`, arrondies au cent chacune. Le produit est calculé en précision étendue (`_CONTEXTE`), jamais
tronqué avant l'arrondi. Aucune tolérance n'est inventée : un écart d'un cent est un écart.

UNITÉ DES PRIX (GATE NATHAN, PLAN T4.15). Le livre de prix de M6 ne déclare pas l'unité dans laquelle un prix unitaire
est exprimé, et le bon de commande n'en déclare pas pour une quantité. M5 ne convertit RIEN et n'invente aucune unité :
il suppose que le prix est exprimé par unité de la quantité reçue, le DIT (`HYPOTHESE_UNITE_PRIX`) et porte la réserve
`REJ-AP-UNITE-PRIX-NON-CONFIRMEE` sur tout attendu et tout rapprochement, même concordant. Cette réserve ne se retire
que par une décision de Nathan et un changement de code, jamais d'elle-même.

FAIL-CLOSED. Une pièce absente (prix du PO, devise autre que CAD, montant illisible) n'est jamais remplacée : elle
devient un code de la liste `manque`, et l'attendu (donc le « à payer ») est « non calculable » (`None`), jamais zéro.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any

from . import encodage, taxes, validation

__all__ = [
    "CODE_UNITE_PRIX",
    "HYPOTHESE_UNITE_PRIX",
    "TYPE_EVENEMENT_RECEPTION",
    "construire_reception",
    "enregistrer_reception",
    "lister",
    "proposer_rapprochement",
    "saisir_facture_fournisseur",
    "synthese_du_po",
    "vue_facture",
]

# Type du catalogue du socle (`src/opsys/evenements/catalogue/m6.reception_enregistree.json`) : M6 en est le seul
# producteur. Le nom seulement : l'abonnement (`opsys.evenements`) reste dans `outils.py`.
TYPE_EVENEMENT_RECEPTION = "m6.reception_enregistree"

CODE_UNITE_PRIX = "REJ-AP-UNITE-PRIX-NON-CONFIRMEE"
HYPOTHESE_UNITE_PRIX = (
    "l'unité des prix du livre de prix M6 n'est pas déclarée (GATE NATHAN) : chaque montant attendu suppose un prix "
    "par unité de la quantité reçue, sans aucune conversion ; à confirmer avant de s'y fier"
)
_HYPOTHESE_TAXES = (
    "les taxes attendues sont recalculées (TPS et TVQ, taux versionnés) sur le total avant taxes ; celles d'une "
    "facture saisie sont celles recalculées à la saisie"
)
_ORDRE = "première réception croissante (le plus ancien d'abord), puis po_id croissant"

_TYPE_RECEPTION = "reception_recue"
_TYPE_FACTURE = "facture_fournisseur_saisie"
_DEVISE = "CAD"
_STATUT_FACTURE = "SAISIE"
_STATUT_RAPPROCHEMENT = "PROPOSE"
_VOIES_HUMAINES = frozenset({"appareil", "approbation"})
_VERDICTS_RECEPTION = frozenset({"CONFORME", "RECEPTION_INFERIEURE", "RECEPTION_SUPERIEURE", "RECEPTION_MIXTE"})
_STATUTS_PO = frozenset({"received", "partially_received"})

_CENT = Decimal("0.01")
_ZERO = Decimal("0")
# Précision d'un produit quantité × prix : deux textes de 40 caractères au plus (`_LONGUEUR_TEXTE_MAX`) tiennent
# largement sous 80 chiffres significatifs. La précision par défaut de `decimal` (28) aurait pu arrondir le produit
# AVANT l'arrondi au cent : ce serait une erreur silencieuse sur de l'argent.
_CONTEXTE = Context(prec=80)
# Ordre de grandeur au-delà duquel un montant est illisible : 10^12 dollars. Un chantier de rénovation n'en approche
# jamais ; ce plafond garde tout calcul dans la précision de `decimal` (jamais une exception d'arithmétique).
_EXPOSANT_MAX = 11
_LONGUEUR_TEXTE_MAX = 40

_TEXTE_DECIMAL = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_TEXTE_MONTANT = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,2})?$")
_DATE_ISO = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_LONGUEUR_ID_FACTURE = 20
_LONGUEUR_NUMERO_MAX = 64


# --------------------------------------------------------------------------------------- petits outils
def _verdict(code: str, detail: str = "") -> dict[str, Any]:
    return validation.construire_verdict(code, detail=detail)


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _decimal_du_texte(valeur: Any) -> Decimal | None:
    """Un texte décimal positionnel, zéro ou plus, comme l'exige le schéma du catalogue ; `None` sinon.

    Un nombre JSON, un signe, une notation scientifique, un texte de plus de `_LONGUEUR_TEXTE_MAX` caractères sont
    refusés : la charge est du texte (jamais un float, dont la lecture varie d'un consommateur à l'autre)."""
    if not isinstance(valeur, str) or len(valeur) > _LONGUEUR_TEXTE_MAX or _TEXTE_DECIMAL.fullmatch(valeur) is None:
        return None
    return Decimal(valeur)


def _au_cent(produit: Decimal) -> Decimal | None:
    """Arrondi au cent, `ROUND_HALF_UP` ; `None` si le montant sort du plafond de lecture."""
    if produit.adjusted() > _EXPOSANT_MAX:
        return None
    return produit.quantize(_CENT, rounding=ROUND_HALF_UP, context=_CONTEXTE)


def _montant_ligne(quantite: Decimal, prix: Decimal) -> Decimal | None:
    return _au_cent(_CONTEXTE.multiply(quantite, prix))


def _texte(valeur: Decimal | None) -> str | None:
    """Représentation positionnelle d'un montant ou d'une quantité, pour une réponse JSON ; `None` reste `None`."""
    return None if valeur is None else format(valeur, "f")


def _somme(valeurs: Iterable[Decimal]) -> Decimal:
    """Somme de montants au cent, rendue au cent (une somme vide vaut `0.00`, jamais `0`)."""
    return sum(valeurs, _ZERO).quantize(_CENT, rounding=ROUND_HALF_UP)


def _instant(horodatage: str) -> datetime:
    return datetime.fromisoformat(horodatage)


def _normaliser_numero(numero: str) -> str:
    """Forme de comparaison d'un numéro de facture : espaces réduits, casse ignorée. Rien d'autre : `00123` et `123`
    restent deux numéros (deviner qu'ils sont le même serait inventer)."""
    return " ".join(numero.split()).casefold()


# --------------------------------------------------------------------------------- réception reçue
def _ligne_recue(brute: Any, index: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Une ligne de la charge -> une ligne de réception avec son montant attendu, ou le refus qui nomme la ligne."""
    def refus(detail: str) -> tuple[None, dict[str, Any]]:
        return None, _verdict("REJ-AP-RECEPTION-INVALIDE", f"ligne {index} : {detail}")

    if not isinstance(brute, Mapping):
        return refus("objet attendu")
    materiau_id = brute.get("materiau_id")
    if not _texte_non_vide(materiau_id):
        return refus("materiau_id requis, non vide")
    quantite_demandee = _decimal_du_texte(brute.get("quantite_demandee"))
    quantite_recue = _decimal_du_texte(brute.get("quantite_recue"))
    if quantite_demandee is None or quantite_recue is None:
        return refus("quantite_demandee et quantite_recue doivent être du texte décimal, zéro ou plus")
    prix_prevu = None
    if brute.get("prix_unitaire_prevu") is not None:
        prix_prevu = _decimal_du_texte(brute["prix_unitaire_prevu"])
        if prix_prevu is None or prix_prevu <= 0:
            return refus("prix_unitaire_prevu doit être du texte décimal strictement positif, ou nul")
    prix_reception = None
    if brute.get("prix_unitaire_reception") is not None:
        prix_reception = _decimal_du_texte(brute["prix_unitaire_reception"])
        if prix_reception is None or prix_reception <= 0:
            return refus("prix_unitaire_reception doit être du texte décimal strictement positif, ou nul")
    devise = brute.get("devise_prevue")
    ecart_critique = brute.get("ecart_prix_critique")
    if devise is not None and not isinstance(devise, str):
        return refus("devise_prevue doit être du texte, ou nulle")
    if ecart_critique is not None and not isinstance(ecart_critique, bool):
        return refus("ecart_prix_critique doit être un booléen, ou nul")
    verdicts = (brute.get("verdict_prix_po"), brute.get("verdict_prix_reception"))
    if not all(_texte_non_vide(v) for v in verdicts):
        return refus("verdict_prix_po et verdict_prix_reception requis")

    manque: list[str] = []
    montant = None
    if prix_prevu is None:
        manque.append("REJ-AP-PRIX-PO-ABSENT")
    elif devise is None or devise.strip().upper() != _DEVISE:
        manque.append("REJ-AP-DEVISE-NON-CAD")
    else:
        montant = _montant_ligne(quantite_recue, prix_prevu)
        if montant is None:
            manque.append("REJ-AP-MONTANT-ILLISIBLE")
    ecart_prix = prix_reception - prix_prevu if prix_reception is not None and prix_prevu is not None else None
    return {
        "materiau_id": materiau_id,
        "quantite_demandee": quantite_demandee,
        "quantite_recue": quantite_recue,
        "prix_unitaire_prevu": prix_prevu,
        "devise_prevue": devise,
        "montant_attendu": montant,
        "prix_unitaire_reception": prix_reception,
        "verdict_prix_reception": verdicts[1],
        "ecart_prix_unitaire": ecart_prix,
        "ecart_prix_critique": ecart_critique,
        "manque": manque,
    }, None


def construire_reception(charge: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(entrée du registre, None)` pour une charge `m6.reception_enregistree`, ou `(None, verdict)`.

    La charge est déjà validée par le catalogue du socle à la publication ; elle est REVALIDÉE ici, parce qu'un
    consommateur ne fait pas confiance à ce qu'il reçoit (AGENTS.md, fail-closed) : `REJ-AP-RECEPTION-INVALIDE`
    LÈVE côté `outils.py` (le répartiteur réessaie puis met en quarantaine, visible d'un humain), jamais une
    réception à moitié comprise. Ce qui ne peut pas être chiffré (prix du PO absent, devise autre que CAD) n'est PAS
    un refus : c'est un code de `manque`, et le montant attendu de la réception est `None` (jamais zéro)."""
    if not isinstance(charge, Mapping):
        return None, _verdict("REJ-AP-RECEPTION-INVALIDE", "la charge doit être un objet")
    for champ in ("evenement_id", "po_id", "fournisseur_id", "chantier_id", "hash_maillon"):
        if not _texte_non_vide(charge.get(champ)):
            return None, _verdict("REJ-AP-RECEPTION-INVALIDE", f"{champ} requis, non vide")
    horodatage = charge.get("horodatage_reception")
    try:
        instant = _instant(horodatage)
    except (TypeError, ValueError):
        instant = None
    if instant is None or instant.tzinfo is None:
        return None, _verdict("REJ-AP-RECEPTION-INVALIDE", "horodatage_reception : RFC 3339 avec fuseau requis")
    if charge.get("verdict_reception") not in _VERDICTS_RECEPTION or charge.get("statut_po") not in _STATUTS_PO:
        return None, _verdict("REJ-AP-RECEPTION-INVALIDE", "verdict_reception ou statut_po inconnu")
    lignes_brutes = charge.get("lignes")
    if not isinstance(lignes_brutes, list) or not lignes_brutes:
        return None, _verdict("REJ-AP-RECEPTION-INVALIDE", "au moins une ligne est requise")

    lignes = []
    for index, brute in enumerate(lignes_brutes):
        ligne, verdict = _ligne_recue(brute, index)
        if verdict is not None:
            return None, verdict
        lignes.append(ligne)
    montants = [ligne["montant_attendu"] for ligne in lignes]
    complet = all(montant is not None for montant in montants)
    return {
        "type_entree": _TYPE_RECEPTION,
        "evenement_id": charge["evenement_id"],
        "po_id": charge["po_id"],
        "fournisseur_id": charge["fournisseur_id"],
        "chantier_id": charge["chantier_id"],
        "horodatage_reception": horodatage,
        "verdict_reception": charge["verdict_reception"],
        "statut_po": charge["statut_po"],
        "hash_maillon": charge["hash_maillon"],
        "lignes": lignes,
        "montant_avant_taxes": _somme(montants) if complet else None,
        "manque": sorted({code for ligne in lignes for code in ligne["manque"]}),
        "horodatage": horodatage,
    }, None


def _retrouver(registre_cible: Any, ligne_id: str) -> dict[str, Any]:
    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return maillon
    raise RuntimeError("Maillon ajouté introuvable.")


def enregistrer_reception(
    entree: Mapping[str, Any], registre_cible: Any
) -> tuple[tuple[dict[str, Any], bool] | None, dict[str, Any] | None]:
    """`((maillon, deja_recue), None)` : range la réception au registre, une seule fois par `evenement_id` (une
    redélivrance rend le premier maillon et `deja_recue` vrai, sans rien écrire) ; ou `(None, verdict)` si le PO est
    déjà connu sous un AUTRE fournisseur ou un AUTRE chantier (`REJ-AP-PO-INCOHERENT` : un même bon de commande n'a
    qu'un fournisseur ; laisser passer, ce serait devoir de l'argent à deux fournisseurs pour le même PO)."""
    maillons = registre_cible.lire()
    for maillon in maillons:
        if maillon.get("type_entree") == _TYPE_RECEPTION and maillon["evenement_id"] == entree["evenement_id"]:
            return (maillon, True), None
    for maillon in maillons:
        if maillon.get("type_entree") != _TYPE_RECEPTION or maillon["po_id"] != entree["po_id"]:
            continue
        if maillon["fournisseur_id"] != entree["fournisseur_id"] or maillon["chantier_id"] != entree["chantier_id"]:
            return None, _verdict(
                "REJ-AP-PO-INCOHERENT",
                f"le PO {entree['po_id']!r} est déjà connu chez {maillon['fournisseur_id']!r} "
                f"(chantier {maillon['chantier_id']!r}), la réception dit {entree['fournisseur_id']!r} "
                f"(chantier {entree['chantier_id']!r})",
            )
    ligne_id = registre_cible.ajouter(dict(entree))
    return (_retrouver(registre_cible, ligne_id), False), None


# ----------------------------------------------------------------------------- facture fournisseur
def _montant_saisi(valeur: Any, nom: str, *, strictement_positif: bool) -> tuple[Decimal | None, dict | None]:
    """Un montant tapé par un humain : texte décimal, 2 décimales au plus, jamais un signe ni un exposant."""
    if not isinstance(valeur, str) or _TEXTE_MONTANT.fullmatch(valeur) is None:
        return None, _verdict(
            "REJ-AP-FACTURE-MONTANT-INVALIDE",
            f"{nom} doit être un montant en texte décimal (ex. \"1234.50\"), 2 décimales au plus, sans signe",
        )
    montant = Decimal(valeur)
    if strictement_positif and montant <= 0:
        return None, _verdict("REJ-AP-FACTURE-MONTANT-INVALIDE", f"{nom} doit être strictement positif")
    return montant, None


def _po_connu(maillons: Iterable[Mapping[str, Any]], po_id: str) -> dict[str, Any] | None:
    """Le fournisseur et le chantier d'un PO, tels que sa première réception les a dits ; `None` si M5 n'a reçu
    aucune réception de ce PO."""
    for maillon in maillons:
        if maillon.get("type_entree") == _TYPE_RECEPTION and maillon["po_id"] == po_id:
            return {"fournisseur_id": maillon["fournisseur_id"], "chantier_id": maillon["chantier_id"]}
    return None


def saisir_facture_fournisseur(
    *,
    po_id: Any,
    fournisseur_id: Any,
    numero_facture: Any,
    date_facture: Any,
    montant_avant_taxes: Any,
    total_facture: Any,
    saisi_par: Any,
    voie: Any,
    horodatage: Any,
    dictionnaire_taux: Mapping[str, Mapping[str, Any]],
    registre_cible: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`({"facture": maillon, "avertissements": [codes]}, None)` : range une facture fournisseur SAISIE par un humain ;
    ou `(None, verdict)` sans rien écrire.

    Ordre des refus, du plus bête au plus fin : champs texte, humain identifié (`saisi_par`, `voie` : l'identité est
    établie par `outils.py`, jamais lue d'un argument), dates, montants, taux, PO connu, fournisseur du PO, doublon.

    - `montant_avant_taxes` est ce qu'un humain tape ; les TAXES, le total après taxes en sont RECALCULÉS
      (`taxes.calculer_taxes`, taux versionnés). `total_facture`, le total imprimé sur la facture, est un contrôle
      optionnel : fourni, il doit égaler le total recalculé (`REJ-AP-FACTURE-TOTAL-INCOHERENT`), sinon la saisie est
      refusée et le détail donne les deux chiffres.
    - le PO doit avoir été reçu, au moins en partie (`REJ-AP-FACTURE-PO-SANS-RECEPTION`) et appartenir au fournisseur
      dit sur la facture (`REJ-AP-FACTURE-FOURNISSEUR-DIFFERENT-DU-PO`).
    - DOUBLON (`REJ-AP-FACTURE-DOUBLON`) : même fournisseur, même numéro (espaces et casse ignorés), même montant
      avant taxes, quel que soit le PO. Même fournisseur et même numéro avec un AUTRE montant n'est pas un doublon :
      la saisie passe avec l'avertissement `REJ-AP-FACTURE-NUMERO-REPETE` (ni correction ni annulation n'existent ici :
      refuser bloquerait la bonne facture ; le rapprochement montrera l'écart).
    - la facture entre au statut `SAISIE`. Aucun autre statut n'existe : ni « approuvée », ni « payée »."""
    for champ, valeur in (("po_id", po_id), ("fournisseur_id", fournisseur_id), ("numero_facture", numero_facture)):
        if not _texte_non_vide(valeur):
            return None, _verdict("REJ-AP-FACTURE-CHAMP-INVALIDE", f"{champ} requis, non vide")
    po_id, fournisseur_id, numero_facture = po_id.strip(), fournisseur_id.strip(), numero_facture.strip()
    if len(numero_facture) > _LONGUEUR_NUMERO_MAX or not numero_facture.isprintable():
        return None, _verdict(
            "REJ-AP-FACTURE-CHAMP-INVALIDE",
            f"numero_facture : {_LONGUEUR_NUMERO_MAX} caractères imprimables au plus, tel qu'imprimé sur la facture",
        )
    if voie not in _VOIES_HUMAINES or not _texte_non_vide(saisi_par):
        return None, _verdict(
            "REJ-AP-HUMAIN-REQUIS",
            "la facture est saisie par un humain identifié (jeton d'appareil ou approbation), jamais par un agent seul",
        )

    if not isinstance(horodatage, str):
        return None, _verdict("REJ-AP-FACTURE-HORODATAGE-INVALIDE", "horodatage : RFC 3339 avec fuseau requis")
    try:
        instant_saisie = _instant(horodatage)
    except ValueError:
        instant_saisie = None
    if instant_saisie is None or instant_saisie.tzinfo is None:
        return None, _verdict("REJ-AP-FACTURE-HORODATAGE-INVALIDE", "horodatage : RFC 3339 avec fuseau requis")
    if not isinstance(date_facture, str) or _DATE_ISO.fullmatch(date_facture) is None:
        return None, _verdict(
            "REJ-AP-FACTURE-DATE-INVALIDE", "date_facture : AAAA-MM-JJ, telle qu'imprimée sur la facture"
        )
    try:
        jour_facture = date.fromisoformat(date_facture)
    except ValueError:
        return None, _verdict("REJ-AP-FACTURE-DATE-INVALIDE", f"date_facture n'est pas une date : {date_facture!r}")
    if jour_facture > instant_saisie.date():
        return None, _verdict(
            "REJ-AP-FACTURE-DATE-FUTURE",
            f"date_facture ({date_facture}) postérieure au jour de la saisie ({instant_saisie.date().isoformat()})",
        )

    montant, verdict = _montant_saisi(montant_avant_taxes, "montant_avant_taxes", strictement_positif=True)
    if verdict is not None:
        return None, verdict
    total_imprime = None
    if total_facture is not None:
        total_imprime, verdict = _montant_saisi(total_facture, "total_facture", strictement_positif=True)
        if verdict is not None:
            return None, verdict
    calcul, verdict = taxes.calculer_taxes(montant, dictionnaire_taux)
    if verdict is not None:
        return None, verdict
    if total_imprime is not None and total_imprime != calcul["montant_apres_taxes"]:
        return None, _verdict(
            "REJ-AP-FACTURE-TOTAL-INCOHERENT",
            f"le total imprimé ({total_imprime}) diffère du total recalculé ({calcul['montant_apres_taxes']} = "
            f"{montant} + taxes {calcul['total_taxes']}) : vérifier la facture et les montants tapés",
        )

    maillons = registre_cible.lire()
    po = _po_connu(maillons, po_id)
    if po is None:
        return None, _verdict(
            "REJ-AP-FACTURE-PO-SANS-RECEPTION",
            f"aucune réception du PO {po_id!r} n'est connue de M5 : enregistrer la réception dans M6 d'abord",
        )
    if po["fournisseur_id"] != fournisseur_id:
        return None, _verdict(
            "REJ-AP-FACTURE-FOURNISSEUR-DIFFERENT-DU-PO",
            f"le PO {po_id!r} est au fournisseur {po['fournisseur_id']!r}, la facture dit {fournisseur_id!r}",
        )

    avertissements: list[str] = []
    numero_normalise = _normaliser_numero(numero_facture)
    for existante in maillons:
        if (
            existante.get("type_entree") != _TYPE_FACTURE
            or existante["fournisseur_id"] != fournisseur_id
            or _normaliser_numero(existante["numero_facture"]) != numero_normalise
        ):
            continue
        if existante["montant_avant_taxes"] == montant:
            return None, _verdict(
                "REJ-AP-FACTURE-DOUBLON",
                f"la facture {numero_facture!r} de {fournisseur_id!r} ({montant} avant taxes) est déjà saisie "
                f"({existante['facture_fournisseur_id']}, PO {existante['po_id']!r}, le "
                f"{existante['date_facture']})",
            )
        avertissements = ["REJ-AP-FACTURE-NUMERO-REPETE"]

    facture = {
        "type_entree": _TYPE_FACTURE,
        # Identifiant DÉTERMINISTE de (fournisseur, numéro, montant) : le montant s'écrit d'une seule façon
        # (« 12.5 » et « 12.50 » sont le même montant), comme la comparaison des doublons.
        "facture_fournisseur_id": "apf-" + encodage.empreinte(
            fournisseur_id, numero_normalise, _texte(_au_cent(montant))
        )[:_LONGUEUR_ID_FACTURE],
        "po_id": po_id,
        "fournisseur_id": fournisseur_id,
        "numero_facture": numero_facture,
        "date_facture": date_facture,
        "montant_avant_taxes": montant,
        "taxes": list(calcul["taxes"]),
        "total_taxes": calcul["total_taxes"],
        "montant_apres_taxes": calcul["montant_apres_taxes"],
        "statut": _STATUT_FACTURE,
        "saisi_par": saisi_par,
        "voie": voie,
        "avertissements": avertissements,
        "horodatage": horodatage,
    }
    ligne_id = registre_cible.ajouter(facture)
    return {"facture": _retrouver(registre_cible, ligne_id), "avertissements": avertissements}, None


def vue_facture(maillon: Mapping[str, Any]) -> dict[str, Any]:
    """Ce qu'une réponse dit d'une facture saisie : la pièce, sans les empreintes du registre. Les montants restent des
    `Decimal` (l'enveloppe des outils les rend en texte)."""
    return {
        cle: maillon[cle]
        for cle in (
            "facture_fournisseur_id", "po_id", "fournisseur_id", "numero_facture", "date_facture",
            "montant_avant_taxes", "taxes", "total_taxes", "montant_apres_taxes", "statut", "saisi_par", "voie",
            "avertissements", "horodatage",
        )
    }


# ------------------------------------------------------------------ état par PO et rapprochement
def _pos(maillons: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Les PO connus, chacun avec ses réceptions et ses factures, dans l'ordre du registre."""
    par_po: dict[str, dict[str, Any]] = {}
    for maillon in maillons:
        type_entree = maillon.get("type_entree")
        if type_entree == _TYPE_RECEPTION:
            po = par_po.setdefault(maillon["po_id"], {
                "po_id": maillon["po_id"], "fournisseur_id": maillon["fournisseur_id"],
                "chantier_id": maillon["chantier_id"], "receptions": [], "factures": []})
            po["receptions"].append(maillon)
            po["statut_po"] = maillon["statut_po"]
        elif type_entree == _TYPE_FACTURE and maillon["po_id"] in par_po:
            par_po[maillon["po_id"]]["factures"].append(maillon)
    return par_po


def _commande_avant_taxes(derniere: Mapping[str, Any]) -> Decimal | None:
    """Valeur du PO au prix du PO, depuis la dernière réception (chacune porte TOUTES les lignes du PO, que M6 gèle à
    sa création) ; `None` si un prix manque ou n'est pas en CAD."""
    montants = []
    for ligne in derniere["lignes"]:
        prix, devise = ligne["prix_unitaire_prevu"], ligne["devise_prevue"]
        if prix is None or devise is None or devise.strip().upper() != _DEVISE:
            return None
        montant = _montant_ligne(ligne["quantite_demandee"], prix)
        if montant is None:
            return None
        montants.append(montant)
    return _somme(montants)


def _quantites(po: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Quantités commandées et reçues (cumulées sur les livraisons) par matériau, dans l'ordre du PO. Aucune unité."""
    recues: dict[str, Decimal] = {}
    for reception in po["receptions"]:
        for ligne in reception["lignes"]:
            recues[ligne["materiau_id"]] = recues.get(ligne["materiau_id"], _ZERO) + ligne["quantite_recue"]
    return [
        {
            "materiau_id": ligne["materiau_id"],
            "commandee": ligne["quantite_demandee"],
            "recue": recues[ligne["materiau_id"]],
            "ecart": recues[ligne["materiau_id"]] - ligne["quantite_demandee"],
        }
        for ligne in po["receptions"][-1]["lignes"]
    ]


def synthese_du_po(
    po: Mapping[str, Any], dictionnaire_taux: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """L'attendu, le facturé, le « à payer » et le rapprochement PROPOSÉ d'un PO, calculés depuis le registre.

    `(None, verdict)` seulement si un taux fiscal manque (`REJ-TAUX-INCONNU`) : rien n'est alors chiffré à demi. Les
    montants sont des `Decimal` (ou `None` : non calculable, avec la liste `manque`)."""
    receptions, factures = po["receptions"], po["factures"]
    manque = sorted({code for reception in receptions for code in reception["manque"]})
    montants_recus = [reception["montant_avant_taxes"] for reception in receptions]
    recu_avant = _somme(montants_recus) if all(m is not None for m in montants_recus) else None
    recu_taxes = recu_apres = None
    if recu_avant is not None:
        calcul, verdict = taxes.calculer_taxes(recu_avant, dictionnaire_taux)
        if verdict is not None:
            return None, verdict
        recu_taxes, recu_apres = calcul["total_taxes"], calcul["montant_apres_taxes"]
    commande_avant = _commande_avant_taxes(receptions[-1])
    facture_avant = _somme(f["montant_avant_taxes"] for f in factures)
    facture_taxes = _somme(f["total_taxes"] for f in factures)
    facture_apres = _somme(f["montant_apres_taxes"] for f in factures)

    non_facture_avant = non_facture_apres = a_payer = None
    if recu_avant is not None:
        non_facture_avant = max(recu_avant - facture_avant, _ZERO)
        calcul, verdict = taxes.calculer_taxes(non_facture_avant, dictionnaire_taux)
        if verdict is not None:
            return None, verdict
        non_facture_apres = calcul["montant_apres_taxes"]
        a_payer = _somme([facture_apres, non_facture_apres])

    quantites = _quantites(po)
    reserves = [CODE_UNITE_PRIX]
    if any(f["avertissements"] for f in factures):
        reserves.append("REJ-AP-FACTURE-NUMERO-REPETE")
    rapprochement = {
        "statut": _STATUT_RAPPROCHEMENT,
        "verdict": None,
        "sens": None,
        "commande_avant_taxes": commande_avant,
        "recu_avant_taxes": recu_avant,
        "facture_avant_taxes": facture_avant if factures else None,
        "facture_moins_recu": facture_avant - recu_avant if recu_avant is not None and factures else None,
        "recu_moins_commande": recu_avant - commande_avant if recu_avant is not None and commande_avant is not None
        else None,
        "reste_a_recevoir": [
            {"materiau_id": q["materiau_id"], "quantite": -q["ecart"]} for q in quantites if q["ecart"] < 0
        ],
        "en_excedent": [
            {"materiau_id": q["materiau_id"], "quantite": q["ecart"]} for q in quantites if q["ecart"] > 0
        ],
        "reserves": reserves,
    }
    if recu_avant is None:
        rapprochement["verdict"] = "INCOMPLET"
    elif not factures:
        rapprochement["verdict"] = "SANS_FACTURE"
    elif facture_avant == recu_avant:
        rapprochement["verdict"] = "CONCORDANT"
    else:
        rapprochement["verdict"] = "ECART"
        rapprochement["sens"] = (
            "FACTURE_SUPERIEURE_AU_RECU" if facture_avant > recu_avant else "FACTURE_INFERIEURE_AU_RECU"
        )
    return {
        "po_id": po["po_id"],
        "fournisseur_id": po["fournisseur_id"],
        "chantier_id": po["chantier_id"],
        "statut_po": po["statut_po"],
        "receptions": receptions,
        "premiere_reception": receptions[0]["horodatage_reception"],
        "derniere_reception": receptions[-1]["horodatage_reception"],
        "attendu": {"avant_taxes": recu_avant, "taxes": recu_taxes, "apres_taxes": recu_apres, "manque": manque},
        "facture": {
            "nombre": len(factures), "avant_taxes": facture_avant, "taxes": facture_taxes, "apres_taxes": facture_apres,
        },
        "a_payer": {
            "apres_taxes": a_payer, "facture_apres_taxes": facture_apres, "attendu_non_facture_apres_taxes":
            non_facture_apres, "manque": manque,
        },
        "commande_avant_taxes": commande_avant,
        "quantites": quantites,
        "factures": factures,
        "rapprochement": rapprochement,
    }, None


# ------------------------------------------------------------------------------------- vues JSON
def _vue_rapprochement(rapprochement: Mapping[str, Any]) -> dict[str, Any]:
    vue = {
        "statut": rapprochement["statut"],
        "verdict": rapprochement["verdict"],
        "commande_avant_taxes": _texte(rapprochement["commande_avant_taxes"]),
        "recu_avant_taxes": _texte(rapprochement["recu_avant_taxes"]),
        "facture_avant_taxes": _texte(rapprochement["facture_avant_taxes"]),
        "facture_moins_recu": _texte(rapprochement["facture_moins_recu"]),
        "recu_moins_commande": _texte(rapprochement["recu_moins_commande"]),
        "reserves": list(rapprochement["reserves"]),
    }
    if rapprochement["sens"] is not None:
        vue["sens"] = rapprochement["sens"]
    for cle in ("reste_a_recevoir", "en_excedent"):
        if rapprochement[cle]:
            vue[cle] = [
                {"materiau_id": q["materiau_id"], "quantite": _texte(q["quantite"])} for q in rapprochement[cle]
            ]
    return vue


def _vue_facture_liste(maillon: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "facture_fournisseur_id": maillon["facture_fournisseur_id"],
        "numero_facture": maillon["numero_facture"],
        "date_facture": maillon["date_facture"],
        "avant_taxes": _texte(maillon["montant_avant_taxes"]),
        "taxes": _texte(maillon["total_taxes"]),
        "apres_taxes": _texte(maillon["montant_apres_taxes"]),
        "saisi_par": maillon["saisi_par"],
        "avertissements": list(maillon["avertissements"]),
    }


def vue_synthese(synthese: Mapping[str, Any], *, detail: bool) -> dict[str, Any]:
    """Une ligne de la liste (`detail` faux) ou le détail d'un PO (`detail` vrai : quantités, factures, réceptions).
    Tout est du texte (montants et quantités), jamais un nombre JSON."""
    attendu, facture, a_payer = synthese["attendu"], synthese["facture"], synthese["a_payer"]
    vue = {
        "po_id": synthese["po_id"],
        "fournisseur_id": synthese["fournisseur_id"],
        "chantier_id": synthese["chantier_id"],
        "statut_po": synthese["statut_po"],
        "receptions": len(synthese["receptions"]),
        "derniere_reception": synthese["derniere_reception"],
        "attendu": {
            "avant_taxes": _texte(attendu["avant_taxes"]), "taxes": _texte(attendu["taxes"]),
            "apres_taxes": _texte(attendu["apres_taxes"]),
        },
        "factures": {
            "nombre": facture["nombre"], "avant_taxes": _texte(facture["avant_taxes"]),
            "taxes": _texte(facture["taxes"]), "apres_taxes": _texte(facture["apres_taxes"]),
        },
        "a_payer_apres_taxes": _texte(a_payer["apres_taxes"]),
        "rapprochement": _vue_rapprochement(synthese["rapprochement"]),
    }
    if attendu["manque"]:
        vue["manque"] = list(attendu["manque"])
    if detail:
        vue["premiere_reception"] = synthese["premiere_reception"]
        vue["commande_avant_taxes"] = _texte(synthese["commande_avant_taxes"])
        vue["attendu_non_facture_apres_taxes"] = _texte(a_payer["attendu_non_facture_apres_taxes"])
        vue["quantites"] = [
            {"materiau_id": q["materiau_id"], "commandee": _texte(q["commandee"]), "recue": _texte(q["recue"]),
             "ecart": _texte(q["ecart"])}
            for q in synthese["quantites"]
        ]
        vue["factures_saisies"] = [_vue_facture_liste(f) for f in synthese["factures"]]
        vue["livraisons"] = [
            {"evenement_id": r["evenement_id"], "horodatage": r["horodatage_reception"],
             "verdict": r["verdict_reception"], "avant_taxes": _texte(r["montant_avant_taxes"]),
             "lignes_avec_ecart_de_prix": [
                 {"materiau_id": ligne["materiau_id"], "ecart_prix_unitaire": _texte(ligne["ecart_prix_unitaire"])}
                 for ligne in r["lignes"] if ligne["ecart_prix_critique"]
             ]}
            for r in synthese["receptions"]
        ]
    return vue


def proposer_rapprochement(
    registre_cible: Any, dictionnaire_taux: Mapping[str, Mapping[str, Any]], po_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Le rapprochement PO / réception / facture PROPOSÉ d'un PO, en vue JSON, avec ses écarts et ses réserves.

    Une proposition, jamais un état : elle est recalculée à chaque lecture, n'est stockée nulle part, et rien ne
    l'« applique » (aucun statut rapproché ni approuvé n'existe). `(None, verdict)` si aucune réception de ce PO n'est
    connue, ou si un taux fiscal manque."""
    po = _pos(registre_cible.lire()).get(po_id)
    if po is None:
        return None, _verdict("REJ-AP-PO-INCONNU", f"aucune réception connue de M5 pour le PO {po_id!r}")
    synthese, verdict = synthese_du_po(po, dictionnaire_taux)
    if verdict is not None:
        return None, verdict
    return _vue_rapprochement(synthese["rapprochement"]), None


# ------------------------------------------------------------------------------------- la liste
def _taille(objet: Any) -> int:
    """Taille sérialisée EXACTE telle que `Capacites._tronquer` la mesure (`json.dumps`, sans échappement ASCII) : la
    borne se calcule sur ce que le modèle recevrait, jamais sur une estimation."""
    return len(json.dumps(objet, ensure_ascii=False))


def _totaux(syntheses: list[Mapping[str, Any]]) -> dict[str, Any]:
    calculables = [s for s in syntheses if s["a_payer"]["apres_taxes"] is not None]
    non_calculables = [s for s in syntheses if s["a_payer"]["apres_taxes"] is None]
    # Le plancher : ce qui est CERTAIN. Un PO calculable compte pour son « à payer » ; un PO non calculable compte au
    # moins pour ce qui est déjà FACTURÉ (une dette ferme, quoi qu'il manque au reste), jamais pour zéro.
    a_payer_connu = _somme(
        s["a_payer"]["apres_taxes"] if s["a_payer"]["apres_taxes"] is not None else s["facture"]["apres_taxes"]
        for s in syntheses
    )
    complet = not non_calculables
    return {
        "nombre_po": len(syntheses),
        "attendu_apres_taxes": _texte(_somme(s["attendu"]["apres_taxes"] for s in calculables)) if complet else None,
        "facture_apres_taxes": _texte(_somme(s["facture"]["apres_taxes"] for s in syntheses)),
        "a_payer_apres_taxes": _texte(a_payer_connu) if complet else None,
        "a_payer_connu_apres_taxes": _texte(a_payer_connu),
        "complet": complet,
        "non_calculables": len(non_calculables),
        "non_calculables_po": [
            {"po_id": s["po_id"], "manque": list(s["attendu"]["manque"])} for s in non_calculables[:5]
        ],
    }


def lister(
    registre_cible: Any,
    dictionnaire_taux: Mapping[str, Mapping[str, Any]],
    *,
    depart: Any = 0,
    budget_caracteres: int,
    po_id: Any = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Une page des comptes à payer, PAR PO, avec l'attendu, le facturé, le « à payer » et le rapprochement proposé.

    Lecture pure : n'écrit rien. Ordre stable et total (`_ORDRE`). `depart` est un rang dans la liste complète
    (entier ≥ 0, 0 par défaut) ; la page contient autant de PO que `budget_caracteres` en laisse tenir (taille
    sérialisée mesurée, jamais estimée ; au moins un). `prochain_depart` est le rang à demander ensuite, `None` à la
    fin ; `reste` compte ce qui n'est pas affiché. Un PO ajouté entre deux pages peut décaler les suivantes : `total`
    change alors, et l'appelant relit depuis 0. `po_id` donne le DÉTAIL d'un seul PO (`REJ-AP-PO-INCONNU` s'il n'en
    existe aucune réception).

    `totaux` porte sur TOUS les PO, pas seulement sur la page. Un PO dont l'attendu n'est pas calculable ne compte
    jamais pour zéro : `a_payer_apres_taxes` est alors `None` et `a_payer_connu_apres_taxes` n'est qu'un plancher.
    Refus nommés, sans rien rendre : `depart` invalide ou au-delà de la fin, taux fiscal manquant, un seul PO plus
    gros à lui seul que la borne."""
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        return None, _verdict(
            "REJ-AP-LISTE-DEPART-INVALIDE", f"depart : entier supérieur ou égal à 0 attendu, reçu {depart!r}"
        )
    pos = _pos(registre_cible.lire())
    if po_id is not None:
        if not _texte_non_vide(po_id) or po_id.strip() not in pos:
            return None, _verdict("REJ-AP-PO-INCONNU", f"aucune réception connue de M5 pour le PO {po_id!r}")
        pos = {po_id.strip(): pos[po_id.strip()]}
    syntheses = []
    for po in sorted(pos.values(), key=lambda p: (_instant(p["receptions"][0]["horodatage_reception"]), p["po_id"])):
        synthese, verdict = synthese_du_po(po, dictionnaire_taux)
        if verdict is not None:
            return None, verdict
        syntheses.append(synthese)
    total = len(syntheses)
    if depart > total:
        return None, _verdict(
            "REJ-AP-LISTE-DEPART-INVALIDE",
            f"depart {depart} au-delà de la fin ({total} PO connu(s)) : reprendre à depart=0 (le total a pu changer)",
        )
    detail = po_id is not None
    lignes = [vue_synthese(s, detail=detail) for s in syntheses]
    versions = {
        taux_id: taux["version"] for taux_id, taux in sorted(dictionnaire_taux.items())
        if taux_id in ("tps_federale", "tvq_quebec")
    }
    totaux = _totaux(syntheses)

    def page(nombre: int) -> dict[str, Any]:
        fin = depart + nombre
        reste = total - fin
        return {
            "type": "COMPTES_A_PAYER",
            "ordre": _ORDRE,
            "hypotheses": [HYPOTHESE_UNITE_PRIX, _HYPOTHESE_TAXES],
            "taxes_versions": versions,
            "totaux": totaux,
            "total": total,
            "depart": depart,
            "affichees": nombre,
            "reste": reste,
            "prochain_depart": fin if reste else None,
            "message": None if not reste else f"{reste} PO non affiché(s) : poursuivre avec depart={fin}.",
            "comptes": lignes[depart:fin],
        }

    nombre = 0
    while depart + nombre < total and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if depart < total and nombre == 0:
        return None, _verdict(
            "REJ-AP-LISTE-LIGNE-TROP-GROSSE",
            f"le PO {syntheses[depart]['po_id']!r} dépasse à lui seul la borne de {budget_caracteres} caractères",
        )
    return page(nombre), None
