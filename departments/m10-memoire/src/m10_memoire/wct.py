from . import contrats


REJ_WCT_CHAMP_MANQUANT = "REJ-WCT-CHAMP-MANQUANT"
REJ_WCT_CHAMP_INATTENDU = "REJ-WCT-CHAMP-INATTENDU"
REJ_WCT_CONSOMMATEUR_M10_ABSENT = "REJ-WCT-CONSOMMATEUR-M10-ABSENT"


def valider_wct(wct_recu):
    if not isinstance(wct_recu, dict):
        return False, REJ_WCT_CHAMP_MANQUANT

    for champ in contrats.CHAMPS_WCT:
        if champ not in wct_recu:
            return False, REJ_WCT_CHAMP_MANQUANT

    for cle in wct_recu:
        if cle not in contrats.CHAMPS_WCT:
            return False, REJ_WCT_CHAMP_INATTENDU

    if contrats.CONSOMMATEUR_ATTENDU not in wct_recu["consommateurs_cibles"]:
        return False, REJ_WCT_CONSOMMATEUR_M10_ABSENT

    return True, None


def memoriser_wct(wct_recu, registre_cible):
    valide, code = valider_wct(wct_recu)
    if not valide:
        return None, code

    entree = {
        **wct_recu,
        "type_entree": "evenement_memorise",
        "horodatage": wct_recu["horodatage_completion"],
    }
    ligne_id = registre_cible.ajouter(entree)

    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return maillon, None

    return None, None
