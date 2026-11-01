"""Plusieurs PROCESSUS (pas seulement des fils) se disputent l'envoi d'un brouillon approuvé : un seul message part.

Les processus partagent la base SQLite (fichier), le coffre et la clé d'ingestion de l'instance de test ; leur transport
est un double qui note chaque envoi dans un fichier (ajout atomique). Aucun réseau. Données fictives."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time

import cablage_qa as cq
import courriel_qa as qa
import pytest

from opsys import stockage
from opsys.courriel_connecteurs import envoi

FICTIF = True
SCRIPT = textwrap.dedent('''
    import os, sys, time
    from opsys import service_acteur_systeme as systeme
    from opsys.connecteurs_planification import bail, hote, planificateur
    from opsys.connecteurs_planification.exec_courriel import Envoi
    from opsys.courriel_connecteurs.transport import ReponseHttp

    JOURNAL, DEPART = sys.argv[1], float(sys.argv[2])


    class Transport:
        def envoyer(self, requete):
            if requete.url.endswith("/messages/send"):
                fd = os.open(JOURNAL, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                os.write(fd, b"envoi\\n")
                os.close(fd)
                return ReponseHttp(200, {"content-type": "application/json"},
                                   b'{"id": "e1", "threadId": "t1", "labelIds": ["SENT"]}')
            raise AssertionError("requête inattendue : " + requete.url)


    environ = {"OPSYS_COURRIEL_REDIRECT_URI": "https://opsys.example.test/oauth/callback",
               "OPSYS_COURRIEL_GMAIL_CLIENT_ID": "client-fictif.apps.example.test"}
    service = hote.construire_service(environ, transport=Transport())
    ports = planificateur.Ports(service_courriel=lambda: service)
    with systeme.contexte_planificateur() as acteur:
        ctx = planificateur.Contexte(ports, acteur, "processus-%d" % os.getpid(), None, time.time())
        executeur = Envoi()
        ressources = executeur.ressources(ctx)
        while time.time() < DEPART:
            time.sleep(0.001)
        for ressource in ressources:
            b = bail.acquerir(executeur.cle_bail(ressource), ctx.porteur, 60)
            if b is None:
                print("bail_refuse")
                continue
            try:
                print("traite", executeur.traiter(ressource, ctx, b))
            finally:
                bail.liberer(b)
''')


@pytest.fixture
def c(tmp_path, monkeypatch):
    mon = cq.monter(tmp_path, monkeypatch, scope_google=qa.SCOPE_GMAIL_LECTURE + " " + qa.SCOPE_GMAIL_ENVOI)
    qa.creer_compte(mon.monde, usage="lecture_envoi", configuration={"reception_m1": 1})
    qa.connecter_oauth(mon.monde)
    yield mon
    cq.demonter()


def test_six_processus_en_meme_temps_un_seul_message_part(c, tmp_path):
    c.monde.gmail.ajouter(cq.courriel_client(1))
    c.activer("courriel.synchro")
    c.tour()
    c.monde.gmail.ajouter(cq.courriel_client(2))
    c.tour()
    signal = next(ligne for ligne in cq.lignes_m1() if ligne["type_entree"] == "reception_courriel_connecteur_v1")
    reponse = c.capacites.appeler("m1_preparer_reponse_courriel", {"signal_id": signal["signal_id"],
                                                                   "corps": "Bonjour, merci de votre message."})
    bid = reponse["resultat"]["resultat"]["brouillon_id"]
    demande = c.capacites.appeler("m1_demander_envoi_courriel", {"brouillon_id": bid, "contexte": "suite à sa demande"})
    c.decider(demande["resultat"]["resultat"]["demande_id"])
    script = tmp_path / "enfant.py"
    script.write_text(SCRIPT, encoding="utf-8")
    journal = tmp_path / "envois.log"
    depart = time.time() + 6.0
    enfants = [subprocess.Popen([sys.executable, str(script), str(journal), str(depart)], env=dict(os.environ),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(6)]
    sorties = [e.communicate(timeout=120) for e in enfants]
    assert [e.returncode for e in enfants] == [0] * 6, [s[1][-600:] for s in sorties]
    assert journal.read_text().splitlines() == ["envoi"]  # UN seul message parti, malgré six processus
    with stockage.transaction() as cnx:
        assert envoi.statut_brouillon(cnx, bid)["statut"] == "ENVOYE"
    assert sum("traite" in s[0] for s in sorties) >= 1
