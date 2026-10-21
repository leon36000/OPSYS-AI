from copy import deepcopy

import pytest
from m10_memoire import contrats, registre, revision

HORODATAGE = "2026-08-04T12:00:00+00:00"


def _evenement(valeur="origine"):
    return {
        "type_entree": "evenement_memorise",
        "horodatage": HORODATAGE,
        "valeur": valeur,
    }


def _deux_evenements(registre_cible):
    ligne_id_a = registre_cible.ajouter(_evenement("origine-a"))
    ligne_id_b = registre_cible.ajouter(_evenement("origine-b"))
    return ligne_id_a, ligne_id_b


def _signaler(registre_cible):
    ligne_id_a, ligne_id_b = _deux_evenements(registre_cible)
    signalement, erreur = revision.signaler_revision(
        registre_cible, ligne_id_a, ligne_id_b, HORODATAGE
    )
    assert erreur is None
    assert signalement is not None
    return ligne_id_a, ligne_id_b, signalement, registre_cible.lire()[-1]["ligne_id"]


def test_signaler_revision_valide_ecrit_un_maillon_en_attente():
    registre_cible = registre.Registre()
    ligne_id_a, ligne_id_b = _deux_evenements(registre_cible)

    maillon, erreur = revision.signaler_revision(
        registre_cible, ligne_id_a, ligne_id_b, HORODATAGE
    )

    assert erreur is None
    assert maillon is not None
    assert maillon["ligne_id_a"] == ligne_id_a
    assert maillon["ligne_id_b"] == ligne_id_b
    assert maillon["statut"] == "en_attente"
    assert maillon["type_entree"] == "revision_signalee"


def test_signaler_revision_ne_modifie_jamais_les_maillons_signales():
    registre_cible = registre.Registre()
    ligne_id_a, ligne_id_b = _deux_evenements(registre_cible)
    avant = deepcopy(registre_cible.lire())

    maillon, erreur = revision.signaler_revision(
        registre_cible, ligne_id_a, ligne_id_b, HORODATAGE
    )

    assert erreur is None
    assert maillon is not None
    apres = registre_cible.lire()
    assert len(apres) == len(avant) + 1
    assert [ligne for ligne in apres if ligne["ligne_id"] == ligne_id_a] == [
        ligne for ligne in avant if ligne["ligne_id"] == ligne_id_a
    ]
    assert [ligne for ligne in apres if ligne["ligne_id"] == ligne_id_b] == [
        ligne for ligne in avant if ligne["ligne_id"] == ligne_id_b
    ]


def test_signaler_revision_refuse_un_maillon_contre_lui_meme():
    registre_cible = registre.Registre()
    ligne_id_a, _ = _deux_evenements(registre_cible)
    taille_avant = len(registre_cible.lire())

    maillon, erreur = revision.signaler_revision(
        registre_cible, ligne_id_a, ligne_id_a, HORODATAGE
    )

    assert maillon is None
    assert erreur is not None
    assert len(registre_cible.lire()) == taille_avant


def test_signaler_revision_refuse_une_ligne_inexistante():
    registre_cible = registre.Registre()
    ligne_id_a, _ = _deux_evenements(registre_cible)
    taille_avant = len(registre_cible.lire())

    maillon, erreur = revision.signaler_revision(
        registre_cible, ligne_id_a, "ligne-inexistante", HORODATAGE
    )

    assert maillon is None
    assert erreur is not None
    assert len(registre_cible.lire()) == taille_avant


def test_arbitrer_revision_ecrit_un_nouveau_maillon_sans_muter_le_signalement():
    registre_cible = registre.Registre()
    _, _, signalement, revision_ligne_id = _signaler(registre_cible)
    signalement_avant = deepcopy(
        next(
            ligne
            for ligne in registre_cible.lire()
            if ligne["ligne_id"] == revision_ligne_id
        )
    )

    arbitrage, erreur = revision.arbitrer_revision(
        registre_cible,
        revision_ligne_id,
        "distincts_confirmes",
        HORODATAGE,
    )

    assert erreur is None
    assert arbitrage is not None
    assert arbitrage["type_entree"] == "revision_signalee"
    assert arbitrage["revision_ligne_id"] == revision_ligne_id
    assert arbitrage["statut"] == "distincts_confirmes"
    signalement_apres = next(
        ligne
        for ligne in registre_cible.lire()
        if ligne["ligne_id"] == revision_ligne_id
    )
    assert signalement_apres == signalement_avant
    assert signalement_apres["statut"] == "en_attente"
    assert revision.statut_revision(registre_cible, revision_ligne_id) == "distincts_confirmes"


def test_arbitrer_revision_refuse_une_revision_inexistante():
    """L'arbitrage doit cibler un signalement RÉELLEMENT écrit au registre.

    Avant ce correctif, ``arbitrer_revision`` ne vérifiait que la validité du
    statut fourni, jamais l'existence du signalement visé par
    ``revision_ligne_id`` — un arbitrage sur un ``ligne_id`` inventé (ou sur le
    ligne_id d'un maillon qui n'est PAS un signalement) était accepté et
    écrivait quand même un maillon.
    """
    registre_cible = registre.Registre()
    taille_avant = len(registre_cible.lire())

    arbitrage, erreur = revision.arbitrer_revision(
        registre_cible, "ligne-jamais-signalee", "obsolete_marquee", HORODATAGE
    )

    assert arbitrage is None
    assert erreur is not None
    assert erreur.startswith("REJ-")
    assert len(registre_cible.lire()) == taille_avant


def test_arbitrer_revision_refuse_de_cibler_un_evenement_qui_n_est_pas_un_signalement():
    """``revision_ligne_id`` doit être un ligne_id de SIGNALEMENT, jamais le
    ligne_id d'un maillon quelconque (ex. un événement mémorisé) qui aurait pu
    exister par ailleurs dans le même registre.
    """
    registre_cible = registre.Registre()
    ligne_id_evenement = registre_cible.ajouter(_evenement("pas-un-signalement"))
    taille_avant = len(registre_cible.lire())

    arbitrage, erreur = revision.arbitrer_revision(
        registre_cible, ligne_id_evenement, "obsolete_marquee", HORODATAGE
    )

    assert arbitrage is None
    assert erreur is not None
    assert len(registre_cible.lire()) == taille_avant


def test_arbitrer_revision_valide_reste_accepte_apres_le_correctif():
    """Non-régression explicite : un arbitrage sur un VRAI signalement (y
    compris un second arbitrage du même signalement, cf.
    test_statut_revision_suit_le_dernier_arbitrage_et_chaine_append_only) doit
    continuer d'être accepté après l'ajout de la garde d'existence.
    """
    registre_cible = registre.Registre()
    _, _, _, revision_ligne_id = _signaler(registre_cible)

    arbitrage, erreur = revision.arbitrer_revision(
        registre_cible, revision_ligne_id, "obsolete_marquee", HORODATAGE
    )

    assert erreur is None
    assert arbitrage is not None


def test_arbitrer_revision_accepte_obsolete_marquee():
    registre_cible = registre.Registre()
    _, _, _, revision_ligne_id = _signaler(registre_cible)

    arbitrage, erreur = revision.arbitrer_revision(
        registre_cible, revision_ligne_id, "obsolete_marquee", HORODATAGE
    )

    assert erreur is None
    assert arbitrage is not None
    assert arbitrage["statut"] == "obsolete_marquee"


@pytest.mark.parametrize("statut", ["fusionnes", "FUSION", "valide"])
def test_arbitrer_revision_refuse_tout_statut_hors_enumeration(statut):
    registre_cible = registre.Registre()
    _, _, _, revision_ligne_id = _signaler(registre_cible)
    taille_avant = len(registre_cible.lire())

    arbitrage, erreur = revision.arbitrer_revision(
        registre_cible, revision_ligne_id, statut, HORODATAGE
    )

    assert arbitrage is None
    assert erreur is not None
    assert statut not in contrats.STATUT_REVISION
    assert len(registre_cible.lire()) == taille_avant


def test_arbitrer_revision_accepte_echappatoire_indetermine():
    registre_cible = registre.Registre()
    _, _, _, revision_ligne_id = _signaler(registre_cible)

    arbitrage, erreur = revision.arbitrer_revision(
        registre_cible,
        revision_ligne_id,
        contrats.ECHAPPATOIRE_INDETERMINE,
        HORODATAGE,
    )

    assert erreur is None
    assert arbitrage is not None
    assert arbitrage["statut"] == "indetermine"


def test_revision_n_expose_aucune_fonction_de_fusion_ou_suppression():
    assert not hasattr(revision, "fusionner")
    assert not hasattr(revision, "fusionner_maillons")
    assert not hasattr(revision, "merger")
    assert not hasattr(revision, "supprimer")


def test_statut_revision_suit_le_dernier_arbitrage_et_chaine_append_only():
    registre_cible = registre.Registre()
    _, _, _, revision_ligne_id = _signaler(registre_cible)

    premier, erreur_premier = revision.arbitrer_revision(
        registre_cible, revision_ligne_id, "distincts_confirmes", HORODATAGE
    )
    second, erreur_second = revision.arbitrer_revision(
        registre_cible, revision_ligne_id, "obsolete_marquee", HORODATAGE
    )

    assert erreur_premier is None
    assert erreur_second is None
    assert premier is not None
    assert second is not None
    arbitrages = [
        ligne
        for ligne in registre_cible.lire()
        if ligne.get("revision_ligne_id") == revision_ligne_id
    ]
    assert len(arbitrages) == 2
    assert revision.statut_revision(registre_cible, revision_ligne_id) == "obsolete_marquee"
    assert registre_cible.valider_chaine()[0] is True


def test_statut_revision_inconnu_retourne_none():
    registre_cible = registre.Registre()

    assert revision.statut_revision(registre_cible, "revision-inconnue") is None
