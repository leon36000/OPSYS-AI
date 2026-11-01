<?php
/**
 * Vérification de la signature des requêtes OPSYS (protocole opsys-connect-sig/v1).
 *
 * Classe pure : aucune fonction WordPress, aucune base de données. Elle suit à la lettre la spécification publiée dans
 * les vecteurs de test partagés (contracts/opsys-connect-vecteurs.v1.json, côté OPSYS).
 *
 * Chaîne canonique (UTF-8, séparateurs LF, aucun LF final) :
 * OPSYS-CONNECT-V1, MÉTHODE en majuscules, route REST sans /wp-json ni requête, horodatage (10 chiffrés), nonce, SHA-256
 * hexadécimal minuscule du corps exact.
 * Signature : "v1=" suivi du HMAC-SHA256 hexadécimal minuscule de la chaîne canonique, avec le secret partagé en UTF-8.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Signature des requêtes.
 */
final class Signature {

	public const PREFIX         = 'OPSYS-CONNECT-V1';
	public const WINDOW         = 300;
	public const MIN_SECRET_LEN = 32;

	public const OK                 = 'OK';
	public const MISSING_HEADER     = 'EN_TETE_MANQUANT';
	public const INVALID_TIMESTAMP  = 'HORODATAGE_INVALIDE';
	public const INVALID_NONCE      = 'NONCE_INVALIDE';
	public const MALFORMED          = 'SIGNATURE_MALFORMEE';
	public const OUT_OF_WINDOW      = 'HORS_FENETRE';
	public const INVALID_SIGNATURE  = 'SIGNATURE_INVALIDE';

	/**
	 * Chaîne canonique d'une requête.
	 *
	 * @param string $method    Méthode HTTP.
	 * @param string $route     Route REST (ex. /opsys-connect/v1/drafts).
	 * @param string $timestamp Horodatage UNIX, 10 chiffrés.
	 * @param string $nonce     Nonce.
	 * @param string $body      Corps exact de la requête.
	 */
	public static function canonical( string $method, string $route, string $timestamp, string $nonce, string $body ): string {
		return implode(
			"\n",
			array(
				self::PREFIX,
				strtoupper( $method ),
				$route,
				$timestamp,
				$nonce,
				hash( 'sha256', $body ),
			)
		);
	}

	/**
	 * Signature attendue ("v1=" + hexadécimal).
	 *
	 * @param string $secret    Secret partagé.
	 * @param string $method    Méthode HTTP.
	 * @param string $route     Route REST.
	 * @param string $timestamp Horodatage.
	 * @param string $nonce     Nonce.
	 * @param string $body      Corps exact.
	 */
	public static function sign( string $secret, string $method, string $route, string $timestamp, string $nonce, string $body ): string {
		return 'v1=' . hash_hmac( 'sha256', self::canonical( $method, $route, $timestamp, $nonce, $body ), $secret );
	}

	/**
	 * Vérifie une requête. Retourne OK ou le premier constat, dans l'ordre fixe : en-tetes présents, horodatage, nonce,
	 * forme de la signature, fenêtre, signature (comparaison en temps constant). L'usage unique du nonce est vérifie
	 * par l'appelant, APRÈS une signature valide.
	 *
	 * @param string               $secret  Secret partagé.
	 * @param string               $method  Méthode HTTP.
	 * @param string               $route   Route REST.
	 * @param string               $body    Corps exact.
	 * @param array<string,string> $headers En-tetes (noms en minuscules).
	 * @param int                  $now     Instant courant (secondes UNIX).
	 */
	public static function verify( string $secret, string $method, string $route, string $body, array $headers, int $now ): string {
		$timestamp = $headers['x-opsys-timestamp'] ?? null;
		$nonce     = $headers['x-opsys-nonce'] ?? null;
		$received  = $headers['x-opsys-signature'] ?? null;
		if ( ! is_string( $timestamp ) || ! is_string( $nonce ) || ! is_string( $received ) ) {
			return self::MISSING_HEADER;
		}
		if ( 1 !== preg_match( '/\A[0-9]{10}\z/D', $timestamp ) ) {
			return self::INVALID_TIMESTAMP;
		}
		if ( 1 !== preg_match( '/\A[A-Za-z0-9_-]{16,64}\z/D', $nonce ) ) {
			return self::INVALID_NONCE;
		}
		if ( 1 !== preg_match( '/\Av1=[0-9a-f]{64}\z/D', $received ) ) {
			return self::MALFORMED;
		}
		if ( abs( $now - (int) $timestamp ) > self::WINDOW ) {
			return self::OUT_OF_WINDOW;
		}
		$expected = self::sign( $secret, $method, $route, $timestamp, $nonce, $body );
		return hash_equals( $expected, $received ) ? self::OK : self::INVALID_SIGNATURE;
	}
}
