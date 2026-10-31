"""Profil des équipes : semaine type, congés d'équipe, fériés déclarés et durée d'un jour-personne
(DECISIONS-ARCHITECTE-r1 §3). Données FICTIVES (`tests/fixtures/equipes_fictives.json` et ce fichier).

Rétrocompatibilité d'abord : un profil qui ne porte aucun de ces champs se normalise, s'empreinte, s'écrit et se
journalise exactement comme avant (les valeurs attendues sont épinglées ici, pas recalculées par le code testé).
"""

from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path

import pytest
import yaml

from opsys import equipes, etat, stockage
from opsys.equipes import ProfilInvalide

RACINE = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "equipes_fictives.json").read_text(encoding="utf-8"))
GABARIT = RACINE / "docs" / "architecture" / "gabarit-profil-equipes.yaml"
# Empreinte du profil fictif SANS les nouveaux champs, calculée avec `opsys/equipes.py` de la base 7a3d784.
EMPREINTE_FICTIF_BASE = "99571f496f68c102ff60b0729b8eeb23fe53c07d682587dd64c1bb07c9f027c8"


def profil_fictif() -> dict:
    assert FIXTURE["fictif"] is True
    return copy.deepcopy(FIXTURE["profil"])


def _semaine(**jours):
    return {"fuseau": "America/Montreal", **jours}


def _avec_capacite() -> dict:
    profil = profil_fictif()
    profil["liste"][0]["semaine_type"] = _semaine(
        lundi=[{"debut": "12:30", "fin": "15:30"}, {"debut": "07:00", "fin": "12:00"}],
        mardi=[{"debut": "07:00", "fin": "15:30"}], samedi=[], dimanche=[],
    )
    profil["conges"] = [
        {"equipes": ["equipe-sud", "equipe-nord"], "du": "2030-07-22", "au": "2030-08-02", "motif": "conge",
         "libelle": "Vacances fictives"},
        {"equipes": ["equipe-nord"], "du": datetime.date(2030, 6, 5), "au": "2030-06-05", "motif": "formation"},
    ]
    profil["feries"] = {"annees": [2031, 2030], "jours": [{"date": "2030-06-24", "libelle": "Férié fictif"}]}
    profil["duree_jour_personne_minutes"] = 480
    return profil


# ---------------------------------------------------------------------------
# 1. Rétrocompatibilité : profil sans les nouveaux champs
# ---------------------------------------------------------------------------
def test_un_profil_sans_les_nouveaux_champs_garde_sa_forme_et_son_empreinte():
    propre = equipes.normaliser_equipes(profil_fictif())
    assert propre == profil_fictif()  # rien n'est ajouté (aucune clé vide ni défaut)
    assert set(propre) == {"liste", "services", "cedule", "fenetre_par_defaut"}
    assert all("semaine_type" not in equipe for equipe in propre["liste"])
    assert equipes.empreinte_equipes(propre) == EMPREINTE_FICTIF_BASE


def test_le_journal_d_un_profil_d_avant_est_identique(opsys_home):
    stockage.migrer()
    equipes.enregistrer_equipes(profil_fictif(), par="nathan")
    with etat.session() as cnx:
        details = etat.lire_journal(cnx)[0]["details"]
    assert set(details) == {"equipes", "membres_par_equipe", "services", "cedule_declaree", "empreinte"}


def test_les_messages_de_consigne_ne_changent_pas():
    assert equipes.CLES_PROFIL == ("liste", "services", "cedule", "fenetre_par_defaut")
    assert equipes.a_declarer(None) == [
        "le profil des équipes : liste, services, cedule, fenetre_par_defaut (`opsys-metier equipes declarer`)"]


# ---------------------------------------------------------------------------
# 2. Le profil complet se normalise, se relit et s'écrit sans rien perdre
# ---------------------------------------------------------------------------
def test_semaine_type_conges_feries_et_duree_sont_canoniques():
    propre = equipes.normaliser_equipes(_avec_capacite())
    nord = next(e for e in propre["liste"] if e["id"] == "equipe-nord")
    assert nord["semaine_type"] == {
        "fuseau": "America/Montreal",
        "lundi": [{"debut": "07:00", "fin": "12:00"}, {"debut": "12:30", "fin": "15:30"}],  # triées
        "mardi": [{"debut": "07:00", "fin": "15:30"}], "samedi": [], "dimanche": [],
    }
    assert "semaine_type" not in next(e for e in propre["liste"] if e["id"] == "equipe-sud")
    assert propre["conges"] == [
        {"equipes": ["equipe-nord"], "du": "2030-06-05", "au": "2030-06-05", "motif": "formation"},
        {"equipes": ["equipe-nord", "equipe-sud"], "du": "2030-07-22", "au": "2030-08-02", "motif": "conge",
         "libelle": "Vacances fictives"},
    ]
    assert propre["feries"] == {"annees": [2030, 2031], "jours": [{"date": "2030-06-24", "libelle": "Férié fictif"}]}
    assert propre["duree_jour_personne_minutes"] == 480
    assert equipes.normaliser_equipes(propre) == propre  # idempotent


def test_le_profil_complet_se_relit_a_l_identique_depuis_le_yaml(opsys_home):
    fichier = equipes.enregistrer_equipes(_avec_capacite())
    attendu = equipes.normaliser_equipes(_avec_capacite())
    assert equipes.lire_equipes() == attendu
    assert yaml.safe_load(fichier.read_text(encoding="utf-8"))["equipes"] == attendu


def test_un_yaml_ecrit_a_la_main_se_lit_dates_non_guillemetees_comprises(tmp_path):
    texte = """
equipes:
  liste:
    - id: eq-a
      membres: [alice.fictif]
      competences: []
      depot: {id: depot-a, latitude_microdegres: 45500000, longitude_microdegres: -73600000}
      quarts: [{jour: 0, debut_min: 480, fin_min: 1020}]
      semaine_type: {fuseau: America/Montreal, lundi: [{debut: "07:00", fin: "15:30"}], dimanche: []}
  conges: [{equipes: [eq-a], du: 2030-06-03, au: 2030-06-04, motif: autre}]
  feries: {annees: [2030], jours: [{date: 2030-06-24}]}
"""
    brut = yaml.safe_load(texte)["equipes"]
    propre = equipes.normaliser_equipes(brut)
    assert propre["conges"][0]["du"] == "2030-06-03" and propre["feries"]["jours"] == [{"date": "2030-06-24"}]


def test_le_journal_compte_sans_libelle_ni_date(opsys_home):
    stockage.migrer()
    equipes.enregistrer_equipes(_avec_capacite(), par="nathan")
    with etat.session() as cnx:
        details = etat.lire_journal(cnx)[0]["details"]
    assert details["semaine_type_equipes"] == ["equipe-nord"]
    assert details["conges_declares"] == 2 and details["feries_declares"] == 1
    assert details["feries_annees"] == [2030, 2031] and details["duree_jour_personne_minutes"] == 480
    texte = json.dumps(details, ensure_ascii=False)
    assert "fictive" not in texte and "Férié" not in texte and "2030-06" not in texte


def test_le_gabarit_de_docs_est_un_profil_valide_sans_ferie_invente():
    brut = yaml.safe_load(GABARIT.read_text(encoding="utf-8"))
    propre = equipes.normaliser_equipes(brut)
    assert all("semaine_type" in equipe for equipe in propre["liste"])
    # OPSYS ne fournit aucune liste de fériés : le gabarit n'en déclare aucune, le propriétaire la saisit.
    assert "feries" not in propre
    assert "CNESST" in GABARIT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. Validation stricte
# ---------------------------------------------------------------------------
def _refus(modifier, attendu):
    profil = _avec_capacite()
    modifier(profil)
    with pytest.raises(ProfilInvalide, match=attendu):
        equipes.normaliser_equipes(profil)


def _semaine_nord(profil, **jours):
    profil["liste"][0]["semaine_type"] = _semaine(**jours)


@pytest.mark.parametrize("heure", ["7:00", "07:60", "25:00", "24:01", "07h00", "", " 07:00", "07:00:00"])
def test_heure_mal_formee_refusee(heure):
    _refus(lambda p: _semaine_nord(p, lundi=[{"debut": heure, "fin": "16:00"}]), "HH:MM")


def test_heure_non_texte_refusee_avec_le_piege_yaml_explique():
    # `12:30` sans guillemets : YAML 1.1 le lit comme 750 (base 60).
    assert yaml.safe_load("x: 12:30")["x"] == 750
    _refus(lambda p: _semaine_nord(p, lundi=[{"debut": 750, "fin": "16:00"}]), "GUILLEMETS")


@pytest.mark.parametrize(("plages", "attendu"), [
    ([{"debut": "08:00", "fin": "12:00"}, {"debut": "11:59", "fin": "16:00"}], "chevauchent"),
    ([{"debut": "08:00", "fin": "12:00"}, {"debut": "08:00", "fin": "12:00"}], "chevauchent"),
    ([{"debut": "08:00", "fin": "16:00"}, {"debut": "09:00", "fin": "10:00"}], "chevauchent"),
    ([{"debut": "16:00", "fin": "08:00"}], "précéder"),
    ([{"debut": "08:00", "fin": "08:00"}], "précéder"),
    ([{"debut": "24:00", "fin": "24:00"}], "fin de plage"),
    ([{"debut": "08:00"}], "manquantes"),
    ([{"debut": "08:00", "fin": "12:00", "personne": "alice"}], "inconnues"),
])
def test_plages_invalides_refusees(plages, attendu):
    _refus(lambda p: _semaine_nord(p, lundi=plages), attendu)


def test_plages_bout_a_bout_et_journee_complete_admises():
    profil = _avec_capacite()
    _semaine_nord(profil, lundi=[{"debut": "08:00", "fin": "12:00"}, {"debut": "12:00", "fin": "16:00"}],
                  mardi=[{"debut": "00:00", "fin": "24:00"}])
    assert equipes.normaliser_equipes(profil)["liste"][0]["semaine_type"]["mardi"] == [{"debut": "00:00",
                                                                                       "fin": "24:00"}]


@pytest.mark.parametrize("fuseau", ["UTC", "America/Toronto", "EST", None, ""])
def test_fuseau_autre_que_montreal_refuse(fuseau):
    _refus(lambda p: p["liste"][0]["semaine_type"].update(fuseau=fuseau), "America/Montreal")


def test_semaine_type_sans_fuseau_jour_inconnu_ou_vide_refusee():
    _refus(lambda p: p["liste"][0]["semaine_type"].pop("fuseau"), "manquantes")
    _refus(lambda p: p["liste"][0]["semaine_type"].update(lundy=[]), "inconnues")
    _refus(lambda p: p["liste"][0].update(semaine_type={"fuseau": "America/Montreal"}), "au moins un jour")
    _refus(lambda p: p["liste"][0].update(semaine_type=[]), "objet")


@pytest.mark.parametrize(("conge", "attendu"), [
    ({"equipes": ["equipe-ouest"], "du": "2030-06-03", "au": "2030-06-03", "motif": "conge"}, "non déclarées"),
    ({"equipes": [], "du": "2030-06-03", "au": "2030-06-03", "motif": "conge"}, "vide"),
    ({"equipes": ["equipe-nord"], "du": "2030-06-04", "au": "2030-06-03", "motif": "conge"}, "précède"),
    ({"equipes": ["equipe-nord"], "du": "2030-06-03", "au": "2030-06-03", "motif": "maladie"}, "motif"),
    ({"equipes": ["equipe-nord"], "du": "2030-06-03", "au": "2030-06-03", "motif": "conge",
      "personne": "alice.fictif"}, "inconnues"),
    ({"equipes": ["equipe-nord"], "du": "2030-6-3", "au": "2030-06-03", "motif": "conge"}, "AAAA-MM-JJ"),
    ({"equipes": ["equipe-nord"], "du": "2030-06-03T08:00", "au": "2030-06-03", "motif": "conge"}, "AAAA-MM-JJ"),
    ({"equipes": ["equipe-nord"], "du": datetime.datetime(2030, 6, 3, 8), "au": "2030-06-03", "motif": "conge"},
     "AAAA-MM-JJ"),
    ({"equipes": ["equipe-nord"], "du": "2030-01-01", "au": "2031-12-31", "motif": "conge"}, "366 jours"),
    ({"equipes": ["equipe-nord"], "du": "2030-06-03", "au": "2030-06-03", "motif": "conge",
      "libelle": "ligne\nsuivante"}, "contrôle"),
    ({"equipes": ["equipe-nord"], "du": "2030-06-03", "au": "2030-06-03", "motif": "conge",
      "libelle": "x" * 121}, "120"),
])
def test_conges_invalides_refuses(conge, attendu):
    _refus(lambda p: p.update(conges=[conge]), attendu)


def test_conge_en_double_ou_sans_liste_d_equipes_refuse():
    conge = {"equipes": ["equipe-nord"], "du": "2030-06-03", "au": "2030-06-03", "motif": "conge"}
    _refus(lambda p: p.update(conges=[conge, dict(conge)]), "double")
    with pytest.raises(ProfilInvalide, match="déclare d'abord"):
        equipes.normaliser_equipes({"conges": [conge]})


@pytest.mark.parametrize(("feries", "attendu"), [
    ({"annees": [], "jours": []}, "vide"),
    ({"annees": [2030, 2030], "jours": []}, "double"),
    ({"annees": [2030], "jours": [{"date": "2031-01-01"}]}, "hors des années"),
    ({"annees": [2030], "jours": [{"date": "2030-06-24"}, {"date": "2030-06-24"}]}, "deux fois"),
    ({"annees": [2030]}, "manquantes"),
    ({"annees": ["2030"], "jours": []}, "entier"),
    ({"annees": [2030], "jours": [{"date": "2030-02-30"}]}, "AAAA-MM-JJ"),
])
def test_feries_invalides_refuses(feries, attendu):
    _refus(lambda p: p.update(feries=feries), attendu)


@pytest.mark.parametrize("duree", [0, -480, 1441, "480", 480.0, True, None])
def test_duree_jour_personne_entier_explicite_borne(duree):
    _refus(lambda p: p.update(duree_jour_personne_minutes=duree), "duree_jour_personne_minutes")


def test_une_cle_rh_reste_refusee_dans_un_conge_ou_une_semaine_type():
    _refus(lambda p: p.update(absences_personnes=[]), "inconnues")

