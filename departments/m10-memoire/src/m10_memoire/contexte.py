from . import contrats, validation

_TYPE_ENTREE_REVISION = "revision_signalee"
_CLE_REFERENCES = "references_decisions"

REJ_CONTEXTE_STRUCTURE_INVALIDE = "REJ-CONTEXTE-STRUCTURE-INVALIDE"
REJ_CONTEXTE_CHAMP_TEXTE_INVALIDE = "REJ-CONTEXTE-CHAMP-TEXTE-INVALIDE"
REJ_CONTEXTE_REFERENCES_ABSENTES = "REJ-CONTEXTE-REFERENCES-ABSENTES"
REJ_REFERENCE_LIGNE_INTROUVABLE = "REJ-REFERENCE-LIGNE-INTROUVABLE"
REJ_REFERENCE_TETE_INCOHERENTE = "REJ-REFERENCE-TETE-INCOHERENTE"
REJ_REFERENCE_CHAINE_INVALIDE = "REJ-REFERENCE-CHAINE-INVALIDE"
REJ_REFERENCE_REGISTRE_INVALIDE = "REJ-REFERENCE-REGISTRE-INVALIDE"


def contexte_suffisant(dossier):
    if not isinstance(dossier, dict):
        return False, REJ_CONTEXTE_STRUCTURE_INVALIDE

    champs_attendus = contrats.CHAMPS_EVENEMENT_MEMOIRE | {_CLE_REFERENCES}
    if set(dossier.keys()) != champs_attendus:
        return False, REJ_CONTEXTE_STRUCTURE_INVALIDE

    # Câblé sur validation.valider_evenement (patron EvenementMemoire) plutôt
    # que de réimplémenter sa propre boucle de contrôle des 5 champs texte —
    # validation.py était jusqu'ici du code mort, jamais appelé par un chemin
    # d'écriture réel.
    evenement = {champ: dossier[champ] for champ in contrats.CHAMPS_EVENEMENT_MEMOIRE}
    evenement_valide, _ = validation.valider_evenement(evenement)
    if not evenement_valide:
        return False, REJ_CONTEXTE_CHAMP_TEXTE_INVALIDE

    references = dossier[_CLE_REFERENCES]
    if not isinstance(references, list) or not references:
        return False, REJ_CONTEXTE_REFERENCES_ABSENTES

    return True, None


def tracer_refus_contexte(dossier, registre_cible, horodatage):
    suffisant, code = contexte_suffisant(dossier)
    if suffisant:
        return None, None

    # Câblé sur validation.construire_verdict : le verdict structuré {code,
    # detail} est tracé en plus du code brut (code_verdict, inchangé pour la
    # compatibilité des lecteurs existants), plutôt que de laisser
    # construire_verdict en code mort jamais appelé.
    verdict = validation.construire_verdict(code)
    ligne_id = registre_cible.ajouter(
        {
            "type_entree": _TYPE_ENTREE_REVISION,
            "horodatage": horodatage,
            "code_verdict": code,
            "verdict": verdict,
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

    # Le champ ``registre`` n'était vérifié que par sa PRÉSENCE (la clé), jamais
    # par la plausibilité de sa VALEUR : None, "" ou un type non texte
    # passaient. Une référence désigne toujours un registre nommé.
    if not isinstance(reference["registre"], str) or not reference["registre"]:
        return False, REJ_REFERENCE_REGISTRE_INVALIDE

    # L'existence d'un ligne_id ne prouve RIEN sur l'intégrité du registre : le
    # contenu d'un maillon peut être altéré sans que son ligne_id stocké ne change.
    # Une référence ne vaut donc que si la chaîne qui la porte est intacte —
    # objection CRITIQUE de la revue scellée (round 1), confirmée par mesure.
    chaine_valide, _ = registre_cible.valider_chaine()
    if not chaine_valide:
        return False, REJ_REFERENCE_CHAINE_INVALIDE

    maillons = registre_cible.lire()
    positions = {maillon.get("ligne_id"): indice for indice, maillon in enumerate(maillons)}

    if reference["ligne_id"] not in positions:
        return False, REJ_REFERENCE_LIGNE_INTROUVABLE

    # hash_tete doit être la tête de chaîne AU MOMENT de l'écriture : il ne
    # peut structurellement jamais désigner un maillon plus ANCIEN que
    # ligne_id (ce maillon n'existait pas encore quand l'antérieur était la
    # tête). Vérifier seulement qu'il EXISTE quelque part dans la chaîne
    # (comme avant ce correctif) ne détecte pas cette incohérence de position
    # — un hash_tete valide mais antérieur passait à tort.
    if reference["hash_tete"] not in positions:
        return False, REJ_REFERENCE_TETE_INCOHERENTE
    if positions[reference["hash_tete"]] < positions[reference["ligne_id"]]:
        return False, REJ_REFERENCE_TETE_INCOHERENTE

    return True, None
