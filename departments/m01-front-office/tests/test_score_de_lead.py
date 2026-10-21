"""PLAN T4.4 : le score de lead est calculé par des règles explicables, avec des poids lus du profil d'entreprise ; sans
poids, « poids à configurer » et aucun score ; il reste dans le registre de M1 et ne touche pas au contrat v2.

Poids et questions de la fixture FICTIVE (`fictif: true`). Registre en mémoire ; numéros en 555.
"""

from __future__ import annotations

import datetime as dt
import inspect
import json
import re
from decimal import Decimal

import pytest
from m1_front_office import contrats, score
from m1_front_office.outils import _obtenir_registre, recevoir_message_canal, reinitialiser_registre

from opsys import taxonomie

NUMERO = "+15145550142"
DEBUT = dt.datetime(2026, 9, 29, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
POIDS = {"urgence": 30, "completude": 50, "zone": 20}


def _a(minutes: float) -> str:
    return (DEBUT + dt.timedelta(minutes=minutes)).isoformat()


@pytest.fixture(autouse=True)
def _instance(declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    taxonomie.enregistrer_fenetre_conversation(30)
    reinitialiser_registre()
    yield
    reinitialiser_registre()


def _sms(texte: str, message_id: str, minutes: float = 0) -> dict:
    return recevoir_message_canal(
        canal="sms", expediteur=NUMERO, message_id=message_id, recu_le=_a(minutes), texte=texte)


def _points(bloc: dict) -> dict[str, str]:
    return {c["critere"]: c["points"] for c in bloc["criteres"]}


# -- Le calcul : exact, explicable, sans nombre flottant


@pytest.mark.parametrize(("urgence", "zone", "etablis", "attendus", "score_attendu", "points"), [
    (True, True, 3, 3, 100, {"urgence": "30.00", "completude": "50.00", "zone": "20.00"}),
    (False, True, 3, 4, 58, {"urgence": "0.00", "completude": "37.50", "zone": "20.00"}),  # 57,5 : demi vers le haut
    (False, False, 1, 3, 17, {"urgence": "0.00", "completude": "16.67", "zone": "0.00"}),
    (True, False, 0, 3, 30, {"urgence": "30.00", "completude": "0.00", "zone": "0.00"}),
    (False, False, 0, 3, 0, {"urgence": "0.00", "completude": "0.00", "zone": "0.00"}),
    (True, True, 5, 5, 100, {"urgence": "30.00", "completude": "50.00", "zone": "20.00"}),
])
def test_le_score_suit_les_poids_du_proprietaire_et_chaque_critere_rend_ses_points(
    urgence, zone, etablis, attendus, score_attendu, points
):
    bloc = score.calculer(urgence=urgence, zone=zone, elements_etablis=etablis, elements_attendus=attendus, poids=POIDS)
    assert bloc["statut"] == "calcule" and bloc["score"] == score_attendu and bloc["sur"] == 100
    assert _points(bloc) == points
    assert [c["critere"] for c in bloc["criteres"]] == list(taxonomie.CRITERES_SCORE_LEAD)
    assert [c["poids"] for c in bloc["criteres"]] == [30, 50, 20]
    assert all(c["constat"] for c in bloc["criteres"]), "chaque critère dit ce qui a été constaté"
    somme = sum(Decimal(c["points"]) for c in bloc["criteres"])
    assert abs(somme - score_attendu) <= Decimal("0.52"), "le score est la somme des points, arrondie"


def test_l_arrondi_est_demi_vers_le_haut_pas_a_l_entier_pair():
    """56,5 arrondi au pair donnerait 56 (`round`) ; la règle écrite est demi vers le haut : 57."""
    poids = {"urgence": 0, "completude": 1, "zone": 0}

    def seul(etablis: int, attendus: int) -> int:
        return score.calculer(
            urgence=False, zone=False, elements_etablis=etablis, elements_attendus=attendus, poids=poids)["score"]

    assert seul(113, 200) == 57
    assert seul(1, 200) == 1, "0,5 monte à 1"
    assert seul(1, 3) == 33


def test_un_poids_zero_ecarte_un_critere_et_les_poids_se_normalisent():
    bloc = score.calculer(urgence=True, zone=True, elements_etablis=1, elements_attendus=2,
                          poids={"urgence": 0, "completude": 1, "zone": 0})
    assert bloc["score"] == 50 and _points(bloc) == {"urgence": "0.00", "completude": "50.00", "zone": "0.00"}
    grands = score.calculer(urgence=True, zone=False, elements_etablis=3, elements_attendus=3,
                            poids={"urgence": 300, "completude": 500, "zone": 200})
    petits = score.calculer(urgence=True, zone=False, elements_etablis=3, elements_attendus=3, poids=POIDS)
    assert grands["score"] == petits["score"] == 80, "seuls les rapports entre poids comptent"


def test_les_valeurs_sont_des_fractions_exactes_lisibles():
    bloc = score.calculer(urgence=False, zone=True, elements_etablis=2, elements_attendus=5, poids=POIDS)
    assert [c["valeur"] for c in bloc["criteres"]] == ["0", "2/5", "1"]
    assert "arrondi" in bloc["regle"] and "demi vers le haut" in bloc["regle"]


def test_aucun_nombre_flottant_ni_round_dans_le_calcul():
    source = inspect.getsource(score)
    assert "round(" not in source and "float(" not in source


@pytest.mark.parametrize(("etablis", "attendus", "poids"), [
    (4, 3, POIDS), (-1, 3, POIDS), (0, 0, POIDS), (1, 3, {"urgence": 0, "completude": 0, "zone": 0}),
])
def test_des_entrees_incoherentes_sont_refusees_jamais_devinees(etablis, attendus, poids):
    with pytest.raises(ValueError):
        score.calculer(urgence=False, zone=False, elements_etablis=etablis, elements_attendus=attendus, poids=poids)


def test_les_criteres_du_code_sont_ceux_que_le_profil_pese():
    bloc = score.calculer(urgence=False, zone=False, elements_etablis=0, elements_attendus=3, poids=POIDS)
    assert {c["critere"] for c in bloc["criteres"]} == set(taxonomie.CRITERES_SCORE_LEAD)


def test_sans_poids_le_score_n_existe_pas_et_le_verdict_dit_a_configurer():
    verdict = taxonomie.charger_poids_score_lead()[1]
    bloc = score.sans_poids(verdict)
    assert bloc["statut"] == "poids_a_configurer" and "score" not in bloc and "criteres" not in bloc
    assert bloc["verdict"]["code"] == "REJ-POIDS-SCORE-NON-CONFIGURES"
    assert bloc["verdict"]["detail"].startswith("poids à configurer")
    invalide = score.sans_poids({"code": "REJ-PROFIL-INVALIDE", "detail": "x"})
    assert invalide["statut"] == "profil_invalide" and "score" not in invalide


def test_le_module_ne_porte_aucun_poids_par_defaut():
    source = inspect.getsource(score)
    assert re.search(r"[\"'](urgence|completude|zone)[\"']\s*:\s*\d", source) is None, "un poids écrit dans le code"


# -- Dans la conversation : lu du profil, dit le pourquoi, jamais sans poids


def test_sans_poids_dans_le_profil_la_reponse_dit_poids_a_configurer_et_ne_donne_aucun_score(declarer_qualification):
    declarer_qualification(poids=False)
    reponse = _sms("Mes gouttières fuient.", "SM-1", 0)
    assert reponse["score"]["statut"] == "poids_a_configurer" and "score" not in reponse["score"]
    assert reponse["score"]["verdict"]["code"] == "REJ-POIDS-SCORE-NON-CONFIGURES"
    assert "poids à configurer" in reponse["score"]["verdict"]["detail"]
    assert str(taxonomie.fichier_profil()) in reponse["score"]["verdict"]["detail"]
    ligne = _obtenir_registre().lire()[-1]
    assert ligne["type_entree"] == "suivi_conversation" and ligne["score"]["statut"] == "poids_a_configurer"


def test_des_poids_invalides_ne_bloquent_pas_la_reception_et_ne_sont_pas_lus_comme_a_configurer():
    fichier = taxonomie.fichier_profil()
    fichier.write_text(fichier.read_text(encoding="utf-8") + "poids_score_lead: {urgence: 1}\n", encoding="utf-8")
    reponse = _sms("Mes gouttières fuient à Laval.", "SM-1", 0)
    assert reponse["decision"] == "TRANSMETTRE_M2"
    assert reponse["score"]["statut"] == "profil_invalide"
    assert reponse["score"]["verdict"]["code"] == "REJ-PROFIL-INVALIDE"
    assert "poids manquants" in reponse["score"]["verdict"]["detail"]
    assert taxonomie.verifier_profil() != []


def test_le_score_suit_la_conversation_message_apres_message(declarer_qualification):
    declarer_qualification()
    # Service et contact connus, ville manquante : 2 éléments sur 5 (service, contact ; 0 des 2 questions).
    premier = _sms("Mes gouttières fuient.", "SM-1", 0)
    assert premier["score"]["score"] == 20 and _points(premier["score"]) == {
        "urgence": "0.00", "completude": "20.00", "zone": "0.00"}

    # Le lead naît : 3 éléments sur 5, la ville de la zone est reconnue.
    lead = _sms("À Laval.", "SM-2", 3)
    assert lead["decision"] == "TRANSMETTRE_M2"
    assert lead["score"]["score"] == 50 and _points(lead["score"]) == {
        "urgence": "0.00", "completude": "30.00", "zone": "20.00"}

    # Après le lead : l'urgence et une réponse comptent, le lead transmis ne change pas.
    urgent = _sms("C'est urgent! Environ 40 pieds.", "SM-3", 5)
    assert urgent["decision"] == "CONVERSATION_DEJA_QUALIFIEE" and urgent["lead"] == lead["lead"]
    assert urgent["score"]["score"] == 90 and _points(urgent["score"]) == {
        "urgence": "30.00", "completude": "40.00", "zone": "20.00"}

    fini = _sms("Deux étages.", "SM-4", 7)
    assert fini["score"]["score"] == 100 and _points(fini["score"])["completude"] == "50.00"


def test_les_poids_sont_lus_du_profil_a_chaque_message(declarer_qualification):
    declarer_qualification()
    assert _sms("Mes gouttières fuient à Laval.", "SM-1", 0)["score"]["score"] == 50
    taxonomie.enregistrer_poids_score_lead({"urgence": 100, "completude": 0, "zone": 0})
    autre = _sms("Merci!", "SM-2", 2)
    assert autre["score"]["score"] == 0, "aucune urgence, et seule l'urgence pèse"
    urgent = _sms("C'est urgent!", "SM-3", 3)
    assert urgent["score"]["score"] == 100 and _points(urgent["score"])["completude"] == "0.00"


def test_le_score_explique_chaque_critere_avec_ce_qui_a_ete_constate(declarer_qualification):
    declarer_qualification()
    bloc = _sms("Mes gouttières fuient, c'est urgent, à Laval.", "SM-1", 0)["score"]
    constats = {c["critere"]: c["constat"] for c in bloc["criteres"]}
    assert constats["urgence"] == "urgence explicite déclarée dans la conversation"
    assert constats["zone"] == "une ville de la zone desservie est reconnue"
    assert constats["completude"] == "3 éléments établis sur 5 (champs du lead et questions du service)"
    sans = _sms("Mes gouttières fuient à Québec.", "SM-9", 120)["score"]
    assert {c["critere"]: c["constat"] for c in sans["criteres"]}["urgence"] == (
        "aucune urgence explicite déclarée (jamais inférée du ton)")


def test_sans_questions_le_score_ne_compte_que_les_champs_du_lead(declarer_qualification):
    declarer_qualification(questions=False)
    bloc = _sms("Mes gouttières fuient à Laval.", "SM-1", 0)["score"]
    assert bloc["score"] == 70 and _points(bloc)["completude"] == "50.00", "3 champs sur 3, aucune question inventée"
    assert next(c for c in bloc["criteres"] if c["critere"] == "completude")["constat"].startswith("3 éléments")


# -- Le score reste dans le registre de M1 : le contrat v2 et le bus n'en savent rien


def test_le_score_est_au_registre_de_m1_et_pas_dans_le_lead(declarer_qualification):
    declarer_qualification()
    _sms("Mes gouttières fuient.", "SM-1", 0)
    reponse = _sms("À Laval.", "SM-2", 3)
    lead = reponse["lead"]
    assert "score" not in lead and set(lead) <= {
        "schema_version", "lead_id", "service", "ville", "urgence_declaree", "canal", "conversation_id", "contact",
        "source", "utm", "campagne"}
    contrats.valider_lead(lead)
    lignes = [ligne for ligne in _obtenir_registre().lire() if ligne["type_entree"] == "suivi_conversation"]
    assert [ligne["score"]["score"] for ligne in lignes] == [20, 50], "une ligne de score par message"
    assert lignes[-1]["score"] == reponse["score"] and lignes[-1]["lead_id"] == lead["lead_id"]
    (ligne_lead,) = [ligne for ligne in _obtenir_registre().lire() if ligne["type_entree"] == "lead_emis"]
    assert "score" not in ligne_lead and "score" not in json.dumps(ligne_lead["lead"])
    assert _obtenir_registre().valider_chaine() == (True, None)
