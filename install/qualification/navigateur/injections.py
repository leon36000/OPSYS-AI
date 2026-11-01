"""Injections de défauts du banc navigateur : chacune AFFAIBLIT la console dans le processus de l'instance fictive (aucun fichier
du dépôt n'est modifié) pour vérifier que le banc, lui, le voit. Une injection que le banc ne détecte pas est un trou du banc.

`INJECTIONS[nom] = (fonction d'application, groupes joués, constats attendus en échec)`. Voir `lancer.py mutations`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any


def _csrf_retire() -> None:
    from opsys.console import securite

    securite.csrf_valide = lambda fourni, session: True  # type: ignore[assignment]


def _cookie(**forces: Any) -> Callable[[], None]:
    def appliquer() -> None:
        from starlette.responses import Response

        original = Response.set_cookie

        def set_cookie(self, key, value="", *args, **kwargs):  # noqa: ANN001
            kwargs.update(forces)
            return original(self, key, value, *args, **kwargs)

        Response.set_cookie = set_cookie  # type: ignore[method-assign]

    return appliquer


def _cookie_non_efface() -> None:
    from starlette.responses import Response

    Response.delete_cookie = lambda self, *a, **k: None  # type: ignore[method-assign]


def _csp_affaiblie() -> None:
    from opsys.console import application

    application.CSP = "default-src *; script-src * 'unsafe-inline'"


def _etiquette_retiree() -> None:
    from opsys.console import pages

    original = pages.page_connexion
    pages.page_connexion = lambda **k: original(**k).replace('<label for="mot_de_passe">Mot de passe</label>', "")


def _lang_retire() -> None:
    from opsys.console import pages

    original = pages.gabarit
    pages.gabarit = lambda *a, **k: original(*a, **k).replace('<html lang="fr">', "<html>", 1)


def _css(supplement: str) -> Callable[[], None]:
    def appliquer() -> None:
        from opsys.console import application, ressources

        application._STATIQUES["console.css"] = (ressources.CSS + supplement, "text/css; charset=utf-8")  # noqa: SLF001

    return appliquer


def _secret_en_clair() -> None:
    """Un intergiciel ASGI recopie la dernière valeur de secret saisie dans la page des secrets (défaut simulé)."""
    from opsys.console import application

    original = application.creer_application

    def fabrique(*a, **k):
        app = original(*a, **k)
        etat = {"valeur": ""}

        class Fuite:
            def __init__(self, suivant):  # noqa: ANN001
                self.suivant = suivant

            async def __call__(self, scope, receive, send):  # noqa: ANN001
                if scope["type"] != "http":
                    return await self.suivant(scope, receive, send)

                async def recevoir():
                    message = await receive()
                    if message["type"] == "http.request" and scope["path"].endswith("/secrets/definir"):
                        trouve = re.search(rb"valeur=([^&]+)", message.get("body", b""))
                        if trouve:
                            etat["valeur"] = trouve.group(1).decode()
                    return message

                async def envoyer(message):  # noqa: ANN001
                    if message["type"] == "http.response.body" and scope["path"].endswith("/plateforme/secrets") and etat["valeur"]:
                        corps = message.get("body", b"")
                        message = {**message, "body": corps.replace(
                            b"</main>", f"<p>Dernière valeur : {etat['valeur']}</p></main>".encode())}
                    if message["type"] == "http.response.start":
                        message = {**message, "headers": [(k, v) for k, v in message["headers"] if k != b"content-length"]}
                    await send(message)

                await self.suivant(scope, recevoir, envoyer)

        app.add_middleware(Fuite)
        return app

    application.creer_application = fabrique


# nom -> (application, groupes à jouer, constats attendus en échec : au moins UN doit échouer pour que l'injection soit « tuée »)
INJECTIONS: dict[str, tuple[Callable[[], None], list[str], list[str]]] = {
    "csrf-retire": (_csrf_retire, ["csrf"], ["csrf/post-sans-jeton", "csrf/post-jeton-faux", "csrf/api-sans-jeton", "csrf/inter-sites-samesite"]),
    "cookie-sans-httponly": (_cookie(httponly=False), ["connexion"], ["connexion/cookie-drapeaux", "connexion/cookie-invisible-js"]),
    "cookie-sans-secure": (_cookie(secure=False), ["connexion"], ["connexion/cookie-drapeaux"]),
    "cookie-samesite-none": (_cookie(samesite="none"), ["connexion", "csrf"], ["connexion/cookie-drapeaux", "csrf/inter-sites-samesite"]),
    "cookie-non-efface": (_cookie_non_efface, ["deconnexion"], ["deconnexion/cookie-efface"]),
    "secret-en-clair": (_secret_en_clair, ["plateforme"], ["plateforme/secret-jamais-reaffiche", "plateforme/secret-aucune-reponse"]),
    "etiquette-retiree": (_etiquette_retiree, ["a11y"], ["accessibilite/regle-champs-etiquetes"]),
    "lang-retire": (_lang_retire, ["a11y"], ["accessibilite/regle-lang-fr"]),
    "csp-affaiblie": (_csp_affaiblie, ["entetes"], ["entetes-securite/pages", "entetes-securite/csp-bloque-script-en-ligne"]),
    "focus-retire": (_css("*:focus-visible { outline: none !important; box-shadow: none !important; }"), ["clavier"],
                     ["clavier/connexion-focus-visible", "clavier/departements-focus"]),
    "contraste-faible": (_css(".entete nav a { color: #b8bcc2; } .intro, .note { color: #c8ccd2; }"), ["a11y"], ["accessibilite/regle-contraste-texte"]),
    "debordement-horizontal": (_css("main { min-width: 1300px; }"), ["responsive"], ["responsive/largeur-375", "responsive/largeur-768"]),
}
