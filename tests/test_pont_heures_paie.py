"""Tests ciblés de la composition privée M5 → lecture M4."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from opsys import contexte
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Outil, executer

ARGS = {
    "technicien_id": "employe-fictif",
    "debut": "2026-09-14",
    "fin": "2026-09-14",
    "fuseau": "America/Montreal",
}
PERIODE_M4 = {"debut": "2026-09-14", "fin": "2026-09-14", "fuseau": "America/Montreal"}
_ROOT = Path(__file__).resolve().parents[1]


def _amorcer_donnees_reelles(session):
    from m4_field_ops import registre as registre_m4
    from m4_field_ops.outils import outils as outils_m4
    from m5_financecore.outils import outils as outils_m5

    from opsys import approbations, identite, stockage
    from opsys.departements import charger_departements, lire_manifeste
    from opsys.outils import executer_atomique

    owner = "owner-paie-fictif"
    employee = "employe-paie-fictif"
    with session() as cnx:
        identite.creer_personne(
            cnx, owner, "Owner paie fictif", "owner-paie-fictif-password", ["admin", "nathan_owner"]
        )
        identite.creer_personne(cnx, employee, "Employé paie fictif", "employe-paie-fictif-password", ["employee"])
    registre = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
    for maillon in (
        {
            "type_entree": "transition_statut",
            "intervention_id": "I-paie-fictif",
            "statut": "en_route",
            "horodatage": "2026-09-14T12:45:00+00:00",
        },
        {
            "type_entree": "pointage",
            "intervention_id": "I-paie-fictif",
            "technicien_id": employee,
            "action": "arrivee",
            "horodatage": "2026-09-14T13:00:00+00:00",
        },
        {
            "type_entree": "pointage",
            "intervention_id": "I-paie-fictif",
            "technicien_id": employee,
            "action": "depart",
            "horodatage": "2026-09-14T15:00:00+00:00",
        },
    ):
        registre.ajouter(maillon)

    deps = charger_departements()
    outils_m4 = {outil.nom: outil for outil in outils_m4()}
    args_m4 = {"technicien_id": employee, **PERIODE_M4}
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante(owner, "admin")),
        contexte.appeler_en_tant_que("m04-field-ops", origine="m04-field-ops"),
    ):
        preview = executer_atomique(outils_m4["m4_previsualiser_heures_regulieres"], args_m4)
    assert preview["resultat"]["accepte"] is True, preview
    proposition = preview["resultat"]["resultat"]
    args_validation = {
        **args_m4,
        "empreinte_sources": proposition["empreinte_sources"],
        "categories_minutes": proposition["categories_minutes"],
        "details_intervalles": proposition["details_intervalles"],
        "sources": proposition["sources"],
        "validation_precedente_attendue": proposition["validation_precedente"],
        "couverture_complete": True,
        "classification_reguliere_confirmee": True,
        "dispositions": {
            cle: {"inclure": cle == "travail", "source": "Décision humaine fictive"}
            for cle in ("travail", "deplacement", "pause")
        },
        "motif_correction": "Validation paie fictive.",
    }
    with session() as cnx:
        demande = approbations.creer_demande(
            cnx,
            "m04-field-ops",
            "m4_valider_heures_regulieres",
            args_validation,
            niveau=approbations.Niveau.N4,
        )
        decision = approbations.decider(
            cnx,
            demande,
            True,
            owner,
            outils_m4,
            {"m04-field-ops": lire_manifeste(_ROOT / "departments/m04-field-ops")},
        )
    assert decision["statut"] == "executee", decision

    outils_m5 = {outil.nom: outil for outil in outils_m5(lecteur_heures_m4=lambda *_args: {})}
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(owner, "admin")):
        contrat = executer_atomique(
            outils_m5["m5_enregistrer_contrat_horaire"],
            {
                "employee_person_id": employee,
                "contrat_id": "CONTRAT-PAIE-FICTIF",
                "valide_du": "2026-09-01",
                "valide_jusqu_au": "2026-10-01",
                "fuseau": "America/Montreal",
                "devise": "CAD",
                "taux_horaire": "31.25",
                "source_humaine": "Contrat fictif PAIE-001",
                "date_source": "2026-08-31",
                "revision_attendue": 0,
                "ligne_id_attendue": "",
                "motif": "Enregistrement fictif de test.",
            },
        )
    assert contrat["resultat"]["accepte"] is True, contrat
    return deps, owner, employee


def _lecture_m4(observations, connexions=None):
    def lire(technicien_id, debut, fin, fuseau):
        if connexions is not None:
            from opsys import stockage

            connexions.append(stockage.connexion_courante())
        observations.append(
            {
                "identite": contexte.identite_appelante(),
                "appelant": contexte.DEPARTEMENT_APPELANT.get(),
                "origine": contexte.departement_origine_appelante(),
                "args": {"technicien_id": technicien_id, "debut": debut, "fin": fin, "fuseau": fuseau},
            }
        )
        return {"accepte": True, "resultat": {"minutes_regulieres": 120}}

    return Outil(
        nom="m4_lire_heures_regulieres_validees",
        description="Lecture de test fictive.",
        parametres={
            "type": "object",
            "properties": {k: {"type": "string"} for k in ARGS},
            "required": list(ARGS),
            "additionalProperties": False,
        },
        fonction=lire,
        autonomie=Autonomie.T0,
    )


def _outil_m5(lecteur_heures_m4, connexions=None):
    def preparer(technicien_id, debut, fin, fuseau):
        if connexions is not None:
            from opsys import stockage

            connexions.append(stockage.connexion_courante())
        return lecteur_heures_m4(technicien_id, debut, fin, fuseau)

    return Outil(
        nom="m5_preparer_brut_regulier",
        description="Préparation fictive de paie.",
        parametres={
            "type": "object",
            "properties": {k: {"type": "string"} for k in ARGS},
            "required": list(ARGS),
            "additionalProperties": False,
        },
        fonction=preparer,
        autonomie=Autonomie.T0,
    )


def _cap_m5(monkeypatch, *, inclure_m4=True):
    departements = charger_departements()
    observations = []
    ports = []
    m4 = SimpleNamespace(outils=lambda: (_lecture_m4(observations),))

    def fabriquer_m5(*, lecteur_heures_m4=None):
        ports.append(lecteur_heures_m4)
        return (_outil_m5(lecteur_heures_m4),)

    m5 = SimpleNamespace(outils=fabriquer_m5)
    import m4_field_ops.outils as module_m4
    import m5_financecore.outils as module_m5

    monkeypatch.setattr(module_m4, "outils", m4.outils)
    monkeypatch.setattr(module_m5, "outils", m5.outils)
    if not inclure_m4:
        departements.pop("m04-field-ops")
    monkeypatch.setattr("opsys.capacites.jetons.etat_budget", lambda *_args: {"niveau": "ok"})
    monkeypatch.setattr("opsys.capacites.approbations.mode_effectif", lambda *_args: "ombre")
    monkeypatch.setattr("opsys.capacites.executer_atomique", executer)
    capacites = Capacites(
        departements,
        lambda: nullcontext(object()),
        filtre={"m05-financecore"},
        appelant="m05-financecore",
        memoire=False,
    )
    return capacites, observations, ports


def test_cap_m5_expose_pas_m4_et_conserve_identite_et_origine(monkeypatch):
    capacites, observations, _ports = _cap_m5(monkeypatch)
    noms = {outil.nom for outil in capacites.lister()}
    assert "m5_preparer_brut_regulier" in noms
    assert "m4_lire_heures_regulieres_validees" not in noms

    appelante = contexte.IdentiteAppelante("owner-fictif", "nathan_owner", source="console")
    with (
        contexte.appele_par_appareil(appelante),
        contexte.appeler_en_tant_que("m05-financecore", origine="m05-financecore"),
    ):
        reponse = capacites.appeler("m5_preparer_brut_regulier", ARGS)

    assert reponse == {
        "ok": True,
        "resultat": {
            "ok": True,
            "resultat": {"accepte": True, "resultat": {"minutes_regulieres": 120}},
        },
    }
    assert observations == [
        {
            "identite": appelante,
            "appelant": "m04-field-ops",
            "origine": "m05-financecore",
            "args": ARGS,
        }
    ]


def test_callable_m4_refuse_mauvaise_forme_sans_dispatch(monkeypatch):
    capacites, observations, ports = _cap_m5(monkeypatch)
    # La fonction M5 de test expose le callback à la seule forme à quatre arguments.
    erreur = ports[0]("employe-fictif", "2026-09-14", "2026-09-14", "America/Montreal", extra="forgé")
    assert erreur["ok"] is False
    assert erreur["erreur"] == "arguments_lecteur_heures_invalides"
    assert observations == []


@pytest.mark.parametrize(
    ("appelante", "origine"),
    [
        (None, "m05-financecore"),
        (contexte.IdentiteAppelante("admin-fictif", "admin", source="console"), "m05-financecore"),
        (contexte.IdentiteAppelante("owner-fictif", "nathan_owner", source="appareil"), "m05-financecore"),
        (contexte.IdentiteAppelante("owner-fictif", "nathan_owner", source="console"), "m04-field-ops"),
    ],
)
def test_callable_m4_refuse_identite_ou_origine_non_owner_avant_dispatch(monkeypatch, appelante, origine):
    _capacites, observations, ports = _cap_m5(monkeypatch)
    with contexte.appele_par_appareil(appelante), contexte.appeler_en_tant_que("m05-financecore", origine=origine):
        reponse = ports[0](ARGS["technicien_id"], ARGS["debut"], ARGS["fin"], ARGS["fuseau"])
    assert reponse["ok"] is False
    assert reponse["erreur"] == "identite_console_proprietaire_requise"
    assert observations == []


def test_absence_de_m4_est_un_refus_nomme_a_l_usage(monkeypatch):
    capacites, _observations, _ports = _cap_m5(monkeypatch, inclure_m4=False)
    assert "m5_preparer_brut_regulier" in {outil.nom for outil in capacites.lister()}
    outil = capacites.index["m5_preparer_brut_regulier"][1]
    reponse = outil.fonction(**ARGS)
    assert reponse["erreur"] == "lecteur_heures_m4_indisponible"


def test_ports_prives_rejetes_hors_m5(monkeypatch):
    departements = charger_departements()
    with pytest.raises(ValueError, match="port privé non autorisé"):
        departements["m04-field-ops"].charger_outils(ports_prives={"lecteur_heures_m4": lambda: None})


def test_console_owner_reutilise_la_meme_transaction_jusqu_au_lecteur_m4(monkeypatch, session):
    from opsys import identite, stockage
    from opsys.console import metier
    from opsys.console.securite import Session

    connexions = []
    observations = []
    module_m4 = __import__("m4_field_ops.outils", fromlist=["outils"])
    module_m5 = __import__("m5_financecore.outils", fromlist=["outils"])
    monkeypatch.setattr(module_m4, "outils", lambda: (_lecture_m4(observations, connexions),))
    monkeypatch.setattr(
        module_m5,
        "outils",
        lambda *, lecteur_heures_m4=None: (_outil_m5(lecteur_heures_m4, connexions),),
    )
    with session() as cnx:
        identite.creer_personne(
            cnx, "owner-pont-fictif", "Owner fictif", "mot-de-passe-fictif-pont-123", ["nathan_owner"]
        )
        session_console = Session("owner-pont-fictif", frozenset({"nathan_owner"}), "csrf-fictif", 2_000_000_000)
        connexions.append(cnx)
        reponse = metier.executer(
            cnx,
            charger_departements(),
            session_console,
            "m5_preparer_brut_regulier",
            ARGS,
        )
        assert stockage.connexion_courante() is cnx

    assert reponse["ok"] is True
    assert len(connexions) == 3
    assert connexions[0] is connexions[1] is connexions[2]
    assert observations[0]["identite"].personne == "owner-pont-fictif"
    assert observations[0]["appelant"] == "m04-field-ops"
    assert observations[0]["origine"] == "m05-financecore"


def test_console_owner_lit_m4_et_m5_sur_le_jeu_de_donnees_reel(monkeypatch, session):
    from opsys import contexte as contexte_module
    from opsys import stockage
    from opsys.console import metier
    from opsys.console.securite import Session

    deps, owner, employee = _amorcer_donnees_reelles(session)
    observations_m4 = []
    maillons_origine = stockage.maillons

    def observer_maillons(departement, nom_registre="principal"):
        if departement == "m04-field-ops" and contexte_module.DEPARTEMENT_APPELANT.get() == "m04-field-ops":
            observations_m4.append(
                {
                    "cnx": stockage.connexion_courante(),
                    "identite": contexte_module.identite_appelante(),
                    "origine": contexte_module.departement_origine_appelante(),
                }
            )
        return maillons_origine(departement, nom_registre)

    monkeypatch.setattr(stockage, "maillons", observer_maillons)
    with session() as cnx:
        assert stockage.connexion_courante() is cnx
        reponse = metier.executer(
            cnx,
            deps,
            Session(owner, frozenset({"nathan_owner"}), "csrf-fictif", 2_000_000_000),
            "m5_preparer_brut_regulier",
            {
                "employee_person_id": employee,
                **PERIODE_M4,
                "politique_arrondi": "centime_demi_superieur",
                "hypothese_arrondi": "Hypothèse fictive PAIE-1, non validée.",
                "sources_attendues": None,
            },
        )
        assert stockage.connexion_courante() is cnx

    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["accepte"] is True, resultat
    assert resultat["resultat"]["minutes_regulieres"] == 120
    assert resultat["resultat"]["brut_brouillon"] == "62.50"
    assert observations_m4
    assert all(observation["cnx"] is cnx for observation in observations_m4)
    assert all(observation["origine"] == "m05-financecore" for observation in observations_m4)
    assert all(observation["identite"].personne == owner for observation in observations_m4)
    assert all(observation["identite"].role == "nathan_owner" for observation in observations_m4)
    assert all(observation["identite"].source == "console" for observation in observations_m4)


def test_mcp_http_reel_catalogue_m5_et_refuse_sans_identite_avant_lecture_m4(monkeypatch, session):
    import socket
    import threading
    import time

    import anyio
    import uvicorn
    from mcp.client.session import ClientSession as SessionMcp
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    from opsys import contexte as contexte_module
    from opsys import stockage
    from opsys.serveur_mcp import application_http_departements

    deps, employee_owner, employee = _amorcer_donnees_reelles(session)
    assert employee_owner
    lectures_m4 = []
    maillons_origine = stockage.maillons

    def observer_maillons(departement, nom_registre="principal"):
        if departement == "m04-field-ops" and contexte_module.DEPARTEMENT_APPELANT.get() == "m04-field-ops":
            lectures_m4.append(departement)
        return maillons_origine(departement, nom_registre)

    monkeypatch.setattr(stockage, "maillons", observer_maillons)
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    jeton = "jeton-MCP-fictif-paie-0123456789"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    application = application_http_departements(deps, session, jeton, hote="127.0.0.1")
    serveur = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, log_level="error"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    try:
        for _ in range(100):
            if serveur.started:
                break
            time.sleep(0.05)
        assert serveur.started
        url = f"http://127.0.0.1:{port}/mcp/m05-financecore"

        async def scenario():
            http = create_mcp_http_client(headers={"Authorization": f"Bearer {jeton}"})
            async with (
                http,
                streamable_http_client(url, http_client=http) as flux,
                SessionMcp(flux[0], flux[1]) as mcp,
            ):
                await mcp.initialize()
                noms = {outil.name for outil in (await mcp.list_tools()).tools}
                assert "m5_preparer_brut_regulier" in noms
                assert "m4_lire_heures_regulieres_validees" not in noms
                appel = await mcp.call_tool(
                    "m5_preparer_brut_regulier",
                    {
                        "employee_person_id": employee,
                        **PERIODE_M4,
                        "politique_arrondi": "centime_demi_superieur",
                        "hypothese_arrondi": "Hypothèse fictive PAIE-HTTP-1, non validée.",
                        "sources_attendues": None,
                    },
                )
                import json

                return json.loads(appel.content[0].text)

        reponse = anyio.run(scenario)
    finally:
        serveur.should_exit = True
        fil.join(timeout=5)

    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-SALAIRE-ACCES-REFUSE"
    assert lectures_m4 == []
