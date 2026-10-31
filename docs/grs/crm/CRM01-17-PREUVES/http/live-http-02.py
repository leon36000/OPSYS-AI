import httpx
from html.parser import HTMLParser
base='http://127.0.0.1:46291'
iid='2f0743e9e6df4f02ecb935f62318784e08ea18b62f6dbdc3f35287de79f7e59e'
s=httpx.Client(trust_env=False)
r=s.get(base+'/crm/visites',params={'intervention_id':iid},allow_redirects=False,timeout=5); print('ANONYME',r.status_code,r.headers.get('location')); assert r.status_code==303
r=s.post(base+'/connexion',data={'identifiant':'admin.fictif','mot_de_passe':'mot-de-passe-qa-fictif-1234'},allow_redirects=False,timeout=5); print('CONNEXION',r.status_code,r.headers.get('location')); assert r.status_code==303
p=base+'/crm/visites?intervention_id='+iid
r=s.get(p,timeout=5); print('VISITES',r.status_code, 'Prévisions et visites' in r.text, 'Composition' in r.text); assert r.status_code==200
class Forms(HTMLParser):
 def __init__(self): super().__init__(); self.forms=[]; self.f=None
 def handle_starttag(self,t,a):
  a=dict(a)
  if t=='form': self.f={'_action':a.get('action','')};self.forms.append(self.f)
  elif t=='input' and self.f is not None and 'name' in a:self.f[a['name']]=a.get('value','')
 def handle_endtag(self,t):
  if t=='form':self.f=None
f=Forms();f.feed(r.text); print('OPERATIONS',[(x.get('operation'),x.get('_action')) for x in f.forms]); form=next(x for x in f.forms if x.get('operation')=='prevoir');form.pop('_action'); bad=dict(form,csrf='csrf-fictif-invalide');r=s.post(p,data=bad,allow_redirects=False,timeout=5);print('CSRF_INVALIDE',r.status_code);assert r.status_code==403
r=s.post(p,data=form,allow_redirects=False,timeout=5);print('PREVOIR',r.status_code);assert r.status_code==303
r=s.get(p,timeout=5); f=Forms();f.feed(r.text); print('APRES_PREVISION',r.status_code, 'Composition déclarée inconnue' in r.text,[(x.get('operation'),x.get('_action')) for x in f.forms]);assert r.status_code==200
form=next(x for x in f.forms if x.get('operation')=='ouvrir');form.pop('_action');r=s.post(p,data=form,allow_redirects=False,timeout=5);print('OUVRIR',r.status_code);assert r.status_code==303
r=s.get(p,timeout=5);f=Forms();f.feed(r.text);print('APRES_OUVERTURE',r.status_code,'Temps pointé : inconnu' in r.text,[(x.get('operation'),x.get('_action')) for x in f.forms]);assert r.status_code==200
