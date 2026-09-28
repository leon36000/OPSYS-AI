"""Contrat PreuvesCompletion — T1.1-b#3.

Validation structurelle du dossier de preuves exigé par ``m4_completer_intervention``
avant de clore une intervention. DEFINITION-PRODUIT.md §6/§9.7 (« Conditions
préalables (M4) : checklist terminée, photos après, matériel utilisé, temps
réel, notes d'imprévus, signature du client si requise ») : ce module porte la
part du dossier qui n'est pas déjà déterminée par le registre lui-même
(checklist, photos après, notes, signature) — le temps réel et le matériel
utilisé restent respectivement du ressort de l'outbox (pointages) et d'un
maillon distinct hors périmètre de cette tranche (M4.18, cf. audit M4 §2.6).

Module pur (patron ``contrats.py``) : aucun import d'``opsys``. Chaque manque
produit un rejet fail-closed NOMMÉ (le catalogue fermé de ``verdicts.py``),
jamais une valeur substituée — un champ absent n'est jamais traité comme vide
ni comme « non requis ».
"""
from typing import Any

from . import verdicts

CLES_PREUVES_COMPLETION = ("checklist_complete", "photos_apres", "notes", "signature")

__all__ = ["CLES_PREUVES_COMPLETION", "valider_preuves_completion"]


def valider_preuves_completion(preuves: Any, signature_requise: bool) -> tuple[bool, dict | None]:
    """Valide le contrat PreuvesCompletion.

    Args:
        preuves: dict candidat, attendu avec EXACTEMENT les clés de
            CLES_PREUVES_COMPLETION :
              - checklist_complete : booléen strict, doit valoir True (une
                checklist « en cours » ne clôt rien) ;
              - photos_apres : liste de chaînes NON VIDE (au moins une preuve
                photographique du travail terminé) ;
              - notes : chaîne (notes d'imprévus — vide toléré : « aucun
                imprévu » est une note légitime, contrairement à une checklist
                ou des photos, dont l'ABSENCE de contenu est le problème) ;
              - signature : chaîne non vide si `signature_requise`, sinon
                chaîne ou None.
        signature_requise: booléen fourni par l'appelant (dépend du client/du
            chantier) — jamais déduit ici.

    Ordre des contrôles, épinglé : structure -> checklist -> photos_apres ->
    notes -> signature_requise -> signature. Première faute rencontrée.

    Returns:
        (True, None) si les preuves sont complètes, (False, verdict) sinon.
    """
    # 1. Structure : objet, clés exactes (aucune manquante, aucune étrangère)
    if not isinstance(preuves, dict):
        return False, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="preuves_completion doit être un objet"
        )
    for cle in CLES_PREUVES_COMPLETION:
        if cle not in preuves:
            return False, verdicts.construire_verdict(
                "REJ-CHAMP-MANQUANT", detail=f"preuves_completion.{cle} manquant"
            )
    if set(preuves.keys()) != set(CLES_PREUVES_COMPLETION):
        return False, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="preuves_completion : clé étrangère"
        )

    # 2. checklist_complete : booléen strict, doit être vrai
    checklist_complete = preuves["checklist_complete"]
    if type(checklist_complete) is not bool:
        return False, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="checklist_complete doit être un booléen"
        )
    if checklist_complete is not True:
        return False, verdicts.construire_verdict(
            "REJ-CHAMP-VIDE", detail="checklist non terminée"
        )

    # 3. photos_apres : liste de chaînes non vide, non vides elles-mêmes
    photos_apres = preuves["photos_apres"]
    if not isinstance(photos_apres, list):
        return False, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="photos_apres doit être une liste"
        )
    if len(photos_apres) == 0:
        return False, verdicts.construire_verdict(
            "REJ-CHAMP-VIDE", detail="photos_apres vide"
        )
    for photo in photos_apres:
        if not isinstance(photo, str) or photo == "":
            return False, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE", detail="photos_apres : élément invalide"
            )

    # 4. notes : chaîne (vide tolérée, cf. docstring)
    notes = preuves["notes"]
    if not isinstance(notes, str):
        return False, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="notes doit être une chaîne"
        )

    # 5. signature_requise : booléen fourni par l'appelant
    if type(signature_requise) is not bool:
        return False, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="signature_requise doit être un booléen"
        )

    # 6. signature : exigée seulement si signature_requise
    signature = preuves["signature"]
    if signature_requise:
        if not isinstance(signature, str) or signature == "":
            return False, verdicts.construire_verdict(
                "REJ-CHAMP-MANQUANT", detail="signature requise mais absente"
            )
    else:
        if signature is not None and not isinstance(signature, str):
            return False, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE", detail="signature doit être une chaîne ou null"
            )

    return True, None
