"""Tableau de bord exécutif M9 par HTTP : routes réelles, session SQL, CSRF, XSS, bornes, reprise, rôle courant."""

from __future__ import annotations

import datetime as dt
import json
import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from m2_revenue_crm import outils as m2

from opsys import contexte, etat, identite, stockage
from opsys.capacites import Capacites
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements

FICTIF = True
M9, M2 = "m09-strategic-intelligence", "m02-revenue-crm"
SECRET = "signature-console-direction-m9-fictive-" + "x" * 32
MDP = "mot-de-passe-direction-fictif"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
CONNAISSANCE = "2026-10-26T12:00:00Z"
JOUR = "2026-10-26"
# La console date ses commandes avec l'horloge du serveur : les relectures se font après ce moment.
_DEMAIN = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
PLUS_TARD, JOUR_PLUS_TARD = _DEMAIN.strftime("%Y-%m-%dT%H:%M:%SZ"), _DEMAIN.strftime("%Y-%m-%d")
XSS = "<script>alert('xss-m9')</script>"


class Formulaires(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.formulaires, self._courant = [], None
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self._courant = {"action": attrs.get("action"), "methode": attrs.get("method"), "champs": {}}
            self.formulaires.append(self._courant)
        elif tag in {"input", "select", "textarea"} and self._courant is not None and attrs.get("name"):
            self._courant["champs"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self._courant = None


def _formulaires(texte, action_contient):
    return [f for f in Formulaires(texte).formulaires if f["action"] and action_contient in f["action"]]


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'direction.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", MDP, ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "proprio.seul", "Propriétaire", MDP, ["nathan_owner"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", MDP, ["seller"])
    assert m2.ingerer_lead(
        {"lead_id": "lead-1", "conversation_id": "c-1", "contact": {"nom": "C", "courriel": "c@example.test"},
         "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone"},
        "2026-09-01T09:00:00-04:00",
    )["accepte"]  # fmt: skip
    departements = charger_departements()
    cap = Capacites(departements, stockage.transaction, filtre={M9, M2}, memoire=False)

    def appel(nom, arguments):
        with contexte.appele_par_appareil(ADMIN):
            return cap.appeler(nom, arguments)

    capture = appel(
        "m9_capturer_producteur",
        {
            "lecture_id": "m2.leads",
            "arguments": {"horodatage": "2026-10-21T12:00:00Z"},
            "horodatage": "2026-10-21T12:00:01Z",
        },
    )
    assert capture["ok"] is True and capture["resultat"]["accepte"] is True, capture
    faits = appel(
        "m9_apercu_dossier_strategique",
        {"question": "Plan", "domaines": ["strategie"], "reference": "2026-10-21T13:00:00Z"},
    )["resultat"]["faits"]
    (statut,) = [a for a in faits if a.endswith("leads[0].statut")]
    (total,) = [a for a in faits if a.endswith("resultat.resultat.affichees")]
    plan = {
        "plan_id": "plan-xss",
        "objectif": f"Qualifier le lead {XSS}",
        "porteur": "vendeur.fictif",
        "echeance": "2026-10-30",
        "resultats_cles": [
            {"id": "qualifie", "libelle": "Lead qualifié", "lecture": "m2.leads",
             "chemin": "resultat.resultat.leads[*].statut", "operateur": "==", "cible": "qualifie"},
        ],
        "sources": [statut],
        "decision_ref": "decision-1",
    }  # fmt: skip
    deposee = appel(
        "m9_enregistrer_plan", {"plan": plan, "reference": "2026-10-21T13:00:00Z", "horodatage": "2026-10-21T13:00:00Z"}
    )
    assert deposee["ok"] is True and deposee["resultat"]["accepte"] is True, deposee
    app = application.creer_application(Configuration(SECRET), departements, etat.session)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client, appel, {"total": total}
    m2.reinitialiser_registre()
    stockage.liberer()


def connecter(client, identifiant="admin.fictif"):
    r = client.post("/connexion", data={"identifiant": identifiant, "mot_de_passe": MDP}, follow_redirects=False)
    assert r.status_code == 303, r.text


def tables():
    with stockage.transaction() as cnx:
        return (
            sorted(map(str, cnx.execute(stockage.META_TABLES_REGISTRES.select()).fetchall()))
            if hasattr(stockage, "META_TABLES_REGISTRES")
            else None
        )


def test_accueil_formulaire_sans_date_fabriquee_puis_panneaux_independants_et_en_tetes_de_securite(monde):
    client, _appel, _ = monde
    anonyme = client.get("/direction", follow_redirects=False)
    assert anonyme.status_code in (303, 307) and "connexion" in anonyme.headers["location"]
    connecter(client)
    r = client.get("/direction")
    assert r.status_code == 200 and 'name="connaissance"' in r.text and 'name="jour"' in r.text
    saisies = re.findall(r'<input name="(?:connaissance|jour)"[^>]*value="([^"]*)"', r.text)
    assert len(saisies) == 2 and saisies == ["", ""], "aucune date préremplie"
    assert "Direction IA" in r.text
    plein = client.get("/direction", params={"connaissance": CONNAISSANCE, "jour": JOUR})
    assert plein.status_code == 200
    for titre in (
        "Briefing",
        "Risques",
        "Prévisions des propriétaires",
        "Plans et suites",
        "Actions proposées",
        "Veille",
    ):
        assert titre in plein.text, titre
    assert "plan-xss" in plein.text and "EN_COURS" in plein.text
    assert (
        plein.headers["cache-control"] == "no-store"
        and "default-src 'none'" in plein.headers["content-security-policy"]
    )


def test_xss_echappe_partout_et_aucun_script_dans_les_pages(monde):
    client, _a, _ = monde
    connecter(client)
    for chemin, params in (
        ("/direction", {"connaissance": CONNAISSANCE, "jour": JOUR}),
        ("/direction/plans", {"connaissance": CONNAISSANCE, "jour": JOUR}),
    ):
        texte = client.get(chemin, params=params).text
        assert XSS not in texte
        assert "<script>" not in texte.replace('<script src="/opsys/statique/console.js" defer></script>', "")
        assert ("&lt;script&gt;alert(&#x27;xss-m9&#x27;)&lt;/script&gt;" in texte) == (chemin == "/direction/plans")
    reflet = client.get("/direction/sources", params={"reference": "2026-10-26T12:00:00Z", "lecture_id": "m2.leads"})
    assert reflet.status_code == 200
    mauvais = client.get("/direction/sources", params={"reference": XSS})
    assert mauvais.status_code == 400 and XSS not in mauvais.text


def test_roles_courants_non_admin_et_proprietaire_seul_refuses_sur_toutes_les_pages(monde):
    client, _a, _ = monde
    chemins = ["/direction", "/direction/risques", "/direction/sources", "/direction/plans", "/direction/actions",
               "/direction/revues", "/direction/veille", "/direction/scenarios", "/direction/conseil"]  # fmt: skip
    for identifiant in ("proprio.seul", "vendeur.fictif"):
        client.cookies.clear()
        connecter(client, identifiant)
        for chemin in chemins:
            assert client.get(chemin).status_code == 403, (identifiant, chemin)
    # Le rôle admin retiré APRÈS la connexion est refusé à l'appel suivant (rôle relu en base).
    client.cookies.clear()
    connecter(client)
    assert client.get("/direction/actions").status_code == 200
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    assert client.get("/direction/actions").status_code == 403
    assert client.get("/direction/plans", params={"connaissance": CONNAISSANCE, "jour": JOUR}).status_code == 403


@pytest.mark.parametrize(
    "chemin, params",
    [
        ("/direction", {"connaissance": "hier", "jour": JOUR}),
        ("/direction", {"connaissance": CONNAISSANCE}),
        ("/direction", {"connaissance": CONNAISSANCE, "jour": "2026-13-45x"}),
        ("/direction", {"connaissance": CONNAISSANCE, "jour": JOUR, "inconnu": "1"}),
        ("/direction/risques", {"connaissance": CONNAISSANCE, "depart": "-1"}),
        ("/direction/risques", {"connaissance": CONNAISSANCE, "depart": "x" * 300}),
        ("/direction/sources", {"reference": CONNAISSANCE, "lecture_id": "a b"}),
        ("/direction/revues", {"granularite": "annuelle"}),
        ("/direction/revue", {"index": "abc"}),
        ("/direction/veille", {"connaissance": "demain"}),
    ],
)
def test_parametres_invalides_ou_inconnus_refuses_sans_lecture(monde, chemin, params):
    client, _a, _ = monde
    connecter(client)
    assert client.get(chemin, params=params).status_code == 400


def test_parametre_repete_refuse(monde):
    client, _a, _ = monde
    connecter(client)
    r = client.get(f"/direction/risques?connaissance={CONNAISSANCE}&connaissance={CONNAISSANCE}")
    assert r.status_code == 400


def test_pages_de_detail_lisent_les_vraies_donnees_sans_rien_ecrire(monde):
    client, _a, _ = monde
    connecter(client)
    avant = _etat_registres()
    risques = client.get("/direction/risques", params={"connaissance": CONNAISSANCE})
    assert risques.status_code == 200 and "RADAR_RISQUES" in risques.text and "ABSENTE" in risques.text
    sources = client.get("/direction/sources", params={"reference": CONNAISSANCE})
    assert sources.status_code == 200 and "m2.leads" in sources.text and "Captures conservées" in sources.text
    actions = client.get("/direction/actions")
    assert actions.status_code == 200 and "/opsys/approbations" in actions.text and "ne les rejoue pas" in actions.text
    veille = client.get("/direction/veille", params={"connaissance": CONNAISSANCE})
    assert veille.status_code == 200 and "jamais récupérés par M9" in veille.text
    assert client.get("/direction/revues").status_code == 200
    assert client.get("/direction/revue", params={"index": "0"}).status_code == 404
    assert client.get("/direction/conseil", params={"session_id": "f" * 32}).status_code == 404
    assert _etat_registres() == avant, "les lectures n'écrivent rien"


def _etat_registres():
    from sqlalchemy import select

    from opsys.stockage.schema import META

    with stockage.transaction() as cnx:
        return sorted(map(str, cnx.execute(select(META.tables["registres_maillons"])).fetchall()))


def test_commandes_de_plan_csrf_idempotence_confirmation_et_reprise(monde):
    client, appel, _ = monde
    connecter(client)
    page = client.get("/direction/plans", params={"connaissance": PLUS_TARD, "jour": JOUR_PLUS_TARD})
    (suivi,) = _formulaires(page.text, "/plans/suivi")
    assert set(suivi["champs"]) >= {"csrf", "plan_id", "mutation_id", "resultat_id", "note", "connaissance", "jour"}
    donnees = {**suivi["champs"], "note": "client rappelé, rendez-vous pris", "resultat_id": "qualifie"}
    avant = _etat_registres()
    sans_csrf = client.post(
        "/direction/plans/suivi", data={k: v for k, v in donnees.items() if k != "csrf"}, follow_redirects=False
    )
    assert sans_csrf.status_code == 403 and _etat_registres() == avant
    mauvais = client.post("/direction/plans/suivi", data={**donnees, "csrf": "faux"}, follow_redirects=False)
    assert mauvais.status_code == 403 and _etat_registres() == avant
    ok = client.post("/direction/plans/suivi", data=donnees, follow_redirects=False)
    assert ok.status_code == 303 and "/direction/plans" in ok.headers["location"]
    apres = appel("m9_lire_plans", {"connaissance": PLUS_TARD, "jour": JOUR_PLUS_TARD})["resultat"]["plans"][0]
    assert (
        apres["resultats_cles"][0]["suivis_declares"] == 1
        and apres["resultats_cles"][0]["mesure"]["statut"] == "NON_SATISFAIT"
    )
    # Double soumission (même mutation_id) : rejouée, aucun second suivi.
    rejeu = client.post("/direction/plans/suivi", data=donnees, follow_redirects=False)
    assert rejeu.status_code == 303
    assert (
        appel("m9_lire_plans", {"connaissance": PLUS_TARD, "jour": JOUR_PLUS_TARD})["resultat"]["plans"][0][
            "resultats_cles"
        ][0]["suivis_declares"]
        == 1
    )
    # Même mutation_id avec d'autres données : conflit nommé, rien d'écrit.
    conflit = client.post("/direction/plans/suivi", data={**donnees, "note": "autre note"}, follow_redirects=False)
    assert conflit.status_code == 409
    # Annulation : exige la confirmation explicite.
    (annul,) = _formulaires(page.text, "/plans/annuler")
    sans_confirmation = client.post(
        "/direction/plans/annuler",
        data={k: v for k, v in annul["champs"].items() if k != "confirmer"} | {"motif": "abandon"},
        follow_redirects=False,
    )
    assert sans_confirmation.status_code == 400
    ok2 = client.post(
        "/direction/plans/annuler",
        data={**annul["champs"], "motif": "projet abandonné", "confirmer": "oui"},
        follow_redirects=False,
    )
    assert ok2.status_code == 303
    final = client.get("/direction/plans", params={"connaissance": PLUS_TARD, "jour": JOUR_PLUS_TARD})
    assert "ANNULE" in final.text and not _formulaires(final.text, "/plans/suivi"), (
        "plus de formulaire sur un plan annulé"
    )
    reprise = client.post(
        "/direction/plans/annuler",
        data={**annul["champs"], "mutation_id": "autre-id-0001", "motif": "encore", "confirmer": "oui"},
        follow_redirects=False,
    )
    assert reprise.status_code == 409 and "REJ-PLAN-ANNULE" in reprise.text


def test_corps_borne_et_formulaire_hors_limite_refuse(monde):
    client, _a, _ = monde
    connecter(client)
    page = client.get("/direction/plans", params={"connaissance": CONNAISSANCE, "jour": JOUR})
    (suivi,) = _formulaires(page.text, "/plans/suivi")
    enorme = client.post(
        "/direction/plans/suivi", data={**suivi["champs"], "note": "x" * 70_000}, follow_redirects=False
    )
    assert enorme.status_code in (400, 413)
    long = client.post(
        "/direction/plans/suivi",
        data={**suivi["champs"], "resultat_id": "qualifie", "note": "y" * 501},
        follow_redirects=False,
    )
    assert long.status_code == 400
    avec_requete = client.post("/direction/plans/suivi?x=1", data=suivi["champs"], follow_redirects=False)
    assert avec_requete.status_code == 400


def test_scenarios_post_csrf_json_borne_calcul_sur_fait_cite_et_refus_nomme(monde):
    client, _a, ids = monde
    connecter(client)
    page = client.get("/direction/scenarios")
    (formulaire,) = _formulaires(page.text, "/scenarios")
    csrf = formulaire["champs"]["csrf"]
    chocs = json.dumps([{"choc": "baisse_leads", "parametres": {"baisse_pct": "25"}}])
    bases = json.dumps({"leads_periode": ids["total"]})
    donnees = {"csrf": csrf, "reference": "2026-10-26T12:00:00Z", "bases": bases, "chocs": chocs}
    assert (
        client.post("/direction/scenarios", data={k: v for k, v in donnees.items() if k != "csrf"}).status_code == 403
    )
    r = client.post("/direction/scenarios", data=donnees)
    assert r.status_code == 200 and "baisse_leads" in r.text and "leads_projetes" in r.text
    sans_base = client.post("/direction/scenarios", data={**donnees, "bases": "{}"})
    assert sans_base.status_code == 200 and "BASE_ABSENTE" in sans_base.text and "NON_CALCULE" in sans_base.text
    assert (
        "leads_projetes" in sans_base.text
        and "calculable" in sans_base.text
        and "<code>true</code>" not in sans_base.text.split("effets")[-1].split("limites")[0]
    )
    illisible = client.post("/direction/scenarios", data={**donnees, "bases": "{pas du json"})
    assert illisible.status_code == 400 and "REJ-DIRECTION-JSON" in illisible.text
    trop = client.post("/direction/scenarios", data={**donnees, "bases": json.dumps({"a": "x" * 5000})})
    assert trop.status_code == 400
    assert re.search(r"maxlength=\"4096\"", page.text)


def test_pagination_des_sources_garde_le_filtre_de_lecture(monde):
    """Le lien « Page suivante » reprend lecture_id : la page 2 ne mélange pas d'autres lectures."""
    client, appel, _ = monde
    for i in range(30):
        capture = appel(
            "m9_capturer_producteur",
            {
                "lecture_id": "m2.leads",
                "arguments": {"horodatage": f"2026-10-21T12:{i:02d}:00Z"},
                "horodatage": f"2026-10-21T13:{i:02d}:00Z",
            },
        )
        assert capture["ok"] is True and capture["resultat"]["accepte"] is True, capture
    autre = {"lecture_id": "m6.disponibilite", "arguments": {}, "horodatage": "2026-10-21T14:00:00Z"}
    assert appel("m9_capturer_producteur", autre)["ok"] is True
    connecter(client)
    page1 = client.get("/direction/sources", params={"reference": CONNAISSANCE, "lecture_id": "m2.leads"})
    assert page1.status_code == 200
    liens = re.findall(r'href="([^"]*direction/sources[^"]*depart=[^"]*)"', page1.text)
    assert liens, "30 captures dépassent la borne d'une page : un lien « Page suivante » est attendu"
    suivant = liens[0].replace("&amp;", "&")
    assert "lecture_id=m2.leads" in suivant
    page2 = client.get(suivant.replace("/opsys", "", 1))
    assert page2.status_code == 200 and "m6.disponibilite" not in page2.text.split("Captures conservées")[-1]


@pytest.mark.parametrize(
    "reponse, attendu",
    [
        ({"ok": True, "resultat": {"accepte": True}}, None),
        ({"ok": True, "resultat": {"accepte": False}}, "REJ-DIRECTION-REFUS"),
        ({"ok": True, "resultat": {"accepte": False, "verdict": {"code": None}}}, "REJ-DIRECTION-REFUS"),
        ({"ok": True, "resultat": {"accepte": False, "verdict": {"code": "REJ-PLAN-ANNULE : x"}}}, "REJ-PLAN-ANNULE"),
        ({"ok": False, "details": ["REJ-VUE-PERIMEE : vue"]}, "REJ-VUE-PERIMEE"),
        ({"ok": False, "details": []}, "REJ-DIRECTION-ECHEC"),
        ("pas un objet", "REJ-DIRECTION-REPONSE-INVALIDE"),
    ],
)
def test_code_de_refus_d_une_reponse_d_outil_a_toujours_un_repli_nomme(reponse, attendu):
    from opsys.console import direction_ui

    assert direction_ui._refus_de_reponse(reponse) == attendu


# --- Indicateurs exécutifs, cadrage de décision, tendances, changements depuis la veille -----------------------------
NOUVELLES_PAGES = [
    ("/direction/indicateurs", {"connaissance": CONNAISSANCE}),
    ("/direction/decision", {"question": "Dois-je acheter un camion ?", "reference": CONNAISSANCE}),
    (
        "/direction/tendances",
        {
            "lecture_id": "m2.leads",
            "chemin": "resultat.resultat.total",
            "connaissance": CONNAISSANCE,
            "horizons": "7j,30j",
        },
    ),
]


def test_nouvelles_pages_refusees_sans_session_et_aux_roles_non_admin(monde):
    client, _a, _ = monde
    for chemin, params in NOUVELLES_PAGES:
        anonyme = client.get(chemin, params=params, follow_redirects=False)
        assert anonyme.status_code in (303, 307) and "connexion" in anonyme.headers["location"], chemin
    for identifiant in ("proprio.seul", "vendeur.fictif"):
        client.cookies.clear()
        connecter(client, identifiant)
        for chemin, params in NOUVELLES_PAGES:
            assert client.get(chemin, params=params).status_code == 403, (identifiant, chemin)


def test_indicateurs_decision_et_tendances_lisent_le_vrai_etat_et_echappent_tout(monde):
    client, _a, _ = monde
    connecter(client)
    avant = _etat_registres()
    indic = client.get("/direction/indicateurs", params={"connaissance": CONNAISSANCE})
    assert indic.status_code == 200 and "A_DEFINIR_PAR_LE_PROPRIETAIRE" in indic.text
    assert "DEFINIE_M8" in indic.text and "calcule_par_m9" in indic.text
    vide = client.get("/direction/indicateurs")
    assert vide.status_code == 200 and 'name="connaissance"' in vide.text
    decision = client.get(
        "/direction/decision", params={"question": "Dois-je acheter un camion ?", "reference": CONNAISSANCE}
    )
    assert decision.status_code == 200 and "achat_vehicule" in decision.text and "BROUILLON_NON_SOUMIS" in decision.text
    assert "VALIDATION_HUMAINE_REQUISE" in decision.text and "decision_prise_par_m9" in decision.text
    piege = client.get(
        "/direction/decision", params={"question": f"Dois-je acheter un camion ? {XSS}", "reference": CONNAISSANCE}
    )
    assert piege.status_code == 200 and XSS not in piege.text and "&lt;script&gt;" in piege.text
    inconnue = client.get("/direction/decision", params={"question": "Quel temps demain ?", "reference": CONNAISSANCE})
    assert inconnue.status_code == 200 and "TYPE_NON_RECONNU" in inconnue.text
    tendance = client.get("/direction/tendances", params=NOUVELLES_PAGES[2][1])
    assert tendance.status_code == 200 and "HISTORIQUE_INSUFFISANT" in tendance.text
    assert "n'est la prévision d'aucun" in tendance.text and "tendance_extrapolee" in tendance.text
    assert _etat_registres() == avant, "ces lectures n'écrivent rien"
    for page in (indic, decision, piege, inconnue, tendance):
        assert page.headers["cache-control"] == "no-store" and "<script>" not in page.text.replace(
            '<script src="/opsys/statique/console.js" defer></script>', ""
        )


@pytest.mark.parametrize(
    "chemin, params",
    [
        ("/direction/indicateurs", {"connaissance": "hier"}),
        ("/direction/indicateurs", {"connaissance": CONNAISSANCE, "depart": "-1"}),
        ("/direction/indicateurs", {"connaissance": CONNAISSANCE, "inconnu": "1"}),
        ("/direction/decision", {"question": "Camion ?"}),
        ("/direction/decision", {"question": "Camion ?", "reference": "hier"}),
        ("/direction/decision", {"question": "x" * 501, "reference": CONNAISSANCE}),
        ("/direction/decision", {"question": "Camion ?", "reference": CONNAISSANCE, "autre": "1"}),
        (
            "/direction/tendances",
            {"lecture_id": "m2.leads", "chemin": "x", "connaissance": CONNAISSANCE, "horizons": "7j"},
        ),
        (
            "/direction/tendances",
            {"lecture_id": "m2.leads", "chemin": "resultat.a", "connaissance": CONNAISSANCE, "horizons": "9j"},
        ),
        (
            "/direction/tendances",
            {"lecture_id": "m2.leads", "chemin": "resultat.a[*].b", "connaissance": CONNAISSANCE, "horizons": "7j"},
        ),
        ("/direction/tendances", {"lecture_id": "m2.leads", "chemin": "resultat.a", "connaissance": CONNAISSANCE}),
        (
            "/direction/tendances",
            {
                "lecture_id": "m2.leads",
                "chemin": "resultat.a",
                "connaissance": CONNAISSANCE,
                "horizons": "7j",
                "saison_jours": "abc",
            },
        ),
    ],
)
def test_nouvelles_pages_refusent_parametres_invalides_sans_lecture(monde, chemin, params):
    client, _a, _ = monde
    connecter(client)
    assert client.get(chemin, params=params).status_code == 400


def test_lecture_refusee_par_m9_est_affichee_avec_son_code_sans_fuite(monde):
    client, _a, _ = monde
    connecter(client)
    refus = client.get(
        "/direction/tendances",
        params={"lecture_id": "m99.inconnue", "chemin": "resultat.a", "connaissance": CONNAISSANCE, "horizons": "7j"},
    )
    assert refus.status_code == 400 and "REJ-" in refus.text and "Traceback" not in refus.text


def test_tableau_de_bord_montre_risques_actifs_changements_depuis_la_veille_et_indicateurs(monde):
    client, _a, _ = monde
    connecter(client)
    page = client.get("/direction", params={"connaissance": CONNAISSANCE, "jour": JOUR})
    assert page.status_code == 200
    assert "depuis la veille" in page.text and "capture(s) nouvelle(s)" in page.text
    assert "Indicateurs exécutifs" in page.text and 'href="/opsys/direction/indicateurs' in page.text
    assert 'href="/opsys/direction/decision' in page.text and 'href="/opsys/direction/tendances' in page.text
