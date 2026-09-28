import math

from . import contrats_sortie
from . import reception
from . import reorder
from . import stock
from . import validation
from . import variance


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

        # NEW-PROD-004 : rejette 0, négatif, NaN, +inf, -inf. Aucun test existant
        # ne valide quantite == 0 comme cas légitime ; si un tel cas était prouvé,
        # cette garde devrait être affinée plutôt que de casser silencieusement.
        quantite = ligne["quantite"]
        if isinstance(quantite, float) and not math.isfinite(quantite):
            return None, "REJ-FORMULAIRE-LIGNE-INVALIDE"
        if quantite <= 0:
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


def soumettre_materiaux_utilises(wct, formulaire, registre) -> tuple[dict | None, str | None]:
    """Formulaire de fin de chantier enrichi (PLAN T1.1-d/d2, M6.10/M6.11).

    NOUVELLE fonction, distincte de consommer_materiaux : elle ne le remplace pas, ne
    l'appelle pas — m6_consommer_materiaux garde son contrat {materiau_id, quantite}
    exact et ses tests existants restent verts. garde_ecriture_stock de conformite.py
    l'autorise explicitement (DESIGNATION_TYPE_MOUVEMENT) pour CONSOMMATION, en plus de
    consommer_materiaux, et pour RETOUR/PERTE/BRIS, qu'elle est seule à écrire.

    Étapes : validation fail-closed du formulaire enrichi à 6 types de ligne (prevu/
    non_prevu/retour/perte/bris/achat_terrain, REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE si un
    achat terrain n'a ni photo ni reçu) -> idempotence par wct_id (REJ-DECLARATION-DEJA-
    SOUMISE : une déclaration par WCT, jamais deux — la corriger est une autre
    fonctionnalité, non faite ici) -> résolution du coût unitaire par ligne, même règle
    fail-closed que consommer_materiaux (_dernier_cout_unitaire_connu,
    REJ-COUT-UNITAIRE-INTROUVABLE, jamais de coût inventé) -> écriture tout-ou-rien
    (ajouter_lot) des mouvements typés :
      - prevu/non_prevu/achat_terrain -> CONSOMMATION (quantité négative, sort du stock) ;
      - retour -> RETOUR (quantité positive, réintègre le stock théorique) ;
      - perte/bris -> PERTE/BRIS (quantité négative, sort du stock SANS être une
        consommation de chantier — type distinct, jamais confondu avec CONSOMMATION).
    stock.deriver_stock_theorique inclut déjà ces types (PLAN T1.1-d2) : le théorique
    reste cohérent immédiatement après l'écriture, sans code spécial ici.

    variance_chantier.comparer_depuis_registre (PLAN T1.1-d2 point 3) relit ensuite ces
    mêmes mouvements, filtrés par wct_id, pour construire le « réel déclaré » sans que
    l'appelant ait besoin de le retransporter.
    """
    ok, code = validation.valider_wct(wct)
    if not ok:
        return None, code

    ok, code = validation.valider_formulaire_materiaux_utilises(formulaire, wct)
    if not ok:
        return None, code

    wct_id = wct["wct_id"]
    if any(mouvement.get("wct_id") == wct_id for mouvement in registre.lire()):
        return None, "REJ-DECLARATION-DEJA-SOUMISE"

    chantier_id = formulaire["chantier_id"]
    mouvements_a_persister = []
    for ligne in formulaire["lignes_materiaux"]:
        materiau_id = ligne["materiau_id"]
        cout = _dernier_cout_unitaire_connu(chantier_id, materiau_id, registre)
        if cout is None:
            return None, "REJ-COUT-UNITAIRE-INTROUVABLE"

        type_ligne = ligne["type_ligne"]
        if type_ligne in ("prevu", "non_prevu", "achat_terrain"):
            mouvements_a_persister.append(
                {
                    "type_mouvement": "CONSOMMATION",
                    "chantier_id": chantier_id,
                    "materiau_id": materiau_id,
                    "quantite": -ligne["quantite"],
                    "cout_unitaire": cout,
                    "wct_id": wct_id,
                }
            )
        elif type_ligne == "retour":
            mouvements_a_persister.append(
                {
                    "type_mouvement": "RETOUR",
                    "chantier_id": chantier_id,
                    "materiau_id": materiau_id,
                    "quantite": ligne["quantite"],
                    "cout_unitaire": cout,
                    "wct_id": wct_id,
                }
            )
        elif type_ligne == "perte":
            mouvements_a_persister.append(
                {
                    "type_mouvement": "PERTE",
                    "chantier_id": chantier_id,
                    "materiau_id": materiau_id,
                    "quantite": -ligne["quantite"],
                    "cout_unitaire": cout,
                    "wct_id": wct_id,
                }
            )
        else:  # "bris"
            mouvements_a_persister.append(
                {
                    "type_mouvement": "BRIS",
                    "chantier_id": chantier_id,
                    "materiau_id": materiau_id,
                    "quantite": -ligne["quantite"],
                    "cout_unitaire": cout,
                    "wct_id": wct_id,
                }
            )

    _, erreur = registre.ajouter_lot(mouvements_a_persister)
    if erreur is not None:
        return None, erreur

    return (
        contrats_sortie.construire_confirmation_materiaux_utilises(
            formulaire["intervention_id"],
            chantier_id,
            formulaire["lignes_materiaux"],
        ),
        None,
    )


def enregistrer_reception(bon_demande, reception_po, catalogue, registre, seuils=None):
    """Orchestrateur RECEPTION (docs/bmad/03-ARCHITECTURE.md l.51, DA-M6-11).

    Bug NEW-PROD corrigé ici : cette fonction n'existait pas. `reception.py`
    (traiter_reception) est une fonction PURE qui ne persiste rien ; sans point
    d'écriture, un matériau reçu n'atteignait jamais le registre, et toute
    consommation ultérieure du même matériau échouait par REJ-STOCK-INSUFFISANT
    faute de stock réellement enregistré.

    Étapes : valider (frontières + structure) -> dériver (accusé de réception,
    logique pure) -> écrire (N maillons RECEPTION, tout-ou-rien via ajouter_lot,
    DA-M6-08) -> construire SignalPoAPayer (jamais si montant indéterminé,
    DA-M6-13) -> réévaluer le reorder pour chaque matériau touché.
    """
    ok, code = validation.valider_bon_demande(bon_demande)
    if not ok:
        return None, code
    ok, code = validation.valider_reception_po(reception_po)
    if not ok:
        return None, code
    ok, code = validation.valider_catalogue(catalogue)
    if not ok:
        return None, code
    ok, code = validation.valider_seuils_reorder(seuils)
    if not ok:
        return None, code

    accuse = reception.traiter_reception(bon_demande, reception_po, catalogue, registre)

    if not accuse["lignes"]:
        # DA-M6-12 : PO introuvable ou lignes non appariables -> zéro écriture.
        return {
            "accuse_reception": {**accuse, "hash_maillon": registre.hash_tete()},
            "signal_po_a_payer": None,
            "signaux_reorder": [],
        }, None

    mouvements = [
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": accuse["chantier_id"],
            "materiau_id": ligne["materiau_id"],
            "quantite": ligne["quantite_recue"],
            "cout_unitaire": ligne["cout_unitaire_resolu"],
        }
        for ligne in accuse["lignes"]
    ]

    maillons, erreur = registre.ajouter_lot(mouvements)
    if erreur is not None:
        return None, erreur

    accuse_final = {**accuse, "hash_maillon": maillons[-1]["hash_maillon"]}

    signal_po_a_payer = None
    if accuse["montant_total_estime"] is not None:
        signal_po_a_payer = {
            "po_id": accuse["po_id"],
            "chantier_id": accuse["chantier_id"],
            "montant_total_estime": accuse["montant_total_estime"],
            "bareme_version": accuse["bareme_version"],
            "hash_maillon": maillons[-1]["hash_maillon"],
        }

    signaux_reorder = []
    if seuils:
        materiaux_touches = sorted({ligne["materiau_id"] for ligne in accuse["lignes"]})
        for materiau_id in materiaux_touches:
            signal = reorder.evaluer_reorder(accuse["chantier_id"], materiau_id, seuils, registre)
            if signal is not None:
                signaux_reorder.append(signal)

    return {
        "accuse_reception": accuse_final,
        "signal_po_a_payer": signal_po_a_payer,
        "signaux_reorder": signaux_reorder,
    }, None


def soumettre_comptage(comptage, registre):
    """Orchestrateur VARIANCE_INVENTAIRE (docs/bmad/03-ARCHITECTURE.md l.51, DA-M6-11).

    Bug NEW-PROD corrigé ici : cette fonction n'existait pas non plus — aucun
    chemin n'écrivait de maillon VARIANCE_INVENTAIRE au registre. Quand le verdict
    est INDETERMINE (aucun mouvement théorique préalable), rien n'est écrit : un
    écart de 0 contre un théorique fabriqué à zéro serait une donnée inventée
    (DA-M6-09) — seul un écart RÉEL rejoint le registre d'audit (R-020).
    """
    ok, code = validation.valider_comptage(comptage)
    if not ok:
        return None, code

    resultat = variance.evaluer_variance(
        comptage["chantier_id"],
        comptage["materiau_id"],
        comptage["quantite_comptee"],
        registre,
    )

    if resultat["verdict_variance"] == "INDETERMINE":
        hash_maillon = registre.hash_tete()
    else:
        mouvement = {
            "type_mouvement": "VARIANCE_INVENTAIRE",
            "chantier_id": resultat["chantier_id"],
            "materiau_id": resultat["materiau_id"],
            "quantite": resultat["ecart"],
            "cout_unitaire": None,
        }
        maillon, erreur = registre.ajouter(mouvement)
        if erreur is not None:
            return None, erreur
        hash_maillon = maillon["hash_maillon"]

    return {
        "chantier_id": resultat["chantier_id"],
        "materiau_id": resultat["materiau_id"],
        "verdict_variance": resultat["verdict_variance"],
        "quantite_theorique": resultat["quantite_theorique"],
        "quantite_comptee": resultat["quantite_comptee"],
        "ecart": resultat["ecart"],
        "note_investigation": resultat["note_investigation"],
        "horodatage": comptage["horodatage"],
        "hash_maillon": hash_maillon,
    }, None
