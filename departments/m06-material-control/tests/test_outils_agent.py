"""Capacités d'agent de M6 : contrat des outils et chaîne matériel composée."""

from __future__ import annotations

from pathlib import Path

from m6_material_control.outils import outils

from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


def _bon_demande(po_id="PO-1", chantier_id="C1", lignes=None):
    return {
        "po_id": po_id,
        "chantier_id": chantier_id,
        "lignes_demandees": lignes or [{"materiau_id": "MAT-1", "quantite_demandee": 10.0}],
        "horodatage": "2026-01-01T00:00:00Z",
    }


def _reception_po(po_id="PO-1", chantier_id="C1", lignes=None):
    return {
        "po_id": po_id,
        "chantier_id": chantier_id,
        "lignes_recues": lignes or [{"materiau_id": "MAT-1", "quantite_recue": 10.0}],
        "horodatage": "2026-01-02T00:00:00Z",
    }


def _catalogue(cout=5.0):
    return {"version": "v1", "unite_monetaire": "CAD", "postes": {"MAT-1": {"cout_unitaire": cout, "libelle": "x"}}}


def _wct():
    return {
        "wct_id": "w1",
        "intervention_id": "i1",
        "lead_id": "l1",
        "technicien_id": "t1",
        "horodatage_completion": "2026-01-03T00:00:00Z",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": None,
    }


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m6_receptionner_commande"
    assert all(nom.startswith("m6_") for nom in noms)
    assert dep.mode == "ombre"
    assert dep.dependances == ("m04-field-ops",)


def test_autonomie_respecte_la_regle_finance():
    """M6 ne porte aucune écriture financière (elle signale, jamais ne paie) :
    ses écritures de registre interne restent T1 ; lecture/calcul = T0."""
    assert _outil("m6_receptionner_commande").autonomie == Autonomie.T1
    assert _outil("m6_consommer_materiaux").autonomie == Autonomie.T1
    assert _outil("m6_soumettre_comptage").autonomie == Autonomie.T1
    assert _outil("m6_produire_digest").autonomie == Autonomie.T0
    assert _outil("m6_resoudre_prix_materiau").autonomie == Autonomie.T0
    # PLAN T1.1-d point 3 : lecture/calcul pur (aucune écriture registre) -> T0.
    assert _outil("m6_evaluer_variance_chantier").autonomie == Autonomie.T0
    # PLAN T1.1-d2 point 2 : écriture registre interne (CONSOMMATION/RETOUR/PERTE/BRIS) -> T1.
    assert _outil("m6_declarer_materiaux_utilises").autonomie == Autonomie.T1


# --- m6_receptionner_commande : composé de bout en bout ---------------------


def test_receptionner_commande_nominal_ecrit_le_stock_et_signale_m5():
    reponse = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["accuse_reception"]["verdict_reception"] == "CONFORME"
    assert resultat["signal_po_a_payer"]["montant_total_estime"] == 50.0
    assert reponse["resultat"]["registre_historique"][0]["type_mouvement"] == "RECEPTION"


def test_receptionner_commande_sans_catalogue_n_emet_aucun_signal_po():
    reponse = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po()},
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["accuse_reception"]["montant_total_estime"] is None
    assert resultat["signal_po_a_payer"] is None
    # Le stock physique est écrit malgré tout (DA-M6-08).
    assert reponse["resultat"]["registre_historique"][0]["quantite"] == 10.0


def test_receptionner_commande_po_incoherent_est_un_refus_sans_ecriture():
    reponse = executer(
        _outil("m6_receptionner_commande"),
        {
            "bon_demande": _bon_demande(po_id="PO-A"),
            "reception_po": _reception_po(po_id="PO-DIFFERENT"),
            "catalogue_materiaux": _catalogue(),
        },
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["accuse_reception"]["verdict_reception"] == "INDETERMINE"
    assert reponse["resultat"]["registre_historique"] == []


def test_receptionner_commande_rejette_une_cle_interdite_glissee_dans_une_ligne():
    """Bug NEW-PROD corrigé : frontieres.py était jamais câblé, une clé comme
    « virement » traversait silencieusement les entrées de M6."""
    bon = _bon_demande()
    bon["lignes_demandees"][0]["virement"] = "virement-001"

    reponse = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": bon, "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-FRONTIERE-VIOLEE"


def test_receptionner_commande_parametre_requis_manquant_est_un_refus_de_schema():
    reponse = executer(_outil("m6_receptionner_commande"), {"bon_demande": _bon_demande()})

    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


# --- m6_consommer_materiaux : chaîné à une réception préalable --------------


def test_consommer_materiaux_apres_reception_reussit_bug_stock_insuffisant_corrige():
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]

    formulaire = {
        "wct_id": "w1",
        "intervention_id": "i1",
        "chantier_id": "C1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 4.0}],
    }
    r2 = executer(
        _outil("m6_consommer_materiaux"),
        {"wct": _wct(), "formulaire": formulaire, "registre_historique": historique},
    )

    assert r2["ok"] is True
    assert r2["resultat"]["accepte"] is True
    assert r2["resultat"]["resultat"]["stock_restant"] == [{"materiau_id": "MAT-1", "quantite": 6.0}]


def test_consommer_materiaux_sans_stock_prealable_est_refuse_nomme():
    formulaire = {
        "wct_id": "w1",
        "intervention_id": "i1",
        "chantier_id": "C1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 4.0}],
    }

    reponse = executer(_outil("m6_consommer_materiaux"), {"wct": _wct(), "formulaire": formulaire})

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"


# --- m6_declarer_materiaux_utilises : PLAN T1.1-d2 point 2 ------------------


def _formulaire_materiaux(lignes, wct_id="w1", chantier_id="C1"):
    return {"wct_id": wct_id, "intervention_id": "i1", "chantier_id": chantier_id, "lignes_materiaux": lignes}


def _ligne_prevu(materiau_id="MAT-1", quantite=4.0, quantite_estimee=4.0, unite="boite"):
    return {
        "type_ligne": "prevu", "materiau_id": materiau_id, "quantite": quantite,
        "unite": unite, "quantite_estimee": quantite_estimee,
    }


def test_declarer_materiaux_utilises_apres_reception_ecrit_une_consommation():
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]

    r2 = executer(
        _outil("m6_declarer_materiaux_utilises"),
        {"wct": _wct(), "formulaire": _formulaire_materiaux([_ligne_prevu()]), "registre_historique": historique},
    )

    assert r2["ok"] is True
    assert r2["resultat"]["accepte"] is True
    nouveaux = r2["resultat"]["registre_historique"][len(historique):]
    assert len(nouveaux) == 1
    assert nouveaux[0]["type_mouvement"] == "CONSOMMATION"
    assert nouveaux[0]["quantite"] == -4.0
    assert nouveaux[0]["wct_id"] == "w1"


def test_declarer_materiaux_utilises_achat_terrain_sans_preuve_est_refuse_nomme():
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]
    ligne = {
        "type_ligne": "achat_terrain", "materiau_id": "MAT-1", "quantite": 1.0,
        "unite": "boite", "photo_fournie": False, "recu_fourni": False,
    }

    r2 = executer(
        _outil("m6_declarer_materiaux_utilises"),
        {"wct": _wct(), "formulaire": _formulaire_materiaux([ligne]), "registre_historique": historique},
    )

    assert r2["ok"] is True
    assert r2["resultat"]["accepte"] is False
    assert r2["resultat"]["verdict"]["code"] == "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE"


def test_declarer_materiaux_utilises_une_seconde_fois_pour_le_meme_wct_est_refuse():
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]
    formulaire = _formulaire_materiaux([_ligne_prevu()])

    r2 = executer(
        _outil("m6_declarer_materiaux_utilises"),
        {"wct": _wct(), "formulaire": formulaire, "registre_historique": historique},
    )
    historique_apres_r2 = r2["resultat"]["registre_historique"]
    r3 = executer(
        _outil("m6_declarer_materiaux_utilises"),
        {"wct": _wct(), "formulaire": formulaire, "registre_historique": historique_apres_r2},
    )

    assert r2["resultat"]["accepte"] is True
    assert r3["ok"] is True
    assert r3["resultat"]["accepte"] is False
    assert r3["resultat"]["verdict"]["code"] == "REJ-DECLARATION-DEJA-SOUMISE"
    # Un refus n'écrit rien : pas de clé registre_historique dans la réponse (même
    # patron que m6_consommer_materiaux/m6_receptionner_commande sur refus).
    assert "registre_historique" not in r3["resultat"]


# --- m6_soumettre_comptage ---------------------------------------------------


def test_soumettre_comptage_apres_reception_ecrit_la_variance():
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]

    comptage = {
        "chantier_id": "C1",
        "materiau_id": "MAT-1",
        "quantite_comptee": 7.0,
        "horodatage": "2026-01-05T00:00:00Z",
    }
    r2 = executer(_outil("m6_soumettre_comptage"), {"comptage": comptage, "registre_historique": historique})

    assert r2["ok"] is True
    resultat = r2["resultat"]["resultat"]
    assert resultat["verdict_variance"] == "STOCK_INFERIEUR_AU_THEORIQUE"
    assert resultat["ecart"] == -3.0
    assert resultat["note_investigation"] is None
    assert len(r2["resultat"]["registre_historique"]) == 2


def test_soumettre_comptage_sans_mouvement_prealable_est_indetermine():
    comptage = {
        "chantier_id": "C-JAMAIS-VU",
        "materiau_id": "MAT-JAMAIS-VU",
        "quantite_comptee": 5.0,
        "horodatage": "2026-01-05T00:00:00Z",
    }

    reponse = executer(_outil("m6_soumettre_comptage"), {"comptage": comptage})

    assert reponse["ok"] is True
    assert reponse["resultat"]["resultat"]["verdict_variance"] == "INDETERMINE"
    assert reponse["resultat"]["registre_historique"] == []


# --- m6_produire_digest / m6_resoudre_prix_materiau : lecture seule ---------


def test_produire_digest_reproductible_sur_le_meme_historique():
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]

    d1 = executer(_outil("m6_produire_digest"), {"registre_historique": historique})
    d2 = executer(_outil("m6_produire_digest"), {"registre_historique": historique})

    assert d1["ok"] is True and d2["ok"] is True
    assert d1["resultat"] == d2["resultat"]
    assert d1["resultat"]["type"] == "DIGEST_MATERIEL"


def test_resoudre_prix_materiau_indetermine_sans_catalogue_ni_historique():
    reponse = executer(_outil("m6_resoudre_prix_materiau"), {"materiau_id": "MAT-INCONNU"})

    assert reponse["ok"] is True
    assert reponse["resultat"]["verdict_resolution_prix"] == "INDETERMINE"
    assert reponse["resultat"]["cout_unitaire_resolu"] is None


# --- m6_evaluer_variance_chantier : PLAN T1.1-d points 2 et 3 ---------------


def _besoin_estime(materiau_id="MAT-1", quantite_estimee=100.0, unite="boite"):
    return {"materiau_id": materiau_id, "quantite_estimee": quantite_estimee, "unite": unite}


def _ligne_declaree(quantite, materiau_id="MAT-1", unite="boite"):
    return {
        "type_ligne": "prevu", "materiau_id": materiau_id, "quantite": quantite,
        "unite": unite, "quantite_estimee": quantite,
    }


def test_evaluer_variance_chantier_quarante_pourcent_emet_un_signal():
    reponse = executer(
        _outil("m6_evaluer_variance_chantier"),
        {
            "chantier_id": "C1",
            "besoins_estimes": [_besoin_estime(quantite_estimee=100.0)],
            "lignes_declarees": [_ligne_declaree(140.0)],
            "seuil_pourcentage": 0.30,
        },
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]["resultat"]
    signal = resultat["signal_variance_critique"]
    assert signal is not None
    assert signal["materiaux_en_ecart_critique"] == ["MAT-1"]
    assert signal["ecart_maximal_pourcentage"] == 0.4


def test_evaluer_variance_chantier_cinq_pourcent_n_emet_aucun_signal():
    reponse = executer(
        _outil("m6_evaluer_variance_chantier"),
        {
            "chantier_id": "C1",
            "besoins_estimes": [_besoin_estime(quantite_estimee=100.0)],
            "lignes_declarees": [_ligne_declaree(105.0)],
            "seuil_pourcentage": 0.30,
        },
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["signal_variance_critique"] is None
    assert resultat["verdicts_materiaux"][0]["cause_possible"] is None


def test_evaluer_variance_chantier_ne_renvoie_aucune_cle_monetaire():
    reponse = executer(
        _outil("m6_evaluer_variance_chantier"),
        {
            "chantier_id": "C1",
            "besoins_estimes": [_besoin_estime(quantite_estimee=100.0)],
            "lignes_declarees": [_ligne_declaree(140.0)],
            "seuil_pourcentage": 0.30,
        },
    )

    assert reponse["ok"] is True
    cles = collecter_cles_recursivement(reponse["resultat"])
    assert not cles.intersection(
        {"cout_unitaire", "cout", "prix", "montant", "devise", "unite_monetaire", "montant_total_estime"}
    )


def test_evaluer_variance_chantier_seuil_manquant_est_un_refus_de_schema():
    reponse = executer(
        _outil("m6_evaluer_variance_chantier"),
        {
            "chantier_id": "C1",
            "besoins_estimes": [_besoin_estime()],
            "lignes_declarees": [_ligne_declaree(140.0)],
        },
    )

    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_evaluer_variance_chantier_lit_le_reel_directement_au_registre_par_wct_id():
    """PLAN T1.1-d2 point 3 : m6_declarer_materiaux_utilises écrit, puis
    m6_evaluer_variance_chantier relit sans que lignes_declarees soit retransporté."""
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]

    r2 = executer(
        _outil("m6_declarer_materiaux_utilises"),
        {
            "wct": _wct(),
            "formulaire": _formulaire_materiaux([_ligne_prevu(quantite=4.0, quantite_estimee=4.0)]),
            "registre_historique": historique,
        },
    )
    historique_apres_declaration = r2["resultat"]["registre_historique"]

    r3 = executer(
        _outil("m6_evaluer_variance_chantier"),
        {
            "chantier_id": "C1",
            "besoins_estimes": [_besoin_estime(quantite_estimee=4.0)],
            "wct_id": "w1",
            "seuil_pourcentage": 0.30,
            "registre_historique": historique_apres_declaration,
        },
    )

    assert r3["ok"] is True
    assert r3["resultat"]["accepte"] is True
    resultat = r3["resultat"]["resultat"]
    verdict = next(v for v in resultat["verdicts_materiaux"] if v["materiau_id"] == "MAT-1")
    assert verdict["quantite_reelle"] == 4.0
    assert verdict["verdict_variance"] == "AUCUN_ECART"


def test_evaluer_variance_chantier_sans_lignes_declarees_ni_declaration_prealable_est_non_utilise():
    """Sans lignes_declarees ni déclaration préalable au registre, le réel vaut zéro
    partout : pas d'erreur (registre vide légitime), juste NON_UTILISE — et le signal
    critique se déclenche bien (100 % d'écart >= 30 % de seuil), sans exception ni refus."""
    reponse = executer(
        _outil("m6_evaluer_variance_chantier"),
        {
            "chantier_id": "C-VIDE",
            "besoins_estimes": [_besoin_estime(quantite_estimee=10.0)],
            "seuil_pourcentage": 0.30,
        },
    )

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["verdicts_materiaux"][0]["verdict_variance"] == "NON_UTILISE"
    assert resultat["verdicts_materiaux"][0]["quantite_reelle"] == 0.0
    assert resultat["signal_variance_critique"]["materiaux_en_ecart_critique"] == ["MAT-1"]


# --- m6_enregistrer_besoins_prevus : PLAN T1.2-b, « M6 garde le prévu » ---------------------


def test_enregistrer_besoins_prevus_nominal_accepte():
    reponse = executer(_outil("m6_enregistrer_besoins_prevus"), {
        "chantier_id": "C1", "devis_id": "DEVIS-1",
        "lignes": [_besoin_estime(quantite_estimee=10.0)],
    })
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["resultat"]["chantier_id"] == "C1"
    assert reponse["resultat"]["registre_historique"][0]["devis_id"] == "DEVIS-1"


def test_enregistrer_besoins_prevus_autonomie_t1():
    assert _outil("m6_enregistrer_besoins_prevus").autonomie == Autonomie.T1


def test_enregistrer_besoins_prevus_idempotent_par_devis_id():
    r1 = executer(_outil("m6_enregistrer_besoins_prevus"), {
        "chantier_id": "C1", "devis_id": "DEVIS-1", "lignes": [_besoin_estime(quantite_estimee=10.0)],
    })
    historique = r1["resultat"]["registre_historique"]

    r2 = executer(_outil("m6_enregistrer_besoins_prevus"), {
        "chantier_id": "C1", "devis_id": "DEVIS-1", "lignes": [_besoin_estime(quantite_estimee=999.0)],
        "registre_historique": historique,
    })
    assert r2["ok"] is True
    assert r2["resultat"]["accepte"] is False
    assert r2["resultat"]["verdict"]["code"] == "REJ-BESOINS-PREVUS-DEJA-ENREGISTRES"
    # rien de nouveau écrit : la clé registre_historique est absente du refus (même patron
    # que m6_declarer_materiaux_utilises sur REJ-DECLARATION-DEJA-SOUMISE)
    assert "registre_historique" not in r2["resultat"]


def test_enregistrer_besoins_prevus_lignes_vides_accepte_prevu_vide_connu():
    # T1.2-d : un devis accepté sans aucune ligne matériau est un PRÉVU VIDE CONNU -- accepté,
    # jamais un refus (l'ancien REJ-BESOINS-PREVUS-LIGNES-VIDES bloquait le chantier en revue
    # pour toujours faute de prévu, exactement le trou que ce correctif comble).
    reponse = executer(_outil("m6_enregistrer_besoins_prevus"), {
        "chantier_id": "C1", "devis_id": "DEVIS-1", "lignes": [],
    })
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["resultat"]["lignes"] == []


def test_enregistrer_besoins_prevus_parametre_requis_manquant_est_un_refus_de_schema():
    reponse = executer(_outil("m6_enregistrer_besoins_prevus"), {"chantier_id": "C1", "devis_id": "DEVIS-1"})
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def collecter_cles_recursivement(valeur):
    cles = set()
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            cles.add(cle)
            cles.update(collecter_cles_recursivement(sous_valeur))
    elif isinstance(valeur, list):
        for element in valeur:
            cles.update(collecter_cles_recursivement(element))
    return cles
