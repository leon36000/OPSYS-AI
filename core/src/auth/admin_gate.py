#!/usr/bin/env python3
"""AdminGate — garde d'admission MFA/TOTP avec anti-brute-force et anti-replay."""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Any, Dict, List, Set

import totp

logger = logging.getLogger("admin_gate")


class AdminGate:
    """Gere la verification TOTP pour l'acces admin avec protections.
    - secret lu depuis l'environnement a chaque tentative (jamais stocke / logge).
    - anti-brute force par IP (max_echecs, verrou_s).
    - anti-replay par hash du secret + timesteps consommes.
    - fail-closed : si secret absent -> 'mfa_non_configure'.
    - thread-safe : un verrou unique pour tout l'etat mutable.
    - SINGLE-PROCESS : l'etat rate-limit et anti-replay est en memoire process ;
      non partage multi-process ; un deploiement multi-worker exigerait un backend
      partage (Redis/sqlite verrouille) — hors perimetre P0-5b, a traiter avant
      tout scale horizontal.
    """

    def __init__(
        self,
        secret_env: str = "OPSYS_ADMIN_TOTP_SECRET",  # nosec: B107 # nom de variable d'environnement à lire, jamais un secret littéral
        max_echecs: int = 5,
        verrou_s: int = 300,
    ) -> None:
        self.secret_env = secret_env
        self.max_echecs = max_echecs
        self.verrou_s = verrou_s
        self._lock = threading.Lock()
        self._replay_state: Dict[bytes, Set[int]] = {}
        self._failure_tracker: Dict[str, List[float]] = {}

    def est_configure(self) -> bool:
        """Retourne True si le secret MFA est present dans l'environnement.
        Lecture seule : aucun etat mutable n'est modifie, aucun log n'est ecrit.
        """
        return bool(os.environ.get(self.secret_env))

    def _purge_expired_failures(self, now: float) -> None:
        """Supprime les entrees de rate-limit dont la fenetre est expiree."""
        cutoff = now - self.verrou_s
        new_tracker: Dict[str, List[float]] = {}
        for ip_addr, timestamps in self._failure_tracker.items():
            kept = [t for t in timestamps if t > cutoff]
            if kept:
                new_tracker[ip_addr] = kept
        self._failure_tracker = new_tracker

    def verifier(self, code: str, ip: str) -> Dict[str, Any]:
        """Verifie un code TOTP pour l'IP donnee.
        Retourne {"autorise": bool, "raison": str}.
        """
        secret_b32 = os.environ.get(self.secret_env)
        if not secret_b32:
            logger.warning("MFA non configurée (secret absent)")
            return {"autorise": False, "raison": "mfa_non_configure"}

        now = time.monotonic()
        with self._lock:
            self._purge_expired_failures(now)

            failures = self._failure_tracker.setdefault(ip, [])
            if len(failures) >= self.max_echecs:
                logger.warning("IP %s verrouillée (trop d'échecs TOTP)", ip)
                return {"autorise": False, "raison": "verrouille"}

            try:
                secret_hash = hashlib.sha256(secret_b32.encode()).digest()
            except Exception:
                logger.error("Erreur lors du hash du secret")
                return {"autorise": False, "raison": "erreur_interne"}

            self._replay_state = {secret_hash: self._replay_state.get(secret_hash, set())}

            try:
                ok, timestep = totp.verify_totp(secret_b32, code, window=1)
            except Exception:
                logger.exception("Exception dans verify_totp")
                ok, timestep = False, None

            if not ok:
                failures.append(now)
                logger.info("Échec de vérification TOTP pour IP %s", ip)
                return {"autorise": False, "raison": "invalide"}

            if timestep is None:
                logger.error("verify_totp a autorisé un code sans timestep pour IP %s", ip)
                return {"autorise": False, "raison": "erreur_interne"}

            if timestep in self._replay_state[secret_hash]:
                logger.warning("Tentative de rejeu TOTP pour IP %s", ip)
                return {"autorise": False, "raison": "rejoue"}

            self._replay_state[secret_hash].add(timestep)
            if ip in self._failure_tracker:
                del self._failure_tracker[ip]
            logger.info("Vérification TOTP réussie pour IP %s", ip)
            return {"autorise": True, "raison": "ok"}
