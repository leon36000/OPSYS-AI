"""PLAN T4.5 — E2E « plainte » et « urgence » : l'admin voit l'attente dans « À voir », l'employé reçoit 403.

DEFINITION-PRODUIT §7 M1 : « escalade de plaintes ; E2E verts (…, plainte, …) » ; « urgence de sécurité : transfert
humain immédiat ». Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai
chemin réseau du moteur (`tests/fixtures/harnais_e2e.py`) :

- le message du client arrive à l'agent M1 par `Capacites.appeler("m1_recevoir_message_canal")` (le point d'entrée des
  outils des agents, celui que le serveur MCP appelle), avec le vrai manifeste de M1 (mode `ombre`), une base temporaire
  migrée et les dix départements réels ;
- chaque geste de l'app est un appel de la porte d'appareil du core, refaite en Python d'après le fork : nom nu autorisé
  par le rôle (`roles.json`), session MCP privée à ce serveur, `_meta` posé comme le core, enveloppe rendue telle
  quelle ;
- personnes et appareils créés par les commandes réelles du socle ; le bus est livré à la main (répartiteur réel).

Ce que ces tests ne prouvent PAS : le core lui-même (poignée de main, jeton d'appareil, session MCP TypeScript) ni
l'écran de l'app (`mobile/`). Vocabulaire et messages FICTIFS (`fictif: true`), numéros en 555.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from harnais_e2e import Moteur, iso
from m1_front_office import outils as m1_outils
from sqlalchemy import select

from opsys import stockage, taxonomie
from opsys.capacites import Capacites
from opsys.stockage.schema import EVENEMENTS_SORTANTS

SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
RACINE = Path(__file__).resolve().parents[2]
FIXTURE = RACINE / "departments" / "m01-front-office" / "fixtures" / "plaintes" / "plaintes.v1.yaml"
LISTER = "m9_lister_demandes_approbation"
LIRE = "m1_lire_transfert"
CLORE = "m1_clore_transfert"
NUMERO = "+15145550142"
AUTRE_NUMERO = "+15145550177"
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`


@pytest.fixture
def m1(moteur: Moteur):
    """M1 prêt à recevoir : profil d'entreprise (services, zone, vocabulaire et destinataires FICTIFS de la fixture),
    registre durable, et l'agent M1 qui appelle ses outils par `Capacites`."""
    donnees = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert donnees["fictif"] is True
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    taxonomie.enregistrer_signaux_plainte(donnees["signaux_plainte"])
    m1_outils.utiliser_stockage_durable()
    agent = Capacites(moteur.departements, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    try:
        yield agent
    finally:
        m1_outils.reinitialiser_registre()


def _sms(
    agent: Capacites, texte: str, message_id: str, recu_le: dt.datetime, expediteur: str = NUMERO
) -> dict[str, Any]:
    reponse = agent.appeler("m1_recevoir_message_canal", {
        "canal": "sms", "expediteur": expediteur, "message_id": message_id, "recu_le": iso(recu_le), "texte": texte})
    assert reponse["ok"] is True and "statut" not in reponse, reponse
    return reponse["resultat"]


def _liste(admin) -> dict[str, Any]:
    reponse = admin.appeler(LISTER, {})
    assert reponse.statut == 200 and reponse.metier["accepte"] is True, reponse.corps
    assert reponse.mesure.tronque is False and reponse.mesure.octets_texte < LIMITE_TRONCATURE
    resultat = reponse.resultat
    assert resultat["attentes_illisibles"] == [], "aucun département dont les attentes n'ont pu être lues"
    return resultat


def _attentes_de_m1(liste: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in liste["attentes"] if a["departement"] == "m01-front-office"]


def _evenements(type_evenement: str) -> list[str]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)).all()
    return [ligne.evenement_id for ligne in lignes]


def _leads_de_m2() -> list[dict[str, Any]]:
    with stockage.transaction():
        return [m for m in stockage.maillons("m02-revenue-crm", "principal") if m.get("type_entree") == "lead_ingere"]


def _refus_403(reponse) -> None:
    assert reponse.statut == 403 and reponse.ok is False, reponse.corps
    assert reponse.corps["error"]["type"] == "tool_call_blocked"
    assert "tool_out_of_scope" in reponse.corps["error"]["message"]


@SQLITE_SEULEMENT
def test_e2e_plainte_l_admin_voit_l_attente_l_employe_recoit_403_et_aucun_lead_n_existe(moteur, equipe, m1):
    admin, employe = equipe["admin"], equipe["employe"]
    debut = moteur.horloge.maintenant

    # 1. Le client se plaint, avec de quoi ouvrir un lead (service, ville, son numéro) : la plainte prime.
    recu = _sms(
        m1, "Mes gouttières à Laval fuient encore après vos travaux, je suis très déçu. Rappelez-moi au 514-555-0199.",
        "SM-plainte-1", debut)
    assert recu["decision"] == "ESCALADE_PLAINTE" and recu["qualifie"] is False and "lead" not in recu
    assert set(recu["plainte"]["categories"]) == {"insatisfaction", "degat"}
    assert recu["envoye"] is False and recu["brouillon_reponse"], "un brouillon empathique, jamais envoyé"
    transfert_id = recu["transfert"]["transfert_id"]
    assert recu["transfert"]["verdict_destinataire"]["code"] == taxonomie.VERDICT_DESTINATAIRE_NON_CONFIGURE

    # 2. Le bus est livré : M2 ne reçoit rien, aucun lead n'a été publié.
    moteur.drainer_bus(debut + dt.timedelta(minutes=5))
    assert _evenements("m1.lead_qualifie") == [] and _leads_de_m2() == []

    # 3. L'admin voit l'attente dans « À voir », sans donnée personnelle ni texte du client.
    liste = _liste(admin)
    (attente,) = _attentes_de_m1(liste)
    assert attente["id"] == transfert_id and attente["type"] == "plainte_escaladee" and attente["niveau"] == "N4"
    assert attente["departement_nom"] == "Front Office"
    assert attente["resume"] == "Plainte (insatisfaction, dégât) par sms, 1 message ; pour : destinataire à configurer."
    assert "m1_lire_transfert" in attente["action_proposee"] and "m1_clore_transfert" in attente["action_proposee"]
    tout = json.dumps(liste, ensure_ascii=False)
    for fragment in ("514", "555", NUMERO, "gouttières", "déçu", "Rappelez"):
        assert fragment not in tout, fragment

    # 4. L'employé n'a ni la liste ni la lecture ni la clôture : 403 à la porte d'appareil.
    _refus_403(employe.appeler(LISTER, {}))
    _refus_403(employe.appeler(LIRE, {"transfert_id": transfert_id}))
    _refus_403(employe.appeler(CLORE, {
        "transfert_id": transfert_id, "motif": "Tentative de clôture par un employé.", "horodatage": iso(debut)},
        cle="mut-employe-1", horodatage_appareil=iso(debut)))

    # 5. L'admin lit le contexte complet : résumé, contact du canal à part, messages, brouillon.
    lu = admin.appeler(LIRE, {"transfert_id": transfert_id})
    assert lu.statut == 200 and lu.mesure.tronque is False
    vue = lu.resultat
    assert vue["statut"] == "ouvert" and vue["type_transfert"] == "plainte" and vue["contact"] == {"telephone": NUMERO}
    assert "514-555-0199" in vue["messages_couverts"][0]["texte"], "la personne lit ce que le client a écrit"
    assert vue["resume"].startswith("Plainte. Ouvert par : les règles.") and "514" not in vue["resume"]
    assert vue["brouillon_reponse"] == recu["brouillon_reponse"] and vue["envoye"] is False

    # 6. L'agent ne clôt pas seul : sa proposition attend une personne, l'attente reste.
    proposition = m1.appeler(CLORE, {"transfert_id": transfert_id, "motif": "Réglé par l'agent, pense-t-il.",
                                     "horodatage": iso(debut)})
    assert proposition["statut"] == "en_attente_approbation"
    assert len(_attentes_de_m1(_liste(admin))) == 1

    # 7. L'admin clôt depuis son téléphone : l'attente disparaît, la personne et son motif restent au registre.
    cloture = admin.appeler(CLORE, {
        "transfert_id": transfert_id, "motif": "Client rappelé, la fuite sera vue sur place.",
        "horodatage": iso(debut)},
        cle="mut-admin-1", horodatage_appareil=iso(debut))
    assert cloture.statut == 200 and cloture.metier["accepte"] is True, cloture.corps
    assert cloture.resultat["clos_par"] == "nathan" and cloture.resultat["voie"] == "appareil"
    assert _attentes_de_m1(_liste(admin)) == []
    relu = admin.appeler(LIRE, {"transfert_id": transfert_id}).resultat
    assert relu["statut"] == "clos" and relu["cloture"]["par"] == "nathan"
    assert _evenements("m1.lead_qualifie") == [] and _leads_de_m2() == [], "rien n'est parti chez M2, avant ni après"


@SQLITE_SEULEMENT
def test_e2e_urgence_passe_devant_la_plainte_sans_conseil_ni_promesse_et_l_employe_recoit_403(moteur, equipe, m1):
    admin, employe = equipe["admin"], equipe["employe"]
    debut = moteur.horloge.maintenant

    # Une plainte plus ancienne attend déjà ; une urgence de sécurité arrive ensuite.
    plainte = _sms(m1, "C'est inacceptable, personne ne m'a rappelé.", "SM-plainte-2", debut, expediteur=AUTRE_NUMERO)
    assert plainte["decision"] == "ESCALADE_PLAINTE"
    urgence = _sms(
        m1, "Il y a de la fumée qui sort du soffite et un fil électrique pend près de la porte.", "SM-urgence-1",
        debut + dt.timedelta(minutes=20))
    assert urgence["decision"] == "ESCALADE_URGENCE" and urgence["qualifie"] is False and "lead" not in urgence
    assert urgence["transfert"]["niveau"] == "N5"
    # Aucun conseil, aucune promesse : le brouillon ne dit que le signalement, et la consigne l'interdit à l'agent.
    assert urgence["brouillon_reponse"] == (
        "Bonjour, merci de votre message. Nous l'avons signalé à une personne de l'équipe.")
    assert urgence["envoye"] is False
    assert "AUCUN conseil de sécurité" in urgence["consigne"] and "AUCUNE intervention" in urgence["consigne"]

    moteur.drainer_bus(debut + dt.timedelta(minutes=30))
    assert _evenements("m1.lead_qualifie") == [] and _leads_de_m2() == []

    # L'admin voit l'urgence AVANT la plainte, bien qu'elle soit arrivée après : niveau, puis ancienneté.
    liste = _liste(admin)
    attentes = _attentes_de_m1(liste)
    assert [(a["type"], a["niveau"]) for a in attentes] == [("urgence_escaladee", "N5"), ("plainte_escaladee", "N4")]
    assert attentes[0]["id"] == urgence["transfert"]["transfert_id"]
    assert attentes[0]["depuis"] > attentes[1]["depuis"], "l'urgence est arrivée après la plainte, et passe devant"
    tout = json.dumps(liste, ensure_ascii=False)
    for fragment in (NUMERO, AUTRE_NUMERO, "fumée", "électrique", "inacceptable"):
        assert fragment not in tout, fragment

    # L'employé ne voit rien de tout cela.
    _refus_403(employe.appeler(LISTER, {}))
    _refus_403(employe.appeler(LIRE, {"transfert_id": urgence["transfert"]["transfert_id"]}))

    # L'admin clôt l'urgence : la plainte reste seule dans la file.
    admin.appeler(CLORE, {
        "transfert_id": urgence["transfert"]["transfert_id"],
        "motif": "Client joint par téléphone, dossier pris en charge.", "horodatage": iso(debut)},
        cle="mut-admin-2", horodatage_appareil=iso(debut))
    restantes = _attentes_de_m1(_liste(admin))
    assert [a["id"] for a in restantes] == [plainte["transfert"]["transfert_id"]]


@SQLITE_SEULEMENT
def test_e2e_un_message_qui_suit_une_plainte_ouverte_ne_devient_pas_un_lead_par_le_bus(moteur, equipe, m1):
    """Le client écrit ensuite sa demande complète : elle est rattachée au transfert et n'atteint jamais M2 tant qu'une
    personne n'a pas clos la plainte. Une fois close, une nouvelle demande suit le chemin d'avant (lead, bus, M2)."""
    admin = equipe["admin"]
    debut = moteur.horloge.maintenant
    plainte = _sms(m1, "Je suis très déçu de votre service.", "SM-p", debut)
    suite = _sms(
        m1, "Mes gouttières fuient à Laval, faites-moi une soumission.", "SM-s", debut + dt.timedelta(minutes=5))
    assert suite["decision"] == "TRANSFERT_EN_COURS" and suite["qualifie"] is False
    moteur.drainer_bus(debut + dt.timedelta(minutes=10))
    assert _evenements("m1.lead_qualifie") == [] and _leads_de_m2() == []
    (attente,) = _attentes_de_m1(_liste(admin))
    assert "2 messages, dont 1 depuis l'ouverture" in attente["resume"]

    admin.appeler(CLORE, {
        "transfert_id": plainte["transfert"]["transfert_id"], "motif": "Plainte traitée avec le client.",
        "horodatage": iso(debut)}, cle="mut-admin-3", horodatage_appareil=iso(debut))
    nouvelle = _sms(m1, "Bonjour, je voudrais une soumission pour des gouttières à Québec.", "SM-n",
                    debut + dt.timedelta(minutes=30))
    assert nouvelle["decision"] == "TRANSMETTRE_M2" and nouvelle["lead"]["ville"] == "Québec"
    moteur.drainer_bus(debut + dt.timedelta(minutes=40))
    assert len(_evenements("m1.lead_qualifie")) == 1 and len(_leads_de_m2()) == 1
