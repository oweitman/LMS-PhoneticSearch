package Plugins::PhoneticEventProbe::Plugin;

use strict;
use warnings;

use base qw(Slim::Plugin::Base);

use Slim::Control::Request;
use Slim::Utils::Timers;
use Time::HiRes qw(time);

my $active = 0;
my $pending = 0;
my $ticks = 0;
my $events = 0;

sub getDisplayName { return 'Phonetic Event Probe'; }

sub initPlugin {
    my $class = shift;
    return if main::SCANNER;
    $class->SUPER::initPlugin(@_);
    $active = 1;
    Slim::Control::Request::subscribe(\&scan_done, [['rescan'], ['done']]);
    warn "PHONETIC_EVENT_PROBE init\n";
    Slim::Utils::Timers::setTimer(__PACKAGE__, time() + 5, \&tick);
}

sub scan_done {
    return unless $active;
    ++$events;
    warn "PHONETIC_EVENT_PROBE scan_done=$events\n";
    return if $pending;
    $pending = 1;
    Slim::Utils::Timers::setTimer(__PACKAGE__, time() + 0.1, \&deferred);
}

sub deferred {
    return unless $active;
    $pending = 0;
    warn "PHONETIC_EVENT_PROBE deferred_scan_check=$events\n";
}

sub tick {
    return unless $active;
    ++$ticks;
    warn "PHONETIC_EVENT_PROBE tick=$ticks\n";
    Slim::Utils::Timers::setTimer(__PACKAGE__, time() + 5, \&tick);
}

sub shutdownPlugin {
    $active = 0;
    Slim::Control::Request::unsubscribe(\&scan_done);
    Slim::Utils::Timers::killTimers(__PACKAGE__, \&tick);
    Slim::Utils::Timers::killTimers(__PACKAGE__, \&deferred);
    warn "PHONETIC_EVENT_PROBE shutdown ticks=$ticks events=$events\n";
}

1;
