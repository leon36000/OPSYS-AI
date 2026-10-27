"""Choix privé de comptes humains actuels, distinct des déclarations historiques M4."""
import hashlib
import json
from urllib.parse import urlencode

from m4_field_ops.absences_ecriture import ROLES_INTERNES
from sqlalchemy import LargeBinary, cast, func, select
from starlette.datastructures import QueryParams

from opsys import identite, stockage
from opsys.stockage.schema import PERSONNES as P
from opsys.stockage.schema import ROLES_PERSONNES as R

from . import journal_equipes, pages
from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

MAX_COMPTES = 10000
MAX_ROLES = 80000
MAX_OCTETS = 8388608
VERSION = 'comptes-internes-actuels-v1'


def _eligible():
    def present(condition):
        return select(R.c.identifiant).where(
            R.c.identifiant == P.c.identifiant, condition).correlate(P).exists()

    return (present(R.c.role.in_(sorted(ROLES_INTERNES)))
            & ~present(R.c.role == 'system_agent') & ~present(~R.c.role.in_(sorted(identite.ROLES))))


def _conditions_roles():
    return R.c.identifiant.in_(select(P.c.identifiant).where(_eligible()))


def _lignes(cnx):
    # Seules ces colonnes alimentent le répertoire; ni secret, ni nom de client/agent.
    comptes = cnx.execute(select(P.c.identifiant, P.c.nom, P.c.actif).where(_eligible())
                          .order_by(P.c.identifiant)).all()
    roles = cnx.execute(select(R.c.identifiant, R.c.role).where(_conditions_roles())
                       .order_by(R.c.identifiant, R.c.role)).all()
    return dict(comptes=[list(r) for r in comptes], roles=[list(r) for r in roles])


def _encoder(valeur):
    return json.dumps(valeur, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _capturer(cnx):
    if cnx is None or cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise lecture.Refus('INSTANCE-NON-QUALIFIEE')

    def taille(colonne):
        return func.length(cast(colonne, LargeBinary))

    n, octets = cnx.execute(select(func.count(), func.sum(taille(P.c.identifiant) + taille(P.c.nom)
                                        + taille(P.c.actif))).select_from(P).where(_eligible())).one()
    nr, octets_roles = cnx.execute(select(func.count(), func.sum(taille(R.c.identifiant) + taille(R.c.role)))
                                  .select_from(R).where(_conditions_roles())).one()
    if n > MAX_COMPTES or nr > MAX_ROLES or (octets or 0) + (octets_roles or 0) > MAX_OCTETS:
        raise lecture.Refus('SOURCE-TROP-VOLUMINEUSE')
    source = _lignes(cnx)
    try:
        if len(source['comptes']) != n or len(source['roles']) != nr:
            raise lecture.Refus('SOURCE-MODIFIEE')
        for identifiant, nom, actif in source['comptes']:
            if (not identite.identifiant_valide(identifiant) or identifiant.strip() != identifiant
                    or not isinstance(nom, str) or not nom.strip() or type(actif) is not bool):
                raise lecture.Refus('SOURCE-INVALIDE')
        brut = _encoder(source)
    except (TypeError, UnicodeError):
        raise lecture.Refus('SOURCE-INVALIDE') from None
    if len(brut) > MAX_OCTETS:
        raise lecture.Refus('SOURCE-TROP-VOLUMINEUSE')
    return source, hashlib.sha256(brut).hexdigest()


def lire(cnx, session, jour, *, debut=0, limite=50, source_attendue=None):
    autorite._admin(cnx, session)
    if type(debut) is not int or type(limite) is not int:
        raise ValueError('page invalide')
    params = dict(jour=jour, debut=str(debut), limite=str(limite))
    if source_attendue is not None:
        params['source_attendue'] = source_attendue
    args = journal_equipes.arguments(QueryParams(params))
    source, empreinte = _capturer(cnx)
    curseur = hashlib.sha256(_encoder([VERSION, args['jour'], empreinte])).hexdigest()
    if source_attendue is not None and source_attendue != curseur:
        raise lecture.Refus('SOURCE-PERIMEE')
    comptes = sorted(source['comptes'], key=lambda r: (r[1], r[0]))
    resultat = dict(jour=args['jour'], debut=debut, total=len(comptes), source=curseur,
                    source_snapshot=empreinte, suivant=debut + limite if debut + limite < len(comptes) else None,
                    lignes=[dict(personne_id=i, nom_actuel=n, actif=a) for i, n, a in comptes[debut:debut + limite]])
    resultat = lecture._sortie(resultat)
    autorite._admin(cnx, session)
    if _capturer(cnx)[1] != empreinte:
        raise lecture.Refus('SOURCE-MODIFIEE')
    autorite._admin(cnx, session)
    return resultat


def url_jour(jour, prefixe):
    return prefixe + '/crm/journal-equipes/comptes?' + urlencode(dict(jour=jour))


def contenu(vue, prefixe, limite):
    from . import absences_personnes

    def lien(debut, titre):
        args = dict(jour=vue['jour'], debut=debut, limite=limite, source_attendue=vue['source'])
        cible = prefixe + '/crm/journal-equipes/comptes?' + urlencode(args)
        return f'<a href="{pages.e(cible)}">{titre}</a>'

    retour = prefixe + '/crm/journal-equipes?' + urlencode(dict(jour=vue['jour']))
    corps = (f'<p><a href="{pages.e(retour)}">Retour au journal</a></p><h2>Choisir un compte interne</h2>'
             '<p>Les noms et l’état des comptes sont actuels. Ils ne prouvent ni emploi passé, ni présence, '
             'ni absence. Les comptes désactivés restent consultables sans être réactivés.</p>'
             f'<p>Jour de consultation : {pages.e(vue["jour"])} · {vue["total"]} comptes admissibles.</p>')
    nav = []
    if vue['debut']:
        nav.append(lien(max(0, vue['debut'] - limite), 'Page précédente'))
    if vue['suivant'] is not None:
        nav.append(lien(vue['suivant'], 'Page suivante'))
    corps += '<nav aria-label="Pages des comptes internes">' + ' · '.join(nav) + '</nav>'
    if not vue['lignes']:
        corps += ('<p>Aucun compte interne admissible.</p>' if vue['total'] == 0 else
                  '<p>Aucun compte sur cette page. ' + lien(0, 'Première page') + '</p>')
    corps += ('<table><thead><tr><th>Nom actuel du compte</th><th>Identifiant</th><th>État actuel</th>'
              '<th>Consultation</th></tr></thead><tbody>')
    for ligne in vue['lignes']:
        cible = absences_personnes.url_declaration(vue['jour'], ligne['personne_id'], prefixe)
        etat = 'Compte actif' if ligne['actif'] else 'Compte désactivé'
        corps += (f'<tr><td>{pages.e(ligne["nom_actuel"])}</td><td>{pages.e(ligne["personne_id"])}</td>'
                  f'<td>{etat}</td><td><a href="{pages.e(cible)}">Consulter ce compte</a></td></tr>')
    return corps + '</tbody></table>' + absences_personnes.formulaire_consultation(vue['jour'], prefixe)


def creer_router(*, session_page, cnx_factory, prefixe, rendre):
    from fastapi import APIRouter, HTTPException, Request

    router = APIRouter()

    @router.get('/crm/journal-equipes/comptes')
    def page(request: Request):
        session = session_page(request)
        try:
            args = journal_equipes.arguments(request.query_params)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Choisir un jour et une page valides') from None
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, session, **args)
                reponse = rendre(session, 'Comptes internes actuels', contenu(vue, prefixe, args['limite']))
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Liste trop volumineuse; réduire la page')
                autorite._admin(cnx, session)
                if _capturer(cnx)[1] != vue['source_snapshot']:
                    raise lecture.Refus('SOURCE-MODIFIEE')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Comptes indisponibles; relire la liste') from None
        return reponse

    return router
