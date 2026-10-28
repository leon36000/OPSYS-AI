"""Tarifs fictifs; coûts fournis par le vrai livre M6, jamais un prix de vente."""
from copy import deepcopy

import pytest
from m6_material_control import livre_prix
from m6_material_control.tarif_soumission import SelectionTarifRefusee, selectionner_tarif

FICTIF = True
FOURNISSEUR = {"fournisseur_id": "fournisseur-fictif", "nom": "Fournisseur fictif"}


def entree(**kw):
    return {"materiau_id": "materiau-fictif", "fournisseur_id": "fournisseur-fictif",
            "prix_unitaire": 12.5, "devise": "CAD", "date_effet": "2030-01-01",
            "source_document": "liste-fictive.pdf", "unite": "pi", **kw}


def choisir(lignes=None, **kw):
    return selectionner_tarif([(7, entree())] if lignes is None else lignes, FOURNISSEUR,
                              "materiau-fictif", "fournisseur-fictif", "pi", "2030-06-01", **kw)


def test_livre_reel_empreinte_rang_copie_et_rejeu():
    registre = []
    args = entree()
    valeur, erreur = livre_prix.enregistrer_prix(**args, registre_cible=registre)
    assert erreur is None and valeur == registre[0]
    lignes = [(17, registre[0])]
    avant = deepcopy(lignes)
    r = choisir(lignes)
    assert r["tarif_rang"] == 17 and len(r["tarif_empreinte"]) == 64
    assert r["cout_unitaire_decimal"] == "12.5"
    assert r["marquage_source"] == "SOURCE_DECLAREE"
    assert "quantite" not in r and "prix_vente" not in r
    assert choisir(lignes, rang_attendu=17, empreinte_attendue=r["tarif_empreinte"]) == r
    r["unite"] = "modification fictive"
    assert lignes == avant


def test_dernier_ecrit_pas_derniere_date_et_autre_fournisseur_ignore():
    r = choisir([(3, entree(date_effet="2030-05-01", prix_unitaire=15)),
                 (19, entree(date_effet="2030-02-01", prix_unitaire=13)),
                 (20, entree(fournisseur_id="autre-fictif", prix_unitaire=1))])
    assert r["cout_unitaire_decimal"] == "13" and r["tarif_rang"] == 19
    assert r["date_effet"] == "2030-02-01"


@pytest.mark.parametrize("changement,raison", [
    ({"prix_unitaire": True}, "prix_invalide"),
    ({"prix_unitaire": float("nan")}, "prix_invalide"),
    ({"prix_unitaire": float("inf")}, "prix_invalide"),
    ({"prix_unitaire": 0}, "prix_invalide"),
    ({"prix_unitaire": -1}, "prix_invalide"),
    ({"prix_unitaire": 10**1000}, "prix_invalide"),
    ({"prix_unitaire": "12.50"}, "prix_invalide"),
    ({"prix_unitaire": 0.0000001}, "precision_non_supportee"),
    ({"unite": None}, "unite_absente_ou_differente"),
    ({"unite": "m"}, "unite_absente_ou_differente"),
    ({"devise": "USD"}, "devise_non_supportee"),
    ({"date_effet": "20300601"}, "date_invalide"),
    ({"date_effet": "2030-02-30"}, "date_invalide"),
    ({"date_effet": "2030-06-02"}, "date_future"),
    ({"source_document": ""}, "source_document_invalide"),
    ({"source_document": "x\nsecret"}, "source_document_invalide"),
    ({"prix_vente": 400}, "source_invalide"),
])
def test_dernier_tarif_inutilisable_ne_reprend_pas_un_ancien(changement, raison):
    with pytest.raises(SelectionTarifRefusee) as exc:
        choisir([(0, entree()), (2, entree(**changement))])
    assert exc.value.raison == raison


def test_reference_absente_est_fallback_et_aucune_authenticite_inventee():
    r = choisir([(7, entree(source_document=None))])
    assert r["marquage_source"] == "FALLBACK_PRICE_BOOK" and r["source_document"] is None


@pytest.mark.parametrize("champ", ["materiau_id", "fournisseur_id"])
@pytest.mark.parametrize("corruption", ["absent", "vide", "type", "unicode"])
def test_identite_illisible_ne_permet_pas_repli_ancien_tarif(champ, corruption):
    derniere = entree(prix_unitaire=99)
    if corruption == "absent":
        del derniere[champ]
    else:
        derniere[champ] = {"vide": "", "type": None, "unicode": "\u202e"}[corruption]
    registre = [(0, entree()), (2, derniere)]
    avant = deepcopy(registre)
    with pytest.raises(SelectionTarifRefusee, match="source_invalide"):
        choisir(registre)
    assert registre == avant


@pytest.mark.parametrize("lignes", [[], [(2, entree(materiau_id="autre-fictif"))],
                                   [(2, entree(fournisseur_id="autre-fictif"))]])
def test_pas_de_prix_invente(lignes):
    with pytest.raises(SelectionTarifRefusee, match="tarif_absent"):
        choisir(lignes)


@pytest.mark.parametrize("lignes", [[(True, entree())], [(2, entree()), (2, entree())],
                                   [(3, entree()), (2, entree())], [(-1, entree())], [(2, None)]])
def test_rang_sql_invalide(lignes):
    with pytest.raises(SelectionTarifRefusee, match="source_invalide"):
        choisir(lignes)


def test_changement_rang_charge_et_empreinte_refuse():
    r = choisir()
    for lignes in [[(8, entree())], [(7, entree(prix_unitaire=13))]]:
        with pytest.raises(SelectionTarifRefusee, match="source_modifiee"):
            choisir(lignes, rang_attendu=7, empreinte_attendue=r["tarif_empreinte"])
    for kw in [{"rang_attendu": 7}, {"empreinte_attendue": r["tarif_empreinte"]},
               {"rang_attendu": True, "empreinte_attendue": r["tarif_empreinte"]}]:
        with pytest.raises(SelectionTarifRefusee, match="source_modifiee"):
            choisir(**kw)


def test_fournisseur_non_resolu_et_borne_source():
    for fournisseur in [None, {}, {**FOURNISSEUR, "fournisseur_id": "autre-fictif"}]:
        with pytest.raises(SelectionTarifRefusee, match="fournisseur_inconnu"):
            selectionner_tarif([(7, entree())], fournisseur, "materiau-fictif", "fournisseur-fictif",
                              "pi", "2030-06-01")
    with pytest.raises(SelectionTarifRefusee, match="sources_trop_volumineuses"):
        choisir([(n, entree()) for n in range(10001)])
