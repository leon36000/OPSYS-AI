"""C10 — ajustements d'inventaire AUDITÉS (M6.14) : un humain corrige le stock, le motif est TYPÉ, l'avant et l'après
sont gardés, la preuve est facultative, et le seuil qui décide QUI peut corriger est DÉCLARÉ par la direction.

Pourquoi ce module. Le comptage physique (`materiel.soumettre_comptage`) CONSTATE un écart
(`VARIANCE_INVENTAIRE`) et n'y touche jamais (DA-M6-09) : après une perte, le théorique reste supérieur au réel jusqu'à
une écriture d'ajustement décidée par un humain. C'est cette écriture, et rien d'autre, que ce module prépare.

Ce que l'ajustement écrit. Un mouvement `AJUSTEMENT` dans le registre hash-chaîné `principal` :
- `quantite` = l'écart SIGNÉ (après - avant), donc le stock théorique de l'article change exactement de cet écart ;
- `chantier_id` = `*` (constante `CHANTIER_GLOBAL`) : un ajustement d'inventaire n'appartient à aucun chantier ; il
  change le stock TOUS LIEUX, jamais le stock d'un chantier (les lectures par chantier filtrent sur leur identifiant) ;
- `ajustement` = un objet d'audit ADDITIONNEL (identifiant, motif typé, preuve, avant, après, niveau d'approbation,
  seuil, acteur, horodatage). Cet objet n'existe QUE sur les ajustements : les maillons antérieurs n'en portent pas, et
  leur empreinte reste identique bit à bit (`registre.py` n'ajoute l'extension au hash que si elle est présente).

Fail-closed. Un motif hors de la liste FERMÉE, une quantité négative/non finie, une preuve CAS mal formée, un
identifiant déjà utilisé pour un autre geste : refus nommé, aucune écriture. Le seuil est DÉCLARÉ (réglage de
direction, CFG-1) ; ABSENT ou illisible, l'ajustement escalade au niveau N4 (admin/propriétaire), jamais un seuil
inventé. À la borne, le seuil est INCLUS (`abs(delta) <= seuil`).

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge, aucun aléa, aucun réseau. Le déplacement par
emplacement est préparé ici (`construire_transfert`) mais écrit par `outils.py`, seul point qui touche `opsys.stockage`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from . import emplacements, registre, stock, verdicts

__all__ = [
    "CHANTIER_GLOBAL",
    "MOTIFS_AJUSTEMENT",
    "construire_mouvement",
    "construire_transfert",
    "deja_enregistre",
    "qualifier",
    "valider_demande",
    "verifier_chaine",
]

CHANTIER_GLOBAL = "*"

# La liste FERMÉE demandée par la fiche C10. Des codes stables, jamais du texte libre : un motif est une décision de
# l'humain qui corrige, pas une phrase que le modèle invente.
MOTIFS_AJUSTEMENT = frozenset({
    "correction",
    "stock_retrouve",
    "retour_fournisseur",
    "erreur_saisie",
    "inventaire_physique",
    "annulation",
})

_REFERENCE_CAS = re.compile(r"fichier:sha256:[0-9a-f]{64}\Z")
_CHAMPS_REQUIS = frozenset({"ajustement_id", "materiau_id", "motif", "quantite_apres", "horodatage", "acteur"})
_CHAMPS_OPTIONNELS = frozenset({"preuve", "emplacement"})
_LONGUEUR_TEXTE_MAX = 40


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _decimal(valeur: Any) -> Decimal | None:
    """Décimal exact d'un nombre fini (int/float/Decimal, jamais un booléen ni un texte), ou `None`."""
    if type(valeur) not in (int, float, Decimal):
        return None
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return None
    try:
        decimal = valeur if isinstance(valeur, Decimal) else Decimal(str(valeur))
    except InvalidOperation:
        return None
    return decimal if decimal.is_finite() else None


def valider_demande(demande: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(demande normalisée, None)` ou `(None, verdict)` : forme, motif typé, quantité, preuve CAS, emplacement.

    Aucun seuil ici : `qualifier` le lit. Aucune écriture, aucune horloge. `quantite_apres` est la cible de
    l'ajustement (le stock total, ou celui de l'emplacement quand il est nommé), jamais un écart fourni par
    l'appelant : l'écart est CALCULÉ contre le stock relu.
    """
    if not isinstance(demande, Mapping):
        return None, verdicts.construire_verdict(
            "REJ-AJUSTEMENT-STRUCTURE-INVALIDE", detail="attendu : un objet ajustement")
    inconnues = sorted(set(demande) - _CHAMPS_REQUIS - _CHAMPS_OPTIONNELS)
    manquants = sorted(_CHAMPS_REQUIS - set(demande))
    if inconnues or manquants:
        return None, verdicts.construire_verdict(
            "REJ-AJUSTEMENT-STRUCTURE-INVALIDE",
            detail=f"champs manquants {manquants} ou inconnus {inconnues}",
        )
    for nom in ("ajustement_id", "materiau_id", "horodatage", "acteur"):
        if not _texte_non_vide(demande.get(nom)):
            return None, verdicts.construire_verdict(
                "REJ-AJUSTEMENT-STRUCTURE-INVALIDE", detail=f"{nom} requis, non vide")
    if demande["motif"] not in MOTIFS_AJUSTEMENT:
        return None, verdicts.construire_verdict(
            "REJ-AJUSTEMENT-MOTIF-INVALIDE",
            detail=f"motif hors de la liste fermée : {sorted(MOTIFS_AJUSTEMENT)}",
        )
    quantite = _decimal(demande["quantite_apres"])
    if quantite is None or quantite < 0 or len(stock.texte_canonique(quantite)) > _LONGUEUR_TEXTE_MAX:
        return None, verdicts.construire_verdict(
            "REJ-AJUSTEMENT-QUANTITE-INVALIDE",
            detail="quantite_apres : un nombre fini positif ou nul (le stock visé), jamais un booléen ni un texte",
        )
    preuve = demande.get("preuve")
    if preuve is not None and (not isinstance(preuve, str) or _REFERENCE_CAS.fullmatch(preuve) is None):
        return None, verdicts.construire_verdict(
            "REJ-AJUSTEMENT-PREUVE-INVALIDE",
            detail="preuve : une référence CAS fichier:sha256:<64 hexadécimaux>, ou absente",
        )
    emplacement = None
    if demande.get("emplacement") is not None:
        emplacement, verdict = emplacements.normaliser(demande["emplacement"])
        if verdict is not None:
            return None, verdict
    return {
        "ajustement_id": demande["ajustement_id"],
        "materiau_id": demande["materiau_id"],
        "motif": demande["motif"],
        "quantite_apres": stock.texte_canonique(quantite),
        "preuve": preuve,
        "emplacement": emplacement,
        "horodatage": demande["horodatage"],
        "acteur": demande["acteur"],
    }, None


def qualifier(
    demande: Mapping[str, Any], stock_avant: Any, seuil: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Ajoute l'avant, l'écart exact et le niveau d'approbation à une demande déjà validée.

    `stock_avant` est le stock RELU (total, ou celui de l'emplacement nommé). Le seuil est un texte/nombre DÉCLARÉ ;
    absent, nul, négatif ou illisible : `niveau_approbation="N4"` et `motif_approbation="seuil_absent"` — jamais un
    seuil par défaut. `abs(ecart) <= seuil` reste N3 (borne incluse) ; au-delà, N4.
    """
    avant = _decimal(stock_avant)
    if avant is None:
        return None, verdicts.construire_verdict(
            "REJ-AJUSTEMENT-STOCK-INVALIDE", detail="stock_avant : un nombre fini")
    apres = Decimal(demande["quantite_apres"])
    ecart = apres - avant
    limite = None
    if isinstance(seuil, bool):
        seuil = None
    if seuil is not None:
        if isinstance(seuil, str):
            try:
                candidat = Decimal(seuil)
            except InvalidOperation:
                candidat = None
        elif isinstance(seuil, (int, float, Decimal)):
            candidat = _decimal(seuil)
        else:
            candidat = None
        if candidat is not None and candidat.is_finite() and candidat > 0:
            limite = candidat
    if limite is None:
        niveau, motif = "N4", "seuil_absent"
    elif abs(ecart) <= limite:
        niveau, motif = "N3", "sous_seuil"
    else:
        niveau, motif = "N4", "seuil_depasse"
    return {
        **demande,
        "quantite_avant": stock.texte_canonique(avant),
        "delta": stock.texte_canonique(ecart),
        "niveau_approbation": niveau,
        "motif_approbation": motif,
        "seuil": None if limite is None else stock.texte_canonique(limite),
        "aucun_ecart": ecart == 0,
    }, None


def construire_mouvement(qualifie: Mapping[str, Any]) -> dict[str, Any]:
    """Le mouvement `AJUSTEMENT` à ajouter au registre principal (aucune écriture ici).

    L'extension `ajustement` porte TOUT ce qu'un auditeur doit pouvoir relire : identifiant, motif typé, preuve,
    emplacement, avant/après, écart, niveau et seuil d'approbation, acteur, horodatage. Elle entre dans l'empreinte
    du maillon (`registre.py`) ; les maillons qui ne la portent pas gardent la leur.
    """
    audit = {
        "ajustement_id": qualifie["ajustement_id"],
        "materiau_id": qualifie["materiau_id"],
        "motif": qualifie["motif"],
        "preuve": qualifie["preuve"],
        "emplacement": qualifie["emplacement"],
        "quantite_avant": qualifie["quantite_avant"],
        "quantite_apres": qualifie["quantite_apres"],
        "delta": qualifie["delta"],
        "niveau_approbation": qualifie["niveau_approbation"],
        "motif_approbation": qualifie["motif_approbation"],
        "seuil": qualifie["seuil"],
        "acteur": qualifie["acteur"],
        "approbateur": qualifie.get("approbateur"),
        "horodatage": qualifie["horodatage"],
    }
    return {
        "type_mouvement": "AJUSTEMENT",
        "chantier_id": CHANTIER_GLOBAL,
        "materiau_id": qualifie["materiau_id"],
        "quantite": Decimal(qualifie["delta"]),
        "cout_unitaire": None,
        "ajustement": audit,
    }


def construire_transfert(qualifie: Mapping[str, Any]) -> dict[str, Any] | None:
    """Le transfert d'emplacement qui suit un ajustement localisé, ou `None`.

    Un ajustement sur un emplacement NOMMÉ change le stock total ; pour que le lieu nommé porte vraiment la quantité
    corrigée, il faut aussi déplacer l'écart entre ce lieu et `inconnu` (le résidu non localisé) :
    - stock trouvé en plus (`delta > 0`) : `inconnu -> emplacement` ;
    - stock manquant (`delta < 0`) : `emplacement -> inconnu`.
    Un ajustement sur `inconnu` n'a pas besoin de transfert. Aucune quantité négative par emplacement : c'est
    `emplacements.construire_transfert` qui le vérifie, avec le stock total APRÈS l'ajustement.
    """
    emplacement = qualifie.get("emplacement")
    ecart = Decimal(qualifie["delta"])
    if emplacement is None or ecart == 0 or emplacements.cle(emplacement) == emplacements.INCONNU:
        return None
    quantite = abs(ecart)
    if ecart > 0:
        origine = {"type": emplacements.INCONNU, "reference": None}
        destination = emplacement
    else:
        origine = emplacement
        destination = {"type": emplacements.INCONNU, "reference": None}
    return {
        "transfert_id": f"{qualifie['ajustement_id']}:emplacement",
        "materiau_id": qualifie["materiau_id"],
        "quantite": quantite,
        "de": origine,
        "vers": destination,
        "acteur": qualifie["acteur"],
        "motif": f"ajustement {qualifie['motif']}",
        "horodatage": qualifie["horodatage"],
    }


def deja_enregistre(ajustement_id: Any, mouvements: Any) -> dict[str, Any] | None:
    """Le maillon d'ajustement déjà écrit pour cet identifiant, ou `None`."""
    for mouvement in mouvements:
        if mouvement.get("type_mouvement") != "AJUSTEMENT":
            continue
        audit = mouvement.get("ajustement")
        if isinstance(audit, Mapping) and audit.get("ajustement_id") == ajustement_id:
            return mouvement
    return None


def verifier_chaine(mouvements: Any) -> tuple[bool, str]:
    """La chaîne hash-chaînée du registre de mouvements, telle que `registre.Registre` la valide."""
    return registre.Registre(maillons=list(mouvements)).valider_chaine()
