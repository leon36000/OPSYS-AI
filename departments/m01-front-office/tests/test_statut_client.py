"""M1-G : le statut client borné, module pur. Table fermée, gabarit fixe, repli exact, aucune fuite de statut brut."""

from __future__ import annotations

import pytest
from m1_front_office import gabarits
from m1_front_office import statut_client as sc

from opsys import garde_fou_texte


def test_les_sujets_sont_l_ensemble_ferme_du_chantier():
    assert sc.SUJETS == ("dossier", "soumission", "visite", "facture")
    assert sc.finalite("facture") == "facturation"
    assert sc.finalite("soumission") == "statut_dossier"


@pytest.mark.parametrize("sujet, brut, attendu", [
    ("dossier", "qualifie", "en qualification"),
    ("dossier", "chantier", "travaux en cours"),
    ("soumission", "brouillon", "en préparation"),
    ("soumission", "envoye", "envoyée, en attente de réponse"),
    ("soumission", "accepte", "acceptée"),
    ("visite", "planifiee", "planifiée"),
    ("visite", "completed_verified", "terminée et vérifiée"),
    ("facture", "BROUILLON", "en préparation"),
    ("facture", "ENVOYEE", "envoyée"),
    ("facture", "PAYEE", "payée"),
])
def test_chaque_statut_brut_connu_a_un_libelle_client(sujet, brut, attendu):
    assert sc.statut_lisible(sujet, brut) == attendu
    resultat = sc.repondre(sujet, brut)
    assert resultat["statut"] == "repondu" and resultat["motif"] == "statut_etabli"
    assert attendu in resultat["reponse"]
    assert sc.TEXTE_REPLI not in resultat["reponse"]


def test_un_statut_inconnu_ne_fuit_jamais_et_rend_le_repli_exact():
    resultat = sc.repondre("facture", "EN_LITIGE_INTERNE")
    assert resultat == {
        "statut": "repli", "sujet": "facture", "reponse": "Je vais vérifier avec l'équipe.",
        "motif": "statut_inconnu",
    }


def test_le_gabarit_est_fixe_et_ne_porte_ni_prix_ni_date_ni_engagement():
    objet, corps = gabarits.rendre("statut_client", {"sujet": "facture", "statut": "envoyée"})
    assert objet is None and "Voici l'état de votre facture : envoyée." in corps
    assert garde_fou_texte.premiere_violation(corps, gabarits.PROFIL_SORTIE) is None


@pytest.mark.parametrize("reference", [None, "", "D-1", "D-1 ", "a" * 128, "a" * 129, "D/1", "D 1", "D-1\n"])
def test_une_reference_de_soumission_est_bornee_et_sans_texte_libre(reference):
    attendu = reference == "D-1" or reference == "a" * 128
    assert sc.reference_valide("soumission", reference) is attendu


def test_un_dossier_n_accepte_aucune_reference():
    assert sc.reference_valide("dossier", None) is True
    assert sc.reference_valide("dossier", "D-1") is False


def test_la_reference_de_facture_est_facultative_et_bornee():
    assert sc.facture_id_valide(None) is True
    assert sc.facture_id_valide("F-01000") is True
    assert sc.facture_id_valide(1) is False
    assert sc.facture_id_valide("") is False
    assert sc.facture_id_valide("a" * 129) is False


def test_le_gabarit_client_est_versionne():
    assert gabarits.GABARITS["statut_client"].version == 1


def test_un_motif_de_repli_inconnu_est_ramene_au_motif_le_plus_sur():
    assert sc.repli("motif_invente")["motif"] == "identite_non_verifiee"
    assert sc.repli("motif_invente")["reponse"] == "Je vais vérifier avec l'équipe."
