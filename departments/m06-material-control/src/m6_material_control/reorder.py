from decimal import Decimal, InvalidOperation

MOTIF_REORDER_INDETERMINE = "stock_localise_par_chantier_non_reconstructible"


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

        hors_main_par_source = {}
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
            hors_main_par_source[source_cle] = hors_main_par_source.get(source_cle, Decimal(0)) + (
                (quantite if destination in emplacements.EMPLACEMENTS_HORS_MAIN else Decimal(0))
                - (quantite if origine in emplacements.EMPLACEMENTS_HORS_MAIN else Decimal(0))
            )

        if materiau_id in incertains_materiaux:
            continue

        try:
            total_hors_main = emplacements.hors_main_par_article(transferts).get(
                materiau_id, Decimal(0)
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            incertains_materiaux.add(materiau_id)
            continue
        total_attribue = sum(hors_main_par_source.values(), Decimal(0))
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

    stock_actuel = stock.deriver_stock_theorique(
        chantier_id,
        materiau_id,
        registre,
    )
    seuil_quantite = seuil_trouve["seuil_quantite"]

    if stock_actuel < seuil_quantite:
        return {
            "chantier_id": chantier_id,
            "materiau_id": materiau_id,
            "stock_actuel": stock_actuel,
            "seuil_quantite": seuil_quantite,
            # Écart en décimal exact (10,3 − 3,1 = 7,2, pas 7,200000000000001), comme `stock.py`.
            "quantite_suggeree": float(Decimal(str(seuil_quantite)) - Decimal(str(stock_actuel))),
        }

    return None
