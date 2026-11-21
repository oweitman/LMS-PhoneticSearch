use strict;
use warnings;

use File::Basename qw(dirname);
use File::Temp qw(tempfile);
use JSON::PP;
use Time::HiRes qw(time);

my ($root, $source, $index, $status_path, $full, $operation) = @ARGV;
die "worker arguments missing\n" unless defined($full) && $full =~ /\A[01]\z/;
$operation ||= 'index';
die "invalid worker operation\n" unless $operation =~ /\A(?:index|rebuild|verify)\z/;
unshift @INC, "$root/lib";
require Plugins::PhoneticSearch::Indexer;

my $started = time();
my $result = eval {
    my $indexer = Plugins::PhoneticSearch::Indexer->new(
        root => $root, source => $source, index => $index);
    $operation eq 'verify' ? $indexer->verify
        : $indexer->run(full => $full, rebuild => $operation eq 'rebuild');
};
my $error = $@;
my $state = $result ? 'ready' : $error =~ /source_changed/ ? 'stale' : 'error';
my $document = {
    state => $state,
    operation => $operation,
    mode => $result ? $result->{mode} : undef,
    changes => $result ? $result->{changes} : undef,
    recent_tracks => $result ? $result->{recent_tracks} : undef,
    verified => $result ? $result->{verified} : undef,
    completed_at => time(),
    duration_ms => int((time() - $started) * 1000 + 0.5),
    error => $result ? undef : "$error",
};

my ($file, $temporary) = tempfile('worker-status-XXXXXXXX',
                                  DIR => dirname($status_path), UNLINK => 0);
print {$file} JSON::PP->new->canonical->encode($document);
close $file or die "status close failed: $!\n";
rename($temporary, $status_path) or die "status swap failed: $!\n";
exit($result ? 0 : $state eq 'stale' ? 2 : 1);
