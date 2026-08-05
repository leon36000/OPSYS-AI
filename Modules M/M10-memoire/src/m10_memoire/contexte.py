from . import contrats


_TYPE_ENTREE_REVISION = "revision_signalee"
_CLE_REFERENCES = "references_decisions"

REJ_CONTEXTE_STRUCTURE_INVALIDE = "REJ-CONTEXTE-STRUCTURE-INVALIDE"
REJ_CONTEXTE_CHAMP_TEXTE_INVALIDE = "REJ-CONTEXTE-CHAMP-TEXTE-INVALIDE"
REJ_CONTEXTE_REFERENCES_ABSENTES = "REJ-CONTEXTE-REFERENCES-ABSENTES"
REJ_REFERENCE_LIGNE_INTROUVABLE = "REJ-REFERENCE-LIGNE-INTROUVABLE"
REJ_REFERENCE_TETE_INCOHERENTE = "REJ-REFERENCE-TETE-INCOHERENTE"
REJ_REFERENCE_CHAINE_INVALIDE = "REJ-REFERENCE-CHAINE-INVALIDE"


def contexte_suffisant(dossier):
    if not isinstance(dossier, dict):
        return False, REJ_CONTEXTE_STRUCTURE_INVALIDE

    champs_attendus = contrats.CHAMPS_EVENEMENT_MEMOIRE | {_CLE_REFERENCES}
    if set(dossier.keys()) != champs_attendus:
        return False, REJ_CONTEXTE_STRUCTURE_INVALIDE

    for champ in contrats.CHAMPS_EVENEMENT_MEMOIRE:
        valeur = dossier[champ]
        if not isinstance(valeur, str) or not valeur:
            return False, REJ_CONTEXTE_CHAMP_TEXTE_INVALIDE

    references = dossier[_CLE_REFERENCES]
    if not isinstance(references, list) or not references:
        return False, REJ_CONTEXTE_REFERENCES_ABSENTES

    return True, None


def tracer_refus_contexte(dossier, registre_cible, horodatage):
    suffisant, code = contexte_suffisant(dossier)
    if suffisant:
        return None, None

    ligne_id = registre_cible.ajouter(
        {
            "type_entree": _TYPE_ENTREE_REVISION,
            "horodatage": horodatage,
            "code_verdict": code,
            "statut": "en_attente",
        }
    )

    for maillon in registre_cible.lire():
        if maillon.get("ligne_id") == ligne_id:
            return maillon, code

    raise RuntimeError("Maillon ajouté introuvable.")


def construire_reference(maillon, nom_registre, registre_cible):
    return {
        "ligne_id": maillon["ligne_id"],
        "registre": nom_registre,
        "hash_tete": registre_cible.tete(),
    }


def verifier_reference(reference, registre_cible):
    if (
        not isinstance(reference, dict)
        or set(reference.keys()) != contrats.CHAMPS_REFERENCE_MEMOIRE
    ):
        return False, REJ_REFERENCE_LIGNE_INTROUVABLE

    # L'existence d'un ligne_id ne prouve RIEN sur l'intégrité du registre : le
    # contenu d'un maillon peut être altéré sans que son ligne_id stocké ne change.
    # Une référence ne vaut donc que si la chaîne qui la porte est intacte —
    # objection CRITIQUE de la revue scellée (round 1), confirmée par mesure.
    chaine_valide, _ = registre_cible.valider_chaine()
    if not chaine_valide:
        return False, REJ_REFERENCE_CHAINE_INVALIDE

    maillons = registre_cible.lire()
    ligne_ids = {maillon.get("ligne_id") for maillon in maillons}

    if reference["ligne_id"] not in ligne_ids:
        return False, REJ_REFERENCE_LIGNE_INTROUVABLE

    if reference["hash_tete"] is not None and reference["hash_tete"] not in ligne_ids:
        return False, REJ_REFERENCE_TETE_INCOHERENTE

    return True, None
