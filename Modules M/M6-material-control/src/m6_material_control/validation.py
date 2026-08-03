from . import contrats


def valider_wct(wct) -> tuple[bool, str | None]:
    if not isinstance(wct, dict):
        return False, "REJ-WCT-CHAMP-MANQUANT"

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

    for champ in contrats.CHAMPS_FORMULAIRE_CONSOMMATION:
        if champ not in formulaire:
            return False, "REJ-FORMULAIRE-WCT-INCOHERENT"

    for cle in formulaire:
        if cle not in contrats.CHAMPS_FORMULAIRE_CONSOMMATION:
            return False, "REJ-FORMULAIRE-WCT-INCOHERENT"

    if formulaire["wct_id"] != wct["wct_id"]:
        return False, "REJ-FORMULAIRE-WCT-INCOHERENT"

    return True, None
