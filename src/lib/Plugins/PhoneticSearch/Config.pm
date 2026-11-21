package Plugins::PhoneticSearch::Config;

use strict;
use warnings;

use constant DEFAULT_INTERVAL => 5;
use constant MIN_INTERVAL => 5;
use constant MAX_INTERVAL => 3600;
use POSIX qw(ceil);

sub valid_interval {
    my ($value) = @_;
    return 0 if !defined($value) || ref($value) || $value !~ /\A[0-9]{1,4}\z/;
    return $value >= MIN_INTERVAL && $value <= MAX_INTERVAL ? 1 : 0;
}

sub interval_or_default {
    my ($value) = @_;
    return valid_interval($value) ? int($value) : DEFAULT_INTERVAL;
}

sub suggested_interval {
    my ($duration_ms, $configured) = @_;
    return undef unless defined($duration_ms) && $duration_ms =~ /\A[0-9]+\z/;
    $configured = interval_or_default($configured);
    return undef unless $duration_ms > $configured * 1000;
    my $suggested = ceil($duration_ms * 1.25 / 1000);
    return $suggested > MAX_INTERVAL ? MAX_INTERVAL : $suggested;
}

1;
