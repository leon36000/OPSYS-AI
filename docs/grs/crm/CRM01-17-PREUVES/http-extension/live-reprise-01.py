import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from html.parser import HTMLParser
import httpx
from m4_field_ops import cedule, etats, pointage, outbox
from m4_field_ops.registre import Registre
from opsys import stockage
base='http://127.0.0.1:39817'; iid='2f0743e9e6df4f02ecb935f62318784e08ea18b62f6dbdc3f35287de79f7e59e'
s=httpx.Client(trust_env=False);r=s.post(base+'/connexion',data={'identifiant':'admin.fictif','mot_de_passe':'mot-de-passe-qa-fictif-1234'},follow_redirects=False,timeout=5);assert r.status_code==303
p=base+'/crm/visites?intervention_id='+iid
class Forms(HTMLParser):
 def __init__(self):super().__init__();self.forms=[];self.f=None
 def handle_starttag(self,t,a):
  a=dict(a)
  if t=='form':self.f={};self.forms.append(self.f)
  elif t=='input' and self.f is not None and 'name' in a:self.f[a['name']]=a.get('value','')
 def handle_endtag(self,t):
  if t=='form':self.f=None
def page():
 r=s.get(p,timeout=5);assert r.status_code==200;f=Forms();f.feed(r.text);return r,f
def form(f,op):return next(x for x in f.forms if x.get('operation')==op)
with stockage.transaction():
 reg=Registre(stockage.maillons('m04-field-ops','principal')); equipe=etats.technicien_assigne(reg,iid); print('EQUIPE_PREVUE',equipe);print('STATUT_INITIAL',etats.statut_courant(reg,iid));assert etats.statut_courant(reg,iid)=='planifiee'
 now=datetime.now(UTC)+timedelta(seconds=5); depart=now+timedelta(minutes=60); assign={'intervention_id':iid,'technicien_id':equipe}
 recu,err=etats.transitionner(iid,'en_route',reg,now.isoformat(),assignation=assign);assert err is None,err
 ref={cedule.tokeniser_ville('sel-fictif','Laval'):{'latitude':45.59,'longitude':-73.74,'rayon_km':25.0}};fenetre={'debut':(now-timedelta(hours=1)).isoformat(),'fin':(depart+timedelta(hours=1)).isoformat()}
 for action,instant in [('arrivee',now+timedelta(seconds=1)),('depart',depart)]:
  recu,err=pointage.enregistrer_pointage(iid,equipe,action,instant.isoformat(),{'latitude':45.59,'longitude':-73.74},{'fictif':True,'appareil_id':'qa-fictif'},assign,fenetre,ref,'Laval','sel-fictif',reg);assert err is None,err
 print('PRIMITIVES_FICTIVES', 'transition en_route et 2 pointages arrivée/départ')
Path(os.environ['QA_CLOCK_FILE']).write_text((depart+timedelta(minutes=1)).isoformat())
r,f=page(); print('OPERATIONS', [x.get('operation') for x in f.forms]);r=s.post(p,data=form(f,'fermer'),follow_redirects=False,timeout=5);print('FERMER_HTTP',r.status_code);assert r.status_code==303,r.text
r,f=page();print('APRES_FERMETURE', [x.get('operation') for x in f.forms]); report=form(f,'interrompre');report['motif']='meteo';Path(os.environ['QA_CLOCK_FILE']).write_text((depart+timedelta(minutes=2)).isoformat());r=s.post(p,data=report,follow_redirects=False,timeout=5);print('INTERRUPTION_HTTP',r.status_code);assert r.status_code==303,r.text
r,f=page();print('MOTIF_VISIBLE', 'Interruption : meteo' in r.text, 'OPERATIONS',[x.get('operation') for x in f.forms]);assert 'Interruption : meteo' in r.text
with stockage.transaction():
 reg=Registre(stockage.maillons('m04-field-ops','principal'));print('STATUT_FINAL',etats.statut_courant(reg,iid),'WCT',len(outbox.lire_outbox(reg)));assert etats.statut_courant(reg,iid)=='reportee';assert not outbox.lire_outbox(reg)
stockage.liberer()
