"""Le cash libre est RAFRAÎCHI PAR LE PLANIFICATEUR, de bout en bout (chantier C1 de l'analyse M8).

Le problème de départ (base e0424b040) : `m5_constater_cash_libre` est scellé N3 au registre MCP (T1 sans `niveau`
explicite : la correspondance par défaut T1 -> N3, là où ses sœurs `m5_constater_*` posent N2) ET porte un droit
d'appareil (l'admin le lance de son téléphone). Le planificateur refuse tout outil N3 (`REJ-PLAN-NIVEAU-INTERDIT`) et le
contrôle de cohérence n'accepte comme constat planifié qu'un outil d'agent sans droit d'appareil : le cash libre n'était
donc jamais rafraîchi seul, et quatre mesures de M8 (cash libre, solde, comptes à payer, taxes à remettre) ainsi que la
composante « finance » du score de santé dépendaient d'un geste manuel.

La décision (voir `departments/m05-financecore/docs/M5-CASH-LIBRE-PLANIFIE.md`) : `m5_constater_cash_libre` RESTE N3 et
garde son droit d'appareil (rien n'est élargi) ; une variante PLANIFIÉE `m5_constater_cash_libre_planifie` (N2, agent
seulement, planificateur seulement, réponse sans montant) partage le code d'écriture (`_constater_cash_libre`) et
donc le même registre de constats, le même rang et la même règle « un constat par jour et par version des données ».

Ici : un trésorier FICTIF (solde, factures clients, factures fournisseurs, provision, déclarations du propriétaire,
semés par les vraies aides de M5), le VRAI planificateur durable à horloge INJECTÉE, le VRAI bus, M8 réel, la console
réelle. Prouvé : rien ne part par défaut ni en ombre ; en actif, les quatre mesures et la composante finance se
remplissent avec les chiffres du cas de référence (calculé à la main) ; idempotence par créneau ; la panne de M5
n'arrête pas les autres constats ; un agent ne peut pas déclencher la variante ; l'outil N3 n'est jamais appelé
par le planificateur.
Limites dites : SQLite seulement, horloge injectée, aucun service externe.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import planif_m8_monde as pm
import pytest
from fastapi.testclient import TestClient
from m5_financecore import outils as m5_outils
from m8_analytics import cadence_constats
from m8_analytics import outils as m8_outils
from sqlalchemy import select

from opsys import contexte, idempotence, stockage
from opsys import departements as modele
from opsys.capacites import Capacites
from opsys.connecteurs_planification import constats, etat, journal
from opsys.console import application, wallboards_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.outils import Niveau, executer_atomique
from opsys.stockage.schema import PLANIFICATEUR_EXECUTEURS

FICTIF = True
MDP = "mot-de-passe-fictif-12345"
CASH = "m5.constat.cash-libre"
OUTIL_PLANIFIE = "m5_constater_cash_libre_planifie"
OUTIL_A_LA_DEMANDE = "m5_constater_cash_libre"
TYPE = "m5.cash_libre_constate"
INTERVALLE = 43200
JOUR = 86400
# Les quatre mesures de M8 que le constat alimente, avec la valeur du cas de référence (calculé à la main).
QUATRE = {
    "m8_cash_libre_cad": "27861.98",
    "m8_solde_tresorerie_cad": "37654.33",
    "m8_comptes_a_payer_cad": "459.91",
    "m8_taxes_a_remettre_cad": "1981.69",
}
# Ce qui ne doit jamais sortir de M5 par le journal du planificateur ni par une réponse d'agent : un montant du cas de
# référence ou un mot du propriétaire.
CONFIDENCES = ("27861.98", "37654.33", "459.91", "1981.69", "4200.00", "1350.75", "800.00", "Marc Tremblay",
               "brouillon de paie", "estimation du CPA", "relevé du prêt")
BORNES_FICTIVES = {"sante": {"bornes": {"m8_cash_libre_cad": {"pire": "0", "cible": "50000"}}}}


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    m.attendu = pm.semer_m5_tresorerie(m, tmp_path, monkeypatch)
    yield m
    pm.demonter()


@pytest.fixture
def console(monde, monkeypatch):
    monkeypatch.setattr(wallboards_ui, "_maintenant", lambda: monde.maintenant())
    app = application.creer_application(Configuration("secret-cash-libre-fictif-" + "x" * 40, cookie_securise=False,
                                                      prefixe="/opsys"), charger_departements(), stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        reponse = client.post("/connexion", data={"identifiant": "nathan", "mot_de_passe": MDP},
                              follow_redirects=False)
        assert reponse.status_code == 303
        yield client


# ------------------------------------------------------------------------------------------------------ les aides
def _publies(monde) -> list[dict]:
    return monde.publies(TYPE)


def _traces() -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(pm.M5, "constats_cash_libre"))


def _quatre(monde) -> dict[str, tuple]:
    mesures = monde.mesures()
    return {i: (mesures[i]["statut"], mesures[i]["valeur"], mesures[i]["fraicheur"]) for i in QUATRE}


def _journal(nom: str = CASH) -> list[dict]:
    with stockage.transaction() as cnx:
        return journal.lire(cnx, nom, limite=500)


def _rejouer_creneau() -> None:
    with stockage.transaction() as cnx:
        cnx.execute(PLANIFICATEUR_EXECUTEURS.update().values(prochain_passage=0))


def _a_la_demande(monde, jour: str, cle: str = "cle-1") -> dict:
    """L'admin touche « constater » sur son téléphone : le chemin réel des appels, sans file (l'outil N3)."""
    capacites = Capacites({pm.M5: monde.bus.departements[pm.M5]}, stockage.transaction)
    meta = idempotence.Meta(cle=cle, appareil="tel-admin-fictif", horodatage_appareil=monde.maintenant())
    with contexte.appele_par_appareil(pm.ADMIN):
        return capacites.appeler(OUTIL_A_LA_DEMANDE, {"aujourd_hui": jour}, meta)


def _sante_finance(monde) -> dict:
    par_nom = {o.nom: o for o in monde.bus.departements[pm.M8].charger_outils()}
    reponse = executer_atomique(par_nom["m8_lire_sante_entreprise"], {"maintenant": monde.maintenant()})
    assert reponse["ok"] is True, reponse
    sante = reponse["resultat"]
    return next(c for c in sante["composantes"] if c["id"] == "finance")


def _donner_bornes(monkeypatch) -> None:
    """Le propriétaire déclare les bornes de l'indicateur « cash libre » (valeurs fictives d'essai)."""
    reel = m8_outils._configuration
    monkeypatch.setattr(m8_outils, "_configuration", lambda: {**reel(), **BORNES_FICTIVES})


# =================================================================================== 0. le défaut, tel que constaté
def test_le_defaut_d_origine_l_outil_a_la_demande_est_n3_avec_droit_d_appareil_et_le_planificateur_le_refuse(monde):
    """Rouge-avant : sur la base e0424b040 il n'y a que cet outil. N3 + droit d'appareil : ni `problemes()` ni le
    planificateur ne peuvent l'accepter comme constat planifié. Ce test RESTE vrai après le correctif : c'est
    l'étanchéité de l'action N3 (le correctif n'a ni abaissé ce niveau ni élargi ce droit)."""
    par_nom = {o.nom: o for o in monde.bus.departements[pm.M5].charger_outils()}
    outil = par_nom[OUTIL_A_LA_DEMANDE]
    assert (outil.autonomie.value, outil.niveau_effectif) == ("T1", Niveau.N3)
    assert outil.roles_appareil == frozenset({"admin"})

    declaration = constats.Declaration(pm.M5, "M5", modele.ConstatPlanifie(
        nom="cash-a-la-demande", outil=OUTIL_A_LA_DEMANDE, mesures=tuple(QUATRE),
        appels=((("aujourd_hui", "calcul", "jour"),),)))
    executeur = constats.ExecuteurConstat(declaration)
    ctx = constats.Contexte(monde.plan.ports, None, "essai", monde.plan.departements, monde.horloge())
    with pytest.raises(constats.NiveauInterdit) as refus:
        executeur.traiter("instance", ctx, None)
    assert refus.value.code == "REJ-PLAN-NIVEAU-INTERDIT"
    avec = {pm.M5: _avec_constat(monde.bus.departements[pm.M5], declaration.constat)}
    erreurs = constats.problemes(avec)
    assert any("niveau N3" in e for e in erreurs) and any("agent seulement" in e for e in erreurs), erreurs
    assert monde.nombre_publie() == {}


def _avec_constat(departement, constat):
    import dataclasses

    return dataclasses.replace(departement._departement, constats_planifies=(constat,))


# ======================================================================================= 1. la déclaration au manifeste
def test_le_constat_est_declare_au_manifeste_de_m5_avec_les_quatre_mesures_du_catalogue(monde):
    deps = charger_departements()
    (declare,) = [c for c in deps[pm.M5].constats_planifies if c.nom == "cash-libre"]
    assert declare.outil == OUTIL_PLANIFIE
    assert declare.appels == ((("aujourd_hui", "calcul", "jour"),),)
    assert set(declare.mesures) == set(QUATRE)
    assert constats.problemes(deps) == []
    assert constats.nom_executeur("M5", "cash-libre") == CASH


def test_les_mesures_declarees_sont_exactement_celles_que_m8_tire_de_l_evenement_pas_une_liste_recopiee(monde):
    """On RELIT les définitions de M8 : toute mesure dont la source de données nomme l'événement du cash libre doit être
    déclarée, et rien d'autre."""
    import yaml

    racine = cadence_constats._MANIFESTE.parent / "metrics"
    tirees = set()
    for fichier in racine.glob("*.yaml"):
        for mesure in yaml.safe_load(fichier.read_text(encoding="utf-8")).get("metrics", []):
            if f"{TYPE} (" in mesure.get("source_donnees", ""):
                tirees.add(mesure["id"])
    assert tirees == set(QUATRE), tirees
    (declare,) = [c for c in charger_departements()[pm.M5].constats_planifies if c.nom == "cash-libre"]
    assert set(declare.mesures) == tirees


def test_la_cadence_est_derivee_du_catalogue_et_suit_une_declaration_du_proprietaire(monde, monkeypatch):
    with stockage.transaction() as cnx:
        vue = {v["executeur"]: v for v in etat.vue(cnx)}
    assert vue[CASH]["niveau"] == "N2" and vue[CASH]["mode"] == "inactif"
    derivee = cadence_constats.cadence_par_defaut(tuple(QUATRE))
    assert vue[CASH]["intervalle_s"] == derivee["intervalle_s"] == INTERVALLE
    assert derivee["fenetre_s"] == JOUR and derivee["passages_par_fenetre"] == 2

    # le propriétaire déclare une fenêtre de 48 h pour une de ces mesures : la plus stricte (24 h) commande encore ;
    # pour les quatre à 48 h, la cadence suit sans toucher au code
    reel = cadence_constats._configuration_proprietaire
    monkeypatch.setattr(cadence_constats, "_configuration_proprietaire", lambda: {
        **reel(), "fraicheur_mesures_s": dict.fromkeys(QUATRE, 2 * JOUR)})
    assert cadence_constats.cadence_par_defaut(tuple(QUATRE))["intervalle_s"] == JOUR


# ================================================================================================ 2. rien par défaut
def test_rien_ne_part_par_defaut_les_quatre_mesures_restent_non_calculables_et_la_finance_indeterminee(monde,
                                                                                                      monkeypatch):
    _donner_bornes(monkeypatch)
    assert monde.tour(1)[CASH] == {"statut": "inactif"}
    assert monde.nombre_publie() == {} and _traces() == []
    monde.propager()
    assert {s for s, _, _ in _quatre(monde).values()} == {"non_calculable"}
    finance = _sante_finance(monde)
    assert finance["statut"] == "indetermine" and finance["score"] is None


def test_l_ombre_dit_ce_qu_elle_ferait_sans_rien_publier_ni_tracer_ni_lire_un_registre(monde, monkeypatch):
    _donner_bornes(monkeypatch)
    monde.activer("ombre", noms=(CASH,))

    def interdit(*args, **kwargs):
        raise AssertionError("l'ombre n'appelle aucun outil")

    monkeypatch.setattr(m5_outils, "_constater_cash_libre", interdit)
    monkeypatch.setattr(m5_outils, "constater_cash_libre_planifie", interdit)
    resume = monde.tour(1)[CASH]
    assert resume["statut"] == "ombre" and resume["ressources"] == 1
    aurait = [j for j in _journal() if j["evenement"] == "aurait"]
    assert len(aurait) == 1 and aurait[0]["mode"] == "ombre" and aurait[0]["details"] == {"aurait": 1}
    assert monde.nombre_publie() == {} and _traces() == []
    monde.propager()
    assert {s for s, _, _ in _quatre(monde).values()} == {"non_calculable"}
    assert _sante_finance(monde)["statut"] == "indetermine"


# ============================================================================================ 3. de bout en bout (acti
def test_du_planificateur_aux_quatre_mesures_au_wallboard_et_au_score_de_sante(monde, console, monkeypatch):
    _donner_bornes(monkeypatch)
    monde.activer("actif", noms=(CASH,))
    resume = monde.tour(1)[CASH]
    assert (resume["statut"], resume["erreurs"], resume["etapes"]) == ("ok", 0, 1), resume

    # -- UN événement, au bon rang, avec l'identifiant déterministe du créneau (le jour local, jamais l'horloge brute)
    (publie,) = _publies(monde)
    charge = publie["charge"]
    assert publie["producteur"] == pm.M5
    assert charge["date_reference"] == "2026-11-12" and charge["sequence"] == 1 and charge["statut"] == "CALCULE"
    assert charge["evenement_id"].startswith("m5-cash-libre-1-2026-11-12-")
    assert [t["sequence"] for t in _traces()] == [1]
    livraison = monde.propager()
    assert livraison["echecs"] == 0 and livraison["quarantaines"] == 0, livraison
    assert monde.bus.quarantaines() == [] and monde.bus.ecritures_hors_propriete() == []

    # -- les quatre mesures de M8 : la valeur exacte, calculée, à jour ------------------------------------------------
    assert _quatre(monde) == {i: ("calculee", v, "a_jour") for i, v in QUATRE.items()}

    # -- recoupement avec la PROPRE lecture de M5 (une autre voie que le constat) --------------------------------------
    lu = _etat_de_tresorerie(monde)
    # identifiant déterministe, sans horloge
    assert charge["evenement_id"] == f"m5-cash-libre-1-2026-11-12-{lu['cash_libre_id'][:16]}"
    assert charge["version_donnees"] == lu["cash_libre_id"]
    assert lu["cash_libre"] == QUATRE["m8_cash_libre_cad"]
    assert lu["solde"]["montant"] == QUATRE["m8_solde_tresorerie_cad"]
    composantes = {c["id"]: c["montant"] for c in lu["composantes"]}
    assert composantes["comptes_a_payer"] == QUATRE["m8_comptes_a_payer_cad"]
    assert composantes["taxes_a_remettre"] == QUATRE["m8_taxes_a_remettre_cad"]
    retranche = sum(Decimal(composantes[i]) for i in
                    ("taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves"))
    # la soustraction est celle du test
    assert Decimal(lu["solde"]["montant"]) - retranche == Decimal(QUATRE["m8_cash_libre_cad"])

    # -- les wallboards de la VRAIE console (admin) -------------------------------------------------------------------
    direction = {t["id"]: t for t in console.get("/api/wallboards/direction").json()["tuiles"]}
    assert direction["cash-libre"]["valeur"] == "27861.98"
    finance = {t["id"]: t for t in console.get("/api/wallboards/finance-operations").json()["tuiles"]}
    assert finance["solde"]["valeur"] == "37654.33" and finance["a-payer"]["valeur"] == "459.91"
    assert "PÉRIMÉE" not in console.get("/wallboards/direction").text

    # -- la vue exécutive (admin, relu en base) ------------------------------------------------------------------------
    vue = _vue_executive(monde, "2026-11-12")
    constat = vue["cash_libre"]["constat"]
    assert vue["cash_libre"]["statut"] == "lu" and constat["cash_libre_cad"] == "27861.98"
    assert constat["composantes"]["taxes_a_remettre"] == "1981.69" and vue["cash_libre"]["age"]["jours"] == 0

    # -- la composante « finance » du score de santé se remplit --------------------------------------------------------
    finance_sante = _sante_finance(monde)
    (indicateur,) = finance_sante["indicateurs"]
    assert (finance_sante["statut"], indicateur["metric_id"], indicateur["valeur"]) == (
        "determine", "m8_cash_libre_cad", "27861.98")
    assert indicateur["fraicheur"] == "a_jour" and indicateur["bornes"] == {"pire": "0", "cible": "50000"}
    assert Decimal(finance_sante["score"]) == Decimal("55.72")  # 27861.98 / 50000, borné [0,100], arrondi à 2 décimales

    # -- ni personne, ni texte du propriétaire, ni montant dans le journal ni dans l'événement ------------------------
    texte_journal = json.dumps(_journal(), ensure_ascii=False)
    for interdit in CONFIDENCES:
        assert interdit not in texte_journal, interdit
    texte_charge = json.dumps(charge, ensure_ascii=False)
    for interdit in ("Marc Tremblay", "brouillon de paie", "estimation du CPA", "relevé du prêt", "client-fictif",
                     "C-1", "gentek", "PO-1", "F-1001"):
        assert interdit not in texte_charge, interdit


def _etat_de_tresorerie(monde) -> dict:
    par_nom = {o.nom: o for o in monde.bus.departements[pm.M5].charger_outils()}
    with contexte.appele_par_appareil(pm.ADMIN):
        reponse = executer_atomique(par_nom["m5_etat_tresorerie"], {})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]["cash_libre"]


def _vue_executive(monde, aujourd_hui: str) -> dict:
    par_nom = {o.nom: o for o in monde.bus.departements[pm.M8].charger_outils()}
    with contexte.appele_par_appareil(pm.ADMIN):
        reponse = executer_atomique(par_nom["m8_lire_vue_executive"], {"aujourd_hui": aujourd_hui})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


# =============================================================================================== 4. idempotence par cr
def test_un_creneau_deja_pris_ne_republie_rien_meme_si_la_reservation_est_perdue(monde):
    monde.activer("actif", noms=(CASH,))
    monde.tour(1)
    (premier,) = _publies(monde)
    assert monde.tour(0)[CASH] == {"statut": "pas_echu"}
    for _ in range(3):  # une deuxième instance, un redémarrage : la réservation du créneau est perdue
        _rejouer_creneau()
        assert monde.tour(60)[CASH]["statut"] == "ok"
    assert [p["evenement_id"] for p in _publies(monde)] == [premier["evenement_id"]]
    assert [t["sequence"] for t in _traces()] == [1]
    monde.propager()
    assert _quatre(monde)["m8_cash_libre_cad"] == ("calculee", "27861.98", "a_jour")


def test_le_passage_suivant_du_meme_jour_sans_changement_ne_publie_rien_le_lendemain_publie_un_constat(monde):
    monde.activer("actif", noms=(CASH,))
    monde.tour(1)
    # 12 h plus tard : même jour local (midi), mêmes données -> `deja_constate`, aucun événement de plus
    assert monde.tour(INTERVALLE)[CASH]["statut"] == "ok"
    assert len(_publies(monde)) == 1
    # le lendemain : un nouveau jour de référence, donc un nouveau constat (rang 2), voulu
    assert monde.tour(INTERVALLE)[CASH]["statut"] == "ok"
    publies = _publies(monde)
    assert [p["charge"]["date_reference"] for p in publies] == ["2026-11-12", "2026-11-13"]
    assert [p["charge"]["sequence"] for p in publies] == [1, 2]
    assert len({p["evenement_id"] for p in publies}) == 2


def test_le_jour_de_reference_est_le_jour_local_de_l_entreprise_meme_en_soiree_quand_l_utc_a_change_de_jour(monde):
    """Un passage horaire de 00 h à 23 h locales (UTC-5) : de 19 h à 23 h, la date UTC est déjà le lendemain. Le constat
    est daté du jour LOCAL, donc un seul constat pour la journée (rien n'a changé), jamais un constat du lendemain."""
    monde.activer("actif", noms=(CASH,), intervalle_s=3600)
    monde.tour(1)
    for _ in range(23):
        assert monde.tour(3600)[CASH]["statut"] == "ok"
    assert [p["charge"]["date_reference"] for p in _publies(monde)] == ["2026-11-12"]
    assert monde.tour(3600)[CASH]["statut"] == "ok"  # minuit local : le jour change vraiment
    assert [p["charge"]["date_reference"] for p in _publies(monde)] == ["2026-11-12", "2026-11-13"]


def test_une_donnee_qui_change_le_meme_jour_publie_un_nouveau_constat_et_les_mesures_suivent(monde):
    from m5_financecore import registre

    monde.activer("actif", noms=(CASH,))
    monde.tour(1)
    monde.propager()
    with stockage.transaction():
        reg = m5_outils._registre_mouvements(None)
        registre.enregistrer_mouvement({"montant": Decimal("-1000.00"), "type_mouvement": "DECAISSEMENT",
                                        "horodatage": "2026-11-12T09:00:00-05:00", "classe_retention": "STANDARD",
                                        "source": "test-fictif"}, reg)
    assert monde.tour(INTERVALLE)[CASH]["statut"] == "ok"  # même jour local, nouvelle version des données
    assert [p["charge"]["sequence"] for p in _publies(monde)] == [1, 2]
    assert {p["charge"]["date_reference"] for p in _publies(monde)} == {"2026-11-12"}
    monde.propager()
    assert _quatre(monde)["m8_cash_libre_cad"] == ("calculee", "26861.98", "a_jour")
    assert _quatre(monde)["m8_solde_tresorerie_cad"] == ("calculee", "36654.33", "a_jour")


def test_le_constat_a_la_demande_et_le_constat_planifie_partagent_le_meme_registre_sans_doublon(monde):
    """L'admin touche « constater » (N3) puis le planificateur passe le même jour : un seul constat ; et l'inverse."""
    reponse = _a_la_demande(monde, "2026-11-12")
    assert reponse["ok"] is True and reponse["resultat"]["resultat"]["publie"] is True
    monde.activer("actif", noms=(CASH,))
    monde.tour(1)
    assert len(_publies(monde)) == 1 and [t["sequence"] for t in _traces()] == [1]  # le planifié a vu `deja_constate`
    # l'inverse, le lendemain : le planificateur d'abord, puis l'admin
    monde.tour(JOUR)
    assert [p["charge"]["date_reference"] for p in _publies(monde)] == ["2026-11-12", "2026-11-13"]
    suite = _a_la_demande(monde, "2026-11-13", cle="cle-2")
    assert suite["resultat"]["resultat"]["deja_constate"] is True and suite["resultat"]["resultat"]["publie"] is False
    assert len(_publies(monde)) == 2


# ======================================================================== 5. non calculable : publié tel quel=========
def test_sans_les_declarations_du_proprietaire_le_constat_est_non_calculable_et_les_mesures_aussi(monde, tmp_path,
                                                                                                 monkeypatch,
                                                                                                 console):
    import yaml

    vide = tmp_path / "department-m5-vide.yaml"
    vide.write_text(yaml.safe_dump({"configuration": {}}), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", vide)
    _donner_bornes(monkeypatch)
    monde.activer("actif", noms=(CASH,))
    assert monde.tour(1)[CASH]["statut"] == "ok"
    (publie,) = _publies(monde)
    assert publie["charge"]["statut"] == "NON_CALCULABLE" and publie["charge"]["manque"], publie["charge"]
    assert publie["charge"]["cash_libre_cad"] is None
    monde.propager()
    mesures = monde.mesures()
    assert mesures["m8_cash_libre_cad"]["statut"] == "non_calculable" and mesures["m8_cash_libre_cad"]["valeur"] is None
    assert _sante_finance(monde)["statut"] == "indetermine"  # pas de zéro inventé : le score le dit
    direction = {t["id"]: t for t in console.get("/api/wallboards/direction").json()["tuiles"]}
    assert direction["cash-libre"]["valeur"] in (None, "") or direction["cash-libre"]["statut"] != "calculee"


# ====================================================================== 6. la panne de M5 n'arrête pas les autres cons
def test_la_panne_de_m5_n_arrete_pas_les_autres_constats_puis_se_retablit(monde, monkeypatch):
    pm.semer_m2()
    monde.activer("actif", noms=(CASH, "m2.constat.pipeline"))

    def casse(*args, **kwargs):
        raise RuntimeError("panne simulée de M5")

    reel = m5_outils._constater_cash_libre
    monkeypatch.setattr(m5_outils, "_constater_cash_libre", casse)
    resume = monde.tour(1)
    assert (resume[CASH]["statut"], resume[CASH]["code"]) == ("erreur", "REJ-PLAN-DEFAUT-EXECUTEUR")
    assert resume["m2.constat.pipeline"]["statut"] == "ok"
    assert monde.nombre_publie() == {"m2.pipeline_constate": 1}  # le constat de M2 est parti malgré M5
    assert _traces() == []  # rien de demi-écrit côté M5
    with stockage.transaction() as cnx:
        vue = {v["executeur"]: v for v in etat.vue(cnx)}
    assert vue[CASH]["dernier_statut"] == "erreur" and vue[CASH]["echecs_24h"] == 1

    monkeypatch.setattr(m5_outils, "_constater_cash_libre", reel)
    resume = monde.tour(INTERVALLE)
    assert resume[CASH]["statut"] == "ok"
    monde.propager()
    assert _quatre(monde)["m8_cash_libre_cad"] == ("calculee", "27861.98", "a_jour")
    assert monde.mesures()["m8_pipeline_leads_ouverts"]["statut"] == "calculee"


def test_un_refus_rendu_par_l_outil_est_une_erreur_visible_avec_son_code(monde, monkeypatch):
    monkeypatch.setattr(m5_outils, "_stockage_durable_actif", False)
    monde.activer("actif", noms=(CASH,))
    resume = monde.tour(1)[CASH]
    assert (resume["statut"], resume["code"], resume["erreurs"]) == ("erreur", "REJ-CONSTAT-STOCKAGE-NON-DURABLE", 1)
    assert monde.nombre_publie() == {} and _traces() == []


# ======================================================================== 7. la variante n'est pas une porte dérobée
def test_un_agent_ne_peut_pas_declencher_la_variante_ni_publier_par_elle(monde):
    """Le N2 d'un agent est automatique : sans le contrôle de l'acteur système, la variante contournerait la validation
    humaine du N3. Refusée AVANT la lecture de tout registre, sans trace ni événement."""
    capacites = Capacites({pm.M5: monde.bus.departements[pm.M5]}, stockage.transaction)
    reponse = capacites.appeler(OUTIL_PLANIFIE, {"aujourd_hui": "2026-11-12"})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT"
    assert monde.nombre_publie() == {} and _traces() == []


def test_un_appareil_admin_ne_peut_pas_non_plus_declencher_la_variante(monde):
    par_nom = {o.nom: o for o in monde.bus.departements[pm.M5].charger_outils()}
    assert par_nom[OUTIL_PLANIFIE].roles_appareil == frozenset()  # aucun droit d'appareil ajouté
    with contexte.appele_par_appareil(pm.ADMIN):
        reponse = executer_atomique(par_nom[OUTIL_PLANIFIE], {"aujourd_hui": "2026-11-12"})
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT"
    assert monde.nombre_publie() == {} and _traces() == []


def test_la_reponse_de_la_variante_ne_porte_aucun_montant(monde):
    """Appelée dans un tour du planificateur, elle publie, mais ne rend à l'appelant que l'en-tête et le statut."""
    from opsys import service_acteur_systeme as systeme

    par_nom = {o.nom: o for o in monde.bus.departements[pm.M5].charger_outils()}
    with systeme.contexte_planificateur():
        reponse = executer_atomique(par_nom[OUTIL_PLANIFIE], {"aujourd_hui": "2026-11-12"})
    corps = reponse["resultat"]["resultat"]
    assert set(corps) == {"deja_constate", "publie", "constat", "mention"}
    assert set(corps["constat"]) == {
        "evenement_id", "sequence", "date_reference", "version_donnees", "statut", "manque"}
    texte = json.dumps(corps, ensure_ascii=False)
    for interdit in CONFIDENCES + ("cash_libre_cad", "montant", "lecture"):
        assert interdit not in texte, interdit
    assert corps["publie"] is True and len(_publies(monde)) == 1


def test_la_variante_est_n2_agent_seulement_et_l_outil_a_la_demande_reste_n3_pour_l_admin(monde):
    par_nom = {o.nom: o for o in monde.bus.departements[pm.M5].charger_outils()}
    variante, a_la_demande = par_nom[OUTIL_PLANIFIE], par_nom[OUTIL_A_LA_DEMANDE]
    assert (variante.autonomie.value, variante.niveau_effectif, variante.roles_appareil) == (
        "T1", Niveau.N2, frozenset())
    assert (a_la_demande.autonomie.value, a_la_demande.niveau_effectif, a_la_demande.roles_appareil) == (
        "T1", Niveau.N3, frozenset({"admin"}))
    assert not variante.frontiere_humaine


# ============================================================== 8. aucune écriture comptable, aucun mouvement, aucun p
def test_le_constat_planifie_n_ecrit_ni_mouvement_ni_facture_ni_grand_livre_ni_comptes_a_payer(monde):
    def registres():
        with stockage.transaction():
            return {nom: list(stockage.maillons(pm.M5, nom)) for nom in
                    ("principal", "factures", "comptes_a_payer", "grand_livre", "reception_enregistree")}

    avant = registres()
    monde.activer("actif", noms=(CASH,))
    monde.tour(1)
    assert registres() == avant
    with stockage.transaction() as cnx:
        types = {r[0] for r in cnx.execute(select(__import__("opsys.stockage.schema", fromlist=["x"])
                                                  .EVENEMENTS_SORTANTS.c.type_evenement)).all()}
    assert types == {TYPE}, "le seul événement est le constat : aucun paiement, aucune remise, aucune écriture"


# ================================================================================ 9. la fraîcheur à travers la journée
def test_la_fraicheur_des_quatre_mesures_a_travers_deux_jours_de_passages_reguliers(monde, monkeypatch):
    """Caractérisation (pas un souhait) : M8 date un constat de M5 du DÉBUT du jour de référence en UTC, la fenêtre
    est de 24 h et le constat change de jour à minuit LOCAL (UTC-5 en novembre). Les mesures sont donc à jour en journée
    et PÉRIMÉES en début de soirée locale (de 19 h à minuit), même quand tous les passages réussissent. Une fenêtre
    déclarée par le propriétaire (48 h) supprime cet intervalle. Voir PLANIFICATION.md §9 et le document de M5."""
    monde.activer("actif", noms=(CASH,))
    etats: list[tuple[str, str]] = []
    # le départ est 00:00:30 local (05:00:30 UTC) ; on observe toutes les 3 heures pendant 36 heures
    monde.tour(1)
    for _ in range(12):
        monde.propager()
        local = (dt.datetime.fromtimestamp(monde.horloge(), dt.UTC) - dt.timedelta(hours=5)).strftime("%d %H:%M")
        etats.append((local, _quatre(monde)["m8_cash_libre_cad"][2]))
        monde.tour(3 * 3600)
    fraicheurs = dict(etats)
    assert fraicheurs["12 00:00"] == "a_jour" and fraicheurs["12 12:00"] == "a_jour"
    assert fraicheurs["12 18:00"] == "a_jour"
    assert fraicheurs["12 21:00"] == "perime"  # le constat du 12 novembre a plus de 24 h (début du jour UTC)
    assert fraicheurs["13 00:00"] == "a_jour"  # le constat du 13 est publié au premier passage du nouveau jour local


def test_une_fenetre_de_48_h_declaree_par_le_proprietaire_garde_les_mesures_a_jour_toute_la_journee(monde, monkeypatch):
    """Le remède qui ne touche ni au catalogue ni au code : le propriétaire déclare 48 h pour les quatre mesures
    (`configuration.fraicheur_mesures_s` de M8) ; l'admin règle l'intervalle à un jour à l'activation. Un passage par
    jour local suffit, et aucune heure n'est périmée sur deux jours (un constat par jour local)."""
    reel = m8_outils._configuration
    monkeypatch.setattr(m8_outils, "_configuration", lambda: {
        **reel(), "fraicheur_mesures_s": dict.fromkeys(QUATRE, 2 * JOUR)})
    monde.activer("actif", noms=(CASH,), intervalle_s=JOUR)
    monde.tour(1)
    fraicheurs = []
    for _ in range(16):
        monde.propager()
        fraicheurs.append(_quatre(monde)["m8_cash_libre_cad"][2])
        monde.tour(3 * 3600)
    assert set(fraicheurs) == {"a_jour"}
    assert [p["charge"]["date_reference"] for p in _publies(monde)] == ["2026-11-12", "2026-11-13", "2026-11-14"]
