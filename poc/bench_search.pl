use strict;
use warnings;

BEGIN {
    my $root = $ARGV[0] or die "Usage: perl bench_search.pl ROOT SOURCE INDEX\n";
    unshift @INC, "$root/lib", '/lms/CPAN/arch/5.40',
        '/lms/CPAN/arch/5.40/x86_64-linux-thread-multi', '/lms/CPAN';
}

use Time::HiRes qw(time);
use Plugins::PhoneticSearch::Search;

my ($root, $source, $index) = @ARGV;
my $search = Plugins::PhoneticSearch::Search->new(
    root => $root, source => $source, index => $index);
for my $case (
    [ 'Benchmark Track 50000', 'track' ],
    [ 'alfa will', 'artist' ],
    [ 'Benchmark Trak 50000', 'track' ],
) {
    my ($query, $type) = @$case;
    $search->search(query => $query, types => [$type]);
    my @ms;
    my $top;
    for (1..20) {
        my $start = time();
        my $result = $search->search(query => $query, types => [$type]);
        push @ms, (time() - $start) * 1000;
        $top = $result->{results_loop}->[0]->{name} if @{ $result->{results_loop} };
    }
    @ms = sort { $a <=> $b } @ms;
    printf "query=%s type=%s p50_ms=%.2f p95_ms=%.2f max_ms=%.2f top=%s\n",
        $query, $type, $ms[9], $ms[18], $ms[19], defined($top) ? $top : '-';
}
