import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m10_memoire import contrats, decisions, registre


HORODATAGE = "2026-08-04T12:00:00+00:00"


def _decision(decision_id="DEC-001", statut="proposee", raison="Raison suffisante."):
    return {
        "decision_id": decision_id,
        "raison": raison,
        "statut": statut,
        "options_ecartees": "Ne rien faire",
    }


def test_enregistrer_decision_valide_retourne_maillon():
    registre_cible = registre.Registre()

    maillon, erreur = decisions.enregistrer_decision(
        _decision(), registre_cible, HORODATAGE
    )

    assert erreur is None
    assert maillon["type_entree"] == "decision_enregistree"
    assert maillon["ligne_id"]
    for champ in contrats.CHAMPS_DECISION:
        assert maillon[champ] == _decision()[champ]


def test_enregistrer_decision_sans_raison_n_ecrit_rien():
    registre_cible = registre.Registre()

    maillon, code = decisions.enregistrer_decision(
        _decision(raison=""), registre_cible, HORODATAGE
    )

    assert maillon is None
    assert code is not None
    assert registre_cible.lire() == []


def test_enregistrer_decision_avec_statut_invalide_n_ecrit_rien():
    registre_cible = registre.Registre()

    maillon, code = decisions.enregistrer_decision(
        _decision(statut="invalide"), registre_cible, HORODATAGE
    )

    assert maillon is None
    assert code is not None
    assert registre_cible.lire() == []


def test_statut_courant_retourne_none_pour_decision_inexistante():
    registre_cible = registre.Registre()

    statut = decisions.statut_courant(registre_cible, "DEC-INEXISTANTE")

    assert statut is None


def test_statut_courant_retourne_statut_enregistre():
    registre_cible = registre.Registre()
    decisions.enregistrer_decision(_decision(statut="validee"), registre_cible, HORODATAGE)

    statut = decisions.statut_courant(registre_cible, "DEC-001")

    assert statut == "validee"


def test_statut_courant_suit_la_derniere_ecriture_sans_ecraser_les_maillons():
    registre_cible = registre.Registre()
    decisions.enregistrer_decision(_decision(statut="proposee"), registre_cible, HORODATAGE)
    decisions.enregistrer_decision(_decision(statut="validee"), registre_cible, HORODATAGE)
    decisions.enregistrer_decision(
        _decision(statut="remplacee"), registre_cible, HORODATAGE
    )

    statut = decisions.statut_courant(registre_cible, "DEC-001")

    assert statut == "remplacee"
    assert len(registre_cible.lire()) == 3


def test_statut_courant_de_deux_decisions_differentes_n_interfere_pas():
    registre_cible = registre.Registre()
    decisions.enregistrer_decision(
        _decision("DEC-001", "validee"), registre_cible, HORODATAGE
    )
    decisions.enregistrer_decision(
        _decision("DEC-002", "annulee"), registre_cible, HORODATAGE
    )

    assert decisions.statut_courant(registre_cible, "DEC-001") == "validee"
    assert decisions.statut_courant(registre_cible, "DEC-002") == "annulee"


def test_statut_courant_relit_la_chaine_et_la_falsification_est_detectee():
    registre_cible = registre.Registre()
    decisions.enregistrer_decision(
        _decision(statut="proposee"), registre_cible, HORODATAGE
    )
    registre_cible._chain[0]["statut"] = "validee"

    statut = decisions.statut_courant(registre_cible, "DEC-001")
    chaine_valide, _ = registre_cible.valider_chaine()

    assert statut == "validee"
    assert chaine_valide is False


def test_indetermine_est_un_statut_legitime():
    registre_cible = registre.Registre()

    maillon, erreur = decisions.enregistrer_decision(
        _decision(statut=contrats.ECHAPPATOIRE_INDETERMINE),
        registre_cible,
        HORODATAGE,
    )

    assert erreur is None
    assert maillon is not None
    assert decisions.statut_courant(registre_cible, "DEC-001") == "indetermine"


def test_horodatage_sans_fuseau_leve_value_error():
    registre_cible = registre.Registre()

    with pytest.raises(ValueError):
        decisions.enregistrer_decision(
            _decision(), registre_cible, "2026-08-04T12:00:00"
        )


def test_enregistrements_successifs_sont_chainés_et_valides():
    registre_cible = registre.Registre()
    premier, erreur_premier = decisions.enregistrer_decision(
        _decision("DEC-001"), registre_cible, HORODATAGE
    )
    second, erreur_second = decisions.enregistrer_decision(
        _decision("DEC-002"), registre_cible, HORODATAGE
    )

    chaine_valide, _ = registre_cible.valider_chaine()

    assert erreur_premier is None
    assert erreur_second is None
    assert second["precedent_ligne_id"] == premier["ligne_id"]
    assert chaine_valide is True


def test_decisions_cohabitent_avec_evenements_et_les_ignorent():
    registre_cible = registre.Registre()
    registre_cible.ajouter(
        {
            "type_entree": "evenement_memorise",
            "horodatage": HORODATAGE,
        }
    )
    maillon, erreur = decisions.enregistrer_decision(
        _decision("DEC-001", "validee"), registre_cible, HORODATAGE
    )

    chaine_valide, _ = registre_cible.valider_chaine()

    assert erreur is None
    assert maillon is not None
    assert chaine_valide is True
    assert decisions.statut_courant(registre_cible, "DEC-001") == "validee"
