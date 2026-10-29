"""Prépare un conseil réel : monde fictif, captures, session, profils ; écrit l'entrée de chaque rôle (fichiers)."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, "/home/user/OPSYS-AI-m9")
D = Path(os.environ["CONSEIL_DIR"]); D.mkdir(parents=True, exist_ok=True)
os.environ["OPSYS_HOME"] = str(D / "opsys"); os.makedirs(D / "opsys", exist_ok=True)
from m2_revenue_crm import outils as m2
from opsys import admission_agents, agents, contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
os.environ[stockage.ENV_URL] = f"sqlite:///{D / 'conseil.db'}"
M9, M2, M6 = "m09-strategic-intelligence", "m02-revenue-crm", "m06-material-control"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
stockage.migrer(); m2.utiliser_stockage_durable()
with stockage.transaction() as cnx:
    identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
    admission_agents.configurer_plafonds_entreprise(cnx, 500_000, 5_000_000, par="admin.fictif", revision_attendue=0)
LEADS = [
 ("lead-1","c-1","renovation_totale","Québec","telephone",False),
 ("lead-2","c-2","isolation_thermique","Lévis","formulaire",True),
 ("lead-3","c-3","ravalement","Québec","courriel",False),
]
for lid,cid,typ,ville,canal,urg in LEADS:
    assert m2.ingerer_lead({"lead_id":lid,"conversation_id":cid,"contact":{"nom":"Contact fictif","courriel":f"{lid}@example.test"},"type_travaux":typ,"ville":ville,"urgence_declaree":urg,"canal":canal},"2026-09-01T09:00:00-04:00")["accepte"]
deps = charger_departements()
cap = Capacites(deps, stockage.transaction, filtre={M9, M2, M6}, memoire=False)
def appel(nom, a):
    with contexte.appele_par_appareil(ADMIN):
        return cap.appeler(nom, a)
def ok(r):
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    return r["resultat"]
ok(appel("m9_capturer_producteur", {"lecture_id": "m2.leads", "arguments": {"horodatage": "2026-10-21T12:00:00Z"}, "horodatage": "2026-10-21T12:00:01Z"}))
ok(appel("m9_capturer_producteur", {"lecture_id": "m6.disponibilite", "arguments": {}, "horodatage": "2026-10-21T12:00:02Z"}))
DOM = ["leads", "stock", "strategie"]
ATT = ["m2.leads", "m6.disponibilite", "m4.interventions"]
Q = "Que devrait faire l'entreprise cette semaine avec les leads reçus et le stock de matériaux ?"
o = ok(appel("m9_ouvrir_conseil", {"question": Q, "domaines": DOM, "importance": "courante", "budget_tokens": 100_000, "reference": "2026-10-21T12:10:00Z", "horodatage": "2026-10-21T12:15:00Z", "attendues": ATT}))
sid = o["session_id"]; roles = [t["role"] for t in o["tours"]]
prop = ok(appel("m9_proposer_profils_conseil", {}))
par_id = {p["id"]: p for p in prop["profils"]}
with stockage.transaction() as cnx:
    for r in roles:
        spec = par_id[f"m9-{r.replace('_','-')}"]
        agents.creer(cnx, deps, spec, par="admin.fictif", mutation_id=f"creer-{r}-0001")
        agents.definir_actif(cnx, spec["id"], deps, True, par="admin.fictif", mutation_id=f"activer-{r}-0001", revision_attendue=1)
faits, depart = {}, 0
while depart is not None:
    p = ok(appel("m9_apercu_dossier_strategique", {"question": Q, "domaines": DOM, "reference": "2026-10-21T12:10:00Z", "attendues": ATT, "depart": depart}))
    faits |= p["faits"]; depart = p["prochain_depart"]
json.dump({"session_id": sid, "roles": roles, "question": Q}, open(D / "session.json", "w"), ensure_ascii=False, indent=1)
json.dump(faits, open(D / "faits.json", "w"), ensure_ascii=False, indent=1)
for r in roles:
    morceaux, depart = [], 0
    while depart is not None:
        e = ok(appel("m9_lire_entree_tour_conseil", {"session_id": sid, "role": r, "depart": depart}))
        morceaux.append(e["contenu_json"]); depart = e.get("prochain_depart")
    (D / f"entree-{r}.json").write_text("".join(morceaux))
print(sid, roles, len(faits), {r: (D / f"entree-{r}.json").stat().st_size for r in roles})
