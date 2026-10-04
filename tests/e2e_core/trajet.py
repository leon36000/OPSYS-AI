"""Le trajet de l'employé par la porte HTTP du core, et ce que le moteur en garde (PLAN T1.5-b).

Ce module ne connaît du core que ce que l'app en connaît : `GET /opsys/identite` et `POST /tools/invoke`, avec le
jeton de l'appareil. Il ne sait pas si le Gateway en face est le vrai (`scenario.py`) ou la passerelle factice de
`test_repetition_sans_core.py`, qui ne prouve que le script.

Ce que `jouer` vérifie, dans l'ordre :
- l'identité de l'appareil est celle que `opsys-metier appareils appairer` a attribuée ; sans jeton, avec un faux
  jeton ou avec le secret partagé du Gateway, aucune identité ;
- une lecture (`m4_lister_interventions`) rend la donnée préparée, identique à la même lecture faite directement
  au moteur avec le même `_meta` : le core ne retouche pas l'enveloppe ;
- trois gestes d'écriture d'un employé (consentement GPS, en route, arrivée) avec `idempotencyKey` : réponse
  métier reçue telle quelle, exécutée une fois ;
- le `_meta` est arrivé au moteur : la trace « validation au départ » nomme la personne et son rôle, et la ligne
  d'idempotence porte l'appareil, la clé et l'heure de l'appareil ; l'heure du punch est celle du serveur ;
- le rejeu avec la même clé rend `rejoue` sans rien changer à l'état durable ; la même clé pour autre chose est un
  conflit nommé ;
- un outil hors de la portée du rôle donne 403, sans jamais atteindre le moteur.

Chaque appel HTTP est chronométré ; les mesures sont la latence réelle de l'app, du Gateway et du moteur.
La suite de la journée (fichiers, « Terminer », matériaux, propriétaire) est dans `journee.py`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
if str(FIXTURES) not in sys.path:
    sys.path.insert(0, str(FIXTURES))

import anyio  # noqa: E402
from harnais_e2e import DT_TZ, Mesure, Reponse  # noqa: E402
from harnais_e2e_chantier import AppEmploye, Chantier  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
from mcp.shared._httpx_utils import create_mcp_http_client  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from opsys import approbations, stockage  # noqa: E402
from opsys.stockage.schema import APPROBATIONS, JOURNAL, MUTATIONS_APPLIQUEES  # noqa: E402

DELAI_HTTP_S = 60.0
GESTES_ECRITURE = ("m4_definir_consentement_gps", "m4_demarrer_route", "m4_pointer")


class EchecE2E(AssertionError):
    """Un constat du scénario n'est pas vrai : le job doit échouer, avec de quoi comprendre pourquoi."""


def exiger(condition: bool, message: str, **contexte: Any) -> None:
    if not condition:
        detail = json.dumps(contexte, ensure_ascii=False, default=str, indent=2)[:3000] if contexte else ""
        raise EchecE2E(f"{message}\n{detail}".rstrip())


@dataclasses.dataclass(frozen=True)
class Appareil:
    """Un appareil appairé vu de l'app : son identifiant (sha256 de sa clé publique) et son jeton."""

    identifiant: str
    jeton: str
    personne: str
    role: str


# -- le client HTTP de l'app ------------------------------------------------------------------------------
class Passerelle:
    """`GET /opsys/identite` et `POST /tools/invoke`, chronométrés. Aucun mandataire : c'est du local."""

    def __init__(self, url: str, jeton: str, mesures: list[dict[str, Any]] | None = None) -> None:
        self.url = url.rstrip("/")
        self.jeton = jeton
        # Deux appareils peuvent partager la même liste : le tableau des latences garde l'ordre des appels.
        self.mesures: list[dict[str, Any]] = mesures if mesures is not None else []
        self.prefixe_etape = ""  # p. ex. « rejeu : », devant le nom de l'outil dans le journal des latences
        self._ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def demander(
        self, methode: str, chemin: str, corps: dict[str, Any] | None = None, *, jeton: str | None = "",
        etape: str = "",
    ) -> tuple[int, dict[str, Any], float]:
        """`jeton=""` : celui de l'appareil ; `None` : aucun ; autre valeur : celle-là (test d'un faux jeton)."""
        entetes = {"content-type": "application/json"}
        porteur = self.jeton if jeton == "" else jeton
        if porteur is not None:
            entetes["authorization"] = f"Bearer {porteur}"
        requete = urllib.request.Request(
            self.url + chemin, method=methode, headers=entetes,
            data=None if corps is None else json.dumps(corps).encode("utf-8"))
        debut = time.perf_counter()
        try:
            with self._ouvreur.open(requete, timeout=DELAI_HTTP_S) as reponse:
                statut, brut = reponse.status, reponse.read()
        except urllib.error.HTTPError as erreur:
            statut, brut = erreur.code, erreur.read()
        except (urllib.error.URLError, OSError) as erreur:  # `TimeoutError` est un `OSError`
            raise EchecE2E(f"{methode} {self.url}{chemin} : le Gateway ne répond pas ({erreur})") from erreur
        ms = (time.perf_counter() - debut) * 1000
        try:
            contenu = json.loads(brut)
        except ValueError:
            contenu = {"brut": brut.decode("utf-8", "replace")[:500]}
        if not isinstance(contenu, dict):
            contenu = {"brut": contenu}
        self.mesures.append({"etape": etape or f"{methode} {chemin}", "statut": statut, "ms": round(ms, 1)})
        print(f"  {ms:8.1f} ms  {statut}  {etape or f'{methode} {chemin}'}", flush=True)
        return statut, contenu, ms

    def identite(self, *, jeton: str | None = "", etape: str = "identité") -> tuple[int, dict[str, Any]]:
        statut, contenu, _ = self.demander("GET", "/opsys/identite", jeton=jeton, etape=etape)
        return statut, contenu

    def invoquer(
        self, outil: str, args: dict[str, Any], *, cle: str | None = None, horodatage_appareil: str | None = None,
        appareil_id: str | None = None, jeton: str | None = "", etape: str = "",
    ) -> Reponse:
        corps: dict[str, Any] = {"tool": outil, "args": args}
        if cle is not None:
            corps["idempotencyKey"] = cle
        if horodatage_appareil is not None:
            corps["deviceTimestamp"] = horodatage_appareil
        if appareil_id is not None:
            corps["deviceId"] = appareil_id
        statut, contenu, ms = self.demander("POST", "/tools/invoke", corps, jeton=jeton,
                                            etape=etape or f"{self.prefixe_etape}{outil}")
        enveloppe = contenu.get("result") if isinstance(contenu.get("result"), dict) else {}
        mesure = Mesure(outil, statut, ms / 1000, 1, {}, len(json.dumps(contenu)), enveloppe.get("tronque") is True,
                        enveloppe.get("rejoue") if isinstance(enveloppe.get("rejoue"), bool) else None)
        return Reponse(statut, contenu, mesure)


class PorteHttp:
    """Ce que `AppEmploye` attend d'une porte d'appareil, branché sur la vraie porte HTTP du core. Comme le
    vidangeur de l'app (`mobile/src/outbox/vidangeur.ts`), une écriture porte `idempotencyKey`, `deviceId` et
    `deviceTimestamp` ; une lecture n'en porte aucun."""

    def __init__(self, passerelle: Passerelle, appareil_id: str) -> None:
        self._passerelle = passerelle
        self.appareil_id = appareil_id

    def appeler(
        self, outil: str, args: dict[str, Any] | None = None, *, cle: str | None = None,
        horodatage_appareil: str | None = None,
    ) -> Reponse:
        return self._passerelle.invoquer(outil, args or {}, cle=cle, horodatage_appareil=horodatage_appareil,
                                         appareil_id=self.appareil_id if cle is not None else None)


class HorlogeReelle:
    """Le moteur du core tourne sur l'heure réelle : l'app n'avance rien, elle lit l'heure."""

    @property
    def maintenant(self) -> dt.datetime:
        return dt.datetime.now(DT_TZ)

    def avancer(self, **_duree: float) -> dt.datetime:
        return self.maintenant


class _Ecran:
    horloge = HorlogeReelle()


# -- ce que le moteur garde ---------------------------------------------------------------------------------
class EtatDuMoteur:
    """Lecture de la base du moteur (même fichier ou même serveur SQL que le sien) : la preuve que le `_meta` que
    pose le core est arrivé, et que le rejeu n'a rien changé."""

    def traces_au_depart(self) -> list[dict[str, Any]]:
        with stockage.transaction() as cnx:
            lignes = cnx.execute(select(APPROBATIONS).where(
                APPROBATIONS.c.motif_decision == approbations.MOTIF_VALIDATION_AU_DEPART)
                .order_by(APPROBATIONS.c.cree_le)).mappings().all()
        return [dict(ligne) for ligne in lignes]

    def demandes_en_attente(self) -> int:
        with stockage.transaction() as cnx:
            return cnx.execute(select(func.count()).select_from(APPROBATIONS).where(
                APPROBATIONS.c.statut == "en_attente")).scalar_one()

    def mutations(self) -> dict[tuple[str, str], dict[str, Any]]:
        with stockage.transaction() as cnx:
            lignes = cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all()
        return {(ligne["appareil"], ligne["cle_idempotence"]): dict(ligne) for ligne in lignes}

    def journal_au_depart(self) -> list[dict[str, Any]]:
        with stockage.transaction() as cnx:
            lignes = cnx.execute(select(JOURNAL).where(
                JOURNAL.c.action == approbations.ACTION_VALIDATION_AU_DEPART).order_by(JOURNAL.c.id)).mappings().all()
        return [{**ligne, "details": json.loads(ligne["details"])} for ligne in lignes]

    def empreinte(self) -> dict[str, Any]:
        """Ce qu'un rejeu ne doit jamais changer."""
        with stockage.transaction() as cnx:
            compte = {nom: cnx.execute(select(func.count()).select_from(table)).scalar_one()
                      for nom, table in (("approbations", APPROBATIONS), ("mutations", MUTATIONS_APPLIQUEES),
                                         ("journal", JOURNAL))}
        return {**compte, "traces": [t["id"] for t in self.traces_au_depart()]}


@dataclasses.dataclass(frozen=True)
class LectureDirecte:
    """Le moteur, appelé sans le core avec le `_meta` que le core pose : l'étalon de « reçu tel quel »."""

    url_departement: str  # ex. http://127.0.0.1:8765/mcp/v1/m04-field-ops
    jeton_mcp: str

    def lire(self, outil: str, args: dict[str, Any], appareil: Appareil) -> dict[str, Any]:
        meta = {"opsys/personne": appareil.personne, "opsys/role": appareil.role}

        async def _appel() -> str:
            client = create_mcp_http_client(headers={"Authorization": f"Bearer {self.jeton_mcp}"})
            async with (client, streamable_http_client(self.url_departement, http_client=client) as flux,
                        ClientSession(flux[0], flux[1]) as session):
                await session.initialize()
                resultat = await session.call_tool(outil, args, meta=meta)
            exiger(len(resultat.content) == 1, "le moteur doit répondre un seul bloc texte", contenu=str(resultat))
            return resultat.content[0].text

        return json.loads(anyio.run(_appel))


# -- avant l'attribution --------------------------------------------------------------------------------------
def verifier_avant_attribution(passerelle: Passerelle) -> None:
    """L'appareil est approuvé par le core (il a un jeton valide) mais `opsys-metier appareils appairer` ne l'a pas
    encore attribué : le core ne lui donne ni identité ni outil (fermé par défaut)."""
    statut, contenu = passerelle.identite(etape="identité avant attribution")
    exiger(statut == 403 and contenu.get("error", {}).get("reason") == "device_unknown",
           "un appareil sans attribution ne doit avoir aucune identité (403 device_unknown)", statut=statut,
           corps=contenu)
    refus = passerelle.invoquer("m4_lister_interventions", {}, etape="outil avant attribution")
    exiger(refus.statut == 403 and "device_unknown" in refus.corps.get("error", {}).get("message", ""),
           "un appareil sans attribution ne doit appeler aucun outil (403 device_unknown)",
           statut=refus.statut, corps=refus.corps)


# -- le trajet ------------------------------------------------------------------------------------------------
def _sans_rejoue(enveloppe: dict[str, Any]) -> dict[str, Any]:
    return {cle: valeur for cle, valeur in enveloppe.items() if cle != "rejoue"}


def jouer(
    passerelle: Passerelle, appareil: Appareil, chantier: Chantier, base: EtatDuMoteur, direct: LectureDirecte,
    *, secret_partage: str, app: AppEmploye | None = None,
) -> list[dict[str, Any]]:
    """Le trajet complet ; rend les mesures de latence de chaque appel. Lève `EchecE2E` au premier constat faux.
    `app` : l'app de l'employé, si l'appelant la garde pour la suite de la journée (`journee.py`) ; les clés
    d'idempotence déjà employées ne sont alors jamais réutilisées."""
    # -- l'identité que l'app apprend -------------------------------------------------------------------
    statut, contenu = passerelle.identite()
    exiger(statut == 200 and contenu.get("ok") is True and contenu.get("identite") == {
        "appareilId": appareil.identifiant, "personne": appareil.personne, "role": appareil.role},
        "GET /opsys/identite doit rendre la personne et le rôle attribués", statut=statut, corps=contenu)
    for jeton, quoi in ((None, "sans jeton"), ("jeton-faux-e2e-fictif", "avec un faux jeton")):
        refus, corps = passerelle.identite(jeton=jeton, etape=f"identité {quoi}")
        exiger(refus == 401 and "identite" not in corps, f"l'identité ne doit pas être rendue {quoi} (401)",
               statut=refus, corps=corps)
    refus, corps = passerelle.identite(jeton=secret_partage, etape="identité avec le secret partagé")
    exiger(refus == 403 and corps.get("error", {}).get("reason") == "device_required",
           "le secret partagé n'a aucune identité d'appareil (403 device_required)", statut=refus, corps=corps)

    # -- une lecture, reçue telle quelle --------------------------------------------------------------------
    app = app or AppEmploye(_Ecran(), PorteHttp(passerelle, appareil.identifiant), chantier)
    lecture = app.chantiers_du_jour()
    exiger(lecture.statut == 200 and lecture.ok and lecture.enveloppe.get("ok") is True,
           "m4_lister_interventions doit répondre 200 avec une enveloppe OPSYS ok", statut=lecture.statut,
           corps=lecture.corps)
    interventions = lecture.metier
    exiger(isinstance(interventions, list) and [i.get("intervention_id") for i in interventions] == [
        chantier.intervention_id], "la lecture doit rendre l'intervention préparée, et elle seule",
        attendu=chantier.intervention_id, obtenu=interventions)
    etalon = direct.lire("m4_lister_interventions", {}, appareil)
    exiger(lecture.enveloppe == etalon, "l'enveloppe rendue par le core doit être celle du moteur, sans retouche",
           par_le_core=lecture.enveloppe, par_le_moteur=etalon)

    # -- les gestes d'écriture, avec clé d'idempotence -------------------------------------------------------
    avant_traces = len(base.traces_au_depart())
    consentement = app.donner_consentement_gps()
    route = app.en_route()
    avant_punch = dt.datetime.now(dt.UTC)
    arrivee = app.pointer("arrivee")
    apres_punch = dt.datetime.now(dt.UTC)
    for geste in (consentement, route, arrivee):
        exiger(geste.statut == 200 and geste.ok and geste.enveloppe.get("ok") is True
               and geste.enveloppe.get("rejoue") is False and geste.metier.get("accepte") is True,
               "un geste d'écriture doit être accepté par le moteur et exécuté une fois", statut=geste.statut,
               corps=geste.corps)
    punch = arrivee.resultat
    exiger(punch.get("statut") == "sur_site" and punch.get("gps_coherent") is True,
           "l'arrivée doit être sur le site (GPS cohérent avec le référentiel)", punch=punch)
    envoye = app.appels[-1].horodatage_appareil
    exiger(punch.get("horodatage_appareil") == envoye and punch.get("horodatage") != envoye,
           "l'heure de l'appareil (`opsys/horodatageAppareil`) doit rester lisible sans faire foi", punch=punch,
           envoye=envoye)
    recu = dt.datetime.fromisoformat(punch["horodatage"])
    exiger(avant_punch <= recu <= apres_punch, "le punch doit porter l'heure de réception du serveur",
           recu=str(recu), fenetre=[str(avant_punch), str(apres_punch)])
    statut_m4 = app.statut()
    exiger(statut_m4.statut == 200 and statut_m4.ok and statut_m4.resultat.get("statut") == "sur_site",
           "le statut de l'intervention doit refléter l'arrivée, lu par la même porte", corps=statut_m4.corps)

    # -- le `_meta` est arrivé au moteur ----------------------------------------------------------------------
    traces = base.traces_au_depart()[avant_traces:]
    exiger([t["outil"] for t in traces] == list(GESTES_ECRITURE),
           "chaque geste doit laisser une trace « validation au départ »", traces=[t["outil"] for t in traces])
    for trace in traces:
        exiger(trace["decide_par"] == appareil.personne and trace["decide_role"] == appareil.role
               and trace["statut"] == "executee" and trace["niveau"] == "N3",
               "la trace doit nommer la personne authentifiée par le core et son rôle", trace=trace)
    exiger(base.demandes_en_attente() == 0, "aucun geste de l'employé ne doit attendre le propriétaire")
    journal = [j for j in base.journal_au_depart() if j["par"] == appareil.personne]
    exiger({j["details"]["appareil"] for j in journal} == {appareil.identifiant},
           "le journal doit porter l'appareil (`opsys/appareil`)", journal=journal)
    mutations = base.mutations()
    for appel in app.appels:
        ligne = mutations.get((appareil.identifiant, appel.cle))
        exiger(ligne is not None and ligne["outil"] == appel.outil and ligne["horodatage_appareil"]
               == appel.horodatage_appareil and ligne["statut"] == "ok",
               "l'idempotence doit connaître l'appareil, la clé et l'heure de l'appareil", cle=appel.cle, ligne=ligne)

    # -- le rejeu ne change rien -----------------------------------------------------------------------------
    avant = base.empreinte()
    passerelle.prefixe_etape = "rejeu : "
    for appel in app.appels:
        rejeu = app.rejouer(appel)
        exiger(rejeu.statut == 200 and rejeu.enveloppe.get("rejoue") is True
               and _sans_rejoue(rejeu.enveloppe) == _sans_rejoue(appel.reponse.enveloppe),
               "le rejeu avec la même clé doit rendre la réponse enregistrée (`rejoue`)", outil=appel.outil,
               rejeu=rejeu.corps, initial=appel.reponse.corps)
    passerelle.prefixe_etape = ""
    exiger(base.empreinte() == avant, "le rejeu ne doit rien changer à l'état durable", avant=avant,
           apres=base.empreinte())
    dernier = next(a for a in app.appels if a.outil == "m4_pointer")
    conflit = passerelle.invoquer("m4_pointer", {**dernier.args, "action": "pause_debut"}, cle=dernier.cle,
                                  horodatage_appareil=dernier.horodatage_appareil,
                                  etape="clé réutilisée pour autre chose")
    exiger(conflit.statut == 200 and conflit.enveloppe.get("ok") is False
           and conflit.enveloppe.get("erreur") == "mutation_conflit",
           "la même clé pour un autre appel doit être un conflit nommé, rien d'exécuté", corps=conflit.corps)
    exiger(base.empreinte() == avant, "un conflit ne doit rien changer à l'état durable")

    # -- ce que le rôle n'a pas le droit d'appeler ---------------------------------------------------------------
    for outil in ("m9_lister_demandes_approbation", "m9_decider_demande_approbation", "outil_qui_n_existe_pas"):
        refus = passerelle.invoquer(outil, {}, etape=f"hors portée : {outil}")
        erreur = refus.corps.get("error", {})
        exiger(refus.statut == 403 and refus.ok is False and erreur.get("type") == "tool_call_blocked"
               and "tool_out_of_scope" in erreur.get("message", ""),
               "un outil hors de la portée du rôle doit être refusé par le core (403 tool_out_of_scope)", outil=outil,
               statut=refus.statut, corps=refus.corps)
    autre = passerelle.invoquer("m4_lister_interventions", {}, appareil_id="0" * 64,
                                etape="deviceId d'un autre appareil")
    exiger(autre.statut == 403 and "does not match" in autre.corps.get("error", {}).get("message", ""),
           "un deviceId du corps différent de l'appareil authentifié doit être refusé (403)", corps=autre.corps)
    sans_jeton = passerelle.invoquer("m4_lister_interventions", {}, jeton=None, etape="outil sans jeton")
    exiger(sans_jeton.statut == 401 and sans_jeton.ok is False, "/tools/invoke sans jeton doit être refusé (401)",
           statut=sans_jeton.statut, corps=sans_jeton.corps)
    exiger(base.empreinte() == avant, "aucun refus ne doit avoir atteint le moteur")
    return passerelle.mesures


def resume_latences(mesures: list[dict[str, Any]]) -> str:
    """Tableau Markdown des latences, pour le journal du job et `$GITHUB_STEP_SUMMARY`."""
    lignes = ["| Appel | HTTP | Latence (ms) |", "|---|---|---|"]
    lignes += [f"| {m['etape']} | {m['statut']} | {m['ms']} |" for m in mesures]
    valeurs = sorted(m["ms"] for m in mesures)
    if valeurs:
        mediane = valeurs[len(valeurs) // 2]
        lignes.append(f"| **{len(valeurs)} appels** : médiane {mediane}, max {valeurs[-1]} |  |  |")
    return "\n".join(lignes)

