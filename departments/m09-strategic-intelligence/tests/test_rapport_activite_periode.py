"""Rapport d'activité de période FICTIF : WCT/bus et approbations SQL natifs."""
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import event

from opsys import approbations, contexte, evenements, identite, stockage
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

w = _charger("_activite_rapport_base", Path(__file__).with_name("test_rapport_periode.py"))
o = _charger("_activite_observations_base", Path(__file__).with_name("test_observations_chantier_periode.py"))
installation = w.installation
NOM = "m9_rapport_activite_periode"
DEBUT, FIN = w.p.DEBUT, w.p.FIN


def test_rapport_activite_apres_trois_wct_alertes_et_suivis_approuves(installation, monkeypatch):
    cap, ids = w.p._preparer_natif(installation, monkeypatch)
    for i in range(3):
        w._recevoir_alerte_fictive(installation, f"2026-10-06T12:00:{i:02d}Z", "-activite-" + str(i))
    ancien = w._rapport(cap)
    observations = o._lire(cap, debut=DEBUT, fin=FIN)
    bilan = w.p._lire(cap)
    assert observations["total"] == ancien["alertes_periode"]["total"] == 3
    assert bilan["total"] == 2 and bilan["compteurs"] == {
        "ouverts_periode": 1, "clotures_periode": 1, "ouverts_fin": 1,
    }
    assert len(w.b._suivis()) == 3 and len(w.p.h._clotures()) == 2
    assert NOM in cap.index, "M9_ACTIVITE_ABSENTE_APRES_3WCT_ALERTES_ET_SUIVIS_APPROUVES_NATIFS"
    avant = w.b._tables()
    page = w.b._lire(cap, NOM, {"debut": DEBUT, "fin": FIN})
    assert page["type"] == "RAPPORT_ACTIVITE_PERIODE"
    assert page["compteurs"] == {"observations": 3, "alertes": 3, "suivis": 2} | bilan["compteurs"]
    assert page["rapport_complet"] is False and page["actualite_metier"] == "NON_EVALUEE"
    assert w.b._tables() == avant



def _sources():
    maillons, publications = o._sources()
    return (deepcopy(w.b._suivis()), deepcopy(w.p.h._clotures()),
            deepcopy(list(stockage.maillons(w.b.DEPARTEMENT, "alertes_m8"))), maillons, publications)


def _pur(sources, **args):
    # Préconditions : sources capturées nativement ; le wrapper valide la chaîne/catalogues.
    # Aucun oracle de vérification cryptographique n'est attribué à cette fonction pure.
    from importlib import import_module
    module = import_module("m9_strategic_intelligence.rapport_activite")
    return module.assembler_rapport_activite(*sources, **({"debut": DEBUT, "fin": FIN,
                                                          "budget_caracteres": 5900} | args))


def _lire(cap, **args):
    return w.b._lire(cap, NOM, {"debut": DEBUT, "fin": FIN} | args)


def _collecter(lire, cle="lignes", section=None):
    premiere = lire()
    page = premiere
    lignes, cursors = [], set()
    for _ in range(100):
        bloc = page[section] if section else page
        assert page["vue"] == premiere["vue"]
        assert bloc["total"] == (premiere[section] if section else premiere)["total"]
        assert bloc["affichees"] == len(bloc[cle])
        lignes.extend(bloc[cle])
        prochain = bloc["prochain_depart"]
        if prochain is None:
            assert bloc["reste"] == 0 and len(lignes) == bloc["total"]
            return premiere, lignes
        assert type(prochain) is int and prochain > bloc["depart"]
        assert prochain == len(lignes) and prochain not in cursors
        cursors.add(prochain)
        page = lire(depart=prochain, vue_attendue=page["vue"])
    pytest.fail("Pagination dépassant cent pages sur cette petite fixture")


def _jeu(installation, monkeypatch):
    cap, ids = w.p._preparer_natif(installation, monkeypatch)
    for i in range(3):
        w._recevoir_alerte_fictive(installation, f"2026-10-06T12:00:{i:02d}Z", "-composition-" + str(i))
    return cap, ids


def _refus(cap, **args):
    avant = w.b._tables()
    with contexte.appele_par_appareil(w.b.PROPRIO):
        resultat = cap.appeler(NOM, {"debut": DEBUT, "fin": FIN} | args)
    assert resultat["ok"] is False and "tronque" not in resultat, resultat
    assert w.b._tables() == avant
    return resultat


def test_flux_natifs_complets_ordres_et_compteurs_identiques_sans_mutation(installation, monkeypatch):
    cap, ids = _jeu(installation, monkeypatch)
    bilan, suivis = _collecter(lambda **kw: w.p._lire(cap, **kw), "suivis")
    ancien, alertes = _collecter(lambda **kw: w._rapport(cap, **kw), "alertes", "alertes_periode")
    observations, faits = _collecter(lambda **kw: o._lire(cap, debut=DEBUT, fin=FIN, **kw), "observations")
    attendu = ([{"section": "observations", "preuve": r} for r in faits]
               + [{"section": "alertes", "preuve": r} for r in alertes]
               + [{"section": "suivis", "preuve": r} for r in suivis])
    avant = w.b._tables()
    pages = []
    def lire(**args):
        page = _lire(cap, **args)
        pages.append(page)
        assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
        assert page["compteurs"] == {"observations": observations["total"],
            "alertes": ancien["alertes_periode"]["total"], "suivis": bilan["total"]} | bilan["compteurs"]
        assert (page["debut"], page["fin"]) == (DEBUT, FIN)
        assert page["statut"] == "NON_VALIDE" and page["actualite_metier"] == "NON_EVALUEE"
        assert page["rapport_complet"] is False and page["bases_temporelles"]
        return page
    _, lignes = _collecter(lire)
    assert lignes == attendu and len(pages) >= 2
    assert w.b._tables() == avant
    futurs = {c["suivi_id"]: c for c in w.p.h._clotures() if c["decision"]["decide_le"] >= FIN}
    for row in lignes:
        if row["section"] == "suivis" and row["preuve"]["suivi"]["suivi_id"] in futurs:
            assert "cloture" not in row["preuve"] and row["preuve"]["ouvert_fin"] is True
    assert ids[2] not in {r["preuve"]["suivi"]["suivi_id"] for r in lignes if r["section"] == "suivis"}


@pytest.mark.parametrize("instant,attendu", [
    ("2026-10-04T20:00:00-04:00", 1), ("2026-10-11T23:59:59Z", 1),
    ("2026-10-11T20:00:00-04:00", 0),
])
def test_bornes_zones_des_deux_flux_metier(installation, instant, attendu):
    w._recevoir_alerte_fictive(installation, instant, "-borne-activite")
    page = _pur(_sources())
    assert page["compteurs"]["observations"] == page["compteurs"]["alertes"] == attendu
    assert page["compteurs"]["suivis"] == 0


@pytest.mark.parametrize("mutation", ["arrivee_tardive", "generique_hors_periode", "cloture_future"])
def test_mutation_source_perime_vue_meme_depart_zero(installation, monkeypatch, mutation):
    cap = w.b._capacites(installation)
    if mutation == "cloture_future":
        monkeypatch.setattr(approbations, "_maintenant", lambda: "2026-10-06T09:00:00Z")
        cap, ids, alerte = w.p.s._preparer(installation, 1)
    else:
        w._recevoir_alerte_fictive(installation, "2026-10-06T12:00:00Z", "-vue-initiale")
    premiere = _lire(cap)
    if mutation == "arrivee_tardive":
        w._recevoir_alerte_fictive(installation, "2026-10-07T12:00:00Z", "-vue-tardive")
    elif mutation == "generique_hors_periode":
        o._ajouter_t1(cap, {"module_source": "generique-fictif", "horodatage": "1999-01-01T00:00:00Z",
                           "valeurs": {"etat": "fictif"}})
    else:
        monkeypatch.setattr(approbations, "_maintenant", lambda: FIN)
        w.p.s._clore(cap, ids[0], alerte)
    refus = _refus(cap, vue_attendue=premiere["vue"])
    assert "REJ-" in json.dumps(refus)
    apres, lignes = _collecter(lambda **kw: _lire(cap, **kw))
    assert apres["vue"] != premiere["vue"]
    if mutation == "arrivee_tardive":
        assert apres["compteurs"]["observations"] == apres["compteurs"]["alertes"] == 2
    elif mutation == "generique_hors_periode":
        assert apres["compteurs"] == premiere["compteurs"]
        assert apres["snapshots_generiques_non_couverts"] == 1
    else:
        assert apres["compteurs"] == premiere["compteurs"]
        [suivi] = [r["preuve"] for r in lignes if r["section"] == "suivis"]
        assert suivi["ouvert_fin"] is True and "cloture" not in suivi


def test_file_courante_non_approuvee_ne_change_pas_vue_ni_contenu(installation):
    cap, arguments, _, _ = w.b._proposer(installation)
    avant = _lire(cap)
    demande = cap.appeler(w.b.OUVRIR, arguments | {"action": "Nouvelle proposition fictive non approuvée"})
    assert demande["statut"] == "en_attente_approbation"
    assert _lire(cap) == avant


def test_pages_pures_copies_profondes_et_terminal_borne(installation, monkeypatch):
    _jeu(installation, monkeypatch)
    sources = _sources()
    avant = deepcopy(sources)
    premiere, lignes = _collecter(lambda **kw: _pur(sources, **kw))
    assert sources == avant and lignes
    terminal = _pur(sources, depart=premiere["total"], vue_attendue=premiere["vue"])
    assert terminal["lignes"] == [] and terminal["affichees"] == terminal["reste"] == 0
    assert terminal["prochain_depart"] is None
    assert len(json.dumps(terminal, ensure_ascii=False, allow_nan=False)) <= 5900
    observation = next(r["preuve"] for r in lignes if r["section"] == "observations")
    observation["maillon"]["valeurs"]["m4_duree_reelle_minutes"] = "999"
    observation["publication"]["snapshot"]["valeurs"]["m4_duree_reelle_minutes"] = "999"
    assert sources == avant


@pytest.mark.parametrize("args", [
    {"depart": True}, {"depart": -1}, {"depart": 1}, {"depart": 999},
    {"vue_attendue": "A" * 64}, {"debut": "2026-10-05T00:00:00"},
    {"fin": DEBUT}, {"budget_caracteres": True}, {"budget_caracteres": 0},
])
def test_parametres_purs_invalides_ne_modifient_pas_sources(args):
    sources = ([], [], [], [], {})
    with pytest.raises(ValueError):
        _pur(sources, **args)
    assert sources == ([], [], [], [], {})


@pytest.mark.parametrize("cause", ["employee", "admin_revoque", "inactif"])
def test_sql_courant_avant_tous_registres_et_publications(installation, monkeypatch, cause):
    cap = w.b._capacites(installation)
    with stockage.transaction() as cnx:
        if cause == "admin_revoque":
            identite.retirer_role(cnx, w.b.PROPRIO.personne, "admin")
        elif cause == "inactif":
            identite.activer(cnx, w.b.PROPRIO.personne, False)
    personne = (contexte.IdentiteAppelante(personne=w.b.RESPONSABLE, role="employee")
                if cause == "employee" else w.b.PROPRIO)
    def interdit(*args, **kwargs):
        pytest.fail("Lecture des sources avant contrôle SQL courant")
    monkeypatch.setattr(stockage, "maillons", interdit)
    monkeypatch.setattr(evenements, "charge_publiee", interdit)
    avant = w.b._tables()
    def garde_sql(cnx, curseur, instruction, parametres, ctx, plusieurs):
        sql = instruction.lower()
        if sql.lstrip().startswith("select") and any(
            t.name.lower() in sql for t in (REGISTRES, EVENEMENTS_SORTANTS, EVENEMENTS_RECUS)
        ):
            pytest.fail("SQL des sources avant contrôle SQL courant")
    moteur = stockage.moteur()
    event.listen(moteur, "before_cursor_execute", garde_sql)
    try:
        with contexte.appele_par_appareil(personne):
            refus = cap.appeler(NOM, {"debut": DEBUT, "fin": FIN})
    finally:
        event.remove(moteur, "before_cursor_execute", garde_sql)
    assert refus["ok"] is False and w.b._tables() == avant


def test_symphony792_suivi_ulterieur_valide_trop_grand_refuse_avant_premiere_page(installation):
    # Portée pure : plans/clôtures synthétiques valides du bilan ; observation et alerte natives.
    w._recevoir_alerte_fictive(installation, "2026-10-06T12:00:00Z", "-lateproof")
    _, _, alertes, maillons, publications = _sources()
    cap = w.b._capacites(installation)
    assert w._rapport(cap)["alertes_periode"]["total"] == 1
    assert o._lire(cap, debut=DEBUT, fin=FIN)["total"] == 1
    premier = w.p._plan("petit", DEBUT)
    tardif = w.p._plan("ulterieur", "2026-10-06T12:00:00Z")
    tardif["source"]["alerte"]["quoi"] = "Preuve fictive volumineuse " + "x" * 3500
    tardif["source"]["empreinte_source"] = w.b.empreinte(tardif["source"]["alerte"])
    cloture = w.p._cloture(tardif, "2026-10-08T12:00:00Z")
    plans, clotures = [premier, tardif], [cloture]
    # Admissibilité établie AVANT le budget : pas de NaN ni de fixture déjà structurellement refusée.
    admissible = w.p._pure(plans, clotures, budget_caracteres=100_000)
    assert admissible["total"] == 2 and admissible["suivis"][1]["cloture"] == cloture
    petite_page = w.p._pure(plans, clotures, budget_caracteres=5900)
    assert [r["suivi"]["suivi_id"] for r in petite_page["suivis"]] == ["petit"]
    assert petite_page["prochain_depart"] == 1
    with pytest.raises(ValueError, match="REJ-BILAN-BORNE") as oracle:
        w.p._pure(plans, clotures, depart=1, vue_attendue=petite_page["vue"], budget_caracteres=5900)
    sources = (plans, clotures, alertes, maillons, publications)
    avant = deepcopy(sources)
    with pytest.raises(ValueError, match="REJ-BILAN-BORNE") as composite:
        _pur(sources)
    assert str(composite.value) == str(oracle.value) and sources == avant


@pytest.mark.parametrize("cause", ["alerte_hors_periode", "publication_hors_periode"])
def test_corruption_source_hors_periode_refuse_rapport_entier(installation, cause):
    w._recevoir_alerte_fictive(installation, "2026-11-06T12:00:00Z", "-corruption-activite")
    sources = _sources()
    if cause == "alerte_hors_periode":
        sources[2][-1]["preuve"]["metric_id"] = "metrique-fictive-discordante"
    else:
        sources[4][next(iter(sources[4]))]["snapshot"]["valeurs"]["m4_duree_reelle_minutes"] = "999"
    avant = deepcopy(sources)
    with pytest.raises(ValueError):
        _pur(sources)
    assert sources == avant


def test_bornes_originales_equivalentes_changent_vue_sans_changer_compteurs(installation):
    w._recevoir_alerte_fictive(installation, "2026-10-06T12:00:00Z", "-bornes-originales")
    sources = _sources()
    a = _pur(sources)
    debut, fin = "2026-10-04T20:00:00.000000-04:00", "2026-10-12T02:00:00+02:00"
    bpage = _pur(sources, debut=debut, fin=fin)
    assert bpage["compteurs"] == a["compteurs"] and bpage["vue"] != a["vue"]
    assert (bpage["debut"], bpage["fin"]) == (debut, fin)
    with pytest.raises(ValueError):
        _pur(sources, debut=debut, fin=fin, vue_attendue=a["vue"])


@pytest.mark.parametrize("section,lecteur", [
    ("observations", "lister_observations_chantier"),
    ("alertes", "assembler_rapport_periode"),
    ("suivis", "bilan_suivis_decision"),
])
@pytest.mark.parametrize("defaut", ["cle_terminale_absente", "compteur_booleen", "curseur_sans_progres"])
def test_pager_interne_malforme_refuse_sans_boucle(installation, monkeypatch, section, lecteur, defaut):
    from importlib import import_module
    module = import_module("m9_strategic_intelligence.rapport_activite")
    original = getattr(module, lecteur)
    appels = []
    def corrompu(*args, **kwargs):
        appels.append(1)
        assert len(appels) <= 3, "Le garde de progression doit refuser sans boucler"
        page = original(*args, **kwargs)
        bloc = page["alertes_periode"] if section == "alertes" else page
        if defaut == "cle_terminale_absente":
            assert bloc["prochain_depart"] is None
            del bloc["prochain_depart"]
        elif defaut == "compteur_booleen":
            bloc["total"] = False
        else:
            bloc["prochain_depart"] = bloc["depart"]
        return page
    monkeypatch.setattr(module, lecteur, corrompu)
    sources = _sources()
    avant = deepcopy(sources)
    with pytest.raises(ValueError, match="REJ-ACTIVITE-PAGINATION"):
        _pur(sources)
    assert sources == avant and len(appels) == 1
