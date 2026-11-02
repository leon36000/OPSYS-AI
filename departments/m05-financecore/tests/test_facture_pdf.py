"""PDF déterministe de la facture et de l'état de compte (M5-FACT-2), module PUR.

Le PDF est produit puis RELU (texte extrait par `pypdf`, dépendance de test) : on ne prouve pas que des octets existent,
on prouve ce qu'un lecteur y lit. Le rendu exige l'extra `soumission` (ReportLab 4.5.1) ; sans lui les rendus sont
sautés en local (jamais silencieusement en CI : `test_en_ci_la_brique_et_pypdf_sont_installees`). Données fictives.
"""

from __future__ import annotations

import hashlib
import io
import os
from datetime import date
from decimal import Decimal
from importlib import metadata
from pathlib import Path

import pytest
from m5_financecore import facturation, facturation_jalons, facture_pdf, taux_fiscaux
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
H = "2026-11-02T10:00:00-05:00"
HUMAIN = {"par": "nathan", "role": "nathan_owner"}
TAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"
ENTREPRISE = {
    "raison_sociale": "Entreprise Fictive Inc.",
    "adresse": ["123, rue Exemple", "Québec (Québec) A1A 1A1"],
    "numero_tps": "123456789 RT0001",
    "numero_tvq": "1234567890 TQ0001",
    "courriel": "facturation@example.test",
}
DESTINATAIRE = {"nom": "Client Fictif (œuvre « test »)", "adresse": ["45, avenue Exemple", "Lévis (Québec) B2B 2B2"]}


@pytest.fixture
def brique():
    installe, raison = facture_pdf.pdf_installe()
    if not installe:
        pytest.skip(raison)
    pytest.importorskip("pypdf")


def _taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(TAUX)
    assert erreurs == []
    return dictionnaire


def _jalons():
    return [
        {"libelle": "Acompte à l'acceptation", "declencheur": "acceptation", "pourcentage": "30"},
        {"libelle": "Mi-chantier", "declencheur": "chantier", "pourcentage": "40"},
        {"libelle": "Solde à la fin des travaux", "declencheur": "fin_travaux", "pourcentage": "30"},
    ]


def _monde(lignes_supplementaires=0):
    """(état du plan, état de la facture du jalon 1 émise et numérotée) : fabriqués par les vraies fonctions."""
    devis = {"devis_id": "D-1", "lead_id": "lead-1", "chantier_id": None, "prix_total": "10000.00"}
    plan, refus = facturation_jalons.construire_plan(
        devis, _jalons(), chantier_declare="CH-1", client_id="client-1", version=1, delai_defaut=30, humain=HUMAIN
    )
    assert refus is None
    plans = registre_module.Registre()
    facturation_jalons.ajouter_plan(plans, facturation_jalons.etat_plans([]), plan, H)
    etat_plan = facturation_jalons.etat_plans(plans.lire())["plans"][plan["plan_id"]]
    factures = registre_module.Registre()
    preparation, _ = facturation_jalons.preparer_facture_jalon(etat_plan, 1, [], travaux_termines=False)
    lignes = preparation["lignes"] + [
        {
            "description": f"Ligne supplémentaire {i}",
            "quantite": "2",
            "unite": "pi",
            "prix_unitaire": "1.50",
            "reference_ligne_devis": f"r{i}",
        }
        for i in range(lignes_supplementaires)
    ]
    facture_id = preparation["facture_id"]
    maillon, verdict = facturation.creer_facture_brouillon(
        facture_id,
        "CH-1",
        "D-1",
        "client-1",
        lignes,
        H,
        _taux(),
        factures,
        rattachement_plan=preparation["rattachement"],
    )
    assert verdict is None, verdict
    facturation.envoyer_facture(
        facture_id,
        H,
        factures,
        {"numero_facture": "F-001000", "sequence_facture": 1000, "echeance": "2026-12-02", "delai_paiement_jours": 30},
    )
    return etat_plan, facturation.etats_des_factures(factures)[0]


def _texte(octets):
    from pypdf import PdfReader

    lecteur = PdfReader(io.BytesIO(octets))
    texte = "\n".join(page.extract_text() for page in lecteur.pages).replace("\u00a0", " ")
    return " ".join(texte.split()), len(lecteur.pages)  # les retours à la ligne d'une cellule n'importent pas


def _rendu(langue="fr", entreprise=ENTREPRISE, destinataire=DESTINATAIRE, **kw):
    plan, etat = _monde(**kw)
    contenu, refus = facture_pdf.contenu_facture(etat, plan, entreprise, destinataire, langue)
    assert refus is None, refus
    octets, refus = facture_pdf.rendre(contenu)
    assert refus is None, refus
    return contenu, octets


# ------------------------------------------------------------------------------------------------ ce qu'on y lit
def test_le_pdf_francais_porte_les_montants_les_taxes_et_les_numeros_declares(brique):
    contenu, octets = _rendu()
    texte, pages = _texte(octets)
    assert octets.startswith(b"%PDF-") and pages == 1
    for attendu in (
        "Facture F-001000",
        "Entreprise Fictive Inc.",
        "123, rue Exemple",
        "N° TPS 123456789 RT0001",
        "N° TVQ 1234567890 TQ0001",
        "facturation@example.test",
        "Client Fictif (œuvre « test »)",
        "45, avenue Exemple",
        "Numéro de facture : F-001000",
        "Date d'émission : 2 novembre 2026",
        "Date d'échéance : 2 décembre 2026",
        "Net 30 jours",
        "Référence du contrat (devis) : D-1",
        "Jalon 1 de 3 — Acompte à l'acceptation",
        "Acompte à l'acceptation (jalon 1 de 3)",
        "3 000,00 $",
        "Sous-total avant taxes",
        "TPS (5 %)",
        "150,00 $",
        "TVQ (9,975 %)",
        "299,25 $",
        "Total",
        "3 449,25 $",
        "Récapitulatif du contrat",
        "10 000,00 $",
        "7 000,00 $",
        "Montants en dollars canadiens (CAD).",
        "Page 1",
    ):
        assert attendu in texte, attendu
    assert contenu["total"] == "3 449,25 $" and "Invoice" not in texte


def test_le_recapitulatif_compte_les_jalons_jusqu_a_celui_de_la_facture_inclus():
    plan, etat = _monde()
    contenu, _ = facture_pdf.contenu_facture(etat, plan, ENTREPRISE, DESTINATAIRE, "fr")
    assert contenu["recapitulatif"] == {
        "prix_contrat": "10 000,00 $",
        "facture_a_ce_jour": "3 000,00 $",
        "solde": "7 000,00 $",
    }
    deuxieme = {**etat, "jalon_rang": 2}
    contenu, _ = facture_pdf.contenu_facture(deuxieme, plan, ENTREPRISE, DESTINATAIRE, "fr")
    assert contenu["recapitulatif"]["facture_a_ce_jour"] == "7 000,00 $"
    assert contenu["recapitulatif"]["solde"] == "3 000,00 $"


def test_le_pdf_bilingue_porte_chaque_etiquette_dans_les_deux_langues(brique):
    _, octets = _rendu("bilingue")
    texte, _ = _texte(octets)
    for attendu in (
        "Facture / Invoice F-001000",
        "Date d'échéance / Due date : 2026-12-02",
        "Net 30 jours / Net 30 days",
        "Facturé à / Bill to",
        "Sous-total avant taxes / Subtotal before taxes",
        "TPS / GST (5 %)",
        "TVQ / QST (9,975 %)",
        "N° TPS / GST no. 123456789 RT0001",
        "Jalon 1 de 3 / Milestone 1 of 3",
        "Récapitulatif du contrat / Contract summary",
        "Page / Page 1",
    ):
        assert attendu in texte, attendu


def test_une_facture_payable_a_la_reception_le_dit():
    plan, etat = _monde()
    contenu, _ = facture_pdf.contenu_facture({**etat, "delai_paiement_jours": 0}, plan, ENTREPRISE, DESTINATAIRE, "fr")
    assert contenu["conditions"] == "Payable à la réception"


def test_sans_echeance_la_facture_ne_dit_ni_echeance_ni_conditions():
    plan, etat = _monde()
    sans = {k: v for k, v in etat.items() if k not in ("echeance", "delai_paiement_jours")}
    contenu, refus = facture_pdf.contenu_facture(sans, plan, ENTREPRISE, DESTINATAIRE, "fr")
    assert refus is None and contenu["echeance"] is None and contenu["conditions"] is None


# ------------------------------------------------------------------------------------------- déterminisme et scellé
def test_memes_entrees_memes_octets_et_meme_empreinte(brique):
    contenu_a, octets_a = _rendu()
    contenu_b, octets_b = _rendu()
    assert octets_a == octets_b and hashlib.sha256(octets_a).hexdigest() == hashlib.sha256(octets_b).hexdigest()
    assert facture_pdf.empreinte_contenu(contenu_a) == facture_pdf.empreinte_contenu(contenu_b)
    assert b"2026" in octets_a  # la date de création vient de l'émission de la facture, jamais de l'horloge
    assert _rendu("bilingue")[1] != octets_a


def test_la_date_de_creation_du_pdf_est_celle_de_l_emission_pas_de_l_horloge(brique):
    from pypdf import PdfReader

    _, octets = _rendu()
    meta = PdfReader(io.BytesIO(octets)).metadata
    assert str(meta.creation_date.date()) == "2026-11-02" and meta.author == "Entreprise Fictive Inc."


def test_le_pdf_ne_change_pas_apres_le_paiement(brique):
    plan, etat = _monde()
    avant, _ = facture_pdf.contenu_facture(etat, plan, ENTREPRISE, DESTINATAIRE, "fr")
    payee = {**etat, "statut": "PAYEE", "date_paiement": "2026-12-01T09:00:00-05:00", "approbateur": "nathan"}
    apres, refus = facture_pdf.contenu_facture(payee, plan, ENTREPRISE, DESTINATAIRE, "fr")
    assert refus is None and apres == avant
    assert facture_pdf.rendre(avant)[0] == facture_pdf.rendre(apres)[0]


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("montant_apres_taxes", D("3449.26")),
        ("montant_avant_taxes", D("3000.01")),
        ("numero_facture", "F-001001"),
        ("echeance", "2026-12-03"),
        ("date_envoi", "2026-11-03T10:00:00-05:00"),
    ],
)
def test_tout_changement_de_la_facture_change_l_empreinte_du_contenu(champ, valeur):
    plan, etat = _monde()
    base = facture_pdf.empreinte_contenu(facture_pdf.contenu_facture(etat, plan, ENTREPRISE, DESTINATAIRE, "fr")[0])
    autre, refus = facture_pdf.contenu_facture({**etat, champ: valeur}, plan, ENTREPRISE, DESTINATAIRE, "fr")
    assert refus is None and facture_pdf.empreinte_contenu(autre) != base


def test_le_scelle_est_rejouable_et_refuse_une_empreinte_differente():
    registre = registre_module.Registre()
    arguments = dict(type_entree="facture_pdf_scellee", cle="f|fr|abc", corps={"facture_id": "f"}, horodatage=H)
    premier, refus = facture_pdf.sceller(registre, empreinte_pdf="a" * 64, strict=True, **arguments)
    assert refus is None and premier["statut"] == "nouveau" and registre.taille() == 1
    rejeu, refus = facture_pdf.sceller(registre, empreinte_pdf="a" * 64, strict=True, **arguments)
    assert refus is None and rejeu["statut"] == "deja" and registre.taille() == 1
    _, refus = facture_pdf.sceller(registre, empreinte_pdf="b" * 64, strict=True, **arguments)
    assert refus["code"] == "REJ-PDF-SCELLE-DIFFERENT" and registre.taille() == 1
    autre_cle = dict(arguments, cle="f|bilingue|abc")
    assert facture_pdf.sceller(registre, empreinte_pdf="b" * 64, strict=True, **autre_cle)[1] is None
    assert registre.taille() == 2
    ecrit = registre.lire()[0]
    assert ecrit["empreinte_pdf"] == "a" * 64 and "pdf" not in {k for k in ecrit if k.endswith("octets")}


# -------------------------------------------------------------------------------------- donnée absente = blocage
@pytest.mark.parametrize(
    "retire,manque",
    [
        ("raison_sociale", "raison_sociale"),
        ("adresse", "adresse"),
        ("numero_tps", "numero_tps"),
        ("numero_tvq", "numero_tvq"),
    ],
)
def test_une_donnee_declaree_absente_bloque_et_dit_quoi_declarer(retire, manque):
    plan, etat = _monde()
    entreprise = {k: v for k, v in ENTREPRISE.items() if k != retire}
    contenu, refus = facture_pdf.contenu_facture(etat, plan, entreprise, DESTINATAIRE, "fr")
    assert contenu is None and refus["code"] == "REJ-PDF-ENTREPRISE-A-DECLARER"
    assert manque in refus["detail"] and "configuration.facturation.entreprise" in refus["detail"]
    assert "jamais inventés" in refus["detail"]


def test_tout_manque_est_liste_et_aucun_profil_dit_tout():
    plan, etat = _monde()
    _, refus = facture_pdf.contenu_facture(etat, plan, None, DESTINATAIRE, "fr")
    for champ in ("raison_sociale", "adresse", "numero_tps", "numero_tvq"):
        assert champ in refus["detail"]


@pytest.mark.parametrize(
    "numero",
    [
        "",
        "123456789",
        "123456789RT",
        "12345678 RT0001",
        "123456789 RT000",
        "123456789 TQ0001",
        "ABCDEFGHI RT0001",
        123456789,
        None,
        "123456789 RT0001; DROP",
    ],
)
def test_un_numero_de_tps_de_forme_invalide_est_refuse(numero):
    plan, etat = _monde()
    _, refus = facture_pdf.contenu_facture(etat, plan, {**ENTREPRISE, "numero_tps": numero}, DESTINATAIRE, "fr")
    assert refus["code"] == "REJ-PDF-ENTREPRISE-A-DECLARER" and "numero_tps" in refus["detail"]


@pytest.mark.parametrize(
    "numero,attendu",
    [
        ("123456789RT0001", "123456789 RT0001"),
        ("123456789 RT 0001", "123456789 RT0001"),
        ("123456789 rt0001", "123456789 RT0001"),
    ],
)
def test_le_numero_de_tps_est_normalise_a_l_affichage(numero, attendu):
    plan, etat = _monde()
    contenu, refus = facture_pdf.contenu_facture(etat, plan, {**ENTREPRISE, "numero_tps": numero}, DESTINATAIRE, "fr")
    assert refus is None and contenu["entreprise"]["numero_tps"] == attendu


def test_le_numero_d_une_taxe_absente_de_la_facture_n_est_pas_exige():
    entreprise, refus = facture_pdf.lire_entreprise({"raison_sociale": "X", "adresse": ["a"]}, ())
    assert refus is None and entreprise == {"raison_sociale": "X", "adresse": ["a"]}
    _, refus = facture_pdf.lire_entreprise({"raison_sociale": "X", "adresse": ["a"]}, ("tps_federale",))
    manque = refus["detail"].split(". ")[0]  # la consigne générale, elle, cite les deux numéros
    assert "numero_tps" in manque and "numero_tvq" not in manque


@pytest.mark.parametrize(
    "destinataire",
    [
        None,
        {},
        {"nom": "A"},
        {"nom": "A", "adresse": []},
        {"nom": "A", "adresse": ["1", "2", "3", "4", "5"]},
        {"nom": "  ", "adresse": ["a"]},
        {"nom": "A", "adresse": [5]},
        {"nom": "A", "adresse": "rue"},
        {"nom": "A", "adresse": ["a"], "extra": 1},
        {"nom": "x" * 121, "adresse": ["a"]},
        {"nom": "A", "adresse": ["x" * 81]},
    ],
)
def test_un_destinataire_incomplet_ou_demesure_est_refuse(destinataire):
    plan, etat = _monde()
    _, refus = facture_pdf.contenu_facture(etat, plan, ENTREPRISE, destinataire, "fr")
    assert refus["code"] == "REJ-PDF-DESTINATAIRE-INVALIDE"


@pytest.mark.parametrize("texte", ["Client ☃", "Client \U0001f600", "Ω", "Client‮", "emoji ​"])
def test_un_caractere_que_la_police_ne_dessine_pas_est_refuse_jamais_un_carre_silencieux(texte):
    plan, etat = _monde()
    _, refus = facture_pdf.contenu_facture(etat, plan, ENTREPRISE, {"nom": texte, "adresse": ["a"]}, "fr")
    assert (
        refus["code"] == "REJ-PDF-CARACTERE-NON-SUPPORTE" and "U+" in refus["detail"] and texte not in refus["detail"]
    )
    _, refus = facture_pdf.contenu_facture(etat, plan, {**ENTREPRISE, "raison_sociale": texte}, DESTINATAIRE, "fr")
    assert refus["code"] == "REJ-PDF-CARACTERE-NON-SUPPORTE"


def test_les_balises_et_les_controles_du_client_sont_des_donnees_jamais_interpretes(brique, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "s.txt").write_text("contenu-secret-fictif", encoding="utf-8")
    secret = "s.txt"
    nom = f'<img src="{secret}"/> <b>gras</b> &amp; <font size="99">x</font>\tY\nZ'
    plan, etat = _monde()
    contenu, refus = facture_pdf.contenu_facture(etat, plan, ENTREPRISE, {"nom": nom, "adresse": ["<i>a</i>"]}, "fr")
    assert refus is None
    octets, refus = facture_pdf.rendre(contenu)
    assert refus is None
    texte, _ = _texte(octets)
    assert "<b>gras</b>" in texte and "&amp;" in texte and str(secret) in texte and "<i>a</i>" in texte
    assert "contenu-secret-fictif" not in texte
    assert contenu["destinataire"]["nom"].count("\n") == 0 and "\t" not in contenu["destinataire"]["nom"]


@pytest.mark.parametrize("langue", ["", "en", "FR", None, "bilingual", 1])
def test_la_langue_est_fr_ou_bilingue(langue):
    plan, etat = _monde()
    _, refus = facture_pdf.contenu_facture(etat, plan, ENTREPRISE, DESTINATAIRE, langue)
    assert refus["code"] == "REJ-PDF-LANGUE-INVALIDE"


@pytest.mark.parametrize(
    "modif",
    [
        {"statut": "BROUILLON"},
        {"statut": "ANNULEE"},
        {"numero_facture": None},
        {"numero_facture": 7},
    ],
)
def test_le_pdf_ne_rend_que_la_facture_approuvee_et_numerotee(modif):
    plan, etat = _monde()
    _, refus = facture_pdf.contenu_facture({**etat, **modif}, plan, ENTREPRISE, DESTINATAIRE, "fr")
    assert refus["code"] == "REJ-PDF-FACTURE-NON-EMISE"
    sans_numero = {k: v for k, v in etat.items() if k != "numero_facture"}
    assert facture_pdf.contenu_facture(sans_numero, plan, ENTREPRISE, DESTINATAIRE, "fr")[1]["code"] == (
        "REJ-PDF-FACTURE-NON-EMISE"
    )


def test_une_date_d_envoi_sans_fuseau_ou_illisible_est_refusee():
    plan, etat = _monde()
    for date_envoi in ("2026-11-02T10:00:00", "n'importe quoi", None):
        _, refus = facture_pdf.contenu_facture({**etat, "date_envoi": date_envoi}, plan, ENTREPRISE, DESTINATAIRE, "fr")
        assert refus["code"] == "REJ-PDF-FACTURE-NON-EMISE"


def test_une_facture_de_jalon_sans_son_plan_est_refusee():
    plan, etat = _monde()
    _, refus = facture_pdf.contenu_facture(etat, None, ENTREPRISE, DESTINATAIRE, "fr")
    assert refus["code"] == "REJ-PDF-FACTURE-INTROUVABLE"
    _, refus = facture_pdf.contenu_facture(etat, {**plan, "plan_id": "autre"}, ENTREPRISE, DESTINATAIRE, "fr")
    assert refus["code"] == "REJ-PDF-FACTURE-INTROUVABLE"


# -------------------------------------------------------------------------------------------------- montants
def test_aucun_montant_n_est_arrondi_a_l_affichage():
    assert facture_pdf.formater_montant(D("1234.5")) == "1 234,50 $"
    assert facture_pdf.formater_montant(D("0.00")) == "0,00 $"
    assert facture_pdf.formater_montant(D("-0.00")) == "0,00 $"
    assert facture_pdf.formater_montant(D("999999999999.99")) == "999 999 999 999,99 $"
    for faux in (D("1.005"), D("NaN"), D("Infinity"), 1.5, "1.00", None, D("1E+20")):
        with pytest.raises(ValueError):
            facture_pdf.formater_montant(faux)


def test_une_facture_dont_un_montant_exigerait_un_arrondi_est_refusee():
    plan, etat = _monde()
    _, refus = facture_pdf.contenu_facture(
        {**etat, "montant_apres_taxes": D("3449.255")}, plan, ENTREPRISE, DESTINATAIRE, "fr"
    )
    assert refus["code"] == "REJ-PDF-MONTANT-INVALIDE" and "sans l'arrondir" in refus["detail"]
    ligne = dict(etat["lignes"][0], prix_unitaire=D("3000.001"))
    _, refus = facture_pdf.contenu_facture({**etat, "lignes": [ligne]}, plan, ENTREPRISE, DESTINATAIRE, "fr")
    assert refus["code"] == "REJ-PDF-MONTANT-INVALIDE"


def test_les_taxes_inconnues_sont_nommees_par_leur_nom_versionne_et_ne_demandent_aucun_numero():
    plan, etat = _monde()
    autre = {"id": "taxe_fictive", "nom": "Taxe fictive", "version": "v1", "taux": "0.01", "montant": D("30.00")}
    contenu, refus = facture_pdf.contenu_facture(
        {**etat, "taxes": [autre]}, plan, {"raison_sociale": "X", "adresse": ["a"]}, DESTINATAIRE, "fr"
    )
    assert refus is None and contenu["taxes"][0]["libelle"] == "Taxe fictive" and contenu["taxes"][0]["taux"] == "1 %"


# ----------------------------------------------------------------------------------------- plusieurs pages, brique
def test_une_longue_facture_tient_sur_plusieurs_pages_et_garde_ses_totaux_et_son_entete_de_table(brique):
    contenu, octets = _rendu(lignes_supplementaires=70)
    texte, pages = _texte(octets)
    assert pages >= 2
    assert "Ligne supplémentaire 69" in texte and texte.count("Description") >= 2  # l'entête de table se répète
    assert "Page 2" in texte and "Facture F-001000" in texte
    total = D("3000.00") + 70 * D("3.00")
    assert contenu["sous_total"] == facture_pdf.formater_montant(total)


def test_sans_la_brique_le_refus_dit_quoi_installer_et_ne_rend_aucun_pdf(monkeypatch):
    def absent(nom):
        raise metadata.PackageNotFoundError(nom)

    monkeypatch.setattr(facture_pdf.metadata, "version", absent)
    assert facture_pdf.pdf_installe() == (False, "reportlab absent")
    contenu = {"type": "facture"}
    octets, refus = facture_pdf.rendre(contenu)
    assert octets is None and refus["code"] == "REJ-PDF-BRIQUE-ABSENTE" and "opsys-ai[soumission]" in refus["detail"]
    monkeypatch.setattr(facture_pdf.metadata, "version", lambda nom: "3.0.0")
    assert facture_pdf.pdf_installe() == (False, "reportlab 3.0.0 trouvé, 4.5.1 exigé")


def test_une_erreur_de_la_brique_devient_un_verdict_sans_son_message(brique, monkeypatch):
    plan, etat = _monde()
    contenu, _ = facture_pdf.contenu_facture(etat, plan, ENTREPRISE, DESTINATAIRE, "fr")

    def casse(_contenu):
        raise RuntimeError("Client Fictif secret dans le message")

    monkeypatch.setattr(facture_pdf, "_rendre_facture", casse)
    octets, refus = facture_pdf.rendre(contenu)
    assert octets is None and refus["code"] == "REJ-PDF-RENDU-IMPOSSIBLE" and "secret" not in refus["detail"]


def test_en_ci_la_brique_et_pypdf_sont_installees():
    if not os.environ.get("CI"):
        pytest.skip("garde de CI seulement")
    assert facture_pdf.pdf_installe()[0] is True
    import pypdf  # noqa: F401


# ------------------------------------------------------------------------------------------------ état de compte
def _etats_pour_etat_de_compte():
    base = {"client_id": "client-1", "taxes": [], "date_envoi": "2026-10-01T09:00:00-04:00"}
    return [
        {
            **base,
            "facture_id": "f1",
            "numero_facture": "F-000001",
            "statut": "ENVOYEE",
            "echeance": "2026-10-31",
            "montant_apres_taxes": D("1149.75"),
        },
        {
            **base,
            "facture_id": "f2",
            "numero_facture": "F-000002",
            "statut": "PAYEE",
            "echeance": "2026-10-31",
            "montant_apres_taxes": D("689.85"),
            "date_envoi": "2026-09-15T09:00:00-04:00",
        },
        {
            **base,
            "facture_id": "f3",
            "numero_facture": "F-000003",
            "statut": "ENVOYEE",
            "echeance": "2026-12-15",
            "montant_apres_taxes": D("500.00"),
            "date_envoi": "2026-11-15T09:00:00-05:00",
        },
        {**base, "facture_id": "f4", "statut": "BROUILLON", "montant_apres_taxes": D("99.00")},
        {
            **base,
            "facture_id": "f5",
            "numero_facture": "F-000005",
            "statut": "ANNULEE",
            "montant_apres_taxes": D("77.00"),
        },
        {
            **base,
            "facture_id": "f6",
            "client_id": "client-2",
            "numero_facture": "F-000006",
            "statut": "ENVOYEE",
            "echeance": "2026-10-31",
            "montant_apres_taxes": D("5.00"),
        },
    ]


def test_l_etat_de_compte_calcule_solde_credits_et_retard_a_la_date_donnee(brique):
    contenu, refus = facture_pdf.contenu_etat_compte(
        "client-1",
        _etats_pour_etat_de_compte(),
        {"f1": D("149.75")},
        date(2026, 11, 20),
        ENTREPRISE,
        DESTINATAIRE,
        "fr",
        H,
    )
    assert refus is None
    assert [ligne["facture"] for ligne in contenu["lignes"]] == ["F-000002", "F-000001", "F-000003"]
    f2, f1, f3 = contenu["lignes"]
    assert (f2["statut"], f2["paye"], f2["solde"]) == ("Payée", "689,85 $", "0,00 $")
    assert (f1["statut"], f1["credits"], f1["solde"]) == ("En retard de 20 j", "149,75 $", "1 000,00 $")
    assert (f3["statut"], f3["solde"]) == ("À payer", "500,00 $")
    # total facturé 2339.60 ; payé 689.85 ; dû (1149.75 - 149.75) + 500.00 = 1500.00 ; en retard 1000.00
    assert contenu["totaux"] == {
        "facture": "2 339,60 $",
        "paye": "689,85 $",
        "du": "1 500,00 $",
        "retard": "1 000,00 $",
    }
    octets, refus = facture_pdf.rendre(contenu)
    assert refus is None
    texte, _ = _texte(octets)
    for attendu in (
        "État de compte",
        "Au 20 novembre 2026",
        "En retard de 20 j",
        "Solde dû",
        "1 500,00 $",
        "dont en retard",
    ):
        assert attendu in texte, attendu
    assert "F-000006" not in texte and "99,00" not in texte  # l'autre client et le brouillon n'y sont pas


def test_l_etat_de_compte_est_deterministe_et_dependant_de_la_date_dite(brique):
    arguments = ("client-1", _etats_pour_etat_de_compte(), {}, date(2026, 11, 20), ENTREPRISE, DESTINATAIRE, "fr", H)
    a, _ = facture_pdf.contenu_etat_compte(*arguments)
    b, _ = facture_pdf.contenu_etat_compte(*arguments)
    assert facture_pdf.rendre(a)[0] == facture_pdf.rendre(b)[0]
    avant_retard, _ = facture_pdf.contenu_etat_compte(
        "client-1", _etats_pour_etat_de_compte(), {}, date(2026, 10, 31), ENTREPRISE, DESTINATAIRE, "fr", H
    )
    assert avant_retard["totaux"]["retard"] == "0,00 $"  # l'échéance du 31 octobre n'est pas encore dépassée
    assert facture_pdf.empreinte_contenu(a) != facture_pdf.empreinte_contenu(avant_retard)


def test_un_etat_de_compte_sans_facture_emise_ou_sans_profil_est_refuse():
    _, refus = facture_pdf.contenu_etat_compte(
        "client-9", _etats_pour_etat_de_compte(), {}, date(2026, 11, 20), ENTREPRISE, DESTINATAIRE, "fr", H
    )
    assert refus["code"] == "REJ-PDF-ETAT-COMPTE-VIDE"
    _, refus = facture_pdf.contenu_etat_compte(
        "client-1", _etats_pour_etat_de_compte(), {}, date(2026, 11, 20), {"raison_sociale": "X"}, DESTINATAIRE, "fr", H
    )
    assert refus["code"] == "REJ-PDF-ENTREPRISE-A-DECLARER" and "adresse" in refus["detail"]
    _, refus = facture_pdf.contenu_etat_compte(
        "client-1", _etats_pour_etat_de_compte(), {}, date(2026, 11, 20), ENTREPRISE, None, "fr", H
    )
    assert refus["code"] == "REJ-PDF-DESTINATAIRE-INVALIDE"
