use strict;
use warnings;

BEGIN {
    my $root = $ARGV[0] or die "Usage: perl test_indexer.pl ROOT LIVE_SOURCE\n";
    unshift @INC, "$root/lib", '/lms/CPAN/arch/5.40',
        '/lms/CPAN/arch/5.40/x86_64-linux-thread-multi', '/lms/CPAN';
}

use DBI;
use File::Spec;
use File::Temp qw(tempdir);
use Time::HiRes qw(time);
use Plugins::PhoneticSearch::Indexer;
use Plugins::PhoneticSearch::Search;

my ($root, $live_source) = @ARGV;
my $directory = tempdir(CLEANUP => 1);
my $source_path = File::Spec->catfile($directory, 'library.db');
my $index_path = File::Spec->catfile($directory, 'index.db');
my $live = DBI->connect("dbi:SQLite:dbname=$live_source", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
    sqlite_open_flags => DBD::SQLite::OPEN_READONLY(),
}) or die DBI->errstr;
$live->do('VACUUM INTO ' . $live->quote($source_path));
$live->disconnect;

my $indexer = Plugins::PhoneticSearch::Indexer->new(
    root => $root, source => $source_path, index => $index_path);
my $initial = $indexer->run;
die "Initial full build failed\n" unless $initial->{mode} eq 'full' && $initial->{changes} >= 1000;
my $verified = $indexer->verify;
die "Initial verification failed\n"
    unless $verified->{mode} eq 'verify' && $verified->{verified} == $initial->{changes};
my $rebuilt = $indexer->run(rebuild => 1);
die "Explicit staging rebuild failed\n"
    unless $rebuilt->{mode} eq 'full' && $rebuilt->{changes} == $initial->{changes};
my $idle = $indexer->run;
die "Idle fast path failed: mode=$idle->{mode} changes=$idle->{changes}\n"
    unless $idle->{mode} eq 'fast' && $idle->{changes} == 0;

my $db = DBI->connect("dbi:SQLite:dbname=$source_path", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
}) or die DBI->errstr;
my ($max_updated) = $db->selectrow_array('SELECT coalesce(max(updated_time),0) FROM tracks');
my $updated = int(time()) > $max_updated ? int(time()) : $max_updated + 2;
$db->do("INSERT INTO albums(title) VALUES ('POC Perl Album')");
my $album = $db->sqlite_last_insert_rowid;
$db->do("INSERT INTO contributors(name) VALUES ('POC Perl Artist')");
my $artist = $db->sqlite_last_insert_rowid;
$db->do("INSERT INTO genres(name) VALUES ('POC Perl Genre')");
my $genre = $db->sqlite_last_insert_rowid;
$db->do('INSERT INTO tracks(url,title,audio,remote,album,updated_time) VALUES (?,?,?,?,?,?)',
        undef, 'file:///poc-perl-track', 'POC Perl Track', 1, 0, $album, $updated);
my $track = $db->sqlite_last_insert_rowid;
$db->do('INSERT INTO contributor_track(role,contributor,track) VALUES (1,?,?)', undef, $artist, $track);
$db->do('INSERT INTO genre_track(genre,track) VALUES (?,?)', undef, $genre, $track);
$db->disconnect;

my $fast = $indexer->run;
die "Fast path missed new entities\n" unless $fast->{mode} eq 'fast' && $fast->{changes} >= 4;
my $check = DBI->connect("dbi:SQLite:dbname=$index_path", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
}) or die DBI->errstr;
Plugins::PhoneticSearch::Loader->new(root => $root)->load_on_handle($check);
for my $case (
    [ artist => $artist, 'POC Perl Artist' ],
    [ album => $album, 'POC Perl Album' ],
    [ track => $track, 'POC Perl Track' ],
    [ genre => $genre, 'POC Perl Genre' ],
) {
    my ($kind, $id, $name) = @$case;
    my ($actual) = $check->selectrow_array(
        'SELECT original FROM ps_entity WHERE entity_type=? AND entity_id=?',
        undef, $kind, $id);
    die "$kind not indexed\n" unless defined($actual) && $actual eq $name;
}
my ($match) = $check->selectrow_array(
    "SELECT word FROM ps_spell_artist WHERE word MATCH 'poc perl artst' LIMIT 1");
die "Perl Spellfix search failed\n" unless $match eq 'poc perl artist';
$check->disconnect;
my $search = Plugins::PhoneticSearch::Search->new(
    root => $root, source => $source_path, index => $index_path);
my $fuzzy = $search->search(query => 'poc perl artst', types => ['artist']);
die "Search did not find new artist\n"
    unless $fuzzy->{count} && $fuzzy->{results_loop}->[0]->{name} eq 'POC Perl Artist';
my $asr = $search->search(query => 'alfa will', types => ['artist']);
die "ASR search did not find Alphaville\n"
    unless $asr->{count} && $asr->{results_loop}->[0]->{name} eq 'Alphaville';

$db = DBI->connect("dbi:SQLite:dbname=$source_path", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
}) or die DBI->errstr;
my ($direct_artist) = $db->selectrow_array(
    'SELECT id FROM contributors WHERE id<>? AND name IS NOT NULL LIMIT 1', undef, $artist);
$db->do("UPDATE contributors SET name='POC Renamed Directly' WHERE id=?", undef, $direct_artist);
$db->do('DELETE FROM genres WHERE id=?', undef, $genre);
$db->disconnect;
my $missed = $indexer->run;
die "Direct contributor change unexpectedly fast\n"
    unless $missed->{mode} eq 'fast' && $missed->{changes} == 0;
my $stale_verified = eval { $indexer->verify; 1 };
die "Verification accepted stale index\n" if $stale_verified;
my $full = $indexer->run(full => 1);
$check = DBI->connect("dbi:SQLite:dbname=$index_path", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
}) or die DBI->errstr;
my ($renamed) = $check->selectrow_array(
    "SELECT original FROM ps_entity WHERE entity_type='artist' AND entity_id=?",
    undef, $direct_artist);
my ($deleted_genre) = $check->selectrow_array(
    "SELECT count(*) FROM ps_entity WHERE entity_type='genre' AND entity_id=?",
    undef, $genre);
$check->disconnect;
die "Full reconciliation missed rename or deletion\n"
    unless $full->{mode} eq 'full' && $full->{changes} == 2
        && !$full->{rebuilt} && $renamed eq 'POC Renamed Directly' && !$deleted_genre;

$db = DBI->connect("dbi:SQLite:dbname=$source_path", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
}) or die DBI->errstr;
my $bulk_time = $updated + 3;
$db->begin_work;
for my $number (1..5001) {
    $db->do('INSERT INTO tracks(url,title,audio,remote,updated_time) VALUES (?,?,?,?,?)',
            undef, "file:///poc-perl-bulk-$number", "POC Bulk $number", 1, 0, $bulk_time);
}
$db->commit;
$db->disconnect;
my $overflow = $indexer->run;
die "Large delta did not fall back to a full build\n" unless $overflow->{mode} eq 'full';

open my $corrupt, '>', $index_path or die $!;
print $corrupt 'corrupt index';
close $corrupt;
my $recovered = $indexer->run;
die "Corrupt index was not rebuilt\n" unless $recovered->{mode} eq 'full';
my $orphan = File::Spec->catfile($directory, 'phonetic-stage-ABCDEFGH');
open my $leftover, '>', $orphan or die $!;
print {$leftover} 'incomplete stage';
close $leftover;
$indexer->run;
die "Orphan stage was not removed\n" if -e $orphan;

print "indexer=ok initial=$initial->{changes} idle=$idle->{changes} " .
      "fast=$fast->{changes} recent_tracks=$fast->{recent_tracks} " .
      "direct_change_fast=$missed->{changes} full=$full->{changes} " .
      "overflow=$overflow->{mode} corrupt=$recovered->{mode} " .
      "verify=$verified->{verified} stale_verify=rejected " .
      "rebuild=$rebuilt->{mode} orphan=cleaned " .
      "search=$match asr=Alphaville\n";
