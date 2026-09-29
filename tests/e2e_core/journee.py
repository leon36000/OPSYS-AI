"""La journée de l'employé jusqu'à la décision du propriétaire, par la porte du vrai core (PLAN T1.5-f).

`trajet.jouer` prouve l'identité, une lecture, trois gestes de terrain et les refus. Ici, la suite de la même
journée, avec le même employé (mêmes clés d'idempotence, jamais réutilisées) et un second appareil, celui du
propriétaire (`nathan_owner`, rôle de jeton `admin`) :

- l'employé dépose sa photo par blocs (plus d'un bloc de `TAILLE_BLOC_OCTETS`) et sa signature, pointe son départ
  et touche « Terminer » : le WCT est daté par l'heure du serveur, jamais par le téléphone ;
- le bus livre la complétion ; l'employé remplit le formulaire des matériaux : 56 pi utilisés pour 40 prévus,
  un écart de 40 % au-delà du seuil de 30 % ; le bus livre la variance ;
- le propriétaire lit son écran des approbations : l'alerte d'écart est dans « À voir » (`attentes`) ;
- il ouvre la revue de la complétion (N4, jamais exécutée au départ) puis la décide avec une clé d'idempotence ;
  l'employé, lui, reçoit 403 sur ces outils et n'a rien décidé ;
- la base du moteur dit que la décision est signée par la personne authentifiée par le core (`nathan`, rôle
  `nathan_owner`) et que l'appareil est au journal ; le rejeu de la décision est sans effet, et une seconde
  décision sous une autre clé est refusée (`deja_decidee`) sans rien changer.

Le bus est livré par ce processus (`evenements.repartir`, comme `tests/e2e/`) : le répartiteur de fond du moteur
est éteint (`OPSYS_EVENEMENTS_REPARTITEUR=0`), la livraison est déterministe et le scénario de `trajet.jouer` reste
celui qui a fait ses preuves. Les heures sont celles du serveur, réelles : la journée tient en quelques secondes.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import random
import struct
import sys
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ICI = Path(__file__).resolve().parent
FIXTURES = ICI.parent / "fixtures"
for chemin in (ICI, FIXTURES):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from harnais_e2e import DT_TZ, Reponse, iso  # noqa: E402
from harnais_e2e_chantier import (  # noqa: E402
    MATERIAU_ID,
    Appel,
    AppEmploye,
    Chantier,
    png_minimal,
    receptionner_materiel_args,
)
from m4_field_ops import encodage as m4_encodage  # noqa: E402
from m6_material_control import registre as m6_registre  # noqa: E402
from m6_material_control import stock as m6_stock  # noqa: E402
from sqlalchemy import select  # noqa: E402
from trajet import (  # noqa: E402
    Appareil,
    EtatDuMoteur,
    Passerelle,
    PorteHttp,
    _Ecran,
    exiger,
)

from opsys import evenements, fichiers, stockage  # noqa: E402
from opsys.departements import Departement  # noqa: E402
from opsys.stockage import codec  # noqa: E402
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, JOURNAL  # noqa: E402

QUANTITE_DECLAREE = 56.0  # prévu : 40 pi. +40 %, au-delà du seuil de 30 % de M6
ROLE_SIGNATAIRE = "nathan_owner"
# Les noms de clés que lit l'app (`mobile/src/approbations/contrat.ts`), épinglés aussi par `tests/e2e/`.
CLES_ECRAN = {"demandes", "total_en_attente", "affichees", "reste", "proprietaire",
              "attentes", "total_attentes", "attentes_affichees", "attentes_reste", "attentes_illisibles"}
CLES_ATTENTE = {"type", "id", "departement", "departement_nom", "resume", "niveau", "depuis", "action_proposee"}


# -- un fichier assez gros pour plusieurs blocs ---------------------------------------------------------------
def png_volumineux(octets_min: int, graine: int = 20260929) -> bytes:
    """PNG réel (signature, IHDR, IDAT, IEND, CRC corrects) d'au moins `octets_min` octets, de quoi remplir plus d'un
    bloc. Contenu pseudo-aléatoire, compression « stockée » : la taille ne dépend pas de zlib."""
    def bloc(etiquette: bytes, donnees: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(etiquette + donnees))
        return struct.pack(">I", len(donnees)) + etiquette + donnees + crc

    largeur = octets_min // 3 + 1
    ligne = b"\x00" + random.Random(graine).randbytes(3 * largeur)
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, 1, 8, 2, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(ligne, 0)) + bloc(b"IEND", b""))


class AppEmployeReelle(AppEmploye):
    """`AppEmploye` de T1.5, avec le dépôt d'un fichier par plusieurs blocs, comme la file sortante de l'app."""

    def deposer_par_blocs(self, contenu: bytes) -> str:
        """Un fichier en `n` blocs de taille fixe (le dernier peut être plus court), un appel par bloc, chacun avec sa
        clé. Seul le dernier le déclare complet ; rend sa référence stable (`fichier:sha256:<hex>`)."""
        taille_bloc = fichiers.TAILLE_BLOC_OCTETS
        nombre = -(-len(contenu) // taille_bloc)
        exiger(nombre >= 2, "le fichier de l'essai doit tenir en plusieurs blocs", octets=len(contenu))
        empreinte = hashlib.sha256(contenu).hexdigest()
        reference = None
        for index in range(nombre):
            morceau = contenu[index * taille_bloc:(index + 1) * taille_bloc]
            reponse = self._envoyer("m4_deposer_fichier", {
                "empreinte_sha256": empreinte, "taille_octets": len(contenu), "type_mime": "image/png",
                "index_bloc": index, "nombre_blocs": nombre, "bloc_base64": base64.b64encode(morceau).decode("ascii")})
            exiger(reponse.statut == 200 and reponse.ok and reponse.enveloppe.get("ok") is True
                   and reponse.metier.get("accepte") is True and reponse.enveloppe.get("rejoue") is False,
                   "chaque bloc doit être accepté et exécuté une fois", bloc=index, statut=reponse.statut,
                   corps=reponse.corps)
            complet = reponse.resultat.get("complet")
            exiger(complet is (index == nombre - 1),
                   "seul le dernier bloc doit rendre le fichier complet", bloc=index, sur=nombre, complet=complet)
            reference = reponse.resultat.get("reference")
        exiger(reference == fichiers.reference_pour(empreinte),
               "la référence doit être l'empreinte SHA-256 du contenu complet", reference=reference)
        return reference


def creer_app_employe(passerelle: Passerelle, appareil: Appareil, chantier: Chantier) -> AppEmployeReelle:
    return AppEmployeReelle(_Ecran(), PorteHttp(passerelle, appareil.identifiant), chantier)


class AppProprietaire:
    """Le téléphone du propriétaire : ses écritures portent une clé, l'heure et l'identifiant de l'appareil, comme
    le vidangeur de l'app ; ses lectures rien."""

    def __init__(self, passerelle: Passerelle, appareil: Appareil) -> None:
        self.passerelle = passerelle
        self.appareil = appareil
        self.appels: list[Appel] = []
        self.lectures: list[Reponse] = []

    def envoyer(self, outil: str, args: dict[str, Any], *, cle: str | None = None) -> Appel:
        cle = cle or f"mut-proprietaire-{len(self.appels) + 1:02d}"
        heure = iso(dt.datetime.now(DT_TZ), -300)
        reponse = self.passerelle.invoquer(outil, args, cle=cle, horodatage_appareil=heure,
                                           appareil_id=self.appareil.identifiant)
        appel = Appel(outil, args, cle, heure, reponse)
        self.appels.append(appel)
        return appel

    def rejouer(self, appel: Appel) -> Reponse:
        return self.passerelle.invoquer(appel.outil, appel.args, cle=appel.cle,
                                        horodatage_appareil=appel.horodatage_appareil,
                                        appareil_id=self.appareil.identifiant, etape=f"rejeu : {appel.outil}")

    def ecran(self) -> dict[str, Any]:
        """L'écran des approbations : `m9_lister_demandes_approbation`."""
        reponse = self.passerelle.invoquer("m9_lister_demandes_approbation", {})
        exiger(reponse.statut == 200 and reponse.ok and reponse.enveloppe.get("ok") is True
               and not (isinstance(reponse.metier, dict) and reponse.metier.get("accepte") is False),
               "l'écran des approbations doit répondre au propriétaire", statut=reponse.statut, corps=reponse.corps)
        self.lectures.append(reponse)
        return reponse.resultat


# -- ce que le moteur garde, en plus de `EtatDuMoteur` -------------------------------------------------------------
class EtatDeLaJournee(EtatDuMoteur):
    def evenements(self, type_evenement: str) -> list[dict[str, Any]]:
        with stockage.transaction() as cnx:
            lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
                EVENEMENTS_SORTANTS.c.type_evenement == type_evenement).order_by(EVENEMENTS_SORTANTS.c.cree_le)).all()
        return [{"evenement_id": ligne.evenement_id, **codec.decoder(ligne.charge)} for ligne in lignes]

    def recus(self, evenement_id: str) -> dict[str, str]:
        with stockage.transaction() as cnx:
            lignes = cnx.execute(select(EVENEMENTS_RECUS.c.consommateur, EVENEMENTS_RECUS.c.statut).where(
                EVENEMENTS_RECUS.c.evenement_id == evenement_id)).all()
        return {ligne.consommateur: ligne.statut for ligne in lignes}

    def recus_non_traites(self) -> list[tuple[str, str, str]]:
        with stockage.transaction() as cnx:
            lignes = cnx.execute(select(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.consommateur,
                                        EVENEMENTS_RECUS.c.statut).where(EVENEMENTS_RECUS.c.statut != "traite")).all()
        return [tuple(ligne) for ligne in lignes]

    def demande(self, identifiant: str) -> dict[str, Any] | None:
        with stockage.transaction() as cnx:
            ligne = cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == identifiant)).mappings().fetchone()
        return None if ligne is None else dict(ligne)

    def maillon_de_completion(self, wct_id: str) -> dict[str, Any]:
        """Le maillon du registre de M4 qui porte le WCT : `horodatage` est celui qui a daté « Terminer »."""
        with stockage.transaction():
            maillons = list(stockage.maillons("m04-field-ops", "principal"))
        trouves = [m for m in maillons if isinstance(m.get("wct"), dict) and m["wct"].get("wct_id") == wct_id]
        exiger(len(trouves) == 1, "le registre de M4 doit porter exactement un maillon pour ce WCT", wct_id=wct_id,
               trouves=len(trouves))
        return trouves[0]

    def journal(self, action: str, cible: str) -> list[dict[str, Any]]:
        with stockage.transaction() as cnx:
            lignes = cnx.execute(select(JOURNAL).where(JOURNAL.c.action == action, JOURNAL.c.cible == cible)
                                 .order_by(JOURNAL.c.id)).mappings().all()
        return [{**ligne, "details": json.loads(ligne["details"])} for ligne in lignes]

    def stock_m6(self, chantier: Chantier) -> float:
        """Stock théorique du matériau sur le chantier, dérivé des mouvements du registre de M6."""
        with stockage.transaction():
            registre = m6_registre.Registre(maillons=stockage.maillons("m06-material-control", "principal"))
            return m6_stock.deriver_stock_theorique(chantier.chantier_id, MATERIAU_ID, registre)


def livrer_le_bus(departements: Mapping[str, Departement], *, max_tours: int = 15, pas_s: int = 90) -> dict[str, int]:
    """Répartiteur réel (`evenements.repartir`, tous les départements) jusqu'au repos, borné : le même que celui du
    moteur, appelé ici parce que celui de fond est éteint. L'heure des réessais avance de `pas_s` par tour."""
    instant = dt.datetime.now(DT_TZ)
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for _ in range(max_tours):
        resume = evenements.repartir(departements, maintenant=iso(instant))
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
        instant += dt.timedelta(seconds=pas_s)
    raise AssertionError(f"le bus n'a pas atteint le repos après {max_tours} tours : {total}")


# -- la journée -------------------------------------------------------------------------------------------------
def _accepte(reponse: Reponse, quoi: str) -> None:
    exiger(reponse.statut == 200 and reponse.ok and reponse.enveloppe.get("ok") is True
           and reponse.enveloppe.get("rejoue") is False and reponse.metier.get("accepte") is True,
           f"{quoi} doit être accepté par le moteur et exécuté une fois", statut=reponse.statut, corps=reponse.corps)


def _statut_de_l_intervention(app: AppEmploye) -> str:
    reponse = app.statut()
    exiger(reponse.statut == 200 and reponse.ok, "m4_statut_intervention doit répondre", corps=reponse.corps)
    return reponse.resultat.get("statut")


def jouer_la_journee(
    passerelle_employe: Passerelle, employe: Appareil, app: AppEmployeReelle, passerelle_proprietaire: Passerelle,
    proprietaire: Appareil, chantier: Chantier, base: EtatDeLaJournee, departements: Mapping[str, Departement],
) -> None:
    """De la photo par blocs à la décision du propriétaire. Lève `EchecE2E` au premier constat faux."""
    ecran = AppProprietaire(passerelle_proprietaire, proprietaire)

    # -- le propriétaire : l'identité que le core lui donne, un écran sans alerte ---------------------------------
    statut, contenu = passerelle_proprietaire.identite(etape="propriétaire : identité")
    exiger(statut == 200 and contenu.get("identite") == {
        "appareilId": proprietaire.identifiant, "personne": proprietaire.personne, "role": proprietaire.role},
        "le second appareil doit avoir l'identité du propriétaire", statut=statut, corps=contenu)
    vide = ecran.ecran()
    exiger(set(vide) == CLES_ECRAN and vide["proprietaire"] is True and vide["demandes"] == []
           and not [a for a in vide["attentes"] if a["type"] in ("completion_en_revue", "chantier_a_reviser")],
           "avant la journée, l'écran du propriétaire ne doit porter aucune alerte d'écart", ecran=vide)

    # -- le matériel arrive au chantier : geste du propriétaire, M6 lit le prévu du devis accepté ---------------
    livrer_le_bus(departements)
    reception = ecran.envoyer("m6_receptionner_commande", receptionner_materiel_args(chantier))
    _accepte(reception.reponse, "la réception du matériel")

    # -- l'employé : photo par blocs, signature, départ, « Terminer » -----------------------------------------------
    photo = app.deposer_par_blocs(png_volumineux(fichiers.TAILLE_BLOC_OCTETS + 20_000))
    signature = app.deposer_fichier(png_minimal(largeur=2))
    avant_depart = dt.datetime.now(dt.UTC)
    _accepte(app.pointer("depart"), "le pointage du départ")
    apres_depart = dt.datetime.now(dt.UTC)
    avant_terminer = dt.datetime.now(dt.UTC)
    terminer = app.terminer(photo, signature)
    apres_terminer = dt.datetime.now(dt.UTC)
    _accepte(terminer, "« Terminer »")
    envoye = app.appels[-1]
    accuse = terminer.resultat
    wct_id = accuse["wct_id"]
    exiger((accuse["statut"], accuse["ecart_signale"]) == ("completed_pending_review", False)
           and accuse["horodatage_appareil"] == envoye.horodatage_appareil,
           "« Terminer » : complétion à vérifier, aucun écart connu de M4, heure de l'appareil lue à côté",
           accuse=accuse)
    (evenement_wct,) = base.evenements("m4.travaux_termines")
    depart = dt.datetime.fromisoformat(evenement_wct["horodatage_completion"])  # dernier départ : heure du serveur
    exiger(evenement_wct["evenement_id"] == wct_id and avant_depart <= depart <= apres_depart,
           "le WCT porte le départ, daté par l'heure de réception du serveur", wct=evenement_wct,
           fenetre=[str(avant_depart), str(apres_depart)])
    completion = base.maillon_de_completion(wct_id)
    recu = dt.datetime.fromisoformat(completion["horodatage"])
    exiger(avant_terminer <= recu <= apres_terminer and completion["horodatage"] != envoye.horodatage_appareil,
           "« Terminer » doit être daté par l'heure de réception du serveur, jamais par le téléphone",
           maillon=completion["horodatage"], appareil=envoye.horodatage_appareil,
           fenetre=[str(avant_terminer), str(apres_terminer)])
    exiger(wct_id == m4_encodage.empreinte("wct", chantier.intervention_id, completion["horodatage"]),
           "le wct_id doit dépendre de l'intervention et de l'heure du serveur, jamais du téléphone", wct_id=wct_id)

    # -- le bus livre la complétion ; le formulaire des matériaux : +40 % ---------------------------------------------
    livrer_le_bus(departements)
    consommateurs = base.recus(wct_id)
    exiger(set(consommateurs.values()) == {"traite"}
           and {"m05-financecore", "m06-material-control"} <= set(consommateurs),
           "chaque consommateur doit avoir traité la complétion", recus=consommateurs)
    declaration = app.declarer_materiaux(wct_id, QUANTITE_DECLAREE)
    _accepte(declaration, "le formulaire des matériaux")
    livrer_le_bus(departements)
    exiger(base.recus_non_traites() == [], "aucun événement ne doit rester en échec ni en quarantaine",
           restes=base.recus_non_traites())
    variance = base.evenements("m6.variance_chantier")[-1]
    exiger((variance["statut_variance"], variance["signal_critique"], variance["seuil_pourcentage"]) == (
        "evaluee", True, 0.3) and variance["lignes"] == [{
            "materiau": MATERIAU_ID, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": "56.0",
            "ecart_pourcentage": "0.4", "critique": True}],
        "M6 doit signaler l'écart critique de 40 % au seuil de 30 %", variance=variance)
    exiger(base.stock_m6(chantier) == 200.0 - QUANTITE_DECLAREE, "le stock doit suivre ce qui a été utilisé",
           stock=base.stock_m6(chantier))
    exiger(_statut_de_l_intervention(app) == "completed_pending_review",
           "un écart critique laisse la complétion en revue : M4 ne vérifie pas seul")

    # -- ce que l'employé a laissé : traces au départ à son nom, fichiers sans trace (N2), une clé par appel ---------
    traces = {t["outil"]: t for t in base.traces_au_depart()}
    exiger({"m4_completer_intervention", "m6_declarer_materiaux_utilises", "m4_pointer"} <= set(traces)
           and "m4_deposer_fichier" not in traces
           and all(traces[o]["decide_par"] == employe.personne for o in (
               "m4_completer_intervention", "m6_declarer_materiaux_utilises", "m4_pointer"))
           and traces["m6_receptionner_commande"]["decide_par"] == proprietaire.personne,
           "chaque geste doit porter le nom de la personne que le core a authentifiée", traces=sorted(traces))
    mutations = base.mutations()
    manquantes = [a.cle for a in app.appels if (employe.identifiant, a.cle) not in mutations]
    exiger(not manquantes, "chaque bloc et chaque geste doit avoir sa ligne d'idempotence", manquantes=manquantes)

    # -- l'alerte d'écart, dans « À voir » du propriétaire ----------------------------------------------------------
    telephone = ecran.ecran()
    exiger(set(telephone) == CLES_ECRAN and telephone["proprietaire"] is True and telephone["attentes_illisibles"] == []
           and all(set(a) == CLES_ATTENTE for a in telephone["attentes"]),
           "l'écran du propriétaire doit avoir la forme que l'app lit", cles=sorted(telephone))
    par_type = {a["type"]: a for a in telephone["attentes"]}
    # `attentes_reste` : ce que l'écran coupe (`BUDGET_ATTENTES`, aucune pagination) ; une alerte coupée n'est pas lue.
    exiger({"completion_en_revue", "chantier_a_reviser"} <= set(par_type) and telephone["attentes_reste"] == 0,
           "l'alerte d'écart doit être dans « À voir », sans qu'aucune attente soit coupée", types=sorted(par_type),
           total=telephone["total_attentes"], affichees=telephone["attentes_affichees"],
           reste=telephone["attentes_reste"], attentes=telephone["attentes"])
    en_revue = par_type["completion_en_revue"]
    exiger(en_revue["id"] == chantier.intervention_id and en_revue["departement"] == "m04-field-ops"
           and en_revue["niveau"] == "N4" and "écart matériaux CRITIQUE signalé par M6" in en_revue["resume"]
           and "m4_resoudre_revue_completion" in en_revue["action_proposee"],
           "la revue de la complétion doit dire l'écart", attente=en_revue)
    a_reviser = par_type["chantier_a_reviser"]
    exiger(a_reviser["id"] == f"variance-{wct_id}" and a_reviser["departement"] == "m05-financecore"
           and "Écart matériaux critique" in a_reviser["resume"] and chantier.chantier_id in a_reviser["resume"],
           "le chantier à réviser doit citer la variance et le chantier", attente=a_reviser)

    # -- le propriétaire ouvre la revue (N4 : jamais au départ), l'employé ne peut rien décider --------------------
    revue = ecran.envoyer("m4_resoudre_revue_completion", {
        "intervention_id": chantier.intervention_id, "decision": "verifiee", "horodatage": iso(dt.datetime.now(DT_TZ)),
        "motif": "Bris de 16 pi constaté sur place et photographié : l'écart est expliqué (fictif)."})
    exiger(revue.reponse.statut == 200 and revue.reponse.enveloppe.get("statut") == "en_attente_approbation",
           "N4 : la revue doit attendre la décision du propriétaire, jamais s'exécuter au départ",
           corps=revue.reponse.corps)
    exiger(_statut_de_l_intervention(app) == "completed_pending_review",
           "rien n'est décidé tant que le propriétaire n'a pas signé")
    file = ecran.ecran()
    exiger(len(file["demandes"]) == 1, "une seule demande doit attendre le propriétaire", demandes=file["demandes"])
    demande = file["demandes"][0]
    exiger((demande["outil"], demande["niveau"], demande["decidable"], demande["arguments"].get("intervention_id")) == (
        "m4_resoudre_revue_completion", "N4", True, chantier.intervention_id),
        "la demande doit être décidable par le propriétaire", demande=demande)
    demande_id = demande["id"]
    for outil, args, cle in (
        ("m9_lister_demandes_approbation", {}, None),
        ("m9_decider_demande_approbation", {"demande_id": demande_id, "decision": "approuver",
                                            "motif": "L'employé ne décide rien (fictif)."}, "mut-employe-decision"),
    ):
        refus = passerelle_employe.invoquer(outil, args, cle=cle, appareil_id=employe.identifiant if cle else None,
                                            horodatage_appareil=iso(dt.datetime.now(DT_TZ), -300) if cle else None,
                                            etape=f"employé hors portée : {outil}")
        erreur = refus.corps.get("error", {})
        exiger(refus.statut == 403 and erreur.get("type") == "tool_call_blocked"
               and "tool_out_of_scope" in erreur.get("message", ""),
               "l'employé doit recevoir 403 sur les outils du propriétaire", outil=outil, statut=refus.statut,
               corps=refus.corps)
    exiger(base.demande(demande_id)["statut"] == "en_attente" and (employe.identifiant, "mut-employe-decision")
           not in base.mutations(), "le refus de l'employé ne doit rien avoir décidé ni atteint le moteur")

    # -- la décision du propriétaire, avec une clé d'idempotence ------------------------------------------------------
    decision = ecran.envoyer("m9_decider_demande_approbation", {
        "demande_id": demande_id, "decision": "approuver", "motif": "Confirmé après vérification du bris (fictif)."})
    _accepte(decision.reponse, "la décision du propriétaire")
    resultat = decision.reponse.resultat
    exiger((resultat["demande_id"], resultat["statut"], resultat["decide_par"], resultat["role"], resultat["outil"],
            resultat["departement"], resultat["niveau"]) == (
        demande_id, "executee", proprietaire.personne, ROLE_SIGNATAIRE, "m4_resoudre_revue_completion",
        "m04-field-ops", "N4") and resultat["issue"]["accepte"] is True,
        "la décision doit être exécutée, signée par la personne authentifiée", resultat=resultat)
    exiger(_statut_de_l_intervention(app) == "completed_verified", "la complétion doit être vérifiée après la décision")
    apres = ecran.ecran()
    exiger("completion_en_revue" not in {a["type"] for a in apres["attentes"]} and apres["total_en_attente"] == 0
           and apres["demandes"] == [], "l'alerte doit quitter la file après la décision", ecran=apres)

    # -- ce que le moteur a gardé : la personne signe, l'appareil est au journal --------------------------------------
    ligne = base.demande(demande_id)
    exiger((ligne["statut"], ligne["decide_par"], ligne["decide_role"], ligne["niveau"], ligne["outil"]) == (
        "executee", proprietaire.personne, ROLE_SIGNATAIRE, "N4", "m4_resoudre_revue_completion"),
        "la demande doit porter la signature de la personne authentifiée, pas celle de l'appareil", demande=ligne)
    (entree,) = base.journal("approbation.approuver", demande_id)
    exiger(entree["par"] == proprietaire.personne and entree["details"].get("appareil") == proprietaire.identifiant
           and entree["details"].get("role") == ROLE_SIGNATAIRE and entree["details"].get("statut") == "executee",
           "le journal doit nommer la personne, son rôle et l'appareil d'où vient la décision", entree=entree)
    trace = base.mutations().get((proprietaire.identifiant, decision.cle))
    exiger(trace is not None and trace["outil"] == "m9_decider_demande_approbation" and trace["statut"] == "ok"
           and trace["horodatage_appareil"] == decision.horodatage_appareil,
           "la décision doit avoir sa ligne d'idempotence (appareil, clé, heure de l'appareil)", ligne=trace)

    # -- le rejeu de la décision est sans effet ---------------------------------------------------------------------
    avant = base.empreinte()
    rejeu = ecran.rejouer(decision)
    exiger(rejeu.statut == 200 and rejeu.enveloppe.get("rejoue") is True
           and {c: v for c, v in rejeu.enveloppe.items() if c != "rejoue"}
           == {c: v for c, v in decision.reponse.enveloppe.items() if c != "rejoue"},
           "le rejeu de la décision doit rendre la réponse enregistrée", rejeu=rejeu.corps)
    exiger(base.empreinte() == avant and base.demande(demande_id) == ligne
           and len(base.journal("approbation.approuver", demande_id)) == 1,
           "le rejeu de la décision ne doit rien changer à l'état durable", avant=avant, apres=base.empreinte())
    encore = ecran.envoyer("m9_decider_demande_approbation", decision.args)
    exiger(encore.reponse.statut == 200 and encore.reponse.metier.get("accepte") is False
           and encore.reponse.metier["verdict"]["code"] == "deja_decidee",
           "une seconde décision sous une autre clé doit être refusée : déjà décidée", corps=encore.reponse.corps)
    exiger(base.demande(demande_id) == ligne and len(base.journal("approbation.approuver", demande_id)) == 1,
           "la seconde décision ne doit rien avoir changé")

    # -- aucune sortie tronquée (`Capacites._tronquer`, au-delà de 6 000 caractères) --------------------------------
    reponses = [a.reponse for a in (*app.appels, *ecran.appels)] + ecran.lectures
    tronquees = [r.mesure.outil for r in reponses if r.mesure.tronque]
    exiger(not tronquees, "aucune réponse ne doit avoir été tronquée : l'app lit ce que le moteur a écrit",
           tronquees=tronquees)


__all__ = ["AppEmployeReelle", "AppProprietaire", "EtatDeLaJournee", "creer_app_employe", "jouer_la_journee",
           "livrer_le_bus", "png_volumineux"]
