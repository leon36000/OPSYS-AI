"""Profils départementaux fictifs : identité canonique des déclencheurs, sans scheduler exécuté."""
from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64encode

import pytest
from agents_base_qa import provisionner_base_qa

from opsys import agents, agents_base, agents_cron_autorite, agents_cron_retraits, agents_declencheurs, openclaw
from opsys.departements import charger_departements

PALIERS = {"standard": {"provider": "anthropic", "model": "qa-no-provider"}}
ENV = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-qa:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "qa"}
FICTIF = True


@pytest.mark.parametrize("profil,attendu", [
    ({"id": "base-m03-estimation", "departement": "m03-estimation"}, "m03-estimation"),
    ({"id": "specialiste-qa", "departement": "m03-estimation"}, "opsys-agent-specialiste-qa"),
    ({"id": "base-m03-estimation", "departement": "m02-revenue-crm"}, "opsys-agent-base-m03-estimation"),
    ({"id": "base-m03-autre", "departement": "m03-estimation"}, "opsys-agent-base-m03-autre"),
])
def test_identite_agent_base_exige_origine_et_identifiant_exacts(profil, attendu):
    assert agents_base.agent_core_id(profil) == attendu


def test_declencheur_base_projette_agent_departement_et_pas_alias_absent(session, opsys_home, monkeypatch):
    deps = charger_departements()
    profils = provisionner_base_qa(session, deps)
    profil = profils["m03-estimation"]
    with session() as cnx:
        profil = agents.modifier(
            cnx, profil["id"], deps,
            {"id": profil["id"], "outils": [],
             "declencheurs": [{"type": "cron", "expression": "0 7 * * 1-5"}]},
            par="base-admin-fictif", mutation_id="qa-base-trigger-cron-01", revision_attendue=2,
        )
    dossier = opsys_home / "core"
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(dossier))
    fichiers = openclaw.generer(deps, dossier, PALIERS, environ=ENV, cnx_factory=session)
    politique = json.loads(fichiers["memoire_autorites"].read_text())
    assert politique["agents"]["m03-estimation"] == {"departement": "m03-estimation", "mode": "global"}
    intention = agents_declencheurs.demander(
        deps, profil["id"], par="base-admin-fictif", revision_attendue=profil["revision"],
        fuseau="America/Toronto", mutation_id="qa-base-trigger-request-01",
    )
    projection = agents_declencheurs.projeter(deps, intention["intentions"][0], par="base-admin-fictif")
    assert projection["native"]["params"]["agentId"] == "m03-estimation"
    assert projection["execute"] is False
    assert projection["argv"][projection["argv"].index("--agent") + 1] == "m03-estimation"
    # Reçu natif explicitement fictif : protège seulement la jonction retrait/profil SQL,
    # sans revendiquer un cron.add/DELETE Core réellement exécuté.
    ident = intention["intentions"][0]
    declaration = projection["native"]["params"]
    capacite = "42" * 32
    revision = "sha256:" + urlsafe_b64encode(hashlib.sha256(b"qa-cron-base").digest()).decode().rstrip("=")
    owner = agents_cron_autorite.ProprietaireCron(deps, profil["id"])
    plan = owner.preparer(ident, empreinte_capacite=hashlib.sha256(bytes.fromhex(capacite)).hexdigest(),
                          epoch_attendue=0, declaration=declaration)
    owner.accuser(ident, capabilite=capacite, epoch=1, lease_epoch=plan["lease_epoch"],
                  declaration=declaration, job_id="job-base-fictif", config_revision=revision)
    agents_declencheurs.retirer(deps, profil["id"], par="base-admin-fictif",
                               revision_attendue=profil["revision"], mutation_id="qa-base-trigger-retire-01")
    retrait = agents_cron_retraits.ProprietaireRetraitCron(deps, profil["id"], lambda: None)
    commun = dict(capabilite=capacite, epoch=1, declaration=declaration,
                  job_id="job-base-fictif", native_revision=revision)
    preuve = retrait.preparer(ident, **commun)
    assert preuve["execute"] is False
    with pytest.raises(agents_declencheurs.DeclencheurRefuse):
        retrait.preparer(ident, **{**commun, "job_id": "autre-job-fictif"})
    accuse = retrait.accuser(ident, **commun, source_hash=preuve["source_hash"], receipt_id=preuve["receipt_id"])
    assert accuse["etat"] == "retiree"


def test_canal_sur_base_refuse_avant_mutation_et_demande_profil_sms_specialise(session):
    deps = charger_departements()
    profil = provisionner_base_qa(session, deps)["m01-front-office"]
    with session() as cnx, pytest.raises(ValueError, match="profil SMS spécialisé"):
        agents.modifier(cnx, profil["id"], deps,
            {"id": profil["id"], "outils": ["m1_recevoir_message_canal"],
             "declencheurs": [{"type": "canal", "version": 1, "canal": "sms",
                               "compte_id": "qa-base-fictif", "account_sid": "AC" + "a" * 32}]},
            par="base-admin-fictif", mutation_id="qa-base-channel-refused-01", revision_attendue=2)
    with session() as cnx:
        assert agents.obtenir(cnx, profil["id"]) == profil
