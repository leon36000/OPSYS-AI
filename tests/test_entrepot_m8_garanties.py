"""Entrepôt de M8 alimenté par les autres départements : les cinq garanties de l'interconnexion, SOURCE PAR SOURCE.

Même patron que `test_interconnexion_consommateurs.py` (vrai bus, `consommateurs()` réels, base SQLite migrée),
appliqué à chaque événement qui nourrit une mesure du catalogue de M8 : chantier terminé (M4), devis accepté (M3),
rentabilité (M5), cash libre (M5), mesures comptables (M5), dépenses, signaux, anomalies et conversions (M7),
réception (M6), demande qualifiée (M1), lead reçu (M2).

1. livré et rangé chez M8 seulement (le reçu du bus passe à `traite`, aucune écriture dans le registre d'un autre) ;
2. idempotent par clé de CONTENU : le même constat sous un autre `evenement_id` n'ajoute rien, ne met rien en
quarantaine ;
3. tolérant à la panne de M8 : `echec` avec recul, jamais perdu, relivraison unique ;
4. charge hors catalogue (champ personnel de trop) refusée à la publication, rien d'écrit ;
5. rien de personnel ne traverse : ni le reçu du bus, ni le fait rangé, ni la ligne de l'entrepôt ne portent le nom, le
   courriel, le téléphone, le technicien ou le fournisseur que la charge pouvait porter.

Données fictives.
"""

from __future__ import annotations

import json

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m8_analytics import catalogue_mesures, entrepot

from opsys import evenements, stockage
from opsys.capacites import Capacites
from opsys.evenements import ChargeInvalide

FICTIF = True
M1, M2, M3, M4, M5, M6, M7, M8, M9, M10 = (
    "m01-front-office",
    "m02-revenue-crm",
    "m03-estimation",
    "m04-field-ops",
    "m05-financecore",
    "m06-material-control",
    "m07-marketing",
    "m08-analytics",
    "m09-strategic-intelligence",
    "m10-memoire",
)
INSTANT = "2026-10-30T20:00:00-04:00"
# Ce que les charges portent de personnel (ou d'identifiant d'une personne ou d'un fournisseur) et que M8 ne doit pas
# garder.
PERSONNEL = (
    "Jeanne",
    "jeanne.fictive",
    "example.test",
    "514-555",
    "tech-fictif",
    "fournisseur-fictif",
    "chantier-fictif",
)

# (nom, producteur, type, fabrique(v), registre de M8 qui reçoit le fait)
CAS = [
    (
        "chantier",
        M4,
        "m4.travaux_termines",
        lambda v: ch.travaux_termines(f"wct-v{v}", f"devis-v{v}"),
        "faits_chantier",
    ),
    ("devis", M3, "m3.devis_accepte", lambda v: ch.devis_accepte(f"devis-v{v}"), "faits_chantier"),
    (
        "rentabilite",
        M5,
        "m5.rentabilite_chantier",
        lambda v: ch.rentabilite(f"wct-v{v}", f"devis-v{v}"),
        "faits_chantier",
    ),
    ("cash-libre", M5, "m5.cash_libre_constate", lambda v: ch.cash_libre(v, f"2026-10-2{v}"), "faits_cash_libre"),
    (
        "mesures-comptables",
        M5,
        "m5.mesures_comptables_constatees",
        lambda v: ch.mesures_comptables(version=f"{v:016x}"),
        "faits_operations",
    ),
    (
        "depenses",
        M7,
        "m7.depenses_marketing_constatees",
        lambda v: ch.depense_marketing(releve_id=f"releve-{v}"),
        "faits_operations",
    ),
    (
        "signaux",
        M7,
        "m7.signaux_marketing_constates",
        lambda v: ch.signaux_marketing(fin=f"2026-10-2{v}", lu_le=f"2026-10-2{v}T06:00:00-04:00"),
        "faits_operations",
    ),
    (
        "anomalie",
        M7,
        "m7.anomalie_depense_detectee",
        lambda v: ch.anomalie_depense(anomalie_id=f"{v:032x}"),
        "faits_operations",
    ),
    (
        "conversion",
        M7,
        "m7.conversion_hors_ligne_importee",
        lambda v: ch.conversion_hors_ligne(conversion_id=f"conv-{v}"),
        "faits_operations",
    ),
    ("reception", M6, "m6.reception_enregistree", lambda v: ch.reception_m6(f"po-v{v}", rang=v), "faits_operations"),
    ("demande-m1", M1, "m1.lead_qualifie", lambda v: ch.lead_qualifie_m1(f"lead-v{v}"), "faits_contenus"),
    ("lead-m2", M2, "m2.client_associe", lambda v: ch.client_associe(lead_id=f"lead-v{v}"), "faits_entonnoir"),
]
IDS = [c[0] for c in CAS]


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M8,))
    m.surveiller(monkeypatch)
    yield m
    im.demonter()


def _publier(producteur, type_evenement, charge, evenement_id):
    return evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)


def _recu(monde, type_evenement, evenement_id):
    ids = {e["evenement_id"] for e in monde.sortants(type_evenement)}
    return {r["evenement_id"]: r for r in monde.recus(consommateur=M8) if r["evenement_id"] in ids}[evenement_id]


@pytest.mark.parametrize(("nom", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_garantie_1_livre_et_range_chez_m8_seulement(monde, nom, prod, type_, fabrique, registre):
    avant = monde.taille(M8, registre)
    _publier(prod, type_, fabrique(1), f"{nom}-1")
    monde.repartir(departements=(M8,))
    recu = _recu(monde, type_, f"{nom}-1")
    assert recu["statut"] == "traite" and recu["tentatives"] == 1, recu
    assert monde.taille(M8, registre) == avant + 1
    assert monde.quarantaines() == [] and monde.ecritures_hors_propriete() == []
    assert any(e["consommateur"] == M8 and e["registre"] == registre for e in monde.ecritures)


@pytest.mark.parametrize(("nom", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_garantie_2_idempotent_par_cle_de_contenu_sous_un_autre_identifiant(
    monde, nom, prod, type_, fabrique, registre
):
    _publier(prod, type_, fabrique(1), f"{nom}-a")
    monde.repartir(departements=(M8,))
    apres = monde.taille(M8, registre)
    _publier(prod, type_, fabrique(1), f"{nom}-b")  # même constat, autre enveloppe
    resume = monde.repartir(departements=(M8,))
    assert _recu(monde, type_, f"{nom}-b")["statut"] == "traite"
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    assert monde.taille(M8, registre) == apres
    monde.repartir(departements=(M8,))  # rejouer le répartiteur n'ajoute rien non plus
    assert monde.taille(M8, registre) == apres and monde.quarantaines() == []


@pytest.mark.parametrize(("nom", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_garantie_3_panne_de_m8_echec_avec_recul_puis_relivraison_unique(monde, nom, prod, type_, fabrique, registre):
    avant = monde.taille(M8, registre)
    monde.pannes.add(M8)
    _publier(prod, type_, fabrique(2), f"{nom}-p")
    monde.repartir(passes=1, departements=(M8,))
    recu = _recu(monde, type_, f"{nom}-p")
    assert recu["statut"] == "echec" and recu["tentatives"] == 1 and recu["prochaine_tentative"], recu
    assert monde.taille(M8, registre) == avant and monde.quarantaines() == []
    monde.pannes.clear()
    monde.repartir(departements=(M8,))
    assert _recu(monde, type_, f"{nom}-p")["statut"] == "traite"
    assert monde.taille(M8, registre) == avant + 1
    monde.repartir(departements=(M8,))
    assert monde.taille(M8, registre) == avant + 1 and monde.quarantaines() == []


@pytest.mark.parametrize(("nom", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_garantie_4_charge_forgee_ou_hors_catalogue_refusee_sans_rien_ecrire(
    monde, nom, prod, type_, fabrique, registre
):
    charge = fabrique(3)
    charge["champ_personnel_inattendu"] = "Jeanne Fictive jeanne.fictive@example.test"
    with pytest.raises(ChargeInvalide):
        _publier(prod, type_, charge, f"{nom}-x")
    manquante = fabrique(3)
    cle = next(iter(manquante))
    del manquante[cle]
    with pytest.raises(ChargeInvalide):
        _publier(prod, type_, manquante, f"{nom}-y")
    assert monde.sortants(type_) == [] and monde.taille(M8, registre) == 0


@pytest.mark.parametrize(("nom", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_garantie_5_rien_de_personnel_ne_traverse(monde, nom, prod, type_, fabrique, registre):
    _publier(prod, type_, fabrique(4), f"{nom}-r")
    monde.repartir(departements=(M8,))
    texte_recu = json.dumps(_recu(monde, type_, f"{nom}-r"), default=str, ensure_ascii=False)
    texte_fait = json.dumps(monde.registre(M8, registre), default=str, ensure_ascii=False)
    for interdit in PERSONNEL:
        if registre == "faits_chantier" and interdit == "tech-fictif":
            continue  # le fait `wct` garde le technicien de M4 (registre de M8, jamais l'entrepôt) : voir ci-dessous
        assert interdit not in texte_recu, (nom, interdit)
        assert interdit not in texte_fait, (nom, interdit)
    # l'entrepôt, lui, n'en porte jamais : toutes les tables dérivées, après une construction réelle
    sortie = Capacites(monde.departements, stockage.transaction, filtre={M8}, memoire=False).appeler(
        "m8_construire_entrepot", {"maintenant": INSTANT}
    )
    assert sortie["ok"] is True, sortie
    registres = {
        "chantier": monde.registre(M8, "faits_chantier"),
        "entonnoir": monde.registre(M8, "faits_entonnoir"),
        "contenus": monde.registre(M8, "faits_contenus"),
        "cash_libre": monde.registre(M8, "faits_cash_libre"),
        "operations": monde.registre(M8, "faits_operations"),
    }
    construit = entrepot.construire(registres, catalogue_mesures.charger(), construit_le=INSTANT, rang_precedent=0)
    texte_entrepot = json.dumps(construit["tables"], default=str, ensure_ascii=False)
    for interdit in PERSONNEL:
        assert interdit not in texte_entrepot, (nom, interdit)


def test_les_registres_de_m8_n_ont_garde_aucun_champ_personnel_de_aucune_source(monde):
    """Toutes les sources ensemble : le technicien de M4 reste au registre `faits_chantier` (comme avant) et nulle part
    ailleurs ; le contact de M1, le fournisseur de M6, les lignes de prix de M6 ne sont dans AUCUN registre de M8."""
    for _, prod, type_, fabrique, _ in CAS:
        _publier(prod, type_, fabrique(1), f"tout-{type_}")
    monde.repartir(departements=(M8,))
    assert monde.quarantaines() == [] and monde.ecritures_hors_propriete() == []
    ailleurs = ""
    for registre in ("faits_entonnoir", "faits_contenus", "faits_cash_libre", "faits_operations", "snapshots"):
        ailleurs += json.dumps(monde.registre(M8, registre), default=str, ensure_ascii=False)
    for interdit in PERSONNEL:
        assert interdit not in ailleurs, interdit
    assert "prix_unitaire" not in ailleurs and "quantite_recue" not in ailleurs
