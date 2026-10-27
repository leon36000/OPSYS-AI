"""CRM secrétariat, tranche 1 : répertoire (/crm) et dossier client (/crm/lead/{id}), lecture seule sur M2.

Données fictives (`FICTIF`). Le vrai registre durable de M2 est amorcé par ses propres fonctions (voie des agents), la
console le lit par `metier.executer` sous l'identité `admin` confirmée en base. NON EXÉCUTÉS dans le snapshot privé :
voir docs/grs/crm/HANDOFF-CLAUDE-SONNET55.md pour les commandes ciblées.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from m2_revenue_crm import outils as outils_m2
from m2_revenue_crm import statuts as statuts_m2
from sqlalchemy import select

from opsys import identite
from opsys.console import application, crm_ui
from opsys.console.securite import Configuration
from opsys.stockage.schema import META

FICTIF = True
SECRET = "secret-console-crm-fictif-" + "x" * 32
PREFIXE = "/opsys"
H0 = "2026-09-01T09:00:00-04:00"
H1 = "2026-09-01T09:05:00-04:00"
H2 = "2026-09-02T10:30:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
NOM_PIEGE = "Client <script>alert(1)</script> FICTIF"
NOTE = "Rappeler pour la visite <b>fictive</b>"
MOTS_DE_PASSE = {
    "admin.fictif": "mot-de-passe-admin-fictif-1234",
    "nathan": "mot-de-passe-proprietaire-fictif",
    "employe": "mot-de-passe-employe-fictif",
}


def _contact(nom: str, courriel: str) -> dict:
    return {"nom": nom, "courriel": courriel}


def _contrat(lead_id: str, contact: dict) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "contact": contact,
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }


@pytest.fixture
def client_crm(session):
    outils_m2.utiliser_stockage_durable()
    with session() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin FICTIVE", MOTS_DE_PASSE["admin.fictif"], ["admin"])
        identite.creer_personne(cnx, "nathan", "Nathan FICTIF", MOTS_DE_PASSE["nathan"], ["nathan_owner"])
        identite.creer_personne(cnx, "employe", "Employé FICTIF", MOTS_DE_PASSE["employe"], ["employee"])
    # Deux projets d'un même client (même contact), un client distinct.
    client_un = _contact(NOM_PIEGE, "un@example.test")
    client_deux = _contact("Client Deux FICTIF", "deux@example.test")
    with session():
        assert outils_m2.ingerer_lead(_contrat("lead-fictif-001", client_un), H0)["accepte"] is True
        assert outils_m2.ingerer_lead(_contrat("lead-fictif-002", client_un), H0)["accepte"] is True
        assert outils_m2.ingerer_lead(_contrat("lead-fictif-003", client_deux), H0)["accepte"] is True
        qualifie = outils_m2.transitionner_statut(
            "lead-fictif-001", "qualifie", H1, owner="vendeur.fictif", prochaine_action=ACTION)
        assert qualifie["accepte"] is True, qualifie
        note = outils_m2.enregistrer_interaction("lead-fictif-001", "admin.fictif", NOTE, H2)
        assert note["accepte"] is True, note
    app = application.creer_application(Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), None, session)
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client


def _connecter(client: TestClient, utilisateur: str) -> None:
    reponse = client.post(
        "/connexion",
        data={"identifiant": utilisateur, "mot_de_passe": MOTS_DE_PASSE[utilisateur]},
        follow_redirects=False,
    )
    assert reponse.status_code == 303, reponse.text


def _instantane_base(session):
    with session() as cnx:
        return tuple(
            (table.name, tuple(tuple(ligne) for ligne in cnx.execute(select(table)).all()))
            for table in META.sorted_tables
        )


# -- accès ---------------------------------------------------------------------------------------------------


def test_acces_refuse_sans_session_pour_employe_et_pour_owner_sans_role_admin(client_crm):
    client = client_crm
    for chemin in ("/crm", "/crm/lead/lead-fictif-001"):
        anonyme = client.get(chemin, follow_redirects=False)
        assert anonyme.status_code == 303 and anonyme.headers["location"].endswith("/connexion")

    _connecter(client, "employe")
    assert client.get("/crm").status_code == 403
    assert client.get("/crm/lead/lead-fictif-001").status_code == 403

    # Les outils M2 n'ont de portée que pour seller/admin : nathan_owner seul est refusé, pas contourné.
    _connecter(client, "nathan")
    for chemin in ("/crm", "/crm/lead/lead-fictif-001"):
        refuse = client.get(chemin)
        assert refuse.status_code == 403
        assert "lead-fictif-001" not in refuse.text and "example.test" not in refuse.text


def test_onglet_crm_dans_la_navigation_et_en_tetes_de_securite(client_crm):
    _connecter(client_crm, "admin.fictif")
    page = client_crm.get("/crm")
    assert page.status_code == 200, page.text
    assert f'href="{PREFIXE}/crm"' in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert "<script>" not in page.text.lower().replace('<script src="', "")


# -- répertoire ----------------------------------------------------------------------------------------------


def test_repertoire_liste_les_leads_de_m2_avec_lien_dossier_et_heure_de_montreal(client_crm):
    _connecter(client_crm, "admin.fictif")
    page = client_crm.get("/crm")
    assert page.status_code == 200, page.text
    for lead_id in ("lead-fictif-001", "lead-fictif-002", "lead-fictif-003"):
        assert f'href="{PREFIXE}/crm/lead/{lead_id}"' in page.text
    assert "vendeur.fictif" in page.text  # propriétaire consigné par M2
    assert "Appeler le client" in page.text  # prochaine action de M2
    assert "2026-09-01 09:00" in page.text  # 09:00-04:00 affiché en heure de Montréal
    assert "Qualifié" in page.text and "Nouveau" in page.text
    assert "Lecture seule" in page.text
    assert "alert(1)" not in page.text  # le nom du contact n'est pas dans la liste


def test_filtre_par_statut_et_parametres_invalides(client_crm):
    _connecter(client_crm, "admin.fictif")
    qualifies = client_crm.get("/crm?statut=qualifie")
    assert qualifies.status_code == 200, qualifies.text
    assert "lead-fictif-001" in qualifies.text
    assert "lead-fictif-002" not in qualifies.text and "lead-fictif-003" not in qualifies.text
    nouveaux = client_crm.get("/crm?statut=nouveau")
    assert "lead-fictif-002" in nouveaux.text and "lead-fictif-003" in nouveaux.text
    assert "lead-fictif-001" not in nouveaux.text

    for requete in ("statut=inexistant", "decalage=-1", "decalage=abc", "decalage=99999999", "inconnu=1"):
        assert client_crm.get(f"/crm?{requete}").status_code == 400, requete


def test_pagination_suit_le_decalage_de_m2_sans_calcul_local():
    page = {
        "ordre": "ingestion croissante", "total": 45, "decalage": 0, "affichees": 20, "reste": 25, "suivant": 20,
        "message": "25 autres leads non affichés : poursuivre avec decalage=20.",
        "leads": [{"lead_id": "lead-fictif-001", "statut": "nouveau", "segments": []}],
        "segments_non_calculables": [{"segment": "quote_stale"}],
    }
    debut = crm_ui.contenu_repertoire(page, statut="qualifie", prefixe=PREFIXE)
    assert f"{PREFIXE}/crm?statut=qualifie&amp;decalage=20" in debut and "Page suivante" in debut
    assert "Revenir au début" not in debut
    assert "quote_stale" in debut and "Aucune valeur n'est devinée" in debut

    milieu = crm_ui.contenu_repertoire({**page, "decalage": 20, "suivant": None}, statut="", prefixe=PREFIXE)
    assert "Revenir au début" in milieu and "Page suivante" not in milieu
    vide = crm_ui.contenu_repertoire({"leads": [], "total": 0, "decalage": 0}, statut="perdu", prefixe=PREFIXE)
    assert "Aucun lead ne correspond à ce filtre." in vide


# -- dossier -------------------------------------------------------------------------------------------------


def test_dossier_affiche_client_projets_sections_et_activites_sans_faux_boutons(client_crm):
    _connecter(client_crm, "admin.fictif")
    page = client_crm.get("/crm/lead/lead-fictif-001")
    assert page.status_code == 200, page.text
    texte = page.text
    # Contact du contrat ingéré, échappé.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in texte and NOM_PIEGE not in texte
    assert "un@example.test" in texte
    # Plusieurs projets du même client ; le client distinct n'apparaît pas.
    assert "lead-fictif-002" in texte and "(affiché ici)" in texte
    assert "lead-fictif-003" not in texte and "deux@example.test" not in texte
    # Neuf sections, état dit en toutes lettres, pas de « Vérification » recopiée.
    for libelle in ("Activités", "Suivi client", "Rencontres", "Soumissions", "Bons de commande", "Bons de travail",
                    "Coûts des travaux", "Factures", "Photos et fichiers"):
        assert libelle in texte, libelle
    assert "Non disponible" in texte and "pas encore branchée" in texte and "Vérification" not in texte
    # Activités réelles de M2, échappées, en heure de Montréal.
    assert "Rappeler pour la visite &lt;b&gt;fictive&lt;/b&gt;" in texte and "<b>fictive</b>" not in texte
    assert "2026-09-02 10:30" in texte and "admin.fictif" in texte
    # Trois formulaires internes : note, correction et déconnexion ; aucun envoi externe.
    assert texte.count('method="post"') == 3 and f'action="{PREFIXE}/deconnexion"' in texte
    assert "Envoyer" not in texte and "mailto:" not in texte
    for outil in ("m2_lister_leads", "m2_obtenir_client_360", "m2_trouver_client_de_lead", "m3_lister_devis",
                  "m5_lire_rentabilite_chantier", "m4_lister_interventions"):
        assert outil not in texte  # aucun nom d'outil à l'écran


def test_dossier_inconnu_ou_identifiant_invalide_donne_404_sans_fuite(client_crm):
    _connecter(client_crm, "admin.fictif")
    for chemin in ("/crm/lead/lead-inconnu-fictif", "/crm/lead/%3Cscript%3Ealert(1)%3C%2Fscript%3E"):
        reponse = client_crm.get(chemin)
        assert reponse.status_code == 404, chemin
        assert "alert(1)" not in reponse.text and "example.test" not in reponse.text


def test_lecture_seule_aucune_ecriture_en_base(client_crm, session):
    _connecter(client_crm, "admin.fictif")
    avant = _instantane_base(session)
    assert client_crm.get("/crm").status_code == 200
    assert client_crm.get("/crm?statut=qualifie&decalage=0").status_code == 200
    assert client_crm.get("/crm/lead/lead-fictif-001").status_code == 200
    assert client_crm.get("/crm/lead/lead-inconnu-fictif").status_code == 404
    assert _instantane_base(session) == avant


def test_aucune_route_d_ecriture_crm(client_crm):
    _connecter(client_crm, "admin.fictif")
    csrf = client_crm.get("/api/session").json()["csrf"]
    for chemin in ("/crm", "/crm/lead/lead-fictif-001"):
        for methode in (client_crm.post, client_crm.put, client_crm.delete):
            reponse = methode(chemin, headers={"x-csrf-token": csrf})
            assert reponse.status_code in {404, 405}, (methode.__name__, chemin)


# -- pur : contrats d'affichage ----------------------------------------------------------------------------


def test_statuts_alignes_sur_m2():
    assert tuple(crm_ui.STATUTS) == statuts_m2.STATUTS


def test_sections_du_brief_et_etats_honnetes():
    libelles = [libelle for _cle, libelle, *_ in crm_ui.SECTIONS]
    assert libelles == ["Activités", "Suivi client", "Rencontres", "Soumissions", "Bons de commande",
                        "Bons de travail", "Coûts des travaux", "Factures", "Photos et fichiers"]
    etats = {cle: etat for cle, _libelle, _source, etat, _explication in crm_ui.SECTIONS}
    assert etats["activites"] == "affiche"
    assert [cle for cle, etat in etats.items() if etat == "affiche"] == ["activites", "soumissions"]
    assert etats["suivi"] == "manquant" and etats["rencontres"] == "manquant"
    assert set(etats.values()) <= set(crm_ui.ETATS_SECTION)


@pytest.mark.parametrize(("entree", "attendu"), [
    ("2026-09-01T13:00:00+00:00", "2026-09-01 09:00"),
    ("2026-01-15T09:00:00-05:00", "2026-01-15 09:00"),
    (None, "—"),
    ("", "—"),
    ("pas une date", "pas une date"),
    ("2026-09-01", "2026-09-01"),
])
def test_heure_de_montreal(entree, attendu):
    assert crm_ui._montreal(entree) == attendu


def test_decalage_trop_long_refuse_nominalement(client_crm):
    _connecter(client_crm, "admin.fictif")
    reponse = client_crm.get("/crm?decalage=" + "9" * 5000)
    assert reponse.status_code == 400


# Notes internes fictives : ajout par la secrétaire, jamais un courriel client.
def _notes_m2(session):
    from opsys import stockage
    with session():
        return [m for m in stockage.maillons("m02-revenue-crm", "principal") if m.get("type_entree") == "interaction"]


def _headers_note(client):
    return {"x-csrf-token": client.get("/api/session").json()["csrf"]}


def test_note_api_auteur_serveur_idempotence_conflit_et_affichage(client_crm, session):
    _connecter(client_crm, "admin.fictif")
    headers = _headers_note(client_crm)
    avant = _notes_m2(session)
    charge = {"mutation_id": "note-fictive-1", "resume": "Visite fictive <b>à confirmer</b>"}
    route = "/api/crm/lead/lead-fictif-001/notes"
    premier = client_crm.post(route, json=charge, headers=headers)
    assert premier.status_code == 200, premier.text
    notes = _notes_m2(session)
    assert len(notes) == len(avant) + 1
    assert notes[-1]["auteur"] == "admin.fictif" and notes[-1]["resume"] == charge["resume"]
    assert notes[-1]["horodatage"] not in (H0, H1, H2)
    rejoue = client_crm.post(route, json=charge, headers=headers)
    assert rejoue.status_code == 200 and rejoue.json()["rejoue"] is True
    assert _notes_m2(session) == notes
    conflit = client_crm.post(route, json={**charge, "resume": "Autre note fictive"}, headers=headers)
    assert conflit.status_code == 409 and _notes_m2(session) == notes
    page = client_crm.get("/crm/lead/lead-fictif-001").text
    assert "Visite fictive &lt;b&gt;à confirmer&lt;/b&gt;" in page
    assert "Visite fictive <b>" not in page


def test_note_formulaire_avec_csrf_et_redirection(client_crm, session):
    import re
    _connecter(client_crm, "admin.fictif")
    page = client_crm.get("/crm/lead/lead-fictif-001").text
    assert 'maxlength="300"' in page and "Ajouter une note" in page
    mutation = re.search(r'name="mutation_id" value="([^"]+)"', page).group(1)
    csrf = client_crm.get("/api/session").json()["csrf"]
    data = {"csrf": csrf, "mutation_id": mutation, "resume": "Note secrétaire FICTIVE"}
    r = client_crm.post("/crm/lead/lead-fictif-001/notes", data=data, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == PREFIXE + "/crm/lead/lead-fictif-001#activites"
    assert _notes_m2(session)[-1]["resume"] == data["resume"]


@pytest.mark.parametrize("charge", [
    {"resume": "sans mutation"}, {"mutation_id": "", "resume": "vide"},
    {"mutation_id": "fictif", "resume": " "}, {"mutation_id": "fictif", "resume": "x" * 301},
    {"mutation_id": "fictif", "resume": "fictif", "auteur": "quelquun"},
    {"mutation_id": "fictif", "resume": "fictif", "horodatage": H0},
    {"mutation_id": "fictif", "resume": 42},
])
def test_note_champs_invalides_necrit_pas(client_crm, session, charge):
    _connecter(client_crm, "admin.fictif")
    avant = _instantane_base(session)
    r = client_crm.post("/api/crm/lead/lead-fictif-001/notes", json=charge, headers=_headers_note(client_crm))
    assert r.status_code == 400 and _instantane_base(session) == avant


def test_note_csrf_role_revoque_et_owner_seul_refuses(client_crm, session):
    _connecter(client_crm, "admin.fictif")
    route = "/api/crm/lead/lead-fictif-001/notes"
    charge = {"mutation_id": "note-acces-fictive", "resume": "Note FICTIVE"}
    avant = _notes_m2(session)
    assert client_crm.post(route, json=charge).status_code == 403
    assert client_crm.post("/crm/lead/lead-fictif-001/notes", data=charge).status_code == 403
    headers = _headers_note(client_crm)
    assert client_crm.post(route, json=charge, headers=headers).status_code == 200
    avant = _notes_m2(session)  # même mutation déjà acceptée : le retrait interdit aussi son rejeu
    with session() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    assert client_crm.post(route, json=charge, headers=headers).status_code == 403
    _connecter(client_crm, "nathan")
    assert client_crm.post(route, json=charge, headers=_headers_note(client_crm)).status_code == 403
    assert _notes_m2(session) == avant


def test_note_lead_inconnu_et_clos_refuses(client_crm, session):
    _connecter(client_crm, "admin.fictif")
    headers = _headers_note(client_crm)
    avant = _notes_m2(session)
    charge = {"mutation_id": "absent-fictif", "resume": "Note FICTIVE"}
    assert client_crm.post("/api/crm/lead/inconnu-fictif/notes", json=charge, headers=headers).status_code == 404
    with session():
        transition = outils_m2.transitionner_statut("lead-fictif-001", "perdu", H2, motif="Projet fictif abandonné")
        assert transition["accepte"]
    assert client_crm.post("/api/crm/lead/lead-fictif-001/notes", json={**charge, "mutation_id": "clos-fictif"},
                           headers=headers).status_code == 409
    assert _notes_m2(session) == avant


def test_note_session_expiree_refusee(client_crm, session, monkeypatch):
    from opsys.console import securite
    _connecter(client_crm, "admin.fictif")
    headers = _headers_note(client_crm)
    avant = _notes_m2(session)
    futur = securite.time.time() + 100000
    monkeypatch.setattr(securite.time, "time", lambda: futur)
    r = client_crm.post("/api/crm/lead/lead-fictif-001/notes",
                        json={"mutation_id": "expire-fictif", "resume": "Note FICTIVE"}, headers=headers)
    assert r.status_code == 401 and _notes_m2(session) == avant


@pytest.fixture
def devis_crm(client_crm, session):
    from m3_estimation import outils as outils_m3
    with session():
        for devis_id, lead in [("devis-fictif-001", "lead-fictif-001"),
                               ("devis-fictif-002", "lead-fictif-001"),
                               ("devis-fictif-autre", "lead-fictif-003")]:
            assert outils_m3.creer_devis(
                devis_id, lead, None,
                [{"description": "Gouttière <script>FICTIF</script>", "quantite": "2", "unite": "pi",
                  "cout_unitaire": "10", "reference_besoin_materiau": None}],
                "0.20", H0,
            )["accepte"]
    return client_crm


def test_soumissions_dossier_scoper_lecture_et_details(devis_crm, session):
    _connecter(devis_crm, "admin.fictif")
    avant = _instantane_base(session)
    dossier = devis_crm.get("/crm/lead/lead-fictif-001")
    assert '/crm/lead/lead-fictif-001/soumissions' in dossier.text
    reponse = devis_crm.get("/crm/lead/lead-fictif-001/soumissions")
    assert reponse.status_code == 200
    assert "devis-fictif-001" in reponse.text and "devis-fictif-002" in reponse.text
    assert "devis-fictif-autre" not in reponse.text
    assert 'href="/opsys/crm/lead/lead-fictif-001">Retour au dossier' in reponse.text
    detail = devis_crm.get("/crm/lead/lead-fictif-001/soumissions/devis-fictif-001")
    assert detail.status_code == 200
    assert "24.00" in detail.text  # M3 applique un taux au coût, pas un calcul du cockpit.
    assert "&lt;script&gt;FICTIF&lt;/script&gt;" in detail.text
    assert "<script>FICTIF</script>" not in detail.text
    assert '<form' not in detail.text.split('<main>', 1)[1]
    assert _instantane_base(session) == avant


def test_soumissions_liens_croises_et_identites_refuses(devis_crm, session):
    for user in ("employe", "nathan"):
        _connecter(devis_crm, user)
        assert devis_crm.get("/crm/lead/lead-fictif-001/soumissions").status_code == 403
    _connecter(devis_crm, "admin.fictif")
    avant = _instantane_base(session)
    for lead, devis in [("lead-fictif-001", "devis-fictif-autre"),
                         ("lead-fictif-001", "devis-fictif-absent"),
                         ("inconnu-fictif", "devis-fictif-001")]:
        assert devis_crm.get(f"/crm/lead/{lead}/soumissions/{devis}").status_code == 404
    assert _instantane_base(session) == avant
    with session() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    assert devis_crm.get("/crm/lead/lead-fictif-001/soumissions/devis-fictif-001").status_code == 403


@pytest.mark.parametrize("query", ["decalage=-1", "decalage=" + "9" * 5000, "decalage=1000001", "role=seller"])
def test_soumissions_pagination_invalide(devis_crm, session, query):
    _connecter(devis_crm, "admin.fictif")
    avant = _instantane_base(session)
    assert devis_crm.get("/crm/lead/lead-fictif-001/soumissions?" + query).status_code == 400
    assert _instantane_base(session) == avant


@pytest.mark.parametrize("role", [None, "seller", "employee", "nathan_owner"])
def test_soumissions_outil_admin_refuse_les_autres_contextes(devis_crm, session, role):
    from m3_estimation import outils as outils_m3

    from opsys import contexte
    avant = _instantane_base(session)
    with session(), contexte.appele_par_appareil(
        contexte.IdentiteAppelante("admin.fictif", role) if role else None,
    ):
        refus = outils_m3.lister_devis_lead_admin("lead-fictif-001")
    assert refus["accepte"] is False
    assert _instantane_base(session) == avant


def test_soumissions_outil_admin_pagine_sans_ecrire_et_revalide_role(devis_crm, session):
    from m3_estimation import outils as outils_m3

    from opsys import contexte
    avant = _instantane_base(session)
    with session(), contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin")):
        page1 = outils_m3.lister_devis_lead_admin("lead-fictif-001", limite=1)["resultat"]
        page2 = outils_m3.lister_devis_lead_admin("lead-fictif-001", limite=1, decalage=1)["resultat"]
        vide = outils_m3.lister_devis_lead_admin("aucun-devis-fictif")["resultat"]
        assert [d["devis_id"] for d in page1["devis"]] == ["devis-fictif-001"]
        assert page1["decalage_suivant"] == 1
        assert [d["devis_id"] for d in page2["devis"]] == ["devis-fictif-002"]
        assert page2["decalage_suivant"] is None and vide["devis"] == []
        assert "lignes" not in page1["devis"][0]
        for args in ({"limite": True}, {"limite": 51}, {"decalage": -1}, {"decalage": 1_000_001}):
            assert outils_m3.lister_devis_lead_admin("lead-fictif-001", **args)["accepte"] is False
        assert outils_m3.lister_devis_lead_admin(" " * 3)["accepte"] is False
        assert outils_m3.lister_devis_lead_admin("x" * 201)["accepte"] is False
    assert _instantane_base(session) == avant
    with session() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    apres = _instantane_base(session)
    with session(), contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin")):
        assert outils_m3.lister_devis_lead_admin("lead-fictif-001")["accepte"] is False
    assert _instantane_base(session) == apres


def test_soumission_approuvee_pour_envoi_ne_promet_pas_livraison(devis_crm, session):
    from m3_estimation import devis_durable
    from m3_estimation import outils as outils_m3
    with session():
        resultat, refus = devis_durable.marquer_devis_envoye(
            "devis-fictif-001", H2, outils_m3.registre_devis_production(),
        )
        assert refus is None and resultat["statut"] == "envoye"
    _connecter(devis_crm, "admin.fictif")
    reponse = devis_crm.get("/crm/lead/lead-fictif-001/soumissions/devis-fictif-001")
    assert reponse.status_code == 200
    assert "Approuvé pour envoi — livraison non attestée" in reponse.text


def test_recherche_console_contact_source_et_chaine_echappee(client_crm, session):
    _connecter(client_crm, "admin.fictif")
    avant = _instantane_base(session)
    resultat = client_crm.get("/crm", params={"q": "UN@EXAMPLE.TEST"})
    assert resultat.status_code == 200
    assert "lead-fictif-001" in resultat.text and "lead-fictif-002" in resultat.text
    assert "lead-fictif-003" not in resultat.text
    rien = client_crm.get("/crm", params={"q": '\"><script>FICTIF</script>'})
    assert rien.status_code == 200
    assert '<script>FICTIF</script>' not in rien.text
    assert "Aucun lead ne correspond" in rien.text
    assert client_crm.get("/crm", params={"q": "x" * 121}).status_code == 400
    assert _instantane_base(session) == avant


def test_recherche_outil_vendeur_n_expose_pas_le_client_d_un_autre(client_crm, session):
    from opsys import contexte
    with session() as cnx:
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur FICTIF", "mot-de-passe-fictif-long", ["seller"])
    avant = _instantane_base(session)
    with session(), contexte.appele_par_appareil(contexte.IdentiteAppelante("vendeur.fictif", "seller")):
        visible = outils_m2.lister_leads(H2, recherche="un@example.test")
        cache = outils_m2.lister_leads(H2, recherche="deux@example.test")
    assert visible["accepte"] and visible["resultat"]["total"] == 1
    assert visible["resultat"]["leads"][0]["lead_id"] == "lead-fictif-001"
    assert cache["accepte"] and cache["resultat"]["total"] == 0
    assert _instantane_base(session) == avant


def test_recherche_console_pagination_conserve_filtre(client_crm, session, monkeypatch):
    monkeypatch.setattr(crm_ui, "LIMITE_PAGE", 1)
    _connecter(client_crm, "admin.fictif")
    avant = _instantane_base(session)
    page = client_crm.get("/crm", params={"q": "un@example.test"})
    assert "lead-fictif-001" in page.text and "lead-fictif-002" not in page.text
    assert "q=un%40example.test&amp;decalage=1" in page.text
    suite = client_crm.get("/crm", params={"q": "un@example.test", "decalage": 1})
    assert "lead-fictif-002" in suite.text and "lead-fictif-003" not in suite.text
    assert _instantane_base(session) == avant


def test_recherche_logs_uvicorn_masquent_query_et_preservent_statut():
    import logging

    from uvicorn.config import LOGGING_CONFIG
    from uvicorn.logging import AccessFormatter

    from opsys.console.journaux_http import MasquerRecherche, configuration_journaux

    for query in ("q=client%40example.test", "%71=client%40example.test&statut=nouveau"):
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                                   ("127.0.0.1", "GET", "/opsys/crm?" + query, "1.1", 200), None)
        assert MasquerRecherche().filter(record)
        ligne = AccessFormatter(fmt='%(request_line)s %(status_code)s', use_colors=False).format(record)
        assert "client" not in ligne and "example.test" not in ligne
        assert "[MASQUE]" in ligne and "200" in ligne and "/opsys/crm" in ligne
    config = configuration_journaux()
    assert config["handlers"]["access"]["filters"] == ["recherche_privee"]
    assert "recherche_privee" not in LOGGING_CONFIG.get("filters", {})


# CRM-04 : corrections de coordonnées, fixtures exclusivement fictives.
def test_contact_corrige_conserve_projets_historique_recherche_et_rejeu(client_crm, session):
    _connecter(client_crm, 'admin.fictif')
    route = '/api/crm/lead/lead-fictif-001/contact'
    contact = {'nom': 'Élodie FICTIVE', 'courriel': 'corrige@example.test', 'telephone': '450-555-0100'}
    charge = {'contact': contact, 'revision_attendue': 0, 'motif': 'Correction demandée FICTIVE',
              'mutation_id': 'contact-correction-fictive-1'}
    headers = _headers_note(client_crm)
    with session():
        avant = outils_m2._obtenir_registre().lire()
        cid = outils_m2.trouver_client_de_lead('lead-fictif-001')['resultat']['client_id']
    r = client_crm.post(route, json=charge, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()['resultat']['revision'] == 1
    with session():
        apres = outils_m2._obtenir_registre().lire()
        assert apres[:-1] == avant
        correction = apres[-1]
        assert correction['client_id'] == cid and correction['auteur'] == 'admin.fictif'
        assert correction['avant']['courriel'] == 'un@example.test'
        assert correction['contact'] == contact and correction['motif'] == charge['motif']
        assert outils_m2._obtenir_registre().valider_chaine()
        vue = outils_m2.obtenir_client_360(cid)['resultat']
        assert vue['contact'] == contact and vue['revision_contact'] == 1
        assert {o['lead_id'] for o in vue['opportunites']} == {'lead-fictif-001', 'lead-fictif-002'}
        nouvel = outils_m2.ingerer_lead(_contrat('lead-fictif-004', contact), H2)
        assert nouvel['accepte']
        assert outils_m2.trouver_client_de_lead('lead-fictif-004')['resultat']['client_id'] == cid
    for lead in ['001', '002']:
        assert 'corrige@example.test' in client_crm.get('/crm/lead/lead-fictif-'+lead).text
    assert 'lead-fictif-001' in client_crm.get('/crm', params={'q': 'ELODIE'}).text
    assert 'lead-fictif-001' not in client_crm.get('/crm', params={'q': 'un@example.test'}).text
    assert client_crm.post(route, json=charge, headers=headers).json()['rejoue'] is True
    stale = client_crm.post(route, json={**charge, 'mutation_id': 'stale-fictif'}, headers=headers)
    assert stale.status_code == 409
    collision = client_crm.post(route, json={**charge, 'mutation_id': 'collision-fictive', 'revision_attendue': 1,
        'contact': _contact('Client Deux FICTIF', 'deux@example.test')}, headers=headers)
    assert collision.status_code == 409
    with session():
        assert len([m for m in outils_m2._obtenir_registre().lire()
                    if m['type_entree'] == 'contact_client_corrige']) == 1


def test_contact_refuse_agent_csrf_champs_invalides_et_rejeu_revoque(client_crm, session):
    _connecter(client_crm, 'admin.fictif')
    route = '/api/crm/lead/lead-fictif-001/contact'
    charge = {'contact': {'nom': 'Nom FICTIF'}, 'revision_attendue': 0, 'motif': 'Correction fictive',
              'mutation_id': 'contact-droits-fictif'}
    headers = _headers_note(client_crm)
    assert client_crm.post(route, json=charge).status_code == 403
    for alteration in [{'auteur': 'usurpe'}, {'revision_attendue': True}, {'contact': {}},
                       {'contact': {'nom': 'x'*255}}, {'motif': ''}]:
        assert client_crm.post(route, json={**charge, **alteration}, headers=headers).status_code == 400
    with session():
        cid = outils_m2.trouver_client_de_lead('lead-fictif-001')['resultat']['client_id']
        r = outils_m2.corriger_contact_client(cid, charge['contact'], 0, charge['motif'], H2)
        assert r['accepte'] is False and r['verdict']['code'] == 'REJ-HUMAIN-REQUIS'
    assert client_crm.post(route, json=charge, headers=headers).status_code == 200
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    assert client_crm.post(route, json=charge, headers=headers).status_code == 403


def test_contact_formulaire_echappe_revision_bornee_et_historique(client_crm, session):
    _connecter(client_crm, 'admin.fictif')
    page = client_crm.get('/crm/lead/lead-fictif-001').text
    assert 'Corriger les coordonnées' in page and 'revision_attendue' in page
    data = {'csrf': client_crm.get('/api/session').json()['csrf'], 'nom': 'Nom <b>FICTIF</b>',
            'courriel': 'nouveau@example.test', 'telephone': '', 'revision_attendue': '0',
            'motif': 'Correction FICTIVE', 'mutation_id': 'contact-form-fictif'}
    route = '/crm/lead/lead-fictif-001/contact'
    assert client_crm.post(route, data={**data, 'revision_attendue': '9'*5000}).status_code == 400
    r = client_crm.post(route, data=data, follow_redirects=False)
    assert r.status_code == 303
    html = client_crm.get('/crm/lead/lead-fictif-002').text
    assert 'Nom &lt;b&gt;FICTIF&lt;/b&gt;' in html and 'Nom <b>FICTIF</b>' not in html
    assert 'value="1"' in html


def test_contact_seller_courant_sans_autre_projet_et_rollback(client_crm, session):
    from opsys import contexte
    with session() as cnx:
        identite.creer_personne(cnx, 'vendeur.fictif', 'Vendeur FICTIF', 'secret-vendeur-fictif-1234', ['seller'])
        cid = outils_m2.trouver_client_de_lead('lead-fictif-001')['resultat']['client_id']
    admin = contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')
    vendeur = contexte.IdentiteAppelante('vendeur.fictif', 'seller', source='console')
    contact = {'nom': 'Contact FICTIF corrigé', 'courriel': 'vendeur-corrige@example.test'}
    with pytest.raises(RuntimeError, match='rollback fictif'), session(), contexte.appele_par_appareil(admin):
        assert outils_m2.corriger_contact_client(cid, contact, 0, 'Correction FICTIVE', H2)['accepte']
        raise RuntimeError('rollback fictif')
    with session():
        assert outils_m2.obtenir_client_360(cid)['resultat']['contact']['courriel'] == 'un@example.test'
    with session(), contexte.appele_par_appareil(admin):
        assert outils_m2.corriger_contact_client(cid, contact, 0, 'Correction FICTIVE', H2)['accepte']
    with session(), contexte.appele_par_appareil(vendeur):
        refuse = outils_m2.corriger_contact_client(cid, {'nom': 'Usurpation FICTIVE'}, 1, 'fictif', H2)
        assert not refuse['accepte'] and refuse['verdict']['code'] == 'REJ-IDENTITE-APPAREIL-INVALIDE'
        vue = outils_m2.obtenir_client_360(cid)['resultat']
        assert vue['contact'] == contact and [o['lead_id'] for o in vue['opportunites']] == ['lead-fictif-001']
        liste = outils_m2.lister_leads(H2, recherche='vendeur-corrige')['resultat']
        assert liste['total'] == 1 and liste['leads'][0]['lead_id'] == 'lead-fictif-001'
        autre = outils_m2.lister_leads(H2, recherche='deux@example.test')['resultat']
        assert autre['total'] == 0


def test_contact_deux_transactions_sqlite_ne_perdent_pas_une_correction(client_crm, session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from opsys import contexte
    with session():
        cid = outils_m2.trouver_client_de_lead('lead-fictif-001')['resultat']['client_id']
    depart = Barrier(2)
    def corriger(numero):
        depart.wait(timeout=10)
        with session(), contexte.appele_par_appareil(
            contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')
        ):
            return outils_m2.corriger_contact_client(cid, {'nom': f'Concurrent FICTIF {numero}'}, 0, 'FICTIF', H2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(corriger, numero) for numero in [1, 2]]
        resultats = [f.result(timeout=20) for f in futures]
    assert sorted(r['accepte'] for r in resultats) == [False, True]
    assert next(r for r in resultats if not r['accepte'])['verdict']['code'] == 'REJ-CONTACT-CONFLIT'
    with session():
        registre = outils_m2._obtenir_registre()
        assert registre.valider_chaine()
        assert len([m for m in registre.lire() if m['type_entree'] == 'contact_client_corrige']) == 1


def test_contact_rejeu_capacites_revalide_admin_sql(client_crm, session):
    from opsys import contexte, idempotence
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements

    with session():
        cid = outils_m2.trouver_client_de_lead('lead-fictif-001')['resultat']['client_id']
    caps = Capacites(charger_departements(), session, filtre={'m02-revenue-crm'},
                     appelant='m02-revenue-crm', memoire=False)
    args = {'client_id': cid, 'contact': {'nom': 'Capacité FICTIVE'}, 'revision_attendue': 0,
            'motif': 'Correction FICTIVE', 'horodatage': H2}
    meta = idempotence.Meta('contact-rejeu-fictif', 'appareil-fictif', H2)
    acteur = contexte.IdentiteAppelante('admin.fictif', 'admin', source='appareil')
    with contexte.appele_par_appareil(acteur):
        premier = caps.appeler('m2_corriger_contact_client', args, meta)
        assert premier.get('resultat', {}).get('accepte') is True, premier
        assert caps.appeler('m2_corriger_contact_client', args, meta).get('rejoue') is True
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    with contexte.appele_par_appareil(acteur):
        refuse = caps.appeler('m2_corriger_contact_client', args, meta)
        assert refuse.get('resultat', {}).get('accepte') is not True, refuse
        assert refuse['resultat']['verdict']['code'] == 'REJ-IDENTITE-APPAREIL-INVALIDE'
    with session():
        assert len([m for m in outils_m2._obtenir_registre().lire()
                    if m['type_entree'] == 'contact_client_corrige']) == 1


def test_historique_contact_admin_pagination_stable_et_lecture_pure(client_crm, session):
    from opsys import contexte
    _connecter(client_crm, 'admin.fictif')
    with session():
        cid = outils_m2.trouver_client_de_lead('lead-fictif-001')['resultat']['client_id']
    acteur = contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')
    route = '/crm/lead/lead-fictif-001/contact/historique'
    vide = client_crm.get(route)
    assert vide.status_code == 200, vide.text
    assert 'Aucune correction' in vide.text
    assert 'contact/historique' in client_crm.get('/crm/lead/lead-fictif-001').text
    with session(), contexte.appele_par_appareil(acteur):
        for revision in range(22):
            assert outils_m2.corriger_contact_client(cid, {'nom': f'Client FICTIF {revision+1}'}, revision,
                                                     'Motif <script>FICTIF</script>', H2)['accepte']
    avant = _instantane_base(session)
    page = client_crm.get(route)
    assert page.status_code == 200 and '22 corrections' in page.text
    assert 'admin.fictif' in page.text and 'Motif &lt;script&gt;FICTIF&lt;/script&gt;' in page.text
    assert 'Motif <script>' not in page.text and 'Client FICTIF 22' not in page.text
    assert 'un@example.test' in page.text and 'revision_max=22' in page.text
    assert 'deux@example.test' not in page.text
    assert _instantane_base(session) == avant
    with session(), contexte.appele_par_appareil(acteur):
        assert outils_m2.corriger_contact_client(cid, {'nom': 'Client FICTIF 23'}, 22, 'FICTIF', H2)['accepte']
        p = outils_m2.lister_historique_contact_client(cid, limite=2, decalage=20, revision_max=22)['resultat']
        assert [e['revision'] for e in p['corrections']] == [21, 22]
        assert p['total'] == 22 and p['suivant'] is None and p['revision_max'] == 22
        assert p['corrections'][0]['avant'] == {'nom': 'Client FICTIF 20'}
        p['corrections'][0]['contact']['nom'] = 'MUTATION FICTIVE'
        relue = outils_m2.lister_historique_contact_client(cid)['resultat']
        assert relue['corrections'][0]['contact']['nom'] == 'Client FICTIF 1'
    avant = _instantane_base(session)
    suite = client_crm.get(route, params={'decalage': 20, 'revision_max': 22})
    assert suite.status_code == 200 and 'Client FICTIF 22' in suite.text and 'Client FICTIF 23' not in suite.text
    assert 'revision_max=22' in suite.text
    assert '23 corrections' in client_crm.get(route).text
    for params in [{'decalage': '-1'}, {'revision_max': '9'*5000}, {'revision_max': '24'},
                   {'limite': '500'}, {'decalage': '1.0'}, {'decalage': '1000001'}]:
        assert client_crm.get(route, params=params).status_code == 400
    assert client_crm.get('/crm/lead/inconnu-fictif/contact/historique').status_code == 404
    assert _instantane_base(session) == avant


def test_historique_contact_refuse_seller_agent_roles_et_revocation(client_crm, session):
    from opsys import contexte
    route = '/crm/lead/lead-fictif-001/contact/historique'
    assert client_crm.get(route, follow_redirects=False).status_code == 303
    for personne in ['employe', 'nathan']:
        _connecter(client_crm, personne)
        r = client_crm.get(route)
        assert r.status_code == 403 and 'example.test' not in r.text
    with session() as cnx:
        identite.creer_personne(cnx, 'vendeur.fictif', 'FICTIF', 'mot-passe-vendeur-fictif-1234', ['seller'])
        cid = outils_m2.trouver_client_de_lead('lead-fictif-001')['resultat']['client_id']
        assert outils_m2.lister_historique_contact_client(cid)['verdict']['code'] == 'REJ-HUMAIN-REQUIS'
    with session(), contexte.appele_par_appareil(
        contexte.IdentiteAppelante('vendeur.fictif', 'seller', source='console')
    ):
        for cible in [cid, '0'*64]:
            r = outils_m2.lister_historique_contact_client(cible)
            assert r['verdict']['code'] == 'REJ-IDENTITE-APPAREIL-INVALIDE' and 'resultat' not in r
    _connecter(client_crm, 'admin.fictif')
    assert client_crm.get(route).status_code == 200
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    assert client_crm.get(route).status_code == 403
    with session(), contexte.appele_par_appareil(
        contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')
    ):
        assert outils_m2.lister_historique_contact_client(cid)['verdict']['code'] == 'REJ-IDENTITE-APPAREIL-INVALIDE'


def test_diagnostic_memoire_contact_admin_lisible_sans_donnee_privee(client_crm, session):
    from opsys import contexte
    route = '/crm/lead/lead-fictif-001/contact/memoire'
    assert client_crm.get(route, follow_redirects=False).status_code == 303
    for personne in ['employe', 'nathan']:
        _connecter(client_crm, personne)
        assert client_crm.get(route).status_code == 403
    _connecter(client_crm, 'admin.fictif')
    assert 'Aucune référence' in client_crm.get(route).text
    with session():
        cid = outils_m2.trouver_client_de_lead('lead-fictif-001')['resultat']['client_id']
    with session(), contexte.appele_par_appareil(
        contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')
    ):
        assert outils_m2.corriger_contact_client(cid, {'nom': 'Coordonnée SECRÈTE FICTIVE'}, 0,
                                                 'Motif SECRÈTE FICTIVE', H2)['accepte']
    avant = _instantane_base(session)
    page = client_crm.get(route)
    assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
    assert '1 corrections ; 2 références' in page.text and 'En attente de M10' in page.text
    assert 'SECRÈTE' not in page.text and 'un@example.test' not in page.text
    assert 'contact/memoire' in client_crm.get('/crm/lead/lead-fictif-001/contact/historique').text
    for params in [{'decalage': '-1'}, {'revision_max': '2'}, {'limite': '500'}, {'replay': '1'}]:
        assert client_crm.get(route, params=params).status_code == 400
    assert _instantane_base(session) == avant
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    assert client_crm.get(route).status_code == 403
