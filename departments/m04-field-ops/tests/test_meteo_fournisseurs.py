"""PLAN T4.13 : le fournisseur que le PROFIL météo ouvre. Fermé par défaut ; Open-Meteo seulement avec un forfait
commercial déclaré et la clé d'API dans l'environnement. Sans réseau (sockets bloqués, transport fictif). Fictif
(`fictif: true`)."""

from __future__ import annotations

import json

import pytest
from m4_field_ops import meteo, meteo_fournisseurs, meteo_geomet, meteo_open_meteo

from opsys import meteo as meteo_entreprise

FICTIF = True
CLE = "CLE-COMMERCIALE-FICTIVE-0123456789"
SERVICES = {"revetement": {"sans_objet": list(meteo_entreprise.RISQUES)}}


@pytest.fixture(autouse=True)
def _sans_reseau(sockets_bloques):
    """Ce module n'ouvre jamais un socket."""


def _profil(**extra):
    return meteo_entreprise.normaliser_meteo({"fuseau": "America/Toronto", "services": SERVICES, **extra})


def _open_meteo(cle_env="OPSYS_CLE_METEO_FICTIVE"):
    return _profil(fournisseur="open_meteo", open_meteo={"forfait": "commercial", "cle_env": cle_env})


def test_sans_profil_aucun_fournisseur_n_est_ouvert_et_ce_n_est_pas_une_erreur():
    assert meteo_fournisseurs.fournisseur_depuis_le_profil(None, {}) == (None, None)


def test_un_profil_sans_cle_fournisseur_reste_ferme_meme_avec_des_seuils():
    assert meteo_fournisseurs.fournisseur_depuis_le_profil(_profil(), {"OPSYS_CLE_METEO_FICTIVE": CLE}) == (None, None)


@pytest.mark.parametrize("profil", ["msc_geomet", 42, [], ""])
def test_un_profil_qui_n_est_pas_un_objet_ne_devient_jamais_un_fournisseur(profil):
    assert meteo_fournisseurs.fournisseur_depuis_le_profil(profil, {}) == (None, None)


def test_msc_geomet_est_ouvert_par_la_configuration_sans_aucune_connexion():
    fournisseur, verdict = meteo_fournisseurs.fournisseur_depuis_le_profil(_profil(fournisseur="msc_geomet"), {})
    assert verdict is None and isinstance(fournisseur, meteo_geomet.FournisseurMscGeomet)
    assert isinstance(fournisseur, meteo.FournisseurMeteo)


def test_open_meteo_est_ouvert_avec_le_forfait_commercial_et_la_cle_de_l_environnement():
    environ = {"OPSYS_CLE_METEO_FICTIVE": CLE, "AUTRE": "x"}
    fournisseur, verdict = meteo_fournisseurs.fournisseur_depuis_le_profil(_open_meteo(), environ)
    assert verdict is None and isinstance(fournisseur, meteo_open_meteo.FournisseurOpenMeteo)
    assert CLE not in json.dumps(fournisseur.descripteur())


@pytest.mark.parametrize("environ", [{}, {"OPSYS_CLE_METEO_FICTIVE": ""}, {"AUTRE": CLE}])
def test_open_meteo_reste_ferme_sans_la_cle_dans_l_environnement_et_le_dit(environ):
    fournisseur, verdict = meteo_fournisseurs.fournisseur_depuis_le_profil(_open_meteo(), environ)
    assert fournisseur is None and verdict["code"] == meteo.CODE_FOURNISSEUR_FERME
    assert "OPSYS_CLE_METEO_FICTIVE" in verdict["detail"] and "jamais dans le profil" in verdict["detail"]
    assert CLE not in json.dumps(verdict)


def test_un_profil_qui_contournerait_la_validation_avec_un_forfait_gratuit_reste_ferme():
    contourne = {
        "fournisseur": "open_meteo",
        "fuseau": "America/Toronto",
        "open_meteo": {"forfait": "gratuit", "cle_env": "OPSYS_CLE_METEO_FICTIVE"},
    }
    fournisseur, verdict = meteo_fournisseurs.fournisseur_depuis_le_profil(contourne, {"OPSYS_CLE_METEO_FICTIVE": CLE})
    assert fournisseur is None and verdict["code"] == meteo.CODE_FOURNISSEUR_FERME
    assert "usage NON commercial" in verdict["detail"]


def test_un_profil_qui_nomme_open_meteo_sans_reglage_reste_ferme():
    fournisseur, verdict = meteo_fournisseurs.fournisseur_depuis_le_profil(
        {"fournisseur": "open_meteo", "fuseau": "America/Toronto"}, {"OPSYS_CLE_METEO_FICTIVE": CLE}
    )
    assert fournisseur is None and verdict["code"] == meteo.CODE_FOURNISSEUR_FERME


def test_un_fournisseur_inconnu_reste_ferme():
    fournisseur, verdict = meteo_fournisseurs.fournisseur_depuis_le_profil(
        {"fournisseur": "meteomedia", "fuseau": "America/Toronto"}, {}
    )
    assert fournisseur is None and verdict["code"] == meteo.CODE_FOURNISSEUR_FERME
    assert "meteomedia" in verdict["detail"]


def test_un_fuseau_inconnu_du_systeme_ferme_le_fournisseur():
    fournisseur, verdict = meteo_fournisseurs.fournisseur_depuis_le_profil(
        {"fournisseur": "msc_geomet", "fuseau": "Nulle/Part"}, {}
    )
    assert fournisseur is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_le_transport_fictif_est_transmis_a_l_adaptateur():
    appels = []

    def transport(url, delai):
        appels.append(url)
        return b"{}", {}

    fournisseur, _ = meteo_fournisseurs.fournisseur_depuis_le_profil(_profil(fournisseur="msc_geomet"), {}, transport)
    fournisseur.previsions(
        {"latitude_microdegres": 45_800_000, "longitude_microdegres": -73_400_000}, "2026-10-05", "2026-10-05"
    )
    assert len(appels) == 1 and appels[0].startswith("https://api.weather.gc.ca/")


def test_le_module_ne_lit_pas_os_environ_lui_meme():
    import ast
    from pathlib import Path

    arbre = ast.parse(Path(meteo_fournisseurs.__file__).read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            assert all(a.name not in {"os", "socket", "urllib"} for a in noeud.names)
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"environ", "getenv"}
