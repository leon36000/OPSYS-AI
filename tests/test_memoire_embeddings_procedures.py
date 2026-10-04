"""Contrat du profil local réservé au vectoriseur explicite M03; aucune inférence réelle."""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from copy import deepcopy

import pytest

from opsys.memoire.__main__ import _limite_bornee
from opsys.memoire.embeddings import ClientEmbeddings, ErreurEmbeddings, _valider_profil
from opsys.memoire.serveur_embeddings_local import (
    RECETTE_EMBEDDING,
    ErreurRequete,
    ServeurEmbeddingsLocal,
    _profil_embedding,
)


class _MoteurFictif:
    def embed_one(self, texte: str, delai_s: float):
        if texte == "limite tokens fictive":
            raise ErreurRequete("entrée au-delà du maximum tokens", "input_token_limit_exceeded")
        return [1.0] + [0.0] * 1023, 9


@contextmanager
def _provider_fictif():
    serveur = ServeurEmbeddingsLocal(("127.0.0.1", 0), cle="x" * 32, moteur=_MoteurFictif(), delai_s=1)
    thread = threading.Thread(target=serveur.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = serveur.server_address
        yield f"http://{host}:{port}/v1"
    finally:
        serveur.shutdown()
        serveur.server_close()
        thread.join(2)


def test_recette_fingerprint_couvre_revision_tokenisation_pooling_normalisation_et_prefixes():
    profil = _profil_embedding()
    assert profil["id"] == _valider_profil(profil, "BAAI/bge-m3", 1024)
    assert RECETTE_EMBEDDING["model_revision"].endswith("4de13258303883538bd53b696b452bf8099f0858")
    assert RECETTE_EMBEDDING["tokenization"] == {
        "add_special_tokens": True,
        "truncation": False,
        "max_tokens": 512,
    }
    assert RECETTE_EMBEDDING["pooling"] == "cls-first-token"
    assert RECETTE_EMBEDDING["normalization"] == "l2-float32"
    assert RECETTE_EMBEDDING["document_prefix"] == RECETTE_EMBEDDING["query_prefix"] == ""
    changed = {**profil, "recipe": {**profil["recipe"], "query_prefix": "query: "}}
    with pytest.raises(ErreurEmbeddings, match="empreinte de profil"):
        _valider_profil(changed, "BAAI/bge-m3", 1024)


@pytest.mark.parametrize(
    ("mutation",),
    [
        ("missing-model-hash",),
        ("extra-field",),
        ("dimension-float",),
        ("dimension-bool",),
        ("max-tokens-float",),
        ("max-tokens-bool",),
        ("truncation",),
        ("model-revision",),
        ("tokenizer-hash",),
        ("pooling",),
        ("document-prefix",),
    ],
)
def test_recette_adversariale_refusee_meme_avec_sha_recalcule(mutation):
    profil = deepcopy(_profil_embedding())
    recette = profil["recipe"]
    if mutation == "missing-model-hash":
        del recette["model_sha256"]
    elif mutation == "extra-field":
        recette["future"] = "valeur"
    elif mutation == "dimension-float":
        recette["dimension"] = 1024.0
    elif mutation == "dimension-bool":
        recette["dimension"] = True
    elif mutation == "max-tokens-float":
        recette["tokenization"]["max_tokens"] = 512.0
    elif mutation == "max-tokens-bool":
        recette["tokenization"]["max_tokens"] = True
    elif mutation == "truncation":
        recette["tokenization"]["truncation"] = True
    elif mutation == "model-revision":
        recette["model_revision"] = "revision-fictive"
    elif mutation == "tokenizer-hash":
        recette["tokenizer_sha256"] = "0" * 64
    elif mutation == "pooling":
        recette["pooling"] = "mean"
    elif mutation == "document-prefix":
        recette["document_prefix"] = "passage: "
    canonique = json.dumps(recette, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    profil["id"] = hashlib.sha256(canonique.encode("ascii")).hexdigest()
    with pytest.raises(ErreurEmbeddings, match="recette locale canonique"):
        _valider_profil(profil, "BAAI/bge-m3", 1024)


def test_handshake_authentifie_et_reponse_embedding_reporte_le_meme_profil():
    with _provider_fictif() as url:
        client = ClientEmbeddings(url, "BAAI/bge-m3", cle="x" * 32, local=True, taille_lot=1)
        lot = client.plonger_avec_profil(["procédure fictive de toiture"])
    assert lot.profile_sha256 == _profil_embedding()["id"]
    assert len(lot.vecteurs) == 1 and len(lot.vecteurs[0]) == 1024


def test_limite_tokens_provider_propage_le_code_machine_exact():
    with _provider_fictif() as url:
        client = ClientEmbeddings(url, "BAAI/bge-m3", cle="x" * 32, local=True, taille_lot=1)
        with pytest.raises(ErreurEmbeddings) as erreur:
            client.plonger_avec_profil(["limite tokens fictive"])
    assert erreur.value.http_status == 413
    assert erreur.value.code == "input_token_limit_exceeded"


def test_http_413_limite_caracteres_porte_un_code_distinct():
    with _provider_fictif() as url:
        client = ClientEmbeddings(url, "BAAI/bge-m3", cle="x" * 32, local=True, taille_lot=1)
        with pytest.raises(ErreurEmbeddings) as erreur:
            client.plonger_avec_profil(["x" * 20_001])
    assert erreur.value.http_status == 413
    assert erreur.value.code == "input_character_limit_exceeded"


def test_fingerprint_de_chaque_reponse_doit_correspondre_au_handshake(monkeypatch):
    with _provider_fictif() as url:
        client = ClientEmbeddings(url, "BAAI/bge-m3", cle="x" * 32, local=True, taille_lot=1)
        monkeypatch.setattr(
            ClientEmbeddings,
            "_appeler_reponse",
            lambda self, lot: ([[1.0] + [0.0] * 1023], "f" * 64),
        )
        with pytest.raises(ErreurEmbeddings, match="différente du handshake"):
            client.plonger_avec_profil(["texte fictif"])


def test_profil_distant_refuse_avant_appel():
    client = ClientEmbeddings("http://127.0.0.1:1/v1", "BAAI/bge-m3", local=False)
    with pytest.raises(ErreurEmbeddings, match="explicitement local"):
        client.verifier_profil_local()


@pytest.mark.parametrize(("valeur", "attendue"), [("1", 1), ("8", 8)])
def test_limite_cli_bornee_et_canonique(valeur, attendue):
    assert _limite_bornee(valeur) == attendue


@pytest.mark.parametrize("valeur", ["0", "9", "08", "999999999999999999", "١"])
def test_limite_cli_invalide_refusee_sans_conversion_non_bornee(valeur):
    from argparse import ArgumentTypeError

    with pytest.raises(ArgumentTypeError):
        _limite_bornee(valeur)
