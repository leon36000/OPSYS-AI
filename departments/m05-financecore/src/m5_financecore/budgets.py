"""Le BUDGET déclaré par la direction (M5-RAPPORTS-1) : un registre append-only, chaîné, de versions successives.

Module pur (même règle que `facturation_jalons.py`) : aucun import d'`opsys`, aucune horloge, aucun réseau. Il reçoit un
`registre_cible` déjà construit (duck-typé : `ajouter`, `lire`), qu'`outils_rapports.py` adosse au registre durable
DÉDIÉ `budgets_declares` (aucune migration : `stockage.maillons`). Il ne nomme jamais le registre des mouvements : un
budget ne fait bouger aucun argent (`conformite.verifier_aucun_decaissement`).

Règle d'or : un budget n'est JAMAIS supposé, calculé ni repris de l'an passé. Il est DÉCLARÉ par une personne (N3,
propriétaire ou finance), ligne par ligne : un compte de produits ou de charges du plan comptable, un mois, un montant
au cent. Absent, le budget contre réel refuse et dit quoi déclarer (`REJ-BUDGET-A-DECLARER`).

Versions : chaque déclaration est une VERSION COMPLÈTE qui remplace la précédente (jamais une retouche en place : le
passé reste lisible). La première n'a pas de motif ; les suivantes en exigent un. Déclarer deux fois le même contenu ne
crée rien (idempotent). Aucun montant n'est arrondi : un montant à plus de deux décimales est refusé.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import encodage, verdicts_rapports

__all__ = [
    "LIGNES_MAX",
    "MOIS_MAX",
    "ajouter_budget",
    "budget_actif",
    "construire_budget",
    "etat_budgets",
    "mois_entre",
    "refus_anomalies",
]

_TYPE_BUDGET = "budget_declare"
LIGNES_MAX = 1500
MOIS_MAX = 36
_MOTIF_MAX = 300
_LIBELLE_MAX = 80
_MONTANT_MAX = Decimal("999999999999.99")
_MOIS = re.compile(r"(\d{4})-(\d{2})", re.ASCII)
_MONTANT = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?", re.ASCII)
_TYPES_BUDGETABLES = ("produits", "charges")


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_rapports.construire_verdict(code, detail=detail)


def _mois_valide(brut: Any) -> tuple[int, int] | None:
    correspondance = _MOIS.fullmatch(brut) if isinstance(brut, str) else None
    if correspondance is None:
        return None
    annee, mois = int(correspondance.group(1)), int(correspondance.group(2))
    return (annee, mois) if 1900 <= annee <= 2999 and 1 <= mois <= 12 else None


def mois_entre(debut: str, fin: str) -> list[str] | None:
    """Les mois `AAAA-MM` de `debut` à `fin` inclus, dans l'ordre ; `None` si un mois est illisible ou inversé."""
    d, f = _mois_valide(debut), _mois_valide(fin)
    if d is None or f is None:
        return None
    indice_d, indice_f = d[0] * 12 + d[1] - 1, f[0] * 12 + f[1] - 1
    if indice_f < indice_d:
        return None
    return [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(indice_d, indice_f + 1)]


def _texte_borne(valeur: Any, maximum: int) -> str | None:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum or "\n" in valeur or "\r" in valeur:
        return None
    return valeur.strip()


def normaliser_lignes(
    lignes: Any, plan: Mapping[str, Any]
) -> tuple[list[dict[str, str]] | None, dict[str, str] | None]:
    """Les lignes déclarées (`compte`, `mois`, `montant`) validées contre le plan comptable EFFECTIF, triées
    (compte, mois). Un compte inconnu, désactivé ou de bilan, un mois illisible, un montant négatif, non décimal, à plus
    de deux décimales ou démesuré, un couple compte/mois en double : un refus, jamais une correction."""
    if not isinstance(lignes, Sequence) or isinstance(lignes, (str, bytes)) or not lignes:
        return None, _verdict("REJ-BUDGET-ENTREE-INVALIDE", "lignes : une liste non vide de {compte, mois, montant}")
    if len(lignes) > LIGNES_MAX:
        return None, _verdict("REJ-BUDGET-ENTREE-INVALIDE", f"lignes : au plus {LIGNES_MAX} lignes par déclaration")
    vues: set[tuple[str, str]] = set()
    resultat: list[dict[str, str]] = []
    for index, ligne in enumerate(lignes):
        if not isinstance(ligne, Mapping) or set(ligne) != {"compte", "mois", "montant"}:
            return None, _verdict(
                "REJ-BUDGET-ENTREE-INVALIDE", f"ligne {index + 1} : exactement les champs compte, mois et montant"
            )
        compte, mois, montant = ligne["compte"], ligne["mois"], ligne["montant"]
        fiche = plan["comptes"].get(compte) if isinstance(compte, str) else None
        if fiche is None:
            return None, _verdict("REJ-BUDGET-COMPTE-INVALIDE", f"ligne {index + 1} : compte {compte!r} absent du plan")
        if not fiche["actif"]:
            return None, _verdict(
                "REJ-BUDGET-COMPTE-INVALIDE", f"ligne {index + 1} : le compte {compte} ({fiche['nom']}) est désactivé"
            )
        if fiche["type"] not in _TYPES_BUDGETABLES:
            return None, _verdict(
                "REJ-BUDGET-COMPTE-INVALIDE",
                f"ligne {index + 1} : le compte {compte} ({fiche['nom']}) est de type {fiche['type']} : un budget "
                "porte sur des comptes de produits ou de charges seulement",
            )
        if _mois_valide(mois) is None:
            return None, _verdict("REJ-BUDGET-MOIS-INVALIDE", f"ligne {index + 1} : mois {mois!r} (AAAA-MM exigé)")
        if not isinstance(montant, str) or _MONTANT.fullmatch(montant) is None:
            return None, _verdict(
                "REJ-BUDGET-MONTANT-INVALIDE",
                f"ligne {index + 1} : montant {montant!r} (texte décimal au cent, positif ou nul, jamais arrondi)",
            )
        try:
            valeur = Decimal(montant)
        except InvalidOperation:  # pragma: no cover — la forme est déjà contrôlée
            return None, _verdict("REJ-BUDGET-MONTANT-INVALIDE", f"ligne {index + 1} : montant illisible")
        if valeur > _MONTANT_MAX:
            return None, _verdict("REJ-BUDGET-MONTANT-INVALIDE", f"ligne {index + 1} : montant démesuré")
        if (compte, mois) in vues:
            return None, _verdict(
                "REJ-BUDGET-LIGNE-DOUBLE", f"le couple compte {compte} / mois {mois} est déclaré deux fois"
            )
        vues.add((compte, mois))
        resultat.append(
            {
                "compte": compte,
                "mois": mois,
                "montant": format(valeur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
            }
        )
    resultat.sort(key=lambda ligne: (ligne["compte"], ligne["mois"]))
    mois_distincts = sorted({ligne["mois"] for ligne in resultat})
    etendue = mois_entre(mois_distincts[0], mois_distincts[-1]) or []
    if len(etendue) > MOIS_MAX:
        return None, _verdict("REJ-BUDGET-MOIS-INVALIDE", f"un budget couvre au plus {MOIS_MAX} mois d'étendue")
    return resultat, None


def _empreinte_contenu(lignes: Sequence[Mapping[str, str]], libelle: str, plan_version: str) -> str:
    return encodage.empreinte(
        "m5.budget.contenu.v1",
        {"lignes": [dict(ligne) for ligne in lignes], "libelle": libelle, "plan_comptable_version": plan_version},
    )


def construire_budget(
    lignes: Any,
    libelle: Any,
    plan: Mapping[str, Any],
    *,
    humain: Mapping[str, str],
    version: int,
    motif: Any,
    remplace: str | None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le corps d'une version de budget (sans `type_entree` ni horodatage), ou le refus nommé. La première version n'a
    pas de motif ; une version qui en remplace une autre en exige un (`REJ-BUDGET-MOTIF-REQUIS`)."""
    normalisees, refus = normaliser_lignes(lignes, plan)
    if refus is not None:
        return None, refus
    nom = _texte_borne(libelle, _LIBELLE_MAX)
    if nom is None:
        return None, _verdict("REJ-BUDGET-ENTREE-INVALIDE", f"libelle : une ligne de {_LIBELLE_MAX} caractères au plus")
    texte_motif = None
    if remplace is not None:
        texte_motif = _texte_borne(motif, _MOTIF_MAX)
        if texte_motif is None:
            return None, _verdict(
                "REJ-BUDGET-MOTIF-REQUIS",
                f"remplacer le budget déclaré exige un motif (une ligne, {_MOTIF_MAX} caractères)",
            )
    mois = sorted({ligne["mois"] for ligne in normalisees})
    empreinte = _empreinte_contenu(normalisees, nom, plan["version_effective"])
    return {
        "budget_id": "bud-" + empreinte[:20],
        "version": version,
        "libelle": nom,
        "mois_debut": mois[0],
        "mois_fin": mois[-1],
        "lignes": normalisees,
        "plan_comptable_version": plan["version_effective"],
        "motif": texte_motif,
        "remplace": remplace,
        "declare_par": dict(humain),
        "empreinte_budget": empreinte,
    }, None


def etat_budgets(maillons: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """L'état relu du registre : `versions` (dans l'ordre d'écriture, la dernière fait foi) et `anomalies` (maillon
    étranger ou illisible, contenu altéré, numéro de version qui saute, remplacement d'un autre que le précédent).
    Une anomalie fait refuser toute lecture : jamais un budget retouché à la main."""
    versions: list[dict[str, Any]] = []
    anomalies: list[str] = []
    for maillon in maillons:
        type_entree = maillon.get("type_entree") if isinstance(maillon, Mapping) else None
        try:
            if type_entree != _TYPE_BUDGET:
                anomalies.append(f"maillon de type {type_entree!r} étranger aux budgets")
                continue
            attendu = _empreinte_contenu(maillon["lignes"], maillon["libelle"], maillon["plan_comptable_version"])
            if maillon["empreinte_budget"] != attendu or maillon["budget_id"] != "bud-" + attendu[:20]:
                anomalies.append(f"budget {maillon.get('budget_id')!r} : contenu altéré")
            elif maillon["version"] != len(versions) + 1:
                anomalies.append(f"budget {maillon['budget_id']} : version {maillon['version']} hors suite")
            elif maillon["remplace"] != (versions[-1]["budget_id"] if versions else None):
                anomalies.append(f"budget {maillon['budget_id']} : ne remplace pas la version précédente")
            else:
                versions.append(dict(maillon))
        except (KeyError, TypeError):
            anomalies.append(f"maillon {type_entree!r} illisible")
    return {"versions": versions, "anomalies": anomalies}


def refus_anomalies(etat: Mapping[str, Any]) -> dict[str, str] | None:
    if etat["anomalies"]:
        return _verdict("REJ-RAPPORT-CHAINE-INVALIDE", "budgets : " + "; ".join(etat["anomalies"][:3]))
    return None


def budget_actif(etat: Mapping[str, Any]) -> dict[str, Any] | None:
    """La dernière version déclarée, ou `None` : aucun budget n'a été déclaré."""
    return etat["versions"][-1] if etat["versions"] else None


def ajouter_budget(
    registre_cible: Any, etat: Mapping[str, Any], corps: Mapping[str, Any], horodatage: str
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Écrit la version, ou reconnaît le budget déjà actif de même contenu (rien n'est écrit)."""
    actif = budget_actif(etat)
    if actif is not None and actif["empreinte_budget"] == corps["empreinte_budget"]:
        return {"statut": "deja", "budget": actif}, None
    ligne_id = registre_cible.ajouter({"type_entree": _TYPE_BUDGET, **dict(corps), "horodatage": horodatage})
    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return {"statut": "ecrit", "budget": maillon}, None
    raise RuntimeError("maillon du budget ajouté introuvable")
