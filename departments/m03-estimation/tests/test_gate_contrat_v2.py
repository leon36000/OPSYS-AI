"""Batterie de mutations du contrôle 13 ter (PLAN T0.13) — le LeadQualifie v2 et le catalogue.

Le contrôle 13 ter garantit que le contrat v2 décrit par l'architecture de M3 est celui que M2
accepte, et que les services cités sont ceux du catalogue du socle (`src/opsys/taxonomie.py`).
Une détection prouvée une fois à la main ne prouve plus rien dès que les artefacts évoluent : ce
fichier rejoue donc chaque mutation à chaque run. Les mutations de l'architecture se font EN
MÉMOIRE ; celles des sources de M2 et du socle se font sur des COPIES dans `tmp_path` — jamais sur
les fichiers suivis."""
import sys as _sys
from pathlib import Path as _Path

import pytest

_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _commun_gate import ARCHI, GATE  # noqa: E402

_DEPOT = _Path(__file__).resolve().parents[3]
_SOURCE_M2 = _DEPOT / "departments" / "m02-revenue-crm" / "src" / "m2_revenue_crm" / "contrats.py"
_SOURCE_TAXONOMIE = _DEPOT / "src" / "opsys" / "taxonomie.py"


def _copie(tmp_path, source, nom, avant=None, apres=None):
    texte = source.read_text(encoding="utf-8")
    if avant is not None:
        assert texte.count(avant) == 1, f"mutation non applicable ({avant!r} x{texte.count(avant)})"
        texte = texte.replace(avant, apres)
    chemin = tmp_path / nom
    chemin.write_text(texte, encoding="utf-8")
    return chemin


def _verifier(archi=ARCHI, m2=None, taxonomie=None):
    return GATE.verifier_contrat_v2_consomme_existe_vraiment(archi, m2, taxonomie)


_TITRE_V2 = "#### `LeadQualifie v2`"


def _muter_archi(avant, apres):
    """Mutation en mémoire, appliquée à partir du titre du contrat v2 (le bloc v1 porte les mêmes
    lignes : la muter donnerait un test vert à tort)."""
    tete, queue = ARCHI.split(_TITRE_V2, 1) if _TITRE_V2 in ARCHI and avant != _TITRE_V2 else (ARCHI, "")
    if not queue:
        assert ARCHI.count(avant) == 1, f"mutation non applicable ({avant!r} x{ARCHI.count(avant)})"
        return ARCHI.replace(avant, apres)
    assert queue.count(avant) >= 1, f"mutation non applicable dans la v2 ({avant!r})"
    return tete + _TITRE_V2 + queue.replace(avant, apres, 1)


def test_le_controle_est_vert_sur_les_artefacts_reels():
    assert _verifier() == []
    assert GATE.verifier_contrat_consomme_existe_vraiment(ARCHI) == [], "le contrôle 13 (v1) reste vert"


LIGNE_SERVICE = (
    "  service: str              # Code d'un service DÉCLARÉ par l'entreprise "
    "(section `service` des énumérés) ; remplace type_travaux.\n"
)


@pytest.mark.parametrize("libelle, avant, apres, attendu", [
    ("clé v2 retirée de l'architecture", LIGNE_SERVICE, "", "DIFFÈRE"),
    ("clé fantôme ajoutée", LIGNE_SERVICE, LIGNE_SERVICE + "  sha256: str            # fantôme.\n", "DIFFÈRE"),
    ("type_travaux réintroduit dans la v2", LIGNE_SERVICE,
     LIGNE_SERVICE + "  type_travaux: str         # ancien énuméré.\n", "DIFFÈRE"),
    ("clé optionnelle non marquée", "  source: str               # OPTIONNEL (PLAN T2.2)",
     "  source: str               # (PLAN T2.2)", "DIFFÈRE"),
    ("type de service divergent", LIGNE_SERVICE, LIGNE_SERVICE.replace("service: str", "service: int"),
     "Type divergent"),
    ("type de schema_version divergent", "  schema_version: int  ", "  schema_version: str  ", "Type divergent"),
    ("version annoncée différente", "Vaut 2 (entier strict", "Vaut 3 (entier strict", "version déclarée"),
    ("titre du contrat v2 renommé", "#### `LeadQualifie v2`", "#### `LeadQualifie deux`", "introuvable"),
    ("nom du bloc erroné", "LeadQualifie_v2:", "LeadQualifie_v3:", "ancrage erroné"),
    (
        "service retiré du catalogue cité",
        "`soffite_fascia`,\n`reparation`.",
        "`soffite_fascia`.",
        "Catalogue de services divergent",
    ),
    ("service inventé dans le catalogue cité", "`soffite_fascia`,\n`reparation`.",
     "`soffite_fascia`,\n`reparation`, `pergola`.", "Catalogue de services divergent"),
    ("phrase du catalogue supprimée", "Codes du catalogue de référence :", "Codes possibles :", "introuvable"),
    ("section service renommée", "#### `service` — aucune copie", "#### `services` — aucune copie", "introuvable"),
])
def test_mutation_de_l_architecture_est_detectee(libelle, avant, apres, attendu):
    erreurs = _verifier(archi=_muter_archi(avant, apres))
    assert erreurs, f"mutation non détectée : {libelle}"
    assert any(attendu in erreur for erreur in erreurs), (libelle, erreurs)


@pytest.mark.parametrize("libelle, avant, apres, attendu", [
    ("clé v2 ajoutée côté producteur", '    "schema_version",\n    "lead_id",',
     '    "schema_version",\n    "sha256",\n    "lead_id",', "DIFFÈRE"),
    (
        "clé v2 retirée côté producteur",
        '    "service",\n    "ville",\n    "canal",\n    "contact",\n    "urgence_declaree",\n)\n\nCANAUX',
     '    "ville",\n    "canal",\n    "contact",\n    "urgence_declaree",\n)\n\nCANAUX', "DIFFÈRE"),
    ("constante de version renommée", "VERSION_CONTRAT_V2 = 2", "VERSION_V2 = 2", "VERSION_CONTRAT_V2 introuvable"),
    ("version du producteur changée", "VERSION_CONTRAT_V2 = 2", "VERSION_CONTRAT_V2 = 3", "version déclarée"),
    ("type imposé à service changé", 'if not isinstance(contrat["service"], str):',
     'if not isinstance(contrat["service"], int):', "Type divergent"),
    ("clé optionnelle retirée côté producteur", 'CHAMPS_CONTRAT_OPTIONNELS = ("source", "utm", "campagne")',
     'CHAMPS_CONTRAT_OPTIONNELS = ("source", "utm")', "OPTIONNELLES"),
])
def test_mutation_du_producteur_est_detectee(tmp_path, libelle, avant, apres, attendu):
    erreurs = _verifier(m2=_copie(tmp_path, _SOURCE_M2, "contrats.py", avant, apres))
    assert erreurs, f"mutation non détectée : {libelle}"
    assert any(attendu in erreur for erreur in erreurs), (libelle, erreurs)


def test_les_controles_de_type_de_la_v2_sont_reellement_extraits_de_m2():
    """Garde de non-vacuité : les deux clés propres à la v2 sont confrontées, pas ignorées."""
    types = GATE._types_imposes_par_m2(_SOURCE_M2.read_text(encoding="utf-8"))
    assert types["schema_version"] == {"int"}
    assert types["service"] == {"str"}


def test_catalogue_du_socle_divergent_est_detecte(tmp_path):
    taxonomie = _copie(tmp_path, _SOURCE_TAXONOMIE, "taxonomie.py",
                       'Service("reparation", "Réparation",', 'Service("pose_pergola", "Pose de pergolas",')
    erreurs = _verifier(taxonomie=taxonomie)
    assert any("Catalogue de services divergent" in e and "pose_pergola" in e for e in erreurs), erreurs


def test_constante_du_catalogue_renommee_est_non_probante(tmp_path):
    taxonomie = _copie(tmp_path, _SOURCE_TAXONOMIE, "taxonomie.py", "CATALOGUE_REFERENCE:", "CATALOGUE_AUTRE:")
    erreurs = _verifier(taxonomie=taxonomie)
    assert erreurs and "CATALOGUE_REFERENCE introuvable" in erreurs[0]


@pytest.mark.parametrize("cible", ["m2", "taxonomie"])
def test_source_absente_est_non_probante_jamais_verte(tmp_path, cible):
    absent = tmp_path / "absent.py"
    erreurs = _verifier(m2=absent if cible == "m2" else None, taxonomie=absent if cible == "taxonomie" else None)
    assert erreurs and "introuvable" in erreurs[0] and "non probant" in erreurs[0]


def test_le_gate_complet_execute_le_controle_13_ter():
    """`main()` appelle 13 ter : sans cela, le contrôle existerait sans jamais tourner en CI."""
    source = (_Path(GATE.__file__)).read_text(encoding="utf-8")
    assert "verifier_contrat_v2_consomme_existe_vraiment(archi)" in source
