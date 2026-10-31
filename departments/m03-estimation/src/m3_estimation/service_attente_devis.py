"""Couture interne M3 : attester son devis accepté, sans identité console."""

import hashlib
import json

from sqlalchemy import LargeBinary, cast, func, select

from opsys import stockage
from opsys.evenements.schemas import erreurs_charge
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

from . import devis_durable, estime_vs_reel, outils


def _canon(value):
    return json.dumps(
        json.loads(codec.encoder(value)), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def verifier(requete):
    """Relit les registres M3 dans la requête Core éphémère ; empreinte seule."""
    from opsys.evenements import attente_wct

    if type(requete) is not attente_wct._RequeteSource:
        raise ValueError("requête source non qualifiée")
    return _verifier_commun(requete)["empreinte"]


def _verifier_commun(requete):
    """Contrôles M3 communs, réservés aux deux types de portée Core."""
    from opsys.evenements import attente_wct

    if type(requete) is not attente_wct._RequeteSource:
        from opsys import service_lecture_m4

        if type(requete) is not getattr(service_lecture_m4, "_RequeteDevisM3", None):
            raise ValueError("requête source non qualifiée")
    cnx, evenement_id, devis_id, lead_id = requete._verifier()
    if (
        cnx is not stockage.connexion_courante()
        or cnx.dialect.name != "sqlite"
        or cnx.get_transaction() is None
        or evenement_id != "m3-devis-accepte-" + devis_id
    ):
        raise ValueError("requête M3 invalide")
    filtre = EVENEMENTS_SORTANTS.c.evenement_id == evenement_id
    taille = cnx.execute(
        select(func.length(cast(EVENEMENTS_SORTANTS.c.charge, LargeBinary))).where(filtre)
    ).scalar_one_or_none()
    if type(taille) is not int or not 0 <= taille <= 262144:
        raise ValueError("source M3 absente ou hors limite")
    event = cnx.execute(select(EVENEMENTS_SORTANTS).where(filtre)).mappings().one()
    if event["type_evenement"] != "m3.devis_accepte" or event["producteur"] != "m03-estimation":
        raise ValueError("producteur M3 invalide")
    charge = codec.decoder_strict(event["charge"])
    if type(charge) is not dict or erreurs_charge("m3.devis_accepte", charge):
        raise ValueError("charge M3 invalide")

    def captures():
        return tuple(
            stockage.copier_maillons_stricts(
                cnx,
                departement="m03-estimation",
                registre=nom,
                max_lignes=1000,
                max_octets_ligne=262144,
                max_octets_total=16777216,
            )
            for nom in ("devis", "principal")
        )

    avant = captures()
    lignes_devis = [x.maillon for x in avant[0].lignes]
    if any(type(x) is not dict for x in lignes_devis):
        raise ValueError("registre M3 invalide")
    cible = [
        x
        for x in lignes_devis
        if x.get("devis_id") == devis_id and x.get("type_entree") in ("devis_cree", "transition_devis")
    ]
    if (
        not cible
        or cible[0].get("type_entree") != "devis_cree"
        or cible[0].get("statut") != "brouillon"
        or sum(x.get("type_entree") == "devis_cree" for x in cible) != 1
        or any(x.get("type_entree") != "transition_devis" for x in cible[1:])
        or [x.get("statut") for x in cible[1:]] not in (["accepte"], ["envoye", "accepte"])
        or type(cible[-1].get("approbateur")) is not str
        or not cible[-1]["approbateur"].strip()
        or cible[-1].get("horodatage") != charge.get("horodatage_acceptation")
    ):
        raise ValueError("historique M3 ambigu ou non accepté")
    devis, erreur = devis_durable.lire_devis(lignes_devis, devis_id)
    if erreur or type(devis) is not dict or devis.get("statut") != "accepte" or devis.get("lead_id") != lead_id:
        raise ValueError("devis M3 non accepté ou divergent")
    attendu = devis_durable.charge_evenement_devis_accepte(devis)
    source_hash = devis.get("estimation_source_hash")
    source = outils._source_estimation_exacte(source_hash, devis_id, lead_id)
    if source_hash is not None and source is None:
        raise ValueError("estimation source non vérifiable")
    if source is not None:
        attendu = estime_vs_reel.avec_duree_estimee(
            attendu, devis_id, outils.registre_devis_production(), outils.registre_production().lire()
        )
    if _canon(charge) != _canon(attendu):
        raise ValueError("publication M3 divergente")
    apres = captures()
    if any(a.empreinte_snapshot_calculee != b.empreinte_snapshot_calculee for a, b in zip(avant, apres, strict=True)):
        raise ValueError("source M3 modifiée")
    requete._verifier()
    return {
        "charge": charge,
        "empreinte": hashlib.sha256(_canon({"charge": charge, "devis": devis, "estimation": source})).hexdigest(),
    }
