import copy
from . import contrats_sortie
from . import stock
from . import validation


def _dernier_cout_unitaire_connu(chantier_id, materiau_id, registre):
    """
    Convention NEW-PROD-006 / issue #465 :
    - Pour une CONSOMMATION, le cout_unitaire n'est pas fourni par le formulaire
      (cles_ligne_attendues = {"materiau_id", "quantite"}).
    - Choix retenu : dériver du DERNIER mouvement RECEPTION connu pour le couple
      (chantier_id, materiau_id) dans le registre append-only.
    - Pourquoi dernier coût et non coût moyen pondéré (CMP) :
      * Le registre est append-only et hash-chaîné ; le dernier RECEPTION est
        déterministe en O(n) sans recalcul d'historique complet.
      * Le CMP nécessiterait de sommer quantités*coûts sur tout l'historique et
        de définir une politique d'arrondi / de devise non spécifiée nulle part.
      * Aucun test/code existant ne référence un CMP ; inventer un CMP serait
        une donnée de coût inventée sans justification tracée (interdit).
      * Dernier coût connu = traçabilité directe : chaque CONSOMMATION référence
        exactement le coût de la dernière entrée réelle, auditable via hash_maillon.
    - Si aucune RECEPTION antérieure n'existe pour ce matériau/chantier,
      retourner REJ-COUT-UNITAIRE-INTROUVABLE plutôt que d'inventer 0/None.
    """
    for maillon in reversed(registre.lire()):
        if (
            maillon.get("type_mouvement") == "RECEPTION"
            and maillon.get("chantier_id") == chantier_id
            and maillon.get("materiau_id") == materiau_id
        ):
            return maillon.get("cout_unitaire")
    return None


def consommer_materiaux(wct, formulaire, registre) -> tuple[dict | None, str | None]:
    ok, code = validation.valider_wct(wct)
    if not ok:
        return None, code

    ok, code = validation.valider_formulaire_consommation(formulaire, wct)
    if not ok:
        return None, code

    if not isinstance(formulaire["lignes_consommees"], list):
        return None, "REJ-FORMULAIRE-LIGNE-INVALIDE"

    cles_ligne_attendues = {"materiau_id", "quantite"}
    for ligne in formulaire["lignes_consommees"]:
        if not isinstance(ligne, dict) or set(ligne.keys()) != cles_ligne_attendues:
            return None, "REJ-FORMULAIRE-LIGNE-INVALIDE"
        if not (
            isinstance(ligne["quantite"], (int, float))
            and type(ligne["quantite"]) is not bool
        ):
            return None, "REJ-FORMULAIRE-LIGNE-INVALIDE"

    # 1. Vérification disponibilité stock via fonction existante (ne jamais confirmer en stock négatif)
    ok, code = stock.verifier_disponibilite_consommation(
        formulaire["chantier_id"], formulaire["lignes_consommees"], registre
    )
    if not ok:
        return None, code

    # 2. Résolution du cout_unitaire pour chaque ligne selon convention dernier RECEPTION connu
    mouvements_a_persister = []
    for ligne in formulaire["lignes_consommees"]:
        cout = _dernier_cout_unitaire_connu(
            formulaire["chantier_id"], ligne["materiau_id"], registre
        )
        if cout is None:
            return None, "REJ-COUT-UNITAIRE-INTROUVABLE"
        # Quantité stockée négative : deriver_stock_theorique somme RECEPTION+CONSOMMATION,
        # donc CONSOMMATION doit être négative pour décrémenter le stock théorique.
        # Le formulaire fournit une quantité positive consommée ; on persiste -quantite.
        mouvements_a_persister.append(
            {
                "type_mouvement": "CONSOMMATION",
                "chantier_id": formulaire["chantier_id"],
                "materiau_id": ligne["materiau_id"],
                "quantite": -ligne["quantite"],
                "cout_unitaire": cout,
            }
        )

    # 3. Persistance append-only AVANT confirmation ; propager l'échec si écriture échoue
    if mouvements_a_persister:
        _, erreur = registre.ajouter_lot(mouvements_a_persister)
        if erreur is not None:
            return None, erreur

    # 4. Construction du stock_restant après persistance (reflète la vérité du registre)
    stock_restant = []
    for ligne in formulaire["lignes_consommees"]:
        theorique_apres = stock.deriver_stock_theorique(
            formulaire["chantier_id"],
            ligne["materiau_id"],
            registre,
        )
        stock_restant.append(
            {
                "materiau_id": ligne["materiau_id"],
                "quantite": theorique_apres,
            }
        )

    return (
        contrats_sortie.construire_confirmation_consommation_terrain(
            formulaire["intervention_id"],
            formulaire["chantier_id"],
            formulaire["lignes_consommees"],
            stock_restant,
        ),
        None,
    )
