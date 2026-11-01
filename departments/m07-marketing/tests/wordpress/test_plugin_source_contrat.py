"""Contrat entre le TEXTE du plugin PHP et le code Python d'OPSYS.

Le plugin n'a jamais été exécuté : ces tests lisent ses fichiers comme du texte et vérifient que ses constantes, ses
routes,
ses codes d'erreur et ses invariants de sécurité sont ceux que le client Python et la spécification supposent. Ils
tuent les
dérives silencieuses (une fenêtre changée d'un côté, une route renommée, un statut `publish` écrit ailleurs que dans le
publicateur) ; ils ne prouvent pas que le PHP fonctionne.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from m7_marketing.wordpress import client, empreinte, jeton, signature

FICTIF = True
RACINE = Path(__file__).resolve().parents[4]
PLUGIN = RACINE / "integrations" / "wordpress" / "opsys-connect"
INCLUDES = PLUGIN / "includes"


def _src(nom: str) -> str:
    return (INCLUDES / f"class-opsys-connect-{nom}.php").read_text(encoding="utf-8")


def _tous() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(PLUGIN.rglob("*.php"))}


def _constante(source: str, nom: str) -> str:
    m = re.search(rf"const\s+{nom}\s*=\s*(.+?);", source, re.DOTALL)
    assert m, nom
    return m.group(1).strip()


def test_les_constantes_de_signature_sont_celles_du_client():
    php = _src("signature")
    assert int(_constante(php, "WINDOW")) == signature.FENETRE_S == 300
    assert _constante(php, "PREFIX") == f"'{signature.PREFIXE_CANONIQUE}'"
    assert int(_constante(php, "MIN_SECRET_LEN")) == signature.SECRET_LONGUEUR_MIN
    for en_tete in (signature.EN_TETE_HORODATAGE, signature.EN_TETE_NONCE, signature.EN_TETE_SIGNATURE):
        assert f"'{en_tete.lower()}'" in php or f"'{en_tete.lower()}'" in _src("auth")
    assert signature.EN_TETE_CLE.lower() in _src("auth")
    # mêmes motifs de forme (avec \A…\z et le modificateur /D : pas de LF final toléré)
    assert r"/\A[0-9]{10}\z/D" in php and r"/\A[A-Za-z0-9_-]{16,64}\z/D" in php and r"/\Av1=[0-9a-f]{64}\z/D" in php
    assert signature.MOTIF_HORODATAGE.pattern == "[0-9]{10}" and signature.MOTIF_NONCE.pattern == "[A-Za-z0-9_-]{16,64}"


def test_les_constantes_du_jeton_sont_celles_du_client():
    php = _src("approval")
    assert int(_constante(php, "MAX_LIFETIME")) == jeton.DUREE_MAX_S == 86400
    assert int(_constante(php, "ISSUE_SKEW")) == 60
    assert _constante(php, "MAC_PREFIX") == '"OPSYS-APPROVAL-V1\\n"' and jeton.PREFIXE_MAC == b"OPSYS-APPROVAL-V1\n"
    assert (
        _constante(php, "KEY_INFO") == '"opsys-connect/approval/v1\\x01"'
        and jeton.INFO_CLE == b"opsys-connect/approval/v1\x01"
    )
    champs = re.search(r"FIELDS\s*=\s*array\((.+?)\);", php, re.DOTALL).group(1)
    assert tuple(re.findall(r"'(\w+)'", champs)) == jeton.CHAMPS
    assert "hash_equals" in php and "hash_hmac( 'sha256'" in php


def test_les_codes_de_constat_du_verificateur_sont_les_memes_dans_php_et_dans_les_vecteurs(vecteurs):
    php = _src("approval")
    codes_php = set(re.findall(r"=\s*'(JETON_[A-Z_]+)'", php)) | {"OK"}
    codes_vecteurs = {c["attendu"] for c in vecteurs["jetons"]}
    assert codes_vecteurs <= codes_php, codes_vecteurs - codes_php
    sig = _src("signature")
    codes_sig = set(re.findall(r"=\s*'([A-Z_]+)';", sig))
    assert {c["attendu"] for c in vecteurs["verifications"]} <= codes_sig


def test_l_empreinte_du_contenu_est_la_meme():
    php = _src("fingerprint")
    assert _constante(php, "HEADER") == '"opsys-content/v1\\n"' and empreinte.ENTETE + "\n" == "opsys-content/v1\n"
    champs = re.search(r"FIELDS\s*=\s*array\((.+?)\);", php, re.DOTALL).group(1)
    assert tuple(re.findall(r"'(\w+)'", champs)) == empreinte.CHAMPS
    assert "strlen( $fields[ $name ] )" in php, "longueur en OCTETS (strlen), pas en caractères (mb_strlen)"
    assert "mb_strlen" not in php


ROUTES_ATTENDUES = {
    ("GET", "/health"),
    ("GET", "/types"),
    ("POST", "/drafts"),
    ("PUT", "/drafts/(?P<id>[0-9]+)"),
    ("POST", "/media"),
    ("GET", "/posts/(?P<id>[0-9]+)/state"),
    ("POST", "/posts/(?P<id>[0-9]+)/publish"),
}


def test_les_routes_du_plugin_sont_exactement_celles_que_le_client_appelle():
    php = _src("rest")
    blocs = re.findall(
        r"register_rest_route\(\s*self::API_NAMESPACE,\s*'([^']+)',\s*array\((.+?)\)\s*\);", php, re.DOTALL
    )
    routes = {(re.search(r"'methods'\s*=>\s*'(\w+)'", corps).group(1), chemin) for chemin, corps in blocs}
    assert routes == ROUTES_ATTENDUES
    assert re.search(r"API_NAMESPACE\s*=\s*'opsys-connect/v1'", php) and client.NAMESPACE == "/opsys-connect/v1"
    for chemin, corps in blocs:
        permission = re.search(r"'permission_callback'\s*=>\s*array\( Auth::class, '(check_\w+)' \)", corps)
        assert permission, f"{chemin} sans permission_callback d'Auth"
        assert "__return_true" not in corps
    # le client n'appelle que des routes que le plugin déclare
    appelees = set(re.findall(r'f"\{NAMESPACE\}(/[^"]+)"', Path(client.__file__).read_text(encoding="utf-8")))
    declarees = {re.sub(r"\(\?P<id>\[0-9\]\+\)", "{ID}", c) for _, c in ROUTES_ATTENDUES}
    normalisees = {re.sub(r"\{[^}]*\}", "{ID}", a) for a in appelees}
    assert normalisees <= declarees, normalisees - declarees


def test_les_codes_d_erreur_du_plugin_et_ceux_du_client_se_correspondent():
    php = " ".join(_tous().values())
    codes_php = set(re.findall(r"'(opsys_[a-z_]+)'", php))
    codes_php -= {
        "opsys_connect_use",
        "opsys_connect_purge",
        "opsys_connect_post_types",
        "opsys_connect_actions",
        "opsys_connect_secret_sealed",
        "opsys_agent",
        "opsys_connect_seen",
        "opsys_connect_version",
    }
    inconnus = {c for c in codes_php if c not in client.CODES_PLUGIN}
    assert inconnus == set(), f"codes du plugin que le client ne sait pas nommer : {inconnus}"
    jamais_emis = {c for c in client.CODES_PLUGIN if c not in codes_php}
    # un code que le client prévoit mais que le plugin ne produit jamais est un code mort : à retirer ou à produire
    assert jamais_emis == set(), f"codes du client sans émetteur dans le plugin : {jamais_emis}"


def test_aucun_statut_de_publication_n_est_ecrit_ailleurs_que_dans_le_publicateur():
    motif = re.compile(r"post_status['\"\]]*\s*(?:=>|=)\s*'(publish|future|private)'")
    for nom, source in _tous().items():
        trouves = motif.findall(source)
        if nom == "class-opsys-connect-publisher.php":
            assert trouves, "le publicateur écrit publish/future"
        else:
            assert trouves == [], f"{nom} écrit un statut public"
    publicateur = _tous()["class-opsys-connect-publisher.php"]
    assert (
        publicateur.index("Approval::verify")
        < publicateur.index("Seen_Store::consume")
        < publicateur.index("wp_update_post")
    )
    assert publicateur.index("Content::fingerprint") < publicateur.index("Approval::verify")


def test_les_ecritures_d_articles_et_de_medias_sont_localisees():
    sources = _tous()
    ecrivent = {nom for nom, s in sources.items() if re.search(r"\bwp_(insert|update)_post\(", s)}
    assert ecrivent == {"class-opsys-connect-content.php", "class-opsys-connect-publisher.php"}
    assert {nom for nom, s in sources.items() if "wp_insert_attachment(" in s} == {"class-opsys-connect-media.php"}
    assert {nom for nom, s in sources.items() if "wp_upload_bits(" in s} == {"class-opsys-connect-media.php"}


def test_l_autorisation_de_publier_est_toujours_remise_a_faux():
    publicateur = _src("publisher")
    m = re.search(
        r"Guard::\$publication_authorized = true;\s*try \{(.+?)\} finally \{\s*Guard::\$publication_authorized "
        r"= false;",
        publicateur,
        re.DOTALL,
    )
    assert m and "wp_update_post" in m.group(1)
    for nom, source in _tous().items():
        if nom != "class-opsys-connect-publisher.php" and nom != "class-opsys-connect-guard.php":
            assert "publication_authorized = true" not in source
    garde = _src("guard")
    assert "Auth::$active" in garde and "'publish', 'future', 'private'" in garde and "'draft'" in garde
    assert "add_filter( 'wp_insert_post_data'" in (PLUGIN / "opsys-connect.php").read_text(encoding="utf-8")


def test_l_ordre_des_controles_d_authentification_est_fixe():
    auth = _src("auth")
    corps = auth[auth.index("private static function authenticate") :]
    etapes = [
        "is_ssl()",
        "Config::secret()",
        "get_query_params()",
        "strlen( $body )",
        "Config::key_id()",
        "Signature::verify(",
        "Seen_Store::consume(",
        "Config::agent_user()",
        "wp_set_current_user(",
        "current_user_can( Config::CAPABILITY )",
    ]
    positions = [corps.index(e) for e in etapes]
    assert positions == sorted(positions), dict(zip(etapes, positions, strict=True))
    assert "self::$active = true" in corps and corps.index("self::$active = true") > positions[-1]


def test_le_nonce_n_est_consomme_qu_apres_une_signature_valide_et_en_base_avec_cle_primaire():
    store = _src("seen-store")
    assert "PRIMARY KEY  (kind,token_hash)" in store and "expires_at" in store
    assert "$wpdb->insert(" in store and "return 1 === $inserted" in store, "échec ou doublon => refus"
    assert "hash( 'sha256', $value )" in store, "rien en clair"
    auth = _src("auth")
    assert auth.index("Signature::verify(") < auth.index("Seen_Store::consume(")


def test_le_secret_vient_d_une_constante_ou_d_une_option_chiffree_jamais_en_clair():
    config = _src("config")
    assert "OPSYS_CONNECT_SECRET" in config and "sodium_crypto_secretbox" in config and "OPSYS_CONNECT_KEY" in config
    for nom, source in _tous().items():
        for appel in re.findall(r"(?:update|add)_option\(([^;]+);", source):
            assert appel.strip().startswith("Config::SEALED_OPTION"), (nom, appel)
    assert "update_option( Config::SEALED_OPTION, $sealed, false )" in (
        INCLUDES / "class-opsys-connect-cli.php"
    ).read_text(encoding="utf-8")
    assert "strlen( OPSYS_CONNECT_SECRET ) >= Signature::MIN_SECRET_LEN" in config


def test_l_utilisateur_de_service_refuse_les_droits_dangereux():
    config = _src("config")
    dangereux = re.search(r"\$dangerous\s*=\s*array\((.+?)\);", config, re.DOTALL).group(1)
    for droit in (
        "manage_options",
        "publish_posts",
        "publish_pages",
        "edit_published_posts",
        "edit_others_posts",
        "unfiltered_html",
        "install_plugins",
        "edit_users",
    ):
        assert f"'{droit}'" in dangereux
    installateur = _src("installer")
    role = re.search(r"add_role\((.+?)\);", installateur, re.DOTALL).group(1)
    droits_donnes = set(re.findall(r"'(\w+)'\s*=>\s*true", role))
    assert droits_donnes == {"read", "edit_posts", "upload_files"}  # + Config::CAPABILITY
    assert "Config::CAPABILITY" in role


def test_le_contenu_est_assaini_et_les_donnees_sont_slashees():
    contenu = _src("content")
    for fonction in (
        "sanitize_text_field",
        "wp_kses_post",
        "sanitize_textarea_field",
        "sanitize_title",
        "wp_slash",
        "esc_url_raw",
    ):
        assert fonction in contenu, fonction
    assert contenu.count("wp_slash(") >= 2
    assert re.search(r"in_array\( \$params\['statut'\], array\( 'draft', 'pending' \), true \)", contenu)
    assert "'opsys_publication_sans_jeton'" in contenu and "'opsys_etat_non_modifiable'" in contenu
    assert "is_managed(" in contenu and "_opsys_managed" in contenu


def test_les_medias_sont_verifies_par_leurs_octets():
    media = _src("media")
    types_php = dict(re.findall(r"'(image/[a-z]+)'\s*=>\s*'(\w+)'", media))
    assert types_php == {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
    for exigence in (
        "new \\finfo( FILEINFO_MIME_TYPE )",
        "getimagesizefromstring",
        "wp_upload_bits",
        "wp_check_filetype",
        "hash_equals",
        "base64_decode( $params['contenu_base64'], true )",
        "stripos( $bytes, '<?php' )",
    ):
        assert exigence in media, exigence
    assert "svg" not in media.lower() and "application/pdf" not in media
    assert media.index("hash_equals") < media.index("self::inspect(") < media.index("self::store(")


def test_la_desinstallation_nettoie():
    assert "Installer::uninstall()" in (PLUGIN / "uninstall.php").read_text(encoding="utf-8")
    installateur = _src("installer")
    for appel in ("Seen_Store::drop()", "remove_role(", "delete_option(", "wp_clear_scheduled_hook("):
        assert appel in installateur


def test_la_publication_est_desactivee_sans_identifiant_de_site_ni_secret():
    publicateur = _src("publisher")
    assert "null === $site_id || null === $secret" in publicateur and "'opsys_publication_desactivee'" in publicateur
    assert publicateur.index("opsys_publication_desactivee") < publicateur.index("Content::load_managed")


def test_le_code_python_n_importe_jamais_le_plugin():
    """Isolation GPL : aucun module Python du dépôt n'importe le dossier du plugin ni ne désigne son chemin en dur. Seul
    l'analyseur le LIT, comme du texte, à partir d'un chemin qu'on lui passe."""
    import ast

    sources = list((RACINE / "departments" / "m07-marketing" / "src").rglob("*.py")) + list(
        (RACINE / "src").rglob("*.py")
    )
    assert len(sources) > 300
    for source in sources:
        arbre = ast.parse(source.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            noms: list[str] = []
            if isinstance(noeud, ast.Import):
                noms = [a.name for a in noeud.names]
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                noms = [noeud.module]
            assert not any(n.split(".")[0] in {"integrations", "opsys_connect"} for n in noms), source
            if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str) and source.name != "analyse_php.py":
                assert not noeud.value.startswith("integrations/wordpress") or len(noeud.value) > 200, (
                    source,
                    noeud.value,
                )


def test_aucun_secret_ni_cle_dans_le_plugin():
    motifs = [
        r"sk-[A-Za-z0-9_-]{8,}",
        r"AIza[0-9A-Za-z_-]{20,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{16,}",
        r"[0-9a-f]{64}(?!.*example)",
    ]
    for chemin in PLUGIN.rglob("*"):
        if chemin.is_file() and chemin.name != "LICENSE":
            texte = chemin.read_text(encoding="utf-8")
            for motif in motifs[:4]:
                assert re.search(motif, texte) is None, (chemin, motif)
    assert not (PLUGIN / "vecteurs").exists()


@pytest.mark.parametrize("fichier", sorted(p.name for p in INCLUDES.glob("class-*.php")))
def test_chaque_classe_declare_son_espace_de_noms_et_son_propos(fichier):
    source = (INCLUDES / fichier).read_text(encoding="utf-8")
    assert "namespace OpsysConnect;" in source and "@package OpsysConnect" in source and "final class " in source


def test_l_ordre_des_constats_du_jeton_est_celui_du_verificateur_de_reference_et_des_vecteurs(vecteurs):
    """Le texte PHP de `Approval::verify` rend ses constats dans le même ordre que la référence : une garde retirée ou
    déplacée dans le PHP se voit ici, faute de pouvoir exécuter le plugin."""
    php = _src("approval")
    corps = php[php.index("public static function verify"):php.index("private static function structure_is_invalid")]
    ordre = [
        "self::MALFORMED", "self::INVALID_SIGNATURE", "self::INVALID_FIELD", "self::EXCESSIVE_LIFETIME",
        "self::EXPIRED",
        "self::ISSUED_IN_FUTURE", "self::WRONG_SITE", "self::WRONG_POST", "self::WRONG_FINGERPRINT",
        "self::ACTION_NOT_ALLOWED", "self::INVALID_SCHEDULE",
    ]
    positions = [corps.index(f"return array( {c}, null )") for c in ordre]
    assert positions == sorted(positions), dict(zip(ordre, positions, strict=True))
    assert "hash_equals( $current_hash, $claims['content_sha256'] )" in corps
    assert corps.index("hash_equals( $expected_mac, $mac )") < corps.index("json_decode( $raw )")
    assert "self::OK, $claims" in corps and corps.count("return array( self::OK") == 1
    assert "$claims['site_id'] !== $expected_site" in corps and "$claims['post_id'] !== $expected_post" in corps


def test_l_utilisateur_de_service_est_verifie_avant_d_etre_adopte():
    auth = _src("auth")
    corps = auth[auth.index("private static function authenticate"):]
    ordre = ["Config::agent_user()", "is_wp_error( $user )", "return $user;", "wp_set_current_user( $user->ID )"]
    positions = [corps.index(e) for e in ordre]
    assert positions == sorted(positions), dict(zip(ordre, positions, strict=True))
