"""Outils des réglages de direction (CFG-1) : lire ce qui manque, adopter une valeur, revenir en arrière.

M9 est le département de la direction : il porte les trois gestes, mais les RÈGLES vivent dans le socle
(`opsys.reglages` : déclaration, magasin chaîné, couche de lecture) et les réglages, eux, sont déclarés par les
départements qui les consomment (bloc `reglages:` de leur manifeste, aujourd'hui M2 et M8).

- `m9_lire_reglages_manquants` (N0, lecture) : ce qui est vide, ce que ça bloque, la proposition et son origine. Ne
  montre aucune raison libre ni aucun journal ; hors transaction, rien n'est lisible ;
- `m9_adopter_reglage` (N3) et `m9_revenir_sur_reglage` (N3) : écritures internes, JAMAIS exécutées sans qu'un HUMAIN
  les ait approuvées par le sas (`approbations.decider`) : l'outil relit l'approbateur EN BASE (`approbateur_en_cours`,
  rôle `nathan_owner`, personne active), la demande approuvée, son niveau et l'instant de la décision. Un appel sans
  cette situation (agent, appareil, ligne de commande, jeu de test direct) est refusé avant toute écriture : une
  proposition ne s'adopte jamais d'elle-même. L'instant écrit au magasin est l'horloge du serveur au moment de la
  décision, jamais un argument.

Aucune valeur n'est inventée ici : `valeur` est celle que le propriétaire approuve (la proposition du département ou
la sienne), validée contre le type et les bornes que le département a déclarés.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from opsys import approbations, contexte, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau, Outil
from opsys.reglages import lecture, magasin
from opsys.reglages.declaration import Reglage, ReglageRefuse
from opsys.stockage.schema import APPROBATIONS

DEPARTEMENT = "m09-strategic-intelligence"
NOM_LIRE = "m9_lire_reglages_manquants"
NOM_ADOPTER = "m9_adopter_reglage"
NOM_REVENIR = "m9_revenir_sur_reglage"
ROLES_ADOPTION = frozenset({"nathan_owner"})
_REF = {"type": "string", "pattern": "^m(10|[1-9])\\.[a-z][a-z0-9_]{2,60}$", "maxLength": 70,
        "description": "Clé du réglage déclaré par un département (ex. m2.jours_entre_relances)."}
_RAISON = {"type": "string", "minLength": 3, "maxLength": magasin.RAISON_MAX,
           "description": "Pourquoi ce geste (3 à 300 caractères, sans renseignement personnel)."}
_VERSION = {"type": "integer", "minimum": 0,
            "description": "Version du réglage lue à l'écran : le geste est refusé si elle a changé depuis."}


def _refus(erreur: ReglageRefuse) -> ValueError:
    return ValueError(str(erreur))


def reglage_declare(cle: str) -> Reglage:
    for departement in charger_departements().values():
        for reglage in departement.reglages:
            if reglage.cle == cle:
                return reglage
    raise ReglageRefuse("REJ-REGLAGE-INCONNU", f"aucun département ne déclare le réglage {cle!r}")


def signature_humaine(nom_outil: str, reglage: Reglage) -> tuple[str, str, str, str]:
    """(personne, rôle, demande, instant ISO UTC) de l'humain qui a approuvé la demande EN COURS, ou `ReglageRefuse`.

    Quatre conditions, toutes relues en base : un approbateur humain `nathan_owner` actif pour CET outil et CE
    département (`approbateur_en_cours`) ; une demande dont le niveau figé est celui que le réglage exige ; l'instant
    de la décision du
    serveur. Sinon : refus, rien d'écrit."""
    cnx = stockage.connexion_courante()
    signataire = approbations.approbateur_en_cours(cnx, nom_outil, DEPARTEMENT, roles=ROLES_ADOPTION)
    demande = contexte.demande_approuvee_en_cours()
    if signataire is None or demande is None:
        raise ReglageRefuse(
            "REJ-HUMAIN-REQUIS",
            "ce geste exige l'approbation d'un humain (propriétaire) dans le sas, jamais un agent seul",
        )
    niveau = cnx.execute(select(APPROBATIONS.c.niveau).where(APPROBATIONS.c.id == demande)).scalar_one_or_none()
    if niveau != reglage.niveau.value:
        raise ReglageRefuse(
            "REJ-REGLAGE-NIVEAU",
            f"ce réglage exige une approbation {reglage.niveau.value} (la demande porte {niveau!r})",
        )
    instant = approbations.instant_de_la_decision_en_cours(cnx)
    if instant is None:
        raise ReglageRefuse("REJ-REGLAGE-INSTANT", "instant de la décision indisponible")
    return signataire.personne, signataire.role, demande, instant.isoformat(timespec="seconds")


def _compact(r: dict[str, Any]) -> dict[str, Any]:
    """Une ligne de réponse pour l'agent : l'essentiel, sans justification ni raison libre."""
    proposition = r["proposition"]
    return {
        "cle": r["cle"], "departement": r["departement"], "libelle": r["libelle"], "statut": r["statut"],
        "valeur": r["valeur_texte"] or None, "unite": r["unite"], "debloque": r["debloque"],
        "proposition": None if proposition is None else {
            "valeur": proposition["valeur_texte"], "etiquette": proposition["etiquette"],
            "source": proposition["source"],
        },
        "version": r["version"],
    }


def construire_outils(*, budget_sortie: int) -> tuple[Outil, ...]:
    def lire_manquants(
        departement: str | None = None, seulement_manquants: bool = True, depart: int = 0
    ) -> dict[str, Any]:
        if stockage.connexion_courante() is None:
            raise ValueError("REJ-REGLAGE-TRANSACTION : lecture possible dans une transaction de l'instance seulement")
        etat = lecture.etat_des_reglages(charger_departements(), departement=departement)
        liste = [r for r in etat["reglages"] if r["manque"]] if seulement_manquants else etat["reglages"]
        if type(depart) is not int or not 0 <= depart <= len(liste):
            raise ValueError("REJ-REGLAGE-DEPART : départ entre 0 et le nombre de réglages ; reprendre à 0")
        entete = {
            "accepte": True, "chaine": etat["chaine"], "total": etat["total"], "manquants": etat["manquants"],
            "mention": ("Valeurs proposées : « recommandation, non validée ». Elles ne s'appliquent jamais seules : "
                        "le propriétaire adopte (N3) depuis la console « Réglages de direction »."),
        }
        marge = budget_sortie - len(json.dumps(entete, ensure_ascii=False)) - 400
        page: list[dict[str, Any]] = []
        for r in liste[depart:]:
            ligne = _compact(r)
            if len(json.dumps(page + [ligne], ensure_ascii=False)) > marge:
                break
            page.append(ligne)
        if liste[depart:] and not page:
            raise ValueError("REJ-REGLAGE-BORNE : un réglage dépasse la borne de sortie")
        suivant = depart + len(page)
        prochain = suivant if suivant < len(liste) else None
        return {**entete, "reglages": page, "depart": depart, "prochain_depart": prochain}

    def adopter(cle: str, valeur: Any, raison: str, version_attendue: int | None = None) -> dict[str, Any]:
        try:
            reglage = reglage_declare(cle)
            par, role, demande, quand = signature_humaine(NOM_ADOPTER, reglage)
            resultat = magasin.adopter(
                stockage.connexion_courante(), reglage, valeur, par=par, role=role, approbation_id=demande,
                raison=raison, quand=quand, version_attendue=version_attendue,
            )
        except ReglageRefuse as erreur:
            raise _refus(erreur) from None
        if resultat["statut"] == "adopte":
            _journaliser(par, "reglage.adopter", reglage, resultat)
        return {"accepte": True, "resultat": resultat}

    def revenir(cle: str, raison: str, version_attendue: int | None = None) -> dict[str, Any]:
        try:
            reglage = reglage_declare(cle)
            par, role, demande, quand = signature_humaine(NOM_REVENIR, reglage)
            resultat = magasin.revenir(
                stockage.connexion_courante(), reglage, par=par, role=role, approbation_id=demande, raison=raison,
                quand=quand, version_attendue=version_attendue,
            )
        except ReglageRefuse as erreur:
            raise _refus(erreur) from None
        _journaliser(par, "reglage.revenir", reglage, resultat)
        return {"accepte": True, "resultat": resultat}

    return (
        Outil(
            nom=NOM_LIRE,
            description=(
                "Liste les réglages de direction (seuils, fréquences, bornes) que les départements déclarent : "
                "ce qui manque, ce que cela bloque, la valeur proposée (« recommandation, non validée ») et sa "
                "source. Lecture seule ; n'adopte rien."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "departement": {"type": "string", "pattern": "^m(0[1-9]|10)-[a-z][a-z0-9-]+$", "maxLength": 64},
                    "seulement_manquants": {"type": "boolean"},
                    "depart": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
            fonction=lire_manquants,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom=NOM_ADOPTER,
            description=(
                "Adopte la valeur d'un réglage de direction (N3). N'agit que sur approbation du propriétaire dans "
                "le sas ; valeur validée contre les bornes du département ; idempotent ; ne s'applique jamais "
                "d'elle-même."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "cle": _REF,
                    "valeur": {"type": ["integer", "number", "string", "array", "object"],
                               "description": "Valeur adoptée, du type déclaré par le département."},
                    "raison": _RAISON,
                    "version_attendue": _VERSION,
                },
                "required": ["cle", "valeur", "raison"],
                "additionalProperties": False,
            },
            fonction=adopter,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
            portee_contexte="globale",  # réglage d'entreprise : aucune affaire à lier (garde du Core)
        ),
        Outil(
            nom=NOM_REVENIR,
            description=(
                "Annule la dernière valeur adoptée d'un réglage de direction (N3) et rétablit la précédente, ou "
                "l'absence. N'agit que sur approbation du propriétaire dans le sas."
            ),
            parametres={
                "type": "object",
                "properties": {"cle": _REF, "raison": _RAISON, "version_attendue": _VERSION},
                "required": ["cle", "raison"],
                "additionalProperties": False,
            },
            fonction=revenir,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
            portee_contexte="globale",
        ),
    )


def _journaliser(par: str, action: str, reglage: Reglage, resultat: dict[str, Any]) -> None:
    """Journal d'audit du socle : la clé, la version et l'empreinte du maillon seulement. Ni la raison (texte libre),
    ni la
    valeur : tout le détail est au magasin chaîné."""
    from opsys.etat import journaliser

    details = {"version": resultat["version"], "empreinte": resultat.get("empreinte"),
               "departement": reglage.departement}
    journaliser(stockage.connexion_courante(), par, action, reglage.cle, details)
