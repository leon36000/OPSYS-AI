"""Producteur RAM fictif : aucun SQL, RPC, DEVICE ou stockage mobile qualifié."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from m10_memoire import documents_affaire as d

FICTIF = True
AFFAIRE = "chantier-fictif"
AUTRE = "autre-affaire-fictive"
CORPS = "Aé😀\r\nZ"
META = {
    "version_schema", "affaire_id", "document_ref", "version_source", "statut", "titre",
    "methode", "source_sha256", "taille_points", "taille_octets", "auteur", "horodatage", "activation_ref",
}
LIGNE = META | {"version_no", "version_precedente_attendue", "activation_attendue"}
TOP = {"version_schema", "affaire_id", "decalage", "limite", "total_versions", "suivant_decalage", "versions"}


def contexte(cible=AFFAIRE, **changes):
    result = {
        "affaire_id": cible,
        "auteur": {"personne": "admin_fictif", "role": "admin", "source": "appareil"},
        "situation": {
            "connue": True, "origine_recue": False, "origine": None, "verdict": "AMONT-ORIGINE-NON-RECUE",
        },
        "mode": "ombre", "quota": 200000,
    }
    result.update(changes)
    return result


def reference(chain, index):
    return {"registre": "documents_affaire", "index": index, "ligne_id": chain[index]["ligne_id"]}


def ajouter(chain, operation, args):
    ctx = contexte(args["affaire_id"])
    ctx.update(
        intention={
            "appareil": "appareil-fictif", "cle": f"intention-fictive-{len(chain)}",
            "outil": d.OUTILS[operation],
            "empreinte_arguments": hashlib.sha256(
                json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        horodatage_appareil_declare="2026-10-10T02:03:04.123456+00:00",
        horodatage="2026-10-10T02:03:05.654321+00:00",
    )
    preparer = {"deposer": d.preparer_depot, "activer": d.preparer_activation, "retirer": d.preparer_retrait}
    return chain + [preparer[operation](chain, args, ctx)]


def depot(chain, cible=AFFAIRE, root=None, precedent=None, corps=CORPS):
    return ajouter(chain, "deposer", {
        "affaire_id": cible, "document_ref": reference(chain, root) if root is not None else None,
        "version_precedente": reference(chain, precedent) if precedent is not None else None,
        "titre": "Note fictive 😀", "corps": corps, "confidentialite": "INTERNAL",
    })


def activer(chain, root, version, attendu=None):
    return ajouter(chain, "activer", {
        "affaire_id": chain[root]["affaire_id"], "document_ref": reference(chain, root),
        "version_source": reference(chain, version),
        "activation_attendue": reference(chain, attendu) if attendu is not None else None,
    })


def retirer(chain, root, attendu=None):
    return ajouter(chain, "retirer", {
        "affaire_id": chain[root]["affaire_id"], "document_ref": reference(chain, root),
        "activation_attendue": reference(chain, attendu) if attendu is not None else None,
        "code_motif": "RETRAIT_ACCES",
    })


def commande(cible=AFFAIRE, decalage=0, limite=1):
    return {"affaire_id": cible, "decalage": decalage, "limite": limite}


def lire(chain, args=None, ctx=None):
    fonction = getattr(d, "lister_versions_documentaires", None)
    assert callable(fonction), "l'index pur documentaire n'est pas livré"
    return fonction(chain, commande() if args is None else args, contexte() if ctx is None else ctx)


def test_index_vide_ferme_et_import_checkout():
    assert lire([]) == {
        "version_schema": 1, "affaire_id": AFFAIRE, "decalage": 0, "limite": 1,
        "total_versions": 0, "suivant_decalage": None, "versions": [],
    }
    assert Path(d.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[3])


def test_metadata_exacte_utf8_sans_corps_ni_intention():
    chain = depot([])
    dto = lire(chain)
    row = dto["versions"][0]
    assert set(dto) == TOP and set(row) == LIGNE
    detail = d.lire_version(chain, AFFAIRE, reference(chain, 0), reference(chain, 0), contexte())
    assert {k: row[k] for k in META} == {k: v for k, v in detail.items() if k != "corps"}
    assert row["source_sha256"] == hashlib.sha256(bytes.fromhex("41c3a9f09f98800d0a5a")).hexdigest()
    assert (row["taille_points"], row["taille_octets"], row["version_no"]) == (6, 10, 1)
    assert row["version_precedente_attendue"] == reference(chain, 0)
    assert row["activation_attendue"] is None and row["activation_ref"] is None
    assert row["horodatage"] == "2026-10-10T02:03:05.654321+00:00"
    assert "corps" not in json.dumps(dto, ensure_ascii=False) and CORPS not in json.dumps(dto, ensure_ascii=False)


def test_v2_deposee_v1_active_et_attentes_documentaires_separees():
    chain = activer(depot([]), 0, 0)
    chain = depot(chain, root=0, precedent=0, corps="V2 fictive\n")
    rows = lire(chain, commande(limite=8))["versions"]
    assert [r["version_source"]["index"] for r in rows] == [0, 2]
    assert [r["statut"] for r in rows] == ["COURANTE", "DEPOSEE_NON_ACTIVEE"]
    assert [r["version_no"] for r in rows] == [1, 2]
    assert all(r["version_precedente_attendue"] == reference(chain, 2) for r in rows)
    assert all(r["activation_attendue"] == reference(chain, 1) for r in rows)
    assert [r["activation_ref"] for r in rows] == [reference(chain, 1), None]


def test_reactivation_ABA_garde_activation_historique_et_cas_courant():
    chain = activer(depot([]), 0, 0)
    chain = depot(chain, root=0, precedent=0)
    chain = activer(chain, 0, 2, 1)
    chain = activer(chain, 0, 0, 3)
    rows = lire(chain, commande(limite=8))["versions"]
    assert [r["statut"] for r in rows] == ["COURANTE", "HISTORIQUE_NON_COURANTE"]
    assert [r["activation_ref"] for r in rows] == [reference(chain, 4), reference(chain, 3)]
    assert all(r["activation_attendue"] == reference(chain, 4) for r in rows)
    assert all(r["version_precedente_attendue"] == reference(chain, 2) for r in rows)


def test_toutes_versions_retirees_sans_corps_et_pas_de_statut_invente():
    chain = activer(depot([]), 0, 0)
    chain = depot(chain, root=0, precedent=0)
    chain = retirer(chain, 0, 1)
    rows = lire(chain, commande(limite=8))["versions"]
    assert [r["statut"] for r in rows] == ["RETIREE", "RETIREE"]
    assert [r["activation_ref"] for r in rows] == [reference(chain, 1), None]
    assert all(r["activation_attendue"] == reference(chain, 1) for r in rows)
    assert all(set(r) == LIGNE and "corps" not in r for r in rows)


def test_multiaffaire_ordre_indices_originaux_et_pages_remplacees():
    chain = depot(depot([], AUTRE))
    chain = depot(chain, AUTRE, root=0, precedent=0)
    chain = depot(chain, root=1, precedent=1)
    chain = depot(chain)
    first = lire(chain)
    assert first["total_versions"] == 3 and first["suivant_decalage"] == 1
    assert first["versions"][0]["version_source"] == reference(chain, 1)
    suite = lire(chain, commande(decalage=1, limite=8))
    assert [r["version_source"]["index"] for r in suite["versions"]] == [3, 4]
    assert suite["suivant_decalage"] is None
    assert all(r["affaire_id"] == AFFAIRE for r in suite["versions"])
    chain = activer(chain, 1, 1)
    replacement = lire(chain)
    assert first["versions"][0]["statut"] == "DEPOSEE_NON_ACTIVEE"
    assert replacement["versions"][0]["statut"] == "COURANTE"
    assert replacement["versions"][0]["activation_attendue"] == reference(chain, 5)


def test_maximum64_versions_et_fin_vide_64_sans_reparer_decalage():
    chain = []
    for _ in range(8):
        root = len(chain)
        chain = depot(chain)
        for _ in range(7):
            chain = depot(chain, root=root, precedent=len(chain) - 1)
    last = lire(chain, commande(decalage=56, limite=8))
    assert last["total_versions"] == 64 and last["suivant_decalage"] is None
    assert [r["version_source"]["index"] for r in last["versions"]] == list(range(56, 64))
    empty = lire(chain, commande(decalage=64))
    assert empty["decalage"] == 64 and empty["total_versions"] == 64 and empty["versions"] == []
    assert empty["suivant_decalage"] is None


@pytest.mark.parametrize("args", [
    [], [["affaire_id", AFFAIRE]], "CANARI-FICTIF", {"affaire_id": AFFAIRE, "decalage": 0},
    {**commande(), "extra": "CANARI-FICTIF"}, commande(decalage=True), commande(limite=True),
    commande(decalage=-1), commande(decalage=65), commande(limite=0), commande(limite=9),
    commande(decalage=1.0), commande(limite="1"), commande(cible="invalide/affaire"),
])
def test_arguments_plain_fermes_bornes_et_sans_echo(args):
    before = copy.deepcopy(args)
    with pytest.raises(d.RefusDocument) as exc:
        lire([], args)
    assert args == before and "CANARI" not in str(exc.value)
    assert exc.value.code in ("REJ-M10-DOC-FORME-INVALIDE", "REJ-M10-DOC-AUTORITE-INVALIDE")


def test_None_commande_est_refuse_sans_default_implicite():
    fonction = getattr(d, "lister_versions_documentaires", None)
    assert callable(fonction), "l'index pur documentaire n'est pas livré"
    with pytest.raises(d.RefusDocument):
        fonction([], None, contexte())


@pytest.mark.parametrize("mode", ["ombre", "supervise", "autonome"])
def test_modes_lecture_et_contexte5_sans_Meta(mode):
    assert lire(depot([]), ctx=contexte(mode=mode))["total_versions"] == 1


@pytest.mark.parametrize("changes", [
    {"intention": {}}, {"horodatage": "2026-10-10T02:00:00Z"}, {"quota": True}, {"quota": 0},
    {"mode": "invente"}, {"affaire_id": AUTRE},
    {"auteur": {"personne": "admin_fictif", "role": "employee", "source": "appareil"}},
    {"auteur": {"personne": "admin_fictif", "role": "admin", "source": "console"}},
    {"situation": {"connue": False, "origine_recue": False, "origine": None, "verdict": "AMONT-AFFAIRE-INCONNUE"}},
])
def test_contexte_ferme_avant_analyse(changes, monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError("registre consulté avant admission du contexte")
    monkeypatch.setattr(d, "_analyse", interdit)
    with pytest.raises(d.RefusDocument):
        lire([], ctx=contexte(**changes))


def test_quota_mesure_enveloppe_entiere_exacte_et_refus_sans_fragment():
    chain = depot(depot(depot(depot([]))))
    args = commande(limite=4)
    dto = lire(chain, args)
    frame = {"ok": True, "resultat": {"accepte": True, "resultat": dto}}
    size = len(json.dumps(frame, ensure_ascii=False, allow_nan=False))
    assert lire(chain, args, contexte(quota=size)) == dto
    for quota in (size - 1, 40, 1):
        with pytest.raises(d.RefusDocument) as exc:
            lire(chain, args, contexte(quota=quota))
        assert exc.value.code == "REJ-M10-DOC-QUOTA-DEPASSE" and "Note fictive" not in str(exc.value)


def test_corps_trop_volumineux_pour_detail_n_empeche_pas_index_metadata():
    chain = depot([], corps="\x01" * 2000)
    assert lire(chain, ctx=contexte(quota=6000))["total_versions"] == 1
    with pytest.raises(d.RefusDocument) as exc:
        d.lire_version(chain, AFFAIRE, reference(chain, 0), reference(chain, 0), contexte(quota=6000))
    assert exc.value.code == "REJ-M10-DOC-QUOTA-DEPASSE"


def test_copies_independantes_et_lecture_ne_modifie_rien():
    chain = activer(depot([]), 0, 0)
    args, ctx = commande(), contexte()
    before = copy.deepcopy((chain, args, ctx))
    dto = lire(chain, args, ctx)
    row = dto["versions"][0]
    row["auteur"]["personne"] = "autre-fictif"
    row["activation_ref"]["index"] = 99
    row["version_precedente_attendue"]["index"] = 88
    assert (chain, args, ctx) == before
    assert row["activation_attendue"]["index"] == 1
    assert row["version_source"]["index"] == 0


def test_corruption_hors_page_et_hors_affaire_est_refusee_sans_partiel():
    chain = depot(depot([], AUTRE))
    chain[0]["corps"] = "CANARI-CORROMPU-FICTIF"
    with pytest.raises(d.RefusDocument) as exc:
        lire(chain)
    assert "CANARI" not in str(exc.value) and "Note fictive" not in str(exc.value)


def test_sous_classes_et_getters_non_executees():
    class Objet(dict):
        def items(self):
            raise AssertionError("getter arbitraire")
    class Texte(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("encode arbitraire")
    for args in (Objet(commande()), {**commande(), "affaire_id": Texte(AFFAIRE)}):
        with pytest.raises(d.RefusDocument):
            lire([], args)
