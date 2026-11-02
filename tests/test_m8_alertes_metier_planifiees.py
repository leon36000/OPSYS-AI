"""C3, de bout en bout : la trésorerie passe sous le seuil de la direction, une alerte s'ouvre AVEC son action et son
propriétaire, M9 la reçoit, « À voir » la montre, on l'accuse, on la reporte, elle se résout au retour dans la cible,
et il n'y en a qu'une par épisode. Rien ne sort de l'application.

Le défaut (base ea631e4bc) : aucune alerte métier (trésorerie, baisse de leads, rupture, facture en retard), ni cycle
de vie (accusé, report, résolution), ni poussée vers un humain. Ici : les vrais départements, le vrai bus, le VRAI
planificateur à horloge INJECTÉE (le tour `m8.entrepot` évalue les alertes), le vrai sas N3 des réglages de direction
(le seuil est ADOPTÉ par le propriétaire, jamais écrit dans un fichier), la section « À voir » du socle
(`approbations.attentes_departements`), des données FICTIVES. Limites dites : SQLite seulement, horloge injectée,
aucun service externe ; aucun écran d'accusé : les gestes passent par les outils N2 d'un agent (les écrans mobiles
sont un autre chantier) ; rien n'est poussé hors de l'application (la poussée est une décision du propriétaire, en
attente).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import planif_m8_monde as pm
import planif_qa as pq
import pytest
from m8_analytics import alertes_metier

from opsys import approbations, horloge, identite, stockage
from opsys.capacites import Capacites
from opsys.connecteurs_planification import etat, planificateur
from opsys.departements import charger_departements


def _charger(chemin: Path, nom: str):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


aide = _charger(Path(__file__).with_name("reglages_aide.py"), "reglages_aide_alertes_m8")

FICTIF = True
HEURE = 3600
CASH = "m5.constat.cash-libre"
ENTREPOT = "m8.entrepot"
TRESORERIE = "ALERTE-TRESORERIE-SOUS-SEUIL"
ID_1 = "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1"
ID_2 = "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:2"
SEUIL_CLE = "m8.seuil_alerte_tresorerie_sous_seuil"
# Le cash libre du trésorier fictif est 27 861,98 $ (cas de référence calculé à la main).
SEUIL_ATTEINT = "30000"  # le cash libre est SOUS ce seuil : franchi
SEUIL_BAS = "1000"  # le cash libre est au-dessus : retour dans la cible


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    m.attendu = pm.semer_m5_tresorerie(m, tmp_path, monkeypatch)
    with stockage.transaction() as cnx:  # la personne qui signe les réglages de direction (le propriétaire)
        identite.creer_personne(cnx, aide.PROPRIETAIRE, "Propriétaire fictif", aide.MOT_DE_PASSE,
                                ["nathan_owner", "admin"])
    # le serveur lit l'heure par `opsys.horloge` (M8 n'a pas d'horloge) : on y met l'horloge injectée du planificateur
    monkeypatch.setattr(horloge, "maintenant", lambda: dt.datetime.fromtimestamp(m.horloge(), dt.UTC))
    yield m
    pm.demonter()


def _adopter(valeur: str) -> dict:
    """Le propriétaire ADOPTE le seuil par le geste N3 des réglages de direction (le vrai sas, le vrai outil)."""
    deps = charger_departements()
    with stockage.transaction() as cnx:
        return aide.adopter(cnx, deps, SEUIL_CLE, valeur, raison="Décision de la direction (fictive)")


def _revenir() -> dict:
    deps = charger_departements()
    with stockage.transaction() as cnx:
        return aide.revenir(cnx, deps, SEUIL_CLE)


def _activer(monde) -> None:
    monde.activer("actif", noms=(CASH,))
    with stockage.transaction() as cnx:
        etat.appliquer(cnx, pq.session_admin(), ENTREPOT, "actif", motif="preuve fictive", maintenant=monde.horloge(),
                       intervalle_s=HEURE)


def _passage(monde, avance: float = HEURE) -> dict:
    monde.horloge.avancer(avance)
    resume = planificateur.tour(monde.plan.departements, ports=monde.plan.ports)
    monde.propager(pm.M8, pm.M9, pm.M10)
    return resume["executeurs"]


def _alertes(monde, **arguments) -> dict:
    return monde.m8("m8_lire_alertes_metier", maintenant=monde.maintenant(), **arguments)


def _a_voir(monde) -> list[dict]:
    deps = charger_departements()
    with stockage.transaction() as cnx:
        attentes, illisibles = approbations.attentes_departements(cnx, deps)
    assert illisibles == []
    return [a for a in attentes if a["departement"] == pm.M8]


def _registre(monde) -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(pm.M8, alertes_metier.NOM_REGISTRE))


def _geste(monde, outil: str, **arguments) -> dict:
    capacites = Capacites(monde.bus.departements, stockage.transaction, filtre={pm.M8}, memoire=False)
    return capacites.appeler(outil, {"maintenant": monde.maintenant(), **arguments})


def _cash_alertes(vue: dict) -> list[dict]:
    return [a for a in vue["alertes"] if a["regle"] == TRESORERIE]


# ===================================================================================== 1. sans seuil, rien n'est
# inventé
def test_sans_seuil_declare_la_regle_est_non_evaluee_et_le_dit_aucune_alerte_ne_s_ouvre(monde):
    _activer(monde)
    monde.tour(1)
    for _ in range(2):
        _passage(monde)
    assert monde.mesures()["m8_cash_libre_cad"]["valeur"] == "27861.98"  # la mesure existe, à jour et conforme
    vue = _alertes(monde)
    ligne = next(r for r in vue["regles"] if r["regle"] == TRESORERIE)
    assert ligne["seuil"] == "a_configurer" and ligne["raisons_non_evaluee"] == ["seuil_a_configurer"]
    assert ligne["reglage"] == "configuration.alertes.seuils.tresorerie_sous_seuil"
    assert vue["alertes"] == [] and _a_voir(monde) == [] and _registre(monde) == []
    assert monde.bus.sortants("m8.alerte_proposee") == []


# ==================================================================== 2. le scénario complet d'un épisode de trésorerie
def test_tresorerie_sous_seuil_alerte_avec_action_et_proprietaire_accuse_report_resolution_une_seule_par_episode(monde):
    _activer(monde)
    monde.tour(1)
    _passage(monde)
    assert _adopter(SEUIL_ATTEINT)["statut"] == "executee"  # le propriétaire déclare son seuil (geste N3)

    # -- le tour planifié ouvre UNE alerte : action, propriétaire, courant, référence
    # -----------------------------------
    resume = _passage(monde)
    assert resume[ENTREPOT]["statut"] == "ok" and resume[ENTREPOT]["erreurs"] == 0, resume[ENTREPOT]
    vue = _alertes(monde)
    (alerte,) = _cash_alertes(vue)
    assert alerte["alerte_id"] == ID_1 and alerte["statut"] == "ouverte" and alerte["gravite"] == "critique"
    assert alerte["departement_proprietaire"] == "m05-financecore"
    assert alerte["courant"] == {"valeur": "27861.98", "unite": "CAD"}
    assert alerte["reference"] == {"sens": "au_dessous", "seuil": "30000.00", "unite": "CAD"}
    assert "m05-financecore" in alerte["action_recommandee"] and "CPA" in alerte["action_recommandee"]
    assert "27 861,98" in alerte["pourquoi"] and "30 000,00" in alerte["pourquoi"]
    assert not any("cause" in cle or "responsable" in cle for cle in alerte)
    assert set(alerte["mesures_liees"]) == {"m8_solde_tresorerie_cad", "m8_comptes_a_payer_cad",
                                            "m8_taxes_a_remettre_cad", "m8_creances_ouvertes_cad"}
    assert next(r for r in vue["regles"] if r["regle"] == TRESORERIE)["franchies"] == 1

    # -- M9 la reçoit par le bus (une seule fois), avec l'action et le destinataire
    # -------------------------------------
    envoyes = [e for e in monde.publies("m8.alerte_proposee") if e["charge"]["alerte_id"] == ID_1]
    assert len(envoyes) == 1
    charge = envoyes[0]["charge"]
    assert charge["a_qui"] == "m05-financecore" and charge["type_alerte"] == "METIER-SEUIL-FRANCHI"
    assert charge["action_proposee"] == alerte["action_recommandee"] and charge["gravite"] == "critique"
    assert charge["preuve"]["episode"] == 1 and charge["preuve"]["seuil"] == "30000.00"
    assert monde.bus.statut(envoyes[0]["evenement_id"], pm.M9) == "traite"
    recues = monde.bus.registre(pm.M9, "alertes_m8")
    assert [a["alerte_id"] for a in recues if a.get("alerte_id") == ID_1] == [ID_1]

    # -- « À voir » du propriétaire la montre, sans aucun montant, N3 car critique
    # ----------------------------------------
    (item,) = [a for a in _a_voir(monde) if a["id"] == ID_1]
    assert item["type"] == "alerte_metier" and item["niveau"] == "N3" and "m05-financecore" in item["resume"]
    assert not any(c.isdigit() for c in item["resume"].replace("m05-financecore", "")), "aucun montant dans l'attente"

    # -- UNE seule alerte par épisode : dix passages de plus, rien de neuf
    # ----------------------------------------------
    for _ in range(10):
        _passage(monde)
    assert len([e for e in monde.publies("m8.alerte_proposee") if e["charge"].get("alerte_id") == ID_1]) == 1
    assert len([e for e in _registre(monde) if e["type_entree"] == "alerte_ouverte"]) == 1
    assert [a["id"] for a in _a_voir(monde)] == [ID_1]

    # -- l'accusé : sort de « À voir », l'épisode reste ouvert, un double accusé n'écrit rien
    # --------------------------------
    reponse = _geste(monde, "m8_accuser_alerte", alerte_id=ID_1)
    assert reponse["ok"] is True and reponse["resultat"]["accusee"] is True
    assert _a_voir(monde) == []
    assert _cash_alertes(_alertes(monde))[0]["statut"] == "accusee"
    deux = _geste(monde, "m8_accuser_alerte", alerte_id=ID_1)
    assert deux["resultat"]["accusee"] is False and deux["resultat"]["deja_accusee"] is True
    _passage(monde)
    assert len([e for e in _registre(monde) if e["type_entree"] == "alerte_accusee"]) == 1
    assert len([e for e in _registre(monde) if e["type_entree"] == "alerte_ouverte"]) == 1  # l'accusé ne rouvre rien

    # -- le report : cachée jusqu'à l'instant choisi, puis elle revient d'elle-même (aucune entrée écrite)
    # -----------------
    jusqu_au = (dt.datetime.fromtimestamp(monde.horloge(), dt.UTC) + dt.timedelta(hours=3)).isoformat()
    assert _geste(monde, "m8_reporter_alerte", alerte_id=ID_1, jusqu_au=jusqu_au)["ok"] is True
    assert _a_voir(monde) == [] and _cash_alertes(_alertes(monde))[0]["statut"] == "reportee"
    _passage(monde)
    _passage(monde)
    assert _a_voir(monde) == [] and _cash_alertes(_alertes(monde))[0]["statut"] == "reportee"
    n_avant = len(_registre(monde))
    _passage(monde)  # 3 h écoulées : le report est échu
    assert _cash_alertes(_alertes(monde))[0]["statut"] == "ouverte"
    assert [a["id"] for a in _a_voir(monde)] == [ID_1]
    assert len(_registre(monde)) == n_avant  # l'échéance n'a rien écrit
    assert len([e for e in monde.publies("m8.alerte_proposee") if e["charge"].get("alerte_id") == ID_1]) == 1

    # -- la résolution : la direction déclare un seuil plus bas, la valeur est revenue dans la cible
    # --------------------------
    assert _adopter(SEUIL_BAS)["statut"] == "executee"
    _passage(monde)
    (resolue,) = _cash_alertes(_alertes(monde, statut="resolue"))
    assert resolue["alerte_id"] == ID_1 and resolue["resolue_le"] is not None
    assert _a_voir(monde) == [] and _cash_alertes(_alertes(monde, statut="ouverte")) == []
    refus = _geste(monde, "m8_accuser_alerte", alerte_id=ID_1)
    assert "REJ-ALERTE-DEJA-RESOLUE" in json.dumps(refus, ensure_ascii=False)

    # -- une rechute ouvre l'épisode SUIVANT (une alerte de plus, pas une réouverture)
    # --------------------------------------
    assert _adopter(SEUIL_ATTEINT)["statut"] == "executee"
    _passage(monde)
    (nouvelle,) = _cash_alertes(_alertes(monde, statut="ouverte"))
    assert nouvelle["alerte_id"] == ID_2 and nouvelle["episode"] == 2
    assert len([e for e in monde.publies("m8.alerte_proposee") if e["charge"].get("alerte_id") in (ID_1, ID_2)]) == 2

    # -- rien d'externe : aucun envoi, aucun appel hors de l'application, aucune donnée personnelle
    # ----------------------
    for e in monde.publies("m8.alerte_proposee"):
        texte = json.dumps(e["charge"], ensure_ascii=False)
        for interdit in pm.PERSONNEL + ("Marc Tremblay", "brouillon de paie", "estimation du CPA", "relevé du prêt"):
            assert interdit not in texte, (e["evenement_id"], interdit)
    assert monde.bus.quarantaines() == [] and monde.bus.ecritures_hors_propriete() == []


# ================================================================== 3. les autres règles : ce qu'elles ne font pas
def test_une_mesure_perimee_n_alerte_pas_sur_sa_valeur_mais_alerte_qu_elle_est_perimee(monde):
    _activer(monde)
    monde.tour(1)
    _passage(monde)
    assert _adopter(SEUIL_ATTEINT)["statut"] == "executee"
    _passage(monde)
    assert [a["id"] for a in _a_voir(monde)] == [ID_1]
    # M5 tombe en panne : le constat n'est plus renouvelé ; 3 jours plus tard la mesure est périmée
    with stockage.transaction() as cnx:
        etat.appliquer(cnx, pq.session_admin(), CASH, "inactif", motif="panne fictive",
                       maintenant=monde.horloge())
    monde.horloge.avancer(3 * 86400)
    _passage(monde, HEURE)
    cash = monde.mesures()["m8_cash_libre_cad"]
    assert cash["fraicheur"] == "perime"
    vue = _alertes(monde)
    ligne = next(r for r in vue["regles"] if r["regle"] == TRESORERIE)
    assert ligne["raisons_non_evaluee"] == ["mesure_perimee"] and ligne["franchies"] == 0
    perimees = [a for a in vue["alertes"] if a["regle"] == "ALERTE-DONNEE-PERIMEE"]
    assert [a["metric_id"] for a in perimees] == ["m8_cash_libre_cad"] and perimees[0]["statut"] == "ouverte"
    assert "m05-financecore" in perimees[0]["action_recommandee"] and "m8_lire_etat_collecte" in perimees[0][
        "action_recommandee"]
    # l'épisode de trésorerie n'est PAS résolu sur une valeur périmée (on ne ferme pas sur ce qu'on ne peut pas juger)
    (episode,) = _cash_alertes(vue)
    assert episode["statut"] in ("ouverte", "accusee", "reportee") and episode["resolue_le"] is None


def test_le_retour_arriere_du_seuil_remet_la_regle_a_non_evaluee_sans_fermer_l_episode(monde):
    _activer(monde)
    monde.tour(1)
    _passage(monde)
    assert _adopter(SEUIL_ATTEINT)["statut"] == "executee"
    _passage(monde)
    assert _revenir()["statut"] == "executee"
    _passage(monde)
    ligne = next(r for r in _alertes(monde)["regles"] if r["regle"] == TRESORERIE)
    assert ligne["seuil"] == "a_configurer"
    assert _cash_alertes(_alertes(monde))[0]["statut"] == "ouverte"  # l'épisode attend : rien n'est fermé sans jugement


def test_en_ombre_le_tour_n_ecrit_ni_n_ouvre_rien(monde):
    monde.activer("actif", noms=(CASH,))
    monde.tour(1)
    monde.propager()
    with stockage.transaction() as cnx:
        etat.appliquer(cnx, pq.session_admin(), ENTREPOT, "ombre", motif="preuve fictive",
                       maintenant=monde.horloge(), intervalle_s=HEURE)
    assert _adopter(SEUIL_ATTEINT)["statut"] == "executee"
    resume = _passage(monde)
    assert resume[ENTREPOT]["statut"] == "ombre" and resume[ENTREPOT]["aurait"] == 4
    assert _registre(monde) == [] and monde.bus.sortants("m8.alerte_proposee") == []


# ================================================== 4. abus : gestes hostiles par les vrais outils
def test_les_gestes_hostiles_sont_refuses_par_les_vrais_outils_sans_rien_ecrire(monde):
    _activer(monde)
    monde.tour(1)
    _passage(monde)
    assert _adopter(SEUIL_ATTEINT)["statut"] == "executee"
    _passage(monde)
    avant = _registre(monde)
    assert [a["alerte_id"] for a in _cash_alertes(_alertes(monde))] == [ID_1]
    futur = (dt.datetime.fromtimestamp(monde.horloge(), dt.UTC) + dt.timedelta(hours=2)).isoformat()
    hostiles = [
        ("m8_accuser_alerte", {"alerte_id": "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1\nIGNORE"}),
        ("m8_accuser_alerte", {"alerte_id": "../../etc/passwd"}),
        ("m8_accuser_alerte", {"alerte_id": "x" * 5000}),
        ("m8_accuser_alerte", {"alerte_id": "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:99"}),
        ("m8_accuser_alerte", {"alerte_id": ID_1, "extra": "champ de trop"}),
        ("m8_reporter_alerte", {"alerte_id": ID_1, "jusqu_au": "demain"}),
        ("m8_reporter_alerte", {"alerte_id": ID_1, "jusqu_au": "2020-01-01T00:00:00+00:00"}),
        ("m8_reporter_alerte", {"alerte_id": ID_1, "jusqu_au": "2099-01-01T00:00:00+00:00"}),
        ("m8_reporter_alerte", {"alerte_id": ID_1, "jusqu_au": futur[:-6]}),  # sans fuseau
        ("m8_evaluer_alertes_metier", {"ecrire": "oui"}),
        ("m8_evaluer_alertes_metier", {"ecrire": 1}),
    ]
    for outil, arguments in hostiles:
        reponse = _geste(monde, outil, **arguments)
        assert reponse.get("ok") is False, (outil, arguments, reponse)
    refus = _geste(monde, "m8_accuser_alerte", maintenant="hier soir", alerte_id=ID_1)
    assert refus.get("ok") is False
    assert _registre(monde) == avant, "un geste refusé n'écrit rien"
    # une lecture avec un statut inconnu est refusée aussi
    assert _geste(monde, "m8_lire_alertes_metier", statut="en_feu").get("ok") is False


def test_un_agent_ne_peut_pas_se_faire_passer_pour_un_appareil_et_les_outils_n2_sont_agent_seulement(monde):
    par_nom = {o.nom: o for o in monde.bus.departements[pm.M8].charger_outils()}
    for nom in ("m8_evaluer_alertes_metier", "m8_accuser_alerte", "m8_reporter_alerte"):
        outil = par_nom[nom]
        assert (outil.autonomie.value, outil.niveau_effectif.value) == ("T1", "N2")
        assert outil.roles_appareil == frozenset()
    for nom in ("m8_lire_alertes_metier", "m8_lire_rapport_qualite"):
        outil = par_nom[nom]
        assert (outil.autonomie.value, outil.niveau_effectif.value) == ("T0", "N0")
        assert outil.roles_appareil == frozenset()
