"""QA fictive : relecture du chantier terminé ; serveur local sans accès sortant."""
import socket
import uvicorn
from opsys import stockage
from opsys.console import application
from opsys.console.securite import Configuration

app = application.creer_application(Configuration(
    'secret-qa-fictif-' + 'x' * 40, cookie_securise=False, prefixe='', duree_session=315360000))
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('127.0.0.1', 0))
sock.listen(32)
print('QA_PORT=' + str(sock.getsockname()[1]), flush=True)
try:
    uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False)).run(sockets=[sock])
finally:
    sock.close()
    stockage.liberer()
