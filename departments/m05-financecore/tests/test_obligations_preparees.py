"""Déclarations préparatoires, fixtures fictives ; aucun paiement."""

import copy
import importlib
import importlib.util

import pytest
from m5_financecore import registre

from opsys.idempotence import empreinte_arguments

FICTIF = True
HORA = "2026-10-09T12:00:00+00:00"
AUTEUR = {"personne": "admin.fictif", "role": "admin", "source": "appareil"}
INTENTION = {"appareil_id": "device.fictif", "intention_uuid": "uuid.fictif", "empreinte_arguments": "a" * 64}


def intention(a):
    return {**INTENTION, "empreinte_arguments": empreinte_arguments(a)}


def args(**changes):
    result = {
        "categorie": "paies",
        "operation": "declarer",
        "revision_attendue": None,
        "motif": "FICTIF",
        "declaration": {
            "montant": "0.00",
            "source": "déclaration FICTIVE",
            "au": "2026-10-09",
            "echeance": None,
            "calendrier": None,
        },
    }
    result.update(changes)
    return result


@pytest.fixture
def ob():
    return importlib.import_module("m5_financecore.obligations_preparees")


def test_module_metier_present():
    assert importlib.util.find_spec("m5_financecore.obligations_preparees") is not None


@pytest.mark.parametrize("montant", [1, True, "-1", "NaN", "1e2", "+1", "0.001", "1" * 13])
def test_montant_invalide_refuse_sans_correction(ob, montant):
    a = args()
    a["declaration"]["montant"] = montant
    with pytest.raises(ob.Refus):
        ob.valider_mutation(a)


@pytest.mark.parametrize(
    "champ,valeur",
    [("au", "2026-02-30"), ("source", " "), ("source", "x" * 121), ("source", "\ud800"), ("echeance", "2026-10-09\n")],
)
def test_deep_validation_date_texte(ob, champ, valeur):
    a = args()
    a["declaration"][champ] = valeur
    with pytest.raises(ob.Refus):
        ob.valider_mutation(a)


def test_raw_et_calendrier_distincts(ob):
    a = args()
    a["declaration"]["source"] = "  FICTIF  "
    r = registre.Registre()
    entry = ob.construire_entree(a, AUTEUR, intention(a), HORA, HORA)
    r.ajouter(entry)
    raw = ob.snapshot_courant(r.lire())["paies"]
    dto = ob.lire(r.lire(), "2026-10-10", 0, 1)
    assert raw["maillon"]["declaration"] == a["declaration"]
    assert dto["obligations"][0]["declaration"]["source"] == "  FICTIF  "
    assert dto["obligations"][0]["calendrier_preparatoire"]["source_montant"]["description"] == "FICTIF"
    assert dto["obligations"][0]["calendrier_preparatoire"]["montant_utilisable"] == "0.00"
    assert dto["obligations"][0]["calendrier_preparatoire"]["statut"] == "INCOMPLETE"


def test_retrait_absence_et_zero_distincts(ob):
    r = registre.Registre()
    assert ob.lire([], "2026-10-09", 0, 8)["obligations"][0]["etat_declaration"] == "ABSENTE"
    r.ajouter(ob.construire_entree(args(), AUTEUR, intention(args()), HORA, HORA))
    ref = ob.snapshot_courant(r.lire())["paies"]["reference"]
    b = args(operation="retirer", declaration=None, revision_attendue=ref)
    i = {**intention(b), "intention_uuid": "autre"}
    r.ajouter(ob.construire_entree(b, AUTEUR, i, HORA, HORA))
    row = ob.lire(r.lire(), "2026-10-09", 0, 8)["obligations"][0]
    assert row["etat_declaration"] == "RETIREE" and row["declaration"] is None
    with pytest.raises(ob.Refus):
        ob.verifier_revision(ob.snapshot_courant(r.lire()), args())


def test_schema_pagination_chain_quota(ob):
    for a in [
        {"aujourd_hui": "2026-10-09", "decalage": True, "limite": 8},
        {"aujourd_hui": "2026-10-09", "decalage": 0, "limite": 9},
    ]:
        with pytest.raises(ob.Refus):
            ob.valider_lecture(a)
    with pytest.raises(ob.Refus):
        ob.snapshot_courant([{}] * 10001)
    r = registre.Registre()
    r.ajouter(ob.construire_entree(args(), AUTEUR, intention(args()), HORA, HORA))
    bad = copy.deepcopy(r.lire())
    bad[0]["declaration"]["montant"] = "10"
    with pytest.raises(ob.Refus):
        ob.snapshot_courant(bad)
    assert ob.lire(r.lire(), "2026-10-09", 3, 1)["obligations"] == []
    with pytest.raises(ob.Refus):
        ob.lire(r.lire(), "2026-10-09", 4, 1)


@pytest.mark.parametrize("value", [None, [], 1, True, {"montant": 0}, {"categorie": "taxes"}])
def test_forme_fermee_nonobject(ob, value):
    with pytest.raises(ob.Refus):
        ob.valider_mutation(value)


@pytest.mark.parametrize("value", [None, [], 1, True])
def test_maillon_nonobject(ob, value):
    with pytest.raises(ob.Refus):
        ob.snapshot_courant([value])


def test_champs_inconnus_et_revision_boolean(ob):
    a = args()
    a["declaration"]["prive"] = "ne doit pas passer"
    with pytest.raises(ob.Refus):
        ob.valider_mutation(a)
    a = args(
        revision_attendue={
            "registre": "obligations_preparees",
            "index": True,
            "ligne_id": "b" * 64,
            "precedent_ligne_id": None,
        }
    )
    with pytest.raises(ob.Refus):
        ob.valider_mutation(a)


def test_source_dates_inverses_refusees_et_raw_unicode_conserve(ob):
    a = args()
    a["declaration"]["calendrier"] = {k: None for k in ob.CHAMPS_CALENDRIER}
    a["declaration"]["calendrier"].update(periode_debut="2026-10-10", periode_fin="2026-10-09")
    with pytest.raises(ob.Refus):
        ob.valider_mutation(a)
    a = args()
    a["motif"] = "FICTIF é 😀\\t\\r\\n"
    a["declaration"]["montant"] = "000.10"
    assert ob.valider_mutation(a) == a


def test_reference_nouvel_index_depassant_plafond_refuse_avant_append(ob):
    with pytest.raises(ob.Refus, match="10000"):
        ob.reference({"ligne_id": "a" * 64, "precedent_ligne_id": None}, 10000)
