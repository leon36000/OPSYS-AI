"""Planification autonome : les tours des départements (M8, M5, M10) branchés au planificateur durable.

Cycle complet sur les VRAIS départements et la VRAIE base : inactif (défaut) -> ombre (constate sans agir) -> actif
(agit, rejouable) -> expiration -> arrêt. Aucun transport : ces tours n'en ont pas. Données fictives."""

from __future__ import annotations

import planif_qa as pq
import pytest
from sqlalchemy import func, select

from opsys import stockage
from opsys.connecteurs_planification import bail, etat, journal, planificateur
from opsys.connecteurs_planification import exec_departements as ed
from opsys.stockage.schema import PLANIFICATEUR_JOURNAL, REGISTRES

FICTIF = True
DEPS = ("m05-financecore", "m08-analytics", "m10-memoire")


@pytest.fixture
def p(tmp_path, monkeypatch):
    mon = pq.monter(tmp_path, monkeypatch, DEPS)
    yield mon
    pq.demonter()


def _lignes_registre(departement: str) -> int:
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(REGISTRES).where(
            REGISTRES.c.departement == departement)).scalar_one()


def _constructions() -> int:
    with stockage.transaction() as cnx:
        return cnx.exec_driver_sql("SELECT COUNT(*) FROM m8_ent_constructions").scalar_one()


def _journal(executeur: str) -> list[dict]:
    with stockage.transaction() as cnx:
        return journal.lire(cnx, executeur)


# -- rien par défaut -----------------------------------------------------------------------------------------------
def test_rien_ne_tourne_par_defaut_et_aucune_ecriture_metier(p):
    avant = (_constructions(), _lignes_registre("m05-financecore"), _lignes_registre("m10-memoire"))
    resume = p.tour()
    assert {v["statut"] for v in resume["executeurs"].values()} == {"inactif"}
    assert (_constructions(), _lignes_registre("m05-financecore"), _lignes_registre("m10-memoire")) == avant
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(PLANIFICATEUR_JOURNAL)).scalar_one() == 0
        assert {v["mode"] for v in etat.vue(cnx)} == {"inactif"}


# -- cycle complet M8 : inactif -> ombre -> actif -> expiration -> arrêt
# ------------------------------------------------
def test_cycle_complet_m8_ombre_constate_sans_agir_actif_agit_et_se_rejoue(p):
    p.activer("m8.entrepot", "ombre")
    resume = p.tour()
    assert resume["executeurs"]["m8.entrepot"]["statut"] == "ombre"
    assert resume["executeurs"]["m8.entrepot"]["aurait"] == 3
    assert _constructions() == 0  # l'ombre ne reconstruit rien
    assert "aurait" in {j["evenement"] for j in _journal("m8.entrepot")}

    p.activer("m8.entrepot", "actif")
    resume = p.tour()
    assert resume["executeurs"]["m8.entrepot"]["statut"] == "ok"
    assert resume["executeurs"]["m8.entrepot"]["etapes"] == 3 and _constructions() == 1

    resume = p.tour()  # rejeu : l'entrepôt est inchangé, rien de plus n'est écrit
    assert resume["executeurs"]["m8.entrepot"]["statut"] == "ok" and _constructions() == 1
    assert resume["executeurs"]["m8.entrepot"]["inchanges"] >= 1

    p.horloge.avancer(91 * 86400)  # l'activation expire (90 jours) : le tour ne fait plus rien
    avant = _constructions()
    assert p.tour(avance=1)["executeurs"]["m8.entrepot"] == {"statut": "inactif"}
    assert _constructions() == avant

    p.activer("m8.entrepot", "inactif", motif="arrêt demandé")
    assert p.tour()["executeurs"]["m8.entrepot"] == {"statut": "inactif"}


def test_le_journal_ne_garde_que_des_identifiants_et_des_compteurs(p):
    p.activer("m8.entrepot")
    p.tour()
    texte = repr(_journal("m8.entrepot"))
    assert "maintenant" not in texte and "construction_id" not in texte


def test_le_coupe_circuit_arrete_les_tours_des_departements(p, monkeypatch):
    p.activer("m8.entrepot")
    monkeypatch.setenv(etat.ENV_PLANIFICATEUR, "0")
    assert p.tour() == {"raison": "desactive", "executeurs": {}}
    assert _constructions() == 0


def test_l_arret_propre_interrompt_le_tour(p):
    p.activer("m8.entrepot")
    planificateur.demander_arret()
    try:
        resume = p.tour()
    finally:
        planificateur.reinitialiser_arret()
    assert resume["raison"] == "arret" and _constructions() == 0


def test_un_departement_absent_est_dit_pas_ignore(p):
    p.departements.pop("m08-analytics")
    p.activer("m8.entrepot")
    resume = p.tour()
    assert resume["executeurs"]["m8.entrepot"]["statut"] == "refus"
    assert resume["executeurs"]["m8.entrepot"]["code"] == "REJ-PLAN-DEPARTEMENT-ABSENT"


# -- M5 : brouillons et préclôture, jamais un paiement, un envoi ni une clôture
# -----------------------------------------
def test_m5_cycle_prepare_sans_rien_cloturer_et_dit_ce_qui_reste_a_declarer(p):
    p.activer("m5.cycle")
    resume = p.tour()
    r = resume["executeurs"]["m5.cycle"]
    assert r["statut"] == "ok" and r["etapes"] >= 3
    assert r["code"] == "REJ-OPS-CONFIGURATION-A-DECLARER"  # politique de relance non déclarée : dit, pas inventé
    taille = _lignes_registre("m05-financecore")
    assert p.tour()["executeurs"]["m5.cycle"]["statut"] == "ok"
    assert _lignes_registre("m05-financecore") == taille  # rejouer ne crée rien de plus


def test_la_periode_preclose_est_le_mois_qui_vient_de_se_terminer():
    assert ed.CycleM5.periode_precedente("2026-11-01") == "2026-10"
    assert ed.CycleM5.periode_precedente("2027-01-15") == "2026-12"
    assert ed.CycleM5.periode_precedente("2026-03-31") == "2026-02"


# -- M10 : Mnémo ----------------------------------------------------------------------------------------------------
def test_m10_mnemo_propose_sans_rien_confirmer_et_se_rejoue(p):
    p.activer("m10.mnemo")
    r = p.tour()["executeurs"]["m10.mnemo"]
    assert r["statut"] == "ok" and r["etapes"] == 4 and r["pages"] >= 1
    taille = _lignes_registre("m10-memoire")
    assert p.tour()["executeurs"]["m10.mnemo"]["statut"] == "ok"
    assert _lignes_registre("m10-memoire") == taille


# -- un seul exécuteur à la fois (bail) -------------------------------------------------------------------------------
def test_un_tour_dont_le_bail_est_pris_ne_travaille_pas(p):
    p.activer("m8.entrepot")
    pris = bail.acquerir("m8.entrepot:instance", "autre-processus", 600, horloge=p.horloge)
    assert pris is not None
    resume = p.tour()
    assert resume["executeurs"]["m8.entrepot"]["ignores"] == 1 and _constructions() == 0
    bail.liberer(pris)
    assert p.tour()["executeurs"]["m8.entrepot"]["statut"] == "ok" and _constructions() == 1


# -- aucun outil N3+ n'est jamais appelé -----------------------------------------------------------------------------
class _FauxOutil:
    def __init__(self, niveau, frontiere=False):
        self.niveau_effectif = niveau
        self.frontiere_humaine = frontiere
        self.appels = 0
        self.parametres = {"type": "object", "properties": {}}
        self.nom = "m8_construire_entrepot"

    def fonction(self, **_):
        self.appels += 1
        return {}


@pytest.mark.parametrize("niveau", ["N3", "N4", "N5"])
def test_un_outil_de_niveau_n3_ou_plus_n_est_jamais_appele(niveau):
    from opsys.outils import Niveau

    faux = _FauxOutil(Niveau(niveau))

    class Ctx:
        def outils(self):
            return {"m8_construire_entrepot": faux}

    with pytest.raises(planificateur.NiveauInterdit) as exc:
        ed.appeler_outil(Ctx(), "m8_construire_entrepot", {}, autorises=frozenset({"m8_construire_entrepot"}))
    assert exc.value.code == "REJ-PLAN-NIVEAU-INTERDIT" and faux.appels == 0


def test_un_outil_hors_de_la_liste_fermee_n_est_pas_appele():
    from opsys.outils import Niveau

    faux = _FauxOutil(Niveau.N2)

    class Ctx:
        def outils(self):
            return {"m8_construire_entrepot": faux}

    with pytest.raises(planificateur.NiveauInterdit) as exc:
        ed.appeler_outil(Ctx(), "m8_construire_entrepot", {}, autorises=frozenset({"autre_outil"}))
    assert exc.value.code == "REJ-PLAN-OUTIL-HORS-LISTE" and faux.appels == 0


def test_un_outil_marque_frontiere_humaine_est_refuse_meme_declare_n2():
    from opsys.outils import Niveau

    faux = _FauxOutil(Niveau.N2, frontiere=True)

    class Ctx:
        def outils(self):
            return {"m8_construire_entrepot": faux}

    with pytest.raises(planificateur.NiveauInterdit):
        ed.appeler_outil(Ctx(), "m8_construire_entrepot", {}, autorises=frozenset({"m8_construire_entrepot"}))
    assert faux.appels == 0


def test_chaque_outil_appele_par_les_executeurs_de_departement_est_de_niveau_automatique(p):
    from opsys.connecteurs_planification.planificateur import Contexte

    ctx = Contexte(p.ports, None, "essai", p.departements, p.horloge())
    for executeur in (ed.EntrepotM8(), ed.CycleM5(), ed.Mnemo()):
        executeur._verifier(ctx)  # lève NiveauInterdit si un outil listé était N3+
        assert executeur.outils
