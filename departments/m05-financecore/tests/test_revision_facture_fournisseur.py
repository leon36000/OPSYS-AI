"""PLAN T4.15-c : une correction ou une annulation N4 décidée sur une révision PÉRIMÉE de la facture ne finalise rien.

Deux demandes peuvent attendre dans la file sur la même facture. Sans lien avec la révision vue à la proposition, la
seconde décision s'appliquerait sur l'état produit par la première : la correction approuvée en premier disparaîtrait
en silence (ou une facture déjà corrigée autrement serait annulée). `revision_attendue` (le nombre de corrections lu
dans les comptes à payer, `corrections` ; une ligne au statut SAISIE n'en porte pas : révision 0) lie la demande à ce
que la personne a vu : différente de l'état courant au moment de l'effet, elle est refusée
(`REJ-AP-FACTURE-REVISION-PERIMEE`) sans rien écrire. Elle est OBLIGATOIRE : omise ou nulle, le schéma la refuse à la
proposition et, à la décision, une demande enregistrée sans elle avant que le jeton soit requis (`arguments_invalides`,
par le socle qui revalide les arguments enregistrés : jamais exécutée, la reproposer). Sans le schéma (un autre point
d'entrée), l'outil et le calcul pur la refusent eux-mêmes au point d'effet (`REJ-AP-FACTURE-REVISION-REQUISE`).

Montants à la main : 310.00 -> 356.42 ; 320.00 -> 320.00 + 16.00 + 31.92 = 367.92. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer as ap
from m5_financecore import registre

from opsys import approbations as opsys_approbations
from opsys import contexte, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.outils import Niveau

FICTIF = True
_ICI = Path(__file__).resolve().parent


def _charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, _ICI / fichier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_o = _charger("correction_outils_fictif", "test_correction_outils.py")
_p = _charger("ap_pur_revision_fictif", "test_comptes_a_payer.py")
base_durable = _o.base_durable
dep = _o.dep
par_nom = _o.par_nom
facture = _o.facture
taux = _p.taux
DEPARTEMENT = _o.DEPARTEMENT
OUTILS_N4 = ("m5_corriger_facture_fournisseur", "m5_annuler_facture_fournisseur")


def _proposer(dep, nom, arguments):
    demande = Capacites({DEPARTEMENT: dep}, stockage.transaction).appeler(nom, arguments)
    assert demande["statut"] == "en_attente_approbation", demande
    return demande["demande_id"]


def _decider(dep, demande_id, decideur="nathan"):
    with stockage.transaction() as cnx:
        return opsys_approbations.decider(
            cnx, demande_id, True, decideur, outils_executables({DEPARTEMENT: dep}, stockage.transaction),
            {DEPARTEMENT: dep})


def _refus_metier(decision):
    assert decision["statut"] == "echec", decision
    resultat = decision["reponse"]["resultat"]
    assert resultat["accepte"] is False, decision
    return resultat["verdict"]


def _revision_lue(par_nom, ident):
    """Ce que la personne lit AVANT de proposer, dans `m5_lister_comptes_a_payer` (détail du PO) : `corrections` sur
    une facture modifiée ; une facture jamais touchée (statut SAISIE) n'en porte pas, sa révision est 0."""
    (ligne,) = [f for f in _o._le_po(par_nom)["factures_saisies"] if f["facture_fournisseur_id"] == ident]
    if ligne["statut"] == "SAISIE":
        assert "corrections" not in ligne and "derniere_modification" not in ligne, ligne
        return 0
    return ligne["corrections"]


def _sans(arguments, cle="revision_attendue"):
    return {k: v for k, v in arguments.items() if k != cle}


def _arguments_sans_revision(facture):
    """Les demandes d'avant le jeton requis : omis, ou nul."""
    corriger = _o._corriger_args(facture, montant_avant_taxes="310.00", revision_attendue=0)
    annuler = _o._annuler_args(facture, revision_attendue=0)
    for forme in ("omise", "nulle"):
        for nom, arguments in (("m5_corriger_facture_fournisseur", corriger),
                               ("m5_annuler_facture_fournisseur", annuler)):
            yield forme, nom, (_sans(arguments) if forme == "omise" else {**arguments, "revision_attendue": None})


# ============================================================================== par la file, au point d'effet
def test_deux_corrections_en_attente_la_seconde_decidee_sur_une_revision_perimee_n_ecrit_rien(
    base_durable, dep, par_nom, facture
):
    a = _proposer(dep, "m5_corriger_facture_fournisseur",
                  _o._corriger_args(facture, montant_avant_taxes="310.00",
                                    revision_attendue=_revision_lue(par_nom, facture)))
    c = _proposer(dep, "m5_corriger_facture_fournisseur",
                  _o._corriger_args(facture, montant_avant_taxes="320.00",
                                    revision_attendue=_revision_lue(par_nom, facture)))

    assert _decider(dep, c)["statut"] == "executee"
    apres_c = _o._registre_ap()
    verdict = _refus_metier(_decider(dep, a))

    assert verdict["code"] == "REJ-AP-FACTURE-REVISION-PERIMEE"
    assert "révision 1" in verdict["detail"] and "révision 0" in verdict["detail"]
    assert _o._registre_ap() == apres_c, "aucune pièce de plus"
    assert _o._le_po(par_nom)["factures"]["apres_taxes"] == "367.92", "la correction approuvée la première reste"
    with stockage.transaction() as cnx:
        demande_a = opsys_approbations.lire(cnx, a)
    assert demande_a["statut"] == "echec"
    assert demande_a["arguments"]["revision_attendue"] == 0, "la file rejoue le jeton proposé, jamais un autre"
    with pytest.raises(ValueError, match="déjà traitée"):
        _decider(dep, a)
    assert _o._registre_ap() == apres_c, "une demande close ne se rejoue pas"


@pytest.mark.parametrize("forme", ["omise", "nulle"])
def test_une_demande_enregistree_sans_revision_n_ecrase_plus_la_decision_courante(
    base_durable, dep, par_nom, facture, forme
):
    """Inverse l'ancienne limite (sans `revision_attendue`, la dernière décision l'emportait : 356.42 écrasait 367.92).
    A est une demande enregistrée SANS jeton (comme avant qu'il soit requis), C une demande proposée sur la révision
    lue ; approuvée après C par un propriétaire valide, A n'est pas exécutée : rien n'est ajouté, C reste."""
    sans_jeton = _sans(_o._corriger_args(facture, montant_avant_taxes="310.00", revision_attendue=0))
    assert "revision_attendue" not in sans_jeton
    if forme == "nulle":
        sans_jeton["revision_attendue"] = None
    with stockage.transaction() as cnx:
        a = opsys_approbations.creer_demande(cnx, DEPARTEMENT, "m5_corriger_facture_fournisseur", sans_jeton,
                                             niveau=Niveau.N4)
    c = _proposer(dep, "m5_corriger_facture_fournisseur",
                  _o._corriger_args(facture, montant_avant_taxes="320.00",
                                    revision_attendue=_revision_lue(par_nom, facture)))

    assert _decider(dep, c)["statut"] == "executee"
    apres_c = _o._registre_ap()
    decision = _decider(dep, a)

    assert decision["statut"] == "echec", decision
    assert decision["reponse"]["erreur"] == "arguments_invalides"
    assert any("revision_attendue" in d for d in decision["reponse"]["details"]), decision
    assert _o._registre_ap() == apres_c, "aucune pièce de plus"
    assert _o._le_po(par_nom)["factures"]["apres_taxes"] == "367.92", "la décision courante n'est pas écrasée"


def test_une_proposition_sans_revision_ou_nulle_n_entre_pas_dans_la_file(base_durable, dep, facture):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    with stockage.transaction() as cnx:
        avant = opsys_approbations.compter(cnx, "en_attente")
    for forme, nom, arguments in _arguments_sans_revision(facture):
        reponse = capacites.appeler(nom, arguments)
        assert reponse.get("ok") is False and reponse["erreur"] == "arguments_invalides", (forme, nom, reponse)
        assert "revision_attendue" in str(reponse["details"]), (forme, nom, reponse)
    with stockage.transaction() as cnx:
        assert opsys_approbations.compter(cnx, "en_attente") == avant, "aucune demande à exécuter plus tard"


def test_une_annulation_decidee_sur_une_revision_perimee_n_annule_rien(base_durable, dep, par_nom, facture):
    annulation = _proposer(dep, "m5_annuler_facture_fournisseur",
                           _o._annuler_args(facture, revision_attendue=_revision_lue(par_nom, facture)))
    correction = _proposer(dep, "m5_corriger_facture_fournisseur",
                           _o._corriger_args(facture, montant_avant_taxes="320.00",
                                             revision_attendue=_revision_lue(par_nom, facture)))
    assert _decider(dep, correction, "comptable")["statut"] == "executee"
    avant = _o._registre_ap()

    verdict = _refus_metier(_decider(dep, annulation))

    assert verdict["code"] == "REJ-AP-FACTURE-REVISION-PERIMEE"
    assert _o._registre_ap() == avant
    assert _o._le_po(par_nom)["rapprochement"]["verdict"] == "ECART", "la facture corrigée reste vivante"


def test_la_revision_exacte_s_applique_et_la_suivante_se_lit_dans_les_comptes_a_payer(
    base_durable, dep, par_nom, facture
):
    lue = _revision_lue(par_nom, facture)
    assert lue == 0
    premiere = _proposer(dep, "m5_corriger_facture_fournisseur",
                         _o._corriger_args(facture, montant_avant_taxes="310.00", revision_attendue=lue))
    assert _decider(dep, premiere)["statut"] == "executee"
    (ligne,) = _o._le_po(par_nom)["factures_saisies"]
    assert ligne["statut"] == "CORRIGEE" and ligne["corrections"] == 1

    seconde = _proposer(dep, "m5_corriger_facture_fournisseur",
                        _o._corriger_args(facture, montant_avant_taxes="320.00",
                                          revision_attendue=_revision_lue(par_nom, facture)))
    assert _decider(dep, seconde)["statut"] == "executee"
    lue = _revision_lue(par_nom, facture)
    assert lue == 2
    annulation = _proposer(dep, "m5_annuler_facture_fournisseur", _o._annuler_args(facture, revision_attendue=lue))
    assert _decider(dep, annulation)["statut"] == "executee"

    pieces = [m["type_entree"] for m in _o._registre_ap()]
    assert pieces == ["reception_recue", "facture_fournisseur_saisie", "correction_facture_fournisseur",
                      "correction_facture_fournisseur", "annulation_facture_fournisseur"]
    assert _o._le_po(par_nom)["rapprochement"]["verdict"] == "SANS_FACTURE"


def test_l_appareil_du_proprietaire_avec_une_revision_perimee_n_ecrit_rien(base_durable, par_nom, facture):
    assert _o._accepte(_o._appeler(par_nom, "m5_corriger_facture_fournisseur",
                                   _o._corriger_args(facture, revision_attendue=_revision_lue(par_nom, facture)),
                                   _o.NATHAN))
    avant = _o._instantane_base()

    reponse = _o._appeler(par_nom, "m5_corriger_facture_fournisseur",
                          _o._corriger_args(facture, montant_avant_taxes="320.00", revision_attendue=0), _o.NATHAN)

    assert _o._code(reponse) == "REJ-AP-FACTURE-REVISION-PERIMEE" and _o._instantane_base() == avant


def test_l_appareil_du_proprietaire_sans_revision_ou_nulle_n_ecrit_rien_et_la_revision_lue_passe(
    base_durable, par_nom, facture
):
    """Le propriétaire est un acteur valide : seul le jeton manque. La réciproque, même acteur, même geste, avec la
    révision lue, s'applique."""
    avant = _o._instantane_base()
    for forme, nom, arguments in _arguments_sans_revision(facture):
        reponse = _o._appeler(par_nom, nom, arguments, _o.NATHAN)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", (forme, nom, reponse)
        assert _o._instantane_base() == avant, (forme, nom)

    corrigee = _o._accepte(_o._appeler(
        par_nom, "m5_corriger_facture_fournisseur",
        _o._corriger_args(facture, montant_avant_taxes="310.00", revision_attendue=_revision_lue(par_nom, facture)),
        _o.NATHAN))
    assert corrigee["facture"]["corrections"] == 1 and corrigee["facture"]["montant_apres_taxes"] == "356.42"


def test_l_outil_refuse_lui_meme_la_revision_omise_ou_nulle_sans_le_schema(base_durable, par_nom, facture):
    """Le schéma n'est pas la seule garde : appelé sans lui (un autre point d'entrée), l'outil refuse au point d'effet,
    pour un propriétaire valide, sans rien écrire."""
    avant = _o._instantane_base()
    for forme, nom, arguments in _arguments_sans_revision(facture):
        with contexte.appele_par_appareil(_o.NATHAN), stockage.transaction():
            reponse = par_nom[nom].fonction(**arguments)
        assert reponse["accepte"] is False, (forme, nom, reponse)
        assert reponse["verdict"]["code"] == "REJ-AP-FACTURE-REVISION-REQUISE", (forme, nom, reponse)
        assert "reproposer" in reponse["verdict"]["detail"], reponse
        assert _o._instantane_base() == avant, (forme, nom)


@pytest.mark.parametrize("valeur", [-1, "0", 1.5, True, None])
def test_une_revision_attendue_mal_formee_est_refusee_sans_rien_ecrire(base_durable, par_nom, facture, valeur):
    """Le validateur du socle vérifie le type, pas `minimum` : -1 passe le schéma et l'outil le refuse lui-même."""
    avant = _o._instantane_base()
    for nom, arguments in (
        ("m5_corriger_facture_fournisseur", _o._corriger_args(facture, revision_attendue=valeur)),
        ("m5_annuler_facture_fournisseur", _o._annuler_args(facture, revision_attendue=valeur)),
    ):
        reponse = _o._appeler(par_nom, nom, arguments, _o.NATHAN)
        if valeur == -1:
            assert _o._code(reponse) == "REJ-AP-FACTURE-CHAMP-INVALIDE", (nom, reponse)
        else:
            assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", (nom, valeur, reponse)
    assert _o._instantane_base() == avant


def test_le_schema_exige_la_revision_attendue_entiere_non_nulle(par_nom):
    for nom in OUTILS_N4:
        schema = par_nom[nom].parametres
        assert schema["properties"]["revision_attendue"] == {
            "type": "integer", "minimum": 0,
            "description": schema["properties"]["revision_attendue"]["description"],
        }
        assert set(schema["required"]) == set(schema["properties"]), nom
        assert schema["additionalProperties"] is False
        assert len(par_nom[nom].description) <= 1024
        assert "relire" in schema["properties"]["revision_attendue"]["description"], nom


# ===================================================================================== en pur, sans la file
def _facture_pure(taux):
    reg = registre.Registre()
    _p._recevoir(reg)
    ident = _p._facturer_ok(reg, taux)["facture"]["facture_fournisseur_id"]
    return reg, ident


def _corriger(reg, taux, ident, montant, revision):
    return ap.corriger_facture_fournisseur(
        facture_fournisseur_id=ident, motif="montant relu (fictif)", numero_facture=None, date_facture=None,
        montant_avant_taxes=montant, total_facture=None, corrige_par="finance.fictive", role="finance",
        voie="approbation", horodatage=_p.SAISIE, dictionnaire_taux=taux, registre_cible=reg,
        revision_attendue=revision)


def _annuler(reg, ident, revision):
    return ap.annuler_facture_fournisseur(
        facture_fournisseur_id=ident, motif="doublon fournisseur (fictif)", annule_par="finance.fictive",
        role="finance", voie="approbation", horodatage=_p.SAISIE, registre_cible=reg, revision_attendue=revision)


def test_en_pur_la_revision_perimee_est_refusee_sans_ecrire_et_l_exacte_passe(taux):
    reg, ident = _facture_pure(taux)
    resultat, verdict = _corriger(reg, taux, ident, "310.00", 0)
    assert verdict is None and resultat["facture"]["montant_apres_taxes"] == Decimal("356.42")
    lue = ap.vue_facture(resultat["facture"])["corrections"]
    avant = reg.lire()

    for appel in (lambda: _corriger(reg, taux, ident, "320.00", 0), lambda: _annuler(reg, ident, 0),
                  lambda: _corriger(reg, taux, ident, "320.00", 2), lambda: _annuler(reg, ident, 2)):
        resultat, verdict = appel()
        assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-REVISION-PERIMEE", verdict
        assert reg.lire() == avant

    resultat, verdict = _annuler(reg, ident, lue)
    assert lue == 1 and verdict is None and resultat["facture"]["statut"] == "ANNULEE"


@pytest.mark.parametrize("valeur", [-1, "1", 1.0, True, False])
def test_en_pur_une_revision_qui_n_est_pas_un_entier_positif_est_refusee(taux, valeur):
    reg, ident = _facture_pure(taux)
    avant = reg.lire()

    for resultat, verdict in (_corriger(reg, taux, ident, "310.00", valeur), _annuler(reg, ident, valeur)):
        assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-CHAMP-INVALIDE", verdict
        assert "revision_attendue" in verdict["detail"]
    assert reg.lire() == avant


def test_en_pur_sans_revision_attendue_ou_nulle_rien_n_est_ecrit(taux):
    """Inverse l'ancien « comportement d'avant » : omise ou nulle, la correction et l'annulation sont refusées, sans
    déduire la révision courante au moment d'écrire."""
    reg, ident = _facture_pure(taux)
    avant = reg.lire()
    omise_corriger = ap.corriger_facture_fournisseur(
        facture_fournisseur_id=ident, motif="montant relu (fictif)", numero_facture=None, date_facture=None,
        montant_avant_taxes="310.00", total_facture=None, corrige_par="finance.fictive", role="finance",
        voie="approbation", horodatage=_p.SAISIE, dictionnaire_taux=taux, registre_cible=reg)
    omise_annuler = ap.annuler_facture_fournisseur(
        facture_fournisseur_id=ident, motif="doublon fournisseur (fictif)", annule_par="finance.fictive",
        role="finance", voie="approbation", horodatage=_p.SAISIE, registre_cible=reg)

    for resultat, verdict in (omise_corriger, omise_annuler, _corriger(reg, taux, ident, "310.00", None),
                              _annuler(reg, ident, None)):
        assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-REVISION-REQUISE", verdict
        assert "relire" in verdict["detail"] and "reproposer" in verdict["detail"], verdict
    assert reg.lire() == avant

    resultat, verdict = _corriger(reg, taux, ident, "310.00", 0)
    assert verdict is None and resultat["facture"]["corrections"] == 1, "la réciproque lue passe"
