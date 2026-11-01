"""D1 : M5 constate ce que le grand livre a COMPTABILISÉ des relevés publicitaires de M7
(`m5.depense_publicitaire_constatee`).

Bus réel, consommateur réel de M5 (brouillon de charge), grand livre réel, outil réel
`m5_constater_depense_publicitaire`.
Prouve : un brouillon n'est pas comptabilisé (il est compté à part) ; une validation humaine le comptabilise ; sa
contre-passation l'annule ; seuls les relevés dont la date d'effet est dans la période comptent ; un relevé
TAXES_INCLUSES
(aucun brouillon) n'entre pas ; un constat par période et par version, le retour à une version antérieure est un
événement
de plus (`sequence`) ; aucun fournisseur ni pièce ne part. Données fictives.
"""

from __future__ import annotations

import json

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m5_financecore import grand_livre, outils

from opsys import evenements, stockage
from opsys.capacites import Capacites

FICTIF = True
M5, M7 = "m05-financecore", "m07-marketing"
H = "2026-11-02T10:00:00-05:00"
HUMAIN = {"par": "nathan.fictif", "role": "nathan_owner", "voie": "test"}
TOUT = {"debut": "2026-10-01", "fin": "2026-10-31", "aujourd_hui": "2026-11-02", "horodatage": H}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M5, M7))
    m.surveiller(monkeypatch)
    yield m
    im.demonter()


def _constater(monde, **plus):
    reponse = Capacites(monde.departements, stockage.transaction, filtre={M5}, memoire=False).appeler(
        "m5_constater_depense_publicitaire", {**TOUT, **plus}
    )
    return reponse


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _releve(monde, releve_id, jour, montant="125.40", base="HORS_TAXES", revision=1):
    evenements.publier(
        "m7.depenses_marketing_constatees",
        M7,
        ch.depense_marketing(releve_id=releve_id, jour=jour, montant=montant, base=base, revision=revision),
        evenement_id=f"{releve_id}-r{revision}",
    )
    monde.repartir(departements=(M5,))


def _valider(monde, releve_id):
    registre, plan = outils._contexte_grand_livre()[0]
    (ecriture,) = [
        e
        for e in grand_livre.etat_grand_livre(registre.lire())["ecritures"].values()
        if e["piece"]["reference"].startswith(f"m7:{releve_id}:") and e["statut"] == "BROUILLON"
    ]
    resultat, refus = grand_livre.valider_ecriture(
        registre, plan, ecriture_id=ecriture["ecriture_id"], humain=HUMAIN, horodatage=H
    )
    assert refus is None, refus
    return ecriture["ecriture_id"]


def _contre_passer_et_valider(monde, ecriture_id, jour):
    registre, plan = outils._contexte_grand_livre()[0]
    resultat, refus = grand_livre.proposer_contre_passation(
        registre, plan, ecriture_id=ecriture_id, date_effet=jour, motif="erreur de relevé (fictif)", horodatage=H
    )
    assert refus is None, refus
    nouvelle = resultat["ecriture"]["ecriture_id"]
    _, refus = grand_livre.valider_ecriture(registre, plan, ecriture_id=nouvelle, humain=HUMAIN, horodatage=H)
    assert refus is None, refus


def _publies(monde):
    return [
        (e["evenement_id"], json.loads(e["charge"]) if isinstance(e["charge"], str) else e["charge"])
        for e in monde.sortants("m5.depense_publicitaire_constatee")
    ]


def test_un_brouillon_n_est_pas_comptabilise_il_est_compte_a_part(monde):
    _releve(monde, "releve-a", "2026-10-27", "125.40")
    resultat = _ok(_constater(monde))
    assert resultat["publie"] is True and resultat["sequence"] == 1
    assert resultat["comptabilise_cad"] == "0.00" and resultat["ecritures_definitives"] == 0
    assert resultat["brouillons_en_attente"] == 1
    ((ident, charge),) = _publies(monde)
    assert charge["comptabilise_cad"] == "0.00" and charge["brouillons_en_attente_cad"] == "125.40"
    assert ident == charge["evenement_id"] == f"m5-depense-pub-1-2026-10-01-2026-10-31-{charge['version_donnees']}"


def test_la_validation_humaine_comptabilise_et_la_contre_passation_annule(monde):
    _releve(monde, "releve-a", "2026-10-27", "125.40")
    _releve(monde, "releve-b", "2026-10-28", "74.60")
    ecriture_a = _valider(monde, "releve-a")
    _valider(monde, "releve-b")
    resultat = _ok(_constater(monde))
    assert resultat["comptabilise_cad"] == "200.00" and resultat["ecritures_definitives"] == 2
    assert resultat["brouillons_en_attente"] == 0
    _contre_passer_et_valider(monde, ecriture_a, "2026-10-29")
    apres = _ok(_constater(monde))
    assert (
        apres["comptabilise_cad"] == "74.60" and apres["sequence"] == 2
    )  # l'origine et sa contre-passation s'annulent


def test_seule_la_date_d_effet_dans_la_periode_compte(monde):
    _releve(monde, "releve-sept", "2026-09-30", "50.00")
    _releve(monde, "releve-oct", "2026-10-15", "80.00")
    _valider(monde, "releve-sept")
    _valider(monde, "releve-oct")
    assert _ok(_constater(monde))["comptabilise_cad"] == "80.00"
    assert _ok(_constater(monde, debut="2026-09-01", fin="2026-09-30"))["comptabilise_cad"] == "50.00"


def test_un_releve_taxes_incluses_n_entre_pas_aucun_brouillon(monde):
    _releve(monde, "releve-t", "2026-10-20", "99.00", base="TAXES_INCLUSES")
    resultat = _ok(_constater(monde))
    assert resultat["comptabilise_cad"] == "0.00" and resultat["brouillons_en_attente"] == 0


def test_un_constat_par_version_le_redire_ne_publie_rien_un_retour_arriere_est_un_evenement_de_plus(monde):
    _releve(monde, "releve-a", "2026-10-27", "125.40")
    premier = _ok(_constater(monde))
    redit = _ok(_constater(monde))
    assert premier["publie"] is True and redit["deja_constate"] is True and redit["publie"] is False
    assert len(_publies(monde)) == 1
    _valider(monde, "releve-a")
    deuxieme = _ok(_constater(monde))
    assert deuxieme["sequence"] == 2 and len(_publies(monde)) == 2
    # une autre période est un autre constat, de son propre rang
    autre = _ok(_constater(monde, debut="2026-09-01", fin="2026-09-30"))
    assert autre["sequence"] == 3 and len(_publies(monde)) == 3


def test_aucun_fournisseur_aucune_piece_aucun_libelle_ne_part(monde):
    _releve(monde, "releve-a", "2026-10-27")
    _valider(monde, "releve-a")
    _ok(_constater(monde))
    texte = json.dumps(_publies(monde), ensure_ascii=False)
    for interdit in ("releve-a", "m7:", "google", "Dépense publicitaire", "5950", "2100"):
        assert interdit not in texte, interdit


@pytest.mark.parametrize(
    "plus",
    [
        {"debut": "2026-10-31", "fin": "2026-10-01"},
        {"debut": "2026-02-30"},
        {"debut": "2025-01-01", "fin": "2026-12-31"},
        {"aujourd_hui": "hier"},
    ],
)
def test_periode_inversee_illisible_ou_trop_longue_refusee_sans_rien_publier(monde, plus):
    reponse = _constater(monde, **plus)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-OPS-DATE-INVALIDE"
    assert _publies(monde) == []


def test_un_appareil_est_refuse_meme_admin(monde):
    from opsys import contexte
    from opsys.contexte import IdentiteAppelante
    from opsys.outils import executer_atomique

    outil = next(o for o in monde.departements[M5].charger_outils() if o.nom == "m5_constater_depense_publicitaire")
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        reponse = executer_atomique(outil, TOUT)
    assert "REJ-IDENTITE-APPAREIL-INVALIDE" in json.dumps(reponse, default=str) and _publies(monde) == []
