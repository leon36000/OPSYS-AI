"""Parcours HTTP réel du dossier de paie préparatoire : M4 → admission → composition → revue → export (fictif).

Application FastAPI intégrée (session signée, CSRF, SQLite migrée), vraies heures M4 validées par approbation N4,
vrai contrat M5, vrais moteurs RRQ/QC/RQAP-AE/fédéral et vrai dispatcher d'outils. Les seules substitutions sont les
captures PDF de l'admission (PDF FICTIFS dont l'empreinte est épinglée dans une copie de la configuration serveur).
"""

from __future__ import annotations

import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import approbations, contexte, identite, stockage
from opsys.console import application, metier, paie_dossier_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements, lire_manifeste
from opsys.outils import executer_atomique
from opsys.stockage.schema import META, REGISTRES

ROOT = Path(__file__).resolve().parents[1]
for chemin in (
    ROOT / "departments/m04-field-ops/src",
    ROOT / "departments/m05-financecore/src",
    ROOT / "departments/m05-financecore/tests",
):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from fixtures_dossier_paie import entrees as fabrique_entrees  # noqa: E402

FICTIF = True
SECRET = "secret-console-dossier-paie-test-" + "x" * 32
PREFIXE = "/opsys"
OWNER, EMPLOYEE, AUTRE_EMPLOYEE = "owner-dossier-fictif", "employe-dossier-fictif", "employe-dossier-fictif-2"
MDP = {
    "owner": "owner-dossier-fictif-password",
    "admin": "admin-dossier-password",
    "manager": "manager-dossier-password",
    "employee": "employe-dossier-fictif-password",
    "finance": "finance-dossier-password",
}
PREMIERE_PAIE = "2026-01-15"
# (période annuelle, début, fin, date de paie, jours de pointage (jour, heures)) → minutes, brut à 31.25 $/h
PERIODES = {
    1: ("2026-01-01", "2026-01-14", "2026-01-15", [("2026-01-06", 8)]),  # 480 min → 250.00
    20: ("2026-09-21", "2026-10-04", "2026-10-08", [("2026-09-22", 3), ("2026-09-24", 2)]),  # 300 min → 156.25
    21: ("2026-10-05", "2026-10-18", "2026-10-22", [("2026-10-06", 4)]),  # 240 min → 125.00
}
BRUT = {1: "250.00", 20: "156.25", 21: "125.00"}
CUMULS_P20 = {
    "salaire_rrq_cumul_avant": "4750.00",
    "rrq_palier1_cumul_avant": "250.00",
    "rrq_palier2_cumul_avant": "0.00",
    "rqap_salarie_cumul_avant": "20.00",
    "rqap_employeur_cumul_avant": "28.00",
    "ae_salarie_cumul_avant": "62.00",
    "ae_employeur_cumul_avant": "86.00",
}


def _installer_captures_fictives(tmp_path, monkeypatch):
    """Copie de la configuration serveur dont les PDF sont des fichiers FICTIFS (empreintes recalculées)."""
    import m5_financecore.outils as m5_outils

    config = json.loads(m5_outils._CHEMIN_ADMISSION_PAIE.read_text(encoding="utf-8"))
    racine = tmp_path / "captures-fictives"
    racine.mkdir()
    for cle, source in config["capacite"]["sources"].items():
        octets = b"%PDF-1.7\n% capture fictive " + cle.encode() + b"\n"
        (racine / source["capture"]).write_bytes(octets)
        source["sha256"] = hashlib.sha256(octets).hexdigest()
    chemin = tmp_path / "admission-fictive.json"
    chemin.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_CHEMIN_ADMISSION_PAIE", chemin)
    monkeypatch.setattr(m5_outils, "_RACINE_CAPTURES_ADMISSION_PAIE", racine)


def _pointer(registre, employee, jour, heures, intervention):
    debut_h = 13
    for maillon in (
        {
            "type_entree": "transition_statut",
            "intervention_id": intervention,
            "statut": "en_route",
            "horodatage": f"{jour}T12:45:00+00:00",
        },
        {
            "type_entree": "pointage",
            "intervention_id": intervention,
            "technicien_id": employee,
            "action": "arrivee",
            "horodatage": f"{jour}T{debut_h}:00:00+00:00",
        },
        {
            "type_entree": "pointage",
            "intervention_id": intervention,
            "technicien_id": employee,
            "action": "depart",
            "horodatage": f"{jour}T{debut_h + heures}:00:00+00:00",
        },
    ):
        registre.ajouter(maillon)


def _valider_heures(session, outils_m4, employee, debut, fin, *, motif="Validation paie fictive."):
    args = {"technicien_id": employee, "debut": debut, "fin": fin, "fuseau": "America/Montreal"}
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante(OWNER, "admin")),
        contexte.appeler_en_tant_que("m04-field-ops", origine="m04-field-ops"),
    ):
        preview = executer_atomique(outils_m4["m4_previsualiser_heures_regulieres"], args)
    assert preview["resultat"]["accepte"] is True, preview
    proposition = preview["resultat"]["resultat"]
    validation = {
        **args,
        "empreinte_sources": proposition["empreinte_sources"],
        "categories_minutes": proposition["categories_minutes"],
        "details_intervalles": proposition["details_intervalles"],
        "sources": proposition["sources"],
        "validation_precedente_attendue": proposition["validation_precedente"],
        "couverture_complete": True,
        "classification_reguliere_confirmee": True,
        "dispositions": {
            c: {"inclure": c == "travail", "source": "Décision humaine fictive"}
            for c in ("travail", "deplacement", "pause")
        },
        "motif_correction": motif,
    }
    with session() as cnx:
        demande = approbations.creer_demande(
            cnx,
            "m04-field-ops",
            "m4_valider_heures_regulieres",
            validation,
            niveau=approbations.Niveau.N4,
        )
        decision = approbations.decider(
            cnx,
            demande,
            True,
            OWNER,
            outils_m4,
            {"m04-field-ops": lire_manifeste(ROOT / "departments/m04-field-ops")},
        )
    assert decision["statut"] == "executee", decision


@pytest.fixture
def env(session, tmp_path, monkeypatch):
    import m5_financecore.outils as m5_outils
    from m4_field_ops import registre as registre_m4
    from m4_field_ops.outils import outils as fabrique_m4
    from m5_financecore.outils import outils as fabrique_m5

    m5_outils.utiliser_stockage_durable()
    _installer_captures_fictives(tmp_path, monkeypatch)
    with session() as cnx:
        identite.creer_personne(cnx, OWNER, "Owner fictif", MDP["owner"], ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "admin-dossier-fictif", "Admin fictif", MDP["admin"], ["admin"])
        identite.creer_personne(cnx, "manager-dossier-fictif", "Manager fictif", MDP["manager"], ["manager"])
        identite.creer_personne(cnx, "finance-dossier-fictif", "Finance fictive", MDP["finance"], ["finance"])
        identite.creer_personne(cnx, EMPLOYEE, "Employé fictif un", MDP["employee"], ["employee"])
        identite.creer_personne(cnx, AUTRE_EMPLOYEE, "Employé fictif deux", MDP["employee"], ["employee"])
    registre = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
    for periode, (_, _, _, jours) in PERIODES.items():
        for k, (jour, heures) in enumerate(jours):
            _pointer(registre, EMPLOYEE, jour, heures, f"I-dossier-{periode}-{k}")
    deps = charger_departements()
    outils_m4 = {o.nom: o for o in fabrique_m4()}
    for debut, fin, _, _ in PERIODES.values():
        _valider_heures(session, outils_m4, EMPLOYEE, debut, fin)
    outils_m5 = {o.nom: o for o in fabrique_m5(lecteur_heures_m4=lambda *_a: {})}
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(OWNER, "admin")):
        contrat = executer_atomique(
            outils_m5["m5_enregistrer_contrat_horaire"],
            {
                "employee_person_id": EMPLOYEE,
                "contrat_id": "CONTRAT-DOSSIER-FICTIF",
                "valide_du": "2026-01-01",
                "valide_jusqu_au": "2026-12-31",
                "fuseau": "America/Montreal",
                "devise": "CAD",
                "taux_horaire": "31.25",
                "source_humaine": "Contrat fictif DOSSIER-001",
                "date_source": "2025-12-31",
                "revision_attendue": 0,
                "ligne_id_attendue": "",
                "motif": "Enregistrement fictif de test.",
            },
        )
    assert contrat["resultat"]["accepte"] is True, contrat
    app = application.creer_application(Configuration(SECRET, cookie_securise=False), deps, session)
    return {"app": app, "session": session, "deps": deps, "outils_m4": outils_m4, "registre_m4": registre}


@pytest.fixture
def client(env):
    with TestClient(env["app"], base_url=f"http://testserver{PREFIXE}") as c:
        yield c


def connecter(client, role="owner", identifiant=OWNER):
    retour = client.post(
        "/connexion", data={"identifiant": identifiant, "mot_de_passe": MDP[role]}, follow_redirects=False
    )
    assert retour.status_code == 303, retour.text
    return client.get("/api/session").json()["csrf"]


def entrees_periode(periode, **kw):
    debut, fin, paie, _ = PERIODES[periode]
    base = dict(premiere=PREMIERE_PAIE, debut=debut, fin=fin, date_paie=paie)
    if periode == 1:
        return fabrique_entrees(1, **base, **kw)
    return fabrique_entrees(periode, **base, cumuls=dict(CUMULS_P20), origine="DECLARE_HISTORIQUE", **kw)


def api(client, csrf, chemin, corps, *, methode="post"):
    entetes = {"x-csrf-token": csrf}
    appel = getattr(client, methode)
    return appel(
        f"/api/finance/paie/dossiers{chemin}", **({"json": corps, "headers": entetes} if methode == "post" else {})
    )


def apercu(client, csrf, entrees, employe=EMPLOYEE):
    reponse = api(client, csrf, "/apercu", {"employee_person_id": employe, "entrees": entrees})
    assert reponse.status_code == 200, reponse.text
    return reponse.json()["resultat"]


def conserver(
    client,
    csrf,
    entrees,
    resultat_apercu,
    *,
    attendue=0,
    type_version="CREATION",
    mutation=None,
    motif="",
    employe=EMPLOYEE,
):
    mutation = (
        mutation
        or hashlib.sha256(f"{attendue}{motif}{type_version}{resultat_apercu['empreinte_apercu']}".encode()).hexdigest()[
            :32
        ]
    )
    return api(
        client,
        csrf,
        "/conserver",
        {
            "employee_person_id": employe,
            "entrees": entrees,
            "empreinte_apercu": resultat_apercu["empreinte_apercu"],
            "version_attendue": attendue,
            "type_version": type_version,
            "motif": motif,
            "mutation_id": mutation,
        },
    )


def instantane(cnx):
    """Empreinte de CHAQUE table (lignes triées) : le périmètre d'écriture doit être exact."""
    resultat = {}
    for nom, table in META.tables.items():
        lignes = sorted(repr(tuple(ligne)) for ligne in cnx.execute(select(table)).all())
        resultat[nom] = (len(lignes), hashlib.sha256("\n".join(lignes).encode()).hexdigest())
    return resultat


def registres(cnx):
    compte = {}
    for ligne in cnx.execute(select(REGISTRES.c.departement, REGISTRES.c.registre)).all():
        compte[tuple(ligne)] = compte.get(tuple(ligne), 0) + 1
    return compte


def lire_etat(env):
    with env["session"]() as cnx:
        return instantane(cnx), registres(cnx)


# ===================================================================== parcours nominal


def test_parcours_complet_p1_et_periodes_suivantes_sans_ecriture_financiere(env, client, monkeypatch):
    original = metier.executer

    def trace(*a, **k):
        r = original(*a, **k)
        print("EXEC", a[3], str(r)[:600])
        return r

    monkeypatch.setattr(metier, "executer", trace)
    csrf = connecter(client)
    tables_avant, regs_avant = lire_etat(env)
    page = client.get("/finance/paie/dossiers")
    assert page.status_code == 200 and "Préparer un nouveau dossier" in page.text
    assert "no-store" in page.headers["cache-control"]
    assert "/finance/paie/dossiers" in client.get("/finance/paie").text

    # --- Période 1 : aperçu (rien n'est conservé), puis version 1.
    e1 = entrees_periode(1)
    ap1 = apercu(client, csrf, e1)
    assert lire_etat(env) == (tables_avant, regs_avant)
    calcul = ap1["version"]["calcul"]
    assert (
        ap1["conservable"] is True
        and calcul["etat"] == "COMPOSE_PREPARATOIRE"
        and ap1["version"]["admission"]["admissible"]
    )
    assert ap1["mention"].startswith("Analyse préparatoire IA")
    assert ap1["version"]["sources"]["brut"]["brut_brouillon"] == BRUT[1]
    assert ap1["version"]["sources"]["heures_m4"]["minutes_regulieres"] == 480
    postes = {p["id"]: p for p in calcul["matrice"]}
    assert postes["rrq_employe"]["montant"] == "7.27"  # 6,3 % × (250,00 − 134,61), arrondi au cent
    recu1 = conserver(client, csrf, e1, ap1)
    assert recu1.status_code == 200, recu1.text
    r1 = recu1.json()["resultat"]
    assert r1["numero"] == 1 and r1["etat_calcul"] == "COMPOSE_PREPARATOIRE" and "montant" not in json.dumps(r1)
    # Le reçu (seul élément conservé en clair par l'idempotence partagée) ne contient aucun montant ni identité.
    with env["session"]() as cnx:
        reponses = cnx.execute(select(META.tables["mutations_appliquees"].c.reponse)).scalars().all()
    assert all("250.00" not in str(r) and EMPLOYEE not in str(r) for r in reponses)

    # --- Version courante lisible; totaux justifiés par l'oracle indépendant.
    d1 = r1["dossier_id"]
    lu = client.get(f"/api/finance/paie/dossiers/{d1}").json()["resultat"]
    totaux = lu["version"]["calcul"]["totaux"]
    retenues = sum(
        Fraction(postes[i]["montant"])
        for i in (
            "rrq_employe",
            "impot_quebec",
            "rqap_employe",
            "ae_employe",
            "impot_federal",
            "autres_retenues_employe",
        )
    )
    assert Fraction(totaux["retenues_employe"]["montant"]) == retenues
    assert Fraction(totaux["net_preparatoire"]["montant"]) == Fraction(BRUT[1]) - retenues
    assert totaux["das_complete"]["etat"] == "CALCULE" and totaux["cout_employeur_global"]["etat"] == "CALCULE"

    # --- Période 20 avec cumuls déclarés; oracles indépendants pour RQAP/AE (taux × assiette, arrondi demi supérieur).
    e20 = entrees_periode(20)
    ap20 = apercu(client, csrf, e20)
    p20 = {p["id"]: p for p in ap20["version"]["calcul"]["matrice"]}
    assert ap20["version"]["sources"]["brut"]["brut_brouillon"] == BRUT[20]
    assert p20["rqap_employe"]["montant"] == "0.67" and p20["rqap_employeur"]["montant"] == "0.94"
    assert p20["ae_employe"]["montant"] == "2.03" and p20["ae_employeur"]["montant"] == "2.84"
    assert p20["rrq_employe"]["montant"] == "1.36" == p20["rrq_employeur"]["montant"]
    r20 = conserver(client, csrf, e20, ap20).json()["resultat"]
    assert r20["numero"] == 1 and r20["dossier_id"] != d1

    # --- Revue, export, réouverture, correction, comparaison.
    rev = api(
        client,
        csrf,
        f"/{r20['dossier_id']}/revue",
        {
            "numero": 1,
            "hash_version": r20["hash_version"],
            "decision": "REVUE_COMPLETEE",
            "note": "Revue interne fictive.",
            "mutation_id": "a" * 32,
        },
    )
    assert rev.status_code == 200 and rev.json()["resultat"]["decision"] == "REVUE_COMPLETEE"
    exp = api(
        client,
        csrf,
        f"/{r20['dossier_id']}/export",
        {
            "numero": 1,
            "hash_version": r20["hash_version"],
            "format_export": "json",
            "mutation_id": "b" * 32,
        },
    )
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"]
    assert exp.headers["x-content-type-options"] == "nosniff" and "no-store" in exp.headers["cache-control"]
    export_json = json.loads(exp.content)
    assert export_json["mode"] == "PREPARATOIRE" and export_json["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert hashlib.sha256(exp.content).hexdigest() == exp.headers["x-export-sha256"]
    assert (
        export_json["heures_et_brut"]["heures_regulieres"] == "5:00"
        and export_json["totaux"]["das_complete"]["etat"] == "CALCULE"
    )

    # --- Aucune table financière, aucune base M4/M5 principale n'a bougé; seuls les registres/clés/journaux du dossier.
    tables_apres, regs_apres = lire_etat(env)
    changees = {t for t in tables_apres if tables_apres[t] != tables_avant[t]}
    assert changees <= {"registres_maillons", "cles_chiffrement", "mutations_appliquees", "journal"}, changees
    nouveaux = {k: v for k, v in regs_apres.items() if regs_avant.get(k) != v}
    assert set(nouveaux) == {("m05-financecore", "dossiers_paie_preparatoires")}
    for intact in (
        ("m04-field-ops", "principal"),
        ("m05-financecore", "principal"),
        ("m05-financecore", "factures"),
        ("m05-financecore", "contrats_salaries_horaires"),
    ):
        assert regs_apres.get(intact, 0) == regs_avant.get(intact, 0), intact


# ===================================================================== parcours par formulaires HTML


def champs_formulaire(employe, entrees):
    valeurs = paie_dossier_ui.valeurs_depuis_entrees(employe, entrees)
    donnees = {}
    for cle, valeur in valeurs.items():
        if valeur is True:
            donnees[cle] = "on"
        elif valeur is False or valeur is None:
            continue
        else:
            donnees[cle] = str(valeur)
    return donnees


def extraire(page, nom):
    import html
    import re

    trouve = re.search(rf'name="{nom}" value="([^"]*)"', page)
    assert trouve, f"champ {nom} absent"
    return html.unescape(trouve.group(1))


def post_form(client, chemin, donnees, csrf, **extra):
    return client.post(chemin, data={**donnees, "csrf": csrf, **extra}, follow_redirects=False)


@pytest.mark.parametrize("periode", [1, 20])
@pytest.mark.parametrize("employeur", [True, False])
def test_formulaire_aller_retour_exact(periode, employeur):
    e = entrees_periode(periode, employeur=employeur)
    e["autres_retenues_employe"] = None if not employeur else e["autres_retenues_employe"]
    employe, retour = paie_dossier_ui.entrees_depuis_formulaire(champs_formulaire(EMPLOYEE, e))
    assert employe == EMPLOYEE and retour == e


def test_formulaire_refuse_champ_inattendu_et_ne_fabrique_aucun_defaut():
    donnees = champs_formulaire(EMPLOYEE, entrees_periode(1))
    with pytest.raises(Exception) as exc:
        paie_dossier_ui.entrees_depuis_formulaire({**donnees, "role": "nathan_owner"})
    assert getattr(exc.value, "status_code", None) == 400
    # Un champ vidé reste vide (donc invalide), il n'est jamais remplacé par une valeur par défaut.
    donnees["tc"] = ""
    _, e = paie_dossier_ui.entrees_depuis_formulaire(donnees)
    assert e["credits_federal"]["TC"] == "" and e["employeur_reference"] == "employeur-fictif"
    donnees["employeur_reference"] = ""
    assert paie_dossier_ui.entrees_depuis_formulaire(donnees)[1]["employeur_reference"] == ""


def test_parcours_formulaires_correction_comparaison_revue_reouverture_et_periode_suivante(env, client):
    csrf = connecter(client)
    nouveau = client.get("/finance/paie/dossiers/nouveau")
    assert nouveau.status_code == 200 and 'name="employee_person_id"' in nouveau.text
    assert "Calculer l'aperçu" in nouveau.text and 'name="att_emploi_continu"' in nouveau.text
    e20 = entrees_periode(20)
    e20["arrondi"]["hypothese"] = "Hypothèse <script>alert(1)</script> fictive"
    page = post_form(client, "/finance/paie/dossiers/apercu", champs_formulaire(EMPLOYEE, e20), csrf, action="apercu")
    assert page.status_code == 200, page.text
    assert "COMPOSE_PREPARATOIRE" in page.text and "NON_QUALIFIEE_POUR_PAIE" in page.text
    assert "Conserver cette version" in page.text and "<script>alert(1)</script>" not in page.text
    assert (
        "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    )  # l'hypothèse saisie revient échappée dans le formulaire
    assert "no-store" in page.headers["cache-control"]
    envoi = {
        n: extraire(page.text, n)
        for n in (
            "employee_person_id",
            "empreinte_apercu",
            "version_attendue",
            "type_version",
            "entrees_json",
            "mutation_id",
        )
    }
    retour = post_form(client, "/finance/paie/dossiers/conserver", envoi, csrf, motif="création fictive")
    assert retour.status_code == 303, retour.text
    chemin = retour.headers["location"].removeprefix(PREFIXE)
    d20 = chemin.rsplit("/", 1)[1]
    fiche = client.get(chemin)
    assert fiche.status_code == 200 and "EN_PREPARATION" in fiche.text and "Revue interne" in fiche.text
    assert "<script>" not in fiche.text

    # --- Correction : formulaire pré-rempli depuis la version courante, nouvelle version, comparaison lisible.
    corr = client.get(f"/finance/paie/dossiers/nouveau?depuis={d20}&mode=correction")
    assert (
        corr.status_code == 200
        and 'value="16452.00"' in corr.text
        and 'name="type_version" value="CORRECTION"' in corr.text
    )
    e20b = json.loads(json.dumps(e20))
    e20b["credits_federal"]["TC"] = "17000.00"
    donnees = champs_formulaire(EMPLOYEE, e20b)
    donnees.update(version_attendue="1", type_version="CORRECTION")
    page2 = post_form(client, "/finance/paie/dossiers/apercu", donnees, csrf, action="apercu")
    assert page2.status_code == 200 and 'value="CORRECTION"' in page2.text
    envoi2 = {
        n: extraire(page2.text, n)
        for n in (
            "employee_person_id",
            "empreinte_apercu",
            "version_attendue",
            "type_version",
            "entrees_json",
            "mutation_id",
        )
    }
    assert envoi2["version_attendue"] == "1" and envoi2["type_version"] == "CORRECTION"
    assert post_form(client, "/finance/paie/dossiers/conserver", envoi2, csrf, motif="TD1 corrigé").status_code == 303
    comp = client.get(f"/finance/paie/dossiers/{d20}?v=2&comparer=1")
    assert comp.status_code == 200 and "credits_federal.TC" in comp.text and "Comparaison v1 → v2" in comp.text
    assert "17000.00" in comp.text and "16452.00" in comp.text
    # L'ancienne version reste affichable, inchangée.
    assert "16452.00" in client.get(f"/finance/paie/dossiers/{d20}?v=1").text

    # --- Revue du hash courant, correction bloquée tant que le dossier est revu, puis réouverture explicite.
    lu = client.get(f"/api/finance/paie/dossiers/{d20}").json()["resultat"]
    courant = lu["dossier"]["versions"][-1]
    revue = post_form(
        client,
        f"/finance/paie/dossiers/{d20}/revue",
        {
            "numero": "2",
            "hash_version": courant["hash_version"],
            "decision": "REVUE_COMPLETEE",
            "note": "ok <b>gras</b>",
            "mutation_id": "c" * 32,
        },
        csrf,
    )
    assert revue.status_code == 303
    fiche = client.get(f"/finance/paie/dossiers/{d20}")
    assert (
        "REVUE_COMPLETEE" in fiche.text
        and "Exporter pour le professionnel" in fiche.text
        and "<b>gras</b>" not in fiche.text
    )
    refus = post_form(client, "/finance/paie/dossiers/apercu", donnees, csrf, action="apercu")
    envoi3 = {n: extraire(refus.text, n) for n in ("employee_person_id", "empreinte_apercu", "entrees_json")}
    bloque = post_form(
        client,
        "/finance/paie/dossiers/conserver",
        {
            **envoi3,
            "version_attendue": "2",
            "type_version": "CORRECTION",
            "mutation_id": "d" * 32,
        },
        csrf,
        motif="x",
    )
    assert bloque.status_code == 409 and "REJ-DOSSIER-PAIE-DOSSIER-REVU" in bloque.text
    mauvais = post_form(
        client,
        f"/finance/paie/dossiers/{d20}/rouvrir",
        {
            "numero": "1",
            "hash_version": courant["hash_version"],
            "motif": "x",
            "mutation_id": "e" * 32,
        },
        csrf,
    )
    assert mauvais.status_code == 409
    assert (
        post_form(
            client,
            f"/finance/paie/dossiers/{d20}/rouvrir",
            {
                "numero": "2",
                "hash_version": courant["hash_version"],
                "motif": "TD1 à revoir",
                "mutation_id": "f" * 32,
            },
            csrf,
        ).status_code
        == 303
    )
    assert "ROUVERT" in client.get(f"/finance/paie/dossiers/{d20}").text

    # --- Période suivante : cumuls simulés depuis la version courante, jamais ceux saisis.
    suiv = client.get(f"/finance/paie/dossiers/nouveau?depuis={d20}&mode=suivante")
    assert suiv.status_code == 200 and 'name="sim_dossier_id"' in suiv.text and 'value="21"' in suiv.text
    donnees21 = {n: extraire(suiv.text, n) for n in ("sim_dossier_id", "sim_numero", "sim_hash")}
    form21 = champs_formulaire(EMPLOYEE, entrees_periode(21, employeur=True))
    form21.update(cumuls_origine="SIMULE_VERSION_PRECEDENTE", **donnees21)
    page21 = post_form(client, "/finance/paie/dossiers/apercu", form21, csrf, action="apercu")
    assert page21.status_code == 200, page21.text
    assert "COMPOSE_PREPARATOIRE" in page21.text and "jamais un versement" in page21.text
    envoi21 = {
        n: extraire(page21.text, n)
        for n in (
            "employee_person_id",
            "empreinte_apercu",
            "version_attendue",
            "type_version",
            "entrees_json",
            "mutation_id",
        )
    }
    ok21 = post_form(client, "/finance/paie/dossiers/conserver", envoi21, csrf, motif="")
    assert ok21.status_code == 303
    d21 = ok21.headers["location"].rsplit("/", 1)[1]
    v21 = client.get(f"/api/finance/paie/dossiers/{d21}").json()["resultat"]["version"]
    assert v21["entrees"]["cumuls_avant"]["origine"] == "SIMULE_VERSION_PRECEDENTE"
    # Cumuls hypothétiques = cumuls avant de P20 + postes de la version 2 de P20 ; salaire = 4750.00 + 156.25.
    assert v21["entrees"]["cumuls_avant"]["valeurs"]["salaire_rrq_cumul_avant"] == "4906.25"
    assert v21["calcul"]["etat"] == "COMPOSE_PREPARATOIRE" and v21["mentions"]["aucun_versement"] is True


# ===================================================================== refus, sécurité et reprises


def creer_dossier(client, csrf, periode=20, *, mutation=None, **kw):
    e = entrees_periode(periode, **kw)
    ap = apercu(client, csrf, e)
    reponse = conserver(client, csrf, e, ap, mutation=mutation)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()["resultat"], e, ap


def interdire_outils(monkeypatch):
    def interdit(*_a, **_k):
        pytest.fail("un outil M5 a été exécuté malgré un refus d'accès ou de CSRF")

    monkeypatch.setattr(metier, "executer", interdit)


ROUTES_LECTURE = (
    "/finance/paie/dossiers",
    "/finance/paie/dossiers/nouveau",
    "/finance/paie/dossiers/" + "a" * 32,
    "/finance/paie/dossiers/" + "a" * 32 + "/verifier",
    "/api/finance/paie/dossiers",
    "/api/finance/paie/dossiers/" + "a" * 32,
    "/api/finance/paie/dossiers/" + "a" * 32 + "/verifier",
)
ROUTES_ECRITURE = (
    "/finance/paie/dossiers/apercu",
    "/finance/paie/dossiers/conserver",
    "/finance/paie/dossiers/" + "a" * 32 + "/revue",
    "/finance/paie/dossiers/" + "a" * 32 + "/rouvrir",
    "/finance/paie/dossiers/" + "a" * 32 + "/export",
    "/api/finance/paie/dossiers/apercu",
    "/api/finance/paie/dossiers/conserver",
    "/api/finance/paie/dossiers/" + "a" * 32 + "/revue",
    "/api/finance/paie/dossiers/" + "a" * 32 + "/rouvrir",
    "/api/finance/paie/dossiers/" + "a" * 32 + "/export",
)


def test_anonyme_refuse_partout(client, monkeypatch):
    interdire_outils(monkeypatch)
    for route in ROUTES_LECTURE:
        reponse = client.get(route, follow_redirects=False)
        assert reponse.status_code in {303, 401}, (route, reponse.status_code)
    for route in ROUTES_ECRITURE:
        reponse = (
            client.post(route, json={}, follow_redirects=False)
            if route.startswith("/api")
            else client.post(route, data={}, follow_redirects=False)
        )
        assert reponse.status_code in {303, 401, 403}, (route, reponse.status_code)


@pytest.mark.parametrize(
    ("role", "identifiant"),
    [
        ("admin", "admin-dossier-fictif"),
        ("manager", "manager-dossier-fictif"),
        ("finance", "finance-dossier-fictif"),
        ("employee", EMPLOYEE),
    ],
)
def test_roles_insuffisants_refuses_sans_executer_d_outil(client, monkeypatch, role, identifiant):
    csrf = connecter(client, role, identifiant)
    interdire_outils(monkeypatch)
    for route in ROUTES_LECTURE:
        assert client.get(route).status_code == 403, route
    for route in ROUTES_ECRITURE:
        if route.startswith("/api"):
            reponse = client.post(route, json={}, headers={"x-csrf-token": csrf})
        else:
            reponse = client.post(route, data={"csrf": csrf})
        assert reponse.status_code == 403, (route, reponse.status_code)


def test_role_proprietaire_revoque_apres_connexion_refuse_et_n_ecrit_rien(env, client, monkeypatch):
    csrf = connecter(client)
    e = entrees_periode(20)
    ap = apercu(client, csrf, e)
    avant = lire_etat(env)
    with env["session"]() as cnx:
        identite.retirer_role(cnx, OWNER, "nathan_owner")
    apres_revocation = lire_etat(env)
    interdire_outils(monkeypatch)
    assert client.get("/finance/paie/dossiers").status_code == 403
    assert client.get("/api/finance/paie/dossiers").status_code == 403
    assert conserver(client, csrf, e, ap).status_code == 403
    assert lire_etat(env) == apres_revocation and apres_revocation[1] == avant[1]


def test_session_expiree_refusee_cote_serveur(client, monkeypatch):
    from datetime import datetime, timedelta

    csrf = connecter(client)

    class Futur(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=3650)

    monkeypatch.setattr(paie_dossier_ui, "datetime", Futur)
    interdire_outils(monkeypatch)
    assert client.get("/finance/paie/dossiers").status_code == 403
    assert api(client, csrf, "/apercu", {"employee_person_id": EMPLOYEE, "entrees": {}}).status_code == 403


def test_csrf_absent_ou_faux_refuse_avant_tout_outil(client, monkeypatch):
    connecter(client)
    interdire_outils(monkeypatch)
    for route in ROUTES_ECRITURE:
        if route.startswith("/api"):
            assert client.post(route, json={}).status_code == 403, route
            assert client.post(route, json={}, headers={"x-csrf-token": "faux"}).status_code == 403, route
        else:
            assert client.post(route, data={}).status_code == 403, route
            assert client.post(route, data={"csrf": "faux"}).status_code == 403, route


def test_corps_non_conformes_refuses_sans_ecriture(env, client):
    csrf = connecter(client)
    avant = lire_etat(env)
    entetes = {"x-csrf-token": csrf}
    route = "/api/finance/paie/dossiers/apercu"
    assert client.post(route, content=b"{pas du json", headers=entetes).status_code == 400
    assert client.post(route, content=b"[1,2]", headers=entetes).status_code == 400
    assert client.post(route, content=("[" * 30000).encode(), headers=entetes).status_code == 400
    assert client.post(route, content=b"x" * (64 * 1024 + 1), headers=entetes).status_code == 413
    assert (
        client.post(
            route, json={"employee_person_id": EMPLOYEE, "entrees": {}, "role": "nathan_owner"}, headers=entetes
        ).status_code
        == 400
    )
    assert client.post("/finance/paie/dossiers/apercu", content=b"x" * (64 * 1024 + 1)).status_code == 413
    form = "/finance/paie/dossiers/apercu"
    assert client.post(form, data={"csrf": csrf, "action": "apercu", "role": "nathan_owner"}).status_code == 400
    assert (
        client.post(
            form, content=b"csrf=a&csrf=b", headers={"content-type": "application/x-www-form-urlencoded"}
        ).status_code
        == 400
    )
    trop = "&".join(f"c{i}=1" for i in range(200))
    assert (
        client.post(
            form, content=trop.encode(), headers={"content-type": "application/x-www-form-urlencoded"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            form, content=b"\xff\xfe=1", headers={"content-type": "application/x-www-form-urlencoded"}
        ).status_code
        == 400
    )
    assert lire_etat(env) == avant


def test_chemins_et_parametres_invalides(client):
    connecter(client)
    assert client.get("/finance/paie/dossiers/zzz").status_code == 404
    assert client.get("/finance/paie/dossiers/" + "A" * 32).status_code == 404
    assert client.get("/finance/paie/dossiers?x=1").status_code == 400
    assert client.get("/finance/paie/dossiers/" + "a" * 32 + "?v=abc").status_code == 400
    assert client.get("/finance/paie/dossiers/" + "a" * 32 + "?v=0").status_code == 400
    assert client.get("/finance/paie/dossiers/nouveau?depuis=" + "a" * 32).status_code == 400
    assert client.get("/finance/paie/dossiers/nouveau?depuis=../x&mode=correction").status_code == 400
    assert client.get("/finance/paie/dossiers/nouveau?foo=1").status_code == 400
    assert client.get("/api/finance/paie/dossiers/" + "a" * 32 + "?numero=-1").status_code == 400
    assert client.get("/finance/paie/dossiers/" + "a" * 32).status_code == 404


def test_refus_metier_donnent_un_code_et_aucune_ecriture(env, client):
    csrf = connecter(client)
    recu, e, ap = creer_dossier(client, csrf)
    avant = lire_etat(env)
    cas = {
        "version_perimee": lambda: conserver(client, csrf, e, ap, attendue=0, mutation="1" * 32),
        "hash_faux": lambda: api(
            client,
            csrf,
            f"/{recu['dossier_id']}/revue",
            {"numero": 1, "hash_version": "0" * 64, "decision": "REVUE_COMPLETEE", "note": "", "mutation_id": "2" * 32},
        ),
        "export_sans_revue": lambda: api(
            client,
            csrf,
            f"/{recu['dossier_id']}/export",
            {"numero": 1, "hash_version": recu["hash_version"], "format_export": "json", "mutation_id": "3" * 32},
        ),
        "reouverture_inutile": lambda: api(
            client,
            csrf,
            f"/{recu['dossier_id']}/rouvrir",
            {"numero": 1, "hash_version": recu["hash_version"], "motif": "x", "mutation_id": "4" * 32},
        ),
        "dossier_inconnu": lambda: api(
            client,
            csrf,
            f"/{'9' * 32}/revue",
            {
                "numero": 1,
                "hash_version": recu["hash_version"],
                "decision": "A_CORRIGER",
                "note": "",
                "mutation_id": "5" * 32,
            },
        ),
        "employe_non_actif": lambda: api(
            client, csrf, "/apercu", {"employee_person_id": "inconnu.fictif", "entrees": e}
        ),
        "employe_non_employee": lambda: api(client, csrf, "/apercu", {"employee_person_id": OWNER, "entrees": e}),
    }
    attendus = {
        "version_perimee": 409,
        "hash_faux": 409,
        "export_sans_revue": 409,
        "reouverture_inutile": 409,
        "dossier_inconnu": 404,
        "employe_non_actif": 403,
        "employe_non_employee": 403,
    }
    for nom, appel in cas.items():
        reponse = appel()
        assert reponse.status_code == attendus[nom], (nom, reponse.status_code, reponse.text)
        assert reponse.json()["verdict"]["code"].startswith("REJ-DOSSIER-PAIE-"), nom
    apres = lire_etat(env)
    changees = {t for t in apres[0] if apres[0][t] != avant[0][t]}
    # Un refus ne laisse que l'audit et le reçu d'idempotence de la commande refusée (jamais de donnée de paie).
    assert changees <= {"mutations_appliquees", "journal"}, changees
    assert apres[1] == avant[1]
    with env["session"]() as cnx:
        reponses = cnx.execute(select(META.tables["mutations_appliquees"].c.reponse)).scalars().all()
    assert all("156.25" not in str(r) and EMPLOYEE not in str(r) for r in reponses)


def test_rejeu_http_idempotent_et_conflit_sans_ecriture(env, client):
    csrf = connecter(client)
    e = entrees_periode(20)
    ap = apercu(client, csrf, e)
    premier = conserver(client, csrf, e, ap, mutation="7" * 32)
    deuxieme = conserver(client, csrf, e, ap, mutation="7" * 32)
    assert premier.status_code == deuxieme.status_code == 200
    r1, r2 = premier.json()["resultat"], deuxieme.json()["resultat"]
    assert {k: v for k, v in r1.items() if k not in {"statut", "rejoue"}} == {
        k: v for k, v in r2.items() if k not in {"statut", "rejoue"}
    }
    etat = lire_etat(env)
    autre = json.loads(json.dumps(e))
    autre["credits_federal"]["TC"] = "17000.00"
    conflit = conserver(client, csrf, autre, apercu(client, csrf, autre), mutation="7" * 32)
    assert conflit.status_code in {400, 409}
    assert lire_etat(env) == etat
    assert (
        len(client.get(f"/api/finance/paie/dossiers/{r1['dossier_id']}").json()["resultat"]["dossier"]["versions"]) == 1
    )


def test_panne_tardive_annule_tout_puis_reprise_sans_doublon(env, monkeypatch):
    from m5_financecore import service_dossier_paie as service

    with TestClient(env["app"], base_url=f"http://testserver{PREFIXE}", raise_server_exceptions=False) as client:
        csrf = connecter(client)
        e = entrees_periode(20)
        ap = apercu(client, csrf, e)
        avant = lire_etat(env)
        vrai = service._recu

        def panne(*_a, **_k):
            raise RuntimeError("panne après l'écriture du journal")

        monkeypatch.setattr(service, "_recu", panne)
        assert conserver(client, csrf, e, ap, mutation="8" * 32).status_code == 500
        assert lire_etat(env) == avant  # journal, clé, idempotence : tout est annulé
        monkeypatch.setattr(service, "_recu", vrai)
        reprise = conserver(client, csrf, e, ap, mutation="8" * 32)
        assert reprise.status_code == 200 and reprise.json()["resultat"]["numero"] == 1
        liste = client.get("/api/finance/paie/dossiers").json()["resultat"]["dossiers"]
        assert len(liste) == 1 and liste[0]["nombre_versions"] == 1


def test_donnees_alterees_en_sql_ferment_la_lecture_sans_fuite(env, client):
    from sqlalchemy import text

    from opsys.stockage import codec

    csrf = connecter(client)
    recu, _, _ = creer_dossier(client, csrf)
    with env["session"]() as cnx:
        ligne = cnx.execute(
            select(REGISTRES.c.maillon).where(REGISTRES.c.registre == "dossiers_paie_preparatoires")
        ).scalar_one()
        maillon = codec.decoder(ligne)
        maillon["ciphertext"] = maillon["ciphertext"][:-2] + ("00" if maillon["ciphertext"][-2:] != "00" else "01")
        cnx.execute(
            text("UPDATE registres_maillons SET maillon = :m WHERE registre = 'dossiers_paie_preparatoires'"),
            {"m": codec.encoder(maillon)},
        )
    for route in (f"/api/finance/paie/dossiers/{recu['dossier_id']}", "/api/finance/paie/dossiers"):
        reponse = client.get(route)
        assert reponse.status_code == 500 and reponse.json()["verdict"]["code"] == "REJ-DOSSIER-PAIE-DONNEES-CORROMPUES"
        assert "156.25" not in reponse.text and EMPLOYEE not in reponse.text
    page = client.get(f"/finance/paie/dossiers/{recu['dossier_id']}")
    assert page.status_code == 500 and "156.25" not in page.text and EMPLOYEE not in page.text
    assert (
        api(
            client,
            csrf,
            f"/{recu['dossier_id']}/revue",
            {
                "numero": 1,
                "hash_version": recu["hash_version"],
                "decision": "A_CORRIGER",
                "note": "",
                "mutation_id": "9" * 32,
            },
        ).status_code
        == 500
    )


def test_derive_des_heures_m4_detectee_puis_rebase_explicite(env, client):
    csrf = connecter(client)
    recu, e, _ = creer_dossier(client, csrf)
    d = recu["dossier_id"]
    assert client.get(f"/api/finance/paie/dossiers/{d}/verifier").json()["resultat"]["differences"] == []
    # Correction des heures M4 APRÈS le snapshot : une heure de plus le 25 septembre, validée par approbation N4.
    _pointer(env["registre_m4"], EMPLOYEE, "2026-09-25", 1, "I-dossier-derive")
    _valider_heures(env["session"], env["outils_m4"], EMPLOYEE, *PERIODES[20][:2], motif="Heure ajoutée après coup.")
    controle = client.get(f"/api/finance/paie/dossiers/{d}/verifier").json()["resultat"]
    codes = {x["code"] for x in controle["differences"]}
    assert controle["reproductible"] is True and controle["sources_inchangees"] is False
    assert {"SOURCE-HEURES_M4-MODIFIEE", "BRUT-MODIFIE"} <= codes
    rev = api(
        client,
        csrf,
        f"/{d}/revue",
        {
            "numero": 1,
            "hash_version": recu["hash_version"],
            "decision": "REVUE_COMPLETEE",
            "note": "",
            "mutation_id": "a1" * 16,
        },
    )
    assert rev.status_code == 409 and rev.json()["verdict"]["code"] == "REJ-DOSSIER-PAIE-SOURCE-MODIFIEE"
    # Un ancien aperçu ne peut plus être conservé : les sources ont changé depuis.
    ancien = apercu(client, csrf, e)
    assert ancien["version"]["sources"]["brut"]["brut_brouillon"] == "187.50"
    rebase = conserver(client, csrf, e, ancien, attendue=1, type_version="REBASE", motif="heures M4 corrigées")
    assert rebase.status_code == 200 and rebase.json()["resultat"]["numero"] == 2
    comp = client.get(f"/api/finance/paie/dossiers/{d}?numero=2&comparer_a=1").json()["resultat"]["comparaison"]
    champs = {c["champ"]: (c["avant"], c["apres"]) for c in comp["sources"]}
    assert champs["brut.brut_brouillon"] == ("156.25", "187.50")
    v1 = client.get(f"/api/finance/paie/dossiers/{d}?numero=1").json()["resultat"]["version"]
    assert v1["sources"]["brut"]["brut_brouillon"] == "156.25" and v1["hash_version"] == recu["hash_version"]


def test_redemarrage_meme_donnees_meme_export(env, client):
    csrf = connecter(client)
    recu, _, _ = creer_dossier(client, csrf)
    d = recu["dossier_id"]
    assert (
        api(
            client,
            csrf,
            f"/{d}/revue",
            {
                "numero": 1,
                "hash_version": recu["hash_version"],
                "decision": "REVUE_COMPLETEE",
                "note": "ok <img src=x onerror=alert(1)>",
                "mutation_id": "b2" * 16,
            },
        ).status_code
        == 200
    )
    export1 = api(
        client,
        csrf,
        f"/{d}/export",
        {"numero": 1, "hash_version": recu["hash_version"], "format_export": "html", "mutation_id": "b3" * 16},
    )
    assert export1.status_code == 200 and "<img" not in export1.text and "&lt;img" in export1.text
    assert "default-src 'none'" in export1.headers["content-security-policy"]
    lecture1 = client.get(f"/api/finance/paie/dossiers/{d}").json()["resultat"]
    stockage.liberer()  # « redémarrage » : le moteur SQL est refermé puis rouvert depuis le disque
    app2 = application.creer_application(Configuration(SECRET, cookie_securise=False), env["deps"], env["session"])
    with TestClient(app2, base_url=f"http://testserver{PREFIXE}") as client2:
        csrf2 = connecter(client2)
        lecture2 = client2.get(f"/api/finance/paie/dossiers/{d}").json()["resultat"]
        assert lecture2["version"]["hash_version"] == lecture1["version"]["hash_version"] == recu["hash_version"]
        assert lecture2["dossier"] == lecture1["dossier"]
        page = client2.get(f"/finance/paie/dossiers/{d}")
        assert "&lt;img" in page.text and "<img" not in page.text
        export2 = api(
            client2,
            csrf2,
            f"/{d}/export",
            {"numero": 1, "hash_version": recu["hash_version"], "format_export": "html", "mutation_id": "b4" * 16},
        )
        assert (
            export2.content == export1.content
            and export2.headers["x-export-sha256"] == export1.headers["x-export-sha256"]
        )


def test_version_attendue_non_numerique_donne_400_et_non_500(env, client):
    csrf = connecter(client)
    donnees = champs_formulaire(EMPLOYEE, entrees_periode(20))
    reponse = post_form(client, "/finance/paie/dossiers/apercu", donnees, csrf, action="apercu", version_attendue="abc")
    assert reponse.status_code == 400
