use strict;
use warnings;

BEGIN {
    my $root = $ARGV[0] or die "Usage: perl test_loader.pl /absolute/fixture/root\n";
    unshift @INC, "$root/lib", '/lms/CPAN/arch/5.40',
        '/lms/CPAN/arch/5.40/x86_64-linux-thread-multi', '/lms/CPAN';
}

use DBI;
use File::Copy qw(copy);
use File::Path qw(make_path);
use File::Spec;
use File::Temp qw(tempdir);
use Plugins::PhoneticSearch::Loader;

my $root = shift @ARGV;
my $loader = Plugins::PhoneticSearch::Loader->new(root => $root);
my $binary = $loader->binary_path;
-f $binary or die "Binary missing\n";

my $dbh = DBI->connect('dbi:SQLite:dbname=:memory:', '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
}) or die DBI->errstr;
$loader->load_on_handle($dbh);
$dbh->do('CREATE VIRTUAL TABLE words USING spellfix1');
$dbh->do("INSERT INTO words(word) VALUES ('alphaville')");
my ($name) = $dbh->selectrow_array("SELECT word FROM words WHERE word MATCH 'alfa will'");
die "Spellfix MATCH failed\n" unless $name eq 'alphaville';
my $still_enabled = eval {
    $dbh->do('SELECT load_extension(?, ?)', undef, $binary, 'sqlite3_spellfix_init');
    1;
};
die "Extension loading remained enabled\n" if $still_enabled;
$dbh->disconnect;

my $temporary = tempdir(CLEANUP => 1);
my $bin_dir = File::Spec->catdir($temporary, 'Bin', 'linux-x86_64');
make_path($bin_dir);
copy(File::Spec->catfile($root, 'Bin', 'manifest.json'),
     File::Spec->catfile($temporary, 'Bin', 'manifest.json')) or die $!;
copy($binary, File::Spec->catfile($bin_dir, 'spellfix.so')) or die $!;
open my $damage, '>>', File::Spec->catfile($bin_dir, 'spellfix.so') or die $!;
print $damage 'damage';
close $damage;
my $bad = Plugins::PhoneticSearch::Loader->new(root => $temporary);
my $verified = eval { $bad->binary_path; 1 };
die "Corrupt binary accepted\n" if $verified || $@ !~ /checksum mismatch/;

print "loader=ok match=alphaville loading_disabled=1 bad_checksum=rejected " .
      "DBD=$DBD::SQLite::VERSION\n";
