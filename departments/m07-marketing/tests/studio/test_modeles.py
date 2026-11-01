"""Sélection du modèle par le registre de fournisseurs existant : politique de licence, aucun repli, instantané sans
revenu."""

from __future__ import annotations

import json

import pytest
from m7_marketing.studio import generation, modeles
from sqlalchemy import select

from opsys import stockage
from opsys.fournisseurs import catalogue, politique, registre
from opsys.stockage.schema import JOURNAL

ADMIN = "gestion"
DEPARTEMENT = "m07-marketing"
PROFIL = {"usage_commercial": True, "revenu_annuel_usd": 1_500_000, "territoires": ["CA"], "heberge_pour_tiers": False}


def _profil(**plus):
    with stockage.transaction() as cnx:
        courant = registre.profil_brut(cnx)
        return registre.declarer_profil(
            cnx, acteur=ADMIN, revision_attendue=courant["revision"] if courant else 0, **{**PROFIL, **plus}
        )


def _activer(identifiant, **modifications):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(
            select(registre.FOURNISSEURS_CONFIGURATIONS.c.revision).where(
                registre.FOURNISSEURS_CONFIGURATIONS.c.identifiant == identifiant
            )
        ).scalar_one_or_none()
        registre.configurer(
            cnx, acteur=ADMIN, identifiant=identifiant, modifications=modifications, revision_attendue=ligne or 0
        )
        return registre.activer(cnx, acteur=ADMIN, identifiant=identifiant)


def _declarer_et_activer(declaration):
    with stockage.transaction() as cnx:
        registre.configurer(cnx, acteur=ADMIN, identifiant=declaration["identifiant"], declaration=declaration)
        return registre.activer(cnx, acteur=ADMIN, identifiant=declaration["identifiant"])


def _selectionner(identifiant, capacite="image", departement=DEPARTEMENT):
    with stockage.transaction() as cnx:
        return registre.selectionner(
            cnx, acteur=ADMIN, capacite=capacite, identifiant=identifiant, departement=departement
        )


def _choisir(capacite="image"):
    with stockage.transaction() as cnx:
        return modeles.selectionner(cnx, capacite)


def test_sans_selection_aucun_modele_aucun_repli(base):
    _profil()
    with pytest.raises(modeles.ModeleRefuse) as erreur:
        _choisir()
    assert erreur.value.code == "REJ-STUDIO-MODELE-AUCUN_FOURNISSEUR"


def test_capacite_hors_studio_refusee(base):
    with pytest.raises(modeles.ModeleRefuse) as erreur:
        _choisir("llm")
    assert erreur.value.code == modeles.REJ_CAPACITE


def test_un_modele_catalogue_conforme_est_selectionne_et_son_instantane_ne_contient_pas_le_revenu(base):
    _profil()
    assert _activer("image.flux2-klein-4b.local").conforme
    _selectionner("image.flux2-klein-4b.local")
    selection = _choisir()
    import datetime as dt

    instantane = selection.instantane(dt.datetime(2026, 11, 1, 12, tzinfo=dt.UTC))
    assert instantane["fournisseur_id"] == "image.flux2-klein-4b.local" and instantane["decision"]["conforme"]
    assert instantane["licence"]["poids"] == "Apache-2.0"
    texte = json.dumps(instantane)
    assert "1500000" not in texte and "revenu" not in texte.replace("seuil_revenu_usd", "")
    assert len(instantane["profil_empreinte"]) == 64 and instantane["profil_revision"] == 1


def test_un_modele_non_commercial_ne_s_active_pas_et_ne_se_selectionne_pas(base):
    _profil()
    decision = _activer("image.flux1-dev")
    assert {politique.FOURNISSEUR_ECARTE, politique.LICENCE_NON_COMMERCIALE} <= set(decision.codes)
    with pytest.raises(registre.RegistreErreur) as erreur:
        _selectionner("image.flux1-dev")
    assert erreur.value.code == "FOURNISSEUR_INACTIF"
    with pytest.raises(modeles.ModeleRefuse):
        _choisir()


def test_seuil_de_revenu_une_licence_sous_seuil_se_refuse_au_franchissement_sans_repli(base):
    _profil(revenu_annuel_usd=2_000_000)
    assert _activer("image.flux2-klein-4b.local").conforme
    _selectionner("image.flux2-klein-4b.local", departement=None)  # défaut global
    declaration = {
        "identifiant": "image.seuil-test.local",
        "capacite": "image",
        "mode": "local",
        "modele": "modèle à seuil de test",
        "licence": {
            "code": None,
            "poids": "Licence communautaire 5 M$",
            "usage_commercial": "sous_seuil",
            "seuil_revenu_usd": 5_000_000,
            "service_tiers": "autorise",
            "integration": "bibliotheque",
            "verification": "verifiee",
            "source": "licence fictive de test",
        },
    }
    assert _declarer_et_activer(declaration).conforme
    _selectionner("image.seuil-test.local")
    assert _choisir().fournisseur.identifiant == "image.seuil-test.local"
    _profil(revenu_annuel_usd=6_000_000)  # le client franchit le seuil
    with pytest.raises(modeles.ModeleRefuse) as erreur:
        _choisir()
    assert erreur.value.code == "REJ-STUDIO-MODELE-REFUS_POLITIQUE"
    assert politique.SEUIL_REVENU_DEPASSE in erreur.value.refus
    # Aucun repli sur le défaut global (klein 4B, toujours conforme) : la décision du département reste un refus.


def test_revenu_inconnu_avec_licence_a_seuil_refuse(base):
    _profil(revenu_annuel_usd=None)
    declaration = {
        "identifiant": "image.seuil-test.local",
        "capacite": "image",
        "mode": "local",
        "modele": "m",
        "licence": {
            "code": None,
            "poids": "Seuil 1 M$",
            "usage_commercial": "sous_seuil",
            "seuil_revenu_usd": 1_000_000,
            "service_tiers": "autorise",
            "integration": "bibliotheque",
            "verification": "verifiee",
            "source": "licence fictive",
        },
    }
    decision = _declarer_et_activer(declaration)
    assert decision.codes == (politique.REVENU_CLIENT_INCONNU,)


def test_territoire_exclu_et_service_a_des_tiers(base):
    _profil(territoires=["CA", "UE"])
    assert politique.TERRITOIRE_EXCLU in _activer("video.hunyuanvideo-1.5").codes
    _profil(territoires=["CA"], heberge_pour_tiers=True)
    decision = _activer("image.flux3-image-klein.local")
    assert politique.SERVICE_TIERS_INCERTAIN in decision.codes and politique.LICENCE_A_VERIFIER in decision.codes


def test_verdict_courant_suit_le_profil_et_l_activation(base):
    _profil()
    assert _activer("image.flux2-klein-4b.local").conforme
    with stockage.transaction() as cnx:
        assert modeles.verdict_courant(cnx, "image.flux2-klein-4b.local")["conforme"] is True
    _profil(
        usage_commercial=True, territoires=["CA"], heberge_pour_tiers=True
    )  # klein 4B : service à des tiers autorisé
    with stockage.transaction() as cnx:
        assert modeles.verdict_courant(cnx, "image.flux2-klein-4b.local")["conforme"] is True
        registre.desactiver(cnx, acteur=ADMIN, identifiant="image.flux2-klein-4b.local")
        verdict = modeles.verdict_courant(cnx, "image.flux2-klein-4b.local")
    assert verdict["conforme"] is False and "FOURNISSEUR_INACTIF" in verdict["codes"]
    with stockage.transaction() as cnx:
        assert modeles.verdict_courant(cnx, "image.inconnu.local")["conforme"] is False


def test_declaration_du_double_est_conforme_et_sa_nature_reste_celle_d_un_double(base):
    _profil()
    assert _declarer_et_activer(modeles.declaration_pour_double()).conforme
    _selectionner("image.double-deterministe.test")
    assert _choisir().fournisseur.identifiant == "image.double-deterministe.test"
    assert generation.GenerateurImageDouble.nature == "double"


# -- la matrice des licences par défaut ----------------------------------------------------------------------------
def test_la_matrice_couvre_tous_les_modeles_image_et_video_du_catalogue():
    matrice = modeles.matrice_licences_defaut()
    ids = {ligne["id"] for ligne in matrice}
    attendus = {f.identifiant for f in catalogue.CATALOGUE if f.capacite in ("image", "video")}
    assert ids == attendus and len(matrice) == len(attendus)
    par_id = {ligne["id"]: ligne for ligne in matrice}
    assert (
        par_id["image.flux1-dev"]["usage_commercial"] == "interdit" and par_id["image.flux1-dev"]["statut"] == "ecarte"
    )
    assert par_id["image.flux3-image-klein.local"]["seuil_revenu_usd"] == 5_000_000
    assert par_id["video.minimax-h3"]["territoires_exclus"] == ["UE", "UK", "KR", "US"]
    assert par_id["video.hunyuanvideo-1.5"]["territoires_exclus"] == ["UE", "UK", "KR"]
    assert par_id["image.flux2-klein-4b.local"]["usage_commercial"] == "autorise"


def test_verdicts_de_la_matrice_pour_un_client_de_6_m_dans_l_ue():
    profil = politique.ProfilClient(True, 6_000_000, frozenset({"UE"}), False)
    verdicts = modeles.verdicts_de_la_matrice(profil)
    assert verdicts["image.flux2-klein-4b.local"] == ()
    assert politique.SEUIL_REVENU_DEPASSE in verdicts["image.flux3-image-klein.local"]
    assert politique.TERRITOIRE_EXCLU in verdicts["video.hunyuanvideo-1.5"]
    assert politique.TERRITOIRE_EXCLU in verdicts["video.minimax-h3"]
    assert politique.LICENCE_NON_COMMERCIALE in verdicts["image.flux1-dev"]


def test_une_refusee_d_activation_est_journalisee(base):
    _profil()
    _activer("image.qwen-image-2.1")
    with stockage.transaction() as cnx:
        refus = cnx.execute(
            select(JOURNAL.c.details).where(JOURNAL.c.action == "fournisseurs.activation.refusee")
        ).scalars()
        assert any("LICENCE_NON_COMMERCIALE" in r for r in refus)
