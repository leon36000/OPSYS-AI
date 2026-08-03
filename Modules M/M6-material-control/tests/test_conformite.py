import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control import conformite, contrats


def test_verifier_conformite_paquet_reel_est_conforme():
    resultat = conformite.verifier_conformite(_SRC / "m6_material_control")

    assert resultat["conforme"] is True
    assert resultat["violations"] == []


def test_verifier_conformite_detecte_les_enumeres_de_domaine_m6():
    resultat = conformite.verifier_conformite(_SRC / "m6_material_control")

    enumerees = {
        entree["nom"]: entree for entree in resultat["enumerees_examinees"]
    }

    for nom in (
        "VERDICT_RESOLUTION_PRIX",
        "VERDICT_RECEPTION",
        "VERDICT_VARIANCE_STOCK",
    ):
        assert nom in enumerees
        assert enumerees[nom]["fichier"] == "contrats.py"
        assert enumerees[nom]["echappatoire_trouvee"] == "INDETERMINE"


def test_verifier_conformite_examine_les_quatre_familles_interdites():
    resultat = conformite.verifier_conformite(_SRC / "m6_material_control")

    codes = {motif["famille"] for motif in resultat["motifs_examines"]}

    assert {
        "RANDOM_NON_ENSEMENCE",
        "ALEA_SYSTEME_INTERDIT",
        "HORLOGE_INTERNE",
        "RESEAU_INTERDIT",
    }.issubset(codes)


def test_verifier_conformite_signale_enumere_sans_echappatoire(tmp_path):
    paquet = tmp_path / "faux_paquet"
    paquet.mkdir()
    (paquet / "verdicts_casses.py").write_text(
        'STATUT_FAUX = ("VALEUR_A", "VALEUR_B")\n',
        encoding="utf-8",
    )

    resultat = conformite.verifier_conformite(paquet)

    assert any(
        violation["code"] == "ENUMERE_SANS_ECHAPPATOIRE"
        and violation["enumere"] == "STATUT_FAUX"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_signale_horloge_interne(tmp_path):
    paquet = tmp_path / "faux_paquet"
    paquet.mkdir()
    (paquet / "horloge.py").write_text(
        "import datetime\n\n"
        "def maintenant():\n"
        "    return datetime.datetime.now()\n",
        encoding="utf-8",
    )

    resultat = conformite.verifier_conformite(paquet)

    assert any(
        violation["code"] == "HORLOGE_INTERNE"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_signale_alea_non_ensemence(tmp_path):
    paquet = tmp_path / "faux_paquet"
    paquet.mkdir()
    (paquet / "alea.py").write_text(
        "import random\n\n"
        "def tirer():\n"
        "    return random.random()\n",
        encoding="utf-8",
    )

    resultat = conformite.verifier_conformite(paquet)

    assert any(
        violation["code"] == "RANDOM_NON_ENSEMENCE"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_signale_reseau_interdit(tmp_path):
    paquet = tmp_path / "faux_paquet"
    paquet.mkdir()
    (paquet / "reseau.py").write_text(
        "import socket\n\n"
        "def ouvrir():\n"
        "    return socket.socket()\n",
        encoding="utf-8",
    )

    resultat = conformite.verifier_conformite(paquet)

    assert any(
        violation["code"] == "RESEAU_INTERDIT"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_signale_litteral_cout_interdit(tmp_path):
    paquet = tmp_path / "faux_paquet"
    paquet.mkdir()
    (paquet / "cout.py").write_text(
        "cout_unitaire_defaut = 42.0\n",
        encoding="utf-8",
    )

    resultat = conformite.verifier_conformite(paquet)

    assert any(
        violation["code"] == "LITTERAL_COUT_INTERDIT"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_accepte_alea_ensemence(tmp_path):
    paquet = tmp_path / "faux_paquet"
    paquet.mkdir()
    (paquet / "alea_ensemence.py").write_text(
        "import random\n\n"
        "GENERATEUR = random.Random(12345)\n",
        encoding="utf-8",
    )

    resultat = conformite.verifier_conformite(paquet)

    assert not any(
        violation["code"] == "RANDOM_NON_ENSEMENCE"
        and violation.get("fichier") == "alea_ensemence.py"
        for violation in resultat["violations"]
    )


def test_verifier_non_recalcul_hash_wct_paquet_reel():
    assert conformite.verifier_non_recalcul_hash_wct(
        _SRC / "m6_material_control"
    ) == (True, "")


def test_verifier_non_recalcul_hash_wct_signale_wct_dans_empreinte(tmp_path):
    fichier = tmp_path / "faux_hash.py"
    fichier.write_text(
        "from . import encodage\n\n"
        "def f(wct, registre):\n"
        "    return encodage.empreinte(wct)\n",
        encoding="utf-8",
    )

    conforme, message = conformite.verifier_non_recalcul_hash_wct(tmp_path)

    assert conforme is False
    assert "faux_hash.py" in message


def test_verifier_non_recalcul_hash_wct_accepte_registre_reel():
    conforme, message = conformite.verifier_non_recalcul_hash_wct(
        _SRC / "m6_material_control"
    )

    assert conforme is True
    assert message == ""


def test_verifier_non_recalcul_hash_wct_signale_wct_en_argument_nomme(tmp_path):
    fichier = tmp_path / "faux_hash_kw.py"
    fichier.write_text(
        "from . import encodage\n\n"
        "def f(wct, registre):\n"
        "    return encodage.empreinte(donnee=wct)\n",
        encoding="utf-8",
    )

    conforme, message = conformite.verifier_non_recalcul_hash_wct(tmp_path)

    assert conforme is False
    assert "faux_hash_kw.py" in message


def test_garde_ecriture_stock_paquet_reel():
    assert conformite.garde_ecriture_stock(
        _SRC / "m6_material_control"
    ) == (True, "")


def test_garde_ecriture_stock_signale_fonction_intruse(tmp_path):
    fichier = tmp_path / "faux_materiel.py"
    fichier.write_text(
        "def consommer_materiaux(registre):\n"
        "    mouvement = {\n"
        '        "type_mouvement": "CONSOMMATION",\n'
        '        "chantier_id": "X",\n'
        '        "materiau_id": "M",\n'
        '        "quantite": 1,\n'
        '        "cout_unitaire": None,\n'
        "    }\n"
        "    return registre.ajouter(mouvement)\n\n"
        "def fonction_intruse(registre):\n"
        "    mouvement = {\n"
        '        "type_mouvement": "CONSOMMATION",\n'
        '        "chantier_id": "X",\n'
        '        "materiau_id": "M",\n'
        '        "quantite": 1,\n'
        '        "cout_unitaire": None,\n'
        "    }\n"
        "    return registre.ajouter(mouvement)\n",
        encoding="utf-8",
    )

    conforme, message = conformite.garde_ecriture_stock(tmp_path)

    assert conforme is False
    assert "fonction_intruse" in message
    assert "CONSOMMATION" in message


def test_garde_ecriture_stock_signale_litteral_en_portee_module(tmp_path):
    fichier = tmp_path / "mouvement_defaut.py"
    fichier.write_text(
        "MOUVEMENT_PAR_DEFAUT = {\n"
        '    "type_mouvement": "RECEPTION",\n'
        '    "chantier_id": "X",\n'
        '    "materiau_id": "M",\n'
        '    "quantite": 1,\n'
        '    "cout_unitaire": None,\n'
        "}\n",
        encoding="utf-8",
    )

    conforme, message = conformite.garde_ecriture_stock(tmp_path)

    assert conforme is False
    assert "portée module" in message


def test_garde_ecriture_stock_accepte_bon_type_dans_bonne_fonction(tmp_path):
    fichier = tmp_path / "reception.py"
    fichier.write_text(
        "def enregistrer_reception(registre):\n"
        "    mouvement = {\n"
        '        "type_mouvement": "RECEPTION",\n'
        '        "chantier_id": "X",\n'
        '        "materiau_id": "M",\n'
        '        "quantite": 1,\n'
        '        "cout_unitaire": None,\n'
        "    }\n"
        "    return registre.ajouter(mouvement)\n",
        encoding="utf-8",
    )

    assert conformite.garde_ecriture_stock(tmp_path) == (True, "")


def test_garde_ecriture_stock_accepte_helper_imbrique_dans_bonne_fonction(tmp_path):
    fichier = tmp_path / "reception_imbriquee.py"
    fichier.write_text(
        "def enregistrer_reception(registre):\n"
        "    def _construire_mouvement():\n"
        "        return {\n"
        '            "type_mouvement": "RECEPTION",\n'
        '            "chantier_id": "X",\n'
        '            "materiau_id": "M",\n'
        '            "quantite": 1,\n'
        '            "cout_unitaire": None,\n'
        "        }\n"
        "    return registre.ajouter(_construire_mouvement())\n",
        encoding="utf-8",
    )

    assert conformite.garde_ecriture_stock(tmp_path) == (True, "")


def test_constantes_verdicts_contrats_completes_et_avec_indetermine():
    assert contrats.VERDICT_RESOLUTION_PRIX == (
        "PRIX_CATALOGUE", "PRIX_HISTORIQUE_FALLBACK", "INDETERMINE",
    )
    assert contrats.VERDICT_RECEPTION == (
        "CONFORME", "RECEPTION_INFERIEURE", "RECEPTION_SUPERIEURE",
        "RECEPTION_MIXTE", "INDETERMINE",
    )
    assert contrats.VERDICT_VARIANCE_STOCK == (
        "AUCUN_ECART", "STOCK_INFERIEUR_AU_THEORIQUE",
        "STOCK_SUPERIEUR_AU_THEORIQUE", "INDETERMINE",
    )
    assert contrats.VERDICT_INDETERMINE == "INDETERMINE"
    for enumere in (
        contrats.VERDICT_RESOLUTION_PRIX,
        contrats.VERDICT_RECEPTION,
        contrats.VERDICT_VARIANCE_STOCK,
    ):
        assert "INDETERMINE" in enumere
