"""Outils M3.2 (contexte de site), M3.3/M3.5 (vision) et M3.7 (géospatial) sur le VRAI socle : base SQLite migrée, bus
d'événements, file d'approbation, registre de fournisseurs. Aucun modèle de vision, aucune donnée réelle (fictives).

Ce que ces tests prouvent : le câblage durable, l'idempotence, la gouvernance de bout en bout (un candidat n'est
jamais une mesure), les événements publiés (et validés par leur JSON Schema), et que RIEN n'est branché en production.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import _commun_vision as cv  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402
from m3_estimation import outils_site_vision, verdicts, vision_doubles  # noqa: E402

from opsys import approbations, contexte, identite, stockage  # noqa: E402
from opsys import meteo as meteo_entreprise  # noqa: E402
from opsys.capacites import Capacites, outils_executables  # noqa: E402
from opsys.departements import lire_manifeste  # noqa: E402
from opsys.evenements import schemas  # noqa: E402
from opsys.fournisseurs import registre as registre_fournisseurs  # noqa: E402
from opsys.outils import Autonomie, Niveau, executer_atomique  # noqa: E402
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS  # noqa: E402

FICTIF = True
DEP = "m03-estimation"
LE = "2026-10-02T10:00:00-04:00"
_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
POLITIQUE = {
    "seuil_confiance": "0.80",
    "tolerance_absolue": "0.05",
    "tolerance_relative": "0.10",
    "declaree_par": "proprio",
    "declaree_le": LE,
}
NOUVEAUX = {
    "m3_construire_contexte_site",
    "m3_lire_contexte_site",
    "m3_executer_pipeline_vision",
    "m3_lire_candidats_vision",
    "m3_valider_candidat_par_reference",
    "m3_valider_candidat_par_humain",
    "m3_lister_modeles_vision",
    "m3_calculer_aire_polygone",
    "m3_agreger_donnees_geospatiales",
    "m3_lister_sources_geospatiales",
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m3-site.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture(autouse=True)
def _propre():
    outils_site_vision.debrancher_detecteurs()
    outils_site_vision.debrancher_ports_geospatiaux()
    yield
    outils_site_vision.debrancher_detecteurs()
    outils_site_vision.debrancher_ports_geospatiaux()


@pytest.fixture
def politique(monkeypatch):
    monkeypatch.setattr(outils_site_vision, "_politique_vision", lambda: dict(POLITIQUE))


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "proprio", "Propriétaire (fictif)", _MOT_DE_PASSE, ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "gestionnaire", "Gestionnaire (fictive)", _MOT_DE_PASSE, ["admin", "manager"])


def _outil(nom):
    return next(o for o in outils_m3.outils() if o.nom == nom)


def _appeler(nom, **arguments):
    """Réponse de l'outil : le dict de la fonction (accepte, resultat | verdict), avec le contenu de `resultat`
    aussi à plat."""
    reponse = executer_atomique(_outil(nom), arguments)
    assert reponse["ok"] is True, reponse
    interne = reponse["resultat"]
    if interne.get("accepte") is True and isinstance(interne.get("resultat"), dict):
        return {**interne["resultat"], "accepte": True, "resultat": interne["resultat"]}
    return interne


def _evenements(type_evenement):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
        ).all()
    return lignes


def _nb_maillons():
    with stockage.transaction():
        return len(stockage.maillons(DEP, "site_vision"))


# =========================================================================================== déclaration des outils
def test_les_dix_outils_sont_declares_sans_aucun_droit_d_appareil_avec_les_bons_niveaux():
    par_nom = {o.nom: o for o in outils_m3.outils()}
    assert set(par_nom) >= NOUVEAUX and len([o for o in outils_m3.outils() if o.nom in NOUVEAUX]) == 10
    for nom in NOUVEAUX:
        assert not par_nom[nom].roles_appareil, nom  # fermé aux appareils : aucun droit élargi
    for nom in (
        "m3_lire_contexte_site",
        "m3_lire_candidats_vision",
        "m3_lister_modeles_vision",
        "m3_calculer_aire_polygone",
        "m3_agreger_donnees_geospatiales",
        "m3_lister_sources_geospatiales",
    ):
        assert par_nom[nom].autonomie is Autonomie.T0 and par_nom[nom].niveau_effectif is Niveau.N0, nom
    for nom in ("m3_construire_contexte_site", "m3_executer_pipeline_vision", "m3_valider_candidat_par_reference"):
        assert par_nom[nom].autonomie is Autonomie.T1 and par_nom[nom].niveau_effectif is Niveau.N2, nom
    humain = par_nom["m3_valider_candidat_par_humain"]
    assert humain.autonomie is Autonomie.T1 and humain.niveau_effectif is Niveau.N3
    assert not any(o.autonomie is Autonomie.T3 for o in outils_m3.outils() if o.nom in NOUVEAUX)


def test_la_description_des_outils_ne_promet_aucun_modele_aucun_poids():
    assert "aucun modèle qualifié" in _outil("m3_executer_pipeline_vision").description.lower()
    assert "aucun modèle qualifié" in _outil("m3_lister_modeles_vision").description.lower()
    for nom in NOUVEAUX:
        assert "est qualifié" not in _outil(nom).description.lower(), nom


# =========================================================================================== M3.2 contexte
def _declare(valeur):
    return {"valeur": valeur, "declare_par": "estimateur.fictif", "declare_le": LE}


def test_le_contexte_se_construit_se_versionne_et_publie_une_fois_par_version(base_durable):
    r1 = _appeler("m3_construire_contexte_site", lead_id="lead-ctx-9", service="service_a", date_reference="2026-10-15")
    c1 = r1["contexte"]
    assert r1["nouvelle_version"] is True and c1["version"] == 1 and "meteo" in c1["inconnus"]
    assert _nb_maillons() == 1 and len(_evenements("m3.contexte_site_pret")) == 1

    # même contenu : aucune nouvelle version, aucun maillon, aucun événement
    r1b = _appeler(
        "m3_construire_contexte_site", lead_id="lead-ctx-9", service="service_a", date_reference="2026-10-15"
    )
    assert r1b["nouvelle_version"] is False and r1b["contexte"]["empreinte"] == c1["empreinte"]
    assert _nb_maillons() == 1 and len(_evenements("m3.contexte_site_pret")) == 1

    r2 = _appeler(
        "m3_construire_contexte_site",
        lead_id="lead-ctx-9",
        service="service_a",
        date_reference="2026-10-15",
        facteurs_declares={"pente": _declare({"pente_sur_12": 5})},
    )
    c2 = r2["contexte"]
    assert r2["nouvelle_version"] is True and c2["version"] == 2 and c2["precedent"] == c1["empreinte"]
    assert len(_evenements("m3.contexte_site_pret")) == 2

    relu = _appeler("m3_lire_contexte_site", lead_id="lead-ctx-9")
    assert (
        relu["contexte"]["version"] == 2
        and relu["versions"] == 2
        and relu["hypotheses"]["empreinte"] == c2["empreinte"]
    )
    ancien = _appeler("m3_lire_contexte_site", lead_id="lead-ctx-9", version=1)
    assert ancien["contexte"]["empreinte"] == c1["empreinte"]


def test_l_evenement_du_contexte_est_valide_par_son_schema_et_ne_porte_ni_adresse_ni_contact(base_durable):
    _appeler(
        "m3_construire_contexte_site",
        lead_id="lead-ctx-8",
        service="service_a",
        date_reference="2026-10-15",
        municipalite="Ville Fictive",
        facteurs_declares={"age": _declare({"annee_construction": 1985})},
    )
    [ligne] = _evenements("m3.contexte_site_pret")
    charge = json.loads(ligne.charge)
    assert schemas.erreurs_charge("m3.contexte_site_pret", charge) == []
    age = next(f for f in charge["facteurs"] if f["facteur"] == "age")
    assert age["statut"] == "connu" and age["valeur"] == {"annee_construction": 1985}
    assert "Ville Fictive" not in ligne.charge and ligne.producteur == DEP
    inconnu = next(f for f in charge["facteurs"] if f["facteur"] == "acces")
    assert inconnu["statut"] == "inconnu" and inconnu["valeur"] is None


def test_la_meteo_du_contexte_vient_des_regles_declarees_par_l_entreprise(base_durable):
    sans = _appeler(
        "m3_construire_contexte_site", lead_id="lead-meteo-1", service="service_a", date_reference="2026-10-15"
    )
    assert {f["facteur"]: f for f in sans["contexte"]["facteurs"]}["meteo"]["statut"] == "inconnu"

    meteo_entreprise.enregistrer_meteo(
        {
            "fuseau": "America/Toronto",
            "services": {
                "service_a": {
                    "seuils": {
                        "vent_kmh": {"validation": 30, "blocage": 45},
                        "pluie_mm_h": {"validation": 1, "blocage": 3},
                        "gel_c": {"validation": 2, "blocage": 0},
                    },
                    "sans_objet": ["verglas", "chaleur"],
                }
            },
        },
        par="proprio",
    )
    avec = _appeler(
        "m3_construire_contexte_site", lead_id="lead-meteo-1", service="service_a", date_reference="2026-10-15"
    )
    meteo = {f["facteur"]: f for f in avec["contexte"]["facteurs"]}["meteo"]
    assert meteo["statut"] == "connu" and meteo["valeur"]["a_decider"] == []
    assert sorted(meteo["valeur"]["risques_juges"]) == ["gel", "pluie", "vent"] and meteo["valeur"]["sans_objet"] == [
        "chaleur",
        "verglas",
    ]
    assert meteo["sources"][0]["type"] == "profil_meteo_entreprise" and meteo["sources"][0]["reference"]
    assert avec["contexte"]["version"] == 2  # la déclaration météo a changé le contenu : nouvelle version

    # un service que l'entreprise n'a pas jugé : inconnu, jamais « sans risque »
    autre = _appeler(
        "m3_construire_contexte_site", lead_id="lead-meteo-2", service="service_b", date_reference="2026-10-15"
    )
    assert {f["facteur"]: f for f in autre["contexte"]["facteurs"]}["meteo"]["statut"] == "inconnu"


def test_un_refus_du_contexte_n_ecrit_rien_ne_publie_rien(base_durable):
    reponse = _appeler(
        "m3_construire_contexte_site",
        lead_id="lead-x",
        service="service_a",
        date_reference="2026-10-15",
        facteurs_declares={"hauteur": {"valeur": {"etages": 2}}},
    )  # sans source
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-CONTEXTE-SOURCE-ABSENTE"
    assert _nb_maillons() == 0 and _evenements("m3.contexte_site_pret") == []
    reponse = _appeler("m3_lire_contexte_site", lead_id="lead-jamais-construit")
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-CONTEXTE-INTROUVABLE"


def test_un_journal_altere_bloque_toute_ecriture_et_toute_lecture(base_durable):
    _appeler("m3_construire_contexte_site", lead_id="lead-alt", service="service_a", date_reference="2026-10-15")
    _appeler(
        "m3_construire_contexte_site",
        lead_id="lead-alt",
        service="service_a",
        date_reference="2026-10-15",
        facteurs_declares={"pente": _declare({"pente_sur_12": 5})},
    )
    from opsys.stockage.schema import REGISTRES

    with stockage.transaction() as cnx:
        maillon = cnx.execute(
            select(REGISTRES.c.maillon, REGISTRES.c.rang).where(
                (REGISTRES.c.departement == DEP) & (REGISTRES.c.registre == "site_vision") & (REGISTRES.c.rang == 0)
            )
        ).one()
        cnx.execute(
            REGISTRES.update()
            .where((REGISTRES.c.departement == DEP) & (REGISTRES.c.registre == "site_vision") & (REGISTRES.c.rang == 0))
            .values(maillon=maillon.maillon.replace("lead-alt", "lead-xyz"))
        )
    for nom, args in (
        ("m3_lire_contexte_site", {"lead_id": "lead-alt"}),
        (
            "m3_construire_contexte_site",
            {"lead_id": "lead-alt", "service": "service_a", "date_reference": "2026-10-15"},
        ),
    ):
        reponse = _appeler(nom, **args)
        assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-SITE-JOURNAL-ALTERE", nom
    assert len(_evenements("m3.contexte_site_pret")) == 2  # rien de plus n'a été publié


# =========================================================================================== M3.3 / M3.5 vision
def _brancher(scripts=None):
    detecteur = vision_doubles.DetecteurScripte(scripts if scripts is not None else {"synth-1": [cv.detection()]})
    outils_site_vision.brancher_detecteur(detecteur)
    return detecteur


def _pipeline(photo=None, modele_id="vision.double-deterministe", lead_id="lead-vis-1"):
    return _appeler(
        "m3_executer_pipeline_vision",
        lead_id=lead_id,
        photo=photo or cv.photo(),
        objets=["objet_test"],
        modele_id=modele_id,
    )


def test_en_production_aucun_detecteur_n_est_branche_et_l_outil_le_dit_honnetement(base_durable):
    reponse = _pipeline()
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-VISION-MODELE-INCONNU"
    assert "aucun modèle qualifié" in reponse["verdict"]["detail"]
    assert _nb_maillons() == 0
    modeles = _appeler("m3_lister_modeles_vision")["resultat"]
    assert modeles["statut"] == "contrat_pret_aucun_modele_qualifie" and modeles["modeles_qualifies_actifs"] == []


def test_le_registre_liste_les_modeles_avec_leurs_drapeaux_de_licence_sans_aucun_poids(base_durable):
    modeles = _appeler("m3_lister_modeles_vision")["resultat"]["modeles"]
    par_id = {m["identifiant"]: m for m in modeles}
    assert {
        "vision.grounding-dino.local",
        "vision.sam2.local",
        "vision.florence-2.local",
        "vision.owlv2.local",
        "vision.ultralytics-yolo",
    } <= set(par_id)
    for m in modeles:
        assert m["qualification"] == "a_mesurer" and m["actif"] is False and m["poids_fournis_par_opsys"] is False
        assert m["licence"]["verification"] == "a_lire" and m["licence"]["source"].startswith("hors-recherche")
        assert "LICENCE_A_VERIFIER" in m["refus_de_licence"]
    assert "FOURNISSEUR_ECARTE" in par_id["vision.ultralytics-yolo"]["refus_de_licence"]
    assert "COPYLEFT_INTEGRE" in par_id["vision.ultralytics-yolo"]["refus_de_licence"]
    assert par_id["vision.sam2.local"]["statut_catalogue"] == "adopte"


def test_un_modele_de_vision_ne_s_active_pas_tant_que_sa_licence_n_a_pas_ete_lue(base_durable, personnes):
    with stockage.transaction() as cnx:
        registre_fournisseurs.configurer(cnx, acteur="proprio", identifiant="vision.sam2.local")
        registre_fournisseurs.declarer_profil(
            cnx,
            acteur="proprio",
            usage_commercial=True,
            revenu_annuel_usd=100000,
            territoires=["CA"],
            heberge_pour_tiers=False,
            revision_attendue=0,
        )
        decision = registre_fournisseurs.activer(cnx, acteur="proprio", identifiant="vision.sam2.local")
    assert decision.conforme is False and "LICENCE_A_VERIFIER" in decision.codes
    assert _appeler("m3_lister_modeles_vision")["resultat"]["statut"] == "contrat_pret_aucun_modele_qualifie"


def test_meme_une_licence_lue_et_un_modele_actif_ne_le_qualifient_pas_sans_mesure(base_durable, personnes):
    with stockage.transaction() as cnx:
        registre_fournisseurs.declarer_profil(
            cnx,
            acteur="proprio",
            usage_commercial=True,
            revenu_annuel_usd=100000,
            territoires=["CA"],
            heberge_pour_tiers=False,
            revision_attendue=0,
        )
        registre_fournisseurs.configurer(
            cnx, acteur="proprio", identifiant="vision.sam2.local", modifications={"licence_lue": True}
        )
        decision = registre_fournisseurs.activer(cnx, acteur="proprio", identifiant="vision.sam2.local")
    assert decision.conforme is True
    modeles = _appeler("m3_lister_modeles_vision")["resultat"]
    sam = next(m for m in modeles["modeles"] if m["identifiant"] == "vision.sam2.local")
    assert sam["actif"] is True and sam["qualification"] == "a_mesurer"
    assert modeles["statut"] == "contrat_pret_aucun_modele_qualifie"  # actif n'est pas qualifié


def test_le_pipeline_journalise_des_candidats_idempotemment_et_publie_rien(base_durable):
    _brancher()
    sortie = _pipeline()["resultat"]
    assert sortie["aucune_mesure_retenue"] is True and sortie["nouveaux_candidats_journalises"] == 1
    assert _nb_maillons() == 1
    assert _evenements("m3.mesure_vision_validee") == []  # un candidat n'est pas une mesure : rien n'est publié
    rejoue = _pipeline()["resultat"]
    assert rejoue["nouveaux_candidats_journalises"] == 0 and _nb_maillons() == 1  # double soumission : pas de doublon
    lus = _appeler("m3_lire_candidats_vision", photo_id="synth-1")["resultat"]
    [ligne] = lus["candidats"]
    assert ligne["statut"] == "candidate_non_validee" and ligne["decision"] is None and ligne["lead_id"] == "lead-vis-1"
    assert lus["politique_declaree"] is False and ligne["evaluation"] is None
    assert "seuil_confiance" in lus["politique_manque"]


def test_une_photo_reelle_est_refusee_par_le_pipeline_durable_politique_non_validee(base_durable):
    _brancher()
    reponse = _pipeline(photo=cv.photo(origine="client", fictif=False, consentement="cons-1"))
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-VISION-PROVENANCE-REFUSEE"
    assert _nb_maillons() == 0


def test_la_politique_photos_reelle_du_depot_est_encore_une_proposition():
    assert outils_site_vision._politique_photos_validee() is False


def test_le_modele_demande_doit_etre_branche_et_les_entrees_hostiles_sont_refusees(base_durable):
    _brancher()
    assert _pipeline(modele_id="vision.autre")["verdict"]["code"] == "REJ-VISION-MODELE-INCONNU"
    assert (
        _appeler(
            "m3_executer_pipeline_vision",
            lead_id="",
            photo=cv.photo(),
            objets=["objet_test"],
            modele_id="vision.double-deterministe",
        )["verdict"]["code"]
        == "REJ-VISION-PHOTO-INVALIDE"
    )
    hostile = vision_doubles.DetecteurHostile("objet_injecte")
    outils_site_vision.brancher_detecteur(hostile)
    sortie = _pipeline(modele_id="vision.double-hostile")["resultat"]
    assert sortie["candidats"] == [] and _nb_maillons() == 0
    outils_site_vision.brancher_detecteur(vision_doubles.DetecteurEnPanne())
    assert _pipeline(modele_id="vision.double-en-panne")["verdict"]["code"] == "REJ-VISION-DETECTEUR-INDISPONIBLE"


def _un_candidat(confiance="0.90", **detection):
    _brancher({"synth-1": [cv.detection(confiance=confiance, **detection)]})
    return _pipeline()["resultat"]["candidats"][0]


def _reference(valeur="0.52"):
    return {
        "reference_id": "mesure-manuelle-7",
        "source": "mesure_manuelle",
        "valeur": valeur,
        "unite": "m2",
        "mesure_par": "estimateur.fictif",
        "mesure_le": LE,
    }


def test_sans_politique_declaree_dans_le_manifeste_aucun_candidat_ne_se_valide(base_durable):
    c = _un_candidat()
    reponse = _appeler("m3_valider_candidat_par_reference", candidat_id=c["candidat_id"], reference=_reference())
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-VISION-POLITIQUE-ABSENTE"
    assert _nb_maillons() == 1  # le candidat seulement


def test_le_manifeste_livre_laisse_la_politique_vide_a_dessein():
    from m3_estimation.vision_gouvernance import lire_politique

    brute = outils_site_vision._politique_vision()
    assert brute == {
        "seuil_confiance": None,
        "tolerance_absolue": None,
        "tolerance_relative": None,
        "declaree_par": None,
        "declaree_le": None,
    }
    assert lire_politique(brute)[1]["code"] == "REJ-VISION-POLITIQUE-ABSENTE"


def test_validation_par_reference_publie_la_mesure_une_fois_et_la_decision_est_immuable(base_durable, politique):
    c = _un_candidat()
    r = _appeler("m3_valider_candidat_par_reference", candidat_id=c["candidat_id"], reference=_reference("0.52"))
    decision = r["resultat"]["decision"]
    assert r["accepte"] is True and decision["statut"] == "validee_par_reference" and r["resultat"]["rejoue"] is False
    [ligne] = _evenements("m3.mesure_vision_validee")
    charge = json.loads(ligne.charge)
    assert schemas.erreurs_charge("m3.mesure_vision_validee", charge) == []
    assert (charge["lead_id"], charge["valeur_retenue"], charge["voie"], charge["origine_valeur"]) == (
        "lead-vis-1",
        "0.5000",
        "reference",
        "vision_validee_par_reference",
    )
    assert charge["modele"] == {"identifiant": "vision.double-deterministe", "version": "1"}
    assert "masque" not in ligne.charge and "segments" not in ligne.charge  # aucune image ni masque dans l'événement

    # double soumission identique : no-op ; décision différente : conflit
    rejeu = _appeler("m3_valider_candidat_par_reference", candidat_id=c["candidat_id"], reference=_reference("0.52"))
    assert rejeu["resultat"]["rejoue"] is True and len(_evenements("m3.mesure_vision_validee")) == 1
    conflit = _appeler("m3_valider_candidat_par_reference", candidat_id=c["candidat_id"], reference=_reference("0.60"))
    assert conflit["accepte"] is False and conflit["verdict"]["code"] == "REJ-VISION-DECISION-CONFLIT"
    lus = _appeler("m3_lire_candidats_vision", candidat_id=c["candidat_id"])["resultat"]["candidats"][0]
    assert lus["statut"] == "validee_par_reference" and lus["decision"]["empreinte"] == decision["empreinte"]


def test_un_ecart_hors_tolerance_rejette_le_candidat_sans_rien_publier(base_durable, politique):
    c = _un_candidat()
    r = _appeler("m3_valider_candidat_par_reference", candidat_id=c["candidat_id"], reference=_reference("0.80"))
    assert r["resultat"]["decision"]["statut"] == "rejetee_ecart_reference"
    assert _evenements("m3.mesure_vision_validee") == []
    lus = _appeler("m3_lire_candidats_vision")["resultat"]["candidats"][0]
    assert lus["decision"]["utilisable_comme_mesure"] is False and lus["decision"]["valeur_retenue"] is None


def test_un_candidat_sous_le_seuil_ou_inconnu_ne_se_valide_jamais(base_durable, politique):
    c = _un_candidat(confiance="0.40")
    refus = _appeler("m3_valider_candidat_par_reference", candidat_id=c["candidat_id"], reference=_reference("0.5"))
    assert refus["accepte"] is False and refus["verdict"]["code"] == "REJ-VISION-DECISION-INVALIDE"
    lus = _appeler("m3_lire_candidats_vision")["resultat"]["candidats"][0]
    assert lus["evaluation"]["statut"] == "rejetee_confiance"
    introuvable = _appeler("m3_valider_candidat_par_reference", candidat_id="cand-inconnu", reference=_reference("0.5"))
    assert introuvable["verdict"]["code"] == "REJ-VISION-CANDIDAT-INTROUVABLE"
    assert _evenements("m3.mesure_vision_validee") == []


def test_un_agent_ne_peut_pas_se_donner_sa_propre_politique(base_durable):
    """La politique ne se passe pas en argument : le schéma d'outil la refuse (additionalProperties faux)."""
    reponse = executer_atomique(
        _outil("m3_valider_candidat_par_reference"),
        {"candidat_id": "cand-x", "reference": _reference(), "politique": dict(POLITIQUE)},
    )
    assert reponse["ok"] is False


def test_la_validation_humaine_exige_une_decision_approuvee_dans_la_file(base_durable, politique, personnes):
    c = _un_candidat()
    args = {"candidat_id": c["candidat_id"], "decision": "valider", "valeur_corrigee": None}
    direct = executer_atomique(_outil("m3_valider_candidat_par_humain"), args)
    assert direct["ok"] is True and direct["resultat"]["verdict"]["code"] == "REJ-VISION-DECISION-SANS-APPROBATION"
    assert _nb_maillons() == 1 and _evenements("m3.mesure_vision_validee") == []

    departements = {DEP: lire_manifeste(Path(outils_m3.__file__).resolve().parents[2])}
    capacites = Capacites(departements, stockage.transaction, appelant=DEP, memoire=False)
    mise_en_file = capacites.appeler("m3_valider_candidat_par_humain", args)
    assert mise_en_file["ok"] is True and mise_en_file["statut"] == "en_attente_approbation", mise_en_file
    assert _nb_maillons() == 1, "la demande attend : rien n'est écrit"
    [demande] = [d for d in _demandes() if d["outil"] == "m3_valider_candidat_par_humain"]
    assert demande["niveau"] == "N3" and demande["arguments"] == args

    def decider(personne, approuver=True):
        with stockage.transaction() as cnx:
            outils = outils_executables(departements, lambda: contextlib.nullcontext(cnx))
            return approbations.decider(cnx, demande["id"], approuver, personne, outils, departements)

    with pytest.raises(ValueError):  # un gestionnaire n'a pas le rôle N3 de M3 (défaut : nathan_owner seul)
        decider("gestionnaire")
    assert _nb_maillons() == 1
    decider("proprio")
    assert _nb_maillons() == 2
    [ligne] = _evenements("m3.mesure_vision_validee")
    charge = json.loads(ligne.charge)
    assert (charge["voie"], charge["origine_valeur"], charge["valeur_retenue"]) == (
        "humain",
        "vision_validee_par_humain",
        "0.5000",
    )
    lus = _appeler("m3_lire_candidats_vision", candidat_id=c["candidat_id"])["resultat"]["candidats"][0]
    assert (
        lus["decision"]["humain"]["valide_par"] == "proprio"
        and lus["decision"]["humain"]["approbation_ref"] == demande["id"]
    )


def _demandes():
    with stockage.transaction() as cnx:
        return approbations.lister(cnx, None)


def test_une_approbation_ne_valide_que_les_arguments_exacts_qu_elle_porte(base_durable, politique, personnes):
    """Une décision approuvée pour valider le candidat A ne peut pas faire valider B, ni A avec une valeur corrigée."""
    a = _un_candidat()
    b = _un_candidat_photo2()
    arguments_approuves = {"candidat_id": a["candidat_id"], "decision": "valider", "valeur_corrigee": None}
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(
            cnx, DEP, "m3_valider_candidat_par_humain", arguments_approuves, niveau=Niveau.N3
        )
        cnx.execute(
            APPROBATIONS.update()
            .where(APPROBATIONS.c.id == demande)
            .values(statut="en_cours", decide_par="proprio", decide_role="nathan_owner", decide_le=LE)
        )
    for detourne in (
        {"candidat_id": b["candidat_id"], "decision": "valider", "valeur_corrigee": None},
        {"candidat_id": a["candidat_id"], "decision": "valider", "valeur_corrigee": "99.0"},
        {"candidat_id": a["candidat_id"], "decision": "refuser", "valeur_corrigee": None},
    ):
        with stockage.transaction(), contexte.executer_demande_approuvee(demande):
            reponse = outils_site_vision.valider_candidat_par_humain(**detourne)
        assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-VISION-DECISION-SANS-APPROBATION"
    assert _nb_maillons() == 2  # les deux candidats seulement : aucune décision écrite
    with stockage.transaction(), contexte.executer_demande_approuvee(demande):  # les arguments exacts, eux, passent
        assert outils_site_vision.valider_candidat_par_humain(**arguments_approuves)["accepte"] is True
    assert _nb_maillons() == 3


def _un_candidat_photo2():
    outils_site_vision.brancher_detecteur(
        vision_doubles.DetecteurScripte({"synth-2": [cv.detection(x0=2, y0=2, w=8, h=8)]})
    )
    return _appeler(
        "m3_executer_pipeline_vision",
        lead_id="lead-vis-2",
        photo=cv.photo("synth-2", sha="b" * 64),
        objets=["objet_test"],
        modele_id="vision.double-deterministe",
    )["resultat"]["candidats"][0]


# =========================================================================================== M3.7 géospatial
def test_l_aire_d_un_polygone_passe_par_l_outil_avec_un_recu_rejouable(base_durable):
    r = _appeler(
        "m3_calculer_aire_polygone", systeme="plan_metrique", sommets=[["0", "0"], ["10", "0"], ["10", "5"], ["0", "5"]]
    )
    assert r["accepte"] is True and r["recu"]["resultat"]["aire_m2"] == "50.00"
    from m3_estimation import geometrie_polygone

    assert geometrie_polygone.rejouer(r["recu"]) == (True, "")
    refus = _appeler(
        "m3_calculer_aire_polygone",
        systeme="plan_metrique",
        sommets=[["0", "0"], ["10", "0"], ["0", "10"], ["10", "10"]],
    )
    assert refus["accepte"] is False and refus["verdict"]["code"] == "REJ-GEO-AUTO-INTERSECTION"


def test_aucune_source_geospatiale_n_est_branchee_en_production(base_durable):
    r = _appeler(
        "m3_agreger_donnees_geospatiales",
        adresse={"numero_civique": "1", "odonyme": "Rue Exemple", "municipalite": "Ville Fictive"},
    )
    assert r["accepte"] is True and set(r["statuts"].values()) == {"non_configure"} and r["faits_pour_contexte"] is None
    sources = _appeler("m3_lister_sources_geospatiales")
    assert set(sources["ports"].values()) == {"non_configure"}
    assert all(s["lue_par"] is None for s in sources["sources_candidates"])


def test_des_ports_doubles_branches_nourrissent_le_contexte_de_bout_en_bout(base_durable):
    from m3_estimation import geospatial

    cle = geospatial.normaliser_adresse(
        {"numero_civique": "1", "odonyme": "Rue Exemple", "municipalite": "Ville Fictive"}
    )[0].cle
    source = geospatial.SourceDonnee("double", "2025", LE, "fictif", True)
    outils_site_vision.brancher_ports_geospatiaux(
        role=geospatial.RoleEvaluationDouble({cle: geospatial.UniteEvaluation("m1", 1990, 2, None, None, None, source)})
    )
    agr = _appeler(
        "m3_agreger_donnees_geospatiales",
        adresse={"numero_civique": "1", "odonyme": "Rue Exemple", "municipalite": "Ville Fictive"},
    )
    assert agr["statuts"]["role_evaluation"] == "ok" and agr["statuts"]["cadastre"] == "non_configure"
    r = _appeler(
        "m3_construire_contexte_site",
        lead_id="lead-geo-9",
        service="service_a",
        date_reference="2026-10-15",
        profil_geospatial=agr["faits_pour_contexte"],
    )
    f = {x["facteur"]: x for x in r["contexte"]["facteurs"]}
    assert f["age"]["valeur"] == {"annee_construction": 1990} and f["hauteur"]["valeur"] == {"etages": 2}


def test_aucun_import_reseau_dans_les_nouveaux_modules():
    import ast

    interdits = {"socket", "urllib", "http", "requests", "httpx", "subprocess", "random", "secrets", "uuid"}
    for nom in (
        "contexte_site",
        "journal_site",
        "vision_contrat",
        "vision_gouvernance",
        "vision_evaluation",
        "vision_doubles",
        "geospatial",
        "geometrie_polygone",
        "vision_modeles",
        "outils_site_vision",
    ):
        arbre = ast.parse((Path(outils_m3.__file__).parent / f"{nom}.py").read_text(encoding="utf-8"))
        importes = {n.names[0].name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import)}
        importes |= {
            n.module.split(".")[0]
            for n in ast.walk(arbre)
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0
        }
        assert not importes & interdits, (nom, importes & interdits)


def test_tous_les_codes_de_refus_emis_existent_au_catalogue_de_m3():
    sources = " ".join(
        (Path(outils_m3.__file__).parent / f"{n}.py").read_text(encoding="utf-8")
        for n in (
            "contexte_site",
            "vision_contrat",
            "vision_gouvernance",
            "geometrie_polygone",
            "geospatial",
            "outils_site_vision",
        )
    )
    import re

    for code in set(re.findall(r'"(REJ-(?:CONTEXTE|VISION|GEO|SITE)-[A-Z-]+)"', sources)):
        assert verdicts.est_verdict(code), code


def test_le_total_des_maillons_et_des_evenements_reste_celui_des_ecritures_acceptees(base_durable):
    # Contrôle de sobriété : aucune écriture parasite hors des outils d'écriture.
    _appeler("m3_lister_modeles_vision")
    _appeler("m3_lister_sources_geospatiales")
    _appeler("m3_calculer_aire_polygone", systeme="plan_metrique", sommets=[["0", "0"], ["1", "0"], ["0", "1"]])
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one() == 0
    assert _nb_maillons() == 0
