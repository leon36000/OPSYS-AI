import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import conformite, contrats


def _ecrire_source(repertoire, nom, contenu):
    fichier = repertoire / nom
    fichier.write_text(contenu, encoding="utf-8")
    return fichier


def test_verifier_conformite_du_vrai_paquet_est_conforme():
    resultat = conformite.verifier_conformite(_SRC / "m5_financecore")

    assert resultat["conforme"] is True
    assert resultat["violations"] == []


def test_verifier_conformite_detecte_type_mouvement_et_son_echappatoire():
    resultat = conformite.verifier_conformite(_SRC / "m5_financecore")

    entree = next(
        element
        for element in resultat["enumerees_examinees"]
        if element["nom"] == "TYPE_MOUVEMENT"
    )

    assert entree["fichier"] == "contrats.py"
    assert entree["echappatoire_trouvee"] == "AUTRE"
    assert "AUTRE" in contrats.TYPE_MOUVEMENT


def test_verifier_conformite_examine_les_quatre_familles_de_motifs():
    resultat = conformite.verifier_conformite(_SRC / "m5_financecore")
    familles_attendues = {
        "RANDOM_NON_ENSEMENCE",
        "ALEA_SYSTEME_INTERDIT",
        "HORLOGE_INTERNE",
        "RESEAU_INTERDIT",
    }

    familles_par_fichier = {}
    for motif in resultat["motifs_examines"]:
        familles_par_fichier.setdefault(motif["fichier"], set()).add(
            motif["famille"]
        )

    assert any(
        familles_attendues.issubset(familles)
        for familles in familles_par_fichier.values()
    )


def test_verifier_conformite_signale_enumere_sans_echappatoire(tmp_path):
    _ecrire_source(
        tmp_path,
        "faux_enumere.py",
        'STATUT_FAUX = ("VALEUR_A", "VALEUR_B")\n',
    )

    resultat = conformite.verifier_conformite(tmp_path)

    assert any(
        violation["code"] == "ENUMERE_SANS_ECHAPPATOIRE"
        and violation["enumere"] == "STATUT_FAUX"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_signale_horloge_interne(tmp_path):
    _ecrire_source(
        tmp_path,
        "horloge.py",
        "import datetime\n\ndatetime.datetime.now()\n",
    )

    resultat = conformite.verifier_conformite(tmp_path)

    assert any(
        violation["code"] == "HORLOGE_INTERNE"
        and violation["fichier"] == "horloge.py"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_signale_alea_non_ensemence(tmp_path):
    _ecrire_source(
        tmp_path,
        "alea.py",
        "import random\n\nrandom.random()\n",
    )

    resultat = conformite.verifier_conformite(tmp_path)

    assert any(
        violation["code"] == "RANDOM_NON_ENSEMENCE"
        and violation["fichier"] == "alea.py"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_accepte_alea_ensemence(tmp_path):
    _ecrire_source(
        tmp_path,
        "alea_ensemence.py",
        "import random\n\nGENERATEUR = random.Random(12345)\n",
    )

    resultat = conformite.verifier_conformite(tmp_path)

    assert not any(
        violation["code"] == "RANDOM_NON_ENSEMENCE"
        and violation.get("fichier") == "alea_ensemence.py"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_signale_reseau_interdit(tmp_path):
    _ecrire_source(
        tmp_path,
        "reseau.py",
        "import socket\n\nsocket.socket()\n",
    )

    resultat = conformite.verifier_conformite(tmp_path)

    assert any(
        violation["code"] == "RESEAU_INTERDIT"
        and violation["fichier"] == "reseau.py"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_signale_litteral_de_taux_en_dur(tmp_path):
    _ecrire_source(
        tmp_path,
        "taux.py",
        "taux_defaut_tps = 0.05\n",
    )

    resultat = conformite.verifier_conformite(tmp_path)

    assert any(
        violation["code"] == "LITTERAL_COUT_INTERDIT"
        and violation["fichier"] == "taux.py"
        for violation in resultat["violations"]
    )


def test_verifier_conformite_signale_litteral_de_cout_en_dur(tmp_path):
    _ecrire_source(
        tmp_path,
        "cout.py",
        "cout_unitaire_defaut = 42.0\n",
    )

    resultat = conformite.verifier_conformite(tmp_path)

    assert any(
        violation["code"] == "LITTERAL_COUT_INTERDIT"
        and violation["fichier"] == "cout.py"
        for violation in resultat["violations"]
    )


def test_verifier_aucun_import_domaine_du_vrai_paquet():
    assert conformite.verifier_aucun_import_domaine(
        _SRC / "m5_financecore"
    ) == (True, "")


def test_verifier_aucun_import_domaine_signale_import_absolu(tmp_path):
    _ecrire_source(
        tmp_path,
        "import_interdit.py",
        "import m2_revenue_crm\n",
    )

    conforme, message = conformite.verifier_aucun_import_domaine(tmp_path)

    assert conforme is False
    assert "import_interdit.py" in message
    assert "m2_revenue_crm" in message


def test_verifier_aucun_import_domaine_signale_from_absolu(tmp_path):
    _ecrire_source(
        tmp_path,
        "from_interdit.py",
        "from m4_field_ops import etats\n",
    )

    conforme, message = conformite.verifier_aucun_import_domaine(tmp_path)

    assert conforme is False
    assert "m4_field_ops" in message


def test_verifier_aucun_import_domaine_accepte_import_relatif(tmp_path):
    _ecrire_source(
        tmp_path,
        "interne.py",
        "from . import registre\n",
    )

    assert conformite.verifier_aucun_import_domaine(tmp_path) == (True, "")


def test_verifier_aucun_import_domaine_accepte_imports_stdlib_et_tiers(tmp_path):
    _ecrire_source(
        tmp_path,
        "imports_autorises.py",
        "import hashlib\nimport yaml\n",
    )

    assert conformite.verifier_aucun_import_domaine(tmp_path) == (True, "")


def test_verifier_aucune_cause_signalee_du_vrai_paquet():
    assert conformite.verifier_aucune_cause_signalee(
        _SRC / "m5_financecore"
    ) == (True, "")


def test_verifier_aucune_cause_signalee_signale_cause(tmp_path):
    _ecrire_source(
        tmp_path,
        "cause.py",
        'EVENEMENT = {"demande_id": "D1", "cause": "erreur humaine"}\n',
    )

    conforme, message = conformite.verifier_aucune_cause_signalee(tmp_path)

    assert conforme is False
    assert "cause.py" in message


def test_verifier_aucune_cause_signalee_signale_responsable(tmp_path):
    _ecrire_source(
        tmp_path,
        "responsable.py",
        'EVENEMENT = {"demande_id": "D1", "responsable": "technicien"}\n',
    )

    conforme, message = conformite.verifier_aucune_cause_signalee(tmp_path)

    assert conforme is False
    assert "responsable.py" in message


def test_verifier_aucune_cause_signalee_accepte_evenement_sans_cle_interdite(
    tmp_path,
):
    _ecrire_source(
        tmp_path,
        "evenement.py",
        'EVENEMENT = {"demande_id": "D1", "statut": "APPROUVE"}\n',
    )

    assert conformite.verifier_aucune_cause_signalee(tmp_path) == (True, "")
