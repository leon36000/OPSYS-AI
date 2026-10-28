"""Ports d'outils du dossier de paie préparatoire : vrai dispatcher, vrai transport MCP HTTP, refus agents (fictif).

Les outils M5 du dossier sont propriétaire-console uniquement : aucun appareil ni agent n'y a accès, et ce chantier
n'accorde aucun grant Core. Ce fichier prouve le REFUS par les vraies voies (dispatcher `Capacites`, serveur MCP HTTP) ;
les parcours nominaux sont dans `test_console_paie_dossier.py` (application HTTP intégrée).
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import anyio
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from sqlalchemy import select

from opsys import contexte, identite
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.serveur_mcp import application_http_departements
from opsys.stockage.schema import META

ROOT = Path(__file__).resolve().parents[1]
for chemin in (ROOT / "departments/m05-financecore/src", ROOT / "departments/m05-financecore/tests"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from fixtures_dossier_paie import entrees  # noqa: E402

FICTIF = True
OUTILS_DOSSIER = {
    "m5_apercu_dossier_paie",
    "m5_conserver_version_dossier_paie",
    "m5_rouvrir_dossier_paie",
    "m5_revue_dossier_paie",
    "m5_exporter_dossier_paie",
    "m5_lire_dossier_paie",
    "m5_verifier_dossier_paie",
    "m5_lire_export_dossier_paie",
}
LISTE = {"dossier_id": None, "numero": None, "comparer_a": None}
JETON_METIER = "jeton-metier-dossier-paie-fictif-suffisamment-long"
JETON_CONTEXTE = "jeton-contexte-dossier-paie-fictif-distinct-long"


@pytest.fixture
def base(session):
    import m5_financecore.outils as m5_outils

    m5_outils.utiliser_stockage_durable()
    with session() as cnx:
        identite.creer_personne(
            cnx, "owner-integre-fictif", "Owner fictif", "owner-integre-password", ["admin", "nathan_owner"]
        )
        identite.creer_personne(cnx, "admin-integre-fictif", "Admin fictif", "admin-integre-password", ["admin"])
        identite.creer_personne(
            cnx, "employe-integre-fictif", "Employé fictif", "employe-integre-password", ["employee"]
        )
    return session


def _etat(session):
    with session() as cnx:
        return {
            nom: sorted(repr(tuple(ligne)) for ligne in cnx.execute(select(t)).all()) for nom, t in META.tables.items()
        }


def _capacites(session):
    return Capacites(
        charger_departements(), session, filtre={"m05-financecore"}, appelant="m05-financecore", memoire=False
    )


def test_les_huit_outils_sont_fermes_aux_appareils_et_declares_t0(base):
    capacites = _capacites(base)
    for nom in OUTILS_DOSSIER:
        departement, outil = capacites.index[nom]
        assert departement is not None and outil.roles_appareil == frozenset(), nom
        schema = outil.parametres
        assert schema["additionalProperties"] is False
        # Un paramètre `horodatage` de la fonction doit être déclaré (la console l'injecte, jamais l'humain).
        import inspect

        parametres_fonction = set(inspect.signature(outil.fonction).parameters)
        assert parametres_fonction == set(schema["properties"]), nom
        assert set(schema["required"]) <= set(schema["properties"])
        if "horodatage" in parametres_fonction:
            assert "horodatage" in schema["required"]


@pytest.mark.parametrize(
    "identite_appelante",
    [
        None,
        contexte.IdentiteAppelante("owner-integre-fictif", "nathan_owner", source="appareil"),
        contexte.IdentiteAppelante("owner-integre-fictif", "admin", source="console"),
        contexte.IdentiteAppelante("admin-integre-fictif", "admin", source="console"),
        contexte.IdentiteAppelante("employe-integre-fictif", "employee", source="console"),
    ],
)
def test_dispatcher_refuse_tout_sauf_le_proprietaire_console(base, identite_appelante):
    capacites = _capacites(base)
    avant = _etat(base)
    appels = {
        "m5_lire_dossier_paie": LISTE,
        "m5_apercu_dossier_paie": {"employee_person_id": "employe-integre-fictif", "entrees": entrees()},
        "m5_verifier_dossier_paie": {"dossier_id": "a" * 32, "numero": None},
    }
    for nom, arguments in appels.items():
        if identite_appelante is None:
            reponse = capacites.appeler(nom, arguments)
        else:
            with (
                contexte.appele_par_appareil(identite_appelante),
                contexte.appeler_en_tant_que("m05-financecore", origine="m05-financecore"),
            ):
                reponse = capacites.appeler(nom, arguments)
        texte = json.dumps(reponse, ensure_ascii=False)
        assert reponse.get("ok") is False or reponse.get("resultat", {}).get("accepte") is False, (nom, reponse)
        assert "mention" not in texte and "dossiers" not in texte and "montant" not in texte, (nom, texte)
    assert _etat(base) == avant


def test_dispatcher_sert_le_proprietaire_console_vivant_puis_le_refuse_une_fois_revoque(base):
    capacites = _capacites(base)
    proprietaire = contexte.IdentiteAppelante("owner-integre-fictif", "nathan_owner", source="console")
    with (
        contexte.appele_par_appareil(proprietaire),
        contexte.appeler_en_tant_que("m05-financecore", origine="m05-financecore"),
    ):
        reponse = capacites.appeler("m5_lire_dossier_paie", LISTE)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["resultat"]["dossiers"] == []
    with base() as cnx:
        identite.retirer_role(cnx, "owner-integre-fictif", "nathan_owner")
    with (
        contexte.appele_par_appareil(proprietaire),
        contexte.appeler_en_tant_que("m05-financecore", origine="m05-financecore"),
    ):
        refuse = capacites.appeler("m5_lire_dossier_paie", LISTE)
    assert refuse.get("ok") is False or refuse["resultat"].get("accepte") is False


@pytest.fixture
def serveur_mcp(base):
    departements = charger_departements(ROOT / "departments")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = application_http_departements(
        departements,
        base,
        JETON_METIER,
        hote="127.0.0.1",
        jeton_contexte=JETON_CONTEXTE,
    )
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    for _ in range(100):
        if serveur.started:
            break
        time.sleep(0.05)
    assert serveur.started
    yield f"http://127.0.0.1:{port}"
    serveur.should_exit = True
    fil.join(timeout=5)
    assert not fil.is_alive()


def test_transport_mcp_http_un_agent_ne_recoit_ni_montant_ni_ecriture(serveur_mcp, base):
    """Agent M5 authentifié par jeton métier sur le vrai serveur MCP HTTP : refus, aucun montant, aucune écriture."""
    avant = _etat(base)

    async def scenario():
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON_METIER}"})
        async with (
            http,
            streamable_http_client(f"{serveur_mcp}/mcp/m05-financecore", http_client=http) as flux,
            ClientSession(flux[0], flux[1]) as client,
        ):
            await client.initialize()
            visibles = {t.name for t in (await client.list_tools()).tools}
            reponses = {}
            for nom, arguments in (
                ("m5_lire_dossier_paie", LISTE),
                ("m5_apercu_dossier_paie", {"employee_person_id": "employe-integre-fictif", "entrees": entrees()}),
            ):
                if nom in visibles:
                    resultat = await client.call_tool(nom, arguments)
                    reponses[nom] = (resultat.is_error, resultat.content[0].text if resultat.content else "")
            return visibles, reponses

    visibles, reponses = anyio.run(scenario)
    # Soit l'outil n'est pas exposé à l'agent, soit son appel est refusé : jamais un montant ni un dossier.
    for nom, (est_erreur, texte) in reponses.items():
        enveloppe = json.loads(texte) if texte.startswith("{") else {}
        refuse = est_erreur or enveloppe.get("ok") is False or enveloppe.get("resultat", {}).get("accepte") is False
        assert refuse, (nom, texte)
        assert "mention" not in texte and "dossiers" not in texte and "1002" not in texte
    assert _etat(base) == avant
    # Les huit outils sont listés sur le serveur MCP du département (comme le brut régulier) : leur appel est refusé.
    assert set(reponses) == {"m5_lire_dossier_paie", "m5_apercu_dossier_paie"}
    assert all(est_erreur for est_erreur, _ in reponses.values())
