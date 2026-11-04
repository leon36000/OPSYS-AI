"""Console « Réglages de direction » (CFG-1) : vraies routes, session SQL, sas N3 réel, données fictives.

Prouve : l'écran liste ce qui manque, ce que ça bloque, la proposition « recommandation, non validée » avec sa source
et un formulaire prérempli — sans rien appliquer ; seul le PROPRIÉTAIRE adopte ou annule (un administrateur voit
l'écran, un employé ne le voit pas, une session sans le rôle est refusée avant toute écriture) ; le geste passe par
le sas (demande N3 décidée par le propriétaire, maillon signé) ; CSRF, champs fermés, paramètres inattendus, valeur
hors bornes, mauvais type, raison avec renseignement personnel, version périmée, double envoi et retour arrière ; une
chaîne falsifiée est signalée et gèle les gestes ; tout est échappé ; réponses sans cache. Les refus ne laissent
AUCUNE demande ni aucun maillon. Données fictives.
"""

from __future__ import annotations

import importlib.util
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from opsys import identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.stockage.schema import APPROBATIONS, JOURNAL, REGISTRES

_spec = importlib.util.spec_from_file_location("reglages_aide", Path(__file__).with_name("reglages_aide.py"))
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)

FICTIF = True
SECRET = "secret-console-reglages-fictif-" + "x" * 40
CLE = "m2.jours_entre_relances"


class Formulaires(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.champs, self.boutons = [], []
        self._bouton = False
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input":
            self.champs.append(a)
        if tag == "button":
            self._bouton = True

    def handle_data(self, data):
        if self._bouton and data.strip():
            self.boutons.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "button":
            self._bouton = False


@pytest.fixture
def deps(tmp_path, monkeypatch):
    yield aide.installer(tmp_path, monkeypatch)
    stockage.liberer()


@pytest.fixture
def client(deps):
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe="/opsys"), deps, stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as c:
        yield c


def _connecter(client, personne=aide.PROPRIETAIRE):
    r = client.post("/connexion", data={"identifiant": personne, "mot_de_passe": aide.MOT_DE_PASSE},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    return client.get("/api/session").json()["csrf"]


def _post(client, csrf, **champs):
    champs = {"csrf": csrf, "action": "adopter", "cle": CLE, "saisie": "7", "raison": "Point de départ discuté",
              "version_attendue": "0", **champs}
    champs = {k: v for k, v in champs.items() if v is not None}
    return client.post("/reglages/geste", data=champs, follow_redirects=False)


def _api(client, csrf, **donnees):
    donnees = {"action": "adopter", "cle": CLE, "valeur": 7, "raison": "Point de départ discuté", **donnees}
    return client.post("/api/reglages", json=donnees, headers={"x-csrf-token": csrf})


def _etat():
    with stockage.transaction() as cnx:
        return {
            "demandes": cnx.execute(select(APPROBATIONS.c.outil, APPROBATIONS.c.statut, APPROBATIONS.c.niveau,
                                           APPROBATIONS.c.decide_par, APPROBATIONS.c.decide_role)).all(),
            "chaine": len(cnx.execute(select(REGISTRES.c.rang).where(
                REGISTRES.c.departement == "opsys-reglages")).all()),
        }


def _texte(html):
    import html as h
    return re.sub(r"\s+", " ", h.unescape(re.sub(r"<[^>]+>", " ", html)))


# -- l'accès --------------------------------------------------------------------------------------------------
def test_sans_session_l_ecran_redirige_et_l_api_refuse(client):
    assert client.get("/reglages", follow_redirects=False).status_code == 303
    assert client.get("/api/reglages").status_code == 401
    assert client.post("/api/reglages", json={}).status_code == 401
    assert client.post("/reglages/geste", data={}, follow_redirects=False).status_code == 303
    assert _etat() == {"demandes": [], "chaine": 0}


def test_un_employe_ne_voit_pas_l_ecran(client):
    csrf = _connecter(client, aide.EMPLOYE)
    assert client.get("/reglages").status_code == 403
    assert client.get("/api/reglages").status_code == 403
    assert _post(client, csrf).status_code == 403
    assert _etat() == {"demandes": [], "chaine": 0}


def test_un_administrateur_voit_l_ecran_mais_ne_peut_ni_adopter_ni_annuler(client):
    csrf = _connecter(client, aide.ADMIN)
    page = client.get("/reglages")
    assert page.status_code == 200 and "Seul le propriétaire adopte ou annule" in _texte(page.text)
    assert 'name="saisie"' not in page.text and "Adopter (N3" not in page.text
    assert client.get("/api/reglages").json()["peut_adopter"] is False
    for action in ("adopter", "revenir"):
        r = _post(client, csrf, action=action)
        assert r.status_code == 403, r.text
        assert "PROPRIETAIRE_REQUIS" in r.text
    assert _api(client, csrf).status_code == 403
    assert _etat() == {"demandes": [], "chaine": 0}


def test_un_non_proprietaire_n_apprend_rien_le_refus_precede_toute_validation_du_reglage(client):
    csrf = _connecter(client, aide.ADMIN)
    for essai in (dict(cle="m2.inexistant"), dict(saisie="abc"), dict(saisie="0"), dict(raison="x"),
                  dict(action="revenir", saisie=None)):
        r = _post(client, csrf, **essai)
        assert r.status_code == 403 and "PROPRIETAIRE_REQUIS" in r.text, (essai, r.text)
    assert _etat() == {"demandes": [], "chaine": 0}


def test_le_role_proprietaire_retire_apres_la_connexion_est_refuse_sans_ecriture(client):
    csrf = _connecter(client)
    assert client.get("/reglages").status_code == 200
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, aide.PROPRIETAIRE, "nathan_owner")
    assert _post(client, csrf).status_code == 403
    assert _api(client, csrf).status_code == 403
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, aide.PROPRIETAIRE, "admin")
    assert client.get("/reglages", follow_redirects=False).status_code in (401, 403)
    assert _etat() == {"demandes": [], "chaine": 0}


# -- l'écran ---------------------------------------------------------------------------------------------------
def test_l_ecran_liste_ce_qui_manque_ce_que_ca_bloque_la_proposition_et_son_origine(client):
    _connecter(client)
    page = client.get("/reglages")
    assert page.status_code == 200
    texte = _texte(page.text)
    assert "31 réglage(s) à décider sur 34" in texte
    assert "REJ-RELANCES-A-CONFIGURER" in texte and "INDÉTERMINÉ" in texte
    assert "recommandation, non validée" in texte and "ANALYSE-M2" in texte
    assert "Aucune valeur proposée : à décider par la direction." in texte
    assert "M2 — Revenue CRM" in texte and "M8 — Analytics" in texte
    assert "À décider" in texte and "Valeur en vigueur —" in texte
    assert "Précédence : valeur adoptée ici, puis valeur déjà écrite dans le fichier du département" in texte
    assert "puis absence." in texte
    assert "(CPA) / professionnel qualifié" in texte
    formulaires = Formulaires(page.text)
    saisies = {c["value"] for c in formulaires.champs if c.get("name") == "saisie"}
    assert {"30", "14", "7"} <= saisies, "la proposition préremplit le champ : elle ne s'applique pas"
    assert formulaires.boutons.count("Adopter (N3, propriétaire)") == 34
    assert 'aria-current="page">Réglages de direction' in page.text.replace("\n", "")
    assert page.headers["cache-control"] == "no-store" and page.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert _etat() == {"demandes": [], "chaine": 0}, "regarder l'écran n'adopte rien"


def test_l_api_donne_le_meme_etat_que_l_ecran(client):
    _connecter(client)
    vue = client.get("/api/reglages").json()
    assert vue["total"] == 34 and vue["manquants"] == 31 and vue["peut_adopter"] is True and vue["journal"] == []
    assert vue["chaine"]["valide"] is True
    assert {r["cle"] for r in vue["reglages"] if r["proposition"]} == {
        "m2.jours_inactivite_dormant", "m2.jours_soumission_perimee", CLE,
        "m6.seuil_variance_chantier_pourcentage", "m6.seuil_ecart_prix_reception_pourcentage",
        "m6.plafond_achat_terrain"}
    assert client.get("/api/reglages?x=1").status_code == 400
    assert client.get("/reglages?x=1").status_code == 400


# -- le geste -----------------------------------------------------------------------------------------------------
def test_adopter_une_proposition_passe_par_le_sas_n3_et_ecrit_un_maillon_signe(client):
    csrf = _connecter(client)
    r = _post(client, csrf)
    assert r.status_code == 303 and r.headers["location"] == "/opsys/reglages?ok=adopte#reglage-m2.jours_entre_relances"
    assert _etat()["demandes"] == [("m9_adopter_reglage", "executee", "N3", aide.PROPRIETAIRE, "nathan_owner")]
    (maillon,) = aide.chaine()
    assert maillon["nouvelle_valeur"] == 7 and maillon["origine"] == "proposition"
    assert maillon["par"] == aide.PROPRIETAIRE
    assert maillon["raison"] == "Point de départ discuté" and maillon["version"] == 1
    page = client.get(r.headers["location"].removeprefix("/opsys").split("#")[0])
    texte = _texte(page.text)
    assert "Valeur adoptée (N3)" in texte and "Adopté" in texte
    assert f"version 1, par {aide.PROPRIETAIRE}" in texte and "Valeur en vigueur 7 jours" in texte
    assert "30 réglage(s) à décider sur 34" in texte
    assert "Revenir en arrière" in texte and "Point de départ discuté" in texte


def test_adopter_sa_propre_valeur_l_emporte_et_n_est_pas_marquee_proposition(client):
    csrf = _connecter(client)
    assert _post(client, csrf, saisie="10").status_code == 303
    assert aide.chaine()[0]["origine"] == "saisie" and aide.chaine()[0]["nouvelle_valeur"] == 10


def test_un_double_envoi_est_idempotent_et_le_bandeau_le_dit(client):
    csrf = _connecter(client)
    assert _post(client, csrf).status_code == 303
    second = _post(client, csrf)
    assert second.status_code == 303 and "ok=deja_adopte" in second.headers["location"]
    assert _etat()["chaine"] == 1
    assert "déjà en vigueur" in _texte(client.get("/reglages?ok=deja_adopte").text)


def test_une_version_perimee_est_refusee_en_409_et_rien_n_est_ecrit(client):
    csrf = _connecter(client)
    assert _post(client, csrf).status_code == 303
    avant = _etat()
    r = _post(client, csrf, saisie="14", version_attendue="0")
    assert r.status_code == 409 and "REJ-REGLAGE-VERSION" in r.text
    assert _etat() == avant


@pytest.mark.parametrize(("saisie", "code"), [
    ("0", "REJ-REGLAGE-HORS-BORNES"), ("3651", "REJ-REGLAGE-HORS-BORNES"), ("-4", "REJ-REGLAGE-HORS-BORNES"),
    ("7.5", "REJ-REGLAGE-TYPE"), ("abc", "REJ-REGLAGE-TYPE"), ("", "REJ-REGLAGE-TYPE"),
    ("1" * 500, "REJ-REGLAGE-FORME"),
])
def test_une_valeur_hors_bornes_ou_illisible_est_refusee_sans_demande_ni_maillon(client, saisie, code):
    csrf = _connecter(client)
    r = _post(client, csrf, saisie=saisie)
    assert r.status_code == 400 and code in r.text, r.text
    assert _etat() == {"demandes": [], "chaine": 0}


@pytest.mark.parametrize(("cle", "saisie"), [
    ("m2.bandes_valeur_cents", "30, 20, 10"), ("m2.bandes_valeur_cents", "10, 20"),
    ("m8.bornes_taux_acceptation_pct", "60 ; 20"), ("m8.bornes_taux_acceptation_pct", "20"),
    ("m8.bornes_devis_sans_reponse", "0 ; 10"), ("m8.bornes_cash_libre_cad", "abc ; 10"),
])
def test_les_types_composes_sont_valides_selon_le_manifeste_du_departement(client, cle, saisie):
    csrf = _connecter(client)
    r = _post(client, csrf, cle=cle, saisie=saisie)
    assert r.status_code == 400, r.text
    assert _etat() == {"demandes": [], "chaine": 0}


def test_les_types_composes_valides_sont_adoptes_et_rendus_lisibles(client):
    csrf = _connecter(client)
    assert _post(client, csrf, cle="m2.bandes_valeur_cents", saisie="500000, 1500000, 4000000").status_code == 303
    assert _post(client, csrf, cle="m8.bornes_taux_acceptation_pct", saisie="20 ; 60").status_code == 303
    assert _post(client, csrf, cle="m8.bornes_devis_sans_reponse", saisie="10 ; 0").status_code == 303
    texte = _texte(client.get("/reglages").text)
    assert "500000, 1500000, 4000000 cents CAD" in texte and "20 ; 60 %" in texte and "10 ; 0 devis" in texte
    assert [m["nouvelle_valeur"] for m in aide.chaine()] == [
        [500000, 1500000, 4000000], {"pire": "20", "cible": "60"}, {"pire": "10", "cible": "0"}]


def test_une_cle_inconnue_est_404_et_une_action_inconnue_400(client):
    csrf = _connecter(client)
    assert _post(client, csrf, cle="m2.inexistant").status_code == 404
    assert _post(client, csrf, cle="m9.jours_entre_relances").status_code == 404
    assert _post(client, csrf, action="supprimer").status_code == 400
    assert _etat() == {"demandes": [], "chaine": 0}


@pytest.mark.parametrize("raison", ["ab", "Voir marie.tremblay@example.test", "Appeler le 418-555-0142", "x" * 301])
def test_une_raison_invalide_ou_avec_renseignement_personnel_est_refusee(client, raison):
    csrf = _connecter(client)
    r = _post(client, csrf, raison=raison)
    assert r.status_code == 400 and "REJ-REGLAGE-RAISON" in r.text
    assert _etat() == {"demandes": [], "chaine": 0}


def test_csrf_absent_ou_faux_champ_en_trop_ou_en_moins_et_parametres_sont_refuses(client):
    csrf = _connecter(client)
    assert _post(client, None).status_code == 403
    assert _post(client, "faux").status_code == 403
    assert client.post("/reglages/geste", data={"csrf": csrf, "action": "adopter", "cle": CLE},
                       follow_redirects=False).status_code == 400
    assert _post(client, csrf, par="autre").status_code == 400
    assert _post(client, csrf, version_attendue="un").status_code == 400
    assert client.post("/reglages/geste?x=1", data={"csrf": csrf}, follow_redirects=False).status_code == 400
    assert _api(client, "faux").status_code == 403
    assert client.post("/api/reglages", json={"action": "adopter", "cle": CLE, "valeur": 7, "raison": "Sans jeton"}
                       ).status_code == 403
    assert _api(client, csrf, role="admin").status_code == 400
    assert _etat() == {"demandes": [], "chaine": 0}


def test_l_api_json_adopte_une_valeur_typee_et_revient_en_arriere(client):
    csrf = _connecter(client)
    r = _api(client, csrf, valeur=10, version_attendue=0)
    assert r.status_code == 200 and r.json()["resultat"]["statut"] == "adopte" and r.json()["resultat"]["version"] == 1
    r = client.post("/api/reglages", json={"action": "revenir", "cle": CLE, "raison": "Retour au départ",
                                           "version_attendue": 1}, headers={"x-csrf-token": csrf})
    assert r.status_code == 200 and r.json()["resultat"]["statut"] == "retour_arriere"
    assert aide.chaine()[-1]["type"] == "retour_arriere" and aide.chaine()[-1]["nouvelle_valeur"] is None


def test_le_retour_arriere_depile_et_refuse_quand_il_n_y_a_rien_a_annuler(client):
    csrf = _connecter(client)
    assert _post(client, csrf, saisie="7").status_code == 303
    assert _post(client, csrf, saisie="10", version_attendue="1").status_code == 303
    r = _post(client, csrf, action="revenir", saisie=None, raison="Retour au point précédent", version_attendue="2")
    assert r.status_code == 303 and "ok=retour_arriere" in r.headers["location"]
    assert "Valeur en vigueur 7 jours" in _texte(client.get("/reglages").text)
    assert _post(client, csrf, action="revenir", saisie=None, raison="Retour au départ", version_attendue="3"
                 ).status_code == 303
    page = _texte(client.get("/reglages").text)
    assert "31 réglage(s) à décider sur 34" in page, "après le retour arrière, la fonction est de nouveau inerte"
    refus = _post(client, csrf, action="revenir", saisie=None, raison="Encore un retour", version_attendue="4")
    assert refus.status_code == 409 and "REJ-REGLAGE-RIEN-A-ANNULER" in refus.text
    assert [m["type"] for m in aide.chaine()] == ["adoption", "adoption", "retour_arriere", "retour_arriere"]


def test_le_journal_affiche_les_gestes_et_echappe_tout(client):
    csrf = _connecter(client)
    assert _post(client, csrf, raison="Décision <b>importante</b> & \"urgente\"").status_code == 303
    page = client.get("/reglages").text
    assert "<b>importante</b>" not in page and "&lt;b&gt;importante&lt;/b&gt;" in page
    texte = _texte(page)
    assert "Adoption" in texte and "aucune → 7" in texte and aide.PROPRIETAIRE in texte


# -- l'intégrité ----------------------------------------------------------------------------------------------------
def test_une_chaine_falsifiee_est_signalee_ne_sert_plus_rien_et_gele_les_gestes(client):
    csrf = _connecter(client)
    assert _post(client, csrf).status_code == 303
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(REGISTRES.c.maillon).where(REGISTRES.c.departement == "opsys-reglages")).scalar_one()
        maillon = json.loads(ligne)
        maillon["nouvelle_valeur"] = 1
        cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == "opsys-reglages").values(
            maillon=json.dumps(maillon, ensure_ascii=False, separators=(",", ":"))))
    page = client.get("/reglages")
    assert page.status_code == 200 and 'role="alert"' in page.text
    assert "AUCUNE valeur adoptée n'est servie" in _texte(page.text)
    vue = client.get("/api/reglages").json()
    assert vue["chaine"]["valide"] is False and vue["manquants"] == 31 and vue["journal"] == []
    avant = _etat()
    r = _post(client, csrf, saisie="14", version_attendue="1")
    assert r.status_code in (409, 400) and "REJ-REGLAGE" in r.text
    assert _etat() == avant


def test_un_refus_du_sas_ne_laisse_ni_demande_ni_maillon(client, monkeypatch):
    csrf = _connecter(client)
    from opsys import approbations

    def refuse(*_a, **_k):
        raise ValueError("le sas refuse")

    monkeypatch.setattr(approbations, "decider", refuse)
    r = _post(client, csrf)
    assert r.status_code == 403 and "PROPRIETAIRE_REQUIS" in r.text
    assert _etat() == {"demandes": [], "chaine": 0}


def test_une_demande_deposee_par_un_agent_s_approuve_depuis_la_page_des_approbations_et_adopte(deps, client):
    from opsys.capacites import Capacites

    csrf = _connecter(client)
    capacites = Capacites({aide.M9: deps[aide.M9]}, stockage.transaction, appelant=aide.M9, memoire=False)
    proposee = capacites.appeler("m9_adopter_reglage", {"cle": CLE, "valeur": 7, "raison": "Proposition de l'agent"})
    assert proposee["statut"] == "en_attente_approbation" and aide.chaine() == []
    r = client.post(f"/approbations/{proposee['demande_id']}/decision",
                    data={"csrf": csrf, "decision": "approuver", "motif": "Validé par le propriétaire"},
                    follow_redirects=False)
    assert r.status_code == 303 and "ok=executee" in r.headers["location"], r.text
    (maillon,) = aide.chaine()
    assert maillon["par"] == aide.PROPRIETAIRE and maillon["approbation_id"] == proposee["demande_id"]
    assert "Valeur en vigueur 7 jours" in _texte(client.get("/reglages").text)


def test_l_audit_du_socle_ne_garde_que_la_cle_la_version_et_l_empreinte(client):
    csrf = _connecter(client)
    assert _post(client, csrf, raison="Raison de direction numéro 5151").status_code == 303
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(JOURNAL)).mappings().all()
    assert any(ligne["action"] == "reglage.adopter" for ligne in lignes)
    assert "5151" not in json.dumps([{k: str(v) for k, v in ligne.items()} for ligne in lignes], ensure_ascii=False)
