"""DÉCISIONS-ARCHITECTE r1 §2 « Matériaux » : les membres DÉCLARÉS de l'équipe d'un WCT d'équipe déclarent les
matériaux depuis leur téléphone, avec un audit nominatif ; un non-membre reste refusé ; l'admin garde le droit.

Vrais outils, base SQLite migrée, vraies personnes, profil des équipes déclaré par la fonction réelle du socle.
Chaque refus prouve que rien n'a été écrit. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from opsys import contexte, equipes, identite, stockage
from opsys.stockage.schema import JOURNAL

FICTIF = True
_spec = importlib.util.spec_from_file_location('acces_declaration_base',
                                               Path(__file__).with_name('test_acces_declaration.py'))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
base_durable, personnes, m6 = base.base_durable, base.personnes, base.m6

EQUIPE, AUTRE_EQUIPE = 'eq-toiture-fictive', 'eq-gouttiere-fictive'
INT_EQUIPE = 'int-equipe-fictive'
MARC, LEA, ADMIN = base.MARC, base.LEA, base.ADMIN  # marc membre de EQUIPE, léa membre de AUTRE_EQUIPE
AUDIT = 'm6.materiaux_declares_membre_equipe'


def _equipe(ident, membres):
    return {'id': ident, 'membres': membres, 'competences': ['gouttieres'],
            'depot': {'id': 'depot-fictif', 'latitude_microdegres': 45735000, 'longitude_microdegres': -73455000},
            'quarts': [{'jour': 0, 'debut_min': 480, 'fin_min': 1020}]}


@pytest.fixture
def profil(personnes, tmp_path, monkeypatch):
    monkeypatch.setenv('OPSYS_HOME', str(tmp_path / 'opsys'))
    equipes.enregistrer_equipes({'liste': [_equipe(EQUIPE, ['marc.fictif']), _equipe(AUTRE_EQUIPE, ['lea.fictif'])]})


@pytest.fixture
def wct_equipe(profil, m6):
    """Le WCT d'une ÉQUIPE (M4 V3 : `technicien_id` = l'équipe), le prévu de son devis et le coût unitaire connu."""
    base._publier_wct('wct-equipe', INT_EQUIPE, EQUIPE)
    base._receptionner(m6, INT_EQUIPE)
    base._prevu(m6, INT_EQUIPE)
    return base._formulaire('wct-equipe', INT_EQUIPE, INT_EQUIPE)


def _audits():
    with stockage.transaction() as cnx:
        return [(r.par, r.cible, json.loads(r.details)) for r in cnx.execute(
            select(JOURNAL.c.par, JOURNAL.c.cible, JOURNAL.c.details).where(JOURNAL.c.action == AUDIT))]


def test_membre_declare_pour_le_wct_de_son_equipe_avec_audit_nominatif(m6, wct_equipe):
    reponse = base._declarer(m6, 'wct-equipe', wct_equipe, MARC)

    base._accepte(reponse)
    assert base._consommations('wct-equipe') == [('CONSOMMATION', INT_EQUIPE, -10.0)]
    assert _audits() == [('marc.fictif', 'wct-equipe', {
        'equipe_id': EQUIPE, 'intervention_id': INT_EQUIPE, 'role': 'membre_equipe', 'lignes': 1})]


def test_non_membre_refuse_sans_ecriture(m6, wct_equipe):
    avant = base._etat()

    assert base._code_refus(base._declarer(m6, 'wct-equipe', wct_equipe, LEA)) == base.CODE_NON_ASSIGNEE

    assert base._etat() == avant and _audits() == []


def test_membre_retire_du_profil_refuse(m6, wct_equipe):
    equipes.enregistrer_equipes({'liste': [_equipe(EQUIPE, ['lea.fictif']), _equipe(AUTRE_EQUIPE, ['admin.fictif'])]})
    avant = base._etat()

    assert base._code_refus(base._declarer(m6, 'wct-equipe', wct_equipe, MARC)) == base.CODE_NON_ASSIGNEE
    assert base._etat() == avant


def test_sans_profil_aucun_acces_par_equipe(m6, wct_equipe, tmp_path, monkeypatch):
    monkeypatch.setenv('OPSYS_HOME', str(tmp_path / 'vide'))
    avant = base._etat()

    assert base._code_refus(base._declarer(m6, 'wct-equipe', wct_equipe, MARC)) == base.CODE_NON_ASSIGNEE
    assert base._etat() == avant


def test_admin_garde_le_droit_sans_audit_de_membre(m6, wct_equipe):
    base._accepte(base._declarer(m6, 'wct-equipe', wct_equipe, ADMIN))

    assert base._consommations('wct-equipe') == [('CONSOMMATION', INT_EQUIPE, -10.0)]
    assert _audits() == []


def test_un_seul_declarant_par_wct_meme_pour_une_equipe(m6, wct_equipe):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, 'paul.fictif', 'Paul Fictif', 'mot-de-passe-paul-1234', ['employee'])
    equipes.enregistrer_equipes({'liste': [_equipe(EQUIPE, ['marc.fictif', 'paul.fictif']),
                                           _equipe(AUTRE_EQUIPE, ['lea.fictif'])]})
    base._accepte(base._declarer(m6, 'wct-equipe', wct_equipe, MARC))
    avant = base._etat()

    paul = contexte.IdentiteAppelante(personne='paul.fictif', role='employee')
    assert base._code_refus(base._declarer(m6, 'wct-equipe', wct_equipe, paul)) == 'REJ-DECLARATION-DEJA-SOUMISE'
    assert base._etat() == avant
    assert [par for par, _, _ in _audits()] == ['marc.fictif']


def test_un_wct_individuel_reste_a_sa_personne(m6, profil):
    """Être membre d'une équipe ne donne aucun droit sur le WCT individuel d'un autre membre ou d'un tiers."""
    base._publier_wct('wct-lea', base.INT_LEA, 'lea.fictif')
    base._receptionner(m6, base.INT_LEA)
    avant = base._etat()

    reponse = base._declarer(m6, 'wct-lea', base._formulaire('wct-lea', base.INT_LEA, base.INT_LEA), MARC)
    assert base._code_refus(reponse) == base.CODE_NON_ASSIGNEE
    assert base._etat() == avant
