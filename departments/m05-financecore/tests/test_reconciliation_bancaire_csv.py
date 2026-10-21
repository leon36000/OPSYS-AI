from __future__ import annotations

import copy
from decimal import Decimal, localcontext

import pytest
from m5_financecore import encodage, facturation, registre
from m5_financecore import reconciliation_bancaire_csv as csv_ar

FICTIF = True
MAPPING = {"date": "Date", "montant": "Montant", "reference_facture": "Reference"}


def _snapshot(factures=None, *, version=7, empreinte="a" * 64, total_complet=True):
    if factures is None:
        factures = [{"facture_id": "FAC-101", "montant_apres_taxes": Decimal("125.50")}]
    return {"version": version, "empreinte": empreinte, "total_complet": total_complet, "factures": factures}


def _preview(csv_text, snapshot=None, **overrides):
    arguments = {
        "contenu": csv_text.encode("utf-8"), "compte_interne_id": "BANQUE-OPER-01", "devise": "CAD",
        "mapping_colonnes": MAPPING, "snapshot_factures": snapshot or _snapshot(),
    }
    arguments.update(overrides)
    return csv_ar.previsualiser_releve_csv(**arguments)


def test_propose_seulement_reference_exacte_et_montant_du_exact_et_hashes_les_sources():
    resultat, verdict = _preview("Date,Montant,Reference\n2026-09-30,125.50,FAC-101\n")

    assert verdict is None
    assert resultat["statut"] == "PROPOSITIONS_PRESENTES"
    assert resultat["lignes"] == [{
        "numero": 2, "date": "2026-09-30", "montant": "125.50", "reference_facture": "FAC-101",
        "statut_rapprochement": "PROPOSITION_EXACTE", "facture_id": "FAC-101", "montant_du": "125.50",
    }]
    assert resultat["propositions"] == [{
        "ligne": 2, "facture_id": "FAC-101", "montant": "125.50", "statut": "PROPOSE",
    }]
    assert resultat["source_factures"]["version"] == 7
    assert resultat["source_factures"]["empreinte"] == "a" * 64
    assert len(resultat["lot_id"]) == 64
    assert len(resultat["source_factures"]["empreinte_vue"]) == 64


def test_adaptateur_peut_utiliser_la_vue_ar_et_la_tete_du_registre_m5_sans_mutation():
    factures = registre.Registre()
    factures.ajouter({
        "type_entree": "facture_creee", "facture_id": "FAC-201", "statut": "BROUILLON",
        "montant_apres_taxes": Decimal("88.25"), "horodatage": "2026-09-28T12:00:00+00:00",
    })
    factures.ajouter({
        "type_entree": "transition_facture", "facture_id": "FAC-201", "statut": "ENVOYEE",
        "date_envoi": "2026-09-29T12:00:00+00:00", "horodatage": "2026-09-29T12:00:00+00:00",
    })
    vue, verdict_vue = facturation.comptes_a_recevoir(factures)
    assert verdict_vue is None and vue["factures"][0]["montant_apres_taxes"] == Decimal("88.25")
    taille_avant, tete_avant = factures.taille(), factures.tete()
    snapshot = {
        "version": taille_avant, "empreinte": tete_avant, "total_complet": vue["total_complet"],
        "factures": vue["factures"],
    }

    resultat, verdict = _preview(
        "Date,Montant,Reference\n2026-09-30,88.25,FAC-201\n", snapshot,
    )

    assert verdict is None and resultat["propositions"][0]["facture_id"] == "FAC-201"
    assert factures.taille() == taille_avant and factures.tete() == tete_avant


def test_un_montant_seul_ne_rapproche_jamais_une_reference_inconnue():
    resultat, verdict = _preview("Date,Montant,Reference\n2026-09-30,125.50,REF-INCONNUE\n")

    assert verdict is None and resultat["propositions"] == []
    assert resultat["lignes"][0]["statut_rapprochement"] == "REFERENCE_FACTURE_INCONNUE"
    assert resultat["lignes"][0]["facture_id"] is None


@pytest.mark.parametrize(
    ("montant", "statut"),
    [("130.00", "FRAIS_OU_ECART_NON_SUPPORTE")],
)
def test_frais_ou_ecart_ne_proposent_aucun_rapprochement(montant, statut):
    snapshot = _snapshot([{"facture_id": "FAC-101", "montant_apres_taxes": Decimal("125.50")}])
    resultat, verdict = _preview(f"Date,Montant,Reference\n2026-09-30,{montant},FAC-101\n", snapshot)

    assert verdict is None and resultat["propositions"] == []
    assert resultat["lignes"][0]["statut_rapprochement"] == statut


def test_reference_repetee_dans_un_split_marque_les_lignes_sans_proposition():
    resultat, verdict = _preview(
        "Date,Montant,Reference\n2026-09-29,60.00,FAC-101\n2026-09-30,65.50,FAC-101\n"
    )

    assert verdict is None and resultat["propositions"] == []
    assert [row["statut_rapprochement"] for row in resultat["lignes"]] == [
        "REFERENCE_REPETEE_SPLIT_NON_SUPPORTE", "REFERENCE_REPETEE_SPLIT_NON_SUPPORTE",
    ]


def test_montants_signes_restent_explicites_sans_rapprocher_les_flux_sortants_ou_zero():
    resultat, verdict = _preview(
        "Date,Montant,Reference\n2026-09-30,-125.50,FAC-101\n2026-09-30,0.00,REF-OTHER\n"
    )

    assert verdict is None and resultat["propositions"] == []
    assert [row["statut_rapprochement"] for row in resultat["lignes"]] == [
        "FLUX_SORTANT_HORS_AR", "MONTANT_ZERO_NON_RAPPROCHABLE",
    ]


@pytest.mark.parametrize(
    ("csv_text", "code"),
    [
        ("Date,Montant,Reference\n2026-09-30,1.0,FAC-101\n", "REJ-M53-CSV-VALEUR"),
        ("Date,Montant,Reference\n2026-9-30,1.00,FAC-101\n", "REJ-M53-CSV-DATE"),
        ("Date,Montant,Reference\n2026-09-30,１２.００,FAC-101\n", "REJ-M53-CSV-VALEUR"),
        ("Date,Montant,Reference\n2026-09-30,12.00,=HYPERLINK(\"x\")\n", "REJ-M53-CSV-FORMULE"),
        ("Date,Montant,Reference\n2026-09-30,12.00,FAC-101\n2026-09-30,12.00,FAC-101\n",
         "REJ-M53-CSV-DOUBLON"),
        ("Date,Montant,Reference\n2026-09-30,12.00,FAC-101,EXTRA\n", "REJ-M53-CSV-COLONNES"),
    ],
)
def test_donnees_mal_formees_sont_refusees_sans_cellule_brute_dans_le_verdict(csv_text, code):
    resultat, verdict = _preview(csv_text)

    assert resultat is None and verdict["code"] == code
    assert "FAC-101" not in verdict["detail"]


def test_formule_et_texte_bancaire_extra_ne_sont_pas_rendus_dans_la_sortie():
    resultat, verdict = _preview(
        "Date,Montant,Reference,Description\n2026-09-30,125.50,FAC-101,Depot client sensible\n"
    )

    assert verdict is None
    assert "Description" not in str(resultat) and "Depot client sensible" not in str(resultat)

    resultat, verdict = _preview(
        "Date,Montant,Reference,Description\n2026-09-30,125.50,FAC-101,=HYPERLINK(\"secret\")\n"
    )
    assert resultat is None and verdict["code"] == "REJ-M53-CSV-FORMULE"
    assert "secret" not in verdict["detail"]


@pytest.mark.parametrize(
    ("snapshot", "code"),
    [
        (_snapshot(total_complet=False), "REJ-M53-SNAPSHOT-INCOMPLET"),
        (_snapshot(empreinte="not-a-hash"), "REJ-M53-SNAPSHOT-EMPREINTE"),
        (_snapshot([{"facture_id": "FAC-101", "montant_apres_taxes": Decimal("NaN")}]),
         "REJ-M53-SNAPSHOT-FACTURE"),
        (_snapshot([{"facture_id": "FAC-101", "montant_apres_taxes": Decimal("1.001")}]),
         "REJ-M53-SNAPSHOT-FACTURE"),
        (_snapshot([
            {"facture_id": "FAC-101", "montant_apres_taxes": Decimal("10.00")},
            {"facture_id": "FAC-101", "montant_apres_taxes": Decimal("20.00")},
        ]), "REJ-M53-SNAPSHOT-AMBIGU"),
    ],
)
def test_vue_m5_absente_incomplete_ou_ambigue_est_refusee(snapshot, code):
    resultat, verdict = _preview("Date,Montant,Reference\n2026-09-30,125.50,FAC-101\n", snapshot)

    assert resultat is None and verdict["code"] == code


def test_compte_devise_mapping_utf8_et_taille_sont_valides():
    base = {"contenu": b"Date,Montant,Reference\n2026-09-30,125.50,FAC-101\n"}
    params = {
        "compte_interne_id": "BANQUE-OPER-01", "devise": "CAD", "mapping_colonnes": MAPPING,
        "snapshot_factures": _snapshot(),
    }
    assert csv_ar.previsualiser_releve_csv(**base, **{**params, "compte_interne_id": ""})[1]["code"] == \
        "REJ-M53-COMPTE-INVALIDE"
    assert csv_ar.previsualiser_releve_csv(**base, **{**params, "devise": "USD"})[1]["code"] == \
        "REJ-M53-DEVISE-NON-CAD"
    assert csv_ar.previsualiser_releve_csv(**base, **{**params, "mapping_colonnes": {"date": "Date"}})[1]["code"] == \
        "REJ-M53-MAPPING-INVALIDE"
    assert csv_ar.previsualiser_releve_csv(contenu=b"\xff", **params)[1]["code"] == "REJ-M53-CSV-LECTURE"
    assert csv_ar.previsualiser_releve_csv(contenu=b"x" * (csv_ar.OCTETS_MAX + 1), **params)[1]["code"] == \
        "REJ-M53-CSV-TROP-GROS"


def test_csv_cite_mais_mal_formee_est_refusee_sans_exposer_son_contenu():
    resultat, verdict = _preview('Date,Montant,Reference\n2026-09-30,"125.50,FAC-101\n')

    assert resultat is None and verdict["code"] == "REJ-M53-CSV-LECTURE"
    assert "125.50" not in verdict["detail"]


def test_limite_lignes_est_un_refus_structure_sans_ligne_partielle():
    lignes = ["Date,Montant,Reference"]
    lignes.extend(f"2026-09-30,1.00,REF-{index}" for index in range(csv_ar.LIGNES_MAX + 1))
    resultat, verdict = _preview("\n".join(lignes) + "\n", _snapshot([], version=0, empreinte=None))

    assert resultat is None
    assert verdict == {
        "code": "REJ-M53-CSV-TROP-DE-LIGNES",
        "detail": "le relevé dépasse 2 000 lignes",
        "ligne": csv_ar.LIGNES_MAX + 2,
    }


def test_aucune_entree_fournie_au_noyau_ni_vue_ar_ni_mapping_n_est_mutablee():
    snapshot = _snapshot()
    mapping = dict(MAPPING)
    snapshot_avant = copy.deepcopy(snapshot)
    mapping_avant = dict(mapping)

    resultat, verdict = csv_ar.previsualiser_releve_csv(
        b"Date,Montant,Reference\n2026-09-30,125.50,FAC-101\n", compte_interne_id="BANQUE-OPER-01",
        devise="CAD", mapping_colonnes=mapping, snapshot_factures=snapshot,
    )

    assert verdict is None and resultat["propositions"]
    assert snapshot == snapshot_avant and mapping == mapping_avant


def test_calculs_et_empreinte_ne_dependent_pas_du_contexte_decimal_ambiant():
    contenu = b"Date,Montant,Reference\n2026-09-30,125.50,FAC-101\n"
    with localcontext() as contexte:
        contexte.prec = 2
        resultat_prec2, verdict = csv_ar.previsualiser_releve_csv(
            contenu, compte_interne_id="BANQUE-OPER-01", devise="CAD", mapping_colonnes=MAPPING,
            snapshot_factures=_snapshot(),
        )
    assert verdict is None

    with localcontext() as contexte:
        contexte.prec = 50
        resultat_prec50, verdict = csv_ar.previsualiser_releve_csv(
            contenu, compte_interne_id="BANQUE-OPER-01", devise="CAD", mapping_colonnes=MAPPING,
            snapshot_factures=_snapshot(),
        )
    assert verdict is None
    assert resultat_prec2 == resultat_prec50


LIMITES_LEGACY = [
    "Rapprochement proposé seulement : aucune facture, aucun mouvement ni solde n'est modifié",
    "La référence doit être le facture_id M5 exact et le montant doit égaler le dû complet",
    "Partiels, splits, frais, frais bancaires et associations par montant seul ne sont pas pris en charge",
    "L'adaptateur doit fournir une vue M5 complète et vérifier son intégrité avant cet appel",
    "La provenance bancaire, les dépôts et l'identité du compte doivent être vérifiés par un humain",
]
LIMITES_PARTIEL = [
    LIMITES_LEGACY[0],
    "Une seule ligne de données, une référence facture M5 exacte et un montant CAD strictement positif "
    "inférieur au dû du snapshot sont requis",
    "Partiels dans un CSV multi-lignes, splits, frais, frais bancaires, surpaiements et associations "
    "par montant seul ne sont pas pris en charge",
    LIMITES_LEGACY[3], LIMITES_LEGACY[4],
    "Ce candidat ne distingue pas un acompte d'un montant net de frais ; il ne confirme ni encaissement "
    "ni solde restant",
]


def test_partiel_unique_propose_sans_reduire_le_du():
    resultat, verdict = _preview("Date,Montant,Reference\n2026-09-30,10.00,FAC-101\n")

    assert verdict is None
    assert resultat["statut"] == "PROPOSITIONS_PRESENTES"
    assert resultat["version_rapprochement"] == "m5.3-partiel-unique/v1"
    assert resultat["lignes"] == [{
        "numero": 2, "date": "2026-09-30", "montant": "10.00", "reference_facture": "FAC-101",
        "statut_rapprochement": "PROPOSITION_PARTIELLE", "facture_id": "FAC-101", "montant_du": "125.50",
    }]
    assert resultat["propositions"] == [{
        "ligne": 2, "facture_id": "FAC-101", "montant": "10.00", "statut": "PROPOSE_PARTIEL",
    }]
    assert resultat["limites"] == LIMITES_PARTIEL


@pytest.mark.parametrize("seconde_ligne", [
    "2026-09-30,20.00,FAC-202", "2026-09-30,50.00,FAC-202", "2026-09-30,0.00,INCONNUE",
])
def test_partiel_exige_un_csv_singleton_sans_filtrer_les_autres_lignes(seconde_ligne):
    snapshot = _snapshot([
        {"facture_id": "FAC-101", "montant_apres_taxes": Decimal("125.50")},
        {"facture_id": "FAC-202", "montant_apres_taxes": Decimal("50.00")},
    ])
    resultat, verdict = _preview(
        f"Date,Montant,Reference\n2026-09-30,10.00,FAC-101\n{seconde_ligne}\n", snapshot,
    )
    assert verdict is None
    assert resultat["lignes"][0]["statut_rapprochement"] == "PAIEMENT_PARTIEL_NON_SUPPORTE"
    assert all(p["statut"] == "PROPOSE" and p["facture_id"] == "FAC-202" for p in resultat["propositions"])
    assert len(resultat["propositions"]) == (1 if ",50.00," in seconde_ligne else 0)
    assert "version_rapprochement" not in resultat
    assert resultat["limites"] == LIMITES_LEGACY


@pytest.mark.parametrize("montant,partiel", [("10.00", True), ("125.50", False), ("130.00", False)])
def test_domaine_lot_versionne_uniquement_pour_partiel(montant, partiel):
    resultat, verdict = _preview(f"Date,Montant,Reference\n2026-09-30,{montant},FAC-101\n")
    assert verdict is None
    domaine_legacy = {
        "sha256_csv": resultat["source_csv"]["sha256"], "compte_interne_id": "BANQUE-OPER-01", "devise": "CAD",
        "mapping_colonnes": MAPPING, "version_factures": 7, "empreinte_factures": "a" * 64,
        "empreinte_vue_factures": encodage.empreinte({"FAC-101": Decimal("125.50")}),
    }
    if partiel:
        assert resultat["lot_id"] != encodage.empreinte(domaine_legacy)
        assert resultat["lot_id"] == encodage.empreinte({
            **domaine_legacy, "version_rapprochement": "m5.3-partiel-unique/v1",
        })
    else:
        assert resultat["lot_id"] == encodage.empreinte(domaine_legacy)
        assert "version_rapprochement" not in resultat
        assert resultat["limites"] == LIMITES_LEGACY


def test_partiel_centime_canonique_et_contexte_decimal():
    resultats = []
    for precision in (2, 50):
        with localcontext() as contexte:
            contexte.prec = precision
            resultat, verdict = _preview("Date,Montant,Reference\n2026-09-30,0.01,FAC-101\n")
        assert verdict is None
        assert resultat["propositions"] == [{
            "ligne": 2, "facture_id": "FAC-101", "montant": "0.01", "statut": "PROPOSE_PARTIEL",
        }]
        resultats.append(resultat)
    assert resultats[0] == resultats[1]


@pytest.mark.parametrize("montant,statut", [
    ("0.00", "MONTANT_ZERO_NON_RAPPROCHABLE"), ("-0.01", "FLUX_SORTANT_HORS_AR"),
])
def test_singleton_non_positif_ne_devient_pas_partiel(montant, statut):
    resultat, verdict = _preview(f"Date,Montant,Reference\n2026-09-30,{montant},FAC-101\n")
    assert verdict is None and resultat["propositions"] == []
    assert resultat["lignes"][0]["statut_rapprochement"] == statut
    assert "version_rapprochement" not in resultat
    assert resultat["limites"] == LIMITES_LEGACY


def test_partiel_ne_modifie_aucune_entree():
    snapshot, mapping = _snapshot(), dict(MAPPING)
    avant = copy.deepcopy((snapshot, mapping))
    resultat, verdict = _preview(
        "Date,Montant,Reference\n2026-09-30,10.00,FAC-101\n", snapshot, mapping_colonnes=mapping,
    )
    assert verdict is None and resultat["propositions"][0]["statut"] == "PROPOSE_PARTIEL"
    assert (snapshot, mapping) == avant
