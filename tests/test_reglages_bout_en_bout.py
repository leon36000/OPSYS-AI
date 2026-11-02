"""Réglages de direction (CFG-1), de bout en bout : VRAIS outils de M2 et de M8, vrai sas N3, vraie console, base
SQLite migrée.

Le scénario : une installation neuve → les réglages de M2 sont vides, la relance et le score de santé sont inertes (le
comportement d'aujourd'hui) → la console liste ce qui manque et ce que ça bloque → le propriétaire adopte (N3) → la
relance se prépare et le score de santé se calcule → retour arrière → de nouveau inertes. Plus : l'adoption sans
approbation est refusée, la valeur hors bornes aussi, la double adoption est idempotente, une panne annule tout, un
redémarrage garde tout, une chaîne falsifiée retombe sur l'inerte (fail-closed) puis se rétablit une fois réparée, et
la valeur déjà écrite dans `department.yaml` continue de valoir tant qu'aucune valeur adoptée ne la remplace. Données
fictives (`fictif: true`) ; aucun envoi réel (M2 ne fait que PRÉPARER la relance).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from m2_revenue_crm import outils as m2
from m8_analytics import jeux_fictifs
from m8_analytics import outils as m8
from m8_analytics.registre import RegistreSnapshots
from sqlalchemy import select, update

from opsys import contexte, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.outils import executer_atomique
from opsys.reglages import lecture
from opsys.stockage.schema import REGISTRES

RACINE = Path(__file__).resolve().parents[1]


def _charger(chemin, nom):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


aide = _charger(Path(__file__).with_name("reglages_aide.py"), "reglages_aide_e2e")
m2t = _charger(RACINE / "departments/m02-revenue-crm/tests/test_relances_outils.py", "m2_relances_outils_e2e")

FICTIF = True
SECRET = "secret-reglages-bout-en-bout-" + "x" * 40
MAINTENANT_M8 = "2026-10-30T20:00:00-04:00"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    deps = aide.installer(tmp_path, monkeypatch)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
    m2.utiliser_stockage_durable()
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe="/opsys"), deps, stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        r = client.post("/connexion", data={"identifiant": aide.PROPRIETAIRE, "mot_de_passe": aide.MOT_DE_PASSE},
                        follow_redirects=False)
        assert r.status_code == 303
        client.csrf = client.get("/api/session").json()["csrf"]
        # un lead avec un devis envoyé il y a 19 jours et un lead dormant : de quoi relancer dès que les réglages
        # existent
        m2t._lead("lead-un", "vendeur.un", m2t.CONTACT_A)
        m2t._lead("lead-dormant", "vendeur.un", m2t.CONTACT_C, ingere="2026-08-01T09:00:00-04:00",
                  qualifie="2026-08-01T10:00:00-04:00")
        m2t._envoyer_devis("devis-un", "lead-un", m2t.ENVOI_UN)
        yield client
    m2.reinitialiser_registre()
    stockage.liberer()


def _adopter(client, cle, saisie, **plus):
    champs = {"csrf": client.csrf, "action": "adopter", "cle": cle, "saisie": saisie,
              "raison": "Décision de la direction", **plus}
    return client.post("/reglages/geste", data=champs, follow_redirects=False)


def _revenir(client, cle, **plus):
    champs = {"csrf": client.csrf, "action": "revenir", "cle": cle, "raison": "Retour au départ", **plus}
    return client.post("/reglages/geste", data=champs, follow_redirects=False)


def _outils_m2():
    return {o.nom: o for o in m2.outils()}


def _lister_relances():
    return m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN)


def _manque_m2():
    with stockage.transaction():
        return lecture.etat_des_reglages(_departements(), departement="m02-revenue-crm")


def _departements():
    from opsys.departements import charger_departements

    return charger_departements()


def _sante():
    faits = jeux_fictifs.registres_fictifs()
    outils = {o.nom: o for o in m8.outils(
        registre_cible=RegistreSnapshots(), definitions_cible=[], faits_cible=faits["chantier"],
        faits_entonnoir_cible=faits["entonnoir"], faits_contenus_cible=faits["contenus"],
        faits_cash_libre_cible=faits["cash_libre"], historique_sante_cible=[], publications_cible=[])}
    reponse = executer_atomique(outils["m8_lire_sante_entreprise"], {"maintenant": MAINTENANT_M8})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _saisie_bornes(bornes):
    return f"{bornes['pire']} ; {bornes['cible']}"


# -- le scénario de la direction ------------------------------------------------------------------------------------
def test_installation_neuve_adoption_deblocage_retour_arriere_pour_m2(monde):
    # 1. installation neuve : les trois délais manquent, la relance est inerte — comme avant ce chantier
    refus = m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN)
    assert refus["resultat"]["accepte"] is False
    assert "REJ-RELANCES-A-CONFIGURER" in str(refus["resultat"]["verdict"])
    inerte = m2t._appeler(_outils_m2(), "m2_preparer_relance", {
        "lead_id": "lead-un", "regle": "relance_devis_sans_reponse", "canal": "appel", "horodatage": m2t.MAINTENANT},
        m2t.VENDEUR_UN)
    assert inerte["resultat"]["accepte"] is False and "REJ-RELANCES-A-CONFIGURER" in str(inerte["resultat"]["verdict"])

    # 2. la console liste ce qui manque et ce que ça bloque, avec la proposition et sa source
    vue = monde.get("/api/reglages").json()
    m2_manquants = {r["cle"]: r for r in vue["reglages"] if r["departement"] == "m02-revenue-crm" and r["manque"]}
    assert set(m2_manquants) == {"m2.jours_inactivite_dormant", "m2.jours_soumission_perimee",
                                 "m2.jours_entre_relances",
                                 "m2.bandes_valeur_cents"}
    relances = m2_manquants["m2.jours_entre_relances"]
    assert "REJ-RELANCES-A-CONFIGURER" in relances["debloque"]
    assert relances["proposition"]["etiquette"] == "recommandation, non validée"

    # 3. adoption (N3, propriétaire) des trois délais proposés : rien ne s'est appliqué avant ce geste
    assert aide.chaine() == []
    for cle, saisie in (("m2.jours_entre_relances", "7"), ("m2.jours_soumission_perimee", "14"),
                        ("m2.jours_inactivite_dormant", "30")):
        assert _adopter(monde, cle, saisie).status_code == 303
    assert [m["origine"] for m in aide.chaine()] == ["proposition"] * 3

    # 4. la fonction se débloque : la relance est listée puis PRÉPARÉE (rien n'est envoyé)
    page = m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN)
    assert page["resultat"]["accepte"] is True
    assert ("lead-un", "relance_devis_sans_reponse") in m2t._ids(page["resultat"]["resultat"])
    prete = m2t._appeler(_outils_m2(), "m2_preparer_relance", {
        "lead_id": "lead-un", "regle": "relance_devis_sans_reponse", "canal": "appel", "horodatage": m2t.MAINTENANT},
        m2t.VENDEUR_UN)
    assert prete["resultat"]["accepte"] is True and prete["resultat"]["resultat"]["envoye"] is False
    assert len(m2t._preparees()) == 1

    # 5. retour arrière du délai de relance : de nouveau inerte (la relance déjà préparée reste un fait daté)
    assert _revenir(monde, "m2.jours_entre_relances", version_attendue="1").status_code == 303
    apres = m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN)
    assert apres["resultat"]["accepte"] is False and "REJ-RELANCES-A-CONFIGURER" in str(apres["resultat"]["verdict"])
    assert [m["type"] for m in aide.chaine()] == ["adoption"] * 3 + ["retour_arriere"]
    restant = {r["cle"]: r for r in monde.get("/api/reglages").json()["reglages"]}
    assert restant["m2.jours_entre_relances"]["manque"] is True
    assert restant["m2.jours_soumission_perimee"]["manque"] is False


def test_les_segments_de_m2_se_calculent_apres_adoption_et_redeviennent_non_calculables_apres_le_retour(monde):
    def segments():
        reponse = m2t._appeler(_outils_m2(), "m2_lister_leads", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN)
        assert reponse["resultat"]["accepte"] is True, reponse
        page = reponse["resultat"]["resultat"]
        par_lead = {lead["lead_id"]: sorted(s["segment"] for s in lead["segments"]) for lead in page["leads"]}
        manques = {n["segment"] for n in page["segments_non_calculables"]}
        return par_lead, manques

    par_lead, manques = segments()
    # `quote_sent` (devis envoyé) ne dépend d'aucun réglage : le filet anti-perte de M2 (M2-C5) l'a rendu calculable.
    assert par_lead == {"lead-dormant": [], "lead-un": ["quote_sent"]}
    assert {"dormant_lead", "quote_stale"} <= manques, "sans réglage, les deux segments sont « à configurer »"
    assert _adopter(monde, "m2.jours_inactivite_dormant", "30").status_code == 303
    assert _adopter(monde, "m2.jours_soumission_perimee", "14").status_code == 303
    par_lead, manques = segments()
    assert par_lead == {"lead-dormant": ["dormant_lead"], "lead-un": ["quote_sent", "quote_stale"]}
    assert not {"dormant_lead", "quote_stale"} & manques
    assert _revenir(monde, "m2.jours_inactivite_dormant").status_code == 303
    par_lead, manques = segments()
    assert par_lead == {"lead-dormant": [], "lead-un": ["quote_sent", "quote_stale"]} and "dormant_lead" in manques


def test_le_score_de_sante_de_m8_est_indetermine_puis_calculable_puis_de_nouveau_indetermine(monde):
    vide = _sante()
    assert vide["statut"] == "indetermine" and vide["score"] is None
    assert {m["raison"] for m in vide["manques"]} == {"bornes_a_configurer"}
    manquants = [r for r in monde.get("/api/reglages").json()["reglages"]
                 if r["departement"] == "m08-analytics" and r["manque"]]
    assert len(manquants) == 6 and all(r["proposition"] is None for r in manquants)

    for mesure, bornes in jeux_fictifs.BORNES_SANTE_FICTIVES.items():
        reponse = _adopter(monde, f"m8.bornes_{mesure[3:]}", _saisie_bornes(bornes))
        assert reponse.status_code == 303, (mesure, reponse.text)
    calcule = _sante()
    assert calcule["statut"] == "determine" and calcule["score"] is not None
    assert calcule["ponderations"]["validee"] is False, "adopter des bornes ne valide pas les pondérations"
    assert all(r["manque"] is False for r in monde.get("/api/reglages").json()["reglages"]
               if r["departement"] == "m08-analytics")

    assert _revenir(monde, "m8.bornes_cash_libre_cad").status_code == 303
    redevenu = _sante()
    assert redevenu["statut"] == "indetermine" and redevenu["score"] is None
    assert {m["raison"] for m in redevenu["manques"]} == {"bornes_a_configurer"}


def test_le_score_adopte_est_le_meme_que_celui_des_bornes_ecrites_dans_le_fichier(monde, monkeypatch):
    """Adopter les bornes donne exactement le score que donnerait le fichier rempli à la main (compatibilité)."""
    for mesure, bornes in jeux_fictifs.BORNES_SANTE_FICTIVES.items():
        assert _adopter(monde, f"m8.bornes_{mesure[3:]}", _saisie_bornes(bornes)).status_code == 303
    adopte = _sante()
    stockage.liberer()  # base vierge : plus rien d'adopté, les mêmes bornes viennent alors du « fichier »
    monkeypatch.setattr(m8, "_configuration", lambda: {"sante": {"bornes": jeux_fictifs.BORNES_SANTE_FICTIVES}})
    ecrit = _sante()
    assert (adopte["score"], adopte["statut"]) == (ecrit["score"], ecrit["statut"])
    assert adopte["composantes"] == ecrit["composantes"]


# -- compatibilité avec department.yaml ---------------------------------------------------------------------
def test_une_valeur_deja_ecrite_dans_department_yaml_vaut_tant_que_rien_n_est_adopte(monde, monkeypatch, tmp_path):
    chemin = aide.manifeste_avec(tmp_path, "m02-revenue-crm", lambda d: d.update(configuration={
        "segments": {"jours_inactivite_dormant": 30, "jours_soumission_perimee": 14},
        "relances": {"jours_entre_relances": 21}, "scoring": {}}))
    monkeypatch.setattr(m2, "_MANIFESTE", chemin)
    ecrit = m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN)
    assert ecrit["resultat"]["accepte"] is True, "le fichier suffit : rien n'est cassé pour qui l'a déjà rempli"
    assert aide.chaine() == []
    assert _configuration_relances()["jours_entre_relances"]["valeur"] == 21
    # une valeur adoptée la remplace…
    assert _adopter(monde, "m2.jours_entre_relances", "3").status_code == 303
    assert _configuration_relances()["jours_entre_relances"]["valeur"] == 3
    # …et le retour arrière rend la main au fichier
    assert _revenir(monde, "m2.jours_entre_relances").status_code == 303
    assert _configuration_relances()["jours_entre_relances"]["valeur"] == 21


def _configuration_relances():
    with stockage.transaction():
        return m2._configuration_relances()


# -- les refus ---------------------------------------------------------------------------------------------------
def test_l_adoption_sans_approbation_du_proprietaire_est_refusee_par_tous_les_chemins_directs(monde):
    outil = aide.outil_m9(_departements(), "m9_adopter_reglage")
    arguments = {"cle": "m2.jours_entre_relances", "valeur": 7, "raison": "Sans approbation"}
    for identite_appelante in (None, contexte.IdentiteAppelante(aide.PROPRIETAIRE, "nathan_owner", source="console")):
        if identite_appelante is None:
            reponse = executer_atomique(outil, arguments)
        else:
            with contexte.appele_par_appareil(identite_appelante):
                reponse = executer_atomique(outil, arguments)
        assert reponse["ok"] is False and "REJ-HUMAIN-REQUIS" in reponse["details"]
    assert aide.chaine() == []
    refus = m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN)
    assert refus["resultat"]["accepte"] is False, "rien ne s'est débloqué"


def test_une_valeur_hors_bornes_est_refusee_et_la_fonction_reste_inerte(monde):
    for saisie in ("0", "3651", "abc", "7.5"):
        assert _adopter(monde, "m2.jours_entre_relances", saisie).status_code == 400
    assert aide.chaine() == []
    assert m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN
                        )["resultat"]["accepte"] is False


def test_la_double_adoption_est_idempotente_et_n_ajoute_aucun_maillon(monde):
    assert _adopter(monde, "m2.jours_entre_relances", "7").status_code == 303
    assert "deja_adopte" in _adopter(monde, "m2.jours_entre_relances", "7").headers["location"]
    assert len(aide.chaine()) == 1 and _configuration_relances()["jours_entre_relances"]["valeur"] == 7


# -- panne et reprise ---------------------------------------------------------------------------------------------
def test_une_panne_pendant_l_adoption_annule_tout_et_la_fonction_reste_inerte(monde, monkeypatch):
    import m9_strategic_intelligence.outils_reglages as outil_reglages

    def panne(*_args, **_kw):
        raise OSError("disque plein simulé après l'écriture du maillon")

    reel = outil_reglages._journaliser
    monkeypatch.setattr(outil_reglages, "_journaliser", panne)
    reponse = _adopter(monde, "m2.jours_entre_relances", "7")
    assert reponse.status_code >= 400, reponse.text
    assert aide.chaine() == []
    with stockage.transaction() as cnx:
        assert cnx.execute(select(REGISTRES.c.rang).where(REGISTRES.c.departement == "opsys-reglages")).all() == []
    assert m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN
                        )["resultat"]["accepte"] is False
    monkeypatch.setattr(outil_reglages, "_journaliser", reel)
    assert _adopter(monde, "m2.jours_entre_relances", "7").status_code == 303, "la reprise rejoue proprement"


def test_apres_un_redemarrage_les_valeurs_adoptees_sont_toujours_servies(monde):
    for cle, saisie in (("m2.jours_entre_relances", "7"), ("m2.jours_soumission_perimee", "14")):
        assert _adopter(monde, cle, saisie).status_code == 303
    avant = aide.chaine()
    stockage.liberer()  # le processus tombe : plus aucune connexion, aucun cache
    m2.reinitialiser_registre()
    m2.utiliser_stockage_durable()
    assert aide.chaine() == avant
    assert _configuration_relances()["jours_entre_relances"]["valeur"] == 7


def test_une_chaine_falsifiee_ramene_la_fonction_a_l_inerte_puis_se_retablit_une_fois_reparee(monde):
    assert _adopter(monde, "m2.jours_entre_relances", "7").status_code == 303
    assert _adopter(monde, "m2.jours_soumission_perimee", "14").status_code == 303
    assert m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN
                        )["resultat"]["accepte"] is True
    with stockage.transaction() as cnx:
        original = cnx.execute(select(REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == "opsys-reglages") & (REGISTRES.c.rang == 0))).scalar_one()
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == "opsys-reglages") & (REGISTRES.c.rang == 0)
        ).values(maillon=original.replace('"nouvelle_valeur":7', '"nouvelle_valeur":1')))
    inerte = m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN)
    assert inerte["resultat"]["accepte"] is False, "chaîne douteuse : rien d'adopté n'est servi (fail-closed)"
    assert monde.get("/api/reglages").json()["chaine"]["valide"] is False
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == "opsys-reglages") & (REGISTRES.c.rang == 0)).values(maillon=original))
    assert m2t._appeler(_outils_m2(), "m2_lister_relances", {"horodatage": m2t.MAINTENANT}, m2t.ADMIN
                        )["resultat"]["accepte"] is True


def test_le_manifeste_de_m2_reste_lisible_et_les_proprietes_du_fichier_ne_changent_pas(monde):
    avant = (RACINE / "departments/m02-revenue-crm/department.yaml").read_text(encoding="utf-8")
    assert _adopter(monde, "m2.jours_entre_relances", "7").status_code == 303
    apres = (RACINE / "departments/m02-revenue-crm/department.yaml").read_text(encoding="utf-8")
    assert avant == apres, "l'adoption n'écrit jamais dans le fichier du département"
    assert yaml.safe_load(apres)["configuration"]["relances"] == {}
    assert re.search(r"relances: \{\}", apres)
