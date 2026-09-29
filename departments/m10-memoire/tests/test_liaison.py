"""liaison.py : l'affaire d'un tour vient de la SESSION, jamais du texte de la demande (PLAN T3.3-suite-b).

Module pur, exercé sur un registre en mémoire. Données fictives (`fictif: true`).
"""

import pytest
from m10_memoire import liaison, registre

FICTIF = True
HORODATAGE = "2026-09-16T09:00:00-04:00"
PLUS_TARD = "2026-09-20T09:00:00-04:00"
CLE_CLIENT = "agent:m01-front-office:whatsapp:direct:+15145550101"
AUTRE_CLIENT = "agent:m01-front-office:whatsapp:direct:+15145550102"
MOTIF = "Le client a écrit depuis ce numéro : c'est bien son dossier."


@pytest.fixture
def affaires():
    return registre.Registre()


def _lier(affaires, cle=CLE_CLIENT, affaire="LEAD-1", par="amina.admin", role="admin", source="appareil",
          motif=MOTIF, horodatage=HORODATAGE):
    return liaison.lier_session_affaire(cle, affaire, par, role, source, motif, horodatage, affaires)


def test_une_session_sans_lien_n_a_pas_d_affaire(affaires):
    assert liaison.affaire_de_la_session(CLE_CLIENT, affaires) == {"lie": False, "affaire_id": None}


def test_lier_ecrit_qui_quand_et_pourquoi_et_la_lecture_le_rend(affaires):
    maillon, verdict = _lier(affaires)

    assert verdict is None
    assert (maillon["type_entree"], maillon["cle_session"], maillon["affaire_id"]) == (
        "session_affaire_liee", CLE_CLIENT, "LEAD-1")
    assert (maillon["par"], maillon["role"], maillon["source_decision"], maillon["motif"]) == (
        "amina.admin", "admin", "appareil", MOTIF)
    assert liaison.affaire_de_la_session(CLE_CLIENT, affaires) == {
        "lie": True, "affaire_id": "LEAD-1", "lie_par": "amina.admin", "lie_le": HORODATAGE}


def test_le_lien_d_une_session_ne_vaut_pas_pour_une_autre(affaires):
    _lier(affaires)

    assert liaison.affaire_de_la_session(AUTRE_CLIENT, affaires)["lie"] is False


def test_un_nouveau_lien_remplace_le_precedent_sans_effacer_l_historique(affaires):
    _lier(affaires, affaire="LEAD-1")
    _lier(affaires, affaire="LEAD-2", horodatage=PLUS_TARD)

    assert liaison.affaire_de_la_session(CLE_CLIENT, affaires)["affaire_id"] == "LEAD-2"
    assert [m["affaire_id"] for m in affaires.lire() if m["type_entree"] == "session_affaire_liee"] == [
        "LEAD-1", "LEAD-2"]
    assert affaires.valider_chaine()[0] is True


@pytest.mark.parametrize(
    "cle",
    [
        "",
        "main",
        "agent:m01-front-office:main",  # la session principale est partagée par tous les correspondants
        "agent:m01-front-office",
        "AGENT:m01-front-office:whatsapp:direct:+1514",
        "agent:m01-front-office:whatsapp:direct:+1514 555",
        "agent:m01-front-office:whatsapp:direct:+1514\n555",
        "agent:M01:whatsapp:direct:x",
        "agent:m01-front-office:WhatsApp:direct:x",
        None,
        12,
    ],
)
def test_une_cle_de_session_qui_n_est_pas_celle_d_un_correspondant_est_refusee(affaires, cle):
    maillon, verdict = _lier(affaires, cle=cle)

    assert maillon is None and verdict["code"] == liaison.REJ_LIAISON_CLE_SESSION_INVALIDE
    assert affaires.lire() == []
    with pytest.raises(ValueError):
        liaison.affaire_de_la_session(cle, affaires)


@pytest.mark.parametrize("affaire", ["", " ", "LEAD 1", "LEAD-1\nLEAD-2", "-LEAD", "x" * 65, None, 7])
def test_une_affaire_invalide_est_refusee(affaires, affaire):
    maillon, verdict = _lier(affaires, affaire=affaire)

    assert maillon is None and verdict["code"] == liaison.REJ_LIAISON_AFFAIRE_INVALIDE
    assert affaires.lire() == []


@pytest.mark.parametrize(
    "surcharges,code",
    [
        ({"role": "employee"}, "REJ-HUMAIN-ACTEUR-INVALIDE"),
        ({"role": "system_agent"}, "REJ-HUMAIN-ACTEUR-INVALIDE"),
        ({"par": "Le Modele"}, "REJ-HUMAIN-ACTEUR-INVALIDE"),
        ({"source": "texte_du_client"}, "REJ-HUMAIN-ACTEUR-INVALIDE"),
        ({"motif": ""}, "REJ-HUMAIN-MOTIF-INVALIDE"),
        ({"motif": "ok"}, "REJ-HUMAIN-MOTIF-INVALIDE"),
        ({"horodatage": "hier"}, "REJ-HUMAIN-HORODATAGE-INVALIDE"),
    ],
)
def test_sans_humain_identifie_et_motive_rien_n_est_lie(affaires, surcharges, code):
    maillon, verdict = _lier(affaires, **surcharges)

    assert maillon is None and verdict["code"] == code
    assert affaires.lire() == []


def test_un_lien_ecrit_hors_du_chemin_de_l_outil_par_un_non_humain_est_ignore(affaires):
    affaires.ajouter({
        "type_entree": liaison.TYPE_ENTREE_LIAISON, "horodatage": HORODATAGE, "cle_session": CLE_CLIENT,
        "affaire_id": "LEAD-PIRATE", "par": "le-modele", "role": "system_agent", "source_decision": "modele",
        "motif": MOTIF,
    })

    assert liaison.affaire_de_la_session(CLE_CLIENT, affaires)["lie"] is False


def test_un_lien_force_apres_un_lien_valide_ne_le_remplace_pas(affaires):
    _lier(affaires, affaire="LEAD-1")
    affaires.ajouter({
        "type_entree": liaison.TYPE_ENTREE_LIAISON, "horodatage": PLUS_TARD, "cle_session": CLE_CLIENT,
        "affaire_id": "LEAD-PIRATE", "par": "le-modele", "role": "system_agent", "source_decision": "modele",
        "motif": MOTIF,
    })

    assert liaison.affaire_de_la_session(CLE_CLIENT, affaires)["affaire_id"] == "LEAD-1"
