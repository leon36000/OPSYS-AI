"""PLAN T2.3-e — bout en bout M3 -> M6 par le VRAI bus (DEFINITION-PRODUIT §6, « flux des matériaux ») :
M3 estime, M6 reçoit les besoins, le prévu est disponible pour la déclaration de matériaux, la
variance est évaluée contre lui — sans qu'aucun devis n'ait été accepté, et sans qu'aucun bon de
commande ne naisse tout seul.

Vrais départements (manifestes réels, `charger_departements`), vrais outils (`executer_atomique`),
vrai répartiteur (`evenements.repartir`, limité à M6 : la variance publiée en retour n'a pas besoin
d'être livrée à M3 pour cette preuve), base SQLite migrée. M4 n'est pas rejoué : le WCT est publié
tel que M4 le publie (`m4.travaux_termines`, `evenement_id = wct_id`), comme le fait la suite
propre à M6 (`test_evenements_m6.py`). Données fictives.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from m2_preparation_estimation import marqueur_m2
from sqlalchemy import func, insert, select, update

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

TYPE = "m3.besoins_materiaux"
M6 = "m06-material-control"
SKU = "gouttiere-alu-5po-fictif"
VIS = "Vis inox (fictif)"
CHANTIER = "chantier-fictif-1"
BASE = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.UTC)

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1-fictif",
    "unite": "pi",
    "postes": {
        "renovation_totale": {
            "cout_unitaire_min": 800.0,
            "cout_unitaire_max": 1400.0,
            "materiaux": [
                {"materiau": "Gouttière aluminium 5 po (fictif)", "sku": SKU, "quantite_par_unite": "1",
                 "unite": "pi", "facteur_perte": "0.08"},
                {"materiau": VIS, "quantite_par_unite": "0.25", "unite": "boite"},
            ],
        }
    },
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-t2-3-e.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def deps():
    """Départements RÉELS, comme au démarrage de l'instance."""
    return charger_departements()


def _outils(deps, dep_id):
    return {o.nom: o for o in deps[dep_id].charger_outils()}


def _iso(offset_s: int) -> str:
    return (BASE + dt.timedelta(seconds=offset_s)).isoformat()


def _drainer(deps, *, max_tours: int = 15, pas_s: int = 90) -> dict:
    """Draine le bus jusqu'à quiescence, répartiteur réel limité à M6 — boucle BORNÉE."""
    departements = {M6: deps[M6]}
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(max_tours):
        resume = evenements.repartir(departements, maintenant=_iso(pas_s * (tour + 1)))
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence après {max_tours} tours : {total}")


def _estimer(deps, *, quantite=40, lead_id="lead-fictif-t2-3-e", bareme=None):
    """M3 estime par l'outil RÉEL, après préparation réelle du lead au registre M2 canonique."""
    reponse = executer_atomique(_outils(deps, "m03-estimation")["m3_estimer_projet"], {
        "contrat": {
            "lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "type_travaux": "renovation_totale",
            "ville": "Repentigny", "canal": "telephone",
            "contact": {"nom": "Client Fictif", "telephone": "418-555-0100"}, "urgence_declaree": False,
        },
        "marqueur": marqueur_m2(lead_id, type_travaux="renovation_totale", ville="Repentigny"),
        "photos": [{
            "photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
            "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True},
        }],
        "seuils": SEUILS,
        "bareme": bareme if bareme is not None else BAREME,
        "quantite": quantite,
        "plancher_rentable": 1000,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _recu(evenement_id, consommateur=M6):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(
            select(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == evenement_id, EVENEMENTS_RECUS.c.consommateur == consommateur
            )
        ).mappings().first()
    return dict(ligne) if ligne else None


def _resume_du_recu(evenement_id):
    return json.loads(_recu(evenement_id)["resultat"])


def _registre(nom):
    with stockage.transaction():
        return list(stockage.maillons(M6, nom))


def _publies(type_evenement):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
            .order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)
        ).mappings().all()
    return [(ligne["evenement_id"], codec.decoder(ligne["charge"])) for ligne in lignes]


def _identifiant_besoins(contrat):
    return "m3-besoins-materiaux-" + contrat["devis_id"] + "-" + contrat["estimation_id"][:16]


def _publier_wct(devis_id, wct_id="wct-fictif-t2-3-e"):
    """Ce que M4 fait en complétant une intervention (`m4.travaux_termines`, `evenement_id = wct_id`)."""
    charge = {
        "wct_id": wct_id, "intervention_id": "int-fictif-1", "lead_id": "lead-fictif-t2-3-e",
        "technicien_id": "TECH-fictif", "horodatage_completion": _iso(3600),
        "fix_gps_completion": {"latitude": 45.7392, "longitude": -73.4536}, "duree_reelle_minutes": 150,
        "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 16,
        "consommateurs_cibles": ["M6"], "devis_id": devis_id, "statut": "completed_verified",
    }
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=wct_id)
    return wct_id


def _receptionner(deps, lignes):
    """Préalable de toute déclaration : un coût unitaire résolu depuis une réception antérieure
    (`_dernier_cout_unitaire_connu`, materiel.py). Le prix vit dans M6, jamais dans le contrat de M3."""
    reponse = executer_atomique(_outils(deps, M6)["m6_receptionner_commande"], {
        "bon_demande": {
            "po_id": "PO-fictif-1", "chantier_id": CHANTIER,
            "lignes_demandees": [{"materiau_id": m, "quantite_demandee": q} for m, q, _ in lignes],
            "horodatage": _iso(-7200),
        },
        "reception_po": {
            "po_id": "PO-fictif-1", "chantier_id": CHANTIER,
            "lignes_recues": [{"materiau_id": m, "quantite_recue": q} for m, q, _ in lignes],
            "horodatage": _iso(-3600),
        },
        "catalogue_materiaux": {
            "version": "v1-fictif", "unite_monetaire": "CAD",
            "postes": {m: {"cout_unitaire": cout, "libelle": m} for m, _, cout in lignes},
        },
    })
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def _declarer(deps, wct_id, lignes):
    """Déclaration de fin de chantier (M6.10) : l'appelant ne donne que le `wct_id` ; M6 relit le WCT
    au bus (PLAN T1.4-i) et le prévu à SON registre, jamais à l'appelant."""
    reponse = executer_atomique(_outils(deps, M6)["m6_declarer_materiaux_utilises"], {
        "wct_id": wct_id,
        "formulaire": {
            "wct_id": wct_id, "intervention_id": "int-fictif-1", "chantier_id": CHANTIER,
            "lignes_materiaux": [
                {"type_ligne": "prevu", "materiau_id": materiau_id, "quantite": quantite, "unite": unite,
                 "quantite_estimee": estimee}
                for materiau_id, quantite, unite, estimee in lignes
            ],
        },
    })
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def _variances():
    return [charge for _, charge in _publies("m6.variance_chantier")]


# =============================================================================================
def test_m3_estime_m6_recoit_le_prevu_est_disponible_pour_la_declaration(base_durable, deps):
    # 1. M3 estime : quantités calculées par le code (40 pi x 1 ; 40 x 0.25 = 10 boîtes).
    estimation = _estimer(deps)
    besoins = estimation["besoins_materiaux"]
    assert [(ligne.get("sku", ligne["materiau"]), ligne["quantite_estimee"], ligne["unite"])
            for ligne in besoins["lignes"]] == [(SKU, "40", "pi"), (VIS, "10", "boite")]
    assert besoins["facteurs_perte_absents"] == [VIS], "la perte inconnue est signalée, jamais inventée"

    # 2. Publié sans attendre l'acceptation d'un devis : aucun m3.devis_accepte n'existe.
    evenement_id = _identifiant_besoins(besoins)
    assert _publies(TYPE) == [(evenement_id, besoins)]
    assert _publies("m3.devis_accepte") == []

    # 3. Le bus réel livre à M6, qui range le prévu dans son registre EXISTANT des besoins prévus.
    assert _drainer(deps)["traites"] == 1
    assert _recu(evenement_id)["statut"] == "traite"
    assert _resume_du_recu(evenement_id)["statut"] == "enregistre"
    prevus = _registre("besoins_prevus")
    assert len(prevus) == 1
    assert prevus[0]["devis_id"] == besoins["devis_id"] == estimation["estimation"]["devis_id"]
    assert prevus[0]["source"] == "estimation_m3"
    assert prevus[0]["lignes"] == [
        {"materiau_id": SKU, "quantite_estimee": 40.0, "unite": "pi"},
        {"materiau_id": VIS, "quantite_estimee": 10.0, "unite": "boite"},
    ]
    assert prevus[0]["detail_lignes"][0]["facteur_perte"] == "0.08"

    # 4. Recevoir n'est pas acheter : aucun bon de commande, aucun mouvement de stock.
    assert _registre("bons_commande") == []
    assert _registre("principal") == []
    creation = executer_atomique(_outils(deps, M6)["m6_creer_po_brouillon"], {
        "po_id": "PO-1", "devis_id": besoins["devis_id"], "fournisseur_id": "F-1", "horodatage": _iso(10),
    })
    assert creation["resultat"] == {"accepte": False, "verdict": {"code": "REJ-PO-CHANTIER-INCONNU"}}

    # 5. Le chantier se termine (WCT de M4), le matériel réel est déclaré : le prévu de l'estimation
    #    est celui que M6 compare au réel — variance évaluée, 46 déclarés contre 40 prévus.
    wct_id = _publier_wct(besoins["devis_id"])
    _receptionner(deps, [(SKU, 60.0, 8.0), (VIS, 12.0, 25.0)])
    assert _drainer(deps)["traites"] == 1
    assert [v["statut_variance"] for v in _variances()] == ["declaration_absente"]

    _declarer(deps, wct_id, [(SKU, 46.0, "pi", 40.0), (VIS, 10.0, "boite", 10.0)])
    variances = _variances()
    assert [v["statut_variance"] for v in variances] == ["declaration_absente", "evaluee"]
    evaluee = variances[-1]
    assert evaluee["wct_id"] == wct_id
    assert evaluee["chantier_id"] == CHANTIER, "le prévu provisoire ignore le chantier : la déclaration le fournit"
    assert evaluee["signal_critique"] is False
    assert {ligne["materiau"]: (ligne["quantite_prevue"], ligne["quantite_reelle"]) for ligne in evaluee["lignes"]} == {
        SKU: ("40.0", "46.0"),
        VIS: ("10.0", "10.0"),
    }

    # 6. Toujours aucun PO : la chaîne entière n'en a jamais créé.
    assert _registre("bons_commande") == []


def test_le_rejeu_est_un_no_op_de_bout_en_bout(base_durable, deps):
    besoins = _estimer(deps)["besoins_materiaux"]
    evenement_id = _identifiant_besoins(besoins)
    _drainer(deps)

    # Rejeu du producteur (même version, même evenement_id) : le bus ne crée rien.
    with stockage.transaction():
        evenements.publier(TYPE, "m03-estimation", besoins, evenement_id=evenement_id)
    assert len(_publies(TYPE)) == 1
    assert _drainer(deps)["livres"] == 0

    # Même version sous un autre identifiant d'événement : M6 la reconnaît, n'écrit pas de second prévu.
    with stockage.transaction():
        evenements.publier(TYPE, "m03-estimation", besoins, evenement_id="m3-besoins-materiaux-rejoue")
    assert _drainer(deps)["traites"] == 1
    assert _resume_du_recu("m3-besoins-materiaux-rejoue")["statut"] == "deja_recu"
    assert len(_registre("besoins_prevus")) == 1


def test_une_reestimation_est_une_nouvelle_version_qui_devient_le_prevu(base_durable, deps):
    v1 = _estimer(deps, quantite=40)["besoins_materiaux"]
    _drainer(deps)
    v2 = _estimer(deps, quantite=50)["besoins_materiaux"]
    assert v1["devis_id"] == v2["devis_id"], "même lead, même marqueur : même devis"
    assert v1["estimation_id"] != v2["estimation_id"]
    assert (v1["rang_registre"], v2["rang_registre"]) == (0, 1)
    assert _drainer(deps)["traites"] == 1

    prevus = _registre("besoins_prevus")
    assert len(prevus) == 2, "append-only : la version 1 reste au registre"
    assert prevus[-1]["lignes"][0] == {"materiau_id": SKU, "quantite_estimee": 50.0, "unite": "pi"}

    # La version 1, déjà reçue, rejouée sous un autre identifiant d'événement : reconnue, jamais réécrite.
    with stockage.transaction():
        evenements.publier(TYPE, "m03-estimation", v1, evenement_id="m3-besoins-materiaux-v1-rejouee")
    _drainer(deps)
    assert _resume_du_recu("m3-besoins-materiaux-v1-rejouee")["statut"] == "deja_recu"
    assert len(_registre("besoins_prevus")) == 2

    # Le prévu que la variance lira est la version 2 (50), pas la 1 (40).
    wct_id = _publier_wct(v2["devis_id"])
    _receptionner(deps, [(SKU, 80.0, 8.0), (VIS, 15.0, 25.0)])
    _drainer(deps)
    _declarer(deps, wct_id, [(SKU, 50.0, "pi", 50.0), (VIS, 12.5, "boite", 12.5)])
    evaluee = _variances()[-1]
    assert evaluee["statut_variance"] == "evaluee" and evaluee["signal_critique"] is False
    assert {ligne["materiau"]: ligne["quantite_prevue"] for ligne in evaluee["lignes"]} == {SKU: "50.0", VIS: "12.5"}


def test_une_version_livree_dans_le_desordre_n_ecrase_pas_la_plus_recente(base_durable, deps):
    """La version 1 n'est livrée qu'APRÈS la version 2 (réessai d'un événement resté en échec, par
    exemple) : l'ordre de livraison du bus ne décide pas du prévu, le rang de version le fait."""
    v1 = _estimer(deps, quantite=40)["besoins_materiaux"]
    v2 = _estimer(deps, quantite=50)["besoins_materiaux"]
    # La version 1 est repoussée d'un jour APRÈS la version 2, dont l'heure est celle du bus (horloge réelle) :
    # une date fixe cesserait d'être « après » dès que l'horloge la dépasse.
    with stockage.transaction() as cnx:
        cree_v2 = cnx.execute(select(EVENEMENTS_SORTANTS.c.cree_le)
                              .where(EVENEMENTS_SORTANTS.c.evenement_id == _identifiant_besoins(v2))).scalar_one()
        plus_tard = (dt.datetime.fromisoformat(cree_v2) + dt.timedelta(days=1)).isoformat()
        cnx.execute(update(EVENEMENTS_SORTANTS)
                    .where(EVENEMENTS_SORTANTS.c.evenement_id == _identifiant_besoins(v1))
                    .values(cree_le=plus_tard))

    assert _drainer(deps)["traites"] == 2
    assert _resume_du_recu(_identifiant_besoins(v2))["statut"] == "enregistre"
    assert _resume_du_recu(_identifiant_besoins(v1))["statut"] == "version_perimee"
    prevus = _registre("besoins_prevus")
    assert [maillon["estimation_id"] for maillon in prevus] == [v2["estimation_id"]]
    assert prevus[0]["lignes"][0]["quantite_estimee"] == 50.0


def test_le_devis_accepte_apres_l_estimation_reste_recu_et_devient_le_prevu(base_durable, deps):
    """L'estimation ne prend pas la place du devis accepté : M6 garde le prévu DÉFINITIF (avec le
    chantier), sans le refuser à cause du prévu provisoire déjà rangé."""
    besoins = _estimer(deps)["besoins_materiaux"]
    _drainer(deps)
    devis_id = besoins["devis_id"]
    with stockage.transaction():
        evenements.publier("m3.devis_accepte", "m03-estimation", {
            "devis_id": devis_id, "lead_id": besoins["lead_id"], "chantier_id": CHANTIER,
            "lignes": [{
                "reference_ligne": f"{devis_id}-L0", "description": "Gouttière (fictif)", "quantite": "44",
                "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "440.00", "reference_besoin_materiau": SKU,
            }],
            "cout_total": "352.00", "prix_total": "440.00", "taux_marge": "0.25",
            "horodatage_acceptation": _iso(1800),
        }, evenement_id=f"m3-devis-accepte-{devis_id}")
    assert _drainer(deps)["traites"] == 1
    assert _recu(f"m3-devis-accepte-{devis_id}")["statut"] == "traite"
    definitifs = [m for m in _registre("besoins_prevus") if "source" not in m]
    assert len(definitifs) == 1
    assert definitifs[0]["chantier_id"] == CHANTIER
    assert definitifs[0]["lignes"] == [{"materiau_id": SKU, "quantite_estimee": 44.0, "unite": "pi"}]


def test_un_contrat_invalide_va_en_quarantaine_et_le_prevu_reste_intact(base_durable, deps):
    bon = _estimer(deps)["besoins_materiaux"]
    _drainer(deps)
    avant = _registre("besoins_prevus")

    # Passe le schéma du catalogue, pas le sens : deux lignes du même SKU (agréger inventerait une quantité).
    doublon = json.loads(json.dumps(bon))
    doublon["devis_id"] = "M3-DEVIS-doublon"
    doublon["estimation_id"] = "c" * 64
    doublon["lignes"].append({**doublon["lignes"][0], "materiau": "Autre désignation"})
    with stockage.transaction():
        evenements.publier(TYPE, "m03-estimation", doublon, evenement_id="m3-besoins-materiaux-doublon")

    # Contourne le catalogue avec un prix : la validation du récepteur est la dernière barrière.
    hostile = json.loads(json.dumps(bon))
    hostile["devis_id"] = "M3-DEVIS-hostile"
    hostile["estimation_id"] = "d" * 64
    hostile["lignes"][0]["prix_unitaire"] = "12.00"
    with stockage.transaction() as cnx:
        cnx.execute(insert(EVENEMENTS_SORTANTS).values(
            evenement_id="m3-besoins-materiaux-hostile", type_evenement=TYPE, producteur="m03-estimation",
            charge=codec.encoder(hostile), cree_le=_iso(0),
        ))

    total = _drainer(deps)
    assert total["quarantaines"] == 2 and total["traites"] == 0, total
    assert "REJ-BESOINS-MATERIAUX-DUPLIQUE" in _recu("m3-besoins-materiaux-doublon")["derniere_erreur"]
    assert "REJ-BESOINS-MATERIAUX-FRONTIERE-VIOLEE" in _recu("m3-besoins-materiaux-hostile")["derniere_erreur"]
    assert {ligne["evenement_id"] for ligne in evenements.etat()["quarantaine"]} == {
        "m3-besoins-materiaux-doublon", "m3-besoins-materiaux-hostile",
    }
    assert _registre("besoins_prevus") == avant
    assert _registre("bons_commande") == []


def test_estimation_bloquee_ou_sans_materiaux_ne_donne_rien_a_recevoir(base_durable, deps):
    sans_materiaux = json.loads(json.dumps(BAREME))
    del sans_materiaux["postes"]["renovation_totale"]["materiaux"]
    assert _estimer(deps, bareme=sans_materiaux)["besoins_materiaux"] is None
    assert _publies(TYPE) == []
    assert _drainer(deps)["livres"] == 0
    assert _registre("besoins_prevus") == []


def test_le_bus_declare_le_flux_de_bout_en_bout_sans_incoherence(deps):
    assert TYPE in deps["m03-estimation"].evenements_publie
    assert TYPE in deps[M6].evenements_consomme
    assert evenements.verifier_coherence(deps) == []


def test_aucun_evenement_de_besoins_n_est_livre_a_un_departement_qui_ne_l_a_pas_declare(base_durable, deps):
    _estimer(deps)
    consommateurs_du_type = {dep.id for dep in deps.values() if TYPE in dep.evenements_consomme}
    assert consommateurs_du_type == {M6}
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(EVENEMENTS_RECUS)).scalar_one() == 0
