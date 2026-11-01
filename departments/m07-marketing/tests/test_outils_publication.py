"""Les douze outils M7 WordPress et sas social, de bout en bout : registres durables, file d'approbation, niveaux,
refus.

Rien n'est exécuté : un N3/N4 approuvé CONSIGNE la décision (`PUBLICATION_APPROUVEE_NON_EXECUTEE`) ; aucun jeton
n'est émis,
aucun réseau appelé, aucun brouillon transmis.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from m7_marketing import journal_chaine, outils, publication_outils
from m7_marketing.sas_social import comptes, etats
from m7_marketing.wordpress import flux

from opsys import approbations, contexte, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique

sys.path.insert(0, str(Path(__file__).resolve().parent / "sas_social"))
from fabriques_sociales import COMPTE, DEMAIN_10H, annonce, publication  # noqa: E402

FICTIF = True
_M7 = Path(__file__).resolve().parents[1]
_OUTILS = {o.nom: o for o in outils.outils()}
_DEPARTEMENTS = {"m07-marketing": lire_manifeste(_M7)}
HORODATAGE = "2026-01-05T15:00:00+00:00"
SITE = "horizon-fictif.example"
CLE_WP = "cle-wordpress-0123456789"
ARTICLE = {
    "type": "post",
    "titre": "Rénovation de toiture à Laval",
    "contenu": "<p>Un texte sobre.</p>",
    "extrait": "",
    "slug": "",
}


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    # L'heure d'une décision est celle du SERVEUR (`approbations.instant_de_la_decision_en_cours`, revue app-04) et non
    # l'`horodatage` déposé par l'agent : le test fixe l'horloge du serveur à l'instant de ses données.
    monkeypatch.setattr(approbations, "_maintenant", lambda: HORODATAGE)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Propriétaire fictif", "mot-de-passe-test-1234", ["nathan_owner"])
        identite.creer_personne(cnx, "gestion", "Gestionnaire fictif", "mot-de-passe-test-1234", ["admin"])
    yield
    stockage.liberer()


def _demande(nom, arguments, niveau=Niveau.N3):
    with stockage.transaction() as cnx:
        return approbations.creer_demande(cnx, "m07-marketing", nom, arguments, niveau=niveau)


def _decider(demande, approuver=True, qui="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, demande, approuver, qui, _OUTILS, _DEPARTEMENTS)


def _approuve(nom, arguments, niveau=Niveau.N3):
    sortie = _decider(_demande(nom, arguments, niveau))
    assert sortie["statut"] == "executee", sortie
    return sortie["reponse"]["resultat"]


def _agent(nom, arguments):
    return executer_atomique(_OUTILS[nom], arguments)["resultat"]


def _journal(registre):
    return list(stockage.maillons(*registre))


# -- le manifeste
# --------------------------------------------------------------------------------------------------------------
NIVEAUX = {
    "m7_enregistrer_site_wordpress": (Autonomie.T1, Niveau.N3),
    "m7_preparer_brouillon_wordpress": (Autonomie.T1, Niveau.N2),
    "m7_demander_publication_wordpress": (Autonomie.T1, Niveau.N3),
    "m7_annuler_publication_wordpress": (Autonomie.T1, Niveau.N2),
    "m7_lire_publication_wordpress": (Autonomie.T0, Niveau.N0),
    "m7_enregistrer_compte_social": (Autonomie.T1, Niveau.N3),
    "m7_composer_publication_sociale": (Autonomie.T1, Niveau.N2),
    "m7_soumettre_publication_sociale": (Autonomie.T1, Niveau.N2),
    "m7_demander_publication_sociale": (Autonomie.T1, Niveau.N3),
    "m7_demander_annonce_payante": (Autonomie.T1, Niveau.N4),
    "m7_annuler_publication_sociale": (Autonomie.T1, Niveau.N2),
    "m7_lire_file_publication_sociale": (Autonomie.T0, Niveau.N0),
}


@pytest.mark.parametrize("nom", sorted(NIVEAUX))
def test_niveaux_et_portees_fermees(nom):
    outil = _OUTILS[nom]
    assert (outil.autonomie, outil.niveau_effectif) == NIVEAUX[nom]
    assert outil.roles_appareil == frozenset(), "aucun appareil : fermé par défaut"
    assert not outil.frontiere_humaine, "ni T3 ni N5 : rien n'est exécuté par ces outils"
    assert outil.parametres["additionalProperties"] is False


def test_le_manifeste_charge_les_douze_outils_et_n4_est_reserve_au_proprietaire():
    departement = lire_manifeste(_M7)
    assert set(NIVEAUX) <= {o.nom for o in departement.charger_outils()}
    assert set(departement.roles_autorises(Niveau.N3)) == {"nathan_owner"}
    assert set(departement.roles_autorises(Niveau.N4)) == {"nathan_owner"}


def test_les_seuls_niveaux_n4_de_m7_sont_les_engagements_de_depense():
    """L'annonce payante du sas social et, depuis la tranche « signaux », le LANCEMENT d'un plan de campagne payante
    (`m7_demander_lancement_campagne`, consigné et jamais exécuté) : deux engagements de dépense, rien d'autre."""
    n4 = {o.nom for o in outils.outils() if o.niveau_effectif is Niveau.N4}
    assert n4 == {"m7_demander_annonce_payante", "m7_demander_lancement_campagne"}


def test_aucun_outil_ne_publie_emet_un_jeton_ou_appelle_un_reseau():
    """Les fonctions des douze outils n'importent ni exécuteur, ni client, ni adaptateur."""
    import ast
    import inspect

    source = inspect.getsource(publication_outils)
    arbre = ast.parse(source)
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.ImportFrom):
            importes |= {(noeud.module or "") + "." + a.name for a in noeud.names}
        elif isinstance(noeud, ast.Import):
            importes |= {a.name for a in noeud.names}
    interdits = ("executeur", "client", "doubles", "jeton", "secret_coffre", "signature", "secrets_coffre")
    assert not [i for i in importes if any(mot in i for mot in interdits)], importes
    assert (
        "coffre" not in source.lower().replace("le coffre", "").replace("du coffre", "").replace("dans le coffre", "")
        or "utiliser" not in source
    )


# -- sites WordPress
# ------------------------------------------------------------------------------------------------------------
SITE_ARGS = {
    "site_id": SITE,
    "base_url": "https://horizon-fictif.example",
    "secret_ref": {"nom": "wordpress.horizon-fictif", "cle_id": "default"},
    "types_autorises": ["post", "page"],
    "fictif": True,
    "horodatage": HORODATAGE,
}


def test_un_agent_seul_ne_branche_pas_un_site(base):
    refus = _agent("m7_enregistrer_site_wordpress", SITE_ARGS)["refus"]
    assert [r["code"] for r in refus] == ["REJ-HUMAIN-REQUIS"] and "N3" in refus[0]["detail"]
    assert _journal(publication_outils.REGISTRE_SITES) == []


def test_un_appareil_admin_qui_n_est_pas_le_proprietaire_ne_branche_pas_un_site(base):
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("gestion", "admin")), stockage.transaction():
        resultat = (
            outils.enregistrer_site_wordpress(**SITE_ARGS)
            if hasattr(outils, "enregistrer_site_wordpress")
            else publication_outils.enregistrer_site_wordpress(**SITE_ARGS)
        )
    assert [r["code"] for r in resultat["refus"]] == ["REJ-HUMAIN-ROLE-INSUFFISANT"]


def test_le_proprietaire_branche_un_site_par_la_file_et_le_secret_n_entre_pas_au_registre(base):
    resultat = _approuve("m7_enregistrer_site_wordpress", SITE_ARGS)
    assert resultat == {"accepte": True, "site_id": SITE, "deja_enregistre": False}
    registre = _journal(publication_outils.REGISTRE_SITES)
    assert registre[0]["par"] == "nathan" and registre[0]["site"]["secret_ref"] == {
        "nom": "wordpress.horizon-fictif",
        "cle_id": "default",
    }
    assert journal_chaine.verifier(registre) == []
    assert _approuve("m7_enregistrer_site_wordpress", SITE_ARGS)["deja_enregistre"] is True
    assert len(_journal(publication_outils.REGISTRE_SITES)) == 1


@pytest.mark.parametrize(
    "modification",
    [
        {"base_url": "http://horizon-fictif.example"},
        {"base_url": "https://192.168.0.10"},
        {"base_url": "https://user:mdp@horizon-fictif.example"},
        {"base_url": "https://horizon-fictif.example?x=1"},
        {"base_url": "https://horizon-reel.com"},
        {"fictif": False},
        {"secret_ref": {"nom": "x"}},
        {"secret_ref": {"nom": "AAA", "cle_id": "d"}},
        {"types_autorises": ["post", "post"]},
        {"site_id": "Majuscules"},
    ],
)
def test_un_enregistrement_de_site_invalide_est_refuse(base, modification):
    sortie = _decider(_demande("m7_enregistrer_site_wordpress", {**SITE_ARGS, **modification}))
    assert sortie["statut"] == "echec"
    assert _journal(publication_outils.REGISTRE_SITES) == []


def test_un_site_reel_ne_peut_pas_porter_un_domaine_reserve_ni_l_inverse(base):
    sortie = _decider(_demande("m7_enregistrer_site_wordpress", {**SITE_ARGS, "fictif": False}))
    assert sortie["reponse"]["resultat"]["refus"][0]["code"] == "REJ-WP-FICTIF-DOMAINE"
    sortie = _decider(_demande("m7_enregistrer_site_wordpress", {**SITE_ARGS, "base_url": "https://horizon-reel.com"}))
    assert sortie["reponse"]["resultat"]["refus"][0]["code"] == "REJ-WP-FICTIF-DOMAINE"


def test_un_horodatage_sans_fuseau_est_refuse(base):
    refus = _agent(
        "m7_preparer_brouillon_wordpress",
        {
            "site_id": SITE,
            "article": ARTICLE,
            "statut_cible": "draft",
            "cle_idempotence": CLE_WP,
            "texte_genere_par_ia": True,
            "horodatage": "2026-01-05T15:00:00",
        },
    )["refus"]
    assert refus[0]["code"] == "REJ-PUBLICATION-HORODATAGE"


# -- brouillons WordPress (N2, autonome)
# -------------------------------------------------------------------------------------------
def _brancher_site():
    _approuve("m7_enregistrer_site_wordpress", SITE_ARGS)


def _brouillon(**plus):
    arguments = {
        "site_id": SITE,
        "article": ARTICLE,
        "statut_cible": "draft",
        "cle_idempotence": CLE_WP,
        "texte_genere_par_ia": True,
        "horodatage": HORODATAGE,
    }
    arguments.update(plus)
    return arguments


def test_un_agent_prepare_un_brouillon_sans_approbation_et_rien_n_est_transmis(base):
    _brancher_site()
    resultat = _agent("m7_preparer_brouillon_wordpress", _brouillon())
    assert (
        resultat["accepte"] and resultat["etat"] == "brouillon" and "PAS encore sur le site" in resultat["transmission"]
    )
    journal = _journal(publication_outils.REGISTRE_PUBLICATIONS_WP)
    assert [m["type"] for m in journal] == ["brouillon_prepare"] and journal[0]["ia_generee"] is True
    assert journal[0]["par"] == "agent"
    assert not [m for m in journal if m["type"] in ("brouillon_transmis", "jeton_emis", "publie")]


def test_le_rejeu_de_la_preparation_ne_cree_pas_un_second_brouillon(base):
    _brancher_site()
    premier = _agent("m7_preparer_brouillon_wordpress", _brouillon())
    second = _agent("m7_preparer_brouillon_wordpress", _brouillon())
    assert second["deja_prepare"] is True and second["publication_id"] == premier["publication_id"]
    assert len(_journal(publication_outils.REGISTRE_PUBLICATIONS_WP)) == 1
    conflit = _agent("m7_preparer_brouillon_wordpress", _brouillon(article={**ARTICLE, "titre": "Un autre titre"}))
    assert conflit["refus"][0]["code"] == "REJ-WP-CLE-CONFLIT"


@pytest.mark.parametrize(
    ("modification", "code"),
    [
        ({"statut_cible": "publish"}, "schema"),
        ({"site_id": "inconnu.example"}, "REJ-WP-SITE-INACTIF"),
        ({"article": {**ARTICLE, "type": "attachment"}}, "schema"),
        ({"article": {**ARTICLE, "contenu": "<script>alert(1)</script>"}}, "REJ-WP-CONTENU-ACTIF"),
        ({"article": {**ARTICLE, "contenu": '<a href="javascript:alert(1)">x</a>'}}, "REJ-WP-CONTENU-ACTIF"),
        ({"article": {**ARTICLE, "contenu": '<img src=x onerror="alert(1)">'}}, "REJ-WP-CONTENU-ACTIF"),
        ({"article": {**ARTICLE, "contenu": "<iframe src='https://x.example'></iframe>"}}, "REJ-WP-CONTENU-ACTIF"),
        ({"article": {**ARTICLE, "contenu": "<p>Le meilleur toit, rabais de 50 %.</p>"}}, "REJ-EXAGERATION"),
        ({"article": {**ARTICLE, "titre": ""}}, "REJ-WP-CHAMP"),
        ({"article": {**ARTICLE, "slug": "Pas Propre"}}, "REJ-WP-CHAMP"),
        ({"article": {**ARTICLE, "contenu": "x" * 100_001}}, "REJ-WP-CHAMP"),
        ({"article": {**ARTICLE, "auteur": "admin"}}, "REJ-WP-CHAMP"),
        ({"cle_idempotence": "courte"}, "schema"),
    ],
)
def test_un_brouillon_hostile_est_refuse_avant_toute_ecriture(base, modification, code):
    _brancher_site()
    reponse = executer_atomique(_OUTILS["m7_preparer_brouillon_wordpress"], _brouillon(**modification))
    if code == "schema":
        assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    else:
        codes = [r["code"] for r in reponse["resultat"]["refus"]]
        assert code in codes, codes
    assert _journal(publication_outils.REGISTRE_PUBLICATIONS_WP) == []


def test_un_contenu_produit_par_un_modele_doit_etre_marque(base):
    _brancher_site()
    resultat = publication_outils.preparer_brouillon_wordpress(SITE, ARTICLE, "draft", CLE_WP, "oui", HORODATAGE)
    assert resultat["refus"][0]["code"] == "REJ-WP-IA-NON-DECLAREE"


def test_publier_demande_un_brouillon_revu_sur_le_site(base):
    _brancher_site()
    pid = _agent("m7_preparer_brouillon_wordpress", _brouillon())["publication_id"]
    sortie = _decider(
        _demande(
            "m7_demander_publication_wordpress",
            {"publication_id": pid, "empreinte": "a" * 64, "action": "publish", "horodatage": HORODATAGE},
        )
    )
    assert sortie["reponse"]["resultat"]["refus"][0]["code"] == "REJ-WP-ETAT"


def _transmettre(pid, post_id=42, empreinte="b" * 64):
    journal = stockage.maillons(*publication_outils.REGISTRE_PUBLICATIONS_WP)
    with stockage.transaction():
        assert flux.consigner_transmission(journal, pid, post_id, empreinte, "2026-01-05T15:01:00Z")["accepte"]


def test_la_publication_wordpress_approuvee_est_consignee_jamais_executee(base):
    _brancher_site()
    pid = _agent("m7_preparer_brouillon_wordpress", _brouillon())["publication_id"]
    _transmettre(pid)
    assert (
        _agent(
            "m7_demander_publication_wordpress",
            {
                "publication_id": pid,
                "empreinte": "b" * 64,
                "action": "publish",
                "horodatage": HORODATAGE,
            },
        )["refus"][0]["code"]
        == "REJ-HUMAIN-REQUIS"
    )
    resultat = _approuve(
        "m7_demander_publication_wordpress",
        {
            "publication_id": pid,
            "empreinte": "b" * 64,
            "action": "schedule",
            "publier_le": "2026-01-06T15:00:00Z",
            "horodatage": HORODATAGE,
        },
    )
    assert resultat["statut"] == "PUBLICATION_APPROUVEE_NON_EXECUTEE" and resultat["execute"] is False
    assert resultat["approbation"] == {"par": "nathan", "role": "nathan_owner", "source": "approbation"}
    etat = flux.plier(_journal(publication_outils.REGISTRE_PUBLICATIONS_WP))[pid]
    assert etat.etat == "approuve" and not etat.jeton_emis
    lu = _agent("m7_lire_publication_wordpress", {"publication_id": pid})
    assert lu["publication"]["etat"] == "approuve" and lu["publication"]["jeton_emis"] is False
    assert "approval_token" not in json.dumps(lu) and "jeton" not in lu["publication"].get("approbation", {})


def test_approuver_une_autre_empreinte_est_refuse(base):
    _brancher_site()
    pid = _agent("m7_preparer_brouillon_wordpress", _brouillon())["publication_id"]
    _transmettre(pid)
    sortie = _decider(
        _demande(
            "m7_demander_publication_wordpress",
            {"publication_id": pid, "empreinte": "c" * 64, "action": "publish", "horodatage": HORODATAGE},
        )
    )
    assert sortie["reponse"]["resultat"]["refus"][0]["code"] == "REJ-WP-EMPREINTE-DIFFERENTE"


def test_annuler_une_publication_wordpress_est_autonome(base):
    _brancher_site()
    pid = _agent("m7_preparer_brouillon_wordpress", _brouillon())["publication_id"]
    resultat = _agent(
        "m7_annuler_publication_wordpress",
        {"publication_id": pid, "motif": "plus d'actualité", "horodatage": HORODATAGE},
    )
    assert resultat["accepte"] and resultat["etat"] == "annule"
    assert (
        _agent("m7_annuler_publication_wordpress", {"publication_id": pid, "motif": "x", "horodatage": HORODATAGE})[
            "refus"
        ][0]["code"]
        == "REJ-WP-ETAT"
    )


def test_lire_les_publications_wordpress_liste_aussi_les_sites(base):
    _brancher_site()
    _agent("m7_preparer_brouillon_wordpress", _brouillon())
    lu = _agent("m7_lire_publication_wordpress", {})
    assert lu["total"] == 1 and lu["sites"][0]["site_id"] == SITE and lu["sites"][0]["actif"] is True
    assert "contenu" not in json.dumps(lu["publications"][0])


# -- sas social
# ----------------------------------------------------------------------------------------------------------------------
COMPTE_ARGS = {
    "reseau": "facebook",
    "compte": COMPTE,
    "secret_ref": {"nom": "social.facebook.horizon"},
    "fictif": True,
    "horodatage": HORODATAGE,
}


def _brancher_comptes():
    for reseau in ("facebook", "gbp"):
        _approuve("m7_enregistrer_compte_social", {**COMPTE_ARGS, "reseau": reseau})


def _composer(donnees=None, cle="cle-sociale-0123456789ab", **plus):
    return _agent(
        "m7_composer_publication_sociale",
        {"publication": donnees or publication("facebook"), "cle_idempotence": cle, "horodatage": HORODATAGE, **plus},
    )


def test_un_compte_social_se_branche_par_la_file_sans_jeton_au_registre(base):
    assert _agent("m7_enregistrer_compte_social", COMPTE_ARGS)["refus"][0]["code"] == "REJ-HUMAIN-REQUIS"
    assert _approuve("m7_enregistrer_compte_social", COMPTE_ARGS)["accepte"]
    registre = _journal(publication_outils.REGISTRE_COMPTES)
    assert (
        registre[0]["secret_ref"] == {"nom": "social.facebook.horizon"} and "jeton" not in json.dumps(registre).lower()
    )
    assert comptes.actifs(registre) == {
        ("facebook", COMPTE): {"secret_nom": "social.facebook.horizon", "fictif": True, "actif": True}
    }
    mauvais = _decider(
        _demande("m7_enregistrer_compte_social", {**COMPTE_ARGS, "secret_ref": {"nom": "Un Jeton Collé"}})
    )
    assert mauvais["statut"] == "echec"


def test_composer_exige_un_compte_declare(base):
    assert _composer()["refus"][0]["code"] == "REJ-SOCIAL-COMPTE-INCONNU"
    _brancher_comptes()
    resultat = _composer()
    assert resultat["accepte"] and resultat["etat"] == "brouillon"
    assert _composer()["deja_cree"] is True
    assert len(_journal(publication_outils.REGISTRE_PUBLICATIONS_SOCIALES)) == 1


def test_le_parcours_complet_organique_est_consigne_planifie_et_jamais_envoye(base):
    _brancher_comptes()
    cree = _composer()
    soumise = _agent(
        "m7_soumettre_publication_sociale", {"publication_id": cree["publication_id"], "horodatage": HORODATAGE}
    )
    assert soumise["accepte"] and soumise["niveau_requis"] == "N3"
    arguments = {"publication_id": cree["publication_id"], "empreinte": cree["empreinte"], "horodatage": HORODATAGE}
    assert _agent("m7_demander_publication_sociale", arguments)["refus"][0]["code"] == "REJ-HUMAIN-REQUIS"
    resultat = _approuve("m7_demander_publication_sociale", arguments)
    assert resultat["statut"] == "PUBLICATION_APPROUVEE_NON_EXECUTEE" and resultat["etat"] == "planifie"
    assert resultat["planifie_le"] == DEMAIN_10H and resultat["execute"] is False
    journal = _journal(publication_outils.REGISTRE_PUBLICATIONS_SOCIALES)
    assert [m["type"] for m in journal] == ["brouillon_cree", "soumise", "approuvee", "planifiee"]
    assert (
        journal[2]["approbation"] == {"par": "nathan", "role": "nathan_owner", "source": "approbation"}
        and journal[2]["niveau"] == 3
    )
    assert journal_chaine.verifier(journal) == []
    assert etats.plier(journal)[cree["publication_id"]].etat == "planifie"
    lu = _agent("m7_lire_file_publication_sociale", {})
    assert lu["total"] == 1 and lu["integrite"]["journal_intact"] is True and lu["comptes"][0]["compte"] == COMPTE


def test_l_annonce_payante_exige_n4_et_un_n3_la_refuse(base):
    _brancher_comptes()
    cree = _composer(annonce("facebook"))
    _agent("m7_soumettre_publication_sociale", {"publication_id": cree["publication_id"], "horodatage": HORODATAGE})
    arguments = {"publication_id": cree["publication_id"], "empreinte": cree["empreinte"], "horodatage": HORODATAGE}
    sortie = _decider(_demande("m7_demander_publication_sociale", arguments, Niveau.N3))
    assert sortie["reponse"]["resultat"]["refus"][0]["code"] == "REJ-SOCIAL-NIVEAU-INSUFFISANT"
    assert _agent("m7_demander_annonce_payante", arguments)["refus"][0]["code"] == "REJ-HUMAIN-REQUIS"
    resultat = _approuve("m7_demander_annonce_payante", arguments, Niveau.N4)
    assert resultat["etat"] == "planifie" and resultat["statut"] == "PUBLICATION_APPROUVEE_NON_EXECUTEE"
    assert _journal(publication_outils.REGISTRE_PUBLICATIONS_SOCIALES)[-2]["niveau"] == 4


def test_l_outil_n4_refuse_une_publication_organique(base):
    _brancher_comptes()
    cree = _composer()
    _agent("m7_soumettre_publication_sociale", {"publication_id": cree["publication_id"], "horodatage": HORODATAGE})
    sortie = _decider(
        _demande(
            "m7_demander_annonce_payante",
            {"publication_id": cree["publication_id"], "empreinte": cree["empreinte"], "horodatage": HORODATAGE},
            Niveau.N4,
        )
    )
    assert sortie["reponse"]["resultat"]["refus"][0]["code"] == "REJ-SOCIAL-NIVEAU-INSUFFISANT"


def test_une_publication_modifiee_apres_la_soumission_n_est_pas_approuvable_par_l_ancienne_empreinte(base):
    _brancher_comptes()
    cree = _composer()
    _agent("m7_soumettre_publication_sociale", {"publication_id": cree["publication_id"], "horodatage": HORODATAGE})
    revise = _composer(
        publication("facebook", texte="Un autre message, sobre lui aussi."), publication_id=cree["publication_id"]
    )
    assert revise["etat"] == "brouillon"
    sortie = _decider(
        _demande(
            "m7_demander_publication_sociale",
            {"publication_id": cree["publication_id"], "empreinte": cree["empreinte"], "horodatage": HORODATAGE},
        )
    )
    assert sortie["reponse"]["resultat"]["refus"][0]["code"] == "REJ-SOCIAL-ETAT"


def test_un_refus_de_soumission_remonte_les_regles_par_l_outil(base):
    _brancher_comptes()
    cree = _composer(publication("facebook", texte="Le meilleur toit, rabais de 50 %, appelez le 450 555 0142."))
    refus = _agent(
        "m7_soumettre_publication_sociale", {"publication_id": cree["publication_id"], "horodatage": HORODATAGE}
    )["refus"]
    assert {"REJ-EXAGERATION", "REJ-PRIX", "REJ-COORDONNEES"} <= {r["code"] for r in refus}
    assert [m["type"] for m in _journal(publication_outils.REGISTRE_PUBLICATIONS_SOCIALES)] == ["brouillon_cree"]


def test_un_media_genere_sans_composition_est_refuse_par_l_outil(base):
    from fabriques_sociales import media_photo

    _brancher_comptes()
    cree = _composer(publication("facebook", medias=[media_photo(origine="genere_non_compose", ia_generee=True)]))
    refus = _agent(
        "m7_soumettre_publication_sociale", {"publication_id": cree["publication_id"], "horodatage": HORODATAGE}
    )["refus"]
    assert "REJ-SOCIAL-MEDIA-GENERE-NON-COMPOSE" in {r["code"] for r in refus}


def test_annuler_une_publication_sociale_est_autonome_et_idempotente_en_refus(base):
    _brancher_comptes()
    cree = _composer()
    assert (
        _agent(
            "m7_annuler_publication_sociale",
            {"publication_id": cree["publication_id"], "motif": "x", "horodatage": HORODATAGE},
        )["etat"]
        == "annule"
    )
    assert (
        _agent(
            "m7_annuler_publication_sociale",
            {"publication_id": cree["publication_id"], "motif": "x", "horodatage": HORODATAGE},
        )["refus"][0]["code"]
        == "REJ-SOCIAL-ETAT"
    )


def test_un_registre_retouche_dans_la_base_arrete_les_outils(base):
    _brancher_comptes()
    cree = _composer()
    with stockage.transaction() as cnx:
        from sqlalchemy import select, update

        from opsys.stockage import codec
        from opsys.stockage.schema import REGISTRES

        ligne = codec.decoder(
            cnx.execute(
                select(REGISTRES.c.maillon).where(
                    (REGISTRES.c.registre == "publications_sociales") & (REGISTRES.c.rang == 0)
                )
            ).scalar_one()
        )
        ligne["publication"]["texte"] = "Texte retouché directement en base"
        cnx.execute(
            update(REGISTRES)
            .where((REGISTRES.c.registre == "publications_sociales") & (REGISTRES.c.rang == 0))
            .values(maillon=codec.encoder(ligne))
        )
    refus = _agent("m7_lire_file_publication_sociale", {})["refus"]
    assert refus[0]["code"] == "REJ-SOCIAL-JOURNAL-ALTERE"
    assert (
        _agent(
            "m7_soumettre_publication_sociale", {"publication_id": cree["publication_id"], "horodatage": HORODATAGE}
        )["refus"][0]["code"]
        == "REJ-SOCIAL-JOURNAL-ALTERE"
    )


def test_les_registres_sont_des_journaux_durables_distincts(base):
    assert (
        len(
            {
                publication_outils.REGISTRE_SITES,
                publication_outils.REGISTRE_PUBLICATIONS_WP,
                publication_outils.REGISTRE_COMPTES,
                publication_outils.REGISTRE_PUBLICATIONS_SOCIALES,
            }
        )
        == 4
    )
    assert all(
        r[0] == "m07-marketing" for r in (publication_outils.REGISTRE_SITES, publication_outils.REGISTRE_COMPTES)
    )
