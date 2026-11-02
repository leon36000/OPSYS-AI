"""Les relevés de dépense publicitaire de M7 reçus par M5 : un BROUILLON de charge, jamais une écriture validée.

Interconnexion des départements (docs/architecture/INTERCONNEXION.md). M7 publie `m7.depenses_marketing_constatees`
quand un connecteur publicitaire en lecture inscrit ou révise un relevé de dépense TOTAL (canal entier, un jour), en
dollars canadiens. M5, propriétaire de la comptabilité, en tire - SANS rien valider - un brouillon d'écriture au grand
livre : débit du compte de charge de la catégorie « marketing » du plan (`correspondance_charges`, jamais un compte
supposé), crédit « Comptes fournisseurs » du même montant. La validation (N4) reste à la personne que le socle désigne.

Ce que ce module décide, en fonction pure (aucun import `opsys`, aucune horloge) :

- `HORS_TAXES` seulement donne un brouillon : le montant est celui de la plateforme, sans taxe à séparer. Un relevé
  `TAXES_INCLUSES` ne se ventile pas ici : séparer la TPS/TVQ d'un fournisseur étranger est une décision fiscale
  (autocotisation, inscription du fournisseur) que M5 ne devine pas. Il est rangé `A_COMPLETER_TAXES`, sans brouillon ;
- seule la RÉVISION 1 d'un relevé donne un brouillon. Une révision ultérieure ne crée jamais un second brouillon (elle
  doublerait la charge) : elle est rangée `A_REVOIR_REVISION`, avec la révision déjà proposée, pour qu'une personne
  décide d'une contre-passation et d'un nouveau brouillon ;
- une révision PÉRIMÉE ne donne jamais de brouillon : si M5 a déjà reçu une révision plus récente du même relevé (la
  livraison du bus n'est pas ordonnée : une panne transitoire fait arriver la révision 2 avant la 1), la plus ancienne
  est rangée `REVISION_PERIMEE`. Sans cette garde, la révision 1 tardive proposerait un brouillon au montant périmé ;
- un montant nul ne donne rien (`MONTANT_NUL`) ;
- la pièce est déclarée (`manuelle`, référence `m7:<relevé>:r<révision>`), jamais prétendue vérifiée : M5 ne lit pas
  le registre de M7.

Idempotence : une ligne par (relevé, révision) au registre `charges_marketing_recues` ; le grand livre dédoublonne en
plus par `cle_piece`. Le rejeu du même relevé sous un autre `evenement_id` n'écrit rien.

CONTRADICTION. La MÊME clé (relevé, révision) avec un contenu DIFFÉRENT (autre montant, autre période, autre base de
taxes...) n'est pas un rejeu : chaque ligne garde l'empreinte du contenu reçu (`empreinte_contenu`, jamais le montant en
clair) et `contenu_contradictoire` la compare à celle de la ligne déjà rangée. Le premier état reste, rien n'est
écrasé ; `outils._recevoir_depense_marketing` range la contradiction (`opsys.evenements.constats`) et la dit. Une
ligne écrite avant cette règle n'a pas d'empreinte : elle ne peut pas être comparée (jamais une contradiction présumée).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

REGISTRE = "charges_marketing_recues"
CHAMPS_CONTENU = ("canal", "periode_debut", "periode_fin", "montant_cad", "devise", "base_taxes", "source", "releve_le")
TYPE_ENTREE = "charge_marketing_recue"
CATEGORIE_CHARGE = "marketing"
MENTION = "À valider auprès d'un comptable (CPA) / professionnel qualifié"

BROUILLON_PROPOSE = "BROUILLON_PROPOSE"
A_COMPLETER_TAXES = "A_COMPLETER_TAXES"
A_REVOIR_REVISION = "A_REVOIR_REVISION"
REVISION_PERIMEE = "REVISION_PERIMEE"
MONTANT_NUL = "MONTANT_NUL"
REFUSE = "REFUSE"


def cle(charge: Mapping[str, Any]) -> str:
    return f"{charge['releve_id']}|r{charge['revision']}"


def empreinte_contenu(charge: Mapping[str, Any]) -> str:
    """L'empreinte du CONTENU du relevé (tout sauf l'identifiant de l'événement du bus) : ce que deux livraisons du même
    relevé doivent partager."""
    contenu = {c: charge[c] for c in CHAMPS_CONTENU}
    texte = json.dumps(contenu, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:32]


def contenu_contradictoire(ligne: Mapping[str, Any], charge: Mapping[str, Any]) -> bool:
    """Vrai si la ligne déjà rangée pour cette clé porte une empreinte différente de celle du relevé reçu."""
    connue = ligne.get("empreinte_contenu")
    return isinstance(connue, str) and connue != empreinte_contenu(charge)


def cle_piece(charge: Mapping[str, Any]) -> str:
    return f"auto:releve_marketing:{charge['releve_id']}:r{charge['revision']}"


def reference_piece(charge: Mapping[str, Any]) -> str:
    return f"m7:{charge['releve_id']}:r{charge['revision']}"


def decision(
    charge: Mapping[str, Any], deja_proposees: Mapping[str, int], revisions_vues: Mapping[str, int] | None = None
) -> str | None:
    """`None` : un brouillon est à proposer. Sinon la raison pour laquelle M5 n'en propose pas.

    `deja_proposees` : `{releve_id: révision déjà proposée}` d'après le registre de M5 ;
    `revisions_vues` : `{releve_id: plus haute révision déjà REÇUE}` (toute issue confondue)."""
    if charge["base_taxes"] != "HORS_TAXES":
        return A_COMPLETER_TAXES
    if (revisions_vues or {}).get(charge["releve_id"], 0) > charge["revision"]:
        return REVISION_PERIMEE
    if charge["revision"] > 1 or charge["releve_id"] in deja_proposees:
        return A_REVOIR_REVISION
    if Decimal(charge["montant_cad"]) == 0:
        return MONTANT_NUL
    return None


def proposition(charge: Mapping[str, Any], compte_charge: str, compte_fournisseurs: str) -> dict[str, Any]:
    """La proposition de brouillon (forme de `grand_livre.proposer_ecriture`)."""
    montant = charge["montant_cad"]
    libelle = f"Dépense publicitaire {charge['canal']} du {charge['periode_debut']} au {charge['periode_fin']}"
    return {
        "cle_piece": cle_piece(charge),
        "piece": {"type": "manuelle", "reference": reference_piece(charge)},
        "nature": "depense_marketing_constatee",
        "date_effet": charge["periode_fin"],
        "libelle": libelle,
        "lignes_brutes": [
            {"compte": compte_charge, "debit": montant, "credit": None},
            {"compte": compte_fournisseurs, "debit": None, "credit": montant},
        ],
    }


def ligne_registre(charge: Mapping[str, Any], issue: str, **plus: Any) -> dict[str, Any]:
    """La ligne de journal : identifiants et issue, jamais le montant du relevé d'un autre département en clair
    ailleurs que dans le brouillon qu'il fonde."""
    return {
        "type_entree": TYPE_ENTREE,
        "cle": cle(charge),
        "releve_id": charge["releve_id"],
        "revision": charge["revision"],
        "canal": charge["canal"],
        "issue": issue,
        "empreinte_contenu": empreinte_contenu(charge),
        "mention": MENTION,
        **plus,
    }
