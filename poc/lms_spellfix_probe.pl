use strict;
use warnings;
use DBI;
use DBD::SQLite;
use File::Temp qw(tempdir);
use File::Spec;

my $binary = shift @ARGV or die "Usage: perl lms_spellfix_probe.pl /absolute/path/spellfix.so\n";
-f $binary or die "Missing binary: $binary\n";
$binary =~ m{^/} or die "Binary path must be absolute\n";

print "Perl $] DBI $DBI::VERSION DBD::SQLite $DBD::SQLite::VERSION\n";
my $dir = tempdir(CLEANUP => 1);
for my $name (':memory:', File::Spec->catfile($dir, 'index.db')) {
    my $dbh = DBI->connect("dbi:SQLite:dbname=$name", '', '', {
        RaiseError => 1, PrintError => 0, AutoCommit => 1,
    }) or die DBI->errstr;
    my ($sqlite_version) = $dbh->selectrow_array('SELECT sqlite_version()');
    print "SQLite $sqlite_version\n";
    my $loaded = eval {
        $dbh->sqlite_enable_load_extension(1);
        $dbh->do('SELECT load_extension(?, ?)', undef, $binary, 'sqlite3_spellfix_init');
        1;
    };
    my $load_error = $@;
    $dbh->sqlite_enable_load_extension(0);
    die "Extension load failed: $load_error" if !$loaded;
    my $still_enabled = eval {
        $dbh->do('SELECT load_extension(?, ?)', undef, $binary, 'sqlite3_spellfix_init');
        1;
    };
    die "Extension loading remained enabled for $name\n" if $still_enabled;
    $dbh->do('CREATE VIRTUAL TABLE words USING spellfix1');
    $dbh->do("INSERT INTO words(word) VALUES ('beatles')");
    my ($result) = $dbh->selectrow_array("SELECT word FROM words WHERE word MATCH 'beatls'");
    die "MATCH failed for $name\n" if !defined($result) || $result ne 'beatles';
    print "PASS $name: $result\n";
    $dbh->disconnect;
}
