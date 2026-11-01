"""« Agents Rule of Two » rendue opérationnelle : table déclarative par surface non fiable + règle des trois propriétés.

Principe (Meta, 2025-10-31, repris par la feuille de route A) : une session d'agent ne cumule pas plus de deux de ces
trois propriétés sans approbation humaine :
  [A] elle traite du contenu NON FIABLE (courriel entrant, document ingéré, page web) ;
  [B] elle a accès à des DONNÉES SENSIBLES (tout outil de département : clients, finances, équipes…) ;
  [C] elle peut CHANGER L'ÉTAT ou communiquer vers l'extérieur (niveau d'approbation N3 ou plus).

Deux gardes, dans cet ordre, pour un appel fait par une session exposée à au moins une surface non fiable :
1. un outil qui combine B et C est refusé (`REJ-MCP-RULE-OF-TWO`), même s'il figurait par erreur dans la table, sauf
   approbation humaine de niveau N3 au moins (`ApprobationPreuve`) ;
2. tout autre outil doit figurer dans la table de CHAQUE surface exposée (lecture seule, niveau N0) ; sinon il est
refusé
   (`REJ-MCP-SURFACE-NON-FIABLE`) sauf la même approbation.

La table est volontairement stricte : « lecture seule uniquement » ; un brouillon (N1) ou une tâche interne (N2) exige
une approbation sous exposition. Une session SANS exposition déclarée n'est pas touchée : c'est l'hôte (le Core, le
profil de l'agent) qui déclare l'exposition (`_meta["opsys/surfacesNonFiables"]` ou le profil du serveur) ; un agent ne
peut que l'AJOUTER. Ce qu'on ne sait pas détecter ici : du contenu non fiable arrivé par un chemin non déclaré.

Sur le planificateur isolé (CaMeL) : non implémenté ici (voir docs/architecture/OBSERVABILITE-MCP.md).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from typing import Any

from .registre import RANG, DefinitionOutil, RefusMCP

SURFACES_NON_FIABLES = ("courriel_entrant", "document_ingere", "web")
NIVEAU_EFFET = "N3"  # [C] : N3 et plus = action externe ou modification interne non finale (ADR-0009 §4)
NIVEAU_APPROBATION_MIN = "N3"
EXPOSITIONS_MAX = 8

# Ce qu'une session exposée peut appeler SANS approbation : lecture seule (N0), vérifiée contre le registre réel.
_COMMUNS = frozenset({"opsys_etat_budget", "opsys_lire_artefact", "opsys_demandes_approbation"})
SANS_APPROBATION: Mapping[str, frozenset[str]] = {
    "courriel_entrant": _COMMUNS | frozenset({
        "m1_filtrer_provenance", "m1_qualifier_signal", "m1_verifier_garde_fou", "m1_verifier_consentement",
        "m1_lire_plaintes_structurees", "m1_produire_digest",
    }),
    "document_ingere": _COMMUNS | frozenset({
        "m1_filtrer_provenance", "m1_verifier_garde_fou", "m5_lire_lot_onboarding", "m5_lire_import_quickbooks",
        "m2_lister_clients_importes",
    }),
    "web": _COMMUNS | frozenset({
        "m1_filtrer_provenance", "m1_verifier_garde_fou", "m7_analyser_concurrents", "m7_auditer_seo_site",
        "m7_valider_schema_site", "m9_lire_veille", "m9_lire_document_veille",
    }),
}
# Outils qui ne touchent à aucune donnée de l'entreprise (calcul ou lecture de leurs seuls arguments). Tout autre outil
# est présumé accéder à des données sensibles : fermé par défaut.
OUTILS_SANS_DONNEES_SENSIBLES = frozenset({"m1_filtrer_provenance", "m1_verifier_garde_fou", "opsys_etat_budget"})


@dataclasses.dataclass(frozen=True)
class ApprobationPreuve:
    """Approbation humaine déjà obtenue (file d'approbation) : niveau, approbateur, demande."""

    niveau: str
    approbateur: str
    demande_id: str
    humain: bool = True

    @property
    def valide(self) -> bool:
        return (self.humain is True and self.niveau in RANG and RANG[self.niveau] >= RANG[NIVEAU_APPROBATION_MIN]
                and bool(self.approbateur) and bool(self.demande_id))


@dataclasses.dataclass(frozen=True)
class Verdict:
    autorise: bool
    raison: str
    code: str | None = None
    sensible: bool = False
    effet: bool = False
    non_fiable: bool = False
    approuve: bool = False

    @property
    def bits(self) -> tuple[bool, bool, bool]:
        return (self.non_fiable, self.sensible, self.effet)

    def refus(self, outil: str) -> RefusMCP | None:
        if self.autorise or self.code is None:
            return None
        return RefusMCP(self.code, self.raison, outil)


def parser_expositions(valeur: Any) -> frozenset[str]:
    """Valide une déclaration d'exposition venue de l'hôte (`_meta`). Toute forme inattendue est refusée, jamais
    ignorée."""
    if valeur is None:
        return frozenset()
    if (not isinstance(valeur, (list, tuple)) or len(valeur) > EXPOSITIONS_MAX
            or not all(isinstance(v, str) and v in SURFACES_NON_FIABLES for v in valeur)):
        raise RefusMCP("REJ-MCP-EXPOSITION-INVALIDE",
                       f"exposition invalide : liste de surfaces parmi {', '.join(SURFACES_NON_FIABLES)} attendue")
    return frozenset(valeur)


def proprietes(d: DefinitionOutil) -> tuple[bool, bool]:
    """(B sensible, C effet) d'un outil : B par défaut, sauf outil déclaré sans données ; C si niveau ≥ N3."""
    return d.nom not in OUTILS_SANS_DONNEES_SENSIBLES, RANG[d.niveau] >= RANG[NIVEAU_EFFET]


def evaluer(d: DefinitionOutil, expositions: frozenset[str], approbation: ApprobationPreuve | None = None) -> Verdict:
    """Verdict de la règle pour un appel de `d` par une session exposée à `expositions`."""
    sensible, effet = proprietes(d)
    if not expositions:
        return Verdict(True, "aucune exposition à du contenu non fiable déclarée", sensible=sensible, effet=effet)
    parser_expositions(sorted(expositions))
    approuve = approbation is not None and approbation.valide
    base = {"sensible": sensible, "effet": effet, "non_fiable": True, "approuve": approuve}
    surfaces = ", ".join(sorted(expositions))
    if sensible and effet:
        if approuve:
            return Verdict(True, f"{d.nom} cumule contenu non fiable ({surfaces}), données sensibles et effet "
                                 f"({d.niveau}) : approbation humaine {approbation.niveau} présentée", **base)  # type: ignore[union-attr]
        return Verdict(
            False, f"Rule of Two : {d.nom} ({d.niveau}) cumulerait contenu non fiable ({surfaces}), accès à des "
                   "données "
                   "sensibles et action externe. Refusé : une approbation humaine de niveau N3 au moins est requise.",
            "REJ-MCP-RULE-OF-TWO", **base)
    if all(d.nom in SANS_APPROBATION[e] for e in expositions) and d.surface == "departement":
        return Verdict(True, f"{d.nom} : lecture permise sans approbation sur {surfaces}", **base)
    if approuve:
        return Verdict(True, f"{d.nom} hors table de {surfaces} : approbation humaine présentée", **base)
    return Verdict(
        False, f"{d.nom} ({d.niveau}) n'est pas permis sans approbation à une session exposée à {surfaces} "
               "(lecture seule uniquement) : demande l'approbation d'un humain.",
        "REJ-MCP-SURFACE-NON-FIABLE", **base)


def valider_table(definitions: Iterable[DefinitionOutil]) -> list[str]:
    """Défauts de la table contre le catalogue réel : outil inconnu, niveau ≠ N0, surface ≠ département, effet."""
    par_nom = {d.nom: d for d in definitions}
    problemes = []
    for surface in SURFACES_NON_FIABLES:
        for nom in sorted(SANS_APPROBATION[surface]):
            d = par_nom.get(nom)
            if d is None:
                problemes.append(f"{surface}: {nom} absent du catalogue")
            elif d.niveau != "N0" or d.surface != "departement":
                problemes.append(f"{surface}: {nom} n'est pas une lecture N0 de département ({d.niveau}, {d.surface})")
    return problemes


def analyser(definitions: Iterable[DefinitionOutil], surface: str) -> dict[str, Any]:
    """Pour la CLI : ce qu'une session exposée à `surface` peut appeler, et ce qui lui est refusé, sur le catalogue."""
    if surface not in SURFACES_NON_FIABLES:
        raise RefusMCP("REJ-MCP-EXPOSITION-INVALIDE", f"surface inconnue : {surface}")
    permis, triple, hors_table = [], [], []
    for d in sorted(definitions, key=lambda x: x.nom):
        v = evaluer(d, frozenset({surface}))
        (permis if v.autorise else triple if v.code == "REJ-MCP-RULE-OF-TWO" else hors_table).append(d.nom)
    return {"surface": surface, "permis_sans_approbation": permis, "refuses_rule_of_two": triple,
            "refuses_hors_table": hors_table}
