exec(open('/tmp/opsys-m4-http-suite-kepXNO/live-correctif-base-01.py').read().split('with stockage.transaction():')[0])
from datetime import timedelta
plan='e5972a185fd9b08d877d11b74487c57a1c545794c5225b4a89f14fcf5f3e8b0c'; u=base+'/crm/cedule/plan/'+plan
r=s.get(u,timeout=5); print('DATES_PAGE',r.status_code); f=Forms();f.feed(r.text);print('DATES_FORMES',[list(x) for x in f.forms]);form=next(x for x in f.forms if 'revision_attendue' in x);form['date_0']='2026-10-30';r=s.post(u,data=form,follow_redirects=False,timeout=10);print('CONFIRMATION_DATE',r.status_code,r.headers.get('location'));assert r.status_code==303,r.text
Path(os.environ['QA_CLOCK_FILE']).write_text('2026-10-30T12:00:00+00:00');r,f=page();print('APRES_DATE',r.status_code,'OPERATIONS',[x.get('operation') for x in f.forms]);
prevoir=form(f,'prevoir');r=s.post(p,data=prevoir,follow_redirects=False,timeout=5);print('PREVOIR_REPRISE',r.status_code);assert r.status_code==303,r.text
r,f=page();ouvrir=form(f,'ouvrir');r=s.post(p,data=ouvrir,follow_redirects=False,timeout=5);print('OUVRIR_REPRISE',r.status_code);assert r.status_code==303,r.text
with stockage.transaction():
 reg=Registre(stockage.maillons('m04-field-ops','principal'));equipe=etats.technicien_assigne(reg,iid);print('EQUIPE_REPRISE',equipe);assert equipe=='eq-b';assign={'intervention_id':iid,'technicien_id':equipe};t=datetime(2026,10,30,12,1,tzinfo=UTC);rec,err=etats.transitionner(iid,'en_route',reg,t.isoformat(),assignation=assign);assert err is None,err
 ref={cedule.tokeniser_ville('sel-fictif','Laval'):{'latitude':45.59,'longitude':-73.74,'rayon_km':25.0}};fenetre={'debut':'2026-10-30T12:00:00+00:00','fin':'2026-10-30T21:00:00+00:00'}
 for action,instant in [('arrivee',t+timedelta(minutes=1)),('depart',t+timedelta(minutes=61))]:
  rec,err=pointage.enregistrer_pointage(iid,equipe,action,instant.isoformat(),{'latitude':45.59,'longitude':-73.74},{'fictif':True,'appareil_id':'qa-fictif'},assign,fenetre,ref,'Laval','sel-fictif',reg);assert err is None,err
 print('PRIMITIVES', 'transition en_route et pointages reprise arrivée/départ')
Path(os.environ['QA_CLOCK_FILE']).write_text('2026-10-30T13:03:00+00:00');r,f=page();fermer=form(f,'fermer');r=s.post(p,data=fermer,follow_redirects=False,timeout=5);print('FERMER_REPRISE',r.status_code);assert r.status_code==303,r.text
r,f=page();print('DEUX_DUREES_60',r.text.count('Pointé : 60 min nettes'));assert r.text.count('Pointé : 60 min nettes')==2
