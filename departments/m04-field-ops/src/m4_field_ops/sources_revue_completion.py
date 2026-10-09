"""Accès SQL en lecture aux sources M4/M6 ; ni APP/JOURNAL ni factory M6."""

from __future__ import annotations

from sqlalchemy import select

from opsys import approbations, contexte, stockage
from opsys import contrats_variance_m6 as variance_materiaux
from opsys.evenements.schemas import erreurs_charge
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

from . import outbox, registre
from . import revue_completion_sources as revue


def autoriser_admin(cnx):
    ident = contexte.identite_appelante()
    if ident is None or ident.source != "appareil" or ident.role != "admin" or cnx is None:
        raise revue.Refus("IDENTITE-INVALIDE")
    if approbations.signataire_valide(cnx, ident) is None:
        raise revue.Refus("IDENTITE-INVALIDE")
    return ident


def _copies(cnx, departement, nom):
    rows = cnx.execute(
        select(REGISTRES.c.rang, REGISTRES.c.maillon)
        .where(REGISTRES.c.departement == departement, REGISTRES.c.registre == nom)
        .order_by(REGISTRES.c.rang)
    ).all()
    try:
        if any(row.rang != k for k, row in enumerate(rows)):
            raise revue.Refus("REGISTRE-INVALIDE")
        values = [codec.decoder(row.maillon) for row in rows]
        if any(type(v) is not dict for v in values):
            raise revue.Refus("REGISTRE-INVALIDE")
        return values
    except (ValueError, TypeError, KeyError):
        raise revue.Refus("REGISTRE-INVALIDE") from None


def _publication(cnx, ident, type_, producteur):
    row = cnx.execute(
        select(
            EVENEMENTS_SORTANTS.c.type_evenement, EVENEMENTS_SORTANTS.c.producteur, EVENEMENTS_SORTANTS.c.charge
        ).where(EVENEMENTS_SORTANTS.c.evenement_id == ident)
    ).one_or_none()
    if row is None:
        raise revue.Refus("SOURCE-INDISPONIBLE")
    try:
        charge = codec.decoder(row.charge)
        if row.type_evenement != type_ or row.producteur != producteur or erreurs_charge(type_, charge):
            raise revue.Refus("SOURCE-INVALIDE")
        return charge
    except (ValueError, TypeError, KeyError):
        raise revue.Refus("SOURCE-INVALIDE") from None


def charger(cnx, intervention_id, registre_cible=None):
    """Appelé uniquement après garde active admin ou données d'exécution Root confirmées."""
    if cnx is None or not variance_materiaux.texte(intervention_id):
        raise revue.Refus("ARGUMENTS-INVALIDES")
    copies = _copies(cnx, revue.DEPARTEMENT, "principal")
    reg = registre_cible or registre.Registre(stockage.maillons(revue.DEPARTEMENT, "principal"))
    if registre_cible is not None and registre_cible.lire() != copies:
        raise revue.Refus("REGISTRE-INVALIDE")
    if not reg.valider_chaine() or not outbox.verifier_invariants_outbox(reg)[0]:
        raise revue.Refus("REGISTRE-INVALIDE")
    completions = [
        m["wct"] for m in copies if m.get("intervention_id") == intervention_id and type(m.get("wct")) is dict
    ]
    if len(completions) != 1:
        raise revue.Refus("WCT-INCONNU")
    wct = completions[0]
    pub = _publication(cnx, wct["wct_id"], "m4.travaux_termines", revue.DEPARTEMENT)
    if pub != wct:
        raise revue.Refus("LIAISON-INCOHERENTE")
    charge = _publication(cnx, f"m6-variance-{wct['wct_id']}-evaluee", "m6.variance_chantier", "m06-material-control")
    prevus = _copies(cnx, "m06-material-control", "besoins_prevus")
    besoin = variance_materiaux.besoin_pour_devis(wct.get("devis_id"), prevus)
    if besoin is None or besoin.get("chantier_id") != charge["chantier_id"]:
        raise revue.Refus("LIAISON-INCOHERENTE")
    principal = _copies(cnx, "m06-material-control", "principal")
    preuves = _copies(cnx, "m06-material-control", "preuves_pertes_bris")
    classes = _copies(cnx, "m06-material-control", variance_materiaux.REGISTRE)
    refus = _copies(cnx, "m06-material-control", variance_materiaux.REGISTRE_REFUS)
    nombre = len(copies) + len(prevus) + 2
    try:
        source = variance_materiaux.valider_source(wct, charge, principal, preuves, classes, nombre, refus)
    except variance_materiaux.Refus as exc:
        raise revue.Refus(exc.suffixe) from None
    source["nombre_admission"] = nombre
    return reg, source


def autoriser_proposition(arguments, *, frais=True):
    """Seam Cap : autorité actuelle avant SQL métier ; fraîcheur uniquement pour P frais."""
    cnx = stockage.connexion_courante()
    autoriser_admin(cnx)
    revue.valider_arguments(arguments)
    reg, source = charger(cnx, arguments["intervention_id"])
    if frais:
        revue.valider_proposition(reg, source, arguments)
    return reg, source
