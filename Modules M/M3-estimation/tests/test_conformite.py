from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path

import pytest


RACINE_MODULE = Path(__file__).resolve().parents[1]
RACINE_SRC = RACINE_MODULE / "src"
if str(RACINE_SRC) not in sys.path:
    sys.path.insert(0, str(RACINE_SRC))

from m3_estimation import conformite, digest


def _ecrire_source(repertoire: Path, nom: str, contenu: str) -> Path:
    """Écrit un module Python local servant exclusivement de cible AST."""
    chemin = repertoire / nom
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def _codes(resultat: dict) -> set[str]:
    """Extrait les codes stables d'un rapport de conformité."""
    assert isinstance(resultat, dict)
    assert "violations" in resultat
    assert isinstance(resultat["violations"], list)
    return {violation["code"] for violation in resultat["violations"]}


def _verifier(repertoire: Path) -> dict:
    """Exécute l'API publique de conformité et verrouille son contrat minimal."""
    resultat = conformite.verifier_conformite(repertoire)
    assert isinstance(resultat, dict)
    assert isinstance(resultat.get("conforme"), bool)
    assert isinstance(resultat.get("enumerees_examinees"), list)
    assert isinstance(resultat.get("motifs_examines"), list)
    assert isinstance(resultat.get("limites"), list)
    return resultat


def _registre(maillons: list[dict]) -> object:
    """Fabrique un registre lecture-seule dont les lectures sont comptabilisées."""

    class RegistreLectureSeule:
        def __init__(self, entrees: list[dict]) -> None:
            self.entrees = entrees
            self.nombre_lectures = 0

        def lire(self) -> tuple[dict, ...]:
            self.nombre_lectures += 1
            return tuple(self.entrees)

    return RegistreLectureSeule(maillons)


def test_listes_de_champs_exclues_et_enumeres_de_domaine_declares(tmp_path: Path) -> None:
    """Verrouille que CA-M3-19 vise les énumérés déclarés, jamais les noms de champs."""
    _ecrire_source(
        tmp_path,
        "contrats.py",
        """
CHAMPS_CONTACT = ("nom", "telephone", "courriel")
TYPES_TRAVAUX = ("renovation_totale", "autre")
VERDICTS_ESTIMATION = ("AUCUN_BLOCAGE", "INDETERMINE")
# Dérivé PAR INDICE, exactement comme le vrai contrats.py — c'est ce qui rend ce
# cas discriminant. Sans cette ligne, la fixture référençait un nom qu'elle ne
# définissait pas : le contrôle abandonnait, à raison, sur une référence
# irrésoluble. La fixture éprouvait alors l'abandon, jamais la résolution.
VERDICT_INDETERMINE = VERDICTS_ESTIMATION[1]
""",
    )
    _ecrire_source(
        tmp_path,
        "hierarchie.py",
        """
from . import contrats
NIVEAUX_CONFIANCE = ("REFERENCE_ECHELLE", contrats.VERDICT_INDETERMINE)
""",
    )

    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is True
    enumerees = {element["nom"]: element for element in resultat["enumerees_examinees"]}
    assert "CHAMPS_CONTACT" not in enumerees
    assert enumerees["TYPES_TRAVAUX"]["echappatoire_attendue"] == "autre"
    assert enumerees["TYPES_TRAVAUX"]["echappatoire_trouvee"] == "autre"
    assert enumerees["VERDICTS_ESTIMATION"]["echappatoire_attendue"] == "INDETERMINE"
    assert enumerees["NIVEAUX_CONFIANCE"]["echappatoire_trouvee"] == "INDETERMINE"
    assert "ENUMERE_SANS_ECHAPPATOIRE" not in _codes(resultat)


def test_type_travaux_sans_autre_est_refuse_explicitement(tmp_path: Path) -> None:
    """Verrouille la décision visible : TYPES_TRAVAUX utilise explicitement « autre »."""
    _ecrire_source(
        tmp_path,
        "contrats.py",
        """
TYPES_TRAVAUX = ("renovation_totale", "extension")
VERDICTS_ESTIMATION = ("AUCUN_BLOCAGE", "INDETERMINE")
""",
    )
    _ecrire_source(
        tmp_path,
        "hierarchie.py",
        """
NIVEAUX_CONFIANCE = ("REFERENCE_ECHELLE", "INDETERMINE")
""",
    )

    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is False
    assert "ENUMERE_SANS_ECHAPPATOIRE" in _codes(resultat)
    violation = next(
        entree
        for entree in resultat["violations"]
        if entree["code"] == "ENUMERE_SANS_ECHAPPATOIRE"
        and entree["enumere"] == "TYPES_TRAVAUX"
    )
    assert violation["echappatoire_attendue"] == "autre"


def test_reference_d_echappatoire_est_resolue_depuis_contrats(tmp_path: Path) -> None:
    """Verrouille la résolution AST de contrats.VERDICT_INDETERMINE, non son seul littéral."""
    _ecrire_source(
        tmp_path,
        "contrats.py",
        """
VERDICT_INDETERMINE = "INDETERMINE"
VERDICTS_ESTIMATION = ("AUCUN_BLOCAGE", VERDICT_INDETERMINE)
TYPES_TRAVAUX = ("autre",)
""",
    )
    _ecrire_source(
        tmp_path,
        "hierarchie.py",
        """
from . import contrats
NIVEAUX_CONFIANCE = (
    "REFERENCE_ECHELLE",
    contrats.VERDICT_INDETERMINE,
)
""",
    )

    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is True
    niveaux = next(
        entree
        for entree in resultat["enumerees_examinees"]
        if entree["nom"] == "NIVEAUX_CONFIANCE"
    )
    assert niveaux["echappatoire_trouvee"] == "INDETERMINE"
    assert niveaux["references_resolues"] == ["contrats.VERDICT_INDETERMINE"]


def test_reference_d_enumere_non_resoluble_echoue_ferme(tmp_path: Path) -> None:
    """Verrouille qu'une référence inconnue interdit le vert plutôt que masquer D-032."""
    _ecrire_source(
        tmp_path,
        "contrats.py",
        """
TYPES_TRAVAUX = ("autre",)
VERDICTS_ESTIMATION = ("AUCUN_BLOCAGE", "INDETERMINE")
""",
    )
    _ecrire_source(
        tmp_path,
        "hierarchie.py",
        """
NIVEAUX_CONFIANCE = ("REFERENCE_ECHELLE", contrats.VERDICT_INDETERMINE)
""",
    )

    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is False
    assert "REFERENCE_ENUMERE_NON_RESOLUE" in _codes(resultat)


@pytest.mark.parametrize(
    ("contenu", "code_attendu"),
    [
        ("import random\nvaleur = random.random()\n", "RANDOM_NON_ENSEMENCE"),
        ("from random import Random\nvaleur = Random()\n", "RANDOM_NON_ENSEMENCE"),
        ("import time\nvaleur = time.time()\n", "HORLOGE_INTERNE"),
        (
            "from datetime import datetime\nvaleur = datetime.now()\n",
            "HORLOGE_INTERNE",
        ),
        (
            "from datetime import datetime\nvaleur = datetime.today()\n",
            "HORLOGE_INTERNE",
        ),
        (
            "from datetime import datetime\nvaleur = datetime.utcnow()\n",
            "HORLOGE_INTERNE",
        ),
        ("import socket\nclient = socket.socket()\n", "RESEAU_INTERDIT"),
        ("import urllib.request\nurllib.request.urlopen('https://exemple.test')\n", "RESEAU_INTERDIT"),
        ("import requests\nrequests.get('https://exemple.test')\n", "RESEAU_INTERDIT"),
        ("import http.client\nhttp.client.HTTPConnection('exemple.test')\n", "RESEAU_INTERDIT"),
    ],
)
def test_motifs_ast_interdits_sont_detectes(
    tmp_path: Path, contenu: str, code_attendu: str
) -> None:
    """Verrouille la détection AST positive de chaque famille interdite par CA-M3-20."""
    _ecrire_source(
        tmp_path,
        "contrats.py",
        """
TYPES_TRAVAUX = ("autre",)
VERDICTS_ESTIMATION = ("INDETERMINE",)
""",
    )
    _ecrire_source(
        tmp_path,
        "cible.py",
        contenu,
    )

    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is False
    assert code_attendu in _codes(resultat)


@pytest.mark.parametrize(
    "contenu",
    [
        "from datetime import datetime\ninstant = datetime.fromisoformat(valeur_fournie)\n",
        "from random import Random\ngenerateur = Random(graine_fournie)\n",
        "temps_de_traitement = entree.time\n",
        "socket_name = 'socket sans import reseau'\n",
        "requests_count = 3\n",
        "prix_bloque = bareme['prix_bloque']\n",
    ],
)
def test_motifs_ressemblants_mais_licites_ne_sont_pas_detectes(
    tmp_path: Path, contenu: str
) -> None:
    """Verrouille que l'analyse AST ne confond pas analyse fournie, graine fournie et interdits."""
    _ecrire_source(
        tmp_path,
        "contrats.py",
        """
TYPES_TRAVAUX = ("autre",)
VERDICTS_ESTIMATION = ("INDETERMINE",)
""",
    )
    _ecrire_source(tmp_path, "cible.py", contenu)

    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is True
    assert not (
        {
            "RANDOM_NON_ENSEMENCE",
            "HORLOGE_INTERNE",
            "RESEAU_INTERDIT",
        }
        & _codes(resultat)
    )


def test_litteral_de_cout_nomme_est_detecte_sans_confondre_seuil_et_indice(
    tmp_path: Path,
) -> None:
    """Verrouille le critère explicite : un nombre devient coût seulement dans un contexte monétaire."""
    _ecrire_source(
        tmp_path,
        "contrats.py",
        """
TYPES_TRAVAUX = ("autre",)
VERDICTS_ESTIMATION = ("INDETERMINE",)
""",
    )
    _ecrire_source(
        tmp_path,
        "bareme_illicite.py",
        """
prix = 1500
seuil_confiance = 0.90
indice_niveau = 3
resolution_minimale = 1024
""",
    )

    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is False
    assert "LITTERAL_COUT_INTERDIT" in _codes(resultat)
    cout = next(
        entree
        for entree in resultat["violations"]
        if entree["code"] == "LITTERAL_COUT_INTERDIT"
    )
    assert cout["ligne"] == 2
    assert cout["contexte"] == "prix"


def test_limite_du_controle_de_cout_est_declaree_et_non_mensongere(
    tmp_path: Path,
) -> None:
    """Verrouille qu'un coût sans contexte identifiable est signalé comme limite, jamais certifié sûr."""
    _ecrire_source(
        tmp_path,
        "contrats.py",
        """
TYPES_TRAVAUX = ("autre",)
VERDICTS_ESTIMATION = ("INDETERMINE",)
""",
    )
    _ecrire_source(
        tmp_path,
        "valeur_opaque.py",
        """
coefficient = 1500
""",
    )

    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is True
    assert any(
        limite["code"] == "LIMITE_DETECTION_COUT_CONTEXTUELLE"
        for limite in resultat["limites"]
    )


def test_extracteur_vide_echoue_ferme(tmp_path: Path) -> None:
    """Verrouille qu'un répertoire sans fichier Python ne peut jamais être déclaré conforme."""
    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is False
    assert "AUCUN_FICHIER_ANALYSE" in _codes(resultat)


def test_extracteur_sans_enumere_echoue_ferme(tmp_path: Path) -> None:
    """Verrouille qu'une analyse sans énuméré cible ne conclut jamais au vert."""
    _ecrire_source(tmp_path, "module.py", "valeur = 'sans enumere'\n")

    resultat = _verifier(tmp_path)

    assert resultat["conforme"] is False
    assert "AUCUN_ENUMERE_EXAMINE" in _codes(resultat)


def test_paquet_m3_reel_passe_sa_propre_conformite() -> None:
    """Verrouille l'auto-application de CA-M3-19 et CA-M3-20 sur toutes les sources M3 livrées."""
    resultat = _verifier(RACINE_SRC / "m3_estimation")

    assert resultat["conforme"] is True
    assert resultat["enumerees_examinees"]
    assert resultat["motifs_examines"]
    assert not resultat["violations"]


def test_digest_n_importe_aucune_source_d_ambiance_interdite() -> None:
    """Verrouille fichier par fichier que le digest n'importe ni horloge, ni hasard, ni réseau."""
    arbre = ast.parse(Path(digest.__file__).read_text(encoding="utf-8"))
    racines_interdites = {"datetime", "time", "random", "socket", "urllib"}

    imports = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module is not None:
            imports.add(noeud.module.split(".", 1)[0])

    assert not (imports & racines_interdites)


def test_digest_est_lecture_seule_deterministe_et_filtre_la_fenetre() -> None:
    """Verrouille le digest byte-identique, sans mutation, limité à la fenêtre fournie."""
    maillons = [
        {
            "type_entree": "estimation_produite",
            "devis_id": "DEV-2",
            "horodatage": "2026-03-03T10:00:00+00:00",
            "prix_bloque": True,
            "alerte_plancher": False,
            "raison_blocage": "QUALITE_ENTREE_INSUFFISANTE",
        },
        {
            "type_entree": "estimation_produite",
            "devis_id": "DEV-1",
            "horodatage": "2026-03-03T09:00:00+00:00",
            "prix_bloque": False,
            "alerte_plancher": True,
            "raison_blocage": None,
        },
        {
            "type_entree": "estimation_produite",
            "devis_id": "DEV-HORS-FENETRE",
            "horodatage": "2026-03-04T00:00:00+00:00",
            "prix_bloque": True,
            "alerte_plancher": True,
            "raison_blocage": "INDETERMINE",
        },
    ]
    registre = _registre(maillons)
    avant = copy.deepcopy(maillons)

    premier = digest.produire_digest(
        registre,
        "2026-03-03T00:00:00+00:00",
        "2026-03-04T00:00:00+00:00",
        "2026-03-04T08:00:00+00:00",
    )
    second = digest.produire_digest(
        registre,
        "2026-03-03T00:00:00+00:00",
        "2026-03-04T00:00:00+00:00",
        "2026-03-04T08:00:00+00:00",
    )

    assert premier == second
    assert maillons == avant
    assert registre.nombre_lectures == 2
    assert "[ESTIMATIONS_BLOQUEES]" in premier
    assert "[ALERTES_PLANCHER]" in premier
    assert "DEV-2" in premier
    assert "DEV-1" in premier
    assert "DEV-HORS-FENETRE" not in premier
    assert premier.index("DEV-2") < premier.index("DEV-1")


def test_digest_vide_est_explicite_et_ne_mutile_pas_le_registre() -> None:
    """Verrouille qu'un registre vide donne les deux sections explicites sans erreur ni écriture."""
    registre = _registre([])

    resultat = digest.produire_digest(
        registre,
        "2026-03-03T00:00:00+00:00",
        "2026-03-04T00:00:00+00:00",
        "2026-03-04T08:00:00+00:00",
    )

    assert resultat == (
        "DIGEST debut_fenetre=2026-03-03T00:00:00+00:00 "
        "fin_fenetre=2026-03-04T00:00:00+00:00 "
        "horodatage=2026-03-04T08:00:00+00:00\n"
        "[ESTIMATIONS_BLOQUEES]\n"
        "[ALERTES_PLANCHER]"
    )
    assert registre.entrees == []
    assert registre.nombre_lectures == 1


def test_digest_est_canonique_pour_des_registres_equivalents_ordonnes_autrement() -> None:
    """Verrouille que le digest trie canoniquement des maillons équivalents."""
    maillons_premier = [
        {
            "type_entree": "estimation_produite",
            "devis_id": "DEV-3",
            "horodatage": "2026-03-03T11:00:00+00:00",
            "prix_bloque": True,
            "alerte_plancher": False,
            "raison_blocage": "INDETERMINE",
        },
        {
            "type_entree": "estimation_produite",
            "devis_id": "DEV-1",
            "horodatage": "2026-03-03T09:00:00+00:00",
            "prix_bloque": True,
            "alerte_plancher": True,
            "raison_blocage": "QUALITE_ENTREE_INSUFFISANTE",
        },
        {
            "type_entree": "estimation_produite",
            "devis_id": "DEV-2",
            "horodatage": "2026-03-03T10:00:00+00:00",
            "prix_bloque": False,
            "alerte_plancher": True,
            "raison_blocage": None,
        },
    ]
    maillons_second = [
        {
            "raison_blocage": None,
            "alerte_plancher": True,
            "prix_bloque": False,
            "horodatage": "2026-03-03T10:00:00+00:00",
            "devis_id": "DEV-2",
            "type_entree": "estimation_produite",
        },
        {
            "raison_blocage": "INDETERMINE",
            "prix_bloque": True,
            "type_entree": "estimation_produite",
            "devis_id": "DEV-3",
            "alerte_plancher": False,
            "horodatage": "2026-03-03T11:00:00+00:00",
        },
        {
            "alerte_plancher": True,
            "horodatage": "2026-03-03T09:00:00+00:00",
            "type_entree": "estimation_produite",
            "raison_blocage": "QUALITE_ENTREE_INSUFFISANTE",
            "prix_bloque": True,
            "devis_id": "DEV-1",
        },
    ]

    assert [maillon["devis_id"] for maillon in maillons_premier] != [
        maillon["devis_id"] for maillon in maillons_second
    ]
    assert sorted(maillons_premier, key=lambda maillon: maillon["devis_id"]) == sorted(
        maillons_second, key=lambda maillon: maillon["devis_id"]
    )
    assert tuple(maillons_premier[0]) != tuple(maillons_second[1])

    premier = digest.produire_digest(
        _registre(maillons_premier),
        "2026-03-03T00:00:00+00:00",
        "2026-03-04T00:00:00+00:00",
        "2026-03-04T08:00:00+00:00",
    )
    second = digest.produire_digest(
        _registre(maillons_second),
        "2026-03-03T00:00:00+00:00",
        "2026-03-04T00:00:00+00:00",
        "2026-03-04T08:00:00+00:00",
    )

    assert premier == second


@pytest.mark.parametrize(
    ("debut_fenetre", "fin_fenetre"),
    [
        ("2026-03-03T00:00:00+00:00", "2026-03-03T00:00:00+00:00"),
        ("2026-03-04T00:00:00+00:00", "2026-03-03T00:00:00+00:00"),
        ("2026-03-03T01:00:00+01:00", "2026-03-03T00:00:00+00:00"),
    ],
)
def test_digest_refuse_une_fenetre_invalide(
    debut_fenetre: str,
    fin_fenetre: str,
) -> None:
    """Verrouille le refus fermé des fenêtres dont la fin n'est pas postérieure au début."""
    try:
        digest.produire_digest(
            _registre([]),
            debut_fenetre,
            fin_fenetre,
            "2026-03-04T08:00:00+00:00",
        )
    except ValueError as erreur:
        assert str(erreur) == (
            "fenêtre invalide : la fin doit être strictement postérieure au début"
        )
    except (AttributeError, KeyError, TypeError) as erreur:
        pytest.fail(f"Exception échappée : {type(erreur).__name__}")
    else:
        pytest.fail("Fenêtre invalide acceptée par produire_digest")
