"""Chargement unique du gate de cohérence et des artefacts BMAD.

Trois fichiers de test de cette batterie chargeaient chacun
``docs/bmad/verif_coherence.py`` à la main, par importlib, depuis
``Path(__file__)`` — trois chargements concurrents du même module, donc
trois vérités concurrentes sur ce qu'est « le gate », plus une duplication
mesurée qui faisait refuser les PR. Ce fichier existe pour qu'il n'y ait
plus qu'UNE localisation de la racine du module, QU'UN chargement du gate
et QU'UNE lecture des trois documents : les tests importent les noms
ci-dessous depuis ``_commun_gate`` au lieu de tout refaire.

Les valeurs sont exposées au niveau MODULE, et non en fixtures pytest :
les tests paramétrés les consomment dans des ``parametrize`` évalués à la
COLLECTE, moment où les fixtures ne sont pas encore disponibles.

Garde de non-vacuité : si l'un des trois documents est vide, l'import lève
une erreur explicite immédiatement — un document vide rendrait des
dizaines de tests de mutation trivialement verts.
"""
import importlib.util
import sys
from pathlib import Path

RACINE_MODULE = Path(__file__).resolve().parents[1]
DOSSIER_BMAD = RACINE_MODULE / "docs" / "bmad"

_SPEC = importlib.util.spec_from_file_location(
    "verif_coherence", DOSSIER_BMAD / "verif_coherence.py"
)
assert _SPEC is not None and _SPEC.loader is not None, "gate de cohérence introuvable"
GATE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = GATE
_SPEC.loader.exec_module(GATE)

BRIEF = (DOSSIER_BMAD / "01-BRIEF-ANALYSTE.md").read_text(encoding="utf-8")
PRD = (DOSSIER_BMAD / "02-PRD-PM.md").read_text(encoding="utf-8")
ARCHI = (DOSSIER_BMAD / "03-ARCHITECTURE.md").read_text(encoding="utf-8")

for _nom, _contenu in (
    ("01-BRIEF-ANALYSTE.md", BRIEF),
    ("02-PRD-PM.md", PRD),
    ("03-ARCHITECTURE.md", ARCHI),
):
    if not _contenu.strip():
        raise RuntimeError(
            f"document BMAD vide : {DOSSIER_BMAD / _nom} — un document vide "
            "rendrait des dizaines de tests de mutation trivialement verts, "
            "import interrompu"
        )
del _nom, _contenu
