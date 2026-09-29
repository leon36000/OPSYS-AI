"""L'entonnoir commercial par le bus d'événements réel (PLAN T4.19) : M8 consomme les faits de M2
(`m2.client_associe`, `m2.lead_assigne`) et de M3 (`m3.devis_envoye`, `m3.devis_accepte`,
`m3.devis_sans_reponse`), les range au registre `faits_entonnoir` et les mesure à la lecture.

Bout en bout, sans doublure : `opsys.evenements.repartir`, le manifeste réel de M8 (seul abonné) et une base SQLite
temporaire migrée. Les charges sont des événements synthétiques et fictifs, validés par le catalogue à la
publication. Ce fichier prouve ce que les consommateurs font du bus (idempotence, ordre, ce qui est gardé) ; la
vue exécutive a le sien (`test_vue_executive.py`), et le trajet complet par les vrais producteurs est dans
`tests/test_cascade_mesure_m8_m9.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m8_analytics import entonnoir
from m8_analytics import outils as m8_outils
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

FICTIF = True  # aucun client réel : des identifiants, des personnes et des montants de test

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_MAINTENANT = "2026-10-09T18:00:00+00:00"
_CLIENT_ID = "c" * 64
_PROPRIETAIRE = "Alice Vendeuse (fictif)"
TYPES_ENTONNOIR = (
    "m2.client_associe", "m2.lead_assigne", "m3.devis_envoye", "m3.devis_accepte", "m3.devis_sans_reponse",
)


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def departements():
    """Manifeste réel ; M8 seul reçoit les événements (les autres ont leurs propres tests)."""
    return {"m08-analytics": charger_departements(_RACINE_DEPARTEMENTS)["m08-analytics"]}


# ---------------------------------------------------------------------------
# Charges au format du catalogue (`src/opsys/evenements/catalogue/*.json`)
# ---------------------------------------------------------------------------
def _client_associe(lead_id="lead-1-fictif", quand="2026-09-29T09:15:00-04:00"):
    return "m2.client_associe", "m02-revenue-crm", f"m2-client-associe-{lead_id}", {
        "lead_id": lead_id, "client_id": _CLIENT_ID, "horodatage_association": quand,
    }


def _lead_assigne(lead_id="lead-1-fictif", quand="2026-09-29T11:00:00-04:00"):
    return "m2.lead_assigne", "m02-revenue-crm", f"m2-lead-assigne-{lead_id}", {
        "lead_id": lead_id, "proprietaire": _PROPRIETAIRE, "horodatage_assignation": quand,
    }


def _lead_reassigne(lead_id="lead-1-fictif", rang=2, quand="2026-09-29T10:00:00-04:00"):
    """Réassignation (PLAN T1.4-m), au format que M2 publie : rang n >= 2 sous sa propre famille d'identifiant."""
    return "m2.lead_assigne", "m02-revenue-crm", f"m2-lead-reassigne-{rang}-{lead_id}", {
        "lead_id": lead_id, "proprietaire": "vendeur-deux-fictif", "horodatage_assignation": quand, "rang": rang,
        "proprietaire_precedent": _PROPRIETAIRE,
    }


def _devis_envoye(devis_id="devis-1-fictif", lead_id="lead-1-fictif", quand="2026-09-29T15:00:00-04:00"):
    return "m3.devis_envoye", "m03-estimation", f"m3-devis-envoye-{devis_id}", {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": quand,
    }


def _devis_accepte(
    devis_id="devis-1-fictif", lead_id="lead-1-fictif", prix="600.00", quand="2026-09-30T10:00:00-04:00"
):
    return "m3.devis_accepte", "m03-estimation", f"m3-devis-accepte-{devis_id}", {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{
            "reference_ligne": f"{devis_id}-L0", "description": "Gouttières 5po (fictif)", "quantite": "40",
            "unite": "pi", "prix_unitaire": "15.00", "prix_ligne": "600.00", "reference_besoin_materiau": None,
        }],
        "cout_total": "480.00", "prix_total": prix, "taux_marge": "0.25", "duree_estimee_minutes": "60",
        "horodatage_acceptation": quand,
    }


def _devis_sans_reponse(devis_id="devis-2-fictif", lead_id="lead-1-fictif", statut="envoye",
                        depuis="2026-09-29T15:30:00-04:00", constat="2026-10-08T08:00:00-04:00"):
    return "m3.devis_sans_reponse", "m03-estimation", f"m3-devis-sans-reponse-{devis_id}", {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "statut": statut,
        "horodatage_devis": depuis, "horodatage_reference": constat, "delai_relance_jours": 7,
    }


def _wct(wct_id="wct-1-fictif", devis_id="devis-1-fictif"):
    return "m4.travaux_termines", "m04-field-ops", wct_id, {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": "lead-1-fictif",
        "technicien_id": "tech-fictif", "horodatage_completion": "2026-10-05T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5}, "duree_reelle_minutes": 120,
        "ecart_signale": False, "revue_id": None, "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M8"], "devis_id": devis_id, "statut": "completed_verified",
    }


def _trajet():
    """Un lead reçu et qualifié, deux devis envoyés dont un accepté (600,00 $) et l'autre sans réponse."""
    return [
        _client_associe(), _lead_assigne(),
        _devis_envoye("devis-1-fictif"), _devis_envoye("devis-2-fictif", quand="2026-09-29T15:30:00-04:00"),
        _devis_accepte("devis-1-fictif"), _devis_sans_reponse("devis-2-fictif"),
    ]


def _publier(evenement):
    type_evenement, producteur, evenement_id, charge = evenement
    evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)


def _livrer(departements, maintenant=_MAINTENANT):
    return evenements.repartir(departements, maintenant=maintenant)


def _faits_entonnoir():
    return list(stockage.maillons("m08-analytics", "faits_entonnoir"))


def _par_metrique():
    par_nom = {o.nom: o for o in m8_outils.outils()}
    reponse = executer_atomique(par_nom["m8_lire_vue_executive"], {})
    assert reponse["ok"] is True, reponse
    return {m["metric_id"]: m for m in reponse["resultat"]["entonnoir"]["mesures"]}


def _recus(consommateur="m08-analytics"):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_RECUS).where(EVENEMENTS_RECUS.c.consommateur == consommateur)
        ).mappings().all()
    return [{**dict(ligne), "resultat": codec.decoder(ligne["resultat"]) if ligne["resultat"] else None}
            for ligne in lignes]


# ---------------------------------------------------------------------------
# Le manifeste et les consommateurs disent la même chose
# ---------------------------------------------------------------------------
def test_le_manifeste_reel_declare_les_cinq_evenements_de_l_entonnoir_et_chacun_a_sa_fonction(departements):
    dep = departements["m08-analytics"]

    assert set(TYPES_ENTONNOIR) <= set(dep.evenements_consomme)
    assert set(m8_outils.consommateurs()) == set(dep.evenements_consomme)  # aucune orpheline, aucune manquante
    assert evenements.verifier_coherence(departements) == []
    assert "m02-revenue-crm" in dep.dependances  # M8 lit M2 : la dépendance est déclarée


def test_les_types_de_l_entonnoir_sont_au_catalogue_et_publies_par_m2_et_m3(departements):
    tous = charger_departements(_RACINE_DEPARTEMENTS)

    for type_evenement in TYPES_ENTONNOIR:
        assert type_evenement in evenements.types_connus()
        producteurs = [d.id for d in tous.values() if type_evenement in d.evenements_publie]
        assert producteurs == ["m02-revenue-crm" if type_evenement.startswith("m2.") else "m03-estimation"]


# ---------------------------------------------------------------------------
# Un événement, un fait ; la vue le mesure
# ---------------------------------------------------------------------------
def test_les_cinq_evenements_donnent_leurs_cinq_faits_et_l_entonnoir_les_mesure(base_durable, departements):
    for evenement in _trajet():
        _publier(evenement)

    total = _livrer(departements)

    assert total == {"livres": 6, "traites": 6, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert sorted(f["type_entree"] for f in _faits_entonnoir()) == [
        "devis_accepte", "devis_envoye", "devis_envoye", "devis_sans_reponse", "lead_qualifie", "lead_recu",
    ]
    assert {r["statut"] for r in _recus()} == {"traite"}
    mesures = _par_metrique()
    assert {m: x["valeur"] for m, x in mesures.items()} == {
        "m8_leads_recus": "1", "m8_leads_qualifies": "1", "m8_devis_envoyes": "2", "m8_devis_acceptes": "1",
        "m8_devis_sans_reponse": "1", "m8_taux_acceptation_pct": "50.00",
        "m8_delai_lead_acceptation_jours": "1.03",  # 24 h 45 min entre l'arrivée du lead et l'acceptation
        "m8_carnet_signe_cad": "600.00",
    }


def test_chaque_consommateur_rend_un_resume_qui_ne_porte_que_l_identifiant_du_fait(base_durable, departements):
    for evenement in _trajet():
        _publier(evenement)
    _livrer(departements)

    resumes = {r["evenement_id"]: r["resultat"] for r in _recus()}

    assert resumes["m2-client-associe-lead-1-fictif"] == {
        "enregistre": True, "deja_enregistre": False, "lead_id": "lead-1-fictif",
    }
    assert resumes["m2-lead-assigne-lead-1-fictif"] == {
        "enregistre": True, "deja_enregistre": False, "lead_id": "lead-1-fictif",
    }
    assert resumes["m3-devis-envoye-devis-1-fictif"] == {
        "enregistre": True, "deja_enregistre": False, "devis_id": "devis-1-fictif",
    }
    assert resumes["m3-devis-sans-reponse-devis-2-fictif"] == {
        "enregistre": True, "deja_enregistre": False, "devis_id": "devis-2-fictif",
    }
    accepte = resumes["m3-devis-accepte-devis-1-fictif"]  # une seule fonction par type : chantier ET entonnoir
    assert accepte["enregistre"] is True and accepte["devis_id"] == "devis-1-fictif"
    assert accepte["entonnoir"] == {"enregistre": True, "deja_enregistre": False}
    texte = json.dumps(list(resumes.values()), ensure_ascii=False)
    assert _CLIENT_ID not in texte and _PROPRIETAIRE not in texte and "600.00" not in texte


# ---------------------------------------------------------------------------
# Idempotence : une relivraison, un rejeu, une republication n'ajoutent rien
# ---------------------------------------------------------------------------
def test_un_rejeu_du_repartiteur_et_une_republication_n_ajoutent_aucun_fait(base_durable, departements):
    for evenement in _trajet():
        _publier(evenement)
    _livrer(departements)
    avant = _faits_entonnoir()

    assert _livrer(departements, "2026-10-09T18:05:00+00:00")["livres"] == 0  # rien de neuf à livrer
    for evenement in _trajet():
        _publier(evenement)  # même identifiant : un no-op de l'outbox
    assert _livrer(departements, "2026-10-09T18:10:00+00:00")["livres"] == 0

    assert _faits_entonnoir() == avant and len(avant) == 6


def test_une_relivraison_directe_du_meme_evenement_dit_deja_enregistre_sans_second_fait(base_durable):
    _, _, _, charge = _client_associe()
    _, _, _, envoi = _devis_envoye()

    with stockage.transaction():
        premier = m8_outils._recevoir_client_associe(dict(charge))
        second = m8_outils._recevoir_client_associe(dict(charge))
        envoi_premier = m8_outils._recevoir_devis_envoye(dict(envoi))
        envoi_second = m8_outils._recevoir_devis_envoye(dict(envoi))

    assert (premier["enregistre"], premier["deja_enregistre"]) == (True, False)
    assert (second["enregistre"], second["deja_enregistre"]) == (False, True)
    assert (envoi_premier["enregistre"], envoi_second["deja_enregistre"]) == (True, True)
    assert [f["type_entree"] for f in _faits_entonnoir()] == ["lead_recu", "devis_envoye"]


def test_un_meme_devis_accepte_deux_fois_ne_compte_qu_une_fois_dans_chaque_registre(base_durable):
    _, _, _, charge = _devis_accepte()

    with stockage.transaction():
        m8_outils._recevoir_devis_accepte(dict(charge))
        second = m8_outils._recevoir_devis_accepte(dict(charge))

    assert second["deja_enregistre"] is True and second["entonnoir"] == {"enregistre": False, "deja_enregistre": True}
    assert [f["type_entree"] for f in _faits_entonnoir()] == ["devis_accepte"]
    assert [f["type_entree"] for f in stockage.maillons("m08-analytics", "faits_chantier")] == ["devis"]


# ---------------------------------------------------------------------------
# L'ordre de livraison n'est pas garanti : la mesure n'en dépend pas
# ---------------------------------------------------------------------------
def _mesures_apres(tmp_path, monkeypatch, nom_base, evenements_a_publier):
    stockage.liberer()
    url = f"sqlite:///{tmp_path / nom_base}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    departements = {"m08-analytics": charger_departements(_RACINE_DEPARTEMENTS)["m08-analytics"]}
    for evenement in evenements_a_publier:
        _publier(evenement)
    assert _livrer(departements)["quarantaines"] == 0
    return {m: (x["statut"], x["valeur"], x.get("entrees")) for m, x in _par_metrique().items()}


def test_les_memes_evenements_dans_l_ordre_inverse_donnent_les_memes_mesures(tmp_path, monkeypatch, base_durable):
    chantier = _wct()
    dans_l_ordre = _mesures_apres(tmp_path, monkeypatch, "ordre.db", [*_trajet(), chantier])
    a_l_envers = _mesures_apres(tmp_path, monkeypatch, "envers.db", [chantier, *reversed(_trajet())])

    assert a_l_envers == dans_l_ordre
    assert dans_l_ordre["m8_carnet_signe_cad"][1] == "0.00"  # le chantier de devis-1 est terminé : il sort du carnet
    assert dans_l_ordre["m8_delai_lead_acceptation_jours"][1] == "1.03"


# ---------------------------------------------------------------------------
# Loi 25 : identifiants, instants et prix arrêté, jamais de donnée de client
# ---------------------------------------------------------------------------
def test_aucun_client_id_proprietaire_cout_ou_ligne_n_entre_au_registre_de_l_entonnoir(base_durable, departements):
    for evenement in _trajet():
        _publier(evenement)
    _livrer(departements)

    texte = json.dumps(_faits_entonnoir(), ensure_ascii=False)

    for confidence in (_CLIENT_ID, _PROPRIETAIRE, "Alice", "480.00", "0.25", "Gouttières", "15.00", "duree_estimee"):
        assert confidence not in texte, confidence
    accepte = next(f for f in _faits_entonnoir() if f["type_entree"] == "devis_accepte")
    assert accepte == {
        "type_entree": "devis_accepte", "devis_id": "devis-1-fictif", "lead_id": "lead-1-fictif",
        "prix_total": "600.00", "horodatage": "2026-09-30T10:00:00-04:00",
    }


def test_le_devis_accepte_alimente_aussi_la_mesure_d_un_chantier_comme_avant(base_durable, departements):
    _publier(_devis_accepte())
    _livrer(departements)

    chantier = list(stockage.maillons("m08-analytics", "faits_chantier"))

    assert [f["type_entree"] for f in chantier] == ["devis"]
    assert chantier[0]["prix_total"] == "600.00" and chantier[0]["cout_total"] == "480.00"  # la mesure de chantier
    assert "cout_total" not in _faits_entonnoir()[0]  # l'entonnoir n'a pas besoin du coût


# ---------------------------------------------------------------------------
# Le carnet suit les chantiers terminés, par le bus
# ---------------------------------------------------------------------------
def test_un_chantier_termine_sort_son_devis_du_carnet(base_durable, departements):
    for evenement in (_client_associe(), _devis_envoye(), _devis_accepte()):
        _publier(evenement)
    _livrer(departements)
    assert _par_metrique()["m8_carnet_signe_cad"]["valeur"] == "600.00"

    _publier(_wct(devis_id="devis-1-fictif"))
    _livrer(departements, "2026-10-09T18:05:00+00:00")

    carnet = _par_metrique()["m8_carnet_signe_cad"]
    assert carnet["valeur"] == "0.00"
    assert carnet["entrees"] == {
        "n_devis_au_carnet": 0, "n_devis_acceptes": 1, "chantiers_termines_sans_devis_relie": 0,
    }


def test_un_chantier_termine_sans_devis_relie_ne_sort_aucun_devis_et_est_compte(base_durable, departements):
    for evenement in (_devis_envoye(), _devis_accepte(), _wct(devis_id=None)):
        _publier(evenement)
    _livrer(departements)

    carnet = _par_metrique()["m8_carnet_signe_cad"]

    assert carnet["valeur"] == "600.00"
    assert carnet["entrees"]["chantiers_termines_sans_devis_relie"] == 1


# ---------------------------------------------------------------------------
# M8 mesure, il ne décide ni n'alerte
# ---------------------------------------------------------------------------
def test_l_entonnoir_ne_publie_aucune_alerte_et_aucun_autre_evenement(base_durable, departements):
    for evenement in _trajet():
        _publier(evenement)
    _livrer(departements)
    _par_metrique()

    with stockage.transaction() as cnx:
        types = {ligne[0] for ligne in cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement)).all()}

    assert types == set(TYPES_ENTONNOIR)  # ceux que M2 et M3 ont publiés ; M8 n'a rien ajouté au bus
    assert evenements.etat()["quarantaine"] == []


def test_les_types_de_fait_de_l_entonnoir_sont_ceux_des_cinq_evenements():
    faits = [
        entonnoir.fait_lead_recu(_client_associe()[3]), entonnoir.fait_lead_qualifie(_lead_assigne()[3]),
        entonnoir.fait_devis_envoye(_devis_envoye()[3]), entonnoir.fait_devis_accepte(_devis_accepte()[3]),
        entonnoir.fait_devis_sans_reponse(_devis_sans_reponse()[3]),
    ]

    assert [f["type_entree"] for f in faits] == [
        entonnoir.TYPE_LEAD_RECU, entonnoir.TYPE_LEAD_QUALIFIE, entonnoir.TYPE_DEVIS_ENVOYE,
        entonnoir.TYPE_DEVIS_ACCEPTE, entonnoir.TYPE_DEVIS_SANS_REPONSE,
    ]


def test_une_reassignation_n_est_jamais_une_qualification_meme_arrivee_la_premiere(base_durable, departements):
    """Lead qualifié avant T1.4-k2, réassigné (rang 2), puis republié (rang 1) : M8 garde l'instant de la
    qualification, jamais celui de la réassignation, et ne compte le lead qu'une fois."""
    _publier(_lead_reassigne())
    _livrer(departements)
    assert [f for f in _faits_entonnoir() if f["type_entree"] == "lead_qualifie"] == []  # rien avant le rang 1

    _publier(_lead_assigne())
    _publier(_lead_reassigne(rang=3, quand="2026-09-30T10:00:00-04:00"))
    total = _livrer(departements)

    assert total["echecs"] == 0 and total["quarantaines"] == 0
    faits = [f for f in _faits_entonnoir() if f["type_entree"] == "lead_qualifie"]
    assert len(faits) == 1 and faits[0]["horodatage"] == "2026-09-29T11:00:00-04:00"  # l'instant du rang 1
    assert _par_metrique()["m8_leads_qualifies"]["valeur"] == "1"

