import sys
from decimal import Decimal
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import encodage, etat_financier, registre


HORODATAGE = "2026-08-03T12:00:00+00:00"


def _registre_peuple():
    registre_cible = registre.Registre()
    registre.enregistrer_mouvement(
        {
            "montant": Decimal("100.00"),
            "type_mouvement": "ENCAISSEMENT",
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "test",
        },
        registre_cible,
    )
    return registre_cible


def _ajouter_mouvement(registre_cible, montant, type_mouvement):
    registre.enregistrer_mouvement(
        {
            "montant": montant,
            "type_mouvement": type_mouvement,
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "test",
        },
        registre_cible,
    )


def test_construit_un_etat_financier_autorise_avec_les_soldes():
    registre_cible = _registre_peuple()
    taux = [{"id": "tps_federale", "version": "2026-v1"}]

    resultat = etat_financier.construire_etat_financier(
        registre_cible,
        taux,
        role="gestionnaire",
    )

    assert resultat["type"] == "ETAT_FINANCIER"
    assert resultat["role"] == "gestionnaire"
    assert type(resultat["solde"]) is Decimal
    assert type(resultat["argent_disponible"]) is Decimal
    assert resultat["solde"] == Decimal("100.00")
    assert resultat["argent_disponible"] == Decimal("100.00")
    assert resultat["taux_utilises"] == taux
    assert resultat["etat_id"]


def test_role_est_none_par_defaut():
    resultat = etat_financier.construire_etat_financier(
        _registre_peuple(),
        [],
    )

    assert resultat["role"] is None


def test_taux_utilises_sont_conserves_et_copies():
    taux = [{"id": "tps_federale", "version": "2026-v1"}]

    resultat = etat_financier.construire_etat_financier(
        _registre_peuple(),
        taux,
        role="gestionnaire",
    )

    assert resultat["taux_utilises"] == taux
    assert resultat["taux_utilises"] is not taux


def test_autorisation_couts_false_filtre_entierement_les_donnees_financieres():
    taux = [
        {"id": "tps_federale", "version": "2026-v1"},
        {"id": "tps_provinciale", "version": "2026-v2"},
    ]

    resultat = etat_financier.construire_etat_financier(
        _registre_peuple(),
        taux,
        role="observateur",
        autorise_couts=False,
    )

    assert resultat["type"] == "ETAT_FINANCIER"
    assert resultat["role"] == "observateur"
    assert resultat["solde"] is None
    assert resultat["argent_disponible"] is None
    assert resultat["taux_utilises"] == []


def test_taux_fournis_vide_est_conserve_si_couts_autorises():
    resultat = etat_financier.construire_etat_financier(
        _registre_peuple(),
        [],
        autorise_couts=True,
    )

    assert resultat["taux_utilises"] == []
    assert resultat["taux_utilises"] is not None


def test_registre_vide_produit_des_soldes_nuls():
    resultat = etat_financier.construire_etat_financier(
        registre.Registre(),
        [],
        autorise_couts=True,
    )

    assert resultat["solde"] == Decimal("0")
    assert resultat["argent_disponible"] == Decimal("0")


def test_argent_disponible_tient_compte_des_provisions():
    registre_cible = _registre_peuple()
    _ajouter_mouvement(registre_cible, Decimal("25.00"), "PROVISION")

    resultat = etat_financier.construire_etat_financier(
        registre_cible,
        [],
    )

    assert resultat["solde"] == Decimal("100.00")
    assert resultat["argent_disponible"] == Decimal("75.00")


def test_deux_constructions_identiques_sont_deterministes():
    registre_cible = _registre_peuple()
    taux = [{"id": "tps_federale", "version": "2026-v1"}]

    premier = etat_financier.construire_etat_financier(
        registre_cible,
        taux,
        role="gestionnaire",
        autorise_couts=True,
    )
    second = etat_financier.construire_etat_financier(
        registre_cible,
        taux,
        role="gestionnaire",
        autorise_couts=True,
    )

    assert premier == second
    assert premier["etat_id"] == second["etat_id"]


def test_etat_id_est_calcule_sans_le_champ_etat_id():
    registre_cible = _registre_peuple()
    taux = [{"id": "tps_federale", "version": "2026-v1"}]

    resultat = etat_financier.construire_etat_financier(
        registre_cible,
        taux,
        role="gestionnaire",
    )
    contenu = {
        "type": resultat["type"],
        "role": resultat["role"],
        "solde": resultat["solde"],
        "argent_disponible": resultat["argent_disponible"],
        "taux_utilises": resultat["taux_utilises"],
    }

    assert resultat["etat_id"] == encodage.empreinte(contenu)


def test_changer_l_autorisation_change_l_etat_id():
    registre_cible = _registre_peuple()
    taux = [{"id": "tps_federale", "version": "2026-v1"}]

    autorise = etat_financier.construire_etat_financier(
        registre_cible,
        taux,
        role="gestionnaire",
        autorise_couts=True,
    )
    non_autorise = etat_financier.construire_etat_financier(
        registre_cible,
        taux,
        role="gestionnaire",
        autorise_couts=False,
    )

    assert autorise["etat_id"] != non_autorise["etat_id"]


def test_changer_le_role_change_le_contenu_et_l_identifiant():
    registre_cible = _registre_peuple()
    taux = [{"id": "tps_federale", "version": "2026-v1"}]

    premier = etat_financier.construire_etat_financier(
        registre_cible,
        taux,
        role="gestionnaire",
    )
    second = etat_financier.construire_etat_financier(
        registre_cible,
        taux,
        role="lecteur",
    )

    assert premier["role"] != second["role"]
    assert premier["etat_id"] != second["etat_id"]


def test_modifier_la_liste_de_taux_fournie_apres_construction_ne_modifie_pas_la_sortie():
    taux = [{"id": "tps_federale", "version": "2026-v1"}]
    resultat = etat_financier.construire_etat_financier(
        _registre_peuple(),
        taux,
    )

    taux.append({"id": "tps_provinciale", "version": "2026-v2"})

    assert resultat["taux_utilises"] == [
        {"id": "tps_federale", "version": "2026-v1"}
    ]
