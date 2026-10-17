"""Comptes à payer : une panne APRÈS l'ajout au registre durable, avant la réponse, n'écrit rien (PLAN T4.15, T4.15-c).

L'outil ajoute la pièce au registre durable puis bâtit sa réponse (rapprochement proposé du PO, ou total sans PO). Une
panne entre les deux annule tout (`executer_atomique` : la transaction est annulée, l'exception remonte ; par la file,
`decider` la clôt en `panne_execution`) : aucune pièce partielle, la chaîne reste valide après une
réouverture fictive de la base (`stockage.liberer`), la demande en échec ne se rejoue pas, et la reprise écrit
exactement une pièce. Aucune preuve de crash, fsync ou PostgreSQL : SQLite fichier fictif seulement.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest

from opsys import approbations as opsys_approbations
from opsys import stockage
from opsys.capacites import Capacites, outils_executables
from opsys.stockage.maillons import MaillonsDurables

FICTIF = True
_spec = importlib.util.spec_from_file_location(
    "correction_outils_panne_fictif", Path(__file__).resolve().parent / "test_correction_outils.py"
)
_o = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_o)
base_durable = _o.base_durable
dep = _o.dep
par_nom = _o.par_nom
facture = _o.facture
declare = _o.declare
DEPARTEMENT = _o.DEPARTEMENT


_RAPPROCHEMENT = m5_outils.comptes_a_payer.proposer_rapprochement


def _panne(*_args, **_kwargs):
    raise RuntimeError("panne fictive après l'ajout au registre")


def _chaine_relue_apres_reouverture():
    stockage.liberer()
    with stockage.transaction():
        maillons = list(stockage.maillons(DEPARTEMENT, "comptes_a_payer"))
    copie = m5_outils.registre_module.Registre(maillons=maillons)
    assert copie.valider_chaine() == (True, "")
    return maillons


def _decider(dep, demande_id):
    with stockage.transaction() as cnx:
        return opsys_approbations.decider(
            cnx, demande_id, True, "nathan", outils_executables({DEPARTEMENT: dep}, stockage.transaction),
            {DEPARTEMENT: dep})


def test_panne_apres_l_ajout_d_une_correction_par_la_file_n_ecrit_rien_et_la_reprise_ecrit_une_piece(
    base_durable, dep, par_nom, facture, monkeypatch
):
    avant = _o._registre_ap()
    ajouts = []
    original = MaillonsDurables.append

    def compter(self, maillon, *, rang_attendu=None):
        ajouts.append(maillon.get("type_entree"))
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", compter)
    monkeypatch.setattr(m5_outils.comptes_a_payer, "proposer_rapprochement", _panne)
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    demande = capacites.appeler("m5_corriger_facture_fournisseur",
                                _o._corriger_args(facture, revision_attendue=_o._revision_lue(facture)))
    decision = _decider(dep, demande["demande_id"])

    assert ajouts == ["correction_facture_fournisseur"], "la pièce a bien été ajoutée avant la panne"
    assert decision["statut"] == "echec" and decision["reponse"]["erreur"] == "panne_execution"
    assert _chaine_relue_apres_reouverture() == avant, "aucune pièce partielle"
    with pytest.raises(ValueError, match="déjà traitée"):
        _decider(dep, demande["demande_id"])

    monkeypatch.setattr(MaillonsDurables, "append", original)
    monkeypatch.setattr(m5_outils.comptes_a_payer, "proposer_rapprochement", _RAPPROCHEMENT)
    reprise = Capacites({DEPARTEMENT: dep}, stockage.transaction).appeler(
        "m5_corriger_facture_fournisseur", _o._corriger_args(facture, revision_attendue=_o._revision_lue(facture)))
    assert _decider(dep, reprise["demande_id"])["statut"] == "executee"
    apres = _chaine_relue_apres_reouverture()
    assert apres[:len(avant)] == avant and [m["type_entree"] for m in apres[len(avant):]] == [
        "correction_facture_fournisseur"]
    assert _o._le_po(par_nom)["factures"]["apres_taxes"] == "356.42"
    with pytest.raises(ValueError, match="déjà traitée"):
        _decider(dep, reprise["demande_id"])
    assert _chaine_relue_apres_reouverture() == apres, "une décision exécutée ne se rejoue pas"


def test_panne_apres_l_ajout_d_une_saisie_par_l_appareil_n_ecrit_rien_et_la_ressaisie_passe_une_fois(
    base_durable, dep, par_nom, monkeypatch
):
    _o._recevoir(dep)
    avant = _chaine_relue_apres_reouverture()
    monkeypatch.setattr(m5_outils.comptes_a_payer, "proposer_rapprochement", _panne)

    with pytest.raises(RuntimeError, match="panne fictive"):
        _o._appeler(par_nom, "m5_saisir_facture_fournisseur", _o._facture_args(), _o.COMPTABLE)

    assert _chaine_relue_apres_reouverture() == avant
    monkeypatch.setattr(m5_outils.comptes_a_payer, "proposer_rapprochement", _RAPPROCHEMENT)
    assert _o._accepte(_o._appeler(par_nom, "m5_saisir_facture_fournisseur", _o._facture_args(), _o.COMPTABLE))
    rejeu = _o._appeler(par_nom, "m5_saisir_facture_fournisseur", _o._facture_args(), _o.COMPTABLE)
    assert _o._code(rejeu) == "REJ-AP-FACTURE-DOUBLON"
    apres = _chaine_relue_apres_reouverture()
    assert [m["type_entree"] for m in apres[len(avant):]] == ["facture_fournisseur_saisie"]


def test_panne_apres_l_ajout_d_une_facture_sans_po_n_ecrit_rien(base_durable, par_nom, declare, monkeypatch):
    declare(_o.CATEGORIES)
    avant = _chaine_relue_apres_reouverture()
    monkeypatch.setattr(m5_outils.comptes_a_payer, "totaux_sans_po", _panne)

    with pytest.raises(RuntimeError, match="panne fictive"):
        _o._appeler(par_nom, "m5_saisir_facture_sans_po", _o._sans_po_args(), _o.COMPTABLE)

    assert _chaine_relue_apres_reouverture() == avant == []
