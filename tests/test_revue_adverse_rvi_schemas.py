"""Revue adverse rvi : le catalogue d'événements est plus strict que `jsonschema` par défaut.

Deux écarts entre ce que le catalogue AFFIRME et ce que `Draft202012Validator` vérifiait :
- `pattern` : Python `re.search` accepte `$` AVANT un saut de ligne final (« abc\\n » passait `^[a-z]+$`) ;
- `format: date-time` : sans paquet tiers, jsonschema ne vérifie RIEN (« pas une date » passait).
Données fictives ; aucune base.
"""

from __future__ import annotations

import interconnexion_charges as ch
import pytest

from opsys import evenements
from opsys.evenements import schemas
from opsys.evenements.bus import ChargeInvalide

FICTIF = True


def test_le_motif_ancre_refuse_le_saut_de_ligne_final_mais_accepte_la_valeur_propre():
    validateur = schemas._VALIDATEUR({"type": "string", "pattern": "^[a-z]+$"}, format_checker=schemas._FORMATS)
    assert validateur.is_valid("abc")
    for hostile in ("abc\n", "abc\n\n", "\nabc", "ab\nc"):
        assert not validateur.is_valid(hostile), repr(hostile)
    # un motif non ancré à la fin garde sa sémantique de recherche ; un « $ » échappé reste un caractère
    assert schemas._VALIDATEUR({"type": "string", "pattern": "abc"}).is_valid("xxabcxx")
    assert schemas._VALIDATEUR({"type": "string", "pattern": r"^a\$"}).is_valid("a$")
    assert not schemas._VALIDATEUR({"type": "string", "pattern": r"^a\$"}).is_valid("a\n")


@pytest.mark.parametrize(
    ("type_evenement", "fabrique", "champ"),
    [
        ("m7.depenses_marketing_constatees", ch.depense_marketing, "releve_id"),
        ("m5.dossier_cpa_scelle", ch.dossier_cpa, "dossier_id"),
        ("m5.creance_relance_preparee", ch.creance_relance, "relance_id"),
        ("m7.conversion_hors_ligne_importee", ch.conversion_hors_ligne, "conversion_id"),
        ("m5.mesures_comptables_constatees", ch.mesures_comptables, "date_reference"),
    ],
)
def test_un_identifiant_termine_par_un_saut_de_ligne_est_refuse_a_la_publication(type_evenement, fabrique, champ):
    charge = fabrique()
    assert evenements.schemas.erreurs_charge(type_evenement, charge) == []
    charge[champ] = charge[champ] + "\n"
    assert any(champ in e for e in evenements.schemas.erreurs_charge(type_evenement, charge))


@pytest.mark.parametrize("valeur", ["pas une date", "", "2026-10-30T10:00:00", "2026-10-30", "2026-13-40T10:00:00Z"])
def test_un_horodatage_date_time_sans_fuseau_ou_illisible_est_refuse(valeur):
    charge = ch.profil_propriete()
    charge["horodatage"] = valeur
    erreurs = schemas.erreurs_charge("m2.profil_propriete_confirme", charge)
    assert any("horodatage" in e and "date-time" in e for e in erreurs), (valeur, erreurs)


@pytest.mark.parametrize(
    "valeur", ["2026-10-30T10:00:00Z", "2026-10-30T10:00:00-04:00", "2026-10-30T10:00:00.250+00:00"])
def test_un_horodatage_date_time_avec_fuseau_reste_accepte(valeur):
    charge = ch.profil_propriete()
    charge["horodatage"] = valeur
    assert schemas.erreurs_charge("m2.profil_propriete_confirme", charge) == []


def test_publier_refuse_la_charge_hors_format_sans_rien_ecrire(tmp_path, monkeypatch):
    from opsys import stockage

    url = f"sqlite:///{tmp_path / 'rvi.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.migrer(url)
    try:
        charge = ch.profil_propriete()
        charge["horodatage"] = "pas une date"
        with pytest.raises(ChargeInvalide, match="date-time"):
            evenements.publier("m2.profil_propriete_confirme", "m02-revenue-crm", charge, evenement_id="rvi-1")
        assert not evenements.deja_publie("rvi-1")
    finally:
        stockage.liberer(url)


def test_tous_les_formats_du_catalogue_sont_connus_du_verificateur():
    """Un `format` ajouté au catalogue sans verificateur serait de nouveau purement décoratif."""
    import json

    formats = set()

    def parcourir(noeud):
        if isinstance(noeud, dict):
            if isinstance(noeud.get("format"), str):
                formats.add(noeud["format"])
            for v in noeud.values():
                parcourir(v)
        elif isinstance(noeud, list):
            for v in noeud:
                parcourir(v)

    for chemin in schemas._DOSSIER.glob("*.json"):
        parcourir(json.loads(chemin.read_text(encoding="utf-8")))
    assert formats <= set(schemas._FORMATS.checkers), formats
