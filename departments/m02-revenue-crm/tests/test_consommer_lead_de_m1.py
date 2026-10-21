"""M2 consomme `m1.lead_qualifie` (ADR-0009 §3, PLAN T2.1-b) : le lead qu'un canal du core a fait qualifier par M1
arrive dans M2 par le bus, sans greffe.

Utilise le VRAI bus (`evenements.repartir`, manifestes réels de `departments/`), une base SQLite temporaire migrée et
le profil d'entreprise de l'instance de test (services du catalogue). Les leads sont des charges fictives : le trajet
complet depuis un SMS (M1 réel, `Capacites`, approbations) est prouvé dans `tests/test_canal_sms_bout_en_bout.py` et
`tests/test_canal_conversation.py`. Ici, ce que M2 fait de l'événement : ingérer une fois, réessayer puis mettre en
quarantaine un refus, ne jamais accepter en silence.
"""

from __future__ import annotations

import datetime as dt

import pytest
from m2_revenue_crm import clients, ingestion, outils, statuts
from sqlalchemy import func, select

from opsys import evenements, stockage, taxonomie
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_SORTANTS

RECU_LE = "2026-09-29T09:15:00-04:00"
NUMERO = "+15145550142"


def _lead(lead_id: str = "lead-m1-0001", **surcharges) -> dict:
    lead = {
        "schema_version": 2,
        "lead_id": lead_id,
        "conversation_id": "sms-conversation-fictive",
        "contact": {"telephone": NUMERO},
        "service": "gouttieres",
        "ville": "Laval",
        "urgence_declaree": False,
        "canal": "texte",
        "source": "sms",
    }
    lead.update(surcharges)
    return lead


def _charge(lead: dict, horodatage: str = RECU_LE) -> dict:
    return {"lead": lead, "horodatage": horodatage, "signal_id": "sms:SMfictif0001"}


def _publier(lead: dict, evenement_id: str | None = None, horodatage: str = RECU_LE) -> None:
    evenements.publier("m1.lead_qualifie", "m01-front-office", _charge(lead, horodatage), evenement_id=evenement_id)


def _deps_bus():
    """Seul M2 reçoit `m1.lead_qualifie` : les comptes de `repartir()` sont ceux de M2."""
    return {"m02-revenue-crm": charger_departements()["m02-revenue-crm"]}


def _repartir_jusqu_au_bout(deps, depart: dt.datetime, tours: int = 6) -> dict[str, int]:
    """Livre à intervalles de 100 s (le plus long délai de réessai est de 16 s) : cinq échecs ferment un événement."""
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(tours):
        resume = evenements.repartir(deps, maintenant=(depart + dt.timedelta(seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    return total


def _maillons() -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons("m02-revenue-crm", "principal"))


def _leads_ingeres() -> list[dict]:
    return [m for m in _maillons() if m["type_entree"] == ingestion.TYPE_ENTREE]


def _nb_evenements(type_evenement: str) -> int:
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)).scalar_one()


@pytest.fixture
def base_durable(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        outils.reinitialiser_registre()
        stockage.liberer()


class TestManifeste:
    def test_la_fonction_est_branchee_au_vrai_manifeste_sans_greffe(self):
        dep = charger_departements()["m02-revenue-crm"]
        assert "m1.lead_qualifie" in dep.evenements_consomme
        assert dep.charger_consommateurs()["m1.lead_qualifie"].__name__ == "_recevoir_lead_qualifie"
        assert evenements.verifier_coherence(charger_departements()) == []


class TestNominal:
    def test_le_lead_publie_par_m1_est_ingere_avec_son_horodatage_et_son_client(self, base_durable):
        lead = _lead(urgence_declaree=True)
        _publier(lead)

        resume = evenements.repartir(_deps_bus(), maintenant="2026-09-29T09:20:00-04:00")
        assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}

        (ingere,) = _leads_ingeres()
        assert ingere["contrat"] == lead, "le contrat est copié tel que M1 l'a émis"
        assert ingere["horodatage"] == RECU_LE, "l'heure de réception de la plateforme, jamais une horloge de M2"
        assert statuts.statut_courant(outils._obtenir_registre(), lead["lead_id"]) == "nouveau"
        with stockage.transaction():
            client_id = clients.client_de_lead(outils._obtenir_registre(), lead["lead_id"])
            charge_client = evenements.charge_publiee("m2.client_associe", f"m2-client-associe-{lead['lead_id']}")
        assert client_id and charge_client["client_id"] == client_id
        assert evenements.etat()["quarantaine"] == []


class TestIdempotence:
    def test_le_meme_evenement_rejoue_ne_cree_ni_second_lead_ni_seconde_opportunite(self, base_durable):
        _publier(_lead())
        evenements.repartir(_deps_bus(), maintenant="2026-09-29T09:20:00-04:00")
        avant = _maillons()

        resume = evenements.repartir(_deps_bus(), maintenant="2026-09-29T10:00:00-04:00")
        assert resume == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
        assert _maillons() == avant

    def test_le_meme_lead_sous_un_autre_evenement_id_est_reconnu_sans_rien_ecrire_ni_quarantaine(self, base_durable):
        lead = _lead()
        _publier(lead)
        evenements.repartir(_deps_bus(), maintenant="2026-09-29T09:20:00-04:00")
        avant = _maillons()
        evenements_client_avant = _nb_evenements("m2.client_associe")

        _publier(lead, evenement_id="rejeu-du-producteur-sous-un-autre-id")
        resume = evenements.repartir(_deps_bus(), maintenant="2026-09-29T09:30:00-04:00")
        assert resume["traites"] == 1 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

        assert _maillons() == avant, "ni lead, ni lien client, ni doublon signalé de plus"
        assert len(_leads_ingeres()) == 1
        with stockage.transaction():
            assert clients.opportunites_du_client(
                outils._obtenir_registre(), clients.client_de_lead(outils._obtenir_registre(), lead["lead_id"])
            ) == [lead["lead_id"]]
        assert _nb_evenements("m2.client_associe") == evenements_client_avant
        assert evenements.etat()["quarantaine"] == []

    def test_l_appel_direct_du_consommateur_deux_fois_rend_deja_applique(self, base_durable):
        charge = _charge(_lead())
        with stockage.transaction():
            premier = outils._recevoir_lead_qualifie(charge)
            second = outils._recevoir_lead_qualifie(charge)
        assert premier["accepte"] is True and "deja_applique" not in premier
        assert second == {
            "accepte": True, "deja_applique": True, "lead_id": charge["lead"]["lead_id"],
            "client_id": premier["client_id"],
        }
        assert len(_leads_ingeres()) == 1

    def test_deux_leads_du_meme_client_sont_deux_opportunites_d_un_seul_client(self, base_durable):
        premier, second = _lead("lead-m1-A"), _lead("lead-m1-B", service="soffite_fascia")
        _publier(premier)
        _publier(second)
        assert _repartir_jusqu_au_bout(_deps_bus(), dt.datetime(2026, 9, 29, 13, 30, tzinfo=dt.UTC), 1)["traites"] == 2
        with stockage.transaction():
            reg = outils._obtenir_registre()
            client = clients.client_de_lead(reg, "lead-m1-A")
            assert clients.client_de_lead(reg, "lead-m1-B") == client
            assert sorted(clients.opportunites_du_client(reg, client)) == ["lead-m1-A", "lead-m1-B"]


class TestRefus:
    """Un lead que M2 refuse lève : le répartiteur réessaie (5 fois), puis met l'événement en quarantaine."""

    def test_un_service_retire_du_profil_depuis_la_qualification_va_en_quarantaine_sans_ecriture(self, base_durable):
        _publier(_lead())
        taxonomie.enregistrer_services(["reparation"])  # « gouttieres » n'est plus déclaré au moment de la livraison

        resume = _repartir_jusqu_au_bout(_deps_bus(), dt.datetime(2026, 9, 29, 13, 30, tzinfo=dt.UTC))
        assert resume["quarantaines"] == 1 and resume["traites"] == 0, resume
        assert _maillons() == [], "un lead refusé n'écrit rien"
        (ligne,) = [q for q in evenements.etat()["quarantaine"] if q["consommateur"] == "m02-revenue-crm"]
        assert ligne["type_evenement"] == "m1.lead_qualifie" and ligne["tentatives"] == 5
        assert "LeadRefuse" in ligne["derniere_erreur"] and "REJ-SERVICE-INCONNU" in ligne["derniere_erreur"]

    def test_un_refus_d_ingestion_leve_avec_le_code_et_le_detail_du_verdict(self, base_durable):
        lead = _lead()
        del lead["ville"]
        with (
            pytest.raises(outils.LeadRefuse, match="REJ-CHAMP-MANQUANT|REJ-CHAMP-VIDE|REJ-ENUM-INVALIDE") as exc,
            stockage.transaction(),
        ):
            outils._recevoir_lead_qualifie(_charge(lead))
        assert lead["lead_id"] in str(exc.value) and "ville" in str(exc.value)
        assert _maillons() == []

    def test_un_lead_id_connu_avec_un_autre_contenu_n_est_jamais_accepte_en_silence(self, base_durable):
        _publier(_lead())
        evenements.repartir(_deps_bus(), maintenant="2026-09-29T09:20:00-04:00")
        avant = _maillons()

        _publier(_lead(ville="Québec"), evenement_id="meme-lead-id-autre-ville")
        resume = _repartir_jusqu_au_bout(_deps_bus(), dt.datetime(2026, 9, 29, 13, 30, tzinfo=dt.UTC))
        assert resume["quarantaines"] == 1 and resume["traites"] == 0, resume
        assert _maillons() == avant
        (ligne,) = [q for q in evenements.etat()["quarantaine"] if q["consommateur"] == "m02-revenue-crm"]
        assert "LeadRefuse" in ligne["derniere_erreur"] and "contenu différent" in ligne["derniere_erreur"]
