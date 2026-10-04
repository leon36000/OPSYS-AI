"""Batterie durable de mutations du contrôle 19 — le contrat d'entrée du brief réel.

Le contrôle 19 (``verifier_brief_contrat_reel``) garantit que le contrat
d'entrée déclaré dans le brief de l'analyste reste la source de vérité du
gate : un champ fantôme réintroduit, une clé réelle retirée, un titre de
section renommé ou une section vidée de ses champs doivent chacun le faire
échouer. Or une détection prouvée une seule fois, à la main, ne prouve plus
rien dès que le brief évolue — un contrôle dont on ne revérifie plus la
détection devient décoratif : il reste vert et ne prouve plus rien. Ce
fichier rejoue donc la batterie à chaque run de la suite : il lit le brief
et l'architecture réels une seule fois, applique chaque mutation EN MÉMOIRE
sur les chaînes, puis appelle la fonction directement.

Aucune écriture de fichier, aucun sous-processus : muter les artefacts
suivis laisserait le dépôt corrompu si la suite était interrompue, et une
preuve qui réécrit ses propres artefacts ne serait pas reproductible. Le
gate n'étant pas un paquet installable, il est chargé par importlib depuis
son chemin réel dérivé de ``__file__`` — jamais du répertoire courant.

Limite assumée : les cas fail-closed (source de M2 absente ou constante
renommée) sont hors de ce fichier, car ils exigeraient de toucher au
système de fichiers d'un module voisin.
"""
import sys as _sys
from pathlib import Path as _Path

import pytest

_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _commun_gate import ARCHI, BRIEF, GATE

# Le corps des tests nomme le gate « VERIF_COHERENCE » : simple affectation
# pour conserver cet identifiant sans toucher à aucun test.
VERIF_COHERENCE = GATE

_CLES_CONTRAT = {
    "lead_id",
    "conversation_id",
    "type_travaux",
    "ville",
    "canal",
    "contact",
    "urgence_declaree",
}


def test_le_controle_est_vert_sur_le_brief_reel():
    """Sans mutation, le contrôle ne produit aucun message sur le brief réel."""
    messages = VERIF_COHERENCE.verifier_brief_contrat_reel(BRIEF, ARCHI)
    assert messages == [], f"contrôle rouge sur le brief réel non muté : {messages}"


@pytest.mark.parametrize(
    "libelle, avant, apres, nombre",
    [
        pytest.param(
            "champ fantôme réintroduit",
            "- `conversation_id` —",
            "- `sha256` — empreinte.\n- `conversation_id` —",
            1,
        ),
        pytest.param(
            "clé réelle retirée",
            "- `urgence_declaree`",
            "- `zzz_retire`",
            1,
        ),
        pytest.param(
            "titre de section renommé",
            "## 4. CONTRAT D'ENTRÉE",
            "## 4. Entrees",
            1,
        ),
        pytest.param(
            "section vidée de ses champs",
            "- `conversation_id`",
            "  `conversation_id`",
            1,
        ),
    ],
    ids=[
        "champ_fantome_reintroduit",
        "cle_reelle_retiree",
        "titre_de_section_renomme",
        "section_videe_de_ses_champs",
    ],
)
def test_chaque_mutation_du_brief_est_detectee(libelle, avant, apres, nombre):
    """Chaque mutation en mémoire du brief est détectée par au moins un message."""
    occurrences = BRIEF.count(avant)
    assert occurrences == 1, (
        f"cas « {libelle} » : motif AVANT présent {occurrences} fois "
        f"au lieu d'une exactement : {avant!r}"
    )
    brief_mute = BRIEF.replace(avant, apres, nombre)
    messages = VERIF_COHERENCE.verifier_brief_contrat_reel(brief_mute, ARCHI)
    assert len(messages) >= 1, (
        f"cas « {libelle} » : mutation non détectée, le contrôle est resté vert"
    )


def test_l_extracteur_unique_rend_les_sept_cles_reelles():
    """L'extracteur du contrat rend exactement les sept clés réelles, sans doublon."""
    champs = VERIF_COHERENCE.champs_du_contrat_brief(BRIEF)
    assert set(champs) == _CLES_CONTRAT, (
        f"clés inattendues ou manquantes : {sorted(set(champs) ^ _CLES_CONTRAT)}"
    )
    assert len(champs) == 7, f"doublon dans les clés extraites : {champs}"


def test_une_section_sans_aucune_puce_nomme_l_extracteur_vide():
    """Éprouve qu'une section vidée de toutes ses puces fait nommer l'extracteur vide par le premier diagnostic.

    La garde ne change pas la DÉTECTION — sans elle, les sept clés réelles
    absentes rougissent de toute façon — elle change le DIAGNOSTIC, et c'est
    ce diagnostic qui est exigé ici : accuser la bonne pièce, l'extracteur,
    pas le brief.
    """
    brief_mute = BRIEF.replace("\n- `", "\n  `")
    messages = VERIF_COHERENCE.verifier_brief_contrat_reel(brief_mute, ARCHI)
    assert len(messages) >= 1, (
        "section vidée de ses puces : aucun message produit, "
        "le contrôle est resté vert"
    )
    assert "extracteur vide" in messages[0], (
        f"le premier message ne nomme pas l'extracteur vide : {messages[0]!r}"
    )
    assert "ne mentionne pas" not in messages[0], (
        "le premier message accuse le brief de clés manquantes au lieu de "
        f"nommer l'extracteur vide : {messages[0]!r}"
    )
