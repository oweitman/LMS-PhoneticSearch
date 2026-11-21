use strict;
use warnings;
use utf8;

BEGIN {
    my $root = $ARGV[0] or die "Usage: perl test_search_corpus.pl ROOT LIVE_SOURCE\n";
    unshift @INC, "$root/lib", '/lms/CPAN/arch/5.40',
        '/lms/CPAN/arch/5.40/x86_64-linux-thread-multi', '/lms/CPAN';
}

use DBI;
use DBD::SQLite;
use File::Spec;
use File::Temp qw(tempdir);
use Plugins::PhoneticSearch::Indexer;
use Plugins::PhoneticSearch::Search;
use Plugins::PhoneticSearch::Loader;

binmode STDOUT, ':encoding(UTF-8)';

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
my $source = DBI->connect("dbi:SQLite:dbname=$source_path", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
}) or die DBI->errstr;
my @names = ('The Beatles', 'Pink Floyd', 'Rihanna', 'Justin Bieber',
             'Beyoncé', 'Rammstein', 'AC/DC', 'P!nk', 'Die Ärzte',
             'Queen', 'Love', 'Live', 'Alphaville');
for my $name (@names) {
    $source->do('INSERT INTO contributors(name) VALUES (?)', undef, $name);
}
$source->disconnect;
my $indexer = Plugins::PhoneticSearch::Indexer->new(
    root => $root, source => $source_path, index => $index_path);
$indexer->run;
die "Corpus index verification failed\n" unless $indexer->verify->{verified} >= 1500;
my $damage = DBI->connect("dbi:SQLite:dbname=$index_path", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
}) or die DBI->errstr;
Plugins::PhoneticSearch::Loader->new(root => $root)->load_on_handle($damage);
$damage->do("DELETE FROM ps_alias WHERE alias='pink'");
$damage->disconnect;
my $alias_verified = eval { $indexer->verify; 1 };
die "Verification accepted missing alias\n" if $alias_verified;
$indexer->run(rebuild => 1);
die "Alias repair failed\n" unless $indexer->verify->{verified} >= 1500;
my $search = Plugins::PhoneticSearch::Search->new(
    root => $root, source => $source_path, index => $index_path);
my @cases = (
    [ 'Bitels', 'The Beatles', 'typo' ],
    [ 'Bietels', 'The Beatles', 'typo' ],
    [ 'Pink Floid', 'Pink Floyd', 'typo' ],
    [ 'Riana', 'Rihanna', 'typo' ],
    [ 'Ramstein', 'Rammstein', 'typo' ],
    [ 'Beyonce', 'Beyoncé', 'diacritic' ],
    [ 'ACDC', 'AC/DC', 'punctuation' ],
    [ 'Pink', 'P!nk', 'punctuation' ],
    [ 'Die Aerzte', 'Die Ärzte', 'transliteration' ],
    [ 'Dschastin Biber', 'Justin Bieber', 'asr' ],
    [ 'alpha will', 'Alphaville', 'asr' ],
    [ 'alfa will', 'Alphaville', 'asr' ],
    [ 'Queen', 'Queen', 'exact' ],
);
my %groups;
for my $case (@cases) {
    my ($query, $expected, $group) = @$case;
    my $result = $search->search(query => $query, types => ['artist'], limit => 5);
    my @top = map { $_->{name} } @{ $result->{results_loop} };
    my $top1 = @top && $top[0] eq $expected ? 1 : 0;
    my $top5 = grep { $_ eq $expected } @top;
    ++$groups{$group}{count};
    $groups{$group}{top1} += $top1;
    $groups{$group}{top5} += $top5 ? 1 : 0;
    print "$group query=$query expected=$expected top1=" . (@top ? $top[0] : '-') .
          " top1_ok=$top1 top5_ok=" . ($top5 ? 1 : 0) . "\n";
}
for my $group (sort keys %groups) {
    my $stats = $groups{$group};
    print "group=$group top1=$stats->{top1}/$stats->{count} " .
          "top5=$stats->{top5}/$stats->{count}\n";
}
my $index = DBI->connect("dbi:SQLite:dbname=$index_path", '', '', {
    RaiseError => 1, PrintError => 0, AutoCommit => 1,
}) or die DBI->errstr;
Plugins::PhoneticSearch::Loader->new(root => $root)->load_on_handle($index);
for my $query ('bitels', 'bietels', 'the bitels', 'the bietels',
               'dschastin biber', 'jastin biber', 'justin biber') {
    for my $scope (2, 3) {
        my $rows = $index->selectall_arrayref(
            'SELECT word FROM ps_spell_artist WHERE word MATCH ? AND scope=? AND top=100',
            undef, $query, $scope);
        my $position = 0;
        for my $row (@$rows) {
            ++$position;
            if ($row->[0] =~ /beatles|bieber/) {
                print "spellfix query=$query scope=$scope target_rank=$position\n";
                last;
            }
        }
        print "spellfix query=$query scope=$scope target_rank=none\n"
            unless grep { $_->[0] =~ /beatles|bieber/ } @$rows;
    }
}
$index->disconnect;
my $short = $search->search(query => 'a', types => ['artist']);
die "Short query used fuzzy matching\n"
    if grep { $_->{match_type} eq 'phonetic' } @{ $short->{results_loop} };
die "Exact query failed\n" unless $groups{exact}{top1} == 1;
die "Typos below 90 percent Top 5\n"
    unless $groups{typo}{top5} / $groups{typo}{count} >= .9;
die "ASR cases failed\n" unless $groups{asr}{top5} == 3;
my $pink = $search->search(query => 'Pink', types => ['artist'], limit => 5);
die "Exact Pink must rank first and P!nk must be suggested\n"
    unless $pink->{results_loop}->[0]->{name} eq 'Pink'
        && $pink->{results_loop}->[0]->{match_type} eq 'exact'
        && grep { $_->{name} eq 'P!nk' && $_->{match_type} eq 'alias' }
                @{ $pink->{results_loop} };
