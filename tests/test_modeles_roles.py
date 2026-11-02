"""Rôles de modèles : politique d'économie, niveaux d'approbation, validations, historique et retour arrière.

Données fictives, aucun réseau réel (les affectations n'appellent aucun serveur). Les parcours avec faux serveur
compatible OpenAI sont dans `test_modeles_passerelle_e2e.py`.
"""

from __future__ import annotations

import pytest
from modeles_aide import (
    ALIAS,
    AMONT,
    PROPRIETAIRE,
    affecter,
    fournisseur_passerelle,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from opsys.fournisseurs import registre
from opsys.roles_modeles import codes, economie, service
from opsys.roles_modeles import roles as lex
from opsys.roles_modeles.codes import ModelesErreur

FICTIF = True


def _appliquer(session, operation, parametres, niveau="N3", acteur=PROPRIETAIRE, **extra):
    with session() as cnx:
        return service.appliquer(
            cnx, acteur=acteur, operation=operation, parametres=parametres, niveau_confirme=niveau, **extra
        )


def _refus(session, code, operation, parametres, niveau="N3", acteur=PROPRIETAIRE, **extra):
    with pytest.raises(ModelesErreur) as exc:
        _appliquer(session, operation, parametres, niveau, acteur, **extra)
    assert exc.value.code == code, exc.value
    return exc.value


def _vue(session, role):
    with session() as cnx:
        return service.vue_role(cnx, role)


# -- politique d'économie : données, jamais d'aiguillage par défaut ---------------------------------------------------
def test_politique_economie_classification_va_au_rapide_redaction_au_fort():
    assert economie.role_pour("classification") == "llm_rapide"
    assert economie.role_pour("extraction") == "llm_rapide"
    assert economie.role_pour("resume_court") == "llm_rapide"
    assert economie.role_pour("redaction") == "llm_fort"
    assert economie.role_pour("analyse") == "llm_fort"
    assert economie.role_pour("outil_complexe") == "llm_fort"
    assert economie.role_pour("vision_document") == "vl"
    assert economie.role_pour("plongement") == "embeddings"


def test_aucune_classe_ordinaire_ne_mene_au_raisonnement():
    menent = [nom for nom, ligne in economie.CLASSES.items() if ligne["role"] == lex.ROLE_RAISONNEMENT]
    assert menent == [economie.CLASSE_ESCALADE]
    assert economie.CLASSES[economie.CLASSE_ESCALADE]["approbation"] is True
    economie.verifier_politique()


def test_invariants_de_la_politique_refusent_une_derive():
    derive = {**economie.CLASSES, "classification": {**economie.CLASSES["classification"], "role": "llm_raisonnement"}}
    with pytest.raises(ValueError, match="seul"):
        economie.verifier_politique(derive)
    sans_approbation = {
        **economie.CLASSES,
        economie.CLASSE_ESCALADE: {**economie.CLASSES[economie.CLASSE_ESCALADE], "approbation": False},
    }
    with pytest.raises(ValueError):
        economie.verifier_politique(sans_approbation)
    with pytest.raises(ValueError, match="rôle inconnu"):
        economie.verifier_politique({"x": {"role": "inconnu", "approbation": False}})


def test_classe_inconnue_refusee_sans_aiguillage_par_defaut():
    for classe in ("inconnue", "", None, 3, "ESCALADE_RAISONNEMENT"):
        with pytest.raises(economie.ClasseInconnue):
            economie.role_pour(classe)


def test_toute_valeur_proposee_est_etiquetee_recommandation_non_validee():
    vue = economie.vue()
    assert vue["statut"] == "recommandation_non_validee"
    assert all(c["statut"] == "recommandation_non_validee" for c in vue["classes"].values())
    assert all(r["statut"] == "recommandation_non_validee" for r in lex.RECOMMANDATIONS.values())
    assert "haiku" in lex.RECOMMANDATIONS["llm_rapide"]["modele_amont"]
    assert "sonnet" in lex.RECOMMANDATIONS["llm_fort"]["modele_amont"]
    assert "opus" in lex.RECOMMANDATIONS["llm_raisonnement"]["modele_amont"]


def test_un_palier_ne_mene_jamais_au_raisonnement():
    assert set(lex.PALIER_VERS_ROLE.values()) == {"llm_rapide", "llm_fort"}
    assert lex.ROLE_RAISONNEMENT not in lex.PALIER_VERS_ROLE.values()


# -- installation neuve : tout est inerte ----------------------------------------------------------------------------
def test_installation_neuve_roles_inertes_et_passerelle_absente(session):
    with session() as cnx:
        vue = service.vue_complete(cnx)
    assert [r["role"] for r in vue["roles"]] == list(lex.ROLES)
    assert all(r["etat"] == "inerte" and not r["configure"] for r in vue["roles"])
    assert vue["passerelle"] == {"configuree": False}
    assert vue["raisonnement"]["actif"] is False
    assert vue["profil_licence_declare"] is False


# -- niveaux d'approbation --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "operation",
    [
        service.OP_PASSERELLE_CONFIGURER,
        service.OP_PASSERELLE_RETIRER,
        service.OP_ROLE_AFFECTER,
        service.OP_ROLE_RETIRER,
        service.OP_ROLE_REPLIS,
        service.OP_RAISONNEMENT_ACTIVER,
        service.OP_REVENIR,
    ],
)
@pytest.mark.parametrize("niveau", [None, "N0", "N2"])
def test_les_gestes_n3_exigent_une_confirmation_n3(pret, operation, niveau):
    assert service.NIVEAU_REQUIS[operation] == "N3"
    _refus(pret, codes.CONFIRMATION_REQUISE, operation, {"role": "llm_fort", "motif": "x" * 12}, niveau=niveau)


def test_niveaux_requis_sont_ceux_de_la_consigne():
    assert service.NIVEAU_REQUIS[service.OP_ROLE_AFFECTER] == "N3"  # changer de fournisseur d'un rôle
    assert service.NIVEAU_REQUIS[service.OP_RAISONNEMENT_ACTIVER] == "N3"
    assert service.NIVEAU_REQUIS[service.OP_ROLE_PLAFONDS] == "N2"
    assert service.NIVEAU_REQUIS[service.OP_RAISONNEMENT_DESACTIVER] == "N2"


def test_un_niveau_superieur_confirme_aussi(pret):
    identifiant = fournisseur_passerelle(pret, "llm_fort", ALIAS["llm_fort"])
    r = _appliquer(
        pret,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_fort", "fournisseur_id": identifiant, "modele_appel": ALIAS["llm_fort"]},
        niveau="N4",
    )
    assert r["configure"] is True


def test_seul_un_admin_actif_ecrit(pret):
    identifiant = fournisseur_passerelle(pret, "llm_fort", ALIAS["llm_fort"])
    parametres = {"role": "llm_fort", "fournisseur_id": identifiant, "modele_appel": ALIAS["llm_fort"]}
    for acteur in ("vendeur_fictif", "inconnu_fictif", "", None):
        _refus(pret, codes.ADMIN_REQUIS, service.OP_ROLE_AFFECTER, parametres, acteur=acteur)
    assert _vue(pret, "llm_fort")["etat"] == "inerte"


# -- validations d'affectation ----------------------------------------------------------------------------------------
def test_affectation_valide_rend_la_vue_complete(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"])
    v = _vue(pret, "llm_rapide")
    assert v["etat"] == "actif" and v["modele_appel"] == "opsys-haiku-5-5"
    assert v["fournisseur"]["identifiant"] == "llm.passerelle.opsys-haiku-5-5"
    assert v["fournisseur"]["conforme"] is True and v["fournisseur"]["mode"] == "api"
    assert v["fournisseur"]["licence"]["usage_commercial"] == "sur_contrat"
    assert v["mesure"]["libelle"] == "non mesuré" and v["mesure"]["connexion_testee"] is False
    assert v["cout"]["entree_par_million"] is None  # jamais un coût inventé
    assert v["plafonds"] == {"jetons_jour": None, "budget_usd_mois": None}
    assert v["classes"] == ["classification", "extraction", "normalisation", "resume_court", "routage"]


def test_fournisseur_non_configure_inactif_ou_de_mauvaise_capacite_refuse(pret):
    base = {"role": "llm_fort", "modele_appel": "x-modele"}
    _refus(pret, codes.FOURNISSEUR_INVALIDE, service.OP_ROLE_AFFECTER, {**base, "fournisseur_id": "llm.inconnu.x"})
    _refus(pret, codes.FOURNISSEUR_INVALIDE, service.OP_ROLE_AFFECTER, {**base, "fournisseur_id": None})
    with pret() as cnx:  # configuré mais jamais activé
        registre.configurer(cnx, acteur=PROPRIETAIRE, identifiant="llm.gpt-oss-120b.local", modifications={})
    _refus(
        pret, codes.FOURNISSEUR_INVALIDE, service.OP_ROLE_AFFECTER, {**base, "fournisseur_id": "llm.gpt-oss-120b.local"}
    )
    ident = fournisseur_passerelle(pret, "embeddings", ALIAS["embeddings"])
    e = _refus(pret, codes.FOURNISSEUR_INVALIDE, service.OP_ROLE_AFFECTER, {**base, "fournisseur_id": ident})
    assert "capacité" in e.detail


def test_fournisseur_devenu_non_conforme_refuse_avec_les_codes_de_la_politique(pret):
    ident = fournisseur_passerelle(pret, "llm_fort", ALIAS["llm_fort"])
    with pret() as cnx:  # le client déclare ensuite héberger des tiers : droit de service non établi
        courant = registre.profil_brut(cnx)
        registre.declarer_profil(
            cnx,
            acteur=PROPRIETAIRE,
            usage_commercial=True,
            revenu_annuel_usd=1,
            territoires=["CA"],
            heberge_pour_tiers=True,
            revision_attendue=courant["revision"],
        )
    e = _refus(
        pret,
        codes.FOURNISSEUR_REFUSE,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_fort", "fournisseur_id": ident, "modele_appel": ALIAS["llm_fort"]},
    )
    assert "SERVICE_TIERS_INCERTAIN" in e.codes


@pytest.mark.parametrize("modele", ["", " ", "a b", "x;rm", "é", "a" * 201, None, 5, "../x"])
def test_nom_de_modele_invalide_refuse(pret, modele):
    ident = fournisseur_passerelle(pret, "llm_fort", ALIAS["llm_fort"])
    _refus(
        pret,
        codes.DECLARATION_INVALIDE,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_fort", "fournisseur_id": ident, "modele_appel": modele},
    )


def test_role_inconnu_refuse(pret):
    _refus(pret, codes.ROLE_INCONNU, service.OP_ROLE_AFFECTER, {"role": "llm_geant"})
    _refus(pret, codes.ROLE_INCONNU, service.OP_ROLE_RETIRER, {"role": None})


def test_operation_inconnue_ou_parametres_invalides_refuses(pret):
    _refus(pret, codes.DECLARATION_INVALIDE, "role.detruire", {}, niveau="N5")
    with pret() as cnx, pytest.raises(ModelesErreur) as exc:
        service.appliquer(
            cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_AFFECTER, parametres=["x"], niveau_confirme="N3"
        )
    assert exc.value.code == codes.DECLARATION_INVALIDE


def test_sans_passerelle_un_fournisseur_de_passerelle_est_refuse(session, cle_coffre):
    from modeles_aide import declarer_profil, definir_secrets, preparer_identites

    from opsys.roles_modeles import passerelle_fournisseur

    preparer_identites(session)
    declarer_profil(session)
    definir_secrets(session, "cle-fictive-sans-passerelle-0123456789")
    with session() as cnx:
        d = passerelle_fournisseur.declarer(
            cnx,
            acteur=PROPRIETAIRE,
            role="llm_fort",
            alias="x-alias",
            secret_cle="passerelle.cle",
            efvp_ref="EFVP-1",
            contrat_ref="C-1",
        )
    assert d["active"]
    _refus(
        session,
        codes.PASSERELLE_ABSENTE,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_fort", "fournisseur_id": d["identifiant"], "modele_appel": "x-alias"},
    )


def test_amont_seulement_pour_un_fournisseur_de_passerelle(pret, faux_local):
    from modeles_aide import fournisseur_local

    local = fournisseur_local(pret, "llm.local.fictif", faux_local.url + "/v1")
    _refus(
        pret,
        codes.DECLARATION_INVALIDE,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_fort", "fournisseur_id": local, "modele_appel": "qwen-local-fictif", "amont": AMONT["llm_fort"]},
    )
    ident = fournisseur_passerelle(pret, "llm_fort", ALIAS["llm_fort"])
    for amont in (
        {"fournisseur": "x"},
        {"fournisseur": "OR", "modele": "a"},
        {"fournisseur": "o", "modele": "a b"},
        "x",
    ):
        _refus(
            pret,
            codes.DECLARATION_INVALIDE,
            service.OP_ROLE_AFFECTER,
            {"role": "llm_fort", "fournisseur_id": ident, "modele_appel": ALIAS["llm_fort"], "amont": amont},
        )


# -- replis -----------------------------------------------------------------------------------------------------------
def test_replis_ordonnes_valides_et_rendus(pret, faux_local):
    from modeles_aide import fournisseur_local

    local = fournisseur_local(pret, "llm.local.fictif", faux_local.url + "/v1")
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], replis=[{"fournisseur": local, "modele": "qwen-local-fictif"}])
    v = _vue(pret, "llm_rapide")
    assert [(r["fournisseur"], r["modele"]) for r in v["replis"]] == [(local, "qwen-local-fictif")]
    assert v["replis"][0]["fournisseur_vue"]["mode"] == "local" and v["replis"][0]["fournisseur_vue"]["conforme"]


def test_replis_invalides_refuses(pret, faux_local):
    from modeles_aide import fournisseur_local

    local = fournisseur_local(pret, "llm.local.fictif", faux_local.url + "/v1")
    ident = fournisseur_passerelle(pret, "llm_rapide", ALIAS["llm_rapide"])
    base = {"role": "llm_rapide", "fournisseur_id": ident, "modele_appel": ALIAS["llm_rapide"]}
    un = {"fournisseur": local, "modele": "qwen-local-fictif"}
    for replis in (
        "x",
        [1],
        [{"fournisseur": local}],
        [un, un],
        [{"fournisseur": ident, "modele": ALIAS["llm_rapide"]}],
        [{"fournisseur": local, "modele": f"m{i}"} for i in range(5)],
        [{"fournisseur": "inconnu.x", "modele": "m"}],
    ):
        with pytest.raises(ModelesErreur):
            _appliquer(pret, service.OP_ROLE_AFFECTER, {**base, "replis": replis})
    assert _vue(pret, "llm_rapide")["etat"] == "inerte"


def test_un_repli_inactif_ou_non_conforme_est_refuse(pret, faux_local):
    from modeles_aide import fournisseur_local

    local = fournisseur_local(pret, "llm.local.fictif", faux_local.url + "/v1")
    ident = fournisseur_passerelle(pret, "llm_rapide", ALIAS["llm_rapide"])
    with pret() as cnx:
        registre.desactiver(cnx, acteur=PROPRIETAIRE, identifiant=local)
    _refus(
        pret,
        codes.FOURNISSEUR_INVALIDE,
        service.OP_ROLE_AFFECTER,
        {
            "role": "llm_rapide",
            "fournisseur_id": ident,
            "modele_appel": ALIAS["llm_rapide"],
            "replis": [{"fournisseur": local, "modele": "qwen-local-fictif"}],
        },
    )


def test_embeddings_sans_repli_autre_espace_vectoriel(pret, faux_local):
    from modeles_aide import fournisseur_local

    local = fournisseur_local(pret, "embeddings.local.fictif", faux_local.url + "/v1", capacite="embeddings")
    ident = fournisseur_passerelle(pret, "embeddings", ALIAS["embeddings"])
    e = _refus(
        pret,
        codes.REPLI_INVALIDE,
        service.OP_ROLE_AFFECTER,
        {
            "role": "embeddings",
            "fournisseur_id": ident,
            "modele_appel": ALIAS["embeddings"],
            "replis": [{"fournisseur": local, "modele": "m"}],
        },
    )
    assert "espace" in e.detail


def test_changer_les_replis_d_un_role_existant(pret, faux_local):
    from modeles_aide import fournisseur_local

    local = fournisseur_local(pret, "llm.local.fictif", faux_local.url + "/v1")
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    r = _appliquer(
        pret,
        service.OP_ROLE_REPLIS,
        {"role": "llm_rapide", "replis": [{"fournisseur": local, "modele": "qwen-local-fictif"}]},
    )
    assert r["replis"] == [{"fournisseur": local, "modele": "qwen-local-fictif"}]
    _refus(pret, codes.ROLE_NON_CONFIGURE, service.OP_ROLE_REPLIS, {"role": "llm_fort", "replis": []})


# -- le raisonnement est isolé ----------------------------------------------------------------------------------------
def test_le_raisonnement_n_a_aucun_repli(pret, faux_local):
    from modeles_aide import fournisseur_local

    local = fournisseur_local(pret, "llm.local.fictif", faux_local.url + "/v1")
    ident = fournisseur_passerelle(pret, "llm_raisonnement", ALIAS["llm_raisonnement"])
    _refus(
        pret,
        codes.RAISONNEMENT_ISOLE,
        service.OP_ROLE_AFFECTER,
        {
            "role": "llm_raisonnement",
            "fournisseur_id": ident,
            "modele_appel": ALIAS["llm_raisonnement"],
            "replis": [{"fournisseur": local, "modele": "qwen-local-fictif"}],
        },
    )


def test_la_cible_du_raisonnement_n_est_jamais_celle_d_un_autre_role(pret):
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    ident = fournisseur_passerelle(pret, "llm_fort", ALIAS["llm_raisonnement"])  # même alias, autre rôle
    _refus(
        pret,
        codes.RAISONNEMENT_ISOLE,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_fort", "fournisseur_id": ident, "modele_appel": ALIAS["llm_raisonnement"]},
    )
    # même modèle d'amont sous un autre alias : refusé aussi (aucune voie détournée vers Opus)
    ident2 = fournisseur_passerelle(pret, "llm_fort", "autre-alias-fort")
    _refus(
        pret,
        codes.RAISONNEMENT_ISOLE,
        service.OP_ROLE_AFFECTER,
        {
            "role": "llm_fort",
            "fournisseur_id": ident2,
            "modele_appel": "autre-alias-fort",
            "amont": AMONT["llm_raisonnement"],
        },
    )
    # dans l'autre ordre : un rôle ordinaire déjà sur ce modèle empêche de l'affecter au raisonnement
    affecter(pret, "llm_fort", ALIAS["llm_fort"], amont=AMONT["llm_fort"])
    ident3 = fournisseur_passerelle(pret, "llm_raisonnement", ALIAS["llm_fort"])
    _refus(
        pret,
        codes.RAISONNEMENT_ISOLE,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_raisonnement", "fournisseur_id": ident3, "modele_appel": ALIAS["llm_fort"]},
    )


def test_activation_du_raisonnement_exige_affectation_motif_et_n3(pret):
    _refus(pret, codes.ROLE_NON_CONFIGURE, service.OP_RAISONNEMENT_ACTIVER, {}, motif="Besoin de raisonnement poussé")
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    for motif in (None, "", "court", "x" * 301, "a\nb" * 6):
        _refus(pret, codes.CONFIRMATION_REQUISE, service.OP_RAISONNEMENT_ACTIVER, {}, motif=motif)
    with pret() as cnx:
        assert service.raisonnement_actif(cnx) is False
    r = _appliquer(pret, service.OP_RAISONNEMENT_ACTIVER, {}, motif="Analyse contractuelle complexe")
    assert r["raisonnement"]["actif"] is True and r["raisonnement"]["par"] == PROPRIETAIRE
    with pret() as cnx:
        assert service.raisonnement_actif(cnx) is True
    _appliquer(pret, service.OP_RAISONNEMENT_DESACTIVER, {}, niveau=None)  # fermer ne demande pas N3
    with pret() as cnx:
        assert service.raisonnement_actif(cnx) is False


# -- plafonds et coûts ------------------------------------------------------------------------------------------------
def test_plafonds_n2_sans_confirmation_et_valeurs_bornees(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    r = _appliquer(
        pret,
        service.OP_ROLE_PLAFONDS,
        {"role": "llm_rapide", "plafond_jetons_jour": 5000, "budget_usd_mois": "12.50"},
        niveau=None,
    )
    assert r["plafond_jetons_jour"] == 5000 and r["budget_usd_mois"] == "12.5"
    for valeur in (0, -1, True, 1.5, "10", 10**13):
        _refus(
            pret,
            codes.DECLARATION_INVALIDE,
            service.OP_ROLE_PLAFONDS,
            {"role": "llm_rapide", "plafond_jetons_jour": valeur},
            niveau=None,
        )
    for valeur in ("-1", "0", "abc", True, "1e400", "NaN", 10**8, "9" * 30):
        _refus(
            pret,
            codes.DECLARATION_INVALIDE,
            service.OP_ROLE_PLAFONDS,
            {"role": "llm_rapide", "budget_usd_mois": valeur},
            niveau=None,
        )
    r = _appliquer(pret, service.OP_ROLE_PLAFONDS, {"role": "llm_rapide"}, niveau=None)  # effacer = plus de plafond
    assert r["plafond_jetons_jour"] is None and r["budget_usd_mois"] is None


def test_couts_declares_par_le_proprietaire_avec_source(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    r = _appliquer(
        pret,
        service.OP_ROLE_COUTS,
        {
            "role": "llm_rapide",
            "cout_entree_par_million": "1",
            "cout_sortie_par_million": "5",
            "cout_source": "grille du contrat",
        },
        niveau=None,
    )
    assert (r["cout_entree_par_million"], r["cout_sortie_par_million"]) == ("1", "5")
    assert _vue(pret, "llm_rapide")["cout"]["source"] == "grille du contrat"
    _refus(
        pret,
        codes.DECLARATION_INVALIDE,
        service.OP_ROLE_COUTS,
        {"role": "llm_rapide", "cout_entree_par_million": "-3"},
        niveau=None,
    )


def test_changer_de_modele_remet_les_couts_a_non_declare_mais_garde_les_plafonds(pret):
    affecter(
        pret,
        "llm_rapide",
        ALIAS["llm_rapide"],
        plafond_jetons_jour=900,
        cout_entree_par_million="1",
        cout_sortie_par_million="5",
    )
    affecter(pret, "llm_rapide", "autre-modele-rapide", plafond_jetons_jour=None)  # plafond absent des paramètres
    v = _vue(pret, "llm_rapide")
    assert v["modele_appel"] == "autre-modele-rapide"
    assert v["cout"]["entree_par_million"] is None and v["cout"]["sortie_par_million"] is None
    assert v["plafonds"]["jetons_jour"] is None  # explicitement remis par la valeur None fournie
    affecter(pret, "llm_rapide", "encore-un-autre", plafond_jetons_jour=700)
    affecter_sans = {"role": "llm_rapide", "fournisseur_id": v["fournisseur"]["identifiant"], "modele_appel": "x-sans"}
    _appliquer(pret, service.OP_ROLE_AFFECTER, affecter_sans)
    assert _vue(pret, "llm_rapide")["plafonds"]["jetons_jour"] == 700  # plafond conservé quand il n'est pas fourni


def test_revision_optimiste(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    v = _vue(pret, "llm_rapide")
    ident = v["fournisseur"]["identifiant"]
    _refus(
        pret,
        codes.CONFLIT_REVISION,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_rapide", "fournisseur_id": ident, "modele_appel": "m2", "revision_attendue": v["revision"] + 5},
    )
    _appliquer(
        pret,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_rapide", "fournisseur_id": ident, "modele_appel": "m2", "revision_attendue": v["revision"]},
    )
    assert _vue(pret, "llm_rapide")["revision"] == v["revision"] + 1


# -- historique append-only et retour arrière -------------------------------------------------------------------------
def test_historique_journalise_chaque_changement_sans_secret(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    with pret() as cnx:
        histo = service.historique(cnx, "role:llm_rapide")
    assert len(histo) == 1 and histo[0]["action"] == "role.affecter" and histo[0]["niveau"] == "N3"
    assert histo[0]["avant"] is None and histo[0]["apres"]["modele_appel"] == ALIAS["llm_rapide"]
    assert histo[0]["acteur"] == PROPRIETAIRE


def test_historique_est_append_only(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    with pytest.raises(DBAPIError, match="immuable"), pret() as cnx:
        cnx.execute(text("UPDATE modeles_historique SET acteur = 'x'"))
    with pytest.raises(DBAPIError, match="immuable"), pret() as cnx:
        cnx.execute(text("DELETE FROM modeles_historique"))


def test_retour_arriere_role_restaure_l_etat_d_avant_et_se_defait(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    ident = _vue(pret, "llm_rapide")["fournisseur"]["identifiant"]
    _appliquer(
        pret,
        service.OP_ROLE_AFFECTER,
        {"role": "llm_rapide", "fournisseur_id": ident, "modele_appel": "modele-b", "plafond_jetons_jour": 123},
    )
    assert _vue(pret, "llm_rapide")["modele_appel"] == "modele-b"
    _appliquer(pret, service.OP_REVENIR, {"cible": "role:llm_rapide"})
    v = _vue(pret, "llm_rapide")
    assert v["modele_appel"] == ALIAS["llm_rapide"] and v["plafonds"]["jetons_jour"] is None
    _appliquer(pret, service.OP_REVENIR, {"cible": "role:llm_rapide"})  # annuler l'annulation
    assert _vue(pret, "llm_rapide")["modele_appel"] == "modele-b"


def test_retour_arriere_d_une_premiere_affectation_remet_le_role_inerte_et_la_selection(pret):
    affecter(pret, "embeddings", ALIAS["embeddings"])
    with pret() as cnx:
        assert [s["identifiant"] for s in registre.selections(cnx) if s["capacite"] == "embeddings"]
    _appliquer(pret, service.OP_REVENIR, {"cible": "role:embeddings"})
    assert _vue(pret, "embeddings")["etat"] == "inerte"
    with pret() as cnx:
        assert not [s for s in registre.selections(cnx) if s["capacite"] == "embeddings"]


def test_retour_arriere_revalide_le_fournisseur(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    ident = _vue(pret, "llm_rapide")["fournisseur"]["identifiant"]
    _appliquer(pret, service.OP_ROLE_RETIRER, {"role": "llm_rapide"})
    with pret() as cnx:
        registre.desactiver(cnx, acteur=PROPRIETAIRE, identifiant=ident)
    _refus(pret, codes.FOURNISSEUR_INVALIDE, service.OP_REVENIR, {"cible": "role:llm_rapide"})
    assert _vue(pret, "llm_rapide")["etat"] == "inerte"


def test_retour_arriere_sans_historique_ou_cible_invalide(pret):
    _refus(pret, codes.RIEN_A_ANNULER, service.OP_REVENIR, {"cible": "role:llm_rapide"})
    _refus(pret, codes.RIEN_A_ANNULER, service.OP_REVENIR, {"cible": "raisonnement"})
    for cible in ("role:", "autre", None, "role:LLM", "../x", "role:inconnu_role"):
        with pytest.raises(ModelesErreur):
            _appliquer(pret, service.OP_REVENIR, {"cible": cible})


def test_retour_arriere_du_raisonnement_et_de_la_passerelle(pret, faux):
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    _appliquer(pret, service.OP_RAISONNEMENT_ACTIVER, {}, motif="Analyse contractuelle complexe")
    _appliquer(pret, service.OP_REVENIR, {"cible": "raisonnement"})
    with pret() as cnx:
        assert service.raisonnement_actif(cnx) is False
    _appliquer(pret, service.OP_ROLE_RETIRER, {"role": "llm_raisonnement"})
    # la passerelle : modifier l'URL puis revenir
    from modeles_aide import connecter_passerelle

    ancienne = _vue_passerelle(pret)["url_base"]
    connecter_passerelle(pret, faux.url.replace("127.0.0.1", "localhost"))
    assert _vue_passerelle(pret)["url_base"] != ancienne
    _appliquer(pret, service.OP_REVENIR, {"cible": "passerelle"})
    assert _vue_passerelle(pret)["url_base"] == ancienne


def _vue_passerelle(session):
    with session() as cnx:
        return service.vue_passerelle(cnx)


# -- passerelle : URL et secrets --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "ftp://x",
        "http://exemple.com",
        "https://u:p@exemple.com",
        "https://exemple.com/?k=v",
        "https://exemple.com/#f",
        "https://exemple.com/autre",
        "https://169.254.169.254",
        "http://0.0.0.0:4000",
        "https://",
        "x",
        "",
        None,
        5,
        "https://exemple.com:99999",
        "http://litellm:4000/\n",
        "https://[fe80::1]",
    ],
)
def test_urls_de_passerelle_refusees(pret, url):
    _refus(
        pret,
        codes.URL_REFUSEE,
        service.OP_PASSERELLE_CONFIGURER,
        {"mode": "integree", "url_base": url, "secret_cle": "passerelle.cle"},
    )


def test_urls_de_passerelle_permises_et_http_prive_confirme(pret):
    ok = [
        ("https://litellm.client.example.test", False),
        ("https://litellm.client.example.test/v1", False),
        ("http://127.0.0.1:4000", False),
        ("http://localhost:4000", False),
        ("http://[::1]:4000", False),
        ("http://litellm:4000", True),
        ("http://192.168.1.20:4000", True),
        ("http://10.0.0.5:4000", True),
    ]
    for url, prive in ok:
        r = _appliquer(
            pret,
            service.OP_PASSERELLE_CONFIGURER,
            {"mode": "existante", "url_base": url, "secret_cle": "passerelle.cle", "reseau_prive_confirme": prive},
        )
        assert r["passerelle"]["url_base"] == url.rstrip("/")
    for url in ("http://litellm:4000", "http://192.168.1.20:4000", "http://8.8.8.8:4000", "http://exemple.com"):
        _refus(
            pret,
            codes.URL_REFUSEE,
            service.OP_PASSERELLE_CONFIGURER,
            {"mode": "existante", "url_base": url, "secret_cle": "passerelle.cle", "reseau_prive_confirme": False},
        )
    _refus(
        pret,
        codes.URL_REFUSEE,
        service.OP_PASSERELLE_CONFIGURER,
        {  # même confirmé, un hôte public reste en https
            "mode": "existante",
            "url_base": "http://8.8.8.8:4000",
            "secret_cle": "passerelle.cle",
            "reseau_prive_confirme": True,
        },
    )


def test_passerelle_exige_des_secrets_actifs_du_coffre_et_des_champs_valides(pret):
    base = {"mode": "integree", "url_base": "https://litellm.client.example.test", "secret_cle": "passerelle.cle"}
    _refus(pret, codes.SECRET_INDISPONIBLE, service.OP_PASSERELLE_CONFIGURER, {**base, "secret_cle": "n.existe.pas"})
    _refus(pret, codes.DECLARATION_INVALIDE, service.OP_PASSERELLE_CONFIGURER, {**base, "secret_cle": "Mauvais Nom!"})
    _refus(pret, codes.DECLARATION_INVALIDE, service.OP_PASSERELLE_CONFIGURER, {**base, "mode": "autre"})
    _refus(pret, codes.DECLARATION_INVALIDE, service.OP_PASSERELLE_CONFIGURER, {**base, "reseau_prive_confirme": "oui"})
    _refus(
        pret,
        codes.DECLARATION_INVALIDE,
        service.OP_PASSERELLE_CONFIGURER,
        {**base, "secrets_amont": {"inconnu": "passerelle.openrouter"}},
    )
    _refus(
        pret,
        codes.SECRET_INDISPONIBLE,
        service.OP_PASSERELLE_CONFIGURER,
        {**base, "secrets_amont": {"openrouter": "absent.du.coffre"}},
    )


def test_passerelle_non_retirable_tant_qu_un_role_en_depend(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    e = _refus(pret, codes.PASSERELLE_ABSENTE, service.OP_PASSERELLE_RETIRER, {})
    assert "llm_rapide" in e.detail
    _appliquer(pret, service.OP_ROLE_RETIRER, {"role": "llm_rapide"})
    _appliquer(pret, service.OP_PASSERELLE_RETIRER, {})
    assert _vue_passerelle(pret) == {"configuree": False}


# -- sélection du registre ---------------------------------------------------------------------------------------------
def test_les_roles_a_capacite_unique_alimentent_la_selection_du_registre(pret):
    affecter(pret, "embeddings", ALIAS["embeddings"])
    with pret() as cnx:
        selection = registre.resoudre(cnx, "embeddings")
    assert selection.fournisseur.identifiant == "embeddings.passerelle.opsys-embed-e5-multilingue"
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])
    with pret() as cnx, pytest.raises(registre.RegistreErreur):
        registre.resoudre(cnx, "llm")  # les rôles LLM n'écrasent aucune sélection globale
    _appliquer(pret, service.OP_ROLE_RETIRER, {"role": "embeddings"})
    with pret() as cnx, pytest.raises(registre.RegistreErreur):
        registre.resoudre(cnx, "embeddings")
