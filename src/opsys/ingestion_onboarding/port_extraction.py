"""Port d'extraction STRUCTURÉE d'une facture : texte -> JSON `opsys.facture/v1`, par un fournisseur du registre.

Le fournisseur est celui que le registre de fournisseurs (`opsys.fournisseurs.registre.resoudre`) retient pour la
capacité `llm` du département M5 : la sélection de M5, sinon le défaut global ; une sélection inactive ou devenue non
conforme à la politique de licence est un REFUS (`REJ-ING-FOURNISSEUR-REFUSE`, avec le code du registre), jamais un
autre fournisseur à sa place. Aucun repli.

Un fournisseur résolu n'est appelé que par un ADAPTATEUR raccordé à son point d'accès (`_ADAPTATEURS`). Cette tranche
n'en raccorde AUCUN de réel : aucun appel réseau, aucun VLM, aucun LLM. Un fournisseur conforme mais non raccordé est
`REJ-ING-EXTRACTEUR-NON-RACCORDE`. Les tests raccordent un fournisseur SIMULÉ déterministe (déclaré au registre,
activé sous la politique, sélectionné), jamais présenté comme une capacité livrée.

La sortie de l'adaptateur n'est jamais crue : elle passe par la validation déterministe de M5
(`m5_financecore.validation_facture_onboarding`).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from ..fournisseurs import registre
from ..fournisseurs.modele import Fournisseur
from .codes import EchecEtape

CAPACITE = "llm"
DEPARTEMENT = "m05-financecore"

class AdaptateurExtraction(Protocol):
    def __call__(self, pages: Sequence[Mapping[str, Any]], fournisseur: Fournisseur) -> Any: ...

# point d'accès du fournisseur -> adaptateur. VIDE en production dans cette tranche (voir la docstring du module).
_ADAPTATEURS: dict[str, AdaptateurExtraction] = {}

@dataclasses.dataclass(frozen=True)
class ExtracteurResolu:
    fournisseur: Fournisseur
    portee: str
    adaptateur: AdaptateurExtraction

    def provenance(self) -> dict[str, Any]:
        return {"fournisseur": self.fournisseur.identifiant, "portee": self.portee,
                "modele": self.fournisseur.modele, "capacite": CAPACITE}

def resoudre(cnx: Any) -> ExtracteurResolu:
    """Le fournisseur retenu ET son adaptateur ; `EchecEtape` typé sinon (définitif : configurer, puis relancer)."""
    try:
        resolution = registre.resoudre(cnx, CAPACITE, DEPARTEMENT)
    except registre.RegistreErreur as exc:
        refus = f" ({', '.join(exc.codes)})" if exc.codes else ""
        raise EchecEtape("REJ-ING-FOURNISSEUR-REFUSE", f"registre de fournisseurs : {exc.code}{refus} ; aucun repli "
                         f"(capacité {CAPACITE}, département {DEPARTEMENT})") from None
    adaptateur = _ADAPTATEURS.get(resolution.fournisseur.point_acces or "")
    if adaptateur is None:
        raise EchecEtape("REJ-ING-EXTRACTEUR-NON-RACCORDE", f"{resolution.fournisseur.identifiant} est conforme mais "
                         "aucun adaptateur d'extraction n'est raccordé à son point d'accès dans cette tranche (aucun "
                         "appel réseau)")
    return ExtracteurResolu(resolution.fournisseur, resolution.portee, adaptateur)

def extraire(extracteur: ExtracteurResolu, pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """L'extraction brute de l'adaptateur (un objet JSON) ; `EchecEtape` reprenable si l'adaptateur échoue."""
    try:
        sortie = extracteur.adaptateur(pages, extracteur.fournisseur)
    except Exception as exc:  # noqa: BLE001 — la panne d'un adaptateur ne doit jamais fuir son contenu
        raise EchecEtape("REJ-ING-EXTRACTION-INVALIDE", f"adaptateur {extracteur.fournisseur.identifiant} en échec "
                         f"({type(exc).__name__})", reprenable=True) from None
    if not isinstance(sortie, dict):
        raise EchecEtape("REJ-ING-EXTRACTION-INVALIDE", "l'adaptateur n'a pas rendu un objet JSON", reprenable=True)
    return sortie

__all__ = ["CAPACITE", "DEPARTEMENT", "AdaptateurExtraction", "ExtracteurResolu", "extraire", "resoudre"]
