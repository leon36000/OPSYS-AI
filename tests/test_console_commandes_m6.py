"""Console « Commandes » (C3) : les bons de commande de M6 dans la VRAIE console (FastAPI, session, rôle relu en base).

Prouvé : accès (session, rôle `admin` relu en base ; propriétaire seul, vendeur et employé refusés) ; la liste montre
statut, fournisseur, date requise, montant, « en retard » et « incomplet » sans AUCUN contact de fournisseur ; le détail
montre lignes (unité, perte déclarée), courriel, historique et réception cumulée ; lecture seule (aucun formulaire dans
le contenu, aucune méthode d'écriture, aucune écriture en base) ; paramètres fermés ; échappement du HTML ; rien en
ligne
(CSP). Limites dites : SQLite seulement, client HTTP de test, aucun navigateur réel. Données fictives.
"""

from __future__ import annotations

import html as html_module

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import META

FICTIF = True
MDP = "mot-de-passe-fictif-12345"
HORO = "2026-11-02T10:00:00-05:00"
DEPT = "m06-material-control"
COURRIEL_FOURNISSEUR = "commandes@fournisseur-un.exemple-fictif.test"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'commandes.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.liberer()
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", MDP, ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", MDP, ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", MDP, ["seller"])
        identite.creer_personne(cnx, "proprio.fictif", "Propriétaire seul", MDP, ["nathan_owner"])
    yield
    stockage.liberer()


@pytest.fixture
def navigateur(monde):
    app = application.creer_application(
        Configuration("secret-commandes-fictif-" + "x" * 40, cookie_securise=False, prefixe="/opsys"),
        charger_departements(), stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client


def _connecter(client, personne="admin.fictif"):
    reponse = client.post("/connexion", data={"identifiant": personne, "mot_de_passe": MDP}, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text


def _texte(reponse) -> str:
    return html_module.unescape(reponse.text)


def _po(po_id, statut="draft", date_requise="2099-12-31", fournisseur="f-un", montant=50.0, notes=None, courriel=None,
        complet=True, **plus):
    ligne = {"materiau_id": "REV-FICTIF", "designation": "Revêtement fictif", "unite": "feuille",
             "unite_source": "declaree", "quantite_nette": 100.0, "facteur_perte": "0.08", "quantite_demandee": 108.0,
             "verdict_prix": "PRIX_LIVRE", "prix_unitaire_prevu": 0.5, "devise_prevue": "CAD",
             "montant_ligne_prevu": montant, "prix_unite_confirmee": True}
    maillon = {"type_entree": "po_cree", "statut": "draft", "po_id": po_id, "chantier_id": "CH-FICTIF",
               "fournisseur_id": fournisseur, "horodatage": HORO, "devis_id": "D-FICTIF", "lieu_livraison": None,
               "ville": "Repentigny", "notes": notes, "lignes": [ligne], "montant_total_prevu": montant,
               "provenance_prix_lignes": [], **plus}
    if complet:
        maillon.update(date_requise=date_requise, mode_livraison="ramassage")
    else:
        for cle in ("devis_id", "lieu_livraison", "ville", "notes"):
            maillon.pop(cle)
        maillon["lignes"] = [{k: ligne[k] for k in ("materiau_id", "quantite_demandee", "verdict_prix",
                                                   "prix_unitaire_prevu", "devise_prevue", "montant_ligne_prevu")}]
    chemin = {"draft": [], "approved": ["approved"], "sent_to_supplier": ["approved", "email_ready",
                                                                          "sent_to_supplier"],
              "email_ready": ["approved", "email_ready"]}[statut]
    if courriel is not None:
        maillon["courriel"] = courriel
    with stockage.transaction():
        registre = stockage.maillons(DEPT, "bons_commande")
        registre.append(maillon)
        for cible in chemin:
            registre.append({"type_entree": "transition_po", "po_id": po_id, "statut": cible, "horodatage": HORO})


def _fournisseur():
    from m6_material_control import fournisseurs

    with stockage.transaction():
        fournisseurs.enregistrer_fournisseur(
            "f-un", "Fournisseur Un (fictif)", HORO, stockage.maillons(DEPT, "fournisseurs"),
            courriel_commande=COURRIEL_FOURNISSEUR, telephone="514-555-0199")


def _instantane():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


# ======================================================================================================== accès
def test_sans_session_les_pages_redirigent(navigateur):
    assert navigateur.get("/commandes", follow_redirects=False).status_code == 303
    assert navigateur.get("/commandes/PO-1", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("personne", ["marc.fictif", "vendeur.fictif", "proprio.fictif"],
                         ids=["employe", "vendeur", "proprietaire_sans_admin"])
def test_seul_l_admin_relu_en_base_voit_les_commandes(navigateur, personne):
    _po("PO-1")
    _connecter(navigateur, personne)

    assert navigateur.get("/commandes").status_code == 403
    assert navigateur.get("/commandes/PO-1").status_code == 403


def test_la_garde_admin_precede_l_appel_de_l_outil(navigateur, monkeypatch):
    from opsys.console import commandes_ui

    appels = []

    def espion(*args, **kwargs):
        appels.append(args)
        raise AssertionError("l'outil ne doit pas être appelé pour un non-admin")

    monkeypatch.setattr(commandes_ui.metier, "executer", espion)
    _connecter(navigateur, "proprio.fictif")

    assert navigateur.get("/commandes").status_code == 403 and appels == []


def test_la_page_est_en_lecture_seule_et_n_ecrit_rien(navigateur):
    _fournisseur()
    _po("PO-1", statut="sent_to_supplier")
    _connecter(navigateur)
    avant = _instantane()

    liste = navigateur.get("/commandes")
    detail = navigateur.get("/commandes/PO-1")

    assert liste.status_code == detail.status_code == 200
    for page in (liste, detail):
        assert "<form" not in page.text.split("<main>", 1)[1], "seul le formulaire de déconnexion de l'en-tête existe"
    for methode in (navigateur.post, navigateur.put, navigateur.delete, navigateur.patch):
        assert methode("/commandes").status_code in (403, 405)
        assert methode("/commandes/PO-1").status_code in (403, 405)
    assert _instantane() == avant


# ======================================================================================================== la liste
def test_la_liste_montre_statut_fournisseur_date_montant_retard_et_incomplet_sans_contact(navigateur):
    _fournisseur()
    _po("PO-RETARD", statut="sent_to_supplier", date_requise="2020-01-01")
    _po("PO-A-VENIR", statut="sent_to_supplier", date_requise="2099-12-31")
    _po("PO-BROUILLON")
    _po("PO-ANCIEN", complet=False)
    _connecter(navigateur)

    reponse = navigateur.get("/commandes")
    html = _texte(reponse)

    assert reponse.status_code == 200 and reponse.headers["cache-control"] == "no-store"
    assert '<html lang="fr">' in reponse.text and 'aria-current="page">Commandes' in reponse.text
    assert "script-src 'self'" in reponse.headers["content-security-policy"]
    assert "<script>" not in reponse.text and " style=" not in reponse.text and " onclick=" not in reponse.text
    assert html.count("<caption>") == 1 and 'scope="col"' in html and 'scope="row"' in html
    assert "Fournisseur Un (fictif)" in html and "Envoyé au fournisseur" in html and "Brouillon" in html
    assert "50,00 $" in html and "2099-12-31" in html
    assert html.count("En retard</span>") == 1, "un seul bon est en retard"
    assert html.count("Incomplet</span>") == 1
    assert "4 bon(s) de commande" in html
    for contact in (COURRIEL_FOURNISSEUR, "514-555-0199"):
        assert contact not in html, "aucun contact de fournisseur dans la liste"


def test_les_filtres_rapides_restreignent_la_liste(navigateur):
    _fournisseur()
    _po("PO-RETARD", statut="sent_to_supplier", date_requise="2020-01-01")
    _po("PO-BROUILLON")
    _connecter(navigateur)

    en_retard = _texte(navigateur.get("/commandes?en_retard=1"))
    brouillons = _texte(navigateur.get("/commandes?statut=draft"))

    assert "PO-RETARD" in en_retard and "PO-BROUILLON" not in en_retard
    assert "PO-BROUILLON" in brouillons and "PO-RETARD" not in brouillons
    assert "1 bon(s) de commande" in en_retard


def test_la_pagination_ne_saute_et_ne_repete_aucun_bon(navigateur):
    for i in range(30):
        _po(f"PO-{i:02d}")
    _connecter(navigateur)

    premiere = _texte(navigateur.get("/commandes"))
    seconde = _texte(navigateur.get("/commandes?debut=25"))

    vus = [f"PO-{i:02d}" for i in range(30) if f"PO-{i:02d}" in premiere] + [
        f"PO-{i:02d}" for i in range(30) if f"PO-{i:02d}" in seconde]
    assert vus == [f"PO-{i:02d}" for i in range(30)]
    assert "Page suivante" in premiere and "Page précédente" in seconde and "Page suivante" not in seconde


@pytest.mark.parametrize("requete", [
    "?statut=inconnu", "?statut=draft&statut=approved", "?debut=-1", "?debut=abc", "?debut=1000000000",
    "?en_retard=oui", "?autre=1", "?po_id=PO-1",
])
def test_les_parametres_invalides_sont_refuses(navigateur, requete):
    _po("PO-1")
    _connecter(navigateur)

    assert navigateur.get("/commandes" + requete).status_code == 400


# ======================================================================================================== le détail
def test_le_detail_montre_lignes_courriel_historique_et_reception(navigateur):
    _fournisseur()
    _po("PO-1", statut="sent_to_supplier",
        courriel={"objet": "Commande matériaux — PO-1 — Repentigny", "destinataire": COURRIEL_FOURNISSEUR,
                  "corps": "Bonjour,\nVoici le bon.", "repli_manuel_requis": False, "empreinte": "e" * 64})
    with stockage.transaction():
        stockage.maillons(DEPT, "bons_commande").append(
            {"type_entree": "transition_po", "po_id": "PO-1", "statut": "partially_received", "horodatage": HORO,
             "verdict_reception": "RECEPTION_INFERIEURE",
             "livraison": {"empreinte": "f" * 64, "horodatage": HORO,
                           "lignes": [{"materiau_id": "REV-FICTIF", "quantite_recue": "40"}]}})
    _connecter(navigateur)

    reponse = navigateur.get("/commandes/PO-1")
    html = _texte(reponse)

    assert reponse.status_code == 200
    assert "Revêtement fictif" in html and "feuille" in html and "0.08" in html and "108" in html
    assert "Commande matériaux — PO-1 — Repentigny" in html and COURRIEL_FOURNISSEUR in html
    assert "Partiellement reçu" in html and "RECEPTION_INFERIEURE" in html
    assert "Réception cumulée" in html and "40" in html
    assert "Lignes commandées" in html and html.count("<caption>") == 3


def test_un_po_ancien_se_lit_et_dit_qu_il_est_incomplet(navigateur):
    _po("PO-ANCIEN", complet=False)
    _connecter(navigateur)

    html = _texte(navigateur.get("/commandes/PO-ANCIEN"))

    assert "Incomplet" in html and "date_requise" in html and "on l'annule et on le refait" in html


def test_le_contenu_libre_est_echappe(navigateur):
    _po("PO-XSS", notes='<script>alert("x")</script>', ville="<b>Ville</b>")
    _connecter(navigateur)

    reponse = navigateur.get("/commandes/PO-XSS")

    assert '<script>alert("x")</script>' not in reponse.text
    assert "&lt;script&gt;" in reponse.text


def test_un_bon_inconnu_ou_un_identifiant_hostile_ne_donne_rien(navigateur):
    _connecter(navigateur)

    assert navigateur.get("/commandes/PO-INCONNU").status_code == 404
    for hostile in ("..%2F..%2Fetc%2Fpasswd", "%3Cscript%3E", "PO-1%00"):
        assert navigateur.get("/commandes/" + hostile).status_code in (400, 404)
    assert navigateur.get("/commandes/PO-1?x=1").status_code == 400
