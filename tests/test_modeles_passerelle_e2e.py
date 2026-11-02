"""Parcours de bout en bout avec un FAUX serveur compatible OpenAI/LiteLLM (boucle locale, aucune clé réelle).

Installation neuve → rôles vides (inertes, fail-closed) → saisie de la clé en coffre → génération de la configuration →
test de connexion → catalogue découvert → affectation des rôles (rapide, fort, embeddings, ocr, vl) → appel routé par la
politique d'économie (une classification va au rapide, jamais au raisonnement) → plafond atteint → repli → activation
du raisonnement refusée sans approbation → retour arrière. Les serveurs enregistrent chaque requête : on prouve QUEL
modèle a été appelé, avec quelle borne, et que rien n'a été appelé quand il ne le fallait pas.
"""

from __future__ import annotations

import json

import pytest
import yaml
from modeles_aide import (  # noqa: F401 — fixtures importées
    ALIAS,
    AMONT,
    CLE_AMONT,
    PROPRIETAIRE,
    affecter,
    cle_coffre,
    connecter_passerelle,
    declarer_profil,
    definir_secrets,
    faux,
    faux_local,
    fournisseur_local,
    preparer_identites,
)
from faux_litellm import CLE_FICTIVE
from sqlalchemy import text

from opsys.fournisseurs import registre
from opsys.roles_modeles import acces, appel, codes, decouverte, generation, service
from opsys.roles_modeles.appel import Escalade
from opsys.roles_modeles.codes import ModelesErreur

FICTIF = True
MESSAGES = [{"role": "user", "content": "Classe ce courriel fictif : demande de soumission."}]


def _vue(session, role):
    with session() as cnx:
        return service.vue_role(cnx, role)


def _erreur(code, fonction, *args, **kwargs):
    with pytest.raises(ModelesErreur) as exc:
        fonction(*args, **kwargs)
    assert exc.value.code == code, exc.value
    return exc.value


def test_parcours_complet_installation_neuve_jusqu_au_retour_arriere(session, cle_coffre, faux, faux_local):
    preparer_identites(session)

    # 1. Installation neuve : rôles vides, inertes ; un appel est refusé SANS toucher le réseau.
    with session() as cnx:
        vue = service.vue_complete(cnx)
    assert all(r["etat"] == "inerte" for r in vue["roles"]) and vue["passerelle"] == {"configuree": False}
    _erreur(codes.ROLE_NON_CONFIGURE, appel.completer, session, classe="classification", messages=MESSAGES)
    assert faux.appels == []

    # 2. Saisie de la clé en coffre (jamais ailleurs), profil de licence, connexion de la passerelle (N3 confirmé).
    declarer_profil(session)
    definir_secrets(session, CLE_FICTIVE)
    with session() as cnx, pytest.raises(ModelesErreur) as exc:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_PASSERELLE_CONFIGURER, parametres={
            "mode": "integree", "url_base": faux.url, "secret_cle": "passerelle.cle"})
    assert exc.value.code == codes.CONFIRMATION_REQUISE
    connecter_passerelle(session, faux.url)
    assert faux.appels == []  # connecter ne contacte pas la passerelle

    # 3. Test de connexion + catalogue découvert (coûts déclarés lus du catalogue, jamais d'`litellm_params`).
    r = decouverte.decouvrir(session, acteur=PROPRIETAIRE)
    assert r["statut"] == "succes" and r["modeles"] == 6 and r["cout_disponible"] is True
    par_nom = {e["nom"]: e for e in r["entrees"]}
    assert par_nom["opsys-haiku-5-5"]["mode"] == "chat"
    assert par_nom["opsys-haiku-5-5"]["cout_entree_par_million"] == "1"
    assert par_nom["opsys-haiku-5-5"]["cout_sortie_par_million"] == "5"
    assert par_nom["opsys-embed-e5-multilingue"]["cout_entree_par_million"] is None  # 0 = non déclaré
    assert par_nom["opsys-vl-qwen3-30b"]["vision"] is True
    assert "sk-secret-amont" not in json.dumps(r) and "interne.fictif" not in json.dumps(r)
    assert all(a["autorise"] for a in faux.appels)
    assert {a["chemin"] for a in faux.appels} == {"/v1/models", "/model/info"}

    # 4. Affectation des rôles.
    affecter(session, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"],
             cout_entree_par_million="1", cout_sortie_par_million="5", cout_source="catalogue de la passerelle")
    affecter(session, "llm_fort", ALIAS["llm_fort"], amont=AMONT["llm_fort"])
    affecter(session, "embeddings", ALIAS["embeddings"], amont=AMONT["embeddings"])
    affecter(session, "vl", ALIAS["vl"])
    with session() as cnx:  # OCR : moteur local du catalogue (worker Tesseract isolé existant)
        registre.configurer(cnx, acteur=PROPRIETAIRE, identifiant="ocr.tesseract-5.5.local", modifications={})
        assert registre.activer(cnx, acteur=PROPRIETAIRE, identifiant="ocr.tesseract-5.5.local").conforme
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_AFFECTER, parametres={
            "role": "ocr", "fournisseur_id": "ocr.tesseract-5.5.local", "modele_appel": "tesseract-5.5"},
                          niveau_confirme="N3")
    assert _vue(session, "ocr")["fournisseur"]["mode"] == "local"
    assert _vue(session, "llm_raisonnement")["etat"] == "inerte"
    assert _vue(session, "stt")["etat"] == "inerte"

    # 5. Test de connexion de rôle : UN appel minuscule, borné ; l'embedding mesure sa dimension.
    avant = len(faux.appels)
    m = appel.tester_role(session, acteur=PROPRIETAIRE, role="llm_rapide")
    assert m["statut"] == "succes" and m["latence_ms"] is not None
    haiku = faux.appels_modele("opsys-haiku-5-5")
    assert len(haiku) == 1 and haiku[0]["max_tokens"] <= 8 and haiku[0]["autorise"]
    me = appel.tester_role(session, acteur=PROPRIETAIRE, role="embeddings")
    assert me["statut"] == "succes" and me["dimension"] == 8
    assert len(faux.appels_modele("opsys-embed-e5-multilingue")) == 1
    assert len(faux.appels) == avant + 2
    assert _vue(session, "embeddings")["mesure"]["dernier_test"]["dimension"] == 8
    assert _vue(session, "llm_rapide")["mesure"]["libelle"] == "non mesuré"  # connexion testée ≠ qualité mesurée
    assert _vue(session, "llm_rapide")["mesure"]["connexion_testee"] is True
    mv = appel.tester_role(session, acteur=PROPRIETAIRE, role="vl")
    assert mv["statut"] == "succes"
    image = faux.appels_modele("opsys-vl-qwen3-30b")[0]["corps"]["messages"][0]["content"]
    assert any(p.get("type") == "image_url" for p in image)

    # 6. Appel routé par la politique d'économie : classification → rapide, rédaction → fort, jamais le raisonnement.
    r1 = appel.completer(session, classe="classification", messages=MESSAGES, max_tokens=16)
    assert (r1["role"], r1["modele"], r1["repli_utilise"]) == ("llm_rapide", "opsys-haiku-5-5", False)
    assert r1["contenu"] == "OK" and r1["usage"] == {"entree": 12, "sortie": 2, "estime": False, "cout_micro_usd": 22}
    r2 = appel.completer(session, classe="redaction", messages=MESSAGES, max_tokens=64)
    assert (r2["role"], r2["modele"]) == ("llm_fort", "opsys-sonnet-5-5")
    assert faux.appels_modele("opsys-opus-5-5") == []
    _erreur(codes.CLASSE_INCONNUE, appel.completer, session, classe="tout_sauf_economique", messages=MESSAGES)
    _erreur(codes.CLASSE_INCONNUE, appel.completer, session, classe="plongement", messages=MESSAGES)  # mauvaise voie
    e = appel.plonger(session, textes=["a", "b"])
    assert len(e["vecteurs"]) == 2 and e["role"] == "embeddings"

    # 7. Plafond atteint → repli sur le modèle LOCAL (second faux serveur) ; le repli n'est pas plafonné.
    local = fournisseur_local(session, "llm.local.fictif", faux_local.url + "/v1")
    with session() as cnx:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_REPLIS, niveau_confirme="N3", parametres={
            "role": "llm_rapide", "replis": [{"fournisseur": local, "modele": "qwen-local-fictif"}]})
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_PLAFONDS, parametres={
            "role": "llm_rapide", "plafond_jetons_jour": 120})
    appels_haiku = len(faux.appels_modele("opsys-haiku-5-5"))
    r3 = appel.completer(session, classe="extraction", messages=MESSAGES, max_tokens=16)
    assert r3["repli_utilise"] is False  # la marge de 120 jetons le permet encore
    for _ in range(10):  # boucle BORNÉE : le plafond (projeté avant l'appel) finit par faire basculer vers le repli
        r4 = appel.completer(session, classe="extraction", messages=MESSAGES, max_tokens=16)
        if r4["repli_utilise"]:
            break
    else:
        pytest.fail("le plafond n'a jamais fait basculer vers le repli")
    n_haiku = len(faux.appels_modele("opsys-haiku-5-5"))
    assert n_haiku > appels_haiku
    assert r4["fournisseur"] == local and r4["modele"] == "qwen-local-fictif"
    r4b = appel.completer(session, classe="extraction", messages=MESSAGES, max_tokens=16)
    assert r4b["repli_utilise"] is True
    assert len(faux.appels_modele("opsys-haiku-5-5")) == n_haiku  # plus un seul appel payant
    assert [t["statut"] for t in r4["tentatives"]] == ["ignoree", "succes"]
    assert r4["tentatives"][0]["code"] == "PLAFOND_JETONS_JOUR"
    assert len(faux_local.appels_modele("qwen-local-fictif")) == 2
    assert _vue(session, "llm_rapide")["usage_jour"]["appels_repli"] == 2

    # 8. Raisonnement : refusé sans approbation, à chaque étape.
    affecter(session, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    demande = Escalade(PROPRIETAIRE, "Analyse contractuelle complexe du dossier fictif")
    _erreur(codes.RAISONNEMENT_INACTIF, appel.completer, session, classe="escalade_raisonnement", messages=MESSAGES,
            escalade=demande)
    with session() as cnx:
        _erreur(codes.CONFIRMATION_REQUISE, service.appliquer, cnx, acteur=PROPRIETAIRE,
                operation=service.OP_RAISONNEMENT_ACTIVER, parametres={}, motif="Analyse contractuelle complexe")
    assert faux.appels_modele("opsys-opus-5-5") == []
    with session() as cnx:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_RAISONNEMENT_ACTIVER, parametres={},
                          niveau_confirme="N3", motif="Analyse contractuelle complexe du dossier fictif")
    _erreur(codes.ESCALADE_REFUSEE, appel.completer, session, classe="escalade_raisonnement", messages=MESSAGES)
    _erreur(codes.ESCALADE_REFUSEE, appel.completer, session, classe="escalade_raisonnement", messages=MESSAGES,
            escalade=Escalade("vendeur_fictif", "Analyse contractuelle complexe du dossier fictif"))
    _erreur(codes.ESCALADE_REFUSEE, appel.completer, session, classe="escalade_raisonnement", messages=MESSAGES,
            escalade=Escalade(PROPRIETAIRE, "court"))
    assert faux.appels_modele("opsys-opus-5-5") == []
    for classe in ("classification", "analyse", "outil_complexe", "redaction"):  # actif ≠ par défaut
        assert appel.completer(session, classe=classe, messages=MESSAGES, max_tokens=8)["role"] != "llm_raisonnement"
    assert faux.appels_modele("opsys-opus-5-5") == []
    r5 = appel.completer(session, classe="escalade_raisonnement", messages=MESSAGES, max_tokens=8, escalade=demande)
    assert r5["modele"] == "opsys-opus-5-5" and r5["approbation_requise"] is True and r5["repli_utilise"] is False
    assert len(faux.appels_modele("opsys-opus-5-5")) == 1
    with session() as cnx:
        journal = cnx.execute(text("SELECT action, details FROM journal WHERE action = 'modeles.escalade.appel'")).all()
    assert len(journal) == 1 and "Analyse contractuelle" in journal[0][1]

    # 9. Retour arrière : le raisonnement redevient inactif ; le rôle fort retrouve son état antérieur.
    with session() as cnx:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_REVENIR, niveau_confirme="N3",
                          parametres={"cible": "raisonnement"})
    _erreur(codes.RAISONNEMENT_INACTIF, appel.completer, session, classe="escalade_raisonnement", messages=MESSAGES,
            escalade=demande)
    ident = _vue(session, "llm_fort")["fournisseur"]["identifiant"]
    with session() as cnx:
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_AFFECTER, niveau_confirme="N3",
                          parametres={"role": "llm_fort", "fournisseur_id": ident, "modele_appel": "autre-modele"})
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_REVENIR, niveau_confirme="N3",
                          parametres={"cible": "role:llm_fort"})
    assert _vue(session, "llm_fort")["modele_appel"] == ALIAS["llm_fort"]

    # 10. Configuration générée : rôles servis par la passerelle, jamais une clé, raisonnement absent (inactif).
    with session() as cnx:
        config = generation.config_depuis_roles(cnx, {})
    noms = {m["model_name"] for m in config["model_list"]}
    assert {"opsys-haiku-5-5", "opsys-sonnet-5-5", "opsys-rapide", "opsys-standard", "opsys-fort",
            "opsys-haiku-5-5-repli1", "opsys-embed-e5-multilingue"} <= noms
    assert "opsys-opus-5-5" not in noms
    texte = yaml.safe_dump(config)
    assert CLE_AMONT not in texte and CLE_FICTIVE not in texte and "os.environ/OPENROUTER_API_KEY" in texte
