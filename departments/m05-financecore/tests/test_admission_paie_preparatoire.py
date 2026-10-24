"""Fixtures FICTIVES : l'identité documentaire n'est pas une validation fiscale."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

FICTIF = True
CODE = "a" * 64
PARAMETRES = "b" * 64
IDS = ("arc_jan2026", "arc_jul2026", "rq_f2026", "rq_tr26_2026")


def _configuration(tmp_path):
    sources = {}
    for identifiant in IDS:
        corps = b"%PDF-1.7\nFICTIF - NOT AN OFFICIAL DOCUMENT\n" + identifiant.encode()
        (tmp_path / f"{identifiant}.pdf").write_bytes(corps)
        sources[identifiant] = {"capture": f"{identifiant}.pdf", "sha256": sha256(corps).hexdigest(), "format": "PDF"}
    return {
        "schema": "opsys.admission-paie-preparatoire/v1",
        "qualification_regles": "NON_QUALIFIEE_POUR_PAIE",
        "actions_financieres_bloquees": True,
        "annee": 2026, "juridiction": "QC", "frequence": "bihebdomadaire", "periodes_annuelles": 26, "pm": 12,
        "fenetres": [
            {"debut": "2026-01-01", "fin": "2026-06-30", "periode_min": 1, "periode_max": 1,
             "methode": "P1", "calculateur_sha256": CODE, "parametres_sha256": PARAMETRES},
            {"debut": "2026-01-01", "fin": "2026-06-30", "periode_min": 2, "periode_max": 26,
             "methode": "YTD", "calculateur_sha256": CODE, "parametres_sha256": PARAMETRES},
            {"debut": "2026-07-01", "fin": "2026-12-31", "periode_min": 2, "periode_max": 26,
             "methode": "YTD", "calculateur_sha256": CODE, "parametres_sha256": PARAMETRES},
        ],
        "sources": sources,
    }


def _contexte(**modifications):
    return {"annee": 2026, "date_paie": "2026-10-23", "juridiction": "QC", "frequence": "bihebdomadaire",
            "periode_annuelle": 22, "pm": 12, **modifications}


def _verifier(tmp_path, configuration, contexte=None, **empreintes):
    # Import dans le test : le rouge initial constate l'API absente, pas une collecte brisée.
    from m5_financecore.admission_paie_preparatoire import verifier_admission_preparatoire

    return verifier_admission_preparatoire(
        racine_captures=tmp_path, capacite=configuration,
        contexte=_contexte() if contexte is None else contexte,
        empreinte_calculateur=empreintes.get("code", CODE),
        empreinte_parametres=empreintes.get("parametres", PARAMETRES),
    )


def test_documents_fictifs_compatibles_ne_qualifient_ni_regles_ni_paie(tmp_path):
    configuration = _configuration(tmp_path)
    original = deepcopy(configuration)
    resultat = _verifier(tmp_path, configuration)
    assert resultat["admissible"] is True
    assert set(resultat["sources_verifiees"]) == set(IDS)
    assert resultat["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert resultat["actions_financieres_bloquees"] is True
    assert resultat["autorisation_outil_ou_acteur"] is False
    assert configuration == original


def test_janvier_ne_reclame_pas_le_document_juillet(tmp_path):
    configuration = _configuration(tmp_path)
    (tmp_path / "arc_jul2026.pdf").unlink()
    resultat = _verifier(tmp_path, configuration, _contexte(date_paie="2026-01-16", periode_annuelle=2))
    assert resultat["admissible"] is True
    assert set(resultat["sources_verifiees"]) == set(IDS) - {"arc_jul2026"}


@pytest.mark.parametrize("modification", [
    {"annee": 2027}, {"periode_annuelle": True}, {"periode_annuelle": 27},
    {"date_paie": "2026-1-16"}, {"frequence": "hebdomadaire"}, {"pm": 11},
    {"date_paie": "2026-07-01", "periode_annuelle": 1},
])
def test_contexte_hors_capacite_est_refuse(tmp_path, modification):
    resultat = _verifier(tmp_path, _configuration(tmp_path), _contexte(**modification))
    assert resultat["admissible"] is False
    assert resultat["motifs"] == ["CONTEXTE_HORS_CAPACITE"]


@pytest.mark.parametrize("cle", ["code", "parametres"])
def test_snapshot_modifie_est_refuse_avant_toute_lecture_capture(tmp_path, cle):
    configuration = _configuration(tmp_path)
    for p in tmp_path.glob("*.pdf"):
        p.unlink()
    resultat = _verifier(tmp_path, configuration, **{cle: "c" * 64})
    assert resultat["motifs"] == ["SNAPSHOT_INCOMPATIBLE"]
    assert resultat["sources_verifiees"] == []


@pytest.mark.parametrize("changement", ["manquante", "hash", "type", "chemin", "lien", "repertoire_lie", "taille"])
def test_capture_absente_modifiee_ou_non_confinee_bloque(tmp_path, changement):
    configuration = _configuration(tmp_path)
    source = configuration["sources"]["rq_f2026"]
    pdf = tmp_path / source["capture"]
    if changement == "manquante":
        pdf.unlink()
    elif changement == "hash":
        pdf.write_bytes(b"%PDF-1.7\nALTERED FICTIF")
    elif changement == "type":
        corps = b"<html>FICTIF not PDF</html>"
        pdf.write_bytes(corps)
        source["sha256"] = sha256(corps).hexdigest()
    elif changement == "chemin":
        source["capture"] = "../outside.pdf"
    elif changement == "lien":
        cible = tmp_path / "fictif-autre.pdf"
        pdf.rename(cible)
        pdf.symlink_to(cible)
    elif changement == "repertoire_lie":
        (tmp_path / "lien").symlink_to(tmp_path, target_is_directory=True)
        source["capture"] = "lien/" + source["capture"]
    else:
        with pdf.open("r+b") as fichier:
            fichier.truncate(16 * 1024 * 1024 + 1)
    resultat = _verifier(tmp_path, configuration)
    assert resultat["admissible"] is False
    assert any(m.startswith("rq_f2026:") for m in resultat["motifs"])
    assert resultat["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"


@pytest.mark.parametrize("changement", ["qualification", "actions", "frequence_implicite", "fenetre_dupliquee"])
def test_configuration_ne_peut_pas_etendre_la_portee_ou_qualifier_les_regles(tmp_path, changement):
    configuration = _configuration(tmp_path)
    if changement == "qualification":
        configuration["qualification_regles"] = "QUALIFIEE"
    elif changement == "actions":
        configuration["actions_financieres_bloquees"] = False
    elif changement == "frequence_implicite":
        configuration["frequence"] = None
    else:
        configuration["fenetres"].append(deepcopy(configuration["fenetres"][2]))
    resultat = _verifier(tmp_path, configuration)
    assert resultat["admissible"] is False
    assert resultat["motifs"] == ["CAPACITE_INVALIDE"]


def test_chemin_point_est_refuse_sans_exception(tmp_path):
    configuration = _configuration(tmp_path)
    configuration["sources"]["rq_f2026"]["capture"] = "."
    resultat = _verifier(tmp_path, configuration)
    assert resultat["admissible"] is False
    assert "rq_f2026:CHEMIN_NON_CONFINE" in resultat["motifs"]


@pytest.mark.parametrize("jour,periode,edition", [
    ("2026-01-16", 1, "T4127-122-2026-01"),
    ("2026-01-30", 2, "T4127-122-2026-01"),
    ("2026-10-23", 22, "T4127-123-2026-07"),
])
def test_snapshot_public_sans_calcul_monetaire(monkeypatch, jour, periode, edition):
    from m5_financecore import impot_federal_qc_2026 as federal
    from m5_financecore.impot_federal_qc_2026 import obtenir_snapshot_retenue_federale_qc_preparatoire

    def interdit(**_arguments):
        pytest.fail("Un snapshot documentaire ne doit pas lancer les calculateurs monétaires")

    monkeypatch.setattr(federal, "calculer_paie_qc_preparatoire", interdit)
    resultat, refus = obtenir_snapshot_retenue_federale_qc_preparatoire(
        contexte=_contexte(date_paie=jour, periode_annuelle=periode),
    )
    assert refus is None
    assert resultat["parametres"]["edition"] == edition
    assert resultat["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert resultat["actions_financieres_bloquees"] is True
    assert resultat["autorisation_outil_ou_acteur"] is False
    if periode == 1:
        assert resultat["hash_parametres"] == federal.HASH_PARAMETRES
    else:
        assert resultat["parametres"]["methode_credits"] == "CUMULS_PLUS_PERIODES_RESTANTES"


@pytest.mark.parametrize("modification", [
    {"date_paie": "2026-02-30"}, {"date_paie": "2026-1-16"},
    {"date_paie": "2026-07-01", "periode_annuelle": 1},
    {"periode_annuelle": True}, {"annee": 2027}, {"frequence": "hebdomadaire"},
    {"pm": 11}, {"juridiction": "ON"}, {"revenu_brut_emploi": "100.00"},
])
def test_snapshot_public_refuse_contexte_non_supporte(modification):
    from m5_financecore.impot_federal_qc_2026 import obtenir_snapshot_retenue_federale_qc_preparatoire

    resultat, refus = obtenir_snapshot_retenue_federale_qc_preparatoire(contexte=_contexte(**modification))
    assert resultat is None
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


def test_snapshot_public_retourne_copie_independante():
    from m5_financecore.impot_federal_qc_2026 import obtenir_snapshot_retenue_federale_qc_preparatoire

    premier, refus = obtenir_snapshot_retenue_federale_qc_preparatoire(contexte=_contexte())
    assert refus is None
    empreinte = premier["hash_parametres"]
    premier["parametres"]["K2Q"]["maximum_ei_qc"] = "0.00"
    suivant, refus = obtenir_snapshot_retenue_federale_qc_preparatoire(contexte=_contexte())
    assert refus is None
    assert suivant["parametres"]["K2Q"]["maximum_ei_qc"] == "895.70"
    assert suivant["hash_parametres"] == empreinte


def test_pont_lie_snapshot_reel_au_lieu_du_hash_fourni_dans_configuration(tmp_path):
    from m5_financecore.admission_paie_preparatoire import verifier_admission_federale_preparatoire
    from m5_financecore.impot_federal_qc_2026 import obtenir_snapshot_retenue_federale_qc_preparatoire

    configuration = _configuration(tmp_path)
    # Le hash fictif de configuration ne remplace pas celui du propriétaire réel.
    refus = verifier_admission_federale_preparatoire(
        racine_captures=tmp_path, capacite=configuration, contexte=_contexte(), empreinte_calculateur=CODE,
    )
    assert refus["admissible"] is False
    assert refus["motifs"] == ["SNAPSHOT_INCOMPATIBLE"]
    snapshot, erreur = obtenir_snapshot_retenue_federale_qc_preparatoire(contexte=_contexte())
    assert erreur is None
    configuration["fenetres"][2]["parametres_sha256"] = snapshot["hash_parametres"]
    resultat = verifier_admission_federale_preparatoire(
        racine_captures=tmp_path, capacite=configuration, contexte=_contexte(), empreinte_calculateur=CODE,
    )
    # Documents toujours FICTIFS : identité compatible seulement, aucune autorité.
    assert resultat["admissible"] is True
    assert resultat["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert resultat["actions_financieres_bloquees"] is True
    assert resultat["autorisation_outil_ou_acteur"] is False


def _configuration_serveur(tmp_path):
    from m5_financecore import impot_federal_qc_2026 as federal

    noms = ("__init__.py", "contrats.py", "validation.py", "cotisations_rrq_regulieres.py",
            "cotisations_rqap_ae_2026.py", "impot_quebec_regulier.py", "paie_qc_preparatoire.py",
            "impot_federal_qc_2026.py")
    racine = Path(federal.__file__).parent
    fichiers = {n: sha256((racine / n).read_bytes()).hexdigest() for n in noms}
    generation = sha256(json.dumps(fichiers, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    capacite = _configuration(tmp_path)
    for fenetre, jour, periode in zip(capacite["fenetres"],
                                     ("2026-01-16", "2026-01-30", "2026-10-23"), (1, 2, 22), strict=True):
        snapshot, refus = federal.obtenir_snapshot_retenue_federale_qc_preparatoire(
            contexte=_contexte(date_paie=jour, periode_annuelle=periode),
        )
        assert refus is None
        fenetre["calculateur_sha256"] = generation
        fenetre["parametres_sha256"] = snapshot["hash_parametres"]
    return {"schema": "opsys.admission-paie-serveur/v1",
            "generation": {"fichiers": fichiers, "sha256": generation}, "capacite": capacite}


def test_serveur_epingle_generation_reelle_et_snapshot_sans_accorder_autorite(tmp_path):
    from m5_financecore.admission_paie_preparatoire import verifier_admission_serveur_preparatoire

    config = tmp_path / "configuration.json"
    config.write_text(json.dumps(_configuration_serveur(tmp_path)))
    resultat = verifier_admission_serveur_preparatoire(
        chemin_configuration=config, racine_captures=tmp_path, contexte=_contexte(),
    )
    assert resultat["admissible"] is True  # captures FICTIVES : identité seulement
    assert resultat["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert resultat["actions_financieres_bloquees"] is True
    assert resultat["autorisation_outil_ou_acteur"] is False


@pytest.mark.parametrize("changement", ["absente", "duplicata", "generation", "lien", "origine", "taille", "profond"])
def test_serveur_refuse_config_generation_ou_origine_avant_snapshot(tmp_path, monkeypatch, changement):
    from m5_financecore import impot_federal_qc_2026 as federal
    from m5_financecore.admission_paie_preparatoire import verifier_admission_serveur_preparatoire

    config = tmp_path / "configuration.json"
    donnees = _configuration_serveur(tmp_path)
    if changement == "generation":
        donnees["generation"]["fichiers"]["contrats.py"] = "f" * 64
    config.write_text(json.dumps(donnees))
    if changement == "absente":
        config.unlink()
    elif changement == "duplicata":
        config.write_text('{"schema":"fictif","schema":"double"}')
    elif changement == "lien":
        cible = tmp_path / "autre.json"
        config.rename(cible)
        config.symlink_to(cible)
    elif changement == "origine":
        monkeypatch.setattr(federal, "__file__", str(tmp_path / "federal-etranger.py"))
    elif changement == "taille":
        config.write_text(" " * (64 * 1024 + 1))
    elif changement == "profond":
        config.write_text("[" * 20000 + "0" + "]" * 20000)

    def interdit(**_arguments):
        pytest.fail("Snapshot appelé avant validation de la configuration/génération serveur")

    monkeypatch.setattr(federal, "obtenir_snapshot_retenue_federale_qc_preparatoire", interdit)
    resultat = verifier_admission_serveur_preparatoire(
        chemin_configuration=config, racine_captures=tmp_path, contexte=_contexte(),
    )
    assert resultat["admissible"] is False
    assert resultat["motifs"]


def test_serveur_refuse_remplacement_config_meme_octets_pendant_controle(tmp_path, monkeypatch):
    from m5_financecore import admission_paie_preparatoire as admission

    config = tmp_path / "configuration.json"
    config.write_text(json.dumps(_configuration_serveur(tmp_path)))
    original = admission.verifier_admission_federale_preparatoire

    def remplacer(**arguments):
        resultat = original(**arguments)
        assert resultat["admissible"] is True  # identité documentaire FICTIVE seulement
        remplacement = tmp_path / "remplacement.json"
        remplacement.write_bytes(config.read_bytes())
        remplacement.replace(config)
        return resultat

    monkeypatch.setattr(admission, "verifier_admission_federale_preparatoire", remplacer)
    resultat = admission.verifier_admission_serveur_preparatoire(
        chemin_configuration=config, racine_captures=tmp_path, contexte=_contexte(),
    )
    assert resultat["admissible"] is False
    assert resultat["motifs"] == ["CONFIGURATION_OU_GENERATION_SERVEUR_INDISPONIBLE"]
