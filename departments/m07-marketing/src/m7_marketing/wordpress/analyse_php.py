"""Analyse statique MAISON du plugin PHP « OPSYS Connect » : un petit lexeur PHP et des règles de motifs dangereux.

POURQUOI : PHP n'est pas installé sur la machine qui a produit ce plugin (`php -v` : commande introuvable). Ce module ne
remplace NI `php -l`, NI PHPCS avec les règles WordPress, NI Plugin Check, NI un test dans WordPress : il ne prouve
ni la
justesse du code ni l'absence de faille. Il attrape des MOTIFS dangereux connus et vérifie quelques invariants de
sécurité
du plugin, de façon à ce qu'une régression grossière (un `eval`, un `$_REQUEST`, une requête SQL concaténée, une route
sans `permission_callback`, une comparaison non constante d'un MAC) soit refusée par la suite de tests.

Il lit les fichiers PHP comme du TEXTE : il n'importe, n'exécute ni n'interprète rien du plugin (qui est sous GPLv2+
et reste
isolé dans `integrations/wordpress/opsys-connect/`).

Règles du plugin (hors `tests/`) :
  - interdits : `eval`, `assert`, `shell_exec`, `system`, `passthru`, `exec`, `popen`, `proc_open`, `pcntl_exec`,
  l'opérateur
    antiguillemet, `unserialize`, `extract`, `create_function`, `call_user_func*`, `parse_str`, variables variables ;
  - entrée : `$_REQUEST`, `$_GET`, `$_POST`, `$_COOKIE`, `$_FILES`, `$_SERVER`, `$GLOBALS` (on passe par
  `WP_REST_Request`) ;
  - SQL : `->query`, `->get_*` n'acceptent qu'un `$wpdb->prepare(...)` ou un littéral sans variable ; `->prepare`
  n'accepte qu'un
    littéral sans variable ni concaténation (les noms de table passent par `%i`) ;
  - sorties : un `echo` n'émet une variable qu'enveloppée dans `esc_*`, `wp_kses*`, `absint`, `intval` ;
  - réseau et disque : aucun appel sortant (`wp_remote_*`, `curl_*`, `fsockopen`, `file_get_contents`…), aucune
  écriture de fichier
    hors des API de la médiathèque (`file_put_contents`, `fopen`, `unlink`, `mkdir`, `copy`, `rename`…) ;
  - routes : chaque `register_rest_route` porte un `permission_callback` qui n'est pas `__return_true` ;
  - rôle : `add_role`/`add_cap` ne donnent jamais `manage_options`, `unfiltered_html`, `install_plugins`,
  `publish_posts`… ;
  - options : aucune option dont le nom évoque un secret n'est écrite en clair par un littéral ;
  - structure : `<?php` en tête, `declare(strict_types=1)`, garde `ABSPATH` (ou `WP_UNINSTALL_PLUGIN`), aucune
  balise fermante,
    aucun BOM, parenthèses, crochets et accolades équilibrés, comparaison des MAC et signatures par `hash_equals`
    seulement ;
  - fichiers : en-tête de plugin (licence GPL-2.0-or-later, version, PHP minimal), `LICENSE` GPLv2.

Module pur : lit des fichiers, n'écrit rien.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator
from pathlib import Path

DANGEREUX_FONCTIONS = {
    "eval": "eval : exécution de code arbitraire",
    "assert": "assert : évalue une chaîne sur les anciens PHP",
    "shell_exec": "exécution de commande système",
    "system": "exécution de commande système",
    "passthru": "exécution de commande système",
    "exec": "exécution de commande système",
    "popen": "exécution de commande système",
    "proc_open": "exécution de commande système",
    "pcntl_exec": "exécution de commande système",
    "unserialize": "unserialize : instanciation d'objets depuis une entrée",
    "maybe_unserialize": "unserialize : instanciation d'objets depuis une entrée",
    "extract": "extract : écrase des variables depuis un tableau",
    "create_function": "create_function : eval déguisé",
    "call_user_func": "appel dynamique de fonction",
    "call_user_func_array": "appel dynamique de fonction",
    "parse_str": "parse_str : variables créées depuis une chaîne",
    "gzinflate": "code obfusqué (règle 4 de wordpress.org)",
    "gzuncompress": "code obfusqué (règle 4 de wordpress.org)",
    "str_rot13": "code obfusqué (règle 4 de wordpress.org)",
    "convert_uudecode": "code obfusqué (règle 4 de wordpress.org)",
    "var_dump": "sortie de débogage",
    "print_r": "sortie de débogage",
    "var_export": "sortie de débogage",
    "debug_zval_dump": "sortie de débogage",
    "phpinfo": "divulgation de configuration",
    "error_log": "journal d'erreurs libre (risque de fuite de secret)",
}
SORTANT_PREFIXES = ("wp_remote_", "wp_safe_remote_", "curl_")
SORTANT_FONCTIONS = {
    "fsockopen",
    "pfsockopen",
    "stream_socket_client",
    "file_get_contents",
    "download_url",
    "readfile",
    "file",
    "wp_http_validate_url",
    "simplexml_load_file",
}
ECRITURE_FONCTIONS = {
    "file_put_contents",
    "fwrite",
    "fputs",
    "fopen",
    "unlink",
    "rename",
    "copy",
    "mkdir",
    "rmdir",
    "touch",
    "chmod",
    "chown",
    "tempnam",
    "tmpfile",
    "move_uploaded_file",
    "symlink",
    "link",
    "wp_mkdir_p",
    "wp_tempnam",
    "wp_handle_upload",
    "wp_handle_sideload",
    "media_handle_upload",
    "media_handle_sideload",
}
SUPERGLOBALES = {"$_REQUEST", "$_GET", "$_POST", "$_COOKIE", "$_FILES", "$_SERVER", "$_ENV", "$GLOBALS"}
SQL_EXECUTION = {"query", "get_results", "get_row", "get_var", "get_col"}
ECHAPPEMENTS = ("esc_", "wp_kses")
ECHAPPEMENTS_NOMBRES = {"absint", "intval", "number_format_i18n"}
CAPACITES_DANGEREUSES = {
    "manage_options",
    "unfiltered_html",
    "install_plugins",
    "edit_plugins",
    "activate_plugins",
    "update_core",
    "publish_posts",
    "publish_pages",
    "edit_published_posts",
    "edit_others_posts",
    "delete_posts",
    "edit_users",
    "create_users",
    "delete_users",
    "promote_users",
    "switch_themes",
    "edit_theme_options",
    "administrator",
}
MOTS_SECRETS = re.compile(r"secret|password|passwd|token|api_?key|private_?key", re.IGNORECASE)
SENSIBLES = {"$expected", "$received", "$mac", "$expected_mac", "$signature", "$secret", "$token", "$hmac"}
OPERATEURS_EGALITE = {"===", "!==", "==", "!="}

FICHIERS_AVEC_COMPARAISON_SENSIBLE = ("class-opsys-connect-signature.php", "class-opsys-connect-approval.php")


@dataclasses.dataclass(frozen=True)
class Jeton:
    genre: str  # var, ident, str, num, punct, html, open, close, backtick
    texte: str
    ligne: int
    interpolation: bool = False


@dataclasses.dataclass(frozen=True)
class Violation:
    code: str
    fichier: str
    ligne: int
    detail: str

    def __str__(self) -> str:
        return f"{self.fichier}:{self.ligne} {self.code} {self.detail}"


_PONCTUATION_LONGUE = (
    "<<<",
    "??=",
    "?->",
    "...",
    "===",
    "!==",
    "<=>",
    "**=",
    "<<=",
    ">>=",
    "::",
    "->",
    "=>",
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "??",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    ".=",
    "%=",
    "<<",
    ">>",
    "**",
    "|=",
    "&=",
    "^=",
)
_IDENT = re.compile(
    r"\\?[A-Za-z_\x80-\uffff][A-Za-z0-9_\x80-\uffff]*(?:\\[A-Za-z_\x80-\uffff][A-Za-z0-9_\x80-\uffff]*)*"
)
_NOMBRE = re.compile(r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|(?:[0-9][0-9_]*)?\.?[0-9][0-9_]*(?:[eE][+-]?[0-9]+)?")
_VARIABLE = re.compile(r"\$[A-Za-z_\x80-\uffff][A-Za-z0-9_\x80-\uffff]*")
_INTERPOLATION = re.compile(r"(?<!\\)(?:\{\$|\$[A-Za-z_{])")


def lexer(source: str) -> tuple[list[Jeton], list[tuple[int, str]]]:
    """(jetons, problèmes de forme). Gère HTML en ligne, commentaires, chaînes simples et doubles, heredoc/nowdoc."""
    jetons: list[Jeton] = []
    problemes: list[tuple[int, str]] = []
    i, ligne, n = 0, 1, len(source)
    en_php = False
    while i < n:
        if not en_php:
            suivant = source.find("<?", i)
            html = source[i:] if suivant < 0 else source[i:suivant]
            if html.strip():
                jetons.append(Jeton("html", html[:40], ligne))
            ligne += html.count("\n")
            if suivant < 0:
                break
            i = suivant
            if source.startswith("<?php", i) and (i + 5 == n or source[i + 5].isspace()):
                jetons.append(Jeton("open", "<?php", ligne))
                i += 5
            elif source.startswith("<?=", i):
                problemes.append((ligne, "balise courte <?= interdite"))
                i += 3
            else:
                problemes.append((ligne, "balise ouvrante courte <? interdite"))
                i += 2
            en_php = True
            continue
        c = source[i]
        if c == "\n":
            ligne += 1
            i += 1
        elif c in " \t\r":
            i += 1
        elif source.startswith("?>", i):
            jetons.append(Jeton("close", "?>", ligne))
            i += 2
            en_php = False
        elif source.startswith("//", i) or (c == "#" and not source.startswith("#[", i)):
            fin = i
            while fin < n and source[fin] != "\n" and not source.startswith("?>", fin):
                fin += 1
            i = fin
        elif source.startswith("/*", i):
            fin = source.find("*/", i + 2)
            fin = n if fin < 0 else fin + 2
            ligne += source.count("\n", i, fin)
            i = fin
        elif c == "'":
            fin = i + 1
            while fin < n and source[fin] != "'":
                fin += 2 if source[fin] == "\\" else 1
            jetons.append(Jeton("str", source[i + 1 : fin], ligne))
            ligne += source.count("\n", i, fin)
            i = fin + 1
        elif c == '"':
            fin = i + 1
            while fin < n and source[fin] != '"':
                fin += 2 if source[fin] == "\\" else 1
            contenu = source[i + 1 : fin]
            jetons.append(Jeton("str", contenu, ligne, interpolation=bool(_INTERPOLATION.search(contenu))))
            ligne += source.count("\n", i, fin)
            i = fin + 1
        elif c == "`":
            fin = source.find("`", i + 1)
            fin = n - 1 if fin < 0 else fin
            jetons.append(Jeton("backtick", source[i + 1 : fin][:40], ligne))
            ligne += source.count("\n", i, fin)
            i = fin + 1
        elif source.startswith("<<<", i):
            m = re.match(r"<<<[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1\r?\n", source[i:])
            if m is None:
                jetons.append(Jeton("punct", "<<", ligne))
                i += 2
                continue
            fin_motif = re.search(rf"^[ \t]*{re.escape(m.group(2))}\b", source[i + m.end() :], re.MULTILINE)
            fin = n if fin_motif is None else i + m.end() + fin_motif.end()
            corps = source[i + m.end() : fin]
            jetons.append(
                Jeton("str", corps[:200], ligne, interpolation=m.group(1) != "'" and bool(_INTERPOLATION.search(corps)))
            )
            ligne += source.count("\n", i, fin)
            i = fin
        elif c == "$" and source.startswith("$$", i):
            jetons.append(Jeton("punct", "$$", ligne))
            i += 2
        elif c == "$" and source.startswith("${", i):
            jetons.append(Jeton("punct", "${", ligne))
            i += 2
        elif c == "$":
            m = _VARIABLE.match(source, i)
            if m is None:
                jetons.append(Jeton("punct", "$", ligne))
                i += 1
            else:
                jetons.append(Jeton("var", m.group(0), ligne))
                i = m.end()
        elif c.isdigit() or (c == "." and i + 1 < n and source[i + 1].isdigit()):
            m = _NOMBRE.match(source, i)
            jetons.append(Jeton("num", m.group(0) if m else c, ligne))
            i = m.end() if m else i + 1
        elif c.isalpha() or c == "_" or c == "\\" or ord(c) >= 0x80:
            m = _IDENT.match(source, i)
            if m is None:
                jetons.append(Jeton("punct", c, ligne))
                i += 1
            else:
                jetons.append(Jeton("ident", m.group(0), ligne))
                i = m.end()
        else:
            longue = next((p for p in _PONCTUATION_LONGUE if source.startswith(p, i)), None)
            jetons.append(Jeton("punct", longue or c, ligne))
            i += len(longue or c)
    return jetons, problemes


def _arguments(jetons: list[Jeton], debut: int) -> tuple[list[Jeton], int]:
    """Jetons entre la parenthèse ouvrante en `debut` et sa fermante (exclues), et l'indice de la fermante."""
    profondeur, j = 0, debut
    while j < len(jetons):
        t = jetons[j]
        if t.genre == "punct" and t.texte in "([{" and len(t.texte) == 1:
            profondeur += 1
        elif t.genre == "punct" and t.texte in ")]}" and len(t.texte) == 1:
            profondeur -= 1
            if profondeur == 0:
                return jetons[debut + 1 : j], j
        j += 1
    return jetons[debut + 1 :], len(jetons)


def _premier_argument(args: list[Jeton]) -> list[Jeton]:
    profondeur, sortie = 0, []
    for t in args:
        if t.genre == "punct" and len(t.texte) == 1 and t.texte in "([{":
            profondeur += 1
        elif t.genre == "punct" and len(t.texte) == 1 and t.texte in ")]}":
            profondeur -= 1
        elif t.genre == "punct" and t.texte == "," and profondeur == 0:
            break
        sortie.append(t)
    return sortie


def _appels(jetons: list[Jeton]) -> Iterator[tuple[int, Jeton, str | None]]:
    """(indice du nom, jeton, jeton précédent) pour chaque `nom (` : appel de fonction, de méthode ou de construction.
    """
    for i, t in enumerate(jetons[:-1]):
        if t.genre == "ident" and jetons[i + 1].genre == "punct" and jetons[i + 1].texte == "(":
            precedent = jetons[i - 1].texte if i > 0 else None
            yield i, t, precedent


def _nom_court(texte: str) -> str:
    return texte.rsplit("\\", 1)[-1].lower()


def analyser_source(source: str, nom: str, *, mode: str = "plugin") -> list[Violation]:
    """Les violations d'UN fichier PHP. `mode` : `plugin` (toutes les règles) ou `test` (script d'essai : disque et
    sortie permis).
    """
    v: list[Violation] = []

    def ajouter(code: str, ligne: int, detail: str) -> None:
        v.append(Violation(code, nom, ligne, detail))

    if source.startswith("\ufeff"):
        ajouter("PHP-BOM", 1, "marque d'ordre des octets (BOM) en tête de fichier")
    jetons, problemes = lexer(source)
    for ligne, detail in problemes:
        ajouter("PHP-BALISE", ligne, detail)
    if not jetons or jetons[0].genre != "open":
        ajouter("PHP-OUVERTURE", 1, "le fichier doit commencer par <?php")
    for t in jetons:
        if t.genre == "close":
            ajouter(
                "PHP-BALISE-FERMANTE", t.ligne, "balise fermante ?> interdite (tout ce qui suit serait émis tel quel)"
            )
        elif t.genre == "html":
            ajouter("PHP-HTML-EN-LIGNE", t.ligne, "texte hors balises PHP")
        elif t.genre == "backtick":
            ajouter("PHP-ANTIGUILLEMET", t.ligne, "opérateur ` : exécution de commande système")
        elif t.genre == "punct" and t.texte in ("$$", "${"):
            ajouter("PHP-VARIABLE-VARIABLE", t.ligne, "variable variable")
        elif t.genre == "var" and t.texte in SUPERGLOBALES and mode == "plugin":
            ajouter("PHP-SUPERGLOBALE", t.ligne, f"{t.texte} : lire l'entrée par WP_REST_Request, jamais directement")
        elif t.genre == "str" and "wp_ajax_nopriv" in t.texte:
            ajouter("PHP-AJAX-ANONYME", t.ligne, "action wp_ajax_nopriv_* : accessible sans compte")
    _equilibre(jetons, ajouter)
    if mode == "plugin":
        _structure(jetons, nom, ajouter)
    for i, t, precedent in _appels(jetons):
        nom_appel = _nom_court(t.texte)
        membre = precedent in ("->", "::", "?->")
        if not membre and precedent != "function":
            if nom_appel in DANGEREUX_FONCTIONS and not (mode == "test" and nom_appel in {"var_export", "print_r"}):
                ajouter("PHP-FONCTION-INTERDITE", t.ligne, f"{nom_appel}() : {DANGEREUX_FONCTIONS[nom_appel]}")
            if mode == "plugin" and (nom_appel in SORTANT_FONCTIONS or nom_appel.startswith(SORTANT_PREFIXES)):
                ajouter("PHP-APPEL-SORTANT", t.ligne, f"{nom_appel}() : le plugin ne contacte aucun service")
            if mode == "plugin" and nom_appel in ECRITURE_FONCTIONS:
                ajouter(
                    "PHP-ECRITURE-DISQUE", t.ligne, f"{nom_appel}() : aucune écriture hors des API de la médiathèque"
                )
            if nom_appel in {"update_option", "add_option", "get_option", "delete_option"} and mode == "plugin":
                args, _ = _arguments(jetons, i + 1)
                premier = _premier_argument(args)
                if len(premier) == 1 and premier[0].genre == "str" and MOTS_SECRETS.search(premier[0].texte):
                    ajouter(
                        "PHP-SECRET-EN-OPTION",
                        t.ligne,
                        f"option {premier[0].texte!r} : un secret ne va pas en option en clair",
                    )
            if nom_appel == "register_rest_route" and mode == "plugin":
                _route(jetons, i, ajouter)
        if nom_appel in {"add_role", "add_cap"} and mode == "plugin":
            args, _ = _arguments(jetons, i + 1)
            for a in args:
                if a.genre == "str" and a.texte in CAPACITES_DANGEREUSES:
                    ajouter("PHP-CAPACITE-DANGEREUSE", a.ligne, f"{nom_appel} donne {a.texte}")
        if membre and nom_appel in SQL_EXECUTION | {"prepare"} and mode == "plugin":
            _sql(jetons, i, nom_appel, ajouter)
    for i, t in enumerate(jetons):
        if t.genre == "ident" and t.texte.lower() in {"include", "include_once", "require", "require_once"}:
            expression = []
            j = i + 1
            while j < len(jetons) and not (jetons[j].genre == "punct" and jetons[j].texte == ";"):
                expression.append(jetons[j])
                j += 1
            if any(e.genre == "var" for e in expression):
                ajouter("PHP-INCLUSION-DYNAMIQUE", t.ligne, f"{t.texte} avec une variable")
        if t.genre == "ident" and t.texte.lower() in {"echo", "print"} and mode == "plugin":
            _sortie(jetons, i, ajouter)
    if mode == "plugin" and Path(nom).name in FICHIERS_AVEC_COMPARAISON_SENSIBLE:
        for i, t in enumerate(jetons):
            if t.genre == "punct" and t.texte in OPERATEURS_EGALITE:
                voisins = [jetons[k] for k in (i - 1, i + 1) if 0 <= k < len(jetons)]
                for voisin in voisins:
                    if voisin.genre == "var" and voisin.texte in SENSIBLES:
                        ajouter(
                            "PHP-COMPARAISON-NON-CONSTANTE",
                            t.ligne,
                            f"{voisin.texte} comparé avec {t.texte} : utiliser hash_equals()",
                        )
    return v


def _equilibre(jetons: list[Jeton], ajouter) -> None:
    paires = {")": "(", "]": "[", "}": "{"}
    pile: list[Jeton] = []
    for t in jetons:
        if t.genre == "punct" and t.texte in ("(", "[", "{", "${"):
            pile.append(t)
        elif t.genre == "punct" and t.texte in paires:
            if not pile or (pile[-1].texte.replace("${", "{")) != paires[t.texte]:
                ajouter("PHP-DESEQUILIBRE", t.ligne, f"{t.texte} sans ouvrante correspondante")
                return
            pile.pop()
    if pile:
        ajouter("PHP-DESEQUILIBRE", pile[-1].ligne, f"{pile[-1].texte} jamais refermée")


def _structure(jetons: list[Jeton], nom: str, ajouter) -> None:
    base = Path(nom).name
    if base == "index.php":
        return
    textes = [(t.genre, t.texte) for t in jetons]
    declare = [
        ("ident", "declare"),
        ("punct", "("),
        ("ident", "strict_types"),
        ("punct", "="),
        ("num", "1"),
        ("punct", ")"),
    ]
    if not any(textes[i : i + 6] == declare for i in range(len(textes))):
        ajouter("PHP-STRICT-TYPES", 1, "declare(strict_types=1) absent")
    garde = "WP_UNINSTALL_PLUGIN" if base == "uninstall.php" else "ABSPATH"
    motif = [("ident", "defined"), ("punct", "("), ("str", garde), ("punct", ")"), ("punct", "||"), ("ident", "exit")]
    if not any(textes[i : i + 6] == motif for i in range(len(textes))):
        ajouter("PHP-GARDE-ACCES", 1, f"garde defined( '{garde}' ) || exit; absente")


def _sortie(jetons: list[Jeton], debut: int, ajouter) -> None:
    pile: list[str] = []
    j = debut + 1
    while j < len(jetons) and not (jetons[j].genre == "punct" and jetons[j].texte == ";"):
        t = jetons[j]
        if t.genre == "punct" and t.texte == "(":
            precedent = jetons[j - 1]
            pile.append(_nom_court(precedent.texte) if precedent.genre == "ident" else "")
        elif t.genre == "punct" and t.texte == ")" and pile:
            pile.pop()
        elif t.genre == "var":
            protege = any(nom.startswith(ECHAPPEMENTS) or nom in ECHAPPEMENTS_NOMBRES for nom in pile)
            if not protege:
                ajouter("PHP-SORTIE-NON-ECHAPPEE", t.ligne, f"echo de {t.texte} sans esc_*/wp_kses*/absint")
        elif t.genre == "str" and t.interpolation:
            ajouter("PHP-SORTIE-NON-ECHAPPEE", t.ligne, "echo d'une chaîne avec interpolation")
        j += 1


def _route(jetons: list[Jeton], debut: int, ajouter) -> None:
    args, _ = _arguments(jetons, debut + 1)
    permissions = [k for k, t in enumerate(args) if t.genre == "str" and t.texte == "permission_callback"]
    if not permissions:
        ajouter("PHP-ROUTE-SANS-PERMISSION", jetons[debut].ligne, "register_rest_route sans permission_callback")
        return
    for k in permissions:
        valeur = args[k + 2 : k + 3]
        if (
            not valeur
            or (valeur[0].genre == "ident" and valeur[0].texte.lower() in {"__return_true", "true"})
            or (valeur[0].genre == "str" and valeur[0].texte == "__return_true")
        ):
            ajouter("PHP-ROUTE-OUVERTE", args[k].ligne, "permission_callback ouvert à tous (__return_true)")


def _sql(jetons: list[Jeton], debut: int, nom_appel: str, ajouter) -> None:
    args, _ = _arguments(jetons, debut + 1)
    premier = _premier_argument(args)
    if not premier:
        return
    litteral = len(premier) == 1 and premier[0].genre == "str" and not premier[0].interpolation
    if nom_appel == "prepare":
        if not litteral:
            ajouter(
                "PHP-SQL-CONCATENE",
                jetons[debut].ligne,
                "$wpdb->prepare( ) : le gabarit doit être un littéral sans variable ni concaténation (noms de table "
                ": %i)",
            )
        return
    prepare = (
        len(premier) >= 3 and premier[0].texte == "$wpdb" and premier[1].texte == "->" and premier[2].texte == "prepare"
    )
    if not litteral and not prepare:
        ajouter(
            "PHP-SQL-NON-PREPARE", jetons[debut].ligne, f"->{nom_appel}() : la requête n'est ni préparée ni un littéral"
        )


def analyser_fichier(chemin: Path, racine: Path) -> list[Violation]:
    relatif = chemin.relative_to(racine).as_posix()
    mode = "test" if relatif.startswith("tests/") else "plugin"
    return analyser_source(chemin.read_text(encoding="utf-8"), relatif, mode=mode)


_EN_TETE = re.compile(r"^[ \t/*#@]*([A-Za-z][A-Za-z ]+):[ \t]*(.+?)\s*$", re.MULTILINE)


def en_tete_plugin(source: str) -> dict[str, str]:
    bloc = source[:8192]
    return {m.group(1).strip(): m.group(2).strip() for m in _EN_TETE.finditer(bloc)}


def analyser_dossier(racine: Path) -> list[Violation]:
    """Toutes les violations du plugin dans `racine` : fichiers PHP, en-tête, licence, structure du dossier."""
    resultat: list[Violation] = []
    fichiers = sorted(p for p in racine.rglob("*.php") if p.is_file())
    for chemin in fichiers:
        resultat.extend(analyser_fichier(chemin, racine))
    principal = racine / "opsys-connect.php"
    if not principal.is_file():
        resultat.append(Violation("PLUGIN-FICHIER-PRINCIPAL", "opsys-connect.php", 1, "fichier principal absent"))
    else:
        entete = en_tete_plugin(principal.read_text(encoding="utf-8"))
        for champ, attendu in (
            ("Plugin Name", None),
            ("Version", None),
            ("Requires PHP", None),
            ("Requires at least", None),
            ("License", "GPL-2.0-or-later"),
            ("Text Domain", "opsys-connect"),
        ):
            if champ not in entete or (attendu is not None and entete[champ] != attendu):
                resultat.append(
                    Violation(
                        "PLUGIN-EN-TETE", "opsys-connect.php", 1, f"en-tête {champ} absent ou différent de {attendu!r}"
                    )
                )
    licence = racine / "LICENSE"
    texte = licence.read_text(encoding="utf-8") if licence.is_file() else ""
    if "GNU GENERAL PUBLIC LICENSE" not in texte or "Version 2" not in texte:
        resultat.append(Violation("PLUGIN-LICENCE", "LICENSE", 1, "LICENSE GPLv2 absent ou illisible"))
    return resultat
