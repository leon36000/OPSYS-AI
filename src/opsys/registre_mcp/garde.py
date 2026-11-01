"""Garde du serveur MCP : registre scellé + Rule of Two, au démarrage et à CHAQUE appel.

- au démarrage (`demarrer`) : compare le catalogue exposé au registre ; un outil dérivé, inconnu ou de niveau changé
est mis
  en quarantaine (absent de `tools/list`, refusé à l'appel) et chaque cas est rapporté ; en mode strict, le premier
  lève ;
- à chaque appel (`controler`) : recalcule l'empreinte de l'outil TEL QU'IL EST EXPOSÉ MAINTENANT et la compare au
sceau ;
  une dérive survenue après le démarrage est donc aussi refusée (aucun cache d'approbation), puis applique la
  Rule of Two si la session déclare une exposition à du contenu non fiable ;
- chaque refus est rapporté (`rapporter`) : le serveur le journalise et le trace (span `refus_mcp`).

Activation en production par variable d'environnement (aucun changement de comportement si elle est absente) :
`OPSYS_MCP_REGISTRE=defaut` (registre livré avec le logiciel) ou un chemin ; `OPSYS_MCP_REGISTRE_STRICT=1` refuse de
démarrer sur une dérive ; `OPSYS_MCP_REGISTRE_HMAC=1` exige le sceau HMAC (clé locale d'observabilité).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from . import registre as reg
from . import rule_of_two
from .registre import DefinitionOutil, RapportVerification, RefusMCP, Registre

_LOG = logging.getLogger(__name__)
ENV_REGISTRE = "OPSYS_MCP_REGISTRE"
ENV_STRICT = "OPSYS_MCP_REGISTRE_STRICT"
ENV_HMAC = "OPSYS_MCP_REGISTRE_HMAC"
REGISTRE_LIVRE = Path(__file__).with_name("registre.v1.json")
_VRAI = {"1", "true", "oui", "on", "actif"}

Rapporteur = Callable[[RefusMCP, Mapping[str, object]], None]


class GardeMCP:
    def __init__(self, registre: Registre, *, surfaces: frozenset[str] = frozenset({"departement"}),
                 rapporter: Rapporteur | None = None, rule_of_two_active: bool = True, strict: bool = False,
                 silencieux: bool = False) -> None:
        self.registre = registre
        self.surfaces = surfaces
        self._rapporter = rapporter
        self.rule_of_two_active = rule_of_two_active
        self.strict = strict
        self.silencieux = silencieux  # évaluation hors ligne : les refus sont attendus, pas des alertes
        self.quarantaine: frozenset[str] = frozenset()

    def __repr__(self) -> str:
        return f"GardeMCP(revision={self.registre.revision}, surfaces={sorted(self.surfaces)})"

    def avec(self, *, surfaces: frozenset[str], rapporter: Rapporteur | None) -> GardeMCP:
        """Copie pour un autre serveur (autres surfaces permises) sur le même registre. Le nouveau rapporteur s'AJOUTE à
        celui de la garde d'origine : un refus est rapporté aux deux."""
        anciens = [r for r in (self._rapporter, rapporter) if r is not None]

        def tous(refus: RefusMCP, contexte: Mapping[str, object]) -> None:
            for un_rapporteur in anciens:
                try:
                    un_rapporteur(refus, contexte)
                except Exception:  # noqa: BLE001 — un rapporteur en panne ne retient pas les autres
                    _LOG.exception("rapport de refus MCP en échec")

        return GardeMCP(self.registre, surfaces=surfaces, rapporter=tous if anciens else None,
                        rule_of_two_active=self.rule_of_two_active, strict=self.strict, silencieux=self.silencieux)

    def signaler(self, refus: RefusMCP, **contexte: object) -> None:
        if not self.silencieux:
            _LOG.warning("MCP refusé : %s (%s)", refus.code, refus.outil)
        if self._rapporter is not None:
            try:
                self._rapporter(refus, contexte)
            except Exception:  # noqa: BLE001 — le rapport ne doit jamais empêcher le refus
                _LOG.exception("rapport de refus MCP en échec")

    def demarrer(self, definitions: Sequence[DefinitionOutil]) -> RapportVerification:
        rapport = reg.comparer(self.registre, definitions, self.surfaces)
        self.quarantaine = rapport.en_quarantaine
        for d in definitions:
            refus = reg.verifier_definition(self.registre, d, self.surfaces)
            if refus is not None:
                if self.strict:
                    raise refus
                self.signaler(refus, moment="demarrage")
        return rapport

    def verifier_definition(self, d: DefinitionOutil) -> RefusMCP | None:
        return reg.verifier_definition(self.registre, d, self.surfaces)

    def filtrer(self, definitions: Sequence[DefinitionOutil]) -> list[DefinitionOutil]:
        """Définitions conformes au sceau (pour `tools/list`) ; les autres sont rapportées et retirées."""
        retenues = []
        for d in definitions:
            refus = self.verifier_definition(d)
            if refus is None:
                retenues.append(d)
            else:
                self.signaler(refus, moment="liste")
        return retenues

    def controler(self, d: DefinitionOutil | None, *, expositions: frozenset[str] = frozenset(),
                  approbation: rule_of_two.ApprobationPreuve | None = None) -> RefusMCP | None:
        """Refus à rendre à l'appelant, ou None. `d` None = outil que le serveur ne connaît pas : sa propre erreur
        répond."""
        if d is None:
            return None
        refus = self.verifier_definition(d)
        if refus is None and self.rule_of_two_active:
            refus = rule_of_two.evaluer(d, expositions, approbation).refus(d.nom)
        if refus is not None:
            self.signaler(refus, moment="appel", expositions=sorted(expositions))
        return refus


def garde_depuis_env(environ: Mapping[str, str] | None = None, *,
                     rapporter: Rapporteur | None = None) -> GardeMCP | None:
    """Garde configurée par l'environnement, ou None si `OPSYS_MCP_REGISTRE` est absent. Une configuration cassée
    LÈVE."""
    env = os.environ if environ is None else environ
    valeur = env.get(ENV_REGISTRE, "").strip()
    if not valeur or valeur.lower() in {"0", "non", "off", "false"}:
        return None
    cle = None
    if env.get(ENV_HMAC, "").strip().lower() in _VRAI:
        from ..observabilite import cle_locale

        cle = cle_locale.deriver(cle_locale.charger(), "mcp/registre/v1")
    chemin = REGISTRE_LIVRE if valeur == "defaut" else Path(valeur)
    return GardeMCP(reg.charger(chemin, cle=cle), rapporter=rapporter,
                    strict=env.get(ENV_STRICT, "").strip().lower() in _VRAI)
