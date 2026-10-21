"""M10 : HTTP/SQLite réel ; porte Core rejouée en Python, aucun rendu mobile.

Données fictives. Volume : charges de variance clonées en fixtures, sans prétendre 50 chantiers réels.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import pytest
from m10_memoire import outils as m10
from tests.e2e.test_briefing_admin_appareil import empreinte_tables
from tests.e2e.test_travaux_termines_appareil import _evenements, _Scenario

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique

FICTIF = True
SQLITE = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
RACINE = Path(__file__).resolve().parents[2]
DATE = "2026-09-15T14:00:00-04:00"
MAILLON = frozenset({
    "type_entree", "horodatage", "ligne_id_a", "ligne_id_b", "statut", "revision_ligne_id",
    "ligne_id", "precedent_ligne_id", "par", "role", "source_decision",
})


def _decision_revision():
    lignes = []
    for numero in (1, 2):
        resultat = m10.journaliser_decision({
            "decision_id": f"DEC-M10-ADMIN-FICTIF-{numero}", "raison": "Révision chantier fictif attestée.",
            "statut": "proposee", "options_ecartees": "Ne rien faire",
        }, DATE)
        assert resultat["accepte"] is True
        lignes.append(resultat["decision"]["ligne_id"])
    signalement = m10.signaler_revision(*lignes, DATE)
    assert signalement["accepte"] is True
    return signalement["resultat"]["ligne_id"]


def _volume():
    consommateurs = m10.consommateurs()
    with stockage.transaction():
        consommateurs["m4.travaux_termines"]({
            "wct_id": "WCT-VOLUME-FICTIF", "intervention_id": "INT-VOLUME-FICTIF", "lead_id": "LEAD-VOLUME-FICTIF",
            "technicien_id": "etienne", "horodatage_completion": DATE,
            "fix_gps_completion": {"latitude": 45.5, "longitude": -73.6}, "duree_reelle_minutes": 90,
            "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 64,
            "consommateurs_cibles": ["M10"], "devis_id": "DEV-VOLUME-FICTIF",
        })
        for numero in range(50):
            consommateurs["m6.variance_chantier"]({
                "evenement_id": f"EVT-VOLUME-FICTIF-{numero:03d}", "wct_id": "WCT-VOLUME-FICTIF",
                "intervention_id": "INT-VOLUME-FICTIF", "chantier_id": "CH-VOLUME-FICTIF",
                "statut_variance": "evaluee", "signal_critique": True, "seuil_pourcentage": 0.3,
                "horodatage_completion": DATE, "lignes": [],
            })
    prise = next(o for o in m10.outils() if o.nom == "m10_prendre_en_compte_signal")
    motif = "Écart fictif expliqué : " + "é" * 476
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin")):
        for numero in range(50):
            resultat = executer_atomique(prise, {
                "signal_id": f"EVT-VOLUME-FICTIF-{numero:03d}", "motif": motif, "horodatage": DATE,
            })
            assert resultat["resultat"]["accepte"] is True
    return motif


@SQLITE
def test_volume_natif_non_tronque_et_omissions_explicites(moteur, equipe):
    motif = _volume()
    avant = empreinte_tables()
    reponse = equipe["admin"].appeler("m10_lister_signaux", {"affaire_id": "LEAD-VOLUME-FICTIF"})
    assert reponse.ok and not reponse.mesure.tronque, reponse.corps
    liste = reponse.resultat
    assert reponse.mesure.octets_texte < 6000
    assert len(json.dumps(liste, ensure_ascii=False)) <= 5400
    assert 0 < len(liste["signaux"]) < 50
    assert liste["nb_total"] == liste["nb_pris_en_compte"] == 50
    assert liste["nb_omis"] == 50 - len(liste["signaux"])
    assert all(s["motif"] == motif for s in liste["signaux"])
    assert empreinte_tables() == avant
    _capturer("volume", {"fictif": True, "provenance": "fixtures volume via consommateurs M10 et traitements réels",
                          "reponses": {"signaux_volume": {"outil": "m10_lister_signaux",
                                      "args": {"affaire_id": "LEAD-VOLUME-FICTIF"}, "enveloppe": reponse.enveloppe}}})


def _capturer(suffixe, donnees):
    destination = os.environ.get("OPSYS_M10_CONTRACT_FIXTURE_OUTPUT")
    if not destination:
        return
    chemin = Path(destination)
    if suffixe:
        chemin = chemin.with_name(chemin.stem + "-" + suffixe + chemin.suffix)
    assert not chemin.exists(), "preuves immuables : utiliser une nouvelle destination"
    sources = [Path(m10.__file__), RACINE / "departments/m10-memoire/src/m10_memoire/revision.py",
               RACINE / "departments/m10-memoire/src/m10_memoire/signaux.py",
               RACINE / "departments/m10-memoire/src/m10_memoire/catalogue_references.py",
               RACINE / "departments/m10-memoire/tests/test_catalogue_references.py",
               RACINE / "departments/m10-memoire/src/m10_memoire/dossier_revision.py",
               RACINE / "departments/m10-memoire/tests/test_dossier_revision.py", Path(__file__)]
    donnees["source_sha256"] = {str(p.relative_to(RACINE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n")


@SQLITE
def test_signaux_metier_statuts_arbitrage_reprise_et_capture(moteur, equipe, monkeypatch):
    # Vrai parcours de complétion M4 puis déclaration M6 : variance+40% critique.
    scenario = _Scenario(moteur, equipe, "M10-CONTRAT-FICTIF", 16)
    completion, declaration = scenario.terminer_puis_declarer(56.0)
    assert declaration.metier["accepte"] is True
    evenement = _evenements("m6.variance_chantier")[-1]
    assert evenement["signal_critique"] is True
    revision_id = _decision_revision()
    captures = {}
    admin = equipe["admin"]

    def lire(label, outil, args):
        avant = empreinte_tables()
        reponse = admin.appeler(outil, args)
        assert reponse.ok and reponse.enveloppe["ok"] and not reponse.mesure.tronque, reponse.corps
        assert empreinte_tables() == avant
        captures[label] = {"outil": outil, "args": args, "enveloppe": reponse.enveloppe}
        return reponse.enveloppe["resultat"]

    liste = lire("signaux_ouverts", "m10_lister_signaux", {"affaire_id": scenario.chantier.lead_id})
    assert liste["nb_total"] == liste["nb_ouverts"] == 1
    assert liste["signaux"][0]["signal_id"] == evenement["evenement_id"]
    assert liste["signaux"][0]["affaire_id"] == scenario.chantier.lead_id
    assert lire("decision_proposee", "m10_statut_decision", {"decision_id": "DEC-M10-ADMIN-FICTIF-1"}) == {
        "statut": "proposee"}
    assert lire("revision_en_attente", "m10_statut_revision", {"revision_ligne_id": revision_id}) == {
        "statut": "en_attente"}
    assert lire("decision_inconnue", "m10_statut_decision", {"decision_id": "DEC-INCONNUE-FICTIVE"}) == {"statut": None}
    assert lire("revision_inconnue", "m10_statut_revision", {"revision_ligne_id": "revision-inconnue-fictive"}) == {
        "statut": None}

    moteur.creer_personne("gestionnaire.fictif", "Gestionnaire Fictive", ["admin"], monkeypatch)
    gestionnaire = moteur.appairer("gestionnaire.fictif", "admin")
    args = {"revision_ligne_id": revision_id, "statut": "distincts_confirmes", "horodatage": "2000-01-01T00:00:00Z"}
    cle = "7b805bab-0132-46f1-9d46-4d260727ab61"
    avant_maillons = m10._REGISTRE_AFFAIRES.lire()
    ack = gestionnaire.appeler("m10_arbitrer_revision", args, cle=cle, horodatage_appareil=args["horodatage"])
    assert ack.metier["accepte"] is True and set(ack.resultat) == MAILLON
    assert (ack.resultat["par"], ack.resultat["role"], ack.resultat["source_decision"]) == (
        "gestionnaire.fictif", "admin", "appareil")
    assert dt.datetime.fromisoformat(ack.resultat["horodatage"]) == moteur.horloge.maintenant
    assert m10._REGISTRE_AFFAIRES.lire()[:-1] == avant_maillons
    captures["arbitrage_accepte"] = {"outil": "m10_arbitrer_revision", "args": args, "enveloppe": ack.enveloppe}
    apres = empreinte_tables()
    # Réponse reçue puis volontairement ignorée : simulation explicite de réponse perdue.
    moteur.arreter()
    stockage.liberer()
    moteur.demarrer()
    reprise = gestionnaire.appeler("m10_arbitrer_revision", args, cle=cle, horodatage_appareil=args["horodatage"])
    assert reprise.enveloppe["rejoue"] is True and reprise.metier == ack.metier
    assert empreinte_tables() == apres
    captures["arbitrage_rejoue"] = {"outil": "m10_arbitrer_revision", "args": args, "enveloppe": reprise.enveloppe}
    conflit = gestionnaire.appeler("m10_arbitrer_revision", {**args, "statut": "obsolete_marquee"},
                                  cle=cle, horodatage_appareil=args["horodatage"])
    assert conflit.enveloppe["erreur"] == "mutation_conflit" and empreinte_tables() == apres
    assert lire("revision_arbitree", "m10_statut_revision", {"revision_ligne_id": revision_id}) == {
        "statut": "distincts_confirmes"}
    with stockage.transaction() as cnx:
        identite.activer(cnx, "nathan", False)
    refuse = lire("lecture_revoquee", "m10_lister_signaux", {})
    assert refuse["accepte"] is False and refuse["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    _capturer("", {
        "fictif": True, "provenance": "HTTP MCP/SQLite réel ; porte Core rejouée Python ; perte réponse simulée",
        "wct_id": completion.resultat["wct_id"], "signal_id": evenement["evenement_id"],
        "revision_ligne_id": revision_id, "capture_le": moteur.horloge.maintenant.isoformat(), "reponses": captures,
    })


@SQLITE
def test_catalogue_couple_natif_pages_confidentialite_et_refus_sans_ecriture(moteur, equipe):
    revision_id = _decision_revision()
    texte_prive = "CORPS_CONFIDENTIEL_FICTIF_JAMAIS_A_RENDRE"
    for numero in range(13):
        resultat = m10.journaliser_decision({
            "decision_id": f"DEC-CATALOGUE-FICTIF-{numero:02d}", "raison": texte_prive,
            "statut": "proposee", "options_ecartees": texte_prive,
        }, DATE)
        assert resultat["accepte"] is True
    for niveau in (None, "CLIENT_PRIVATE"):
        resultat = m10.journaliser_decision({
            "decision_id": "DEC-CLIENT-PRIVEE-FICTIVE", "raison": texte_prive,
            "statut": "validee", "options_ecartees": texte_prive,
        }, DATE, niveau)
        assert resultat["accepte"] is True
    tete_privee = m10._REGISTRE_AFFAIRES.tete()
    captures = {}
    admin = equipe["admin"]

    def lire(label, args):
        avant = empreinte_tables()
        reponse = admin.appeler("m10_lister_references", args)
        assert reponse.ok and not reponse.mesure.tronque
        assert empreinte_tables() == avant
        texte = json.dumps(reponse.enveloppe, ensure_ascii=False)
        assert texte_prive not in texte and "DEC-CLIENT-PRIVEE-FICTIVE" not in texte and tete_privee not in texte
        captures[label] = {"outil": "m10_lister_references", "args": args, "enveloppe": reponse.enveloppe}
        return reponse

    premiere = lire("catalogue_page_1", {})
    assert premiere.metier["accepte"] is True
    page = premiere.resultat
    assert set(page) == {
        "decisions", "revisions", "decalage", "suivant", "reste", "total", "affichees", "limite",
        "borne_caracteres", "taille_caracteres", "confidentialite",
    }
    assert page["total"] == 16 and page["decalage"] == 0 and page["limite"] == 8
    assert page["affichees"] == 8 and page["suivant"] == 8 and page["reste"] == 8
    assert page["confidentialite"]["nb_retenus"] == 1
    assert len(json.dumps(premiere.enveloppe, ensure_ascii=False)) == page["taille_caracteres"] <= 5400
    suivantes = lire("catalogue_page_2", {"decalage": page["suivant"]})
    suite = suivantes.resultat
    assert suite["affichees"] == 8 and suite["suivant"] is None and suite["reste"] == 0
    decisions = [*page["decisions"], *suite["decisions"]]
    assert len({d["decision_id"] for d in decisions}) == 15
    assert [r["revision_ligne_id"] for r in suite["revisions"]] == [revision_id]
    assert suite["revisions"][0]["statut"] == "en_attente"
    for item in [*decisions, *suite["revisions"]]:
        for cle in ("reference", "reference_statut", "reference_a", "reference_b"):
            if cle in item:
                assert item[cle]["hash_tete"] == item[cle]["ligne_id"]
                assert m10.verifier_reference(item[cle])["accepte"] is True
    assert len(json.dumps(suivantes.enveloppe, ensure_ascii=False)) == suite["taille_caracteres"] <= 5400
    fin = lire("catalogue_hors_page", {"decalage": 999}).resultat
    assert fin["affichees"] == 0 and fin["total"] == 16 and fin["reste"] == 0 and fin["suivant"] is None
    assert fin["decisions"] == fin["revisions"] == []
    invalide = lire("catalogue_pagination_invalide", {"limite": 9})
    assert invalide.metier["accepte"] is False
    assert invalide.metier["verdict"]["code"] == "REJ-CATALOGUE-PAGINATION-INVALIDE"
    schema = lire("catalogue_schema_invalide", {"domaine": "developpement"})
    assert schema.enveloppe["erreur"] == "arguments_invalides"
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "nathan", "admin")
    revoque = lire("catalogue_role_revoque", {})
    assert revoque.metier["accepte"] is False
    assert revoque.metier["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    _capturer("catalogue", {
        "fictif": True, "provenance": "HTTP MCP/SQLite réel ; porte Core rejouée Python ; catalogue des Affaires",
        "capture_le": moteur.horloge.maintenant.isoformat(), "revision_ligne_id": revision_id,
        "reponses": captures,
    })


@SQLITE
def test_dossier_natif_deux_faits_exacts_confidentialite_budget_et_refus(moteur, equipe):
    marqueur_prive = "CORPS_PRIVE_FICTIF_NE_DOIT_PAS_SORTIR"
    captures = {}
    admin = equipe["admin"]

    def decision(ident, raison, niveau=None):
        resultat = m10.journaliser_decision({
            "decision_id": ident, "raison": raison, "statut": "proposee",
            "options_ecartees": "Conserver l'installation initiale (fictif).",
        }, DATE, niveau)
        assert resultat["accepte"] is True
        return resultat["decision"]["ligne_id"]

    a = decision("DEC-JOINTS-FICTIVE", "Deux joints de gouttière repris après inspection (fictif).")
    b = decision("DEC-INSPECTION-FICTIVE", "Inspection des deux joints après reprise satisfaisante (fictif).")
    ident = m10.signaler_revision(a, b, DATE)["resultat"]["ligne_id"]
    prive = decision("DEC-CLIENT-DOSSIER-PRIVEE-FICTIVE", marqueur_prive, "CLIENT_PRIVATE")
    tete_privee = m10._REGISTRE_AFFAIRES.tete()

    def lire(label, revision_id):
        avant = empreinte_tables()
        reponse = admin.appeler("m10_lire_revision", {"revision_ligne_id": revision_id})
        assert reponse.ok and not reponse.mesure.tronque, reponse.corps
        assert empreinte_tables() == avant
        texte = json.dumps(reponse.enveloppe, ensure_ascii=False)
        assert len(texte) <= 5400 and marqueur_prive not in texte and tete_privee not in texte
        captures[label] = {"outil": "m10_lire_revision", "args": {"revision_ligne_id": revision_id},
                           "enveloppe": reponse.enveloppe}
        return reponse.metier

    complet = lire("dossier_complet", ident)
    assert complet["accepte"] is True
    dossier = complet["resultat"]
    assert set(dossier) == {"revision", "faits"} and len(dossier["faits"]) == 2
    assert dossier["revision"]["revision_ligne_id"] == ident and dossier["revision"]["statut"] == "en_attente"
    assert [f["champs"]["raison"] for f in dossier["faits"]] == [
        "Deux joints de gouttière repris après inspection (fictif).",
        "Inspection des deux joints après reprise satisfaisante (fictif).",
    ]
    assert [f["reference"]["ligne_id"] for f in dossier["faits"]] == [a, b]
    for fait in dossier["faits"]:
        assert set(fait) == {"reference", "type_entree", "horodatage", "champs"}
        assert set(fait["champs"]) == {"decision_id", "raison", "statut", "options_ecartees"}
        assert fait["reference"]["hash_tete"] == fait["reference"]["ligne_id"]
        assert fait["horodatage"] == DATE
        assert m10.verifier_reference(fait["reference"])["accepte"] is True
    assert lire("dossier_inconnu", "revision-inconnue-fictive")["verdict"]["code"] == (
        "REJ-DOSSIER-REVISION-INCONNUE")
    evenement = m10._REGISTRE_AFFAIRES.ajouter({
        "type_entree": "evenement_memorise", "horodatage": DATE,
        "evenement": "Inspection des joints (source fictive)",
        "preuves": {"photos": ["photo-fictive-1"], "mesure": {"valeur": 2, "unite": "joints"},
                    "confirme": True, "note": None},
    })
    reference_evenement = m10.signaler_revision(a, evenement, DATE)["resultat"]["ligne_id"]
    autre_dossier = lire("dossier_evenement_preuves", reference_evenement)["resultat"]
    assert autre_dossier["faits"][1]["type_entree"] == "evenement_memorise"
    assert autre_dossier["faits"][1]["champs"] == {
        "evenement": "Inspection des joints (source fictive)",
        "preuves": {"photos": ["photo-fictive-1"], "mesure": {"valeur": 2, "unite": "joints"},
                    "confirme": True, "note": None},
    }
    retenu = m10.signaler_revision(prive, b, DATE)["resultat"]["ligne_id"]
    assert lire("dossier_confidentialite", retenu)["verdict"]["code"] == "REJ-DOSSIER-REVISION-RETENU"
    enorme = decision("DEC-DOSSIER-LONGUE-FICTIVE", "Raison métier fictive entière. " * 300)
    grand = m10.signaler_revision(enorme, b, DATE)["resultat"]["ligne_id"]
    assert lire("dossier_hors_budget", grand)["verdict"]["code"] == "REJ-DOSSIER-REVISION-BUDGET-DEPASSE"
    non_comparable = m10._REGISTRE_AFFAIRES.ajouter({
        "type_entree": "memoire_developpement", "horodatage": DATE, "corps": marqueur_prive,
    })
    controle = m10.signaler_revision(non_comparable, b, DATE)["resultat"]["ligne_id"]
    assert lire("dossier_source_non_comparable", controle)["verdict"]["code"] == (
        "REJ-DOSSIER-REVISION-TYPE-FAIT-INTERDIT")
    with stockage.transaction() as cnx:
        identite.activer(cnx, "nathan", False)
    assert lire("dossier_identite_revoquee", ident)["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    _capturer("dossier", {
        "fictif": True, "provenance": "HTTP/SQLite réel ; porte Core rejouée Python ; décisions M10, événement fixture",
        "capture_le": moteur.horloge.maintenant.isoformat(), "revision_ligne_id": ident, "reponses": captures,
    })
