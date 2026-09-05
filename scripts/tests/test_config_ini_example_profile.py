"""#585 : [forge].profile et [proof].profile désignent le MÊME concept (même énumération,
même commentaire de domaine, config.ini.example:10) ; deux valeurs opposées rendent le
fichier exemple contradictoire, et la section qui gouverne la rigueur portait la valeur
affaiblie. Ce test fige : même valeur, et valeur PROOF-Team (motif : ligne 11)."""
from __future__ import annotations

import configparser
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def _cfg() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
    cfg.read(RACINE / "config.ini.example", encoding="utf-8")
    return cfg


def test_les_deux_sections_declarent_le_meme_profil_proof() -> None:
    cfg = _cfg()
    assert cfg["forge"]["profile"] == cfg["proof"]["profile"]


def test_le_profil_est_proof_team_comme_le_motif_de_la_ligne_11_l_exige() -> None:
    assert _cfg()["proof"]["profile"] == "PROOF-Team"
