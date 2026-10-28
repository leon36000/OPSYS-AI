import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from html.parser import HTMLParser
import httpx
from m4_field_ops import cedule, etats, pointage, outbox
from m4_field_ops.registre import Registre
from opsys import stockage
base='http://127.0.0.1:41731'; iid='2f0743e9e6df4f02ecb935f62318784e08ea18b62f6dbdc3f35287de79f7e59e'
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
depart=datetime.fromisoformat(Path(os.environ['QA_CLOCK_FILE']).read_text().strip())-timedelta(minutes=1)
r,f=page(); print('OPERATIONS', [x.get('operation') for x in f.forms]);r=s.post(p,data=form(f,'fermer'),follow_redirects=False,timeout=5);print('FERMER_HTTP',r.status_code);assert r.status_code==303,r.text
r,f=page();print('APRES_FERMETURE', [x.get('operation') for x in f.forms]); report=form(f,'interrompre');report['motif']='meteo';Path(os.environ['QA_CLOCK_FILE']).write_text((depart+timedelta(minutes=2)).isoformat());r=s.post(p,data=report,follow_redirects=False,timeout=5);print('INTERRUPTION_HTTP',r.status_code);assert r.status_code==303,r.text
r,f=page();print('MOTIF_VISIBLE', 'Interruption : meteo' in r.text, 'OPERATIONS',[x.get('operation') for x in f.forms]);assert 'Interruption : meteo' in r.text
with stockage.transaction():
 reg=Registre(stockage.maillons('m04-field-ops','principal'));print('STATUT_FINAL',etats.statut_courant(reg,iid),'WCT',len(outbox.lire_outbox(reg)));assert etats.statut_courant(reg,iid)=='reportee';assert not outbox.lire_outbox(reg)
stockage.liberer()
