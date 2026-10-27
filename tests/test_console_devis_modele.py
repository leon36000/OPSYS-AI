"""Parcours réel du brouillon avec modèle figé; toutes les données sont fictives."""
import html
import importlib.util
import io
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opsys import contexte, idempotence, stockage
from opsys.console import devis_modele_ui

spec = importlib.util.spec_from_file_location(
    'fixture_modeles_devis', Path(__file__).with_name('test_console_modeles_soumission.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
client_crm = m.client_crm
catalogue = m.catalogue
FICTIF = True
ROUTE = '/crm/lead/lead-fictif-001/nouvelle-soumission'


def preparer(client, session):
    r = m.direct(session)
    assert r['accepte'], r
    choix = client.get(ROUTE)
    assert choix.status_code == 200, choix.text
    lien = html.unescape(re.search(r'href="([^"]+\?modele_id=[^"]+)"', choix.text)[1])
    page = client.get(lien.removeprefix(m.base.PREFIXE))
    assert page.status_code == 200, page.text
    form = re.search(r'<form method="post" action="[^"]+/nouvelle-soumission"(.*?)</form>', page.text, re.S)[1]
    p = {k: '' for k in devis_modele_ui.CHAMPS}
    p.update({k: html.unescape(v) for k, v in re.findall(
        r'<input type="hidden" name="([^"]+)" value="([^"]*)">', form)})
    assert p['modele_revision'] == '1' and p['modele_source'] and p['csrf']
    p.update(taux_marge='0.35', description_0='Pose FICTIVE', quantite_0='2', unite_0='pi', cout_unitaire_0='378.91')
    return p


def direct(session, p, *, quota=65536, origine='console'):
    from m3_estimation import outils

    now = datetime(2030, 6, 1, tzinfo=UTC)
    meta = idempotence.Meta(p['mutation_id'], 'console:admin.fictif', now.isoformat())
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que('m03-estimation', origine=origine), contexte.sortie_bornee(quota),
          outils.contexte_modeles(meta),
          contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, now, now))):
        return outils.creer_devis_depuis_modele(
            p['devis_id'], 'lead-fictif-001', None,
            [{k: p[f'{k}_0'] or None for k in devis_modele_ui.CHAMPS_LIGNE}], p['taux_marge'],
            p['modele_id'], int(p['modele_revision']), p['modele_source'])


def test_creation_modele_fige_documents_et_acceptation(catalogue, session):
    from m3_estimation import devis_durable, outils
    from pypdf import PdfReader

    p = preparer(catalogue, session)
    # Révision concurrente du catalogue après affichage : l'ancienne version choisie reste explicite.
    assert m.direct(session, cle='v2', revision_attendue=1, clauses='Clause V2 FICTIVE')['accepte']
    r = catalogue.post(ROUTE, data=p, follow_redirects=False)
    assert r.status_code == 303, r.text
    detail = r.headers['location'].removeprefix(m.base.PREFIXE)
    assert 'Modèle figé' in catalogue.get(detail).text
    from sqlalchemy import select

    from opsys.stockage.schema import MUTATIONS_APPLIQUEES
    with session() as cnx:
        recu = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.cle_idempotence == p['mutation_id'])).mappings().one()
        assert recu['statut'] == 'ok'
        assert '378.91' not in repr(recu) and 'Note FICTIVE' not in repr(recu)
    with session():
        d, v = devis_durable.lire_devis(outils.registre_devis_production(), p['devis_id'])
        assert v is None and d['modele_soumission']['revision'] == 1
        assert str(d['prix_total']) == '1023.06' and d['statut'] == 'brouillon'
    avant = m.base._instantane_base(session)
    assert catalogue.post(ROUTE, data=p, follow_redirects=False).status_code == 303
    assert catalogue.post(ROUTE, data={**p, 'quantite_0': '3'}).status_code == 409
    assert m.base._instantane_base(session) == avant
    documents = {}
    for fmt in ('html', 'pdf'):
        r = catalogue.get(detail + '/document/' + fmt)
        assert r.status_code == 200, r.text[:500]
        assert r.headers['cache-control'] == 'no-store'
        assert 'attachment' in r.headers['content-disposition']
        documents[fmt] = r.content
    texte_pdf = '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(documents['pdf'])).pages)
    assert 'Note FICTIVE, sans valeur légale.' in texte_pdf
    assert 'Clause V2 FICTIVE' not in texte_pdf
    assert '378.91' not in texte_pdf and '378,91' not in texte_pdf and 'taux_marge' not in texte_pdf
    h = documents['html'].decode()
    assert '&lt;script&gt;texte&lt;/script&gt;' in h and '<script>texte</script>' not in h
    assert 'Clause V2 FICTIVE' not in h and '378.91' not in h and p['modele_source'] not in h
    assert m.base._instantane_base(session) == avant  # lectures sans effets
    with session():
        d, v = devis_durable.marquer_devis_accepte(p['devis_id'], 'client.fictif', m.base.H2,
                                                  outils.registre_devis_production())
        assert v is None and d['statut'] == 'accepte'
    apres_acceptation = {fmt: catalogue.get(detail+'/document/'+fmt).content for fmt in ('html', 'pdf')}
    assert m.direct(session, cle='v3', revision_attendue=2, clauses='Clause V3 FICTIVE')['accepte']
    stockage.liberer()
    assert {fmt: catalogue.get(detail+'/document/'+fmt).content for fmt in ('html', 'pdf')} == apres_acceptation
    assert catalogue.get(detail.replace('lead-fictif-001', 'lead-fictif-002')+'/document/html').status_code == 404


@pytest.mark.parametrize('champ,valeur', [('modele_source','0'*64), ('modele_revision','2'),
    ('quantite_0','-1'), ('cout_unitaire_0','NaN'), ('taux_marge','1e99'), ('devis_id','..'),
    ('description_0',''), ('modele_revision','0'), ('description_0','x'*501),
    ('devis_id','a/b'), ('quantite_0','9'*24), ('cout_unitaire_0','9'*24), ('taux_marge','10000')])
def test_refus_source_et_saisie_sans_effet(catalogue, session, champ, valeur):
    p = preparer(catalogue, session)
    avant = m.base._instantane_base(session)
    r = catalogue.post(ROUTE, data={**p, champ: valeur})
    assert r.status_code in {400,404,409}, r.text
    assert m.base._instantane_base(session) == avant


def test_csrf_quota_role_rejeu_et_audit_atomique(catalogue, session, monkeypatch):
    from opsys import etat, identite

    p = preparer(catalogue, session)
    avant = m.base._instantane_base(session)
    assert catalogue.post(ROUTE, data={**p,'csrf':'faux'}).status_code == 403
    assert catalogue.post(ROUTE, data={**p,'clauses':'injection'}).status_code == 400
    assert catalogue.post(ROUTE, content=b'x'*131073,
                          headers={'content-type':'application/x-www-form-urlencoded'}).status_code == 413
    assert direct(session,p,quota=8)['accepte'] is False
    assert direct(session,p,origine='m03-estimation')['accepte'] is False
    assert m.base._instantane_base(session) == avant
    with monkeypatch.context() as mp:
        def panne(*args, **kwargs):
            raise RuntimeError('audit fictif indisponible')
        mp.setattr(etat,'journaliser',panne)
        with pytest.raises(RuntimeError, match='audit fictif'):
            catalogue.post(ROUTE,data=p)
    assert m.base._instantane_base(session) == avant
    assert catalogue.post(ROUTE,data=p,follow_redirects=False).status_code == 303
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = m.base._instantane_base(session)
    assert catalogue.post(ROUTE,data=p).status_code == 403
    assert m.base._instantane_base(session) == avant


def test_double_creation_concurrente_et_intention_reutilisee(catalogue, session):
    from concurrent.futures import ThreadPoolExecutor

    p = preparer(catalogue, session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats=list(pool.map(lambda x: direct(session,x),[p,p]))
    assert all(r['accepte'] for r in resultats),resultats
    with session():
        assert len(list(stockage.maillons('m03-estimation','devis'))) == 1
    avant=m.base._instantane_base(session)
    autre={**p,'devis_id':'autre-fictif'}
    assert direct(session,autre)['accepte'] is False
    assert m.base._instantane_base(session) == avant


def test_ports_generiques_fermes(session):
    from opsys.capacites import Capacites

    cap = Capacites({}, cnx_factory=session)
    for nom in ('m3_creer_devis_depuis_modele', 'm3_document_devis_console'):
        attendu = {'ok': False, 'erreur': 'port_console_prive_requis'}
        assert cap.appeler(nom, {}) == attendu
        assert cap.appeler_profil_runtime(nom, {}, None, None,
                                         profile_id='fictif', profile_revision=1, server='fictif') == attendu


def test_pdf_clauses_longues_utilise_quota_console(catalogue, session):
    import hashlib

    from pypdf import PdfReader

    p = preparer(catalogue, session)
    lignes = [hashlib.sha256(('clause-fictive-'+str(i)).encode()).hexdigest() for i in range(140)]
    r = m.direct(session, cle='clauses-longues', revision_attendue=1, clauses='\n'.join(lignes))
    assert r['accepte']
    p.update(modele_revision='2', modele_source=r['resultat']['source_id'])
    r = catalogue.post(ROUTE, data=p, follow_redirects=False)
    assert r.status_code == 303, r.text
    pdf = catalogue.get(r.headers['location'].removeprefix(m.base.PREFIXE)+'/document/pdf')
    assert pdf.status_code == 200, pdf.text[:200]
    assert len(pdf.content) > 4500
    texte = ''.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert lignes[0] in texte and lignes[-1] in texte
