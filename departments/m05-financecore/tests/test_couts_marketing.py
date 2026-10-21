"""Répartition analytique humaine, pièces fictives ; réutilise les AP réelles."""

import importlib
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer as ap
from m5_financecore import registre, taux_fiscaux

DATES = {"debut": "2026-09-01", "fin": "2026-09-30"}
CAMPAGNE = {
    "campagne_id": "flyer-fictif", "revision": 1, "empreinte": "a" * 64,
    "nom": "Flyers fictifs", "periode": DATES, "utm_source": "flyer",
    "utm_campaign": "flyer-fictif-2026",
}


@pytest.fixture
def source():
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(
        Path(__file__).resolve().parents[1] / "contracts/taux_fiscaux.v1.yaml"
    )
    assert erreurs == []
    reg = registre.Registre()
    resultat, verdict = ap.saisir_facture_sans_po(
        fournisseur_id="Imprimeur fictif", categorie="marketing", numero_facture="F-FICTIVE",
        date_facture="2026-10-01", montant_avant_taxes="100.00", total_facture=None,
        saisi_par="owner.fictif", voie="approbation", horodatage="2026-10-02T12:00:00+00:00",
        dictionnaire_taux=taux, categories_configurees=("marketing",), registre_cible=reg,
    )
    assert verdict is None, verdict
    return reg, resultat["facture"]["facture_fournisseur_id"], taux


def _module():
    return importlib.import_module("m5_financecore.couts_marketing")


def _arguments(cm, reg, journal, ident, *, part="60.00", base="HT", affectation_id=None):
    return {
        "facture_fournisseur_id": ident, "campagne_id": CAMPAGNE["campagne_id"], **DATES,
        "base": base, "devise": "CAD", "montant_alloue_cad": part, "motif": "Flyers fictifs septembre",
        "sources_attendues": cm.references(reg.lire(), journal.lire(), CAMPAGNE, ident, affectation_id),
        **({"affectation_id": affectation_id} if affectation_id else {}),
    }


def _ajouter(cm, reg, journal, ident, affectation="part-fictive-1", **kwargs):
    corps = cm.preparer_affectation(
        reg.lire(), journal.lire(), CAMPAGNE,
        _arguments(cm, reg, journal, ident, **kwargs), auteur="owner.fictif",
        horodatage="2026-10-02T12:00:00+00:00", nouvel_id=affectation,
    )
    journal.ajouter(corps)
    return corps


def test_centimes_bases_inconnues_et_aucun_decaissement(source):
    cm = _module()
    reg, ident, _ = source
    journal = registre.Registre()
    _ajouter(cm, reg, journal, ident)
    _ajouter(cm, reg, journal, ident, "part-fictive-2", part="40.00")
    projection = cm.projeter(reg.lire(), journal.lire(), CAMPAGNE, **DATES)
    assert projection["totaux_par_base"] == {"HT": "100.00", "TTC": None}
    assert projection["couverture"] == "PARTIELLE"
    assert projection["paiement_cad"] is None and projection["roi"] is None
    assert projection["taxes_non_recuperables_cad"] is None
    assert projection["pieces_eligibles"][0]["montant_apres_taxes"] == "114.98"
    assert projection["pieces_eligibles"][0]["devise_source"] is None
    assert all(ligne["type_entree"].startswith("affectation_cout_marketing") for ligne in journal.lire())


@pytest.mark.parametrize("part", ["0.00", "-0.01", "1.001", "1e2", "NaN", "Inf", "01.00", True, 10.0])
def test_montants_invalides_ne_creent_aucune_part(source, part):
    cm = _module()
    reg, ident, _ = source
    journal = registre.Registre()
    with pytest.raises(cm.CoutErreur, match="MONTANT"):
        _ajouter(cm, reg, journal, ident, part=part)
    assert journal.lire() == []


def test_plafond_et_base_ne_liberent_pas_les_parts_perimees(source):
    cm = _module()
    reg, ident, taux = source
    journal = registre.Registre()
    _ajouter(cm, reg, journal, ident)
    (lue,) = [f for f in ap.factures_saisies(reg) if f["facture_fournisseur_id"] == ident]
    resultat, verdict = ap.corriger_facture_fournisseur(
        facture_fournisseur_id=ident, numero_facture="F-FICTIVE",
        date_facture="2026-10-01", montant_avant_taxes="80.00", total_facture=None,
        motif="Correction fictive", corrige_par="owner.fictif", voie="approbation", role="nathan_owner",
        horodatage="2026-10-02T13:00:00+00:00", dictionnaire_taux=taux, registre_cible=reg,
        revision_attendue=lue["corrections"],
    )
    assert verdict is None, verdict
    assert resultat is not None
    projection = cm.projeter(reg.lire(), journal.lire(), CAMPAGNE, **DATES)
    assert projection["affectations"][0]["statut"] == "PERIMEE_SOURCE_AP"
    with pytest.raises(cm.CoutErreur, match="CAPACITE"):
        _ajouter(cm, reg, journal, ident, "part-2", part="30.00")
    with pytest.raises(cm.CoutErreur, match="BASE"):
        _ajouter(cm, reg, journal, ident, "part-2", part="10.00", base="TTC")
    retrait = cm.preparer_retrait(journal.lire(), "part-fictive-1", 1, cm.snapshot(journal.lire()),
                                 "Retrait fictif", auteur="owner.fictif", horodatage="2026-10-02T14:00:00+00:00")
    journal.ajouter(retrait)
    _ajouter(cm, reg, journal, ident, "part-2", part="80.00")
    assert cm.projeter(reg.lire(), journal.lire(), CAMPAGNE, **DATES)["totaux_par_base"]["HT"] == "80.00"


def test_empty_et_chevauchement_ne_sont_pas_zero(source):
    cm = _module()
    reg, ident, _ = source
    journal = registre.Registre()
    assert cm.projeter(reg.lire(), [], CAMPAGNE, **DATES)["totaux_par_base"] == {"HT": None, "TTC": None}
    _ajouter(cm, reg, journal, ident)
    projection = cm.projeter(reg.lire(), journal.lire(), CAMPAGNE, debut="2026-09-10", fin="2026-09-30")
    assert projection["totaux_par_base"]["HT"] is None
    assert projection["exclusions"]["CHEVAUCHEMENT_PARTIEL"] == 1
    assert projection["couverture"] == "INCONNUE"


def test_autre_piece_ne_perime_pas_et_tamper_ferme(source):
    cm = _module()
    reg, ident, taux = source
    journal = registre.Registre()
    _ajouter(cm, reg, journal, ident)
    _resultat, verdict = ap.saisir_facture_sans_po(
        fournisseur_id="Autre fictif", categorie="marketing", numero_facture="F-AUTRE", date_facture="2026-10-01",
        montant_avant_taxes="25.00", total_facture=None, saisi_par="owner.fictif", voie="approbation",
        horodatage="2026-10-02T14:00:00+00:00", dictionnaire_taux=taux,
        categories_configurees=("marketing",), registre_cible=reg,
    )
    assert verdict is None
    assert cm.projeter(reg.lire(), journal.lire(), CAMPAGNE, **DATES)["affectations"][0]["statut"] == "COURANTE"
    brise = reg.lire()
    brise[0]["montant_avant_taxes"] = Decimal("1000.00")
    with pytest.raises(cm.CoutErreur, match="CHAINE"):
        cm.projeter(brise, journal.lire(), CAMPAGNE, **DATES)


def test_pagination_snapshot_et_totaux_sur_toutes_les_parts(source):
    cm = _module()
    reg, ident, _ = source
    journal = registre.Registre()
    for indice in range(12):
        _ajouter(cm, reg, journal, ident, f"part-fictive-{indice:02d}", part="5.00")
    premiere = cm.projeter(reg.lire(), journal.lire(), CAMPAGNE, **DATES)
    assert premiere["pagination"] == {"offset": 0, "total": 12, "affichees": 10, "reste": 2, "suivant": 10}
    assert premiere["totaux_par_base"]["HT"] == "60.00"
    suivante = cm.projeter(reg.lire(), journal.lire(), CAMPAGNE, **DATES, offset_affectations=10,
                          snapshot_attendu=premiere["observation_source"])
    assert suivante["pagination"]["affichees"] == 2 and suivante["totaux_par_base"]["HT"] == "60.00"
    assert {m["affectation_id"] for m in premiere["affectations"]}.isdisjoint(
        {m["affectation_id"] for m in suivante["affectations"]},
    )
    _ajouter(cm, reg, journal, ident, "part-fictive-tardive", part="5.00")
    with pytest.raises(cm.CoutErreur, match="PAGE-PERIMEE"):
        cm.projeter(reg.lire(), journal.lire(), CAMPAGNE, **DATES, offset_affectations=10,
                    snapshot_attendu=premiere["observation_source"])


@pytest.mark.parametrize("debut,fin", [("2026-09-30", "2026-09-01"), ("2025-09-01", "2026-09-30"),
                                     ("2026-9-1", "2026-09-30"), ("2026-02-30", "2026-09-30")])
def test_periodes_incorrectes_ne_creent_pas_de_part(source, debut, fin):
    cm = _module()
    reg, ident, _ = source
    journal = registre.Registre()
    args = _arguments(cm, reg, journal, ident) | {"debut": debut, "fin": fin}
    with pytest.raises(cm.CoutErreur, match="PERIODE"):
        cm.preparer_affectation(reg.lire(), [], CAMPAGNE, args, auteur="owner.fictif",
                               horodatage="2026-10-02T12:00:00+00:00", nouvel_id="part-fictive")
    assert journal.lire() == []


def test_retrait_cas_et_cible_revision_restent_explicitement_lies(source):
    cm = _module()
    reg, ident, _ = source
    journal = registre.Registre()
    _ajouter(cm, reg, journal, ident)
    with pytest.raises(cm.CoutErreur, match="SNAPSHOT"):
        cm.preparer_retrait(journal.lire(), "part-fictive-1", True, cm.snapshot(journal.lire()), "Fictif",
                            auteur="owner.fictif", horodatage="2026-10-02T12:00:00+00:00")
    autre = CAMPAGNE | {"campagne_id": "autre-fictive"}
    args = _arguments(cm, reg, journal, ident, affectation_id="part-fictive-1") | {"campagne_id": "autre-fictive"}
    with pytest.raises(cm.CoutErreur, match="CIBLE-DIFFERENTE"):
        cm.preparer_affectation(reg.lire(), journal.lire(), autre, args, auteur="owner.fictif",
                               horodatage="2026-10-02T12:00:00+00:00", nouvel_id="ne-doit-pas-exister")
    assert len(journal.lire()) == 1
