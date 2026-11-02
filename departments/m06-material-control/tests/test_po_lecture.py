"""C3 — LIRE et PILOTER les bons de commande : avant, aucun outil ne listait ni ne lisait un PO, et quatre statuts
(`pending_admin_review`, `invoiced`, `closed`, `disputed`) n'avaient aucun outil.

  - `m6_lister_po` / `m6_lire_po` : lectures (N0) réservées à l'admin (ou à un agent / la console, sans identité
    d'appareil) ; projection par LISTE BLANCHE de champs, pages sans troncature, « en retard » par rapport à un jour
    dit ;
    aucune écriture, aucun événement ;
  - `m6_changer_statut_po` : revue demandée, litige, facturé, fermé, avec motif (N3, décision de personne) ;
  - les attentes de l'admin : PO à approuver, PO en retard ;
  - l'écart de matériaux critique porte le message imposé de Nathan et jamais le mot « vol ».

Vrais outils sur une base SQLite migrée ; données fictives (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import json

import pytest
from m6_material_control import bons_commande, po_lecture, variance_chantier
from m6_material_control import outils as outils_mod
from m6_material_control.outils import outils

from opsys import contexte, evenements, identite, stockage
from opsys.outils import Niveau, executer_atomique

FICTIF = True
HORO = "2026-11-02T10:00:00-05:00"
DEPT = "m06-material-control"
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
EMPLOYE = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
MESSAGE_IMPOSE = (
    "Écart matériaux critique — validation admin requise. Causes possibles : erreur d'estimation, changement terrain, "
    "perte, bris, mauvaise saisie, retour non déclaré ou usage non expliqué."
)


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def m6(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
    return {o.nom: o for o in outils()}


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _appeler(m6, nom, arguments, identite_appelante=None):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        return executer_atomique(m6[nom], arguments)


def _ligne(materiau="REV-FICTIF", net=10.0, unite="feuille"):
    return {"materiau_id": materiau, "designation": None, "unite": unite, "unite_source": "declaree",
            "quantite_nette": net, "facteur_perte": None, "quantite_demandee": net, "verdict_prix": "PRIX_LIVRE",
            "prix_unitaire_prevu": 5.0, "devise_prevue": "CAD", "montant_ligne_prevu": net * 5.0,
            "prix_unite_confirmee": True}


def _creer_po(po_id, fournisseur="f-un", chantier="CH-1", devis="D-1", statut="draft", date_requise="2026-11-10",
              mode="ramassage", **plus):
    """Un PO commandable écrit au registre, au statut voulu (`transition_po` par la table légale)."""
    maillon = {"type_entree": "po_cree", "statut": "draft", "po_id": po_id, "chantier_id": chantier,
               "fournisseur_id": fournisseur, "horodatage": HORO, "devis_id": devis, "date_requise": date_requise,
               "mode_livraison": mode, "lieu_livraison": None, "ville": "Repentigny", "notes": None,
               "lignes": [_ligne()], "montant_total_prevu": 50.0, "provenance_prix_lignes": [], **plus}
    with stockage.transaction():
        registre = stockage.maillons(DEPT, "bons_commande")
        registre.append(maillon)
        chemin = {"draft": [], "approved": ["approved"], "email_ready": ["approved", "email_ready"],
                  "sent_to_supplier": ["approved", "email_ready", "sent_to_supplier"],
                  "supplier_confirmed": ["approved", "email_ready", "sent_to_supplier", "supplier_confirmed"],
                  "cancelled": ["cancelled"]}[statut]
        for cible in chemin:
            registre.append({"type_entree": "transition_po", "po_id": po_id, "statut": cible, "horodatage": HORO})


def _fournisseur(m6, identifiant="f-un", nom="Fournisseur Un (fictif)"):
    _ok(executer_atomique(m6["m6_enregistrer_fournisseur"], {
        "fournisseur_id": identifiant, "nom": nom, "horodatage": HORO,
        "courriel_commande": f"{identifiant}@exemple-fictif.test", "telephone": "514-555-0100"}))


def _registre():
    with stockage.transaction():
        return list(stockage.maillons(DEPT, "bons_commande"))


def _nb_evenements():
    from sqlalchemy import func, select

    from opsys.stockage.schema import EVENEMENTS_SORTANTS

    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one()


# =========================================================================================
# 1. Lister : filtres, comptes, pages complètes
# =========================================================================================
def test_la_liste_donne_une_page_sans_troncature_et_les_comptes_par_statut(m6):
    _fournisseur(m6)
    for i in range(30):
        _creer_po(f"PO-{i:02d}", statut="draft" if i % 3 else "approved")

    vues = []
    depart = 0
    while depart is not None:
        page = _ok(_appeler(m6, "m6_lister_po", {"depart": depart, "limite": 7}, ADMIN))["resultat"]
        vues += [p["po_id"] for p in page["pos"]]
        assert page["total"] == 30 and len(page["pos"]) <= 7
        depart = page["suivant"]

    assert vues == [f"PO-{i:02d}" for i in range(30)], "chaque PO une fois, dans l'ordre, sans saut"
    assert page["comptes"] == {"approved": 10, "draft": 20}


@pytest.mark.parametrize("filtre,attendus", [
    ({"statut": "approved"}, ["PO-B"]),
    ({"fournisseur_id": "f-deux"}, ["PO-C"]),
    ({"chantier_id": "CH-9"}, ["PO-C"]),
    ({"devis_id": "D-2"}, ["PO-B"]),
])
def test_les_filtres_restreignent_la_liste_et_les_comptes_disent_tout(m6, filtre, attendus):
    _fournisseur(m6)
    _creer_po("PO-A")
    _creer_po("PO-B", statut="approved", devis="D-2")
    _creer_po("PO-C", fournisseur="f-deux", chantier="CH-9")

    page = _ok(_appeler(m6, "m6_lister_po", filtre, ADMIN))["resultat"]

    assert [p["po_id"] for p in page["pos"]] == attendus and page["total"] == len(attendus)
    assert sum(page["comptes"].values()) == 3, "les comptes par statut sont ceux de TOUS les PO"


def test_en_retard_veut_dire_envoye_et_date_requise_depassee_a_un_jour_dit(m6):
    _creer_po("PO-RETARD", statut="sent_to_supplier", date_requise="2026-11-05")
    _creer_po("PO-AVANT", statut="sent_to_supplier", date_requise="2026-11-20")
    _creer_po("PO-BROUILLON", statut="draft", date_requise="2026-11-01")
    _creer_po("PO-ANNULE", statut="cancelled", date_requise="2026-11-01")

    page = _ok(_appeler(m6, "m6_lister_po", {"en_retard": True, "aujourd_hui": "2026-11-12"}, ADMIN))["resultat"]

    assert [p["po_id"] for p in page["pos"]] == ["PO-RETARD"]
    tous = _ok(_appeler(m6, "m6_lister_po", {"aujourd_hui": "2026-11-12"}, ADMIN))["resultat"]["pos"]
    assert {p["po_id"]: p["en_retard"] for p in tous} == {
        "PO-ANNULE": False, "PO-AVANT": False, "PO-BROUILLON": False, "PO-RETARD": True}
    sans_jour = _ok(_appeler(m6, "m6_lister_po", {}, ADMIN))["resultat"]["pos"]
    assert {p["en_retard"] for p in sans_jour} == {None}, "sans jour dit, « en retard » n'est pas évalué"
    assert _refus(_appeler(m6, "m6_lister_po", {"en_retard": True}, ADMIN)) == "REJ-PO-LECTURE-JOUR-REQUIS"


def test_un_jour_de_lecture_invalide_est_refuse(m6):
    for mauvais in ("demain", "2026-13-01", "2026-11-12T10:00:00"):
        assert _refus(_appeler(m6, "m6_lister_po", {"aujourd_hui": mauvais}, ADMIN)) == "REJ-PO-LECTURE-JOUR-INVALIDE"


# =========================================================================================
# 2. Lire : tout ce qu'il faut pour décider, rien de plus
# =========================================================================================
def test_la_lecture_donne_lignes_courriel_historique_et_livraisons_cumulees(m6):
    _fournisseur(m6)
    _creer_po("PO-LU", statut="sent_to_supplier",
              courriel={"objet": "Commande matériaux — PO-LU", "destinataire": "f-un@exemple-fictif.test",
                        "corps": "Bonjour", "repli_manuel_requis": False, "empreinte": "e" * 64})
    with stockage.transaction():
        registre = stockage.maillons(DEPT, "bons_commande")
        registre.append({"type_entree": "transition_po", "po_id": "PO-LU", "statut": "partially_received",
                         "horodatage": "2026-11-06T09:00:00-05:00", "verdict_reception": "RECEPTION_INFERIEURE",
                         "livraison": {"empreinte": "f" * 64, "horodatage": "2026-11-06T08:00:00-05:00",
                                       "lignes": [{"materiau_id": "REV-FICTIF", "quantite_recue": "4"}]}})

    po = _ok(_appeler(m6, "m6_lire_po", {"po_id": "PO-LU"}, ADMIN))["resultat"]

    assert po["statut"] == "partially_received" and po["fournisseur_nom"] == "Fournisseur Un (fictif)"
    assert [h["statut"] for h in po["historique"]] == ["approved", "email_ready", "sent_to_supplier",
                                                       "partially_received"]
    assert po["historique"][-1]["livraison"]["lignes"] == [{"materiau_id": "REV-FICTIF", "quantite_recue": "4"}]
    assert po["reception_cumulee"]["lignes"] == [{"materiau_id": "REV-FICTIF", "quantite_demandee": "10.0",
                                                  "quantite_recue_cumulee": "4", "ecart_cumule": "-6.0"}]
    assert po["courriel"]["destinataire"] == "f-un@exemple-fictif.test" and po["commandable"] is True
    assert po["lignes"][0]["unite"] == "feuille"


def test_la_projection_est_une_liste_blanche_aucun_contact_dans_la_liste_ni_champ_inconnu(m6):
    _fournisseur(m6)
    _creer_po("PO-FUITE", statut="sent_to_supplier", champ_interne_inconnu="ne-doit-pas-sortir",
              courriel={"objet": "o", "destinataire": "f-un@exemple-fictif.test", "corps": "b",
                        "repli_manuel_requis": False, "empreinte": "e" * 64})

    liste = json.dumps(_ok(_appeler(m6, "m6_lister_po", {}, ADMIN)), ensure_ascii=False)
    detail = json.dumps(_ok(_appeler(m6, "m6_lire_po", {"po_id": "PO-FUITE"}, ADMIN)), ensure_ascii=False)

    for texte in (liste, detail):
        assert "ne-doit-pas-sortir" not in texte and "514-555-0100" not in texte
    assert "f-un@exemple-fictif.test" not in liste, "l'adresse de commande n'est que dans le détail"
    assert "f-un@exemple-fictif.test" in detail


def test_un_po_ancien_se_lit_et_dit_ce_qui_lui_manque(m6):
    ancien = {"type_entree": "po_cree", "statut": "draft", "po_id": "PO-ANCIEN", "chantier_id": "CH-1",
              "fournisseur_id": "f-un", "horodatage": HORO, "montant_total_prevu": 10.0,
              "lignes": [{"materiau_id": "REV-FICTIF", "quantite_demandee": 1.0, "verdict_prix": "PRIX_LIVRE",
                          "prix_unitaire_prevu": 10.0, "devise_prevue": "CAD", "montant_ligne_prevu": 10.0}]}
    with stockage.transaction():
        stockage.maillons(DEPT, "bons_commande").append(ancien)

    po = _ok(_appeler(m6, "m6_lire_po", {"po_id": "PO-ANCIEN"}, ADMIN))["resultat"]

    assert po["commandable"] is False
    assert set(po["manques"]) == {"date_requise", "mode_livraison", "unite:REV-FICTIF"}


def test_lire_un_po_inconnu_est_un_refus_nomme(m6):
    assert _refus(_appeler(m6, "m6_lire_po", {"po_id": "PO-INCONNU"}, ADMIN)) == "REJ-PO-INTROUVABLE"


# =========================================================================================
# 3. Qui lit : l'admin seulement ; aucune écriture
# =========================================================================================
@pytest.mark.parametrize("appelant", [EMPLOYE, VENDEUR])
@pytest.mark.parametrize("outil,arguments", [("m6_lister_po", {}), ("m6_lire_po", {"po_id": "PO-A"})])
def test_un_employe_ou_un_vendeur_ne_lit_aucun_po(m6, appelant, outil, arguments):
    _creer_po("PO-A")

    assert _refus(_appeler(m6, outil, arguments, appelant)) == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_une_identite_d_appareil_revoquee_ne_lit_rien(m6):
    _creer_po("PO-A")
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")

    assert _refus(_appeler(m6, "m6_lister_po", {}, ADMIN)) == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_lire_et_lister_n_ecrivent_rien_ni_registre_ni_evenement(m6):
    _fournisseur(m6)
    _creer_po("PO-A", statut="sent_to_supplier")
    avant, evenements_avant = _registre(), _nb_evenements()

    _ok(_appeler(m6, "m6_lister_po", {"aujourd_hui": "2026-12-01", "en_retard": True}, ADMIN))
    _ok(_appeler(m6, "m6_lire_po", {"po_id": "PO-A"}, ADMIN))

    assert _registre() == avant and _nb_evenements() == evenements_avant


def test_les_lectures_sont_n0_et_les_statuts_en_n3():
    par_nom = {o.nom: o for o in outils()}
    assert par_nom["m6_lister_po"].niveau_effectif is Niveau.N0 and par_nom["m6_lire_po"].niveau_effectif is Niveau.N0
    assert par_nom["m6_changer_statut_po"].niveau_effectif is Niveau.N3


# =========================================================================================
# 4. Piloter : les quatre statuts sans outil
# =========================================================================================
def _changer(m6, po_id, cible, motif="Décision de l'admin"):
    return executer_atomique(m6["m6_changer_statut_po"], {
        "po_id": po_id, "statut_cible": cible, "motif": motif, "horodatage": HORO})


def test_un_po_recu_se_facture_puis_se_ferme_et_chaque_pas_garde_son_motif(m6):
    _creer_po("PO-F", statut="sent_to_supplier")
    with stockage.transaction():
        stockage.maillons(DEPT, "bons_commande").append(
            {"type_entree": "transition_po", "po_id": "PO-F", "statut": "received", "horodatage": HORO,
             "verdict_reception": "CONFORME"})

    assert _ok(_changer(m6, "PO-F", "invoiced", "Facture 1234 rapprochée par M5"))["po"]["statut"] == "invoiced"
    assert _ok(_changer(m6, "PO-F", "closed", "Payé et fermé"))["po"]["statut"] == "closed"

    historique = [m for m in _registre() if m.get("po_id") == "PO-F" and m.get("motif_statut")]
    assert [(m["statut"], m["motif_statut"]) for m in historique] == [
        ("invoiced", "Facture 1234 rapprochée par M5"), ("closed", "Payé et fermé")]


def test_un_litige_s_ouvre_depuis_un_po_envoye_ou_recu_et_la_revue_se_demande_depuis_un_brouillon(m6):
    _creer_po("PO-L", statut="sent_to_supplier")
    _creer_po("PO-R", statut="draft")

    assert _ok(_changer(m6, "PO-L", "disputed", "Livraison contestée"))["po"]["statut"] == "disputed"
    assert _ok(_changer(m6, "PO-R", "pending_admin_review",
                        "Montant à valider"))["po"]["statut"] == "pending_admin_review"


@pytest.mark.parametrize("depart,cible", [("draft", "invoiced"), ("draft", "closed"), ("approved", "disputed")])
def test_une_transition_illegale_est_refusee_sans_rien_ecrire(m6, depart, cible):
    _creer_po("PO-X", statut=depart)
    avant = _registre()

    assert _refus(_changer(m6, "PO-X", cible)) == "REJ-PO-TRANSITION-ILLEGALE"
    assert _registre() == avant


def test_le_motif_est_requis_et_les_autres_statuts_ne_se_pilotent_pas_ici(m6):
    _creer_po("PO-M", statut="sent_to_supplier")

    assert _refus(_changer(m6, "PO-M", "disputed", motif="   ")) == "REJ-PO-MOTIF-VIDE"
    assert _changer(m6, "PO-M", "received")["ok"] is False, "received ne se pilote pas : il vient de la réception"
    assert bons_commande.changer_statut("PO-M", "approved", "x", HORO, [])[1]["code"] == "REJ-PO-STATUT-NON-PILOTABLE"


# =========================================================================================
# 5. Les attentes de l'admin
# =========================================================================================
def _attentes():
    with stockage.transaction():
        return outils_mod.attentes()


def test_un_po_a_approuver_est_une_attente_n3_avec_ce_qui_manque_s_il_n_est_pas_commandable(m6):
    _creer_po("PO-OK", statut="draft")
    ancien = {"type_entree": "po_cree", "statut": "draft", "po_id": "PO-VIEUX", "chantier_id": "CH-1",
              "fournisseur_id": "f-un", "horodatage": HORO, "montant_total_prevu": 1.0,
              "lignes": [{"materiau_id": "X", "quantite_demandee": 1.0, "verdict_prix": "PRIX_LIVRE",
                          "prix_unitaire_prevu": 1.0, "devise_prevue": "CAD", "montant_ligne_prevu": 1.0}]}
    with stockage.transaction():
        stockage.maillons(DEPT, "bons_commande").append(ancien)

    par_id = {a["id"]: a for a in _attentes() if a["type"] == "po_a_approuver"}

    assert set(par_id) == {"PO-OK", "PO-VIEUX"}
    assert par_id["PO-OK"]["niveau"] == "N3" and par_id["PO-OK"]["action_proposee"] == "m6_approuver_po"
    assert "incomplet" in par_id["PO-VIEUX"]["resume"] and "refaire" in par_id["PO-VIEUX"]["action_proposee"]


def test_un_po_deja_approuve_n_est_plus_a_approuver(m6):
    _creer_po("PO-AP", statut="approved")

    assert not [a for a in _attentes() if a["type"] == "po_a_approuver"]


# =========================================================================================
# 6. Le message imposé pour un écart critique
# =========================================================================================
def test_le_message_impose_est_verbatim_et_ne_dit_jamais_vol():
    assert variance_chantier.MESSAGE_ECART_CRITIQUE == MESSAGE_IMPOSE
    assert "vol" not in variance_chantier.MESSAGE_ECART_CRITIQUE.lower().replace("involontaire", "")
    mots = {m.strip(".,:—").lower() for m in variance_chantier.MESSAGE_ECART_CRITIQUE.split()}
    assert "vol" not in mots and "voleur" not in mots and "vole" not in mots


def test_l_evaluation_d_une_variance_critique_porte_le_message_impose_et_une_non_critique_non(m6):
    besoin = [{"materiau_id": "REV-FICTIF", "quantite_estimee": 10.0, "unite": "feuille"}]
    critique = _ok(_appeler(m6, "m6_evaluer_variance_chantier", {
        "chantier_id": "CH-1", "besoins_estimes": besoin, "seuil_pourcentage": 0.30,
        "lignes_declarees": [{"type_ligne": "prevu", "materiau_id": "REV-FICTIF", "quantite": 14.0,
                              "unite": "feuille", "quantite_estimee": 10.0}]}))
    normale = _ok(_appeler(m6, "m6_evaluer_variance_chantier", {
        "chantier_id": "CH-1", "besoins_estimes": besoin, "seuil_pourcentage": 0.30,
        "lignes_declarees": [{"type_ligne": "prevu", "materiau_id": "REV-FICTIF", "quantite": 10.5,
                              "unite": "feuille", "quantite_estimee": 10.0}]}))

    assert critique["resultat"]["message_admin"] == MESSAGE_IMPOSE
    assert "message_admin" not in normale["resultat"]


def test_po_lecture_ne_depend_que_de_ce_qu_on_lui_donne():
    assert po_lecture.est_en_retard({"statut": "sent_to_supplier", "date_requise": "2026-11-05"}, "2026-11-06") is True
    assert po_lecture.est_en_retard({"statut": "sent_to_supplier", "date_requise": "2026-11-06"}, "2026-11-06") is False
    assert po_lecture.est_en_retard({"statut": "sent_to_supplier"},
                                    "2026-11-06") is False, "pas de date : pas en retard"
    assert evenements is not None


def _publier_variance(wct_id, critique, statut="evaluee"):
    ligne = {"materiau": "REV-FICTIF", "unite": "feuille", "quantite_prevue": "10.0", "quantite_reelle": "14.0",
             "ecart_pourcentage": "0.4", "critique": critique}
    charge = {"evenement_id": f"m6-variance-{wct_id}-{statut}", "wct_id": wct_id, "intervention_id": "int-1",
              "chantier_id": "CH-1", "statut_variance": statut, "signal_critique": critique if statut == "evaluee" else
              None,
              "seuil_pourcentage": 0.3, "horodatage_completion": HORO, "lignes": [ligne] if statut == "evaluee" else
              None}
    with stockage.transaction():
        evenements.publier("m6.variance_chantier", DEPT, charge, evenement_id=charge["evenement_id"])


def test_un_ecart_critique_attend_l_admin_avec_le_message_impose_jusqu_a_ce_que_sa_cause_soit_classee(base_durable):
    _publier_variance("wct-critique", True)
    _publier_variance("wct-normal", False)
    _publier_variance("wct-incomplet", False, statut="declaration_absente")

    (attente,) = [a for a in _attentes() if a["type"] == "ecart_materiaux_critique"]

    assert attente["id"] == "ecart_materiaux_critique:wct-critique" and attente["niveau"] == "N3"
    assert attente["resume"].startswith(MESSAGE_IMPOSE) and "REV-FICTIF" in attente["resume"]
    assert "vol" not in attente["resume"].lower().replace("involontaire", "")

    with stockage.transaction():  # une personne a classé la cause de cette ligne
        stockage.maillons(DEPT, "classements_variance").append(
            {"selection": {"wct_id": "wct-critique", "materiau_id": "REV-FICTIF"}})
    assert not [a for a in _attentes() if a["type"] == "ecart_materiaux_critique"]
