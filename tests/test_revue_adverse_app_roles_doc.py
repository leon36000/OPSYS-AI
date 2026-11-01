"""Revue adverse (app-03) : `docs/architecture/ROLES.md` dit, outil par outil, qui peut appeler quoi depuis un appareil.

`tests/test_portees_appareil.py` épingle le CODE (les ensembles `employee`, `seller`, `admin`) et les compteurs de
ROLES.md, mais rien ne vérifie que chaque outil projeté sur un rôle y est NOMMÉ : un outil peut être ouvert à `admin`
sans que la doc de portée le dise, et le lecteur d'une revue ne voit alors jamais ce qui a été ouvert. Ce test ferme cet
écart.

`NON_DOCUMENTES` liste les écarts CONSTATÉS à la revue (six lectures M9 N0/T0, `admin`) en attendant que ROLES.md
(propriété du coordonnateur) les nomme : dès qu'un de ces noms apparaît dans ROLES.md, le test exige qu'on le retire de
la liste.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from opsys.departements import charger_departements, tous_les_outils

FICTIF = True
ROLES_MD = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "ROLES.md"

NON_DOCUMENTES: frozenset[str] = frozenset()  # écart app-03 fermé : ROLES.md nomme les six lectures M9


@pytest.fixture(scope="module")
def index():
    return tous_les_outils(charger_departements().values())


@pytest.fixture(scope="module")
def noms_documentes():
    texte = ROLES_MD.read_text(encoding="utf-8")
    return set(re.findall(r"`(m\d+_[a-z0-9_]+)`", texte))


def _absents(ouverts, documentes, connus=NON_DOCUMENTES):
    return ouverts - documentes - connus


def test_chaque_outil_ouvert_a_un_appareil_est_nomme_dans_roles_md(index, noms_documentes):
    ouverts = {nom for nom, (_dep, outil) in index.items() if outil.roles_appareil and not outil.frontiere_humaine}
    assert len(ouverts) > 200  # le test ne passe pas à vide
    absents = _absents(ouverts, noms_documentes)
    assert not absents, f"outils ouverts à un appareil mais absents de ROLES.md : {sorted(absents)}"


def test_le_controle_detecte_un_outil_ouvert_mais_non_documente():
    assert _absents({"m4_pointer", "m9_nouvel_outil"}, {"m4_pointer"}, frozenset()) == {"m9_nouvel_outil"}
    assert _absents({"m4_pointer", "m9_toléré"}, {"m4_pointer"}, frozenset({"m9_toléré"})) == set()  # écart connu
    assert _absents({"m9_cadrer_decision"}, {"m4_pointer"}) == {"m9_cadrer_decision"}  # plus toléré depuis app-03
    assert _absents({"m9_autre"}, {"m4_pointer"}) == {"m9_autre"}


def test_la_liste_des_ecarts_connus_se_vide_quand_la_doc_les_nomme(noms_documentes):
    maintenant_documentes = NON_DOCUMENTES & noms_documentes
    assert not maintenant_documentes, f"retirer de NON_DOCUMENTES : {sorted(maintenant_documentes)}"


def test_les_ecarts_connus_existent_encore_et_restent_des_lectures_sans_effet(index):
    for nom in NON_DOCUMENTES:
        assert nom in index, f"{nom} n'existe plus : le retirer de NON_DOCUMENTES"
        outil = index[nom][1]
        assert outil.niveau_effectif.value == "N0" and outil.autonomie.value == "T0", (nom, outil.niveau_effectif)
        assert outil.roles_appareil == frozenset({"admin"}), (nom, outil.roles_appareil)


def test_aucun_outil_nomme_dans_roles_md_n_a_disparu(index, noms_documentes):
    """Un nom cité par ROLES.md qui n'existe plus est un droit documenté qui n'est plus celui du code."""
    fantomes = {n for n in noms_documentes if n not in index}
    assert not fantomes, f"noms de ROLES.md absents du code : {sorted(fantomes)}"
