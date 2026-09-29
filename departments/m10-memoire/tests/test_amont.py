"""PLAN T4.18 : M10 garde l'AMONT d'une affaire, du lead au devis (P4, DEFINITION-PRODUIT §6 « M10 reçoit des
événements de tous les départements à chaque étape »).

Quatre types du bus : `m1.lead_qualifie`, `m2.client_associe`, `m3.devis_accepte`, `m3.devis_sans_reponse`.
Ce que M10 en garde : des identifiants et des faits d'étape, jamais la charge (le contact du lead, la ville, les
empreintes du correspondant, les lignes d'un devis restent chez leur département). Le client associé est
`CLIENT_PRIVATE` (M1 et M2 seulement) ; le prix et le coût d'un devis accepté sont un maillon `FINANCIAL` à part, qui
ne sort dans aucun paquet.

Quatre étages : les modules purs (`etapes.py`, `amont.py`), la lecture (classification, paquet, consolidation,
audit), la table qui permet d'ajouter `m3.devis_envoye` sans refonte, et le VRAI bus sur une base SQLite temporaire
migrée. Charges fictives, conformes au catalogue du socle (contrôlé).
"""

from __future__ import annotations

import ast
import dataclasses
import itertools
import json
from pathlib import Path

import m10_memoire.outils as outils_mod
import pytest
from m10_memoire import (
    amont,
    audit,
    classification,
    confidentialite,
    consolidation,
    etapes,
    paquets,
    registre,
    wct,
)
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS

FICTIF = True
LEAD = "LEAD-AMONT-1"
CLIENT_ID = "9f" * 32
HORODATAGE_LEAD = "2026-09-10T09:15:00-04:00"
HORODATAGE_CLIENT = "2026-09-10T09:15:30-04:00"
HORODATAGE_DEVIS_A = "2026-09-14T16:00:00-04:00"  # acceptation du devis A
HORODATAGE_DEVIS_B = "2026-09-05T10:00:00-04:00"  # dernier état du devis B
HORODATAGE_CONSTAT = "2026-09-12T08:00:00-04:00"  # le constat « sans réponse » du devis B
HORODATAGE_WCT = "2026-09-15T14:00:00-04:00"
HORODATAGE_PAQUET = "2026-09-16T08:00:00-04:00"  # « maintenant » de la lecture : ne doit figurer dans aucun fait
JOUR_LEAD = "2026-09-10"

CONTACT = {"nom": "Camille Testeur", "telephone": "+1 514 555 0142", "courriel": "camille.testeur@exemple.test"}
# Tout ce que le client a donné ou que son numéro a produit : rien de cela n'entre chez M10.
CONFIDENCES_DU_CLIENT = (
    "Camille", "Testeur", "514 555 0142", "camille.testeur@exemple.test", "Repentigny", "texte-conv-9f3a",
    "texte:sig-777",
)
MONTANTS_DU_DEVIS = ("1249.75", "49.99", "812.50", "0.35")
DESCRIPTION_DE_LIGNE = "Gouttières aluminium 5 po"

TYPE_LEAD = etapes.TYPE_LEAD_QUALIFIE
TYPE_CLIENT = etapes.TYPE_CLIENT_ASSOCIE
TYPE_ACCEPTE = etapes.TYPE_DEVIS_ACCEPTE
TYPE_SANS_REPONSE = etapes.TYPE_DEVIS_SANS_REPONSE
TYPE_MONTANTS = etapes.TYPE_MONTANTS_DEVIS_ACCEPTE
TYPES_DE_L_AMONT = (TYPE_LEAD, TYPE_CLIENT, TYPE_ACCEPTE, TYPE_SANS_REPONSE)


def _lead_qualifie(lead_id=LEAD, **surcharges):
    lead = {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": "texte-conv-9f3a", "contact": dict(CONTACT),
        "service": "gouttieres", "ville": "Repentigny", "urgence_declaree": True, "canal": "texte",
        "source": "sms", "utm": {"utm_source": "facebook"}, "campagne": "printemps-fictif",
    }
    lead.update(surcharges)
    return {"lead": lead, "horodatage": HORODATAGE_LEAD, "signal_id": "texte:sig-777"}


def _client_associe(lead_id=LEAD, **surcharges):
    charge = {"lead_id": lead_id, "client_id": CLIENT_ID, "horodatage_association": HORODATAGE_CLIENT}
    charge.update(surcharges)
    return charge


def _devis_accepte(devis_id="DEVIS-A", lead_id=LEAD, **surcharges):
    charge = {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": "CH-AMONT-1",
        "lignes": [{
            "reference_ligne": f"{devis_id}-L0", "description": DESCRIPTION_DE_LIGNE, "quantite": "25",
            "unite": "pied", "prix_unitaire": "49.99", "prix_ligne": "1249.75", "reference_besoin_materiau": None,
        }],
        "cout_total": "812.50", "prix_total": "1249.75", "taux_marge": "0.35",
        "horodatage_acceptation": HORODATAGE_DEVIS_A,
    }
    charge.update(surcharges)
    return charge


def _devis_sans_reponse(devis_id="DEVIS-B", lead_id=LEAD, **surcharges):
    charge = {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "statut": "envoye",
        "horodatage_devis": HORODATAGE_DEVIS_B, "horodatage_reference": HORODATAGE_CONSTAT,
        "delai_relance_jours": 7,
    }
    charge.update(surcharges)
    return charge


CHARGES = {
    TYPE_LEAD: _lead_qualifie, TYPE_CLIENT: _client_associe, TYPE_ACCEPTE: _devis_accepte,
    TYPE_SANS_REPONSE: _devis_sans_reponse,
}


def _wct(wct_id="WCT-AMONT-1", lead_id=LEAD, devis_id="DEVIS-A"):
    return {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": lead_id, "technicien_id": "TECH-1",
        "horodatage_completion": HORODATAGE_WCT, "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90, "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"], "devis_id": devis_id,
    }


@pytest.fixture
def evenements_m10():
    return registre.Registre()


@pytest.fixture
def registres():
    return registre.Registre(), registre.Registre()


def _memoriser_tout(registre_evenements, *, avec_wct=False):
    """Le dossier complet d'une affaire : lead, client, devis A accepté, devis B sans réponse (et le WCT)."""
    for type_evenement in (TYPE_LEAD, TYPE_CLIENT, TYPE_ACCEPTE, TYPE_SANS_REPONSE):
        resultat, verdict = amont.memoriser(type_evenement, CHARGES[type_evenement](), registre_evenements)
        assert verdict is None, (type_evenement, verdict)
        assert resultat["maillon"]["ligne_id"]
    if avec_wct:
        wct.memoriser_wct(_wct(), registre_evenements)


def _couche(paquet, nom):
    return next(c for c in paquet["couches"] if c["nom"] == nom)


def _faits_recents(paquet):
    return _couche(paquet, paquets.COUCHE_EVENEMENTS_RECENTS)["faits"]


def _de_type(registre_evenements, type_maillon):
    return [m for m in registre_evenements.lire() if classification.type_evenement(m) == type_maillon]


# =========================================================================================
# 1. Les charges de test sont celles du catalogue ; les modules sont purs
# =========================================================================================
@pytest.mark.parametrize("type_evenement", TYPES_DE_L_AMONT)
def test_les_charges_de_test_sont_conformes_au_catalogue_du_socle(type_evenement):
    assert erreurs_charge(type_evenement, CHARGES[type_evenement]()) == []


def test_le_manifeste_et_la_table_disent_la_meme_chose():
    dep = charger_departements()["m10-memoire"]

    assert etapes.types_consommes() == TYPES_DE_L_AMONT
    assert set(TYPES_DE_L_AMONT) <= set(dep.evenements_consomme)
    assert "m3.devis_envoye" not in dep.evenements_consomme  # T4.7 ne l'a pas encore publié
    assert "m3.devis_envoye" not in evenements.types_connus()
    assert {etape.producteur for etape in etapes.etapes_de_l_amont()} == {
        "m01-front-office", "m02-revenue-crm", "m03-estimation"}
    for etape in etapes.etapes_de_l_amont():
        assert etape.producteur in charger_departements(), etape.producteur


def test_opsys_verifier_ne_trouve_rien_a_redire_au_manifeste_de_m10():
    problemes = evenements.verifier_coherence(charger_departements())

    assert [p for p in problemes if p.startswith("m10-memoire")] == []


@pytest.mark.parametrize("module", [etapes, amont])
def test_les_modules_de_l_amont_restent_purs(module):
    """DA-M10-08 : aucun import d'`opsys` hors de `outils.py`."""
    arbre = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    importes = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes += [alias.name for alias in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0:
            importes.append(noeud.module or "")
    assert [nom for nom in importes if nom.split(".")[0] == "opsys"] == []


# =========================================================================================
# 2. Ce qui est gardé : identifiants et faits d'étape, rien d'autre
# =========================================================================================
def test_un_lead_qualifie_garde_le_service_le_canal_l_urgence_et_l_instant_du_message(evenements_m10):
    resultat, verdict = amont.memoriser(TYPE_LEAD, _lead_qualifie(), evenements_m10)

    assert verdict is None
    maillon = resultat["maillon"]
    assert {cle: valeur for cle, valeur in maillon.items() if cle not in ("ligne_id", "precedent_ligne_id")} == {
        "lead_id": LEAD, "service": "gouttieres", "canal": "texte", "urgence_declaree": True,
        "horodatage": HORODATAGE_LEAD, "type_entree": "evenement_memorise", "type_evenement": TYPE_LEAD,
        "confidentialite": "INTERNAL",
    }
    assert resultat["montants"] is None and resultat["deja_memorise"] is False and resultat["identique"] is True


def test_le_contact_le_texte_et_les_empreintes_du_correspondant_ne_sont_jamais_copies(evenements_m10):
    """Loi 25 : on cherche chaque confidence dans TOUT ce que le registre porte, clés et valeurs."""
    _memoriser_tout(evenements_m10, avec_wct=True)

    tout = json.dumps(evenements_m10.lire(), ensure_ascii=False)
    for confidence in CONFIDENCES_DU_CLIENT:
        assert confidence not in tout, confidence
    for cle_interdite in ("contact", "telephone", "courriel", "nom", "ville", "conversation_id", "signal_id",
                          "utm", "campagne", "lignes", "description"):
        assert f'"{cle_interdite}"' not in tout, cle_interdite
    assert DESCRIPTION_DE_LIGNE not in tout


def test_un_client_associe_est_client_prive_et_ne_garde_que_le_lien_et_l_instant(evenements_m10):
    resultat, _ = amont.memoriser(TYPE_CLIENT, _client_associe(), evenements_m10)

    maillon = resultat["maillon"]
    assert confidentialite.niveau_de(maillon) == confidentialite.NIVEAU_CLIENT_PRIVE == "CLIENT_PRIVATE"
    assert {cle: valeur for cle, valeur in maillon.items() if cle not in ("ligne_id", "precedent_ligne_id")} == {
        "lead_id": LEAD, "client_id": CLIENT_ID, "horodatage": HORODATAGE_CLIENT,
        "type_entree": "evenement_memorise", "type_evenement": TYPE_CLIENT, "confidentialite": "CLIENT_PRIVATE",
    }


def test_un_devis_accepte_donne_une_etape_sans_montant_et_un_compagnon_financier(evenements_m10):
    resultat, verdict = amont.memoriser(TYPE_ACCEPTE, _devis_accepte(), evenements_m10)

    assert verdict is None
    etape, montants = resultat["maillon"], resultat["montants"]
    assert {cle: valeur for cle, valeur in etape.items() if cle not in ("ligne_id", "precedent_ligne_id")} == {
        "lead_id": LEAD, "devis_id": "DEVIS-A", "chantier_id": "CH-AMONT-1", "horodatage": HORODATAGE_DEVIS_A,
        "type_entree": "evenement_memorise", "type_evenement": TYPE_ACCEPTE, "confidentialite": "INTERNAL",
    }
    assert {cle: valeur for cle, valeur in montants.items() if cle not in ("ligne_id", "precedent_ligne_id")} == {
        "lead_id": LEAD, "devis_id": "DEVIS-A", "prix_total": "1249.75", "cout_total": "812.50", "taux_marge": "0.35",
        "horodatage": HORODATAGE_DEVIS_A, "type_entree": "evenement_memorise", "type_evenement": TYPE_MONTANTS,
        "confidentialite": "FINANCIAL",
    }
    assert confidentialite.niveau_de(montants) == "FINANCIAL"
    assert [m["ligne_id"] for m in evenements_m10.lire()] == [etape["ligne_id"], montants["ligne_id"]]
    texte_etape = json.dumps(etape)
    for montant in MONTANTS_DU_DEVIS:
        assert montant not in texte_etape, montant


def test_un_devis_sans_reponse_garde_le_constat_comme_instant_et_le_dernier_etat_du_devis(evenements_m10):
    resultat, _ = amont.memoriser(TYPE_SANS_REPONSE, _devis_sans_reponse(), evenements_m10)

    maillon = resultat["maillon"]
    assert {cle: valeur for cle, valeur in maillon.items() if cle not in ("ligne_id", "precedent_ligne_id")} == {
        "lead_id": LEAD, "devis_id": "DEVIS-B", "chantier_id": None, "statut": "envoye", "depuis": HORODATAGE_DEVIS_B,
        "delai_relance_jours": 7, "horodatage": HORODATAGE_CONSTAT, "type_entree": "evenement_memorise",
        "type_evenement": TYPE_SANS_REPONSE, "confidentialite": "INTERNAL",
    }


def test_l_instant_de_chaque_maillon_est_celui_de_l_evenement_jamais_une_horloge(evenements_m10):
    _memoriser_tout(evenements_m10)

    instants = {classification.type_evenement(m): m["horodatage"] for m in evenements_m10.lire()}
    assert instants == {
        TYPE_LEAD: HORODATAGE_LEAD, TYPE_CLIENT: HORODATAGE_CLIENT, TYPE_ACCEPTE: HORODATAGE_DEVIS_A,
        TYPE_MONTANTS: HORODATAGE_DEVIS_A, TYPE_SANS_REPONSE: HORODATAGE_CONSTAT}


def test_une_charge_ne_peut_ni_choisir_son_type_ni_ouvrir_son_niveau(evenements_m10):
    charge = _client_associe(confidentialite="PUBLIC_INTERNAL", type_evenement=TYPE_LEAD, type_entree="signal")

    resultat, _ = amont.memoriser(TYPE_CLIENT, charge, evenements_m10)

    maillon = resultat["maillon"]
    assert maillon["confidentialite"] == "CLIENT_PRIVATE"
    assert maillon["type_evenement"] == TYPE_CLIENT and maillon["type_entree"] == "evenement_memorise"


def test_la_chaine_du_registre_reste_valide(evenements_m10):
    _memoriser_tout(evenements_m10, avec_wct=True)

    assert evenements_m10.valider_chaine() == (True, "")


# =========================================================================================
# 3. Refus : forme fermée, verdict nommé, rien d'écrit, jamais la valeur
# =========================================================================================
def _avec(charge, chemin, valeur):
    copie = json.loads(json.dumps(charge))
    cible = copie
    for cle in chemin[:-1]:
        cible = cible[cle]
    cible[chemin[-1]] = valeur
    return copie


REFUS = [
    (TYPE_LEAD, ("lead", "lead_id"), "camille.testeur@exemple.test", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_LEAD, ("lead", "lead_id"), "+15145550142", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_LEAD, ("lead", "service"), "Gouttières à Repentigny", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_LEAD, ("lead", "canal"), "signal-de-fumée", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_LEAD, ("lead", "urgence_declaree"), "oui", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_LEAD, ("horodatage",), "2026-09-10T09:15:00", etapes.REJ_AMONT_HORODATAGE_INVALIDE),
    (TYPE_LEAD, ("horodatage",), "hier", etapes.REJ_AMONT_HORODATAGE_INVALIDE),
    (TYPE_CLIENT, ("client_id",), "Camille Testeur", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_CLIENT, ("horodatage_association",), None, etapes.REJ_AMONT_HORODATAGE_INVALIDE),
    (TYPE_ACCEPTE, ("devis_id",), "Devis de Camille", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_ACCEPTE, ("prix_total",), "1 249,75 $", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_ACCEPTE, ("cout_total",), "beaucoup", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_ACCEPTE, ("chantier_id",), "chantier chez Camille", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_SANS_REPONSE, ("statut",), "accepte", etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_SANS_REPONSE, ("delai_relance_jours",), 0, etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_SANS_REPONSE, ("delai_relance_jours",), True, etapes.REJ_AMONT_CHAMP_INVALIDE),
    (TYPE_SANS_REPONSE, ("horodatage_reference",), "2026-09-12", etapes.REJ_AMONT_HORODATAGE_INVALIDE),
]


@pytest.mark.parametrize(("type_evenement", "chemin", "valeur", "code"), REFUS)
def test_un_champ_hors_de_sa_forme_est_refuse_sans_rien_ecrire_et_sans_citer_la_valeur(
    evenements_m10, type_evenement, chemin, valeur, code
):
    charge = _avec(CHARGES[type_evenement](), chemin, valeur)

    resultat, verdict = amont.memoriser(type_evenement, charge, evenements_m10)

    assert resultat is None
    assert verdict["code"] == code
    assert verdict["detail"] == "/".join(chemin)  # le CHAMP, jamais la valeur
    assert evenements_m10.lire() == []


@pytest.mark.parametrize(("type_evenement", "chemin"), [
    (TYPE_LEAD, ("lead", "lead_id")), (TYPE_LEAD, ("lead", "service")), (TYPE_LEAD, ("horodatage",)),
    (TYPE_CLIENT, ("client_id",)), (TYPE_ACCEPTE, ("prix_total",)), (TYPE_ACCEPTE, ("horodatage_acceptation",)),
    (TYPE_SANS_REPONSE, ("horodatage_reference",)), (TYPE_SANS_REPONSE, ("chantier_id",)),
])
def test_un_champ_absent_est_refuse_et_dit_lequel(evenements_m10, type_evenement, chemin):
    charge = CHARGES[type_evenement]()
    cible = charge
    for cle in chemin[:-1]:
        cible = cible[cle]
    del cible[chemin[-1]]

    resultat, verdict = amont.memoriser(type_evenement, charge, evenements_m10)

    assert resultat is None
    assert verdict["code"] == etapes.REJ_AMONT_CHAMP_MANQUANT and verdict["detail"] == "/".join(chemin)
    assert evenements_m10.lire() == []


def test_un_type_inconnu_et_une_charge_qui_n_est_pas_un_objet_sont_refuses(evenements_m10):
    inconnu, verdict_inconnu = amont.memoriser("m3.devis_envoye", _devis_accepte(), evenements_m10)
    assert inconnu is None and verdict_inconnu["code"] == etapes.REJ_AMONT_TYPE_INCONNU

    pas_un_objet, verdict = amont.memoriser(TYPE_CLIENT, ["lead_id", LEAD], evenements_m10)
    assert pas_un_objet is None and verdict["code"] == etapes.REJ_AMONT_CHAMP_MANQUANT
    assert evenements_m10.lire() == []


def test_un_devis_dont_les_montants_sont_hors_forme_n_ecrit_meme_pas_l_etape(evenements_m10):
    """L'étape et son compagnon sont écrits ensemble ou pas du tout."""
    resultat, verdict = amont.memoriser(TYPE_ACCEPTE, _devis_accepte(taux_marge="trente-cinq pour cent"),
                                        evenements_m10)

    assert resultat is None and verdict["detail"] == "taux_marge"
    assert evenements_m10.lire() == []


# =========================================================================================
# 4. Idempotence : un rejeu ne crée rien, un fait différent est dit
# =========================================================================================
@pytest.mark.parametrize("type_evenement", TYPES_DE_L_AMONT)
def test_un_rejeu_ne_cree_aucun_doublon_et_rend_le_maillon_existant(evenements_m10, type_evenement):
    premier, _ = amont.memoriser(type_evenement, CHARGES[type_evenement](), evenements_m10)
    taille = len(evenements_m10.lire())

    rejeu, verdict = amont.memoriser(type_evenement, CHARGES[type_evenement](), evenements_m10)

    assert verdict is None
    assert len(evenements_m10.lire()) == taille
    assert rejeu["maillon"]["ligne_id"] == premier["maillon"]["ligne_id"]
    assert rejeu["deja_memorise"] is True and rejeu["identique"] is True
    assert premier["deja_memorise"] is False
    assert evenements_m10.valider_chaine() == (True, "")


def test_un_devis_accepte_rejoue_ne_double_ni_l_etape_ni_le_compagnon(evenements_m10):
    amont.memoriser(TYPE_ACCEPTE, _devis_accepte(), evenements_m10)
    amont.memoriser(TYPE_ACCEPTE, _devis_accepte(), evenements_m10)

    assert len(_de_type(evenements_m10, TYPE_ACCEPTE)) == 1
    assert len(_de_type(evenements_m10, TYPE_MONTANTS)) == 1


def test_un_compagnon_manquant_est_ecrit_sans_doubler_l_etape(evenements_m10):
    """Un registre où l'étape est déjà là sans son compagnon (écriture interrompue) : le rejeu écrit le compagnon."""
    resultat, _ = amont.memoriser(TYPE_ACCEPTE, _devis_accepte(), evenements_m10)
    seul = registre.Registre()
    seul.ajouter({key: value for key, value in resultat["maillon"].items()
                  if key not in ("ligne_id", "precedent_ligne_id")})

    rejeu, _ = amont.memoriser(TYPE_ACCEPTE, _devis_accepte(), seul)

    assert len(_de_type(seul, TYPE_ACCEPTE)) == 1 and len(_de_type(seul, TYPE_MONTANTS)) == 1
    assert rejeu["deja_memorise"] is False and rejeu["montants"]["confidentialite"] == "FINANCIAL"


def test_un_rejeu_qui_porte_d_autres_faits_est_dit_et_l_original_reste(evenements_m10):
    premier, _ = amont.memoriser(TYPE_CLIENT, _client_associe(), evenements_m10)

    autre, _ = amont.memoriser(TYPE_CLIENT, _client_associe(client_id="ab" * 32), evenements_m10)

    assert autre["identique"] is False and autre["deja_memorise"] is True
    assert autre["maillon"]["ligne_id"] == premier["maillon"]["ligne_id"]
    (seul,) = _de_type(evenements_m10, TYPE_CLIENT)
    assert seul["client_id"] == CLIENT_ID  # rien n'est écrasé, rien n'est fusionné


def test_deux_devis_d_un_meme_lead_sont_deux_faits_et_deux_leads_ne_se_melangent_pas(evenements_m10):
    amont.memoriser(TYPE_ACCEPTE, _devis_accepte("DEVIS-A"), evenements_m10)
    amont.memoriser(TYPE_ACCEPTE, _devis_accepte("DEVIS-C"), evenements_m10)
    amont.memoriser(TYPE_ACCEPTE, _devis_accepte("DEVIS-D", lead_id="LEAD-AUTRE"), evenements_m10)

    assert sorted(m["devis_id"] for m in _de_type(evenements_m10, TYPE_ACCEPTE)) == ["DEVIS-A", "DEVIS-C", "DEVIS-D"]
    tous = evenements_m10.lire()
    assert sorted(m["devis_id"] for m in classification.evenements_de_laffaire("LEAD-AUTRE", tous)
                  if classification.type_evenement(m) == TYPE_ACCEPTE) == ["DEVIS-D"]


# =========================================================================================
# 5. Ordre : un fait qui arrive avant celui qui le précède ne se perd pas et ne bloque personne
# =========================================================================================
@pytest.mark.parametrize("ordre", list(itertools.permutations(TYPES_DE_L_AMONT)))
def test_dans_n_importe_quel_ordre_chaque_fait_est_ecrit_une_fois(evenements_m10, ordre):
    """Les 24 ordres d'arrivée donnent le même registre, au rang près : lead, client, devis, son compagnon, sans
    réponse. C'est le défaut de T1.5-d (un maillon du même `lead_id` faisait croire le WCT déjà mémorisé),
    éprouvé sur les quatre types."""
    for type_evenement in ordre:
        resultat, verdict = amont.memoriser(type_evenement, CHARGES[type_evenement](), evenements_m10)
        assert verdict is None
        assert resultat["deja_memorise"] is False, f"{type_evenement} pris pour déjà mémorisé"

    types = sorted(classification.type_evenement(m) for m in evenements_m10.lire())
    assert types == sorted([TYPE_LEAD, TYPE_CLIENT, TYPE_ACCEPTE, TYPE_MONTANTS, TYPE_SANS_REPONSE])
    assert evenements_m10.valider_chaine() == (True, "")
    situation = amont.situation(LEAD, evenements_m10.lire())
    assert situation == {"connue": True, "origine_recue": True, "verdict": None}


def test_un_devis_recu_avant_son_lead_ne_fait_pas_croire_le_lead_memorise(evenements_m10):
    amont.memoriser(TYPE_ACCEPTE, _devis_accepte(), evenements_m10)
    amont.memoriser(TYPE_CLIENT, _client_associe(), evenements_m10)

    lead, verdict = amont.memoriser(TYPE_LEAD, _lead_qualifie(), evenements_m10)

    assert verdict is None and lead["deja_memorise"] is False
    assert len(_de_type(evenements_m10, TYPE_LEAD)) == 1


def test_un_wct_recu_apres_l_amont_est_toujours_ecrit_et_l_amont_apres_un_wct_aussi(evenements_m10):
    """Même principe que `test_une_rentabilite_recue_avant_son_wct_ne_fait_pas_oublier_le_wct`, dans les deux sens :
    le WCT porte le même `lead_id` et le même `devis_id` que l'amont."""
    amont.memoriser(TYPE_ACCEPTE, _devis_accepte(), evenements_m10)
    wct_ecrit, verdict = wct.memoriser_wct(_wct(), evenements_m10)
    assert verdict is None and classification.type_evenement(wct_ecrit) == classification.TYPE_WCT

    autre = registre.Registre()
    wct.memoriser_wct(_wct(), autre)
    resultat, _ = amont.memoriser(TYPE_LEAD, _lead_qualifie(), autre)
    assert resultat["deja_memorise"] is False
    assert sorted(classification.type_evenement(m) for m in autre.lire()) == sorted(
        [classification.TYPE_WCT, TYPE_LEAD])


def test_un_lead_inconnu_donne_un_verdict_clair_et_aucune_affaire_n_est_inventee(evenements_m10):
    inconnu = amont.situation("LEAD-JAMAIS-VU", evenements_m10.lire())
    assert inconnu == {"connue": False, "origine_recue": False, "verdict": amont.AMONT_AFFAIRE_INCONNUE}

    # Un devis accepté seul : le fait est gardé sous son lead_id, l'origine est dite non reçue, rien n'est fabriqué.
    resultat, _ = amont.memoriser(TYPE_ACCEPTE, _devis_accepte(), evenements_m10)
    assert resultat["affaire"] == {"connue": True, "origine_recue": False, "verdict": amont.AMONT_ORIGINE_NON_RECUE}
    assert _de_type(evenements_m10, TYPE_LEAD) == [] and _de_type(evenements_m10, TYPE_CLIENT) == []
    assert amont.situation("LEAD-AUTRE", evenements_m10.lire())["verdict"] == amont.AMONT_AFFAIRE_INCONNUE

    # Le lead arrive : l'origine est reçue, le verdict s'efface.
    resultat, _ = amont.memoriser(TYPE_LEAD, _lead_qualifie(), evenements_m10)
    assert resultat["affaire"] == {"connue": True, "origine_recue": True, "verdict": None}


# =========================================================================================
# 6. La classification lit l'amont : type, clé publique, affaire directe
# =========================================================================================
def test_la_classification_reconnait_chaque_fait_et_sa_cle_publique(evenements_m10):
    _memoriser_tout(evenements_m10, avec_wct=True)

    lus = {(classification.type_evenement(m), classification.identifiant(m)) for m in evenements_m10.lire()}
    assert lus == {
        (TYPE_LEAD, LEAD), (TYPE_CLIENT, LEAD), (TYPE_ACCEPTE, "DEVIS-A"), (TYPE_MONTANTS, "DEVIS-A"),
        (TYPE_SANS_REPONSE, "DEVIS-B"), (classification.TYPE_WCT, "WCT-AMONT-1")}


def test_l_affaire_d_un_fait_de_l_amont_est_son_lead_id_jamais_devinee(evenements_m10):
    _memoriser_tout(evenements_m10)
    tous = evenements_m10.lire()
    index = classification.index_lead_id_par_wct_id(tous)

    assert {classification.lead_id(m, index) for m in tous} == {LEAD}
    assert len(classification.evenements_de_laffaire(LEAD, tous)) == 5
    assert classification.evenements_de_laffaire("LEAD-AUTRE", tous) == []


def test_un_maillon_qui_ressemble_a_l_amont_sans_en_etre_n_est_pas_classifie():
    forge = {"type_entree": "evenement_memorise", "type_evenement": "m3.devis_accepte:autre", "devis_id": "X"}
    autre_registre = {"type_entree": "decision_enregistree", "type_evenement": TYPE_LEAD, "lead_id": LEAD}

    assert classification.type_evenement(forge) is None and classification.identifiant(forge) is None
    assert classification.type_evenement(autre_registre) is None
    assert classification.lead_id(forge, {}) is None


# =========================================================================================
# 7. Le paquet : l'historique avec provenance et heure, filtré par confidentialité
# =========================================================================================
def test_le_paquet_montre_l_historique_avec_provenance_et_heure_de_l_evenement(registres):
    registre_evenements, registre_affaires = registres
    _memoriser_tout(registre_evenements, avec_wct=True)

    paquet = paquets.assembler_paquet_contexte(
        LEAD, HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent="m03-estimation",
        n_faits_max_par_couche=9, budget_caracteres=9000)

    faits = _faits_recents(paquet)
    # Plus récent d'abord ; le client (CLIENT_PRIVATE) et les montants (FINANCIAL) ne sont pas rendus à M3.
    assert [(f["horodatage"], f["source"], f["identifiant"]) for f in faits] == [
        (HORODATAGE_WCT, classification.TYPE_WCT, "WCT-AMONT-1"),
        (HORODATAGE_DEVIS_A, TYPE_ACCEPTE, "DEVIS-A"),
        (HORODATAGE_CONSTAT, TYPE_SANS_REPONSE, "DEVIS-B"),
        (HORODATAGE_LEAD, TYPE_LEAD, LEAD),
    ]
    assert paquet["confidentialite"]["nb_retenus"] == 2  # le client associé et les montants, comptés sans être dits
    assert all(f["confidentialite"] == "INTERNAL" for f in faits)
    resumes = {f["source"]: f["resume"] for f in faits}
    assert resumes[TYPE_LEAD] == "Lead qualifié : service gouttieres, canal texte, urgence déclarée"
    assert resumes[TYPE_ACCEPTE] == "Devis DEVIS-A accepté, chantier CH-AMONT-1"
    assert resumes[TYPE_SANS_REPONSE] == (
        f"Devis DEVIS-B (envoye) sans réponse depuis {HORODATAGE_DEVIS_B}, délai de relance 7 j")
    assert HORODATAGE_PAQUET not in json.dumps(faits)  # l'horloge de la lecture n'est jamais l'heure d'un fait


@pytest.mark.parametrize(("agent", "voit_le_client"), [
    (None, False), ("m01-front-office", True), ("m02-revenue-crm", True), ("m03-estimation", False),
    ("m04-field-ops", False), ("m05-financecore", False), ("m07-marketing", False), ("m08-analytics", False),
    ("m10-memoire", False),
])
def test_le_client_associe_ne_sort_que_vers_m1_et_m2(registres, agent, voit_le_client):
    registre_evenements, registre_affaires = registres
    _memoriser_tout(registre_evenements)

    paquet = paquets.assembler_paquet_contexte(
        LEAD, HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent=agent, n_faits_max_par_couche=9,
        budget_caracteres=9000)

    sources = [f["source"] for f in _faits_recents(paquet)]
    texte = json.dumps(paquet, ensure_ascii=False)
    assert (TYPE_CLIENT in sources) is voit_le_client
    assert (CLIENT_ID in texte) is voit_le_client
    assert paquet["confidentialite"]["nb_retenus"] == (1 if voit_le_client else 2)  # les montants, toujours retenus
    if voit_le_client:
        (fait,) = [f for f in _faits_recents(paquet) if f["source"] == TYPE_CLIENT]
        assert fait["confidentialite"] == "CLIENT_PRIVATE" and fait["horodatage"] == HORODATAGE_CLIENT


@pytest.mark.parametrize("agent", [None, "m01-front-office", "m02-revenue-crm", "m03-estimation", "m05-financecore",
                                    "m08-analytics"])
def test_le_prix_et_le_cout_ne_sortent_dans_aucun_paquet_pour_aucun_agent(registres, agent):
    registre_evenements, registre_affaires = registres
    _memoriser_tout(registre_evenements, avec_wct=True)

    paquet = paquets.assembler_paquet_contexte(
        LEAD, HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent=agent, n_faits_max_par_couche=9,
        budget_caracteres=9000)

    texte = json.dumps(paquet, ensure_ascii=False)
    for montant in MONTANTS_DU_DEVIS:
        assert montant not in texte, (agent, montant)
    assert TYPE_MONTANTS not in texte and "montants" not in texte.lower()
    # ... mais ils sont bien au registre, au niveau FINANCIAL : classés, pas jetés.
    (compagnon,) = _de_type(registre_evenements, TYPE_MONTANTS)
    assert (compagnon["prix_total"], compagnon["cout_total"]) == ("1249.75", "812.50")


def test_le_resume_des_montants_ne_porte_aucun_montant_meme_si_le_marquage_se_perdait(registres):
    """Défense en profondeur (patron de `test_rentabilite`) : un compagnon écrit SANS niveau serait INTERNAL, donc
    rendu ; son résumé n'a de toute façon aucun montant."""
    registre_evenements, registre_affaires = registres
    resultat, _ = amont.memoriser(TYPE_ACCEPTE, _devis_accepte(), registre_evenements)
    forge = {cle: valeur for cle, valeur in resultat["montants"].items()
             if cle not in ("ligne_id", "precedent_ligne_id", "confidentialite")}
    autre = registre.Registre()
    autre.ajouter(forge)

    paquet = paquets.assembler_paquet_contexte(
        LEAD, HORODATAGE_PAQUET, autre, registre_affaires, agent="m01-front-office")

    (fait,) = _faits_recents(paquet)
    assert fait["source"] == TYPE_MONTANTS and fait["resume"] == "Montants du devis DEVIS-A (niveau financier)"
    for montant in MONTANTS_DU_DEVIS:
        assert montant not in json.dumps(paquet, ensure_ascii=False)


def test_le_paquet_garde_ses_quatre_couches_et_dit_ce_qu_il_omet(registres):
    registre_evenements, registre_affaires = registres
    for numero in range(8):
        amont.memoriser(TYPE_ACCEPTE, _devis_accepte(f"DEVIS-{numero}"), registre_evenements)

    paquet = paquets.assembler_paquet_contexte(
        LEAD, HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent="m03-estimation")

    assert [c["nom"] for c in paquet["couches"]] == [
        paquets.COUCHE_REGLES_ENTREPRISE, paquets.COUCHE_FAITS_AFFAIRE, paquets.COUCHE_EVENEMENTS_RECENTS,
        paquets.COUCHE_SIGNAUX_NON_RESOLUS]
    couche = _couche(paquet, paquets.COUCHE_EVENEMENTS_RECENTS)
    assert couche["nb_total"] == 8 and couche["tronque"] is True
    assert couche["nb_inclus"] + couche["nb_omis"] == 8 and couche["nb_omis"] >= 1
    assert paquet["caracteres_utilises"] <= paquet["budget_caracteres"]
    assert paquet["confidentialite"]["nb_retenus"] == 8  # un compagnon financier par devis


def test_la_forme_du_paquet_ne_change_pas_et_un_lead_inconnu_donne_quatre_couches_vides(registres):
    """La forme du paquet est épinglée contre les fixtures du core (`tests/test_openclaw_contexte.py`) : l'amont
    n'y ajoute aucune clé. Un lead inconnu n'y a aucun fait, aucune retenue, et M10 n'en invente pas."""
    registre_evenements, registre_affaires = registres
    _memoriser_tout(registre_evenements)

    connu = paquets.assembler_paquet_contexte(
        LEAD, HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent="m03-estimation")
    inconnu = paquets.assembler_paquet_contexte(
        "LEAD-JAMAIS-VU", HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent="m03-estimation")

    forme = {"affaire_id", "horodatage", "budget_caracteres", "caracteres_utilises", "couches", "signaux",
             "confidentialite"}
    assert set(connu) == forme and set(inconnu) == forme
    assert all(couche["vide"] for couche in inconnu["couches"])
    assert inconnu["confidentialite"]["nb_retenus"] == 0
    assert amont.situation("LEAD-JAMAIS-VU", registre_evenements.lire())["verdict"] == amont.AMONT_AFFAIRE_INCONNUE


# =========================================================================================
# 8. La consolidation nocturne et l'audit « non-oubli » couvrent l'amont
# =========================================================================================
def test_la_consolidation_compte_l_amont_dans_l_ordre_de_l_entonnoir_sans_montant_ni_client(registres):
    registre_evenements, registre_affaires = registres
    for type_evenement in (TYPE_LEAD, TYPE_CLIENT):
        amont.memoriser(type_evenement, CHARGES[type_evenement](), registre_evenements)

    resultat = consolidation.consolider_affaire(
        LEAD, JOUR_LEAD, HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    assert resultat["ecrit"] is True and resultat["verdict"] is None
    fait = resultat["fait"]
    assert fait["resume"] == "1 lead(s) qualifié(s), 1 client(s) associé(s)"
    assert {(s["type_evenement"], s["identifiant"]) for s in fait["sources"]} == {
        (TYPE_LEAD, LEAD), (TYPE_CLIENT, LEAD)}
    assert CLIENT_ID not in json.dumps(fait) and confidentialite.niveau_de(fait) == "INTERNAL"

    encore = consolidation.consolider_affaire(
        LEAD, JOUR_LEAD, HORODATAGE_PAQUET, registre_evenements, registre_affaires)
    assert encore["ecrit"] is False and encore["deja_consolide"] is True
    assert len(registre_affaires.lire()) == 1


def test_la_consolidation_du_jour_d_un_devis_compte_le_devis_une_fois_et_cite_le_compagnon_sans_montant(registres):
    registre_evenements, registre_affaires = registres
    _memoriser_tout(registre_evenements, avec_wct=True)

    accepte = consolidation.consolider_affaire(
        LEAD, "2026-09-14", HORODATAGE_PAQUET, registre_evenements, registre_affaires)["fait"]
    sans_reponse = consolidation.consolider_affaire(
        LEAD, "2026-09-12", HORODATAGE_PAQUET, registre_evenements, registre_affaires)["fait"]
    chantier = consolidation.consolider_affaire(
        LEAD, "2026-09-15", HORODATAGE_PAQUET, registre_evenements, registre_affaires)["fait"]

    assert accepte["resume"] == "1 devis accepté(s)"  # le compagnon financier n'est pas un devis de plus
    assert {s["type_evenement"] for s in accepte["sources"]} == {TYPE_ACCEPTE, TYPE_MONTANTS}
    assert sans_reponse["resume"] == "1 devis sans réponse"
    assert chantier["resume"] == "1 travaux terminés"
    for fait in (accepte, sans_reponse, chantier):
        for montant in MONTANTS_DU_DEVIS:
            assert montant not in json.dumps(fait, ensure_ascii=False)


def test_la_consolidation_ne_confond_pas_les_affaires_et_dit_un_jour_sans_evenement(registres):
    registre_evenements, registre_affaires = registres
    _memoriser_tout(registre_evenements)

    autre = consolidation.consolider_affaire(
        "LEAD-AUTRE", JOUR_LEAD, HORODATAGE_PAQUET, registre_evenements, registre_affaires)
    vide = consolidation.consolider_affaire(
        LEAD, "2026-01-01", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    assert autre["verdict"] == consolidation.REJ_CONSOLIDATION_AUCUN_EVENEMENT and autre["fait"] is None
    assert vide["verdict"] == consolidation.REJ_CONSOLIDATION_AUCUN_EVENEMENT
    assert registre_affaires.lire() == []


@pytest.mark.parametrize(("type_evenement", "identifiant"), [
    (TYPE_LEAD, LEAD), (TYPE_CLIENT, LEAD), (TYPE_ACCEPTE, "DEVIS-A"), (TYPE_SANS_REPONSE, "DEVIS-B")])
def test_l_audit_verifie_la_trace_de_chaque_fait_de_l_amont(registres, type_evenement, identifiant):
    registre_evenements, registre_affaires = registres
    amont.memoriser(type_evenement, CHARGES[type_evenement](), registre_evenements)

    present = audit.auditer_non_oubli(
        [{"type_evenement": type_evenement, "identifiant": identifiant}], registre_evenements, registre_affaires)
    absent = audit.auditer_non_oubli(
        [{"type_evenement": type_evenement, "identifiant": "JAMAIS-RECU"}], registre_evenements, registre_affaires)

    assert present["nb_oublis"] == 0 and present["total_attendus"] == 1
    assert absent["oublis"] == [{
        "type_evenement": type_evenement, "identifiant": "JAMAIS-RECU", "verdict": audit.REJ_AUDIT_TRACE_ABSENTE}]


def test_l_audit_ne_prend_pas_un_lead_id_pour_un_devis_ni_un_type_pour_un_autre(registres):
    registre_evenements, registre_affaires = registres
    amont.memoriser(TYPE_CLIENT, _client_associe(), registre_evenements)

    rapport = audit.auditer_non_oubli(
        [{"type_evenement": TYPE_LEAD, "identifiant": LEAD}, {"type_evenement": TYPE_ACCEPTE, "identifiant": LEAD}],
        registre_evenements, registre_affaires)

    assert rapport["nb_oublis"] == 2  # le client associé de ce lead n'est ni son lead ni un devis


def test_l_outil_d_audit_accepte_les_quatre_types_de_l_amont_dans_son_schema():
    outil = next(o for o in outils_mod.outils() if o.nom == "m10_auditer_non_oubli")
    enum = outil.parametres["properties"]["identifiants_attendus"]["items"]["properties"]["type_evenement"]["enum"]

    assert enum == list(audit.types_audites())
    assert set(TYPES_DE_L_AMONT) <= set(enum) and TYPE_MONTANTS not in enum


# =========================================================================================
# 9. m3.devis_envoye s'ajoute sans refonte : une entrée de la table, une ligne du manifeste
# =========================================================================================
def _extraire_devis_envoye(charge):
    return {
        "lead_id": charge["lead_id"], "devis_id": charge["devis_id"], "chantier_id": None,
        "horodatage": charge["horodatage_envoi"],
    }


@pytest.fixture
def avec_devis_envoye(monkeypatch):
    """Ce que T4.7 ajoutera : une étape de plus dans la table, sans toucher aucun autre module."""
    fictive = etapes.Etape(
        "m3.devis_envoye", "m03-estimation", "devis_id", "devis envoyé(s)", confidentialite.NIVEAU_INTERNE,
        _extraire_devis_envoye, lambda m: f"Devis {m.get('devis_id')} envoyé")
    monkeypatch.setattr(etapes, "_ETAPES", (*etapes.etapes_de_l_amont(), fictive))
    return fictive


def test_une_etape_de_plus_est_lue_par_toute_la_chaine_sans_autre_changement(avec_devis_envoye, registres):
    registre_evenements, registre_affaires = registres
    charge = {"lead_id": LEAD, "devis_id": "DEVIS-E", "horodatage_envoi": "2026-09-11T09:00:00-04:00"}

    resultat, verdict = amont.memoriser("m3.devis_envoye", charge, registre_evenements)
    assert verdict is None and resultat["maillon"]["confidentialite"] == "INTERNAL"
    assert amont.memoriser("m3.devis_envoye", charge, registre_evenements)[0]["deja_memorise"] is True

    assert "m3.devis_envoye" in etapes.types_consommes()
    assert "m3.devis_envoye" in outils_mod.consommateurs()  # le manifeste, lui, devrait la déclarer
    assert "m3.devis_envoye" in audit.types_audites()
    maillon = registre_evenements.lire()[0]
    assert (classification.type_evenement(maillon), classification.identifiant(maillon)) == (
        "m3.devis_envoye", "DEVIS-E")
    paquet = paquets.assembler_paquet_contexte(
        LEAD, HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent="m03-estimation")
    (fait,) = _faits_recents(paquet)
    assert (fait["source"], fait["resume"], fait["horodatage"]) == (
        "m3.devis_envoye", "Devis DEVIS-E envoyé", "2026-09-11T09:00:00-04:00")
    consolide = consolidation.consolider_affaire(LEAD, "2026-09-11", HORODATAGE_PAQUET, registre_evenements,
                                                 registre_affaires)
    assert consolide["fait"]["resume"] == "1 devis envoyé(s)"
    rapport = audit.auditer_non_oubli(
        [{"type_evenement": "m3.devis_envoye", "identifiant": "DEVIS-E"}], registre_evenements, registre_affaires)
    assert rapport["nb_oublis"] == 0


def test_sans_cette_entree_le_type_n_est_pas_consomme(registres):
    registre_evenements, _ = registres

    assert "m3.devis_envoye" not in outils_mod.consommateurs()
    assert "m3.devis_envoye" not in audit.types_audites()
    assert amont.memoriser("m3.devis_envoye", {"lead_id": LEAD}, registre_evenements)[1]["code"] == (
        etapes.REJ_AMONT_TYPE_INCONNU)


# =========================================================================================
# 10. Le VRAI bus : lead, client associé, devis accepté, paquet lu ; rejeu ; ordre inversé ; consommateur retiré
# =========================================================================================
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


PRODUCTEURS = {TYPE_LEAD: "m01-front-office", TYPE_CLIENT: "m02-revenue-crm", TYPE_ACCEPTE: "m03-estimation",
               TYPE_SANS_REPONSE: "m03-estimation"}


def _publier(type_evenement, charge=None, evenement_id=None):
    charge = CHARGES[type_evenement]() if charge is None else charge
    cle = (charge["lead"]["lead_id"] if type_evenement == TYPE_LEAD
           else charge["lead_id"] if type_evenement == TYPE_CLIENT else charge["devis_id"])
    evenement_id = evenement_id or f"{type_evenement.replace('.', '-').replace('_', '-')}-{cle}"
    evenements.publier(type_evenement, PRODUCTEURS[type_evenement], charge, evenement_id=evenement_id)
    return evenement_id


def _deps_bus():
    """Seul M10 reçoit les événements de ces tests : les comptes de `repartir()` sont globaux, et chaque autre
    consommateur (M2, M4, M5, M6, M8…) les changerait."""
    return {"m10-memoire": charger_departements()["m10-memoire"]}


def _repartir(deps=None, maintenant="2026-09-16T07:00:00-04:00"):
    return evenements.repartir(deps or _deps_bus(), maintenant=maintenant)


def _registre_m10():
    return stockage.maillons("m10-memoire", "evenements")


def _quarantaine_m10():
    return [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == "m10-memoire"]


def _recu_m10(evenement_id):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == "m10-memoire")
        )).mappings().first()
    assert ligne is not None, evenement_id
    return {**dict(ligne), "resultat": codec.decoder(ligne["resultat"]) if ligne["resultat"] else None}


def _types_ecrits():
    return sorted(classification.type_evenement(m) for m in _registre_m10())


def test_le_bus_livre_lead_client_et_devis_a_m10_et_le_paquet_les_montre(base_durable):
    identifiants = [_publier(TYPE_LEAD), _publier(TYPE_CLIENT), _publier(TYPE_ACCEPTE), _publier(TYPE_SANS_REPONSE)]

    resume = _repartir()

    assert resume["traites"] == 4 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert _quarantaine_m10() == []
    assert _types_ecrits() == sorted([TYPE_LEAD, TYPE_CLIENT, TYPE_ACCEPTE, TYPE_MONTANTS, TYPE_SANS_REPONSE])
    for identifiant in identifiants:
        recu = _recu_m10(identifiant)
        assert recu["statut"] == "traite" and recu["resultat"]["memorise"] is True

    with stockage.transaction():
        paquet_m3 = outils_mod.paquet_contexte_affaire(LEAD, HORODATAGE_PAQUET, "m03-estimation")
        paquet_m1 = outils_mod.paquet_contexte_affaire(LEAD, HORODATAGE_PAQUET, "m01-front-office")
        sans_agent = outils_mod.paquet_contexte_affaire(LEAD, HORODATAGE_PAQUET)

    assert [f["source"] for f in _faits_recents(paquet_m3)] == [TYPE_ACCEPTE, TYPE_SANS_REPONSE, TYPE_LEAD]
    assert [f["source"] for f in _faits_recents(paquet_m1)] == [TYPE_ACCEPTE, TYPE_SANS_REPONSE, TYPE_CLIENT, TYPE_LEAD]
    assert [f["source"] for f in _faits_recents(sans_agent)] == [TYPE_ACCEPTE, TYPE_SANS_REPONSE, TYPE_LEAD]
    assert (paquet_m3["confidentialite"]["nb_retenus"], paquet_m1["confidentialite"]["nb_retenus"]) == (2, 1)
    for paquet in (paquet_m3, paquet_m1, sans_agent):
        texte = json.dumps(paquet, ensure_ascii=False)
        assert not [m for m in MONTANTS_DU_DEVIS if m in texte]
        assert HORODATAGE_PAQUET not in json.dumps(_faits_recents(paquet))
        assert not [c for c in CONFIDENCES_DU_CLIENT if c in texte]
    assert CLIENT_ID in json.dumps(paquet_m1) and CLIENT_ID not in json.dumps(paquet_m3)


def test_le_contact_du_lead_n_entre_dans_aucun_registre_ni_dans_aucun_reçu_du_bus(base_durable):
    for type_evenement in TYPES_DE_L_AMONT:
        _publier(type_evenement)
    _repartir()

    with stockage.transaction() as cnx:
        recus = json.dumps([dict(ligne) for ligne in cnx.execute(select(EVENEMENTS_RECUS)).mappings().all()],
                           default=str, ensure_ascii=False)
    tout_m10 = json.dumps([list(_registre_m10()), list(stockage.maillons("m10-memoire", "affaires"))],
                          default=str, ensure_ascii=False)
    for confidence in CONFIDENCES_DU_CLIENT:
        assert confidence not in tout_m10, confidence
        assert confidence not in recus, confidence
    assert DESCRIPTION_DE_LIGNE not in tout_m10


def test_un_rejeu_du_bus_ne_cree_aucun_doublon(base_durable):
    for type_evenement in TYPES_DE_L_AMONT:
        _publier(type_evenement)
    _repartir()
    avant = list(_registre_m10())

    encore = _repartir()  # redélivrance : rien n'est dû, ni pour M10 ni pour personne
    assert encore == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}

    # Le même fait relivré par un producteur en défaut, sous un evenement_id DIFFÉRENT.
    for type_evenement in TYPES_DE_L_AMONT:
        _publier(type_evenement, evenement_id=f"rejeu-manuel-{type_evenement}")
    resume = _repartir()

    assert resume["traites"] == 4 and resume["echecs"] == 0, resume
    assert list(_registre_m10()) == avant, "un rejeu ne crée ni doublon ni maillon de plus"
    recu = _recu_m10(f"rejeu-manuel-{TYPE_ACCEPTE}")
    assert recu["resultat"]["deja_memorise"] is True and recu["resultat"]["identique"] is True


def test_un_rejeu_qui_porte_d_autres_faits_est_dit_dans_le_recu_et_l_original_reste(base_durable):
    _publier(TYPE_CLIENT)
    _repartir()
    _publier(TYPE_CLIENT, _client_associe(client_id="ab" * 32), evenement_id="m2-client-associe-rejeu-different")
    _repartir()

    (client,) = [m for m in _registre_m10() if classification.type_evenement(m) == TYPE_CLIENT]
    assert client["client_id"] == CLIENT_ID
    recu = _recu_m10("m2-client-associe-rejeu-different")["resultat"]
    assert recu["deja_memorise"] is True and recu["identique"] is False


def test_a_l_envers_le_devis_puis_le_client_puis_le_lead_sont_tous_gardes_et_le_verdict_se_leve(base_durable):
    _publier(TYPE_ACCEPTE)
    _repartir()
    premier = _recu_m10(f"{TYPE_ACCEPTE.replace('.', '-').replace('_', '-')}-DEVIS-A")["resultat"]
    assert premier["origine_recue"] is False and premier["verdict"] == amont.AMONT_ORIGINE_NON_RECUE
    assert _de_type_durable(TYPE_LEAD) == []  # aucun lead n'est inventé pour faire joli

    _publier(TYPE_CLIENT)
    _repartir()
    assert _recu_m10(f"{TYPE_CLIENT.replace('.', '-').replace('_', '-')}-{LEAD}")["resultat"]["verdict"] == (
        amont.AMONT_ORIGINE_NON_RECUE)

    _publier(TYPE_LEAD)
    _repartir()
    dernier = _recu_m10(f"{TYPE_LEAD.replace('.', '-').replace('_', '-')}-{LEAD}")["resultat"]
    assert dernier["deja_memorise"] is False, "le lead reçu en dernier est écrit"
    assert dernier["origine_recue"] is True and dernier["verdict"] is None
    assert _types_ecrits() == sorted([TYPE_LEAD, TYPE_CLIENT, TYPE_ACCEPTE, TYPE_MONTANTS])
    with stockage.transaction():
        paquet = outils_mod.paquet_contexte_affaire(LEAD, HORODATAGE_PAQUET, "m01-front-office")
    assert [f["source"] for f in _faits_recents(paquet)] == [TYPE_ACCEPTE, TYPE_CLIENT, TYPE_LEAD]


def _de_type_durable(type_maillon):
    return [m for m in _registre_m10() if classification.type_evenement(m) == type_maillon]


def test_un_lead_inconnu_donne_un_paquet_vide_et_aucune_affaire_inventee_par_les_vrais_outils(base_durable):
    _publier(TYPE_LEAD)
    _repartir()

    with stockage.transaction():
        inconnu = outils_mod.paquet_contexte_affaire("LEAD-JAMAIS-VU", HORODATAGE_PAQUET, "m01-front-office")
        consolide = outils_mod.consolider_affaire("LEAD-JAMAIS-VU", JOUR_LEAD, HORODATAGE_PAQUET)

    assert all(couche["vide"] for couche in inconnu["couches"])
    assert inconnu["confidentialite"]["nb_retenus"] == 0
    assert consolide["ecrit"] is False and consolide["fait"] is None
    assert consolide["verdict"] == consolidation.REJ_CONSOLIDATION_AUCUN_EVENEMENT
    assert _types_ecrits() == [TYPE_LEAD]  # rien n'a été écrit pour l'affaire inconnue


def test_un_fait_hors_de_sa_forme_va_en_quarantaine_sans_ecriture_et_sans_citer_la_valeur(base_durable):
    charge = _lead_qualifie(service="Gouttières à Repentigny")  # passe le catalogue (texte non vide), pas M10
    _publier(TYPE_LEAD, charge)

    for tour in range(5):
        _repartir(maintenant=f"2026-09-16T07:{tour * 2:02d}:00-04:00")

    assert list(_registre_m10()) == [], "un fait refusé n'écrit rien"
    (ligne,) = _quarantaine_m10()
    assert ligne["tentatives"] == 5
    assert "AmontRefuse" in ligne["derniere_erreur"] and etapes.REJ_AMONT_CHAMP_INVALIDE in ligne["derniere_erreur"]
    assert "lead/service" in ligne["derniere_erreur"]
    assert "Repentigny" not in ligne["derniere_erreur"]  # le champ, jamais la valeur


def test_la_consolidation_et_l_audit_par_les_vrais_outils_couvrent_l_amont(base_durable):
    identifiants_attendus = [
        {"type_evenement": TYPE_LEAD, "identifiant": LEAD}, {"type_evenement": TYPE_CLIENT, "identifiant": LEAD},
        {"type_evenement": TYPE_ACCEPTE, "identifiant": "DEVIS-A"},
        {"type_evenement": TYPE_SANS_REPONSE, "identifiant": "DEVIS-B"},
    ]
    for type_evenement in TYPES_DE_L_AMONT:
        _publier(type_evenement)
    _repartir()

    with stockage.transaction():
        consolide = outils_mod.consolider_affaire(LEAD, JOUR_LEAD, HORODATAGE_PAQUET)
        rapport = outils_mod.auditer_non_oubli(identifiants_attendus)
        encore = outils_mod.consolider_affaire(LEAD, JOUR_LEAD, HORODATAGE_PAQUET)

    assert consolide["ecrit"] is True and consolide["fait"]["resume"] == "1 lead(s) qualifié(s), 1 client(s) associé(s)"
    assert encore["ecrit"] is False and encore["deja_consolide"] is True
    assert rapport["nb_oublis"] == 0 and rapport["total_attendus"] == 4
    assert rapport["chaine_evenements_intacte"] is True and rapport["chaine_affaires_intacte"] is True


@pytest.mark.parametrize("retire", TYPES_DE_L_AMONT)
def test_un_consommateur_retire_du_manifeste_est_detecte_par_l_audit_non_oubli(base_durable, retire):
    """Le bus publie les quatre faits ; M10 n'en reçoit que trois, le manifeste ayant perdu un type. L'audit, à qui
    l'on dit ce que le bus a publié, nomme le fait dont la trace manque — et lui seul. Avec le manifeste complet,
    aucun oubli."""
    attendus = [
        {"type_evenement": TYPE_LEAD, "identifiant": LEAD}, {"type_evenement": TYPE_CLIENT, "identifiant": LEAD},
        {"type_evenement": TYPE_ACCEPTE, "identifiant": "DEVIS-A"},
        {"type_evenement": TYPE_SANS_REPONSE, "identifiant": "DEVIS-B"},
    ]
    for type_evenement in TYPES_DE_L_AMONT:
        _publier(type_evenement)
    reel = charger_departements()["m10-memoire"]
    sans_le_type = dataclasses.replace(
        reel, evenements_consomme=tuple(t for t in reel.evenements_consomme if t != retire))

    # `opsys verifier` voit déjà l'incohérence : une fonction de consommateurs() orpheline.
    assert any(retire in probleme and "orpheline" in probleme
               for probleme in evenements.verifier_coherence({"m10-memoire": sans_le_type}))

    _repartir({"m10-memoire": sans_le_type})
    with stockage.transaction():
        rapport = outils_mod.auditer_non_oubli(attendus)

    assert rapport["nb_oublis"] == 1, rapport
    (oubli,) = rapport["oublis"]
    assert oubli["type_evenement"] == retire and oubli["verdict"] == audit.REJ_AUDIT_TRACE_ABSENTE

    # Le manifeste complet est rétabli : le bus livre ce qui manquait (jamais livré, donc jamais « traité »).
    _repartir({"m10-memoire": reel}, maintenant="2026-09-16T07:10:00-04:00")
    with stockage.transaction():
        complet = outils_mod.auditer_non_oubli(attendus)
    assert complet["nb_oublis"] == 0 and complet["total_attendus"] == 4


def test_les_consommateurs_du_manifeste_de_m10_sont_ceux_de_la_table_et_du_chantier():
    dep = charger_departements()["m10-memoire"]
    fonctions = dep.charger_consommateurs()

    assert set(fonctions) == set(dep.evenements_consomme)
    assert [t for t in dep.evenements_consomme if t in TYPES_DE_L_AMONT] == list(TYPES_DE_L_AMONT)
    for type_evenement in TYPES_DE_L_AMONT:
        assert callable(fonctions[type_evenement])
