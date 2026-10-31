"""Moteur de politique de licence (FEUILLE-DE-ROUTE r2 B.2 ; R5 §7.1 ; DECISIONS r1 §7).

`evaluer(fournisseur, profil)` est une fonction PURE et déterministe : elle rend TOUS les refus applicables,
chacun avec un code stable et un motif lisible. Aucun repli : un refus ne propose ni n'active jamais un autre
fournisseur ; c'est à l'humain de choisir. Une donnée manquante (profil absent, revenu inconnu, territoire
inconnu, licence non lue) est un refus explicite, jamais une valeur supposée.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping
from typing import Any

from .modele import TERRITOIRES, DeclarationInvalide, Fournisseur

# Codes de refus (stables : la console, la CLI et les tests les citent tels quels).
PROFIL_CLIENT_ABSENT = "PROFIL_CLIENT_ABSENT"
FOURNISSEUR_ECARTE = "FOURNISSEUR_ECARTE"
LICENCE_NON_COMMERCIALE = "LICENCE_NON_COMMERCIALE"
LICENCE_INCONNUE = "LICENCE_INCONNUE"
LICENCE_A_VERIFIER = "LICENCE_A_VERIFIER"
CONTRAT_REQUIS = "CONTRAT_REQUIS"
SEUIL_REVENU_DEPASSE = "SEUIL_REVENU_DEPASSE"
REVENU_CLIENT_INCONNU = "REVENU_CLIENT_INCONNU"
TERRITOIRE_EXCLU = "TERRITOIRE_EXCLU"
TERRITOIRE_CLIENT_INCONNU = "TERRITOIRE_CLIENT_INCONNU"
SERVICE_TIERS_INTERDIT = "SERVICE_TIERS_INTERDIT"
SERVICE_TIERS_INCERTAIN = "SERVICE_TIERS_INCERTAIN"
COPYLEFT_INTEGRE = "COPYLEFT_INTEGRE"
MENTION_NON_CONFIRMEE = "MENTION_NON_CONFIRMEE"
EFVP_REQUISE = "EFVP_REQUISE"

CODES_REFUS: tuple[str, ...] = (
    PROFIL_CLIENT_ABSENT, FOURNISSEUR_ECARTE, LICENCE_NON_COMMERCIALE, LICENCE_INCONNUE, LICENCE_A_VERIFIER,
    CONTRAT_REQUIS, SEUIL_REVENU_DEPASSE, REVENU_CLIENT_INCONNU, TERRITOIRE_EXCLU, TERRITOIRE_CLIENT_INCONNU,
    SERVICE_TIERS_INTERDIT, SERVICE_TIERS_INCERTAIN, COPYLEFT_INTEGRE, MENTION_NON_CONFIRMEE, EFVP_REQUISE,
)


@dataclasses.dataclass(frozen=True)
class ProfilClient:
    """Profil de licence du client, déclaré par un administrateur (aucune valeur par défaut).

    - `usage_commercial` : le client est une entreprise qui exploite les sorties commercialement ;
    - `revenu_annuel_usd` : chiffre d'affaires annuel déclaré EN USD, affiliés compris (les seuils des licences
      sont en USD ; aucune conversion implicite) ; `None` = inconnu ;
    - `territoires` : où le client opère ET où l'infrastructure est hébergée (codes de `modele.TERRITOIRES`) ;
    - `heberge_pour_tiers` : OPSYS sert ce composant à plusieurs entreprises (SaaS, multi-locataire) ou à une
      entreprise tierce de l'éditeur. Question juridique ouverte (FEUILLE r2 B.6) : déclarée, jamais supposée.
    """

    usage_commercial: bool
    revenu_annuel_usd: int | None
    territoires: frozenset[str]
    heberge_pour_tiers: bool

    def __post_init__(self) -> None:
        if type(self.usage_commercial) is not bool or type(self.heberge_pour_tiers) is not bool:
            raise DeclarationInvalide("profil : usage_commercial et heberge_pour_tiers sont des booléens")
        if self.revenu_annuel_usd is not None and (
            type(self.revenu_annuel_usd) is not int or self.revenu_annuel_usd < 0
        ):
            raise DeclarationInvalide("profil : revenu_annuel_usd est un entier positif ou nul (USD)")
        if not isinstance(self.territoires, frozenset) or any(t not in TERRITOIRES for t in self.territoires):
            raise DeclarationInvalide(f"profil : territoires parmi {', '.join(TERRITOIRES)}")

    def vers_json(self) -> dict[str, Any]:
        return {"usage_commercial": self.usage_commercial, "revenu_annuel_usd": self.revenu_annuel_usd,
                "territoires": sorted(self.territoires), "heberge_pour_tiers": self.heberge_pour_tiers}

    @classmethod
    def depuis_valeurs(cls, *, usage_commercial: Any, revenu_annuel_usd: Any, territoires: Iterable[str] | str,
                       heberge_pour_tiers: Any) -> ProfilClient:
        if isinstance(territoires, str):
            territoires = json.loads(territoires)
        return cls(usage_commercial=usage_commercial, revenu_annuel_usd=revenu_annuel_usd,
                   territoires=frozenset(territoires), heberge_pour_tiers=heberge_pour_tiers)


@dataclasses.dataclass(frozen=True)
class Refus:
    code: str
    motif: str


@dataclasses.dataclass(frozen=True)
class Decision:
    identifiant: str
    refus: tuple[Refus, ...]

    @property
    def conforme(self) -> bool:
        return not self.refus

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.refus)

    def vers_json(self) -> dict[str, Any]:
        return {"identifiant": self.identifiant, "conforme": self.conforme,
                "refus": [{"code": r.code, "motif": r.motif} for r in self.refus]}


def evaluer(fournisseur: Fournisseur, profil: ProfilClient | None) -> Decision:
    """Tous les refus applicables, dans l'ordre stable de `CODES_REFUS`."""
    licence = fournisseur.licence
    refus: list[Refus] = []

    def refuser(code: str, motif: str) -> None:
        refus.append(Refus(code, motif))

    if profil is None:
        refuser(PROFIL_CLIENT_ABSENT, "profil de licence du client non déclaré : déclarer usage commercial, "
                "revenu annuel (USD), territoires et hébergement pour tiers avant toute activation")
    if fournisseur.statut_catalogue == "ecarte":
        refuser(FOURNISSEUR_ECARTE, f"écarté par la feuille de route : {fournisseur.raison_ecart}")
    commercial = profil is None or profil.usage_commercial
    if commercial and licence.usage_commercial == "interdit":
        refuser(LICENCE_NON_COMMERCIALE, f"licence non commerciale (code : {licence.code or 'n/a'} ; "
                f"poids : {licence.poids or 'n/a'})")
    if licence.usage_commercial == "inconnu":
        refuser(LICENCE_INCONNUE, "droit d'usage commercial inconnu : licence à qualifier avant activation")
    if licence.verification == "a_lire" and not fournisseur.licence_lue_par:
        refuser(LICENCE_A_VERIFIER, "texte intégral de la licence non lu : un administrateur doit le lire et "
                "le consigner (licence_lue_par) avant activation")
    if commercial and licence.usage_commercial == "sur_contrat" and not fournisseur.contrat_ref:
        refuser(CONTRAT_REQUIS, "usage commercial sur contrat ou conditions payantes : référence de contrat requise")
    if licence.seuil_revenu_usd is not None and commercial:
        if profil is not None and profil.revenu_annuel_usd is None:
            refuser(REVENU_CLIENT_INCONNU, f"licence plafonnée à {licence.seuil_revenu_usd} USD de revenu annuel : "
                    "revenu du client non déclaré")
        elif profil is not None and profil.revenu_annuel_usd >= licence.seuil_revenu_usd:
            refuser(SEUIL_REVENU_DEPASSE, f"revenu déclaré {profil.revenu_annuel_usd} USD ≥ seuil de la licence "
                    f"{licence.seuil_revenu_usd} USD")
    if licence.territoires_exclus and profil is not None:
        if not profil.territoires:
            refuser(TERRITOIRE_CLIENT_INCONNU, "licence à exclusions territoriales : territoires du client et de "
                    "l'infrastructure non déclarés")
        else:
            exclus = sorted(profil.territoires.intersection(licence.territoires_exclus))
            if exclus:
                refuser(TERRITOIRE_EXCLU, f"territoire(s) exclu(s) par la licence : {', '.join(exclus)}")
    if profil is not None and profil.heberge_pour_tiers:
        if licence.service_tiers == "interdit":
            refuser(SERVICE_TIERS_INTERDIT, "la licence interdit d'offrir ce composant comme service à des tiers")
        elif licence.service_tiers == "incertain":
            refuser(SERVICE_TIERS_INCERTAIN, "droit de service à des tiers non établi (avis juridique requis, "
                    "FEUILLE r2 B.6)")
    if licence.copyleft and licence.integration == "bibliotheque":
        refuser(COPYLEFT_INTEGRE, "licence GPL/AGPL : seulement en service séparé non modifié (DECISIONS r1 §7)")
    if licence.mention_obligatoire and not fournisseur.mention_confirmee:
        refuser(MENTION_NON_CONFIRMEE, f"mention obligatoire à afficher : « {licence.mention_obligatoire} » ; "
                "confirmer qu'elle sera affichée")
    if fournisseur.mode == "api" and fournisseur.residence_donnees not in {"local", "QC"} and not fournisseur.efvp_ref:
        refuser(EFVP_REQUISE, "transfert de données hors Québec : référence d'EFVP (Loi 25) requise avant usage")
    ordre = {code: i for i, code in enumerate(CODES_REFUS)}
    return Decision(fournisseur.identifiant, tuple(sorted(refus, key=lambda r: ordre[r.code])))


def profil_depuis_ligne(ligne: Mapping[str, Any] | None) -> ProfilClient | None:
    if ligne is None:
        return None
    return ProfilClient.depuis_valeurs(
        usage_commercial=bool(ligne["usage_commercial"]), revenu_annuel_usd=ligne["revenu_annuel_usd"],
        territoires=ligne["territoires"], heberge_pour_tiers=bool(ligne["heberge_pour_tiers"]),
    )
