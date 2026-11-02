"""M5 -> M2 : une facture PAYÉE ou ANNULÉE lève la relance de créance (`m5.facture_emise_constatee`).

Défaut fermé (revue adverse rvi, INTERCONNEXION.md §7) : M2 gardait la relance de créance de plus haut niveau sans
jamais la lever quand la facture était payée. Décision d'architecte, prise après lecture du catalogue de la phase 2 :
on RÉUTILISE `m5.facture_emise_constatee` (M5 en publie déjà un par (facture, statut), PAYEE et ANNULEE comprises, dans
le cycle comptable) au lieu d'un nouveau type ; M8 le consomme toujours comme avant. Bus réel, consommateurs réels
(M2, M8), outils réels de M5 pour le producteur. Prouve : levée, ordre inversé, rejeu, A -> B -> A, paiement partiel
(la relance reste), facture annulée, une autre facture du même client. Fictif.
"""

from __future__ import annotations

import json

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
import yaml
from m2_revenue_crm import faits_interconnexion as fi
from m2_revenue_crm import outils as outils_m2
from m5_financecore import constats_pour_m8, facturation, taux_fiscaux
from m5_financecore import outils as m5_outils
from m5_financecore import registre as registre_m5

from opsys import evenements, stockage
from opsys.outils import executer_atomique

FICTIF = True
M2, M5, M8 = "m02-revenue-crm", "m05-financecore", "m08-analytics"
H = "2026-11-02T10:00:00-04:00"
CONFIG = {
    "categories_depense_sans_po": ["carburant", "outils"],
    "operations": {
        "relances": {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7, 21, 45]},
        "compte_remboursement_employes": "2200",
        "rapprochement": {"motifs_frais": ["frais mensuels"], "compte_frais_bancaires": "5800"},
    },
}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M2, M5, M8))
    m.surveiller(monkeypatch)
    manifeste = tmp_path / "department-m5.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": CONFIG}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    yield m
    im.demonter()


@pytest.fixture
def m5():
    return {o.nom: o for o in m5_outils.outils()}


def _taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    return dictionnaire


def _facturer(facture_id, *, client="client-fictif", envoi="2026-10-02T09:00:00-04:00"):
    """Une facture de 600.00 $ avant taxes (689.85 $), envoyée par une personne le `envoi`."""
    with stockage.transaction():
        reg = registre_m5.Registre(maillons=stockage.maillons(M5, "factures"))
        lignes = [
            {
                "description": "Travaux (fictif)",
                "quantite": "1",
                "unite": "forfait",
                "prix_unitaire": "600.00",
                "reference_ligne_devis": "L1",
            }
        ]
        for couple in (
            facturation.creer_facture_brouillon(
                facture_id,
                f"CH-{facture_id}",
                f"D-{facture_id}",
                client,
                lignes,
                "2026-10-01T09:00:00-04:00",
                _taux(),
                reg,
            ),
            facturation.envoyer_facture(facture_id, envoi, reg),
        ):
            assert couple[1] is None, couple


def _payer(facture_id, montant="689.85"):
    with stockage.transaction():
        reg = registre_m5.Registre(maillons=stockage.maillons(M5, "factures"))
        return facturation.enregistrer_paiement_facture(facture_id, montant, "nathan", "2026-10-20T09:00:00-04:00", reg)


def _appeler(par_nom, nom, arguments):
    reponse = executer_atomique(par_nom[nom], arguments)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _relances(m5, jour):
    return _appeler(m5, "m5_preparer_relances_clients", {"aujourd_hui": jour, "horodatage": H})


def _constater(m5):
    return _appeler(m5, "m5_constater_factures_emises", {"horodatage": H})


def _ouvertes(monde):
    with stockage.transaction():
        return outils_m2._creances_recues()


def _par_client(monde):
    return fi.creances_par_client(_ouvertes(monde))


def _relance(relance_id, facture_id, niveau, client="client-fictif", **plus):
    return ch.creance_relance(relance_id=relance_id, facture_id=facture_id, client_id=client, niveau=niveau, **plus)


def _publier_relance(monde, ident, **kw):
    evenements.publier("m5.creance_relance_preparee", M5, _relance(**kw), evenement_id=ident)


def _publier_etat(ident, facture_id, statut):
    evenements.publier(
        "m5.facture_emise_constatee", M5, ch.facture_emise(facture_id=facture_id, statut=statut), evenement_id=ident
    )


# ---------------------------------------------------------------------------------------- de bout en bout réel
def test_de_bout_en_bout_le_paiement_leve_la_relance_apres_le_cycle_comptable_de_m5(monde, m5):
    _facturer("F-1")
    _relances(m5, "2026-11-10")
    monde.repartir()
    assert [c["facture_id"] for c in _ouvertes(monde)] == ["F-1"] and "client-fictif" in _par_client(monde)
    assert _payer("F-1")[1] is None  # paiement exact, par la voie de M5 (frontière humaine N5 au socle)
    # La relance déjà publiée ne se retire pas du bus : c'est l'état de la facture qui la lève.
    cycle = _appeler(m5, "m5_executer_cycle_comptable", {"aujourd_hui": "2026-11-11", "horodatage": H, "periode": None})
    assert any(e["etape"] == "factures_emises_pour_m8" for e in cycle["etapes"])
    resume = monde.repartir()
    assert resume["quarantaines"] == 0 and resume["echecs"] == 0
    assert _ouvertes(monde) == [] and _par_client(monde) == {}
    # La relance est toujours au registre de M2 (audit) ; M8 a reçu les mêmes constats qu'avant (PAYEE comprise).
    assert monde.taille(M2, fi.REGISTRE_CREANCES) == 1
    statuts_m8 = [f["statut"] for f in monde.registre(M8, "faits_operations") if f["type_entree"] == "facture_emise"]
    assert statuts_m8 == ["PAYEE"]
    assert monde.ecritures_hors_propriete() == []


def test_paiement_partiel_ne_leve_rien_la_relance_reste(monde, m5):
    _facturer("F-1")
    _relances(m5, "2026-11-10")
    monde.repartir()
    donnees, verdict = _payer("F-1", "300.00")
    assert donnees is None and verdict["code"] == "REJ-FACTURE-PAIEMENT-PARTIEL"
    _constater(m5)
    monde.repartir()
    assert [c["facture_id"] for c in _ouvertes(monde)] == ["F-1"]
    assert monde.taille(M2, fi.REGISTRE_FACTURES_CLOSES) == 0  # l'état ENVOYEE ne range rien


def test_une_autre_facture_du_meme_client_garde_son_avertissement(monde, m5):
    _facturer("F-1")
    _facturer("F-2", envoi="2026-10-05T09:00:00-04:00")
    _relances(m5, "2026-11-25")
    monde.repartir()
    assert _par_client(monde)["client-fictif"]["niveau"] == 2
    assert _payer("F-1")[1] is None
    _constater(m5)
    monde.repartir()
    restantes = {c["facture_id"] for c in _ouvertes(monde)}
    assert restantes == {"F-2"} and _par_client(monde)["client-fictif"]["facture_id"] == "F-2"


# ---------------------------------------------------------------------------------------- ordre, rejeu, A -> B -> A
def test_ordre_inverse_le_paiement_livre_avant_la_relance_la_leve_aussi(monde):
    _publier_etat("e-payee", "F-9", "PAYEE")
    monde.repartir()
    _publier_relance(monde, "r-9", relance_id="rel-9", facture_id="F-9", niveau=3)
    monde.repartir()
    assert monde.taille(M2, fi.REGISTRE_CREANCES) == 1 and _ouvertes(monde) == []


def test_a_b_a_un_etat_plus_ancien_ou_une_relance_rejouee_ne_rouvre_jamais(monde):
    _publier_relance(monde, "r-1", relance_id="rel-1", facture_id="F-1", niveau=2)
    monde.repartir()
    assert len(_ouvertes(monde)) == 1  # A : due
    _publier_etat("e-payee", "F-1", "PAYEE")
    monde.repartir()
    assert _ouvertes(monde) == []  # B : payée
    # A de nouveau : l'état ENVOYEE (plus ancien) arrive APRÈS le paiement, et la relance est rejouée sous d'autres id.
    _publier_etat("e-envoyee-tardive", "F-1", "ENVOYEE")
    _publier_relance(monde, "r-1-bis", relance_id="rel-1", facture_id="F-1", niveau=2)
    _publier_relance(monde, "r-1-autre", relance_id="rel-1b", facture_id="F-1", niveau=3)
    resume = monde.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    assert _ouvertes(monde) == [] and _par_client(monde) == {}
    assert monde.taille(M2, fi.REGISTRE_FACTURES_CLOSES) == 1


def test_le_rejeu_du_paiement_sous_un_autre_identifiant_n_ajoute_rien(monde):
    _publier_etat("e-1", "F-1", "PAYEE")
    monde.repartir()
    _publier_etat("e-2", "F-1", "PAYEE")
    resume = monde.repartir()
    assert resume["quarantaines"] == 0 and monde.taille(M2, fi.REGISTRE_FACTURES_CLOSES) == 1


def test_facture_annulee_leve_aussi_la_relance(monde):
    _publier_relance(monde, "r-1", relance_id="rel-1", facture_id="F-1", niveau=1)
    # La charge d'un état ANNULEE est celle que M5 construirait (aucun outil n'annule encore une facture client).
    charge = constats_pour_m8.charge_facture_emise(
        {
            "statut": "ANNULEE",
            "facture_id": "F-1",
            "date_envoi": "2026-10-02T09:00:00-04:00",
            "montant_avant_taxes": "600.00",
            "total_taxes": "89.85",
            "montant_apres_taxes": "689.85",
        }
    )
    evenements.publier("m5.facture_emise_constatee", M5, charge, evenement_id=charge["evenement_id"])
    monde.repartir()
    assert _ouvertes(monde) == []
    assert [f["statut"] for f in monde.registre(M2, fi.REGISTRE_FACTURES_CLOSES)] == ["ANNULEE"]


def test_un_etat_seulement_envoyee_ne_range_rien_et_ne_leve_rien(monde):
    _publier_relance(monde, "r-1", relance_id="rel-1", facture_id="F-1", niveau=1)
    _publier_etat("e-1", "F-1", "ENVOYEE")
    resume = monde.repartir()
    assert resume["quarantaines"] == 0 and monde.taille(M2, fi.REGISTRE_FACTURES_CLOSES) == 0
    assert len(_ouvertes(monde)) == 1
    resultat = [r for r in monde.recus(consommateur=M2) if r["evenement_id"] == "e-1"][0]
    assert resultat["statut"] == "traite" and "facture_due" in str(resultat["resultat"])


# ---------------------------------------------------------------------------------------- minimisation
def test_m2_ne_garde_ni_montant_ni_client_ni_date_d_une_facture_close(monde):
    _publier_etat("e-1", "F-1", "PAYEE")
    monde.repartir()
    (fait,) = monde.registre(M2, fi.REGISTRE_FACTURES_CLOSES)
    assert set(fait) - {"ligne_id", "precedent_ligne_id", "horodatage", "empreinte"} == {
        "type_entree",
        "facture_id",
        "statut",
    }
    texte = json.dumps(fait)
    for interdit in ("689", "600.00", "149.75", "CAD", "client"):
        assert interdit not in texte


def test_fonctions_pures_fait_facture_close_et_creances_ouvertes():
    assert fi.fait_facture_close(ch.facture_emise(statut="ENVOYEE")) is None
    assert fi.fait_facture_close(ch.facture_emise(facture_id="F-7", statut="PAYEE")) == {
        "type_entree": fi.TYPE_FACTURE_CLOSE,
        "facture_id": "F-7",
        "statut": "PAYEE",
    }
    creances = [fi.fait_creance(_relance("a", "F-1", 1)), fi.fait_creance(_relance("b", "F-2", 2))]
    closes = [fi.fait_facture_close(ch.facture_emise(facture_id="F-1", statut="PAYEE"))]
    assert [c["relance_id"] for c in fi.creances_ouvertes(creances, closes)] == ["b"]
    assert [c["relance_id"] for c in fi.creances_ouvertes(creances, [])] == ["a", "b"]
    assert fi.creances_ouvertes([], closes) == []
    # un fait d'un autre type dans le registre des factures closes ne lève rien
    autre = [{"type_entree": "autre", "facture_id": "F-2"}]
    assert len(fi.creances_ouvertes(creances, autre)) == 2


def test_evenements_m5_et_m2_vont_ensemble_dans_le_manifeste():
    from m2_revenue_crm import outils as o

    assert "m5.facture_emise_constatee" in o.consommateurs()
