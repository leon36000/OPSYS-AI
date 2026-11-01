<?php
/**
 * Routes REST du plugin (espace opsys-connect/v1).
 *
 * Chaque route a un permission_callback propre à Auth (jamais __return_true) : signature, nonce neuf, utilisateur de service
 * sûr et capacité WordPress. Aucune route n'accepte de paramètre de requête ; les corps JSON sont validés à la main dans
 * Content, Média et Publisher, après l'authentification.
 *
 *   GET  /health                 version, configuration, état (sans secret)
 *   GET  /types                  types de contenu et leur caractère gérable
 *   POST /drafts                 crée un brouillon (draft ou pending), idempotent par clé
 *   PUT  /drafts/{id}            met à jour un brouillon (jamais un article publié)
 *   POST /media                  téléverse un média dans la médiathèque (type MIME réel vérifié)
 *   GET  /posts/{id}/state       état et empreinte d'un article géré
 *   POST /posts/{id}/publish     publie ou planifie, avec un jeton d'approbation valide pour le contenu actuel
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Enregistrement et gestionnaires des routes.
 */
final class Rest {

	public const API_NAMESPACE = 'opsys-connect/v1';

	/**
	 * Enregistre les routes (action rest_api_init).
	 */
	public static function register_routes(): void {
		register_rest_route(
			self::API_NAMESPACE,
			'/health',
			array(
				'methods'             => 'GET',
				'callback'            => array( self::class, 'health' ),
				'permission_callback' => array( Auth::class, 'check_read' ),
			)
		);
		register_rest_route(
			self::API_NAMESPACE,
			'/types',
			array(
				'methods'             => 'GET',
				'callback'            => array( self::class, 'types' ),
				'permission_callback' => array( Auth::class, 'check_read' ),
			)
		);
		register_rest_route(
			self::API_NAMESPACE,
			'/drafts',
			array(
				'methods'             => 'POST',
				'callback'            => array( self::class, 'create_draft' ),
				'permission_callback' => array( Auth::class, 'check_edit' ),
			)
		);
		register_rest_route(
			self::API_NAMESPACE,
			'/drafts/(?P<id>[0-9]+)',
			array(
				'methods'             => 'PUT',
				'callback'            => array( self::class, 'update_draft' ),
				'permission_callback' => array( Auth::class, 'check_edit' ),
			)
		);
		register_rest_route(
			self::API_NAMESPACE,
			'/media',
			array(
				'methods'             => 'POST',
				'callback'            => array( self::class, 'upload_media' ),
				'permission_callback' => array( Auth::class, 'check_upload' ),
			)
		);
		register_rest_route(
			self::API_NAMESPACE,
			'/posts/(?P<id>[0-9]+)/state',
			array(
				'methods'             => 'GET',
				'callback'            => array( self::class, 'post_state' ),
				'permission_callback' => array( Auth::class, 'check_edit' ),
			)
		);
		register_rest_route(
			self::API_NAMESPACE,
			'/posts/(?P<id>[0-9]+)/publish',
			array(
				'methods'             => 'POST',
				'callback'            => array( self::class, 'publish_post' ),
				'permission_callback' => array( Auth::class, 'check_edit' ),
			)
		);
	}

	/**
	 * Convertit un résultat en réponse REST.
	 *
	 * @param array<string,mixed>|\WP_Error $result Résultat.
	 * @param int                           $status Statut HTTP en cas de succès.
	 * @return \WP_REST_Response|\WP_Error
	 */
	private static function respond( $result, int $status = 200 ) {
		if ( is_wp_error( $result ) ) {
			return $result;
		}
		return new \WP_REST_Response( $result, $status );
	}

	/**
	 * Corps JSON de la requête : un objet, sinon une erreur.
	 *
	 * @param \WP_REST_Request $request Requête.
	 * @return array<string,mixed>|\WP_Error
	 */
	private static function json_object( \WP_REST_Request $request ) {
		$params = json_decode( $request->get_body(), true );
		if ( ! is_array( $params ) || ( array() !== $params && array_is_list( $params ) ) ) {
			return Content::error( 'opsys_champ_invalide', 'Un objet JSON est attendu.', 400 );
		}
		return $params;
	}

	/**
	 * GET /health.
	 *
	 * @return \WP_REST_Response
	 */
	public static function health() {
		$agent = Config::agent_user();
		return new \WP_REST_Response(
			array(
				'schema'              => 'opsys-connect/v1',
				'plugin_version'      => OPSYS_CONNECT_VERSION,
				'wp_version'          => get_bloginfo( 'version' ),
				'php_version'         => PHP_VERSION,
				'site_id'             => Config::site_id(),
				'publication_activee' => null !== Config::site_id(),
				'agent_sur'           => ! is_wp_error( $agent ),
				'https'               => is_ssl(),
				'heure_serveur'       => time(),
			),
			200
		);
	}

	/**
	 * GET /types.
	 *
	 * @return \WP_REST_Response
	 */
	public static function types() {
		$managed = Config::post_types();
		$types   = array();
		foreach ( get_post_types( array( 'public' => true ), 'objects' ) as $type ) {
			$types[] = array(
				'nom'            => $type->name,
				'libelle'        => sanitize_text_field( (string) $type->label ),
				'gerable'        => in_array( $type->name, $managed, true ),
				'statuts_permis' => in_array( $type->name, $managed, true ) ? array( 'draft', 'pending' ) : array(),
			);
		}
		return new \WP_REST_Response( array( 'types' => $types ), 200 );
	}

	/**
	 * POST /drafts.
	 *
	 * @param \WP_REST_Request $request Requête.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public static function create_draft( \WP_REST_Request $request ) {
		$params = self::json_object( $request );
		if ( is_wp_error( $params ) ) {
			return $params;
		}
		$result = Content::create( $params );
		return self::respond( $result, ( is_array( $result ) && ! empty( $result['deja_cree'] ) ) ? 200 : 201 );
	}

	/**
	 * PUT /drafts/{id}.
	 *
	 * @param \WP_REST_Request $request Requête.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public static function update_draft( \WP_REST_Request $request ) {
		$params = self::json_object( $request );
		if ( is_wp_error( $params ) ) {
			return $params;
		}
		return self::respond( Content::update( absint( $request['id'] ), $params ) );
	}

	/**
	 * POST /media.
	 *
	 * @param \WP_REST_Request $request Requête.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public static function upload_media( \WP_REST_Request $request ) {
		$params = self::json_object( $request );
		if ( is_wp_error( $params ) ) {
			return $params;
		}
		$result = Media::upload( $params );
		return self::respond( $result, ( is_array( $result ) && ! empty( $result['deja_cree'] ) ) ? 200 : 201 );
	}

	/**
	 * GET /posts/{id}/state.
	 *
	 * @param \WP_REST_Request $request Requête.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public static function post_state( \WP_REST_Request $request ) {
		$post = Content::load_managed( absint( $request['id'] ) );
		if ( is_wp_error( $post ) ) {
			return $post;
		}
		return self::respond( Content::state( $post ) );
	}

	/**
	 * POST /posts/{id}/publish.
	 *
	 * @param \WP_REST_Request $request Requête.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public static function publish_post( \WP_REST_Request $request ) {
		$params = self::json_object( $request );
		if ( is_wp_error( $params ) ) {
			return $params;
		}
		return self::respond( Publisher::publish( absint( $request['id'] ), $params ) );
	}
}
