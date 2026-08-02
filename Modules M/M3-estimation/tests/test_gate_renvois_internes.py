"""Batterie durable de mutations du contrôle 21 — renvois internes BMAD.

Le contrôle vérifie que les renvois internes mesurés dans les documents BMAD
visent une section réellement définie dans le même document. Les mutations sont
appliquées en mémoire : aucun artefact suivi n'est réécrit par les tests.
"""
import sys as _sys
from pathlib import Path as _Path

import pytest

_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _commun_gate import GATE, BRIEF, PRD, ARCHI

VERIF_COHERENCE = GATE

MUTATIONS = [
    {
        "libelle": "bug historique décrit en 2.3 bis",
        "document": "archi",
        "avant": "décrit en 2.3",
        "apres": "décrit en 2.3 bis",
        "doit_produire_un_message": True,
    },
    {
        "libelle": "renvoi voir 2.5 vers section inexistante",
        "document": "archi",
        "avant": "voir 2.5",
        "apres": "voir 2.9",
        "doit_produire_un_message": True,
    },
    {
        # Objection de revue scellée, confirmée par mesure : la mutation
        # précédente ne contenait ni « décrit en » ni « voir », donc elle
        # n'atteignait JAMAIS les motifs de renvoi capturés — le test passait
        # trivialement, quelle que soit l'exclusion par proximité. Celle-ci
        # combine un motif RÉELLEMENT capturé (« voir 99.9 ») avec la marque
        # d'exclusion « du prd section » à proximité mesurée (< 40 caractères) :
        # elle exerce enfin le chemin d'exclusion lui-même, pas seulement
        # l'absence de détection du motif.
        "libelle": "renvoi inter-document absurde, motif capturé, reste hors périmètre",
        "document": "archi",
        "avant": "Copié mot pour mot du PRD section 4.1.",
        "apres": "Copié mot pour mot du PRD section, voir 99.9.",
        "doit_produire_un_message": False,
    },
    {
        "libelle": "renvoi interne valide vers autre section valide",
        "document": "archi",
        "avant": "décrit en 2.3",
        "apres": "décrit en 2.4",
        "doit_produire_un_message": False,
    },
]


@pytest.mark.parametrize(
    "mutation", MUTATIONS, ids=[mutation["libelle"] for mutation in MUTATIONS]
)
def test_le_controle_detecte_chaque_mutation(mutation):
    """Chaque mutation en mémoire produit exactement le verdict attendu."""
    documents = {"brief": BRIEF, "prd": PRD, "archi": ARCHI}
    cible = documents[mutation["document"]]
    occurrences = cible.count(mutation["avant"])
    assert occurrences == 1, (
        f"mutation « {mutation['libelle']} » : le motif AVANT apparaît "
        f"{occurrences} fois dans « {mutation['document']} » — la mutation "
        "serait ambiguë ou ne muterait rien, et le test serait vert pour rien"
    )

    documents_mutes = dict(documents)
    documents_mutes[mutation["document"]] = cible.replace(
        mutation["avant"], mutation["apres"], 1
    )
    messages = VERIF_COHERENCE.verifier_renvois_internes_valides(
        documents_mutes["prd"],
        documents_mutes["archi"],
    )

    attendu = (
        "produire au moins un message"
        if mutation["doit_produire_un_message"]
        else "ne produire aucun message"
    )
    assert bool(messages) == mutation["doit_produire_un_message"], (
        f"mutation « {mutation['libelle']} » : le contrôle devait {attendu} ; "
        f"messages obtenus : {messages}"
    )


def test_le_controle_est_vert_sur_les_documents_reels():
    """Les renvois internes réellement présents visent tous une section existante."""
    messages = VERIF_COHERENCE.verifier_renvois_internes_valides(PRD, ARCHI)
    assert messages == [], (
        "le contrôle 21 est rouge sur les documents réels ; une mutation qui "
        "mordrait ne prouverait plus rien. Messages : "
        f"{messages}"
    )


def test_un_renvoi_dans_un_bloc_cloture_est_ignore():
    """Un renvoi cité dans un bloc de code n'est pas un engagement documentaire."""
    messages_nus = VERIF_COHERENCE.verifier_renvois_internes_valides(PRD, ARCHI)
    assert messages_nus == [], (
        "les documents réels doivent être verts avant l'insertion de la "
        f"citation en bloc clôturé. Messages : {messages_nus}"
    )

    archi_avec_citation = ARCHI + (
        "\n## Exemple de renvoi cité\n\n"
        "```text\n"
        "décrit en 99.9\n"
        "voir 88.8\n"
        "```\n"
    )
    messages = VERIF_COHERENCE.verifier_renvois_internes_valides(
        PRD,
        archi_avec_citation,
    )
    assert messages == [], (
        "les renvois écrits dans un bloc clôturé doivent être masqués : ce "
        "sont des citations et non des engagements. Messages : "
        f"{messages}"
    )

    archi_temoin = ARCHI + "\n## Exemple de renvoi réel\n\ndécrit en 99.9\n"
    messages_temoin = VERIF_COHERENCE.verifier_renvois_internes_valides(
        PRD,
        archi_temoin,
    )
    assert messages_temoin, (
        "témoin : le même renvoi hors bloc clôturé doit être détecté ; sans "
        "ce témoin, le test serait vert même si le masquage ignorait tout le "
        f"document. Messages : {messages_temoin}"
    )


def test_exclusion_inter_document_par_proximite_est_reellement_exercee():
    """Objection de revue scellée : la mutation MUTATIONS ne contenait ni

    « décrit en » ni « voir », donc elle n'atteignait jamais les motifs de
    renvoi capturés — elle passait trivialement sans jamais exercer
    l'exclusion par proximité. Ce test combine un motif RÉELLEMENT capturé
    avec la marque d'exclusion à proximité mesurée, ET fournit le témoin
    inverse : sans la marque, le même motif doit rougir.
    """
    messages_nus = VERIF_COHERENCE.verifier_renvois_internes_valides(PRD, ARCHI)
    assert messages_nus == [], (
        "les documents réels doivent être verts avant l'ajout du cas exclu. "
        f"Messages : {messages_nus}"
    )

    archi_exclu = ARCHI + (
        "\n## Exemple de renvoi inter-document\n\n"
        "Du PRD section, voir 99.9 pour le détail complet.\n"
    )
    messages_exclu = VERIF_COHERENCE.verifier_renvois_internes_valides(
        PRD,
        archi_exclu,
    )
    assert messages_exclu == [], (
        "un renvoi capturé (« voir 99.9 ») mais précédé de la marque "
        "d'exclusion inter-document « du PRD section » à proximité doit "
        f"rester ignoré. Messages : {messages_exclu}"
    )

    archi_temoin_sans_marque = ARCHI + (
        "\n## Exemple sans marque d'exclusion\n\n"
        "Voir également, voir 99.9 pour le détail.\n"
    )
    messages_temoin = VERIF_COHERENCE.verifier_renvois_internes_valides(
        PRD,
        archi_temoin_sans_marque,
    )
    assert messages_temoin, (
        "témoin : le même motif « voir 99.9 » SANS la marque d'exclusion à "
        "proximité doit être détecté ; sans ce témoin, un motif jamais "
        "capturé du tout produirait le même résultat vert et le test "
        f"précédent ne prouverait rien. Messages : {messages_temoin}"
    )
