"""Portes du sas social et du site : un média « composé » doit être un visuel approuvé ; aucun actif sous une autre
origine."""

from __future__ import annotations

import pytest
from m7_marketing.sas_social import modele
from m7_marketing.studio import portes as p

SHA = "a" * 64


def _info(**plus):
    base = {
        "actif_id": "visuel-1",
        "kind": p.KIND_VISUEL,
        "etat": "approuve",
        "format": "png",
        "octets": 5000,
        "largeur": 1080,
        "hauteur": 1350,
        "ia_generee": True,
        "realiste": True,
        "fictif": True,
        "approuve": True,
    }
    return p.InfoActif(**{**base, **plus})


def _media(**plus):
    base = {
        "reference": "visuel-1-png",
        "type_media": "image",
        "format": "png",
        "sha256": SHA,
        "octets": 5000,
        "largeur": 1080,
        "hauteur": 1350,
        "duree_s": None,
        "alt": "Alt",
        "origine": "composition_deterministe",
        "ia_generee": True,
        "realiste": True,
        "moderation": "verifiee",
        "controle_ocr": "conforme",
    }
    return {**base, **plus}


def _resolveur(info=None, integre=True):
    class R:
        def __init__(self):
            self.integre = integre

        def __call__(self, sha):
            return info if sha == SHA else None

    return R()


def _codes(refus):
    return [r["code"] for r in refus]


def test_un_visuel_approuve_aux_faits_exacts_passe():
    assert p.controler_media_sas(_media(), "$.medias[0]", _resolveur(_info())) == []


def test_un_media_compose_inconnu_du_studio_est_refuse():
    assert _codes(p.controler_media_sas(_media(), "$.medias[0]", _resolveur(None))) == [p.REJ_SOCIAL_ACTIF_INCONNU]


def test_un_media_qui_n_est_pas_du_studio_et_ne_pretend_pas_l_etre_passe():
    assert (
        p.controler_media_sas(_media(origine="photo_chantier", ia_generee=False, realiste=False), "$", _resolveur(None))
        == []
    )


@pytest.mark.parametrize("etat", ["compose", "controle_conforme", "controle_echec", "en_revue", "rejete", "revoque"])
def test_un_visuel_non_approuve_est_refuse_quel_que_soit_son_etat(etat):
    refus = p.controler_media_sas(_media(), "$", _resolveur(_info(etat=etat, approuve=False)))
    assert p.REJ_SOCIAL_ACTIF_NON_APPROUVE in _codes(refus) and etat in refus[0]["detail"]


@pytest.mark.parametrize("kind", [p.KIND_FOND, p.KIND_LOGO])
def test_un_fond_ou_un_logo_seul_ne_se_publie_jamais(kind):
    refus = p.controler_media_sas(_media(), "$", _resolveur(_info(kind=kind, approuve=True)))
    assert _codes(refus) == [p.REJ_SOCIAL_ACTIF_NON_APPROUVE] and "jamais" in refus[0]["detail"]


@pytest.mark.parametrize("origine", ["photo_chantier", "banque_licenciee", "genere_non_compose"])
def test_un_actif_du_studio_sous_une_autre_origine_est_refuse_pour_toute_origine(origine):
    """Laver une image générée en la déclarant photo ou banque d'images (et échapper à la divulgation d'IA)."""
    refus = p.controler_media_sas(_media(origine=origine), "$", _resolveur(_info()))
    assert _codes(refus) == [p.REJ_SOCIAL_ACTIF_ORIGINE]
    refus = p.controler_media_sas(
        _media(origine=origine, ia_generee=False), "$", _resolveur(_info(kind=p.KIND_FOND, approuve=False))
    )
    assert _codes(refus) == [p.REJ_SOCIAL_ACTIF_ORIGINE]


@pytest.mark.parametrize(("champ", "valeur"), [("format", "jpeg"), ("octets", 5001), ("largeur", 1081), ("hauteur", 1)])
def test_les_faits_du_media_sont_ceux_du_registre(champ, valeur):
    refus = p.controler_media_sas(_media(**{champ: valeur}), "$", _resolveur(_info()))
    assert _codes(refus) == [p.REJ_SOCIAL_ACTIF_INCOHERENT] and champ in refus[0]["detail"]


def test_la_part_d_ia_et_l_allure_realiste_viennent_du_registre_pas_de_l_agent():
    assert _codes(p.controler_media_sas(_media(ia_generee=False), "$", _resolveur(_info()))) == [p.REJ_SOCIAL_IA]
    refus = p.controler_media_sas(_media(realiste=False), "$", _resolveur(_info()))
    assert _codes(refus) == [p.REJ_SOCIAL_IA] and "realiste" in refus[0]["chemin"]
    assert _codes(
        p.controler_media_sas(_media(ia_generee=True), "$", _resolveur(_info(ia_generee=False, realiste=False)))
    ) == [p.REJ_SOCIAL_IA]


def test_registre_altere_tout_est_refuse_meme_une_photo():
    resolveur = _resolveur(None, integre=False)
    assert _codes(p.controler_media_sas(_media(), "$", resolveur)) == [p.REJ_SOCIAL_REGISTRE]
    assert _codes(p.controler_media_sas(_media(origine="photo_chantier"), "$", resolveur)) == [p.REJ_SOCIAL_REGISTRE]
    assert _codes(p.controler_image_site("hero", SHA, resolveur)) == [p.REJ_SITE_REGISTRE]


def test_un_resolveur_sans_attribut_integre_est_considere_integre():
    assert p.registre_integre(lambda sha: None) is True


# -- site ----------------------------------------------------------------------------------------------------------
def test_site_image_inconnue_passe_visuel_approuve_passe():
    assert p.controler_image_site("hero", SHA, _resolveur(None)) == []
    assert p.controler_image_site("hero", SHA, _resolveur(_info())) == []


def test_site_fond_brut_jamais_et_visuel_non_approuve_jamais():
    refus = p.controler_image_site("hero", SHA, _resolveur(_info(kind=p.KIND_FOND, approuve=False, etat="fond_brut")))
    assert _codes(refus) == [p.REJ_SITE_FOND_BRUT]
    refus = p.controler_image_site("hero", SHA, _resolveur(_info(approuve=False, etat="en_revue")))
    assert _codes(refus) == [p.REJ_SITE_NON_APPROUVE] and "en_revue" in refus[0]["detail"]


def test_les_champs_du_media_du_sas_sont_ceux_que_les_portes_lisent():
    """Garde de contrat : `controler_media_sas` lit les champs de `sas_social.modele.Media` ; un renommage casserait
    la porte."""
    champs = {c for c in modele.CHAMPS_MEDIA}
    assert {"sha256", "origine", "format", "octets", "largeur", "hauteur", "ia_generee", "realiste"} <= champs
