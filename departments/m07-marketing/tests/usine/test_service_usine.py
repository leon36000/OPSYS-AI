"""L'usine à contenu sur la base durable (PLAN T4.17) : proposer, lire, décider, exporter, retirer, « À voir ».

Ces tests passent par les VRAIS outils du VRAI manifeste, appelés comme en production (`executer_atomique`, une
transaction par appel), sur une base SQLite temporaire migrée. L'identité d'un appareil est posée comme le core la
pose (`contexte.appele_par_appareil`), les personnes sont créées par `opsys.identite`. Aucune donnée réelle.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest
from m7_marketing import outils
from m7_marketing.brand import profil_client
from m7_marketing.moderation.detection import Detection
from m7_marketing.moderation.image import Boite
from m7_marketing.social import postiz_adapter
from m7_marketing.usine import chantier, plateformes, registre, service
from sqlalchemy import delete, select, update

from opsys import approbations, contexte, evenements, identite, stockage
from opsys.approbations_appareil import LIMITE_RESUME_ATTENTE
from opsys.departements import PolitiqueApprobation, lire_manifeste
from opsys.outils import Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
HORODATAGE = "2026-09-29T10:00:00-04:00"
_RACINE_M7 = Path(__file__).resolve().parents[2]
_OUTILS = {o.nom: o for o in outils.outils()}
PREUVE_AVIS = {"consentement_demande_avis": True}
_VRAI_CHARGEUR = profil_client.charger_profil_client  # celui du dépôt, avant tout remplacement par un test


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def brand_configure(monkeypatch, profil):
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(profil), None))
    return profil


@pytest.fixture
def proprietaire(base_durable):
    """Nathan (propriétaire, appareil `admin`) et une gestionnaire `admin` qui n'est pas le propriétaire."""
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-de-test-1234", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "gestionnaire", "Gestionnaire fictive", "mot-de-passe-de-test-1234", ["admin"])
        identite.creer_personne(cnx, "etienne", "Étienne fictif", "mot-de-passe-de-test-1234", ["employee"])


def _appeler(nom, *, appareil=None, **arguments):
    """Un appel d'outil comme en production ; `appareil=("nathan", "admin")` pose l'identité du jeton."""
    if appareil is None:
        return executer_atomique(_OUTILS[nom], arguments)
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(*appareil)):
        return executer_atomique(_OUTILS[nom], arguments)


def _metier(reponse):
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _lire(nom):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def _semer_wct(charge):
    """Le WCT est « reçu » sans passer par le consommateur (donc sans contenu automatique)."""
    with stockage.transaction():
        stockage.maillons("m07-marketing", "wct_recus").append(dict(charge))
    return charge["wct_id"]


def _recevoir(charge):
    with stockage.transaction():
        return outils.consommateurs()["m4.travaux_termines"](dict(charge))


def _contenus(statut=None, wct_id=None):
    arguments = {"limite": 8}
    if statut:
        arguments["statut"] = statut
    if wct_id:
        arguments["wct_id"] = wct_id
    return _metier(_appeler("m7_lister_contenus_chantier", **arguments))["contenus"]


def _id(plateforme, wct_id="wct-usine-1"):
    (contenu,) = [c for c in _contenus(wct_id=wct_id) if c["plateforme"] == plateforme]
    return contenu["contenu_id"]


# =============================================================================================================
# Proposer
# =============================================================================================================
def test_wct_inconnu_ne_produit_rien(base_durable, brand_configure):
    resultat = _metier(_appeler("m7_proposer_contenus_chantier", wct_id="wct-jamais-recu"))
    assert resultat["statut"] == "wct_inconnu" and resultat["contenus"] == []
    assert "wct-jamais-recu" in resultat["motif"]
    assert _lire("contenus_chantier") == []


def test_cinq_contenus_proposes_jamais_publies_et_relancer_n_en_ajoute_pas(base_durable, brand_configure, charge):
    wct_id = _semer_wct(charge)
    resultat = _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id))
    assert resultat["statut"] == "propose" and resultat["motif"] is None
    assert [i["plateforme"] for i in resultat["contenus"]] == list(plateformes.CODES_PLATEFORMES)
    assert all(i["statut"] == "propose" and i["apercu"] for i in resultat["contenus"])
    enregistres = _lire("contenus_chantier")
    assert len(enregistres) == 5 and {p["approval_status"] for p in enregistres} == {"PROPOSE"}
    assert {p["origine"] for p in enregistres} == {"agent"}

    encore = _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id))
    assert encore["statut"] == "deja_propose" and len(_lire("contenus_chantier")) == 5


def test_l_outil_ne_prend_ni_consentement_ni_marque_ni_texte_hors_schema(base_durable):
    outil = _OUTILS["m7_proposer_contenus_chantier"]
    assert set(outil.parametres["properties"]) == {"wct_id", "textes"} and outil.parametres["required"] == ["wct_id"]
    reponse = executer_atomique(outil, {"wct_id": "x", "consentement_marketing": True})
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert set(outil.parametres["properties"]["textes"]["properties"]) == set(plateformes.CODES_PLATEFORMES)


def test_le_propose_par_est_la_personne_du_jeton_confirmee_jamais_un_argument(
    base_durable, brand_configure, proprietaire, charge,
):
    wct_id = _semer_wct(charge)
    _metier(_appeler("m7_proposer_contenus_chantier", appareil=("nathan", "admin"), wct_id=wct_id))
    assert {p["origine"] for p in _lire("contenus_chantier")} == {"appareil:nathan"}


@pytest.mark.parametrize(("textes", "motif"), [
    ("un texte", "textes : un objet"),
    ({"tiktok_live": "x"}, "plateforme inconnue"),
    ({"facebook": ""}, "textes.facebook"),
    ({"facebook": 3}, "textes.facebook"),
])
def test_textes_mal_formes_sont_un_refus_metier_et_n_ecrivent_rien(
    base_durable, brand_configure, charge, textes, motif,
):
    wct_id = _semer_wct(charge)
    reponse = executer_atomique(_OUTILS["m7_proposer_contenus_chantier"], {"wct_id": wct_id, "textes": textes})
    assert reponse["ok"] is False
    assert motif in reponse["details"] or reponse["erreur"] == "arguments_invalides"
    assert _lire("contenus_chantier") == []


def test_texte_du_modele_avec_un_prix_est_refuse_en_nommant_la_regle_et_les_autres_passent(
    base_durable, brand_configure, charge,
):
    wct_id = _semer_wct(charge)
    resultat = _metier(_appeler(
        "m7_proposer_contenus_chantier", wct_id=wct_id,
        textes={"facebook": "Gouttières installées à partir de 4 500 $ seulement, demandez votre soumission."},
    ))
    assert resultat["statut"] == "partiel"
    facebook = next(i for i in resultat["contenus"] if i["plateforme"] == "facebook")
    assert facebook["statut"] == "refuse" and [r["regle"] for r in facebook["regles"]] == ["REJ-PRIX"]
    assert "4 500" in facebook["regles"][0]["detail"]
    assert {p["plateforme"] for p in _lire("contenus_chantier")} == {
        "instagram", "fiche_google", "video_courte", "demande_temoignage",
    }
    assert "4 500" not in json.dumps(_lire("contenus_chantier"), ensure_ascii=False)  # jamais écrit nulle part

    # Le texte corrigé complète le chantier : les quatre autres ne bougent pas.
    corrige = _metier(_appeler(
        "m7_proposer_contenus_chantier", wct_id=wct_id,
        textes={"facebook": "Un chantier de gouttières terminé avec soin. Demandez votre soumission."},
    ))
    assert corrige["statut"] == "propose"
    assert [i["statut"] for i in corrige["contenus"]] == ["propose", "deja_propose", "deja_propose", "deja_propose",
                                                          "deja_propose"]
    assert len(_lire("contenus_chantier")) == 5


@pytest.mark.parametrize(("texte", "regle"), [
    ("Terminé demain, on vous appelle.", "REJ-PROMESSE-DE-DATE"),
    ("Merci à Mme Tremblay pour sa confiance.", "REJ-NOM-CLIENT"),
    ("Un chantier fini au 1234 rue des Érables.", "REJ-ADRESSE"),
    ("Un travail garanti pour toujours.", "REJ-GARANTIE-NON-VALIDEE"),
    ("Le meilleur toit de Repentigny.", "REJ-EXAGERATION"),
    ("Voir https://exemple-fictif.ca/prix", "REJ-LIEN"),
    ("Dossier wct-usine-1 : terminé.", "REJ-IDENTIFIANT-INTERNE"),
    pytest.param("x" * 2001, "REJ-LONGUEUR", id="trop-long"),
])
def test_chaque_regle_du_controle_refuse_un_texte_du_modele(base_durable, brand_configure, charge, texte, regle):
    wct_id = _semer_wct(charge)
    resultat = _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id, textes={"instagram": texte}))
    instagram = next(i for i in resultat["contenus"] if i["plateforme"] == "instagram")
    assert instagram["statut"] == "refuse" and regle in {r["regle"] for r in instagram["regles"]}
    assert "instagram" not in {p["plateforme"] for p in _lire("contenus_chantier")}


def test_les_identifiants_du_wct_ne_paraissent_jamais_dans_un_texte_meme_venu_du_modele(
    base_durable, brand_configure, fabriquer_charge,
):
    wct_id = _semer_wct(fabriquer_charge(technicien_id="technicien-fictif-42"))
    resultat = _metier(_appeler(
        "m7_proposer_contenus_chantier", wct_id=wct_id,
        textes={"video_courte": "Chantier de gouttières réalisé par technicien-fictif-42."},
    ))
    video = next(i for i in resultat["contenus"] if i["plateforme"] == "video_courte")
    assert video["statut"] == "refuse"
    assert "REJ-IDENTIFIANT-INTERNE" in {r["regle"] for r in video["regles"]}


# ---- refus de départ : rien n'est écrit -------------------------------------------------------------------------
@pytest.mark.parametrize(("surcharges", "statut", "extrait"), [
    ({"consentement_marketing": False}, "refuse", "consentement_marketing = false"),
    ({"client_satisfait": False}, "refuse", "insatisfait"),
    ({"type_travaux": None}, "nature_inconnue", "nature des travaux absente"),
])
def test_refus_de_depart_n_ecrit_rien(base_durable, brand_configure, fabriquer_charge, surcharges, statut, extrait):
    charge = fabriquer_charge(**surcharges)
    if charge.get("type_travaux") is None:
        del charge["type_travaux"]
    wct_id = _semer_wct(charge)
    resultat = _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id))
    assert resultat["statut"] == statut and extrait in resultat["motif"] and resultat["contenus"] == []
    assert _lire("contenus_chantier") == []


def test_sans_consentement_du_tout_rien(base_durable, brand_configure, charge):
    del charge["consentement_marketing"]
    wct_id = _semer_wct(charge)
    resultat = _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id))
    assert resultat["statut"] == "refuse" and "absent" in resultat["motif"]
    assert _lire("contenus_chantier") == []


def test_profil_de_marque_non_configure_refuse_sans_rien_ecrire(base_durable, charge):
    """Le VRAI chargeur fail-closed contre le VRAI `profile.yaml` du dépôt : encore le gabarit non configuré."""
    wct_id = _semer_wct(charge)
    resultat = _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id))
    assert resultat["statut"] == "profil_marque_non_configure" and "GATE" in resultat["motif"]
    assert _lire("contenus_chantier") == []


def test_le_service_du_lead_v2_vient_de_la_taxonomie_de_l_entreprise(
    base_durable, brand_configure, fabriquer_charge, tmp_path,
):
    charge = fabriquer_charge(wct_id="wct-v2", service="gouttieres")
    del charge["type_travaux"]
    wct_id = _semer_wct(charge)
    sans_profil = _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id))
    assert sans_profil["statut"] == "nature_inconnue" and "REJ-SERVICE-NON-CONFIGURE" in sans_profil["motif"]
    assert "entreprise.yaml" not in sans_profil["motif"]  # le chemin du serveur n'entre pas dans un motif
    (tmp_path / "opsys-home").mkdir(exist_ok=True)
    (tmp_path / "opsys-home" / "entreprise.yaml").write_text("services: [gouttieres]\n", encoding="utf-8")
    avec_profil = _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id))
    assert avec_profil["statut"] == "propose"
    facebook = next(c for c in _contenus(wct_id="wct-v2") if c["plateforme"] == "facebook")
    assert "gouttières et descentes" in facebook["texte"] and "gouttieres" not in facebook["texte"]
    assert "#gouttiere" in facebook["mots_clics"] and "#descentepluviale" in facebook["mots_clics"]


def test_un_wct_avec_service_et_type_travaux_est_une_donnee_contradictoire(
    base_durable, brand_configure, fabriquer_charge,
):
    wct_id = _semer_wct(fabriquer_charge(service="gouttieres"))
    resultat = _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id))
    assert resultat["statut"] == "nature_inconnue" and "jamais les deux" in resultat["motif"]


# =============================================================================================================
# Le consommateur du bus : « Terminer » avec consentement donne cinq contenus, sans consentement rien
# =============================================================================================================
def test_le_consommateur_propose_les_cinq_contenus_et_garde_le_resume_de_la_demande_d_avis(
    base_durable, brand_configure, charge,
):
    resume = _recevoir(charge)
    assert resume["contenus"] == {"statut": "propose", "motif": None, "crees": 5, "deja_la": 0, "refuses": []}
    assert resume["brouillon_cree"] is False and resume["wct_id"] == "wct-usine-1"  # la demande d'avis : inchangée
    assert {p["origine"] for p in _lire("contenus_chantier")} == {"bus:m4.travaux_termines"}
    assert len(_lire("wct_recus")) == 1


def test_le_consommateur_rejoue_n_ajoute_rien(base_durable, brand_configure, charge):
    _recevoir(charge)
    avant = _lire("contenus_chantier")
    resume = _recevoir(charge)
    assert resume["contenus"]["crees"] == 0 and resume["contenus"]["deja_la"] == 5
    assert _lire("contenus_chantier") == avant and len(_lire("wct_recus")) == 1


def test_le_consommateur_sans_consentement_marketing_n_ecrit_aucun_contenu(base_durable, brand_configure, charge):
    for cle in ("consentement_marketing", "consentement_recueilli_par", "consentement_recueilli_le",
                "consentement_version_texte"):
        del charge[cle]
    resume = _recevoir(charge)
    assert resume["contenus"]["statut"] == "refuse" and resume["contenus"]["crees"] == 0
    assert _lire("contenus_chantier") == [] and len(_lire("wct_recus")) == 1  # le fait reçu reste enregistré


def test_le_consommateur_avec_profil_non_configure_ne_leve_rien_et_n_ecrit_rien(base_durable, charge):
    resume = _recevoir(charge)
    assert resume["contenus"]["statut"] == "profil_marque_non_configure" and resume["contenus"]["crees"] == 0
    assert _lire("contenus_chantier") == []
    # Le profil configuré ensuite, l'agent relance l'outil : les cinq contenus naissent.
    assert len(_lire("wct_recus")) == 1


def test_le_consommateur_ne_cree_pas_les_contenus_d_un_chantier_dont_le_consentement_etait_deja_retire(
    base_durable, brand_configure, charge,
):
    """Le retrait a précédé l'arrivée du WCT (le bus peut retarder) : le WCT est bloqué à sa réception."""
    _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id=charge["wct_id"], canal="courriel",
                     horodatage=HORODATAGE))
    resume = _recevoir(charge)
    assert resume["contenus"]["statut"] == "consentement_retire" and _lire("contenus_chantier") == []


# =============================================================================================================
# Lire la matière, lire la file
# =============================================================================================================
def test_la_matiere_dit_ce_qu_il_faut_pour_rediger_et_ce_qui_refusera(base_durable, brand_configure, charge):
    wct_id = _semer_wct(charge)
    matiere = _metier(_appeler("m7_lire_matiere_chantier", wct_id=wct_id))
    assert matiere["statut"] == "ok"
    assert matiere["matiere"]["marque"] == "Toitures Boréales Fictive Inc."
    assert matiere["matiere"]["nature"] == "gouttières" and matiere["matiere"]["ville"] == "Repentigny"
    assert matiere["matiere"]["note_du_chantier"] == "Installation terminée, sans imprévu."
    assert matiere["matiere"]["photos"] == 2 and matiere["matiere"]["ton"] == "professionnel, factuel"
    assert [p["code"] for p in matiere["plateformes"]] == list(plateformes.CODES_PLATEFORMES)
    assert {"REJ-PRIX", "REJ-ADRESSE", "REJ-NOM-CLIENT", "REJ-GARANTIE-NON-VALIDEE", "REJ-PROMESSE-DE-DATE"} <= set(
        matiere["regles"])


def test_la_note_du_chantier_avec_un_nom_ou_une_adresse_n_est_pas_montree(
    base_durable, brand_configure, fabriquer_charge,
):
    wct_id = _semer_wct(fabriquer_charge(description_factuelle="Chez Mme Tremblay, 12 rue des Lilas, tout est fini."))
    matiere = _metier(_appeler("m7_lire_matiere_chantier", wct_id=wct_id))
    assert matiere["matiere"]["note_du_chantier"] is None
    assert any("non utilisable" in a for a in matiere["avertissements"])
    assert "Tremblay" not in json.dumps(matiere, ensure_ascii=False)


@pytest.mark.parametrize(("surcharges", "statut"), [
    ({"consentement_marketing": False}, "refuse"), ({"client_satisfait": False}, "refuse"),
])
def test_la_matiere_a_les_memes_refus_que_la_proposition(
    base_durable, brand_configure, fabriquer_charge, surcharges, statut,
):
    wct_id = _semer_wct(fabriquer_charge(**surcharges))
    assert _metier(_appeler("m7_lire_matiere_chantier", wct_id=wct_id))["statut"] == statut


def test_la_matiere_d_un_wct_inconnu_ou_d_un_profil_non_configure_refuse(base_durable, charge):
    assert _metier(_appeler("m7_lire_matiere_chantier", wct_id="inconnu"))["statut"] == "wct_inconnu"
    wct_id = _semer_wct(charge)
    assert _metier(_appeler("m7_lire_matiere_chantier", wct_id=wct_id))["statut"] == "profil_marque_non_configure"


def test_lister_montre_le_texte_entier_le_statut_et_la_preuve_du_consentement(base_durable, brand_configure, charge):
    _recevoir(charge)
    lecture = _metier(_appeler("m7_lister_contenus_chantier", limite=8))
    assert (lecture["total"], lecture["reste"], lecture["suivant"], lecture["decalage"]) == (5, 0, None, 0)
    assert [c["plateforme"] for c in lecture["contenus"]] == list(reversed(plateformes.CODES_PLATEFORMES))
    facebook = next(c for c in lecture["contenus"] if c["plateforme"] == "facebook")
    assert facebook["approval_status"] == "PROPOSE" and facebook["exporte"] is False and facebook["decision"] is None
    assert facebook["texte"].startswith("Chantier terminé à Repentigny : gouttières.")
    assert facebook["consentement"] == {"recueilli_par": "etienne", "recueilli_le": "2026-09-28T18:05:00+00:00",
                                        "version_texte": "consentement-client-fr-CA-v1"}
    assert facebook["lien_utm"].startswith("https://exemple-fictif.ca/?utm_source=facebook")


def test_lister_par_pages_filtre_et_refuse_les_arguments_hors_bornes(
    base_durable, brand_configure, charge, fabriquer_charge,
):
    _recevoir(charge)
    _recevoir(fabriquer_charge(wct_id="wct-usine-2", lead_id="lead-usine-2"))
    page1 = _metier(_appeler("m7_lister_contenus_chantier", limite=4))
    assert page1["total"] == 10 and len(page1["contenus"]) == 4 and page1["suivant"] == 4 and page1["reste"] == 6
    page2 = _metier(_appeler("m7_lister_contenus_chantier", limite=4, decalage=page1["suivant"]))
    page3 = _metier(_appeler("m7_lister_contenus_chantier", limite=4, decalage=page2["suivant"]))
    vus = [c["contenu_id"] for page in (page1, page2, page3) for c in page["contenus"]]
    assert len(vus) == len(set(vus)) == 10 and page3["suivant"] is None and page3["reste"] == 0
    assert len(_contenus(wct_id="wct-usine-2")) == 5
    assert _contenus(statut="APPROVED") == []
    hors_plage = _metier(_appeler("m7_lister_contenus_chantier", decalage=99))
    assert hors_plage["contenus"] == [] and hors_plage["suivant"] is None and hors_plage["reste"] == 0
    for mauvais in ({"limite": 0}, {"limite": 9}, {"decalage": -1}, {"statut": "PUBLIE"}):
        reponse = _appeler("m7_lister_contenus_chantier", **mauvais)
        assert reponse["ok"] is False


def test_la_liste_reste_sous_la_limite_de_troncature_meme_avec_de_longs_textes(base_durable, brand_configure, charge):
    wct_id = _semer_wct(charge)
    long = "Un chantier de gouttières terminé avec soin par notre équipe. " * 18  # environ 1 100 caractères
    _metier(_appeler("m7_proposer_contenus_chantier", wct_id=wct_id,
                     textes={"facebook": long, "instagram": long, "fiche_google": long, "video_courte": long}))
    plein = _metier(_appeler("m7_lister_contenus_chantier", limite=8))
    assert len(json.dumps(plein, ensure_ascii=False)) < 6000  # `Capacites` tronquerait au-delà
    assert plein["suivant"] is not None and plein["reste"] > 0 and len(plein["contenus"]) >= 1
    lus = list(plein["contenus"])
    while plein["suivant"] is not None:
        plein = _metier(_appeler("m7_lister_contenus_chantier", limite=8, decalage=plein["suivant"]))
        assert len(json.dumps(plein, ensure_ascii=False)) < 6000
        lus.extend(plein["contenus"])
    assert len({c["contenu_id"] for c in lus}) == 5


# =============================================================================================================
# Décider : le propriétaire, jamais l'agent
# =============================================================================================================
def _contenu_propose(charge):
    _recevoir(charge)
    return _id("facebook", charge["wct_id"])


def test_un_agent_seul_ne_peut_pas_decider(base_durable, brand_configure, charge):
    contenu_id = _contenu_propose(charge)
    resultat = _metier(_appeler(
        "m7_decider_contenu", contenu_id=contenu_id, decision="approuver", horodatage=HORODATAGE,
    ))
    assert resultat["accepte"] is False and resultat["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _lire("decisions_contenu") == []


def test_le_proprietaire_approuve_depuis_son_appareil_avec_l_empreinte_du_texte(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    resultat = _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                                decision="approuver", horodatage=HORODATAGE))
    assert resultat["accepte"] is True
    accepte = resultat["resultat"]
    assert (accepte["approval_status"], accepte["par"], accepte["source"]) == ("APPROVED", "nathan", "appareil")
    assert "m7_exporter_paquet_manuel" in accepte["prochaine_etape"]
    (decision,) = _lire("decisions_contenu")
    assert decision["role"] == "nathan_owner" and decision["contenu_id"] == contenu_id
    facebook = next(c for c in _contenus() if c["contenu_id"] == contenu_id)
    assert facebook["approval_status"] == "APPROVED" and facebook["decision"]["par"] == "nathan"
    assert decision["empreinte_texte"] == next(p for p in _lire("contenus_chantier")
                                               if p["contenu_id"] == contenu_id)["empreinte_texte"]


def test_l_heure_du_serveur_fait_foi_pendant_un_appel_d_appareil(base_durable, brand_configure, proprietaire, charge):
    contenu_id = _contenu_propose(charge)
    recu_le = dt.datetime(2026, 9, 29, 15, 0, tzinfo=dt.UTC)
    reception = contexte.HorodatageAppareil("appareil-fictif", recu_le - dt.timedelta(hours=3), recu_le)
    with contexte.receptionne_de(reception):
        _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                         decision="approuver", horodatage="2020-01-01T00:00:00-04:00"))
    (decision,) = _lire("decisions_contenu")
    assert decision["horodatage"] == recu_le.isoformat()  # ni l'argument ni l'horloge du téléphone


@pytest.mark.parametrize(("appareil", "code"), [
    (("gestionnaire", "admin"), "REJ-HUMAIN-ROLE-INSUFFISANT"),  # admin, mais pas le propriétaire
    (("etienne", "employee"), "REJ-HUMAIN-ROLE-INSUFFISANT"),
    (("inconnu", "admin"), "REJ-HUMAIN-IDENTITE-INVALIDE"),
    (("nathan", "seller"), "REJ-HUMAIN-IDENTITE-INVALIDE"),  # nathan ne porte pas le rôle « seller »
])
def test_ni_le_gestionnaire_ni_l_employe_ni_une_identite_perimee_ne_decident(
    base_durable, brand_configure, proprietaire, charge, appareil, code,
):
    contenu_id = _contenu_propose(charge)
    resultat = _metier(_appeler("m7_decider_contenu", appareil=appareil, contenu_id=contenu_id, decision="approuver",
                                horodatage=HORODATAGE))
    assert resultat["accepte"] is False and resultat["verdict"]["code"] == code
    assert _lire("decisions_contenu") == []


def test_une_personne_desactivee_depuis_l_appairage_ne_decide_plus(base_durable, brand_configure, proprietaire, charge):
    contenu_id = _contenu_propose(charge)
    with stockage.transaction() as cnx:
        identite.activer(cnx, "nathan", False)
    resultat = _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                                decision="approuver", horodatage=HORODATAGE))
    assert resultat["verdict"]["code"] == "REJ-HUMAIN-IDENTITE-INVALIDE"


def test_le_rejet_dit_pourquoi_puis_un_nouveau_texte_cree_une_revision(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    sans_motif = _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                                  decision="rejeter", horodatage=HORODATAGE))
    assert sans_motif["verdict"]["code"] == "REJ-MOTIF-REQUIS" and _lire("decisions_contenu") == []
    rejet = _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                             decision="rejeter", horodatage=HORODATAGE, motif="trop vendeur pour notre voix de marque"))
    assert rejet["accepte"] is True and rejet["resultat"]["approval_status"] == "REJECTED"
    assert next(c for c in _contenus() if c["contenu_id"] == contenu_id)["approval_status"] == "REJECTED"

    sans_texte = _metier(_appeler("m7_proposer_contenus_chantier", wct_id="wct-usine-1"))
    assert next(i for i in sans_texte["contenus"] if i["plateforme"] == "facebook")["statut"] == "texte_requis"
    avec_texte = _metier(_appeler("m7_proposer_contenus_chantier", wct_id="wct-usine-1",
                                  textes={"facebook": "Un projet de gouttières terminé avec soin."}))
    assert avec_texte["statut"] == "propose"
    nouveau = next(c for c in _contenus() if c["plateforme"] == "facebook")
    assert nouveau["revision"] == 2 and nouveau["contenu_id"] != contenu_id and nouveau["approval_status"] == "PROPOSE"
    assert len(_lire("contenus_chantier")) == 6  # la révision 1 reste au registre, l'audit ne se réécrit pas

    perime = _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                              decision="approuver", horodatage=HORODATAGE))
    assert perime["verdict"]["code"] == "REJ-CONTENU-PERIME"  # rejetée puis remplacée : elle ne se rouvre pas


def test_on_ne_tranche_pas_deux_fois_ni_un_contenu_inconnu(base_durable, brand_configure, proprietaire, charge):
    contenu_id = _contenu_propose(charge)
    args = {"appareil": ("nathan", "admin"), "horodatage": HORODATAGE}
    assert _metier(_appeler("m7_decider_contenu", contenu_id=contenu_id, decision="approuver", **args))["accepte"]
    deuxieme = _metier(_appeler("m7_decider_contenu", contenu_id=contenu_id, decision="rejeter", motif="finalement non",
                                **args))
    assert deuxieme["verdict"]["code"] == "REJ-CONTENU-DEJA-TRANCHE" and len(_lire("decisions_contenu")) == 1
    inconnu = _metier(_appeler("m7_decider_contenu", contenu_id="n'existe-pas", decision="approuver", **args))
    assert inconnu["verdict"]["code"] == "REJ-CONTENU-INCONNU"


def test_une_revision_plus_recente_perime_la_precedente(base_durable, brand_configure, proprietaire, charge):
    """Cas défensif : deux révisions PROPOSE (l'outil n'en crée qu'après un rejet) — seule la dernière se décide."""
    contenu_id = _contenu_propose(charge)
    ancienne = next(p for p in _lire("contenus_chantier") if p["contenu_id"] == contenu_id)
    with stockage.transaction():
        stockage.maillons("m07-marketing", "contenus_chantier").append(
            {**ancienne, "contenu_id": "revision-2-fictive", "revision": 2})
    resultat = _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                                decision="approuver", horodatage=HORODATAGE))
    assert resultat["verdict"]["code"] == "REJ-CONTENU-PERIME"


def test_approuver_refuse_un_texte_qui_ne_passe_plus_le_controle(
    base_durable, brand_configure, proprietaire, charge, profil,
):
    """Défense en profondeur : le contrôle est rejoué à l'approbation. Une garantie validée au moment de la
    proposition puis retirée du profil ne s'approuve plus."""
    profil["tagline"] = "Garantie limitée de la main-d'œuvre"
    profil["garanties_validees"] = ["Garantie limitée de la main-d'œuvre"]
    contenu_id = _contenu_propose(charge)
    del profil["garanties_validees"]  # le client a retiré cet énoncé de son profil
    resultat = _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                                decision="approuver", horodatage=HORODATAGE))
    assert resultat["verdict"]["code"] == "REJ-TEXTE-NON-CONFORME"
    assert "REJ-GARANTIE-NON-VALIDEE" in resultat["verdict"]["detail"] and _lire("decisions_contenu") == []
    # Rejeter reste possible : on n'oblige jamais à approuver.
    rejet = _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                             decision="rejeter", horodatage=HORODATAGE, motif="la garantie n'est plus validée"))
    assert rejet["accepte"] is True


def test_approuver_sans_profil_de_marque_configure_refuse(
    base_durable, brand_configure, proprietaire, charge, monkeypatch,
):
    contenu_id = _contenu_propose(charge)
    monkeypatch.setattr(profil_client, "charger_profil_client", _VRAI_CHARGEUR)  # encore le gabarit non configuré
    resultat = _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                                decision="approuver", horodatage=HORODATAGE))
    assert resultat["verdict"]["code"] == "REJ-PROFIL-MARQUE-NON-CONFIGURE"


def _decider_par_la_file(arguments, personne="nathan", *, roles_n3=None):
    """Le chemin de l'agent en mode `ombre` : la demande attend, le propriétaire l'approuve dans la file du socle,
    qui exécute l'outil avec les arguments exacts enregistrés. `roles_n3` élargit la politique N3 du département
    (le manifeste ne déclare que `nathan_owner`) : la file accepte alors ces rôles."""
    index = dict(_OUTILS)
    departement = lire_manifeste(_RACINE_M7)
    if roles_n3 is not None:
        departement = dataclasses.replace(
            departement, politique_approbation=PolitiqueApprobation(roles={Niveau.N3: frozenset(roles_n3)}))
    departements = {"m07-marketing": departement}
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, "m07-marketing", "m7_decider_contenu", arguments, niveau=Niveau.N3)
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, ident, True, personne, index, departements)


def test_la_decision_passe_aussi_par_la_file_d_approbation_du_socle(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    sortie = _decider_par_la_file({"contenu_id": contenu_id, "decision": "approuver", "horodatage": HORODATAGE})
    assert sortie["statut"] == "executee" and sortie["reponse"]["resultat"]["accepte"] is True
    (decision,) = _lire("decisions_contenu")
    assert (decision["par"], decision["role"], decision["source"]) == ("nathan", "nathan_owner", "approbation")


def test_la_decision_par_la_file_porte_le_nom_de_la_personne_que_le_socle_dit_pas_un_nom_fixe(
    base_durable, brand_configure, proprietaire, charge,
):
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "adjointe.proprietaire", "Adjointe propriétaire fictive", "mot-de-passe-de-test-1234",
            ["nathan_owner"])
    contenu_id = _contenu_propose(charge)

    sortie = _decider_par_la_file(
        {"contenu_id": contenu_id, "decision": "approuver", "horodatage": HORODATAGE}, personne="adjointe.proprietaire")

    assert sortie["statut"] == "executee" and sortie["reponse"]["resultat"]["accepte"] is True
    (decision,) = _lire("decisions_contenu")
    assert (decision["par"], decision["role"], decision["source"]) == (
        "adjointe.proprietaire", "nathan_owner", "approbation")


def test_la_file_du_socle_refuse_d_approuver_par_un_autre_que_le_proprietaire(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    with pytest.raises(ValueError, match="aucun rôle autorisé pour N3"):
        _decider_par_la_file({"contenu_id": contenu_id, "decision": "approuver", "horodatage": HORODATAGE},
                             personne="gestionnaire")
    assert _lire("decisions_contenu") == []


def test_une_demande_approuvee_pour_un_contenu_ne_decide_que_ce_contenu_et_une_seule_fois(
    base_durable, brand_configure, proprietaire, charge,
):
    """Le socle ne dit qui a approuvé que PENDANT `decider` (T4.15-d) : un agent qui appelle l'outil ensuite, pour un
    AUTRE contenu ou pour une autre décision du même contenu, ne récupère pas cette approbation."""
    _recevoir(charge)
    facebook, instagram = _id("facebook"), _id("instagram")

    sortie = _decider_par_la_file({"contenu_id": facebook, "decision": "approuver", "horodatage": HORODATAGE})
    assert sortie["statut"] == "executee" and sortie["reponse"]["resultat"]["accepte"] is True
    with stockage.transaction():
        pris = service.decider_contenu(instagram, "approuver", HORODATAGE)
        autre_decision = service.decider_contenu(facebook, "rejeter", HORODATAGE, "non")

    assert pris["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert autre_decision["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert [d["contenu_id"] for d in _lire("decisions_contenu")] == [facebook]


def test_une_ligne_en_cours_ecrite_a_la_main_ne_donne_aucun_droit_meme_bien_formee(
    base_durable, brand_configure, proprietaire, charge,
):
    """Ce que M7 acceptait avant T4.15-d (une demande `en_cours` de cet outil, aux mêmes contenu, décision et heure,
    du propriétaire actif) ne vaut plus rien sans que `decider` soit en train d'exécuter."""
    _recevoir(charge)
    facebook = _id("facebook")
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(
            cnx, "m07-marketing", "m7_decider_contenu",
            {"contenu_id": facebook, "decision": "approuver", "horodatage": HORODATAGE}, niveau=Niveau.N3)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            statut="en_cours", decide_par="nathan", decide_role="nathan_owner"))
        forgee = service.decider_contenu(facebook, "approuver", HORODATAGE)

    assert forgee["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _lire("decisions_contenu") == []


def test_un_role_que_la_file_admet_mais_que_l_outil_ne_reconnait_pas_ne_decide_rien(
    base_durable, brand_configure, proprietaire, charge,
):
    """Le manifeste peut élargir la politique N3 de M7 : la file exécute alors la demande d'une gestionnaire `admin`,
    mais l'outil ne reconnaît que le propriétaire (`nathan_owner`) pour un contenu public."""
    contenu_id = _contenu_propose(charge)

    sortie = _decider_par_la_file(
        {"contenu_id": contenu_id, "decision": "approuver", "horodatage": HORODATAGE},
        personne="gestionnaire", roles_n3={"admin", "nathan_owner"})

    assert sortie["statut"] == "executee", sortie
    assert sortie["reponse"]["resultat"]["accepte"] is False
    assert sortie["reponse"]["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _lire("decisions_contenu") == []


# =============================================================================================================
# « À voir »
# =============================================================================================================
def test_les_contenus_proposes_apparaissent_dans_a_voir_avec_la_forme_commune(base_durable, brand_configure, charge):
    _recevoir(charge)
    with stockage.transaction():
        liste = outils.attentes()
    assert len(liste) == 5
    for attente in liste:
        assert set(attente) == set(approbations.CHAMPS_ATTENTE)
        assert (attente["type"], attente["niveau"], attente["depuis"]) == (
            "contenu_a_approuver", "N3", "2026-09-28T14:00:00-04:00")
        assert len(attente["resume"]) <= LIMITE_RESUME_ATTENTE
        assert "m7_decider_contenu" in attente["action_proposee"]
    assert {a["id"] for a in liste} == {c["contenu_id"] for c in _contenus()}


def test_le_socle_decouvre_les_attentes_de_m7_dans_sa_file_du_proprietaire(base_durable, brand_configure, charge):
    _recevoir(charge)
    departements = {"m07-marketing": lire_manifeste(_RACINE_M7)}
    with stockage.transaction() as cnx:
        attentes, illisibles = approbations.attentes_departements(cnx, departements)
        file_complete = approbations.file_proprietaire(cnx, departements)
    assert illisibles == [] and len(attentes) == 5 and len(file_complete) == 5
    assert {a["departement"] for a in attentes} == {"m07-marketing"}


def test_une_attente_disparait_quand_le_proprietaire_a_decide(base_durable, brand_configure, proprietaire, charge):
    contenu_id = _contenu_propose(charge)
    _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id, decision="approuver",
                     horodatage=HORODATAGE))
    with stockage.transaction():
        restantes = outils.attentes()
    assert len(restantes) == 4 and contenu_id not in {a["id"] for a in restantes}


def test_aucun_chantier_aucune_attente(base_durable):
    with stockage.transaction():
        assert outils.attentes() == []


# =============================================================================================================
# Exporter : le paquet manuel d'un contenu approuvé
# =============================================================================================================
def _approuver(contenu_id):
    return _metier(_appeler("m7_decider_contenu", appareil=("nathan", "admin"), contenu_id=contenu_id,
                            decision="approuver", horodatage=HORODATAGE))


def test_un_contenu_non_approuve_ne_s_exporte_pas(base_durable, brand_configure, proprietaire, charge):
    contenu_id = _contenu_propose(charge)
    resultat = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))
    assert resultat["accepte"] is False and resultat["verdict"]["code"] == "REJ-CONTENU-NON-APPROUVE"
    assert _lire("exports_paquet") == []
    inconnu = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id="n'existe-pas", horodatage=HORODATAGE))
    assert inconnu["verdict"]["code"] == "REJ-CONTENU-INCONNU"


def test_le_paquet_approuve_est_remis_avec_sa_trace_et_rien_n_est_publie(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    _approuver(contenu_id)
    paquet = _metier(_appeler("m7_exporter_paquet_manuel", appareil=("nathan", "admin"), contenu_id=contenu_id,
                              horodatage=HORODATAGE))
    assert paquet["accepte"] is True
    resultat = paquet["resultat"]
    assert resultat["plateforme"] == "facebook" and resultat["deja_exporte"] is False
    assert resultat["publication"].startswith("manuelle")
    assert resultat["approuve_par"] == "nathan" and resultat["heure_suggeree"]["heure_locale"] == "18:30"
    assert [m["statut"] for m in resultat["medias"]] == ["a_flouter_a_la_main", "a_flouter_a_la_main"]
    (export,) = _lire("exports_paquet")
    assert export["contenu_id"] == contenu_id and export["exporte_par"] == "nathan"
    assert next(c for c in _contenus() if c["contenu_id"] == contenu_id)["exporte"] is True

    # Un second export rend le même paquet sans second maillon.
    encore = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))["resultat"]
    assert encore["deja_exporte"] is True and encore["texte_a_copier"] == resultat["texte_a_copier"]
    assert len(_lire("exports_paquet")) == 1


def test_l_export_n_appelle_aucune_api_de_plateforme(base_durable, brand_configure, proprietaire, charge, monkeypatch):
    """M7 ne publie jamais : l'adaptateur Postiz n'est ni importé ni appelé par l'export."""
    def _interdit(*args, **kwargs):
        raise AssertionError("l'export ne doit jamais publier")

    monkeypatch.setattr(postiz_adapter.PostizAdapter, "publier", _interdit)
    contenu_id = _contenu_propose(charge)
    _approuver(contenu_id)
    assert _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))["accepte"]
    assert "postiz" not in Path(service.__file__).read_text(encoding="utf-8").casefold()


def test_le_paquet_d_un_texte_modifie_apres_l_approbation_est_refuse(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    _approuver(contenu_id)
    with stockage.transaction():
        decisions = stockage.maillons("m07-marketing", "decisions_contenu")
        original = decisions[0]
        # Un registre trafiqué : l'approbation porte une autre empreinte que le texte enregistré.
        stockage.connexion_courante().execute(update(REGISTRES).where(
            (REGISTRES.c.departement == "m07-marketing") & (REGISTRES.c.registre == "decisions_contenu")
        ).values(maillon=codec.encoder({**original, "empreinte_texte": "autre-texte"})))
    resultat = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))
    assert resultat["verdict"]["code"] == "REJ-CONTENU-MODIFIE-APRES-APPROBATION" and _lire("exports_paquet") == []


def test_l_export_rejoue_le_controle_du_texte(base_durable, brand_configure, proprietaire, charge, profil):
    profil["tagline"] = "Garantie limitée de la main-d'œuvre"
    profil["garanties_validees"] = ["Garantie limitée de la main-d'œuvre"]
    contenu_id = _contenu_propose(charge)
    _approuver(contenu_id)
    del profil["garanties_validees"]
    resultat = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))
    assert resultat["verdict"]["code"] == "REJ-TEXTE-NON-CONFORME" and _lire("exports_paquet") == []


def test_la_demande_de_temoignage_dit_si_le_client_peut_etre_contacte(
    base_durable, brand_configure, proprietaire, fabriquer_charge,
):
    _recevoir(fabriquer_charge(consentement_demande_avis=True))
    _recevoir(fabriquer_charge(wct_id="wct-usine-2", lead_id="lead-usine-2"))
    for wct_id, autorise in (("wct-usine-1", True), ("wct-usine-2", False)):
        contenu_id = _id("demande_temoignage", wct_id)
        _approuver(contenu_id)
        exporte = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))
        paquet = exporte["resultat"]
        assert paquet["public"] is False and paquet["contact_client"]["autorise"] is autorise
        assert paquet["medias"] == [] and paquet["lien_utm"] is None


# =============================================================================================================
# Mesure par contenu (PLAN T4.17-e) : la clé `utm_content` du paquet et le fait « contenu exporté » au bus
# =============================================================================================================
def _faits_contenu_exporte():
    """Les événements `m7.contenu_exporte` du bus, `(evenement_id, producteur, charge)`, dans l'ordre de publication."""
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m7.contenu_exporte"
        ).order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)).mappings().all()
    return [(ligne["evenement_id"], ligne["producteur"], codec.decoder(ligne["charge"])) for ligne in lignes]


def _exporter(contenu_id, *, appareil=("nathan", "admin")):
    return _metier(_appeler("m7_exporter_paquet_manuel", appareil=appareil, contenu_id=contenu_id,
                            horodatage=HORODATAGE))


def _alterer_proposition(contenu_id, **surcharges):
    """Réécrit UN maillon de proposition, comme un contenu proposé avant la convention ou un registre trafiqué."""
    with stockage.transaction() as cnx:
        maillons = list(stockage.maillons("m07-marketing", "contenus_chantier"))
        rang = next(i for i, m in enumerate(maillons) if m["contenu_id"] == contenu_id)
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == "m07-marketing") & (REGISTRES.c.registre == "contenus_chantier")
            & (REGISTRES.c.rang == rang)
        ).values(maillon=codec.encoder({**maillons[rang], **surcharges})))


def test_l_export_annonce_le_contenu_au_bus_une_seule_fois_avec_sa_cle_son_chantier_et_son_canal(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    _approuver(contenu_id)
    assert _faits_contenu_exporte() == []  # approuvé n'est pas exporté : rien n'est annoncé

    paquet = _exporter(contenu_id)["resultat"]
    (export,) = _lire("exports_paquet")
    evenement_id = f"m7-contenu-exporte-{contenu_id}"
    assert paquet["mesure"] == {"fait": "m7.contenu_exporte", "statut": "annonce"}
    assert _faits_contenu_exporte() == [(evenement_id, "m07-marketing", {
        "contenu_id": contenu_id, "wct_id": "wct-usine-1", "canal": "facebook", "utm_content": paquet["utm_content"],
        "lien_de_suivi": True, "exporte_le": export["horodatage"],
    })]
    # La clé annoncée est celle du paquet, de son lien de suivi et de la trace d'export.
    assert f"utm_content={paquet['utm_content']}" in paquet["lien_utm"]
    assert export["utm_content"] == paquet["utm_content"]

    # Un export rejoué rend le même paquet et n'annonce rien de plus.
    encore = _exporter(contenu_id)["resultat"]
    assert encore["deja_exporte"] is True and encore["mesure"]["statut"] == "deja_annonce"
    assert len(_faits_contenu_exporte()) == 1 and len(_lire("exports_paquet")) == 1


def test_le_fait_du_bus_n_emporte_aucun_renseignement_personnel(base_durable, brand_configure, proprietaire, charge):
    contenu_id = _contenu_propose(charge)
    _approuver(contenu_id)
    _exporter(contenu_id)
    ((_, _, fait),) = _faits_contenu_exporte()
    assert set(fait) == {"contenu_id", "wct_id", "canal", "utm_content", "lien_de_suivi", "exporte_le"}
    lu = json.dumps(fait, ensure_ascii=False)
    for interdit in ("lead-usine-1", "Repentigny", "int-usine-1", "etienne", "Toitures", "devis-usine-1", "photo-"):
        assert interdit not in lu, interdit


@pytest.mark.parametrize("plateforme", list(plateformes.CODES_PLATEFORMES))
def test_les_cinq_contenus_ont_chacun_leur_cle_et_leur_fait(
    base_durable, brand_configure, proprietaire, charge, plateforme,
):
    _recevoir(charge)
    contenu_id = _id(plateforme)
    _approuver(contenu_id)
    paquet = _exporter(contenu_id)["resultat"]
    ((_, _, fait),) = _faits_contenu_exporte()
    assert fait["canal"] == plateforme and fait["utm_content"] == paquet["utm_content"]
    assert fait["utm_content"].startswith(f"{plateforme}-")
    assert fait["lien_de_suivi"] is (plateforme != "demande_temoignage")
    assert (paquet["lien_utm"] is not None) is fait["lien_de_suivi"]


def test_deux_contenus_du_meme_chantier_annoncent_deux_faits_de_cles_differentes(
    base_durable, brand_configure, proprietaire, charge,
):
    _recevoir(charge)
    for plateforme in ("facebook", "instagram"):
        contenu_id = _id(plateforme)
        _approuver(contenu_id)
        _exporter(contenu_id)
    faits = [fait for _, _, fait in _faits_contenu_exporte()]
    assert {f["canal"] for f in faits} == {"facebook", "instagram"} and {f["wct_id"] for f in faits} == {"wct-usine-1"}
    assert len({f["utm_content"] for f in faits}) == 2 and len({f["contenu_id"] for f in faits}) == 2


def test_sans_site_dans_le_profil_le_contenu_s_exporte_sans_lien_et_le_fait_le_dit(
    base_durable, brand_configure, proprietaire, charge, profil,
):
    del profil["site_url"]
    contenu_id = _contenu_propose(charge)
    _approuver(contenu_id)
    paquet = _exporter(contenu_id)["resultat"]
    assert paquet["lien_utm"] is None and paquet["utm_content"].startswith("facebook-")
    ((_, _, fait),) = _faits_contenu_exporte()
    assert fait["lien_de_suivi"] is False and fait["utm_content"] == paquet["utm_content"]


def test_un_paquet_exporte_avant_le_fait_est_annonce_quand_on_le_reexporte(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    _approuver(contenu_id)
    premier = _exporter(contenu_id)["resultat"]
    with stockage.transaction() as cnx:  # comme un export d'avant l'existence du fait : la trace est là, le fait non
        cnx.execute(delete(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m7.contenu_exporte"))
    assert _faits_contenu_exporte() == []

    rattrape = _exporter(contenu_id)["resultat"]
    assert rattrape["deja_exporte"] is True and rattrape["mesure"]["statut"] == "annonce"
    ((_, _, fait),) = _faits_contenu_exporte()
    (export,) = _lire("exports_paquet")
    assert fait["utm_content"] == premier["utm_content"] and fait["exporte_le"] == export["horodatage"]
    assert len(_lire("exports_paquet")) == 1  # la trace n'a pas été réécrite


def test_un_lien_d_avant_la_convention_bloque_l_export_sans_rien_ecrire_ni_annoncer(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    propose = next(p for p in _lire("contenus_chantier") if p["contenu_id"] == contenu_id)
    ancienne = "facebook-3f2a9c1d"  # l'ancienne clé : 8 chiffres de l'empreinte du chantier
    _alterer_proposition(
        contenu_id, utm={**propose["utm"], "content": ancienne}, utm_content=None,
        lien_utm=propose["lien_utm"].replace(propose["utm_content"], ancienne),
    )
    _approuver(contenu_id)
    resultat = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))
    assert resultat["accepte"] is False and resultat["verdict"]["code"] == "REJ-UTM-CONTENT-INCOHERENT"
    assert "nouveau texte" in resultat["verdict"]["detail"]
    assert _lire("exports_paquet") == [] and _faits_contenu_exporte() == []


def test_un_contenu_sans_lien_n_a_rien_a_contredire_mais_un_lien_sans_la_cle_est_refuse(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    propose = next(p for p in _lire("contenus_chantier") if p["contenu_id"] == contenu_id)
    _alterer_proposition(contenu_id, lien_utm=propose["lien_utm"].split("&utm_content=")[0])
    _approuver(contenu_id)
    resultat = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))
    assert resultat["accepte"] is False and resultat["verdict"]["code"] == "REJ-UTM-CONTENT-INCOHERENT"
    assert "ne porte pas utm_content" in resultat["verdict"]["detail"] and _faits_contenu_exporte() == []


def test_une_proposition_d_avant_la_convention_sans_cle_ecrite_mais_au_lien_conforme_s_exporte(
    base_durable, brand_configure, proprietaire, charge,
):
    """Le champ `utm_content` du maillon est nouveau : son absence ne bloque pas ; la clé est recalculée."""
    contenu_id = _contenu_propose(charge)
    propose = next(p for p in _lire("contenus_chantier") if p["contenu_id"] == contenu_id)
    _alterer_proposition(contenu_id, utm_content=None)
    _approuver(contenu_id)
    paquet = _exporter(contenu_id)["resultat"]
    assert paquet["utm_content"] == propose["utm_content"]
    assert [f["utm_content"] for _, _, f in _faits_contenu_exporte()] == [propose["utm_content"]]


def test_un_contenu_non_approuve_ou_au_consentement_retire_n_annonce_rien(
    base_durable, brand_configure, proprietaire, charge,
):
    contenu_id = _contenu_propose(charge)
    non_approuve = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))
    assert non_approuve["accepte"] is False and _faits_contenu_exporte() == []
    _approuver(contenu_id)
    _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id="wct-usine-1", canal="courriel",
                     horodatage=HORODATAGE))
    resultat = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))
    assert resultat["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE" and _faits_contenu_exporte() == []


def test_l_export_est_atomique_un_fait_refuse_par_le_catalogue_annule_aussi_la_trace(
    base_durable, brand_configure, proprietaire, charge, monkeypatch,
):
    """Si l'annonce échoue, la trace de l'export n'est pas écrite : jamais un paquet que M8 ne connaîtrait pas."""
    contenu_id = _contenu_propose(charge)
    _approuver(contenu_id)
    monkeypatch.setattr(service.mesure, "charge_contenu_exporte", lambda *a, **k: {"contenu_id": "seul"})
    reponse = _appeler("m7_exporter_paquet_manuel", appareil=("nathan", "admin"), contenu_id=contenu_id,
                       horodatage=HORODATAGE)
    assert reponse["ok"] is False
    assert _lire("exports_paquet") == [] and _faits_contenu_exporte() == []


def test_le_manifeste_declare_le_type_publie_et_le_catalogue_le_connait(base_durable):
    manifeste = lire_manifeste(_RACINE_M7)
    assert manifeste.evenements_publie == ("m7.contenu_exporte",)
    assert "m7.contenu_exporte" in evenements.types_connus()


# =============================================================================================================
# Retrait du consentement marketing (Loi 25)
# =============================================================================================================
def test_un_retrait_bloque_toute_tache_de_contenu_y_compris_un_paquet_deja_propose_ou_exporte(
    base_durable, brand_configure, proprietaire, charge,
):
    _recevoir(charge)
    facebook, instagram = _id("facebook"), _id("instagram")
    _approuver(facebook)
    _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=facebook, horodatage=HORODATAGE))
    args = {"appareil": ("nathan", "admin"), "horodatage": HORODATAGE}
    with stockage.transaction():
        avant = len(outils.attentes())
    assert avant == 4

    retrait = _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id="wct-usine-1", canal="telephone",
                               **args))["resultat"]
    assert retrait["wct_connu"] is True and retrait["deja_enregistre"] is False
    assert len(retrait["contenus_bloques"]) == 5 and retrait["contenus_deja_exportes"] == [facebook]
    assert any("retirer à la main" in etape for etape in retrait["a_faire"])
    (maillon,) = _lire("retraits_consentement_marketing")
    assert (maillon["enregistre_par"], maillon["source"], maillon["canal"], maillon["lead_id"]) == (
        "nathan", "appareil", "telephone", "lead-usine-1")

    # Tout est bloqué : la liste, « À voir », la décision, l'export, la proposition, la matière, l'outil de photo.
    assert {c["approval_status"] for c in _contenus(wct_id="wct-usine-1")} == {"CONSENTEMENT_RETIRE"}
    with stockage.transaction():
        assert outils.attentes() == []
    decision = _metier(_appeler("m7_decider_contenu", contenu_id=instagram, decision="approuver", **args))
    assert decision["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE" and len(_lire("decisions_contenu")) == 1
    rejet = _metier(_appeler(
        "m7_decider_contenu", contenu_id=instagram, decision="rejeter", motif="peu importe", **args,
    ))
    assert rejet["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"
    export = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=facebook, horodatage=HORODATAGE))
    assert export["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"  # même approuvé, même déjà exporté une fois
    reproposition = _metier(_appeler("m7_proposer_contenus_chantier", wct_id="wct-usine-1"))
    assert reproposition["statut"] == "consentement_retire" and len(_lire("contenus_chantier")) == 5
    assert _metier(_appeler("m7_lire_matiere_chantier", wct_id="wct-usine-1"))["statut"] == "consentement_retire"
    assert _contenus(statut="CONSENTEMENT_RETIRE", wct_id="wct-usine-1") and _contenus(statut="PROPOSE") == []


def test_le_retrait_est_idempotent_et_ne_se_leve_pas(base_durable, brand_configure, charge):
    _recevoir(charge)
    premier = _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id="wct-usine-1", canal="sms",
                               horodatage=HORODATAGE))["resultat"]
    second = _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id="wct-usine-1", canal="courriel",
                              horodatage="2026-10-01T09:00:00-04:00"))["resultat"]
    assert premier["retrait_id"] == second["retrait_id"] and second["deja_enregistre"] is True
    (maillon,) = _lire("retraits_consentement_marketing")
    # Le premier retrait fait foi : canal, source et personne ne changent au second appel.
    assert (maillon["canal"], maillon["source"], maillon["enregistre_par"]) == ("sms", "agent", "agent")
    noms = {o.nom for o in outils.outils()}
    assert not any("annuler_retrait" in nom or "lever_retrait" in nom for nom in noms)  # aucun outil ne le défait


def test_un_retrait_sans_texte_libre_avec_un_canal_inconnu_est_refuse(base_durable):
    reponse = _appeler(
        "m7_enregistrer_retrait_consentement_marketing", wct_id="w", canal="pigeon", horodatage=HORODATAGE,
    )
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    schema = _OUTILS["m7_enregistrer_retrait_consentement_marketing"].parametres
    assert set(schema["properties"]) == {"wct_id", "canal", "horodatage"}
    refus = _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id="  ", canal="sms",
                             horodatage=HORODATAGE))
    assert refus["verdict"]["code"] == "REJ-RETRAIT-INVALIDE"
    refus = _metier(_appeler(
        "m7_enregistrer_retrait_consentement_marketing", wct_id="w", canal="sms", horodatage="tôt",
    ))
    assert refus["verdict"]["code"] == "REJ-HORODATAGE-INVALIDE"
    assert _lire("retraits_consentement_marketing") == []


def test_un_retrait_pour_un_wct_encore_inconnu_est_enregistre_et_le_dit(base_durable, brand_configure, charge):
    resultat = _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id="wct-usine-1", canal="sms",
                                horodatage=HORODATAGE))["resultat"]
    assert resultat["wct_connu"] is False and resultat["lead_id"] is None and resultat["contenus_bloques"] == []
    assert any("wct_id inconnu" in etape for etape in resultat["a_faire"])
    assert _recevoir(charge)["contenus"]["statut"] == "consentement_retire"  # le WCT est bloqué à son arrivée


def test_le_retrait_d_un_chantier_bloque_les_autres_chantiers_du_meme_lead(
    base_durable, brand_configure, fabriquer_charge,
):
    _recevoir(fabriquer_charge())
    _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id="wct-usine-1", canal="sms",
                     horodatage=HORODATAGE))
    suivant = _recevoir(fabriquer_charge(wct_id="wct-usine-1-bis", horodatage_completion="2026-10-05T14:00:00-04:00"))
    assert suivant["contenus"]["statut"] == "consentement_retire"
    autre_client = _recevoir(fabriquer_charge(wct_id="wct-usine-3", lead_id="lead-usine-3"))
    assert autre_client["contenus"]["crees"] == 5  # un autre client n'est pas touché


def test_le_retrait_de_marketing_ne_touche_pas_la_demande_d_avis_un_autre_consentement(
    base_durable, brand_configure, fabriquer_charge,
):
    _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id="wct-usine-1", canal="sms",
                     horodatage=HORODATAGE))
    resume = _recevoir(fabriquer_charge(**PREUVE_AVIS))
    assert resume["brouillon_cree"] is True  # la demande d'avis naît de consentement_demande_avis, distinct
    assert resume["contenus"]["statut"] == "consentement_retire"


def test_le_retrait_bloque_aussi_l_outil_de_photo_meme_avec_un_brouillon_deja_depose(
    base_durable, brand_configure, charge, monkeypatch,
):
    class _Detecteur:
        def detecter(self, image):
            return [Detection(type="visage", boite=Boite(0, 0, 1, 1), confiance=0.95)]

    monkeypatch.setattr(outils.moderation_detection, "detecteur_opencv_par_defaut", lambda: _Detecteur())
    wct_id = _semer_wct(charge)
    photo = {"reference": "photo-apres-1", "image": {"largeur": 2, "hauteur": 2, "pixels": [[255, 0, 0]] * 4}}
    assert _metier(_appeler("m7_preparer_contenu_public", wct_id=wct_id, photos=[photo], seuil_confiance=0.8))[
        "statut"] == "propose"
    _metier(_appeler("m7_enregistrer_retrait_consentement_marketing", wct_id=wct_id, canal="courriel",
                     horodatage=HORODATAGE))
    bloque = _metier(_appeler("m7_preparer_contenu_public", wct_id=wct_id, photos=[photo], seuil_confiance=0.8))
    assert bloque["statut"] == "consentement_retire" and bloque["brouillon"] is None  # ni neuf ni « deja_prepare »


# =============================================================================================================
# Le paquet et le contenu public de T4.3 se parlent : le rapport du détecteur est joint, jamais une garantie
# =============================================================================================================
def test_le_rapport_de_floutage_de_t4_3_est_joint_au_paquet_sans_jamais_dire_flouté(
    base_durable, brand_configure, proprietaire, charge, monkeypatch,
):
    class _Detecteur:
        def detecter(self, image):
            return [Detection(type="visage", boite=Boite(0, 0, 1, 1), confiance=0.95)]

    monkeypatch.setattr(outils.moderation_detection, "detecteur_opencv_par_defaut", lambda: _Detecteur())
    contenu_id = _contenu_propose(charge)
    photo = {"reference": "photo-apres-1", "image": {"largeur": 2, "hauteur": 2, "pixels": [[255, 0, 0]] * 4}}
    _metier(_appeler("m7_preparer_contenu_public", wct_id=charge["wct_id"], photos=[photo], seuil_confiance=0.8))
    _approuver(contenu_id)
    paquet = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=contenu_id, horodatage=HORODATAGE))["resultat"]
    premier, second = paquet["medias"]
    assert premier["reference"] == "photo-apres-1" and premier["statut"] == "a_flouter_a_la_main"
    assert premier["rapport_detecteur"]["zones_floutees"] == 1
    assert second["rapport_detecteur"] is None  # la seconde photo n'a jamais été traitée
    assert registre.STATUT_APPROUVE == "APPROVED" and chantier.STATUT_PROPOSE == "propose"
