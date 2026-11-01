<?php
/**
 * Mémoire à usage unique : nonces des requêtes, identifiants d'approbation, clés d'idempotence.
 *
 * Une table dédiée dont la clé primaire (genre, empreinte) garantit l'unicité en base : deux requêtes simultanées avec le
 * même nonce ne passent pas toutes les deux (la seconde insertion échoue). Rien n'est stocké en clair (SHA-256). Chaque
 * ligne expire ; la purge ne supprimé jamais une ligne dont l'expiration n'est pas passée.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Magasin d'usage unique.
 */
final class Seen_Store {

	public const KIND_NONCE    = 'nonce';
	public const KIND_APPROVAL = 'approval';
	public const KIND_IDEM     = 'idem';

	/**
	 * Nom de la table.
	 */
	public static function table(): string {
		global $wpdb;
		return $wpdb->prefix . 'opsys_connect_seen';
	}

	/**
	 * Crée la table (activation).
	 */
	public static function install(): void {
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		$table   = self::table();
		$charset = $wpdb->get_charset_collate();
		dbDelta(
			"CREATE TABLE {$table} (
			kind varchar(16) NOT NULL,
			token_hash char(64) NOT NULL,
			expires_at bigint(20) unsigned NOT NULL,
			PRIMARY KEY  (kind,token_hash),
			KEY expires_at (expires_at)
			) {$charset};"
		);
	}

	/**
	 * Marque une valeur comme vue. Vrai la première fois seulement (ou si la base échoue : échec fermé, la requête est
	 * alors refusée comme un rejeu).
	 *
	 * @param string $kind       Genre (nonce, approval, idem).
	 * @param string $value      Valeur.
	 * @param int    $expires_at Expiration (secondes UNIX).
	 */
	public static function consume( string $kind, string $value, int $expires_at ): bool {
		global $wpdb;
		$previous = $wpdb->suppress_errors( true );
		$inserted = $wpdb->insert(
			self::table(),
			array(
				'kind'       => $kind,
				'token_hash' => hash( 'sha256', $value ),
				'expires_at' => $expires_at,
			),
			array( '%s', '%s', '%d' )
		);
		$wpdb->suppress_errors( $previous );
		return 1 === $inserted;
	}

	/**
	 * Oublie une valeur (création échouée : la clé d'idempotence doit pouvoir resservir).
	 *
	 * @param string $kind  Genre.
	 * @param string $value Valeur.
	 */
	public static function release( string $kind, string $value ): void {
		global $wpdb;
		$wpdb->delete(
			self::table(),
			array(
				'kind'       => $kind,
				'token_hash' => hash( 'sha256', $value ),
			),
			array( '%s', '%s' )
		);
	}

	/**
	 * Supprime les lignes expirées.
	 *
	 * @param int $now Instant courant.
	 */
	public static function purge( int $now ): void {
		global $wpdb;
		$wpdb->query( $wpdb->prepare( 'DELETE FROM %i WHERE expires_at < %d', self::table(), $now ) );
	}

	/**
	 * Supprime la table (désinstallation).
	 */
	public static function drop(): void {
		global $wpdb;
		$wpdb->query( $wpdb->prepare( 'DROP TABLE IF EXISTS %i', self::table() ) );
	}
}
