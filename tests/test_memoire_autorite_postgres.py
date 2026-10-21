"""Filtre SQL réel : données fictives, aucune qualification d'embeddings ou de modèle."""
from __future__ import annotations

import datetime as dt

import pytest
from memoire.autorite import emettre_ticket as _ticket
from memoire.autorite import lier_affaire as _lier
from memoire.doubles import postgres_ephemere, raison_sans_docker

from opsys.memoire import MemoireEntreprise, autorite, outils


@pytest.fixture(scope="module")
def memoire_client():
    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)
    with postgres_ephemere(stockage_en_memoire=True) as url:
        memoire = MemoireEntreprise(url)
        memoire.migrer()
        lignes = [
            ("A", "clients", "personnelle", ["client:A"]),
            ("B", "clients", "personnelle", ["client:B"]),
            ("AB", "clients", "personnelle", ["client:A", "client:B"]),
            ("sans-sujet", "clients", "confidentielle", []),
            ("procedure-globale", "procedures", "interne", []),
            ("procedure-client-B", "procedures", "interne", ["client:B"]),
            ("procedure-chantier", "procedures", "interne", ["chantier:CH-B"]),
            ("procedure-confidentielle", "procedures", "confidentielle", []),
        ]
        for label, portee, sensibilite, sujets in lignes:
            memoire.ajouter("Préférence fictive " + label,
                {"departement": "m02-revenue-crm", "portee": portee, "sensibilite": sensibilite,
                 "sujets": sujets, "source": "fictif:" + label,
                 "expire_le": dt.datetime.now(dt.UTC) + dt.timedelta(days=1)})
        yield memoire


def test_pg_client_exclut_autres_multi_sujets_et_non_etiquetes(memoire_client):
    recherche = memoire_client.rechercher("préférence", None, 20,
        {"portee": ["clients", "procedures"], "sujets_autorises": ["client:A"], "portees_globales": ["procedures"]})
    assert {r.source for r in recherche.resultats} == {"fictif:A", "fictif:procedure-globale"}
    sortie = outils._sortie(recherche, "plein texte fictif")
    assert {r["source"] for r in sortie["resultats"]} == {"fictif:A", "fictif:procedure-globale"}
    assert "client:B" not in str(sortie)


def test_pg_procedures_seules_ne_servent_aucun_fragment_client_ou_personnel(memoire_client):
    recherche = memoire_client.rechercher("préférence", None, 20,
        {"portee": ["procedures"], "sujets_autorises": [], "portees_globales": ["procedures"]})
    assert {r.source for r in recherche.resultats} == {"fictif:procedure-globale"}


def test_pg_departement_global_conserve_lectures_multi_client_autorisees(memoire_client):
    recherche = memoire_client.rechercher("préférence", None, 20, {"portee": ["clients"]})
    assert {r.source for r in recherche.resultats} == {"fictif:A", "fictif:B", "fictif:AB", "fictif:sans-sujet"}


def test_pg_citation_procedure_admise_reste_liee_a_version_source(memoire_client):
    service = memoire_client.procedures()
    admission = service.admettre(b"# Procedure fictive\n\nPreference de pose fictive.\n", "Fictif R33",
        auteur="admin:fictif", cle_admission="r33-procedure-fictive-0001")
    service.indexer(admission.document_id, admission.sha256)
    service.activer(admission.document_id, admission.sha256, attendu_sha256=None, auteur="admin:fictif")
    recherche = memoire_client.rechercher("préférence", None, 20,
        {"portee": ["procedures"], "sujets_autorises": [], "portees_globales": ["procedures"]})
    source = f"opsys-document://{admission.document_id}/{admission.sha256}"
    citation = next(r for r in outils._sortie(recherche, "plein texte fictif")["resultats"] if r["source"] == source)
    assert citation["contenu_non_fiable"] is True
    assert citation["citations_verifiees"][0]["version_sha256"] == admission.sha256
    assert citation["citations_verifiees"][0]["document_id"] == admission.document_id


@pytest.mark.parametrize("retirer", [False, True])
def test_pg_lecture_reelle_revalide_apres_sql(memoire_client, tmp_path, monkeypatch, retirer):
    from m10_memoire import liaison
    from m10_memoire import registre as m10

    from opsys import stockage
    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste, racine_departements
    stockage.liberer()
    monkeypatch.setenv("OPSYS_BASE_URL", "sqlite:///" + str(tmp_path / "canon-r33-pg-fictif.db"))
    stockage.migrer()
    dep = lire_manifeste(racine_departements() / "m01-front-office")
    policy = {"version": 1, "departements": {dep.id: "client_session"},
        "agents": {dep.id: {"departement": dep.id, "mode": "client_session"}}, "procedures_globales": ["procedures"]}
    session, client, lien = _lier("LEAD-FICTIF-PG-" + str(retirer))
    source = "fictif:client-canonique-" + str(retirer)
    memoire_client.ajouter("Préférence confidentielle fictive du client lié",
        {"departement": dep.id, "portee": "signaux", "sensibilite": "personnelle",
         "sujets": ["client:" + client], "source": source,
         "expire_le": dt.datetime.now(dt.UTC) + dt.timedelta(days=1)})
    appels = []
    class LecturePuisRetrait:
        def rechercher(self, *args, **kwargs):
            assert "embedding_profile_sha256" in kwargs
            assert kwargs["embedding_profile_sha256"] is None
            result = memoire_client.rechercher(*args, **kwargs)
            appels.append(result)
            if retirer:
                with stockage.transaction():
                    journal = m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
                    assert liaison.revoquer_session_affaire(
                        session, lien["ligne_id"], "owner_fictif", "admin", "appareil",
                        "retrait pendant SQL fictif", "2026-10-02T10:01:00+00:00", journal)[1] is None
            return result
    monkeypatch.setattr(outils, "_memoire", LecturePuisRetrait)
    monkeypatch.setattr(outils, "_embeddings", lambda: (None, "aucun provider fictif"))
    cap = Capacites({dep.id: dep}, stockage.transaction, appelant=dep.id,
        memoire_politique=lambda: policy, memoire_versionnee=True)
    args = {"requete": "préférence"}
    ticket = _ticket(policy, session, args)
    try:
        rep = cap.appeler(autorite.NOM_OUTIL, args, ticket_memoire=ticket)
        assert len(appels) == 1 and {r.source for r in appels[0].resultats} == {source}
        if retirer:
            assert rep["ok"] is False and "resultat" not in rep
            assert "Préférence confidentielle" not in str(rep)
        else:
            assert rep["ok"] is True
            assert {r["source"] for r in rep["resultat"]["resultats"]} == {source}
    finally:
        stockage.liberer()
