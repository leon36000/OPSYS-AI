"""Brouillon de demande d'avis à partir de `m4.travaux_termines` (ADR-0009 §3, PLAN T1.2-c, T1.5-d).

Module pur : aucun import `opsys`. Seul l'adaptateur `outils.py` sait où persister le brouillon
(registre durable) et lire la taxonomie — ce module ne fait que décider et rédiger, jamais écrire.

Doctrine :
  - DEFINITION-PRODUIT.md §6 « Travaux terminés » : « M7 propose une demande d'avis et, avec
    consentement, du contenu avant/après » ; §7 M7.5 (réputation : « demandes d'avis »).
  - Jamais un envoi : `approval_status` est toujours "PROPOSE", même invariant que
    `reputation/response_builder.py` (D-043) — l'envoi réel est un engagement externe (T3) derrière
    une décision humaine, hors de ce module et de son appelant.
  - PLAN T1.5-d, Loi 25 : la demande naît du consentement explicite du CLIENT à être contacté pour un
    avis, `consentement_demande_avis` du WCT, recueilli par l'employé dans l'app (« Terminer ») et
    DISTINCT de `consentement_marketing` (l'usage de photos, POLITIQUE-photos-non-contractuelles.md
    §3) : l'un n'est jamais déduit de l'autre. Fail-closed : absent ou faux, aucun brouillon. Le
    consentement doit aussi venir avec sa PREUVE, posée par M4 (qui l'a recueilli, quand, quel texte
    a été présenté) : un consentement que personne ne peut relire n'est pas documenté.
  - `client_satisfait = false` refuse encore (aucune demande à un client connu insatisfait, règle de
    T1.2-c) ; son absence ou `null` (« non recueilli, jamais inventé ») ne refuse plus : c'est le
    client qui a demandé à être sollicité, pas un signal deviné. Décision à confirmer par Nathan : les
    plateformes d'avis interdisent de ne solliciter que les clients satisfaits (P9).
  - Nature des travaux (PLAN T0.13-b) : un WCT de lead v1 porte `type_travaux`, un WCT de lead v2
    porte `service` (code de la taxonomie). Le texte dit `type_travaux` pour un v1 et le LIBELLÉ du
    service pour un v2, que l'adaptateur résout (`libelle_service`) ; jamais l'un déduit de l'autre, et
    un WCT qui porte les deux est refusé (donnée contradictoire).
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

REFUS_CONSENTEMENT_ABSENT = "consentement_demande_avis absent (fail-closed) : aucun brouillon"
REFUS_CONSENTEMENT_FAUX = (
    "consentement_demande_avis = false : le client n'a pas consenti à une demande d'avis"
)
REFUS_PREUVE_ABSENTE = (
    "preuve du consentement absente (fail-closed) : aucun brouillon sans qui l'a recueilli, quand, "
    "et quel texte a été présenté au client"
)
REFUS_CLIENT_INSATISFAIT = "client_satisfait = false : aucune demande d'avis à un client insatisfait"
REFUS_NATURE_TRAVAUX_AMBIGUE = (
    "type_travaux ET service dans le même WCT (lead v1 ou v2, jamais les deux) : aucun brouillon"
)

# Les trois clés de preuve posées par M4 (`outbox.CLES_PREUVE_CONSENTEMENT`) — copiées ici, un module
# pur ne connaît que le contrat de l'événement (catalogue `m4.travaux_termines.json`), pas M4.
CLES_PREUVE = ("consentement_recueilli_par", "consentement_recueilli_le", "consentement_version_texte")

# Gabarit fixe (AGENTS.md/T1.2-c : « un gabarit fixe et documenté est permis »). {lieu} est le
# seul segment variable, construit uniquement à partir de faits déjà fournis par l'événement
# (ville, nature des travaux) — jamais un fait inventé quand l'un des deux manque (_lieu_texte ci-dessous).
_GABARIT = (
    "Bonjour,\n\n"
    "Merci d'avoir fait confiance à notre équipe pour vos travaux{lieu}. "
    "Si vous êtes satisfait du résultat, accepteriez-vous de laisser un avis Google ? "
    "Cela nous aide énormément à faire connaître notre travail.\n\n"
    "Cordialement,\nL'équipe"
)


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _motif_refus(charge: Mapping[str, Any]) -> str | None:
    """Motif de refus fail-closed, ou `None` si la préparation du brouillon est autorisée."""
    if "consentement_demande_avis" not in charge:
        return REFUS_CONSENTEMENT_ABSENT
    if charge["consentement_demande_avis"] is not True:
        return REFUS_CONSENTEMENT_FAUX
    if not all(_texte_non_vide(charge.get(cle)) for cle in CLES_PREUVE):
        return REFUS_PREUVE_ABSENTE
    if charge.get("client_satisfait") is False:
        return REFUS_CLIENT_INSATISFAIT
    if "type_travaux" in charge and "service" in charge:
        return REFUS_NATURE_TRAVAUX_AMBIGUE
    return None


def _lieu_texte(ville: str | None, nature_travaux: str | None) -> str:
    """Segment factuel optionnel du gabarit — jamais un lieu ou une nature inventés quand absents."""
    if nature_travaux and ville:
        return f" ({nature_travaux} à {ville})"
    if nature_travaux:
        return f" ({nature_travaux})"
    if ville:
        return f" à {ville}"
    return ""


def _nature_des_travaux(
    charge: Mapping[str, Any], libelle_service: str | None,
) -> str | None:
    """Ce que le texte dit des travaux : `type_travaux` d'un WCT v1 (les mots du contrat, sans les
    soulignés), le libellé du service d'un WCT v2. Jamais l'un à la place de l'autre : un WCT v2
    dont le libellé n'a pas pu être résolu n'a PAS de nature, il n'emprunte pas son code brut."""
    if _texte_non_vide(charge.get("type_travaux")):
        return charge["type_travaux"].replace("_", " ")
    if _texte_non_vide(charge.get("service")) and _texte_non_vide(libelle_service):
        return libelle_service
    return None


def construire_brouillon(
    charge: Mapping[str, Any], libelle_service: str | None = None, motif_service: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """`(brouillon, None)` si `consentement_demande_avis` est vrai, sa preuve est là et le client n'est
    pas connu insatisfait ; sinon `(None, motif)`. Jamais d'exception : un refus métier n'est pas une
    panne, la structure de `charge` (champs requis du WCT) est déjà garantie par le schéma JSON du
    catalogue avant que ceci ne soit appelé.

    `libelle_service` : le libellé fr-CA du service d'un WCT v2, résolu par l'adaptateur dans la
    taxonomie de l'instance (`opsys.taxonomie`) ; `None` si le WCT est v1 ou si le service n'est pas
    déclaré, auquel cas `motif_service` dit pourquoi et le brouillon le consigne (`avertissements`),
    plutôt que de taire l'absence de nature.

    `id` est un uuid5 déterministe dérivé de `wct_id` : le même chantier produit toujours le même
    identifiant de brouillon, condition nécessaire à l'idempotence côté adaptateur (`outils.py`).
    """
    motif = _motif_refus(charge)
    if motif is not None:
        return None, motif

    wct_id = charge["wct_id"]
    ville = charge.get("ville")
    nature_travaux = _nature_des_travaux(charge, libelle_service)
    texte = _GABARIT.format(lieu=_lieu_texte(ville, nature_travaux))

    canonique = json.dumps({"wct_id": wct_id, "type": "demande_avis"}, sort_keys=True, ensure_ascii=False)
    identifiant = str(uuid.uuid5(uuid.NAMESPACE_URL, canonique))

    avertissements = []
    if "service" in charge and nature_travaux is None:
        avertissements.append(motif_service or f"libellé du service {charge['service']!r} non résolu")

    brouillon = {
        "id": identifiant,
        "type": "demande_avis",
        "wct_id": wct_id,
        "intervention_id": charge["intervention_id"],
        "lead_id": charge["lead_id"],
        "ville": ville,
        "type_travaux": charge.get("type_travaux"),  # lead v1 ; None pour un v2
        "service": charge.get("service"),  # lead v2 (code) ; None pour un v1
        "nature_travaux": nature_travaux,  # ce que le texte en dit
        "texte": texte,
        "preuve_consentement": {
            "consentement_demande_avis": True,
            "recueilli_par": charge["consentement_recueilli_par"],
            "recueilli_le": charge["consentement_recueilli_le"],
            "version_texte": charge["consentement_version_texte"],
            "source": "wct_m4_travaux_termines",
            "wct_id": wct_id,
        },
        "avertissements": avertissements,
        "approval_status": "PROPOSE",  # invariant — jamais auto-envoyé (D-043)
    }
    return brouillon, None
