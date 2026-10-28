"""Captures fictives : le codec ne prouve ni origine, ni autorité, ni réception."""
import tracemalloc
from dataclasses import FrozenInstanceError
from hashlib import sha256
from importlib import import_module, util

import pytest

SOURCE = b"From: fictif@example.test\r\nMessage-ID: <fictif@example.test>\r\n\r\nCorps\x00\xff"
ERREUR = "REJ-M1-COURRIEL-ORIGINAL-INVALIDE"


def valider_original(arguments, *, source):
    return import_module("opsys.reception_courriel_contrat").valider_original(arguments, source=source)


def test_contrat_original_disponible():
    assert util.find_spec("opsys.reception_courriel_contrat") is not None


def arguments(**changes):
    return dict({
        "version": 1,
        "instance_id": "00000000-0000-4000-8000-000000000001",
        "source_id": "a" * 64,
        "compte_id": "inbox-fictif",
        "boite": "INBOX",
        "uid_validity": "17",
        "uid": 42,
        "taille_annoncee": len(SOURCE),
        "recu_le": "2026-10-28T04:00:00.000Z",
        "date_interne": None,
        "message_id": "<fictif@example.test>",
    }, **changes)


def test_vecteur_identite_independant_et_octets_intacts():
    original = valider_original(arguments(), source=SOURCE)
    # Vecteur calculé indépendamment avec node:crypto, cadrage UTF8 documenté.
    assert original.identite_id == "d0c0989039f05131fd28403d01a360007da4abb4618ce792ce50595d1cf4cd5d"
    assert original.source == SOURCE
    assert original.source_octets == len(SOURCE)
    assert original.source_sha256 == sha256(SOURCE).hexdigest()
    assert SOURCE.hex() not in repr(original)
    assert "fictif@example.test" not in repr(original)


def test_conflit_de_contenu_ne_change_pas_identite():
    premier = valider_original(arguments(), source=SOURCE)
    autre = valider_original(arguments(), source=b"x" * len(SOURCE))
    assert premier.identite_id == autre.identite_id
    assert premier.source_sha256 != autre.source_sha256


@pytest.mark.parametrize(("cle", "valeur"), [
    ("instance_id", "00000000-0000-4000-8000-000000000002"),
    ("source_id", "b" * 64), ("compte_id", "second-fictif"),
    ("boite", "Archive"), ("boite", "inbox"), ("boite", "Réponses"),
    ("uid_validity", "18"), ("uid", 43),
])
def test_chaque_dimension_source_change_identite(cle, valeur):
    assert valider_original(arguments(**{cle: valeur}), source=SOURCE).identite_id != (
        valider_original(arguments(), source=SOURCE).identite_id
    )


def test_identite_ignore_message_id_et_horodatage_de_relecture():
    first = valider_original(arguments(), source=SOURCE)
    second = valider_original(arguments(
        message_id=None, recu_le="2026-10-28T05:00:00.000Z",
        date_interne="2026-10-27T12:00:00.001Z",
    ), source=SOURCE)
    assert first.identite_id == second.identite_id
    assert first.source_sha256 == second.source_sha256


def test_cadrage_multioctet_et_decoupage_non_ambigus():
    one = valider_original(arguments(compte_id="a", boite="b:c"), source=SOURCE)
    two = valider_original(arguments(compte_id="a_b", boite="c"), source=SOURCE)
    assert one.identite_id != two.identite_id
    composed = valider_original(arguments(boite="é"), source=SOURCE)
    decomposed = valider_original(arguments(boite="e\u0301"), source=SOURCE)
    assert composed.identite_id != decomposed.identite_id


def test_capture_immuable_et_sans_alias_du_dict_appelant():
    source = arguments()
    result = valider_original(source, source=SOURCE)
    source["boite"] = "Archive"
    assert result.arguments["boite"] == "INBOX"
    with pytest.raises(TypeError):
        result.arguments["boite"] = "Archive"
    with pytest.raises(FrozenInstanceError):
        result.source = b"autre"


@pytest.mark.parametrize(("cle", "valeur"), [
    ("version", True), ("version", 2), ("instance_id", "pas-uuid"),
    ("instance_id", "00000000-0000-4000-8000-00000000000A"),
    ("source_id", "a" * 63), ("source_id", "A" * 64),
    ("compte_id", "__proto__"), ("compte_id", "constructor"),
    ("compte_id", "avec:deux"), ("compte_id", "a" * 65),
    ("boite", ""), ("boite", "INBOX\r\ncache"), ("boite", "x\x00"),
    ("boite", "\ud800"), ("boite", "x" * 1025),
    ("uid_validity", "0"), ("uid_validity", "017"),
    ("uid_validity", "4294967296"), ("uid_validity", 17),
    ("uid", True), ("uid", 0), ("uid", 4294967296), ("uid", "42"),
    ("taille_annoncee", True), ("taille_annoncee", len(SOURCE) + 1),
    ("taille_annoncee", len(SOURCE) - 1),
    ("recu_le", "2026-02-30T04:00:00.000Z"), ("recu_le", "0000-01-01T00:00:00.000Z"),
    ("recu_le", "2026-10-28T04:00:00+00:00"), ("recu_le", None),
    ("date_interne", "date inconnue"), ("date_interne", "2026-13-28T00:00:00.000Z"),
    ("message_id", ""), ("message_id", "x\r\nsecret"),
    ("message_id", "x" * 1025), ("message_id", "\ud800"),
])
def test_refus_ferme_sans_contenu_dans_erreur(cle, valeur):
    with pytest.raises(ValueError, match=f"^{ERREUR}$"):
        valider_original(arguments(**{cle: valeur}), source=SOURCE)


@pytest.mark.parametrize("source", [b"", bytearray(SOURCE), memoryview(SOURCE), "texte"])
def test_original_exige_bytes_exacts_non_vides(source):
    with pytest.raises(ValueError, match=f"^{ERREUR}$"):
        valider_original(arguments(taille_annoncee=len(source)), source=source)


def test_bornes_de_taille_et_identifiants_imap():
    limit = 1_048_576
    data = b"x" * limit
    result = valider_original(arguments(taille_annoncee=limit, uid=4294967295,
                                        uid_validity="4294967295", boite="x" * 1024), source=data)
    assert result.source_octets == limit
    with pytest.raises(ValueError, match=f"^{ERREUR}$"):
        valider_original(arguments(taille_annoncee=limit + 1), source=data + b"x")


def test_champs_fermes_sans_hash_fourni_ou_permission_sms():
    for extra in [{"source_sha256": "0" * 64}, {"permission": "sms"}, {"lead_id": "projet-fictif"}]:
        with pytest.raises(ValueError, match=f"^{ERREUR}$"):
            valider_original(dict(arguments(), **extra), source=SOURCE)
    missing = arguments()
    del missing["source_id"]
    with pytest.raises(ValueError, match=f"^{ERREUR}$"):
        valider_original(missing, source=SOURCE)


def test_sous_classes_refusees_sans_executer_leurs_methodes():
    class HostileDict(dict):
        def __iter__(self):
            pytest.fail("appel méthode de sous-classe")

    class HostileString(str):
        def encode(self, *args, **kwargs):
            pytest.fail("appel méthode de sous-classe")

    class HostileBytes(bytes):
        def __len__(self):
            pytest.fail("appel méthode de sous-classe")

    for value, data in [(HostileDict(arguments()), SOURCE),
                        (arguments(boite=HostileString("INBOX")), SOURCE),
                        (arguments(), HostileBytes(SOURCE))]:
        with pytest.raises(ValueError, match=f"^{ERREUR}$"):
            valider_original(value, source=data)


def test_refus_longueur_avant_allocation_encodage():
    oversized = arguments(boite="x" * 2_000_000)
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match=f"^{ERREUR}$"):
            valider_original(oversized, source=SOURCE)
        _, peak = tracemalloc.get_traced_memory()
        assert peak < 512_000
    finally:
        tracemalloc.stop()


def test_borne_utf16_native_sur_caracteres_astraux():
    assert valider_original(arguments(boite="\U0001f4e7" * 512), source=SOURCE).source == SOURCE
    with pytest.raises(ValueError, match=f"^{ERREUR}$"):
        valider_original(arguments(boite="\U0001f4e7" * 513), source=SOURCE)


def test_mutation_appelant_pendant_hachage_ne_desynchronise_pas_capture(monkeypatch):
    module = import_module("opsys.reception_courriel_contrat")
    caller = arguments(boite="é" * 1024)
    expected = valider_original(dict(caller), source=SOURCE)
    native_hash = module.sha256
    changed = []

    class HashWithCallerMutation:
        """Même hash réel; mutation déterministe au point où un thread pourrait agir."""
        def __init__(self, initial):
            self.native = native_hash(initial)

        def update(self, data):
            self.native.update(data)
            if data == b"2:42":
                caller["boite"] = "Archive"
                changed.append(True)

        def hexdigest(self):
            return self.native.hexdigest()

    def hash_factory(initial):
        if initial == b"opsys:m1:courriel:identite:v1:":
            return HashWithCallerMutation(initial)
        return native_hash(initial)

    monkeypatch.setattr(module, "sha256", hash_factory)
    actual = valider_original(caller, source=SOURCE)
    assert changed == [True]
    assert caller["boite"] == "Archive"
    assert actual.arguments == expected.arguments
    assert actual.identite_id == expected.identite_id
    assert actual.source_sha256 == expected.source_sha256
