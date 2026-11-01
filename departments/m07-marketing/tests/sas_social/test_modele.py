"""Le modèle d'une publication : validation stricte (fail-closed) et empreinte qui lie TOUT ce qui est approuvé."""

from __future__ import annotations

import copy

import pytest
from fabriques_sociales import annonce, media_photo, media_video, publication
from m7_marketing.sas_social import modele

FICTIF = True


def _publication(donnees):
    resultat, refus = modele.depuis_dict(donnees)
    assert refus == [], refus
    return resultat


def test_une_publication_valide_se_charge_et_se_rejoue_a_l_identique():
    donnees = publication("facebook")
    chargee = _publication(donnees)
    assert modele.en_dict(chargee) == donnees
    assert modele.empreinte(chargee) == modele.empreinte(_publication(copy.deepcopy(donnees)))
    assert len(modele.empreinte(chargee)) == 64


@pytest.mark.parametrize("reseau", ["gbp", "facebook", "instagram", "linkedin", "youtube", "tiktok"])
def test_chaque_reseau_a_une_publication_de_base_valide(reseau):
    assert _publication(publication(reseau)).reseau == reseau


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("reseau", "myspace"),
        ("compte", "A B"),
        ("compte", ""),
        ("texte", 5),
        ("titre", 5),
        ("planifie_le", "demain"),
        ("planifie_le", "2026-01-06T15:00:00"),
        ("planifie_le", "2026-01-06T15:00:00+00:00"),
        ("planifie_le", "2026-13-06T15:00:00Z"),
        ("type_publication", "gratuit"),
        ("options", []),
        ("medias", "photo"),
        ("divulgation", {"texte_ia": True}),
        ("divulgation", {"texte_ia": "oui", "media_synthetique_realiste": False, "contenu_commercial": False}),
        ("budget", {"montant_cents": 1}),
        ("budget", {"montant_cents": 1.5, "plafond_quotidien_cents": 1, "duree_jours": 1}),
        ("budget", {"montant_cents": 0, "plafond_quotidien_cents": 1, "duree_jours": 1}),
        ("budget", {"montant_cents": True, "plafond_quotidien_cents": 1, "duree_jours": 1}),
        ("budget", 12),
    ],
)
def test_une_valeur_invalide_est_refusee_jamais_corrigee(champ, valeur):
    donnees = publication("facebook")
    donnees[champ] = valeur
    resultat, refus = modele.depuis_dict(donnees)
    assert resultat is None and refus
    assert all({"code", "chemin", "detail"} == set(r) for r in refus)


def test_un_champ_inconnu_ou_manquant_est_refuse_avec_son_chemin():
    donnees = publication("facebook")
    donnees["pirate"] = 1
    del donnees["texte"]
    _, refus = modele.depuis_dict(donnees)
    assert {(r["code"], r["chemin"]) for r in refus} == {
        ("REJ-SOCIAL-CHAMP-INCONNU", "$.pirate"),
        ("REJ-SOCIAL-CHAMP", "$.texte"),
    }
    _, refus = modele.depuis_dict("pas un objet")
    assert refus[0]["code"] == "REJ-SOCIAL-CHAMP"


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("reference", "Majuscules"),
        ("reference", ""),
        ("sha256", "g" * 64),
        ("sha256", "a" * 63),
        ("format", "JPEG"),
        ("type_media", "audio"),
        ("origine", "inconnue"),
        ("moderation", "ok"),
        ("controle_ocr", "peut-etre"),
        ("octets", 0),
        ("largeur", -1),
        ("hauteur", 1.5),
        ("ia_generee", "non"),
        ("alt", "x" * 301),
        ("alt", "  "),
        ("duree_s", 30),
    ],
)
def test_un_media_invalide_est_refuse(champ, valeur):
    donnees = publication("facebook")
    donnees["medias"] = [media_photo(**{champ: valeur})]
    resultat, refus = modele.depuis_dict(donnees)
    assert resultat is None and refus and refus[0]["chemin"].startswith("$.medias[0]")


def test_une_video_exige_sa_duree_et_un_texte_alternatif_est_facultatif():
    donnees = publication("youtube")
    donnees["medias"] = [media_video(duree_s=None)]
    assert modele.depuis_dict(donnees)[0] is None
    donnees["medias"] = [media_video(alt="")]
    assert modele.depuis_dict(donnees)[0] is not None


def test_un_media_ne_peut_pas_avoir_un_champ_de_plus():
    donnees = publication("facebook")
    donnees["medias"] = [{**media_photo(), "chemin_disque": "/etc/passwd"}]
    _, refus = modele.depuis_dict(donnees)
    assert refus[0]["code"] == "REJ-SOCIAL-CHAMP-INCONNU" and refus[0]["chemin"].endswith("chemin_disque")


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("texte", TEXTE_AUTRE := "Un autre texte de publication, sobre."),
        ("compte", "autre-page"),
        ("reseau", "linkedin"),
        ("planifie_le", "2026-01-06T16:00:00Z"),
        ("type_publication", "annonce_payante"),
        ("titre", "Un titre"),
        ("options", {"x": 1}),
        ("divulgation", {"texte_ia": False, "media_synthetique_realiste": False, "contenu_commercial": False}),
        ("divulgation", {"texte_ia": True, "media_synthetique_realiste": True, "contenu_commercial": False}),
        ("divulgation", {"texte_ia": True, "media_synthetique_realiste": False, "contenu_commercial": True}),
        ("budget", {"montant_cents": 100, "plafond_quotidien_cents": 100, "duree_jours": 1}),
        ("medias", []),
        ("medias", [media_photo(), media_photo("photo-2")]),
        ("medias", [media_photo(sha256="c" * 64)]),
        ("medias", [media_photo(alt="Un autre texte alternatif")]),
        ("medias", [media_photo(moderation="revue_requise")]),
        ("medias", [media_photo(origine="banque_licenciee")]),
        ("medias", [media_photo(ia_generee=True)]),
        ("medias", [media_photo(reference="photo-chantier-002")]),
        ("medias", [media_photo(format_="png")]),
    ],
)
def test_chaque_champ_approuve_change_l_empreinte(champ, valeur):
    base = publication("facebook")
    autre = {**base, champ: valeur}
    chargee, refus = modele.depuis_dict(autre)
    assert chargee is not None, refus
    assert modele.empreinte(chargee) != modele.empreinte(_publication(base))


def test_l_ordre_des_cles_ne_change_pas_l_empreinte_mais_l_ordre_des_medias_oui():
    base = publication("facebook", medias=[media_photo("photo-1"), media_photo("photo-2")])
    inverse = {cle: base[cle] for cle in reversed(list(base))}
    assert modele.empreinte(_publication(inverse)) == modele.empreinte(_publication(base))
    permute = {**base, "medias": list(reversed(base["medias"]))}
    assert modele.empreinte(_publication(permute)) != modele.empreinte(_publication(base))


def test_l_empreinte_ne_depend_ni_de_la_cle_d_idempotence_ni_de_l_heure_de_creation():
    # la clé n'est pas un champ du modèle : elle identifie la publication, pas son contenu
    assert "cle_idempotence" not in modele.CHAMPS_PUBLICATION


def test_la_divulgation_realiste_est_calculee_des_medias_jamais_crue():
    sans = _publication(publication("facebook"))
    assert modele.media_synthetique_realiste(sans) is False
    avec = _publication(
        publication(
            "facebook",
            medias=[
                media_photo(origine="composition_deterministe", ia_generee=True, realiste=True, controle_ocr="conforme")
            ],
        )
    )
    assert modele.media_synthetique_realiste(avec) is True
    stylise = _publication(
        publication(
            "facebook",
            medias=[
                media_photo(
                    origine="composition_deterministe", ia_generee=True, realiste=False, controle_ocr="conforme"
                )
            ],
        )
    )
    assert modele.media_synthetique_realiste(stylise) is False


def test_les_instants_sont_stricts():
    assert modele.instant("2026-01-06T15:00:00Z").hour == 15
    for mauvais in ("2026-01-06 15:00:00Z", "2026-01-06T15:00:00z", "2026-01-06T15:00:00Z\n", "", None, 5):
        with pytest.raises(ValueError):
            modele.instant(mauvais)


def test_une_annonce_porte_son_budget_dans_l_empreinte():
    a = _publication(annonce("facebook"))
    b = _publication(annonce("facebook"))
    assert modele.empreinte(a) == modele.empreinte(b)
    donnees = annonce("facebook")
    donnees["budget"]["montant_cents"] += 1
    assert modele.empreinte(_publication(donnees)) != modele.empreinte(a)
