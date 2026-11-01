"""Nexora Creative : port, double sans réseau, adaptateur, capacités -> déclarations soumises à la politique de
licence."""

from __future__ import annotations

import socket

import fabriques_studio as f
import pytest
from m7_marketing.studio import generation, nexora, png

from opsys import stockage
from opsys.fournisseurs import politique, registre
from opsys.fournisseurs.modele import Fournisseur

ADMIN = "gestion"


@pytest.fixture(autouse=True)
def _aucun_reseau(monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError("appel réseau réel interdit en QA")

    monkeypatch.setattr(socket, "create_connection", interdit)
    monkeypatch.setattr(socket, "getaddrinfo", interdit)


def _demande(**plus):
    base = {
        "job_id": "job-n",
        "brief_id": "brief-n",
        "brief_empreinte": "a" * 64,
        "genre": "image",
        "invite": "fond sans texte",
        "invite_negative": "texte",
        "largeur": 64,
        "hauteur": 48,
        "graine": 11,
    }
    return generation.DemandeGeneration(**{**base, **plus})


def test_le_double_nexora_annonce_des_capacites_et_travaille_sans_reseau():
    port = nexora.NexoraDouble()
    assert [c["id"] for c in port.capacites()] == ["nexora-fond-1", "nexora-nc", "nexora-seuil"]
    sortie = nexora.GenerateurNexora(port, "nexora-fond-1").generer(_demande())
    assert sortie.nature == "double" and sortie.modele == "nexora-fond-1" and sortie.graine == 11
    assert (
        png.dimensions(sortie.octets) == (64, 48) and sortie.parametres["nexora"]["licence_id"] == "Nexora-Commercial"
    )
    generation.verifier_sortie(sortie, _demande())
    assert port.appels == ["capacites", "soumettre", "statut", "artefacts"]


def test_le_travail_est_idempotent_par_la_cle_de_la_demande():
    port = nexora.NexoraDouble()
    adaptateur = nexora.GenerateurNexora(port, "nexora-fond-1")
    un, deux = adaptateur.generer(_demande()), adaptateur.generer(_demande())
    assert un.octets == deux.octets and len(port._travaux) == 1


def test_un_modele_different_de_celui_demande_est_refuse_aucun_remplacement_silencieux():
    port = nexora.NexoraDouble(modele_reel_different="nexora-nc")
    with pytest.raises(generation.ErreurGeneration) as erreur:
        nexora.GenerateurNexora(port, "nexora-fond-1").generer(_demande())
    assert erreur.value.code == nexora.REJ_NEXORA_MODELE and "nexora-nc" in erreur.value.detail


def test_une_sortie_jpeg_ou_sans_licence_est_refusee():
    with pytest.raises(generation.ErreurGeneration) as erreur:
        nexora.GenerateurNexora(nexora.NexoraDouble(format_sortie="jpeg"), "nexora-fond-1").generer(_demande())
    assert "PNG" in erreur.value.detail

    class SansLicence(nexora.NexoraDouble):
        def artefacts(self, travail_id):
            return [{**super().artefacts(travail_id)[0], "licence_id": ""}]

    with pytest.raises(generation.ErreurGeneration) as erreur:
        nexora.GenerateurNexora(SansLicence(), "nexora-fond-1").generer(_demande())
    assert erreur.value.code == nexora.REJ_NEXORA_LICENCE


def test_artefact_illisible_travail_non_termine_ou_video_refuses():
    class Casse(nexora.NexoraDouble):
        def artefacts(self, travail_id):
            return [{**super().artefacts(travail_id)[0], "octets_base64": "!!pas-du-base64!!"}]

    with pytest.raises(generation.ErreurGeneration):
        nexora.GenerateurNexora(Casse(), "nexora-fond-1").generer(_demande())

    class Attente(nexora.NexoraDouble):
        def statut(self, travail_id):
            return "en_cours"

    with pytest.raises(generation.ErreurGeneration):
        nexora.GenerateurNexora(Attente(), "nexora-fond-1").generer(_demande())
    with pytest.raises(generation.ErreurGeneration):
        nexora.GenerateurNexora(nexora.NexoraDouble(), "nexora-fond-1").generer(_demande(genre="video"))


def test_les_capacites_deviennent_des_declarations_conservatrices_jamais_actives():
    declarations = {
        d["identifiant"]: d
        for d in nexora.declarations_depuis_capacites(nexora.NexoraDouble().capacites(), "https://nexora.example/v1")
    }
    assert set(declarations) == {
        "image.nexora.nexora-fond-1.api",
        "image.nexora.nexora-nc.api",
        "image.nexora.nexora-seuil.api",
    }
    for d in declarations.values():
        assert d["licence"]["verification"] == "a_lire" and d["residence_donnees"] == "inconnue" and d["mode"] == "api"
        Fournisseur.depuis_json(
            {**d, "statut_catalogue": "declare", "qualification": "a_mesurer", "licence_lue_par": None}
        )
    nc = declarations["image.nexora.nexora-nc.api"]["licence"]
    assert nc["usage_commercial"] == "interdit" and nc["service_tiers"] == "interdit"
    seuil = declarations["image.nexora.nexora-seuil.api"]["licence"]
    assert seuil["usage_commercial"] == "sous_seuil" and seuil["seuil_revenu_usd"] == 1_000_000
    assert seuil["territoires_exclus"] == ["UE", "UK"] and seuil["mention_obligatoire"] == "Powered by Nexora"
    libre = declarations["image.nexora.nexora-fond-1.api"]["licence"]
    assert libre["usage_commercial"] == "autorise" and libre["service_tiers"] == "incertain"


def test_une_capacite_sans_licence_declaree_est_inconnue_donc_refusee():
    declaration = nexora.declarations_depuis_capacites(
        [{"id": "X_Y", "name": "XY", "kind": "video.t2v"}], "https://nexora.example/v1"
    )[0]
    assert declaration["identifiant"] == "video.nexora.x-y.api" and declaration["capacite"] == "video"
    assert declaration["licence"]["usage_commercial"] == "inconnu"
    f_ = Fournisseur.depuis_json(
        {**declaration, "statut_catalogue": "declare", "qualification": "a_mesurer", "licence_lue_par": None}
    )
    profil = politique.ProfilClient(True, 100_000, frozenset({"CA"}), False)
    assert {politique.LICENCE_INCONNUE, politique.LICENCE_A_VERIFIER, politique.EFVP_REQUISE} <= set(
        politique.evaluer(f_, profil).codes
    )


def test_le_registre_refuse_d_activer_les_capacites_nexora_non_conformes_et_lit_l_activation_de_la_bonne(base):
    with stockage.transaction() as cnx:
        registre.declarer_profil(
            cnx,
            acteur=ADMIN,
            usage_commercial=True,
            revenu_annuel_usd=2_000_000,
            territoires=["CA"],
            heberge_pour_tiers=False,
            revision_attendue=0,
        )
    resultats = {}
    for d in nexora.declarations_depuis_capacites(nexora.NexoraDouble().capacites(), "https://nexora.example/v1"):
        with stockage.transaction() as cnx:
            registre.configurer(cnx, acteur=ADMIN, identifiant=d["identifiant"], declaration=d)
            resultats[d["identifiant"]] = registre.activer(cnx, acteur=ADMIN, identifiant=d["identifiant"])
    # La bonne capacité ne s'active pas seule : licence à lire, EFVP, service à des tiers non applicable ici.
    libre = resultats["image.nexora.nexora-fond-1.api"]
    assert not libre.conforme and {politique.LICENCE_A_VERIFIER, politique.EFVP_REQUISE} <= set(libre.codes)
    assert politique.LICENCE_NON_COMMERCIALE in resultats["image.nexora.nexora-nc.api"].codes
    assert politique.SEUIL_REVENU_DEPASSE in resultats["image.nexora.nexora-seuil.api"].codes
    # Un administrateur lit la licence, consigne l'EFVP : l'activation devient possible, sous le même moteur.
    with stockage.transaction() as cnx:
        registre.configurer(
            cnx,
            acteur=ADMIN,
            identifiant="image.nexora.nexora-fond-1.api",
            modifications={"licence_lue": True, "efvp_ref": "EFVP-2026-07"},
            revision_attendue=1,
        )
        assert registre.activer(cnx, acteur=ADMIN, identifiant="image.nexora.nexora-fond-1.api").conforme


def test_aucun_module_reseau_n_est_importe_par_le_module():
    import ast
    import inspect

    arbre = ast.parse(inspect.getsource(nexora))
    importes = {n.module or "" for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names
    }
    assert not importes & {"socket", "urllib", "urllib.request", "http", "http.client", "requests", "httpx", "ssl"}


def test_la_nature_de_l_adaptateur_suit_celle_du_transport():
    class Reel(nexora.NexoraDouble):
        nature = generation.NATURE_REEL

    assert nexora.GenerateurNexora(Reel(), "nexora-fond-1").nature == "reel"
    assert nexora.GenerateurNexora(nexora.NexoraDouble(), "nexora-fond-1").nature == "double"
    assert f.FICTIF
