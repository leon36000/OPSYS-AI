"""Dossier CPA de fin de période ou d'année de M5 : un paquet DÉTERMINISTE de fichiers (CSV, JSON, Beancount),
scellé par empreinte, avec sa liste de contrôle.

Module pur : aucun import d'`opsys`, aucune horloge (la date de référence est un argument), aucun réseau, aucune
écriture de fichier (il rend des OCTETS ; l'adaptateur les écrit dans un dossier confiné). Mêmes entrées, mêmes octets,
même sceau, sur toute machine : CSV en UTF-8 sans BOM et fins de ligne `\\n`, JSON à clés triées, lignes triées.

Le paquet contient : balance de vérification, grand livre de la période et soldes d'ouverture, brouillons encore en
attente, états de rapprochement bancaire, relevés TPS/TVQ PRÉPARÉS (par mois, depuis le grand livre), liste des pièces
justificatives, registre des jugements et estimations, journal des corrections, sous-comptes clients et fournisseurs,
export Beancount (cumulatif jusqu'à la fin), liste de contrôle et manifeste. Le sceau est le SHA-256 d'une forme
canonique du manifeste (fichiers, empreintes, têtes des registres) : retoucher un fichier, ou ajouter un maillon au
grand livre sans refaire le dossier, se voit.

CE QUE LE DOSSIER N'EST PAS. Ce n'est ni une compilation, ni un examen, ni un audit, ni des états financiers
vérifiés, ni une déclaration de taxes : c'est la matière préparée qu'un CPA reprend. La nature de la mission
(compilation, mission d'examen, audit) et ce qu'on peut remettre à une banque, à un investisseur ou à une autorité
sans ce professionnel sont des questions JURIDIQUES et professionnelles qu'OPSYS ne tranche pas : la liste de
contrôle les laisse « A_FAIRE ». Les relevés TPS/TVQ ne portent aucune ligne de formulaire officiel : « non
renseigné — source officielle requise ».
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import (
    analyse,
    encodage,
    grand_livre,
    grand_livre_beancount,
    operations_registre,
    releve_bancaire,
    verdicts_operations,
)

__all__ = ["VERSION", "construire_dossier", "verifier_fichiers", "noms_fichiers"]

VERSION = "1.0.0"
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_NOMS_FICHIERS = (
    "00-LISEZ-MOI.txt",
    "01-balance-verification.csv",
    "02-soldes-ouverture.csv",
    "03-grand-livre.csv",
    "04-brouillons-en-attente.csv",
    "05-rapprochements-bancaires.json",
    "06-releves-taxes-preparees.json",
    "07-liste-des-pieces.csv",
    "08-jugements-et-estimations.json",
    "09-journal-des-corrections.csv",
    "10-sous-comptes-clients.csv",
    "11-sous-comptes-fournisseurs.csv",
    "12-grand-livre.beancount",
    "13-liste-de-controle.json",
)
_PIECES_A_JUSTIFIER = ("facture_fournisseur", "depense_employe", "recu", "manuelle")
_NON_RENSEIGNE = "non renseigné — source officielle requise"


def noms_fichiers() -> tuple[str, ...]:
    """Les quatorze fichiers du dossier, dans l'ordre de leur numéro (hors MANIFESTE.json)."""
    return _NOMS_FICHIERS


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_operations.construire_verdict(code, detail=detail)


def _txt(valeur: Decimal) -> str:
    return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _t(valeur: Any) -> str:
    """Une cellule TEXTE (libellé, nom, référence) : neutralisée contre l'injection de formule."""
    return releve_bancaire.neutraliser_cellule(" ".join(str(valeur if valeur is not None else "").split()))


def _csv(entete: Sequence[str], lignes: Sequence[Sequence[str]]) -> bytes:
    sortie = io.StringIO(newline="")
    ecrivain = csv.writer(sortie, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    ecrivain.writerow(list(entete))
    for ligne in lignes:
        ecrivain.writerow(list(ligne))
    return sortie.getvalue().encode("utf-8")


def _json(valeur: Any) -> bytes:
    return (json.dumps(valeur, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


def _dans(jour: str, debut: date, fin: date) -> bool:
    return debut <= date.fromisoformat(jour) <= fin


# ------------------------------------------------------------------------------------------------ les fichiers
def _balance(etat_gl: Mapping[str, Any], plan: Mapping[str, Any], fin: date) -> tuple[bytes, Decimal, Decimal]:
    cumuls: dict[str, list[Decimal]] = {}
    for e in etat_gl["ecritures"].values():
        if e["statut"] != "DEFINITIVE" or date.fromisoformat(e["date_effet"]) > fin:
            continue
        for ligne in e["lignes"]:
            c = cumuls.setdefault(ligne["compte"], [_ZERO, _ZERO])
            c[0] += ligne["debit"]
            c[1] += ligne["credit"]
    lignes = []
    total_d = total_c = _ZERO
    for numero in sorted(cumuls):
        debit, credit = cumuls[numero]
        fiche = plan["comptes"].get(numero, {})
        solde = debit - credit
        lignes.append(
            [
                numero,
                _t(fiche.get("nom", "(absent du plan courant)")),
                fiche.get("type", ""),
                _txt(debit),
                _txt(credit),
                _txt(solde) if solde > 0 else "0.00",
                _txt(-solde) if solde < 0 else "0.00",
            ]
        )
        total_d, total_c = total_d + debit, total_c + credit
    lignes.append(["TOTAL", "", "", _txt(total_d), _txt(total_c), "", ""])
    return (
        _csv(["compte", "nom", "type", "total_debits", "total_credits", "solde_debiteur", "solde_crediteur"], lignes),
        total_d,
        total_c,
    )


def _ouverture(etat_gl: Mapping[str, Any], plan: Mapping[str, Any], debut: date) -> bytes:
    soldes: dict[str, Decimal] = {}
    for e in etat_gl["ecritures"].values():
        if e["statut"] == "DEFINITIVE" and date.fromisoformat(e["date_effet"]) < debut:
            for ligne in e["lignes"]:
                soldes[ligne["compte"]] = soldes.get(ligne["compte"], _ZERO) + ligne["debit"] - ligne["credit"]
    lignes = [
        [n, _t(plan["comptes"].get(n, {}).get("nom", "")), _txt(s) if s > 0 else "0.00", _txt(-s) if s < 0 else "0.00"]
        for n, s in sorted(soldes.items())
        if s != 0
    ]
    return _csv(["compte", "nom", "solde_debiteur", "solde_crediteur"], lignes)


def _grand_livre(etat_gl: Mapping[str, Any], plan: Mapping[str, Any], debut: date, fin: date) -> bytes:
    lignes = []
    definitives = sorted(
        (
            e
            for e in etat_gl["ecritures"].values()
            if e["statut"] == "DEFINITIVE" and _dans(e["date_effet"], debut, fin)
        ),
        key=lambda e: (e["date_effet"], e["numero"]),
    )
    for e in definitives:
        for ligne in e["lignes"]:
            lignes.append(
                [
                    e["date_effet"],
                    e["numero"],
                    e["ecriture_id"],
                    ligne["compte"],
                    _t(plan["comptes"].get(ligne["compte"], {}).get("nom", "")),
                    _t(e["libelle"]),
                    f"{e['piece']['type']}:{_t(e['piece']['reference'])}",
                    _txt(ligne["debit"]) if ligne["debit"] > 0 else "",
                    _txt(ligne["credit"]) if ligne["credit"] > 0 else "",
                ]
            )
    return _csv(
        ["date", "numero", "ecriture_id", "compte", "nom_compte", "libelle", "piece", "debit", "credit"], lignes
    )


def _brouillons(etat_gl: Mapping[str, Any], fin: date) -> bytes:
    lignes = []
    for e in sorted(
        (
            e
            for e in etat_gl["ecritures"].values()
            if e["statut"] == "BROUILLON" and date.fromisoformat(e["date_effet"]) <= fin
        ),
        key=lambda e: (e["date_effet"], e["ecriture_id"]),
    ):
        total = sum((ligne["debit"] for ligne in e["lignes"]), _ZERO)
        lignes.append(
            [
                e["date_effet"],
                e["ecriture_id"],
                _t(e["libelle"]),
                f"{e['piece']['type']}:{_t(e['piece']['reference'])}",
                _txt(total),
            ]
        )
    return _csv(["date", "ecriture_id", "libelle", "piece", "total"], lignes)


def _rapprochements(etat_ops: Mapping[str, Any], debut: date, fin: date) -> tuple[bytes, list[dict[str, Any]]]:
    confirmations = {c["rapprochement_vise"]: c for c in etat_ops["par_type"]["op_rapprochement_confirme"].values()}
    sortie = []
    for r in sorted(
        etat_ops["par_type"]["op_rapprochement_prepare"].values(),
        key=lambda r: (r["periode_fin"], r["rapprochement_id"]),
    ):
        if date.fromisoformat(r["periode_fin"]) < debut or date.fromisoformat(r["periode_debut"]) > fin:
            continue
        confirmation = confirmations.get(r["rapprochement_id"])
        sortie.append(
            {
                "rapprochement_id": r["rapprochement_id"],
                "periode": {"debut": r["periode_debut"], "fin": r["periode_fin"]},
                "etat": r["etat"],
                "ecart": r["ecart"],
                "solde_releve": r["solde_releve"],
                "solde_livre": r["solde_livre"],
                "releve": r["releve"],
                "depots_en_transit": r["depots_en_transit"],
                "cheques_en_circulation": r["cheques_en_circulation"],
                "non_comptabilise": r["non_comptabilise"],
                "appariements": r["appariements"],
                "recu_empreinte": r["recu_empreinte"],
                "confirme": None
                if confirmation is None
                else {
                    "par": confirmation["par"],
                    "role": confirmation["role"],
                    "motif_ecart": confirmation.get("motif_ecart"),
                    "horodatage": confirmation["horodatage"],
                },
            }
        )
    return _json(
        {
            "rapprochements": sortie,
            "mention": "États PRÉPARÉS ; seul un rapprochement « confirme » a été relu par une personne.",
        }
    ), sortie


def _releves_taxes(etat_gl: Mapping[str, Any], plan: Mapping[str, Any], debut: date, fin: date) -> bytes:
    roles = plan["roles"]
    comptes = {
        "tps_percue": (roles["tps_a_percevoir"], True),
        "tps_cti": (roles["tps_cti"], False),
        "tvq_percue": (roles["tvq_a_percevoir"], True),
        "tvq_rti": (roles["tvq_rti"], False),
    }
    mois: dict[str, dict[str, Decimal]] = {}
    for e in etat_gl["ecritures"].values():
        if e["statut"] != "DEFINITIVE" or not _dans(e["date_effet"], debut, fin):
            continue
        cle = e["date_effet"][:7]
        ligne_mois = mois.setdefault(cle, {k: _ZERO for k in comptes})
        for ligne in e["lignes"]:
            for nom, (compte, credit_positif) in comptes.items():
                if ligne["compte"] == compte:
                    ligne_mois[nom] += (
                        (ligne["credit"] - ligne["debit"]) if credit_positif else (ligne["debit"] - ligne["credit"])
                    )
    lignes = []
    total = {k: _ZERO for k in comptes}
    for cle in sorted(mois):
        m = mois[cle]
        for k in total:
            total[k] += m[k]
        lignes.append(
            {
                "mois": cle,
                **{k: _txt(v) for k, v in m.items()},
                "tps_nette": _txt(m["tps_percue"] - m["tps_cti"]),
                "tvq_nette": _txt(m["tvq_percue"] - m["tvq_rti"]),
            }
        )
    return _json(
        {
            "periode": {"debut": debut.isoformat(), "fin": fin.isoformat()},
            "nature": "RELEVÉ PRÉPARÉ depuis le grand livre (écritures définitives) : ce n'est pas une déclaration",
            "mois": lignes,
            "total": {
                **{k: _txt(v) for k, v in total.items()},
                "tps_nette": _txt(total["tps_percue"] - total["tps_cti"]),
                "tvq_nette": _txt(total["tvq_percue"] - total["tvq_rti"]),
            },
            "lignes_du_formulaire_officiel": _NON_RENSEIGNE,
            "regroupement_par_periode_de_production": (
                "à faire avec le CPA : la fréquence de production et la fin d'exercice sont des faits du propriétaire"
            ),
            "hypothese": "crédits de taxes sur intrants supposés récupérables à 100 % (comme ailleurs dans M5)",
            "mention": analyse.MENTION_COMPTABLE,
        }
    )


def _pieces(etat_gl: Mapping[str, Any], etat_ops: Mapping[str, Any], fin: date) -> tuple[bytes, int]:
    liees: dict[tuple[str, str], list[str]] = {}
    for p in etat_ops["par_type"]["op_piece_liee"].values():
        liees.setdefault((p["cible_type"], p["cible_id"]), []).append(p["sha256"])
    lignes = []
    manquantes = 0
    for e in sorted(
        (e for e in etat_gl["ecritures"].values() if date.fromisoformat(e["date_effet"]) <= fin),
        key=lambda e: (e["date_effet"], e["ecriture_id"]),
    ):
        type_piece, reference = e["piece"]["type"], e["piece"]["reference"]
        cible = (
            (type_piece, reference)
            if type_piece in ("facture_fournisseur", "depense_employe")
            else ("ecriture", e["ecriture_id"])
        )
        empreintes = sorted(liees.get(cible, []))
        requis = type_piece in _PIECES_A_JUSTIFIER
        etat = "LIEE" if empreintes else ("MANQUANTE" if requis else "NON_REQUISE")
        manquantes += etat == "MANQUANTE"
        lignes.append(
            [
                e["date_effet"],
                e["ecriture_id"],
                e["statut"],
                type_piece,
                _t(reference),
                e["piece"]["verification"],
                etat,
                ";".join(empreintes),
            ]
        )
    return _csv(
        [
            "date",
            "ecriture_id",
            "statut",
            "piece_type",
            "piece_reference",
            "verification_par_m5",
            "piece_justificative",
            "empreintes_sha256",
        ],
        lignes,
    ), manquantes


def _jugements(etat_ops: Mapping[str, Any], debut: date, fin: date) -> tuple[bytes, int]:
    gardes = []
    for j in sorted(
        etat_ops["par_type"]["op_jugement_enregistre"].values(), key=lambda j: (j["periode"], j["jugement_id"])
    ):
        mois = grand_livre.fin_de_periode(j["periode"])
        if mois is None or not (debut.replace(day=1) <= mois <= fin):
            continue
        gardes.append(
            {
                k: j[k]
                for k in (
                    "jugement_id",
                    "genre",
                    "periode",
                    "sujet",
                    "description",
                    "montant",
                    "hypotheses",
                    "base",
                    "par",
                    "role",
                    "voie",
                    "horodatage",
                )
            }
        )
    return _json(
        {
            "jugements_et_estimations": gardes,
            "nature": "consignés par des personnes ; OPSYS ne les valide pas",
            "mention": analyse.MENTION_COMPTABLE,
        }
    ), len(gardes)


def _corrections(
    etat_gl: Mapping[str, Any],
    etat_ops: Mapping[str, Any],
    factures_fournisseurs: Sequence[Mapping[str, Any]],
    debut: date,
    fin: date,
) -> tuple[bytes, int]:
    lignes: list[list[str]] = []
    for e in etat_gl["ecritures"].values():
        if e["contre_passe"] is not None and _dans(e["date_effet"], debut, fin):
            validation = e["validation"] or {}
            lignes.append(
                [
                    e["date_effet"],
                    "contre_passation",
                    e["ecriture_id"],
                    _t(e["libelle"]),
                    _t(validation.get("par", "")),
                    e["statut"],
                    e["contre_passe"],
                ]
            )
    for f in factures_fournisseurs:
        for m in f.get("modifications", []):
            jour = str(m["horodatage"])[:10]
            if _dans(jour, debut, fin):
                lignes.append(
                    [
                        jour,
                        m["type"].lower() + "_facture_fournisseur",
                        f["facture_fournisseur_id"],
                        _t(m["motif"]),
                        _t(m["par"]),
                        "ENREGISTREE",
                        "",
                    ]
                )
    for n in etat_ops["par_type"]["op_note_credit_proposee"].values():
        if _dans(n["date_effet"], debut, fin):
            lignes.append(
                [
                    n["date_effet"],
                    "note_credit_" + n["genre"],
                    n["note_id"],
                    _t(n["motif"]),
                    "",
                    "BROUILLON",
                    n["facture_id"],
                ]
            )
    confirmations = etat_ops["par_type"]["op_rapprochement_confirme"].values()
    for c in confirmations:
        if c.get("motif_ecart") and _dans(str(c["horodatage"])[:10], debut, fin):
            lignes.append(
                [
                    str(c["horodatage"])[:10],
                    "confirmation_rapprochement_avec_ecart",
                    c["rapprochement_vise"],
                    _t(c["motif_ecart"]),
                    _t(c["par"]),
                    "CONFIRME",
                    "",
                ]
            )
    lignes.sort(key=lambda r: (r[0], r[1], r[2]))
    return _csv(["date", "genre", "reference", "motif_ou_libelle", "par", "statut", "vise"], lignes), len(lignes)


def _sous_comptes(
    clients: Sequence[Mapping[str, Any]], fournisseurs: Sequence[Mapping[str, Any]]
) -> tuple[bytes, bytes]:
    lignes_c = []
    for f in sorted(
        (f for f in clients if f.get("statut") in ("ENVOYEE", "PAYEE")), key=lambda f: str(f["facture_id"])
    ):
        lignes_c.append(
            [
                _t(f["facture_id"]),
                _t(f.get("client_id")),
                str(f.get("date_envoi"))[:10],
                _txt(f["montant_avant_taxes"]),
                _txt(f["total_taxes"]),
                _txt(f["montant_apres_taxes"]),
                f["statut"],
                str(f.get("date_paiement") or "")[:10],
            ]
        )
    lignes_f = []
    for f in sorted(fournisseurs, key=lambda f: str(f["facture_fournisseur_id"])):
        lignes_f.append(
            [
                _t(f["facture_fournisseur_id"]),
                _t(f.get("fournisseur_id")),
                _t(f.get("numero_facture")),
                str(f.get("date_facture")),
                _t(f.get("po_id") or ""),
                _txt(f["montant_avant_taxes"]),
                _txt(f["total_taxes"]),
                _txt(f["montant_apres_taxes"]),
                f["statut"],
            ]
        )
    return (
        _csv(
            ["facture_id", "client_id", "date_envoi", "avant_taxes", "taxes", "apres_taxes", "statut", "date_paiement"],
            lignes_c,
        ),
        _csv(
            [
                "facture_fournisseur_id",
                "fournisseur_id",
                "numero_facture",
                "date_facture",
                "po_id",
                "avant_taxes",
                "taxes",
                "apres_taxes",
                "statut",
            ],
            lignes_f,
        ),
    )


def _beancount(etat_gl: Mapping[str, Any], plan: Mapping[str, Any], fin: date) -> bytes:
    filtre = {
        **etat_gl,
        "ecritures": {k: e for k, e in etat_gl["ecritures"].items() if date.fromisoformat(e["date_effet"]) <= fin},
    }
    return grand_livre_beancount.exporter_beancount(filtre, plan).encode("utf-8")


def _liste_de_controle(
    *,
    fin: date,
    etat_gl: Mapping[str, Any],
    etat_ops: Mapping[str, Any],
    total_d: Decimal,
    total_c: Decimal,
    pieces_manquantes: int,
    jugements: int,
    corrections: int,
    controle_taxes: Mapping[str, Any] | None,
    base_fiscale: Mapping[str, Any] | None,
    periode_precedente_close: bool | None,
) -> list[dict[str, str]]:
    def item(ident: str, statut: str, libelle: str, detail: str) -> dict[str, str]:
        return {"id": ident, "statut": statut, "libelle": libelle, "detail": detail}

    verrou = etat_gl["verrou"]
    brouillons = sum(
        1
        for e in etat_gl["ecritures"].values()
        if e["statut"] == "BROUILLON" and date.fromisoformat(e["date_effet"]) <= fin
    )
    confirmes = {c["rapprochement_vise"] for c in etat_ops["par_type"]["op_rapprochement_confirme"].values()}
    couvrants = [
        r
        for r in etat_ops["par_type"]["op_rapprochement_prepare"].values()
        if r["periode_debut"] <= fin.isoformat() <= r["periode_fin"]
    ]
    elements = [
        item(
            "periode_close",
            "FAIT" if verrou is not None and verrou >= fin else "A_FAIRE",
            "Période close (N4)",
            f"verrou au {verrou.isoformat()}"
            if verrou
            else "aucune période close : la clôture est une décision humaine",
        ),
        item(
            "aucun_brouillon_en_attente",
            "FAIT" if brouillons == 0 else "A_FAIRE",
            "Aucun brouillon d'écriture en attente",
            f"{brouillons} brouillon(s) daté(s) au plus tard le {fin.isoformat()}",
        ),
        item(
            "balance_equilibree",
            "FAIT" if total_d == total_c else "A_FAIRE",
            "Balance de vérification équilibrée",
            f"débits {_txt(total_d)} / crédits {_txt(total_c)}",
        ),
        item(
            "rapprochement_bancaire_confirme",
            "FAIT" if any(r["rapprochement_id"] in confirmes for r in couvrants) else "A_FAIRE",
            "Rapprochement bancaire confirmé à la fin de la période",
            f"{len(couvrants)} rapprochement(s) couvrent la fin ; confirmés : "
            f"{sum(1 for r in couvrants if r['rapprochement_id'] in confirmes)}",
        ),
        item(
            "taxes_rapprochees",
            "A_FAIRE"
            if controle_taxes is None
            else ("FAIT" if controle_taxes.get("verdict") == "CONCORDANT" else "A_VERIFIER"),
            "TPS/TVQ rapprochées des taux versionnés",
            "non exécuté" if controle_taxes is None else f"verdict : {controle_taxes.get('verdict')}",
        ),
        item(
            "pieces_justificatives",
            "FAIT" if pieces_manquantes == 0 else "A_VERIFIER",
            "Pièces justificatives liées",
            f"{pieces_manquantes} écriture(s) à justifier sans pièce liée (voir 07-liste-des-pieces.csv)",
        ),
        item(
            "jugements_et_estimations",
            "FAIT" if jugements else "A_VERIFIER",
            "Jugements et estimations consignés",
            f"{jugements} consigné(s) ; si aucun n'existe vraiment, le dire au CPA",
        ),
        item(
            "corrections_revues",
            "A_VERIFIER" if corrections else "FAIT",
            "Journal des corrections relu",
            f"{corrections} correction(s) à relire (09-journal-des-corrections.csv)",
        ),
        item(
            "ouverture_coherente",
            "A_VERIFIER" if periode_precedente_close is None else ("FAIT" if periode_precedente_close else "A_FAIRE"),
            "Soldes d'ouverture issus d'une période précédente close",
            "la clôture de l'exercice précédent n'est pas établie ici"
            if periode_precedente_close is None
            else ("période précédente close" if periode_precedente_close else "la période précédente n'est pas close"),
        ),
        item(
            "beancount_equilibre",
            "FAIT",
            "Export Beancount cumulatif généré (somme nulle par écriture)",
            "contre-vérification par Beancount réel (processus séparé) : non exécutée ici",
        ),
        item(
            "regles_fiscales_du_depot",
            "A_VERIFIER",
            "Règles fiscales utilisées",
            (base_fiscale or {}).get("approbation", "base fiscale non lue") + " : aucune règle n'est approuvée tant "
            "que deux réviseurs ne l'ont pas relue",
        ),
        item(
            "mission_et_attestation",
            "A_FAIRE",
            "Compilation, examen ou audit et attestation par un CPA",
            "Hors d'OPSYS. La nature de la mission et ce qui peut être remis à un tiers (banque, investisseur, "
            "autorité) sont des questions juridiques et professionnelles qu'OPSYS ne tranche pas.",
        ),
    ]
    return elements


# ----------------------------------------------------------------------------------------------- le dossier
def construire_dossier(
    *,
    debut: Any,
    fin: Any,
    date_reference: Any,
    etat_gl: Mapping[str, Any],
    plan: Mapping[str, Any],
    etat_ops: Mapping[str, Any],
    factures_clients: Sequence[Mapping[str, Any]],
    factures_fournisseurs: Sequence[Mapping[str, Any]],
    controle_taxes: Mapping[str, Any] | None,
    resume_base_fiscale: Mapping[str, Any] | None,
    tetes: Mapping[str, str | None],
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le dossier de la période `debut`..`fin` : `{fichiers: {nom: octets}, manifeste, scelle, liste_de_controle,
    resume}` ou un refus. `tetes` : la tête (empreinte du dernier maillon) de chaque registre lu, que le sceau
    couvre."""
    jour_debut = grand_livre._date(debut)
    jour_fin = grand_livre._date(fin)
    jour_ref = grand_livre._date(date_reference)
    if jour_debut is None or jour_fin is None or jour_debut > jour_fin or jour_ref is None:
        return None, _verdict("REJ-DOSSIER-PERIODE-INVALIDE", "debut, fin et date_reference AAAA-MM-JJ, debut ≤ fin")
    if (jour_fin - jour_debut).days > 400:
        return None, _verdict("REJ-DOSSIER-PERIODE-INVALIDE", "une période de plus de 400 jours n'est pas un dossier")
    refus = grand_livre._refus_anomalies(etat_gl) or operations_registre.refus_anomalies(etat_ops)
    if refus is not None:
        return None, refus
    balance, total_d, total_c = _balance(etat_gl, plan, jour_fin)
    rapprochements, vues_rapprochements = _rapprochements(etat_ops, jour_debut, jour_fin)
    pieces, manquantes = _pieces(etat_gl, etat_ops, jour_fin)
    jugements, nb_jugements = _jugements(etat_ops, jour_debut, jour_fin)
    corrections, nb_corrections = _corrections(etat_gl, etat_ops, factures_fournisseurs, jour_debut, jour_fin)
    clients, fournisseurs = _sous_comptes(factures_clients, factures_fournisseurs)
    veille = jour_debut.toordinal() - 1
    precedente_close = None
    if etat_gl["verrou"] is not None:
        precedente_close = etat_gl["verrou"].toordinal() >= veille
    liste = _liste_de_controle(
        fin=jour_fin,
        etat_gl=etat_gl,
        etat_ops=etat_ops,
        total_d=total_d,
        total_c=total_c,
        pieces_manquantes=manquantes,
        jugements=nb_jugements,
        corrections=nb_corrections,
        controle_taxes=controle_taxes,
        base_fiscale=resume_base_fiscale,
        periode_precedente_close=precedente_close,
    )
    fichiers: dict[str, bytes] = {
        "01-balance-verification.csv": balance,
        "02-soldes-ouverture.csv": _ouverture(etat_gl, plan, jour_debut),
        "03-grand-livre.csv": _grand_livre(etat_gl, plan, jour_debut, jour_fin),
        "04-brouillons-en-attente.csv": _brouillons(etat_gl, jour_fin),
        "05-rapprochements-bancaires.json": rapprochements,
        "06-releves-taxes-preparees.json": _releves_taxes(etat_gl, plan, jour_debut, jour_fin),
        "07-liste-des-pieces.csv": pieces,
        "08-jugements-et-estimations.json": jugements,
        "09-journal-des-corrections.csv": corrections,
        "10-sous-comptes-clients.csv": clients,
        "11-sous-comptes-fournisseurs.csv": fournisseurs,
        "12-grand-livre.beancount": _beancount(etat_gl, plan, jour_fin),
        "13-liste-de-controle.json": _json({"liste_de_controle": liste, "mention": analyse.MENTION_COMPTABLE}),
    }
    resume = {statut: sum(1 for i in liste if i["statut"] == statut) for statut in ("FAIT", "A_FAIRE", "A_VERIFIER")}
    fichiers["00-LISEZ-MOI.txt"] = _lisez_moi(jour_debut, jour_fin, jour_ref, plan, resume, vues_rapprochements).encode(
        "utf-8"
    )
    entrees = [{"nom": nom, "octets": len(fichiers[nom]), "sha256": _sha(fichiers[nom])} for nom in sorted(fichiers)]
    corps_scelle = {
        "version": VERSION,
        "periode": {"debut": jour_debut.isoformat(), "fin": jour_fin.isoformat()},
        "plan_comptable_version": plan["version_effective"],
        "fichiers": entrees,
        "tetes_des_registres": dict(sorted(tetes.items())),
    }
    scelle = encodage.empreinte("m5.dossier_cpa.scelle.v1", corps_scelle)
    manifeste = {
        **corps_scelle,
        "scelle": scelle,
        "date_reference": jour_ref.isoformat(),
        "statut": "BROUILLON_POUR_CPA",
        "mention": analyse.MENTION_COMPTABLE,
        "limites": [
            "Ce dossier n'est ni une compilation, ni un examen, ni un audit, ni une déclaration.",
            "La mission du CPA et l'attestation sont hors d'OPSYS ; la nature de la mission et ce qui "
            "peut être remis à un tiers sont des questions juridiques que M5 ne tranche pas.",
        ],
    }
    fichiers["MANIFESTE.json"] = _json(manifeste)
    return {
        "fichiers": fichiers,
        "manifeste": manifeste,
        "scelle": scelle,
        "liste_de_controle": liste,
        "resume": resume,
    }, None


def _lisez_moi(
    debut: date,
    fin: date,
    ref: date,
    plan: Mapping[str, Any],
    resume: Mapping[str, int],
    rapprochements: Sequence[Mapping[str, Any]],
) -> str:
    return "\n".join(
        [
            f"DOSSIER CPA — du {debut.isoformat()} au {fin.isoformat()} (préparé en date du {ref.isoformat()})",
            "",
            analyse.MENTION_COMPTABLE,
            "",
            "Ce paquet a été PRÉPARÉ par OPSYS-AI (agent Sophie, M5) à partir du grand livre en partie double et des",
            "registres de M5. Il est déterministe : mêmes registres, mêmes fichiers, même sceau (voir MANIFESTE.json).",
            f"Plan comptable : {plan['plan_id']} version {plan['version_effective']}.",
            "",
            "CE QU'IL N'EST PAS : ni une compilation, ni un examen, ni un audit, ni des états financiers vérifiés, "
            "ni une",
            "déclaration de taxes. La nature de la mission d'un CPA (compilation, examen, audit) et ce qui peut être",
            "remis à un tiers (banque, investisseur, autorité) sont des questions juridiques et professionnelles : "
            "OPSYS",
            "ne les tranche pas.",
            "",
            f"Liste de contrôle : {resume['FAIT']} fait, {resume['A_FAIRE']} à faire, {resume['A_VERIFIER']} à "
            f"vérifier "
            "(13-liste-de-controle.json).",
            f"Rapprochements bancaires touchant la période : {len(rapprochements)}.",
            "Relevés TPS/TVQ : préparés depuis le grand livre, sans ligne de formulaire officiel (« non renseigné "
            "— source",
            "officielle requise »).",
            "Les règles fiscales du dépôt ne sont pas approuvées tant que deux réviseurs ne les ont pas relues.",
            "",
            "Fichiers : voir MANIFESTE.json (nom, taille, SHA-256 de chacun).",
            "",
        ]
    )


def verifier_fichiers(manifeste: Mapping[str, Any], contenus: Mapping[str, bytes]) -> dict[str, Any]:
    """Compare des fichiers lus au manifeste : `{"conforme", "alteres", "manquants", "inattendus", "sceau_recalcule"}`.
    Le sceau est recalculé depuis les empreintes RÉELLES des fichiers, pas depuis celles que le manifeste affirme."""
    attendus = {f["nom"]: f for f in manifeste["fichiers"]}
    alteres = sorted(nom for nom, f in attendus.items() if nom in contenus and _sha(contenus[nom]) != f["sha256"])
    manquants = sorted(nom for nom in attendus if nom not in contenus)
    inattendus = sorted(nom for nom in contenus if nom not in attendus and nom != "MANIFESTE.json")
    reel = [
        {"nom": nom, "octets": len(contenus[nom]), "sha256": _sha(contenus[nom])}
        for nom in sorted(attendus)
        if nom in contenus
    ]
    corps = {
        "version": manifeste["version"],
        "periode": manifeste["periode"],
        "plan_comptable_version": manifeste["plan_comptable_version"],
        "fichiers": reel,
        "tetes_des_registres": manifeste["tetes_des_registres"],
    }
    recalcule = encodage.empreinte("m5.dossier_cpa.scelle.v1", corps)
    conforme = not alteres and not manquants and not inattendus and recalcule == manifeste["scelle"]
    return {
        "conforme": conforme,
        "alteres": alteres,
        "manquants": manquants,
        "inattendus": inattendus,
        "sceau_recalcule": recalcule,
        "sceau_manifeste": manifeste["scelle"],
    }
