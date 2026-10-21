"""Fictif : extraction SQL de provenance, sans route Cap ni effet métier M4.

La réservation APP est une fixture explicite ; créer des sources/hashes fictifs
ne constitue pas une publication M4/M6. Les helpers doivent lire sans mutation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json

import pytest
from sqlalchemy import delete, insert, inspect, select, text, update

from opsys import approbations, contexte, idempotence, identite
from opsys.outils import Niveau
from opsys.stockage.schema import APPROBATIONS, JOURNAL, MUTATIONS_APPLIQUEES

OUTIL = "m4_resoudre_revue_completion_sources"
DEP = "m04-field-ops"
DATE = "2026-10-09T08:00:00+00:00"
SERVEUR = "2026-10-09T08:05:00+00:00"
P = idempotence.Meta("PROPOSITION-FICTIVE", "DEVICE-P-FICTIF", DATE)
D = idempotence.Meta("DECISION-FICTIVE", "DEVICE-D-FICTIF", DATE)
ACTEUR = contexte.IdentiteAppelante("admin-proposant-fictif", "admin", source="appareil")
ARGS = {"intervention_id": "I-FICTIVE", "decision": "correction", "horodatage": DATE,
        "motif": "Revue fictive", "sources": {"fictif": True}}


def _module():
    return importlib.import_module("opsys.approbations_completion_m4")


def _empreintes(cnx):
    result = {}
    for name in sorted(inspect(cnx).get_table_names()):
        rows = cnx.execute(text('SELECT * FROM "' + name.replace('"', '""') + '"')).all()
        result[name] = hashlib.sha256(repr(sorted(map(tuple, rows), key=repr)).encode()).hexdigest()
    return result


def _monde(cnx, nathan):
    identite.creer_personne(cnx, ACTEUR.personne, "Admin fictif", "mot-de-passe-fictif-12345", ["admin"])
    idempotence.reclamer(cnx, P, OUTIL, ARGS, dt.datetime.fromisoformat(DATE))
    ident = approbations.creer_demande(cnx, DEP, OUTIL, ARGS, niveau=Niveau.N4,
                                     provenance_humaine=(ACTEUR, P.appareil, P.cle))
    idempotence.finaliser(cnx, P, {"ok": True, "statut": "en_attente_approbation", "demande_id": ident})
    cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
        statut="en_cours", decide_par=nathan, decide_role="nathan_owner", decide_le=SERVEUR))
    args_d = {"demande_id": ident, "decision": "approuver"}
    idempotence.reclamer(cnx, D, "m9_decider_demande_approbation", args_d, dt.datetime.fromisoformat(DATE))
    return ident, args_d


def test_extraction_signature_sql_et_pair_d_propres_sans_ecriture(session, nathan):
    mod = _module()
    with session() as cnx:
        ident, args_d = _monde(cnx, nathan)
        before = _empreintes(cnx)
        with mod.contexte_decision(D, args_d), contexte.executer_demande_approuvee(ident):
            data, refus = mod.donnees_execution(cnx, OUTIL, DEP, ARGS)
        assert refus is None and data["approuve_par"] == nathan
        assert data["role_approbateur"] == "nathan_owner" and data["horodatage_decision_serveur"] == SERVEUR
        assert data["proposant"] == {"personne": ACTEUR.personne, "role": "admin",
                                    "appareil_id": P.appareil, "intention_uuid": P.cle}
        assert data["association_decision"] == {"appareil_id": D.appareil, "intention_uuid": D.cle,
            "empreinte_arguments": idempotence.empreinte_arguments(args_d), "horodatage_appareil_declare": DATE}
        assert _empreintes(cnx) == before
        with contexte.executer_demande_approuvee(ident):
            data, refus = mod.donnees_execution(cnx, OUTIL, DEP, ARGS)
        assert data is None and refus is not None  # reset finally, pas de signature réutilisable


@pytest.mark.parametrize("alteration", ["journal_absent", "journal_double", "hashP", "outilP", "horaD", "statutAPP"])
def test_provenance_absente_ou_alteree_refuse_sans_ecriture(session, nathan, alteration):
    mod = _module()
    with session() as cnx:
        ident, args_d = _monde(cnx, nathan)
        if alteration == "journal_absent":
            cnx.execute(delete(JOURNAL).where(JOURNAL.c.cible == ident))
        elif alteration == "journal_double":
            row = dict(cnx.execute(select(JOURNAL).where(JOURNAL.c.cible == ident)).mappings().one())
            row.pop("id")
            cnx.execute(insert(JOURNAL).values(**row))
        elif alteration == "hashP":
            row = cnx.execute(select(JOURNAL.c.details).where(JOURNAL.c.cible == ident)).scalar_one()
            details = json.loads(row)
            details["arguments_sha256"] = "f" * 64
            cnx.execute(update(JOURNAL).where(JOURNAL.c.cible == ident).values(details=json.dumps(details)))
        elif alteration == "outilP":
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(MUTATIONS_APPLIQUEES.c.appareil == P.appareil)
                        .values(outil="m4_autre_fictif"))
        elif alteration == "horaD":
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(MUTATIONS_APPLIQUEES.c.appareil == D.appareil)
                        .values(horodatage_appareil="2026-10-09T08:00:01+00:00"))
        else:
            cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(statut="executee"))
        before = _empreintes(cnx)
        with mod.contexte_decision(D, args_d), contexte.executer_demande_approuvee(ident):
            data, refus = mod.donnees_execution(cnx, OUTIL, DEP, ARGS)
        assert data is None and refus is not None
        assert _empreintes(cnx) == before


def test_preuve_creation_reste_historique_apres_echec_app(session, nathan):
    mod = _module()
    with session() as cnx:
        ident, _ = _monde(cnx, nathan)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(statut="echec"))
        before = _empreintes(cnx)
        preuve, refus = mod.preuve_proposition(cnx, ident, ARGS)
        assert refus is None and preuve["demande_id"] == ident
        assert preuve["empreinte_arguments"] == idempotence.empreinte_arguments(ARGS)
        assert _empreintes(cnx) == before
