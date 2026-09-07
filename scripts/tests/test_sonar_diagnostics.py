"""Contrats de collecte Sonar #182, réponses réseau exclusivement fictives."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import secrets
from pathlib import Path
import sys
import urllib.error

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "sonar_diagnostics.py"
PROJECT = "leon36000_OPSYS-AI"
SHA = "a" * 40
TOKEN = secrets.token_urlsafe(32)  # Jeton éphémère de test, jamais utilisé sur un service réel.


def subject():
    assert SOURCE.is_file(), "exporteur Sonar manquant : aucune collecte vérifiable disponible"
    name = "opsys_sonar_diagnostics_test_subject"
    spec = importlib.util.spec_from_file_location(name, SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def output_directory(mod, tmp_path):
    mod._REPO_ROOT = tmp_path
    directory = tmp_path / ".opsys" / "diagnostics"
    directory.mkdir(parents=True)
    return directory


class FakeAPI:
    """Double du service externe ; aucune réponse n'est une mesure OPSYS-AI."""

    def __init__(self, mod):
        self.calls = []
        self.analysis = {"key": "analysis-1", "revision": SHA, "date": "2026-09-06T12:00:00+0000"}
        self.logged = True
        self.component = {"key": PROJECT, "qualifier": "TRK"}
        self.gate = {"status": "ERROR", "ignoredConditions": False, "conditions": [
            {"metricKey": "new_duplicated_lines_density", "status": "ERROR", "actualValue": "12.7", "errorThreshold": "3", "comparator": "GT"}]}
        self.measures = [{"metric": key, "value": "1"} for key in mod.METRICS]
        self.issues = [{"key": f"I{i}", "project": PROJECT, "component": PROJECT + ":src/a.py", "rule": "python:S0000", "severity": "MAJOR", "type": "BUG", "status": "OPEN", "line": i + 1, "message": "texte exclu", "author": "adresse-privee"} for i in range(3)]
        self.hotspots = [{"key": "H1", "project": PROJECT, "component": PROJECT + ":src/a.py", "ruleKey": "python:S9999", "status": "TO_REVIEW", "line": 3}]
        self.files = [{"key": PROJECT + ":src/a.py", "path": "src/a.py", "qualifier": "FIL", "measures": [{"metric": "duplicated_blocks", "value": "2"}]}]
        self.duplications = {"duplications": [{"blocks": [{"from": 1, "size": 3, "_ref": "1"}, {"from": 7, "size": 3, "_ref": "1"}]}], "files": {"1": {"key": PROJECT + ":src/a.py", "name": "a.py"}}}
        self.hook = None

    def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        if path == "api/users/current":
            result = {"isLoggedIn": self.logged, "login": "identity-excluded", "email": "private-email"}
        elif path == "api/components/show":
            result = {"component": self.component}
        elif path == "api/project_analyses/search":
            result = {"paging": {"pageIndex": 1, "pageSize": 1, "total": 1}, "analyses": [self.analysis]}
        elif path == "api/qualitygates/project_status":
            assert params == {"analysisId": "analysis-1"}
            result = {"projectStatus": self.gate}
        elif path == "api/measures/component":
            result = {"component": dict(self.component, measures=self.measures)}
        elif path == "api/duplications/show":
            result = self.duplications
        else:
            key, rows = {"api/issues/search": ("issues", self.issues), "api/hotspots/search": ("hotspots", self.hotspots), "api/measures/component_tree": ("components", self.files)}[path]
            page = int(params["p"])
            result = {"paging": {"pageIndex": page, "pageSize": 2, "total": len(rows)}, key: rows[(page-1)*2:page*2]}
            if path == "api/measures/component_tree":
                result["baseComponent"] = self.component
        result = copy.deepcopy(result)
        return self.hook(path, params, result) if self.hook else result


def test_collecte_complete_conserve_le_rouge_et_paginations():
    mod = subject()
    api = FakeAPI(mod)
    report = mod.collect(api, SHA)
    assert report["quality_verified"] is False
    assert report["collection_status"] == "COMPLETE"
    assert report["quality_gate"]["status"] == "ERROR"
    assert report["analysis"]["revision"] == SHA
    assert len(report["issues"]) == 3
    assert len(report["hotspots"]) == 1
    assert len(report["duplications"]) == 1
    assert mod.diagnostic_exit_code(report) == 1
    assert [p["p"] for e, p in api.calls if e == "api/issues/search"] == [1, 2]
    assert api.calls[-1][0] == "api/project_analyses/search"
    for endpoint, params in api.calls:
        if endpoint not in {"api/users/current", "api/qualitygates/project_status"}:
            assert params["branch"] == "main"
    text = json.dumps(report)
    assert "private-email" not in text and "identity-excluded" not in text
    assert "texte exclu" not in text and "adresse-privee" not in text


@pytest.mark.parametrize("logged", [False, None, 1, "true"])
def test_session_anonyme_ou_ambigue_refusee(logged):
    mod = subject()
    api = FakeAPI(mod)
    api.logged = logged
    with pytest.raises(mod.ExportError, match="AUTH_REQUIRED"):
        mod.collect(api, SHA)
    assert len(api.calls) == 1


@pytest.mark.parametrize("component", [{}, {"key": "autre", "qualifier": "TRK"}, {"key": PROJECT, "qualifier": "FIL"}])
def test_projet_inaccessible_ou_mauvais_refuse(component):
    mod = subject()
    api = FakeAPI(mod)
    api.component = component
    with pytest.raises(mod.ExportError, match="PROJECT_MISMATCH"):
        mod.collect(api, SHA)


@pytest.mark.parametrize("revision", ["", "b" * 40, None])
def test_analyse_obsolete_refusee(revision):
    mod = subject()
    api = FakeAPI(mod)
    api.analysis["revision"] = revision
    with pytest.raises(mod.ExportError, match="REVISION_MISMATCH"):
        mod.collect(api, SHA)


@pytest.mark.parametrize("sha", ["main", "a" * 39, "A" * 40, "../bad", "0" * 40])
def test_commit_attendu_exact_obligatoire(sha):
    mod = subject()
    api = FakeAPI(mod)
    with pytest.raises(mod.ExportError, match="EXPECTED_REVISION_INVALID"):
        mod.collect(api, sha)
    assert api.calls == []


def test_changement_analyse_pendant_collecte_refuse():
    mod = subject()
    api = FakeAPI(mod)
    def drift(path, params, response):
        if path == "api/project_analyses/search" and sum(e == path for e, _ in api.calls) > 1:
            response["analyses"][0]["key"] = "analysis-2"
        return response
    api.hook = drift
    with pytest.raises(mod.ExportError, match="ANALYSIS_CHANGED"):
        mod.collect(api, SHA)


@pytest.mark.parametrize("fault", ["missing_paging", "wrong_index", "empty_second", "duplicate", "total_changed", "bool_total", "too_many"])
def test_pagination_incomplete_incoherente_ou_dupliquee_refusee(fault):
    mod = subject()
    api = FakeAPI(mod)
    def break_page(path, params, response):
        if path != "api/issues/search":
            return response
        page = params["p"]
        if fault == "missing_paging":
            response.pop("paging")
        elif fault == "wrong_index":
            response["paging"]["pageIndex"] = 99
        elif fault == "bool_total":
            response["paging"]["total"] = True
        elif fault == "too_many":
            response["paging"]["total"] = mod.MAX_ITEMS + 1
        elif page == 2:
            if fault == "empty_second":
                response["issues"] = []
            elif fault == "duplicate":
                response["issues"][0]["key"] = "I0"
            elif fault == "total_changed":
                response["paging"]["total"] = 4
        return response
    api.hook = break_page
    with pytest.raises(mod.ExportError, match="PAGINATION|DUPLICATE|LIMIT"):
        mod.collect(api, SHA)


def test_metrique_absente_reste_non_mesuree():
    mod = subject()
    api = FakeAPI(mod)
    removed = api.measures.pop()
    report = mod.collect(api, SHA)
    assert removed["metric"] in report["missing_metrics"]
    assert mod.diagnostic_exit_code(report) != 0


@pytest.mark.parametrize("status", [None, "PASS", True, ""])
def test_statut_gate_inconnu_ne_devient_pas_vert(status):
    mod = subject()
    api = FakeAPI(mod)
    api.gate["status"] = status
    with pytest.raises(mod.ExportError, match="GATE_INVALID"):
        mod.collect(api, SHA)


def test_gate_ok_ne_vaut_pas_qualification_globale():
    mod = subject()
    api = FakeAPI(mod)
    api.gate = {"status": "OK", "conditions": [{"metricKey": "coverage", "status": "OK"}], "ignoredConditions": False}
    report = mod.collect(api, SHA)
    assert mod.diagnostic_exit_code(report) == 0
    assert report["quality_verified"] is False
    api.gate["ignoredConditions"] = True
    assert mod.diagnostic_exit_code(mod.collect(api, SHA)) == 3


def test_issues_vides_ne_transforment_pas_le_gate_rouge_en_vert():
    mod = subject()
    api = FakeAPI(mod)
    api.issues = []
    report = mod.collect(api, SHA)
    assert report["issues"] == []
    assert mod.diagnostic_exit_code(report) == 1
    assert report["quality_verified"] is False


def test_dupliquations_annoncees_sans_bloc_refusees():
    mod = subject()
    api = FakeAPI(mod)
    api.duplications["duplications"] = []
    with pytest.raises(mod.ExportError, match="DUPLICATION_DETAILS_MISSING"):
        mod.collect(api, SHA)


@pytest.mark.parametrize("bad_ref", ["absent", "", None])
def test_reference_bloc_duplique_inconnue_refusee(bad_ref):
    mod = subject()
    api = FakeAPI(mod)
    api.duplications["duplications"][0]["blocks"][0]["_ref"] = bad_ref
    with pytest.raises(mod.ExportError, match="DUPLICATION_INVALID"):
        mod.collect(api, SHA)


@pytest.mark.parametrize("token", ["", "\n", "secret\r\ninjection", "spaces forbidden"])
def test_token_absent_ou_entete_invalide_refuse_sans_reseau(token):
    mod = subject()
    with pytest.raises(mod.ExportError, match="TOKEN_REQUIRED|TOKEN_INVALID"):
        mod.SonarClient(token)


def test_transport_get_tls_destination_fixe_et_pas_token_dans_url(monkeypatch):
    mod = subject()
    client = mod.SonarClient(TOKEN)
    observed = []
    class Opener:
        def open(self, request, timeout):
            observed.append((request, timeout))
            return io.BytesIO(b'{"isLoggedIn":true}')
    client.opener = Opener()
    assert client.get("api/users/current", {}) == {"isLoggedIn": True}
    request, timeout = observed[0]
    assert request.full_url == "https://sonarcloud.io/api/users/current"
    assert request.get_method() == "GET" and request.data is None
    assert request.get_header("Authorization") == "Bearer " + TOKEN
    assert TOKEN not in request.full_url and timeout == 15
    assert any(isinstance(h, mod.NoRedirect) for h in mod.SonarClient(TOKEN).opener.handlers)


@pytest.mark.parametrize("bad_path", ["https://example.org/", "api/issues/do_transition", "../x", "api/users/current?x=1"])
def test_destination_et_actions_non_autorisees_refusees(bad_path):
    mod = subject()
    with pytest.raises(mod.ExportError, match="ENDPOINT_REFUSED"):
        mod.SonarClient(TOKEN).get(bad_path, {})


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 429, 500])
def test_erreur_http_sans_fuite_du_corps_ou_token(status):
    mod = subject()
    client = mod.SonarClient(TOKEN)
    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, TOKEN, {}, io.BytesIO(TOKEN.encode()))
    client.opener = Opener()
    with pytest.raises(mod.ExportError, match=f"HTTP_{status}") as caught:
        client.get("api/users/current", {})
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("payload", [b'not JSON', b'[]', b'{"a":NaN}', b'{"a":1,"a":2}', b'\xff'])
def test_json_invalide_ou_ambigu_refuse(payload):
    mod = subject()
    client = mod.SonarClient(TOKEN)
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(payload)
    client.opener = Opener()
    with pytest.raises(mod.ExportError, match="JSON_INVALID"):
        client.get("api/users/current", {})


def test_sortie_pas_de_token_et_pas_ecrasement(tmp_path):
    mod = subject()
    tmp_path = output_directory(mod, tmp_path)
    report = mod.collect(FakeAPI(mod), SHA)
    target = tmp_path / "export.json"
    mod.write_export(target, report, TOKEN)
    data = json.loads(target.read_text())
    canonical = mod.canonical(data["report"])
    assert data["sha256"] == hashlib.sha256(canonical).hexdigest()
    before = target.read_bytes()
    with pytest.raises(mod.ExportError, match="OUTPUT_EXISTS"):
        mod.write_export(target, report, TOKEN)
    assert target.read_bytes() == before
    with pytest.raises(mod.ExportError, match="TOKEN_IN_OUTPUT"):
        mod.write_export(tmp_path / "bad.json", dict(report, reflected=TOKEN), TOKEN)
    assert not (tmp_path / "bad.json").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["export.json"]


def test_cli_sans_token_ne_cree_pas_un_faux_export(tmp_path, monkeypatch, capsys):
    mod = subject()
    tmp_path = output_directory(mod, tmp_path)
    monkeypatch.delenv("SONAR_TOKEN", raising=False)
    dest = tmp_path / "export.json"
    assert mod.main(["--revision", SHA, "--output", str(dest)]) == 2
    assert "TOKEN_REQUIRED" in capsys.readouterr().err
    assert not dest.exists()


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity"])
def test_metrique_sans_valeur_finie_n_est_pas_mesuree(value):
    mod = subject()
    api = FakeAPI(mod)
    api.measures[-1]["value"] = value
    report = mod.collect(api, SHA)
    assert api.measures[-1]["metric"] in report["missing_metrics"]


def test_projections_imbriquees_excluent_les_champs_non_prevus():
    mod = subject()
    api = FakeAPI(mod)
    api.issues[0]["textRange"] = {"startLine": 1, "endLine": 1, "source": "excluded-nested-source"}
    api.issues[0]["impacts"] = [{"severity": "HIGH", "softwareQuality": "SECURITY", "author": "excluded-nested-author"}]
    report = mod.collect(api, SHA)
    assert "excluded-nested" not in json.dumps(report)


def test_aucune_requete_vers_un_fichier_d_un_autre_projet():
    mod = subject()
    api = FakeAPI(mod)
    api.files[0]["key"] = "another-project:secret.py"
    with pytest.raises(mod.ExportError, match="COMPONENT_OUTSIDE_PROJECT"):
        mod.collect(api, SHA)
    assert not any(path == "api/duplications/show" for path, _ in api.calls)


@pytest.mark.parametrize("bad_date", ["yesterday", "2026-09-06", "2026-09-06T12:00:00"])
def test_date_analyse_invalide_ou_sans_fuseau_refusee(bad_date):
    mod = subject()
    api = FakeAPI(mod)
    api.analysis["date"] = bad_date
    with pytest.raises(mod.ExportError, match="ANALYSIS_DATE_INVALID"):
        mod.collect(api, SHA)


def test_redirection_reelle_du_handler_refuse_et_ferme_le_flux():
    mod = subject()
    stream = io.BytesIO(b"redirect fixture")
    with pytest.raises(mod.ExportError, match="REDIRECT_REFUSED"):
        mod.NoRedirect().redirect_request(None, stream, 302, "Found", {}, "https://example.org")
    assert stream.closed


def test_reponse_bornee_et_timeout_sans_fuite(monkeypatch):
    mod = subject()
    client = mod.SonarClient(TOKEN)
    monkeypatch.setattr(mod, "MAX_RESPONSE", 10)
    class TooLarge:
        def open(self, request, timeout):
            return io.BytesIO(b"x" * 11)
    client.opener = TooLarge()
    with pytest.raises(mod.ExportError, match="RESPONSE_LIMIT"):
        client.get("api/users/current", {})
    class Timeout:
        def open(self, request, timeout):
            raise TimeoutError(TOKEN)
    client.opener = Timeout()
    with pytest.raises(mod.ExportError, match="TRANSPORT_UNAVAILABLE") as caught:
        client.get("api/users/current", {})
    assert TOKEN not in str(caught.value)


def test_erreur_arguments_ne_reimprime_pas_une_valeur_sensible(capsys):
    mod = subject()
    with pytest.raises(SystemExit) as caught:
        mod.main(["--revision", SHA, "--output", "x.json", "--token", TOKEN])
    assert caught.value.code == 2
    assert TOKEN not in capsys.readouterr().err


def test_mesures_periodiques_conservent_la_forme_et_pas_de_faux_zero():
    mod = subject()
    api = FakeAPI(mod)
    api.measures[0] = {"metric": mod.METRICS[0], "period": {"index": 1, "value": "1"}}
    api.measures[1] = {"metric": mod.METRICS[1], "periods": [{"index": 1, "value": "3"}]}
    report = mod.collect(api, SHA)
    assert report["measures"][0] == api.measures[0]
    assert report["measures"][1] == api.measures[1]
    assert report["missing_metrics"] == []


def test_sortie_en_cas_erreur_ne_publie_rien_et_preserve_symlink(tmp_path, monkeypatch):
    mod = subject()
    tmp_path = output_directory(mod, tmp_path)
    report = mod.collect(FakeAPI(mod), SHA)
    existing = tmp_path / "important"
    existing.write_text("preserved")
    target = tmp_path / "export.json"
    target.symlink_to(existing)
    with pytest.raises(mod.ExportError, match="OUTPUT_EXISTS"):
        mod.write_export(target, report, TOKEN)
    assert existing.read_text() == "preserved" and target.is_symlink()
    def fail(*args, **kwargs):
        raise OSError("fixture-disk-error")
    monkeypatch.setattr(mod.os, "fsync", fail)
    with pytest.raises(OSError, match="fixture-disk-error"):
        mod.write_export(tmp_path / "failed.json", report, TOKEN)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["export.json", "important"]


def test_cli_exporte_rouge_sans_annoncer_qualification(tmp_path, monkeypatch, capsys):
    mod = subject()
    tmp_path = output_directory(mod, tmp_path)
    api = FakeAPI(mod)
    monkeypatch.setenv("SONAR_TOKEN", TOKEN)
    monkeypatch.setattr(mod.SonarClient, "get", lambda self, path, params: api(path, params))
    output = tmp_path / "diagnostic.json"
    assert mod.main(["--revision", SHA, "--output", str(output)]) == 1
    assert output.exists()
    assert "quality_verified=false" in capsys.readouterr().out
    assert json.loads(output.read_text())["report"]["quality_gate"]["status"] == "ERROR"


def test_issue_portant_sur_le_projet_reste_collectable():
    mod = subject()
    api = FakeAPI(mod)
    api.issues[0]["component"] = PROJECT
    assert mod.collect(api, SHA)["issues"][0]["component"] == PROJECT


@pytest.mark.parametrize("endpoint,key,value", [
    ("api/project_analyses/search", "analyses", []),
    ("api/project_analyses/search", "analyses", [None]),
    ("api/qualitygates/project_status", "projectStatus", {}),
    ("api/issues/search", "issues", {}),
    ("api/hotspots/search", "hotspots", [1]),
])
def test_reponse_structurellement_incomplete_refusee(endpoint, key, value):
    mod = subject()
    api = FakeAPI(mod)
    def corrupt(path, params, response):
        if path == endpoint:
            response[key] = value
        return response
    api.hook = corrupt
    with pytest.raises(mod.ExportError):
        mod.collect(api, SHA)


@pytest.mark.parametrize("kind", ["missing_key", "duplicate_metric", "unknown_number", "wrong_project", "bad_condition", "bad_qualifier", "missing_dup_metric", "empty_blocks", "bad_line"])
def test_refus_precis_des_artefacts_invalides(kind):
    mod = subject()
    api = FakeAPI(mod)
    if kind == "missing_key":
        api.issues[0].pop("key")
    elif kind == "duplicate_metric":
        api.measures.append(dict(api.measures[0]))
    elif kind == "unknown_number":
        api.measures[0]["value"] = "n/a"
        report = mod.collect(api, SHA)
        assert mod.METRICS[0] in report["missing_metrics"]
        return
    elif kind == "wrong_project":
        api.issues[0]["project"] = "autre"
    elif kind == "bad_condition":
        api.gate["conditions"][0]["status"] = "SUCCESS"
    elif kind == "bad_qualifier":
        api.files[0]["qualifier"] = "DIR"
    elif kind == "missing_dup_metric":
        api.files[0]["measures"] = []
    elif kind == "empty_blocks":
        api.duplications["duplications"][0]["blocks"] = []
    elif kind == "bad_line":
        api.duplications["duplications"][0]["blocks"][0]["size"] = 0
    with pytest.raises(mod.ExportError):
        mod.collect(api, SHA)


def test_zero_duplication_ne_demande_pas_de_blocs():
    mod = subject()
    api = FakeAPI(mod)
    api.files[0]["measures"][0]["value"] = "0"
    assert mod.collect(api, SHA)["duplications"] == []
    assert not any(e == "api/duplications/show" for e, _ in api.calls)


def test_erreur_disque_cli_est_explicite_et_ne_fuit_pas(tmp_path, monkeypatch, capsys):
    mod = subject()
    tmp_path = output_directory(mod, tmp_path)
    api = FakeAPI(mod)
    monkeypatch.setenv("SONAR_TOKEN", TOKEN)
    monkeypatch.setattr(mod.SonarClient, "get", lambda self, path, params: api(path, params))
    tmp_path.rmdir()
    dest = tmp_path / "export.json"
    assert mod.main(["--revision", SHA, "--output", str(dest)]) == 2
    err = capsys.readouterr().err
    assert "OUTPUT_IO_ERROR" in err and TOKEN not in err
    assert not dest.exists()


def test_credential_de_test_regenere_a_chaque_chargement(monkeypatch):
    import runpy
    import secrets

    samples = iter(("first-ephemeral-fixture", "second-ephemeral-fixture"))
    calls = []

    def generate(size):
        calls.append(size)
        return next(samples)

    monkeypatch.setattr(secrets, "token_urlsafe", generate)
    first = runpy.run_path(str(Path(__file__)))
    second = runpy.run_path(str(Path(__file__)))
    assert calls == [32, 32]
    assert first["TOKEN"] == "first-ephemeral-fixture"
    assert second["TOKEN"] == "second-ephemeral-fixture"


@pytest.mark.parametrize("kind", ["outside", "dotdot", "prefix", "nested", "backslash", "bad_suffix"])
def test_destination_non_confinee_refusee_avant_ecriture(tmp_path, monkeypatch, kind):
    mod = subject()
    root = output_directory(mod, tmp_path)
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    prefix = tmp_path / ".opsys" / "diagnostics-extra"
    prefix.mkdir()
    (root / "nested").mkdir()
    choices = {
        "outside": outside / "export.json",
        "dotdot": root / ".." / "export.json",
        "prefix": prefix / "export.json",
        "nested": root / "nested" / "export.json",
        "backslash": root / "bad\\name.json",
        "bad_suffix": root / "export.py",
    }
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    with pytest.raises(mod.ExportError, match="OUTPUT_PATH_REFUSED"):
        mod.write_export(choices[kind], mod.collect(FakeAPI(mod), SHA), TOKEN)
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == before


def test_nom_simple_est_ancre_au_repertoire_du_depot(tmp_path, monkeypatch):
    mod = subject()
    root = output_directory(mod, tmp_path)
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    mod.write_export(Path("diagnostic.json"), mod.collect(FakeAPI(mod), SHA), TOKEN)
    assert (root / "diagnostic.json").is_file()
    assert (root / "diagnostic.json").stat().st_mode & 0o777 == 0o600
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize("component", [".opsys", "diagnostics"])
def test_symlink_du_repertoire_export_refuse(tmp_path, component):
    mod = subject()
    root = output_directory(mod, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    if component == ".opsys":
        (outside / "diagnostics").mkdir()
        root.rmdir()
        root.parent.rmdir()
        root.parent.symlink_to(outside, target_is_directory=True)
    else:
        root.rmdir()
        root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(mod.ExportError, match="OUTPUT_ROOT_UNSAFE"):
        mod.write_export(root / "diagnostic.json", mod.collect(FakeAPI(mod), SHA), TOKEN)
    assert not list(outside.rglob("*.json"))
    assert not list(outside.rglob(".sonar-export-*"))


def test_remplacement_du_repertoire_pendant_ecriture_ne_redirige_pas(tmp_path, monkeypatch):
    mod = subject()
    root = output_directory(mod, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = root.with_name("diagnostics-moved")
    fsync = mod.os.fsync
    def replace_directory(fd):
        fsync(fd)
        root.rename(moved)
        root.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(mod.os, "fsync", replace_directory)
    mod.write_export(root / "diagnostic.json", mod.collect(FakeAPI(mod), SHA), TOKEN)
    assert list(outside.iterdir()) == []
    assert sorted(p.name for p in moved.iterdir()) == ["diagnostic.json"]


def test_cli_refuse_destination_hors_scope_sans_requete_reseau(tmp_path, monkeypatch, capsys):
    mod = subject()
    output_directory(mod, tmp_path)
    monkeypatch.setenv("SONAR_TOKEN", TOKEN)
    calls = []
    api = FakeAPI(mod)
    def get(self, path, params):
        calls.append(path)
        return api(path, params)
    monkeypatch.setattr(mod.SonarClient, "get", get)
    output = tmp_path / "outside.json"
    assert mod.main(["--revision", SHA, "--output", str(output)]) == 2
    assert "OUTPUT_PATH_REFUSED" in capsys.readouterr().err
    assert calls == [] and not output.exists()


@pytest.mark.parametrize("value", ["١", "１２", "²", "1٢"])
def test_compte_duplication_refuse_chiffres_non_ascii(value):
    mod = subject()
    api = FakeAPI(mod)
    api.files[0]["measures"][0]["value"] = value
    with pytest.raises(mod.ExportError, match="DUPLICATION_METRIC_MISSING"):
        mod.collect(api, SHA)


@pytest.mark.parametrize("error", [urllib.error.URLError("fixture"), TimeoutError("fixture"), OSError("fixture")])
def test_erreurs_transport_redundantes_restent_capturees(error):
    mod = subject()
    client = mod.SonarClient(TOKEN)
    class Failing:
        def open(self, request, timeout):
            raise error
    client.opener = Failing()
    with pytest.raises(mod.ExportError, match="TRANSPORT_UNAVAILABLE"):
        client.get("api/users/current", {})
