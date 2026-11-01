"""Revue adverse (reg) : une ligne hostile du journal de traces ne fait ni planter la vérification ni arrêter la
télémétrie. Le journal est un fichier local : qui peut y écrire (disque plein, éditeur, coupure de courant) y met
n'importe quoi. `verifier()` doit répondre « pas intègre » plutôt que lever, `lire()` ne doit pas emporter la console,
et `ajouter()` doit retrouver le dernier VRAI maillon sous une fin de fichier illisible, même plus grande que la fenêtre
de relecture : sinon la chaîne repart à `seq` 1 sur le maillon génèse. Données fictives."""

from __future__ import annotations

import datetime as dt

import pytest

from opsys.observabilite.traces import JournalTraces, Span

FICTIF = True
DEP = "m01-front-office"
PROFONDEUR = 40_000  # assez pour dépasser la récursion de l'analyseur JSON, sous la fenêtre de relecture (2 x 16 Kio)


@pytest.fixture
def journal(tmp_path) -> JournalTraces:
    horloge = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)
    return JournalTraces(tmp_path / "traces", b"c" * 32, maintenant=lambda: horloge)


def _span() -> Span:
    return Span(trace_id="a" * 32, span_id="b" * 16, type="appel_outil", debut="2026-11-01T12:00:00.000Z", duree_ms=5,
                departement=DEP, agent="agent-m1", issue="ok", outil="m1_filtrer_provenance", niveau="N0")


def _segment(journal: JournalTraces):
    return next(journal.dossier.glob("traces-*.jsonl"))


def _remplacer_ligne(journal: JournalTraces, numero: int, texte: str) -> None:
    chemin = _segment(journal)
    lignes = chemin.read_text(encoding="utf-8").splitlines()
    lignes[numero] = texte
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")


@pytest.mark.parametrize("hostile", [
    '{"v":1,"seq":2,"prev":"x","span":{"duree_ms":NaN},"h":"y"}',
    '{"v":1,"seq":2,"prev":"x","span":{"duree_ms":Infinity},"h":"y"}',
    '{"v":1,"seq":2,"prev":"x","span":' + "[" * PROFONDEUR + '"h":"y"}',
    '{"v":1,"seq":2,"prev":"x","span":' + "[" * 5000 + "0" + "]" * 5000 + ',"h":"y"}',
], ids=["nan", "infini", "imbrication-ouverte", "imbrication-fermee"])
def test_verifier_signale_une_ligne_hostile_au_lieu_de_lever(journal, hostile):
    for _ in range(3):
        journal.ajouter(_span())
    _remplacer_ligne(journal, 1, hostile)
    rapport = journal.verifier()
    assert rapport.ok is False and rapport.problemes


def test_lire_saute_une_ligne_trop_imbriquee_sans_lever(journal):
    for _ in range(3):
        journal.ajouter(_span())
    _remplacer_ligne(journal, 1, '{"v":1,"seq":2,"prev":"x","span":' + "[" * PROFONDEUR + '"h":"y"}')
    assert [e.seq for e in journal.lire()] == [1, 3]


def test_ajouter_continue_apres_une_derniere_ligne_trop_imbriquee(journal):
    journal.ajouter(_span())
    chemin = _segment(journal)
    with chemin.open("ab") as f:
        f.write(b'{"v":1,"seq":2,"prev":"x","span":' + b"[" * PROFONDEUR + b"\n")
    enregistrement = journal.ajouter(_span())  # ne doit pas lever : la ligne illisible est ignorée, la chaîne reprend
    assert enregistrement.seq == 2
    assert journal.verifier().ok is False  # la ligne hostile reste signalée


def test_cas_negatif_un_journal_sain_reste_integre(journal):
    for _ in range(3):
        journal.ajouter(_span())
    rapport = journal.verifier()
    assert rapport.ok and rapport.enregistrements == 3
    assert [e.seq for e in journal.lire()] == [1, 2, 3]


def test_une_fin_de_fichier_de_octets_nuls_plus_grande_que_la_fenetre_ne_fait_pas_repartir_la_chaine(journal):
    """Après une coupure de courant, un fichier peut finir par des pages d'octets nuls (bien plus de 32 Kio ici)."""
    premier = journal.ajouter(_span())
    chemin = _segment(journal)
    with chemin.open("ab") as f:
        f.write(b"\x00" * 200_000)
    suivant = journal.ajouter(_span())
    assert (premier.seq, suivant.seq) == (1, 2)
    lignes = [ligne for ligne in chemin.read_bytes().split(b"\n") if ligne.strip(b"\x00 ")]
    assert b'"seq":2' in lignes[-1] and b'"seq":1' in lignes[0]
    # le maillon 2 est chaîné au maillon 1 (et non à la genèse) : seule la ligne de nuls est signalée
    problemes = journal.verifier().problemes
    assert problemes and all("séquence" not in p and "précédent rompu" not in p for p in problemes)


def test_limite_connue_retirer_la_fin_du_journal_n_est_pas_detectable_et_la_doc_le_dit(journal):
    """LIMITE (pas une faille corrigée) : sans ancre externe, supprimer les dernières lignes laisse une chaîne valide.
    Le test fige ce comportement ET l'exigence que la documentation d'architecture le dise (pas de sur-promesse)."""
    from pathlib import Path

    for _ in range(4):
        journal.ajouter(_span())
    chemin = _segment(journal)
    lignes = chemin.read_text(encoding="utf-8").splitlines()
    chemin.write_text("\n".join(lignes[:2]) + "\n", encoding="utf-8")  # deux dernières lignes retirées
    assert journal.verifier().ok is True and journal.verifier().enregistrements == 2
    doc = (Path(__file__).resolve().parents[1] / "docs" / "architecture" / "OBSERVABILITE-MCP.md").read_text("utf-8")
    assert "DERNIÈRES lignes du dernier segment" in doc and "ancre externe" in doc
