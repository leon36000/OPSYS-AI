"""Appel routé : replis, plafonds, budget, coûts, usage, escalade et test de connexion borné (faux serveur local)."""

from __future__ import annotations

import http.server
import json
import threading

import pytest
from modeles_aide import (  # noqa: F401 — fixtures importées
    ALIAS,
    AMONT,
    CLE_AMONT,
    PROPRIETAIRE,
    affecter,
    cle_coffre,
    faux,
    faux_local,
    fournisseur_local,
    pret,
)
from faux_litellm import CLE_FICTIVE, FauxLiteLLM
from sqlalchemy import text

from opsys.fournisseurs import registre
from opsys.roles_modeles import acces, appel, client, codes, service
from opsys.roles_modeles.appel import Escalade
from opsys.roles_modeles.codes import ModelesErreur

FICTIF = True
MESSAGES = [{"role": "user", "content": "Bonjour, classe ce message fictif."}]


def _refus(code, fonction, *args, **kwargs):
    with pytest.raises(ModelesErreur) as exc:
        fonction(*args, **kwargs)
    assert exc.value.code == code, exc.value
    return exc.value


def _usage(session, role, jour=None):
    with session() as cnx:
        return service.usage(cnx, role, jour)


def _regler(session, operation, **parametres):
    with session() as cnx:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=operation, parametres=parametres, niveau_confirme="N3")


@pytest.fixture
def avec_repli(pret, faux_local):
    """llm_rapide sur la passerelle (faux) avec un repli LOCAL (second faux serveur)."""
    local = fournisseur_local(pret, "llm.local.fictif", faux_local.url + "/v1")
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"],
             replis=[{"fournisseur": local, "modele": "qwen-local-fictif"}])
    return pret


# -- replis -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("code_http", [500, 502, 503, 429])
def test_panne_retentable_bascule_sur_le_repli(avec_repli, faux, faux_local, code_http):
    faux.pannes["opsys-haiku-5-5"] = code_http
    r = appel.completer(avec_repli, classe="classification", messages=MESSAGES, max_tokens=8)
    assert r["repli_utilise"] is True and r["modele"] == "qwen-local-fictif"
    assert [(t["statut"], t["code"]) for t in r["tentatives"][:1]] == [("echec", "REJ-MODELES-APPEL-ECHEC")]
    assert len(faux.appels_modele("opsys-haiku-5-5")) == 1 and len(faux_local.appels_modele("qwen-local-fictif")) == 1
    u = _usage(avec_repli, "llm_rapide")
    assert u["appels"] == 0 and u["appels_repli"] == 1  # l'appel de repli n'est pas compté au plafond du principal


@pytest.mark.parametrize("code_http", [400, 404, 422, 401, 403])
def test_erreur_de_requete_ou_d_authentification_ne_bascule_jamais(avec_repli, faux, faux_local, code_http):
    faux.pannes["opsys-haiku-5-5"] = code_http
    e = _refus(codes.APPEL_REFUSE, appel.completer, avec_repli, classe="classification", messages=MESSAGES,
               max_tokens=8)
    assert faux_local.appels == []  # un autre fournisseur ne corrigerait pas la requête
    assert "aucun repli" in e.detail


def test_hote_injoignable_est_retentable(avec_repli, faux, faux_local):
    with avec_repli() as cnx:  # l'URL de la passerelle pointe vers un port fermé
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_PASSERELLE_CONFIGURER, niveau_confirme="N3",
                          parametres={"mode": "integree", "url_base": "http://127.0.0.1:9", "secret_cle": "passerelle.cle"})
    r = appel.completer(avec_repli, classe="classification", messages=MESSAGES, max_tokens=8)
    assert r["repli_utilise"] is True and r["tentatives"][0]["code"] == "REJ-MODELES-APPEL-ECHEC"
    assert faux.appels == []


def test_sans_repli_une_panne_est_un_echec_type(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    faux.pannes["opsys-haiku-5-5"] = 503
    e = _refus(codes.APPEL_ECHEC, appel.completer, pret, classe="classification", messages=MESSAGES, max_tokens=8)
    assert e.codes == ("REJ-MODELES-APPEL-ECHEC",)
    assert _usage(pret, "llm_rapide")["appels"] == 0  # un appel échoué ne compte pas


def test_repli_ignore_s_il_est_devenu_non_conforme_ou_inactif(avec_repli, faux, faux_local):
    faux.pannes["opsys-haiku-5-5"] = 503
    with avec_repli() as cnx:
        registre.desactiver(cnx, acteur=PROPRIETAIRE, identifiant="llm.local.fictif")
    e = _refus(codes.APPEL_ECHEC, appel.completer, avec_repli, classe="classification", messages=MESSAGES, max_tokens=8)
    assert "FOURNISSEUR_INACTIF" in e.codes and faux_local.appels == []


def test_fournisseur_principal_non_conforme_n_est_pas_appele(avec_repli, faux, faux_local):
    with avec_repli() as cnx:  # le client passe en hébergement pour tiers : la passerelle (incertain) est refusée
        courant = registre.profil_brut(cnx)
        registre.declarer_profil(cnx, acteur=PROPRIETAIRE, usage_commercial=True, revenu_annuel_usd=1,
                                 territoires=["CA"], heberge_pour_tiers=True, revision_attendue=courant["revision"])
    r = appel.completer(avec_repli, classe="classification", messages=MESSAGES, max_tokens=8)
    assert faux.appels_modele("opsys-haiku-5-5") == []  # jamais appelé
    # le repli local est sous licence permissive : il reste utilisable
    assert r["repli_utilise"] is True
    assert r["tentatives"][0]["statut"] == "ignoree" and r["tentatives"][0]["code"].startswith("REFUS_POLITIQUE")


def test_aucun_fournisseur_utilisable(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    with pret() as cnx:
        registre.desactiver(cnx, acteur=PROPRIETAIRE, identifiant="llm.passerelle.opsys-haiku-5-5")
    _refus(codes.FOURNISSEUR_REFUSE, appel.completer, pret, classe="classification", messages=MESSAGES, max_tokens=8)
    assert faux.appels == []


# -- plafonds et budget -----------------------------------------------------------------------------------------------
def test_plafond_de_jetons_sans_repli_est_un_refus_type_et_aucun_appel(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], plafond_jetons_jour=10)
    e = _refus(codes.PLAFOND_ATTEINT, appel.completer, pret, classe="classification", messages=MESSAGES, max_tokens=8)
    assert "PLAFOND_JETONS_JOUR" in e.codes and faux.appels == []


def test_le_plafond_projete_inclut_la_sortie_demandee(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], plafond_jetons_jour=100)
    appel.completer(pret, classe="classification", messages=MESSAGES, max_tokens=8)  # 14 comptés
    _refus(codes.PLAFOND_ATTEINT, appel.completer, pret, classe="classification", messages=MESSAGES, max_tokens=90)
    assert len(faux.appels_modele("opsys-haiku-5-5")) == 1


def test_le_plafond_de_jetons_est_par_role_et_par_jour(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], plafond_jetons_jour=100)
    affecter(pret, "llm_fort", ALIAS["llm_fort"], plafond_jetons_jour=10_000)
    appel.completer(pret, classe="classification", messages=MESSAGES, max_tokens=8)
    appel.completer(pret, classe="redaction", messages=MESSAGES, max_tokens=8)
    assert _usage(pret, "llm_rapide")["jetons_entree"] == 12 and _usage(pret, "llm_fort")["jetons_entree"] == 12
    assert _usage(pret, "llm_rapide", "2000-01-01")["appels"] == 0  # un autre jour : compteur à part


def test_budget_du_mois_refuse_quand_depasse(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], cout_entree_par_million="1", cout_sortie_par_million="5",
             budget_usd_mois="0.0001")  # 100 micro-USD
    appel.completer(pret, classe="classification", messages=MESSAGES, max_tokens=8)  # 12 + 10 = 22 µUSD
    assert _usage(pret, "llm_rapide")["cout_micro_usd"] == 22
    _refus(codes.PLAFOND_ATTEINT, appel.completer, pret, classe="classification", messages=MESSAGES, max_tokens=64)
    # 22 + (entrée estimée + 64 × 5) dépasse 100 : aucun nouvel appel
    assert len(faux.appels_modele("opsys-haiku-5-5")) == 1


def test_budget_sans_cout_connu_est_non_verifiable_donc_refuse(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], budget_usd_mois="5")  # aucun coût déclaré
    e = _refus(codes.PLAFOND_ATTEINT, appel.completer, pret, classe="classification", messages=MESSAGES, max_tokens=8)
    assert "BUDGET_NON_VERIFIABLE_COUT_INCONNU" in e.codes and faux.appels == []


def test_budget_et_repli(avec_repli, faux, faux_local):
    _regler(avec_repli, service.OP_ROLE_PLAFONDS, role="llm_rapide", budget_usd_mois="5")
    r = appel.completer(avec_repli, classe="classification", messages=MESSAGES, max_tokens=8)
    assert r["repli_utilise"] is True and r["tentatives"][0]["code"] == "BUDGET_NON_VERIFIABLE_COUT_INCONNU"


def test_usage_estime_quand_l_amont_ne_rapporte_rien(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], plafond_jetons_jour=100_000)
    faux_ouvrir = client._ouvrir_reel

    def sans_usage(requete, delai):
        statut, corps = faux_ouvrir(requete, delai)
        donnees = json.loads(corps)
        donnees.pop("usage", None)
        return statut, json.dumps(donnees).encode()

    r = appel.completer(pret, classe="classification", messages=MESSAGES, max_tokens=40, ouvrir=sans_usage)
    assert r["usage"]["estime"] is True and r["usage"]["sortie"] == 40  # borne haute : jamais sous-compter
    assert _usage(pret, "llm_rapide")["jetons_sortie"] == 40


def test_validation_des_parametres_d_appel(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    for max_tokens in (0, -1, 9000, 1.5, True, "8"):
        _refus(codes.DECLARATION_INVALIDE, appel.completer, pret, classe="classification", messages=MESSAGES,
               max_tokens=max_tokens)
    for messages in ([], "texte", None, [MESSAGES[0]] * 65):
        _refus(codes.DECLARATION_INVALIDE, appel.completer, pret, classe="classification", messages=messages)
    assert faux.appels == []


# -- escalade ---------------------------------------------------------------------------------------------------------
def _activer_raisonnement(session):
    affecter(session, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    with session() as cnx:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_RAISONNEMENT_ACTIVER, niveau_confirme="N3",
                          parametres={}, motif="Analyse contractuelle complexe du dossier fictif")


def test_escalade_inactive_ou_sans_demande_valide_ne_touche_pas_le_reseau(pret, faux):
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    demande = Escalade(PROPRIETAIRE, "Analyse contractuelle complexe du dossier fictif")
    _refus(codes.RAISONNEMENT_INACTIF, appel.completer, pret, classe="escalade_raisonnement", messages=MESSAGES,
           escalade=demande)
    with pret() as cnx:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_RAISONNEMENT_ACTIVER, niveau_confirme="N3",
                          parametres={}, motif="Analyse contractuelle complexe du dossier fictif")
    for escalade in (None, "moi", Escalade("vendeur_fictif", demande.motif), Escalade("inconnu", demande.motif),
                     Escalade(PROPRIETAIRE, ""), Escalade(PROPRIETAIRE, "x" * 400), Escalade(PROPRIETAIRE, 5)):
        _refus(codes.ESCALADE_REFUSEE, appel.completer, pret, classe="escalade_raisonnement", messages=MESSAGES,
               escalade=escalade)
    assert faux.appels == []


def test_escalade_valide_appelle_le_raisonnement_et_se_journalise(pret, faux):
    _activer_raisonnement(pret)
    demande = Escalade(PROPRIETAIRE, "Analyse contractuelle complexe du dossier fictif")
    r = appel.completer(pret, classe="escalade_raisonnement", messages=MESSAGES, max_tokens=8, escalade=demande)
    assert r["role"] == "llm_raisonnement" and r["modele"] == "opsys-opus-5-5"
    with pret() as cnx:
        lignes = cnx.execute(text("SELECT par, cible FROM journal WHERE action = 'modeles.escalade.appel'")).all()
    assert lignes == [(PROPRIETAIRE, "role:llm_raisonnement")]


def test_une_escalade_fournie_a_une_classe_ordinaire_ne_change_rien(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    _activer_raisonnement(pret)
    demande = Escalade(PROPRIETAIRE, "Analyse contractuelle complexe du dossier fictif")
    r = appel.completer(pret, classe="classification", messages=MESSAGES, max_tokens=8, escalade=demande)
    assert r["role"] == "llm_rapide" and faux.appels_modele("opsys-opus-5-5") == []


def test_le_raisonnement_ne_bascule_jamais_sur_un_autre_modele(pret, faux):
    _activer_raisonnement(pret)
    affecter(pret, "llm_fort", ALIAS["llm_fort"])
    faux.pannes["opsys-opus-5-5"] = 503
    demande = Escalade(PROPRIETAIRE, "Analyse contractuelle complexe du dossier fictif")
    _refus(codes.APPEL_ECHEC, appel.completer, pret, classe="escalade_raisonnement", messages=MESSAGES, max_tokens=8,
           escalade=demande)
    assert faux.appels_modele("opsys-sonnet-5-5") == []


# -- test de connexion de rôle ----------------------------------------------------------------------------------------
def test_test_de_connexion_est_borne_et_ne_bascule_pas(avec_repli, faux, faux_local):
    faux.pannes["opsys-haiku-5-5"] = 503
    m = appel.tester_role(avec_repli, acteur=PROPRIETAIRE, role="llm_rapide")
    assert m["statut"] == "echec" and faux_local.appels == []  # jamais de repli pour un test
    assert len(faux.appels_modele("opsys-haiku-5-5")) == 1
    del faux.pannes["opsys-haiku-5-5"]
    m = appel.tester_role(avec_repli, acteur=PROPRIETAIRE, role="llm_rapide")
    assert m["statut"] == "succes"
    assert all(a["max_tokens"] is None or a["max_tokens"] <= client.JETONS_TEST_MAX for a in faux.appels)
    assert faux.appels_modele("opsys-haiku-5-5")[-1]["max_tokens"] == 8


def test_test_de_connexion_exige_admin_et_role_configure(pret, faux):
    _refus(codes.ROLE_NON_CONFIGURE, appel.tester_role, pret, acteur=PROPRIETAIRE, role="llm_rapide")
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    _refus(codes.ADMIN_REQUIS, appel.tester_role, pret, acteur="vendeur_fictif", role="llm_rapide")
    with pytest.raises(ValueError):
        appel.tester_role(pret, acteur=PROPRIETAIRE, role="llm_inconnu")
    assert faux.appels == []


def test_test_du_raisonnement_exige_l_activation(pret, faux):
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    _refus(codes.RAISONNEMENT_INACTIF, appel.tester_role, pret, acteur=PROPRIETAIRE, role="llm_raisonnement")
    assert faux.appels == []
    with pret() as cnx:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_RAISONNEMENT_ACTIVER, niveau_confirme="N3",
                          parametres={}, motif="Analyse contractuelle complexe du dossier fictif")
    _refus(codes.ESCALADE_REFUSEE, appel.tester_role, pret, acteur="agent:m10-memoire", role="llm_raisonnement",
           verifier_admin=False, interdire_raisonnement=True)
    assert appel.tester_role(pret, acteur=PROPRIETAIRE, role="llm_raisonnement")["statut"] == "succes"


def test_test_de_connexion_refuse_une_fournisseur_non_conforme_sans_appel(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    with pret() as cnx:
        courant = registre.profil_brut(cnx)
        registre.declarer_profil(cnx, acteur=PROPRIETAIRE, usage_commercial=True, revenu_annuel_usd=1,
                                 territoires=["CA"], heberge_pour_tiers=True, revision_attendue=courant["revision"])
    m = appel.tester_role(pret, acteur=PROPRIETAIRE, role="llm_rapide")
    assert m["statut"] == "refuse_politique" and faux.appels == []


def test_test_de_connexion_delai_minimal_pour_les_agents(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    appel.tester_role(pret, acteur="agent:m10-memoire", role="llm_rapide", verifier_admin=False, delai_min_s=60)
    _refus(codes.APPEL_REFUSE, appel.tester_role, pret, acteur="agent:m10-memoire", role="llm_rapide",
           verifier_admin=False, delai_min_s=60)
    assert len(faux.appels_modele("opsys-haiku-5-5")) == 1


def test_roles_sans_appel_generique_verifient_la_presence_de_l_alias(pret, faux):
    with pret() as cnx:
        registre.configurer(cnx, acteur=PROPRIETAIRE, identifiant="ocr.tesseract-5.5.local", modifications={})
        registre.activer(cnx, acteur=PROPRIETAIRE, identifiant="ocr.tesseract-5.5.local")
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_AFFECTER, niveau_confirme="N3",
                          parametres={"role": "ocr", "fournisseur_id": "ocr.tesseract-5.5.local",
                                      "modele_appel": "tesseract-5.5"})
    m = appel.tester_role(pret, acteur=PROPRIETAIRE, role="ocr")
    assert m["statut"] == "non_verifiable" and faux.appels == []  # moteur local : pas d'appel réseau


def test_reranker_via_la_passerelle(pret, faux):
    from modeles_aide import fournisseur_passerelle

    ident = fournisseur_passerelle(pret, "reranker", ALIAS["reranker"])
    with pret() as cnx:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_AFFECTER, niveau_confirme="N3",
                          parametres={"role": "reranker", "fournisseur_id": ident, "modele_appel": ALIAS["reranker"]})
    assert appel.tester_role(pret, acteur=PROPRIETAIRE, role="reranker")["statut"] == "succes"
    r = appel.reclasser(pret, requete="q", passages=["a", "b", "c"])
    assert r["notes"] == [1.0, 0.5, pytest.approx(1 / 3)]
    _refus(codes.DECLARATION_INVALIDE, appel.reclasser, pret, requete="q", passages=[])


# -- secrets : jamais fuités ------------------------------------------------------------------------------------------
def test_un_mauvais_secret_est_un_refus_sans_fuite(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    faux.cle = "autre-cle-fictive-differente-0123456789"
    e = _refus(codes.APPEL_REFUSE, appel.completer, pret, classe="classification", messages=MESSAGES, max_tokens=8)
    assert CLE_FICTIVE not in str(e) and CLE_AMONT not in str(e) and "Bearer" not in str(e)
    m = appel.tester_role(pret, acteur=PROPRIETAIRE, role="llm_rapide")
    assert m["statut"] == "echec" and CLE_FICTIVE not in json.dumps(m)


def test_secret_revoque_ou_absent_refus_sans_appel(pret, faux):
    from opsys.secrets_coffre import coffre

    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    with pret() as cnx:
        coffre.revoquer(cnx, acteur=PROPRIETAIRE, nom="passerelle.cle")
    _refus(codes.FOURNISSEUR_REFUSE, appel.completer, pret, classe="classification", messages=MESSAGES, max_tokens=8)
    assert faux.appels == []
    m = appel.tester_role(pret, acteur=PROPRIETAIRE, role="llm_rapide")
    assert m["statut"] == "echec" and "SECRET-INDISPONIBLE" in m["detail"]


def test_la_cle_n_apparait_dans_aucune_table_ni_journal_apres_un_parcours(pret, faux):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"])
    appel.tester_role(pret, acteur=PROPRIETAIRE, role="llm_rapide")
    appel.completer(pret, classe="classification", messages=MESSAGES, max_tokens=8)
    with pret() as cnx:
        for table in ("journal", "modeles_historique", "modeles_reglages", "modeles_roles", "modeles_usage",
                      "coffre_acces", "fournisseurs_configurations"):
            contenu = json.dumps([list(map(str, ligne)) for ligne in cnx.execute(text(f"SELECT * FROM {table}"))])
            assert CLE_FICTIVE not in contenu and CLE_AMONT not in contenu, table
