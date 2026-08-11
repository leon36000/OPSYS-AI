"""Tests du ledger append-only hash-chaîné de l'exécution (C01-001).

Contrat exact (task spec `tasks/C01-001.md`) :
- `append_event(path: Path, event: dict) -> str` : ajoute un événement, retourne
  son `event_hash` (str hex sha256).
- `replay_state(path: Path) -> dict` : rejoue le journal depuis le début,
  vérifie la chaîne (previous_hash -> event_hash), lève `LedgerCorruptionError`
  sur toute suppression, réordonnancement ou modification.
- JSON canonique UTF-8, chaînage previous_hash/event_hash, jamais de
  modification d'une ligne existante (append-only), écriture par verrou +
  fsync.

Écrit par l'Orchestrateur AVANT toute implémentation (RED d'abord, TDD) —
le crew implémente `tools/proof/state_ledger.py` CONTRE ce fichier, jamais
l'inverse.

Note de conception (mutation-testée) : un contrôle explicite "previous_hash
déjà vu" (bifurcation) a été ENVISAGÉ puis RETIRÉ de l'implémentation —
mesuré structurellement redondant avec le contrôle de continuité de chaîne
(`previous_hash == valeur courante attendue`), qui rend une bifurcation
réaliste indétectable SANS être aussi détectée par la continuité, sauf
collision SHA-256 (hors modèle de menace). Les 3 sous-tests ci-dessous pour
séquence/chaîne/hash sont conçus pour s'ISOLER mutuellement (forger un
enregistrement qui viole EXACTEMENT un seul contrôle, les deux autres
restant satisfaits) — sinon la mutation d'un contrôle redondant ne fait
jamais rougir aucun test (piège mesuré une fois avant correction : les
sous-cas suppression/réordonnancement du test _1 cassent SIMULTANÉMENT
sequence ET chaîne, donc désactiver l'un OU l'autre seul ne les faisait pas
rougir)."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path

import pytest

from tools.proof.state_ledger import (
    LedgerCorruptionError,
    append_event,
    replay_state,
)


def _lignes(path: Path) -> list[str]:
    return [ligne for ligne in path.read_text(encoding="utf-8").splitlines() if ligne.strip()]


def _ecrire_lignes(path: Path, lignes: list[str]) -> None:
    path.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def _canonique(obj: object) -> str:
    """Réplique le format canonique DOCUMENTÉ (spec, pas l'implémentation
    privée) — utilisé pour forger des enregistrements auto-cohérents dans
    les tests d'isolation ci-dessous."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_forge(sequence: int, previous_hash: str, event: dict) -> str:
    payload = {"sequence": sequence, "previous_hash": previous_hash, "event": event}
    return hashlib.sha256(_canonique(payload).encode("utf-8")).hexdigest()


def test_installer_le_ledger_append_only_de_l_ex_cution_1(tmp_path):
    """Cas RED obligatoire : détecter suppression, réordonnancement et
    modification d'un événement — les 3 sous-cas doivent lever
    LedgerCorruptionError, jamais passer en silence."""
    path = tmp_path / "ledger.jsonl"
    for i in range(4):
        append_event(path, {"i": i, "action": f"etape-{i}"})

    # Référence : la chaîne intacte se rejoue sans erreur.
    replay_state(path)
    lignes_intactes = _lignes(path)
    assert len(lignes_intactes) == 4

    # Sous-cas SUPPRESSION : retirer une ligne du milieu.
    lignes = list(lignes_intactes)
    del lignes[1]
    _ecrire_lignes(path, lignes)
    with pytest.raises(LedgerCorruptionError):
        replay_state(path)

    # Sous-cas RÉORDONNANCEMENT : permuter deux lignes.
    lignes = list(lignes_intactes)
    lignes[1], lignes[2] = lignes[2], lignes[1]
    _ecrire_lignes(path, lignes)
    with pytest.raises(LedgerCorruptionError):
        replay_state(path)

    # Sous-cas MODIFICATION : altérer le contenu d'un événement en place
    # (event_hash ne correspond plus au contenu recalculé).
    lignes = list(lignes_intactes)
    record = json.loads(lignes[2])
    record["event"]["action"] = "falsifie"
    lignes[2] = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    _ecrire_lignes(path, lignes)
    with pytest.raises(LedgerCorruptionError):
        replay_state(path)


def test_installer_le_ledger_append_only_de_l_ex_cution_2(tmp_path):
    """Cas RED obligatoire : refuser deux événements concurrents avec même
    previous_hash — des écritures VRAIMENT concurrentes (ThreadPoolExecutor,
    verrou de fichier partagé) ne doivent jamais produire de bifurcation de
    chaîne ; le verrou sérialise, personne ne "gagne" sur un previous_hash
    déjà consommé."""
    path = tmp_path / "ledger-concurrent.jsonl"
    n = 12

    def _ecrire(i: int) -> str:
        return append_event(path, {"writer": i})

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as executor:
        hashes = list(executor.map(_ecrire, range(n)))

    assert len(hashes) == n
    assert len(set(hashes)) == n, "deux écritures concurrentes ont produit le même event_hash"

    etat = replay_state(path)
    assert etat["sequence"] == n - 1
    assert len(etat["events"]) == n

    # Second claimant forgé pour le MÊME previous_hash qu'un événement déjà
    # consommé par la chaîne (hors API, directement sur le fichier) : la
    # continuité de chaîne doit refuser ce second claimant, previous_hash
    # ne pouvant jamais légitimement "reculer" vers une valeur déjà dépassée.
    path_second_claimant = tmp_path / "ledger-second-claimant.jsonl"
    append_event(path_second_claimant, {"a": 1})
    lignes = _lignes(path_second_claimant)
    premiere = json.loads(lignes[0])
    second_claimant = {
        "sequence": premiere["sequence"] + 1,
        "previous_hash": premiere["previous_hash"],  # réutilise GENESIS, déjà "dépassé"
        "event": {"a": "second-claimant"},
    }
    second_claimant["event_hash"] = _hash_forge(
        second_claimant["sequence"], second_claimant["previous_hash"], second_claimant["event"]
    )
    _ecrire_lignes(path_second_claimant, lignes + [_canonique(second_claimant)])
    with pytest.raises(LedgerCorruptionError):
        replay_state(path_second_claimant)


def test_installer_le_ledger_append_only_de_l_ex_cution_3(tmp_path):
    """Cas RED obligatoire : rejouer un état identique depuis le journal —
    replay_state est pur/déterministe, deux appels sur le même fichier
    inchangé rendent EXACTEMENT le même état, et le fichier lui-même n'est
    jamais modifié par la lecture (append-only, jamais réécrit en place)."""
    path = tmp_path / "ledger-idempotent.jsonl"
    for i in range(6):
        append_event(path, {"sequence_metier": i, "payload": {"x": i * 2}})

    contenu_avant = path.read_text(encoding="utf-8")
    etat_1 = replay_state(path)
    etat_2 = replay_state(path)
    contenu_apres = path.read_text(encoding="utf-8")

    assert etat_1 == etat_2
    assert contenu_avant == contenu_apres, "replay_state a modifié le journal (violerait append-only)"


def test_append_event_genese_et_chainage(tmp_path):
    """Le premier événement d'un journal inexistant chaîne depuis une
    genèse fixe ; chaque event_hash suivant dépend du precedent (chaîne
    réellement liée, pas seulement des hashes indépendants)."""
    path = tmp_path / "ledger-genese.jsonl"
    assert not path.exists()

    h1 = append_event(path, {"n": 1})
    h2 = append_event(path, {"n": 2})
    assert h1 != h2

    lignes = _lignes(path)
    assert len(lignes) == 2
    rec1 = json.loads(lignes[0])
    rec2 = json.loads(lignes[1])
    assert rec1["sequence"] == 0
    assert rec2["sequence"] == 1
    assert rec2["previous_hash"] == rec1["event_hash"] == h1
    assert rec1["previous_hash"] != rec2["previous_hash"]


def test_replay_state_journal_vide_ou_absent(tmp_path):
    """Un journal absent ou vide rejoue vers un état vide déterministe,
    jamais une exception — l'absence de journal n'est pas une corruption."""
    path_absent = tmp_path / "jamais-cree.jsonl"
    etat = replay_state(path_absent)
    assert etat["events"] == []
    assert etat["sequence"] == -1

    path_vide = tmp_path / "vide.jsonl"
    path_vide.write_text("", encoding="utf-8")
    etat_vide = replay_state(path_vide)
    assert etat_vide == etat


def test_append_event_canonical_json_utf8(tmp_path):
    """Le format sur disque est du JSON canonique UTF-8 (clés triées,
    séparateurs compacts) — vérifié en relisant la ligne brute, pas
    seulement en repassant par l'API."""
    path = tmp_path / "ledger-canonique.jsonl"
    append_event(path, {"zeta": 1, "alpha": "é è à ç", "beta": [1, 2, 3]})
    ligne = _lignes(path)[0]
    record = json.loads(ligne)
    reserialise = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert ligne == reserialise, "la ligne écrite n'est pas en JSON canonique (clés triées, séparateurs compacts)"
    assert "é è à ç" in ligne, "ensure_ascii doit être False (UTF-8 réel, pas des échappements unicode)"


def test_replay_state_detecte_sequence_mensongere_isolee(tmp_path):
    """Isole le contrôle de SÉQUENCE : un enregistrement forgé dont le
    `previous_hash` est CORRECT (chaîne intacte) et le `event_hash` est
    AUTO-COHÉRENT (recalculé pour son propre contenu, y compris sa
    `sequence` mensongère) ne peut être détecté QUE par le contrôle
    séquence == index positionnel — les contrôles chaîne et hash, pris
    séparément, le laisseraient passer."""
    path = tmp_path / "ledger-sequence-mensongere.jsonl"
    h0 = append_event(path, {"a": 0})
    lignes = _lignes(path)

    sequence_mensongere = 99  # n'importe quelle valeur != index réel (1)
    forge = {
        "sequence": sequence_mensongere,
        "previous_hash": h0,  # CORRECT : vrai prédécesseur
        "event": {"a": "sequence-mensongere"},
    }
    forge["event_hash"] = _hash_forge(sequence_mensongere, h0, forge["event"])  # AUTO-COHÉRENT
    _ecrire_lignes(path, lignes + [_canonique(forge)])

    with pytest.raises(LedgerCorruptionError):
        replay_state(path)


def test_replay_state_detecte_previous_hash_mensonger_isole(tmp_path):
    """Isole le contrôle de CHAÎNE : un enregistrement forgé dont la
    `sequence` est CORRECTE (correspond à sa position réelle) et le
    `event_hash` est AUTO-COHÉRENT ne peut être détecté QUE par le
    contrôle previous_hash == valeur courante attendue — un `previous_hash`
    arbitraire (ni la genèse, ni le hash du vrai prédécesseur) doit être
    refusé même si tout le reste de l'enregistrement est interne
    cohérent."""
    path = tmp_path / "ledger-chaine-mensongere.jsonl"
    append_event(path, {"a": 0})
    lignes = _lignes(path)

    sequence_correcte = 1  # correspond bien à l'index réel de la 2e ligne
    previous_hash_arbitraire = hashlib.sha256(b"valeur-qui-ne-chaine-nulle-part").hexdigest()
    forge = {
        "sequence": sequence_correcte,
        "previous_hash": previous_hash_arbitraire,  # FAUX : ne chaîne à rien de réel
        "event": {"a": "chaine-mensongere"},
    }
    forge["event_hash"] = _hash_forge(sequence_correcte, previous_hash_arbitraire, forge["event"])
    _ecrire_lignes(path, lignes + [_canonique(forge)])

    with pytest.raises(LedgerCorruptionError):
        replay_state(path)
