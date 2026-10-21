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
  - Le consentement vient AVEC SA PREUVE (PLAN T4.17) : `consentement_marketing` vrai ne suffit plus,
    M4 y joint qui l'a recueilli, quand, et quel texte a été présenté (`consentement_recueilli_par`,
    `consentement_recueilli_le`, `consentement_version_texte`, posés par le serveur). Sans elle, un
    consentement que personne ne peut relire n'est pas documenté : refus.
  - Le RETRAIT du consentement (Loi 25) est un registre à part (`usine.retrait`), que l'adaptateur
    consulte AVANT ce module : un retrait bloque tout contenu de ce chantier. Ce module-ci ne connaît que
    le WCT ; il ne voit jamais un retrait, et ne prétend donc jamais qu'aucun n'existe.
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
from ..reputation.demande_avis import CLES_PREUVE

REFUS_CONSENTEMENT_ABSENT = "consentement_marketing absent (fail-closed) : aucun contenu public"
REFUS_CONSENTEMENT_FAUX = "consentement_marketing = false : le client n'a pas consenti au contenu public"
REFUS_PREUVE_ABSENTE = (
    "preuve du consentement marketing absente (fail-closed) : aucun contenu public sans qui l'a recueilli, "
    "quand, et quel texte a été présenté au client"
)
REFUS_AUCUNE_PHOTO = "aucune photo fournie : rien à préparer"
REFUS_WCT_ID_ABSENT = "wct_id absent de la charge (fail-closed) : identifiant de brouillon impossible"


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def verifier_consentement(charge: Mapping[str, Any]) -> str | None:
    """Fail-closed : `consentement_marketing` absent ou pas strictement `True` refuse, et un consentement
    sans sa PREUVE (les trois clés posées par M4) refuse aussi (`None` si accordé et prouvé). Le retrait du
    consentement n'est pas vu ici : le registre de retrait (`usine.retrait`) est consulté par l'adaptateur,
    avant ce module (voir docstring du module).

    Exposée (pas de `_` initial) pour que l'adaptateur (`outils.py`) et l'usine à contenu de chantier
    (`usine.chantier`) refusent tôt, AVANT de résoudre un profil de marque ou un détecteur, sur le motif le
    plus fondamental — mais `preparer_brouillon_contenu_public` ci-dessous la rappelle aussi elle-même :
    jamais de confiance aveugle en un appelant qui aurait sauté l'étape. Une seule règle de consentement
    pour tout le contenu public de M7."""
    if "consentement_marketing" not in charge:
        return REFUS_CONSENTEMENT_ABSENT
    if charge["consentement_marketing"] is not True:
        return REFUS_CONSENTEMENT_FAUX
    if not all(_texte_non_vide(charge.get(cle)) for cle in CLES_PREUVE):
        return REFUS_PREUVE_ABSENTE
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
            "recueilli_par": charge["consentement_recueilli_par"],
            "recueilli_le": charge["consentement_recueilli_le"],
            "version_texte": charge["consentement_version_texte"],
            "source": "wct_m4_travaux_termines",
            "wct_id": wct_id,
        },
        "revue_humaine_requise": revue_humaine_requise,
        "motifs_revue_humaine": motifs_revue,
        "seuil_confiance": seuil_confiance,
        "approval_status": "PROPOSE",  # invariant — jamais auto-publié (D-043)
    }
    return brouillon, None
