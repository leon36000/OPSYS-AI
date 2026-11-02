"""`m8_lire_etat_collecte` : POURQUOI une mesure est vide, sur le VRAI planificateur et le VRAI bus (chantier C2).

Le monde est celui de `test_entrepot_m8_planifie.py` : données FICTIVES dans M1, M2, M4, M5, M6 et M7, le vrai
planificateur durable à horloge INJECTÉE, les vrais outils de constat, le vrai bus et M8. L'outil de M8 lit l'état du
planificateur lui-même (aucune copie) et les mesures ordinaires ; il n'écrit rien.

Prouvé, dans l'ordre d'une installation : neuve (rien d'activé : « constat inactif » ou « sans constat planifié »),
constats en ombre (rien n'est publié : « en ombre »), constats actifs mais bus non livré (« jamais reçue »), livré (les
mesures sont à jour, le « non calculable » du producteur est dit comme tel), panne d'un département (« en erreur » avec
son code, puis périmée), activation échue (« expiré »), coupe-circuit, fraîcheur du soir du cash libre. Prouvé aussi :
l'outil n'écrit et ne publie rien, ne rend aucune valeur de mesure, refuse un appareil non admin, n'ajoute aucun droit
d'appareil, et la liste de contrôle suit l'état lu. Limites dites : SQLite seulement, horloge injectée.
"""

from __future__ import annotations

import json

import planif_m8_monde as pm
import pytest
from m8_analytics import catalogue_mesures
from sqlalchemy import select

from opsys import contexte, stockage
from opsys.connecteurs_planification import etat
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS, META

FICTIF = True
MDP = "mot-de-passe-fictif-12345"
CASH = "m5.constat.cash-libre"
OUTIL = "m8_lire_etat_collecte"
INTERVALLE = 43200
JOUR = 86400
CASH_MESURES = ("m8_cash_libre_cad", "m8_solde_tresorerie_cad", "m8_comptes_a_payer_cad", "m8_taxes_a_remettre_cad")
VALEURS_SEMEES = ("1200.00", "27861.98", "689.85")  # facturation émise, cash libre de référence, une facture


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    pm.semer_tout(m, pm.lire_yaml(pm.RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml"))
    yield m
    pm.demonter()


def _outil(monde):
    return {o.nom: o for o in monde.bus.departements[pm.M8].charger_outils()}[OUTIL]


def _appel(monde, identite=None, **arguments):
    arguments.setdefault("maintenant", monde.maintenant())
    with contexte.appele_par_appareil(identite) if identite is not None else _rien():
        return executer_atomique(_outil(monde), arguments)


class _rien:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


def _lire(monde, **arguments):
    reponse = _appel(monde, **arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _toutes(monde, vue, **arguments):
    """Toutes les pages d'une vue (la réponse est bornée par la limite du socle)."""
    cle = "mesures" if vue == "mesures" else "etapes"
    lignes, depart = [], 0
    while depart is not None:
        page = _lire(monde, vue=vue, depart=depart, **arguments)
        lignes += page[cle]
        depart = page["prochain_depart"]
    return lignes


def _causes(monde) -> dict[str, str]:
    return {m["metric_id"]: m["etat_collecte"] for m in _toutes(monde, "mesures", seulement_a_corriger=False)}


def _instantane():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


# ============================================================================================ 1. installation neuve
def test_une_installation_neuve_dit_constat_inactif_pour_ce_qu_un_constat_nourrit_et_le_reste_sans_constat(monde):
    monde.propager()
    causes = _causes(monde)

    # les mesures nourries par un constat planifié déclaré : le constat est inactif (jamais activé)
    for metric_id in CASH_MESURES + ("m8_factures_emises", "m8_pipeline_leads_ouverts", "m8_plaintes_periode",
                                     "m8_clics_recherche", "m8_articles_en_rupture"):
        assert causes[metric_id] == "constat_inactif", metric_id
    # une mesure que seul un événement alimente (M3) : aucun constat à activer
    assert causes["m8_taux_acceptation_pct"] == "sans_constat_planifie"
    assert len(causes) == len(catalogue_mesures.charger()["mesures"])
    # aucune mesure qu'un constat planifié nourrit n'est à jour (rien n'a encore tourné) ; celles qui le sont viennent
    # d'un événement déjà livré (les relevés de dépense de M7) ou sont terminales (cumul de chantiers terminés)
    lignes = _toutes(monde, "mesures", seulement_a_corriger=False)
    assert all(m["etat_collecte"] != "a_jour" for m in lignes if m["constats"])
    assert {m["metric_id"] for m in lignes if m["etat_collecte"] == "a_jour"} <= {
        "m8_releves_depense_pub_cad", *(e["metric_id"] for e in catalogue_mesures.charger()["mesures"]
                                        if e["fraicheur"].get("terminale"))}
    resume = _lire(monde, vue="resume")
    assert resume["planificateur_autorise"] is True and resume["n_mesures"] == len(causes)
    assert sum(resume["resume"].values()) == len(causes)
    assert resume["resume"]["constat_inactif"] >= 20
    assert {c["etat"] for c in resume["constats"]} == {"inactif"} and len(resume["constats"]) == 9
    assert CASH in {c["executeur"] for c in resume["constats"]}


def test_chaque_mesure_vide_a_une_phrase_et_une_action_qui_nomme_le_bon_constat(monde):
    monde.propager()

    lignes = {m["metric_id"]: m for m in _toutes(monde, "mesures")}

    cash = lignes["m8_cash_libre_cad"]
    assert cash["constats"] == [CASH] and cash["etat_collecte"] == "constat_inactif"
    assert CASH in cash["action"] and "ombre" in cash["action"] and "Connecteurs" in cash["action"]
    assert lignes["m8_taux_acceptation_pct"]["constats"] == []
    assert all(m["phrase"] and m["action"] for m in lignes.values())


def test_la_liste_de_controle_d_une_installation_neuve_n_a_rien_de_fait_et_dit_quoi_faire(monde):
    etapes = _toutes(monde, "liste_de_controle", seulement_a_corriger=False)

    assert etapes[0]["etape"] == "planificateur_autorise" and etapes[0]["fait"] is True
    par_constat = {}
    for e in etapes[1:]:
        par_constat.setdefault(e["constat"], []).append((e["etape"], e["fait"]))
    assert len(par_constat) == 9
    for nom, suite in par_constat.items():
        assert suite == [("activer_en_ombre", False), ("passer_en_actif", False),
                         ("premier_passage_reussi", False)], nom
    a_faire = _toutes(monde, "liste_de_controle")  # le défaut : seulement ce qui reste à faire
    assert len(a_faire) == 27 and all(not e["fait"] and e["action"] for e in a_faire)
    assert {CASH} <= {e["constat"] for e in a_faire}


# ======================================================================================================== 2. en ombre
def test_en_ombre_les_constats_ne_publient_rien_et_l_outil_le_dit(monde):
    monde.activer("ombre")
    monde.tour(1)
    monde.propager()

    assert monde.nombre_publie() == {}
    causes = _causes(monde)
    for metric_id in CASH_MESURES + ("m8_factures_emises", "m8_plaintes_periode"):
        assert causes[metric_id] == "constat_en_ombre", metric_id
    ligne = next(m for m in _toutes(monde, "mesures") if m["metric_id"] == "m8_cash_libre_cad")
    assert "ne publie rien" in ligne["phrase"] and "de l'ombre à l'actif" in ligne["action"]
    etapes = {(e["constat"], e["etape"]): e["fait"]
              for e in _toutes(monde, "liste_de_controle", seulement_a_corriger=False)}
    assert etapes[(CASH, "activer_en_ombre")] is True and etapes[(CASH, "passer_en_actif")] is False
    assert {c["etat"] for c in _lire(monde, vue="resume")["constats"]} == {"ombre"}


# ============================================================================================= 3. actif mais pas livré
def test_actif_mais_rien_livre_a_m8_dit_jamais_recue_puis_les_mesures_arrivent(monde):
    monde.activer("actif")
    assert {v["statut"] for v in monde.tour(1).values()} == {"ok"}

    causes = _causes(monde)  # le bus n'a rien livré à M8
    for metric_id in CASH_MESURES + ("m8_factures_emises", "m8_plaintes_periode"):
        assert causes[metric_id] == "jamais_recue", metric_id
    ligne = next(m for m in _toutes(monde, "mesures") if m["metric_id"] == "m8_plaintes_periode")
    assert "aucun fait n'a été reçu" in ligne["phrase"] and "bus" in ligne["action"]

    monde.propager()
    causes = _causes(monde)
    assert {causes[m] for m in ("m8_plaintes_periode", "m8_factures_emises", "m8_pipeline_leads_ouverts")} == {"a_jour"}


def test_une_fois_livre_le_non_calculable_du_producteur_n_est_pas_pris_pour_un_defaut_technique(monde):
    """M5 n'a ni mouvement ni déclaration dans ce monde : il constate « non calculable » (publié tel quel). Le constat
    fonctionne ; ce qui manque est une DÉCLARATION, et l'outil le dit."""
    monde.activer("actif")
    monde.tour(1)
    monde.propager()

    lignes = {m["metric_id"]: m for m in _toutes(monde, "mesures")}

    assert lignes["m8_cash_libre_cad"]["etat_collecte"] == "producteur_non_calculable"
    assert "constat n'y peut rien" in lignes["m8_cash_libre_cad"]["action"]
    assert "m8_factures_emises" not in lignes  # à jour : filtrée par défaut
    etapes = {(e["constat"], e["etape"]): e["fait"]
              for e in _toutes(monde, "liste_de_controle", seulement_a_corriger=False)}
    assert all(etapes[(CASH, e)] for e in ("activer_en_ombre", "passer_en_actif", "premier_passage_reussi"))
    resume = _lire(monde, vue="resume")
    cash = next(c for c in resume["constats"] if c["executeur"] == CASH)
    assert cash["etat"] == "actif" and cash["dernier_statut"] == "ok" and cash["mesures_total"] == 4


# ========================================================================================================= 4. la panne
def test_la_panne_d_un_departement_est_dite_avec_son_code_puis_la_mesure_perime_puis_la_reprise(monde, monkeypatch):
    from m6_material_control import outils as m6_outils

    monde.activer("actif")
    monde.tour(1)
    monde.propager()
    assert _causes(monde)["m8_articles_en_rupture"] == "a_jour"

    def casse(horodatage):
        raise RuntimeError("panne simulée de M6")

    reel = m6_outils.constater_disponibilite
    monkeypatch.setattr(m6_outils, "constater_disponibilite", casse)
    monde.tour(INTERVALLE)  # premier passage manqué : la mesure est encore à jour, mais l'échec se voit déjà
    monde.propager()
    resume = _lire(monde, vue="resume")
    m6 = next(c for c in resume["constats"] if c["executeur"] == "m6.constat.disponibilite")
    assert (m6["dernier_statut"], m6["dernier_code"]) == ("erreur", "REJ-PLAN-DEFAUT-EXECUTEUR")
    assert _causes(monde)["m8_articles_en_rupture"] == "a_jour"

    monde.tour(INTERVALLE)  # deuxième passage manqué : la mesure est périmée, la cause est l'erreur du constat
    monde.propager()
    ligne = next(m for m in _toutes(monde, "mesures") if m["metric_id"] == "m8_articles_en_rupture")
    assert ligne["etat_collecte"] == "constat_en_erreur" and "REJ-PLAN-DEFAUT-EXECUTEUR" in ligne["phrase"]
    assert ligne["fraicheur"] == "perime"
    assert _causes(monde)["m8_pipeline_leads_ouverts"] == "a_jour"  # les autres continuent

    monkeypatch.setattr(m6_outils, "constater_disponibilite", reel)
    monde.tour(INTERVALLE)
    monde.propager()
    assert _causes(monde)["m8_articles_en_rupture"] == "a_jour"


# ==================================================================================== 5. expiration et coupe-circuit
def test_une_activation_echue_dit_constat_expire_et_non_jamais_active(monde):
    monde.activer("actif", noms=(CASH,))
    monde.tour(1)
    monde.propager()
    monde.horloge.avancer(91 * JOUR)  # l'activation de 90 jours est échue (fail-closed : plus rien ne tourne)

    ligne = next(m for m in _toutes(monde, "mesures") if m["metric_id"] == "m8_solde_tresorerie_cad")

    assert ligne["etat_collecte"] == "constat_expire" and "90 jours est échue" in ligne["phrase"]
    assert "Renouveler" in ligne["action"]
    cash = next(c for c in _lire(monde, vue="resume")["constats"] if c["executeur"] == CASH)
    assert cash["etat"] == "expire"


def test_le_coupe_circuit_est_dit_pour_toutes_les_mesures_et_en_premier_dans_la_liste_de_controle(monde, monkeypatch):
    monde.activer("actif")
    monde.tour(1)
    monde.propager()
    monkeypatch.setenv(etat.ENV_PLANIFICATEUR, "0")

    resume = _lire(monde, vue="resume")

    assert resume["planificateur_autorise"] is False
    causes = _causes(monde)
    assert causes["m8_cash_libre_cad"] == "planificateur_coupe"
    assert causes["m8_factures_emises"] in ("planificateur_coupe", "a_jour")  # une mesure encore fraîche reste à jour
    premier = _toutes(monde, "liste_de_controle")[0]
    assert premier["etape"] == "planificateur_autorise" and premier["fait"] is False
    assert "OPSYS_PLANIFICATEUR_CONNECTEURS" in premier["action"]


# ============================================================================== 6. lecture seule, aucune valeur, accès
def test_l_outil_n_ecrit_ni_ne_publie_rien(monde):
    monde.activer("actif")
    monde.tour(1)
    monde.propager()
    avant = _instantane()

    for vue in ("resume", "mesures", "liste_de_controle"):
        _toutes(monde, vue, seulement_a_corriger=False) if vue != "resume" else _lire(monde, vue=vue)

    assert _instantane() == avant
    with stockage.transaction() as cnx:
        types_avant = len(cnx.execute(select(EVENEMENTS_SORTANTS)).fetchall())
    _lire(monde, vue="resume")
    with stockage.transaction() as cnx:
        assert len(cnx.execute(select(EVENEMENTS_SORTANTS)).fetchall()) == types_avant


def test_aucune_valeur_de_mesure_aucune_personne_ne_sort_de_l_outil(monde):
    monde.activer("actif")
    monde.tour(1)
    monde.propager()
    sortie = json.dumps([_lire(monde, vue="resume"), _toutes(monde, "mesures", seulement_a_corriger=False),
                         _toutes(monde, "liste_de_controle", seulement_a_corriger=False)], ensure_ascii=False)

    for interdit in VALEURS_SEMEES + ("example", "@", "Client", "client-fictif", "+1514", "Jeanne"):
        assert interdit not in sortie, interdit
    assert '"valeur"' not in sortie


def test_l_outil_est_n0_sans_droit_d_appareil_et_un_admin_authentifie_le_lit(monde):
    outil = _outil(monde)
    assert outil.autonomie.value == "T0" and outil.niveau_effectif.value == "N0"
    assert outil.roles_appareil == frozenset() and not outil.frontiere_humaine

    lu = _lire(monde, identite=pm.ADMIN, vue="resume")
    assert lu["n_mesures"] > 0


@pytest.mark.parametrize("personne", [contexte.IdentiteAppelante("marc.fictif", "employee"),
                                      contexte.IdentiteAppelante("vendeur.un", "seller"),
                                      contexte.IdentiteAppelante("fantome.fictif", "admin")],
                         ids=["employe", "vendeur", "admin_inconnu"])
def test_un_appareil_qui_n_est_pas_un_admin_confirme_est_refuse_avant_toute_lecture(monde, personne):
    reponse = _appel(monde, identite=personne, vue="resume")

    assert reponse["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in str(reponse)


@pytest.mark.parametrize("arguments", [
    {"vue": "tout"}, {"vue": "mesures", "seulement_a_corriger": "oui"}, {"depart": -1}, {"depart": 10_000},
    {"maintenant": "2026-11-12 10:00"}, {"inconnu": 1}, {"vue": "resume", "metric_ids": ["m8_a"]},
], ids=["vue", "filtre", "depart_negatif", "depart_hors_fin", "instant_sans_fuseau", "argument_inconnu", "metric_ids"])
def test_les_arguments_hostiles_sont_refuses_sans_rien_lire_d_utile(monde, arguments):
    avant = _instantane()
    reponse = _appel(monde, vue=arguments.pop("vue", "mesures"), **arguments)

    assert reponse["ok"] is False
    assert _instantane() == avant


# ====================================================================================== 7. pagination sous la limite
def test_la_vue_des_mesures_tient_page_par_page_sous_la_limite_du_socle_sans_rien_perdre(monde):
    from m8_analytics import outils as m8_outils

    premiere = _lire(monde, vue="mesures", seulement_a_corriger=False)
    assert premiere["prochain_depart"] is not None, "56 lignes ne tiennent pas dans une seule page"
    assert len(json.dumps(premiere, ensure_ascii=False)) <= m8_outils.BUDGET_SORTIE
    toutes = _toutes(monde, "mesures", seulement_a_corriger=False)
    catalogue = [e["metric_id"] for e in catalogue_mesures.charger()["mesures"]]
    assert [m["metric_id"] for m in toutes] == catalogue and premiere["n_lignes"] == len(catalogue)


def test_le_resume_tient_dans_une_page(monde):
    resume = _lire(monde, vue="resume")

    assert resume["prochain_depart"] is None and "mesures" not in resume


# ======================================================================================== 8. le wallboard « collecte »
def test_le_wallboard_collecte_a_un_temoin_par_constat_declare_pas_une_liste_recopiee():
    """Chaque constat planifié déclaré par un manifeste a au moins une de ses mesures sur le wallboard, et chaque tuile
    est nourrie par un constat : la liste se déduit des manifestes, elle n'est pas recopiée."""
    import yaml
    from m8_analytics import wallboards

    from opsys.connecteurs_planification import constats as plan_constats
    from opsys.departements import charger_departements

    definition = yaml.safe_load((wallboards._DOSSIER / "collecte.v1.yaml").read_text(encoding="utf-8"))
    declarations = plan_constats.declarations(charger_departements())
    mesures_du_wallboard = {t["mesure"] for t in definition["tuiles"]}
    for declaration in declarations:
        assert mesures_du_wallboard & set(declaration.constat.mesures), declaration.nom
    nourries = {m for d in declarations for m in d.constat.mesures}
    assert mesures_du_wallboard <= nourries
    assert len(definition["tuiles"]) == len(declarations) and definition["roles"] == ["admin"]
    assert wallboards.valider(definition, catalogue_mesures.charger())["id"] == "collecte"
