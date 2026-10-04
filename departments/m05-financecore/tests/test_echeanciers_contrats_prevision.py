"""M5.8a : échéanciers contractuels relus sur les registres SQLite fictifs."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import facturation, registre, taux_fiscaux
from sqlalchemy import select, update

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

FICTIF = True
TODAY = "2026-10-01"
OWNER = contexte.IdentiteAppelante(personne="nathan.fictif", role="nathan_owner", source="console")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
ADMIN_CONSOLE = contexte.IdentiteAppelante(personne="admin.fictif", role="admin", source="console")
OWNER_DEVICE = contexte.IdentiteAppelante(personne="nathan.fictif", role="nathan_owner", source="appareil")
EMPLOYEE = contexte.IdentiteAppelante(personne="employe.fictif", role="employee")


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm58a.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    config = {
        "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12,
                   "taxes_remises_jusqu_au": "2026-06-30"},
        "obligations_declarees": {},
        "prevision": {"horizon_semaines": 6, "delai_encaissement_clients_jours": 30,
                      "delai_paiement_fournisseurs_jours": 30},
    }
    manifest = tmp_path / "department.yaml"
    manifest.write_text(yaml.safe_dump({"configuration": config}), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifest)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan.fictif", "Nathan Fictif", "mot-de-passe-nathan-123", ["nathan_owner"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-123", ["admin"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-123", ["employee"])
    yield tmp_path
    stockage.liberer()


def _tool(name):
    return next(tool for tool in m5_outils.outils() if tool.nom == name)


def _call(name, arguments, caller=OWNER):
    with contexte.appele_par_appareil(caller):
        return executer_atomique(_tool(name), arguments)


def _quote(devis_id="DEVIS-58A"):
    with stockage.transaction():
        result = m5_outils._recevoir_devis_accepte({
            "devis_id": devis_id, "lead_id": "LEAD-1", "chantier_id": "CHANTIER-1",
            "lignes": [{"description": "travaux fictifs", "quantite": "1", "unite": "u",
                        "prix_unitaire": "1000.00", "reference_ligne": "L-1"}],
            "prix_total": "1000.00", "horodatage_acceptation": "2026-09-20T12:00:00-04:00",
        })
        assert result["statut"] == "en_attente_travaux_termines"
        mouvements = m5_outils._registre_mouvements(None)
        registre.enregistrer_mouvement({
            "montant": Decimal("20000.00"), "type_mouvement": "ENCAISSEMENT",
            "horodatage": "2026-09-30T12:00:00-04:00", "classe_retention": "STANDARD",
            "source": "solde initial fictif",
        }, mouvements)


def _contract_args():
    return {
        "contrat_id": "CTR-58A", "devis_id": "DEVIS-58A", "prix_ht": "1000.00",
        "prix_ttc": "1149.75", "devise": "CAD", "source_humaine": "Pièce contractuelle fictive C-58A",
        "date_source": "2026-09-21", "couverture_jusquau": "2026-11-11",
        "echeances": [{"date": "2026-10-31", "montant_ttc": "1149.75"}],
        "revision_attendue": 0, "ligne_id_attendue": "", "motif": "Saisie humaine fictive",
    }


def _facture_envoyee(*, payee=False):
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    with stockage.transaction():
        journal = m5_outils._registre_factures(None)
        facture, verdict = facturation.creer_facture_brouillon(
            "FAC-58A", "CHANTIER-1", "DEVIS-58A", "CLIENT-1",
            [{"description": "travaux fictifs", "quantite": "1", "unite": "u",
              "prix_unitaire": "1000.00", "reference_ligne_devis": "L-1"}],
            "2026-10-01T09:00:00-04:00", taux, journal, montant_avant_taxes_fourni="1000.00",
        )
        assert verdict is None, verdict
        _sent, verdict = facturation.envoyer_facture("FAC-58A", "2026-10-01T09:30:00-04:00", journal)
        assert verdict is None, verdict
        if payee:
            _payee, verdict = facturation.marquer_facture_payee(
                "FAC-58A", "Nathan fictif", "2026-10-02T09:30:00-04:00", journal,
            )
            assert verdict is None, verdict
    return facture["montant_apres_taxes"]


def test_un_devis_m3_sans_contrat_ne_devient_pas_un_encaissement(base):
    _quote()
    result = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})

    assert result["ok"] is True, result
    page = result["resultat"]["resultat"]
    assert page["contrats"]["statut"] == "PARTIEL"
    assert page["contrats"]["echeances_rapprochees"] == []
    assert page["contrats"]["devis_sans_echeancier"] == ["DEVIS-58A"]
    baseline = _call("m5_prevoir_tresorerie", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    assert page["semaines"] == baseline["semaines"]


def test_facture_active_du_devis_empeche_le_double_compte_contractuel(base):
    _quote()
    ttc = _facture_envoyee()
    arguments = _contract_args()
    arguments["prix_ttc"] = format(ttc, ".2f")
    arguments["echeances"][0]["montant_ttc"] = format(ttc, ".2f")
    enregistrement = _call("m5_enregistrer_echeancier_contrat", arguments)
    assert enregistrement["ok"] is True and enregistrement["resultat"]["accepte"] is True, enregistrement

    result = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})
    assert result["ok"] is True, result
    page = result["resultat"]["resultat"]
    assert page["contrats"]["echeances_rapprochees"] == []
    bloque = page["contrats"]["bloques"]
    assert bloque == [{"contrat_id": "CTR-58A", "devis_id": "DEVIS-58A",
                       "code": "REJ-CONTRAT-FACTURE-EXISTANTE", "facture_id": "FAC-58A"}]
    assert page["contrats"]["echeances_rapprochees"] == []
    baseline = _call("m5_prevoir_tresorerie", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    assert page["semaines"] == baseline["semaines"]


def test_echeancier_ht_rapproche_et_ttc_explicite_alimente_le_meme_solde(base):
    _quote()
    avant = len(stockage.maillons("m05-financecore", "principal"))
    enregistrement = _call("m5_enregistrer_echeancier_contrat", _contract_args())
    assert enregistrement["ok"] is True and enregistrement["resultat"]["accepte"] is True, enregistrement

    result = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})
    page = result["resultat"]["resultat"]
    assert page["contrats"]["statut"] == "PARTIEL"
    assert page["contrats"]["echeances_rapprochees"] == [{
        "contrat_id": "CTR-58A", "devis_id": "DEVIS-58A", "echeance": "1",
        "date": "2026-10-31", "montant_ttc": "1149.75", "source_humaine": "Pièce contractuelle fictive C-58A",
        "qualification_source": "REFERENCE_HUMAINE_NON_VERIFIEE",
        "date_source": "2026-09-21", "ligne_id": enregistrement["resultat"]["resultat"]["ligne_id"],
    }]
    baseline = _call("m5_prevoir_tresorerie", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    assert page["semaines"][4]["lignes"] == baseline["semaines"][4]["lignes"] + 1
    assert page["calculable"] is False
    assert len(stockage.maillons("m05-financecore", "principal")) == avant


def test_prevision_complete_part_du_solde_registre_et_ajoute_le_ttc_une_fois(base):
    _quote()
    configuration = {
        "fiscal": {
            "frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12,
            "taxes_remises_jusqu_au": "2026-06-30",
        },
        "obligations_declarees": {
            "paies": {"montant": "0.00", "source": "déclaration fictive", "au": "2026-09-25"},
            "das": {"montant": "0.00", "source": "déclaration fictive", "au": "2026-09-25"},
            "dettes": {"montant": "0.00", "source": "déclaration fictive", "au": "2026-09-25"},
        },
        "prevision": {
            "horizon_semaines": 6,
            "seuil_alerte": {"montant": "10000.00", "source": "seuil fictif", "au": "2026-09-25"},
            "delai_encaissement_clients_jours": 30,
            "delai_paiement_fournisseurs_jours": 30,
            "echeances_obligations": {"paies": "2026-10-09", "das": "2026-10-15", "dettes": "2026-10-31"},
        },
    }
    Path(base, "department.yaml").write_text(yaml.safe_dump({"configuration": configuration}), encoding="utf-8")
    enregistrement = _call("m5_enregistrer_echeancier_contrat", _contract_args())
    assert enregistrement["resultat"]["accepte"] is True
    avant = {
        nom: list(stockage.maillons("m05-financecore", nom))
        for nom in ("principal", "factures", "comptes_a_payer", "echeanciers_contrats_tresorerie")
    }

    page = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})["resultat"]["resultat"]

    assert page["calculable"] is True
    assert page["solde_initial"]["montant"] == "20000.00"
    assert page["semaines"][4]["solde_fin"] == "21149.75"
    assert page["semaines"][4]["entrees"] == "1149.75"
    assert page["semaines"][4]["sorties"] == "0.00"
    assert page["semaines"][4]["lignes"] == 1
    assert page["contrats"]["echeances_rapprochees"][0]["montant_ttc"] == "1149.75"
    assert {
        nom: list(stockage.maillons("m05-financecore", nom))
        for nom in avant
    } == avant


def test_obligations_non_nulles_de_m57_restent_comptees_une_fois(base):
    _quote()
    configuration = {
        "fiscal": {
            "frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12,
            "taxes_remises_jusqu_au": "2026-06-30",
        },
        "obligations_declarees": {
            "paies": {"montant": "4200.00", "source": "brouillon fictif", "au": "2026-09-25"},
            "das": {"montant": "1350.75", "source": "déclaration fictive", "au": "2026-09-25"},
            "dettes": {"montant": "800.00", "source": "prêt fictif", "au": "2026-09-01"},
        },
        "prevision": {
            "horizon_semaines": 6,
            "seuil_alerte": {"montant": "10000.00", "source": "seuil fictif", "au": "2026-09-25"},
            "delai_encaissement_clients_jours": 30,
            "delai_paiement_fournisseurs_jours": 30,
            "echeances_obligations": {"paies": "2026-10-09", "das": "2026-10-15", "dettes": "2026-10-31"},
        },
    }
    Path(base, "department.yaml").write_text(yaml.safe_dump({"configuration": configuration}), encoding="utf-8")
    baseline = _call("m5_prevoir_tresorerie", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    assert _call("m5_enregistrer_echeancier_contrat", _contract_args())["resultat"]["accepte"] is True

    page = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})["resultat"]["resultat"]

    for index, (semaine_base, semaine_contrat) in enumerate(zip(baseline["semaines"], page["semaines"], strict=True)):
        supplement = Decimal("1149.75") if index >= 4 else Decimal("0.00")
        assert Decimal(semaine_contrat["solde_fin"]) == Decimal(semaine_base["solde_fin"]) + supplement
        assert semaine_contrat["sorties"] == semaine_base["sorties"]
        entree_supplement = Decimal("1149.75") if index == 4 else Decimal("0.00")
        assert Decimal(semaine_contrat["entrees"]) == Decimal(semaine_base["entrees"]) + entree_supplement, (
            semaine_base, semaine_contrat,
        )
        assert semaine_contrat["lignes"] == semaine_base["lignes"] + (1 if index == 4 else 0)


def test_prix_ht_different_du_devis_est_refuse_sans_ecriture(base):
    _quote()
    arguments = _contract_args()
    arguments["prix_ht"] = "999.00"
    refuse = _call("m5_enregistrer_echeancier_contrat", arguments)

    assert refuse["ok"] is True and refuse["resultat"]["accepte"] is False, refuse
    assert refuse["resultat"]["verdict"]["code"] == "REJ-CONTRAT-HT-INCOHERENT"
    assert len(stockage.maillons("m05-financecore", "echeanciers_contrats_tresorerie")) == 0


@pytest.mark.parametrize(
    ("champ", "valeur", "code"),
    [
        ("prix_ttc", None, None),
        ("echeances", [{"date": "2026-10-31", "montant_ttc": "1149.74"}], "REJ-CONTRAT-TTC-INCOHERENT"),
        ("prix_ttc", 1149.75, None),
        ("prix_ttc", True, None),
        ("prix_ttc", "NaN", "REJ-CONTRAT-MONTANT-INVALIDE"),
        ("prix_ttc", "١١٤٩.٧٥", "REJ-CONTRAT-MONTANT-INVALIDE"),
        ("echeances", [{"date": "２０２６-10-31", "montant_ttc": "1149.75"}], "REJ-CONTRAT-ECHEANCIER-INVALIDE"),
    ],
)
def test_ttc_et_echeances_invalides_sont_refuses_sans_journal(champ, valeur, code, base):
    _quote()
    arguments = _contract_args()
    arguments[champ] = valeur
    refuse = _call("m5_enregistrer_echeancier_contrat", arguments)

    if code is None:
        assert refuse["ok"] is False and refuse["erreur"] == "arguments_invalides", refuse
    else:
        assert refuse["ok"] is True and refuse["resultat"]["accepte"] is False, refuse
        assert refuse["resultat"]["verdict"]["code"] == code
    assert len(stockage.maillons("m05-financecore", "echeanciers_contrats_tresorerie")) == 0


def test_devis_ht_modifie_apres_capture_exclut_le_flux(base):
    _quote()
    assert _call("m5_enregistrer_echeancier_contrat", _contract_args())["resultat"]["accepte"] is True
    with stockage.transaction() as cnx:
        row = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == "m05-financecore",
            REGISTRES.c.registre == "devis_recus",
            REGISTRES.c.rang == 0,
        )).one()
        devis = codec.decoder(row.maillon)
        devis["prix_total"] = Decimal("1200.00")
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == "m05-financecore",
            REGISTRES.c.registre == "devis_recus",
            REGISTRES.c.rang == 0,
        ).values(maillon=codec.encoder(devis)))

    result = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})
    contrats = result["resultat"]["resultat"]["contrats"]
    assert contrats["echeances_rapprochees"] == []
    assert contrats["bloques"] == [{
        "contrat_id": "CTR-58A", "devis_id": "DEVIS-58A", "code": "REJ-CONTRAT-HT-INCOHERENT",
    }]


def test_demande_n4_en_attente_ne_cree_pas_de_flux_actif(base):
    _quote()
    racine_repo = Path(contexte.__file__).resolve().parents[2]
    manifeste_actif = racine_repo / "departments" / "m05-financecore"
    capacites = Capacites({"m05-financecore": lire_manifeste(manifeste_actif)}, stockage.transaction)
    demande = capacites.appeler("m5_enregistrer_echeancier_contrat", _contract_args())

    assert demande["statut"] == "en_attente_approbation"
    assert list(stockage.maillons("m05-financecore", "echeanciers_contrats_tresorerie")) == []
    projection = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    baseline = _call("m5_prevoir_tresorerie", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    assert projection["contrats"]["echeances_rapprochees"] == []
    assert projection["semaines"] == baseline["semaines"]


def test_revoquer_retirer_flux_sans_effacer_historique(base):
    _quote()
    enregistrement = _call("m5_enregistrer_echeancier_contrat", _contract_args())
    assert enregistrement["resultat"]["accepte"] is True
    maillon = enregistrement["resultat"]["resultat"]
    retire = _call("m5_revoquer_echeancier_contrat", {
        "contrat_id": "CTR-58A", "devis_id": "DEVIS-58A", "revision_attendue": maillon["revision"],
        "ligne_id_attendue": maillon["ligne_id"], "motif": "Révocation fictive N4",
    })
    assert retire["resultat"]["accepte"] is True, retire
    historique = stockage.maillons("m05-financecore", "echeanciers_contrats_tresorerie")
    assert len(historique) == 2
    assert historique[-1]["type_entree"] == "echeancier_contrat_revoque"

    projection = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    baseline = _call("m5_prevoir_tresorerie", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    assert projection["contrats"]["echeances_rapprochees"] == []
    assert projection["semaines"] == baseline["semaines"]


def test_facture_payee_bloque_echeancier_sans_creer_encaissement(base):
    _quote()
    ttc = _facture_envoyee(payee=True)
    arguments = _contract_args()
    arguments["prix_ttc"] = format(ttc, ".2f")
    arguments["echeances"][0]["montant_ttc"] = format(ttc, ".2f")
    enregistrement = _call("m5_enregistrer_echeancier_contrat", arguments)
    assert enregistrement["resultat"]["accepte"] is True
    mouvements_avant = stockage.maillons("m05-financecore", "principal")

    projection = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    baseline = _call("m5_prevoir_tresorerie", {"aujourd_hui": TODAY})["resultat"]["resultat"]
    assert projection["contrats"]["echeances_rapprochees"] == []
    assert projection["contrats"]["bloques"][0]["code"] == "REJ-CONTRAT-FACTURE-EXISTANTE"
    assert projection["semaines"] == baseline["semaines"]
    assert list(stockage.maillons("m05-financecore", "principal")) == list(mouvements_avant)


def test_role_sans_acces_est_refuse_avant_lecture_financiere(base):
    with (
        patch.object(
            m5_outils, "_configuration_manifeste", side_effect=AssertionError("configuration prématurée")
        ) as config,
        patch.object(m5_outils, "_lectures_finance", side_effect=AssertionError("lecture prématurée")) as lectures,
        patch.object(stockage, "maillons", side_effect=AssertionError("registre lu prématurément")) as maillons,
    ):
        resultat = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY}, EMPLOYEE)

    assert resultat["ok"] is True and resultat["resultat"]["accepte"] is False, resultat
    assert resultat["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    config.assert_not_called()
    lectures.assert_not_called()
    maillons.assert_not_called()


@pytest.mark.parametrize(
    "cas",
    ["admin_appareil", "admin_console", "owner_appareil", "sans_identite", "agent", "inactive", "role_perdu"],
)
def test_prevision_contrats_exige_owner_console_avant_toute_lecture(base, cas):
    appelant = {
        "admin_appareil": ADMIN,
        "admin_console": ADMIN_CONSOLE,
        "owner_appareil": OWNER_DEVICE,
        "sans_identite": None,
        "agent": None,
        "inactive": OWNER,
        "role_perdu": OWNER,
    }[cas]
    if cas == "inactive":
        with stockage.transaction() as cnx:
            identite.activer(cnx, "nathan.fictif", False)
    elif cas == "role_perdu":
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, "nathan.fictif", "nathan_owner")

    with (
        patch.object(
            m5_outils, "_configuration_manifeste", side_effect=AssertionError("configuration prématurée")
        ) as config,
        patch.object(m5_outils, "_lectures_finance", side_effect=AssertionError("lecture prématurée")) as lectures,
        patch.object(stockage, "maillons", side_effect=AssertionError("registre lu prématurément")) as maillons,
    ):
        resultat = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY}, appelant)

    assert resultat["ok"] is True and resultat["resultat"]["accepte"] is False, (cas, resultat)
    code_attendu = (
        "REJ-CONTRAT-ACCES-REFUSE"
        if cas in {"admin_appareil", "admin_console", "sans_identite", "agent"}
        else "REJ-IDENTITE-APPAREIL-INVALIDE"
    )
    assert resultat["resultat"]["verdict"]["code"] == code_attendu, (cas, resultat)
    config.assert_not_called()
    lectures.assert_not_called()
    maillons.assert_not_called()


@pytest.mark.parametrize("devis_id", [["corrompu"], {"corrompu": True}])
def test_devis_id_non_hashable_donne_un_refus_structure(base, devis_id):
    _quote()
    with stockage.transaction() as cnx:
        row = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == "m05-financecore",
            REGISTRES.c.registre == "devis_recus",
            REGISTRES.c.rang == 0,
        )).one()
        devis = codec.decoder(row.maillon)
        devis["devis_id"] = devis_id
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == "m05-financecore",
            REGISTRES.c.registre == "devis_recus",
            REGISTRES.c.rang == 0,
        ).values(maillon=codec.encoder(devis)))

    resultat = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})
    assert resultat["ok"] is True and resultat["resultat"]["accepte"] is False, resultat
    assert resultat["resultat"]["verdict"]["code"] == "REJ-CONTRAT-DEVIS-INVALIDE"


def test_aucun_acces_appareil_ouvert_par_le_catalogue(base):
    outils = {outil.nom: outil for outil in m5_outils.outils()}
    assert outils["m5_enregistrer_echeancier_contrat"].roles_appareil == frozenset()
    assert outils["m5_revoquer_echeancier_contrat"].roles_appareil == frozenset()
    assert outils["m5_prevoir_tresorerie_contrats"].roles_appareil == frozenset()


def test_chaine_echeancier_alteree_est_refusee_avant_projection(base):
    _quote()
    assert _call("m5_enregistrer_echeancier_contrat", _contract_args())["resultat"]["accepte"] is True
    with stockage.transaction() as cnx:
        row = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == "m05-financecore",
            REGISTRES.c.registre == "echeanciers_contrats_tresorerie",
            REGISTRES.c.rang == 0,
        )).one()
        maillon = codec.decoder(row.maillon)
        maillon["source_humaine"] = "source modifiée sans rehash"
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == "m05-financecore",
            REGISTRES.c.registre == "echeanciers_contrats_tresorerie",
            REGISTRES.c.rang == 0,
        ).values(maillon=codec.encoder(maillon)))

    with patch.object(m5_outils.prevision, "assembler", side_effect=AssertionError("projection prématurée")):
        resultat = _call("m5_prevoir_tresorerie_contrats", {"aujourd_hui": TODAY})

    assert resultat["ok"] is True and resultat["resultat"]["accepte"] is False, resultat
    assert resultat["resultat"]["verdict"]["code"] == "REJ-CONTRAT-CHAINE-INVALIDE"
