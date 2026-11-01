<?php
/**
 * Garde de dernier recours : pendant une requête OPSYS, aucun article ne passe a publish, future ou private sans que
 * Publisher l'ait explicitement autorisé après vérification du jeton d'approbation.
 *
 * Les gestionnaires de brouillons forcent déjà le statut a draft ou pending. Ce filtre couvre le cas ou une autre extension
 * modifierait les données en route (wp_insert_post_data) : il ramené alors le statut a draft.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

namespace OpsysConnect;

defined( 'ABSPATH' ) || exit;

/**
 * Garde des statuts.
 */
final class Guard {

	/**
	 * Vrai seulement pendant l'appel de publication autorisé par un jeton valide.
	 *
	 * @var bool
	 */
	public static bool $publication_authorized = false;

	/**
	 * Filtre wp_insert_post_data.
	 *
	 * @param array<string,mixed> $data Données de l'article.
	 * @return array<string,mixed>
	 */
	public static function filter_post_data( $data ) {
		if ( ! is_array( $data ) || ! Auth::$active || self::$publication_authorized ) {
			return $data;
		}
		if ( isset( $data['post_status'] ) && in_array( $data['post_status'], array( 'publish', 'future', 'private' ), true ) ) {
			$data['post_status'] = 'draft';
		}
		return $data;
	}
}
