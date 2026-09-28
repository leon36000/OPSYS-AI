import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m10_memoire import contrats, registre, wct


HORODATAGE = "2026-08-04T12:00:00+00:00"


def _wct(consommateurs=("M6", "M5", "M2", "M7", "M8", "M10")):
    return {
        "wct_id": "WCT-001",
        "intervention_id": "INT-001",
        "lead_id": "LEAD-001",
        "technicien_id": "TECH-001",
        "horodatage_completion": HORODATAGE,
        "fix_gps_completion": {"lat": "45.5", "lon": "-73.6"},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": "REV-001",
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": consommateurs,
        "devis_id": "DEV-001",
    }


@pytest.fixture
def registre_cible():
    return registre.Registre()


def test_valider_wct_accepte_un_wct_complet_destine_a_m10():
    assert wct.valider_wct(_wct()) == (True, None)


@pytest.mark.parametrize("wct_invalide", [[], None, "texte", 42])
def test_valider_wct_rejette_une_valeur_qui_n_est_pas_un_dict(wct_invalide):
    valide, code = wct.valider_wct(wct_invalide)

    assert valide is False
    assert code.startswith("REJ-")


def test_valider_wct_rejette_un_champ_manquant_avec_le_meme_code_qu_un_non_dict():
    wct_sans_devis = _wct()
    del wct_sans_devis["devis_id"]

    _, code_non_dict = wct.valider_wct(None)
    valide, code_champ_manquant = wct.valider_wct(wct_sans_devis)

    assert valide is False
    assert code_champ_manquant == code_non_dict


def test_valider_wct_rejette_un_champ_inattendu_avec_un_code_distinct():
    wct_avec_champ_inconnu = _wct()
    wct_avec_champ_inconnu["champ_inconnu"] = "inattendu"

    wct_sans_devis = _wct()
    del wct_sans_devis["devis_id"]

    _, code_champ_manquant = wct.valider_wct(wct_sans_devis)
    valide, code_champ_inattendu = wct.valider_wct(wct_avec_champ_inconnu)

    assert valide is False
    assert code_champ_inattendu.startswith("REJ-")
    assert code_champ_inattendu != code_champ_manquant


def test_valider_wct_rejette_l_absence_de_m10_avec_un_code_distinct():
    wct_sans_m10 = _wct(("M6", "M5", "M2", "M7", "M8"))

    wct_sans_devis = _wct()
    del wct_sans_devis["devis_id"]

    wct_avec_champ_inconnu = _wct()
    wct_avec_champ_inconnu["champ_inconnu"] = "inattendu"

    _, code_champ_manquant = wct.valider_wct(wct_sans_devis)
    _, code_champ_inattendu = wct.valider_wct(wct_avec_champ_inconnu)
    valide, code_m10_absent = wct.valider_wct(wct_sans_m10)

    assert valide is False
    assert code_m10_absent.startswith("REJ-")
    assert code_m10_absent != code_champ_manquant
    assert code_m10_absent != code_champ_inattendu


@pytest.mark.parametrize(
    "consommateurs",
    [
        ("M10", "M6", "M5"),
        ("M6", "M5", "M10"),
    ],
)
def test_valider_wct_accepte_m10_independamment_de_sa_position(consommateurs):
    assert wct.valider_wct(_wct(consommateurs)) == (True, None)


def test_valider_wct_accepte_une_liste_de_consommateurs_contenant_m10():
    assert wct.valider_wct(_wct(["M6", "M5", "M10"])) == (True, None)


def test_memoriser_wct_valide_ecrit_un_evenement_memorise(registre_cible):
    maillon, code = wct.memoriser_wct(_wct(), registre_cible)

    assert code is None
    assert maillon["type_entree"] == "evenement_memorise"
    assert maillon["ligne_id"]
    assert len(registre_cible.lire()) == 1


def test_memoriser_wct_invalide_n_ecrit_rien(registre_cible):
    maillon, code = wct.memoriser_wct(
        _wct(("M6", "M5", "M2", "M7", "M8")),
        registre_cible,
    )

    assert maillon is None
    assert code.startswith("REJ-")
    assert registre_cible.lire() == []


def test_memoriser_wct_conserve_tel_quel_le_hash_maillon_recu(registre_cible):
    wct_recu = _wct()

    maillon, code = wct.memoriser_wct(wct_recu, registre_cible)
    maillon_stocke = registre_cible.lire()[0]

    assert code is None
    assert maillon["hash_maillon"] == "a" * 64
    assert maillon_stocke["hash_maillon"] == "a" * 64


def test_memoriser_wct_n_utilise_pas_le_hash_m4_comme_ligne_id(registre_cible):
    maillon, code = wct.memoriser_wct(_wct(), registre_cible)

    assert code is None
    assert maillon["ligne_id"] != "a" * 64


def test_memoriser_wct_chaine_deux_maillons_successifs(registre_cible):
    premier, code_premier = wct.memoriser_wct(_wct(), registre_cible)

    second_wct = _wct()
    second_wct["wct_id"] = "WCT-002"
    second, code_second = wct.memoriser_wct(second_wct, registre_cible)

    assert code_premier is None
    assert code_second is None
    assert len(registre_cible.lire()) == 2
    assert second["precedent_ligne_id"] == premier["ligne_id"]
    assert registre_cible.valider_chaine() == (True, "")


def test_memoriser_wct_dans_deux_registres_distincts_ne_les_affecte_pas_mutuellement():
    registre_forge = registre.Registre()
    registre_business = registre.Registre()

    maillon_forge, code_forge = wct.memoriser_wct(_wct(), registre_forge)

    business_wct = _wct()
    business_wct["wct_id"] = "WCT-002"
    maillon_business, code_business = wct.memoriser_wct(
        business_wct,
        registre_business,
    )

    assert code_forge is None
    assert code_business is None
    assert len(registre_forge.lire()) == 1
    assert len(registre_business.lire()) == 1
    assert registre_forge.lire()[0] == maillon_forge
    assert registre_business.lire()[0] == maillon_business
    assert maillon_forge != maillon_business


def test_valider_wct_n_accepte_qu_un_seul_argument_positionnel():
    with pytest.raises(TypeError):
        wct.valider_wct(_wct(), None)
