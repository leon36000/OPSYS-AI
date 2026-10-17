"""Parcours privé coûts AP→M7, vrai SDK et SQLite ; entreprise et pièces fictives."""

import copy
import json
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from m5_financecore import outils as m5
from sqlalchemy import select, update

from opsys import approbations, contexte, identite, stockage
from opsys.console import application, metier, securite
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, JOURNAL, MUTATIONS_APPLIQUEES, REGISTRES

DATES = {"debut": "2026-09-01", "fin": "2026-09-30"}
MOT_DE_PASSE = "mot-de-passe-couts-fictif-123"
SECRET = "secret-couts-fictif-" + "x" * 64


@pytest.fixture
def navigateur(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'couts-fictifs.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-fictif"))
    configuration = tmp_path / "m5-configuration-fictive.yaml"
    configuration.write_text("configuration:\n  categories_depense_sans_po: [marketing]\n", encoding="utf-8")
    monkeypatch.setattr(m5, "_MANIFESTE", configuration)
    stockage.liberer()
    stockage.migrer()
    deps = charger_departements()
    with stockage.transaction() as cnx:
        for ident, roles in (("owner.fictif", ["nathan_owner"]), ("admin.fictif", ["admin"]),
                             ("employe.fictif", ["employee"])):
            identite.creer_personne(cnx, ident, ident, MOT_DE_PASSE, roles)
        outil = next(o for o in deps["m05-financecore"].charger_outils() if o.nom == "m5_saisir_facture_sans_po")
        demande = approbations.creer_demande(cnx, "m05-financecore", outil.nom, {
            "fournisseur_id": "Imprimeur fictif", "categorie": "marketing", "numero_facture": "F-FICTIVE",
            "date_facture": "2026-10-01", "montant_avant_taxes": "100.00", "total_facture": None,
            "horodatage": "2026-10-02T12:00:00+00:00",
        }, niveau=approbations.Niveau.N3)
        decision = approbations.decider(cnx, demande, True, "owner.fictif", {outil.nom: outil}, deps)
        assert decision["statut"] == "executee", decision
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe="/opsys"),
        deps, stockage.transaction,
    )
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client
    stockage.liberer()


def _connecter(client, personne="owner.fictif"):
    response = client.post("/connexion", data={"identifiant": personne, "mot_de_passe": MOT_DE_PASSE},
                           follow_redirects=False)
    assert response.status_code == 303, response.text
    return client.get("/api/session").json()["csrf"]


def _campagne(client, csrf):
    # La campagne utilise le SDK public existant ; aucune route de création nouvelle n'est inventée.
    session = securite.lire_session(client.cookies.get(securite.NOM_COOKIE), SECRET)
    assert session is not None and session.csrf == csrf
    with stockage.transaction() as cnx:
        response = metier.executer(cnx, charger_departements(), session, "m7_proposer_campagne_locale", {
            "campagne_id": "flyer-fictif", "type_campagne": "flyer", "nom": "Flyers <fictifs>",
            "periode_debut": DATES["debut"], "periode_fin": DATES["fin"], "budget_cad": 100,
            "url_base": "https://exemple.invalid/flyers", "utm_source": "site", "utm_medium": "referral",
        }, mutation_id="campagne-fictive-1")
    assert response["ok"] is True and response["resultat"]["statut"] == "brouillon_propose", response


def _lecture(client):
    response = client.get("/api/marketing/cmo/couts", params={"campagne_id": "flyer-fictif", **DATES})
    assert response.status_code == 200, response.text
    return response.json()["resultat"]


def _charge(projection, cle="part-fictive-1", montant="60.00"):
    piece = projection["pieces_eligibles"][0]
    return {"mutation_id": cle, "arguments": {
        "facture_fournisseur_id": piece["facture_fournisseur_id"], "campagne_id": "flyer-fictif", **DATES,
        "devise": "CAD", "base": "HT", "montant_alloue_cad": montant, "motif": "Flyers fictifs",
        "sources_attendues": piece["sources_attendues"],
    }}


def _tables():
    with stockage.transaction() as cnx:
        return {table.name: cnx.execute(select(table)).all()
                for table in (REGISTRES, APPROBATIONS, JOURNAL, MUTATIONS_APPLIQUEES)}


def _post(client, csrf, charge):
    return client.post("/api/marketing/cmo/couts/affectations", json=charge, headers={"x-csrf-token": csrf})


def _corriger_ap(client, facture_id, montant="80.00"):
    session = securite.lire_session(client.cookies.get(securite.NOM_COOKIE), SECRET)
    deps = charger_departements()
    outil = next(o for o in deps["m05-financecore"].charger_outils()
                 if o.nom == "m5_corriger_facture_fournisseur")
    with stockage.transaction() as cnx:
        # La révision lue sur la facture au moment de proposer.
        (lue,) = [f for f in m5.comptes_a_payer.factures_saisies(m5._registre_comptes_a_payer())
                  if f["facture_fournisseur_id"] == facture_id]
        demande = approbations.creer_demande(cnx, "m05-financecore", outil.nom, {
            "facture_fournisseur_id": facture_id, "motif": "Correction tardive fictive",
            "numero_facture": None, "date_facture": None, "montant_avant_taxes": montant,
            "total_facture": None, "horodatage": "2026-10-02T14:00:00+00:00",
            "revision_attendue": lue["corrections"],
        }, niveau=approbations.Niveau.N4)
        decision = approbations.decider(cnx, demande, True, session.utilisateur, {outil.nom: outil}, deps)
    assert decision["statut"] == "executee", decision


def test_post_reel_n4_owner_rejeu_et_sources_durables(navigateur):
    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    charge = _charge(_lecture(navigateur))
    response = navigateur.post("/api/marketing/cmo/couts/affectations", json=charge, headers={"x-csrf-token": csrf})
    assert response.status_code == 200, response.text
    with stockage.transaction() as cnx:
        decision = cnx.execute(select(APPROBATIONS).where(
            APPROBATIONS.c.outil == "m5_affecter_cout_marketing",
        )).mappings().one()
        assert decision["niveau"] == "N4" and decision["decide_par"] == "owner.fictif"
        assert decision["statut"] == "executee"
        avant = cnx.execute(select(REGISTRES)).all()
    replay = navigateur.post("/api/marketing/cmo/couts/affectations", json=charge, headers={"x-csrf-token": csrf})
    assert replay.status_code == 200 and replay.json()["rejoue"] is True
    projection = _lecture(navigateur)
    assert projection["totaux_par_base"] == {"HT": "60.00", "TTC": None}
    assert projection["paiement_cad"] is None and projection["roi"] is None
    assert projection["affectations"][0]["valide_par"] == "owner.fictif"
    assert projection["affectations"][0]["affectation_id"] == "cout-" + decision["id"]
    with stockage.transaction() as cnx:
        assert cnx.execute(select(REGISTRES)).all() == avant
    charge["arguments"]["montant_alloue_cad"] = "50.00"
    assert navigateur.post("/api/marketing/cmo/couts/affectations", json=charge,
                           headers={"x-csrf-token": csrf}).status_code == 409


def test_rbac_csrf_et_html_sans_montants_non_autorises(navigateur):
    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    charge = _charge(_lecture(navigateur))
    assert navigateur.post("/api/marketing/cmo/couts/affectations", json=charge).status_code == 403
    csrf = _connecter(navigateur, "admin.fictif")
    assert navigateur.post("/api/marketing/cmo/couts/affectations", json=charge,
                           headers={"x-csrf-token": csrf}).status_code == 403
    assert _lecture(navigateur)["couverture"] == "INCONNUE"
    page = navigateur.get("/marketing/cmo/couts", params={"campagne_id": "flyer-fictif", **DATES})
    assert page.status_code == 200 and "Flyers &lt;fictifs&gt;" in page.text
    _connecter(navigateur, "employe.fictif")
    refus = navigateur.get("/api/marketing/cmo/couts", params={"campagne_id": "flyer-fictif", **DATES})
    assert refus.status_code == 403 and "114.98" not in refus.text


@pytest.mark.parametrize("changement", ["centimes", "plafond", "periode", "campagne", "devise", "reference_bool"])
def test_refus_metier_annule_demande_recu_journal_et_maillon(navigateur, changement):
    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    charge = _charge(_lecture(navigateur))
    args = charge["arguments"]
    if changement == "centimes":
        args["montant_alloue_cad"] = "0.001"
    elif changement == "plafond":
        args["montant_alloue_cad"] = "100.01"
    elif changement == "periode":
        args["fin"] = "2026-08-31"
    elif changement == "campagne":
        args["campagne_id"] = "inconnue-fictive"
    elif changement == "devise":
        args["devise"] = "USD"
    else:
        # bool == int ne constitue pas une preuve de version/head canonique.
        args["sources_attendues"]["ap"]["nombre"] = True
    avant = _tables()
    response = _post(navigateur, csrf, charge)
    assert response.status_code in {400, 409}, response.text
    assert "114.98" not in response.text
    assert _tables() == avant


def test_revision_retrait_et_recu_historique_apres_correction_tardive(navigateur):
    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    charge = _charge(_lecture(navigateur))
    original = _post(navigateur, csrf, charge)
    assert original.status_code == 200, original.text
    _corriger_ap(navigateur, charge["arguments"]["facture_fournisseur_id"])
    projection = _lecture(navigateur)
    part = projection["affectations"][0]
    assert part["statut"] == "PERIMEE_SOURCE_AP" and projection["totaux_par_base"]["HT"] is None
    avant = _tables()
    replay = _post(navigateur, csrf, charge)
    assert replay.status_code == 200 and replay.json()["nature_recu"] == "HISTORIQUE"
    assert _tables() == avant
    supplement = _charge(projection, "supplement-fictif-1", "30.00")
    assert _post(navigateur, csrf, supplement).status_code == 409
    assert _tables() == avant
    revision = copy.deepcopy(charge)
    revision["mutation_id"] = "revision-fictive-1"
    revision["arguments"].update(affectation_id=part["affectation_id"], montant_alloue_cad="50.00",
                                 sources_attendues=part["sources_courantes"])
    assert _post(navigateur, csrf, revision).status_code == 200
    projection = _lecture(navigateur)
    assert projection["totaux_par_base"]["HT"] == "50.00"
    part = projection["affectations"][0]
    assert part["version"] == 2 and part["statut"] == "COURANTE"
    retrait = {"mutation_id": "retrait-fictif-1", "arguments": {
        "affectation_id": part["affectation_id"], "version_attendue": 2,
        "snapshot_attendu": projection["observation_source"]["affectations"], "motif": "Retrait fictif",
    }}
    response = navigateur.post("/api/marketing/cmo/couts/retraits", json=retrait, headers={"x-csrf-token": csrf})
    assert response.status_code == 200, response.text
    projection = _lecture(navigateur)
    assert projection["affectations"][0]["statut"] == "RETIREE"
    assert projection["totaux_par_base"]["HT"] is None
    assert _post(navigateur, csrf, _charge(projection, "nouvelle-part-fictive", "80.00")).status_code == 200
    assert _lecture(navigateur)["totaux_par_base"]["HT"] == "80.00"


@pytest.mark.parametrize("registre", ["comptes_a_payer", "couts_marketing_affectes", "local_campaigns"])
def test_tamper_source_refuse_avant_montants_et_sans_ecriture(navigateur, registre):
    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    assert _post(navigateur, csrf, _charge(_lecture(navigateur))).status_code == 200
    with stockage.transaction() as cnx:
        filtre = REGISTRES.c.registre == registre
        brut = cnx.execute(select(REGISTRES.c.maillon).where(filtre, REGISTRES.c.rang == 0)).scalar_one()
        maillon = codec.decoder(brut)
        if registre == "local_campaigns":
            maillon["nom"] = "Tamper fictif"
        elif registre == "couts_marketing_affectes":
            maillon["montant_alloue_cad"] = "99.00"
        else:
            maillon["numero_facture"] = "Tamper fictif"
        cnx.execute(update(REGISTRES).where(filtre, REGISTRES.c.rang == 0).values(maillon=codec.encoder(maillon)))
    avant = _tables()
    refusee = navigateur.get("/api/marketing/cmo/couts", params={"campagne_id": "flyer-fictif", **DATES})
    assert refusee.status_code == 409 and "114.98" not in refusee.text and "60.00" not in refusee.text
    assert _tables() == avant


@pytest.mark.parametrize("moment", ["port", "apres_append", "journal"])
def test_revalidation_et_panne_annulent_toute_ecriture(navigateur, monkeypatch, moment):
    from m7_marketing import local

    from opsys.console import couts_marketing as console

    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    charge = _charge(_lecture(navigateur))
    avant = _tables()
    appels = []
    if moment == "port":
        originale = local.lire

        def lire(ident):
            resultat = originale(ident)
            appels.append("source_reelle_lue")
            identite.retirer_role(stockage.connexion_courante(), "owner.fictif", "nathan_owner")
            return resultat

        monkeypatch.setattr(local, "lire", lire)
    elif moment == "apres_append":
        originale = stockage.MaillonsDurables.append

        def ajouter(self, maillon, **kwargs):
            originale(self, maillon, **kwargs)
            if self.registre == "couts_marketing_affectes":
                appels.append("maillon_reel_insere")
                identite.retirer_role(stockage.connexion_courante(), "owner.fictif", "nathan_owner")

        monkeypatch.setattr(stockage.MaillonsDurables, "append", ajouter)
    else:
        def journal(*_args, **_kwargs):
            appels.append("journal_final")
            raise ValueError("panne_fictive_journal")

        monkeypatch.setattr(console, "journaliser", journal)
    response = _post(navigateur, csrf, charge)
    assert response.status_code == (409 if moment == "journal" else 403), response.text
    assert appels and _tables() == avant
    assert "60.00" not in response.text


def test_role_retire_au_rejeu_refuse_sans_nouveau_recu(navigateur):
    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    charge = _charge(_lecture(navigateur))
    assert _post(navigateur, csrf, charge).status_code == 200
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "owner.fictif", "nathan_owner")
    avant = _tables()
    refus = _post(navigateur, csrf, charge)
    assert refus.status_code == 403 and "60.00" not in refus.text
    assert _tables() == avant


def test_identite_console_ne_remplace_pas_decision_n4(navigateur):
    from opsys.outils import executer_atomique

    _connecter(navigateur)
    outil = next(o for o in charger_departements()["m05-financecore"].charger_outils(
        ports_prives={"lecteur_campagne_m7": lambda _: pytest.fail("port jamais lu sans N4")},
    ) if o.nom == "m5_affecter_cout_marketing")
    with stockage.transaction() as cnx, contexte.appele_par_appareil(
        contexte.IdentiteAppelante("owner.fictif", "nathan_owner", "console"),
    ):
        response = executer_atomique(outil, _charge({"pieces_eligibles": [{
            "facture_fournisseur_id": "fictive", "sources_attendues": {},
        }]})["arguments"])
        assert response["ok"] is False and "OWNER-N4-REQUIS" in response["details"]
        assert cnx.execute(select(REGISTRES).where(REGISTRES.c.registre == "couts_marketing_affectes")).all() == []


def test_ancienne_demande_n3_ne_devient_pas_n4(navigateur):
    from opsys.console import couts_marketing as console

    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    charge = _charge(_lecture(navigateur))
    session = securite.lire_session(navigateur.cookies.get(securite.NOM_COOKIE), SECRET)
    deps = charger_departements()
    with stockage.transaction() as cnx:
        outil = console._outil_prive(cnx, deps, session, "m5_affecter_cout_marketing")
        demande = approbations.creer_demande(cnx, "m05-financecore", outil.nom, charge["arguments"],
                                            niveau=approbations.Niveau.N3)
        decision = approbations.decider(cnx, demande, True, session.utilisateur, {outil.nom: outil}, deps)
        assert decision["statut"] == "echec" and "OWNER-N4-REQUIS" in decision["reponse"]["details"]
        assert cnx.execute(select(REGISTRES).where(REGISTRES.c.registre == "couts_marketing_affectes")).all() == []


def test_backend_non_sqlite_refuse_avant_lecture_du_port(navigateur, monkeypatch):
    from opsys.outils import executer_atomique

    appels = []
    outil = next(o for o in charger_departements()["m05-financecore"].charger_outils(
        ports_prives={"lecteur_campagne_m7": lambda _: appels.append("interdit")},
    ) if o.nom == "m5_lire_couts_marketing_affectes")
    avant = _tables()
    # Contrat de refus du dialecte, pas une preuve d'exécution PostgreSQL.
    with stockage.transaction() as cnx, monkeypatch.context() as patch:
        patch.setattr(cnx.dialect, "name", "postgresql")
        response = executer_atomique(outil, {"campagne_id": "flyer-fictif", **DATES})
    assert response["ok"] is False and "BACKEND-NON-PRIS-EN-CHARGE" in response["details"]
    assert appels == [] and _tables() == avant


@pytest.mark.parametrize("genre", ["octets_utf8", "profondeur", "noeuds", "codec_invalide", "inf_exposant"])
def test_sql_json_bornes_et_codec_ferment_sans_montants(navigateur, monkeypatch, genre):
    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    if genre == "octets_utf8":
        brut = json.dumps({"non_decode": "é" * 40_000}, ensure_ascii=False)
    elif genre == "profondeur":
        valeur = "fictif"
        for _ in range(18):
            valeur = [valeur]
        brut = json.dumps({"non_decode": valeur})
    elif genre == "noeuds":
        brut = json.dumps({"non_decode": [0] * 2050})
    elif genre == "inf_exposant":
        brut = '{"non_decode":1e999}'
    else:
        brut = '{"__opsys__":"dict","items":null}'
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(REGISTRES.c.registre == "comptes_a_payer").values(maillon=brut))
    avant = _tables()
    with monkeypatch.context() as patch:
        if genre != "codec_invalide":
            patch.setattr(codec, "decoder", lambda _: pytest.fail("restauration avant contrôle des bornes"))
        refusee = navigateur.get("/api/marketing/cmo/couts", params={"campagne_id": "flyer-fictif", **DATES})
    assert refusee.status_code == 409 and "114.98" not in refusee.text
    assert _tables() == avant


def test_role_retire_apres_lecture_refuse_avant_serialisation(navigateur, monkeypatch):
    from m7_marketing import local

    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    originale = local.lire
    appels = []

    def lire(ident):
        resultat = originale(ident)
        appels.append(ident)
        identite.retirer_role(stockage.connexion_courante(), "owner.fictif", "nathan_owner")
        return resultat

    monkeypatch.setattr(local, "lire", lire)
    avant = _tables()
    refusee = navigateur.get("/api/marketing/cmo/couts", params={"campagne_id": "flyer-fictif", **DATES})
    assert refusee.status_code == 403 and "114.98" not in refusee.text and appels == ["flyer-fictif"]
    assert _tables() == avant


def test_formulaire_rendu_affectation_revision_retrait(navigateur):
    class Formulaires(HTMLParser):
        def __init__(self):
            super().__init__()
            self.champs = None
            self.commandes = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "form":
                self.champs = {} if attrs.get("action", "").endswith("/cmo/couts/affectations") else None
            elif tag == "input" and self.champs is not None and attrs.get("name"):
                self.champs[attrs["name"]] = attrs.get("value", "")

        def handle_endtag(self, tag):
            if tag == "form" and self.champs is not None:
                self.commandes.append(self.champs)
                self.champs = None

    def formulaires():
        response = navigateur.get("/marketing/cmo/couts", params={"campagne_id": "flyer-fictif", **DATES})
        assert response.status_code == 200, response.text
        parseur = Formulaires()
        parseur.feed(response.text)
        return parseur.commandes

    csrf = _connecter(navigateur)
    _campagne(navigateur, csrf)
    form = formulaires()[0] | {"base": "HT", "devise": "CAD", "montant_alloue_cad": "60.00", "motif": "Fictif"}
    assert form["csrf"] == csrf and "sources_attendues" in form
    response = navigateur.post("/marketing/cmo/couts/affectations", data=form, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert _lecture(navigateur)["totaux_par_base"]["HT"] == "60.00"
    revision = formulaires()[0] | {"base": "HT", "devise": "CAD", "montant_alloue_cad": "50.00"}
    assert revision["affectation_id"] and revision["sources_attendues"] != form["sources_attendues"]
    response = navigateur.post("/marketing/cmo/couts/affectations", data=revision, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert _lecture(navigateur)["affectations"][0]["version"] == 2
    retrait = next(f for f in formulaires() if f["action"] == "retirer") | {"motif": "Retrait fictif"}
    response = navigateur.post("/marketing/cmo/couts/affectations", data=retrait, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert _lecture(navigateur)["totaux_par_base"]["HT"] is None
