"""Poste de pilotage des agents : profil activé, révision exportée, réservations et activité inconnue.

Parcours réels : registre SQLite, export par `openclaw.generer`, lecture HTTP de la console. Toutes les
données sont fictives ; aucune attestation de chargement Core ni d'activité n'est fabriquée.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from agents_base_qa import provisionner_base_qa
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from opsys import admission_agents, agents, identite, openclaw, stockage
from opsys.console import agents_etat, application
from opsys.console.securite import Configuration
from opsys.departements import Departement, charger_departements
from opsys.stockage.schema import AGENTS_CONFIGURABLES, AGENTS_GRANTS_CFO, OPSYS_INSTANCE

FICTIF = True
OWNER = "owner.pilotage.fictif"
PASSWORD = "mot-de-passe-pilotage-fictif-123"
SECRET = "secret-pilotage-console-fictif-" + "x" * 32
DEP_A = "m03-estimation"
DEP_B = "m07-marketing"
PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5", "fallbacks": ["rapide"]},
}
EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-fictif:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}
ECRITURE_SQL = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP)\b", re.IGNORECASE)
# Une ligne de profil : toutes ses colonnes viennent du registre des profils. Un COUNT scalaire n'en a aucune.
COLONNES_PROFIL = frozenset(AGENTS_CONFIGURABLES.c.keys())


@dataclass
class Console:
    client: TestClient
    csrf: str
    deps: dict
    dossier: Path
    requetes: list[str]
    lignes: list[tuple[str, ...]]

    def lignes_profil(self) -> int:
        return sum(1 for colonnes in self.lignes if colonnes and set(colonnes) <= COLONNES_PROFIL)


def _connecter(client: TestClient) -> str:
    reponse = client.post("/connexion", data={"identifiant": OWNER, "mot_de_passe": PASSWORD}, follow_redirects=False)
    assert reponse.status_code == 303
    return client.get("/api/session").json()["csrf"]


@pytest.fixture
def console(session, opsys_home, monkeypatch):
    deps = charger_departements()
    dossier = opsys_home / "core-export-fictif"
    dossier.mkdir(parents=True)
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(dossier))
    with session() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", PASSWORD, ["nathan_owner"])
        admission_agents.configurer_plafonds_entreprise(cnx, 100000, 1000000, par=OWNER, revision_attendue=0)
    requetes: list[str] = []
    lignes: list[tuple[str, ...]] = []

    def materialiser(curseur, ligne):
        # Appelée par sqlite3 pour chaque ligne réellement lue (fetchone, fetchmany, fetchall ou itération).
        lignes.append(tuple(colonne[0] for colonne in curseur.description))
        return ligne

    @contextmanager
    def espion():
        with session() as cnx:
            def noter(_conn, curseur, instruction, *_args):
                requetes.append(instruction)
                curseur.row_factory = materialiser

            event.listen(cnx, "before_cursor_execute", noter)
            try:
                yield cnx
            finally:
                event.remove(cnx, "before_cursor_execute", noter)

    app = application.creer_application(Configuration(SECRET), deps, espion)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield Console(client, _connecter(client), deps, dossier, requetes, lignes)


def _spec(c: Console, ident: str, dep: str = DEP_A, responsabilite: str = "Préparer des soumissions fictives.") -> dict:
    return {
        "id": ident,
        "departement": dep,
        "responsabilite": responsabilite,
        "palier_modele": "rapide",
        "outils": [c.deps[dep].charger_outils()[0].nom],
        "budget_jour": 1000,
        "budget_mois": 10000,
        "limite_tours": 8,
        "limite_reessais": 1,
        "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }


def _creer(c: Console, ident: str, dep: str = DEP_A, *, actif: bool = True, **extra) -> dict:
    entetes = {"x-csrf-token": c.csrf}
    reponse = c.client.post(
        "/api/agents", json={"spec": _spec(c, ident, dep, **extra), "mutation_id": f"creer-{ident}"}, headers=entetes
    )
    assert reponse.status_code == 200, reponse.text
    profil = reponse.json()["agent"]
    if actif:
        profil = _activation(c, profil, True)
    return profil


def _activation(c: Console, profil: dict, actif: bool) -> dict:
    commande = {"actif": actif, "mutation_id": f"actif-{profil['id']}-{profil['revision']}",
                "revision_attendue": profil["revision"]}
    reponse = c.client.post(f"/api/agents/{profil['id']}/activation", json=commande, headers={"x-csrf-token": c.csrf})
    assert reponse.status_code == 200, reponse.text
    return reponse.json()["agent"]


def _exporter(c: Console, session) -> None:
    provisionner_base_qa(session, c.deps, budget_entreprise_jour=100000, budget_entreprise_mois=1000000)
    openclaw.generer(c.deps, c.dossier, PALIERS, environ=EMBEDDINGS, cnx_factory=session)


def _etat(c: Console, ident: str) -> dict:
    reponse = c.client.get(f"/api/agents/{ident}")
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert "etat" in corps, "la réponse agent n'expose pas encore l'état de pilotage"
    return corps["etat"]


def _ecrire_export(c: Console, entrees: dict) -> None:
    (c.dossier / "opsys").mkdir(exist_ok=True)
    (c.dossier / "opsys" / "agents.json").write_text(json.dumps({"entries": entrees}), encoding="utf-8")


def test_revision_sql_apres_export_rend_la_revision_exportee_perimee(console, session):
    profil = _creer(console, "estimateur-fictif")
    etat = _etat(console, profil["id"])
    assert etat["export"]["statut"] == "EXPORT_ABSENT"
    assert etat["chargement_core"]["statut"] == "INCONNU"
    assert etat["activite"]["statut"] == "INCONNUE"

    _exporter(console, session)
    etat = _etat(console, profil["id"])
    assert etat["profil"] == {**etat["profil"], "statut": "ACTIVE", "revision": 2}
    assert etat["export"]["statut"] == "CONCORDANT"
    assert etat["export"]["revision_exportee"] == 2
    assert isinstance(etat["export"]["ecrit_le"], str)
    assert etat["chargement_core"]["statut"] == "INCONNU"

    modifie = console.client.patch(
        f"/api/agents/{profil['id']}", headers={"x-csrf-token": console.csrf},
        json={"spec": _spec(console, profil["id"], responsabilite="Réviser les marges fictives."),
              "mutation_id": "modifier-estimateur-fictif", "revision_attendue": 2},
    )
    assert modifie.status_code == 200
    etat = _etat(console, profil["id"])
    assert etat["profil"]["revision"] == 3
    assert etat["export"]["statut"] == "PERIME"
    assert etat["export"]["revision_exportee"] == 2
    page = console.client.get(f"/agents/{profil['id']}").text
    assert "Révision exportée périmée" in page and "révision exportée 2" in page

    _exporter(console, session)
    assert _etat(console, profil["id"])["export"]["revision_exportee"] == 3


@pytest.mark.parametrize(
    "contenu",
    [
        "{",
        json.dumps({"entries": {"opsys-agent-x": {"opsysRuntimeAdmission": {
            "profileId": "estimateur-fictif", "profileRevision": "2"}}}}),
        json.dumps({"entries": {"opsys-agent-x": {"opsysRuntimeAdmission": {
            "profileId": "estimateur-fictif", "profileRevision": True}}}}),
        json.dumps({"entries": {
            "a": {"opsysRuntimeAdmission": {"profileId": "estimateur-fictif", "profileRevision": 2}},
            "b": {"opsysRuntimeAdmission": {"profileId": "estimateur-fictif", "profileRevision": 2}},
        }}),
        json.dumps({"entries": []}),
    ],
    ids=["json-tronque", "revision-texte", "revision-booleenne", "profil-double", "entrees-liste"],
)
def test_export_malforme_est_illisible_sans_chemin_ni_valeur_brute(console, contenu):
    profil = _creer(console, "estimateur-fictif")
    (console.dossier / "opsys").mkdir()
    (console.dossier / "opsys" / "agents.json").write_text(contenu, encoding="utf-8")
    reponse = console.client.get(f"/api/agents/{profil['id']}")
    etat = _etat(console, profil["id"])
    assert etat["export"]["statut"] == "EXPORT_ILLISIBLE"
    assert etat["export"]["revision_exportee"] is None
    assert str(console.dossier) not in reponse.text and "opsys-home" not in reponse.text


def test_lien_symbolique_dossier_absent_et_export_absent_sont_distincts(console, tmp_path, monkeypatch):
    profil = _creer(console, "estimateur-fictif")
    assert _etat(console, profil["id"])["export"]["statut"] == "EXPORT_ABSENT"
    cible = tmp_path / "ailleurs.json"
    cible.write_text(json.dumps({"entries": {"x": {"opsysRuntimeAdmission": {
        "profileId": profil["id"], "profileRevision": 2}}}}), encoding="utf-8")
    (console.dossier / "opsys").mkdir()
    (console.dossier / "opsys" / "agents.json").symlink_to(cible)
    assert _etat(console, profil["id"])["export"]["statut"] == "EXPORT_ILLISIBLE"
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(tmp_path / "dossier-inexistant"))
    etat = _etat(console, profil["id"])
    assert etat["export"]["statut"] == "NON_OBSERVABLE"
    assert etat["export"]["revision_exportee"] is None


def test_desactivation_avec_reservation_restante_n_est_pas_une_activite(console, session):
    profil = _creer(console, "estimateur-fictif")
    _exporter(console, session)
    with session() as cnx:
        admission_agents.reserver(
            cnx, profil["id"], console.deps, "execution-fictive-0001", "cle-fictive-0001", 60, tours=1, reessais=0
        )
    desactive = _activation(console, profil, False)
    etat = _etat(console, profil["id"])
    assert etat["profil"]["statut"] == "DESACTIVE" and etat["profil"]["revision"] == desactive["revision"] == 3
    assert etat["export"]["statut"] == "DESACTIVE_ENCORE_EXPORTE"
    assert etat["export"]["revision_exportee"] == 2
    assert etat["reservations"]["actives"] == 1 and etat["reservations"]["statut"] == "OBSERVEES"
    assert etat["activite"]["statut"] == "INCONNUE"
    liste = console.client.get("/agents").text
    assert "Désactivé — encore exporté" in liste
    assert "1 observée(s)" in liste and "INCONNUE" in liste
    assert "en cours" not in liste.lower()


def test_profils_de_meme_departement_et_de_deux_departements_restent_distincts(console, session):
    a = _creer(console, "estimateur-a-fictif", responsabilite="<img src=x onerror=alert(1)> devis fictifs")
    c = _creer(console, "marketing-c-fictif", DEP_B)
    _exporter(console, session)
    b = _creer(console, "estimateur-b-fictif")
    e = _creer(console, "estimateur-e-fictif", actif=False)
    attendus = {a["id"]: "CONCORDANT", b["id"]: "NON_EXPORTE", c["id"]: "CONCORDANT", e["id"]: "ABSENT_CONFORME"}
    bases = {f"base-{dep}": "CONCORDANT" for dep in console.deps}
    attendus.update(bases)
    for ident, statut in attendus.items():
        assert _etat(console, ident)["export"]["statut"] == statut, ident

    outil = console.deps[DEP_A].charger_outils()[0]
    autorises = _etat(console, a["id"])["outils"]["autorises"]
    assert autorises == [{"nom": outil.nom, "autonomie": outil.autonomie.value}]

    dep_a = console.client.get("/api/agents", params={"departement": DEP_A}).json()
    assert {item["id"]: item["etat"]["export"]["statut"] for item in dep_a["agents"]} == {
        k: v for k, v in attendus.items() if k in {a["id"], b["id"], e["id"], f"base-{DEP_A}"}
    }
    assert dep_a["export"]["statut"] == "LU" and dep_a["export"]["profils_exportes"] == len(bases) + 2

    premiere = console.client.get("/api/agents", params={"limite": 2, "decalage": 0}).json()
    seconde = console.client.get("/api/agents", params={"limite": 2, "decalage": 2}).json()
    assert premiere["pagination"] == {"total": len(attendus), "limite": 2, "decalage": 0, "retournes": 2}
    assert seconde["pagination"]["retournes"] == 2
    assert {x["id"] for x in premiere["agents"]} | {x["id"] for x in seconde["agents"]} == set(sorted(attendus)[:4])
    pages = [console.client.get("/api/agents", params={"limite": 2, "decalage": d}).json()
             for d in range(0, len(attendus), 2)]
    assert [x["id"] for page in pages for x in page["agents"]] == sorted(attendus)
    for invalide in ({"limite": 0}, {"limite": 51}, {"decalage": -1}):
        assert console.client.get("/api/agents", params=invalide).status_code == 400

    page = console.client.get("/agents").text
    assert "<img src=x" not in page and "&lt;img src=x" in page


def test_admin_revoque_en_cours_de_session_ne_lit_plus_l_etat(console, session):
    profil = _creer(console, "estimateur-fictif")
    _exporter(console, session)
    assert _etat(console, profil["id"])["export"]["statut"] == "CONCORDANT"
    with session() as cnx:
        identite.retirer_role(cnx, OWNER, "nathan_owner")
        identite.ajouter_role(cnx, OWNER, "employee")
    for chemin in (f"/api/agents/{profil['id']}", "/api/agents", f"/agents/{profil['id']}", "/agents"):
        reponse = console.client.get(chemin)
        assert reponse.status_code == 403, chemin
        assert "CONCORDANT" not in reponse.text and "revision_exportee" not in reponse.text


def _empreintes(*racines: Path) -> dict[str, str]:
    # `-shm` est l'index mémoire partagé du WAL : tout lecteur SQLite y pose ses marques de lecture.
    # La base, le WAL et l'export restent comparés octet pour octet.
    fichiers = sorted(
        p for racine in racines for p in racine.rglob("*") if p.is_file() and not p.name.endswith("-shm")
    )
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in fichiers}


def test_get_n_ecrit_ni_base_ni_export_et_reste_identique(console, session, opsys_home):
    profil = _creer(console, "estimateur-fictif")
    _exporter(console, session)
    with session() as cnx:
        admission_agents.reserver(
            cnx, profil["id"], console.deps, "execution-fictive-0002", "cle-fictive-0002", 60, tours=1, reessais=0
        )
    avant = _empreintes(opsys_home)
    console.requetes.clear()
    lectures = [console.client.get(chemin) for chemin in ("/api/agents", f"/api/agents/{profil['id']}") * 2]
    pages = [console.client.get(chemin) for chemin in ("/agents", f"/agents/{profil['id']}")]
    assert all(r.status_code == 200 for r in lectures + pages)
    assert lectures[0].json() == lectures[2].json() and lectures[1].json() == lectures[3].json()
    assert "etat" in lectures[1].json()
    assert [q for q in console.requetes if ECRITURE_SQL.match(q)] == []
    assert _empreintes(opsys_home) == avant
    for texte in [r.text for r in lectures + pages]:
        assert "Bearer" not in texte and "OPSYS_MCP_JETON" not in texte and str(opsys_home) not in texte


def test_fifo_a_la_place_de_l_export_ne_bloque_pas_la_lecture(console):
    profil = _creer(console, "estimateur-fictif")
    (console.dossier / "opsys").mkdir()
    os.mkfifo(console.dossier / "opsys" / "agents.json")
    assert _etat(console, profil["id"])["export"]["statut"] == "EXPORT_ILLISIBLE"


def test_manifeste_illisible_degrade_les_outils_sans_message_interne(console, monkeypatch):
    profil = _creer(console, "estimateur-fictif")

    def panne(self, **_):
        raise ValueError("module-interne-fictif introuvable")

    monkeypatch.setattr(Departement, "charger_outils", panne)
    for chemin in (f"/api/agents/{profil['id']}", "/api/agents"):
        reponse = console.client.get(chemin)
        assert reponse.status_code == 200 and "module-interne-fictif" not in reponse.text
    assert _etat(console, profil["id"])["outils"]["statut"] == "MANIFESTE_INDISPONIBLE"


def test_revision_exportee_superieure_au_registre_est_divergente(console):
    profil = _creer(console, "estimateur-fictif")
    _ecrire_export(console, {"opsys-agent-estimateur-fictif": {"opsysRuntimeAdmission": {
        "profileId": profil["id"], "profileRevision": 5}}})
    etat = _etat(console, profil["id"])
    assert etat["export"]["statut"] == "DIVERGENT" and etat["export"]["revision_exportee"] == 5
    # Seule une révision supérieure est observée : aucune origine (autre base, restauration) n'est affirmée.
    assert "origine non attestée" in etat["export"]["detail"]
    page = console.client.get(f"/agents/{profil['id']}").text
    assert "Révision exportée divergente" in page and "origine non attestée" in page
    for texte in (etat["export"]["detail"], page):
        assert "autre base" not in texte and "restauration" not in texte


def test_parcours_durable_deux_departements_archivage_et_reouverture(console, session):
    a = _creer(console, "estimateur-fictif")
    c = _creer(console, "marketing-fictif", DEP_B)
    archive = _creer(console, "archive-fictif")
    _exporter(console, session)
    entetes = {"x-csrf-token": console.csrf}
    supprime = console.client.request(
        "DELETE", f"/api/agents/{archive['id']}", headers=entetes,
        json={"mutation_id": "archiver-archive-fictif", "revision_attendue": archive["revision"]},
    )
    assert supprime.status_code == 200
    assert console.client.patch(
        f"/api/agents/{a['id']}", headers=entetes,
        json={"spec": _spec(console, a["id"], responsabilite="Réviser des soumissions fictives."),
              "mutation_id": "modifier-estimateur-durable", "revision_attendue": a["revision"]},
    ).status_code == 200
    with session() as cnx:
        admission_agents.reserver(
            cnx, c["id"], console.deps, "execution-fictive-0003", "cle-fictive-0003", 60, tours=1, reessais=0
        )
    _activation(console, c, False)
    avant = console.client.get("/api/agents").json()
    assert {x["id"]: x["etat"]["export"]["statut"] for x in avant["agents"]} == {
        a["id"]: "PERIME", c["id"]: "DESACTIVE_ENCORE_EXPORTE",
        **{f"base-{dep}": "CONCORDANT" for dep in console.deps},
    }
    assert avant["export"]["orphelins"] == [archive["id"]]
    assert console.client.get(f"/api/agents/{archive['id']}").status_code == 404

    stockage.liberer()
    app = application.creer_application(Configuration(SECRET), console.deps, session)
    with TestClient(app, base_url="https://testserver/opsys") as autre:
        _connecter(autre)
        assert autre.get("/api/agents").json() == avant
        _exporter(console, session)
        apres = {x["id"]: x["etat"] for x in autre.get("/api/agents").json()["agents"]}
        assert apres[a["id"]]["export"]["statut"] == "CONCORDANT"
        assert apres[a["id"]]["export"]["revision_exportee"] == 3
        assert apres[c["id"]]["export"]["statut"] == "ABSENT_CONFORME"
        assert apres[c["id"]]["reservations"]["actives"] == 1
        assert {e["activite"]["statut"] for e in apres.values()} == {"INCONNUE"}
        assert {e["chargement_core"]["statut"] for e in apres.values()} == {"INCONNU"}
        assert autre.get("/api/agents").json()["export"]["orphelins"] == []
        with session() as cnx:
            identite.retirer_role(cnx, OWNER, "nathan_owner")
        assert autre.get("/api/agents").status_code == 403
        assert autre.get(f"/agents/{a['id']}").status_code == 403


def _lire_sans_ecriture(c: Console, chemin: str, **params) -> tuple:
    """Une lecture HTTP et le nombre de lignes de profil sorties du DBAPI pendant celle-ci."""
    c.requetes.clear()
    c.lignes.clear()
    reponse = c.client.get(chemin, params=params)
    assert reponse.status_code == 200, reponse.text
    assert [q for q in c.requetes if ECRITURE_SQL.match(q)] == []
    return reponse, c.lignes_profil()


def test_pages_agents_ne_materialisent_que_les_profils_de_la_page(console, session):
    """Plus de profils que la plus grande page : un chargement complet suivi d'un découpage échoue ici."""
    exporte = _creer(console, "exporte-fictif")
    archive = _creer(console, "archive-borne-fictif")
    _exporter(console, session)
    assert console.client.request(
        "DELETE", f"/api/agents/{archive['id']}", headers={"x-csrf-token": console.csrf},
        json={"mutation_id": "archiver-borne-fictif", "revision_attendue": archive["revision"]},
    ).status_code == 200
    departements = {exporte["id"]: DEP_A, **{f"base-{dep}": dep for dep in console.deps}}
    with session() as cnx:
        for rang in range(agents_etat.LIMITE_MAX + 4):
            ident, dep = f"profil-{rang:03d}-fictif", DEP_A if rang % 3 else DEP_B
            agents.creer(cnx, console.deps, _spec(console, ident, dep), par=OWNER, mutation_id=f"creer-borne-{rang}")
            departements[ident] = dep
    tous = sorted(departements)
    dep_b = [ident for ident in tous if departements[ident] == DEP_B]

    reponse, lignes = _lire_sans_ecriture(console, "/api/agents", limite=3, decalage=3)
    corps = reponse.json()
    assert [x["id"] for x in corps["agents"]] == tous[3:6]
    assert corps["pagination"] == {"total": len(tous), "limite": 3, "decalage": 3, "retournes": 3}
    assert lignes == 3
    assert corps["export"]["orphelins"] == [archive["id"]] and corps["export"]["orphelins_total"] == 1
    assert corps["export"]["profils_exportes"] == len(console.deps) + 2

    reponse, lignes = _lire_sans_ecriture(console, "/api/agents", departement=DEP_B, limite=2, decalage=1)
    corps = reponse.json()
    assert [x["id"] for x in corps["agents"]] == dep_b[1:3]
    assert corps["pagination"] == {"total": len(dep_b), "limite": 2, "decalage": 1, "retournes": 2}
    assert lignes == 2 and corps["export"]["orphelins"] == [archive["id"]]

    reponse, lignes = _lire_sans_ecriture(console, "/api/agents", limite=5, decalage=len(tous))
    assert reponse.json()["agents"] == [] and reponse.json()["pagination"]["total"] == len(tous)
    assert lignes == 0

    pages = [_lire_sans_ecriture(console, "/api/agents", decalage=d) for d in (0, agents_etat.LIMITE_MAX)]
    assert [x["id"] for r, _ in pages for x in r.json()["agents"]] == tous
    assert [n for _, n in pages] == [agents_etat.LIMITE_MAX, len(tous) - agents_etat.LIMITE_MAX]

    page, lignes = _lire_sans_ecriture(console, "/agents")
    assert lignes == agents_etat.LIMITE_MAX
    assert f"{agents_etat.LIMITE_MAX} profil(s) affiché(s) sur {len(tous)}" in page.text
    assert "Profils suivants" in page.text
    page, lignes = _lire_sans_ecriture(console, "/agents", decalage=agents_etat.LIMITE_MAX)
    assert lignes == len(tous) - agents_etat.LIMITE_MAX and "Profils précédents" in page.text
    _, lignes = _lire_sans_ecriture(console, f"/agents/{tous[-1]}")
    assert lignes == agents_etat.LIMITE_MAX + 1  # la page courante et le profil détaillé
    _, lignes = _lire_sans_ecriture(console, f"/api/agents/{tous[-1]}")
    assert lignes == 1


def test_orphelins_sur_plusieurs_lots_restent_exacts_tries_et_bornes(console):
    connu = _creer(console, "lot-0700-fictif")
    exportes = [f"lot-{rang:04d}-fictif" for rang in range(2 * agents_etat.ORPHELINS_LOT + 150)]
    _ecrire_export(console, {f"opsys-agent-{ident}": {"opsysRuntimeAdmission": {
        "profileId": ident, "profileRevision": 1}} for ident in reversed(exportes)})
    reponse, lignes = _lire_sans_ecriture(console, "/api/agents", limite=1)
    export = reponse.json()["export"]
    orphelins = [ident for ident in exportes if ident != connu["id"]]
    assert export["profils_exportes"] == len(exportes)
    assert export["orphelins_total"] == len(orphelins)
    assert export["orphelins"] == orphelins[:agents_etat.ORPHELINS_MAX]
    assert lignes == 1


def test_lecture_profil_m05_ne_cree_ni_instance_ni_droit(console, session, opsys_home):
    profil = _creer(console, "cfo-lecture-fictif", "m05-financecore")

    def instance_et_droits():
        with session() as cnx:
            return (cnx.execute(select(OPSYS_INSTANCE)).all(),
                    cnx.execute(select(func.count()).select_from(AGENTS_GRANTS_CFO)).scalar_one())

    avant, empreintes = instance_et_droits(), _empreintes(opsys_home)
    assert len(avant[0]) == 1 and avant[1] == 0
    for chemin in (f"/agents/{profil['id']}", f"/api/agents/{profil['id']}", "/agents", "/api/agents"):
        _lire_sans_ecriture(console, chemin)
    assert instance_et_droits() == avant
    assert _empreintes(opsys_home) == empreintes
