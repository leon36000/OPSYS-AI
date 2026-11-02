"""Les outils de réglages de direction de M9 (CFG-1) : lire ce qui manque, adopter, revenir — par le VRAI sas N3.

Prouve : la surface (trois outils, niveaux N0 / N3 / N3, aucun droit d'appareil, schémas fermés) ; un appel
direct, d'agent ou de test sans approbation humaine est refusé AVANT toute écriture (« jamais d'auto-adoption ») ;
l'approbation du propriétaire dans le sas écrit UN maillon signé par lui, avec l'instant de la décision du serveur ;
un administrateur sans le rôle propriétaire est refusé par le sas, une décision forgée sous un autre rôle, pour un
autre outil ou à un autre niveau est refusée par l'outil ; un agent qui appelle l'outil ne fait que déposer une
demande ; hors bornes, mauvais type, clé inconnue, version périmée, double adoption et retour arrière ; le journal
d'audit ne porte ni la raison ni la valeur. Données fictives.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import select, update

from opsys import approbations, contexte, stockage
from opsys.capacites import Capacites
from opsys.outils import Autonomie, Niveau
from opsys.reglages import magasin
from opsys.stockage.schema import APPROBATIONS, JOURNAL

_spec = importlib.util.spec_from_file_location(
    "reglages_aide", Path(__file__).resolve().parents[3] / "tests" / "reglages_aide.py")
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)

FICTIF = True
CLE = "m2.jours_entre_relances"


@pytest.fixture
def deps(tmp_path, monkeypatch):
    yield aide.installer(tmp_path, monkeypatch)
    stockage.liberer()


def _outils(deps):
    return {o.nom: o for o in deps[aide.M9].charger_outils()}


# -- la surface -----------------------------------------------------------------------------------------------
def test_surface_trois_outils_niveaux_exacts_et_aucun_droit_d_appareil(deps):
    outils = _outils(deps)
    lire, adopter, revenir = (outils[n] for n in ("m9_lire_reglages_manquants", "m9_adopter_reglage",
                                                   "m9_revenir_sur_reglage"))
    assert (lire.autonomie, lire.niveau_effectif) == (Autonomie.T0, Niveau.N0)
    assert lire.roles_appareil == frozenset(), "aucun droit d'appareil n'est ajouté par ce chantier"
    for ecriture in (adopter, revenir):
        assert ecriture.autonomie is Autonomie.T1 and ecriture.niveau_effectif is Niveau.N3
        assert ecriture.roles_appareil == frozenset() and ecriture.frontiere_humaine is False
        assert ecriture.portee_contexte == "globale", "un réglage d'entreprise n'est lié à aucune affaire"
    assert set(adopter.parametres["required"]) == {"cle", "valeur", "raison"}
    assert set(revenir.parametres["required"]) == {"cle", "raison"}
    for outil in (lire, adopter, revenir):
        assert outil.parametres["additionalProperties"] is False and len(outil.description) <= 1024
    assert not {"par", "role", "quand", "approbation_id", "origine"} & set(adopter.parametres["properties"])


# -- jamais d'auto-adoption -----------------------------------------------------------------------------------
def test_un_appel_direct_sans_approbation_humaine_est_refuse_avant_toute_ecriture(deps):
    outils = _outils(deps)
    with stockage.transaction():
        for nom, args in (("m9_adopter_reglage", {"cle": CLE, "valeur": 7, "raison": "Essai sans sas"}),
                          ("m9_revenir_sur_reglage", {"cle": CLE, "raison": "Essai sans sas"})):
            with pytest.raises(ValueError, match="REJ-HUMAIN-REQUIS"):
                outils[nom].fonction(**args)
        assert magasin.lire_chaine() == []


def test_un_appel_atomique_direct_sous_identite_d_admin_ou_d_agent_est_refuse(deps):
    from opsys.outils import executer_atomique

    outil = _outils(deps)["m9_adopter_reglage"]
    for identite_appelante in (None, contexte.IdentiteAppelante(aide.ADMIN, "admin", source="console"),
                               contexte.IdentiteAppelante(aide.PROPRIETAIRE, "nathan_owner", source="appareil")):
        arguments = {"cle": CLE, "valeur": 7, "raison": "Essai sous une identité"}
        if identite_appelante is None:
            reponse = executer_atomique(outil, arguments)
        else:
            with contexte.appele_par_appareil(identite_appelante):
                reponse = executer_atomique(outil, arguments)
        assert reponse["ok"] is False and "REJ-HUMAIN-REQUIS" in reponse["details"], identite_appelante
    assert aide.chaine() == []


def test_un_agent_qui_appelle_l_outil_ne_fait_que_deposer_une_demande_en_attente(deps):
    capacites = Capacites({aide.M9: deps[aide.M9]}, stockage.transaction, appelant=aide.M9, memoire=False)
    reponse = capacites.appeler("m9_adopter_reglage", {"cle": CLE, "valeur": 7, "raison": "Proposition de l'agent"})
    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation", reponse
    assert aide.chaine() == []
    with stockage.transaction() as cnx:
        (ligne,) = cnx.execute(select(APPROBATIONS.c.statut, APPROBATIONS.c.niveau, APPROBATIONS.c.outil)).all()
    assert tuple(ligne) == ("en_attente", "N3", "m9_adopter_reglage")


def test_l_approbation_du_proprietaire_dans_le_sas_ecrit_un_maillon_signe_par_lui(deps):
    with stockage.transaction() as cnx:
        decision = aide.adopter(cnx, deps, CLE, 7)
        resultat = aide.resultat(decision)
        ligne = cnx.execute(select(APPROBATIONS.c.decide_le, APPROBATIONS.c.decide_par, APPROBATIONS.c.decide_role,
                                   APPROBATIONS.c.id)).one()
    (maillon,) = aide.chaine()
    assert resultat["statut"] == "adopte" and resultat["valeur"] == 7 and resultat["origine"] == "proposition"
    assert (maillon["par"], maillon["role"]) == (aide.PROPRIETAIRE, "nathan_owner")
    assert maillon["approbation_id"] == ligne.id == decision["id"]
    assert maillon["quand"].startswith(ligne.decide_le[:19]), "l'instant est celui de la décision du serveur"


def test_l_instant_ecrit_est_l_horloge_du_serveur_pas_un_argument_de_l_agent(deps):
    schema = _outils(deps)["m9_adopter_reglage"].parametres["properties"]
    assert "quand" not in schema and "horodatage" not in schema and "maintenant" not in schema
    with stockage.transaction() as cnx:
        aide.adopter(cnx, deps, CLE, 7)
    assert aide.chaine()[0]["quand"].endswith("+00:00")


def test_un_administrateur_sans_le_role_proprietaire_est_refuse_par_le_sas_et_rien_n_est_ecrit(deps):
    with stockage.transaction() as cnx:
        outil = aide.outil_m9(deps, "m9_adopter_reglage")
        ident = approbations.creer_demande(cnx, aide.M9, outil.nom, {"cle": CLE, "valeur": 7, "raison": "Tentative"},
                                           niveau=Niveau.N3)
        for personne, role in ((aide.ADMIN, "admin"), (aide.EMPLOYE, "employee"), ("inconnu.fictif", None)):
            with pytest.raises(ValueError):
                approbations.decider(cnx, ident, True, personne, {outil.nom: outil}, deps, role=role)
        statut = cnx.execute(select(APPROBATIONS.c.statut)).scalar_one()
    assert statut == "en_attente" and aide.chaine() == []


def test_le_proprietaire_ne_peut_pas_approuver_sous_le_role_d_admin(deps):
    with stockage.transaction() as cnx:
        outil = aide.outil_m9(deps, "m9_adopter_reglage")
        ident = approbations.creer_demande(cnx, aide.M9, outil.nom, {"cle": CLE, "valeur": 7, "raison": "Tentative"},
                                           niveau=Niveau.N3)
        with pytest.raises(ValueError):
            approbations.decider(cnx, ident, True, aide.PROPRIETAIRE, {outil.nom: outil}, deps, role="admin")
    assert aide.chaine() == []


def test_une_decision_refusee_n_ecrit_rien(deps):
    with stockage.transaction() as cnx:
        decision = aide.decider(cnx, deps, "m9_adopter_reglage", {"cle": CLE, "valeur": 7, "raison": "À refuser"},
                                role="nathan_owner", approuver=False)
    assert decision["statut"] == "refusee" and aide.chaine() == []


def _forcer_en_cours(cnx, nom, arguments, *, decide_par=aide.PROPRIETAIRE, decide_role="nathan_owner", niveau=Niveau.N3,
                     departement=aide.M9):
    """La ligne que `decider` écrit au moment d'exécuter, forgée : pour prouver ce que l'OUTIL refuse seul."""
    ident = approbations.creer_demande(cnx, departement, nom, arguments, niveau=niveau)
    cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
        statut="en_cours", decide_par=decide_par, decide_role=decide_role, decide_le="2026-11-02T15:00:00+00:00"))
    return ident


@pytest.mark.parametrize(("variante", "code"), [
    ({"decide_role": "admin"}, "REJ-HUMAIN-REQUIS"),
    ({"decide_role": "system_agent"}, "REJ-HUMAIN-REQUIS"),
    ({"decide_role": "client"}, "REJ-HUMAIN-REQUIS"),
    ({"decide_par": "inconnu.fictif"}, "REJ-HUMAIN-REQUIS"),
    ({"decide_par": aide.EMPLOYE}, "REJ-HUMAIN-REQUIS"),
    ({"niveau": Niveau.N4}, "REJ-REGLAGE-NIVEAU"),
    ({"niveau": Niveau.N5}, "REJ-REGLAGE-NIVEAU"),
    ({"departement": "m02-revenue-crm"}, "REJ-HUMAIN-REQUIS"),
])
def test_une_decision_forgee_est_refusee_par_l_outil_lui_meme(deps, variante, code):
    arguments = {"cle": CLE, "valeur": 7, "raison": "Décision forgée"}
    outil = _outils(deps)["m9_adopter_reglage"]
    with stockage.transaction() as cnx:
        ident = _forcer_en_cours(cnx, "m9_adopter_reglage", arguments, **variante)
        with contexte.executer_demande_approuvee(ident), pytest.raises(ValueError, match=code):
            outil.fonction(**arguments)
        assert magasin.lire_chaine() == []


def test_une_approbation_donnee_a_un_autre_outil_ne_sert_pas_a_adopter(deps):
    arguments = {"cle": CLE, "valeur": 7, "raison": "Réutilisation d'une approbation"}
    outil = _outils(deps)["m9_adopter_reglage"]
    with stockage.transaction() as cnx:
        ident = _forcer_en_cours(cnx, "m9_revenir_sur_reglage", {"cle": CLE, "raison": "Autre geste"})
        with contexte.executer_demande_approuvee(ident), pytest.raises(ValueError, match="REJ-HUMAIN-REQUIS"):
            outil.fonction(**arguments)
        # une demande déjà exécutée (et non en cours) n'autorise plus rien non plus
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(statut="executee"))
        with contexte.executer_demande_approuvee(ident), pytest.raises(ValueError, match="REJ-HUMAIN-REQUIS"):
            _outils(deps)["m9_revenir_sur_reglage"].fonction(cle=CLE, raison="Rejeu")


def test_une_demande_d_un_niveau_inferieur_n_est_pas_acceptee_pour_un_reglage_n3(deps):
    arguments = {"cle": CLE, "valeur": 7, "raison": "Niveau trop bas"}
    outil = _outils(deps)["m9_adopter_reglage"]
    with stockage.transaction() as cnx:
        ident = _forcer_en_cours(cnx, "m9_adopter_reglage", arguments, niveau=Niveau.N2)
        with contexte.executer_demande_approuvee(ident), pytest.raises(ValueError, match="REJ-REGLAGE-NIVEAU"):
            outil.fonction(**arguments)


# -- les refus de contenu ------------------------------------------------------------------------------------
@pytest.mark.parametrize(("cle", "valeur", "code"), [
    (CLE, 0, "REJ-REGLAGE-HORS-BORNES"),
    (CLE, 3651, "REJ-REGLAGE-HORS-BORNES"),
    (CLE, "7", "REJ-REGLAGE-TYPE"),
    (CLE, 7.5, "REJ-REGLAGE-TYPE"),
    ("m2.bandes_valeur_cents", [3, 2, 1], "REJ-REGLAGE-FORME"),
    ("m2.bandes_valeur_cents", [1, 2], "REJ-REGLAGE-FORME"),
    ("m8.bornes_taux_acceptation_pct", {"pire": 60, "cible": 20}, "REJ-REGLAGE-FORME"),
    ("m8.bornes_taux_acceptation_pct", {"pire": 20, "cible": 160}, "REJ-REGLAGE-HORS-BORNES"),
    ("m8.bornes_devis_sans_reponse", {"pire": 0, "cible": 10}, "REJ-REGLAGE-FORME"),
    ("m2.inexistant", 7, "REJ-REGLAGE-INCONNU"),
    ("m8.jours_entre_relances", 7, "REJ-REGLAGE-INCONNU"),
])
def test_une_valeur_invalide_ou_un_reglage_inconnu_est_refuse_et_la_demande_echoue(deps, cle, valeur, code):
    with stockage.transaction() as cnx:
        decision = aide.adopter(cnx, deps, cle, valeur)
        assert code in aide.refus(decision), decision
    assert aide.chaine() == []


def test_une_clef_hors_motif_ou_un_argument_en_trop_est_refuse_par_le_schema(deps):
    with stockage.transaction() as cnx:
        decision = aide.decider(cnx, deps, "m9_adopter_reglage", {"cle": "M2 jours", "valeur": 7, "raison": "Motif"},
                                role="nathan_owner")
        assert decision["statut"] == "echec"
        decision = aide.decider(cnx, deps, "m9_adopter_reglage",
                                {"cle": CLE, "valeur": 7, "raison": "Motif valide", "par": "autre"},
                                role="nathan_owner")
        assert decision["statut"] == "echec"
    assert aide.chaine() == []


def test_double_adoption_idempotente_version_perimee_et_retour_arriere_par_le_sas(deps):
    with stockage.transaction() as cnx:
        premier = aide.resultat(aide.adopter(cnx, deps, CLE, 7, version_attendue=0))
        deuxieme = aide.resultat(aide.adopter(cnx, deps, CLE, 7, version_attendue=0, raison="Double clic"))
        assert (premier["statut"], deuxieme["statut"], deuxieme["version"]) == ("adopte", "deja_adopte", 1)
        perimee = aide.adopter(cnx, deps, CLE, 10, version_attendue=0)
        assert "REJ-REGLAGE-VERSION" in aide.refus(perimee)
        autre = aide.resultat(aide.adopter(cnx, deps, CLE, 10, version_attendue=1))
        assert autre["version"] == 2 and autre["ancienne_valeur"] == 7
        retour = aide.resultat(aide.revenir(cnx, deps, CLE))
        assert retour["statut"] == "retour_arriere" and retour["valeur"] == 7
        retour = aide.resultat(aide.revenir(cnx, deps, CLE))
        assert retour["valeur"] is None
        assert "REJ-REGLAGE-RIEN-A-ANNULER" in aide.refus(aide.revenir(cnx, deps, CLE))
    assert [m["type"] for m in aide.chaine()] == ["adoption", "adoption", "retour_arriere", "retour_arriere"]


def test_une_raison_avec_renseignement_personnel_est_refusee_par_l_outil(deps):
    with stockage.transaction() as cnx:
        decision = aide.adopter(cnx, deps, CLE, 7, raison="Voir avec marie.tremblay@example.test")
        assert "REJ-REGLAGE-RAISON-PII" in aide.refus(decision)
    assert aide.chaine() == []


def test_le_journal_d_audit_ne_porte_ni_la_raison_ni_la_valeur_ni_le_signataire_en_clair_dans_les_details(deps):
    raison = "Raison confidentielle de la direction numéro 4242"
    with stockage.transaction() as cnx:
        aide.resultat(aide.adopter(cnx, deps, CLE, 7, raison=raison))
        aide.resultat(aide.revenir(cnx, deps, CLE, raison=raison))
        lignes = cnx.execute(select(JOURNAL)).mappings().all()
    audit = [dict(ligne) for ligne in lignes if str(ligne["action"]).startswith("reglage.")]
    assert sorted(a["action"] for a in audit) == ["reglage.adopter", "reglage.revenir"]
    for ligne in lignes:
        texte = json.dumps({k: str(v) for k, v in ligne.items()}, ensure_ascii=False)
        assert raison not in texte and "4242" not in texte, ligne
    for ligne in audit:
        details = json.loads(ligne["details"])
        assert set(details) == {"version", "empreinte", "departement"} and details["departement"] == "m02-revenue-crm"


def test_une_double_adoption_ne_laisse_qu_une_ligne_d_audit(deps):
    with stockage.transaction() as cnx:
        aide.resultat(aide.adopter(cnx, deps, CLE, 7))
        aide.resultat(aide.adopter(cnx, deps, CLE, 7, raison="Double clic"))
        actions = [a for (a,) in cnx.execute(select(JOURNAL.c.action)).all() if a.startswith("reglage.")]
    assert actions == ["reglage.adopter"]


def test_une_erreur_apres_l_ecriture_annule_le_maillon_la_transaction_est_atomique(deps, monkeypatch):
    import m9_strategic_intelligence.outils_reglages as outil_module

    def panne(*_args, **_kw):
        raise RuntimeError("panne simulée après l'écriture du maillon")

    monkeypatch.setattr(outil_module, "_journaliser", panne)
    with stockage.transaction() as cnx:
        decision = aide.adopter(cnx, deps, CLE, 7)
        assert decision["statut"] == "echec" and "panne" in decision["reponse"]["details"]
        assert magasin.lire_chaine() == [], "le maillon écrit avant la panne est annulé avec l'appel"
    assert aide.chaine() == []


# -- lire ce qui manque ---------------------------------------------------------------------------------------
def _lire(deps, **args):
    with stockage.transaction():
        return _outils(deps)["m9_lire_reglages_manquants"].fonction(**args)


def test_lire_a_la_livraison_dit_dix_manquants_avec_ce_que_ca_bloque_et_la_proposition(deps):
    page = _lire(deps)
    # 10 réglages vides (M2, M8) + 2 de M6 (C3) dont la valeur d'un agent est déjà écrite à department.yaml.
    assert page["accepte"] is True and page["total"] == 12 and page["manquants"] == 10
    assert page["chaine"]["valide"] is True and "recommandation, non validée" in page["mention"]
    lignes = page["reglages"]
    # la liste ne rend que ce qui MANQUE : les deux seuils de M6 ont déjà une valeur, ils ne s'y trouvent pas.
    assert len(lignes) == 10 and page["prochain_depart"] is None
    relances = next(r for r in lignes if r["cle"] == CLE)
    assert relances["statut"] == "vide" and relances["valeur"] is None
    assert relances["proposition"] == {"valeur": "7", "etiquette": "recommandation, non validée",
                                       "source": relances["proposition"]["source"]}
    assert "REJ-RELANCES-A-CONFIGURER" in relances["debloque"]
    assert len(json.dumps(page, ensure_ascii=False)) < 6000
    for ligne in lignes:
        assert set(ligne) == {"cle", "departement", "libelle", "statut", "valeur", "unite", "debloque", "proposition",
                              "version"}


def test_lire_filtre_par_departement_pagine_et_refuse_un_depart_invalide(deps):
    assert {r["departement"] for r in _lire(deps, departement="m08-analytics")["reglages"]} == {"m08-analytics"}
    assert _lire(deps, departement="m05-financecore")["reglages"] == []
    premiere = _lire(deps, depart=0)
    assert premiere["depart"] == 0
    with pytest.raises(ValueError, match="REJ-REGLAGE-DEPART"):
        _lire(deps, depart=11)
    with pytest.raises(ValueError, match="REJ-REGLAGE-DEPART"):
        _lire(deps, depart=-1)


def test_lire_apres_adoption_ne_liste_plus_le_reglage_comme_manquant_sauf_si_demande(deps):
    with stockage.transaction() as cnx:
        aide.resultat(aide.adopter(cnx, deps, CLE, 7))
    manquants = _lire(deps)
    assert manquants["manquants"] == 9 and CLE not in {r["cle"] for r in manquants["reglages"]}
    tous = _lire(deps, seulement_manquants=False)
    adopte = next(r for r in tous["reglages"] if r["cle"] == CLE)
    assert (adopte["statut"], adopte["valeur"], adopte["version"]) == ("adopte", "7", 1)


def test_lire_ne_montre_aucune_raison_libre_et_hors_transaction_refuse(deps):
    with stockage.transaction() as cnx:
        aide.resultat(aide.adopter(cnx, deps, CLE, 7, raison="Raison libre de la direction 9999"))
    assert "9999" not in json.dumps(_lire(deps, seulement_manquants=False), ensure_ascii=False)
    with pytest.raises(ValueError, match="REJ-REGLAGE-TRANSACTION"):
        _outils(deps)["m9_lire_reglages_manquants"].fonction()
