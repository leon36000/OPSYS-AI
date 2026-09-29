"""Profil des équipes de l'entreprise (PLAN T4.12) : lu dans `entreprise.yaml`, jamais inventé, aucune donnée RH.

Fixture FICTIVE (`fictif: true`) : `tests/fixtures/equipes_fictives.json`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from opsys import equipes, etat, identite, stockage, taxonomie
from opsys.equipes import ProfilInvalide

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "equipes_fictives.json").read_text(encoding="utf-8"))


def profil_fictif() -> dict:
    assert FIXTURE["fictif"] is True
    return copy.deepcopy(FIXTURE["profil"])


def _ecrire_yaml(contenu: str) -> Path:
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(contenu, encoding="utf-8")
    return fichier


# ---------------------------------------------------------------------------
# Sans profil : un verdict qui dit quoi déclarer, jamais un repli
# ---------------------------------------------------------------------------
def test_sans_profil_aucune_equipe_n_est_inventee_et_le_verdict_dit_quoi_declarer(opsys_home):
    profil, verdict = equipes.charger_equipes()
    assert profil is None
    assert verdict["code"] == equipes.VERDICT_EQUIPES_NON_CONFIGUREES
    assert str(taxonomie.fichier_profil()) in verdict["detail"]
    assert "opsys-metier equipes declarer --depuis" in verdict["detail"] and "--par" in verdict["detail"]
    assert "jamais inventé" in verdict["detail"]
    assert equipes.lire_equipes() is None


def test_un_profil_de_services_sans_equipes_n_a_pas_d_equipes(opsys_home, declarer_services):
    declarer_services("gouttieres")
    taxonomie.enregistrer_zone_desservie(["Laval"])
    assert equipes.charger_equipes()[0] is None
    assert equipes.verifier_profil() == []  # l'absence n'est pas une erreur


def test_un_profil_vide_est_l_absence_pas_un_profil_valide(opsys_home):
    _ecrire_yaml("equipes: {}\n")
    assert equipes.charger_equipes()[1]["code"] == equipes.VERDICT_EQUIPES_NON_CONFIGUREES
    with pytest.raises(ProfilInvalide, match="vide"):
        equipes.enregistrer_equipes({})


# ---------------------------------------------------------------------------
# Déclaration, relecture, cohabitation avec les autres clés
# ---------------------------------------------------------------------------
def test_un_profil_declare_se_relit_a_l_identique_et_les_autres_cles_restent(opsys_home, declarer_services):
    declarer_services("gouttieres", "revetement")
    taxonomie.enregistrer_zone_desservie(["Laval"])
    taxonomie.enregistrer_fenetre_conversation(30)
    fichier = equipes.enregistrer_equipes(profil_fictif())
    assert fichier == taxonomie.fichier_profil()
    profil, verdict = equipes.charger_equipes()
    assert verdict is None and profil == profil_fictif()
    assert [s.code for s in taxonomie.lire_services()] == ["gouttieres", "revetement"]
    assert taxonomie.lire_zone_desservie() == ("Laval",) and taxonomie.lire_fenetre_conversation() == 30
    # Déclarer les autres clés ensuite n'écrase pas les équipes.
    taxonomie.enregistrer_services(["reparation"])
    taxonomie.enregistrer_zone_desservie(["Québec"])
    assert equipes.lire_equipes() == profil_fictif()
    assert yaml.safe_load(fichier.read_text(encoding="utf-8"))["equipes"] == profil_fictif()


def test_declarer_remplace_la_cle_entiere(opsys_home):
    equipes.enregistrer_equipes(profil_fictif())
    seule = {"fenetre_par_defaut": {"jours": [3], "debut_min": 0, "fin_min": 60}}
    equipes.enregistrer_equipes(seule)
    assert equipes.lire_equipes() == seule


def test_le_profil_est_canonique_quel_que_soit_l_ordre_de_la_declaration(opsys_home):
    brut = profil_fictif()
    brut["liste"].reverse()
    brut["liste"][0]["quarts"].reverse()
    brut["liste"][1]["membres"].reverse()
    brut["liste"][1]["competences"].reverse()
    brut["services"] = dict(reversed(list(brut["services"].items())))
    propre = equipes.normaliser_equipes(brut)
    assert propre == profil_fictif()
    assert list(propre["services"]) == ["gouttieres", "reparation", "revetement"]
    assert equipes.empreinte_equipes(propre) == equipes.empreinte_equipes(profil_fictif())


def test_l_empreinte_change_avec_le_moindre_champ(opsys_home):
    base = equipes.empreinte_equipes(profil_fictif())
    for chemin in (
        lambda p: p["liste"][0]["quarts"][0].update(fin_min=1019),
        lambda p: p["services"]["gouttieres"].update(duree_min=91),
        lambda p: p["cedule"].update(iterations=501),
        lambda p: p["liste"][1]["depot"].update(latitude_microdegres=45735001),
        lambda p: p["liste"][1]["membres"].append("dario.fictif"),
    ):
        modifie = profil_fictif()
        chemin(modifie)
        assert equipes.empreinte_equipes(equipes.normaliser_equipes(modifie)) != base


def test_les_quatre_sections_sont_facultatives_une_a_une():
    for cle, valeur in profil_fictif().items():
        assert equipes.normaliser_equipes({cle: valeur}) == {cle: valeur}


# ---------------------------------------------------------------------------
# Refus : la raison, jamais une correction silencieuse
# ---------------------------------------------------------------------------
def _sans(chemin_cles):
    def transformer(profil):
        cible = profil
        for cle in chemin_cles[:-1]:
            cible = cible[cle]
        del cible[chemin_cles[-1]]
    return transformer


def _remplacer(chemin_cles, valeur):
    def transformer(profil):
        cible = profil
        for cle in chemin_cles[:-1]:
            cible = cible[cle]
        cible[chemin_cles[-1]] = valeur
    return transformer


REFUS = [
    ("racine liste", None, "objet"),
    ("clé inconnue à la racine", _remplacer(["notes"], {}), "clés inconnues"),
    ("liste vide", _remplacer(["liste"], []), "vide"),
    ("liste en objet", _remplacer(["liste"], {"id": "x"}), "liste"),
    ("équipe sans membre", _remplacer(["liste", 0, "membres"], []), "vide"),
    ("membre mal formé", _remplacer(["liste", 0, "membres"], ["Alice Tremblay"]), "personne OPSYS"),
    ("membre en double", _remplacer(["liste", 0, "membres"], ["alice.fictif", "alice.fictif"]), "double"),
    ("équipe sans dépôt", _sans(["liste", 0, "depot"]), "clés manquantes"),
    ("équipe sans quart", _remplacer(["liste", 0, "quarts"], []), "vide"),
    ("équipe sans compétences déclarées", _sans(["liste", 0, "competences"]), "clés manquantes"),
    ("id d'équipe mal formé", _remplacer(["liste", 0, "id"], "Équipe Nord"), "identifiant d'équipe"),
    ("compétence mal formée", _remplacer(["liste", 0, "competences"], ["Gouttières"]), "compétence est un code"),
    ("quart : début après la fin", _remplacer(["liste", 0, "quarts", 0, "debut_min"], 1020), "précéder"),
    ("quart : fin après minuit", _remplacer(["liste", 0, "quarts", 0, "fin_min"], 1441), "entre 1 et 1440"),
    ("quart : jour négatif", _remplacer(["liste", 0, "quarts", 0, "jour"], -1), "entre 0 et 9999"),
    ("quart : jour décimal", _remplacer(["liste", 0, "quarts", 0, "jour"], 0.5), "entier"),
    ("quart : jour booléen", _remplacer(["liste", 0, "quarts", 0, "jour"], True), "entier"),
    ("quart : deux fois le même jour", _remplacer(["liste", 0, "quarts", 1, "jour"], 0), "deux quarts le jour 0"),
    ("latitude hors du globe", _remplacer(["liste", 0, "depot", "latitude_microdegres"], 91_000_000), "entre"),
    ("latitude en texte", _remplacer(["liste", 0, "depot", "latitude_microdegres"], "46.015"), "entier"),
    ("équipe déclarée deux fois", lambda p: p["liste"].append(copy.deepcopy(p["liste"][0])), "en double"),
    ("services : durée nulle", _remplacer(["services", "gouttieres", "duree_min"], 0), "entre 1 et 1440"),
    ("services : durée de plus d'une journée", _remplacer(["services", "gouttieres", "duree_min"], 1441), "entre"),
    ("services : durée en texte", _remplacer(["services", "gouttieres", "duree_min"], "90"), "entier"),
    ("services : sans compétences déclarées", _sans(["services", "gouttieres", "competences"]), "clés manquantes"),
    ("services : code de service mal formé",
     _remplacer(["services"], {"Gouttières": {"duree_min": 60, "competences": []}}), "code de service"),
    ("services vide", _remplacer(["services"], {}), "vide"),
    ("cédule : un réglage manque", _sans(["cedule", "iterations"]), "clés manquantes"),
    ("cédule : réglage en texte", _remplacer(["cedule", "vitesse_moyenne_kmh"], "50"), "entier"),
    ("cédule : réglage décimal", _remplacer(["cedule", "vitesse_moyenne_kmh"], 50.5), "entier"),
    ("cédule : vitesse nulle", _remplacer(["cedule", "vitesse_moyenne_kmh"], 0), "au moins 1"),
    ("cédule : marge négative", _remplacer(["cedule", "marge_par_trajet_secondes"], -1), "au moins 0"),
    ("cédule : graine trop grande", _remplacer(["cedule", "graine"], 2**32), "entre"),
    ("cédule : réglage inconnu", _remplacer(["cedule", "cout_par_kilometre"], 1), "clés inconnues"),
    ("fenêtre : aucun jour", _remplacer(["fenetre_par_defaut", "jours"], []), "vide"),
    ("fenêtre : jour en double", _remplacer(["fenetre_par_defaut", "jours"], [1, 1]), "double"),
    ("fenêtre : début après la fin", _remplacer(["fenetre_par_defaut", "debut_min"], 1020), "précéder"),
]


@pytest.mark.parametrize(("nom", "transformer", "motif"), REFUS, ids=[r[0] for r in REFUS])
def test_une_declaration_invalide_est_refusee_avec_la_raison(nom, transformer, motif):
    if transformer is None:
        brut = ["liste"]
    else:
        brut = profil_fictif()
        transformer(brut)
    with pytest.raises(ProfilInvalide, match=motif):
        equipes.normaliser_equipes(brut)


@pytest.mark.parametrize("cle_rh", ["salaire", "taux_horaire", "sante", "evaluation", "note", "score", "performance",
                                    "date_naissance", "nas", "sanctions", "certifications"])
def test_aucune_donnee_rh_ni_evaluation_n_entre_dans_une_equipe(cle_rh):
    """Garde-fou humain (DEFINITION-PRODUIT M4) : le schéma est FERMÉ, une clé de RH, de santé ou d'évaluation est
    refusée à l'équipe comme au service, jamais ignorée en silence."""
    brut = profil_fictif()
    brut["liste"][0][cle_rh] = 1
    with pytest.raises(ProfilInvalide, match=f"clés inconnues.*{cle_rh}"):
        equipes.normaliser_equipes(brut)
    brut = profil_fictif()
    brut["services"]["gouttieres"][cle_rh] = 1
    with pytest.raises(ProfilInvalide, match="clés inconnues"):
        equipes.normaliser_equipes(brut)


def test_une_personne_ne_peut_etre_membre_de_deux_equipes():
    brut = profil_fictif()
    brut["liste"][1]["membres"].append("alice.fictif")
    with pytest.raises(ProfilInvalide, match="membre de deux équipes"):
        equipes.normaliser_equipes(brut)


def test_l_identifiant_d_une_equipe_ne_peut_etre_celui_d_un_membre_d_une_autre():
    """L'accès d'un employé se décide sur le technicien assigné : une équipe qui porterait l'identifiant de la
    personne d'une autre équipe la ferait voir les chantiers qui ne sont pas les siens."""
    brut = profil_fictif()
    brut["liste"][1]["id"] = "alice.fictif"
    with pytest.raises(ProfilInvalide, match="celui d'une personne qui est membre de l'équipe 'equipe-nord'"):
        equipes.normaliser_equipes(brut)


def test_une_equipe_d_une_personne_peut_porter_l_identifiant_de_cette_personne():
    brut = profil_fictif()
    brut["liste"][1]["id"] = "chloe.fictif"
    assert equipes.normaliser_equipes(brut)["liste"][0]["id"] == "chloe.fictif"


def test_un_meme_depot_doit_avoir_une_seule_position():
    brut = profil_fictif()
    brut["liste"][1]["depot"] = {"id": "depot-nord", "latitude_microdegres": 1, "longitude_microdegres": 2}
    with pytest.raises(ProfilInvalide, match="deux positions différentes"):
        equipes.normaliser_equipes(brut)


def test_deux_equipes_peuvent_partir_du_meme_depot():
    brut = profil_fictif()
    brut["liste"][1]["depot"] = copy.deepcopy(brut["liste"][0]["depot"])
    assert equipes.normaliser_equipes(brut)["liste"][0]["depot"]["id"] == "depot-nord"


# ---------------------------------------------------------------------------
# Un profil cassé n'est jamais lu comme absent
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contenu", [
    "equipes: []\n",
    "equipes: liste\n",
    "equipes:\n  liste: []\n",
    "equipes:\n  liste: [{id: eq-a}]\n",
    "equipes:\n  salaire: 1\n",
    "equipes: {liste: [\n",
])
def test_un_profil_mal_forme_est_refuse_jamais_lu_comme_absent(opsys_home, contenu):
    _ecrire_yaml(contenu)
    with pytest.raises(ProfilInvalide):
        equipes.lire_equipes()
    profil, verdict = equipes.charger_equipes()
    assert profil is None
    assert verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE, "distinct de l'absence"
    assert equipes.verifier_profil() != []


def test_enregistrer_un_profil_invalide_ne_touche_pas_au_fichier(opsys_home, declarer_services):
    declarer_services("gouttieres")
    equipes.enregistrer_equipes(profil_fictif())
    avant = taxonomie.fichier_profil().read_text(encoding="utf-8")
    invalide = profil_fictif()
    invalide["liste"][0]["salaire"] = 1
    for brut in (invalide, {}, None, "eq-a", []):
        with pytest.raises(ProfilInvalide):
            equipes.enregistrer_equipes(brut)
    assert taxonomie.fichier_profil().read_text(encoding="utf-8") == avant


# ---------------------------------------------------------------------------
# Écriture signée au journal d'audit
# ---------------------------------------------------------------------------
def test_la_declaration_signee_ecrit_au_journal_sans_nommer_les_membres(opsys_home):
    stockage.migrer()
    equipes.enregistrer_equipes(profil_fictif(), par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    assert journal[0]["par"] == "nathan" and journal[0]["action"] == "entreprise.equipes"
    details = journal[0]["details"]
    assert details["equipes"] == ["equipe-nord", "equipe-sud"]
    assert details["membres_par_equipe"] == {"equipe-nord": 2, "equipe-sud": 1}
    assert details["services"] == ["gouttieres", "reparation", "revetement"]
    assert details["cedule_declaree"] is True
    assert details["empreinte"] == equipes.empreinte_equipes(profil_fictif())
    assert "fictif" not in json.dumps(details), "le journal ne nomme aucun membre"


def test_sans_signature_rien_n_est_journalise(opsys_home):
    stockage.migrer()
    equipes.enregistrer_equipes(profil_fictif())
    with etat.session() as cnx:
        assert etat.lire_journal(cnx) == []


# ---------------------------------------------------------------------------
# Ce que le profil dit : équipes d'une personne, ce qui reste à déclarer
# ---------------------------------------------------------------------------
def test_equipes_de_lit_le_profil_et_ne_devine_rien():
    profil = equipes.normaliser_equipes(profil_fictif())
    assert equipes.equipes_de(profil, "alice.fictif") == ("equipe-nord",)
    assert equipes.equipes_de(profil, "chloe.fictif") == ("equipe-sud",)
    assert equipes.equipes_de(profil, "inconnu.fictif") == ()
    assert equipes.equipes_de(None, "alice.fictif") == ()
    assert equipes.equipes_de({"services": profil["services"]}, "alice.fictif") == ()


def test_a_declarer_dit_ce_qui_manque_et_rien_de_plus():
    assert len(equipes.a_declarer(None, ["gouttieres"])) == 1
    complet = equipes.normaliser_equipes(profil_fictif())
    assert equipes.a_declarer(complet, ["gouttieres", "revetement", "reparation"]) == []
    # la fenêtre par défaut est facultative
    sans_fenetre = {k: v for k, v in complet.items() if k != "fenetre_par_defaut"}
    assert equipes.a_declarer(sans_fenetre, ["gouttieres"]) == []
    manques = equipes.a_declarer({"fenetre_par_defaut": complet["fenetre_par_defaut"]}, ["gouttieres"])
    assert len(manques) == 3
    assert any("les équipes" in m for m in manques) and any("par service" in m for m in manques)
    assert any("réglages de la cédule" in m and "iterations" in m for m in manques)
    un_seul_service = {"gouttieres": complet["services"]["gouttieres"]}
    par_service = equipes.a_declarer(
        {"liste": complet["liste"], "cedule": complet["cedule"], "services": un_seul_service},
        ["gouttieres", "revetement"],
    )
    assert len(par_service) == 1 and "'revetement'" in par_service[0]


# ---------------------------------------------------------------------------
# `opsys-metier verifier` : les services du profil des équipes sont des services déclarés
# ---------------------------------------------------------------------------
def test_verifier_signale_une_duree_pour_un_service_non_declare(opsys_home, declarer_services):
    declarer_services("gouttieres", "revetement")
    equipes.enregistrer_equipes(profil_fictif())  # 'reparation' n'est pas un service déclaré ici
    problemes = equipes.verifier_profil()
    assert len(problemes) == 1 and "'reparation'" in problemes[0] and "gouttieres, revetement" in problemes[0]
    declarer_services()
    assert equipes.verifier_profil() == []


def test_verifier_ne_dit_rien_sans_service_declare(opsys_home):
    equipes.enregistrer_equipes(profil_fictif())
    assert equipes.verifier_profil() == []  # `taxonomie.verifier_profil` ne l'exige pas non plus


# ---------------------------------------------------------------------------
# Personnes OPSYS : les membres existent, l'identifiant d'équipe n'est pas celui d'un tiers
# ---------------------------------------------------------------------------
@pytest.fixture
def personnes(session):
    with session() as cnx:
        for identifiant in ("alice.fictif", "bruno.fictif", "chloe.fictif"):
            identite.creer_personne(cnx, identifiant, identifiant.title(), "mot-de-passe-fictif-1234", ["employee"])
        yield cnx


def test_les_membres_existants_et_actifs_passent(personnes):
    assert equipes.verifier_personnes(equipes.normaliser_equipes(profil_fictif()), personnes) == []


def test_un_membre_inconnu_est_refuse(personnes):
    brut = profil_fictif()
    brut["liste"][1]["membres"].append("fantome.fictif")
    problemes = equipes.verifier_personnes(equipes.normaliser_equipes(brut), personnes)
    assert problemes == ["équipe 'equipe-sud' : personne inconnue 'fantome.fictif' (opsys-metier personnes creer)"]


def test_un_membre_desactive_est_refuse(personnes):
    identite.activer(personnes, "bruno.fictif", False)
    problemes = equipes.verifier_personnes(equipes.normaliser_equipes(profil_fictif()), personnes)
    assert problemes == ["équipe 'equipe-nord' : la personne 'bruno.fictif' est désactivée"]


def test_l_identifiant_d_equipe_d_une_personne_qui_n_en_est_pas_membre_est_refuse(personnes):
    brut = profil_fictif()
    brut["liste"][1]["id"] = "bruno.fictif"  # bruno est membre d'equipe-nord : refusé dès la normalisation
    with pytest.raises(ProfilInvalide):
        equipes.normaliser_equipes(brut)
    with personnes.begin_nested():
        identite.creer_personne(personnes, "diane.fictif", "Diane", "mot-de-passe-fictif-1234", ["employee"])
    brut = profil_fictif()
    brut["liste"][1]["id"] = "diane.fictif"  # existe en base, n'est membre d'aucune équipe
    problemes = equipes.verifier_personnes(equipes.normaliser_equipes(brut), personnes)
    assert len(problemes) == 1 and "'diane.fictif'" in problemes[0] and "n'en est pas membre" in problemes[0]
    brut["liste"][1]["membres"] = ["chloe.fictif", "diane.fictif"]
    assert equipes.verifier_personnes(equipes.normaliser_equipes(brut), personnes) == []


# ---------------------------------------------------------------------------
# La fixture d'équipes est fictive, et ne dérive pas du schéma
# ---------------------------------------------------------------------------
def test_la_fixture_est_marquee_fictive_et_respecte_le_schema():
    assert FIXTURE["fictif"] is True and "FICTIVES" in FIXTURE["avertissement"]
    assert equipes.normaliser_equipes(FIXTURE["profil"]) == FIXTURE["profil"]
