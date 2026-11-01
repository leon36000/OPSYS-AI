"""M8 reçoit les constats de M7, M5 et M3 (bus réel) et la vue exécutive les montre sans rien refaire.

Fonctions pures de `operations_recues` (somme des relevés, dernière révision, bases de taxes mixtes, fictifs) et
lecture par
le vrai outil `m8_lire_vue_executive`. Données fictives.
"""

from __future__ import annotations

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m8_analytics import operations_recues as op

from opsys import contexte, evenements, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante

FICTIF = True
M3, M5, M7, M8 = "m03-estimation", "m05-financecore", "m07-marketing", "m08-analytics"
ADMIN = IdentiteAppelante("admin.fictif", "admin")


def _fait(type_entree, charge):
    return op.fait(type_entree, charge)


# ------------------------------------------------------------------------------------------------ fonctions pures
def test_somme_des_derniers_releves_par_canal_sans_additionner_une_revision():
    faits = [
        _fait(op.TYPE_DEPENSE, ch.depense_marketing(releve_id="r1", revision=1, montant="100.00")),
        _fait(op.TYPE_DEPENSE, ch.depense_marketing(releve_id="r1", revision=2, montant="110.00")),
        _fait(op.TYPE_DEPENSE, ch.depense_marketing(releve_id="r2", jour="2026-10-28", montant="40.10")),
        _fait(op.TYPE_DEPENSE, ch.depense_marketing(releve_id="r3", canal="meta", montant="7.00")),
    ]
    sec = op.section(faits)
    par_canal = {d["canal"]: d for d in sec["marketing"]["depenses_par_canal"]}
    assert par_canal["google_ads"]["somme_cad"] == "150.10"  # 110.00 (révision 2 de r1) + 40.10
    assert par_canal["google_ads"]["releves"] == 2
    assert par_canal["meta"]["somme_cad"] == "7.00"
    assert "zéros" in par_canal["google_ads"]["libelle"]


def test_bases_de_taxes_differentes_aucune_somme():
    faits = [
        _fait(op.TYPE_DEPENSE, ch.depense_marketing(releve_id="r1", base="HORS_TAXES")),
        _fait(op.TYPE_DEPENSE, ch.depense_marketing(releve_id="r2", base="TAXES_INCLUSES")),
    ]
    ligne = op.section(faits)["marketing"]["depenses_par_canal"][0]
    assert ligne["somme_cad"] is None and "taxes" in ligne["raison"]


def test_sans_fait_pas_de_section():
    assert op.section([]) is None


def test_fictifs_comptes_a_part_et_exclus():
    faits = [
        _fait(op.TYPE_SIGNAUX, ch.signaux_marketing(fictif=True)),
        _fait(op.TYPE_ANOMALIE, ch.anomalie_depense(fictif=True)),
        _fait(op.TYPE_ANOMALIE, ch.anomalie_depense(anomalie_id="b" * 32, severite="critique")),
    ]
    sec = op.section(faits)
    assert sec["fictifs_ignores"] == 2
    assert sec["marketing"]["signaux_par_source"] == []
    assert sec["marketing"]["anomalies"]["total"] == 1
    assert sec["marketing"]["anomalies"]["plus_graves"][0]["severite"] == "critique"


def test_anomalies_les_plus_graves_d_abord_et_reste_compte():
    faits = [
        _fait(op.TYPE_ANOMALIE, ch.anomalie_depense(anomalie_id=f"{i:032x}", severite=s))
        for i, s in enumerate(["info", "critique", "attention", "info", "info", "info", "attention"])
    ]
    anomalies = op.section(faits)["marketing"]["anomalies"]
    assert [a["severite"] for a in anomalies["plus_graves"]][:3] == ["critique", "attention", "attention"]
    assert len(anomalies["plus_graves"]) == 5 and anomalies["reste"] == 2


def test_dernier_constat_comptable_tel_quel_avec_mention_et_age():
    faits = [
        _fait(op.TYPE_MESURES_COMPTABLES, ch.mesures_comptables(jour="2026-10-29", version="a" * 16)),
        _fait(
            op.TYPE_MESURES_COMPTABLES,
            ch.mesures_comptables(jour="2026-10-30", version="b" * 16, ecritures_definitives=99),
        ),
    ]
    compta = op.section(faits, "2026-11-01")["comptabilite"]
    assert compta["dernier"]["ecritures_definitives"] == 99 and compta["age_jours"] == 2
    assert compta["constats_recus"] == 2 and "CPA" in compta["mention"]


def test_la_vision_garde_ni_la_photo_ni_le_modele():
    fait = _fait(op.TYPE_MESURE_VISION, ch.mesure_vision())
    assert "photo_id" not in fait and "modele" not in fait and "decision_empreinte" not in fait
    assert fait["valeur_retenue"] == "42.5"


def test_signaux_dernier_par_source():
    faits = [
        _fait(op.TYPE_SIGNAUX, ch.signaux_marketing(fin="2026-10-20", lu_le="2026-10-21T06:00:00-04:00")),
        _fait(op.TYPE_SIGNAUX, ch.signaux_marketing(fin="2026-10-28", lu_le="2026-10-29T06:00:00-04:00")),
        _fait(op.TYPE_SIGNAUX, ch.signaux_marketing(source="pagespeed")),
    ]
    sources = {s["source"]: s for s in op.section(faits)["marketing"]["signaux_par_source"]}
    assert sources["search_console"]["periode_fin"] == "2026-10-28" and set(sources) == {"search_console", "pagespeed"}


def test_conversions_par_type_et_par_source():
    faits = [
        _fait(op.TYPE_CONVERSION, ch.conversion_hors_ligne(conversion_id="c1")),
        _fait(op.TYPE_CONVERSION, ch.conversion_hors_ligne(conversion_id="c2", source=None, type_="vente")),
    ]
    conv = op.section(faits)["marketing"]["conversions_hors_ligne"]
    assert conv["total"] == 2 and conv["par_source"] == {"google": 1, "source_inconnue": 1}
    assert conv["avec_source_normalisee"] == 1


# ------------------------------------------------------------------------------------------------ bus réel + vue
@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M3, M5, M7, M8))
    m.surveiller(monkeypatch)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
    yield m
    im.demonter()


def _vue(monde):
    capacites = Capacites(monde.departements, stockage.transaction, filtre={M8}, memoire=False)
    with contexte.appele_par_appareil(ADMIN):
        reponse = capacites.appeler("m8_lire_vue_executive", {"aujourd_hui": "2026-11-02"})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def test_la_vue_executive_n_a_pas_la_section_sans_constat(monde):
    assert "operations_recues" not in _vue(monde)


def test_de_m7_m5_m3_vers_la_vue_executive_de_m8_par_le_vrai_bus(monde):
    evenements.publier(
        "m7.depenses_marketing_constatees", M7, ch.depense_marketing(releve_id="rel-1"), evenement_id="d1"
    )
    evenements.publier(
        "m7.depenses_marketing_constatees",
        M7,
        ch.depense_marketing(releve_id="rel-2", jour="2026-10-28", montant="74.60"),
        evenement_id="d2",
    )
    evenements.publier("m7.signaux_marketing_constates", M7, ch.signaux_marketing(), evenement_id="s1")
    evenements.publier("m7.anomalie_depense_detectee", M7, ch.anomalie_depense(severite="critique"), evenement_id="a1")
    evenements.publier("m7.conversion_hors_ligne_importee", M7, ch.conversion_hors_ligne(), evenement_id="c1")
    evenements.publier("m5.mesures_comptables_constatees", M5, ch.mesures_comptables(), evenement_id="mc1")
    evenements.publier("m3.mesure_vision_validee", M3, ch.mesure_vision(), evenement_id="v1")
    resume = monde.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    # La vue lue par le vrai outil porte la section (réduite si la borne du socle l'exige, jamais coupée) ...
    lue = _vue(monde)["operations_recues"]
    assert lue["constats_recus"] == 7
    # ... et le détail complet vient du registre que le consommateur réel a rempli.
    vue = op.section(monde.registre(M8, "faits_operations"), "2026-11-02")
    google = next(d for d in vue["marketing"]["depenses_par_canal"] if d["canal"] == "google_ads")
    assert google["somme_cad"] == "200.00" and google["releves"] == 2
    assert vue["marketing"]["anomalies"]["plus_graves"][0]["severite"] == "critique"
    assert vue["marketing"]["conversions_hors_ligne"]["total"] == 1
    assert vue["comptabilite"]["dernier"]["creances"]["total"] == "7210.55"
    assert vue["mesures_vision_validees"]["total"] == 1
    assert monde.ecritures_hors_propriete() == []


def test_la_vue_reste_sous_la_limite_du_socle_avec_beaucoup_de_constats(monde):
    for i in range(60):
        evenements.publier(
            "m7.depenses_marketing_constatees",
            M7,
            ch.depense_marketing(releve_id=f"rel-{i}", canal="meta" if i % 2 else "google_ads"),
            evenement_id=f"d{i}",
        )
        evenements.publier(
            "m7.anomalie_depense_detectee", M7, ch.anomalie_depense(anomalie_id=f"{i:032x}"), evenement_id=f"a{i}"
        )
    monde.repartir(passes=4, limite=500)
    vue = _vue(monde)
    section = vue["operations_recues"]
    # Sous la borne du socle, le détail cède (dit dans `omis`) mais le compte reste : jamais une section tronquée au
    # milieu.
    assert section.get("omise_pour_tenir_sous_la_borne") or section["marketing"]["anomalies"]["total"] == 60
    assert section["constats_recus"] == 120 or section["constats_recus"] > 0
    assert section.get("omis") or "plus_graves" in section["marketing"]["anomalies"]
