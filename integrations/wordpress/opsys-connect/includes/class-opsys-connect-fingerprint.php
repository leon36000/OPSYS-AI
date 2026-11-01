<?php
/**
 * Empreinte du contenu d'un article (opsys-content/v1), identique chez OPSYS et dans le plugin.
 *
 * Encodage : la ligne "opsys-content/v1" puis, pour chacun des champs type, titre, contenu, extrait, slug et
 * image_a_la_une_sha256, la ligne "<nom>:<octets UTF-8>:<valeur>" terminée par LF. L'empreinte est le SHA-256
 * hexadécimal minuscule de l'ensemble. La longueur en octets empêche une valeur d'imiter un autre champ.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Empreinte de contenu.
 */
final class Fingerprint {

	public const HEADER = "opsys-content/v1\n";

	/**
	 * Champs, dans l'ordre.
	 *
	 * @var string[]
	 */
	public const FIELDS = array( 'type', 'titre', 'contenu', 'extrait', 'slug', 'image_a_la_une_sha256' );

	/**
	 * Encodage canonique.
	 *
	 * @param array<string,string> $fields Valeurs des champs (tous requis).
	 * @throws \InvalidArgumentException Si un champ manque ou n'est pas un texte.
	 */
	public static function canonical( array $fields ): string {
		$out = self::HEADER;
		foreach ( self::FIELDS as $name ) {
			if ( ! isset( $fields[ $name ] ) || ! is_string( $fields[ $name ] ) ) {
				throw new \InvalidArgumentException( 'champ manquant ou invalide : ' . $name );
			}
			$out .= $name . ':' . strlen( $fields[ $name ] ) . ':' . $fields[ $name ] . "\n";
		}
		return $out;
	}

	/**
	 * Empreinte SHA-256 hexadécimale.
	 *
	 * @param array<string,string> $fields Valeurs des champs.
	 */
	public static function hash( array $fields ): string {
		return hash( 'sha256', self::canonical( $fields ) );
	}
}
