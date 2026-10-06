"""Serveur M10 réel de test TCP/Core : données fictives, aucune exécution d'outil source."""
from __future__ import annotations

import json
import os
import sys

PROFILE = "it-postflight"


def prepare() -> None:
    from opsys import agents, identite, stockage
    from opsys.departements import charger_departements

    stockage.migrer()
    deps = charger_departements()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "pf-it-admin", "Admin fictif", "synthetic-pf-password-2026", ["admin"])
        agents.creer(cnx, deps, {
            "id": PROFILE, "departement": "m03-estimation", "responsabilite": "Profil TCP fictif POSTFLIGHT.",
            "palier_modele": "standard", "outils": ["m3_estimer_projet", "m3_creer_devis", "m3_marquer_devis_accepte"],
            "budget_jour": 100, "budget_mois": 1_000, "limite_tours": 2,
            "limite_reessais": 1, "limite_concurrence": 1, "declencheurs": [{"type": "manuel"}],
        }, par="pf-it-admin", mutation_id="pf-it-create")
        agents.definir_actif(cnx, PROFILE, deps, True, par="pf-it-admin",
                            mutation_id="pf-it-activate", revision_attendue=1)
    print(json.dumps({"profile_id": PROFILE, "revision": 2}))


def inspect() -> None:
    from m10_memoire import outils

    from opsys import agents, stockage

    with stockage.transaction() as cnx:
        rows = list(stockage.maillons("m10-memoire", "affaires"))
        if len(rows) > 128:
            raise ValueError("borne du registre fictif dépassée")
        facts = [{key: row[key] for key in ("cle_depot", "affaire_id", "departement_source", "outil", "resultat")}
                 for row in rows if row.get("type_entree") == "fait_candidat"]
        valid, _ = outils._REGISTRE_AFFAIRES.valider_chaine()
        profile = agents.obtenir(cnx, PROFILE)
    if profile is None:
        raise ValueError("profil fictif absent")
    print(json.dumps({"facts": facts, "chain_valid": valid,
                      "profile_revision": profile["revision"], "profile_active": profile["actif"]}))


def revoke() -> None:
    from opsys import agents, stockage
    from opsys.departements import charger_departements

    with stockage.transaction() as cnx:
        profile = agents.obtenir(cnx, PROFILE)
        if profile is None:
            raise ValueError("profil fictif absent")
        agents.definir_actif(cnx, PROFILE, charger_departements(), False, par="pf-it-admin",
                            mutation_id="pf-it-revoke", revision_attendue=profile["revision"])


def serve() -> None:
    import uvicorn

    from opsys import stockage
    from opsys.departements import charger_departements
    from opsys.serveur_mcp import application_http_departements

    app = application_http_departements(
        charger_departements(), stockage.transaction, os.environ["OPSYS_MCP_JETON"],
        hote="127.0.0.1", jeton_contexte=os.environ["OPSYS_CONTEXT_MCP_JETON"],
    )
    # The OS assigns the port; the parent reads Uvicorn's actual readiness event.
    uvicorn.run(app, host="127.0.0.1", port=0, access_log=False, log_level="info")


if __name__ == "__main__":
    action = sys.argv[1]
    actions = {"prepare": prepare, "inspect": inspect, "revoke": revoke, "serve": serve}
    if action not in actions:
        raise ValueError("action fixture inconnue")
    actions[action]()
