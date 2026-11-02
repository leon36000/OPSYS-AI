"""Numérotation des factures de jalon sous concurrence RÉELLE sur PostgreSQL 17 (READ COMMITTED), données fictives.

Deux émissions approuvées (N4) de deux factures différentes se disputent le même numéro : l'écrivain A a lu la suite et
calculé le numéro 1000, B émet et valide d'abord (1000), puis A reprend et perd la course au rang (clé primaire du
registre). `relire_si_conflit` rejoue le corps d'A, qui relit la suite et reçoit 1001 : deux numéros distincts, sans
trou, et aucune erreur. Aucun envoi externe ni paiement réel. Opt-in comme les autres épreuves PostgreSQL (job
`frontiere-postgresql`).
"""

import os
import threading
from pathlib import Path

import pytest
import yaml
from m5_financecore import facturation
from m5_financecore import outils as m5_outils
from m5_financecore import registre as registre_m5
from memoire.doubles import postgres_ephemere

from opsys import approbations, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.maillons import MaillonsDurables

D = "m05-financecore"
H = "2026-11-02T10:00:00-05:00"
CONFIG = {
    "facturation": {
        "numerotation": {"prefixe": "F-", "premier_numero": 1000, "largeur": 5},
        "conditions_paiement": {"delai_jours": 30},
    }
}
JALONS = [
    {"libelle": "Acompte", "declencheur": "acceptation", "pourcentage": "50", "delai_paiement_jours": 0},
    {"libelle": "Mi-chantier", "declencheur": "chantier", "pourcentage": "30"},
    {"libelle": "Solde", "declencheur": "fin_travaux", "pourcentage": "20"},
]


def _decider(dep, demande):
    disponibles = outils_executables({D: dep}, stockage.transaction)
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, demande, True, "finance-fictif", disponibles, {D: dep})


def _demander(dep, nom, arguments):
    reponse = Capacites({D: dep}, stockage.transaction).appeler(nom, arguments)
    assert reponse["statut"] == "en_attente_approbation"
    return reponse["demande_id"]


def _etat(facture_id):
    with stockage.transaction():
        return facturation._etat_facture(m5_outils._registre_factures(None), facture_id)


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
def test_deux_emissions_qui_se_disputent_le_meme_numero_obtiennent_deux_numeros_sans_trou(monkeypatch, tmp_path):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": CONFIG}), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        m5_outils.utiliser_stockage_durable()
        dep = charger_departements(Path(__file__).resolve().parents[2] / "departments")[D]
        with stockage.transaction() as cnx:
            identite.creer_personne(
                cnx, "finance-fictif", "Finance fictive", "mot-de-passe-fixture-fictif", ["finance"]
            )
        charge = {
            "devis_id": "D-1",
            "lead_id": "lead-1",
            "chantier_id": None,
            "prix_total": "1000.00",
            "lignes": [
                {
                    "reference_ligne": "D-1-L0",
                    "description": "Travaux (fictif)",
                    "quantite": "1",
                    "unite": "forfait",
                    "prix_unitaire": "1000.00",
                    "prix_ligne": "1000.00",
                    "reference_besoin_materiau": None,
                }
            ],
            "cout_total": "700.00",
            "taux_marge": "0.30",
            "horodatage_acceptation": "2026-10-20T09:00:00-04:00",
        }
        with stockage.transaction():
            m5_outils._recevoir_devis_accepte(charge)
        plan = _decider(
            dep,
            _demander(
                dep,
                "m5_etablir_plan_facturation",
                {"devis_id": "D-1", "jalons": JALONS, "chantier_id": "CH-1", "horodatage": H},
            ),
        )
        assert plan["statut"] == "executee", plan
        plan_id = plan["reponse"]["resultat"]["resultat"]["plan_id"]
        creer = next(o for o in dep.charger_outils() if o.nom == "m5_creer_facture_jalon")
        for rang in (1, 2):
            reponse = executer_atomique(creer, {"devis_id": "D-1", "rang": rang, "horodatage": H})
            assert reponse["resultat"]["accepte"], reponse
        factures = [f"fac-{plan_id}-J1", f"fac-{plan_id}-J2"]
        demandes = [_demander(dep, "m5_envoyer_facture", {"facture_id": f, "horodatage": H}) for f in factures]

        calcule, reprendre = threading.Event(), threading.Event()
        observations: dict = {}
        original = MaillonsDurables.append

        def pauser(self, maillon, *, rang_attendu=None):
            premiere = "pid_a" not in observations and threading.current_thread() is a
            if premiere and (self.departement, self.registre) == (D, "numerotation_factures"):
                cnx = stockage.connexion_courante()
                assert cnx.get_isolation_level() == "READ COMMITTED"
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '20s'")
                observations["pid_a"] = cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                observations["rang_a"] = rang_attendu
                calcule.set()
                assert reprendre.wait(15), "coordination fictive non libérée"
            return original(self, maillon, rang_attendu=rang_attendu)

        def approuver_a():
            try:
                observations["decision_a"] = _decider(dep, demandes[0])
            except BaseException as exc:  # noqa: BLE001
                observations["exception"] = f"{type(exc).__name__}: {exc}"
                calcule.set()

        a = threading.Thread(target=approuver_a, name="m5-numero-a-fictif")
        monkeypatch.setattr(MaillonsDurables, "append", pauser)
        try:
            a.start()
            assert calcule.wait(20) and "exception" not in observations, observations
            assert observations["rang_a"] == 0  # A a lu une suite vide et vise le premier numéro
            decision_b = _decider(dep, demandes[1])  # B, autre connexion, prend 1000 et valide
            assert decision_b["statut"] == "executee", decision_b
            reprendre.set()
            a.join(30)
            assert not a.is_alive() and "exception" not in observations, observations
            assert observations["decision_a"]["statut"] == "executee", observations["decision_a"]
        finally:
            reprendre.set()
            if a.ident is not None:
                a.join(10)
            assert not a.is_alive(), "écrivain fictif non arrêté"
            monkeypatch.setattr(MaillonsDurables, "append", original)
        stockage.liberer()
        numeros = {f: _etat(f)["numero_facture"] for f in factures}
        assert numeros[factures[1]] == "F-01000" and numeros[factures[0]] == "F-01001", numeros  # B d'abord, A rejoué
        with stockage.transaction():
            suite = list(stockage.maillons(D, "numerotation_factures"))
        assert [m["sequence"] for m in suite] == [1000, 1001]
        assert registre_m5.Registre(maillons=suite).valider_chaine() == (True, "")
        stockage.liberer()
