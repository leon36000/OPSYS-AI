"""PLAN T4.6 (M2.11) — le vendeur lit SES leads, par la vraie porte d'appareil (E2E moteur).

DEFINITION-PRODUIT §9.4 : « M2 : ses leads, priorité, pipeline personnel » ; §9.5 : l'admin voit le pipeline et les
leads chauds. Avant T4.6, aucun outil ne listait les leads : ni écran vendeur, ni pipeline pour l'admin.

Le scénario est celui d'une équipe de vente, par la même porte que l'app (`PorteAppareil`, la règle du core relue
dans le fork, appliquée au vrai moteur HTTP MCP sur une base temporaire) :

- deux vendeurs (`vendeur.a`, `vendeur.b`), appairés avec le rôle `seller`, et l'admin (Nathan) ;
- vingt-quatre leads qualifiés au vendeur A, dix au vendeur B, deux leads `nouveau` sans propriétaire ;
- le vendeur A lit ses leads ; le vendeur B les siens ; l'admin tout ; l'employé est refusé (403).

Ce que ces tests prouvent : le vendeur A ne voit pas les leads de B (ni dans la liste, ni dans `total`, ni dans le
corps brut de la réponse) ; la pagination se recolle sans doublon ni trou, avec la limite de page et avec la borne de
sortie du socle (jamais tronquée) ; un lead ingéré ou noté pendant la lecture ne décale aucune page déjà lue ; un
filtre reste dans la portée du vendeur ; un segment sans donnée est refusé avec ce qui manque ; la lecture n'écrit
rien ; l'identité est confirmée en base à chaque appel (un rôle retiré depuis l'appairage est refusé).
Ce que ces tests ne prouvent PAS : l'écran (Jest, `mobile/`) ni le core.
"""

from __future__ import annotations

import json
from typing import Any

import m2_revenue_crm.outils as m2_outils
import pytest
import yaml
from harnais_e2e import Moteur, PorteAppareil, iso

from opsys import identite, stockage
from opsys.outils import executer_atomique

SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
LISTER = "m2_lister_leads"
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`
HORODATAGE = "2026-09-29T12:00:00-04:00"
ACTION = {"description": "Appeler le client (fictif)", "echeance": "2026-09-05T09:00:00-04:00"}
NB_A, NB_B = 24, 10
LEADS_A = [f"lead-a-{i:02d}" for i in range(NB_A)]
LEADS_B = [f"lead-b-{i:02d}" for i in range(NB_B)]
LEADS_NOUVEAUX = ["lead-nouveau-0", "lead-nouveau-1"]
URGENTS_A = LEADS_A[::6]  # 0, 6, 12, 18
URGENTS_B = LEADS_B[::5]  # 0, 5


def _m2(moteur: Moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements["m02-revenue-crm"].charger_outils()}


def _contrat(lead_id: str, urgence: bool) -> dict[str, Any]:
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": f"Client {lead_id} (fictif)", "courriel": f"{lead_id}@exemple-fictif.test"},
        "type_travaux": "renovation_totale", "ville": "Repentigny", "urgence_declaree": urgence, "canal": "telephone",
    }


def _ingerer(m2: dict[str, Any], lead_id: str, minute: int, urgence: bool = False) -> None:
    horodatage = f"2026-09-01T{9 + minute // 60:02d}:{minute % 60:02d}:00-04:00"
    reponse = executer_atomique(
        m2["m2_ingerer_lead"], {"contrat": _contrat(lead_id, urgence), "horodatage": horodatage})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def _qualifier_par_l_agent(m2: dict[str, Any], lead_id: str, owner: str) -> None:
    reponse = executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": "2026-09-02T09:00:00-04:00", "owner": owner,
        "prochaine_action": ACTION})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


@pytest.fixture
def vendeurs(moteur, equipe, monkeypatch):
    """Les deux vendeurs et leurs appareils, créés et appairés par les commandes réelles du socle."""
    moteur.creer_personne("vendeur.a", "Vendeur A (fictif)", ["seller"], monkeypatch)
    moteur.creer_personne("vendeur.b", "Vendeur B (fictif)", ["seller"], monkeypatch)
    return {"a": moteur.appairer("vendeur.a", "seller"), "b": moteur.appairer("vendeur.b", "seller")}


@pytest.fixture
def equipe_de_vente(moteur, equipe, vendeurs):
    """Les leads, préparés par la voie des agents (l'ingestion vient de M1 par le bus en production), et la
    qualification de chacun au bon vendeur. Le dernier lead de A est qualifié PAR L'ADMIN depuis son téléphone
    (`test_un_lead_qualifie_pendant_la_lecture...`) : ici seuls les leads déjà là."""
    m2 = _m2(moteur)
    minute = 0
    for lead_id in LEADS_A:
        _ingerer(m2, lead_id, minute, urgence=lead_id in URGENTS_A)
        _qualifier_par_l_agent(m2, lead_id, "vendeur.a")
        minute += 1
    for lead_id in LEADS_B:
        _ingerer(m2, lead_id, minute, urgence=lead_id in URGENTS_B)
        _qualifier_par_l_agent(m2, lead_id, "vendeur.b")
        minute += 1
    for lead_id in LEADS_NOUVEAUX:
        _ingerer(m2, lead_id, minute, urgence=True)
        minute += 1
    return {**equipe, **vendeurs}


def _lire(porte: PorteAppareil, **args: Any):
    """Un appel de l'écran : HTTP 200, réponse acceptée, jamais tronquée par le socle."""
    reponse = porte.appeler(LISTER, {"horodatage": HORODATAGE, **args})
    assert reponse.statut == 200 and reponse.metier["accepte"] is True, reponse.corps
    assert reponse.mesure.tronque is False and reponse.mesure.octets_texte < LIMITE_TRONCATURE, reponse.mesure
    return reponse


def _reponses(porte: PorteAppareil, **args: Any) -> list[Any]:
    """Comme l'app : la page 0, puis `suivant` tant qu'il n'est pas nul. Rend les réponses brutes."""
    reponses = [_lire(porte, **args)]
    while reponses[-1].resultat["suivant"] is not None:
        reponses.append(_lire(porte, decalage=reponses[-1].resultat["suivant"], **args))
        assert len(reponses) <= 60, "la lecture ne progresse pas"
    return reponses


def _lire_tout(porte: PorteAppareil, **args: Any) -> list[dict[str, Any]]:
    return [reponse.resultat for reponse in _reponses(porte, **args)]


def _ids(pages: list[dict[str, Any]]) -> list[str]:
    return [lead["lead_id"] for page in pages for lead in page["leads"]]


# ---------------------------------------------------------------------------------------------------------
# Le vendeur A ne voit pas le lead de B
# ---------------------------------------------------------------------------------------------------------
def test_le_vendeur_a_ne_voit_pas_les_leads_de_b_ni_les_nouveaux_et_b_ne_voit_pas_ceux_de_a(moteur, equipe_de_vente):
    a, b = equipe_de_vente["a"], equipe_de_vente["b"]

    pages_a = _lire_tout(a)
    assert _ids(pages_a) == LEADS_A
    assert {p["total"] for p in pages_a} == {NB_A}  # jamais le total de l'entreprise
    pages_b = _lire_tout(b)
    assert _ids(pages_b) == LEADS_B
    assert {p["total"] for p in pages_b} == {NB_B}

    # Le corps brut de chaque réponse, pas seulement la liste : aucun lead d'un autre, aucun nouveau lead, aucune
    # personne d'un autre vendeur (`proprietaire`), nulle part (règles, données de segment, messages).
    for porte, autres, personne in (
        (a, LEADS_B + LEADS_NOUVEAUX, "vendeur.b"), (b, LEADS_A + LEADS_NOUVEAUX, "vendeur.a"),
    ):
        for reponse in _reponses(porte):
            brut = json.dumps(reponse.corps, ensure_ascii=False)
            assert not any(autre in brut for autre in autres)
            assert personne not in brut
    assert {lead["proprietaire"] for p in pages_a for lead in p["leads"]} == {"vendeur.a"}
    assert {lead["proprietaire"] for p in pages_b for lead in p["leads"]} == {"vendeur.b"}


def test_l_admin_voit_tous_les_leads_dont_les_nouveaux_sans_proprietaire(moteur, equipe_de_vente):
    pages = _lire_tout(equipe_de_vente["admin"])
    tous = _ids(pages)
    assert sorted(tous) == sorted(LEADS_A + LEADS_B + LEADS_NOUVEAUX)
    assert len(tous) == len(set(tous)) == NB_A + NB_B + 2
    assert {p["total"] for p in pages} == {NB_A + NB_B + 2}
    proprietaires = {lead["lead_id"]: lead["proprietaire"] for p in pages for lead in p["leads"]}
    assert proprietaires["lead-nouveau-0"] is None and proprietaires["lead-a-03"] == "vendeur.a"


def test_l_employe_n_a_pas_la_portee_de_l_outil(moteur, equipe_de_vente):
    refus = equipe_de_vente["employe"].appeler(LISTER, {"horodatage": HORODATAGE})
    assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"]


def test_aucun_argument_ne_designe_un_autre_vendeur(moteur, equipe_de_vente):
    for cle in ("owner", "proprietaire", "vendeur", "personne"):
        reponse = equipe_de_vente["a"].appeler(LISTER, {"horodatage": HORODATAGE, cle: "vendeur.b"})
        assert reponse.statut == 200 and reponse.enveloppe["ok"] is False
        assert reponse.enveloppe["erreur"] == "arguments_invalides"


def test_un_role_retire_depuis_l_appairage_est_refuse_par_l_identite_confirmee_en_base(moteur, equipe_de_vente):
    b = equipe_de_vente["b"]
    assert _lire(b).resultat["total"] == NB_B
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "vendeur.b", "seller")
        identite.ajouter_role(cnx, "vendeur.b", "employee")
    reponse = b.appeler(LISTER, {"horodatage": HORODATAGE})
    assert reponse.statut == 200  # le jeton passe la porte : c'est M2 qui refuse, sur la personne, pas sur le jeton
    assert reponse.metier["accepte"] is False
    assert reponse.metier["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert "lead-b" not in json.dumps(reponse.corps)


# ---------------------------------------------------------------------------------------------------------
# La pagination se recolle
# ---------------------------------------------------------------------------------------------------------
@SQLITE_SEULEMENT
def test_la_pagination_par_limite_se_recolle_sans_doublon_ni_trou(moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    pages = _lire_tout(a, limite=5)
    assert [p["affichees"] for p in pages] == [5, 5, 5, 5, 4]
    assert [p["decalage"] for p in pages] == [0, 5, 10, 15, 20]
    assert [p["suivant"] for p in pages] == [5, 10, 15, 20, None]
    assert [p["reste"] for p in pages] == [19, 14, 9, 4, 0]
    recolle = _ids(pages)
    assert recolle == LEADS_A  # dans l'ordre documenté, chacun une seule fois
    assert len(set(recolle)) == len(recolle) == NB_A
    assert {p["ordre"] for p in pages} == {pages[0]["ordre"]} and "plus ancien" in pages[0]["ordre"]


@SQLITE_SEULEMENT
def test_la_pagination_par_la_borne_de_sortie_du_socle_se_recolle_aussi_et_n_est_jamais_tronquee(
        moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    pages = _lire_tout(a)  # limite par défaut : c'est la borne de 6 000 caractères qui coupe
    assert len(pages) > 1, "24 leads tiennent en une page : la borne de sortie n'est pas exercée"
    assert all(p["affichees"] == len(p["leads"]) >= 1 for p in pages)
    assert _ids(pages) == LEADS_A
    mesures = [m for m in moteur.mesures if m.outil == LISTER][-len(pages):]
    assert all(m.tronque is False and m.octets_texte < LIMITE_TRONCATURE for m in mesures)
    print("MESURE-LEADS " + json.dumps({
        "leads": NB_A, "pages": len(pages), "par_page": [p["affichees"] for p in pages],
        "octets": [m.octets_texte for m in mesures], "duree_s": [round(m.duree_s, 3) for m in mesures]}))


@SQLITE_SEULEMENT
def test_un_decalage_au_dela_de_la_fin_est_une_page_vide_et_un_decalage_invalide_un_verdict(moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    for hors_plage in (NB_A, NB_A + 1, 500):
        page = _lire(a, decalage=hors_plage).resultat
        assert page["leads"] == [] and page["suivant"] is None and page["reste"] == 0 and page["total"] == NB_A
    negatif = a.appeler(LISTER, {"horodatage": HORODATAGE, "decalage": -1})
    assert negatif.statut == 200 and negatif.metier["accepte"] is False
    assert negatif.metier["verdict"]["code"] == "REJ-PAGINATION-INVALIDE"
    zero = a.appeler(LISTER, {"horodatage": HORODATAGE, "limite": 0})
    assert zero.metier["verdict"]["code"] == "REJ-PAGINATION-INVALIDE"
    booleen = a.appeler(LISTER, {"horodatage": HORODATAGE, "limite": True})
    assert booleen.enveloppe["ok"] is False and booleen.enveloppe["erreur"] == "arguments_invalides"


@SQLITE_SEULEMENT
def test_un_lead_qualifie_pendant_la_lecture_par_l_admin_s_ajoute_a_la_fin_sans_decaler_les_pages_lues(
        moteur, equipe_de_vente):
    """La suite de la lecture d'un vendeur quand l'admin qualifie un nouveau lead pour lui, DEPUIS SON TÉLÉPHONE
    (la chaîne réelle : validation au départ, propriétaire consigné). Une note sur un lead déjà lu ne change pas
    non plus son rang (l'ordre est celui de l'ingestion)."""
    a, admin = equipe_de_vente["a"], equipe_de_vente["admin"]
    premiere = _lire(a, limite=10).resultat
    assert _ids([premiere]) == LEADS_A[:10]

    _ingerer(_m2(moteur), "lead-a-tard", minute=200)
    qualification = admin.appeler(
        "m2_transitionner_statut",
        {"lead_id": "lead-a-tard", "statut_cible": "qualifie", "horodatage": HORODATAGE, "owner": "vendeur.a",
         "prochaine_action": ACTION},
        cle="e2e-qualifier-lead-a-tard", horodatage_appareil=iso(moteur.horloge.maintenant))
    assert qualification.resultat["statut"] == "qualifie"
    note = a.appeler(
        "m2_enregistrer_interaction",
        {"lead_id": LEADS_A[3], "resume": "Rappel fait (fictif)", "horodatage": HORODATAGE},
        cle="e2e-note-lead-a-03", horodatage_appareil=iso(moteur.horloge.maintenant))
    assert note.resultat["lead_id"] == LEADS_A[3]

    suite = [premiere]
    while suite[-1]["suivant"] is not None:
        suite.append(_lire(a, limite=10, decalage=suite[-1]["suivant"]).resultat)
    assert _ids(suite) == LEADS_A + ["lead-a-tard"]
    assert len(set(_ids(suite))) == NB_A + 1
    assert suite[-1]["total"] == NB_A + 1


# ---------------------------------------------------------------------------------------------------------
# Filtres et segments
# ---------------------------------------------------------------------------------------------------------
@SQLITE_SEULEMENT
def test_le_filtre_par_segment_reste_dans_la_portee_du_vendeur(moteur, equipe_de_vente):
    a, b, admin = equipe_de_vente["a"], equipe_de_vente["b"], equipe_de_vente["admin"]
    chauds_a = _lire_tout(a, segment="hot_lead")
    assert _ids(chauds_a) == URGENTS_A
    assert all(lead["segments"][0]["regle"] == "urgence_declaree_lead_ouvert"
               for p in chauds_a for lead in p["leads"])
    assert _ids(_lire_tout(b, segment="hot_lead")) == URGENTS_B
    tous = _ids(_lire_tout(admin, segment="hot_lead"))
    assert sorted(tous) == sorted(URGENTS_A + URGENTS_B + LEADS_NOUVEAUX)  # l'admin voit aussi les nouveaux chauds
    assert _ids(_lire_tout(a, statut="nouveau")) == []
    assert _ids(_lire_tout(admin, statut="nouveau")) == LEADS_NOUVEAUX
    assert _ids(_lire_tout(a, statut="qualifie", segment="hot_lead")) == URGENTS_A


@SQLITE_SEULEMENT
def test_un_segment_sans_donnee_est_refuse_avec_ce_qui_manque_jamais_une_liste_vide(moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    for segment, mot in (("needs_photos", "photos"), ("quote_sent", "m3.devis_envoye"),
                         ("complaint_risk", "plaintes"), ("high_value_customer", "valeur du client")):
        reponse = a.appeler(LISTER, {"horodatage": HORODATAGE, "segment": segment})
        assert reponse.statut == 200 and reponse.metier["accepte"] is False
        verdict = reponse.metier["verdict"]
        assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE"
        assert "non calculable, manque" in verdict["detail"] and mot in verdict["detail"]
    page = _lire(a).resultat
    assert {n["segment"] for n in page["segments_non_calculables"]} >= {
        "needs_photos", "quote_sent", "high_value_customer", "referral_candidate", "complaint_risk",
        "seasonal_opportunity", "dormant_lead", "quote_stale"}


@SQLITE_SEULEMENT
def test_les_seuils_de_department_yaml_decident_de_dormant_et_restent_dans_la_portee(
        moteur, equipe_de_vente, monkeypatch, tmp_path):
    a = equipe_de_vente["a"]
    plus_tard = "2026-12-01T12:00:00-04:00"
    # Le manifeste livré est vide : « seuil à configurer », jamais un lead déclaré dormant.
    vide = a.appeler(LISTER, {"horodatage": plus_tard, "segment": "dormant_lead"})
    assert vide.metier["verdict"]["code"] == "REJ-SEGMENT-NON-CALCULABLE"
    assert "seuil à configurer" in vide.metier["verdict"]["detail"]

    reel = yaml.safe_load(m2_outils._MANIFESTE.read_text(encoding="utf-8"))
    manifeste = {**reel, "configuration": {**reel["configuration"], "segments": {"jours_inactivite_dormant": 60}}}
    chemin = tmp_path / "department-m2-e2e.yaml"
    chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(m2_outils, "_MANIFESTE", chemin)

    pages = _lire_tout(a, segment="dormant_lead", horodatage=plus_tard)
    assert _ids(pages) == LEADS_A  # 91 jours sans activité, seuil de 60 : les siens, et seulement les siens
    dormant = pages[0]["leads"][0]["segments"][-1]
    assert dormant["segment"] == "dormant_lead" and dormant["regle"] == "lead_ouvert_sans_activite"
    assert dormant["donnee"]["seuil_jours"] == 60 and dormant["donnee"]["jours_ecoules"] >= 60
    trop_tot = a.appeler(LISTER, {"horodatage": "2026-09-20T12:00:00-04:00", "segment": "dormant_lead"})
    assert trop_tot.metier["accepte"] is True and trop_tot.resultat["leads"] == []


# ---------------------------------------------------------------------------------------------------------
# Lecture seule, rejeu, aucun montant
# ---------------------------------------------------------------------------------------------------------
@SQLITE_SEULEMENT
def test_lire_n_ecrit_rien_et_la_meme_lecture_rend_la_meme_page(moteur, equipe_de_vente):
    a, admin = equipe_de_vente["a"], equipe_de_vente["admin"]
    empreinte = moteur.empreinte_etat()
    premiere = _lire(a, limite=7, decalage=7)
    seconde = _lire(a, limite=7, decalage=7)
    assert premiere.resultat == seconde.resultat
    _lire_tout(a)
    _lire_tout(admin, segment="hot_lead")
    assert moteur.empreinte_etat() == empreinte  # ni registre, ni événement, ni approbation, ni journal, ni mutation


@SQLITE_SEULEMENT
def test_aucun_montant_ni_contact_dans_aucune_page(moteur, equipe_de_vente):
    for porte in (equipe_de_vente["a"], equipe_de_vente["admin"]):
        for page in _lire_tout(porte):
            texte = json.dumps(page["leads"], ensure_ascii=False).lower()
            for interdit in ("exemple-fictif.test", "client lead", "prix", "cout", "marge", "montant", "$"):
                assert interdit not in texte, interdit
            for lead in page["leads"]:
                assert set(lead) <= {"lead_id", "statut", "proprietaire", "travaux", "ville", "urgence_declaree",
                                     "ingere_le", "derniere_activite", "prochaine_action", "segments",
                                     "non_calculables"}
