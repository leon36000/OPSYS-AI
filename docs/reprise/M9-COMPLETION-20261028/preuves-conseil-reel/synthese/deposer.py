"""Dépose les sorties RÉELLES de modèles (verbatim) par les outils M9 ; réserve/réconcilie l'usage comme le runtime natif."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, "/home/user/OPSYS-AI-m9")
D = Path(os.environ["CONSEIL_DIR"]); ronde = sys.argv[1]; roles_tokens = json.loads(sys.argv[2]); exec_tag = sys.argv[3]
os.environ["OPSYS_HOME"] = str(D / "opsys")
from m2_revenue_crm import outils as m2
from opsys import admission_agents, contexte, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
os.environ[stockage.ENV_URL] = f"sqlite:///{D / 'conseil.db'}"
stockage.migrer(); m2.utiliser_stockage_durable()
M9, M2, M6 = "m09-strategic-intelligence", "m02-revenue-crm", "m06-material-control"
deps = charger_departements(); cap = Capacites(deps, stockage.transaction, filtre={M9, M2, M6}, memoire=False)
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
def appel(nom, a):
    with contexte.appele_par_appareil(ADMIN): return cap.appeler(nom, a)
sid = json.load(open(D / "session.json"))["session_id"]
resultats = {}
for role, tokens in roles_tokens.items():
    sortie = json.load(open(D / ronde / f"sortie-{role}.json"))
    agent_id = f"m9-{role.replace('_', '-')}"
    info = {"tokens_reconcilies_estimation_deterministe": tokens}
    try:
        with stockage.transaction() as cnx:
            res = admission_agents.reserver(cnx, agent_id, deps, f"exec-{exec_tag}-{role}", f"cle-{exec_tag}-{role}", 6000, tours=1, reessais=0)
            info["reservation_id"] = res["id"]
            try:
                info["reconciliation"] = admission_agents.concilier(cnx, res["id"], tokens)
            except Exception as e:  # noqa: BLE001 — on garde le refus tel quel
                info["reconciliation_refusee"] = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001
        info["reservation_refusee"] = f"{type(e).__name__}: {e}"
    if "reservation_id" in info:
        r = appel("m9_deposer_tour_conseil", {"session_id": sid, "role": role, "sortie": sortie, "reservation_id": info["reservation_id"], "horodatage": "2026-10-21T12:20:00Z"})
        info["depot"] = r
    resultats[role] = info
json.dump(resultats, open(D / ronde / "depots.json", "w"), ensure_ascii=False, indent=1, default=str)
for role, info in resultats.items():
    d = info.get("depot")
    print(role, "|", info.get("reconciliation_refusee") or info.get("reservation_refusee") or "", "|", json.dumps(d, ensure_ascii=False)[:420] if d else None)
