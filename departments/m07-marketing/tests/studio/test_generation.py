"""Génération de fonds : invite sans texte, doubles déterministes, graine rejouable, provenance append-only."""

from __future__ import annotations

import dataclasses

import fabriques_studio as f
import pytest
from m7_marketing import journal_chaine
from m7_marketing.studio import brief as b
from m7_marketing.studio import generation, png, provenance


def _brief(**plus):
    brief, refus = b.depuis_dict(f.brief(fond=f.GENERE, **plus))
    assert brief is not None, refus
    return brief


def _demande(**plus):
    base = {
        "job_id": "job-test",
        "brief_id": "brief-test",
        "brief_empreinte": "a" * 64,
        "genre": "image",
        "invite": "p",
        "invite_negative": "n",
        "largeur": 64,
        "hauteur": 48,
        "graine": 7,
    }
    return generation.DemandeGeneration(**{**base, **plus})


def test_l_invite_interdit_explicitement_texte_logo_et_signature_et_vient_de_champs_structures():
    invite, negative = generation.construire_invite(_brief())
    assert "no text" in invite and "no logo" in invite and "no signature" in invite
    assert "toiture de bardeaux gris" in invite and "#0B3C5D" in invite
    assert "logo" in negative and "watermark" in negative and "text" in negative
    assert "514" not in invite and "Horizon" not in invite  # ni nom de marque ni coordonnées dans l'invite


def test_un_brief_sans_fond_genere_n_a_pas_d_invite():
    brief, _ = b.depuis_dict(f.brief())
    with pytest.raises(generation.ErreurGeneration):
        generation.construire_invite(brief)


def test_dimensions_demandees_au_modele_sont_bornees():
    assert generation.dimensions_du_fond(1126, 676) == (1126, 676)
    largeur, hauteur = generation.dimensions_du_fond(10_000, 5_000)
    assert max(largeur, hauteur) == generation.DIMENSION_FOND_MAX and largeur == 2 * hauteur


def test_le_double_image_est_deterministe_et_la_graine_change_la_sortie():
    double = generation.GenerateurImageDouble()
    un, deux = double.generer(_demande()), double.generer(_demande())
    assert un.octets == deux.octets and un.nature == "double" and un.graine == 7
    autre = double.generer(_demande(graine=8))
    assert autre.octets != un.octets
    assert png.dimensions(un.octets) == (64, 48)
    assert double.generer(_demande(invite="autre")).octets != un.octets


@pytest.mark.parametrize("plus", [{"largeur": 8}, {"hauteur": 99999}, {"genre": "video"}])
def test_le_double_image_refuse_les_demandes_hors_bornes(plus):
    with pytest.raises(generation.ErreurGeneration):
        generation.GenerateurImageDouble().generer(_demande(**plus))


def test_le_double_video_produit_un_apng_valide():
    sortie = generation.GenerateurVideoDouble().generer(
        _demande(genre="video", duree_s=1, images_par_seconde=4, largeur=32, hauteur=24)
    )
    assert sortie.format == "apng" and sortie.nature == "double" and sortie.duree_s == 1
    assert sortie.octets.startswith(png.SIGNATURE) and b"acTL" in sortie.octets and sortie.octets.count(b"fcTL") == 4
    assert b"fdAT" in sortie.octets and png.dimensions(sortie.octets) == (32, 24)
    with pytest.raises(generation.ErreurGeneration):
        generation.GenerateurVideoDouble().generer(_demande(genre="video", largeur=32, hauteur=24))


def test_aucun_adaptateur_reel_n_est_livre():
    assert generation.ADAPTATEURS_DE_PRODUCTION == {}


def test_la_graine_par_defaut_est_deterministe_et_journalisable():
    assert generation.graine_par_defaut("a" * 64, "job-1") == generation.graine_par_defaut("a" * 64, "job-1")
    assert generation.graine_par_defaut("a" * 64, "job-1") != generation.graine_par_defaut("a" * 64, "job-2")
    assert 0 <= generation.graine_par_defaut("a" * 64, "job-1") < 2**32


# -- vérification de la sortie d'un adaptateur ---------------------------------------------------------------------
def _sortie(**plus):
    base = generation.GenerateurImageDouble().generer(_demande())
    return dataclasses.replace(base, **plus)


@pytest.mark.parametrize(
    "plus",
    [
        {"octets": b""},
        {"octets": b"pas un png"},
        {"graine": 99},
        {"nature": "inconnue"},
        {"modele": ""},
        {"version_modele": ""},
        {"format": "jpeg"},
        {"largeur": 65},
    ],
)
def test_une_sortie_d_adaptateur_mal_formee_est_refusee(plus):
    with pytest.raises(generation.ErreurGeneration) as erreur:
        generation.verifier_sortie(_sortie(**plus), _demande())
    assert erreur.value.code == generation.REJ_SORTIE


def test_une_sortie_valide_passe():
    generation.verifier_sortie(_sortie(), _demande())


# -- provenance ----------------------------------------------------------------------------------------------------
LICENCE = {"fournisseur_id": "image.double-deterministe.test", "decision": {"conforme": True, "refus": []}}


def test_la_provenance_consigne_modele_version_graine_invite_licence_et_empreintes():
    journal: list = []
    demande, sortie = _demande(), _sortie()
    maillon = provenance.enregistrer(
        journal, demande, sortie, LICENCE, "image.double-deterministe.test", "agent", f.HORODATAGE
    )
    assert maillon["modele"] == "double-deterministe" and maillon["version_modele"] == "1" and maillon["graine"] == 7
    assert maillon["invite"] == "p" and maillon["invite_negative"] == "n" and maillon["marquage_ia"] is True
    assert maillon["licence"] == LICENCE and maillon["nature_generateur"] == "double"
    assert maillon["sortie"]["sha256"] == __import__("hashlib").sha256(sortie.octets).hexdigest()
    assert maillon["demande_empreinte"] == demande.empreinte() and len(maillon["chaine"]) == 64
    assert provenance.trouver(journal, maillon["chaine"]) == maillon
    assert provenance.trouver_par_sortie(journal, maillon["sortie"]["sha256"]) == maillon
    assert provenance.trouver(journal, "0" * 64) is None


def test_la_chaine_de_provenance_se_verifie_et_toute_retouche_est_vue():
    journal: list = []
    for graine in (1, 2, 3):
        provenance.enregistrer(
            journal, _demande(graine=graine), _sortie(graine=graine), LICENCE, "x", "agent", f.HORODATAGE
        )
    assert journal_chaine.integre(journal)
    journal[1] = {**journal[1], "graine": 999}
    assert not journal_chaine.integre(journal)
    with pytest.raises(provenance.ProvenanceErreur) as erreur:
        provenance.enregistrer(journal, _demande(), _sortie(), LICENCE, "x", "agent", f.HORODATAGE)
    assert erreur.value.code == provenance.REJ_JOURNAL_ALTERE
    assert provenance.trouver(journal, journal[0]["chaine"]) is None  # journal altéré : rien n'est lu


def test_la_provenance_pour_la_composition_porte_la_graine_et_la_chaine():
    journal: list = []
    maillon = provenance.enregistrer(journal, _demande(), _sortie(), LICENCE, "x", "agent", f.HORODATAGE)
    assert provenance.vers_provenance_de_composition(maillon) == {
        "chaine": maillon["chaine"],
        "modele": "double-deterministe",
        "version_modele": "1",
        "graine": 7,
    }


def test_une_provenance_sans_graine_entiere_ou_sans_invite_est_refusee():
    journal: list = []
    with pytest.raises(provenance.ProvenanceErreur):
        provenance.enregistrer(journal, _demande(), _sortie(graine="7"), LICENCE, "x", "agent", f.HORODATAGE)
    with pytest.raises(provenance.ProvenanceErreur):
        provenance.enregistrer(journal, _demande(), _sortie(invite_effective=""), LICENCE, "x", "agent", f.HORODATAGE)
    assert journal == []
