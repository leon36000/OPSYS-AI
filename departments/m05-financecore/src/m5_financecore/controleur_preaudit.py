"""Le CONTRÔLEUR de pré-audit de M5 (M5-PRE-AUDIT) : des règles DÉTERMINISTES, en lecture seule, qui relisent les
registres
déjà écrits et sortent une liste de CONSTATS (règle, raison, sources, action proposée). Rien n'est exécuté, rien n'est
corrigé, aucun modèle ne juge.

Module pur (ADR-0009) : aucun import d'`opsys`, aucune horloge (« aujourd'hui » vient de l'appelant), aucun registre,
aucun réseau, aucune écriture. `outils_rapports.py` lit les registres, normalise un `dossier` (types JSON) et appelle
`controler`.

Les dix règles (codes stables, ordre fixe) :

| Règle | Ce qu'elle voit |
|---|---|
| `FACTURE_SANS_PAIEMENT` | facture ENVOYÉE dont l'échéance PROPRE est dépassée (strictement) et qui n'est pas payée |
| `PAIEMENT_SANS_FACTURE` | encaissement client (ou décaissement fournisseur) au grand livre sans facture payée
(vivante) derrière |
| `DEPENSE_SANS_RECU` | facture fournisseur, dépense d'employé ou écriture de charge sans pièce justificative liée |
| `TAXE_INCOHERENTE` | TPS/TVQ du grand livre contre le moteur fiscal versionné (jamais un taux écrit ici) |
| `DOUBLON_PROBABLE` | même fournisseur, même montant avant taxes, dates proches (ou écritures manuelles identiques) |
| `TRANSACTION_HORS_NORME` | montant à partir d'un seuil DÉCLARÉ par la direction ; sans seuil, règle NON ÉVALUÉE |
| `FACTURE_MODIFIEE` | facture corrigée ou annulée dont l'écriture n'est plus celle de la pièce courante |
| `CHANGEMENT_COMPTE_INHABITUEL` | un fournisseur dont les n dernières factures allaient au même compte de charge
change de compte (n DÉCLARÉ) |
| `PISTE_AUDIT_INCOMPLETE` | chaîne d'un registre altérée, anomalie du grand livre, numéro de facture manquant ou en
double |
| `DOCUMENT_MANQUANT` | facture émise ou fournisseur sans écriture, écriture dont la pièce est introuvable, pièce
illisible |

Fail-closed : une règle dont la donnée déclarée est absente est « NON ÉVALUÉE » et DIT ce qu'il faut déclarer ; elle ne
compte pas zéro constat (`par_regle[règle]` vaut `null`). Une règle évaluée seulement en partie est « PARTIELLE » et dit
laquelle. Un grand livre altéré rend non évaluées les règles qui en dépendent : jamais « aucun constat ».

Interprétation écrite (à valider par le CPA) : « changement de compte inhabituel » vise le compte de CHARGE auquel un
fournisseur est rangé. Le changement de coordonnées BANCAIRES d'un fournisseur n'est pas évaluable : M5 n'en garde
aucune
(dit dans `limites`).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import encodage, recu_calcul

__all__ = [
    "GRAVITES",
    "REGLES",
    "VERSION",
    "controler",
    "normaliser_lignes",
    "rejouer",
    "seuils_depuis",
]

VERSION = "1.0.0"
# Listes fermées du contrôleur : privées dans leur définition, exposées par alias (la garde de conformité traite une
# séquence
# publique en MAJUSCULES comme un énumérés de classification qui exigerait une échappatoire ; ici la liste est un
# catalogue de
# règles du code, jamais une classification déduite d'une entrée ambiguë).
_LES_REGLES = (
    "FACTURE_SANS_PAIEMENT",
    "PAIEMENT_SANS_FACTURE",
    "DEPENSE_SANS_RECU",
    "TAXE_INCOHERENTE",
    "DOUBLON_PROBABLE",
    "TRANSACTION_HORS_NORME",
    "FACTURE_MODIFIEE",
    "CHANGEMENT_COMPTE_INHABITUEL",
    "PISTE_AUDIT_INCOMPLETE",
    "DOCUMENT_MANQUANT",
)
_LES_GRAVITES = ("haute", "moyenne", "faible")
REGLES = _LES_REGLES
GRAVITES = _LES_GRAVITES
_GRAVITE_DE_REGLE = {
    "FACTURE_SANS_PAIEMENT": "moyenne",
    "PAIEMENT_SANS_FACTURE": "haute",
    "DEPENSE_SANS_RECU": "moyenne",
    "TAXE_INCOHERENTE": "haute",
    "DOUBLON_PROBABLE": "haute",
    "TRANSACTION_HORS_NORME": "faible",
    "FACTURE_MODIFIEE": "haute",
    "CHANGEMENT_COMPTE_INHABITUEL": "moyenne",
    "PISTE_AUDIT_INCOMPLETE": "haute",
    "DOCUMENT_MANQUANT": "moyenne",
}
# Les règles qui lisent le grand livre : un grand livre altéré les rend non évaluées.
_REGLES_DU_GRAND_LIVRE = frozenset(
    {"PAIEMENT_SANS_FACTURE", "TAXE_INCOHERENTE", "TRANSACTION_HORS_NORME", "FACTURE_MODIFIEE", "DOCUMENT_MANQUANT"}
)
_REGLES_PAR_REGISTRE = {
    "factures": frozenset(
        {
            "FACTURE_SANS_PAIEMENT",
            "PAIEMENT_SANS_FACTURE",
            "TAXE_INCOHERENTE",
            "FACTURE_MODIFIEE",
            "DOCUMENT_MANQUANT",
        }
    ),
    "comptes_a_payer": frozenset(
        {
            "PAIEMENT_SANS_FACTURE",
            "DEPENSE_SANS_RECU",
            "TAXE_INCOHERENTE",
            "DOUBLON_PROBABLE",
            "FACTURE_MODIFIEE",
            "CHANGEMENT_COMPTE_INHABITUEL",
            "DOCUMENT_MANQUANT",
        }
    ),
    "operations_comptables": frozenset({"DEPENSE_SANS_RECU", "TAXE_INCOHERENTE", "DOCUMENT_MANQUANT"}),
}
_PIECES_MANUELLES = ("manuelle", "recu", "releve_bancaire")
_PIECES_VERIFIEES = ("facture_client", "facture_fournisseur", "note_credit", "depense_employe")
_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")
_SEUIL_MAX = Decimal("999999999999.99")
_SEUIL_AFFICHAGE_MAX = 120  # borne de présentation, pas de saisie ni de calcul monétaire
_FENETRE_DOUBLON_MAX = 366
_HISTORIQUE_MAX = 50
_SOURCES_MAX = 12
_PRECISION = {"montants": "Decimal exact au cent, aucun arrondi", "comptes": "dénombrements entiers"}
_MAGASIN = re.compile(r"\s+")


# ---------------------------------------------------------------------------------------------------- les seuils
def seuils_depuis(brut: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Les seuils DÉCLARÉS (couche de réglages de direction) lus et contrôlés : `(seuils, problèmes)`. Un seuil absent
    vaut `None` (la règle est non évaluée) ; un seuil présent mais mal formé vaut aussi `None` ET est nommé dans les
    problèmes : jamais une valeur par défaut, jamais un seuil deviné."""
    problemes: list[str] = []
    seuils: dict[str, Any] = {
        "transaction_hors_norme_cad": None,
        "jours_fenetre_doublon": None,
        "historique_changement_compte": None,
    }
    montant = brut.get("seuil_transaction_hors_norme_cad")
    if montant is not None:
        try:
            valeur = Decimal(str(montant))
            if not (Decimal(0) < valeur <= _SEUIL_MAX) or isinstance(montant, bool):
                raise ValueError
            # Le seuil est une déclaration de direction, pas un montant comptabilisé : aucun arrondi ne doit le
            # déplacer. Les valeurs exactes au cent gardent le format historique `123.00`; un seuil sub-cent reste
            # en notation décimale/scientifique compacte sans expansion d'exposants extrêmes.
            seuils["transaction_hors_norme_cad"] = _texte_seuil_exact(valeur)
        except (ValueError, ArithmeticError):
            problemes.append("seuil_transaction_hors_norme_cad : montant décimal positif exigé")
    for cle, sortie, maximum in (
        ("jours_fenetre_doublon", "jours_fenetre_doublon", _FENETRE_DOUBLON_MAX),
        ("historique_changement_compte", "historique_changement_compte", _HISTORIQUE_MAX),
    ):
        valeur = brut.get(cle)
        if valeur is None:
            continue
        if type(valeur) is int and 1 <= valeur <= maximum:
            seuils[sortie] = valeur
        else:
            problemes.append(f"{cle} : entier de 1 à {maximum} exigé")
    return seuils, problemes


def _texte_seuil_exact(valeur: Decimal) -> str:
    """Formate au cent seulement si le Decimal vaut exactement un multiple de 0,01; sinon le garde compact et exact."""
    signe, chiffres, exposant = valeur.as_tuple()
    if exposant < -2:
        chiffres_a_retirer = -2 - exposant
        if chiffres_a_retirer > len(chiffres) or any(chiffres[-chiffres_a_retirer:]):
            return str(valeur)
        chiffres = chiffres[:-chiffres_a_retirer]
        exposant = -2
    texte = "".join(map(str, chiffres))
    position_point = len(texte) + exposant
    if position_point <= 0:
        entier, fraction = "0", "0" * -position_point + texte
    elif position_point >= len(texte):
        entier, fraction = texte + "0" * (position_point - len(texte)), ""
    else:
        entier, fraction = texte[:position_point], texte[position_point:]
    return ("-" if signe else "") + entier + "." + fraction.ljust(2, "0")[:2]


# ------------------------------------------------------------------------------------------------ normalisation
def normaliser_lignes(lignes: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    """Les lignes d'une écriture sous une forme comparable : `[compte, débit, crédit]` en textes au cent, triées."""

    def montant(valeur: Any) -> str:
        if valeur is None:
            return "0.00"
        return format(Decimal(str(valeur)).quantize(_CENT, rounding=ROUND_HALF_UP), "f")

    return sorted([ligne["compte"], montant(ligne.get("debit")), montant(ligne.get("credit"))] for ligne in lignes)


def _jour(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or len(valeur) < 10 or not valeur[:10].isascii():
        return None
    try:
        return date.fromisoformat(valeur[:10])
    except ValueError:
        return None


def _dec(texte: Any) -> Decimal:
    return Decimal(str(texte))


def _txt(valeur: Decimal) -> str:
    return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _nom(texte: Any) -> str:
    return _MAGASIN.sub(" ", str(texte)).strip().casefold()


def _constat(
    regle: str,
    raison: str,
    sources: Sequence[Mapping[str, str]],
    action: str,
    *,
    montant: str | None = None,
    outil: str | None = None,
) -> dict[str, Any]:
    triees = sorted(
        ({"registre": s["registre"], "reference": s["reference"]} for s in sources),
        key=lambda s: (s["registre"], s["reference"]),
    )
    cle = (
        "pa-"
        + encodage.empreinte("m5.preaudit.constat.v1", regle, [[s["registre"], s["reference"]] for s in triees])[:16]
    )
    constat: dict[str, Any] = {
        "cle": cle,
        "regle": regle,
        "gravite": _GRAVITE_DE_REGLE[regle],
        "raison": raison,
        "sources": triees[:_SOURCES_MAX],
        "sources_total": len(triees),
        "action_proposee": action,
        "action_executee": False,
    }
    if montant is not None:
        constat["montant_cad"] = montant
    if outil is not None:
        constat["outil_suggere"] = outil
    return constat


# ================================================================================================== les règles
Resultat = tuple[list[dict[str, Any]], str, list[str]]  # (constats, état, ce qui manque ou limite)


def _facture_sans_paiement(d: Mapping[str, Any]) -> Resultat:
    aujourd_hui = _jour(d["aujourd_hui"])
    constats: list[dict[str, Any]] = []
    sans_echeance = 0
    for f in d["factures_clients"]:
        if f["statut"] != "ENVOYEE":
            continue
        echeance = _jour(f.get("echeance"))
        if echeance is None:
            sans_echeance += 1
            continue
        if echeance < aujourd_hui:
            retard = (aujourd_hui - echeance).days
            numero = f.get("numero") or f["facture_id"]
            constats.append(
                _constat(
                    "FACTURE_SANS_PAIEMENT",
                    f"La facture {numero} est échue depuis {retard} jour(s) (échéance {echeance.isoformat()}) et "
                    f"aucun paiement "
                    "n'est enregistré.",
                    [{"registre": "factures", "reference": f["facture_id"]}],
                    "Préparer une relance en brouillon et la faire valider ; vérifier d'abord que le paiement n'a "
                    "pas été "
                    "reçu sans être enregistré (rapprochement bancaire).",
                    montant=f.get("montant_apres_taxes"),
                    outil="m5_preparer_relances_clients",
                )
            )
    manque = []
    if sans_echeance:
        manque.append(
            f"{sans_echeance} facture(s) émise(s) sans échéance lisible : le retard n'est pas calculable pour elles"
        )
    return constats, "PARTIELLE" if sans_echeance else "EVALUEE", manque


def _flux(ecriture: Mapping[str, Any], compte_debit: str, compte_credit: str) -> bool:
    debits = {ligne[0] for ligne in ecriture["lignes"] if _dec(ligne[1]) > 0}
    credits = {ligne[0] for ligne in ecriture["lignes"] if _dec(ligne[2]) > 0}
    return compte_debit in debits and compte_credit in credits


def _paiement_sans_facture(d: Mapping[str, Any]) -> Resultat:
    plan = d["plan"]
    clients = {f["facture_id"]: f for f in d["factures_clients"]}
    fournisseurs = {f["id"]: f for f in d["factures_fournisseurs"]}
    constats: list[dict[str, Any]] = []
    for e in d["ecritures"]:
        if e.get("contre_passe") is not None:
            continue
        source = {"registre": "grand_livre", "reference": e["id"]}
        if _flux(e, plan["banque"], plan["comptes_clients"]):
            facture = clients.get(e["piece_ref"]) if e["piece_type"] == "facture_client" else None
            if facture is None or facture["statut"] != "PAYEE":
                constats.append(
                    _constat(
                        "PAIEMENT_SANS_FACTURE",
                        f"L'écriture {e['id']} ({e['date_effet']}) encaisse un montant des comptes clients sans "
                        f"facture payée "
                        "derrière (pièce "
                        + (f"{e['piece_type']}:{e['piece_ref']}" if e["piece_ref"] else e["piece_type"])
                        + ").",
                        [source],
                        "Retrouver la facture visée et la lier, ou comprendre l'origine de l'encaissement ; ne rien "
                        "contre-passer avant de savoir.",
                        montant=_txt(sum((_dec(li[1]) for li in e["lignes"] if li[0] == plan["banque"]), _ZERO)),
                        outil="m5_proposer_contre_passation",
                    )
                )
        elif _flux(e, plan["comptes_fournisseurs"], plan["banque"]):
            facture = fournisseurs.get(e["piece_ref"]) if e["piece_type"] == "facture_fournisseur" else None
            if facture is None or facture["statut"] not in ("SAISIE", "CORRIGEE"):
                constats.append(
                    _constat(
                        "PAIEMENT_SANS_FACTURE",
                        f"L'écriture {e['id']} ({e['date_effet']}) règle un montant des comptes fournisseurs sans "
                        f"facture "
                        "fournisseur vivante derrière.",
                        [source],
                        "Retrouver la facture fournisseur visée (ou comprendre le décaissement) avant toute autre "
                        "écriture.",
                        montant=_txt(sum((_dec(li[2]) for li in e["lignes"] if li[0] == plan["banque"]), _ZERO)),
                    )
                )
    return constats, "EVALUEE", []


def _depense_sans_recu(d: Mapping[str, Any]) -> Resultat:
    liees = {(p[0], p[1]) for p in d["pieces_liees"]}
    constats: list[dict[str, Any]] = []
    for f in d["factures_fournisseurs"]:
        if f["statut"] in ("SAISIE", "CORRIGEE") and ("facture_fournisseur", f["id"]) not in liees:
            constats.append(
                _constat(
                    "DEPENSE_SANS_RECU",
                    f"La facture fournisseur {f['numero']} du {f['date_facture']} n'a aucune pièce justificative liée.",
                    [{"registre": "comptes_a_payer", "reference": f["id"]}],
                    "Joindre la facture ou le reçu (m5_lier_piece_justificative) ; la pièce se dépose, M5 n'en "
                    "invente pas.",
                    montant=f.get("montant_avant_taxes"),
                    outil="m5_lier_piece_justificative",
                )
            )
    for depense in d["depenses_employes"]:
        if ("depense_employe", depense["id"]) not in liees:
            constats.append(
                _constat(
                    "DEPENSE_SANS_RECU",
                    f"La dépense d'employé {depense['id']} du {depense['date']} n'a aucun reçu lié.",
                    [{"registre": "operations_comptables", "reference": depense["id"]}],
                    "Joindre le reçu (m5_lier_piece_justificative) avant de rembourser quoi que ce soit.",
                    montant=depense.get("montant"),
                    outil="m5_lier_piece_justificative",
                )
            )
    if d["gl_utilisable"]:
        types = d["plan"]["types"]
        for e in d["ecritures"]:
            if e["piece_type"] not in ("recu", "manuelle") or e.get("contre_passe") is not None:
                continue
            if not any(types.get(li[0]) == "charges" and _dec(li[1]) > 0 for li in e["lignes"]):
                continue
            if ("ecriture", e["id"]) not in liees:
                constats.append(
                    _constat(
                        "DEPENSE_SANS_RECU",
                        f"L'écriture {e['id']} du {e['date_effet']} constate une charge sur une pièce déclarée "
                        f"({e['piece_type']}) sans reçu lié.",
                        [{"registre": "grand_livre", "reference": e["id"]}],
                        "Joindre le reçu (m5_lier_piece_justificative).",
                        montant=_txt(sum((_dec(li[1]) for li in e["lignes"] if types.get(li[0]) == "charges"), _ZERO)),
                        outil="m5_lier_piece_justificative",
                    )
                )
    return constats, "EVALUEE", []


def _taxe_incoherente(d: Mapping[str, Any]) -> Resultat:
    taxes = d["taxes"]
    if not taxes["disponible"]:
        return [], "NON_EVALUEE", [f"rapprochement des taxes impossible : {taxes['raison']}"]
    groupes: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    # Une pièce SANS écriture définitive n'a pas de taxe incohérente : elle n'a pas d'écriture (DOCUMENT_MANQUANT si
    # elle n'a
    # même pas de brouillon) ou son brouillon attend une validation (le rapport le compte). Ici, seulement ce qui
    # DIFFÈRE.
    for ecart in taxes["ecarts"]:
        if ecart.get("sans_ecriture"):
            continue
        groupes[f"{ecart['cote']}:{ecart['reference'] or 'sans-piece'}"].append(ecart)
    constats = []
    for cle in sorted(groupes):
        ecarts = groupes[cle]
        cote = ecarts[0]["cote"]
        reference = ecarts[0]["reference"]
        details = "; ".join(
            f"{e['role']} : {e['raison']}"
            + (
                f" (attendu {e['attendu']}, au grand livre {e['au_grand_livre']})"
                if e.get("attendu") is not None
                else f" (au grand livre {e['au_grand_livre']})"
            )
            for e in ecarts
        )
        constats.append(
            _constat(
                "TAXE_INCOHERENTE",
                ("Taxes à percevoir" if cote == "clients" else "Taxes sur intrants")
                + (f" de {reference}" if reference else " d'une écriture non rattachée")
                + f" : {details}.",
                [
                    {
                        "registre": "factures" if cote == "clients" else "comptes_a_payer",
                        "reference": reference or "ecritures-non-rattachees",
                    }
                ],
                "Comparer l'écriture à la pièce et au moteur fiscal (m5_rapprocher_grand_livre) ; corriger par une "
                "contre-passation validée, jamais en modifiant l'écriture.",
                outil="m5_rapprocher_grand_livre",
            )
        )
    illisibles = taxes.get("illisibles", 0)
    return (
        constats,
        "PARTIELLE" if illisibles else "EVALUEE",
        (
            [f"{illisibles} pièce(s) aux montants ou taxes illisibles : leurs taxes n'ont pas pu être comparées"]
            if illisibles
            else []
        ),
    )


def _groupes_proches(elements: Sequence[tuple[date, str]], fenetre: int) -> list[list[str]]:
    """Regroupe (jour, identifiant) en chaînes dont deux voisins sont distants de `fenetre` jours ou moins."""
    groupes: list[list[tuple[date, str]]] = []
    for jour, ident in sorted(elements):
        if groupes and (jour - groupes[-1][-1][0]).days <= fenetre:
            groupes[-1].append((jour, ident))
        else:
            groupes.append([(jour, ident)])
    return [[ident for _jour_, ident in g] for g in groupes if len(g) > 1]


def _doublon(d: Mapping[str, Any]) -> Resultat:
    fenetre = d["seuils"]["jours_fenetre_doublon"]
    constats: list[dict[str, Any]] = []
    par_cle: dict[tuple[str, str], list[tuple[date, str]]] = defaultdict(list)
    numeros: dict[str, str] = {}
    for f in d["factures_fournisseurs"]:
        jour = _jour(f.get("date_facture"))
        if f["statut"] in ("SAISIE", "CORRIGEE") and jour is not None:
            par_cle[(_nom(f["fournisseur_id"]), _txt(_dec(f["montant_avant_taxes"])))].append((jour, f["id"]))
            numeros[f["id"]] = f["numero"]
    for (_fournisseur, montant), elements in sorted(par_cle.items()):
        for groupe in _groupes_proches(elements, fenetre if fenetre is not None else 0):
            texte_fenetre = f"moins de {fenetre} jour(s) d'écart" if fenetre else "la même date"
            constats.append(
                _constat(
                    "DOUBLON_PROBABLE",
                    f"{len(groupe)} factures du même fournisseur au même montant avant taxes ({montant} $) à "
                    f"{texte_fenetre} : numéros " + ", ".join(sorted(str(numeros[i]) for i in groupe)) + ".",
                    [{"registre": "comptes_a_payer", "reference": i} for i in groupe],
                    "Vérifier auprès du fournisseur ; si c'est un doublon, annuler la facture en trop "
                    "(m5_annuler_facture_fournisseur, "
                    "validation humaine) avant tout paiement.",
                    montant=montant,
                    outil="m5_annuler_facture_fournisseur",
                )
            )
    if d["gl_utilisable"]:
        manuelles: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        for e in d["ecritures"]:
            if (
                e["piece_type"] in _PIECES_MANUELLES
                and not str(e["cle"]).startswith("auto:")
                and e.get("contre_passe") is None
            ):
                manuelles[(e["date_effet"], e["piece_type"], repr(e["lignes"]))].append(e["id"])
        for (jour, _type, _lignes), ids in sorted(manuelles.items()):
            if len(ids) > 1:
                constats.append(
                    _constat(
                        "DOUBLON_PROBABLE",
                        f"{len(ids)} écritures saisies à la main le {jour} ont exactement les mêmes lignes.",
                        [{"registre": "grand_livre", "reference": i} for i in ids],
                        "Confirmer qu'il ne s'agit pas d'une double saisie ; contre-passer l'écriture en trop "
                        "(validation "
                        "humaine).",
                        outil="m5_proposer_contre_passation",
                    )
                )
    limites = []
    if fenetre is None:
        limites.append("m5.jours_fenetre_doublon non déclaré : seuls les doublons de la MÊME date sont évalués")
    if not d["gl_utilisable"]:
        limites.append("grand livre non utilisable : les doublons d'écritures manuelles ne sont pas évalués")
    return constats, "PARTIELLE" if limites else "EVALUEE", limites


def _hors_norme(d: Mapping[str, Any]) -> Resultat:
    seuil = d["seuils"]["transaction_hors_norme_cad"]
    if seuil is None:
        return (
            [],
            "NON_EVALUEE",
            [
                "m5.seuil_transaction_hors_norme_cad non déclaré : la direction décide à partir de quel montant une "
                "transaction est « hors norme » (réglages de direction) ; M5 n'en suppose aucun"
            ],
        )
    limite = _dec(seuil)
    par_piece: dict[tuple[str, str], tuple[Decimal, list[str]]] = {}
    for e in d["ecritures"]:
        if e.get("contre_passe") is not None:
            continue
        total = sum((_dec(li[1]) for li in e["lignes"]), _ZERO)
        if total < limite:
            continue
        cle = (e["piece_type"], e["piece_ref"] or e["id"])
        courant = par_piece.get(cle, (_ZERO, []))
        par_piece[cle] = (max(courant[0], total), [*courant[1], e["id"]])
    constats = [
        _constat(
            "TRANSACTION_HORS_NORME",
            f"La pièce {cle[0]}:{cle[1]} passe au grand livre pour {_txt(total)} $, "
            + (
                f"atteint ou dépasse le seuil déclaré de {seuil} $."
                if len(str(seuil)) <= _SEUIL_AFFICHAGE_MAX
                else "atteint ou dépasse le seuil déclaré (valeur longue non affichée; consulter les réglages de "
                "direction)."
            ),
            [{"registre": "grand_livre", "reference": i} for i in ids],
            "Confirmer que la transaction est voulue et documentée (à confirmer, pas une erreur en soi).",
            montant=_txt(total),
        )
        for cle, (total, ids) in sorted(par_piece.items())
    ]
    return constats, "EVALUEE", []


def _facture_modifiee(d: Mapping[str, Any]) -> Resultat:
    par_cle = {e["cle"]: e for e in d["ecritures"]}
    constats: list[dict[str, Any]] = []
    attendues = {a["cle"]: a for a in d["attendues"]}
    for f in d["factures_fournisseurs"]:
        cle = f"auto:facture_fournisseur:{f['id']}:saisie"
        ecriture = par_cle.get(cle)
        if ecriture is None:
            continue
        if f["statut"] == "ANNULEE" and ecriture.get("contre_passee_par") is None:
            constats.append(
                _constat(
                    "FACTURE_MODIFIEE",
                    f"La facture fournisseur {f['numero']} a été annulée mais son écriture {ecriture['id']} existe "
                    f"encore "
                    "et n'est pas contre-passée.",
                    [
                        {"registre": "comptes_a_payer", "reference": f["id"]},
                        {"registre": "grand_livre", "reference": ecriture["id"]},
                    ],
                    "Proposer la contre-passation de l'écriture (validation humaine).",
                    outil="m5_proposer_contre_passation",
                )
            )
        elif (
            f["statut"] == "CORRIGEE"
            and cle in attendues
            and ecriture.get("contre_passee_par") is None
            and ecriture["lignes"] != attendues[cle]["lignes"]
        ):
            constats.append(
                _constat(
                    "FACTURE_MODIFIEE",
                    f"La facture fournisseur {f['numero']} a été corrigée depuis la comptabilisation : son écriture "
                    f"{ecriture['id']} ne correspond plus à la pièce courante.",
                    [
                        {"registre": "comptes_a_payer", "reference": f["id"]},
                        {"registre": "grand_livre", "reference": ecriture["id"]},
                    ],
                    "Contre-passer l'écriture d'origine et en proposer une nouvelle (validation humaine).",
                    outil="m5_proposer_contre_passation",
                )
            )
    for f in d["factures_clients"]:
        for suite in ("emission", "paiement"):
            cle = f"auto:facture_client:{f['facture_id']}:{suite}"
            ecriture, attendue = par_cle.get(cle), attendues.get(cle)
            if ecriture is None or attendue is None or ecriture.get("contre_passee_par") is not None:
                continue
            if ecriture["lignes"] != attendue["lignes"]:
                constats.append(
                    _constat(
                        "FACTURE_MODIFIEE",
                        f"L'écriture {ecriture['id']} ({suite}) de la facture {f.get('numero') or f['facture_id']} "
                        f"ne correspond "
                        "plus aux montants de la facture courante.",
                        [
                            {"registre": "factures", "reference": f["facture_id"]},
                            {"registre": "grand_livre", "reference": ecriture["id"]},
                        ],
                        "Contre-passer l'écriture et en proposer une nouvelle depuis la pièce courante (validation "
                        "humaine).",
                        outil="m5_proposer_contre_passation",
                    )
                )
    return constats, "EVALUEE", []


def _changement_de_compte(d: Mapping[str, Any]) -> Resultat:
    n = d["seuils"]["historique_changement_compte"]
    if n is None:
        return (
            [],
            "NON_EVALUEE",
            [
                "m5.historique_changement_compte non déclaré : la direction décide combien de factures de suite "
                "sur le même "
                "compte rendent un changement « inhabituel » ; M5 n'en suppose aucun"
            ],
        )
    par_fournisseur: dict[str, list[tuple[date, str, str | None, str]]] = defaultdict(list)
    for f in d["factures_fournisseurs"]:
        jour = _jour(f.get("date_facture"))
        if f["statut"] in ("SAISIE", "CORRIGEE") and jour is not None:
            par_fournisseur[_nom(f["fournisseur_id"])].append((jour, f["id"], f.get("compte_charge"), f["numero"]))
    constats = []
    for fournisseur in sorted(par_fournisseur):
        suite = sorted(par_fournisseur[fournisseur], key=lambda t: (t[0], t[1]))
        for index, (jour, ident, compte, numero) in enumerate(suite):
            if compte is None:
                continue
            precedents = [t[2] for t in suite[max(0, index - n) : index]]
            if len(precedents) < n:
                continue  # historique trop court : rien n'est « inhabituel » faute de points de comparaison
            if len(set(precedents)) == 1 and precedents[0] is not None and precedents[0] != compte:
                constats.append(
                    _constat(
                        "CHANGEMENT_COMPTE_INHABITUEL",
                        f"La facture {numero} du {jour.isoformat()} va au compte {compte} alors que les {n} "
                        f"factures précédentes "
                        f"du même fournisseur allaient au compte {precedents[0]}.",
                        [{"registre": "comptes_a_payer", "reference": ident}],
                        "Confirmer le classement avec la personne qui a saisi la facture ; si c'est une erreur, "
                        "corriger la "
                        "facture (m5_corriger_facture_fournisseur, validation humaine).",
                        outil="m5_corriger_facture_fournisseur",
                    )
                )
    return constats, "EVALUEE", []


def _piste_incomplete(d: Mapping[str, Any]) -> Resultat:
    constats: list[dict[str, Any]] = []
    chaines_invalides = {
        chaine["registre"] for chaine in d["chaines"] if chaine["ok"] is False
    }
    for chaine in d["chaines"]:
        if not chaine["ok"]:
            origine = (
                f"La source du registre {chaine['registre']} n'est pas vérifiable pour ce contrôle"
                if chaine.get("nature") == "source_non_verifiable"
                else f"La chaîne cryptographique du registre {chaine['registre']} ne se rejoue pas"
            )
            constats.append(
                _constat(
                    "PISTE_AUDIT_INCOMPLETE",
                    f"{origine} : {chaine['detail']}.",
                    [{"registre": chaine["registre"], "reference": "chaine"}],
                    (
                        "Faire examiner les sources avant ce rapprochement."
                        if chaine.get("nature") == "source_non_verifiable"
                        else (
                            "Ne rien écrire dans ce registre ; restaurer depuis la sauvegarde ou faire examiner "
                            "la chaîne par un humain."
                        )
                    ),
                )
            )
    for anomalie in d["anomalies_gl"]:
        constats.append(
            _constat(
                "PISTE_AUDIT_INCOMPLETE",
                f"Anomalie du grand livre : {anomalie}.",
                [{"registre": "grand_livre", "reference": encodage.empreinte("m5.preaudit.anomalie", anomalie)[:12]}],
                "Faire examiner le grand livre par un humain avant toute nouvelle écriture.",
            )
        )
    numerotation = d["numerotation"]
    if numerotation is not None and not numerotation["ok"]:
        for defaut in numerotation["defauts"]:
            constats.append(
                _constat(
                    "PISTE_AUDIT_INCOMPLETE",
                    f"Numérotation des factures : {defaut}.",
                    [
                        {
                            "registre": "numerotation_factures",
                            "reference": encodage.empreinte("m5.preaudit.numero", defaut)[:12],
                        }
                    ],
                    "Relire la suite avec m5_verifier_numerotation_factures ; un numéro émis ne se réutilise pas.",
                    outil="m5_verifier_numerotation_factures",
                )
            )
    if numerotation is not None:
        manque = list(numerotation.get("manque", []))
    elif "numerotation_factures" in chaines_invalides:
        manque = ["suite des numéros de facture non vérifiable (chaîne du registre altérée)"]
    else:
        manque = ["suite des numéros de facture non lue (registre absent)"]
    return constats, "PARTIELLE" if manque else "EVALUEE", manque


def _document_manquant(d: Mapping[str, Any]) -> Resultat:
    cles = {e["cle"] for e in d["ecritures"]}
    constats: list[dict[str, Any]] = []
    for f in d["factures_clients"]:
        if f["statut"] not in ("ENVOYEE", "PAYEE"):
            continue
        if f"auto:facture_client:{f['facture_id']}:emission" not in cles:
            constats.append(
                _constat(
                    "DOCUMENT_MANQUANT",
                    f"La facture {f.get('numero') or f['facture_id']} est émise mais n'a aucune écriture (ni "
                    f"brouillon) au grand livre.",
                    [{"registre": "factures", "reference": f["facture_id"]}],
                    "Générer les brouillons comptables (m5_generer_brouillons_comptables) puis les faire valider.",
                    outil="m5_generer_brouillons_comptables",
                )
            )
        if f["statut"] == "PAYEE" and f"auto:facture_client:{f['facture_id']}:paiement" not in cles:
            constats.append(
                _constat(
                    "DOCUMENT_MANQUANT",
                    f"La facture {f.get('numero') or f['facture_id']} est payée mais le paiement n'a aucune "
                    f"écriture au grand livre.",
                    [{"registre": "factures", "reference": f["facture_id"]}],
                    "Générer les brouillons comptables puis les faire valider.",
                    outil="m5_generer_brouillons_comptables",
                )
            )
    for f in d["factures_fournisseurs"]:
        if f["statut"] in ("SAISIE", "CORRIGEE") and f"auto:facture_fournisseur:{f['id']}:saisie" not in cles:
            constats.append(
                _constat(
                    "DOCUMENT_MANQUANT",
                    f"La facture fournisseur {f['numero']} est saisie mais n'a aucune écriture (ni brouillon) au "
                    f"grand livre.",
                    [{"registre": "comptes_a_payer", "reference": f["id"]}],
                    "Générer les brouillons comptables puis les faire valider.",
                    outil="m5_generer_brouillons_comptables",
                )
            )
    connues = {
        "facture_client": {f["facture_id"] for f in d["factures_clients"]},
        "facture_fournisseur": {f["id"] for f in d["factures_fournisseurs"]},
        "depense_employe": {x["id"] for x in d["depenses_employes"]},
        "note_credit": set(d["notes_credit"]),
    }
    for e in d["ecritures"]:
        if e["piece_type"] in _PIECES_VERIFIEES and e["piece_ref"] not in connues[e["piece_type"]]:
            constats.append(
                _constat(
                    "DOCUMENT_MANQUANT",
                    f"L'écriture {e['id']} cite la pièce {e['piece_type']}:{e['piece_ref']} que les registres de M5 "
                    f"ne contiennent pas.",
                    [{"registre": "grand_livre", "reference": e["id"]}],
                    "Retrouver la pièce d'origine ou faire examiner l'écriture par un humain.",
                )
            )
    for ignoree in d["pieces_illisibles"]:
        constats.append(
            _constat(
                "DOCUMENT_MANQUANT",
                f"La pièce {ignoree['reference']} est illisible pour la comptabilité ({ignoree['code']}) : aucune "
                f"écriture n'a pu en sortir.",
                [{"registre": ignoree["registre"], "reference": ignoree["reference"]}],
                "Corriger la pièce à la source (facture) ; M5 ne complète jamais un montant ou une date.",
            )
        )
    return constats, "EVALUEE", []


_REGLES: dict[str, Callable[[Mapping[str, Any]], Resultat]] = {
    "FACTURE_SANS_PAIEMENT": _facture_sans_paiement,
    "PAIEMENT_SANS_FACTURE": _paiement_sans_facture,
    "DEPENSE_SANS_RECU": _depense_sans_recu,
    "TAXE_INCOHERENTE": _taxe_incoherente,
    "DOUBLON_PROBABLE": _doublon,
    "TRANSACTION_HORS_NORME": _hors_norme,
    "FACTURE_MODIFIEE": _facture_modifiee,
    "CHANGEMENT_COMPTE_INHABITUEL": _changement_de_compte,
    "PISTE_AUDIT_INCOMPLETE": _piste_incomplete,
    "DOCUMENT_MANQUANT": _document_manquant,
}
_ORDRE_GRAVITE = {g: i for i, g in enumerate(GRAVITES)}


def controler(dossier: Mapping[str, Any]) -> dict[str, Any]:
    """Applique les dix règles au `dossier` normalisé. Rend `{constats, regles, par_regle, par_gravite, total, limites,
    recu}`. Aucune règle ne lève : une règle dont la donnée manque est « NON_EVALUEE » et dit laquelle."""
    regles: list[dict[str, Any]] = []
    constats: list[dict[str, Any]] = []
    chaines_invalides = {
        chaine["registre"]
        for chaine in dossier.get("chaines", [])
        if chaine.get("ok") is False and isinstance(chaine.get("registre"), str)
    }
    chaines_non_verifiables = {
        chaine["registre"]
        for chaine in dossier.get("chaines", [])
        if chaine.get("ok") is False
        and chaine.get("nature") == "source_non_verifiable"
        and isinstance(chaine.get("registre"), str)
    }
    for nom in REGLES:
        if _gl_altere(dossier) and nom in _REGLES_DU_GRAND_LIVRE:
            regles.append(
                {
                    "regle": nom,
                    "etat": "NON_EVALUEE",
                    "constats": None,
                    "manque": ["le grand livre est altéré (voir PISTE_AUDIT_INCOMPLETE) : aucune lecture n'est fiable"],
                }
            )
            continue
        registres_requis_invalides = [
            registre
            for registre, regles_registre in _REGLES_PAR_REGISTRE.items()
            if nom in regles_registre and registre in chaines_invalides
        ]
        if registres_requis_invalides:
            sources_crypto = sorted(set(registres_requis_invalides) - chaines_non_verifiables)
            sources_non_verifiables = sorted(set(registres_requis_invalides) & chaines_non_verifiables)
            details_sources = []
            if "operations_comptables" in sources_crypto:
                details_sources.append("registre des opérations illisible")
                sources_crypto.remove("operations_comptables")
            if sources_crypto:
                details_sources.append(f"chaîne invalide : {', '.join(sources_crypto)}")
            if sources_non_verifiables:
                details_sources.append(f"source non vérifiable : {', '.join(sources_non_verifiables)}")
            regles.append(
                {
                    "regle": nom,
                    "etat": "NON_EVALUEE",
                    "constats": None,
                    "manque": [f"{'; '.join(details_sources)} (PISTE_AUDIT_INCOMPLETE)"],
                }
            )
            continue
        trouves, etat, manque = _REGLES[nom](dossier)
        constats.extend(trouves)
        regles.append(
            {"regle": nom, "etat": etat, "constats": None if etat == "NON_EVALUEE" else len(trouves), "manque": manque}
        )
    constats.sort(key=lambda c: (_ORDRE_GRAVITE[c["gravite"]], REGLES.index(c["regle"]), c["cle"]))
    par_regle = {r["regle"]: r["constats"] for r in regles}
    evaluees = [n for n in par_regle.values() if n is not None]
    par_gravite = {g: sum(1 for c in constats if c["gravite"] == g) for g in GRAVITES}
    limites = [
        "Interprétation : « changement de compte inhabituel » vise le compte de CHARGE d'un fournisseur ; le "
        "changement de "
        "coordonnées bancaires d'un fournisseur n'est pas évaluable (M5 n'en garde aucune).",
        "Lecture seule : aucune action proposée n'est exécutée ; chaque correction passe par un outil du sas (N1 à "
        "N4).",
        "Un constat est une question posée à une personne, pas un verdict de fraude ni d'erreur.",
    ]
    resume = {
        "total": sum(evaluees) if evaluees else None,
        "par_regle": par_regle,
        "par_gravite": par_gravite,
        "regles_non_evaluees": [r["regle"] for r in regles if r["etat"] == "NON_EVALUEE"],
        "regles_partielles": [r["regle"] for r in regles if r["etat"] == "PARTIELLE"],
        "empreinte_constats": encodage.empreinte("m5.preaudit.constats.v1", [c["cle"] for c in constats]),
    }
    recu = recu_calcul.construire(
        moteur="preaudit_controle",
        version_moteur=VERSION,
        methode="Dix règles déterministes appliquées au dossier normalisé des registres ; seuils déclarés par la "
        "direction ; "
        "constats triés par gravité, règle puis clé stable.",
        precision=_PRECISION,
        parametres={"regles": list(REGLES)},
        entrees={"dossier": dict(dossier)},
        resultat=resume,
        avertissements=list(limites),
    )
    return {
        "constats": constats,
        "regles": regles,
        "par_regle": par_regle,
        "par_gravite": par_gravite,
        "total": resume["total"],
        "limites": limites,
        "recu": recu,
    }


def _gl_altere(d: Mapping[str, Any]) -> bool:
    return not d["gl_utilisable"]


def rejouer_controle(entrees: Mapping[str, Any], parametres: Mapping[str, Any]) -> dict[str, Any]:
    """Le rejeu d'un reçu de pré-audit : même dossier, mêmes constats, même empreinte (même signature que les moteurs de
    `rapports_financiers.MOTEURS`)."""
    return controler(entrees["dossier"])


def rejouer(recu: Any) -> tuple[bool, str]:
    from . import rapports_financiers

    return rapports_financiers.rejouer(recu, {"preaudit_controle": rejouer_controle})
