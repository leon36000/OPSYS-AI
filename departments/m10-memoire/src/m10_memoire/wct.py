from . import classification, contrats, encodage

REJ_WCT_CHAMP_MANQUANT = "REJ-WCT-CHAMP-MANQUANT"
REJ_WCT_CHAMP_INATTENDU = "REJ-WCT-CHAMP-INATTENDU"
REJ_WCT_CONSOMMATEUR_M10_ABSENT = "REJ-WCT-CONSOMMATEUR-M10-ABSENT"
REJ_WCT_CONFLIT = "REJ-WCT-CONFLIT"


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

    Idempotent par ``wct_id`` : le même contenu rend le maillon EXISTANT sans rien réécrire.
    Un payload différent sous cet identifiant est un conflit nommé; il ne remplace pas l'historique.
    Un WCT donné n'est censé arriver qu'une fois (`m4.travaux_termines` publie sous
    `evenement_id = wct_id`, ADR-0009 §3) ; le répartiteur ne rappelle d'ailleurs jamais cette
    fonction deux fois pour le même (evenement_id, consommateur). Mais cette garde-là seule ne
    protège pas contre une relivraison du MÊME fait sous un evenement_id DIFFÉRENT (producteur en
    défaut, rejeu manuel) : sans elle, un second appel écrirait un second maillon pour le même
    wct_id — un doublon mémoire, contrairement à `wct_recus.py` (M5/M6) et aux registres
    d'idempotence de M7/M8, qui vérifient déjà tous le wct_id avant d'écrire.

    Seul un maillon WCT compte pour ce doublon (`classification.type_evenement`) : la variance de M6 et la
    rentabilité de M5 portent aussi le `wct_id`, et l'une d'elles reçue AVANT le WCT ne doit pas le faire passer
    pour déjà mémorisé (le WCT ne serait alors jamais écrit)."""
    valide, code = valider_wct(wct_recu)
    if not valide:
        return None, code

    wct_id = wct_recu["wct_id"]
    for maillon in registre_cible.lire():
        if classification.type_evenement(maillon) == classification.TYPE_WCT and maillon.get("wct_id") == wct_id:
            # Compare le WCT contractuel complet. Ne recalcule jamais hash_maillon de M4 : cette
            # empreinte n'est ni notre canon de comparaison, ni une preuve d'égalité du payload.
            # Les anciens maillons incomplets échouent fermé, plutôt que d'être déclarés identiques.
            if not all(champ in maillon for champ in contrats.CHAMPS_WCT):
                return None, REJ_WCT_CONFLIT
            deja_recu = {champ: maillon[champ] for champ in contrats.CHAMPS_WCT}
            empreinte_nouvelle = encodage.empreinte(wct_recu)
            empreinte_existante = encodage.empreinte(deja_recu)
            if empreinte_nouvelle != empreinte_existante:
                return None, REJ_WCT_CONFLIT
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
