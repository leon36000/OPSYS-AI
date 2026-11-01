<?php
/**
 * Publication d'un article, et SEULEMENT avec un jeton d'approbation valide pour son contenu actuel.
 *
 * Ordre : publication configurée (identifiant de site), article géré et encore brouillon, empreinte du contenu STOCKÉ
 * recalculée à l'instant, jeton vérifié (signature, expiration, site, article, empreinte, action), identifiant
 * d'approbation consommé (usage unique), puis seulement le changement de statut, sous l'autorisation de la garde. L'empreinte
 * vérifiée est mémorisée (_opsys_published_sha256) : WordPress complète l'adresse à la publication, ce qui change
 * l'empreinte "vivante" sans que le contenu approuvé ait change.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Publication.
 */
final class Publisher {

	/**
	 * Codes d'erreur publics des constats de Approval.
	 *
	 * @var array<string,string>
	 */
	private const CODES = array(
		Approval::MALFORMED          => 'opsys_jeton_malforme',
		Approval::INVALID_SIGNATURE  => 'opsys_jeton_signature_invalide',
		Approval::INVALID_FIELD      => 'opsys_jeton_champ_invalide',
		Approval::EXPIRED            => 'opsys_jeton_expire',
		Approval::EXCESSIVE_LIFETIME => 'opsys_jeton_duree_excessive',
		Approval::ISSUED_IN_FUTURE   => 'opsys_jeton_champ_invalide',
		Approval::WRONG_SITE         => 'opsys_jeton_site_different',
		Approval::WRONG_POST         => 'opsys_jeton_article_different',
		Approval::WRONG_FINGERPRINT  => 'opsys_jeton_empreinte_differente',
		Approval::ACTION_NOT_ALLOWED => 'opsys_jeton_action_non_permise',
		Approval::INVALID_SCHEDULE   => 'opsys_jeton_planification_invalide',
	);

	/**
	 * Publie ou planifie un article.
	 *
	 * @param int                 $post_id Article.
	 * @param array<string,mixed> $params  Paramètres JSON (approval_token seulement).
	 * @return array<string,mixed>|\WP_Error
	 */
	public static function publish( int $post_id, array $params ) {
		$site_id = Config::site_id();
		$secret  = Config::secret();
		if ( null === $site_id || null === $secret ) {
			return Content::error( 'opsys_publication_desactivee', "La publication n'est pas activée sur ce site.", 503 );
		}
		if ( array( 'approval_token' ) !== array_keys( $params ) || ! is_string( $params['approval_token'] ) || strlen( $params['approval_token'] ) > 2048 ) {
			return Content::error( 'opsys_publication_sans_jeton', "La publication exige le jeton d'approbation de la direction.", 403 );
		}
		$post = Content::load_managed( $post_id );
		if ( is_wp_error( $post ) ) {
			return $post;
		}
		if ( ! in_array( $post->post_status, array( 'draft', 'pending' ), true ) ) {
			return Content::error( 'opsys_etat_non_modifiable', 'Seul un brouillon se publie : cet article est ' . sanitize_key( $post->post_status ) . '.', 409 );
		}
		$fingerprint = Content::fingerprint( $post );
		list( $verdict, $claims ) = Approval::verify( $secret, $params['approval_token'], $site_id, $post_id, $fingerprint, time(), Config::actions() );
		if ( Approval::OK !== $verdict || null === $claims ) {
			return Content::error( self::CODES[ $verdict ] ?? 'opsys_jeton_malforme', "Jeton d'approbation refusé.", 403 );
		}
		if ( ! Seen_Store::consume( Seen_Store::KIND_APPROVAL, $claims['approval_id'], $claims['exp'] + 2 * Signature::WINDOW ) ) {
			return Content::error( 'opsys_jeton_deja_utilise', "Ce jeton d'approbation a déjà servi.", 403 );
		}
		$postarr = array( 'ID' => $post_id );
		if ( 'schedule' === $claims['action'] ) {
			$gmt                     = gmdate( 'Y-m-d H:i:s', Approval::to_timestamp( $claims['publish_at'] ) );
			$postarr['post_status']   = 'future';
			$postarr['post_date_gmt'] = $gmt;
			$postarr['post_date']     = get_date_from_gmt( $gmt );
			$postarr['edit_date']     = true;
			$expected                 = 'future';
		} else {
			$postarr['post_status'] = 'publish';
			$expected               = 'publish';
		}
		Guard::$publication_authorized = true;
		try {
			$result = wp_update_post( wp_slash( $postarr ), true );
		} finally {
			Guard::$publication_authorized = false;
		}
		$fresh = get_post( $post_id );
		if ( is_wp_error( $result ) || ! ( $fresh instanceof \WP_Post ) || $fresh->post_status !== $expected ) {
			return Content::error( 'opsys_erreur_interne', "La publication n'a pas abouti.", 500 );
		}
		update_post_meta( $post_id, Content::META_PUBLISHED, $fingerprint );
		return array(
			'post_id'       => $post_id,
			'statut'        => $fresh->post_status,
			'empreinte'     => $fingerprint,
			'publie_le_gmt' => Content::iso( $fresh->post_date_gmt ),
			'lien_public'   => esc_url_raw( (string) get_permalink( $fresh ) ),
		);
	}
}
