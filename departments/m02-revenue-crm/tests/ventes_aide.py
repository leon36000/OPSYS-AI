"""Aides partagées des tests « ventes » de M2 (profil de propriété, score, coach, analytique) : une VRAIE base SQLite
migrée, de VRAIES personnes (`opsys.identite`), les VRAIS outils (`outils.outils()`) exécutés par `executer_atomique`
(transaction et validation des arguments d'un appel réel). Aucune donnée réelle (`fictif: true`) : personnes,
courriels `@example.test`, adresses inventées.

Ces fixtures sont additives : aucun test existant ne les utilise.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import yaml
from m2_revenue_crm import outils

from opsys import contexte, stockage
from opsys.outils import executer_atomique

FICTIF = True

M2 = Path(__file__).resolve().parents[1]
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
EMPLOYE = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
ANCIEN = contexte.IdentiteAppelante(personne="ancien.vendeur", role="seller")
H_INGERE = "2026-09-01T09:00:00-04:00"
H_QUALIFIE = "2026-09-01T10:00:00-04:00"
MAINTENANT = "2026-10-15T12:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
SEGMENTS_CONFIGURES = {"jours_inactivite_dormant": 30, "jours_soumission_perimee": 14}
RELANCES_CONFIGUREES = {"jours_entre_relances": 7}
BANDES = [500_000, 1_500_000, 4_000_000]


def contact(nom: str, n: int) -> dict[str, str]:
    return {"nom": nom, "telephone": f"418-555-{n:04d}", "courriel": f"client{n}@example.test"}


class Monde:
    """Un monde fictif prêt à l'emploi : appels d'outils réels, lecture des registres, création de leads."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp_path, self.monkeypatch = tmp_path, monkeypatch
        self.par_nom = {o.nom: o for o in outils.outils()}

    # -- appels
    def appeler(self, nom: str, arguments: dict, identite_appelante=None, *, recu_le: str | None = None) -> dict:
        reception = None
        if recu_le is not None:
            reception = contexte.HorodatageAppareil(
                appareil="tel-fictif",
                horodatage_appareil=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
                recu_le=dt.datetime.fromisoformat(recu_le),
            )
        with contexte.receptionne_de(reception):
            if identite_appelante is None:
                return executer_atomique(self.par_nom[nom], arguments)
            with contexte.appele_par_appareil(identite_appelante):
                return executer_atomique(self.par_nom[nom], arguments)

    @staticmethod
    def accepte(reponse: dict) -> dict:
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
        return reponse["resultat"]["resultat"]

    @staticmethod
    def verdict(reponse: dict) -> dict:
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
        return reponse["resultat"]["verdict"]

    def code(self, reponse: dict) -> str:
        return self.verdict(reponse)["code"]

    # -- registres
    def registre(self, nom: str) -> list:
        with stockage.transaction():
            return list(stockage.maillons("m02-revenue-crm", nom))

    def instantane(self) -> dict:
        """Toutes les tables de la base : pour prouver qu'un refus n'a RIEN écrit."""
        from sqlalchemy import select

        from opsys.stockage.schema import META

        with stockage.transaction() as cnx:
            return {
                nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()
            }

    # -- données
    def lead(
        self,
        lead_id: str,
        owner: str | None,
        contact_: dict,
        *,
        ingere: str = H_INGERE,
        qualifie: str = H_QUALIFIE,
        urgence: bool = False,
        service_champs: dict | None = None,
    ) -> None:
        contrat = {
            "lead_id": lead_id,
            "conversation_id": f"conv-{lead_id}",
            "contact": contact_,
            "type_travaux": "renovation_totale",
            "ville": "Québec",
            "urgence_declaree": urgence,
            "canal": "telephone",
            **(service_champs or {}),
        }
        assert outils.ingerer_lead(contrat, ingere)["accepte"] is True
        if owner is not None:
            reponse = outils.transitionner_statut(lead_id, "qualifie", qualifie, owner=owner, prochaine_action=ACTION)
            assert reponse["accepte"] is True, reponse

    def interaction(self, lead_id: str, resume: str, horodatage: str, auteur: str = "vendeur.un") -> None:
        reponse = outils.enregistrer_interaction(lead_id, auteur, resume, horodatage)
        assert reponse["accepte"] is True, reponse

    def configurer(self, **blocs) -> None:
        reel = yaml.safe_load(outils._MANIFESTE.read_text(encoding="utf-8"))
        manifeste = {
            **reel,
            "configuration": {
                "segments": SEGMENTS_CONFIGURES,
                "relances": RELANCES_CONFIGUREES,
                "scoring": {},
                **blocs,
            },
        }
        chemin = self.tmp_path / "department-m2-ventes.yaml"
        chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.monkeypatch.setattr(outils, "_MANIFESTE", chemin)


def taille(objet) -> int:
    """La taille sérialisée telle que le répartiteur la mesure (limite de sortie de 6 000 caractères)."""
    return len(json.dumps(objet, ensure_ascii=False))
