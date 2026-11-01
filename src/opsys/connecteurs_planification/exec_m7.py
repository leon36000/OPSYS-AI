"""Les exécuteurs de M7 : brouillons WordPress, publications WordPress approuvées, publications sociales approuvées.

Les exécuteurs de M7 existaient (`m7_marketing.wordpress.executeur`, `m7_marketing.sas_social.executeur`) mais aucun
planificateur ne les appelait. Ce module les raccorde SANS rien y changer : il choisit QUOI faire passer et dans quel
ordre, sous bail, et laisse les exécuteurs de M7 faire leurs propres contrôles (ils revérifient tout au point de
sortie).

- `m7.wordpress.brouillons` (N2) : transmet au site les brouillons d'article (statut `draft` ou `pending` : le client et
  le plugin refusent le reste) ; trois échecs de transmission écartent un brouillon du tour jusqu'à sa révision.
- `m7.wordpress.publication` (N3, approbation consommée) : une approbation de la direction, non expirée, jamais déjà
  utilisée, pour l'empreinte actuelle, devient UN jeton signé ; une approbation expirée ferme la publication en échec
  SANS toucher au site ; une réponse perdue (jeton émis, ni publiée ni échec) se réconcilie en relisant le site,
  jamais en renvoyant un jeton.
- `m7.social.publication` (N3/N4, approbation consommée) : les publications APPROUVÉES et planifiées, à leur heure, dans
  la fenêtre et le quota ; un échec transitoire se reprend (bornée) ; une publication d'issue incertaine est
  d'abord RETROUVÉE par le réseau avant tout nouvel envoi.

Les ports (client WordPress, adaptateurs de réseaux, secrets) sont injectés. Sans eux : `non raccordé`, rien ne part.
Aucun transport WordPress ni aucun adaptateur de réseau réel n'existe dans cette version.
"""

from __future__ import annotations

from typing import Any

from .. import evenements, stockage
from .. import service_acteur_systeme as systeme
from . import journal
from .bail import Bail
from .planificateur import RefusExecuteur

TYPE_FAITE = "m7.publication_faite"
TYPE_ECHOUEE = "m7.publication_echouee"
PRODUCTEUR = "m07-marketing"
TRANSMISSIONS_ECHOUEES_MAX = 3
_REGISTRES = {
    "sites": ("m07-marketing", "sites_wordpress"),
    "wp": ("m07-marketing", "publications_wordpress"),
    "comptes": ("m07-marketing", "comptes_sociaux"),
    "social": ("m07-marketing", "publications_sociales"),
}


def _m7():
    """Les modules de M7, importés à la demande (le département peut être absent de l'instance)."""
    try:
        from m7_marketing import journal_chaine
        from m7_marketing.sas_social import comptes, etats, garde_fous, modele, politique
        from m7_marketing.sas_social import executeur as exec_social
        from m7_marketing.sas_social import service as service_social
        from m7_marketing.wordpress import executeur as exec_wp
        from m7_marketing.wordpress import flux, sites
    except ImportError:
        raise RefusExecuteur("REJ-PLAN-M7-ABSENT") from None
    return {"journal_chaine": journal_chaine, "comptes": comptes, "etats": etats, "garde_fous": garde_fous,
            "modele": modele, "politique": politique, "exec_social": exec_social,
            "service_social": service_social, "exec_wp": exec_wp, "flux": flux, "sites": sites}


def _journal(cle: str):
    return stockage.maillons(*_REGISTRES[cle])


def _charger_wp(m7):
    tous, refus = m7["flux"].charger(_journal("wp"))
    if refus is not None:
        raise RefusExecuteur(refus["refus"][0]["code"])
    return tous


def _charger_social(m7):
    tous, refus = m7["service_social"].charger(_journal("social"))
    if refus is not None:
        raise RefusExecuteur(refus["refus"][0]["code"])
    return tous


def _evenement(type_evenement: str, charge: dict[str, Any], identifiant: str) -> None:
    with stockage.transaction():
        evenements.publier(type_evenement, PRODUCTEUR, charge, evenement_id=identifiant)


def _echec_derniere(etat: Any) -> tuple[str, bool, bool]:
    erreur = etat.derniere_erreur or {}
    return str(erreur.get("code") or "REJ-PLAN-ECHEC"), bool(erreur.get("transitoire", False)), bool(
        getattr(etat, "incertain", False))


class _WordPressBase:
    nom = ""

    def cle_bail(self, ressource: str) -> str:
        return f"m7.wp:{ressource}"

    def _par_site(self, ctx: Any, etat_voulu: str, filtre=lambda e, m7: True) -> dict[str, list[Any]]:
        m7 = _m7()
        sites_actifs = m7["sites"].actifs(_journal("sites"))
        parsite: dict[str, list[Any]] = {}
        for pub in _charger_wp(m7).values():
            if pub.etat == etat_voulu and pub.site_id in sites_actifs and filtre(pub, m7):
                parsite.setdefault(pub.site_id, []).append(pub)
        return parsite

    def _client(self, ctx: Any, site_id: str):
        m7 = _m7()
        site = m7["sites"].actifs(_journal("sites")).get(site_id)
        if site is None or ctx.ports.client_wordpress is None:
            raise RefusExecuteur("REJ-PLAN-WORDPRESS-NON-RACCORDE")
        client = ctx.ports.client_wordpress(site)
        if client is None:
            raise RefusExecuteur("REJ-PLAN-WORDPRESS-NON-RACCORDE")
        return m7, client


class TransmissionWordPress(_WordPressBase):
    nom = "m7.wordpress.brouillons"

    def _filtre(self, pub: Any, m7: Any) -> bool:
        echecs = m7["journal_chaine"].de_type(_journal("wp"), m7["flux"].M_TRANSMISSION_ECHEC)
        return sum(1 for m in echecs if m.get("publication_id") == pub.publication_id) < TRANSMISSIONS_ECHOUEES_MAX

    def ressources(self, ctx: Any) -> list[str]:
        return sorted(self._par_site(ctx, "brouillon", self._filtre))

    def constater(self, ressource: str, ctx: Any) -> dict[str, Any]:
        n = len(self._par_site(ctx, "brouillon", self._filtre).get(ressource, []))
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=f"wp:{ressource}"[:160],
                                mode="ombre", details={"aurait": n})
        return {"aurait": n}

    def traiter(self, ressource: str, ctx: Any, bail: Bail) -> dict[str, Any]:
        m7, client = self._client(ctx, ressource)
        transmis = erreurs = 0
        code = None
        courant = bail
        for pub in self._par_site(ctx, "brouillon", self._filtre).get(ressource, []):
            courant = ctx.exiger_actif(courant)
            resultat = m7["exec_wp"].transmettre_brouillon(_journal("wp"), pub.publication_id, client,
                                                           ctx.maintenant_dt())
            if resultat.get("accepte"):
                transmis += 1
            else:
                erreurs += 1
                code = resultat["refus"][0]["code"]
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=f"wp:{ressource}"[:160],
                                mode="actif", statut="erreur" if erreurs else "ok", code=code,
                                details={"transmis": transmis, "erreurs": erreurs})
        return {"transmis": transmis, "erreurs": erreurs, "code": code}


class PublicationWordPress(_WordPressBase):
    nom = "m7.wordpress.publication"

    def ressources(self, ctx: Any) -> list[str]:
        return sorted(self._par_site(ctx, "approuve"))

    def constater(self, ressource: str, ctx: Any) -> dict[str, Any]:
        m7 = _m7()
        partiraient = expires = reconcilier = 0
        for pub in self._par_site(ctx, "approuve").get(ressource, []):
            if pub.jeton_emis:
                reconcilier += 1
            elif isinstance(m7["flux"].approbation_verifiee(_journal("wp"), pub.publication_id, ctx.maintenant_dt()),
                            dict):
                expires += 1
            else:
                partiraient += 1
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=f"wp:{ressource}"[:160],
                                mode="ombre", details={"aurait": partiraient, "expires": expires,
                                                       "reconcilies": reconcilier})
        return {"aurait": partiraient, "expires": expires, "reconcilies": reconcilier}

    def _apres(self, m7: Any, pub: Any, ressource: str) -> None:
        nouvel = _charger_wp(m7).get(pub.publication_id)
        if nouvel is None:
            return
        if nouvel.etat == "publie":
            _evenement(TYPE_FAITE, {"canal": "wordpress", "publication_id": pub.publication_id, "cible": ressource,
                                    "id_externe": None if nouvel.post_id is None else str(nouvel.post_id),
                                    "lien_public": nouvel.lien_public, "retrouvee": False},
                       f"m7-publication-faite-wp-{pub.publication_id}")
        elif nouvel.etat == "echec":
            code, transitoire, incertain = _echec_derniere(nouvel)
            _evenement(TYPE_ECHOUEE, {"canal": "wordpress", "publication_id": pub.publication_id, "cible": ressource,
                                      "code": code, "transitoire": transitoire, "resultat_incertain": incertain},
                       f"m7-publication-echouee-wp-{pub.publication_id}-{code[:40]}")

    def traiter(self, ressource: str, ctx: Any, bail: Bail) -> dict[str, Any]:
        m7, client = self._client(ctx, ressource)
        flux, executeur = m7["flux"], m7["exec_wp"]
        publies = expires = reconcilies = erreurs = 0
        code = None
        courant = bail
        for pub in self._par_site(ctx, "approuve").get(ressource, []):
            courant = ctx.exiger_actif(courant)
            maintenant = ctx.maintenant_dt()
            horodatage = m7["modele"].en_instant(maintenant)
            if pub.jeton_emis:
                # Réponse perdue : on relit le site, on ne renvoie JAMAIS un jeton.
                resultat = executeur.reconcilier(_journal("wp"), pub.publication_id, client, maintenant)
                reconcilies += 1
                erreurs += 0 if resultat.get("accepte") else 1
                self._apres(m7, pub, ressource)
                continue
            verifiee = flux.approbation_verifiee(_journal("wp"), pub.publication_id, maintenant)
            if isinstance(verifiee, dict):
                # Approbation absente, expirée ou ne correspondant plus au brouillon : AUCUN jeton n'est émis, le site
                # n'est pas touché ; la publication retombe en échec (une nouvelle revue et une nouvelle approbation).
                refus = verifiee["refus"][0]
                # Instantané de début de tour : si la publication n'est plus « approuvée » (annulée, publiée par un
                # autre exécuteur), rien n'est écrit et rien n'est compté.
                if flux.consigner_echec(_journal("wp"), pub.publication_id, refus["code"], refus["detail"], horodatage):
                    expires += 1
                    code = refus["code"]
                self._apres(m7, pub, ressource)
                continue
            resultat = executeur.publier(_journal("wp"), pub.publication_id, client, maintenant)
            if resultat.get("accepte"):
                publies += 1
            else:
                erreurs += 1
                code = resultat["refus"][0]["code"]
            self._apres(m7, pub, ressource)
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=f"wp:{ressource}"[:160],
                                mode="actif", statut="erreur" if erreurs else "ok", code=code,
                                details={"publies": publies, "expires": expires, "reconcilies": reconcilies,
                                         "erreurs": erreurs})
        return {"publies": publies, "expires": expires, "reconcilies": reconcilies, "erreurs": erreurs, "code": code}


class PublicationSociale:
    nom = "m7.social.publication"

    def cle_bail(self, ressource: str) -> str:
        return f"m7.social:{ressource}"

    def _a_traiter(self) -> dict[str, list[Any]]:
        m7 = _m7()
        comptes_actifs = m7["comptes"].actifs(_journal("comptes"))
        parcompte: dict[str, list[Any]] = {}
        for pub in _charger_social(m7).values():
            reprenable = pub.etat == "echec" and (pub.derniere_erreur or {}).get("transitoire") is True
            if (pub.etat == "planifie" or reprenable) and (pub.reseau, pub.compte) in comptes_actifs:
                parcompte.setdefault(f"{pub.reseau}:{pub.compte}", []).append(pub)
        for liste in parcompte.values():
            liste.sort(key=lambda p: (p.planifie_le or "", p.publication_id))
        return parcompte

    def ressources(self, ctx: Any) -> list[str]:
        return sorted(self._a_traiter())

    def constater(self, ressource: str, ctx: Any) -> dict[str, Any]:
        m7 = _m7()
        a_traiter = self._a_traiter().get(ressource, [])
        maintenant = ctx.maintenant_dt()
        tolerance = (ctx.ports.politique_sociale or m7["politique"].PolitiqueSas()).tolerance_retard_s
        dues = expirees = 0
        for pub in a_traiter:
            prevu = m7["modele"].instant(pub.planifie_le)
            if maintenant < prevu:
                continue
            if (maintenant - prevu).total_seconds() > tolerance:
                expirees += 1
            else:
                dues += 1
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=f"social:{ressource}"[:160],
                                mode="ombre", details={"aurait": dues, "expires": expirees})
        return {"aurait": dues, "expires": expirees}

    def _apres(self, m7: Any, pub: Any, ressource: str) -> None:
        nouvel = _charger_social(m7).get(pub.publication_id)
        if nouvel is None:
            return
        if nouvel.etat == "publie":
            _evenement(TYPE_FAITE, {"canal": "social", "publication_id": pub.publication_id, "cible": ressource,
                                    "id_externe": nouvel.id_externe, "lien_public": nouvel.url_externe,
                                    "retrouvee": False}, f"m7-publication-faite-social-{pub.publication_id}")
        elif nouvel.etat == "echec":
            code, transitoire, incertain = _echec_derniere(nouvel)
            _evenement(TYPE_ECHOUEE, {"canal": "social", "publication_id": pub.publication_id, "cible": ressource,
                                      "code": code, "transitoire": transitoire, "resultat_incertain": incertain},
                       f"m7-publication-echouee-social-{pub.publication_id}-{code[:30]}-t{nouvel.tentatives}")

    def traiter(self, ressource: str, ctx: Any, bail: Bail) -> dict[str, Any]:
        if ctx.ports.adaptateurs_sociaux is None or ctx.ports.secret_social is None:
            raise RefusExecuteur("REJ-PLAN-SOCIAL-NON-RACCORDE")
        m7 = _m7()
        adaptateurs = ctx.ports.adaptateurs_sociaux()
        politique = ctx.ports.politique_sociale or m7["politique"].PolitiqueSas()
        comptes_actifs = m7["comptes"].actifs(_journal("comptes"))
        publies = erreurs = reportees = 0
        code = None
        courant = bail
        for pub in self._a_traiter().get(ressource, []):
            courant = ctx.exiger_actif(courant)
            maintenant = ctx.maintenant_dt()
            horodatage = m7["modele"].en_instant(maintenant)
            secret = ctx.ports.secret_social(comptes_actifs[(pub.reseau, pub.compte)]["secret_nom"])
            if pub.etat == "echec":
                reprise = m7["exec_social"].reprendre(_journal("social"), pub.publication_id, politique, horodatage)
                if not reprise.get("accepte"):
                    continue
            resultat = m7["exec_social"].executer(_journal("social"), pub.publication_id, adaptateurs, secret,
                                                  politique, maintenant)
            if resultat.get("publie"):
                publies += 1
            elif resultat.get("refus") and resultat["refus"][0]["code"] in {
                    m7["exec_social"].REJ_PAS_ENCORE, m7["garde_fous"].REJ_HORS_FENETRE, m7["garde_fous"].REJ_QUOTA}:
                reportees += 1  # rien d'écrit : on réessaie à un prochain passage, dans la fenêtre
            else:
                erreurs += 1
                code = (resultat.get("refus") or [{"code": "REJ-PLAN-ECHEC"}])[0]["code"]
            self._apres(m7, pub, ressource)
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT,
                                ressource=f"social:{ressource}"[:160], mode="actif",
                                statut="erreur" if erreurs else "ok", code=code,
                                details={"publies": publies, "erreurs": erreurs, "ignores": reportees})
        return {"publies": publies, "erreurs": erreurs, "ignores": reportees, "code": code}
