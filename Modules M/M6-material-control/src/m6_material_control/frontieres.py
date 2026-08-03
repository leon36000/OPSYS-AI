from . import contrats


def verifier_frontieres(entree: dict) -> tuple[bool, str | None]:
    def contient_mot_interdit(valeur) -> bool:
        if isinstance(valeur, dict):
            for cle, valeur_associee in valeur.items():
                if cle in contrats.MOTS_INTERDITS_DOMAINE:
                    return True
                if contient_mot_interdit(valeur_associee):
                    return True
        elif isinstance(valeur, (list, tuple)):
            for element in valeur:
                if contient_mot_interdit(element):
                    return True
        return False

    if contient_mot_interdit(entree):
        return False, "REJ-FRONTIERE-VIOLEE"
    return True, None
