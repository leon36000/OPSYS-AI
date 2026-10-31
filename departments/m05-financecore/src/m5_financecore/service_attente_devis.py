"""M5 confirme strictement son propre reçu ; aucune lecture SQL privée par Core."""

import hashlib

from sqlalchemy import select

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

from . import devis_recus, encodage


def verifier(requete):
    from opsys.evenements import attente_wct

    if type(requete) is not attente_wct._RequeteSource:
        raise ValueError("requête source non qualifiée")
    cnx, evenement_id, devis_id, lead_id = requete._verifier()
    raw = cnx.execute(
        select(EVENEMENTS_SORTANTS.c.charge).where(EVENEMENTS_SORTANTS.c.evenement_id == evenement_id)
    ).scalar_one()
    charge = codec.decoder_strict(raw)
    if (
        cnx is not stockage.connexion_courante()
        or type(charge) is not dict
        or charge.get("devis_id") != devis_id
        or charge.get("lead_id") != lead_id
    ):
        raise ValueError("requête M5 invalide")
    snapshot = stockage.copier_maillons_stricts(
        cnx,
        departement="m05-financecore",
        registre="devis_recus",
        max_lignes=1000,
        max_octets_ligne=262144,
        max_octets_total=16777216,
    )
    lignes = [
        x.maillon
        for x in snapshot.lignes
        if type(x.maillon) is dict and x.maillon.get("devis_id") == charge.get("devis_id")
    ]
    attendu = devis_recus.construire(
        devis_id=charge["devis_id"],
        lead_id=charge["lead_id"],
        chantier_id=charge["chantier_id"],
        lignes=charge["lignes"],
        prix_total=charge["prix_total"],
        horodatage_acceptation=charge["horodatage_acceptation"],
        cout_total=charge.get("cout_total"),
        taux_marge=charge.get("taux_marge"),
    )
    if len(lignes) != 1 or encodage.encoder_canonique(lignes[0]) != encodage.encoder_canonique(attendu):
        raise ValueError("reçu M5 absent, ambigu ou divergent")
    requete._verifier()
    return hashlib.sha256(encodage.encoder_canonique(lignes[0]).encode("utf-8")).hexdigest()


def verifier_wct_en_attente(cap, projection):
    from opsys import service_capability as sc

    from . import wct_recus

    if type(cap) is not sc._Capacite or sc._COURANTE.get() is not cap.portee:
        raise ValueError("capacité WCT non qualifiée")
    cap.verifier_projection(projection)
    cnx, charge = stockage.connexion_courante(), projection["charge"]
    if cnx is None or type(charge) is not dict:
        raise ValueError("requête WCT invalide")

    def lire(nom):
        snap = stockage.copier_maillons_stricts(
            cnx,
            departement="m05-financecore",
            registre=nom,
            max_lignes=1000,
            max_octets_ligne=262144,
            max_octets_total=16777216,
        )
        return [x.maillon for x in snap.lignes]

    wcts, devis = lire("wct_recus"), lire("devis_recus")
    candidats = [x for x in wcts if type(x) is dict and x.get("wct_id") == charge["wct_id"]]
    par_devis = [x for x in wcts if type(x) is dict and x.get("devis_id") == charge["devis_id"]]
    if (
        len(candidats) != 1
        or len(par_devis) != 1
        or any(type(x) is dict and x.get("devis_id") == charge["devis_id"] for x in devis)
    ):
        raise ValueError("attente WCT ou devis incohérent")
    attendu = wct_recus.construire(
        wct_id=charge["wct_id"],
        intervention_id=charge["intervention_id"],
        devis_id=charge["devis_id"],
        horodatage_completion=charge["horodatage_completion"],
        duree_reelle_minutes=charge.get("duree_reelle_minutes"),
        empreinte_charge=encodage.empreinte(charge),
    )
    if encodage.encoder_canonique(candidats[0]) != encodage.encoder_canonique(attendu) or encodage.encoder_canonique(
        par_devis[0]
    ) != encodage.encoder_canonique(attendu):
        raise ValueError("reçu WCT divergent")
    wct_recus.verifier_rejeu(candidats[0], charge)
    cap.verifier_projection(projection)
