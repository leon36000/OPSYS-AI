"""Opérations comptables de M5, jusqu'aux BROUILLONS : relances de comptes clients, notes de crédit (clients et
fournisseurs), dépenses d'employés, pièces justificatives, paiements fournisseurs PRÉPARÉS, jugements et estimations.

Module pur (même règle que `grand_livre.py`) : aucun import d'`opsys`, aucune horloge, aucun réseau. Il reçoit des
registres déjà construits (`registre_ops` : le registre DÉDIÉ `operations_comptables`, `registre_gl` : le grand
livre) et des faits lus (factures, plan, taux) ; il ne nomme jamais le registre des mouvements (garde
anti-décaissement, strict).

Ce que ce module ne fait JAMAIS :
- envoyer une relance (elle est un texte en brouillon ; l'envoi appartient à M1 et à la politique d'approbation) ;
- rendre une écriture définitive (un brouillon d'écriture attend `m5_valider_ecriture_comptable`, N4) ;
- payer quoi que ce soit : un « paiement préparé » est une fiche (fournisseur, montant, date voulue, rapprochement)
qu'une
  personne exécute HORS d'OPSYS ; payer un fournisseur est N5 et n'existe pas ici ;
- deviner un délai, un compte ou un taux : tout ce que le propriétaire décide (politique de relance, compte de
  remboursement des employés) se déclare, et l'absence est un refus qui dit quoi déclarer.

Les montants viennent du code (taxes recalculées avec les taux versionnés, arrondi ROUND_HALF_UP) ou sont RELUS des
pièces
de M5 ; ils sont des textes décimaux au cent. Toute opération est idempotente par clé (`operations_registre.py`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import grand_livre, operations_registre, plan_comptable, taxes, verdicts_operations

__all__ = [
    "lire_politique_relances",
    "preparer_relances",
    "proposer_note_credit",
    "proposer_depense_employe",
    "lier_piece",
    "preparer_paiement",
    "enregistrer_jugement",
    "montant_texte",
    "credits_par_facture",
    "texte_relance",
    "formater_cad",
    "cibles_piece",
]

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_MONTANT_MAX = Decimal("999999999999.99")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}$")
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_PALIERS_MAX = 4
_DELAI_MAX = 365
_CIBLES_PIECE = (
    "facture_client",
    "facture_fournisseur",
    "ecriture",
    "note_credit",
    "depense_employe",
    "releve_bancaire",
    "paiement_prepare",
    "rapprochement",
)
ROLES_APPROBATEURS_JUGEMENT = frozenset({"finance", "nathan_owner", "admin"})
_GENRES_JUGEMENT = ("jugement", "estimation")


def cibles_piece() -> tuple[str, ...]:
    """Les opérations de M5 auxquelles une pièce justificative peut se lier."""
    return _CIBLES_PIECE


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_operations.construire_verdict(code, detail=detail)


def _texte_borne(valeur: Any, maximum: int) -> str | None:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur.strip()) > maximum:
        return None
    if any(c in valeur for c in ("\n", "\r", "\x00")):
        return None
    return valeur.strip()


def _date(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or not _DATE.fullmatch(valeur):
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def _jour_iso(horodatage: Any) -> str | None:
    try:
        return datetime.fromisoformat(horodatage).date().isoformat() if isinstance(horodatage, str) else None
    except ValueError:
        return None


def _horodatage_valide(horodatage: Any) -> dict[str, str] | None:
    try:
        instant = datetime.fromisoformat(horodatage) if isinstance(horodatage, str) else None
    except ValueError:
        instant = None
    if instant is None or instant.tzinfo is None:
        return _verdict("REJ-OPS-ENTREE-INVALIDE", "horodatage ISO 8601 avec fuseau requis")
    return None


def montant_texte(valeur: Any, champ: str, *, nul_permis: bool = False) -> tuple[Decimal | None, dict[str, str] | None]:
    """Un montant au cent depuis un TEXTE décimal (jamais un nombre JSON), strictement positif (ou nul si permis)."""
    if isinstance(valeur, bool) or not isinstance(valeur, (str, Decimal)):
        return None, _verdict("REJ-OPS-MONTANT-INVALIDE", f"{champ} : texte décimal exigé (jamais un nombre JSON)")
    try:
        montant = Decimal(valeur) if isinstance(valeur, str) else valeur
    except InvalidOperation:
        return None, _verdict("REJ-OPS-MONTANT-INVALIDE", f"{champ} : {valeur!r} n'est pas un décimal")
    if not montant.is_finite() or montant < 0 or (montant == 0 and not nul_permis) or montant > _MONTANT_MAX:
        return None, _verdict("REJ-OPS-MONTANT-INVALIDE", f"{champ} : fini, positif et au plus {_MONTANT_MAX}")
    if montant.as_tuple().exponent < -2:
        return None, _verdict("REJ-OPS-MONTANT-INVALIDE", f"{champ} : au cent près (deux décimales au plus)")
    return montant.quantize(_CENT, rounding=ROUND_HALF_UP), None


def _txt(valeur: Decimal) -> str:
    return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def formater_cad(montant: Decimal) -> str:
    """« 1 234,56 $ » : la forme québécoise, pour un texte destiné à une personne (jamais pour un calcul)."""
    entier, _, cents = format(montant.quantize(_CENT, rounding=ROUND_HALF_UP), "f").partition(".")
    groupes = []
    while len(entier) > 3:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    groupes.insert(0, entier)
    return " ".join(groupes) + "," + cents + " $"


# ------------------------------------------------------------------------------------------------- relances
def lire_politique_relances(brut: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """La politique de relance que le PROPRIÉTAIRE a déclarée (`configuration.operations.relances`) : le délai entre
    l'envoi d'une facture et son échéance, et les paliers de retard (en jours après l'échéance) des relances
    successives.
    Absente ou mal formée : refus qui dit quoi déclarer ; rien n'est supposé."""
    a_declarer = (
        "déclarer configuration.operations.relances : delai_echeance_jours (0 à 365, jours entre l'envoi et "
        "l'échéance) et paliers_jours_apres_echeance (1 à 4 entiers croissants, jours de retard de chaque "
        "relance) — décision du propriétaire, jamais supposée"
    )
    if not isinstance(brut, Mapping) or set(brut) != {"delai_echeance_jours", "paliers_jours_apres_echeance"}:
        return None, _verdict("REJ-OPS-CONFIGURATION-A-DECLARER", a_declarer)
    delai, paliers = brut["delai_echeance_jours"], brut["paliers_jours_apres_echeance"]
    if type(delai) is not int or not 0 <= delai <= _DELAI_MAX:
        return None, _verdict(
            "REJ-OPS-CONFIGURATION-A-DECLARER", "delai_echeance_jours : entier de 0 à 365. " + a_declarer
        )
    if (
        not isinstance(paliers, list)
        or not 1 <= len(paliers) <= _PALIERS_MAX
        or any(type(p) is not int or not 1 <= p <= _DELAI_MAX for p in paliers)
        or any(b <= a for a, b in zip(paliers, paliers[1:], strict=False))
    ):
        return None, _verdict(
            "REJ-OPS-CONFIGURATION-A-DECLARER",
            "paliers_jours_apres_echeance : 1 à 4 entiers croissants de 1 à 365. " + a_declarer,
        )
    return {"delai_echeance_jours": delai, "paliers_jours_apres_echeance": list(paliers)}, None


def texte_relance(niveau: int, facture_id: str, montant: Decimal, echeance: str, jours_retard: int) -> str:
    """Le BROUILLON de message de relance, en français québécois, sans nom ni coordonnée de client (l'envoi appartient à
    M1 et passe par l'approbation). Le ton monte avec le niveau ; aucune menace, aucune mention légale."""
    somme = formater_cad(montant)
    if niveau <= 1:
        return (
            f"Bonjour, sauf erreur, la facture {facture_id} de {somme} était payable le {echeance} et n'apparaît pas "
            "encore comme réglée. Si le paiement est déjà en route, vous pouvez ignorer ce rappel. Merci!"
        )
    if niveau == 2:
        return (
            f"Bonjour, la facture {facture_id} de {somme}, payable le {echeance}, est toujours impayée "
            f"({jours_retard} jours de retard). Pouvez-vous nous confirmer la date de paiement prévue? Merci!"
        )
    return (
        f"Bonjour, la facture {facture_id} de {somme} accuse maintenant {jours_retard} jours de retard depuis "
        f"son échéance du {echeance}. Nous aimerions en discuter avec vous et convenir d'une façon de la régler : "
        "pouvez-vous nous joindre cette semaine?"
    )


def credits_par_facture(etat_ops: Mapping[str, Any], genre: str) -> dict[str, Decimal]:
    """Le total (avant taxes) déjà crédité par facture, d'après les notes de crédit du registre."""
    totaux: dict[str, Decimal] = {}
    for note in etat_ops["par_type"]["op_note_credit_proposee"].values():
        if note["genre"] == genre:
            totaux[note["facture_id"]] = totaux.get(note["facture_id"], _ZERO) + Decimal(note["montant_avant_taxes"])
    return totaux


def _credits_ttc(etat_ops: Mapping[str, Any], genre: str) -> dict[str, Decimal]:
    totaux: dict[str, Decimal] = {}
    for note in etat_ops["par_type"]["op_note_credit_proposee"].values():
        if note["genre"] == genre:
            totaux[note["facture_id"]] = totaux.get(note["facture_id"], _ZERO) + Decimal(note["montant_apres_taxes"])
    return totaux


def preparer_relances(
    registre_ops: Any,
    etat_ops: Mapping[str, Any],
    factures: Sequence[Mapping[str, Any]],
    politique: Mapping[str, Any],
    aujourd_hui: Any,
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Prépare, pour chaque facture ENVOYÉE en retard, le BROUILLON de la relance de son niveau courant (un seul niveau
    par facture : on ne rattrape pas les paliers sautés). Idempotent par (facture, niveau). Une facture soldée par des
    notes de crédit n'est pas relancée. Rien n'est envoyé. Rend `{creees, evenements, deja, sans_retard, soldees,
    ignorees}` ; `evenements` : les charges `m5.creance_relance_preparee` que l'adaptateur publie dans la même
    transaction."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    jour = _date(aujourd_hui)
    if jour is None:
        return None, _verdict("REJ-OPS-DATE-INVALIDE", f"aujourd_hui {aujourd_hui!r} : AAAA-MM-JJ exigé")
    credits = _credits_ttc(etat_ops, "client")
    creees: list[dict[str, Any]] = []
    evenements: list[dict[str, Any]] = []
    ignorees: list[dict[str, str]] = []
    deja = sans_retard = soldees = 0
    for facture in sorted(
        (f for f in factures if f.get("statut") == "ENVOYEE"), key=lambda f: str(f.get("facture_id"))
    ):
        ident = str(facture.get("facture_id"))
        envoi = _jour_iso(facture.get("date_envoi"))
        montant = facture.get("montant_apres_taxes")
        if envoi is None or not isinstance(montant, Decimal) or not montant.is_finite() or montant <= 0:
            ignorees.append(
                {
                    "facture_id": ident,
                    "code": "REJ-OPS-ENTREE-INVALIDE",
                    "detail": "facture envoyée sans date d'envoi ou montant lisible : jamais complétée",
                }
            )
            continue
        net = montant - credits.get(ident, _ZERO)
        if net <= 0:
            soldees += 1
            continue
        echeance = date.fromisoformat(envoi) + timedelta(days=politique["delai_echeance_jours"])
        retard = (jour - echeance).days
        niveau = sum(1 for palier in politique["paliers_jours_apres_echeance"] if retard >= palier)
        if niveau == 0:
            sans_retard += 1
            continue
        texte = texte_relance(niveau, ident, net, echeance.isoformat(), retard)
        corps = {
            "facture_id": ident,
            "client_id": facture.get("client_id"),
            "niveau": niveau,
            "jours_retard": retard,
            "echeance": echeance.isoformat(),
            "montant_du": _txt(net),
            "date_reference": jour.isoformat(),
            "texte": texte,
            "statut": "BROUILLON",
            "envoi": "non_envoye : l'envoi appartient à M1 et passe par l'approbation humaine",
        }
        # L'identité d'une relance est (facture, niveau, échéance, montant dû) : `jours_retard`, `date_reference` et
        # `texte` (qui cite le retard) changent chaque jour sans que ce soit une autre relance.
        resultat, refus = operations_registre.ajouter_operation(
            registre_ops, etat_ops, "op_relance_preparee", f"relance:{ident}:{niveau}", corps, horodatage,
            hors_identite=("jours_retard", "date_reference", "texte"),
        )
        if refus is not None and refus["code"] == "REJ-OPS-DOUBLON":
            # Le montant dû (note de crédit) ou l'échéance (politique) a changé depuis la relance de ce niveau : elle
            # n'est jamais récrite, et elle ne bloque pas les autres factures du lot ; on le DIT.
            ignorees.append(
                {
                    "facture_id": ident,
                    "code": refus["code"],
                    "detail": f"relance de niveau {niveau} déjà préparée pour un autre montant dû ou une autre "
                    "échéance : jamais récrite, à reprendre à la main ou au niveau suivant",
                }
            )
            continue
        if refus is not None:
            return None, refus
        if resultat["statut"] == "deja":
            deja += 1
            continue
        operation = resultat["operation"]
        creees.append(
            {
                "relance_id": operation["relance_id"],
                "facture_id": ident,
                "niveau": niveau,
                "jours_retard": retard,
                "montant_du": corps["montant_du"],
                "echeance": corps["echeance"],
            }
        )
        evenements.append(
            {
                "evenement_id": f"m5-relance-{operation['relance_id']}",
                "relance_id": operation["relance_id"],
                "facture_id": ident,
                "client_id": facture.get("client_id") or "inconnu",
                "niveau": niveau,
                "jours_retard": retard,
                "montant_du": corps["montant_du"],
                "echeance": corps["echeance"],
                "date_reference": jour.isoformat(),
            }
        )
    return {
        "creees": creees,
        "evenements": evenements,
        "deja": deja,
        "sans_retard": sans_retard,
        "soldees": soldees,
        "ignorees": ignorees[:10],
        "ignorees_reste": max(0, len(ignorees) - 10),
        "politique": dict(politique),
    }, None


# ---------------------------------------------------------------------------------------------- notes de crédit
def _reste_creditable(
    facture: Mapping[str, Any], genre: str, deja: Sequence[Mapping[str, Any]]
) -> tuple[Decimal, dict[str, Decimal]] | None:
    lus = grand_livre.lire_montants_facture(facture, genre)
    if lus is None:
        return None
    avant, _apres, taxes_facture = lus
    reste_ht = avant - sum((Decimal(n["montant_avant_taxes"]) for n in deja), _ZERO)
    reste_taxes = dict(taxes_facture)
    for note in deja:
        for role, montant in note["taxes"].items():
            reste_taxes[role] = reste_taxes.get(role, _ZERO) - Decimal(montant)
    return reste_ht, reste_taxes


def proposer_note_credit(
    registre_ops: Any,
    etat_ops: Mapping[str, Any],
    registre_gl: Any,
    plan: Mapping[str, Any],
    dictionnaire_taux: Mapping[str, Any],
    *,
    genre: str,
    facture: Mapping[str, Any] | None,
    reference: Any,
    montant_avant_taxes: Any,
    date_effet: Any,
    motif: Any,
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Une NOTE DE CRÉDIT (client ou fournisseur) sur une facture de M5, et son BROUILLON d'écriture au grand livre.

    Client : débit produits (avant taxes), TPS et TVQ à percevoir (taxes), crédit comptes clients (total). Fournisseur :
    débit comptes fournisseurs (total), crédit du compte de charge de la facture (avant taxes), CTI et RTI. Les taxes
    sont recalculées avec les taux versionnés ; la note qui solde la facture reprend EXACTEMENT les taxes restantes
    (aucun cent perdu à l'arrondi) ; une note ne dépasse jamais ce que la facture permet encore de créditer. La note
    naît
    de sa clé (`nc:<genre>:<facture>:<référence>`) : la rejouer ne recrée rien."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    if genre not in ("client", "fournisseur"):
        return None, _verdict("REJ-OPS-ENTREE-INVALIDE", "genre : client ou fournisseur")
    if facture is None:
        return None, _verdict("REJ-OPS-FACTURE-INTROUVABLE", "facture absente du registre de M5")
    if genre == "client":
        ident = facture.get("facture_id")
        if facture.get("statut") not in ("ENVOYEE", "PAYEE"):
            return None, _verdict(
                "REJ-OPS-FACTURE-NON-EMISE", "une note de crédit client vise une facture envoyée ou payée"
            )
        jour_facture = _jour_iso(facture.get("date_envoi"))
    else:
        ident = facture.get("facture_fournisseur_id")
        if facture.get("statut") == "ANNULEE":
            return None, _verdict("REJ-OPS-FACTURE-ANNULEE", "facture fournisseur annulée : plus de dette à créditer")
        jour_facture = facture.get("date_facture") if _date(facture.get("date_facture")) else None
    if not isinstance(ident, str) or jour_facture is None:
        return None, _verdict("REJ-OPS-ENTREE-INVALIDE", "facture sans identifiant ou sans date lisible")
    ref = reference if isinstance(reference, str) and _REFERENCE.fullmatch(reference) else None
    if ref is None:
        return None, _verdict("REJ-OPS-ENTREE-INVALIDE", "reference : numéro de la note (lettres, chiffres, . _ : / -)")
    texte_motif = _texte_borne(motif, 300)
    if texte_motif is None:
        return None, _verdict("REJ-OPS-ENTREE-INVALIDE", "motif obligatoire, une ligne de 300 caractères au plus")
    jour = _date(date_effet)
    if jour is None:
        return None, _verdict("REJ-OPS-DATE-INVALIDE", f"date_effet {date_effet!r} : AAAA-MM-JJ exigé")
    if jour < date.fromisoformat(jour_facture):
        return None, _verdict("REJ-OPS-DATE-INVALIDE", "une note de crédit ne précède pas sa facture")
    montant, refus = montant_texte(montant_avant_taxes, "montant_avant_taxes")
    if refus is not None:
        return None, refus
    cle = f"nc:{genre}:{ident}:{ref}"
    existantes = [
        n
        for n in etat_ops["par_type"]["op_note_credit_proposee"].values()
        if n["genre"] == genre and n["facture_id"] == ident and n["cle"] != cle
    ]
    reste = _reste_creditable(facture, genre, existantes)
    if reste is None:
        return None, _verdict("REJ-OPS-ENTREE-INVALIDE", "montants de la facture illisibles ou incohérents")
    reste_ht, reste_taxes = reste
    if montant > reste_ht:
        return None, _verdict(
            "REJ-OPS-NOTE-CREDIT-EXCEDE",
            f"{_txt(montant)} dépasse ce qui reste à créditer sur {ident} ({_txt(reste_ht)} avant taxes)",
        )
    if montant == reste_ht:
        taxes_note = {role: m for role, m in reste_taxes.items() if m > 0}
    else:
        calcul, refus_taux = taxes.calculer_taxes(montant, dictionnaire_taux)
        if refus_taux is not None:
            return None, refus_taux
        table = (
            {"tps_federale": "tps_a_percevoir", "tvq_quebec": "tvq_a_percevoir"}
            if genre == "client"
            else {"tps_federale": "tps_cti", "tvq_quebec": "tvq_rti"}
        )
        taxes_note = {table[t["id"]]: t["montant"] for t in calcul["taxes"] if t["montant"] > 0}
        for role, m in taxes_note.items():
            if m > reste_taxes.get(role, _ZERO):
                return None, _verdict(
                    "REJ-OPS-NOTE-CREDIT-EXCEDE",
                    f"la taxe {role} de cette note dépasse ce qui reste à créditer sur {ident}",
                )
    total_taxes = sum(taxes_note.values(), _ZERO)
    total = montant + total_taxes
    roles = plan["roles"]
    if genre == "client":
        lignes = [{"compte": roles["produits_services"], "debit": _txt(montant), "credit": None}]
        lignes += [{"compte": roles[role], "debit": _txt(m), "credit": None} for role, m in sorted(taxes_note.items())]
        lignes.append({"compte": roles["comptes_clients"], "debit": None, "credit": _txt(total)})
        libelle = f"Note de crédit {ref} sur la facture client {ident}"
        nature = "note_credit_client"
    else:
        compte, refus_compte = plan_comptable.compte_de_charge(
            plan, po_id=facture.get("po_id"), categorie=facture.get("categorie_depense")
        )
        if refus_compte is not None:
            return None, refus_compte
        lignes = [
            {"compte": roles["comptes_fournisseurs"], "debit": _txt(total), "credit": None},
            {"compte": compte, "debit": None, "credit": _txt(montant)},
        ]
        lignes += [{"compte": roles[role], "debit": None, "credit": _txt(m)} for role, m in sorted(taxes_note.items())]
        libelle = f"Note de crédit {ref} du fournisseur sur la facture {ident}"
        nature = "note_credit_fournisseur"
    note_id = operations_registre.identifiant("op_note_credit_proposee", cle)
    deja = etat_ops["par_type"]["op_note_credit_proposee"].get(note_id)
    corps = {
        "genre": genre,
        "facture_id": ident,
        "reference": ref,
        "date_effet": jour.isoformat(),
        "montant_avant_taxes": _txt(montant),
        "taxes": {role: _txt(m) for role, m in sorted(taxes_note.items())},
        "total_taxes": _txt(total_taxes),
        "montant_apres_taxes": _txt(total),
        "motif": texte_motif,
        "ecriture_id": grand_livre.identifiant_ecriture(f"auto:note_credit:{note_id}"),
        "facture_payee": genre == "client" and facture.get("statut") == "PAYEE",
    }
    if deja is None:
        ecriture, refus_gl = grand_livre.proposer_ecriture(
            registre_gl,
            plan,
            cle_piece=f"auto:note_credit:{note_id}",
            piece={"type": "note_credit", "reference": note_id},
            nature=nature,
            date_effet=jour.isoformat(),
            libelle=libelle[:200],
            lignes_brutes=lignes,
            horodatage=horodatage,
            origine="operations_comptables",
            pieces_connues={"note_credit": {note_id}},
        )
        if refus_gl is not None:
            return None, refus_gl
        del ecriture
    resultat, refus = operations_registre.ajouter_operation(
        registre_ops, etat_ops, "op_note_credit_proposee", cle, corps, horodatage
    )
    if refus is not None:
        return None, refus
    note = resultat["operation"]
    vue = {
        cle_: note[cle_]
        for cle_ in (
            "note_id",
            "genre",
            "facture_id",
            "reference",
            "date_effet",
            "montant_avant_taxes",
            "taxes",
            "total_taxes",
            "montant_apres_taxes",
            "ecriture_id",
            "facture_payee",
        )
    }
    vue["statut"] = "deja_proposee" if resultat["statut"] == "deja" else "proposee"
    vue["a_faire"] = "le brouillon d'écriture attend m5_valider_ecriture_comptable (N4)" + (
        "; la facture est PAYÉE : le remboursement ou l'avoir au client est une décision humaine"
        if corps["facture_payee"]
        else ""
    )
    return vue, None


# --------------------------------------------------------------------------------------- dépenses d'employés
def proposer_depense_employe(
    registre_ops: Any,
    etat_ops: Mapping[str, Any],
    registre_gl: Any,
    plan: Mapping[str, Any],
    dictionnaire_taux: Mapping[str, Any],
    *,
    employe_id: Any,
    reference: Any,
    date_depense: Any,
    categorie: Any,
    description: Any,
    montant_avant_taxes: Any,
    taxable: Any,
    total_recu: Any,
    compte_remboursement: Any,
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Une DÉPENSE D'EMPLOYÉ à rembourser, et son BROUILLON d'écriture : débit du compte de charge de sa catégorie
    (avant taxes), CTI et RTI (taxes payées, recalculées avec les taux versionnés), crédit du compte de
    remboursement des employés que le propriétaire a DÉSIGNÉ (un compte de passif du plan, jamais supposé). Le total
    du reçu doit égaler le
    total recalculé, sinon refus avec l'écart : le reçu est relu par une personne. Les crédits de taxes sont supposés
    récupérables à 100 % (comme ailleurs dans M5) : à valider par le CPA. Rien n'est remboursé ni approuvé ici."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    employe = employe_id if isinstance(employe_id, str) and _IDENTIFIANT.fullmatch(employe_id) else None
    ref = reference if isinstance(reference, str) and _REFERENCE.fullmatch(reference) else None
    texte_description = _texte_borne(description, 120)
    if employe is None or ref is None or texte_description is None or not isinstance(categorie, str):
        return None, _verdict(
            "REJ-OPS-ENTREE-INVALIDE",
            "employe_id (identifiant, jamais un nom), reference, categorie et description (120 car.)",
        )
    if type(taxable) is not bool:
        return None, _verdict("REJ-OPS-ENTREE-INVALIDE", "taxable : vrai ou faux, jamais supposé")
    jour = _date(date_depense)
    if jour is None:
        return None, _verdict("REJ-OPS-DATE-INVALIDE", f"date_depense {date_depense!r} : AAAA-MM-JJ exigé")
    montant, refus = montant_texte(montant_avant_taxes, "montant_avant_taxes")
    if refus is not None:
        return None, refus
    recu, refus = montant_texte(total_recu, "total_recu")
    if refus is not None:
        return None, refus
    if not isinstance(compte_remboursement, str):
        return None, _verdict(
            "REJ-OPS-COMPTE-A-DECLARER",
            "déclarer configuration.operations.compte_remboursement_employes : le compte de passif du plan où "
            "inscrire ce que l'entreprise doit aux employés (décision du propriétaire avec le CPA, jamais supposée)",
        )
    refus = plan_comptable.compte_utilisable(plan, compte_remboursement)
    if refus is not None:
        return None, refus
    if plan["comptes"][compte_remboursement]["type"] != "passif":
        return None, _verdict(
            "REJ-OPS-COMPTE-A-DECLARER", f"le compte {compte_remboursement} n'est pas un compte de passif"
        )
    compte_charge, refus = plan_comptable.compte_de_charge(plan, po_id=None, categorie=categorie)
    if refus is not None:
        return None, refus
    if taxable:
        calcul, refus_taux = taxes.calculer_taxes(montant, dictionnaire_taux)
        if refus_taux is not None:
            return None, refus_taux
        taxes_depense = {
            {"tps_federale": "tps_cti", "tvq_quebec": "tvq_rti"}[t["id"]]: t["montant"]
            for t in calcul["taxes"]
            if t["montant"] > 0
        }
    else:
        taxes_depense = {}
    total_taxes = sum(taxes_depense.values(), _ZERO)
    total = montant + total_taxes
    if total != recu:
        return None, _verdict(
            "REJ-OPS-MONTANT-INVALIDE",
            f"le total du reçu ({_txt(recu)}) diffère du total recalculé ({_txt(total)}, taxes aux taux versionnés) : "
            "écart " + _txt(abs(recu - total)) + " ; relire le reçu avant de proposer la dépense",
        )
    cle = f"dep:{employe}:{ref}"
    depense_id = operations_registre.identifiant("op_depense_employe_proposee", cle)
    corps = {
        "employe_id": employe,
        "reference": ref,
        "date_depense": jour.isoformat(),
        "categorie": categorie,
        "description": texte_description,
        "montant_avant_taxes": _txt(montant),
        "taxable": taxable,
        "taxes": {r: _txt(m) for r, m in sorted(taxes_depense.items())},
        "total_taxes": _txt(total_taxes),
        "montant_apres_taxes": _txt(total),
        "compte_charge": compte_charge,
        "compte_remboursement": compte_remboursement,
        "ecriture_id": grand_livre.identifiant_ecriture(f"auto:depense_employe:{depense_id}"),
    }
    deja = etat_ops["par_type"]["op_depense_employe_proposee"].get(depense_id)
    roles = plan["roles"]
    if deja is None:
        lignes = [{"compte": compte_charge, "debit": _txt(montant), "credit": None}]
        lignes += [{"compte": roles[r], "debit": _txt(m), "credit": None} for r, m in sorted(taxes_depense.items())]
        lignes.append({"compte": compte_remboursement, "debit": None, "credit": _txt(total)})
        _, refus_gl = grand_livre.proposer_ecriture(
            registre_gl,
            plan,
            cle_piece=f"auto:depense_employe:{depense_id}",
            piece={"type": "depense_employe", "reference": depense_id},
            nature="depense_employe",
            date_effet=jour.isoformat(),
            libelle=f"Dépense d'employé {ref} : {texte_description}"[:200],
            lignes_brutes=lignes,
            horodatage=horodatage,
            origine="operations_comptables",
            pieces_connues={"depense_employe": {depense_id}},
        )
        if refus_gl is not None:
            return None, refus_gl
    resultat, refus = operations_registre.ajouter_operation(
        registre_ops, etat_ops, "op_depense_employe_proposee", cle, corps, horodatage
    )
    if refus is not None:
        return None, refus
    depense = resultat["operation"]
    vue = {
        k: depense[k]
        for k in (
            "depense_id",
            "employe_id",
            "reference",
            "date_depense",
            "categorie",
            "montant_avant_taxes",
            "taxes",
            "total_taxes",
            "montant_apres_taxes",
            "compte_charge",
            "compte_remboursement",
            "ecriture_id",
        )
    }
    vue["statut"] = "deja_proposee" if resultat["statut"] == "deja" else "proposee"
    vue["a_faire"] = (
        "joindre le reçu (m5_lier_piece_justificative) ; le brouillon d'écriture attend "
        "m5_valider_ecriture_comptable (N4) ; le remboursement lui-même se fait hors d'OPSYS"
    )
    return vue, None


# --------------------------------------------------------------------------------------- pièces justificatives
def lier_piece(
    registre_ops: Any,
    etat_ops: Mapping[str, Any],
    *,
    cible_type: Any,
    cible_id: Any,
    cibles_connues: Mapping[str, Sequence[str]],
    nom: Any,
    sha256: Any,
    taille: Any,
    lie_par: Any,
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Lie une PIÈCE JUSTIFICATIVE (son empreinte SHA-256, son nom, sa taille ; jamais son contenu) à une opération de
    M5 qui EXISTE. Idempotent par (cible, empreinte). La même empreinte liée à deux cibles différentes est permise mais
    signalée (`reutilisee_ailleurs`) : un même reçu ne justifie pas deux dépenses."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    if cible_type not in _CIBLES_PIECE or not isinstance(cible_id, str) or not cible_id.strip():
        return None, _verdict("REJ-OPS-PIECE-INVALIDE", f"cible_type parmi {', '.join(_CIBLES_PIECE)} et cible_id")
    if cible_id not in set(cibles_connues.get(cible_type, ())):
        return None, _verdict("REJ-OPS-PIECE-INTROUVABLE", f"{cible_type} {cible_id!r} absent du registre de M5")
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        return None, _verdict("REJ-OPS-PIECE-INVALIDE", "sha256 : 64 caractères hexadécimaux minuscules")
    nom_propre = _texte_borne(nom, 120)
    if (
        nom_propre is None
        or "/" in nom_propre
        or "\\" in nom_propre
        or ".." in nom_propre
        or not nom_propre.isprintable()
    ):
        return None, _verdict("REJ-OPS-PIECE-INVALIDE", "nom : un nom de fichier seul (sans chemin), 120 car. au plus")
    if type(taille) is not int or not 1 <= taille <= 200_000_000:
        return None, _verdict("REJ-OPS-PIECE-INVALIDE", "taille : entier d'octets de 1 à 200 000 000")
    if not isinstance(lie_par, str) or not lie_par.strip():
        return None, _verdict("REJ-OPS-PIECE-INVALIDE", "lie_par : l'identité de celui qui lie la pièce")
    ailleurs = sorted(
        {
            p["cible_id"]
            for p in etat_ops["par_type"]["op_piece_liee"].values()
            if p["sha256"] == sha256 and (p["cible_type"], p["cible_id"]) != (cible_type, cible_id)
        }
    )
    corps = {
        "cible_type": cible_type,
        "cible_id": cible_id,
        "sha256": sha256,
        "nom": nom_propre,
        "taille": taille,
        "lie_par": lie_par.strip(),
    }
    resultat, refus = operations_registre.ajouter_operation(
        registre_ops, etat_ops, "op_piece_liee", f"piece:{cible_type}:{cible_id}:{sha256}", corps, horodatage
    )
    if refus is not None:
        return None, refus
    piece = resultat["operation"]
    return {
        "piece_id": piece["piece_id"],
        "cible_type": cible_type,
        "cible_id": cible_id,
        "sha256": sha256,
        "statut": "deja_liee" if resultat["statut"] == "deja" else "liee",
        "reutilisee_ailleurs": ailleurs[:5],
        "avertissement": (
            "la même pièce est déjà liée à d'autres opérations : un reçu ne justifie qu'une dépense"
            if ailleurs
            else None
        ),
    }, None


# ------------------------------------------------------------------------------------ paiements préparés
def preparer_paiement(
    registre_ops: Any,
    etat_ops: Mapping[str, Any],
    *,
    facture: Mapping[str, Any] | None,
    rapprochement: Mapping[str, Any] | None,
    date_prevue: Any,
    derogation_motif: Any,
    humain: Mapping[str, str],
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """PRÉPARE (jamais n'exécute) le paiement d'une facture fournisseur : une fiche (fournisseur, montant net des
    notes de crédit, date voulue, état du rapprochement PO/réception/facture) qu'une personne autorisée exécute HORS
    d'OPSYS (N5). Faite par un HUMAIN identifié (`humain`, établi par l'adaptateur). Une facture sur PO dont le
    rapprochement n'est pas « CONCORDANT » est refusée, sauf dérogation motivée d'une personne ; la réserve sur
    l'unité des prix de M6
    est toujours portée. Un seul paiement préparé par facture."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    if facture is None:
        return None, _verdict("REJ-OPS-FACTURE-INTROUVABLE", "facture fournisseur absente du registre de M5")
    if facture.get("statut") == "ANNULEE":
        return None, _verdict("REJ-OPS-FACTURE-ANNULEE", "facture fournisseur annulée : rien à payer")
    jour = _date(date_prevue)
    if jour is None:
        return None, _verdict("REJ-OPS-DATE-INVALIDE", f"date_prevue {date_prevue!r} : AAAA-MM-JJ exigé")
    ident = facture["facture_fournisseur_id"]
    total = facture.get("montant_apres_taxes")
    if not isinstance(total, Decimal) or not total.is_finite() or total <= 0:
        return None, _verdict("REJ-OPS-PAIEMENT-INVALIDE", "montant de la facture illisible")
    net = total - _credits_ttc(etat_ops, "fournisseur").get(ident, _ZERO)
    if net <= 0:
        return None, _verdict(
            "REJ-OPS-PAIEMENT-INVALIDE", "la facture est soldée par des notes de crédit : rien à payer"
        )
    deja = [p for p in etat_ops["par_type"]["op_paiement_prepare"].values() if p["facture_fournisseur_id"] == ident]
    if deja:
        return None, _verdict(
            "REJ-OPS-PAIEMENT-DEJA-PREPARE", f"le paiement {deja[0]['paiement_id']} couvre déjà la facture {ident}"
        )
    verdict_rapprochement = None if facture.get("po_id") is None else (rapprochement or {}).get("verdict")
    derogation = None
    if facture.get("po_id") is not None and verdict_rapprochement != "CONCORDANT":
        derogation = _texte_borne(derogation_motif, 300)
        if derogation is None or len(derogation) < 10:
            return None, _verdict(
                "REJ-OPS-PAIEMENT-RAPPROCHEMENT",
                f"le rapprochement du PO {facture['po_id']} est « {verdict_rapprochement} », pas « CONCORDANT » : "
                "résoudre l'écart, ou donner une dérogation motivée (10 caractères au moins) d'une personne",
            )
    corps = {
        "facture_fournisseur_id": ident,
        "fournisseur_id": facture.get("fournisseur_id"),
        "numero_facture": facture.get("numero_facture"),
        "po_id": facture.get("po_id"),
        "montant": _txt(net),
        "devise": "CAD",
        "date_prevue": jour.isoformat(),
        "rapprochement": verdict_rapprochement if facture.get("po_id") is not None else "SANS_PO",
        "derogation_motif": derogation,
        "reserves": ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"] if facture.get("po_id") else [],
        "prepare_par": humain["par"],
        "role": humain["role"],
        "voie": humain["voie"],
        "execution": "hors_opsys : payer un fournisseur est N5 (propriétaire ET attestation du professionnel)",
        "statut": "PREPARE",
    }
    resultat, refus = operations_registre.ajouter_operation(
        registre_ops, etat_ops, "op_paiement_prepare", f"paiement:{ident}", corps, horodatage
    )
    if refus is not None:
        return None, refus
    p = resultat["operation"]
    return {
        "paiement_id": p["paiement_id"],
        "facture_fournisseur_id": ident,
        "montant": corps["montant"],
        "date_prevue": corps["date_prevue"],
        "rapprochement": corps["rapprochement"],
        "derogation": derogation is not None,
        "reserves": corps["reserves"],
        "statut": "deja_prepare" if resultat["statut"] == "deja" else "prepare",
        "execution": corps["execution"],
    }, None


# ---------------------------------------------------------------------------------- jugements et estimations
def enregistrer_jugement(
    registre_ops: Any,
    etat_ops: Mapping[str, Any],
    *,
    genre: Any,
    periode: Any,
    sujet: Any,
    description: Any,
    montant: Any,
    hypotheses: Any,
    base: Any,
    humain: Mapping[str, str],
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Consigne un JUGEMENT ou une ESTIMATION comptable (provision, durée d'amortissement, créance douteuse…) faite par
    une PERSONNE : le sujet, ce qu'elle a décidé, ses hypothèses et sa base. Le registre alimente le dossier du CPA ; il
    ne calcule ni ne valide rien : un montant est celui que la personne déclare. Append-only (une révision est un
    nouvel enregistrement)."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    if genre not in _GENRES_JUGEMENT:
        return None, _verdict("REJ-OPS-JUGEMENT-INVALIDE", "genre : jugement ou estimation")
    if grand_livre.fin_de_periode(periode) is None:
        return None, _verdict("REJ-OPS-PERIODE-INVALIDE", f"période {periode!r} : AAAA-MM exigé")
    texte_sujet = _texte_borne(sujet, 120)
    texte_description = _texte_borne(description, 400)
    texte_base = _texte_borne(base, 300)
    if texte_sujet is None or texte_description is None or texte_base is None:
        return None, _verdict(
            "REJ-OPS-JUGEMENT-INVALIDE", "sujet (120), description (400) et base (300) : une ligne chacun, non vides"
        )
    if (
        not isinstance(hypotheses, list)
        or not 1 <= len(hypotheses) <= 8
        or any(_texte_borne(h, 200) is None for h in hypotheses)
    ):
        return None, _verdict("REJ-OPS-JUGEMENT-INVALIDE", "hypotheses : 1 à 8 textes d'une ligne (200 car. au plus)")
    valeur = None
    if montant is not None:
        valeur_decimale, refus = montant_texte(montant, "montant", nul_permis=True)
        if refus is not None:
            return None, refus
        valeur = _txt(valeur_decimale)
    corps = {
        "genre": genre,
        "periode": periode,
        "sujet": texte_sujet,
        "description": texte_description,
        "montant": valeur,
        "hypotheses": [h.strip() for h in hypotheses],
        "base": texte_base,
        "par": humain["par"],
        "role": humain["role"],
        "voie": humain["voie"],
    }
    cle = f"jugement:{periode}:{genre}:{texte_sujet.lower()}:{texte_description.lower()[:60]}"
    resultat, refus = operations_registre.ajouter_operation(
        registre_ops, etat_ops, "op_jugement_enregistre", cle, corps, horodatage
    )
    if refus is not None:
        return None, refus
    j = resultat["operation"]
    return {
        "jugement_id": j["jugement_id"],
        "genre": genre,
        "periode": periode,
        "sujet": texte_sujet,
        "montant": valeur,
        "statut": "deja_consigne" if resultat["statut"] == "deja" else "consigne",
    }, None
