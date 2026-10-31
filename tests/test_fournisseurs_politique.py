"""Moteur de politique de licence et catalogue initial (données fictives : aucun client réel)."""

from __future__ import annotations

import dataclasses

import pytest

from opsys.fournisseurs import catalogue, politique
from opsys.fournisseurs.modele import CAPACITES, Cout, DeclarationInvalide, Fournisseur, Licence
from opsys.fournisseurs.politique import ProfilClient, evaluer

FICTIF = True
PME_QC = ProfilClient(usage_commercial=True, revenu_annuel_usd=1_500_000, territoires=frozenset({"CA"}),
                      heberge_pour_tiers=False)


def _licence(**valeurs) -> Licence:
    base = {"code": "Apache-2.0", "poids": "Apache-2.0", "usage_commercial": "autorise", "service_tiers": "autorise",
            "source": "fixture fictive"}
    return Licence(**{**base, **valeurs})


def _fournisseur(**valeurs) -> Fournisseur:
    base = {"identifiant": "image.fictif.local", "capacite": "image", "mode": "local", "modele": "modèle fictif",
            "licence": _licence()}
    return Fournisseur(**{**base, **valeurs})


def test_activation_conforme_acceptee():
    decision = evaluer(_fournisseur(), PME_QC)
    assert decision.conforme and decision.codes == ()


@pytest.mark.parametrize(("valeurs", "profil", "code"), [
    ({"licence": _licence(usage_commercial="interdit", poids="CC-BY-NC-4.0")}, PME_QC,
     politique.LICENCE_NON_COMMERCIALE),
    ({"licence": _licence(usage_commercial="sous_seuil", seuil_revenu_usd=1_000_000)}, PME_QC,
     politique.SEUIL_REVENU_DEPASSE),
    ({"licence": _licence(usage_commercial="sous_seuil", seuil_revenu_usd=5_000_000)},
     dataclasses.replace(PME_QC, revenu_annuel_usd=None), politique.REVENU_CLIENT_INCONNU),
    ({"licence": _licence(territoires_exclus=("UE", "UK", "KR"))},
     dataclasses.replace(PME_QC, territoires=frozenset({"CA", "UE"})), politique.TERRITOIRE_EXCLU),
    ({"licence": _licence(territoires_exclus=("UE",))},
     dataclasses.replace(PME_QC, territoires=frozenset()), politique.TERRITOIRE_CLIENT_INCONNU),
    ({"licence": _licence(service_tiers="interdit")}, dataclasses.replace(PME_QC, heberge_pour_tiers=True),
     politique.SERVICE_TIERS_INTERDIT),
    ({"licence": _licence(service_tiers="incertain")}, dataclasses.replace(PME_QC, heberge_pour_tiers=True),
     politique.SERVICE_TIERS_INCERTAIN),
    ({"licence": _licence(code="AGPL-3.0", poids=None)}, PME_QC, politique.COPYLEFT_INTEGRE),
    ({"licence": _licence(usage_commercial="inconnu")}, PME_QC, politique.LICENCE_INCONNUE),
    ({"licence": _licence(verification="a_lire")}, PME_QC, politique.LICENCE_A_VERIFIER),
    ({"licence": _licence(usage_commercial="sur_contrat")}, PME_QC, politique.CONTRAT_REQUIS),
    ({"licence": _licence(mention_obligatoire="Mention fictive")}, PME_QC, politique.MENTION_NON_CONFIRMEE),
    ({"mode": "api", "point_acces": "https://api.fictive.example/v1", "residence_donnees": "US"}, PME_QC,
     politique.EFVP_REQUISE),
    ({}, None, politique.PROFIL_CLIENT_ABSENT),
    ({"statut_catalogue": "ecarte", "raison_ecart": "raison fictive"}, PME_QC, politique.FOURNISSEUR_ECARTE),
])
def test_chaque_refus_porte_son_code(valeurs, profil, code):
    decision = evaluer(_fournisseur(**valeurs), profil)
    assert not decision.conforme
    assert code in decision.codes
    assert all(r.motif for r in decision.refus)
    assert set(decision.codes) <= set(politique.CODES_REFUS)


def test_conditions_levees_rendent_conforme():
    """Chaque refus « administratif » se lève par une donnée explicite, jamais par défaut."""
    f = _fournisseur(mode="api", point_acces="https://api.fictive.example/v1", residence_donnees="US",
                     licence=_licence(usage_commercial="sur_contrat", mention_obligatoire="Mention fictive",
                                      verification="a_lire"))
    assert set(evaluer(f, PME_QC).codes) == {politique.CONTRAT_REQUIS, politique.MENTION_NON_CONFIRMEE,
                                             politique.LICENCE_A_VERIFIER, politique.EFVP_REQUISE}
    leve = dataclasses.replace(f, contrat_ref="contrat-fictif-1", mention_confirmee=True,
                               licence_lue_par="admin_fictif le 2026-10-31", efvp_ref="efvp-fictive-1")
    assert evaluer(leve, PME_QC).conforme


def test_seuil_en_dessous_accepte_et_usage_non_commercial():
    f = _fournisseur(licence=_licence(usage_commercial="sous_seuil", seuil_revenu_usd=5_000_000))
    assert evaluer(f, PME_QC).conforme
    nc = _fournisseur(licence=_licence(usage_commercial="interdit"))
    assert evaluer(nc, dataclasses.replace(PME_QC, usage_commercial=False)).conforme


def test_refus_cumules_dans_un_ordre_stable():
    f = _fournisseur(licence=_licence(usage_commercial="interdit", territoires_exclus=("UE",),
                                      service_tiers="interdit"))
    profil = ProfilClient(True, 10, frozenset({"UE"}), True)
    assert evaluer(f, profil).codes == (politique.LICENCE_NON_COMMERCIALE, politique.TERRITOIRE_EXCLU,
                                        politique.SERVICE_TIERS_INTERDIT)


@pytest.mark.parametrize("champs", [
    {"reference_secret": "sk-valeur-fictive-en-clair"},
    {"reference_secret": "coffre:"},
    {"point_acces": "http://exemple.fictif/v1"},
    {"point_acces": "https://u:p@api.fictive.example/v1", "mode": "api"},
    {"mode": "api", "point_acces": "http://127.0.0.1:8000/v1"},
    {"capacite": "musique"},
])
def test_declaration_invalide_refusee(champs):
    with pytest.raises(DeclarationInvalide):
        _fournisseur(**champs)


def test_cout_decimal_jamais_flottant():
    with pytest.raises(DeclarationInvalide):
        Cout("page", 0.002, "USD", "fictif")  # type: ignore[arg-type]
    assert Cout("page", "0.002", "USD", "fictif").montant == "0.002"


def test_catalogue_couvre_les_capacites_et_cite_ses_sources():
    index = catalogue.par_identifiant()
    assert len(index) == len(catalogue.CATALOGUE)
    capacites = {f.capacite for f in catalogue.CATALOGUE}
    assert capacites == set(CAPACITES)
    for f in catalogue.CATALOGUE:
        assert f.qualification == "a_mesurer", f.identifiant  # aucune mesure locale n'existe encore
        assert f.licence.source.startswith("recherche/R"), f.identifiant
        assert f.reference_secret is None  # aucun secret dans le catalogue
        assert Fournisseur.depuis_json(f.vers_json()) == f
    adoptes = {f.capacite for f in catalogue.CATALOGUE if f.statut_catalogue == "adopte"}
    assert adoptes == set(CAPACITES)


def test_catalogue_ecartes_toujours_refuses_avec_raison():
    profils = [PME_QC, ProfilClient(False, 0, frozenset({"CA"}), False)]
    ecartes = [f for f in catalogue.CATALOGUE if f.statut_catalogue == "ecarte"]
    assert len(ecartes) >= 20
    for f in ecartes:
        assert f.raison_ecart
        for profil in profils:
            decision = evaluer(f, profil)
            assert politique.FOURNISSEUR_ECARTE in decision.codes
            assert f.raison_ecart in decision.refus[0].motif


def test_criteres_e0_de_la_recherche_r5():
    """R5 E0 : FLUX.1-dev/Qwen-Image 2.1/Fibo-dev refusés pour un usage commercial ; un client à 6 M$ ne peut pas
    utiliser FLUX 3 Klein ; un client de l'UE ne peut pas utiliser Hunyuan."""
    index = catalogue.par_identifiant()
    for ident in ("image.flux1-dev", "image.qwen-image-2.1", "image.bria-fibo-2.0-dev"):
        assert politique.LICENCE_NON_COMMERCIALE in evaluer(index[ident], PME_QC).codes
    klein = dataclasses.replace(index["image.flux3-image-klein.local"], licence_lue_par="admin_fictif")
    assert evaluer(klein, PME_QC).conforme
    assert evaluer(klein, dataclasses.replace(PME_QC, revenu_annuel_usd=6_000_000)).codes == (
        politique.SEUIL_REVENU_DEPASSE,)
    saas = dataclasses.replace(PME_QC, heberge_pour_tiers=True)
    assert politique.SERVICE_TIERS_INCERTAIN in evaluer(klein, saas).codes
    hunyuan = index["video.hunyuanvideo-1.5"]
    europe = dataclasses.replace(PME_QC, territoires=frozenset({"UE"}))
    assert politique.TERRITOIRE_EXCLU in evaluer(hunyuan, europe).codes


def test_adoptes_permissifs_conformes_pour_une_pme_sans_condition():
    index = catalogue.par_identifiant()
    for ident in ("llm.mistral-small-4.local", "embeddings.bge-m3.local", "reranker.bge-reranker-v2-m3.local",
                  "ocr.tesseract-5.5.local", "stt.voxtral-mini-realtime.local", "tts.chatterbox-multilingual.local",
                  "avatar.talkinghead", "image.flux2-klein-4b.local", "video.wan-2.2.local"):
        assert evaluer(index[ident], PME_QC).conforme, ident
    # Licences à lire en entier (R3 q.11, R6 l.431) : refus tant que la lecture n'est pas consignée.
    assert evaluer(index["ocr.docling.local"], PME_QC).codes == (politique.LICENCE_A_VERIFIER,)
    assert evaluer(index["llm.nemotron-3.5-lightning.local"], PME_QC).codes == (politique.LICENCE_A_VERIFIER,)
