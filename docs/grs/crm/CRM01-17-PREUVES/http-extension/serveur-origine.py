"""Serveur fictif local : aucune donnée client réelle, aucune connexion sortante."""
import contextlib
import importlib.util
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from opsys import contexte, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.outils import executer_atomique
from m4_field_ops.outils import outils

root = Path.cwd()
spec = importlib.util.spec_from_file_location('qa_terrain_fictif', root / 'departments/m04-field-ops/tests/test_cedule_tournees_outils.py')
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
now = datetime.now(UTC)
t.HORODATAGE = (now - timedelta(days=1)).isoformat()
t.MARQUEUR = {**t.MARQUEUR, 'horodatage': t.HORODATAGE}
recue = now - timedelta(minutes=10)
def appeler(par_nom, nom, arguments, identite_appelante=None):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
            pile.enter_context(contexte.receptionne_de(contexte.HorodatageAppareil('qa-fictif', recue, recue)))
        return executer_atomique(par_nom[nom], arguments)
t._appeler = appeler
stockage.migrer()
with stockage.transaction() as cnx:
    identite.creer_personne(cnx, 'admin.fictif', 'Admin Fictive', 'mot-de-passe-qa-fictif-1234', ['admin'])
par = {o.nom: o for o in outils()}
lead = t.SCENARIO['leads'][0]
iid = t._inscrire(par, lead, t.HORODATAGE)
t._resultat(t._confirmer(par, lead))
plan = t._resultat(t._proposer(par, {lead['lead_id']: iid}))['plan_id']
t._resultat(t._appliquer(par, plan))
jour = now.astimezone(ZoneInfo('America/Montreal')).date().isoformat()
t._resultat(t._appeler(par, 'm4_confirmer_dates_cedule', {'plan_id': plan, 'calendrier': {'0': jour},
                                                            'revision_attendue': 0}, t.ADMIN))
app = application.creer_application(Configuration('secret-qa-fictif-' + 'x' * 40, cookie_securise=False, prefixe=''))
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('127.0.0.1', 0))
sock.listen(32)
print('QA_PORT=' + str(sock.getsockname()[1]), flush=True)
print('QA_INTERVENTION=' + iid, flush=True)
print('QA_JOUR=' + jour, flush=True)
try:
    uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False)).run(sockets=[sock])
finally:
    sock.close()
    stockage.liberer()
    print('QA_SERVEUR_FERME', flush=True)
