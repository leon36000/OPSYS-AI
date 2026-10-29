"""QA navigateur réel du tableau de bord M9 (données fictives, base SQLite privée, serveur local éphémère)."""
import datetime as dt, json, os, sys, threading, time
from pathlib import Path

sys.path.insert(0, "/home/user/OPSYS-AI-m9")
BASE = Path(os.environ["QA_DIR"])
os.environ["OPSYS_HOME"] = str(BASE / "opsys")
import uvicorn

from m2_revenue_crm import outils as m2
from opsys import contexte, etat, identite, stockage
from opsys.capacites import Capacites
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements

M9, M2 = "m09-strategic-intelligence", "m02-revenue-crm"
MDP = "mot-de-passe-direction-fictif"
XSS = "<img src=x onerror=alert('xss')>"
os.environ[stockage.ENV_URL] = f"sqlite:///{BASE / 'qa.db'}"
stockage.migrer(); m2.utiliser_stockage_durable()
with stockage.transaction() as cnx:
    identite.creer_personne(cnx, "admin.fictif", "Admin", MDP, ["admin", "nathan_owner"])
m2.ingerer_lead({"lead_id": "lead-1", "conversation_id": "c-1", "contact": {"nom": "C", "courriel": "c@example.test"},
    "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone"}, "2026-09-01T09:00:00-04:00")
deps = charger_departements()
cap = Capacites(deps, stockage.transaction, filtre={M9, M2}, memoire=False)
def appel(nom, a):
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin", source="console")):
        return cap.appeler(nom, a)
assert appel("m9_capturer_producteur", {"lecture_id": "m2.leads", "arguments": {"horodatage": "2026-10-21T12:00:00Z"}, "horodatage": "2026-10-21T12:00:01Z"})["ok"]
faits = appel("m9_apercu_dossier_strategique", {"question": "Plan", "domaines": ["strategie"], "reference": "2026-10-21T13:00:00Z"})["resultat"]["faits"]
(statut,) = [a for a in faits if a.endswith("leads[0].statut")]
r = appel("m9_enregistrer_plan", {"plan": {"plan_id": "plan-qa", "objectif": f"Qualifier {XSS}", "porteur": "vendeur.fictif", "echeance": "2026-10-30",
    "resultats_cles": [{"id": "qualifie", "libelle": "Lead qualifié", "lecture": "m2.leads", "chemin": "resultat.resultat.leads[*].statut", "operateur": "==", "cible": "qualifie"}],
    "sources": [statut], "decision_ref": "decision-1"}, "reference": "2026-10-21T13:00:00Z", "horodatage": "2026-10-21T13:00:00Z"})
assert r["ok"] and r["resultat"]["accepte"], r

app = application.creer_application(Configuration("signature-qa-navigateur-fictive-" + "x" * 32), deps, etat.session)
serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning"))
threading.Thread(target=serveur.run, daemon=True).start()
for _ in range(100):
    if serveur.started: break
    time.sleep(0.1)

print("PRET", flush=True)
while not Path(os.environ["QA_DIR"], "stop").exists():
    time.sleep(0.5)
serveur.should_exit = True
