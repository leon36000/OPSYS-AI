<?php
/**
 * Commandes WP-CLI : enregistrer le secret partagé chiffré sans le passer en argument (pas de trace dans l'historique du shell).
 *
 *   printf '%s' "$SECRET" | wp opsys-connect set-secret
 *   wp opsys-connect status
 *
 * Le secret est lu sur l'entrée standard, chiffré avec la clé de la constante OPSYS_CONNECT_KEY (wp-config.php), puis
 * enregistré dans une option NON chargée automatiquement. Sans cette constante, rien n'est enregistré : préférer alors la
 * constante OPSYS_CONNECT_SECRET dans wp-config.php.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Commandes.
 */
final class Cli {

	/**
	 * Enregistre le secret partagé (lu sur l'entrée standard), chiffré.
	 *
	 * ## EXAMPLES
	 *
	 *     printf '%s' "$SECRET" | wp opsys-connect set-secret
	 *
	 * @subcommand set-secret
	 *
	 * @param string[]             $args       Arguments positionnels (aucun).
	 * @param array<string,string> $assoc_args Arguments nommés (aucun).
	 */
	public function set_secret( $args, $assoc_args ): void {
		$secret = stream_get_contents( STDIN );
		if ( ! is_string( $secret ) || strlen( $secret ) < Signature::MIN_SECRET_LEN ) {
			\WP_CLI::error( 'Secret absent ou trop court (32 octets au moins).' );
			return;
		}
		$sealed = Config::seal( $secret );
		if ( null === $sealed ) {
			\WP_CLI::error( 'Chiffrement impossible : définir OPSYS_CONNECT_KEY (32 octets au moins) dans wp-config.php.' );
			return;
		}
		update_option( Config::SEALED_OPTION, $sealed, false );
		\WP_CLI::success( 'Secret enregistré (chiffré).' );
	}

	/**
	 * Affiche l'état de la configuration (sans secret).
	 *
	 * @param string[]             $args       Arguments positionnels (aucun).
	 * @param array<string,string> $assoc_args Arguments nommés (aucun).
	 */
	public function status( $args, $assoc_args ): void {
		$agent = Config::agent_user();
		\WP_CLI::line( 'secret : ' . ( null !== Config::secret() ? 'configuré' : 'absent' ) );
		\WP_CLI::line( 'site_id : ' . ( Config::site_id() ?? 'absent (publication désactivée)' ) );
		\WP_CLI::line( 'utilisateur de service : ' . ( is_wp_error( $agent ) ? $agent->get_error_message() : 'sûr' ) );
	}
}
