"""`m9_lire_alertes_m8` est BORNÉ (PLAN T1.5-d) : une page à la fois, sous la limite de sortie du socle.

Avant : l'outil rendait TOUTES les alertes de M8 reçues, sans limite ; au-delà d'une dizaine, la réponse
dépassait les 6 000 caractères de `Capacites._tronquer` et l'app du propriétaire recevait un aperçu coupé.
Maintenant : le même mécanisme que `m9_lire_suite_briefing` (`depart`, `prochain_depart`, budget
`BUDGET_SORTIE`), l'ordre est stable (le plus récent d'abord, puis identifiant), et ce qui ne tient pas est
compté, jamais perdu.

Deux niveaux : le module pur (`lecture_alertes`) et l'outil par `executer` pour les cas fins (limite exacte,
ordre, refus) ; puis `Capacites`, sur une vraie base et le vrai bus, pour la troncature elle-même. La porte
d'appareil (rôle `admin`) est prouvée par `tests/e2e/test_a_voir_pagination.py`. Les alertes sont fictives
(métriques `m8_metrique_fictive_NN`) : ce fichier prouve la lecture par pages, pas les règles de M8.
"""

from __future__ import annotations

import copy
import datetime as dt
import itertools
import json
from pathlib import Path

import m9_strategic_intelligence.outils as outils_m9
import pytest
from m9_strategic_intelligence import lecture_alertes
from m9_strategic_intelligence.outils import outils
from m9_strategic_intelligence.registre import RegistreSnapshots

from opsys import evenements, jetons, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
LIRE = "m9_lire_alertes_m8"
_DEBUT = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)
_GROS = 10**9  # un budget qui ne borne rien : la liste entière, pour comparer


def _taille(objet) -> int:
    """Ce que `Capacites._tronquer` mesure : `json.dumps(objet, ensure_ascii=False)`."""
    return len(json.dumps(objet, ensure_ascii=False))


def _instant(numero: int) -> str:
    return (_DEBUT + dt.timedelta(hours=numero)).isoformat().replace("+00:00", "Z")


def _alerte(numero: int, instant: str | None = None, **plus) -> dict:
    """Une alerte `m8.alerte_proposee` fictive, valide contre le catalogue, de la taille de celles de M8
    (environ 800 caractères : sept ou huit tiennent sous la limite du socle)."""
    instant = instant or _instant(numero)
    metrique = f"m8_metrique_fictive_{numero:02d}"
    base = {
        "evenement_id": f"m8-alerte-{metrique}-REJ-QUALITE-DONNEE-PERIMEE-{instant}",
        "metric_id": metrique,
        "type_alerte": "REJ-QUALITE-DONNEE-PERIMEE",
        "quoi": f"Valeur périmée pour {metrique} (donnée fictive).",
        "a_qui": "m04-field-ops",
        "pourquoi": "âge observé 10.00 jours > fraîcheur attendue 2 jours. " + "Règle de fraîcheur fictive. " * 6,
        "preuve": {"metric_id": metrique, "fraicheur_jours": 10.0, "fraicheur_attendue_jours": 2},
        "action_proposee": "Rafraîchir la donnée à la source (action fictive proposée par M8, jamais exécutée).",
        "source": "source fictive de la définition de la métrique",
        "horodatage_reference": instant,
    }
    base.update(plus)
    return base


def _outils(alertes: list[dict]) -> dict:
    """Registre de snapshots ET registre d'alertes EN MÉMOIRE, explicites (aucune base montée)."""
    return {o.nom: o for o in outils(RegistreSnapshots(), alertes_cible=alertes)}


def _lire(par_nom: dict, **arguments) -> dict:
    return executer(par_nom[LIRE], arguments)


def _pages(lire, maximum: int = 100) -> list[dict]:
    """Comme l'app : `depart` 0, puis `prochain_depart` tant qu'il n'est pas nul. Rend les pages dans l'ordre."""
    pages: list[dict] = []
    depart: int | None = 0
    while depart is not None:
        reponse = lire(depart)
        assert reponse["ok"] is True, reponse
        pages.append(reponse["resultat"])
        depart = pages[-1]["prochain_depart"]
        assert len(pages) <= maximum, "la lecture ne progresse pas"
    return pages


def _identifiants(pages: list[dict]) -> list[str]:
    return [a["evenement_id"] for page in pages for a in page["alertes"]]


def _budget_de(alertes: list[dict], nombre: int) -> int:
    """Le plus petit budget sous lequel la première page compte `nombre` alertes : la taille exacte de cette
    page, trouvée par dichotomie sur le module lui-même (le nombre d'alertes rendues croît avec le budget)."""
    def tenant(budget: int) -> int:
        try:
            return lecture_alertes.lire_alertes_m8(alertes, 0, budget_caracteres=budget)["affichees"]
        except ValueError:  # pas même une alerte
            return 0

    bas, haut = 1, _taille(lecture_alertes.lire_alertes_m8(alertes, 0, budget_caracteres=_GROS))
    while bas < haut:
        milieu = (bas + haut) // 2
        if tenant(milieu) >= nombre:
            haut = milieu
        else:
            bas = milieu + 1
    assert tenant(bas) == nombre and tenant(bas - 1) == nombre - 1
    return bas


# ---------------------------------------------------------------------------
# Liste vide, une page, forme de la réponse
# ---------------------------------------------------------------------------
def test_liste_vide_une_page_vide_qui_dit_qu_il_n_y_a_rien_a_lire():
    reponse = _lire(_outils([]))

    assert reponse["ok"] is True
    page = reponse["resultat"]
    assert page["type"] == "ALERTES_M8"
    assert page["alertes"] == [] and page["total"] == 0 and page["depart"] == 0
    assert page["affichees"] == 0 and page["reste"] == 0
    assert page["prochain_depart"] is None and page["message"] is None


def test_une_page_qui_contient_tout_est_complete_et_porte_l_ordre_documente():
    alertes = [_alerte(numero) for numero in range(3)]

    page = _lire(_outils(alertes))["resultat"]

    assert page["total"] == 3 and page["affichees"] == 3 and page["reste"] == 0
    assert page["prochain_depart"] is None and page["message"] is None
    assert page["ordre"] == lecture_alertes.ORDRE_ALERTES
    assert "le plus récent d'abord" in page["ordre"] and "evenement_id croissant" in page["ordre"]
    assert page["source"].startswith("m8.alerte_proposee")
    assert [a["evenement_id"] for a in page["alertes"]] == [a["evenement_id"] for a in reversed(alertes)]
    assert set(page) == {
        "type", "source", "ordre", "total", "depart", "affichees", "reste", "prochain_depart", "message", "alertes",
    }


def test_chaque_alerte_est_rendue_telle_que_recue_sans_champ_retire_ni_ajoute():
    alerte = _alerte(0)

    (rendue,) = _lire(_outils([alerte]))["resultat"]["alertes"]

    assert rendue == alerte


# ---------------------------------------------------------------------------
# Exactement la limite : le budget est mesuré par le code sur la taille sérialisée
# ---------------------------------------------------------------------------
def test_exactement_la_limite_tout_tient_et_un_caractere_de_moins_en_retire_une_alerte():
    alertes = [_alerte(numero) for numero in range(5)]
    page = lecture_alertes.lire_alertes_m8(alertes, 0, budget_caracteres=_GROS)
    assert page["affichees"] == 5

    for attendues in (5, 4, 3, 2, 1):
        limite = _taille(page)  # la page de `attendues` alertes, au caractère près
        assert page["affichees"] == attendues
        exacte = lecture_alertes.lire_alertes_m8(alertes, 0, budget_caracteres=limite)
        assert exacte == page  # à la limite exacte : la même page, rien de retiré
        assert exacte["prochain_depart"] == (attendues if attendues < 5 else None)
        if attendues == 1:
            with pytest.raises(ValueError, match="dépasse à elle seule la borne"):
                lecture_alertes.lire_alertes_m8(alertes, 0, budget_caracteres=limite - 1)
            break
        page = lecture_alertes.lire_alertes_m8(alertes, 0, budget_caracteres=limite - 1)
        assert page["affichees"] == attendues - 1  # un caractère de moins : une alerte de moins, pas davantage
        assert page["reste"] == 5 - (attendues - 1) and page["prochain_depart"] == attendues - 1


def test_l_outil_borne_sous_BUDGET_SORTIE_le_meme_budget_que_le_briefing(monkeypatch):
    alertes = [_alerte(numero) for numero in range(5)]
    tout = lecture_alertes.lire_alertes_m8(alertes, 0, budget_caracteres=_GROS)
    par_nom = _outils(alertes)
    assert outils_m9.BUDGET_SORTIE < jetons.LIMITE_SORTIE_DEFAUT

    monkeypatch.setattr(outils_m9, "BUDGET_SORTIE", _taille(tout))
    exacte = _lire(par_nom)["resultat"]
    assert exacte["affichees"] == 5 and exacte["prochain_depart"] is None

    monkeypatch.setattr(outils_m9, "BUDGET_SORTIE", _taille(tout) - 1)
    serree = _lire(par_nom)["resultat"]
    assert serree["affichees"] == 4 and serree["reste"] == 1 and serree["prochain_depart"] == 4
    assert serree["message"] == "1 autre alerte non affichée : poursuivre avec depart=4."


# ---------------------------------------------------------------------------
# Au-delà de la limite : les pages se recollent, sans doublon ni trou
# ---------------------------------------------------------------------------
def test_au_dela_de_la_limite_les_pages_se_recollent_sans_doublon_ni_trou():
    alertes = [_alerte(numero) for numero in range(30)]
    par_nom = _outils(alertes)

    pages = _pages(lambda depart: _lire(par_nom, depart=depart))

    assert len(pages) > 2
    assert _identifiants(pages) == [a["evenement_id"] for a in reversed(alertes)]  # toutes, du plus récent
    assert len(set(_identifiants(pages))) == 30
    lus = 0
    for page in pages:
        assert page["total"] == 30 and page["depart"] == lus
        assert page["affichees"] == len(page["alertes"]) >= 1
        assert _taille(page) <= outils_m9.BUDGET_SORTIE
        lus += page["affichees"]
        assert page["reste"] == 30 - lus
        assert page["prochain_depart"] == (lus if lus < 30 else None)
        if page["reste"]:
            assert page["message"].endswith(f"poursuivre avec depart={lus}.")
    assert pages[-1]["prochain_depart"] is None and pages[-1]["reste"] == 0 and pages[-1]["message"] is None


def test_chaque_page_est_pleine_l_alerte_suivante_ne_tenait_pas():
    alertes = [_alerte(numero) for numero in range(30)]
    par_nom = _outils(alertes)
    pages = _pages(lambda depart: _lire(par_nom, depart=depart))

    for page in pages[:-1]:
        restant = lecture_alertes.lire_alertes_m8(alertes, page["depart"], budget_caracteres=_GROS)["alertes"]
        avec_une_de_plus = {**page, "affichees": page["affichees"] + 1, "alertes": restant[:page["affichees"] + 1]}
        assert _taille(avec_une_de_plus) > outils_m9.BUDGET_SORTIE  # le budget est rempli, pas gaspillé


def test_deux_pages_se_recollent_petit_budget():
    alertes = [_alerte(numero) for numero in range(7)]
    tout = lecture_alertes.lire_alertes_m8(alertes, 0, budget_caracteres=_GROS)
    budget = _budget_de(alertes, 3)  # trois alertes par page

    premiere = lecture_alertes.lire_alertes_m8(alertes, 0, budget_caracteres=budget)
    deuxieme = lecture_alertes.lire_alertes_m8(alertes, premiere["prochain_depart"], budget_caracteres=budget)
    troisieme = lecture_alertes.lire_alertes_m8(alertes, deuxieme["prochain_depart"], budget_caracteres=budget)

    assert [p["affichees"] for p in (premiere, deuxieme, troisieme)] == [3, 3, 1]
    assert [p["prochain_depart"] for p in (premiere, deuxieme, troisieme)] == [3, 6, None]
    assert _identifiants([premiere, deuxieme, troisieme]) == [a["evenement_id"] for a in tout["alertes"]]


# ---------------------------------------------------------------------------
# `depart` au-delà de la fin, `depart` invalide : un refus qui dit quoi corriger
# ---------------------------------------------------------------------------
def test_depart_egal_au_total_est_une_page_vide_pas_une_erreur():
    par_nom = _outils([_alerte(numero) for numero in range(3)])

    page = _lire(par_nom, depart=3)["resultat"]

    assert page["alertes"] == [] and page["affichees"] == 0 and page["total"] == 3 and page["depart"] == 3
    assert page["reste"] == 0 and page["prochain_depart"] is None


@pytest.mark.parametrize("depart", [4, 99])
def test_depart_au_dela_de_la_fin_est_un_refus_metier_qui_dit_de_reprendre_a_zero(depart):
    par_nom = _outils([_alerte(numero) for numero in range(3)])

    reponse = _lire(par_nom, depart=depart)

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert f"depart {depart} au-delà de la fin des alertes (3 alerte(s) reçue(s))" in reponse["details"]
    assert "reprendre à depart=0" in reponse["details"]


def test_depart_1_sans_aucune_alerte_est_au_dela_de_la_fin():
    reponse = _lire(_outils([]), depart=1)

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "0 alerte(s)" in reponse["details"] and "depart=0" in reponse["details"]


def test_depart_negatif_est_un_refus_metier_qui_dit_quoi_corriger():
    reponse = _lire(_outils([_alerte(0)]), depart=-1)

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "entier supérieur ou égal à 0 attendu" in reponse["details"] and "-1" in reponse["details"]


@pytest.mark.parametrize("depart", ["2", 1.5, None, True, [0]])
def test_depart_qui_n_est_pas_un_entier_est_refuse_par_le_schema_de_l_outil(depart):
    reponse = _lire(_outils([_alerte(0)]), depart=depart)

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert any(detail.startswith("depart : type attendu integer") for detail in reponse["details"])


def test_un_parametre_inconnu_est_refuse_et_le_schema_offre_depart_seulement():
    par_nom = _outils([_alerte(0)])

    refuse = _lire(par_nom, depart=0, limite=5)
    assert refuse["ok"] is False and refuse["erreur"] == "arguments_invalides"
    assert "paramètre inconnu : limite" in refuse["details"]

    schema = par_nom[LIRE].parametres
    assert schema["additionalProperties"] is False and set(schema["properties"]) == {"depart"}
    assert schema["properties"]["depart"]["type"] == "integer" and schema["properties"]["depart"]["minimum"] == 0
    assert "required" not in schema  # `depart` est facultatif : 0 par défaut


@pytest.mark.parametrize("depart", [True, False, -1, "0", 1.0, None])
def test_le_module_pur_refuse_lui_aussi_un_depart_qui_n_est_pas_un_entier_positif_ou_nul(depart):
    with pytest.raises(ValueError, match="depart : entier supérieur ou égal à 0 attendu"):
        lecture_alertes.lire_alertes_m8([_alerte(0)], depart, budget_caracteres=_GROS)


@pytest.mark.parametrize("budget", [0, -5, True, "6000", None])
def test_un_budget_invalide_est_refuse(budget):
    with pytest.raises(ValueError, match="budget_caracteres : entier strictement positif attendu"):
        lecture_alertes.lire_alertes_m8([_alerte(0)], 0, budget_caracteres=budget)


# ---------------------------------------------------------------------------
# Ordre stable : le plus récent d'abord, à instant égal par identifiant
# ---------------------------------------------------------------------------
def test_a_heure_egale_l_identifiant_departage_quel_que_soit_l_ordre_d_arrivee():
    instant = "2026-09-28T09:00:00Z"
    egales = [_alerte(numero, instant) for numero in (3, 1, 2)]
    plus_ancienne = _alerte(9, "2026-09-27T09:00:00Z")
    plus_recente = _alerte(8, "2026-09-29T09:00:00Z")
    attendu = [plus_recente["evenement_id"]] + sorted(a["evenement_id"] for a in egales) + [
        plus_ancienne["evenement_id"]]

    for arrivee in itertools.permutations([*egales, plus_ancienne, plus_recente]):
        page = _lire(_outils(list(arrivee)))["resultat"]
        assert [a["evenement_id"] for a in page["alertes"]] == attendu


def test_le_plus_recent_se_compare_en_instant_pas_alphabetiquement():
    """07:00 à -04:00 est 11:00 UTC : plus récent que 10:00Z, bien que « 2026-09-28T07… » précède
    « 2026-09-28T10… » dans l'ordre alphabétique. 12:00+02:00 est 10:00 UTC : égale à 10:00Z, donc départagée
    par l'identifiant."""
    dix_heures_z = _alerte(1, "2026-09-28T10:00:00Z")
    sept_heures_quebec = _alerte(2, "2026-09-28T07:00:00-04:00")
    midi_paris = _alerte(3, "2026-09-28T12:00:00+02:00")

    page = _lire(_outils([dix_heures_z, midi_paris, sept_heures_quebec]))["resultat"]

    assert [a["evenement_id"] for a in page["alertes"]] == [
        sept_heures_quebec["evenement_id"], *sorted([dix_heures_z["evenement_id"], midi_paris["evenement_id"]]),
    ]


def test_deux_alertes_de_meme_heure_a_la_frontiere_de_page_ne_se_perdent_ni_ne_se_repetent():
    instant = "2026-09-28T09:00:00Z"
    alertes = [_alerte(numero, instant) for numero in (4, 2, 3, 1)]
    budget = _budget_de(alertes, 1)  # une seule alerte par page

    pages = _pages(lambda depart: {"ok": True, "resultat": lecture_alertes.lire_alertes_m8(
        alertes, depart, budget_caracteres=budget)})

    assert [p["affichees"] for p in pages] == [1, 1, 1, 1]
    assert _identifiants(pages) == sorted(a["evenement_id"] for a in alertes)


def test_l_ordre_ne_depend_pas_de_l_ordre_du_registre_et_deux_lectures_se_ressemblent():
    alertes = [_alerte(numero) for numero in (5, 0, 3, 4, 1, 2)]
    par_nom = _outils(alertes)

    premiere = _lire(par_nom)["resultat"]
    deuxieme = _lire(par_nom)["resultat"]

    assert premiere == deuxieme
    assert [a["metric_id"] for a in premiere["alertes"]] == [f"m8_metrique_fictive_{n:02d}" for n in (5, 4, 3, 2, 1, 0)]


# ---------------------------------------------------------------------------
# Fail-closed et relecture pure
# ---------------------------------------------------------------------------
def test_une_alerte_sans_ses_champs_est_un_refus_qui_la_nomme_jamais_un_element_ignore():
    incomplete = _alerte(1)
    del incomplete["horodatage_reference"]

    reponse = _lire(_outils([_alerte(0), incomplete]))

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "alertes_m8 : champ(s) manquant(s) ['horodatage_reference']" in reponse["details"]


def test_un_horodatage_illisible_est_un_refus_qui_nomme_l_alerte():
    illisible = _alerte(1, "hier matin")

    reponse = _lire(_outils([_alerte(0), illisible]))

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert f"horodatage_reference illisible pour {illisible['evenement_id']}" in reponse["details"]


def test_une_seule_alerte_plus_grosse_que_la_borne_est_un_refus_nomme_pas_une_page_vide():
    grosse = _alerte(1, pourquoi="x" * 500)

    with pytest.raises(ValueError, match=f"l'alerte {grosse['evenement_id']} dépasse à elle seule la borne de 400"):
        lecture_alertes.lire_alertes_m8([grosse], 0, budget_caracteres=400)


def test_la_lecture_n_ecrit_rien_et_rend_des_copies():
    alertes = [_alerte(numero) for numero in (2, 0, 1)]
    avant = copy.deepcopy(alertes)
    par_nom = _outils(alertes)

    page = _lire(par_nom)["resultat"]
    page["alertes"][0]["quoi"] = "modifiée par l'appelant"
    page["alertes"][0]["preuve"]["fraicheur_jours"] = -1  # une copie superficielle ne suffirait pas ici

    assert alertes == avant  # ni réordonné, ni modifié, ni grossi
    assert _lire(par_nom)["resultat"]["alertes"][0]["preuve"]["fraicheur_jours"] == 10.0


def test_l_outil_reste_t0_et_reserve_a_l_admin():
    outil = _outils([])[LIRE]

    assert outil.autonomie == Autonomie.T0
    assert outil.roles_appareil == frozenset({"admin"})


# ---------------------------------------------------------------------------
# Par `Capacites`, sur une vraie base et le vrai bus : la troncature du socle n'a plus lieu
# ---------------------------------------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def departements(base_durable):
    """M8 (producteur) et M9 (consommateur) : les manifestes réels du dépôt."""
    tous = charger_departements(_RACINE_DEPARTEMENTS)
    return {code: tous[code] for code in ("m08-analytics", "m09-strategic-intelligence")}


@pytest.fixture
def capacites(base_durable):
    return Capacites(charger_departements(_RACINE_DEPARTEMENTS), stockage.transaction,
                     filtre={"m09-strategic-intelligence"}, memoire=False)


def _livrer_par_le_bus(alertes: list[dict], departements) -> None:
    """Chaque alerte est PUBLIÉE (validée contre le catalogue `m8.alerte_proposee`) puis livrée à M9 par le
    répartiteur réel : le registre durable est rempli par le consommateur de production."""
    for alerte in alertes:
        evenements.publier("m8.alerte_proposee", "m08-analytics", alerte, evenement_id=alerte["evenement_id"])
    resume = evenements.repartir(departements, limite=len(alertes) + 10, maintenant="2026-09-29T00:00:00+00:00")
    assert resume["traites"] == len(alertes) and resume["echecs"] == 0 and resume["quarantaines"] == 0


def test_avant_la_borne_trente_alertes_depassaient_la_limite_du_socle(base_durable, departements):
    """La preuve de la régression : la liste entière, telle que l'outil la rendait, dépasse 6 000 caractères."""
    _livrer_par_le_bus([_alerte(numero) for numero in range(30)], departements)

    en_registre = [dict(m) for m in stockage.maillons("m09-strategic-intelligence", "alertes_m8")]

    assert len(en_registre) == 30
    assert _taille({"ok": True, "resultat": en_registre}) > jetons.LIMITE_SORTIE_DEFAUT


def test_trente_alertes_reelles_sont_lues_par_capacites_sans_troncature_ni_doublon(
    base_durable, departements, capacites,
):
    alertes = [_alerte(numero) for numero in range(30)]
    _livrer_par_le_bus(alertes, departements)

    def lire(depart: int) -> dict:
        reponse = capacites.appeler(LIRE, {"depart": depart})
        assert reponse["ok"] is True, reponse
        assert "tronque" not in reponse and "apercu" not in reponse  # pas l'aperçu coupé de `_tronquer`
        assert _taille(reponse) <= jetons.LIMITE_SORTIE_DEFAUT
        return reponse

    pages = _pages(lire)

    assert len(pages) > 2 and all(p["total"] == 30 for p in pages)
    assert _identifiants(pages) == [a["evenement_id"] for a in reversed(alertes)]
    assert len(set(_identifiants(pages))) == 30


def test_un_depart_au_dela_de_la_fin_est_un_refus_metier_par_capacites(base_durable, departements, capacites):
    _livrer_par_le_bus([_alerte(numero) for numero in range(3)], departements)

    au_dela = capacites.appeler(LIRE, {"depart": 99})
    negatif = capacites.appeler(LIRE, {"depart": -2})

    assert au_dela["ok"] is False and au_dela["erreur"] == "refus_metier" and "depart=0" in au_dela["details"]
    assert negatif["ok"] is False and negatif["erreur"] == "refus_metier"
    assert "entier supérieur ou égal à 0" in negatif["details"]
