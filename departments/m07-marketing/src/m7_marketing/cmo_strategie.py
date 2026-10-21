"""Programme CMO humain durable; projection existante, aucune action externe."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from opsys import contexte, identite, stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

from . import growth_lecture, plan_cmo

DEPARTEMENT = "m07-marketing"
REGISTRE = "strategies_cmo"
MAX_EVENEMENTS = 1000
MAX_MAILLON = 32 * 1024  # caractères, distincts des octets du POST
MAX_TOTAL = 1024 * 1024
_FENETRES = {"J1-30", "J31-60", "J61-90"}
_COMMANDES = {"proposer", "decider", "revoir"}


def empreinte(valeur: Any) -> str:
    return hashlib.sha256(json.dumps(
        valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _objet(valeur, champs):
    if not isinstance(valeur, dict) or set(valeur) != set(champs):
        raise ValueError("CMO-CHAMPS-INVALIDES")


def _texte(valeur, maximum=400):
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum:
        raise ValueError("CMO-TEXTE-INVALIDE")


def _hash(valeur):
    if not isinstance(valeur, str) or re.fullmatch(r"[0-9a-f]{64}", valeur) is None:
        raise ValueError("CMO-EMPREINTE-INVALIDE")


def _entier(valeur, minimum=0):
    if type(valeur) is not int or not minimum <= valeur <= MAX_EVENEMENTS:
        raise ValueError("CMO-REVISION-INVALIDE")


def _nombre(valeur):
    if type(valeur) not in {int, float} or (type(valeur) is float and not math.isfinite(valeur)):
        raise ValueError("CMO-NOMBRE-INVALIDE")


def _liste(valeur, maximum, minimum=0):
    if not isinstance(valeur, list) or not minimum <= len(valeur) <= maximum:
        raise ValueError("CMO-LISTE-HORS-BORNES")


def _tete(valeur):
    _objet(valeur, {"rang", "empreinte"})
    _entier(valeur["rang"])
    _hash(valeur["empreinte"])


def _reference(valeur):
    _objet(valeur, {"observation_id", "empreinte"})
    _texte(valeur["observation_id"], 200)
    _hash(valeur["empreinte"])


def _periode(debut, fin):
    d, f = plan_cmo.date_iso(debut, "DEBUT"), plan_cmo.date_iso(fin, "FIN")
    if d > f or (f - d).days > 365:
        raise ValueError("CMO-PERIODE-INVALIDE")


def _definition(a):
    _texte(a["programme_id"], 100)
    _texte(a["titre"], 200)
    _texte(a["hypothese"])
    _objet(a["parametres"], {"date_depart", "debut", "fin"})
    _periode(a["parametres"]["debut"], a["parametres"]["fin"])
    depart = plan_cmo.date_iso(a["parametres"]["date_depart"], "DATE_DEPART")
    if depart > date.max - timedelta(days=89):
        raise ValueError("CMO-HORIZON-DATE-DEPASSE")
    _liste(a["objectifs"], 10, 1)
    _liste(a["actions"], 30, 1)
    ids = set()
    for objectif in a["objectifs"]:
        _objet(objectif, {"objectif_id", "intitule", "metrique", "unite", "cible", "baseline"})
        for cle in ("objectif_id", "intitule", "metrique", "unite"):
            _texte(objectif[cle], 200)
        if objectif["objectif_id"] in ids:
            raise ValueError("CMO-OBJECTIF-DUPLIQUE")
        ids.add(objectif["objectif_id"])
        if objectif["cible"] is not None:
            _nombre(objectif["cible"])
        if objectif["baseline"] is not None:
            _reference(objectif["baseline"])
    actions = set()
    for action in a["actions"]:
        _objet(action, {"action_id", "objectif_id", "fenetre", "livrable", "responsable", "capacite_declaree"})
        for cle in ("action_id", "objectif_id", "livrable", "responsable", "capacite_declaree"):
            _texte(action[cle], 64 if cle == "responsable" else 400)
        if action["action_id"] in actions or action["objectif_id"] not in ids or action["fenetre"] not in _FENETRES:
            raise ValueError("CMO-ACTION-INVALIDE")
        actions.add(action["action_id"])


def valider_commande(nom, a):
    communs = {"programme_id", "tete", "growth_tete"}
    if nom == "proposer":
        _objet(a, communs | {"revision_attendue", "empreinte_revision_attendue", "parametres", "projection_attendue",
                            "titre", "hypothese", "objectifs", "actions"})
        _definition(a)
        _entier(a["revision_attendue"])
        if a["revision_attendue"] == 0:
            if a["empreinte_revision_attendue"] is not None:
                raise ValueError("CMO-REVISION-INITIALE-INVALIDE")
        else:
            _hash(a["empreinte_revision_attendue"])
        _hash(a["projection_attendue"])
    elif nom in {"decider", "revoir"}:
        specifiques = {"decision", "motif", "projection_attendue"} if nom == "decider" else {
            "debut", "fin", "conclusion", "observations",
        }
        _objet(a, communs | {"revision", "empreinte_revision"} | specifiques)
        _texte(a["programme_id"], 100)
        _entier(a["revision"], 1)
        _hash(a["empreinte_revision"])
        if nom == "decider":
            if a["decision"] not in {"approuver", "rejeter"}:
                raise ValueError("CMO-DECISION-INVALIDE")
            _texte(a["motif"])
            _hash(a["projection_attendue"])
        else:
            _periode(a["debut"], a["fin"])
            _texte(a["conclusion"], 800)
            _liste(a["observations"], 20)
            for ref in a["observations"]:
                _reference(ref)
            if len({r["observation_id"] for r in a["observations"]}) != len(a["observations"]):
                raise ValueError("CMO-REFERENCE-DUPLIQUEE")
    else:
        raise ValueError("CMO-COMMANDE-INCONNUE")
    _tete(a["tete"])
    _tete(a["growth_tete"])
    # Même contrat à l'appel Python; pas seulement au transport HTTP.
    if len(empreinte(a)) != 64 or len(codec.encoder(a).encode("utf-8")) > 32 * 1024:
        raise ValueError("CMO-COMMANDE-TROP-GRANDE")


def _autorite(cnx, *, owner=False):
    appelant = contexte.identite_appelante()
    if (stockage.connexion_courante() is not cnx or cnx.engine.dialect.name != "sqlite" or appelant is None
            or appelant.source != "console" or contexte.departement_origine_appelante() != "console"):
        raise PermissionError("CMO-PORT-HUMAIN-REQUIS")
    personne = identite.personne_active(cnx, appelant.personne)
    if (personne is None or appelant.role not in personne.roles
            or appelant.role not in {"admin", "nathan_owner"} or (owner and appelant.role != "nathan_owner")):
        raise PermissionError("CMO-AUTORITE-RETIREE")
    return {"personne": personne.identifiant, "role": appelant.role, "source": "console"}


def _bornes(nombre, total, maximum):
    if nombre > MAX_EVENEMENTS or total > MAX_TOTAL or maximum > MAX_MAILLON:
        raise ValueError("CMO-QUOTA-REGISTRE")


def _prefixe(cnx):
    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == REGISTRE)
    stats = cnx.execute(select(func.count(), func.coalesce(func.sum(func.length(REGISTRES.c.maillon)), 0),
                               func.coalesce(func.max(func.length(REGISTRES.c.maillon)), 0),
                               func.max(REGISTRES.c.rang), func.min(REGISTRES.c.rang)).where(filtre)).one()
    _bornes(*stats[:3])
    if stats[3] is not None and (stats[3] != stats[0] - 1 or stats[4] != 0):
        raise ValueError("CMO-PREFIXE-NON-CONTIGU")
    textes = [] if stats[3] is None else list(cnx.execute(
        select(func.substr(REGISTRES.c.maillon, 1, MAX_MAILLON + 1))
        .where(filtre & (REGISTRES.c.rang <= stats[3])).order_by(REGISTRES.c.rang).limit(MAX_EVENEMENTS + 1)
    ).scalars())
    if len(textes) != stats[0] or any(not isinstance(t, str) for t in textes):
        raise ValueError("CMO-PREFIXE-CHANGE")
    _bornes(len(textes), sum(map(len, textes)), max(map(len, textes), default=0))
    digest = hashlib.sha256()
    for texte in textes:
        octets = texte.encode("utf-8")
        digest.update(len(octets).to_bytes(8, "big"))
        digest.update(octets)
    return textes, {"rang": len(textes), "empreinte": digest.hexdigest()}


def _image_declaree(s):
    _objet(s, {"observation_id", "empreinte", "metrique", "unite", "valeur", "periode"})
    _reference({k: s[k] for k in ("observation_id", "empreinte")})
    _texte(s["metrique"], 200)
    _texte(s["unite"], 200)
    _nombre(s["valeur"])
    _objet(s["periode"], {"debut", "fin"})
    _periode(s["periode"]["debut"], s["periode"]["fin"])


def _projection_stockee(c):
    _objet(c["projection"], {"version_regles", "fenetres"})
    if c["projection"]["version_regles"] != plan_cmo.VERSION_REGLES:
        raise ValueError("CMO-REGLES-INCONNUES")
    f = c["projection"]["fenetres"]
    _liste(f, 3, 3)
    depart = plan_cmo.date_iso(c["parametres"]["date_depart"], "DATE_DEPART")
    for i, nom in enumerate(("J1-30", "J31-60", "J61-90")):
        _objet(f[i], {"id", "debut", "fin"})
        if f[i] != {"id": nom, "debut": (depart + timedelta(days=i * 30)).isoformat(),
                    "fin": (depart + timedelta(days=i * 30 + 29)).isoformat()}:
            raise ValueError("CMO-FENETRES-INVALIDES")
    _objet(c["baselines"], {o["objectif_id"] for o in c["objectifs"]})
    for o in c["objectifs"]:
        s = c["baselines"][o["objectif_id"]]
        if o["baseline"] is None:
            if s is not None:
                raise ValueError("CMO-BASELINE-INVENTEE")
        else:
            _image_declaree(s)
            if ({k: s[k] for k in ("observation_id", "empreinte")} != o["baseline"]
                    or s["metrique"] != o["metrique"] or s["unite"] != o["unite"]
                    or s["periode"]["debut"] < c["parametres"]["debut"]
                    or s["periode"]["fin"] > c["parametres"]["fin"]):
                raise ValueError("CMO-BASELINE-HISTORIQUE-INCOHERENTE")


def _journal(cnx):
    textes, tete = _prefixe(cnx)
    programmes = {}
    for texte in textes:
        try:
            e = codec.decoder(texte)
            _objet(e, {"schema_version", "type", "charge", "auteur", "horodatage", "empreinte"})
            if type(e["schema_version"]) is not int or e["schema_version"] != 1 or e["type"] not in _COMMANDES:
                raise ValueError("CMO-EVENEMENT-INCONNU")
            _objet(e["auteur"], {"personne", "role", "source"})
            _texte(e["auteur"]["personne"], 64)
            if e["auteur"]["role"] not in {"admin", "nathan_owner"} or e["auteur"]["source"] != "console":
                raise ValueError("CMO-PROVENANCE-INVALIDE")
            _texte(e["horodatage"], 40)
            instant = datetime.fromisoformat(e["horodatage"])
            if instant.utcoffset() != timedelta(0):
                raise ValueError("CMO-HORODATAGE-INVALIDE")
            _hash(e["empreinte"])
            if empreinte({k: v for k, v in e.items() if k != "empreinte"}) != e["empreinte"]:
                raise ValueError("CMO-HASH-INVALIDE")
            c = e["charge"]
            _texte(c["programme_id"], 100)
            _entier(c["revision"], 1)
            versions = programmes.setdefault(c["programme_id"], [])
            if e["type"] == "proposer":
                _objet(c, {"programme_id", "revision", "titre", "hypothese", "parametres", "objectifs", "actions",
                           "projection", "empreinte_projection", "baselines", "growth_tete"})
                _definition(c)
                _projection_stockee(c)
                _hash(c["empreinte_projection"])
                _tete(c["growth_tete"])
                if c["revision"] != len(versions) + 1:
                    raise ValueError("CMO-REVISION-NON-CONTIGUE")
                versions.append({"proposition": e, "decision": None, "revues": []})
            else:
                v = versions[c["revision"] - 1]
                if c["empreinte_revision"] != v["proposition"]["empreinte"]:
                    raise ValueError("CMO-REVISION-HASH-INVALIDE")
                if e["type"] == "decider":
                    _objet(c, {"programme_id", "revision", "empreinte_revision", "decision", "motif", "growth_tete",
                               "empreinte_projection"})
                    if (e["auteur"]["role"] != "nathan_owner" or v["decision"] is not None
                            or c["revision"] != len(versions) or c["decision"] not in {"approuver", "rejeter"}):
                        raise ValueError("CMO-DECISION-HISTORIQUE-INVALIDE")
                    _texte(c["motif"])
                    _hash(c["empreinte_projection"])
                    if c["empreinte_projection"] != v["proposition"]["charge"]["empreinte_projection"]:
                        raise ValueError("CMO-DECISION-REBASEE")
                    _tete(c["growth_tete"])
                    v["decision"] = e
                else:
                    _objet(c, {"programme_id", "revision", "empreinte_revision", "debut", "fin", "conclusion",
                               "observations", "growth_tete"})
                    if v["decision"] is None or v["decision"]["charge"]["decision"] != "approuver":
                        raise ValueError("CMO-REVUE-NON-APPROUVEE")
                    _periode(c["debut"], c["fin"])
                    _texte(c["conclusion"], 800)
                    _liste(c["observations"], 20)
                    for observation in c["observations"]:
                        _image_declaree(observation)
                        if observation["periode"]["debut"] < c["debut"] or observation["periode"]["fin"] > c["fin"]:
                            raise ValueError("CMO-REVUE-PERIODE-INCOHERENTE")
                    if len({o["observation_id"] for o in c["observations"]}) != len(c["observations"]):
                        raise ValueError("CMO-REVUE-REFERENCE-DUPLIQUEE")
                    _tete(c["growth_tete"])
                    v["revues"].append(e)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError, AttributeError, RecursionError) as exc:
            raise ValueError("CMO-HISTORIQUE-INVALIDE") from exc
    return textes, tete, programmes


def lire(cnx):
    """Historique figé accessible sans lire les sources Growth ou recalculer le plan."""
    _autorite(cnx)
    _, tete, programmes = _journal(cnx)
    return {"tete": tete, "programmes": programmes, "statut_source": "DECLAREE_NON_VERIFIEE"}


def _growth(cnx, attendu):
    textes, tete = growth_lecture.lire_prefixe(cnx)
    if attendu != tete:
        raise ValueError("CMO-GROWTH-TETE-PERIMEE")
    return growth_lecture.decoder_prefixe(textes), tete


def _snapshot(ref, observations, debut, fin):
    observation = next((o for o in observations if o["observation_id"] == ref["observation_id"]), None)
    if (observation is None or observation["empreinte"] != ref["empreinte"]
            or observation["periode"]["debut"] < debut or observation["periode"]["fin"] > fin):
        raise ValueError("CMO-REFERENCE-GROWTH-INEXACTE")
    return {k: observation[k] for k in ("observation_id", "empreinte", "metrique", "unite", "valeur", "periode")}


def executer(cnx, nom, arguments, *, projection, horodatage):
    """Appelé seulement après reclaim par la branche privée; décision sans rebase."""
    valider_commande(nom, arguments)
    auteur = _autorite(cnx, owner=nom == "decider")
    textes, tete, programmes = _journal(cnx)
    if tete != arguments["tete"]:
        raise ValueError("CMO-TETE-PERIMEE")
    observations, growth_tete = _growth(cnx, arguments["growth_tete"])
    versions = programmes.get(arguments["programme_id"], [])
    if nom == "proposer":
        revision = len(versions)
        dernier_hash = versions[-1]["proposition"]["empreinte"] if versions else None
        if revision != arguments["revision_attendue"] or dernier_hash != arguments["empreinte_revision_attendue"]:
            raise ValueError("CMO-REVISION-PERIMEE")
        if projection is None or empreinte(projection) != arguments["projection_attendue"]:
            raise ValueError("CMO-PROJECTION-PERIMEE")
        if any(projection["sources_tronquees"].values()):
            raise ValueError("CMO-PROJECTION-TRONQUEE")
        baselines = {}
        p = arguments["parametres"]
        for o in arguments["objectifs"]:
            s = None if o["baseline"] is None else _snapshot(o["baseline"], observations, p["debut"], p["fin"])
            if s is not None and (s["metrique"] != o["metrique"] or s["unite"] != o["unite"]):
                raise ValueError("CMO-BASELINE-UNITE-INCOMPATIBLE")
            baselines[o["objectif_id"]] = s
        charge = {k: arguments[k] for k in ("programme_id", "titre", "hypothese", "parametres", "objectifs", "actions")}
        charge.update(revision=revision + 1, baselines=baselines, growth_tete=growth_tete,
                      empreinte_projection=arguments["projection_attendue"],
                      projection={"version_regles": projection["version_regles"],
                                  "fenetres": [
                                      {k: f[k] for k in ("id", "debut", "fin")} for f in projection["fenetres"]
                                  ]})
    else:
        revision = arguments["revision"]
        if (revision > len(versions)
                or versions[revision - 1]["proposition"]["empreinte"] != arguments["empreinte_revision"]):
            raise ValueError("CMO-REVISION-PERIMEE")
        version = versions[revision - 1]
        initiale = version["proposition"]["charge"]
        if nom == "decider":
            if revision != len(versions) or version["decision"] is not None:
                raise ValueError("CMO-DECISION-DEJA-PRISE-OU-VERSION-ANCIENNE")
            if (projection is None or empreinte(projection) != arguments["projection_attendue"]
                    or arguments["projection_attendue"] != initiale["empreinte_projection"]):
                raise ValueError("CMO-PROJECTION-CHANGEE-REVISER")
            for o in initiale["objectifs"]:
                if o["baseline"] is not None:
                    p = initiale["parametres"]
                    source_actuelle = _snapshot(o["baseline"], observations, p["debut"], p["fin"])
                    if source_actuelle != initiale["baselines"][o["objectif_id"]]:
                        raise ValueError("CMO-BASELINE-CHANGEE-REVISER")
            charge = {k: arguments[k] for k in ("programme_id", "revision", "empreinte_revision", "decision", "motif")}
            charge.update(growth_tete=growth_tete, empreinte_projection=arguments["projection_attendue"])
        else:
            if version["decision"] is None or version["decision"]["charge"]["decision"] != "approuver":
                raise ValueError("CMO-REVUE-VERSION-NON-APPROUVEE")
            charge = {k: arguments[k] for k in (
                "programme_id", "revision", "empreinte_revision", "debut", "fin", "conclusion",
            )}
            charge.update(growth_tete=growth_tete, observations=[
                _snapshot(ref, observations, arguments["debut"], arguments["fin"]) for ref in arguments["observations"]
            ])
    # Une affectation n'accorde aucun droit ni ne garantit la disponibilité du département M4.
    actions_a_verifier = charge["actions"] if nom == "proposer" else initiale["actions"] if nom == "decider" else []
    for action in actions_a_verifier:
        responsable = identite.personne_active(cnx, action["responsable"])
        roles_internes = {"admin", "nathan_owner", "employee", "seller", "manager", "finance"}
        if responsable is None or not responsable.roles.intersection(roles_internes):
            raise ValueError("CMO-RESPONSABLE-INTERNE-INACTIF")
    e = {"schema_version": 1, "type": nom, "charge": charge, "auteur": auteur, "horodatage": horodatage}
    e["empreinte"] = empreinte(e)
    texte = codec.encoder(e)
    _bornes(len(textes) + 1, sum(map(len, textes)) + len(texte), len(texte))
    _autorite(cnx, owner=nom == "decider")
    stockage.maillons(DEPARTEMENT, REGISTRE).append(e, rang_attendu=tete["rang"])
    return {"ok": True, "evenement": e, "statut_source": "DECLAREE_NON_VERIFIEE"}
