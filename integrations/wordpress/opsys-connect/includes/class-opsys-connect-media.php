<?php
/**
 * Téléversement d'un média dans la médiathèque de WordPress, et nulle part ailleurs.
 *
 * Le fichier est reçu en base64 dans le corps JSON, avec son SHA-256 déclaré. Contrôles, dans l'ordre : champs exacts, texte
 * alternatif obligatoire, base64 strict, taille, empreinte déclarée égale à l'empreinte réelle, TYPE MIME RÉEL lu dans les
 * octets (finfo) parmi JPEG, PNG, WebP et GIF seulement, image décodable (getimagesizefromstring) dont le type et les
 * dimensions concordent, aucun amorce de code PHP dans les octets. Le nom du fichier est reconstruit (nom assaini,
 * empreinte, extension tirée du type réel) : l'extension annoncée par OPSYS n'est jamais crue. L'écriture passe par
 * wp_upload_bits (dossier des téléversements de WordPress) ; aucune autre écriture sur le disque n'existe dans ce plugin.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Médias.
 */
final class Media {

	public const MAX_BYTES  = 8388608;
	public const MAX_PIXELS = 12000;

	private const KEYS = array( 'nom_fichier', 'contenu_base64', 'sha256', 'alt' );

	/**
	 * Types MIME permis, avec l'extension imposée.
	 *
	 * @var array<string,string>
	 */
	public const MIME_TYPES = array(
		'image/jpeg' => 'jpg',
		'image/png'  => 'png',
		'image/webp' => 'webp',
		'image/gif'  => 'gif',
	);

	/**
	 * Téléverse un média.
	 *
	 * @param array<string,mixed> $params Paramètres JSON.
	 * @return array<string,mixed>|\WP_Error
	 */
	public static function upload( array $params ) {
		foreach ( array_keys( $params ) as $key ) {
			if ( ! in_array( $key, self::KEYS, true ) ) {
				return Content::error( 'opsys_champ_inconnu', 'Champ inconnu : ' . sanitize_key( (string) $key ), 400 );
			}
		}
		foreach ( self::KEYS as $key ) {
			if ( ! isset( $params[ $key ] ) || ! is_string( $params[ $key ] ) ) {
				return Content::error( 'opsys_media_invalide', 'Champ requis : ' . $key, 400 );
			}
		}
		$alt = sanitize_text_field( $params['alt'] );
		if ( '' === trim( $alt ) || strlen( $alt ) > 300 ) {
			return Content::error( 'opsys_media_invalide', 'Texte alternatif requis (300 caractères au plus).', 400 );
		}
		if ( 1 !== preg_match( '/\A[0-9a-f]{64}\z/D', $params['sha256'] ) ) {
			return Content::error( 'opsys_media_invalide', 'sha256 invalide.', 400 );
		}
		$bytes = base64_decode( $params['contenu_base64'], true );
		if ( false === $bytes || '' === $bytes ) {
			return Content::error( 'opsys_media_invalide', 'Contenu base64 invalide.', 400 );
		}
		if ( strlen( $bytes ) > self::MAX_BYTES ) {
			return Content::error( 'opsys_media_trop_gros', 'Média trop gros.', 413 );
		}
		if ( ! hash_equals( hash( 'sha256', $bytes ), $params['sha256'] ) ) {
			return Content::error( 'opsys_media_empreinte_differente', "L'empreinte déclarée n'est pas celle du contenu.", 400 );
		}
		$existing = self::find_by_hash( $params['sha256'] );
		if ( null !== $existing ) {
			return self::view( $existing, true );
		}
		$checked = self::inspect( $bytes );
		if ( is_wp_error( $checked ) ) {
			return $checked;
		}
		return self::store( $params, $bytes, $checked, $alt );
	}

	/**
	 * Contrôle les octets : type réel, image décodable, dimensions, aucun amorce de code.
	 *
	 * @param string $bytes Octets du fichier.
	 * @return array{mime:string,ext:string,width:int,height:int}|\WP_Error
	 */
	private static function inspect( string $bytes ) {
		if ( ! class_exists( 'finfo' ) ) {
			return Content::error( 'opsys_erreur_interne', 'Détection du type indisponible.', 500 );
		}
		$finfo = new \finfo( FILEINFO_MIME_TYPE );
		$mime  = $finfo->buffer( $bytes );
		if ( ! is_string( $mime ) || ! isset( self::MIME_TYPES[ $mime ] ) ) {
			return Content::error( 'opsys_media_type_refuse', 'Type de média non permis (JPEG, PNG, WebP et GIF seulement).', 415 );
		}
		$info = getimagesizefromstring( $bytes );
		if ( false === $info || ! isset( $info['mime'] ) || $info['mime'] !== $mime ) {
			return Content::error( 'opsys_media_type_refuse', "Le contenu n'est pas une image valide du type détecté.", 415 );
		}
		$width  = (int) $info[0];
		$height = (int) $info[1];
		if ( $width < 1 || $height < 1 || $width > self::MAX_PIXELS || $height > self::MAX_PIXELS ) {
			return Content::error( 'opsys_media_invalide', 'Dimensions hors limites.', 400 );
		}
		if ( false !== stripos( $bytes, '<?php' ) || false !== strpos( $bytes, '<?=' ) ) {
			return Content::error( 'opsys_media_contenu_actif', 'Le fichier contient du code.', 400 );
		}
		return array(
			'mime'   => $mime,
			'ext'    => self::MIME_TYPES[ $mime ],
			'width'  => $width,
			'height' => $height,
		);
	}

	/**
	 * Écrit le fichier dans la médiathèque et crée la pièce jointe.
	 *
	 * @param array<string,mixed>                                  $params  Paramètres.
	 * @param string                                               $bytes   Octets.
	 * @param array{mime:string,ext:string,width:int,height:int}   $checked Résultat de inspect().
	 * @param string                                               $alt     Texte alternatif assaini.
	 * @return array<string,mixed>|\WP_Error
	 */
	private static function store( array $params, string $bytes, array $checked, string $alt ) {
		$base = sanitize_file_name( pathinfo( $params['nom_fichier'], PATHINFO_FILENAME ) );
		$base = '' === $base ? 'media' : substr( $base, 0, 60 );
		$name = $base . '-' . substr( $params['sha256'], 0, 12 ) . '.' . $checked['ext'];
		$file = wp_upload_bits( $name, null, $bytes );
		if ( ! is_array( $file ) || ! empty( $file['error'] ) || empty( $file['file'] ) ) {
			return Content::error( 'opsys_erreur_interne', 'Écriture dans la médiathèque impossible.', 500 );
		}
		$type = wp_check_filetype( $file['file'] );
		if ( $type['type'] !== $checked['mime'] ) {
			wp_delete_file( $file['file'] );
			return Content::error( 'opsys_media_type_refuse', "WordPress ne reconnaît pas ce type pour l'extension imposée.", 415 );
		}
		$attachment_id = wp_insert_attachment(
			wp_slash(
				array(
					'post_mime_type' => $checked['mime'],
					'post_title'     => $base,
					'post_content'   => '',
					'post_status'    => 'inherit',
					'meta_input'     => array(
						Content::META_MANAGED => '1',
						Content::META_SHA     => $params['sha256'],
					),
				)
			),
			$file['file'],
			0,
			true
		);
		if ( is_wp_error( $attachment_id ) || 0 === $attachment_id ) {
			wp_delete_file( $file['file'] );
			return Content::error( 'opsys_erreur_interne', 'Création de la pièce jointe impossible.', 500 );
		}
		require_once ABSPATH . 'wp-admin/includes/image.php';
		wp_update_attachment_metadata( $attachment_id, wp_generate_attachment_metadata( $attachment_id, $file['file'] ) );
		update_post_meta( $attachment_id, '_wp_attachment_image_alt', $alt );
		$post = get_post( $attachment_id );
		return $post instanceof \WP_Post ? self::view( $post, false ) : Content::error( 'opsys_erreur_interne', 'Pièce jointe introuvable.', 500 );
	}

	/**
	 * Pièce jointe déjà téléversée avec cette empreinte.
	 *
	 * @param string $hash SHA-256 du contenu.
	 */
	private static function find_by_hash( string $hash ): ?\WP_Post {
		$ids = get_posts(
			array(
				'post_type'        => 'attachment',
				'post_status'      => 'inherit',
				'meta_key'         => Content::META_SHA, // phpcs:ignore WordPress.DB.SlowDBQuery.slow_db_query_meta_key
				'meta_value'       => $hash,             // phpcs:ignore WordPress.DB.SlowDBQuery.slow_db_query_meta_value
				'numberposts'      => 1,
				'fields'           => 'ids',
				'suppress_filters' => true,
			)
		);
		if ( array() === $ids ) {
			return null;
		}
		$post = get_post( (int) $ids[0] );
		return ( $post instanceof \WP_Post && '1' === get_post_meta( $post->ID, Content::META_MANAGED, true ) ) ? $post : null;
	}

	/**
	 * Vue d'un média.
	 *
	 * @param \WP_Post $post    Pièce jointe.
	 * @param bool     $already Vrai pour un rejeu.
	 * @return array<string,mixed>
	 */
	private static function view( \WP_Post $post, bool $already ): array {
		$meta = wp_get_attachment_metadata( $post->ID );
		return array(
			'media_id'  => $post->ID,
			'sha256'    => (string) get_post_meta( $post->ID, Content::META_SHA, true ),
			'mime'      => (string) $post->post_mime_type,
			'largeur'   => is_array( $meta ) && isset( $meta['width'] ) ? (int) $meta['width'] : 1,
			'hauteur'   => is_array( $meta ) && isset( $meta['height'] ) ? (int) $meta['height'] : 1,
			'deja_cree' => $already,
		);
	}
}
