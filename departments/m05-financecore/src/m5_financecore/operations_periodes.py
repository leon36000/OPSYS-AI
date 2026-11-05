"""Périodes comptables (ouverture, préclôture), flux fournisseur et mesures de M5 : des CONSTATS lus des registres.

Module pur (aucun import d'`opsys`, aucune horloge, aucun réseau, jamais le registre des mouvements). Il ne clôt
rien : clore un mois est `m5_clore_periode_comptable` (N4, une personne). La préclôture dit ce qui empêcherait de clore
sans surprise (`BLOQUANT`) et ce qu'une personne devrait vérifier (`A_VERIFIER`) ; c'est une liste de contrôle, pas une
décision. L'ouverture consigne les soldes d'ouverture (la balance des écritures définitives avant la période) et dit si
la période précédente est close.

Les mesures sont des NOMBRES et des montants que le code compte dans les registres ; M8 les affiche sans les recalculer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import encodage, grand_livre, operations_registre, recu_calcul, verdicts_operations

__all__ = [
    "VERSION",
    "ouvrir_periode",
    "preclore_periode",
    "mesures_comptables",
    "flux_fournisseur",
    "soldes_avant",
    "controles",
]

VERSION = "1.0.0"
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_CONTROLES = (
    "brouillons_en_attente",
    "balance_equilibree",
    "factures_clients_sans_ecriture",
    "factures_fournisseurs_sans_ecriture",
    "rapprochement_bancaire",
    "pieces_justificatives",
    "taxes_rapprochees",
    "jugements_et_estimations",
    "ouverture_consignee",
)
_PIECES_A_JUSTIFIER = ("facture_fournisseur", "depense_employe", "recu", "manuelle")


def controles() -> tuple[str, ...]:
    """Les neuf contrôles de la préclôture, dans l'ordre."""
    return _CONTROLES


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_operations.construire_verdict(code, detail=detail)


def _txt(valeur: Decimal) -> str:
    return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _bornes_mois(periode: Any) -> tuple[date, date] | None:
    fin = grand_livre.fin_de_periode(periode)
    return None if fin is None else (fin.replace(day=1), fin)


def soldes_avant(etat_gl: Mapping[str, Any], jour: date) -> dict[str, Decimal]:
    """Le solde débiteur (positif) ou créditeur (négatif) de chaque compte, écritures DÉFINITIVES datées avant "
    "`jour`."""
    soldes: dict[str, Decimal] = {}
    for ident in etat_gl["ordre"]:
        e = etat_gl["ecritures"][ident]
        if e["statut"] != "DEFINITIVE" or date.fromisoformat(e["date_effet"]) >= jour:
            continue
        for ligne in e["lignes"]:
            soldes[ligne["compte"]] = soldes.get(ligne["compte"], _ZERO) + ligne["debit"] - ligne["credit"]
    return {compte: s for compte, s in sorted(soldes.items()) if s != 0}


def _empreinte_soldes_ouverture(soldes: Mapping[str, Decimal]) -> str:
    """Même empreinte canonique pour l'ouverture consignée et le contrôle de préclôture."""
    return encodage.empreinte("m5.ouverture.soldes.v1", {c: _txt(s) for c, s in soldes.items()})


# ------------------------------------------------------------------------------------------------ ouverture
def ouvrir_periode(
    registre_ops: Any,
    etat_ops: Mapping[str, Any],
    etat_gl: Mapping[str, Any],
    *,
    periode: Any,
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Consigne l'OUVERTURE d'un mois : ses soldes d'ouverture (écritures définitives avant le 1er du mois) et l'état de
    la période précédente. Refuse un mois déjà clos. Idempotent par (mois, empreinte des soldes) : si les soldes
    d'ouverture ont changé depuis (une écriture antérieure validée entre-temps), c'est une NOUVELLE ouverture,
    l'ancienne
    reste dans l'historique."""
    bornes = _bornes_mois(periode)
    if bornes is None:
        return None, _verdict("REJ-OPS-PERIODE-INVALIDE", f"période {periode!r} : AAAA-MM exigé")
    debut, fin = bornes
    verrou = etat_gl["verrou"]
    if verrou is not None and fin <= verrou:
        return None, _verdict("REJ-OPS-PERIODE-CLOSE", f"{periode} est close (verrou au {verrou.isoformat()})")
    veille = debut - timedelta(days=1)
    soldes = soldes_avant(etat_gl, debut)
    sans_historique = not any(date.fromisoformat(e["date_effet"]) < debut for e in etat_gl["ecritures"].values())
    precedente_close = verrou is not None and verrou >= veille
    empreinte = _empreinte_soldes_ouverture(soldes)
    corps = {
        "periode": periode,
        "soldes_ouverture": {c: _txt(s) for c, s in soldes.items()},
        "empreinte_soldes": empreinte,
        "total_debiteur": _txt(sum((s for s in soldes.values() if s > 0), _ZERO)),
        "total_crediteur": _txt(-sum((s for s in soldes.values() if s < 0), _ZERO)),
    }
    resultat, refus = operations_registre.ajouter_operation(
        registre_ops, etat_ops, "op_periode_ouverte", f"ouverture:{periode}:{empreinte[:16]}", corps, horodatage
    )
    if refus is not None:
        return None, refus
    o = resultat["operation"]
    avertissements = []
    if not precedente_close and not sans_historique:
        avertissements.append("la période précédente n'est pas close : les soldes d'ouverture sont PROVISOIRES")
    if corps["total_debiteur"] != corps["total_crediteur"]:
        avertissements.append("les soldes d'ouverture ne s'équilibrent pas : à expliquer avant d'aller plus loin")
    return {
        "ouverture_id": o["ouverture_id"],
        "periode": periode,
        "statut": "deja_consignee" if resultat["statut"] == "deja" else "consignee",
        "comptes": len(soldes),
        "total_debiteur": corps["total_debiteur"],
        "total_crediteur": corps["total_crediteur"],
        "precedente_close": precedente_close,
        "sans_historique": sans_historique,
        "avertissements": avertissements,
    }, None


# ----------------------------------------------------------------------------------------------- préclôture
def _controle(identifiant: str, statut: str, detail: str, nombre: int | None = None) -> dict[str, Any]:
    return {"controle": identifiant, "statut": statut, "detail": detail, "nombre": nombre}


def preclore_periode(
    registre_ops: Any,
    etat_ops: Mapping[str, Any],
    etat_gl: Mapping[str, Any],
    *,
    periode: Any,
    factures_clients: Sequence[Mapping[str, Any]],
    factures_fournisseurs: Sequence[Mapping[str, Any]],
    controle_taxes: Mapping[str, Any] | None,
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """La LISTE DE CONTRÔLE de préclôture d'un mois : neuf contrôles, chacun `OK`, `A_VERIFIER` ou `BLOQUANT`. Le statut
    global est `BLOQUE` (au moins un bloquant), `PRET_AVEC_RESERVES` (des points à vérifier) ou `PRET_A_CLORE`. Rien
    n'est
    clos ni modifié : clore est une décision humaine (N4). Le constat est consigné (reçu rejouable)."""
    bornes = _bornes_mois(periode)
    if bornes is None:
        return None, _verdict("REJ-OPS-PERIODE-INVALIDE", f"période {periode!r} : AAAA-MM exigé")
    debut, fin = bornes
    verrou = etat_gl["verrou"]
    if verrou is not None and fin <= verrou:
        return None, _verdict("REJ-OPS-PERIODE-CLOSE", f"{periode} est déjà close (verrou au {verrou.isoformat()})")
    ecritures = list(etat_gl["ecritures"].values())
    jusqua = [e for e in ecritures if date.fromisoformat(e["date_effet"]) <= fin]
    controles: list[dict[str, Any]] = []
    brouillons = [e for e in jusqua if e["statut"] == "BROUILLON"]
    controles.append(
        _controle(
            "brouillons_en_attente",
            "BLOQUANT" if brouillons else "OK",
            f"{len(brouillons)} brouillon(s) daté(s) au plus tard le {fin.isoformat()} : après la clôture ils ne se "
            f"valident "
            "plus"
            if brouillons
            else "aucun brouillon en attente",
            len(brouillons),
        )
    )
    definitives = [e for e in jusqua if e["statut"] == "DEFINITIVE"]
    debits = sum((ligne["debit"] for e in definitives for ligne in e["lignes"]), _ZERO)
    credits = sum((ligne["credit"] for e in definitives for ligne in e["lignes"]), _ZERO)
    controles.append(
        _controle(
            "balance_equilibree",
            "OK" if debits == credits else "BLOQUANT",
            f"débits {_txt(debits)} / crédits {_txt(credits)}",
        )
    )
    cles = {e["cle_piece"] for e in ecritures}
    sans_clients: list[str] = []
    for f in factures_clients:
        if f.get("statut") not in ("ENVOYEE", "PAYEE"):
            continue
        envoi = str(f.get("date_envoi"))[:10]
        if envoi <= fin.isoformat() and f"auto:facture_client:{f['facture_id']}:emission" not in cles:
            sans_clients.append(str(f["facture_id"]))
        paiement = str(f.get("date_paiement"))[:10]
        if (
            f.get("statut") == "PAYEE"
            and paiement <= fin.isoformat()
            and f"auto:facture_client:{f['facture_id']}:paiement" not in cles
        ):
            sans_clients.append(f"{f['facture_id']} (paiement)")
    controles.append(
        _controle(
            "factures_clients_sans_ecriture",
            "BLOQUANT" if sans_clients else "OK",
            (
                "sans écriture (ni brouillon) : "
                + ", ".join(sans_clients[:8])
                + " — lancer m5_generer_brouillons_comptables"
            )
            if sans_clients
            else "chaque facture cliente émise ou payée a son écriture",
            len(sans_clients),
        )
    )
    sans_fournisseurs = [
        str(f["facture_fournisseur_id"])
        for f in factures_fournisseurs
        if f.get("statut") in ("SAISIE", "CORRIGEE")
        and str(f.get("date_facture")) <= fin.isoformat()
        and f"auto:facture_fournisseur:{f['facture_fournisseur_id']}:saisie" not in cles
    ]
    controles.append(
        _controle(
            "factures_fournisseurs_sans_ecriture",
            "BLOQUANT" if sans_fournisseurs else "OK",
            ("sans écriture (ni brouillon) : " + ", ".join(sans_fournisseurs[:8]))
            if sans_fournisseurs
            else "chaque facture fournisseur vivante a son écriture",
            len(sans_fournisseurs),
        )
    )
    # rapprochement bancaire : confirmé couvrant la fin du mois ?
    couvrants = [
        r
        for r in etat_ops["par_type"]["op_rapprochement_prepare"].values()
        if r["periode_debut"] <= fin.isoformat() <= r["periode_fin"]
    ]
    confirmes = {c["rapprochement_vise"] for c in etat_ops["par_type"]["op_rapprochement_confirme"].values()}
    non_nuls = [r for r in couvrants if r["etat"] == "ECART" and r["rapprochement_id"] not in confirmes]
    if non_nuls:
        controles.append(
            _controle(
                "rapprochement_bancaire",
                "BLOQUANT",
                f"{len(non_nuls)} rapprochement(s) couvrant la fin du mois ont un écart non nul et "
                "ne sont pas confirmés",
                len(non_nuls),
            )
        )
    elif any(r["rapprochement_id"] in confirmes for r in couvrants):
        controles.append(
            _controle("rapprochement_bancaire", "OK", "un rapprochement confirmé couvre la fin du mois", len(couvrants))
        )
    else:
        controles.append(
            _controle(
                "rapprochement_bancaire",
                "A_VERIFIER",
                "aucun rapprochement bancaire confirmé ne couvre la fin du mois (importer le relevé et le confirmer)",
                len(couvrants),
            )
        )
    # pièces justificatives
    liees = {(p["cible_type"], p["cible_id"]) for p in etat_ops["par_type"]["op_piece_liee"].values()}
    manquantes: list[str] = []
    for e in jusqua:
        type_piece, reference = e["piece"]["type"], e["piece"]["reference"]
        if type_piece not in _PIECES_A_JUSTIFIER:
            continue
        cible = (
            (type_piece, reference)
            if type_piece in ("facture_fournisseur", "depense_employe")
            else ("ecriture", e["ecriture_id"])
        )
        if cible not in liees:
            manquantes.append(f"{cible[0]}:{cible[1]}")
    controles.append(
        _controle(
            "pieces_justificatives",
            "A_VERIFIER" if manquantes else "OK",
            (
                f"{len(manquantes)} écriture(s) sans pièce justificative liée (m5_lier_piece_justificative)"
                if manquantes
                else "chaque écriture à justifier a sa pièce liée"
            ),
            len(manquantes),
        )
    )
    # taxes
    if controle_taxes is None:
        controles.append(_controle("taxes_rapprochees", "A_VERIFIER", "le rapprochement TPS/TVQ n'a pas été exécuté"))
    else:
        controles.append(
            _controle(
                "taxes_rapprochees",
                "OK" if controle_taxes.get("verdict") == "CONCORDANT" else "A_VERIFIER",
                "TPS/TVQ concordantes avec les taux versionnés"
                if controle_taxes.get("verdict") == "CONCORDANT"
                else "écarts TPS/TVQ nommés dans m5_rapprocher_grand_livre : à expliquer",
            )
        )
    jugements = [j for j in etat_ops["par_type"]["op_jugement_enregistre"].values() if j["periode"] == periode]
    controles.append(
        _controle(
            "jugements_et_estimations",
            "OK" if jugements else "A_VERIFIER",
            f"{len(jugements)} jugement(s) ou estimation(s) consigné(s)"
            if jugements
            else "aucun jugement ni estimation consigné pour ce mois : confirmer qu'il n'y en a pas (provisions, "
            "amortissement, créances douteuses)",
            len(jugements),
        )
    )
    ouvertures = [
        etat_ops["par_type"]["op_periode_ouverte"][identifiant]
        for identifiant in etat_ops["ordre"]["op_periode_ouverte"]
        if etat_ops["par_type"]["op_periode_ouverte"][identifiant]["periode"] == periode
    ]
    empreinte_soldes_actuels = _empreinte_soldes_ouverture(soldes_avant(etat_gl, debut))
    ouverture_a_jour = any(o.get("empreinte_soldes") == empreinte_soldes_actuels for o in ouvertures)
    if ouverture_a_jour:
        statut_ouverture = "OK"
        detail_ouverture = "une ouverture consignée correspond aux soldes d'ouverture actuels"
    elif ouvertures:
        statut_ouverture = "A_VERIFIER"
        detail_ouverture = (
            "empreinte d'ouverture absente ou différente des soldes actuels : relancer m5_ouvrir_periode_comptable"
        )
    else:
        statut_ouverture = "A_VERIFIER"
        detail_ouverture = "ouverture du mois non consignée (m5_ouvrir_periode)"
    controles.append(
        _controle(
            "ouverture_consignee",
            statut_ouverture,
            detail_ouverture,
        )
    )
    bloquants = [c for c in controles if c["statut"] == "BLOQUANT"]
    a_verifier = [c for c in controles if c["statut"] == "A_VERIFIER"]
    statut = "BLOQUE" if bloquants else ("PRET_AVEC_RESERVES" if a_verifier else "PRET_A_CLORE")
    resume = {"controle_" + c["controle"]: c["statut"] for c in controles}
    empreinte = encodage.empreinte("m5.precloture.v1", periode, controles)
    recu = recu_calcul.construire(
        moteur="precloture_periode",
        version_moteur=VERSION,
        methode="Liste de contrôle : neuf contrôles lus du grand livre et du registre des opérations ; statut global "
        "BLOQUE s'il y a un bloquant, PRET_AVEC_RESERVES s'il y a un point à vérifier.",
        precision={"montants": "Decimal au cent"},
        parametres={"periode": periode},
        entrees={"empreinte_controles": empreinte},
        resultat={"statut": statut, **resume},
        avertissements=["La clôture reste une décision humaine (N4) : cette liste ne clôt rien."],
    )
    corps = {
        "periode": periode,
        "statut": statut,
        "controles": controles,
        "empreinte_controles": empreinte,
        "recu_empreinte": recu["empreinte"],
    }
    resultat, refus = operations_registre.ajouter_operation(
        registre_ops, etat_ops, "op_precloture_constatee", f"precloture:{periode}:{empreinte[:16]}", corps, horodatage
    )
    if refus is not None:
        return None, refus
    return {
        "precloture_id": resultat["operation"]["precloture_id"],
        "periode": periode,
        "statut": statut,
        "controles": controles,
        "bloquants": len(bloquants),
        "a_verifier": len(a_verifier),
        "recu": recu,
        "consignation": "deja_consignee" if resultat["statut"] == "deja" else "consignee",
        "a_faire": "clore le mois est m5_clore_periode_comptable (N4) : une personne le décide",
    }, None


# ------------------------------------------------------------------------------------------------- mesures
def mesures_comptables(
    etat_gl: Mapping[str, Any],
    etat_ops: Mapping[str, Any],
    *,
    creances: Mapping[str, Any],
    date_reference: str,
) -> dict[str, Any]:
    """Les mesures que M8 affiche (jamais recalculées chez lui) : créances ouvertes (nombre, total, par tranche d'âge),
    relances en brouillon, brouillons d'écriture en attente, écritures définitives, dernière période close, paiements
    préparés, rapprochements (préparés, confirmés, à écart), notes de crédit, dépenses d'employés, pièces liées. Que des
    nombres et des montants en texte décimal : aucun nom, aucun libellé."""
    ops = etat_ops["par_type"]
    confirmes = {c["rapprochement_vise"] for c in ops["op_rapprochement_confirme"].values()}
    paiements = list(ops["op_paiement_prepare"].values())
    notes = list(ops["op_note_credit_proposee"].values())
    depenses = list(ops["op_depense_employe_proposee"].values())
    rapprochements = list(ops["op_rapprochement_prepare"].values())
    verrou = etat_gl["verrou"]
    return {
        "date_reference": date_reference,
        "creances": {
            "nombre": creances["nombre"],
            "total": creances["total"],
            "par_tranche": dict(creances["par_tranche"]),
        },
        "relances_en_brouillon": sum(1 for r in ops["op_relance_preparee"].values()),
        "brouillons_en_attente": sum(1 for e in etat_gl["ecritures"].values() if e["statut"] == "BROUILLON"),
        "ecritures_definitives": etat_gl["definitives"],
        "derniere_periode_close": None if verrou is None else verrou.isoformat()[:7],
        "paiements_prepares": {
            "nombre": len(paiements),
            "total": _txt(sum((Decimal(p["montant"]) for p in paiements), _ZERO)),
        },
        "rapprochements": {
            "prepares": len(rapprochements),
            "confirmes": len(confirmes),
            "a_ecart": sum(1 for r in rapprochements if r["etat"] == "ECART"),
        },
        "notes_de_credit": {
            "nombre": len(notes),
            "total": _txt(sum((Decimal(n["montant_apres_taxes"]) for n in notes), _ZERO)),
        },
        "depenses_employes": {
            "nombre": len(depenses),
            "total": _txt(sum((Decimal(d["montant_apres_taxes"]) for d in depenses), _ZERO)),
        },
        "pieces_liees": len(ops["op_piece_liee"]),
    }


# ----------------------------------------------------------------------------------------- flux fournisseur
def flux_fournisseur(
    facture: Mapping[str, Any],
    rapprochement: Mapping[str, Any] | None,
    ecriture: Mapping[str, Any] | None,
    paiement: Mapping[str, Any] | None,
    notes_credit: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Où en est une facture fournisseur sur le chemin facture reçue → appariement avec la commande de M6 → brouillon
    d'écriture → paiement PRÉPARÉ. Chaque étape dit son état ; le paiement réel n'est jamais suivi ici (hors
    d'OPSYS)."""
    po = facture.get("po_id")
    verdict = None if po is None else (rapprochement or {}).get("verdict")
    if po is None:
        appariement = {
            "etape": "appariement_commande",
            "etat": "SANS_COMMANDE",
            "detail": "dépense sans bon de commande de M6 (catégorie de dépense)",
        }
    elif verdict == "CONCORDANT":
        appariement = {
            "etape": "appariement_commande",
            "etat": "CONCORDANT",
            "detail": f"la facture concorde avec la réception du PO {po}",
        }
    else:
        appariement = {
            "etape": "appariement_commande",
            "etat": verdict or "INCONNU",
            "detail": f"rapprochement du PO {po} : {verdict or 'non établi'} (voir m5_lister_comptes_a_payer)",
        }
    if ecriture is None:
        brouillon = {"etape": "brouillon_ecriture", "etat": "ABSENT", "detail": "aucun brouillon d'écriture"}
    else:
        brouillon = {
            "etape": "brouillon_ecriture",
            "etat": ecriture["statut"],
            "detail": f"écriture {ecriture['ecriture_id']}",
        }
    prepare = (
        {"etape": "paiement_prepare", "etat": "ABSENT", "detail": "aucun paiement préparé"}
        if paiement is None
        else {
            "etape": "paiement_prepare",
            "etat": paiement["statut"],
            "detail": f"{paiement['montant']} $ le {paiement['date_prevue']}",
        }
    )
    etapes = [
        {"etape": "facture_recue", "etat": facture["statut"], "detail": f"facture {facture['numero_facture']}"},
        appariement,
        brouillon,
        prepare,
        {
            "etape": "paiement_execute",
            "etat": "HORS_OPSYS",
            "detail": "l'exécution du paiement est humaine (N5) et n'est pas suivie par M5",
        },
    ]
    if facture["statut"] == "ANNULEE":
        suivante = "facture annulée : rien à faire"
    elif ecriture is None:
        suivante = "générer le brouillon d'écriture (m5_avancer_flux_fournisseur)"
    elif po is not None and verdict != "CONCORDANT":
        suivante = (
            "résoudre l'écart de rapprochement avec la commande, ou préparer le paiement avec une dérogation motivée"
        )
    elif paiement is None:
        suivante = "préparer le paiement (m5_preparer_paiement_fournisseur, N3) après la validation de l'écriture"
    else:
        suivante = "paiement préparé : une personne autorisée l'exécute hors d'OPSYS (N5)"
    return {
        "facture_fournisseur_id": facture["facture_fournisseur_id"],
        "etapes": etapes,
        "notes_de_credit": len(notes_credit),
        "prochaine_action": suivante,
    }
