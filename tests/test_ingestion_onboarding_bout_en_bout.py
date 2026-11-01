"""Bout en bout : ZIP d'onboarding déposé -> factures en brouillon AP (M5) + clients en brouillon CRM (M2) -> décision
humaine dans la file d'approbation -> données DÉFINITIVES ; et tout ce qui doit être refusé en chemin.

Vrai socle : base SQLite migrée, vrais manifestes de M5 et de M2 (mode `ombre`), vrais outils, vraie file
d'approbation (`Capacites.appeler` puis `approbations.decider`), vrai registre de fournisseurs (fournisseur d'extraction
SIMULÉ déclaré, activé sous la politique et sélectionné). Le seul substitut : le code du worker PDF natif exécuté dans
le processus de test (bubblewrap manque dans le bac à sable). Corpus et personnes fictifs.
"""

from __future__ import annotations

import json
from pathlib import Path

import ingestion_onboarding_qa as qa
import m5_financecore.outils as m5_outils
import pytest
import yaml
from m2_revenue_crm import outils as m2_outils
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION

from opsys import approbations, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.ingestion_onboarding import extraction_texte, service
from opsys.outils import Niveau, executer_atomique

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
M5, M2 = "m05-financecore", "m02-revenue-crm"
QUAND = "2026-10-31T11:00:00-04:00"


@pytest.fixture
def instance(tmp_path, monkeypatch):
    url = qa.preparer_instance(tmp_path, monkeypatch)
    monkeypatch.setattr(extraction_texte, "extracteur_pdf_isole", qa.extracteur_pdf_en_processus)
    manifeste = tmp_path / "m5-department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {"categories_depense_sans_po": ["materiaux", "outils"]}}),
                         encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    m5_outils.utiliser_stockage_durable()
    m2_outils.utiliser_stockage_durable()
    return url


@pytest.fixture
def deps():
    return {M5: lire_manifeste(RACINE / "departments" / M5), M2: lire_manifeste(RACINE / "departments" / M2)}


@pytest.fixture
def capacites(deps):
    return Capacites(deps, stockage.transaction)


def _deballer(reponse):
    """La réponse de l'outil, sous l'enveloppe `{"ok", "resultat"}` de `Capacites.appeler` s'il y en a une."""
    if isinstance(reponse, dict) and "ok" in reponse and "accepte" not in reponse:
        assert reponse["ok"] is True, reponse
        return reponse["resultat"]
    return reponse


def _accepte(reponse):
    reponse = _deballer(reponse)
    assert reponse.get("accepte") is True, reponse
    return reponse["resultat"]


def _code(reponse):
    reponse = _deballer(reponse)
    assert reponse.get("accepte") is False, reponse
    return reponse["verdict"]["code"]


def _decider(deps, demande, *, role="nathan_owner"):
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, demande["demande_id"], True, "nathan",
                                    outils_executables(deps, stockage.transaction), deps, role=role)


def _resultat_decision(decision):
    """La réponse de l'outil que la décision humaine vient d'exécuter."""
    accepte = _deballer(decision["reponse"]).get("accepte")
    assert decision["statut"] == ("executee" if accepte else "echec"), decision
    return decision["reponse"]


def _maillons(departement, registre):
    with stockage.transaction():
        return list(stockage.maillons(departement, registre))


def _lot_complet(capacites):
    qa.deposer_fichier("onboarding-synergy.zip", qa.zip_onboarding(qa.corpus_complet()))
    lot = _accepte(capacites.appeler("m5_deposer_lot_onboarding",
                                     {"fichier": "onboarding-synergy.zip", "mutation_id": "onboarding-1"}))
    avance = _accepte(capacites.appeler("m5_avancer_lot_onboarding", {"lot_id": lot["lot_id"], "budget": 500}))
    assert avance["statut"] == "TERMINE", avance["compteurs"]
    # 13 documents à traiter, 7 tâches chacun : 77 exécutées, 14 sautées après un verdict (classe, image, sens).
    assert avance["compteurs"]["taches"] == {"TERMINEE": 77, "SAUTEE": 14}
    assert avance["taches_executees"] == 77 and avance["baux_perdus"] == 0
    return {"lot_id": lot["lot_id"], "documents": _tout(capacites, lot["lot_id"], "documents"),
            "brouillons": _tout(capacites, lot["lot_id"], "brouillons")}


def _tout(capacites, lot_id, vue):
    """Toutes les pages d'une vue (chaque page tient dans la sortie d'un outil, sans troncature)."""
    elements, depart = [], 0
    while depart is not None:
        page = _accepte(capacites.appeler("m5_lire_lot_onboarding", {"lot_id": lot_id, "vue": vue,
                                                                     "depart": depart, "limite": 15}))
        assert page["mention"] == MENTION
        elements.extend(page[vue])
        depart = page["suivant"]
    return elements


def _brouillon(capacites, lot, brouillon_id):
    lu = _accepte(capacites.appeler("m5_lire_lot_onboarding", {"lot_id": lot["lot_id"], "brouillon_id": brouillon_id}))
    assert lu["mention"] == MENTION, "sortie d'analyse : la mention obligatoire de M5"
    return lu["brouillon"]


def _par_fournisseur(capacites, lot):
    index = {}
    for b in lot["brouillons"]:
        if b["genre"] == "ap_facture_fournisseur":
            contenu = _brouillon(capacites, lot, b["brouillon_id"])["contenu"]
            index[contenu["validation"]["facture"]["fournisseur"]] = b
    return index


def _par_lignes(capacites, lot):
    index = {}
    for b in lot["brouillons"]:
        if b["genre"] == "crm_client":
            contenu = _brouillon(capacites, lot, b["brouillon_id"])["contenu"]
            index[tuple(contenu["fiche"]["lignes"])] = b
    return index


def _args_ap(brouillon, **surcharges):
    return {"brouillon_id": brouillon["brouillon_id"], "revision_attendue": brouillon["revision"],
            "decision": "valider", "categorie": "materiaux", "motif": None, "horodatage": QUAND, **surcharges}


def _args_crm(brouillon, **surcharges):
    return {"brouillon_id": brouillon["brouillon_id"], "revision_attendue": brouillon["revision"],
            "decision": "valider", "choix": None, "motif": None, "horodatage": QUAND, **surcharges}


def test_les_outils_ont_leur_niveau_et_restent_fermes_aux_appareils():
    par_nom = {o.nom: o for o in (*m5_outils.outils(), *m2_outils.outils())}
    niveaux = {nom: par_nom[nom].niveau_effectif for nom in (
        "m5_deposer_lot_onboarding", "m5_avancer_lot_onboarding", "m5_lire_lot_onboarding",
        "m5_valider_brouillon_onboarding_ap", "m2_valider_brouillon_onboarding_client", "m2_lister_clients_importes")}
    assert niveaux == {"m5_deposer_lot_onboarding": Niveau.N1, "m5_avancer_lot_onboarding": Niveau.N1,
                       "m5_lire_lot_onboarding": Niveau.N0, "m5_valider_brouillon_onboarding_ap": Niveau.N3,
                       "m2_valider_brouillon_onboarding_client": Niveau.N3, "m2_lister_clients_importes": Niveau.N0}
    assert all(par_nom[nom].roles_appareil == frozenset() for nom in niveaux)


def test_zip_depose_brouillons_ap_et_crm_puis_validation_humaine_puis_definitif(instance, deps, capacites):
    lot = _lot_complet(capacites)
    documents = {d["nom"]: (d["statut"], d["code"]) for d in lot["documents"]}
    assert documents == {
        "factures/F1-quincaillerie.pdf": ("TERMINE", None), "factures/F2-materiaux.pdf": ("TERMINE", None),
        "factures/F3-location-tvq.pdf": ("A_VERIFIER", None), "factures/F4-peinture-sommes.txt": ("A_VERIFIER", None),
        "factures/F5-emise-par-nous.txt": ("NON_TRAITE", "REJ-ING-CLASSE-NON-PEUPLEE"),
        "factures/F6-date-future.txt": ("A_VERIFIER", None), "factures/F7-sans-numero-tps.txt": ("A_VERIFIER", None),
        "copies/F1-quincaillerie-copie.pdf": ("DOUBLON", None), "copies/F1-quincaillerie.txt": ("TERMINE", None),
        "autres/soumission-toiture.txt": ("NON_TRAITE", "REJ-ING-CLASSE-NON-PEUPLEE"),
        "autres/contrat-entretien.txt": ("NON_TRAITE", "REJ-ING-CLASSE-NON-PEUPLEE"),
        "autres/notes-reunion.txt": ("NON_TRAITE", "REJ-ING-CLASSE-INCONNUE"),
        "clients/clients.csv": ("A_VERIFIER", None),
        "autres/photo-chantier.png": ("NON_TRAITE", "REJ-ING-IMAGE-NON-TRAITEE"),
        "autres/outil.exe": ("REFUSE", "REJ-ING-TYPE-NON-ACCEPTE"),
        "autres/faux.pdf": ("REFUSE", "REJ-ING-TYPE-INCOHERENT"),
    }
    ap = _par_fournisseur(capacites, lot)
    assert {nom: (b["statut"], b["raisons"]) for nom, b in ap.items()} == {
        "Quincaillerie Fictive Laval inc.": ("PRET", []),
        "Matériaux Fictifs Rive-Sud": ("PRET", []),
        "Location Fictive d'Outils": ("A_VERIFIER", ["REJ-ING-FACTURE-TOTAL-ECART", "REJ-ING-FACTURE-TVQ-ECART"]),
        "Peinture Fictive Express": ("A_VERIFIER", ["REJ-ING-FACTURE-NO-TPS-FORME", "REJ-ING-FACTURE-SOMME-LIGNES"]),
        "Béton Fictif": ("A_VERIFIER", ["REJ-ING-FACTURE-DATE-FUTURE"]),
        "Petit Fournisseur Fictif": ("A_VERIFIER", ["REJ-ING-FACTURE-NO-TPS-ABSENT", "REJ-ING-FACTURE-NO-TVQ-ABSENT"]),
    }
    detail = _brouillon(capacites, lot, ap["Location Fictive d'Outils"]["brouillon_id"])["contenu"]["validation"]
    assert {r["code"]: r["detail"] for r in detail["raisons"]}["REJ-ING-FACTURE-TVQ-ECART"] == (
        "TVQ imprimée 29.92, recalculée 29.93 (9,975 % de 300.00, au cent)")
    assert detail["facture"]["tvq"] == "29.92", "jamais corrigée en silence"
    crm = _par_lignes(capacites, lot)
    assert {lignes: b["statut"] for lignes, b in crm.items()} == {
        (2, 3): "PRET", (4, 5): "PRET", (6, 7): "A_VERIFIER", (8,): "A_VERIFIER", (9,): "A_VERIFIER"}
    fusion = _brouillon(capacites, lot, crm[(2, 3)]["brouillon_id"])["contenu"]["fiche"]["fusions"]
    assert fusion == [{"regle": "courriel_identique", "lignes": [2, 3],
                       "valeur_normalisee": "marie.tremblay@exemple.test"}]

    # Rien n'est définitif avant un humain : ni facture, ni grand livre, ni mouvement, ni client.
    assert _maillons(M5, "comptes_a_payer") == [] and _maillons(M5, "grand_livre") == []
    assert _maillons(M5, "principal") == [] and _maillons(M2, "clients_importes") == []

    # --------------------------------------------------------------------------- AP : l'agent seul ne saisit rien
    f1 = ap["Quincaillerie Fictive Laval inc."]
    par_nom = {o.nom: o for o in m5_outils.outils()}
    assert _code(executer_atomique(par_nom["m5_valider_brouillon_onboarding_ap"], _args_ap(f1))) == \
        "REJ-AP-HUMAIN-REQUIS"
    decision = _decider(deps, capacites.appeler("m5_valider_brouillon_onboarding_ap", _args_ap(f1)))
    saisie = _accepte(_resultat_decision(decision))
    assert saisie["mention"] == MENTION
    facture = saisie["facture"]
    assert (facture["fournisseur_id"], facture["numero_facture"], facture["montant_avant_taxes"],
            facture["montant_apres_taxes"]) == ("Quincaillerie Fictive Laval inc.", "QF-2026-0418", "304.00", "349.52")
    assert saisie["brouillon"]["statut"] == "VALIDE"
    assert saisie["brouillon"]["reference_definitive"] == facture["facture_fournisseur_id"]
    assert saisie["brouillon"]["decision"]["voie"] == "approbation"
    [piece] = _maillons(M5, "comptes_a_payer")
    assert (piece["type_entree"], piece["categorie_depense"], piece["saisi_par"], piece["voie"]) == (
        "facture_fournisseur_saisie", "materiaux", "nathan", "approbation")

    # Rejeu, révision périmée, catégorie hors liste, brouillon à vérifier : refusés, rien d'écrit.
    rejeu = _resultat_decision(_decider(deps, capacites.appeler("m5_valider_brouillon_onboarding_ap",
                                                                _args_ap(f1, revision_attendue=2))))
    assert _code(rejeu) == "REJ-ING-BROUILLON-DEJA-DECIDE"
    f2 = ap["Matériaux Fictifs Rive-Sud"]
    perime = _resultat_decision(_decider(deps, capacites.appeler("m5_valider_brouillon_onboarding_ap",
                                                                 _args_ap(f2, revision_attendue=7))))
    assert _code(perime) == "REJ-ING-BROUILLON-REVISION"
    hors_liste = _resultat_decision(_decider(deps, capacites.appeler("m5_valider_brouillon_onboarding_ap",
                                                                     _args_ap(f2, categorie="carburant"))))
    assert _code(hors_liste) == "REJ-AP-CATEGORIE-INCONNUE"
    f3 = ap["Location Fictive d'Outils"]
    a_verifier = _resultat_decision(_decider(deps, capacites.appeler("m5_valider_brouillon_onboarding_ap",
                                                                     _args_ap(f3))))
    assert _code(a_verifier) == "REJ-ING-BROUILLON-A-VERIFIER"
    assert "saisir la facture à la main" in _deballer(a_verifier)["verdict"]["detail"], \
        "refusé AVANT toute revalidation : un brouillon à vérifier n'est jamais validé tel quel"
    assert len(_maillons(M5, "comptes_a_payer")) == 1

    # F2 validée (catégorie de la liste) ; F3 écartée avec motif (sans motif : refus).
    _accepte(_resultat_decision(_decider(deps, capacites.appeler("m5_valider_brouillon_onboarding_ap",
                                                                 _args_ap(f2, categorie="outils")))))
    sans_motif = _resultat_decision(_decider(deps, capacites.appeler(
        "m5_valider_brouillon_onboarding_ap", _args_ap(f3, decision="ecarter", categorie=None))))
    assert _code(sans_motif) == "REJ-ING-MOTIF-REQUIS"
    ecarte = _accepte(_resultat_decision(_decider(deps, capacites.appeler(
        "m5_valider_brouillon_onboarding_ap",
        _args_ap(f3, decision="ecarter", categorie=None, motif="TVQ mal arrondie : facture corrigée demandée")))))
    assert ecarte["brouillon"]["statut"] == "ECARTE" and ecarte["mention"] == MENTION
    assert [str(p["montant_avant_taxes"]) for p in _maillons(M5, "comptes_a_payer")] == ["304.00", "100.50"]
    assert _maillons(M5, "grand_livre") == [] and _maillons(M5, "principal") == []

    # ------------------------------------------------------------------------------------ CRM : fiches définitives
    par_nom_m2 = {o.nom: o for o in m2_outils.outils()}
    marie = crm[(2, 3)]
    assert _code(executer_atomique(par_nom_m2["m2_valider_brouillon_onboarding_client"], _args_crm(marie))) == \
        "REJ-HUMAIN-REQUIS"
    client = _accepte(_resultat_decision(_decider(deps, capacites.appeler(
        "m2_valider_brouillon_onboarding_client", _args_crm(marie)))))
    toitures = crm[(6, 7)]
    sans_choix = _resultat_decision(_decider(deps, capacites.appeler("m2_valider_brouillon_onboarding_client",
                                                                     _args_crm(toitures))))
    assert _code(sans_choix) == "REJ-CLIENT-IMPORT-CHOIX-INVALIDE"
    _accepte(_resultat_decision(_decider(deps, capacites.appeler(
        "m2_valider_brouillon_onboarding_client",
        _args_crm(toitures, choix={"courriel": "info@toitures-bedard.test"})))))
    sophie = crm[(8,)]
    invalide = _resultat_decision(_decider(deps, capacites.appeler("m2_valider_brouillon_onboarding_client",
                                                                   _args_crm(sophie))))
    assert _code(invalide) == "REJ-CLIENT-IMPORT-INVALIDE"
    _accepte(_resultat_decision(_decider(deps, capacites.appeler(
        "m2_valider_brouillon_onboarding_client",
        _args_crm(sophie, decision="ecarter", motif="courriel incomplet : à recontacter")))))
    importes = _accepte(capacites.appeler("m2_lister_clients_importes", {}))
    assert importes["total"] == 2
    assert [c["contact"]["courriel"] for c in importes["clients"]] == [
        "marie.tremblay@exemple.test", "info@toitures-bedard.test"]
    assert importes["clients"][0]["client_id"] == client["client_id"]
    assert all(c["voie"] == "approbation" and c["importe_par"] == "nathan" for c in importes["clients"])

    # ------------------------------------------------------------- nouveau dépôt : rien n'est reproposé en double
    qa.deposer_fichier("onboarding-synergy.zip", qa.zip_onboarding(qa.corpus_complet()))
    second = _accepte(capacites.appeler("m5_deposer_lot_onboarding",
                                        {"fichier": "onboarding-synergy.zip", "mutation_id": "onboarding-2"}))
    assert set(second["compteurs"]["documents"]) <= {"DOUBLON", "REFUSE"} and second["statut"] == "TERMINE"
    liste = (qa.CORPUS / "clients.csv").read_text(encoding="utf-8") + \
        "Marie Tremblay (fictive),MARIE.TREMBLAY@exemple.test,514 555 0101,,,\n"
    qa.deposer_fichier("clients-mise-a-jour.csv", liste.encode("utf-8"))
    troisieme = _accepte(capacites.appeler("m5_deposer_lot_onboarding",
                                           {"fichier": "clients-mise-a-jour.csv", "mutation_id": "onboarding-3"}))
    _accepte(capacites.appeler("m5_avancer_lot_onboarding", {"lot_id": troisieme["lot_id"]}))
    assert _tout(capacites, troisieme["lot_id"], "brouillons") == [], (
        "chaque fiche se rattache à un client importé ou à un brouillon existant")
    with stockage.transaction() as cnx:
        [tache] = [t for t in service.journal(cnx, troisieme["lot_id"]) if t["evenement"] == "tache.terminee"
                   and t["details"]["etape"] == "proposition"]
    assert tache["code"] is None


def test_lire_un_brouillon_d_un_autre_lot_et_un_lot_inconnu(instance, capacites):
    lot = _lot_complet(capacites)
    brouillon_id = lot["brouillons"][0]["brouillon_id"]
    assert _code(capacites.appeler("m5_lire_lot_onboarding", {"lot_id": "0" * 32})) == "REJ-ING-LOT-INCONNU"
    assert _code(capacites.appeler("m5_lire_lot_onboarding", {"lot_id": "0" * 32, "brouillon_id": brouillon_id})) \
        == "REJ-ING-BROUILLON-INCONNU"
    assert _code(capacites.appeler("m5_deposer_lot_onboarding", {"fichier": "../x.zip", "mutation_id": "m"})) == \
        "REJ-ING-NOM-INVALIDE"
    contenu = json.dumps(lot, ensure_ascii=False)
    assert "Quincaillerie" not in contenu and "marie.tremblay" not in contenu, \
        "la vue d'un lot ne porte que des métadonnées"


def test_la_revalidation_au_moment_de_decider_refuse_un_brouillon_devenu_incoherent(instance, deps, capacites):
    """Le brouillon était PRET au dépôt ; l'identité fiscale déclarée change avant la décision : la facture n'est plus
    adressée à l'entreprise, la validation est refusée et rien n'est saisi."""
    lot = _lot_complet(capacites)
    f1 = _par_fournisseur(capacites, lot)["Quincaillerie Fictive Laval inc."]
    autre = {"nom_legal": "Autre Entreprise Fictive", "tps": "111111118 RT 0001", "tvq": "1111111111 TQ 0001"}
    (stockage.dossier_opsys() / "entreprise.yaml").write_text(yaml.safe_dump({"identite_fiscale": autre}),
                                                              encoding="utf-8")
    refus = _resultat_decision(_decider(deps, capacites.appeler("m5_valider_brouillon_onboarding_ap", _args_ap(f1))))
    assert _code(refus) == "REJ-ING-BROUILLON-A-VERIFIER"
    assert "REJ-ING-FACTURE-DESTINATAIRE-NON-RECONNU" in _deballer(refus)["verdict"]["detail"]
    assert _maillons(M5, "comptes_a_payer") == []
