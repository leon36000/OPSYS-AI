"""PLAN T4.27-a : `m4_lister_interventions` par pages, sur les VRAIS outils, une base SQLite migrée et de vraies
personnes.

`m4_lister_interventions` rendait la liste entière ; le socle (`Capacites`) la coupait à 6 000 caractères, et l'app de
l'admin lisait un aperçu, pas une liste (T4.20 : « un appel par statut »). `curseur` et `taille_page` sont des clés
SŒURS additives : sans elles, la liste v1 est rendue telle qu'avant ; avec l'une des deux, une page
`{interventions, page}`.

Ce que ce fichier prouve :

  * sans clé de pagination, la réponse est la liste v1, octet pour octet ; avec l'une des deux clés (même nulle), une
    page ;
  * l'admin lit TOUTES les interventions, une seule fois, dans l'ordre, chaque page sous la borne du socle (jamais
    tronquée, alors que la liste v1 entière l'est) ;
  * l'employé ne voit que SES interventions, page par page : `total`, `reste` et `curseur_suivant` ne comptent jamais
    celles des autres, et un curseur pris chez un autre ne révèle rien ;
  * le statut demandé filtre avant la pagination ; la lecture n'écrit rien ;
  * un curseur ou une taille mal formés sont refusés (`refus_metier`, `REJ-CONTRAT-INVALIDE`), une identité invalide
    aussi.

Le scénario par la porte d'appareil est `tests/e2e/test_lectures_admin_m4_appareil.py`.
Données fictives (`fictif: true`) : personnes, appareils et identifiants portent « fictif ».
"""

from __future__ import annotations

import contextlib
import json

import pytest
from m4_field_ops import etats, pagination_interventions
from m4_field_ops import outils as outils_m4
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import outils

from opsys import contexte, identite, jetons, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer_atomique

FICTIF = True
SEL = "sel-t4-27-a-fictif"
VILLE = "Montreal"
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
LEA = contexte.IdentiteAppelante(personne="lea.fictif", role="employee")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
INCONNUE = contexte.IdentiteAppelante(personne="fantome.fictif", role="employee")
NOMBRE = 45  # de quoi remplir trois pages sous la borne de 6 000 caractères
LIMITE_SOCLE = jetons.LIMITE_SORTIE_DEFAUT


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345", ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in outils()}


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _maillons():
    with stockage.transaction():
        return json.dumps(registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")).lire(), sort_keys=True)


def _contrat(lead_id):
    return {
        "lead_id": lead_id,
        "conversation_id": "C1",
        "type_travaux": "renovation_totale",
        "ville": VILLE,
        "canal": "telephone",
        "contact": {"nom": "Client fictif", "telephone": "0102030405"},
        "urgence_declaree": False,
    }


def _marqueur(lead_id):
    return {
        "readiness_ok": True,
        "lead_id": lead_id,
        "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00",
        "empreinte": "ab" * 32,
    }


def _planifier(par_nom, lead_id, technicien) -> str:
    """Un agent inscrit et cédule l'intervention, assignée à `technicien` (`m4_planifier_intervention`)."""
    reponse = _appeler(
        par_nom,
        "m4_planifier_intervention",
        {
            "contrat": _contrat(lead_id),
            "marqueur": _marqueur(lead_id),
            "horodatage": "2025-06-02T06:00:00+00:00",
            "sel": SEL,
            "techniciens_disponibles": [technicien],
            "fenetres_disponibles": [FENETRE],
        },
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["intervention_id"]


@pytest.fixture
def monde(par_nom):
    """45 interventions planifiées : 30 à Marc, 15 à Léa. `{intervention_id: technicien}`."""
    assignees = {}
    for numero in range(NOMBRE):
        technicien = "lea.fictif" if numero % 3 == 0 else "marc.fictif"
        assignees[_planifier(par_nom, f"L-PAGE-{numero:02d}", technicien)] = technicien
    assert sum(1 for t in assignees.values() if t == "lea.fictif") == 15
    return assignees


def _liste(par_nom, arguments=None, identite_appelante=None):
    reponse = _appeler(par_nom, "m4_lister_interventions", arguments or {}, identite_appelante)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _mesure(page) -> int:
    """Ce que `Capacites` mesure pour une réponse de l'outil : l'enveloppe `{ok, resultat}`."""
    return len(json.dumps({"ok": True, "resultat": page}, ensure_ascii=False))


def _lire_toutes_les_pages(par_nom, identite_appelante=None, arguments=None, maximum=30):
    """Comme l'app : première page sans curseur, puis `curseur_suivant` tant qu'il n'est pas nul."""
    pages, curseur = [], None
    for _ in range(maximum):
        page = _liste(par_nom, {**(arguments or {}), "curseur": curseur}, identite_appelante)
        pages.append(page)
        curseur = page["page"]["curseur_suivant"]
        if curseur is None:
            return pages
    raise AssertionError("la lecture ne progresse pas")


def _ids(pages):
    return [ligne["intervention_id"] for page in pages for ligne in page["interventions"]]


# =========================================================================================
# 1. L'outil : lecture T0, ouvert à l'employé et à l'admin, clés sœurs décrites
# =========================================================================================
def test_l_outil_reste_une_lecture_ouverte_a_l_employe_et_a_l_admin_avec_deux_cles_soeurs(par_nom):
    outil = par_nom["m4_lister_interventions"]
    assert outil.autonomie is Autonomie.T0 and outil.roles_appareil == frozenset({"employee", "admin"})
    assert set(outil.parametres["properties"]) == {"statut", "curseur", "taille_page"}
    assert outil.parametres["additionalProperties"] is False and "required" not in outil.parametres
    curseur, taille = outil.parametres["properties"]["curseur"], outil.parametres["properties"]["taille_page"]
    assert curseur["type"] == ["string", "null"] and curseur["pattern"] == pagination_interventions.FORME_CURSEUR
    assert taille["type"] == ["integer", "null"] and (taille["minimum"], taille["maximum"]) == (1, 50)
    assert len(outil.description) <= 1024
    for mot in ("curseur", "taille_page", "page.reste", "page.curseur_suivant", "6 000"):
        assert mot in outil.description, mot


def test_les_cles_du_contrat_v1_de_la_liste_n_ont_pas_change(par_nom, monde):
    """Le contrat v1 est gelé : la clé `statut` garde son schéma, la liste garde ses sept clés."""
    outil = par_nom["m4_lister_interventions"]
    assert outil.parametres["properties"]["statut"] == {"type": ["string", "null"], "enum": [*etats.ETATS, None]}
    for ligne in _liste(par_nom):
        assert set(ligne) == {
            "intervention_id",
            "statut",
            "lead_id",
            "type_travaux",
            "devis_id",
            "technicien_assigne",
            "fenetre_planifiee",
        }


# =========================================================================================
# 2. Sans clé de pagination : la liste v1, telle qu'avant
# =========================================================================================
def test_sans_cle_de_pagination_la_reponse_est_la_liste_v1_octet_pour_octet(par_nom, monde):
    liste = _liste(par_nom)
    assert isinstance(liste, list) and len(liste) == NOMBRE
    with stockage.transaction():
        attendue = etats.lister_interventions(registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")))
    assert json.dumps(liste, sort_keys=True) == json.dumps(attendue, sort_keys=True)
    assert [ligne["intervention_id"] for ligne in liste] == sorted(monde)
    filtree = _liste(par_nom, {"statut": "planifiee"})
    assert isinstance(filtree, list) and len(filtree) == NOMBRE
    assert _liste(par_nom, {"statut": "annulee"}) == []


@pytest.mark.parametrize(
    "arguments", [{"curseur": None}, {"taille_page": None}, {"curseur": None, "taille_page": None}]
)
def test_l_une_des_deux_cles_meme_nulle_demande_une_page(par_nom, monde, arguments):
    page = _liste(par_nom, arguments)
    assert isinstance(page, dict) and set(page) == {"interventions", "page"}
    assert page["page"]["curseur"] is None and page["page"]["taille_demandee"] is None
    assert page["page"]["total"] == NOMBRE


def test_avec_taille_page_seule_la_premiere_page_a_cette_taille_et_le_reste_suit(par_nom, monde):
    page = _liste(par_nom, {"taille_page": 10})
    assert page["page"]["taille"] == len(page["interventions"]) == 10
    assert (page["page"]["total"], page["page"]["reste"]) == (NOMBRE, NOMBRE - 10)
    assert page["page"]["curseur_suivant"] == page["interventions"][-1]["intervention_id"]
    assert page["page"]["taille_demandee"] == 10 and page["page"]["borne_atteinte"] is False


# =========================================================================================
# 3. L'admin lit tout, une seule fois, sous la borne du socle
# =========================================================================================
def test_l_admin_lit_les_quarante_cinq_interventions_page_par_page_chacune_une_seule_fois(par_nom, monde):
    pages = _lire_toutes_les_pages(par_nom, ADMIN)
    assert len(pages) >= 3, "la liste ne tient pas en une page : c'est ce que la pagination répare"
    ids = _ids(pages)
    assert ids == sorted(monde) and len(set(ids)) == NOMBRE
    for page in pages:
        assert _mesure(page) <= outils_m4._LIMITE_REPONSE_LECTURE < LIMITE_SOCLE
        assert page["page"]["total"] == NOMBRE and page["page"]["taille"] == len(page["interventions"]) >= 1
    assert all(page["page"]["borne_atteinte"] is True for page in pages[:-1])
    assert pages[-1]["page"]["borne_atteinte"] is False and pages[-1]["page"]["reste"] == 0
    assert pages[-1]["page"]["curseur_suivant"] is None
    restant = NOMBRE
    for page in pages:
        restant -= page["page"]["taille"]
        assert page["page"]["reste"] == restant
        assert (page["page"]["curseur_suivant"] is None) == (restant == 0)


def test_les_lignes_d_une_page_sont_celles_de_la_liste_v1(par_nom, monde):
    v1 = {ligne["intervention_id"]: ligne for ligne in _liste(par_nom)}
    for page in _lire_toutes_les_pages(par_nom, ADMIN):
        for ligne in page["interventions"]:
            assert ligne == v1[ligne["intervention_id"]]


def test_le_socle_coupe_la_liste_v1_entiere_mais_jamais_une_page(par_nom, monde):
    """La raison d'être de T4.27-a, mesurée par le VRAI socle (`Capacites`, 6 000 caractères)."""
    capacites = Capacites(charger_departements(), stockage.transaction, memoire=False)
    entiere = capacites.appeler("m4_lister_interventions", {})
    assert entiere.get("tronque") is True and "resultat" not in entiere, "l'app lirait un aperçu coupé"
    curseur = None
    lues = []
    for _ in range(10):
        reponse = capacites.appeler("m4_lister_interventions", {"curseur": curseur})
        assert reponse["ok"] is True and "tronque" not in reponse, reponse
        assert len(json.dumps(reponse, ensure_ascii=False)) < LIMITE_SOCLE
        lues.extend(ligne["intervention_id"] for ligne in reponse["resultat"]["interventions"])
        curseur = reponse["resultat"]["page"]["curseur_suivant"]
        if curseur is None:
            break
    assert lues == sorted(monde)


def test_deux_lectures_donnent_les_memes_pages(par_nom, monde):
    assert _lire_toutes_les_pages(par_nom, ADMIN) == _lire_toutes_les_pages(par_nom, ADMIN)


def test_la_lecture_par_pages_n_ecrit_rien(par_nom, monde):
    avant = _maillons()
    _lire_toutes_les_pages(par_nom, ADMIN)
    _lire_toutes_les_pages(par_nom, MARC)
    _liste(par_nom, {"taille_page": 3, "statut": "planifiee"})
    assert _maillons() == avant


def test_une_intervention_qui_nait_entre_deux_pages_ne_fait_ni_sauter_ni_repeter(par_nom, monde):
    premiere = _liste(par_nom, {"taille_page": 20}, ADMIN)
    vues = _ids([premiere])
    nouvelle = _planifier(par_nom, "L-PAGE-NAISSANTE", "marc.fictif")
    suite, curseur = [], premiere["page"]["curseur_suivant"]
    for _ in range(10):
        page = _liste(par_nom, {"curseur": curseur, "taille_page": 20}, ADMIN)
        suite.append(page)
        curseur = page["page"]["curseur_suivant"]
        if curseur is None:
            break
    lues = vues + _ids(suite)
    assert len(lues) == len(set(lues)), "aucune répétition"
    assert set(monde) <= set(lues), "aucune intervention d'avant n'est sautée"
    assert suite[-1]["page"]["total"] == NOMBRE + 1 != premiere["page"]["total"], "le signal : le total a changé"
    assert (nouvelle in lues) == (nouvelle > vues[-1])


# =========================================================================================
# 4. L'employé ne voit que SES interventions, page par page
# =========================================================================================
def test_l_employe_ne_lit_que_ses_interventions_et_les_pages_ne_comptent_pas_celles_des_autres(par_nom, monde):
    siennes = sorted(i for i, technicien in monde.items() if technicien == "marc.fictif")
    assert len(siennes) == 30
    pages = _lire_toutes_les_pages(par_nom, MARC)
    assert _ids(pages) == siennes
    for page in pages:
        assert page["page"]["total"] == 30, "le total ne compte que les interventions qu'il a le droit de voir"
        assert {ligne["technicien_assigne"] for ligne in page["interventions"]} == {"marc.fictif"}
        assert _mesure(page) <= outils_m4._LIMITE_REPONSE_LECTURE
    assert pages[-1]["page"]["reste"] == 0 and pages[-1]["page"]["curseur_suivant"] is None
    restant = 30
    for page in pages:
        restant -= page["page"]["taille"]
        assert page["page"]["reste"] == restant
    lea = _lire_toutes_les_pages(par_nom, LEA, {"taille_page": 4})
    assert _ids(lea) == sorted(i for i, technicien in monde.items() if technicien == "lea.fictif")
    assert {page["page"]["total"] for page in lea} == {15} and len(lea) == 4


def test_le_curseur_d_un_autre_employe_ne_revele_rien_de_ses_interventions(par_nom, monde):
    de_lea = sorted(i for i, technicien in monde.items() if technicien == "lea.fictif")
    siennes = sorted(i for i, technicien in monde.items() if technicien == "marc.fictif")
    # Marc donne l'identifiant d'une intervention de Léa comme curseur : il ne reçoit que SES interventions au-delà.
    curseur = de_lea[7]
    page = _liste(par_nom, {"curseur": curseur, "taille_page": 50}, MARC)
    assert page["page"]["total"] == 30 and page["page"]["curseur"] == curseur
    audela = [i for i in siennes if i > curseur]
    assert _ids([page]) == audela[: page["page"]["taille"]]
    assert page["page"]["reste"] == len(audela) - page["page"]["taille"], "le reste ne compte que les siennes"
    lues = _ids([page])
    while page["page"]["curseur_suivant"] is not None:
        page = _liste(par_nom, {"curseur": page["page"]["curseur_suivant"], "taille_page": 50}, MARC)
        lues += _ids([page])
    assert lues == audela
    assert set(lues).isdisjoint(de_lea), "aucune intervention de Léa, ni dans les lignes ni dans les comptes"


def test_un_employe_sans_intervention_recoit_une_page_vide_qui_le_dit(par_nom, personnes, monde):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nadia.fictif", "Nadia Fictive", "mot-de-passe-nadia-1234", ["employee"])
    page = _liste(par_nom, {"curseur": None}, contexte.IdentiteAppelante(personne="nadia.fictif", role="employee"))
    assert page["interventions"] == []
    assert (page["page"]["total"], page["page"]["reste"], page["page"]["curseur_suivant"]) == (0, 0, None)


def test_l_admin_voit_toutes_les_interventions_dans_les_pages(par_nom, monde):
    pages = _lire_toutes_les_pages(par_nom, ADMIN)
    assert {ligne["technicien_assigne"] for page in pages for ligne in page["interventions"]} == {
        "marc.fictif",
        "lea.fictif",
    }
    assert pages[0]["page"]["total"] == NOMBRE


# =========================================================================================
# 5. Le statut filtre AVANT la pagination
# =========================================================================================
def test_le_statut_demande_filtre_avant_la_pagination(par_nom, monde):
    en_route = sorted(monde)[3]
    technicien = monde[en_route]
    identite_technicien = contexte.IdentiteAppelante(personne=technicien, role="employee")
    reponse = _appeler(
        par_nom,
        "m4_demarrer_route",
        {"intervention_id": en_route, "technicien_id": technicien, "horodatage": "2025-06-02T07:30:00+00:00"},
        identite_technicien,
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    page = _liste(par_nom, {"statut": "en_route", "taille_page": 5}, ADMIN)
    assert _ids([page]) == [en_route]
    assert (page["page"]["total"], page["page"]["reste"], page["page"]["curseur_suivant"]) == (1, 0, None)
    planifiees = _lire_toutes_les_pages(par_nom, ADMIN, {"statut": "planifiee"})
    assert _ids(planifiees) == sorted(set(monde) - {en_route})
    assert {page["page"]["total"] for page in planifiees} == {NOMBRE - 1}
    assert _liste(par_nom, {"statut": "annulee", "curseur": None}, ADMIN)["interventions"] == []


# =========================================================================================
# 6. Refus : rien n'est corrigé en silence, rien n'est écrit
# =========================================================================================
@pytest.mark.parametrize(
    "curseur", ["", "abc", "X" * 64, "a" * 63, "a" * 65, ("ab" * 32).upper(), "intervention-fantome"]
)
def test_un_curseur_mal_forme_est_un_refus_metier_qui_ne_lit_rien(par_nom, monde, curseur):
    avant = _maillons()
    reponse = _appeler(par_nom, "m4_lister_interventions", {"curseur": curseur}, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "REJ-CONTRAT-INVALIDE" in reponse["details"] and "curseur_suivant" in reponse["details"]
    assert _maillons() == avant


@pytest.mark.parametrize("taille", [0, -1, 51, 500])
def test_une_taille_de_page_hors_bornes_est_un_refus_metier_jamais_bornee_en_silence(par_nom, monde, taille):
    reponse = _appeler(par_nom, "m4_lister_interventions", {"taille_page": taille}, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "REJ-CONTRAT-INVALIDE" in reponse["details"] and "1 à 50" in reponse["details"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"taille_page": "3"},
        {"taille_page": 2.5},
        {"taille_page": True},
        {"curseur": 12},
        {"curseur": ["a"]},
        {"page": 2},
        {"limite": 5},
        {"decalage": 3},
        {"personne": "marc.fictif"},
    ],
)
def test_le_socle_refuse_un_mauvais_type_et_toute_cle_inconnue(par_nom, monde, arguments):
    reponse = _appeler(par_nom, "m4_lister_interventions", arguments, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"


def test_le_statut_hors_catalogue_reste_refuse_avec_la_pagination(par_nom, monde):
    reponse = _appeler(par_nom, "m4_lister_interventions", {"statut": "statut_pirate", "taille_page": 5}, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"


def test_une_identite_non_confirmee_est_refusee_meme_avec_la_pagination(par_nom, monde):
    for arguments in ({}, {"curseur": None}, {"taille_page": 5}):
        reponse = _appeler(par_nom, "m4_lister_interventions", arguments, INCONNUE)
        assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
        assert "REJ-IDENTITE-APPAREIL-INVALIDE" in reponse["details"]


def test_un_vendeur_n_a_pas_de_portee_sur_la_liste_et_le_code_ne_l_ouvre_pas(par_nom, monde):
    """La portée (`roles_appareil`) le refuse à la porte ; ici, l'identité d'un vendeur n'a aucune portée sur M4."""
    vendeur = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
    reponse = _appeler(par_nom, "m4_lister_interventions", {"taille_page": 5}, vendeur)
    assert reponse["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in reponse["details"]


# =========================================================================================
# 7. La borne pilote la page
# =========================================================================================
def test_la_limite_de_la_page_est_celle_de_l_appareil_moins_une_marge():
    assert outils_m4._LIMITE_REPONSE_LECTURE == jetons.LIMITE_SORTIE_DEFAUT - 500


def test_la_limite_pilote_la_taille_de_la_page_et_une_limite_trop_serree_est_un_refus(par_nom, monde, monkeypatch):
    normale = _liste(par_nom, {"curseur": None}, ADMIN)
    monkeypatch.setattr(outils_m4, "_LIMITE_REPONSE_LECTURE", 1500)
    serree = _liste(par_nom, {"curseur": None}, ADMIN)
    assert 1 <= serree["page"]["taille"] < normale["page"]["taille"] and _mesure(serree) <= 1500
    assert serree["page"]["borne_atteinte"] is True
    monkeypatch.setattr(outils_m4, "_LIMITE_REPONSE_LECTURE", 300)
    refus = _appeler(par_nom, "m4_lister_interventions", {"curseur": None}, ADMIN)
    assert refus["ok"] is False and refus["erreur"] == "refus_metier" and "à elle seule" in refus["details"]
    monkeypatch.setattr(outils_m4, "_LIMITE_REPONSE_LECTURE", 10**9)
    assert _liste(par_nom, {"curseur": None}, ADMIN)["page"]["taille"] == NOMBRE
