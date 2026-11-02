"""Aides communes aux tests des réglages de direction (CFG-1) : instance fictive, personnes, geste par le sas N3.

Importé par chemin (`importlib.util.spec_from_file_location`) comme les autres aides de `tests/`. Données fictives.
"""

from __future__ import annotations

from typing import Any

import yaml

from opsys import approbations, identite, stockage
from opsys.departements import charger_departements
from opsys.outils import Niveau

FICTIF = True
M9 = "m09-strategic-intelligence"
MOT_DE_PASSE = "mot-de-passe-fictif-reglages-1"
PROPRIETAIRE = "owner.fictif"
ADMIN = "admin.fictif"
EMPLOYE = "employe.fictif"
ADOPTER = "m9_adopter_reglage"
REVENIR = "m9_revenir_sur_reglage"


def installer(tmp_path, monkeypatch) -> dict[str, Any]:
    """Base SQLite migrée, personnes fictives (propriétaire, administrateur seul, employé) et départements chargés."""
    url = f"sqlite:///{tmp_path / 'reglages.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.liberer()
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, PROPRIETAIRE, "Propriétaire fictif", MOT_DE_PASSE, ["nathan_owner", "admin"])
        identite.creer_personne(cnx, ADMIN, "Admin fictif", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, EMPLOYE, "Employé fictif", MOT_DE_PASSE, ["employee"])
    return charger_departements()


def outil_m9(deps, nom: str):
    return next(o for o in deps[M9].charger_outils() if o.nom == nom)


def decider(cnx, deps, nom: str, arguments: dict[str, Any], *, par: str = PROPRIETAIRE, role: str | None = None,
            niveau: Niveau = Niveau.N3, approuver: bool = True) -> dict[str, Any]:
    """Dépose la demande N3 d'un outil de réglage et la décide : la voie de la console et de la CLI."""
    outil = outil_m9(deps, nom)
    ident = approbations.creer_demande(cnx, M9, nom, arguments, niveau=niveau)
    return approbations.decider(cnx, ident, approuver, par, {nom: outil}, deps, role=role)


def adopter(cnx, deps, cle: str, valeur: Any, raison: str = "Décision de départ de la direction",
            **plus) -> dict[str, Any]:
    arguments = {"cle": cle, "valeur": valeur, "raison": raison, **plus}
    return decider(cnx, deps, ADOPTER, arguments, role="nathan_owner")


def revenir(cnx, deps, cle: str, raison: str = "Retour au point de départ", **plus) -> dict[str, Any]:
    return decider(cnx, deps, REVENIR, {"cle": cle, "raison": raison, **plus}, role="nathan_owner")


def resultat(decision: dict[str, Any]) -> dict[str, Any]:
    """Le résultat métier d'une décision exécutée ; échoue clairement si le geste a été refusé."""
    assert decision["statut"] == "executee", decision
    return decision["reponse"]["resultat"]["resultat"]


def refus(decision: dict[str, Any]) -> str:
    """Le texte du refus d'un geste exécuté en échec."""
    assert decision["statut"] == "echec", decision
    return str(decision["reponse"].get("details", ""))


def chaine() -> list[dict[str, Any]]:
    from opsys.reglages import magasin

    with stockage.transaction():
        return magasin.lire_chaine()


def manifeste_avec(tmp_path, departement: str, modifier) -> Any:
    """Copie le `department.yaml` réel d'un département, appliquée à `modifier(donnees)`, vers un dossier fictif.

    Rend le chemin du fichier modifié ; sert aux tests de précédence (valeur du fichier) sans toucher au dépôt."""
    from opsys.departements import racine_departements

    donnees = yaml.safe_load((racine_departements() / departement / "department.yaml").read_text(encoding="utf-8"))
    modifier(donnees)
    chemin = tmp_path / f"{departement}.yaml"
    chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return chemin
