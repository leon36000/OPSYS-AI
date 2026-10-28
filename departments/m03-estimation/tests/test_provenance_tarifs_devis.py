"""Snapshots de coûts fictifs : intégrité, rejeu et confinement des rendus clients."""

import io
from copy import deepcopy
from decimal import Decimal

import pytest
from m3_estimation import devis_durable as devis
from m3_estimation import soumission, soumission_pdf

FICTIF = True
HEURE = "2030-06-03T12:00:00+00:00"
MODELE = {"modele_id": "modele-fictif", "revision": 1, "source_id": "a" * 64,
          "titre": "Travaux fictifs", "description": "Description fictive", "clauses": "Clauses fictives"}
TARIF = {"reference_ligne": "devis-fictif-L0", "ligne_modele_id": "ligne-fictive",
         "materiau_id": "materiau-prive-fictif", "fournisseur_id": "fournisseur-prive-fictif",
         "tarif_rang": 17, "tarif_empreinte": "b" * 64, "cout_unitaire_decimal": "11.17",
         "devise": "CAD", "unite": "pi", "date_effet": "2030-05-01",
         "source_document": "document-prive-fictif.pdf", "marquage_source": "SOURCE_DECLAREE"}
PROVENANCE = {"modele_source": MODELE["source_id"], "lignes_source": "c" * 64,
              "lignes_revision": 1, "tarifs": [TARIF]}


def creer(journal, **kw):
    args = {"devis_id": "devis-fictif", "lead_id": "lead-fictif", "chantier_id": None,
            "lignes": [{"description": "Pose fictive", "quantite": "3", "unite": "pi",
                        "cout_unitaire": "11.17", "reference_besoin_materiau": None}],
            "taux_marge": "0.25", "horodatage": HEURE, "modele_soumission": deepcopy(MODELE),
            "provenance_tarifs": deepcopy(PROVENANCE), **kw}
    return devis.creer_devis(**args, registre_cible=journal)


def test_snapshot_rejeu_transitions_copies_et_cout_reel():
    journal, source = [], deepcopy(PROVENANCE)
    premier, refus = creer(journal, provenance_tarifs=source)
    assert refus is None and premier["prix_total"] == Decimal("41.88")
    assert premier["cout_total"] == Decimal("33.51")
    source["tarifs"][0]["cout_unitaire_decimal"] = "99.99"
    premier["provenance_tarifs"]["tarifs"].clear()
    rejoue, refus = creer(journal)
    assert refus is None and rejoue["provenance_tarifs"] == PROVENANCE and len(journal) == 1
    rejoue["provenance_tarifs"]["tarifs"][0]["fournisseur_id"] = "mutation-fictive"
    lu, refus = devis.lire_devis(journal, "devis-fictif")
    assert refus is None and lu["provenance_tarifs"] == PROVENANCE
    projete, refus = devis.projeter_devis(lu, "interne")
    assert refus is None
    projete["provenance_tarifs"]["tarifs"].clear()
    assert lu["provenance_tarifs"] == PROVENANCE
    accepte, refus = devis.marquer_devis_accepte("devis-fictif", "humain-fictif", HEURE, journal)
    assert refus is None and accepte["provenance_tarifs"] == PROVENANCE
    accepte["provenance_tarifs"]["tarifs"].clear()
    liste = devis.lister_devis(journal)
    assert liste[0]["provenance_tarifs"] == PROVENANCE
    liste[0]["provenance_tarifs"]["tarifs"].clear()
    assert journal[0]["provenance_tarifs"] == PROVENANCE


@pytest.mark.parametrize("champ,valeur", [("tarif_rang", 18), ("tarif_empreinte", "d" * 64),
    ("source_document", "autre-document-fictif"), ("fournisseur_id", "autre-fictif"),
    ("materiau_id", "autre-materiau-fictif"), ("ligne_modele_id", "autre-ligne")])
def test_provenance_differe_refuse_rejeu_meme_cout(champ, valeur):
    journal = []
    assert creer(journal)[1] is None
    modifie = deepcopy(PROVENANCE)
    modifie["tarifs"][0][champ] = valeur
    resultat, refus = creer(journal, provenance_tarifs=modifie)
    assert resultat is None and refus["code"] == "REJ-DEVIS-ID-DEJA-UTILISE"
    assert len(journal) == 1


def test_pas_de_rattachement_retroactif_ni_suppression_de_provenance():
    journal = []
    manuel, refus = creer(journal, provenance_tarifs=None)
    assert refus is None and "provenance_tarifs" not in manuel
    assert creer(journal)[1]["code"] == "REJ-DEVIS-ID-DEJA-UTILISE"
    source = []
    assert creer(source)[1] is None
    assert creer(source, provenance_tarifs=None)[1]["code"] == "REJ-DEVIS-ID-DEJA-UTILISE"


@pytest.mark.parametrize("champ,valeur", [
    ("reference_ligne", "devis-autre-L0"), ("reference_ligne", []),
    ("ligne_modele_id", "."), ("ligne_modele_id", True), ("ligne_modele_id", "a" * 101),
    ("materiau_id", ""), ("fournisseur_id", "\u202e"), ("tarif_rang", True), ("tarif_rang", -1),
    ("tarif_empreinte", "B" * 64), ("cout_unitaire_decimal", "11.18"),
    ("cout_unitaire_decimal", 11.17), ("cout_unitaire_decimal", "NaN"),
    ("cout_unitaire_decimal", "0"), ("cout_unitaire_decimal", "11.1700000"),
    ("devise", "USD"), ("unite", "m"), ("date_effet", "20300501"),
    ("date_effet", "2030-02-30"), ("date_effet", "2030-06-04"), ("date_effet", None),
    ("source_document", ""), ("source_document", "\x00"),
    ("marquage_source", "AUTHENTIFIE"), ("champ_invente", "x")])
def test_tarif_incoherent_refuse_sans_ecriture(champ, valeur):
    source, journal = deepcopy(PROVENANCE), []
    source["tarifs"][0][champ] = valeur
    resultat, refus = creer(journal, provenance_tarifs=source)
    assert resultat is None and refus["code"] == "REJ-CONTRAT-INVALIDE" and journal == []


@pytest.mark.parametrize("changement", [{"modele_source": "d" * 64}, {"lignes_source": "C" * 64},
    {"lignes_revision": True}, {"lignes_revision": 0}, {"lignes_revision": 1001},
    {"tarifs": []}, {"tarifs": [TARIF, TARIF]}, {"tarifs": (TARIF,)}, {"invente": "fictif"}])
def test_snapshot_ferme_et_couverture_exacte(changement):
    journal = []
    resultat, refus = creer(journal, provenance_tarifs={**deepcopy(PROVENANCE), **changement})
    assert resultat is None and refus["code"] == "REJ-CONTRAT-INVALIDE" and journal == []


def test_source_document_absente_exige_fallback_et_modele_requis():
    source = deepcopy(PROVENANCE)
    source["tarifs"][0]["source_document"] = None
    assert creer([], provenance_tarifs=source)[1]["code"] == "REJ-CONTRAT-INVALIDE"
    source["tarifs"][0]["marquage_source"] = "FALLBACK_PRICE_BOOK"
    assert creer([], provenance_tarifs=source)[1] is None
    assert creer([], modele_soumission=None)[1]["code"] == "REJ-CONTRAT-INVALIDE"
    assert creer([], horodatage="sans-fuseau-fictif")[1]["code"] == "REJ-CONTRAT-INVALIDE"


def test_plusieurs_lignes_et_doublons_de_reference_ou_modele():
    lignes = [{"description": f"Pose fictive {n}", "quantite": "1", "unite": "pi",
               "cout_unitaire": "11.17", "reference_besoin_materiau": None} for n in range(20)]
    source = {**deepcopy(PROVENANCE), "tarifs": [
        {**TARIF, "reference_ligne": f"devis-fictif-L{n}", "ligne_modele_id": f"ligne-{n}"}
        for n in range(20)]}
    resultat, refus = creer([], lignes=lignes, provenance_tarifs=source)
    assert refus is None and len(resultat["provenance_tarifs"]["tarifs"]) == 20
    assert resultat["cout_total"] == Decimal("223.40")
    for champ in ["reference_ligne", "ligne_modele_id"]:
        invalide = deepcopy(source)
        invalide["tarifs"][-1][champ] = invalide["tarifs"][0][champ]
        assert creer([], lignes=lignes, provenance_tarifs=invalide)[1]["code"] == "REJ-CONTRAT-INVALIDE"
    source["tarifs"].append({**TARIF, "reference_ligne": "devis-fictif-L20", "ligne_modele_id": "ligne-20"})
    assert creer([], lignes=lignes + [lignes[0]], provenance_tarifs=source)[1]["code"] == "REJ-CONTRAT-INVALIDE"


def test_stockage_sqlite_reouvert_rejeu_et_rollback(tmp_path, monkeypatch):
    from m3_estimation.outils import registre_devis_production

    from opsys import stockage

    url = f"sqlite:///{tmp_path / 'provenance-fictive.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        with pytest.raises(RuntimeError, match="rollback-fictif"), stockage.transaction():
            assert creer(registre_devis_production())[1] is None
            raise RuntimeError("rollback-fictif")
        assert len(registre_devis_production()) == 0
        with stockage.transaction():
            assert creer(registre_devis_production())[1] is None
        stockage.liberer()  # Rouvrir réellement le moteur; ne pas relire une liste mémoire.
        lu, refus = devis.lire_devis(registre_devis_production(), "devis-fictif")
        assert refus is None and lu["provenance_tarifs"] == PROVENANCE
        assert lu["lignes"][0]["cout_unitaire"] == Decimal("11.17")
        with stockage.transaction():
            rejoue, refus = creer(registre_devis_production())
            assert refus is None and rejoue == lu
            accepte, refus = devis.marquer_devis_accepte(
                "devis-fictif", "humain-fictif", HEURE, registre_devis_production())
            assert refus is None and accepte["provenance_tarifs"] == PROVENANCE
        stockage.liberer()
        lu, refus = devis.lire_devis(registre_devis_production(), "devis-fictif")
        assert refus is None and lu["statut"] == "accepte" and lu["provenance_tarifs"] == PROVENANCE
        assert len(registre_devis_production()) == 2
    finally:
        stockage.liberer()


def test_rendus_clients_employes_et_evenement_sans_provenance():
    source, refus = creer([])
    assert refus is None
    manuel, refus = creer([], provenance_tarifs=None)
    assert refus is None
    assert soumission.contenu_client(source) == soumission.contenu_client(manuel)
    assert soumission.generer_brouillon_html(source) == soumission.generer_brouillon_html(manuel)
    assert devis.projeter_devis(source, "employe") == devis.projeter_devis(manuel, "employe")
    assert devis.charge_evenement_devis_accepte(source) == devis.charge_evenement_devis_accepte(manuel)
    pypdf = pytest.importorskip("pypdf")
    octets, refus = soumission_pdf.generer_brouillon_pdf(source)
    assert refus is None and octets.startswith(b"%PDF-")
    assert (octets, refus) == soumission_pdf.generer_brouillon_pdf(manuel)
    texte = "\n".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(octets)).pages)
    for prive in [TARIF["fournisseur_id"], TARIF["materiau_id"], TARIF["source_document"],
                  TARIF["tarif_empreinte"], "33,51", "provenance_tarifs"]:
        assert prive not in texte
