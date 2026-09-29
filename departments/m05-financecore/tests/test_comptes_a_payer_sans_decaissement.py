"""PLAN T4.15 : les comptes à payer n'écrivent JAMAIS de décaissement. Payer un fournisseur est de l'argent réel
(N5, Nathan ET le CPA, ADR-0009 §5) : rien, dans le code des comptes à payer, ne peut créer un DECAISSEMENT, une
PROVISION ni un ENCAISSEMENT, ni même toucher au registre des mouvements.

Trois preuves, de la plus structurelle à la plus concrète :
1. la garde AST `conformite.verifier_aucun_decaissement` passe sur le vrai paquet ET MORD : chaque violation
   injectée, dans le module des comptes à payer et dans les fonctions d'`outils.py` de ce chemin, est nommée ; hors de
   cette portée, rien n'est dit ;
2. aucun outil de M5 ne déplace de l'argent en plus de ceux d'avant (les seuls T3 sont les deux d'avant) ;
3. sur une base réelle, tout le parcours (réception par le bus, facture saisie, doublon refusé, lecture) laisse le
   registre des mouvements et celui des factures clients EXACTEMENT comme ils étaient (même tête de chaîne, même
   taille), avec un solde qui ne bouge pas.

Le piège est celui de T1.1-e (« aucun ENCAISSEMENT avant PAYEE ») appliqué au fournisseur. Fictif (AGENTS.md).
"""

from __future__ import annotations

import re
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
from m5_financecore import conformite

from opsys import contexte, evenements, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer_atomique

FICTIF = True
_RACINE_M5 = Path(__file__).resolve().parents[1]
_PAQUET = _RACINE_M5 / "src" / "m5_financecore"
DEPARTEMENT = "m05-financecore"
HORODATAGE = "2026-10-08T10:00:00-04:00"


# ---------------------------------------------------------------------------------- 1. la garde AST
def test_le_vrai_paquet_ne_touche_pas_aux_mouvements_dans_les_comptes_a_payer():
    assert conformite.verifier_aucun_decaissement(_PAQUET) == (True, "")


def test_la_garde_surveille_ce_qu_elle_dit_surveiller():
    """Un renommage ne doit pas la désarmer en silence : chaque fonction surveillée existe dans le vrai `outils.py`."""
    arbre_outils = (_PAQUET / "outils.py").read_text(encoding="utf-8")
    for nom in conformite._SURVEILLE_SANS_DECAISSEMENT["outils"]:
        assert re.search(rf"^def {re.escape(nom)}\(", arbre_outils, re.MULTILINE), nom
    assert conformite._SURVEILLE_SANS_DECAISSEMENT["comptes_a_payer"] is None, "le module entier"
    assert (_PAQUET / "comptes_a_payer.py").is_file()


def _garde(tmp_path, sources, surveille):
    for nom, contenu in sources.items():
        (tmp_path / f"{nom}.py").write_text(contenu, encoding="utf-8")
    return conformite.verifier_aucun_decaissement(tmp_path, surveille)


@pytest.mark.parametrize("ligne, attendu", [
    ("from . import registre", "importe registre.py"),
    ("from . import encodage, registre", "importe registre.py"),
    ("from .registre import Registre", "importe registre.py"),
    ("from m5_financecore.registre import enregistrer_mouvement", "importe registre.py"),
    ("import m5_financecore.registre", "importe registre.py"),
    ("enregistrer_mouvement(x, y)", "nomme enregistrer_mouvement"),
    ("registre_module.enregistrer_mouvement(x, y)", "nomme enregistrer_mouvement"),
    ("_registre_mouvements(None)", "nomme _registre_mouvements"),
    ("outils._etat_mouvements(None, reg)", "nomme _etat_mouvements"),
    ("nom = _NOM_REGISTRE_MOUVEMENTS", "nomme _NOM_REGISTRE_MOUVEMENTS"),
    ("stockage.maillons('d', 'principal')", "porte le texte 'principal'"),
    ("type_mouvement = 'DECAISSEMENT'", "porte le texte 'DECAISSEMENT'"),
    ("x = 'ENCAISSEMENT'", "porte le texte 'ENCAISSEMENT'"),
    ("x = 'PROVISION'", "porte le texte 'PROVISION'"),
    ("x = 'AJUSTEMENT'", "porte le texte 'AJUSTEMENT'"),
    ("x = {'type_entree': 'mouvement_enregistre'}", "porte le texte 'mouvement_enregistre'"),
    ("x = {'type_mouvement': 'AUTRE'}", "porte le texte 'type_mouvement'"),
    ("x = ('DECAISSEMENT',)", "porte le texte 'DECAISSEMENT'"),
])
def test_chaque_violation_injectee_dans_le_module_des_comptes_a_payer_est_nommee(tmp_path, ligne, attendu):
    source = f"def f(x, y, reg):\n    {ligne}\n"
    conforme, detail = _garde(tmp_path, {"comptes_a_payer": source}, {"comptes_a_payer": None})

    assert conforme is False and attendu in detail and "comptes_a_payer.py:2" in detail


def test_un_docstring_qui_mentionne_le_mot_n_est_pas_une_violation(tmp_path):
    source = '"""Aucun DECAISSEMENT, aucune PROVISION, jamais de mouvement_enregistre : payer est N5."""\n\nx = 1\n'

    assert _garde(tmp_path, {"comptes_a_payer": source}, {"comptes_a_payer": None}) == (True, "")


def test_dans_outils_seules_les_fonctions_du_chemin_sont_surveillees(tmp_path):
    source = (
        "def hors_chemin(x):\n    return registre_module.enregistrer_mouvement(x, 'DECAISSEMENT')\n\n"
        "def saisir_facture_fournisseur(x):\n    return x\n"
    )
    surveille = {"outils": ("saisir_facture_fournisseur",)}

    assert _garde(tmp_path, {"outils": source}, surveille) == (True, "")

    en_faute = source.replace("    return x\n", "    return registre_module.enregistrer_mouvement(x, 'DECAISSEMENT')\n")
    conforme, detail = _garde(tmp_path, {"outils": en_faute}, surveille)
    assert conforme is False
    assert "saisir_facture_fournisseur()" in detail and "enregistrer_mouvement" in detail and "DECAISSEMENT" in detail


def test_une_fonction_surveillee_qui_disparait_est_une_violation(tmp_path):
    conforme, detail = _garde(
        tmp_path, {"outils": "def autre():\n    return 1\n"}, {"outils": ("saisir_facture_fournisseur",)})

    assert conforme is False and "fonction surveillée introuvable : saisir_facture_fournisseur" in detail


def test_un_module_surveille_illisible_ou_absent_est_une_violation(tmp_path):
    assert conformite.verifier_aucun_decaissement(tmp_path, {"absent": None})[0] is False
    (tmp_path / "casse.py").write_text("def (:\n", encoding="utf-8")
    conforme, detail = conformite.verifier_aucun_decaissement(tmp_path, {"casse": None})
    assert conforme is False and "illisible" in detail


def _sur_les_vrais_fichiers(tmp_path, modifier):
    """Copie les vrais modules que la garde surveille (`comptes_a_payer.py`, `outils.py`, et, depuis T4.16, le
    calendrier fiscal, le cash libre, la mention et les modules du solde), y applique `modifier`, rend le verdict de
    la garde."""
    surveilles = set(conformite._SURVEILLE_SANS_DECAISSEMENT) | set(conformite._SURVEILLE_EN_LECTURE_SEULE)
    for nom in sorted(surveilles):
        (tmp_path / f"{nom}.py").write_text(modifier(nom, (_PAQUET / f"{nom}.py").read_text(encoding="utf-8")),
                                            encoding="utf-8")
    return conformite.verifier_aucun_decaissement(tmp_path)


def test_les_vrais_fichiers_copies_tels_quels_sont_conformes(tmp_path):
    assert _sur_les_vrais_fichiers(tmp_path, lambda _nom, texte: texte) == (True, "")


def test_un_decaissement_glisse_dans_la_vraie_saisie_est_attrape(tmp_path):
    def modifier(nom, texte):
        if nom != "outils":
            return texte
        ancre = (
            "    registre_cible = _registre_comptes_a_payer()\n"
            "    resultat, verdict = comptes_a_payer.saisir_facture_fournisseur("
        )
        assert ancre in texte
        piege = "    registre_module.enregistrer_mouvement({}, registre_module.Registre())\n"
        return texte.replace(ancre, piege + ancre, 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "saisir_facture_fournisseur()" in detail and "enregistrer_mouvement" in detail


def test_un_decaissement_glisse_dans_le_vrai_consommateur_est_attrape(tmp_path):
    def modifier(nom, texte):
        if nom != "outils":
            return texte
        ancre = "    maillon, deja_recue = resultat\n"
        assert ancre in texte
        return texte.replace(ancre, ancre + "    _registre_mouvements(None)\n", 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "_recevoir_reception_enregistree()" in detail and "_registre_mouvements" in detail


def test_un_import_du_registre_des_mouvements_dans_le_vrai_module_est_attrape(tmp_path):
    def modifier(nom, texte):
        if nom != "comptes_a_payer":
            return texte
        ancre = "from . import analyse, encodage, taxes, validation"
        assert ancre in texte
        return texte.replace(ancre, "from . import analyse, encodage, registre, taxes, validation")

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "comptes_a_payer.py" in detail and "importe registre.py" in detail


def test_un_type_de_mouvement_dans_le_vrai_module_est_attrape(tmp_path):
    def modifier(nom, texte):
        if nom != "comptes_a_payer":
            return texte
        return texte + '\n\ndef _piege():\n    return {"type_mouvement": "DECAISSEMENT", "montant": 1}\n'

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "DECAISSEMENT" in detail and "type_mouvement" in detail


# ------------------------------------------------------------------- 2. aucun outil ne déplace de l'argent en plus
def test_les_seuls_outils_t3_de_m5_sont_les_deux_d_avant_aucun_ne_paie_un_fournisseur():
    par_nom = {o.nom: o for o in m5_outils.outils()}

    assert {nom for nom, o in par_nom.items() if o.autonomie is Autonomie.T3} == {
        "m5_enregistrer_mouvement", "m5_enregistrer_paiement_facture"}
    for nom in ("m5_saisir_facture_fournisseur", "m5_lister_comptes_a_payer"):
        assert par_nom[nom].autonomie is not Autonomie.T3 and not par_nom[nom].frontiere_humaine, nom
    parlent_d_argent = {nom for nom in par_nom if re.search(r"(paye|paiement|decaisse|virement|rembours)", nom)}
    assert parlent_d_argent == {"m5_enregistrer_paiement_facture", "m5_lister_comptes_a_payer"}, (
        "aucun outil de paiement fournisseur : le paiement d'une facture CLIENT (d'avant) et la LECTURE des "
        "comptes à payer")
    assert par_nom["m5_lister_comptes_a_payer"].autonomie is Autonomie.T0


# ------------------------------------------------------------- 3. sur une base réelle, les mouvements ne bougent pas
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-sans-decaissement.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    yield url
    stockage.liberer()


def _etat_des_registres():
    with stockage.transaction():
        mouvements = m5_outils._registre_mouvements(None)
        factures = m5_outils._registre_factures(None)
        return {
            "mouvements": (mouvements.taille(), mouvements.tete()),
            "factures": (factures.taille(), factures.tete()),
        }


def _charge(evenement_id, po_id, gouttiere, vis):
    def ligne(materiau, demandee, recue, prix):
        return {"materiau_id": materiau, "quantite_demandee": demandee, "quantite_recue": recue,
                "prix_unitaire_prevu": prix, "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE", "ecart_prix_critique": None}
    return {"evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek", "chantier_id": "CH-1",
            "horodatage_reception": "2026-09-29T09:15:00-04:00", "verdict_reception": "RECEPTION_INFERIEURE",
            "statut_po": "partially_received", "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": None,
            "lignes": [ligne("gouttiere-5po", "60", gouttiere, "5.00"), ligne("vis-inox", "40", vis, "0.50")]}


def test_tout_le_parcours_laisse_les_mouvements_et_les_factures_clients_exactement_comme_avant(base_durable):
    dep = lire_manifeste(_RACINE_M5)
    par_nom = {o.nom: o for o in m5_outils.outils()}
    # un registre des mouvements DÉJÀ garni : 500.00 encaissés, pour que « rien ne bouge » veuille dire quelque chose
    ecrit = executer_atomique(par_nom["m5_enregistrer_mouvement"], {
        "montant": "500.00", "type_mouvement": "ENCAISSEMENT", "horodatage": HORODATAGE,
        "classe_retention": "STANDARD", "source": "test-fictif"})
    assert ecrit["ok"] and ecrit["resultat"]["accepte"], ecrit
    avant = _etat_des_registres()
    assert avant["mouvements"][0] == 1 and avant["factures"][0] == 0

    with stockage.transaction():
        for charge in (_charge("evt-1", "PO-1", "60", "0"), _charge("evt-2", "PO-2", "30", "20")):
            evenements.publier("m6.reception_enregistree", "m06-material-control", charge,
                               evenement_id=charge["evenement_id"])
    assert evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-09-29T12:00:00+00:00")["traites"] == 2
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne="admin.fictif", role="admin")):
        for numero, po, montant in (("F-1", "PO-1", "300.00"), ("F-2", "PO-2", "260.00")):
            reponse = executer_atomique(par_nom["m5_saisir_facture_fournisseur"], {
                "po_id": po, "fournisseur_id": "gentek", "numero_facture": numero, "date_facture": "2026-10-01",
                "montant_avant_taxes": montant, "total_facture": None, "horodatage": HORODATAGE})
            assert reponse["resultat"]["accepte"] is True, reponse
        doublon = executer_atomique(par_nom["m5_saisir_facture_fournisseur"], {
            "po_id": "PO-1", "fournisseur_id": "gentek", "numero_facture": "F-1", "date_facture": "2026-10-01",
            "montant_avant_taxes": "300.00", "total_facture": None, "horodatage": HORODATAGE})
        assert doublon["resultat"]["verdict"]["code"] == "REJ-AP-FACTURE-DOUBLON"
        lecture = executer_atomique(par_nom["m5_lister_comptes_a_payer"], {})
        assert lecture["resultat"]["accepte"] is True

    assert _etat_des_registres() == avant, "ni tête de chaîne ni taille : aucun mouvement, aucune facture cliente"
    with stockage.transaction():
        maillons = list(stockage.maillons(DEPARTEMENT, "comptes_a_payer"))
    assert {m["type_entree"] for m in maillons} == {"reception_recue", "facture_fournisseur_saisie"}
    assert "DECAISSEMENT" not in str(maillons) and "mouvement_enregistre" not in str(maillons)
    etat = executer_atomique(par_nom["m5_etat_tresorerie"], {"autorise_couts": True})["resultat"]
    assert etat["solde"] == "500.00" and etat["argent_disponible"] == "500.00", (
        "le solde et l'argent disponible ne bougent pas : payer un fournisseur est N5, et rien n'a été décaissé")
    # T4.16 : le CASH LIBRE, lui, retranche ce qui est dû aux fournisseurs (à payer : 344.93 + 298.94), sans rien
    # écrire
    a_payer = next(c for c in etat["cash_libre"]["composantes"] if c["id"] == "comptes_a_payer")
    assert a_payer["montant"] == "643.87" and etat["cash_libre"]["cash_libre"] is None
