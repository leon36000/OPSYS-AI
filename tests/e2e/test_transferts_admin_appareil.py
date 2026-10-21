"""T4.26 : lectures M1 HTTP MCP/SQLite réelles, porte Core rejouée Python seulement.

Fixtures fictives : aucun client/prestataire réel, appel, message envoyé ou Gateway TypeScript.
La préparation utilise les outils métier existants ; chaque lecture conserve toutes les tables.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import yaml
from m1_front_office import outils as m1
from sqlalchemy import select

from opsys import contexte, identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.stockage.schema import META

FICTIF = True
LIRE = "m1_lire_transfert"
DIGEST = "m1_produire_digest"
CAPTURES_FICTIVES: dict[str, dict] = {}
SQLITE = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)


@pytest.fixture
def agent(moteur):
    chemin = Path(__file__).resolve().parents[2] / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml"
    corpus = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    assert corpus["fictif"] is True
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    taxonomie.enregistrer_signaux_plainte(corpus["signaux_plainte"])
    taxonomie.enregistrer_fenetre_conversation(120)
    m1.utiliser_stockage_durable()
    yield Capacites(moteur.departements, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    m1.reinitialiser_registre()


def _sms(agent, texte, identifiant, instant, telephone="+15145550142"):
    r = agent.appeler("m1_recevoir_message_canal", {"canal": "sms", "expediteur": telephone,
        "message_id": identifiant, "recu_le": instant.isoformat(), "texte": texte})
    assert r["ok"] is True, r
    return r["resultat"]


def _etat():
    with stockage.transaction() as cnx:
        return tuple((t.name, tuple(tuple(r) for r in cnx.execute(select(t)))) for t in META.sorted_tables)


def _capture(nom, outil, args, reponse):
    assert nom not in CAPTURES_FICTIVES
    CAPTURES_FICTIVES[nom] = {"outil": outil, "args": args, "statut_http": reponse.statut,
        "corps": reponse.corps, "enveloppe": reponse.corps.get("result")}


def _lire_sans_effet(appareil, nom, outil, args):
    avant = _etat()
    reponse = appareil.appeler(outil, args)
    assert _etat() == avant, "une lecture M1 ne modifie aucune table"
    _capture(nom, outil, args, reponse)
    return reponse


@SQLITE
def test_captures_plainte_urgence_rappel_digest_et_omissions(moteur, equipe, agent):
    admin = equipe["admin"]
    instant = moteur.horloge.maintenant
    jour = instant.date().isoformat()
    vide = _lire_sans_effet(admin, "digest_vide", DIGEST, {"date_reference": jour})
    assert vide.resultat == f"Absence d'activité enregistrée pour la période de référence {jour}."
    plainte = _sms(agent, "Mes gouttières à Laval fuient encore après vos travaux, je suis très déçu.",
                   "plainte-fictive", instant)
    tid = plainte["transfert"]["transfert_id"]
    lu = _lire_sans_effet(admin, "plainte_ouverte", LIRE, {"transfert_id": tid}).resultat
    assert lu["type_transfert"] == "plainte" and lu["envoye"] is False
    assert lu["brouillon_reponse"] and lu["destinataire"] is None and lu["lead_id"] is None
    assert lu["verdict_destinataire"]["code"] == taxonomie.VERDICT_DESTINATAIRE_NON_CONFIGURE
    assert lu["contact"] == {"telephone": "+15145550142"}
    urgence = _sms(agent, "Il y a de la fumée qui sort du soffite et un fil électrique pend près de la porte.",
                   "urgence-fictive", instant, "+15145550177")
    urgent = _lire_sans_effet(admin, "urgence_ouverte", LIRE,
                            {"transfert_id": urgence["transfert"]["transfert_id"]}).resultat
    assert urgent["type_transfert"] == "urgence" and urgent["niveau"] == "N5" and urgent["envoye"] is False

    appel = agent.appeler("m1_importer_appel_manuellement", {"source": "Journal PBX FICTIF",
        "evenement_id": "appel-event-fictif", "appel_id": "appel-fictif", "recu_le": instant.isoformat(),
        "telephone": "+15145550188", "statut": "manque"})
    assert appel["ok"] is True and appel["resultat"]["envoi_automatique"] is False
    rappel_id = appel["resultat"]["tache_rappel"]["transfert_id"]
    premiere = _lire_sans_effet(admin, "rappel_non_assigne", LIRE, {"transfert_id": rappel_id}).resultat
    assert premiere["suivi_rappel"]["responsable"] is None
    # Préparation fictive par le port métier de console existant, aucune commande mobile ajoutée.
    with stockage.transaction(), contexte.appele_par_appareil(
        contexte.IdentiteAppelante("nathan", "nathan_owner", source="console")
    ):
        prise = m1.consigner_suivi_rappel(rappel_id, "prise_en_charge", premiere["suivi_rappel"]["snapshot_suivi"],
                                       dt.datetime.now(dt.UTC).isoformat())
    assert prise["accepte"] is True
    assigne = _lire_sans_effet(admin, "rappel_assigne", LIRE, {"transfert_id": rappel_id}).resultat
    assert assigne["suivi_rappel"]["responsable"] == "nathan"
    assert assigne["suivi_rappel"]["tentatives_sans_contact"] == 0 and assigne["statut"] == "ouvert"

    telephone = "+15145550199"
    for i in range(6):
        _sms(agent, "Bonjour, voici un message factuel supplémentaire pour votre équipe. " * 8,
             f"couvert-fictif-{i}", instant + dt.timedelta(minutes=i), telephone)
    transferer = agent.appeler("m1_transferer", {
        "type_transfert": "technique", "canal": "sms", "expediteur": telephone,
    })
    assert transferer["ok"] is True and transferer["resultat"]["accepte"] is True
    technique_id = transferer["resultat"]["resultat"]["transfert"]["transfert_id"]
    for i in range(6):
        _sms(agent, "Voici une autre précision factuelle pour votre équipe. " * 8,
             f"suivant-fictif-{i}", instant + dt.timedelta(minutes=10 + i), telephone)
    omis = _lire_sans_effet(admin, "transfert_omissions", LIRE, {"transfert_id": technique_id})
    assert omis.mesure.tronque is False
    assert len(omis.resultat["messages_couverts"]) == len(omis.resultat["messages_suivants"]) == 4
    assert omis.resultat["messages_couverts_omis"] == omis.resultat["messages_suivants_omis"] == 2
    assert all(len(m["texte"]) <= 350 for cle in ("messages_couverts", "messages_suivants") for m in omis.resultat[cle])
    _sms(agent, "STOP", "stop-fictif", instant + dt.timedelta(minutes=25))
    retire = _lire_sans_effet(admin, "plainte_stop", LIRE, {"transfert_id": tid}).resultat
    assert retire["client_retire_des_messages"] is True and retire["brouillon_reponse"] is None
    assert retire["envoye"] is False
    digest = _lire_sans_effet(admin, "digest_date", DIGEST, {"date_reference": jour}).resultat
    assert isinstance(digest, str) and digest.startswith(f"DIGEST - Période de référence : {jour}")
    assert "transferts à un humain ouverts : 4" in digest and "urgences de sécurité : 1, plaintes : 1" in digest
    assert "gouttières" not in digest and "+1514" not in digest
    autre_jour = _lire_sans_effet(admin, "digest_autre_jour", DIGEST, {"date_reference": "2024-02-29"}).resultat
    assert autre_jour.startswith("DIGEST -") and "Absence d'activité" not in autre_jour


@SQLITE
def test_refus_http_dates_inconnus_schema_et_profils(moteur, equipe, agent, monkeypatch):
    admin = equipe["admin"]
    inconnu = _lire_sans_effet(admin, "transfert_inconnu", LIRE, {"transfert_id": "tr-inconnu-fictif"})
    assert inconnu.metier["verdict"]["code"] == "REJ-TRANSFERT-INCONNU"
    invalide = _lire_sans_effet(admin, "digest_date_invalide", DIGEST, {"date_reference": "2026-02-30"})
    assert invalide.metier["verdict"]["code"] == "REJ-DIGEST-DATE-INVALIDE"
    schema = _lire_sans_effet(admin, "digest_argument_source_refuse", DIGEST,
                             {"date_reference": "2026-09-15", "source": "console"})
    assert schema.enveloppe["ok"] is False and schema.enveloppe["erreur"] == "arguments_invalides"
    # Le profil client n'est pas un rôle d'appareil appairable ; sa garde native est testée séparément.
    for role, appareil in [("employee", equipe["employe"]), ("seller", None)]:
        if appareil is None:
            personne = role + ".fictif"
            moteur.creer_personne(personne, "Personne fictive", [role], monkeypatch)
            appareil = moteur.appairer(personne, role)
        for outil in (LIRE, DIGEST):
            args = {"transfert_id": "tr-inconnu-fictif"} if outil == LIRE else {"date_reference": "2026-09-15"}
            refuse = _lire_sans_effet(appareil, f"{role}_{outil}_refuse", outil, args)
            assert refuse.statut == 403 and refuse.ok is False


@SQLITE
@pytest.mark.parametrize("perte", ["role_retire", "inactive"])
def test_meme_appareil_http_admin_retire_refuse_avant_registre(moteur, equipe, agent, monkeypatch, perte):
    admin = equipe["admin"]
    plainte = _sms(agent, "Je suis très déçu, les gouttières fuient encore.", "refus-plainte-fictive",
                   moteur.horloge.maintenant)
    tid = plainte["transfert"]["transfert_id"]
    fragment = moteur._fragment("appareils.json")
    with stockage.transaction() as cnx:
        if perte == "inactive":
            identite.activer(cnx, "nathan", False)
        else:
            identite.retirer_role(cnx, "nathan", "admin")
    lectures = []
    obtenir = m1._obtenir_registre

    def observer():
        lectures.append("registre")
        return obtenir()

    monkeypatch.setattr(m1, "_obtenir_registre", observer)
    for outil in (LIRE, DIGEST):
        args = {"transfert_id": tid} if outil == LIRE else {"date_reference": "2026-09-15"}
        r = _lire_sans_effet(admin, f"{perte}_{outil}", outil, args)
        assert r.statut == 200 and r.metier["accepte"] is False
        assert r.metier["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
        assert "gouttières" not in json.dumps(r.corps, ensure_ascii=False)
    assert lectures == [] and moteur._fragment("appareils.json") == fragment
