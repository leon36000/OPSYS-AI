"""Candidat interne M4 : lecture des faits V3 pour une livraison Core.

Non activé. SQLite seulement ; suppose la réclamation d'écriture du répartiteur
Core dans la même transaction. PostgreSQL reste refusé jusqu'à qualification.
"""

import copy
import re

from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, OPSYS_INSTANCE
from sqlalchemy import select

from . import encodage, outbox
from . import temps_certifies_v2 as v2
from . import temps_certifies_v3 as v3

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA = "opsys.core.m4.source-request.v1"


def _lire(requete):
    """Construit les faits et la projection sous la même requête vérifiée."""
    cnx, schema, instance, evenement_id = requete._verifier()
    if (
        schema != _SCHEMA
        or cnx.engine.dialect.name != "sqlite"
        or type(instance) is not str
        or not instance
        or len(instance) > 256
        or type(evenement_id) is not str
        or not _HEX.fullmatch(evenement_id)
    ):
        raise v2.Refus("REQUETE-INVALIDE")
    try:
        evenement = (
            cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == evenement_id))
            .mappings()
            .one_or_none()
        )
        if (
            evenement is None
            or evenement["type_evenement"] != "m4.travaux_termines"
            or evenement["producteur"] != "m04-field-ops"
        ):
            raise v2.Refus("EVENEMENT-INVALIDE")
        charge = codec.decoder(evenement["charge"])
        if not isinstance(charge, dict) or charge.get("wct_id") != evenement_id:
            raise v2.Refus("EVENEMENT-INVALIDE")
        intervention = charge.get("intervention_id")
        if type(intervention) is not str or not intervention or len(intervention) > 256:
            raise v2.Refus("EVENEMENT-INVALIDE")
        captures = v2._sources(cnx)
        wcts = [
            x.maillon[outbox.CLE_WCT]
            for x in captures[0].lignes
            if outbox.CLE_WCT in x.maillon and x.maillon.get("intervention_id") == intervention
        ]
        if len(wcts) != 1 or encodage.encoder_canonique(wcts[0]) != encodage.encoder_canonique(charge):
            raise v2.Refus("WCT-ABSENT-OU-AMBIGU")
        projection = v2._projection(instance, intervention, evenement_id, captures)
        source_v2 = v2._cas(instance, evenement_id, captures)
        audits = v3._qualifier(cnx, projection, captures)
        source = encodage.empreinte("m4.temps_certifies.cas.v3", source_v2, audits)
        copie = copy.deepcopy(projection)
        if (
            v2._sources(cnx) != captures
            or v3._qualifier(cnx, copie, captures) != audits
            or cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
            != instance
            or requete._verifier() != (cnx, schema, instance, evenement_id)
        ):
            raise v2.Refus("SOURCE-MODIFIEE")
        projection["version"] = v3.VERSION
        empreinte = encodage.empreinte(
            "m4.temps_certifies.v3", {k: v for k, v in projection.items() if k != "empreinte"}
        )
        hash_maillon = projection["wct"]["hash_maillon"]
        if any(type(h) is not str or not _HEX.fullmatch(h) for h in (hash_maillon, source, empreinte)):
            raise v2.Refus("EMPREINTE-INVALIDE")
        faits = (
            "opsys.m4.faits_source.v1",
            instance,
            intervention,
            evenement_id,
            hash_maillon,
            source,
            v3.VERSION,
            empreinte,
        )
        projection["empreinte"] = empreinte
        return faits, {"source": source, "projection": projection}
    except v2.Refus:
        raise
    except (ValueError, KeyError, TypeError, StopIteration) as exc:
        raise v2.Refus("SOURCE-INVALIDE") from exc


def lire(requete):
    """Retourne les huit faits pour Core ; jamais une autorité autonome."""
    return _lire(requete)[0]


def projeter(requete):
    """Projection M4 vérifiée pour un consommateur pendant la portée active."""
    return _lire(requete)
