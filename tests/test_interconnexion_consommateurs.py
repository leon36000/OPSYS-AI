"""Contrat commun des consommateurs d'interconnexion, sur le VRAI bus (`evenements.repartir`, `consommateurs()` réels).

Pour chaque consommateur ajouté par le chantier d'interconnexion (docs/architecture/INTERCONNEXION.md), les MÊMES
garanties :

1. livré et rangé chez le département destinataire (le reçu du bus passe à `traite`) ;
2. idempotent : le même constat republié sous un AUTRE `evenement_id` n'ajoute rien et ne met rien en quarantaine ;
3. tolérant à la panne : si le stockage du destinataire est indisponible, l'événement reste en `echec` avec un recul
(jamais
   en quarantaine à la première panne, jamais perdu), puis la relivraison l'écrit UNE fois ;
4. propriété des données : aucun consommateur n'écrit dans le registre d'un autre département ;
5. charge hors catalogue refusée à la publication (rien n'est écrit) ;
6. le résumé gardé au reçu du bus ne contient aucun champ personnel.

Les comportements propres à chaque consommateur sont dans les fichiers `test_interconnexion_<flux>.py`. Données
fictives.
"""

from __future__ import annotations

import json

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest

from opsys import evenements
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

# (nom, destinataire, producteur, type, fabrique(variante: int) -> charge, registre du destinataire)
CAS = [
    (
        "m8-signaux",
        M8,
        M7,
        "m7.signaux_marketing_constates",
        lambda v: ch.signaux_marketing(fin=f"2026-10-{20 + v}", lu_le=f"2026-10-{20 + v}T06:00:00-04:00"),
        "faits_operations",
    ),
    (
        "m8-depenses",
        M8,
        M7,
        "m7.depenses_marketing_constatees",
        lambda v: ch.depense_marketing(releve_id=f"releve-{v}"),
        "faits_operations",
    ),
    (
        "m8-anomalie",
        M8,
        M7,
        "m7.anomalie_depense_detectee",
        lambda v: ch.anomalie_depense(anomalie_id=f"{v:032x}"),
        "faits_operations",
    ),
    (
        "m8-conversion",
        M8,
        M7,
        "m7.conversion_hors_ligne_importee",
        lambda v: ch.conversion_hors_ligne(conversion_id=f"conv-{v}"),
        "faits_operations",
    ),
    (
        "m8-mesures-comptables",
        M8,
        M5,
        "m5.mesures_comptables_constatees",
        lambda v: ch.mesures_comptables(version=f"{v:016x}"),
        "faits_operations",
    ),
    (
        "m8-vision",
        M8,
        M3,
        "m3.mesure_vision_validee",
        lambda v: ch.mesure_vision(candidat_id=f"cand-{v}"),
        "faits_operations",
    ),
    (
        "m5-depense",
        M5,
        M7,
        "m7.depenses_marketing_constatees",
        lambda v: ch.depense_marketing(releve_id=f"releve-m5-{v}"),
        "charges_marketing_recues",
    ),
    (
        "m2-conversion",
        M2,
        M7,
        "m7.conversion_hors_ligne_importee",
        lambda v: ch.conversion_hors_ligne(conversion_id=f"conv-m2-{v}"),
        "conversions_hors_ligne_recues",
    ),
    (
        "m2-creance",
        M2,
        M5,
        "m5.creance_relance_preparee",
        lambda v: ch.creance_relance(relance_id=f"relance-{v}"),
        "creances_relances_recues",
    ),
    (
        "m2-facture-close",
        M2,
        M5,
        "m5.facture_emise_constatee",
        lambda v: ch.facture_emise(facture_id=f"fc-close-{v}", statut="PAYEE"),
        "factures_closes_recues",
    ),
    (
        "m2-contexte-site",
        M2,
        M3,
        "m3.contexte_site_pret",
        lambda v: ch.contexte_site(lead_id=f"lead-site-{v}"),
        "contextes_site_recus",
    ),
    (
        "m3-lien",
        M3,
        M2,
        "m2.client_associe",
        lambda v: ch.client_associe(lead_id=f"lead-lien-{v}"),
        "liens_lead_client",
    ),
    (
        "m3-profil",
        M3,
        M2,
        "m2.profil_propriete_confirme",
        lambda v: ch.profil_propriete(propriete_id=ch.empreinte("p", str(v))),
        "profils_propriete_recus",
    ),
    (
        "m4-lien",
        M4,
        M2,
        "m2.client_associe",
        lambda v: ch.client_associe(lead_id=f"lead-lien4-{v}"),
        "liens_lead_client",
    ),
    (
        "m4-profil",
        M4,
        M2,
        "m2.profil_propriete_confirme",
        lambda v: ch.profil_propriete(propriete_id=ch.empreinte("p4", str(v))),
        "profils_propriete_recus",
    ),
    (
        "m6-rapprochement",
        M6,
        M5,
        "m5.rapprochement_po_constate",
        lambda v: ch.rapprochement_po(facture=f"ff-{v}"),
        "rapprochements_facture_recus",
    ),
    (
        "m9-anomalie",
        M9,
        M7,
        "m7.anomalie_depense_detectee",
        lambda v: ch.anomalie_depense(anomalie_id=f"{v + 100:032x}"),
        "signaux_gestion_recus",
    ),
    ("m9-consolide", M9, M8, "m8.fait_consolide", lambda v: ch.fait_consolide(graine=f"g{v}"), "signaux_gestion_recus"),
    (
        "m1-suivi-retire",
        M1,
        M4,
        "m4.consentement_suivi_retire",
        lambda v: ch.consentement_suivi_retire(intervention_id=f"interv-retrait-{v}"),
        "messages_clients_m4",
    ),
    (
        "m10-dossier-cpa",
        M10,
        M5,
        "m5.dossier_cpa_scelle",
        lambda v: ch.dossier_cpa(dossier_id=f"dossier-{v}"),
        "dossiers_cpa_scelles",
    ),
]
IDS = [c[0] for c in CAS]


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch)
    m.surveiller(monkeypatch)
    yield m
    im.demonter()


def _publier(producteur, type_evenement, charge, evenement_id):
    return evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)


def _statuts(monde, destinataire, type_evenement):
    ids = {e["evenement_id"] for e in monde.sortants(type_evenement)}
    return {r["evenement_id"]: r for r in monde.recus(consommateur=destinataire) if r["evenement_id"] in ids}


@pytest.mark.parametrize(("nom", "dest", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_livre_et_range_chez_le_destinataire_sans_ecrire_chez_un_autre(
    monde, nom, dest, prod, type_, fabrique, registre
):
    avant = monde.taille(dest, registre)
    _publier(prod, type_, fabrique(1), f"{nom}-1")
    monde.repartir()
    recu = _statuts(monde, dest, type_)[f"{nom}-1"]
    assert recu["statut"] == "traite" and recu["tentatives"] == 1, recu
    assert monde.taille(dest, registre) == avant + 1
    assert monde.quarantaines() == []
    assert monde.ecritures_hors_propriete() == []
    assert any(e["consommateur"] == dest and e["registre"] == registre for e in monde.ecritures)


@pytest.mark.parametrize(("nom", "dest", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_rejeu_sous_un_autre_evenement_id_ne_duplique_rien_et_ne_met_rien_en_quarantaine(
    monde, nom, dest, prod, type_, fabrique, registre
):
    _publier(prod, type_, fabrique(1), f"{nom}-a")
    monde.repartir()
    apres_premier = monde.taille(dest, registre)
    # Même constat, autre identifiant : le bus le livre (autre enveloppe), le consommateur ne ré-écrit pas.
    _publier(prod, type_, fabrique(1), f"{nom}-b")
    resume = monde.repartir()
    recus = _statuts(monde, dest, type_)
    assert recus[f"{nom}-b"]["statut"] == "traite", recus
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    assert monde.taille(dest, registre) == apres_premier
    assert monde.quarantaines() == []
    # Rejouer le répartiteur n'ajoute rien non plus (reçus clos).
    monde.repartir()
    assert monde.taille(dest, registre) == apres_premier


@pytest.mark.parametrize(("nom", "dest", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_panne_du_destinataire_echec_avec_recul_puis_relivraison_unique(
    monde, nom, dest, prod, type_, fabrique, registre
):
    avant = monde.taille(dest, registre)
    monde.pannes.add(dest)
    _publier(prod, type_, fabrique(2), f"{nom}-p")
    monde.repartir(passes=1)
    recu = _statuts(monde, dest, type_)[f"{nom}-p"]
    assert recu["statut"] == "echec" and recu["tentatives"] == 1 and recu["prochaine_tentative"], recu
    assert monde.taille(dest, registre) == avant  # rien d'écrit à moitié
    assert monde.quarantaines() == []
    # Le département revient : la relivraison (échéance due) écrit une fois.
    monde.pannes.clear()
    monde.repartir()
    assert _statuts(monde, dest, type_)[f"{nom}-p"]["statut"] == "traite"
    assert monde.taille(dest, registre) == avant + 1
    monde.repartir()
    assert monde.taille(dest, registre) == avant + 1
    assert monde.quarantaines() == []


@pytest.mark.parametrize(("nom", "dest", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_charge_hors_catalogue_refusee_a_la_publication(monde, nom, dest, prod, type_, fabrique, registre):
    charge = fabrique(3)
    charge["champ_personnel_inattendu"] = "Jean Tremblay jean@example.test"
    with pytest.raises(ChargeInvalide):
        _publier(prod, type_, charge, f"{nom}-x")
    assert monde.sortants(type_) == []


@pytest.mark.parametrize(("nom", "dest", "prod", "type_", "fabrique", "registre"), CAS, ids=IDS)
def test_le_recu_du_bus_ne_garde_aucune_donnee_personnelle(monde, nom, dest, prod, type_, fabrique, registre):
    _publier(prod, type_, fabrique(4), f"{nom}-r")
    monde.repartir()
    recu = _statuts(monde, dest, type_)[f"{nom}-r"]
    texte = json.dumps(recu, default=str, ensure_ascii=False)
    for interdit in ("@example.test", "Jean", "telephone", "courriel", "adresse"):
        assert interdit not in texte, (interdit, texte)
