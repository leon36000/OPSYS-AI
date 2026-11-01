"""L'analyse statique maison du plugin PHP : elle laisse passer le plugin, et elle ATTRAPE chaque motif dangereux.

Rappel : ceci n'est ni `php -l`, ni PHPCS, ni Plugin Check, ni une exécution dans WordPress. Chaque test « hostile »
prouve qu'une règle du linter maison tient ; un plugin qui passe ici n'est pas pour autant sûr.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m7_marketing.wordpress import analyse_php

FICTIF = True
DOSSIER_PLUGIN = Path(__file__).resolve().parents[4] / "integrations" / "wordpress" / "opsys-connect"
GARDE = "<?php\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\n"


def _codes(corps: str, nom: str = "includes/x.php", *, mode: str = "plugin") -> list[str]:
    return [v.code for v in analyse_php.analyser_source(GARDE + corps, nom, mode=mode)]


def test_le_plugin_livre_passe_l_analyse_sans_violation():
    assert analyse_php.analyser_dossier(DOSSIER_PLUGIN) == []


def test_le_plugin_est_bien_sous_gplv2_et_isole_dans_son_dossier():
    entete = analyse_php.en_tete_plugin((DOSSIER_PLUGIN / "opsys-connect.php").read_text(encoding="utf-8"))
    assert entete["License"] == "GPL-2.0-or-later" and entete["Requires PHP"] == "8.1"
    texte = (DOSSIER_PLUGIN / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in texte and "Version 2, June 1991" in texte


@pytest.mark.parametrize(
    ("corps", "code"),
    [
        ("eval( $x );", "PHP-FONCTION-INTERDITE"),
        ("assert( $x );", "PHP-FONCTION-INTERDITE"),
        ("shell_exec( 'ls' );", "PHP-FONCTION-INTERDITE"),
        ("system( $c );", "PHP-FONCTION-INTERDITE"),
        ("passthru( $c );", "PHP-FONCTION-INTERDITE"),
        ("exec( $c );", "PHP-FONCTION-INTERDITE"),
        ("popen( $c, 'r' );", "PHP-FONCTION-INTERDITE"),
        ("proc_open( $c, array(), $p );", "PHP-FONCTION-INTERDITE"),
        ("$y = unserialize( $x );", "PHP-FONCTION-INTERDITE"),
        ("$y = maybe_unserialize( $x );", "PHP-FONCTION-INTERDITE"),
        ("extract( $_POST );", "PHP-FONCTION-INTERDITE"),
        ("call_user_func( $f );", "PHP-FONCTION-INTERDITE"),
        ("$f = create_function( '', $c );", "PHP-FONCTION-INTERDITE"),
        ("$d = str_rot13( $x );", "PHP-FONCTION-INTERDITE"),
        ("$d = gzinflate( $x );", "PHP-FONCTION-INTERDITE"),
        ("var_dump( $x );", "PHP-FONCTION-INTERDITE"),
        ("error_log( $secret );", "PHP-FONCTION-INTERDITE"),
        ("$o = `ls`;", "PHP-ANTIGUILLEMET"),
        ("$y = $_REQUEST['a'];", "PHP-SUPERGLOBALE"),
        ("$y = $_GET['a'];", "PHP-SUPERGLOBALE"),
        ("$y = $_POST['a'];", "PHP-SUPERGLOBALE"),
        ("$y = $_COOKIE['a'];", "PHP-SUPERGLOBALE"),
        ("$y = $_FILES['a'];", "PHP-SUPERGLOBALE"),
        ("$y = $_SERVER['REMOTE_ADDR'];", "PHP-SUPERGLOBALE"),
        ("$y = $GLOBALS['wpdb'];", "PHP-SUPERGLOBALE"),
        ("$$nom = 1;", "PHP-VARIABLE-VARIABLE"),
        ("add_action( 'wp_ajax_nopriv_x', 'f' );", "PHP-AJAX-ANONYME"),
        ("require_once $dossier . 'x.php';", "PHP-INCLUSION-DYNAMIQUE"),
        ("include( $_SERVER['x'] );", "PHP-INCLUSION-DYNAMIQUE"),
        ("$r = wp_remote_get( 'https://example.test' );", "PHP-APPEL-SORTANT"),
        ("$r = wp_safe_remote_post( $u );", "PHP-APPEL-SORTANT"),
        ("$c = curl_init( $u );", "PHP-APPEL-SORTANT"),
        ("$d = file_get_contents( $u );", "PHP-APPEL-SORTANT"),
        ("$s = fsockopen( $h, 80 );", "PHP-APPEL-SORTANT"),
        ("file_put_contents( $p, $d );", "PHP-ECRITURE-DISQUE"),
        ("$h = fopen( $p, 'w' );", "PHP-ECRITURE-DISQUE"),
        ("unlink( $p );", "PHP-ECRITURE-DISQUE"),
        ("mkdir( $p );", "PHP-ECRITURE-DISQUE"),
        ("copy( $a, $b );", "PHP-ECRITURE-DISQUE"),
        ("rename( $a, $b );", "PHP-ECRITURE-DISQUE"),
        ("move_uploaded_file( $a, $b );", "PHP-ECRITURE-DISQUE"),
        ("$r = wp_handle_upload( $f, array() );", "PHP-ECRITURE-DISQUE"),
        ('$wpdb->query( "DELETE FROM x WHERE a = $id" );', "PHP-SQL-NON-PREPARE"),
        ("$wpdb->query( 'DELETE FROM x WHERE a = ' . $id );", "PHP-SQL-NON-PREPARE"),
        ("$wpdb->get_results( $sql );", "PHP-SQL-NON-PREPARE"),
        ('$wpdb->get_var( "SELECT {$col} FROM t" );', "PHP-SQL-NON-PREPARE"),
        ("$x = $wpdb->prepare( 'SELECT * FROM ' . $table . ' WHERE a = %d', $id );", "PHP-SQL-CONCATENE"),
        ('$x = $wpdb->prepare( "SELECT * FROM {$table} WHERE a = %d", $id );', "PHP-SQL-CONCATENE"),
        ("update_option( 'opsys_connect_secret', $s );", "PHP-SECRET-EN-OPTION"),
        ("update_option( 'opsys_api_key', $s );", "PHP-SECRET-EN-OPTION"),
        ("add_role( 'r', 'R', array( 'manage_options' => true ) );", "PHP-CAPACITE-DANGEREUSE"),
        ("add_role( 'r', 'R', array( 'unfiltered_html' => true ) );", "PHP-CAPACITE-DANGEREUSE"),
        ("add_role( 'r', 'R', array( 'publish_posts' => true ) );", "PHP-CAPACITE-DANGEREUSE"),
        ("$r = get_role( 'x' ); $r->add_cap( 'install_plugins' );", "PHP-CAPACITE-DANGEREUSE"),
        ("register_rest_route( 'a/v1', '/x', array( 'callback' => 'f' ) );", "PHP-ROUTE-SANS-PERMISSION"),
        (
            "register_rest_route( 'a/v1', '/x', array( 'callback' => 'f', 'permission_callback' => '__return_true' "
            ") );",
            "PHP-ROUTE-OUVERTE",
        ),
        (
            "register_rest_route( 'a/v1', '/x', array( 'callback' => 'f', 'permission_callback' => __return_true ) );",
            "PHP-ROUTE-OUVERTE",
        ),
        ("echo $titre;", "PHP-SORTIE-NON-ECHAPPEE"),
        ("echo '<p>' . $titre . '</p>';", "PHP-SORTIE-NON-ECHAPPEE"),
        ('echo "<p>$titre</p>";', "PHP-SORTIE-NON-ECHAPPEE"),
        ("print $titre;", "PHP-SORTIE-NON-ECHAPPEE"),
        ("echo strtoupper( $titre );", "PHP-SORTIE-NON-ECHAPPEE"),
    ],
)
def test_chaque_motif_dangereux_est_attrape(corps, code):
    assert code in _codes(corps)


@pytest.mark.parametrize(
    "corps",
    [
        "// eval( $x ); commentaire",
        "/* system( 'ls' ); */",
        "# exec( $c );",
        "$texte = 'eval( $x ) et $_POST et system(ls)';",
        '$texte = "eval( x ) et \\$_POST";',
        "$wpdb->query( $wpdb->prepare( 'DELETE FROM %i WHERE a < %d', $t, $n ) );",
        "$wpdb->query( 'TRUNCATE TABLE wp_x' );",
        "$wpdb->prepare( 'SELECT * FROM %i WHERE a = %d', $table, $id );",
        "$wpdb->insert( $table, array( 'a' => 1 ), array( '%d' ) );",
        'dbDelta( "CREATE TABLE {$table} ( a int )" );',
        "$this->exec( $x );",
        "$objet->system( $x );",
        "self::assert( $x );",
        "function evaluer( $x ) { return $x; }",
        "echo esc_html( $titre );",
        "echo '<p>' . esc_html( $a ) . esc_url( $u ) . absint( $n ) . '</p>';",
        "echo wp_kses_post( $html );",
        "echo esc_html__( 'Texte', 'opsys-connect' );",
        "echo '<td>' . esc_html( wp_json_encode( $v ) ) . '</td>';",
        "register_rest_route( 'a/v1', '/x', array( 'callback' => 'f', 'permission_callback' => array( Auth::class, "
        "'c' ) ) );",
        "add_role( 'r', 'R', array( 'read' => true, 'edit_posts' => true, 'upload_files' => true ) );",
        "update_option( Config::SEALED_OPTION, $sealed, false );",
        "update_option( 'opsys_connect_version', '1', false );",
        "require_once OPSYS_CONNECT_DIR . 'includes/a.php';",
        "require_once __DIR__ . '/a.php';",
        "if ( hash_equals( $expected, $received ) ) { return 1; }",
    ],
)
def test_les_faux_positifs_courants_ne_sont_pas_signales(corps):
    assert _codes(corps) == []


def test_un_heredoc_et_un_nowdoc_ne_cachent_pas_de_code_et_ne_confondent_pas_le_lexeur():
    source = GARDE + "$a = <<<TXT\neval( $x );\nTXT;\n$b = <<<'RAW'\n$y = $_POST;\nRAW;\n$c = $_GET['x'];\n"
    violations = analyse_php.analyser_source(source, "includes/x.php")
    assert [v.code for v in violations] == ["PHP-SUPERGLOBALE"]
    assert violations[0].ligne == 10


def test_les_numeros_de_ligne_sont_justes():
    violations = analyse_php.analyser_source(GARDE + "\n\n$a = 1;\neval( $x );\n", "includes/x.php")
    assert [(v.code, v.ligne) for v in violations] == [("PHP-FONCTION-INTERDITE", 7)]


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("<?php\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\nfunction f( {\n", "PHP-DESEQUILIBRE"),
        (
            "<?php\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\nfunction f() { return 1; } }\n",
            "PHP-DESEQUILIBRE",
        ),
        ("<?php\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\n$a = array( 1, 2 ;\n", "PHP-DESEQUILIBRE"),
        ("<?php\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\n$a = [ 1, 2 );\n", "PHP-DESEQUILIBRE"),
        ("<?php\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\n?>\n", "PHP-BALISE-FERMANTE"),
        (
            "<?php\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\n?>\nTexte\n<?php\n$a = 1;\n",
            "PHP-HTML-EN-LIGNE",
        ),
        ("\ufeff<?php\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\n", "PHP-BOM"),
        ("<?\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\n", "PHP-BALISE"),
        ("Texte avant\n<?php\ndeclare( strict_types=1 );\ndefined( 'ABSPATH' ) || exit;\n", "PHP-OUVERTURE"),
        ("<?php\ndefined( 'ABSPATH' ) || exit;\n", "PHP-STRICT-TYPES"),
        ("<?php\ndeclare( strict_types=1 );\n$a = 1;\n", "PHP-GARDE-ACCES"),
    ],
)
def test_les_defauts_de_structure_sont_attrapes(source, code):
    assert code in [v.code for v in analyse_php.analyser_source(source, "includes/x.php")]


def test_le_fichier_de_desinstallation_exige_sa_propre_garde():
    sans = analyse_php.analyser_source("<?php\ndeclare( strict_types=1 );\n$a = 1;\n", "uninstall.php")
    assert "PHP-GARDE-ACCES" in [v.code for v in sans]
    avec = analyse_php.analyser_source(
        "<?php\ndeclare( strict_types=1 );\ndefined( 'WP_UNINSTALL_PLUGIN' ) || exit;\n", "uninstall.php"
    )
    assert avec == []


@pytest.mark.parametrize(
    "corps",
    [
        "if ( $expected === $received ) { return true; }",
        "return $mac == $expected_mac;",
        "if ( $received !== $expected ) { return false; }",
        "return $signature === $x;",
        "return $x != $token;",
    ],
)
def test_un_mac_ou_une_signature_compare_sans_hash_equals_est_attrape_dans_les_classes_sensibles(corps):
    codes = _codes(corps, "includes/class-opsys-connect-signature.php")
    assert "PHP-COMPARAISON-NON-CONSTANTE" in codes
    assert "PHP-COMPARAISON-NON-CONSTANTE" not in _codes(corps, "includes/class-opsys-connect-rest.php")


def test_un_script_d_essai_a_le_droit_de_lire_des_fichiers_et_d_afficher_mais_pas_d_executer():
    corps = "$h = fopen( $argv[1], 'r' ); fwrite( STDERR, var_export( $x, true ) ); echo $x;\neval( $c );\n"
    codes = _codes(corps, "tests/essai.php", mode="test")
    assert codes == ["PHP-FONCTION-INTERDITE"], codes


def test_le_dossier_signale_un_en_tete_manquant_ou_une_licence_absente(tmp_path):
    (tmp_path / "opsys-connect.php").write_text(
        "<?php\n/**\n * Plugin Name: X\n * License: Proprietary\n */\ndeclare( strict_types=1 );\ndefined( "
        "'ABSPATH' ) || exit;\n",
        encoding="utf-8",
    )
    codes = [v.code for v in analyse_php.analyser_dossier(tmp_path)]
    assert codes.count("PLUGIN-EN-TETE") >= 4 and "PLUGIN-LICENCE" in codes
    assert [v.code for v in analyse_php.analyser_dossier(tmp_path / "vide")] == [
        "PLUGIN-FICHIER-PRINCIPAL",
        "PLUGIN-LICENCE",
    ]
