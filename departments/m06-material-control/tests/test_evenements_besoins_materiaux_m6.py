"""M6 consomme `m3.besoins_materiaux` (PLAN T2.3-e) : le prévu d'une ESTIMATION, avant le devis.

Sur base SQLite migrée (ADR-0009), consommateur appelé directement ET par le répartiteur réel du
bus. Prouve : contrat valide -> prévu provisoire dans le registre EXISTANT des besoins prévus ;
idempotent par (devis, version d'estimation) ; contrat invalide -> `ValueError` puis QUARANTAINE,
sans aucune écriture ; recevoir un besoin ne crée JAMAIS de bon de commande ni de mouvement de
stock ; le devis accepté n'est jamais refusé à cause de l'estimation. Fixtures fictives.
"""

from __future__ import annotations

import datetime as dt

import pytest
from m6_material_control import besoins_prevus
from m6_material_control.outils import consommateurs, outils
from sqlalchemy import func, insert, select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

DEPARTEMENT = "m06-material-control"
TYPE = "m3.besoins_materiaux"
DEVIS = "M3-DEVIS-0123456789abcdef"
HASH_1, HASH_2, HASH_3 = "1" * 64, "2" * 64, "3" * 64
BASE = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _charge(estimation_id=HASH_1, rang=0, devis_id=DEVIS, quantite="13.32"):
    return {
        "devis_id": devis_id,
        "lead_id": "lead-fictif-001",
        "estimation_id": estimation_id,
        "rang_registre": rang,
        "bareme_version": "2026.1",
        "niveau_confiance": 0.9,
        "lignes": [
            {
                "materiau": "Revêtement vinyle (fictif)", "sku": "SKU-FICTIF-VINYLE",
                "quantite_estimee": quantite, "unite": "carton", "facteur_perte": "0.10",
            },
            {"materiau": "Clous (fictif)", "quantite_estimee": "600", "unite": "boite"},
        ],
        "facteurs_perte_absents": ["Clous (fictif)"],
    }


def _recevoir(charge):
    """Ce que fait le répartiteur : dans une transaction ouverte, appelle le consommateur."""
    with stockage.transaction():
        return consommateurs()[TYPE](charge)


def _registre(nom):
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, nom))


def _prevus():
    return _registre("besoins_prevus")


def _nb_evenements(type_evenement=None):
    requete = select(func.count()).select_from(EVENEMENTS_SORTANTS)
    if type_evenement is not None:
        requete = requete.where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
    with stockage.transaction() as cnx:
        return cnx.execute(requete).scalar_one()


def _variances():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m6.variance_chantier")
            .order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)
        ).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


def _recu(evenement_id):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(
            select(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == evenement_id, EVENEMENTS_RECUS.c.consommateur == DEPARTEMENT
            )
        ).mappings().first()
    return dict(ligne) if ligne else None


def _repartir(tours=1, *, pas_s=90):
    """Le répartiteur RÉEL, limité à M6 : un tour par `pas_s` secondes simulées (backoff exponentiel)."""
    departements = {DEPARTEMENT: charger_departements()[DEPARTEMENT]}
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(tours):
        resume = evenements.repartir(departements, maintenant=(BASE + dt.timedelta(seconds=pas_s * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    return total


def _publier(charge, evenement_id):
    with stockage.transaction():
        evenements.publier(TYPE, "m03-estimation", charge, evenement_id=evenement_id)


def _inserer_sans_catalogue(charge, evenement_id):
    """Un producteur défaillant (ou hostile) qui contourne le catalogue : la charge entre au bus sans
    validation de schéma. La seule défense est alors la validation du récepteur."""
    with stockage.transaction() as cnx:
        cnx.execute(insert(EVENEMENTS_SORTANTS).values(
            evenement_id=evenement_id, type_evenement=TYPE, producteur="m03-estimation",
            charge=codec.encoder(dict(charge)), cree_le=BASE.isoformat(),
        ))


# ---------------------------------------------------------------------------------------- nominal
def test_contrat_valide_est_range_comme_prevu_provisoire_dans_le_registre_existant(base_durable):
    resultat = _recevoir(_charge())
    assert resultat == {
        "traite": True, "statut": "enregistre", "devis_id": DEVIS, "estimation_id": HASH_1,
        "lignes_enregistrees": 2, "lignes_sans_sku": ["Clous (fictif)"],
        "facteurs_perte_absents": ["Clous (fictif)"], "prevu_definitif_existant": False,
    }
    prevus = _prevus()
    assert len(prevus) == 1, "le registre des besoins prévus EXISTANT : pas de second registre"
    assert prevus[0]["source"] == "estimation_m3"
    assert prevus[0]["devis_id"] == DEVIS
    assert prevus[0]["chantier_id"] is None
    assert prevus[0]["lignes"] == [
        {"materiau_id": "SKU-FICTIF-VINYLE", "quantite_estimee": 13.32, "unite": "carton"},
        {"materiau_id": "Clous (fictif)", "quantite_estimee": 600.0, "unite": "boite"},
    ]


def test_le_prevu_range_est_celui_que_les_lecteurs_existants_relisent(base_durable):
    _recevoir(_charge())
    with stockage.transaction():
        courant = besoins_prevus.pour_devis(DEVIS, stockage.maillons(DEPARTEMENT, "besoins_prevus"))
    assert courant["lignes"][0]["materiau_id"] == "SKU-FICTIF-VINYLE"


def test_recevoir_un_besoin_ne_cree_jamais_de_bon_de_commande_ni_de_mouvement_de_stock(base_durable):
    _recevoir(_charge())
    assert _registre("bons_commande") == []
    assert _registre("principal") == [], "aucun mouvement de stock, aucune réservation"
    assert _registre("livre_prix") == [] and _registre("fournisseurs") == []
    assert _nb_evenements() == 0, "recevoir n'émet rien : ni variance, ni signal"


def test_un_po_reste_un_brouillon_demande_explicitement_et_exige_un_chantier(base_durable):
    _recevoir(_charge())
    m6 = {o.nom: o for o in outils()}
    reponse = executer_atomique(m6["m6_creer_po_brouillon"], {
        "po_id": "PO-1", "devis_id": DEVIS, "fournisseur_id": "F-1", "horodatage": "2026-09-28T12:00:00+00:00",
    })
    assert reponse["ok"] is True
    assert reponse["resultat"] == {"accepte": False, "verdict": {"code": "REJ-PO-CHANTIER-INCONNU"}}
    assert _registre("bons_commande") == []


# ------------------------------------------------------------------------- idempotence, versions
def test_rejeu_de_la_meme_version_est_un_no_op(base_durable):
    _recevoir(_charge())
    resultat = _recevoir(_charge())
    assert resultat == {"traite": True, "statut": "deja_recu", "devis_id": DEVIS, "estimation_id": HASH_1}
    assert len(_prevus()) == 1


def test_une_version_plus_recente_devient_le_prevu_sans_effacer_la_precedente(base_durable):
    _recevoir(_charge(HASH_1, rang=0, quantite="13.32"))
    resultat = _recevoir(_charge(HASH_2, rang=1, quantite="20"))
    assert resultat["statut"] == "enregistre"
    assert len(_prevus()) == 2
    with stockage.transaction():
        courant = besoins_prevus.pour_devis(DEVIS, stockage.maillons(DEPARTEMENT, "besoins_prevus"))
    assert courant["estimation_id"] == HASH_2
    assert courant["lignes"][0]["quantite_estimee"] == 20.0


def test_une_version_perimee_arrivee_en_retard_n_ecrase_pas_la_plus_recente(base_durable):
    _recevoir(_charge(HASH_2, rang=1, quantite="20"))
    resultat = _recevoir(_charge(HASH_1, rang=0, quantite="13.32"))
    assert resultat == {"traite": True, "statut": "version_perimee", "devis_id": DEVIS, "estimation_id": HASH_1}
    with stockage.transaction():
        courant = besoins_prevus.pour_devis(DEVIS, stockage.maillons(DEPARTEMENT, "besoins_prevus"))
    assert courant["estimation_id"] == HASH_2


# ----------------------------------------------------------- un contrat invalide n'écrit rien
@pytest.mark.parametrize(
    "modification",
    [
        lambda c: c.update(prix_total="12.00"),
        lambda c: c["lignes"][0].update(prix_unitaire="3.00"),
        lambda c: c.update(estimation_id="pas-une-empreinte"),
        lambda c: c.update(niveau_confiance="MULTI_VUES"),
        lambda c: c.update(lignes=[], facteurs_perte_absents=[]),
        lambda c: c["lignes"][1].update(quantite_estimee="0"),
        lambda c: c["lignes"][0].update(facteur_perte="10"),
        lambda c: c.update(facteurs_perte_absents=[]),
        lambda c: c["lignes"].append(dict(c["lignes"][1])),
        lambda c: c.pop("bareme_version"),
    ],
)
def test_contrat_invalide_leve_et_n_ecrit_rien(base_durable, modification):
    charge = _charge()
    modification(charge)
    with pytest.raises(ValueError, match="REJ-BESOINS-MATERIAUX-"):
        _recevoir(charge)
    assert _prevus() == []
    assert _registre("bons_commande") == []
    assert _nb_evenements() == 0


def test_un_contrat_invalide_ne_touche_pas_au_prevu_deja_range(base_durable):
    _recevoir(_charge(HASH_1, rang=0))
    avant = _prevus()
    invalide = _charge(HASH_2, rang=1)
    invalide["lignes"][0]["quantite_estimee"] = "-4"
    with pytest.raises(ValueError):
        _recevoir(invalide)
    assert _prevus() == avant


# ------------------------------------------------------------------- par le répartiteur du bus réel
def test_le_repartiteur_livre_l_evenement_et_le_prevu_apparait(base_durable):
    _publier(_charge(), "m3-besoins-materiaux-test-1")
    assert _repartir()["traites"] == 1
    assert _recu("m3-besoins-materiaux-test-1")["statut"] == "traite"
    assert len(_prevus()) == 1


def test_une_redelivrance_ne_recree_rien(base_durable):
    _publier(_charge(), "m3-besoins-materiaux-test-1")
    _repartir()
    resume = _repartir(2)
    assert resume["livres"] == 0, "un reçu clos n'est plus livré"
    assert len(_prevus()) == 1


def test_le_meme_evenement_republie_sous_le_meme_id_est_un_no_op_du_bus(base_durable):
    _publier(_charge(), "m3-besoins-materiaux-test-1")
    _publier(_charge(), "m3-besoins-materiaux-test-1")
    assert _nb_evenements(TYPE) == 1


def test_la_meme_version_sous_deux_identifiants_d_evenement_reste_un_seul_prevu(base_durable):
    _publier(_charge(), "m3-besoins-materiaux-test-1")
    _publier(_charge(), "m3-besoins-materiaux-test-2")
    assert _repartir()["traites"] == 2
    assert len(_prevus()) == 1, "l'idempotence du prévu est par (devis, version), pas par événement"


def test_contrat_invalide_du_catalogue_puis_quarantaine_apres_les_reessais(base_durable):
    """Passe le schéma du catalogue (« 0 » est un texte décimal) mais pas le sens : M6 le refuse,
    le répartiteur réessaie (backoff) puis le met en quarantaine — visible d'un humain."""
    invalide = _charge()
    invalide["lignes"][1]["quantite_estimee"] = "0"
    _publier(invalide, "m3-besoins-materiaux-invalide")

    premier = _repartir()
    assert premier["echecs"] == 1 and premier["traites"] == 0
    assert _recu("m3-besoins-materiaux-invalide")["statut"] == "echec"

    total = _repartir(6)
    recu = _recu("m3-besoins-materiaux-invalide")
    assert recu["statut"] == "quarantaine", recu
    assert recu["tentatives"] == 5
    assert "REJ-BESOINS-MATERIAUX-QUANTITE-INVALIDE" in recu["derniere_erreur"]
    assert total["quarantaines"] == 1
    assert _prevus() == []
    assert evenements.etat()["quarantaine"][0]["evenement_id"] == "m3-besoins-materiaux-invalide"


def test_contournement_du_catalogue_avec_un_prix_est_refuse_puis_quarantaine(base_durable):
    """Un producteur qui écrit au bus SANS le schéma du catalogue : la validation du récepteur est
    la dernière barrière, et le prix n'entre jamais dans M6."""
    hostile = _charge()
    hostile["lignes"][0]["prix_unitaire"] = "12.00"
    hostile["taux_marge"] = "0.35"
    _inserer_sans_catalogue(hostile, "m3-besoins-materiaux-hostile")
    _repartir(7)
    recu = _recu("m3-besoins-materiaux-hostile")
    assert recu["statut"] == "quarantaine"
    assert "REJ-BESOINS-MATERIAUX-FRONTIERE-VIOLEE" in recu["derniere_erreur"]
    assert _prevus() == []


def test_un_evenement_invalide_ne_bloque_pas_les_valides(base_durable):
    invalide = _charge(HASH_1, rang=0, devis_id="M3-DEVIS-invalide")
    invalide["lignes"][1]["quantite_estimee"] = "0"
    _publier(invalide, "m3-besoins-materiaux-invalide")
    _publier(_charge(HASH_2, rang=1), "m3-besoins-materiaux-valide")
    _repartir(7)
    assert _recu("m3-besoins-materiaux-valide")["statut"] == "traite"
    assert _recu("m3-besoins-materiaux-invalide")["statut"] == "quarantaine"
    assert [maillon["devis_id"] for maillon in _prevus()] == [DEVIS]


# ---------------------------------------------------- l'estimation et le devis accepté cohabitent
def _devis_accepte(chantier_id="C1", quantite="40"):
    return {
        "devis_id": DEVIS, "lead_id": "lead-fictif-001", "chantier_id": chantier_id,
        "lignes": [{
            "reference_ligne": f"{DEVIS}-L0", "description": "Vinyle (fictif)", "quantite": quantite,
            "unite": "carton", "prix_unitaire": "10.00", "prix_ligne": "400.00",
            "reference_besoin_materiau": "SKU-FICTIF-VINYLE",
        }],
        "cout_total": "320.00", "prix_total": "400.00", "taux_marge": "0.25",
        "horodatage_acceptation": "2026-09-28T14:00:00-04:00",
    }


def test_le_devis_accepte_n_est_jamais_refuse_a_cause_de_l_estimation(base_durable):
    _recevoir(_charge())
    with stockage.transaction():
        resultat = consommateurs()["m3.devis_accepte"](_devis_accepte())
    assert resultat["accepte"] is True, resultat
    with stockage.transaction():
        courant = besoins_prevus.pour_devis(DEVIS, stockage.maillons(DEPARTEMENT, "besoins_prevus"))
    assert courant["chantier_id"] == "C1", "le prévu définitif porte le chantier, que l'estimation ignorait"
    assert courant["lignes"] == [{"materiau_id": "SKU-FICTIF-VINYLE", "quantite_estimee": 40.0, "unite": "carton"}]


def test_une_estimation_tardive_apres_le_devis_accepte_ne_remplace_pas_le_prevu_definitif(base_durable):
    with stockage.transaction():
        consommateurs()["m3.devis_accepte"](_devis_accepte())
    resultat = _recevoir(_charge())
    assert resultat["statut"] == "enregistre" and resultat["prevu_definitif_existant"] is True
    with stockage.transaction():
        courant = besoins_prevus.pour_devis(DEVIS, stockage.maillons(DEPARTEMENT, "besoins_prevus"))
    assert courant["chantier_id"] == "C1"
    assert courant["lignes"][0]["quantite_estimee"] == 40.0


# --------------------------------------------- un WCT déjà reçu est réévalué quand le prévu arrive
def _wct(wct_id="wct-1", devis_id=DEVIS):
    return {
        "wct_id": wct_id, "intervention_id": "int-1", "lead_id": "lead-fictif-001", "technicien_id": "t1",
        "horodatage_completion": "2026-09-28T10:00:00-05:00",
        "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5}, "duree_reelle_minutes": 120,
        "ecart_signale": True, "revue_id": None, "hash_maillon": "a" * 16, "consommateurs_cibles": ["M6"],
        "devis_id": devis_id, "statut": "completed_pending_review",
    }


def test_un_wct_deja_recu_est_reevalue_quand_l_estimation_devient_son_prevu(base_durable):
    with stockage.transaction():
        consommateurs()["m4.travaux_termines"](_wct())
    assert [v["statut_variance"] for v in _variances()] == ["prevu_absent"]

    _recevoir(_charge())
    assert [v["statut_variance"] for v in _variances()] == ["prevu_absent", "declaration_absente"]


def test_une_version_deja_recue_ne_reevalue_pas_une_seconde_fois(base_durable):
    with stockage.transaction():
        consommateurs()["m4.travaux_termines"](_wct())
    _recevoir(_charge())
    avant = _nb_evenements("m6.variance_chantier")
    _recevoir(_charge())
    assert _nb_evenements("m6.variance_chantier") == avant


def test_l_estimation_ne_reevalue_pas_un_wct_dont_le_devis_a_deja_un_prevu_definitif(base_durable):
    with stockage.transaction():
        consommateurs()["m3.devis_accepte"](_devis_accepte())
        consommateurs()["m4.travaux_termines"](_wct())
    avant = [v["statut_variance"] for v in _variances()]
    _recevoir(_charge())
    assert [v["statut_variance"] for v in _variances()] == avant, "le prévu n'a pas changé : rien à réévaluer"
