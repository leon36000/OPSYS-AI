"""Paquet manuel d'un contenu approuvé (PLAN T4.17, M7.2) : ce que le propriétaire copie, sans rien de publié."""

from __future__ import annotations

import pytest
from m7_marketing.usine import chantier, paquet, plateformes, registre, verdicts

FICTIF = True
HORODATAGE = "2026-09-29T10:00:00-04:00"


def _contenu(charge, profil, nature, code, decision_par="nathan"):
    proposition = next(
        p for p in chantier.preparer(charge, profil, nature, None, [], [], "test").nouvelles if p["plateforme"] == code
    )
    approbation = {"contenu_id": proposition["contenu_id"], "decision": registre.STATUT_APPROUVE, "par": decision_par,
                   "role": "nathan_owner", "source": "appareil", "motif": "", "horodatage": HORODATAGE,
                   "empreinte_texte": proposition["empreinte_texte"]}
    return registre.vue(proposition, [approbation], [], [])


def test_le_paquet_facebook_dit_texte_lien_mots_clics_medias_heure_et_instructions(charge, profil, nature):
    contenu = _contenu(charge, profil, nature, "facebook")
    resultat = paquet.composer_paquet(contenu, charge, [], profil)
    assert resultat["plateforme"] == "facebook" and resultat["public"] is True
    assert resultat["texte"] == contenu["texte"]
    assert resultat["mots_clics"] == ["#gouttiere", "#descentepluviale", "#descentedegouttiere", "#repentigny"]
    assert resultat["lien_utm"].startswith("https://exemple-fictif.ca/?utm_source=facebook")
    # Facebook garde le lien dans le texte à copier ; le texte et les mots-clics restent les siens.
    assert resultat["texte_a_copier"] == "\n\n".join(
        [contenu["texte"], resultat["lien_utm"], " ".join(resultat["mots_clics"])]
    )
    assert resultat["heure_suggeree"] == {"heure_locale": "18:30", "source": "profil de marque (heures_publication)"}
    assert resultat["a_configurer"] == []
    assert resultat["approuve_par"] == "nathan" and resultat["approuve_le"] == HORODATAGE
    assert resultat["publication"].startswith("manuelle") and "jamais" in resultat["publication"]
    assert plateformes.VERIFICATION_AVANT_PUBLICATION in resultat["instructions"]
    assert "contact_client" not in resultat


def test_instagram_ne_met_pas_le_lien_dans_la_legende(charge, profil, nature):
    resultat = paquet.composer_paquet(_contenu(charge, profil, nature, "instagram"), charge, [], profil)
    assert resultat["lien_utm"] and resultat["lien_utm"] not in resultat["texte_a_copier"]
    assert any("bio" in etape for etape in resultat["instructions"])


def test_sans_heure_dans_le_profil_aucune_heure_n_est_inventee_et_le_manque_est_dit(charge, profil, nature):
    resultat = paquet.composer_paquet(_contenu(charge, profil, nature, "fiche_google"), charge, [], profil)
    assert resultat["heure_suggeree"] is None
    assert resultat["a_configurer"] == [
        "heures_publication.fiche_google dans le profil de marque : aucune heure suggérée"
    ]


@pytest.mark.parametrize("heure", ["25:00", "18h30", "6:30", "", None, 1830])
def test_une_heure_mal_formee_du_profil_n_est_pas_suggeree(heure, profil):
    profil["heures_publication"] = {"facebook": heure}
    assert paquet.heure_suggeree(profil, "facebook") is None
    profil["heures_publication"] = "18:30"
    assert paquet.heure_suggeree(profil, "facebook") is None


def test_tout_media_est_a_flouter_a_la_main_jamais_presente_comme_sur(charge, profil, nature):
    resultat = paquet.composer_paquet(_contenu(charge, profil, nature, "facebook"), charge, [], profil)
    assert [m["reference"] for m in resultat["medias"]] == ["photo-apres-1", "photo-apres-2"]
    for media in resultat["medias"]:
        assert media["statut"] == paquet.STATUT_MEDIA_A_FLOUTER == "a_flouter_a_la_main"
        assert "flouter à la main" in media["instruction"] and media["rapport_detecteur"] is None
    assert not any(mot in str(resultat["medias"]).casefold() for mot in ("sûr", "sécuritaire", "conforme"))


def test_le_rapport_du_detecteur_de_t4_3_est_joint_a_titre_d_information_avec_sa_reserve(charge, profil, nature):
    brouillon = {"wct_id": "wct-usine-1", "photos": [
        {"reference": "photo-apres-1", "revue_humaine_requise": False, "detections": [
            {"type": "visage", "confiance": 0.9, "floutee": True, "doute": False},
            {"type": "plaque", "confiance": 0.4, "floutee": True, "doute": True},
        ]},
    ]}
    autre_chantier = {"wct_id": "wct-autre", "photos": [
        {"reference": "photo-apres-2", "revue_humaine_requise": False, "detections": []},
    ]}
    resultat = paquet.composer_paquet(
        _contenu(charge, profil, nature, "facebook"), charge, [brouillon, autre_chantier], profil,
    )
    premier, second = resultat["medias"]
    assert premier["statut"] == "a_flouter_a_la_main"  # même avec un rapport : aucun fichier flouté n'existe
    assert premier["rapport_detecteur"]["zones_detectees"] == 2 and premier["rapport_detecteur"]["zones_floutees"] == 2
    assert "ne prouve pas" in premier["rapport_detecteur"]["reserve"]
    assert second["rapport_detecteur"] is None  # le rapport d'un autre chantier n'est jamais prêté à celui-ci


def test_la_demande_de_temoignage_est_privee_et_dit_si_on_peut_ecrire_au_client(
    charge, profil, nature, fabriquer_charge,
):
    consenti = fabriquer_charge(consentement_demande_avis=True)
    resultat = paquet.composer_paquet(_contenu(consenti, profil, nature, "demande_temoignage"), consenti, [], profil)
    assert resultat["public"] is False and resultat["medias"] == [] and resultat["heure_suggeree"] is None
    assert resultat["a_configurer"] == [] and resultat["lien_utm"] is None
    assert resultat["contact_client"]["autorise"] is True
    assert resultat["contact_client"]["consentement"]["recueilli_par"] == "etienne"
    assert plateformes.VERIFICATION_AVANT_PUBLICATION not in resultat["instructions"]

    non_consenti = paquet.composer_paquet(_contenu(charge, profil, nature, "demande_temoignage"), charge, [], profil)
    assert non_consenti["contact_client"]["autorise"] is False
    assert "ne lui envoie pas" in non_consenti["contact_client"]["detail"]


def test_le_contact_du_client_exige_aussi_la_preuve_de_son_consentement(fabriquer_charge):
    sans_preuve = fabriquer_charge(consentement_demande_avis=True)
    del sans_preuve["consentement_recueilli_le"]
    assert paquet.contact_client(sans_preuve)["autorise"] is False
    assert paquet.contact_client(fabriquer_charge(consentement_demande_avis=False))["autorise"] is False


def test_la_trace_d_export_est_deterministe_et_valide_l_horodatage(charge, profil, nature):
    contenu = _contenu(charge, profil, nature, "facebook")
    a, verdict = paquet.construire_export(contenu, "nathan", HORODATAGE)
    b, _ = paquet.construire_export(contenu, "agent", "2026-10-01T09:00:00-04:00")
    assert verdict is None and a["export_id"] == b["export_id"]
    assert (a["contenu_id"], a["exporte_par"], a["empreinte_texte"]) == (
        contenu["contenu_id"], "nathan", contenu["empreinte_texte"])
    rate, verdict = paquet.construire_export(contenu, "nathan", "bientôt")
    assert rate is None and verdict["code"] == verdicts.REJ_HORODATAGE_INVALIDE
