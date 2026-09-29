"""PLAN T4.18-b — l'opportunité que M2 ouvre pour un client qui revient a un paquet chez M10, par le VRAI bus.

Le trajet, sans réseau ni core (le core ne s'exécute pas ici), sur les VRAIS départements et les VRAIS producteurs :

    SMS du client -> `m1_recevoir_message_canal` (vrai M1) -> lead qualifié -> M2 l'ingère
    -> M2 qualifie, M3 crée un devis, un humain l'accepte (T3) -> le lead est converti
    -> `m4.travaux_termines` (premier chantier) : M2 mène le lead jusqu'à la facture
    -> un DEUXIÈME `m4.travaux_termines` pour le même lead : son cycle est fini, M2 ouvre `<lead>~opp~<wct_id>`
       pour le même client et publie `m2.client_associe` avec cet identifiant
    -> M10 le garde, et le paquet de contexte de l'opportunité existe : connue, origine reçue (le client associé de
       M2), sans mélanger son histoire avec celle du lead d'origine.

Ce test fait ce que les charges fictives de `departments/m10-memoire/tests/` ne peuvent pas : prouver, avec
l'identifiant que M2 fabrique vraiment (un lead venu d'un SMS de 64 caractères, un `wct_id` de 64 caractères : 133
caractères et un tilde), que M10 le garde, que le paquet s'assemble, et que la forme d'affaire du core (le texte de
`AFFAIRE_ID`) l'admet.
Avant T4.18-b le core refusait cet identifiant (64 caractères au plus, aucun tilde) et le reçu de M10 disait, à tort,
que l'origine de l'opportunité n'était jamais reçue. Données fictives (`fictif: true` : numéro, personnes, montants).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import pytest
from m1_front_office import outils as m1_outils
from m2_revenue_crm import outils as m2_outils
from m10_memoire import affaire, amont, classification, etapes
from m10_memoire import outils as m10_outils
from sqlalchemy import select

from opsys import evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import Departement, charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS

FICTIF = True  # aucune donnée réelle : un numéro, des personnes, des montants et des empreintes de test
RACINE = Path(__file__).resolve().parents[1]
DEBUT = dt.datetime(2026, 9, 29, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
NUMERO = "+15145550142"
SMS = {
    "canal": "sms", "expediteur": NUMERO, "message_id": "SMfictif0418b", "recu_le": "2026-09-29T09:15:00-04:00",
    "texte": "Bonjour, mes gouttières fuient à Laval, c'est urgent.",
}
M2, M3, M10 = "m02-revenue-crm", "m03-estimation", "m10-memoire"
DEVIS = "DEVIS-T418B-A"
PREMIER_CHANTIER = "2026-10-05T14:00:00-04:00"
CHANTIER_SUIVANT = "2026-10-20T14:00:00-04:00"
LECTURE_LE = "2026-10-21T07:00:00-04:00"
# Un `wct_id` de M4 est une empreinte de 64 caractères (`m4_field_ops.outbox`) : on en fabrique deux, fictives.
WCT_1 = hashlib.sha256(b"fictif-t418b-wct-1").hexdigest()
WCT_2 = hashlib.sha256(b"fictif-t418b-wct-2").hexdigest()


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


def _maillons_m10() -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(M10, "evenements"))


def _wct(lead_id: str, wct_id: str, horodatage: str) -> dict:
    """Un `m4.travaux_termines` conforme au catalogue, tel que M4 le publie (fictif)."""
    return {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id[:12]}", "lead_id": lead_id,
        "technicien_id": "tech-fictif-1", "horodatage_completion": horodatage,
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2}, "duree_reelle_minutes": 90,
        "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M2", "M10"], "devis_id": DEVIS, "statut": "completed_verified",
    }


@pytest.fixture
def client_qui_revient(instance):
    """Rend `(départements, lead_id, opportunité)` : le premier chantier est terminé et facturé, le suivant ouvre
    l'opportunité chez M2. Le bus est livré sur TOUS les départements jusqu'au devis accepté, puis sur M2 et M10
    seulement pour les deux fins de travaux (les autres consommateurs de M4 n'ont rien à faire de ce scénario)."""
    deps = instance
    capacites = Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    reponse = capacites.appeler("m1_recevoir_message_canal", SMS)
    assert reponse["ok"] is True and reponse["resultat"]["decision"] == "TRANSMETTRE_M2", reponse
    lead_id = reponse["resultat"]["lead"]["lead_id"]
    assert _drainer(deps, DEBUT)["quarantaines"] == 0

    m2, m3 = _outils(deps, M2), _outils(deps, M3)
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": "2026-09-29T11:00:00-04:00",
        "owner": "Alice Vendeuse (fictif)",
        "prochaine_action": {
            "description": "Préparer la soumission (fictif)", "echeance": "2026-10-02T09:00:00-04:00"}}))
    _ok(executer_atomique(m3["m3_creer_devis"], {
        "devis_id": DEVIS, "lead_id": lead_id, "chantier_id": None,
        "lignes": [
            {"description": "Gouttières 5po aluminium (fictif)", "quantite": "40", "unite": "pi",
             "cout_unitaire": "8.00", "reference_besoin_materiau": "gouttiere-alu-5po-fictif"},
            {"description": "Main d'oeuvre installation (fictif)", "quantite": "1", "unite": "forfait",
             "cout_unitaire": "160.00", "reference_besoin_materiau": None},
        ],
        "taux_marge": "0.25", "horodatage": "2026-09-29T15:00:00-04:00", "prix_total": "600.00"}))
    _ok(executer_atomique(m3["m3_marquer_devis_accepte"], {
        "devis_id": DEVIS, "approbateur": "Nathan Proprietaire (fictif, T3)",
        "horodatage": "2026-09-30T10:00:00-04:00"}))
    assert _drainer(deps, DEBUT + dt.timedelta(hours=2))["quarantaines"] == 0

    seulement_m2_et_m10 = {M2: deps[M2], M10: deps[M10]}
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(lead_id, WCT_1, PREMIER_CHANTIER))
    premier = _drainer(seulement_m2_et_m10, dt.datetime(2026, 10, 5, 15, 0, tzinfo=dt.UTC))
    assert premier["echecs"] == 0 and premier["quarantaines"] == 0, premier
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(lead_id, WCT_2, CHANTIER_SUIVANT))
    suivant = _drainer(seulement_m2_et_m10, dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC))
    assert suivant["echecs"] == 0 and suivant["quarantaines"] == 0, suivant
    return deps, lead_id, f"{lead_id}~opp~{WCT_2}"


class TestOpportuniteParLeVraiBus:
    def test_m2_ouvre_l_opportunite_pour_le_meme_client_et_m10_la_garde(self, client_qui_revient):
        _, lead_id, opportunite = client_qui_revient

        client_du_lead = m2_outils.trouver_client_de_lead(lead_id)["resultat"]["client_id"]
        assert m2_outils.trouver_client_de_lead(opportunite)["resultat"]["client_id"] == client_du_lead
        assert len(opportunite) == 64 + len("~opp~") + 64 and affaire.est_opportunite(opportunite)
        associations = [m for m in _maillons_m10()
                        if classification.type_evenement(m) == etapes.TYPE_CLIENT_ASSOCIE]
        assert sorted(m["lead_id"] for m in associations) == sorted([lead_id, opportunite])
        assert all(m["client_id"] == client_du_lead and m["confidentialite"] == "CLIENT_PRIVATE"
                   for m in associations)

    def test_le_reçu_de_m10_dit_l_origine_de_l_opportunite_recue_et_plus_jamais_manquante(self, client_qui_revient):
        _, _, opportunite = client_qui_revient

        recu = _recu_m10(f"m2-client-associe-{opportunite}")

        assert recu["statut"] == "traite" and recu["resultat"]["memorise"] is True
        assert recu["resultat"]["lead_id"] == opportunite
        # Avant T4.18-b : `origine_recue: False` et `AMONT-ORIGINE-NON-RECUE` pour toute opportunité, à jamais.
        assert recu["resultat"]["origine_recue"] is True and recu["resultat"]["verdict"] is None
        assert [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == M10] == []

    def test_le_paquet_de_l_opportunite_existe_connue_avec_son_origine_recue(self, client_qui_revient):
        _, _, opportunite = client_qui_revient

        with stockage.transaction():
            pour_m1 = m10_outils.paquet_contexte_affaire(opportunite, LECTURE_LE, "m01-front-office")
            pour_m3 = m10_outils.paquet_contexte_affaire(opportunite, LECTURE_LE, "m03-estimation")

        for paquet in (pour_m1, pour_m3):
            assert paquet["affaire_id"] == opportunite
            assert paquet["affaire"] == {
                "connue": True, "origine_recue": True, "origine": etapes.TYPE_CLIENT_ASSOCIE, "verdict": None}
            assert paquet["consolidation"] == {"a_consolider": [], "nb_a_consolider": 0}
        evenements_m1 = next(c for c in pour_m1["couches"] if c["nom"] == "evenements_recents")
        evenements_m3 = next(c for c in pour_m3["couches"] if c["nom"] == "evenements_recents")
        assert [f["source"] for f in evenements_m1["faits"]] == ["m2.client_associe"]  # M1 voit le client associé
        assert evenements_m3["vide"] is True and pour_m3["confidentialite"]["nb_retenus"] == 1  # M3 ne le voit pas
        # ... mais le bloc de l'affaire, lui, ne dépend ni de la vue ni de la troncature.

    def test_l_histoire_de_l_opportunite_et_celle_du_lead_d_origine_ne_se_melangent_pas(self, client_qui_revient):
        _, lead_id, opportunite = client_qui_revient

        with stockage.transaction():
            du_lead = m10_outils.paquet_contexte_affaire(lead_id, LECTURE_LE, "m01-front-office")
            de_l_opportunite = m10_outils.paquet_contexte_affaire(opportunite, LECTURE_LE, "m01-front-office")

        assert du_lead["affaire"]["origine"] == etapes.TYPE_LEAD_QUALIFIE
        assert de_l_opportunite["affaire"]["origine"] == etapes.TYPE_CLIENT_ASSOCIE

        def sources(paquet):
            couche = next(c for c in paquet["couches"] if c["nom"] == "evenements_recents")
            return {(f["source"], f["identifiant"]) for f in couche["faits"]}

        assert (etapes.TYPE_CLIENT_ASSOCIE, opportunite) not in sources(du_lead)
        assert sources(de_l_opportunite) == {(etapes.TYPE_CLIENT_ASSOCIE, opportunite)}

    def test_avec_de_vrais_identifiants_l_origine_du_lead_sort_de_la_couche_et_le_paquet_le_dit_quand_meme(
        self, client_qui_revient
    ):
        """Cinq faits, des identifiants de 64 caractères : trois tiennent dans les 1 000 caractères de la couche. Le
        lead qualifié, le plus ancien, est omis, mais le bloc `affaire` en garde l'origine, et `consolidation` dit le
        jour (celui du lead et du client, le 29) qu'aucun fait durable ne résume. Consolider ce jour vide la liste."""
        _, lead_id, _ = client_qui_revient

        with stockage.transaction():
            avant = m10_outils.paquet_contexte_affaire(lead_id, LECTURE_LE, "m01-front-office")
        couche = next(c for c in avant["couches"] if c["nom"] == "evenements_recents")
        assert couche["nb_total"] == 5 and couche["nb_inclus"] == 3 and couche["nb_omis"] == 2
        assert etapes.TYPE_LEAD_QUALIFIE not in {fait["source"] for fait in couche["faits"]}
        assert avant["affaire"] == {
            "connue": True, "origine_recue": True, "origine": etapes.TYPE_LEAD_QUALIFIE, "verdict": None}
        assert avant["consolidation"] == {
            "a_consolider": [{"affaire_id": lead_id, "jour": "2026-09-29"}], "nb_a_consolider": 1}

        entree = avant["consolidation"]["a_consolider"][0]
        with stockage.transaction():
            fait = m10_outils.consolider_affaire(entree["affaire_id"], entree["jour"], LECTURE_LE)
            apres = m10_outils.paquet_contexte_affaire(lead_id, LECTURE_LE, "m01-front-office")
        assert fait["ecrit"] is True and fait["fait"]["resume"] == "1 lead(s) qualifié(s), 1 client(s) associé(s)"
        assert apres["consolidation"] == {"a_consolider": [], "nb_a_consolider": 0}

    def test_un_lead_qui_n_a_jamais_ete_vu_est_dit_inconnu_par_les_vrais_outils(self, client_qui_revient):
        _, lead_id, _ = client_qui_revient
        inconnu = f"{lead_id}~opp~{hashlib.sha256(b'jamais-vu').hexdigest()}"

        with stockage.transaction():
            paquet = m10_outils.paquet_contexte_affaire(inconnu, LECTURE_LE, "m03-estimation")

        assert paquet["affaire"] == {
            "connue": False, "origine_recue": False, "origine": None, "verdict": amont.AMONT_AFFAIRE_INCONNUE}
        assert all(couche["vide"] for couche in paquet["couches"])

    def test_le_texte_du_motif_du_core_admet_l_identifiant_que_m2_a_fabrique(self, client_qui_revient):
        _, lead_id, opportunite = client_qui_revient
        core = (RACINE / "core" / "src" / "context-engine" / "opsys-contexte-paquet.ts").read_text(encoding="utf-8")
        identifiant = re.search(r"AFFAIRE_ID = /(.*?)/u;", core)
        ligne = re.search(r"AFFAIRE_LINE =\s*/(.*?)/gmu;", core)
        assert identifiant is not None and ligne is not None

        assert re.fullmatch(identifiant.group(1), opportunite)
        assert re.fullmatch(identifiant.group(1), lead_id)
        assert re.fullmatch(ligne.group(1), f"affaire_id: {opportunite}")

    def test_aucune_donnee_du_client_n_entre_dans_les_blocs_de_l_affaire(self, client_qui_revient):
        _, _, opportunite = client_qui_revient

        with stockage.transaction():
            paquet = m10_outils.paquet_contexte_affaire(opportunite, LECTURE_LE, "m01-front-office")

        blocs = json.dumps([paquet["affaire"], paquet["consolidation"]], ensure_ascii=False)
        for confidence in (NUMERO, "5145550142", "Laval", "gouttières fuient", "Alice", "Nathan"):
            assert confidence not in blocs, confidence
        client_id = next(m["client_id"] for m in _maillons_m10() if "client_id" in m)
        assert client_id not in blocs
