"""Le propriétaire liste et décide les demandes d'approbation depuis son téléphone (PLAN T1.4-f, étape 6).

Deux étages. Le premier exerce la logique (`opsys.approbations_appareil`) sur le département de démonstration
du socle, où chaque garde se prouve seule. Le second passe par les VRAIS outils M9 (`m9_lister_demandes_
approbation`, `m9_decider_demande_approbation`) et `Capacites.appeler` avec le `_meta` d'idempotence et
`contexte.appele_par_appareil`, exactement ce que `serveur_mcp.appeler_outil` pose : la décision, son
rejeu et ses refus, de bout en bout. Personnes, appareils, clés : fictifs (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
from pathlib import Path

import demo_outils
import pytest
from sqlalchemy import select, update

from opsys import approbations, approbations_appareil, contexte, etat, idempotence, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import PolitiqueApprobation, charger_departements
from opsys.outils import Niveau
from opsys.stockage.schema import APPROBATIONS

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[1] / "departments"
DEP_DEMO = "m09-demo"

PROPRIO = contexte.IdentiteAppelante(personne="proprio.fictif", role="admin")
GESTIONNAIRE = contexte.IdentiteAppelante(personne="gestionnaire.fictif", role="admin")
EMPLOYE = contexte.IdentiteAppelante(personne="employe.fictif", role="employee")
INACTIF = contexte.IdentiteAppelante(personne="inactif.fictif", role="admin")
APPAREIL = "tel-proprio-fictif-1"
FIX_GPS = {"latitude": 45.508812, "longitude": -73.587834}


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def personnes(session):
    with session() as cnx:
        identite.creer_personne(cnx, "proprio.fictif", "Propriétaire Fictif", "mot-de-passe-proprio-1234",
                                ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "gestionnaire.fictif", "Gestionnaire Fictive", "mot-de-passe-gestion-1234",
                                ["admin", "manager"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
        identite.creer_personne(cnx, "inactif.fictif", "Inactif Fictif", "mot-de-passe-inactif-1234",
                                ["admin", "nathan_owner"], actif=False)


@pytest.fixture(autouse=True)
def _vider_les_temoins():
    demo_outils.JOURNAL.clear()
    demo_outils.IDENTITES_VUES.clear()
    demo_outils.HORODATAGES_VUS.clear()
    yield
    demo_outils.JOURNAL.clear()


def _demande(cnx, outil="m9_pointer", arguments=None, niveau=Niveau.N3, departement=DEP_DEMO, depuis=None):
    ident = approbations.creer_demande(
        cnx, departement, outil, {"appareil": "T1"} if arguments is None else arguments, niveau=niveau)
    if depuis is not None:
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(cree_le=depuis))
    return ident


def _lister(session, departements, identite_appelante=PROPRIO, **kw):
    with session() as cnx:
        return approbations_appareil.lister_demandes(cnx, departements, identite_appelante, **kw)


def _decider(session, departements, ident, decision="approuver", identite_appelante=PROPRIO, motif="",
             appareil=APPAREIL):
    with session() as cnx:
        return approbations_appareil.decider_demande(
            cnx, departements, identite_appelante, ident, decision, motif, appareil=appareil)


def _statut(session, ident):
    with session() as cnx:
        return approbations.lire(cnx, ident)


def _journal(session, action=None):
    with session() as cnx:
        return [e for e in etat.lire_journal(cnx) if action is None or e["action"] == action]


# ============================ étage 1 : la logique, sur le département de démonstration ==============
# -- lister ------------------------------------------------------------------------------------------
def test_le_proprietaire_voit_la_file_du_plus_ancien_au_plus_recent_avec_les_arguments(
    session, personnes, departements_demo
):
    with session() as cnx:
        recente = _demande(cnx, "m9_pointer", {"appareil": "R"}, depuis="2026-09-20T10:00:00+00:00")
        ancienne = _demande(cnx, "m9_envoyer_message", {"destinataire": "a@b.c", "texte": "Bonjour"},
                            Niveau.N4, depuis="2026-09-01T10:00:00+00:00")

    resultat, verdict = _lister(session, departements_demo)

    assert verdict is None
    assert [d["id"] for d in resultat["demandes"]] == [ancienne, recente]
    premiere = resultat["demandes"][0]
    assert premiere["outil"] == "m9_envoyer_message"
    assert premiere["niveau"] == "N4"
    assert premiere["arguments"] == {"destinataire": "a@b.c", "texte": "Bonjour"}
    assert premiere["decidable"] is True and premiere["lecture_seule"] is None
    assert premiere["departement"] == DEP_DEMO and premiere["departement_nom"] == "Démo"
    assert premiere["description_outil"] == "Envoie un message à un client."
    assert (resultat["total_en_attente"], resultat["affichees"], resultat["reste"]) == (2, 2, 0)
    assert resultat["proprietaire"] is True


def test_une_file_vide_est_une_reponse_pas_une_erreur(session, personnes, departements_demo):
    resultat, verdict = _lister(session, departements_demo)

    assert verdict is None
    assert resultat["demandes"] == [] and resultat["total_en_attente"] == 0 and resultat["reste"] == 0


def test_la_liste_ne_montre_que_les_demandes_en_attente(session, personnes, departements_demo):
    with session() as cnx:
        traitee = _demande(cnx)
        attente = _demande(cnx, "m9_envoyer_message", {"destinataire": "x", "texte": "y"}, Niveau.N4)
    _decider(session, departements_demo, traitee, "refuser")

    resultat, _ = _lister(session, departements_demo)

    assert [d["id"] for d in resultat["demandes"]] == [attente]
    assert resultat["total_en_attente"] == 1


def test_n5_est_montre_en_lecture_seule_a_decider_a_la_console(session, personnes, departements_demo):
    with session() as cnx:
        paiement = _demande(cnx, "m9_payer", {"montant": 1500}, Niveau.N5)

    resultat, _ = _lister(session, departements_demo)

    [item] = resultat["demandes"]
    assert item["id"] == paiement and item["niveau"] == "N5"
    assert item["decidable"] is False
    assert item["lecture_seule"]["code"] == "n5_a_la_console"
    assert "à décider à la console" in item["lecture_seule"]["detail"]
    assert item["arguments"] == {"montant": 1500}  # le propriétaire le voit, il ne le décide pas ici


def test_une_ancienne_demande_sans_niveau_est_lue_n5(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(niveau=None))

    resultat, _ = _lister(session, departements_demo)

    [item] = resultat["demandes"]
    assert item["niveau"] is None  # jamais deviné à l'affichage
    assert item["decidable"] is False and item["lecture_seule"]["code"] == "n5_a_la_console"


def test_un_outil_t3_n_est_jamais_decidable_meme_a_un_niveau_n4(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx, "m9_payer", {"montant": 1}, Niveau.N4)

    resultat, _ = _lister(session, departements_demo)

    assert resultat["demandes"][0]["lecture_seule"]["code"] == "outil_frontiere_humaine"
    refus, verdict = _decider(session, departements_demo, ident)
    assert refus is None and verdict["code"] == "outil_frontiere_humaine"
    assert demo_outils.JOURNAL == []
    assert _statut(session, ident)["statut"] == "en_attente"


def test_un_outil_inconnu_du_serveur_est_en_lecture_seule(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx, "m9_outil_disparu", {})

    resultat, _ = _lister(session, departements_demo)
    _, verdict = _decider(session, departements_demo, ident)

    assert resultat["demandes"][0]["lecture_seule"]["code"] == "outil_inconnu"
    assert verdict["code"] == "outil_inconnu"


def test_l_admin_qui_n_est_pas_le_proprietaire_voit_la_file_sans_les_arguments(
    session, personnes, departements_demo
):
    with session() as cnx:
        _demande(cnx, "m9_envoyer_message", {"destinataire": "prive@x.ca", "texte": "montant 12 345 $"}, Niveau.N4)

    resultat, verdict = _lister(session, departements_demo, GESTIONNAIRE)

    assert verdict is None and resultat["proprietaire"] is False
    [item] = resultat["demandes"]
    assert item["outil"] == "m9_envoyer_message" and item["niveau"] == "N4"
    assert item["arguments"] is None
    assert item["decidable"] is False and item["lecture_seule"]["code"] == "reserve_au_proprietaire"
    assert "12 345" not in json.dumps(resultat, ensure_ascii=False)


def test_le_fix_gps_n_est_jamais_affiche(session, personnes, departements_demo):
    with session() as cnx:
        _demande(cnx, "m9_pointer", {"appareil": "T1", "fix_gps": FIX_GPS})

    resultat, _ = _lister(session, departements_demo)

    [item] = resultat["demandes"]
    assert item["arguments"]["fix_gps"] == approbations.VALEUR_MASQUEE
    assert "45.508812" not in json.dumps(resultat, ensure_ascii=False)


def test_des_arguments_trop_gros_pour_le_telephone_laissent_la_demande_a_la_console(
    session, personnes, departements_demo
):
    with session() as cnx:
        ident = _demande(cnx, "m9_pointer", {"appareil": "z" * (approbations_appareil.LIMITE_ARGUMENTS + 1)})

    resultat, _ = _lister(session, departements_demo)
    _, verdict = _decider(session, departements_demo, ident)

    [item] = resultat["demandes"]
    assert item["arguments"] is None
    assert item["lecture_seule"]["code"] == "arguments_trop_volumineux"
    assert verdict["code"] == "arguments_trop_volumineux"
    assert demo_outils.JOURNAL == [] and _statut(session, ident)["statut"] == "en_attente"


def test_la_liste_reste_sous_la_troncature_des_outils_et_compte_ce_qu_elle_ne_montre_pas(
    session, personnes, departements_demo
):
    with session() as cnx:
        for i in range(8):
            _demande(cnx, "m9_pointer", {"appareil": "y" * 1400}, depuis=f"2026-09-0{i + 1}T10:00:00+00:00")

    resultat, verdict = _lister(session, departements_demo)

    assert verdict is None
    assert len(json.dumps({"ok": True, "resultat": {"accepte": True, "resultat": resultat}},
                          ensure_ascii=False)) < 6000  # jetons.LIMITE_SORTIE_DEFAUT
    assert resultat["total_en_attente"] == 8
    assert 0 < resultat["affichees"] < 8
    assert resultat["reste"] == 8 - resultat["affichees"]
    # les plus anciennes d'abord : ce qui n'est pas montré est le plus récent
    assert [d["depuis"] for d in resultat["demandes"]] == sorted(d["depuis"] for d in resultat["demandes"])
    assert resultat["demandes"][0]["depuis"].startswith("2026-09-01")


@pytest.mark.parametrize("limite", [0, -1, 51, 2.5, "10", True, None])
def test_une_limite_invalide_est_refusee(session, personnes, departements_demo, limite):
    resultat, verdict = _lister(session, departements_demo, limite=limite)

    assert resultat is None and verdict["code"] == "limite_invalide"


def test_la_limite_borne_le_nombre_de_demandes_lues(session, personnes, departements_demo):
    with session() as cnx:
        for i in range(3):
            _demande(cnx, depuis=f"2026-09-0{i + 1}T10:00:00+00:00")

    resultat, _ = _lister(session, departements_demo, limite=2)

    assert (resultat["total_en_attente"], resultat["affichees"], resultat["reste"]) == (3, 2, 1)


# -- les attentes des départements : l'autre moitié de la file du propriétaire (PLAN T1.5) ---------------
def _attente(ident="wct-1", resume="Écart matériaux critique sur le chantier CH-1", depuis="2026-09-01T00:00:00+00:00",
             type_="chantier_a_reviser"):
    return {"type": type_, "id": ident, "resume": resume, "niveau": "N4", "depuis": depuis,
            "action_proposee": "réviser et approuver"}


@pytest.fixture
def attentes_demo():
    demo_outils.ATTENTES_DEMO.clear()
    yield demo_outils.ATTENTES_DEMO
    demo_outils.ATTENTES_DEMO.clear()


def test_la_liste_montre_les_attentes_des_departements_sans_les_confondre_avec_des_demandes(
    session, personnes, departements_demo, attentes_demo
):
    attentes_demo.append(_attente())
    with session() as cnx:
        demande = _demande(cnx)

    resultat, verdict = _lister(session, departements_demo)

    assert verdict is None
    assert [d["id"] for d in resultat["demandes"]] == [demande]
    assert resultat["attentes"] == [{
        "type": "chantier_a_reviser", "id": "wct-1", "departement": DEP_DEMO, "departement_nom": "Démo",
        "resume": "Écart matériaux critique sur le chantier CH-1", "niveau": "N4",
        "depuis": "2026-09-01T00:00:00+00:00", "action_proposee": "réviser et approuver",
    }]
    assert (resultat["total_attentes"], resultat["attentes_affichees"], resultat["attentes_reste"]) == (1, 1, 0)
    assert resultat["attentes_illisibles"] == []
    # Une attente n'est pas décidable ici : ni `decidable`, ni arguments, ni compte parmi les demandes.
    assert "decidable" not in resultat["attentes"][0] and "arguments" not in resultat["attentes"][0]
    assert resultat["total_en_attente"] == 1


def test_sans_attente_la_liste_le_dit(session, personnes, departements_demo, attentes_demo):
    resultat, verdict = _lister(session, departements_demo)

    assert verdict is None
    assert resultat["attentes"] == []
    assert (resultat["total_attentes"], resultat["attentes_affichees"], resultat["attentes_reste"]) == (0, 0, 0)
    assert resultat["attentes_illisibles"] == []


def test_l_admin_qui_n_est_pas_le_proprietaire_voit_aussi_les_attentes(
    session, personnes, departements_demo, attentes_demo
):
    attentes_demo.append(_attente())

    resultat, verdict = _lister(session, departements_demo, GESTIONNAIRE)

    assert verdict is None and resultat["proprietaire"] is False
    assert [a["id"] for a in resultat["attentes"]] == ["wct-1"]  # comme le briefing du matin de M9


def test_un_employe_ne_voit_aucune_attente(session, personnes, departements_demo, attentes_demo):
    attentes_demo.append(_attente())

    resultat, verdict = _lister(session, departements_demo, EMPLOYE)

    assert resultat is None and verdict["code"] == "role_appareil_insuffisant"


def test_les_attentes_les_plus_anciennes_d_abord_et_le_reste_est_compte(
    session, personnes, departements_demo, attentes_demo
):
    for i in range(12):
        attentes_demo.append(_attente(f"wct-{i:02d}", "x" * 240, f"2026-09-{i + 1:02d}T00:00:00+00:00"))

    resultat, verdict = _lister(session, departements_demo)

    assert verdict is None
    assert resultat["total_attentes"] == 12
    assert 0 < resultat["attentes_affichees"] < 12
    assert resultat["attentes_reste"] == 12 - resultat["attentes_affichees"]
    assert [a["id"] for a in resultat["attentes"]] == [f"wct-{i:02d}" for i in range(resultat["attentes_affichees"])]


def test_la_liste_avec_attentes_reste_sous_la_troncature_des_outils(
    session, personnes, departements_demo, attentes_demo
):
    for i in range(12):
        attentes_demo.append(_attente(f"wct-{i:02d}", "x" * 400, f"2026-09-{i + 1:02d}T00:00:00+00:00"))
    with session() as cnx:
        for i in range(8):
            _demande(cnx, "m9_pointer", {"appareil": "y" * 1400}, depuis=f"2026-09-0{i + 1}T10:00:00+00:00")

    resultat, verdict = _lister(session, departements_demo)

    assert verdict is None
    assert len(json.dumps({"ok": True, "resultat": {"accepte": True, "resultat": resultat}},
                          ensure_ascii=False)) < 6000  # jetons.LIMITE_SORTIE_DEFAUT
    assert resultat["attentes_affichees"] >= 1 and resultat["affichees"] >= 1
    assert resultat["attentes_reste"] == resultat["total_attentes"] - resultat["attentes_affichees"]
    assert resultat["reste"] == resultat["total_en_attente"] - resultat["affichees"]


def test_un_departement_dont_les_attentes_sont_illisibles_est_nomme_et_ne_bloque_pas_la_liste(
    session, personnes, departements_demo, attentes_demo
):
    attentes_demo.append({"type": "incomplet"})  # champs manquants : `_valider_attente` refuse
    with session() as cnx:
        demande = _demande(cnx)

    resultat, verdict = _lister(session, departements_demo)

    assert verdict is None
    assert resultat["attentes"] == [] and resultat["total_attentes"] == 0
    assert resultat["attentes_illisibles"] == [DEP_DEMO]  # son silence n'est pas « rien à signaler »
    assert [d["id"] for d in resultat["demandes"]] == [demande]


def test_la_liste_des_attentes_ne_decide_ni_n_ecrit_rien(session, personnes, departements_demo, attentes_demo):
    attentes_demo.append(_attente())
    with session() as cnx:
        demande = _demande(cnx)

    _lister(session, departements_demo)

    assert _statut(session, demande)["statut"] == "en_attente" and demo_outils.JOURNAL == []
    assert _journal(session) == []


# -- les attentes se lisent par pages (PLAN T1.5-e) ------------------------------------------------------
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`


def _taille_reponse(resultat) -> int:
    return len(json.dumps({"ok": True, "resultat": {"accepte": True, "resultat": resultat}}, ensure_ascii=False))


def _lire_toutes_les_pages(session, departements, identite_appelante=PROPRIO, **kw):
    """Comme l'app : page 0, puis `attentes_suivant` tant qu'il n'est pas nul. Rend les pages dans l'ordre."""
    pages, decalage = [], 0
    while decalage is not None:
        resultat, verdict = _lister(session, departements, identite_appelante, decalage_attentes=decalage, **kw)
        assert verdict is None, verdict
        pages.append(resultat)
        assert len(pages) <= 100, "la lecture ne progresse pas"
        decalage = resultat["attentes_suivant"]
    return pages


def _pile_d_attentes(attentes_demo, nombre=12, taille=240):
    for i in range(nombre):
        attentes_demo.append(_attente(f"wct-{i:02d}", "x" * taille, f"2026-09-{i + 1:02d}T00:00:00+00:00"))


def test_les_attentes_se_lisent_page_par_page_chacune_une_seule_fois_dans_l_ordre(
    session, personnes, departements_demo, attentes_demo
):
    _pile_d_attentes(attentes_demo)

    pages = _lire_toutes_les_pages(session, departements_demo)

    assert len(pages) > 1  # la pile ne tient pas dans une page : c'est ce que T1.5-e sert à lire
    lues = [a["id"] for page in pages for a in page["attentes"]]
    assert lues == [f"wct-{i:02d}" for i in range(12)]  # toutes, une fois, la plus ancienne d'abord
    rang = 0
    for page in pages:
        assert page["attentes_decalage"] == rang
        assert page["total_attentes"] == 12
        assert 1 <= page["attentes_affichees"] == len(page["attentes"])
        rang += page["attentes_affichees"]
        assert page["attentes_reste"] == 12 - rang
        assert page["attentes_suivant"] == (rang if rang < 12 else None)
    assert pages[-1]["attentes_suivant"] is None and pages[-1]["attentes_reste"] == 0
    assert all(page["attentes_illisibles"] == [] for page in pages)


def test_la_premiere_page_est_celle_d_avant_et_le_decalage_zero_est_le_defaut(
    session, personnes, departements_demo, attentes_demo
):
    _pile_d_attentes(attentes_demo)

    par_defaut, _ = _lister(session, departements_demo)
    explicite, _ = _lister(session, departements_demo, decalage_attentes=0)

    assert par_defaut == explicite
    assert par_defaut["attentes_decalage"] == 0
    assert par_defaut["attentes_reste"] == 12 - par_defaut["attentes_affichees"]  # ce qui n'est pas montré
    assert par_defaut["attentes_suivant"] == par_defaut["attentes_affichees"]


def test_chaque_page_reste_sous_la_troncature_et_garde_le_budget_des_demandes(
    session, personnes, departements_demo, attentes_demo
):
    _pile_d_attentes(attentes_demo, taille=400)
    with session() as cnx:
        for i in range(8):
            _demande(cnx, "m9_pointer", {"appareil": "y" * 1400}, depuis=f"2026-09-0{i + 1}T10:00:00+00:00")

    pages = _lire_toutes_les_pages(session, departements_demo)

    assert len(pages) > 1
    for page in pages:
        assert _taille_reponse(page) < LIMITE_TRONCATURE
        poids = sum(len(json.dumps(a, ensure_ascii=False)) for a in page["attentes"])
        assert poids <= approbations_appareil.BUDGET_ATTENTES  # le budget des attentes n'est pas relevé
        assert page["affichees"] >= 1  # les demandes gardent leur place, page après page
        assert page["reste"] == page["total_en_attente"] - page["affichees"]
    assert [a["id"] for page in pages for a in page["attentes"]] == [f"wct-{i:02d}" for i in range(12)]


@pytest.mark.parametrize("decalage", [12, 13, 500, 10**12])
def test_un_decalage_hors_plage_rend_une_page_vide_sans_erreur_ni_invention(
    session, personnes, departements_demo, attentes_demo, decalage
):
    _pile_d_attentes(attentes_demo)
    with session() as cnx:
        demande = _demande(cnx)

    resultat, verdict = _lister(session, departements_demo, decalage_attentes=decalage)

    assert verdict is None
    assert resultat["attentes"] == [] and resultat["attentes_affichees"] == 0
    assert resultat["attentes_suivant"] is None and resultat["attentes_reste"] == 0
    assert resultat["attentes_decalage"] == decalage and resultat["total_attentes"] == 12
    assert [d["id"] for d in resultat["demandes"]] == [demande]  # la liste des demandes n'en dépend pas


def test_sans_attente_aucun_decalage_n_en_invente(session, personnes, departements_demo, attentes_demo):
    for decalage in (0, 1, 7):
        resultat, verdict = _lister(session, departements_demo, decalage_attentes=decalage)

        assert verdict is None
        assert resultat["attentes"] == [] and resultat["total_attentes"] == 0
        assert (resultat["attentes_suivant"], resultat["attentes_reste"]) == (None, 0)


@pytest.mark.parametrize("decalage", [-1, True, False, 1.5, "2", None, [0], {}])
def test_un_decalage_qui_n_est_pas_un_entier_positif_ou_nul_est_refuse(
    session, personnes, departements_demo, attentes_demo, decalage
):
    _pile_d_attentes(attentes_demo)

    resultat, verdict = _lister(session, departements_demo, decalage_attentes=decalage)

    assert resultat is None and verdict["code"] == "decalage_invalide"
    assert "entier" in verdict["detail"]


def test_l_ordre_est_total_a_egalite_de_depuis_et_ne_depend_pas_de_l_ordre_de_declaration(
    session, personnes, departements_demo, attentes_demo
):
    instant = "2026-09-16T15:00:00+00:00"
    declarees = [
        _attente("fac-2", "Facture 2", instant, "facture_brouillon"),
        _attente("variance-9", "Chantier 9", instant, "chantier_a_reviser"),
        _attente("fac-1", "Facture 1", instant, "facture_brouillon"),
        _attente("wct-0", "Plus ancienne", "2026-09-15T00:00:00+00:00", "completion_en_revue"),
    ]
    attentes_demo.extend(declarees)
    avant = [a["id"] for page in _lire_toutes_les_pages(session, departements_demo) for a in page["attentes"]]

    attentes_demo.reverse()
    apres = [a["id"] for page in _lire_toutes_les_pages(session, departements_demo) for a in page["attentes"]]

    assert avant == apres == ["wct-0", "fac-1", "fac-2", "variance-9"]  # depuis, puis id


def test_une_attente_plus_grosse_que_le_budget_est_rendue_seule_et_la_lecture_progresse(
    session, personnes, departements_demo, attentes_demo
):
    attentes_demo.append(_attente("g" * 1800, "premiere", "2026-09-01T00:00:00+00:00"))
    attentes_demo.append(_attente("wct-2", "seconde", "2026-09-02T00:00:00+00:00"))

    pages = _lire_toutes_les_pages(session, departements_demo)

    assert [[a["resume"] for a in page["attentes"]] for page in pages] == [["premiere"], ["seconde"]]
    assert _taille_reponse(pages[0]) < LIMITE_TRONCATURE


@pytest.mark.parametrize(("appelante", "code"), [
    (None, "identite_absente"),
    (INACTIF, "identite_invalide"),
    (EMPLOYE, "role_appareil_insuffisant"),
])
def test_chaque_page_exige_la_meme_identite_que_la_liste(
    session, personnes, departements_demo, attentes_demo, appelante, code
):
    _pile_d_attentes(attentes_demo)

    resultat, verdict = _lister(session, departements_demo, appelante, decalage_attentes=3)

    assert resultat is None and verdict["code"] == code


def test_l_admin_qui_n_est_pas_le_proprietaire_lit_aussi_les_pages_suivantes(
    session, personnes, departements_demo, attentes_demo
):
    _pile_d_attentes(attentes_demo)

    pages = _lire_toutes_les_pages(session, departements_demo, GESTIONNAIRE)

    assert [a["id"] for page in pages for a in page["attentes"]] == [f"wct-{i:02d}" for i in range(12)]
    assert all(page["proprietaire"] is False for page in pages)


def test_lire_une_page_ne_decide_ni_n_ecrit_rien(session, personnes, departements_demo, attentes_demo):
    _pile_d_attentes(attentes_demo)
    with session() as cnx:
        demande = _demande(cnx)

    _lire_toutes_les_pages(session, departements_demo)

    assert _statut(session, demande)["statut"] == "en_attente" and demo_outils.JOURNAL == []
    assert _journal(session) == []


# -- identité : sans elle, rien --------------------------------------------------------------------
@pytest.mark.parametrize(("appelante", "code"), [
    (None, "identite_absente"),
    (contexte.IdentiteAppelante(personne="inconnu.fictif", role="admin"), "identite_invalide"),
    (INACTIF, "identite_invalide"),
    (contexte.IdentiteAppelante(personne="proprio.fictif", role="seller"), "identite_invalide"),  # rôle non porté
    (EMPLOYE, "role_appareil_insuffisant"),
    (contexte.IdentiteAppelante(personne="proprio.fictif", role="nathan_owner"), "role_appareil_insuffisant"),
])
def test_sans_identite_valide_ni_liste_ni_decision(session, personnes, departements_demo, appelante, code):
    with session() as cnx:
        ident = _demande(cnx)

    liste, verdict_liste = _lister(session, departements_demo, appelante)
    decision, verdict_decision = _decider(session, departements_demo, ident, identite_appelante=appelante)

    assert liste is None and verdict_liste["code"] == code
    assert decision is None and verdict_decision["code"] == code
    assert demo_outils.JOURNAL == []
    assert _statut(session, ident)["statut"] == "en_attente"
    assert _journal(session, "approbation.refus_appareil") == []  # pas de personne authentifiée : pas d'audit


def test_une_personne_desactivee_apres_l_appairage_perd_l_acces(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx)
        identite.activer(cnx, "proprio.fictif", False)

    _, verdict = _decider(session, departements_demo, ident)

    assert verdict["code"] == "identite_invalide"
    assert demo_outils.JOURNAL == []


def test_le_role_nathan_owner_retire_apres_coup_perd_la_decision(session, personnes, departements_demo):
    """La qualité de propriétaire est relue en base à chaque appel, jamais gardée avec le jeton."""
    with session() as cnx:
        ident = _demande(cnx)
        identite.retirer_role(cnx, "proprio.fictif", "nathan_owner")

    _, verdict = _decider(session, departements_demo, ident)

    assert verdict["code"] == "reserve_au_proprietaire"
    assert demo_outils.JOURNAL == []


# -- décider : le chemin de la console -------------------------------------------------------------
def test_le_proprietaire_approuve_une_demande_n3_l_outil_s_execute_avec_les_arguments_exacts(
    session, personnes, departements_demo
):
    with session() as cnx:
        ident = _demande(cnx, "m9_pointer", {"appareil": "T-EXACT"})

    resultat, verdict = _decider(session, departements_demo, ident, motif="Vu, c'est bon.")

    assert verdict is None
    assert resultat["statut"] == "executee" and resultat["decision"] == "approuver"
    assert resultat["decide_par"] == "proprio.fictif" and resultat["role"] == "nathan_owner"
    assert resultat["outil"] == "m9_pointer" and resultat["niveau"] == "N3"
    assert resultat["issue"] == {"ok": True}
    assert resultat["decide_le"]
    assert demo_outils.JOURNAL == [{"pointage": "T-EXACT"}]
    ligne = _statut(session, ident)
    assert ligne["statut"] == "executee"
    assert ligne["decide_par"] == "proprio.fictif" and ligne["decide_role"] == "nathan_owner"
    assert ligne["motif_decision"] == "Vu, c'est bon."


def test_le_proprietaire_approuve_une_demande_n4(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx, "m9_envoyer_message", {"destinataire": "client@x.ca", "texte": "Bonjour"}, Niveau.N4)

    resultat, verdict = _decider(session, departements_demo, ident)

    assert verdict is None and resultat["statut"] == "executee" and resultat["niveau"] == "N4"
    assert demo_outils.JOURNAL == [{"a": "client@x.ca", "texte": "Bonjour"}]


def test_le_proprietaire_refuse_une_demande_rien_ne_s_execute(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx)

    resultat, verdict = _decider(session, departements_demo, ident, "refuser", motif="Pas maintenant.")

    assert verdict is None and resultat["statut"] == "refusee" and resultat["decision"] == "refuser"
    assert "issue" not in resultat
    assert demo_outils.JOURNAL == []
    ligne = _statut(session, ident)
    assert ligne["statut"] == "refusee" and ligne["decide_role"] == "nathan_owner"


def test_la_decision_est_tracee_comme_celle_de_la_console_avec_l_appareil(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx)

    _decider(session, departements_demo, ident)

    [entree] = _journal(session, "approbation.approuver")
    assert entree["par"] == "proprio.fictif" and entree["cible"] == ident
    assert entree["details"] == {"outil": "m9_pointer", "statut": "executee", "role": "nathan_owner",
                                 "appareil": APPAREIL}
    assert entree["quand"]


def test_le_refus_est_trace_avec_l_appareil(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx)

    _decider(session, departements_demo, ident, "refuser", motif="non")

    [entree] = _journal(session, "approbation.refuser")
    assert entree["par"] == "proprio.fictif"
    assert entree["details"] == {"outil": "m9_pointer", "motif": "non", "role": "nathan_owner", "appareil": APPAREIL}


def test_l_admin_qui_n_est_pas_le_proprietaire_ne_decide_rien_et_l_essai_est_audite(
    session, personnes, departements_demo
):
    with session() as cnx:
        ident = _demande(cnx, "m9_envoyer_message", {"destinataire": "x", "texte": "y"}, Niveau.N4)

    for decision in ("approuver", "refuser"):
        resultat, verdict = _decider(session, departements_demo, ident, decision, identite_appelante=GESTIONNAIRE)
        assert resultat is None and verdict["code"] == "reserve_au_proprietaire"

    assert demo_outils.JOURNAL == []
    assert _statut(session, ident)["statut"] == "en_attente"
    essais = _journal(session, "approbation.refus_appareil")
    assert len(essais) == 2
    assert essais[0]["par"] == "gestionnaire.fictif" and essais[0]["cible"] == ident
    assert essais[0]["details"] == {"code": "reserve_au_proprietaire", "decision": "refuser",
                                    "appareil": APPAREIL, "role_appareil": "admin"}


def test_n5_ne_se_decide_jamais_depuis_l_app_ni_approuve_ni_refuse(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx, "m9_payer", {"montant": 999}, Niveau.N5)

    for decision in ("approuver", "refuser"):
        resultat, verdict = _decider(session, departements_demo, ident, decision)
        assert resultat is None and verdict["code"] == "n5_a_la_console"
        assert "console" in verdict["detail"]

    assert demo_outils.JOURNAL == []
    assert _statut(session, ident)["statut"] == "en_attente"
    assert [e["details"]["code"] for e in _journal(session, "approbation.refus_appareil")] == ["n5_a_la_console"] * 2


def test_une_demande_sans_niveau_ne_se_decide_pas_depuis_l_app(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(niveau=None))

    _, verdict = _decider(session, departements_demo, ident)

    assert verdict["code"] == "n5_a_la_console"
    assert demo_outils.JOURNAL == []


def test_une_demande_deja_decidee_donne_un_verdict_clair_et_rien_ne_se_refait(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx)
    premiere, _ = _decider(session, departements_demo, ident)

    for decision in ("approuver", "refuser"):
        resultat, verdict = _decider(session, departements_demo, ident, decision)
        assert resultat is None
        assert verdict["code"] == "deja_decidee" and verdict["statut"] == "executee"
        assert verdict["decide_par"] == "proprio.fictif" and verdict["decide_le"] == premiere["decide_le"]

    assert demo_outils.JOURNAL == [{"pointage": "T1"}]  # exécuté une seule fois
    assert len(_journal(session, "approbation.approuver")) == 1


def test_une_demande_refusee_puis_rejouee_reste_refusee(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx)
    _decider(session, departements_demo, ident, "refuser")

    _, verdict = _decider(session, departements_demo, ident, "approuver")

    assert verdict["code"] == "deja_decidee" and verdict["statut"] == "refusee"
    assert demo_outils.JOURNAL == []


def test_une_demande_inconnue_est_nommee(session, personnes, departements_demo):
    _, verdict = _decider(session, departements_demo, "introuvable00")

    assert verdict["code"] == "demande_inconnue"


@pytest.mark.parametrize("ident", ["", "   ", None, 12, "x" * 33])
def test_un_identifiant_de_demande_invalide_est_refuse(session, personnes, departements_demo, ident):
    _, verdict = _decider(session, departements_demo, ident)

    assert verdict["code"] == "demande_inconnue"


@pytest.mark.parametrize("decision", ["", "APPROUVER", "annuler", None, ["approuver"]])
def test_une_decision_hors_liste_est_refusee(session, personnes, departements_demo, decision):
    with session() as cnx:
        ident = _demande(cnx)

    resultat, verdict = _decider(session, departements_demo, ident, decision)

    assert resultat is None and verdict["code"] == "decision_invalide"
    assert demo_outils.JOURNAL == [] and _statut(session, ident)["statut"] == "en_attente"


@pytest.mark.parametrize("motif", [12, None, "m" * (approbations_appareil.LIMITE_MOTIF + 1)])
def test_un_motif_invalide_est_refuse(session, personnes, departements_demo, motif):
    with session() as cnx:
        ident = _demande(cnx)

    _, verdict = _decider(session, departements_demo, ident, motif=motif)

    assert verdict["code"] == "motif_invalide"
    assert _statut(session, ident)["statut"] == "en_attente"


@pytest.mark.parametrize("appareil", [None, "", "   "])
def test_sans_appareil_identifie_pas_de_decision(session, personnes, departements_demo, appareil):
    with session() as cnx:
        ident = _demande(cnx)

    _, verdict = _decider(session, departements_demo, ident, appareil=appareil)

    assert verdict["code"] == "appareil_inconnu"
    assert demo_outils.JOURNAL == [] and _statut(session, ident)["statut"] == "en_attente"


def test_la_politique_du_departement_s_applique_en_plus(session, personnes, departements_demo):
    """Un département dont N4 ne nomme pas `nathan_owner` garde sa politique : l'app ne l'élargit pas."""
    restreint = dataclasses.replace(
        departements_demo[DEP_DEMO],
        politique_approbation=PolitiqueApprobation({Niveau.N4: frozenset({"finance"})}),
    )
    departements = {DEP_DEMO: restreint}
    with session() as cnx:
        ident = _demande(cnx, "m9_envoyer_message", {"destinataire": "x", "texte": "y"}, Niveau.N4)

    resultat, _ = _lister(session, departements)
    _, verdict = _decider(session, departements, ident)

    assert resultat["demandes"][0]["lecture_seule"]["code"] == "politique_du_departement"
    assert verdict["code"] == "politique_du_departement"
    assert demo_outils.JOURNAL == [] and _statut(session, ident)["statut"] == "en_attente"


def test_la_decision_est_signee_nathan_owner_meme_quand_le_departement_autorise_aussi_admin(
    session, personnes, departements_demo
):
    """Comme M4 (`n3: [manager, admin, nathan_owner]`) : sans nommer le rôle, `decider` signerait `admin`, le
    premier dans l'ordre alphabétique. L'autorité de l'app est celle du propriétaire : la trace le dit."""
    ouvert_a_admin = dataclasses.replace(
        departements_demo[DEP_DEMO],
        politique_approbation=PolitiqueApprobation({Niveau.N3: frozenset({"manager", "admin", "nathan_owner"})}),
    )
    with session() as cnx:
        ident = _demande(cnx)

    resultat, verdict = _decider(session, {DEP_DEMO: ouvert_a_admin}, ident)

    assert verdict is None and resultat["role"] == "nathan_owner"
    assert _statut(session, ident)["decide_role"] == "nathan_owner"
    assert _journal(session, "approbation.approuver")[0]["details"]["role"] == "nathan_owner"


def test_l_outil_approuve_ne_voit_ni_l_identite_ni_les_horloges_de_l_appareil(session, personnes, departements_demo):
    """Comme depuis la console : sinon `m4_pointer` daterait un pointage d'un tiers à l'heure de
    l'approbation. Le contexte de l'appel est rétabli après la décision."""
    with session() as cnx:
        ident = _demande(cnx, "m9_voir_horodatage", {})
    maintenant = dt.datetime(2026, 9, 28, 10, 15, tzinfo=dt.UTC)
    reception = contexte.HorodatageAppareil(appareil=APPAREIL, horodatage_appareil=maintenant, recu_le=maintenant)

    with contexte.appele_par_appareil(PROPRIO), contexte.receptionne_de(reception):
        resultat, verdict = _decider(session, departements_demo, ident)
        assert contexte.identite_appelante() == PROPRIO  # rétabli après la décision
        assert contexte.horodatage_reception() == reception

    assert verdict is None and resultat["statut"] == "executee"
    assert demo_outils.HORODATAGES_VUS == [None]


def test_l_outil_approuve_ne_voit_pas_l_identite_de_l_appareil(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx, "m9_voir_identite", {})

    with contexte.appele_par_appareil(PROPRIO):
        resultat, verdict = _decider(session, departements_demo, ident)

    assert verdict is None and resultat["statut"] == "executee"
    assert demo_outils.IDENTITES_VUES == [None]


def test_un_echec_d_execution_est_dit_tel_quel_et_la_demande_est_close(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx, "m9_refuser_si_negatif", {"valeur": -1})

    resultat, verdict = _decider(session, departements_demo, ident)

    assert verdict is None
    assert resultat["statut"] == "echec"
    assert resultat["issue"]["ok"] is False and resultat["issue"]["erreur"] == "refus_metier"
    assert "valeur négative refusée" in resultat["issue"]["details"]
    _, deja = _decider(session, departements_demo, ident)
    assert deja["code"] == "deja_decidee" and deja["statut"] == "echec"


# -- `approbations.decider(role=, appareil=)` : additif, la console ne change pas -------------------------
def test_decider_sans_role_ni_appareil_se_comporte_comme_avant(session, personnes, departements_demo):
    with session() as cnx:
        ident = _demande(cnx)
        index = outils_executables(departements_demo, lambda: contextlib.nullcontext(cnx))
        resultat = approbations.decider(cnx, ident, True, "proprio.fictif", index, departements_demo)

    assert resultat["statut"] == "executee"
    [entree] = _journal(session, "approbation.approuver")
    assert entree["details"] == {"outil": "m9_pointer", "statut": "executee", "role": "nathan_owner"}


def test_decider_nomme_le_role_de_signature_quand_on_le_demande(session, personnes, departements_demo):
    autorisant_admin = dataclasses.replace(
        departements_demo[DEP_DEMO],
        politique_approbation=PolitiqueApprobation({Niveau.N3: frozenset({"admin", "nathan_owner"})}),
    )
    departements = {DEP_DEMO: autorisant_admin}
    with session() as cnx:
        sans_role = _demande(cnx)
        avec_role = _demande(cnx)
        sans_droit = _demande(cnx)
        index = outils_executables(departements, lambda: contextlib.nullcontext(cnx))
        approbations.decider(cnx, sans_role, True, "proprio.fictif", index, departements)
        approbations.decider(cnx, avec_role, True, "proprio.fictif", index, departements, role="nathan_owner")
        with pytest.raises(ValueError, match="rôle demandé : manager"):
            approbations.decider(cnx, sans_droit, True, "proprio.fictif", index, departements, role="manager")

    assert _statut(session, sans_role)["decide_role"] == "admin"  # premier rôle autorisé, ordre alphabétique
    assert _statut(session, avec_role)["decide_role"] == "nathan_owner"
    assert _statut(session, sans_droit)["statut"] == "en_attente"


def test_lire_compter_et_lister_dans_les_deux_sens(session, personnes):
    with session() as cnx:
        a = _demande(cnx, depuis="2026-09-01T00:00:00+00:00")
        b = _demande(cnx, depuis="2026-09-02T00:00:00+00:00")
        c = _demande(cnx, depuis="2026-09-03T00:00:00+00:00")
        assert approbations.lire(cnx, "introuvable") is None
        assert approbations.lire(cnx, b)["arguments"] == {"appareil": "T1"}
        assert approbations.compter(cnx, "en_attente") == 3 and approbations.compter(cnx, "executee") == 0
        assert [d["id"] for d in approbations.lister(cnx, "en_attente", 2)] == [c, b]
        assert [d["id"] for d in approbations.lister(cnx, "en_attente", 2, plus_anciennes_d_abord=True)] == [a, b]


# ============================ étage 2 : les vrais outils M9, par Capacites et le `_meta` d'appareil ===========
SNAPSHOT = {"module_source": "m04-field-ops", "horodatage": "2026-09-28T06:00:00Z",
            "valeurs": {"interventions_du_jour": "3", "fictif": "true"}}  # `valeurs` : du texte, toujours


@pytest.fixture
def capacites(session, personnes):
    """Vrais départements (mode `ombre` de M9), base migrée, personnes présentes."""
    departements = charger_departements(RACINE_DEPARTEMENTS)
    return Capacites(departements, session, filtre={"m04-field-ops", "m09-strategic-intelligence"}, memoire=False)


def _meta(cle: str) -> idempotence.Meta:
    return idempotence.Meta(cle=cle, appareil=APPAREIL, horodatage_appareil="2026-09-28T10:15:00-04:00")


def _appeler(capacites, nom, arguments, identite_appelante, cle):
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments, _meta(cle))


def _proposer_par_un_agent(capacites, snapshot=SNAPSHOT) -> str:
    """Un agent propose une écriture N3 (M9 est en mode `ombre`) : elle attend le propriétaire."""
    reponse = capacites.appeler("m9_etat_consolide", {"snapshot": snapshot})
    assert reponse["statut"] == "en_attente_approbation", reponse
    return reponse["demande_id"]


def _faits_consolides(capacites) -> dict:
    """Ce que M9 a consolidé : vide tant que l'écriture proposée par l'agent n'a pas été approuvée."""
    return capacites.appeler("m9_lire_etat_consolide", {})["resultat"]["faits_par_module"]


def test_de_bout_en_bout_un_agent_propose_le_proprietaire_liste_puis_approuve(session, capacites):
    ident = _proposer_par_un_agent(capacites)
    assert _faits_consolides(capacites) == {}  # proposée, pas faite

    liste = _appeler(capacites, "m9_lister_demandes_approbation", {}, PROPRIO, "liste-1")
    assert liste["ok"] is True and liste["resultat"]["accepte"] is True
    [item] = liste["resultat"]["resultat"]["demandes"]
    assert item["id"] == ident and item["outil"] == "m9_etat_consolide" and item["decidable"] is True
    assert item["arguments"] == {"snapshot": SNAPSHOT}

    decision = _appeler(capacites, "m9_decider_demande_approbation",
                        {"demande_id": ident, "decision": "approuver"}, PROPRIO, "decision-1")

    assert decision["ok"] is True and decision["rejoue"] is False
    assert decision["resultat"]["accepte"] is True
    assert decision["resultat"]["resultat"]["statut"] == "executee"
    assert decision["resultat"]["resultat"]["decide_par"] == "proprio.fictif"
    assert decision["resultat"]["resultat"]["issue"] == {"ok": True, "accepte": True}, decision
    # l'écriture proposée a bien eu lieu, avec les arguments exacts
    assert _faits_consolides(capacites)["m04-field-ops"]["valeurs"] == SNAPSHOT["valeurs"]
    with session() as cnx:
        ligne = approbations.lire(cnx, ident)
        assert ligne["statut"] == "executee" and ligne["decide_role"] == "nathan_owner"
        # L'outil de décision est N2 : aucune demande d'approbation n'a été créée pour lui-même.
        assert [d["outil"] for d in approbations.lister(cnx)] == ["m9_etat_consolide"]
        [entree] = [e for e in etat.lire_journal(cnx) if e["action"] == "approbation.approuver"]
        assert entree["par"] == "proprio.fictif" and entree["details"]["appareil"] == APPAREIL


def test_rejouer_la_meme_decision_avec_la_meme_cle_ne_s_applique_qu_une_fois(session, capacites):
    ident = _proposer_par_un_agent(capacites)
    args = {"demande_id": ident, "decision": "approuver"}

    premiere = _appeler(capacites, "m9_decider_demande_approbation", args, PROPRIO, "decision-rejeu")
    rejeu = _appeler(capacites, "m9_decider_demande_approbation", args, PROPRIO, "decision-rejeu")

    assert premiere["rejoue"] is False and rejeu["rejoue"] is True
    assert {k: v for k, v in rejeu.items() if k != "rejoue"} == {k: v for k, v in premiere.items() if k != "rejoue"}
    with session() as cnx:
        assert len([e for e in etat.lire_journal(cnx) if e["action"] == "approbation.approuver"]) == 1
    with stockage.transaction():  # l'écriture n'a été faite qu'une fois
        assert len(stockage.maillons("m09-strategic-intelligence", "snapshots")) == 1


def test_la_meme_cle_pour_une_autre_decision_est_un_conflit_rien_n_est_decide(session, capacites):
    ident = _proposer_par_un_agent(capacites)
    _appeler(capacites, "m9_decider_demande_approbation", {"demande_id": ident, "decision": "refuser"},
             PROPRIO, "cle-reutilisee")

    conflit = _appeler(capacites, "m9_decider_demande_approbation", {"demande_id": ident, "decision": "approuver"},
                       PROPRIO, "cle-reutilisee")

    assert conflit["ok"] is False and conflit["erreur"] == "mutation_conflit"
    with session() as cnx:
        assert approbations.lire(cnx, ident)["statut"] == "refusee"


def test_une_autre_cle_pour_une_demande_deja_decidee_recoit_le_verdict_deja_decidee(session, capacites):
    ident = _proposer_par_un_agent(capacites)
    args = {"demande_id": ident, "decision": "approuver"}
    _appeler(capacites, "m9_decider_demande_approbation", args, PROPRIO, "cle-a")

    second = _appeler(capacites, "m9_decider_demande_approbation", args, PROPRIO, "cle-b")

    assert second["ok"] is True and second["rejoue"] is False
    assert second["resultat"]["accepte"] is False
    assert second["resultat"]["verdict"]["code"] == "deja_decidee"
    assert second["resultat"]["verdict"]["statut"] == "executee"
    with session() as cnx:
        assert len([e for e in etat.lire_journal(cnx) if e["action"] == "approbation.approuver"]) == 1


def test_sans_identite_d_appareil_les_deux_outils_refusent(session, capacites):
    ident = _proposer_par_un_agent(capacites)

    liste = capacites.appeler("m9_lister_demandes_approbation", {})
    decision = capacites.appeler("m9_decider_demande_approbation", {"demande_id": ident, "decision": "approuver"})

    assert liste["resultat"]["verdict"]["code"] == "identite_absente"
    assert decision["resultat"]["verdict"]["code"] == "identite_absente"
    with session() as cnx:
        assert approbations.lire(cnx, ident)["statut"] == "en_attente"


def test_une_identite_sans_appel_d_appareil_idempotent_ne_decide_pas(session, capacites):
    """Le `_meta` d'identité seul (sans clé d'idempotence ni appareil) ne suffit pas à décider."""
    ident = _proposer_par_un_agent(capacites)

    with contexte.appele_par_appareil(PROPRIO):
        decision = capacites.appeler("m9_decider_demande_approbation", {"demande_id": ident, "decision": "approuver"})

    # Le garde idempotence précède la résolution de l'appareil et le dispatch de décision.
    assert decision["ok"] is False and decision["erreur"] == "idempotence_appareil_requise"
    with session() as cnx:
        assert approbations.lire(cnx, ident)["statut"] == "en_attente"


@pytest.mark.parametrize("identite_appelante", [GESTIONNAIRE, EMPLOYE, INACTIF])
def test_mauvais_role_ou_mauvaise_personne_rien_n_est_decide(session, capacites, identite_appelante):
    ident = _proposer_par_un_agent(capacites)

    decision = _appeler(capacites, "m9_decider_demande_approbation",
                        {"demande_id": ident, "decision": "approuver"}, identite_appelante, "decision-refusee")

    assert decision["resultat"]["accepte"] is False
    assert decision["resultat"]["verdict"]["code"] in {"reserve_au_proprietaire", "role_appareil_insuffisant",
                                                       "identite_invalide"}
    with session() as cnx:
        assert approbations.lire(cnx, ident)["statut"] == "en_attente"
    assert _faits_consolides(capacites) == {}


@pytest.mark.parametrize("champ", ["personne", "decide_par", "identifiant", "role", "appareil"])
def test_aucun_argument_ne_designe_le_decideur(session, capacites, champ):
    """L'identité ne vient que du contexte authentifié : un argument qui la nomme est refusé net."""
    ident = _proposer_par_un_agent(capacites)

    decision = _appeler(capacites, "m9_decider_demande_approbation",
                        {"demande_id": ident, "decision": "approuver", champ: "proprio.fictif"}, GESTIONNAIRE,
                        f"forge-{champ}")

    assert decision["ok"] is False and decision["erreur"] == "arguments_invalides"
    assert any(champ in d for d in decision["details"])
    with session() as cnx:
        assert approbations.lire(cnx, ident)["statut"] == "en_attente"


def test_l_agent_m9_sans_identite_ne_peut_pas_vider_la_file_meme_en_nommant_le_proprietaire(session, capacites):
    ident = _proposer_par_un_agent(capacites)
    meta_agent = idempotence.Meta(cle="agent-1", appareil="tel-agent", horodatage_appareil="2026-09-28T10:15:00-04:00")

    decision = capacites.appeler("m9_decider_demande_approbation",
                                 {"demande_id": ident, "decision": "approuver"}, meta_agent)

    assert decision["resultat"]["verdict"]["code"] == "identite_absente"
    with session() as cnx:
        assert approbations.lire(cnx, ident)["statut"] == "en_attente"


def test_n5_reel_reste_a_la_console_par_les_vrais_outils(session, capacites):
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m05-financecore", "m5_enregistrer_paiement_facture",
                                           {"facture_id": "F-FICTIF"}, niveau=Niveau.N5)

    liste = _appeler(capacites, "m9_lister_demandes_approbation", {}, PROPRIO, "liste-n5")
    decision = _appeler(capacites, "m9_decider_demande_approbation", {"demande_id": ident, "decision": "approuver"},
                        PROPRIO, "decision-n5")

    [item] = liste["resultat"]["resultat"]["demandes"]
    assert item["decidable"] is False and item["lecture_seule"]["code"] == "n5_a_la_console"
    assert decision["resultat"]["verdict"]["code"] == "n5_a_la_console"
    with session() as cnx:
        assert approbations.lire(cnx, ident)["statut"] == "en_attente"


def test_les_deux_outils_sont_declares_admin_seulement_et_aucun_n_est_une_frontiere_humaine(capacites):
    lister = capacites.index["m9_lister_demandes_approbation"][1]
    decider = capacites.index["m9_decider_demande_approbation"][1]

    for outil in (lister, decider):
        assert outil.roles_appareil == frozenset({"admin"})
        assert outil.frontiere_humaine is False
    assert lister.niveau_effectif is Niveau.N0
    assert decider.niveau_effectif is Niveau.N2
    assert set(decider.parametres["properties"]) == {"demande_id", "decision", "motif"}
    assert decider.parametres["additionalProperties"] is False
    deux = {"m9_lister_demandes_approbation", "m9_decider_demande_approbation"}
    assert deux <= capacites._outils_du_role("admin")
    assert not deux & capacites._outils_du_role("employee")
    assert not deux & capacites._outils_du_role("seller")


def test_la_table_approbations_ne_garde_pas_la_valeur_masquee_du_gps_dans_la_liste(session, capacites):
    """La demande garde ses arguments exacts (la console les montre) ; l'app ne montre jamais le fix GPS."""
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m04-field-ops", "m4_pointer",
                                           {"intervention_id": "I1", "fix_gps": FIX_GPS}, niveau=Niveau.N3)

    liste = _appeler(capacites, "m9_lister_demandes_approbation", {}, PROPRIO, "liste-gps")

    [item] = liste["resultat"]["resultat"]["demandes"]
    assert item["id"] == ident
    assert item["arguments"]["fix_gps"] == approbations.VALEUR_MASQUEE
    assert "45.508812" not in json.dumps(liste, ensure_ascii=False)
    with session() as cnx:
        stocke = cnx.execute(select(APPROBATIONS.c.arguments).where(APPROBATIONS.c.id == ident)).scalar_one()
    assert "45.508812" in stocke  # inchangé : la console et l'exécution utilisent les arguments exacts
