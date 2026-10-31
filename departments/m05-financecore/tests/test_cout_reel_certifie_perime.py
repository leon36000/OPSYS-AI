"""E1 (régression I5) : la cascade ORDINAIRE de M5 ne remplace pas un coût certifié et ne le laisse pas périmé.

Deux niveaux. (1) Fonctions pures de `cout_reel.py` : l'empreinte `empreinte_hors_ventilation` (ce qui change et ce
qui ne change pas), la décision `decision_apres_etat_certifie` (ordinaire | conserver | perime), le marquage
`marquer_certifie_perime`. (2) La cascade réelle (`_essayer_cout_reel`) sur une base SQLite temporaire, avec une trace
« certifiée » SYNTHÉTIQUE posée dans le registre (la vraie voie certifiée, avec projection M4, est prouvée par
`tests/test_regression_cascade_cout_certifie.py`) : décisions de bout en bout, schéma de l'événement, voie console.
Identifiants et montants fictifs.
"""

from __future__ import annotations

import copy
import re
from decimal import Decimal

import m5_financecore.outils as outils_mod
import pytest
from m5_financecore import cout_reel

from opsys import evenements, stockage
from opsys.departements import charger_departements

FICTIF = True
_DEPARTEMENT = "m05-financecore"
_M6 = "m06-material-control"
MATERIAU = "gouttiere-alu-5po-fictif"
COMPLETION = "2026-09-25T16:30:00-04:00"
CODE = "REJ-COUT-CERTIFIE-A-RECALCULER"


# --------------------------------------------------------------------------------------- pièces pures
def _wct(**surcharges):
    base = {"wct_id": "WCT-1", "intervention_id": "INT-1", "devis_id": "DEVIS-1",
            "horodatage_completion": "2026-09-15T15:00:00+00:00", "duree_reelle_minutes": 180}
    return {**base, **surcharges}


def _signal(reelle="42.0"):
    return {"wct_id": "WCT-1", "chantier_id": "CH-1", "statut_variance": "evaluee", "signal_critique": False,
            "horodatage_completion": "2026-09-15T15:00:00+00:00",
            "lignes": [{"materiau": MATERIAU, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": reelle,
                        "ecart_pourcentage": "0.05", "critique": False}]}


def _prix(prix=8.0):
    return {"materiau_id": MATERIAU, "fournisseur_id": "gentek-fictif", "prix_unitaire": prix, "devise": "CAD",
            "date_effet": "2026-09-01", "source_document": None, "unite": "pi"}


def _facture(statut="BROUILLON", montant="600.00"):
    return {"facture_id": "fac-DEVIS-1", "statut": statut, "montant_avant_taxes": Decimal(montant)}


def _devis(**surcharges):
    base = {"devis_id": "DEVIS-1", "chantier_id": "CH-1", "cout_total": "480.00", "prix_total": "600.00",
            "taux_marge": "0.25"}
    return {**base, **surcharges}


def _rentabilite(*, wct=None, signal=None, prix=8.0, facture="BROUILLON", montant="600.00", taux="50.00",
                 devis=None, autres=()):
    cout = cout_reel.calculer_cout_reel(wct or _wct(), signal or _signal(), [_prix(prix)], taux, autres)
    return cout_reel.calculer_rentabilite(
        cout, _facture(facture, montant) if facture else None, devis or _devis(), devis_id="DEVIS-1",
        chantier_id="CH-1")


def _empreinte(**kw):
    return _rentabilite(**kw)[cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION]


def test_l_empreinte_hors_ventilation_ignore_la_main_d_oeuvre_et_suit_le_reste():
    ref = _rentabilite()
    base = ref[cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION]
    assert re.fullmatch(r"[0-9a-f]{64}", base)
    # Ce qui est de la main-d'oeuvre n'y entre pas (mais change `version_entrees`) : durée scalaire, taux horaire.
    for variante in (_rentabilite(wct=_wct(duree_reelle_minutes=240)), _rentabilite(taux="60.00")):
        assert variante[cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION] == base
        assert variante["version_entrees"] != ref["version_entrees"]
    # ENVOYEE -> PAYEE : même prix, même finalité, même empreinte ; BROUILLON -> ENVOYEE : la finalité change.
    assert _empreinte(facture="PAYEE") == _empreinte(facture="ENVOYEE")
    assert _empreinte(facture="ENVOYEE") != base
    # Tout le reste est une entrée réelle.
    for nom, variante in {
        "prix du livre": _empreinte(prix=9.0),
        "quantité": _empreinte(signal=_signal("56.0")),
        "montant de la facture": _empreinte(montant="650.00"),
        "facture absente": _empreinte(facture=None),
        "devis": _empreinte(devis=_devis(prix_total="700.00")),
        "autre WCT": _empreinte(autres=("WCT-2",)),
        "autre WCT reçu (identité)": _empreinte(wct=_wct(wct_id="WCT-9")),
        "date du WCT": _empreinte(wct=_wct(horodatage_completion="2026-09-16T15:00:00+00:00")),
    }.items():
        assert variante != base, nom


def test_la_trace_porte_l_empreinte_au_niveau_de_la_trace_pas_dans_la_rentabilite():
    rentabilite = _rentabilite()
    trace = cout_reel.construire_trace(rentabilite, "2026-09-15T15:00:00+00:00")
    assert trace[cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION] == rentabilite[cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION]
    assert cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION not in trace["rentabilite"]
    assert "version_entrees" not in trace["rentabilite"]
    # L'événement du bus (liste blanche, schéma fermé) ne la porte pas : pas de changement de schéma.
    charge = cout_reel.charge_evenement(rentabilite, 1, "2026-09-15T15:00:00+00:00")
    assert cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION not in charge


def _trace_certifiee(rentabilite=None, *, source_tarifs="tarifs-A", empreinte=True, mo_statut="complet",
                     provenance="provenance_service_v1"):
    """Une trace qui se présente comme certifiée (SYNTHÉTIQUE : modèle de la décision, pas une preuve de M4)."""
    trace = copy.deepcopy(cout_reel.construire_trace(rentabilite or _rentabilite(), COMPLETION))
    trace[provenance] = {"source_tarifs": source_tarifs, "version": "opsys.m4.temps_certifies.v3"}
    mo = trace["rentabilite"]["cout_reel"]["main_d_oeuvre"]
    mo.update({"statut": mo_statut, "projection_empreinte": "a" * 64})
    if not empreinte:
        del trace[cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION]
    return trace


def _decision(trace, rentabilite=None, tarifs="tarifs-A"):
    return cout_reel.decision_apres_etat_certifie(trace, rentabilite or _rentabilite(), lambda: tarifs)


def test_decision_conserver_quand_seule_la_ventilation_manque():
    assert _decision(_trace_certifiee()) == "conserver"
    # Un rejeu, ou ENVOYEE -> PAYEE, ne change pas l'empreinte : conservé.
    trace = _trace_certifiee(_rentabilite(facture="ENVOYEE"))
    assert _decision(trace, _rentabilite(facture="PAYEE")) == "conserver"


@pytest.mark.parametrize("actuelle", [
    pytest.param(dict(prix=9.0), id="prix_du_livre"),
    pytest.param(dict(signal=_signal("56.0")), id="quantite"),
    pytest.param(dict(facture="ENVOYEE"), id="facture_envoyee"),
    pytest.param(dict(facture=None), id="facture_absente"),
    pytest.param(dict(devis=_devis(cout_total="500.00")), id="devis"),
    pytest.param(dict(autres=("WCT-2",)), id="autre_wct"),
])
def test_decision_perime_quand_une_entree_change_vraiment(actuelle):
    assert _decision(_trace_certifiee(), _rentabilite(**actuelle)) == "perime"


def test_decision_perime_quand_les_tarifs_changent_ou_ne_se_lisent_pas_ou_que_la_trace_ne_le_prouve_pas():
    assert _decision(_trace_certifiee(), tarifs="tarifs-B") == "perime"
    assert _decision(_trace_certifiee(), tarifs=None) == "perime"  # historique des tarifs illisible : fail-closed
    assert _decision(_trace_certifiee(source_tarifs=None)) == "perime"
    assert _decision(_trace_certifiee(empreinte=False)) == "perime"  # trace antérieure à E1 : non prouvable


def test_decision_ordinaire_quand_la_trace_n_est_pas_une_main_d_oeuvre_certifiee():
    appels = []

    def tarifs():
        appels.append(1)
        return "tarifs-A"

    rentabilite = _rentabilite()
    for trace in (
        None,
        cout_reel.construire_trace(rentabilite, COMPLETION),                      # trace ordinaire
        _trace_certifiee(mo_statut="partiel"),                                    # équipes à tarifer
        _trace_certifiee(mo_statut="non_disponible"),                             # revue ou équipes à vérifier
        _trace_certifiee(provenance="provenance_v3"),                             # voie console, jamais publiée
        {**_trace_certifiee(), "provenance_service_v1": "pas-un-dict"},
    ):
        assert cout_reel.decision_apres_etat_certifie(trace, rentabilite, tarifs) == "ordinaire"
    assert appels == []  # la lecture des tarifs n'est faite que pour une trace certifiée


def test_marquer_certifie_perime_ajoute_le_manque_sans_toucher_la_version_ni_le_verdict():
    rentabilite = _rentabilite()
    marquee = cout_reel.marquer_certifie_perime(rentabilite)
    assert [e["code"] for e in marquee["manque"]][-1] == CODE
    assert marquee["manque"][:-1] == rentabilite["manque"]
    assert marquee["version_entrees"] == rentabilite["version_entrees"]
    assert marquee["verdict"] == "PARTIELLE" and marquee["marge_reelle"] is None
    assert len(rentabilite["manque"]) == len(marquee["manque"]) - 1  # l'original n'est pas modifié
    charge = cout_reel.charge_evenement(marquee, 3, COMPLETION)
    assert CODE in charge["manque"] and charge["marge_reelle_cad"] is None and charge["verdict"] == "PARTIELLE"
    assert re.fullmatch(r"REJ-[A-Z0-9-]+", CODE)  # le motif du schéma du catalogue
    # Jamais sur un état qui porte une marge : un faux périmé cacherait un vrai chiffre.
    with pytest.raises(ValueError):
        cout_reel.marquer_certifie_perime({**rentabilite, "marge_reelle": Decimal("1.00")})


# --------------------------------------------------------------------------------------- cascade réelle
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m5-certifie-perime.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils_mod.utiliser_stockage_durable()
    yield url
    stockage.liberer()


def _charges():
    devis = {
        "devis_id": "DEVIS-1", "lead_id": "LEAD-1-fictif", "chantier_id": "CHANTIER-1",
        "lignes": [{"reference_ligne": "DEVIS-1-L0", "description": "Gouttières 5po aluminium", "quantite": "40",
                    "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "400.00",
                    "reference_besoin_materiau": MATERIAU},
                   {"reference_ligne": "DEVIS-1-L1", "description": "Main d'oeuvre installation", "quantite": "1",
                    "unite": "forfait", "prix_unitaire": "200.00", "prix_ligne": "200.00",
                    "reference_besoin_materiau": None}],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
        "horodatage_acceptation": "2026-09-20T10:00:00-04:00",
    }
    wct = {
        "wct_id": "WCT-1", "intervention_id": "INT-WCT-1", "lead_id": "LEAD-1-fictif", "technicien_id": "TECH-1",
        "horodatage_completion": COMPLETION, "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 180, "ecart_signale": False, "revue_id": None, "hash_maillon": "hash-WCT-1",
        "consommateurs_cibles": ["M5"], "devis_id": "DEVIS-1", "statut": "completed_verified",
    }
    variance = {
        "evenement_id": "m6-variance-WCT-1-evaluee", "wct_id": "WCT-1", "intervention_id": "INT-WCT-1",
        "chantier_id": "CHANTIER-1", "statut_variance": "evaluee", "signal_critique": False,
        "seuil_pourcentage": 0.3, "horodatage_completion": COMPLETION,
        "lignes": [{"materiau": MATERIAU, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": "42.0",
                    "ecart_pourcentage": "0.05", "critique": False}],
    }
    return devis, wct, variance


def _livrer():
    resume = evenements.repartir({_DEPARTEMENT: charger_departements()[_DEPARTEMENT]},
                                 maintenant="2026-09-25T17:00:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


@pytest.fixture
def chantier_ordinaire(base_durable):
    """Devis, WCT et variance livrés par le vrai bus, prix au livre : un état ORDINAIRE tracé (partiel)."""
    with stockage.transaction():
        stockage.maillons(_M6, "livre_prix").append(_prix(8.0))
    devis, wct, variance = _charges()
    evenements.publier("m3.devis_accepte", "m03-estimation", devis)
    evenements.publier("m4.travaux_termines", "m04-field-ops", wct)
    evenements.publier("m6.variance_chantier", _M6, variance, evenement_id=variance["evenement_id"])
    _livrer()


def _traces():
    with stockage.transaction():
        return [m for m in stockage.maillons(_DEPARTEMENT, "rentabilite") if m["devis_id"] == "DEVIS-1"]


def _evenements_m5():
    from sqlalchemy import select

    from opsys.stockage.schema import EVENEMENTS_SORTANTS
    with stockage.transaction() as cnx:
        return cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m5.rentabilite_chantier")
            .order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)).scalars().all()


def _essayer():
    with stockage.transaction():
        return outils_mod._essayer_cout_reel("DEVIS-1")


def _poser_trace_certifiee_synthetique(monkeypatch, *, empreinte=True, source_tarifs="tarifs-A",
                                       provenance="provenance_service_v1"):
    """Ajoute au registre une trace qui se présente comme certifiée, calculée sur l'état d'AUJOURD'HUI, et fixe la
    lecture des tarifs. Écrite par `_consigner_rentabilite` (publiée au bus) comme le fait la voie de service."""
    monkeypatch.setattr(outils_mod, "_source_tarifs_equipes_ou_none", lambda: "tarifs-A")
    with stockage.transaction():
        etat = outils_mod._etat_chantier("DEVIS-1")
        rentabilite = etat["rentabilite"]
        trace = cout_reel.construire_trace(rentabilite, etat["horodatage"])
        trace[provenance] = {"source_tarifs": source_tarifs}
        mo = trace["rentabilite"]["cout_reel"]["main_d_oeuvre"]
        mo.update({"statut": "complet", "projection_empreinte": "a" * 64})
        if not empreinte:
            del trace[cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION]
        # La version doit différer de l'ordinaire, comme une vraie trace certifiée (ventilation dans les entrées).
        trace["version_entrees"] = "f" * 64
        registre = stockage.maillons(_DEPARTEMENT, "rentabilite")
        sequence = len(registre) + 1
        registre.append(trace)
        outils_mod._publier_rentabilite({**rentabilite, "version_entrees": trace["version_entrees"]}, sequence,
                                        etat["horodatage"])


def test_cascade_conserve_la_trace_certifiee_et_n_ecrit_rien(base_durable, chantier_ordinaire, monkeypatch):
    _poser_trace_certifiee_synthetique(monkeypatch)
    traces, evts = _traces(), _evenements_m5()
    assert _essayer() == {"statut": "certifie_conserve"}
    assert _essayer() == {"statut": "certifie_conserve"}  # convergence
    assert (_traces(), _evenements_m5()) == (traces, evts)


def test_cascade_une_entree_change_la_trace_est_perimee_et_publie_le_manque(
        base_durable, chantier_ordinaire, monkeypatch):
    _poser_trace_certifiee_synthetique(monkeypatch)
    avant, evts = _traces(), _evenements_m5()
    with stockage.transaction():
        stockage.maillons(_M6, "livre_prix").append(_prix(9.0) | {"date_effet": "2026-09-02"})
    assert _essayer() == {"statut": "tracee_certifie_perime"}
    apres = _traces()
    assert apres[:-1] == avant and len(apres) == len(avant) + 1  # append-only, un seul maillon de plus
    nouvelle = apres[-1]
    assert nouvelle["verdict"] == "PARTIELLE" and "provenance_service_v1" not in nouvelle
    assert CODE in [e["code"] for e in nouvelle["rentabilite"]["manque"]]
    nouveaux = _evenements_m5()[len(evts):]
    assert len(nouveaux) == 1  # l'événement a franchi la validation du catalogue (schéma fermé)
    # Convergence : le même état ordinaire n'est pas retracé, et la trace périmée n'est plus « certifiée ».
    assert _essayer() == {"statut": "deja_tracee"}
    assert (_traces(), _evenements_m5()) == (apres, evts + nouveaux)


def test_cascade_une_trace_certifiee_sans_empreinte_ne_peut_pas_etre_conservee(
        base_durable, chantier_ordinaire, monkeypatch):
    _poser_trace_certifiee_synthetique(monkeypatch, empreinte=False)
    assert _essayer() == {"statut": "tracee_certifie_perime"}


def test_cascade_les_tarifs_changes_perimement_le_certifie(base_durable, chantier_ordinaire, monkeypatch):
    _poser_trace_certifiee_synthetique(monkeypatch, source_tarifs="tarifs-A")
    monkeypatch.setattr(outils_mod, "_source_tarifs_equipes_ou_none", lambda: "tarifs-B")
    assert _essayer() == {"statut": "tracee_certifie_perime"}


def test_cascade_une_trace_de_la_voie_console_n_est_pas_publiee_et_ne_masque_pas_le_certifie(
        base_durable, chantier_ordinaire, monkeypatch):
    """La voie console (`provenance_v3`) écrit sans publier : une telle trace en DERNIER ne doit pas faire retomber
    la cascade dans l'écrasement du certifié publié juste avant elle."""
    _poser_trace_certifiee_synthetique(monkeypatch)
    with stockage.transaction():
        etat = outils_mod._etat_chantier("DEVIS-1")
        trace = cout_reel.construire_trace(etat["rentabilite"], etat["horodatage"])
        trace["version_entrees"] = "e" * 64
        trace["provenance_v3"] = {"source_tarifs": "tarifs-A"}
        stockage.maillons(_DEPARTEMENT, "rentabilite").append(trace)
    traces, evts = _traces(), _evenements_m5()
    assert _essayer() == {"statut": "certifie_conserve"}
    assert (_traces(), _evenements_m5()) == (traces, evts)


def test_cascade_sans_trace_certifiee_le_comportement_d_avant_est_inchange(base_durable, chantier_ordinaire):
    assert _essayer() == {"statut": "deja_tracee"}
    with stockage.transaction():
        stockage.maillons(_M6, "livre_prix").append(_prix(9.0) | {"date_effet": "2026-09-02"})
    avant = _traces()
    assert _essayer() == {"statut": "tracee"}  # pas « périmé » : il n'y avait rien de certifié
    assert CODE not in [e["code"] for e in _traces()[-1]["rentabilite"]["manque"]]
    assert len(_traces()) == len(avant) + 1
