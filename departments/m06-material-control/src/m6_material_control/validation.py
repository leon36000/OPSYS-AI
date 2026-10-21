import math

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
        if cle not in contrats.CHAMPS_WCT and cle not in contrats.CHAMPS_WCT_OPTIONNELS:
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


def _valider_quantite_positive(quantite) -> tuple[bool, str | None]:
    """Même garde que consommer_materiaux (NEW-PROD-004) : rejette non-numérique, bool,
    NaN, +-inf, 0 et négatif. Partagée par le formulaire de fin de chantier et par
    variance_chantier pour rester cohérente avec la convention déjà en place."""
    if isinstance(quantite, bool) or not isinstance(quantite, (int, float)):
        return False, "REJ-LIGNE-MATERIAUX-QUANTITE-INVALIDE"
    if isinstance(quantite, float) and not math.isfinite(quantite):
        return False, "REJ-LIGNE-MATERIAUX-QUANTITE-INVALIDE"
    if quantite <= 0:
        return False, "REJ-LIGNE-MATERIAUX-QUANTITE-INVALIDE"
    return True, None


def _valider_ligne_materiaux_utilises(ligne) -> tuple[bool, str | None]:
    """Une ligne du formulaire de fin de chantier enrichi (PLAN T1.1-d, M6.10/M6.11).

    Partagée par valider_formulaire_materiaux_utilises (formulaire soumis par l'employé)
    et par variance_chantier (lignes_declarees fournies directement à
    m6_evaluer_variance_chantier) : même forme, même discipline fail-closed aux deux
    frontières.
    """
    if not isinstance(ligne, dict):
        return False, "REJ-LIGNE-MATERIAUX-STRUCTURE-INVALIDE"

    type_ligne = ligne.get("type_ligne")
    if type_ligne not in contrats.TYPES_LIGNE_MATERIAUX_UTILISES:
        return False, "REJ-LIGNE-MATERIAUX-TYPE-INVALIDE"

    if set(ligne.keys()) != contrats.CHAMPS_LIGNE_MATERIAUX_UTILISES_PAR_TYPE[type_ligne]:
        return False, "REJ-LIGNE-MATERIAUX-STRUCTURE-INVALIDE"

    if not isinstance(ligne.get("materiau_id"), str) or not ligne["materiau_id"]:
        return False, "REJ-LIGNE-MATERIAUX-STRUCTURE-INVALIDE"

    if not isinstance(ligne.get("unite"), str) or not ligne["unite"]:
        return False, "REJ-LIGNE-MATERIAUX-UNITE-INVALIDE"

    ok, code = _valider_quantite_positive(ligne.get("quantite"))
    if not ok:
        return False, code

    if type_ligne == "prevu":
        ok, code = _valider_quantite_positive(ligne.get("quantite_estimee"))
        if not ok:
            return False, code

    if type_ligne == "achat_terrain":
        photo_fournie = ligne.get("photo_fournie")
        recu_fourni = ligne.get("recu_fourni")
        if not isinstance(photo_fournie, bool) or not isinstance(recu_fourni, bool):
            return False, "REJ-LIGNE-MATERIAUX-STRUCTURE-INVALIDE"
        # Règle dure PLAN T1.1-d : un achat terrain sans photo NI reçu est un rejet
        # fail-closed nommé, pas une acceptation silencieuse (M6.11/M6.17).
        if not (photo_fournie or recu_fourni):
            return False, "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE"

    return True, None


def valider_formulaire_materiaux_utilises(formulaire, wct) -> tuple[bool, str | None]:
    """Formulaire de fin de chantier enrichi (PLAN T1.1-d) : lignes typées prevu/
    non_prevu/retour/perte/bris/achat_terrain. Étend CHAMPS_FORMULAIRE_CONSOMMATION
    sans le remplacer — m6_consommer_materiaux et valider_formulaire_consommation
    restent inchangés et verts."""
    if not isinstance(formulaire, dict):
        return False, "REJ-FORMULAIRE-MATERIAUX-STRUCTURE-INVALIDE"

    ok, code = frontieres.verifier_frontieres(formulaire)
    if not ok:
        return False, code

    if set(formulaire.keys()) != contrats.CHAMPS_FORMULAIRE_MATERIAUX_UTILISES:
        return False, "REJ-FORMULAIRE-MATERIAUX-STRUCTURE-INVALIDE"

    if formulaire["wct_id"] != wct["wct_id"]:
        return False, "REJ-FORMULAIRE-MATERIAUX-WCT-INCOHERENT"

    # PLAN T1.4-k : l'intervention du formulaire est celle du WCT lu à la source — jamais une autre
    # affirmée par l'appareil (le `wct_id` seul ne dit pas de quelle intervention l'appelant parle).
    if formulaire["intervention_id"] != wct["intervention_id"]:
        return False, "REJ-FORMULAIRE-MATERIAUX-INTERVENTION-INCOHERENTE"

    if not isinstance(formulaire["lignes_materiaux"], list) or not formulaire["lignes_materiaux"]:
        return False, "REJ-FORMULAIRE-MATERIAUX-STRUCTURE-INVALIDE"

    for ligne in formulaire["lignes_materiaux"]:
        ok, code = _valider_ligne_materiaux_utilises(ligne)
        if not ok:
            return False, code

    return True, None


def valider_besoins_estimes_chantier(besoins_estimes) -> tuple[bool, str | None]:
    """BesoinEstimeChantier (variance_chantier.py) : le « prévu » fourni en entrée par
    l'appelant (intake M3 -> M6 hors PLAN T1.1-d, PRD M6.4)."""
    if not isinstance(besoins_estimes, list):
        return False, "REJ-BESOIN-CHANTIER-STRUCTURE-INVALIDE"

    materiaux_vus: set[str] = set()
    for besoin in besoins_estimes:
        if not isinstance(besoin, dict) or set(besoin.keys()) != contrats.CHAMPS_BESOIN_ESTIME_CHANTIER:
            return False, "REJ-BESOIN-CHANTIER-STRUCTURE-INVALIDE"

        ok, code = frontieres.verifier_frontieres(besoin)
        if not ok:
            return False, code

        materiau_id = besoin.get("materiau_id")
        if not isinstance(materiau_id, str) or not materiau_id:
            return False, "REJ-BESOIN-CHANTIER-STRUCTURE-INVALIDE"
        if materiau_id in materiaux_vus:
            # Fail-closed : agréger silencieusement deux lignes du même matériau
            # inventerait une quantité estimée que personne n'a fournie telle quelle.
            return False, "REJ-BESOIN-CHANTIER-DUPLIQUE"
        materiaux_vus.add(materiau_id)

        if not isinstance(besoin.get("unite"), str) or not besoin["unite"]:
            return False, "REJ-LIGNE-MATERIAUX-UNITE-INVALIDE"

        ok, code = _valider_quantite_positive(besoin.get("quantite_estimee"))
        if not ok:
            return False, code

    return True, None


def valider_lignes_declarees_chantier(lignes_declarees) -> tuple[bool, str | None]:
    """Réel déclaré (variance_chantier.py) : même forme de ligne que le formulaire de fin
    de chantier (_valider_ligne_materiaux_utilises), validée à nouveau ici parce que
    m6_evaluer_variance_chantier est un point d'entrée public indépendant — il ne suppose
    jamais que l'appelant a déjà validé via m6_soumettre_materiaux_utilises."""
    if not isinstance(lignes_declarees, list):
        return False, "REJ-VARIANCE-CHANTIER-LIGNES-INVALIDES"

    for ligne in lignes_declarees:
        ok, code = _valider_ligne_materiaux_utilises(ligne)
        if not ok:
            return False, code

    return True, None


def valider_seuil_variance_chantier(seuil_pourcentage) -> tuple[bool, str | None]:
    """Seuil de criticité (PLAN T1.1-d point 3) : toujours fourni par l'appelant, jamais
    codé en dur ici ni ailleurs dans variance_chantier.py."""
    if isinstance(seuil_pourcentage, bool) or not isinstance(seuil_pourcentage, (int, float)):
        return False, "REJ-SEUIL-VARIANCE-CHANTIER-INVALIDE"
    if isinstance(seuil_pourcentage, float) and not math.isfinite(seuil_pourcentage):
        return False, "REJ-SEUIL-VARIANCE-CHANTIER-INVALIDE"
    if seuil_pourcentage <= 0:
        return False, "REJ-SEUIL-VARIANCE-CHANTIER-INVALIDE"
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
