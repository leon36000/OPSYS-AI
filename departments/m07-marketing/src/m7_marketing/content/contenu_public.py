"""Brouillon de contenu public (photo de chantier) — consentement + floutage (PLAN T4.3).

Doctrine :
  - `docs/departements/M7-audit.md` §3.5, §4-Phase1.4 ; `docs/produit/DEFINITION-PRODUIT.md` §7
    M7, garde-fous (« photo de client sans autorisation, adresse ou visage ou plaque visibles »
    = blocage).
  - Fail-closed (P2, AGENTS.md) : `consentement_marketing` absent ou faux refuse la préparation ;
    profil de marque absent ou non configuré (encore le gabarit, `brand.profil_client`) refuse
    aussi — jamais un contenu public composé sous l'identité d'OPSYS-AI ou un nom inventé
    (`SOUL.md`). Le consentement n'est jamais supposé : il vient tel quel de `charge`, jamais
    déduit — et `charge` elle-même vient exclusivement du WCT `m4.travaux_termines` déjà reçu par
    le bus (registre durable `wct_recus`, `outils.py`), jamais d'un argument fourni par
    l'appelant/le modèle (AGENTS.md « le LLM orchestre, il ne fournit jamais un fait »).
  - PAS de mécanisme de retrait de consentement : le catalogue `m4.travaux_termines.json` ne
    porte aucun champ de retrait, et aucun registre de retrait de consentement marketing n'existe
    aujourd'hui dans le dépôt (Loi 25, gestion des droits — à construire, voir `SOUL.md`/
    `README.md`). Ce module ne prétend donc PAS savoir si un consentement autrefois accordé a été
    retiré depuis — seul `consentement_marketing` du WCT reçu fait foi, tel quel.
  - Floutage déterministe obligatoire (`moderation.floutage`) pour chaque photo AVANT toute mise
    en file : toute détection sous le seuil de confiance fourni force `revue_humaine_requise`,
    jamais une publication automatique sur un doute de détection.
  - Jamais une publication : `approval_status` toujours "PROPOSE" (même invariant que
    `content/approval.py`, `reputation/demande_avis.py`, D-043). La publication réelle (N5,
    approbation signée du socle) reste hors de ce module et de son appelant.
  - Module pur : aucun import `opsys`. Seul l'adaptateur (`outils.py`) sait où persister le
    brouillon et où trouver un détecteur réel (ou constater qu'il est indisponible).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from ..brand.profil_client import verifier_profil_configure
from ..moderation.detection import Detecteur
from ..moderation.floutage import flouter_photo
from ..moderation.image import ImageSynthetique

REFUS_CONSENTEMENT_ABSENT = "consentement_marketing absent (fail-closed) : aucun contenu public"
REFUS_CONSENTEMENT_FAUX = "consentement_marketing = false : le client n'a pas consenti au contenu public"
REFUS_AUCUNE_PHOTO = "aucune photo fournie : rien à préparer"
REFUS_WCT_ID_ABSENT = "wct_id absent de la charge (fail-closed) : identifiant de brouillon impossible"


def verifier_consentement(charge: Mapping[str, Any]) -> str | None:
    """Fail-closed : `consentement_marketing` absent ou pas strictement `True` refuse (`None` si
    accordé). Aucune notion de « retrait » ici — pas de source de vérité pour ça aujourd'hui (voir
    docstring du module) : seul l'état tel que reçu du WCT fait foi.

    Exposée (pas de `_` initial) pour que l'adaptateur (`outils.py`) puisse refuser tôt, AVANT de
    résoudre un profil de marque ou un détecteur, sur le motif le plus fondamental — mais
    `preparer_brouillon_contenu_public` ci-dessous la rappelle aussi elle-même : jamais de
    confiance aveugle en un appelant qui aurait sauté l'étape."""
    if "consentement_marketing" not in charge:
        return REFUS_CONSENTEMENT_ABSENT
    if charge["consentement_marketing"] is not True:
        return REFUS_CONSENTEMENT_FAUX
    return None


def preparer_brouillon_contenu_public(
    charge: Mapping[str, Any],
    photos: Sequence[tuple[str, ImageSynthetique]],
    brand: Mapping[str, Any],
    detecteur: Detecteur,
    seuil_confiance: float,
) -> tuple[dict[str, Any] | None, str | None]:
    """`(brouillon, None)` si le consentement est accordé, le profil de marque est configuré, et
    le floutage réussit pour chaque photo ; sinon `(None, motif)`.

    `photos` est une séquence de `(reference, image)` déjà décodée en mémoire (voir
    `moderation.image` — le décodage d'un vrai fichier JPEG/PNG reste hors de ce module).

    Jamais d'exception métier : un refus n'est pas une panne (même doctrine que
    `reputation/demande_avis.py`). Un floutage qui échoue réellement (boîte de détection hors
    image, `moderation.image.DimensionInvalide`) reste, lui, une exception propagée — une erreur
    de détecteur n'est pas un refus métier ordinaire, l'appelant (`outils.py`) la traite comme un
    incident, pas comme un simple avis.
    """
    motif = verifier_consentement(charge)
    if motif is not None:
        return None, motif

    profil, motif = verifier_profil_configure(dict(brand))
    if motif is not None:
        return None, motif

    if not photos:
        return None, REFUS_AUCUNE_PHOTO

    wct_id = charge.get("wct_id")
    if not wct_id:
        return None, REFUS_WCT_ID_ABSENT

    photos_traitees: list[dict[str, Any]] = []
    revue_humaine_requise = False
    motifs_revue: list[str] = []
    for reference, image in photos:
        _, rapport = flouter_photo(reference, image, detecteur, seuil_confiance)
        photos_traitees.append(
            {
                "reference": reference,
                "detections": [
                    {
                        "type": t.detection.type,
                        "confiance": t.detection.confiance,
                        "floutee": t.floutee,
                        "doute": t.doute,
                    }
                    for t in rapport.detections
                ],
                "revue_humaine_requise": rapport.revue_humaine_requise,
            }
        )
        if rapport.revue_humaine_requise:
            revue_humaine_requise = True
            motifs_revue.append(rapport.motif_revue_humaine)  # type: ignore[arg-type]

    canonique = json.dumps({"wct_id": wct_id, "type": "contenu_public"}, sort_keys=True, ensure_ascii=False)
    identifiant = str(uuid.uuid5(uuid.NAMESPACE_URL, canonique))

    brouillon = {
        "id": identifiant,
        "type": "contenu_public",
        "wct_id": wct_id,
        "intervention_id": charge.get("intervention_id"),
        "lead_id": charge.get("lead_id"),
        "ville": charge.get("ville"),
        "type_travaux": charge.get("type_travaux"),  # lead v1 ; None pour un v2
        "service": charge.get("service"),  # lead v2 (code, PLAN T0.13-b) ; None pour un v1, jamais déduit
        "brand_name": profil["name"],  # type: ignore[index]
        "photos": photos_traitees,
        "preuve_consentement": {
            "consentement_marketing": charge.get("consentement_marketing"),
            "source": "wct_m4_travaux_termines",
            "wct_id": wct_id,
        },
        "revue_humaine_requise": revue_humaine_requise,
        "motifs_revue_humaine": motifs_revue,
        "seuil_confiance": seuil_confiance,
        "approval_status": "PROPOSE",  # invariant — jamais auto-publié (D-043)
    }
    return brouillon, None
