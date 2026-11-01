"""Chaque classe d'adaptateur DÉCLARE les limites du service ; le sas les respecte, et ne les connaît que par elle.

Pour chaque réseau et chaque limite : exactement à la limite -> accepté ; un cran au-delà -> refusé avec la règle
nommée.
Puis la preuve que le sas LIT la classe : une classe aux limites modifiées change ce que le sas accepte.
"""

from __future__ import annotations

import dataclasses

import pytest
from fabriques_sociales import MAINTENANT, TEXTE, media_photo, media_video, publication
from m7_marketing.sas_social import doubles, garde_fous, modele, politique, reseaux

FICTIF = True
TOUS = list(reseaux.RESEAUX)
PLAFOND_TEXTE_PUBLIC = 5000  # profil de texte public de M7 : aucun texte public au-delà, quel que soit le réseau


def _texte(longueur: int) -> str:
    brut = (TEXTE + " ") * (longueur // len(TEXTE) + 2)
    return brut[:longueur].rstrip() + "e" if brut[:longueur].endswith(" ") else brut[:longueur]


def _controle(declaration, donnees, pol=None):
    chargee, refus = modele.depuis_dict(donnees)
    assert chargee is not None, refus
    return [r["code"] for r in garde_fous.controler_contenu(chargee, declaration, pol or politique.PolitiqueSas())]


def _media_pour(limites, rang=0, **plus):
    if limites.formats_images:
        return media_photo(f"photo-{rang}", format_=sorted(limites.formats_images)[0], **plus)
    return media_video(f"video-{rang}", format_=sorted(limites.formats_videos)[0], **plus)


def _pub(reseau, declaration, **plus):
    base = publication(reseau)
    if reseau not in ("youtube", "tiktok", "instagram", "gbp"):
        base["medias"] = [_media_pour(declaration.LIMITES)]
    base.update(plus)
    return base


@pytest.mark.parametrize("reseau", TOUS)
def test_les_limites_viennent_de_la_classe_et_sont_marquees_a_verifier(declarations, reseau):
    classe = reseaux.DECLARATIONS[reseau]
    limites = classe.LIMITES
    assert limites.reseau == reseau and limites.a_verifier is True and limites.source.strip()
    assert doubles.DOUBLES[reseau].LIMITES is limites, "le double hérite des limites de la classe de déclaration"
    assert declarations[reseau].LIMITES is limites


@pytest.mark.parametrize("reseau", TOUS)
def test_le_texte_est_accepte_a_la_limite_et_refuse_un_caractere_plus_loin(declarations, reseau):
    declaration = declarations[reseau]
    limite = min(declaration.LIMITES.texte_max, PLAFOND_TEXTE_PUBLIC)
    assert _controle(declaration, _pub(reseau, declaration, texte=_texte(limite))) == []
    assert "REJ-LONGUEUR" in _controle(declaration, _pub(reseau, declaration, texte=_texte(limite + 1)))


def test_facebook_declare_63206_mais_le_profil_de_texte_public_de_m7_plafonne_a_5000(declarations):
    assert declarations["facebook"].LIMITES.texte_max == 63206
    assert "REJ-LONGUEUR" in _controle(
        declarations["facebook"], _pub("facebook", declarations["facebook"], texte=_texte(5001))
    )


@pytest.mark.parametrize("reseau", TOUS)
def test_le_nombre_de_medias_est_accepte_aux_deux_bornes_et_refuse_au_dela(declarations, reseau):
    declaration = declarations[reseau]
    limites = declaration.LIMITES
    for nombre in {limites.medias_min, limites.medias_max}:
        medias = [_media_pour(limites, i) for i in range(nombre)]
        assert "REJ-SOCIAL-MEDIAS-NOMBRE" not in _controle(declaration, _pub(reseau, declaration, medias=medias)), (
            nombre
        )
    trop = [_media_pour(limites, i) for i in range(limites.medias_max + 1)]
    assert "REJ-SOCIAL-MEDIAS-NOMBRE" in _controle(declaration, _pub(reseau, declaration, medias=trop))
    if limites.medias_min > 0:
        assert "REJ-SOCIAL-MEDIAS-NOMBRE" in _controle(declaration, _pub(reseau, declaration, medias=[]))


@pytest.mark.parametrize("reseau", TOUS)
def test_chaque_format_declare_est_accepte_et_un_format_voisin_est_refuse(declarations, reseau):
    declaration = declarations[reseau]
    limites = declaration.LIMITES
    for format_ in limites.formats_images:
        medias = [media_photo("p1", format_=format_)]
        assert "REJ-SOCIAL-MEDIA-FORMAT" not in _controle(declaration, _pub(reseau, declaration, medias=medias))
    for format_ in limites.formats_videos:
        medias = [media_video("v1", format_=format_)]
        assert "REJ-SOCIAL-MEDIA-FORMAT" not in _controle(declaration, _pub(reseau, declaration, medias=medias))
    refuses = {"image": ("bmp", limites.formats_images), "video": ("avi", limites.formats_videos)}
    if limites.formats_images:
        assert "REJ-SOCIAL-MEDIA-FORMAT" in _controle(
            declaration, _pub(reseau, declaration, medias=[media_photo("p1", format_="bmp")])
        )
    if limites.formats_videos:
        assert "REJ-SOCIAL-MEDIA-FORMAT" in _controle(
            declaration, _pub(reseau, declaration, medias=[media_video("v1", format_="avi")])
        )
    assert refuses


@pytest.mark.parametrize("reseau", TOUS)
def test_le_poids_et_la_duree_sont_acceptes_a_la_limite_et_refuses_un_cran_plus_loin(declarations, reseau):
    declaration = declarations[reseau]
    limites = declaration.LIMITES
    au_plus = _media_pour(limites, octets=limites.octets_max)
    assert "REJ-SOCIAL-MEDIA-TAILLE" not in _controle(declaration, _pub(reseau, declaration, medias=[au_plus]))
    trop = _media_pour(limites, octets=limites.octets_max + 1)
    assert "REJ-SOCIAL-MEDIA-TAILLE" in _controle(declaration, _pub(reseau, declaration, medias=[trop]))
    if limites.video_duree_max_s is not None and limites.formats_videos:
        pile = media_video("v1", format_=sorted(limites.formats_videos)[0], duree_s=limites.video_duree_max_s)
        assert "REJ-SOCIAL-MEDIA-DUREE" not in _controle(declaration, _pub(reseau, declaration, medias=[pile]))
        long = media_video("v1", format_=sorted(limites.formats_videos)[0], duree_s=limites.video_duree_max_s + 1)
        assert "REJ-SOCIAL-MEDIA-DUREE" in _controle(declaration, _pub(reseau, declaration, medias=[long]))


@pytest.mark.parametrize("reseau", TOUS)
def test_le_quota_de_la_classe_est_respecte_exactement(declarations, reseau):
    declaration = declarations[reseau]
    quota = declaration.LIMITES.quota_24h
    chargee = _pub(reseau, declaration)
    publication_ = modele.depuis_dict(chargee)[0]
    candidat = modele.instant(publication_.planifie_le)
    from datetime import timedelta

    existants = [candidat - timedelta(minutes=i + 1) for i in range(quota - 1)]
    pol = politique.PolitiqueSas()

    def avec(horaires):
        return [
            r["code"]
            for r in garde_fous.controler_planification(publication_, declaration.LIMITES, pol, MAINTENANT, horaires)
        ]

    assert "REJ-SOCIAL-QUOTA-24H" not in avec(existants)
    assert "REJ-SOCIAL-QUOTA-24H" in avec([candidat - timedelta(minutes=quota + 5), *existants])


def test_le_sas_suit_la_classe_une_classe_aux_limites_modifiees_change_ce_qu_il_accepte(declarations):
    base = declarations["facebook"]
    donnees = publication("facebook", texte=_texte(300), medias=[media_photo("p1"), media_photo("p2")])
    assert _controle(base, donnees) == []

    class FacebookStrict(reseaux.DeclarationFacebook):
        LIMITES = dataclasses.replace(
            reseaux.LIMITES_FACEBOOK,
            texte_max=200,
            medias_max=1,
            formats_images=frozenset({"png"}),
            quota_24h=1,
        )

    stricte = FacebookStrict()
    codes = _controle(stricte, donnees)
    assert "REJ-LONGUEUR" in codes and "REJ-SOCIAL-MEDIAS-NOMBRE" in codes and "REJ-SOCIAL-MEDIA-FORMAT" in codes
    chargee = modele.depuis_dict(donnees)[0]
    deux = [modele.instant("2026-01-06T14:00:00Z")]
    assert "REJ-SOCIAL-QUOTA-24H" in [
        r["code"]
        for r in garde_fous.controler_planification(
            chargee, stricte.LIMITES, politique.PolitiqueSas(), MAINTENANT, deux
        )
    ]
    assert "REJ-SOCIAL-QUOTA-24H" not in [
        r["code"]
        for r in garde_fous.controler_planification(chargee, base.LIMITES, politique.PolitiqueSas(), MAINTENANT, deux)
    ]


def test_la_soumission_complete_suit_aussi_la_classe_d_adaptateur(journal, comptes_actifs):
    from m7_marketing.sas_social import service

    class FacebookTresStrict(reseaux.DeclarationFacebook):
        LIMITES = dataclasses.replace(reseaux.LIMITES_FACEBOOK, texte_max=50)

    cree = service.composer(
        journal, publication("facebook"), "cle-limites-0123456789", comptes_actifs, "agent", "2026-01-05T15:00:00Z"
    )
    refus = service.soumettre(
        journal,
        cree["publication_id"],
        {"facebook": FacebookTresStrict()},
        politique.PolitiqueSas(),
        MAINTENANT,
        "2026-01-05T15:00:00Z",
    )
    assert refus["accepte"] is False and "REJ-LONGUEUR" in [r["code"] for r in refus["refus"]]
    ok = service.soumettre(
        journal,
        cree["publication_id"],
        {"facebook": reseaux.DeclarationFacebook()},
        politique.PolitiqueSas(),
        MAINTENANT,
        "2026-01-05T15:00:00Z",
    )
    assert ok["accepte"] is True


def test_un_reseau_dont_l_adaptateur_annonce_un_autre_reseau_est_refuse(journal, comptes_actifs):
    from m7_marketing.sas_social import service

    cree = service.composer(
        journal, publication("facebook"), "cle-limites-0123456789", comptes_actifs, "agent", "2026-01-05T15:00:00Z"
    )
    refus = service.soumettre(
        journal,
        cree["publication_id"],
        {"facebook": reseaux.DeclarationInstagram()},
        politique.PolitiqueSas(),
        MAINTENANT,
        "2026-01-05T15:00:00Z",
    )
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-ADAPTATEUR"
    assert (
        service.soumettre(
            journal, cree["publication_id"], {}, politique.PolitiqueSas(), MAINTENANT, "2026-01-05T15:00:00Z"
        )["refus"][0]["code"]
        == "REJ-SOCIAL-ADAPTATEUR"
    )


def test_les_options_exigees_par_tiktok_viennent_de_la_classe():
    assert reseaux.LIMITES_TIKTOK.options_requises == ("confidentialite", "commentaires", "duo", "stitch")
    assert all(not reseaux.LIMITES_PAR_RESEAU[r].options_requises for r in TOUS if r != "tiktok")
