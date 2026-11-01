<?php
/**
 * Lecture et écriture des articles gérés par OPSYS : empreinte du contenu STOCKÉ, état, brouillons.
 *
 * Règles : seuls les articles créés par ce plugin (meta _opsys_managed) sont lus ou modifiés ; le statut d'un article crée
 * ou mis à jour est forcé à draft ou pending ; un article publié, planifié, privé ou à la corbeille n'est jamais modifié ;
 * titre, extrait et adresse passent par sanitize_* et le corps par wp_kses_post ; les données sont passées "slashées" a
 * wp_insert_post et wp_update_post, comme WordPress l'exige.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Brouillons.
 */
final class Content {

	public const META_MANAGED   = '_opsys_managed';
	public const META_IDEM      = '_opsys_idempotency_key';
	public const META_REQUEST   = '_opsys_request_sha256';
	public const META_SHA       = '_opsys_sha256';
	public const META_PUBLISHED = '_opsys_published_sha256';

	private const MAX_TITLE   = 200;
	private const MAX_CONTENT = 200000;
	private const MAX_EXCERPT = 1000;
	private const MAX_SLUG    = 100;

	private const CREATE_KEYS = array( 'type', 'titre', 'contenu', 'extrait', 'slug', 'statut', 'cle_idempotence', 'image_a_la_une' );
	private const UPDATE_KEYS = array( 'titre', 'contenu', 'extrait', 'slug', 'statut', 'empreinte_attendue', 'image_a_la_une' );

	/**
	 * Erreur HTTP.
	 *
	 * @param string $code    Code.
	 * @param string $message Message.
	 * @param int    $status  Statut HTTP.
	 */
	public static function error( string $code, string $message, int $status ): \WP_Error {
		return new \WP_Error( $code, $message, array( 'status' => $status ) );
	}

	/**
	 * Date GMT de WordPress en AAAA-MM-JJTHH:MM:SSZ.
	 *
	 * @param string $gmt Date "Y-m-d H:i:s" en GMT.
	 */
	public static function iso( string $gmt ): string {
		$ts = strtotime( $gmt . ' UTC' );
		return gmdate( 'Y-m-d\TH:i:s\Z', false === $ts ? 0 : $ts );
	}

	/**
	 * Empreinte du contenu STOCKÉ d'un article.
	 *
	 * @param \WP_Post $post Article.
	 */
	public static function fingerprint( \WP_Post $post ): string {
		$thumb_id = (int) get_post_thumbnail_id( $post->ID );
		$thumb    = '';
		if ( $thumb_id > 0 ) {
			$sha   = get_post_meta( $thumb_id, self::META_SHA, true );
			$thumb = ( is_string( $sha ) && '' !== $sha ) ? $sha : 'unmanaged-' . $thumb_id;
		}
		return Fingerprint::hash(
			array(
				'type'                  => $post->post_type,
				'titre'                 => $post->post_title,
				'contenu'               => $post->post_content,
				'extrait'               => $post->post_excerpt,
				'slug'                  => $post->post_name,
				'image_a_la_une_sha256' => $thumb,
			)
		);
	}

	/**
	 * Vrai si l'article a été crée par ce plugin.
	 *
	 * @param \WP_Post $post Article.
	 */
	public static function is_managed( \WP_Post $post ): bool {
		return '1' === get_post_meta( $post->ID, self::META_MANAGED, true );
	}

	/**
	 * Charge un article géré et de type permis, ou une erreur.
	 *
	 * @param int $post_id Identifiant.
	 * @return \WP_Post|\WP_Error
	 */
	public static function load_managed( int $post_id ) {
		$post = get_post( $post_id );
		if ( ! ( $post instanceof \WP_Post ) || ! self::is_managed( $post ) || ! in_array( $post->post_type, Config::post_types(), true ) ) {
			return self::error( 'opsys_non_gere', "Cet article n'existe pas ou n'est pas géré par OPSYS.", 404 );
		}
		return $post;
	}

	/**
	 * État d'un article, tel que rendu a OPSYS.
	 *
	 * @param \WP_Post $post Article.
	 * @return array<string,mixed>
	 */
	public static function state( \WP_Post $post ): array {
		$published = get_post_meta( $post->ID, self::META_PUBLISHED, true );
		return array(
			'post_id'           => $post->ID,
			'type'              => $post->post_type,
			'statut'            => $post->post_status,
			'empreinte'         => self::fingerprint( $post ),
			'empreinte_publiee' => ( is_string( $published ) && '' !== $published ) ? $published : null,
			'modifie_gmt'       => self::iso( $post->post_modified_gmt ),
			'gere'              => true,
			'lien_public'       => in_array( $post->post_status, array( 'publish', 'future' ), true ) ? esc_url_raw( (string) get_permalink( $post ) ) : null,
		);
	}

	/**
	 * Valide et assainit les champs d'une requête de brouillon.
	 *
	 * @param array<string,mixed> $params  Paramètres JSON.
	 * @param bool                $creating Vrai pour une création.
	 * @return array<string,mixed>|\WP_Error Champs assainis (clés WordPress).
	 */
	private static function sanitize( array $params, bool $creating ) {
		$allowed = $creating ? self::CREATE_KEYS : self::UPDATE_KEYS;
		foreach ( array_keys( $params ) as $key ) {
			if ( ! in_array( $key, $allowed, true ) ) {
				return self::error( 'opsys_champ_inconnu', 'Champ inconnu : ' . sanitize_key( (string) $key ), 400 );
			}
		}
		$limits = array(
			'titre'   => self::MAX_TITLE,
			'contenu' => self::MAX_CONTENT,
			'extrait' => self::MAX_EXCERPT,
			'slug'    => self::MAX_SLUG,
		);
		foreach ( $limits as $key => $max ) {
			if ( isset( $params[ $key ] ) && ( ! is_string( $params[ $key ] ) || strlen( $params[ $key ] ) > $max ) ) {
				return self::error( 'opsys_champ_invalide', 'Champ invalide : ' . $key, 400 );
			}
		}
		$out = array();
		if ( isset( $params['titre'] ) ) {
			$out['post_title'] = sanitize_text_field( $params['titre'] );
		}
		if ( isset( $params['contenu'] ) ) {
			$out['post_content'] = wp_kses_post( $params['contenu'] );
		}
		if ( isset( $params['extrait'] ) ) {
			$out['post_excerpt'] = sanitize_textarea_field( $params['extrait'] );
		}
		if ( isset( $params['slug'] ) ) {
			$out['post_name'] = sanitize_title( $params['slug'] );
		}
		if ( isset( $params['statut'] ) ) {
			if ( in_array( $params['statut'], array( 'publish', 'future', 'private' ), true ) ) {
				return self::error( 'opsys_publication_sans_jeton', 'La publication exige le jeton d\'approbation de la direction.', 403 );
			}
			if ( ! in_array( $params['statut'], array( 'draft', 'pending' ), true ) ) {
				return self::error( 'opsys_statut_interdit', 'Statut interdit : draft ou pending seulement.', 400 );
			}
			$out['post_status'] = $params['statut'];
		}
		if ( isset( $params['image_a_la_une'] ) ) {
			if ( ! is_int( $params['image_a_la_une'] ) || $params['image_a_la_une'] < 0 ) {
				return self::error( 'opsys_champ_invalide', 'Champ invalide : image_a_la_une', 400 );
			}
			$out['_thumbnail'] = $params['image_a_la_une'];
		}
		return $out;
	}

	/**
	 * Associe l'image à la une (média géré par OPSYS seulement).
	 *
	 * @param int $post_id Article.
	 * @param int $media   Média (0 pour retirer).
	 * @return true|\WP_Error
	 */
	private static function set_thumbnail( int $post_id, int $media ) {
		if ( 0 === $media ) {
			delete_post_thumbnail( $post_id );
			return true;
		}
		$attachment = get_post( $media );
		if ( ! ( $attachment instanceof \WP_Post ) || 'attachment' !== $attachment->post_type || '1' !== get_post_meta( $media, self::META_MANAGED, true ) ) {
			return self::error( 'opsys_champ_invalide', "L'image à la une doit être un média téléversé par OPSYS.", 400 );
		}
		set_post_thumbnail( $post_id, $media );
		return true;
	}

	/**
	 * Crée un brouillon (idempotent par clé).
	 *
	 * @param array<string,mixed> $params Paramètres JSON.
	 * @return array<string,mixed>|\WP_Error
	 */
	public static function create( array $params ) {
		$fields = self::sanitize( $params, true );
		if ( is_wp_error( $fields ) ) {
			return $fields;
		}
		$key = $params['cle_idempotence'] ?? null;
		if ( ! is_string( $key ) || 1 !== preg_match( '/\A[A-Za-z0-9_-]{16,64}\z/D', $key ) ) {
			return self::error( 'opsys_champ_invalide', 'cle_idempotence : 16 a 64 caractères [A-Za-z0-9_-].', 400 );
		}
		$type = $params['type'] ?? null;
		if ( ! is_string( $type ) || ! in_array( $type, Config::post_types(), true ) ) {
			return self::error( 'opsys_type_non_permis', 'Type de contenu non permis.', 400 );
		}
		if ( ! isset( $fields['post_title'] ) || '' === trim( $fields['post_title'] ) ) {
			return self::error( 'opsys_champ_invalide', 'Titre requis.', 400 );
		}
		$request_hash = Fingerprint::hash(
			array(
				'type'                  => $type,
				'titre'                 => $fields['post_title'],
				'contenu'               => $fields['post_content'] ?? '',
				'extrait'               => $fields['post_excerpt'] ?? '',
				'slug'                  => $fields['post_name'] ?? '',
				'image_a_la_une_sha256' => (string) ( $fields['_thumbnail'] ?? 0 ),
			)
		);
		$existing     = self::find_by_key( $key );
		if ( null !== $existing ) {
			return self::replay( $existing, $request_hash );
		}
		if ( ! Seen_Store::consume( Seen_Store::KIND_IDEM, $key, time() + 30 * DAY_IN_SECONDS ) ) {
			return self::error( 'opsys_creation_en_cours', 'Une création avec cette clé est en cours.', 409 );
		}
		$status  = $fields['post_status'] ?? 'draft';
		$postarr = array(
			'post_type'    => $type,
			'post_status'  => 'pending' === $status ? 'pending' : 'draft',
			'post_title'   => $fields['post_title'],
			'post_content' => $fields['post_content'] ?? '',
			'post_excerpt' => $fields['post_excerpt'] ?? '',
			'post_name'    => $fields['post_name'] ?? '',
			'post_author'  => get_current_user_id(),
			'meta_input'   => array(
				self::META_MANAGED => '1',
				self::META_IDEM    => $key,
				self::META_REQUEST => $request_hash,
			),
		);
		$post_id = wp_insert_post( wp_slash( $postarr ), true );
		if ( is_wp_error( $post_id ) || 0 === $post_id ) {
			Seen_Store::release( Seen_Store::KIND_IDEM, $key );
			return self::error( 'opsys_erreur_interne', "Création impossible.", 500 );
		}
		if ( isset( $fields['_thumbnail'] ) ) {
			$thumb = self::set_thumbnail( $post_id, $fields['_thumbnail'] );
			if ( is_wp_error( $thumb ) ) {
				wp_trash_post( $post_id );
				Seen_Store::release( Seen_Store::KIND_IDEM, $key );
				return $thumb;
			}
		}
		$post = get_post( $post_id );
		if ( ! ( $post instanceof \WP_Post ) || ! in_array( $post->post_status, array( 'draft', 'pending' ), true ) ) {
			return self::error( 'opsys_erreur_interne', 'Le brouillon a un statut inattendu.', 500 );
		}
		return array_merge( self::draft_view( $post ), array( 'deja_cree' => false ) );
	}

	/**
	 * Rejeu d'une création : même clé et même requête, c'est le même article ; une autre requête est un conflit. La
	 * comparaison porte sur l'empreinte de la REQUÊTE assainie, mémorisée à la création (le contenu stocké peut avoir été
	 * modifié depuis, ou normalisé par WordPress).
	 *
	 * @param \WP_Post $existing     Article déjà crée.
	 * @param string   $request_hash Empreinte de la requête courante.
	 * @return array<string,mixed>|\WP_Error
	 */
	private static function replay( \WP_Post $existing, string $request_hash ) {
		$stored = get_post_meta( $existing->ID, self::META_REQUEST, true );
		if ( ! is_string( $stored ) || ! hash_equals( $stored, $request_hash ) ) {
			return self::error( 'opsys_cle_idempotence_reutilisee', 'Cette clé désigne déjà un article au contenu différent.', 409 );
		}
		return array_merge( self::draft_view( $existing ), array( 'deja_cree' => true ) );
	}

	/**
	 * Retrouve un article par sa clé d'idempotence.
	 *
	 * @param string $key Clé.
	 */
	private static function find_by_key( string $key ): ?\WP_Post {
		$ids = get_posts(
			array(
				'post_type'        => Config::post_types(),
				'post_status'      => 'any',
				'meta_key'         => self::META_IDEM, // phpcs:ignore WordPress.DB.SlowDBQuery.slow_db_query_meta_key
				'meta_value'       => $key,            // phpcs:ignore WordPress.DB.SlowDBQuery.slow_db_query_meta_value
				'numberposts'      => 1,
				'fields'           => 'ids',
				'suppress_filters' => true,
			)
		);
		if ( array() === $ids ) {
			return null;
		}
		$post = get_post( (int) $ids[0] );
		return ( $post instanceof \WP_Post && self::is_managed( $post ) ) ? $post : null;
	}

	/**
	 * Vue d'un brouillon.
	 *
	 * @param \WP_Post $post Article.
	 * @return array<string,mixed>
	 */
	private static function draft_view( \WP_Post $post ): array {
		return array(
			'post_id'           => $post->ID,
			'type'              => $post->post_type,
			'statut'            => $post->post_status,
			'empreinte'         => self::fingerprint( $post ),
			'modifie_gmt'       => self::iso( $post->post_modified_gmt ),
			'lien_modification' => esc_url_raw( admin_url( 'post.php?post=' . $post->ID . '&action=edit' ) ),
		);
	}

	/**
	 * Met à jour un brouillon. Un article publié, planifié, privé ou à la corbeille n'est jamais modifié.
	 *
	 * @param int                 $post_id Article.
	 * @param array<string,mixed> $params  Paramètres JSON.
	 * @return array<string,mixed>|\WP_Error
	 */
	public static function update( int $post_id, array $params ) {
		$post = self::load_managed( $post_id );
		if ( is_wp_error( $post ) ) {
			return $post;
		}
		if ( ! in_array( $post->post_status, array( 'draft', 'pending' ), true ) ) {
			return self::error( 'opsys_etat_non_modifiable', 'Seul un brouillon se modifie : cet article est ' . sanitize_key( $post->post_status ) . '.', 409 );
		}
		$fields = self::sanitize( $params, false );
		if ( is_wp_error( $fields ) ) {
			return $fields;
		}
		if ( isset( $params['empreinte_attendue'] ) ) {
			if ( ! is_string( $params['empreinte_attendue'] ) || ! hash_equals( self::fingerprint( $post ), $params['empreinte_attendue'] ) ) {
				return self::error( 'opsys_empreinte_obsolete', "Le brouillon a changé sur le site depuis la dernière lecture.", 409 );
			}
		}
		$postarr = array( 'ID' => $post_id );
		foreach ( array( 'post_title', 'post_content', 'post_excerpt', 'post_name', 'post_status' ) as $column ) {
			if ( isset( $fields[ $column ] ) ) {
				$postarr[ $column ] = $fields[ $column ];
			}
		}
		if ( count( $postarr ) > 1 ) {
			$result = wp_update_post( wp_slash( $postarr ), true );
			if ( is_wp_error( $result ) || 0 === $result ) {
				return self::error( 'opsys_erreur_interne', 'Mise à jour impossible.', 500 );
			}
		}
		if ( isset( $fields['_thumbnail'] ) ) {
			$thumb = self::set_thumbnail( $post_id, $fields['_thumbnail'] );
			if ( is_wp_error( $thumb ) ) {
				return $thumb;
			}
		}
		$fresh = get_post( $post_id );
		if ( ! ( $fresh instanceof \WP_Post ) || ! in_array( $fresh->post_status, array( 'draft', 'pending' ), true ) ) {
			return self::error( 'opsys_erreur_interne', "Le brouillon a un statut inattendu.", 500 );
		}
		$view = self::draft_view( $fresh );
		unset( $view['lien_modification'] );
		return $view;
	}
}
