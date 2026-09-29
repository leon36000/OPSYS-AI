"""La mesure par contenu par le bus d'événements réel (PLAN T4.17-e) : M8 consomme `m7.contenu_exporte` et
`m1.lead_qualifie`, range des faits sans renseignement personnel, et `m8_lire_mesures_contenus` les lit.

Bout en bout, sans doublure : `opsys.evenements.repartir`, le manifeste réel de M8 (seul abonné) et une base SQLite
temporaire migrée. Les charges sont des événements synthétiques et fictifs, validés par le catalogue à la publication.
Ce fichier prouve ce que les consommateurs font du bus (idempotence, ordre, ce qui est gardé), qui peut lire et que la
lecture n'écrit rien ; l'attribution fine est dans `test_contenus.py`, le trajet par les VRAIS producteurs (M7, M1) dans
`tests/test_boucle_de_mesure_par_contenu.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m8_analytics import contenus
from m8_analytics import outils as m8_outils
from sqlalchemy import func, select

from opsys import contexte, evenements, identite, stockage
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True  # aucun client réel : des identifiants, des personnes et des clés de test

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_MAINTENANT = "2026-10-09T18:00:00+00:00"
CLE_A = "facebook-0123456789abcdef"
CLE_B = "instagram-fedcba9876543210"
_ADMIN = IdentiteAppelante("admin.fictif", "admin")
CONFIDENCES = ("Client Fictif", "418-555-0100", "c@exemple-fictif.test", "Repentigny", "gouttieres", "conv-L")


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-1234", ["seller"])
    yield url
    stockage.liberer()


@pytest.fixture
def departements():
    """Manifeste réel ; M8 seul reçoit les événements (les autres ont leurs propres tests)."""
    return {"m08-analytics": charger_departements(_RACINE_DEPARTEMENTS)["m08-analytics"]}


# ---------------------------------------------------------------------------
# Charges au format du catalogue (`src/opsys/evenements/catalogue/*.json`)
# ---------------------------------------------------------------------------
def _contenu_exporte(contenu_id="contenu-1", cle=CLE_A, canal="facebook", lien=True, wct_id="wct-1-fictif",
                     quand="2026-09-29T20:00:00-04:00", evenement_id=None):
    return "m7.contenu_exporte", "m07-marketing", evenement_id or f"m7-contenu-exporte-{contenu_id}", {
        "contenu_id": contenu_id, "wct_id": wct_id, "canal": canal, "utm_content": cle, "lien_de_suivi": lien,
        "exporte_le": quand,
    }


def _lead_qualifie(
    lead_id="lead-1", cle=None, quand="2026-09-30T10:00:00-04:00", utm_en_plus=None, evenement_id=None,
):
    """Le lead tel que M1 le publie (LeadQualifie v2), contact et ville compris : M8 n'en doit rien garder."""
    lead = {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "service": "gouttieres",
        "ville": "Repentigny", "urgence_declaree": False, "canal": "formulaire",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100", "courriel": "c@exemple-fictif.test"},
    }
    utm = dict(utm_en_plus or {})
    if cle is not None:
        utm["utm_content"] = cle
    if utm:
        lead["utm"] = utm
    return "m1.lead_qualifie", "m01-front-office", evenement_id or f"m1-lead-qualifie-{lead_id}", {
        "lead": lead, "horodatage": quand, "signal_id": f"formulaire:{lead_id}",
    }


def _devis_envoye(devis_id, lead_id, quand="2026-10-01T09:00:00-04:00"):
    return "m3.devis_envoye", "m03-estimation", f"m3-devis-envoye-{devis_id}", {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": quand,
    }


def _devis_accepte(devis_id, lead_id, quand="2026-10-02T09:00:00-04:00"):
    return "m3.devis_accepte", "m03-estimation", f"m3-devis-accepte-{devis_id}", {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{
            "reference_ligne": f"{devis_id}-L0", "description": "Gouttières 5po (fictif)", "quantite": "40",
            "unite": "pi", "prix_unitaire": "15.00", "prix_ligne": "600.00", "reference_besoin_materiau": None,
        }],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25", "horodatage_acceptation": quand,
    }


def _publier(evenement):
    type_evenement, producteur, evenement_id, charge = evenement
    evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)


def _livrer(departements, maintenant=_MAINTENANT):
    return evenements.repartir(departements, maintenant=maintenant)


def _faits_contenus():
    with stockage.transaction():
        return list(stockage.maillons("m08-analytics", "faits_contenus"))


def _recu(evenement_id):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.evenement_id == evenement_id, EVENEMENTS_RECUS.c.consommateur == "m08-analytics",
        )).mappings().first()
    return None if ligne is None else dict(ligne)


def _outil():
    return {o.nom: o for o in m8_outils.outils()}["m8_lire_mesures_contenus"]  # les registres durables


def _lire(appelante=None, **arguments):
    outil = _outil()
    if appelante is None:
        return executer_atomique(outil, arguments)
    with contexte.appele_par_appareil(appelante):
        return executer_atomique(outil, arguments)


def _vue(appelante=_ADMIN, **arguments):
    reponse = _lire(appelante, **arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _mesures(vue):
    return {ligne["metric_id"]: ligne for ligne in vue["metriques"]}


def _ecritures():
    with stockage.transaction() as cnx:
        return (
            cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one(),
            cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one(),
            cnx.execute(select(func.count()).select_from(EVENEMENTS_RECUS)).scalar_one(),
        )


# ---------------------------------------------------------------------------
# Ce que M8 garde du bus
# ---------------------------------------------------------------------------
def test_m8_recoit_un_contenu_et_un_lead_et_ne_range_que_des_identifiants_des_instants_et_la_cle(
    base_durable, departements,
):
    _publier(_contenu_exporte())
    _publier(_lead_qualifie("lead-1", CLE_A, utm_en_plus={"utm_source": "facebook", "utm_medium": "social"}))

    resume = _livrer(departements)

    assert resume["traites"] == 2 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert _faits_contenus() == [
        {"type_entree": "contenu_exporte", "contenu_id": "contenu-1", "wct_id": "wct-1-fictif", "canal": "facebook",
         "utm_content": CLE_A, "lien_de_suivi": True, "horodatage": "2026-09-29T20:00:00-04:00"},
        {"type_entree": "lead_m1", "lead_id": "lead-1", "utm_content": CLE_A,
         "horodatage": "2026-09-30T10:00:00-04:00"},
    ]
    assert _recu("m7-contenu-exporte-contenu-1")["statut"] == "traite"
    assert _recu("m1-lead-qualifie-lead-1")["statut"] == "traite"


def test_aucun_renseignement_personnel_ne_reste_ni_dans_les_faits_ni_dans_le_recu_du_bus(base_durable, departements):
    _publier(_contenu_exporte())
    _publier(_lead_qualifie("lead-1", CLE_A))
    _publier(_lead_qualifie("lead-2"))
    _livrer(departements)

    with stockage.transaction() as cnx:
        registres = [ligne.maillon for ligne in cnx.execute(
            select(REGISTRES.c.maillon).where(REGISTRES.c.departement == "m08-analytics")).all()]
        recus = [ligne.resultat for ligne in cnx.execute(select(EVENEMENTS_RECUS.c.resultat)).all()]
    lu = json.dumps(registres, ensure_ascii=False) + json.dumps(recus, ensure_ascii=False)

    assert len(registres) == 3 and len(recus) == 3
    assert not [confidence for confidence in CONFIDENCES if confidence in lu], lu
    assert codec.decoder(_recu("m1-lead-qualifie-lead-1")["resultat"]) == {
        "enregistre": True, "deja_enregistre": False, "lead_id": "lead-1", "avec_utm_content": True,
    }
    assert codec.decoder(_recu("m1-lead-qualifie-lead-2")["resultat"])["avec_utm_content"] is False


def test_un_lead_sans_utm_content_est_range_avec_une_cle_nulle_pas_ignore(base_durable, departements):
    _publier(_lead_qualifie("lead-1", None, utm_en_plus={"utm_source": "facebook"}))
    _publier(_lead_qualifie("lead-2"))

    _livrer(departements)

    assert [(f["lead_id"], f["utm_content"]) for f in _faits_contenus()] == [("lead-1", None), ("lead-2", None)]


def test_une_relivraison_sous_un_autre_identifiant_n_ajoute_aucun_second_fait(base_durable, departements):
    _publier(_contenu_exporte())
    _publier(_lead_qualifie("lead-1", CLE_A))
    _publier(_contenu_exporte(evenement_id="m7-copie-du-meme-contenu"))
    _publier(_lead_qualifie("lead-1", CLE_A, evenement_id="m1-copie-du-meme-lead"))

    resume = _livrer(departements)

    assert resume["traites"] == 4 and len(_faits_contenus()) == 2
    doubles = [_recu("m7-copie-du-meme-contenu"), _recu("m1-copie-du-meme-lead")]
    assert [codec.decoder(recu["resultat"])["deja_enregistre"] for recu in doubles] == [True, True]


def test_rejouer_le_repartiteur_ne_change_rien(base_durable, departements):
    _publier(_contenu_exporte())
    _publier(_lead_qualifie("lead-1", CLE_A))
    _livrer(departements)
    avant = (_faits_contenus(), _vue())

    encore = _livrer(departements, maintenant="2026-10-10T18:00:00+00:00")

    assert encore["livres"] == 0
    assert (_faits_contenus(), _vue()) == avant


def test_le_lead_avant_le_contenu_ou_le_contenu_avant_le_lead_donne_la_meme_lecture(
    base_durable, tmp_path, monkeypatch, departements,
):
    """L'ordre de livraison du bus n'est pas garanti : la jointure se fait à la lecture, jamais à l'arrivée."""
    lectures = []
    for ordre, (premier, second) in enumerate(((_contenu_exporte(), _lead_qualifie("lead-1", CLE_A)),
                                              (_lead_qualifie("lead-1", CLE_A), _contenu_exporte()))):
        url = f"sqlite:///{tmp_path / f'ordre-{ordre}.db'}"
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.liberer()
        stockage.migrer(url)
        _publier(premier)
        _livrer(departements, maintenant="2026-10-09T18:00:00+00:00")
        _publier(second)
        _livrer(departements, maintenant="2026-10-09T19:00:00+00:00")
        lectures.append(_vue(None))
    assert lectures[0] == lectures[1]
    assert _mesures(lectures[0])["m8_leads_par_contenu"]["valeur"] == "1"


# ---------------------------------------------------------------------------
# La lecture
# ---------------------------------------------------------------------------
def test_l_admin_lit_les_leads_et_les_devis_par_contenu_apres_livraison(base_durable, departements):
    for evenement in (
        _contenu_exporte("contenu-1", CLE_A), _contenu_exporte("contenu-2", CLE_B, canal="instagram"),
        _lead_qualifie("lead-1", CLE_A), _lead_qualifie("lead-2", CLE_A), _lead_qualifie("lead-3", CLE_B),
        _lead_qualifie("lead-4"),
        _devis_envoye("devis-1", "lead-1"), _devis_envoye("devis-2", "lead-3"), _devis_accepte("devis-1", "lead-1"),
    ):
        _publier(evenement)
    assert _livrer(departements)["traites"] == 9

    vue = _vue()

    mesures = _mesures(vue)
    assert {m: ligne["valeur"] for m, ligne in mesures.items()} == {
        "m8_contenus_exportes": "2", "m8_leads_par_contenu": "3", "m8_devis_envoyes_par_contenu": "2",
        "m8_devis_acceptes_par_contenu": "1", "m8_impressions_par_contenu": None, "m8_clics_par_contenu": None,
    }
    assert mesures["m8_leads_par_contenu"]["entrees"]["n_leads_sans_utm_content"] == 1
    lignes = {ligne["utm_content"]: ligne for ligne in vue["contenus"]}
    assert (lignes[CLE_A]["leads"], lignes[CLE_A]["devis_envoyes"], lignes[CLE_A]["devis_acceptes"]) == (2, 1, 1)
    assert (lignes[CLE_B]["leads"], lignes[CLE_B]["devis_envoyes"], lignes[CLE_B]["devis_acceptes"]) == (1, 1, 0)
    assert [(s["evenement"], s["n"]) for s in vue["sources"]] == [
        ("m7.contenu_exporte", 2), ("m1.lead_qualifie", 4), ("m3.devis_envoye", 2), ("m3.devis_accepte", 1),
    ]
    assert vue["manques"] == [{
        "champ": "source des impressions et des clics",
        "source": "aucune (connecteur à décider : statistiques des plateformes, Matomo)",
        "raison": "ni le bus ni un connecteur ne fournit les impressions ni les clics d'un contenu",
    }]


def test_sans_aucun_fait_recu_la_lecture_est_entierement_non_calculable(base_durable):
    vue = _vue()

    assert all(m["statut"] == "non_calculable" and m["valeur"] is None for m in vue["metriques"])
    assert vue["contenus"] == [] and vue["affichage"]["n_contenus"] == 0
    assert {m["champ"] for m in vue["manques"]} == {
        "m7.contenu_exporte", "m1.lead_qualifie", "m3.devis_envoye", "m3.devis_accepte",
        "source des impressions et des clics",
    }


def test_la_lecture_n_ecrit_rien_et_ne_publie_rien(base_durable, departements):
    _publier(_contenu_exporte())
    _publier(_lead_qualifie("lead-1", CLE_A))
    _livrer(departements)
    avant = _ecritures()

    premiere, seconde = _vue(), _vue()

    assert _ecritures() == avant and premiere == seconde


def test_la_reponse_reste_sous_la_limite_du_socle_et_se_lit_page_par_page(base_durable, departements):
    for i in range(60):
        quand = f"2026-09-{1 + i % 28:02d}T10:00:00-04:00"
        _publier(_contenu_exporte(f"contenu-{i:02d}", f"facebook-{i:016x}", quand=quand))
    for i in range(0, 60, 3):
        _publier(_lead_qualifie(f"lead-{i:02d}", f"facebook-{i:016x}"))
    assert _livrer(departements)["echecs"] == 0

    pages, depart = [], 0
    while depart is not None:
        reponse = _lire(_ADMIN, depart=depart)
        assert reponse["ok"] is True and len(json.dumps(reponse, ensure_ascii=False)) < m8_outils.BUDGET_SORTIE + 100
        pages.append(reponse["resultat"])
        depart = reponse["resultat"]["affichage"]["prochain_depart"]

    assert len(pages) > 1
    assert sorted(ligne["utm_content"] for page in pages for ligne in page["contenus"]) == sorted(
        f"facebook-{i:016x}" for i in range(60)
    )
    assert _lire(_ADMIN, depart=61)["erreur"] == "refus_metier"  # au-delà de la fin : un refus, jamais une page vide


def test_l_outil_est_t0_reserve_au_role_admin_et_ne_prend_que_depart():
    outil = _outil()

    assert outil.autonomie == Autonomie.T0 and not outil.frontiere_humaine
    assert outil.roles_appareil == frozenset({"admin"})  # ni employee, ni seller
    assert set(outil.parametres["properties"]) == {"depart"} and outil.parametres["additionalProperties"] is False
    assert "required" not in outil.parametres and len(outil.description) <= 1024
    for argument in ({"role": "admin"}, {"limite": 5}, {"wct_id": "wct-1"}, {"utm_content": CLE_A}):
        reponse = executer_atomique(outil, argument)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", argument


@pytest.mark.parametrize("appelante", [
    IdentiteAppelante("employe.fictif", "employee"),
    IdentiteAppelante("vendeur.fictif", "seller"),
    IdentiteAppelante("employe.fictif", "admin"),   # un jeton qui prétend un rôle que la personne n'a pas
    IdentiteAppelante("inconnu.fictif", "admin"),
])
def test_tout_autre_role_d_appareil_est_refuse_dans_le_code_et_ne_voit_rien(base_durable, departements, appelante):
    _publier(_contenu_exporte())
    _publier(_lead_qualifie("lead-1", CLE_A))
    _livrer(departements)

    reponse = _lire(appelante)

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE") and "resultat" not in reponse
    assert CLE_A not in json.dumps(reponse, ensure_ascii=False)


def test_sans_identite_d_appareil_la_voie_des_agents_reste_ouverte(base_durable):
    assert _vue(None)["vue"] == "contenus"


# ---------------------------------------------------------------------------
# Les manifestes : ce que M8 consomme est déclaré, dépendance comprise
# ---------------------------------------------------------------------------
def test_le_manifeste_declare_les_deux_types_et_la_dependance_et_les_consommateurs_suivent():
    m8 = charger_departements(_RACINE_DEPARTEMENTS)["m08-analytics"]

    assert {"m7.contenu_exporte", "m1.lead_qualifie"} <= set(m8.evenements_consomme)
    assert set(m8_outils.consommateurs()) == set(m8.evenements_consomme)
    assert "m01-front-office" in m8.dependances and "m07-marketing" in m8.dependances
    assert {"m7.contenu_exporte", "m1.lead_qualifie"} <= evenements.types_connus()
    assert evenements.verifier_coherence(charger_departements(_RACINE_DEPARTEMENTS)) == []


def test_les_faits_de_contenu_ne_se_melangent_pas_aux_faits_de_l_entonnoir(base_durable, departements):
    _publier(_contenu_exporte())
    _publier(_lead_qualifie("lead-1", CLE_A))
    _livrer(departements)

    with stockage.transaction():
        assert list(stockage.maillons("m08-analytics", "faits_entonnoir")) == []
    assert {fait["type_entree"] for fait in _faits_contenus()} == {contenus.TYPE_CONTENU_EXPORTE, contenus.TYPE_LEAD_M1}
