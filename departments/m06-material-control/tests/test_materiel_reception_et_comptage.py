"""Orchestrateurs RECEPTION et VARIANCE_INVENTAIRE (docs/bmad/03-ARCHITECTURE.md
l.51, 406-410, DA-M6-11) : bug NEW-PROD corrigé ici -- `enregistrer_reception` et
`soumettre_comptage` n'existaient pas, et `traiter_reception` (logique pure) n'a
jamais écrit au registre. Une consommation ultérieure du même matériau échouait
donc par REJ-STOCK-INSUFFISANT faute de stock réellement enregistré.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control import materiel
from m6_material_control.registre import Registre


def _bon_demande(po_id="PO-100", chantier_id="CHANTIER-1", lignes=None):
    return {
        "po_id": po_id,
        "chantier_id": chantier_id,
        "lignes_demandees": lignes
        or [{"materiau_id": "MAT-1", "quantite_demandee": 10.0}],
        "horodatage": "2026-01-01T08:00:00Z",
    }


def _reception_po(po_id="PO-100", chantier_id="CHANTIER-1", lignes=None):
    return {
        "po_id": po_id,
        "chantier_id": chantier_id,
        "lignes_recues": lignes or [{"materiau_id": "MAT-1", "quantite_recue": 10.0}],
        "horodatage": "2026-01-02T08:00:00Z",
    }


def _catalogue(cout=12.5):
    return {
        "version": "2026.01",
        "unite_monetaire": "CAD",
        "postes": {"MAT-1": {"cout_unitaire": cout, "libelle": "Matériau 1"}},
    }


def _wct():
    return {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "lead_id": "lead-1",
        "technicien_id": "tech-1",
        "horodatage_completion": "2026-01-03T00:00:00Z",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": None,
    }


# --- enregistrer_reception : écrit réellement au registre -----------------


def test_enregistrer_reception_ecrit_les_maillons_reception_au_registre():
    registre = Registre()

    resultat, code = materiel.enregistrer_reception(
        _bon_demande(), _reception_po(), _catalogue(), registre
    )

    assert code is None
    maillons = registre.lire()
    assert len(maillons) == 1
    assert maillons[0]["type_mouvement"] == "RECEPTION"
    assert maillons[0]["chantier_id"] == "CHANTIER-1"
    assert maillons[0]["materiau_id"] == "MAT-1"
    assert maillons[0]["quantite"] == 10.0
    assert maillons[0]["cout_unitaire"] == 12.5
    assert resultat["accuse_reception"]["verdict_reception"] == "CONFORME"
    assert resultat["accuse_reception"]["hash_maillon"] == maillons[-1]["hash_maillon"]


def test_bug_stock_insuffisant_est_corrige_reception_puis_consommation_reussit():
    """Reproduction exacte du bug rapporté : sans écriture réelle au registre à
    la réception, toute consommation ultérieure du même matériau échouait par
    REJ-STOCK-INSUFFISANT. Après le correctif, réception -> consommation marche."""
    registre = Registre()

    resultat, code = materiel.enregistrer_reception(
        _bon_demande(), _reception_po(), _catalogue(), registre
    )
    assert code is None

    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 4.0}],
    }
    confirmation, code_consommation = materiel.consommer_materiaux(_wct(), formulaire, registre)

    assert code_consommation is None
    assert confirmation["stock_restant"] == [{"materiau_id": "MAT-1", "quantite": 6.0}]


def test_enregistrer_reception_emet_un_signal_po_a_payer_quand_le_prix_est_resolu():
    registre = Registre()

    resultat, code = materiel.enregistrer_reception(
        _bon_demande(), _reception_po(), _catalogue(cout=10.0), registre
    )

    assert code is None
    assert resultat["signal_po_a_payer"] == {
        "po_id": "PO-100",
        "chantier_id": "CHANTIER-1",
        "montant_total_estime": 100.0,
        "bareme_version": "2026.01",
        "hash_maillon": registre.lire()[-1]["hash_maillon"],
    }


def test_enregistrer_reception_n_emet_jamais_de_signal_po_si_montant_indetermine():
    """DA-M6-13 : M5 ne doit jamais recevoir un montant à payer indéterminé."""
    registre = Registre()

    resultat, code = materiel.enregistrer_reception(
        _bon_demande(), _reception_po(), None, registre
    )

    assert code is None
    assert resultat["accuse_reception"]["montant_total_estime"] is None
    assert resultat["signal_po_a_payer"] is None
    # Le stock physique est tout de même incrémenté (DA-M6-08 : un prix
    # INDETERMINE ne bloque jamais l'entrée physique en stock).
    assert registre.lire()[0]["quantite"] == 10.0
    assert registre.lire()[0]["cout_unitaire"] is None


def test_enregistrer_reception_indeterminee_n_ecrit_rien_au_registre():
    registre = Registre()
    bon = _bon_demande(po_id="PO-A")
    reception_incoherente = _reception_po(po_id="PO-DIFFERENT")

    resultat, code = materiel.enregistrer_reception(bon, reception_incoherente, _catalogue(), registre)

    assert code is None
    assert resultat["accuse_reception"]["verdict_reception"] == "INDETERMINE"
    assert resultat["signal_po_a_payer"] is None
    assert registre.lire() == []


def test_enregistrer_reception_emet_un_signal_reorder_quand_le_stock_passe_sous_le_seuil():
    registre = Registre()
    seuils = [{"chantier_id": "CHANTIER-1", "materiau_id": "MAT-1", "seuil_quantite": 20.0}]

    resultat, code = materiel.enregistrer_reception(
        _bon_demande(), _reception_po(), _catalogue(), registre, seuils=seuils
    )

    assert code is None
    assert resultat["signaux_reorder"] == [
        {
            "chantier_id": "CHANTIER-1",
            "materiau_id": "MAT-1",
            "stock_actuel": 10.0,
            "seuil_quantite": 20.0,
            "quantite_suggeree": 10.0,
        }
    ]


def test_enregistrer_reception_est_silencieux_sans_seuil_fourni():
    registre = Registre()

    resultat, code = materiel.enregistrer_reception(
        _bon_demande(), _reception_po(), _catalogue(), registre, seuils=None
    )

    assert code is None
    assert resultat["signaux_reorder"] == []


def test_enregistrer_reception_est_tout_ou_rien_si_une_ligne_du_catalogue_est_indeterminee_mais_ecrit_quand_meme():
    """Un prix INDETERMINE par ligne n'empêche pas l'écriture physique (DA-M6-08) :
    seule la non-correspondance structurelle PO<->réception bloque l'écriture."""
    registre = Registre()
    bon = _bon_demande(
        lignes=[
            {"materiau_id": "MAT-1", "quantite_demandee": 4.0},
            {"materiau_id": "MAT-INCONNU", "quantite_demandee": 2.0},
        ]
    )
    recep = _reception_po(
        lignes=[
            {"materiau_id": "MAT-1", "quantite_recue": 4.0},
            {"materiau_id": "MAT-INCONNU", "quantite_recue": 2.0},
        ]
    )

    resultat, code = materiel.enregistrer_reception(bon, recep, _catalogue(), registre)

    assert code is None
    assert len(registre.lire()) == 2
    assert resultat["accuse_reception"]["montant_total_estime"] is None
    assert resultat["signal_po_a_payer"] is None


# --- soumettre_comptage : écrit réellement au registre ---------------------


def test_soumettre_comptage_ecrit_un_maillon_variance_inventaire():
    registre = Registre()
    registre.ajouter(
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "CHANTIER-1",
            "materiau_id": "MAT-1",
            "quantite": 10.0,
            "cout_unitaire": 12.5,
        }
    )
    comptage = {
        "chantier_id": "CHANTIER-1",
        "materiau_id": "MAT-1",
        "quantite_comptee": 7.0,
        "horodatage": "2026-01-05T00:00:00Z",
    }

    signal, code = materiel.soumettre_comptage(comptage, registre)

    assert code is None
    maillons = registre.lire()
    assert len(maillons) == 2
    assert maillons[-1]["type_mouvement"] == "VARIANCE_INVENTAIRE"
    assert maillons[-1]["quantite"] == -3.0
    assert maillons[-1]["cout_unitaire"] is None
    assert signal == {
        "chantier_id": "CHANTIER-1",
        "materiau_id": "MAT-1",
        "verdict_variance": "STOCK_INFERIEUR_AU_THEORIQUE",
        "quantite_theorique": 10.0,
        "quantite_comptee": 7.0,
        "ecart": -3.0,
        "note_investigation": None,
        "horodatage": "2026-01-05T00:00:00Z",
        "hash_maillon": maillons[-1]["hash_maillon"],
    }


def test_soumettre_comptage_indetermine_n_ecrit_rien_au_registre():
    """DA-M6-09 : comparer contre zéro fabriquerait un écart. Aucun mouvement
    théorique préalable -> INDETERMINE -> aucune écriture (registre inchangé)."""
    registre = Registre()
    comptage = {
        "chantier_id": "CHANTIER-JAMAIS-VU",
        "materiau_id": "MAT-JAMAIS-VU",
        "quantite_comptee": 5.0,
        "horodatage": "2026-01-05T00:00:00Z",
    }

    signal, code = materiel.soumettre_comptage(comptage, registre)

    assert code is None
    assert signal["verdict_variance"] == "INDETERMINE"
    assert registre.lire() == []
    assert signal["hash_maillon"] == ""


def test_soumettre_comptage_sans_ecart_ecrit_tout_de_meme_le_constat():
    registre = Registre()
    registre.ajouter(
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "CHANTIER-1",
            "materiau_id": "MAT-1",
            "quantite": 5.0,
            "cout_unitaire": 1.0,
        }
    )
    comptage = {
        "chantier_id": "CHANTIER-1",
        "materiau_id": "MAT-1",
        "quantite_comptee": 5.0,
        "horodatage": "2026-01-05T00:00:00Z",
    }

    signal, code = materiel.soumettre_comptage(comptage, registre)

    assert code is None
    assert signal["verdict_variance"] == "AUCUN_ECART"
    assert len(registre.lire()) == 2


# --- frontières câblées : "virement" (et autres clés interdites) est refusé --
# à travers les VRAIS points d'entrée, pas seulement via un appel direct et
# isolé à frontieres.verifier_frontieres (bug NEW-PROD : jamais câblé).


def test_consommer_materiaux_rejette_un_virement_glisse_dans_le_wct():
    registre = Registre()
    wct = _wct()
    wct["fix_gps_completion"]["virement"] = "virement-001"
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 1.0}],
    }

    confirmation, code = materiel.consommer_materiaux(wct, formulaire, registre)

    assert confirmation is None
    assert code == "REJ-FRONTIERE-VIOLEE"


def test_enregistrer_reception_rejette_un_virement_glisse_dans_le_bon_de_commande():
    registre = Registre()
    bon = _bon_demande()
    bon["lignes_demandees"][0]["virement"] = "virement-002"

    resultat, code = materiel.enregistrer_reception(bon, _reception_po(), _catalogue(), registre)

    assert resultat is None
    assert code == "REJ-FRONTIERE-VIOLEE"
    assert registre.lire() == []


def test_enregistrer_reception_rejette_un_virement_glisse_dans_la_reception():
    registre = Registre()
    recep = _reception_po()
    recep["virement"] = "virement-003"

    resultat, code = materiel.enregistrer_reception(_bon_demande(), recep, _catalogue(), registre)

    assert resultat is None
    assert code == "REJ-FRONTIERE-VIOLEE"
    assert registre.lire() == []


def test_soumettre_comptage_rejette_un_virement_glisse_dans_le_comptage():
    registre = Registre()
    comptage = {
        "chantier_id": "CHANTIER-1",
        "materiau_id": "MAT-1",
        "quantite_comptee": 5.0,
        "horodatage": "2026-01-05T00:00:00Z",
        "virement": "virement-004",
    }

    signal, code = materiel.soumettre_comptage(comptage, registre)

    assert signal is None
    assert code == "REJ-FRONTIERE-VIOLEE"
    assert registre.lire() == []
