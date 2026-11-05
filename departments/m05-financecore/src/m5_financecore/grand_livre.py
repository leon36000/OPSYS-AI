"""Grand livre en partie double de M5 (tranche 1) : écritures, validation, contre-passation, clôture, lectures.

Module pur (ADR-0009, même règle que `facturation.py`) : aucun import d'`opsys`, aucune horloge, aucun accès réseau. Il
reçoit un `registre_cible` déjà construit (duck-typé : `ajouter`, `lire`), qu'`outils.py` adosse au registre durable
DÉDIÉ `grand_livre` (append-only, hash-chaîné : `registre.py`, `opsys.stockage.maillons`). Il n'écrit jamais au
registre des mouvements ni ne le lit : une écriture comptable ne fait bouger aucun argent
(`conformite.verifier_aucun_decaissement` couvre ce module en entier).

Contrat d'une écriture (un maillon `gl_ecriture_proposee`, jamais modifié ensuite) :
- `date_effet` (AAAA-MM-JJ), `libelle`, `piece` (référence TYPÉE : une facture client ou fournisseur de M5, vérifiée
  dans son registre, ou une pièce déclarée — paie préparatoire, relevé, reçu, saisie manuelle — que rien ne vérifie et
  qui le dit), `cle_piece` (idempotence), `lignes` (compte, débit, crédit), `devise` CAD, la version du plan comptable ;
- montants `Decimal` au cent, strictement positifs, jamais un nombre JSON ; chaque ligne est un débit OU un crédit ;
- débits = crédits, sinon `REJ-GL-ECRITURE-DESEQUILIBREE` : rien n'est écrit.

Cycle : une écriture naît BROUILLON (générée depuis un fait M5 ou saisie). Elle ne devient DÉFINITIVE que par un maillon
`gl_ecriture_validee` qu'un HUMAIN fait écrire (N4, la file d'approbation du socle : `outils.py` dit qui, jamais un
argument). Une définitive ne se corrige que par une CONTRE-PASSATION liée (un nouveau brouillon, lignes inversées, à
valider à son tour) ; jamais par modification. Une période close (`gl_periode_cloturee`, mensuelle et cumulative : clore
un mois verrouille tout ce qui le précède) refuse toute écriture datée au plus tard à sa fin, à la proposition comme à
la validation.

Idempotence : une `cle_piece` ne porte qu'une écriture. La même clé avec le même contenu rend l'écriture déjà proposée
(rien n'est écrit) ; avec un autre contenu, `REJ-GL-PIECE-CONFLIT`.

Les lectures (balance de vérification, grand livre d'un compte, rapprochement) ne comptent que les écritures
DÉFINITIVES ; elles disent combien de brouillons attendent, jamais ne les additionnent.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import encodage, plan_comptable, taxes, verdicts_grand_livre

__all__ = [
    "etat_grand_livre",
    "lire_montants_facture",
    "proposer_ecriture",
    "proposer_ecritures_lot",
    "valider_ecriture",
    "valider_ecritures_lot",
    "proposer_contre_passation",
    "clore_periode",
    "propositions_factures_clients",
    "propositions_factures_fournisseurs",
    "balance_verification",
    "grand_livre_compte",
    "rapprocher",
]

_TYPE_PROPOSEE = "gl_ecriture_proposee"
_TYPE_VALIDEE = "gl_ecriture_validee"
_TYPE_CLOTURE = "gl_periode_cloturee"
_BROUILLON = "BROUILLON"
_DEFINITIVE = "DEFINITIVE"
_DEVISE = "CAD"
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_MONTANT_MAX = Decimal("999999999999.99")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# ASCII et `fullmatch` : `$` accepte un « \n » final et `\d` les chiffres Unicode (« ２０２６-０１ »).
_PERIODE = re.compile(r"(\d{4})-(\d{2})", re.ASCII)
_LIBELLE_MAX = 200
_REFERENCE_MAX = 120
_LIGNES_MAX = 50
# Les pièces qu'une écriture peut citer. `True` : OPSYS vérifie que la pièce existe dans un registre de M5 ;
# `False` : la pièce est DÉCLARÉE par l'humain qui saisit (à joindre au dossier), et l'écriture le dit.
_TYPES_PIECE = {
    "facture_client": True,
    "facture_fournisseur": True,
    "paie_preparatoire": False,
    "releve_bancaire": False,
    "recu": False,
    "manuelle": False,
    # Reprise d'historique par les exports QuickBooks Online (`import_quickbooks.py`) : la pièce cite le numéro de
    # transaction QBO et l'empreinte du fichier exporté ; rien dans M5 ne la vérifie (déclarée).
    "import_quickbooks": False,
    # Opérations comptables (`operations_comptables.py`) : la note de crédit et la dépense d'employé naissent d'une
    # opération DU REGISTRE `operations_comptables` (vérifiée, comme une facture) ; leur brouillon d'écriture la cite.
    "note_credit": True,
    "depense_employe": True,
}
_LOT_MAX = 5000
_TAXES_FACTURE = {"tps_federale": "tps_a_percevoir", "tvq_quebec": "tvq_a_percevoir"}
# Les taxes PAYÉES d'une facture fournisseur, vers les comptes de crédits et remboursements sur intrants.
_TAXES_INTRANTS = {"tps_federale": "tps_cti", "tvq_quebec": "tvq_rti"}
# Les états d'une facture fournisseur qui portent une dette (`comptes_a_payer._etats_factures`) ; ANNULEE, plus.
_STATUTS_FOURNISSEUR_VIVANTS = ("SAISIE", "CORRIGEE")


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_grand_livre.construire_verdict(code, detail=detail)


def _texte(valeur: Decimal) -> str:
    return str(valeur.quantize(_CENT, rounding=ROUND_HALF_UP))


def _texte_borne(valeur: Any, maximum: int) -> str | None:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum or "\n" in valeur:
        return None
    return valeur.strip()


def _date(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or not _DATE.fullmatch(valeur):
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def _horodatage_valide(horodatage: Any) -> dict[str, str] | None:
    try:
        instant = datetime.fromisoformat(horodatage) if isinstance(horodatage, str) else None
    except ValueError:
        instant = None
    if instant is None or instant.tzinfo is None:
        return _verdict("REJ-GL-CHAMP-INVALIDE", "horodatage ISO 8601 avec fuseau requis")
    return None


def fin_de_periode(periode: Any) -> date | None:
    """Le dernier jour du mois `AAAA-MM`, ou `None` si la période est mal formée."""
    correspondance = _PERIODE.fullmatch(periode) if isinstance(periode, str) else None
    if correspondance is None:
        return None
    annee, mois = int(correspondance.group(1)), int(correspondance.group(2))
    if not 1 <= mois <= 12 or annee < 1900:
        return None
    return date(annee, mois, calendar.monthrange(annee, mois)[1])


# ---------------------------------------------------------------------------------------------- les montants
def _montant(valeur: Any, champ: str) -> tuple[Decimal | None, dict[str, str] | None]:
    """Un montant au cent, strictement positif, depuis un TEXTE (ou un Decimal lu du registre) ; jamais un float."""
    if isinstance(valeur, bool) or not isinstance(valeur, (str, Decimal)):
        return None, _verdict("REJ-GL-MONTANT-INVALIDE", f"{champ} : texte décimal exigé (jamais un nombre JSON)")
    try:
        montant = Decimal(valeur) if isinstance(valeur, str) else valeur
    except InvalidOperation:
        return None, _verdict("REJ-GL-MONTANT-INVALIDE", f"{champ} : {valeur!r} n'est pas un décimal")
    if not montant.is_finite() or montant <= 0 or montant > _MONTANT_MAX:
        return None, _verdict("REJ-GL-MONTANT-INVALIDE", f"{champ} : strictement positif et fini exigé")
    if montant.as_tuple().exponent < -2:
        return None, _verdict("REJ-GL-MONTANT-INVALIDE", f"{champ} : au cent près (deux décimales au plus)")
    return montant.quantize(_CENT, rounding=ROUND_HALF_UP), None


def normaliser_lignes(
    lignes_brutes: Any, plan: Mapping[str, Any]
) -> tuple[list[dict[str, Any]] | None, dict[str, str] | None]:
    """Les lignes d'une écriture, validées : `[{compte, debit, credit}]` en Decimal au cent (l'un des deux à zéro).
    Refus : moins de deux lignes, ligne mal formée (débit ET crédit, ni l'un ni l'autre), montant invalide, compte
    inconnu ou inactif, ou écriture déséquilibrée (débits ≠ crédits)."""
    if not isinstance(lignes_brutes, (list, tuple)) or len(lignes_brutes) < 2:
        return None, _verdict("REJ-GL-LIGNES-INSUFFISANTES", "une écriture a au moins deux lignes")
    if len(lignes_brutes) > _LIGNES_MAX:
        return None, _verdict("REJ-GL-LIGNE-INVALIDE", f"au plus {_LIGNES_MAX} lignes")
    lignes: list[dict[str, Any]] = []
    for index, brute in enumerate(lignes_brutes):
        if not isinstance(brute, Mapping) or set(brute) != {"compte", "debit", "credit"}:
            return None, _verdict("REJ-GL-LIGNE-INVALIDE", f"ligne {index} : exactement compte, debit, credit")
        debit, credit = brute["debit"], brute["credit"]
        if (debit is None) == (credit is None):
            return None, _verdict(
                "REJ-GL-LIGNE-INVALIDE", f"ligne {index} : un débit OU un crédit (l'autre nul), jamais les deux"
            )
        montant, refus = _montant(debit if debit is not None else credit, f"ligne {index}")
        if refus is not None:
            return None, refus
        refus = plan_comptable.compte_utilisable(plan, brute["compte"])
        if refus is not None:
            return None, refus
        lignes.append({
            "compte": brute["compte"],
            "debit": montant if debit is not None else _ZERO,
            "credit": montant if credit is not None else _ZERO,
        })
    debits = sum((ligne["debit"] for ligne in lignes), _ZERO)
    credits = sum((ligne["credit"] for ligne in lignes), _ZERO)
    if debits != credits:
        return None, _verdict(
            "REJ-GL-ECRITURE-DESEQUILIBREE", f"débits {_texte(debits)} ≠ crédits {_texte(credits)} : écart "
            f"{_texte(abs(debits - credits))}"
        )
    return lignes, None


def _equilibree(lignes: Iterable[Mapping[str, Any]]) -> bool:
    debits = credits = _ZERO
    for ligne in lignes:
        debit, credit = ligne.get("debit"), ligne.get("credit")
        if not isinstance(debit, Decimal) or not isinstance(credit, Decimal):
            return False
        if (debit > 0) == (credit > 0) or debit < 0 or credit < 0:
            return False
        debits, credits = debits + debit, credits + credit
    return debits == credits and debits > 0


# ---------------------------------------------------------------------------------------------- l'état
def _empreinte_contenu(corps: Mapping[str, Any]) -> str:
    return encodage.empreinte("m5.grand_livre.ecriture.v1", {
        cle: corps[cle] for cle in ("cle_piece", "piece", "nature", "date_effet", "libelle", "lignes", "devise",
                                    "contre_passe")
    })


def identifiant_ecriture(cle_piece: str) -> str:
    return "gle-" + encodage.empreinte("m5.grand_livre.cle", cle_piece)[:20]


def etat_grand_livre(maillons: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """L'état du grand livre relu des maillons, dans l'ordre : chaque écriture (BROUILLON ou DEFINITIVE, son numéro et
    qui l'a validée), la date de verrouillage (fin de la dernière période close), les DOUBLONS et les ANOMALIES.

    Le numéro d'une définitive est son rang parmi les validations, recalculé ici (celui écrit au maillon n'est qu'une
    trace). Un DOUBLON (la même écriture proposée deux fois, ou validée deux fois, par deux appels concurrents qui ont
    lu le même état) : le premier maillon fait foi, le suivant est ignoré et compté, la lecture continue. Une ANOMALIE
    (contenu altéré ou déséquilibré, identifiant incohérent, validation d'une écriture inconnue ou d'un autre contenu,
    maillon illisible ou étranger) fait refuser toute lecture : jamais un chiffre faux."""
    ecritures: dict[str, dict[str, Any]] = {}
    ordre: list[str] = []
    clotures: list[dict[str, Any]] = []
    anomalies: list[str] = []
    doublons: list[str] = []
    definitives = 0
    for maillon in maillons:
        type_entree = maillon.get("type_entree") if isinstance(maillon, Mapping) else None
        try:
            if type_entree == _TYPE_PROPOSEE:
                ident = maillon.get("ecriture_id")
                if ident != identifiant_ecriture(maillon.get("cle_piece", "")):
                    anomalies.append(f"écriture {ident!r} d'identifiant incohérent")
                elif (maillon.get("empreinte_contenu") != _empreinte_contenu(maillon)
                      or not _equilibree(maillon["lignes"])):
                    anomalies.append(f"écriture {ident} : contenu altéré ou déséquilibré")
                elif ident in ecritures:
                    doublons.append(f"écriture {ident} proposée de nouveau (le premier maillon fait foi)")
                else:
                    ecritures[ident] = {**maillon, "statut": _BROUILLON, "numero": None, "validation": None,
                                        "contre_passee_par": None}
                    ordre.append(ident)
            elif type_entree == _TYPE_VALIDEE:
                ecriture = ecritures.get(maillon.get("ecriture_id"))
                if ecriture is None or maillon.get("empreinte_contenu") != ecriture["empreinte_contenu"]:
                    anomalies.append(f"validation {maillon.get('ecriture_id')!r} sans brouillon concordant")
                elif ecriture["statut"] != _BROUILLON:
                    doublons.append(f"écriture {ecriture['ecriture_id']} validée de nouveau (la première fait foi)")
                else:
                    definitives += 1
                    ecriture.update(statut=_DEFINITIVE, numero=definitives, validation={
                        "par": maillon["valide_par"], "role": maillon["role"], "voie": maillon["voie"],
                        "horodatage": maillon["horodatage"],
                    })
                    if ecriture["contre_passe"] is not None:
                        originale = ecritures.get(ecriture["contre_passe"])
                        if originale is None:
                            anomalies.append(f"contre-passation {ecriture['ecriture_id']} d'une écriture inconnue")
                        else:
                            originale["contre_passee_par"] = ecriture["ecriture_id"]
            elif type_entree == _TYPE_CLOTURE:
                date.fromisoformat(maillon["fin"])
                clotures.append({"periode": maillon["periode"], "fin": maillon["fin"], "par": maillon["cloture_par"],
                                 "role": maillon["role"], "horodatage": maillon["horodatage"]})
            else:
                anomalies.append(f"maillon de type {type_entree!r} étranger au grand livre")
        except (KeyError, TypeError, ValueError, AttributeError):
            anomalies.append(f"maillon {type_entree!r} illisible")
    verrou = max((date.fromisoformat(c["fin"]) for c in clotures), default=None)
    return {"ecritures": ecritures, "ordre": ordre, "clotures": clotures, "verrou": verrou,
            "anomalies": anomalies, "doublons": doublons, "definitives": definitives}


def _refus_verrou(etat: Mapping[str, Any], jour: date) -> dict[str, str] | None:
    verrou = etat["verrou"]
    if verrou is not None and jour <= verrou:
        return _verdict("REJ-GL-PERIODE-CLOSE", f"{jour.isoformat()} : la période est close jusqu'au "
                                                f"{verrou.isoformat()} inclus")
    return None


def _refus_anomalies(etat: Mapping[str, Any]) -> dict[str, str] | None:
    if etat["anomalies"]:
        return _verdict("REJ-GL-CHAINE-INVALIDE", "; ".join(etat["anomalies"][:3]))
    return None


# ---------------------------------------------------------------------------------------------- écrire
def _retrouver(registre_cible: Any, ligne_id: str) -> dict[str, Any]:
    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return maillon
    raise RuntimeError("maillon du grand livre ajouté introuvable")


def _preparer_proposition(
    etat: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    cle_piece: str,
    piece: Mapping[str, Any],
    nature: str,
    date_effet: Any,
    libelle: Any,
    lignes_brutes: Any,
    contre_passe: str | None = None,
    pieces_connues: Mapping[str, Iterable[str]] | None = None,
) -> tuple[tuple[str, dict[str, Any]] | None, dict[str, str] | None]:
    """Valide une proposition contre l'état lu : `(("deja", écriture existante), None)` pour une redite (même pièce,
    même contenu), `(("nouvelle", corps complet avec ecriture_id et empreinte), None)`, ou `(None, verdict)`. N'écrit
    rien : `proposer_ecriture` et `proposer_ecritures_lot` partagent ces règles, dans cet ordre."""
    if not isinstance(piece, Mapping) or piece.get("type") not in _TYPES_PIECE:
        return None, _verdict("REJ-GL-PIECE-INVALIDE", f"type de pièce attendu parmi {sorted(_TYPES_PIECE)}")
    reference = _texte_borne(piece.get("reference"), _REFERENCE_MAX)
    if reference is None:
        return None, _verdict("REJ-GL-PIECE-INVALIDE", "référence de pièce vide, multiligne ou trop longue")
    verifiable = _TYPES_PIECE[piece["type"]]
    if verifiable and pieces_connues is not None and reference not in set(pieces_connues.get(piece["type"], ())):
        return None, _verdict("REJ-GL-PIECE-INTROUVABLE", f"{piece['type']} {reference!r} absente du registre de M5")
    jour = _date(date_effet)
    if jour is None:
        return None, _verdict("REJ-GL-DATE-INVALIDE", f"date_effet {date_effet!r} : AAAA-MM-JJ exigé")
    texte_libelle = _texte_borne(libelle, _LIBELLE_MAX)
    if texte_libelle is None:
        return None, _verdict("REJ-GL-CHAMP-INVALIDE", f"libellé vide, multiligne ou de plus de {_LIBELLE_MAX} car.")
    lignes, refus = normaliser_lignes(lignes_brutes, plan)
    if refus is not None:
        return None, refus
    corps = {
        "cle_piece": cle_piece,
        "piece": {"type": piece["type"], "reference": reference,
                  "verification": "verifiee" if verifiable else "declaree_non_verifiee"},
        "nature": nature,
        "date_effet": jour.isoformat(),
        "libelle": texte_libelle,
        "lignes": lignes,
        "devise": _DEVISE,
        "contre_passe": contre_passe,
    }
    empreinte = _empreinte_contenu(corps)
    ident = identifiant_ecriture(cle_piece)
    existante = etat["ecritures"].get(ident)
    if existante is not None:
        if existante["empreinte_contenu"] == empreinte:
            return ("deja", existante), None
        return None, _verdict("REJ-GL-PIECE-CONFLIT", f"la pièce {cle_piece!r} porte déjà l'écriture {ident}, "
                                                      "d'un autre contenu : contre-passer ou citer une autre pièce")
    refus = _refus_verrou(etat, jour)
    if refus is not None:
        return None, refus
    return ("nouvelle", {"ecriture_id": ident, **corps, "empreinte_contenu": empreinte}), None


def _entree_proposee(prepare: Mapping[str, Any], plan: Mapping[str, Any], origine: str, horodatage: str) -> dict:
    corps = {cle: valeur for cle, valeur in prepare.items() if cle not in ("ecriture_id", "empreinte_contenu")}
    return {
        "type_entree": _TYPE_PROPOSEE,
        "ecriture_id": prepare["ecriture_id"],
        **corps,
        "plan_comptable_version": plan["version_effective"],
        "origine": origine,
        "empreinte_contenu": prepare["empreinte_contenu"],
        "horodatage": horodatage,
    }


def proposer_ecriture(
    registre_cible: Any,
    plan: Mapping[str, Any],
    *,
    cle_piece: str,
    piece: Mapping[str, Any],
    nature: str,
    date_effet: Any,
    libelle: Any,
    lignes_brutes: Any,
    horodatage: Any,
    origine: str,
    contre_passe: str | None = None,
    pieces_connues: Mapping[str, Iterable[str]] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Écrit un BROUILLON (jamais une définitive) : `({"statut": "proposee"|"deja_proposee", "ecriture": ...}, None)`
    ou `(None, verdict)`. Rien n'est écrit sur un refus, ni sur une redite (même `cle_piece`, même contenu)."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    etat = etat_grand_livre(registre_cible.lire())
    refus = _refus_anomalies(etat)
    if refus is not None:
        return None, refus
    prepare, refus = _preparer_proposition(
        etat, plan, cle_piece=cle_piece, piece=piece, nature=nature, date_effet=date_effet, libelle=libelle,
        lignes_brutes=lignes_brutes, contre_passe=contre_passe, pieces_connues=pieces_connues)
    if refus is not None:
        return None, refus
    genre, contenu = prepare
    if genre == "deja":
        return {"statut": "deja_proposee", "ecriture": vue_ecriture(contenu, plan)}, None
    maillon = _retrouver(registre_cible, registre_cible.ajouter(_entree_proposee(contenu, plan, origine, horodatage)))
    ecriture = {**maillon, "statut": _BROUILLON, "numero": None, "validation": None, "contre_passee_par": None}
    return {"statut": "proposee", "ecriture": vue_ecriture(ecriture, plan)}, None


def proposer_ecritures_lot(
    registre_cible: Any,
    plan: Mapping[str, Any],
    *,
    propositions: list[Mapping[str, Any]],
    horodatage: Any,
    origine: str,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Écrit un LOT de brouillons, tout ou rien : chaque proposition (`cle_piece`, `piece`, `nature`, `date_effet`,
    `libelle`, `lignes_brutes`) passe exactement les règles de `proposer_ecriture`, contre l'état lu UNE fois ; au
    premier refus, rien n'est écrit et le verdict dit quelle pièce (`cle_piece`). Une redite est rendue « déjà
    proposée » sans rien écrire ; deux propositions du lot sur la même pièce sont refusées (`REJ-GL-PIECE-CONFLIT`).
    Rend `{"proposees": [écritures], "deja_proposees": [écritures]}` (vues). Au plus `_LOT_MAX` propositions."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    if not isinstance(propositions, list) or len(propositions) > _LOT_MAX:
        return None, _verdict("REJ-GL-LIMITE-INVALIDE", f"un lot est une liste d'au plus {_LOT_MAX} propositions")
    etat = etat_grand_livre(registre_cible.lire())
    refus = _refus_anomalies(etat)
    if refus is not None:
        return None, refus
    nouvelles: list[dict[str, Any]] = []
    deja: list[dict[str, Any]] = []
    vues: set[str] = set()
    for proposition in propositions:
        cle = proposition.get("cle_piece") if isinstance(proposition, Mapping) else None
        if not isinstance(cle, str) or not cle:
            return None, _verdict("REJ-GL-PIECE-INVALIDE", "proposition sans cle_piece")
        if cle in vues:
            return None, _verdict("REJ-GL-PIECE-CONFLIT", f"la pièce {cle!r} figure deux fois dans le lot")
        vues.add(cle)
        prepare, refus = _preparer_proposition(
            etat, plan, cle_piece=cle, piece=proposition.get("piece"), nature=proposition.get("nature"),
            date_effet=proposition.get("date_effet"), libelle=proposition.get("libelle"),
            lignes_brutes=proposition.get("lignes_brutes"))
        if refus is not None:
            return None, {**refus, "detail": f"{cle} : {refus['detail']}"}
        genre, contenu = prepare
        (deja if genre == "deja" else nouvelles).append(contenu)
    ecrites = []
    for contenu in nouvelles:
        entree = _entree_proposee(contenu, plan, origine, horodatage)
        registre_cible.ajouter(entree)
        ecrites.append({**entree, "statut": _BROUILLON, "numero": None, "validation": None,
                        "contre_passee_par": None})
    return {"proposees": [vue_ecriture(e, plan) for e in ecrites],
            "deja_proposees": [vue_ecriture(e, plan) for e in deja]}, None


def valider_ecriture(
    registre_cible: Any,
    plan: Mapping[str, Any],
    *,
    ecriture_id: Any,
    humain: Mapping[str, str],
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """BROUILLON -> DEFINITIVE, par un maillon `gl_ecriture_validee` qui porte l'humain (`humain` : `par`, `role`,
    `voie`, établis par l'appelant depuis le socle, jamais depuis un argument). Revérifie tout au moment de valider :
    équilibre, comptes utilisables au plan COURANT, période ouverte, original encore définitif et non contre-passé."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    etat = etat_grand_livre(registre_cible.lire())
    refus = _refus_anomalies(etat)
    if refus is not None:
        return None, refus
    ecriture, refus = _ecriture_validable(etat, plan, ecriture_id)
    if refus is not None:
        return None, refus
    numero = etat["definitives"] + 1
    registre_cible.ajouter(_entree_validee(ecriture, numero, humain, horodatage))
    definitive = {**ecriture, "statut": _DEFINITIVE, "numero": numero, "validation": {
        "par": humain["par"], "role": humain["role"], "voie": humain["voie"], "horodatage": horodatage}}
    return {"statut": "validee", "ecriture": vue_ecriture(definitive, plan)}, None


def _ecriture_validable(
    etat: Mapping[str, Any], plan: Mapping[str, Any], ecriture_id: Any
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """L'écriture si elle peut devenir définitive maintenant : brouillon connu, période ouverte, comptes utilisables au
    plan COURANT, original encore définitif et non contre-passé ; sinon le refus nommé."""
    ecriture = etat["ecritures"].get(ecriture_id) if isinstance(ecriture_id, str) else None
    if ecriture is None:
        return None, _verdict("REJ-GL-ECRITURE-INTROUVABLE", f"écriture {ecriture_id!r} inconnue")
    if ecriture["statut"] != _BROUILLON:
        return None, _verdict("REJ-GL-ECRITURE-DEJA-VALIDEE",
                              f"écriture {ecriture_id} déjà définitive (n° {ecriture['numero']})")
    refus = _refus_verrou(etat, date.fromisoformat(ecriture["date_effet"]))
    if refus is not None:
        return None, refus
    for ligne in ecriture["lignes"]:
        refus = plan_comptable.compte_utilisable(plan, ligne["compte"])
        if refus is not None:
            return None, refus
    if ecriture["contre_passe"] is not None:
        originale = etat["ecritures"].get(ecriture["contre_passe"])
        if originale is None or originale["statut"] != _DEFINITIVE or originale["contre_passee_par"] is not None:
            return None, _verdict("REJ-GL-DEJA-CONTRE-PASSEE",
                                  f"l'écriture {ecriture['contre_passe']} n'est plus contre-passable")
    return ecriture, None


def _entree_validee(ecriture: Mapping[str, Any], numero: int, humain: Mapping[str, str], horodatage: str) -> dict:
    return {
        "type_entree": _TYPE_VALIDEE,
        "ecriture_id": ecriture["ecriture_id"],
        "empreinte_contenu": ecriture["empreinte_contenu"],
        "numero": numero,
        "valide_par": humain["par"],
        "role": humain["role"],
        "voie": humain["voie"],
        "horodatage": horodatage,
    }


def valider_ecritures_lot(
    registre_cible: Any,
    plan: Mapping[str, Any],
    *,
    ecriture_ids: list[str],
    humain: Mapping[str, str],
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Rend DÉFINITIVES, tout ou rien, les brouillons `ecriture_ids` (une seule décision humaine, établie par
    l'appelant comme pour `valider_ecriture`) : chacun passe les règles de `valider_ecriture` contre l'état lu UNE
    fois ; au premier refus, rien n'est écrit. Les numéros suivent l'ordre (date d'effet, rang de proposition). Ne
    contient pas de contre-passation (une contre-passation se valide seule, après lecture de l'original)."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    if (not isinstance(ecriture_ids, list) or not ecriture_ids or len(ecriture_ids) > _LOT_MAX
            or len(set(ecriture_ids)) != len(ecriture_ids)):
        return None, _verdict("REJ-GL-LIMITE-INVALIDE", f"de 1 à {_LOT_MAX} écritures distinctes par lot")
    etat = etat_grand_livre(registre_cible.lire())
    refus = _refus_anomalies(etat)
    if refus is not None:
        return None, refus
    retenues = []
    for ident in ecriture_ids:
        ecriture, refus = _ecriture_validable(etat, plan, ident)
        if refus is not None:
            return None, {**refus, "detail": f"{ident} : {refus['detail']}"}
        if ecriture["contre_passe"] is not None:
            return None, _verdict("REJ-GL-CONTRE-PASSATION-INVALIDE",
                                  f"{ident} : une contre-passation se valide seule, jamais en lot")
        retenues.append(ecriture)
    rang = {ident: index for index, ident in enumerate(etat["ordre"])}
    retenues.sort(key=lambda e: (e["date_effet"], rang[e["ecriture_id"]]))
    numero = etat["definitives"]
    for ecriture in retenues:
        numero += 1
        registre_cible.ajouter(_entree_validee(ecriture, numero, humain, horodatage))
    return {"statut": "validees", "validees": len(retenues), "premier_numero": etat["definitives"] + 1,
            "dernier_numero": numero}, None


def proposer_contre_passation(
    registre_cible: Any,
    plan: Mapping[str, Any],
    *,
    ecriture_id: Any,
    date_effet: Any,
    motif: Any,
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le BROUILLON qui annule une écriture DÉFINITIVE : mêmes comptes, débits et crédits inversés, lié à l'original
    (`contre_passe`). La correction d'une définitive passe par là, jamais par une modification. Refus : écriture
    inconnue, encore brouillon, déjà contre-passée, elle-même une contre-passation, date antérieure à l'original."""
    etat = etat_grand_livre(registre_cible.lire())
    refus = _refus_anomalies(etat)
    if refus is not None:
        return None, refus
    originale = etat["ecritures"].get(ecriture_id) if isinstance(ecriture_id, str) else None
    if originale is None:
        return None, _verdict("REJ-GL-ECRITURE-INTROUVABLE", f"écriture {ecriture_id!r} inconnue")
    if originale["statut"] != _DEFINITIVE:
        return None, _verdict("REJ-GL-ECRITURE-NON-DEFINITIVE",
                              "un brouillon ne se contre-passe pas : il n'est simplement pas validé")
    if originale["contre_passee_par"] is not None:
        return None, _verdict("REJ-GL-DEJA-CONTRE-PASSEE",
                              f"déjà contre-passée par {originale['contre_passee_par']}")
    if originale["contre_passe"] is not None:
        return None, _verdict("REJ-GL-CONTRE-PASSATION-INVALIDE",
                              "une contre-passation ne se contre-passe pas : proposer une nouvelle écriture")
    texte_motif = _texte_borne(motif, 300)
    if texte_motif is None:
        return None, _verdict("REJ-GL-MOTIF-REQUIS", "motif obligatoire, une ligne de 300 caractères au plus")
    jour = _date(date_effet)
    if jour is None:
        return None, _verdict("REJ-GL-DATE-INVALIDE", f"date_effet {date_effet!r} : AAAA-MM-JJ exigé")
    if jour < date.fromisoformat(originale["date_effet"]):
        return None, _verdict("REJ-GL-DATE-INVALIDE", "une contre-passation ne précède pas l'écriture d'origine")
    lignes = [{"compte": ligne["compte"],
               "debit": _texte(ligne["credit"]) if ligne["credit"] > 0 else None,
               "credit": _texte(ligne["debit"]) if ligne["debit"] > 0 else None}
              for ligne in originale["lignes"]]
    return proposer_ecriture(
        registre_cible, plan,
        # La clé porte la date et l'empreinte du motif : le même geste est idempotent, mais un brouillon mal daté ou mal
        # motivé (jamais supprimable, registre append-only) se REPREND par un autre brouillon au lieu d'un conflit sans
        # issue. Un seul des deux peut devenir définitif (`REJ-GL-DEJA-CONTRE-PASSEE` à la validation du second).
        cle_piece=f"contre_passation:{originale['ecriture_id']}:{jour.isoformat()}:{encodage.empreinte(texte_motif)[:12]}",
        piece=originale["piece"],
        nature="contre_passation",
        date_effet=date_effet,
        libelle=f"Contre-passation n° {originale['numero']} : {texte_motif}"[:_LIBELLE_MAX],
        lignes_brutes=lignes,
        horodatage=horodatage,
        origine="contre_passation",
        contre_passe=originale["ecriture_id"],
    )


def clore_periode(
    registre_cible: Any,
    *,
    periode: Any,
    humain: Mapping[str, str],
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Clôt le mois `AAAA-MM` (et, cumulativement, tout ce qui le précède) : plus aucune écriture datée au plus tard à
    sa fin ne peut être proposée ni validée. Rend les totaux de la balance à la clôture et les brouillons laissés en
    plan (désormais non validables : à contre-passer dans une période ouverte s'ils devaient compter)."""
    refus = _horodatage_valide(horodatage)
    if refus is not None:
        return None, refus
    fin = fin_de_periode(periode)
    if fin is None:
        return None, _verdict("REJ-GL-PERIODE-INVALIDE", f"période {periode!r} : AAAA-MM exigé")
    etat = etat_grand_livre(registre_cible.lire())
    refus = _refus_anomalies(etat)
    if refus is not None:
        return None, refus
    if etat["verrou"] is not None and fin <= etat["verrou"]:
        return None, _verdict("REJ-GL-PERIODE-DEJA-CLOSE",
                              f"{periode} déjà close (verrou au {etat['verrou'].isoformat()})")
    debits = credits = _ZERO
    for ecriture in _definitives_jusqua(etat, fin):
        for ligne in ecriture["lignes"]:
            debits, credits = debits + ligne["debit"], credits + ligne["credit"]
    if debits != credits:
        return None, _verdict("REJ-GL-ECRITURE-DESEQUILIBREE", "la balance à clôturer n'est pas équilibrée")
    en_plan = [e["ecriture_id"] for e in etat["ecritures"].values()
               if e["statut"] == _BROUILLON and date.fromisoformat(e["date_effet"]) <= fin]
    registre_cible.ajouter({
        "type_entree": _TYPE_CLOTURE,
        "periode": periode,
        "fin": fin.isoformat(),
        "cloture_par": humain["par"],
        "role": humain["role"],
        "voie": humain["voie"],
        "total_debits": debits,
        "total_credits": credits,
        "horodatage": horodatage,
    })
    return {"statut": "close", "periode": periode, "verrou": fin.isoformat(), "total_debits": _texte(debits),
            "total_credits": _texte(credits), "brouillons_laisses_en_plan": en_plan[:20],
            "brouillons_laisses_en_plan_reste": max(0, len(en_plan) - 20)}, None


# ---------------------------------------------------------------------------------------------- générer
def _jour_iso(horodatage: Any) -> str | None:
    try:
        return datetime.fromisoformat(horodatage).date().isoformat() if isinstance(horodatage, str) else None
    except ValueError:
        return None


def _montants_lus(
    facture: Mapping[str, Any], table: Mapping[str, str]
) -> tuple[Decimal, Decimal, dict[str, Decimal]] | None:
    """`(avant taxes, après taxes, {rôle: montant de taxe})` RELUS de la pièce, ou `None` dès que quelque chose est
    illisible ou incohérent : montant absent ou non `Decimal`, taxe hors `table` ou répétée, taxe négative, avant +
    taxes ≠ après, somme des taxes ≠ total des taxes, avant ou après non strictement positif. Rien n'est recalculé :
    la pièce dit ses montants, ce code vérifie qu'ils se tiennent."""
    avant, apres, total = (facture.get(c) for c in ("montant_avant_taxes", "montant_apres_taxes", "total_taxes"))
    detail_taxes = facture.get("taxes")
    if not (all(isinstance(v, Decimal) and v.is_finite() for v in (avant, apres, total))
            and isinstance(detail_taxes, (list, tuple))):
        return None
    if any(v.as_tuple().exponent < -2 for v in (avant, apres, total)):
        return None
    montants: dict[str, Decimal] = {}
    for taxe in detail_taxes:
        role = table.get(taxe.get("id")) if isinstance(taxe, Mapping) else None
        montant = taxe.get("montant") if role is not None else None
        if (role is None or not isinstance(montant, Decimal) or not montant.is_finite() or montant < 0
                or montant.as_tuple().exponent < -2 or role in montants):
            return None
        montants[role] = montant
    if avant + total != apres or sum(montants.values(), _ZERO) != total or apres <= 0 or avant <= 0:
        return None
    return avant, apres, montants


def lire_montants_facture(facture: Mapping[str, Any], genre: str) -> tuple[Decimal, Decimal, dict[str, Decimal]] | None:
    """Les montants RELUS d'une facture cliente (`genre` « client ») ou fournisseur (« fournisseur ») : `(avant taxes,
    après taxes, {rôle du plan: taxe})` ou `None` si la pièce est illisible ou incohérente. Rien n'est recalculé."""
    table = _TAXES_FACTURE if genre == "client" else _TAXES_INTRANTS
    return _montants_lus(facture, table)


def propositions_factures_clients(
    factures: Iterable[Mapping[str, Any]], plan: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Les brouillons que les faits LES PLUS SÛRS de M5 justifient, sans rien deviner :
    - facture ÉMISE (statut ENVOYEE ou PAYEE, `date_envoi`) : débit comptes clients du total après taxes ; crédit
      produits du total avant taxes ; crédit TPS et TVQ à percevoir des montants de taxe FACTURÉS ;
    - paiement REÇU (statut PAYEE, `date_paiement` ; le code de facturation a déjà exigé un dépôt égal au montant dû) :
      débit banque, crédit comptes clients du total après taxes.
    Rend `(propositions, ignorees)` : une facture illisible (date, montant ou taxe absent ou incohérent, taxe autre que
    TPS/TVQ) est IGNORÉE avec son code, jamais complétée."""
    roles = plan["roles"]
    propositions: list[dict[str, Any]] = []
    ignorees: list[dict[str, str]] = []
    for facture in factures:
        ident = facture.get("facture_id")
        statut = facture.get("statut")
        if statut not in ("ENVOYEE", "PAYEE"):
            continue
        lus = _montants_lus(facture, _TAXES_FACTURE)
        if lus is None:
            ignorees.append({"facture_id": str(ident), "code": "REJ-GL-SOURCE-ILLISIBLE",
                             "detail": "montants ou taxes de la facture illisibles ou incohérents"})
            continue
        avant, apres, montants_taxe = lus
        jour_envoi = _jour_iso(facture.get("date_envoi"))
        if jour_envoi is None:
            ignorees.append({"facture_id": str(ident), "code": "REJ-GL-SOURCE-ILLISIBLE",
                             "detail": "facture émise sans date_envoi lisible"})
            continue
        lignes = [{"compte": roles["comptes_clients"], "debit": _texte(apres), "credit": None},
                  {"compte": roles["produits_services"], "debit": None, "credit": _texte(avant)}]
        lignes += [{"compte": roles[role], "debit": None, "credit": _texte(montant)}
                   for role, montant in sorted(montants_taxe.items()) if montant > 0]
        propositions.append({
            "cle_piece": f"auto:facture_client:{ident}:emission",
            "piece": {"type": "facture_client", "reference": ident},
            "nature": "facture_emise",
            "date_effet": jour_envoi,
            "libelle": f"Facture client {ident} émise",
            "lignes_brutes": lignes,
        })
        if statut == "PAYEE":
            jour_paiement = _jour_iso(facture.get("date_paiement"))
            if jour_paiement is None:
                ignorees.append({"facture_id": str(ident), "code": "REJ-GL-SOURCE-ILLISIBLE",
                                 "detail": "facture payée sans date_paiement lisible"})
                continue
            propositions.append({
                "cle_piece": f"auto:facture_client:{ident}:paiement",
                "piece": {"type": "facture_client", "reference": ident},
                "nature": "paiement_recu",
                "date_effet": jour_paiement,
                "libelle": f"Paiement reçu de la facture client {ident}",
                "lignes_brutes": [
                    {"compte": roles["banque"], "debit": _texte(apres), "credit": None},
                    {"compte": roles["comptes_clients"], "debit": None, "credit": _texte(apres)},
                ],
            })
    propositions.sort(key=lambda p: (p["date_effet"], p["cle_piece"]))
    return propositions, ignorees


def _une_ligne(valeur: Any) -> str:
    return " ".join(str(valeur).split())


def propositions_factures_fournisseurs(
    factures: Iterable[Mapping[str, Any]], plan: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Les brouillons des factures fournisseurs SAISIES (état courant des comptes à payer : SAISIE ou CORRIGEE ; une
    ANNULEE n'en donne aucun), datés de la date de la facture :
    débit du compte de charge (`plan_comptable.compte_de_charge` : sa catégorie, ou `factures_sur_po`) du montant
    avant taxes ; débit CTI de la TPS payée et RTI de la TVQ payée ; crédit comptes fournisseurs du total après taxes.
    Les montants sont RELUS de la pièce (`_montants_lus`), jamais recalculés. Le registre des comptes à payer ne porte
    aucun paiement (payer un fournisseur est N5, hors de M5) : aucun brouillon de paiement n'en sort.
    Rend `(propositions, ignorees)` : une facture aux taxes illisibles ou sans date lisible est ignorée
    (`REJ-GL-SOURCE-ILLISIBLE`), une facture sans compte de charge déclaré aussi (`REJ-GL-CATEGORIE-SANS-COMPTE`) ;
    jamais complétée."""
    roles = plan["roles"]
    propositions: list[dict[str, Any]] = []
    ignorees: list[dict[str, str]] = []
    for facture in factures:
        if facture.get("statut") not in _STATUTS_FOURNISSEUR_VIVANTS:
            continue
        ident = facture.get("facture_fournisseur_id")
        lus = _montants_lus(facture, _TAXES_INTRANTS)
        if lus is None:
            ignorees.append({"facture_fournisseur_id": str(ident), "code": "REJ-GL-SOURCE-ILLISIBLE",
                             "detail": "montants ou taxes payées de la facture fournisseur illisibles ou incohérents"})
            continue
        jour = _date(facture.get("date_facture"))
        if jour is None:
            ignorees.append({"facture_fournisseur_id": str(ident), "code": "REJ-GL-SOURCE-ILLISIBLE",
                             "detail": "facture fournisseur sans date_facture lisible"})
            continue
        compte, refus = plan_comptable.compte_de_charge(
            plan, po_id=facture.get("po_id"), categorie=facture.get("categorie_depense"))
        if refus is not None:
            ignorees.append({"facture_fournisseur_id": str(ident), **refus})
            continue
        avant, apres, montants_taxe = lus
        lignes = [{"compte": compte, "debit": _texte(avant), "credit": None}]
        lignes += [{"compte": roles[role], "debit": _texte(montant), "credit": None}
                   for role, montant in sorted(montants_taxe.items()) if montant > 0]
        lignes.append({"compte": roles["comptes_fournisseurs"], "debit": None, "credit": _texte(apres)})
        libelle = (f"Facture fournisseur {_une_ligne(facture.get('numero_facture'))} "
                   f"({_une_ligne(facture.get('fournisseur_id'))}) saisie")
        propositions.append({
            "cle_piece": f"auto:facture_fournisseur:{ident}:saisie",
            "piece": {"type": "facture_fournisseur", "reference": ident},
            "nature": "facture_fournisseur_saisie",
            "date_effet": jour.isoformat(),
            "libelle": libelle[:_LIBELLE_MAX],
            "lignes_brutes": lignes,
        })
    propositions.sort(key=lambda p: (p["date_effet"], p["cle_piece"]))
    return propositions, ignorees


# ---------------------------------------------------------------------------------------------- lire
def vue_ecriture(ecriture: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    """Une écriture telle qu'une sortie la montre : montants en texte décimal, comptes nommés."""
    comptes = plan["comptes"]
    return {
        "ecriture_id": ecriture["ecriture_id"],
        "statut": ecriture["statut"],
        "numero": ecriture["numero"],
        "date_effet": ecriture["date_effet"],
        "libelle": ecriture["libelle"],
        "piece": ecriture["piece"],
        "nature": ecriture["nature"],
        "contre_passe": ecriture["contre_passe"],
        "contre_passee_par": ecriture.get("contre_passee_par"),
        "plan_comptable_version": ecriture["plan_comptable_version"],
        "lignes": [{"compte": ligne["compte"],
                    "nom": comptes.get(ligne["compte"], {}).get("nom", "(absent du plan courant)"),
                    "debit": _texte(ligne["debit"]) if ligne["debit"] > 0 else None,
                    "credit": _texte(ligne["credit"]) if ligne["credit"] > 0 else None}
                   for ligne in ecriture["lignes"]],
        "validation": ecriture["validation"],
    }


def _definitives_jusqua(etat: Mapping[str, Any], jour: date | None, debut: date | None = None) -> list[dict]:
    retenues = []
    for ident in etat["ordre"]:
        ecriture = etat["ecritures"][ident]
        if ecriture["statut"] != _DEFINITIVE:
            continue
        jour_effet = date.fromisoformat(ecriture["date_effet"])
        if (jour is None or jour_effet <= jour) and (debut is None or jour_effet >= debut):
            retenues.append(ecriture)
    retenues.sort(key=lambda e: (e["date_effet"], e["numero"]))
    return retenues


def _brouillons(etat: Mapping[str, Any], jour: date | None) -> int:
    return sum(1 for e in etat["ecritures"].values()
               if e["statut"] == _BROUILLON and (jour is None or date.fromisoformat(e["date_effet"]) <= jour))


def balance_verification(
    etat: Mapping[str, Any], plan: Mapping[str, Any], au: Any, *, depart: int = 0, limite: int = 25
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """La balance de vérification au `au` (inclus) : pour chaque compte mouvementé, total des débits, des crédits et
    solde (côté débiteur ou créditeur), et la PREUVE totale débits = crédits. Écritures DÉFINITIVES seulement ;
    `brouillons_non_comptabilises` dit combien attendent une validation. Comptes paginés (`depart`, `limite`) ; les
    totaux portent toujours sur tous les comptes."""
    refus = _refus_anomalies(etat)
    if refus is not None:
        return None, refus
    jour = _date(au)
    if jour is None:
        return None, _verdict("REJ-GL-DATE-INVALIDE", f"au {au!r} : AAAA-MM-JJ exigé")
    cumuls: dict[str, list[Decimal]] = {}
    ecritures = _definitives_jusqua(etat, jour)
    for ecriture in ecritures:
        for ligne in ecriture["lignes"]:
            cumul = cumuls.setdefault(ligne["compte"], [_ZERO, _ZERO])
            cumul[0] += ligne["debit"]
            cumul[1] += ligne["credit"]
    total_debits = sum((c[0] for c in cumuls.values()), _ZERO)
    total_credits = sum((c[1] for c in cumuls.values()), _ZERO)
    lignes = []
    for numero in sorted(cumuls):
        debit, credit = cumuls[numero]
        compte = plan["comptes"].get(numero)
        solde = debit - credit
        lignes.append({
            "compte": numero,
            "nom": compte["nom"] if compte else "(absent du plan courant)",
            "type": compte["type"] if compte else None,
            "actif": compte["actif"] if compte else False,
            "total_debits": _texte(debit),
            "total_credits": _texte(credit),
            "solde": _texte(abs(solde)),
            "cote": "debiteur" if solde > 0 else ("crediteur" if solde < 0 else "nul"),
            "sens_normal": plan_comptable.sens_normal(compte["type"]) if compte else None,
        })
    page = lignes[depart:depart + limite]
    return {
        "au": jour.isoformat(),
        "devise": _DEVISE,
        "plan_comptable_version": plan["version_effective"],
        "ecritures_definitives": len(ecritures),
        "brouillons_non_comptabilises": _brouillons(etat, jour),
        "doublons_ignores": len(etat["doublons"]),
        "total_debits": _texte(total_debits),
        "total_credits": _texte(total_credits),
        "equilibree": total_debits == total_credits,
        "comptes": page,
        "comptes_total": len(lignes),
        "prochain_depart": depart + limite if depart + limite < len(lignes) else None,
    }, None


def grand_livre_compte(
    etat: Mapping[str, Any], plan: Mapping[str, Any], compte: Any, *, debut: Any, fin: Any,
    depart: int = 0, limite: int = 20,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le grand livre d'un compte entre `debut` et `fin` (inclus) : solde d'ouverture (tout ce qui précède `debut`),
    chaque ligne définitive avec son écriture et le solde courant, solde de clôture. Le solde est signé du côté
    débiteur (positif : débiteur). Lignes paginées ; les soldes portent toujours sur toute la période."""
    refus = _refus_anomalies(etat)
    if refus is not None:
        return None, refus
    if not isinstance(compte, str) or compte not in plan["comptes"]:
        return None, _verdict("REJ-GL-COMPTE-INCONNU", f"compte {compte!r} absent du plan comptable")
    jour_debut, jour_fin = _date(debut), _date(fin)
    if jour_debut is None or jour_fin is None or jour_debut > jour_fin:
        return None, _verdict("REJ-GL-DATE-INVALIDE", "debut et fin AAAA-MM-JJ, debut au plus tard à fin")
    ouverture = _ZERO
    mouvements = []
    for ecriture in _definitives_jusqua(etat, jour_fin):
        for ligne in ecriture["lignes"]:
            if ligne["compte"] != compte:
                continue
            if date.fromisoformat(ecriture["date_effet"]) < jour_debut:
                ouverture += ligne["debit"] - ligne["credit"]
            else:
                mouvements.append((ecriture, ligne))
    solde = ouverture
    lignes = []
    debits = credits = _ZERO
    for ecriture, ligne in mouvements:
        solde += ligne["debit"] - ligne["credit"]
        debits, credits = debits + ligne["debit"], credits + ligne["credit"]
        lignes.append({
            "date_effet": ecriture["date_effet"], "numero": ecriture["numero"],
            "ecriture_id": ecriture["ecriture_id"], "libelle": ecriture["libelle"],
            "piece": f"{ecriture['piece']['type']}:{ecriture['piece']['reference']}",
            "debit": _texte(ligne["debit"]) if ligne["debit"] > 0 else None,
            "credit": _texte(ligne["credit"]) if ligne["credit"] > 0 else None,
            "solde_debiteur": _texte(solde),
        })
    fiche = plan["comptes"][compte]
    return {
        "compte": compte, "nom": fiche["nom"], "type": fiche["type"], "actif": fiche["actif"],
        "sens_normal": plan_comptable.sens_normal(fiche["type"]),
        "debut": jour_debut.isoformat(), "fin": jour_fin.isoformat(), "devise": _DEVISE,
        "solde_ouverture_debiteur": _texte(ouverture),
        "total_debits": _texte(debits), "total_credits": _texte(credits),
        "solde_cloture_debiteur": _texte(solde),
        "lignes": lignes[depart:depart + limite],
        "lignes_total": len(lignes),
        "prochain_depart": depart + limite if depart + limite < len(lignes) else None,
        "brouillons_non_comptabilises": _brouillons(etat, jour_fin),
    }, None


def _taxes_attendues(
    factures: Iterable[Mapping[str, Any]], dictionnaire_taux: Mapping[str, Any], debut: date, fin: date
) -> tuple[dict[str, dict[str, Decimal]], list[dict[str, str]]]:
    """Par facture ÉMISE dans la période, la TPS et la TVQ que `taxes.calculer_taxes` (taux versionnés) calcule sur
    son montant avant taxes : la référence indépendante du rapprochement."""
    attendues: dict[str, dict[str, Decimal]] = {}
    illisibles: list[dict[str, str]] = []
    for facture in factures:
        if facture.get("statut") not in ("ENVOYEE", "PAYEE"):
            continue
        jour = _jour_iso(facture.get("date_envoi"))
        if jour is None or not debut <= date.fromisoformat(jour) <= fin:
            if jour is None:
                illisibles.append({"facture_id": str(facture.get("facture_id")), "code": "REJ-GL-SOURCE-ILLISIBLE"})
            continue
        calcul, verdict = taxes.calculer_taxes(facture.get("montant_avant_taxes"), dictionnaire_taux)
        if verdict is not None:
            illisibles.append({"facture_id": str(facture.get("facture_id")), "code": verdict["code"]})
            continue
        attendues[facture["facture_id"]] = {_TAXES_FACTURE[t["id"]]: t["montant"] for t in calcul["taxes"]}
    return attendues, illisibles


def _taxes_payees(
    factures_fournisseurs: Iterable[Mapping[str, Any]], debut: date, fin: date
) -> tuple[dict[str, dict[str, Decimal]], list[dict[str, str]]]:
    """Par facture fournisseur VIVANTE datée dans la période, la TPS et la TVQ PAYÉES telles que la pièce les porte
    (relues, jamais recalculées : ce sont elles que le brouillon doit débiter aux CTI et RTI)."""
    attendues: dict[str, dict[str, Decimal]] = {}
    illisibles: list[dict[str, str]] = []
    for facture in factures_fournisseurs:
        if facture.get("statut") not in _STATUTS_FOURNISSEUR_VIVANTS:
            continue
        ident = str(facture.get("facture_fournisseur_id"))
        jour = _date(facture.get("date_facture"))
        if jour is None:
            illisibles.append({"facture_fournisseur_id": ident, "code": "REJ-GL-SOURCE-ILLISIBLE"})
            continue
        if not debut <= jour <= fin:
            continue
        lus = _montants_lus(facture, _TAXES_INTRANTS)
        if lus is None:
            illisibles.append({"facture_fournisseur_id": ident, "code": "REJ-GL-SOURCE-ILLISIBLE"})
            continue
        attendues[ident] = lus[2]
    return attendues, illisibles


def _rapprocher_taxe(
    periode: list[Mapping[str, Any]],
    compte: str,
    role: str,
    attendues: Mapping[tuple[str, str], Mapping[str, Decimal]],
    *,
    types_piece: tuple[str, ...],
    debiteur: bool,
    cle_id: str,
    cle_attendu: str,
    raison_sans_piece: str,
    raison_autre: str,
) -> tuple[Decimal, Decimal, list[dict[str, Any]]]:
    """Le mouvement net d'un compte de taxe dans la période (débiteur ou créditeur selon le compte), par pièce du type
    `types_piece`, contre ce que chaque pièce attend : `(attendu total, au grand livre total, écarts par pièce)`."""
    par_piece: dict[tuple[str, str], Decimal] = {}
    autres = _ZERO
    for ecriture in periode:
        net = sum((ligne["credit"] - ligne["debit"] for ligne in ecriture["lignes"] if ligne["compte"] == compte),
                  _ZERO)
        if debiteur:
            net = -net
        if net == 0:
            continue
        if ecriture["piece"]["type"] in types_piece:
            identite = (ecriture["piece"]["type"], ecriture["piece"]["reference"])
            par_piece[identite] = par_piece.get(identite, _ZERO) + net
        else:
            autres += net
    attendu_total = sum((a.get(role, _ZERO) for a in attendues.values()), _ZERO)
    livre_total = sum(par_piece.values(), _ZERO) + autres
    ecarts: list[dict[str, Any]] = []
    identites = set(attendues) | set(par_piece)
    types_par_reference: dict[str, set[str]] = {}
    for type_piece, reference in identites:
        types_par_reference.setdefault(reference, set()).add(type_piece)
    references_multiples = {reference for reference, types in types_par_reference.items() if len(types) > 1}
    for type_piece, reference in sorted(identites, key=lambda identite: (identite[1], identite[0])):
        identite = (type_piece, reference)
        attendu = attendues[identite].get(role, _ZERO) if identite in attendues else None
        au_livre = par_piece.get(identite, _ZERO)
        identifiant = {cle_id: reference}
        if reference in references_multiples:
            identifiant["piece_type"] = type_piece
        if attendu is None:
            ecarts.append({**identifiant, "raison": raison_sans_piece, "au_grand_livre": _texte(au_livre)})
        elif attendu != au_livre:
            ecarts.append({**identifiant, cle_attendu: _texte(attendu), "au_grand_livre": _texte(au_livre),
                           "raison": "sans écriture définitive" if identite not in par_piece
                           else "montant différent"})
    if autres != 0:
        ecarts.append({cle_id: None, "raison": raison_autre, "au_grand_livre": _texte(autres)})
    return attendu_total, livre_total, ecarts


def rapprocher(
    etat: Mapping[str, Any],
    plan: Mapping[str, Any],
    factures: Iterable[Mapping[str, Any]],
    dictionnaire_taux: Mapping[str, Any],
    *,
    debut: Any,
    fin: Any,
    limite_ecarts: int = 10,
    factures_fournisseurs: Iterable[Mapping[str, Any]] = (),
    autres_pieces_taxees: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le rapprochement du grand livre pour la période `debut`..`fin` :
    1. ÉQUILIBRE : chaque écriture définitive est équilibrée, et la somme des débits = la somme des crédits de toutes
       les écritures définitives jusqu'à `fin` ;
    2. TPS et TVQ à percevoir : le mouvement net (crédits moins débits) des comptes TPS et TVQ à percevoir dans la
       période, contre la TPS et la TVQ que `taxes.py` calcule sur les factures émises dans la même période. Écart par
       facture : facture sans écriture définitive, montant différent, ou mouvement de taxe sans facture de la période ;
    3. CTI et RTI (intrants) : le mouvement net (débits moins crédits) des comptes CTI et RTI dans la période, contre la
       TPS et la TVQ PAYÉES que portent les factures fournisseurs vivantes datées dans la période
       (`factures_fournisseurs`, état courant des comptes à payer). Écart par facture fournisseur, mêmes raisons ; un
       mouvement d'une autre pièce (reçu saisi à la main, import) est un écart nommé, jamais absorbé.

    `autres_pieces_taxees` : les pièces d'`operations_comptables.py` (notes de crédit, dépenses d'employés) qui
    mouvementent ces comptes de taxe ; chacune `{piece_type, reference, date_effet, taxes: {rôle: montant attendu}}`, le
    montant étant le mouvement net attendu dans le sens naturel du compte (négatif pour une note de crédit). Sans cela,
    leurs écritures seraient des « écritures non rattachées » ; avec cela, elles sont rapprochées comme les factures."""
    refus = _refus_anomalies(etat)
    if refus is not None:
        return None, refus
    jour_debut, jour_fin = _date(debut), _date(fin)
    if jour_debut is None or jour_fin is None or jour_debut > jour_fin:
        return None, _verdict("REJ-GL-DATE-INVALIDE", "debut et fin AAAA-MM-JJ, debut au plus tard à fin")
    jusqua = _definitives_jusqua(etat, jour_fin)
    debits = sum((ligne["debit"] for e in jusqua for ligne in e["lignes"]), _ZERO)
    credits = sum((ligne["credit"] for e in jusqua for ligne in e["lignes"]), _ZERO)
    desequilibrees = [e["ecriture_id"] for e in jusqua if not _equilibree(e["lignes"])]
    roles = plan["roles"]
    attendues, illisibles = _taxes_attendues(factures, dictionnaire_taux, jour_debut, jour_fin)
    periode = _definitives_jusqua(etat, jour_fin, jour_debut)
    roles_clients = {"tps_a_percevoir", "tvq_a_percevoir"}
    supplementaires: dict[str, dict[tuple[str, str], dict[str, Decimal]]] = {"clients": {}, "intrants": {}}
    types_clients, types_intrants = ["facture_client"], ["facture_fournisseur"]
    for piece in autres_pieces_taxees:
        jour_piece = _date(piece.get("date_effet"))
        if jour_piece is None or not jour_debut <= jour_piece <= jour_fin:
            continue
        for role, montant in piece["taxes"].items():
            cote = "clients" if role in roles_clients else "intrants"
            supplementaires[cote].setdefault((piece["piece_type"], piece["reference"]), {})[role] = montant
            liste = types_clients if cote == "clients" else types_intrants
            if piece["piece_type"] not in liste:
                liste.append(piece["piece_type"])
    taxes_resultat = {}
    attendues_clients = {("facture_client", reference): taxes for reference, taxes in attendues.items()}
    for role in ("tps_a_percevoir", "tvq_a_percevoir"):
        attendu_total, livre_total, ecarts = _rapprocher_taxe(
            periode, roles[role], role, {**attendues_clients, **supplementaires["clients"]},
            types_piece=tuple(types_clients), debiteur=False,
            cle_id="facture_id", cle_attendu="attendu_taxes",
            raison_sans_piece="mouvement de taxe sans facture émise dans la période",
            raison_autre="mouvement d'une écriture non rattachée à une facture client")
        taxes_resultat[role] = {
            "compte": roles[role],
            "attendu_taxes_py": _texte(attendu_total),
            "au_grand_livre": _texte(livre_total),
            "verdict": "CONCORDANT" if attendu_total == livre_total and not ecarts else "ECART",
            "ecarts": ecarts[:limite_ecarts],
            "ecarts_reste": max(0, len(ecarts) - limite_ecarts),
        }
    payees, illisibles_fournisseurs = _taxes_payees(factures_fournisseurs, jour_debut, jour_fin)
    payees_typed = {("facture_fournisseur", reference): taxes for reference, taxes in payees.items()}
    intrants = {}
    for role in ("tps_cti", "tvq_rti"):
        compte = roles.get(role)
        if compte is None:
            continue
        attendu_total, livre_total, ecarts = _rapprocher_taxe(
            periode, compte, role, {**payees_typed, **supplementaires["intrants"]},
            types_piece=tuple(types_intrants), debiteur=True,
            cle_id="facture_fournisseur_id", cle_attendu="attendu_facture",
            raison_sans_piece="mouvement de taxe sans facture fournisseur vivante datée dans la période",
            raison_autre="mouvement d'une écriture non rattachée à une facture fournisseur")
        solde = sum((ligne["debit"] - ligne["credit"] for e in jusqua for ligne in e["lignes"]
                     if ligne["compte"] == compte), _ZERO)
        intrants[role] = {
            "compte": compte,
            "attendu_factures_fournisseurs": _texte(attendu_total),
            "au_grand_livre": _texte(livre_total),
            "solde_debiteur_a_la_fin": _texte(solde),
            "verdict": "CONCORDANT" if attendu_total == livre_total and not ecarts else "ECART",
            "ecarts": ecarts[:limite_ecarts],
            "ecarts_reste": max(0, len(ecarts) - limite_ecarts),
        }
    equilibre = debits == credits and not desequilibrees
    return {
        "debut": jour_debut.isoformat(),
        "fin": jour_fin.isoformat(),
        "equilibre": {"total_debits": _texte(debits), "total_credits": _texte(credits),
                      "ecritures_desequilibrees": desequilibrees, "verdict": "EQUILIBRE" if equilibre
                      else "DESEQUILIBRE"},
        "taxes": taxes_resultat,
        "factures_illisibles": illisibles[:limite_ecarts],
        "intrants": intrants,
        "factures_fournisseurs_illisibles": illisibles_fournisseurs[:limite_ecarts],
        "brouillons_non_comptabilises": _brouillons(etat, jour_fin),
        "doublons_ignores": len(etat["doublons"]),
        "verdict": "CONCORDANT" if equilibre and not illisibles and not illisibles_fournisseurs and all(
            t["verdict"] == "CONCORDANT" for t in (*taxes_resultat.values(), *intrants.values())) else "ECART",
    }, None
