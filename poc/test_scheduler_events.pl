use strict;
use warnings;
use Test::More;
use File::Temp qw(tempfile tempdir);
use Time::HiRes qw(time);
use lib 'src/lib';

BEGIN {
    for my $module (qw(DBI DBD::SQLite Proc::Background Slim::Control::Request
                       Slim::Music::Import Slim::Utils::Prefs Slim::Utils::Timers)) {
        (my $file = "$module.pm") =~ s!::!/!g;
        $INC{$file} = __FILE__;
    }
    package DBI; sub import { }
    package DBD::SQLite; sub import { } sub OPEN_READONLY { 1 }
    package Proc::Background; sub import { }
    package Slim::Control::Request;
    our (@SUBSCRIPTIONS, @UNSUBSCRIPTIONS);
    sub subscribe { push @SUBSCRIPTIONS, [@_] }
    sub unsubscribe { push @UNSUBSCRIPTIONS, $_[0] }
    package Slim::Music::Import;
    our $SCANNING = 0;
    sub stillScanning { return $SCANNING }
    package Slim::Utils::Timers;
    our (@SCHEDULED, $KILLED);
    sub killTimers { ++$KILLED }
    sub setTimer { push @SCHEDULED, $_[1] }
}

require Plugins::PhoneticSearch::Scheduler;

{ package TestGate; sub selectrow_array { 1 } sub disconnect { } }
{ package TestLog; sub info { } sub error { } }
{ package TestWorker; sub alive { 0 } sub wait { 0 } }

my ($file, $index) = tempfile();
close $file;
my $subscriptions = bless {
    active => 0, directory => tempdir(CLEANUP => 1),
}, 'Plugins::PhoneticSearch::Scheduler';
$subscriptions->start;
is(scalar @Slim::Control::Request::SUBSCRIPTIONS, 2,
    'scan completion and targeted rescans are both subscribed');
is_deeply($Slim::Control::Request::SUBSCRIPTIONS[1][1],
    [['rescan'], ['album', 'track']], 'targeted subscription covers album and track');
$subscriptions->stop;
is(scalar @Slim::Control::Request::UNSUBSCRIPTIONS, 2,
    'both scan subscriptions are removed on stop');
my $scheduler = bless {
    active => 1, gate => bless({}, 'TestGate'), identity => 'source',
    version => 1, index => $index, state => 'ready',
    pending => 0, force_full => 0, log => bless({}, 'TestLog'),
}, 'Plugins::PhoneticSearch::Scheduler';
my $launches = 0;
{
    no warnings 'redefine';
    local *Plugins::PhoneticSearch::Scheduler::_identity = sub { 'source' };
    local *Plugins::PhoneticSearch::Scheduler::_launch = sub { ++$launches };
    @Slim::Utils::Timers::SCHEDULED = ();
    $scheduler->_tick;
    is($launches, 0, 'idle tick does not start a worker');
    is(scalar @Slim::Utils::Timers::SCHEDULED, 0,
        'idle scheduler leaves no recurring timer');

    $scheduler->scan_done;
    ok($scheduler->{pending} && $scheduler->{force_full},
        'scan event requests a full reconciliation');
    $scheduler->{settle_until} = time() - 1;
    @Slim::Utils::Timers::SCHEDULED = ();
    $scheduler->_tick;
    is($launches, 1, 'scan event starts one worker');
    is(scalar @Slim::Utils::Timers::SCHEDULED, 1,
        'running worker gets a completion check');

    $scheduler->{pending} = 1;
    $scheduler->{retry_at} = time() + 50;
    @Slim::Utils::Timers::SCHEDULED = ();
    $scheduler->_tick;
    is($launches, 1, 'retry delay prevents an early worker start');
    ok(@Slim::Utils::Timers::SCHEDULED == 1 &&
        $Slim::Utils::Timers::SCHEDULED[0] - time() > 45,
        'retry schedules one future timer');

    $scheduler->{retry_at} = undef;
    $Slim::Music::Import::SCANNING = 1;
    @Slim::Utils::Timers::SCHEDULED = ();
    $scheduler->_tick;
    is($launches, 1, 'scan in progress blocks reconciliation');
    is(scalar @Slim::Utils::Timers::SCHEDULED, 1,
        'scan in progress is checked until it ends');
    $Slim::Music::Import::SCANNING = 0;
}

$scheduler->{worker} = bless({}, 'TestWorker');
$scheduler->{pending} = 1;
$scheduler->{force_full} = 1;
$scheduler->{launch_version} = 1;
{
    no warnings 'redefine';
    local *Plugins::PhoneticSearch::Scheduler::_identity = sub { 'source' };
    local *Plugins::PhoneticSearch::Scheduler::_read_worker_status = sub {
        return { state => 'ready', mode => 'fast', changes => 0,
                 completed_at => time(), operation => 'index' };
    };
    $scheduler->_check_worker;
}
ok($scheduler->{pending} && $scheduler->{force_full},
    'scan event received during worker survives completion');

$scheduler->{worker} = bless({}, 'TestWorker');
$scheduler->{pending} = 0;
$scheduler->{force_full} = 0;
$scheduler->{launch_full} = 1;
{
    no warnings 'redefine';
    local *Plugins::PhoneticSearch::Scheduler::_read_worker_status = sub {
        return { state => 'stale' };
    };
    $scheduler->_check_worker;
}
ok($scheduler->{pending} && $scheduler->{force_full},
    'stale full reconciliation is retried as full');

$scheduler->{worker} = bless({}, 'TestWorker');
$scheduler->{pending} = 0;
$scheduler->{force_full} = 0;
{
    no warnings 'redefine';
    local *Plugins::PhoneticSearch::Scheduler::_read_worker_status = sub {
        return { state => 'error', error => 'extension_unavailable' };
    };
    $scheduler->_check_worker;
}
ok($scheduler->{pending} && $scheduler->{force_full} &&
    $scheduler->{retry_at} > time(),
    'failed full reconciliation keeps full retry with backoff');

done_testing();
