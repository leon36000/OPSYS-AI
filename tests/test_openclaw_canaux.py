"""Canaux du public dans la configuration d'OPSYS-CORE (PLAN T2.1-a) : SMS -> agent M1.

Chaque clé et chaque valeur que `opsys openclaw configurer` écrit pour le canal est confrontée au schéma du fork,
lu dans ses sources (`tests/fixtures/schema_ts.py` : le core ne s'exécute pas dans ce bac à sable ; le job
`e2e-core` de la CI passe ensuite le vrai `openclaw config validate` sur la même configuration). Aucun secret :
les tests fournissent des valeurs reconnaissables et vérifient qu'aucun fichier généré ne les contient.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import schema_ts as ts
from m10_memoire import liaison

from opsys import canaux, cli, openclaw, tableau_de_bord
from opsys.departements import Departement, charger_departements, lire_manifeste
from opsys.outils import Niveau, Outil

RACINE = Path(__file__).resolve().parents[1]
M1 = RACINE / "departments" / "m01-front-office"
PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
    "fort": {"provider": "anthropic", "model": "claude-opus-5"},
}
ENVIRON_EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}
SECRET = "valeur-secrete-de-test-a-ne-jamais-ecrire"
TOUTES_LES_VARIABLES = {
    "OPSYS_SMS_COMPTE_SID": "ACfictif0000000000000000000000000",
    "OPSYS_SMS_JETON": SECRET,
    "OPSYS_SMS_NUMERO": "+15145550100",
    "OPSYS_SMS_URL_PUBLIQUE": "https://exemple-fictif.test/webhooks/sms",
    "OPSYS_SMS_POLITIQUES_VALIDEES": "validation-ecrite-fictive-2026-10-01",
}


@pytest.fixture(scope="module")
def m1() -> Departement:
    return lire_manifeste(M1)


@pytest.fixture
def tous():
    return charger_departements()


def _generer(departements, dossier, **extra):
    environ = {**ENVIRON_EMBEDDINGS, **extra.pop("environ", {})}
    fichiers = openclaw.generer(departements, dossier, PALIERS, environ=environ, **extra)
    return {nom: chemin for nom, chemin in fichiers.items()}


def _json(fichiers, cle):
    return json.loads(fichiers[cle].read_text(encoding="utf-8"))


# -- Le manifeste ----------------------------------------------------------------------------------------------


def test_m1_declare_le_canal_sms_et_garde_son_identite(m1):
    assert m1.id == "m01-front-office"
    assert m1.canaux == ("sms",)
    assert m1.evenements_publie == ("m1.lead_qualifie", "m1.retrait_consentement")  # le lead, puis le STOP (T4.17-c)


def test_un_canal_inconnu_ou_double_dans_un_manifeste_est_refuse(tmp_path):
    dossier = tmp_path / "m01-front-office"
    for cible in ("department.yaml", "SOUL.md"):
        (dossier).mkdir(exist_ok=True)
        (dossier / cible).write_text((M1 / cible).read_text(encoding="utf-8"), encoding="utf-8")
    (dossier / "skills").mkdir()
    for skill in (M1 / "skills").iterdir():
        (dossier / "skills" / skill.name).mkdir()
        (dossier / "skills" / skill.name / "SKILL.md").write_text(
            (skill / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
    texte = (dossier / "department.yaml").read_text(encoding="utf-8")
    (dossier / "department.yaml").write_text(texte.replace("canaux: [sms]", "canaux: [pigeon]"), encoding="utf-8")
    with pytest.raises(ValueError, match="canal inconnu 'pigeon'"):
        lire_manifeste(dossier)
    (dossier / "department.yaml").write_text(texte.replace("canaux: [sms]", "canaux: [sms, sms]"), encoding="utf-8")
    with pytest.raises(ValueError, match="canaux en double"):
        lire_manifeste(dossier)


# -- Chaque clé, confrontée au schéma du fork -------------------------------------------------------------------


def test_channels_sms_ne_porte_que_des_cles_du_schema_de_l_extension(tous, tmp_path):
    fichiers = _generer(tous, tmp_path)
    sms = _json(fichiers, "channels")["sms"]
    schema = ts.lire("extensions/sms/src/config-schema.ts")
    permises = ts.cles_de_l_objet(schema, "export const SmsAccountConfigSchema = z") | {"accounts", "defaultAccount"}
    assert set(sms) <= permises, sorted(set(sms) - permises)
    assert sms["dmPolicy"] in ts.valeurs_apres(ts.lire("src/config/zod-schema.core.ts"), "export const DmPolicySchema")
    # `dmPolicy: "open"` exige `allowFrom` avec "*" (refine du schéma de l'extension).
    assert sms["dmPolicy"] == "open" and "*" in sms["allowFrom"]
    assert "requireChannelOpenAllowFrom" in schema
    # Chaque clé du schéma que l'on écrit y est bien typée comme on l'écrit : booléens et références, jamais un secret.
    assert isinstance(sms["enabled"], bool) and sms["configWrites"] is False
    assert sms["authToken"] == "${OPSYS_SMS_JETON}"
    assert sms["accountSid"] == "${OPSYS_SMS_COMPTE_SID}"
    assert sms["fromNumber"] == "${OPSYS_SMS_NUMERO}"
    assert sms["publicWebhookUrl"] == "${OPSYS_SMS_URL_PUBLIQUE}"


def test_le_canal_est_une_cle_de_la_racine_du_core_et_la_liaison_suit_le_schema(tous, tmp_path):
    fichiers = _generer(tous, tmp_path)
    racine = ts.cles_de_l_objet(ts.lire("src/config/zod-schema.root-shape.ts"), "export const OpenClawSchemaShape =")
    assert {"channels", "bindings", "session", "plugins", "agents", "tools"} <= racine

    agents = ts.lire("src/config/zod-schema.agents.ts")
    cles_liaison = ts.cles_de_l_objet(agents, "const RouteBindingSchema = z")
    cles_match = ts.cles_de_l_objet(agents, "const BindingMatchSchema = z")
    cles_session = ts.cles_de_l_objet(agents, "const BindingSessionSchema = z")
    liaisons = _json(fichiers, "bindings")
    assert len(liaisons) == 1
    (liaison_sms,) = liaisons
    assert set(liaison_sms) <= cles_liaison, sorted(set(liaison_sms) - cles_liaison)
    assert set(liaison_sms["match"]) <= cles_match and set(liaison_sms["session"]) <= cles_session
    assert liaison_sms["type"] == "route" and 'z.literal("route")' in agents
    assert liaison_sms["session"]["dmScope"] in ts.valeurs_apres(agents, "const BindingSessionSchema = z")
    # Le canal entre par l'agent M1, sans compte nommé (le compte par défaut seulement), une session par client.
    assert liaison_sms["agentId"] == "m01-front-office"
    assert liaison_sms["match"] == {"channel": "sms"}
    assert liaison_sms["session"] == {"dmScope": "per-channel-peer"}
    # Et cet agent existe dans le roster que la même génération écrit (sinon le core refuserait la liaison).
    assert "m01-front-office" in _json(fichiers, "agents")["entries"]


def test_session_dmscope_et_send_policy_suivent_le_schema_du_fork(tous, tmp_path):
    fichiers = _generer(tous, tmp_path)
    session = _json(fichiers, "session")
    config = ts.lire("src/config/zod-schema.session-config.ts")
    assert set(session) <= ts.cles_de_l_objet(config, "export const SessionSchema = z")
    assert session["dmScope"] == "per-channel-peer"
    assert session["dmScope"] in ts.valeurs_apres(config, "dmScope:")

    regles = ts.lire("src/config/zod-schema.allowdeny.ts")
    politique = session["sendPolicy"]
    assert set(politique) <= ts.cles_de_l_objet(regles, "return z")
    assert politique["default"] in ts.valeurs_apres(regles, "const AllowDenyActionSchema")
    cles_regle = ts.cles_de_l_objet(regles, "rules: z")
    cles_match = ts.cles_de_l_objet(regles, "match: z")
    for regle in politique["rules"]:
        assert set(regle) <= cles_regle
        assert regle["action"] in ts.valeurs_apres(regles, "const AllowDenyActionSchema")
        assert set(regle["match"]) <= cles_match
    # Aucune réponse automatique sur le canal SMS, même si la lecture du canal échoue (deuxième règle : la clé).
    assert politique["rules"] == [
        {"action": "deny", "match": {"channel": "sms"}},
        {"action": "deny", "match": {"rawKeyPrefix": "agent:m01-front-office:sms:"}},
    ]


def test_l_extension_du_canal_est_une_entree_de_plugin_du_schema(tous, tmp_path):
    fichiers = _generer(tous, tmp_path)
    plugins = _json(fichiers, "plugins")
    entree = plugins["entries"]["sms"]
    cles = ts.cles_de_l_objet(ts.lire("src/config/zod-schema.root-support.ts"), "export const PluginEntrySchema = z")
    assert set(entree) <= cles
    assert entree == {"enabled": False}
    # Le reste du fragment (mémoire native) est inchangé.
    assert "memory-core" in plugins["entries"]


def test_les_outils_de_l_agent_m1_sont_fermes_et_suivent_le_schema(tous, tmp_path):
    fichiers = _generer(tous, tmp_path)
    entrees = _json(fichiers, "agents")["entries"]
    outils = entrees["m01-front-office"]["tools"]
    runtime = ts.lire("src/config/zod-schema.agent-runtime.ts")
    permises = (ts.cles_de_l_objet(runtime, "const CommonToolPolicyFields =")
                | ts.cles_de_l_objet(runtime, "const AgentToolsSchema = z"))
    assert set(outils) <= permises
    assert "alsoAllow" not in outils, "le schéma refuse allow et alsoAllow ensemble"
    # Il n'appelle que les outils de son propre serveur MCP...
    assert outils["allow"] == ["opsys_m1__*"]
    # ... jamais ceux des autres départements, ni l'outil `message` du core (envoi sans approbation).
    assert "message" in outils["deny"] and "group:messaging" in outils["deny"]
    autres = {f"opsys_m{n}__*" for n in range(2, 11)}
    assert autres <= set(outils["deny"])
    assert "opsys_m1__*" not in outils["deny"]
    # Les autres agents gardent la forme d'avant : refus des serveurs voisins, rien d'autre.
    m2 = entrees["m02-revenue-crm"]["tools"]
    assert set(m2) == {"deny"} and "message" not in m2["deny"]


def test_la_cle_de_session_calculee_est_celle_du_core_et_celle_que_m10_accepte():
    cle = canaux.cle_session("m01-front-office", "sms", "+15145550142")
    assert cle == "agent:m01-front-office:sms:direct:+15145550142"
    assert liaison.cle_session_valide(cle) is True
    # Même composition que le core (`per-channel-peer`, correspondant en minuscules) : lue dans sa source.
    source = ts.lire("src/routing/session-key.ts")
    assert 'if (dmScope === "per-channel-peer" && peerId) {' in source
    assert "return `agent:${normalizeAgentId(params.agentId)}:${channel}:direct:${peerId}`;" in source
    assert "peerId = normalizeLowercaseStringOrEmpty(peerId);" in source
    assert canaux.cle_session("m01-front-office", "sms", "  +15145550142 ") == cle
    # Le correspondant et l'agent sont mis en minuscules, comme le core le fait.
    minuscules = canaux.cle_session(" M01-Front-Office ", "sms", "Client-ABC")
    assert minuscules == "agent:m01-front-office:sms:direct:client-abc"


def test_cle_de_session_refuse_ce_qu_un_correspondant_n_est_pas():
    for mauvais in ("", "  ", "a b", "a\nb"):
        with pytest.raises(ValueError, match="correspondant invalide"):
            canaux.cle_session("m01-front-office", "sms", mauvais)
    with pytest.raises(ValueError, match="canal inconnu"):
        canaux.cle_session("m01-front-office", "pigeon", "x")


def test_l_affaire_de_m1_vient_de_la_session_et_l_accueil_n_est_jamais_bloque_par_le_garde_du_core(tous, tmp_path):
    """ADR-0010 : sur un canal client, l'affaire vient de la clé de session liée par un humain. Le garde du core
    refuse un outil de niveau N3 ou plus sans contexte d'affaire ; l'outil d'accueil (N2) doit donc passer pour
    le premier message d'un client, dont la session n'est pas encore liée."""
    fichiers = _generer(tous, tmp_path, contexte_entreprise={"m01-front-office": []},
                        affaire_par_session=["m01-front-office"])
    contexte = _json(fichiers, "contexte")
    assert contexte["agents"]["m01-front-office"] == {"depot": [], "affaire": "session"}
    assert contexte["niveaux"]["m1_recevoir_message_canal"] == "N2"
    assert contexte["niveaux"]["m1_traiter_demande_entrante"] == "N3"
    assert contexte["niveaux"]["m1_emettre_notification"] == "N4"
    assert _json(fichiers, "plugins")["slots"] == {"contextEngine": "opsys"}


# -- Désactivé par défaut, activé par les seules variables ----------------------------------------------------


def test_sans_identifiant_le_canal_et_son_extension_sont_desactives(tous, tmp_path):
    fichiers = _generer(tous, tmp_path)
    assert _json(fichiers, "channels")["sms"]["enabled"] is False
    assert _json(fichiers, "plugins")["entries"]["sms"] == {"enabled": False}


def test_un_identifiant_manquant_vide_ou_blanc_laisse_le_canal_desactive(tous, tmp_path):
    for variable in TOUTES_LES_VARIABLES:
        for valeur in (None, "", "   "):
            environ = dict(TOUTES_LES_VARIABLES)
            if valeur is None:
                del environ[variable]
            else:
                environ[variable] = valeur
            fichiers = _generer(tous, tmp_path / f"{variable}-{valeur!r}", environ=environ)
            assert _json(fichiers, "channels")["sms"]["enabled"] is False, (variable, valeur)


def test_l_attestation_de_validation_des_politiques_est_exigee_pour_activer(tous, tmp_path):
    """Les quatre identifiants Twilio ne suffisent pas : la politique de consentement SMS est une PROPOSITION
    tant que le propriétaire ne l'a pas validée par écrit (T3)."""
    environ = {k: v for k, v in TOUTES_LES_VARIABLES.items() if k != "OPSYS_SMS_POLITIQUES_VALIDEES"}
    fichiers = _generer(tous, tmp_path, environ=environ)
    assert _json(fichiers, "channels")["sms"]["enabled"] is False


def test_toutes_les_variables_fournies_activent_le_canal_et_son_extension(tous, tmp_path):
    fichiers = _generer(tous, tmp_path, environ=TOUTES_LES_VARIABLES)
    assert _json(fichiers, "channels")["sms"]["enabled"] is True
    assert _json(fichiers, "plugins")["entries"]["sms"] == {"enabled": True}
    # Activer le canal ne desserre rien d'autre : ni l'envoi automatique, ni la boîte à outils.
    assert _json(fichiers, "session")["sendPolicy"]["rules"][0] == {"action": "deny", "match": {"channel": "sms"}}
    assert _json(fichiers, "agents")["entries"]["m01-front-office"]["tools"]["allow"] == ["opsys_m1__*"]


def test_aucun_fichier_genere_ne_contient_un_secret_seulement_des_references(tous, tmp_path):
    _generer(tous, tmp_path, environ=TOUTES_LES_VARIABLES)
    fichiers_ecrits = [f for f in (tmp_path / "opsys").rglob("*") if f.is_file()]
    assert fichiers_ecrits
    for fichier in fichiers_ecrits:
        contenu = fichier.read_text(encoding="utf-8")
        for valeur in TOUTES_LES_VARIABLES.values():
            assert valeur not in contenu, f"{fichier.name} contient une valeur d'identifiant"
    channels = (tmp_path / "opsys" / "channels.json").read_text(encoding="utf-8")
    for variable in list(TOUTES_LES_VARIABLES)[:4]:
        assert "${" + variable + "}" in channels
    # La référence de validation n'est qu'une condition d'activation : elle n'entre pas dans la configuration.
    assert "POLITIQUES_VALIDEES" not in channels


def test_sans_departement_a_canaux_les_fragments_sont_vides_et_les_agents_inchanges(departements_demo, tmp_path):
    fichiers = _generer(departements_demo, tmp_path)
    assert _json(fichiers, "channels") == {}
    assert _json(fichiers, "bindings") == []
    assert _json(fichiers, "session") == {}
    assert _json(fichiers, "plugins")["entries"].keys() == {"memory-core"}
    assert _json(fichiers, "agents")["entries"]["m09-demo"]["tools"] == {"deny": []}


def test_l_etat_des_canaux_dit_les_variables_a_fournir(tous):
    etat = canaux.configuration(tous, {}).etat
    assert etat == [{
        "departement": "m01-front-office", "canal": "sms", "actif": False,
        "variables_manquantes": list(canaux.CANAL_SMS.variables), "includes_manquants": [],
    }]
    assert canaux.lignes_d_etat(etat) == [
        "canal m01-front-office / sms : INACTIF, variables à fournir : OPSYS_SMS_COMPTE_SID, OPSYS_SMS_JETON, "
        "OPSYS_SMS_NUMERO, OPSYS_SMS_URL_PUBLIQUE, OPSYS_SMS_POLITIQUES_VALIDEES"
    ]
    actif = canaux.configuration(tous, TOUTES_LES_VARIABLES).etat
    assert canaux.lignes_d_etat(actif) == ["canal m01-front-office / sms : ACTIF"]


# -- Squelette et installations existantes ----------------------------------------------------------------------


def test_le_squelette_inclut_les_trois_fragments_de_canal(tmp_path):
    contenu = json.loads(openclaw.racine_si_absente(tmp_path).read_text(encoding="utf-8"))
    assert contenu["channels"] == {"$include": ["./opsys/channels.json"]}
    assert contenu["session"] == {"$include": ["./opsys/session.json"]}
    # `bindings` est une liste : l'inclusion d'un seul fichier rend la liste elle-même.
    assert contenu["bindings"] == {"$include": "./opsys/bindings.json"}
    assert openclaw.includes_manquants(tmp_path) == []


def test_une_installation_anterieure_est_signalee_sans_etre_reecrite(tmp_path):
    racine = tmp_path / "openclaw.json"
    racine.write_text(
        '{ // JSON5 de l\'utilisateur\n gateway: { port: 18789 },\n'
        ' models: {"$include": ["./opsys/models.json"]},\n agents: {"$include": ["./opsys/agents.json"]},\n'
        ' mcp: {"$include": ["./opsys/mcp.json"]}, tools: {"$include": ["./opsys/tools.json"]},\n'
        ' memory: {"$include": ["./opsys/memory.json"]}, plugins: {"$include": ["./opsys/plugins.json"]} }\n',
        encoding="utf-8")
    avant = racine.read_text(encoding="utf-8")
    assert openclaw.racine_si_absente(tmp_path) is None
    assert racine.read_text(encoding="utf-8") == avant
    assert openclaw.includes_manquants(tmp_path) == ["channels", "bindings", "session"]
    assert openclaw.includes_manquants(tmp_path / "vide") == sorted(openclaw.FICHIER_RACINE_MODELE)


def test_un_openclaw_json_sans_tous_les_includes_de_canal_garde_le_canal_inactif_meme_avec_toutes_les_variables(
    tous, tmp_path
):
    """Un canal dont `session.sendPolicy` ne serait pas lu par le core répondrait aux clients sans approbation :
    tant que `openclaw.json` n'inclut pas `channels`, `bindings` et `session`, le canal reste éteint."""
    dossier = tmp_path / "oc"
    dossier.mkdir()
    (dossier / "openclaw.json").write_text(
        '{"channels": {"$include": ["./opsys/channels.json"]}, "bindings": {"$include": "./opsys/bindings.json"}}\n',
        encoding="utf-8")
    fichiers = _generer(tous, dossier, environ=TOUTES_LES_VARIABLES)
    assert _json(fichiers, "channels")["sms"]["enabled"] is False
    assert _json(fichiers, "plugins")["entries"]["sms"] == {"enabled": False}

    etat = canaux.configuration(tous, TOUTES_LES_VARIABLES, ["session"]).etat
    assert etat[0]["actif"] is False and etat[0]["variables_manquantes"] == []
    assert canaux.lignes_d_etat(etat) == ["canal m01-front-office / sms : INACTIF, openclaw.json n'inclut pas session"]

    # Une fois le squelette complet, la même génération l'active ; sans openclaw.json (première installation :
    # `racine_si_absente` l'écrit ensuite avec tous les includes), rien ne retient le canal.
    (dossier / "openclaw.json").write_text(json.dumps(openclaw.FICHIER_RACINE_MODELE), encoding="utf-8")
    assert _json(_generer(tous, dossier, environ=TOUTES_LES_VARIABLES), "channels")["sms"]["enabled"] is True
    neuf = _generer(tous, tmp_path / "neuf", environ=TOUTES_LES_VARIABLES)
    assert _json(neuf, "channels")["sms"]["enabled"] is True


def test_l_etat_dit_a_la_fois_les_variables_et_les_includes_qui_manquent(tous):
    etat = canaux.configuration(tous, {}, ["channels", "session"]).etat
    ligne = canaux.lignes_d_etat(etat)[0]
    assert "variables à fournir : OPSYS_SMS_COMPTE_SID" in ligne
    assert ligne.endswith("openclaw.json n'inclut pas channels, session")


# -- Déclarations incohérentes : rien n'est écrit -------------------------------------------------------------------


def _outil(nom: str, niveau: Niveau | None) -> Outil:
    return Outil(nom, "Outil de test.", {"type": "object", "properties": {}}, lambda: {}, niveau=niveau)


class _M1SansOutil(Departement):
    def charger_outils(self):
        return (_outil("m1_autre", None),)


class _M1AccueilN3(Departement):
    def charger_outils(self):
        return (_outil("m1_recevoir_message_canal", Niveau.N3),)


def _comme(classe, dep: Departement, **surcharges):
    champs = {f.name: getattr(dep, f.name) for f in dataclasses.fields(dep)}
    return classe(**{**champs, **surcharges})


def test_verifier_declarations_est_vide_pour_le_vrai_m1(tous):
    assert canaux.verifier_declarations(tous) == []


def test_l_outil_d_accueil_absent_ou_de_niveau_n3_est_signale(m1):
    assert canaux.verifier_declarations({m1.id: _comme(_M1SansOutil, m1)}) == [
        "m01-front-office : le canal sms exige l'outil d'accueil m1_recevoir_message_canal, absent du département"
    ]
    (probleme,) = canaux.verifier_declarations({m1.id: _comme(_M1AccueilN3, m1)})
    assert "de niveau N3" in probleme and "N2 au plus" in probleme


def test_un_canal_inconnu_un_canal_double_et_le_mode_autonome_sont_signales(m1, tous):
    inconnu = dataclasses.replace(m1, canaux=("pigeon",))
    assert any("canal inconnu 'pigeon'" in p for p in canaux.verifier_declarations({m1.id: inconnu}))

    autre = dataclasses.replace(tous["m02-revenue-crm"], canaux=("sms",))
    problemes = canaux.verifier_declarations({m1.id: m1, autre.id: autre})
    assert any("déclaré par plusieurs départements" in p for p in problemes)
    with pytest.raises(ValueError, match="un canal entre par un seul agent"):
        canaux.configuration({m1.id: m1, autre.id: autre}, {})

    autonome = dataclasses.replace(m1, mode="autonome")
    (probleme,) = canaux.verifier_declarations({m1.id: autonome})
    assert "sans approbation humaine" in probleme


def test_generer_refuse_avant_d_ecrire_quand_la_declaration_est_incoherente(m1, tmp_path):
    autonome = dataclasses.replace(m1, mode="autonome")
    with pytest.raises(ValueError, match="canaux du public invalides, rien n'est écrit"):
        openclaw.generer({m1.id: autonome}, tmp_path / "oc", PALIERS, environ=ENVIRON_EMBEDDINGS)
    assert not (tmp_path / "oc" / "opsys").exists()


def test_le_mode_autonome_est_refuse_a_un_departement_a_canaux(m1, tous, opsys_home, session):
    assert canaux.mode_refuse(m1, "autonome") is not None
    assert canaux.mode_refuse(m1, "supervise") is None and canaux.mode_refuse(m1, "ombre") is None
    assert canaux.mode_refuse(tous["m02-revenue-crm"], "autonome") is None
    with session() as cnx, pytest.raises(ValueError, match="sans approbation humaine"):
        tableau_de_bord.changer_mode(cnx, tous, "m01-front-office", "autonome", "nathan")
    with session() as cnx:
        assert tableau_de_bord.changer_mode(cnx, tous, "m01-front-office", "supervise", "nathan")["mode"] == "supervise"


# -- La ligne de commande -----------------------------------------------------------------------------------------


def test_cli_verifier_dit_ce_qui_manque_sans_echouer(monkeypatch, capsys, opsys_home):
    for variable in TOUTES_LES_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    assert cli.main(["verifier"]) == 0
    sortie = capsys.readouterr().out
    assert "canal m01-front-office / sms : INACTIF, variables à fournir : OPSYS_SMS_COMPTE_SID" in sortie
    assert "OPSYS_SMS_POLITIQUES_VALIDEES" in sortie
    for variable, valeur in TOUTES_LES_VARIABLES.items():
        monkeypatch.setenv(variable, valeur)
    assert cli.main(["verifier"]) == 0
    sortie = capsys.readouterr().out
    assert "canal m01-front-office / sms : ACTIF" in sortie
    assert SECRET not in sortie


def test_cli_verifier_config_dir_detecte_un_ecart_avec_l_environnement(monkeypatch, capsys, opsys_home, tmp_path):
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", ENVIRON_EMBEDDINGS["OPSYS_EMBEDDINGS_URL"])
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", "bge-m3")
    for variable in TOUTES_LES_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    dossier = tmp_path / "oc"
    _generer(charger_departements(), dossier)
    openclaw.racine_si_absente(dossier)
    assert cli.main(["verifier", "--config-dir", str(dossier)]) == 0

    # Les identifiants arrivent dans l'environnement sans que la configuration ait été régénérée.
    for variable, valeur in TOUTES_LES_VARIABLES.items():
        monkeypatch.setenv(variable, valeur)
    capsys.readouterr()
    assert cli.main(["verifier", "--config-dir", str(dossier)]) == 1
    erreur = capsys.readouterr().err
    assert "écrit inactif mais l'environnement le rend actif" in erreur
    assert "opsys openclaw configurer" in erreur

    # Régénérée, elle suit.
    _generer(charger_departements(), dossier, environ=TOUTES_LES_VARIABLES)
    assert cli.main(["verifier", "--config-dir", str(dossier)]) == 0


def test_cli_verifier_config_dir_signale_un_fragment_absent_et_un_openclaw_json_sans_include(
    monkeypatch, capsys, opsys_home, tmp_path
):
    for variable in TOUTES_LES_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    dossier = tmp_path / "oc"
    dossier.mkdir()
    assert cli.main(["verifier", "--config-dir", str(dossier)]) == 1
    assert "channels.json" in capsys.readouterr().err

    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", ENVIRON_EMBEDDINGS["OPSYS_EMBEDDINGS_URL"])
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", "bge-m3")
    _generer(charger_departements(), dossier)
    (dossier / "openclaw.json").write_text('{"gateway": {"port": 18789}}\n', encoding="utf-8")
    assert cli.main(["verifier", "--config-dir", str(dossier)]) == 1
    assert "n'inclut pas channels, bindings, session" in capsys.readouterr().err


def test_cli_configurer_avertit_et_garde_le_canal_inactif_quand_openclaw_json_est_anterieur(
    monkeypatch, capsys, opsys_home, tmp_path
):
    for variable, valeur in TOUTES_LES_VARIABLES.items():
        monkeypatch.setenv(variable, valeur)
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", ENVIRON_EMBEDDINGS["OPSYS_EMBEDDINGS_URL"])
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", "bge-m3")
    dossier = tmp_path / "oc"
    dossier.mkdir()
    (dossier / "openclaw.json").write_text('{"gateway": {"port": 18789}}\n', encoding="utf-8")
    monkeypatch.setattr(cli.modeles, "charger_paliers", lambda *a, **k: PALIERS)

    assert cli.main(["openclaw", "configurer", "--config-dir", str(dossier)]) == 0
    sortie = capsys.readouterr()
    attendu = "canal m01-front-office / sms : INACTIF, openclaw.json n'inclut pas channels, bindings, session"
    assert attendu in sortie.out
    assert "ATTENTION : openclaw.json n'inclut pas channels, bindings, session" in sortie.err
    assert json.loads((dossier / "opsys" / "channels.json").read_text(encoding="utf-8"))["sms"]["enabled"] is False
    assert (dossier / "openclaw.json").read_text(encoding="utf-8") == '{"gateway": {"port": 18789}}\n'
    assert SECRET not in sortie.out + sortie.err


def test_cli_mode_refuse_autonome_a_m1(capsys, session):
    assert cli.main(["mode", "m01-front-office", "autonome", "--par", "nathan"]) == 1
    assert "sans approbation humaine" in capsys.readouterr().err
    assert cli.main(["mode", "m02-revenue-crm", "autonome", "--par", "nathan"]) == 0
