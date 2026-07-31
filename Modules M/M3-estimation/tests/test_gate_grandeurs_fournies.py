"""Batterie durable de mutations du contrôle 20 — grandeurs fournies déclarées.

Le contrôle 20 (``verifier_grandeurs_fournies_declarees``) garantit que toute
grandeur FOURNIE par l'appelant qu'un critère d'acceptation du PRD emploie
(« seuil », « barème », « graine », « plancher ») est déclarée dans
l'interface d'entrée §3.1 de l'architecture — règle DA-M3-09 : un critère qui
exige ce que l'interface ne déclare pas est improuvable. Or une détection
prouvée une seule fois, à la main, ne prouve plus rien dès que les documents
évoluent — un contrôle dont on ne revérifie plus la détection devient
décoratif : il reste vert et ne prouve plus rien. Ce fichier rejoue donc la
batterie à chaque run de la suite : il lit le PRD et l'architecture réels une
seule fois, applique chaque mutation EN MÉMOIRE sur les chaînes, puis appelle
la fonction directement.

Aucune écriture de fichier, aucun sous-processus : muter les artefacts suivis
laisserait le dépôt corrompu si la suite était interrompue, et une preuve qui
réécrit ses propres artefacts ne serait pas reproductible. Le gate n'étant pas
un paquet installable, il est chargé par importlib depuis son chemin réel
dérivé de ``__file__`` — jamais du répertoire courant.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE = Path(__file__).resolve().parents[1]
_BMAD = _MODULE / "docs" / "bmad"

_SPEC = importlib.util.spec_from_file_location(
    "verif_coherence", _BMAD / "verif_coherence.py"
)
assert _SPEC is not None and _SPEC.loader is not None, "gate de cohérence introuvable"
VERIF_COHERENCE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = VERIF_COHERENCE
_SPEC.loader.exec_module(VERIF_COHERENCE)

PRD = (_BMAD / "02-PRD-PM.md").read_text(encoding="utf-8")
ARCHI = (_BMAD / "03-ARCHITECTURE.md").read_text(encoding="utf-8")


def test_le_controle_est_vert_sur_les_documents_reels():
    """Sans mutation, aucun message — sinon une mutation « qui mord » pourrait mordre parce que le contrôle est rouge en permanence."""
    messages = VERIF_COHERENCE.verifier_grandeurs_fournies_declarees(PRD, ARCHI)
    assert messages == [], f"contrôle rouge sur les documents réels non mutés : {messages}"


@pytest.mark.parametrize(
    "libelle, prefixe",
    [
        pytest.param(
            "grandeur seuils_qualite retirée de §3.1",
            "- `seuils_qualite: dict`",
        ),
        pytest.param(
            "grandeur bareme_couts retirée de §3.1",
            "- `bareme_couts: dict`",
        ),
        pytest.param(
            "grandeur graine_monte_carlo retirée de §3.1",
            "- `graine_monte_carlo: int`",
        ),
        pytest.param(
            "grandeur plancher_rentable retirée de §3.1",
            "- `plancher_rentable: float`",
        ),
    ],
    ids=[
        "seuils_qualite_retiree",
        "bareme_couts_retire",
        "graine_monte_carlo_retiree",
        "plancher_rentable_retire",
    ],
)
def test_chaque_grandeur_retiree_de_l_interface_est_detectee(libelle, prefixe):
    """Supprimer une entrée de §3.1 — sa puce ET ses lignes de continuation — est détecté.

    Les trois dernières grandeurs étaient DÉJÀ correctement déclarées avant
    l'ajout du contrôle : les inclure prouve que le contrôle ne dépend pas du
    seul cas qui l'a motivé.
    """
    lignes = ARCHI.splitlines(keepends=True)
    indices = [i for i, ligne in enumerate(lignes) if ligne.startswith(prefixe)]
    assert len(indices) == 1, (
        f"cas « {libelle} » : ligne d'interface présente {len(indices)} fois "
        f"au lieu d'une exactement : {prefixe!r}"
    )
    debut = indices[0]
    fin = debut + 1
    while fin < len(lignes) and lignes[fin].startswith("  "):
        fin += 1
    archi_mute = "".join(lignes[:debut] + lignes[fin:])
    messages = VERIF_COHERENCE.verifier_grandeurs_fournies_declarees(PRD, archi_mute)
    assert len(messages) >= 1, (
        f"cas « {libelle} » : entrée retirée non détectée, le contrôle est resté vert"
    )


def test_section_interface_introuvable_est_non_probante():
    """Renommer le titre §3.1 fait échouer le contrôle, qui nomme la section cherchée au lieu de passer en silence."""
    titre = "### 3.1 Interface d'entrée"
    assert titre in ARCHI, (
        f"titre de la section §3.1 absent de l'architecture, "
        f"mutation impossible : {titre!r}"
    )
    archi_mute = ARCHI.replace(titre, "### 3.1 Grandeurs fournies renommées")
    messages = VERIF_COHERENCE.verifier_grandeurs_fournies_declarees(PRD, archi_mute)
    assert len(messages) >= 1, (
        "section §3.1 renommée : aucun message produit, "
        "le contrôle est passé en silence"
    )
    premier = messages[0]
    assert "Interface d'entrée" in premier, (
        f"le premier message ne nomme pas la section cherchée : {premier!r}. "
        "On n'exige pas le numéro de section car ce gate s'ancre sur le nom des sections, "
        "jamais sur leur numéro."
    )


