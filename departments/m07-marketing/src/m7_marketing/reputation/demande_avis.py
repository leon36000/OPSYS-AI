"""Brouillon de demande d'avis à partir de `m4.travaux_termines` (ADR-0009 §3, PLAN T1.2-c).

Module pur : aucun import `opsys`. Seul l'adaptateur `outils.py` sait où persister le brouillon
(registre durable) — ce module ne fait que décider et rédiger, jamais écrire.

Doctrine :
  - DEFINITION-PRODUIT.md §6 « Travaux terminés » : « M7 propose une demande d'avis et, avec
    consentement, du contenu avant/après » ; §7 M7.5 (réputation : « demandes d'avis »).
  - Jamais un envoi : `approval_status` est toujours "PROPOSE", même invariant que
    `reputation/response_builder.py` (D-043) — l'envoi réel est une action externe derrière une
    approbation, hors de ce module et de son appelant.
  - Fail-closed (P2, AGENTS.md) : `consentement_marketing` absent ou faux refuse la préparation ;
    `client_satisfait` absent refuse aussi (tout champ absent vaut refus). Seul `client_satisfait`
    explicitement `null` (« non recueilli, jamais inventé », catalogue m4.travaux_termines.json)
    ou `true` laisse passer — jamais un brouillon envisagé pour un client connu insatisfait
    (`false`).
  - Gabarit fixe et documenté (ci-dessous), jamais un texte généré par un modèle (P7).
  - Aucune photo, aucun contenu public : ceci prépare une note interne pour relancer un client,
    jamais une publication — le floutage et le consentement public restent T4.3, hors périmètre
    (M7-audit.md L322-324).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

REFUS_CONSENTEMENT_ABSENT = "consentement_marketing absent (fail-closed) : aucun brouillon"
REFUS_CONSENTEMENT_FAUX = "consentement_marketing = false : le client n'a pas consenti au marketing"
REFUS_CLIENT_SATISFAIT_ABSENT = "client_satisfait absent (fail-closed) : aucun brouillon"
REFUS_CLIENT_INSATISFAIT = "client_satisfait = false : aucune demande d'avis à un client insatisfait"

# Gabarit fixe (AGENTS.md/T1.2-c : « un gabarit fixe et documenté est permis »). {lieu} est le
# seul segment variable, construit uniquement à partir de faits déjà fournis par l'événement
# (ville, type_travaux) — jamais un fait inventé quand l'un des deux manque (_lieu_texte ci-dessous).
_GABARIT = (
    "Bonjour,\n\n"
    "Merci d'avoir fait confiance à notre équipe pour vos travaux{lieu}. "
    "Si vous êtes satisfait du résultat, accepteriez-vous de laisser un avis Google ? "
    "Cela nous aide énormément à faire connaître notre travail.\n\n"
    "Cordialement,\nL'équipe"
)


def _motif_refus(charge: Mapping[str, Any]) -> str | None:
    """Motif de refus fail-closed, ou `None` si la préparation du brouillon est autorisée."""
    if "consentement_marketing" not in charge:
        return REFUS_CONSENTEMENT_ABSENT
    if charge["consentement_marketing"] is not True:
        return REFUS_CONSENTEMENT_FAUX
    if "client_satisfait" not in charge:
        return REFUS_CLIENT_SATISFAIT_ABSENT
    if charge["client_satisfait"] is False:
        return REFUS_CLIENT_INSATISFAIT
    return None


def _lieu_texte(ville: str | None, type_travaux: str | None) -> str:
    """Segment factuel optionnel du gabarit — jamais un lieu ou un type inventé quand absent."""
    if type_travaux and ville:
        return f" ({type_travaux} à {ville})"
    if type_travaux:
        return f" ({type_travaux})"
    if ville:
        return f" à {ville}"
    return ""


def construire_brouillon(charge: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """`(brouillon, None)` si `consentement_marketing` est vrai et `client_satisfait` n'est pas
    faux ; sinon `(None, motif)`. Jamais d'exception : un refus métier n'est pas une panne, la
    structure de `charge` (champs requis du WCT) est déjà garantie par le schéma JSON du
    catalogue avant que ceci ne soit appelé.

    `id` est un uuid5 déterministe dérivé de `wct_id` : le même chantier produit toujours le même
    identifiant de brouillon, condition nécessaire à l'idempotence côté adaptateur (`outils.py`).
    """
    motif = _motif_refus(charge)
    if motif is not None:
        return None, motif

    wct_id = charge["wct_id"]
    ville = charge.get("ville")
    type_travaux = charge.get("type_travaux")
    texte = _GABARIT.format(lieu=_lieu_texte(ville, type_travaux))

    canonique = json.dumps({"wct_id": wct_id, "type": "demande_avis"}, sort_keys=True, ensure_ascii=False)
    identifiant = str(uuid.uuid5(uuid.NAMESPACE_URL, canonique))

    brouillon = {
        "id": identifiant,
        "type": "demande_avis",
        "wct_id": wct_id,
        "intervention_id": charge["intervention_id"],
        "lead_id": charge["lead_id"],
        "ville": ville,
        "type_travaux": type_travaux,
        "texte": texte,
        "approval_status": "PROPOSE",  # invariant — jamais auto-envoyé (D-043)
    }
    return brouillon, None
