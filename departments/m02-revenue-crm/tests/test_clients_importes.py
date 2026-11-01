"""Clients importés à l'onboarding (`clients_importes.py`) : en-tête, normalisation, dédoublonnage expliqué, fiche
définitive. Personnes, courriels, téléphones et adresses fictifs (AGENTS.md)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from m2_revenue_crm import clients, clients_importes
from m2_revenue_crm.registre import Registre

FICTIF = True
CSV = (Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ingestion_onboarding" / "clients.csv")
QUAND = "2026-10-31T10:00:00-04:00"


def _lignes(texte: str, separateur: str = ","):
    return [{"separateur": separateur, "lignes": list(csv.reader(io.StringIO(texte), delimiter=separateur))}]


@pytest.fixture
def lecture():
    lu, raison = clients_importes.lire_lignes(_lignes(CSV.read_text(encoding="utf-8")))
    assert raison is None
    return lu


def test_l_entete_est_reconnue_en_francais_et_en_anglais_a_n_importe_quelle_des_dix_premieres_lignes():
    assert clients_importes.reperer_entete([["Nom", "Courriel"]]) == (0, {"nom": 0, "courriel": 1})
    assert clients_importes.reperer_entete([["Rapport fictif"], [], ["Full Name", "Phone", "City"]]) == (
        2, {"nom": 0, "telephone": 1, "ville": 2})
    assert clients_importes.reperer_entete([["Prénom", "Nom de famille", "E-mail"]])[1] == {
        "prenom": 0, "nom_famille": 1, "courriel": 2}
    assert clients_importes.reperer_entete([["Nom", "Ville"]]) is None, "un nom seul ne fait pas une liste de clients"
    lu, raison = clients_importes.lire_lignes(_lignes("Produit;Prix\nSolin;3\n", ";"))
    assert lu is None and raison["code"] == "REJ-ING-CLIENT-ENTETE-INTROUVABLE"


def test_prenom_et_nom_de_famille_forment_le_nom_et_une_ligne_sans_nom_est_refusee():
    lu, _ = clients_importes.lire_lignes(_lignes("Prénom,Nom de famille,Courriel\nAnne,Fictive,a@exemple.test\n,,"
                                                 "b@exemple.test\n\n"))
    assert [ligne["champs"]["nom"] for ligne in lu["lignes"]] == ["Anne Fictive"]
    assert lu["refusees"] == [{"ligne": 3, "code": "REJ-ING-CLIENT-NOM-ABSENT", "detail": "ligne sans nom de client"}]


@pytest.mark.parametrize(("fonction", "entree", "attendu"), [
    (clients_importes.normaliser_nom, "Toitures Bédard (fictif) inc.", "toitures bedard fictif"),
    (clients_importes.normaliser_nom, "A & B Rénovation Ltée", "a et b renovation"),
    (clients_importes.normaliser_courriel, " Marie.Tremblay@Exemple.TEST ", "marie.tremblay@exemple.test"),
    (clients_importes.normaliser_courriel, "marie@exemple", None),
    (clients_importes.normaliser_telephone, "1-514-555-0101 poste 22", "+15145550101"),
    (clients_importes.normaliser_telephone, "(514) 555-0101", "+15145550101"),
    (clients_importes.normaliser_telephone, "555-0101", None),
    (clients_importes.normaliser_telephone, "014-555-0101", None),
    (clients_importes.normaliser_code_postal, "h2x1y4", "H2X 1Y4"),
    (clients_importes.normaliser_code_postal, "D2X 1Y4", None),
])
def test_normalisations(fonction, entree, attendu):
    assert fonction(entree) == attendu


def test_adresse_abreviations_et_accents():
    assert clients_importes.normaliser_adresse("45 Boulevard Saint-Fictif") == clients_importes.normaliser_adresse(
        "45 boul. St-Fictif")


def test_le_corpus_se_regroupe_par_regles_fortes_avec_explications(lecture):
    groupes, fusions, signalements = clients_importes.regrouper(lecture["lignes"])
    assert [[lecture["lignes"][i]["ligne"] for i in g] for g in groupes] == [[2, 3], [4, 5], [6, 7], [8], [9]]
    # Une fusion par paire, la règle la plus forte d'abord (courriel, puis téléphone et nom, puis nom et adresse).
    assert [(f["regle"], f["lignes"]) for f in fusions] == [
        ("courriel_identique", [2, 3]), ("telephone_et_nom", [4, 5]), ("telephone_et_nom", [6, 7])]
    assert fusions[0]["valeur_normalisee"] == "marie.tremblay@exemple.test"
    assert [(s["regle"], s["lignes"]) for s in signalements] == [("telephone_seul", [8, 9])]


def test_les_fiches_proposees_disent_leur_statut_et_leurs_raisons(lecture):
    fiches = clients_importes.proposer_fiches(lecture["lignes"])
    resume = [(f["lignes"], f["statut"], sorted(r["code"] for r in f["raisons"])) for f in fiches]
    assert resume == [
        ([2, 3], "PRET", []),
        ([4, 5], "PRET", []),
        ([6, 7], "A_VERIFIER", ["REJ-ING-CLIENT-CONFLIT"]),
        ([8], "A_VERIFIER", ["REJ-ING-CLIENT-COURRIEL-INVALIDE", "REJ-ING-CLIENT-DOUBLON-PROBABLE"]),
        ([9], "A_VERIFIER", ["REJ-ING-CLIENT-DOUBLON-PROBABLE"]),
    ]
    toitures = fiches[2]
    assert toitures["champs"]["courriel"]["valeurs"] == ["info@toitures-bedard.test", "ventes@toitures-bedard.test"]
    assert toitures["champs"]["nom"]["conflit"] is False, "même nom une fois normalisé : pas un conflit"
    jean = fiches[1]
    assert jean["champs"]["courriel"] == {"valeur": "jean.gagnon@exemple.test",
                                          "valeurs": ["jean.gagnon@exemple.test"], "conflit": False}
    assert len({f["cle_metier"] for f in fiches}) == len(fiches)


def test_le_meme_fichier_donne_les_memes_fiches(lecture):
    assert clients_importes.proposer_fiches(lecture["lignes"]) == clients_importes.proposer_fiches(lecture["lignes"])


def test_deux_personnes_au_meme_nom_sans_autre_lien_ne_sont_jamais_fusionnees():
    lu, _ = clients_importes.lire_lignes(_lignes("Nom,Téléphone,Adresse\nPaul Fictif,514-555-0111,1 rue A\n"
                                                 "Paul Fictif,450-555-0222,2 rue B\n"))
    fiches = clients_importes.proposer_fiches(lu["lignes"])
    assert len(fiches) == 2 and all(f["statut"] == "A_VERIFIER" for f in fiches)
    assert {r["code"] for f in fiches for r in f["raisons"]} == {"REJ-ING-CLIENT-DOUBLON-PROBABLE"}


def test_fiche_definitive_par_un_humain_identifiant_du_client_360(lecture):
    fiches = clients_importes.proposer_fiches(lecture["lignes"])
    registre = Registre()
    source = {"lot_id": "a" * 32, "lignes": [2, 3]}
    resultat, verdict = clients_importes.importer_client(fiches[0], None, par="nathan", role="nathan_owner",
                                                         voie="approbation", horodatage=QUAND, source=source,
                                                         registre_cible=registre)
    assert verdict is None
    maillon = resultat["maillon"]
    assert maillon["contact"] == {"nom": "Marie Tremblay (fictive)", "telephone": "+15145550101",
                                  "courriel": "marie.tremblay@exemple.test"}
    assert maillon["code_postal"] == "H2X 1Y4" and maillon["voie"] == "approbation"
    assert resultat["client_id"] == clients.identifiant_client({"contact": maillon["contact"]})
    assert registre.valider_chaine()
    _, refus = clients_importes.importer_client(fiches[0], None, par="nathan", role="nathan_owner",
                                                voie="approbation", horodatage=QUAND, source=source,
                                                registre_cible=registre)
    assert refus["code"] == "REJ-CLIENT-DEJA-IMPORTE" and registre.taille() == 1
    # Les clés fortes de la fiche définitive (valeurs normalisées) recouvrent celles du brouillon : le socle ne la
    # reproposera pas à un dépôt suivant.
    assert set(clients_importes.empreintes_du_client(maillon)) == set(fiches[0]["cles"])


@pytest.mark.parametrize(("index", "choix", "code"), [
    (2, None, "REJ-CLIENT-IMPORT-CHOIX-INVALIDE"),
    (2, {"courriel": "autre@exemple.test"}, "REJ-CLIENT-IMPORT-CHOIX-INVALIDE"),
    (2, {"inconnu": "x"}, "REJ-CLIENT-IMPORT-CHOIX-INVALIDE"),
    (3, None, "REJ-CLIENT-IMPORT-INVALIDE"),
])
def test_conflit_sans_choix_ou_valeur_mal_formee_jamais_validee(lecture, index, choix, code):
    fiches = clients_importes.proposer_fiches(lecture["lignes"])
    registre = Registre()
    _, verdict = clients_importes.importer_client(fiches[index], choix, par="nathan", role="nathan_owner",
                                                  voie="approbation", horodatage=QUAND, source={},
                                                  registre_cible=registre)
    assert verdict["code"] == code and registre.taille() == 0


def test_conflit_resolu_par_un_choix_observe(lecture):
    fiches = clients_importes.proposer_fiches(lecture["lignes"])
    registre = Registre()
    resultat, verdict = clients_importes.importer_client(
        fiches[2], {"courriel": "ventes@toitures-bedard.test"}, par="nathan", role="nathan_owner",
        voie="approbation", horodatage=QUAND, source={}, registre_cible=registre)
    assert verdict is None and resultat["maillon"]["contact"]["courriel"] == "ventes@toitures-bedard.test"


@pytest.mark.parametrize(("par", "voie", "horodatage", "code"), [
    ("nathan", "agent", QUAND, "REJ-HUMAIN-REQUIS"),
    ("", "approbation", QUAND, "REJ-HUMAIN-REQUIS"),
    ("nathan", "approbation", "2026-10-31T10:00:00", "REJ-HORODATAGE-INVALIDE"),
])
def test_seul_un_humain_identifie_cree_une_fiche(lecture, par, voie, horodatage, code):
    fiches = clients_importes.proposer_fiches(lecture["lignes"])
    registre = Registre()
    _, verdict = clients_importes.importer_client(fiches[0], None, par=par, role="admin", voie=voie,
                                                  horodatage=horodatage, source={}, registre_cible=registre)
    assert verdict["code"] == code and registre.taille() == 0


def test_catalogue_des_raisons_ferme():
    with pytest.raises(ValueError):
        clients_importes._raison("REJ-INVENTE", "x")
