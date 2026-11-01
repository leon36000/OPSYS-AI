"""Le brief créatif : validation stricte, éléments critiques typés, fond sans texte ni logo, empreinte stable."""

from __future__ import annotations

import copy

import fabriques_studio as f
import pytest
from m7_marketing.studio import brief as b


def _refus(donnees):
    brief, refus = b.depuis_dict(donnees)
    assert brief is None, "le brief aurait dû être refusé"
    return refus


def _codes(refus):
    return {r["code"] for r in refus}


def _chemins(refus):
    return {r["chemin"] for r in refus}


def test_un_brief_valide_est_accepte_et_son_empreinte_est_stable():
    brief, refus = b.depuis_dict(f.brief())
    assert refus == [] and brief is not None
    assert brief.empreinte() == b.depuis_dict(copy.deepcopy(f.brief()))[0].empreinte()
    autre = f.brief(objet="Un autre objet de campagne fictive")
    assert b.depuis_dict(autre)[0].empreinte() != brief.empreinte()


def test_les_quatre_gabarits_et_tous_leurs_formats_sont_valides():
    for gabarit, formats in b.GABARITS.items():
        for format_ in formats:
            assert b.depuis_dict(f.brief(gabarit, format_))[0] is not None, (gabarit, format_)


@pytest.mark.parametrize("champ", list(b.CHAMPS_BRIEF[:-2]))
def test_champ_requis_absent_refuse(champ):
    donnees = f.brief()
    del donnees[champ]
    assert f"$.{champ}" in _chemins(_refus(donnees))


def test_champ_inconnu_refuse_au_lieu_d_etre_ignore():
    donnees = f.brief()
    donnees["prix_calcule_par_le_modele"] = "99 $"
    assert b.REJ_CHAMP_INCONNU in _codes(_refus(donnees))


@pytest.mark.parametrize(
    ("chemin", "valeur"),
    [
        ("gabarit", "flyer"),
        ("format", "9x9"),
        ("canal", "tiktok"),
        ("fictif", "oui"),
        ("couleur", "pantone"),
        ("schema", "autre/v2"),
        ("ppp", 10),
        ("langues", ["en"]),
        ("langues", ["fr", "en", "es"]),
    ],
)
def test_valeurs_hors_liste_refusees(chemin, valeur):
    donnees = f.brief()
    donnees[chemin] = valeur
    assert _refus(donnees)


def test_format_incompatible_avec_le_gabarit():
    assert _refus(f.brief("carte_affaires", "11x17"))


def test_canal_incompatible_avec_le_gabarit():
    donnees = f.brief("affiche")
    donnees["canal"] = "instagram"
    assert "$.canal" in _chemins(_refus(donnees))


@pytest.mark.parametrize(
    ("type_", "valeur"),
    [
        ("telephone", "514 555 01"),
        ("telephone", "+1 450 555 014a"),
        ("telephone", "+1 050 555 0142"),
        ("telephone", "+1 450 555 0142 poste 3"),
        ("courriel", "Info@Horizon-Fictif.example"),
        ("courriel", "sans-arobase.example"),
        ("licence_rbq", "1234-5678-9"),
        ("licence_rbq", "12345678-90"),
        ("neq", "12345"),
        ("neq", "11678901234"),
        ("adresse", "123, rue des Érables, Laval"),
        ("site_web", "horizon fictif"),
        ("site_web", "horizon-fictif.example/page"),
        ("prix", "1250 $"),
        ("prix", "1 250.00 $"),
        ("prix", "mille dollars"),
    ],
)
def test_forme_invalide_d_un_element_critique_refusee(type_, valeur):
    donnees = f.brief()
    element = f.critiques(type_ if type_ != "prix" else "prix")[0]
    element["valeur"] = valeur
    donnees["elements_critiques"] = [element]
    assert b.REJ_CRITIQUE in _codes(_refus(donnees))


def test_brief_fictif_refuse_un_numero_reel_ou_un_domaine_reel():
    donnees = f.brief()
    donnees["elements_critiques"] = [{"type": "telephone", "valeur": "+1 514 555 0199", "source": "fiche fictive"}]
    assert b.depuis_dict(donnees)[0] is not None  # 555-01XX : plage fictive
    donnees["elements_critiques"] = [{"type": "telephone", "valeur": "+1 514 523 4567", "source": "fiche fictive"}]
    assert b.REJ_FICTIF in _codes(_refus(donnees))
    donnees["elements_critiques"] = [{"type": "courriel", "valeur": "info@exemple.com", "source": "fiche fictive"}]
    assert b.REJ_FICTIF in _codes(_refus(donnees))
    donnees["elements_critiques"] = [{"type": "site_web", "valeur": "exemple.com", "source": "fiche fictive"}]
    assert b.REJ_FICTIF in _codes(_refus(donnees))


def test_brief_non_fictif_accepte_un_numero_ordinaire():
    donnees = f.brief(fictif=False)
    donnees["elements_critiques"] = [
        {"type": "telephone", "valeur": "+1 514 523 4567", "source": "fiche de l'entreprise"}
    ]
    assert b.depuis_dict(donnees)[0] is not None


def test_prix_exige_une_date_de_validite_et_une_source():
    donnees = f.brief()
    element = f.critiques("prix")[0]
    del element["valide_jusqu_au"]
    donnees["elements_critiques"] = [element]
    assert _refus(donnees)
    element = f.critiques("prix")[0]
    element["valide_jusqu_au"] = "2027-02-30"
    donnees["elements_critiques"] = [element]
    assert _refus(donnees)
    element = f.critiques("prix")[0]
    element["source"] = ""
    donnees["elements_critiques"] = [element]
    assert _refus(donnees)


def test_element_critique_en_double_ou_trop_nombreux_ou_champ_en_trop():
    donnees = f.brief()
    donnees["elements_critiques"] = f.critiques("telephone", "telephone")
    assert _refus(donnees)
    donnees["elements_critiques"] = [{**f.critiques("telephone")[0], "libelle": "x"}]
    assert b.REJ_CHAMP_INCONNU in _codes(_refus(donnees))
    donnees["elements_critiques"] = [
        {"type": "telephone", "valeur": f"+1 450 555 01{i:02d}", "source": "fiche"} for i in range(13)
    ]
    assert _refus(donnees)


@pytest.mark.parametrize(
    "piege",
    [
        "‮SEUL",
        "zéro​largeur",
        "ligne\nbrisée",
        "tab\tulation",
        "nul\x00",
        "double  espace",
        " bordure",
        "bordure ",
        "é décomposé",
    ],
)
def test_caracteres_de_controle_bidi_ou_non_nfc_refuses_partout(piege):
    donnees = f.brief()
    donnees["textes"]["titre"]["fr"] = piege
    assert _refus(donnees)
    donnees = f.brief()
    donnees["mentions_obligatoires"] = [piege]
    assert _refus(donnees)
    donnees = f.brief()
    donnees["marque"]["nom"] = piege
    assert _refus(donnees)


def test_homographe_dans_une_donnee_critique_refuse():
    donnees = f.brief()
    donnees["elements_critiques"] = [{"type": "licence_rbq", "valeur": "1234-5678-9٠", "source": "registre"}]
    assert _refus(donnees)
    donnees["elements_critiques"] = [{"type": "telephone", "valeur": "+1 450 555 0142", "source": "fiche"}]
    assert _refus(donnees)


def test_francais_obligatoire_pour_chaque_role():
    donnees = f.brief()
    donnees["textes"]["titre"] = {"en": "Your roof, with confidence"}
    assert b.REJ_FRANCAIS in _codes(_refus(donnees))
    donnees = f.brief(langues=["fr", "en"])
    donnees["textes"]["titre"] = {"fr": "Votre toiture en confiance", "en": "Your roof, with confidence"}
    assert b.depuis_dict(donnees)[0] is not None
    donnees = f.brief()  # anglais présent mais langue non déclarée
    donnees["textes"]["titre"]["en"] = "Your roof"
    assert b.REJ_FRANCAIS in _codes(_refus(donnees))


def test_texte_libre_passe_le_garde_fou_de_texte_public():
    for texte in (
        "Appelez le 514 555 0100 maintenant",
        "Le meilleur couvreur du Québec",
        "Seulement 49,95 $ ce mois-ci",
        "Garantie à vie sur tout",
    ):
        donnees = f.brief()
        donnees["textes"]["titre"]["fr"] = texte
        refus = _refus(donnees)
        assert any(r["chemin"] == "$.textes.titre.fr" for r in refus), texte


def test_texte_libre_trop_long_refuse():
    donnees = f.brief()
    donnees["textes"]["titre"]["fr"] = "Mot " * 40
    assert _refus(donnees)


def test_la_marque_vient_du_profil_et_est_validee():
    donnees = f.brief()
    donnees["marque"]["couleurs"] = ["bleu"]
    assert _refus(donnees)
    donnees = f.brief()
    donnees["marque"]["empreinte_profil"] = "pas-un-hash"
    assert _refus(donnees)
    donnees = f.brief()
    donnees["marque"]["langue"] = "en"
    assert b.REJ_FRANCAIS in _codes(_refus(donnees))
    donnees = f.brief()
    del donnees["marque"]["nom"]
    assert _refus(donnees)


def test_fond_uni_ou_degrade_n_accepte_aucune_description():
    donnees = f.brief(fond={"mode": "uni", "sujet": "une toiture"})
    assert b.REJ_FOND in _codes(_refus(donnees))
    assert b.depuis_dict(f.brief(fond={"mode": "degrade"}))[0] is not None


@pytest.mark.parametrize(
    "sujet",
    [
        "une toiture avec le logo de l'entreprise",
        "un panneau avec un slogan accrocheur",
        "maison dans le style de Disney",
        "un camion avec le numéro de téléphone",
        "affiche portant le texte promotionnel",
        "fond avec watermark discret",
        "an illustration in the style of a famous painter",
        "un mot écrit sur le mur",
        "a house with phone numbers",
    ],
)
def test_un_fond_ne_demande_jamais_de_texte_de_logo_ou_de_marque(sujet):
    donnees = f.brief(fond={"mode": "genere", "sujet": sujet})
    assert b.REJ_FOND in _codes(_refus(donnees))


def test_fond_genere_valide_et_graine_bornee():
    fond = {
        "mode": "genere",
        "sujet": "toiture de bardeaux gris sous un ciel de printemps",
        "ambiance": "lumineuse",
        "rendu": "photographique",
        "graine": 42,
    }
    brief = b.depuis_dict(f.brief(fond=fond))[0]
    assert brief.genere and brief.fond["graine"] == 42
    for graine in (-1, 2**32, "42", True):
        assert _refus(f.brief(fond={**fond, "graine": graine}))
    assert _refus(f.brief(fond={**fond, "rendu": "dessin"}))
    assert _refus(f.brief(fond={"mode": "genere"}))


def test_l_empreinte_du_fond_ne_depend_que_du_fond_du_format_et_des_couleurs():
    fond = {"mode": "genere", "sujet": "toiture de bardeaux gris sous un ciel de printemps"}
    un = b.depuis_dict(f.brief(fond=fond))[0]
    deux = b.depuis_dict(f.brief(fond=fond, objet="Autre objet de campagne fictive"))[0]
    assert un.empreinte_fond() == deux.empreinte_fond() and un.empreinte() != deux.empreinte()
    trois = b.depuis_dict(f.brief(fond={**fond, "sujet": "toiture de tuiles rouges sous un ciel de printemps"}))[0]
    assert trois.empreinte_fond() != un.empreinte_fond()


def test_non_dict_refuse_sans_exception():
    for entree in (None, [], "x", 3):
        assert b.depuis_dict(entree)[0] is None
