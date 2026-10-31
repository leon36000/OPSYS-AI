"""E0 (CONCEPTION-ROUTAGE-COUT-CERTIFIE, suspicion I5) — la cascade ORDINAIRE de M5 écrase-t-elle un coût certifié ?

Hypothèse : après qu'un recalcul certifié (couture QA `service_recalcul_m4._executer_qa`) a publié une trace
`m5.rentabilite_chantier` dont la main-d'oeuvre est certifiée (verdict CALCULEE, projection M4 V3 vérifiée), un
événement ordinaire du bus (variance M6 relue, devis ou WCT relivrés, facture envoyée ou payée) fait recalculer à M5
un coût PARTIEL (sans projection), le trace et le publie avec un `sequence` plus grand ; M8 et M10 retiennent le
plus grand `sequence` (docstring de `m8_analytics.outils._recevoir_rentabilite_chantier`, `m10_memoire.rentabilite`),
donc l'état partiel tardif remplace l'état certifié.

Ce fichier ne modifie AUCUN code produit. Il exécute, pour CHAQUE événement de la cascade, le même parcours :
chantier terminé par la voie certifiée -> cascade ordinaire (partiel) -> recalcul certifié -> UN événement ordinaire
-> relevé (traces M5, événement de plus grand `sequence`, mesure M8 `m8_marge_reelle_cad`, leçon M10, rapport
d'apprentissage M3). Chaque cas est sur sa propre base : un verdict par étape de cascade, jamais mélangé.

Sortie brute : si `E0_SORTIE_JSON` est défini, chaque cas y est écrit (un fichier JSON par exécution).

Les helpers de scénario sont ceux de `test_cascade_marge_m5_m8_m10.py`, chargés depuis ce fichier (même dossier) pour
ne pas recopier 400 lignes de journée d'équipe certifiée ; le seul couplage est l'API de ces helpers.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
from sqlalchemy import insert, select

from opsys import approbations, contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, OPSYS_INSTANCE, SERVICE_POLITIQUES


def _charger_helpers():
    chemin = Path(__file__).with_name("test_cascade_marge_m5_m8_m10.py")
    nom = "e0_helpers_cascade_marge"
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


cm = _charger_helpers()

RACINE = Path(__file__).resolve().parent.parent
BASE = dt.datetime(2026, 9, 16, 7, 0, 0, tzinfo=cm.DT_TZ)
TARIF_PRIX_LIVRE = 8.0


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    import opsys
    # le `pythonpath` du pyproject de CE worktree doit primer sur tout autre éditable
    assert Path(opsys.__file__).resolve().is_relative_to(RACINE), opsys.__file__
    assert Path(m5_outils.__file__).resolve().is_relative_to(RACINE), m5_outils.__file__
    url = f"sqlite:///{tmp_path / 'opsys-e0-regression.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        m2_outils.reinitialiser_registre()
        stockage.liberer()


# -------------------------------------------------------------------------------------------
# Gestes de la cascade ordinaire (tous passent par le VRAI bus / les VRAIS outils)
# -------------------------------------------------------------------------------------------
def _cle_temps(deps, minutes: int) -> dt.datetime:
    return BASE + dt.timedelta(hours=6, minutes=minutes)


def _drainer(deps, minutes: int) -> None:
    cm._drainer_sans_echec(deps, _cle_temps(deps, minutes))


def _charge_sortante(type_evenement: str, **filtre) -> tuple[str, str, dict]:
    """(evenement_id, producteur, charge) du premier événement publié du type, dont la charge contient `filtre`."""
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(
            EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.producteur, EVENEMENTS_SORTANTS.c.charge,
        ).where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
            .order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)).all()
    for ligne in lignes:
        charge = codec.decoder(ligne.charge)
        if all(charge.get(cle) == valeur for cle, valeur in filtre.items()):
            return ligne.evenement_id, ligne.producteur, charge
    raise AssertionError(f"aucun {type_evenement} publié pour {filtre}")


def _republier(type_evenement: str, suffixe: str, **filtre) -> str:
    """Relivre une pièce déjà publiée : même enveloppe (type, producteur, charge), NOUVEL identifiant d'événement.
    C'est ce que voit M5 quand un producteur republie, ou quand une livraison est reprise après une panne : le
    répartiteur livre l'événement au consommateur M5 par le chemin ordinaire."""
    evenement_id, producteur, charge = _charge_sortante(type_evenement, **filtre)
    nouveau = f"{evenement_id}-e0-{suffixe}"
    with stockage.transaction():
        from opsys import evenements
        evenements.publier(type_evenement, producteur, charge, evenement_id=nouveau)
    return nouveau


def _rejouer(type_evenement: str, **filtre) -> str:
    """REJEU du MÊME événement (même identifiant) : le reçu de M5 est retiré, le répartiteur le relivre tel quel au
    consommateur M5, comme après une livraison reprise (panne avant commit, redémarrage). L'identifiant d'origine
    compte : le producteur M4 exige `evenement_id == wct_id` pour la voie certifiée de livraison."""
    from sqlalchemy import delete

    from opsys.stockage.schema import EVENEMENTS_RECUS
    evenement_id, _, _ = _charge_sortante(type_evenement, **filtre)
    with stockage.transaction() as cnx:
        supprimes = cnx.execute(delete(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.evenement_id == evenement_id,
            EVENEMENTS_RECUS.c.consommateur == "m05-financecore")).rowcount
    assert supprimes == 1, (type_evenement, evenement_id, supprimes)
    return evenement_id


def _nouvelle_revision_politique(operation: str, *, active: bool) -> None:
    """Révision +1 de la politique de service (append-only) : révocation (`active=False`) ou octroi daté."""
    with stockage.transaction() as cnx:
        instance_id = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
        derniere = cnx.execute(
            select(SERVICE_POLITIQUES.c.revision).where(SERVICE_POLITIQUES.c.operation == operation)
            .order_by(SERVICE_POLITIQUES.c.revision.desc())
        ).scalars().first()
        cnx.execute(insert(SERVICE_POLITIQUES).values(
            instance_id=instance_id, consommateur="m05-financecore", operation=operation,
            revision=derniere + 1, active=active, expire_le=int(time.time()) + 3600))


def _fermer_politique(operation: str) -> None:
    """Révoque la politique : l'état de production hors fenêtre d'octroi."""
    _nouvelle_revision_politique(operation, active=False)


def _rouvrir_politique(operation: str) -> None:
    """Octroi daté d'une fenêtre de recalcul, après une révocation."""
    _nouvelle_revision_politique(operation, active=True)


def _creer_approbateurs(finance: bool = True, owner: bool = False) -> None:
    with stockage.transaction() as cnx:
        if finance:
            identite.creer_personne(cnx, "finance-e0-fictif", "Finance (fictif)",
                                    "un-autre-mot-de-passe-suffisamment-long", ["finance"])
        if owner:
            identite.creer_personne(cnx, "owner-e0-fictif", "Propriétaire (fictif)",
                                    "un-mot-de-passe-owner-suffisamment-long", ["nathan_owner"])


def _facture_du_devis(devis_id: str) -> dict:
    with stockage.transaction():
        factures = list(stockage.maillons("m05-financecore", "factures"))
    return next(f for f in factures if f.get("devis_id") == devis_id)


def _envoyer_facture(deps, devis_id: str) -> None:
    """Envoi de la facture : vraie approbation N4 (aucun transport courriel), comme le test de cascade."""
    _creer_approbateurs(finance=True)
    facture = _facture_du_devis(devis_id)
    cap = Capacites({"m05-financecore": deps["m05-financecore"]}, stockage.transaction)
    demande = cap.appeler("m5_envoyer_facture", {"facture_id": facture["facture_id"],
                                                 "horodatage": cm._iso(BASE, 12000)})
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        decision = approbations.decider(cnx, demande["demande_id"], True, "finance-e0-fictif",
                                        outils_executables(deps, stockage.transaction), deps)
    assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"], decision


def _payer_facture(deps, devis_id: str) -> None:
    _creer_approbateurs(finance=False, owner=True)
    facture = _facture_du_devis(devis_id)
    cap = Capacites({"m05-financecore": deps["m05-financecore"]}, stockage.transaction)
    demande = cap.appeler("m5_enregistrer_paiement_facture", {
        "facture_id": facture["facture_id"], "montant_paye": str(facture["montant_apres_taxes"]),
        "approbateur": "Propriétaire (fictif)", "horodatage": cm._iso(BASE, 13000)})
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        decision = approbations.decider(
            cnx, demande["demande_id"], True, "owner-e0-fictif", outils_executables(deps, stockage.transaction), deps,
            attestation={"nom": "CPA (fictif)", "profession": "CPA", "reference_document": "DEPOT-E0-fictif"})
    assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"], decision


# -------------------------------------------------------------------------------------------
# Relevé : ce que voient M5 (traces + événements), M8, M10 et l'apprentissage de M3
# -------------------------------------------------------------------------------------------
def _traces_m5(devis_id: str) -> list[dict]:
    with stockage.transaction():
        traces = [t for t in stockage.maillons("m05-financecore", "rentabilite") if t.get("devis_id") == devis_id]
    sortie = []
    for rang, trace in enumerate(traces, start=1):
        mo = trace["rentabilite"]["cout_reel"]["main_d_oeuvre"]
        sortie.append({
            "rang": rang, "verdict": trace["verdict"],
            "cout_reel_complet": trace["rentabilite"]["cout_reel"]["complet"] is True,
            "projection_empreinte": mo.get("projection_empreinte"),
            "mo_statut": mo.get("statut"),
            "provenance_service_v1": "provenance_service_v1" in trace,
            "provenance_v3": "provenance_v3" in trace,
            "prix_definitif": trace["rentabilite"].get("prix_definitif"),
            "version_entrees": trace["version_entrees"][:12],
        })
    return sortie


def _evenement_courant_m5(devis_id: str) -> dict:
    """L'événement `m5.rentabilite_chantier` de PLUS GRAND `sequence` du devis (la règle de M8/M10), pas le dernier
    inséré."""
    publies = [c for c in cm._publies_m5() if c["devis_id"] == devis_id]
    courant = max(publies, key=lambda c: c["sequence"])
    dernier_insere = publies[-1] if publies else None
    return {
        "nb_evenements": len(publies), "sequences": [c["sequence"] for c in publies],
        "sequence_max": courant["sequence"], "verdict": courant["verdict"],
        "cout_reel_complet": courant["cout_reel_complet"], "cout_reel_cad": courant["cout_reel_cad"],
        "marge_reelle_cad": courant["marge_reelle_cad"], "prix_definitif": courant["prix_definitif"],
        "manque": courant["manque"], "dernier_insere_sequence": dernier_insere["sequence"],
    }


def _m8(deps, wct_id: str) -> dict:
    resultat = cm._mesures_de_m8(deps, wct_id)
    mesures = {m["metric_id"]: m for m in resultat["mesures"]}
    marge = mesures["m8_marge_reelle_cad"]
    with stockage.transaction():
        faits = [f for f in stockage.maillons("m08-analytics", "faits_chantier")
                 if f.get("type_entree") == "rentabilite" and f.get("wct_id") == wct_id]
    courant = max(faits, key=lambda f: f["sequence"])
    return {
        "m8_marge_reelle_cad": {"statut": marge["statut"], "valeur": marge["valeur"], "manque": marge.get("manque")},
        "m8_ecart_marge_cad": mesures["m8_ecart_marge_cad"]["statut"],
        "fait_sequence_max": courant["sequence"], "fait_marge_reelle_cad": courant.get("marge_reelle_cad"),
        "faits_sequences": sorted(f["sequence"] for f in faits),
        "manques": [m.get("raison") for m in resultat["manques"]],
    }


def _m10() -> dict:
    lecons = cm._m10_rentabilites()
    courante = max(lecons, key=lambda m: m["sequence"])
    return {"sequences": [m["sequence"] for m in lecons], "sequence_max": courante["sequence"],
            "marge_reelle_cad": courante["marge_reelle_cad"], "ecart_marge_cad": courante["ecart_marge_cad"],
            "manque": courante.get("manque")}


def _apprentissage_m3(deps, wct_id: str) -> dict:
    # Le compte admin existe déjà : c'est celui de la journée d'équipe certifiée (helpers de cascade).
    admin = contexte.IdentiteAppelante(personne=cm.ADMIN_CERTIFIE, role="admin", source="appareil")
    cap = Capacites({"m03-estimation": deps["m03-estimation"]}, stockage.transaction,
                    appelant="m03-estimation", memoire=False)
    with contexte.appele_par_appareil(admin):
        reponse = cap.appeler(
            "m3_lire_apprentissage_chantier", {"wct_id": wct_id, "coupure_utc": "2026-10-05T00:00:00Z"})
    if reponse.get("ok") is not True:
        return {"ok": False, "reponse": str(reponse)[:300]}
    rapport = reponse["resultat"]
    rent = rapport.get("rentabilite") or {}
    return {"ok": True, "statut": rapport["statut"], "exclusions": rapport.get("exclusions"),
            "verdict_m5": rent.get("verdict_m5"), "cout_reel_complet": rent.get("cout_reel_complet"),
            "statut_rentabilite": rent.get("statut"), "trace_m5_a_jour": rent.get("trace_m5_a_jour"),
            "montant_marge_reelle_cad": rent.get("montant_marge_reelle_cad"), "exclusions_rent": rent.get("exclusions")}


def _releve(deps, etape: str, wct_id: str, devis_id: str) -> dict:
    return {
        "etape": etape,
        "traces_m5": _traces_m5(devis_id),
        "evenement_courant_m5": _evenement_courant_m5(devis_id),
        "m8": _m8(deps, wct_id),
        "m10": _m10(),
        "apprentissage_m3": _apprentissage_m3(deps, wct_id),
    }


# -------------------------------------------------------------------------------------------
# Le parcours commun : chantier terminé (voie certifiée) -> cascade ordinaire -> recalcul certifié
# -------------------------------------------------------------------------------------------
def _amener_a_l_etat_certifie(deps, *, facture_envoyee_avant: bool, politique_ouverte: bool) -> dict:
    cm._m6_prix_au_livre(cm._outils(deps, "m06-material-control"), TARIF_PRIX_LIVRE)
    lead_id, devis_id, chantier_id = "LEAD-E0-fictif", "DEVIS-E0-fictif", "CH-E0-fictif"
    wct_id, intervention_id = cm._chantier_termine(deps, BASE, lead_id, devis_id, chantier_id, 40.0, certifie=True)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    ordinaire = _evenement_courant_m5(devis_id)
    assert ordinaire["verdict"] == "PARTIELLE" and "REJ-COUT-TEMPS-POINTE-ABSENT" in ordinaire["manque"], ordinaire
    if facture_envoyee_avant:
        _envoyer_facture(deps, devis_id)
        cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4, minutes=30))
    cm._recalculer_cout_certifie(wct_id, devis_id, f"e0-certifie-{facture_envoyee_avant}")
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=5))
    if not politique_ouverte:
        _fermer_politique("m4.verifier_v3")
    cm._prouver_main_d_oeuvre_certifiee(intervention_id, wct_id, publications=1)
    return {"wct_id": wct_id, "devis_id": devis_id, "intervention_id": intervention_id, "lead_id": lead_id}


def _ecrire_sortie(cas: dict) -> None:
    sortie = os.environ.get("E0_SORTIE_JSON")
    if not sortie:
        return
    chemin = Path(sortie)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    existant = json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else []
    existant.append(cas)
    chemin.write_text(json.dumps(existant, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _evenement(deps, nom: str, devis_id: str, wct_id: str, minute: int) -> None:
    """Un événement ordinaire de la cascade de M5, livré par le vrai répartiteur."""
    if nom == "variance_m6_republiee":
        _republier("m6.variance_chantier", "republiee", wct_id=wct_id)
    elif nom == "variance_m6_rejouee":
        _rejouer("m6.variance_chantier", wct_id=wct_id)
    elif nom == "devis_accepte_rejoue":
        _rejouer("m3.devis_accepte", devis_id=devis_id)
    elif nom == "travaux_termines_rejoues":
        _rejouer("m4.travaux_termines", wct_id=wct_id)
    elif nom == "facture_envoyee":
        _envoyer_facture(deps, devis_id)
    elif nom == "facture_payee":
        _payer_facture(deps, devis_id)
    elif nom == "prix_livre_change_puis_variance_relue":
        cm._m6_prix_au_livre(cm._outils(deps, "m06-material-control"), 9.0)
        _republier("m6.variance_chantier", "prix", wct_id=wct_id)
    else:  # pragma: no cover
        raise AssertionError(nom)
    _drainer(deps, minute)


# (événement ordinaire, facture envoyée AVANT le recalcul certifié, politique `m4.verifier_v3` encore ouverte)
CAS_ECRASES = [
    ("variance_m6_republiee", False, False),
    ("variance_m6_rejouee", False, False),
    ("devis_accepte_rejoue", False, False),
    ("travaux_termines_rejoues", False, False),
    ("facture_envoyee", False, False),
    ("prix_livre_change_puis_variance_relue", False, False),
    ("variance_m6_republiee", True, False),
    ("variance_m6_rejouee", True, False),
    ("devis_accepte_rejoue", True, False),
    ("travaux_termines_rejoues", True, False),
    ("facture_payee", True, False),
]
# Seul cas où l'état de plus grand `sequence` redevient certifié : la livraison d'un WCT REJOUÉ alors que la politique
# `m4.verifier_v3` est encore ouverte relance la voie V1 (`port_service_m4.publier`), qui republie un certifié APRÈS
# le partiel. Ce n'est pas l'état de production (aucune politique n'existe, I1) : la cascade a quand même tracé et
# publié un partiel avant, que M8 et M10 ont reçu.
CAS_GUERIS = [("travaux_termines_rejoues", False, True)]
CAS = CAS_ECRASES + CAS_GUERIS

# Événements qui ne changent AUCUNE entrée du calcul de M5 (facture envoyée ou payée, prix du livre : eux, en changent).
REJEUX_PURS = {"variance_m6_republiee", "variance_m6_rejouee", "devis_accepte_rejoue", "travaux_termines_rejoues"}
MARGE_CERTIFIEE = "180.00"  # 40 pi x 8,00 $ + 120 min x 50,00 $/h-équipe = 420,00 $ de coût ; prix 600,00 $


def _identifiant(cas) -> str:
    evenement, facture, politique = cas
    etat_facture = "envoyee" if facture else "brouillon"
    return f"{evenement}-facture_{etat_facture}-politique_{'ouverte' if politique else 'fermee'}"


def _executer_cas(cas) -> tuple[dict, dict, dict]:
    evenement, facture_avant, politique = cas
    deps = charger_departements()
    ids = _amener_a_l_etat_certifie(deps, facture_envoyee_avant=facture_avant, politique_ouverte=politique)
    avant = _releve(deps, "apres_recalcul_certifie", ids["wct_id"], ids["devis_id"])
    _evenement(deps, evenement, ids["devis_id"], ids["wct_id"], 30)
    apres = _releve(deps, f"apres_{evenement}", ids["wct_id"], ids["devis_id"])
    _ecrire_sortie({"cas": _identifiant(cas), "avant": avant, "apres": apres})
    return avant, apres, ids


def _est_certifie(releve: dict) -> bool:
    """Vrai si l'état COURANT (plus grand `sequence`) est le coût certifié, à chaque étage."""
    e, m10 = releve["evenement_courant_m5"], releve["m10"]
    derniere = max(releve["traces_m5"], key=lambda t: t["rang"])
    return (
        e["verdict"] == "CALCULEE" and e["cout_reel_complet"] is True and e["marge_reelle_cad"] == MARGE_CERTIFIEE
        and derniere["projection_empreinte"] is not None and derniere["mo_statut"] == "complet"
        and m10["marge_reelle_cad"] == MARGE_CERTIFIEE and releve["m8"]["fait_marge_reelle_cad"] == MARGE_CERTIFIEE
    )


def _verifier_avant_certifie(avant: dict, facture_avant: bool) -> None:
    """Précondition commune : le recalcul certifié a bien publié l'état courant (sequence maximal) à M8 et M10."""
    assert _est_certifie(avant), avant
    e = avant["evenement_courant_m5"]
    assert e["sequence_max"] == e["dernier_insere_sequence"] == len(avant["traces_m5"])
    assert avant["m10"]["sequence_max"] == avant["m8"]["fait_sequence_max"] == e["sequence_max"]
    assert e["prix_definitif"] is facture_avant
    # M8 n'affiche la marge réelle que si le prix est définitif (facture envoyée) ; sinon « non calculable ».
    marge_m8 = avant["m8"]["m8_marge_reelle_cad"]
    if facture_avant:
        assert (marge_m8["statut"], marge_m8["valeur"]) == ("calculee", MARGE_CERTIFIEE)
    else:
        assert marge_m8["statut"] == "non_calculable" and marge_m8["valeur"] is None
    # Le rapport d'apprentissage de M3 relit M5 en direct (calcul ordinaire, sans portée de relecture) : il ne voit
    # jamais l'état certifié, avant comme après (constat 5 de la conception) ; hors périmètre de la cascade.
    assert avant["apprentissage_m3"]["verdict_m5"] == "PARTIELLE"
    assert avant["apprentissage_m3"]["trace_m5_a_jour"] is False


@pytest.mark.parametrize("cas", CAS_ECRASES, ids=[_identifiant(c) for c in CAS_ECRASES])
def test_caracterisation_i5_la_cascade_ordinaire_ecrase_l_etat_certifie(base_durable, cas):
    """CARACTÉRISATION de l'état ACTUEL (verdict E0 : I5 CONFIRMÉE) : l'événement ordinaire fait tracer et publier un
    PARTIEL de `sequence` + 1, sans projection, qui devient l'état courant de M5, M8 et M10 et efface la marge
    certifiée. Quand ce test devient rouge, la régression est corrigée : retirer le `xfail` du test de garde."""
    _, facture_avant, _ = cas
    avant, apres, _ = _executer_cas(cas)
    _verifier_avant_certifie(avant, facture_avant)

    e_avant, e = avant["evenement_courant_m5"], apres["evenement_courant_m5"]
    # M5 : une SEULE trace et un seul événement de plus, de plus grand sequence, partiels et sans projection.
    assert len(apres["traces_m5"]) == len(avant["traces_m5"]) + 1
    assert e["sequence_max"] == e["dernier_insere_sequence"] == e_avant["sequence_max"] + 1
    assert (e["verdict"], e["cout_reel_complet"], e["marge_reelle_cad"], e["cout_reel_cad"]) == (
        "PARTIELLE", False, None, None)
    assert "REJ-COUT-TEMPS-POINTE-ABSENT" in e["manque"]
    nouvelle = apres["traces_m5"][-1]
    assert (nouvelle["verdict"], nouvelle["projection_empreinte"], nouvelle["mo_statut"]) == (
        "PARTIELLE", None, "non_disponible")
    assert not nouvelle["provenance_service_v1"] and not nouvelle["provenance_v3"]
    certifiee = apres["traces_m5"][-2]
    assert certifiee["verdict"] == "CALCULEE" and certifiee["projection_empreinte"] is not None  # l'historique l'a
    # La version d'entrées de l'ordinaire n'est PAS celle du certifié : c'est la raison de l'écrasement
    # (`_essayer_cout_reel` ne compare qu'à la dernière trace). Pour un simple REJEU (aucune entrée changée), le
    # partiel revient même à une version déjà tracée avant le certifié.
    assert nouvelle["version_entrees"] != certifiee["version_entrees"]
    if cas[0] in REJEUX_PURS:
        assert nouvelle["version_entrees"] in {t["version_entrees"] for t in apres["traces_m5"][:-2]}
    # M8 et M10 : le plus grand sequence est le partiel ; la marge certifiée a disparu des deux.
    assert apres["m8"]["fait_sequence_max"] == apres["m10"]["sequence_max"] == e["sequence_max"]
    assert apres["m8"]["fait_marge_reelle_cad"] is None and apres["m10"]["marge_reelle_cad"] is None
    assert apres["m10"]["ecart_marge_cad"] is None
    marge_m8 = apres["m8"]["m8_marge_reelle_cad"]
    assert (marge_m8["statut"], marge_m8["valeur"]) == ("non_calculable", None)
    # Les faits antérieurs (dont le certifié) restent dans l'historique de M8 et de M10 : append-only, rien de perdu.
    assert e_avant["sequence_max"] in apres["m8"]["faits_sequences"]
    assert e_avant["sequence_max"] in apres["m10"]["sequences"]
    assert not _est_certifie(apres)
    # Le prix définitif est dit tel quel : seul l'envoi de la facture le fait passer à vrai.
    assert e["prix_definitif"] is (facture_avant or cas[0] == "facture_envoyee" or cas[0] == "facture_payee")


@pytest.mark.parametrize(
    "cas",
    [pytest.param(c, id=_identifiant(c), marks=pytest.mark.xfail(
        strict=True, raises=AssertionError,
        reason=(
            "I5 (CONCEPTION-ROUTAGE-COUT-CERTIFIE, E0/E1) : la cascade ordinaire de M5 (`_essayer_cout_reel`) compare "
            "`version_entrees` à la seule dernière trace ; l'état certifié (projection M4 V3) a une autre version que "
            "l'état ordinaire, donc un événement ordinaire trace et publie un PARTIEL de sequence + 1 (sans "
            "projection, marge None) que M8 et M10 retiennent comme état courant. Attendu après E1 : l'état de plus "
            "grand sequence reste le certifié.")))
     for c in CAS_ECRASES],
)
def test_garde_i5_un_evenement_ordinaire_ne_remplace_pas_l_etat_certifie(base_durable, cas):
    """GARDE (rouge pour de bonne raison aujourd'hui) : après un événement ordinaire, l'état de plus grand `sequence`
    de M5, M8 et M10 doit rester le coût certifié (CALCULEE, projection présente, marge 180,00 $)."""
    avant, apres, _ = _executer_cas(cas)
    assert _est_certifie(avant)
    assert _est_certifie(apres), (
        apres["evenement_courant_m5"], apres["m8"]["fait_marge_reelle_cad"], apres["m10"]["marge_reelle_cad"])


@pytest.mark.parametrize("cas", CAS_GUERIS, ids=[_identifiant(c) for c in CAS_GUERIS])
def test_i5_politique_ouverte_le_wct_rejoue_republie_le_certifie_apres_le_partiel(base_durable, cas):
    """Garde VERTE : WCT rejoué avec la politique `m4.verifier_v3` encore ouverte. La cascade trace d'abord un partiel
    (sequence + 1), puis la voie V1 de livraison republie le certifié (sequence + 2) dans la même livraison :
    l'état de plus grand sequence reste certifié à chaque étage. Le partiel intermédiaire existe pourtant dans
    l'historique de M5, M8 et M10 (M8/M10 l'ont reçu), ce qui n'est pas l'état de production (aucune politique)."""
    avant, apres, _ = _executer_cas(cas)
    _verifier_avant_certifie(avant, False)
    base = avant["evenement_courant_m5"]["sequence_max"]
    assert apres["evenement_courant_m5"]["sequences"][-3:] == [base, base + 1, base + 2]
    assert [t["verdict"] for t in apres["traces_m5"][-3:]] == ["CALCULEE", "PARTIELLE", "CALCULEE"]
    assert apres["traces_m5"][-2]["projection_empreinte"] is None  # le partiel intermédiaire
    assert apres["traces_m5"][-1]["provenance_service_v1"] is True
    assert _est_certifie(apres)
    assert apres["m8"]["fait_sequence_max"] == apres["m10"]["sequence_max"] == base + 2
    assert base + 1 in apres["m8"]["faits_sequences"] and base + 1 in apres["m10"]["sequences"]


def test_i5_apres_l_ecrasement_les_evenements_suivants_n_ajoutent_rien(base_durable):
    """Convergence (caractérisation) : une fois le partiel tracé, un second événement ordinaire du même devis recalcule
    la même version d'entrées que le dernier partiel : `deja_tracee`, ni trace ni événement de plus. L'écrasement est
    donc UN pas, pas une boucle d'écriture ; il ne se défait pas non plus sans recalcul certifié."""
    deps = charger_departements()
    ids = _amener_a_l_etat_certifie(deps, facture_envoyee_avant=False, politique_ouverte=False)
    wct_id, devis_id = ids["wct_id"], ids["devis_id"]
    _evenement(deps, "variance_m6_rejouee", devis_id, wct_id, 30)
    apres_premier = _releve(deps, "apres_variance", wct_id, devis_id)
    assert apres_premier["evenement_courant_m5"]["verdict"] == "PARTIELLE"
    _evenement(deps, "devis_accepte_rejoue", devis_id, wct_id, 35)
    _evenement(deps, "travaux_termines_rejoues", devis_id, wct_id, 40)
    apres_suivants = _releve(deps, "apres_devis_et_wct", wct_id, devis_id)
    assert apres_suivants["traces_m5"] == apres_premier["traces_m5"]
    assert apres_suivants["evenement_courant_m5"] == apres_premier["evenement_courant_m5"]
    # Un nouveau recalcul certifié (autre intention) republie le certifié, de sequence maximal : l'état se corrige.
    _rouvrir_politique("m4.verifier_v3")
    cm._recalculer_cout_certifie(wct_id, devis_id, "e0-corrige-apres-ecrasement")
    _drainer(deps, 50)
    rattrape = _releve(deps, "apres_nouveau_recalcul", wct_id, devis_id)
    assert _est_certifie(rattrape)
    assert rattrape["evenement_courant_m5"]["sequence_max"] == apres_premier["evenement_courant_m5"]["sequence_max"] + 1
