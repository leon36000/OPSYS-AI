"""Brouillon de contenu public (photo de chantier) — consentement + floutage (PLAN T4.3).

Doctrine :
  - `docs/departements/M7-audit.md` §3.5, §4-Phase1.4 ; `docs/produit/DEFINITION-PRODUIT.md` §7
    M7, garde-fous (« photo de client sans autorisation, adresse ou visage ou plaque visibles »
    = blocage).
  - Fail-closed (P2, AGENTS.md) : `consentement_marketing` absent, faux ou retiré refuse la
    préparation ; profil de marque absent ou non configuré (encore le gabarit,
    `brand.profil_client`) refuse aussi — jamais un contenu public composé sous l'identité
    d'OPSYS-AI ou un nom inventé (`SOUL.md`). Le consentement n'est jamais supposé : il vient
    tel quel de la charge fournie par l'appelant (WCT `m4.travaux_termines`), jamais déduit.
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
REFUS_CONSENTEMENT_RETIRE = "consentement_marketing_retire = true : consentement retiré, aucun contenu public"
REFUS_AUCUNE_PHOTO = "aucune photo fournie : rien à préparer"
REFUS_WCT_ID_ABSENT = "wct_id absent de la charge (fail-closed) : identifiant de brouillon impossible"


def _motif_consentement(charge: Mapping[str, Any]) -> str | None:
    """Fail-closed, dans l'ordre : un retrait explicite prime toujours sur l'état d'origine du
    consentement — un client qui retire son consentement APRÈS l'avoir donné doit être refusé,
    jamais republié sur la foi d'un `consentement_marketing: true` périmé."""
    if charge.get("consentement_marketing_retire") is True:
        return REFUS_CONSENTEMENT_RETIRE
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
    """`(brouillon, None)` si le consentement est accordé (et non retiré), le profil de marque
    est configuré, et le floutage réussit pour chaque photo ; sinon `(None, motif)`.

    `photos` est une séquence de `(reference, image)` déjà décodée en mémoire (voir
    `moderation.image` — le décodage d'un vrai fichier JPEG/PNG reste hors de ce module).

    Jamais d'exception métier : un refus n'est pas une panne (même doctrine que
    `reputation/demande_avis.py`). Un floutage qui échoue réellement (boîte de détection hors
    image, `moderation.image.DimensionInvalide`) reste, lui, une exception propagée — une erreur
    de détecteur n'est pas un refus métier ordinaire, l'appelant (`outils.py`) la traite comme un
    incident, pas comme un simple avis.
    """
    motif = _motif_consentement(charge)
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
        "type_travaux": charge.get("type_travaux"),
        "brand_name": profil["name"],  # type: ignore[index]
        "photos": photos_traitees,
        "preuve_consentement": {
            "consentement_marketing": charge.get("consentement_marketing"),
            "consentement_marketing_retire": charge.get("consentement_marketing_retire", False),
            "source": "wct_m4_travaux_termines",
            "wct_id": wct_id,
        },
        "revue_humaine_requise": revue_humaine_requise,
        "motifs_revue_humaine": motifs_revue,
        "seuil_confiance": seuil_confiance,
        "approval_status": "PROPOSE",  # invariant — jamais auto-publié (D-043)
    }
    return brouillon, None
