"""Provenance atomique des demandes N4 créées par un appareil humain (APR002)."""

from __future__ import annotations

import datetime as dt
import json
from contextlib import contextmanager

import pytest
from sqlalchemy import select

from opsys import approbations, contexte, etat, idempotence, identite
from opsys.capacites import Capacites
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.schema import APPROBATIONS, MUTATIONS_APPLIQUEES

NOM_OUTIL = "m2_enregistrer_interaction"
AUTEUR = "admin-apr002-fictif"
ROLE = "admin"
APPAREIL = "appareil-apr002-fictif"
CLE = "request-apr002-fictif-001"
ARGUMENTS = {"lead_id": "LEAD-FICTIF-APR002", "note": "texte sensible fictif"}


def _meta(cle: str = CLE) -> idempotence.Meta:
    # L'heure appareil ancienne sert à prouver que le journal utilise son horloge serveur.
    return idempotence.Meta(cle, APPAREIL, "2000-01-01T00:00:00-05:00")


@pytest.fixture
def capacites_n4(session, departements_demo, monkeypatch):
    cap = Capacites(departements_demo, session, memoire=False)
    departement = next(iter(departements_demo.values()))
    cap.index[NOM_OUTIL] = (
        departement,
        Outil(
            NOM_OUTIL,
            "Enregistre une interaction, outil fictif pour APR002.",
            {
                "type": "object",
                "properties": {"lead_id": {"type": "string"}, "note": {"type": "string"}},
                "required": ["lead_id", "note"],
                "additionalProperties": False,
            },
            lambda **_kwargs: {"accepte": True},
            Autonomie.T1,
            niveau=Niveau.N4,
        ),
    )
    monkeypatch.setattr(cap, "_outils_du_role", lambda role: frozenset({NOM_OUTIL}) if role == ROLE else frozenset())
    with session() as cnx:
        identite.creer_personne(cnx, AUTEUR, "Admin APR002 fictif", "mot-de-passe-apr002-fictif", [ROLE])
    return cap


def _appeler(cap, arguments=ARGUMENTS, meta=None, auteur=AUTEUR, role=ROLE):
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(auteur, role)):
        return cap.appeler(NOM_OUTIL, arguments, _meta() if meta is None else meta)


def _audit(session) -> list[dict]:
    with session() as cnx:
        return [e for e in etat.lire_journal(cnx) if e["action"] == "approbation.demander_humain"]


def test_demande_n4_journalise_identite_meta_hash_et_heure_serveur_sans_arguments_bruts(
    capacites_n4, session
):
    avant = dt.datetime.now(dt.UTC)
    premiere = _appeler(capacites_n4)
    apres = dt.datetime.now(dt.UTC)
    assert premiere["ok"] is True and premiere["statut"] == "en_attente_approbation"
    assert premiere["rejoue"] is False

    [trace] = _audit(session)
    details = trace["details"]
    assert trace["par"] == AUTEUR
    assert trace["cible"] == premiere["demande_id"]
    assert trace["action"] == "approbation.demander_humain"
    assert details["role"] == ROLE
    assert details["appareil"] == APPAREIL
    assert details["request_id"] == CLE
    assert details["departement"]
    assert details["outil"] == NOM_OUTIL
    assert details["niveau"] == "N4"
    assert details["arguments_sha256"] == idempotence.empreinte_arguments(ARGUMENTS)
    assert "texte sensible fictif" not in json.dumps(trace, ensure_ascii=False)
    horodatage_serveur = dt.datetime.fromisoformat(trace["quand"])
    assert avant - dt.timedelta(seconds=1) <= horodatage_serveur <= apres + dt.timedelta(seconds=1)
    assert horodatage_serveur.year != 2000


def test_rejeu_n4_ne_duplique_ni_demande_ni_trace_et_conflit_n_en_ajoute_pas(
    capacites_n4, session
):
    premiere = _appeler(capacites_n4)
    rejeu = _appeler(capacites_n4)
    conflit = _appeler(capacites_n4, {**ARGUMENTS, "note": "autres arguments"})

    assert rejeu["rejoue"] is True and rejeu["demande_id"] == premiere["demande_id"]
    assert conflit["ok"] is False and conflit["erreur"] == "mutation_conflit"
    assert len(_audit(session)) == 1
    with session() as cnx:
        assert len(cnx.execute(select(APPROBATIONS)).mappings().all()) == 1
        assert len(cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all()) == 1


def test_role_revoque_en_base_refuse_la_demande_sans_provenance_ni_ecriture(
    capacites_n4, session
):
    with session() as cnx:
        identite.retirer_role(cnx, AUTEUR, ROLE)

    reponse = _appeler(capacites_n4)

    assert reponse["ok"] is False and reponse["erreur"] == "ticket_cible_requis"
    assert _audit(session) == []
    with session() as cnx:
        assert cnx.execute(select(APPROBATIONS)).mappings().all() == []
        assert cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all() == []


def test_role_retire_apres_precontrole_est_refuse_dans_la_transaction_n4(
    capacites_n4, session
):
    fabrique = capacites_n4._cnx_factory
    ouvertures = 0

    @contextmanager
    def fabrique_avec_retrait():
        nonlocal ouvertures
        with fabrique() as cnx:
            yield cnx
        ouvertures += 1
        if ouvertures == 1:
            with fabrique() as cnx:
                identite.retirer_role(cnx, AUTEUR, ROLE)

    capacites_n4._cnx_factory = fabrique_avec_retrait
    reponse = _appeler(capacites_n4)

    assert ouvertures >= 2
    assert reponse["ok"] is False and reponse["erreur"] == "ticket_cible_requis"
    assert _audit(session) == []
    with session() as cnx:
        assert cnx.execute(select(APPROBATIONS)).mappings().all() == []
        assert cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all() == []


def test_panne_apres_insertion_demande_et_journal_annule_les_trois_ecritures(
    capacites_n4, session, monkeypatch
):
    journaliser = approbations.journaliser

    def journaliser_puis_tomber(*args, **kwargs):
        journaliser(*args, **kwargs)
        raise RuntimeError("panne APR002 après journal, avant commit")

    monkeypatch.setattr(approbations, "journaliser", journaliser_puis_tomber)
    with pytest.raises(RuntimeError, match="panne APR002"):
        _appeler(capacites_n4)

    with session() as cnx:
        assert cnx.execute(select(APPROBATIONS)).mappings().all() == []
        assert cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all() == []
        assert [e for e in etat.lire_journal(cnx) if e["action"] == "approbation.demander_humain"] == []

    monkeypatch.setattr(approbations, "journaliser", journaliser)
    reprise = _appeler(capacites_n4)
    assert reprise["ok"] is True and reprise["rejoue"] is False
    assert len(_audit(session)) == 1


def test_demande_generique_sans_appareil_ne_recoit_pas_un_auteur_humain_invente(
    session, departements_demo
):
    cap = Capacites(departements_demo, session, memoire=False)
    reponse = cap.appeler("m9_payer", {"montant": 100}, _meta("request-agent-apr002"))

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    with session() as cnx:
        assert [e for e in etat.lire_journal(cnx) if e["action"] == "approbation.demander_humain"] == []
        assert len(cnx.execute(select(APPROBATIONS)).mappings().all()) == 1

# Parcours M5 réel : ces deux mutations N4 passent par _distribuer, contrairement à la voie C02 ci-dessus.
M5 = "m05-financecore"
NOMS_M5 = ("m5_corriger_facture_fournisseur", "m5_annuler_facture_fournisseur")


@pytest.fixture
def capacites_m5(session, monkeypatch):
    from pathlib import Path

    import m5_financecore.outils as m5_outils

    from opsys.departements import lire_manifeste

    departement = lire_manifeste(Path(__file__).resolve().parents[1] / "departments" / M5)
    cap = Capacites({M5: departement}, session, memoire=False)
    with session() as cnx:
        identite.creer_personne(cnx, "finance-apr002-fictif", "Finance fictive", "mot-de-passe-apr002-fictif",
                                ["finance", "admin"])
    m5_outils.utiliser_stockage_durable()
    return cap


def _arguments_m5(nom):
    if nom == NOMS_M5[0]:
        return {
            "facture_fournisseur_id": "FACTURE-FICTIVE-APR002",
            "motif": "montant corrigé fictif et confidentiel",
            "numero_facture": None,
            "date_facture": None,
            "montant_avant_taxes": "123.45",
            "total_facture": None,
            "horodatage": "2026-09-30T10:00:00-04:00",
        }
    return {
        "facture_fournisseur_id": "FACTURE-FICTIVE-APR002",
        "motif": "annulation fictive et confidentielle",
        "horodatage": "2026-09-30T10:00:00-04:00",
    }


@pytest.mark.parametrize("nom", NOMS_M5)
def test_m5_demande_n4_appareil_humain_journalise_source_sans_arguments_bruts(capacites_m5, session, nom):
    arguments = _arguments_m5(nom)
    meta = _meta(f"request-m5-{nom}")
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("finance-apr002-fictif", "admin")):
        reponse = capacites_m5.appeler(nom, arguments, meta)

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation", reponse
    [trace] = _audit(session)
    assert trace["par"] == "finance-apr002-fictif"
    assert trace["cible"] == reponse["demande_id"]
    assert trace["details"]["role"] == "admin"
    assert trace["details"]["appareil"] == APPAREIL
    assert trace["details"]["request_id"] == meta.cle
    assert trace["details"]["outil"] == nom
    assert trace["details"]["niveau"] == "N4"
    assert trace["details"]["arguments_sha256"] == idempotence.empreinte_arguments(arguments)
    assert "confidentiel" not in json.dumps(trace, ensure_ascii=False)


@pytest.mark.parametrize("nom", NOMS_M5)
def test_m5_rejeu_restitue_la_demande_sans_doubler_sa_provenance(capacites_m5, session, nom):
    arguments = _arguments_m5(nom)
    meta = _meta(f"request-m5-replay-{nom}")
    appelante = contexte.IdentiteAppelante("finance-apr002-fictif", "admin")
    with contexte.appele_par_appareil(appelante):
        premiere = capacites_m5.appeler(nom, arguments, meta)
        rejeu = capacites_m5.appeler(nom, arguments, meta)
        conflit = capacites_m5.appeler(nom, {**arguments, "motif": "motif différent fictif"}, meta)

    assert premiere["statut"] == "en_attente_approbation"
    assert rejeu["rejoue"] is True and rejeu["demande_id"] == premiere["demande_id"]
    assert conflit["ok"] is False and conflit["erreur"] == "mutation_conflit"
    assert len(_audit(session)) == 1


def test_m5_role_appareil_retire_avant_appel_n_est_pas_attribue(capacites_m5, session):
    with session() as cnx:
        identite.retirer_role(cnx, "finance-apr002-fictif", "admin")
    arguments = _arguments_m5(NOMS_M5[0])
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("finance-apr002-fictif", "admin")):
        reponse = capacites_m5.appeler(NOMS_M5[0], arguments, _meta("request-m5-revoked"))

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    assert _audit(session) == []


def test_m5_demande_agent_avec_meta_ne_recoit_pas_un_auteur_humain_invente(capacites_m5, session):
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("agent-apr002-fictif", "system_agent")):
        reponse = capacites_m5.appeler(
            NOMS_M5[1], _arguments_m5(NOMS_M5[1]), _meta("request-m5-agent")
        )

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    assert _audit(session) == []


def test_demande_n5_ne_recoit_pas_la_provenance_n4(capacites_n4, session):
    departement = next(iter(capacites_n4.departements.values()))
    nom = "m9_test_n5_apr002"
    capacites_n4.index[nom] = (
        departement,
        Outil(nom, "Outil N5 APR002 fictif", {"type": "object", "properties": {},
                                               "additionalProperties": False},
              lambda **_kwargs: {"ok": True}, Autonomie.T2, niveau=Niveau.N5),
    )
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(AUTEUR, ROLE)):
        reponse = capacites_n4.appeler(nom, {}, _meta("request-n5-apr002"))
    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    assert _audit(session) == []


def test_m5_panne_apres_journal_annule_demande_trace_et_reclamation(capacites_m5, session, monkeypatch):
    journaliser = approbations.journaliser

    def journaliser_puis_tomber(*args, **kwargs):
        journaliser(*args, **kwargs)
        raise RuntimeError("panne APR002 phase 2 après provenance")

    monkeypatch.setattr(approbations, "journaliser", journaliser_puis_tomber)
    arguments = _arguments_m5(NOMS_M5[1])
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante("finance-apr002-fictif", "admin")),
        pytest.raises(RuntimeError, match="phase 2"),
    ):
        capacites_m5.appeler(NOMS_M5[1], arguments, _meta("request-m5-rollback"))

    with session() as cnx:
        assert cnx.execute(select(APPROBATIONS)).mappings().all() == []
        assert cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all() == []
    assert _audit(session) == []
