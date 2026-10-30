"""Projection privée V3, avec provenance typée des nouveaux pointages."""
import json
import re
from hashlib import sha256

from sqlalchemy import select

from opsys import contexte
from opsys.stockage.schema import JOURNAL, OPSYS_INSTANCE, REGISTRES

from . import encodage, equipes_pointees_v3, temps_certifies_v2

VERSION = 'opsys.m4.temps_certifies.v3'
_HEX = re.compile('[0-9a-f]{64}\\Z')


def _audits(cnx, preuve):
    rows = cnx.execute(select(JOURNAL.c.id, JOURNAL.c.par, JOURNAL.c.details).where(
        JOURNAL.c.action == 'm4.pointage_equipe_v3', JOURNAL.c.cible == preuve['ligne_id']).limit(2)).all()
    if len(rows) != 1:
        raise temps_certifies_v2.Refus('AUDIT-INVALIDE')
    row = rows[0]
    attendu = {'visite_id': preuve['visite_id'], 'pointage_id': preuve['pointage_id'],
               'equipe_id': preuve['sujet']['id'], 'profil_empreinte': preuve['profil_empreinte'],
               'role': preuve['auteur']['role'], 'source_attendue': preuve['source_attendue'],
               'source_rangs': preuve['source_rangs']}
    if row.par != preuve['auteur']['personne'] or json.loads(row.details) != attendu:
        raise temps_certifies_v2.Refus('AUDIT-INVALIDE')
    return {'id': row.id, 'par': row.par, 'details': attendu}


def _empreintes_prefixes(cnx, nom, capture, demandes):
    if any(type(n) is not int or n < 0 or n > len(capture.lignes) for n in demandes):
        raise temps_certifies_v2.Refus('PREUVE-INVALIDE')
    lignes = cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.cree_le, REGISTRES.c.maillon).where(
        REGISTRES.c.departement == 'm04-field-ops', REGISTRES.c.registre == nom).order_by(REGISTRES.c.rang)).all()
    if len(lignes) != len(capture.lignes):
        raise temps_certifies_v2.Refus('SOURCE-MODIFIEE')
    hachage = sha256(b'[')
    resultats = {0: sha256(b'[]').hexdigest()} if 0 in demandes else {}
    for n, (rang, cree_le, maillon) in enumerate(lignes, 1):
        if rang != capture.lignes[n - 1].rang or cree_le != capture.lignes[n - 1].cree_le:
            raise temps_certifies_v2.Refus('SOURCE-MODIFIEE')
        if n > 1:
            hachage.update(b',')
        ligne = {'rang': rang, 'cree_le': cree_le.isoformat(), 'maillon': maillon}
        hachage.update(json.dumps(ligne, sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':'), allow_nan=False).encode())
        if n in demandes:
            copie = hachage.copy()
            copie.update(b']')
            resultats[n] = copie.hexdigest()
    return resultats


def _qualifier(cnx, projection, captures):
    snapshot, visites_capture = captures[0], captures[1]
    maillons = [r.maillon for r in snapshot.lignes]
    index = {m['ligne_id']: n for n, m in enumerate(maillons)}
    audits = []
    tous = [m for m in maillons if m.get('type_entree') == equipes_pointees_v3.TYPE
            and m.get('intervention_id') == projection['intervention_id']]
    if any(p.get('visite_id') not in {v['visite_id'] for v in projection['visites']} for p in tous):
        raise temps_certifies_v2.Refus('PREUVE-ORPHELINE')
    rangs = [p.get('source_rangs') for p in tous]
    if any(not isinstance(r, dict) or set(r) != {'principal', 'visites'} for r in rangs):
        raise temps_certifies_v2.Refus('PREUVE-INVALIDE')
    principaux = _empreintes_prefixes(cnx, 'principal', snapshot, {r['principal'] for r in rangs})
    visites = _empreintes_prefixes(cnx, 'visites_chantier', visites_capture, {r['visites'] for r in rangs})
    for visite in projection['visites']:
        vid = visite['visite_id']
        evenements = [e for e in visite['evenements'] if e['type'] != 'en_route']
        pointages = {e['source_ligne_id'] for e in evenements}
        preuves = [m for m in maillons if m.get('type_entree') == equipes_pointees_v3.TYPE
                   and m.get('visite_id') == vid]
        groupes = {}
        for preuve in preuves:
            pid = preuve.get('pointage_id')
            sujet, auteur = preuve.get('sujet'), preuve.get('auteur')
            if (pid not in pointages or not isinstance(sujet, dict) or set(sujet) != {'type', 'id'}
                    or sujet['type'] != 'equipe' or sujet['id'] != visite['identifiant_pointe']
                    or not isinstance(auteur, dict) or set(auteur) != {'personne', 'role'}
                    or auteur['role'] != 'admin' or not isinstance(auteur['personne'], str) or not auteur['personne']
                    or not isinstance(preuve.get('profil_empreinte'), str)
                    or not _HEX.fullmatch(preuve['profil_empreinte'])
                    or not _HEX.fullmatch(preuve.get('source_attendue', ''))
                    or not _HEX.fullmatch(preuve.get('intention', ''))
                    or preuve.get('intervention_id') != projection['intervention_id']
                    or preuve['source_rangs']['principal'] != index[pid]
                    or not any(x.maillon.get('ligne_id') == vid for x in
                               visites_capture.lignes[:preuve['source_rangs']['visites']])
                    or encodage.empreinte('m4.pointage_equipe.cas.v3',
                        principaux[preuve['source_rangs']['principal']], visites[preuve['source_rangs']['visites']],
                        preuve['profil_empreinte']) != preuve['source_attendue']
                    or index[pid] >= index[preuve['ligne_id']]
                    or index[preuve['ligne_id']] >= index[visite['fermeture']['source_ligne_id']]):
                raise temps_certifies_v2.Refus('PREUVE-INVALIDE')
            pointage = maillons[index[pid]]
            if (pointage.get('type_entree') != 'pointage' or pointage.get('visite_id') != vid
                    or pointage.get('technicien_id') != sujet['id']
                    or pointage.get('horodatage') != preuve.get('horodatage')):
                raise temps_certifies_v2.Refus('PREUVE-INVALIDE')
            audit = _audits(cnx, preuve)
            audits.append(audit)
            groupes.setdefault(pid, []).append((preuve, audit))
        if any(len(elements) != 1 for elements in groupes.values()):
            raise temps_certifies_v2.Refus('PREUVE-AMBIGUE')
        if pointages and set(groupes) == pointages:
            equipe = visite['identifiant_pointe']
            details = []
            for evenement in evenements:
                preuve, audit = groupes[evenement['source_ligne_id']][0]
                details.append({'pointage_id': preuve['pointage_id'], 'preuve_id': preuve['ligne_id'],
                                'auteur': preuve['auteur'], 'profil_empreinte': preuve['profil_empreinte'],
                                'audit_id': audit['id']})
            visite['equipe_pointee'] = {'statut': 'identifiee', 'identifiant': equipe,
                                       'justification': 'pointages_attestes_v3', 'preuves': details}
            projection['inconnus'] = [x for x in projection['inconnus']
                                      if not (x['visite_id'] == vid and x['code'] == 'equipe_pointee_indeterminee')]
    return audits


def projeter(cnx, intervention_id, wct_id, *, source_attendue=None):
    """Lit les faits V2, puis vérifie les preuves typées et leurs audits SQL."""
    if source_attendue is not None and (not isinstance(source_attendue, str) or not _HEX.fullmatch(source_attendue)):
        raise temps_certifies_v2.Refus('ARGUMENTS')
    try:
        auteur = temps_certifies_v2._autoriser(cnx)
        recu = temps_certifies_v2.projeter(cnx, intervention_id, wct_id)
        captures = temps_certifies_v2._sources(cnx)
        projection = recu['projection']
        if any(c.empreinte_snapshot_calculee != projection['sources'][nom]['empreinte_snapshot']
               for nom, c in zip(('principal', 'visites', 'compositions'), captures, strict=True)):
            raise temps_certifies_v2.Refus('SOURCE-MODIFIEE')
        audits = _qualifier(cnx, projection, captures)
        source = encodage.empreinte('m4.temps_certifies.cas.v3', recu['source'], audits)
        if source_attendue is not None and source_attendue != source:
            raise temps_certifies_v2.Refus('SOURCE-PERIMEE')
        copie = json.loads(json.dumps(recu['projection']))
        requete_instance = select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)
        instance = cnx.execute(requete_instance).scalar_one_or_none()
        if (temps_certifies_v2._sources(cnx) != captures or _qualifier(cnx, copie, captures) != audits
                or instance != projection['instance_id']):
            raise temps_certifies_v2.Refus('SOURCE-MODIFIEE')
        if temps_certifies_v2._autoriser(cnx) != auteur:
            raise temps_certifies_v2.Refus('IDENTITE')
        projection['version'] = VERSION
        projection['empreinte'] = encodage.empreinte(
            'm4.temps_certifies.v3', {k: v for k, v in projection.items() if k != 'empreinte'})
        resultat = {'source': source, 'projection': projection}
        limite = contexte.limite_sortie()
        borne = min(limite if limite is not None else 65536, 65536)
        if len(json.dumps(resultat, ensure_ascii=False, allow_nan=False).encode()) > borne:
            raise temps_certifies_v2.Refus('SORTIE-TROP-VOLUMINEUSE')
        return resultat
    except temps_certifies_v2.Refus:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise temps_certifies_v2.Refus('PREUVE-INVALIDE') from exc
