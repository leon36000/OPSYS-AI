import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import outils, registre

from opsys import stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer_atomique

D = "m05-financecore"
R = "factures"


def args(n):
    return dict(
        facture_id="FICTIF-FACT-" + n,
        chantier_id="FICTIF-CHANT-" + n,
        devis_id="FICTIF-DEVIS-" + n,
        client_id="FICTIF-CLIENT",
        lignes=[
            dict(
                description="FICTIF",
                quantite="1",
                unite="forfait",
                prix_unitaire="100.00",
                reference_ligne_devis="FICTIF-L1",
            )
        ],
        horodatage="2026-08-03T12:00:00+00:00",
    )


def journal():
    return registre.Registre(stockage.maillons(D, R))


@pytest.fixture
def outil(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-fictive"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    stockage.migrer()
    outils.utiliser_stockage_durable()
    o = next(
        o
        for o in charger_departements(Path.cwd() / "departments")[D].charger_outils()
        if o.nom == "m5_creer_facture_brouillon"
    )
    assert o.autonomie == Autonomie.T1
    yield o
    stockage.liberer()


def _wire(outil):
    r = executer_atomique(outil, dict(args("A"), factures_historique=[]))
    assert r["ok"] and r["resultat"]["accepte"]
    return json.loads(json.dumps(r["resultat"]["factures_historique"]))


def test_api_json_rejeu_identique_sans_effet_natif(outil):
    h = _wire(outil)
    avant = copy.deepcopy(h)
    r = executer_atomique(outil, dict(args("A"), factures_historique=h))
    assert r["ok"] and r["resultat"]["accepte"]
    assert r["resultat"]["factures_historique"] == avant and h == avant and journal().taille() == 0


def test_wire_reconstitue_decimal_empreinte_et_taux_textuels(outil):
    h = _wire(outil)
    avant = copy.deepcopy(h)
    relus = outils._rejouer_registre(h).lire()
    assert [x["ligne_id"] for x in relus] == [x["ligne_id"] for x in h]
    for x in relus:
        assert all(type(x[k]) is Decimal for k in ["montant_avant_taxes", "total_taxes", "montant_apres_taxes"])
        assert all(type(ligne[k]) is Decimal for ligne in x["lignes"] for k in ["quantite", "prix_unitaire", "montant"])
        assert all(type(t["montant"]) is Decimal and type(t["taux"]) is str for t in x["taxes"])
    assert h == avant


def test_historique_type_preserve_et_ne_touche_pas_journal(outil):
    assert executer_atomique(outil, args("SEED"))["resultat"]["accepte"]
    natif = journal().lire()
    h = copy.deepcopy(natif)
    assert outils._rejouer_registre(h).lire() == natif and h == natif
    r = executer_atomique(outil, dict(args("A"), factures_historique=h))
    assert r["ok"] and r["resultat"]["accepte"]
    stockage.liberer()
    assert journal().lire() == natif and h == natif


def test_rejeu_ne_recalcule_pas_taxes_historiques(outil, monkeypatch):
    h = _wire(outil)
    avant = copy.deepcopy(h)

    def interdit(*a, **k):
        raise AssertionError("historique ne doit pas recalculer les taxes")

    monkeypatch.setattr(outils.taxes, "calculer_taxes", interdit)
    assert outils._rejouer_registre(h).lire()[0]["ligne_id"] == h[0]["ligne_id"]
    assert h == avant and journal().taille() == 0


CHAMPS = [
    ("montant_avant_taxes",),
    ("total_taxes",),
    ("montant_apres_taxes",),
    ("lignes", 0, "quantite"),
    ("lignes", 0, "prix_unitaire"),
    ("lignes", 0, "montant"),
    ("taxes", 0, "montant"),
]


@pytest.mark.parametrize("chemin", CHAMPS)
@pytest.mark.parametrize("invalide", [1.25, True, "NaN", "texte-invalide"])
def test_nombre_historique_invalide_refuse_sans_ecrire(outil, chemin, invalide):
    h = _wire(outil)
    cible = h[0]
    for cle in chemin[:-1]:
        cible = cible[cle]
    cible[chemin[-1]] = invalide
    avant = copy.deepcopy(h)
    r = executer_atomique(outil, dict(args("A"), factures_historique=h))
    assert not r["ok"] and r["erreur"] == "refus_metier"
    assert h == avant and journal().taille() == 0


@pytest.mark.parametrize("collection", ["lignes", "taxes"])
@pytest.mark.parametrize("invalide", [None, "texte", ["pas-un-dict"]])
def test_collection_historique_mal_formee_refuse(outil, collection, invalide):
    h = _wire(outil)
    h[0][collection] = invalide
    avant = copy.deepcopy(h)
    r = executer_atomique(outil, dict(args("A"), factures_historique=h))
    assert not r["ok"] and r["erreur"] == "refus_metier"
    assert h == avant and journal().taille() == 0


def test_plusieurs_factures_json_conservent_chaine_rejeu_et_conflit(outil):
    historique = []
    for identite in ["A", "B"]:
        r = executer_atomique(outil, dict(args(identite), factures_historique=historique))
        assert r["ok"] and r["resultat"]["accepte"]
        nouveau = json.loads(json.dumps(r["resultat"]["factures_historique"]))
        assert nouveau[:-1] == historique
        historique = nouveau
    avant = copy.deepcopy(historique)
    assert historique[1]["precedent_ligne_id"] == historique[0]["ligne_id"]
    for identite in ["A", "B"]:
        r = executer_atomique(outil, dict(args(identite), factures_historique=historique))
        assert r["ok"] and r["resultat"]["accepte"]
        assert r["resultat"]["factures_historique"] == avant
    modifie = args("A")
    modifie["lignes"][0]["prix_unitaire"] = "200.00"
    r = executer_atomique(outil, dict(modifie, factures_historique=historique))
    assert r["ok"] and not r["resultat"]["accepte"]
    assert historique == avant and journal().taille() == 0
