"""Faits de chantier M8 vers M9, sur bus natif et SQLite fictive migrée."""

from copy import deepcopy
from pathlib import Path

import pytest
from m8_analytics.outils import outils as outils_m8
from m8_analytics.registre import RegistreSnapshots as RegistreM8
from m9_strategic_intelligence.etat_consolide import construire_etat_consolide
from m9_strategic_intelligence.outils import outils as outils_m9
from m9_strategic_intelligence.registre import RegistreSnapshots as RegistreM9
from sqlalchemy import select, update

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

_TYPE = "m8.snapshot_chantier"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'snapshots-chantier.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _wct(**changements):
    charge = {
        "wct_id": "wct-snapshot-1",
        "intervention_id": "intervention-snapshot-1",
        "lead_id": "lead-prive",
        "technicien_id": "technicien-prive",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 129,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "empreinte-wct-fictive",
        "consommateurs_cibles": ["M8"],
        "devis_id": None,
        "statut": "completed_verified",
    }
    charge.update(changements)
    return charge


def _departements():
    tous = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    return {nom: tous[nom] for nom in ("m08-analytics", "m09-strategic-intelligence")}


def _snapshots_m9():
    return RegistreM9(maillons=stockage.maillons("m09-strategic-intelligence", "snapshots"))


def _sortants(type_evenement=_TYPE):
    with stockage.transaction() as cnx:
        return [
            dict(ligne)
            for ligne in cnx.execute(
                select(EVENEMENTS_SORTANTS).where(
                    EVENEMENTS_SORTANTS.c.type_evenement == type_evenement,
                )
            ).mappings()
        ]


def _recu(evenement_id, consommateur="m09-strategic-intelligence"):
    with stockage.transaction() as cnx:
        return dict(
            cnx.execute(
                select(EVENEMENTS_RECUS).where(
                    EVENEMENTS_RECUS.c.evenement_id == evenement_id,
                    EVENEMENTS_RECUS.c.consommateur == consommateur,
                )
            )
            .mappings()
            .one()
        )


def _projection(maillon):
    return {
        "evenement_id": "m8-snapshot-chantier-" + maillon["hash_maillon"],
        "source_m8": {"index": maillon["index"], "hash_maillon": maillon["hash_maillon"]},
        "snapshot": {cle: deepcopy(maillon[cle]) for cle in ("module_source", "horodatage", "valeurs")},
    }


def _produire(charge=None):
    charge = charge or _wct()
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="wct-source-1")
    departements = _departements()
    assert evenements.repartir(departements)["echecs"] == 0
    assert evenements.repartir(departements)["echecs"] == 0
    lignes = _sortants()
    assert len(lignes) == 1
    return evenements.charge_publiee(_TYPE, lignes[0]["evenement_id"])


def test_wct_sans_alerte_transmet_son_snapshot_durable_a_m9(base_durable):
    charge = _wct()
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="wct-source-1")
    premier = evenements.repartir(_departements(), maintenant="2026-10-20T00:00:00+00:00")
    assert premier["traites"] == 1 and premier["echecs"] == 0
    m8 = RegistreM8(maillons=stockage.maillons("m08-analytics", "snapshots"))
    assert m8.valider_chaine()[0] is True
    assert len(m8.lire()) == 1
    assert m8.lire()[0]["valeurs"]["m4_duree_reelle_minutes"] == "129"
    # Deuxième sélection native : les publications du consommateur M8 arrivent après
    # la sélection du premier drain. Aucun coût ni durée estimée n'a été inventé.
    second = evenements.repartir(_departements(), maintenant="2026-10-20T00:01:00+00:00")
    assert second["echecs"] == 0
    m9 = RegistreM9(maillons=stockage.maillons("m09-strategic-intelligence", "snapshots"))
    assert len(m9.lire()) == 1, "M9_SNAPSHOT_ABSENT_APRES_WCT_NATIF_M8_SANS_ALERTE"
    assert m9.valider_chaine()[0] is True
    assert m9.lire()[0]["horodatage"] == charge["horodatage_completion"]
    assert m9.lire()[0]["valeurs"]["m4_duree_reelle_minutes"] == "129"
    assert premier["livres"] == 1 and second["traites"] == second["livres"] == 1
    assert _sortants("m8.alerte_proposee") == []
    assert list(stockage.maillons("m09-strategic-intelligence", "alertes_m8")) == []
    assert evenements.repartir(_departements())["livres"] == 0


@pytest.mark.parametrize("type_travaux", [None, "gouttières", ""])
def test_projection_exacte_et_absence_de_donnees_personnelles(base_durable, type_travaux):
    wct = _wct()
    if type_travaux is not None:
        wct["type_travaux"] = type_travaux
    charge = _produire(wct)
    m8 = RegistreM8(maillons=stockage.maillons("m08-analytics", "snapshots")).lire()[0]
    assert charge == _projection(m8)
    valeurs = dict(
        m8["valeurs"],
        m8_snapshot_evenement_id=charge["evenement_id"],
        m8_snapshot_index=str(m8["index"]),
        m8_snapshot_hash_maillon=m8["hash_maillon"],
    )
    assert _snapshots_m9().lire()[0]["valeurs"] == valeurs
    assert all(isinstance(v, str) for v in valeurs.values())
    assert ("m4_type_travaux" in valeurs) is (type_travaux is not None)
    texte = repr(charge) + repr(valeurs)
    for sentinelle in ("lead-prive", "technicien-prive", "45.75", "-73.5", "fix_gps_completion"):
        assert sentinelle not in texte
    assert _recu(charge["evenement_id"])["statut"] == "traite"


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("supplement", "prive"),
        ("source_m8.index", True),
        ("source_m8.index", -1),
        ("source_m8.hash_maillon", "hash-invalide"),
        ("snapshot.module_source", "m05-financecore"),
        ("snapshot.valeurs.technicien_id", "prive"),
        ("snapshot.valeurs.m4_type_travaux", None),
        ("snapshot.valeurs.m4_duree_reelle_minutes", 129),
        ("snapshot.valeurs.m4_duree_reelle_minutes", "129.0"),
    ],
)
def test_catalogue_refuse_charge_non_typee_sans_publication(base_durable, champ, valeur):
    charge = _produire()
    cible = charge
    cles = champ.split(".")
    for cle in cles[:-1]:
        cible = cible[cle]
    cible[cles[-1]] = valeur
    avant = _sortants()
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier(_TYPE, "m08-analytics", charge, evenement_id="invalide")
    assert _sortants() == avant


def test_replay_wct_contradictoire_preserve_premier_maillon_et_outbox(base_durable):
    charge = _produire()
    avant = _sortants()
    m9 = _snapshots_m9().lire()
    evenements.publier(
        "m4.travaux_termines",
        "m04-field-ops",
        _wct(
            duree_reelle_minutes=999,
            type_travaux="autre",
            horodatage_completion="2026-10-01T01:00:00Z",
        ),
        evenement_id="wct-contradictoire",
    )
    assert evenements.repartir(_departements())["echecs"] == 0
    recu = _recu("wct-contradictoire", "m08-analytics")
    assert recu["statut"] == "traite"
    assert codec.decoder(recu["resultat"])["deja_enregistre"] is True
    assert _sortants() == avant  # charge ET première date de publication conservées
    assert evenements.charge_publiee(_TYPE, charge["evenement_id"]) == charge
    assert _snapshots_m9().lire() == m9
    assert evenements.repartir(_departements())["livres"] == 0


def test_deux_wct_contradictoires_avant_drain_copient_le_gagnant_durable(base_durable):
    for ident, duree in (("avant-a", 245), ("avant-b", 999)):
        evenements.publier(
            "m4.travaux_termines",
            "m04-field-ops",
            _wct(
                duree_reelle_minutes=duree,
            ),
            evenement_id=ident,
        )
    assert evenements.repartir(_departements())["traites"] == 2
    assert evenements.repartir(_departements())["traites"] == 1
    m8 = RegistreM8(maillons=stockage.maillons("m08-analytics", "snapshots")).lire()
    assert len(m8) == len(_sortants()) == len(_snapshots_m9().lire()) == 1
    charge = evenements.charge_publiee(_TYPE, _sortants()[0]["evenement_id"])
    assert charge == _projection(m8[0])
    assert (
        _snapshots_m9().lire()[0]["valeurs"]["m4_duree_reelle_minutes"] == m8[0]["valeurs"]["m4_duree_reelle_minutes"]
    )
    assert evenements.etat()["comptes"] == {"traite": 3}


def test_reouverture_sqlite_et_relivraison_najoutent_pas_de_maillon(base_durable):
    charge = _produire()
    avant = _snapshots_m9().lire()
    stockage.liberer()
    # La même URL d'instance reste configurée : vraie réouverture du stockage durable.
    assert (
        evenements.publier(_TYPE, "m08-analytics", charge, evenement_id=charge["evenement_id"])
        == charge["evenement_id"]
    )
    evenements.publier(_TYPE, "m08-analytics", charge, evenement_id="autre-enveloppe")
    assert evenements.repartir(_departements())["traites"] == 1
    recu = _recu("autre-enveloppe")
    assert codec.decoder(recu["resultat"])["deja_recu"] is True
    assert _snapshots_m9().lire() == avant
    assert evenements.repartir(_departements())["livres"] == 0


@pytest.mark.parametrize(
    "cas,code",
    [
        ("id_incoherent", "REJ-SNAPSHOT-CHANTIER-SOURCE"),
        ("charge_modifiee", "REJ-SNAPSHOT-CHANTIER-SOURCE"),
        ("meme_wct_nouvelle_source", "REJ-SNAPSHOT-CHANTIER-CONTRADICTOIRE"),
        ("instant_sans_fuseau", "REJ-SNAPSHOT-CHANTIER"),
    ],
)
def test_source_et_contradiction_refusees_avant_ecriture(base_durable, cas, code):
    charge = deepcopy(_produire())
    avant = _snapshots_m9().lire()
    if cas == "id_incoherent":
        charge["evenement_id"] = "m8-snapshot-chantier-" + "a" * 64
    elif cas == "charge_modifiee":
        charge["snapshot"]["valeurs"]["m4_duree_reelle_minutes"] = "999"
    else:
        charge["source_m8"]["hash_maillon"] = "a" * 64
        charge["evenement_id"] = "m8-snapshot-chantier-" + "a" * 64
        if cas == "instant_sans_fuseau":
            charge["snapshot"]["horodatage"] = "2026-09-28T14:00:00"
            charge["snapshot"]["valeurs"]["m4_wct_id"] = "autre-wct"
        else:
            charge["snapshot"]["valeurs"]["m4_duree_reelle_minutes"] = "999"
    enveloppe = (
        charge["evenement_id"]
        if cas
        in (
            "meme_wct_nouvelle_source",
            "instant_sans_fuseau",
        )
        else "enveloppe-refusee"
    )
    evenements.publier(_TYPE, "m08-analytics", charge, evenement_id=enveloppe)
    assert evenements.repartir(_departements())["echecs"] == 1
    assert code in _recu(enveloppe)["derniere_erreur"]
    assert _snapshots_m9().lire() == avant


def test_conflit_publication_annule_snapshot_et_fait_m8_dans_transaction_native(base_durable):
    wct = _wct()
    premier, _ = RegistreM8().ajouter(
        {
            "module_source": "m04-field-ops",
            "horodatage": wct["horodatage_completion"],
            "valeurs": {
                "m4_wct_id": wct["wct_id"],
                "m4_intervention_id": wct["intervention_id"],
                "m4_duree_reelle_minutes": "129",
            },
        }
    )
    charge = _projection(premier)
    charge["snapshot"]["valeurs"]["m4_duree_reelle_minutes"] = "1"
    evenements.publier(_TYPE, "m08-analytics", charge, evenement_id=charge["evenement_id"])
    avant = _sortants()
    evenements.publier("m4.travaux_termines", "m04-field-ops", wct, evenement_id="wct-conflit")
    m8_seul = {"m08-analytics": _departements()["m08-analytics"]}
    assert evenements.repartir(m8_seul)["echecs"] == 1
    assert "ConflitPublication" in _recu("wct-conflit", "m08-analytics")["derniere_erreur"]
    assert list(stockage.maillons("m08-analytics", "snapshots")) == []
    assert list(stockage.maillons("m08-analytics", "faits_chantier")) == []
    assert _sortants() == avant


def test_chaine_m9_alteree_refuse_meme_une_relivraison_exacte(base_durable):
    charge = _produire()
    with stockage.transaction() as cnx:
        cible = (REGISTRES.c.departement == "m09-strategic-intelligence") & (REGISTRES.c.registre == "snapshots")
        maillon = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(cible)).scalar_one())
        maillon["valeurs"]["m4_duree_reelle_minutes"] = "999"
        cnx.execute(update(REGISTRES).where(cible).values(maillon=codec.encoder(maillon)))
        avant = cnx.execute(select(REGISTRES.c.maillon).where(cible)).scalar_one()
    evenements.publier(_TYPE, "m08-analytics", charge, evenement_id="relivre-chaine-alteree")
    assert evenements.repartir(_departements())["echecs"] == 1
    assert "REJ-SNAPSHOT-CHAINE-INVALIDE" in _recu("relivre-chaine-alteree")["derniere_erreur"]
    with stockage.transaction() as cnx:
        assert cnx.execute(select(REGISTRES.c.maillon).where(cible)).scalars().all() == [avant]


def test_preexistant_nest_pas_rattrape_et_snapshot_generique_reste_compatible(base_durable):
    RegistreM8(maillons=stockage.maillons("m08-analytics", "snapshots")).ajouter(
        {
            "module_source": "m04-field-ops",
            "horodatage": "2026-09-28T14:00:00-04:00",
            "valeurs": {
                "m4_wct_id": "wct-snapshot-1",
                "m4_intervention_id": "intervention-snapshot-1",
                "m4_duree_reelle_minutes": "129",
            },
        }
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    assert evenements.repartir(_departements())["traites"] == 1
    assert evenements.repartir(_departements())["livres"] == 0
    assert _sortants() == [] and _snapshots_m9().lire() == []
    outil = next(o for o in outils_m9() if o.nom == "m9_etat_consolide")
    reponse = executer_atomique(
        outil,
        {
            "snapshot": {
                "module_source": "m10-memoire",
                "horodatage": "2026-09-28T14:00:00Z",
                "valeurs": {},
            }
        },
    )
    assert reponse["ok"] is True
    assert set(construire_etat_consolide(_snapshots_m9())["faits_par_module"]) == {"m10-memoire"}


def test_snapshot_et_alerte_native_coexistent_sans_modifier_leurs_recus(base_durable):
    _produire()
    avant = _snapshots_m9().lire()
    par_nom = {o.nom: o for o in outils_m8()}
    definition = {
        "metric_id": "m4_duree_reelle_minutes",
        "departement_proprietaire": "m04-field-ops",
        "unite": "min",
        "source": "Module M4 — WCT",
        "fraicheur_attendue_jours": 2,
        "regles_qualite": {"plage_min": None, "plage_max": None},
    }
    assert (
        executer_atomique(
            par_nom["m8_enregistrer_definition_metrique"],
            {
                "definition": definition,
            },
        )["ok"]
        is True
    )
    assert (
        executer_atomique(
            par_nom["m8_rapport_metriques"],
            {
                "dictionnaire": {"m04-field-ops": {"m4_duree_reelle_minutes": {}}},
                "snapshot": {
                    "module_source": "m04-field-ops",
                    "horodatage": "2026-01-01T00:00:00Z",
                    "valeurs": {"m4_duree_reelle_minutes": "42"},
                },
                "metric_ids": ["m4_duree_reelle_minutes"],
                "horodatage_reference": "2026-01-01T00:00:00Z",
                "n_minimal": 1,
            },
        )["ok"]
        is True
    )
    assert (
        executer_atomique(
            par_nom["m8_evaluer_qualite_metrique"],
            {
                "metric_id": "m4_duree_reelle_minutes",
                "horodatage_reference": "2026-01-11T00:00:00Z",
            },
        )["ok"]
        is True
    )
    assert evenements.repartir(_departements())["traites"] == 1
    alertes = list(stockage.maillons("m09-strategic-intelligence", "alertes_m8"))
    assert len(alertes) == 1
    assert evenements.repartir(_departements())["livres"] == 0
    assert _snapshots_m9().lire() == avant
    assert list(stockage.maillons("m09-strategic-intelligence", "alertes_m8")) == alertes
    assert all(_recu(ligne["evenement_id"])["statut"] == "traite" for ligne in _sortants("m8.alerte_proposee"))
