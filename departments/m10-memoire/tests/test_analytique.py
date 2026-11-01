"""M8.18 — M10 mémorise les faits analytiques consolidés que M8 publie (`m8.fait_consolide`).

Prouve (données fictives, vrai bus, vraie base migrée) : la charge est gardée par liste blanche et formes fermées (un
champ hors
forme est un refus qui nomme le CHAMP, jamais la valeur) ; le type, le producteur et la confidentialité FINANCIAL sont
posés
par M10 après la charge, que celle-ci ne peut ni choisir ni rouvrir ; une consolidation n'est mémorisée qu'une fois ; le
registre est distinct de ceux des événements et des affaires ; la lecture admin pagine et rend la dernière valeur d'une
mesure ; rien de personnel n'entre.
"""

from __future__ import annotations

import copy

import pytest
from m10_memoire import analytique, outils, registre

from opsys import evenements, stockage
from opsys.departements import charger_departements

FICTIF = True
EMPREINTE = "a" * 64
VERSION = "b" * 64


def _mesure(metric_id="m8_taux_acceptation_pct", **surcharges):
    base = {
        "metric_id": metric_id,
        "nom": "Taux d'acceptation des devis",
        "domaine": "ventes",
        "unite": "pourcentage",
        "proprietaire": "m03-estimation",
        "statut": "calculee",
        "valeur": "50.00",
        "version_definition": VERSION,
        "dernier_fait_le": "2026-10-30T11:06:00-04:00",
        "fraicheur": "a_jour",
    }
    base.update(surcharges)
    return base


def _charge(numero=1, **surcharges):
    base = {
        "evenement_id": "m8-faits-" + f"{numero:064x}",
        "consolide_le": "2026-10-30T20:00:00-04:00",
        "empreinte_registres": EMPREINTE,
        "version_catalogue": VERSION,
        "premiere_consolidation": True,
        "mesures": [
            _mesure(),
            _mesure(
                "m8_cash_libre_cad",
                nom="Cash libre",
                domaine="finance",
                unite="CAD",
                proprietaire="m05-financecore",
                valeur="25000.00",
            ),
            _mesure(
                "m8_clics_par_contenu",
                nom="Clics",
                domaine="marketing",
                unite="clics",
                proprietaire="m07-marketing",
                statut="non_calculable",
                valeur=None,
                dernier_fait_le=None,
                fraicheur="manquant",
            ),
        ],
        "changements_definition": [],
        "anomalies": [],
        "mention": "Faits consolidés par M8. À valider auprès d'un comptable (CPA) / professionnel qualifié.",
    }
    base.update(surcharges)
    return base


# -- le module pur ---------------------------------------------------------------------------------------------------
def test_la_charge_valide_est_gardee_par_liste_blanche_et_posee_financiere():
    charge = _charge(confidentialite="PUBLIC_INTERNAL", producteur="m99", type_entree="evenement_memorise", lead_id="x")
    entree = analytique.entree(analytique.extraire(charge))
    assert entree["type_entree"] == "fait_analytique" and entree["producteur"] == "m08-analytics"
    assert entree["confidentialite"] == "FINANCIAL"  # la charge n'a pu ni choisir ni rouvrir
    assert "lead_id" not in entree and entree["horodatage"] == "2026-10-30T20:00:00-04:00"
    assert [m["valeur"] for m in entree["mesures"]] == ["50.00", "25000.00", None]


@pytest.mark.parametrize(
    ("mutation", "champ"),
    [
        (lambda c: c.pop("mesures"), "mesures"),
        (lambda c: c.update({"mesures": []}), "mesures"),
        (lambda c: c.update({"mesures": [_mesure()] * 41}), "mesures"),
        (lambda c: c.update({"evenement_id": "m8-faits-xyz"}), "evenement_id"),
        (lambda c: c.update({"consolide_le": "hier"}), "consolide_le"),
        (lambda c: c.update({"empreinte_registres": "A" * 64}), "empreinte_registres"),
        (lambda c: c.update({"premiere_consolidation": "oui"}), "premiere_consolidation"),
        (lambda c: c["mesures"][0].update({"valeur": "50,00"}), "mesures[0].valeur"),
        (lambda c: c["mesures"][0].update({"valeur": 50}), "mesures[0].valeur"),
        (lambda c: c["mesures"][0].update({"statut": "non_calculable"}), "mesures[0].statut"),
        (lambda c: c["mesures"][2].update({"statut": "calculee"}), "mesures[2].statut"),
        (lambda c: c["mesures"][0].update({"domaine": "personnel"}), "mesures[0].domaine"),
        (lambda c: c["mesures"][0].update({"fraicheur": "frais"}), "mesures[0].domaine"),
        (lambda c: c["mesures"][0].update({"metric_id": "taux"}), "mesures[0].metric_id"),
        (lambda c: c["mesures"][0].update({"proprietaire": "technicien-jean"}), "mesures[0].proprietaire"),
        (lambda c: c["mesures"][0].update({"technicien": "jean"}), "mesures[0]"),
        (lambda c: c["mesures"][0].pop("unite"), "mesures[0]"),
        (lambda c: c["mesures"][0].update({"nom": "x" * 121}), "mesures[0].nom"),
        (lambda c: c["mesures"][0].update({"version_definition": "zz"}), "mesures[0].version_definition"),
        (
            lambda c: c.update(
                {"changements_definition": [{"metric_id": "m8_a", "ancienne": "x", "nouvelle": VERSION}]}
            ),
            "changements_definition[0].ancienne",
        ),
        (lambda c: c.update({"changements_definition": "non"}), "changements_definition"),
        (lambda c: c.update({"anomalies": [{"metric_id": "m8_a", "type": "inventee"}]}), "anomalies[0]"),
        (lambda c: c.update({"anomalies": [{"metric_id": "m8_a", "type": "perimee", "extra": 1}]}), "anomalies[0]"),
        (lambda c: c.update({"mention": ""}), "mention"),
        (lambda c: c.update({"mention": 12}), "mention"),
    ],
)
def test_un_champ_hors_de_sa_forme_est_refuse_et_le_detail_nomme_le_champ(mutation, champ):
    charge = _charge()
    mutation(charge)
    with pytest.raises(analytique.ChampRefuse) as exc:
        analytique.extraire(charge)
    assert exc.value.code in (analytique.REJ_ANALYTIQUE_CHAMP_INVALIDE, analytique.REJ_ANALYTIQUE_CHAMP_MANQUANT)
    assert exc.value.detail == champ


def test_le_refus_ne_recopie_jamais_la_valeur_fautive():
    valeur = "jean.tremblay@example.test"
    charge = _charge()
    charge["mesures"][0]["nom"] = valeur * 10  # trop long : refusé
    with pytest.raises(analytique.ChampRefuse) as exc:
        analytique.extraire(charge)
    assert valeur not in str(exc.value) and valeur not in repr(exc.value.verdict())


def test_memoriser_est_idempotent_par_evenement_et_chaine_valide():
    cible = registre.Registre()
    premier, verdict = analytique.memoriser(_charge(1), cible)
    assert verdict is None and premier["deja_memorise"] is False
    rejoue, _ = analytique.memoriser(copy.deepcopy(_charge(1)), cible)
    assert rejoue["deja_memorise"] is True and rejoue["maillon"]["ligne_id"] == premier["maillon"]["ligne_id"]
    deuxieme, _ = analytique.memoriser(_charge(2), cible)
    assert deuxieme["deja_memorise"] is False and len(cible.lire()) == 2 and cible.valider_chaine() == (True, "")


def test_un_refus_n_ecrit_rien():
    cible = registre.Registre()
    charge = _charge()
    charge["mesures"][0]["domaine"] = "personnel"
    resultat, verdict = analytique.memoriser(charge, cible)
    assert resultat is None and verdict["code"] == analytique.REJ_ANALYTIQUE_CHAMP_INVALIDE and cible.lire() == []


def test_lister_et_derniere_valeur():
    cible = registre.Registre()
    analytique.memoriser(_charge(1), cible)
    plus_recent = _charge(2, consolide_le="2026-10-31T20:00:00-04:00")
    plus_recent["mesures"][0]["valeur"] = "55.00"
    plus_recent["anomalies"] = [{"metric_id": "m8_cash_libre_cad", "type": "perimee"}]
    analytique.memoriser(plus_recent, cible)
    page = analytique.lister(cible, 1, 0)
    assert page["total"] == 2 and page["consolidations"][0]["consolide_le"] == "2026-10-31T20:00:00-04:00"
    assert page["consolidations"][0]["anomalies"] == plus_recent["anomalies"] and page["suivant"] == 1
    assert "mesures" not in page["consolidations"][0] and page["confidentialite"] == "FINANCIAL"
    assert analytique.lister(cible, 1, 1)["suivant"] is None
    derniere = analytique.derniere_valeur(cible, "m8_taux_acceptation_pct")
    assert derniere["trouvee"] is True and derniere["mesure"]["valeur"] == "55.00"
    assert analytique.derniere_valeur(cible, "m8_inconnue") == {"trouvee": False, "metric_id": "m8_inconnue"}


# -- le vrai bus
# ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _livrer(*charges):
    for charge in charges:
        evenements.publier("m8.fait_consolide", "m08-analytics", charge, evenement_id=charge["evenement_id"])
    evenements.repartir({"m10-memoire": charger_departements()["m10-memoire"]}, maintenant="2026-10-30T21:00:00-04:00")


def _faits():
    return stockage.maillons("m10-memoire", "faits_analytiques")


def test_le_bus_livre_la_consolidation_une_seule_fois(base_durable):
    _livrer(_charge(1))
    _livrer(_charge(1))  # republication du même événement : le bus la rejoue, M10 ne la double pas
    assert len(_faits()) == 1 and _faits()[0]["producteur"] == "m08-analytics"
    _livrer(_charge(2))
    assert len(_faits()) == 2
    assert not [m for m in stockage.maillons("m10-memoire", "evenements") if m.get("type_entree") == "fait_analytique"]
    assert not [m for m in stockage.maillons("m10-memoire", "affaires") if m.get("type_entree") == "fait_analytique"]


def test_le_catalogue_du_socle_refuse_avant_m10_une_charge_avec_une_personne(base_durable):
    charge = _charge(1)
    charge["mesures"][0]["technicien"] = "jean"
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier("m8.fait_consolide", "m08-analytics", charge, evenement_id=charge["evenement_id"])


def test_la_lecture_admin_pagine_borne_et_refuse_les_arguments_invalides(base_durable):
    _livrer(_charge(1), _charge(2))
    lecture = outils.lire_faits_analytiques(limite=1, decalage=0)
    assert lecture["total"] == 2 and len(lecture["consolidations"]) == 1
    derniere = outils.lire_faits_analytiques(metric_id="m8_cash_libre_cad")
    assert derniere["trouvee"] is True and derniere["mesure"]["valeur"] == "25000.00"
    for args in ({"limite": 0}, {"limite": 9}, {"limite": "1"}, {"decalage": -1}):
        assert outils.lire_faits_analytiques(**args)["verdict"]["code"] == "REJ-ANALYTIQUE-PAGINATION-INVALIDE"
    for metric in ("taux", "m8_" + "x" * 90, 12):
        assert outils.lire_faits_analytiques(metric_id=metric)["verdict"]["code"] == "REJ-ANALYTIQUE-MESURE-INVALIDE"


def test_l_outil_de_lecture_est_n0_ferme_aux_appareils():
    outil = next(o for o in outils.outils() if o.nom == "m10_lire_faits_analytiques")
    assert outil.niveau_effectif.value == "N0" and outil.roles_appareil == frozenset()
