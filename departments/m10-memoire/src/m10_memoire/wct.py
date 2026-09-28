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
    """Mémorise le WCT reçu ; rend ``(maillon, None)``.

    Idempotent par ``wct_id`` (PLAN T1.2-e) : un WCT déjà mémorisé rend le maillon EXISTANT sans
    rien réécrire. Un WCT donné n'est censé arriver qu'une fois (`m4.travaux_termines` publie sous
    `evenement_id = wct_id`, ADR-0009 §3) ; le répartiteur ne rappelle d'ailleurs jamais cette
    fonction deux fois pour le même (evenement_id, consommateur). Mais cette garde-là seule ne
    protège pas contre une relivraison du MÊME fait sous un evenement_id DIFFÉRENT (producteur en
    défaut, rejeu manuel) : sans elle, un second appel écrirait un second maillon pour le même
    wct_id — un doublon mémoire, contrairement à `wct_recus.py` (M5/M6) et aux registres
    d'idempotence de M7/M8, qui vérifient déjà tous le wct_id avant d'écrire."""
    valide, code = valider_wct(wct_recu)
    if not valide:
        return None, code

    wct_id = wct_recu["wct_id"]
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") == "evenement_memorise" and maillon.get("wct_id") == wct_id:
            return maillon, None

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
