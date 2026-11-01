"""Scénarios de bout en bout sur le VRAI bus : trois départements ou plus, consommateurs réels, outils réels.

Aucun handler factice : `evenements.repartir` appelle les `consommateurs()` de chaque département chargé. Quand un
maillon
amont est publié directement (connecteur publicitaire de M7, réception de M6, qui ont besoin d'un service externe ou
d'un
long montage), la charge est celle du catalogue (validée à la publication) ; tout ce qui est en aval est exécuté par les
vrais outils et les vrais consommateurs. Vérifie à chaque scénario : propriété des données (aucun département n'écrit
dans
le registre d'un autre), absence de quarantaine, relivraison unique après panne d'un consommateur. Données fictives.
"""

from __future__ import annotations

import json

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m8_analytics import jeux_fictifs
from m8_analytics import operations_recues as op

from opsys import contexte, evenements, identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante

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
ADMIN = IdentiteAppelante("admin.fictif", "admin")
COMPTABLE = IdentiteAppelante("comptable", "admin")
INSTANT = "2026-10-30T20:00:00-04:00"
H = "2026-11-02T10:00:00-04:00"


@pytest.fixture
def inst(tmp_path, monkeypatch, declarer_services):
    m = im.monter(tmp_path, monkeypatch)
    m.surveiller(monkeypatch)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
        identite.creer_personne(
            cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234", ["finance", "admin"]
        )
        identite.creer_personne(
            cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234", ["nathan_owner", "admin"]
        )
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
    yield m
    im.demonter()


def _cap(m, *depts, appelant=None):
    return Capacites(m.departements, stockage.transaction, filtre=set(depts), memoire=False)


def _appeler(m, dept, outil, arguments, qui=None):
    """Appel d'un outil RÉEL : `Capacites` (agent), ou la porte d'un humain identifié (`executer_atomique`, comme les
    tests de chaque département) quand `qui` est donné."""
    if qui is None:
        return _cap(m, dept).appeler(outil, arguments)
    from opsys.outils import executer_atomique

    outil_reel = next(o for o in m.departements[dept].charger_outils() if o.nom == outil)
    with contexte.appele_par_appareil(qui):
        return executer_atomique(outil_reel, arguments)


def _ok(reponse):
    assert reponse["ok"] is True, reponse
    corps = reponse["resultat"]
    assert corps.get("accepte", True) is True, reponse
    return corps


def _propre(m):
    """Fin de scénario : aucune quarantaine, aucune écriture hors de son département."""
    assert m.quarantaines() == []
    assert m.ecritures_hors_propriete() == []


# ================================================================================================================ S1
def test_s1_signal_marketing_vers_entrepot_m8_puis_strategie_m9_et_memoire_m10(inst):
    """M7 -> M8 (faits) -> M9 (briefing) -> M10 (mémoire) ; M7 -> M5 (brouillon de charge). Cinq départements."""
    m = inst
    with stockage.transaction():
        registres = jeux_fictifs.registres_fictifs()
        for cle, nom in {
            "chantier": "faits_chantier",
            "entonnoir": "faits_entonnoir",
            "contenus": "faits_contenus",
            "cash_libre": "faits_cash_libre",
        }.items():
            for fait in registres[cle]:
                stockage.maillons(M8, nom).append(fait)
    evenements.publier("m7.signaux_marketing_constates", M7, ch.signaux_marketing(), evenement_id="s1-sig")
    evenements.publier("m7.depenses_marketing_constatees", M7, ch.depense_marketing(), evenement_id="s1-dep")
    evenements.publier(
        "m7.anomalie_depense_detectee",
        M7,
        ch.anomalie_depense(severite="critique", jour_debut="2026-11-01", jour_fin="2026-11-01"),
        evenement_id="s1-ano",
    )
    resume = m.repartir()
    assert resume["quarantaines"] == 0 and resume["echecs"] == 0, resume

    # M8 a rangé les trois constats ; M5 a un brouillon de charge ; M9 a l'anomalie.
    assert op.section(m.registre(M8, "faits_operations"), "2026-11-02")["marketing"]["anomalies"]["total"] == 1
    assert [x["issue"] for x in m.registre(M5, "charges_marketing_recues")] == ["BROUILLON_PROPOSE"]
    assert m.taille(M9, "signaux_gestion_recus") == 1

    # M8 consolide (vrai outil) -> m8.fait_consolide -> M9 et M10.
    publication = _ok(_appeler(m, M8, "m8_publier_faits_consolides", {"maintenant": INSTANT}))
    assert publication
    resume = m.repartir()
    assert resume["quarantaines"] == 0
    assert m.taille(M10, "faits_analytiques") == 1
    assert m.taille(M9, "signaux_gestion_recus") == 2  # anomalie + consolidation

    briefing = _ok(_appeler(m, M9, "m9_produire_briefing_matin", {"maintenant": "2026-11-02T07:00:00-05:00"}, ADMIN))
    section = briefing["signaux_de_gestion"]
    assert section["anomalies_depense"]["affichees"][0]["severite"] == "critique"
    assert section["derniere_consolidation_m8"]["mesures"] >= 1
    _propre(m)


def test_s1_rejouer_tout_le_flux_ne_cree_ni_doublon_ni_quarantaine(inst):
    m = inst
    evenements.publier("m7.depenses_marketing_constatees", M7, ch.depense_marketing(), evenement_id="a")
    evenements.publier("m7.anomalie_depense_detectee", M7, ch.anomalie_depense(), evenement_id="b")
    m.repartir()
    avant = {
        (d, r): m.taille(d, r)
        for d, r in [
            (M8, "faits_operations"),
            (M5, "charges_marketing_recues"),
            (M5, "grand_livre"),
            (M9, "signaux_gestion_recus"),
        ]
    }
    evenements.publier("m7.depenses_marketing_constatees", M7, ch.depense_marketing(), evenement_id="a-bis")
    evenements.publier("m7.anomalie_depense_detectee", M7, ch.anomalie_depense(), evenement_id="b-bis")
    resume = m.repartir()
    apres = {k: m.taille(*k) for k in avant}
    assert apres == avant and resume["quarantaines"] == 0 and resume["echecs"] == 0
    _propre(m)


# ================================================================================================================ S2
def _reception_m6(po="PO-1"):
    charge = {
        "evenement_id": "evt-rec-1",
        "po_id": po,
        "fournisseur_id": "gentek",
        "chantier_id": "CH-1",
        "horodatage_reception": "2026-09-29T09:15:00-04:00",
        "verdict_reception": "CONFORME",
        "statut_po": "received",
        "hash_maillon": "a" * 64,
        "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [
            {
                "materiau_id": "gouttiere-5po",
                "quantite_demandee": "60",
                "quantite_recue": "60",
                "prix_unitaire_prevu": "5.00",
                "devise_prevue": "CAD",
                "verdict_prix_po": "PRIX_LIVRE",
                "prix_unitaire_reception": None,
                "verdict_prix_reception": "INDETERMINE",
                "ecart_prix_critique": None,
            }
        ],
    }
    return charge


def test_s2_reception_m6_vers_facture_m5_puis_ecart_vu_par_m6_et_mesures_comptables_vues_par_m8(inst):
    """M6 (réception) -> M5 (à payer, facture fournisseur, rapprochement) -> M6 (À voir) ; M5 -> M8 (mesures)."""
    m = inst
    evenements.publier("m6.reception_enregistree", M6, _reception_m6(), evenement_id="evt-rec-1")
    assert m.repartir()["quarantaines"] == 0
    saisie = _ok(
        _appeler(
            m,
            M5,
            "m5_saisir_facture_fournisseur",
            {
                "po_id": "PO-1",
                "fournisseur_id": "gentek",
                "numero_facture": "F-1001",
                "date_facture": "2026-10-02",
                "montant_avant_taxes": "330.00",
                "total_facture": None,
                "horodatage": "2026-10-08T10:00:00-04:00",
            },
            COMPTABLE,
        )
    )
    ident = saisie["resultat"]["facture"]["facture_fournisseur_id"]
    avance = _ok(
        _appeler(
            m,
            M5,
            "m5_avancer_flux_fournisseur",
            {"facture_fournisseur_id": ident, "aujourd_hui": "2026-11-02", "horodatage": H},
        )
    )
    assert avance["resultat"]["evenement"] is True
    _ok(_appeler(m, M5, "m5_constater_mesures_comptables", {"aujourd_hui": "2026-11-02", "horodatage": H}))
    resume = m.repartir()
    assert resume["quarantaines"] == 0 and resume["echecs"] == 0, resume

    from m6_material_control import outils as m6

    with stockage.transaction():
        attentes = [a for a in m6.attentes() if a["type"] == "rapprochement_po_a_voir"]
    assert [a["id"] for a in attentes] == [ident] and "ECART" in attentes[0]["resume"]
    section = op.section(m.registre(M8, "faits_operations"), "2026-11-02")
    assert section["comptabilite"]["constats_recus"] == 1
    # M5 n'a validé aucune écriture : seulement des brouillons ; aucun mouvement d'argent.
    assert {x["type_entree"] for x in m.registre(M5, "grand_livre")} <= {"gl_ecriture_proposee"}
    assert m.registre(M5, "principal") == []
    _propre(m)


# ================================================================================================================ S3
VENDEUR = IdentiteAppelante("vendeur.un", "seller")
CLIENT_COURRIEL = "cliente.fictive@example.test"
TEXTE_COURRIEL = (
    "Bonjour, mes gouttières fuient à Laval. Nous avons une maison unifamiliale de deux étages construite en 1987, "
    "au 245 rue des Pins, Laval, H7N 1A1."
)
SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}


def _photo(i=1):
    return {
        "photo_id": f"p{i}",
        "resolution_largeur": 3000,
        "resolution_hauteur": 2000,
        "eclairage": 7,
        "angle": "face",
        "reference_echelle": {"type": "porte", "dimensions_connues": True},
    }


def test_s3_courriel_m1_vers_profil_m2_contexte_de_site_m3_et_estimation(inst):
    """M1 (courriel) -> M2 (lead, client) -> profil confirmé par une personne -> M3, M4 et M10 -> contexte de site M3
    -> M2 (coach) ; l'estimation de M3 reprend le contexte. Cinq départements, aucun double de handler."""
    m = inst
    from m2_revenue_crm import outils as m2

    reponse = _ok(
        _appeler(
            m,
            M1,
            "m1_recevoir_message_canal",
            {
                "canal": "courriel",
                "expediteur": CLIENT_COURRIEL,
                "message_id": "msg-fictif-0001",
                "recu_le": "2026-10-30T14:00:00-04:00",
                "texte": TEXTE_COURRIEL,
                "objet": "Fuite de gouttières",
            },
        )
    )
    assert reponse["decision"] == "TRANSMETTRE_M2", reponse
    lead_id = reponse["lead"]["lead_id"]
    assert m.repartir()["quarantaines"] == 0  # M2 ingère ; client_associe va à M3, M4, M5, M7, M8, M10
    assert m.taille(M3, "liens_lead_client") == 1 and m.taille(M4, "liens_lead_client") == 1

    # Un humain (le vendeur) qualifie le lead et confirme le profil de propriété proposé d'après le courriel.
    assert (
        m2.transitionner_statut(
            lead_id,
            "qualifie",
            "2026-10-30T15:00:00-04:00",
            owner="vendeur.un",
            prochaine_action={"description": "Appeler la cliente", "echeance": "2026-11-02T09:00:00-05:00"},
        )["accepte"]
        is True
    )
    assert m2.enregistrer_interaction(
        lead_id, "vendeur.un", "Appel de qualification fictif", "2026-10-30T15:30:00-04:00"
    )["accepte"]
    proposition = _ok(
        _appeler(
            m,
            M2,
            "m2_proposer_profil_propriete_depuis_courriel",
            {
                "lead_id": lead_id,
                "revision_attendue": 0,
                "message_ref": "msg-fictif-0001@example.test",
                "texte": TEXTE_COURRIEL,
                "horodatage": "2026-10-30T16:00:00-04:00",
            },
            VENDEUR,
        )
    )
    propriete_id = proposition["resultat"]["propriete_id"]
    confirmation = _ok(
        _appeler(
            m,
            M2,
            "m2_confirmer_profil_propriete",
            {
                "lead_id": lead_id,
                "propriete_id": propriete_id,
                "revision_attendue": 1,
                "decision": "confirmer",
                "horodatage": "2026-10-30T16:05:00-04:00",
            },
            VENDEUR,
        )
    )
    assert confirmation["resultat"]["decision"] == "confirmer"
    assert m.repartir()["quarantaines"] == 0
    assert m.taille(M3, "profils_propriete_recus") == 1 and m.taille(M4, "profils_propriete_recus") == 1

    # M3 construit le contexte de site : le profil du bus est repris (aucun profil fourni par l'appelant).
    contexte_site = _ok(
        _appeler(
            m,
            M3,
            "m3_construire_contexte_site",
            {"lead_id": lead_id, "service": "gouttieres", "date_reference": "2026-11-02"},
        )
    )
    assert contexte_site["resultat"]["profil_propriete_du_bus"] == "repris"
    facteurs = {f["facteur"]: f for f in contexte_site["resultat"]["contexte"]["facteurs"]}
    assert facteurs["hauteur"]["valeur"] == {"etages": 2} and facteurs["age"]["valeur"] == {"annee_construction": 1987}
    empreinte = contexte_site["resultat"]["contexte"]["empreinte"]
    assert m.repartir()["quarantaines"] == 0
    assert m.taille(M2, "contextes_site_recus") == 1  # M2 sait que M3 a un contexte de site pour ce lead

    # L'estimation de M3 reprend ce contexte (clé sœur), sans changer le prix ni le blocage.
    marqueur = _ok(
        _appeler(
            m, M2, "m2_evaluer_readiness", {"lead_id": lead_id, "horodatage": "2026-11-02T08:00:00-05:00"}, VENDEUR
        )
    )["resultat"]
    with stockage.transaction():
        contrat = next(
            x["contrat"]
            for x in m2._obtenir_registre().lire()
            if x.get("type_entree") == "lead_ingere" and x.get("lead_id") == lead_id
        )
    from opsys.outils import executer_atomique

    estimer = next(o for o in m.departements[M3].charger_outils() if o.nom == "m3_estimer_projet")
    estimation = executer_atomique(
        estimer,
        {
            "contrat": contrat,
            "marqueur": marqueur,
            "photos": [_photo()],
            "seuils": SEUILS,
            "bareme": {
                "version": "2026.1",
                "unite": "pi2",
                "postes": {"gouttieres": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}},
            },
            "quantite": 1200,
            "plancher_rentable": 9000,
            "contexte_site_empreinte": empreinte,
        },
    )
    corps = _ok(estimation)
    assert corps["contexte_site"]["empreinte"] == empreinte and corps["contexte_site"]["version_courante"] is True

    # M4 : le bloc contexte_propriete est dit à la préparation, hors verdict (rien ne s'écrit chez M4 pour cela).
    from m4_field_ops import contexte_propriete as cp4

    with stockage.transaction():
        bloc = cp4.contexte_du_lead(
            list(stockage.maillons(M4, cp4.REGISTRE_LIENS)), list(stockage.maillons(M4, cp4.REGISTRE_PROFILS)), lead_id
        )
    assert bloc["statut"] == "recu" and bloc["etages"] == 2 and bloc["annee_construction"] == 1987
    # Aucune adresse ni contact chez M3, M4 : le profil du bus n'en porte pas.
    for dept, registre in ((M3, "profils_propriete_recus"), (M4, "profils_propriete_recus")):
        texte = json.dumps(m.registre(dept, registre), ensure_ascii=False)
        assert CLIENT_COURRIEL not in texte and "rue" not in texte.lower()
    _propre(m)


# ================================================================================================================ S4
def _facture_client(client_id, facture_id="F-1"):
    """Une facture envoyée le 2 octobre (échéance le 1er novembre), posée avec les vraies fonctions de M5."""
    from m5_financecore import facturation, taux_fiscaux
    from m5_financecore import outils as m5
    from m5_financecore import registre as registre_module

    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    with stockage.transaction():
        reg = registre_module.Registre(maillons=stockage.maillons(M5, "factures"))
        lignes = [
            {
                "description": "Travaux (fictif)",
                "quantite": "1",
                "unite": "forfait",
                "prix_unitaire": "600.00",
                "reference_ligne_devis": "L1",
            }
        ]
        for couple in (
            facturation.creer_facture_brouillon(
                facture_id,
                f"CH-{facture_id}",
                f"D-{facture_id}",
                client_id,
                lignes,
                "2026-10-01T09:00:00-04:00",
                dictionnaire,
                reg,
            ),
            facturation.envoyer_facture(facture_id, "2026-10-02T09:00:00-04:00", reg),
        ):
            assert couple[1] is None, couple


def test_s4_relance_de_creance_m5_vers_m2_avertit_le_coach_et_m8_compte_le_brouillon_sans_aucun_envoi(
    inst, monkeypatch, tmp_path
):
    """M1 (lead) -> M2 (client) ; M5 prépare la relance d'une facture en retard -> M2 (avertissement) et M8
    (mesures)."""
    import yaml
    from m2_revenue_crm import outils as m2
    from m2_revenue_crm import outils_ventes
    from m5_financecore import outils as m5

    manifeste = tmp_path / "department-m5.yaml"
    manifeste.write_text(
        yaml.safe_dump(
            {
                "configuration": {
                    "categories_depense_sans_po": ["carburant", "outils"],
                    "operations": {
                        "relances": {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7, 21, 45]},
                        "compte_remboursement_employes": "2200",
                        "rapprochement": {"motifs_frais": ["frais mensuels"], "compte_frais_bancaires": "5800"},
                    },
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(m5, "_MANIFESTE", manifeste)
    m = inst
    reponse = _ok(
        _appeler(
            m,
            M1,
            "m1_recevoir_message_canal",
            {
                "canal": "courriel",
                "expediteur": CLIENT_COURRIEL,
                "message_id": "msg-fictif-0002",
                "recu_le": "2026-10-30T14:00:00-04:00",
                "texte": "Bonjour, mes gouttières fuient à Laval.",
                "objet": "Fuite",
            },
        )
    )
    lead_id = reponse["lead"]["lead_id"]
    m.repartir()
    with stockage.transaction():
        client_id = m2.clients.client_de_lead(m2._obtenir_registre(), lead_id)
    assert client_id
    assert (
        m2.transitionner_statut(
            lead_id,
            "qualifie",
            "2026-10-30T15:00:00-04:00",
            owner="vendeur.un",
            prochaine_action={"description": "Appeler", "echeance": "2026-11-02T09:00:00-05:00"},
        )["accepte"]
        is True
    )
    _facture_client(client_id)

    relances = _ok(_appeler(m, M5, "m5_preparer_relances_clients", {"aujourd_hui": "2026-11-10", "horodatage": H}))
    assert relances["resultat"]["creees"] == 1 and "rien n'est envoyé" in relances["resultat"]["a_faire"]
    _ok(_appeler(m, M5, "m5_constater_mesures_comptables", {"aujourd_hui": "2026-11-10", "horodatage": H}))
    resume = m.repartir()
    assert resume["quarantaines"] == 0 and resume["echecs"] == 0, resume

    with stockage.transaction():
        dossier, refus = outils_ventes._dossier_coach(m2._obtenir_registre(), lead_id, "2026-11-10T09:00:00-05:00")
    assert refus is None
    texte = " ".join(f["texte"] for f in dossier["faits"])
    assert "facture en retard" in texte and "niveau 1" in texte and "689.85" not in texte  # aucun montant au coach
    compta = op.section(m.registre(M8, "faits_operations"), "2026-11-10")["comptabilite"]["dernier"]
    assert compta["relances_en_brouillon"] == 1 and compta["creances"]["nombre"] == 1
    # Rien n'est parti : aucune demande d'approbation, aucun courriel, aucun mouvement d'argent.
    from sqlalchemy import func, select

    from opsys.stockage.schema import APPROBATIONS

    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(APPROBATIONS)).scalar_one() == 0
    assert m.registre(M5, "principal") == []
    assert not [e for e in m.sortants("m1.courriel_envoye")]
    _propre(m)


# ================================================================================================================ S5
def test_s5_conversion_hors_ligne_m7_vers_score_m2_et_vue_m8_sans_ecraser_le_lead(inst):
    """Un lead d'appel téléphonique (aucune source au contrat) ; M7 importe une conversion hors ligne -> M2 (score en
    lecture) et M8 (comptage) ; le contrat du lead est intact. (Un lead de M1 porte toujours le canal d'entrée comme
    source : la conversion de M7 n'y change rien, ce qui est le bon comportement.)"""
    from m2_revenue_crm import liste_leads, outils_ventes, scoring_faits
    from m2_revenue_crm import outils as m2

    m = inst
    lead_id = "lead-appel-fictif"
    assert (
        m2.ingerer_lead(
            {
                "lead_id": lead_id,
                "conversation_id": "conv-appel",
                "contact": {"nom": "Cliente Fictive", "telephone": "418-555-0188"},
                "type_travaux": "renovation_totale",
                "ville": "Québec",
                "urgence_declaree": False,
                "canal": "telephone",
            },
            "2026-10-30T14:00:00-04:00",
        )["accepte"]
        is True
    )

    def _source_connue():
        with stockage.transaction():
            ctx, absent = outils_ventes._contexte_score("2026-11-02T10:00:00-05:00")
            assert absent is None
            return scoring_faits.faits_du_lead(ctx, lead_id)["source_connue"]

    def _contrat():
        with stockage.transaction():
            return dict(liste_leads.fiches_des_leads(m2._obtenir_registre().lire())[lead_id].contrat)

    avant, contrat_avant = _source_connue(), _contrat()
    evenements.publier(
        "m7.conversion_hors_ligne_importee",
        M7,
        ch.conversion_hors_ligne(lead_id=lead_id, source="google"),
        evenement_id="s5-conv",
    )
    resume = m.repartir()
    assert resume["quarantaines"] == 0
    assert (avant, _source_connue()) == (False, True) and _contrat() == contrat_avant
    section = op.section(m.registre(M8, "faits_operations"))
    assert section["marketing"]["conversions_hors_ligne"]["par_source"] == {"google": 1}
    score = _ok(
        _appeler(m, M2, "m2_calculer_score_lead", {"lead_id": lead_id, "horodatage": "2026-11-02T10:00:00-05:00"})
    )
    assert score  # le score se calcule sur les faits relus, sans erreur
    _propre(m)


# ================================================================================================================ S6
def test_s6_panne_de_m8_en_pleine_chaine_les_autres_livrent_puis_m8_reprend_une_seule_fois(inst):
    """M8 tombe : M5 et M9 reçoivent quand même (aucun blocage croisé) ; M8 revient : ses événements en attente sont
    livrés UNE fois, puis sa consolidation atteint M9 et M10. Aucune quarantaine à aucun moment."""
    m = inst
    evenements.publier("m7.depenses_marketing_constatees", M7, ch.depense_marketing(), evenement_id="s6-dep")
    evenements.publier(
        "m7.anomalie_depense_detectee",
        M7,
        ch.anomalie_depense(jour_debut="2026-11-01", jour_fin="2026-11-01"),
        evenement_id="s6-ano",
    )
    m.pannes.add(M8)
    m.repartir(passes=1)
    assert m.statut("s6-dep", M8) == "echec" and m.statut("s6-ano", M8) == "echec"
    assert m.statut("s6-dep", M5) == "traite" and m.statut("s6-ano", M9) == "traite"  # pas de blocage croisé
    assert m.taille(M8, "faits_operations") == 0 and m.quarantaines() == []
    m.pannes.clear()
    m.repartir()
    assert m.taille(M8, "faits_operations") == 2
    m.repartir()
    assert m.taille(M8, "faits_operations") == 2 and m.taille(M5, "charges_marketing_recues") == 1
    _ok(_appeler(m, M8, "m8_publier_faits_consolides", {"maintenant": INSTANT}))
    m.repartir()
    assert m.taille(M10, "faits_analytiques") == 1 and m.taille(M9, "signaux_gestion_recus") == 2
    _propre(m)


# ================================================================================================================ S7
def test_s7_dossier_cpa_scelle_m5_vers_m10_et_mesures_m8_sans_aucune_donnee_de_client(inst):
    m = inst
    evenements.publier("m5.dossier_cpa_scelle", M5, ch.dossier_cpa(), evenement_id="s7-d")
    evenements.publier("m5.mesures_comptables_constatees", M5, ch.mesures_comptables(), evenement_id="s7-m")
    evenements.publier(
        "m5.rapprochement_po_constate", M5, ch.rapprochement_po(verdict="INCOMPLET"), evenement_id="s7-r"
    )
    resume = m.repartir()
    assert resume["quarantaines"] == 0
    assert m.taille(M10, "dossiers_cpa_scelles") == 1 and m.taille(M8, "faits_operations") == 1
    assert m.taille(M6, "rapprochements_facture_recus") == 1
    tout = json.dumps(
        [
            m.registre(M10, "dossiers_cpa_scelles"),
            m.registre(M8, "faits_operations"),
            m.registre(M6, "rapprochements_facture_recus"),
        ],
        default=str,
        ensure_ascii=False,
    )
    for interdit in ("@example.test", "Tremblay", "telephone"):
        assert interdit not in tout
    _propre(m)
