import json, os, sys
from pathlib import Path
sys.path.insert(0, "/home/user/OPSYS-AI-m9")
D = Path(os.environ["CONSEIL_DIR"]); os.environ["OPSYS_HOME"] = str(D / "opsys")
from m2_revenue_crm import outils as m2
from opsys import contexte, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
os.environ[stockage.ENV_URL] = f"sqlite:///{D / 'conseil.db'}"
stockage.migrer(); m2.utiliser_stockage_durable()
cap = Capacites(charger_departements(), stockage.transaction, filtre={"m09-strategic-intelligence", "m02-revenue-crm", "m06-material-control"}, memoire=False)
sid = json.load(open(D / "session.json"))["session_id"]
def appel(n, a):
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin", source="console")): return cap.appeler(n, a)
c = appel("m9_cloturer_conseil", {"session_id": sid, "horodatage": "2026-10-21T12:30:00Z"})
json.dump(c, open(D / "cloture.json", "w"), ensure_ascii=False, indent=1)
r = c["resultat"]
print(json.dumps({k: r.get(k) for k in ("accepte", "rejoue")}), json.dumps(r["cloture"], ensure_ascii=False)[:500])
print(json.dumps(r.get("gouvernance"), ensure_ascii=False)[:900])
morceaux, depart = [], 0
while depart is not None:
    p = appel("m9_lire_rapport_conseil", {"session_id": sid, "depart": depart})["resultat"]
    morceaux.append(p["contenu_json"]); depart = p["prochain_depart"]
rapport = json.loads("".join(morceaux)); json.dump(rapport, open(D / "rapport-v2.json", "w"), ensure_ascii=False, indent=1)
print(rapport["statut_contrat"], [ (k, (v.get("statut") if isinstance(v, dict) else None)) for k, v in rapport.get("sections", {}).items()][:25])
