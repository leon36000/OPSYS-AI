"""Restore only a fresh fictional target and qualify it in this new Python process."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from opsys import evenements, exportation, stockage
from opsys.stockage.schema import JOURNAL, META


def snapshot():
    with stockage.transaction() as cnx:
        rows = {
            table.name: [dict(row._mapping) for row in cnx.execute(select(table).order_by(*table.primary_key.columns))]
            for table in META.sorted_tables
        }
    hashes = {
        name: hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
        for name, value in rows.items()
    }
    return {"hashes": hashes, "journal": rows[JOURNAL.name]}


def main():
    manifest = json.loads(Path(sys.argv[1]).read_text())
    assert manifest["fictif"] is True and os.getpid() != manifest["parent_pid"]
    evidence = Path(manifest["evidence"]).resolve()
    home = evidence / "instance-restauree-fictive"
    assert not home.exists() and os.environ["OPSYS_BASE_URL"] == f"sqlite:///{home / 'opsys.db'}"
    assert os.environ["OPSYS_HOME"] == str(home)
    corrupt_target = evidence / "instance-refusee-fictive"
    os.environ["OPSYS_BASE_URL"] = f"sqlite:///{corrupt_target / 'opsys.db'}"
    try:
        exportation.restaurer(
            Path(manifest["corrupt_archive"]),
            corrupt_target,
            par="qualification-fictive",
            empreinte=manifest["archive_sha256"],
        )
    except exportation.ErreurExportation as error:
        assert "archive altérée" in str(error)
    else:
        raise AssertionError("corrupt archive accepted")
    assert not corrupt_target.exists()
    os.environ["OPSYS_BASE_URL"] = f"sqlite:///{home / 'opsys.db'}"
    home.mkdir(mode=0o700)
    result = exportation.restaurer(
        Path(manifest["archive"]), home, par="qualification-fictive", empreinte=manifest["archive_sha256"]
    )
    assert not result.mis_de_cote and result.revision == manifest["revision"]
    restored = snapshot()
    expected = manifest["checkpoint"]
    assert {name: digest for name, digest in restored["hashes"].items() if name != JOURNAL.name} == {
        name: digest for name, digest in expected["hashes"].items() if name != JOURNAL.name
    }
    assert restored["journal"][:-1] == expected["journal"]
    extra = restored["journal"][-1]
    assert extra["action"] == "instance.restauration" and extra["par"] == "qualification-fictive"
    assert json.loads(extra["details"])["sha256"] == manifest["archive_sha256"]
    # Scenario-only manifests are supplied explicitly; the export does not carry them.
    from m5_financecore import outils as m5
    from m8_analytics import outils as m8

    m5._MANIFESTE = Path(manifest["finance_manifest"])
    m8._MANIFESTE = Path(manifest["analytics_manifest"])
    m5.utiliser_stockage_durable()
    from m2_revenue_crm import outils as m2

    m2.utiliser_stockage_durable()
    from harnais_e2e import Moteur

    moteur = Moteur(
        evidence / "backend-fictif", os.environ["OPSYS_BASE_URL"], jeton_contexte=manifest["private_bearer"]
    )
    moteur.dossier.mkdir(mode=0o700)
    repo = Path(manifest["repo"])
    phases = [
        {"fictif": True, "phase": "archive-alteree-refusee-cible-absente"},
        {
            "fictif": True,
            "phase": "restauration-48tables-journal-explicite",
            "hashes_before": expected["hashes"],
            "hashes_after": restored["hashes"],
            "appendice_journal": extra,
        },
    ]

    def call(phase, kind, *, catalog=False):
        before = snapshot()
        input_path = evidence / f"restauration-{phase}-manifest-fictif.json"
        common = {
            "fictif": True,
            "phase": phase,
            "workspaceDir": str(moteur.dossier),
            "bearer": manifest["public_bearer"],
        }
        if kind == "profil":
            common.update(
                {
                    "profileId": manifest["m8_profile"],
                    "profileRevision": 2,
                    "baseUrl": f"http://127.0.0.1:{moteur.port}",
                    "privateBearer": manifest["private_bearer"],
                    "wctId": manifest["wct_id"],
                }
            )
        else:
            common.update(
                {
                    "profileId": manifest["m10_profile"],
                    "serverName": "opsys_context_m5",
                    "url": f"http://127.0.0.1:{moteur.port}/mcp/contexte/m05-financecore",
                    "bearer": manifest["private_bearer"],
                    "tool": "m10_paquet_contexte_affaire",
                    "args": {"affaire_id": manifest["affaire_id"], "horodatage": manifest["maintenant"]},
                    "catalog": catalog,
                }
            )
        with input_path.open("x") as stream:
            json.dump(common, stream)
        input_path.chmod(0o600)
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(moteur.dossier),
            "LANG": "C.UTF-8",
            "TZ": "UTC",
            "OPENCLAW_STATE_DIR": str(moteur.dossier / "core-etat-fictif"),
            "OPENCLAW_CONFIG_PATH": str(moteur.dossier / "config-absente-fictive.json"),
            "OPSYS_QUALIFICATION_REPO": str(repo),
        }
        out = evidence / f"restauration-{phase}-stdout.log"
        err = evidence / f"restauration-{phase}-stderr.log"
        driver = repo / f"core/test/fixtures/opsys-verticale/core_verticale_{kind}_driver.mjs"
        try:
            with out.open("x") as stdout, err.open("x") as stderr:
                response = subprocess.run(
                    ["node", "--import", "./scripts/tsx.mjs", str(driver), str(input_path)],
                    cwd=repo / "core",
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=90,
                )
        finally:
            input_path.unlink(missing_ok=True)
        assert response.returncode == 0, err.read_text()[-4000:]
        rows = [
            row.removeprefix("OPSYS_PROOF_JSON:")
            for row in out.read_text().splitlines()
            if row.startswith("OPSYS_PROOF_JSON:")
        ]
        assert len(rows) == 1
        proof = json.loads(rows[0])
        assert proof.get("envelope", {}).get("ok") is True and not proof.get("isError"), proof
        assert snapshot() == before
        proof["all_meta_unchanged"] = True
        proof["hashes_before_after"] = before["hashes"]
        phases.append(proof)
        return proof["envelope"]["resultat"]

    try:
        moteur.demarrer()
        assert snapshot() == restored
        m8_result = call("lecture-m8-nouveau-backend", "profil")
        assert m8_result["trouve"] is True and m8_result["wct_id"] == manifest["wct_id"]
        assert {row["metric_id"]: row for row in m8_result["mesures"]} == manifest["mesures"]
        assert {row["metric_id"]: row for row in m8_result["mesures"]}["m8_marge_reelle_cad"]["valeur"] == "114.00"
        packet = call("paquet-m10-nouveau-backend", "memoire")
        assert packet["affaire_id"] == manifest["affaire_id"] and packet["affaire"]["connue"] is True
        assert packet["confidentialite"]["agent"] == "m05-financecore" and packet["confidentialite"]["nb_retenus"] >= 3
        text = json.dumps(packet)
        assert "marge_reelle_cad" not in text and "cliente-verticale@exemple.test" not in text
        assert all(identifier not in text for identifier in manifest["financial_event_ids"])
        # The coupled qualification exported the technical corpus too. Use the
        # real console login and live owner role in this restored Python process.
        from fastapi.testclient import TestClient
        from harnais_e2e import MOT_DE_PASSE

        from opsys.console import securite
        from opsys.console.application import creer_application

        before_dev = snapshot()
        configuration = securite.Configuration(
            "session-restauration-console-fictive-" + "x" * 32, cookie_securise=False
        )
        app = creer_application(configuration, moteur.departements, stockage.transaction)
        with TestClient(app, base_url=f"http://testserver{configuration.prefixe}") as client:
            login = client.post(
                "/connexion", data={"identifiant": "nathan", "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False
            )
            assert login.status_code == 303, login.text
            response = client.post(
                "/api/memoire-developpement/preflight",
                json={"module": "M10", "task": manifest["dev_prompt_id"], "files": []},
            )
            assert response.status_code == 200, response.text
            dev = response.json()
            assert dev["status"] == "available"
            context = {key: dev[key] for key in ("must_know", "evidence", "contradictions", "links")}
            assert context == manifest["dev_context_expected"]
        assert snapshot() == before_dev
        phases.append(
            {
                "fictif": True,
                "phase": "corpus-dev-restaure-via-console",
                "all_meta_unchanged": True,
                "hashes_before_after": before_dev["hashes"],
            }
        )
        before_replay = snapshot()
        replay = evenements.repartir(moteur.departements, maintenant=manifest["maintenant"])
        assert replay["livres"] == replay["echecs"] == replay["quarantaines"] == 0, replay
        assert snapshot() == before_replay
        phases.append(
            {
                "fictif": True,
                "phase": "bus-rejoue-au-repos",
                "resultat": replay,
                "all_meta_unchanged": True,
                "hashes_before_after": before_replay["hashes"],
            }
        )
        assert call("m8-apres-rejeu", "profil") == m8_result
        assert call("m10-apres-rejeu", "memoire") == packet
        with (evidence / "restauration.json").open("x") as stream:
            json.dump(
                {
                    "fictif": True,
                    "parent_pid": manifest["parent_pid"],
                    "backend_pid": os.getpid(),
                    "target_base_url": os.environ["OPSYS_BASE_URL"],
                    "archive_sha256": manifest["archive_sha256"],
                    "affaire_id": manifest["affaire_id"],
                    "wct_id": manifest["wct_id"],
                    "devis_id": manifest["devis_id"],
                    "phases": phases,
                    "restaures": result.restaures,
                    "limites": [
                        "affaire SQLite fictive, restauration dans nouveau processus Python",
                        "les manifestes M5/M8 de fixture sont fournis séparément, hors export",
                        "état Core, jetons Gateway, sessions et index rqa exclus ; pas réappairage physique",
                        "pas PostgreSQL positif, crash pendant effet ou fournisseur réel",
                        "qualification intégrée au job Core tests-opsys",
                    ],
                },
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.write("\n")
    finally:
        moteur.arreter()
        stockage.liberer()


if __name__ == "__main__":
    main()
