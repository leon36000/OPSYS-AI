"""Console privée pour la base QA fictive déjà construite, loopback seulement."""
import json
import os
import socket
from pathlib import Path
import uvicorn
from opsys import stockage
from opsys.console import application
from opsys.console.securite import Configuration

app = application.creer_application(Configuration('secret-qa-fictif-' + 'x' * 40, cookie_securise=False, prefixe=''))
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
    print('QA_SERVEUR_FERME', flush=True)
