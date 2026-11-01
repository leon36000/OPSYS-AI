<?php
/**
 * Vérifie les classes pures du plugin (Signature, Fingerprint, Approval) contre les vecteurs de test PARTAGÉS avec OPSYS.
 *
 * Usage : php tests/verifier-vecteurs.php chemin/vers/opsys-connect-vecteurs.v1.json
 * (le fichier est dans le dépôt OPSYS : departments/m07-marketing/contracts/opsys-connect-vecteurs.v1.json).
 *
 * Code de sortie 0 si tous les cas donnent l'issue attendue, 1 sinon. AUCUN WordPress n'est nécessaire : les trois classes
 * ne dépendent d'aucune fonction WordPress. CE SCRIPT N'A JAMAIS ÉTÉ EXECUTE (PHP n'était pas installé sur la machine ou le
 * plugin a été écrit) : c'est la première chose à lancer sur une machine qui a PHP 8.1 ou plus.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

if ( 'cli' !== PHP_SAPI ) {
	exit( 1 );
}

define( 'ABSPATH', __DIR__ . '/' );

require_once __DIR__ . '/../includes/class-opsys-connect-signature.php';
require_once __DIR__ . '/../includes/class-opsys-connect-fingerprint.php';
require_once __DIR__ . '/../includes/class-opsys-connect-approval.php';

use OpsysConnect\Approval;
use OpsysConnect\Fingerprint;
use OpsysConnect\Signature;

if ( $argc < 2 || ! is_readable( $argv[1] ) ) {
	fwrite( STDERR, "Usage : php verifier-vecteurs.php vecteurs.json\n" );
	exit( 1 );
}
$vectors = json_decode( (string) stream_get_contents( fopen( $argv[1], 'r' ) ), true );
if ( ! is_array( $vectors ) ) {
	fwrite( STDERR, "Vecteurs illisibles.\n" );
	exit( 1 );
}

$failures = 0;
$checked  = 0;

$check = static function ( string $id, $got, $expected ) use ( &$failures, &$checked ): void {
	++$checked;
	if ( $got !== $expected ) {
		++$failures;
		fwrite( STDERR, 'ECHEC ' . $id . ' : obtenu ' . var_export( $got, true ) . ', attendu ' . var_export( $expected, true ) . "\n" );
	}
};

foreach ( $vectors['signatures'] as $case ) {
	$body = $case['corps_utf8'];
	$check( 'empreinte-corps:' . $case['id'], hash( 'sha256', $body ), $case['empreinte_corps'] );
	$check( 'canonique:' . $case['id'], Signature::canonical( $case['methode'], $case['route'], $case['horodatage'], $case['nonce'], $body ), $case['chaine_canonique'] );
	$check( 'signature:' . $case['id'], Signature::sign( $vectors['secret_de_test'], $case['methode'], $case['route'], $case['horodatage'], $case['nonce'], $body ), $case['signature'] );
}

foreach ( $vectors['verifications'] as $case ) {
	$request = $case['requete'];
	$headers = array();
	foreach ( $request['en_tetes'] as $name => $value ) {
		$headers[ strtolower( (string) $name ) ] = $value;
	}
	$check(
		'verification:' . $case['id'],
		Signature::verify( $case['secret_verificateur'], $request['methode'], $request['route'], $request['corps_utf8'], $headers, (int) $case['maintenant'] ),
		$case['attendu']
	);
}

$check( 'cle-approbation', bin2hex( Approval::derive_key( $vectors['secret_de_test'] ) ), $vectors['cle_approbation_hex'] );

foreach ( $vectors['jetons'] as $case ) {
	$context = $case['contexte'];
	list( $verdict ) = Approval::verify(
		$context['secret_verificateur'],
		$case['jeton'],
		$context['site_id_attendu'],
		(int) $context['post_id_attendu'],
		$context['empreinte_courante'],
		(int) $context['maintenant'],
		$context['actions_permises']
	);
	$check( 'jeton:' . $case['id'], $verdict, $case['attendu'] );
}

foreach ( $vectors['empreintes_contenu'] as $case ) {
	$check( 'canonique-contenu:' . $case['id'], Fingerprint::canonical( $case['champs'] ), $case['canonique_utf8'] );
	$check( 'empreinte-contenu:' . $case['id'], Fingerprint::hash( $case['champs'] ), $case['attendu_sha256'] );
}

fwrite( STDOUT, $checked . ' verifications, ' . $failures . " echec(s).\n" );
exit( 0 === $failures ? 0 : 1 );
