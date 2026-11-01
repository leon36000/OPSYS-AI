#!/usr/bin/env python3
"""Peuple une instance avec le code d'une VERSION PRÉCÉDENTE (arbre `git archive` monté sur PYTHONPATH) : base à sa
révision d'alors (0038), avec des données fictives (une personne, un lead, une soumission). Sert à la preuve de mise à
jour : la base est écrite par l'ancien logiciel, puis migrée par le courant. Aucune API récente n'y est utilisée.
Sortie : un objet JSON (révision, comptes) ; code 0 seulement si tout est écrit."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path


def main() -> int:
    from m1_front_office import outils as m1_outils
    from m2_revenue_crm import outils as m2_outils
    from sqlalchemy import text

    import opsys
    from opsys import evenements, identite, stockage, taxonomie
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements
    from opsys.outils import executer_atomique

    mdp = Path(sys.argv[1]).read_text().strip()
    revision = stockage.migrer()
    deps = charger_departements()
    m1_outils.utiliser_stockage_durable()
    m2_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", mdp, ["nathan_owner"])
    taxonomie.enregistrer_services([{"code": "entretien_fictif", "libelle": "Entretien fictif",
                                     "mots_cles": ["entretien", "soumission"]}], par="banc")
    taxonomie.enregistrer_zone_desservie(["Laval"], par="banc")
    cap = Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    rep = cap.appeler("m1_recevoir_message_canal", {
        "canal": "sms", "expediteur": "+15145550143", "message_id": "SMfictif-ancien-0001",
        "recu_le": "2026-10-20T09:15:00-04:00", "texte": "Bonjour, une soumission pour un entretien fictif à Laval."})
    lead_id = rep["resultat"]["lead"]["lead_id"]
    for _ in range(8):
        if evenements.repartir(deps, maintenant=dt.datetime.now(dt.UTC).isoformat())["livres"] == 0:
            break

    def outil(dep: str, nom: str):
        return {o.nom: o for o in deps[dep].charger_outils()}[nom]

    executer_atomique(outil("m02-revenue-crm", "m2_transitionner_statut"), {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": "2026-10-20T11:00:00-04:00",
        "owner": "Alice Vendeuse (fictif)",
        "prochaine_action": {"description": "Préparer la soumission (fictif)", "echeance": "2026-10-22T09:00:00-04:00"}})
    devis = executer_atomique(outil("m03-estimation", "m3_creer_devis"), {
        "devis_id": "DEVIS-ANCIEN-1", "lead_id": lead_id, "chantier_id": None,
        "lignes": [{"description": "Service d'entretien (fictif)", "quantite": "4", "unite": "h",
                    "cout_unitaire": "50.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.25", "horodatage": "2026-10-20T15:00:00-04:00", "prix_total": "250.00"})
    with stockage.transaction() as cnx:
        tables = cnx.execute(text("SELECT count(*) FROM sqlite_master WHERE type='table'")).scalar_one()
    ok = devis.get("ok") is True and revision != "aucune"
    print(json.dumps({"code_source": os.path.dirname(opsys.__file__), "revision": revision, "tables": tables,
                      "lead_id": lead_id, "devis_ok": devis.get("ok")}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
