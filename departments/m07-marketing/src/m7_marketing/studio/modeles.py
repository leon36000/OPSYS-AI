"""Sélection du modèle par le registre de fournisseurs existant, sous le moteur de politique de licence.

Rien n'est recopié de `opsys.fournisseurs` : ce module appelle `registre.resoudre` (sélection du département, sinon
défaut global ; un fournisseur inactif ou devenu non conforme est un REFUS, jamais un repli sur un autre) et
`politique.evaluer`, puis fige l'INSTANTANÉ de licence qui entre au journal de provenance : bloc de licence du modèle,
verdict de la politique, empreinte (et révision) du profil du client. Le profil lui-même — revenu déclaré compris —
n'est
pas recopié : un agent qui lit la provenance ne doit pas lire le chiffre d'affaires de l'entreprise.

La licence est revérifiée à chaque étape qui compte (génération, contrôle qualité, revue) : `verdict_courant` rend le
verdict d'AUJOURD'HUI pour le fournisseur qui a produit un fond (un revenu passé au-dessus d'un seuil, un territoire
ajouté, une désactivation l'invalident).

La matrice des licences des modèles par défaut (`matrice_licences_defaut`) est tirée du catalogue (R5 §1.1 et §2.1) ; la
documentation la reprend et un test la compare.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from typing import Any

from sqlalchemy import Connection

from opsys.fournisseurs import catalogue, politique, registre
from opsys.fournisseurs.modele import Fournisseur
from opsys.fournisseurs.registre import RegistreErreur

CAPACITES = ("image", "video")
DEPARTEMENT = "m07-marketing"
PREFIXE_REFUS = "REJ-STUDIO-MODELE-"
REJ_CAPACITE = "REJ-STUDIO-MODELE-CAPACITE"


class ModeleRefuse(ValueError):
    """Aucun modèle utilisable : le code reprend celui du registre (`REJ-STUDIO-MODELE-<code>`), sans repli."""

    def __init__(self, code: str, detail: str, refus: tuple[str, ...] = ()) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail, self.refus = code, detail, refus


@dataclasses.dataclass(frozen=True)
class SelectionModele:
    fournisseur: Fournisseur
    portee: str
    decision: politique.Decision
    profil_empreinte: str
    profil_revision: int | None

    def instantane(self, maintenant: dt.datetime) -> dict[str, Any]:
        """Ce qui entre au journal de provenance (JSON natif, sans secret ni revenu)."""
        f = self.fournisseur
        return {
            "fournisseur_id": f.identifiant,
            "modele": f.modele,
            "capacite": f.capacite,
            "mode": f.mode,
            "portee": self.portee,
            "statut_catalogue": f.statut_catalogue,
            "qualification": f.qualification,
            "residence_donnees": f.residence_donnees,
            "licence": f.licence.vers_json(),
            "mention_obligatoire": f.licence.mention_obligatoire,
            "decision": self.decision.vers_json(),
            "profil_empreinte": self.profil_empreinte,
            "profil_revision": self.profil_revision,
            "verifie_le": maintenant.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def _empreinte_profil(profil: politique.ProfilClient | None) -> str:
    texte = json.dumps(profil.vers_json() if profil else None, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(("opsys-profil-licence/v1\n" + texte).encode("utf-8")).hexdigest()


def selectionner(cnx: Connection, capacite: str, departement: str = DEPARTEMENT) -> SelectionModele:
    """Le modèle du département pour `capacite`, ou `ModeleRefuse` (aucun repli, jamais un autre modèle)."""
    if capacite not in CAPACITES:
        raise ModeleRefuse(REJ_CAPACITE, f"capacité du studio : {list(CAPACITES)}")
    try:
        resolution = registre.resoudre(cnx, capacite, departement)
    except RegistreErreur as exc:
        raise ModeleRefuse(PREFIXE_REFUS + exc.code, exc.detail, exc.codes) from None
    profil = registre.lire_profil(cnx)
    decision = politique.evaluer(resolution.fournisseur, profil)
    if not decision.conforme:  # ceinture : `resoudre` a déjà refusé
        raise ModeleRefuse(PREFIXE_REFUS + "REFUS_POLITIQUE", "modèle non conforme au profil du client", decision.codes)
    brut = registre.profil_brut(cnx)
    return SelectionModele(
        resolution.fournisseur,
        resolution.portee,
        decision,
        _empreinte_profil(profil),
        brut["revision"] if brut else None,
    )


def verdict_courant(cnx: Connection, fournisseur_id: str) -> dict[str, Any]:
    """Le verdict de licence d'AUJOURD'HUI pour un fournisseur déjà utilisé (actif ET conforme au profil actuel)."""
    try:
        vue = registre.vue(cnx, fournisseur_id)
    except RegistreErreur as exc:
        return {"conforme": False, "codes": [exc.code], "fournisseur_id": fournisseur_id}
    codes = list(vue["politique"]["refus"] and [r["code"] for r in vue["politique"]["refus"]])
    if not vue["actif"]:
        codes.append("FOURNISSEUR_INACTIF")
    return {
        "conforme": not codes,
        "codes": codes,
        "fournisseur_id": fournisseur_id,
        "profil_empreinte": _empreinte_profil(registre.lire_profil(cnx)),
    }


def declaration_pour_double(identifiant: str = "image.double-deterministe.test") -> dict[str, Any]:
    """Déclaration (pour `registre.configurer(declaration=…)`) du générateur de TEST : licence maison permissive,
    local. Sert aux tests et aux démonstrations ; un brief non fictif refuse un générateur double (`generation`)."""
    return {
        "identifiant": identifiant,
        "capacite": "image",
        "mode": "local",
        "modele": "double déterministe de test",
        "point_acces": "module:m7_marketing.studio.generation",
        "residence_donnees": "local",
        "licence": {
            "code": "Apache-2.0",
            "poids": None,
            "usage_commercial": "autorise",
            "service_tiers": "autorise",
            "integration": "bibliotheque",
            "verification": "verifiee",
            "source": "double de test livré avec OPSYS (aucun poids, aucun modèle)",
        },
    }


# -- matrice des licences par défaut (documentation) -------------------------------------------------------------
USAGES = {
    "autorise": "oui",
    "interdit": "NON",
    "sous_seuil": "sous seuil",
    "sur_contrat": "sur contrat",
    "inconnu": "inconnu",
}


def matrice_licences_defaut() -> list[dict[str, Any]]:
    """Une ligne par modèle `image`/`video` du catalogue, avec les drapeaux de licence que la politique applique."""
    lignes = []
    for f in catalogue.CATALOGUE:
        if f.capacite not in CAPACITES:
            continue
        lic = f.licence
        lignes.append(
            {
                "id": f.identifiant,
                "capacite": f.capacite,
                "modele": f.modele,
                "statut": f.statut_catalogue,
                "poids": lic.poids or lic.code or "n/a",
                "usage_commercial": lic.usage_commercial,
                "seuil_revenu_usd": lic.seuil_revenu_usd,
                "territoires_exclus": list(lic.territoires_exclus),
                "service_tiers": lic.service_tiers,
                "mention": lic.mention_obligatoire,
                "verification": lic.verification,
                "source": lic.source,
            }
        )
    return sorted(
        lignes,
        key=lambda x: (x["capacite"], {"adopte": 0, "repli": 1, "conditionnel": 2, "ecarte": 3}[x["statut"]], x["id"]),
    )


def verdicts_de_la_matrice(profil: politique.ProfilClient) -> dict[str, tuple[str, ...]]:
    """Codes de refus de chaque modèle de la matrice pour ce profil (vide = conforme)."""
    return {f.identifiant: politique.evaluer(f, profil).codes for f in catalogue.CATALOGUE if f.capacite in CAPACITES}


def fournisseur_de(identifiant: str, cnx: Connection | None = None) -> Fournisseur | None:
    if cnx is not None:
        return registre.definition(cnx, identifiant)
    return catalogue.par_identifiant().get(identifiant)


__all__ = [
    "CAPACITES",
    "ModeleRefuse",
    "SelectionModele",
    "matrice_licences_defaut",
    "selectionner",
    "verdict_courant",
    "verdicts_de_la_matrice",
]
