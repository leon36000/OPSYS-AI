"""Plan comptable du grand livre M5 (tranche 1) : le plan par défaut versionné, étendu par le client.

Module pur (ADR-0009, même règle que `taux_fiscaux.py`) : aucun import d'`opsys`, aucune horloge. Le plan de base vit
dans `contracts/plan_comptable_pme_qc.v1.yaml` ; le client AJOUTE des comptes ou en DÉSACTIVE par
`department.yaml/configuration.grand_livre` (`comptes_ajoutes`, `comptes_desactives`), relu à chaque appel. Rien n'est
retiré : un compte désactivé reste lisible (les écritures déjà passées gardent leur compte), mais aucune nouvelle
écriture ne peut le mouvementer (`REJ-GL-COMPTE-INACTIF`). Un compte absent du plan effectif est
`REJ-GL-COMPTE-INCONNU`.

La version EFFECTIVE du plan (`version_effective`) est la version du fichier, suivie de l'empreinte de l'extension du
client quand il y en a une : deux extensions différentes ne portent jamais la même version, et chaque écriture du grand
livre garde la version sous laquelle elle a été proposée.

Numérotation imposée par le type (contrôlée, pour qu'un compte ajouté ne se range pas au mauvais endroit des états) :
1xxx actif, 2xxx passif, 3xxx capitaux propres, 4xxx produits, 5xxx à 9xxx charges. Actif et charges ont un solde
normal débiteur ; passif, capitaux propres et produits, créditeur.

CORRESPONDANCE DES CHARGES (version `2026-v2`, `correspondance_charges` du fichier) : le compte de charge d'une facture
fournisseur, DÉCLARÉ et jamais supposé. Une facture sans PO va au compte de sa catégorie de dépense
(`categories_depense`, mêmes noms que `configuration.categories_depense_sans_po`) ; une facture sur PO au compte
`factures_sur_po`. Chaque compte visé existe au plan EFFECTIF, y est actif et de type charges, sinon le plan est refusé
au chargement (`REJ-GL-CORRESPONDANCE-INVALIDE`) : jamais une facture rangée dans un compte inconnu, désactivé
ou d'actif. Le client ajoute ou redirige des catégories (`correspondance_charges` de son extension) et en retire
(`categories_depense_retirees`) ; une catégorie absente de la correspondance n'a pas de compte (`compte_de_charge` le
dit, `REJ-GL-CATEGORIE-SANS-COMPTE`). Comptes proposés à valider par le CPA.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from . import comptes_a_payer, encodage, verdicts_grand_livre

__all__ = ["charger_plan", "appliquer_extension", "compte_utilisable", "compte_de_charge", "sens_normal"]

_TYPES_PAR_PREMIER_CHIFFRE = {
    "1": "actif",
    "2": "passif",
    "3": "capitaux_propres",
    "4": "produits",
    "5": "charges",
    "6": "charges",
    "7": "charges",
    "8": "charges",
    "9": "charges",
}
_TYPES_DEBITEURS = frozenset({"actif", "charges"})
_TYPES_CONNUS = frozenset(_TYPES_PAR_PREMIER_CHIFFRE.values())
_NUMERO = re.compile(r"^[1-9][0-9]{3}$")
_ROLES_REQUIS = frozenset({
    "banque", "comptes_clients", "produits_services", "tps_a_percevoir", "tvq_a_percevoir",
})
_LONGUEUR_NOM_MAX = 120
# Les rôles qu'un brouillon de facture fournisseur mouvemente, exigés dès qu'une correspondance est déclarée.
_ROLES_FOURNISSEURS = frozenset({"comptes_fournisseurs", "tps_cti", "tvq_rti"})
_CLES_CORRESPONDANCE = frozenset({"factures_sur_po", "categories_depense"})
_CORRESPONDANCE_VIDE = {"factures_sur_po": None, "categories_depense": {}}


def _refus(detail: str) -> tuple[None, dict[str, str]]:
    return None, verdicts_grand_livre.construire_verdict("REJ-GL-PLAN-INVALIDE", detail=detail)


def _refus_correspondance(detail: str) -> tuple[None, dict[str, str]]:
    return None, verdicts_grand_livre.construire_verdict("REJ-GL-CORRESPONDANCE-INVALIDE", detail=detail)


def _lire_correspondance(brut: Any, origine: str) -> tuple[dict[str, Any] | None, str | None]:
    """La forme d'une correspondance (`{factures_sur_po: numéro, categories_depense: {catégorie: numéro}}`, chaque clé
    optionnelle) : `(correspondance, None)` ou `(None, raison)`. Les noms de catégorie suivent la règle de la liste
    fermée des comptes à payer (`comptes_a_payer.lire_categories_depense`) ; les comptes ne sont vérifiés qu'ensuite,
    contre le plan effectif (`_verifier_correspondance`)."""
    if not isinstance(brut, Mapping) or not set(brut) <= _CLES_CORRESPONDANCE:
        return None, f"{origine} : correspondance_charges n'a que factures_sur_po et categories_depense"
    sur_po = brut.get("factures_sur_po")
    if sur_po is not None and not isinstance(sur_po, str):
        return None, f"{origine} : factures_sur_po est un numéro de compte en texte, ex. \"5100\""
    categories = brut.get("categories_depense") or {}
    if not isinstance(categories, Mapping):
        return None, f"{origine} : categories_depense associe chaque catégorie à un numéro de compte"
    if categories:
        _noms, refus = comptes_a_payer.lire_categories_depense(list(categories))
        if refus is not None:
            return None, f"{origine} : {refus['detail']}"
    for categorie, numero in categories.items():
        if not isinstance(numero, str):
            return None, f"{origine} : la catégorie {categorie!r} vise {numero!r}, pas un numéro de compte en texte"
    return {"factures_sur_po": sur_po, "categories_depense": dict(categories)}, None


def _verifier_correspondance(correspondance: Mapping[str, Any], comptes: Mapping[str, Any]) -> str | None:
    """`None` si chaque compte visé existe, est actif et de type charges dans `comptes` ; sinon la première raison."""
    cibles = [("factures_sur_po", correspondance["factures_sur_po"])] if correspondance["factures_sur_po"] else []
    cibles += [(f"catégorie {c!r}", n) for c, n in sorted(correspondance["categories_depense"].items())]
    for quoi, numero in cibles:
        compte = comptes.get(numero)
        if compte is None:
            return f"{quoi} vise le compte {numero!r}, absent du plan"
        if not compte["actif"]:
            return f"{quoi} vise le compte {numero} ({compte['nom']}), désactivé : rediriger ou retirer l'entrée"
        if compte["type"] != "charges":
            return f"{quoi} vise le compte {numero} ({compte['nom']}), de type {compte['type']}, pas charges"
    return None


def compte_de_charge(
    plan: Mapping[str, Any], *, po_id: Any, categorie: Any
) -> tuple[str | None, dict[str, str] | None]:
    """Le compte de charge d'une facture fournisseur sous `plan` : `factures_sur_po` pour une facture sur PO, celui de
    sa catégorie pour une facture sans PO ; sinon `REJ-GL-CATEGORIE-SANS-COMPTE` (jamais un compte par défaut)."""
    correspondance = plan.get("correspondance_charges") or _CORRESPONDANCE_VIDE
    if po_id is not None:
        numero = correspondance["factures_sur_po"]
        quoi = "facture sur PO : factures_sur_po"
    else:
        numero = correspondance["categories_depense"].get(categorie) if isinstance(categorie, str) else None
        quoi = f"catégorie de dépense {categorie!r}"
    if numero is None:
        return None, verdicts_grand_livre.construire_verdict(
            "REJ-GL-CATEGORIE-SANS-COMPTE",
            detail=f"{quoi} sans compte de charge déclaré au plan {plan['version_effective']} : déclarer la "
                   "correspondance (configuration.grand_livre.correspondance_charges), rien n'est supposé",
        )
    return numero, None


def _compte_valide(brut: Any, origine: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(brut, Mapping) or set(brut) != {"numero", "nom", "type"}:
        return None, f"{origine} : un compte a exactement numero, nom, type"
    numero, nom, type_compte = brut["numero"], brut["nom"], brut["type"]
    if not isinstance(numero, str) or not _NUMERO.match(numero):
        return None, f"{origine} : numéro {numero!r} invalide (quatre chiffres en texte, ex. \"5450\")"
    if not isinstance(nom, str) or not nom.strip() or len(nom) > _LONGUEUR_NOM_MAX:
        return None, f"{origine} : nom du compte {numero} vide ou trop long"
    if type_compte not in _TYPES_CONNUS:
        return None, f"{origine} : type {type_compte!r} du compte {numero} inconnu"
    if _TYPES_PAR_PREMIER_CHIFFRE[numero[0]] != type_compte:
        return None, (
            f"{origine} : le compte {numero} est un compte de {_TYPES_PAR_PREMIER_CHIFFRE[numero[0]]}, "
            f"pas de {type_compte}"
        )
    return {"numero": numero, "nom": nom.strip(), "type": type_compte, "actif": True, "origine": origine}, None


def charger_plan(chemin: str | Path) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le plan de base du fichier versionné : `{plan_id, version, source, comptes: {numero: compte}, roles}`, ou le
    refus `REJ-GL-PLAN-INVALIDE` qui dit ce qui ne va pas (jamais un plan partiel)."""
    try:
        contenu = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return _refus(f"plan comptable illisible : {type(exc).__name__}")
    if not isinstance(contenu, Mapping) or contenu.get("schema_version") != 1:
        return _refus("schema_version 1 attendu")
    for champ in ("plan_id", "version", "source"):
        if not isinstance(contenu.get(champ), str) or not contenu[champ].strip():
            return _refus(f"champ {champ!r} absent ou vide")
    comptes_bruts = contenu.get("comptes")
    if not isinstance(comptes_bruts, list) or not comptes_bruts:
        return _refus("liste de comptes absente")
    comptes: dict[str, dict[str, Any]] = {}
    for brut in comptes_bruts:
        compte, erreur = _compte_valide(brut, "plan")
        if erreur is not None:
            return _refus(erreur)
        if compte["numero"] in comptes:
            return _refus(f"compte {compte['numero']} déclaré deux fois")
        comptes[compte["numero"]] = compte
    roles = contenu.get("roles")
    if not isinstance(roles, Mapping) or not set(roles) >= _ROLES_REQUIS:
        return _refus(f"rôles requis : {sorted(_ROLES_REQUIS)}")
    for role, numero in roles.items():
        if numero not in comptes:
            return _refus(f"le rôle {role!r} vise le compte {numero!r}, absent du plan")
    correspondance = dict(_CORRESPONDANCE_VIDE)
    if contenu.get("correspondance_charges") is not None:
        correspondance, erreur = _lire_correspondance(contenu["correspondance_charges"], "plan")
        if erreur is None and not set(roles) >= _ROLES_FOURNISSEURS:
            erreur = f"plan : une correspondance des charges exige les rôles {sorted(_ROLES_FOURNISSEURS)}"
        erreur = erreur or _verifier_correspondance(correspondance, comptes)
        if erreur is not None:
            return _refus_correspondance(erreur)
    return {
        "plan_id": contenu["plan_id"],
        "version": contenu["version"],
        "version_effective": contenu["version"],
        "source": contenu["source"],
        "comptes": comptes,
        "roles": dict(roles),
        "correspondance_charges": correspondance,
    }, None


def appliquer_extension(
    plan: Mapping[str, Any], extension: Any
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le plan effectif : le plan de base, plus les comptes que le client AJOUTE, moins (désactivés) ceux qu'il
    DÉSACTIVE, et la correspondance des charges que le client complète (`correspondance_charges` : catégories ajoutées
    ou redirigées, `factures_sur_po` redirigé) ou réduit (`categories_depense_retirees`). `extension` est
    `configuration.grand_livre` du manifeste (absente : `None`, le plan de base tel quel). Un ajout qui reprend un
    numéro existant, une désactivation d'un compte inconnu, une clé inconnue ou une forme invalide est refusé en entier
    (`REJ-GL-PLAN-INVALIDE`) ; une correspondance qui viserait alors un compte inconnu, désactivé ou hors des charges,
    ou qui retire une catégorie absente, aussi (`REJ-GL-CORRESPONDANCE-INVALIDE`) : jamais une extension appliquée à
    moitié."""
    base_correspondance = plan.get("correspondance_charges") or _CORRESPONDANCE_VIDE
    if extension is None:
        return {**plan, "comptes": {n: dict(c) for n, c in plan["comptes"].items()},
                "correspondance_charges": {**base_correspondance,
                                           "categories_depense": dict(base_correspondance["categories_depense"])}}, None
    permises = {"comptes_ajoutes", "comptes_desactives", "correspondance_charges", "categories_depense_retirees"}
    if not isinstance(extension, Mapping) or not set(extension) <= permises:
        return _refus("configuration.grand_livre : seules comptes_ajoutes, comptes_desactives, "
                      "correspondance_charges et categories_depense_retirees sont permises")
    ajoutes = extension.get("comptes_ajoutes") or []
    desactives = extension.get("comptes_desactives") or []
    if not isinstance(ajoutes, list) or not isinstance(desactives, list):
        return _refus("configuration.grand_livre : comptes_ajoutes et comptes_desactives sont des listes")
    comptes = {n: dict(c) for n, c in plan["comptes"].items()}
    for brut in ajoutes:
        compte, erreur = _compte_valide(brut, "client")
        if erreur is not None:
            return _refus(erreur)
        if compte["numero"] in comptes:
            return _refus(f"compte ajouté {compte['numero']} : ce numéro existe déjà au plan")
        comptes[compte["numero"]] = compte
    vus: set[str] = set()
    for numero in desactives:
        if not isinstance(numero, str) or numero not in comptes:
            return _refus(f"compte désactivé {numero!r} : inconnu du plan")
        if numero in vus:
            return _refus(f"compte désactivé {numero!r} répété")
        vus.add(numero)
        comptes[numero]["actif"] = False
    correspondance, refus = _correspondance_etendue(base_correspondance, extension, comptes)
    if refus is not None:
        return None, refus
    forme: dict[str, Any] = {"comptes_ajoutes": ajoutes, "comptes_desactives": desactives}
    for cle in ("correspondance_charges", "categories_depense_retirees"):
        if extension.get(cle):
            forme[cle] = extension[cle]
    version = plan["version"]
    if ajoutes or desactives or len(forme) > 2:
        version = f"{plan['version']}+client.{encodage.empreinte(forme)[:12]}"
    return {**plan, "comptes": comptes, "version_effective": version, "correspondance_charges": correspondance}, None


def _correspondance_etendue(
    base: Mapping[str, Any], extension: Mapping[str, Any], comptes: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """La correspondance du plan EFFECTIF : la base, moins les catégories retirées, plus celles que le client ajoute
    ou redirige, puis vérifiée contre les comptes effectifs (désactiver un compte encore visé est refusé)."""
    retirees = extension.get("categories_depense_retirees") or []
    if not isinstance(retirees, list):
        return _refus_correspondance("categories_depense_retirees est une liste de catégories")
    ajout, erreur = _lire_correspondance(extension.get("correspondance_charges") or {}, "client")
    if erreur is not None:
        return _refus_correspondance(erreur)
    categories = dict(base["categories_depense"])
    for categorie in retirees:
        if not isinstance(categorie, str) or categorie not in categories:
            return _refus_correspondance(f"catégorie retirée {categorie!r} : absente de la correspondance de base")
        if categorie in ajout["categories_depense"]:
            return _refus_correspondance(f"catégorie {categorie!r} à la fois retirée et redirigée")
        del categories[categorie]
    categories.update(ajout["categories_depense"])
    correspondance = {"factures_sur_po": ajout["factures_sur_po"] or base["factures_sur_po"],
                      "categories_depense": categories}
    erreur = _verifier_correspondance(correspondance, comptes)
    if erreur is not None:
        return _refus_correspondance(erreur)
    return correspondance, None


def compte_utilisable(plan: Mapping[str, Any], numero: Any) -> dict[str, str] | None:
    """`None` si une nouvelle écriture peut mouvementer ce compte ; sinon le refus nommé (inconnu, inactif)."""
    compte = plan["comptes"].get(numero) if isinstance(numero, str) else None
    if compte is None:
        return verdicts_grand_livre.construire_verdict(
            "REJ-GL-COMPTE-INCONNU", detail=f"compte {numero!r} absent du plan comptable {plan['version_effective']}"
        )
    if not compte["actif"]:
        return verdicts_grand_livre.construire_verdict(
            "REJ-GL-COMPTE-INACTIF", detail=f"compte {numero} ({compte['nom']}) désactivé par le client"
        )
    return None


def sens_normal(type_compte: str) -> str:
    """« debiteur » pour l'actif et les charges, « crediteur » pour le passif, les capitaux propres et les produits."""
    return "debiteur" if type_compte in _TYPES_DEBITEURS else "crediteur"
