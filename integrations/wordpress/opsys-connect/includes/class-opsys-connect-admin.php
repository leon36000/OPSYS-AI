<?php
/**
 * Page d'état (lecture seule) sous Réglages : le plugin dit s'il est prêt, sans jamais afficher un secret. Aucun formulaire,
 * donc aucune action a protéger par un nonce ; l'accès exige la capacité manage_options.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Page d'état.
 */
final class Admin {

	/**
	 * Ajoute la page.
	 */
	public static function menu(): void {
		add_options_page(
			__( 'OPSYS Connect', 'opsys-connect' ),
			__( 'OPSYS Connect', 'opsys-connect' ),
			'manage_options',
			'opsys-connect',
			array( self::class, 'render' )
		);
	}

	/**
	 * Affiche l'état.
	 */
	public static function render(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		$agent = Config::agent_user();
		$rows  = array(
			__( 'Version du plugin', 'opsys-connect' )           => OPSYS_CONNECT_VERSION,
			__( 'Secret partagé configuré', 'opsys-connect' )    => null !== Config::secret() ? __( 'oui', 'opsys-connect' ) : __( 'non', 'opsys-connect' ),
			__( 'Identifiant du site', 'opsys-connect' )         => (string) Config::site_id(),
			__( 'Publication activée', 'opsys-connect' )         => null !== Config::site_id() ? __( 'oui', 'opsys-connect' ) : __( 'non', 'opsys-connect' ),
			__( 'HTTPS', 'opsys-connect' )                       => is_ssl() ? __( 'oui', 'opsys-connect' ) : __( 'non', 'opsys-connect' ),
			__( 'Utilisateur de service sans droit dangereux', 'opsys-connect' ) => is_wp_error( $agent ) ? $agent->get_error_message() : __( 'oui', 'opsys-connect' ),
		);
		echo '<div class="wrap"><h1>' . esc_html__( 'OPSYS Connect', 'opsys-connect' ) . '</h1>';
		echo '<p>' . esc_html__( 'Ce plugin ne publie rien sans le jeton d\'approbation de la direction. Aucun secret n\'est affiché ici.', 'opsys-connect' ) . '</p>';
		echo '<table class="widefat striped"><tbody>';
		foreach ( $rows as $label => $value ) {
			echo '<tr><th scope="row">' . esc_html( $label ) . '</th><td>' . esc_html( $value ) . '</td></tr>';
		}
		echo '</tbody></table>';
		echo '<p>' . esc_html__( 'Adresse de l\'interface :', 'opsys-connect' ) . ' <code>' . esc_html( rest_url( Rest::API_NAMESPACE ) ) . '</code></p></div>';
	}
}
