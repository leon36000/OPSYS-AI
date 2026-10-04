"""Comptes à payer (M5.2, PLAN T4.15 ; DEFINITION-PRODUIT §7 M5.2 « comptes à payer » et M6.16 « pont finance »).

Ce que l'entreprise doit à ses fournisseurs. Module pur (ADR-0009, même règle que `facturation.py`) : aucun import
`opsys`, aucun import d'un autre département (DA-M5-04), aucune horloge, aucun aléa, aucun réseau. `outils.py`
(l'adaptateur, seul) lit le bus, le registre durable et l'identité ; ce module ne fait que valider, calculer et
décider.

TROIS CHOSES D'ORIGINE, UN SEUL REGISTRE (`comptes_a_payer`, DÉDIÉ : ni les mouvements, ni les factures clients) :

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

PLAN T4.15-c : QUATRE CHOSES DE PLUS, SUR LE MÊME REGISTRE.

4. CORRIGER OU ANNULER une facture saisie, sans jamais la modifier. Une correction (`correction_facture_fournisseur`)
   et une annulation (`annulation_facture_fournisseur`) sont des PIÈCES DE PLUS, chaînées au registre (la chaîne de
   hash reste valide), qui portent le motif (obligatoire), la personne, son rôle, la voie, l'avant et l'après. L'ÉTAT
   COURANT d'une facture (`SAISIE`, `CORRIGEE`, `ANNULEE`) est relu de ses pièces (`_etats_factures`) : c'est de cet
   état, et de lui seul, que partent le facturé, l'« à payer », le rapprochement, le doublon et les crédits de taxes du
   cash libre. Un REJEU n'a aucun effet : une correction qui ne change rien, une annulation déjà faite, sont refusées
   sans rien écrire. Un registre où une pièce vise une facture absente ou annulée LÈVE : jamais un chiffre à demi lu.
5. Une facture SANS PO (carburant, outils) : une dépense que M6 n'a pas commandée. Même saisie (humain, taxes
   recalculées, total imprimé en contrôle, doublon refusé parmi TOUTES les factures vivantes), avec une catégorie de la
   liste fermée que le propriétaire déclare ; sans liste : « catégories à configurer ». Aucun PO, aucune réception :
   c'est une dette ferme dès la saisie, comptée en entier dans les totaux, le résumé et le cash libre.
6. L'identifiant d'une facture reste unique au registre : celui d'avant (déterministe de fournisseur, numéro, montant)
   tant qu'il est libre, le rang suivant sinon (la même facture annulée puis ressaisie ; un numéro ou un montant que la
   correction d'une autre a libéré).
7. Aucune de ces écritures ne paie : annuler n'efface pas la dette (un PO reçu et non facturé redevient un « à payer
   attendu »), et rien n'écrit aux mouvements.

CE MODULE NE FAIT JAMAIS : payer. Aucune écriture au registre des mouvements, aucun DECAISSEMENT, aucun
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
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any

from . import analyse, encodage, taxes, validation

__all__ = [
    "CODE_NUMERO_REPETE",
    "CODE_UNITE_PRIX",
    "HYPOTHESE_UNITE_PRIX",
    "TYPE_EVENEMENT_RECEPTION",
    "annuler_facture_fournisseur",
    "construire_reception",
    "corriger_facture_fournisseur",
    "dettes_datables",
    "enregistrer_reception",
    "lire_categories_depense",
    "lister",
    "lister_sans_po",
    "factures_saisies",
    "proposer_rapprochement",
    "resume_a_payer",
    "saisir_facture_fournisseur",
    "saisir_facture_sans_po",
    "synthese_du_po",
    "totaux_sans_po",
    "verifier_facture_fournisseur",
    "vue_facture",
]

# Type du catalogue du socle (`src/opsys/evenements/catalogue/m6.reception_enregistree.json`) : M6 en est le seul
# producteur. Le nom seulement : l'abonnement (`opsys.evenements`) reste dans `outils.py`.
TYPE_EVENEMENT_RECEPTION = "m6.reception_enregistree"

CODE_UNITE_PRIX = "REJ-AP-UNITE-PRIX-NON-CONFIRMEE"
CODE_NUMERO_REPETE = "REJ-AP-FACTURE-NUMERO-REPETE"
HYPOTHESE_UNITE_PRIX = (
    "l'unité des prix du livre de prix M6 n'est pas déclarée (GATE NATHAN) : chaque montant attendu suppose un prix "
    "par unité de la quantité reçue, sans aucune conversion ; à confirmer avant de s'y fier"
)
_HYPOTHESE_TAXES = (
    "les taxes attendues sont recalculées (TPS et TVQ, taux versionnés) sur le total avant taxes ; celles d'une "
    "facture saisie sont celles recalculées à la saisie"
)
_ORDRE = "première réception croissante (le plus ancien d'abord), puis po_id croissant"
_ORDRE_SANS_PO = "ordre de saisie (la plus ancienne d'abord)"
_HYPOTHESE_SANS_PO = (
    "une facture sans PO est une dette ferme dès sa saisie : aucune réception ne la rapproche, sa catégorie vient de "
    "la liste configurée (GATE NATHAN), ses taxes sont celles recalculées à la saisie (crédit supposé à 100 %, à "
    "valider par le CPA)"
)

_TYPE_RECEPTION = "reception_recue"
_TYPE_FACTURE = "facture_fournisseur_saisie"
# PLAN T4.15-c : les deux pièces qui changent l'état d'une facture sans la modifier (voir `_etats_factures`).
_TYPE_CORRECTION = "correction_facture_fournisseur"
_TYPE_ANNULATION = "annulation_facture_fournisseur"
_DEVISE = "CAD"
_STATUT_FACTURE = "SAISIE"
_STATUT_CORRIGEE = "CORRIGEE"
_STATUT_ANNULEE = "ANNULEE"
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
_LONGUEUR_MOTIF_MAX = 300
_LONGUEUR_FOURNISSEUR_MAX = 64
_LONGUEUR_CATEGORIE_MAX = 32


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


def _humain_identifie(par: Any, voie: Any, role: Any, geste: str, *, role_exige: bool) -> dict[str, Any] | None:
    """`None` si `par`, `voie` (et `role`, quand la pièce l'exige : correction et annulation) décrivent un humain
    identifié ; sinon le refus `REJ-AP-HUMAIN-REQUIS`. L'identité est établie par `outils.py` (jeton d'appareil
    confirmé en base, ou décision approuvée dans la file), jamais lue d'un argument : ce module ne fait que refuser ce
    qui n'a pas la forme d'un humain."""
    if voie in _VOIES_HUMAINES and _texte_non_vide(par) and (not role_exige or _texte_non_vide(role)):
        return None
    return _verdict(
        "REJ-AP-HUMAIN-REQUIS",
        f"{geste} par un humain identifié (jeton d'appareil ou approbation), jamais par un agent seul",
    )


def _horodatage_valide(horodatage: Any) -> tuple[datetime | None, dict[str, Any] | None]:
    if isinstance(horodatage, str):
        try:
            instant = _instant(horodatage)
        except ValueError:
            instant = None
        if instant is not None and instant.tzinfo is not None:
            return instant, None
    return None, _verdict("REJ-AP-FACTURE-HORODATAGE-INVALIDE", "horodatage : RFC 3339 avec fuseau requis")


def _date_facture_valide(date_facture: Any, instant: datetime) -> dict[str, Any] | None:
    """`None` si la date est une vraie date AAAA-MM-JJ, au plus celle du jour de la saisie (ou de la correction)."""
    if not isinstance(date_facture, str) or _DATE_ISO.fullmatch(date_facture) is None:
        return _verdict("REJ-AP-FACTURE-DATE-INVALIDE", "date_facture : AAAA-MM-JJ, telle qu'imprimée sur la facture")
    try:
        jour_facture = date.fromisoformat(date_facture)
    except ValueError:
        return _verdict("REJ-AP-FACTURE-DATE-INVALIDE", f"date_facture n'est pas une date : {date_facture!r}")
    if jour_facture > instant.date():
        return _verdict(
            "REJ-AP-FACTURE-DATE-FUTURE",
            f"date_facture ({date_facture}) postérieure au jour de la saisie ({instant.date().isoformat()})",
        )
    return None


def _numero_valide(numero_facture: str) -> dict[str, Any] | None:
    """`None` si le numéro (déjà sans espaces aux bouts) est imprimable et de longueur raisonnable."""
    if len(numero_facture) > _LONGUEUR_NUMERO_MAX or not numero_facture.isprintable():
        return _verdict(
            "REJ-AP-FACTURE-CHAMP-INVALIDE",
            f"numero_facture : {_LONGUEUR_NUMERO_MAX} caractères imprimables au plus, tel qu'imprimé sur la facture",
        )
    return None


def _controler_total(
    montant: Decimal, total_facture: Any, dictionnaire_taux: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(calcul des taxes, None)` : les taxes et le total après taxes de `montant`, RECALCULÉS (taux versionnés). Le
    total imprimé sur la facture (`total_facture`), s'il est fourni, doit égaler le total recalculé au cent près
    (`REJ-AP-FACTURE-TOTAL-INCOHERENT`, avec les deux chiffres)."""
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
    return calcul, None


def _motif_valide(motif: Any) -> tuple[str | None, dict[str, Any] | None]:
    """Le motif d'une correction ou d'une annulation : OBLIGATOIRE, une ligne de texte imprimable, `_LONGUEUR_MOTIF_MAX`
    caractères au plus. Rendu sans espaces aux bouts."""
    if not _texte_non_vide(motif):
        return None, _verdict("REJ-AP-MOTIF-REQUIS", "le motif est obligatoire : dire pourquoi la facture change")
    motif = motif.strip()
    if len(motif) > _LONGUEUR_MOTIF_MAX or not motif.isprintable():
        return None, _verdict(
            "REJ-AP-MOTIF-REQUIS",
            f"motif : une ligne de texte imprimable, {_LONGUEUR_MOTIF_MAX} caractères au plus",
        )
    return motif, None


def _forme_de_comparaison(texte: str) -> str:
    """Forme de comparaison d'un fournisseur ou d'un numéro de facture : espaces réduits, casse ignorée."""
    return _normaliser_numero(texte)


def _chercher_doublon(
    etats: Mapping[str, Mapping[str, Any]], fournisseur_id: str, numero_facture: str, montant: Decimal,
    *, sauf_id: str | None = None,
) -> tuple[Mapping[str, Any] | None, list[str]]:
    """`(doublon, avertissements)` d'une facture qui aurait ce fournisseur, ce numéro et ce montant avant taxes.

    Ne comptent que les factures VIVANTES (une annulée n'existe plus : la ressaisir est le geste juste après une erreur
    d'annulation) et leurs valeurs COURANTES (une corrigée vaut ce que sa dernière correction dit). `sauf_id` écarte la
    facture qu'on corrige : elle ne se répète pas elle-même. Même fournisseur et même numéro (espaces et casse
    ignorés) avec un AUTRE montant : pas un doublon, l'avertissement `REJ-AP-FACTURE-NUMERO-REPETE`."""
    fournisseur, numero = _forme_de_comparaison(fournisseur_id), _forme_de_comparaison(numero_facture)
    avertissements: list[str] = []
    for etat in etats.values():
        if (
            etat["statut"] == _STATUT_ANNULEE
            or etat["facture_fournisseur_id"] == sauf_id
            or _forme_de_comparaison(etat["fournisseur_id"]) != fournisseur
            or _forme_de_comparaison(etat["numero_facture"]) != numero
        ):
            continue
        if etat["montant_avant_taxes"] == montant:
            return etat, []
        avertissements = [CODE_NUMERO_REPETE]
    return None, avertissements


def _ou_est_rangee(etat: Mapping[str, Any]) -> str:
    return f"PO {etat['po_id']!r}" if etat["po_id"] is not None else "sans PO"


def _refus_doublon(etat: Mapping[str, Any], fournisseur_id: str, numero_facture: str, montant: Decimal) -> dict:
    return _verdict(
        "REJ-AP-FACTURE-DOUBLON",
        f"la facture {numero_facture!r} de {fournisseur_id!r} ({montant} avant taxes) est déjà saisie "
        f"({etat['facture_fournisseur_id']}, {_ou_est_rangee(etat)}, le {etat['date_facture']})",
    )


def _identifiant_facture(
    fournisseur_id: str, numero_normalise: str, montant: Decimal, etats: Mapping[str, Any]
) -> str:
    """Identifiant DÉTERMINISTE de (fournisseur, numéro, montant) : le montant s'écrit d'une seule façon (« 12.5 » et
    « 12.50 » sont le même montant), comme la comparaison des doublons. Un identifiant est unique au registre : si
    celui-là existe déjà (la même facture annulée puis ressaisie, ou une facture dont une correction a changé le
    numéro ou le montant), le rang suivant donne le suivant, toujours le même pour le même état du registre."""
    texte = _texte(_au_cent(montant))
    rang = 1
    while True:
        elements = (fournisseur_id, numero_normalise, texte) if rang == 1 else (
            fournisseur_id, numero_normalise, texte, rang)
        identifiant = "apf-" + encodage.empreinte(*elements)[:_LONGUEUR_ID_FACTURE]
        if identifiant not in etats:
            return identifiant
        rang += 1


def _ranger_facture(
    registre_cible: Any, etats: Mapping[str, Any], *, po_id: str | None, categorie_depense: str | None,
    fournisseur_id: str, numero_facture: str, date_facture: str, montant: Decimal, calcul: Mapping[str, Any],
    saisi_par: str, voie: str, avertissements: list[str], horodatage: str,
) -> dict[str, Any]:
    """Écrit la facture au registre (au statut `SAISIE`, le seul de départ) et rend son état courant."""
    identifiant = _identifiant_facture(fournisseur_id, _forme_de_comparaison(numero_facture), montant, etats)
    facture = {
        "type_entree": _TYPE_FACTURE,
        "facture_fournisseur_id": identifiant,
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
    if categorie_depense is not None:
        facture["categorie_depense"] = categorie_depense
    registre_cible.ajouter(facture)
    return _etats_factures(registre_cible.lire())[identifiant]


def _preparer_facture_fournisseur(
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
    obtenir_maillons: Callable[[], Iterable[Mapping[str, Any]]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Prépare une facture sur un unique instantané de maillons, sans écrire.

    Ordre des refus, du plus bête au plus fin : champs texte, humain identifié (`saisi_par`, `voie` : l'identité est
    établie par `outils.py`, jamais lue d'un argument), dates, montants, taux, PO connu, fournisseur du PO, doublon.

    - `montant_avant_taxes` est ce qu'un humain tape ; les TAXES, le total après taxes en sont RECALCULÉS
      (`taxes.calculer_taxes`, taux versionnés). `total_facture`, le total imprimé sur la facture, est un contrôle
      optionnel : fourni, il doit égaler le total recalculé (`REJ-AP-FACTURE-TOTAL-INCOHERENT`), sinon la saisie est
      refusée et le détail donne les deux chiffres.
    - le PO doit avoir été reçu, au moins en partie (`REJ-AP-FACTURE-PO-SANS-RECEPTION`) et appartenir au fournisseur
      dit sur la facture (`REJ-AP-FACTURE-FOURNISSEUR-DIFFERENT-DU-PO`).
    - DOUBLON (`REJ-AP-FACTURE-DOUBLON`) : même fournisseur, même numéro (espaces et casse ignorés), même montant
      avant taxes, quel que soit le PO, parmi les factures VIVANTES à leur valeur COURANTE (`_chercher_doublon`). Même
      fournisseur et même numéro avec un AUTRE montant n'est pas un doublon : la saisie passe avec l'avertissement
      `REJ-AP-FACTURE-NUMERO-REPETE` (refuser bloquerait la bonne facture ; le rapprochement montrera l'écart, et la
      correction ou l'annulation de l'une des deux le lève).
    `obtenir_maillons` est appelé seulement après les contrôles locaux, ce qui conserve l'ordre de lecture historique
    de la saisie. Il reçoit la même séquence que celle utilisée pour vérifier le PO et l'état courant des factures.
    """
    for champ, valeur in (("po_id", po_id), ("fournisseur_id", fournisseur_id), ("numero_facture", numero_facture)):
        if not _texte_non_vide(valeur):
            return None, _verdict("REJ-AP-FACTURE-CHAMP-INVALIDE", f"{champ} requis, non vide")
    po_id, fournisseur_id, numero_facture = po_id.strip(), fournisseur_id.strip(), numero_facture.strip()
    verdict = _numero_valide(numero_facture) or _humain_identifie(
        saisi_par, voie, None, "la facture est saisie", role_exige=False)
    if verdict is not None:
        return None, verdict
    instant_saisie, verdict = _horodatage_valide(horodatage)
    if verdict is not None:
        return None, verdict
    verdict = _date_facture_valide(date_facture, instant_saisie)
    if verdict is not None:
        return None, verdict
    montant, verdict = _montant_saisi(montant_avant_taxes, "montant_avant_taxes", strictement_positif=True)
    if verdict is not None:
        return None, verdict
    calcul, verdict = _controler_total(montant, total_facture, dictionnaire_taux)
    if verdict is not None:
        return None, verdict

    maillons = obtenir_maillons()
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

    etats = _etats_factures(maillons)
    doublon, avertissements = _chercher_doublon(etats, fournisseur_id, numero_facture, montant)
    if doublon is not None:
        return None, _refus_doublon(doublon, fournisseur_id, numero_facture, montant)
    return {
        "po_id": po_id,
        "fournisseur_id": fournisseur_id,
        "numero_facture": numero_facture,
        "date_facture": date_facture,
        "montant_avant_taxes": montant,
        "calcul": calcul,
        "etats": etats,
        "avertissements": avertissements,
    }, None


def verifier_facture_fournisseur(
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
    maillons: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Vérifie et prépare une facture fournisseur en lecture seule.

    Les paramètres de saisie restent identiques, mais `maillons` remplace le registre : l'appelant fournit un
    instantané déjà lu et stable. `(préparation, None)` contient uniquement les champs canoniques de la facture et les
    taxes recalculées ; `(None, verdict)` nomme le premier contrôle refusé. Aucun statut n'est attribué, aucun
    identifiant n'est généré et aucune pièce n'est écrite.
    """
    preparation, verdict = _preparer_facture_fournisseur(
        po_id=po_id,
        fournisseur_id=fournisseur_id,
        numero_facture=numero_facture,
        date_facture=date_facture,
        montant_avant_taxes=montant_avant_taxes,
        total_facture=total_facture,
        saisi_par=saisi_par,
        voie=voie,
        horodatage=horodatage,
        dictionnaire_taux=dictionnaire_taux,
        obtenir_maillons=lambda: tuple(maillons),
    )
    if verdict is not None:
        return None, verdict
    calcul = preparation["calcul"]
    return {
        "po_id": preparation["po_id"],
        "fournisseur_id": preparation["fournisseur_id"],
        "numero_facture": preparation["numero_facture"],
        "date_facture": preparation["date_facture"],
        "montant_avant_taxes": preparation["montant_avant_taxes"],
        "taxes": list(calcul["taxes"]),
        "total_taxes": calcul["total_taxes"],
        "montant_apres_taxes": calcul["montant_apres_taxes"],
        "avertissements": list(preparation["avertissements"]),
    }, None


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
    """`({"facture": état, "avertissements": [codes]}, None)` : range une facture fournisseur SAISIE par un humain ;
    ou `(None, verdict)` sans rien écrire.

    La préparation et ses contrôles canoniques sont partagés avec `verifier_facture_fournisseur`. La saisie lit un seul
    instantané après les contrôles locaux, puis seule `_ranger_facture` écrit la facture.
    """
    preparation, verdict = _preparer_facture_fournisseur(
        po_id=po_id,
        fournisseur_id=fournisseur_id,
        numero_facture=numero_facture,
        date_facture=date_facture,
        montant_avant_taxes=montant_avant_taxes,
        total_facture=total_facture,
        saisi_par=saisi_par,
        voie=voie,
        horodatage=horodatage,
        dictionnaire_taux=dictionnaire_taux,
        obtenir_maillons=registre_cible.lire,
    )
    if verdict is not None:
        return None, verdict
    etat = _ranger_facture(
        registre_cible,
        preparation["etats"],
        po_id=preparation["po_id"],
        categorie_depense=None,
        fournisseur_id=preparation["fournisseur_id"],
        numero_facture=preparation["numero_facture"],
        date_facture=preparation["date_facture"],
        montant=preparation["montant_avant_taxes"],
        calcul=preparation["calcul"],
        saisi_par=saisi_par,
        voie=voie,
        avertissements=preparation["avertissements"],
        horodatage=horodatage,
    )
    return {"facture": etat, "avertissements": etat["avertissements"]}, None


# -------------------------------------------------------------------------- facture SANS PO (T4.15-c)
def lire_categories_depense(brut: Any) -> tuple[tuple[str, ...] | None, dict[str, Any] | None]:
    """La liste FERMÉE des catégories de dépense d'une facture sans PO (`department.yaml`,
    `configuration.categories_depense_sans_po`) : `(catégories, None)` ou `(None, verdict)`.

    Absente ou vide : `REJ-AP-CATEGORIES-A-CONFIGURER` (le propriétaire la décide, GATE NATHAN : aucune catégorie
    n'est supposée à sa place). Illisible (pas une liste, un nom qui n'est ni du texte en minuscules de 2 à
    `_LONGUEUR_CATEGORIE_MAX` caractères sans espace, un doublon) : `REJ-AP-CATEGORIES-INVALIDES`, jamais une liste à
    moitié lue."""
    if brut is None or (isinstance(brut, (list, tuple)) and len(brut) == 0):
        return None, _verdict(
            "REJ-AP-CATEGORIES-A-CONFIGURER",
            "catégories à configurer : déclarer `configuration.categories_depense_sans_po` dans department.yaml, une "
            "liste fermée de catégories de dépense (ex. carburant, outils) : GATE NATHAN, rien n'est supposé",
        )
    if not isinstance(brut, (list, tuple)):
        return None, _verdict("REJ-AP-CATEGORIES-INVALIDES", "categories_depense_sans_po doit être une liste de noms")
    for nom in brut:
        valide = (
            isinstance(nom, str) and 2 <= len(nom) <= _LONGUEUR_CATEGORIE_MAX and nom.isidentifier()
            and nom == nom.lower()
        )
        if not valide:
            return None, _verdict(
                "REJ-AP-CATEGORIES-INVALIDES",
                f"catégorie {nom!r} : du texte en minuscules, sans espace, de 2 à {_LONGUEUR_CATEGORIE_MAX} "
                "caractères (lettres, chiffres et _)",
            )
    if len(set(brut)) != len(brut):
        return None, _verdict("REJ-AP-CATEGORIES-INVALIDES", "categories_depense_sans_po : un nom est répété")
    return tuple(brut), None


def saisir_facture_sans_po(
    *,
    fournisseur_id: Any,
    categorie: Any,
    numero_facture: Any,
    date_facture: Any,
    montant_avant_taxes: Any,
    total_facture: Any,
    saisi_par: Any,
    voie: Any,
    horodatage: Any,
    dictionnaire_taux: Mapping[str, Mapping[str, Any]],
    categories_configurees: Any,
    registre_cible: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`({"facture": état, "avertissements": [codes]}, None)` : range une facture fournisseur SANS PO (carburant,
    outils : une dépense que M6 n'a pas commandée), saisie par un humain ; ou `(None, verdict)` sans rien écrire.

    Mêmes règles que `saisir_facture_fournisseur` (humain identifié, dates, montants tapés en texte, taxes et total
    RECALCULÉS avec les taux versionnés, total imprimé en contrôle, doublon refusé sur (fournisseur, numéro, montant)
    parmi TOUTES les factures vivantes, PO ou non), sauf :
    - aucun PO, donc aucune réception ni aucun rapprochement : la facture est une DETTE dès qu'elle est saisie (elle
      entre en entier dans les comptes à payer et dans le cash libre) ;
    - `categorie` est de la liste fermée `categories_configurees` (lue de la configuration par `outils.py`) ; absente
      ou vide, la saisie est refusée (`REJ-AP-CATEGORIES-A-CONFIGURER`), une catégorie hors liste aussi
      (`REJ-AP-CATEGORIE-INCONNUE`, qui donne la liste) ;
    - `fournisseur_id` est un nom tapé par l'humain (M6 n'a pas de fiche pour un fournisseur d'essence) : texte
      imprimable de `_LONGUEUR_FOURNISSEUR_MAX` caractères au plus ; deux écritures qui ne diffèrent que par la casse
      ou les espaces sont le même fournisseur pour le doublon."""
    for champ, valeur in (
        ("fournisseur_id", fournisseur_id), ("categorie", categorie), ("numero_facture", numero_facture),
    ):
        if not _texte_non_vide(valeur):
            return None, _verdict("REJ-AP-FACTURE-CHAMP-INVALIDE", f"{champ} requis, non vide")
    fournisseur_id, categorie, numero_facture = fournisseur_id.strip(), categorie.strip(), numero_facture.strip()
    if len(fournisseur_id) > _LONGUEUR_FOURNISSEUR_MAX or not fournisseur_id.isprintable():
        return None, _verdict(
            "REJ-AP-FACTURE-CHAMP-INVALIDE",
            f"fournisseur_id : {_LONGUEUR_FOURNISSEUR_MAX} caractères imprimables au plus, tel qu'imprimé sur la "
            "facture",
        )
    verdict = _numero_valide(numero_facture) or _humain_identifie(
        saisi_par, voie, None, "la facture sans PO est saisie", role_exige=False)
    if verdict is not None:
        return None, verdict
    categories, verdict = lire_categories_depense(categories_configurees)
    if verdict is not None:
        return None, verdict
    if categorie not in categories:
        return None, _verdict(
            "REJ-AP-CATEGORIE-INCONNUE",
            f"catégorie {categorie!r} hors de la liste configurée : {', '.join(categories)}",
        )
    instant_saisie, verdict = _horodatage_valide(horodatage)
    if verdict is not None:
        return None, verdict
    verdict = _date_facture_valide(date_facture, instant_saisie)
    if verdict is not None:
        return None, verdict
    montant, verdict = _montant_saisi(montant_avant_taxes, "montant_avant_taxes", strictement_positif=True)
    if verdict is not None:
        return None, verdict
    calcul, verdict = _controler_total(montant, total_facture, dictionnaire_taux)
    if verdict is not None:
        return None, verdict

    etats = _etats_factures(registre_cible.lire())
    doublon, avertissements = _chercher_doublon(etats, fournisseur_id, numero_facture, montant)
    if doublon is not None:
        return None, _refus_doublon(doublon, fournisseur_id, numero_facture, montant)
    etat = _ranger_facture(
        registre_cible, etats, po_id=None, categorie_depense=categorie, fournisseur_id=fournisseur_id,
        numero_facture=numero_facture, date_facture=date_facture, montant=montant, calcul=calcul,
        saisi_par=saisi_par, voie=voie, avertissements=avertissements, horodatage=horodatage,
    )
    return {"facture": etat, "avertissements": etat["avertissements"]}, None


# ------------------------------------------------------------- correction et annulation (T4.15-c)
def _instantane(etat: Mapping[str, Any]) -> dict[str, Any]:
    """Ce qu'une pièce de correction ou d'annulation garde de la facture AVANT elle : de quoi lire, sans recalcul, ce
    qui a changé."""
    return {
        "numero_facture": etat["numero_facture"], "date_facture": etat["date_facture"],
        "montant_avant_taxes": etat["montant_avant_taxes"], "total_taxes": etat["total_taxes"],
        "montant_apres_taxes": etat["montant_apres_taxes"],
    }


def _facture_a_modifier(
    etats: Mapping[str, Mapping[str, Any]], identifiant: str
) -> tuple[Mapping[str, Any] | None, dict[str, Any] | None]:
    etat = etats.get(identifiant)
    if etat is None:
        return None, _verdict(
            "REJ-AP-FACTURE-INCONNUE",
            f"aucune facture fournisseur {identifiant!r} au registre : lire l'identifiant dans les comptes à payer",
        )
    return etat, None


def _identifiant_a_modifier(identifiant: Any) -> tuple[str | None, dict[str, Any] | None]:
    if not _texte_non_vide(identifiant):
        return None, _verdict("REJ-AP-FACTURE-CHAMP-INVALIDE", "facture_fournisseur_id requis, non vide")
    return identifiant.strip(), None


def corriger_facture_fournisseur(
    *,
    facture_fournisseur_id: Any,
    motif: Any,
    numero_facture: Any,
    date_facture: Any,
    montant_avant_taxes: Any,
    total_facture: Any,
    corrige_par: Any,
    role: Any,
    voie: Any,
    horodatage: Any,
    dictionnaire_taux: Mapping[str, Mapping[str, Any]],
    registre_cible: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`({"facture": état, "avertissements": [codes]}, None)` : corrige une facture fournisseur SAISIE en AJOUTANT une
    pièce de correction chaînée au registre ; ou `(None, verdict)` sans rien écrire. La facture d'origine n'est jamais
    modifiée : son état courant est celui que sa dernière pièce dit.

    Ce qui se corrige : le numéro, la date et le montant avant taxes (`None` : inchangé ; au moins un des trois est
    fourni). Les taxes et le total après taxes sont RECALCULÉS (taux versionnés), `total_facture` sert de contrôle
    comme à la saisie. Le PO, le fournisseur et la catégorie ne se corrigent pas : annuler puis ressaisir sous le bon.

    Refus, sans rien écrire : motif absent (`REJ-AP-MOTIF-REQUIS`), pas d'humain identifié (`REJ-AP-HUMAIN-REQUIS`),
    facture inconnue ou annulée (`REJ-AP-FACTURE-INCONNUE`, `REJ-AP-FACTURE-ANNULEE`), rien ne change
    (`REJ-AP-CORRECTION-SANS-CHANGEMENT` : un REJEU d'une correction déjà appliquée tombe ici, sans aucun effet), un
    doublon avec une autre facture vivante (`REJ-AP-FACTURE-DOUBLON`), et les refus de format de la saisie. La pièce
    porte le motif, la personne, son rôle, la voie, l'avant et l'après."""
    identifiant, verdict = _identifiant_a_modifier(facture_fournisseur_id)
    if verdict is not None:
        return None, verdict
    motif, verdict = _motif_valide(motif)
    if verdict is not None:
        return None, verdict
    verdict = _humain_identifie(corrige_par, voie, role, "la correction est faite", role_exige=True)
    if verdict is not None:
        return None, verdict
    instant, verdict = _horodatage_valide(horodatage)
    if verdict is not None:
        return None, verdict

    if numero_facture is not None:
        if not _texte_non_vide(numero_facture):
            return None, _verdict("REJ-AP-FACTURE-CHAMP-INVALIDE", "numero_facture : non vide, ou nul pour l'ignorer")
        numero_facture = numero_facture.strip()
        verdict = _numero_valide(numero_facture)
        if verdict is not None:
            return None, verdict
    if date_facture is not None:
        verdict = _date_facture_valide(date_facture, instant)
        if verdict is not None:
            return None, verdict
    montant = None
    if montant_avant_taxes is not None:
        montant, verdict = _montant_saisi(montant_avant_taxes, "montant_avant_taxes", strictement_positif=True)
        if verdict is not None:
            return None, verdict
    if numero_facture is None and date_facture is None and montant is None:
        return None, _verdict(
            "REJ-AP-CORRECTION-SANS-CHANGEMENT",
            "rien à corriger : fournir au moins un de numero_facture, date_facture, montant_avant_taxes",
        )

    maillons = registre_cible.lire()
    etats = _etats_factures(maillons)
    etat, verdict = _facture_a_modifier(etats, identifiant)
    if verdict is not None:
        return None, verdict
    if etat["statut"] == _STATUT_ANNULEE:
        return None, _verdict(
            "REJ-AP-FACTURE-ANNULEE",
            f"la facture {identifiant} est annulée : ressaisir la bonne facture (une annulée ne se corrige plus)",
        )
    apres_numero = etat["numero_facture"] if numero_facture is None else numero_facture
    apres_date = etat["date_facture"] if date_facture is None else date_facture
    apres_montant = etat["montant_avant_taxes"] if montant is None else montant
    if (apres_numero, apres_date, apres_montant) == (
        etat["numero_facture"], etat["date_facture"], etat["montant_avant_taxes"]
    ):
        return None, _verdict(
            "REJ-AP-CORRECTION-SANS-CHANGEMENT",
            f"la facture {identifiant} a déjà ce numéro, cette date et ce montant : rien n'est écrit",
        )
    calcul, verdict = _controler_total(apres_montant, total_facture, dictionnaire_taux)
    if verdict is not None:
        return None, verdict
    doublon, _avertissements = _chercher_doublon(
        etats, etat["fournisseur_id"], apres_numero, apres_montant, sauf_id=identifiant)
    if doublon is not None:
        return None, _refus_doublon(doublon, etat["fournisseur_id"], apres_numero, apres_montant)

    registre_cible.ajouter({
        "type_entree": _TYPE_CORRECTION,
        "modification_id": _identifiant_modification(identifiant, etat),
        "facture_fournisseur_id": identifiant,
        "motif": motif,
        "corrige_par": corrige_par,
        "role": role,
        "voie": voie,
        "avant": _instantane(etat),
        "apres": {
            "numero_facture": apres_numero, "date_facture": apres_date, "montant_avant_taxes": apres_montant,
            "taxes": list(calcul["taxes"]), "total_taxes": calcul["total_taxes"],
            "montant_apres_taxes": calcul["montant_apres_taxes"],
        },
        "horodatage": horodatage,
    })
    corrigee = _etats_factures(registre_cible.lire())[identifiant]
    return {"facture": corrigee, "avertissements": corrigee["avertissements"]}, None


def annuler_facture_fournisseur(
    *,
    facture_fournisseur_id: Any,
    motif: Any,
    annule_par: Any,
    role: Any,
    voie: Any,
    horodatage: Any,
    registre_cible: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`({"facture": état, "avertissements": [codes]}, None)` : annule une facture fournisseur saisie en AJOUTANT une
    pièce d'annulation chaînée au registre ; ou `(None, verdict)` sans rien écrire. La facture d'origine n'est jamais
    modifiée ni effacée : elle reste au registre avec le statut `ANNULEE`, et n'entre plus dans le facturé, l'« à
    payer », le rapprochement, le doublon ni les crédits de taxes du cash libre.

    Annuler ne paie rien et ne supprime pas la dette envers le fournisseur : un PO reçu et non facturé redevient un
    « à payer attendu ». Refus : motif absent (`REJ-AP-MOTIF-REQUIS`), pas d'humain identifié
    (`REJ-AP-HUMAIN-REQUIS`), facture inconnue (`REJ-AP-FACTURE-INCONNUE`), déjà annulée
    (`REJ-AP-FACTURE-DEJA-ANNULEE` : un REJEU de l'annulation tombe ici, sans aucun effet). La pièce porte le motif, la
    personne, son rôle, la voie et l'état annulé."""
    identifiant, verdict = _identifiant_a_modifier(facture_fournisseur_id)
    if verdict is not None:
        return None, verdict
    motif, verdict = _motif_valide(motif)
    if verdict is not None:
        return None, verdict
    verdict = _humain_identifie(annule_par, voie, role, "l'annulation est faite", role_exige=True)
    if verdict is not None:
        return None, verdict
    _instant_valide, verdict = _horodatage_valide(horodatage)
    if verdict is not None:
        return None, verdict

    etat, verdict = _facture_a_modifier(_etats_factures(registre_cible.lire()), identifiant)
    if verdict is not None:
        return None, verdict
    if etat["statut"] == _STATUT_ANNULEE:
        return None, _verdict(
            "REJ-AP-FACTURE-DEJA-ANNULEE", f"la facture {identifiant} est déjà annulée : rien n'est écrit"
        )
    registre_cible.ajouter({
        "type_entree": _TYPE_ANNULATION,
        "modification_id": _identifiant_modification(identifiant, etat),
        "facture_fournisseur_id": identifiant,
        "motif": motif,
        "annule_par": annule_par,
        "role": role,
        "voie": voie,
        "avant": _instantane(etat),
        "horodatage": horodatage,
    })
    annulee = _etats_factures(registre_cible.lire())[identifiant]
    return {"facture": annulee, "avertissements": annulee["avertissements"]}, None


# ------------------------------------------------------------- l'état courant d'une facture (T4.15-c)
def _identifiant_modification(identifiant: str, etat: Mapping[str, Any]) -> str:
    """Identifiant DÉTERMINISTE de la pièce suivante d'une facture : (facture, rang de la pièce)."""
    return "apm-" + encodage.empreinte(identifiant, len(etat["modifications"]) + 1)[:_LONGUEUR_ID_FACTURE]


def _resume_modification(piece: Mapping[str, Any]) -> dict[str, Any]:
    """Une pièce de correction ou d'annulation, en une ligne : ce qu'une lecture de la facture en dit."""
    correction = piece["type_entree"] == _TYPE_CORRECTION
    return {
        "modification_id": piece["modification_id"],
        "type": "CORRECTION" if correction else "ANNULATION",
        "par": piece["corrige_par"] if correction else piece["annule_par"],
        "role": piece["role"],
        "voie": piece["voie"],
        "motif": piece["motif"],
        "horodatage": piece["horodatage"],
    }


def _etats_factures(maillons: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """L'ÉTAT COURANT de chaque facture fournisseur du registre, dans l'ordre de saisie : la facture d'origine, puis
    ce que ses pièces de correction et d'annulation y changent, dans l'ordre du registre. C'est LE seul endroit où une
    facture se lit : le rapprochement, les totaux, le doublon et les crédits de taxes du cash libre partent tous de
    cet état, jamais de la facture d'origine.

    Chaque état porte les champs de la facture d'origine (à leur valeur courante), `statut` (`SAISIE`, `CORRIGEE` ou
    `ANNULEE`), `corrections` (leur nombre), `modifications` (une ligne par pièce, l'ordre du registre) et
    `avertissements` (RECALCULÉS sur l'ensemble vivant : le même fournisseur et le même numéro sur deux factures
    vivantes, qui diffèrent forcément de montant, se signalent l'une l'autre ; annuler ou corriger l'une lève
    l'avertissement de l'autre).

    Un registre où une pièce vise une facture absente ou déjà annulée LÈVE (`RuntimeError`) : l'écriture le refuse en
    amont, donc c'est une corruption, et la lire à demi donnerait un chiffre faux sur de l'argent."""
    etats: dict[str, dict[str, Any]] = {}
    for maillon in maillons:
        type_entree = maillon.get("type_entree")
        if type_entree == _TYPE_FACTURE:
            identifiant = maillon["facture_fournisseur_id"]
            if identifiant in etats:
                raise RuntimeError(f"registre des comptes à payer incohérent : facture {identifiant} écrite deux fois")
            etats[identifiant] = {**maillon, "corrections": 0, "modifications": []}
        elif type_entree in (_TYPE_CORRECTION, _TYPE_ANNULATION):
            etat = etats.get(maillon["facture_fournisseur_id"])
            if etat is None or etat["statut"] == _STATUT_ANNULEE:
                raise RuntimeError(
                    "registre des comptes à payer incohérent : la pièce "
                    f"{maillon['modification_id']} vise la facture {maillon['facture_fournisseur_id']}, absente ou "
                    "déjà annulée"
                )
            if type_entree == _TYPE_CORRECTION:
                etat.update(maillon["apres"])
                etat["statut"] = _STATUT_CORRIGEE
                etat["corrections"] += 1
            else:
                etat["statut"] = _STATUT_ANNULEE
            etat["modifications"].append(_resume_modification(maillon))
    vivantes: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for etat in etats.values():
        etat["avertissements"] = []
        if etat["statut"] != _STATUT_ANNULEE:
            cle = (_forme_de_comparaison(etat["fournisseur_id"]), _forme_de_comparaison(etat["numero_facture"]))
            vivantes.setdefault(cle, []).append(etat)
    for groupe in vivantes.values():
        if len(groupe) > 1:
            for etat in groupe:
                etat["avertissements"] = [CODE_NUMERO_REPETE]
    return etats


def vue_facture(etat: Mapping[str, Any]) -> dict[str, Any]:
    """Ce qu'une réponse dit d'une facture fournisseur : son état courant, sans les empreintes du registre. Les montants
    restent des `Decimal` (l'enveloppe des outils les rend en texte). `categorie_depense` (facture sans PO),
    `corrections` et `derniere_modification` n'y sont que s'il y a lieu : une facture saisie et jamais touchée garde la
    forme d'avant."""
    vue = {
        cle: etat[cle]
        for cle in (
            "facture_fournisseur_id", "po_id", "fournisseur_id", "numero_facture", "date_facture",
            "montant_avant_taxes", "taxes", "total_taxes", "montant_apres_taxes", "statut", "saisi_par", "voie",
            "avertissements", "horodatage",
        )
    }
    if etat.get("categorie_depense") is not None:
        vue["categorie_depense"] = etat["categorie_depense"]
    if etat["modifications"]:
        vue["corrections"] = etat["corrections"]
        vue["derniere_modification"] = dict(etat["modifications"][-1])
    return vue


# ------------------------------------------------------------------ état par PO et rapprochement
def _pos(
    maillons: Iterable[Mapping[str, Any]], etats: Mapping[str, Mapping[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """Les PO connus, chacun avec ses réceptions et ses factures, dans l'ordre du registre.

    Les factures d'un PO sont leur ÉTAT COURANT (`_etats_factures`, calculé ici si l'appelant ne le donne pas) : les
    VIVANTES (`SAISIE`, `CORRIGEE`) sous `factures`, celles que le facturé, l'« à payer » et le rapprochement
    comptent ; les ANNULÉES sous `factures_annulees`, que rien ne compte. Une facture sans PO n'est d'aucun PO."""
    maillons = list(maillons)
    etats = _etats_factures(maillons) if etats is None else etats
    par_po: dict[str, dict[str, Any]] = {}
    for maillon in maillons:
        if maillon.get("type_entree") == _TYPE_RECEPTION:
            po = par_po.setdefault(maillon["po_id"], {
                "po_id": maillon["po_id"], "fournisseur_id": maillon["fournisseur_id"],
                "chantier_id": maillon["chantier_id"], "receptions": [], "factures": [], "factures_annulees": []})
            po["receptions"].append(maillon)
            po["statut_po"] = maillon["statut_po"]
    for etat in etats.values():
        if etat["po_id"] in par_po:
            cle = "factures_annulees" if etat["statut"] == _STATUT_ANNULEE else "factures"
            par_po[etat["po_id"]][cle].append(etat)
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
        reserves.append(CODE_NUMERO_REPETE)
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
        "factures_annulees": po["factures_annulees"],
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


def _vue_facture_liste(etat: Mapping[str, Any]) -> dict[str, Any]:
    """Une facture en une ligne, à son ÉTAT COURANT. `statut`, `corrections` et `derniere_modification` (qui, pourquoi,
    quand) disent ce qui a changé depuis la saisie ; `fournisseur_id` et `categorie_depense` n'y sont que pour une
    facture sans PO (celle d'un PO a le fournisseur de son PO)."""
    vue = {
        "facture_fournisseur_id": etat["facture_fournisseur_id"],
        "numero_facture": etat["numero_facture"],
        "date_facture": etat["date_facture"],
        "avant_taxes": _texte(etat["montant_avant_taxes"]),
        "taxes": _texte(etat["total_taxes"]),
        "apres_taxes": _texte(etat["montant_apres_taxes"]),
        "statut": etat["statut"],
        "saisi_par": etat["saisi_par"],
        "avertissements": list(etat["avertissements"]),
    }
    if etat["po_id"] is None:
        vue["fournisseur_id"] = etat["fournisseur_id"]
        vue["categorie_depense"] = etat["categorie_depense"]
    if etat["modifications"]:
        vue["corrections"] = etat["corrections"]
        vue["derniere_modification"] = dict(etat["modifications"][-1])
    return vue


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
    if synthese["factures_annulees"]:
        vue["factures_annulees"] = len(synthese["factures_annulees"])
    if detail:
        vue["premiere_reception"] = synthese["premiere_reception"]
        vue["commande_avant_taxes"] = _texte(synthese["commande_avant_taxes"])
        vue["attendu_non_facture_apres_taxes"] = _texte(a_payer["attendu_non_facture_apres_taxes"])
        vue["quantites"] = [
            {"materiau_id": q["materiau_id"], "commandee": _texte(q["commandee"]), "recue": _texte(q["recue"]),
             "ecart": _texte(q["ecart"])}
            for q in synthese["quantites"]
        ]
        vue["factures_saisies"] = [
            _vue_facture_liste(f) for f in (*synthese["factures"], *synthese["factures_annulees"])
        ]
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


# ------------------------------------------------------------------- ce que le cash libre en retient
def factures_saisies(registre_cible: Any) -> list[dict[str, Any]]:
    """Les factures fournisseur VIVANTES du registre (avec ou sans PO), à leur ÉTAT COURANT et dans l'ordre de saisie
    (lecture pure) : une corrigée vaut sa dernière correction, une annulée n'y est plus. Le cash libre (T4.16) en tire
    les crédits de taxes sur intrants : ce qui a été saisi par un humain et n'a pas été annulé, jamais ce qui est
    seulement attendu."""
    return [etat for etat in _etats_factures(registre_cible.lire()).values() if etat["statut"] != _STATUT_ANNULEE]


def dettes_datables(
    registre_cible: Any, dictionnaire_taux: Mapping[str, Mapping[str, Any]]
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Ce que l'entreprise doit aux fournisseurs, UNE DETTE À LA FOIS, pour que la prévision de trésorerie (PLAN
    T4.16-d, `prevision.py`) date chacune : `(dettes, None)` ou `(None, verdict)`.

    Ce sont les dettes de `resume_a_payer`, séparées (une seule règle : leur somme est son « à payer », plancher
    compris) :
    - `FACTURE` : chaque facture fournisseur VIVANTE (avec ou sans PO), à son état courant (une corrigée vaut sa
      correction, une annulée n'y est pas) ; `date_base` est la date imprimée sur la facture ;
    - `ATTENDU` : pour chaque PO reçu, ce qui est reçu et pas encore facturé (taxes recalculées sur ce reste) ;
      `date_base` est la PREMIÈRE réception du PO (la plus ancienne, donc la date de paiement la plus prudente), `id`
      est le `po_id`. Un attendu que rien ne permet de chiffrer (prix du PO absent, devise autre que CAD) a `montant`
      `None` et ses codes dans `manque`, jamais zéro ; il porte la réserve de l'unité des prix.

    Chaque dette : `type`, `id`, `po_id` (`None` sans PO), `fournisseur_id`, `numero_facture` (`None` pour un
    attendu), `date_base` (texte), `montant` (`Decimal` après taxes, ou `None`), `manque` (codes), `reserves` (codes).
    Ordre stable : les PO par première réception puis `po_id` (leurs factures dans l'ordre de saisie, puis l'attendu),
    ensuite les factures sans PO dans l'ordre de saisie. Aucun délai de paiement n'existe ici : la facture n'en porte
    pas, la date d'échéance est l'affaire de `prevision.py` et des règles que le propriétaire déclare. `(None,
    verdict)` seulement si un taux fiscal manque : rien n'est alors chiffré à demi."""
    maillons = registre_cible.lire()
    etats = _etats_factures(maillons)
    dettes: list[dict[str, Any]] = []
    ordonnes = sorted(
        _pos(maillons, etats).values(),
        key=lambda p: (_instant(p["receptions"][0]["horodatage_reception"]), p["po_id"]),
    )
    for po in ordonnes:
        synthese, verdict = synthese_du_po(po, dictionnaire_taux)
        if verdict is not None:
            return None, verdict
        for facture in synthese["factures"]:
            dettes.append(_dette_facture(facture))
        attendu = synthese["a_payer"]["attendu_non_facture_apres_taxes"]
        if attendu is None or attendu > _ZERO:
            dettes.append({
                "type": "ATTENDU", "id": synthese["po_id"], "po_id": synthese["po_id"],
                "fournisseur_id": synthese["fournisseur_id"], "numero_facture": None,
                "date_base": synthese["premiere_reception"], "montant": attendu,
                "manque": list(synthese["attendu"]["manque"]), "reserves": [CODE_UNITE_PRIX],
            })
    for etat in etats.values():
        if etat["po_id"] is None and etat["statut"] != _STATUT_ANNULEE:
            dettes.append(_dette_facture(etat))
    return dettes, None


def _dette_facture(etat: Mapping[str, Any]) -> dict[str, Any]:
    """Une facture fournisseur vivante, en dette : son montant après taxes à son état courant."""
    return {
        "type": "FACTURE", "id": etat["facture_fournisseur_id"], "po_id": etat["po_id"],
        "fournisseur_id": etat["fournisseur_id"], "numero_facture": etat["numero_facture"],
        "date_base": etat["date_facture"], "montant": etat["montant_apres_taxes"], "manque": [], "reserves": [],
    }


def _resume_sans_po(etats: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Ce que valent les factures SANS PO vivantes, en `Decimal` : leur nombre, le total avant taxes, taxes et après
    taxes, et le détail par catégorie de dépense (ordre alphabétique). Une facture sans PO est une dette ferme : elle
    compte en entier dans l'« à payer » dès qu'elle est saisie. Sans facture : des zéros LUS, pas supposés."""
    vivantes = [e for e in etats.values() if e["po_id"] is None and e["statut"] != _STATUT_ANNULEE]
    par_categorie: dict[str, list[Mapping[str, Any]]] = {}
    for etat in vivantes:
        par_categorie.setdefault(etat["categorie_depense"], []).append(etat)
    return {
        "nombre": len(vivantes),
        "avant_taxes": _somme(e["montant_avant_taxes"] for e in vivantes),
        "taxes": _somme(e["total_taxes"] for e in vivantes),
        "apres_taxes": _somme(e["montant_apres_taxes"] for e in vivantes),
        "par_categorie": {
            categorie: {
                "nombre": len(factures), "apres_taxes": _somme(e["montant_apres_taxes"] for e in factures),
            }
            for categorie, factures in sorted(par_categorie.items())
        },
    }


def _vue_sans_po(resume: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "nombre": resume["nombre"],
        "avant_taxes": _texte(resume["avant_taxes"]),
        "taxes": _texte(resume["taxes"]),
        "apres_taxes": _texte(resume["apres_taxes"]),
        "par_categorie": {
            categorie: {"nombre": ligne["nombre"], "apres_taxes": _texte(ligne["apres_taxes"])}
            for categorie, ligne in resume["par_categorie"].items()
        },
    }


def totaux_sans_po(registre_cible: Any) -> dict[str, Any]:
    """Ce que les factures SANS PO vivantes valent en tout, en texte (`_vue_sans_po`) : ce que la réponse d'une écriture
    sur une facture sans PO ajoute à la facture elle-même. Lecture pure."""
    return _vue_sans_po(_resume_sans_po(_etats_factures(registre_cible.lire())))


def resume_a_payer(
    registre_cible: Any, dictionnaire_taux: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Ce que les comptes à payer disent au total, pour le cash libre (T4.16) : `(résumé, None)` ou `(None, verdict)`.

    Le total porte sur TOUS les PO et sur toutes les factures SANS PO vivantes (comme `totaux` de `lister`, dont il
    reprend le calcul : une seule règle) : `a_payer_apres_taxes` est `None` dès qu'un PO n'est pas calculable (jamais
    zéro à sa place) et `a_payer_connu_apres_taxes` n'est alors qu'un plancher (les factures déjà saisies, dettes
    fermes, sans PO comprises). `sans_po` dit ce que les factures sans PO y mettent (`_resume_sans_po`). `reserves`
    porte l'hypothèse de l'unité des prix dès qu'un PO existe. `pieces`, `derniere_piece` et `tete` disent d'où vient
    le chiffre (le nombre de maillons du registre, l'horodatage du plus récent, la tête de la chaîne). `(None,
    verdict)` seulement si un taux fiscal manque : rien n'est alors chiffré à demi."""
    maillons = registre_cible.lire()
    etats = _etats_factures(maillons)
    syntheses = []
    ordonnes = sorted(
        _pos(maillons, etats).values(),
        key=lambda p: (_instant(p["receptions"][0]["horodatage_reception"]), p["po_id"]),
    )
    for po in ordonnes:
        synthese, verdict = synthese_du_po(po, dictionnaire_taux)
        if verdict is not None:
            return None, verdict
        syntheses.append(synthese)
    sans_po = _resume_sans_po(etats)
    totaux = _totaux(syntheses, sans_po)
    calculables = totaux["complet"]
    return {
        "nombre_po": totaux["nombre_po"],
        "complet": calculables,
        "a_payer_apres_taxes": Decimal(totaux["a_payer_apres_taxes"]) if calculables else None,
        "a_payer_connu_apres_taxes": Decimal(totaux["a_payer_connu_apres_taxes"]),
        "non_calculables_po": totaux["non_calculables_po"],
        "non_calculables": totaux["non_calculables"],
        "sans_po": sans_po,
        "reserves": [CODE_UNITE_PRIX] if syntheses else [],
        "pieces": len(maillons),
        "derniere_piece": max((m["horodatage"] for m in maillons), key=_instant, default=None),
        "tete": maillons[-1]["ligne_id"] if maillons else None,
    }, None


# ------------------------------------------------------------------------------------- la liste
def _taille(objet: Any) -> int:
    """Taille sérialisée EXACTE telle que `Capacites._tronquer` la mesure (`json.dumps`, sans échappement ASCII) : la
    borne se calcule sur ce que le modèle recevrait, jamais sur une estimation."""
    return len(json.dumps(objet, ensure_ascii=False))


def _totaux(syntheses: list[Mapping[str, Any]], sans_po: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Les totaux des PO donnés et, si `sans_po` est donné (`_resume_sans_po`), des factures sans PO vivantes : une
    facture sans PO est une dette ferme, comptée en entier dans l'« à payer » et dans son plancher, et n'ôte rien à
    `complet` (qui ne parle que des PO dont l'attendu peut manquer). Sans `sans_po` (le détail d'un seul PO) : aucune
    facture sans PO n'entre dans les totaux."""
    calculables = [s for s in syntheses if s["a_payer"]["apres_taxes"] is not None]
    non_calculables = [s for s in syntheses if s["a_payer"]["apres_taxes"] is None]
    # Le plancher : ce qui est CERTAIN. Un PO calculable compte pour son « à payer » ; un PO non calculable compte au
    # moins pour ce qui est déjà FACTURÉ (une dette ferme, quoi qu'il manque au reste), jamais pour zéro. Les factures
    # sans PO sont des dettes fermes : elles y sont toutes.
    a_payer_connu = _somme([
        *(
            s["a_payer"]["apres_taxes"] if s["a_payer"]["apres_taxes"] is not None else s["facture"]["apres_taxes"]
            for s in syntheses
        ),
        *([sans_po["apres_taxes"]] if sans_po is not None else []),
    ])
    complet = not non_calculables
    totaux = {
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
    if sans_po is not None and sans_po["nombre"]:
        totaux["sans_po"] = _vue_sans_po(sans_po)
    return totaux


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

    `totaux` porte sur TOUS les PO, pas seulement sur la page, et, hors du détail d'un PO, sur les factures SANS PO
    vivantes (bloc `sans_po`, présent s'il y en a : elles se lisent avec `lister_sans_po`). Un PO dont l'attendu n'est
    pas calculable ne compte jamais pour zéro : `a_payer_apres_taxes` est alors `None` et
    `a_payer_connu_apres_taxes` n'est qu'un plancher. Les factures ANNULÉES ne comptent nulle part : ni facturé, ni
    « à payer », ni rapprochement. Refus nommés, sans rien rendre : `depart` invalide ou au-delà de la fin, taux fiscal
    manquant, un seul PO plus gros à lui seul que la borne."""
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        return None, _verdict(
            "REJ-AP-LISTE-DEPART-INVALIDE", f"depart : entier supérieur ou égal à 0 attendu, reçu {depart!r}"
        )
    maillons = registre_cible.lire()
    etats = _etats_factures(maillons)
    pos = _pos(maillons, etats)
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
    totaux = _totaux(syntheses, _resume_sans_po(etats) if po_id is None else None)
    hypotheses = [HYPOTHESE_UNITE_PRIX, _HYPOTHESE_TAXES]
    if "sans_po" in totaux:
        hypotheses.append(_HYPOTHESE_SANS_PO)

    def page(nombre: int) -> dict[str, Any]:
        fin = depart + nombre
        reste = total - fin
        return {
            "type": "COMPTES_A_PAYER",
            "mention": analyse.MENTION_ANALYSE_PREPARATOIRE,
            "ordre": _ORDRE,
            "hypotheses": hypotheses,
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


def lister_sans_po(
    registre_cible: Any, *, depart: Any = 0, budget_caracteres: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Une page des factures fournisseur SANS PO (carburant, outils), à leur ÉTAT COURANT, avec leur identifiant (celui
    que la correction et l'annulation demandent), leur catégorie, leur statut et ce qui a changé depuis la saisie.

    Lecture pure : n'écrit rien. Toutes les factures sans PO y sont, les ANNULÉES comprises (statut `ANNULEE`, pour
    retrouver un identifiant et lire le motif) ; `totaux` ne compte que les vivantes (`_resume_sans_po`), en entier :
    c'est une dette ferme. Ordre de saisie. Même page par rang que `lister` : `depart`, `prochain_depart`, `reste`,
    la taille sérialisée MESURÉE sous `budget_caracteres` (au moins une facture), refus nommés sans rien rendre
    (`depart` invalide ou au-delà de la fin, une seule facture plus grosse à elle seule que la borne)."""
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        return None, _verdict(
            "REJ-AP-LISTE-DEPART-INVALIDE", f"depart : entier supérieur ou égal à 0 attendu, reçu {depart!r}"
        )
    etats = _etats_factures(registre_cible.lire())
    sans_po = [etat for etat in etats.values() if etat["po_id"] is None]
    total = len(sans_po)
    if depart > total:
        return None, _verdict(
            "REJ-AP-LISTE-DEPART-INVALIDE",
            f"depart {depart} au-delà de la fin ({total} facture(s) sans PO) : reprendre à depart=0 (le total a pu "
            "changer)",
        )
    lignes = [_vue_facture_liste(etat) for etat in sans_po]
    totaux = _vue_sans_po(_resume_sans_po(etats))

    def page(nombre: int) -> dict[str, Any]:
        fin = depart + nombre
        reste = total - fin
        return {
            "type": "COMPTES_A_PAYER_SANS_PO",
            "mention": analyse.MENTION_ANALYSE_PREPARATOIRE,
            "ordre": _ORDRE_SANS_PO,
            "hypotheses": [_HYPOTHESE_SANS_PO, _HYPOTHESE_TAXES],
            "totaux": totaux,
            "total": total,
            "depart": depart,
            "affichees": nombre,
            "reste": reste,
            "prochain_depart": fin if reste else None,
            "message": None if not reste else f"{reste} facture(s) non affichée(s) : poursuivre avec depart={fin}.",
            "factures": lignes[depart:fin],
        }

    nombre = 0
    while depart + nombre < total and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if depart < total and nombre == 0:
        return None, _verdict(
            "REJ-AP-LISTE-LIGNE-TROP-GROSSE",
            f"la facture {sans_po[depart]['facture_fournisseur_id']!r} dépasse à elle seule la borne de "
            f"{budget_caracteres} caractères",
        )
    return page(nombre), None
