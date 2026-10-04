"""PLAN T4.18 — l'amont d'une affaire atteint M10 (DEFINITION-PRODUIT §6 : « M10 reçoit des événements de tous les
départements à chaque étape »), par le VRAI bus, sur les VRAIS départements et les VRAIS producteurs.

Le trajet, sans réseau ni core (le core ne s'exécute pas ici) :

    SMS du client -> `m1_recevoir_message_canal` (vrai M1) -> `m1.lead_qualifie`
    -> `evenements.repartir` sur TOUS les départements : M2 ingère le lead et publie `m2.client_associe`
    -> M2 qualifie, M3 crée deux devis, un humain marque l'un accepté (T3) -> `m3.devis_accepte` ;
       le contrôle de relance de M3 publie `m3.devis_sans_reponse` pour l'autre
    -> M10 (parmi les consommateurs) garde l'historique de l'affaire : le paquet le montre, filtré par agent.

Ce test fait ce que les charges fictives de `departments/m10-memoire/tests/test_amont.py` ne peuvent pas : prouver que
les charges RÉELLES des producteurs (empreintes de 64 caractères, identifiants de devis, montants calculés par M3)
passent les formes fermées de M10, et que le numéro de téléphone du client, qui traverse tout le bus, n'entre dans
aucun registre de M10. Données fictives (`fictif: true` au sens d'AGENTS.md : numéro, personnes, montants de test).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json

import pytest
from m1_front_office import outils as m1_outils
from m2_revenue_crm import outils as m2_outils
from m10_memoire import classification, etapes
from m10_memoire import outils as m10_outils
from sqlalchemy import select

from opsys import contexte, evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import Departement, charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

DEBUT = dt.datetime(2026, 9, 29, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
NUMERO = "+15145550142"
RECU_LE = "2026-09-29T09:15:00-04:00"
SMS = {
    "canal": "sms", "expediteur": NUMERO, "message_id": "SMfictif0418", "recu_le": RECU_LE,
    "texte": "Bonjour, mes gouttières fuient à Laval, c'est urgent.",
}
ACCEPTE_LE = "2026-09-30T10:00:00-04:00"
CONSTAT_LE = "2026-10-08T08:00:00-04:00"
LECTURE_LE = "2026-10-09T07:00:00-04:00"  # « maintenant » des lectures : l'heure d'aucun fait
M3 = "m03-estimation"
M1 = "m01-front-office"
M10 = "m10-memoire"
DEVIS_ACCEPTE = "DEVIS-T418-A"
DEVIS_SANS_REPONSE = "DEVIS-T418-B"
# Ce que M3 calcule pour le devis A (40 pi à 8,00 $ + 160,00 $ de main-d'oeuvre, marge 25 %) : jamais chez M10 hors du
# maillon financier.
MONTANTS_DU_DEVIS = ("600.00", "480.00", "0.25", "10.00")
TYPES = ("m1.lead_qualifie", "m2.client_associe", "m3.devis_accepte", "m3.devis_sans_reponse")


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    m1_outils.utiliser_stockage_durable()
    m2_outils.utiliser_stockage_durable()
    yield charger_departements()
    m1_outils.reinitialiser_registre()
    m2_outils.reinitialiser_registre()
    stockage.liberer()


def _outils(deps, dep_id):
    return {o.nom: o for o in deps[dep_id].charger_outils()}


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _drainer(deps: dict[str, Departement], depuis: dt.datetime, *, max_tours: int = 12, pas_s: int = 100) -> dict:
    """Livre le bus jusqu'à quiescence, sur les départements donnés (boucle bornée)."""
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(max_tours):
        resume = evenements.repartir(deps, maintenant=(depuis + dt.timedelta(seconds=pas_s * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence après {max_tours} tours : {total}")


def _recu_m10(evenement_id: str) -> dict:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == M10)
        )).mappings().first()
    assert ligne is not None, f"M10 n'a aucun reçu pour {evenement_id}"
    return {**dict(ligne), "resultat": codec.decoder(ligne["resultat"]) if ligne["resultat"] else None}


def _maillons_m10(registre: str = "evenements") -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(M10, registre))


def _paquet_m10(affaire_id: str, horodatage: str, departement: str) -> dict:
    with contexte.appeler_en_tant_que(departement):
        return m10_outils.paquet_contexte_affaire(affaire_id, horodatage)


def _quarantaine_m10() -> list[dict]:
    return [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == M10]


def test_m10_nextrait_pas_le_hash_de_provenance_du_devis():
    charge = {
        "devis_id": DEVIS_ACCEPTE, "lead_id": "LEAD-T418", "chantier_id": None,
        "horodatage_acceptation": ACCEPTE_LE, "estimation_source_hash": "a" * 64,
        "semantique_temps": "duree_ecoulee_intervention", "prix_total": "600.00",
        "cout_total": "480.00", "taux_marge": "0.25",
    }
    evenement = etapes._extraire_devis_accepte(charge)
    financier = etapes._extraire_montants_devis_accepte(charge)
    assert "estimation_source_hash" not in evenement
    assert "semantique_temps" not in evenement
    assert set(financier) == {"lead_id", "devis_id", "prix_total", "cout_total", "taux_marge", "horodatage"}


def _creer_devis(m3, devis_id: str, lead_id: str, horodatage: str, prix_total: str) -> None:
    _ok(executer_atomique(m3["m3_creer_devis"], {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [
            {"description": "Gouttières 5po aluminium (fictif)", "quantite": "40", "unite": "pi",
             "cout_unitaire": "8.00", "reference_besoin_materiau": "gouttiere-alu-5po-fictif"},
            {"description": "Main d'oeuvre installation (fictif)", "quantite": "1", "unite": "forfait",
             "cout_unitaire": "160.00", "reference_besoin_materiau": None},
        ],
        "taux_marge": "0.25", "horodatage": horodatage, "prix_total": prix_total}))


def _ids_publies() -> dict[str, list[str]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement, EVENEMENTS_SORTANTS.c.evenement_id)
                             .where(EVENEMENTS_SORTANTS.c.type_evenement.in_(TYPES))
                             .order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)).all()
    publies: dict[str, list[str]] = {}
    for type_evenement, evenement_id in lignes:
        publies.setdefault(type_evenement, []).append(evenement_id)
    return publies


@pytest.fixture
def affaire(instance):
    """L'affaire d'un SMS, de bout en bout : lead, client associé, devis A accepté, devis B resté sans réponse. Rend
    `(départements, lead_id)`, le bus déjà drainé sur TOUS les départements."""
    deps = instance
    capacites = Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    reponse = capacites.appeler("m1_recevoir_message_canal", SMS)
    assert reponse["ok"] is True and reponse["resultat"]["decision"] == "TRANSMETTRE_M2", reponse
    lead_id = reponse["resultat"]["lead"]["lead_id"]
    assert _drainer(deps, DEBUT)["quarantaines"] == 0  # M2 ingère le lead et publie le client associé

    m2, m3 = _outils(deps, "m02-revenue-crm"), _outils(deps, M3)
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": "2026-09-29T11:00:00-04:00",
        "owner": "Alice Vendeuse (fictif)",
        "prochaine_action": {
            "description": "Préparer la soumission (fictif)", "echeance": "2026-10-02T09:00:00-04:00"}}))
    _creer_devis(m3, DEVIS_ACCEPTE, lead_id, "2026-09-29T15:00:00-04:00", "600.00")
    _creer_devis(m3, DEVIS_SANS_REPONSE, lead_id, "2026-09-29T15:30:00-04:00", "600.00")
    _ok(executer_atomique(m3["m3_marquer_devis_accepte"], {
        "devis_id": DEVIS_ACCEPTE, "approbateur": "Nathan Proprietaire (fictif, T3)", "horodatage": ACCEPTE_LE}))
    detection = executer_atomique(m3["m3_detecter_devis_sans_reponse"], {
        "horodatage_reference": CONSTAT_LE, "delai_relance_jours": 7})
    assert detection["ok"] is True and detection["resultat"]["relances_publiees"] == [DEVIS_SANS_REPONSE], detection

    total = _drainer(deps, DEBUT + dt.timedelta(hours=2))
    assert total["quarantaines"] == 0, total
    return deps, lead_id


class TestAmontParLeVraiBus:
    def test_du_sms_au_paquet_de_l_affaire_par_les_charges_reelles_des_producteurs(self, affaire):
        _, lead_id = affaire

        assert _quarantaine_m10() == []
        publies = _ids_publies()
        assert sorted(publies) == sorted(TYPES)
        for type_evenement in TYPES:
            for evenement_id in publies[type_evenement]:
                recu = _recu_m10(evenement_id)
                assert recu["statut"] == "traite" and recu["resultat"]["memorise"] is True, (type_evenement, recu)
        types_ecrits = sorted(classification.type_evenement(m) for m in _maillons_m10())
        assert types_ecrits == sorted([*TYPES, etapes.TYPE_MONTANTS_DEVIS_ACCEPTE])

        with stockage.transaction():
            paquet_m3 = _paquet_m10(lead_id, LECTURE_LE, M3)
            paquet_m1 = _paquet_m10(lead_id, LECTURE_LE, M1)
            sans_agent = m10_outils.paquet_contexte_affaire(lead_id, LECTURE_LE)

        def sources(paquet):
            couche = next(c for c in paquet["couches"] if c["nom"] == "evenements_recents")
            return [(f["horodatage"], f["source"]) for f in couche["faits"]]

        # L'historique, plus récent d'abord, à l'heure de chaque ÉVÉNEMENT ; le client (CLIENT_PRIVATE) et les
        # montants (FINANCIAL) ne sortent pas vers M3 ; le client sort vers M1.
        assert sources(paquet_m3) == [
            (CONSTAT_LE, "m3.devis_sans_reponse"), (ACCEPTE_LE, "m3.devis_accepte"), (RECU_LE, "m1.lead_qualifie")]
        # M2 date l'association de l'heure de réception du lead : à instant égal, l'ordre d'arrivée fait foi.
        assert sources(paquet_m1) == [
            (CONSTAT_LE, "m3.devis_sans_reponse"), (ACCEPTE_LE, "m3.devis_accepte"),
            (RECU_LE, "m1.lead_qualifie"), (RECU_LE, "m2.client_associe")]
        assert paquet_m3["confidentialite"]["nb_retenus"] == 2 and paquet_m1["confidentialite"]["nb_retenus"] == 1
        for paquet in (paquet_m3, paquet_m1, sans_agent):
            texte = json.dumps(paquet, ensure_ascii=False)
            assert LECTURE_LE not in json.dumps([f for c in paquet["couches"] for f in c["faits"]])
            assert not [montant for montant in MONTANTS_DU_DEVIS if montant in texte], texte
        client_id = next(m["client_id"] for m in _maillons_m10() if "client_id" in m)
        assert len(client_id) == 64 and client_id in json.dumps(paquet_m1) and client_id not in json.dumps(paquet_m3)

    def test_le_prix_et_le_cout_reels_sont_classes_financial_et_le_numero_du_client_n_entre_pas(self, affaire):
        _, lead_id = affaire

        (montants,) = [m for m in _maillons_m10()
                       if classification.type_evenement(m) == etapes.TYPE_MONTANTS_DEVIS_ACCEPTE]
        assert montants["confidentialite"] == "FINANCIAL" and montants["devis_id"] == DEVIS_ACCEPTE
        assert (montants["prix_total"], montants["cout_total"], montants["taux_marge"]) == ("600.00", "480.00", "0.25")
        (etape,) = [m for m in _maillons_m10() if classification.type_evenement(m) == etapes.TYPE_DEVIS_ACCEPTE]
        assert etape["lead_id"] == lead_id and "prix_total" not in etape and "lignes" not in etape

        with stockage.transaction() as cnx:
            recus = json.dumps([dict(ligne) for ligne in cnx.execute(select(EVENEMENTS_RECUS)).mappings().all()
                                if ligne["consommateur"] == M10], default=str, ensure_ascii=False)
        tout_m10 = json.dumps([_maillons_m10("evenements"), _maillons_m10("affaires")], default=str, ensure_ascii=False)
        for confidence in (NUMERO, "5145550142", "514", "Laval", "gouttières fuient", "Gouttières 5po",
                           "Main d'oeuvre"):
            assert confidence not in tout_m10, confidence
            assert confidence not in recus, confidence

    def test_un_rejeu_du_bus_et_de_la_detection_ne_cree_rien_chez_m10(self, affaire):
        deps, _ = affaire
        avant = _maillons_m10()

        assert _drainer(deps, DEBUT + dt.timedelta(days=1))["livres"] == 0
        m3 = _outils(deps, M3)
        detection = executer_atomique(m3["m3_detecter_devis_sans_reponse"], {
            "horodatage_reference": CONSTAT_LE, "delai_relance_jours": 7})
        assert detection["ok"] is True
        assert _drainer(deps, DEBUT + dt.timedelta(days=1))["quarantaines"] == 0

        assert _maillons_m10() == avant

    def test_la_consolidation_et_l_audit_par_les_vrais_outils_couvrent_l_amont_reel(self, affaire):
        _, lead_id = affaire
        publies = _ids_publies()
        attendus = [
            {"type_evenement": "m1.lead_qualifie", "identifiant": lead_id},
            {"type_evenement": "m2.client_associe", "identifiant": lead_id},
            {"type_evenement": "m3.devis_accepte", "identifiant": DEVIS_ACCEPTE},
            {"type_evenement": "m3.devis_sans_reponse", "identifiant": DEVIS_SANS_REPONSE},
        ]
        assert sum(len(ids) for ids in publies.values()) == 4

        with stockage.transaction():
            rapport = m10_outils.auditer_non_oubli(attendus)
            jour_lead = m10_outils.consolider_affaire(lead_id, "2026-09-29", LECTURE_LE)
            jour_devis = m10_outils.consolider_affaire(lead_id, "2026-09-30", LECTURE_LE)
            jour_constat = m10_outils.consolider_affaire(lead_id, "2026-10-08", LECTURE_LE)
            encore = m10_outils.consolider_affaire(lead_id, "2026-09-30", LECTURE_LE)

        assert rapport["nb_oublis"] == 0 and rapport["total_attendus"] == 4
        assert rapport["chaine_evenements_intacte"] is True
        assert jour_lead["fait"]["resume"] == "1 lead(s) qualifié(s), 1 client(s) associé(s)"
        assert jour_devis["fait"]["resume"] == "1 devis accepté(s)"
        assert jour_constat["fait"]["resume"] == "1 devis sans réponse"
        assert encore["ecrit"] is False and encore["deja_consolide"] is True
        for consolide in (jour_lead, jour_devis, jour_constat):
            assert not [m for m in MONTANTS_DU_DEVIS if m in json.dumps(consolide["fait"], ensure_ascii=False)]

    def test_sans_le_consommateur_de_m10_l_audit_nomme_le_devis_dont_la_trace_manque(self, instance):
        """Le même trajet, mais le manifeste de M10 a perdu `m3.devis_accepte` : le bus publie, M10 ne reçoit pas."""
        deps = instance
        reel = deps[M10]
        sans_devis = {M10: dataclasses.replace(
            reel, evenements_consomme=tuple(t for t in reel.evenements_consomme if t != "m3.devis_accepte"))}
        capacites = Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
        lead_id = capacites.appeler("m1_recevoir_message_canal", SMS)["resultat"]["lead"]["lead_id"]
        _drainer(deps, DEBUT)  # M2 ingère le lead
        m3 = _outils(deps, M3)
        _creer_devis(m3, DEVIS_ACCEPTE, lead_id, "2026-09-29T15:00:00-04:00", "600.00")
        _ok(executer_atomique(m3["m3_marquer_devis_accepte"], {
            "devis_id": DEVIS_ACCEPTE, "approbateur": "Nathan Proprietaire (fictif, T3)", "horodatage": ACCEPTE_LE}))
        _drainer(sans_devis, DEBUT + dt.timedelta(hours=1))

        with stockage.transaction():
            rapport = m10_outils.auditer_non_oubli([
                {"type_evenement": "m1.lead_qualifie", "identifiant": lead_id},
                {"type_evenement": "m3.devis_accepte", "identifiant": DEVIS_ACCEPTE}])

        assert rapport["nb_oublis"] == 1
        assert rapport["oublis"][0]["type_evenement"] == "m3.devis_accepte"
        assert rapport["oublis"][0]["verdict"] == "REJ-AUDIT-TRACE-ABSENTE"
