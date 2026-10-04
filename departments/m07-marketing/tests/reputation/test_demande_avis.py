"""Tests — brouillon de demande d'avis à partir d'un WCT `m4.travaux_termines` (PLAN T1.2-c, T1.5-d).

`construire_brouillon` est une fonction pure (aucun import `opsys`, testée ici sans base de
données ni bus d'événements) ; l'intégration bout en bout (bus réel, registre durable,
idempotence de l'adaptateur, taxonomie) est couverte par `tests/test_evenements_travaux_termines.py`.

PLAN T1.5-d : la demande naît du consentement du CLIENT à être contacté pour un avis
(`consentement_demande_avis`, distinct de `consentement_marketing`), avec sa preuve (qui, quand, quel texte).
"""

from __future__ import annotations

import pytest
from m7_marketing.reputation import demande_avis

# ---------------------------------------------------------------------------
# Données de test (forme d'un WCT m4.travaux_termines, champs requis minimaux + optionnels M7)
# ---------------------------------------------------------------------------
_WCT_BASE = {
    "wct_id": "wct-demo-1",
    "intervention_id": "int-1",
    "lead_id": "lead-1",
    "technicien_id": "tech-1",
    "horodatage_completion": "2026-09-28T14:00:00-04:00",
    "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
    "duree_reelle_minutes": 180,
    "ecart_signale": False,
    "revue_id": None,
    "hash_maillon": "deadbeef",
    "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
    "devis_id": "devis-1",
    "statut": "completed_verified",
}
_PREUVE = {
    "consentement_recueilli_par": "etienne",
    "consentement_recueilli_le": "2026-09-28T18:05:00+00:00",
    "consentement_version_texte": "consentement-client-fr-CA-v1",
}


def _wct(**overrides):
    charge = dict(_WCT_BASE)
    charge.update(overrides)
    return charge


def _wct_consenti(**overrides):
    """Un WCT dont le client a consenti à la demande d'avis, preuve comprise."""
    return _wct(consentement_demande_avis=True, **_PREUVE, **overrides)


# ---------------------------------------------------------------------------
# Éligibilité : consentement vrai et prouvé ; satisfaction sans effet sur la sélection
# ---------------------------------------------------------------------------
def test_consentement_prouve_produit_un_brouillon_propose():
    charge = _wct_consenti(ville="Repentigny", type_travaux="gouttières", client_satisfait=True)
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert motif is None
    assert brouillon["approval_status"] == "PROPOSE"
    assert brouillon["wct_id"] == "wct-demo-1"
    assert brouillon["intervention_id"] == "int-1"
    assert brouillon["lead_id"] == "lead-1"
    assert brouillon["ville"] == "Repentigny"
    assert brouillon["type_travaux"] == "gouttières"
    assert "gouttières à Repentigny" in brouillon["texte"]


def test_le_brouillon_garde_la_preuve_du_consentement_lue_dans_le_wct():
    brouillon, _ = demande_avis.construire_brouillon(_wct_consenti())
    assert brouillon["preuve_consentement"] == {
        "consentement_demande_avis": True,
        "recueilli_par": "etienne",
        "recueilli_le": "2026-09-28T18:05:00+00:00",
        "version_texte": "consentement-client-fr-CA-v1",
        "source": "wct_m4_travaux_termines",
        "wct_id": "wct-demo-1",
    }


def test_satisfaction_null_non_recueillie_ne_refuse_pas():
    """`client_satisfait: null` (« non recueilli, jamais inventé », catalogue m4.travaux_termines) n'est pas
    `false` : c'est le client qui a demandé à être sollicité, la satisfaction n'est plus un préalable."""
    brouillon, motif = demande_avis.construire_brouillon(_wct_consenti(client_satisfait=None))
    assert motif is None
    assert brouillon is not None


def test_satisfaction_absente_ne_refuse_plus():
    """Elle refusait en T1.2-c (« tout champ absent vaut refus ») : avec le consentement du client à la
    demande d'avis, son absence ne dit rien contre la demande."""
    charge = _wct_consenti()
    assert "client_satisfait" not in charge
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert motif is None
    assert brouillon is not None


# ---------------------------------------------------------------------------
# Fail-closed : tout champ absent ou défavorable vaut refus, jamais un brouillon
# ---------------------------------------------------------------------------
def test_consentement_absent_refuse_fail_closed():
    charge = _wct(client_satisfait=True, **_PREUVE)  # consentement_demande_avis absent du tout
    assert "consentement_demande_avis" not in charge
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert brouillon is None
    assert motif == demande_avis.REFUS_CONSENTEMENT_ABSENT


def test_consentement_faux_refuse():
    charge = _wct(consentement_demande_avis=False, client_satisfait=True, **_PREUVE)
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert brouillon is None
    assert motif == demande_avis.REFUS_CONSENTEMENT_FAUX


@pytest.mark.parametrize("valeur", ["true", 1, "oui", None])
def test_un_consentement_qui_n_est_pas_strictement_vrai_refuse(valeur):
    brouillon, motif = demande_avis.construire_brouillon(_wct(consentement_demande_avis=valeur, **_PREUVE))
    assert brouillon is None
    assert motif == demande_avis.REFUS_CONSENTEMENT_FAUX


def test_le_consentement_aux_photos_ne_vaut_pas_consentement_a_la_demande_d_avis():
    """Loi 25 (POLITIQUE-photos-non-contractuelles.md §3) : deux consentements distincts. Un client qui accepte
    les photos n'a pas accepté d'être contacté pour un avis, et l'inverse."""
    charge = _wct(consentement_marketing=True, client_satisfait=True, **_PREUVE)
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert brouillon is None
    assert motif == demande_avis.REFUS_CONSENTEMENT_ABSENT


@pytest.mark.parametrize("cle", demande_avis.CLES_PREUVE)
def test_un_consentement_sans_sa_preuve_refuse(cle):
    charge = _wct_consenti()
    del charge[cle]
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert brouillon is None
    assert motif == demande_avis.REFUS_PREUVE_ABSENTE


@pytest.mark.parametrize("vide", ["", "   ", None, 7])
def test_une_preuve_vide_ou_mal_typee_refuse(vide):
    charge = _wct_consenti()
    charge["consentement_recueilli_par"] = vide
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert brouillon is None
    assert motif == demande_avis.REFUS_PREUVE_ABSENTE


def test_client_insatisfait_recoit_la_meme_demande_neutre_et_un_brouillon_a_approuver():
    charge = _wct_consenti(client_satisfait=False)
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert motif is None
    assert brouillon["approval_status"] == "PROPOSE"
    assert "Si vous le souhaitez" in brouillon["texte"]
    assert "honnête" in brouillon["texte"]


@pytest.mark.parametrize("satisfaction", [False, None])
def test_satisfaction_ne_change_pas_l_eligibilite_a_la_demande_d_avis(satisfaction):
    brouillon, motif = demande_avis.construire_brouillon(_wct_consenti(client_satisfait=satisfaction))
    assert motif is None
    assert brouillon["approval_status"] == "PROPOSE"


# ---------------------------------------------------------------------------
# Gabarit fixe : jamais un fait inventé quand ville / nature des travaux manquent
# ---------------------------------------------------------------------------
def test_gabarit_sans_ville_ni_nature_reste_generique():
    brouillon, _ = demande_avis.construire_brouillon(_wct_consenti())
    assert brouillon["ville"] is None
    assert brouillon["type_travaux"] is None and brouillon["service"] is None
    assert brouillon["nature_travaux"] is None
    assert "pour vos travaux. " in brouillon["texte"]
    assert "None" not in brouillon["texte"]


def test_gabarit_avec_ville_seule():
    brouillon, _ = demande_avis.construire_brouillon(_wct_consenti(ville="Lévis"))
    assert "à Lévis" in brouillon["texte"]


# ---------------------------------------------------------------------------
# Nature des travaux (PLAN T0.13-b) : type_travaux d'un lead v1, libellé du service d'un lead v2
# ---------------------------------------------------------------------------
def test_lead_v1_le_texte_dit_type_travaux_sans_les_soulignes():
    brouillon, _ = demande_avis.construire_brouillon(_wct_consenti(type_travaux="renovation_totale"))
    assert brouillon["type_travaux"] == "renovation_totale"  # la valeur du contrat, telle quelle
    assert brouillon["service"] is None
    assert brouillon["nature_travaux"] == "renovation totale"
    assert "(renovation totale)" in brouillon["texte"]


def test_lead_v2_le_texte_dit_le_libelle_du_service_pas_son_code():
    charge = _wct_consenti(service="gouttieres", ville="Repentigny")
    brouillon, motif = demande_avis.construire_brouillon(charge, "Gouttières et descentes")
    assert motif is None
    assert brouillon["service"] == "gouttieres"
    assert brouillon["type_travaux"] is None  # jamais l'un déduit de l'autre
    assert brouillon["nature_travaux"] == "Gouttières et descentes"
    assert "(Gouttières et descentes à Repentigny)" in brouillon["texte"]
    assert "gouttieres" not in brouillon["texte"]
    assert brouillon["avertissements"] == []


def test_lead_v2_sans_libelle_resolu_n_emprunte_pas_son_code_et_le_dit():
    """Le service n'est pas (ou plus) déclaré par l'entreprise : le texte reste générique, le code brut n'y
    entre pas, et le brouillon dit pourquoi il n'a pas de nature (jamais un silence)."""
    charge = _wct_consenti(service="pose_pergola")
    brouillon, motif = demande_avis.construire_brouillon(
        charge, None, "libellé du service 'pose_pergola' introuvable (REJ-SERVICE-INCONNU)")
    assert motif is None
    assert brouillon["nature_travaux"] is None and brouillon["service"] == "pose_pergola"
    assert "pergola" not in brouillon["texte"]
    assert brouillon["avertissements"] == ["libellé du service 'pose_pergola' introuvable (REJ-SERVICE-INCONNU)"]


def test_un_libelle_fourni_a_un_wct_v1_n_est_pas_utilise():
    """Un libellé n'a de sens que pour un `service` : un WCT v1 dit son `type_travaux`, jamais un libellé."""
    charge = _wct_consenti(type_travaux="extension")
    brouillon, _ = demande_avis.construire_brouillon(charge, "Gouttières et descentes")
    assert brouillon["nature_travaux"] == "extension"
    assert "Gouttières" not in brouillon["texte"]


def test_un_wct_qui_porte_les_deux_natures_est_refuse():
    charge = _wct_consenti(type_travaux="extension", service="gouttieres")
    brouillon, motif = demande_avis.construire_brouillon(charge, "Gouttières et descentes")
    assert brouillon is None
    assert motif == demande_avis.REFUS_NATURE_TRAVAUX_AMBIGUE


# ---------------------------------------------------------------------------
# Identifiant déterministe (condition nécessaire à l'idempotence côté adaptateur)
# ---------------------------------------------------------------------------
def test_id_deterministe_pour_le_meme_wct_id():
    charge = _wct_consenti(wct_id="wct-fixe")
    brouillon1, _ = demande_avis.construire_brouillon(charge)
    brouillon2, _ = demande_avis.construire_brouillon(charge)
    assert brouillon1["id"] == brouillon2["id"]


def test_id_differe_pour_un_wct_id_different():
    brouillon_a, _ = demande_avis.construire_brouillon(_wct_consenti(wct_id="wct-a"))
    brouillon_b, _ = demande_avis.construire_brouillon(_wct_consenti(wct_id="wct-b"))
    assert brouillon_a["id"] != brouillon_b["id"]


# ---------------------------------------------------------------------------
# Jamais d'exception : un refus métier n'est pas une panne
# ---------------------------------------------------------------------------
def test_charge_minimale_sans_champs_optionnels_ne_leve_jamais():
    brouillon, motif = demande_avis.construire_brouillon(_wct())
    assert brouillon is None
    assert isinstance(motif, str) and motif
