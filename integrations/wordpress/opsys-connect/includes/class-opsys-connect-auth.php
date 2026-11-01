<?php
/**
 * Authentification des requêtes REST : rien ne passe sans signature valide, nonce neuf et utilisateur de service sûr.
 *
 * Ordre (chaque refus est un WP_Error avec son code HTTP) : HTTPS, configuration, forme de la requête (aucun paramètre de
 * requête, corps borné), identifiant de clé, signature (temps constant, fenêtre de 300 s), nonce à usage unique (consommé
 * APRÈS une signature valide : une requête non authentique ne remplit pas la table), utilisateur de service sans droit
 * dangereux, capacités WordPress requises. Les routes n'ont pas de validation de paramètres avant cette étape.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Authentification.
 */
final class Auth {

	public const MAX_BODY       = 1000000;
	public const MAX_MEDIA_BODY = 12000000;

	/**
	 * Indique qu'une requête OPSYS authentifiée est en cours de traitement (utilisé par Guard).
	 *
	 * @var bool
	 */
	public static bool $active = false;

	/**
	 * Lecture seule.
	 *
	 * @param \WP_REST_Request $request Requête.
	 * @return true|\WP_Error
	 */
	public static function check_read( \WP_REST_Request $request ) {
		return self::authenticate( $request, 'read', self::MAX_BODY );
	}

	/**
	 * Écriture de brouillons et lecture d'état.
	 *
	 * @param \WP_REST_Request $request Requête.
	 * @return true|\WP_Error
	 */
	public static function check_edit( \WP_REST_Request $request ) {
		return self::authenticate( $request, 'edit_posts', self::MAX_BODY );
	}

	/**
	 * Téléversement de médias.
	 *
	 * @param \WP_REST_Request $request Requête.
	 * @return true|\WP_Error
	 */
	public static function check_upload( \WP_REST_Request $request ) {
		return self::authenticate( $request, 'upload_files', self::MAX_MEDIA_BODY );
	}

	/**
	 * Code d'erreur public pour un constat de Signature.
	 *
	 * @param string $verdict Constat.
	 */
	private static function signature_error( string $verdict ): \WP_Error {
		$codes = array(
			Signature::MISSING_HEADER    => 'opsys_en_tete_manquant',
			Signature::INVALID_TIMESTAMP => 'opsys_horodatage_invalide',
			Signature::INVALID_NONCE     => 'opsys_nonce_invalide',
			Signature::MALFORMED         => 'opsys_signature_malformee',
			Signature::OUT_OF_WINDOW     => 'opsys_horodatage_hors_fenetre',
			Signature::INVALID_SIGNATURE => 'opsys_signature_invalide',
		);
		return new \WP_Error( $codes[ $verdict ] ?? 'opsys_signature_invalide', 'Requête non authentifiée.', array( 'status' => 401 ) );
	}

	/**
	 * Authentifie la requête.
	 *
	 * @param \WP_REST_Request $request    Requête.
	 * @param string           $capability Capacité WordPress requise de l'utilisateur de service.
	 * @param int              $max_body   Taille maximale du corps.
	 * @return true|\WP_Error
	 */
	private static function authenticate( \WP_REST_Request $request, string $capability, int $max_body ) {
		if ( ! is_ssl() && ! Config::allow_http() ) {
			return new \WP_Error( 'opsys_https_requis', 'HTTPS est requis.', array( 'status' => 403 ) );
		}
		$secret = Config::secret();
		if ( null === $secret ) {
			return new \WP_Error( 'opsys_non_configure', "Le plugin n'est pas configuré.", array( 'status' => 503 ) );
		}
		$query = $request->get_query_params();
		unset( $query['rest_route'] );
		if ( array() !== $query ) {
			return new \WP_Error( 'opsys_query_interdite', 'Aucun paramètre de requête.', array( 'status' => 400 ) );
		}
		$body = $request->get_body();
		if ( strlen( $body ) > $max_body ) {
			return new \WP_Error( 'opsys_corps_trop_grand', 'Corps trop grand.', array( 'status' => 413 ) );
		}
		$headers = array(
			'x-opsys-timestamp' => $request->get_header( 'x-opsys-timestamp' ),
			'x-opsys-nonce'     => $request->get_header( 'x-opsys-nonce' ),
			'x-opsys-signature' => $request->get_header( 'x-opsys-signature' ),
		);
		$key_id  = $request->get_header( 'x-opsys-key-id' );
		if ( ! is_string( $key_id ) || ! hash_equals( Config::key_id(), $key_id ) ) {
			return new \WP_Error( 'opsys_cle_inconnue', 'Clé inconnue.', array( 'status' => 401 ) );
		}
		$now     = time();
		$verdict = Signature::verify( $secret, $request->get_method(), $request->get_route(), $body, array_filter( $headers, 'is_string' ), $now );
		if ( Signature::OK !== $verdict ) {
			return self::signature_error( $verdict );
		}
		$timestamp = (int) $headers['x-opsys-timestamp'];
		if ( ! Seen_Store::consume( Seen_Store::KIND_NONCE, (string) $headers['x-opsys-nonce'], $timestamp + 2 * Signature::WINDOW ) ) {
			return new \WP_Error( 'opsys_rejeu', 'Requête déjà vue.', array( 'status' => 401 ) );
		}
		if ( 0 === wp_rand( 0, 49 ) ) {
			Seen_Store::purge( $now );
		}
		$user = Config::agent_user();
		if ( is_wp_error( $user ) ) {
			return $user;
		}
		wp_set_current_user( $user->ID );
		if ( ! current_user_can( Config::CAPABILITY ) || ! current_user_can( $capability ) ) {
			return new \WP_Error( 'opsys_capacite_insuffisante', "Droits insuffisants de l'utilisateur de service.", array( 'status' => 403 ) );
		}
		self::$active = true;
		return true;
	}
}
