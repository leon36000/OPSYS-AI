"""Montage de QA de M1 (Léa), M5, M6 et M4 sur le monde des connecteurs courriel (tests seulement).

Vrai socle : base SQLite migrée, bus, sas d'approbation, registres des départements, planificateur ; seuls le RÉSEAU
et les serveurs de courrier sont des doubles. Les verdicts d'authentification des courriels fictifs sont écrits par un
serveur de réception « de confiance » fictif (`mx.fictif.example.test`), déclaré fiable pour le test seulement.
Personnes
fictives."""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

import cablage_qa as cq
import courriel_doubles as dbl
import courriel_qa as qa

from opsys import approbations, evenements, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.courriel_connecteurs import ingestion as ingestion_mod
from opsys.departements import lire_manifeste

SCOPES = qa.SCOPE_GMAIL_LECTURE + " " + qa.SCOPE_GMAIL_ENVOI
SERVEUR_FIABLE = "mx.fictif.example.test"
DOMAINE_ENTREPRISE = "atelier.example.test"
AUTH_OK = f"{SERVEUR_FIABLE}; spf=pass; dkim=pass; dmarc=pass"
AUTH_ECHEC = f"{SERVEUR_FIABLE}; spf=fail; dkim=none; dmarc=fail"
HORO = "2026-11-02T10:00:00-05:00"


@dataclasses.dataclass
class Monde:
    c: cq.Cablage
    n: int = 0

    @property
    def capacites(self) -> Capacites:
        return self.c.capacites

    def appeler(self, nom: str, **arguments: Any) -> dict[str, Any]:
        return self.capacites.appeler(nom, arguments)

    def recevoir(
        self,
        objet: str,
        corps: str,
        de: str = "client.fictif@client.example.test",
        auth: str | None = AUTH_OK,
        pieces: list | None = None,
        nom: str = "Client Fictif",
        date: Any = None,
    ) -> str:
        """Dépose un courriel dans la boîte fictive, fait passer le planificateur et rend le `signal_id` de M1."""
        self.n += 1
        extra = {"Authentication-Results": auth} if auth else None
        self.c.monde.gmail.ajouter(
            dbl.courriel_brut(
                de=de,
                objet=objet,
                corps=corps,
                nom_expediteur=nom,
                extra=extra,
                pieces=pieces,
                date=date,
                message_id=f"<lr{self.n}-{hashlib.sha1((objet + corps).encode()).hexdigest()[:8]}@fictif.example.test>",
            )
        )
        self.c.tour()
        return [x for x in cq.lignes_m1() if x["type_entree"] == "reception_courriel_connecteur_v1"][-1]["signal_id"]

    def repartir(self, passes: int = 3) -> dict[str, int]:
        total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
        for _ in range(passes):
            r = evenements.repartir(self.capacites.departements)
            for k in total:
                total[k] += r.get(k, 0)
        return total

    def decider(self, demande_id: str, approuver: bool = True, par: str = "nathan") -> dict[str, Any]:
        outils = outils_executables(self.capacites.departements, stockage.transaction)
        with stockage.transaction() as cnx:
            return approbations.decider(cnx, demande_id, approuver, par, outils, self.capacites.departements)

    def registre(self, dept: str, nom: str) -> list[dict[str, Any]]:
        with stockage.transaction():
            return list(stockage.maillons(dept, nom))


def monter(
    tmp_path,
    monkeypatch,
    departements: tuple[str, ...] = ("m01-front-office", "m05-financecore", "m06-material-control"),
    lecteur_m4: Any = None,
) -> Monde:
    from m1_front_office import tri_courriel_outils

    mon = cq.monter(tmp_path, monkeypatch, scope_google=SCOPES)
    qa.creer_compte(mon.monde, usage="lecture_envoi", configuration={"reception_m1": 1})
    qa.connecter_oauth(mon.monde)
    brut = ingestion_mod.normaliser
    monkeypatch.setattr(
        ingestion_mod, "normaliser", lambda b, **kw: brut(b, **{**kw, "serveurs_fiables": frozenset({SERVEUR_FIABLE})})
    )
    monkeypatch.setattr(tri_courriel_outils, "domaines_internes", lambda: (DOMAINE_ENTREPRISE,))
    if (
        lecteur_m4 is not None
    ):  # double du port privé de lecture de M4 (la capacité et la cédule), pour les tests de rendez-vous
        monkeypatch.setattr(Capacites, "_lecteur_capacite_m4", staticmethod(lambda *_a: lecteur_m4))
    deps = {d: lire_manifeste(cq.RACINE / "departments" / d) for d in departements}
    mon.capacites = Capacites(deps, stockage.transaction, memoire=False)
    mon.monde.gmail.ajouter(
        dbl.courriel_brut(objet="Historique", corps="Ancien message", message_id="<h0@fictif.example.test>")
    )
    mon.activer("courriel.synchro")
    mon.tour()  # amorçage : l'historique n'entre pas chez M1
    return Monde(mon)
