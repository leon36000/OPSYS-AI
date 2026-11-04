"""Concurrence fictive entre sources pendant un rapprochement public M5."""
from __future__ import annotations

import threading

import pytest
import yaml

from opsys import stockage


def test_rapprochement_pg_ne_melie_pas_les_registres_sur_un_commit_concurrent(
    monkeypatch, tmp_path, m5_test_helpers, m5_postgres_doubles
):
    raison = m5_postgres_doubles.raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)
    helper = m5_test_helpers
    m5 = helper.m5_outils
    with m5_postgres_doubles.postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        m5.utiliser_stockage_durable()
        with stockage.transaction(url) as cnx:
            helper.identite.creer_personne(
                cnx, "nathan.fictif", "Nathan fictif", "password-fictif-1234", ["nathan_owner", "admin"]
            )
            helper.identite.creer_personne(
                cnx, "comptable", "Comptable fictif", "password-fictif-1234", ["finance", "admin"]
            )
        manifeste = tmp_path / "department.yaml"
        manifeste.write_text(
            yaml.safe_dump({"configuration": {"categories_depense_sans_po": ["carburant"]}}), encoding="utf-8"
        )
        monkeypatch.setattr(m5, "_MANIFESTE", manifeste)
        tools = {o.nom: o for o in m5.outils()}
        dep = helper.lire_manifeste(helper._RACINE_M5)
        entered, release = threading.Event(), threading.Event()
        errors = []
        public_report = {}
        reads_before_pause = []
        reader_ident = []
        original = m5._factures_emises

        def pause_after_invoice_read(*args, **kwargs):
            # Sur HEAD initial : la liste clients est déjà lue; après ce retour, le code lit AP puis opérations.
            # Sur le prototype : il reçoit la liste client du snapshot commun, pris avant la pause.
            values = original(*args, **kwargs)
            if threading.get_ident() == reader_ident[0]:
                reads_before_pause.append(len(args) + len(kwargs))
                entered.set()
                if not release.wait(40):
                    raise TimeoutError("écriture concurrente non terminée")
            return values

        monkeypatch.setattr(m5, "_factures_emises", pause_after_invoice_read)

        def reader():
            try:
                reader_ident.append(threading.get_ident())
                public_report.update(helper._appeler(tools, "m5_rapprocher_grand_livre", helper.OCTOBRE))
            except Exception as exc:  # noqa: BLE001 — remonter l'erreur du thread au thread pytest
                errors.append(exc)

        def writer():
            try:
                if not entered.wait(40):
                    raise TimeoutError("lecture publique non atteinte")
                ap_response = helper._appeler(tools, "m5_saisir_facture_sans_po", {
                    "fournisseur_id": "fournisseur-fictif", "categorie": "carburant", "numero_facture": "PG-FICTIF",
                    "date_facture": "2026-10-01", "montant_avant_taxes": "100.00", "total_facture": None,
                    "horodatage": helper.SAISIE,
                }, helper.COMPTABLE)
                assert ap_response["ok"] and ap_response["resultat"]["accepte"], ap_response
                generation = helper._appeler(tools, "m5_generer_brouillons_comptables", {"horodatage": helper.H})
                drafts = generation["resultat"]["resultat"]["brouillons_crees"]
                assert len(drafts) == 1, {"generation": generation, "ap": ap_response}
                helper._valider_par_la_file(dep, drafts[0]["ecriture_id"])
            except Exception as exc:  # noqa: BLE001 — remonter l'erreur du thread au thread pytest
                errors.append(exc)
            finally:
                release.set()

        t_reader = threading.Thread(target=reader)
        t_writer = threading.Thread(target=writer)
        t_reader.start()
        t_writer.start()
        t_reader.join(60)
        t_writer.join(60)
        assert not t_reader.is_alive() and not t_writer.is_alive(), "threads stalled"
        assert not errors, errors
        body = public_report["resultat"]["resultat"]
        before_replay = body["verdict"]
        replay = helper._appeler(tools, "m5_rapprocher_grand_livre", helper.OCTOBRE)
        after_replay = replay["resultat"]["resultat"]["verdict"]
        assert [before_replay, after_replay] == ["CONCORDANT", "CONCORDANT"], {
            "actual": [before_replay, after_replay],
            "read_helper_received_snapshot": reads_before_pause,
        }
        stockage.liberer(url)
