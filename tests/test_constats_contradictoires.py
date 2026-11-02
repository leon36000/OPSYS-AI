"""Un constat rejoué avec la MÊME clé de contenu mais un contenu DIFFÉRENT est dit, jamais avalé (M2, M5, M8).

Défaut fermé (revue adverse rvi, INTERCONNEXION.md §7) : l'idempotence par clé de contenu ignorait sans alerte un
contenu contradictoire (même `relance_id`, même `releve_id` + révision) ; seul M10 nommait la contradiction de sceau.
Règle commune (`opsys.evenements.constats`) : le PREMIER état reste, rien n'est écrasé, la contradiction est rangée au
registre `constats_contradictoires` (noms des champs, jamais les valeurs), dite au bus et exposée dans l'état de lecture
du département ; le rejeu IDENTIQUE reste silencieux. Bus réel, consommateurs réels. Fictif.
"""

from __future__ import annotations

import json

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m2_revenue_crm import faits_interconnexion as fi
from m5_financecore import charges_marketing_recues as cmr
from m5_financecore import outils as outils_m5
from m8_analytics import operations_recues as ops_m8
from m8_analytics import outils as outils_m8

from opsys import evenements
from opsys.evenements import constats
from opsys.outils import executer_atomique
from opsys.stockage import codec

FICTIF = True
M2, M3, M5, M7, M8 = "m02-revenue-crm", "m03-estimation", "m05-financecore", "m07-marketing", "m08-analytics"
AUDIT = constats.REGISTRE


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M2, M3, M5, M7, M8))
    m.surveiller(monkeypatch)
    yield m
    im.demonter()


def _pub(producteur, type_evenement, charge, ident):
    evenements.publier(type_evenement, producteur, charge, evenement_id=ident)


def _resultat_recu(monde, ident, consommateur):
    (recu,) = [r for r in monde.recus(consommateur=consommateur) if r["evenement_id"] == ident]
    assert recu["statut"] == "traite", recu
    return codec.decoder(recu["resultat"])


# ------------------------------------------------------------------------------------------------ M2
def test_m2_relance_de_meme_cle_et_contenu_different_premier_garde_contradiction_rangee_et_dite(monde):
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1", niveau=1), "r1")
    monde.repartir()
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1", niveau=4, jours_retard=90), "r2")
    resume = monde.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    (creance,) = monde.registre(M2, fi.REGISTRE_CREANCES)
    assert creance["niveau"] == 1 and creance["jours_retard"] == 12  # le PREMIER état n'est jamais écrasé
    (audit,) = monde.registre(M2, AUDIT)
    assert audit["constat"] == "creance_relance_recue" and audit["cle"] == {"relance_id": "rel-1"}
    assert audit["champs"] == ["jours_retard", "niveau"]  # les NOMS, jamais les valeurs
    assert audit["empreinte_premier"] != audit["empreinte_nouveau"] and audit["regle"] == constats.REGLE
    for valeur in ("4500", "2300", ": 90"):
        assert valeur not in json.dumps(audit)
    dit = _resultat_recu(monde, "r2", M2)
    assert dit["contradiction"] == constats.CODE and dit["champs"] == ["jours_retard", "niveau"]
    assert monde.ecritures_hors_propriete() == []


def test_m2_rejeu_identique_reste_silencieux(monde):
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1"), "r1")
    monde.repartir()
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1"), "r2")
    monde.repartir()
    assert monde.registre(M2, AUDIT) == []
    dit = _resultat_recu(monde, "r2", M2)
    assert "contradiction" not in dit and dit["deja_enregistre"] is True


def test_m2_la_meme_contradiction_rejouee_n_ajoute_pas_de_seconde_ligne_d_audit(monde):
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1", niveau=1), "r1")
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1", niveau=3), "r2")
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1", niveau=3), "r3")
    monde.repartir()
    assert len(monde.registre(M2, AUDIT)) == 1
    # un TROISIÈME contenu différent est une autre contradiction
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1", niveau=4), "r4")
    monde.repartir()
    assert len(monde.registre(M2, AUDIT)) == 2
    assert [c["niveau"] for c in monde.registre(M2, fi.REGISTRE_CREANCES)] == [1]


def test_m2_conversion_et_contexte_de_site_suivent_la_meme_regle(monde):
    _pub(M7, "m7.conversion_hors_ligne_importee", ch.conversion_hors_ligne(conversion_id="c1", source="google"), "c-a")
    _pub(M7, "m7.conversion_hors_ligne_importee", ch.conversion_hors_ligne(conversion_id="c1", source="meta"), "c-b")
    _pub(M3, "m3.contexte_site_pret", ch.contexte_site(lead_id="lead-s", version=1), "s-a")
    _pub(M3, "m3.contexte_site_pret", ch.contexte_site(lead_id="lead-s", version=1, service="bardeau"), "s-b")
    monde.repartir()
    constats_audit = {a["constat"]: a for a in monde.registre(M2, AUDIT)}
    assert set(constats_audit) == {"conversion_hors_ligne_recue", "contexte_site_recu"}
    assert constats_audit["conversion_hors_ligne_recue"]["champs"] == ["utm_source"]
    assert constats_audit["contexte_site_recu"]["champs"] == ["service"]
    assert [c["utm_source"] for c in monde.registre(M2, fi.REGISTRE_CONVERSIONS)] == ["google"]


def test_m2_une_facture_close_n_a_pas_de_contenu_a_contredire(monde):
    _pub(M5, "m5.facture_emise_constatee", ch.facture_emise(facture_id="F-1", statut="PAYEE", avant="1.00"), "f1")
    _pub(M5, "m5.facture_emise_constatee", ch.facture_emise(facture_id="F-1", statut="PAYEE", avant="2.00"), "f2")
    monde.repartir()
    assert monde.registre(M2, AUDIT) == [] and monde.taille(M2, fi.REGISTRE_FACTURES_CLOSES) == 1


# ------------------------------------------------------------------------------------------------ M5
def test_m5_releve_de_meme_cle_et_montant_different_premier_brouillon_garde_contradiction_rangee(monde):
    _pub(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(montant="125.40"), "d1")
    monde.repartir()
    _pub(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(montant="999.99"), "d2")
    resume = monde.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    (ligne,) = monde.registre(M5, cmr.REGISTRE)
    assert ligne["issue"] == cmr.BROUILLON_PROPOSE  # un seul brouillon, au premier montant
    (ecriture,) = monde.registre(M5, "grand_livre")
    assert {str(m["debit"]) for m in ecriture["lignes"] if m["debit"]} == {"125.40"}
    (audit,) = monde.registre(M5, AUDIT)
    assert audit["constat"] == "m7.depenses_marketing_constatees"
    assert audit["cle"] == {"releve_id": "releve-google-2026-10-27", "revision": 1}
    assert audit["champs"] is None and audit["empreinte_premier"] == ligne["empreinte_contenu"]
    assert audit["empreinte_nouveau"] == cmr.empreinte_contenu(ch.depense_marketing(montant="999.99"))
    assert "999.99" not in json.dumps(audit) and "125.40" not in json.dumps(audit)
    assert _resultat_recu(monde, "d2", M5)["contradiction"] == constats.CODE


def test_m5_rejeu_identique_reste_silencieux_et_une_autre_revision_n_est_pas_une_contradiction(monde):
    _pub(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(montant="125.40"), "d1")
    monde.repartir()
    _pub(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(montant="125.40"), "d2")
    _pub(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(revision=2, montant="130.00"), "d3")
    monde.repartir()
    assert monde.registre(M5, AUDIT) == []
    assert "contradiction" not in _resultat_recu(monde, "d2", M5)


def test_m5_chaque_champ_du_contenu_compte(monde):
    base = ch.depense_marketing(montant="10.00")
    _pub(M7, "m7.depenses_marketing_constatees", base, "d0")
    monde.repartir()
    variantes = {
        "canal": "meta",
        "periode_debut": "2026-10-26",
        "periode_fin": "2026-10-27",
        "montant_cad": "10.01",
        "devise": "CAD",
        "base_taxes": "TAXES_INCLUSES",
        "source": "RELEVE_PLATEFORME",
        "releve_le": "2026-10-29T06:00:00-04:00",
    }
    attendues = 0
    for champ, valeur in variantes.items():
        charge = {**base, champ: valeur}
        if charge == base:
            continue
        _pub(M7, "m7.depenses_marketing_constatees", charge, f"v-{champ}")
        monde.repartir()
        attendues += 1
        assert len(monde.registre(M5, AUDIT)) == attendues, champ


def test_m5_l_etat_du_cycle_comptable_dit_les_contradictions_seulement_quand_il_y_en_a(monde, tmp_path, monkeypatch):
    par_nom = {o.nom: o for o in outils_m5.outils()}

    def cycle():
        reponse = executer_atomique(
            par_nom["m5_executer_cycle_comptable"],
            {"aujourd_hui": "2026-11-11", "horodatage": "2026-11-11T10:00:00-05:00", "periode": None},
        )
        return reponse["resultat"]

    import yaml

    manifeste = tmp_path / "department-m5.yaml"
    manifeste.write_text(
        yaml.safe_dump(
            {
                "configuration": {
                    "operations": {
                        "relances": {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7, 21, 45]}
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(outils_m5, "_MANIFESTE", manifeste)
    avant = cycle()
    assert avant["accepte"] is True
    assert "constats_contradictoires_m7_a_examiner" not in avant["resultat"]["en_attente_d_une_personne"]
    _pub(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(montant="1.00"), "d1")
    _pub(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(montant="2.00"), "d2")
    monde.repartir()
    apres = cycle()["resultat"]["en_attente_d_une_personne"]
    assert apres["constats_contradictoires_m7_a_examiner"] == 1


# ------------------------------------------------------------------------------------------------ M8
@pytest.mark.parametrize(
    ("type_evenement", "producteur", "premier", "second", "champ"),
    [
        (
            "m7.depenses_marketing_constatees",
            M7,
            lambda: ch.depense_marketing(montant="10.00"),
            lambda: ch.depense_marketing(montant="11.00"),
            "montant_cad",
        ),
        (
            "m7.anomalie_depense_detectee",
            M7,
            lambda: ch.anomalie_depense(severite="info"),
            lambda: ch.anomalie_depense(severite="critique"),
            "severite",
        ),
        (
            "m5.facture_emise_constatee",
            M5,
            lambda: ch.facture_emise(avant="100.00"),
            lambda: ch.facture_emise(avant="101.00"),
            "montant_avant_taxes_cad",
        ),
        (
            "m7.conversion_hors_ligne_importee",
            M7,
            lambda: ch.conversion_hors_ligne(source="google"),
            lambda: ch.conversion_hors_ligne(source="meta"),
            "utm_source",
        ),
    ],
    ids=["depense", "anomalie", "facture-emise", "conversion"],
)
def test_m8_meme_cle_contenu_different_premier_garde_contradiction_rangee_et_dite(
    monde, type_evenement, producteur, premier, second, champ
):
    _pub(producteur, type_evenement, premier(), "a")
    monde.repartir()
    avant = monde.registre(M8, "faits_operations")
    _pub(producteur, type_evenement, second(), "b")
    resume = monde.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    assert monde.registre(M8, "faits_operations") == avant  # rien n'est écrasé ni ajouté
    (audit,) = monde.registre(M8, AUDIT)
    assert audit["constat"] == type_evenement and champ in audit["champs"]
    assert _resultat_recu(monde, "b", M8)["contradiction"] == constats.CODE


def test_m8_rejeu_identique_sous_un_autre_identifiant_reste_silencieux_meme_pour_les_types_a_evenement_id(monde):
    for type_evenement, producteur, fabrique in (
        ("m5.facture_emise_constatee", M5, lambda ident: ch.facture_emise(evenement_id=ident)),
        ("m7.depenses_marketing_constatees", M7, lambda ident: ch.depense_marketing()),
    ):
        _pub(producteur, type_evenement, fabrique("m5-facture-emise-facture-fictive-1-ENVOYEE"), f"x1-{producteur}")
        monde.repartir()
        _pub(producteur, type_evenement, fabrique("m5-facture-emise-AUTRE-ENVOYEE"), f"x2-{producteur}")
        monde.repartir()
    assert monde.registre(M8, AUDIT) == []


def test_m8_l_instant_de_publication_et_la_provenance_ne_sont_pas_du_contenu():
    a = {
        "type_entree": "facture_emise",
        "facture_id": "F",
        "statut": "PAYEE",
        "publie_le": "t1",
        "provenance": {"e": 1},
    }
    b = {**a, "publie_le": "t2", "provenance": {"e": 2}}
    assert constats.champs_differents(a, b, ops_m8.CHAMPS_NON_COMPARES) == []
    assert ops_m8.contenu_compare(a) == ops_m8.contenu_compare(b)
    assert constats.champs_differents(a, {**b, "statut": "ANNULEE"}, ops_m8.CHAMPS_NON_COMPARES) == ["statut"]


def test_m8_la_vue_executive_dit_les_contradictions_seulement_quand_il_y_en_a(monde):
    par_nom = {o.nom: o for o in outils_m8.outils()}

    def vue():
        reponse = executer_atomique(par_nom["m8_lire_vue_executive"], {})
        assert reponse["ok"] is True, reponse
        return reponse["resultat"]["resultat"] if "resultat" in reponse["resultat"] else reponse["resultat"]

    _pub(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(montant="10.00"), "a")
    monde.repartir()
    assert "constats_contradictoires" not in vue()
    _pub(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(montant="99.00"), "b")
    monde.repartir()
    lue = vue()
    assert lue["constats_contradictoires"]["nombre"] == 1
    assert "premier état est gardé" in lue["constats_contradictoires"]["message"]
    assert "99" not in json.dumps(lue["constats_contradictoires"])


# ------------------------------------------------------------------------------------------------ panne et reprise
def test_panne_du_destinataire_la_contradiction_est_rangee_une_seule_fois_apres_reprise(monde):
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1", niveau=1), "r1")
    monde.repartir()
    monde.pannes.add(M2)
    _pub(M5, "m5.creance_relance_preparee", ch.creance_relance(relance_id="rel-1", niveau=2), "r2")
    monde.repartir(passes=1)
    assert monde.registre(M2, AUDIT) == []
    assert monde.statut("r2", M2) == "echec"
    monde.pannes.clear()
    monde.repartir()
    monde.repartir()
    assert len(monde.registre(M2, AUDIT)) == 1 and monde.statut("r2", M2) == "traite"


# ------------------------------------------------------------------------------------------------ le module commun
def test_empreinte_de_contenu_independante_de_l_ordre_des_cles():
    assert constats.empreinte_contenu({"a": 1, "b": [1, 2]}) == constats.empreinte_contenu({"b": [1, 2], "a": 1})
    assert constats.empreinte_contenu({"a": 1}) != constats.empreinte_contenu({"a": 2})
    assert len(constats.empreinte_contenu({})) == 32


def test_champs_differents_nomme_les_champs_sans_valeur_et_respecte_ignorer():
    existant = {"x": 1, "y": 2, "z": 3, "meta": "a"}
    assert constats.champs_differents(existant, {"x": 1, "y": 9, "z": 3, "meta": "b"}, ["meta"]) == ["y"]
    assert constats.champs_differents(existant, {"x": 1, "nouveau": 5}) == ["nouveau"]
    assert constats.champs_differents(existant, dict(existant)) == []
    assert constats.champs_differents({"l": [1, 2]}, {"l": (1, 2)}) == []  # tuple et liste : même contenu


def test_deja_signalee_et_compter():
    ligne = constats.ligne_contradiction(
        "t", {"k": 1}, empreinte_premier="a", empreinte_nouveau="b", champs=["x"], publie_le=None
    )
    assert constats.deja_signalee([], ligne) is False
    assert constats.deja_signalee([ligne], ligne) is True
    for variante in (
        {**ligne, "constat": "autre"},
        {**ligne, "cle": {"k": 2}},
        {**ligne, "empreinte_nouveau": "c"},
        {**ligne, "type_entree": "autre"},
    ):
        assert constats.deja_signalee([variante], ligne) is False, variante
    assert constats.compter([ligne, ligne, {"type_entree": "autre"}]) == 2
    assert constats.compter([]) == 0
