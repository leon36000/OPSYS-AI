from decimal import Decimal, InvalidOperation

from .decimal_exact import (
    AccumulateurDecimalExact,
    DecimalIndeterminable,
    float_projection_exacte_ou_refus,
    somme_decimaux_exactement,
    soustraire_exactement,
)
from .decimal_exact import (
    texte_decimal_exact as _texte_decimal_exact,
)

MOTIF_REORDER_INDETERMINE = "stock_localise_par_chantier_non_reconstructible"


def texte_decimal_exact(valeur):
    """Réexport rétrocompatible du formateur décimal exact partagé."""
    return _texte_decimal_exact(valeur)


def paires_indeterminees(seuils, mouvements, transferts_emplacements):
    """Paires seuil/matériau que les transferts ne permettent pas d'évaluer.

    Un transfert C5 dont la `reference_source` pointe vers un mouvement RECEPTION
    exact est attribué à ce mouvement et à son chantier. Seules les quantités de
    cette source encore hors main rendent cette paire indéterminée. Un transfert
    historique sans référence, ou une référence non résolue, ne permet pas cette
    attribution : toutes les paires fournies pour ce matériau restent alors
    indéterminées. Si la chaîne d'emplacements n'est pas disponible, toutes les
    paires fournies d'un matériau portant un mouvement de stock le restent aussi,
    sans agrégation des chantiers. Aucun stock global ni seuil n'est fabriqué.
    """
    if not isinstance(seuils, list) or not seuils:
        return []
    from . import emplacements
    from . import registre as registre_module

    mouvements = list(mouvements or [])
    paires = {
        (seuil["chantier_id"], seuil["materiau_id"])
        for seuil in seuils
        if isinstance(seuil, dict)
        and isinstance(seuil.get("chantier_id"), str)
        and seuil["chantier_id"]
        and isinstance(seuil.get("materiau_id"), str)
        and seuil["materiau_id"]
    }
    if not paires:
        return []

    paires_par_materiau = {}
    for chantier_id, materiau_id in paires:
        paires_par_materiau.setdefault(materiau_id, set()).add(chantier_id)

    if transferts_emplacements is None:
        # Absence de chaîne ≠ chaîne consultée vide. Sans l'archive, les mouvements
        # de stock ne suffisent pas à prouver la répartition physique par chantier.
        from . import stock

        # Toute paire du matériau peut être affectée même si des mouvements sur
        # d'autres chantiers annulent le total global. Reprendre la liste canonique
        # des types qui contribuent au stock théorique, sans agréger les chantiers.
        materiaux_concernes = {
            mouvement.get("materiau_id")
            for mouvement in mouvements
            if isinstance(mouvement, dict)
            and mouvement.get("type_mouvement") in stock._TYPES_STOCK_THEORIQUE
            and isinstance(mouvement.get("materiau_id"), str)
        }
        return _paires_toutes({
            materiau_id: chantiers
            for materiau_id, chantiers in paires_par_materiau.items()
            if materiau_id in materiaux_concernes
        })

    transferts_emplacements = list(transferts_emplacements)
    par_materiau = {}
    for maillon in transferts_emplacements:
        if (
            isinstance(maillon, dict)
            and maillon.get("type_entree") == emplacements.TYPE_TRANSFERT
            and isinstance(maillon.get("materiau_id"), str)
        ):
            par_materiau.setdefault(maillon["materiau_id"], []).append(maillon)

    incertains = set()
    chaines_emplacements_valides = False
    if par_materiau:
        try:
            chaines_emplacements_valides = emplacements.valider_chaine(transferts_emplacements)[0]
        except (KeyError, TypeError, ValueError, InvalidOperation):
            chaines_emplacements_valides = False
        if not chaines_emplacements_valides:
            # La source n'est pas fiable si sa propre chaîne d'audit est rompue.
            return _paires_toutes(paires_par_materiau)

    # Les anciennes chaînes de mouvements restent valides; on ne s'appuie sur la
    # source qu'après validation de la chaîne primaire qui porte ses identifiants.
    indices = {}
    index_par_hash = {}
    chaine_principale_valide = False
    if par_materiau:
        try:
            chaine_principale_valide = registre_module.Registre(maillons=mouvements).valider_chaine()[0]
        except (KeyError, TypeError, ValueError, InvalidOperation):
            chaine_principale_valide = False
        if chaine_principale_valide:
            for mouvement in mouvements:
                index, hash_maillon = mouvement.get("index"), mouvement.get("hash_maillon")
                if type(index) is not int or not isinstance(hash_maillon, str):
                    chaine_principale_valide = False
                    break
                if index in indices or hash_maillon in index_par_hash:
                    chaine_principale_valide = False
                    break
                indices[index] = mouvement
                index_par_hash[hash_maillon] = index
        if not chaine_principale_valide:
            return _paires_toutes(paires_par_materiau)

    incertains_materiaux = set()
    for materiau_id, transferts in par_materiau.items():
        if materiau_id not in paires_par_materiau:
            continue
        if any("reference_source" not in transfert for transfert in transferts):
            # Les transferts antérieurs à C5 ne peuvent pas être réattribués.
            incertains_materiaux.add(materiau_id)
            continue

        termes_hors_main_par_source = {}
        quantites_source = {}
        for transfert in transferts:
            reference = transfert.get("reference_source")
            source_ref = reference.get("mouvement") if isinstance(reference, dict) else None
            if not isinstance(source_ref, dict):
                incertains_materiaux.add(materiau_id)
                break
            source_index, source_hash = source_ref.get("index"), source_ref.get("hash_maillon")
            source = indices.get(source_index)
            if (
                source is None
                or source.get("hash_maillon") != source_hash
                or source.get("type_mouvement") != "RECEPTION"
                or source.get("materiau_id") != materiau_id
                or not isinstance(source.get("chantier_id"), str)
                or not source.get("chantier_id")
            ):
                incertains_materiaux.add(materiau_id)
                break
            tete_index = index_par_hash.get(reference.get("hash_reception"))
            tete = indices.get(tete_index)
            if (
                tete is None
                or tete_index < source_index
                or tete.get("type_mouvement") != "RECEPTION"
                or tete.get("chantier_id") != source.get("chantier_id")
            ):
                incertains_materiaux.add(materiau_id)
                break
            try:
                quantite = Decimal(str(transfert["quantite"]))
                quantite_source = Decimal(str(source["quantite"]))
                origine, refus_origine = emplacements.normaliser(transfert["de"])
                destination, refus_destination = emplacements.normaliser(transfert["vers"])
            except (KeyError, TypeError, ValueError, InvalidOperation):
                incertains_materiaux.add(materiau_id)
                break
            if (
                refus_origine is not None
                or refus_destination is not None
                or origine != transfert["de"]
                or destination != transfert["vers"]
                or not quantite.is_finite()
                or not quantite_source.is_finite()
                or quantite <= 0
                or quantite_source <= 0
            ):
                incertains_materiaux.add(materiau_id)
                break

            origine = emplacements.cle(origine).split(":", 1)[0]
            destination = emplacements.cle(destination).split(":", 1)[0]
            source_cle = (source_index, source_hash)
            quantites_source[source_cle] = (source, quantite_source)
            termes_source = termes_hors_main_par_source.setdefault(source_cle, [])
            if destination in emplacements.EMPLACEMENTS_HORS_MAIN:
                termes_source.append((quantite, 1))
            if origine in emplacements.EMPLACEMENTS_HORS_MAIN:
                termes_source.append((quantite, -1))

        if materiau_id in incertains_materiaux:
            continue

        try:
            total_hors_main = emplacements.hors_main_par_article(transferts).get(
                materiau_id, Decimal(0)
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            incertains_materiaux.add(materiau_id)
            continue
        hors_main_par_source = {
            source_cle: somme_decimaux_exactement(termes)
            for source_cle, termes in termes_hors_main_par_source.items()
        }
        if any(quantite is None for quantite in hors_main_par_source.values()):
            incertains_materiaux.add(materiau_id)
            continue
        total_attribue = somme_decimaux_exactement(
            (quantite, 1) for quantite in hors_main_par_source.values()
        )
        if total_attribue is None:
            incertains_materiaux.add(materiau_id)
            continue
        if total_hors_main != total_attribue or any(
            quantite < 0 or quantite > quantites_source[source_cle][1]
            for source_cle, quantite in hors_main_par_source.items()
        ):
            incertains_materiaux.add(materiau_id)
            continue

        for source_cle, quantite in hors_main_par_source.items():
            if quantite > 0:
                source, _ = quantites_source[source_cle]
                paire = (source["chantier_id"], materiau_id)
                if paire in paires:
                    incertains.add(paire)

    for materiau_id in incertains_materiaux:
        incertains.update(
            (chantier_id, materiau_id) for chantier_id in paires_par_materiau.get(materiau_id, ())
        )

    return [
        {"chantier_id": chantier_id, "materiau_id": materiau_id, "motif": MOTIF_REORDER_INDETERMINE}
        for chantier_id, materiau_id in sorted(incertains)
    ]


def borne_superieure_en_main_locale(chantier_id, materiau_id, mouvements, transferts_emplacements):
    """Borne supérieure prouvable pour l'ancien prélèvement, ou ``None`` si l'historique est ambigu.

    Ce contrôle très étroit n'attribue rien à partir d'un stock agrégé : il ne fonctionne que si le stock
    théorique du chantier/article est constitué de réceptions positives, si les deux chaînes sont valides,
    et si tous les transferts de l'article sont des séquences C5 simples qui pointent sur leur mouvement
    RECEPTION exact et sur cette même ligne de réception comme clôture (le hash de clôture doit désigner
    l'index source). Une source manquante/incohérente, un transfert entre chantiers ou une autre ligne d'un
    lot multi-ligne dont la frontière n'est pas prouvée rend le résultat indéterminé. La ligne finale d'un
    lot multi-ligne reste admissible si elle est elle-même la source exacte désignée par la clôture. Les
    sources sans transfert sont comptées intégralement comme potentiellement disponibles.

    La borne est le stock théorique local moins le stock C5 de CE chantier qui est encore dans un lieu hors
    main. C'est une borne supérieure (les autres lieux en main ne sont pas prétendus physiquement présents
    au chantier). L'appelant ne s'en sert que pour refuser une demande qui dépasse cette borne; autrement,
    les gardes historiques continuent de décider.
    """
    if not isinstance(chantier_id, str) or not chantier_id or not isinstance(materiau_id, str) or not materiau_id:
        return None
    if transferts_emplacements is None:
        return None

    from . import emplacements
    from . import registre as registre_module

    try:
        mouvements = list(mouvements)
        transferts_emplacements = list(transferts_emplacements)
        chaine_mouvements_valide = registre_module.Registre(maillons=mouvements).valider_chaine()[0]
        chaine_emplacements_valide = emplacements.valider_chaine(transferts_emplacements)[0]
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError, OverflowError):
        return None
    if not chaine_mouvements_valide or not chaine_emplacements_valide:
        return None
    if any(
        not isinstance(transfert, dict) or transfert.get("type_entree") != emplacements.TYPE_TRANSFERT
        for transfert in transferts_emplacements
    ):
        return None

    mouvements_par_index = {}
    index_par_hash = {}
    hashes_vus = set()
    for position, mouvement in enumerate(mouvements):
        index = mouvement.get("index")
        hash_maillon = mouvement.get("hash_maillon")
        if type(index) is not int or index != position or index in mouvements_par_index:
            return None
        if not isinstance(hash_maillon, str) or hash_maillon in hashes_vus:
            return None
        mouvements_par_index[index] = mouvement
        index_par_hash[hash_maillon] = index
        hashes_vus.add(hash_maillon)

    mouvements_locaux = [
        mouvement for mouvement in mouvements
        if mouvement.get("chantier_id") == chantier_id and mouvement.get("materiau_id") == materiau_id
    ]
    # Le sous-ensemble est volontairement limité aux seules RECEPTION du chantier/article.
    # Toute sortie, correction d'inventaire ou type inconnu rend l'historique indéterminé.
    if not mouvements_locaux or any(mouvement.get("type_mouvement") != "RECEPTION" for mouvement in mouvements_locaux):
        return None

    accumulateur_borne = AccumulateurDecimalExact()
    for mouvement in mouvements_locaux:
        try:
            quantite = Decimal(str(mouvement["quantite"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return None
        if not quantite.is_finite() or quantite <= 0:
            return None
        if not accumulateur_borne.ajouter(quantite, 1):
            return None

    groupes = {}
    for transfert in transferts_emplacements:
        if transfert.get("type_entree") != emplacements.TYPE_TRANSFERT or transfert.get("materiau_id") != materiau_id:
            continue
        reference = transfert.get("reference_source")
        if not emplacements._reference_source_valide(reference):
            return None
        reference_mouvement = reference["mouvement"]
        source = mouvements_par_index.get(reference_mouvement["index"])
        index_tete = index_par_hash.get(reference["hash_reception"])
        tete = mouvements_par_index.get(index_tete)
        if (
            source is None
            or source.get("hash_maillon") != reference_mouvement["hash_maillon"]
            or source.get("type_mouvement") != "RECEPTION"
            or source.get("materiau_id") != materiau_id
            or not isinstance(source.get("chantier_id"), str)
            or not source.get("chantier_id")
            or tete is None
            or tete.get("type_mouvement") != "RECEPTION"
            or tete.get("chantier_id") != source.get("chantier_id")
            or index_tete != source.get("index")
        ):
            # Une clôture différente implique au moins une réception à plusieurs lignes dont la frontière
            # ne peut pas être prouvée depuis le schéma durable courant.
            return None
        try:
            quantite_source = Decimal(str(source["quantite"]))
            quantite_transfert = Decimal(str(transfert["quantite"]))
            origine, refus_origine = emplacements.normaliser(transfert["de"])
            destination, refus_destination = emplacements.normaliser(transfert["vers"])
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return None
        if (
            refus_origine is not None or refus_destination is not None
            or origine != transfert["de"] or destination != transfert["vers"]
            or not quantite_source.is_finite() or quantite_source <= 0
            or not quantite_transfert.is_finite() or quantite_transfert != quantite_source
        ):
            return None
        if (
            (source["chantier_id"] == chantier_id and any(
                lieu.get("type") == "chantier" and lieu.get("reference") != chantier_id
                for lieu in (origine, destination)
            ))
            or (source["chantier_id"] != chantier_id and any(
                lieu.get("type") == "chantier" and lieu.get("reference") == chantier_id
                for lieu in (origine, destination)
            ))
        ):
            return None
        cle_source = (source["index"], source["hash_maillon"])
        groupe = groupes.setdefault(cle_source, {"source": source, "reference": reference, "transferts": []})
        if groupe["reference"] != reference:
            return None
        groupe["transferts"].append((transfert, origine, destination))

    hors_main_local_prouve = False
    for groupe in groupes.values():
        source = groupe["source"]
        transferts_source = sorted(groupe["transferts"], key=lambda item: item[0]["index"])
        reference = groupe["reference"]
        statut = reference["statut_ligne"]
        if not transferts_source or transferts_source[0][1] != {"type": "inconnu", "reference": None}:
            return None
        if statut == "endommage":
            if len(transferts_source) == 1:
                if transferts_source[0][2] != {"type": "rebut", "reference": None}:
                    return None
            elif len(transferts_source) == 2:
                premier, second = transferts_source
                if premier[2] != second[1] or second[2] != {"type": "rebut", "reference": None}:
                    return None
            else:
                return None
        elif len(transferts_source) != 1:
            return None

        destination_finale = transferts_source[-1][2]
        if (
            source.get("chantier_id") == chantier_id
            and destination_finale["type"] in emplacements.EMPLACEMENTS_HORS_MAIN
        ):
            hors_main_local_prouve = True
            if not accumulateur_borne.ajouter(source["quantite"], -1):
                return None

    if not hors_main_local_prouve:
        return None
    borne = accumulateur_borne.resultat()
    if borne is None or borne < 0:
        return None
    return borne


def _paires_toutes(paires_par_materiau):
    return [
        {"chantier_id": chantier_id, "materiau_id": materiau_id, "motif": MOTIF_REORDER_INDETERMINE}
        for materiau_id, chantiers in sorted(paires_par_materiau.items())
        for chantier_id in sorted(chantiers)
    ]


def evaluer_reorder(chantier_id, materiau_id, seuils, registre):
    seuil_trouve = None

    for seuil in seuils:
        if (
            seuil["chantier_id"] == chantier_id
            and seuil["materiau_id"] == materiau_id
        ):
            seuil_trouve = seuil
            break

    if seuil_trouve is None:
        return None

    from . import stock

    stock_exact = stock._deriver_stock_theorique_decimal(
        chantier_id,
        materiau_id,
        registre,
    )
    seuil_quantite = seuil_trouve["seuil_quantite"]
    seuil_exact = Decimal(str(seuil_quantite))

    if stock_exact < seuil_exact:
        quantite_suggeree = soustraire_exactement(seuil_exact, stock_exact)
        stock_actuel = float_projection_exacte_ou_refus(stock_exact)
        quantite_suggeree_float = float_projection_exacte_ou_refus(quantite_suggeree)
        somme_affichee = somme_decimaux_exactement(
            ((Decimal(str(stock_actuel)), 1), (Decimal(str(quantite_suggeree_float)), 1))
        )
        if somme_affichee != seuil_exact:
            raise DecimalIndeterminable
        return {
            "chantier_id": chantier_id,
            "materiau_id": materiau_id,
            "stock_actuel": stock_actuel,
            "seuil_quantite": seuil_quantite,
            # Les trois projections sont fidèles et gardent la même équation que le calcul exact.
            "quantite_suggeree": quantite_suggeree_float,
        }

    return None
