"""Outils permis par rôle nommé de jeton d'appareil (T1.4-c2) : `opsys.openclaw.roles_outils` et
`opsys.openclaw.ecrire_appareils`. Contrat : `docs/architecture/IDEMPOTENCE.md` §7 bis."""

from __future__ import annotations

import json
from pathlib import Path

from opsys import appareils, identite, openclaw
from opsys.departements import Budget, Departement

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


def test_roles_outils_repartit_par_departement_et_exclut_t3():
    roles = openclaw.roles_outils(_departements_demo_roles())

    # Pas d'entrée nathan_owner : un jeton d'appareil ne peut jamais porter ce rôle (le mobile a un
    # type Profil fermé à admin/employee/seller/client, opsys.appareils.ROLES_APPAREIL).
    assert set(roles) == appareils.ROLES_APPAREIL == {"employee", "seller", "admin"}
    assert roles["seller"] == ("m2_lire_leads", "m3_lire_devis")
    assert roles["employee"] == ("m4_pointer_entree", "m6_soumettre_materiaux")
    # T3 (m4_payer_sous_traitant) exclu de tous les rôles, y compris admin (ADR-0009 §5 : réservé à
    # nathan_owner, qui n'a pas d'entrée ici puisqu'aucun appareil ne peut porter ce rôle).
    assert "m4_payer_sous_traitant" not in roles["employee"]
    assert "m4_payer_sous_traitant" not in roles["admin"]
    assert roles["admin"] == (
        "m2_lire_leads", "m3_lire_devis", "m4_pointer_entree", "m6_soumettre_materiaux",
    )


def test_roles_outils_sans_departement_terrain_ni_commercial(departements_demo):
    """Fixture par défaut (M9 seul) : employee/seller restent vides, admin couvre M9 sauf le T3
    `m9_payer`."""
    roles = openclaw.roles_outils(departements_demo)
    assert roles["employee"] == ()
    assert roles["seller"] == ()
    assert "m9_payer" not in roles["admin"]
    assert "m9_additionner" in roles["admin"]


def test_roles_ecrit_par_generer(departements_demo, tmp_path):
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, fuseau="America/Toronto",
                                 environ=ENVIRON_EMBEDDINGS)
    fragment = json.loads(fichiers["roles"].read_text(encoding="utf-8"))
    assert fragment["roles"] == {role: list(outils) for role, outils in
                                 openclaw.roles_outils(departements_demo).items()}
    # Pas de $include vers roles.json dans le squelette openclaw.json (lu directement par le core).
    racine = openclaw.racine_si_absente(tmp_path / "autre")
    assert "roles" not in json.loads(racine.read_text(encoding="utf-8"))


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
