"""M2 consomme `m3.devis_accepte` (ADR-0009 §3, PLAN T4.10-a ; DEFINITION-PRODUIT §6 « soumission acceptée -> M4
planifie », §7 M2.8) : le lead qualifié devient `converti` avec la référence du devis, la prochaine action « planifier
le chantier » (règle citée) et une activité au Client 360, sans que personne ne l'écrive à la main et sans promettre de
date au client.

Utilise le VRAI bus (`evenements.repartir`, manifestes réels de `departments/`), une base SQLite temporaire migrée et le
registre de M2 branché sur le stockage durable. Seul M2 reçoit les événements de ces tests : les comptes de
`repartir()` sont ceux de M2 (l'effet des autres consommateurs du même événement est prouvé par
`tests/test_cascade_devis_accepte.py`).
Les devis publiés sont des charges fictives conformes au catalogue. Données fictives.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from m2_revenue_crm import clients, interactions, outils, statuts, suggestions
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS

M2 = "m02-revenue-crm"
ACCEPTE_LE = "2026-09-20T15:30:00-04:00"
DEBUT = dt.datetime(2026, 9, 20, 16, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
PRIX_TOTAL = "1234.56"


def _contrat(lead_id: str) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }


def _devis_accepte(devis_id: str, lead_id: str, horodatage: str = ACCEPTE_LE) -> dict:
    return {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{
            "reference_ligne": f"{devis_id}-L0", "description": "Gouttières 5po aluminium (fictif)",
            "quantite": "40", "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": PRIX_TOTAL,
            "reference_besoin_materiau": "gouttiere_5po_alu",
        }],
        "cout_total": "987.65", "prix_total": PRIX_TOTAL, "taux_marge": "0.25",
        "horodatage_acceptation": horodatage,
    }


def _publier(devis_id: str, lead_id: str, evenement_id: str | None = None, horodatage: str = ACCEPTE_LE) -> str:
    identifiant = evenement_id or f"m3-devis-accepte-{devis_id}"
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte(devis_id, lead_id, horodatage),
                       evenement_id=identifiant)
    return identifiant


def _amener_a(lead_id: str, statut: str, reference: str = "DEVIS-FICTIF-1") -> None:
    """Amène un lead fictif à `statut` par les outils composés de M2 (jamais un accès direct au registre)."""
    outils.ingerer_lead(_contrat(lead_id), "2026-09-01T09:00:00-04:00")
    if statut == "nouveau":
        return
    if statut == "perdu":
        outils.transitionner_statut(
            lead_id, "perdu", "2026-09-01T09:05:00-04:00", motif="Client parti ailleurs (fictif)")
        return
    outils.transitionner_statut(
        lead_id, "qualifie", "2026-09-01T09:05:00-04:00", owner="Alice",
        prochaine_action={"description": "Appeler", "echeance": "2026-09-05T09:00:00-04:00"})
    if statut == "qualifie":
        return
    outils.transitionner_statut(lead_id, "converti", "2026-09-01T09:10:00-04:00", reference_devis_m3=reference)
    if statut == "converti":
        return
    outils.transitionner_statut(lead_id, "cedule", "2026-09-01T09:15:00-04:00")
    if statut == "cedule":
        return
    outils.transitionner_statut(lead_id, "chantier", "2026-09-01T09:20:00-04:00")
    assert statut == "chantier", statut


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


def _deps_bus():
    """Seul M2 reçoit `m3.devis_accepte` ici : les comptes de `repartir()` sont ceux de M2."""
    return {M2: charger_departements()[M2]}


def _repartir(instant: str = "2026-09-20T16:00:00-04:00") -> dict[str, int]:
    return evenements.repartir(_deps_bus(), maintenant=instant)


def _repartir_jusqu_au_bout(tours: int = 6) -> dict[str, int]:
    """Livre à intervalles de 100 s (le plus long délai de réessai est de 16 s) : cinq échecs ferment un événement."""
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(tours):
        resume = _repartir((DEBUT + dt.timedelta(seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    return total


def _maillons(nom: str = "principal") -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(M2, nom))


def _recu(evenement_id: str) -> dict:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == M2)
        )).mappings().first()
    assert ligne is not None, f"aucun reçu pour {evenement_id}"
    return dict(ligne)


def _resultat(evenement_id: str) -> dict:
    return codec.decoder(_recu(evenement_id)["resultat"])


def _statut(lead_id: str) -> str | None:
    return statuts.statut_courant(outils._obtenir_registre(), lead_id)


def _transitions(lead_id: str, statut: str) -> list[dict]:
    return [m for m in _maillons() if m["type_entree"] == "transition_statut" and m["lead_id"] == lead_id
            and m["statut"] == statut]


def _interactions_systeme(lead_id: str) -> list[dict]:
    return [m for m in _maillons() if m["type_entree"] == "interaction" and m["lead_id"] == lead_id
            and m["auteur"] == "system:m3"]


class TestManifeste:
    def test_la_fonction_est_branchee_au_vrai_manifeste(self):
        dep = charger_departements()[M2]
        assert "m3.devis_accepte" in dep.evenements_consomme
        assert dep.charger_consommateurs()["m3.devis_accepte"].__name__ == "_recevoir_devis_accepte"
        assert evenements.verifier_coherence(charger_departements()) == []

    def test_les_types_declares_et_les_fonctions_sont_les_memes(self):
        dep = charger_departements()[M2]
        assert set(dep.evenements_consomme) == set(dep.charger_consommateurs())


class TestNominal:
    def test_le_lead_qualifie_devient_converti_avec_la_reference_du_devis(self, base_durable):
        _amener_a("LEAD-A", "qualifie")
        evenement_id = _publier("DEVIS-A", "LEAD-A")

        resume = _repartir()
        assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}

        assert _statut("LEAD-A") == "converti"
        (converti,) = _transitions("LEAD-A", "converti")
        assert converti["statut_precedent"] == "qualifie"
        assert converti["reference_devis_m3"] == "DEVIS-A"
        assert converti["horodatage"] == ACCEPTE_LE, "l'heure de l'acceptation fournie par M3, jamais une horloge de M2"
        assert converti["prochaine_action"] == suggestions.prochaine_action_planifier_chantier("DEVIS-A", ACCEPTE_LE)

        resultat = _resultat(evenement_id)
        assert resultat["traite"] is True and resultat["converti"] is True and resultat["statut"] == "converti"
        assert evenements.etat()["quarantaine"] == []

    def test_la_prochaine_action_cite_sa_regle_et_ne_promet_aucune_date(self, base_durable):
        _amener_a("LEAD-B", "qualifie")
        _publier("DEVIS-B", "LEAD-B")
        _repartir()

        (converti,) = _transitions("LEAD-B", "converti")
        action = converti["prochaine_action"]
        assert action["description"].startswith("Planifier le chantier avec M4")
        assert "règle planifier_chantier" in action["description"] and "DEVIS-B" in action["description"]
        assert "Aucune date ni aucun créneau n'est promis au client" in action["description"]
        assert action["echeance"] == ACCEPTE_LE, "l'échéance est l'heure réelle de l'acceptation, pas une date future"

    def test_une_activite_systeme_rattache_l_acceptation_au_dossier(self, base_durable):
        _amener_a("LEAD-C", "qualifie")
        _publier("DEVIS-C", "LEAD-C")
        _repartir()

        (activite,) = _interactions_systeme("LEAD-C")
        assert activite["horodatage"] == ACCEPTE_LE
        assert "DEVIS-C" in activite["resume"] and "converti" in activite["resume"]
        assert "Planifier le chantier avec M4" in activite["resume"]

    def test_le_client_360_montre_le_statut_la_prochaine_action_et_l_activite(self, base_durable):
        _amener_a("LEAD-D", "qualifie")
        _publier("DEVIS-D", "LEAD-D")
        _repartir()

        client_id = clients.client_de_lead(outils._obtenir_registre(), "LEAD-D")
        vue = outils.obtenir_client_360(client_id)["resultat"]
        (opportunite,) = vue["opportunites"]
        assert opportunite["statut"] == "converti"
        assert opportunite["prochaine_action"]["description"].startswith("Planifier le chantier avec M4")
        assert any(i["auteur"] == "system:m3" and "DEVIS-D" in i["resume"] for i in vue["interactions_recentes"])

    def test_la_suggestion_d_un_lead_converti_est_la_meme_regle(self, base_durable):
        _amener_a("LEAD-E", "qualifie")
        _publier("DEVIS-E", "LEAD-E")
        _repartir()

        suggestion = outils.suggerer_prochaine_action("LEAD-E", "2026-09-21T09:00:00-04:00")["resultat"]
        (converti,) = _transitions("LEAD-E", "converti")
        assert suggestion["regle"] == "planifier_chantier"
        assert converti["prochaine_action"]["description"].startswith(suggestion["suggestion"])

    def test_aucun_montant_n_entre_au_registre_de_m2(self, base_durable):
        """M2 n'est pas la source de vérité financière (§7 M2) : ni prix, ni coût, ni marge du devis."""
        _amener_a("LEAD-F", "qualifie")
        _publier("DEVIS-F", "LEAD-F")
        _repartir()

        contenu = json.dumps(_maillons() + _maillons("devis_acceptes_recus"), ensure_ascii=False, sort_keys=True)
        for montant in (PRIX_TOTAL, "987.65", "0.25", "prix_total", "cout_total", "taux_marge"):
            assert montant not in contenu, montant

    def test_la_conversion_ne_touche_pas_aux_autres_leads(self, base_durable):
        _amener_a("LEAD-G1", "qualifie")
        _amener_a("LEAD-G2", "qualifie")
        avant = json.dumps([m for m in _maillons() if m.get("lead_id") == "LEAD-G2"], sort_keys=True)
        _publier("DEVIS-G1", "LEAD-G1")
        _repartir()

        assert _statut("LEAD-G1") == "converti" and _statut("LEAD-G2") == "qualifie"
        assert json.dumps([m for m in _maillons() if m.get("lead_id") == "LEAD-G2"], sort_keys=True) == avant


class TestIdempotence:
    def test_un_evenement_rejoue_ne_convertit_pas_deux_fois(self, base_durable):
        _amener_a("LEAD-H", "qualifie")
        evenement_id = _publier("DEVIS-H", "LEAD-H")
        _repartir()
        maillons = json.dumps(_maillons(), sort_keys=True)

        assert _publier("DEVIS-H", "LEAD-H", evenement_id=evenement_id) == evenement_id  # no-op du bus
        assert _repartir("2026-09-20T16:05:00-04:00")["livres"] == 0
        assert json.dumps(_maillons(), sort_keys=True) == maillons

    def test_le_meme_devis_sous_un_autre_evenement_est_deja_applique(self, base_durable):
        _amener_a("LEAD-I", "qualifie")
        _publier("DEVIS-I", "LEAD-I")
        _repartir()
        maillons = json.dumps(_maillons(), sort_keys=True)

        autre = _publier("DEVIS-I", "LEAD-I", evenement_id="rejeu-par-un-autre-producteur")
        resume = _repartir("2026-09-20T16:05:00-04:00")
        assert resume["traites"] == 1 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
        assert _resultat(autre) == {"traite": True, "lead_id": "LEAD-I", "devis_id": "DEVIS-I", "deja_applique": True}
        assert json.dumps(_maillons(), sort_keys=True) == maillons, "aucun maillon de plus"
        assert len(_transitions("LEAD-I", "converti")) == 1 and len(_interactions_systeme("LEAD-I")) == 1

    def test_le_registre_des_devis_recus_garde_un_fait_par_devis(self, base_durable):
        _amener_a("LEAD-J", "qualifie")
        _publier("DEVIS-J", "LEAD-J")
        _publier("DEVIS-J", "LEAD-J", evenement_id="autre-id")
        _repartir()

        recus = _maillons("devis_acceptes_recus")
        assert [(r["devis_id"], r["lead_id"]) for r in recus] == [("DEVIS-J", "LEAD-J")]
        assert recus[0]["horodatage_acceptation"] == ACCEPTE_LE and recus[0]["client_id"]


class TestLeadDejaConverti:
    @pytest.mark.parametrize("statut", ["converti", "cedule", "chantier"])
    def test_un_lead_deja_converti_par_ce_devis_n_est_pas_touche(self, base_durable, statut):
        """Le flux d'avant T4.10 : un humain a converti le lead avant l'acceptation. Rien à refaire."""
        _amener_a(f"LEAD-K-{statut}", statut, reference="DEVIS-K")
        maillons = json.dumps(_maillons(), sort_keys=True)
        evenement_id = _publier("DEVIS-K", f"LEAD-K-{statut}")

        resume = _repartir()
        assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
        resultat = _resultat(evenement_id)
        assert resultat["converti"] is False and resultat["deja_converti"] is True and resultat["statut"] == statut
        assert json.dumps(_maillons(), sort_keys=True) == maillons
        assert _maillons("devis_acceptes_recus")[0]["deja_converti"] is True

    def test_un_lead_converti_par_un_autre_devis_part_en_quarantaine_sans_ecriture(self, base_durable):
        _amener_a("LEAD-L", "converti", reference="DEVIS-L-ORIGINE")
        maillons = json.dumps(_maillons(), sort_keys=True)
        evenement_id = _publier("DEVIS-L-AUTRE", "LEAD-L")

        total = _repartir_jusqu_au_bout()
        assert total["quarantaines"] == 1 and total["traites"] == 0, total
        recu = _recu(evenement_id)
        assert recu["statut"] == "quarantaine" and recu["tentatives"] == 5
        assert "AcceptationIncompatible" in recu["derniere_erreur"]
        assert "DEVIS-L-ORIGINE" in recu["derniere_erreur"] and "DEVIS-L-AUTRE" in recu["derniere_erreur"]
        assert json.dumps(_maillons(), sort_keys=True) == maillons
        assert _maillons("devis_acceptes_recus") == []
        assert _statut("LEAD-L") == "converti"
        assert statuts.reference_devis(outils._obtenir_registre(), "LEAD-L") == "DEVIS-L-ORIGINE"


class TestLeadClosOuInconnu:
    def test_un_lead_perdu_garde_le_fait_sans_conversion_ni_quarantaine(self, base_durable):
        _amener_a("LEAD-M", "perdu")
        maillons = json.dumps(_maillons(), sort_keys=True)
        evenement_id = _publier("DEVIS-M", "LEAD-M")

        resume = _repartir()
        assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
        resultat = _resultat(evenement_id)
        assert resultat["converti"] is False and "dossier clos" in resultat["motif"]
        assert _statut("LEAD-M") == "perdu"
        assert json.dumps(_maillons(), sort_keys=True) == maillons, "ni transition ni interaction sur un dossier clos"
        (recu,) = _maillons("devis_acceptes_recus")
        assert recu["ignore"] == "lead_clos" and recu["devis_id"] == "DEVIS-M"
        assert evenements.etat()["quarantaine"] == []

    def test_un_lead_inconnu_est_reessaye_puis_mis_en_quarantaine_sans_ecriture(self, base_durable):
        evenement_id = _publier("DEVIS-N", "LEAD-INCONNU")

        total = _repartir_jusqu_au_bout()
        assert total["quarantaines"] == 1 and total["echecs"] == 4 and total["traites"] == 0, total
        recu = _recu(evenement_id)
        assert recu["statut"] == "quarantaine" and recu["tentatives"] == 5
        assert "LeadIntrouvable" in recu["derniere_erreur"] and "LEAD-INCONNU" in recu["derniere_erreur"]
        assert _maillons() == [] and _maillons("devis_acceptes_recus") == []
        (en_quarantaine,) = evenements.etat()["quarantaine"]
        assert en_quarantaine["type_evenement"] == "m3.devis_accepte" and en_quarantaine["consommateur"] == M2

    def test_ordre_inverse_le_devis_arrive_avant_le_lead_puis_tout_se_rejoue_sans_doublon(self, base_durable):
        evenement_id = _publier("DEVIS-O", "LEAD-O")
        premier = _repartir("2026-09-20T16:00:00-04:00")
        assert premier["echecs"] == 1 and premier["traites"] == 0 and premier["quarantaines"] == 0, premier
        assert _recu(evenement_id)["statut"] == "echec"

        _amener_a("LEAD-O", "qualifie")  # le lead arrive enfin (M1 puis qualification)
        suite = _repartir("2026-09-20T16:05:00-04:00")  # le délai de réessai est écoulé
        assert suite["traites"] == 1 and suite["echecs"] == 0, suite

        assert _statut("LEAD-O") == "converti"
        assert len(_transitions("LEAD-O", "converti")) == 1 and len(_interactions_systeme("LEAD-O")) == 1
        assert _recu(evenement_id)["statut"] == "traite"
        assert _repartir("2026-09-20T16:10:00-04:00")["livres"] == 0
        assert len(_transitions("LEAD-O", "converti")) == 1

    def test_un_lead_jamais_qualifie_part_en_quarantaine_sans_transition_fabriquee(self, base_durable):
        _amener_a("LEAD-P", "nouveau")
        maillons = json.dumps(_maillons(), sort_keys=True)
        evenement_id = _publier("DEVIS-P", "LEAD-P")

        total = _repartir_jusqu_au_bout()
        assert total["quarantaines"] == 1, total
        erreur = _recu(evenement_id)["derniere_erreur"]
        assert "AcceptationIncompatible" in erreur and "n'a jamais été qualifié" in erreur
        assert _statut("LEAD-P") == "nouveau"
        assert json.dumps(_maillons(), sort_keys=True) == maillons, "aucune transition sans propriétaire ni décision"


class TestRefusEtAtomicite:
    def test_un_horodatage_d_acceptation_invalide_est_refuse_sans_ecriture(self, base_durable):
        _amener_a("LEAD-Q", "qualifie")
        maillons = json.dumps(_maillons(), sort_keys=True)
        evenement_id = _publier("DEVIS-Q", "LEAD-Q", horodatage="hier après-midi")

        total = _repartir_jusqu_au_bout()
        assert total["quarantaines"] == 1, total
        erreur = _recu(evenement_id)["derniere_erreur"]
        assert "AcceptationIncompatible" in erreur and "REJ-HORODATAGE-INVALIDE" in erreur
        assert json.dumps(_maillons(), sort_keys=True) == maillons
        assert _statut("LEAD-Q") == "qualifie"

    def test_une_panne_apres_la_transition_annule_aussi_la_transition(self, base_durable, monkeypatch):
        """Même transaction : si l'activité échoue, le lead n'est pas converti à moitié."""
        _amener_a("LEAD-R", "qualifie")
        maillons = json.dumps(_maillons(), sort_keys=True)
        evenement_id = _publier("DEVIS-R", "LEAD-R")
        with monkeypatch.context() as panne:
            panne.setattr(
                interactions, "enregistrer",
                lambda *_a, **_k: (None, {"code": "REJ-CHAMP-VIDE", "statut": "", "detail": "panne simulée"}),
            )
            resume = _repartir()
        assert resume["echecs"] == 1 and resume["traites"] == 0, resume
        assert "RuntimeError" in _recu(evenement_id)["derniere_erreur"]
        assert _statut("LEAD-R") == "qualifie"
        assert json.dumps(_maillons(), sort_keys=True) == maillons, "la transition a été annulée avec l'activité"
        assert _maillons("devis_acceptes_recus") == []

        assert _repartir("2026-09-20T16:05:00-04:00")["traites"] == 1
        assert _statut("LEAD-R") == "converti" and len(_transitions("LEAD-R", "converti")) == 1
