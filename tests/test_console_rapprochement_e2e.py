"""Parcours navigateur du rapprochement M5 avec application et calculateur réels, données fictives."""
from __future__ import annotations

import json
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import m5_financecore.outils as m5_outils
import pytest
import yaml
from fastapi.testclient import TestClient
from httpx import Response

from opsys import identite, stockage
from opsys.console import application, finance_snapshot_prive, obligations_privees
from opsys.console.securite import Configuration
from opsys.departements import charger_departements

FICTIF = True
SECRET = "secret-integration-rapprochement-fictif-" + "x" * 32
PREFIX = "/opsys"
OWNER = "owner-rapprochement-integration-fictif"
ADMIN = "admin-rapprochement-integration-fictif"
PASSWORD = "mot-de-passe-rapprochement-fictif-123"
PRIVATE_REF = "RELEVE-PRIVE-NE-DOIT-PAS-SORTIR"


class _Forms(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.select_name: str | None = None
        self.select_first: str | None = None
        self.select_selected: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "form":
            self.current = {"action": attr.get("action") or ""}
        elif tag == "input" and self.current is not None and attr.get("name"):
            self.current[attr["name"]] = attr.get("value") or ""
        elif tag == "select" and self.current is not None:
            self.select_name = attr.get("name")
            self.select_first = None
            self.select_selected = None
        elif tag == "option" and self.select_name is not None:
            value = attr.get("value") or ""
            if self.select_first is None:
                self.select_first = value
            if "selected" in attr:
                self.select_selected = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self.current is not None and self.select_name:
            self.current[self.select_name] = self.select_selected or self.select_first or ""
            self.select_name = None
        elif tag == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


def _forms(html: str) -> list[dict[str, str]]:
    parser = _Forms()
    parser.feed(html)
    return parser.forms


def _form_for(html: str, action: str, *, obligation_id: str | None = None,
              source_ref: str | None = None) -> dict[str, str]:
    for form in _forms(html):
        if form.get("action") != action:
            continue
        if obligation_id is not None and form.get("obligation_id") != obligation_id:
            continue
        if source_ref is not None and form.get("source_ref") != source_ref:
            continue
        return form
    raise AssertionError(f"formulaire fictif introuvable : {action}/{obligation_id}/{source_ref}")


@pytest.fixture
def client_rapprochement(session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    m5_outils.utiliser_stockage_durable()
    manifest = tmp_path / "department.yaml"
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifest)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, OWNER, "Owner fictif", PASSWORD, ["nathan_owner", "admin"])
        identite.creer_personne(cnx, ADMIN, "Admin seul fictif", PASSWORD, ["admin"])
    base_config = {
        "fiscal": {
            "frequence_tps_tvq": "trimestrielle",
            "mois_fin_exercice": 12,
            "taxes_remises_jusqu_au": "2026-09-30",
        },
        "obligations_declarees": {
            "das": {"montant": "0.00", "source": "DAS fictives complètes", "au": date.today().isoformat()},
            "dettes": {"montant": "0.00", "source": "dettes fictives complètes", "au": date.today().isoformat()},
        },
    }
    manifest.write_text(yaml.safe_dump({"configuration": base_config}, allow_unicode=True), encoding="utf-8")
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe=PREFIX), charger_departements(), session,
    )
    assert any(getattr(route, "path", None) == "/finance/paie/rapprochements" for route in app.routes)
    with TestClient(app, base_url="http://testserver") as client:
        yield client
    stockage.liberer()


def _login(client: TestClient, user: str = OWNER) -> str:
    retour = client.post(
        f"{PREFIX}/connexion", data={"identifiant": user, "mot_de_passe": PASSWORD}, follow_redirects=False,
    )
    assert retour.status_code == 303
    return client.get(f"{PREFIX}/api/session").json()["csrf"]


def _private_obligation(csrf: str, *, kind: str = "paies", amount: str = "1250.00",
                        obligation_id: str = "a" * 32, revision: str = "0") -> dict[str, str]:
    return {
        "type": kind, "montant_cad": amount,
        "periode_debut": "2026-10-01", "periode_fin": "2026-10-02",
        "date_paie": "2026-10-06", "echeance": "2026-10-07",
        "reference_piece": PRIVATE_REF, "autorite": "source fictive privée",
        "source_consultee_le": date.today().isoformat(),
        "applicable_du": "2026-01-01", "applicable_au": "2026-12-31",
        "version": "édition-fictive-2026", "revision_attendue": revision,
        "mutation_id": obligation_id, "csrf": csrf,
    }


def _ajouter_mouvement(type_mouvement: str, amount: str, minute: int) -> dict[str, Any]:
    with stockage.transaction():
        result = m5_outils.enregistrer_mouvement(
            amount, type_mouvement, f"{date.today().isoformat()}T12:{minute:02d}:00+00:00",
            "STANDARD", f"écriture {type_mouvement} fictive",
        )
    assert result["accepte"] is True, result
    return result["resultat"]


def _lier(client: TestClient, csrf: str, action: str, *, obligation_id: str | None = None,
          source_ref: str | None = None, amount: str | None = None) -> Response:
    page = client.get(f"{PREFIX}/finance/paie/rapprochements")
    assert page.status_code == 200, page.text
    form = _form_for(page.text, action, obligation_id=obligation_id, source_ref=source_ref)
    form["csrf"] = csrf
    if amount is not None:
        form["montant_cad"] = amount
    response = client.post(f"{PREFIX}/finance/paie/rapprochements", data=form, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"{PREFIX}/finance/paie/rapprochements"
    return response


def _lectures_base() -> dict[str, Any]:
    with stockage.transaction():
        loaded = yaml.safe_load(m5_outils._MANIFESTE.read_text(encoding="utf-8"))
        configuration = loaded["configuration"]
        return m5_outils._lectures_finance(
            m5_outils._registre_mouvements(None), configuration=configuration,
            validateur_snapshot=m5_outils._valider_chaines_cfo,
        )


def _resultat_reel_prive():
    with stockage.transaction() as cnx:
        return finance_snapshot_prive.calculer_vue_privee(cnx, obligations_privees)


def _diagnostic_prive():
    with stockage.transaction() as cnx:
        capture = finance_snapshot_prive.capturer_snapshot_prive(cnx)
        projection = obligations_privees.lire_rapprochements(cnx, capture.snapshot_builder)
        cash = m5_outils._resultat_cash_libre(
            finance_snapshot_prive._private_declarations(capture._lectures, projection)
        ) if projection["statut"] == "CONNU" else {}
        return {"sources_courantes": capture.verifier_sources_courantes(),
                "projection": projection["statut"], "raisons": projection["raisons"],
                "cash": {k: v for k, v in cash.items() if k in {"cash_libre", "manque", "statut"}}}


def test_reel_legacy_exact_cash_source_stale_reconfirmation_et_frontieres(client_rapprochement: TestClient,
                                                                            session):
    client = client_rapprochement
    _ajouter_mouvement("ENCAISSEMENT", "10000.00", 1)
    legacy = {"montant": "1250.00", "source": "journal de paie déclaré fictif", "au": date.today().isoformat()}
    config = yaml.safe_load(m5_outils._MANIFESTE.read_text(encoding="utf-8"))
    config["configuration"]["obligations_declarees"]["paies"] = legacy
    m5_outils._MANIFESTE.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    csrf = _login(client)
    declaration = client.post(
        f"{PREFIX}/finance/paie/obligations", data=_private_obligation(csrf), follow_redirects=False,
    )
    assert declaration.status_code in {200, 303}, declaration.text
    das = client.post(f"{PREFIX}/finance/paie/obligations", data=_private_obligation(
        csrf, kind="das", amount="0.00", obligation_id="d" * 32, revision="1",
    ), follow_redirects=False)
    assert das.status_code in {200, 303}, das.text
    page = client.get(f"{PREFIX}/finance/paie/rapprochements")
    assert page.status_code == 200 and "INCONNU" in page.text and "1250.00" in page.text
    invalid_csrf = _form_for(page.text, "LEGACY_IDENTIQUE", obligation_id="a" * 32, source_ref="paies")
    invalid_csrf["csrf"] = "csrf-fictif-invalide"
    assert client.post(f"{PREFIX}/finance/paie/rapprochements", data=invalid_csrf).status_code == 403
    with session():
        assert len(stockage.maillons("m05-financecore", "obligations_paies_das_privees")) == 2
    _lier(client, csrf, "LEGACY_IDENTIQUE", obligation_id="a" * 32, source_ref="paies")
    _lier(client, csrf, "LEGACY_IDENTIQUE", obligation_id="d" * 32, source_ref="das", amount="0.00")
    sans_reserves = client.get(f"{PREFIX}/finance/paie/rapprochements")
    assert sans_reserves.status_code == 200 and "État actuel : INCONNU" in sans_reserves.text
    assert "Composante financière non calculable : Réserves critiques" in sans_reserves.text
    assert _resultat_reel_prive()["montant_utilisable"] is None
    # Absence de provision ne vaut pas réserve zéro. La personne la déclare explicitement.
    config["configuration"]["obligations_declarees"]["reserves"] = {
        "montant": "0.00", "source": "aucune réserve décidée, fixture fictive", "au": date.today().isoformat(),
    }
    m5_outils._MANIFESTE.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    _lier(client, csrf, "LEGACY_IDENTIQUE", obligation_id="a" * 32, source_ref="paies")
    _lier(client, csrf, "LEGACY_IDENTIQUE", obligation_id="d" * 32, source_ref="das", amount="0.00")
    final = client.get(f"{PREFIX}/finance/paie/rapprochements")
    assert final.status_code == 200 and "État actuel : CONNU" in final.text, _diagnostic_prive()
    assert "no-store" in final.headers["cache-control"]

    base = _lectures_base()
    expected = m5_outils._resultat_cash_libre(base)
    actual = _resultat_reel_prive()
    assert actual["statut"] == "CONNU"
    assert actual["cash_libre"]["cash_libre"] == expected["cash_libre"]
    assert format(expected["cash_libre"], "f") in final.text

    _ajouter_mouvement("ENCAISSEMENT", "50.00", 2)
    assert _resultat_reel_prive()["statut"] == "INCONNU"
    stale_page = client.get(f"{PREFIX}/finance/paie/rapprochements")
    assert stale_page.status_code == 200 and "État actuel : INCONNU" in stale_page.text
    _lier(client, csrf, "LEGACY_IDENTIQUE", obligation_id="a" * 32, source_ref="paies")
    _lier(client, csrf, "LEGACY_IDENTIQUE", obligation_id="d" * 32, source_ref="das", amount="0.00")
    final_reconfirme = client.get(f"{PREFIX}/finance/paie/rapprochements")
    assert "État actuel : CONNU" in final_reconfirme.text
    expected_reconfirme = m5_outils._resultat_cash_libre(_lectures_base())
    assert format(expected_reconfirme["cash_libre"], "f") in final_reconfirme.text

    # L'API financière ordinaire ne contient pas la pièce privée ni ses marqueurs, et admin seul ne lit pas le HTML.
    public = client.get(f"{PREFIX}/api/finance/cash-libre")
    assert public.status_code == 200, public.text
    assert PRIVATE_REF not in public.text and "édition-fictive-2026" not in public.text
    with session():
        ciphertext_rows = list(stockage.maillons("m05-financecore", "obligations_paies_das_privees"))
    assert PRIVATE_REF not in json.dumps(ciphertext_rows, ensure_ascii=False)
    admin_csrf = _login(client, ADMIN)
    assert admin_csrf
    assert client.get(f"{PREFIX}/finance/paie/rapprochements").status_code == 403
    with session():
        assert len(stockage.maillons("m05-financecore", "obligations_paies_das_privees")) == 8


def test_reel_nouvelle_composante_credit_provision_et_classement_hors_paies(
    client_rapprochement: TestClient, session,
):
    client = client_rapprochement
    _ajouter_mouvement("ENCAISSEMENT", "10000.00", 1)
    first = _ajouter_mouvement("PROVISION", "100.00", 2)
    second = _ajouter_mouvement("PROVISION", "200.00", 3)
    csrf = _login(client)
    declaration = client.post(
        f"{PREFIX}/finance/paie/obligations", data=_private_obligation(csrf), follow_redirects=False,
    )
    assert declaration.status_code in {200, 303}, declaration.text
    das = client.post(f"{PREFIX}/finance/paie/obligations", data=_private_obligation(
        csrf, kind="das", amount="0.00", obligation_id="d" * 32, revision="1",
    ), follow_redirects=False)
    assert das.status_code in {200, 303}, das.text

    _lier(client, csrf, "NOUVELLE_COMPOSANTE", obligation_id="a" * 32, amount="1250.00")
    _lier(client, csrf, "LEGACY_IDENTIQUE", obligation_id="d" * 32, source_ref="das", amount="0.00")
    _lier(client, csrf, "PROVISION_CREDIT", obligation_id="a" * 32, source_ref=first["ligne_id"], amount="25.00")
    _lier(client, csrf, "PROVISION_HORS_PAIE", obligation_id="", source_ref=second["ligne_id"], amount="200.00")
    page = client.get(f"{PREFIX}/finance/paie/rapprochements")
    assert page.status_code == 200 and "État actuel : CONNU" in page.text, _diagnostic_prive()

    base = _lectures_base()
    adapted = dict(base)
    adapted["declarees"] = dict(base["declarees"])
    adapted["declarees"]["paies"] = {
        "montant": "1250.00", "source": "rapprochement privé confirmé", "au": date.today().isoformat(),
    }
    total, count, latest = base["provisions"]
    adapted["provisions"] = (total - 25, count, latest)
    expected = m5_outils._resultat_cash_libre(adapted)
    actual = _resultat_reel_prive()
    assert actual["statut"] == "CONNU"
    assert actual["cash_libre"]["cash_libre"] == expected["cash_libre"]
    assert actual["cash_libre"]["cash_libre"] is not None
    assert format(expected["cash_libre"], "f") in page.text
    with session():
        assert len(stockage.maillons("m05-financecore", "obligations_paies_das_privees")) == 6
