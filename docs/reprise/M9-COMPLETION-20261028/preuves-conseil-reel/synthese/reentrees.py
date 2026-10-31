"""Réécrit l'entrée de rôles donnés (consigne à jour) dans <ronde>/entree-<role>.json, depuis la base de la session."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, "/home/user/OPSYS-AI-m9")
D = Path(os.environ["CONSEIL_DIR"]); ronde = sys.argv[1]; roles = sys.argv[2:]
os.environ["OPSYS_HOME"] = str(D / "opsys")
from m2_revenue_crm import outils as m2
from opsys import contexte, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
os.environ[stockage.ENV_URL] = f"sqlite:///{D / 'conseil.db'}"
stockage.migrer(); m2.utiliser_stockage_durable()
cap = Capacites(charger_departements(), stockage.transaction, filtre={"m09-strategic-intelligence", "m02-revenue-crm", "m06-material-control"}, memoire=False)
sid = json.load(open(D / "session.json"))["session_id"]
(D / ronde).mkdir(exist_ok=True)
for r in roles:
    morceaux, depart = [], 0
    while depart is not None:
        with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin", source="console")):
            e = cap.appeler("m9_lire_entree_tour_conseil", {"session_id": sid, "role": r, "depart": depart})
        assert e["ok"] is True and e["resultat"]["accepte"] is True, e
        morceaux.append(e["resultat"]["contenu_json"]); depart = e["resultat"].get("prochain_depart")
    (D / ronde / f"entree-{r}.json").write_text("".join(morceaux))
    print(r, len("".join(morceaux)))
