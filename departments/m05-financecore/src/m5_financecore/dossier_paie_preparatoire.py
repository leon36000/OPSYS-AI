"""Dossier de paie préparatoire QC : contrat des entrées, composition des vrais moteurs, matrice des postes.

Module pur : aucune E/S, aucun SQL, aucune lecture d'heures. Il ne recalcule aucune formule fiscale ;
il appelle `calculer_retenue_federale_qc_preparatoire`, qui recompose RRQ, impôt QC et RQAP/AE, puis
ajoute les postes employeur absents de cette chaîne (`cotisations_employeur_2026`). Rien n'est accepté
d'un appelant comme résultat : seules des *déclarations* (attestations, crédits, cumuls, pièces) entrent.

Grain : employé × employeur × année × période annuelle. Une version ne devient jamais une paie
versée : `mode=PREPARATOIRE`, `qualification_regles=NON_QUALIFIEE_POUR_PAIE`, actions bloquées.
Un total (retenues, net, DAS, coût employeur) n'existe que si TOUS ses postes applicables sont
couverts ; sinon il vaut `None` et la matrice dit exactement ce qui manque.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Any

from . import brut_regulier, cotisations_employeur_2026
from .impot_federal_qc_2026 import calculer_retenue_federale_qc_preparatoire

SCHEMA_ENTREES = "opsys.dossier-paie-entrees/v1"
SCHEMA_VERSION = "opsys.dossier-paie-version/v1"
SCHEMA_CALCUL = "opsys.dossier-paie-calcul/v1"
MODE = "PREPARATOIRE"
QUALIFICATION = "NON_QUALIFIEE_POUR_PAIE"
ANNEE = 2026
PERIODES_ANNUELLES = 26
JOURS_PERIODE = 14
CENT = Decimal("0.01")

_ETATS_CALCUL = ("COMPOSE_PREPARATOIRE", "ADMISSION_REFUSEE", "HORS_COUVERTURE", "COMPOSANTE_REFUSEE", "SOURCE_REFUSEE")

_ID_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MONTANT = re.compile(r"^(?:0|[1-9][0-9]{0,8})\.[0-9]{2}$")
_ID_DOSSIER = re.compile(r"^[a-f0-9]{32}$")
_EMPLOYEUR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:-]{0,63}$")

CHAMPS_PIECES = (
    "td1_federal",
    "tp1015_3_qc",
    "registre_cumuls",
    "calendrier_paie",
    "attestation_pm",
    "attestation_assiettes",
    "attestation_emploi",
    "attestation_residence",
    "attestation_zeros",
)
CHAMPS_ATTESTATIONS = (
    "emploi_continu",
    "resident_qc",
    "assujettissement_qc",
    "paiement_regulier_fixe",
    "aucune_gratification_ni_retroactif",
    "aucun_transfert_province_ou_rpc",
    "aucune_exemption_ni_exoneration",
    "taux_ae_normal",
    "salaire_en_argent",
    "aucune_remuneration_variable",
    "assiettes_egales_au_brut",
    "aucune_autre_remuneration_ni_avantage",
    "pm_12",
)
CHAMPS_CREDITS_FEDERAL = ("TC", "F", "F2", "HD", "F1", "U1", "K3", "LCF", "L")
CHAMPS_CREDITS_FEDERAL_NULS = ("F", "F2", "HD", "F1", "U1", "K3", "LCF", "L")
CHAMPS_CREDITS_QC_MONTANTS = (
    "F",
    "J_annuel",
    "J3",
    "J1_annuel",
    "J2",
    "K1_annuel",
    "K2",
    "E1",
    "E2",
    "Q",
    "Q1",
    "fonds_travailleurs_total_annuel_programme",
    "L",
)
CHAMPS_CREDITS_QC_MARQUEURS = (
    "J_determined_after_period_1",
    "J1_determined_after_period_1",
    "K1_determined_after_period_1",
)
CHAMPS_CUMULS = (
    "salaire_rrq_cumul_avant",
    "rrq_palier1_cumul_avant",
    "rrq_palier2_cumul_avant",
    "rqap_salarie_cumul_avant",
    "rqap_employeur_cumul_avant",
    "ae_salarie_cumul_avant",
    "ae_employeur_cumul_avant",
)
_ORIGINES_CUMUL = ("NUL_PERIODE_1", "DECLARE_HISTORIQUE", "CONFIRME_AUTORITE_HUMAINE", "SIMULE_VERSION_PRECEDENTE")
_REGIMES_CCQ = ("NON_CCQ_DECLARE", "CCQ", "INCONNU")

_CHAMPS_ENTREES = frozenset(
    {
        "schema",
        "employeur_reference",
        "periode",
        "arrondi",
        "classification",
        "attestations",
        "pieces",
        "fictif",
        "credits_federal",
        "credits_qc",
        "cumuls_avant",
        "autres_retenues_employe",
        "autres_couts_employeur",
        "parametres_employeur",
    }
)
_CHAMPS_PERIODE = frozenset(
    {"annee", "periode_annuelle", "debut", "fin", "fuseau", "date_paie", "premiere_date_paie_annee"}
)


def refus(code: str, detail: str) -> dict[str, str]:
    """Verdict local (espace `REJ-DOSSIER-PAIE-*`) : ne dépend pas du module `validation` épinglé par l'admission."""
    return {"code": f"REJ-DOSSIER-PAIE-{code}", "detail": detail}


def canonique(objet: Any) -> str:
    return json.dumps(objet, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def empreinte(objet: Any) -> str:
    return hashlib.sha256(canonique(objet).encode("utf-8")).hexdigest()


def _ctx() -> Context:
    contexte = Context(prec=50, rounding=ROUND_HALF_UP, Emin=-999999, Emax=999999, clamp=0)
    for signal in contexte.traps:
        contexte.traps[signal] = False
    return contexte


def _dec(valeur: str) -> Decimal:
    return Decimal(valeur)


def _fmt(montant: Decimal) -> str:
    return format(montant.quantize(CENT, rounding=ROUND_HALF_UP, context=_ctx()), "f")


def _montant_ok(valeur: object) -> bool:
    return isinstance(valeur, str) and _MONTANT.fullmatch(valeur) is not None


def _date_iso(valeur: object) -> date | None:
    if not isinstance(valeur, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", valeur) is None:
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def _piece_ok(piece: object) -> bool:
    if not isinstance(piece, Mapping) or set(piece) != {"reference", "sha256"}:
        return False
    sha = piece["sha256"]
    return (
        isinstance(piece["reference"], str)
        and _ID_REFERENCE.fullmatch(piece["reference"]) is not None
        and (sha is None or (isinstance(sha, str) and _SHA.fullmatch(sha) is not None))
    )


def valider_entrees(entrees: object) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Structure fermée, types stricts, aucune valeur par défaut; la couverture se juge dans `evaluer_couverture`."""
    if not isinstance(entrees, Mapping) or set(entrees) != _CHAMPS_ENTREES:
        return None, refus("STRUCTURE-INVALIDE", "entrées : jeu de champs exact requis")
    if entrees["schema"] != SCHEMA_ENTREES:
        return None, refus("STRUCTURE-INVALIDE", "schéma d'entrées inconnu")
    if type(entrees["fictif"]) is not bool:
        return None, refus("STRUCTURE-INVALIDE", "fictif : booléen explicite requis")
    emp = entrees["employeur_reference"]
    if not isinstance(emp, str) or _EMPLOYEUR.fullmatch(emp) is None:
        return None, refus("STRUCTURE-INVALIDE", "employeur_reference : étiquette sans donnée personnelle requise")
    periode = entrees["periode"]
    if not isinstance(periode, Mapping) or set(periode) != _CHAMPS_PERIODE:
        return None, refus("PERIODE-INVALIDE", "période : jeu de champs exact requis")
    if type(periode["annee"]) is not int or type(periode["periode_annuelle"]) is not int:
        return None, refus("PERIODE-INVALIDE", "année et période annuelle entières requises")
    for cle in ("debut", "fin", "fuseau", "date_paie", "premiere_date_paie_annee"):
        if not isinstance(periode[cle], str):
            return None, refus("PERIODE-INVALIDE", f"{cle} : texte requis")
    arrondi = entrees["arrondi"]
    if (
        not isinstance(arrondi, Mapping)
        or set(arrondi) != {"politique", "hypothese"}
        or arrondi["politique"] != brut_regulier.POLITIQUE_ARRONDI
        or not isinstance(arrondi["hypothese"], str)
        or not 1 <= len(arrondi["hypothese"].strip()) <= 300
    ):
        return None, refus("STRUCTURE-INVALIDE", "arrondi : politique supportée et hypothèse humaine (1–300) requises")
    classification = entrees["classification"]
    if (
        not isinstance(classification, Mapping)
        or set(classification) != {"regime_ccq"}
        or classification["regime_ccq"] not in _REGIMES_CCQ
    ):
        return None, refus("STRUCTURE-INVALIDE", "classification.regime_ccq : NON_CCQ_DECLARE, CCQ ou INCONNU requis")
    attestations = entrees["attestations"]
    if (
        not isinstance(attestations, Mapping)
        or set(attestations) != set(CHAMPS_ATTESTATIONS)
        or any(type(v) is not bool for v in attestations.values())
    ):
        return None, refus(
            "STRUCTURE-INVALIDE", "attestations : chaque booléen explicite requis, aucune valeur par défaut"
        )
    pieces = entrees["pieces"]
    if not isinstance(pieces, Mapping) or set(pieces) != set(CHAMPS_PIECES) or not all(map(_piece_ok, pieces.values())):
        return None, refus("STRUCTURE-INVALIDE", "pieces : neuf références {reference, sha256|null} requises")
    federal = entrees["credits_federal"]
    if (
        not isinstance(federal, Mapping)
        or set(federal) != set(CHAMPS_CREDITS_FEDERAL)
        or not all(_montant_ok(v) for v in federal.values())
    ):
        return None, refus("STRUCTURE-INVALIDE", "credits_federal : montants CAD au centime, tous explicites")
    qc = entrees["credits_qc"]
    if (
        not isinstance(qc, Mapping)
        or set(qc) != set(CHAMPS_CREDITS_QC_MONTANTS) | set(CHAMPS_CREDITS_QC_MARQUEURS)
        or not all(_montant_ok(qc[c]) for c in CHAMPS_CREDITS_QC_MONTANTS)
        or any(type(qc[c]) is not bool for c in CHAMPS_CREDITS_QC_MARQUEURS)
    ):
        return None, refus(
            "STRUCTURE-INVALIDE", "credits_qc : montants CAD au centime et marqueurs booléens explicites"
        )
    cumuls = entrees["cumuls_avant"]
    if not isinstance(cumuls, Mapping) or set(cumuls) != {
        "origine",
        "valeurs",
        "source_simulee",
        "reference_confirmation",
    }:
        return None, refus(
            "CUMUL-INVALIDE", "cumuls_avant : origine, valeurs, source_simulee, reference_confirmation requis"
        )
    if cumuls["origine"] not in _ORIGINES_CUMUL:
        return None, refus("CUMUL-INVALIDE", "origine de cumul inconnue")
    valeurs = cumuls["valeurs"]
    if (
        not isinstance(valeurs, Mapping)
        or set(valeurs) != set(CHAMPS_CUMULS)
        or not all(_montant_ok(v) for v in valeurs.values())
    ):
        return None, refus("CUMUL-INVALIDE", "cumuls_avant.valeurs : sept montants CAD au centime requis")
    simulee = cumuls["source_simulee"]
    if cumuls["origine"] == "SIMULE_VERSION_PRECEDENTE":
        if (
            not isinstance(simulee, Mapping)
            or set(simulee) != {"dossier_id", "numero_version", "hash_version"}
            or not isinstance(simulee["dossier_id"], str)
            or _ID_DOSSIER.fullmatch(simulee["dossier_id"]) is None
            or type(simulee["numero_version"]) is not int
            or simulee["numero_version"] < 1
            or not isinstance(simulee["hash_version"], str)
            or _SHA.fullmatch(simulee["hash_version"]) is None
        ):
            return None, refus(
                "CUMUL-INVALIDE", "source_simulee : dossier_id, numero_version, hash_version exacts requis"
            )
    elif simulee is not None:
        return None, refus("CUMUL-INVALIDE", "source_simulee interdite hors origine SIMULE_VERSION_PRECEDENTE")
    confirmation = cumuls["reference_confirmation"]
    if cumuls["origine"] == "CONFIRME_AUTORITE_HUMAINE":
        if not isinstance(confirmation, str) or _ID_REFERENCE.fullmatch(confirmation) is None:
            return None, refus("CUMUL-INVALIDE", "confirmation d'autorité humaine : référence de pièce requise")
    elif confirmation is not None:
        return None, refus("CUMUL-INVALIDE", "reference_confirmation interdite hors origine CONFIRME_AUTORITE_HUMAINE")
    for cle in ("autres_retenues_employe", "autres_couts_employeur"):
        bloc = entrees[cle]
        if bloc is None:
            continue
        if (
            not isinstance(bloc, Mapping)
            or set(bloc) != {"montant", "reference"}
            or not _montant_ok(bloc["montant"])
            or not isinstance(bloc["reference"], str)
            or _ID_REFERENCE.fullmatch(bloc["reference"]) is None
        ):
            return None, refus("STRUCTURE-INVALIDE", f"{cle} : null (inconnu) ou {{montant, reference}} requis")
    params = entrees["parametres_employeur"]
    if params is not None:
        ok, verdict = cotisations_employeur_2026.valider_parametres_employeur(params)
        if not ok:
            return None, verdict
    return json.loads(canonique(entrees)), None


def valider_periode(periode: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Périmètre calendaire : 2026, bihebdomadaire de 14 jours, période 1..26 cohérente avec la première paie."""
    if periode["annee"] != ANNEE:
        return None, refus(
            "HORS-COUVERTURE", "seule l'année 2026 est transcrite; aucune reconduction vers une autre année"
        )
    if not 1 <= periode["periode_annuelle"] <= PERIODES_ANNUELLES:
        return None, refus("PERIODE-INVALIDE", "période annuelle entre 1 et 26 requise (27e paie hors couverture)")
    bornes = brut_regulier.valider_periode(periode["debut"], periode["fin"], periode["fuseau"])
    if bornes is None:
        return None, refus("PERIODE-INVALIDE", "dates inclusives ISO ordonnées et fuseau IANA requis")
    if (bornes[1] - bornes[0]).days + 1 != JOURS_PERIODE:
        return None, refus("HORS-COUVERTURE", "la période de travail doit couvrir exactement 14 jours inclusifs")
    paie, premiere = _date_iso(periode["date_paie"]), _date_iso(periode["premiere_date_paie_annee"])
    if paie is None or premiere is None or paie.year != ANNEE or premiere.year != ANNEE:
        return None, refus("PERIODE-INVALIDE", "date de paie et première paie 2026 en ISO requises")
    if paie < bornes[1]:
        return None, refus("PERIODE-INVALIDE", "la date de paie ne peut précéder la fin de la période de travail")
    ecart = (paie - premiere).days
    if ecart < 0 or ecart % JOURS_PERIODE != 0 or ecart // JOURS_PERIODE + 1 != periode["periode_annuelle"]:
        return None, refus(
            "CALENDRIER-INCOHERENT",
            "la période annuelle déclarée ne correspond pas à la date de paie et à la première paie de l'année",
        )
    if premiere + timedelta(days=JOURS_PERIODE * PERIODES_ANNUELLES) <= date(ANNEE, 12, 31):
        return None, refus(
            "HORS-COUVERTURE", "année à 27 paies bihebdomadaires : seule la table à 26 périodes est transcrite"
        )
    return {"debut": bornes[0].isoformat(), "fin": bornes[1].isoformat()}, None


def evaluer_couverture(entrees: Mapping[str, Any]) -> list[dict[str, str]]:
    """Motifs précis de sortie du domaine couvert ; liste vide = le cas relève du domaine régulier transcrit."""
    motifs: list[dict[str, str]] = []
    att = entrees["attestations"]
    libelles = {
        "emploi_continu": "emploi annuel continu non attesté",
        "resident_qc": "résidence au Québec non attestée",
        "assujettissement_qc": "assujettissement QC non attesté",
        "paiement_regulier_fixe": "paiement régulier fixe non attesté (surtemps, primes variables hors couverture)",
        "aucune_gratification_ni_retroactif": "gratification ou rétroactif déclaré",
        "aucun_transfert_province_ou_rpc": "transfert de province ou de régime de pensions déclaré",
        "aucune_exemption_ni_exoneration": "exemption ou exonération déclarée",
        "taux_ae_normal": "taux AE réduit déclaré",
        "salaire_en_argent": "salaire non confirmé en argent (RQAP)",
        "aucune_remuneration_variable": "rémunération variable déclarée",
        "assiettes_egales_au_brut": "assiettes distinctes du brut régulier : non supporté",
        "aucune_autre_remuneration_ni_avantage": "autre rémunération ou avantage imposable : non supporté",
        "pm_12": "PM différent de 12 : non supporté",
    }
    for cle in CHAMPS_ATTESTATIONS:
        if att[cle] is not True:
            motifs.append({"code": f"ATTESTATION-{cle.upper()}", "detail": libelles[cle]})
    regime = entrees["classification"]["regime_ccq"]
    if regime == "CCQ":
        motifs.append(
            {"code": "REGIME-CCQ", "detail": "régime CCQ déclaré : règles de la construction non transcrites"}
        )
    if any(entrees["credits_federal"][c] != "0.00" for c in CHAMPS_CREDITS_FEDERAL_NULS):
        motifs.append(
            {
                "code": "CREDITS-FEDERAL-HORS-SCOPE",
                "detail": "déduction ou crédit fédéral hors TC non nul : non transcrit",
            }
        )
    qc = entrees["credits_qc"]
    if qc["F"] != "0.00" or qc["L"] != "0.00":
        motifs.append(
            {
                "code": "CREDITS-QC-HORS-SCOPE",
                "detail": "F ou L du formulaire QC non nuls : assiette/retenue supplémentaire non supportée",
            }
        )
    return motifs


def _preuve(entrees: Mapping[str, Any], slot: str) -> dict[str, Any]:
    piece = entrees["pieces"][slot]
    sha = (
        piece["sha256"]
        or hashlib.sha256(canonique({"slot": slot, "reference": piece["reference"]}).encode()).hexdigest()
    )
    return {"id": piece["reference"], "sha256": sha, "fictif": entrees["fictif"]}


def provenance_pieces(entrees: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Origine de chaque empreinte : pièce fournie (octets hachés par l'humain) ou empreinte de la seule déclaration."""
    return {
        slot: {
            "reference": entrees["pieces"][slot]["reference"],
            "sha256": _preuve(entrees, slot)["sha256"],
            "origine_empreinte": "PIECE_FOURNIE" if entrees["pieces"][slot]["sha256"] else "DECLARATION_SEULE",
        }
        for slot in CHAMPS_PIECES
    }


def construire_demandes(entrees: Mapping[str, Any], brut_cad: str) -> dict[str, dict[str, Any]]:
    """Traduction déterministe des déclarations vers les quatre demandes des moteurs publics existants."""
    per, att = entrees["periode"], entrees["attestations"]
    contexte = {
        "annee": per["annee"],
        "date_paie": per["date_paie"],
        "juridiction": "QC",
        "frequence": "bihebdomadaire",
        "periode_annuelle": per["periode_annuelle"],
    }
    cum = entrees["cumuls_avant"]["valeurs"]
    qc = entrees["credits_qc"]
    fed = entrees["credits_federal"]
    rrq = {
        **contexte,
        "emploi_continu": att["emploi_continu"],
        "paiement_regulier_fixe": att["paiement_regulier_fixe"],
        "gratif_ou_retroactif": not att["aucune_gratification_ni_retroactif"],
        "transfert_rpc_vers_rrq": not att["aucun_transfert_province_ou_rpc"],
        "exemption_speciale": not att["aucune_exemption_ni_exoneration"],
        "assujettissement_qc": att["assujettissement_qc"],
        "pm": 12 if att["pm_12"] else 0,
        "preuve_pm": _preuve(entrees, "attestation_pm"),
        "salaire_rrq_periode": brut_cad,
        "salaire_rrq_cumul_avant": cum["salaire_rrq_cumul_avant"],
        "rrq_palier1_cumul_avant": cum["rrq_palier1_cumul_avant"],
        "rrq_palier2_cumul_avant": cum["rrq_palier2_cumul_avant"],
        "preuve_assiette": _preuve(entrees, "attestation_assiettes"),
        "preuve_cumuls": _preuve(entrees, "registre_cumuls"),
        "preuve_calendrier": _preuve(entrees, "calendrier_paie"),
    }
    impot_qc = {
        **contexte,
        "paiement_regulier_fixe": att["paiement_regulier_fixe"],
        "gratif_ou_retroactif": not att["aucune_gratification_ni_retroactif"],
        "remuneration_variable": not att["aucune_remuneration_variable"],
        "exonere": not att["aucune_exemption_ni_exoneration"],
        "transfert_province": not att["aucun_transfert_province_ou_rpc"],
        "resident": att["resident_qc"],
        "G": brut_cad,
        "F": qc["F"],
        "D": brut_cad,
        "CSA": "0.00",
        **{c: qc[c] for c in CHAMPS_CREDITS_QC_MONTANTS if c not in {"F"}},
        **{c: qc[c] for c in CHAMPS_CREDITS_QC_MARQUEURS},
    }
    rqap_ae = {
        **contexte,
        "paiement_regulier_fixe": att["paiement_regulier_fixe"],
        "gratif_ou_retroactif": not att["aucune_gratification_ni_retroactif"],
        "transfert_province": not att["aucun_transfert_province_ou_rpc"],
        "taux_ae_reduit": not att["taux_ae_normal"],
        "exemption_speciale": not att["aucune_exemption_ni_exoneration"],
        "assujettissement_qc": att["assujettissement_qc"],
        "salaire_en_argent_confirme": att["salaire_en_argent"],
        "assiette_rqap_periode": brut_cad,
        "rqap_salarie_cumul_avant": cum["rqap_salarie_cumul_avant"],
        "rqap_employeur_cumul_avant": cum["rqap_employeur_cumul_avant"],
        "assiette_ae_periode": brut_cad,
        "ae_salarie_cumul_avant": cum["ae_salarie_cumul_avant"],
        "ae_employeur_cumul_avant": cum["ae_employeur_cumul_avant"],
        "preuve_assiette_rqap": _preuve(entrees, "attestation_assiettes"),
        "preuve_cumul_rqap_salarie": _preuve(entrees, "registre_cumuls"),
        "preuve_cumul_rqap_employeur": _preuve(entrees, "registre_cumuls"),
        "preuve_assiette_ae": _preuve(entrees, "attestation_assiettes"),
        "preuve_cumul_ae_salarie": _preuve(entrees, "registre_cumuls"),
        "preuve_cumul_ae_employeur": _preuve(entrees, "registre_cumuls"),
    }
    federale = {
        **contexte,
        "pm": 12,
        "emploi_annuel_continu": att["emploi_continu"],
        "resident": att["resident_qc"],
        "revenu_brut_emploi": brut_cad,
        **{c: fed[c] for c in CHAMPS_CREDITS_FEDERAL},
        "preuves": {
            "td1": _preuve(entrees, "td1_federal"),
            "emploi_annuel_continu": _preuve(entrees, "attestation_emploi"),
            "assiettes_egales": _preuve(entrees, "attestation_assiettes"),
            "residence": _preuve(entrees, "attestation_residence"),
            "zeros_hors_scope": _preuve(entrees, "attestation_zeros"),
        },
    }
    return {"entree_rrq": rrq, "entree_impot_qc": impot_qc, "entree_rqap_ae": rqap_ae, "demande_federale": federale}


_poste = cotisations_employeur_2026.poste


_ETATS_CONNUS = frozenset({"CALCULE", "DECLARE", "NON_APPLICABLE"})


def _somme(postes: list[dict[str, Any]]) -> Decimal | None:
    if any(p["etat"] not in _ETATS_CONNUS for p in postes):
        return None
    with localcontext(_ctx()):
        total = Decimal(0)
        for poste in postes:
            total += _dec(poste["montant"] or "0.00")
        return total


def _manques(postes: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {f"{p['id']}: {m}" for p in postes if p["etat"] not in _ETATS_CONNUS for m in (p["manque"] or [p["etat"]])}
    )


def _total(valeur: Decimal | None, postes: list[dict[str, Any]], libelle: str) -> dict[str, Any]:
    return {
        "libelle": libelle,
        "etat": "CALCULE" if valeur is not None else "INCONNU",
        "montant": _fmt(valeur) if valeur is not None else None,
        "manques": [] if valeur is not None else _manques(postes),
        "postes": [p["id"] for p in postes],
    }


def matrice_et_totaux(
    entrees: Mapping[str, Any],
    brut_cad: str | None,
    composition: Mapping[str, Any] | None,
    motifs_hors_couverture: list[dict[str, str]],
    contexte_blocage: str | None = None,
) -> dict[str, Any]:
    """Matrice exhaustive des postes du cas régulier + totaux conditionnels à la couverture complète.

    `composition` est la sortie du moteur fédéral (qui a recalculé RRQ/QC/RQAP/AE) ou None si non calculée.
    """
    bloque = composition is None
    raison = contexte_blocage or "composition non exécutée"

    def ligne(ident, lib, porteur, autorite, montant, moteur, source=None, note=None):
        return _poste(
            ident,
            lib,
            porteur,
            autorite,
            "INCONNU" if bloque else "CALCULE",
            montant,
            moteur=moteur,
            manque=[raison] if bloque else None,
            source=source,
            note=note,
        )

    postes_comp = composition["postes_composants"] if composition else {}
    rrq = postes_comp.get("rrq", {})
    rqap_ae = postes_comp.get("rqap_ae", {})
    impot_qc = postes_comp.get("impot_qc", {})
    rrq_total = None
    if composition:
        with localcontext(_ctx()):
            rrq_total = _fmt(_dec(rrq["cotisation_palier1"]) + _dec(rrq["cotisation_palier2"]))
    brut_poste = _poste(
        "brut_regulier",
        "Brut régulier (taux horaire M5 × minutes régulières M4)",
        "employe",
        "Employeur",
        "CALCULE" if brut_cad is not None else "INCONNU",
        brut_cad,
        moteur="brut_regulier",
        manque=[] if brut_cad else [raison],
    )
    employe = [
        ligne(
            "rrq_employe",
            "RRQ — cotisation de l'employé (paliers 1 et 2)",
            "employe",
            "Revenu Québec",
            rrq_total,
            "cotisations_rrq_regulieres",
            {"edition": "TP-1015.F 2026-01", "tables": "TP-1015.TR.26"},
        ),
        ligne(
            "impot_quebec",
            "Impôt du Québec retenu à la source",
            "employe",
            "Revenu Québec",
            impot_qc.get("retenue_qc_preparatoire"),
            "impot_quebec_regulier",
            {"edition": "TP-1015.F 2026-01", "pages": impot_qc.get("source", {}).get("pages")},
        ),
        ligne(
            "rqap_employe",
            "RQAP — cotisation de l'employé",
            "employe",
            "Revenu Québec",
            rqap_ae.get("rqap_salarie"),
            "cotisations_rqap_ae_2026",
            {"edition": "TP-1015.F 2026-01", "pages": "41-42"},
        ),
        ligne(
            "ae_employe",
            "Assurance-emploi — prime de l'employé (taux QC)",
            "employe",
            "Agence du revenu du Canada",
            rqap_ae.get("ae_salarie"),
            "cotisations_rqap_ae_2026",
            {"edition": "T4127 122e/123e", "chapitre": "7"},
        ),
        ligne(
            "impot_federal",
            "Impôt fédéral retenu à la source (T4127, option 1)",
            "employe",
            "Agence du revenu du Canada",
            composition["retenue_impot_federal"] if composition else None,
            "impot_federal_qc_2026",
            {
                "edition": (composition or {}).get("parametres", {}).get("edition"),
                "version": (composition or {}).get("version_bareme"),
            },
        ),
    ]
    autres = entrees["autres_retenues_employe"]
    employe.append(
        _poste(
            "autres_retenues_employe",
            "Autres retenues de l'employé (syndicat, assurance, régime privé…)",
            "employe",
            "Employeur",
            "DECLARE" if autres else "INCONNU",
            autres["montant"] if autres else None,
            moteur="declaration_proprietaire",
            manque=[] if autres else ["montant total des autres retenues non déclaré (0.00 avec pièce si aucune)"],
            source={"reference": autres["reference"]} if autres else None,
        )
    )
    employeur_postes = cotisations_employeur_2026.evaluer_postes_employeur(
        rrq_employe=rrq_total,
        rqap_employeur=rqap_ae.get("rqap_employeur"),
        ae_employeur=rqap_ae.get("ae_employeur"),
        brut_cad=brut_cad,
        cumuls_avant=entrees["cumuls_avant"]["valeurs"],
        parametres_employeur=entrees["parametres_employeur"],
        date_paie=entrees["periode"]["date_paie"],
        composition_disponible=not bloque,
        raison_blocage=raison,
    )
    autres_couts = entrees["autres_couts_employeur"]
    employeur_postes.append(
        _poste(
            "autres_couts_employeur",
            "Autres coûts employeur de la période (avantages, assurance collective, vacances provisionnées)",
            "employeur",
            "Employeur",
            "DECLARE" if autres_couts else "INCONNU",
            autres_couts["montant"] if autres_couts else None,
            moteur="declaration_proprietaire",
            manque=[] if autres_couts else ["coûts employeur hors cotisations non déclarés (0.00 avec pièce si aucun)"],
            source={"reference": autres_couts["reference"]} if autres_couts else None,
        )
    )
    matrice = [brut_poste, *employe, *employeur_postes]
    par_id = {p["id"]: p for p in matrice}

    classification_ok = entrees["classification"]["regime_ccq"] == "NON_CCQ_DECLARE"
    prerequis: list[str] = []
    if not classification_ok:
        prerequis.append(
            "classification CCQ non établie"
            if entrees["classification"]["regime_ccq"] == "INCONNU"
            else "régime CCQ déclaré : hors couverture"
        )
    prerequis += [m["detail"] for m in motifs_hors_couverture]
    if brut_cad is None:
        prerequis.append("brut régulier indisponible")
    couvert = not prerequis

    def sous(ids: list[str]) -> list[dict[str, Any]]:
        return [par_id[i] for i in ids]

    ids_ret = ["rrq_employe", "impot_quebec", "rqap_employe", "ae_employe", "impot_federal", "autres_retenues_employe"]
    retenues = sous(ids_ret)
    somme_retenues = _somme(retenues) if couvert else None
    totaux: dict[str, Any] = {
        "retenues_employe": _total(somme_retenues, retenues, "Retenues totales de l'employé (6 postes)"),
    }
    if not couvert:
        totaux["retenues_employe"]["manques"] = sorted(set(totaux["retenues_employe"]["manques"]) | set(prerequis))
    net = None
    if somme_retenues is not None and brut_cad is not None:
        with localcontext(_ctx()):
            net = _dec(brut_cad) - somme_retenues
        if net < 0:
            net = None  # retenues supérieures au brut : incohérence de base, jamais un net négatif présenté
    totaux["net_preparatoire"] = {
        "libelle": "Net préparatoire (brut − retenues totales de l'employé)",
        "etat": "CALCULE" if net is not None else "INCONNU",
        "montant": _fmt(net) if net is not None else None,
        "manques": []
        if net is not None
        else (totaux["retenues_employe"]["manques"] or ["retenues supérieures au brut : base incohérente"]),
        "postes": ["brut_regulier", *ids_ret],
    }
    ids_das_rq = ["impot_quebec", "rrq_employe", "rrq_employeur", "rqap_employe", "rqap_employeur", "fss"]
    ids_das_arc = ["impot_federal", "ae_employe", "ae_employeur"]
    das_rq, das_arc = sous(ids_das_rq), sous(ids_das_arc)
    s_rq = _somme(das_rq) if couvert else None
    s_arc = _somme(das_arc) if couvert else None
    totaux["das_revenu_quebec"] = _total(s_rq, das_rq, "Remises à Revenu Québec (retenues + cotisations employeur)")
    totaux["das_arc"] = _total(
        s_arc, das_arc, "Remises à l'Agence du revenu du Canada (retenues + cotisations employeur)"
    )
    das = None
    if s_rq is not None and s_arc is not None:
        with localcontext(_ctx()):
            das = s_rq + s_arc
    totaux["das_complete"] = _total(das, das_rq + das_arc, "DAS complète de la période (Revenu Québec + ARC)")
    ids_cout = [
        "brut_regulier",
        "rrq_employeur",
        "rqap_employeur",
        "ae_employeur",
        "fss",
        "fdrcmo",
        "cnesst",
        "normes_travail",
        "autres_couts_employeur",
    ]
    cout_postes = sous(ids_cout)
    cout = _somme(cout_postes) if couvert else None
    totaux["cout_employeur_global"] = _total(cout, cout_postes, "Coût employeur global de la période")
    for cle in ("das_revenu_quebec", "das_arc", "das_complete", "cout_employeur_global"):
        if not couvert:
            totaux[cle]["manques"] = sorted(set(totaux[cle]["manques"]) | set(prerequis))
    return {"matrice": matrice, "totaux": totaux, "prerequis_manquants": prerequis}


def _extraire_composition(composition: Mapping[str, Any]) -> dict[str, Any]:
    """Résultat des moteurs minimisé pour conservation : montants, intermédiaires, sources, empreintes — sans PII."""
    qc = composition["postes_composants"]["impot_qc"]
    return {
        "version_bareme_federal": composition["version_bareme"],
        "hash_parametres_federal": composition["hash_parametres"],
        "methode_credits": composition["methode_credits"],
        "edition_federale": composition["parametres"]["edition"],
        "rrq": dict(composition["postes_composants"]["rrq"]),
        "rqap_ae": dict(composition["postes_composants"]["rqap_ae"]),
        "impot_qc": {
            "retenue": qc["retenue_qc_preparatoire"],
            "intermediaires": dict(qc["intermediaires"]),
            "source": dict(qc["source"]),
            "revenu_imposable_annuel": qc["revenu_imposable_annuel"],
        },
        "impot_federal": {
            "retenue": composition["retenue_impot_federal"],
            "facteurs_exacts": dict(composition["facteurs_exacts"]),
        },
        "sources_composantes": dict(composition["sources_composantes"]),
        "empreinte_sortie_moteurs": empreinte({k: composition[k] for k in composition if k != "preuves"}),
    }


def composer(
    entrees: Mapping[str, Any],
    brut: Mapping[str, Any] | None,
    admission: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compose une version de calcul à partir d'entrées validées, d'un brut M4/M5 et d'une admission SERVEUR.

    Ordre fail-closed : période → couverture → admission documentaire → moteurs. Un refus à une étape
    laisse les postes inconnus et n'appelle jamais l'étape suivante.
    """
    resultat: dict[str, Any] = {
        "schema": SCHEMA_CALCUL,
        "mode": MODE,
        "qualification_regles": QUALIFICATION,
        "actions_financieres_bloquees": True,
        "aucun_versement": True,
        "statut_ccq": "UNKNOWN"
        if entrees["classification"]["regime_ccq"] != "NON_CCQ_DECLARE"
        else "NON_CCQ_DECLARE_NON_VERIFIE",
        "etat": "SOURCE_REFUSEE",
        "refus": None,
        "moteurs": None,
        "motifs_hors_couverture": [],
        "provenance_pieces": provenance_pieces(entrees),
    }
    brut_cad = brut.get("brut_brouillon") if isinstance(brut, Mapping) else None
    if not isinstance(brut_cad, str) or not _montant_ok(brut_cad):
        resultat["refus"] = refus("SOURCE-REFUSEE", "brut régulier M4/M5 absent ou illisible : aucun poste calculé")
        resultat.update(matrice_et_totaux(entrees, None, None, [], "brut régulier M4/M5 indisponible"))
        return resultat
    _, verdict = valider_periode(entrees["periode"])
    if verdict is not None:
        resultat["etat"], resultat["refus"] = "HORS_COUVERTURE", verdict
        resultat.update(matrice_et_totaux(entrees, brut_cad, None, [], verdict["detail"]))
        return resultat
    motifs = evaluer_couverture(entrees)
    resultat["motifs_hors_couverture"] = motifs
    if motifs:
        resultat["etat"] = "HORS_COUVERTURE"
        resultat["refus"] = refus("HORS-COUVERTURE", "; ".join(m["detail"] for m in motifs))
        resultat.update(matrice_et_totaux(entrees, brut_cad, None, motifs, "cas hors du domaine régulier transcrit"))
        return resultat
    if not isinstance(admission, Mapping) or admission.get("admissible") is not True:
        resultat["etat"] = "ADMISSION_REFUSEE"
        motifs_adm = list(admission.get("motifs", [])) if isinstance(admission, Mapping) else ["ADMISSION_ABSENTE"]
        resultat["refus"] = refus(
            "ADMISSION-REFUSEE", "prérequis documentaires non satisfaits : " + ", ".join(motifs_adm)
        )
        resultat.update(matrice_et_totaux(entrees, brut_cad, None, [], "admission documentaire refusée"))
        return resultat
    demandes = construire_demandes(entrees, brut_cad)
    composition, verdict = calculer_retenue_federale_qc_preparatoire(**demandes)
    if verdict is not None or composition is None:
        resultat["etat"] = "COMPOSANTE_REFUSEE"
        resultat["refus"] = refus(
            "COMPOSANTE-REFUSEE", f"moteur public : {verdict['code'] if verdict else 'sortie absente'}"
        )
        resultat["refus"]["moteur"] = verdict
        resultat.update(matrice_et_totaux(entrees, brut_cad, None, [], "composante refusée par un moteur public"))
        return resultat
    resultat["etat"] = "COMPOSE_PREPARATOIRE"
    resultat["moteurs"] = _extraire_composition(composition)
    resultat.update(matrice_et_totaux(entrees, brut_cad, composition, []))
    return resultat


def cumuls_apres(entrees: Mapping[str, Any], calcul: Mapping[str, Any], brut_cad: str) -> dict[str, str] | None:
    """Cumuls HYPOTHÉTIQUES après cette période (jamais un versement) : `None` si la composition n'est pas complète."""
    if calcul.get("etat") != "COMPOSE_PREPARATOIRE" or calcul.get("moteurs") is None:
        return None
    avant, moteurs = entrees["cumuls_avant"]["valeurs"], calcul["moteurs"]
    with localcontext(_ctx()):
        return {
            "salaire_rrq_cumul_avant": _fmt(_dec(avant["salaire_rrq_cumul_avant"]) + _dec(brut_cad)),
            "rrq_palier1_cumul_avant": _fmt(
                _dec(avant["rrq_palier1_cumul_avant"]) + _dec(moteurs["rrq"]["cotisation_palier1"])
            ),
            "rrq_palier2_cumul_avant": _fmt(
                _dec(avant["rrq_palier2_cumul_avant"]) + _dec(moteurs["rrq"]["cotisation_palier2"])
            ),
            "rqap_salarie_cumul_avant": _fmt(
                _dec(avant["rqap_salarie_cumul_avant"]) + _dec(moteurs["rqap_ae"]["rqap_salarie"])
            ),
            "rqap_employeur_cumul_avant": _fmt(
                _dec(avant["rqap_employeur_cumul_avant"]) + _dec(moteurs["rqap_ae"]["rqap_employeur"])
            ),
            "ae_salarie_cumul_avant": _fmt(
                _dec(avant["ae_salarie_cumul_avant"]) + _dec(moteurs["rqap_ae"]["ae_salarie"])
            ),
            "ae_employeur_cumul_avant": _fmt(
                _dec(avant["ae_employeur_cumul_avant"]) + _dec(moteurs["rqap_ae"]["ae_employeur"])
            ),
        }
