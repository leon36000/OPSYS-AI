"""Processus OS distincts de la composition voicemail M1 -> M2 (lancé en sous-processus, jamais collecté).

Chaque rôle est un vrai nouveau processus qui rouvre la même base SQLite par les registres durables canoniques :

- `ecrivain` : STT local réel puis import canonique `Capacites.appeler("m1_importer_appel_manuellement")`. La
  réponse est perdue APRÈS le retour canonique, une fois le commit constaté par une connexion SQLite indépendante
  en lecture seule ; le processus sort alors avec `CODE_PERTE_APRES_COMMIT`.
- `reception` : même parcours sans panne, puis répartition au vrai consommateur M2.
- `reouverture` : relivre exactement le même voicemail (arguments M1 enregistrés), puis répartit au vrai
  consommateur M2.
- `repartition` : seconde répartition seulement.
- `retrait` : relivre le même voicemail avec un consentement courant absent ou refusé.

Le processus parent possède le serveur STT 127.0.0.1 et ne lit la base qu'en lecture seule. Données fictives.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

CODE_PERTE_APRES_COMMIT = 75
CODE_PANNE_AVANT_COMMIT = 76
M1 = "m01-front-office"
M2 = "m02-revenue-crm"
TYPE_LEAD = "m1.lead_qualifie"
MODELE_STT = "whisper-local-fictif"


class PerteReponseApresCommit(RuntimeError):
    """Perte fictive du transport de réponse, levée seulement après le retour canonique de l'import."""


def identite_processus(pid: int | None = None) -> dict[str, int] | None:
    """PID, parent et horloge de démarrage (`/proc/<pid>/stat`), pour ne pas confondre un PID réutilisé."""
    cible = os.getpid() if pid is None else pid
    try:
        donnees = Path(f"/proc/{cible}/stat").read_text(encoding="utf-8")
        champs = donnees[donnees.rindex(")") + 2:].split()
        return {"pid": cible, "parent": int(champs[1]), "start_time": int(champs[19])}
    except (OSError, ValueError, IndexError):
        return None


def lire_temoins(chemin_db: str | Path) -> dict[str, Any]:
    """Faits committés vus par une connexion sqlite3 indépendante, en lecture seule, hors de toute transaction."""
    uri = f"{Path(chemin_db).resolve().as_uri()}?mode=ro"
    cnx = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        if cnx.in_transaction:
            raise RuntimeError("connexion témoin déjà dans une transaction")
        registres = {
            departement: [texte for (texte,) in cnx.execute(
                "SELECT maillon FROM registres_maillons WHERE departement = ? AND registre = 'principal' "
                "ORDER BY rang", (departement,))]
            for departement in (M1, M2)
        }
        sortants = [
            {"evenement_id": ident, "type_evenement": type_, "producteur": producteur, "charge": charge,
             "cree_le": cree_le}
            for ident, type_, producteur, charge, cree_le in cnx.execute(
                "SELECT evenement_id, type_evenement, producteur, charge, cree_le FROM evenements_sortants "
                "ORDER BY cree_le, evenement_id")
        ]
        recus = [
            {"evenement_id": ident, "consommateur": consommateur, "statut": statut, "tentatives": tentatives,
             "resultat": resultat, "derniere_erreur": erreur}
            for ident, consommateur, statut, tentatives, resultat, erreur in cnx.execute(
                "SELECT evenement_id, consommateur, statut, tentatives, resultat, derniere_erreur "
                "FROM evenements_recus ORDER BY evenement_id, consommateur")
        ]
    finally:
        cnx.close()
    return {"registres": registres, "sortants": sortants, "recus": recus}


def faits_m1_committes(temoins: dict[str, Any], metadonnees: dict[str, str], lead_id: str | None) -> dict[str, int]:
    """Comptes minimaux qui décident si la panne est postcommit ; l'oracle complet reste dans le test."""
    from opsys.stockage import codec

    lignes = [codec.decoder(texte) for texte in temoins["registres"][M1]]
    return {
        "appel_importe": sum(
            1 for ligne in lignes if ligne.get("type_entree") == "appel_importe"
            and ligne.get("source") == metadonnees["source"] and ligne.get("appel_id") == metadonnees["appel_id"]
            and ligne.get("evenement_id") == metadonnees["evenement_id"]
        ),
        "lead_emis": sum(
            1 for ligne in lignes if ligne.get("type_entree") == "lead_emis"
            and isinstance(ligne.get("lead"), dict) and ligne["lead"].get("lead_id") == lead_id
        ),
        "outbox": sum(
            1 for sortant in temoins["sortants"] if sortant["type_evenement"] == TYPE_LEAD
            and sortant["evenement_id"] == f"m1-lead-qualifie-{lead_id}"
        ),
    }


def _valider_chaines() -> dict[str, Any]:
    from m1_front_office import outils as outils_m1
    from m2_revenue_crm import outils as outils_m2

    from opsys import stockage

    with stockage.transaction():
        m1 = outils_m1._obtenir_registre().valider_chaine()
        m2 = outils_m2._obtenir_registre().valider_chaine()
    return {"m1": list(m1) if isinstance(m1, tuple) else m1, "m2": m2}


def executer(role: str, config: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from m1_front_office import outils as outils_m1
    from m1_front_office import voicemail_stt
    from m2_revenue_crm import outils as outils_m2

    from opsys import evenements, stockage
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements

    chemin_db = config["base"]
    metadonnees = config["metadonnees"]
    audio = Path(config["audio"]).read_bytes()
    rapport: dict[str, Any] = {
        "role": role, "identite": identite_processus(), "sha256_audio": hashlib.sha256(audio).hexdigest(),
        "metadonnees": metadonnees,
    }
    outils_m1.utiliser_stockage_durable()
    outils_m2.utiliser_stockage_durable()
    deps = charger_departements()
    capacites = Capacites({M1: deps[M1]}, stockage.transaction, memoire=False)
    configuration = voicemail_stt.ConfigurationSTT(base_url=config["stt_url"], modele=MODELE_STT, local=True)
    consentement = config.get("consentement", "accorde")

    def transcrire(importeur=None) -> dict[str, Any]:
        return voicemail_stt.transcrire_et_importer(
            audio, suffixe=".wav", capacites=capacites, configuration=configuration,
            consentement_enregistrement=consentement, importeur=importeur, **metadonnees,
        )

    def repartir() -> dict[str, int]:
        return evenements.repartir({M2: deps[M2]}, maintenant=config["maintenant"])

    try:
        if role == "ecrivain":
            capture: dict[str, Any] = {}

            def importeur_perdant_la_reponse(arguments):
                # Seam public : délègue au vrai appel canonique, puis perd seulement la réponse déjà rendue.
                capture["transaction_englobante"] = stockage.connexion_courante() is not None
                capture["arguments"] = dict(arguments)
                reponse = capacites.appeler("m1_importer_appel_manuellement", arguments)
                capture["reponse"] = reponse
                capture["temoins"] = lire_temoins(chemin_db)
                raise PerteReponseApresCommit("réponse d'import perdue après retour canonique (fictif)")

            try:
                rapport["resultat_inattendu"] = transcrire(importeur_perdant_la_reponse)
                return 1, rapport
            except PerteReponseApresCommit:
                rapport.update(capture)
            reponse = capture["reponse"]
            traitement = reponse.get("resultat", {}).get("traitement", {}) if reponse.get("ok") else {}
            lead_id = None
            if traitement.get("decision") == "TRANSMETTRE_M2":
                lead_id = traitement.get("lead", {}).get("lead_id")
            rapport["faits_committes"] = faits_m1_committes(capture["temoins"], metadonnees, lead_id)
            postcommit = lead_id is not None and set(rapport["faits_committes"].values()) == {1}
            return (CODE_PERTE_APRES_COMMIT if postcommit else CODE_PANNE_AVANT_COMMIT), rapport
        if role == "reception":
            rapport["resultat"] = transcrire()
            rapport["repartition"] = repartir()
        elif role == "reouverture":
            arguments_relivres: list[dict[str, Any]] = []

            def importeur_canonique(arguments):
                # Seam transparent : enregistre la relivraison exacte et rend la vraie réponse canonique.
                arguments_relivres.append(dict(arguments))
                return capacites.appeler("m1_importer_appel_manuellement", arguments)

            rapport["resultat"] = transcrire(importeur_canonique)
            rapport["arguments"] = arguments_relivres
            rapport["repartition"] = repartir()
            rapport["chaines"] = _valider_chaines()
        elif role == "repartition":
            rapport["repartition"] = repartir()
            rapport["chaines"] = _valider_chaines()
        elif role == "retrait":
            rapport["resultat"] = transcrire()
            rapport["repartition"] = repartir()
            rapport["chaines"] = _valider_chaines()
        else:
            raise ValueError(f"rôle inconnu : {role}")
        return 0, rapport
    finally:
        stockage.liberer()


def main(argv: list[str]) -> int:
    role, chemin_config = argv
    code, rapport = executer(role, json.loads(Path(chemin_config).read_text(encoding="utf-8")))
    rapport["fin"] = True
    sys.stdout.write(json.dumps(rapport, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
