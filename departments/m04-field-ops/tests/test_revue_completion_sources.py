"""Pactes purs FICTIFS et adaptateur SQLite; aucune preuve DEVICE/Gateway."""

from __future__ import annotations

import copy
import datetime as dt
import importlib
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import outbox, outils, registre
from m6_material_control import classement_variance_appareil as c

from opsys import contexte, idempotence
from opsys.outils import Autonomie, Niveau
from opsys.stockage.schema import META as SCHEMA_META

# Schéma courant déclaré : toutes les lignes, y compris la file F4 et Alembic.
TABLES_SQLITE = set(SCHEMA_META.tables) | {"alembic_version"}

p = Path(__file__).with_name("test_outbox.py")
spec = importlib.util.spec_from_file_location("fixture_revue_sources_m4", p)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
LIRE = "m4_lire_dossier_revue_completion_appareil"
ECRIRE = "m4_resoudre_revue_completion_sources"
DATE = "2026-10-09T12:00:00+00:00"


def pur():
    name = "m4_field_ops.revue_completion_sources"
    assert importlib.util.find_spec(name) is not None, "revue liée aux sources absente"
    return importlib.import_module(name)


def source_pure(n=1, classes=True):
    reg, i = fx._intervention_sur_site_avec_pointages()
    ack, err = outbox.completer_intervention(i, fx.H_COMPLETION, reg, ecart_detecte=False, verification_en_attente=True)
    assert err is None
    wct = outbox.lire_outbox(reg)[0][1]
    charge = {
        "evenement_id": f"m6-variance-{ack['wct_id']}-evaluee",
        "wct_id": ack["wct_id"],
        "intervention_id": i,
        "chantier_id": "CHANTIER-FICTIF",
        "statut_variance": "evaluee",
        "signal_critique": True,
        "seuil_pourcentage": 20,
        "horodatage_completion": wct["horodatage_completion"],
        "lignes": [
            {
                "materiau": f"MAT-FICTIF-{k}",
                "unite": "pi",
                "quantite_prevue": "40",
                "quantite_reelle": "60",
                "ecart_pourcentage": "0.5",
                "critique": True,
            }
            for k in range(n)
        ],
    }
    src = c.valider_source(wct, charge, [], [], [], len(reg.lire()))
    if classes:
        h = contexte.HorodatageAppareil(
            "APP-CLASS-FICTIF", dt.datetime.fromisoformat(DATE), dt.datetime.fromisoformat(DATE)
        )
        for k in range(n):
            src["classements"].append(
                c.construire(
                    src,
                    c.selection(src, k),
                    "waste",
                    "FICTIF annotation",
                    None,
                    [],
                    {"personne": "ADMIN-FICTIF", "role": "admin", "source": "appareil"},
                    h,
                )
            )
    return reg, src, i


def demande(reg, source, i, decision="verifiee"):
    return {
        "intervention_id": i,
        "decision": decision,
        "horodatage": DATE,
        "motif": "FICTIF : revue humaine",
        "sources": pur().capture_sources(reg, source, i),
    }


def execution(args, ident="D-APPROVAL-FICTIF"):
    return {
        "demande_approbation_id": ident,
        "empreinte_arguments_proposition": idempotence.empreinte_arguments(args),
        "proposant": {
            "personne": "ADMIN-FICTIF",
            "role": "admin",
            "appareil_id": "APP-P-FICTIF",
            "intention_uuid": "UUID-P-FICTIF",
        },
        "approuve_par": "OWNER-FICTIF",
        "role_approbateur": "nathan_owner",
        "horodatage_decision_serveur": DATE,
        "association_decision": {
            "appareil_id": "APP-D-FICTIF",
            "intention_uuid": "UUID-D-FICTIF",
            "empreinte_arguments": idempotence.empreinte_arguments({"demande_id": ident, "decision": "approuver"}),
            "horodatage_appareil_declare": DATE,
        },
    }


@pytest.mark.parametrize("nom", [LIRE, ECRIRE])
def test_deux_nouveaux_outils_declares_fermes(nom):
    o = next((o for o in outils.outils() if o.nom == nom), None)
    assert o is not None, "outil revue liée absent"
    assert o.roles_appareil == frozenset({"admin"})
    assert o.autonomie is (Autonomie.T0 if nom == LIRE else Autonomie.T1)
    assert o.niveau_effectif is (Niveau.N0 if nom == LIRE else Niveau.N4)
    assert o.parametres["additionalProperties"] is False
    assert set(o.parametres["required"]) == (
        {"intervention_id", "demande_id"}
        if nom == LIRE
        else {"intervention_id", "decision", "horodatage", "motif", "sources"}
    )


def test_pur_verifiee_un_maillon_n4_lie_sans_toucher_v1():
    reg, src, i = source_pure()
    before = reg.lire()
    args = demande(reg, src, i)
    ack, err = pur().resoudre(reg, src, args, execution(args))
    assert err is None
    assert ack["accepte"] and ack["version_schema"] == 2
    assert ack["resultat"]["statut"] == "completed_verified"
    assert reg.lire()[:-1] == before
    m = reg.lire()[-1]
    assert m["sources"] == args["sources"] and m["association_decision"] == execution(args)["association_decision"]
    assert m["horodatage"] == DATE and m["demande_approbation_id"] == "D-APPROVAL-FICTIF"
    assert reg.valider_chaine() and len(outbox.lire_outbox(reg)) == 1


def test_legacy_device_direct_refuse_avant_transition(base_durable):
    reg, _, i = source_pure()
    o = next(o for o in outils.outils(registre_cible=reg) if o.nom == "m4_resoudre_revue_completion")
    before = reg.lire()
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("ADMIN-FICTIF", "admin")):
        reply = o.fonction(i, "verifiee", DATE, "FICTIF legacy")
    assert reply["accepte"] is False
    assert reg.lire() == before


def test_toute_ligne_critique_doit_etre_classee():
    reg, src, i = source_pure(n=2)
    src["classements"].pop()
    args = demande(reg, src, i)
    before = reg.lire()
    ack, err = pur().resoudre(reg, src, args, execution(args))
    assert ack is None and err["code"] == "REJ-M4-REVUE-COUVERTURE-INCOMPLETE"
    assert reg.lire() == before


def test_correction_classement_absent_reste_pending_sans_wct_neuf():
    reg, src, i = source_pure(classes=False)
    args = demande(reg, src, i, "correction")
    assert args["sources"]["classements"][0]["reference"] is None
    ack, err = pur().resoudre(reg, src, args, execution(args))
    assert err is None and ack["resultat"]["statut"] == "completed_pending_review"
    assert len(outbox.lire_outbox(reg)) == 1


@pytest.mark.parametrize("field", ["wct_id", "chantier_id", "completion_ligne_id", "transition_attendue_ligne_id"])
def test_cible_source_croisee_refuse_sans_append(field):
    reg, src, i = source_pure()
    args = demande(reg, src, i)
    args["sources"][field] = "0" * 64
    if field == "wct_id":
        args["sources"]["reference_variance"]["evenement_id"] = "m6-variance-" + "0" * 64 + "-evaluee"
    before = reg.lire()
    ack, err = pur().resoudre(reg, src, args, execution(args))
    assert ack is None and err["code"] == "REJ-M4-REVUE-SOURCES-PERIMEES"
    assert reg.lire() == before


def test_classement_suivant_apres_proposition_refuse_frais():
    reg, src, i = source_pure()
    args = demande(reg, src, i)
    h = contexte.HorodatageAppareil(
        "APP-CLASS-FICTIF", dt.datetime.fromisoformat(DATE), dt.datetime.fromisoformat(DATE)
    )
    src["classements"].append(
        c.construire(
            src,
            c.selection(src, 0),
            "breakage",
            "FICTIF correction",
            c.reference(src["classements"][-1]),
            [],
            {"personne": "ADMIN-FICTIF", "role": "admin", "source": "appareil"},
            h,
        )
    )
    before = reg.lire()
    ack, err = pur().resoudre(reg, src, args, execution(args))
    assert ack is None and err["code"] == "REJ-M4-REVUE-SOURCES-PERIMEES"
    assert reg.lire() == before


def test_correction_selfloop_invalide_la_transition_attendue_de_l_autre_projet():
    reg, src, i = source_pure()
    a = demande(reg, src, i, "correction")
    before = reg.lire()
    ack, err = pur().resoudre(reg, src, a, execution(a))
    assert err is None and len(reg.lire()) == len(before) + 1
    stale = demande(reg, src, i)
    stale["sources"]["transition_attendue_ligne_id"] = a["sources"]["transition_attendue_ligne_id"]
    saved = reg.lire()
    ack, err = pur().resoudre(reg, src, stale, execution(stale, "AUTRE-DEMANDE"))
    assert ack is None and err["code"] == "REJ-M4-REVUE-SOURCES-PERIMEES" and reg.lire() == saved


def test_ratio_et_unite_null_restant_inconnus_pas_zero():
    reg, src, i = source_pure()
    src["charge"]["lignes"][0]["unite"] = None
    src["charge"]["lignes"][0]["ecart_pourcentage"] = None
    src["classements"] = []
    dto = pur().dossier(reg, src, i)
    assert dto["lignes_critiques"][0]["source_ligne"]["unite"] is None
    assert dto["lignes_critiques"][0]["source_ligne"]["ecart_pourcentage"] is None


@pytest.mark.parametrize("bad", [None, 1, {"faux": True}])
def test_source_non_dict_nominale_pas_typeerror(bad):
    reg, src, i = source_pure()
    src["charge"] = bad
    with pytest.raises(pur().Refus) as e:
        pur().dossier(reg, src, i)
    assert e.value.suffixe == "SOURCE-INVALIDE"


def test_chaine_m4_corrompue_ne_devient_pas_dossier():
    reg, src, i = source_pure()
    rows = reg.lire()
    rows[0]["horodatage"] = DATE
    with pytest.raises(pur().Refus) as e:
        pur().dossier(registre.Registre(rows), src, i)
    assert e.value.suffixe == "REGISTRE-INVALIDE"


def test_preflight_arg1500_et_d_reply_entier_sans_write():
    reg, src, i = source_pure()
    args = demande(reg, src, i)
    args["motif"] = "é" * 501
    before = reg.lire()
    ack, err = pur().resoudre(reg, src, args, execution(args))
    assert ack is None and err["code"] == "REJ-M4-REVUE-ARGUMENTS-INVALIDES"
    args["motif"] = "FICTIF"
    ack, err = pur().resoudre(reg, src, args, execution(args), borne=100)
    assert ack is None and err["code"] == "REJ-M4-REVUE-SORTIE-TROP-VOLUMINEUSE"
    assert reg.lire() == before


def test_hash_arguments_n_est_pas_l_encodage_injectif_du_registre_m4():
    reg, src, i = source_pure()
    args = demande(reg, src, i)
    assert pur().empreinte_arguments(args) == idempotence.empreinte_arguments(args)


_m6tests = Path(__file__).resolve().parents[2] / "m06-material-control/tests/test_classement_variance_appareil.py"
spec = importlib.util.spec_from_file_location("fixture_revue_sources_sql_m6", _m6tests)
sqlfx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sqlfx)
monde = sqlfx.monde


def lire_sql(i, actor=None):
    from opsys.outils import executer_atomique

    actor = actor or sqlfx.ADMIN
    o = next(o for o in outils.outils() if o.nom == LIRE)
    with contexte.appele_par_appareil(actor):
        return executer_atomique(o, {"intervention_id": i, "demande_id": None})


def test_SQL_courant_publications_reelles_et_tables_inchangees(monde):
    a = sqlfx.preparer()
    d = sqlfx.demande(a)
    class_ack = sqlfx.executer(sqlfx.ECRIRE, d)["resultat"]
    assert class_ack["accepte"]
    before = sqlfx.fx.fx._tables()
    result = lire_sql(a["formulaire"]["intervention_id"])
    assert result["ok"] and result["resultat"]["accepte"], result
    dto = result["resultat"]["resultat"]
    assert dto["sources"]["reference_variance"] == d["selection"]["reference_variance"]
    assert dto["lignes_critiques"][0]["classement_courant"] == class_ack["resultat"]
    assert dto["reference_completion"]["ligne_id"] != dto["reference_completion"]["hash_maillon"]
    assert dto["couverture"]["positions_sans_classement"] == []
    assert set(before) == TABLES_SQLITE and before == sqlfx.fx.fx._tables()
    assert "cout_unitaire" not in str(dto) and "fix_gps" not in str(dto)


def test_SQL_role_retire_avant_publication_et_zero_mutation(monde, monkeypatch):
    from m4_field_ops import sources_revue_completion as adapter

    from opsys import identite, stockage

    a = sqlfx.preparer()
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, sqlfx.ADMIN.personne, "admin")
    monkeypatch.setattr(adapter, "_publication", lambda *_: pytest.fail("lecture métier avant autorité"))
    before = sqlfx.fx.fx._tables()
    r = lire_sql(a["formulaire"]["intervention_id"])
    assert r["resultat"]["verdict"]["code"] == "REJ-M4-REVUE-IDENTITE-INVALIDE"
    assert before == sqlfx.fx.fx._tables()


def test_SQL_declaration_absente_est_source_indisponible_pas_verified(monde):
    a = sqlfx.fx.preparer()
    before = sqlfx.fx.fx._tables()
    r = lire_sql(a["formulaire"]["intervention_id"])
    assert r["resultat"]["verdict"]["code"] == "REJ-M4-REVUE-SOURCE-INDISPONIBLE"
    assert before == sqlfx.fx.fx._tables()


def test_historique_propre_reste_lisible_apres_append_etranger():
    reg, src, i = source_pure()
    args = demande(reg, src, i)
    ex = execution(args)
    ack, err = pur().resoudre(reg, src, args, ex)
    assert err is None
    own = copy.deepcopy(ack["resultat"])
    reg.ajouter(
        {
            "type_entree": "variance_m6_recue",
            "intervention_id": "AUTRE-FICTIF",
            "horodatage": DATE,
            "evenement_id_variance": "FICTIF",
            "statut_variance": "evaluee",
            "signal_critique": True,
            "seuil_pourcentage": 20,
        }
    )
    dem = {
        "statut": "executee",
        "decide_par": ex["approuve_par"],
        "decide_role": ex["role_approbateur"],
        "decide_le": DATE,
    }
    proof, err = pur().preuve_resolution_historique(
        reg.lire(), ex["demande_approbation_id"], args, {"proposant": ex["proposant"]}, dem
    )
    assert err is None and proof == own and reg.tete() != proof["tete_chaine"]


@pytest.mark.parametrize("key", ["sources", "motif", "decision", "horodatage"])
def test_historique_ne_confirme_pas_un_autre_corps(key):
    reg, src, i = source_pure()
    args = demande(reg, src, i)
    ex = execution(args)
    assert pur().resoudre(reg, src, args, ex)[1] is None
    dem = {
        "statut": "executee",
        "decide_par": ex["approuve_par"],
        "decide_role": ex["role_approbateur"],
        "decide_le": DATE,
    }
    forged = copy.deepcopy(args)
    forged[key] = {} if key == "sources" else "AUTRE-FICTIF"
    proof, err = pur().preuve_resolution_historique(
        reg.lire(), ex["demande_approbation_id"], forged, {"proposant": ex["proposant"]}, dem
    )
    assert proof is None and err["code"] == "REJ-M4-REVUE-REJEU-INCOHERENT"


@pytest.mark.parametrize(
    "field,value",
    [("statut", "completed_pending_review"), ("statut_precedent", "sur_site"), ("champ_inconnu", "FICTIF")],
)
def test_historique_maillon_v2_ferme_et_transition_coherente(field, value):
    from m4_field_ops import encodage

    reg, src, i = source_pure()
    args = demande(reg, src, i)
    ex = execution(args)
    assert pur().resoudre(reg, src, args, ex)[1] is None
    rows = reg.lire()
    original = rows[-1]
    changed = {k: v for k, v in original.items() if k not in {"ligne_id", "precedent_ligne_id"}}
    changed[field] = value
    rows[-1] = {
        **changed,
        "precedent_ligne_id": original["precedent_ligne_id"],
        "ligne_id": encodage.empreinte(changed, original["precedent_ligne_id"]),
    }
    assert registre.Registre(rows).valider_chaine()
    dem = {
        "statut": "executee",
        "decide_par": ex["approuve_par"],
        "decide_role": ex["role_approbateur"],
        "decide_le": DATE,
    }
    proof, err = pur().preuve_resolution_historique(
        rows, ex["demande_approbation_id"], args, {"proposant": ex["proposant"]}, dem
    )
    assert proof is None and err["code"] == "REJ-M4-REVUE-REJEU-INCOHERENT"


def test_panne_postappend_annule_maillon_SQL_et_toutes_tables(monde, monkeypatch):
    from m4_field_ops import sources_revue_completion as adapter

    from opsys import stockage

    a = sqlfx.preparer()
    assert sqlfx.executer(sqlfx.ECRIRE, sqlfx.demande(a))["resultat"]["accepte"]
    with stockage.transaction() as cnx:
        reg, src = adapter.charger(cnx, a["formulaire"]["intervention_id"])
        args = demande(reg, src, a["formulaire"]["intervention_id"])
        n = reg.taille()
    before = sqlfx.fx.fx._tables()
    real = pur().borner_metier

    def panne_postappend(*params, **kwargs):
        if reg.taille() > n:
            raise pur().Refus("SORTIE-TROP-VOLUMINEUSE")
        return real(*params, **kwargs)

    monkeypatch.setattr(pur(), "borner_metier", panne_postappend)
    with pytest.raises(RuntimeError, match="après append"), stockage.transaction():
        pur().resoudre(reg, src, args, execution(args))
    assert before == sqlfx.fx.fx._tables()
    monkeypatch.setattr(pur(), "borner_metier", real)
    # Le factory métier rouvre le registre après rollback : aucune tête mémoire périmée.
    with stockage.transaction() as cnx:
        reg_frais, source_fraiche = adapter.charger(cnx, a["formulaire"]["intervention_id"])
        ack, err = pur().resoudre(reg_frais, source_fraiche, args, execution(args))
    assert err is None and ack["resultat"]["statut"] == "completed_verified"


@pytest.mark.parametrize(
    "champ,valeur", [("signal_critique", None), ("signal_critique", 1), ("seuil_pourcentage", float("nan"))]
)
def test_source_globale_non_mesurable_refuse_ferme(champ, valeur):
    reg, src, i = source_pure(classes=False)
    src["charge"][champ] = valeur
    with pytest.raises(pur().Refus) as e:
        pur().dossier(reg, src, i)
    assert e.value.suffixe == "SOURCE-INVALIDE"


def test_SQL_historique_propre_creation_P_et_decision_SQL_sans_Cap_Device(monde):
    """Vraie API d'approbation SQL, contexte D injecté : aucun Gateway/Cap natif."""
    from opsys import approbations, identite, stockage
    from opsys.approbations_completion_m4 import contexte_decision
    from opsys.departements import lire_manifeste
    from opsys.outils import executer_atomique

    a = sqlfx.preparer()
    assert sqlfx.executer(sqlfx.ECRIRE, sqlfx.demande(a))["resultat"]["accepte"]
    i = a["formulaire"]["intervention_id"]
    current = lire_sql(i)["resultat"]["resultat"]
    args = {
        "intervention_id": i,
        "decision": "verifiee",
        "horodatage": DATE,
        "motif": "FICTIF : revue SQL",
        "sources": current["sources"],
    }
    par_nom = {o.nom: o for o in outils.outils()}
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    meta_p = idempotence.Meta("UUID-P-SQL-FICTIF", "APP-P-SQL-FICTIF", DATE)
    meta_d = idempotence.Meta("UUID-D-SQL-FICTIF", "APP-D-SQL-FICTIF", DATE)
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "owner-sql-fictif", "FICTIF propriétaire", "FICTIF-not-auth", ["admin", "nathan_owner"]
        )
        assert not idempotence.reclamer(cnx, meta_p, ECRIRE, args, dt.datetime.fromisoformat(DATE)).rejouee
        ident = approbations.creer_demande(
            cnx,
            "m04-field-ops",
            ECRIRE,
            args,
            niveau=Niveau.N4,
            provenance_humaine=(sqlfx.ADMIN, meta_p.appareil, meta_p.cle),
        )
        idempotence.finaliser(cnx, meta_p, {"ok": True, "statut": "en_attente_approbation", "demande_id": ident})
    before = sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(sqlfx.ADMIN):
        pending = executer_atomique(par_nom[LIRE], {"intervention_id": i, "demande_id": ident})
    assert pending["resultat"]["accepte"], pending
    assert pending["resultat"]["resultat"]["preuve_completion"] is None
    assert pending["resultat"]["resultat"]["proposition"]["proposant"]["intention_uuid"] == meta_p.cle
    assert before == sqlfx.fx.fx._tables()
    args_d = {"demande_id": ident, "decision": "approuver"}
    with stockage.transaction() as cnx:
        idempotence.reclamer(cnx, meta_d, "m9_decider_demande_approbation", args_d, dt.datetime.fromisoformat(DATE))
        with contexte_decision(meta_d, args_d), contexte.sortie_bornee(5400):
            result = approbations.decider(
                cnx,
                ident,
                True,
                "owner-sql-fictif",
                par_nom,
                {dep.id: dep},
                role="nathan_owner",
                appareil=meta_d.appareil,
            )
        assert result["statut"] == "executee", result
        idempotence.finaliser(cnx, meta_d, {"ok": True, "resultat": result["reponse"]["resultat"]})
    before = sqlfx.fx.fx._tables()
    with contexte.appele_par_appareil(sqlfx.ADMIN):
        historical = executer_atomique(par_nom[LIRE], {"intervention_id": i, "demande_id": ident})
    assert historical["resultat"]["accepte"], historical
    dto = historical["resultat"]["resultat"]
    assert dto["preuve_completion"]["association_decision"]["intention_uuid"] == meta_d.cle
    assert dto["preuve_completion"] == result["reponse"]["resultat"]["resultat"]
    assert before == sqlfx.fx.fx._tables() and set(before) == TABLES_SQLITE


def test_interface_socle_de_variance_delegue_aux_contrats_canoniques_m6():
    nom = "opsys.contrats_variance_m6"
    assert importlib.util.find_spec(nom) is not None, "interface socle M6 absente"
    interface = importlib.import_module(nom)
    assert interface.Refus is c.Refus
    assert interface.valider_source is c.valider_source
    assert interface.projection is c.projection
    assert interface.empreinte_charge is c.encodage.empreinte
    reg, source, i = source_pure()
    dto = pur().dossier(reg, source, i)
    assert dto["source_variance"] == {
        **c.source_projection(source),
        "signal_critique": source["charge"]["signal_critique"],
        "seuil_pourcentage": source["charge"]["seuil_pourcentage"],
    }
    assert dto["lignes_critiques"][0]["classement_courant"] == c.projection(source["classements"][0])
