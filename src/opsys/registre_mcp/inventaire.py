"""Inventaire des outils RÉELLEMENT exposés par `opsys.serveur_mcp`, sous trois surfaces :

- `departement` : les outils des départements et les outils communs (`Capacites.lister`), ce que voient `/mcp` et
  `/mcp/<département>` ;
- `contexte` : les outils privés des routes `/mcp/contexte/<département>` (tickets de cible et de mémoire, succès M9) ;
- `runtime` : la plomberie d'hôte du serveur d'admission (`/mcp/runtime/<profil>`), lue par un vrai `tools/list`.

Le niveau d'un outil de département vient de `Outil.niveau_effectif`. Pour la plomberie `runtime`, qui n'est pas un
`Outil`, le niveau est déclaré ici (`NIVEAUX_RUNTIME`) : un outil `runtime` nouveau et non classé fait ÉCHOUER
l'inventaire (fermé par défaut) plutôt que de recevoir un niveau par défaut.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import anyio

from .registre import DefinitionOutil, RefusMCP

# Plomberie d'hôte, jeton privé, jamais exposée à un modèle. Niveau = niveau de l'effet interne (voir la doc).
NIVEAUX_RUNTIME: Mapping[str, str] = {
    "opsys_runtime_admettre": "N2",                 # réserve du budget de jetons pour un cycle fournisseur
    "opsys_runtime_concilier": "N2",                # enregistre l'usage exact d'un flux
    "opsys_runtime_liberer_avant_dispatch": "N2",   # libère une réservation jamais dispatchée
    "opsys_runtime_importer_appel_manque": "N2",    # dépose un appel manqué validé par l'hôte (aucun envoi)
    "opsys_runtime_deposer_faits": "N2",           # dépose des faits candidats (aucune décision)
    "opsys_runtime_verifier_outil": "N0",           # revalide un outil du profil (lecture)
    "opsys_runtime_cfo_ticket": "N3",               # émet un ticket d'autorité CFO lié au profil
    "opsys_runtime_lire_reception_sms": "N0",
    "opsys_runtime_recevoir_sms": "N2",
}


def _definitions_departement(departements: Mapping[str, Any], cnx_factory: Callable[[], Any], *,
                             memoire: bool) -> list[DefinitionOutil]:
    from ..capacites import Capacites

    capacites = Capacites(departements, cnx_factory, memoire=memoire)
    return [DefinitionOutil.depuis_outil(outil, dep.id if dep is not None else "opsys")
            for dep, outil in capacites.index.values()]


def _definitions_contexte(departements: Mapping[str, Any], cnx_factory: Callable[[], Any]) -> list[DefinitionOutil]:
    from .. import liaison_cibles
    from ..memoire import autorite as autorite_memoire

    trouvees: dict[str, DefinitionOutil] = {}
    for ident in sorted(departements):
        outils = [liaison_cibles.outil_emission(cnx_factory, ident),
                  autorite_memoire.outil_emission(cnx_factory, ident, autorite_memoire.lire_politique)]
        if ident == "m09-strategic-intelligence":
            outils.append(liaison_cibles.outil_lecture_succes_m9(cnx_factory, ident))
        for outil in outils:
            d = DefinitionOutil.depuis_outil(outil, "opsys", "contexte")
            if trouvees.setdefault(d.nom, d).empreinte != d.empreinte:
                raise RefusMCP("REJ-MCP-ARGUMENT-INVALIDE",
                               f"{d.nom} : la définition dépend du département ({ident}) ; une seule empreinte est "
                               "possible", d.nom)
    return list(trouvees.values())


def _definitions_runtime(departements: Mapping[str, Any], cnx_factory: Callable[[], Any]) -> list[DefinitionOutil]:
    from mcp import Client

    from ..serveur_mcp import _creer_serveur_admission

    serveur = _creer_serveur_admission(departements, cnx_factory, "inventaire", garde=None)

    async def lister() -> list[Any]:
        async with Client(serveur) as client:
            return list((await client.list_tools()).tools)

    definitions = []
    for outil in anyio.run(lister):
        niveau = NIVEAUX_RUNTIME.get(outil.name)
        if niveau is None:
            raise RefusMCP("REJ-MCP-ARGUMENT-INVALIDE",
                           f"{outil.name} : outil runtime sans niveau déclaré (NIVEAUX_RUNTIME) : classe-le "
                           "avant de sceller",
                           outil.name)
        definitions.append(DefinitionOutil(outil.name, outil.description or "", dict(outil.input_schema), "opsys",
                                           niveau,
                                           "runtime"))
    return definitions


def inventaire(departements: Mapping[str, Any], cnx_factory: Callable[[], Any], *, memoire: bool = True,
               contexte: bool = True, runtime: bool = True) -> list[DefinitionOutil]:
    """Toutes les définitions exposées (triées par nom). Les options retirent une surface (tests sur des départements
    partiels : le serveur `runtime` exige les dix départements, M10 compris) ou les outils de mémoire d'entreprise."""
    toutes = _definitions_departement(departements, cnx_factory, memoire=memoire)
    if contexte:
        toutes += _definitions_contexte(departements, cnx_factory)
    if runtime:
        toutes += _definitions_runtime(departements, cnx_factory)
    return sorted(toutes, key=lambda d: d.nom)
