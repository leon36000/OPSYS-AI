"""T4.21 : quatre lectures M9 admin, HTTP MCP réel ; porte Core simulée en Python, pas rendu téléphone."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import pytest
from harnais_e2e import Moteur
from m9_strategic_intelligence.outils import outils as outils_m9
from sqlalchemy import text, update

from opsys import approbations, evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import Niveau, executer_atomique
from opsys.stockage.schema import APPROBATIONS

FICTIF = True
MAINTENANT = "2026-10-06T07:00:00-04:00"
RACINE = Path(__file__).resolve().parents[2]
FIXTURE = RACINE / "mobile/src/m9/fixtures/reponses-moteur.json"
OUTILS = (
    "m9_produire_briefing_matin", "m9_lire_suite_briefing", "m9_lire_alertes_m8", "m9_lire_etat_consolide",
)
SQLITE = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)


def empreinte_tables() -> str:
    with stockage.transaction() as cnx:
        noms = cnx.execute(text("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name NOT LIKE 'sqlite_%' ORDER BY name")).scalars().all()
        tables = {nom: sorted([dict(ligne) for ligne in cnx.execute(text(f'SELECT * FROM "{nom}"')).mappings()],
                              key=lambda ligne: json.dumps(ligne, sort_keys=True, default=str)) for nom in noms}
    return hashlib.sha256(json.dumps(tables, sort_keys=True, default=str).encode()).hexdigest()


def preparer_sources() -> None:
    with stockage.transaction() as cnx:
        for numero in range(40):
            ident = approbations.creer_demande(
                cnx, "m06-material-control", "m6_creer_bon_commande", {"fournisseur": f"fictif-{numero}"},
                niveau=Niveau.N4, motif="réapprovisionnement fictif",
            )
            cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
                cree_le=(dt.datetime(2026, 10, 1, tzinfo=dt.UTC) + dt.timedelta(minutes=numero)).isoformat()))
    ingester = next(o for o in outils_m9() if o.nom == "m9_etat_consolide")
    for valeur in ["245", "246"]:
        executer_atomique(ingester, {"snapshot": {
            "module_source": "m04-field-ops", "horodatage": "2026-10-05T18:00:00Z",
            "valeurs": {"m4_wct_id": "wct-fictif", "m4_duree_reelle_minutes": valeur},
        }})
    for numero in range(20):
        ident = f"m8-alerte-m8_ecart_duree_pct-MESURE-SEUIL-FRANCHI-fictif-{numero:03d}"
        evenements.publier("m8.alerte_proposee", "m08-analytics", {
            "evenement_id": ident, "metric_id": "m8_ecart_duree_pct", "type_alerte": "MESURE-SEUIL-FRANCHI",
            "quoi": f"Écart de durée du chantier wct-fictif-{numero} : 100.00 %.", "a_qui": "m04-field-ops",
            "pourquoi": "100.00 % atteint le seuil déclaré 50.00 %.",
            "preuve": {"metric_id": "m8_ecart_duree_pct", "wct_id": f"wct-fictif-{numero}",
                       "valeur": "100.00", "unite": "pourcentage", "sens": "au_dessus", "seuil": "50.00",
                       "version_definition": "a" * 64},
            "source": "M4 m4.travaux_termines ; M3 m3.devis_accepte", "horodatage_reference": MAINTENANT,
        }, evenement_id=ident)
    departements = charger_departements(RACINE / "departments")
    bilan = evenements.repartir({"m09-strategic-intelligence": departements["m09-strategic-intelligence"]},
                               maintenant="2026-10-06T12:00:00Z")
    assert bilan["echecs"] == 0 and bilan["quarantaines"] == 0
    assert len(stockage.maillons("m09-strategic-intelligence", "alertes_m8")) == 20


def forme(valeur):
    if isinstance(valeur, dict):
        return {cle: forme(v) for cle, v in sorted(valeur.items())}
    if isinstance(valeur, list):
        return [forme(valeur[0])] if valeur else []
    return "null" if valeur is None else type(valeur).__name__


@SQLITE
def test_quatre_lectures_admin_et_fixture_native(moteur: Moteur, equipe):
    preparer_sources()
    portes = equipe["admin"]
    reponses = {}
    appels = {}

    def lire(nom, outil, args):
        avant = empreinte_tables()
        reponse = portes.appeler(outil, args)
        assert reponse.statut == 200 and reponse.enveloppe["ok"] is True, reponse.corps
        assert not reponse.mesure.tronque and reponse.mesure.octets_texte < 6000
        assert empreinte_tables() == avant, "une lecture M9 ne doit modifier aucune table"
        reponses[nom] = reponse.enveloppe
        appels[nom] = {"outil": outil, "args": args}
        return reponse.enveloppe["resultat"]

    briefing = lire("briefing", OUTILS[0], {"maintenant": MAINTENANT})
    for section in ["decisions_en_attente", "alertes_m8", "faits_veille"]:
        depart = len(briefing["sections"][section]["items"])
        if briefing["affichage"]["non_affiches"][section]:
            lire(f"suite_{section}", OUTILS[1], {"maintenant": MAINTENANT, "section": section, "depart": depart})
    lire("alertes", OUTILS[2], {"depart": 0})
    lire("etat", OUTILS[3], {})
    export = {"fictif": True, "maintenant": MAINTENANT, "appels": appels, "reponses": reponses}
    destination = os.environ.get("OPSYS_BRIEFING_FIXTURE_OUTPUT")
    if destination:
        with Path(destination).open("x", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2)
            f.write("\n")
    else:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert fixture["fictif"] and fixture["appels"] == appels
        assert {nom: forme(valeur) for nom, valeur in reponses.items()} == {
            nom: forme(valeur) for nom, valeur in fixture["reponses"].items()
        }


@SQLITE
@pytest.mark.parametrize("role", ["employee", "seller"])
def test_autres_roles_refuses_sans_mutation(moteur: Moteur, monkeypatch, role):
    ident = f"personne-{role}-fictive"
    moteur.creer_personne(ident, f"Profil {role} fictif", [role], monkeypatch)
    porte = moteur.appairer(ident, role)
    arguments = [
        {"maintenant": MAINTENANT},
        {"maintenant": MAINTENANT, "section": "decisions_en_attente", "depart": 0},
        {"depart": 0}, {},
    ]
    avant = empreinte_tables()
    for outil, args in zip(OUTILS, arguments, strict=True):
        assert porte.appeler(outil, args).statut == 403
        assert empreinte_tables() == avant
