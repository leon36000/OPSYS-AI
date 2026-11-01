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
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from . import encodage, verdicts_grand_livre

__all__ = ["charger_plan", "appliquer_extension", "compte_utilisable", "sens_normal"]

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


def _refus(detail: str) -> tuple[None, dict[str, str]]:
    return None, verdicts_grand_livre.construire_verdict("REJ-GL-PLAN-INVALIDE", detail=detail)


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
    return {
        "plan_id": contenu["plan_id"],
        "version": contenu["version"],
        "version_effective": contenu["version"],
        "source": contenu["source"],
        "comptes": comptes,
        "roles": dict(roles),
    }, None


def appliquer_extension(
    plan: Mapping[str, Any], extension: Any
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le plan effectif : le plan de base, plus les comptes que le client AJOUTE, moins (désactivés) ceux qu'il
    DÉSACTIVE. `extension` est `configuration.grand_livre` du manifeste (absente : `None`, le plan de base tel quel).
    Un ajout qui reprend un numéro existant, une désactivation d'un compte inconnu, une clé inconnue ou une forme
    invalide est refusé en entier (`REJ-GL-PLAN-INVALIDE`) : jamais une extension appliquée à moitié."""
    if extension is None:
        return {**plan, "comptes": {n: dict(c) for n, c in plan["comptes"].items()}}, None
    if not isinstance(extension, Mapping) or not set(extension) <= {"comptes_ajoutes", "comptes_desactives"}:
        return _refus("configuration.grand_livre : seules comptes_ajoutes et comptes_desactives sont permises")
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
    forme = {"comptes_ajoutes": ajoutes, "comptes_desactives": desactives}
    version = plan["version"]
    if ajoutes or desactives:
        version = f"{plan['version']}+client.{encodage.empreinte(forme)[:12]}"
    return {**plan, "comptes": comptes, "version_effective": version}, None


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
