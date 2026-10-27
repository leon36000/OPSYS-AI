"""Ports privés du catalogue M6 : autorité SQL, transaction et reçu de mutation."""
import json
from contextlib import contextmanager
from contextvars import ContextVar

from opsys import approbations, contexte, idempotence, stockage
from opsys.outils import Autonomie, Outil, valider_arguments

from . import catalogue_materiaux as domaine

DEPARTEMENT = 'm06-material-control'
NOMS = frozenset({'m6_enregistrer_materiau_console', 'm6_lire_materiau_console', 'm6_lister_materiaux_console'})
_META = ContextVar('m6_catalogue_meta', default=None)


@contextmanager
def contexte_mutation(meta):
    token = _META.set(meta)
    try:
        yield
    finally:
        _META.reset(token)


def schemas():
    ident = {'type': 'string', 'minLength': 1, 'maxLength': 100, 'pattern': r'^[a-zA-Z0-9_.:-]+$'}
    revision = {'type': 'integer', 'minimum': 0, 'maximum': domaine.MAX_SOURCES}
    proprietes = {
        'enregistrer': dict(materiau_id=ident, nom={'type': 'string', 'minLength': 1, 'maxLength': 200},
                           unite={'type': 'string', 'minLength': 1, 'maxLength': 40}, actif={'type': 'boolean'},
                           raison={'type': 'string', 'minLength': 1, 'maxLength': 500}, revision_attendue=revision),
        'lire': dict(materiau_id=ident, revision=revision),
        'lister': dict(debut=revision, limite={'type': 'integer', 'minimum': 1, 'maximum': 50},
                       actifs_seulement={'type': 'boolean'}),
    }
    return {k: {'type': 'object', 'properties': v, 'required': list(v), 'additionalProperties': False}
            for k, v in proprietes.items()}


def _autoriser():
    cnx = stockage.connexion_courante()
    personne = contexte.identite_appelante()
    if (cnx is None or personne is None or personne.role != 'admin' or personne.source != 'console'
            or contexte.departement_origine_appelante() != 'console' or contexte.appel_provient_du_mcp()):
        raise domaine.CatalogueRefuse('IDENTITE')
    signataire = approbations.signataire_valide(cnx, personne)
    if signataire is None or signataire.role != 'admin':
        raise domaine.CatalogueRefuse('IDENTITE')
    if cnx.dialect.name != 'sqlite':
        raise domaine.CatalogueRefuse('INSTANCE-NON-QUALIFIEE')
    reception = contexte.horodatage_reception()
    if (reception is None or reception.appareil != 'console:' + signataire.personne
            or reception.recu_le.utcoffset() is None):
        raise domaine.CatalogueRefuse('RECEPTION-ABSENTE')
    return cnx, signataire.personne, reception


def _borner(resultat):
    taille = len(json.dumps({"ok": True, "resultat": resultat}, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    limite = contexte.limite_sortie()
    if taille > (65536 if limite is None else min(limite, 65536)):
        raise domaine.CatalogueRefuse('SORTIE-TROP-VOLUMINEUSE')
    return resultat


def _executer(operation, arguments):
    try:
        cnx, auteur, reception = _autoriser()
        if valider_arguments(schemas()[operation], arguments):
            raise domaine.CatalogueRefuse('ARGUMENTS')
        journal = stockage.maillons(DEPARTEMENT, domaine.REGISTRE)
        if operation != 'enregistrer':
            r = getattr(domaine, operation)(journal, **arguments)
            return _borner({'accepte': True, 'resultat': r})
        meta = _META.get()
        if not isinstance(meta, idempotence.Meta) or meta.appareil != 'console:' + auteur:
            raise domaine.CatalogueRefuse('MUTATION-ABSENTE')
        with cnx.begin_nested():
            recu = idempotence.reclamer(cnx, meta, 'm6_enregistrer_materiau_console', arguments, reception.recu_le)
            if recu.rejouee:
                if not isinstance(recu.reponse, dict) or recu.reponse.get('ok') is not True:
                    raise domaine.CatalogueRefuse('SOURCE-INVALIDE')
                return _borner(recu.reponse['resultat'])
            r = domaine.enregistrer(journal, **arguments, auteur=auteur, horodatage=reception.recu_le.isoformat())
            resultat = _borner({'accepte': True, 'resultat': r})
            from opsys.etat import journaliser

            journaliser(cnx, auteur, 'm6.catalogue_materiau', r['materiau_id'],
                        {'revision': r['revision'], 'source_id': r['source_id']})
            idempotence.finaliser(cnx, meta, {'ok': True, 'resultat': resultat})
            return resultat
    except idempotence.MutationConflit:
        return {'accepte': False, 'raison': 'MUTATION-CONFLIT'}
    except domaine.CatalogueRefuse as exc:
        return {'accepte': False, 'raison': exc.code}


def enregistrer(materiau_id, nom, unite, actif, raison, revision_attendue):
    return _executer('enregistrer', dict(materiau_id=materiau_id, nom=nom, unite=unite,
                                       actif=actif, raison=raison, revision_attendue=revision_attendue))


def lire(materiau_id, revision):
    return _executer('lire', dict(materiau_id=materiau_id, revision=revision))


def lister(debut, limite, actifs_seulement):
    return _executer('lister', dict(debut=debut, limite=limite, actifs_seulement=actifs_seulement))


def outils():
    s = schemas()
    return (Outil(nom='m6_enregistrer_materiau_console',
                  description='Console admin privée : réviser une fiche matériau.',
                  parametres=s['enregistrer'], fonction=enregistrer, autonomie=Autonomie.T1),
            Outil(nom='m6_lire_materiau_console', description='Console admin privée : fiche matériau versionnée.',
                  parametres=s['lire'], fonction=lire),
            Outil(nom='m6_lister_materiaux_console', description='Console admin privée : page de matériaux nommés.',
                  parametres=s['lister'], fonction=lister))
