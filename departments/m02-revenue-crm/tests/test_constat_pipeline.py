"""D2 : M2 publie, pour M8, les comptes agrégés du pipeline (`m2.pipeline_constate`).

Vrais outils, vraie base peuplée de leads fictifs (80 sur seize semaines), vrai bus (outbox). Prouve : les comptes sont
ceux de `m2_analyser_pipeline` ; le taux de conversion et la valeur pondérée sont null quand M2 refuse de conclure
(jamais
un zéro) ; aucun lead, contact, vendeur ni propriétaire ne part ; rejouer le même constat ne publie rien de plus, un
autre instant
ou une donnée changée est un événement de plus ; un vendeur n'a pas de périmètre global donc est refusé. Données
FICTIVES.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from test_previsions_outils import MAINTENANT, _analyser, _peupler, base_peuplee, gros  # noqa: F401
from ventes_aide import ADMIN, VENDEUR_UN

from opsys import stockage
from opsys.outils import Autonomie, Niveau
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
TYPE = "m2.pipeline_constate"
AUTRE_JOUR = "2026-10-16T12:00:00-04:00"


def _constater(m, qui=None, horodatage=MAINTENANT):
    return m.appeler("m2_constater_pipeline", {"horodatage": horodatage}, qui)


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)
            .order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        ).all()
    return [(i, codec.decoder(c)) for i, c in lignes]


def test_agent_seulement_aucun_droit_d_appareil(monde):
    outil = monde.par_nom["m2_constater_pipeline"]
    assert (outil.autonomie, outil.niveau_effectif) == (Autonomie.T1, Niveau.N2) and not outil.roles_appareil


def test_les_comptes_publies_sont_ceux_de_l_analytique_sans_aucun_lead(gros):  # noqa: F811
    m = gros
    a = m.accepte(_analyser(m))
    retour = m.accepte(_constater(m))
    ((identifiant, charge),) = _publies()
    assert identifiant == retour["evenement_id"] == charge["evenement_id"]
    assert charge["date_reference"] == retour["date_reference"] == "2026-10-15"
    assert charge["total"] == a["pipeline"]["total"] == 80 and charge["ouverts"] == a["pipeline"]["ouverts"]
    assert charge["par_statut"] == a["pipeline"]["par_statut"]
    assert charge["convertis_un_jour"] == a["entonnoir"]["convertis_un_jour"]
    assert charge["perdus"] == a["entonnoir"]["perdus"] and charge["resolus"] == a["entonnoir"]["resolus"]
    assert float(charge["taux_conversion_resolus_pct"]) == round(
        float(a["taux_conversion_des_resolus"]["valeur"]) * 100, 2
    )
    assert charge["valeur_ponderee_cad"] is None, "aucune valeur déclarée : null, jamais zéro"
    assert set(charge) == {
        "evenement_id",
        "date_reference",
        "version_donnees",
        "total",
        "ouverts",
        "par_statut",
        "convertis_un_jour",
        "perdus",
        "resolus",
        "taux_conversion_resolus_pct",
        "valeur_ponderee_cad",
        "constate_le",
    }
    texte = json.dumps(charge, ensure_ascii=False)
    for fuite in ("p000", "example.test", "vendeur", "Client", "conv-"):
        assert fuite not in texte


def test_sous_le_seuil_le_taux_et_la_valeur_sont_null(monde):
    m = monde
    _peupler(m, n=12)
    m.accepte(_constater(m))
    ((_, charge),) = _publies()
    assert charge["total"] == 12 and charge["taux_conversion_resolus_pct"] is None
    assert charge["valeur_ponderee_cad"] is None


def test_la_valeur_ponderee_declaree_part_en_montant_cad(gros):  # noqa: F811
    m = gros
    ouverts = [k for k in range(80) if k % 4 == 3 or (k % 3 != 0 and k % 5 != 0)]
    for k in ouverts[:6]:
        m.accepte(
            m.appeler(
                "m2_declarer_valeur_pipeline",
                {"lead_id": f"p{k:03d}", "montant": f"{10000 + 1000 * k}.00", "horodatage": MAINTENANT},
                ADMIN,
            )
        )
    centre = m.accepte(_analyser(m))["valeur_ponderee"]["valeur_ponderee"]["centre"]
    m.accepte(_constater(m))
    ((_, charge),) = _publies()
    assert charge["valeur_ponderee_cad"] == centre


def test_rejouer_le_meme_constat_ne_publie_rien_un_autre_instant_est_un_evenement_de_plus(gros):  # noqa: F811
    m = gros
    premier = m.accepte(_constater(m))
    assert m.accepte(_constater(m))["evenement_id"] == premier["evenement_id"] and len(_publies()) == 1
    plus_tard = m.accepte(_constater(m, horodatage="2026-10-15T18:00:00-04:00"))
    assert plus_tard["version_donnees"] == premier["version_donnees"] and plus_tard["date_reference"] == "2026-10-15"
    assert plus_tard["evenement_id"] != premier["evenement_id"] and len(_publies()) == 2
    lendemain = m.accepte(_constater(m, horodatage=AUTRE_JOUR))
    assert lendemain["date_reference"] == "2026-10-16" and len(_publies()) == 3
    assert {c["constate_le"] for _, c in _publies()} == {MAINTENANT, "2026-10-15T18:00:00-04:00", AUTRE_JOUR}


def test_une_donnee_changee_est_une_version_de_plus_et_un_retour_arriere_reste_distinct(gros):  # noqa: F811
    m = gros
    a1 = m.accepte(_constater(m, horodatage="2026-10-15T10:00:00-04:00"))
    _peupler(m, n=3, prefixe="z")
    b = m.accepte(_constater(m, horodatage="2026-10-15T11:00:00-04:00"))
    assert b["version_donnees"] != a1["version_donnees"]
    # la même version qu'au départ, constatée plus tard, ne se confond pas avec la première publication
    a2 = m.accepte(_constater(m, horodatage="2026-10-15T12:00:00-04:00"))
    assert a2["version_donnees"] == b["version_donnees"] and a2["evenement_id"] != b["evenement_id"]
    assert len(_publies()) == 3


def test_un_vendeur_n_a_pas_de_perimetre_global_et_rien_ne_part(gros):  # noqa: F811
    m = gros
    reponse = _constater(m, VENDEUR_UN)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert _publies() == []


def test_horodatage_illisible_refuse_sans_rien_publier(gros):  # noqa: F811
    m = gros
    reponse = _constater(m, horodatage="hier")
    assert reponse["resultat"]["accepte"] is False if reponse["ok"] else True
    assert _publies() == []
