<?php
/**
 * Configuration du plugin.
 *
 * Le secret partagé n'est JAMAIS une option en clair. Il vient, par ordre de préférence :
 * 1. de la constante OPSYS_CONNECT_SECRET définie dans wp-config.php (32 octets au moins) ;
 * 2. d'une option chiffrée (libsodium secretbox) dont la clé est la constante OPSYS_CONNECT_KEY de wp-config.php.
 * Sans l'un des deux, le plugin refuse toute requête (503). Les autres constantes : OPSYS_CONNECT_KEY_ID (identifiant de
 * la clé, "default"), OPSYS_CONNECT_SITE_ID (identifiant de ce site, lié aux jetons d'approbation ; sans lui la
 * publication est désactivée), OPSYS_CONNECT_AGENT_LOGIN (utilisateur de service, "opsys-agent"),
 * OPSYS_CONNECT_ALLOW_HTTP (vrai seulement en développement).
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Lecture de la configuration.
 */
final class Config {

	public const SEALED_OPTION = 'opsys_connect_secret_sealed';
	public const AGENT_ROLE    = 'opsys_agent';
	public const CAPABILITY    = 'opsys_connect_use';

	/**
	 * Secret partagé, ou null s'il n'est pas configuré correctement.
	 */
	public static function secret(): ?string {
		if ( defined( 'OPSYS_CONNECT_SECRET' ) && is_string( OPSYS_CONNECT_SECRET ) ) {
			return strlen( OPSYS_CONNECT_SECRET ) >= Signature::MIN_SECRET_LEN ? OPSYS_CONNECT_SECRET : null;
		}
		$plain = self::unseal();
		return ( null !== $plain && strlen( $plain ) >= Signature::MIN_SECRET_LEN ) ? $plain : null;
	}

	/**
	 * Identifiant de la clé annoncée par OPSYS.
	 */
	public static function key_id(): string {
		if ( defined( 'OPSYS_CONNECT_KEY_ID' ) && is_string( OPSYS_CONNECT_KEY_ID ) && 1 === preg_match( '/\A[A-Za-z0-9._-]{1,64}\z/D', OPSYS_CONNECT_KEY_ID ) ) {
			return OPSYS_CONNECT_KEY_ID;
		}
		return 'default';
	}

	/**
	 * Identifiant de ce site (lié aux jetons d'approbation), ou null : la publication est alors désactivée.
	 */
	public static function site_id(): ?string {
		if ( defined( 'OPSYS_CONNECT_SITE_ID' ) && is_string( OPSYS_CONNECT_SITE_ID ) && 1 === preg_match( '/\A[a-z0-9][a-z0-9._-]{2,63}\z/D', OPSYS_CONNECT_SITE_ID ) ) {
			return OPSYS_CONNECT_SITE_ID;
		}
		return null;
	}

	/**
	 * Identifiant de connexion de l'utilisateur de service.
	 */
	public static function agent_login(): string {
		if ( defined( 'OPSYS_CONNECT_AGENT_LOGIN' ) && is_string( OPSYS_CONNECT_AGENT_LOGIN ) && '' !== OPSYS_CONNECT_AGENT_LOGIN ) {
			return OPSYS_CONNECT_AGENT_LOGIN;
		}
		return 'opsys-agent';
	}

	/**
	 * Vrai si HTTP est toléré (développement seulement).
	 */
	public static function allow_http(): bool {
		return defined( 'OPSYS_CONNECT_ALLOW_HTTP' ) && true === OPSYS_CONNECT_ALLOW_HTTP;
	}

	/**
	 * Types de contenu que le plugin peut gérer (article et page par défaut), restreints aux types publics enregistrés.
	 *
	 * @return string[]
	 */
	public static function post_types(): array {
		$wanted = apply_filters( 'opsys_connect_post_types', array( 'post', 'page' ) );
		if ( ! is_array( $wanted ) ) {
			return array();
		}
		$public = array_keys( get_post_types( array( 'public' => true ) ) );
		return array_values( array_intersect( array_filter( $wanted, 'is_string' ), $public ) );
	}

	/**
	 * Actions de publication permises par le plugin.
	 *
	 * @return string[]
	 */
	public static function actions(): array {
		$actions = apply_filters( 'opsys_connect_actions', array( 'publish', 'schedule' ) );
		return is_array( $actions ) ? array_values( array_intersect( array( 'publish', 'schedule' ), $actions ) ) : array();
	}

	/**
	 * Clé de chiffrement de l'option (32 octets), dérivée de la constante OPSYS_CONNECT_KEY.
	 */
	private static function sealing_key(): ?string {
		if ( ! defined( 'OPSYS_CONNECT_KEY' ) || ! is_string( OPSYS_CONNECT_KEY ) || strlen( OPSYS_CONNECT_KEY ) < Signature::MIN_SECRET_LEN ) {
			return null;
		}
		if ( ! function_exists( 'sodium_crypto_generichash' ) || ! defined( 'SODIUM_CRYPTO_SECRETBOX_KEYBYTES' ) ) {
			return null;
		}
		return sodium_crypto_generichash( OPSYS_CONNECT_KEY, '', SODIUM_CRYPTO_SECRETBOX_KEYBYTES );
	}

	/**
	 * Chiffre un secret pour l'option (utilisé par la commande WP-CLI). Retourne null si le chiffrement est impossible.
	 *
	 * @param string $plain Secret en clair.
	 */
	public static function seal( string $plain ): ?string {
		$key = self::sealing_key();
		if ( null === $key || ! function_exists( 'sodium_crypto_secretbox' ) ) {
			return null;
		}
		$nonce = random_bytes( SODIUM_CRYPTO_SECRETBOX_NONCEBYTES );
		return 'v1:' . base64_encode( $nonce . sodium_crypto_secretbox( $plain, $nonce, $key ) );
	}

	/**
	 * Déchiffre l'option, ou null.
	 */
	private static function unseal(): ?string {
		$key = self::sealing_key();
		$raw = get_option( self::SEALED_OPTION, '' );
		if ( null === $key || ! is_string( $raw ) || 0 !== strpos( $raw, 'v1:' ) || ! function_exists( 'sodium_crypto_secretbox_open' ) ) {
			return null;
		}
		$decoded = base64_decode( substr( $raw, 3 ), true );
		if ( false === $decoded || strlen( $decoded ) <= SODIUM_CRYPTO_SECRETBOX_NONCEBYTES ) {
			return null;
		}
		$plain = sodium_crypto_secretbox_open(
			substr( $decoded, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES ),
			substr( $decoded, 0, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES ),
			$key
		);
		return false === $plain ? null : $plain;
	}

	/**
	 * L'utilisateur de service, SI son rôle et ses droits sont ceux attendus ; sinon une erreur qui nommé le problème.
	 * Un utilisateur de service qui pourrait publier, installer un plugin ou écrire du HTML non filtré est refusé :
	 * le jeton d'approbation serait alors contournable.
	 *
	 * @return \WP_User|\WP_Error
	 */
	public static function agent_user() {
		$user = get_user_by( 'login', self::agent_login() );
		if ( false === $user ) {
			return new \WP_Error( 'opsys_agent_absent', "L'utilisateur de service OPSYS n'existe pas.", array( 'status' => 503 ) );
		}
		$dangerous = array( 'manage_options', 'publish_posts', 'publish_pages', 'edit_published_posts', 'edit_others_posts', 'unfiltered_html', 'install_plugins', 'edit_plugins', 'edit_users', 'delete_posts' );
		foreach ( $dangerous as $capability ) {
			if ( user_can( $user, $capability ) ) {
				return new \WP_Error( 'opsys_agent_dangereux', "L'utilisateur de service a un droit qu'il ne doit pas avoir : " . $capability, array( 'status' => 503 ) );
			}
		}
		if ( array( self::AGENT_ROLE ) !== array_values( $user->roles ) ) {
			return new \WP_Error( 'opsys_agent_dangereux', "L'utilisateur de service doit porter le seul rôle opsys_agent.", array( 'status' => 503 ) );
		}
		return $user;
	}
}
