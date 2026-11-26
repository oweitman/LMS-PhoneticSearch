use strict;
use warnings;
use utf8;

BEGIN {
    my $root = $ARGV[0] or die "Usage: perl bench_track_phrases.pl ROOT LIVE_SOURCE\n";
    unshift @INC, "$root/lib", '/lms/CPAN/arch/5.40',
        '/lms/CPAN/arch/5.40/x86_64-linux-thread-multi', '/lms/CPAN';
}

use DBI;
use File::Spec;
use File::Temp qw(tempdir);
use Time::HiRes qw(time);
use Plugins::PhoneticSearch::Indexer;
use Plugins::PhoneticSearch::Search;

my ($root, $source_path) = @ARGV;
my $directory = tempdir(CLEANUP => 1);
my $index_path = File::Spec->catfile($directory, 'index.db');
my $indexer = Plugins::PhoneticSearch::Indexer->new(
    root => $root, source => $source_path, index => $index_path);
my $started = time();
my $build = $indexer->run;
my $build_seconds = time() - $started;
die "Expected a fresh index\n" unless $build->{mode} eq 'full';
my $index_bytes = -s $index_path;
my $source = DBI->connect("dbi:SQLite:dbname=$source_path", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
    sqlite_open_flags => DBD::SQLite::OPEN_READONLY(),
}) or die DBI->errstr;
my $rows = $source->selectall_arrayref(
    q{SELECT id,title FROM tracks WHERE length(title) BETWEEN 35 AND 80 AND title LIKE '% % % % % %' ORDER BY id LIMIT 20});
$source->disconnect;
my $search = Plugins::PhoneticSearch::Search->new(
    root => $root, source => $source_path, index => $index_path);
my ($exact_top5, $fuzzy_top5, $cases) = (0, 0, 0);
my @times;
for my $row (@$rows) {
    my ($id, $title) = @$row;
    $title = Plugins::PhoneticSearch::Indexer::_text($title);
    my $normalized = Plugins::PhoneticSearch::Indexer::_normalized($title);
    my @words = $normalized =~ /[\p{L}\p{N}]+/g;
    next unless @words >= 7;
    my $middle = int(@words / 2) - 1;
    my $query = join ' ', @words[$middle, $middle + 1];
    next unless length($words[$middle]) >= 5;
    my $typo = substr($words[$middle], 0, -1) . ' ' . $words[$middle + 1];
    my $exact = $search->search(query => $query, types => ['track'], limit => 5);
    my $start = time();
    my $fuzzy = $search->search(query => $typo, types => ['track'], limit => 5);
    push @times, 1000 * (time() - $start);
    ++$exact_top5 if grep { $_->{id} == $id } @{ $exact->{results_loop} };
    ++$fuzzy_top5 if grep { $_->{id} == $id } @{ $fuzzy->{results_loop} };
    ++$cases;
}
@times = sort { $a <=> $b } @times;
my $p95 = @times ? $times[int(0.95 * $#times)] : 0;
print "entities=$build->{changes} index_bytes=$index_bytes build_s=",
    sprintf('%.3f', $build_seconds), " real_track_cases=$cases",
    " exact_top5=$exact_top5 fuzzy_top5=$fuzzy_top5",
    " fuzzy_p95_ms=", sprintf('%.3f', $p95), "\n";
