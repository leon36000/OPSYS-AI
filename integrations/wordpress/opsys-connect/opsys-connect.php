<?php
/**
 * Plugin Name:       OPSYS Connect
 * Description:       Connecteur mince et signé entre un site WordPress et OPSYS-AI : brouillons, médias, état. Aucune publication sans le jeton d'approbation de la direction, lié à l'empreinte du contenu.
 * Version:           0.1.0
 * Requires at least: 6.9
 * Requires PHP:      8.1
 * Author:            OPSYS-AI
 * License:           GPL-2.0-or-later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       opsys-connect
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

define( 'OPSYS_CONNECT_VERSION', '0.1.0' );
define( 'OPSYS_CONNECT_DIR', plugin_dir_path( __FILE__ ) );

require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-signature.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-fingerprint.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-approval.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-config.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-seen-store.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-auth.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-guard.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-content.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-media.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-publisher.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-rest.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-installer.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-admin.php';
require_once OPSYS_CONNECT_DIR . 'includes/class-opsys-connect-cli.php';

register_activation_hook( __FILE__, array( Installer::class, 'activate' ) );
register_deactivation_hook( __FILE__, array( Installer::class, 'deactivate' ) );

add_action( 'rest_api_init', array( Rest::class, 'register_routes' ) );
add_action( Installer::PURGE_HOOK, array( Installer::class, 'purge' ) );
add_action( 'admin_menu', array( Admin::class, 'menu' ) );
add_filter( 'wp_insert_post_data', array( Guard::class, 'filter_post_data' ), 99 );

if ( defined( 'WP_CLI' ) && WP_CLI ) {
	\WP_CLI::add_command( 'opsys-connect', Cli::class );
}
