from . import contrats, frontieres

# Ordre épinglé (docs/bmad/03-ARCHITECTURE.md, responsabilité de validation.py) :
# frontière → structure → correspondance. Bug NEW-PROD corrigé ici : frontieres.py
# existait mais n'était appelé nulle part dans le pipeline réel — une clé interdite
# comme « virement » traversait donc n'importe quelle entrée sans être détectée
# (seul un appel direct et isolé à frontieres.verifier_frontieres la voyait).


def valider_wct(wct) -> tuple[bool, str | None]:
    if not isinstance(wct, dict):
        return False, "REJ-WCT-CHAMP-MANQUANT"

    ok, code = frontieres.verifier_frontieres(wct)
    if not ok:
        return False, code

    for champ in contrats.CHAMPS_WCT:
        if champ not in wct:
            return False, "REJ-WCT-CHAMP-MANQUANT"

    for cle in wct:
        if cle not in contrats.CHAMPS_WCT:
            return False, "REJ-WCT-CHAMP-INATTENDU"

    if contrats.CONSOMMATEUR_ATTENDU not in wct["consommateurs_cibles"]:
        return False, "REJ-WCT-CONSOMMATEUR-M6-ABSENT"

    return True, None


def valider_formulaire_consommation(formulaire, wct) -> tuple[bool, str | None]:
    if not isinstance(formulaire, dict):
        return False, "REJ-FORMULAIRE-WCT-INCOHERENT"

    ok, code = frontieres.verifier_frontieres(formulaire)
    if not ok:
        return False, code

    for champ in contrats.CHAMPS_FORMULAIRE_CONSOMMATION:
        if champ not in formulaire:
            return False, "REJ-FORMULAIRE-WCT-INCOHERENT"

    for cle in formulaire:
        if cle not in contrats.CHAMPS_FORMULAIRE_CONSOMMATION:
            return False, "REJ-FORMULAIRE-WCT-INCOHERENT"

    if formulaire["wct_id"] != wct["wct_id"]:
        return False, "REJ-FORMULAIRE-WCT-INCOHERENT"

    return True, None


def valider_bon_demande(bon_demande) -> tuple[bool, str | None]:
    if not isinstance(bon_demande, dict):
        return False, "REJ-BON-DEMANDE-STRUCTURE-INVALIDE"

    ok, code = frontieres.verifier_frontieres(bon_demande)
    if not ok:
        return False, code

    if set(bon_demande.keys()) != contrats.CHAMPS_BON_DEMANDE:
        return False, "REJ-BON-DEMANDE-STRUCTURE-INVALIDE"

    if not isinstance(bon_demande["lignes_demandees"], list) or not bon_demande["lignes_demandees"]:
        return False, "REJ-BON-DEMANDE-STRUCTURE-INVALIDE"
    for ligne in bon_demande["lignes_demandees"]:
        if not isinstance(ligne, dict) or set(ligne.keys()) != contrats.CHAMPS_LIGNE_DEMANDEE:
            return False, "REJ-BON-DEMANDE-STRUCTURE-INVALIDE"

    return True, None


def valider_reception_po(reception_po) -> tuple[bool, str | None]:
    if not isinstance(reception_po, dict):
        return False, "REJ-RECEPTION-STRUCTURE-INVALIDE"

    ok, code = frontieres.verifier_frontieres(reception_po)
    if not ok:
        return False, code

    if set(reception_po.keys()) != contrats.CHAMPS_RECEPTION_PO:
        return False, "REJ-RECEPTION-STRUCTURE-INVALIDE"

    if not isinstance(reception_po["lignes_recues"], list):
        return False, "REJ-RECEPTION-STRUCTURE-INVALIDE"
    for ligne in reception_po["lignes_recues"]:
        if not isinstance(ligne, dict) or set(ligne.keys()) != contrats.CHAMPS_LIGNE_RECUE:
            return False, "REJ-RECEPTION-STRUCTURE-INVALIDE"

    return True, None


def valider_catalogue(catalogue) -> tuple[bool, str | None]:
    # Fail-closed mais PERMISSIF par design (PRD §5.3) : un catalogue absent ou
    # partiel n'est jamais une erreur bloquante globale — chaque matériau non
    # couvert passe simplement en résolution FALLBACK/INDETERMINE (catalogue.py).
    # Seule une clé interdite (frontière de domaine) bloque ici.
    if catalogue is None:
        return True, None
    ok, code = frontieres.verifier_frontieres(catalogue)
    if not ok:
        return False, code
    if not isinstance(catalogue, dict):
        return False, "REJ-CATALOGUE-STRUCTURE-INVALIDE"
    return True, None


def valider_comptage(comptage) -> tuple[bool, str | None]:
    if not isinstance(comptage, dict):
        return False, "REJ-COMPTAGE-STRUCTURE-INVALIDE"

    ok, code = frontieres.verifier_frontieres(comptage)
    if not ok:
        return False, code

    if set(comptage.keys()) != contrats.CHAMPS_COMPTAGE:
        return False, "REJ-COMPTAGE-STRUCTURE-INVALIDE"

    return True, None


def valider_seuils_reorder(seuils) -> tuple[bool, str | None]:
    if seuils is None:
        return True, None
    if not isinstance(seuils, list):
        return False, "REJ-SEUIL-REORDER-STRUCTURE-INVALIDE"
    for seuil in seuils:
        if not isinstance(seuil, dict):
            return False, "REJ-SEUIL-REORDER-STRUCTURE-INVALIDE"
        ok, code = frontieres.verifier_frontieres(seuil)
        if not ok:
            return False, code
        if set(seuil.keys()) != contrats.CHAMPS_SEUIL_REORDER:
            return False, "REJ-SEUIL-REORDER-STRUCTURE-INVALIDE"
    return True, None
