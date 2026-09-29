"""M1 et les canaux du core, par `Capacites` et les approbations réelles (PLAN T2.1-a).

Ces tests passent par le VRAI point d'entrée des outils (`opsys.capacites.Capacites.appeler`, celui que le serveur
MCP appelle), le VRAI manifeste de M1 (mode `ombre`), la file d'approbation réelle (`approbations.decider`) et une
base SQLite migrée. Ils prouvent trois choses : recevoir un message de client ne demande aucune approbation (c'est
une écriture interne, N2) ; tout ce qui sort vers un client ou décide à la place d'un humain attend l'approbation
d'une personne qui en a le droit ; l'inscription au registre et la publication au bus réussissent ou échouent
ensemble. Données fictives (numéros en 555, personnes de test).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m1_front_office import outils as outils_m1
from sqlalchemy import func, select

from opsys import approbations, evenements, identite, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.stockage.schema import EVENEMENTS_SORTANTS

M1 = Path(__file__).resolve().parents[1]
NUMERO = "+15145550142"
RECU_LE = "2026-09-29T09:15:00-04:00"
MESSAGE = {
    "canal": "sms", "expediteur": NUMERO, "message_id": "SMfictif0001", "recu_le": RECU_LE,
    "texte": "Bonjour, mes gouttières fuient à Laval, c'est urgent.",
}
SORTANT = {"canal": "sms", "message": "Bonjour, nous avons bien reçu votre demande. Une personne vous répondra."}


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    """Base migrée, profil d'entreprise, registre de production de M1, et trois personnes de test."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    outils_m1.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
    yield
    outils_m1.reinitialiser_registre()
    stockage.liberer()


@pytest.fixture
def dep(instance):
    return lire_manifeste(M1)


@pytest.fixture
def capacites(dep):
    return Capacites({dep.id: dep}, stockage.transaction, memoire=False)


def _lignes():
    with stockage.transaction():
        return outils_m1._obtenir_registre().lire()


def _evenements_publies():
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie")).scalar_one()


def _en_attente():
    with stockage.transaction() as cnx:
        return approbations.lister(cnx, "en_attente")


def _decider(capacites, demande_id, par):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande_id, True, par, outils_executables(capacites.departements, stockage.transaction),
            capacites.departements)


# -- Recevoir : une écriture interne, sans approbation -------------------------------------------------------------


def test_le_message_d_un_client_est_recu_sans_approbation_et_le_lead_est_publie(capacites):
    reponse = capacites.appeler("m1_recevoir_message_canal", MESSAGE)

    assert reponse["ok"] is True and "statut" not in reponse, reponse
    resultat = reponse["resultat"]
    assert resultat["decision"] == "TRANSMETTRE_M2" and resultat["lead"]["source"] == "sms"
    assert _en_attente() == []
    signal, lead = _lignes()
    assert (signal["type_entree"], lead["type_entree"]) == ("signal", "lead_emis")
    with stockage.transaction():
        assert outils_m1._obtenir_registre().valider_chaine() == (True, None)
        charge = evenements.charge_publiee("m1.lead_qualifie", f"m1-lead-qualifie-{resultat['lead']['lead_id']}")
    assert charge == {"lead": resultat["lead"], "horodatage": RECU_LE, "signal_id": "sms:SMfictif0001"}


def test_un_message_recu_deux_fois_ne_publie_pas_un_second_evenement(capacites):
    premiere = capacites.appeler("m1_recevoir_message_canal", MESSAGE)
    seconde = capacites.appeler("m1_recevoir_message_canal", MESSAGE)
    assert premiere["ok"] and seconde["ok"]
    assert seconde["resultat"]["doublon"] is True
    assert len(_lignes()) == 2 and _evenements_publies() == 1


def test_le_message_d_un_client_est_recu_meme_quand_m1_passe_en_supervise(capacites, dep):
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, dep.id, "supervise", "nathan")
    reponse = capacites.appeler("m1_recevoir_message_canal", MESSAGE)
    assert reponse["ok"] is True and "statut" not in reponse
    assert _en_attente() == []


def test_un_refus_metier_annule_tout_et_ne_publie_rien(capacites):
    taxonomie.fichier_profil().write_text("services: [gouttieres]\n", encoding="utf-8")  # plus de zone
    reponse = capacites.appeler("m1_recevoir_message_canal", MESSAGE)
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "REJ-ZONE-NON-CONFIGUREE" in reponse["details"]
    assert _lignes() == [] and _evenements_publies() == 0


def test_l_inscription_au_registre_et_la_publication_reussissent_ou_echouent_ensemble(capacites, monkeypatch):
    def publication_en_panne(*_args, **_kwargs):
        raise ValueError("bus indisponible")

    with monkeypatch.context() as panne:
        panne.setattr(outils_m1.evenements, "publier", publication_en_panne)
        reponse = capacites.appeler("m1_recevoir_message_canal", MESSAGE)
    assert reponse["ok"] is False and "bus indisponible" in reponse["details"]
    # Ni le signal ni le lead ne restent au registre : le message pourra être rejoué sans doublon ni trou.
    assert _lignes() == [] and _evenements_publies() == 0
    assert capacites.appeler("m1_recevoir_message_canal", MESSAGE)["resultat"]["decision"] == "TRANSMETTRE_M2"
    assert len(_lignes()) == 2 and _evenements_publies() == 1


# -- Ce qui décide ou sort vers un client attend un humain ----------------------------------------------------------


def test_l_ancien_outil_de_traitement_attend_l_approbation_puis_s_execute_avec_son_lead_publie(capacites):
    arguments = {
        "contenu_brut": "Gouttières à Laval, 514-555-0142.", "canal": "texte", "conversation_id": "conv-x",
        "signal_id": "sig-x", "horodatage": RECU_LE, "zone_desservie": ["Laval"],
    }
    reponse = capacites.appeler("m1_traiter_demande_entrante", arguments)
    assert reponse["statut"] == "en_attente_approbation", reponse
    (demande,) = _en_attente()
    assert demande["outil"] == "m1_traiter_demande_entrante" and demande["niveau"] == "N3"
    assert _lignes() == [] and _evenements_publies() == 0, "rien n'est exécuté avant la décision"

    _decider(capacites, reponse["demande_id"], "nathan")
    assert [ligne["type_entree"] for ligne in _lignes()] == ["signal", "lead_emis"]
    assert _evenements_publies() == 1


def test_un_message_vers_un_client_n_est_pas_envoye_avant_l_approbation_d_une_personne_autorisee(
    capacites, monkeypatch
):
    envois: list[tuple[str, str]] = []

    class BusEspion:
        def emettre(self, canal, message):
            envois.append((canal, message))
            return "id-espion"

    monkeypatch.setattr(outils_m1.adaptateurs, "creer_bus", lambda mode_ombre=True: BusEspion())

    reponse = capacites.appeler("m1_emettre_notification", SORTANT)
    assert reponse["statut"] == "en_attente_approbation"
    (demande,) = _en_attente()
    assert (demande["outil"], demande["niveau"], demande["departement"]) == (
        "m1_emettre_notification", "N4", "m01-front-office")
    assert envois == [], "rien ne part tant qu'un humain n'a pas approuvé"

    # Un employé n'est pas autorisé à décider un envoi (N4 : le propriétaire) : refus nommé, rien ne part.
    with pytest.raises(ValueError, match="aucun rôle autorisé"):
        _decider(capacites, reponse["demande_id"], "employe.fictif")
    assert envois == [] and len(_en_attente()) == 1

    _decider(capacites, reponse["demande_id"], "nathan")
    assert envois == [(SORTANT["canal"], SORTANT["message"])]
    assert _en_attente() == []


def test_en_mode_supervise_un_message_vers_un_client_attend_toujours(capacites, dep):
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, dep.id, "supervise", "nathan")
    reponse = capacites.appeler("m1_emettre_notification", SORTANT)
    assert reponse["statut"] == "en_attente_approbation"


def test_seuls_l_accueil_et_les_deux_outils_de_transfert_sont_n2_et_rien_n_est_t3_dans_m1(dep):
    """N2 « tâche interne » (ADR-0009 §4) : l'accueil, et les deux outils qui mettent une conversation devant une
    personne (PLAN T4.5). Tous trois sont appelés dans la session d'un client dont l'affaire n'est pas liée, où le
    garde du core refuserait un N3. Tout ce qui sort vers le client (N4) ou décide (clôture, N3) est ailleurs."""
    par_nom = {o.nom: o for o in dep.charger_outils()}
    n2 = sorted(nom for nom, o in par_nom.items() if o.niveau_effectif.value == "N2")
    assert n2 == ["m1_escalader_plainte", "m1_recevoir_message_canal", "m1_transferer"]
    assert not any(o.frontiere_humaine for o in par_nom.values())
    assert par_nom["m1_emettre_notification"].niveau_effectif.value == "N4"
    assert par_nom["m1_clore_transfert"].niveau_effectif.value == "N3"
    assert par_nom["m1_lire_transfert"].niveau_effectif.value == "N0"
