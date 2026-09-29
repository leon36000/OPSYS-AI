import pytest
from m10_memoire import registre

HORODATAGE = "2026-08-04T12:00:00+00:00"


def _entree(type_entree="evenement_memorise", valeur=""):
    return {
        "type_entree": type_entree,
        "horodatage": HORODATAGE,
        "valeur": valeur,
    }


def test_types_entree_valides_sont_exactement_ceux_de_m10():
    types_attendus = {
        "evenement_memorise",
        "decision_enregistree",
        "revision_signalee",
        "fait_consolide",  # PLAN T3.3 : consolidation.py
        "fait_candidat",  # PLAN T3.3-suite : faits_candidats.py
    }

    assert types_attendus.issubset(registre._TYPE_ENTREE_VALIDES)
    assert len(registre._TYPE_ENTREE_VALIDES) == 5
    assert "mouvement_enregistre" not in registre._TYPE_ENTREE_VALIDES
    assert "demande_creee" not in registre._TYPE_ENTREE_VALIDES
    assert "transition_approbation" not in registre._TYPE_ENTREE_VALIDES


def test_fait_consolide_est_un_type_entree_accepte():
    journal = registre.Registre()

    ligne_id = journal.ajouter(_entree(type_entree="fait_consolide"))

    assert ligne_id
    assert journal.lire()[0]["type_entree"] == "fait_consolide"


def test_ajouter_retourne_ligne_id_et_premier_maillon_a_precedent_none():
    journal = registre.Registre()

    ligne_id = journal.ajouter(_entree(valeur="memoire"))

    maillons = journal.lire()
    assert isinstance(ligne_id, str)
    assert ligne_id
    assert len(maillons) == 1
    assert maillons[0]["ligne_id"] == ligne_id
    assert maillons[0]["precedent_ligne_id"] is None


def test_ajouter_refuse_une_entree_qui_n_est_pas_un_dict():
    journal = registre.Registre()

    with pytest.raises(TypeError):
        journal.ajouter("pas-un-dict")


def test_ajouter_copie_profondement_le_dict_recu():
    journal = registre.Registre()
    entree = _entree(valeur={"nested": ["origine"]})

    journal.ajouter(entree)
    entree["valeur"]["nested"].append("mutation")

    assert journal.lire()[0]["valeur"] == {"nested": ["origine"]}


def test_lire_retourne_une_copie_profonde():
    journal = registre.Registre()
    journal.ajouter(_entree(valeur={"nested": ["origine"]}))

    lecture = journal.lire()
    lecture[0]["valeur"]["nested"].append("mutation")
    lecture[0]["ligne_id"] = "ligne-falsifiee"

    maillon_interne = journal.lire()[0]
    assert maillon_interne["valeur"] == {"nested": ["origine"]}
    assert maillon_interne["ligne_id"] != "ligne-falsifiee"


def test_tete_est_none_si_vide_puis_designe_le_dernier_maillon():
    journal = registre.Registre()

    assert journal.tete() is None

    premier_id = journal.ajouter(_entree(valeur="premier"))
    second_id = journal.ajouter(_entree(valeur="second"))

    assert premier_id != second_id
    assert journal.tete() == second_id


def test_chaine_de_trois_maillons_est_valide():
    journal = registre.Registre()
    journal.ajouter(_entree(valeur="un"))
    journal.ajouter(_entree(valeur="deux"))
    journal.ajouter(_entree(valeur="trois"))

    assert journal.valider_chaine() == (True, "")


def test_type_entree_inconnu_est_refuse():
    journal = registre.Registre()

    with pytest.raises(ValueError):
        journal.ajouter(_entree(type_entree="type_inconnu"))


def test_horodatage_absent_est_refuse():
    journal = registre.Registre()
    entree = _entree()
    del entree["horodatage"]

    with pytest.raises((KeyError, ValueError)):
        journal.ajouter(entree)


@pytest.mark.parametrize("horodatage", ["pas-une-date", "2026-08-04T12:00:00"])
def test_horodatage_invalide_ou_sans_fuseau_est_refuse(horodatage):
    journal = registre.Registre()
    entree = _entree()
    entree["horodatage"] = horodatage

    with pytest.raises(ValueError):
        journal.ajouter(entree)


def test_valider_chaine_detecte_une_valeur_falsifiee():
    journal = registre.Registre()
    journal.ajouter(_entree(valeur="origine"))

    journal._chain[0]["valeur"] = "falsifiee"

    est_valide, detail = journal.valider_chaine()
    assert est_valide is False
    assert detail


def test_valider_chaine_detecte_un_ligne_id_falsifie():
    journal = registre.Registre()
    journal.ajouter(_entree(valeur="origine"))

    journal._chain[0]["ligne_id"] = "ligne-id-falsifie"

    est_valide, detail = journal.valider_chaine()
    assert est_valide is False
    assert detail


def test_valider_chaine_detecte_une_troncature_du_debut():
    journal = registre.Registre()
    journal.ajouter(_entree(valeur="un"))
    journal.ajouter(_entree(valeur="deux"))
    journal.ajouter(_entree(valeur="trois"))

    del journal._chain[0]

    est_valide, detail = journal.valider_chaine()
    assert est_valide is False
    assert detail


def test_trois_types_de_maillon_cohabitent_dans_une_meme_chaine():
    journal = registre.Registre()

    premier_id = journal.ajouter(_entree("evenement_memorise", "evenement"))
    second_id = journal.ajouter(_entree("decision_enregistree", "decision"))
    troisieme_id = journal.ajouter(_entree("revision_signalee", "revision"))

    maillons = journal.lire()
    assert journal.valider_chaine() == (True, "")
    assert [maillon["type_entree"] for maillon in maillons] == [
        "evenement_memorise",
        "decision_enregistree",
        "revision_signalee",
    ]
    assert maillons[0]["ligne_id"] == premier_id
    assert maillons[1]["ligne_id"] == second_id
    assert maillons[2]["ligne_id"] == troisieme_id
    assert maillons[1]["precedent_ligne_id"] == premier_id
    assert maillons[2]["precedent_ligne_id"] == second_id


def test_deux_instances_sont_totalement_independantes():
    registre_evenements = registre.Registre()
    registre_affaires = registre.Registre()
    entree = _entree(valeur={"contenu": "partage"})

    ligne_id_evenements = registre_evenements.ajouter(entree)

    assert registre_affaires.lire() == []
    assert registre_affaires.tete() is None

    ligne_id_affaires = registre_affaires.ajouter(entree)

    assert ligne_id_evenements == ligne_id_affaires
    assert registre_evenements._chain is not registre_affaires._chain

    registre_evenements._chain[0]["valeur"]["contenu"] = "falsifie"

    assert registre_affaires.lire()[0]["valeur"]["contenu"] == "partage"


def test_aucun_maillon_ne_porte_de_champ_de_permission():
    journal = registre.Registre()
    journal.ajouter(_entree())

    cles_interdites = {"permission", "registre", "visibilite", "monde"}
    maillon = journal.lire()[0]

    assert cles_interdites.isdisjoint(maillon)


def test_registre_n_expose_aucune_methode_de_mutation():
    for nom_methode in ("modifier", "supprimer", "fusionner", "mettre_a_jour"):
        assert not hasattr(registre.Registre, nom_methode)
