"""Graphe d'impacts M9.2 sur de VRAIES captures : « rupture de matériau » à travers M2, M3, M4, M5, M6 et M8.

Un seul scénario cohérent (même lead, même devis, même chantier, même WCT, même matériau) est monté par les outils et
le bus réels des départements (fixtures `m9_producteurs_a.py` et `m9_producteurs_b.py`, non modifiées) :

* M1 qualifie le lead (service « ravalement ») ; M2 l'ingère puis un vendeur le qualifie
  (outil `m2_transitionner_statut`) ;
* M3 accepte le devis `DEVIS-B1` (40 pi du matériau) ; M6 le consomme et réserve, puis publie « matériel prêt » ; M4 en
  fait une intervention (lead et devis portés), que l'admin cédule, confirme (position) et date ;
* le chantier se termine (WCT, variance) ; M5 en calcule la rentabilité ; un bon de commande est reçu (M6 → M5) ;
* la RUPTURE : 120 des 150 pi du matériau passent au rebut (`m6_transferer_stock`) ; M6 déclare alors la réservation du
  devis « partielle », avec la ligne manquante du matériau.

Huit lectures sont capturées par `m9_capturer_producteur` (admin console, port privé). `REGLES` est la liste de règles
proposée : chacune cite le champ exact du producteur ; `LIMITES` dit ce que ce champ ne permet pas. Les tests
construisent le graphe depuis la chaîne de captures RÉELLE (`graphe_impacts.construire`) et propagent.

Constat central, prouvé plus bas : aucune ligne d'aucune lecture ne porte à la fois un matériau et un devis, un chantier
ou un lead. Le matériau n'est donc PAS un nœud du graphe : l'objet le plus en amont que les captures justifient est le
devis en rupture (M6 : réservation `partielle`). Aucune relation n'est inventée.
Données fictives (`fictif: true`).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import m2_revenue_crm.outils as m2_outils
import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import graphe_impacts as gi
from m9_strategic_intelligence import relations_catalogue as rc

from opsys import identite, stockage

_TESTS = Path(__file__).resolve().parent


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, _TESTS / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


A = _charger("m9_producteurs_a")
B = _charger("m9_producteurs_b")

FICTIF = True
LEAD, DEVIS, CHANTIER, WCT, MATERIAU = B.LEAD_ID, B.DEVIS_ID, B.CHANTIER_ID, B.WCT_ID, B.MATERIAU
PO = "PO-G1"
M2, M3, M4, M5, M6, M8 = (
    "m02-revenue-crm", "m03-estimation", "m04-field-ops", "m05-financecore", "m06-material-control", "m08-analytics",
)
CONNAISSANCE = "2026-10-28T13:00:00Z"
RESULTAT = "resultat.resultat"

# Les règles et leurs limites vivent dans le catalogue versionné (src) : ce test les prouve sur de vraies captures.
REGLES = rc.REGLES
LIMITES = rc.LIMITES
ARGUMENTS = {
    "m2.leads": {"horodatage": "2026-10-28T12:00:00Z"},
    "m3.ecarts": {"devis_id": DEVIS},
    "m4.interventions": {},
    "m4.cedule_semaine": {"debut_semaine": A.LUNDI},
    "m5.rentabilite_chantier": {},
    "m5.comptes_a_payer": {},
    "m6.disponibilite": {},
    "m8.mesures_chantier": {"wct_id": WCT},
}


# -- le monde réel -------------------------------------------------------------------------------------------------
def _instant(rang: int) -> str:
    return f"2026-10-28T12:00:{rang:02d}Z"


def _monter_scenario(base: Path, mp: pytest.MonkeyPatch) -> dict:
    B.installer_base(base, mp)
    m2_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        for personne, nom, secret in (("marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234"),
                                      ("lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345")):
            identite.creer_personne(cnx, personne, nom, secret, ["employee"])
    B.declarer_m5(base, mp)
    A.declarer_equipes(base)
    A.declarer_meteo(base)
    B.prix_au_livre_m6()
    m3, m4, m6 = (A.outils_departement(d) for d in (A.M3, A.M4, A.M6))
    m2 = A.outils_departement(M2)
    A.m6_recevoir(m6, MATERIAU, 150.0, "PO-G0")
    A.m3_creer_devis(m3, DEVIS, LEAD)
    lead = B.charge_lead_qualifie(LEAD)
    lead["lead"]["service"] = "ravalement"
    B.publier("m1.lead_qualifie", B.M1, lead, evenement_id=f"m1-lead-qualifie-{LEAD}")
    B.livrer((M2,))
    A.geste(m2, "m2_transitionner_statut", {
        "lead_id": LEAD, "statut_cible": "qualifie", "horodatage": "2026-09-18T12:00:00-04:00",
        "owner": "vendeur.fictif",
        "prochaine_action": {"description": "Appeler le client", "echeance": "2026-09-20T09:00:00-04:00"}})
    B.publier("m3.devis_accepte", "m03-estimation", B.charge_devis_accepte())
    B.livrer((B.M5, M2, M4, M6, M3))
    intervention = A.lire_outil(m4, "m4_lister_interventions", {})[0]["intervention_id"]
    A.geste(m4, "m4_confirmer_localisation", {
        "chantier_id": LEAD, "action": "confirmee", "horodatage": A.HORODATAGE_PLAN, "confirme_par": "admin.fictif",
        "adresse": {"numero_municipal": "10", "odonyme": "rue Fictive", "municipalite": "Repentigny"},
        "source": "manuel", "motif": "", "latitude_microdegres": 45742000, "longitude_microdegres": -73450000})
    plan = A.geste(m4, "m4_proposer_cedule", {"horodatage": A.HORODATAGE_PLAN})["plan_id"]
    A.geste(m4, "m4_appliquer_cedule",
            {"plan_id": plan, "horodatage": A.HORODATAGE_PLAN, "confirme_par": "admin.fictif"})
    A.geste(m4, "m4_confirmer_dates_cedule", {"plan_id": plan, "calendrier": {"0": A.LUNDI}, "revision_attendue": 0})
    # le chantier est terminé : M4 publie le WCT (porte l'intervention réelle), M6 la variance
    wct = B.charge_wct()
    wct["intervention_id"] = intervention
    B.publier("m4.travaux_termines", "m04-field-ops", wct)
    variance = B.charge_variance()
    B.publier("m6.variance_chantier", "m06-material-control", variance, evenement_id=variance["evenement_id"])
    B.livrer((B.M5, M2, M3, M6, M8))
    # un bon de commande reçu pour ce chantier (M6 → M5 : comptes à payer)
    reception = B._charge_reception("m6-reception-PO-G1-0001", PO, "40", "2026-09-15T09:00:00-04:00")
    reception["chantier_id"] = CHANTIER
    reception["lignes"][0]["materiau_id"] = MATERIAU
    B.publier("m6.reception_enregistree", "m06-material-control", reception, evenement_id=reception["evenement_id"])
    B.livrer((B.M5,))
    # LA RUPTURE : 120 des 150 pi passent au rebut ; la réservation du devis devient « partielle »
    A.geste(m6, "m6_transferer_stock", {
        "transfert_id": "TR-G1", "materiau_id": MATERIAU, "quantite": 120.0, "de": {"type": "inconnu"},
        "vers": {"type": "rebut"}, "motif": "bris fictif", "horodatage": "2026-10-07T09:00:00-04:00"})
    capacites = B.capacites(M2, M3, M4, M5, M6, M8)
    index = {}
    for rang, (lecture_id, arguments) in enumerate(ARGUMENTS.items(), start=1):
        reponse = B.capturer(capacites, B.ADMIN, lecture_id, arguments, _instant(rang))
        capture = reponse["resultat"]["capture"]
        assert reponse["ok"] is True and capture["verdict"] == "ACCEPTEE" and capture["complete"] is True, reponse
        index[lecture_id] = capture["index"]
    chaine = B.captures_stockees()
    # Une VRAIE capture refusée par le producteur (un mardi n'est pas un lundi), conservée comme manque. Hors `chaine`
    # (instantané des huit lectures acceptées) : le test du refus la substitue à la cédule.
    reponse = B.capturer(capacites, B.ADMIN, "m4.cedule_semaine", {"debut_semaine": "2026-11-03"}, _instant(30))
    refusee = reponse["resultat"]["capture"]
    assert refusee["verdict"] == "REFUSEE" and refusee["code"] == "REJ-CONTRAT-INVALIDE", reponse
    return {"intervention": intervention, "plan": plan, "index": index, "chaine": chaine,
            "refusee": B.captures_stockees()[refusee["index"]]}


@pytest.fixture(scope="module")
def monde(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        monde = _monter_scenario(tmp_path_factory.mktemp("graphe-reel"), mp)
        try:
            yield monde
        finally:
            m2_outils.reinitialiser_registre()
            B.desinstaller_base()


def _graphe(chaine, regles=REGLES, connaissance=CONNAISSANCE) -> dict:
    return gi.construire(chaine, regles, connaissance=connaissance)


def _cles(document) -> set[str]:
    """Toutes les clés d'objet d'une réponse, à n'importe quelle profondeur."""
    if isinstance(document, dict):
        return set(document) | {cle for valeur in document.values() for cle in _cles(valeur)}
    if isinstance(document, list):
        return {cle for valeur in document for cle in _cles(valeur)}
    return set()


def _page(monde, lecture_id) -> dict:
    return monde["chaine"][monde["index"][lecture_id]]["pages"][0]


def _atteints(propagation) -> dict:
    return {(i["objet"]["kind"], i["objet"]["id"]): i["distance"] for i in propagation["impacts"]}


# =====================================================================================================
# 0. Le scénario : la rupture est bien déclarée par le producteur
# =====================================================================================================
def test_la_rupture_est_declaree_par_m6_au_niveau_de_la_reservation_du_devis(monde):
    page = _page(monde, "m6.disponibilite")
    assert cs.extraire(page, f"{RESULTAT}.reservations_actives[*].statut") == ["partiel"]
    assert cs.extraire(page, f"{RESULTAT}.reservations_actives[*].devis_id") == [DEVIS]
    assert cs.extraire(page, f"{RESULTAT}.reservations_actives[*].chantier_id") == [CHANTIER]
    assert cs.extraire(page, f"{RESULTAT}.reservations_actives[*].lignes_manquantes[*].materiau_id") == [MATERIAU]
    (article,) = cs.extraire(page, f"{RESULTAT}.articles[*]")
    assert (article["materiau_id"], article["en_main"], article["reserve"], article["disponible"]) == (
        MATERIAU, "30", "30", "0")
    assert cs.valider_chaine(monde["chaine"]) == (True, "")
    assert [m["lecture_id"] for m in monde["chaine"]] == list(ARGUMENTS)


# =====================================================================================================
# 1. Chaque règle est justifiée par des lignes réelles qui portent les DEUX champs
# =====================================================================================================
def test_chaque_regle_cite_des_lignes_reelles_portant_ses_deux_champs(monde):
    assert {r.id for r in REGLES} == set(LIMITES), "chaque règle dit sa limite"
    assert len({r.id for r in REGLES}) == len(REGLES)
    for regle in REGLES:
        assert regle.lecture_id in cat.PAR_ID and regle.lecture_id in monde["index"], regle.id
        if regle.id.startswith("m4_page_"):
            continue  # forme paginée de M4 : prouvée par test_forme_paginee_de_m4_donne_les_memes_aretes
        page = _page(monde, regle.lecture_id)
        lignes = cs.extraire(page, regle.lignes)
        assert lignes, f"{regle.id} : aucune ligne à {regle.lignes}"
        for ligne in lignes:
            assert isinstance(ligne, dict), regle.id
            for champ in (regle.de_champ, regle.vers_champ):
                assert type(ligne.get(champ)) is str and ligne[champ], f"{regle.id} : {champ} absent de la ligne"


# =====================================================================================================
# 2. Le graphe réel : arêtes, preuves (capture, empreinte, ligne), règles actives
# =====================================================================================================
def test_graphe_construit_depuis_la_chaine_reelle_avec_preuves(monde):
    chaine = monde["chaine"]
    graphe = _graphe(chaine)
    assert graphe["regles_inconnues"] == []
    assert {r["regle"] for r in graphe["regles_actives"]} == {r.id for r in REGLES}
    assert all(r["lignes_ecartees"] == 0 for r in graphe["regles_actives"])
    refs = {n["ref"] for n in graphe["noeuds"]}
    assert refs == {
        f"devis:{DEVIS}", f"chantier:{CHANTIER}", f"intervention:{monde['intervention']}", f"lead:{LEAD}",
        f"wct:{WCT}", "equipe:eq-a", f"rentabilite:{CHANTIER}", f"po:{PO}", "personne:vendeur.fictif",
    }
    par_regle = {r.id: r for r in REGLES}
    for arete in graphe["aretes"]:
        regle = par_regle[arete["regle"]]
        preuve = arete["preuve"]
        capture = chaine[preuve["capture_index"]]
        assert capture["hash_maillon"] == preuve["capture_hash"] and capture["lecture_id"] == regle.lecture_id
        ligne = cs.extraire(capture["pages"][preuve["page"]], preuve["chemin"])[preuve["ligne"]]
        assert f"{regle.de_kind}:{ligne[regle.de_champ]}" == arete["de"]
        assert f"{regle.vers_kind}:{ligne[regle.vers_champ]}" == arete["vers"]
    assert _graphe(chaine)["graphe_id"] == graphe["graphe_id"], "reproductible"
    assert _graphe(chaine, connaissance="2026-10-28T11:00:00Z")["aretes"] == [], "rien n'était connu avant les captures"


# =====================================================================================================
# 3. Propagation depuis le devis en rupture : chantier, WCT, lead, M5
# =====================================================================================================
def test_propagation_du_devis_en_rupture_atteint_chantier_wct_lead_et_finances(monde):
    chaine = monde["chaine"]
    graphe = _graphe(chaine)
    resultat = gi.propager(graphe, "devis", DEVIS, profondeur_max=4)
    atteints = _atteints(resultat)
    assert atteints == {
        ("chantier", CHANTIER): 1, ("intervention", monde["intervention"]): 1, ("wct", WCT): 1,
        ("lead", LEAD): 2, ("equipe", "eq-a"): 2, ("rentabilite", CHANTIER): 2, ("po", PO): 2,
        ("personne", "vendeur.fictif"): 3,
    }
    assert resultat["complet"] is True and resultat["regles_inconnues_pertinentes"] == []
    assert all(set(i) == {"objet", "distance", "chemin"} for i in resultat["impacts"]), "aucune quantité"
    par_id = {a["id"]: a for a in graphe["aretes"]}
    lead = next(i for i in resultat["impacts"] if i["objet"] == {"kind": "lead", "id": LEAD})
    premier, second = (par_id[e] for e in lead["chemin"])
    assert premier["regle"] == "m4_devis_intervention" and second["regle"] in {
        "m4_intervention_lead", "m4_cedule_intervention_lead"}
    for impact in resultat["impacts"]:  # chaque saut cite une capture réelle de la chaîne
        for identifiant in impact["chemin"]:
            preuve = par_id[identifiant]["preuve"]
            assert chaine[preuve["capture_index"]]["hash_maillon"] == preuve["capture_hash"]
    # M5 est atteint par DEUX preuves indépendantes (M6 puis M5 pour le chantier) ; le lead par M4 (liste et cédule)
    regles_du_graphe = {a["regle"] for a in graphe["aretes"]}
    assert {"m6_reservation_devis_chantier", "m5_devis_chantier"} <= regles_du_graphe
    # le lead n'est PAS atteint depuis M3, M5 ni M8 : seulement par M4
    sans_m4 = _graphe([c for c in chaine if c["departement"] != M4])
    assert ("lead", LEAD) not in _atteints(gi.propager(sans_m4, "devis", DEVIS))


def test_propagation_depuis_le_lead_et_le_chantier_suit_le_sens_declare(monde):
    graphe = _graphe(monde["chaine"])
    depuis_lead = _atteints(gi.propager(graphe, "lead", LEAD))
    assert depuis_lead == {("personne", "vendeur.fictif"): 1}, "le lead ne remonte pas à son devis (sens de->vers)"
    depuis_chantier = _atteints(gi.propager(graphe, "chantier", CHANTIER))
    assert depuis_chantier == {("rentabilite", CHANTIER): 1, ("po", PO): 1}


# =====================================================================================================
# 4. Liens NON justifiés : le matériau n'est relié à rien, rien n'est inventé
# =====================================================================================================
def test_aucune_ligne_ne_porte_a_la_fois_un_materiau_et_un_devis_ou_un_chantier(monde):
    page = _page(monde, "m6.disponibilite")
    (reservation,) = cs.extraire(page, f"{RESULTAT}.reservations_actives[*]")
    assert set(reservation) == {"chantier_id", "devis_id", "lignes_manquantes", "statut"}
    assert "materiau_id" not in reservation, "la réservation ne nomme pas le matériau au niveau où elle nomme le devis"
    (manquante,) = cs.extraire(page, f"{RESULTAT}.reservations_actives[*].lignes_manquantes[*]")
    assert "materiau_id" in manquante and not {"devis_id", "chantier_id"} & set(manquante)
    (article,) = cs.extraire(page, f"{RESULTAT}.articles[*]")
    assert not {"devis_id", "chantier_id", "reservations"} & set(article)
    # M3 : le matériau est dans materiaux.lignes[*] (sans wct ni devis), M8 dans mesures[*].entrees (sans devis)
    for ligne in cs.extraire(_page(monde, "m3.ecarts"), f"{RESULTAT}[*].materiaux.lignes[*]"):
        assert "materiau" in ligne and not {"wct_id", "devis_id", "chantier_id"} & set(ligne)
    entrees = [e for e in cs.extraire(_page(monde, "m8.mesures_chantier"), "resultat.mesures[*].entrees")
               if "materiau" in e]
    assert entrees and all("devis_id" not in e and "wct_id" not in e for e in entrees)
    # M5 ne nomme aucun matériau : ni la rentabilité ni les comptes à payer
    for lecture_id in ("m5.rentabilite_chantier", "m5.comptes_a_payer"):
        assert not {k for k in _cles(_page(monde, lecture_id)) if "materiau" in k}, lecture_id


def test_le_materiau_n_est_pas_un_noeud_du_graphe_et_une_regle_inventee_ne_cree_rien(monde):
    chaine = monde["chaine"]
    graphe = _graphe(chaine)
    assert not any(n["kind"] == "materiau" for n in graphe["noeuds"])
    with pytest.raises(ValueError, match="REJ-GRAPHE-NOEUD-INCONNU"):
        gi.propager(graphe, "materiau", MATERIAU)  # inconnu, jamais « aucun impact »
    # Une règle « matériau → devis » sur la liste d'articles de M6 est rejetée ligne à ligne : devis_id n'y est pas.
    inventee = gi.Regle("materiau_devis_invente", "utilise_par", "m6.disponibilite", f"{RESULTAT}.articles[*]",
                        "materiau", "materiau_id", "devis", "devis_id")
    avec = _graphe(chaine, (*REGLES, inventee))
    active = next(r for r in avec["regles_actives"] if r["regle"] == "materiau_devis_invente")
    assert active["aretes"] == 0 and active["lignes_ecartees"] == 1
    assert not any(n["kind"] == "materiau" for n in avec["noeuds"])
    assert {a["id"] for a in avec["aretes"]} == {a["id"] for a in graphe["aretes"]}


def test_m3_m5_m8_ne_portent_pas_le_lead_et_m2_ne_porte_pas_le_devis(monde):
    for lecture_id in ("m3.ecarts", "m5.rentabilite_chantier", "m5.comptes_a_payer", "m8.mesures_chantier",
                       "m6.disponibilite"):
        assert "lead_id" not in _cles(_page(monde, lecture_id)), lecture_id
    for lecture_id in ("m4.interventions", "m4.cedule_semaine", "m2.leads"):
        assert "lead_id" in _cles(_page(monde, lecture_id)), lecture_id
    assert not {k for k in _cles(_page(monde, "m2.leads")) if "devis" in k}, "M2 ne dit que le statut du lead"
    assert not {k for k in _cles(_page(monde, "m4.cedule_semaine")) if "devis" in k}, "la cédule n'a pas le devis"
    assert "devis_id" in _cles(_page(monde, "m4.interventions")), "seule la liste M4 relie intervention et devis"
    # Sans la liste M4, le lead reste relié à son intervention (cédule) mais plus au devis : le chemin est inconnu.
    sans_liste = _graphe([c for c in monde["chaine"] if c["lecture_id"] != "m4.interventions"])
    atteints = _atteints(gi.propager(sans_liste, "devis", DEVIS))
    assert ("lead", LEAD) not in atteints and ("wct", WCT) in atteints


# =====================================================================================================
# 5. Lecture requise absente ou refusée : règle inconnue, propagation non complète
# =====================================================================================================
def test_lecture_absente_rend_la_regle_inconnue_et_la_propagation_incomplete(monde):
    chaine = [c for c in monde["chaine"] if c["lecture_id"] not in ("m4.interventions", "m5.rentabilite_chantier")]
    graphe = _graphe(chaine)
    inconnues = {(r["regle"], r["raison"]) for r in graphe["regles_inconnues"]}
    assert inconnues == {
        ("m4_devis_intervention", "ABSENTE"), ("m4_intervention_lead", "ABSENTE"),
        ("m4_page_devis_intervention", "ABSENTE"), ("m4_page_intervention_lead", "ABSENTE"),
        ("m5_devis_chantier", "ABSENTE"), ("m5_chantier_rentabilite", "ABSENTE"),
    }
    resultat = gi.propager(graphe, "devis", DEVIS)
    atteints = _atteints(resultat)
    assert ("rentabilite", CHANTIER) not in atteints, "aucune arête n'est supposée sans sa lecture"
    assert ("chantier", CHANTIER) in atteints and ("wct", WCT) in atteints
    assert resultat["complet"] is False
    assert {r["regle"] for r in resultat["regles_inconnues_pertinentes"]} >= {"m4_devis_intervention"}
    # sans AUCUNE capture, le devis n'est pas un objet connu : refus, pas « aucun impact »
    with pytest.raises(ValueError, match="REJ-GRAPHE-NOEUD-INCONNU"):
        gi.propager(_graphe([]), "devis", DEVIS)


def test_lecture_refusee_par_le_producteur_rend_la_regle_inconnue(monde):
    # La VRAIE capture refusée (monde["refusee"]) remplace la cédule : le refus est un manque conservé.
    refusee = monde["refusee"]
    assert refusee["verdict"] == "REFUSEE" and refusee["complete"] is False and refusee["lecture_id"] == (
        "m4.cedule_semaine")
    chaine = [c for c in monde["chaine"] if c["lecture_id"] != "m4.cedule_semaine"] + [refusee]
    graphe = _graphe(chaine)
    inconnues = {(r["regle"], r["raison"]) for r in graphe["regles_inconnues"]}
    assert inconnues == {("m4_cedule_intervention_lead", "REFUSEE"), ("m4_cedule_intervention_equipe", "REFUSEE")}
    assert not any(a["regle"].startswith("m4_cedule") for a in graphe["aretes"])
    resultat = gi.propager(graphe, "devis", DEVIS)
    atteints = _atteints(resultat)
    assert ("equipe", "eq-a") not in atteints and ("lead", LEAD) in atteints, "le lead tient encore par la liste M4"
    assert resultat["complet"] is False, "l'équipe est inconnue : l'absence d'impact sur elle n'est pas affirmée"
    assert {r["raison"] for r in resultat["regles_inconnues_pertinentes"]} == {"REFUSEE"}


# =====================================================================================================
# 6. Forme paginée de M4 (taille_page) : mêmes arêtes que la liste v1
# =====================================================================================================
def test_forme_paginee_de_m4_donne_les_memes_aretes(monde):
    """La forme {interventions, page} est celle que documente M4 (prouvée en réel par test_m9_producteurs_a) ; ici, les
    lignes RÉELLES de la liste v1 y sont rangées pour vérifier que les règles `m4_page_*` lisent la même chose."""
    v1 = next(c for c in monde["chaine"] if c["lecture_id"] == "m4.interventions")
    lignes = v1["pages"][0]["resultat"]
    paginee = {"ok": True, "resultat": {"interventions": lignes, "page": {"total": len(lignes), "reste": 0,
                                                                     "curseur_suivant": None}}}
    capture = cs.construire(
        cat.PAR_ID["m4.interventions"], {"taille_page": 5}, [paginee], recu_a="2026-10-28T12:00:40Z", reference=None,
        index=len(monde["chaine"]), hash_precedent=monde["chaine"][-1]["hash_maillon"],
        dernier_recu_a=monde["chaine"][-1]["recu_a"], max_octets=262_144)
    assert capture["verdict"] == "ACCEPTEE" and capture["complete"] is True, capture
    graphe = _graphe([c for c in monde["chaine"] if c["lecture_id"] != "m4.interventions"] + [capture])
    par_regle = {}
    for arete in graphe["aretes"]:
        par_regle.setdefault(arete["regle"], set()).add((arete["de"], arete["vers"]))
    assert par_regle["m4_page_devis_intervention"] == {(f"devis:{DEVIS}", f"intervention:{monde['intervention']}")}
    assert par_regle["m4_page_intervention_lead"] == {(f"intervention:{monde['intervention']}", f"lead:{LEAD}")}
    atteints = _atteints(gi.propager(graphe, "devis", DEVIS))
    assert ("lead", LEAD) in atteints and ("intervention", monde["intervention"]) in atteints


# =====================================================================================================
# 7. Les outils m9_apercu_graphe_impacts et m9_propager_impacts sur le monde réel (admin seulement)
# =====================================================================================================
def test_outils_graphe_sur_le_monde_reel_admin_seulement(tmp_path, monkeypatch):
    try:
        monde = _monter_scenario(tmp_path, monkeypatch)
        assert monde["chaine"]
        cap = B.capacites(M2, M3, M4, M5, M6, M8)
        connaissance = "2026-10-28T13:00:00Z"

        def appel(nom, arguments, identite_appelante=B.ADMIN):
            if identite_appelante is None:
                return cap.appeler(nom, arguments)
            with B.contexte.appele_par_appareil(identite_appelante):
                return cap.appeler(nom, arguments)

        apercu = appel("m9_apercu_graphe_impacts", {"connaissance": connaissance})
        assert apercu["ok"] is True and apercu["resultat"]["accepte"] is True, apercu
        res = apercu["resultat"]
        assert res["total_aretes"] > 0 and res["noeuds_par_type"]["devis"] == 1
        # La VRAIE capture refusée (cédule d'un mardi) est conservée : ses deux règles sont inconnues, pas effacées.
        assert {(r["regle"], r["raison"]) for r in res["regles_inconnues"]} == {
            ("m4_cedule_intervention_lead", "REFUSEE"), ("m4_cedule_intervention_equipe", "REFUSEE")}
        assert any("materiau" in m for m in res["manques_connus"])
        propage = appel(
            "m9_propager_impacts", {"connaissance": connaissance, "kind": "devis", "identifiant": DEVIS}
        )["resultat"]
        assert propage["accepte"] is True and propage["complet"] is False and propage["graphe_id"] == res["graphe_id"]
        assert {i["objet"]["kind"] for i in propage["impacts"]} >= {"chantier", "wct", "lead"}
        for impact in propage["impacts"]:
            for arete_id in impact["chemin"]:
                assert propage["aretes_citees"][arete_id]["preuve"]["capture_hash"]
        # un matériau n'est pas un objet connu : refus nommé, jamais « aucun impact »
        refus = appel(
            "m9_propager_impacts", {"connaissance": connaissance, "kind": "materiau", "identifiant": MATERIAU}
        )
        assert refus["ok"] is False or refus["resultat"].get("accepte") is False
        assert "REJ-GRAPHE-NOEUD-INCONNU" in str(refus)
        # connaissance antérieure aux captures : graphe vide, tout est inconnu et le devis aussi
        avant = appel(
            "m9_propager_impacts", {"connaissance": "2026-10-28T11:00:00Z", "kind": "devis", "identifiant": DEVIS}
        )
        assert "REJ-GRAPHE-NOEUD-INCONNU" in str(avant)
        # relation hors catalogue, identité non admin, voie d'agent : refusées
        assert "REJ-GRAPHE-RELATION" in str(appel(
            "m9_propager_impacts",
            {"connaissance": connaissance, "kind": "devis", "identifiant": DEVIS, "relations": ["inventee"]}))
        vendeur = B.IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
        assert appel("m9_apercu_graphe_impacts", {"connaissance": connaissance}, vendeur)["ok"] is False
        assert appel("m9_apercu_graphe_impacts", {"connaissance": connaissance}, None)["ok"] is False
    finally:
        m2_outils.reinitialiser_registre()
