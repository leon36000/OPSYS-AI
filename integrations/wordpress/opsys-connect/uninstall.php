<?php
/**
 * Désinstallation : supprimé la table des valeurs à usage unique, le rôle de service et l'option chiffrée.
 *
 * @package OpsysConnect
 */

declare( strict_types=1 );

defined( 'WP_UNINSTALL_PLUGIN' ) || exit;

require_once __DIR__ . '/includes/class-opsys-connect-signature.php';
require_once __DIR__ . '/includes/class-opsys-connect-config.php';
require_once __DIR__ . '/includes/class-opsys-connect-seen-store.php';
require_once __DIR__ . '/includes/class-opsys-connect-installer.php';

\OpsysConnect\Installer::uninstall();
