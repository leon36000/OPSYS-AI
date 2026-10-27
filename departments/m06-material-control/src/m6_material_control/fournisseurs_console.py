"""Fiches fournisseurs privées : PATCH conservateur, CAS et reçu atomique."""
import re

from opsys import idempotence, stockage
from opsys.outils import Autonomie, Outil, valider_arguments
from opsys.stockage import codec

from . import catalogue_console as acces
from . import catalogue_materiaux, contrats, fournisseurs, prix_console, tarif_soumission

NOMS = frozenset({'m6_lire_fournisseur_console', 'm6_enregistrer_fournisseur_console',
                  'm6_lister_fournisseurs_console'})
_ID = {'type': 'string', 'minLength': 1, 'maxLength': 200}
_PATCH = {
    'nom': {'type': 'string', 'minLength': 1, 'maxLength': 200},
    'courriel_commande': {'type': ['string', 'null'], 'maxLength': 254},
    'telephone': {'type': ['string', 'null'], 'maxLength': 80},
    'categories_vendues': {'type': ['array', 'null'], 'maxItems': 25,
                          'items': {'type': 'string', 'minLength': 1, 'maxLength': 100}},
    'delai_habituel_jours': {'type': ['integer', 'null'], 'minimum': 1, 'maximum': 3650},
    'format_commande_prefere': {'type': ['string', 'null'], 'maxLength': 200},
}
_ECRITURE = prix_console.schema(dict(fournisseur_id=_ID,
    modifications={'type': 'object', 'properties': {k: {'type': v['type']} for k, v in _PATCH.items()},
                   'additionalProperties': False, 'minProperties': 1},
    source_attendue={'type': 'string', 'maxLength': 64, 'pattern': r'^(|[0-9a-f]{64})$'}))
_LISTE = prix_console.schema(dict(debut={'type': 'integer', 'minimum': 0, 'maximum': 10000},
                                   limite={'type': 'integer', 'minimum': 1, 'maximum': 50}))
_CHAMPS = contrats.CHAMPS_FOURNISSEUR_REQUIS | contrats.CHAMPS_FOURNISSEUR_OPTIONNELS


def _valider_modifications(modifications, courant):
    # Une valeur historique inchangée reste lisible/corrigeable, même si une
    # saisie nouvelle serait désormais plus strictement bornée.
    if valider_arguments({'properties': _PATCH, 'additionalProperties': False}, modifications):
        raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
    changements = {k: v for k, v in modifications.items() if courant is None or courant.get(k) != v}
    schema = prix_console.schema({k: _PATCH[k] for k in changements})
    if valider_arguments(schema, changements):
        raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
    for cle, valeur in changements.items():
        if isinstance(valeur, str) and not tarif_soumission._texte(valeur, _PATCH[cle]['maxLength']):
            raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
    categories = changements.get('categories_vendues')
    if categories is not None and (not isinstance(categories, list) or len(categories) > 25
                                  or any(not tarif_soumission._texte(c, 100) for c in categories)):
        raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
    delai = changements.get('delai_habituel_jours')
    if delai is not None and (type(delai) is not int or not 1 <= delai <= 3650):
        raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
    courriel = changements.get('courriel_commande')
    if courriel is not None and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', courriel) is None:
        raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')


def _journal():
    journal = stockage.maillons(acces.DEPARTEMENT, 'fournisseurs')
    if len(journal) > 10000:
        raise catalogue_materiaux.CatalogueRefuse('SOURCES-TROP-VOLUMINEUSES')
    lignes = list(journal)
    tarif_soumission.verifier_journal_fournisseurs(lignes)
    return lignes


def _courant(fournisseur_id):
    if not tarif_soumission._texte(fournisseur_id, 200):
        raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
    return fournisseurs.lire_fournisseur(_journal(), fournisseur_id)


def _projection(fiche):
    champs = {k: fiche.get(k) for k in _CHAMPS}
    # Réutiliser la validation historique du domaine dans une liste éphémère :
    # aucune écriture durable, aucune nouvelle contrainte sur les champs conservés.
    _, refus = fournisseurs.enregistrer_fournisseur(
        champs['fournisseur_id'], champs['nom'], fiche.get('horodatage'), [],
        **{k: champs[k] for k in contrats.CHAMPS_FOURNISSEUR_OPTIONNELS})
    if refus is not None:
        raise catalogue_materiaux.CatalogueRefuse('SOURCE-INVALIDE')
    return dict(champs, source_empreinte=prix_console._empreinte(fiche), horodatage=fiche['horodatage'])


def lire(fournisseur_id):
    try:
        acces._autoriser()
        fiche = _courant(fournisseur_id)
        if fiche is None:
            raise catalogue_materiaux.CatalogueRefuse('INTROUVABLE')
        return acces._borner({'accepte': True, 'resultat': _projection(fiche)})
    except (catalogue_materiaux.CatalogueRefuse, tarif_soumission.SelectionTarifRefusee) as exc:
        return prix_console._refus(exc)


def lister(debut, limite):
    try:
        acces._autoriser()
        if (valider_arguments(_LISTE, dict(debut=debut, limite=limite))
                or type(debut) is not int or not 0 <= debut <= 10000
                or type(limite) is not int or not 1 <= limite <= 50):
            raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
        fiches = fournisseurs.lister_fournisseurs(_journal())
        page = [_projection(f) for f in fiches[debut:debut + limite]]
        resultat = dict(fournisseurs=[{k: f[k] for k in ('fournisseur_id', 'nom')} for f in page],
                        total=len(fiches), suivant=debut + limite if debut + limite < len(fiches) else None)
        return acces._borner({'accepte': True, 'resultat': resultat})
    except (catalogue_materiaux.CatalogueRefuse, tarif_soumission.SelectionTarifRefusee) as exc:
        return prix_console._refus(exc)


def enregistrer(fournisseur_id, modifications, source_attendue):
    try:
        cnx, auteur, reception = acces._autoriser()
        args = dict(fournisseur_id=fournisseur_id, modifications=modifications, source_attendue=source_attendue)
        if (valider_arguments(_ECRITURE, args) or len(codec.encoder(args).encode('utf-8')) > 131072
                or not modifications
                or re.fullmatch(r'(|[0-9a-f]{64})', source_attendue) is None):
            raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
        meta = acces._META.get()
        if not isinstance(meta, idempotence.Meta) or meta.appareil != 'console:' + auteur:
            raise catalogue_materiaux.CatalogueRefuse('MUTATION-ABSENTE')
        with cnx.begin_nested():
            recu = idempotence.reclamer(cnx, meta, 'm6_enregistrer_fournisseur_console', args, reception.recu_le)
            if recu.rejouee:
                if not isinstance(recu.reponse, dict) or recu.reponse.get('ok') is not True:
                    raise catalogue_materiaux.CatalogueRefuse('SOURCE-INVALIDE')
                return acces._borner(recu.reponse['resultat'])
            courant = _courant(fournisseur_id)
            if source_attendue != (prix_console._empreinte(courant) if courant else ''):
                raise catalogue_materiaux.CatalogueRefuse('SOURCE-MODIFIEE')
            if courant is None and re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', fournisseur_id) is None:
                raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
            # Le PATCH ne remplace jamais par None une option que la personne n'a pas éditée.
            candidat = {k: courant.get(k) if courant else None for k in _PATCH}
            candidat.update(modifications)
            _valider_modifications(modifications, courant)
            journal = stockage.maillons(acces.DEPARTEMENT, 'fournisseurs')
            if len(journal) >= 10000:
                raise catalogue_materiaux.CatalogueRefuse('SOURCES-TROP-VOLUMINEUSES')
            avant = len(journal)
            fiche, refus = fournisseurs.enregistrer_fournisseur(
                fournisseur_id, candidat['nom'], reception.recu_le.isoformat(), journal,
                **{k: candidat[k] for k in contrats.CHAMPS_FOURNISSEUR_OPTIONNELS})
            if refus is not None:
                raise catalogue_materiaux.CatalogueRefuse('ARGUMENTS')
            resultat = acces._borner({'accepte': True, 'resultat': _projection(fiche)})
            if len(journal) != avant:
                from opsys.etat import journaliser

                journaliser(cnx, auteur, 'm6.fournisseur_console', fournisseur_id,
                            {'source_precedente': source_attendue, 'source_empreinte':
                             resultat['resultat']['source_empreinte']})
            idempotence.finaliser(cnx, meta, {'ok': True, 'resultat': resultat})
            return resultat
    except idempotence.MutationConflit:
        return {'accepte': False, 'raison': 'MUTATION-CONFLIT'}
    except (catalogue_materiaux.CatalogueRefuse, tarif_soumission.SelectionTarifRefusee) as exc:
        return prix_console._refus(exc)


def outils():
    return (Outil(nom='m6_lister_fournisseurs_console', description='Console admin privée : noms des fournisseurs.',
                  parametres=_LISTE, fonction=lister),
            Outil(nom='m6_lire_fournisseur_console', description='Console admin privée : fiche fournisseur sourcée.',
                  parametres=prix_console.schema({'fournisseur_id': _ID}), fonction=lire),
            Outil(nom='m6_enregistrer_fournisseur_console', description='Console admin privée : corriger une fiche.',
                  parametres=_ECRITURE, fonction=enregistrer, autonomie=Autonomie.T1))
