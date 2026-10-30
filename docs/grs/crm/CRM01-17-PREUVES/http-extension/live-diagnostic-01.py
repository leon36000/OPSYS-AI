exec(open('/tmp/opsys-m4-http-suite-kepXNO/live-diagnostic-base-01.py').read().split('with stockage.transaction():')[0])
u=base+'/crm/visites/reprise?intervention_id='+iid
r=s.get(u,timeout=5);print('OUVERTURE_PAGE_REPRISE',r.status_code);print('CONTENU',r.text[:400]);
from html.parser import HTMLParser
class Extra(HTMLParser):
 def __init__(self): super().__init__();self.forms=[];self.f=None;self.options=[]
 def handle_starttag(self,t,a):
  a=dict(a)
  if t=='form': self.f={};self.forms.append(self.f)
  elif t=='input' and self.f is not None and a.get('name'): self.f[a['name']]=a.get('value','')
  elif t=='option':self.options.append(a.get('value'))
 def handle_endtag(self,t):
  if t=='form':self.f=None
f=Extra();f.feed(r.text);print('CHOIX',f.options,'FORMES',[list(x) for x in f.forms]);assert r.status_code==200
form=next(x for x in f.forms if 'empreinte_attendue' in x);assert f.options
form.update(equipe_id=next((x for x in f.options if x!='eq-a'),f.options[0]),debut='08:00',fin='16:00');r=s.post(u,data=form,follow_redirects=False,timeout=10);print('PROPOSITION',r.status_code,r.headers.get('location'));print('DETAIL',r.text[:300]);assert r.status_code==303
loc=r.headers['location'];r=s.get(base+loc,timeout=5);print('REVUE',r.status_code,'N3', 'Confirmer l’affectation interne N3' in r.text);assert r.status_code==200
f=Extra();f.feed(r.text);apply=next(x for x in f.forms if 'empreinte_attendue' in x);r=s.post(base+loc,data=apply,follow_redirects=False,timeout=10);print('APPROBATION_N3',r.status_code,r.headers.get('location'));assert r.status_code==303
