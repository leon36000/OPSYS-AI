"""La clé de mesure d'un contenu et le fait « contenu exporté » (PLAN T4.17-e) : module pur, sans base ni bus.

Ce que ce fichier prouve : la clé `utm_content` est déterministe, tirée du seul identifiant du contenu, conforme au
contrat UTM gelé, sans renseignement personnel ; un contenu sans identifiant stable, ou dont la clé écrite n'est pas
celle que son identifiant donne, est refusé ; la charge du fait ne porte que ce que le catalogue en dit. La base, le
bus et les outils sont dans `test_service_usine.py`, le trajet complet dans `tests/test_boucle_de_mesure_par_contenu.py`
(socle).
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from m7_marketing.usine import chantier, mesure, plateformes, verdicts
from m7_marketing.utm import utm_engine

from opsys import evenements

FICTIF = True
CONTENU_ID = "00000000-0000-5000-8000-000000000001"
# Valeur de référence, recalculée à part (sha256 du texte de l'identifiant, 16 premiers chiffres hexadécimaux) : la
# changer sépare les exports d'avant de ceux d'après, donc les leads déjà comptés de ceux qui ne le seraient plus.
CLE_DE_REFERENCE = "facebook-b2066f4f4e2aa307"
SRC_MESURE = Path(mesure.__file__)


def _proposition(charge, profil, nature, plateforme="facebook"):
    preparation = chantier.preparer(charge, profil, nature, None, [], [], "test")
    return next(p for p in preparation.nouvelles if p["plateforme"] == plateforme)


# -- la clé : déterministe, tirée du seul identifiant ------------------------------------------------------------
def test_la_cle_est_celle_de_reference_et_ne_depend_que_de_l_identifiant_et_de_la_plateforme():
    assert mesure.utm_content_de(CONTENU_ID, "facebook") == CLE_DE_REFERENCE
    assert [mesure.utm_content_de(CONTENU_ID, "facebook") for _ in range(3)] == [CLE_DE_REFERENCE] * 3


def test_la_cle_ne_depend_ni_du_processus_ni_de_l_aleatoire_de_hachage_de_python():
    code = (
        "from m7_marketing.usine import mesure;"
        f"print(mesure.utm_content_de({CONTENU_ID!r}, 'facebook'))"
    )
    for graine in ("0", "1", "12345"):
        sortie = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": graine},
        ).stdout.strip()
        assert sortie == CLE_DE_REFERENCE, graine


def test_deux_contenus_ou_deux_plateformes_ne_partagent_jamais_leur_cle():
    autre = "00000000-0000-5000-8000-000000000002"
    assert mesure.utm_content_de(autre, "facebook") != CLE_DE_REFERENCE
    cles = {mesure.utm_content_de(CONTENU_ID, code) for code in plateformes.CODES_PLATEFORMES}
    assert len(cles) == len(plateformes.CODES_PLATEFORMES)


def test_dix_mille_identifiants_donnent_dix_mille_cles():
    cles = {mesure.utm_content_de(f"contenu-{n}", "instagram") for n in range(10_000)}
    assert len(cles) == 10_000


@pytest.mark.parametrize("code", plateformes.CODES_PLATEFORMES)
def test_la_cle_respecte_le_contrat_utm_gele_pour_chaque_plateforme(code):
    cle = mesure.utm_content_de(CONTENU_ID, code)
    assert re.fullmatch(r"[a-z0-9_-]+", cle) and len(cle) <= 80 and cle.startswith(f"{code}-")
    lien = utm_engine.generer_lien_utm(
        "https://exemple-fictif.ca/", "site", "referral", "contenu-gouttieres-2026", cle,
    )
    assert [v for _, v, _ in utm_engine.valider_lien_utm(lien) if v == "fail"] == []
    assert parse_qs(urlsplit(lien).query)["utm_content"] == [cle]


def test_la_cle_ne_porte_aucun_renseignement_personnel_ni_l_identifiant_du_chantier():
    contenu_id = "chantier-Tremblay-12-rue-des-Lilas-Repentigny"
    cle = mesure.utm_content_de(contenu_id, "instagram")
    for morceau in ("Tremblay", "tremblay", "Lilas", "lilas", "Repentigny", "repentigny", "rue", "chantier"):
        assert morceau not in cle


# -- sans identifiant stable : refus, jamais une clé inventée ---------------------------------------------------
@pytest.mark.parametrize("contenu_id", [None, "", "   ", "\n", 12, 3.5, b"abc", ["a"], {"a": 1}, True])
def test_un_contenu_sans_identifiant_stable_n_a_pas_de_cle(contenu_id):
    with pytest.raises(ValueError, match="contenu_id"):
        mesure.utm_content_de(contenu_id, "facebook")


@pytest.mark.parametrize("plateforme", [None, "", "linkedin", "Facebook", 3, "facebook "])
def test_une_plateforme_inconnue_n_a_pas_de_cle(plateforme):
    with pytest.raises(ValueError, match="plateforme"):
        mesure.utm_content_de(CONTENU_ID, plateforme)


def test_le_module_n_a_aucune_source_d_aleatoire_ni_d_horloge():
    """Garde statique : la clé ne peut pas être « tirée au sort » sans que ce test le voie."""
    arbre = ast.parse(SRC_MESURE.read_text(encoding="utf-8"))
    importes = {a.name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names}
    importes |= {n.module.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module}
    assert not importes & {"random", "uuid", "secrets", "time", "datetime", "os", "opsys"}, importes
    noms = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(arbre) if isinstance(n, ast.Attribute)
    }
    assert not noms & {"uuid4", "uuid1", "random", "randint", "token_hex", "now", "utcnow", "time", "urandom"}, noms


# -- la clé d'un contenu proposé : recalculée, jamais crue sur parole -----------------------------------------
def test_une_proposition_conforme_donne_sa_cle(charge, profil, nature):
    proposition = _proposition(charge, profil, nature)
    assert mesure.identifiant_de_mesure(proposition) == (
        mesure.utm_content_de(proposition["contenu_id"], "facebook"), None,
    )


def test_une_proposition_sans_lien_a_quand_meme_sa_cle(charge, profil, nature):
    del profil["site_url"]
    proposition = _proposition(charge, profil, nature)
    assert proposition["lien_utm"] is None
    cle, verdict = mesure.identifiant_de_mesure(proposition)
    assert verdict is None and cle == proposition["utm_content"]


def test_le_message_prive_a_sa_cle_mais_aucun_lien(charge, profil, nature):
    proposition = _proposition(charge, profil, nature, "demande_temoignage")
    cle, verdict = mesure.identifiant_de_mesure(proposition)
    assert verdict is None and cle.startswith("demande_temoignage-")
    assert proposition["lien_utm"] is None and proposition["utm"] is None


@pytest.mark.parametrize("retire", ["contenu_id", "plateforme"])
def test_une_proposition_sans_identifiant_ou_sans_plateforme_est_refusee_nommement(charge, profil, nature, retire):
    proposition = _proposition(charge, profil, nature)
    del proposition[retire]
    cle, verdict = mesure.identifiant_de_mesure(proposition)
    assert cle is None and verdict["code"] == verdicts.REJ_CONTENU_SANS_IDENTIFIANT
    assert retire in verdict["detail"]


@pytest.mark.parametrize("contenu_id", ["", None, "  "])
def test_un_identifiant_vide_est_refuse_meme_si_une_cle_est_deja_ecrite(charge, profil, nature, contenu_id):
    proposition = {**_proposition(charge, profil, nature), "contenu_id": contenu_id}
    cle, verdict = mesure.identifiant_de_mesure(proposition)
    assert cle is None and verdict["code"] == "REJ-CONTENU-SANS-IDENTIFIANT-DE-MESURE"


def test_une_cle_ecrite_qui_n_est_pas_celle_de_l_identifiant_est_refusee(charge, profil, nature):
    proposition = _proposition(charge, profil, nature)
    cle, verdict = mesure.identifiant_de_mesure({**proposition, "utm_content": "facebook-d-avant-la-convention"})
    assert cle is None and verdict["code"] == verdicts.REJ_UTM_CONTENT_INCOHERENT
    assert "utm_content du contenu" in verdict["detail"] and proposition["utm_content"] in verdict["detail"]


def test_un_utm_ou_un_lien_d_avant_la_convention_est_refuse_avec_le_chemin_pour_le_refaire(charge, profil, nature):
    proposition = _proposition(charge, profil, nature)
    ancienne = "facebook-3f2a9c1d"  # l'ancienne clé : 8 chiffres de l'empreinte du chantier
    utm_ancien = {**proposition["utm"], "content": ancienne}
    lien_ancien = proposition["lien_utm"].replace(proposition["utm_content"], ancienne)
    for altere, source in (({"utm": utm_ancien}, "utm.content"), ({"lien_utm": lien_ancien}, "dans le lien")):
        cle, verdict = mesure.identifiant_de_mesure({**proposition, **altere})
        assert cle is None and verdict["code"] == verdicts.REJ_UTM_CONTENT_INCOHERENT, source
        assert source in verdict["detail"] and "nouveau texte" in verdict["detail"]


def test_un_lien_qui_ne_porte_pas_utm_content_est_refuse_aucun_lead_ne_serait_compte(charge, profil, nature):
    proposition = _proposition(charge, profil, nature)
    sans = proposition["lien_utm"].split("&utm_content=")[0]
    cle, verdict = mesure.identifiant_de_mesure({**proposition, "lien_utm": sans})
    assert cle is None and verdict["code"] == verdicts.REJ_UTM_CONTENT_INCOHERENT
    assert "ne porte pas utm_content" in verdict["detail"]


def test_utm_content_du_lien_lit_le_parametre_et_rien_d_autre():
    lien = "https://exemple-fictif.ca/?utm_source=site&utm_content=facebook-abc"
    assert mesure.utm_content_du_lien(lien) == "facebook-abc"
    for pas_de_cle in (None, "", "https://exemple-fictif.ca/?utm_source=site", "https://exemple-fictif.ca/", 12):
        assert mesure.utm_content_du_lien(pas_de_cle) is None


# -- le fait « contenu exporté » -----------------------------------------------------------------------------------
def test_la_charge_ne_porte_que_la_cle_le_chantier_le_canal_et_la_trace_de_l_export(charge, profil, nature):
    proposition = _proposition(charge, profil, nature)
    cle = proposition["utm_content"]
    fait = mesure.charge_contenu_exporte(proposition, cle, "2026-09-29T20:00:00-04:00")
    assert fait == {
        "contenu_id": proposition["contenu_id"], "wct_id": "wct-usine-1", "canal": "facebook", "utm_content": cle,
        "lien_de_suivi": True, "exporte_le": "2026-09-29T20:00:00-04:00",
    }


def test_la_charge_n_emporte_aucun_renseignement_personnel_meme_quand_la_proposition_en_porte(charge, profil, nature):
    proposition = _proposition(charge, profil, nature)
    assert proposition["lead_id"] == "lead-usine-1" and proposition["ville"] == "Repentigny" and proposition["texte"]
    fait = mesure.charge_contenu_exporte(proposition, proposition["utm_content"], "2026-09-29T20:00:00-04:00")
    assert set(fait) == {"contenu_id", "wct_id", "canal", "utm_content", "lien_de_suivi", "exporte_le"}
    lu = str(fait)
    for interdit in ("lead-usine-1", "Repentigny", "intervention", "etienne", "Toitures", proposition["texte"][:20]):
        assert interdit not in lu, interdit


@pytest.mark.parametrize("code", plateformes.CODES_PLATEFORMES)
def test_le_catalogue_accepte_la_charge_de_chaque_plateforme_de_m7(code, charge, profil, nature):
    """Le couplage catalogue - M7 : une sixième plateforme sans son entrée au catalogue casserait l'export ici."""
    proposition = _proposition(charge, profil, nature, code)
    fait = mesure.charge_contenu_exporte(proposition, proposition["utm_content"], "2026-09-29T20:00:00-04:00")
    assert evenements.schemas.erreurs_charge(mesure.TYPE_EVENEMENT, fait) == []
    assert fait["lien_de_suivi"] is (code != "demande_temoignage")


def test_le_catalogue_refuse_ce_qui_n_est_pas_la_charge_exacte(charge, profil, nature):
    proposition = _proposition(charge, profil, nature)
    fait = mesure.charge_contenu_exporte(proposition, proposition["utm_content"], "2026-09-29T20:00:00-04:00")
    for surplus in ({"lead_id": "lead-usine-1"}, {"ville": "Repentigny"}, {"texte": "x"}, {"contact": "x"}):
        assert evenements.schemas.erreurs_charge(mesure.TYPE_EVENEMENT, {**fait, **surplus})
    for retire in fait:
        assert evenements.schemas.erreurs_charge(mesure.TYPE_EVENEMENT, {k: v for k, v in fait.items() if k != retire})
    assert evenements.schemas.erreurs_charge(mesure.TYPE_EVENEMENT, {**fait, "utm_content": "Facebook Chez Mme"})
    assert evenements.schemas.erreurs_charge(mesure.TYPE_EVENEMENT, {**fait, "canal": "linkedin"})
    assert evenements.schemas.erreurs_charge(mesure.TYPE_EVENEMENT, {**fait, "lien_de_suivi": "oui"})


def test_sans_lien_le_fait_le_dit(charge, profil, nature):
    del profil["site_url"]
    proposition = _proposition(charge, profil, nature)
    fait = mesure.charge_contenu_exporte(proposition, proposition["utm_content"], "2026-09-29T20:00:00-04:00")
    assert fait["lien_de_suivi"] is False and fait["utm_content"].startswith("facebook-")


def test_l_identifiant_du_fait_est_celui_du_contenu_donc_un_export_rejoue_ne_double_rien():
    assert mesure.evenement_id(CONTENU_ID) == f"m7-contenu-exporte-{CONTENU_ID}"
    assert mesure.evenement_id(CONTENU_ID) == mesure.evenement_id(CONTENU_ID)
    assert mesure.evenement_id("autre") != mesure.evenement_id(CONTENU_ID)
