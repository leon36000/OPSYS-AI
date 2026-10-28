"""Préparation CSV privée sur trois snapshots canoniques; aucune application de tarif."""
import re

from sqlalchemy import LargeBinary, cast, func, select

from opsys import stockage
from opsys.outils import Outil, valider_arguments
from opsys.stockage.maillons import copier_maillons_avec_metadonnees
from opsys.stockage.schema import REGISTRES

from . import catalogue_console as acces
from . import (
    catalogue_materiaux,
    fournisseurs,
    fournisseurs_console,
    historique_prix,
    import_tarifs,
    import_tarifs_csv,
    livre_prix,
    prix_console,
    tarif_soumission,
)

NOM = 'm6_preparer_import_tarifs_console'
MAX_SOURCES = 10000
MAX_OCTETS = 8388608
_REGISTRES = ('catalogue_materiaux', 'fournisseurs', 'livre_prix')


def schema():
    champs = {k: {'type': 'string', 'minLength': 1, 'maxLength': 200}
              for k in ('materiau_id', 'unite', 'prix_unitaire_decimal', 'devise', 'date_effet')}
    return prix_console.schema(dict(
        source_csv_utf8={'type': 'string', 'minLength': 1, 'maxLength': import_tarifs.MAX_SOURCE},
        mapping_colonnes=prix_console.schema(champs), separateur={'type': 'string', 'enum': [',', ';']},
        fournisseur_id={'type': 'string', 'minLength': 1, 'maxLength': 200},
        source_document={'type': 'string', 'minLength': 1, 'maxLength': 1000},
        source_attendue={'type': ['string', 'null'], 'pattern': '^[0-9a-f]{64}$'}))


def capturer(cnx):
    if cnx is None or cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise catalogue_materiaux.CatalogueRefuse('INSTANCE-NON-QUALIFIEE')
    # Compter les trois familles avant le premier décodage, y compris une corruption hors couple.
    for registre in _REGISTRES:
        condition = (REGISTRES.c.departement == acces.DEPARTEMENT) & (REGISTRES.c.registre == registre)
        n, octets = cnx.execute(select(func.count(), func.sum(func.length(cast(REGISTRES.c.maillon, LargeBinary))))
                               .select_from(REGISTRES).where(condition)).one()
        # Le prepare de saisie réserve une place au futur append du livre (refus à 10000).
        limite = MAX_SOURCES - 1 if registre == 'livre_prix' else MAX_SOURCES
        if n > limite or (octets or 0) > MAX_OCTETS:
            raise catalogue_materiaux.CatalogueRefuse('SOURCES-TROP-VOLUMINEUSES')
    return {registre: copier_maillons_avec_metadonnees(cnx, departement=acces.DEPARTEMENT, registre=registre)
            for registre in _REGISTRES}


def _lignes(snapshot):
    lignes = []
    for i, ligne in enumerate(snapshot.lignes):
        if type(ligne.rang) is not int or ligne.rang != i or type(ligne.maillon) is not dict:
            raise catalogue_materiaux.CatalogueRefuse('SOURCE-INVALIDE')
        lignes.append(ligne.maillon)
    return lignes


def _sources(snapshots):
    return {k: snapshots[k].empreinte_snapshot_calculee for k in _REGISTRES}


def _preparation(candidat, materiau, fournisseur, livre, jour):
    precedents = [(rang, entree) for rang, entree in livre
                  if (entree['materiau_id'], entree['fournisseur_id']) ==
                  (candidat['materiau_id'], candidat['fournisseur_id'])]
    rang, precedent = precedents[-1] if precedents else (-1, None)
    ancien, avertissement = None, None
    if precedent is not None:
        try:
            ancien = tarif_soumission.selectionner_tarif(livre, fournisseur, candidat['materiau_id'],
                candidat['fournisseur_id'], materiau['unite'], jour)
        except tarif_soumission.SelectionTarifRefusee as exc:
            avertissement = exc.raison
    return dict(materiau_nom=materiau['nom'], fournisseur_nom=fournisseur['nom'], unite=materiau['unite'],
                prix_unitaire_decimal=candidat['prix_unitaire_decimal'], devise='CAD',
                date_effet=candidat['date_effet'], source_document=candidat['source_document'],
                marquage_source=livre_prix.marquage_source_document(candidat['source_document']),
                ancien_tarif=ancien, ancien_indisponible=avertissement, materiau_source=materiau['source_id'],
                fournisseur_source=prix_console._empreinte(fournisseur), tarif_rang=rang,
                tarif_empreinte=prix_console._empreinte(dict(rang=rang, entree=precedent)))


def projeter(snapshots, preparation, jour_reference):
    cat = _lignes(snapshots['catalogue_materiaux'])
    _, materiaux, _ = catalogue_materiaux._charger(cat)
    repertoire = _lignes(snapshots['fournisseurs'])
    tarif_soumission.verifier_journal_fournisseurs(repertoire)
    fiches = fournisseurs.lister_fournisseurs(repertoire)
    for fiche in fiches:
        fournisseurs_console._projection(fiche)
    hors_contrat = any(not tarif_soumission._texte(fiche['nom'], 200) for fiche in fiches)
    lot = preparation['lot']
    fournisseur = next((f for f in fiches if f['fournisseur_id'] == lot['fournisseur_id']), None)
    livre = list(enumerate(_lignes(snapshots['livre_prix'])))
    historique_prix._capturer(livre)
    # Conserver l’ordre des clés décodées : le reçu de saisie existant utilise le codec natif.
    source_sql = _sources(snapshots)
    source = import_tarifs._sha(dict(preparation=preparation['preparation_sha256'],
                                    jour_reference=jour_reference, sources_sql=source_sql))
    lignes = []
    for ligne in lot['lignes']:
        erreurs = list(ligne['erreurs'])
        candidat = ligne['candidat']
        saisie = None
        if candidat is not None:
            materiau = materiaux.get(candidat['materiau_id'])
            if materiau is None:
                erreurs.append('MATERIAU_INCONNU')
            elif not materiau['actif']:
                erreurs.append('MATERIAU_INACTIF')
            elif materiau['unite'] != candidat['unite']:
                erreurs.append('UNITE_CATALOGUE_DIFFERENTE')
            if fournisseur is None:
                erreurs.append('FOURNISSEUR_INCONNU')
            if hors_contrat:
                erreurs.append('REPERTOIRE_HORS_CONTRAT_SAISIE')
            if not erreurs:
                saisie = _preparation(candidat, materiau, fournisseur, livre, jour_reference)
        lignes.append(dict(position=ligne['position'], numero_ligne=ligne['numero_ligne'],
                           candidat=candidat, erreurs=erreurs, preparation_saisie=saisie,
                           statut='A_CORRIGER' if erreurs else 'A_REVOIR'))
    revalides = sum(ligne['preparation_saisie'] is not None for ligne in lignes)
    return dict(version='m6-import-tarifs-apercu-prive-v1', source=source, sources_sql=source_sql,
                jour_reference=jour_reference, source_sha256=lot['source_sha256'],
                mapping_sha256=lot['mapping_sha256'], preparation_sha256=preparation['preparation_sha256'],
                statut='A_REVOIR' if revalides == len(lignes) else 'A_CORRIGER', total_lignes=len(lignes),
                candidats_revalides=revalides, lignes=lignes,
                avertissements=['SOURCE_DOCUMENTAIRE_NON_AUTHENTIFIEE', 'CONFIRMATION_EXPLICITE_REQUISE'])


def _autorite(cnx, auteur):
    courant, signataire, _ = acces._autoriser()
    if courant is not cnx or signataire != auteur:
        raise catalogue_materiaux.CatalogueRefuse('IDENTITE')


def preparer(source_csv_utf8, mapping_colonnes, separateur, fournisseur_id, source_document, source_attendue=None):
    try:
        cnx, auteur, reception = acces._autoriser()
        arguments = dict(source_csv_utf8=source_csv_utf8, mapping_colonnes=mapping_colonnes, separateur=separateur,
                         fournisseur_id=fournisseur_id, source_document=source_document,
                         source_attendue=source_attendue)
        # Le validateur commun ne contrôle pas maxLength/pattern; borner avant encode.
        if (valider_arguments(schema(), arguments) or type(source_csv_utf8) is not str
                or (source_attendue is not None and (type(source_attendue) is not str
                    or re.fullmatch('[0-9a-f]{64}', source_attendue) is None))):
            raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
        if len(source_csv_utf8) > import_tarifs.MAX_SOURCE:
            raise import_tarifs.Refus('SOURCE_TROP_VOLUMINEUSE')
        jour = reception.recu_le.date().isoformat()
        preparation = import_tarifs_csv.preparer(source_csv_utf8.encode('utf-8'), mapping_colonnes=mapping_colonnes,
            separateur=separateur, fournisseur_id=fournisseur_id, source_document=source_document, jour_reference=jour)
        snapshots = capturer(cnx)
        vue = projeter(snapshots, preparation, jour)
        if source_attendue is not None and source_attendue != vue['source']:
            raise catalogue_materiaux.CatalogueRefuse('SOURCE-PERIMEE')
        resultat = acces._borner(dict(accepte=True, resultat=vue))
        _autorite(cnx, auteur)
        if _sources(capturer(cnx)) != _sources(snapshots):
            raise catalogue_materiaux.CatalogueRefuse('SOURCE-MODIFIEE')
        _autorite(cnx, auteur)
        return resultat
    except (catalogue_materiaux.CatalogueRefuse, historique_prix.Refus, import_tarifs.Refus) as exc:
        return dict(accepte=False, raison=exc.code)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return dict(accepte=False, raison='SOURCE-INVALIDE')


def outil():
    return Outil(nom=NOM, description='Console admin privée : préparer une liste CSV sur les sources M6 courantes.',
                 parametres=schema(), fonction=preparer)
