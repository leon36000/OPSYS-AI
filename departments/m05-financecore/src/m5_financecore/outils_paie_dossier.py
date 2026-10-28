"""Outils M5 du dossier de paie préparatoire : propriétaire console uniquement, aucune capacité appareil ni agent.

Chaque outil exige le propriétaire confirmé en base ET l'origine console (même garde que `m5_preparer_brut_regulier`,
seule origine autorisée par le port M4). `roles_appareil` est vide : un nouvel outil dans ce manifeste ne confère
aucun grant Core ni accès MCP ; l'ouverture d'un accès agent reste un raccord séparé du coordinateur.

Un refus lève `DossierErreur` (sous-classe de ValueError) : le socle annule alors TOUTE la transaction de l'appel,
donc un refus tardif ne laisse aucune écriture partielle. Le verdict (`REJ-DOSSIER-PAIE-*`) voyage en JSON
dans `details`.
Les commandes ne rendent que des reçus sans montant (l'idempotence partagée les conserve en clair) ; les
montants ne sont rendus que par les lectures, jamais persistés hors du journal chiffré.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Connection

from opsys import identite, stockage
from opsys.outils import Autonomie, Outil

from . import analyse
from . import dossier_paie_preparatoire as dossier
from . import export_paie_preparatoire as export
from . import journal_dossiers_paie as journal
from . import service_dossier_paie as service

_HEX_32 = {"type": "string", "pattern": "^[a-f0-9]{32}$"}
_HEX_64 = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
_ID_PERSONNE = {"type": "string", "minLength": 1, "maxLength": 128}
_NOTE = {"type": "string", "maxLength": journal.MAX_NOTE}
_HORODATAGE = {
    "type": "string",
    "description": "Créé par le serveur (la console l'injecte); jamais fourni par un humain.",
}


def _schema(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False}


def _decrire(texte: str) -> str:
    return (
        texte
        + " Réservé au propriétaire confirmé via console. Préparatoire : aucun salaire versé, aucune remise, aucun "
        "document fiscal officiel, aucune écriture au grand livre, aux factures, aux obligations ni à M4."
    )


def construire_outils(
    *,
    proprietaire: Callable[[], tuple[str | None, dict[str, Any] | None]],
    fournisseur_brut: service.FournisseurBrut,
    fournisseur_admission: service.FournisseurAdmission,
    employe_actif: Callable[[str], bool],
    liens_officiels: tuple[Mapping[str, Any], ...],
) -> tuple[Outil, ...]:
    def acteur() -> tuple[Connection, str]:
        """Propriétaire console confirmé + transaction courante; sinon refus (donc annulation de l'appel)."""
        personne, refus = proprietaire()
        cnx = stockage.connexion_courante()
        if refus is not None or personne is None or cnx is None:
            raise dossier.DossierErreur(refus or dossier.refus("ACCES-REFUSE", "propriétaire console confirmé requis"))
        return cnx, personne

    def verifier_acteur(cnx: Connection, identifiant: str) -> None:
        vivant = identite.personne_active(cnx, identifiant)
        if vivant is None or "nathan_owner" not in vivant.roles:
            raise dossier.DossierErreur(dossier.refus("ACCES-REFUSE", "autorité du propriétaire retirée"))

    def exiger_employe(employee_person_id: str) -> None:
        if not employe_actif(employee_person_id):
            raise dossier.DossierErreur(
                dossier.refus("ACCES-REFUSE", "la cible doit être une personne OPSYS employee active")
            )

    def apercu(employee_person_id: str, entrees: dict[str, Any]) -> dict[str, Any]:
        cnx, _ = acteur()
        exiger_employe(employee_person_id)
        resultat = service.apercu(
            cnx,
            employee_person_id=employee_person_id,
            entrees_brutes=entrees,
            fournisseur_brut=fournisseur_brut,
            fournisseur_admission=fournisseur_admission,
        )
        return {"accepte": True, "resultat": analyse.avec_mention(resultat)}

    def conserver(
        employee_person_id: str,
        entrees: dict[str, Any],
        empreinte_apercu: str,
        version_attendue: int,
        type_version: str,
        motif: str,
        mutation_id: str,
        horodatage: str,
    ) -> dict[str, Any]:
        cnx, personne = acteur()
        exiger_employe(employee_person_id)
        recu = service.conserver_version(
            cnx,
            acteur=personne,
            employee_person_id=employee_person_id,
            entrees_brutes=entrees,
            empreinte_apercu=empreinte_apercu,
            version_attendue=version_attendue,
            type_version=type_version,
            motif=motif,
            mutation_id=mutation_id,
            maintenant=horodatage,
            fournisseur_brut=fournisseur_brut,
            fournisseur_admission=fournisseur_admission,
            verifier_acteur=verifier_acteur,
        )
        return {"accepte": True, "resultat": recu}

    def rouvrir(
        dossier_id: str,
        numero: int,
        hash_version: str,
        motif: str,
        mutation_id: str,
        horodatage: str,
    ) -> dict[str, Any]:
        cnx, personne = acteur()
        recu = service.rouvrir(
            cnx,
            acteur=personne,
            dossier_id=dossier_id,
            numero=numero,
            hash_version=hash_version,
            motif=motif,
            mutation_id=mutation_id,
            maintenant=horodatage,
            verifier_acteur=verifier_acteur,
        )
        return {"accepte": True, "resultat": recu}

    def revue(
        dossier_id: str,
        numero: int,
        hash_version: str,
        decision: str,
        note: str,
        mutation_id: str,
        horodatage: str,
    ) -> dict[str, Any]:
        cnx, personne = acteur()
        recu = service.revue(
            cnx,
            acteur=personne,
            dossier_id=dossier_id,
            numero=numero,
            hash_version=hash_version,
            decision=decision,
            note=note,
            mutation_id=mutation_id,
            maintenant=horodatage,
            fournisseur_brut=fournisseur_brut,
            fournisseur_admission=fournisseur_admission,
            verifier_acteur=verifier_acteur,
        )
        return {"accepte": True, "resultat": recu}

    def exporter(
        dossier_id: str,
        numero: int,
        hash_version: str,
        format_export: str,
        mutation_id: str,
        horodatage: str,
    ) -> dict[str, Any]:
        cnx, personne = acteur()
        recu = service.exporter(
            cnx,
            acteur=personne,
            dossier_id=dossier_id,
            numero=numero,
            hash_version=hash_version,
            format_export=format_export,
            mutation_id=mutation_id,
            maintenant=horodatage,
            liens_officiels=liens_officiels,
            fournisseur_brut=fournisseur_brut,
            fournisseur_admission=fournisseur_admission,
            verifier_acteur=verifier_acteur,
        )
        return {"accepte": True, "resultat": recu}

    def lire(dossier_id: str | None, numero: int | None, comparer_a: int | None) -> dict[str, Any]:
        cnx, _ = acteur()
        if dossier_id is None:
            return {"accepte": True, "resultat": analyse.avec_mention({"dossiers": service.lister(cnx)})}
        d = journal.lire_dossier(cnx, dossier_id)
        if d is None or not d["versions"]:
            raise dossier.DossierErreur(dossier.refus("INTROUVABLE", "dossier introuvable"))
        version = service.version_numero(d, numero)
        resume_versions = [
            {
                "numero": v["numero"],
                "hash_version": v["hash_version"],
                "type_version": v["type_version"],
                "motif": v["motif"],
                "acteur": v["acteur"],
                "horodatage": v["horodatage"],
                "etat_calcul": v["version"]["calcul"]["etat"],
                "net_preparatoire": v["version"]["calcul"]["totaux"]["net_preparatoire"]["montant"],
            }
            for v in d["versions"]
        ]
        resultat = {
            "dossier": {
                "dossier_id": d["dossier_id"],
                "etat": d["etat"],
                "versions": resume_versions,
                "revues": d["revues"],
                "reouvertures": d["reouvertures"],
                "exports": d["exports"],
            },
            "version": {"numero": version["numero"], "hash_version": version["hash_version"], **version["version"]},
            "comparaison": None if comparer_a is None else service.comparer(d, comparer_a, version["numero"]),
        }
        return {"accepte": True, "resultat": analyse.avec_mention(resultat)}

    def verifier(dossier_id: str, numero: int | None) -> dict[str, Any]:
        cnx, _ = acteur()
        resultat = service.verifier_version(
            cnx,
            dossier_id=dossier_id,
            numero=numero,
            fournisseur_brut=fournisseur_brut,
            fournisseur_admission=fournisseur_admission,
        )
        return {"accepte": True, "resultat": resultat}

    def lire_export(dossier_id: str, numero: int, hash_version: str, format_export: str) -> dict[str, Any]:
        cnx, _ = acteur()
        octets, empreinte = service.lire_export(
            cnx,
            dossier_id=dossier_id,
            numero=numero,
            hash_version=hash_version,
            format_export=format_export,
            liens_officiels=liens_officiels,
        )
        return {
            "accepte": True,
            "resultat": {
                "format": format_export,
                "type_mime": export.TYPES_MIME[format_export],
                "empreinte_sha256": empreinte,
                "contenu": octets.decode("utf-8"),
            },
        }

    entrees_schema = {
        "type": "object",
        "description": "Déclarations humaines du dossier (schéma opsys.dossier-paie-entrees/v1).",
    }
    return (
        Outil(
            nom="m5_apercu_dossier_paie",
            description=_decrire(
                "Aperçu en lecture seule : lit les heures M4 et le taux M5 par les ports existants, "
                "vérifie l'admission "
                "documentaire serveur, appelle les moteurs RRQ, impôt QC, RQAP/AE et fédéral, "
                "ajoute les postes employeur "
                "sourcés, et rend la matrice des postes avec ce qui manque. Rien n'est conservé."
            ),
            parametres=_schema(
                {"employee_person_id": _ID_PERSONNE, "entrees": entrees_schema}, ["employee_person_id", "entrees"]
            ),
            fonction=apercu,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_conserver_version_dossier_paie",
            description=_decrire(
                "Conserve une version immuable et chiffrée du dossier (création, correction ou rebase) "
                "si l'empreinte de "
                "l'aperçu vu est encore exacte et que la version attendue est courante. Rejeu exact : même reçu. "
                "Ne rend qu'un reçu sans montant."
            ),
            parametres=_schema(
                {
                    "employee_person_id": _ID_PERSONNE,
                    "entrees": entrees_schema,
                    "empreinte_apercu": _HEX_64,
                    "version_attendue": {"type": "integer", "minimum": 0},
                    "type_version": {"type": "string", "enum": ["CREATION", "CORRECTION", "REBASE"]},
                    "motif": _NOTE,
                    "mutation_id": _HEX_32,
                },
                [
                    "employee_person_id",
                    "entrees",
                    "empreinte_apercu",
                    "version_attendue",
                    "type_version",
                    "motif",
                    "mutation_id",
                ],
            ),
            fonction=conserver,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_rouvrir_dossier_paie",
            description=_decrire(
                "Rouvre explicitement un dossier revu ou à corriger pour permettre une nouvelle version."
            ),
            parametres=_schema(
                {
                    "dossier_id": _HEX_32,
                    "numero": {"type": "integer", "minimum": 1},
                    "hash_version": _HEX_64,
                    "motif": {"type": "string", "minLength": 1, "maxLength": journal.MAX_NOTE},
                    "mutation_id": _HEX_32,
                    "horodatage": _HORODATAGE,
                },
                ["dossier_id", "numero", "hash_version", "motif", "mutation_id", "horodatage"],
            ),
            fonction=rouvrir,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_revue_dossier_paie",
            description=_decrire(
                "Revue interne du propriétaire liée à la version ET au hash exacts de la version courante. "
                "Ce n'est ni une validation fiscale ni une attestation professionnelle."
            ),
            parametres=_schema(
                {
                    "dossier_id": _HEX_32,
                    "numero": {"type": "integer", "minimum": 1},
                    "hash_version": _HEX_64,
                    "decision": {"type": "string", "enum": ["REVUE_COMPLETEE", "A_CORRIGER"]},
                    "note": _NOTE,
                    "mutation_id": _HEX_32,
                    "horodatage": _HORODATAGE,
                },
                ["dossier_id", "numero", "hash_version", "decision", "note", "mutation_id", "horodatage"],
            ),
            fonction=revue,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_exporter_dossier_paie",
            description=_decrire(
                "Audite l'export CPA (json ou html) d'une version revue, courante et dont les sources n'ont pas bougé. "
                "Ne rend que l'empreinte de l'export ; le contenu se lit avec m5_lire_export_dossier_paie."
            ),
            parametres=_schema(
                {
                    "dossier_id": _HEX_32,
                    "numero": {"type": "integer", "minimum": 1},
                    "hash_version": _HEX_64,
                    "format_export": {"type": "string", "enum": ["json", "html"]},
                    "mutation_id": _HEX_32,
                    "horodatage": _HORODATAGE,
                },
                ["dossier_id", "numero", "hash_version", "format_export", "mutation_id", "horodatage"],
            ),
            fonction=exporter,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_lire_dossier_paie",
            description=_decrire(
                "Liste les dossiers (sans dossier_id) ou lit un dossier : historique des versions, "
                "revues, réouvertures, "
                "exports, une version complète et, si demandé, la comparaison avec une autre version."
            ),
            parametres=_schema(
                {
                    "dossier_id": {"type": ["string", "null"], "pattern": "^[a-f0-9]{32}$"},
                    "numero": {"type": ["integer", "null"], "minimum": 1},
                    "comparer_a": {"type": ["integer", "null"], "minimum": 1},
                },
                ["dossier_id", "numero", "comparer_a"],
            ),
            fonction=lire,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_verifier_dossier_paie",
            description=_decrire(
                "Vérifie une version conservée : reproductibilité du calcul à partir des entrées figées, et dérive des "
                "heures M4, du contrat M5, de l'admission ou des cumuls simulés. Aucune écriture."
            ),
            parametres=_schema(
                {"dossier_id": _HEX_32, "numero": {"type": ["integer", "null"], "minimum": 1}}, ["dossier_id", "numero"]
            ),
            fonction=verifier,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_lire_export_dossier_paie",
            description=_decrire(
                "Reconstruit l'export CPA reproductible d'une version courante revue, seulement s'il correspond à un "
                "export déjà audité (même empreinte)."
            ),
            parametres=_schema(
                {
                    "dossier_id": _HEX_32,
                    "numero": {"type": "integer", "minimum": 1},
                    "hash_version": _HEX_64,
                    "format_export": {"type": "string", "enum": ["json", "html"]},
                },
                ["dossier_id", "numero", "hash_version", "format_export"],
            ),
            fonction=lire_export,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
    )


def verdict_depuis_details(details: object) -> dict[str, Any] | None:
    """Relit le verdict JSON qu'une `DossierErreur` a laissé dans `details` (enveloppe `refus_metier`)."""
    if not isinstance(details, str):
        return None
    try:
        verdict = json.loads(details)
    except ValueError:
        return None
    if (
        isinstance(verdict, dict)
        and set(verdict) == {"code", "detail"}
        and str(verdict["code"]).startswith("REJ-DOSSIER-PAIE-")
    ):
        return verdict
    return None
