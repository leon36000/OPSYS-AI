import os,socket,uvicorn
from datetime import datetime,UTC
from pathlib import Path
from opsys import stockage
from opsys.console import application, metier, reprise_visite
from opsys.console.securite import Configuration
class HorlogeFictive(datetime):
 @classmethod
 def now(cls,tz=None):
  return datetime.fromisoformat(Path(os.environ['QA_CLOCK_FILE']).read_text().strip()).astimezone(tz)
metier.datetime=HorlogeFictive
reprise_visite.datetime=HorlogeFictive
original = reprise_visite.executer_atomique
def tracer(outil, args):
 import json
 r=original(outil,args)
 print("QA_OUTIL_RESULTAT="+json.dumps(r,ensure_ascii=False,default=str),flush=True)
 return r
reprise_visite.executer_atomique=tracer
app=application.creer_application(Configuration('secret-qa-fictif-'+'x'*40,cookie_securise=False,prefixe='',duree_session=315360000))
sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM);sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('127.0.0.1',0));sock.listen(32)
print('QA_PORT='+str(sock.getsockname()[1]),flush=True)
try:uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False)).run(sockets=[sock])
finally:sock.close();stockage.liberer();print('QA_SERVEUR_FERME',flush=True)
