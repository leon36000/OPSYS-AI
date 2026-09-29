"""M2 consomme `m3.devis_envoye` (ADR-0009 §3, PLAN T4.9 ; DEFINITION-PRODUIT §6 « M2 suit la soumission (relances) »,
§7 M2.7) : l'envoi approuvé d'un devis fait partir le délai d'une relance, à l'instant que M3 publie, jamais d'une date
supposée.

Utilise le VRAI bus (`evenements.repartir`, manifeste réel de M2), une base SQLite temporaire migrée et le registre de
M2 sur le stockage durable. Seul M2 reçoit les événements de ces tests. Les charges sont conformes au catalogue
(`m3.devis_envoye.json`) et publiées comme M3 les publie (`m3-devis-envoye-<devis_id>`). Ce qui est prouvé : le fait est
rangé sans montant ; le rejeu, ou le même devis sous un autre identifiant d'événement, n'écrit rien de plus ; un lead
inconnu ou une heure illisible finit en quarantaine, sans écriture ; un lead perdu garde le fait sans relance ; et le
constat de M3 ne l'emporte jamais sur l'envoi (`quote_stale` part de l'instant de l'envoi). Données fictives.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from m2_revenue_crm import clients, liste_leads, outils, relances, segments, statuts
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS

FICTIF = True

M2 = "m02-revenue-crm"
ENVOYE_LE = "2026-09-10T09:00:00-04:00"
DEBUT = dt.datetime(2026, 9, 29, 16, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
HORODATAGE = "2026-09-29T12:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}


def _contrat(lead_id: str) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }


def _charge(devis_id: str, lead_id: str, envoye_le: str = ENVOYE_LE, chantier_id=None) -> dict:
    """La charge que M3 publie (`devis_durable.charge_evenement_devis_envoye`) : quatre clés, aucun montant."""
    return {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": chantier_id, "horodatage_envoi": envoye_le}


def _publier(devis_id: str, lead_id: str, evenement_id: str | None = None, **plus) -> str:
    identifiant = evenement_id or f"m3-devis-envoye-{devis_id}"
    evenements.publier(
        "m3.devis_envoye", "m03-estimation", _charge(devis_id, lead_id, **plus), evenement_id=identifiant)
    return identifiant


def _amener_a(lead_id: str, statut: str) -> None:
    outils.ingerer_lead(_contrat(lead_id), "2026-09-01T09:00:00-04:00")
    if statut == "nouveau":
        return
    if statut == "perdu":
        outils.transitionner_statut(lead_id, "perdu", "2026-09-01T09:05:00-04:00", motif="Client parti (fictif)")
        return
    outils.transitionner_statut(lead_id, "qualifie", "2026-09-01T09:05:00-04:00", owner="vendeur.un",
                                prochaine_action=ACTION)
    if statut == "converti":
        outils.transitionner_statut(lead_id, "converti", "2026-09-01T09:10:00-04:00", reference_devis_m3="DEVIS-1")


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        outils.reinitialiser_registre()
        stockage.liberer()


def _repartir(instant: str = "2026-09-29T16:00:00-04:00") -> dict[str, int]:
    return evenements.repartir({M2: charger_departements()[M2]}, maintenant=instant)


def _repartir_jusqu_au_bout(tours: int = 6) -> dict[str, int]:
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(tours):
        resume = _repartir((DEBUT + dt.timedelta(seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    return total


def _fait_recus() -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(M2, "devis_envoyes_recus"))


def _recu(evenement_id: str) -> dict:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == M2)
        )).mappings().first()
    assert ligne is not None, f"aucun reçu pour {evenement_id}"
    return dict(ligne)


def _resultat(evenement_id: str) -> dict:
    return codec.decoder(_recu(evenement_id)["resultat"])


def _ecritures() -> dict:
    """Ce qu'un refus ou un rejeu ne doit jamais changer : le registre principal de M2 et le registre des faits."""
    with stockage.transaction():
        return {
            "principal": len(stockage.maillons(M2, "principal")),
            "envoyes": len(stockage.maillons(M2, "devis_envoyes_recus")),
            "sans_reponse": len(stockage.maillons(M2, "relances_devis_recues")),
        }


class TestManifeste:
    def test_la_fonction_est_branchee_au_vrai_manifeste(self):
        dep = charger_departements()[M2]
        assert "m3.devis_envoye" in dep.evenements_consomme
        assert dep.charger_consommateurs()["m3.devis_envoye"].__name__ == "_recevoir_devis_envoye"
        assert evenements.verifier_coherence(charger_departements()) == []

    def test_le_type_est_au_catalogue_et_m3_le_publie(self):
        assert "m3.devis_envoye" in evenements.types_connus()
        assert "m3.devis_envoye" in charger_departements()["m03-estimation"].evenements_publie

    def test_la_charge_de_ces_tests_est_conforme_au_catalogue(self):
        assert erreurs_charge("m3.devis_envoye", _charge("devis-1", "lead-1")) == []
        assert erreurs_charge("m3.devis_envoye", {**_charge("devis-1", "lead-1"), "prix_total": "100.00"}) != []


class TestRangement:
    def test_l_envoi_est_range_a_l_instant_publie_par_m3_sans_montant(self, base_durable):
        _amener_a("lead-1", "qualifie")
        identifiant = _publier("devis-1", "lead-1", chantier_id="chantier-1")

        resume = _repartir()

        assert (resume["traites"], resume["echecs"], resume["quarantaines"]) == (1, 0, 0)
        (fait,) = _fait_recus()
        assert fait == {
            "devis_id": "devis-1", "lead_id": "lead-1", "chantier_id": "chantier-1", "horodatage_envoi": ENVOYE_LE,
            "client_id": clients.client_de_lead(outils._obtenir_registre(), "lead-1"),
        }
        assert fait["client_id"], "le fait est rattaché au client (Client 360)"
        texte = json.dumps(fait)
        for interdit in ("prix", "cout", "marge", "montant", "418-555-0100", "example.test"):
            assert interdit not in texte, interdit
        assert _resultat(identifiant) == {
            "traite": True, "lead_id": "lead-1", "devis_id": "devis-1", "client_id": fait["client_id"],
            "horodatage_envoi": ENVOYE_LE,
        }

    def test_le_fait_ne_change_ni_le_statut_ni_l_historique_du_lead(self, base_durable):
        _amener_a("lead-1", "qualifie")
        avant = _ecritures()["principal"]
        _publier("devis-1", "lead-1")
        _repartir()
        assert _ecritures()["principal"] == avant, "aucune transition, aucune interaction : la relance est proposée"
        assert statuts.statut_courant(outils._obtenir_registre(), "lead-1") == "qualifie"

    def test_un_lead_sans_client_associe_est_range_avec_client_nul(self, base_durable, monkeypatch):
        _amener_a("lead-1", "qualifie")
        monkeypatch.setattr(clients, "client_de_lead", lambda registre, lead_id: None)
        _publier("devis-1", "lead-1")
        _repartir()
        assert _fait_recus()[0]["client_id"] is None

    @pytest.mark.parametrize("statut", ["nouveau", "qualifie", "converti"])
    def test_un_lead_ouvert_ou_converti_garde_le_fait_sans_marque_de_cloture(self, base_durable, statut):
        _amener_a("lead-1", statut)
        _publier("devis-1", "lead-1")
        assert _repartir()["traites"] == 1
        (fait,) = _fait_recus()
        assert "ignore" not in fait

    def test_deux_devis_du_meme_lead_sont_deux_faits(self, base_durable):
        _amener_a("lead-1", "qualifie")
        _publier("devis-1", "lead-1")
        _publier("devis-2", "lead-1", envoye_le="2026-09-12T09:00:00-04:00")
        assert _repartir()["traites"] == 2
        assert sorted(f["devis_id"] for f in _fait_recus()) == ["devis-1", "devis-2"]

    def test_un_lead_perdu_garde_le_fait_sans_relance_ni_quarantaine(self, base_durable):
        _amener_a("lead-1", "perdu")
        identifiant = _publier("devis-1", "lead-1")

        resume = _repartir()

        assert (resume["traites"], resume["quarantaines"]) == (1, 0)
        (fait,) = _fait_recus()
        assert fait["ignore"] == "lead_clos"
        assert _resultat(identifiant)["motif"] == "lead 'lead-1' au statut 'perdu' : dossier clos, aucune relance"


class TestIdempotence:
    def test_un_evenement_rejoue_n_ecrit_rien_de_plus(self, base_durable):
        _amener_a("lead-1", "qualifie")
        _publier("devis-1", "lead-1")
        _repartir()
        avant = _ecritures()

        _publier("devis-1", "lead-1")  # même identifiant d'événement : un no-op du bus
        assert _repartir()["livres"] == 0

        assert _ecritures() == avant and len(_fait_recus()) == 1

    def test_le_meme_devis_sous_un_autre_identifiant_est_reconnu_par_son_devis_id(self, base_durable):
        _amener_a("lead-1", "qualifie")
        _publier("devis-1", "lead-1")
        _repartir()
        avant = _ecritures()

        autre = _publier("devis-1", "lead-1", evenement_id="m3-devis-envoye-autre-identifiant")
        resume = _repartir()

        assert (resume["traites"], resume["echecs"], resume["quarantaines"]) == (1, 0, 0)
        assert _resultat(autre) == {"traite": True, "lead_id": "lead-1", "devis_id": "devis-1", "deja_applique": True}
        assert _ecritures() == avant

    def test_le_meme_devis_avec_un_autre_lead_ou_une_autre_heure_est_une_incoherence(self, base_durable):
        _amener_a("lead-1", "qualifie")
        _amener_a("lead-2", "qualifie")
        _publier("devis-1", "lead-1")
        _repartir()
        avant = _ecritures()
        _publier("devis-1", "lead-2", evenement_id="autre-lead")
        _publier("devis-1", "lead-1", evenement_id="autre-heure", envoye_le="2026-09-11T09:00:00-04:00")

        total = _repartir_jusqu_au_bout()

        assert total["quarantaines"] == 2 and total["traites"] == 0
        assert _ecritures() == avant, "jamais une seconde entrée, jamais une entrée écrasée"
        assert len(evenements.etat()["quarantaine"]) == 2
        assert _fait_recus()[0]["lead_id"] == "lead-1" and _fait_recus()[0]["horodatage_envoi"] == ENVOYE_LE


class TestRefus:
    def test_un_lead_inconnu_finit_en_quarantaine_sans_ecriture(self, base_durable):
        identifiant = _publier("devis-1", "lead-inconnu")

        total = _repartir_jusqu_au_bout()

        assert (total["traites"], total["quarantaines"]) == (0, 1) and total["echecs"] >= 4
        assert _fait_recus() == [] and _ecritures()["principal"] == 0
        (quarantaine,) = evenements.etat()["quarantaine"]
        assert quarantaine["evenement_id"] == identifiant and "introuvable" in quarantaine["derniere_erreur"]

    def test_l_heure_arrive_apres_le_lead_la_quarantaine_se_rejoue_a_la_republication(self, base_durable):
        _publier("devis-1", "lead-tardif")
        _repartir_jusqu_au_bout()
        assert _fait_recus() == []
        _amener_a("lead-tardif", "qualifie")
        _publier("devis-1", "lead-tardif", evenement_id="m3-devis-envoye-republie")
        assert _repartir()["traites"] == 1 and len(_fait_recus()) == 1

    @pytest.mark.parametrize("heure", ["hier", "2026-09-10", "2026-09-10T09:00:00", "2026-13-40T09:00:00-04:00"])
    def test_une_heure_d_envoi_illisible_est_refusee_et_jamais_rangee(self, base_durable, heure):
        _amener_a("lead-1", "qualifie")
        identifiant = _publier("devis-1", "lead-1", envoye_le=heure)

        total = _repartir_jusqu_au_bout()

        assert (total["traites"], total["quarantaines"]) == (0, 1)
        assert _fait_recus() == []
        (quarantaine,) = evenements.etat()["quarantaine"]
        assert quarantaine["evenement_id"] == identifiant and "aucun délai de relance ne part d'une date supposée" in (
            quarantaine["derniere_erreur"])


class TestDepartDuDelai:
    """L'échéance d'une relance de devis part de l'envoi RÉEL publié par M3, jamais du constat de M3 ni d'une date
    supposée."""

    SEUILS = segments.lire_seuils({"jours_soumission_perimee": 14, "jours_inactivite_dormant": 30})

    def _segments_de(self, lead_id: str, horodatage: str = HORODATAGE):
        page, verdict = liste_leads.lister(
            outils._obtenir_registre().lire(), visibles=None, relances_devis=outils._devis_connus(),
            seuils=self.SEUILS, horodatage=horodatage, budget_caracteres=100_000)
        assert verdict is None, verdict
        return {s["segment"]: s for lead in page["leads"] if lead["lead_id"] == lead_id for s in lead["segments"]}

    def test_quote_stale_part_de_l_instant_de_l_envoi_sans_aucun_constat_de_m3(self, base_durable):
        _amener_a("lead-1", "qualifie")
        _publier("devis-1", "lead-1")
        _repartir()

        segment = self._segments_de("lead-1")["quote_stale"]

        assert segment["donnee"] == {
            "devis_id": "devis-1", "statut_devis": "envoye", "horodatage_devis": ENVOYE_LE, "jours_ecoules": 19,
            "seuil_jours": 14,
        }
        assert outils._devis_sans_reponse_recus() == [], "M3 n'a publié aucun constat : l'envoi suffit"

    def test_avant_le_delai_le_devis_envoye_n_est_pas_perime(self, base_durable):
        _amener_a("lead-1", "qualifie")
        _publier("devis-1", "lead-1")
        _repartir()
        assert "quote_stale" not in self._segments_de("lead-1", "2026-09-24T08:59:59-04:00")
        assert "quote_stale" in self._segments_de("lead-1", "2026-09-24T09:00:00-04:00")

    def test_l_envoi_l_emporte_sur_un_constat_brouillon_publie_avant_l_envoi(self, base_durable):
        """M3 publie UN constat par devis : un devis d'abord signalé brouillon n'est pas signalé de nouveau une fois
        envoyé. Sans l'envoi, `quote_stale` ne verrait jamais ce devis ; avec lui, il part de l'envoi."""
        _amener_a("lead-1", "qualifie")
        with stockage.transaction():
            evenements.publier("m3.devis_sans_reponse", "m03-estimation", {
                "devis_id": "devis-1", "lead_id": "lead-1", "chantier_id": None, "statut": "brouillon",
                "horodatage_devis": "2026-09-01T09:00:00-04:00", "horodatage_reference": "2026-09-20T09:00:00-04:00",
                "delai_relance_jours": 7}, evenement_id="m3-devis-sans-reponse-devis-1")
        _repartir()
        assert "quote_stale" not in self._segments_de("lead-1"), "un brouillon n'est pas un devis envoyé"

        _publier("devis-1", "lead-1")
        _repartir()

        connus = outils._devis_connus()
        assert [(d["devis_id"], d["statut_devis"], d["origine"]) for d in connus] == [
            ("devis-1", "envoye", "m3.devis_envoye")]
        assert self._segments_de("lead-1")["quote_stale"]["donnee"]["horodatage_devis"] == ENVOYE_LE

    def test_l_origine_du_depart_se_lit_dans_la_relance(self, base_durable):
        _amener_a("lead-1", "qualifie")
        _publier("devis-1", "lead-1")
        _repartir()
        (fait,) = [d for d in outils._devis_connus() if d["devis_id"] == "devis-1"]
        assert fait["origine"] == relances.ORIGINE_DEVIS_ENVOYE and fait["horodatage_devis"] == ENVOYE_LE

    def test_un_registre_en_memoire_ne_lit_pas_les_devis_donc_quote_stale_est_non_calculable(self, base_durable):
        outils.reinitialiser_registre()
        assert outils._devis_envoyes_recus() is None and outils._devis_connus() is None
        outils.utiliser_stockage_durable()
        assert outils._devis_envoyes_recus() == [] and outils._devis_connus() == []
