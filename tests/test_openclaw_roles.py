"""Outils permis par rôle nommé de jeton d'appareil (T1.4-c2, portée par outil T1.4-j) :
`opsys.openclaw.roles_outils`, `opsys.openclaw.ecrire_appareils`, `opsys.departements.verifier_portees`.
Contrat : `docs/architecture/IDEMPOTENCE.md` §7 bis ; table et règle : `docs/architecture/ROLES.md`.

Ces tests portent sur des départements fictifs (fixtures) ; la table des départements réels est
épinglée dans `tests/test_portees_appareil.py`."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from agents_base_qa import provisionner_base_qa

from opsys import appareils, cli, identite, modeles, openclaw
from opsys.departements import Budget, Departement, charger_departements, verifier_portees
from opsys.outils import Outil

FICTIF = True  # tout identifiant d'appareil ci-dessous est fictif (AGENTS.md)

# Mêmes valeurs que tests/test_openclaw_passerelle.py (dupliquées plutôt qu'importées entre
# modules de test, pour ne dépendre d'aucun mode d'import particulier de pytest).
PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}
ENVIRON_EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1",
                      "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}
_VIDE = {"type": "object", "properties": {}, "additionalProperties": False}


def _departement(code: str, module_outils: str) -> Departement:
    """Département minimal construit directement (pas de YAML) : seuls les champs lus par
    `roles_outils`/`charger_outils` comptent ici."""
    return Departement(
        id=f"m{int(code[1:]):02d}-demo-{code.lower()}", code=code, nom=f"{code} démo",
        mission="test", module_outils=module_outils, mode="ombre", dependances=(),
        modeles={"defaut": "standard"}, skills=(), planifications=(), budget=Budget(1, 1),
        memoire_lecture=(), memoire_ecriture=(), kpis=(), racine=Path("."),
    )


def _departements_demo_roles() -> dict[str, Departement]:
    deps = [
        _departement("M2", "demo_outils_m2"),
        _departement("M3", "demo_outils_m3"),
        _departement("M4", "demo_outils_m4"),
        _departement("M6", "demo_outils_m6"),
    ]
    return {d.id: d for d in deps}


def _racine_avec_outils(racine_demo: Path, tmp_path: Path, module_outils: str) -> Path:
    """Copie des départements de démonstration dont le manifeste M9 charge `module_outils`."""
    cible = tmp_path / "departements"
    shutil.copytree(racine_demo, cible)
    manifeste = cible / "m09-demo" / "department.yaml"
    donnees = yaml.safe_load(manifeste.read_text(encoding="utf-8"))
    donnees["outils"] = module_outils
    manifeste.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    return cible


# -- La table rôle -> outils : fermée par défaut ------------------------------------------------


def test_roles_outils_n_accorde_que_ce_qui_est_declare():
    roles = openclaw.roles_outils(_departements_demo_roles())

    # Pas d'entrée nathan_owner ni client : un jeton d'appareil ne peut jamais porter ces rôles (le
    # mobile a un type Profil fermé à admin/employee/seller/client, opsys.appareils.ROLES_APPAREIL ;
    # le client passe par un lien tokenisé, R12 §6).
    assert set(roles) == appareils.ROLES_APPAREIL == {"employee", "seller", "admin"}
    assert roles["seller"] == ("m2_lire_leads", "m3_lire_devis")
    assert roles["employee"] == ("m4_pointer_entree", "m6_soumettre_materiaux")
    assert roles["admin"] == (
        "m2_lire_leads", "m3_lire_devis", "m4_pointer_entree", "m6_approuver_bon_commande",
        "m6_soumettre_materiaux",
    )
    # Un outil déclaré `admin` seulement n'est ni chez l'employé ni chez le vendeur.
    assert "m6_approuver_bon_commande" not in roles["employee"]
    assert "m6_approuver_bon_commande" not in roles["seller"]


def test_un_outil_sans_declaration_est_ferme_pour_tous_les_roles_admin_compris():
    """Fail-closed : `m4_lire_outbox_gps` (départements M4, lecture) et `m2_exporter_tous_les_leads`
    (M2) sont dans le département d'un rôle, mais aucune déclaration ne les cite : aucun appareil ne
    peut les appeler. Avant T1.4-j, `employee` recevait tout M4 hors T3, et `admin` tout hors T3."""
    roles = openclaw.roles_outils(_departements_demo_roles())
    for role, outils in roles.items():
        assert "m4_lire_outbox_gps" not in outils, role
        assert "m2_exporter_tous_les_leads" not in outils, role


def test_t3_jamais_projete_dans_aucun_role():
    roles = openclaw.roles_outils(_departements_demo_roles())
    # T3 (m4_payer_sous_traitant) exclu de tous les rôles, y compris admin (ADR-0009 §5 : réservé à
    # nathan_owner, qui n'a pas d'entrée ici puisqu'aucun appareil ne peut porter ce rôle).
    for role, outils in roles.items():
        assert "m4_payer_sous_traitant" not in outils, role


def test_roles_outils_ignore_t3_n5_et_roles_inconnus_meme_declares():
    """Défense en profondeur : même si une déclaration invalide existe (`opsys-metier verifier` la refuse),
    la projection ne l'accorde jamais — ni T3, ni N5 explicite, ni un rôle hors `ROLES_APPAREIL`."""
    roles = openclaw.roles_outils({"m09": _departement("M9", "demo_outils_portee_invalide")})

    assert set(roles) == {"admin", "employee", "seller"}  # ni `client`, ni `nathan_owner`, ni `superviseur`
    assert roles["admin"] == ()  # m9_payer_declare (T3) et m9_n5_declare (N5) écartés
    assert roles["seller"] == ()  # m9_payer_declare écarté
    assert roles["employee"] == ("m9_role_inconnu", "m9_valide")  # seul le rôle connu est retenu


def test_roles_outils_sans_declaration_donne_des_portees_vides(departements_demo):
    """Fixture par défaut (M9 seul, aucune déclaration) : rien n'est appelable par un appareil, pas
    même les outils de lecture T0 (`m9_additionner`) ni pour admin."""
    roles = openclaw.roles_outils(departements_demo)
    assert roles == {"admin": (), "employee": (), "seller": ()}


# -- La forme de la déclaration -----------------------------------------------------------------


def test_un_outil_est_ferme_par_defaut():
    assert Outil("m9_exemple", "Sans déclaration.", _VIDE, lambda: {}).roles_appareil == frozenset()


@pytest.mark.parametrize("invalide", ["employee", ["employee"], {"employee"}, frozenset({""}), frozenset({1})])
def test_un_outil_refuse_une_declaration_de_mauvaise_forme(invalide):
    """Une chaîne nue serait itérée caractère par caractère ; on exige un frozenset de noms."""
    with pytest.raises(ValueError, match="roles_appareil"):
        Outil("m9_exemple", "Déclaration mal formée.", _VIDE, lambda: {}, roles_appareil=invalide)


# -- `opsys-metier verifier` : rôle inconnu ou outil T3 ------------------------------------------------


def test_verifier_portees_ne_signale_rien_pour_des_declarations_valides():
    assert verifier_portees(_departements_demo_roles()) == []
    assert verifier_portees({"m09": _departement("M9", "demo_outils_portee_valide")}) == []


def test_verifier_portees_signale_role_inconnu_role_non_appareil_et_t3():
    problemes = verifier_portees({"m09": _departement("M9", "demo_outils_portee_invalide")})

    texte = "\n".join(problemes)
    assert len(problemes) == 5, texte
    # Outil T3 et outil N5 : aucun rôle d'appareil ne peut les appeler.
    assert any("m9_payer_declare est T3/N5" in p for p in problemes), texte
    assert any("m9_n5_declare est T3/N5" in p for p in problemes), texte
    # Rôle inconnu, rôle OPSYS qui n'est pas un rôle d'appareil (client, nathan_owner).
    assert any("m9_role_inconnu" in p and "'superviseur'" in p and "rôle inconnu" in p for p in problemes), texte
    assert any("m9_role_client" in p and "'client'" in p and "pas un rôle d'appareil" in p for p in problemes), texte
    assert any("m9_role_proprietaire" in p and "'nathan_owner'" in p and "pas un rôle d'appareil" in p
               for p in problemes), texte
    # Le témoin valide n'est jamais cité.
    assert not any("m9_valide" in p for p in problemes), texte


def test_cli_verifier_echoue_sur_une_declaration_invalide(racine_demo, tmp_path, monkeypatch, capsys):
    cible = _racine_avec_outils(racine_demo, tmp_path, "demo_outils_portee_invalide")
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(cible))

    assert cli.main(["verifier"]) == 1

    erreur = capsys.readouterr().err
    assert "portée d'appareil invalide" in erreur
    assert "m9_payer_declare est T3/N5" in erreur
    assert "'superviseur'" in erreur


def test_cli_verifier_accepte_des_declarations_valides(racine_demo, tmp_path, monkeypatch, capsys):
    cible = _racine_avec_outils(racine_demo, tmp_path, "demo_outils_portee_valide")
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(cible))

    assert cli.main(["verifier"]) == 0

    sortie = capsys.readouterr().out
    assert "portées d'appareil valides (3 outils déclarés" in sortie


# -- Le fragment roles.json généré --------------------------------------------------------------


def test_roles_ecrit_par_generer(departements_demo, tmp_path, session):
    provisionner_base_qa(session, departements_demo)
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, fuseau="America/Toronto",
                                 environ=ENVIRON_EMBEDDINGS, cnx_factory=session)
    fragment = json.loads(fichiers["roles"].read_text(encoding="utf-8"))
    assert fragment["roles"] == {role: list(outils) for role, outils in
                                 openclaw.roles_outils(departements_demo).items()}
    assert fragment["serveurs"] == openclaw.serveurs_outils(departements_demo)
    # Pas de $include vers roles.json dans le squelette openclaw.json (lu directement par le core).
    racine = openclaw.racine_si_absente(tmp_path / "autre")
    assert "roles" not in json.loads(racine.read_text(encoding="utf-8"))


def test_generer_ecrit_la_table_declaree_dans_roles_json(racine_demo, tmp_path, session):
    deps = charger_departements(_racine_avec_outils(racine_demo, tmp_path / "src", "demo_outils_portee_valide"))
    provisionner_base_qa(session, deps)
    fichiers = openclaw.generer(deps, tmp_path / "oc", PALIERS, environ=ENVIRON_EMBEDDINGS, cnx_factory=session)

    fragment = json.loads(fichiers["roles"].read_text(encoding="utf-8"))
    assert fragment == {
        "roles": {
            "admin": ["m9_approuver", "m9_lire_client", "m9_pointer_terrain"],
            "employee": ["m9_pointer_terrain"],
            "seller": ["m9_lire_client"],
        },
        # T1.4-c6 : le serveur MCP qui porte chaque outil d'un rôle (clé de `mcp.servers`).
        "serveurs": {
            "m9_approuver": "opsys_m9",
            "m9_lire_client": "opsys_m9",
            "m9_pointer_terrain": "opsys_m9",
        },
    }
    # L'outil sans déclaration et l'outil T3 n'apparaissent dans aucun rôle.
    assert "m9_interne" not in json.dumps(fragment)
    assert "m9_payer" not in json.dumps(fragment)


def test_generer_refuse_une_portee_invalide_et_n_ecrit_rien(racine_demo, tmp_path):
    deps = charger_departements(_racine_avec_outils(racine_demo, tmp_path / "src", "demo_outils_portee_invalide"))
    sortie = tmp_path / "oc"

    with pytest.raises(ValueError, match="portée d'appareil invalide"):
        openclaw.generer(deps, sortie, PALIERS, environ=ENVIRON_EMBEDDINGS)

    assert not (sortie / "opsys").exists()


def test_cli_openclaw_configurer_ecrit_roles_json(racine_demo, tmp_path, monkeypatch, capsys, session):
    """`opsys-metier openclaw configurer` (la commande réelle) produit le fragment lu par le core."""
    cible = _racine_avec_outils(racine_demo, tmp_path / "src", "demo_outils_portee_valide")
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(cible))
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", ENVIRON_EMBEDDINGS["OPSYS_EMBEDDINGS_URL"])
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", ENVIRON_EMBEDDINGS["OPSYS_EMBEDDINGS_MODELE"])
    modeles.enregistrer_paliers(PALIERS)
    config = tmp_path / "oc"

    provisionner_base_qa(session, charger_departements(cible))
    assert cli.main(["openclaw", "configurer", "--config-dir", str(config)]) == 0

    capsys.readouterr()
    fragment = json.loads((config / "opsys" / "roles.json").read_text(encoding="utf-8"))
    assert fragment["roles"]["employee"] == ["m9_pointer_terrain"]
    assert set(fragment["roles"]) == appareils.ROLES_APPAREIL


def test_cli_openclaw_configurer_refuse_une_portee_invalide(racine_demo, tmp_path, monkeypatch, capsys, session):
    cible = _racine_avec_outils(racine_demo, tmp_path / "src", "demo_outils_portee_invalide")
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(cible))
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", ENVIRON_EMBEDDINGS["OPSYS_EMBEDDINGS_URL"])
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", ENVIRON_EMBEDDINGS["OPSYS_EMBEDDINGS_MODELE"])
    modeles.enregistrer_paliers(PALIERS)
    config = tmp_path / "oc"

    provisionner_base_qa(session, charger_departements(cible))
    assert cli.main(["openclaw", "configurer", "--config-dir", str(config)]) == 2
    assert "portée d'appareil invalide" in capsys.readouterr().err

    assert not (config / "opsys").exists()


# -- Le serveur qui porte chaque outil d'appareil (T1.4-c6) -------------------------------------


def test_serveurs_outils_donne_le_serveur_du_departement_de_chaque_outil_d_un_role():
    serveurs = openclaw.serveurs_outils(_departements_demo_roles())

    assert serveurs == {
        "m2_lire_leads": "opsys_m2",
        "m3_lire_devis": "opsys_m3",
        "m4_pointer_entree": "opsys_m4",
        "m6_approuver_bon_commande": "opsys_m6",
        "m6_soumettre_materiaux": "opsys_m6",
    }


def test_serveurs_outils_couvre_exactement_les_outils_des_roles():
    """Ni un outil fermé, ni un outil T3, ni un outil de plus : le core ne sait appeler pour un
    appareil que ce que `roles_outils` lui permet."""
    deps = _departements_demo_roles()
    roles = openclaw.roles_outils(deps)

    serveurs = openclaw.serveurs_outils(deps)

    assert set(serveurs) == {nom for noms in roles.values() for nom in noms}
    for ferme in ("m4_lire_outbox_gps", "m2_exporter_tous_les_leads", "m4_payer_sous_traitant"):
        assert ferme not in serveurs


def test_serveurs_outils_vide_sans_declaration(departements_demo):
    assert openclaw.serveurs_outils(departements_demo) == {}


def test_le_serveur_d_un_outil_est_une_cle_de_mcp_json(racine_demo, tmp_path, session):
    """Le nom de serveur écrit dans `roles.json` est bien celui de `mcp.servers` : le core ne peut
    pas viser un serveur que sa propre configuration ne déclare pas."""
    deps = charger_departements(_racine_avec_outils(racine_demo, tmp_path / "src", "demo_outils_portee_valide"))
    provisionner_base_qa(session, deps)
    fichiers = openclaw.generer(deps, tmp_path / "oc", PALIERS, environ=ENVIRON_EMBEDDINGS, cnx_factory=session)

    serveurs = json.loads(fichiers["roles"].read_text(encoding="utf-8"))["serveurs"]
    declares = json.loads(fichiers["mcp"].read_text(encoding="utf-8"))["servers"]

    assert serveurs
    assert set(serveurs.values()) <= set(declares)


# -- La table appareils.json (inchangée par T1.4-j) ---------------------------------------------


def test_ecrire_appareils_projette_la_table(session, tmp_path):
    with session() as cnx:
        identite.creer_personne(cnx, "jdupont", "J. Dupont", "un-mot-de-passe-solide-123", ["employee"])
        appareils.appairer(cnx, "tel-fictif-roles-1", "jdupont", "employee")
        chemin = openclaw.ecrire_appareils(cnx, tmp_path)

    assert chemin == tmp_path / "opsys" / "appareils.json"
    fragment = json.loads(chemin.read_text(encoding="utf-8"))
    assert fragment == {"appareils": {"tel-fictif-roles-1": {"personne": "jdupont", "role": "employee"}}}


def test_ecrire_appareils_vide_si_aucun_appareil(session, tmp_path):
    with session() as cnx:
        chemin = openclaw.ecrire_appareils(cnx, tmp_path)
    assert json.loads(chemin.read_text(encoding="utf-8")) == {"appareils": {}}


# -- Transport MCP : HTTP seulement sous déclaration explicite de topologie --------------------


@pytest.mark.parametrize("url", [
    "http://mcp.fictif.invalid:9876/mcp",
    "http://127.0.0.1:9876/mcp",
    "http://192.168.50.2:9876/mcp",
], ids=["hostname", "loopback", "rfc1918"])
@pytest.mark.parametrize("existant", [False, True], ids=["neuf", "existant"])
def test_mcp_tls_http_personnalise_sans_declaration_refuse_avant_ecriture(
    departements_demo, tmp_path, url, existant,
):
    """Une URL HTTP seule n'est pas un accord opérateur, même si son hôte paraît local."""
    sortie = tmp_path / "configuration-fictive"
    if existant:
        sortie.mkdir()
        (sortie / "temoin.txt").write_bytes(b"contenu fictif a conserver\n")
    avant = {str(p.relative_to(sortie)): p.read_bytes() for p in sortie.rglob("*") if p.is_file()}
    erreur = None

    try:
        openclaw.generer(departements_demo, sortie, PALIERS, url_mcp=url, environ=ENVIRON_EMBEDDINGS)
    except ValueError as exc:
        erreur = exc

    apres = {str(p.relative_to(sortie)): p.read_bytes() for p in sortie.rglob("*") if p.is_file()}
    assert apres == avant, "une URL HTTP non declaree ne doit creer ni modifier aucun fragment/espace"
    assert sortie.exists() is existant
    assert erreur is not None, "une URL MCP HTTP personnalisee exige un accord explicite"
    assert "HTTP" in str(erreur).upper()


def test_mcp_tls_topologie_docker_declare_origine_http_exacte(departements_demo, tmp_path, session):
    provisionner_base_qa(session, departements_demo)
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, environ=ENVIRON_EMBEDDINGS, cnx_factory=session)
    serveurs = json.loads(fichiers["mcp"].read_text(encoding="utf-8"))["servers"]

    assert serveurs
    for dep in departements_demo.values():
        serveur = serveurs[openclaw.serveur_mcp(dep)]
        assert serveur["url"] == f"http://opsys:8765/mcp/v1/{dep.id}"
        assert serveur.get("transportSecurity") == {"insecureHttpOrigin": "http://opsys:8765"}
        assert serveur["headers"] == {"Authorization": "Bearer ${OPSYS_MCP_JETON}"}


def test_mcp_tls_https_personnalise_fonctionne_sans_accord_http(departements_demo, tmp_path, session):
    base = "https://mcp.fictif.invalid:9443/mcp"
    provisionner_base_qa(session, departements_demo)
    fichiers = openclaw.generer(
        departements_demo, tmp_path, PALIERS, url_mcp=base, environ=ENVIRON_EMBEDDINGS,
    cnx_factory=session, )
    serveurs = json.loads(fichiers["mcp"].read_text(encoding="utf-8"))["servers"]

    assert serveurs
    for dep in departements_demo.values():
        serveur = serveurs[openclaw.serveur_mcp(dep)]
        assert serveur["url"] == f"{base}/v1/{dep.id}"
        assert "insecureHttpOrigin" not in serveur.get("transportSecurity", {})
        assert serveur["headers"] == {"Authorization": "Bearer ${OPSYS_MCP_JETON}"}


@pytest.mark.parametrize(("url", "origine"), [
    ("http://mcp.fictif.invalid:9876/mcp", "http://mcp.fictif.invalid:9876"),
    ("http://127.0.0.1:9876/mcp", "http://127.0.0.1:9876"),
    ("http://192.168.50.2:9876/mcp", "http://192.168.50.2:9876"),
    ("http://[::1]:9876/mcp", "http://[::1]:9876"),
    ("http://mcp.fictif.invalid:80/mcp", "http://mcp.fictif.invalid"),
])
def test_mcp_tls_accord_http_explicite_projette_uniquement_origine_exacte(
    departements_demo, tmp_path, url, origine,
session, ):
    provisionner_base_qa(session, departements_demo)
    fichiers = openclaw.generer(
        departements_demo, tmp_path, PALIERS, url_mcp=url, origine_http_mcp_autorisee=origine,
        environ=ENVIRON_EMBEDDINGS,
    cnx_factory=session, )
    serveurs = json.loads(fichiers["mcp"].read_text(encoding="utf-8"))["servers"]
    assert serveurs
    for dep in departements_demo.values():
        serveur = serveurs[openclaw.serveur_mcp(dep)]
        assert serveur["url"] == f"{url}/v1/{dep.id}"
        assert serveur["transportSecurity"] == {"insecureHttpOrigin": origine}


@pytest.mark.parametrize("origine", [
    "http://autre.fictif.invalid:9876", "http://mcp.fictif.invalid:9877", "https://mcp.fictif.invalid:9876",
    "http://mcp.fictif.invalid:9876/", "http://mcp.fictif.invalid:9876/mcp",
    "http://mcp.fictif.invalid:9876?x=1", "http://mcp.fictif.invalid:9876#x",
    "http://fictif:secret-fictif@mcp.fictif.invalid:9876", "HTTP://mcp.fictif.invalid:9876",
    "http://MCP.FICTIF.INVALID:9876", "http://mcp.fictif.invalid:80", "",
])
def test_mcp_tls_accord_different_ou_non_canonique_refuse_sans_ecrire(
    departements_demo, tmp_path, origine,
):
    sortie = tmp_path / "configuration-fictive"
    sortie.mkdir()
    temoin = sortie / "temoin.txt"
    temoin.write_bytes(b"configuration fictive preservee\n")

    with pytest.raises(ValueError, match="(?i)HTTP"):
        openclaw.generer(
            departements_demo, sortie, PALIERS, url_mcp="http://mcp.fictif.invalid:9876/mcp",
            origine_http_mcp_autorisee=origine, environ=ENVIRON_EMBEDDINGS,
        )

    assert list(sortie.iterdir()) == [temoin]
    assert temoin.read_bytes() == b"configuration fictive preservee\n"


@pytest.mark.parametrize("url", [
    "http://fictif:secret-fictif@mcp.fictif.invalid:9876/mcp",
    "http://mcp.fictif.invalid:9876/mcp?x=1", "http://mcp.fictif.invalid:9876/mcp#x",
    "http://mcp.fictif.invalid:9876/mcp?", "http://mcp.fictif.invalid:9876/mcp#",
    "http://mcp.fictif.invalid:9876\\mcp", " http://mcp.fictif.invalid:9876/mcp",
    "http:///mcp", "http://mcp.fictif.invalid:0/mcp", "http://mcp.fictif.invalid:999999/mcp",
    "http://127.1/mcp", "http://0x7f000001/mcp", "/mcp", "ftp://mcp.fictif.invalid:9876/mcp",
])
def test_mcp_tls_url_invalide_refuse_meme_si_accord_http_fourni(departements_demo, tmp_path, url):
    sortie = tmp_path / "configuration-fictive"
    with pytest.raises(ValueError, match="(?i)HTTP"):
        openclaw.generer(
            departements_demo, sortie, PALIERS, url_mcp=url,
            origine_http_mcp_autorisee="http://mcp.fictif.invalid:9876", environ=ENVIRON_EMBEDDINGS,
        )
    assert not sortie.exists()


def test_mcp_tls_https_ne_recoit_jamais_une_exception_http(departements_demo, tmp_path):
    sortie = tmp_path / "configuration-fictive"
    with pytest.raises(ValueError, match="HTTP"):
        openclaw.generer(
            departements_demo, sortie, PALIERS, url_mcp="https://mcp.fictif.invalid:9876/mcp",
            origine_http_mcp_autorisee="http://mcp.fictif.invalid:9876", environ=ENVIRON_EMBEDDINGS,
        )
    assert not sortie.exists()


def test_mcp_tls_cli_http_sans_accord_refuse_avant_configuration_et_etat(tmp_path, monkeypatch, capsys):
    sortie = tmp_path / "configuration-fictive"
    home = tmp_path / "etat-metier-fictif"
    monkeypatch.setenv("OPSYS_HOME", str(home))

    assert cli.main([
        "openclaw", "configurer", "--config-dir", str(sortie),
        "--url-mcp", "http://127.0.0.1:9876/mcp",
    ]) == 2

    assert "--autoriser-origine-http-mcp" in capsys.readouterr().err
    assert not sortie.exists()
    assert not home.exists()


@pytest.mark.parametrize(("url", "origine"), [
    (None, None),
    ("http://127.0.0.1:9876/mcp", "http://127.0.0.1:9876"),
    ("https://mcp.fictif.invalid:9443/mcp", None),
])
def test_mcp_tls_cli_choix_explicite_ou_defaut_gere_genere_la_bonne_policy(
    tmp_path, monkeypatch, capsys, url, origine,
session, ):
    for nom, valeur in ENVIRON_EMBEDDINGS.items():
        monkeypatch.setenv(nom, valeur)
    modeles.enregistrer_paliers(PALIERS)
    sortie = tmp_path / "configuration-fictive"
    commande = ["openclaw", "configurer", "--config-dir", str(sortie)]
    if url is not None:
        commande += ["--url-mcp", url]
    if origine is not None:
        commande += ["--autoriser-origine-http-mcp", origine]

    provisionner_base_qa(session, charger_departements())
    assert cli.main(commande) == 0
    capsys.readouterr()
    serveurs = json.loads((sortie / "opsys" / "mcp.json").read_text(encoding="utf-8"))["servers"]
    assert serveurs
    for serveur in serveurs.values():
        if url is None:
            assert serveur["transportSecurity"] == {"insecureHttpOrigin": "http://opsys:8765"}
        elif origine is not None:
            assert serveur["url"].startswith(url + "/")
            assert serveur["transportSecurity"] == {"insecureHttpOrigin": origine}
        else:
            assert serveur["url"].startswith(url + "/")
            assert "insecureHttpOrigin" not in serveur.get("transportSecurity", {})
