"""PLAN T4.1-a : localisation des chantiers, partie pure (`m4_field_ops.localisation`).

Le mini-RQA de ces tests est FICTIF (`tests/data/rqa_fictif.csv`, colonne `fictif` = true, données
inventées) : mêmes en-têtes que le guide d'utilisation du RQA v1.2, mais aucune adresse réelle. Il
contient exprès un doublon (deux « 30 rue Principale, Saint-Paul » dans deux MRC), des suffixes et des
unités, toutes les qualités de position, une adresse non certifiée, une adresse détruite et trois lignes
inutilisables (sans numéro, coordonnées inversées, coordonnées illisibles), plus un identifiant en double.

Ce fichier prouve : la normalisation, la correspondance EXACTE, le verdict « coordonnées manquantes : à
confirmer » (jamais une position inventée), l'import, l'absence de tout accès réseau, le chiffrement
des coordonnées, l'empreinte d'adresse et le maillon versionné (le dernier gagne, l'historique reste, la
chaîne reste valide quand la clé est détruite). Les outils, la base durable et le contrôle d'accès sont
prouvés dans `test_localisation_outils.py`.
"""

from __future__ import annotations

import ast
import csv
import json
import socket
from pathlib import Path

import pytest
from m4_field_ops import digest, localisation
from m4_field_ops import registre as registre_m4

FICTIF = True
DONNEES = Path(__file__).parent / "data" / "rqa_fictif.csv"
CODE_A_CONFIRMER = "REJ-COORDONNEES-A-CONFIRMER"
HORODATAGE = "2026-09-28T10:00:00+00:00"
CLE = bytes(range(32))
AUTRE_CLE = bytes(range(1, 33))


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def chemin_index(tmp_path_factory):
    chemin = tmp_path_factory.mktemp("rqa") / "rqa" / "index.sqlite"
    localisation.importer_rqa(DONNEES, chemin)
    return chemin


@pytest.fixture
def index(chemin_index):
    with localisation.IndexRqa.ouvrir(chemin_index) as ouvert:
        yield ouvert


def _proposer(index, adresse):
    return localisation.proposer(index, adresse)


def _code(verdict):
    assert verdict is not None
    return verdict["code"]


# =========================================================================================
# 1. Normalisation
# =========================================================================================
@pytest.mark.parametrize(("texte", "attendu"), [
    ("Belœil", "beloeil"),
    ("L'Assomption", "l assomption"),
    ("L’Assomption", "l assomption"),
    ("  Saint-Jean-sur-Richelieu ,  ", "saint jean sur richelieu"),
    ("Église", "eglise"),
    ("ÉCOLE  Nº 5", "ecole no 5"),  # NFKD : º devient o
])
def test_normaliser_texte(texte, attendu):
    assert localisation.normaliser_texte(texte) == attendu


@pytest.mark.parametrize(("ecrit", "attendu"), [
    ("St-Jean-sur-Richelieu", "saint jean sur richelieu"),
    ("Saint-Jean-sur-Richelieu", "saint jean sur richelieu"),
    ("Ste-Anne-des-Plaines", "sainte anne des plaines"),
    ("Ville de Québec", "quebec"),
    ("Paroisse de Saint-Paul", "saint paul"),
    ("Belœil", "beloeil"),
])
def test_normaliser_municipalite(ecrit, attendu):
    assert localisation.normaliser_municipalite(ecrit) == attendu


@pytest.mark.parametrize(("ecrit", "attendu"), [
    ("boul. Iberville", "boulevard iberville"),
    ("Ch. du Golf", "chemin du golf"),
    ("rue de l’Église", "rue de l eglise"),
    ("Rue Ste-Anne", "rue sainte anne"),
    ("Chemin de la Marquise N.-E.", "chemin de la marquise nord est"),
    ("Chemin de la Marquise S.", "chemin de la marquise sud"),
    ("Chemin de la Marquise Sud", "chemin de la marquise sud"),
    ("Grande Allée E", "grande allee est"),
    ("Rte 138", "route 138"),
])
def test_normaliser_odonyme(ecrit, attendu):
    assert localisation.normaliser_odonyme(ecrit) == attendu


@pytest.mark.parametrize("fonction", [
    localisation.normaliser_texte, localisation.normaliser_municipalite, localisation.normaliser_odonyme,
])
@pytest.mark.parametrize("texte", ["St-Jean N.-E.", "Boul. de l’Église E", "Ville de Belœil", "  ", "x"])
def test_normalisation_idempotente(fonction, texte):
    une_fois = fonction(texte)
    assert fonction(une_fois) == une_fois


# =========================================================================================
# 2. Analyse de l'adresse : structurée ou en une ligne, jamais devinée
# =========================================================================================
def test_adresse_structuree_normalisee():
    adresse, verdict = localisation.analyser_adresse({
        "numero_municipal": "56", "suffixe": " a ", "unite": "2", "odonyme": "boul. du Séminaire N.",
        "municipalite": "St-Jean-sur-Richelieu", "code_postal": "j3b 5j6", "code_municipalite": "56083",
    })
    assert verdict is None
    assert adresse == {
        "numero": 56, "suffixe": "A", "unite": "2", "cle_odonyme": "boulevard du seminaire nord",
        "cle_municipalite": "saint jean sur richelieu", "code_municipalite": "56083", "code_postal": "J3B5J6",
    }


def test_numero_entier_accepte():
    adresse, verdict = localisation.analyser_adresse(
        {"numero_municipal": 100, "odonyme": "rue X", "municipalite": "Y"})
    assert verdict is None and adresse["numero"] == 100 and adresse["suffixe"] == "" and adresse["unite"] == ""


@pytest.mark.parametrize(("adresse", "code"), [
    ({"odonyme": "rue X", "municipalite": "Y"}, "REJ-CHAMP-MANQUANT"),
    ({"numero_municipal": "1", "municipalite": "Y"}, "REJ-CHAMP-MANQUANT"),
    ({"numero_municipal": "1", "odonyme": "rue X"}, "REJ-CHAMP-MANQUANT"),
    ({"numero_municipal": "1", "odonyme": "  ", "municipalite": "Y"}, "REJ-CHAMP-VIDE"),
    ({"numero_municipal": "1", "odonyme": "rue X", "municipalite": ""}, "REJ-CHAMP-VIDE"),
    ({"numero_municipal": "1", "odonyme": "...", "municipalite": "Y"}, "REJ-CHAMP-VIDE"),
    ({"numero_municipal": "56A", "odonyme": "rue X", "municipalite": "Y"}, "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": "0", "odonyme": "rue X", "municipalite": "Y"}, "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": -3, "odonyme": "rue X", "municipalite": "Y"}, "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": True, "odonyme": "rue X", "municipalite": "Y"}, "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": 1.5, "odonyme": "rue X", "municipalite": "Y"}, "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": "1", "odonyme": 12, "municipalite": "Y"}, "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": "1", "odonyme": "rue X", "municipalite": "Y", "suffixe": "?!"}, "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": "1", "odonyme": "rue X", "municipalite": "Y", "unite": "a b*"}, "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": "1", "odonyme": "rue X", "municipalite": "Y", "code_postal": "12345"},
     "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": "1", "odonyme": "rue X", "municipalite": "Y", "code_municipalite": 5},
     "REJ-CONTRAT-INVALIDE"),
    ({"numero_municipal": "1", "odonyme": "rue X", "municipalite": "Y", "ville": "Z"}, "REJ-CONTRAT-INVALIDE"),
    (12345, "REJ-CONTRAT-INVALIDE"),
    (None, "REJ-CONTRAT-INVALIDE"),
    ("Repentigny", "REJ-CONTRAT-INVALIDE"),
    ("rue Principale, Beloeil", "REJ-CONTRAT-INVALIDE"),
])
def test_adresse_incomplete_ou_illisible_refusee_avec_verdict(adresse, code):
    resultat, verdict = localisation.analyser_adresse(adresse)
    assert resultat is None
    assert _code(verdict) == code


@pytest.mark.parametrize(("texte", "attendu"), [
    ("56 A boulevard du Séminaire Nord, Saint-Jean-sur-Richelieu J3B 5J6",
     {"numero_municipal": "56", "suffixe": "A", "odonyme": "boulevard du Séminaire Nord",
      "municipalite": "Saint-Jean-sur-Richelieu", "code_postal": "J3B5J6"}),
    ("2-56 boulevard du Séminaire Nord, Saint-Jean-sur-Richelieu",
     {"numero_municipal": "56", "unite": "2", "odonyme": "boulevard du Séminaire Nord",
      "municipalite": "Saint-Jean-sur-Richelieu"}),
    ("100, rue de l'Église, Repentigny, QC",
     {"numero_municipal": "100", "odonyme": "rue de l'Église", "municipalite": "Repentigny"}),
    ("776 ch. de la Marquise S., Terrebonne j6w 1f8",
     {"numero_municipal": "776", "odonyme": "ch. de la Marquise S.", "municipalite": "Terrebonne",
      "code_postal": "J6W1F8"}),
    ("12 1/3 rue des Érables, Beloeil",
     {"numero_municipal": "12", "suffixe": "1/3", "odonyme": "rue des Érables", "municipalite": "Beloeil"}),
])
def test_adresse_en_une_ligne_de_forme_stricte(texte, attendu):
    normalisee, verdict = localisation.analyser_adresse(texte)
    assert verdict is None
    attendue, verdict_attendu = localisation.analyser_adresse(attendu)
    assert verdict_attendu is None
    assert normalisee == attendue


# =========================================================================================
# 3. Microdegrés : des entiers, jamais un flottant
# =========================================================================================
@pytest.mark.parametrize(("degres", "attendu"), [
    ("46.555572433870", 46555572),
    ("-71.26426574247", -71264266),
    ("45.5", 45500000),
    (46, 46000000),
    ("0.0000005", 0),       # égalité : vers le pair
    ("0.0000015", 2),
    ("-0.0000015", -2),
    (" -73.450000000000 ", -73450000),
])
def test_microdegres_exacts(degres, attendu):
    resultat = localisation.microdegres(degres)
    assert resultat == attendu and type(resultat) is int


@pytest.mark.parametrize("degres", ["abc", "", "NaN", "Infinity", 1.5, True, None, [1]])
def test_microdegres_illisibles_refuses(degres):
    with pytest.raises(ValueError, match="illisibles"):
        localisation.microdegres(degres)


@pytest.mark.parametrize(("libelle", "precision"), [
    ("Bâtiment", "batiment"), ("Accès propriété", "acces_propriete"), ("Front lot", "front_lot"),
    ("Centre lot", "centre_lot"), ("Site", "site"), ("Géocodée", "geocodee"), ("Incertaine", "incertaine"),
    ("Zone floue", "inconnue"), ("", "inconnue"), (None, "inconnue"),
])
def test_precision_rqa(libelle, precision):
    assert localisation.precision_rqa(libelle) == precision


def test_seules_quatre_precisions_donnent_une_proposition():
    assert set(localisation.PRECISIONS_PROPOSABLES) == {"batiment", "acces_propriete", "front_lot", "centre_lot"}


# =========================================================================================
# 4. Import du CSV du RQA dans l'index local
# =========================================================================================
def test_import_complet_rapporte_chaque_ecart(tmp_path):
    rapport = localisation.importer_rqa(DONNEES, tmp_path / "i.sqlite")
    assert rapport == {
        "version": "2026-09-01", "lignes_lues": 22, "importees": 17, "ignorees_hors_mrc": 0,
        "ignorees_detruites": 1, "doublons_identifiant": 1, "ignorees_invalides": 3,
        "raisons_invalides": {
            "coordonnees_hors_quebec": 1, "coordonnees_illisibles": 1, "numero_municipal_absent": 1,
        },
        "mrc": [],
    }


def test_import_filtre_par_code_de_mrc(tmp_path):
    rapport = localisation.importer_rqa(DONNEES, tmp_path / "i.sqlite", mrc=["60"])
    assert rapport["importees"] == 9 and rapport["ignorees_hors_mrc"] == 8 and rapport["mrc"] == ["60"]
    with localisation.IndexRqa.ouvrir(tmp_path / "i.sqlite") as idx:
        assert idx.nombre_adresses == 9
        assert idx.lire("f005") is None  # Joliette : hors de la MRC gardée
        assert idx.lire("f001")["nom_mrc"] == "MRC de L'Assomption"


def test_import_filtre_par_nom_de_mrc_sans_accent_ni_casse(tmp_path):
    rapport = localisation.importer_rqa(DONNEES, tmp_path / "i.sqlite", mrc=["joliette", "LA VALLEE-DU-RICHELIEU"])
    assert rapport["importees"] == 5  # f005, f006, f007, f011, f014
    assert rapport["mrc"] == ["joliette", "la vallee du richelieu"]


def test_import_liste_de_mrc_vide_refusee(tmp_path):
    with pytest.raises(ValueError, match="mrc"):
        localisation.importer_rqa(DONNEES, tmp_path / "i.sqlite", mrc=[])
    assert not (tmp_path / "i.sqlite").exists()


def test_import_qui_ne_donne_rien_conserve_l_index_en_place(tmp_path):
    chemin = tmp_path / "i.sqlite"
    localisation.importer_rqa(DONNEES, chemin)
    avant = chemin.read_bytes()
    with pytest.raises(ValueError, match="aucune adresse importable"):
        localisation.importer_rqa(DONNEES, chemin, mrc=["MRC qui n'existe pas"])
    assert chemin.read_bytes() == avant
    assert not list(tmp_path.glob("*.import"))


def test_import_refuse_une_colonne_absente_et_ne_laisse_rien(tmp_path):
    csv_incomplet = tmp_path / "incomplet.csv"
    csv_incomplet.write_text("identifiant_unique_adresse,numero_municipal\nx,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="colonnes absentes") as erreur:
        localisation.importer_rqa(csv_incomplet, tmp_path / "i.sqlite")
    assert "latitude" in str(erreur.value) and "nom_mrc" in str(erreur.value)
    assert not (tmp_path / "i.sqlite").exists() and not list(tmp_path.glob("*.import"))


def test_import_tolere_un_bom_et_les_seules_colonnes_requises(tmp_path):
    colonnes = [*localisation.COLONNES_RQA_REQUISES, "specifique_odonyme", "generique_odonyme"]
    chemin_csv = tmp_path / "min.csv"
    with chemin_csv.open("w", encoding="utf-8-sig", newline="") as f:
        ecrivain = csv.DictWriter(f, fieldnames=colonnes)
        ecrivain.writeheader()
        ecrivain.writerow({
            "identifiant_unique_adresse": "m1", "numero_municipal": "7", "adresse_formatee": "7 Rue Fictive, Y",
            "qualite_positionnement_geometrique": "Bâtiment", "etat": "Certifiée", "code_mrc": "1",
            "nom_mrc": "MRC fictive", "code_municipalite": "1", "nom_municipalite": "Y",
            "longitude": "-73.5", "latitude": "45.5", "specifique_odonyme": "Fictive", "generique_odonyme": "Rue",
        })
    rapport = localisation.importer_rqa(chemin_csv, tmp_path / "i.sqlite", version="2026-09")
    assert rapport["importees"] == 1 and rapport["version"] == "2026-09"
    with localisation.IndexRqa.ouvrir(tmp_path / "i.sqlite") as idx:
        # Sans `odonyme_recompose_normal`, la voie se recompose : générique, particule, spécifique, cardinal.
        proposition, verdict = localisation.proposer(idx, "7 rue Fictive, Y")
    assert verdict is None and proposition["coordonnees"] == {
        "latitude_microdegres": 45500000, "longitude_microdegres": -73500000}


def test_import_exige_une_version_non_ambigue(tmp_path):
    chemin_csv = tmp_path / "deux_versions.csv"
    lignes = list(csv.DictReader(DONNEES.open(encoding="utf-8", newline="")))
    lignes[1]["date_diffusion_version"] = "2026-10-01"
    with chemin_csv.open("w", encoding="utf-8", newline="") as f:
        ecrivain = csv.DictWriter(f, fieldnames=list(lignes[0]))
        ecrivain.writeheader()
        ecrivain.writerows(lignes)
    with pytest.raises(ValueError, match="version du RQA introuvable ou ambiguë"):
        localisation.importer_rqa(chemin_csv, tmp_path / "i.sqlite")
    assert not (tmp_path / "i.sqlite").exists()
    # Fournie explicitement, elle est retenue : jamais devinée, jamais la plus récente par défaut.
    assert localisation.importer_rqa(chemin_csv, tmp_path / "i.sqlite", version="2026-10-01")["version"] == "2026-10-01"


def test_import_deux_fois_donne_le_meme_index(tmp_path):
    premier = localisation.importer_rqa(DONNEES, tmp_path / "a.sqlite")
    second = localisation.importer_rqa(DONNEES, tmp_path / "b.sqlite")
    assert premier == second
    with localisation.IndexRqa.ouvrir(tmp_path / "a.sqlite") as a:
        lignes_a = a._lignes("1 = 1", [])
    with localisation.IndexRqa.ouvrir(tmp_path / "b.sqlite") as b:
        lignes_b = b._lignes("1 = 1", [])
    assert lignes_a == lignes_b and len(lignes_a) == 17


def test_import_remplace_l_index_precedent(tmp_path):
    chemin = tmp_path / "i.sqlite"
    localisation.importer_rqa(DONNEES, chemin)
    localisation.importer_rqa(DONNEES, chemin, mrc=["60"])
    with localisation.IndexRqa.ouvrir(chemin) as idx:
        assert idx.nombre_adresses == 9


def test_cli_importer_ecrit_le_rapport_ou_refuse(tmp_path, capsys):
    chemin = tmp_path / "rqa" / "index.sqlite"
    assert localisation.principal(["importer", "--csv", str(DONNEES), "--index", str(chemin), "--mrc", "60"]) == 0
    rapport = json.loads(capsys.readouterr().out)
    assert rapport["importees"] == 9 and chemin.is_file()
    assert localisation.principal(["importer", "--csv", str(tmp_path / "absent.csv"), "--index", str(chemin)]) == 1
    assert "import refusé" in capsys.readouterr().err
    with localisation.IndexRqa.ouvrir(chemin) as idx:  # l'index en place n'a pas bougé
        assert idx.nombre_adresses == 9


# =========================================================================================
# 5. L'index : ouverture et absence
# =========================================================================================
def test_index_absent_est_un_verdict_qui_dit_quoi_faire(tmp_path):
    index, verdict = localisation.ouvrir_index(tmp_path / "absent.sqlite")
    assert index is None and _code(verdict) == "REJ-INDEX-RQA-ABSENT"
    assert "importer" in verdict["detail"]


def test_fichier_qui_n_est_pas_un_index_est_absent(tmp_path):
    faux = tmp_path / "faux.sqlite"
    faux.write_bytes(b"ceci n'est pas une base SQLite" * 20)
    index, verdict = localisation.ouvrir_index(faux)
    assert index is None and _code(verdict) == "REJ-INDEX-RQA-ABSENT"


def test_index_d_un_autre_schema_est_refuse(tmp_path):
    import sqlite3
    chemin = tmp_path / "autre.sqlite"
    cnx = sqlite3.connect(chemin)
    cnx.execute("CREATE TABLE meta (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL)")
    cnx.execute("INSERT INTO meta VALUES ('schema', 'autre/v9')")
    cnx.commit()
    cnx.close()
    index, verdict = localisation.ouvrir_index(chemin)
    assert index is None and _code(verdict) == "REJ-INDEX-RQA-ABSENT" and "autre schéma" in verdict["detail"]


def test_index_ouvert_en_lecture_seule(chemin_index):
    import sqlite3
    with localisation.IndexRqa.ouvrir(chemin_index) as idx, pytest.raises(sqlite3.OperationalError):
        idx._cnx.execute("DELETE FROM adresses")


# =========================================================================================
# 6. Proposition : correspondance EXACTE, ou « coordonnées manquantes : à confirmer »
# =========================================================================================
def test_correspondance_unique_donne_une_proposition_complete(index):
    proposition, verdict = _proposer(index, {
        "numero_municipal": "100", "odonyme": "boulevard Iberville", "municipalite": "Repentigny"})
    assert verdict is None
    assert proposition == {
        "statut": "proposee",
        "coordonnees": {"latitude_microdegres": 45741000, "longitude_microdegres": -73450000},
        "qualite_positionnement_geometrique": "Bâtiment", "precision": "batiment",
        "rqa_identifiant": "f001", "rqa_version": "2026-09-01",
        "adresse_formatee": "100 Boulevard Iberville, Repentigny J5Y1A1", "nom_mrc": "MRC de L'Assomption",
        "avertissements": [], "attribution": localisation.ATTRIBUTION_RQA, "confirmation_humaine_requise": True,
    }
    assert "CC-BY 4.0" in proposition["attribution"]
    assert "Référentiel québécois des adresses" in proposition["attribution"]
    assert type(proposition["coordonnees"]["latitude_microdegres"]) is int


def test_coordonnees_arrondies_au_microdegre_depuis_les_degres_du_csv(index):
    proposition, _ = _proposer(index, "100 rue de l'Église, Repentigny")
    assert proposition["rqa_identifiant"] == "f002"
    assert proposition["coordonnees"] == {"latitude_microdegres": 45742346, "longitude_microdegres": -73451235}


@pytest.mark.parametrize(("adresse", "identifiant"), [
    ("100 Rue de l’Eglise, repentigny", "f002"),                      # apostrophe courbe, sans accent, minuscules
    ("776 ch. de la Marquise S., Terrebonne J6W 1F8", "f013"),        # abréviations, cardinal, discriminant absent
    ("776 chemin de la Marquise Sud, Terrebonne", "f013"),
    ("5 rue Principale, Belœil", "f014"),                              # ligature
    ("8 rue Ste-Anne, St-Jean-sur-Richelieu", "f015"),                 # saints abrégés
    ("55 A chemin du Golf, L'Assomption", "f003"),                     # suffixe
    ("55 b ch. du Golf, L'Assomption", "f004"),
    ("200 rue Notre-Dame, Joliette", "f005"),                          # sans unité : l'immeuble seul
    ("2-200 rue Notre-Dame, Joliette", "f006"),                        # avec unité
])
def test_ecritures_equivalentes_trouvent_la_meme_adresse(index, adresse, identifiant):
    proposition, verdict = _proposer(index, adresse)
    assert verdict is None, verdict
    assert proposition["rqa_identifiant"] == identifiant


def test_unite_inconnue_ne_devine_pas_l_immeuble(index):
    aide, verdict = _proposer(index, {
        "numero_municipal": "200", "unite": "9", "odonyme": "rue Notre-Dame", "municipalite": "Joliette"})
    assert _code(verdict) == CODE_A_CONFIRMER and "coordonnées manquantes : à confirmer" in verdict["detail"]
    assert aide["raison"] == localisation.RAISON_AUCUNE
    assert [c["rqa_identifiant"] for c in aide["candidats"]] == ["f005", "f006", "f007"]
    assert "coordonnees" not in aide and "statut" not in aide  # des candidats en aide, aucune position choisie


def test_suffixe_absent_ne_choisit_pas_entre_a_et_b(index):
    aide, verdict = _proposer(index, "55 chemin du Golf, L'Assomption")
    assert _code(verdict) == CODE_A_CONFIRMER
    assert aide["raison"] == localisation.RAISON_AUCUNE
    assert {c["rqa_identifiant"] for c in aide["candidats"]} == {"f003", "f004"}
    assert "coordonnees" not in aide


def test_doublon_donne_le_verdict_et_les_candidats_sans_en_choisir_un(index):
    aide, verdict = _proposer(index, "30 rue Principale, Saint-Paul")
    assert _code(verdict) == CODE_A_CONFIRMER and "coordonnées manquantes : à confirmer" in verdict["detail"]
    assert aide["raison"] == localisation.RAISON_PLUSIEURS and aide["nombre_candidats"] == 2
    assert {c["rqa_identifiant"] for c in aide["candidats"]} == {"f011", "f012"}
    assert {c["nom_mrc"] for c in aide["candidats"]} == {"Joliette", "MRC fictive"}
    assert "coordonnees" not in aide and "statut" not in aide
    assert aide["attribution"] == localisation.ATTRIBUTION_RQA and aide["rqa_version"] == "2026-09-01"


def test_un_code_postal_fourni_departage_les_doublons_sans_deviner(index):
    proposition, verdict = _proposer(index, "30 rue Principale, Saint-Paul G0X 1A1")
    assert verdict is None and proposition["rqa_identifiant"] == "f012"
    proposition, verdict = _proposer(index, {
        "numero_municipal": "30", "odonyme": "rue Principale", "municipalite": "Saint-Paul",
        "code_municipalite": "70040"})
    assert verdict is None and proposition["rqa_identifiant"] == "f011"
    # Un code postal qui ne départage rien ne choisit rien.
    aide, verdict = _proposer(index, "30 rue Principale, Saint-Paul H0H 0H0")
    assert _code(verdict) == CODE_A_CONFIRMER and aide["raison"] == localisation.RAISON_PLUSIEURS


def test_un_code_postal_qui_contredit_l_unique_correspondance_est_signale(index):
    proposition, verdict = _proposer(index, "100 boulevard Iberville, Repentigny H0H 0H0")
    assert verdict is None and proposition["rqa_identifiant"] == "f001"
    assert proposition["avertissements"] == ["le code postal fourni diffère de celui du RQA pour cette adresse"]


def test_code_de_municipalite_faux_ne_trouve_rien(index):
    aide, verdict = _proposer(index, {
        "numero_municipal": "5", "odonyme": "rue Principale", "municipalite": "Beloeil", "code_municipalite": "00000"})
    assert _code(verdict) == CODE_A_CONFIRMER and aide["candidats"] == []


@pytest.mark.parametrize("adresse", [
    "999 rue Inconnue, Repentigny",
    "100 rue de l'Église, Villeinexistante",
    "100 boulevard Iberville, Joliette",
])
def test_adresse_absente_jamais_de_position_de_remplacement(index, adresse):
    aide, verdict = _proposer(index, adresse)
    assert _code(verdict) == CODE_A_CONFIRMER
    assert aide["raison"] == localisation.RAISON_AUCUNE and aide["candidats"] == []
    assert aide["nombre_candidats"] == 0
    # Ni centre de ville, ni code postal, ni voie voisine : aucune coordonnée nulle part dans la réponse.
    assert "coordonnees" not in json.dumps(aide, ensure_ascii=False)
    assert "latitude" not in json.dumps(aide, ensure_ascii=False)


def test_adresse_detruite_n_existe_plus_dans_l_index(index):
    aide, verdict = _proposer(index, "16 rue Lafleur, Repentigny")
    assert _code(verdict) == CODE_A_CONFIRMER and aide["candidats"] == []


@pytest.mark.parametrize(("adresse", "qualite"), [
    ("12 rue Lafleur, Repentigny", "Géocodée"),
    ("40 chemin du Lac, Repentigny", "Site"),
    ("42 chemin du Lac, Repentigny", "Incertaine"),
    ("9 chemin du Lac, Repentigny", "Zone floue"),   # valeur que le guide ne liste pas : fail-closed
])
def test_position_de_qualite_faible_est_a_confirmer_sur_place(index, adresse, qualite):
    aide, verdict = _proposer(index, adresse)
    assert _code(verdict) == CODE_A_CONFIRMER
    assert aide["raison"] == localisation.RAISON_QUALITE and "sur place" in verdict["detail"]
    assert [c["qualite_positionnement_geometrique"] for c in aide["candidats"]] == [qualite]
    assert "statut" not in aide


def test_adresse_non_certifiee_est_a_confirmer_sur_place(index):
    aide, verdict = _proposer(index, "14 rue Lafleur, Repentigny")
    assert _code(verdict) == CODE_A_CONFIRMER
    assert aide["raison"] == localisation.RAISON_NON_CERTIFIEE and "Non certifiée" in verdict["detail"]


@pytest.mark.parametrize(("adresse", "identifiant", "qualite"), [
    ("100 boulevard Iberville, Repentigny", "f001", "Bâtiment"),
    ("55 A chemin du Golf, L'Assomption", "f003", "Accès propriété"),
    ("55 B chemin du Golf, L'Assomption", "f004", "Front lot"),
    ("776 ch. de la Marquise S., Terrebonne", "f013", "Centre lot"),
])
def test_les_quatre_bonnes_qualites_donnent_une_proposition(index, adresse, identifiant, qualite):
    proposition, verdict = _proposer(index, adresse)
    assert verdict is None
    assert proposition["rqa_identifiant"] == identifiant
    assert proposition["qualite_positionnement_geometrique"] == qualite
    assert proposition["confirmation_humaine_requise"] is True


def test_adresse_illisible_ou_index_absent_donnent_leur_propre_verdict(index):
    _, verdict = _proposer(index, {"numero_municipal": "1"})
    assert _code(verdict) == "REJ-CHAMP-MANQUANT"
    _, verdict = _proposer(None, "100 boulevard Iberville, Repentigny")
    assert _code(verdict) == "REJ-INDEX-RQA-ABSENT"
    _, verdict = _proposer(None, {"numero_municipal": "1"})
    assert _code(verdict) == "REJ-CHAMP-MANQUANT"  # l'adresse est jugée d'abord


def test_la_liste_de_candidats_est_plafonnee_mais_le_total_est_dit(tmp_path):
    colonnes = [*localisation.COLONNES_RQA_REQUISES, "odonyme_recompose_normal", "code_postal"]
    chemin_csv = tmp_path / "doublons.csv"
    with chemin_csv.open("w", encoding="utf-8", newline="") as f:
        ecrivain = csv.DictWriter(f, fieldnames=colonnes)
        ecrivain.writeheader()
        for i in range(localisation.MAX_CANDIDATS + 2):
            ecrivain.writerow({
                "identifiant_unique_adresse": f"d{i:02d}", "numero_municipal": "1",
                "adresse_formatee": "1 Rue Fictive, Ville", "qualite_positionnement_geometrique": "Bâtiment",
                "etat": "Certifiée", "code_mrc": str(i), "nom_mrc": f"MRC fictive {i}", "code_municipalite": str(i),
                "nom_municipalite": "Ville", "longitude": "-73.5", "latitude": "45.5",
                "odonyme_recompose_normal": "Rue Fictive", "code_postal": "",
            })
    localisation.importer_rqa(chemin_csv, tmp_path / "i.sqlite", version="2026-09")
    with localisation.IndexRqa.ouvrir(tmp_path / "i.sqlite") as idx:
        aide, verdict = _proposer(idx, "1 rue Fictive, Ville")
    assert _code(verdict) == CODE_A_CONFIRMER and aide["raison"] == localisation.RAISON_PLUSIEURS
    assert len(aide["candidats"]) == localisation.MAX_CANDIDATS
    assert aide["nombre_candidats"] == localisation.MAX_CANDIDATS + 2


def test_proposer_est_deterministe(index):
    adresses = ["100 boulevard Iberville, Repentigny", "30 rue Principale, Saint-Paul", "999 rue Inconnue, Repentigny"]
    une_fois = [json.dumps(_proposer(index, a), sort_keys=True, ensure_ascii=False) for a in adresses]
    deux_fois = [json.dumps(_proposer(index, a), sort_keys=True, ensure_ascii=False) for a in adresses]
    assert une_fois == deux_fois


# =========================================================================================
# 7. Aucun accès réseau, aucune horloge, aucun aléa
# =========================================================================================
@pytest.fixture
def sockets_bloques(monkeypatch):
    def interdit(*_args, **_kwargs):
        raise AssertionError("accès réseau interdit dans la localisation")

    class SocketInterdit:
        def __init__(self, *_args, **_kwargs):
            interdit()

    monkeypatch.setattr(socket, "socket", SocketInterdit)
    monkeypatch.setattr(socket, "create_connection", interdit)
    monkeypatch.setattr(socket, "getaddrinfo", interdit)
    monkeypatch.setattr(socket, "gethostbyname", interdit)
    monkeypatch.setattr(socket, "socketpair", interdit)


def test_le_blocage_des_sockets_est_reel(sockets_bloques):
    with pytest.raises(AssertionError, match="accès réseau interdit"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(AssertionError, match="accès réseau interdit"):
        socket.getaddrinfo("example.org", 443)


def test_import_proposition_et_confirmation_sans_aucun_socket(sockets_bloques, tmp_path):
    chemin = tmp_path / "rqa" / "index.sqlite"
    rapport = localisation.importer_rqa(DONNEES, chemin)
    assert rapport["importees"] == 17
    index, verdict = localisation.ouvrir_index(chemin)
    assert verdict is None
    try:
        proposition, verdict = _proposer(index, "100 boulevard Iberville, Repentigny")
        assert verdict is None
        _, verdict = _proposer(index, "999 rue Inconnue, Repentigny")  # même l'absence ne sort pas du serveur
        assert _code(verdict) == CODE_A_CONFIRMER
        registre = registre_m4.Registre()
        accuse, verdict = localisation.confirmer(
            registre, "C-RESEAU", "confirmee", HORODATAGE, "admin.fictif",
            adresse="100 boulevard Iberville, Repentigny", source="rqa",
            rqa_identifiant=proposition["rqa_identifiant"], index=index, fournir_cle=lambda: CLE)
    finally:
        index.fermer()
    assert verdict is None and accuse["version"] == 1


_MODULES_INTERDITS = frozenset({
    "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "imaplib",
    "poplib", "telnetlib", "xmlrpc", "asyncio", "selectors", "subprocess", "multiprocessing",
    "time", "datetime", "random", "secrets", "uuid", "opsys", "sqlalchemy",
})


def test_le_module_n_importe_ni_reseau_ni_horloge_ni_alea_ni_socle():
    source = Path(localisation.__file__).read_text(encoding="utf-8")
    importes = set()
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.Import):
            importes.update(alias.name.split(".")[0] for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
            importes.add(noeud.module.split(".")[0])
    assert importes & _MODULES_INTERDITS == set(), importes & _MODULES_INTERDITS
    assert {"sqlite3", "csv", "hmac", "hashlib"} <= importes  # le contrôle regarde bien les imports réels


def test_gardes_ast_du_paquet_passent_avec_le_nouveau_module():
    ok, message = digest.garde_absence_horloge()
    assert ok, message
    ok, message = digest.garde_conformite_r020()
    assert ok, message


# =========================================================================================
# 8. Chiffrement des coordonnées et empreinte d'adresse
# =========================================================================================
def test_chiffrement_aller_retour_et_nonce_par_version():
    nonce_1 = localisation.nonce_localisation("C1", 1)
    nonce_2 = localisation.nonce_localisation("C1", 2)
    assert len(nonce_1) == 16 and nonce_1 != nonce_2 != localisation.nonce_localisation("C2", 2)
    chiffre = localisation.chiffrer_coordonnees(CLE, nonce_1, 45741000, -73450000)
    assert localisation.dechiffrer_coordonnees(CLE, nonce_1, chiffre) == (45741000, -73450000)
    assert bytes.fromhex(chiffre) != b"45741000|-73450000"
    assert chiffre != localisation.chiffrer_coordonnees(CLE, nonce_2, 45741000, -73450000)
    assert chiffre != localisation.chiffrer_coordonnees(AUTRE_CLE, nonce_1, 45741000, -73450000)


def test_mauvaise_cle_ou_mauvais_nonce_jamais_une_paire_fausse():
    nonce = localisation.nonce_localisation("C1", 1)
    chiffre = localisation.chiffrer_coordonnees(CLE, nonce, 45741000, -73450000)
    with pytest.raises(ValueError, match="déchiffrement invalide"):
        localisation.dechiffrer_coordonnees(AUTRE_CLE, nonce, chiffre)
    with pytest.raises(ValueError, match="déchiffrement invalide"):
        localisation.dechiffrer_coordonnees(CLE, localisation.nonce_localisation("C1", 2), chiffre)
    for abime in ("zz", "abc", ""):
        with pytest.raises(ValueError, match="déchiffrement invalide"):
            localisation.dechiffrer_coordonnees(CLE, nonce, abime)


def test_le_chiffrement_de_la_localisation_n_est_pas_celui_du_gps():
    from m4_field_ops import retention
    nonce = localisation.nonce_localisation("C1", 1)
    chiffre_local = localisation.chiffrer_coordonnees(CLE, nonce, 45741000, -73450000)
    chiffre_gps = retention.chiffrer_position(CLE, nonce, 45741000, -73450000)
    assert chiffre_local != chiffre_gps  # contexte de flux distinct : une clé ne sert pas deux usages


def test_empreinte_d_adresse_stable_par_equivalence_et_liee_a_la_cle():
    a, _ = localisation.analyser_adresse("8 rue Ste-Anne, St-Jean-sur-Richelieu")
    b, _ = localisation.analyser_adresse({"numero_municipal": 8, "odonyme": "Rue Sainte-Anne",
                                          "municipalite": "Saint-Jean-sur-Richelieu", "code_postal": "J3B1H1"})
    autre, _ = localisation.analyser_adresse("9 rue Ste-Anne, St-Jean-sur-Richelieu")
    unite, _ = localisation.analyser_adresse("2-8 rue Ste-Anne, St-Jean-sur-Richelieu")
    empreinte = localisation.empreinte_adresse(CLE, a)
    assert len(empreinte) == 64 and int(empreinte, 16) >= 0
    assert empreinte == localisation.empreinte_adresse(CLE, b)          # le code postal n'en fait pas partie
    assert empreinte != localisation.empreinte_adresse(CLE, autre)
    assert empreinte != localisation.empreinte_adresse(CLE, unite)
    assert empreinte != localisation.empreinte_adresse(AUTRE_CLE, a)    # sans la clé, invérifiable


# =========================================================================================
# 9. Le maillon `localisation_chantier` : versionné, le dernier gagne, chaîne intacte
# =========================================================================================
ADRESSE_F001 = "100 boulevard Iberville, Repentigny"
CHAMPS_MAILLON = {
    "type_entree", "chantier_id", "version", "action", "coordonnees_chiffrees", "empreinte_adresse", "source",
    "rqa_identifiant", "rqa_version", "precision", "confirme_par", "motif", "horodatage",
    "ligne_id", "precedent_ligne_id",
}


class _Cle:
    """Fournisseur de clé qui compte ses appels : un refus ne doit jamais en demander une."""

    def __init__(self, cle=CLE):
        self.cle = cle
        self.appels = 0

    def __call__(self):
        self.appels += 1
        return self.cle


def _confirmer(registre, index, cle=None, chantier="C1", action="confirmee", par="admin.fictif", **args):
    cle = cle or _Cle()
    resultat = localisation.confirmer(
        registre, chantier, action, args.pop("horodatage", HORODATAGE), par, index=index, fournir_cle=cle, **args)
    return resultat, cle


def _confirmer_rqa(registre, index, cle=None, chantier="C1", adresse=ADRESSE_F001, identifiant="f001", **args):
    return _confirmer(
        registre, index, cle, chantier, adresse=adresse, source="rqa", rqa_identifiant=identifiant, **args)


def _maillons(registre, chantier="C1"):
    return [m for m in registre.lire() if m["type_entree"] == "localisation_chantier" and m["chantier_id"] == chantier]


def test_confirmation_rqa_ecrit_un_maillon_chiffre_sans_adresse_ni_coordonnees_en_clair(index):
    registre = registre_m4.Registre()
    (accuse, verdict), cle = _confirmer_rqa(registre, index)
    assert verdict is None and cle.appels == 1
    assert accuse["version"] == 1 and accuse["action"] == "confirmee" and accuse["source"] == "rqa"
    assert accuse["precision"] == "batiment" and accuse["confirme_par"] == "admin.fictif"
    assert accuse["tete_chaine"] == registre.tete() == accuse["ligne_id"]
    # L'accusé (rejoué par l'idempotence d'appareil) ne porte ni coordonnées ni adresse.
    accuse_json = json.dumps(accuse, ensure_ascii=False).lower()
    for interdit in ("45741", "73450", "iberville", "repentigny", "latitude", "longitude"):
        assert interdit not in accuse_json
    [maillon] = _maillons(registre)
    assert set(maillon) == CHAMPS_MAILLON
    assert (maillon["source"], maillon["rqa_identifiant"], maillon["rqa_version"]) == ("rqa", "f001", "2026-09-01")
    assert maillon["coordonnees_chiffrees"] and len(maillon["empreinte_adresse"]) == 64
    assert maillon["motif"] == "" and maillon["horodatage"] == HORODATAGE
    # Rien de lisible dans TOUT le registre : ni adresse, ni ville, ni coordonnées (degrés ou microdegrés).
    registre_json = json.dumps(registre.lire(), ensure_ascii=False).lower()
    for interdit in ("iberville", "repentigny", "45741000", "-73450000", "45.741", "73.45", "j5y1a1"):
        assert interdit not in registre_json, interdit
    assert registre.valider_chaine() is True


def test_les_coordonnees_confirmees_viennent_de_l_index_et_se_relisent(index):
    registre = registre_m4.Registre()
    _confirmer_rqa(registre, index)
    position, verdict = localisation.position_confirmee(registre, "C1", CLE)
    assert verdict is None
    assert position == {
        "chantier_id": "C1", "version": 1, "latitude_microdegres": 45741000, "longitude_microdegres": -73450000,
        "source": "rqa", "precision": "batiment", "rqa_identifiant": "f001", "rqa_version": "2026-09-01",
        "confirme_par": "admin.fictif", "horodatage": HORODATAGE, "ligne_id": registre.tete(),
    }


def test_jamais_confirmee_est_a_confirmer_et_le_chantier_voisin_n_est_pas_touche(index):
    registre = registre_m4.Registre()
    position, verdict = localisation.position_confirmee(registre, "C1", CLE)
    assert position is None and _code(verdict) == CODE_A_CONFIRMER
    assert "coordonnées manquantes : à confirmer" in verdict["detail"]
    _confirmer_rqa(registre, index, chantier="C1")
    assert localisation.position_confirmee(registre, "C2", CLE)[1]["code"] == CODE_A_CONFIRMER
    assert localisation.confirmation_courante(registre, "C2") is None


def test_dernier_maillon_gagne_et_l_historique_reste_lisible(index):
    registre = registre_m4.Registre()
    _confirmer_rqa(registre, index)
    (accuse_2, verdict), _ = _confirmer(
        registre, index, adresse=ADRESSE_F001, source="manuel", latitude_microdegres=45741500,
        longitude_microdegres=-73450500, motif="portail d'accès relevé sur place", par="marie.fictif",
        horodatage="2026-09-29T08:30:00+00:00")
    assert verdict is None and accuse_2["version"] == 2
    assert accuse_2["source"] == "manuel" and accuse_2["precision"] == "manuel"
    position, _ = localisation.position_confirmee(registre, "C1", CLE)
    assert (position["version"], position["latitude_microdegres"], position["longitude_microdegres"]) == (
        2, 45741500, -73450500)
    assert position["source"] == "manuel" and position["confirme_par"] == "marie.fictif"
    assert position["rqa_identifiant"] is None and position["rqa_version"] is None
    assert localisation.confirmation_courante(registre, "C1")["version"] == 2
    historique = localisation.historique(registre, "C1", CLE)
    assert [(h["version"], h["action"], h["source"], h["confirme_par"]) for h in historique] == [
        (1, "confirmee", "rqa", "admin.fictif"), (2, "confirmee", "manuel", "marie.fictif")]
    assert historique[0]["position"] == {"latitude_microdegres": 45741000, "longitude_microdegres": -73450000}
    assert historique[1]["position"] == {"latitude_microdegres": 45741500, "longitude_microdegres": -73450500}
    assert historique[1]["motif"] == "portail d'accès relevé sur place"
    assert [m["version"] for m in _maillons(registre)] == [1, 2]  # les deux maillons restent dans la chaîne
    assert registre.valider_chaine() is True


def test_remplacer_une_confirmation_exige_un_motif_et_ne_laisse_rien_sinon(index):
    registre = registre_m4.Registre()
    _confirmer_rqa(registre, index)
    taille = registre.taille()
    (accuse, verdict), cle = _confirmer(
        registre, index, adresse=ADRESSE_F001, source="manuel", latitude_microdegres=45741500,
        longitude_microdegres=-73450500)
    assert accuse is None and _code(verdict) == "REJ-CHAMP-VIDE" and "remplacer" in verdict["detail"]
    assert registre.taille() == taille and cle.appels == 0


def test_deux_confirmations_des_memes_coordonnees_ne_reutilisent_jamais_le_meme_chiffre(index):
    registre = registre_m4.Registre()
    for _ in range(2):
        _confirmer(registre, index, adresse=ADRESSE_F001, source="manuel", latitude_microdegres=45741500,
                   longitude_microdegres=-73450500, motif="même point, reconfirmé")
    premier, second = _maillons(registre)
    assert premier["coordonnees_chiffrees"] != second["coordonnees_chiffrees"]
    assert premier["empreinte_adresse"] == second["empreinte_adresse"]  # même adresse, même clé : même empreinte


def test_retirer_ramene_le_chantier_a_a_confirmer_puis_reconfirmer_est_permis(index):
    registre = registre_m4.Registre()
    _confirmer_rqa(registre, index)
    (accuse, verdict), cle = _confirmer(registre, index, action="retiree")
    assert accuse is None and _code(verdict) == "REJ-CHAMP-VIDE" and cle.appels == 0
    (accuse, verdict), cle = _confirmer(registre, index, action="retiree", motif="mauvaise adresse au dossier")
    assert verdict is None and accuse["version"] == 2 and accuse["action"] == "retiree"
    assert accuse["source"] is None and accuse["precision"] is None and cle.appels == 0  # aucune clé pour retirer
    maillon = _maillons(registre)[1]
    assert maillon["coordonnees_chiffrees"] is None and maillon["empreinte_adresse"] is None
    position, verdict = localisation.position_confirmee(registre, "C1", CLE)
    assert position is None and _code(verdict) == CODE_A_CONFIRMER and "retirée" in verdict["detail"]
    assert "admin.fictif" in verdict["detail"] and "version 2" in verdict["detail"]
    # Retirer deux fois : il n'y a plus rien à retirer.
    (accuse, verdict), _ = _confirmer(registre, index, action="retiree", motif="encore")
    assert accuse is None and "aucune localisation confirmée à retirer" in verdict["detail"]
    # Reconfirmer après un retrait : pas de motif exigé (rien n'est remplacé) ; l'historique garde tout.
    (accuse, verdict), _ = _confirmer_rqa(registre, index, adresse="8 rue Ste-Anne, St-Jean-sur-Richelieu",
                                          identifiant="f015")
    assert verdict is None and accuse["version"] == 3
    assert localisation.position_confirmee(registre, "C1", CLE)[0]["rqa_identifiant"] == "f015"
    assert [h["action"] for h in localisation.historique(registre, "C1", CLE)] == ["confirmee", "retiree", "confirmee"]
    assert registre.valider_chaine() is True


def test_retirer_sans_rien_de_confirme_ou_avec_des_arguments_en_trop_est_refuse(index):
    registre = registre_m4.Registre()
    (accuse, verdict), _ = _confirmer(registre, index, action="retiree", motif="rien à retirer")
    assert accuse is None and "aucune localisation confirmée à retirer" in verdict["detail"]
    _confirmer_rqa(registre, index)
    taille = registre.taille()
    (accuse, verdict), _ = _confirmer(
        registre, index, action="retiree", motif="x", adresse=ADRESSE_F001, source="rqa")
    assert accuse is None and _code(verdict) == "REJ-CONTRAT-INVALIDE"
    assert registre.taille() == taille


def test_cle_detruite_position_illisible_historique_lisible_chaine_valide(index):
    registre = registre_m4.Registre()
    _confirmer_rqa(registre, index)
    _confirmer(registre, index, adresse=ADRESSE_F001, source="manuel", latitude_microdegres=45741500,
               longitude_microdegres=-73450500, motif="correction", par="marie.fictif")
    avant = registre.lire()
    tete = registre.tete()
    # La clé du chantier est détruite (effacement cryptographique) : plus de clé, ou une autre clé.
    for cle_disponible in (None, AUTRE_CLE):
        position, verdict = localisation.position_confirmee(registre, "C1", cle_disponible)
        assert position is None and _code(verdict) == "REJ-LOCALISATION-DETRUITE"
    historique = localisation.historique(registre, "C1", None)
    assert [(h["version"], h["action"], h["confirme_par"], h["position"]) for h in historique] == [
        (1, "confirmee", "admin.fictif", None), (2, "confirmee", "marie.fictif", None)]
    assert localisation.historique(registre, "C1", AUTRE_CLE)[0]["position"] is None
    assert localisation.confirmation_courante(registre, "C1")["version"] == 2  # les métadonnées restent
    # Aucun octet de la chaîne n'a changé.
    assert registre.lire() == avant and registre.tete() == tete and registre.valider_chaine() is True


def test_adresse_changee_depuis_la_confirmation_est_a_confirmer_de_nouveau(index):
    registre = registre_m4.Registre()
    _confirmer_rqa(registre, index, adresse="8 rue Ste-Anne, St-Jean-sur-Richelieu", identifiant="f015")
    # Même adresse, écrite autrement : la position est rendue.
    position, verdict = localisation.position_confirmee(
        registre, "C1", CLE, adresse={"numero_municipal": "8", "odonyme": "Rue Sainte-Anne",
                                      "municipalite": "Saint-Jean-sur-Richelieu"})
    assert verdict is None and position["rqa_identifiant"] == "f015"
    # Une autre adresse : jamais la position d'une ancienne adresse.
    position, verdict = localisation.position_confirmee(
        registre, "C1", CLE, adresse="9 rue Ste-Anne, St-Jean-sur-Richelieu")
    assert position is None and _code(verdict) == CODE_A_CONFIRMER and "L'adresse a changé" in verdict["detail"]
    position, verdict = localisation.position_confirmee(registre, "C1", CLE, adresse="illisible")
    assert position is None and _code(verdict) == "REJ-CONTRAT-INVALIDE"


def test_l_empreinte_ecrite_ne_se_verifie_plus_sans_la_cle(index):
    registre = registre_m4.Registre()
    _confirmer_rqa(registre, index)
    [maillon] = _maillons(registre)
    adresse, _ = localisation.analyser_adresse(ADRESSE_F001)
    assert localisation.empreinte_adresse(CLE, adresse) == maillon["empreinte_adresse"]
    assert localisation.empreinte_adresse(AUTRE_CLE, adresse) != maillon["empreinte_adresse"]


# -- source rqa : la coordonnée vient de l'index, jamais des arguments -----------------------------
@pytest.mark.parametrize(("args", "code", "morceau"), [
    ({"rqa_identifiant": "inconnu"}, "REJ-CONTRAT-INVALIDE", "inconnu de l'index"),
    ({"rqa_identifiant": ""}, "REJ-CHAMP-VIDE", "rqa_identifiant"),
    ({"rqa_identifiant": None}, "REJ-CHAMP-MANQUANT", "rqa_identifiant"),
    ({"rqa_identifiant": "f003"}, "REJ-CONTRAT-INVALIDE", "EXACTEMENT"),   # l'adresse d'un autre immeuble
    ({"latitude_microdegres": 45741000, "longitude_microdegres": -73450000}, "REJ-CONTRAT-INVALIDE",
     "jamais des arguments"),
    ({"latitude_microdegres": 45741000}, "REJ-CONTRAT-INVALIDE", "jamais des arguments"),
])
def test_source_rqa_refusee_sans_rien_ecrire(index, args, code, morceau):
    registre = registre_m4.Registre()
    arguments = {"adresse": ADRESSE_F001, "source": "rqa", "rqa_identifiant": "f001", **args}
    (accuse, verdict), cle = _confirmer(registre, index, **arguments)
    assert accuse is None and _code(verdict) == code and morceau in verdict["detail"]
    assert registre.taille() == 0 and cle.appels == 0


def test_source_rqa_sans_index_est_un_verdict_qui_dit_quoi_faire():
    registre = registre_m4.Registre()
    (accuse, verdict), cle = _confirmer(
        registre, None, adresse=ADRESSE_F001, source="rqa", rqa_identifiant="f001")
    assert accuse is None and _code(verdict) == "REJ-INDEX-RQA-ABSENT"
    assert registre.taille() == 0 and cle.appels == 0


def test_code_de_municipalite_qui_contredit_l_identifiant_est_refuse(index):
    registre = registre_m4.Registre()
    adresse = {"numero_municipal": "30", "odonyme": "rue Principale", "municipalite": "Saint-Paul",
               "code_municipalite": "70040"}
    (accuse, verdict), _ = _confirmer(registre, index, adresse=adresse, source="rqa", rqa_identifiant="f012")
    assert accuse is None and "EXACTEMENT" in verdict["detail"] and registre.taille() == 0
    (accuse, verdict), _ = _confirmer(registre, index, adresse=adresse, source="rqa", rqa_identifiant="f011")
    assert verdict is None and accuse["version"] == 1


def test_un_humain_departage_un_doublon_par_l_identifiant_choisi(index):
    registre = registre_m4.Registre()
    (accuse, verdict), _ = _confirmer_rqa(
        registre, index, adresse="30 rue Principale, Saint-Paul", identifiant="f012")
    assert verdict is None and accuse["version"] == 1
    position, _ = localisation.position_confirmee(registre, "C1", CLE)
    assert (position["latitude_microdegres"], position["longitude_microdegres"]) == (47000000, -72000000)
    assert position["rqa_identifiant"] == "f012"


@pytest.mark.parametrize(("adresse", "identifiant", "precision"), [
    ("12 rue Lafleur, Repentigny", "f008", "geocodee"),
    ("14 rue Lafleur, Repentigny", "f009", "batiment"),      # bonne qualité, mais adresse non certifiée
    ("40 chemin du Lac, Repentigny", "f016", "site"),
    ("42 chemin du Lac, Repentigny", "f017", "incertaine"),
    ("9 chemin du Lac, Repentigny", "f018", "inconnue"),
])
def test_position_faible_ou_adresse_non_certifiee_exige_un_motif_puis_garde_sa_precision(
        index, adresse, identifiant, precision):
    registre = registre_m4.Registre()
    (accuse, verdict), cle = _confirmer_rqa(registre, index, adresse=adresse, identifiant=identifiant)
    assert accuse is None and _code(verdict) == "REJ-CHAMP-VIDE" and "sur place" in verdict["detail"]
    assert registre.taille() == 0 and cle.appels == 0
    (accuse, verdict), _ = _confirmer_rqa(
        registre, index, adresse=adresse, identifiant=identifiant, motif="vérifié sur place avec le client")
    assert verdict is None and accuse["precision"] == precision  # la faiblesse reste inscrite au registre
    assert _maillons(registre)[0]["motif"] == "vérifié sur place avec le client"


# -- source manuelle -------------------------------------------------------------------------------
def test_confirmation_manuelle_est_marquee_manuel(index):
    registre = registre_m4.Registre()
    (accuse, verdict), _ = _confirmer(
        registre, None, adresse="999 rue Inconnue, Repentigny", source="manuel",
        latitude_microdegres=45760000, longitude_microdegres=-73480000)
    assert verdict is None and accuse["source"] == "manuel" and accuse["precision"] == "manuel"
    [maillon] = _maillons(registre)
    assert maillon["rqa_identifiant"] is None and maillon["rqa_version"] is None
    position, _ = localisation.position_confirmee(registre, "C1", CLE)
    assert (position["latitude_microdegres"], position["longitude_microdegres"], position["source"]) == (
        45760000, -73480000, "manuel")


@pytest.mark.parametrize(("args", "code"), [
    ({}, "REJ-CHAMP-MANQUANT"),
    ({"latitude_microdegres": 45760000}, "REJ-CHAMP-MANQUANT"),
    ({"latitude_microdegres": 45.76, "longitude_microdegres": -73.48}, "REJ-CHAMP-MANQUANT"),  # degrés, pas microdegrés
    ({"latitude_microdegres": True, "longitude_microdegres": -73480000}, "REJ-CHAMP-MANQUANT"),
    ({"latitude_microdegres": -73480000, "longitude_microdegres": 45760000}, "REJ-CONTRAT-INVALIDE"),  # inversées
    ({"latitude_microdegres": 45, "longitude_microdegres": -73}, "REJ-CONTRAT-INVALIDE"),  # oubli du × 1 000 000
    ({"latitude_microdegres": 10_000_000, "longitude_microdegres": -73480000}, "REJ-CONTRAT-INVALIDE"),
    ({"latitude_microdegres": 45760000, "longitude_microdegres": -73480000, "rqa_identifiant": "f001"},
     "REJ-CONTRAT-INVALIDE"),
])
def test_confirmation_manuelle_mal_formee_refusee_sans_rien_ecrire(args, code):
    registre = registre_m4.Registre()
    (accuse, verdict), cle = _confirmer(
        registre, None, adresse="999 rue Inconnue, Repentigny", source="manuel", **args)
    assert accuse is None and _code(verdict) == code
    assert registre.taille() == 0 and cle.appels == 0


# -- validations communes --------------------------------------------------------------------------
@pytest.mark.parametrize(("chantier", "par", "action", "horodatage", "args", "code"), [
    ("", "admin.fictif", "confirmee", HORODATAGE, {}, "REJ-CHAMP-VIDE"),
    (12, "admin.fictif", "confirmee", HORODATAGE, {}, "REJ-CONTRAT-INVALIDE"),
    ("C1", "  ", "confirmee", HORODATAGE, {}, "REJ-CHAMP-VIDE"),
    ("C1", "admin.fictif", "confirmee", "hier", {}, "REJ-HORODATAGE-INVALIDE"),
    ("C1", "admin.fictif", "confirmee", "2026-09-28T10:00:00", {}, "REJ-HORODATAGE-INVALIDE"),  # sans fuseau
    ("C1", "admin.fictif", "supprimee", HORODATAGE, {}, "REJ-ENUM-INVALIDE"),
    ("C1", "admin.fictif", "confirmee", HORODATAGE, {"source": "rqa", "rqa_identifiant": "f001"}, "REJ-CHAMP-MANQUANT"),
    ("C1", "admin.fictif", "confirmee", HORODATAGE, {"adresse": ADRESSE_F001}, "REJ-ENUM-INVALIDE"),
    ("C1", "admin.fictif", "confirmee", HORODATAGE, {"adresse": ADRESSE_F001, "source": "gps"}, "REJ-ENUM-INVALIDE"),
    ("C1", "admin.fictif", "confirmee", HORODATAGE, {"adresse": "n'importe quoi", "source": "rqa"},
     "REJ-CONTRAT-INVALIDE"),
    ("C1", "admin.fictif", "confirmee", HORODATAGE,
     {"adresse": ADRESSE_F001, "source": "rqa", "rqa_identifiant": "f001", "motif": 5}, "REJ-CONTRAT-INVALIDE"),
])
def test_refus_communs_sans_ecriture_ni_cle(index, chantier, par, action, horodatage, args, code):
    registre = registre_m4.Registre()
    cle = _Cle()
    accuse, verdict = localisation.confirmer(
        registre, chantier, action, horodatage, par, index=index, fournir_cle=cle, **args)
    assert accuse is None and _code(verdict) == code
    assert registre.taille() == 0 and cle.appels == 0


def test_sans_fournisseur_de_cle_rien_n_est_ecrit_en_clair(index):
    registre = registre_m4.Registre()
    accuse, verdict = localisation.confirmer(
        registre, "C1", "confirmee", HORODATAGE, "admin.fictif", adresse=ADRESSE_F001, source="rqa",
        rqa_identifiant="f001", index=index)
    assert accuse is None and _code(verdict) == "REJ-CONTRAT-INVALIDE" and "clé de chiffrement" in verdict["detail"]
    assert registre.taille() == 0


def test_versions_independantes_par_chantier_et_chaine_commune(index):
    registre = registre_m4.Registre()
    _confirmer_rqa(registre, index, chantier="C1")
    _confirmer_rqa(
        registre, index, chantier="C2", adresse="8 rue Ste-Anne, St-Jean-sur-Richelieu", identifiant="f015")
    _confirmer_rqa(
        registre, index, chantier="C1", adresse="5 rue Principale, Belœil", identifiant="f014", motif="corrigé")
    assert [m["version"] for m in _maillons(registre, "C1")] == [1, 2]
    assert [m["version"] for m in _maillons(registre, "C2")] == [1]
    assert localisation.position_confirmee(registre, "C2", CLE)[0]["rqa_identifiant"] == "f015"
    assert localisation.position_confirmee(registre, "C1", CLE)[0]["rqa_identifiant"] == "f014"
    assert registre.valider_chaine() is True
