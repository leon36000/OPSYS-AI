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
    "proposer_ecriture",
    "valider_ecriture",
    "proposer_contre_passation",
    "clore_periode",
    "propositions_factures_clients",
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
_PERIODE = re.compile(r"^(\d{4})-(\d{2})$")
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
}
_TAXES_FACTURE = {"tps_federale": "tps_a_percevoir", "tvq_quebec": "tvq_a_percevoir"}


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_grand_livre.construire_verdict(code, detail=detail)


def _texte(valeur: Decimal) -> str:
    return str(valeur.quantize(_CENT, rounding=ROUND_HALF_UP))


def _texte_borne(valeur: Any, maximum: int) -> str | None:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum or "\n" in valeur:
        return None
    return valeur.strip()


def _date(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or not _DATE.match(valeur):
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
    correspondance = _PERIODE.match(periode) if isinstance(periode, str) else None
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
            return {"statut": "deja_proposee", "ecriture": vue_ecriture(existante, plan)}, None
        return None, _verdict("REJ-GL-PIECE-CONFLIT", f"la pièce {cle_piece!r} porte déjà l'écriture {ident}, "
                                                      "d'un autre contenu : contre-passer ou citer une autre pièce")
    refus = _refus_verrou(etat, jour)
    if refus is not None:
        return None, refus
    entree = {
        "type_entree": _TYPE_PROPOSEE,
        "ecriture_id": ident,
        **corps,
        "plan_comptable_version": plan["version_effective"],
        "origine": origine,
        "empreinte_contenu": empreinte,
        "horodatage": horodatage,
    }
    maillon = _retrouver(registre_cible, registre_cible.ajouter(entree))
    ecriture = {**maillon, "statut": _BROUILLON, "numero": None, "validation": None, "contre_passee_par": None}
    return {"statut": "proposee", "ecriture": vue_ecriture(ecriture, plan)}, None


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
    numero = etat["definitives"] + 1
    entree = {
        "type_entree": _TYPE_VALIDEE,
        "ecriture_id": ecriture_id,
        "empreinte_contenu": ecriture["empreinte_contenu"],
        "numero": numero,
        "valide_par": humain["par"],
        "role": humain["role"],
        "voie": humain["voie"],
        "horodatage": horodatage,
    }
    registre_cible.ajouter(entree)
    definitive = {**ecriture, "statut": _DEFINITIVE, "numero": numero, "validation": {
        "par": humain["par"], "role": humain["role"], "voie": humain["voie"], "horodatage": horodatage}}
    return {"statut": "validee", "ecriture": vue_ecriture(definitive, plan)}, None


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
        cle_piece=f"contre_passation:{originale['ecriture_id']}",
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
        avant, apres, total = (facture.get(c) for c in ("montant_avant_taxes", "montant_apres_taxes", "total_taxes"))
        detail_taxes = facture.get("taxes")
        lisible = (all(isinstance(v, Decimal) and v.is_finite() for v in (avant, apres, total))
                   and isinstance(detail_taxes, (list, tuple)))
        montants_taxe: dict[str, Decimal] = {}
        if lisible:
            for taxe in detail_taxes:
                role = _TAXES_FACTURE.get(taxe.get("id")) if isinstance(taxe, Mapping) else None
                montant = taxe.get("montant") if role is not None else None
                if role is None or not isinstance(montant, Decimal) or role in montants_taxe:
                    lisible = False
                    break
                montants_taxe[role] = montant
        if (not lisible or avant + total != apres or sum(montants_taxe.values(), _ZERO) != total
                or apres <= 0 or avant <= 0):
            ignorees.append({"facture_id": str(ident), "code": "REJ-GL-SOURCE-ILLISIBLE",
                             "detail": "montants ou taxes de la facture illisibles ou incohérents"})
            continue
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


def rapprocher(
    etat: Mapping[str, Any],
    plan: Mapping[str, Any],
    factures: Iterable[Mapping[str, Any]],
    dictionnaire_taux: Mapping[str, Any],
    *,
    debut: Any,
    fin: Any,
    limite_ecarts: int = 10,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le rapprochement du grand livre pour la période `debut`..`fin` :
    1. ÉQUILIBRE : chaque écriture définitive est équilibrée, et la somme des débits = la somme des crédits de toutes
       les écritures définitives jusqu'à `fin` ;
    2. TPS et TVQ : le mouvement net (crédits moins débits) des comptes TPS et TVQ à percevoir dans la période, contre
       la TPS et la TVQ que `taxes.py` calcule sur les factures émises dans la même période. Écart par facture :
       facture sans écriture définitive, montant différent, ou mouvement de taxe sans facture de la période.
    Les crédits et remboursements sur intrants (CTI/RTI) sont rendus en solde, NON rapprochés en tranche 1."""
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
    taxes_resultat = {}
    for role in ("tps_a_percevoir", "tvq_a_percevoir"):
        compte = roles[role]
        par_facture: dict[str, Decimal] = {}
        autres = _ZERO
        for ecriture in periode:
            net = sum((ligne["credit"] - ligne["debit"] for ligne in ecriture["lignes"] if ligne["compte"] == compte),
                      _ZERO)
            if net == 0:
                continue
            if ecriture["piece"]["type"] == "facture_client":
                reference = ecriture["piece"]["reference"]
                par_facture[reference] = par_facture.get(reference, _ZERO) + net
            else:
                autres += net
        attendu_total = sum((a.get(role, _ZERO) for a in attendues.values()), _ZERO)
        livre_total = sum(par_facture.values(), _ZERO) + autres
        ecarts = []
        for reference in sorted(set(attendues) | set(par_facture)):
            attendu = attendues.get(reference, {}).get(role, _ZERO) if reference in attendues else None
            au_livre = par_facture.get(reference, _ZERO)
            if attendu is None:
                ecarts.append({"facture_id": reference, "raison": "mouvement de taxe sans facture émise dans la "
                               "période", "au_grand_livre": _texte(au_livre)})
            elif attendu != au_livre:
                ecarts.append({"facture_id": reference, "attendu_taxes": _texte(attendu),
                               "au_grand_livre": _texte(au_livre),
                               "raison": "sans écriture définitive" if reference not in par_facture
                               else "montant différent"})
        if autres != 0:
            ecarts.append({"facture_id": None, "raison": "mouvement d'une écriture non rattachée à une facture client",
                           "au_grand_livre": _texte(autres)})
        taxes_resultat[role] = {
            "compte": compte,
            "attendu_taxes_py": _texte(attendu_total),
            "au_grand_livre": _texte(livre_total),
            "verdict": "CONCORDANT" if attendu_total == livre_total and not ecarts else "ECART",
            "ecarts": ecarts[:limite_ecarts],
            "ecarts_reste": max(0, len(ecarts) - limite_ecarts),
        }
    intrants = {}
    for role in ("tps_cti", "tvq_rti"):
        compte = roles.get(role)
        if compte is None:
            continue
        solde = sum((ligne["debit"] - ligne["credit"] for e in jusqua for ligne in e["lignes"]
                     if ligne["compte"] == compte), _ZERO)
        intrants[role] = {"compte": compte, "solde_debiteur": _texte(solde), "rapproche": False}
    equilibre = debits == credits and not desequilibrees
    return {
        "debut": jour_debut.isoformat(),
        "fin": jour_fin.isoformat(),
        "equilibre": {"total_debits": _texte(debits), "total_credits": _texte(credits),
                      "ecritures_desequilibrees": desequilibrees, "verdict": "EQUILIBRE" if equilibre
                      else "DESEQUILIBRE"},
        "taxes": taxes_resultat,
        "factures_illisibles": illisibles[:limite_ecarts],
        "intrants_non_rapproches": intrants,
        "brouillons_non_comptabilises": _brouillons(etat, jour_fin),
        "doublons_ignores": len(etat["doublons"]),
        "verdict": "CONCORDANT" if equilibre and not illisibles and all(
            t["verdict"] == "CONCORDANT" for t in taxes_resultat.values()) else "ECART",
    }, None
