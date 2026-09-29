"""PLAN T2.1-b — un client qui écrit le service, puis la ville, donne UN lead que M2 reçoit par le vrai bus.

Même trajet que `test_canal_sms_bout_en_bout.py`, sans réseau ni core (le core ne s'exécute pas ici), mais avec une
conversation de plusieurs messages :

    messages reçus par le canal (champs que la plateforme donne à l'agent)
      -> `Capacites.appeler("m1_recevoir_message_canal")`   (vrai manifeste de M1, mode ombre, N2 : sans approbation)
      -> M1 rassemble les messages de la conversation dans la fenêtre du profil d'entreprise, par du code
      -> un seul lead, au message qui complète service et ville ; événement `m1.lead_qualifie` (même transaction)
      -> `evenements.repartir` (vrai répartiteur) -> M2 (vrai manifeste : `consommateurs()["m1.lead_qualifie"]`)

Ce qui est demandé au client reste un brouillon : il ne part que par `m1_emettre_notification` (N4), après
l'approbation d'une personne (`approbations.decider`). Données fictives (numéros en 555, personnes de test).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml
from m1_front_office import outils as m1
from m2_revenue_crm import outils as m2
from sqlalchemy import func, select

from opsys import approbations, evenements, identite, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

DEBUT = dt.datetime(2026, 9, 29, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
NUMERO = "+15145550142"
PROFIL_FICTIF = (
    Path(__file__).resolve().parents[1]
    / "departments" / "m01-front-office" / "fixtures" / "qualification" / "profil-fictif.v1.yaml"
)


def _declarer_qualification(*, poids: bool = True) -> None:
    """Questions et poids FICTIFS de la fixture, écrits dans le profil de l'instance comme le ferait Nathan."""
    donnees = yaml.safe_load(PROFIL_FICTIF.read_text(encoding="utf-8"))
    assert donnees["fictif"] is True
    taxonomie.enregistrer_questions_qualification(donnees["questions_qualification"], par="nathan")
    if poids:
        taxonomie.enregistrer_poids_score_lead(donnees["poids_score_lead"], par="nathan")


def _sms(texte: str, message_id: str, minutes: float = 0) -> dict:
    return {
        "canal": "sms", "expediteur": NUMERO, "message_id": message_id,
        "recu_le": (DEBUT + dt.timedelta(minutes=minutes)).isoformat(), "texte": texte,
    }


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    """Base migrée, profil d'entreprise SANS fenêtre (chaque test la déclare, ou non), M1 et M2 durables."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    m1.utiliser_stockage_durable()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
    deps = charger_departements()
    yield deps, Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    m1.reinitialiser_registre()
    m2.reinitialiser_registre()
    stockage.liberer()


def _drainer(deps, *, max_tours: int = 10) -> dict[str, int]:
    """Livre le bus jusqu'à quiescence, sur TOUS les départements (boucle bornée, 90 s entre deux tours)."""
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(max_tours):
        resume = evenements.repartir(deps, maintenant=(DEBUT + dt.timedelta(hours=3, seconds=90 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence : {total}")


def _maillons_m2() -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons("m02-revenue-crm", "principal"))


def _leads_ingeres() -> list[dict]:
    return [m for m in _maillons_m2() if m.get("type_entree") == "lead_ingere"]


def _evenements_publies() -> int:
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie")).scalar_one()


def _recu(evenement_id: str) -> dict | None:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id)
            & (EVENEMENTS_RECUS.c.consommateur == "m02-revenue-crm")
        )).mappings().first()
    return None if ligne is None else dict(ligne)


def _livraisons_a_m2() -> int:
    """Nombre de livraisons de `m1.lead_qualifie` à M2 (les autres consommateurs du bus, M5 par exemple, reçoivent
    `m2.client_associe` que M2 publie à son tour : ils ne comptent pas ici)."""
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.consommateur == "m02-revenue-crm")).scalar_one()


def _en_attente() -> list[dict]:
    with stockage.transaction() as cnx:
        return approbations.lister(cnx, "en_attente")


# -- La conversation en deux messages : un seul lead, ingéré une fois par M2 ----------------------------------------


def test_une_conversation_en_deux_messages_donne_un_lead_que_m2_ingere_une_fois(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)

    premier = capacites.appeler("m1_recevoir_message_canal", _sms("Bonjour, mes gouttières fuient.", "SM-1", 0))
    assert premier["ok"] is True and "statut" not in premier, "recevoir un message n'attend aucune approbation"
    assert premier["resultat"]["decision"] == "DEMANDER_PRECISIONS" and premier["resultat"]["a_demander"] == ["ville"]
    assert _evenements_publies() == 0 and _drainer(deps)["livres"] == 0, "rien n'arrive à M2 tant que la ville manque"

    second = capacites.appeler("m1_recevoir_message_canal", _sms("Je suis à Laval.", "SM-2", 4))
    assert second["ok"] is True and second["resultat"]["decision"] == "TRANSMETTRE_M2"
    lead = second["resultat"]["lead"]
    assert second["resultat"]["conversation"]["signaux"] == ["sms:SM-1", "sms:SM-2"]
    assert _evenements_publies() == 1

    resume = _drainer(deps)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert _livraisons_a_m2() == 1
    (ingere,) = _leads_ingeres()
    assert ingere["contrat"] == lead and ingere["lead_id"] == lead["lead_id"]
    assert (lead["service"], lead["ville"], lead["source"], lead["contact"]) == (
        "gouttieres", "Laval", "sms", {"telephone": NUMERO})
    recu = _recu(f"m1-lead-qualifie-{lead['lead_id']}")
    assert recu["statut"] == "traite" and codec.decoder(recu["resultat"])["client_id"]
    assert evenements.etat()["quarantaine"] == []


def test_un_message_de_plus_dans_la_fenetre_ne_cree_ni_second_lead_ni_second_evenement(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient.", "SM-1", 0))
    capacites.appeler("m1_recevoir_message_canal", _sms("À Laval.", "SM-2", 4))
    _drainer(deps)

    merci = capacites.appeler("m1_recevoir_message_canal", _sms("Merci, c'est urgent!", "SM-3", 6))
    assert merci["resultat"]["decision"] == "CONVERSATION_DEJA_QUALIFIEE"
    assert merci["resultat"]["complement"]["urgence_declaree"] is True
    assert _evenements_publies() == 1 and _drainer(deps)["livres"] == 0
    assert len(_leads_ingeres()) == 1


# -- Le rejeu -------------------------------------------------------------------------------------------------------


def test_le_rejeu_des_messages_ne_donne_ni_second_lead_ni_seconde_livraison_ni_seconde_opportunite(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    messages = [_sms("Mes gouttières fuient.", "SM-1", 0), _sms("À Laval.", "SM-2", 4)]
    premiers = [capacites.appeler("m1_recevoir_message_canal", m)["resultat"] for m in messages]
    _drainer(deps)
    avant = _maillons_m2()

    for message, premiere in zip(messages, premiers, strict=True):
        rejoue = capacites.appeler("m1_recevoir_message_canal", message)["resultat"]
        assert rejoue["doublon"] is True and rejoue["decision"] == premiere["decision"]
    assert _evenements_publies() == 1
    assert _drainer(deps)["livres"] == 0
    assert _maillons_m2() == avant and len(_leads_ingeres()) == 1
    assert _livraisons_a_m2() == 1, "une seule livraison à M2, jamais rejouée"


def test_un_message_rejoue_au_milieu_ne_compte_pas_deux_fois_dans_le_lead(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    for _ in range(3):
        capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient.", "SM-1", 0))
    lead = capacites.appeler("m1_recevoir_message_canal", _sms("À Laval.", "SM-2", 4))["resultat"]
    assert lead["conversation"]["messages"] == 2
    _drainer(deps)
    assert len(_leads_ingeres()) == 1


# -- STOP au milieu d'une conversation ------------------------------------------------------------------------------


def test_stop_au_milieu_d_une_conversation_ne_qualifie_jamais_et_ne_cree_rien_chez_m2(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient.", "SM-1", 0))
    stop = capacites.appeler("m1_recevoir_message_canal", _sms("STOP", "SM-STOP", 2))["resultat"]
    assert stop["decision"] == "RETRAIT_CONSENTEMENT" and stop["conversation"]["messages_non_qualifies"] == 1
    suite = capacites.appeler("m1_recevoir_message_canal", _sms("À Laval.", "SM-2", 4))["resultat"]
    assert suite["qualifie"] is False and suite["brouillon_reponse"] is None
    assert suite["sans_brouillon"] == "retrait_consentement"

    assert _evenements_publies() == 0 and _drainer(deps)["livres"] == 0
    assert _maillons_m2() == []
    assert _en_attente() == [], "un retrait ne demande aucune approbation et ne propose aucun message"


# -- Fenêtre expirée ------------------------------------------------------------------------------------------------


def test_une_fenetre_expiree_ne_donne_pas_de_lead_et_m2_ne_recoit_rien(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient.", "SM-1", 0))
    tard = capacites.appeler("m1_recevoir_message_canal", _sms("À Laval.", "SM-2", 120))["resultat"]
    assert tard["qualifie"] is False and tard["conversation"]["hors_fenetre"] == 1
    assert _evenements_publies() == 0 and _drainer(deps)["livres"] == 0 and _maillons_m2() == []
    with stockage.transaction():
        signaux = [m for m in m1._obtenir_registre().lire() if m["type_entree"] == "signal"]
    assert [s["signal_id"] for s in signaux] == ["sms:SM-1", "sms:SM-2"], "aucun message n'est perdu"


# -- Paramètre absent : le comportement d'avant, et le verdict le dit -----------------------------------------------


def test_sans_fenetre_declaree_chaque_message_est_qualifie_seul_et_le_verdict_le_dit(instance):
    deps, capacites = instance
    premier = capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient.", "SM-1", 0))["resultat"]
    second = capacites.appeler("m1_recevoir_message_canal", _sms("À Laval.", "SM-2", 4))["resultat"]
    for reponse in (premier, second):
        assert reponse["qualifie"] is False and reponse["conversation"]["mode"] == "message_par_message"
        assert reponse["conversation"]["verdict"]["code"] == "REJ-FENETRE-NON-CONFIGUREE"
        assert "brouillon_reponse" not in reponse
    assert _evenements_publies() == 0 and _drainer(deps)["livres"] == 0 and _maillons_m2() == []

    complet = capacites.appeler("m1_recevoir_message_canal", _sms("Gouttières à Laval.", "SM-3", 5))["resultat"]
    assert complet["decision"] == "TRANSMETTRE_M2"
    assert _drainer(deps)["echecs"] == 0 and _livraisons_a_m2() == 1 and len(_leads_ingeres()) == 1


# -- Refus par M2 : réessais puis quarantaine -----------------------------------------------------------------------


def test_un_lead_que_m2_refuse_est_reessaye_puis_mis_en_quarantaine_sans_rien_ecrire_chez_m2(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient.", "SM-1", 0))
    lead = capacites.appeler("m1_recevoir_message_canal", _sms("À Laval.", "SM-2", 4))["resultat"]["lead"]
    assert _evenements_publies() == 1
    taxonomie.enregistrer_services(["reparation"])  # entre la qualification et la livraison, « gouttieres » est retiré

    resume = _drainer(deps)
    assert resume["traites"] == 0 and resume["echecs"] == 4 and resume["quarantaines"] == 1, resume
    assert _maillons_m2() == []
    (ligne,) = [q for q in evenements.etat()["quarantaine"] if q["consommateur"] == "m02-revenue-crm"]
    assert ligne["evenement_id"] == f"m1-lead-qualifie-{lead['lead_id']}" and ligne["tentatives"] == 5
    assert "LeadRefuse" in ligne["derniere_erreur"] and "REJ-SERVICE-INCONNU" in ligne["derniere_erreur"]
    assert _recu(ligne["evenement_id"])["statut"] == "quarantaine"


# -- Ce qui est demandé au client reste un brouillon soumis à l'approbation N4 --------------------------------------


def test_la_question_au_client_est_un_brouillon_qui_ne_part_qu_apres_l_approbation_d_une_personne(
    instance, monkeypatch
):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    envois: list[tuple[str, str]] = []

    class BusEspion:
        def emettre(self, canal, message):
            envois.append((canal, message))
            return "id-espion"

    monkeypatch.setattr(m1.adaptateurs, "creer_bus", lambda mode_ombre=True: BusEspion())

    reponse = capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient.", "SM-1", 0))["resultat"]
    brouillon = reponse["brouillon_reponse"]
    assert brouillon and reponse["envoye"] is False
    assert envois == [] and _en_attente() == [], "la réception ne demande rien à personne et n'envoie rien"

    # Le brouillon passe le garde-fou des interdits (aucun prix, aucune date, aucun engagement, aucun aveu)...
    verifie = capacites.appeler("m1_verifier_garde_fou", {"texte": brouillon})
    assert verifie["ok"] is True and verifie["resultat"]["code"] == "OK"

    # ... puis il est PROPOSÉ à l'envoi : N4, en attente d'une personne. Rien ne part avant sa décision.
    proposition = capacites.appeler("m1_emettre_notification", {"canal": "sms", "message": brouillon})
    assert proposition["statut"] == "en_attente_approbation", proposition
    (demande,) = _en_attente()
    assert (demande["outil"], demande["niveau"], demande["departement"]) == (
        "m1_emettre_notification", "N4", "m01-front-office")
    assert envois == []

    with stockage.transaction() as cnx:
        approbations.decider(cnx, proposition["demande_id"], True, "nathan",
                             outils_executables(capacites.departements, stockage.transaction), capacites.departements)
    assert envois == [("sms", brouillon)]
    assert _en_attente() == []


# -- Trois SMS, un lead, des questions du profil en brouillon ---------------------------------------------------------


def test_trois_sms_donnent_un_lead_v2_complet_et_les_questions_du_profil_restent_un_brouillon(instance, monkeypatch):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    _declarer_qualification()
    envois: list[tuple[str, str]] = []

    class BusEspion:
        def emettre(self, canal, message):
            envois.append((canal, message))
            return "id-espion"

    monkeypatch.setattr(m1.adaptateurs, "creer_bus", lambda mode_ombre=True: BusEspion())

    premier = capacites.appeler("m1_recevoir_message_canal", _sms("Bonjour, j'ai un problème chez moi.", "SM-1", 0))
    assert premier["resultat"]["champs_manquants"] == ["service", "ville"]
    second = capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières débordent, c'est urgent.", "SM-2", 2))
    assert second["resultat"]["champs_manquants"] == ["ville"] and second["resultat"]["a_demander"] == ["ville"]
    assert _evenements_publies() == 0 and _drainer(deps)["livres"] == 0

    troisieme = capacites.appeler("m1_recevoir_message_canal", _sms("Nous sommes à Laval.", "SM-3", 4))["resultat"]
    assert troisieme["decision"] == "TRANSMETTRE_M2"
    lead = troisieme["lead"]
    assert (lead["schema_version"], lead["service"], lead["ville"], lead["urgence_declaree"]) == (
        2, "gouttieres", "Laval", True)
    assert _evenements_publies() == 1 and _drainer(deps)["echecs"] == 0
    (ingere,) = _leads_ingeres()
    assert ingere["contrat"] == lead, "M2 reçoit le lead v2 tel quel : le contrat n'a pas changé"

    # Les questions du service (écrites dans le profil, pas dans le code) sont un BROUILLON : rien ne part.
    assert troisieme["questions"]["statut"] == "a_poser"
    assert [q["code"] for q in troisieme["questions"]["restantes"]] == ["longueur", "etages"]
    brouillon = troisieme["brouillon_reponse"]
    assert brouillon and troisieme["envoye"] is False
    assert "Quelle est la longueur approximative de gouttières" in brouillon
    assert envois == [] and _en_attente() == []

    proposition = capacites.appeler("m1_emettre_notification", {"canal": "sms", "message": brouillon})
    assert proposition["statut"] == "en_attente_approbation" and envois == []
    with stockage.transaction() as cnx:
        approbations.decider(cnx, proposition["demande_id"], True, "nathan",
                             outils_executables(capacites.departements, stockage.transaction), capacites.departements)
    assert envois == [("sms", brouillon)]


def test_une_reponse_aux_questions_ne_cree_ni_lead_ni_evenement_de_plus(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    _declarer_qualification()
    capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient.", "SM-1", 0))
    capacites.appeler("m1_recevoir_message_canal", _sms("À Laval.", "SM-2", 2))
    _drainer(deps)

    reponse = capacites.appeler(
        "m1_recevoir_message_canal", _sms("Environ 40 pieds, la maison a 2 étages.", "SM-3", 5))["resultat"]
    assert reponse["decision"] == "CONVERSATION_DEJA_QUALIFIEE"
    assert reponse["questions"]["statut"] == "aucune_restante" and "brouillon_reponse" not in reponse
    assert _evenements_publies() == 1 and _drainer(deps)["livres"] == 0 and len(_leads_ingeres()) == 1


def test_sans_questions_ni_poids_dans_le_profil_la_reception_le_dit_et_n_invente_rien(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient.", "SM-1", 0))
    reponse = capacites.appeler("m1_recevoir_message_canal", _sms("À Laval.", "SM-2", 2))["resultat"]
    assert reponse["decision"] == "TRANSMETTRE_M2"
    assert reponse["questions"]["verdict"]["code"] == "REJ-QUESTIONS-NON-CONFIGUREES"
    assert "brouillon_reponse" not in reponse
    assert _drainer(deps)["echecs"] == 0 and len(_leads_ingeres()) == 1


def test_le_score_et_la_prochaine_action_restent_au_registre_durable_de_m1_pas_dans_l_evenement(instance):
    """Le contrat `LeadQualifie` v2 est gelé : le score (règles, poids du profil) et la prochaine action datée restent
    dans le registre de M1 ; ni l'événement du bus ni le lead ingéré par M2 ne les portent."""
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    _declarer_qualification()
    capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient, c'est urgent.", "SM-1", 0))
    second = capacites.appeler("m1_recevoir_message_canal", _sms("À Laval.", "SM-2", 4))["resultat"]
    assert second["score"]["statut"] == "calcule" and second["score"]["score"] == 80
    assert second["prochaine_action"]["a_faire_avant"] == (DEBUT + dt.timedelta(minutes=30)).isoformat()
    assert second["prochaine_action"]["inscrite_le"] == (DEBUT + dt.timedelta(minutes=4)).isoformat()

    with stockage.transaction():
        lignes = [m for m in m1._obtenir_registre().lire() if m["type_entree"] == "suivi_conversation"]
        assert m1._obtenir_registre().valider_chaine() == (True, None)
    assert [ligne["score"]["score"] for ligne in lignes] == [50, 80]
    assert lignes[-1]["prochaine_action"] == second["prochaine_action"]

    with stockage.transaction() as cnx:
        (charge,) = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie")).scalars().all()
    publie = codec.decoder(charge)
    assert set(publie) == {"lead", "horodatage", "signal_id"}, "l'événement n'a pas changé"
    assert "score" not in publie["lead"] and set(publie["lead"]) <= {
        "schema_version", "lead_id", "service", "ville", "urgence_declaree", "canal", "conversation_id", "contact",
        "source", "utm", "campagne"}
    assert _drainer(deps)["echecs"] == 0
    (ingere,) = _leads_ingeres()
    assert ingere["contrat"] == second["lead"] and "score" not in ingere["contrat"]


def test_sans_poids_dans_le_profil_la_reception_le_dit_et_aucun_score_n_est_ecrit(instance):
    deps, capacites = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    reponse = capacites.appeler("m1_recevoir_message_canal", _sms("Mes gouttières fuient à Laval.", "SM-1", 0))
    bloc = reponse["resultat"]["score"]
    assert bloc["statut"] == "poids_a_configurer" and bloc["verdict"]["code"] == "REJ-POIDS-SCORE-NON-CONFIGURES"
    with stockage.transaction():
        (ligne,) = [m for m in m1._obtenir_registre().lire() if m["type_entree"] == "suivi_conversation"]
    assert "score" not in ligne["score"] and ligne["score"]["statut"] == "poids_a_configurer"
    assert _drainer(deps)["echecs"] == 0 and len(_leads_ingeres()) == 1, "le lead n'attend pas les poids"
