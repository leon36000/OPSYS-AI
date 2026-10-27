"""PLAN T4.6 (M2.11) : la liste des leads visibles, filtrée par statut et par segment, paginée.

`liste_leads.py` est PUR : il reçoit les maillons du registre, l'ensemble des leads visibles, les seuils et
l'instant. Ces tests le nourrissent d'un VRAI registre en mémoire, rempli par les vraies fonctions de M2
(`ingestion`, `clients`, `statuts`, `interactions`) : la liste lit ce que M2 écrit, jamais une fixture à la main.

Ce qui est prouvé : l'ordre (un instant, pas du texte), les filtres, la visibilité (un lead hors de `visibles` n'est
ni listé, ni compté, ni cité), l'absence de montant et de contact, la pagination (les pages se recollent sans doublon
ni trou, un décalage hors de la fin rend une page vide, la borne de sortie tient), et les segments tirés des faits
réels. Les portes d'appareil sont dans `test_lister_leads_outil.py` et dans `tests/e2e/`. Données fictives.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from m2_revenue_crm import clients, ingestion, interactions, liste_leads, registre, segments, statuts

FICTIF = True

MAINTENANT = "2026-09-29T12:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
SEUILS_OK = segments.lire_seuils({"jours_inactivite_dormant": 30, "jours_soumission_perimee": 14})
SEUILS_VIDES = segments.lire_seuils({})
BUDGET = 5900

CLES_D_UN_LEAD = {
    "lead_id", "statut", "proprietaire", "travaux", "ville", "urgence_declaree", "ingere_le", "derniere_activite",
    "prochaine_action", "segments", "non_calculables",
}
CLES_D_UNE_PAGE = {
    "ordre", "filtre", "total", "decalage", "affichees", "reste", "suivant", "message", "indetermines", "leads",
    "regles", "segments_non_calculables",
}


# -- construction d'un registre réel -----------------------------------------------------------------------
def _contrat(lead_id: str, *, urgence: bool = False, contact: dict | None = None, ville: str = "Québec",
             service: str | None = None) -> dict:
    """Un contrat v1 (`type_travaux`) ; avec `service`, un contrat v2 (`schema_version`, `service`)."""
    contrat = {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": contact or {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale", "ville": ville, "urgence_declaree": urgence, "canal": "telephone",
    }
    if service is not None:
        del contrat["type_travaux"]
        contrat.update({"schema_version": 2, "service": service})
    return contrat


def _ingerer(reg, lead_id: str, horodatage: str = "2026-09-01T09:00:00-04:00", **options) -> None:
    contrat = _contrat(lead_id, **options)
    _, verdict = ingestion.ingerer(contrat, reg, horodatage)
    assert verdict is None, verdict
    _, verdict_client = clients.lier_lead(reg, lead_id, contrat, horodatage)
    assert verdict_client is None, verdict_client


def _transition(reg, lead_id: str, cible: str, horodatage: str, **options) -> None:
    _, verdict = statuts.transitionner(lead_id, cible, reg, horodatage, **options)
    assert verdict is None, verdict


def _qualifier(reg, lead_id: str, owner: str = "vendeur.un", horodatage: str = "2026-09-01T10:00:00-04:00") -> None:
    _transition(reg, lead_id, "qualifie", horodatage, owner=owner, prochaine_action=ACTION)


def _note(reg, lead_id: str, horodatage: str, auteur: str = "vendeur.un") -> None:
    _, verdict = interactions.enregistrer(lead_id, auteur, "Appel fait (fictif)", reg, horodatage)
    assert verdict is None, verdict


def _amener_a(reg, lead_id: str, statut: str, owner: str = "vendeur.un") -> None:
    """Fait avancer un lead ingéré jusqu'à `statut` par la machine à états réelle."""
    chemin = ["qualifie", "converti", "cedule", "chantier", "facture", "paiement", "avis"]
    options = {
        "qualifie": {"owner": owner, "prochaine_action": ACTION},
        "converti": {"reference_devis_m3": f"devis-{lead_id}"},
        "facture": {"prochaine_action": ACTION},
    }
    for i, etape in enumerate(chemin):
        _transition(reg, lead_id, etape, f"2026-09-02T09:{i:02d}:00-04:00", **options.get(etape, {}))
        if etape == statut:
            return
    raise AssertionError(statut)


def _lister(reg, *, verdict_attendu: bool = False, visibles=None, relances=(), seuils=SEUILS_OK, budget=BUDGET,
            horodatage=MAINTENANT, **options):
    resultat, verdict = liste_leads.lister(
        reg.lire(), visibles=visibles, relances_devis=None if relances is None else list(relances), seuils=seuils,
        horodatage=horodatage, budget_caracteres=budget, **options)
    if verdict_attendu:
        assert resultat is None and verdict is not None
        return verdict
    assert verdict is None, verdict
    return resultat


def _ids(page: dict) -> list[str]:
    return [lead["lead_id"] for lead in page["leads"]]


def _lire_tout(reg, **options) -> list[dict]:
    """Toutes les pages, en suivant `suivant` : la lecture d'un écran."""
    pages: list[dict] = []
    decalage = 0
    while True:
        page = _lister(reg, decalage=decalage, **options)
        pages.append(page)
        if page["suivant"] is None:
            return pages
        assert page["suivant"] == decalage + page["affichees"]
        assert len(pages) < 200, "la lecture ne progresse pas"
        decalage = page["suivant"]


@pytest.fixture
def reg():
    return registre.Registre()


@pytest.fixture
def sept_leads(reg):
    for i in range(7):
        _ingerer(reg, f"lead-{i}", f"2026-09-01T09:0{i}:00-04:00")
    return reg


# ---------------------------------------------------------------------------------------------------------
# Ordre
# ---------------------------------------------------------------------------------------------------------
def test_l_ordre_est_celui_des_instants_d_ingestion_pas_celui_du_texte(reg):
    _ingerer(reg, "lead-a", "2026-09-01T09:00:00-04:00")  # 13:00Z
    _ingerer(reg, "lead-b", "2026-09-01T12:00:00+00:00")  # 12:00Z : plus tôt, mais « 12 » > « 09 » en texte
    assert _ids(_lister(reg)) == ["lead-b", "lead-a"]


def test_a_instant_egal_le_lead_id_departage_pas_l_ordre_d_ingestion(reg):
    for lead_id in ("lead-z", "lead-m", "lead-a"):
        _ingerer(reg, lead_id, "2026-09-01T09:00:00-04:00")
    assert _ids(_lister(reg)) == ["lead-a", "lead-m", "lead-z"]


def test_l_ordre_est_documente_et_repete_dans_chaque_page(reg):
    _ingerer(reg, "lead-a")
    assert _lister(reg)["ordre"] == liste_leads.ORDRE_LEADS
    assert "plus ancien" in liste_leads.ORDRE_LEADS


def test_une_activite_ne_change_pas_le_rang_d_un_lead(sept_leads):
    avant = _ids(_lister(sept_leads))
    _qualifier(sept_leads, "lead-3")
    _note(sept_leads, "lead-3", "2026-09-20T09:00:00-04:00")
    assert _ids(_lister(sept_leads)) == avant


def test_un_lead_ingere_apres_le_debut_de_la_lecture_s_ajoute_a_la_fin_sans_decaler_les_pages_lues(sept_leads):
    page_1 = _lister(sept_leads, limite=3)
    _ingerer(sept_leads, "lead-nouveau", "2026-09-15T09:00:00-04:00")
    page_2 = _lister(sept_leads, limite=3, decalage=page_1["suivant"])
    page_3 = _lister(sept_leads, limite=3, decalage=page_2["suivant"])
    rendus = _ids(page_1) + _ids(page_2) + _ids(page_3)
    assert rendus == [f"lead-{i}" for i in range(7)] + ["lead-nouveau"]
    assert page_3["total"] == 8


# ---------------------------------------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def pipeline(reg):
    """Un lead par statut utile, tous à des instants distincts. lead-chaud : urgent et qualifié."""
    _ingerer(reg, "lead-nouveau", "2026-09-01T09:00:00-04:00")
    _ingerer(reg, "lead-qualifie", "2026-09-01T09:01:00-04:00")
    _qualifier(reg, "lead-qualifie")
    _ingerer(reg, "lead-chaud", "2026-09-01T09:02:00-04:00", urgence=True)
    _qualifier(reg, "lead-chaud")
    _ingerer(reg, "lead-converti", "2026-09-01T09:03:00-04:00", urgence=True)
    _amener_a(reg, "lead-converti", "converti")
    _ingerer(reg, "lead-chantier", "2026-09-01T09:04:00-04:00")
    _amener_a(reg, "lead-chantier", "chantier")
    _ingerer(reg, "lead-perdu", "2026-09-01T09:05:00-04:00")
    _transition(reg, "lead-perdu", "perdu", "2026-09-02T09:00:00-04:00", motif="Parti ailleurs (fictif)")
    return reg


def test_sans_filtre_tous_les_leads_visibles_sont_listes_avec_leur_statut(pipeline):
    page = _lister(pipeline)
    assert {lead["lead_id"]: lead["statut"] for lead in page["leads"]} == {
        "lead-nouveau": "nouveau", "lead-qualifie": "qualifie", "lead-chaud": "qualifie",
        "lead-converti": "converti", "lead-chantier": "chantier", "lead-perdu": "perdu",
    }
    assert page["total"] == 6
    assert page["filtre"] == {"statut": None, "segment": None}


@pytest.mark.parametrize(("statut", "attendus"), [
    ("nouveau", ["lead-nouveau"]), ("qualifie", ["lead-qualifie", "lead-chaud"]),
    ("converti", ["lead-converti"]), ("chantier", ["lead-chantier"]), ("perdu", ["lead-perdu"]),
    ("cedule", []), ("avis", []),
])
def test_le_filtre_par_statut_ne_garde_que_ce_statut(pipeline, statut, attendus):
    page = _lister(pipeline, statut=statut)
    assert _ids(page) == attendus
    assert page["total"] == len(attendus)
    assert page["filtre"]["statut"] == statut


def test_le_filtre_par_segment_ne_garde_que_les_leads_du_segment_avec_la_regle_citee(pipeline):
    page = _lister(pipeline, segment="hot_lead")
    assert _ids(page) == ["lead-chaud"]  # lead-converti est urgent mais n'est plus ouvert
    assert page["leads"][0]["segments"] == [{
        "segment": "hot_lead", "regle": "urgence_declaree_lead_ouvert",
        "donnee": {"urgence_declaree": True, "statut": "qualifie"},
    }]
    assert _ids(_lister(pipeline, segment="won_pending_schedule")) == ["lead-converti"]
    assert _ids(_lister(pipeline, segment="active_job")) == ["lead-chantier"]


def test_statut_et_segment_se_combinent(pipeline):
    assert _ids(_lister(pipeline, statut="qualifie", segment="hot_lead")) == ["lead-chaud"]
    assert _ids(_lister(pipeline, statut="nouveau", segment="hot_lead")) == []


def test_un_segment_calculable_que_personne_n_a_donne_une_page_vide_pas_un_refus(pipeline):
    page = _lister(pipeline, segment="invoice_pending")
    assert page["leads"] == []
    assert page["total"] == 0
    assert page["suivant"] is None
    assert page["indetermines"] == 0


@pytest.mark.parametrize("options", [{"statut": "inconnu"}, {"segment": "inconnu"}, {"statut": ""}, {"segment": 3}])
def test_un_statut_ou_un_segment_hors_liste_est_refuse(pipeline, options):
    verdict = _lister(pipeline, verdict_attendu=True, **options)
    assert verdict["code"] == "REJ-ENUM-INVALIDE"


@pytest.mark.parametrize("segment", segments.SEGMENTS_NON_CALCULABLES)
def test_filtrer_sur_un_segment_sans_donnee_est_refuse_avec_ce_qui_manque(pipeline, segment):
    verdict = _lister(pipeline, verdict_attendu=True, segment=segment)
    assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE"
    assert f"segment {segment} : non calculable, manque " in verdict["detail"]


@pytest.mark.parametrize("segment", ["dormant_lead", "quote_stale"])
def test_filtrer_sur_un_segment_sans_seuil_est_refuse_seuil_a_configurer_jamais_une_liste_vide(pipeline, segment):
    verdict = _lister(pipeline, verdict_attendu=True, segment=segment, seuils=SEUILS_VIDES)
    assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE"
    assert "seuil à configurer" in verdict["detail"]
    assert "configuration.segments" in verdict["detail"]


def test_sans_seuil_la_liste_ne_declare_jamais_un_lead_dormant_meme_tres_ancien(reg):
    _ingerer(reg, "lead-ancien", "2019-01-01T09:00:00-04:00")
    page = _lister(reg, seuils=SEUILS_VIDES)
    assert page["leads"][0]["segments"] == []
    noms = [n["segment"] for n in page["segments_non_calculables"]]
    assert "dormant_lead" in noms
    assert "quote_stale" in noms


# ---------------------------------------------------------------------------------------------------------
# Visibilité, montants, contacts
# ---------------------------------------------------------------------------------------------------------
def test_un_lead_hors_des_visibles_n_est_ni_liste_ni_compte_ni_cite(pipeline):
    page = _lister(pipeline, visibles={"lead-qualifie", "lead-chaud"})
    assert _ids(page) == ["lead-qualifie", "lead-chaud"]
    assert page["total"] == 2
    texte = json.dumps(page, ensure_ascii=False)
    for autre in ("lead-nouveau", "lead-converti", "lead-chantier", "lead-perdu"):
        assert autre not in texte


def test_aucun_lead_visible_donne_une_page_vide_pas_un_refus(pipeline):
    page = _lister(pipeline, visibles=set())
    assert page["leads"] == []
    assert page["total"] == 0
    assert page["suivant"] is None


def test_le_filtre_ne_revele_pas_un_lead_invisible_meme_s_il_correspond(pipeline):
    page = _lister(pipeline, visibles={"lead-qualifie"}, segment="hot_lead")
    assert page["leads"] == []
    assert page["total"] == 0


def test_un_ancien_client_ne_se_lit_que_dans_les_opportunites_visibles(reg):
    """Même client (même contact) : `lead-paye` (avis) et `lead-neuf` (qualifié). L'admin voit l'ancien client ;
    le vendeur du lead neuf, qui ne voit pas `lead-paye`, ne l'apprend pas par un segment."""
    contact = {"nom": "Cliente Fidèle", "courriel": "fidele@example.test"}
    _ingerer(reg, "lead-paye", "2026-09-01T09:00:00-04:00", contact=contact)
    _amener_a(reg, "lead-paye", "avis", owner="vendeur.un")
    _ingerer(reg, "lead-neuf", "2026-09-10T09:00:00-04:00", contact=contact)
    _qualifier(reg, "lead-neuf", owner="vendeur.deux")

    admin = _lister(reg, visibles=None, segment="past_customer")
    assert _ids(admin) == ["lead-paye", "lead-neuf"]
    par_id = {lead["lead_id"]: lead for lead in admin["leads"]}
    assert par_id["lead-neuf"]["segments"][0]["donnee"] == {"lead_paye": "lead-paye", "statut": "avis"}

    vendeur_deux = _lister(reg, visibles={"lead-neuf"})
    assert vendeur_deux["leads"][0]["segments"] == []
    assert "lead-paye" not in json.dumps(vendeur_deux, ensure_ascii=False)
    assert _lister(reg, visibles={"lead-neuf"}, segment="past_customer")["leads"] == []

    vendeur_un = _lister(reg, visibles={"lead-paye"})
    assert vendeur_un["leads"][0]["segments"][0]["segment"] == "past_customer"
    assert vendeur_un["leads"][0]["segments"][0]["donnee"]["lead_paye"] == "lead-paye"


def test_un_client_sans_chantier_paye_n_est_pas_un_ancien_client(reg):
    contact = {"nom": "Cliente Neuve", "courriel": "neuve@example.test"}
    _ingerer(reg, "lead-1", "2026-09-01T09:00:00-04:00", contact=contact)
    _amener_a(reg, "lead-1", "paiement")  # facturé, paiement non confirmé
    _ingerer(reg, "lead-2", "2026-09-10T09:00:00-04:00", contact=contact)
    assert _lister(reg, segment="past_customer")["leads"] == []


def _cles(objet) -> set[str]:
    """Toutes les clés de tous les dictionnaires imbriqués."""
    if isinstance(objet, dict):
        return set(objet) | {c for v in objet.values() for c in _cles(v)}
    if isinstance(objet, list):
        return {c for v in objet for c in _cles(v)}
    return set()


def test_aucun_montant_aucun_contact_et_seulement_les_cles_documentees(pipeline):
    page = _lister(pipeline)
    assert set(page) == CLES_D_UNE_PAGE
    for lead in page["leads"]:
        assert set(lead) <= CLES_D_UN_LEAD, set(lead) - CLES_D_UN_LEAD
    interdits_en_cle = ("montant", "prix", "cout", "coût", "marge", "taux", "valeur", "total_ttc", "sous_total",
                        "contact", "nom", "courriel", "telephone", "email")
    for cle in _cles(page):
        assert not any(mot in cle for mot in interdits_en_cle), cle
    # Les leads eux-mêmes : ni donnée de contact, ni montant en valeur. (Les énoncés de règles et de manques,
    # eux, peuvent nommer ce qui manque : « montants à M3 et à M5 ».)
    texte_des_leads = json.dumps(page["leads"], ensure_ascii=False).lower()
    for interdit in ("example.test", "client lead", "$", "prix", "marge"):
        assert interdit not in texte_des_leads, interdit


def test_prochaine_action_et_travaux_longs_sont_bornes_la_courte_reste_intacte(reg):
    _ingerer(reg, "lead-long", ville="V" * 500)
    _transition(reg, "lead-long", "qualifie", "2026-09-01T10:00:00-04:00", owner="vendeur.un",
                prochaine_action={"description": "D" * 500, "echeance": ACTION["echeance"]})
    _ingerer(reg, "lead-court", "2026-09-01T09:30:00-04:00")
    _qualifier(reg, "lead-court")
    par_id = {lead["lead_id"]: lead for lead in _lister(reg)["leads"]}
    assert len(par_id["lead-long"]["prochaine_action"]["description"]) == 160
    assert par_id["lead-long"]["prochaine_action"]["description"].endswith("…")
    assert len(par_id["lead-long"]["ville"]) == 80
    assert par_id["lead-court"]["prochaine_action"] == ACTION
    assert par_id["lead-court"]["ville"] == "Québec"


def test_un_lead_sans_prochaine_action_la_rend_nulle_jamais_inventee(pipeline):
    par_id = {lead["lead_id"]: lead for lead in _lister(pipeline)["leads"]}
    assert par_id["lead-nouveau"]["prochaine_action"] is None
    assert par_id["lead-qualifie"]["prochaine_action"] == ACTION
    assert par_id["lead-nouveau"]["proprietaire"] is None
    assert par_id["lead-qualifie"]["proprietaire"] == "vendeur.un"


def test_le_travaux_d_un_lead_v2_est_son_service_celui_d_un_lead_v1_son_type_de_travaux(reg, declarer_services):
    declarer_services()
    _ingerer(reg, "lead-v1", "2026-09-01T09:00:00-04:00")
    _ingerer(reg, "lead-v2", "2026-09-01T09:01:00-04:00", service="gouttieres")
    par_id = {lead["lead_id"]: lead for lead in _lister(reg)["leads"]}
    assert par_id["lead-v1"]["travaux"] == "renovation_totale"
    assert par_id["lead-v2"]["travaux"] == "gouttieres"


# ---------------------------------------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------------------------------------
def test_les_pages_se_recollent_sans_doublon_ni_trou(sept_leads):
    tout = _ids(_lister(sept_leads, limite=50))
    pages = _lire_tout(sept_leads, limite=3)
    assert [p["affichees"] for p in pages] == [3, 3, 1]
    assert [p["suivant"] for p in pages] == [3, 6, None]
    assert [p["reste"] for p in pages] == [4, 1, 0]
    assert [p["decalage"] for p in pages] == [0, 3, 6]
    recolle = [lead_id for p in pages for lead_id in _ids(p)]
    assert recolle == tout == [f"lead-{i}" for i in range(7)]
    assert len(set(recolle)) == len(recolle)
    assert {p["total"] for p in pages} == {7}


def test_le_message_dit_comment_poursuivre(sept_leads):
    premiere = _lister(sept_leads, limite=3)
    assert premiere["message"] == "4 autres leads non affichés : poursuivre avec decalage=3."
    derniere = _lister(sept_leads, limite=3, decalage=6)
    assert derniere["message"] is None
    reste_un = _lister(sept_leads, limite=6)
    assert reste_un["message"] == "1 autre lead non affiché : poursuivre avec decalage=6."


@pytest.mark.parametrize("decalage", [7, 8, 1000])
def test_un_decalage_a_la_fin_ou_au_dela_rend_une_page_vide_et_rien_ensuite(sept_leads, decalage):
    page = _lister(sept_leads, decalage=decalage)
    assert page["leads"] == []
    assert page["affichees"] == 0
    assert page["reste"] == 0
    assert page["suivant"] is None
    assert page["total"] == 7
    assert page["message"] is None


@pytest.mark.parametrize("decalage", [-1, True, False, "0", 1.5, None, [0]])
def test_un_decalage_qui_n_est_pas_un_entier_positif_est_refuse(sept_leads, decalage):
    verdict = _lister(sept_leads, verdict_attendu=True, decalage=decalage)
    assert verdict["code"] == "REJ-PAGINATION-INVALIDE"
    assert "decalage" in verdict["detail"]


@pytest.mark.parametrize("limite", [0, -1, 51, 1000, True, "5", 2.5, None])
def test_une_limite_hors_de_un_a_cinquante_est_refusee(sept_leads, limite):
    verdict = _lister(sept_leads, verdict_attendu=True, limite=limite)
    assert verdict["code"] == "REJ-PAGINATION-INVALIDE"
    assert "limite" in verdict["detail"]


@pytest.mark.parametrize("limite", [1, 2, 7, 50])
def test_les_bornes_de_la_limite_sont_acceptees_et_respectees(sept_leads, limite):
    page = _lister(sept_leads, limite=limite)
    assert page["affichees"] == min(limite, 7)
    assert len(page["leads"]) == page["affichees"]


def test_la_limite_par_defaut_est_vingt_quand_la_borne_de_sortie_ne_la_devance_pas(reg):
    for i in range(25):
        _ingerer(reg, f"lead-{i:02d}", f"2026-09-01T09:{i:02d}:00-04:00")
    page = _lister(reg, budget=10**6)
    assert page["affichees"] == liste_leads.LIMITE_DEFAUT == 20
    assert page["suivant"] == 20
    assert page["reste"] == 5


def test_la_borne_de_sortie_devance_la_limite_et_le_dit_par_suivant(reg):
    for i in range(25):
        _ingerer(reg, f"lead-{i:02d}", f"2026-09-01T09:{i:02d}:00-04:00")
    page = _lister(reg)
    assert 0 < page["affichees"] < 20
    assert page["suivant"] == page["affichees"]
    assert liste_leads._taille(page) <= BUDGET


def test_la_borne_de_sortie_est_mesuree_par_le_code_et_les_pages_se_recollent_quand_meme(sept_leads):
    taille = liste_leads._taille
    p3 = _lister(sept_leads, limite=3)
    budget = taille(p3) - 1  # une page de trois leads ne tient pas, deux oui
    premiere = _lister(sept_leads, limite=50, budget=budget)
    assert premiere["affichees"] == 2
    assert taille(premiere) <= budget
    pages = _lire_tout(sept_leads, limite=50, budget=budget)
    assert all(taille(p) <= budget for p in pages if p["affichees"] > 1)
    recolle = [lead_id for p in pages for lead_id in _ids(p)]
    assert recolle == [f"lead-{i}" for i in range(7)]


def test_une_page_de_la_taille_exacte_de_la_borne_est_acceptee(sept_leads):
    """La borne est inclusive : `Capacites` ne tronque qu'au-delà de la limite, jamais à la limite."""
    p2 = _lister(sept_leads, limite=2)
    taille_exacte = liste_leads._taille(p2)
    page = _lister(sept_leads, limite=50, budget=taille_exacte)
    assert page["affichees"] == 2
    assert liste_leads._taille(page) == taille_exacte
    assert _lister(sept_leads, limite=50, budget=taille_exacte - 1)["affichees"] == 1


def test_une_page_porte_toujours_un_lead_au_moins_meme_sous_une_borne_impossible(sept_leads):
    pages = _lire_tout(sept_leads, limite=50, budget=1)
    assert [p["affichees"] for p in pages] == [1] * 7
    assert [lead_id for p in pages for lead_id in _ids(p)] == [f"lead-{i}" for i in range(7)]


def test_soixante_leads_qualifies_tiennent_dans_la_limite_de_sortie_du_socle_page_apres_page(reg):
    for i in range(60):
        _ingerer(reg, f"lead-{i:03d}", f"2026-09-01T{9 + i // 60:02d}:{i % 60:02d}:00-04:00", urgence=(i % 3 == 0))
        _qualifier(reg, f"lead-{i:03d}", owner="vendeur.un")
    pages = _lire_tout(reg, limite=50)
    assert len(pages) > 1, "60 leads qualifiés tiennent en une page : la borne n'est pas exercée"
    assert all(liste_leads._taille(p) <= BUDGET for p in pages)
    assert sum(p["affichees"] for p in pages) == 60
    recolle = [lead_id for p in pages for lead_id in _ids(p)]
    assert recolle == sorted(recolle) and len(set(recolle)) == 60


def test_le_total_compte_tous_les_leads_du_filtre_pas_seulement_la_page(reg):
    for i in range(6):
        _ingerer(reg, f"lead-{i}", f"2026-09-01T09:0{i}:00-04:00", urgence=True)
    page = _lister(reg, segment="hot_lead", limite=2)
    assert page["total"] == 6
    assert page["affichees"] == 2
    assert page["reste"] == 4


def test_la_pagination_d_un_filtre_se_recolle_aussi(pipeline):
    pages = _lire_tout(pipeline, statut="qualifie", limite=1)
    assert [lead_id for p in pages for lead_id in _ids(p)] == ["lead-qualifie", "lead-chaud"]


# ---------------------------------------------------------------------------------------------------------
# Les segments, tirés des faits réels du registre
# ---------------------------------------------------------------------------------------------------------
def _segments_de(page: dict, lead_id: str) -> list[str]:
    lead = next(item for item in page["leads"] if item["lead_id"] == lead_id)
    return [s["segment"] for s in lead["segments"]]


def test_prete_pour_l_estimation_exige_l_interaction_apres_la_qualification(reg):
    _ingerer(reg, "lead-sans-note", "2026-09-01T09:00:00-04:00")
    _qualifier(reg, "lead-sans-note", horodatage="2026-09-01T10:00:00-04:00")
    _ingerer(reg, "lead-avec-note", "2026-09-01T09:01:00-04:00")
    _qualifier(reg, "lead-avec-note", horodatage="2026-09-01T10:00:00-04:00")
    _note(reg, "lead-avec-note", "2026-09-01T11:00:00-04:00")
    page = _lister(reg)
    assert "estimate_ready" not in _segments_de(page, "lead-sans-note")
    assert "estimate_ready" in _segments_de(page, "lead-avec-note")
    lead = next(i for i in page["leads"] if i["lead_id"] == "lead-avec-note")
    assert lead["segments"][0]["regle"] == "readiness_m3_satisfaite"
    assert "readiness_m3_satisfaite" in page["regles"]


def test_readiness_n_est_jamais_lue_pour_un_lead_non_qualifie(reg):
    _ingerer(reg, "lead-nouveau")
    assert "estimate_ready" not in _segments_de(_lister(reg), "lead-nouveau")


def test_une_interaction_de_personne_remet_a_zero_la_dormance_une_ecriture_du_systeme_non(reg):
    _ingerer(reg, "lead-actif", "2026-07-01T09:00:00-04:00")
    _qualifier(reg, "lead-actif", horodatage="2026-07-01T10:00:00-04:00")
    _note(reg, "lead-actif", "2026-09-20T09:00:00-04:00")  # il y a 9 jours
    _ingerer(reg, "lead-relance-systeme", "2026-07-01T09:01:00-04:00")
    _qualifier(reg, "lead-relance-systeme", horodatage="2026-07-01T10:00:00-04:00")
    _note(reg, "lead-relance-systeme", "2026-09-20T09:00:00-04:00", auteur="system:m3")
    page = _lister(reg)
    assert "dormant_lead" not in _segments_de(page, "lead-actif")
    assert "dormant_lead" in _segments_de(page, "lead-relance-systeme")
    dormant = next(i for i in page["leads"] if i["lead_id"] == "lead-relance-systeme")
    assert dormant["derniere_activite"] == "2026-07-01T10:00:00-04:00"
    segment = next(s for s in dormant["segments"] if s["segment"] == "dormant_lead")
    assert segment["regle"] == "lead_ouvert_sans_activite"
    assert segment["donnee"] == {
        "derniere_activite": "2026-07-01T10:00:00-04:00", "jours_ecoules": 90, "seuil_jours": 30}


def test_la_derniere_activite_est_l_instant_le_plus_recent_pas_le_dernier_maillon_ecrit(reg):
    _ingerer(reg, "lead-1", "2026-09-01T09:00:00-04:00")
    _qualifier(reg, "lead-1", horodatage="2026-09-01T10:00:00-04:00")
    _note(reg, "lead-1", "2026-09-10T09:00:00-04:00")
    _note(reg, "lead-1", "2026-09-05T09:00:00-04:00")  # écrite après, mais plus ancienne
    assert _lister(reg)["leads"][0]["derniere_activite"] == "2026-09-10T09:00:00-04:00"


def test_un_lead_perdu_ou_avance_n_est_jamais_dormant_meme_sans_activite(pipeline):
    page = _lister(pipeline, horodatage="2027-09-29T12:00:00-04:00")  # un an plus tard
    assert _segments_de(page, "lead-perdu") == []
    assert "dormant_lead" not in _segments_de(page, "lead-converti")
    assert "dormant_lead" in _segments_de(page, "lead-nouveau")
    assert "dormant_lead" in _segments_de(page, "lead-qualifie")


def _fait_devis(lead_id: str, statut: str = "envoye", horodatage: str = "2026-09-01T12:00:00-04:00",
                devis_id: str = "devis-1") -> dict:
    return {"devis_id": devis_id, "lead_id": lead_id, "statut_devis": statut, "horodatage_devis": horodatage,
            "horodatage_reference": MAINTENANT, "delai_relance_jours": 7, "client_id": None}


def test_devis_perime_lu_des_faits_de_m3_pour_le_bon_lead_seulement(reg):
    _ingerer(reg, "lead-perime", "2026-08-01T09:00:00-04:00")
    _qualifier(reg, "lead-perime", horodatage="2026-08-01T10:00:00-04:00")
    _note(reg, "lead-perime", "2026-09-28T09:00:00-04:00")
    _ingerer(reg, "lead-autre", "2026-08-01T09:01:00-04:00")
    _qualifier(reg, "lead-autre", horodatage="2026-08-01T10:00:00-04:00")
    _note(reg, "lead-autre", "2026-09-28T09:00:00-04:00")
    page = _lister(reg, relances=[_fait_devis("lead-perime")])
    assert "quote_stale" in _segments_de(page, "lead-perime")
    assert "quote_stale" not in _segments_de(page, "lead-autre")
    assert _ids(_lister(reg, relances=[_fait_devis("lead-perime")], segment="quote_stale")) == ["lead-perime"]


def test_un_devis_brouillon_ou_recent_ne_rend_pas_le_lead_perime(reg):
    _ingerer(reg, "lead-1", "2026-08-01T09:00:00-04:00")
    _qualifier(reg, "lead-1", horodatage="2026-08-01T10:00:00-04:00")
    brouillon = _fait_devis("lead-1", statut="brouillon", horodatage="2026-08-01T12:00:00-04:00")
    recent = _fait_devis("lead-1", horodatage="2026-09-25T12:00:00-04:00", devis_id="devis-2")
    assert "quote_stale" not in _segments_de(_lister(reg, relances=[brouillon, recent]), "lead-1")


def test_faits_de_m3_illisibles_rendent_quote_stale_non_calculable_et_le_filtre_est_refuse(reg):
    _ingerer(reg, "lead-1", "2026-08-01T09:00:00-04:00")
    _qualifier(reg, "lead-1", horodatage="2026-08-01T10:00:00-04:00")
    page = _lister(reg, relances=None)
    assert "quote_stale" in [n["segment"] for n in page["segments_non_calculables"]]
    verdict = _lister(reg, verdict_attendu=True, relances=None, segment="quote_stale")
    assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE"
    assert "relances_devis_recues" in verdict["detail"]


def test_un_devis_a_l_horodatage_illisible_n_est_pas_un_lead_absent_du_filtre_il_est_indetermine(reg):
    _ingerer(reg, "lead-casse", "2026-08-01T09:00:00-04:00")
    _qualifier(reg, "lead-casse", horodatage="2026-08-01T10:00:00-04:00")
    _ingerer(reg, "lead-perime", "2026-08-01T09:01:00-04:00")
    _qualifier(reg, "lead-perime", horodatage="2026-08-01T10:00:00-04:00")
    relances = [_fait_devis("lead-casse", horodatage="hier", devis_id="devis-casse"),
                _fait_devis("lead-perime", devis_id="devis-bon")]
    filtre = _lister(reg, relances=relances, segment="quote_stale")
    assert _ids(filtre) == ["lead-perime"]
    assert filtre["total"] == 1
    assert filtre["indetermines"] == 1
    sans_filtre = _lister(reg, relances=relances)
    casse = next(i for i in sans_filtre["leads"] if i["lead_id"] == "lead-casse")
    assert casse["non_calculables"] == [{
        "segment": "quote_stale",
        "manque": "non calculable, manque l'horodatage lisible du devis devis-casse (m3.devis_sans_reponse)",
    }]
    autre = next(i for i in sans_filtre["leads"] if i["lead_id"] == "lead-perime")
    assert "non_calculables" not in autre


def test_les_statuts_avances_donnent_leurs_segments_par_la_vraie_machine_a_etats(reg):
    for i, statut in enumerate(("converti", "cedule", "chantier", "facture", "paiement", "avis")):
        _ingerer(reg, f"lead-{statut}", f"2026-09-01T09:0{i}:00-04:00")
        _amener_a(reg, f"lead-{statut}", statut)
    page = _lister(reg)
    assert _segments_de(page, "lead-converti") == ["won_pending_schedule"]
    assert _segments_de(page, "lead-cedule") == ["active_job"]
    assert _segments_de(page, "lead-chantier") == ["active_job"]
    assert _segments_de(page, "lead-facture") == ["invoice_pending"]
    assert _segments_de(page, "lead-paiement") == ["invoice_pending"]
    # un lead au statut avis est lui-même un chantier payé : son client est un ancien client
    assert _segments_de(page, "lead-avis") == ["past_customer"]
    converti = next(i for i in page["leads"] if i["lead_id"] == "lead-converti")
    assert converti["segments"][0]["donnee"]["reference_devis_m3"] == "devis-lead-converti"


def test_les_regles_citees_sont_celles_de_la_page_pas_de_toutes(pipeline):
    page = _lister(pipeline, statut="perdu")
    assert page["regles"] == {}
    page = _lister(pipeline, segment="hot_lead")
    assert page["regles"] == {"urgence_declaree_lead_ouvert": segments.REGLES["urgence_declaree_lead_ouvert"]}


def test_les_segments_non_calculables_sont_donnes_a_chaque_page_meme_vide(sept_leads):
    attendus = segments.segments_non_calculables(SEUILS_OK, True)
    assert _lister(sept_leads)["segments_non_calculables"] == attendus
    assert _lister(sept_leads, decalage=99)["segments_non_calculables"] == attendus
    assert _lister(sept_leads, visibles=set())["segments_non_calculables"] == attendus


# ---------------------------------------------------------------------------------------------------------
# Lecture seule, déterminisme, garde-fous
# ---------------------------------------------------------------------------------------------------------
def test_la_liste_n_ecrit_rien_et_rend_deux_fois_la_meme_page(pipeline):
    avant = copy.deepcopy(pipeline.lire())
    tete = pipeline.tete()
    premiere = _lister(pipeline)
    seconde = _lister(pipeline)
    assert premiere == seconde
    assert pipeline.lire() == avant
    assert pipeline.tete() == tete
    assert pipeline.valider_chaine() is True


def test_la_liste_ne_modifie_pas_les_maillons_ni_les_faits_qu_elle_recoit(pipeline):
    maillons = pipeline.lire()
    relances = [_fait_devis("lead-qualifie")]
    avant = copy.deepcopy((maillons, relances))
    liste_leads.lister(maillons, visibles=None, relances_devis=relances, seuils=SEUILS_OK, horodatage=MAINTENANT,
                       budget_caracteres=BUDGET)
    assert (maillons, relances) == avant


def test_un_horodatage_sans_fuseau_ou_illisible_est_refuse(sept_leads):
    for valeur in ("2026-09-29T12:00:00", "hier", "", None, 12):
        verdict = _lister(sept_leads, verdict_attendu=True, horodatage=valeur)
        assert verdict["code"] == "REJ-HORODATAGE-INVALIDE"


def test_un_registre_vide_donne_une_page_vide(reg):
    page = _lister(reg)
    assert page["leads"] == [] and page["total"] == 0 and page["suivant"] is None


def test_une_ligne_dont_le_lead_n_a_jamais_ete_ingere_n_est_pas_un_lead(reg):
    _ingerer(reg, "lead-1")
    maillons = reg.lire() + [{"type_entree": "interaction", "lead_id": "lead-fantome", "auteur": "x",
                              "resume": "y", "horodatage": "2026-09-01T09:00:00-04:00"}]
    page, verdict = liste_leads.lister(
        maillons, visibles=None, relances_devis=[], seuils=SEUILS_OK, horodatage=MAINTENANT, budget_caracteres=BUDGET)
    assert verdict is None
    assert _ids(page) == ["lead-1"]


def test_les_opportunites_par_client_egalent_celles_du_module_clients(reg):
    contact = {"nom": "Cliente Deux Affaires", "courriel": "deux@example.test"}
    _ingerer(reg, "lead-a", "2026-09-01T09:00:00-04:00", contact=contact)
    _ingerer(reg, "lead-b", "2026-09-02T09:00:00-04:00")
    _ingerer(reg, "lead-c", "2026-09-03T09:00:00-04:00", contact=contact)
    par_client = liste_leads._opportunites_par_client(reg.lire())
    assert set(par_client) == {clients.client_de_lead(reg, lead) for lead in ("lead-a", "lead-b", "lead-c")}
    for client_id, opportunites in par_client.items():
        assert opportunites == clients.opportunites_du_client(reg, client_id)


def test_identifiants_des_leads_sans_repetition_dans_l_ordre_du_registre(reg):
    _ingerer(reg, "lead-b", "2026-09-02T09:00:00-04:00")
    _ingerer(reg, "lead-a", "2026-09-01T09:00:00-04:00")
    _qualifier(reg, "lead-b")
    maillons = reg.lire()
    assert liste_leads.identifiants_des_leads(maillons) == ["lead-b", "lead-a"]
    # Un maillon d'ingestion rejoué (registre falsifié ou réimporté) ne fait pas un second lead.
    rejoue = next(m for m in maillons if m["type_entree"] == "lead_ingere" and m["lead_id"] == "lead-b")
    assert liste_leads.identifiants_des_leads([*maillons, rejoue, rejoue]) == ["lead-b", "lead-a"]


def test_un_lien_client_rejoue_ne_repete_pas_l_opportunite_comme_clients_opportunites_du_client(reg):
    """Même sémantique que `clients.opportunites_du_client` : dans l'ordre du registre, sans répétition, même si
    le maillon `client_associe` d'un lead est présent deux fois."""
    contact = {"nom": "Cliente Rejouee", "courriel": "rejouee@example.test"}
    _ingerer(reg, "lead-a", "2026-09-01T09:00:00-04:00", contact=contact)
    _ingerer(reg, "lead-b", "2026-09-02T09:00:00-04:00", contact=contact)
    maillons = reg.lire()
    lien = next(m for m in maillons if m["type_entree"] == "client_associe" and m["lead_id"] == "lead-a")
    rejoues = [*maillons, lien, lien]
    client_id = clients.client_de_lead(reg, "lead-a")
    assert liste_leads._opportunites_par_client(rejoues) == {client_id: ["lead-a", "lead-b"]}
    assert clients.opportunites_du_client(registre.Registre(maillons=rejoues), client_id) == ["lead-a", "lead-b"]


def test_le_module_est_pur_aucun_import_opsys_ni_horloge():
    source = Path(liste_leads.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import) opsys", source, re.M)
    assert "datetime.now" not in source
    assert "time.time" not in source


def test_recherche_contact_avant_pagination_et_visibilite(reg):
    for i in range(24):
        _ingerer(reg, f"aaa-sans-match-{i:02d}")
    for ident in ["cible-a", "cible-b", "cache-c"]:
        _ingerer(reg, ident, contact={"nom": "Élodie FICTIVE", "courriel": "elodie@example.test",
                                    "telephone": "514-555-0100"})
    _qualifier(reg, "cible-b")
    _note(reg, "cible-a", "2026-09-02T09:00:00-04:00")
    avant = reg.lire()
    page = _lister(reg, recherche="ELODIE example.test", visibles={"cible-a", "cible-b"}, limite=1)
    assert _ids(page) == ["cible-a"] and page["total"] == 2 and page["suivant"] == 1
    suite = _lister(reg, recherche="élodie", visibles={"cible-a", "cible-b"}, limite=1, decalage=1)
    assert _ids(suite) == ["cible-b"] and suite["suivant"] is None
    assert _lister(reg, recherche="Appel")["total"] == 0  # aucune recherche dans les notes
    assert _lister(reg, recherche="514-555", visibles={"cible-a"})["total"] == 1
    assert _lister(reg, recherche="cache-c", visibles={"cible-a"})["total"] == 0
    assert _ids(_lister(reg, recherche="elodie", statut="qualifie")) == ["cible-b"]
    assert reg.lire() == avant


@pytest.mark.parametrize("recherche", [123, [], "x" * 121, "\u0301"])
def test_recherche_invalide_refusee_sans_lecture_large(reg, recherche):
    _ingerer(reg, "un")
    avant = reg.lire()
    refus = _lister(reg, recherche=recherche, verdict_attendu=True)
    assert refus["code"] == "REJ-CONTRAT-INVALIDE"
    assert reg.lire() == avant


def test_recherche_vide_compatible_et_syntaxe_litterale(reg):
    _ingerer(reg, "un", contact={"nom": "Alpha FICTIF", "courriel": "a@example.test"})
    assert _lister(reg, recherche="  ") == _lister(reg)
    assert _lister(reg, recherche=None) == _lister(reg)
    assert _lister(reg, recherche=".*")["total"] == 0
    assert _lister(reg, recherche="' OR 1=1 --")["total"] == 0
