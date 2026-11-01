"""Un SITE WORDPRESS SIMULÉ, en Python, qui applique les règles du plugin telles que la spécification les dit.

Ce n'est PAS le plugin : c'est une seconde lecture de la même spécification, écrite pour que le client OPSYS soit exercé
contre un interlocuteur qui REFUSE comme le plugin refuse (signature, rejeu, statut forcé, publication par jeton). La
concordance entre ce simulateur et le vrai code PHP n'est garantie que par (1) les vecteurs partagés, (2) les tests de
contrat sur le texte du plugin (`test_plugin_source_contrat.py`). Le plugin n'a pas été exécuté.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime

from m7_marketing.wordpress.client import ReponseHTTP, RequeteHTTP

BALISES_PERMISES = ("p", "a", "strong", "em", "ul", "ol", "li", "h2", "h3", "br", "blockquote")
MAGIQUES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/gif": b"GIF89a",
}


def kses(html: str) -> str:
    """Simule wp_kses_post : retire les balises hors liste et les attributs d'événement."""

    def balise(m: re.Match) -> str:
        nom = m.group(2).lower()
        if nom not in BALISES_PERMISES:
            return ""
        return f"<{m.group(1)}{nom}>" if not m.group(1) else f"</{nom}>"

    sans_script = re.sub(r"<script.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"<(/?)([A-Za-z0-9]+)[^>]*>", balise, sans_script)


def reponse(statut: int, corps: dict) -> ReponseHTTP:
    return ReponseHTTP(statut=statut, corps=json.dumps(corps).encode())


def erreur(statut: int, code: str, message: str = "refus") -> ReponseHTTP:
    return reponse(statut, {"code": code, "message": message, "data": {"status": statut}})


class SiteSimule:
    def __init__(
        self,
        reference,
        secret: str,
        site_id: str,
        horloge,
        cle_id: str = "default",
        *,
        https: bool = True,
        publication_activee: bool = True,
        agent_sur: bool = True,
    ) -> None:
        self.ref, self.secret, self.site_id, self.horloge, self.cle_id = reference, secret, site_id, horloge, cle_id
        self.https, self.publication_activee, self.agent_sur = https, publication_activee, agent_sur
        self.vus = reference.MemoireUsageUnique()
        self.posts: dict[int, dict] = {}
        self.medias: dict[int, dict] = {}
        self.suivant = 100
        self.requetes: list[RequeteHTTP] = []
        self.statut_force_publish = False  # simule une extension tierce qui tenterait de publier

    # -- empreinte du contenu stocké ---------------------------------------------------------------------------
    def empreinte(self, p: dict) -> str:
        return self.ref.empreinte_contenu(
            {
                "type": p["type"],
                "titre": p["titre"],
                "contenu": p["contenu"],
                "extrait": p["extrait"],
                "slug": p["slug"],
                "image_a_la_une_sha256": p.get("image_sha", ""),
            }
        )

    def modifier_dans_wp_admin(self, post_id: int, **champs) -> None:
        """Un humain (ou une extension) retouche le brouillon dans WordPress : l'empreinte change."""
        self.posts[post_id].update(champs)

    # -- transport ---------------------------------------------------------------------------------------------
    def envoyer(self, requete: RequeteHTTP) -> ReponseHTTP:
        self.requetes.append(requete)
        maintenant = self.horloge()
        if not self.https:
            return erreur(403, "opsys_https_requis")
        m = re.fullmatch(r"https://[^/]+/wp-json(/opsys-connect/v1/[A-Za-z0-9/_-]*)", requete.url)
        if m is None:
            return erreur(404, "rest_no_route")
        route = m.group(1)
        en_tetes = dict(requete.en_tetes)
        plis = {k.lower(): v for k, v in en_tetes.items()}
        if plis.get("x-opsys-key-id") != self.cle_id:
            return erreur(401, "opsys_cle_inconnue")
        verdict = self.ref.verifier_requete(self.secret, requete.methode, route, requete.corps, en_tetes, maintenant)
        if verdict != "OK":
            codes = {
                "EN_TETE_MANQUANT": "opsys_en_tete_manquant",
                "HORODATAGE_INVALIDE": "opsys_horodatage_invalide",
                "NONCE_INVALIDE": "opsys_nonce_invalide",
                "SIGNATURE_MALFORMEE": "opsys_signature_malformee",
                "HORS_FENETRE": "opsys_horodatage_hors_fenetre",
                "SIGNATURE_INVALIDE": "opsys_signature_invalide",
            }
            return erreur(401, codes[verdict])
        if not self.vus.consommer("nonce", plis["x-opsys-nonce"], int(plis["x-opsys-timestamp"]) + 600, maintenant):
            return erreur(401, "opsys_rejeu")
        if not self.agent_sur:
            return erreur(503, "opsys_agent_dangereux")
        try:
            corps = json.loads(requete.corps.decode()) if requete.corps else {}
        except ValueError:
            return erreur(400, "opsys_champ_invalide")
        return self._router(requete.methode, route, corps, maintenant)

    def _router(self, methode: str, route: str, corps: dict, maintenant: int) -> ReponseHTTP:
        if (methode, route) == ("GET", "/opsys-connect/v1/health"):
            return reponse(
                200,
                {
                    "schema": "opsys-connect/v1",
                    "plugin_version": "0.1.0",
                    "wp_version": "6.9",
                    "php_version": "8.3.0",
                    "site_id": self.site_id,
                    "publication_activee": self.publication_activee,
                    "agent_sur": True,
                    "https": True,
                    "heure_serveur": maintenant,
                },
            )
        if (methode, route) == ("GET", "/opsys-connect/v1/types"):
            return reponse(
                200,
                {
                    "types": [
                        {"nom": "post", "libelle": "Articles", "gerable": True, "statuts_permis": ["draft", "pending"]}
                    ]
                },
            )
        if (methode, route) == ("POST", "/opsys-connect/v1/drafts"):
            return self._creer(corps)
        if methode == "PUT" and (m := re.fullmatch(r"/opsys-connect/v1/drafts/([0-9]+)", route)):
            return self._maj(int(m.group(1)), corps)
        if (methode, route) == ("POST", "/opsys-connect/v1/media"):
            return self._media(corps)
        if methode == "GET" and (m := re.fullmatch(r"/opsys-connect/v1/posts/([0-9]+)/state", route)):
            post = self.posts.get(int(m.group(1)))
            return erreur(404, "opsys_non_gere") if post is None else reponse(200, self._etat(int(m.group(1))))
        if methode == "POST" and (m := re.fullmatch(r"/opsys-connect/v1/posts/([0-9]+)/publish", route)):
            return self._publier(int(m.group(1)), corps, maintenant)
        return erreur(404, "rest_no_route")

    # -- gestionnaires ------------------------------------------------------------------------------------------
    def _iso(self, instant: int) -> str:
        return datetime.fromtimestamp(instant, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _vue(self, post_id: int) -> dict:
        p = self.posts[post_id]
        return {
            "post_id": post_id,
            "type": p["type"],
            "statut": p["statut"],
            "empreinte": self.empreinte(p),
            "modifie_gmt": self._iso(p["modifie"]),
        }

    def _etat(self, post_id: int) -> dict:
        p = self.posts[post_id]
        public = p["statut"] in ("publish", "future")
        return {
            **self._vue(post_id),
            "empreinte_publiee": p.get("empreinte_publiee"),
            "gere": True,
            "lien_public": f"https://{self.site_id}/{p['slug']}/" if public else None,
        }

    def _creer(self, c: dict) -> ReponseHTTP:
        permis = {"type", "titre", "contenu", "extrait", "slug", "statut", "cle_idempotence", "image_a_la_une"}
        if set(c) - permis:
            return erreur(400, "opsys_champ_inconnu")
        statut = c.get("statut", "draft")
        if statut in ("publish", "future", "private"):
            return erreur(403, "opsys_publication_sans_jeton")
        if statut not in ("draft", "pending"):
            return erreur(400, "opsys_statut_interdit")
        if c.get("type") not in ("post", "page"):
            return erreur(400, "opsys_type_non_permis")
        cle = c.get("cle_idempotence")
        if not isinstance(cle, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", cle):
            return erreur(400, "opsys_champ_invalide")
        champs = {
            "type": c["type"],
            "titre": re.sub(r"<[^>]*>", "", c.get("titre", "")).strip(),
            "contenu": kses(c.get("contenu", "")),
            "extrait": c.get("extrait", ""),
            "slug": c.get("slug", ""),
        }
        demande = self.ref.empreinte_contenu({**champs, "image_a_la_une_sha256": ""})
        for pid, p in self.posts.items():
            if p["cle"] == cle:
                if p["demande"] != demande:
                    return erreur(409, "opsys_cle_idempotence_reutilisee")
                return reponse(
                    200,
                    {
                        **self._vue(pid),
                        "deja_cree": True,
                        "lien_modification": f"https://{self.site_id}/wp-admin/post.php?post={pid}&action=edit",
                    },
                )
        pid = self.suivant
        self.suivant += 1
        self.posts[pid] = {**champs, "statut": statut, "cle": cle, "demande": demande, "modifie": self.horloge()}
        return reponse(
            201,
            {
                **self._vue(pid),
                "deja_cree": False,
                "lien_modification": f"https://{self.site_id}/wp-admin/post.php?post={pid}&action=edit",
            },
        )

    def _maj(self, post_id: int, c: dict) -> ReponseHTTP:
        p = self.posts.get(post_id)
        if p is None:
            return erreur(404, "opsys_non_gere")
        if p["statut"] not in ("draft", "pending"):
            return erreur(409, "opsys_etat_non_modifiable")
        if set(c) - {"titre", "contenu", "extrait", "slug", "statut", "empreinte_attendue", "image_a_la_une"}:
            return erreur(400, "opsys_champ_inconnu")
        if c.get("statut") in ("publish", "future", "private"):
            return erreur(403, "opsys_publication_sans_jeton")
        if "statut" in c and c["statut"] not in ("draft", "pending"):
            return erreur(400, "opsys_statut_interdit")
        if "empreinte_attendue" in c and c["empreinte_attendue"] != self.empreinte(p):
            return erreur(409, "opsys_empreinte_obsolete")
        for nom in ("titre", "extrait", "slug", "statut"):
            if nom in c:
                p[nom] = c[nom]
        if "contenu" in c:
            p["contenu"] = kses(c["contenu"])
        p["modifie"] = self.horloge()
        return reponse(200, self._vue(post_id))

    def _media(self, c: dict) -> ReponseHTTP:
        if set(c) != {"nom_fichier", "contenu_base64", "sha256", "alt"}:
            return erreur(400, "opsys_champ_inconnu")
        try:
            octets = base64.b64decode(c["contenu_base64"], validate=True)
        except ValueError:
            return erreur(400, "opsys_media_invalide")
        if hashlib.sha256(octets).hexdigest() != c["sha256"]:
            return erreur(400, "opsys_media_empreinte_differente")
        if b"<?php" in octets.lower():
            return erreur(400, "opsys_media_contenu_actif")
        mime = next((m for m, magique in MAGIQUES.items() if octets.startswith(magique)), None)
        if mime is None:  # le nom de fichier annoncé n'est JAMAIS cru : seuls les octets comptent
            return erreur(415, "opsys_media_type_refuse")
        for mid, mm in self.medias.items():
            if mm["sha"] == c["sha256"]:
                return reponse(
                    200,
                    {
                        "media_id": mid,
                        "sha256": c["sha256"],
                        "mime": mime,
                        "largeur": 10,
                        "hauteur": 10,
                        "deja_cree": True,
                    },
                )
        mid = self.suivant
        self.suivant += 1
        self.medias[mid] = {"sha": c["sha256"], "mime": mime}
        return reponse(
            201,
            {"media_id": mid, "sha256": c["sha256"], "mime": mime, "largeur": 10, "hauteur": 10, "deja_cree": False},
        )

    def _publier(self, post_id: int, c: dict, maintenant: int) -> ReponseHTTP:
        if not self.publication_activee:
            return erreur(503, "opsys_publication_desactivee")
        if set(c) != {"approval_token"} or not isinstance(c["approval_token"], str):
            return erreur(403, "opsys_publication_sans_jeton")
        p = self.posts.get(post_id)
        if p is None:
            return erreur(404, "opsys_non_gere")
        if p["statut"] not in ("draft", "pending"):
            return erreur(409, "opsys_etat_non_modifiable")
        courante = self.empreinte(p)
        verdict, charge = self.ref.verifier_jeton(
            self.secret,
            c["approval_token"],
            site_id_attendu=self.site_id,
            post_id_attendu=post_id,
            empreinte_courante=courante,
            maintenant=maintenant,
        )
        correspondance = {
            "JETON_MALFORME": "opsys_jeton_malforme",
            "JETON_SIGNATURE_INVALIDE": "opsys_jeton_signature_invalide",
            "JETON_CHAMP_INVALIDE": "opsys_jeton_champ_invalide",
            "JETON_EXPIRE": "opsys_jeton_expire",
            "JETON_DUREE_EXCESSIVE": "opsys_jeton_duree_excessive",
            "JETON_EMIS_DANS_LE_FUTUR": "opsys_jeton_champ_invalide",
            "JETON_SITE_DIFFERENT": "opsys_jeton_site_different",
            "JETON_ARTICLE_DIFFERENT": "opsys_jeton_article_different",
            "JETON_EMPREINTE_DIFFERENTE": "opsys_jeton_empreinte_differente",
            "JETON_ACTION_NON_PERMISE": "opsys_jeton_action_non_permise",
            "JETON_PLANIFICATION_INVALIDE": "opsys_jeton_planification_invalide",
        }
        if verdict != "OK":
            return erreur(403, correspondance[verdict])
        if not self.vus.consommer("approval", charge["approval_id"], charge["exp"] + 600, maintenant):
            return erreur(403, "opsys_jeton_deja_utilise")
        p["statut"] = "future" if charge["action"] == "schedule" else "publish"
        p["empreinte_publiee"] = courante
        if not p["slug"]:  # WordPress complète l'adresse à la publication : l'empreinte « vivante » change
            p["slug"] = re.sub(r"[^a-z0-9]+", "-", p["titre"].lower()).strip("-")
        return reponse(
            200,
            {
                "post_id": post_id,
                "statut": p["statut"],
                "empreinte": courante,
                "publie_le_gmt": self._iso(maintenant),
                "lien_public": f"https://{self.site_id}/{p['slug']}/",
            },
        )
