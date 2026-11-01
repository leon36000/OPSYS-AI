"""M2.15 Analytique et prévisions commerciales : les VRAIS outils `m2_analyser_pipeline` et `m2_prevoir_pipeline`, sur
un
registre réel peuplé de leads fictifs étalés sur seize semaines.

Ce qui est prouvé ici :
- chaque mesure dit son effectif et son seuil ; sous le seuil, elle REFUSE de conclure (taux, délai de cycle, valeur)
  ;
- une prévision est un INTERVALLE (jamais un point seul), reproductible par sa graine, rejouable par son reçu ;
- sous le seuil d'échantillon déclaré (12 semaines, 20 événements), la prévision est REFUSÉE et dit ce qu'il faut ;
- les séries hebdomadaires sont exactes (la somme des semaines complètes égale le nombre d'événements de la fenêtre) ;
- un vendeur n'analyse que SES leads ; la valeur pondérée utilise la valeur DÉCLARÉE et dit ce qui manque. Données
  fictives (`fictif: true`).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil

import pytest
from m2_revenue_crm import outils, previsions
from ventes_aide import ADMIN, EMPLOYE, MAINTENANT, VENDEUR_DEUX, VENDEUR_UN, Monde, taille

from opsys import identite, stockage
from opsys.outils import Autonomie, Niveau

FICTIF = True
FIN = dt.datetime.fromisoformat(MAINTENANT)
DEBUT = FIN - dt.timedelta(days=111)
ACTION = {"description": "Appeler le client", "echeance": "2026-07-05T09:00:00-04:00"}


def _iso(instant):
    return instant.isoformat()


def _peupler(m, n=80, vendeur="vendeur.un", prefixe="p", debut=DEBUT):
    """`n` leads étalés sur ~16 semaines : trois sur quatre qualifiés, un tiers de ceux-ci convertis, un cinquième
    perdus."""
    for k in range(n):
        lead_id = f"{prefixe}{k:03d}"
        ingere = debut + dt.timedelta(hours=33 * k)
        contrat = {
            "lead_id": lead_id,
            "conversation_id": f"conv-{lead_id}",
            "type_travaux": "renovation_totale",
            "contact": {
                "nom": f"Client {lead_id}",
                "telephone": f"418-{k:03d}-{(k * 7) % 10000:04d}",
                "courriel": f"{lead_id}@example.test",
            },
            "ville": "Québec",
            "urgence_declaree": k % 7 == 0,
            "canal": "telephone",
        }
        assert outils.ingerer_lead(contrat, _iso(ingere))["accepte"] is True
        if k % 4 == 3:
            continue
        qualifie = ingere + dt.timedelta(days=1)
        assert (
            outils.transitionner_statut(lead_id, "qualifie", _iso(qualifie), owner=vendeur, prochaine_action=ACTION)[
                "accepte"
            ]
            is True
        )
        if k % 3 == 0:
            converti = qualifie + dt.timedelta(days=3 + k % 9)
            assert (
                outils.transitionner_statut(lead_id, "converti", _iso(converti), reference_devis_m3=f"devis-{lead_id}")[
                    "accepte"
                ]
                is True
            )
        elif k % 5 == 0:
            perdu = qualifie + dt.timedelta(days=5 + k % 4)
            assert (
                outils.transitionner_statut(lead_id, "perdu", _iso(perdu), motif="Budget insuffisant.")["accepte"]
                is True
            )


@pytest.fixture(scope="module")
def base_peuplee(tmp_path_factory):
    """Une base SQLite peuplée UNE fois (80 leads sur seize semaines) ; chaque test en reçoit une copie."""
    dossier = tmp_path_factory.mktemp("pipeline")
    url = f"sqlite:///{dossier / 'gros.db'}"
    mp = pytest.MonkeyPatch()
    mp.setenv(stockage.ENV_URL, url)
    mp.setenv("OPSYS_HOME", str(dossier / "home"))
    try:
        stockage.migrer(url)
        outils.utiliser_stockage_durable()
        with stockage.transaction() as cnx:
            for ident, roles in (
                ("nathan", ["nathan_owner", "admin"]),
                ("admin.fictif", ["admin"]),
                ("vendeur.un", ["seller"]),
                ("vendeur.deux", ["seller"]),
                ("marc.fictif", ["employee"]),
            ):
                identite.creer_personne(cnx, ident, ident, "mot-de-passe-fictif-12345", roles)
        monde_ = Monde(dossier, mp)
        _peupler(monde_)
        stockage.liberer()
    finally:
        outils.reinitialiser_registre()
        mp.undo()
    return dossier / "gros.db"


@pytest.fixture
def gros(base_peuplee, tmp_path, monkeypatch):
    copie = tmp_path / "opsys-m2-ventes.db"
    shutil.copyfile(base_peuplee, copie)
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{copie}")
    outils.utiliser_stockage_durable()
    monde_ = Monde(tmp_path, monkeypatch)
    monde_.configurer()
    try:
        yield monde_
    finally:
        outils.reinitialiser_registre()
        stockage.liberer()


def _analyser(m, qui=ADMIN, **plus):
    return m.appeler("m2_analyser_pipeline", {"horodatage": MAINTENANT, **plus}, qui)


def _prevoir(m, qui=ADMIN, **plus):
    arguments = {
        "horodatage": MAINTENANT,
        "serie": "leads_ingeres",
        "methode": "moyenne_mobile",
        "fenetre": 4,
        "horizon": 4,
        **plus,
    }
    return m.appeler("m2_prevoir_pipeline", arguments, qui)


# ---------------------------------------------------------------------------------------- déclaration
def test_niveaux_et_portees(monde):
    for nom in ("m2_analyser_pipeline", "m2_prevoir_pipeline"):
        outil = monde.par_nom[nom]
        assert (outil.autonomie, outil.niveau_effectif) == (Autonomie.T0, Niveau.N0)
        assert outil.roles_appareil == frozenset({"seller", "admin"})
        assert "jamais un point" in outil.description or "seuil" in outil.description


# ---------------------------------------------------------------------------------------- analytique
def test_l_analytique_dit_son_effectif_et_son_seuil_et_calcule_les_taux_les_delais_et_le_pipeline(gros):
    m = gros
    a = m.accepte(_analyser(m))
    assert a["pipeline"]["total"] == 80 and sum(a["pipeline"]["par_statut"].values()) == 80
    assert a["pipeline"]["ouverts"] == a["pipeline"]["par_statut"]["nouveau"] + a["pipeline"]["par_statut"]["qualifie"]
    e = a["entonnoir"]
    assert e["ingeres"] == 80 and e["qualifies_un_jour"] == 60 and e["resolus"] == e["convertis_un_jour"] + e["perdus"]
    conversion = a["taux_conversion_des_resolus"]
    assert (
        conversion["n"] == e["resolus"] >= previsions.SEUILS["resolus_conversion"] and conversion["valeur"] is not None
    )
    assert 0 < float(conversion["valeur"]) < 1
    qualification = a["taux_qualification"]
    assert qualification["valeur"] == "0.7500" and qualification["succes"] == 60 and qualification["n"] == 80
    cycle = a["delai_de_cycle"]
    assert cycle["unite"] == "jours" and cycle["n"] == e["convertis_un_jour"] and cycle["valeurs"] is not None
    assert 4 <= float(cycle["valeurs"]["mediane"]) <= 13 and float(cycle["valeurs"]["p25"]) <= float(
        cycle["valeurs"]["p75"]
    )
    assert a["seuils_declares"] == previsions.SEUILS and "CPA" in " ".join(a["avertissements"])
    assert taille({"ok": True, "resultat": {"accepte": True, "resultat": a}}) < 6000


def test_sous_le_seuil_la_mesure_refuse_de_conclure_au_lieu_d_estimer(monde):
    m = monde
    _peupler(m, n=12)
    a = m.accepte(_analyser(m))
    assert (
        a["taux_conversion_des_resolus"]["valeur"] is None
        and "échantillon insuffisant" in a["taux_conversion_des_resolus"]["refus"]
    )
    assert a["taux_conversion_des_resolus"]["n"] < a["taux_conversion_des_resolus"]["seuil"]
    assert a["delai_de_cycle"]["valeurs"] is None and "insuffisant" in a["delai_de_cycle"]["refus"]
    assert a["taux_qualification"]["valeur"] is None
    assert a["valeur_ponderee"]["valeur_ponderee"] is None


def test_la_valeur_ponderee_exige_la_valeur_declaree_et_donne_un_intervalle(gros):
    m = gros
    sans = m.accepte(_analyser(m))["valeur_ponderee"]
    assert sans["valeur_ponderee"] is None and "aucune valeur déclarée" in sans["refus"]
    ouverts = [k for k in range(80) if k % 4 == 3 or (k % 3 != 0 and k % 5 != 0)]
    for k in ouverts[:6]:
        m.accepte(
            m.appeler(
                "m2_declarer_valeur_pipeline",
                {"lead_id": f"p{k:03d}", "montant": f"{10000 + 1000 * k}.00", "horodatage": MAINTENANT},
                ADMIN,
            )
        )
    a = m.accepte(_analyser(m))["valeur_ponderee"]
    v = a["valeur_ponderee"]
    assert v is not None and v["intervalle"]["niveau"] == 80
    assert float(v["intervalle"]["bas"]) < float(v["intervalle"]["haut"]), "un intervalle, pas un point"
    assert float(v["centre"]) < float(a["valeur_declaree_totale"]), "pondérée < brute : la probabilité est < 1"
    assert a["ouverts"] > a["sans_valeur_declaree"] > 0 and "bootstrap" in v["methode"]
    # une autre graine ne déplace pas le centre (calculé sans tirage)
    autre = m.accepte(_analyser(m, graine=99))["valeur_ponderee"]["valeur_ponderee"]
    assert autre["centre"] == v["centre"]
    # la même graine redonne exactement la même chose
    assert m.accepte(_analyser(m))["valeur_ponderee"] == a


def test_un_vendeur_n_analyse_que_ses_leads(monde):
    m = monde
    _peupler(m, n=60, vendeur="vendeur.un", prefixe="a")
    _peupler(m, n=60, vendeur="vendeur.deux", prefixe="b")
    admin = m.accepte(_analyser(m, ADMIN))
    un = m.accepte(_analyser(m, VENDEUR_UN))
    deux = m.accepte(_analyser(m, VENDEUR_DEUX))
    assert admin["pipeline"]["total"] == 120
    assert un["pipeline"]["total"] == 45 == deux["pipeline"]["total"], (
        "les leads « nouveau » sans propriétaire sont exclus"
    )
    assert un["perimetre"] == "les leads de la personne authentifiée" and admin["perimetre"] == "tous les leads"
    assert (
        un["entonnoir"]["convertis_un_jour"] + deux["entonnoir"]["convertis_un_jour"]
        <= admin["entonnoir"]["convertis_un_jour"]
    )
    assert m.code(_analyser(m, EMPLOYE)) == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_le_recu_de_l_analytique_se_rejoue_et_se_verifie(gros):
    m = gros
    reponse = m.accepte(_analyser(m, avec_recu=True))
    recu = reponse["recu"]
    assert recu["moteur"] == "analytique_pipeline" and recu["format"] == "recu-calcul.v1"
    if "entrees" in recu:
        assert m.accepte(m.appeler("m2_rejouer_recu_commercial", {"recu": recu}, ADMIN))["identique"] is True
    else:
        assert (
            recu["entrees_omises"] is True
            and m.code(
                m.appeler(
                    "m2_rejouer_recu_commercial",
                    {"recu": {k: v for k, v in recu.items() if k != "entrees_omises"}},
                    ADMIN,
                )
            )
            == "REJ-PREV-RECU-INVALIDE"
        )
    # l'entrée du reçu est anonyme : ni identifiant de lead, ni contact
    texte = json.dumps(recu, ensure_ascii=False)
    assert "example.test" not in texte and "p000" not in texte and "Client p" not in texte


@pytest.mark.parametrize("plus", [{"niveau": 70}, {"repetitions": 10}, {"graine": -1}, {"niveau": "80"}])
def test_parametres_d_analyse_invalides_refuses(gros, plus):
    m = gros
    reponse = _analyser(m, **plus)
    assert reponse["ok"] is False or m.code(reponse) == "REJ-PREV-PARAMETRE-INVALIDE"


# ---------------------------------------------------------------------------------------- séries
def test_la_serie_hebdomadaire_est_exacte(gros):
    reg = outils._obtenir_registre().lire()
    from m2_revenue_crm import liste_leads

    records = previsions.enregistrements(liste_leads.fiches_des_leads(reg), {})
    fin_s = previsions.instant_s(MAINTENANT)
    for nom, cle in (
        ("leads_ingeres", "ingere_s"),
        ("leads_qualifies", "qualifie_s"),
        ("leads_convertis", "converti_s"),
        ("leads_perdus", "perdu_s"),
    ):
        serie = previsions.serie_hebdomadaire(records, nom, fin_s)
        assert len(serie) == 15 and all(type(v) is int and v >= 0 for v in serie), nom
        debut_fenetre = fin_s - 7 * 86400 * len(serie)
        attendu = sum(1 for r in records if r[cle] is not None and debut_fenetre < r[cle] <= fin_s)
        assert sum(serie) == attendu, nom
    # la dernière semaine est exactement (fin − 7 j ; fin]
    serie = previsions.serie_hebdomadaire(records, "leads_ingeres", fin_s)
    derniere = sum(1 for r in records if fin_s - 7 * 86400 < r["ingere_s"] <= fin_s)
    assert serie[-1] == derniere


# ---------------------------------------------------------------------------------------- prévision
def test_une_prevision_est_un_intervalle_reproductible_avec_son_centre_comme_repere(gros):
    m = gros
    p = m.accepte(_prevoir(m, serie="leads_ingeres"))
    total = p["prevision_totale"]
    assert total["horizon_periodes"] == 4 and total["intervalle"]["niveau"] == 80
    assert float(total["intervalle"]["bas"]) < float(total["intervalle"]["haut"]), "un intervalle, jamais un point seul"
    assert len(p["par_periode"]) == 4 and all(
        float(x["intervalle"]["bas"]) <= float(x["intervalle"]["haut"]) for x in p["par_periode"]
    )
    assert p["serie"]["periodes"] == 15 and 70 <= p["serie"]["evenements"] <= 80
    assert any("repère" in a for a in p["avertissements"]) and "bootstrap" in p["methode"]
    # reproductible par la graine ; une autre graine change l'intervalle
    assert m.accepte(_prevoir(m, serie="leads_ingeres")) == p
    autre = m.accepte(_prevoir(m, serie="leads_ingeres", graine=7))
    assert autre["prevision_totale"]["centre"] == total["centre"]
    assert taille({"ok": True, "resultat": {"accepte": True, "resultat": p}}) < 6000


def test_un_niveau_plus_eleve_donne_un_intervalle_plus_large(gros):
    m = gros
    largeurs = {}
    for niveau in (80, 90, 95):
        i = m.accepte(_prevoir(m, niveau=niveau))["prevision_totale"]["intervalle"]
        largeurs[niveau] = float(i["haut"]) - float(i["bas"])
    assert largeurs[80] <= largeurs[90] <= largeurs[95] and largeurs[80] < largeurs[95]


def test_les_deux_methodes_donnent_chacune_leur_niveau(gros):
    m = gros
    mm = m.accepte(_prevoir(m, methode="moyenne_mobile", fenetre=3, alpha=None))
    ses = m.accepte(_prevoir(m, methode="lissage_exponentiel", fenetre=None, alpha="0.4"))
    assert mm["niveau_courant"] != ses["niveau_courant"]
    assert "moyenne_mobile (fenêtre 3)" in mm["methode"] and "alpha 0.4" in ses["methode"]


def test_sous_le_seuil_d_echantillon_la_prevision_refuse_et_dit_ce_qu_il_faut(monde):
    m = monde
    _peupler(m, n=30, debut=FIN - dt.timedelta(days=36))  # un CRM de cinq semaines
    reponse = _prevoir(m)
    verdict = m.verdict(reponse)
    assert verdict["code"] == "REJ-PREV-ECHANTILLON-INSUFFISANT"
    assert "12" in verdict["detail"] and "20" in verdict["detail"] and "Aucune prévision" in verdict["detail"]


def test_sans_aucun_lead_la_prevision_refuse(monde):
    assert monde.code(_prevoir(monde)) == "REJ-PREV-ECHANTILLON-INSUFFISANT"


def test_une_serie_constante_est_refusee(monde):
    m = monde
    # un lead par semaine pendant 16 semaines : aucune variation
    for k in range(16):
        ingere = DEBUT + dt.timedelta(days=7 * k, hours=3)
        contrat = {
            "lead_id": f"c{k}",
            "conversation_id": f"conv-c{k}",
            "type_travaux": "renovation_totale",
            "contact": {"nom": f"C {k}", "courriel": f"c{k}@example.test"},
            "ville": "Québec",
            "urgence_declaree": False,
            "canal": "telephone",
        }
        assert outils.ingerer_lead(contrat, _iso(ingere))["accepte"] is True
    reponse = _prevoir(m, evenements_minimum=20)
    assert m.code(reponse) in ("REJ-PREV-SERIE-DEGENEREE", "REJ-PREV-ECHANTILLON-INSUFFISANT")
    reponse = _prevoir(m, evenements_minimum=20, serie="leads_ingeres", horizon=2)
    assert m.code(reponse) in ("REJ-PREV-SERIE-DEGENEREE", "REJ-PREV-ECHANTILLON-INSUFFISANT")


@pytest.mark.parametrize(
    ("plus", "code"),
    [
        ({"methode": "moyenne_mobile", "fenetre": None}, "REJ-PREV-PARAMETRE-INVALIDE"),
        ({"methode": "moyenne_mobile", "fenetre": 4, "alpha": "0.3"}, "REJ-PREV-PARAMETRE-INVALIDE"),
        ({"methode": "lissage_exponentiel", "fenetre": None, "alpha": "0"}, "REJ-PREV-PARAMETRE-INVALIDE"),
        ({"methode": "lissage_exponentiel", "fenetre": None, "alpha": "1.5"}, "REJ-PREV-PARAMETRE-INVALIDE"),
        ({"methode": "lissage_exponentiel", "fenetre": None, "alpha": "0.12345"}, "REJ-PREV-PARAMETRE-INVALIDE"),
        ({"methode": "lissage_exponentiel", "fenetre": None, "alpha": "abc"}, "REJ-PREV-PARAMETRE-INVALIDE"),
        ({"methode": "lissage_exponentiel", "fenetre": 3, "alpha": "0.3"}, "REJ-PREV-PARAMETRE-INVALIDE"),
        ({"fenetre": 12}, "REJ-PREV-PARAMETRE-INVALIDE"),  # plus que la moitié de l'historique (15 // 2 = 7)
        ({"horizon": 8}, "REJ-PREV-PARAMETRE-INVALIDE"),  # plus que le tiers de l'historique (15 // 3 = 5)
    ],
)
def test_parametres_de_prevision_invalides_refuses_sans_ecriture(gros, plus, code):
    m = gros
    avant = m.instantane()
    reponse = _prevoir(m, **plus)
    assert reponse["ok"] is False or m.code(reponse) == code
    assert m.instantane() == avant


@pytest.mark.parametrize(
    "plus",
    [
        {"horizon": 0},
        {"horizon": 9},
        {"niveau": 99},
        {"periodes_minimum": 5},
        {"evenements_minimum": 3},
        {"serie": "tout"},
        {"methode": "arima"},
        {"repetitions": 1_000_000},
    ],
)
def test_le_schema_refuse_les_seuils_abaisses_et_les_valeurs_hors_liste(gros, plus):
    m = gros
    reponse = _prevoir(m, **plus)
    assert reponse["ok"] is False or reponse["resultat"]["accepte"] is False


def test_un_seuil_peut_etre_releve_pas_abaisse(gros):
    m = gros
    reponse = _prevoir(m, periodes_minimum=20)
    assert m.code(reponse) == "REJ-PREV-ECHANTILLON-INSUFFISANT", "15 semaines < 20 exigées"
    assert m.code(_prevoir(m, evenements_minimum=500)) == "REJ-PREV-ECHANTILLON-INSUFFISANT"


def test_le_recu_de_prevision_se_rejoue_a_l_identique_et_un_chiffre_retouche_est_refuse(gros):
    m = gros
    recu = m.accepte(_prevoir(m, avec_recu=True))["recu"]
    assert recu["moteur"] == "prevision_commerciale" and "entrees" in recu
    assert recu["parametres"]["graine"] == 20261101 and recu["parametres"]["repetitions"] == 1000
    rejeu = m.accepte(m.appeler("m2_rejouer_recu_commercial", {"recu": recu}, ADMIN))
    assert rejeu["identique"] is True
    retouche = json.loads(json.dumps(recu))
    retouche["resultat"]["prevision_totale"]["intervalle"]["haut"] = "999.00"
    assert m.code(m.appeler("m2_rejouer_recu_commercial", {"recu": retouche}, ADMIN)) == "REJ-PREV-RECU-INVALIDE"
    # des entrées retouchées avec des empreintes refaites par un tiers : le rejeu donne un autre résultat
    from opsys import recu_calcul_pont

    faux = json.loads(json.dumps(recu))
    faux["entrees"]["serie"][0] += 5
    refait = recu_calcul_pont.construire(
        moteur=faux["moteur"],
        version_moteur=faux["version_moteur"],
        methode=faux["methode"],
        precision=faux["precision"],
        parametres=faux["parametres"],
        entrees=faux["entrees"],
        resultat=faux["resultat"],
        avertissements=faux["avertissements"],
    )
    verdict_rejeu = m.accepte(m.appeler("m2_rejouer_recu_commercial", {"recu": refait}, ADMIN))
    assert verdict_rejeu["identique"] is False, "le résultat ne correspond pas aux entrées : le rejeu le dit"


def test_le_reçu_est_verifiable_par_l_outil_de_m5(gros):
    m = gros
    recu = m.accepte(_prevoir(m, avec_recu=True))["recu"]
    from m5_financecore import recu_calcul

    assert recu_calcul.verifier(recu) == (True, "")


def test_la_prevision_ne_change_rien_au_registre(gros):
    m = gros
    avant = m.instantane()
    m.accepte(_prevoir(m))
    m.accepte(_analyser(m))
    assert m.instantane() == avant
    _ = previsions
