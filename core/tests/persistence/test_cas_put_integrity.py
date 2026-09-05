"""Régression #620 : ne pas réutiliser/résurrecter un objet corrompu.

Les objets et les corruptions sont créés uniquement sous tmp_path. Une
corruption doit être refusée, pas réparée ni effacée silencieusement.
"""
from __future__ import annotations

import builtins
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import sys
from threading import Barrier
from typing import BinaryIO, Literal

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from opsys_core.objects import local_cas  # noqa: E402
from opsys_core.objects.local_cas import (  # noqa: E402
    CasLocal,
    HashMismatch,
    ObjetSupprimeLogiquement,
)


@pytest.mark.parametrize("supprime", [False, True], ids=["vivant", "tombstone"])
@pytest.mark.parametrize("corruption", ["meme_taille", "tronque", "allonge"])
def test_put_refuse_corruption_sans_reparation_ni_resurrection(
    tmp_path: Path, supprime: bool, corruption: str,
) -> None:
    contenu = b"a" * 200_000
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(contenu))
    chemin = tmp_path / ref.sha256[:2] / ref.sha256[2:]
    tombstone = chemin.with_name(chemin.name + ".supprime")
    if supprime:
        cas.supprimer_logiquement(ref)

    if corruption == "meme_taille":
        # Mutation après le premier bloc : taille seule ou préfixe ne suffisent pas.
        corrompu = contenu[:100_000] + b"b" + contenu[100_001:]
    elif corruption == "tronque":
        corrompu = contenu[:-1]
    else:
        corrompu = contenu + b"b"
    chemin.write_bytes(corrompu)

    with pytest.raises(HashMismatch):
        cas.put(BytesIO(contenu))

    assert chemin.read_bytes() == corrompu
    assert tombstone.exists() is supprime
    assert [p for p in tmp_path.iterdir() if p.is_file()] == []
    if supprime:
        with pytest.raises(ObjetSupprimeLogiquement):
            cas.get(ref)
    else:
        with pytest.raises(HashMismatch):
            cas.get(ref)


@pytest.mark.parametrize("supprime", [False, True], ids=["vivant", "tombstone"])
@pytest.mark.parametrize("contenu", [b"", b"sain", b"a" * 200_000], ids=["vide", "court", "multibloc"])
def test_put_sain_reste_idempotent_et_resurrectable(
    tmp_path: Path, supprime: bool, contenu: bytes,
) -> None:
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(contenu))
    if supprime:
        cas.supprimer_logiquement(ref)
    assert cas.put(BytesIO(contenu)) == ref
    with cas.get(ref) as flux:
        assert flux.tell() == 0
        assert flux.read() == contenu
    assert [p for p in tmp_path.iterdir() if p.is_file()] == []


def test_verification_put_ferme_le_descripteur_du_contenu_existant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cas = CasLocal(tmp_path)
    contenu = b"objet sain"
    ref = cas.put(BytesIO(contenu))
    ouverts: list[BinaryIO] = []

    def ouvrir(chemin: Path, mode: Literal["rb"]) -> BinaryIO:
        flux = builtins.open(chemin, mode)
        ouverts.append(flux)
        return flux

    monkeypatch.setattr(local_cas, "open", ouvrir, raising=False)
    assert cas.put(BytesIO(contenu)) == ref
    assert len(ouverts) == 1
    assert ouverts[0].closed


def test_verification_corruption_ferme_le_descripteur(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cas = CasLocal(tmp_path)
    contenu = b"objet sain"
    ref = cas.put(BytesIO(contenu))
    chemin = tmp_path / ref.sha256[:2] / ref.sha256[2:]
    chemin.write_bytes(b"objet faux")
    ouverts: list[BinaryIO] = []

    def ouvrir(cible: Path, mode: Literal["rb"]) -> BinaryIO:
        flux = builtins.open(cible, mode)
        ouverts.append(flux)
        return flux

    monkeypatch.setattr(local_cas, "open", ouvrir, raising=False)
    with pytest.raises(HashMismatch):
        cas.put(BytesIO(contenu))
    assert len(ouverts) == 1
    assert ouverts[0].closed


def test_echec_entree_sortie_ne_devient_pas_resurrection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cas = CasLocal(tmp_path)
    contenu = b"objet inaccessible"
    ref = cas.put(BytesIO(contenu))
    cas.supprimer_logiquement(ref)
    chemin = tmp_path / ref.sha256[:2] / ref.sha256[2:]
    tombstone = chemin.with_name(chemin.name + ".supprime")

    def refuser_lecture(cible: Path, mode: str) -> BinaryIO:
        raise PermissionError("lecture refusee pour le test")

    monkeypatch.setattr(local_cas, "open", refuser_lecture, raising=False)
    with pytest.raises(PermissionError, match="lecture refusee pour le test"):
        cas.put(BytesIO(contenu))
    assert tombstone.exists()
    assert chemin.read_bytes() == contenu
    assert [p for p in tmp_path.iterdir() if p.is_file()] == []


def test_get_retourne_le_descripteur_deja_verifie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cas = CasLocal(tmp_path)
    contenu = b"lecture sans reouverture"
    ref = cas.put(BytesIO(contenu))
    ouverts: list[BinaryIO] = []

    def ouvrir(chemin: Path, mode: Literal["rb"]) -> BinaryIO:
        flux = builtins.open(chemin, mode)
        ouverts.append(flux)
        return flux

    monkeypatch.setattr(local_cas, "open", ouvrir, raising=False)
    with cas.get(ref) as flux:
        assert len(ouverts) == 1
        assert flux is ouverts[0]
        assert flux.tell() == 0
        assert flux.read() == contenu
    assert ouverts[0].closed


def test_resurrection_concurrente_saine_reste_idempotente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cas = CasLocal(tmp_path)
    contenu = b"resurrection concurrente saine"
    ref = cas.put(BytesIO(contenu))
    cas.supprimer_logiquement(ref)
    chemin = tmp_path / ref.sha256[:2] / ref.sha256[2:]
    tombstone = chemin.with_name(chemin.name + ".supprime")
    rendez_vous = Barrier(2)
    unlink_original = Path.unlink

    def unlink_synchronise(cible: Path, missing_ok: bool = False) -> None:
        if cible == tombstone:
            rendez_vous.wait(timeout=5)
        unlink_original(cible, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_synchronise)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(cas.put, BytesIO(contenu)) for _ in range(2)]
        resultats = [future.result(timeout=10) for future in futures]
    assert resultats == [ref, ref]
    assert not tombstone.exists()
    with cas.get(ref) as flux:
        assert flux.read() == contenu
