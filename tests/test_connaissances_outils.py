"""Outils de la base de connaissances : les outils M10 (ingestion, revue, publication, validation humaine, retrait) et
les
outils communs de lecture, par le VRAI répartiteur `Capacites`, la VRAIE file d'approbation et le VRAI registre.

Données fictives. Aucun réseau : le fournisseur d'embeddings est une déclaration fictive raccordée au double
déterministe.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from connaissances_aide import (
    INJECTION,
    MAINTENANT,
    NORME,
    TAXES,
    declarer_embeddings,
    raccorder_embeddings,
)

from opsys import approbations, contexte, identite, openclaw, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.connaissances import ports, service
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau

FICTIF = True
RACINE = Path(__file__).resolve().parents[1] / "departments"
M10_OUTILS_ECRITURE = {
    "m10_ingerer_source_connaissance": Niveau.N2, "m10_reviser_source_connaissance": Niveau.N2,
    "m10_publier_source_connaissance": Niveau.N2, "m10_retirer_source_connaissance": Niveau.N2,
    "m10_reindexer_connaissances": Niveau.N2, "m10_valider_source_connaissance": Niveau.N3,
}
M10_OUTILS_LECTURE = ("m10_rechercher_connaissances", "m10_lire_connaissance", "m10_lister_sources_connaissance")
COMMUNS = ("opsys_connaissances_rechercher", "opsys_connaissances_lire")
M5 = "m05-financecore"
M3 = "m03-estimation"


@pytest.fixture
def instance(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(service, "maintenant", lambda: MAINTENANT)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def deps():
    return charger_departements(RACINE)


def _caps(deps, ident):
    return Capacites(deps, stockage.transaction, filtre={ident}, appelant=ident)


@pytest.fixture
def m10(instance, deps):
    return _caps(deps, "m10-memoire")


def _ingerer(m10, **surcharge):
    args = {"departement": M5, "cle": "taxes-fictives", "titre": "Taxes fictives de Valdoré", "domaine": "fiscalite",
            "type_source": "markdown", "editeur": "Éditeur fictif", "type_autorite": "fictive",
            "reference": "fictif://doc/1", "licence_reutilisation": "interne", "contenu": TAXES,
            "date_publication": "2026-10-01", "revision_due_le": "2027-10-01", **surcharge}
    return m10.appeler("m10_ingerer_source_connaissance", args)


def _resultat(reponse):
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _approuver(deps, demande_id, par="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, demande_id, True, par, outils_executables(deps, stockage.transaction), deps)


def _publier_reglemente(m10, deps, version_id, motif="Source relue en entier par la direction."):
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": version_id}))
    demande = m10.appeler("m10_valider_source_connaissance", {"version_id": version_id, "motif": motif})
    assert demande["statut"] == "en_attente_approbation", demande
    return _approuver(deps, demande["demande_id"])


# -- niveaux, portées d'appareil, manifeste
# -----------------------------------------------------------------------------------
def test_niveaux_et_autonomie_des_outils_m10(m10):
    par_nom = {o.nom: o for o in m10.lister()}
    for nom in M10_OUTILS_LECTURE:
        assert (par_nom[nom].autonomie, par_nom[nom].niveau_effectif) == (Autonomie.T0, Niveau.N0), nom
    for nom, niveau in M10_OUTILS_ECRITURE.items():
        assert (par_nom[nom].autonomie, par_nom[nom].niveau_effectif) == (Autonomie.T1, niveau), nom
        assert par_nom[nom].frontiere_humaine is False


def test_aucun_outil_de_connaissances_n_est_ouvert_a_un_appareil(m10, deps):
    noms = set(M10_OUTILS_LECTURE) | set(M10_OUTILS_ECRITURE) | set(COMMUNS)
    for outil in m10.lister():
        if outil.nom in noms:
            assert outil.roles_appareil == frozenset(), outil.nom
    projection = openclaw.roles_outils(deps)
    for role, outils in projection.items():
        assert not noms & set(outils), (role, noms & set(outils))


def test_les_outils_communs_sont_t0_n0_sur_chaque_departement(deps):
    for ident in deps:
        caps = _caps(deps, ident)
        for nom in COMMUNS:
            outil = caps.index[nom][1]
            assert (outil.autonomie, outil.niveau_effectif, outil.roles_appareil) == (
                Autonomie.T0, Niveau.N0, frozenset()), (ident, nom)


def test_un_appel_avec_identite_d_appareil_est_refuse_meme_pour_une_lecture(instance, deps, m10):
    _resultat(_ingerer(m10))
    admin = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
    for ident, nom, args in ((M5, "opsys_connaissances_rechercher", {"requete": "taxe de vente"}),
                             ("m10-memoire", "m10_rechercher_connaissances", {"requete": "taxe de vente"})):
        with contexte.appele_par_appareil(admin):
            reponse = _caps(deps, ident).appeler(nom, args)
        assert reponse["ok"] is False and "REJ-CONN-APPAREIL-FERME" in json.dumps(reponse)


# -- ingestion : N2 automatique, brouillon invisible
# ------------------------------------------------------------------------
def test_l_ingestion_est_automatique_n2_cree_un_brouillon_et_dit_la_prochaine_etape(m10, deps):
    assert m10.departements["m10-memoire"].mode == "ombre"  # N3 serait mis en attente ; N2 s'exécute
    r = _resultat(_ingerer(m10))
    assert (r["etat"], r["numero"], r["rejeu"], r["prochaine_etape"]) == ("brouillon", 1, False,
        "reviser_source_connaissance")
    assert r["vecteurs"]["vectorise"] is False and "AUCUN_FOURNISSEUR" in r["vecteurs"]["detail"]
    # Invisible pour les départements tant que ce n'est pas publié.
    rep = _resultat(_caps(deps, "m07-marketing").appeler("opsys_connaissances_rechercher",
        {"requete": "taxe de vente"}))
    assert rep["statut"] == "aucune_source"
    # Rejeu : la même demande ne crée rien de plus.
    assert _resultat(_ingerer(m10))["rejeu"] is True


def test_la_date_de_consultation_vient_du_serveur_jamais_de_l_agent(m10):
    refus = m10.appeler("m10_ingerer_source_connaissance", {
        "departement": M5, "cle": "x-source", "titre": "T", "domaine": "general", "type_source": "texte",
        "editeur": "E", "type_autorite": "tierce", "reference": "r", "licence_reutilisation": "interne",
        "contenu": "texte", "date_consultation": "2000-01-01"})
    assert refus["ok"] is False and "date_consultation" in json.dumps(refus)  # paramètre inconnu : refusé
    r = _resultat(_ingerer(m10, cle="y-source", domaine="general"))
    lu = _resultat(m10.appeler("m10_lire_connaissance", {"version_id": r["version_id"]}))
    assert lu["date_consultation"] == "2026-11-01"


@pytest.mark.parametrize("surcharge", [
    {"departement": "m11-inconnu"}, {"departement": "m99-fictif"}, {"cle": "Mauvaise Clé"}, {"domaine": "astrologie"},
    {"contenu": None, "contenu_base64": None}, {"contenu_base64": "AAAA"},  # deux contenus / base64 hors pdf
    {"type_source": "pdf"},  # pdf en texte
])
def test_ingestion_hostile_ou_incoherente_est_refusee_sans_rien_ecrire(m10, surcharge):
    reponse = _ingerer(m10, **surcharge)
    assert reponse["ok"] is False
    liste = _resultat(m10.appeler("m10_lister_sources_connaissance", {"departement": M5}))
    assert liste["total"] == 0


def test_un_pdf_est_refuse_proprement_quand_l_isolation_est_absente(m10, monkeypatch):
    from opsys.ingestion_onboarding import extraction_texte
    from opsys.ingestion_onboarding.codes import EchecEtape

    def indisponible(_octets):
        raise EchecEtape("REJ-ING-ISOLATION-INDISPONIBLE", "bubblewrap absent", reprenable=True)

    monkeypatch.setattr(extraction_texte, "extracteur_pdf_isole", indisponible)
    reponse = m10.appeler("m10_ingerer_source_connaissance", {
        "departement": M5, "cle": "guide-pdf", "titre": "T", "domaine": "general", "type_source": "pdf", "editeur": "E",
        "type_autorite": "tierce", "reference": "r", "licence_reutilisation": "interne",
        "contenu_base64": base64.b64encode(b"%PDF-1.7 faux").decode()})
    assert reponse["ok"] is False and "REJ-CONN-PDF-INDISPONIBLE" in reponse["details"]
    mauvais = m10.appeler("m10_ingerer_source_connaissance", {
        "departement": M5, "cle": "guide-pdf", "titre": "T", "domaine": "general", "type_source": "pdf", "editeur": "E",
        "type_autorite": "tierce", "reference": "r", "licence_reutilisation": "interne", "contenu_base64": "pas "
                                                                                                           "base64!"})
    assert mauvais["ok"] is False and "base64" in mauvais["details"]


# -- publication : N2 interne, N3 humain pour le réglementé
# ---------------------------------------------------------------------
def test_une_source_non_reglementee_se_publie_en_n2_sans_humain(m10, deps):
    r = _resultat(_ingerer(m10, departement=M3, cle="norme", domaine="technique", contenu=NORME))
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": r["version_id"]}))
    p = _resultat(m10.appeler("m10_publier_source_connaissance", {"version_id": r["version_id"]}))
    assert p["etat"] == "publie"
    rep = _resultat(_caps(deps, M3).appeler("opsys_connaissances_rechercher", {"requete": "hauteur du garde-corps"}))
    assert rep["statut"] == "ok" and rep["resultats"][0]["source"]["departement"] == M3


def test_une_source_fiscale_ne_se_publie_pas_par_l_outil_n2(m10):
    r = _resultat(_ingerer(m10))
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": r["version_id"]}))
    refus = m10.appeler("m10_publier_source_connaissance", {"version_id": r["version_id"]})
    assert refus["ok"] is False and "REJ-CONN-REVUE-HUMAINE-REQUISE" in refus["details"]
    assert "CPA" in refus["details"]


def test_la_validation_humaine_est_un_n3_mis_en_attente_puis_approuve_par_la_personne(m10, deps):
    r = _resultat(_ingerer(m10))
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": r["version_id"]}))
    demande = m10.appeler("m10_valider_source_connaissance", {
        "version_id": r["version_id"], "motif": "Source relue en entier par la direction."})
    assert demande["ok"] is True and demande["statut"] == "en_attente_approbation"  # rien n'est publié sans la personne
    assert _resultat(m10.appeler("m10_lister_sources_connaissance", {"departement": M5, "etat": "revu"}))["total"] == 1
    decision = _approuver(deps, demande["demande_id"])
    assert decision["statut"] == "executee"
    lu = _resultat(m10.appeler("m10_lire_connaissance", {"version_id": r["version_id"]}))
    dernier = lu["historique"][-1]
    assert (dernier["etat"], dernier["par"], dernier["mode"], dernier["role"], dernier["raison"]) == (
        "publie", "nathan", "humain", "nathan_owner", "Source relue en entier par la direction.")
    assert lu["mention_professionnelle"].startswith("À valider auprès d'un comptable (CPA)")
    assert lu["demonstration_fictive"] is True and lu["integrite"] is True


@pytest.mark.parametrize("mode", ["supervise", "autonome"])
def test_un_agent_seul_ne_valide_jamais_meme_sans_file_d_approbation(m10, deps, mode):
    r = _resultat(_ingerer(m10))
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": r["version_id"]}))
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, "m10-memoire", mode, "nathan")
    reponse = m10.appeler("m10_valider_source_connaissance", {
        "version_id": r["version_id"], "motif": "Je me valide moi-même, sans personne."})
    assert reponse["ok"] is False and "REJ-CONN-REVUE-HUMAINE-REQUISE" in reponse["details"]
    assert _resultat(m10.appeler("m10_lister_sources_connaissance", {"departement": M5, "etat": "revu"}))["total"] == 1


def test_un_motif_trop_court_est_refuse_a_l_approbation(m10, deps):
    r = _resultat(_ingerer(m10))
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": r["version_id"]}))
    demande = m10.appeler("m10_valider_source_connaissance", {"version_id": r["version_id"], "motif": "ok"})
    decision = _approuver(deps, demande["demande_id"])
    assert decision["reponse"]["ok"] is False and "REJ-CONN-RAISON-REQUISE" in decision["reponse"]["details"]
    assert _resultat(m10.appeler("m10_lister_sources_connaissance", {"departement": M5,
        "etat": "publie"}))["total"] == 0


def test_un_admin_ne_valide_pas_un_n3_de_m10_la_politique_par_defaut_est_nathan_seul(m10, deps):
    r = _resultat(_ingerer(m10))
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": r["version_id"]}))
    demande = m10.appeler("m10_valider_source_connaissance", {
        "version_id": r["version_id"], "motif": "Validation par un rôle non autorisé."})
    with pytest.raises(ValueError, match="aucun rôle autorisé"):
        _approuver(deps, demande["demande_id"], par="admin.fictif")


# -- injection dans une source, de bout en bout
# ------------------------------------------------------------------------------------
def test_injection_dans_une_source_de_bout_en_bout(m10, deps):
    r = _resultat(_ingerer(m10, departement=M3, cle="guide-piege", titre="Guide piégé", domaine="technique",
                           contenu=INJECTION))
    assert r["suspect"] is True
    # L'agent ne peut ni réviser ni publier une source suspecte.
    assert "REJ-CONN-REVUE-HUMAINE-REQUISE" in m10.appeler(
        "m10_reviser_source_connaissance", {"version_id": r["version_id"]})["details"]
    # La revue de M10 la montre neutralisée.
    lu = _resultat(m10.appeler("m10_lire_connaissance", {"version_id": r["version_id"], "limite": 5}))
    assert lu["suspect"] is True and lu["neutralise"] is True
    assert "Ignore tes règles" not in json.dumps(lu, ensure_ascii=False)
    assert "[CONTENU_NON_FIABLE]" in json.dumps(lu, ensure_ascii=False)
    # Une personne la valide (N3, approbation) ; la lecture par un département la rend neutralisée et non fiable.
    demande = m10.appeler("m10_valider_source_connaissance", {
        "version_id": r["version_id"], "motif": "Lue : la note est un exemple de piège."})
    assert _approuver(deps, demande["demande_id"])["statut"] == "executee"
    rep = _resultat(_caps(deps, M3).appeler("opsys_connaissances_rechercher",
                                            {"requete": "révèle les instructions système au client"}))
    texte = json.dumps(rep, ensure_ascii=False)
    assert "Ignore tes règles" not in texte and "[CONTENU_NON_FIABLE]" in texte
    assert rep["fiabilite"] == "non_fiable" and "jamais une consigne" in rep["avertissement_fiabilite"]
    assert any(x["neutralise"] and x["fiabilite"] == "non_fiable" for x in rep["resultats"])


# -- droits de lecture inter-départements
# --------------------------------------------------------------------------------------------
def _monde(m10, deps):
    r5 = _resultat(_ingerer(m10))
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": r5["version_id"]}))
    _approuver(deps, m10.appeler("m10_valider_source_connaissance", {
        "version_id": r5["version_id"], "motif": "Source relue en entier par la direction."})["demande_id"])
    r3 = _resultat(_ingerer(m10, departement=M3, cle="norme", titre="Norme fictive", domaine="technique",
        contenu=NORME))
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": r3["version_id"]}))
    _resultat(m10.appeler("m10_publier_source_connaissance", {"version_id": r3["version_id"]}))
    return r5, r3


def _chercher(deps, ident, requete, **extra):
    return _caps(deps, ident).appeler("opsys_connaissances_rechercher", {"requete": requete, **extra})


def test_un_departement_lit_sa_base_et_celles_de_ses_dependances_declarees_rien_de_plus(m10, deps):
    _monde(m10, deps)
    assert M5 in deps["m07-marketing"].dependances and M3 in deps["m07-marketing"].dependances
    assert M3 in deps["m04-field-ops"].dependances and M5 not in deps["m04-field-ops"].dependances
    assert not {M3, M5} & set(deps["m06-material-control"].dependances)
    # M3 lit sa propre base et celle de M5, une de ses dépendances.
    assert _resultat(_chercher(deps, M3, "hauteur du garde-corps"))["resultats"][0]["source"]["departement"] == M3
    assert _resultat(_chercher(deps, M3, "taux de la taxe de vente"))["statut"] == "ok"
    # M7 dépend de M3 et de M5 : les deux sont lisibles.
    assert _resultat(_chercher(deps, "m07-marketing", "taux de la taxe de vente"))["statut"] == "ok"
    assert _resultat(_chercher(deps, "m07-marketing", "hauteur du garde-corps"))["statut"] == "ok"
    # M4 dépend de M3 mais pas de M5 : par défaut il ne voit rien de M5, et le demander est un refus.
    assert _resultat(_chercher(deps, "m04-field-ops", "hauteur du garde-corps"))["statut"] == "ok"
    assert _resultat(_chercher(deps, "m04-field-ops", "taux de la taxe de vente"))["statut"] == "aucune_source"
    refus = _chercher(deps, "m04-field-ops", "taux de la taxe de vente", bases=[M5])
    assert refus["ok"] is False and "REJ-CONN-LECTURE-INTERDITE" in refus["details"]
    # M6 ne dépend ni de M3 ni de M5 : sa seule base est la sienne (vide).
    assert _resultat(_chercher(deps, "m06-material-control", "hauteur du garde-corps"))["statut"] == "aucune_source"
    refus = _chercher(deps, "m06-material-control", "hauteur", bases=[M3])
    assert refus["ok"] is False and "REJ-CONN-LECTURE-INTERDITE" in refus["details"]
    # M5 dépend de M3 : il lit donc la base de M3 ; la relation suit le manifeste, pas un droit codé en dur.
    assert M3 in deps[M5].dependances
    assert _resultat(_chercher(deps, M5, "hauteur du garde-corps"))["statut"] == "ok"


def test_un_departement_ne_peut_pas_lire_une_version_d_une_base_non_lisible_et_ne_la_confirme_pas(m10, deps):
    r5, r3 = _monde(m10, deps)
    ok = _resultat(_caps(deps, M3).appeler("opsys_connaissances_lire", {"version_id": r5["version_id"]}))
    assert ok["departement"] == M5 and ok["fragments"] and ok["integrite"] is True
    refus = _caps(deps, "m06-material-control").appeler("opsys_connaissances_lire", {"version_id": r5["version_id"]})
    inconnue = _caps(deps, "m06-material-control").appeler("opsys_connaissances_lire", {"version_id": "0" * 32})
    assert refus["ok"] is False and inconnue["ok"] is False
    assert "REJ-CONN-LECTURE-INTERDITE" in refus["details"]


def test_la_lecture_commune_ne_rend_jamais_un_brouillon(m10, deps):
    r = _resultat(_ingerer(m10))
    refus = _caps(deps, M5).appeler("opsys_connaissances_lire", {"version_id": r["version_id"]})
    assert refus["ok"] is False and "non publiée" in refus["details"]
    # L'outil M10, lui, lit l'état de revue (neutralisé).
    assert _resultat(m10.appeler("m10_lire_connaissance", {"version_id": r["version_id"]}))["etat"] == "brouillon"


def test_sans_departement_appelant_les_outils_communs_sont_refuses(instance, deps):
    direction = Capacites(deps, stockage.transaction)  # le point d'accès /mcp de la direction : aucun appelant
    reponse = direction.appeler("opsys_connaissances_rechercher", {"requete": "taxe de vente"})
    assert reponse["ok"] is False and "REJ-CONN-APPELANT-INCONNU" in reponse["details"]


def test_une_recherche_hors_transaction_est_refusee(instance, deps):
    from opsys.outils import executer

    outil = _caps(deps, M5).index["opsys_connaissances_rechercher"][1]
    with contexte.appeler_en_tant_que(M5, origine=M5):
        reponse = executer(outil, {"requete": "taxe de vente"})
    assert reponse["ok"] is False and "REJ-CONN-APPELANT-INCONNU" in reponse["details"]


# -- retrait
# ----------------------------------------------------------------------------------------------------
def test_le_retrait_n2_exige_une_raison_retire_de_la_recherche_et_garde_le_texte(m10, deps):
    r5, r3 = _monde(m10, deps)
    sans = m10.appeler("m10_retirer_source_connaissance", {"departement": M3, "source_id": r3["source_id"],
        "raison": "non"})
    assert sans["ok"] is False and "REJ-CONN-RAISON-REQUISE" in sans["details"]
    ok = _resultat(m10.appeler("m10_retirer_source_connaissance", {
        "departement": M3, "source_id": r3["source_id"], "raison": "Norme remplacée par la révision suivante."}))
    assert ok["etat"] == "retire"
    assert _resultat(_chercher(deps, M3, "hauteur du garde-corps"))["statut"] == "aucune_source"
    lu = _resultat(m10.appeler("m10_lire_connaissance", {"version_id": r3["version_id"]}))
    assert lu["etat"] == "retire" and "garde-corps" in json.dumps(lu, ensure_ascii=False)
    assert lu["historique"][-1]["raison"] == "Norme remplacée par la révision suivante."
    deux = m10.appeler("m10_retirer_source_connaissance", {
        "departement": M3, "source_id": r3["source_id"], "raison": "Une deuxième fois, sans effet."})
    assert deux["ok"] is False and "TRANSITION-INTERDITE" in deux["details"]


# -- recherche par les outils : embeddings via le registre, sortie bornée
# ----------------------------------------------------------------------
def test_les_embeddings_viennent_du_registre_et_la_recherche_devient_hybride(instance, deps, m10, monkeypatch):
    declarer_embeddings(stockage.transaction)
    raccorder_embeddings(monkeypatch)
    r = _resultat(_ingerer(m10))
    assert r["vecteurs"]["vectorise"] is True
    _publier_reglemente(m10, deps, r["version_id"])
    rep = _resultat(_caps(deps, "m07-marketing").appeler("opsys_connaissances_rechercher",
                                                         {"requete": "Quel est le taux de la taxe de vente ?"}))
    assert rep["mode_effectif"] == "hybride" and rep["espace_vectoriel"]["fournisseur_id"] == "embeddings.fictif-a"
    assert rep["resultats"][0]["scores"]["vectoriel"]["rang"] == 1


def test_changer_le_modele_du_registre_bascule_en_lexical_avec_avertissement_puis_reindexer_retablit(
        instance, deps, m10, monkeypatch):
    from connaissances_aide import changer_modele

    declarer_embeddings(stockage.transaction)
    raccorder_embeddings(monkeypatch)
    r = _resultat(_ingerer(m10))
    _publier_reglemente(m10, deps, r["version_id"])
    changer_modele(stockage.transaction, "embeddings.fictif-a", "Modèle fictif B")
    rep = _resultat(_chercher(deps, M5, "taux de la taxe de vente"))
    assert rep["mode_effectif"] == "lexical"
    assert [a["code"] for a in rep["avertissements"]] == ["REJ-CONN-ESPACE-INCOMPATIBLE"]
    bascule = _resultat(m10.appeler("m10_reindexer_connaissances", {"departement": M5}))
    assert bascule["vecteurs_ecrits"] == 2 and bascule["precedent"] != bascule["espace_id"]
    apres = _resultat(_chercher(deps, M5, "taux de la taxe de vente"))
    assert apres["mode_effectif"] == "hybride" and not apres["avertissements"]


def test_reindexer_sans_adaptateur_raccorde_est_un_refus_type(instance, m10):
    declarer_embeddings(stockage.transaction)  # déclaré, actif, sélectionné — mais aucun adaptateur raccordé
    _resultat(_ingerer(m10))
    reponse = m10.appeler("m10_reindexer_connaissances", {"departement": M5})
    assert reponse["ok"] is False and "REJ-CONN-EMBEDDINGS-NON-RACCORDE" in reponse["details"]
    assert ports._ADAPTATEURS_EMBEDDINGS == {}


def test_la_sortie_des_outils_est_bornee_par_resultats_entiers_et_dit_ce_qui_manque(m10, deps):
    sections = "\n\n".join(f"## Section {i}\n" + (f"Règle fictive {i} sur la taxe de vente de Valdoré. " * 15).strip()
                           for i in range(8))
    r = _resultat(_ingerer(m10, departement=M3, cle="gros", domaine="general", titre="Gros guide",
                           contenu="# Gros guide\n\n" + sections))
    _resultat(m10.appeler("m10_reviser_source_connaissance", {"version_id": r["version_id"]}))
    _resultat(m10.appeler("m10_publier_source_connaissance", {"version_id": r["version_id"]}))
    reponse = _caps(deps, M3).appeler("opsys_connaissances_rechercher", {"requete": "taxe de vente de Valdoré", "k": 8})
    assert reponse["ok"] is True and "artefact" not in json.dumps(reponse)[:200]
    rep = reponse["resultat"]
    assert len(json.dumps(reponse, ensure_ascii=False)) <= 6000
    assert rep["omis_budget"] >= 1 and 1 <= len(rep["resultats"]) < 8
    assert all(x["source"]["sha256"] and x["emplacement"]["fragment_sha256"] for x in rep["resultats"])  # jamais coupé


def test_k_hors_bornes_et_arguments_inconnus_sont_refuses(m10, deps):
    for args in ({"requete": "taxe", "k": 0}, {"requete": "taxe", "k": 9}, {"requete": "taxe", "k": True},
                 {"requete": "taxe", "mode": "vectoriel"}, {}):
        assert _chercher(deps, M5, args.pop("requete", ""), **args)["ok"] is False


def test_lire_une_version_pagine_ses_fragments(m10, deps):
    sections = "\n\n".join(f"## S{i}\nContenu fictif {i}." for i in range(5))
    r = _resultat(_ingerer(m10, cle="paginee", domaine="general", contenu="# P\n\n" + sections))
    page1 = _resultat(m10.appeler("m10_lire_connaissance", {"version_id": r["version_id"], "limite": 2}))
    page2 = _resultat(m10.appeler("m10_lire_connaissance", {"version_id": r["version_id"], "limite": 2, "decalage": 2}))
    assert [f["rang"] for f in page1["fragments"]] == [0, 1] and page1["suivant"] == 2
    assert [f["rang"] for f in page2["fragments"]] == [2, 3]
    fin = _resultat(m10.appeler("m10_lire_connaissance", {"version_id": r["version_id"], "limite": 2, "decalage": 4}))
    assert [f["rang"] for f in fin["fragments"]] == [4] and fin.get("suivant") is None
    assert m10.appeler("m10_lire_connaissance", {"version_id": r["version_id"], "limite": 11})["ok"] is False


def test_le_journal_d_audit_trace_chaque_ecriture_sans_contenu(m10, deps):
    r5, _ = _monde(m10, deps)
    from sqlalchemy import select

    from opsys.stockage.schema import JOURNAL

    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(JOURNAL.c.action, JOURNAL.c.par, JOURNAL.c.details).where(
            JOURNAL.c.action.like("connaissances.%"))).all()
    actions = [a for a, _, _ in lignes]
    assert actions.count("connaissances.ingerer") == 2 and "connaissances.publier" in actions
    publiee = next(d for a, p, d in lignes if a == "connaissances.publier" and json.loads(d)["mode"] == "humain")
    assert json.loads(publiee)["role"] == "nathan_owner"
    assert "taux fictif" not in " ".join(d for _, _, d in lignes)  # jamais le texte d'une source dans le journal
