"""Projection de profils SMS fictifs : vrai registre/SQLite et vrais fragments, aucun host."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

import pytest
from sqlalchemy import MetaData, Table, select, update
from sqlalchemy.exc import IntegrityError

from opsys import agents, departements, identite, openclaw
from opsys.stockage import schema
from opsys.stockage.schema import AGENTS_CONFIGURABLES

FICTIF = True
SID = "AC" + "0123456789aBcDeF" * 2
ADMIN = "admin-projection-fictif"
TOOL = "m1_recevoir_message_canal"
PALIERS = {nom: {"provider": "anthropic", "model": "modele-fictif"}
           for nom in ("rapide", "standard", "local", "fort")}
ENV = {
    "OPSYS_EMBEDDINGS_URL": "http://embeddings-fictifs.test/v1",
    "OPSYS_EMBEDDINGS_MODELE": "modele-fictif",
    "OPSYS_SMS_COMPTE_SID": SID,
    "OPSYS_SMS_JETON": "canari-secret-fictif-non-restitue",
    "OPSYS_SMS_NUMERO": "+15145550100",
    "OPSYS_SMS_URL_PUBLIQUE": "https://sms-fictif.test/webhook",
    "OPSYS_SMS_POLITIQUES_VALIDEES": "politique-fictive",
}
PROOF_WINDOWS = []
FRAGMENTS_FICTIFS = []


def _encoder(valeur):
    if isinstance(valeur, (dt.date, dt.datetime)):
        return {"date": valeur.isoformat()}
    if isinstance(valeur, (bytes, memoryview)):
        return {"octets": bytes(valeur).hex()}
    raise TypeError("type SQL non pris en charge dans le census fictif")


def snapshot_sql(cnx):
    noms = cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").scalars()
    resultat = {}
    for nom in noms:
        table = schema.META.tables.get(nom)
        if table is None:
            table = Table(nom, MetaData(), autoload_with=cnx)
        lignes = [json.dumps(dict(row), ensure_ascii=False, sort_keys=True, allow_nan=False, default=_encoder)
                  for row in cnx.execute(select(table)).mappings()]
        resultat[nom] = hashlib.sha256(json.dumps(sorted(lignes), ensure_ascii=False).encode()).hexdigest()
    return resultat


def _spec(ident="m01-sms-projection", compte="default", sid=SID):
    return {
        "id": ident, "departement": "m01-front-office", "responsabilite": "Accueil SMS fictif.",
        "palier_modele": "rapide", "outils": [TOOL], "budget_jour": 1000, "budget_mois": 10000,
        "limite_tours": 8, "limite_reessais": 1, "limite_concurrence": 1,
        "declencheurs": [{"type": "canal", "version": 1, "canal": "sms", "compte_id": compte,
                          "account_sid": sid}],
    }


@pytest.fixture
def monde(session):
    deps = departements.charger_departements()
    with session() as cnx:
        identite.creer_personne(cnx, ADMIN, "Admin fictif", "mot-de-passe-projection-fictif", ["admin"])
    return session, deps


def _creer(monde, spec=None, *, actif=True):
    session, deps = monde
    spec = _spec() if spec is None else spec
    with session() as cnx:
        profil = agents.creer(cnx, deps, spec, par=ADMIN, mutation_id="creation-" + spec["id"])
        if actif:
            profil = agents.definir_actif(cnx, profil["id"], deps, True, par=ADMIN,
                                         mutation_id="activation-" + profil["id"], revision_attendue=1)
    return profil


def _arbre(dossier):
    if not dossier.exists():
        return {}
    return {str(p.relative_to(dossier)): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "DIRECTORY"
            for p in sorted(dossier.rglob("*"))}


def _generer(monde, dossier, *, environ=None, refus=False):
    session, deps = monde
    with session() as cnx:
        avant = snapshot_sql(cnx)
    fichiers_avant = _arbre(dossier)
    try:
        if refus:
            with pytest.raises(ValueError, match="projection SMS invalide"):
                openclaw.generer(deps, dossier, PALIERS, environ=ENV if environ is None else environ,
                                 cnx_factory=session)
            assert _arbre(dossier) == fichiers_avant
            assert dossier.exists() is bool(fichiers_avant)
            return None
        return openclaw.generer(deps, dossier, PALIERS, environ=ENV if environ is None else environ,
                                cnx_factory=session)
    finally:
        with session() as cnx:
            apres = snapshot_sql(cnx)
        PROOF_WINDOWS.append({"test": os.environ.get("PYTEST_CURRENT_TEST", "fictif"),
                              "avant": avant, "apres": apres,
                              "fichiers_avant": fichiers_avant, "fichiers_apres": _arbre(dossier)})
        assert apres == avant


def _json(fichiers, cle):
    return json.loads(fichiers[cle].read_text())


def test_selection_default_projette_marker_route_et_permission_native(monde, tmp_path):
    profil = _creer(monde)
    fichiers = _generer(monde, tmp_path / "config")
    entry = _json(fichiers, "agents")["entries"]["opsys-agent-" + profil["id"]]
    assert entry["opsysRuntimeAdmission"] == {
        "profileId": profil["id"], "profileRevision": 2,
        "smsIngress": {"version": 1, "accountId": "default", "accountSid": SID},
    }
    assert _json(fichiers, "bindings") == [{
        "type": "route", "agentId": "opsys-agent-" + profil["id"],
        "comment": ("OPSYS : le canal sms entre par opsys-agent-m01-sms-projection (T2.1-a) ; "
                    "une session par correspondant"),
        "match": {"channel": "sms", "accountId": "default"}, "session": {"dmScope": "per-channel-peer"},
    }]
    assert "opsys_m1__" + TOOL not in entry["tools"]["allow"]
    assert "opsys_m1__" + TOOL in entry["tools"]["deny"]
    assert entry["tools"]["allow"] == [] and "*" in entry["tools"]["deny"]
    assert entry["opsysIsolation"] == {"exec": "sandbox-required"}
    with monde[0]() as cnx:
        assert agents.obtenir(cnx, profil["id"])["outils"] == [TOOL]
    session = _json(fichiers, "session")
    rules = session["sendPolicy"]["rules"]
    assert {"action": "deny", "match": {"channel": "sms"}} in rules
    assert {"action": "deny", "match": {"rawKeyPrefix": "agent:opsys-agent-m01-sms-projection:sms:"}} in rules
    assert {"action": "deny", "match": {"rawKeyPrefix": "agent:m01-front-office:sms:"}} in rules
    sms = _json(fichiers, "channels")["sms"]
    assert sms["enabled"] is True and "accounts" not in sms
    assert sms["accountSid"] == "${OPSYS_SMS_COMPTE_SID}"
    for valeur in (ENV["OPSYS_SMS_JETON"], ENV["OPSYS_SMS_NUMERO"], ENV["OPSYS_SMS_URL_PUBLIQUE"],
                   ENV["OPSYS_SMS_POLITIQUES_VALIDEES"]):
        assert all(valeur not in p.read_text() for p in (tmp_path / "config").rglob("*") if p.is_file())
    FRAGMENTS_FICTIFS.append({"fictif": True, "origine": "openclaw.generer réel, ENV et SQLite fictifs",
                             "marker": entry["opsysRuntimeAdmission"], "politique": entry["tools"],
                             "allow_attendu": [],
                             "channels": _json(fichiers, "channels"), "bindings": _json(fichiers, "bindings"),
                             "session": session})


def test_droit_modele_restant_conserve_allow_exact_et_refus_denvoi(monde, tmp_path):
    lecture = "m1_lister_rappels_appareil"
    spec = _spec()
    spec["outils"] = [TOOL, lecture]
    profil = _creer(monde, spec)
    fichiers = _generer(monde, tmp_path / "config")
    entry = _json(fichiers, "agents")["entries"]["opsys-agent-" + profil["id"]]
    assert entry["tools"]["allow"] == ["opsys_m1__" + lecture]
    assert "*" not in entry["tools"]["deny"]
    assert "opsys_m1__" + TOOL in entry["tools"]["deny"]
    with monde[0]() as cnx:
        assert agents.obtenir(cnx, profil["id"])["outils"] == sorted([TOOL, lecture])
    rules = _json(fichiers, "session")["sendPolicy"]["rules"]
    assert {"action": "deny", "match": {"channel": "sms"}} in rules
    assert {"action": "deny", "match": {"rawKeyPrefix": "agent:opsys-agent-m01-sms-projection:sms:"}} in rules
    FRAGMENTS_FICTIFS.append({"fictif": True, "origine": "openclaw.generer réel, deux droits SQL fictifs",
                             "politique": entry["tools"], "allow_attendu": ["opsys_m1__" + lecture]})


@pytest.mark.parametrize("variable", ["OPSYS_SMS_COMPTE_SID", "OPSYS_SMS_JETON", "OPSYS_SMS_NUMERO",
                                       "OPSYS_SMS_URL_PUBLIQUE", "OPSYS_SMS_POLITIQUES_VALIDEES"])
def test_selection_exige_configuration_active_avant_mkdir(monde, tmp_path, variable):
    _creer(monde)
    env = {k: v for k, v in ENV.items() if k != variable}
    _generer(monde, tmp_path / "absent", environ=env, refus=True)


@pytest.mark.parametrize("sid", [SID + "\n", " " + SID, "AC" + "fedcba9876543210" * 2,
                                 SID.lower().replace("ac", "AC", 1)])
def test_sid_environnement_exact_sans_normalisation(monde, tmp_path, sid):
    _creer(monde)
    _generer(monde, tmp_path / "absent", environ={**ENV, "OPSYS_SMS_COMPTE_SID": sid}, refus=True)


def test_compte_nommee_ne_devient_jamais_default(monde, tmp_path):
    _creer(monde, _spec(compte="cabinet-1"))
    _generer(monde, tmp_path / "absent", refus=True)


@pytest.mark.parametrize("cle", ["channels", "bindings", "session"])
def test_include_manquant_refuse_sans_changer_racine_existante(monde, tmp_path, cle):
    _creer(monde)
    root = tmp_path / "config"
    root.mkdir()
    shape = {k: v for k, v in openclaw.FICHIER_RACINE_MODELE.items() if k != cle}
    (root / "opsys.json").write_text(json.dumps(shape))
    _generer(monde, root, refus=True)


@pytest.mark.parametrize("champ,valeur", [
    ("revision", 9_007_199_254_740_992), ("revision", 2.5),
    ("id", "m01-sms-bad "),
    ("declencheurs", [{"type": "canal", "version": True, "canal": "sms", "compte_id": "default", "account_sid": SID}]),
    ("declencheurs", [{"type": "canal", "version": 1, "canal": "sms", "compte_id": "default"}]),
    ("declencheurs", [{"type": "canal", "version": 1, "canal": "sms", "compte_id": "default",
                      "account_sid": SID, "extra": 1}]),
    ("declencheurs", [{"type": "canal", "version": 1, "canal": "sms", "compte_id": "default",
                      "account_sid": SID}, {"type": "manuel"}]),
    ("declencheurs", ["canal"]), ("declencheurs", None), ("outils", []),
    ("departement", "m03-estimation"),
])
def test_corruption_sql_ne_tombe_pas_en_legacy_et_necrit_rien(monde, tmp_path, champ, valeur):
    profil = _creer(monde)
    encoded = json.dumps(valeur) if champ in {"declencheurs", "outils"} else valeur
    with monde[0]() as cnx:
        cnx.execute(update(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == profil["id"])
                    .values({champ: encoded}))
    _generer(monde, tmp_path / "absent", refus=True)


def test_revision_zero_deja_fermee_par_contrainte_sql(monde):
    profil = _creer(monde)
    with monde[0]() as cnx:
        avant = snapshot_sql(cnx)
    with pytest.raises(IntegrityError, match="revision_positive"), monde[0]() as cnx:
        cnx.execute(update(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == profil["id"])
                    .values(revision=0))
    with monde[0]() as cnx:
        apres = snapshot_sql(cnx)
    PROOF_WINDOWS.append({"test": os.environ.get("PYTEST_CURRENT_TEST", "fictif"),
                          "avant": avant, "apres": apres, "scope": "contrainte SQL existante"})
    assert avant == apres


def test_selection_double_sql_refuse_avant_tous_fichiers(monde, tmp_path):
    _creer(monde)
    other = _creer(monde, _spec(ident="m01-sms-autre"), actif=False)
    with monde[0]() as cnx:
        cnx.execute(update(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == other["id"])
                    .values(actif=True))
    _generer(monde, tmp_path / "absent", refus=True)


def test_profil_inactif_nommee_ne_change_pas_le_legacy(monde, tmp_path):
    _creer(monde, _spec(compte="cabinet-1"), actif=False)
    files = _generer(monde, tmp_path / "legacy", environ={k: v for k, v in ENV.items() if k != "OPSYS_SMS_JETON"})
    entries = _json(files, "agents")["entries"]
    assert "opsys-agent-m01-sms-projection" not in entries
    assert _json(files, "channels")["sms"]["enabled"] is False
    assert _json(files, "bindings")[0]["match"] == {"channel": "sms"}
    assert _json(files, "bindings")[0]["agentId"] == "m01-front-office"


def test_projection_preserve_autres_profils_agents_et_fragments(monde, tmp_path):
    legacy = _spec(ident="m01-legacy-manuel")
    legacy["declencheurs"] = [{"type": "manuel"}]
    p = _creer(monde, legacy)
    old_files = _generer(monde, tmp_path / "before")
    before = {k: _json(old_files, k) for k in ("agents", "channels", "plugins", "models", "roles", "tools")}
    _creer(monde)
    new_files = _generer(monde, tmp_path / "after")
    current = _json(new_files, "agents")
    assert current["entries"]["opsys-agent-" + p["id"]] == before["agents"]["entries"]["opsys-agent-" + p["id"]]
    assert current["entries"]["opsys-agent-" + p["id"]]["tools"]["allow"] == ["opsys_m1__" + TOOL]
    for name, entry in before["agents"]["entries"].items():
        assert current["entries"][name] == entry
    for name in ("channels", "plugins", "models", "roles", "tools"):
        assert _json(new_files, name) == before[name]
