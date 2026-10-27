"""Saisie privée de tarifs : préparation sans effet, confirmation atomique avec CAS des sources."""
import hashlib
import re
from datetime import date
from decimal import Decimal

from opsys import idempotence, stockage
from opsys.outils import Autonomie, Outil, valider_arguments
from opsys.stockage import codec
from opsys.stockage.maillons import copier_maillons_avec_metadonnees

from . import catalogue_console as acces
from . import catalogue_materiaux, fournisseurs, livre_prix, tarif_soumission

NOMS = frozenset({'m6_lister_fournisseurs_tarif_console', 'm6_preparer_tarif_console', 'm6_confirmer_tarif_console'})
_BASE = {'materiau_id': {'type': 'string', 'minLength': 1, 'maxLength': 100},
         'fournisseur_id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
         'prix_unitaire': {'type': 'string', 'pattern': r'^[0-9]{1,9}(\.[0-9]{1,6})?$', 'maxLength': 16},
         'date_effet': {'type': 'string', 'maxLength': 10},
         'source_document': {'type': ['string', 'null'], 'maxLength': 1000}}
_ANCRE = {'materiau_source': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
          'fournisseur_source': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
          'tarif_rang': {'type': 'integer', 'minimum': -1, 'maximum': 9999},
          'tarif_empreinte': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}}


def schema(proprietes):
    return {'type': 'object', 'properties': proprietes, 'required': list(proprietes), 'additionalProperties': False}


def _empreinte(valeur):
    return hashlib.sha256(codec.encoder(valeur).encode('utf-8')).hexdigest()


def _fournisseurs():
    journal = stockage.maillons(acces.DEPARTEMENT, 'fournisseurs')
    if len(journal) > 10000:
        raise catalogue_materiaux.CatalogueRefuse('SOURCES-TROP-VOLUMINEUSES')
    lignes = list(journal)
    tarif_soumission.verifier_journal_fournisseurs(lignes)
    fiches = fournisseurs.lister_fournisseurs(lignes)
    if any(not tarif_soumission._texte(f.get('nom'), 200) for f in fiches):
        raise catalogue_materiaux.CatalogueRefuse('SOURCE-INVALIDE')
    return fiches


def _livre():
    journal = stockage.maillons(acces.DEPARTEMENT, 'livre_prix')
    if len(journal) >= 10000:
        raise catalogue_materiaux.CatalogueRefuse('SOURCES-TROP-VOLUMINEUSES')
    snapshot = copier_maillons_avec_metadonnees(stockage.connexion_courante(),
                                              departement=acces.DEPARTEMENT, registre='livre_prix')
    lignes = []
    for i, m in enumerate(snapshot.lignes):
        if (m.rang != i or type(m.maillon) is not dict
                or not tarif_soumission._texte(m.maillon.get('materiau_id'), 200)
                or not tarif_soumission._texte(m.maillon.get('fournisseur_id'), 200)):
            raise catalogue_materiaux.CatalogueRefuse('SOURCE-INVALIDE')
        lignes.append((m.rang, m.maillon))
    return journal, lignes


def _preparer(args, reception):
    if (valider_arguments(schema(_BASE), args)
            or re.fullmatch(r'[0-9]{1,9}(\.[0-9]{1,6})?', args['prix_unitaire']) is None):
        raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
    montant = Decimal(args['prix_unitaire'])
    valeur = float(montant)
    if montant <= 0 or Decimal(str(valeur)) != montant:
        raise catalogue_materiaux.CatalogueRefuse('MONTANT-INVALIDE')
    try:
        jour = date.fromisoformat(args['date_effet'])
        if jour.isoformat() != args['date_effet'] or jour > reception.recu_le.date():
            raise ValueError('date')
    except ValueError:
        raise catalogue_materiaux.CatalogueRefuse('DATE-INVALIDE') from None
    document = args['source_document']
    if document is not None and not tarif_soumission._texte(document, 1000):
        raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
    materiau = catalogue_materiaux.lire(stockage.maillons(acces.DEPARTEMENT, catalogue_materiaux.REGISTRE),
                                       args['materiau_id'])
    if not materiau['actif']:
        raise catalogue_materiaux.CatalogueRefuse('MATERIAU-INACTIF')
    fournisseur = next((f for f in _fournisseurs() if f['fournisseur_id'] == args['fournisseur_id']), None)
    if fournisseur is None:
        raise catalogue_materiaux.CatalogueRefuse('FOURNISSEUR-INCONNU')
    journal, lignes = _livre()
    precedents = [(rang, ligne) for rang, ligne in lignes if (ligne['materiau_id'], ligne['fournisseur_id']) ==
                  (args['materiau_id'], args['fournisseur_id'])]
    rang, precedent = precedents[-1] if precedents else (-1, None)
    ancre = dict(materiau_source=materiau['source_id'], fournisseur_source=_empreinte(fournisseur),
                 tarif_rang=rang, tarif_empreinte=_empreinte({'rang': rang, 'entree': precedent}))
    ancien, avertissement = None, None
    if precedent is not None:
        try:
            ancien = tarif_soumission.selectionner_tarif(
                lignes, fournisseur, args['materiau_id'], args['fournisseur_id'], materiau['unite'],
                reception.recu_le.date().isoformat())
        except tarif_soumission.SelectionTarifRefusee as exc:
            avertissement = exc.raison
    resultat = dict(materiau_nom=materiau['nom'], fournisseur_nom=fournisseur['nom'], unite=materiau['unite'],
                    prix_unitaire_decimal=format(montant, 'f'), devise='CAD', date_effet=args['date_effet'],
                    source_document=document, marquage_source=livre_prix.marquage_source_document(document),
                    ancien_tarif=ancien, ancien_indisponible=avertissement, **ancre)
    return resultat, journal, valeur


def lister(debut, limite):
    try:
        acces._autoriser()
        if type(debut) is not int or not 0 <= debut <= 10000 or type(limite) is not int or not 1 <= limite <= 25:
            raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
        fiches = _fournisseurs()
        page = [{'fournisseur_id': f['fournisseur_id'], 'nom': f['nom']} for f in fiches[debut:debut + limite]]
        return acces._borner({'accepte': True, 'resultat': dict(fournisseurs=page, total=len(fiches),
                              suivant=debut + len(page) if debut + len(page) < len(fiches) else None)})
    except (catalogue_materiaux.CatalogueRefuse, tarif_soumission.SelectionTarifRefusee) as exc:
        return _refus(exc)


def _refus(exc):
    return {'accepte': False, 'raison': getattr(exc, 'code', 'SOURCE-INVALIDE')}


def preparer(materiau_id, fournisseur_id, prix_unitaire, date_effet, source_document):
    try:
        _, _, reception = acces._autoriser()
        args = dict(materiau_id=materiau_id, fournisseur_id=fournisseur_id, prix_unitaire=prix_unitaire,
                    date_effet=date_effet, source_document=source_document)
        resultat, _, _ = _preparer(args, reception)
        return acces._borner({'accepte': True, 'resultat': resultat})
    except (catalogue_materiaux.CatalogueRefuse, tarif_soumission.SelectionTarifRefusee) as exc:
        return _refus(exc)


def confirmer(materiau_id, fournisseur_id, prix_unitaire, date_effet, source_document,
              materiau_source, fournisseur_source, tarif_rang, tarif_empreinte):
    try:
        cnx, auteur, reception = acces._autoriser()
        base = dict(materiau_id=materiau_id, fournisseur_id=fournisseur_id, prix_unitaire=prix_unitaire,
                    date_effet=date_effet, source_document=source_document)
        ancre = dict(materiau_source=materiau_source, fournisseur_source=fournisseur_source,
                     tarif_rang=tarif_rang, tarif_empreinte=tarif_empreinte)
        args = dict(base, **ancre)
        if valider_arguments(schema(dict(_BASE, **_ANCRE)), args):
            raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
        meta = acces._META.get()
        if not isinstance(meta, idempotence.Meta) or meta.appareil != 'console:' + auteur:
            raise catalogue_materiaux.CatalogueRefuse('MUTATION-ABSENTE')
        with cnx.begin_nested():
            recu = idempotence.reclamer(cnx, meta, 'm6_confirmer_tarif_console', args, reception.recu_le)
            if recu.rejouee:
                if not isinstance(recu.reponse, dict) or recu.reponse.get('ok') is not True:
                    raise catalogue_materiaux.CatalogueRefuse('SOURCE-INVALIDE')
                return acces._borner(recu.reponse['resultat'])
            nouveau, journal, valeur = _preparer(base, reception)
            if any(nouveau[k] != v for k, v in ancre.items()):
                raise catalogue_materiaux.CatalogueRefuse('SOURCE-MODIFIEE')
            rang = len(journal)
            _, refus = livre_prix.enregistrer_prix(materiau_id, fournisseur_id, valeur, 'CAD', date_effet, journal,
                                                   source_document=source_document, unite=nouveau['unite'])
            if refus is not None:
                raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
            resultat = acces._borner({'accepte': True, 'resultat': dict(tarif_rang=rang,
                                      prix_unitaire_decimal=nouveau['prix_unitaire_decimal'], unite=nouveau['unite'],
                                      devise='CAD', marquage_source=nouveau['marquage_source'])})
            from opsys.etat import journaliser

            journaliser(cnx, auteur, 'm6.tarif_console', materiau_id,
                        {'tarif_rang': rang, 'fournisseur_source': fournisseur_source,
                         'materiau_source': materiau_source})
            idempotence.finaliser(cnx, meta, {'ok': True, 'resultat': resultat})
            return resultat
    except idempotence.MutationConflit:
        return {'accepte': False, 'raison': 'MUTATION-CONFLIT'}
    except (catalogue_materiaux.CatalogueRefuse, tarif_soumission.SelectionTarifRefusee) as exc:
        return _refus(exc)


def outils():
    return (Outil(nom='m6_lister_fournisseurs_tarif_console',
                  description='Console admin : page de fournisseurs nommés.',
                  parametres=schema({'debut': {'type': 'integer', 'minimum': 0, 'maximum': 10000},
                                    'limite': {'type': 'integer', 'minimum': 1, 'maximum': 25}}), fonction=lister),
            Outil(nom='m6_preparer_tarif_console', description='Console admin : vérifier un tarif sans écriture.',
                  parametres=schema(_BASE), fonction=preparer),
            Outil(nom='m6_confirmer_tarif_console', description='Console admin : confirmer un nouveau tarif sourcé.',
                  parametres=schema(dict(_BASE, **_ANCRE)), fonction=confirmer, autonomie=Autonomie.T1))
