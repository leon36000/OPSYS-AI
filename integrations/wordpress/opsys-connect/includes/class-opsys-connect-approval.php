<?php
/**
 * Jeton d'approbation de publication (opsys-approval/v1).
 *
 * Format : v1.<charge utile JSON en base64url sans bourrage>.<MAC hexadécimal minuscule>.
 * MAC = HMAC-SHA256(clé d'approbation, "OPSYS-APPROVAL-V1\n" suivi de la charge base64url telle quelle).
 * Clé d'approbation = HMAC-SHA256(secret, "opsys-connect/approval/v1" suivi de l'octet 0x01) : séparation des domaines
 * avec la signature des requêtes (un MAC de requête n'est jamais un jeton valide).
 *
 * Charge utile (tous les champs, aucun autre) : v=1, approval_id, site_id, action (publish ou schedule), post_id,
 * content_sha256, iat, exp (vie de 24 h au plus), publish_at (pour schedule, sinon null), approved_by.
 *
 * Classe pure : l'usage unique de approval_id est vérifie par l'appelant (Seen_Store), après cette vérification.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Vérification des jetons d'approbation.
 */
final class Approval {

	public const OK                  = 'OK';
	public const MALFORMED           = 'JETON_MALFORME';
	public const INVALID_SIGNATURE   = 'JETON_SIGNATURE_INVALIDE';
	public const INVALID_FIELD       = 'JETON_CHAMP_INVALIDE';
	public const EXPIRED             = 'JETON_EXPIRE';
	public const EXCESSIVE_LIFETIME  = 'JETON_DUREE_EXCESSIVE';
	public const ISSUED_IN_FUTURE    = 'JETON_EMIS_DANS_LE_FUTUR';
	public const WRONG_SITE          = 'JETON_SITE_DIFFERENT';
	public const WRONG_POST          = 'JETON_ARTICLE_DIFFERENT';
	public const WRONG_FINGERPRINT   = 'JETON_EMPREINTE_DIFFERENTE';
	public const ACTION_NOT_ALLOWED  = 'JETON_ACTION_NON_PERMISE';
	public const INVALID_SCHEDULE    = 'JETON_PLANIFICATION_INVALIDE';

	public const MAX_LIFETIME = 86400;
	public const ISSUE_SKEW   = 60;

	private const MAC_PREFIX = "OPSYS-APPROVAL-V1\n";
	private const KEY_INFO   = "opsys-connect/approval/v1\x01";

	private const FIELDS = array( 'v', 'approval_id', 'site_id', 'action', 'post_id', 'content_sha256', 'iat', 'exp', 'publish_at', 'approved_by' );

	/**
	 * Clé d'approbation dérivée du secret partagé (32 octets bruts).
	 *
	 * @param string $secret Secret partagé.
	 */
	public static function derive_key( string $secret ): string {
		return hash_hmac( 'sha256', self::KEY_INFO, $secret, true );
	}

	/**
	 * Décode strictement du base64url sans bourrage (null si invalide).
	 *
	 * @param string $text Texte base64url.
	 */
	private static function b64url_decode( string $text ): ?string {
		if ( 1 !== preg_match( '/\A[A-Za-z0-9_-]+\z/D', $text ) ) {
			return null;
		}
		$raw = base64_decode( strtr( $text, '-_', '+/' ) . str_repeat( '=', ( 4 - strlen( $text ) % 4 ) % 4 ), true );
		if ( false === $raw ) {
			return null;
		}
		return rtrim( strtr( base64_encode( $raw ), '+/', '-_' ), '=' ) === $text ? $raw : null;
	}

	/**
	 * Vérifie un jeton. Retourne le code et, si OK, la charge utile décodée.
	 *
	 * Ordre : forme, MAC, décodage, champs, durée, expiration, émission, site, article, empreinte, action, planification.
	 *
	 * @param string   $secret          Secret partagé.
	 * @param string   $token           Jeton reçu.
	 * @param string   $expected_site   Identifiant de ce site.
	 * @param int      $expected_post   Article vise.
	 * @param string   $current_hash    Empreinte actuelle du contenu stocké.
	 * @param int      $now             Instant courant (secondes UNIX).
	 * @param string[] $allowed_actions Actions permises.
	 * @return array{0:string,1:?array<string,mixed>}
	 */
	public static function verify( string $secret, string $token, string $expected_site, int $expected_post, string $current_hash, int $now, array $allowed_actions ): array {
		$parts = explode( '.', $token );
		if ( 3 !== count( $parts ) || 'v1' !== $parts[0] ) {
			return array( self::MALFORMED, null );
		}
		list( , $payload_b64, $mac ) = $parts;
		if ( '' === $payload_b64 || 1 !== preg_match( '/\A[0-9a-f]{64}\z/D', $mac ) ) {
			return array( self::MALFORMED, null );
		}
		$expected_mac = hash_hmac( 'sha256', self::MAC_PREFIX . $payload_b64, self::derive_key( $secret ) );
		if ( ! hash_equals( $expected_mac, $mac ) ) {
			return array( self::INVALID_SIGNATURE, null );
		}
		$raw = self::b64url_decode( $payload_b64 );
		if ( null === $raw ) {
			return array( self::MALFORMED, null );
		}
		$decoded = json_decode( $raw );
		if ( ! ( $decoded instanceof \stdClass ) ) {
			return array( self::MALFORMED, null );
		}
		$claims = (array) $decoded;
		if ( self::structure_is_invalid( $claims ) ) {
			return array( self::INVALID_FIELD, null );
		}
		$lifetime = $claims['exp'] - $claims['iat'];
		if ( $lifetime <= 0 || $lifetime > self::MAX_LIFETIME ) {
			return array( self::EXCESSIVE_LIFETIME, null );
		}
		if ( $claims['exp'] <= $now ) {
			return array( self::EXPIRED, null );
		}
		if ( $claims['iat'] > $now + self::ISSUE_SKEW ) {
			return array( self::ISSUED_IN_FUTURE, null );
		}
		if ( $claims['site_id'] !== $expected_site ) {
			return array( self::WRONG_SITE, null );
		}
		if ( $claims['post_id'] !== $expected_post ) {
			return array( self::WRONG_POST, null );
		}
		if ( ! hash_equals( $current_hash, $claims['content_sha256'] ) ) {
			return array( self::WRONG_FINGERPRINT, null );
		}
		if ( ! in_array( $claims['action'], $allowed_actions, true ) ) {
			return array( self::ACTION_NOT_ALLOWED, null );
		}
		if ( 'schedule' === $claims['action'] && self::to_timestamp( (string) $claims['publish_at'] ) <= $now ) {
			return array( self::INVALID_SCHEDULE, null );
		}
		return array( self::OK, $claims );
	}

	/**
	 * Vrai si la charge n'a pas exactement la structure attendue.
	 *
	 * @param array<mixed> $claims Charge décodée.
	 */
	private static function structure_is_invalid( array $claims ): bool {
		$keys     = array_keys( $claims );
		$required = self::FIELDS;
		sort( $keys );
		sort( $required );
		if ( $keys !== $required ) {
			return true;
		}
		if ( 1 !== $claims['v'] ) {
			return true;
		}
		$patterns = array(
			'approval_id'    => '/\A[A-Za-z0-9_-]{8,64}\z/D',
			'site_id'        => '/\A[a-z0-9][a-z0-9._-]{2,63}\z/D',
			'content_sha256' => '/\A[0-9a-f]{64}\z/D',
		);
		foreach ( $patterns as $name => $pattern ) {
			if ( ! is_string( $claims[ $name ] ) || 1 !== preg_match( $pattern, $claims[ $name ] ) ) {
				return true;
			}
		}
		if ( ! in_array( $claims['action'], array( 'publish', 'schedule' ), true ) ) {
			return true;
		}
		foreach ( array( 'post_id', 'iat', 'exp' ) as $name ) {
			if ( ! is_int( $claims[ $name ] ) || $claims[ $name ] <= 0 ) {
				return true;
			}
		}
		$at       = $claims['publish_at'];
		$at_valid = is_string( $at ) && 1 === preg_match( '/\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\z/D', $at );
		if ( 'schedule' === $claims['action'] && ! $at_valid ) {
			return true;
		}
		if ( 'publish' === $claims['action'] && null !== $at ) {
			return true;
		}
		return ! is_string( $claims['approved_by'] ) || strlen( $claims['approved_by'] ) < 1 || strlen( $claims['approved_by'] ) > 64;
	}

	/**
	 * Instant UNIX d'une date AAAA-MM-JJTHH:MM:SSZ (UTC).
	 *
	 * @param string $iso Date.
	 */
	public static function to_timestamp( string $iso ): int {
		$date = \DateTimeImmutable::createFromFormat( '!Y-m-d\TH:i:s\Z', $iso, new \DateTimeZone( 'UTC' ) );
		if ( false === $date || $date->format( 'Y-m-d\TH:i:s\Z' ) !== $iso ) {
			return 0;
		}
		return $date->getTimestamp();
	}
}
