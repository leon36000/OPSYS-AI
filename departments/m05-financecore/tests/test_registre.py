from decimal import Decimal

import pytest
from m5_financecore import registre, validation

HORODATAGE = "2026-08-03T12:00:00+00:00"


def _entree_demande(suffix=""):
    """Entrée générique non monétaire; les mouvements suivent un contrat strict séparé."""
    return {
        "type_entree": "demande_creee",
        "horodatage": HORODATAGE,
        "valeur": suffix,
    }


def _mouvement(source="caisse-principale"):
    return {
        "montant": Decimal("125.00"),
        "type_mouvement": "ENCAISSEMENT",
        "horodatage": HORODATAGE,
        "classe_retention": "STANDARD",
        "source": source,
    }


def test_type_entree_valide_est_present_dans_l_enumeration_privee():
    assert "mouvement_enregistre" in registre._TYPE_ENTREE_VALIDES


def test_types_entree_facture_sont_presents_dans_l_enumeration_privee():
    """M5.2 (facturation.py) : troisième famille sur le même registre générique."""
    assert "facture_creee" in registre._TYPE_ENTREE_VALIDES
    assert "transition_facture" in registre._TYPE_ENTREE_VALIDES


def test_ajouter_accepte_un_maillon_facture_creee_sans_validation_specifique():
    """Contrairement à `mouvement_enregistre`, `facture_creee` n'a aucune validation de structure
    dans `Registre.ajouter` (comme `demande_creee`/`transition_approbation`) : la validation vit
    entièrement dans `facturation.py`, avant l'appel à `ajouter`."""
    journal = registre.Registre()

    ligne_id = journal.ajouter(
        {"type_entree": "facture_creee", "facture_id": "FACT-1", "horodatage": HORODATAGE}
    )

    assert journal.lire()[0]["ligne_id"] == ligne_id
    assert journal.valider_chaine() == (True, "")


def test_ajouter_retourne_un_ligne_id_et_lire_retourne_le_maillon_complet():
    journal = registre.Registre()

    ligne_id = journal.ajouter(_entree_demande())

    assert isinstance(ligne_id, str)
    assert ligne_id
    maillons = journal.lire()
    assert len(maillons) == 1
    assert maillons[0]["ligne_id"] == ligne_id
    assert maillons[0]["precedent_ligne_id"] is None
    assert maillons[0]["type_entree"] == "demande_creee"


def test_ajouter_protege_le_maillon_de_la_mutation_de_l_entree_originale():
    journal = registre.Registre()
    entree = _entree_demande()
    journal.ajouter(entree)

    entree["valeur"] = "modifiee"
    entree["nouvelle_cle"] = True

    maillon = journal.lire()[0]
    assert maillon["valeur"] == ""
    assert "nouvelle_cle" not in maillon


def test_lire_retourne_des_copies_profondes():
    journal = registre.Registre()
    journal.ajouter(_entree_demande())

    copie = journal.lire()
    copie[0]["valeur"] = "modifiee"

    assert journal.lire()[0]["valeur"] == ""


def test_tete_vaut_none_pour_un_registre_vide_puis_le_dernier_id():
    journal = registre.Registre()

    assert journal.tete() is None

    premier_id = journal.ajouter(_entree_demande("premier"))
    second_id = journal.ajouter(_entree_demande("second"))

    assert journal.tete() == second_id
    assert second_id != premier_id


def test_une_chaine_de_trois_maillons_est_valide():
    journal = registre.Registre()

    journal.ajouter(_entree_demande("un"))
    journal.ajouter(_entree_demande("deux"))
    journal.ajouter(_entree_demande("trois"))

    assert journal.valider_chaine() == (True, "")


def test_type_entree_inconnu_leve_value_error():
    journal = registre.Registre()

    with pytest.raises(ValueError):
        journal.ajouter(
            {
                "type_entree": "type_inconnu",
                "horodatage": HORODATAGE,
            }
        )


def test_horodatage_absent_leve_une_erreur():
    journal = registre.Registre()

    with pytest.raises((KeyError, ValueError)):
        journal.ajouter({"type_entree": "mouvement_enregistre"})


@pytest.mark.parametrize(
    "horodatage",
    ["pas-une-date", "2026-08-03T12:00:00"],
)
def test_horodatage_invalide_ou_sans_fuseau_leve_value_error(horodatage):
    journal = registre.Registre()

    with pytest.raises(ValueError):
        journal.ajouter(
            {
                "type_entree": "mouvement_enregistre",
                "horodatage": horodatage,
            }
        )


def test_enregistrer_mouvement_chaine_deux_maillons_et_conserve_les_champs():
    journal = registre.Registre()
    mouvement = _mouvement()

    premier = registre.enregistrer_mouvement(mouvement, journal)
    second = registre.enregistrer_mouvement(mouvement, journal)

    assert premier["type_entree"] == "mouvement_enregistre"
    assert second["type_entree"] == "mouvement_enregistre"
    assert premier["ligne_id"] != second["ligne_id"]
    assert premier["precedent_ligne_id"] is None
    assert second["precedent_ligne_id"] == premier["ligne_id"]

    for champ, valeur in mouvement.items():
        assert premier[champ] == valeur
        assert second[champ] == valeur

    assert type(premier["montant"]) is Decimal
    assert type(second["montant"]) is Decimal
    assert journal.valider_chaine() == (True, "")

    assert set(premier) == {
        "montant",
        "type_mouvement",
        "horodatage",
        "classe_retention",
        "source",
        "type_entree",
        "ligne_id",
        "precedent_ligne_id",
    }
    assert journal.lire() == [premier, second]


def test_enregistrer_mouvement_rejette_float_sans_ecrire():
    journal = registre.Registre()
    mouvement = _mouvement()
    mouvement["montant"] = 0.1

    with pytest.raises(validation.MouvementInvalide) as erreur:
        registre.enregistrer_mouvement(mouvement, journal)

    assert erreur.value.verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"
    assert journal.lire() == []


def test_ajouter_accepte_un_maillon_mouvement_decimal_complet():
    journal = registre.Registre()
    entree = {**_mouvement(), "type_entree": "mouvement_enregistre"}

    ligne_id = journal.ajouter(entree)

    assert journal.lire()[0]["ligne_id"] == ligne_id
    assert journal.lire()[0]["montant"] == Decimal("125.00")
    assert journal.valider_chaine() == (True, "")


def test_ajouter_rejette_un_champ_mouvement_inattendu_sans_ecrire():
    journal = registre.Registre()
    entree = {
        **_mouvement(),
        "type_entree": "mouvement_enregistre",
        "devise": "CAD",
    }

    with pytest.raises(validation.MouvementInvalide) as erreur:
        journal.ajouter(entree)

    assert erreur.value.verdict["code"] == "REJ-MOUVEMENT-STRUCTURE-INVALIDE"
    assert journal.lire() == []


def test_ajouter_rejette_un_maillon_mouvement_booleen_sans_ecrire():
    journal = registre.Registre()
    entree = {**_mouvement(), "type_entree": "mouvement_enregistre", "montant": True}

    with pytest.raises(validation.MouvementInvalide) as erreur:
        journal.ajouter(entree)

    assert erreur.value.verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"
    assert journal.lire() == []


def test_ajouter_recalcule_les_identifiants_d_un_maillon_mouvement():
    journal = registre.Registre()
    entree = {
        **_mouvement(),
        "type_entree": "mouvement_enregistre",
        "ligne_id": "faux-ligne-id",
        "precedent_ligne_id": "faux-precedent-id",
    }

    ligne_id = journal.ajouter(entree)
    maillon = journal.lire()[0]

    assert maillon["ligne_id"] == ligne_id
    assert maillon["ligne_id"] != "faux-ligne-id"
    assert maillon["precedent_ligne_id"] is None
    assert journal.valider_chaine() == (True, "")


@pytest.mark.parametrize(
    "montant",
    [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_ajouter_rejette_un_decimal_non_fini_sans_ecrire(montant):
    journal = registre.Registre()
    entree = {**_mouvement(), "type_entree": "mouvement_enregistre", "montant": montant}

    with pytest.raises(validation.MouvementInvalide) as erreur:
        journal.ajouter(entree)

    assert erreur.value.verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"
    assert journal.lire() == []


def test_ajouter_rejette_un_maillon_mouvement_float_sans_ecrire():
    journal = registre.Registre()

    with pytest.raises(validation.MouvementInvalide) as erreur:
        journal.ajouter(
            {
                "montant": 0.1,
                "type_mouvement": "ENCAISSEMENT",
                "horodatage": HORODATAGE,
                "classe_retention": "STANDARD",
                "source": "test",
                "type_entree": "mouvement_enregistre",
            }
        )

    assert erreur.value.verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"
    assert journal.lire() == []


def test_valider_chaine_detecte_une_valeur_de_maillon_falsifiee():
    journal = registre.Registre()
    journal.ajouter(_entree_demande("un"))
    journal.ajouter(_entree_demande("deux"))
    journal.ajouter(_entree_demande("trois"))

    journal._chain[1]["valeur"] = "falsifie"

    valide, detail = journal.valider_chaine()

    assert valide is False
    assert detail


def test_valider_chaine_detecte_un_ligne_id_falsifie():
    journal = registre.Registre()
    journal.ajouter(_entree_demande("un"))
    journal.ajouter(_entree_demande("deux"))

    journal._chain[0]["ligne_id"] = "faux-ligne-id"

    valide, detail = journal.valider_chaine()

    assert valide is False
    assert detail


def test_valider_chaine_detecte_une_troncature_du_debut_de_chaine():
    journal = registre.Registre()
    journal.ajouter(_entree_demande("un"))
    journal.ajouter(_entree_demande("deux"))

    del journal._chain[0]

    valide, detail = journal.valider_chaine()

    assert valide is False
    assert detail
