"""Radar de risques M9.12 : des signaux déjà mesurés par leurs propriétaires, datés, gradués, contestables.

Module pur. Chaque risque vient d'une RÈGLE versionnée appliquée à des captures complètes (M9.1) : le signal est la
valeur
même que le propriétaire a publiée (alerte de seuil de M5, réservation partielle de M6, incident bloqué de M4, écart de
marge
de M8). M9 n'invente ni seuil ni cause :

* la GRAVITÉ vient d'une grille versionnée (``GRILLE``), PROPOSÉE et non validée par Nathan, qui ne dépend que de la
nature du
  signal ; elle est rendue avec chaque risque ;
* une règle dont la lecture est absente, refusée, partielle ou contradictoire n'est PAS évaluée : elle est listée comme
  donnée manquante (« risque inconnu »), jamais comptée comme « aucun risque » ;
* un risque présent dans une version plus ancienne de la lecture mais absent de la plus récente est LEVÉ (faux positif
  possible) : les deux preuves sont citées ;
* un risque dont la source est plus ancienne que la péremption demandée est À RECONFIRMER, non affirmé ;
* ``origine_etablie`` reste faux : le radar ne dit jamais pourquoi, il dit quoi, quand et d'où.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs

VERSION = "2026-10-28.1"
GRILLE_STATUT = "PROPOSEE_NON_VALIDEE_PAR_NATHAN"
GRADES = ("FAIBLE", "MOYEN", "ELEVE", "INCONNU")
EXPLICATION = "origine non établie par M9 : le signal est publié par son propriétaire, sans cause"
_LIMITES = (
    "Signaux publiés par les propriétaires ; la gravité suit une grille proposée, non validée, sans mesure de dommage.",
    "Une règle non évaluée (lecture absente, refusée, partielle ou contradictoire) est un risque INCONNU, non nul.",
)
_R = "resultat.resultat"


@dataclass(frozen=True)
class Regle:
    id: str
    domaine: str
    lecture_id: str
    lignes: str  # chemin vers la liste de lignes à examiner, ou vers l'objet racine
    signal: Callable[[Mapping], tuple[str, str, tuple[str, ...]] | None]
    # signal(ligne) -> (gravité, sujet, champs cités) ou None

    def __post_init__(self) -> None:
        if not self.id or not self.domaine or not self.lignes:
            raise ValueError("règle de risque incomplète")


def _signal_alerte_cash(ligne: Mapping) -> tuple[str, str, tuple[str, ...]] | None:
    alerte = ligne.get("alerte")
    if not isinstance(alerte, Mapping) or alerte.get("statut") != "ALERTE":
        return None
    deficit = ligne.get("premiere_semaine_en_deficit") is not None
    return ("ELEVE" if deficit else "MOYEN", "tresorerie", ("alerte.statut", "premiere_semaine_en_deficit"))


def _signal_cash_inconnu(ligne: Mapping) -> tuple[str, str, tuple[str, ...]] | None:
    alerte = ligne.get("alerte") if isinstance(ligne.get("alerte"), Mapping) else {}
    if ligne.get("calculable") is False or alerte.get("statut") in ("NON_EVALUEE", "SEUIL_A_CONFIGURER"):
        return ("INCONNU", "tresorerie", ("calculable", "alerte.statut"))
    return None


def _signal_reservation(ligne: Mapping) -> tuple[str, str, tuple[str, ...]] | None:
    statut = ligne.get("statut")
    if statut not in ("partiel", "a_commander") or type(ligne.get("devis_id")) is not str:
        return None
    return ("ELEVE" if statut == "a_commander" else "MOYEN", f"devis:{ligne['devis_id']}", ("statut", "devis_id"))


def _signal_incident(ligne: Mapping) -> tuple[str, str, tuple[str, ...]] | None:
    if type(ligne.get("demande_id")) is not str:
        return None
    return (
        "ELEVE" if ligne.get("bloquee") is True else "FAIBLE",
        f"incident:{ligne['demande_id']}",
        ("bloquee", "demande_id"),
    )


def _signal_report(ligne: Mapping) -> tuple[str, str, tuple[str, ...]] | None:
    if type(ligne.get("intervention_id")) is not str:
        return None
    return ("MOYEN" if ligne.get("motif") == "meteo" else "FAIBLE", f"report:{ligne['intervention_id']}", ("motif",))


def _signal_ecart_marge(ligne: Mapping) -> tuple[str, str, tuple[str, ...]] | None:
    if ligne.get("metric_id") != "m8_ecart_marge_cad" or type(ligne.get("valeur")) is not str:
        return None
    try:
        negatif = Decimal(ligne["valeur"]) < 0
    except InvalidOperation:
        return None
    return ("MOYEN", "rentabilite_chantier", ("metric_id", "valeur")) if negatif else None


REGLES: tuple[Regle, ...] = (
    Regle("cash_alerte_seuil", "cash", "m5.prevision_tresorerie", _R, _signal_alerte_cash),
    Regle("cash_non_evaluable", "cash", "m5.prevision_tresorerie", _R, _signal_cash_inconnu),
    Regle("materiaux_reservation_incomplete", "materiaux", "m6.disponibilite",
          f"{_R}.reservations_actives[*]", _signal_reservation),
    Regle("capacite_incident_ouvert", "capacite", "m4.retards_incidents", f"{_R}.incidents.liste[*]", _signal_incident),
    Regle("capacite_report_en_cours", "capacite", "m4.retards_incidents", f"{_R}.reports.liste[*]", _signal_report),
    Regle("qualite_ecart_marge_negatif", "qualite", "m8.mesures_chantier", "resultat.mesures[*]", _signal_ecart_marge),
)  # fmt: skip


def _adresse(capture: Mapping, numero_page: int, lignes: str, rang: int, champ: str | None) -> str:
    base = lignes[:-3] + f"[{rang}]" if lignes.endswith("[*]") else lignes
    suffixe = f".{champ}" if champ else ""
    return f"{capture['lecture_id']}#{capture['index']}:p{numero_page}.{base}{suffixe}"


def _occurrences(regle: Regle, capture: Mapping) -> dict[str, dict]:
    trouvees: dict[str, dict] = {}
    for numero_page, page in enumerate(capture["pages"]):
        for rang, ligne in enumerate(cs.extraire(page, regle.lignes)):
            if not isinstance(ligne, Mapping):
                continue
            signal = regle.signal(ligne)
            if signal is None:
                continue
            gravite, sujet, champs = signal
            trouvees.setdefault(
                sujet,
                {
                    "gravite": gravite,
                    "preuves": [_adresse(capture, numero_page, regle.lignes, rang, champ) for champ in champs],
                },
            )
    return trouvees


def _age_jours(capture: Mapping, connaissance_dt) -> int | None:
    recu = cs.instant(capture["recu_a"])
    return (connaissance_dt - recu).days if recu is not None and connaissance_dt is not None else None


def evaluer(captures: Sequence[Mapping], *, connaissance: str, perime_apres_jours: int | None = None) -> dict:
    if perime_apres_jours is not None and (type(perime_apres_jours) is not int or not 0 <= perime_apres_jours <= 3650):
        raise ValueError("REJ-RISQUE-PEREMPTION : entier de 0 à 3650 jours ou absent")
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    maintenant = cs.instant(connaissance)
    risques: list[dict] = []
    non_evaluees: list[dict] = []
    for regle in REGLES:
        lues = [c for c in connues if c["lecture_id"] == regle.lecture_id]
        if not lues:
            non_evaluees.append({"regle": regle.id, "domaine": regle.domaine, "raison": "ABSENTE"})
            continue
        par_arguments: dict[str, list[Mapping]] = {}
        for capture in lues:
            par_arguments.setdefault(capture["arguments_sha256"], []).append(capture)
        evaluee = False
        for groupe in par_arguments.values():
            utilisables = [
                c
                for c in groupe
                if c["verdict"] == "ACCEPTEE"
                and c["complete"]
                and (c["lecture_id"], c["arguments_sha256"]) not in en_conflit
            ]
            derniere = groupe[-1]
            if not utilisables or utilisables[-1] is not derniere:
                if derniere["verdict"] != "ACCEPTEE":
                    raison = "REFUSEE"
                elif (derniere["lecture_id"], derniere["arguments_sha256"]) in en_conflit:
                    raison = "CONTRADICTOIRE"
                else:
                    raison = "PARTIELLE"
                non_evaluees.append(
                    {"regle": regle.id, "domaine": regle.domaine, "raison": raison, "capture": derniere["index"]}
                )
                continue
            evaluee = True
            courante = utilisables[-1]
            actuels = _occurrences(regle, courante)
            for sujet, trouve in actuels.items():
                age = _age_jours(courante, maintenant)
                perime = perime_apres_jours is not None and age is not None and age > perime_apres_jours
                risques.append(
                    _risque(regle, sujet, trouve, courante, "A_RECONFIRMER" if perime else "ACTIF", age, [], perime)
                )
            # Versions plus anciennes du même jeu d'arguments : un signal disparu est LEVÉ (faux positif possible).
            deja = set(actuels)
            for ancienne in reversed(utilisables[:-1]):
                for sujet, trouve in _occurrences(regle, ancienne).items():
                    if sujet in deja:
                        continue
                    deja.add(sujet)
                    contraire = {
                        "capture": courante["index"],
                        "constat": "signal absent de la lecture plus récente",
                        "recu_a": courante["recu_a"],
                    }
                    risques.append(
                        _risque(
                            regle, sujet, trouve, ancienne, "LEVE", _age_jours(ancienne, maintenant), [contraire], False
                        )
                    )
        if not evaluee and not any(n["regle"] == regle.id for n in non_evaluees):  # pragma: no cover - garde
            non_evaluees.append({"regle": regle.id, "domaine": regle.domaine, "raison": "INCONNUE"})
    ordre = {"ACTIF": 0, "A_RECONFIRMER": 1, "LEVE": 2}
    risques.sort(
        key=lambda r: (
            ordre[r["statut"]],
            -GRADES.index(r["gravite"]) if r["gravite"] != "INCONNU" else 1,
            r["risque_id"],
        )
    )
    resultat = {
        "type": "RADAR_RISQUES",
        "version": VERSION,
        "grille": {"statut": GRILLE_STATUT, "grades": list(GRADES)},
        "connaissance": connaissance,
        "perime_apres_jours": perime_apres_jours,
        "risques": risques,
        "regles_non_evaluees": non_evaluees,
        "limites": list(_LIMITES),
    }
    resultat["radar_id"] = hashlib.sha256(
        json.dumps(resultat, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return resultat


def _risque(regle, sujet, trouve, capture, statut, age, contraires, perime) -> dict:
    identifiant = hashlib.sha256(f"{regle.id}|{sujet}|{capture['hash_maillon']}".encode()).hexdigest()[:20]
    manquants = ["source plus ancienne que la péremption demandée : à reconfirmer"] if perime else []
    return {
        "risque_id": identifiant,
        "regle": regle.id,
        "domaine": regle.domaine,
        "sujet": sujet,
        "gravite": trouve["gravite"],
        "statut": statut,
        "source": {
            "capture": capture["index"],
            "hash": capture["hash_maillon"],
            "recu_a": capture["recu_a"],
            "age_jours": age,
        },
        "preuves": trouve["preuves"],
        "elements_contraires": contraires,
        "donnees_manquantes": manquants,
        "origine_etablie": False,
        "explication": EXPLICATION,
    }
