#!/usr/bin/env perl

use strict;
use warnings;
use utf8;

BEGIN {
  my $root = $ENV{KIVITENDO_DIR} || '/var/www/kivitendo-erp';
  die "Invalid KIVITENDO_DIR\n" if $root =~ /[\r\n]/ || !-d $root;
  chdir $root or die "Cannot chdir to kivitendo installation: $!\n";
  unshift @INC, "$root/modules/override", $root, "$root/modules/fallback";
}

use CGI qw();
use DBI;
use Digest::SHA qw(sha256_hex);
use SL::Form;
use SL::Layout::None;
use SL::Locale;
use SL::LXDebug;
use SL::LxOfficeConf;
use SL::Request;
use SL::User;

{
  package KivitendoMigrationAuth;

  sub new {
    my ($class, %values) = @_;
    return bless \%values, $class;
  }

  sub get_session_value {
    my ($self, $key) = @_;
    return $self->{$key};
  }

  sub set_session_value {
    my ($self, %values) = @_;
    @{$self}{keys %values} = values %values;
    return 1;
  }
}

sub required_env {
  my ($name) = @_;
  my $value = $ENV{$name};
  die "Required environment variable $name is missing\n"
    if !defined($value) || $value eq '';
  die "Environment variable $name contains a newline\n" if $value =~ /[\r\n]/;
  return $value;
}

sub optional_env {
  my ($name, $default) = @_;
  my $value = exists $ENV{$name} ? $ENV{$name} : $default;
  die "Environment variable $name contains a newline\n"
    if defined($value) && $value =~ /[\r\n]/;
  return $value;
}

sub bool_env {
  my ($name, $default) = @_;
  my $value = lc optional_env($name, $default ? '1' : '0');
  return 1 if $value =~ /^(?:1|true|yes|on)$/;
  return 0 if $value =~ /^(?:0|false|no|off)$/;
  die "Environment variable $name is not boolean\n";
}

my $root             = required_env('KIVITENDO_DIR');
my $db_host          = required_env('KIVITENDO_DB_HOST');
my $db_port          = required_env('KIVITENDO_DB_PORT');
my $db_user          = required_env('KIVITENDO_DB_USER');
my $db_password      = required_env('KIVITENDO_DB_PASSWORD');
my $source_db        = required_env('KIVITENDO_SOURCE_DB');
my $target_db        = required_env('KIVITENDO_TARGET_DB');
my $run_id           = required_env('KIVITENDO_RUN_ID');
my $chart            = required_env('KIVITENDO_CHART');
my $superuser        = required_env('KIVITENDO_SUPERUSER');
my $superuser_pass   = required_env('KIVITENDO_SUPERUSER_PASSWORD');
my $default_currency = optional_env('KIVITENDO_DEFAULT_CURRENCY', 'EUR');
my $precision        = optional_env('KIVITENDO_PRECISION', '0.01');
my $marker_key       = 'kivitendo-datev-skr04-v1';
my $staging_db       = 'kivi_skr04_stage_' . substr(
  sha256_hex(join("\0", $run_id, $target_db)),
  0,
  24,
);

$source_db =~ /^[a-z][a-z0-9_]{2,62}$/
  or die "Unsafe source database name\n";
$target_db =~ /^[a-z][a-z0-9_]{2,62}$/
  or die "Unsafe target database name\n";
$staging_db =~ /^kivi_skr04_stage_[a-f0-9]{24}$/
  or die "Unsafe staging database name\n";
$source_db ne $target_db
  or die "Source and target database must differ\n";
$run_id =~ /^[A-Za-z0-9][A-Za-z0-9_-]{7,95}$/
  or die "Unsafe migration run identifier\n";
$db_user =~ /^[A-Za-z_][A-Za-z0-9_.-]{0,62}$/
  or die "Unsafe database role name\n";
$superuser =~ /^[A-Za-z_][A-Za-z0-9_.-]{0,62}$/
  or die "Unsafe temporary superuser role name\n";
$db_port =~ /^\d{1,5}$/ && $db_port > 0 && $db_port <= 65535
  or die "Invalid database port\n";
$chart eq 'Germany-DATEV-SKR04EU'
  or die "Only Germany-DATEV-SKR04EU is permitted by this migration helper\n";
-f "$root/sql/${chart}-chart.sql"
  or die "Requested SKR04 chart file does not exist\n";

my $admin_dsn = "dbi:Pg:dbname=template1;host=$db_host;port=$db_port";
my $admin_dbh = DBI->connect(
  $admin_dsn,
  $db_user,
  $db_password,
  { AutoCommit => 1, RaiseError => 1, PrintError => 0 },
);
my $occupied_names = $admin_dbh->selectall_arrayref(
  q{
    SELECT datname
      FROM pg_database
     WHERE datname = ?
        OR left(datname, length('kivi_skr04_stage_')) = 'kivi_skr04_stage_'
     ORDER BY datname
  },
  undef,
  $target_db,
);
$admin_dbh->disconnect;
if (@{$occupied_names}) {
  my $names = join(', ', map { $_->[0] } @{$occupied_names});
  die "Target or reserved staging database already exists ($names); refusing to adopt or modify it\n";
}

SL::LxOfficeConf->read;
$::lxdebug = LXDebug->new;
$::locale  = Locale->new('de');
$::form    = Form->new;
$::request = SL::Request->new(
  cgi    => CGI->new({}),
  layout => SL::Layout::None->new,
);
$::auth    = KivitendoMigrationAuth->new(
  database_superuser_username => $superuser,
  database_superuser_password => $superuser_pass,
);

%::myconfig = (
  dbdriver     => 'Pg',
  dbhost       => $db_host,
  dbport       => $db_port,
  dbname       => $staging_db,
  dbuser       => $db_user,
  dbpasswd     => $db_password,
  numberformat => '1000.00',
  dateformat   => 'yyyy-mm-dd',
);

my %dataset = (
  dbdriver                    => 'Pg',
  dbhost                      => $db_host,
  dbport                      => $db_port,
  db                          => $staging_db,
  dbname                      => $staging_db,
  dbdefault                   => 'template1',
  dbuser                      => $db_user,
  dbpasswd                    => $db_password,
  chart                       => $chart,
  encoding                    => 'UTF8',
  defaultcurrency             => $default_currency,
  precision                   => $precision,
  precision_as_number         => $precision,
  accounting_method           => optional_env('KIVITENDO_ACCOUNTING_METHOD', 'cash'),
  profit_determination        => optional_env('KIVITENDO_PROFIT_DETERMINATION', 'income'),
  inventory_system            => optional_env('KIVITENDO_INVENTORY_SYSTEM', 'periodic'),
  feature_balance             => bool_env('KIVITENDO_FEATURE_BALANCE', 0),
  feature_datev               => bool_env('KIVITENDO_FEATURE_DATEV', 1),
  feature_erfolgsrechnung     => bool_env('KIVITENDO_FEATURE_ERFOLGSRECHNUNG', 0),
  feature_eurechnung          => bool_env('KIVITENDO_FEATURE_EURECHNUNG', 1),
  feature_ustva               => bool_env('KIVITENDO_FEATURE_USTVA', 1),
  datev_check_on_sales_invoice    => 1,
  datev_check_on_purchase_invoice => 1,
  datev_check_on_ar_transaction   => 1,
  datev_check_on_ap_transaction   => 1,
  datev_check_on_gl_transaction   => 1,
);

@{$::form}{keys %dataset} = values %dataset;

my $created = eval {
  User->new->dbcreate($::form);
  1;
};
if (!$created) {
  my $error = $@ || 'unknown kivitendo dataset creation error';
  $error =~ s/\Q$db_password\E/<redacted>/g;
  $error =~ s/\Q$superuser_pass\E/<redacted>/g;
  die "kivitendo staging dataset creation failed: $error";
}

my $staging_dsn = "dbi:Pg:dbname=$staging_db;host=$db_host;port=$db_port";
my $staging_dbh = DBI->connect(
  $staging_dsn,
  $db_user,
  $db_password,
  { AutoCommit => 0, RaiseError => 1, PrintError => 0 },
);

my $marker_created = eval {
  $staging_dbh->do(q{
    CREATE TABLE datev_skr04_migration_marker (
      marker_key text PRIMARY KEY,
      run_id text NOT NULL,
      source_database text NOT NULL,
      target_database text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK (marker_key = 'kivitendo-datev-skr04-v1')
    )
  });
  $staging_dbh->do(
    q{
      INSERT INTO datev_skr04_migration_marker
        (marker_key, run_id, source_database, target_database)
      VALUES (?, ?, ?, ?)
    },
    undef,
    $marker_key,
    $run_id,
    $source_db,
    $target_db,
  );
  $staging_dbh->commit;
  1;
};
if (!$marker_created) {
  my $error = $@ || 'unknown ownership-marker error';
  eval { $staging_dbh->rollback };
  $staging_dbh->disconnect;
  die "native staging dataset was created but run ownership could not be recorded: $error";
}
$staging_dbh->disconnect;

$admin_dbh = DBI->connect(
  $admin_dsn,
  $db_user,
  $db_password,
  { AutoCommit => 1, RaiseError => 1, PrintError => 0 },
);
my $quoted_staging = $admin_dbh->quote_identifier($staging_db);
my $quoted_target  = $admin_dbh->quote_identifier($target_db);
my $renamed = eval {
  $admin_dbh->do("ALTER DATABASE $quoted_staging RENAME TO $quoted_target");
  1;
};
if (!$renamed) {
  my $error = $@ || 'unknown atomic target rename error';
  $admin_dbh->disconnect;
  die "native staging dataset could not be atomically promoted to the unused target name: $error";
}
$admin_dbh->disconnect;

my $target_dsn = "dbi:Pg:dbname=$target_db;host=$db_host;port=$db_port";
my $target_dbh = DBI->connect(
  $target_dsn,
  $db_user,
  $db_password,
  { AutoCommit => 1, RaiseError => 1, PrintError => 0 },
);
my ($defaults_rows) = $target_dbh->selectrow_array('SELECT count(*) FROM defaults');
my ($installed_coa) = $target_dbh->selectrow_array('SELECT coa FROM defaults');
my ($account_count)  = $target_dbh->selectrow_array(
  q{SELECT count(*) FROM chart WHERE charttype = 'A'},
);
my ($wrong_lengths)  = $target_dbh->selectrow_array(
  q{SELECT count(*) FROM chart WHERE charttype = 'A' AND accno !~ '^[0-9]{4}$'},
);
my $marker = $target_dbh->selectrow_hashref(
  q{
    SELECT marker_key, run_id, source_database, target_database
    FROM datev_skr04_migration_marker
    WHERE marker_key = ?
  },
  undef,
  $marker_key,
);
$target_dbh->disconnect;

die "Created dataset has an ambiguous defaults state\n"
  if !defined($defaults_rows) || $defaults_rows != 1;
die "Created dataset has unexpected chart of accounts\n"
  if !defined($installed_coa) || $installed_coa ne $chart;
die "Created dataset contains no general-ledger accounts\n"
  if !$account_count;
die "Created dataset contains non-four-digit general-ledger accounts\n"
  if $wrong_lengths;
die "Created dataset lost or changed its migration ownership marker\n"
  if !$marker
  || $marker->{run_id} ne $run_id
  || $marker->{source_database} ne $source_db
  || $marker->{target_database} ne $target_db;

print "Created isolated, run-bound SKR04 dataset '$target_db' through native staging initialization and atomic promotion.\n";
