"""PLAN T1.5-e — l'admin lit TOUTES les attentes de sa section « À voir », page par page (E2E moteur).

Constat de T1.5 : la liste de l'app (`m9_lister_demandes_approbation`) bornait les attentes à 1 500 caractères
et ne faisait que COMPTER les suivantes (`attentes_reste`) : au-delà d'environ trois alertes, l'admin ne lisait
pas les autres sur son téléphone. `decalage_attentes` / `attentes_suivant` (T1.5-e) les rendent lisibles.

Le scénario est celui d'une semaine chargée, par la vraie porte d'appareil (comme
`test_travaux_termines_appareil.py`, dont ce fichier reprend l'amont : chantier préparé, matériel reçu,
journée de l'employé, bus livré) :

- deux chantiers terminés avec un écart de matériaux de 40 % : chacun laisse une complétion en revue (M4), une
  facture prête à envoyer et un chantier à réviser (M5) ;
- un chantier terminé sans histoire : une facture prête à envoyer (M5) ;
- le stock de l'article passe sous son seuil : un besoin de commande (M6, un par article).

Huit attentes, de trois départements. Ce que ces tests ne prouvent PAS : l'écran (Jest, `mobile/`) ni le core.

Suite (PLAN T1.5-d) : `m9_lire_alertes_m8` (`admin`) rendait TOUTES les alertes de M8 reçues, sans limite. Il est
borné comme le reste : ce fichier prouve, par la même porte d'appareil, que l'admin lit les alertes page par page
(`depart`, `prochain_depart`), sans troncature, doublon ni écriture, et que l'employé n'y entre pas.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import m6_material_control.outils as m6_outils
import pytest
import yaml
from harnais_e2e import Moteur, iso
from harnais_e2e_chantier import (
    MATERIAU_ID,
    AppEmploye,
    Chantier,
    debut_de_journee,
    png_minimal,
    preparer_chantier,
    receptionner_materiel_args,
)

from opsys import approbations, evenements, stockage
from opsys.approbations_appareil import BUDGET_ATTENTES

SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`
LISTER = "m9_lister_demandes_approbation"

# Stock final de l'article : 3 réceptions de 200 - (56 + 56 + 42) utilisés = 446 pi, sous ce seuil.
SEUIL_FRANCHI = {MATERIAU_ID: {"seuil_reapprovisionnement": 450, "quantite_cible": 600}}
TYPES_ATTENDUS = {
    "completion_en_revue": 2, "chantier_a_reviser": 2, "facture_brouillon": 3, "besoin_commande": 1,
}


@pytest.fixture
def reappro(monkeypatch, tmp_path):
    """Le `department.yaml` de M6 dont seul le bloc de réapprovisionnement change : M6 le relit à chaque appel."""
    reel = yaml.safe_load(m6_outils._MANIFESTE.read_text(encoding="utf-8"))

    def configurer(articles: dict[str, Any]) -> None:
        manifeste = {**reel, "configuration": {**reel["configuration"], "reapprovisionnement": {"articles": articles}}}
        chemin = tmp_path / "department-m6-a-voir.yaml"
        chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8")
        monkeypatch.setattr(m6_outils, "_MANIFESTE", chemin)

    return configurer


def _chantier_termine(moteur: Moteur, equipe: dict[str, Any], suffixe: str, jour: int, quantite: float) -> Chantier:
    """Un chantier de bout en bout jusqu'à la variance : le matériel arrive, l'employé fait sa journée et
    « Terminer », le bus livre la complétion, l'employé déclare `quantite` pi utilisés, le bus livre la variance."""
    chantier = preparer_chantier(moteur.departements, suffixe=suffixe, technicien="etienne",
                                 debut=debut_de_journee(jour))
    moteur.horloge.maintenant = chantier.debut
    moteur.drainer_bus(moteur.horloge.maintenant)  # le devis accepté est livré à M6 (prévu de matériaux)
    reception = equipe["admin"].appeler(
        "m6_receptionner_commande", receptionner_materiel_args(chantier), cle=f"mut-reception-{suffixe}",
        horodatage_appareil=iso(chantier.debut))
    assert reception.metier["accepte"] is True, reception.metier
    app = AppEmploye(moteur, equipe["employe"], chantier)
    completion = _journee_jusqu_a_la_completion(app)
    wct_id = completion.resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    app.attendre(minutes=5)
    assert app.declarer_materiaux(wct_id, quantite).metier["accepte"] is True
    moteur.drainer_bus(moteur.horloge.maintenant)
    return chantier


def _journee_jusqu_a_la_completion(app: AppEmploye):
    """La journée de `AppEmploye.journee_jusqu_a_la_completion`, geste pour geste. Une seule différence : avec
    plusieurs chantiers dans la même base, « chantiers du jour » les liste tous, pas seulement celui-ci."""
    interventions = {i["intervention_id"] for i in app.chantiers_du_jour().resultat}
    assert app.chantier.intervention_id in interventions
    app.attendre(minutes=1)
    assert app.donner_consentement_gps().metier["accepte"] is True
    app.attendre(minutes=29)
    assert app.en_route().metier["accepte"] is True
    app.attendre(minutes=30)
    assert app.pointer("arrivee").metier["accepte"] is True
    app.attendre(hours=2, minutes=55)
    photo = app.deposer_fichier(png_minimal(largeur=4))
    signature = app.deposer_fichier(png_minimal(largeur=2))
    app.attendre(minutes=5)
    assert app.pointer("depart").metier["accepte"] is True
    app.attendre(minutes=5)
    return app.terminer(photo, signature)


@pytest.fixture
def semaine_chargee(moteur, equipe, reappro):
    reappro(SEUIL_FRANCHI)
    _chantier_termine(moteur, equipe, "AV-ECART-1", 21, 56.0)  # +40 % : en revue
    _chantier_termine(moteur, equipe, "AV-ECART-2", 22, 56.0)  # +40 % : en revue
    _chantier_termine(moteur, equipe, "AV-NORMAL", 23, 42.0)  # +5 % : vérifié
    return moteur


def _cle(attente: dict[str, Any]) -> tuple[str, str, str]:
    return attente["departement"], attente["type"], attente["id"]


def _console(moteur: Moteur) -> list[dict[str, Any]]:
    """La vérité de la console : `attentes_departements`, dans son ordre stable."""
    with stockage.transaction() as cnx:
        attentes, illisibles = approbations.attentes_departements(cnx, moteur.departements)
    assert illisibles == []
    return attentes


def _page(admin, decalage: int | None = None):
    """Un appel de l'écran : la première page sans argument, la suivante avec le seul rang."""
    reponse = admin.appeler(LISTER, {} if decalage is None else {"decalage_attentes": decalage})
    assert reponse.statut == 200 and reponse.metier["accepte"] is True, reponse.corps
    assert reponse.mesure.tronque is False and reponse.mesure.octets_texte < LIMITE_TRONCATURE
    return reponse.resultat


def _lire_tout(admin) -> list[dict[str, Any]]:
    """Comme l'app : page 0, puis `attentes_suivant` tant qu'il n'est pas nul. Rend les pages dans l'ordre."""
    pages = [_page(admin)]
    while pages[-1]["attentes_suivant"] is not None:
        pages.append(_page(admin, pages[-1]["attentes_suivant"]))
        assert len(pages) <= 20, "la lecture ne progresse pas"
    return pages


@SQLITE_SEULEMENT
def test_l_admin_lit_les_huit_attentes_page_par_page_chacune_une_seule_fois(moteur, equipe, semaine_chargee):
    admin = equipe["admin"]
    verite = _console(moteur)

    # -- la semaine chargée : huit attentes, de trois départements ---------------------------------------------
    par_type = {t: sum(1 for a in verite if a["type"] == t) for t in TYPES_ATTENDUS}
    assert par_type == TYPES_ATTENDUS and len(verite) == 8
    assert {a["departement"] for a in verite} == {"m04-field-ops", "m05-financecore", "m06-material-control"}
    (besoin,) = (a for a in verite if a["type"] == "besoin_commande")
    assert "446.0 pi en main, sous le seuil de 450 pi" in besoin["resume"]
    assert "154.0 pi pour atteindre 600 pi" in besoin["resume"]

    # -- avant T1.5-e : la première page ne montrait que les premières, et comptait le reste ---------------------
    avant = _page(admin)
    assert avant["total_attentes"] == 8 and 1 <= avant["attentes_affichees"] < 8
    assert avant["attentes_reste"] == 8 - avant["attentes_affichees"] > 0
    assert avant["attentes_decalage"] == 0 and avant["attentes_suivant"] == avant["attentes_affichees"]

    # -- l'app lit la suite, page par page, sans rien changer à l'état du moteur ----------------------------------
    empreinte = moteur.empreinte_etat()
    pages = _lire_tout(admin)
    assert moteur.empreinte_etat() == empreinte  # lire n'écrit rien : ni approbation, ni journal, ni registre

    print("MESURE-A-VOIR " + json.dumps({
        "attentes": 8, "pages": len(pages), "par_page": [p["attentes_affichees"] for p in pages],
        "octets_attentes": [sum(len(json.dumps(a, ensure_ascii=False)) for a in p["attentes"]) for p in pages],
        "duree_s": [round(m.duree_s, 3) for m in moteur.mesures if m.outil == LISTER][-len(pages):],
    }))
    assert len(pages) > 1
    lues = [a for page in pages for a in page["attentes"]]
    assert [_cle(a) for a in lues] == [_cle(a) for a in verite]  # toutes, une seule fois, dans l'ordre de la console
    assert len({_cle(a) for a in lues}) == 8
    rang = 0
    for page in pages:
        assert page["attentes_decalage"] == rang and page["total_attentes"] == 8
        assert page["attentes_affichees"] == len(page["attentes"]) >= 1
        assert sum(len(json.dumps(a, ensure_ascii=False)) for a in page["attentes"]) <= BUDGET_ATTENTES
        assert page["attentes_illisibles"] == []
        rang += page["attentes_affichees"]
        assert page["attentes_reste"] == 8 - rang
    assert pages[-1]["attentes_suivant"] is None and pages[-1]["attentes_reste"] == 0
    assert all(set(a) == {"type", "id", "departement", "departement_nom", "resume", "niveau", "depuis",
                          "action_proposee"} for a in lues)  # rien de plus qu'avant : pas de décision, pas d'argument

    # -- la liste des demandes, elle, ne change pas d'une page à l'autre ------------------------------------------
    assert {p["total_en_attente"] for p in pages} == {0}
    assert all(p["proprietaire"] is True for p in pages)

    # -- au-delà de la fin : une page vide, jamais une erreur ni une attente inventée -----------------------------
    for hors_plage in (8, 9, 500):
        vide = _page(admin, hors_plage)
        assert vide["attentes"] == [] and vide["attentes_affichees"] == 0
        assert vide["attentes_suivant"] is None and vide["attentes_reste"] == 0
        assert vide["attentes_decalage"] == hors_plage and vide["total_attentes"] == 8


@SQLITE_SEULEMENT
def test_les_pages_suivantes_ont_la_meme_portee_et_la_meme_identite_que_la_liste(moteur, equipe, semaine_chargee):
    employe = equipe["employe"]

    # L'employé n'a pas la portée de l'outil : le core (sa règle, refaite ici) le refuse, page 0 comme page 2.
    for args in ({}, {"decalage_attentes": 3}):
        refus = employe.appeler(LISTER, args)
        assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"]

    # Un rang qui n'est pas un entier ≥ 0 n'est jamais une page : un verdict, ou l'erreur d'arguments du socle.
    admin = equipe["admin"]
    negatif = admin.appeler(LISTER, {"decalage_attentes": -1})
    assert negatif.statut == 200 and negatif.metier["accepte"] is False
    assert negatif.metier["verdict"]["code"] == "decalage_invalide"
    texte = admin.appeler(LISTER, {"decalage_attentes": "3"})
    assert texte.enveloppe["ok"] is False and texte.enveloppe["erreur"] == "arguments_invalides"

    # Aucun paramètre ne désigne une personne : le socle refuse tout paramètre inconnu.
    for intrus in ("personne", "role", "decide_par", "appareil"):
        refuse = admin.appeler(LISTER, {"decalage_attentes": 0, intrus: "nathan"})
        assert refuse.enveloppe["ok"] is False and refuse.enveloppe["erreur"] == "arguments_invalides"


@SQLITE_SEULEMENT
def test_une_attente_traitee_entre_deux_pages_change_le_total_et_la_relecture_reste_complete(
    moteur, equipe, semaine_chargee
):
    """Les pages sont par rang : si l'état change entre deux lectures, le rang glisse. Le signal que l'écran
    utilise pour relire depuis le début est `total_attentes`, qui change ; une relecture depuis 0 est complète."""
    admin = equipe["admin"]
    premiere = _page(admin)
    assert premiere["total_attentes"] == 8

    # L'admin réapprovisionne (réception au dépôt) : le stock d'aujourd'hui remonte, le besoin de commande s'efface.
    chantier = _chantier_du_depot(moteur)
    args = receptionner_materiel_args(chantier, quantite=200.0)
    for cle in ("bon_demande", "reception_po"):
        args[cle] = {**args[cle], "po_id": f"PO-DEPOT-{chantier.devis_id}", "chantier_id": "DEPOT-AV-fictif"}
    reception = admin.appeler("m6_receptionner_commande", args, cle="mut-reception-depot-av",
                              horodatage_appareil=iso(moteur.horloge.maintenant))
    assert reception.metier["accepte"] is True

    suivante = _page(admin, premiere["attentes_suivant"])
    assert suivante["total_attentes"] == 7  # le signal : l'écran relit depuis le début

    relues = [a for page in _lire_tout(admin) for a in page["attentes"]]
    assert len(relues) == 7 and len({_cle(a) for a in relues}) == 7
    assert "besoin_commande" not in {a["type"] for a in relues}
    assert [_cle(a) for a in relues] == [_cle(a) for a in _console(moteur)]


def _chantier_du_depot(moteur: Moteur) -> Chantier:
    """Un chantier de rattachement pour la réception au dépôt (seuls `devis_id` et `chantier_id` servent)."""
    return Chantier(lead_id="LEAD-DEPOT-AV-fictif", devis_id="DEVIS-DEPOT-AV-fictif",
                    chantier_id="DEPOT-AV-fictif", intervention_id="", technicien="etienne",
                    debut=moteur.horloge.maintenant)


# ---------------------------------------------------------------------------------------------------------------
# PLAN T1.5-d : les alertes de M8 reçues par M9 se lisent par pages, par la porte d'appareil (rôle `admin`)
# ---------------------------------------------------------------------------------------------------------------
LIRE_ALERTES = "m9_lire_alertes_m8"
NB_ALERTES = 20
_DEBUT_ALERTES = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.UTC)


def _alerte_fictive(numero: int) -> dict[str, Any]:
    """Une alerte `m8.alerte_proposee` fictive (métrique `m8_metrique_fictive_NN`), valide contre le catalogue.
    Les numéros 7 et 8 ont le MÊME instant (départage par identifiant) ; le 13 est écrit en heure du Québec."""
    instant = _DEBUT_ALERTES + dt.timedelta(hours=7 if numero == 8 else numero)
    texte = instant.isoformat().replace("+00:00", "Z")
    if numero == 13:
        texte = instant.astimezone(dt.timezone(dt.timedelta(hours=-4))).isoformat()
    metrique = f"m8_metrique_fictive_{numero:02d}"
    return {
        "evenement_id": f"m8-alerte-{metrique}-REJ-QUALITE-DONNEE-PERIMEE-{texte}",
        "metric_id": metrique, "type_alerte": "REJ-QUALITE-DONNEE-PERIMEE",
        "quoi": f"Valeur périmée pour {metrique} (donnée fictive).", "a_qui": "m04-field-ops",
        "pourquoi": "âge observé 10.00 jours > fraîcheur attendue 2 jours. " + "Règle de fraîcheur fictive. " * 6,
        "preuve": {"metric_id": metrique, "fraicheur_jours": 10.0, "fraicheur_attendue_jours": 2},
        "action_proposee": "Rafraîchir la donnée à la source (action fictive proposée par M8, jamais exécutée).",
        "source": "source fictive de la définition de la métrique", "horodatage_reference": texte,
    }


def _instant_alerte(alerte: dict[str, Any]) -> dt.datetime:
    return dt.datetime.fromisoformat(alerte["horodatage_reference"].replace("Z", "+00:00"))


def _alertes_de_m9() -> list[dict[str, Any]]:
    return [dict(m) for m in stockage.maillons("m09-strategic-intelligence", "alertes_m8")]


def _page_alertes(admin, depart: int | None = None) -> dict[str, Any]:
    """Un appel de l'écran : la première page sans argument, la suivante avec le seul `depart`."""
    reponse = admin.appeler(LIRE_ALERTES, {} if depart is None else {"depart": depart})
    assert reponse.statut == 200 and reponse.enveloppe["ok"] is True, reponse.corps
    assert reponse.mesure.tronque is False and reponse.mesure.octets_texte < LIMITE_TRONCATURE
    return reponse.resultat


def _lire_toutes_les_alertes(admin) -> list[dict[str, Any]]:
    pages = [_page_alertes(admin)]
    while pages[-1]["prochain_depart"] is not None:
        pages.append(_page_alertes(admin, pages[-1]["prochain_depart"]))
        assert len(pages) <= 20, "la lecture ne progresse pas"
    return pages


@SQLITE_SEULEMENT
def test_l_admin_lit_les_alertes_de_m8_page_par_page_chacune_une_seule_fois(moteur, equipe):
    admin = equipe["admin"]

    # -- aucune alerte reçue : une page vide, qui le dit --------------------------------------------------------
    vide = _page_alertes(admin)
    assert vide["alertes"] == [] and vide["total"] == 0 and vide["prochain_depart"] is None

    # -- vingt alertes livrées par le vrai bus (validées contre le catalogue, reçues par le consommateur de M9) ----
    for numero in range(NB_ALERTES):
        alerte = _alerte_fictive(numero)
        evenements.publier("m8.alerte_proposee", "m08-analytics", alerte, evenement_id=alerte["evenement_id"])
    moteur.drainer_bus(moteur.horloge.maintenant)
    registre = _alertes_de_m9()
    assert len(registre) == NB_ALERTES
    assert len(json.dumps({"ok": True, "resultat": registre}, ensure_ascii=False)) > LIMITE_TRONCATURE  # avant la borne

    # -- ce que l'écran doit lire : le plus récent d'abord, à instant égal par identifiant ---------------------
    verite = sorted(registre, key=lambda a: (-_instant_alerte(a).timestamp(), a["evenement_id"]))
    sept, huit = (a for a in registre if a["metric_id"] in ("m8_metrique_fictive_07", "m8_metrique_fictive_08"))
    assert _instant_alerte(sept) == _instant_alerte(huit)  # le départage par identifiant est bien exercé

    empreinte = moteur.empreinte_etat()
    pages = _lire_toutes_les_alertes(admin)
    assert moteur.empreinte_etat() == empreinte  # lire n'écrit rien : ni approbation, ni journal, ni registre

    print("MESURE-ALERTES-M8 " + json.dumps({
        "alertes": NB_ALERTES, "pages": len(pages), "par_page": [p["affichees"] for p in pages],
        "octets_texte": [m.octets_texte for m in moteur.mesures if m.outil == LIRE_ALERTES][-len(pages):],
    }))
    assert len(pages) > 2
    lues = [a for page in pages for a in page["alertes"]]
    assert [a["evenement_id"] for a in lues] == [a["evenement_id"] for a in verite]  # toutes, une fois, dans l'ordre
    assert len({a["evenement_id"] for a in lues}) == NB_ALERTES
    assert lues == verite  # et telles que reçues : aucun champ retiré ni ajouté
    rang = 0
    for page in pages:
        assert page["type"] == "ALERTES_M8" and page["total"] == NB_ALERTES and page["depart"] == rang
        assert page["affichees"] == len(page["alertes"]) >= 1
        rang += page["affichees"]
        assert page["reste"] == NB_ALERTES - rang
        assert page["prochain_depart"] == (rang if rang < NB_ALERTES else None)
    assert pages[-1]["reste"] == 0 and pages[-1]["message"] is None and pages[0]["message"] is not None


@SQLITE_SEULEMENT
def test_les_alertes_reelles_de_m8_sont_lues_par_l_admin_dans_l_ordre_du_plus_recent(moteur, equipe, semaine_chargee):
    """Les alertes que M8 publie vraiment (trois chantiers terminés, un rappel « seuil à configurer » par jour de
    chantier) passent la validation stricte de l'outil : aucune n'est refusée ni retirée."""
    registre = _alertes_de_m9()
    assert len(registre) == 3 and {a["type_alerte"] for a in registre} == {"MESURE-SEUIL-A-CONFIGURER"}

    page = _page_alertes(equipe["admin"])

    assert page["total"] == 3 and page["affichees"] == 3 and page["prochain_depart"] is None
    assert [a["horodatage_reference"] for a in page["alertes"]] == sorted(
        (a["horodatage_reference"] for a in registre), reverse=True)  # des instants d'un même fuseau : reste 23, 22, 21
    assert sorted(a["evenement_id"] for a in page["alertes"]) == sorted(a["evenement_id"] for a in registre)


@SQLITE_SEULEMENT
def test_la_porte_refuse_l_employe_et_les_depart_invalides(moteur, equipe):
    for numero in range(3):
        alerte = _alerte_fictive(numero)
        evenements.publier("m8.alerte_proposee", "m08-analytics", alerte, evenement_id=alerte["evenement_id"])
    moteur.drainer_bus(moteur.horloge.maintenant)

    # L'employé n'a pas la portée de l'outil : le core (sa règle, refaite ici) le refuse, page 0 comme page 2.
    for args in ({}, {"depart": 2}):
        refus = equipe["employe"].appeler(LIRE_ALERTES, args)
        assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"]

    admin = equipe["admin"]
    # Au-delà de la fin, ou négatif : un refus métier qui dit quoi corriger, jamais une page inventée.
    au_dela = admin.appeler(LIRE_ALERTES, {"depart": 4})
    assert au_dela.statut == 200 and au_dela.enveloppe["ok"] is False and au_dela.enveloppe["erreur"] == "refus_metier"
    assert "depart=0" in au_dela.enveloppe["details"]
    negatif = admin.appeler(LIRE_ALERTES, {"depart": -1})
    assert negatif.enveloppe["ok"] is False and negatif.enveloppe["erreur"] == "refus_metier"
    assert "entier supérieur ou égal à 0" in negatif.enveloppe["details"]
    # `depart` égal au total : la fin, une page vide.
    fin = _page_alertes(admin, 3)
    assert fin["alertes"] == [] and fin["total"] == 3 and fin["prochain_depart"] is None

    # Ni un texte ni un paramètre inconnu : l'erreur d'arguments du socle.
    for args in ({"depart": "1"}, {"depart": 1.5}, {"depart": 0, "limite": 5}, {"depart": 0, "personne": "nathan"}):
        refuse = admin.appeler(LIRE_ALERTES, args)
        assert refuse.enveloppe["ok"] is False and refuse.enveloppe["erreur"] == "arguments_invalides", args
