<?php
/**
 * Activation, désactivation, désinstallation.
 *
 * Activation : table des valeurs à usage unique, rôle opsys_agent (lire, écrire des brouillons, téléverser ; AUCUN droit de
 * publier, d'administrer ou d'écrire du HTML non filtré), utilisateur de service sans mot de passe utilisable (mot de passe
 * aléatoire jamais affiché ni enregistré), purge quotidienne. Désinstallation : table, rôle, options.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Cycle de vie.
 */
final class Installer {

	public const PURGE_HOOK = 'opsys_connect_purge';

	/**
	 * Activation du plugin.
	 */
	public static function activate(): void {
		Seen_Store::install();
		add_role(
			Config::AGENT_ROLE,
			'OPSYS Connect',
			array(
				'read'              => true,
				'edit_posts'        => true,
				'upload_files'      => true,
				Config::CAPABILITY  => true,
			)
		);
		if ( false === get_user_by( 'login', Config::agent_login() ) ) {
			wp_insert_user(
				array(
					'user_login'   => Config::agent_login(),
					'user_pass'    => wp_generate_password( 64, true, true ),
					'role'         => Config::AGENT_ROLE,
					'display_name' => 'OPSYS Connect',
				)
			);
		}
		if ( ! wp_next_scheduled( self::PURGE_HOOK ) ) {
			wp_schedule_event( time() + HOUR_IN_SECONDS, 'daily', self::PURGE_HOOK );
		}
	}

	/**
	 * Désactivation du plugin.
	 */
	public static function deactivate(): void {
		wp_clear_scheduled_hook( self::PURGE_HOOK );
	}

	/**
	 * Purge quotidienne des valeurs expirées.
	 */
	public static function purge(): void {
		Seen_Store::purge( time() );
	}

	/**
	 * Désinstallation : table, rôle, options.
	 */
	public static function uninstall(): void {
		Seen_Store::drop();
		remove_role( Config::AGENT_ROLE );
		delete_option( Config::SEALED_OPTION );
		wp_clear_scheduled_hook( self::PURGE_HOOK );
	}
}
