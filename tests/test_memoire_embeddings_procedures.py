"""Contrat du profil local réservé au vectoriseur explicite M03; aucune inférence réelle."""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer

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
    def __init__(self):
        self.textes = []

    def embed_one(self, texte: str, delai_s: float):
        self.textes.append(texte)
        if texte == "limite tokens fictive":
            raise ErreurRequete("entrée au-delà du maximum tokens", "input_token_limit_exceeded")
        return [1.0] + [0.0] * 1023, 9


@contextmanager
def _provider_fictif(*, moteur=None, instrumenter_slot=None):
    serveur = ServeurEmbeddingsLocal(
        ("127.0.0.1", 0), cle="x" * 32, moteur=moteur or _MoteurFictif(), delai_s=1
    )
    slot = instrumenter_slot(serveur._slot) if instrumenter_slot else None
    if slot is not None:
        serveur._slot = slot
    thread = threading.Thread(target=serveur.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = serveur.server_address
        yield f"http://{host}:{port}/v1"
    finally:
        if slot is not None:
            slot.debloquer()
        serveur.shutdown()
        serveur.server_close()
        thread.join(2)


class _SlotFinReponseRetardee:
    """Gate de test après fermeture HTTP, avant libération du slot réel du provider."""

    def __init__(self, slot, *, nombre=1, liberer_au_refus=True):
        self.slot = slot
        self.gates = [threading.Event() for _ in range(nombre)]
        self.liberer_au_refus = liberer_au_refus
        self.refus = 0
        self.liberations = 0

    def acquire(self, *args, **kwargs):
        pris = self.slot.acquire(*args, **kwargs)
        if not pris:
            self.refus += 1
            if self.liberer_au_refus:
                self.gates[min(self.refus - 1, len(self.gates) - 1)].set()
        return pris

    def release(self):
        index = self.liberations
        self.liberations += 1
        if index < len(self.gates):
            assert self.gates[index].wait(5), "gate de qualification non libérée"
        self.slot.release()

    def debloquer(self):
        for gate in self.gates:
            gate.set()


@pytest.mark.parametrize("texte,code", [
    ("limite tokens fictive", "input_token_limit_exceeded"),
    ("x" * 20_001, "input_character_limit_exceeded"),
], ids=["tokens", "caracteres"])
def test_reprise_503_apres_handshake_conserve_413_et_code_exact(texte, code):
    moteur = _MoteurFictif()
    slots = []

    def instrumenter(slot):
        retarde = _SlotFinReponseRetardee(slot)
        slots.append(retarde)
        return retarde

    with _provider_fictif(moteur=moteur, instrumenter_slot=instrumenter) as url:
        client = ClientEmbeddings(url, "BAAI/bge-m3", cle="x" * 32, local=True, taille_lot=1)
        with pytest.raises(ErreurEmbeddings) as erreur:
            client.plonger_avec_profil([texte])
    assert erreur.value.http_status == 413
    assert erreur.value.code == code
    assert slots[0].refus == 1
    assert moteur.textes == ([texte] if code == "input_token_limit_exceeded" else [])


def test_reprise_503_par_lot_apres_handshake_et_reponse_precedente():
    moteur = _MoteurFictif()
    slots = []

    def instrumenter(slot):
        retarde = _SlotFinReponseRetardee(slot, nombre=2)
        slots.append(retarde)
        return retarde

    with _provider_fictif(moteur=moteur, instrumenter_slot=instrumenter) as url:
        client = ClientEmbeddings(url, "BAAI/bge-m3", cle="x" * 32, local=True, taille_lot=1)
        lot = client.plonger_avec_profil(["premier fait fictif", "second fait fictif"])
    assert len(lot.vecteurs) == 2
    assert lot.profile_sha256 == _profil_embedding()["id"]
    assert slots[0].refus == 2
    assert moteur.textes == ["premier fait fictif", "second fait fictif"]


def test_reprise_503_est_bornee_a_deux_tentatives_sans_inference():
    moteur = _MoteurFictif()
    slots = []

    def instrumenter(slot):
        retarde = _SlotFinReponseRetardee(slot, liberer_au_refus=False)
        slots.append(retarde)
        return retarde

    with _provider_fictif(moteur=moteur, instrumenter_slot=instrumenter) as url:
        client = ClientEmbeddings(url, "BAAI/bge-m3", cle="x" * 32, local=True, taille_lot=1)
        with pytest.raises(ErreurEmbeddings) as erreur:
            client.plonger_avec_profil(["fait fictif jamais calculé"])
    assert erreur.value.http_status == 503
    assert slots[0].refus == 2
    assert moteur.textes == []


@pytest.mark.parametrize("status", [400, 401, 413, None], ids=["400", "401", "413", "timeout"])
def test_reprise_ne_rejoue_pas_les_autres_refus_http(status):
    """SDK contre HTTP local fictif : une erreur connue ne déclenche aucun nouvel appel."""
    appels = []
    publier = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def repondre(self, code, corps):
            brut = json.dumps(corps).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(brut)))
            self.end_headers()
            self.wfile.write(brut)

        def do_GET(self):
            self.repondre(200, {"status": "ready", "model": "BAAI/bge-m3", "dimension": 1024,
                               "opsys_embedding_profile": _profil_embedding()})

        def do_POST(self):
            appels.append(self.rfile.read(int(self.headers["Content-Length"])))
            if status is None:
                publier.wait(3)
                return
            self.repondre(status, {"error": {"code": "refus_http_fictif", "message": "refus"}})

    serveur = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=serveur.serve_forever, daemon=True)
    thread.start()
    try:
        client = ClientEmbeddings(f"http://127.0.0.1:{serveur.server_port}/v1", "BAAI/bge-m3",
                                  cle="x" * 32, local=True, taille_lot=1, delai_s=0.2)
        with pytest.raises(ErreurEmbeddings) as erreur:
            client.plonger_avec_profil(["fait fictif"])
        assert erreur.value.http_status == status
        assert erreur.value.code == ("refus_http_fictif" if status is not None else None)
    finally:
        publier.set()
        serveur.shutdown()
        serveur.server_close()
        thread.join(2)
    assert len(appels) == 1


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
