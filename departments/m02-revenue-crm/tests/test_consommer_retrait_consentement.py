"""M2 consomme `m1.retrait_consentement` (ADR-0009 §3, PLAN T4.9 ; POLITIQUE-consentement-sms §4 « STOP »,
DEFINITION-PRODUIT §7 M2 « opt-in respecté ») : le STOP d'un client est rangé par `lead_id`, jamais son numéro, et plus
aucun canal écrit ne reste ouvert à sa PERSONNE.

Utilise le VRAI bus (`evenements.repartir`, manifeste réel de M2), une base SQLite temporaire migrée et le registre de
M2 sur le stockage durable. Les charges sont conformes au catalogue (`m1.retrait_consentement.json`) et publiées comme
M1 les publie (schéma fermé : `lead_ids`, `canal`, `horodatage`, `signal_id`). Ce qui est prouvé : le retrait est rangé
sans contact ; un rejeu, ou le même STOP sous un autre identifiant d'événement, n'écrit rien de plus ; un retrait
illisible n'est JAMAIS ignoré (quarantaine, visible, sans écriture partielle) ; un STOP pour un lead que M2 ne connaît
pas encore est rangé quand même ; et le retrait ferme les canaux écrits de la personne (tous ses leads), jamais l'appel.
Données fictives.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from m2_revenue_crm import clients, consentements, outils
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS

FICTIF = True

M2 = "m02-revenue-crm"
NUMERO = "418-555-0100"
STOP_LE = "2026-09-25T09:00:00-04:00"
DEBUT = dt.datetime(2026, 9, 29, 16, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
CONTACT_PARTAGE = {"nom": "Cliente Partagée", "telephone": NUMERO, "courriel": "partagee@example.test"}
PREUVE = {"type": "formulaire", "reference": "formulaire-web-2026-09-20-0042"}


def _contrat(lead_id: str, contact: dict | None = None) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": contact
        or {"nom": f"Client {lead_id}", "telephone": "418-555-0199", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }


def _ingerer(lead_id: str, contact: dict | None = None, *, qualifier: bool = True) -> None:
    assert outils.ingerer_lead(_contrat(lead_id, contact), "2026-09-01T09:00:00-04:00")["accepte"] is True
    if qualifier:
        assert outils.transitionner_statut(
            lead_id, "qualifie", "2026-09-01T09:05:00-04:00", owner="vendeur.un", prochaine_action=ACTION)["accepte"]


def _charge(lead_ids, canal="sms", signal_id="sms:SM-STOP-1", horodatage=STOP_LE) -> dict:
    """La charge que M1 publie (`retrait.charge`) : quatre clés, ni numéro, ni courriel, ni conversation."""
    return {"lead_ids": list(lead_ids), "canal": canal, "horodatage": horodatage, "signal_id": signal_id}


def _publier(lead_ids, evenement_id="m1-retrait-consentement-fictif-1", **plus) -> str:
    evenements.publier("m1.retrait_consentement", "m01-front-office", _charge(lead_ids, **plus),
                       evenement_id=evenement_id)
    return evenement_id


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


def _journal() -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(M2, "consentements_contact"))


def _retraits() -> list[dict]:
    return [m for m in _journal() if m["type_entree"] == "retrait_contact"]


def _resultat(evenement_id: str) -> dict:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == M2)
        )).mappings().first()
    assert ligne is not None, f"aucun reçu pour {evenement_id}"
    return codec.decoder(ligne["resultat"])


def _appeler_le_consommateur(charge: dict) -> dict:
    with stockage.transaction():
        return outils._recevoir_retrait_consentement(charge)


def _canaux_permis(lead_id: str) -> tuple[list[str], dict]:
    """Les canaux permis à la PERSONNE de ce lead, lus comme le fait la liste des relances."""
    with stockage.transaction():
        reg = outils._obtenir_registre()
        contenus, retraits, _ = outils._registres_de_relance()
        return consentements.canaux_permis(outils._perimetre_du_lead(reg, lead_id), contenus, retraits)


def _consentir(lead_id: str, canal: str = "sms", *, instant: str = "2026-09-20T10:05:00-04:00") -> None:
    with stockage.transaction():
        reg = outils._obtenir_registre()
        entree, verdict = consentements.construire_consentement(
            lead_id, clients.client_de_lead(reg, lead_id), canal, "consentement-v1", "formulaire", dict(PREUVE),
            "2026-09-20T10:00:00-04:00", instant, "vendeur.un", "appareil")
        assert verdict is None, verdict
        stockage.maillons(M2, "consentements_contact").append(entree)


class TestManifeste:
    def test_la_fonction_est_branchee_au_vrai_manifeste(self):
        dep = charger_departements()[M2]
        assert "m1.retrait_consentement" in dep.evenements_consomme
        assert dep.charger_consommateurs()["m1.retrait_consentement"].__name__ == "_recevoir_retrait_consentement"
        assert evenements.verifier_coherence(charger_departements()) == []

    def test_le_type_est_au_catalogue_et_m1_le_publie(self):
        assert "m1.retrait_consentement" in evenements.types_connus()
        assert "m1.retrait_consentement" in charger_departements()["m01-front-office"].evenements_publie

    def test_la_charge_de_ces_tests_est_conforme_au_catalogue_et_le_schema_est_ferme(self):
        assert erreurs_charge("m1.retrait_consentement", _charge(["lead-1"])) == []
        assert erreurs_charge("m1.retrait_consentement", {**_charge(["lead-1"]), "telephone": NUMERO}) != []
        assert erreurs_charge("m1.retrait_consentement", {**_charge(["lead-1"]), "conversation_id": "conv-1"}) != []
        assert erreurs_charge("m1.retrait_consentement", _charge([])) != []


class TestRangement:
    def test_le_stop_est_range_par_lead_sans_aucun_contact(self, base_durable):
        _ingerer("lead-1", CONTACT_PARTAGE)
        identifiant = _publier(["lead-1"])

        resume = _repartir()

        assert (resume["traites"], resume["echecs"], resume["quarantaines"]) == (1, 0, 0)
        (retrait,) = _retraits()
        assert retrait == {
            "type_entree": "retrait_contact", "retrait_id": retrait["retrait_id"], "lead_id": "lead-1", "canal": "sms",
            "signal_id": "sms:SM-STOP-1", "horodatage": STOP_LE, "source": "bus:m1.retrait_consentement",
        }
        assert _resultat(identifiant) == {"traite": True, "retraits_ecrits": 1, "deja_enregistres": 0}

    def test_le_numero_du_client_n_est_jamais_stocke_dans_le_registre_du_retrait(self, base_durable):
        _ingerer("lead-1", CONTACT_PARTAGE)
        _publier(["lead-1"])
        _repartir()
        tout = json.dumps(_journal()) + json.dumps(_resultat("m1-retrait-consentement-fictif-1"))
        for secret in (NUMERO, "4185550100", "partagee@example.test", "Cliente"):
            assert secret not in tout, secret

    def test_un_stop_qui_couvre_deux_leads_ecrit_un_retrait_par_lead(self, base_durable):
        _ingerer("lead-1")
        _ingerer("lead-2")
        identifiant = _publier(["lead-1", "lead-2"])
        assert _repartir()["traites"] == 1
        assert sorted(r["lead_id"] for r in _retraits()) == ["lead-1", "lead-2"]
        assert len({r["retrait_id"] for r in _retraits()}) == 2
        assert _resultat(identifiant) == {"traite": True, "retraits_ecrits": 2, "deja_enregistres": 0}

    def test_le_stop_par_courriel_est_range_avec_son_canal(self, base_durable):
        _ingerer("lead-1")
        _publier(["lead-1"], canal="courriel", signal_id="courriel:MSG-9")
        _repartir()
        (retrait,) = _retraits()
        assert (retrait["canal"], retrait["signal_id"]) == ("courriel", "courriel:MSG-9")

    def test_un_stop_pour_un_lead_que_m2_ne_connait_pas_encore_est_range_quand_meme(self, base_durable):
        identifiant = _publier(["lead-pas-encore-ingere"])
        resume = _repartir()
        assert (resume["traites"], resume["quarantaines"]) == (1, 0)
        assert [r["lead_id"] for r in _retraits()] == ["lead-pas-encore-ingere"]
        assert _resultat(identifiant)["retraits_ecrits"] == 1

    def test_un_lead_perdu_est_retire_aussi_le_retrait_ne_depend_pas_du_statut(self, base_durable):
        _ingerer("lead-1", qualifier=False)
        assert outils.transitionner_statut("lead-1", "perdu", "2026-09-02T09:00:00-04:00", motif="parti (fictif)")[
            "accepte"]
        _publier(["lead-1"])
        assert _repartir()["traites"] == 1 and len(_retraits()) == 1


class TestIdempotence:
    def test_un_evenement_rejoue_n_ecrit_rien_de_plus(self, base_durable):
        _ingerer("lead-1")
        _publier(["lead-1"])
        _repartir()
        avant = _journal()

        _publier(["lead-1"])  # même identifiant d'événement : un no-op du bus
        assert _repartir()["livres"] == 0
        assert _journal() == avant

    def test_le_meme_stop_sous_un_autre_identifiant_est_reconnu_lead_par_lead(self, base_durable):
        _ingerer("lead-1")
        _publier(["lead-1"])
        _repartir()
        avant = _journal()

        autre = _publier(["lead-1"], evenement_id="m1-retrait-consentement-fictif-autre")
        resume = _repartir()

        assert (resume["traites"], resume["echecs"], resume["quarantaines"]) == (1, 0, 0)
        assert _resultat(autre) == {"traite": True, "retraits_ecrits": 0, "deja_enregistres": 1}
        assert _journal() == avant

    def test_un_stop_qui_ajoute_un_lead_n_ecrit_que_le_nouveau(self, base_durable):
        _ingerer("lead-1")
        _ingerer("lead-2")
        _publier(["lead-1"])
        _repartir()
        autre = _publier(["lead-1", "lead-2"], evenement_id="m1-retrait-consentement-fictif-2")
        _repartir()
        assert sorted(r["lead_id"] for r in _retraits()) == ["lead-1", "lead-2"]
        assert _resultat(autre) == {"traite": True, "retraits_ecrits": 1, "deja_enregistres": 1}

    def test_un_autre_stop_du_meme_lead_est_un_autre_retrait_et_le_premier_date_toujours(self, base_durable):
        _ingerer("lead-1")
        _publier(["lead-1"])
        _publier(["lead-1"], evenement_id="m1-retrait-consentement-fictif-2", signal_id="sms:SM-STOP-2",
                 horodatage="2026-09-27T09:00:00-04:00")
        _repartir()
        assert [r["signal_id"] for r in _retraits()] == ["sms:SM-STOP-1", "sms:SM-STOP-2"]
        with stockage.transaction():
            _, retraits, _ = outils._registres_de_relance()
        etat = consentements.etat_du_canal("sms", frozenset({"lead-1"}), [], retraits)
        assert etat["retire_le"] == STOP_LE, "le premier STOP date le retrait"

    def test_un_lead_ouvert_apres_le_stop_donne_un_second_evenement_pour_ce_lead_seul(self, base_durable):
        """M1 publie, pour un lead ouvert APRÈS le STOP, un second événement avec l'heure et le signal du STOP
        d'origine."""
        _ingerer("lead-1")
        _ingerer("lead-2")
        _publier(["lead-1"])
        _publier(["lead-2"], evenement_id="m1-retrait-consentement-fictif-2")  # même signal, autre lead
        assert _repartir()["traites"] == 2
        assert sorted(r["lead_id"] for r in _retraits()) == ["lead-1", "lead-2"]
        assert {r["signal_id"] for r in _retraits()} == {"sms:SM-STOP-1"}
        assert {r["horodatage"] for r in _retraits()} == {STOP_LE}


class TestRefus:
    @pytest.mark.parametrize("charge", [
        {"lead_ids": [], "canal": "sms", "horodatage": STOP_LE, "signal_id": "sms:x"},
        {"lead_ids": None, "canal": "sms", "horodatage": STOP_LE, "signal_id": "sms:x"},
        {"lead_ids": "lead-1", "canal": "sms", "horodatage": STOP_LE, "signal_id": "sms:x"},
        {"canal": "sms", "horodatage": STOP_LE, "signal_id": "sms:x"},
    ])
    def test_sans_lead_le_retrait_est_refuse_pas_ignore(self, base_durable, charge):
        with pytest.raises(outils.RetraitIllisible, match="au moins un lead"):
            _appeler_le_consommateur(charge)
        assert _journal() == []

    @pytest.mark.parametrize(("surcharge", "mot"), [
        ({"canal": "appel"}, "canal"), ({"canal": None}, "canal"), ({"canal": "whatsapp"}, "canal"),
        ({"signal_id": ""}, "signal_id"), ({"signal_id": None}, "signal_id"),
        ({"horodatage": "hier"}, "horodatage"), ({"horodatage": "2026-09-25T09:00:00"}, "horodatage"),
        ({"horodatage": None}, "horodatage"),
    ])
    def test_un_champ_illisible_refuse_tout_le_retrait_sans_ecriture(self, base_durable, surcharge, mot):
        with pytest.raises(outils.RetraitIllisible, match=mot):
            _appeler_le_consommateur({**_charge(["lead-1", "lead-2"]), **surcharge})
        assert _journal() == [], "rien n'est à moitié rangé : un lead illisible ne laisse pas les autres inscrits"

    def test_un_lead_illisible_au_milieu_n_ecrit_aucun_des_autres(self, base_durable):
        with pytest.raises(outils.RetraitIllisible, match="lead_id"):
            _appeler_le_consommateur(_charge(["lead-1", "", "lead-3"]))
        assert _journal() == []

    def test_un_retrait_illisible_finit_en_quarantaine_visible_jamais_ignore(self, base_durable):
        # Une charge que le catalogue refuserait ne se publie pas ; on la rend illisible par ce que le schéma laisse
        # passer : une heure sans fuseau (le catalogue ne demande qu'un texte non vide).
        identifiant = _publier(["lead-1"], horodatage="2026-09-25T09:00:00")

        total = _repartir_jusqu_au_bout()

        assert (total["traites"], total["quarantaines"]) == (0, 1) and total["echecs"] >= 4
        assert _journal() == []
        (quarantaine,) = evenements.etat()["quarantaine"]
        assert quarantaine["evenement_id"] == identifiant
        assert "REJ-HORODATAGE-INVALIDE" in quarantaine["derniere_erreur"]


class TestEffet:
    """Plus aucun canal écrit pour la PERSONNE (tous ses leads), l'appel reste permis."""

    def test_avant_le_stop_un_consentement_ouvre_son_canal_apres_le_stop_plus_aucun_canal_ecrit(self, base_durable):
        _ingerer("lead-1", CONTACT_PARTAGE)
        _consentir("lead-1", "sms")
        _consentir("lead-1", "courriel")
        assert _canaux_permis("lead-1")[0] == ["appel", "sms", "courriel"]

        _publier(["lead-1"])
        _repartir()

        permis, etats = _canaux_permis("lead-1")
        assert permis == ["appel"]
        assert etats["sms"]["etat"] == etats["courriel"]["etat"] == "retire"
        assert etats["sms"]["source"] == "bus:m1.retrait_consentement" and etats["sms"]["retire_le"] == STOP_LE

    def test_le_stop_d_un_lead_ferme_les_canaux_de_tous_les_leads_du_meme_client(self, base_durable):
        _ingerer("lead-1", CONTACT_PARTAGE)
        _ingerer("lead-2", CONTACT_PARTAGE)  # même contact : même client
        _consentir("lead-2", "sms")
        assert _canaux_permis("lead-1")[0] == ["appel", "sms"], "le consentement est celui de la personne"

        _publier(["lead-1"])
        _repartir()

        assert _canaux_permis("lead-1")[0] == ["appel"] and _canaux_permis("lead-2")[0] == ["appel"]

    def test_le_stop_d_un_client_ne_touche_pas_un_autre_client(self, base_durable):
        _ingerer("lead-1")
        _ingerer("lead-2")
        _consentir("lead-1", "sms")
        _consentir("lead-2", "sms")
        _publier(["lead-1"])
        _repartir()
        assert _canaux_permis("lead-1")[0] == ["appel"]
        assert _canaux_permis("lead-2")[0] == ["appel", "sms"]

    def test_un_stop_arrive_avant_le_lead_s_applique_des_que_le_lien_existe(self, base_durable):
        _publier(["lead-1"])
        _repartir()
        _ingerer("lead-1", CONTACT_PARTAGE)
        _ingerer("lead-2", CONTACT_PARTAGE)
        _consentir("lead-2", "sms")
        assert _canaux_permis("lead-2")[0] == ["appel"], "résolu à la lecture : jamais dépendant de l'ordre d'arrivée"

    def test_un_consentement_inscrit_apres_le_stop_ne_le_leve_pas(self, base_durable):
        _ingerer("lead-1")
        _publier(["lead-1"])
        _repartir()
        _consentir("lead-1", "sms", instant="2026-10-15T10:05:00-04:00")
        permis, etats = _canaux_permis("lead-1")
        assert permis == ["appel"] and etats["sms"]["etat"] == "retire"
