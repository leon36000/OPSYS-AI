"""Les huit outils des médias payants, avec la VRAIE base, la VRAIE file d'approbation et les VRAIS connecteurs de
lecture (doubles
de fournisseur).

Ce que ces tests prouvent : niveaux et portées (N4 réservé au propriétaire, rien d'exécuté, rien d'écrit hors du
registre des
plans), garde d'argent AVANT toute lecture, chaîne complète ingestion -> plan -> évaluation -> anomalies au bus ->
rapport, trous
et devises étrangères, refus nommés. Ce qu'ils ne prouvent PAS : le comportement des vrais services (aucun réseau).
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fabriques_medias import StudioFictif, plan_brut
from fabriques_signaux import JETON, JETON_DEV, Horloge, coffre_pour, compte, masqueur
from m7_marketing import medias_outils, outils
from m7_marketing.medias_payants import plan as pl
from m7_marketing.signaux import ingestion, publicite
from m7_marketing.signaux.doubles_publicite import DoubleMetaAds
from sqlalchemy import select

from opsys import approbations, contexte, evenements, stockage
from opsys.departements import lire_manifeste
from opsys.evenements import schemas
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

_M7 = Path(__file__).resolve().parents[2]
_OUTILS = {o.nom: o for o in outils.outils()}
_DEPARTEMENTS = {"m07-marketing": lire_manifeste(_M7)}
HORODATAGE = "2026-10-01T12:00:00+00:00"
AUJOURD_HUI = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)  # les rapports publicitaires se lisent jusqu'à HIER
JOURS = [date(2026, 10, 4) + timedelta(days=i) for i in range(28)]
COMPTE_META = "act_12345678"
ADMIN = contexte.IdentiteAppelante("gestion", "admin", "console")

NIVEAUX = {
    "m7_preparer_plan_media": (Autonomie.T1, Niveau.N2),
    "m7_soumettre_plan_media": (Autonomie.T1, Niveau.N2),
    "m7_demander_lancement_campagne": (Autonomie.T1, Niveau.N4),
    "m7_retirer_plan_media": (Autonomie.T1, Niveau.N2),
    "m7_lire_plans_media": (Autonomie.T0, Niveau.N0),
    "m7_evaluer_regles_media": (Autonomie.T0, Niveau.N0),
    "m7_signaler_anomalies_depense": (Autonomie.T1, Niveau.N2),
    "m7_rapport_performance_media": (Autonomie.T0, Niveau.N0),
}


# ---- aides -----------------------------------------------------------------------------------------------------------
def _demande(nom, arguments, niveau=Niveau.N4):
    with stockage.transaction() as cnx:
        return approbations.creer_demande(cnx, "m07-marketing", nom, arguments, niveau=niveau)


def _decider(demande, approuver=True, qui="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, demande, approuver, qui, _OUTILS, _DEPARTEMENTS)


def _agent(nom, arguments):
    return executer_atomique(_OUTILS[nom], arguments)["resultat"]


def _codes(resultat):
    return [r["code"] for r in resultat.get("refus", [])]


def _registres():
    with stockage.transaction() as cnx:
        return [(r.departement, r.registre, r.rang, r.maillon) for r in cnx.execute(select(REGISTRES)).all()]


def _evenements(type_evenement):
    with stockage.transaction() as cnx:
        lignes = (
            cnx.execute(
                select(EVENEMENTS_SORTANTS)
                .where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
                .order_by(EVENEMENTS_SORTANTS.c.evenement_id)
            )
            .mappings()
            .all()
        )
    return [(ligne["evenement_id"], codec.decoder(ligne["charge"])) for ligne in lignes]


@pytest.fixture
def studio(monkeypatch):
    fictif = StudioFictif()
    monkeypatch.setattr(medias_outils, "_resolveur", fictif)
    return fictif


def _preparer(brut=None, cle="cle-plan-media-0123456789", horodatage=HORODATAGE, **plus):
    return _agent(
        "m7_preparer_plan_media",
        {"plan": plan_brut() if brut is None else brut, "cle_idempotence": cle, "horodatage": horodatage, **plus},
    )


def _plan_soumis(brut=None, horodatage=HORODATAGE):
    cree = _preparer(brut, horodatage=horodatage)
    assert cree["accepte"], cree
    soumis = _agent("m7_soumettre_plan_media", {"plan_id": cree["plan_id"], "horodatage": horodatage})
    assert soumis["accepte"], soumis
    return cree["plan_id"], cree["empreinte"]


def _lancement(plan_id, empreinte, horodatage=HORODATAGE):
    return {"plan_id": plan_id, "empreinte": empreinte, "horodatage": horodatage}


def _approuve_lancement(plan_id, empreinte, horodatage=HORODATAGE):
    sortie = _decider(_demande("m7_demander_lancement_campagne", _lancement(plan_id, empreinte, horodatage)))
    assert sortie["statut"] == "executee", sortie
    return sortie["reponse"]["resultat"]


# ======================================================================================================================
# le manifeste
# ======================================================================================================================
@pytest.mark.parametrize("nom", sorted(NIVEAUX))
def test_niveaux_portees_fermees_et_schemas_stricts(nom):
    outil = _OUTILS[nom]
    assert (outil.autonomie, outil.niveau_effectif) == NIVEAUX[nom]
    assert outil.roles_appareil == frozenset(), "aucun appareil : fermé par défaut"
    assert not outil.frontiere_humaine, "ni T3 ni N5 : rien n'est exécuté par ces outils"
    assert outil.parametres["additionalProperties"] is False


def test_le_seul_n4_ajoute_est_le_lancement_et_il_est_reserve_au_proprietaire():
    n4 = {o.nom for o in outils.outils() if o.niveau_effectif is Niveau.N4}
    assert n4 == {"m7_demander_annonce_payante", "m7_demander_lancement_campagne"}
    departement = lire_manifeste(_M7)
    assert set(NIVEAUX) <= {o.nom for o in departement.charger_outils()}
    assert set(departement.roles_autorises(Niveau.N4)) == {"nathan_owner"}


def test_les_outils_de_lecture_d_argent_sont_les_seuls_a_lire_les_faits_publicitaires():
    lecteurs = {
        nom
        for nom, o in _OUTILS.items()
        if o.fonction.__module__ == medias_outils.__name__ and "lire_serie" in inspect.getsource(o.fonction)
    }
    assert lecteurs == {"m7_evaluer_regles_media", "m7_rapport_performance_media"}


def test_aucun_outil_de_ce_module_n_importe_de_transport_ni_de_connecteur():
    arbre = ast.parse(inspect.getsource(medias_outils))
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.ImportFrom):
            importes |= {f"{'.' * noeud.level}{noeud.module or ''}:{a.name}" for a in noeud.names}
        elif isinstance(noeud, ast.Import):
            importes |= {a.name for a in noeud.names}
    interdits = (
        "transport",
        "publicite",
        "catalogue",
        "ingestion",
        "base:",
        "doubles",
        "socket",
        "urllib",
        "http",
        "requests",
        "executeur",
        "connecteur",
    )
    assert not [i for i in importes if any(mot in i.lower() for mot in interdits)], sorted(importes)
    signaux = {i for i in importes if i.startswith(".signaux")}
    assert signaux == {".signaux:minimisation", ".signaux:modele", ".signaux:registre"}, sorted(signaux)


# ======================================================================================================================
# plan -> décision N4 : rien n'est exécuté
# ======================================================================================================================
def test_un_agent_seul_ne_lance_rien_et_le_plan_n_est_pas_approuve(base, studio):
    plan_id, empreinte = _plan_soumis()
    refus = _agent("m7_demander_lancement_campagne", _lancement(plan_id, empreinte))
    assert _codes(refus) == ["REJ-HUMAIN-REQUIS"] and "N3/N4" in refus["refus"][0]["detail"]
    assert _agent("m7_lire_plans_media", {"plan_id": plan_id})["plan"]["etat"] == "PRET_POUR_APPROBATION"


def test_un_admin_qui_n_est_pas_le_proprietaire_ne_lance_rien(base, studio):
    plan_id, empreinte = _plan_soumis()
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("gestion", "admin")), stockage.transaction():
        resultat = medias_outils.demander_lancement_campagne(**_lancement(plan_id, empreinte))
    assert _codes(resultat) == ["REJ-HUMAIN-ROLE-INSUFFISANT"]
    assert _agent("m7_lire_plans_media", {"plan_id": plan_id})["plan"]["etat"] == "PRET_POUR_APPROBATION"


def test_le_proprietaire_approuve_par_la_file_le_lancement_est_consigne_jamais_execute(base, studio):
    plan_id, empreinte = _plan_soumis()
    avant = _registres()
    evenements_avant = _evenements("m7.anomalie_depense_detectee")
    resultat = _approuve_lancement(plan_id, empreinte)
    assert resultat["accepte"] is True and resultat["statut"] == "LANCEMENT_APPROUVE_NON_EXECUTE"
    assert resultat["etat"] == "LANCEMENT_APPROUVE_NON_EXECUTE" and resultat["executee_par_opsys"] is False
    assert "Aucune dépense n'a été engagée par OPSYS" in resultat["suite"]
    # AUCUNE dépense : la seule écriture est un maillon du registre des plans ; rien d'autre n'a bougé
    apres = _registres()
    nouveaux = [x for x in apres if x not in avant]
    assert len(nouveaux) == 1 and nouveaux[0][:2] == ("m07-marketing", "plans_medias")
    assert _evenements("m7.anomalie_depense_detectee") == evenements_avant
    maillon = list(stockage.maillons(*pl.REGISTRE))[-1]
    assert maillon["type"] == "plan_lancement_approuve" and maillon["decision"]["par"] == "nathan"
    assert maillon["decision"]["role"] == "nathan_owner" and maillon["niveau"] == 4


def test_une_empreinte_qui_n_est_plus_la_bonne_n_est_pas_approuvee_par_la_file(base, studio):
    plan_id, ancienne = _plan_soumis()
    revise = _preparer(plan_brut(nom="Soumissions automne révisé"), plan_id=plan_id)
    assert revise["etat"] == "BROUILLON"
    _agent("m7_soumettre_plan_media", {"plan_id": plan_id, "horodatage": HORODATAGE})
    sortie = _decider(_demande("m7_demander_lancement_campagne", _lancement(plan_id, ancienne)))
    assert _codes(sortie["reponse"]["resultat"]) == ["REJ-PLAN-MEDIA-EMPREINTE"]
    assert _approuve_lancement(plan_id, revise["empreinte"])["accepte"] is True


def test_un_visuel_revoque_entre_la_soumission_et_la_decision_bloque_le_lancement(base, studio):
    plan_id, empreinte = _plan_soumis()
    studio.revoquer("visuel-1")
    sortie = _decider(_demande("m7_demander_lancement_campagne", _lancement(plan_id, empreinte)))
    assert _codes(sortie["reponse"]["resultat"]) == ["REJ-PLAN-MEDIA-CREATIF-NON-APPROUVE"]
    assert _agent("m7_lire_plans_media", {"plan_id": plan_id})["plan"]["etat"] == "PRET_POUR_APPROBATION"


def test_preparer_un_plan_refuse_n_ecrit_rien(base, studio):
    avant = _registres()
    refus = _preparer(
        plan_brut(
            budget={
                "montant_total_cents": 999999,
                "plafond_quotidien_cents": 99999,
                "duree_jours": 10,
                "date_debut": "2026-11-10",
            }
        )
    )
    assert refus["accepte"] is False and "REJ-PLAN-MEDIA-PLAFOND" in _codes(refus)
    assert _registres() == avant


def test_retirer_un_plan_par_l_outil_et_lire_les_plans(base, studio):
    plan_id, _ = _plan_soumis()
    assert (
        _agent("m7_retirer_plan_media", {"plan_id": plan_id, "motif": "plus utile", "horodatage": HORODATAGE})["etat"]
        == "RETIRE"
    )
    assert _agent("m7_lire_plans_media", {"etat": "RETIRE"})["total"] == 1
    assert _agent("m7_lire_plans_media", {"etat": "BROUILLON"})["total"] == 0
    assert _codes(_agent("m7_lire_plans_media", {"plan_id": "plan-inconnu"})) == ["REJ-PLAN-MEDIA-INCONNU"]


def test_le_dossier_de_lancement_n_existe_que_pour_un_plan_approuve(base, studio):
    plan_id, empreinte = _plan_soumis()
    sans = _agent("m7_lire_plans_media", {"plan_id": plan_id, "avec_dossier": True})
    assert sans["dossier"] is None and "lancement est approuvé" in sans["dossier_refus"]
    assert "dossier" not in _agent("m7_lire_plans_media", {"plan_id": plan_id})
    _approuve_lancement(plan_id, empreinte)
    avec = _agent("m7_lire_plans_media", {"plan_id": plan_id, "avec_dossier": True})["dossier"]
    assert avec["empreinte"] == empreinte and len(avec["publications_sas_preparees"]) == 1
    (publication,) = avec["publications_sas_preparees"]
    assert publication["type_publication"] == "annonce_payante" and publication["medias"][0]["sha256"] == "a" * 64
    # un visuel revoqué depuis : le dossier ne propose plus de publication avec ce média
    studio.revoquer("visuel-1")
    apres = _agent("m7_lire_plans_media", {"plan_id": plan_id, "avec_dossier": True})["dossier"]
    assert apres["publications_sas_preparees"] == []


# ======================================================================================================================
# garde d'argent : refus AVANT toute lecture
# ======================================================================================================================
@pytest.mark.parametrize(
    "nom, arguments",
    [
        ("evaluer_regles_media", {"debut": "2026-10-04", "fin": "2026-10-31", "campagne_ref": "meta-333"}),
        ("signaler_anomalies_depense", {"debut": "2026-10-04", "fin": "2026-10-31", "campagne_ref": "meta-333"}),
        ("rapport_performance_media", {"canal": "meta", "debut": "2026-10-04", "fin": "2026-10-31"}),
    ],
)
def test_un_agent_seul_est_refuse_avant_toute_lecture_de_depense(base, monkeypatch, nom, arguments):
    def ne_pas_lire(*args, **kwargs):
        raise AssertionError("la dépense ne doit pas être lue avant l'autorisation")

    monkeypatch.setattr(medias_outils, "lire_serie", ne_pas_lire)
    monkeypatch.setattr(medias_outils.registre, "lire", ne_pas_lire)
    monkeypatch.setattr(medias_outils.evenements, "publier", ne_pas_lire)
    with stockage.transaction(), pytest.raises(ValueError, match="REJ-HUMAIN-REQUIS"):
        getattr(medias_outils, nom)(**arguments)


def test_un_employe_ou_un_role_non_autorise_est_refuse(base, monkeypatch):
    from opsys import identite

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe.fictif", "Employé fictif", "mot-de-passe-test-1234", ["employee"])
    monkeypatch.setattr(medias_outils, "lire_serie", lambda *a, **k: pytest.fail("lecture avant la garde"))
    with (
        stockage.transaction(),
        contexte.appele_par_appareil(contexte.IdentiteAppelante("employe.fictif", "employee", "appareil")),
        pytest.raises(ValueError, match="REJ-ROLE-COUTS"),
    ):
        medias_outils.rapport_performance_media("meta", "2026-10-04", "2026-10-31")


@pytest.mark.parametrize(
    "nom, arguments",
    [
        (
            "evaluer_regles_media",
            {"debut": "2026-10-04", "fin": "2026-10-31", "campagne_ref": "meta-333", "canal": "meta"},
        ),
        ("rapport_performance_media", {"canal": "meta", "debut": "2026-10-04", "fin": "2026-10-31"}),
    ],
)
def test_la_garde_est_appliquee_avant_et_reappliquee_apres_la_lecture(base, studio, monkeypatch, nom, arguments):
    from m7_marketing import outils as o

    _ingerer(_meta_double())
    appels = []
    monkeypatch.setattr(o, "_autoriser_lecture_performance", lambda n="x": appels.append(n))
    with stockage.transaction():
        resultat = getattr(medias_outils, nom)(**arguments)
    assert resultat["accepte"] is True and appels == [f"m7_{nom}"] * 2
    # la garde qui échoue APRÈS la lecture (droit retiré entre-temps) : rien n'est rendu
    etat = {"n": 0}

    def retire_au_second_appel(n="x"):
        etat["n"] += 1
        if etat["n"] == 2:
            raise ValueError("REJ-ROLE-COUTS : droit retiré")

    monkeypatch.setattr(o, "_autoriser_lecture_performance", retire_au_second_appel)
    with stockage.transaction(), pytest.raises(ValueError, match="REJ-ROLE-COUTS"):
        getattr(medias_outils, nom)(**arguments)


# ======================================================================================================================
# bout en bout : ingestion (vrais connecteurs, doubles) -> plan -> évaluation -> anomalies au bus -> rapport
# ======================================================================================================================
def _meta_double(*, devise="CAD", sauter=(), pic=None, compte_meta=COMPTE_META, jeton=JETON):
    """Total 50,00 $ par jour ; campagne 333 : 30,00 $ (2 000 impressions, 70 clics, 3 prospects) par jour."""
    jours = [j for j in JOURS if j.isoformat() not in sauter]
    total = {j.isoformat(): ("50.00", 3000, 120, [("lead", 5)]) for j in jours}
    camp = {j.isoformat(): ("30.00", 2000, 70, [("lead", 3)]) for j in jours}
    if pic is not None:
        camp[pic[0]] = (pic[1], 2000, 70, [("lead", 3)])
    return DoubleMetaAds(
        compte=compte_meta,
        jeton=jeton,
        devise=devise,
        jours=total,
        campagnes={"333": {"nom": "Soumissions Meta", "jours": camp}},
    )


def _ingerer(serveur, *, fictif=False, horloge=None, compte_ref="principal", ressource=COMPTE_META):
    cpt = compte("meta_ads", ressource, fictif=fictif, compte_ref=compte_ref)
    coffre = coffre_pour("meta_ads")
    horloge = horloge or Horloge(AUJOURD_HUI)
    con = publicite.ConnecteurMetaAds(serveur, cpt, coffre.fournisseurs(), maintenant=horloge, masqueur=masqueur())
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert all(f["statut"] == "termine" for f in bilan["flux"]), bilan
    return horloge


def _plan_pour_donnees(studio, **plus):
    """Un plan rédigé le 1er octobre pour la période 4 octobre - 31 octobre : 30 $ par jour (plafond), 840 $ au
    total."""
    brut = plan_brut(
        budget={
            "montant_total_cents": 84000,
            "plafond_quotidien_cents": 3000,
            "duree_jours": 28,
            "date_debut": "2026-10-04",
        },
        utm_campagne="contenu-octobre-2026",
        **plus,
    )
    cree = _preparer(brut)
    assert cree["accepte"], cree
    return cree["plan_id"]


def _admin(fonction, *args, **kw):
    with stockage.transaction(), contexte.appele_par_appareil(ADMIN):
        return fonction(*args, **kw)


EVAL = {"debut": "2026-10-04", "fin": "2026-10-31", "campagne_ref": "meta-333"}


def test_serie_normale_aucune_anomalie_et_aucune_regle_non_evaluable(base, studio):
    _ingerer(_meta_double())
    plan_id = _plan_pour_donnees(studio)
    res = _admin(medias_outils.evaluer_regles_media, plan_id=plan_id, **EVAL)
    assert res["accepte"] and res["anomalies"] == [] and res["non_evaluables"] == []
    assert res["jours_lus"] == 28 and res["jours_manquants"] == [] and res["executee"] is False
    types = [c["type"] for c in res["constats"]]
    assert types == ["plafond_quotidien", "plafond_total", "saut_depense"]
    # 30,00 $ par jour pile au plafond du plan : jamais « dépassé » ; 28 x 30 $ = 840 $ pile au budget total
    quotidien, total, _ = res["constats"]
    assert quotidien["declenchee"] is False and quotidien["valeur"] == "30" and quotidien["seuil"] == "36"
    assert total["declenchee"] is False and total["valeur"] == "840" and total["seuil"] == "840"
    assert res["fictifs_presents"] is False and res["canal"] == "meta" and res["plan_id"] == plan_id


def test_un_pic_de_depense_declenche_trois_regles_et_chaque_anomalie_va_au_bus_une_fois(base, studio):
    _ingerer(_meta_double())
    plan_id = _plan_pour_donnees(studio)
    horloge = _ingerer(_meta_double(pic=("2026-10-29", "95.00")))  # relecture : le pic est une RÉVISION du jour
    res = _admin(medias_outils.evaluer_regles_media, plan_id=plan_id, **EVAL)
    par_regle = {a["regle"]: a for a in res["anomalies"]}
    # 9 500 cents > 2 x 3 600 : critique ; 27 x 30 + 95 = 905 $ > 840 $ ; 9 500 x 100 > 3 000 x 300 et écart 6 500 >= 2
    # 500
    assert sorted(par_regle) == ["DEP-01", "DEP-03", "DEP-07"]
    assert par_regle["DEP-01"]["severite"] == "critique" and par_regle["DEP-01"]["valeur"] == "95"
    assert par_regle["DEP-01"]["seuil"] == "36" and par_regle["DEP-01"]["jour_debut"] == "2026-10-29"
    assert par_regle["DEP-07"]["severite"] == "critique" and par_regle["DEP-07"]["valeur"] == "905"
    assert par_regle["DEP-03"]["severite"] == "attention" and par_regle["DEP-03"]["seuil"] == "90"  # 3 x médiane 30 $
    assert all(a["executee"] is False and a["action_preparee"] == "proposer_pause" for a in res["anomalies"])
    assert horloge() == AUJOURD_HUI
    # --- au bus : par la seule voie N2, idempotente
    avant = _evenements("m7.anomalie_depense_detectee")
    assert avant == []
    signale = _admin(medias_outils.signaler_anomalies_depense, plan_id=plan_id, **EVAL)
    assert signale["evenements_publies"] == 3
    publies = _evenements("m7.anomalie_depense_detectee")
    assert len(publies) == 3
    for identifiant, charge in publies:
        assert schemas.erreurs_charge("m7.anomalie_depense_detectee", charge) == []
        assert identifiant.startswith("m7-anomalie-") and charge["campagne_ref"] == "meta-333"
        assert charge["canal"] == "meta" and charge["fictif"] is False and "nom" not in charge
    assert {c["regle"] for _, c in publies} == {"DEP-01", "DEP-03", "DEP-07"}
    # rejeu : rien de plus, aucune exception, mêmes identifiants
    rejoue = _admin(medias_outils.signaler_anomalies_depense, plan_id=plan_id, **EVAL)
    assert rejoue["evenements_publies"] == 3 and _evenements("m7.anomalie_depense_detectee") == publies


def test_le_rejeu_plus_tard_d_une_meme_anomalie_n_est_pas_un_conflit_de_bus(base, studio, monkeypatch):
    _ingerer(_meta_double(pic=("2026-10-29", "95.00")))
    plan_id = _plan_pour_donnees(studio)
    _admin(medias_outils.signaler_anomalies_depense, plan_id=plan_id, **EVAL)
    publies = _evenements("m7.anomalie_depense_detectee")
    monkeypatch.setattr(medias_outils, "_maintenant", lambda: datetime(2026, 12, 25, 8, 0, tzinfo=UTC))
    _admin(medias_outils.signaler_anomalies_depense, plan_id=plan_id, **EVAL)
    assert _evenements("m7.anomalie_depense_detectee") == publies


def test_une_valeur_revisee_donne_un_nouvel_evenement_et_pas_un_conflit(base, studio):
    _ingerer(_meta_double(pic=("2026-10-29", "95.00")))
    plan_id = _plan_pour_donnees(studio)
    _admin(medias_outils.signaler_anomalies_depense, plan_id=plan_id, **EVAL)
    avant = _evenements("m7.anomalie_depense_detectee")
    horloge = Horloge(AUJOURD_HUI + timedelta(hours=2))
    _ingerer(_meta_double(pic=("2026-10-29", "120.00")), horloge=horloge)  # la plateforme révise le pic à 120 $
    _admin(medias_outils.signaler_anomalies_depense, plan_id=plan_id, **EVAL)
    apres = _evenements("m7.anomalie_depense_detectee")
    assert len(apres) > len(avant) and {i for i, _ in avant} <= {i for i, _ in apres}
    assert {c["valeur"] for _, c in apres if c["regle"] == "DEP-01"} == {"95", "120"}


def test_comptes_fictifs_les_anomalies_et_les_evenements_portent_fictif_vrai(base, studio):
    _ingerer(_meta_double(pic=("2026-10-29", "95.00")), fictif=True)
    plan_id = _plan_pour_donnees(studio)
    res = _admin(medias_outils.evaluer_regles_media, plan_id=plan_id, **EVAL)
    assert res["fictifs_presents"] is True and res["anomalies"] and all(a["fictif"] for a in res["anomalies"])
    _admin(medias_outils.signaler_anomalies_depense, plan_id=plan_id, **EVAL)
    assert all(c["fictif"] is True for _, c in _evenements("m7.anomalie_depense_detectee"))
    rapport = _admin(medias_outils.rapport_performance_media, "meta", "2026-10-04", "2026-10-31")
    assert rapport["fictifs_presents"] is True


def test_un_jour_non_lu_est_un_trou_pas_un_zero(base, studio):
    _ingerer(_meta_double(sauter=("2026-10-15",)))
    plan_id = _plan_pour_donnees(studio)
    res = _admin(medias_outils.evaluer_regles_media, plan_id=plan_id, **EVAL)
    assert res["jours_lus"] == 27 and res["jours_manquants"] == ["2026-10-15"]
    assert [a["regle"] for a in res["anomalies"]] == ["DEP-05"]
    trou = res["anomalies"][0]
    assert trou["severite"] == "info" and trou["valeur"] == "1" and trou["jour_debut"] == "2026-10-15"
    # 27 x 30 $ = 810 $ < 840 $ : on ne peut pas dire que le budget est tenu (le jour manquant pourrait avoir dépensé)
    (total,) = [c for c in res["constats"] if c["type"] == "plafond_total"]
    assert total["declenchee"] is None and total["valeur"] == "810" and total["jours"] == ["2026-10-15"]
    assert [n["regle"] for n in res["non_evaluables"]] == ["DEP-07"]
    rapport = _admin(medias_outils.rapport_performance_media, "meta", "2026-10-04", "2026-10-31")
    (campagne,) = rapport["campagnes"]
    assert campagne["couverture"]["jours_manquants"] == ["2026-10-15"]
    assert campagne["totaux"]["cout_cad"] == "810.00"


def test_une_devise_etrangere_est_comptee_et_jamais_convertie(base, studio):
    _ingerer(_meta_double(devise="USD"))
    res = _admin(medias_outils.evaluer_regles_media, **EVAL, canal="meta")
    assert res["anomalies"] == [] and res["constats"] == [] and res["ignores_devise"] == 28
    assert (
        res["non_evaluables"][0]["regle"] == "toutes"
        and "aucun jour de dépense lu" in res["non_evaluables"][0]["raison"]
    )
    rapport = _admin(medias_outils.rapport_performance_media, "meta", "2026-10-04", "2026-10-31")
    assert rapport["campagnes"] == [] and rapport["ignores_devise"] == 28 and rapport["causalite"] == "non_etablie"


def test_sans_aucun_fait_lu_ni_zero_ni_normal(base, studio):
    res = _admin(medias_outils.evaluer_regles_media, **EVAL, canal="meta")
    assert res["constats"] == [] and res["anomalies"] == [] and res["executee"] is False
    assert "ni zéro ni normal" in res["non_evaluables"][0]["raison"]
    rapport = _admin(medias_outils.rapport_performance_media, "meta", "2026-10-04", "2026-10-31")
    assert rapport["campagnes"] == [] and "pas une absence de dépense" in rapport["lecture"]


def test_sans_plan_les_plafonds_sont_dits_non_evaluables(base, studio):
    _ingerer(_meta_double(pic=("2026-10-29", "95.00")))
    res = _admin(medias_outils.evaluer_regles_media, **EVAL, canal="meta")
    assert [a["regle"] for a in res["anomalies"]] == ["DEP-03"]
    assert any(n["regle_id"] == "plafonds" for n in res["non_evaluables"]) and res["plan_id"] is None


def test_le_rapport_de_performance_de_la_campagne(base, studio):
    from m7_marketing.mesure import statistiques as st

    _ingerer(_meta_double())
    rapport = _admin(medias_outils.rapport_performance_media, "meta", "2026-10-04", "2026-10-31")
    assert rapport["accepte"] and rapport["canal"] == "meta" and rapport["causalite"] == "non_etablie"
    (c,) = rapport["campagnes"]
    # 28 jours x (30,00 $ ; 2 000 impressions ; 70 clics ; 3 prospects)
    assert c["campagne_ref"] == "meta-333"
    assert c["totaux"] == {"cout_cad": "840.00", "impressions": 56000, "clics": 1960, "conversions": "84"}
    assert c["couverture"] == {"jours_attendus": 28, "jours_lus": 28, "jours_manquants": []}
    assert c["taux_de_clic"]["valeur"] == "0.035" and c["taux_de_conversion"]["valeur"] == "0.042857"
    assert c["cout_par_clic_cad"] == "0.43" and c["cout_par_conversion_cad"]["valeur"] == "10.00"
    bas, haut = st.wilson(84, 1960)
    assert c["taux_de_conversion"]["intervalle"] == {"bas": st.texte(bas), "haut": st.texte(haut)}
    assert c["suffisant"] is True and rapport["comparaison"]["classement"] is None
    assert rapport["comparaison"]["niveaux_indistinguables"] == [["meta-333"]]
    # filtre par référence de campagne
    vide = _admin(
        medias_outils.rapport_performance_media, "meta", "2026-10-04", "2026-10-31", campagne_refs=["meta-999"]
    )
    assert vide["campagnes"] == []


def test_plusieurs_comptes_sans_campagne_ref_est_ambigu(base, studio):
    _ingerer(_meta_double())
    _ingerer(_meta_double(compte_meta="act_87654321"), ressource="act_87654321", compte_ref="second")
    res = _admin(medias_outils.evaluer_regles_media, "2026-10-04", "2026-10-31", canal="meta")
    assert res["accepte"] is False and _codes(res) == ["REJ-MEDIA-AMBIGU"]
    unique = _admin(medias_outils.evaluer_regles_media, **EVAL, canal="meta")
    assert unique["accepte"] is True  # avec campagne_ref : une seule série


def test_plan_inconnu_canal_incoherent_et_periode_invalide(base, studio):
    plan_id = _plan_pour_donnees(studio)
    inconnu = _admin(medias_outils.evaluer_regles_media, plan_id="plan-inconnu", **EVAL)
    assert _codes(inconnu) == ["REJ-PLAN-MEDIA-INCONNU"]
    incoherent = _admin(medias_outils.evaluer_regles_media, plan_id=plan_id, canal="google_ads", **EVAL)
    assert _codes(incoherent) == ["REJ-MEDIA-CANAL"]
    assert _codes(_admin(medias_outils.evaluer_regles_media, **EVAL)) == ["REJ-MEDIA-CANAL"]  # ni plan ni canal
    assert _codes(_admin(medias_outils.evaluer_regles_media, **EVAL, canal="tiktok")) == ["REJ-MEDIA-CANAL"]
    for debut, fin in (
        ("2026-10-31", "2026-10-04"),
        ("pas-une-date", "2026-10-31"),
        ("2025-01-01", "2026-10-31"),
        (None, "2026-10-31"),
    ):
        res = _admin(medias_outils.evaluer_regles_media, debut, fin, canal="meta")
        assert _codes(res) == ["REJ-MEDIA-PERIODE"], (debut, fin)
        assert _codes(_admin(medias_outils.rapport_performance_media, "meta", debut, fin)) == ["REJ-MEDIA-PERIODE"]
    assert _codes(_admin(medias_outils.rapport_performance_media, "tiktok", "2026-10-04", "2026-10-31")) == [
        "REJ-MEDIA-CANAL"
    ]


def test_une_periode_de_367_jours_est_acceptee_368_refusee(base, studio):
    debut = date(2025, 10, 31)
    ok = _admin(
        medias_outils.rapport_performance_media, "meta", debut.isoformat(), (debut + timedelta(days=366)).isoformat()
    )
    assert ok["accepte"] is True
    refus = _admin(
        medias_outils.rapport_performance_media, "meta", debut.isoformat(), (debut + timedelta(days=367)).isoformat()
    )
    assert _codes(refus) == ["REJ-MEDIA-PERIODE"]


def test_les_secrets_des_connecteurs_n_apparaissent_dans_aucune_sortie_des_outils(base, studio):
    _ingerer(_meta_double(pic=("2026-10-29", "95.00")))
    plan_id = _plan_pour_donnees(studio)
    sorties = [
        _admin(medias_outils.evaluer_regles_media, plan_id=plan_id, **EVAL),
        _admin(medias_outils.signaler_anomalies_depense, plan_id=plan_id, **EVAL),
        _admin(medias_outils.rapport_performance_media, "meta", "2026-10-04", "2026-10-31"),
        medias_outils.lire_plans_media(plan_id),
    ]
    brut = repr(sorties) + repr(_evenements("m7.anomalie_depense_detectee"))
    assert JETON not in brut and JETON_DEV not in brut and "Soumissions Meta" not in brut


# ======================================================================================================================
# avec un VRAI visuel du studio approuvé par une personne
# ======================================================================================================================
def test_plan_avec_un_vrai_visuel_du_studio_puis_revocation(base, monkeypatch):
    """Le résolveur n'est pas remplacé : `actifs.media_pour_sas` lit le vrai registre du studio créatif."""
    import fabriques_studio as f
    from m7_marketing.brand import registre as registre_marque

    f.ecrire_polices(base / "studio" / "polices")
    registre_marque.enregistrer(
        {
            "name": "Revêtements Horizon Fictif",
            "tagline": "Des toitures qui durent",
            "tone": "chaleureux",
            "colors": ["#0B3C5D", "#F2C14E", "#FFFFFF"],
            "langue": "fr",
        },
        "nathan",
        HORODATAGE,
    )
    brief = f.brief(
        "banniere_social",
        elements_critiques=f.critiques("telephone", "courriel"),
        mentions_obligatoires=["Licence RBQ détenue par l'entreprise"],
    )
    del brief["marque"]
    brief_id = _agent(
        "m7_preparer_brief_creatif",
        {"brief": brief, "cle_idempotence": "cle-brief-0123456789abcdef", "horodatage": HORODATAGE},
    )["brief_id"]
    compose = _agent("m7_composer_visuel_studio", {"brief_id": brief_id, "horodatage": HORODATAGE})
    actif_id = compose["actif_id"]
    assert _agent("m7_controler_visuel_studio", {"actif_id": actif_id, "horodatage": HORODATAGE})["conforme"]
    brut = plan_brut(creatifs=[{"actif_id": actif_id, "textes": plan_brut()["creatifs"][0]["textes"]}])
    # visuel composé et contrôlé mais PAS approuvé : refusé
    refus = _preparer(brut)
    assert _codes(refus) == ["REJ-PLAN-MEDIA-CREATIF-NON-APPROUVE"]
    # la personne approuve le visuel (N3, propriétaire) : le plan est accepté
    assert _agent("m7_demander_revue_visuel_studio", {"actif_id": actif_id, "horodatage": HORODATAGE})["accepte"]
    detail = _agent("m7_lire_studio", {"actif_id": actif_id})["actif"]
    sortie = _decider(
        _demande(
            "m7_approuver_visuel_studio",
            {
                "actif_id": actif_id,
                "composition_empreinte": detail["composition_empreinte"],
                "rapport_empreinte": detail["rapport_empreinte"],
                "horodatage": HORODATAGE,
                "attestations": {
                    "elements_critiques_verifies": True,
                    "aucun_visage_ni_plaque_identifiable": True,
                    "rendu_relu_a_l_ecran": True,
                    "realiste": False,
                },
            },
            Niveau.N3,
        )
    )
    assert sortie["statut"] == "executee", sortie
    cree = _preparer(brut)
    assert cree["accepte"], cree
    media = _agent("m7_lire_studio", {"actif_id": actif_id, "media_sas": True})["media_sas"]["media"]
    plan, _ = pl.normaliser(
        brut,
        **{
            **{
                "politique": medias_outils.POLITIQUE,
                "maintenant": datetime(2026, 10, 1, 12, tzinfo=UTC),
                "resolveur": medias_outils._resolveur,
                "masqueur": masqueur(),
                "controle_marques": None,
            }
        },
    )
    assert plan["creatifs"][0]["media_sha256"] == media["sha256"]
    assert _agent("m7_soumettre_plan_media", {"plan_id": cree["plan_id"], "horodatage": HORODATAGE})["accepte"]
    # la personne révoque le visuel : la décision de lancement est refusée, le plan n'est pas approuvé
    assert (
        _agent(
            "m7_retirer_visuel_studio",
            {"actif_id": actif_id, "action": "revoquer", "motif": "licence changée", "horodatage": HORODATAGE},
        )["etat"]
        == "revoque"
    )
    refus = _decider(_demande("m7_demander_lancement_campagne", _lancement(cree["plan_id"], cree["empreinte"])))
    assert _codes(refus["reponse"]["resultat"]) == ["REJ-PLAN-MEDIA-CREATIF-NON-APPROUVE"]
    assert _agent("m7_lire_plans_media", {"plan_id": cree["plan_id"]})["plan"]["etat"] == "PRET_POUR_APPROBATION"


def test_evenements_et_bus_restent_inchanges_par_la_preparation_d_un_plan(base, studio):
    avant = _registres()
    _plan_soumis()
    apres = _registres()
    assert {(d, r) for d, r, _, _ in apres} - {(d, r) for d, r, _, _ in avant} == {("m07-marketing", "plans_medias")}
    assert evenements.deja_publie("m7-n-existe-pas") is False
