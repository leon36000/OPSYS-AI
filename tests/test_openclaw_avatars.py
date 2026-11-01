"""Avatars, étape 2 : `openclaw.generer` projette l'identité EFFECTIVE de chaque département dans son agent du core.

Ce que le core lit (`docs/architecture/AVATARS.md`) : `identity.name` de l'entrée d'agent, premier choix de
`resolveAssistantIdentity` (en-tête du chat, `agent.identity.get`), et `description` pour le rôle. Preuves : les dix
départements réels, la surcharge du client (`$OPSYS_HOME/entreprise.yaml`), le refus d'une surcharge invalide avant
toute écriture (jamais de repli sur le nom par défaut), l'idempotence octet pour octet, et le contrat épinglé en
lisant le code TypeScript du core. Si `core/node_modules` est installé, le vrai `resolveAssistantIdentity` du core
relit la configuration générée.

Noms et surcharges : données FICTIVES ; dossier de configuration jetable.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from agents_base_qa import provisionner_base_qa

from opsys import avatars, openclaw, taxonomie
from opsys.departements import charger_departements
from opsys.taxonomie import ProfilInvalide

FICTIF = True

RACINE = Path(__file__).resolve().parents[1]
CORE = RACINE / "core"

PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "fort": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}
ENVIRON = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}

NOMS_PAR_DEFAUT = {
    "m01-front-office": "Léa",
    "m02-revenue-crm": "Victor",
    "m03-estimation": "Mathis",
    "m04-field-ops": "Gabriel",
    "m05-financecore": "Sophie",
    "m06-material-control": "Rosalie",
    "m07-marketing": "Chloé",
    "m08-analytics": "Olivier",
    "m09-strategic-intelligence": "Athéna",
    "m10-memoire": "Mnémo",
}


@pytest.fixture(scope="module")
def departements():
    return charger_departements()


@pytest.fixture
def base(session, departements):
    provisionner_base_qa(session, departements)
    return session


def _generer(departements, dossier, cnx_factory, **options):
    return openclaw.generer(departements, dossier, PALIERS, environ=ENVIRON, cnx_factory=cnx_factory, **options)


def _profil(contenu) -> Path:
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    texte = contenu if isinstance(contenu, str) else yaml.safe_dump(contenu, allow_unicode=True)
    fichier.write_text(texte, encoding="utf-8")
    return fichier


def _entrees(fichiers) -> dict:
    return json.loads(fichiers["agents"].read_text(encoding="utf-8"))["entries"]


def _instantane(dossier: Path) -> dict[str, bytes]:
    """Tout ce que `generer` a écrit, octet pour octet (espaces de travail compris)."""
    return {
        str(chemin.relative_to(dossier)): chemin.read_bytes()
        for chemin in sorted(dossier.rglob("*")) if chemin.is_file()
    }


# -- Les dix départements réels --------------------------------------------------------------------


def test_chaque_agent_de_departement_porte_le_nom_et_le_role_de_son_avatar(departements, base, tmp_path):
    fichiers = _generer(departements, tmp_path / "oc", base)
    entrees = _entrees(fichiers)

    assert set(NOMS_PAR_DEFAUT) <= set(entrees)
    for ident, nom in NOMS_PAR_DEFAUT.items():
        dep = departements[ident]
        agent = entrees[ident]
        # Exactement le nom (pas d'émoji, d'image, de modèle 3D ni de voix inventés) ; le rôle en description.
        assert agent["identity"] == {"name": nom}
        assert agent["description"] == dep.avatar.role
        # Le nom de l'agent dans la liste du core reste celui du département.
        assert agent["name"] == f"{dep.code} · {dep.nom}"
        assert "tts" not in agent
        assert len(nom.encode("utf-16-le")) // 2 <= 50  # ASSISTANT_IDENTITY_LIMITS.name : jamais tronqué
        # IDENTITY.md n'est pas écrit : il appartient à l'espace de travail du core.
        espace = Path(agent["workspace"])
        assert not (espace / "IDENTITY.md").exists()
    assert entrees["m01-front-office"]["identity"]["name"] == "Léa"


def test_la_surcharge_du_client_remplace_le_nom_affiche(departements, base, tmp_path):
    _profil({"avatars": {
        "m01-front-office": {"nom": "Julie", "voix": "voix.julie.chaleureuse"},
        "m05-financecore": {"visage": "visage.sophie.tailleur"},
        # Deux avatars peuvent échanger leurs noms.
        "m02-revenue-crm": {"nom": "Mathis"},
        "m03-estimation": {"nom": "Victor"},
    }})
    entrees = _entrees(_generer(departements, tmp_path / "oc", base))

    attendus = {**NOMS_PAR_DEFAUT, "m01-front-office": "Julie", "m02-revenue-crm": "Mathis",
                "m03-estimation": "Victor"}
    assert {ident: entrees[ident]["identity"]["name"] for ident in NOMS_PAR_DEFAUT} == attendus
    # Le client ne change jamais le rôle ; voix et visage logiques ne sont pas projetés.
    assert entrees["m01-front-office"]["description"] == departements["m01-front-office"].avatar.role
    assert entrees["m05-financecore"]["identity"] == {"name": "Sophie"}


def test_le_profil_explicite_l_emporte_sur_celui_de_l_instance(departements, base, tmp_path):
    _profil({"avatars": {"m01-front-office": {"nom": "Julie"}}})
    autre = tmp_path / "autre-entreprise.yaml"
    autre.write_text(yaml.safe_dump({"avatars": {"m01-front-office": {"nom": "Noémie"}}}, allow_unicode=True),
                     encoding="utf-8")
    entrees = _entrees(_generer(departements, tmp_path / "oc", base, profil_entreprise=autre))
    assert entrees["m01-front-office"]["identity"]["name"] == "Noémie"


# -- Fail-closed : une surcharge invalide n'écrit rien ------------------------------------------------


SURCHARGES_INVALIDES = {
    "nom-avec-chiffre": ({"avatars": {"m01-front-office": {"nom": "Julie2"}}}, "nom 'Julie2' refusé"),
    "nom-trop-long": ({"avatars": {"m01-front-office": {"nom": "A" * 41}}}, "au plus 40"),
    "departement-inconnu": ({"avatars": {"m99-inconnu": {"nom": "Julie"}}}, "département\\(s\\) inconnu"),
    "doublon-de-nom": ({"avatars": {"m01-front-office": {"nom": "Victor"}}}, "partagé par"),
    "doublon-sans-accent": ({"avatars": {"m01-front-office": {"nom": "Athena"}}}, "partagé par"),
    "role-non-personnalisable": ({"avatars": {"m01-front-office": {"role": "Patronne"}}}, "non personnalisable"),
    "entree-vide": ({"avatars": {"m01-front-office": {}}}, "non vide"),
    "voix-fournisseur": ({"avatars": {"m01-front-office": {"voix": "elevenlabs:abc"}}}, "mal formé"),
    "cle-pas-un-objet": ({"avatars": ["m01-front-office"]}, "doit être un objet"),
    "yaml-casse": ("avatars: [\n", "avatars des départements invalides, rien n.est écrit"),
}


@pytest.mark.parametrize("contenu,message", SURCHARGES_INVALIDES.values(), ids=SURCHARGES_INVALIDES.keys())
def test_une_surcharge_invalide_fait_echouer_la_generation_sans_rien_ecrire(
    departements, base, tmp_path, contenu, message
):
    _profil(contenu)
    sortie = tmp_path / "oc"
    with pytest.raises(ProfilInvalide, match=message):
        _generer(departements, sortie, base)
    assert not sortie.exists()


def test_une_surcharge_cassee_ne_retombe_jamais_sur_le_nom_par_defaut(departements, base, tmp_path):
    """Après une génération valide, une surcharge cassée laisse la configuration précédente intacte."""
    sortie = tmp_path / "oc"
    _profil({"avatars": {"m01-front-office": {"nom": "Julie"}}})
    _generer(departements, sortie, base)
    avant = _instantane(sortie)

    _profil({"avatars": {"m01-front-office": {"nom": "Julie <script>"}}})
    with pytest.raises(ProfilInvalide, match="avatars des départements invalides, rien n'est écrit"):
        _generer(departements, sortie, base)
    assert _instantane(sortie) == avant
    assert _entrees({"agents": sortie / "opsys" / "agents.json"})["m01-front-office"]["identity"]["name"] == "Julie"


def test_un_departement_sans_avatar_est_refuse_avant_toute_ecriture(racine_demo, base, tmp_path):
    cible = tmp_path / "departements"
    shutil.copytree(racine_demo, cible)
    manifeste = cible / "m09-demo" / "department.yaml"
    donnees = yaml.safe_load(manifeste.read_text(encoding="utf-8"))
    donnees.pop("avatar")
    manifeste.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    sortie = tmp_path / "oc"
    with pytest.raises(ValueError, match="ne déclare pas de bloc avatar"):
        openclaw.generer(charger_departements(cible), sortie, PALIERS, environ=ENVIRON, cnx_factory=base)
    assert not sortie.exists()


# -- Idempotence ----------------------------------------------------------------------------------------


def test_regenerer_sans_changement_est_identique_octet_pour_octet(departements, base, tmp_path):
    sortie = tmp_path / "oc"
    _profil({"avatars": {"m01-front-office": {"nom": "Julie"}}})
    _generer(departements, sortie, base)
    premier = _instantane(sortie)
    _generer(departements, sortie, base)
    assert _instantane(sortie) == premier


def test_changer_la_surcharge_ne_change_que_ce_qui_depend_de_l_avatar(departements, base, tmp_path):
    sortie = tmp_path / "oc"
    _generer(departements, sortie, base)
    defaut = _instantane(sortie)

    # Voix et visage logiques : rien de projeté, donc rien ne change.
    _profil({"avatars": {"m01-front-office": {"voix": "voix.julie.chaleureuse", "visage": "visage.lea.souriante"}}})
    _generer(departements, sortie, base)
    assert _instantane(sortie) == defaut

    # Le nom : seul `identity.name` de l'agent de M1 change.
    _profil({"avatars": {"m01-front-office": {"nom": "Julie"}}})
    _generer(departements, sortie, base)
    renomme = _instantane(sortie)
    assert {chemin for chemin in defaut if defaut[chemin] != renomme[chemin]} == {"opsys/agents.json"}
    assert set(renomme) == set(defaut)
    avant, apres = (json.loads(contenu["opsys/agents.json"]) for contenu in (defaut, renomme))
    assert apres["entries"]["m01-front-office"]["identity"] == {"name": "Julie"}
    apres["entries"]["m01-front-office"]["identity"]["name"] = "Léa"
    assert apres == avant

    # Retirer la surcharge rend exactement la configuration par défaut.
    _profil({})
    _generer(departements, sortie, base)
    assert _instantane(sortie) == defaut


# -- Contrat avec le core (lu dans le code TypeScript) -----------------------------------------------------


def _source(relatif: str) -> str:
    return (CORE / relatif).read_text(encoding="utf-8")


def test_le_core_lit_identity_name_et_description_tels_que_projetes():
    schema = _source("src/config/zod-schema.core.ts")
    identite = re.search(r"export const IdentitySchema = z\s*\.object\(\{(.*?)\}\)\s*\.strict\(\)", schema, re.S)
    assert identite and "name: z.string().optional()" in identite.group(1)
    assert "identity: IdentitySchema" in _source("src/config/zod-schema.agent-runtime.ts")
    assert "description: z.string().optional()" in _source("src/config/zod-schema.agent-entry-base.ts")
    # Le nom de la configuration passe avant IDENTITY.md et le défaut « Assistant ».
    resolution = _source("src/gateway/assistant-identity.ts")
    assert 'const agentName = normalizeIdentityValue("name", agentIdentity?.name);' in resolution
    assert re.search(r"agentName\s*\?\s*\[agentName, \"agent\"\]\s*:\s*fileName", resolution)
    limite = re.search(r"ASSISTANT_IDENTITY_LIMITS = \{\s*name: (\d+),", resolution)
    assert limite and int(limite.group(1)) >= avatars.NOM_MAX
    # Consommateurs : la méthode lue par l'en-tête du chat et la ligne d'exécution du prompt système.
    assert "resolveAssistantIdentity({ cfg, agentId })" in _source("src/gateway/server-methods/agent-identity.ts")
    assert "resolveAgentIdentity(config, agentId)?.name" in _source("src/agents/system-prompt-params.ts")


def test_le_core_refuse_un_visage_logique_comme_modele_3d_ou_image():
    """Pourquoi `visage` n'est pas projeté : `avatarModelId` doit nommer un modèle du catalogue local."""
    validation = _source("src/config/validation-core.ts")
    assert "identity.avatarModelId must name a model in the local avatar catalogue." in validation
    catalogue = _source("src/shared/assistant-avatar-model-catalog.ts")
    for dep in charger_departements().values():
        assert dep.avatar.visage not in catalogue


def test_le_vrai_resolveur_du_core_lit_le_nom_de_l_avatar(departements, base, tmp_path):
    """Le schéma `AgentsSchema` accepte la configuration générée et `resolveAgentIdentity` (source unique du bloc
    `identity` pour `resolveAssistantIdentity`, le prompt système et les préfixes de réponse) rend le nom effectif.

    `resolveAssistantIdentity` lui-même tire, sous tsx, des dépendances que l'installation locale de `node_modules`
    ne résout pas toujours ; son ordre de priorité est épinglé par lecture ci-dessus, et vérifié sous vitest
    (AVATARS.md, preuves de l'étape 2)."""
    tsx = CORE / "node_modules" / ".bin" / "tsx"
    if not tsx.is_file():
        pytest.skip("core/node_modules absent : contrat vérifié par lecture du code TypeScript seulement")
    _profil({"avatars": {"m01-front-office": {"nom": "Julie"}}})
    fichiers = _generer(departements, tmp_path / "oc", base)
    script = tmp_path / "resoudre-identites.ts"
    script.write_text(
        "import { readFileSync } from 'node:fs';\n"
        f"import {{ AgentsSchema }} from {json.dumps((CORE / 'src/config/zod-schema.agents.ts').as_posix())};\n"
        f"import {{ resolveAgentIdentity }} from {json.dumps((CORE / 'src/agents/identity.ts').as_posix())};\n"
        "const agents = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
        "const parsed = AgentsSchema.safeParse(agents);\n"
        "if (!parsed.success) { process.stderr.write(JSON.stringify(parsed.error.issues)); process.exit(1); }\n"
        "const noms: Record<string, unknown> = {};\n"
        "for (const agentId of Object.keys(agents.entries)) {\n"
        "  noms[agentId] = resolveAgentIdentity({ agents } as never, agentId) ?? null;\n"
        "}\n"
        "process.stdout.write(JSON.stringify(noms));\n",
        encoding="utf-8",
    )
    resultat = subprocess.run(
        [str(tsx), str(script), str(fichiers["agents"])], cwd=CORE, check=False, capture_output=True, text=True,
        timeout=300,
    )
    assert resultat.returncode == 0, resultat.stderr
    identites = json.loads(resultat.stdout)
    attendus = {**NOMS_PAR_DEFAUT, "m01-front-office": "Julie"}
    assert {ident: identites[ident] for ident in attendus} == {ident: {"name": nom} for ident, nom in attendus.items()}
