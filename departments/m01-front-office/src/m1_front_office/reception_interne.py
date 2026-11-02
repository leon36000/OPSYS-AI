"""L'adjointe de réception qui regarde sa propre file (M1.11) : ce qui est à rappeler, à confirmer, ouvert ou resté sans
suite, et la façon dont cela devient une attente « À voir » — sans jamais écrire au client.

Module pur : aucune horloge (l'instant est fourni), aucun accès à la base ni au réseau. Il lit les lignes du registre
anti-perte (`registre.py`), celles des rendez-vous et les AVIS déjà consignés, et rend :

- l'ÉTAT de la réception à un instant (`etat_reception`) : des comptes et des références PSEUDONYMES (identifiant de
  transfert, identifiant de conversation : des empreintes), jamais un contact ni un texte de client ;
- les AVIS à consigner (`avis_a_consigner`) : un digest par jour, et trois alertes internes — une urgence de sécurité
  toujours ouverte, un rappel dont l'échéance explicite est passée, une conversation dont la fenêtre est terminée sans
  que la prochaine action ait été faite. Un avis a une clé déterministe : le consigner deux fois n'écrit rien de plus ;
- les ATTENTES « À voir » (`attentes`) : un avis reste affiché tant que la situation qu'il signale est la même (urgence
  encore ouverte, même échéance de rappel, même dernière ligne de la conversation). Aucune heure ici : une alerte
  disparaît quand une personne agit (clôture, nouvelle tentative consignée, nouveau message), jamais par péremption.

Aucun délai de service n'est inventé. Le seul seuil de l'alerte d'urgence est « toujours ouverte après un intervalle
complet de contrôle » (l'intervalle que l'administrateur a réglé à l'activation) ; un rappel est échu à l'échéance
qu'une PERSONNE a choisie ; une conversation est sans suivi à la fin de sa fenêtre (profil de l'entreprise). Un délai de
réponse à promettre (par exemple « une urgence se prend en moins de X minutes ») reste une décision de la direction.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from . import digest, plaintes, rendez_vous, transferts
from . import suivi as suivi_conversation
from .registre import TYPE_REPONSE_COURRIEL

TYPE_AVIS = "avis_reception"
TYPE_KPIS = "kpis_reception"
REGISTRE = "reception_interne"

GENRE_DIGEST = "digest"
GENRE_URGENCE = "urgence_non_prise"
GENRE_RAPPEL = "rappel_echu"
GENRE_SANS_SUIVI = "sans_suivi"
# Ce qu'une consignation traite : le digest du jour, les urgences, les échéances (rappels échus et conversations sans
# suivi).
GROUPES = {"digest": (GENRE_DIGEST,), "urgences": (GENRE_URGENCE,), "echeances": (GENRE_RAPPEL, GENRE_SANS_SUIVI)}

JOURS_COUVERTS_MAX = 7  # un digest couvre au plus une semaine (jamais un historique entier)
GRILLE_MAX = 3000
FENETRE_KPI_DEFAUT, FENETRE_KPI_MAX = 30, 366
KPI_IDS = ("taux_signaux_qualifies_pct", "taux_interdits_bloques_pct")

NIVEAUX = {GENRE_URGENCE: "N5", GENRE_RAPPEL: "N3", GENRE_SANS_SUIVI: "N3", GENRE_DIGEST: "N3"}
TYPES_D_ATTENTE = {
    GENRE_URGENCE: "urgence_non_prise",
    GENRE_RAPPEL: "rappel_echu",
    GENRE_SANS_SUIVI: "conversation_sans_suivi",
    GENRE_DIGEST: "digest_reception",
}
ACTIONS = {
    GENRE_URGENCE: "lire le transfert (m1_lire_transfert), agir, puis le clore (m1_clore_transfert)",
    GENRE_RAPPEL: "rappeler le client, puis consigner la tentative ou clore le transfert",
    GENRE_SANS_SUIVI: "relire la conversation et décider de la suite (aucun message ne part sans une personne)",
    GENRE_DIGEST: "lire (m1_lire_attentes_reception) puis agir sur chaque élément",
}


def instant(valeur: Any) -> datetime:
    """Un instant ISO-8601 AVEC fuseau, ou `ValueError`."""
    if not isinstance(valeur, str):
        raise ValueError("REJ-HORODATAGE-INVALIDE: chaîne ISO-8601 requise")
    try:
        quand = datetime.fromisoformat(valeur)
    except (ValueError, OverflowError):
        raise ValueError("REJ-HORODATAGE-INVALIDE: format ISO-8601 invalide") from None
    if quand.tzinfo is None:
        raise ValueError("REJ-HORODATAGE-INVALIDE: fuseau horaire manquant")
    return quand


def _minutes(depuis: str, maintenant: datetime) -> int:
    return max(0, int((maintenant - instant(depuis)).total_seconds() // 60))


def _empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def cle_avis(genre: str, ref: str | None, extra: str | None) -> str:
    return "|".join(x for x in (genre, ref, extra) if x)


def id_attente(cle: str) -> str:
    return "rec-" + _empreinte(cle)[:20]


# ---------------------------------------------------------------------------------------------------------------
# L'état de la réception
# ---------------------------------------------------------------------------------------------------------------
def _conversations_sans_suivi(
    lignes: Sequence[Mapping[str, Any]], maintenant: datetime, portees_par_un_transfert: set[Any]
) -> list[dict[str, Any]]:
    """Les correspondants dont la DERNIÈRE ligne de suivi demande encore une action et dont la fenêtre est terminée.
    Une conversation plus récente du même correspondant remplace l'ancienne (c'est elle qui porte la suite) ; une
    conversation fermée (transfert à une personne, retrait STOP) n'est plus à suivre. Une conversation qui a un
    transfert OUVERT est déjà portée par une attente « À voir » (un rappel d'appel manqué, par exemple) : elle n'est
    pas comptée une seconde fois."""
    derniere: dict[Any, Mapping[str, Any]] = {}
    for ligne in lignes:
        if ligne.get("type_entree") == suivi_conversation.TYPE_SUIVI:
            derniere[ligne.get("conversation_id")] = ligne
    sortie = []
    for conversation_id, ligne in derniere.items():
        if conversation_id in portees_par_un_transfert:
            continue
        action = ligne.get("prochaine_action")
        if ligne.get("statut") != suivi_conversation.STATUT_OUVERTE or not isinstance(action, Mapping):
            continue
        try:
            fin = instant(action.get("a_faire_avant"))
        except ValueError:
            continue  # une échéance illisible n'est jamais devinée : elle n'est pas comptée
        if fin <= maintenant and isinstance(conversation_id, str) and isinstance(ligne.get("ligne_id"), str):
            sortie.append(
                {
                    "ref": conversation_id,
                    "ligne_ref": ligne["ligne_id"],
                    "a_faire_avant": action["a_faire_avant"],
                    "depuis_min": _minutes(action["a_faire_avant"], maintenant),
                }
            )
    return sorted(sortie, key=lambda x: (x["a_faire_avant"], x["ref"]))


def _rendez_vous(
    lignes: Sequence[Mapping[str, Any]], lignes_rdv: Sequence[Mapping[str, Any]], maintenant: str
) -> dict[str, int]:
    """Fenêtres retenues non confirmées (à confirmer par une personne) et rappels de rendez-vous échus dont le brouillon
    n'a pas encore été demandé à l'envoi par courriel. Limite : un rappel SMS déjà demandé n'est pas reconnu comme
    tel."""
    demandes = {
        x.get("brouillon_id")
        for x in lignes if x.get("type_entree") == TYPE_REPONSE_COURRIEL and x.get("etape") == "demandee"
    }
    quand = instant(maintenant)
    a_confirmer = rappels_dus = 0
    for etat in rendez_vous.etats(lignes_rdv, maintenant).values():
        if etat["etat"] == "retenue":
            a_confirmer += 1
        elif etat["etat"] == "confirmee":
            rappels_dus += sum(
                1
                for m in etat["messages"]
                if m.get("type") == "rappel"
                and m.get("echeance")
                and instant(m["echeance"]) <= quand
                and m.get("brouillon_id") not in demandes
            )
    return {"a_confirmer": a_confirmer, "rappels_dus": rappels_dus}


def etat_reception(
    lignes: Sequence[Mapping[str, Any]], lignes_rdv: Sequence[Mapping[str, Any]], maintenant: str
) -> dict[str, Any]:
    """Ce que la réception a devant elle à cet instant. Références pseudonymes et comptes seulement."""
    quand = instant(maintenant)
    a_rappeler: list[dict[str, Any]] = []
    plaintes_ouvertes: list[int] = []
    urgences: list[dict[str, Any]] = []
    illisibles = 0
    etats = transferts.lire(lignes)
    portees = {e.ouverture["conversation_id"] for e in etats if e.ouvert}
    for etat in etats:
        if not etat.ouvert:
            continue
        ouverture = etat.ouverture
        age = _minutes(ouverture["horodatage"], quand)
        type_transfert = ouverture.get("type_transfert")
        if type_transfert == plaintes.TYPE_URGENCE:
            urgences.append({"ref": etat.identifiant, "depuis_min": age})
        elif type_transfert == plaintes.TYPE_PLAINTE:
            plaintes_ouvertes.append(age)
        if type_transfert == "ventes" and transferts.sources_appel_rappel(lignes, etat.identifiant):
            try:
                projection = transferts.projection_suivi_rappel(lignes, etat.identifiant)
            except ValueError:
                illisibles += 1  # un historique incohérent est dit, jamais interprété
                continue
            if projection is None:
                continue
            prochaine = projection["prochaine_tentative_le"]
            a_rappeler.append(
                {
                    "ref": etat.identifiant,
                    "depuis_min": age,
                    "responsable": projection["responsable"] is not None,
                    "echeance": prochaine,
                    "echu": prochaine is not None and instant(prochaine) <= quand,
                }
            )
    urgences.sort(key=lambda x: (-x["depuis_min"], x["ref"]))
    a_rappeler.sort(key=lambda x: (-x["depuis_min"], x["ref"]))
    return {
        "maintenant": maintenant,
        "a_rappeler": {
            "total": len(a_rappeler),
            "sans_responsable": sum(1 for x in a_rappeler if not x["responsable"]),
            "echus": [{"ref": x["ref"], "echeance": x["echeance"]} for x in a_rappeler if x["echu"]],
            "plus_ancien_minutes": max((x["depuis_min"] for x in a_rappeler), default=None),
        },
        "plaintes_ouvertes": {
            "total": len(plaintes_ouvertes),
            "plus_ancienne_minutes": max(plaintes_ouvertes, default=None),
        },
        "urgences_ouvertes": urgences,
        "sans_suivi": _conversations_sans_suivi(lignes, quand, portees),
        "rendez_vous": _rendez_vous(lignes, lignes_rdv, maintenant),
        "historiques_illisibles": illisibles,
    }


def compteurs(etat: Mapping[str, Any]) -> dict[str, int]:
    """Les comptes du digest (entiers seulement : ce sont eux que le journal et l'attente portent)."""
    return {
        "a_rappeler": etat["a_rappeler"]["total"],
        "a_rappeler_sans_responsable": etat["a_rappeler"]["sans_responsable"],
        "rappels_echus": len(etat["a_rappeler"]["echus"]),
        "rendez_vous_a_confirmer": etat["rendez_vous"]["a_confirmer"],
        "rappels_rdv_dus": etat["rendez_vous"]["rappels_dus"],
        "plaintes_ouvertes": etat["plaintes_ouvertes"]["total"],
        "urgences_non_prises": len(etat["urgences_ouvertes"]),
        "sans_suivi": len(etat["sans_suivi"]),
    }


# ---------------------------------------------------------------------------------------------------------------
# Les avis à consigner
# ---------------------------------------------------------------------------------------------------------------
def jours_a_couvrir(jour: str, avis: Iterable[Mapping[str, Any]]) -> list[str]:
    """Les jours qu'un digest écrit le `jour` décrit : de celui du digest précédent (inclus) à la veille (incluse), au
    plus `JOURS_COUVERTS_MAX` ; la veille seule s'il n'y en a pas eu. Chaque jour entre ainsi dans un digest et un
    seul (le lundi couvre vendredi, samedi et dimanche)."""
    aujourd_hui = datetime.fromisoformat(jour).date()
    veille = aujourd_hui - timedelta(days=1)
    precedents = [
        datetime.fromisoformat(a["jour"]).date()
        for a in avis if a.get("genre") == GENRE_DIGEST and isinstance(a.get("jour"), str) and a["jour"] < jour
    ]
    debut = max(precedents) if precedents else veille
    debut = max(min(debut, veille), veille - timedelta(days=JOURS_COUVERTS_MAX - 1))
    return [(debut + timedelta(days=i)).isoformat() for i in range((veille - debut).days + 1)]


def grille(lignes: Sequence[Mapping[str, Any]], jours: Sequence[str]) -> str:
    """Le digest existant du registre (`digest.produire_digest`), un bloc par jour couvert, borné."""
    texte = "\n\n".join(digest.produire_digest(list(lignes), j) for j in jours)
    return texte if len(texte) <= GRILLE_MAX else texte[: GRILLE_MAX - 1].rstrip() + "…"


def avis_a_consigner(
    groupe: str,
    etat: Mapping[str, Any],
    existants: Iterable[Mapping[str, Any]],
    *,
    lignes: Sequence[Mapping[str, Any]],
    jour: str | None,
    delai_controle_s: int | None,
) -> list[dict[str, Any]]:
    """Les avis du groupe qui n'ont pas déjà une ligne (même clé). Sans écrire : l'ombre et la consignation partagent ce
    calcul. Le digest exige le jour local ; l'urgence exige le délai de contrôle (secondes)."""
    existants = list(existants)
    deja = {a.get("cle") for a in existants}
    candidats: list[dict[str, Any]] = []
    if groupe == "digest":
        if jour is None:
            raise ValueError("REJ-RECEPTION-JOUR-REQUIS: le digest exige le jour local (AAAA-MM-JJ)")
        compte = compteurs(etat)
        jours = jours_a_couvrir(jour, existants)
        candidats.append(
            {
                "genre": GENRE_DIGEST,
                "cle": cle_avis(GENRE_DIGEST, None, jour),
                "ref": None,
                "jour": jour,
                "compteurs": compte,
                "jours_couverts": jours,
                "grille": grille(lignes, jours),
            }
        )
    elif groupe == "urgences":
        if delai_controle_s is None:
            raise ValueError("REJ-RECEPTION-DELAI-REQUIS: l'alerte d'urgence exige le délai de contrôle en secondes")
        for u in etat["urgences_ouvertes"]:
            if u["depuis_min"] * 60 >= delai_controle_s:
                candidats.append(
                    {"genre": GENRE_URGENCE, "cle": cle_avis(GENRE_URGENCE, u["ref"], None), "ref": u["ref"]}
                )
    elif groupe == "echeances":
        for r in etat["a_rappeler"]["echus"]:
            candidats.append(
                {
                    "genre": GENRE_RAPPEL,
                    "cle": cle_avis(GENRE_RAPPEL, r["ref"], r["echeance"]),
                    "ref": r["ref"],
                    "echeance": r["echeance"],
                }
            )
        for c in etat["sans_suivi"]:
            candidats.append(
                {
                    "genre": GENRE_SANS_SUIVI,
                    "cle": cle_avis(GENRE_SANS_SUIVI, c["ref"], c["ligne_ref"]),
                    "ref": c["ref"],
                    "ligne_ref": c["ligne_ref"],
                    "a_faire_avant": c["a_faire_avant"],
                }
            )
    else:
        raise ValueError(f"REJ-RECEPTION-GROUPE-INCONNU: groupe {groupe!r} (attendu {sorted(GROUPES)})")
    return [c for c in candidats if c["cle"] not in deja]


def ligne_avis(avis: Mapping[str, Any], horodatage: str) -> dict[str, Any]:
    return {"type_entree": TYPE_AVIS, "horodatage": horodatage, **avis}


# ---------------------------------------------------------------------------------------------------------------
# Les attentes « À voir »
# ---------------------------------------------------------------------------------------------------------------
def resume_digest(a: Mapping[str, Any]) -> str:
    c = a["compteurs"]
    return (
        f"Digest de réception du {a['jour']} : {c['a_rappeler']} à rappeler ({c['rappels_echus']} échu(s)), "
        f"{c['rendez_vous_a_confirmer']} rendez-vous à confirmer, {c['plaintes_ouvertes']} plainte(s) ouverte(s), "
        f"{c['urgences_non_prises']} urgence(s) non prise(s) en charge, {c['sans_suivi']} conversation(s) sans suivi, "
        f"{c['rappels_rdv_dus']} rappel(s) de rendez-vous dû(s)."
    )


def _resume(a: Mapping[str, Any]) -> str:
    genre = a["genre"]
    if genre == GENRE_DIGEST:
        return resume_digest(a)
    if genre == GENRE_URGENCE:
        return (
            "Urgence de sécurité toujours ouverte, non prise en charge au dernier contrôle : une personne doit la "
            "lire et la clore."
        )
    if genre == GENRE_RAPPEL:
        return f"Rappel échu : la tentative prévue le {a['echeance']} est passée et le dossier est toujours ouvert."
    return (
        f"Conversation sans suivi : sa fenêtre s'est terminée le {a['a_faire_avant']} sans que la prochaine "
        "action soit faite."
    )


def _derniere_ligne_de_suivi(lignes: Sequence[Mapping[str, Any]], conversation_id: str) -> Mapping[str, Any] | None:
    derniere = None
    for ligne in lignes:
        if (
            ligne.get("type_entree") == suivi_conversation.TYPE_SUIVI
            and ligne.get("conversation_id") == conversation_id
        ):
            derniere = ligne
    return derniere


def _persiste(a: Mapping[str, Any], lignes: Sequence[Mapping[str, Any]], etats: Mapping[str, Any]) -> bool:
    """La situation que l'avis signalait est-elle encore la même ?"""
    genre = a["genre"]
    if genre == GENRE_URGENCE:
        etat = etats.get(a.get("ref"))
        return etat is not None and etat.ouvert
    if genre == GENRE_RAPPEL:
        etat = etats.get(a.get("ref"))
        if etat is None or not etat.ouvert:
            return False
        try:
            projection = transferts.projection_suivi_rappel(lignes, etat.identifiant)
        except ValueError:
            return True  # historique incohérent : l'alerte reste (fail-closed)
        return projection is not None and projection["prochaine_tentative_le"] == a.get("echeance")
    if genre == GENRE_SANS_SUIVI:
        derniere = _derniere_ligne_de_suivi(lignes, a.get("ref"))
        return (
            derniere is not None
            and derniere.get("ligne_id") == a.get("ligne_ref")
            and derniere.get("statut") == suivi_conversation.STATUT_OUVERTE
            and isinstance(derniere.get("prochaine_action"), Mapping)
        )
    return False


def attentes(avis: Sequence[Mapping[str, Any]], lignes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Les attentes « À voir » (forme `approbations.CHAMPS_ATTENTE`) que les avis consignés font encore vivre : le
    DERNIER digest, puis chaque alerte dont la situation est la même. Sans donnée personnelle : des comptes et des
    références."""
    etats = {e.identifiant: e for e in transferts.lire(lignes)}
    sortie: list[dict[str, Any]] = []
    digests = [a for a in avis if a.get("genre") == GENRE_DIGEST]
    retenus = ([digests[-1]] if digests else []) + [
        a for a in avis
        if a.get("genre") in (GENRE_URGENCE, GENRE_RAPPEL, GENRE_SANS_SUIVI) and _persiste(a, lignes, etats)
    ]
    for a in retenus:
        sortie.append(
            {
                "type": TYPES_D_ATTENTE[a["genre"]],
                "id": id_attente(a["cle"]),
                "resume": _resume(a),
                "niveau": NIVEAUX[a["genre"]],
                "depuis": a["horodatage"],
                "action_proposee": ACTIONS[a["genre"]],
            }
        )
    return sortie


# ---------------------------------------------------------------------------------------------------------------
# Les KPI du manifeste (taux_signaux_qualifies_pct, taux_interdits_bloques_pct)
# ---------------------------------------------------------------------------------------------------------------
def kpis(lignes: Sequence[Mapping[str, Any]], jour: str, jours: int) -> dict[str, Any]:
    """Les KPI de réception sur les `jours` jours civils finissant à `jour` (date telle qu'écrite au registre). Un KPI
    que le registre ne permet pas de calculer le DIT (`calculable` faux, `manque`) : jamais zéro, jamais cent."""
    fin = datetime.fromisoformat(jour).date()
    debut = (fin - timedelta(days=jours - 1)).isoformat()
    fin_iso = fin.isoformat()
    signaux = [
        x for x in lignes if x.get("type_entree") == "signal" and debut <= str(x.get("horodatage", ""))[:10] <= fin_iso
    ]
    qualifies: set[Any] = set()
    for x in lignes:
        if x.get("type_entree") == "lead_emis":
            qualifies.add(x.get("signal_id"))
            qualifies.update(x.get("signaux_rassembles", ()))
    nombre = sum(1 for s in signaux if s.get("signal_id") in qualifies or s.get("rattache_au_lead"))
    if signaux:
        premier: dict[str, Any] = {
            "calculable": True,
            "valeur_pct": round(100 * nombre / len(signaux), 1),
            "numerateur": nombre,
            "denominateur": len(signaux),
        }
    else:
        premier = {"calculable": False, "manque": "aucun signal reçu dans la fenêtre : un taux sur zéro n'existe pas"}
    return {
        "fenetre": {"debut": debut, "fin": fin_iso, "jours": jours},
        "kpis": {
            "taux_signaux_qualifies_pct": premier,
            "taux_interdits_bloques_pct": {
                "calculable": False,
                "manque": "le garde-fou répond sans rien consigner : aucune ligne du registre ne compte les tentatives "
                "(bloquées ou non), donc aucun taux — la cible de 100 % n'est pas mesurable aujourd'hui",
            },
        },
    }
