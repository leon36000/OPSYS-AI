import importlib.util
import io
from pathlib import Path

_CHEMIN_MODULE = Path(__file__).resolve().parent / "outils_preuve" / "lecture_junit.py"
_SPECIFICATION = importlib.util.spec_from_file_location(
    "lecture_junit_outils_preuve",
    _CHEMIN_MODULE,
)
if _SPECIFICATION is None or _SPECIFICATION.loader is None:
    raise ImportError(f"Impossible de charger {_CHEMIN_MODULE}")

lecture_junit = importlib.util.module_from_spec(_SPECIFICATION)
_SPECIFICATION.loader.exec_module(lecture_junit)


_BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
<!ENTITY lol "lol">
<!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
<!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<testsuite name="attaque">&lol4;</testsuite>
"""

_ENTITE_EXTERNE = """<?xml version="1.0"?>
<!DOCTYPE testsuite [
<!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<testsuite name="attaque">&xxe;</testsuite>
"""


def _ecrire_rapport(tmp_path, nom, contenu):
    chemin = tmp_path / nom
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def test_lit_exactement_les_echecs_et_erreurs_d_un_rapport_junit_normal(tmp_path):
    """Verrouille la lecture saine des échecs nommés et des erreurs sans classe."""
    rapport = _ecrire_rapport(
        tmp_path,
        "rapport-normal.xml",
        """<?xml version="1.0"?>
<testsuites>
  <testsuite name="estimation">
    <testcase classname="m3.estimation" name="test_vert"/>
    <testcase classname="m3.estimation" name="test_echec">
      <failure message="borne invalide"/>
    </testcase>
    <testcase name="test_erreur">
      <error message="collecte interrompue"/>
    </testcase>
  </testsuite>
</testsuites>
""",
    )

    echecs = lecture_junit.echecs_junit(rapport, journalisation=None)

    assert echecs == {
        "m3.estimation::test_echec",
        "test_erreur",
    }


def test_voit_une_erreur_directement_portee_par_la_suite(tmp_path):
    """Verrouille l'attribution des erreurs de collecte sans testcase nommé."""
    rapport = _ecrire_rapport(
        tmp_path,
        "erreur-collecte.xml",
        """<?xml version="1.0"?>
<testsuite name="collecte-m3">
  <error message="échec pendant la collecte"/>
</testsuite>
""",
    )

    echecs = lecture_junit.echecs_junit(rapport, journalisation=None)

    assert echecs == {"collecte-m3::error"}


def test_refuse_le_billion_laughs_et_journalise_le_motif(tmp_path):
    """Verrouille le refus des entités récursives avant leur expansion XML."""
    rapport = _ecrire_rapport(tmp_path, "billion-laughs.xml", _BILLION_LAUGHS)
    journal = io.StringIO()

    echecs = lecture_junit.echecs_junit(rapport, journalisation=journal)

    assert echecs == set()
    assert "DTD refusée" in journal.getvalue()


def test_refuse_l_entite_externe_sans_lire_le_fichier_reference(tmp_path):
    """Verrouille le refus d'une entité SYSTEM indépendamment de /etc/passwd."""
    rapport = _ecrire_rapport(tmp_path, "entite-externe.xml", _ENTITE_EXTERNE)
    journal = io.StringIO()

    echecs = lecture_junit.echecs_junit(rapport, journalisation=journal)

    assert echecs == set()
    assert "DTD refusée" in journal.getvalue()


def test_un_fichier_absent_retourne_le_vide_et_rend_le_silence_visible(tmp_path):
    """Verrouille le contrat fail-closed et la journalisation d'un rapport absent."""
    rapport_absent = tmp_path / "rapport-absent.xml"
    journal = io.StringIO()

    echecs = lecture_junit.echecs_junit(rapport_absent, journalisation=journal)

    assert echecs == set()
    assert "fichier absent" in journal.getvalue()


def test_les_gardes_expat_sont_reellement_branchees_au_refus_des_dtd(tmp_path):
    """Verrouille que neutraliser les gardes change le refus du billion laughs."""
    rapport = _ecrire_rapport(tmp_path, "preuve-branchement.xml", _BILLION_LAUGHS)

    journal_protege = io.StringIO()
    resultat_protege = lecture_junit.echecs_junit(
        rapport,
        journalisation=journal_protege,
    )
    sortie_protegee = journal_protege.getvalue()

    assert resultat_protege == set()
    assert "DTD refusée" in sortie_protegee

    garde_originale = lecture_junit._configurer_gardes_expat

    def configurer_sans_garde(_parseur):
        return None

    lecture_junit._configurer_gardes_expat = configurer_sans_garde
    try:
        journal_sans_garde = io.StringIO()
        resultat_sans_garde = lecture_junit.echecs_junit(
            rapport,
            journalisation=journal_sans_garde,
        )
        sortie_sans_garde = journal_sans_garde.getvalue()
    finally:
        lecture_junit._configurer_gardes_expat = garde_originale

    assert (resultat_sans_garde, sortie_sans_garde) != (
        resultat_protege,
        sortie_protegee,
    )
    assert "DTD refusée" not in sortie_sans_garde


def test_la_journalisation_non_demandee_n_ecrit_ni_sur_stdout_ni_sur_stderr(
    tmp_path,
    capsys,
):
    """Verrouille qu'une journalisation explicitement non demandée reste silencieuse."""
    rapport_absent = tmp_path / "sans-journalisation.xml"

    echecs = lecture_junit.echecs_junit(rapport_absent, journalisation=None)
    capture = capsys.readouterr()

    assert echecs == set()
    assert capture.out == ""
    assert capture.err == ""


def test_equivalence_semantique_sur_table_de_reference_figee(tmp_path):
    """Verrouille les cas de compatibilité de l'ancienne extraction JUnit."""
    # L'historique git n'est pas une dépendance fiable d'une batterie distribuée :
    # cette comparaison est donc faite contre une table de référence, et non contre
    # le code d'origine chargé dynamiquement depuis git.
    cas = [
        (
            "espaces-noms.xml",
            """<testsuites xmlns="urn:junit">
<testsuite name="ns"><testcase classname="pkg.Classe" name="rouge"><failure/></testcase>
<error/></testsuite></testsuites>""",
            {"pkg.Classe::rouge", "ns::error"},
        ),
        (
            "plusieurs-suites.xml",
            """<testsuites><testsuite name="a"><testcase name="x"><error/></testcase></testsuite>
<testsuite name="b"><testcase classname="B" name="y"><failure/></testcase></testsuite></testsuites>""",
            {"x", "B::y"},
        ),
        (
            "attributs-absents.xml",
            """<testsuite><testcase><failure/></testcase></testsuite>""",
            {"<test sans nom>"},
        ),
        (
            "echecs-meles.xml",
            """<testsuite name="mix"><testcase classname="C" name="n"><failure/><error/></testcase>
<failure/><error/></testsuite>""",
            {"C::n", "mix::failure", "mix::error"},
        ),
        (
            "suite-vide.xml",
            """<testsuite name="vide"/>""",
            set(),
        ),
        (
            "sans-echec.xml",
            """<testsuites><testsuite name="vert"><testcase classname="C" name="ok"/></testsuite></testsuites>""",
            set(),
        ),
    ]

    for nom, contenu, attendu in cas:
        rapport = _ecrire_rapport(tmp_path, nom, contenu)
        assert lecture_junit.echecs_junit(rapport, journalisation=None) == attendu
