"""Fictif : frontières Cap/SQLite contrôlées, puis producteurs M4/M6 réels.

Les trois premiers cas isolent les gardes avec des handlers de fixture. Les
suivants chargent les factories canoniques et leurs publications durables.
Les identités de transport sont injectées : aucun Gateway ou téléphone prouvé.
"""
from __future__ import annotations

import hashlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import inspect, select, text, update

from opsys import contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import Budget, Departement, charger_departements
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.schema import APPROBATIONS, MUTATIONS_APPLIQUEES, REGISTRES

PROPOSITION = "m4_resoudre_revue_completion_sources"
LECTURE = "m4_lire_dossier_revue_completion_appareil"
ACTEUR = contexte.IdentiteAppelante("admin-revue-fictif", "admin", source="appareil")
META = idempotence.Meta("P-REVUE-FICTIF", "DEVICE-REVUE-FICTIF", "2026-10-09T08:00:00+00:00")


def _tables(cnx):
    result = {}
    for name in sorted(inspect(cnx).get_table_names()):
        rows = cnx.execute(text('SELECT * FROM "' + name.replace('"', '""') + '"')).all()
        result[name] = hashlib.sha256(repr(sorted(map(tuple, rows), key=repr)).encode()).hexdigest()
    return result


def _cap(limite=5400):
    dep = Departement(
        id="m04-field-ops", code="M4", nom="M4 fictif", mission="Frontière Cap seulement",
        module_outils="fixture_non_chargee", mode="ombre", dependances=(), modeles={}, skills=(),
        planifications=(), budget=Budget(10000, 100000), memoire_lecture=(), memoire_ecriture=(),
        kpis=(), racine=Path(__file__).parent,
    )
    schema = {"type": "object", "properties": {
        "intervention_id": {"type": "string"}, "decision": {"enum": ["verifiee", "correction"]},
        "horodatage": {"type": "string"}, "motif": {"type": "string", "maxLength": 500},
        "sources": {"type": "object"},
    }, "required": ["intervention_id", "decision", "horodatage", "motif", "sources"],
        "additionalProperties": False}

    def jamais_execute(**_):
        raise AssertionError("N4 ne doit pas être exécuté pendant la création de demande")

    def lecture_fictive(intervention_id, demande_id):
        return {"accepte": True, "resultat": {"fictif": True, "details": "x" * 7000}}

    outils = [
        Outil(PROPOSITION, "Fixture N4 sans métier", schema, jamais_execute, Autonomie.T1,
              niveau=Niveau.N4, roles_appareil=frozenset({"admin"})),
        Outil(LECTURE, "Fixture T0 volumineuse", {"type": "object", "properties": {
            "intervention_id": {"type": "string"}, "demande_id": {"type": "null"}},
            "required": ["intervention_id", "demande_id"], "additionalProperties": False},
              lecture_fictive, Autonomie.T0, roles_appareil=frozenset({"admin"})),
    ]
    cap = Capacites({}, stockage.transaction, limite_sortie=limite, memoire=False)
    cap.departements = {dep.id: dep}
    cap.index.update({o.nom: (dep, o) for o in outils})
    cap._portees_roles = {"admin": frozenset(o.nom for o in outils)}
    return cap


def _args():
    return {
        "intervention_id": "I-REVUE-FICTIF", "decision": "correction",
        "horodatage": META.horodatage_appareil, "motif": "Examen fictif des sources",
        "sources": {"wct_id": "WCT-FICTIF", "chantier_id": "CHANTIER-FICTIF",
                    "completion_ligne_id": "a" * 64, "transition_attendue_ligne_id": "b" * 64,
                    "reference_variance": {"type": "m6.variance_chantier", "evenement_id": "VAR-FICTIF",
                                           "empreinte_charge": "c" * 64},
                    "classements": [{"position_ligne": n, "materiau_id": f"MAT-FICTIF-{n}",
                                     "reference": {"registre": "classements_variance", "index": n,
                                                   "hash_maillon": "d" * 64}} for n in range(10)]},
    }


def _admin(cnx):
    identite.creer_personne(cnx, ACTEUR.personne, "Admin fictif", "mot-de-passe-fictif-12345", ["admin"])


def test_proposition_inapprovable_1500_refusee_avant_claim_et_journal(session):
    import json

    args = _args()
    assert len(json.dumps(args, ensure_ascii=False)) > 1500
    with session() as cnx:
        _admin(cnx)
        before = _tables(cnx)
    with contexte.appele_par_appareil(ACTEUR):
        observed = _cap().appeler(PROPOSITION, args, meta=META)
    assert observed.get("statut") != "en_attente_approbation", observed
    with session() as cnx:
        assert _tables(cnx) == before


def test_proposition_identite_non_confirmee_ne_cree_pas_app_ni_claim(session):
    args = _args()
    args["sources"]["classements"] = []
    with session() as cnx:
        before = _tables(cnx)
    with contexte.appele_par_appareil(ACTEUR):
        observed = _cap().appeler(PROPOSITION, args, meta=META)
    assert observed.get("statut") != "en_attente_approbation", observed
    with session() as cnx:
        assert _tables(cnx) == before


def test_lecture_quota_tres_bas_ne_cree_pas_artefact(session):
    with session() as cnx:
        _admin(cnx)
        before = _tables(cnx)
    with contexte.appele_par_appareil(ACTEUR):
        observed = _cap(40).appeler(LECTURE, {"intervention_id": "I-REVUE-FICTIF", "demande_id": None})
    assert observed.get("ok") is False and not observed.get("tronque"), observed
    with session() as cnx:
        assert _tables(cnx) == before


_path_m4 = Path(__file__).resolve().parents[1] / "departments/m04-field-ops/tests/test_revue_completion_sources.py"
_spec_m4 = importlib.util.spec_from_file_location("fixture_m4_sources_cap_root", _path_m4)
_fx_m4 = importlib.util.module_from_spec(_spec_m4)
_spec_m4.loader.exec_module(_fx_m4)
monde = _fx_m4.monde


def _preparer_metier():
    """Producteurs réels et SQLite fictive ; aucune réponse API construite à la main."""
    import m4_field_ops
    import m6_material_control

    base = Path(__file__).resolve().parents[1]
    assert all(Path(m.__file__).resolve().is_relative_to(base) for m in (m4_field_ops, m6_material_control))
    a = _fx_m4.sqlfx.preparer()
    assert _fx_m4.sqlfx.executer(_fx_m4.sqlfx.ECRIRE, _fx_m4.sqlfx.demande(a))["resultat"]["accepte"]
    ident = a["formulaire"]["intervention_id"]
    cap = Capacites(charger_departements(), stockage.transaction, limite_sortie=5400)
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        lecture = cap.appeler(LECTURE, {"intervention_id": ident, "demande_id": None})
    assert lecture["resultat"]["accepte"], lecture
    args = {"intervention_id": ident, "decision": "verifiee", "horodatage": _fx_m4.DATE,
            "motif": "FICTIF : jonction Cap", "sources": lecture["resultat"]["resultat"]["sources"]}
    return cap, args


def test_cap_proposition_reelle_rend_sa_preuve_creation_propre(monde):
    cap, args = _preparer_metier()
    meta = idempotence.Meta("P-CAP-REEL-FICTIF", "APP-P-CAP-FICTIF", _fx_m4.DATE)
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        result = cap.appeler(PROPOSITION, args, meta=meta)
    assert result["ok"] and result["statut"] == "en_attente_approbation", result
    assert result.get("version_schema") == 1 and "preuve_proposition" in result, result
    assert result["preuve_proposition"]["proposant"]["intention_uuid"] == meta.cle
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        replay = cap.appeler(PROPOSITION, args, meta=meta)
    assert replay == {**result, "rejoue": True}
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_cap_decision_reelle_retrouve_son_propre_maillon_et_signature(monde):
    cap, args = _preparer_metier()
    p = idempotence.Meta("P-CAP-D-FICTIF", "APP-P-CAP-FICTIF", _fx_m4.DATE)
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        proposition = cap.appeler(PROPOSITION, args, meta=p)
    assert proposition["ok"] and proposition["statut"] == "en_attente_approbation", proposition
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "owner-cap-fictif", "Propriétaire fictif", "mot-de-passe-fictif-12345",
                               ["admin", "nathan_owner"])
    acteur = contexte.IdentiteAppelante("owner-cap-fictif", "admin", source="appareil")
    d = idempotence.Meta("D-CAP-REEL-FICTIF", "APP-D-CAP-FICTIF", _fx_m4.DATE)
    arguments_d = {"demande_id": proposition["demande_id"], "decision": "approuver"}
    with contexte.appele_par_appareil(acteur):
        result = cap.appeler("m9_decider_demande_approbation", arguments_d, meta=d)
    assert result["ok"] and result["resultat"]["accepte"], result
    decision = result["resultat"]["resultat"]
    assert decision["statut"] == "executee" and decision.get("preuve_completion"), decision
    assert decision["preuve_completion"]["association_decision"]["intention_uuid"] == d.cle
    assert decision["preuve_completion"]["approuve_par"] == acteur.personne


def _decision_metier():
    cap, args = _preparer_metier()
    p = idempotence.Meta("P-CACHE-FICTIF", "APP-P-CAP-FICTIF", _fx_m4.DATE)
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        proposition = cap.appeler(PROPOSITION, args, meta=p)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "owner-cache-fictif", "Propriétaire fictif", "mot-de-passe-fictif-12345",
                               ["admin", "nathan_owner"])
    acteur = contexte.IdentiteAppelante("owner-cache-fictif", "admin", source="appareil")
    d = idempotence.Meta("D-CACHE-FICTIF", "APP-D-CAP-FICTIF", _fx_m4.DATE)
    arguments_d = {"demande_id": proposition["demande_id"], "decision": "approuver"}
    with contexte.appele_par_appareil(acteur):
        result = cap.appeler("m9_decider_demande_approbation", arguments_d, meta=d)
    assert result["resultat"]["resultat"]["statut"] == "executee", result
    return cap, args, p, proposition, acteur, d, arguments_d, result


def test_cache_d_succes_substitue_negatif_ne_nie_pas_le_maillon(monde):
    cap, _, _, _, acteur, d, args_d, _ = _decision_metier()
    cible = (MUTATIONS_APPLIQUEES.c.appareil == d.appareil) & (MUTATIONS_APPLIQUEES.c.cle_idempotence == d.cle)
    with stockage.transaction() as cnx:
        old = cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse).where(cible)).scalar_one()
        assert old
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(cible).values(reponse=stockage.codec.encoder({
            "ok": True, "resultat": {"accepte": False, "verdict": {"code": "deja_decidee", "detail": "FICTIF"}},
        })))
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(acteur):
        replay = cap.appeler("m9_decider_demande_approbation", args_d, meta=d)
    assert replay.get("ok") is False and replay.get("issue") == "inconnue", replay
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_rejeu_d_role_owner_retire_avant_restitution(monde):
    cap, _, _, _, acteur, d, args_d, _ = _decision_metier()
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, acteur.personne, "nathan_owner")
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(acteur):
        replay = cap.appeler("m9_decider_demande_approbation", args_d, meta=d)
    assert replay.get("ok") is False and replay.get("issue") == "inconnue", replay
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_rejeu_p_quota_reduit_ne_transmet_pas_confirmation_hors_borne(monde):
    _, args, p, _, _, _, _, _ = _decision_metier()
    cap = Capacites(charger_departements(), stockage.transaction, limite_sortie=40)
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        replay = cap.appeler(PROPOSITION, args, meta=p)
    assert replay.get("ok") is False and replay.get("issue") == "inconnue", replay
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_cache_d_ne_confirme_pas_app_resultat_substitue(monde):
    cap, _, _, proposition, acteur, d, args_d, _ = _decision_metier()
    with stockage.transaction() as cnx:
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == proposition["demande_id"]).values(
            resultat='{"ok":true,"resultat":{"accepte":true,"resultat":{"fictif":"autre résultat"}}}',
        ))
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(acteur):
        replay = cap.appeler("m9_decider_demande_approbation", args_d, meta=d)
    assert replay.get("ok") is False and replay.get("issue") == "inconnue", replay
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_creation_p_quota_tres_bas_refuse_avant_claim_et_journal(monde):
    _, args = _preparer_metier()
    cap = Capacites(charger_departements(), stockage.transaction, limite_sortie=40)
    p = idempotence.Meta("P-QUOTA-FICTIF", "APP-P-CAP-FICTIF", _fx_m4.DATE)
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        observed = cap.appeler(PROPOSITION, args, meta=p)
    assert observed.get("ok") is False, observed
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_decision_fraiche_non_owner_ne_cree_pas_claim(monde):
    cap, args = _preparer_metier()
    p = idempotence.Meta("P-NONOWNER-FICTIF", "APP-P-CAP-FICTIF", _fx_m4.DATE)
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        proposition = cap.appeler(PROPOSITION, args, meta=p)
    before = _fx_m4.sqlfx.fx.fx._tables()
    d = idempotence.Meta("D-NONOWNER-FICTIF", "APP-D-CAP-FICTIF", _fx_m4.DATE)
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        observed = cap.appeler("m9_decider_demande_approbation",
                               {"demande_id": proposition["demande_id"], "decision": "approuver"}, meta=d)
    assert observed.get("ok") is False and observed.get("issue") == "inconnue", observed
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_rejeu_d_nominal_apres_recreation_cap_sans_mutation(monde):
    _, _, _, _, acteur, d, args_d, original = _decision_metier()
    cap = Capacites(charger_departements(), stockage.transaction, limite_sortie=5400)
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(acteur):
        replay = cap.appeler("m9_decider_demande_approbation", args_d, meta=d)
    assert replay == {**original, "rejoue": True}, replay
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_lecture_historique_ne_confirme_pas_app_resultat_contradictoire(monde):
    cap, args, _, proposition, acteur, _, _, _ = _decision_metier()
    with stockage.transaction() as cnx:
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == proposition["demande_id"]).values(
            resultat='{"ok":true,"resultat":{"accepte":false,"verdict":{"code":"FICTIF","detail":"refus"}}}',
        ))
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(acteur):
        observed = cap.appeler(LECTURE, {"intervention_id": args["intervention_id"],
                                      "demande_id": proposition["demande_id"]})
    assert observed["resultat"]["accepte"] is False, observed
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_rejeu_p_heure_changee_ne_restitue_pas_confirmation(monde):
    cap, args, p, _, _, _, _, _ = _decision_metier()
    altered = idempotence.Meta(p.cle, p.appareil, "2026-10-09T08:00:01+00:00")
    assert altered.horodatage_appareil != p.horodatage_appareil
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        observed = cap.appeler(PROPOSITION, args, meta=altered)
    assert observed.get("ok") is False and observed.get("issue") == "inconnue", observed
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_decision_quota_tres_bas_ne_cree_pas_artefact_ni_effet(monde):
    cap, args = _preparer_metier()
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        p = cap.appeler(PROPOSITION, args, meta=idempotence.Meta(
            "P-DQUOTA-FICTIF", "APP-P-CAP-FICTIF", _fx_m4.DATE))
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "owner-quota-fictif", "Propriétaire fictif", "mot-de-passe-fictif-12345",
                               ["admin", "nathan_owner"])
    owner = contexte.IdentiteAppelante("owner-quota-fictif", "admin", source="appareil")
    before = _fx_m4.sqlfx.fx.fx._tables()
    cap = Capacites(charger_departements(), stockage.transaction, limite_sortie=40)
    with contexte.appele_par_appareil(owner):
        observed = cap.appeler("m9_decider_demande_approbation",
                               {"demande_id": p["demande_id"], "decision": "approuver"},
                               meta=idempotence.Meta("D-QUOTA-FICTIF", "APP-D-CAP-FICTIF", _fx_m4.DATE))
    assert observed.get("ok") is False and not observed.get("tronque"), observed
    assert before == _fx_m4.sqlfx.fx.fx._tables()


@pytest.mark.parametrize("alteration", ["heure", "autre_pair"])
def test_d_reponse_positive_non_transferee_a_intention_distincte(monde, alteration):
    cap, _, _, _, acteur, d, args_d, _ = _decision_metier()
    if alteration == "heure":
        altered = idempotence.Meta(d.cle, d.appareil, "2026-10-09T12:00:00.000001+00:00")
        assert altered.horodatage_appareil != d.horodatage_appareil
    else:
        altered = idempotence.Meta("D2-CACHE-FICTIF", d.appareil, d.horodatage_appareil)
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(acteur):
        observed = cap.appeler("m9_decider_demande_approbation", args_d, meta=altered)
    assert not (observed.get("ok") is True and observed.get("resultat", {}).get("accepte") is True), observed
    after = _fx_m4.sqlfx.fx.fx._tables()
    # D2 peut conserver son verdict propre, mais ne modifie aucun objet métier.
    assert before == after if alteration == "heure" else all(
        before[k] == after[k] for k in before if k != "mutations_appliquees")


@pytest.mark.parametrize("retrait", ["role", "inactive"])
def test_rejeu_p_autorite_sql_retiree_avant_cache(monde, retrait):
    cap, args, p, _, _, _, _, _ = _decision_metier()
    with stockage.transaction() as cnx:
        if retrait == "role":
            identite.retirer_role(cnx, _fx_m4.sqlfx.ADMIN.personne, "admin")
        else:
            identite.activer(cnx, _fx_m4.sqlfx.ADMIN.personne, False)
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        observed = cap.appeler(PROPOSITION, args, meta=p)
    assert observed.get("ok") is False, observed
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def _reclasser_metier(args):
    ref = args["sources"]["classements"][0]["reference"]
    selection = {"wct_id": args["sources"]["wct_id"],
                 "reference_variance": args["sources"]["reference_variance"],
                 "position_ligne": 0, "materiau_id": args["sources"]["classements"][0]["materiau_id"]}
    observed = _fx_m4.sqlfx.executer(_fx_m4.sqlfx.ECRIRE, {
        "selection": selection, "cause": "breakage", "motif": "FICTIF nouvelle revue M6",
        "classement_attendu": ref, "references_pieces": [],
    })
    assert observed["resultat"]["accepte"], observed
    assert observed["resultat"]["resultat"]["reference"] != ref


def test_rejeu_d_propre_reste_historique_apres_nouvelle_classification(monde):
    cap, args, _, _, acteur, d, args_d, original = _decision_metier()
    _reclasser_metier(args)
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(acteur):
        replay = cap.appeler("m9_decider_demande_approbation", args_d, meta=d)
    assert replay == {**original, "rejoue": True}, replay
    assert before == _fx_m4.sqlfx.fx.fx._tables()


def test_classification_changee_apres_p_clot_app_echec_sans_transition(monde):
    cap, args = _preparer_metier()
    with contexte.appele_par_appareil(_fx_m4.sqlfx.ADMIN):
        p = cap.appeler(PROPOSITION, args, meta=idempotence.Meta(
            "P-SOURCE-PERIMEE-FICTIF", "APP-P-CAP-FICTIF", _fx_m4.DATE))
    _reclasser_metier(args)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "owner-source-fictif", "Propriétaire fictif", "mot-de-passe-fictif-12345",
                               ["admin", "nathan_owner"])
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("owner-source-fictif", "admin", source="appareil")):
        observed = cap.appeler("m9_decider_demande_approbation",
                               {"demande_id": p["demande_id"], "decision": "approuver"},
                               meta=idempotence.Meta("D-SOURCE-PERIMEE-FICTIF", "APP-D-CAP-FICTIF", _fx_m4.DATE))
    assert observed["resultat"]["resultat"]["statut"] == "echec", observed
    assert observed["resultat"]["resultat"]["preuve_completion"] is None
    after = _fx_m4.sqlfx.fx.fx._tables()
    assert all(before[k] == after[k] for k in before if k not in {
        "approbations", "journal", "mutations_appliquees"})
    with stockage.transaction() as cnx:
        statut = cnx.execute(select(APPROBATIONS.c.statut).where(APPROBATIONS.c.id == p["demande_id"])).scalar_one()
        assert statut == "echec"


def test_concurrence_puis_d_meme_pair_un_seul_app_et_maillon(monde):
    cap, args = _preparer_metier()

    def concurrents(outil, arguments, meta, acteur):
        barrier = Barrier(2)

        def appeler():
            barrier.wait(timeout=5)
            with contexte.appele_par_appareil(acteur):
                return cap.appeler(outil, arguments, meta=meta)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(appeler) for _ in range(2)]
            return [f.result(timeout=10) for f in futures]

    p = concurrents(PROPOSITION, args, idempotence.Meta(
        "P-CONCURRENT-FICTIF", "APP-P-CAP-FICTIF", _fx_m4.DATE), _fx_m4.sqlfx.ADMIN)
    assert all(x["ok"] and x["statut"] == "en_attente_approbation" for x in p), p
    assert sorted(x["rejoue"] for x in p) == [False, True]
    assert p[0]["demande_id"] == p[1]["demande_id"]
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "owner-concurrent-fictif", "Propriétaire fictif", "mot-de-passe-fictif-12345",
                               ["admin", "nathan_owner"])
        before = cnx.execute(select(REGISTRES).where(REGISTRES.c.departement == "m04-field-ops")).all()
        assert len(cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.outil == PROPOSITION)).all()) == 1
    d = concurrents("m9_decider_demande_approbation", {"demande_id": p[0]["demande_id"], "decision": "approuver"},
                    idempotence.Meta("D-CONCURRENT-FICTIF", "APP-D-CAP-FICTIF", _fx_m4.DATE),
                    contexte.IdentiteAppelante("owner-concurrent-fictif", "admin", source="appareil"))
    assert all(x["resultat"]["resultat"]["statut"] == "executee" for x in d), d
    assert sorted(x["rejoue"] for x in d) == [False, True]
    assert d[0]["resultat"] == d[1]["resultat"]
    with stockage.transaction() as cnx:
        after = cnx.execute(select(REGISTRES).where(REGISTRES.c.departement == "m04-field-ops")).all()
    assert len(after) == len(before) + 1


@pytest.mark.parametrize("champ,valeur", [
    ("arguments", "{FICTIF-JSON-INVALIDE"), ("arguments", "null"), ("arguments", "[]"),
    ("resultat", "{FICTIF-JSON-INVALIDE"), ("departement", "FICTIF-AUTRE"), ("niveau", "FICTIF-AUTRE"),
])
def test_d_cache_app_corrompue_ne_tombe_pas_sur_rejeu_generique(monde, champ, valeur):
    cap, _, _, p, acteur, d, args_d, _ = _decision_metier()
    with stockage.transaction() as cnx:
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == p["demande_id"]).values(
            **{champ: valeur}))
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(acteur):
        observed = cap.appeler("m9_decider_demande_approbation", args_d, meta=d)
    assert observed.get("ok") is False and observed.get("issue") == "inconnue", observed
    assert before == _fx_m4.sqlfx.fx.fx._tables()


@pytest.mark.parametrize("brut", ["{FICTIF-JSON-INVALIDE", "[]", "null"])
def test_d_cache_brut_malforme_conserve_intention_sans_mutation(monde, brut):
    cap, _, _, _, acteur, d, args_d, _ = _decision_metier()
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == d.appareil, MUTATIONS_APPLIQUEES.c.cle_idempotence == d.cle,
        ).values(reponse=brut))
    before = _fx_m4.sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(acteur):
        observed = cap.appeler("m9_decider_demande_approbation", args_d, meta=d)
    assert observed.get("ok") is False and observed.get("issue") == "inconnue", observed
    assert before == _fx_m4.sqlfx.fx.fx._tables()
