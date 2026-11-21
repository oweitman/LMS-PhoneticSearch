use strict;
use warnings;
use Test::More;
use lib 'src/lib';
use lib '/lms/CPAN/arch/5.40',
        '/lms/CPAN/arch/5.40/x86_64-linux-thread-multi', '/lms/CPAN', '/lms/lib', '/lms';

BEGIN {
    for my $module (qw(Slim::Control::Request Slim::Music::Import
                       Slim::Utils::Prefs Slim::Utils::Timers)) {
        (my $file = "$module.pm") =~ s!::!/!g;
        $INC{$file} = __FILE__;
    }
}

require Plugins::PhoneticSearch::Scheduler;

{
    package TestPrefs;
    sub get { return 5 }
}
{
    package TestLog;
    sub error { die $_[1] }
}

my $scheduler = bless {
    active => 1,
    prefs => bless({}, 'TestPrefs'),
    log => bless({}, 'TestLog'),
    worker => bless({}, 'TestWorker'),
    pending => 1,
}, 'Plugins::PhoneticSearch::Scheduler';

my ($delay, $launches);
{
    no warnings 'redefine';
    local *Plugins::PhoneticSearch::Scheduler::_check_worker = sub {
        my ($self) = @_;
        $self->{worker} = undef;
        return 0;
    };
    local *Plugins::PhoneticSearch::Scheduler::_timer = sub {
        $delay = $_[1];
    };
    local *Plugins::PhoneticSearch::Scheduler::_launch = sub {
        $launches++;
    };
    $scheduler->_tick;
}
is($delay, 5, 'next automatic tick waits five seconds after worker completion');
is($launches || 0, 0, 'pending change does not launch a second worker in completion tick');

$scheduler->{worker} = bless({}, 'TestWorker');
{
    no warnings 'redefine';
    local *Plugins::PhoneticSearch::Scheduler::_check_worker = sub { return 1 };
    local *Plugins::PhoneticSearch::Scheduler::_timer = sub { $delay = $_[1] };
    local *Plugins::PhoneticSearch::Scheduler::_launch = sub { $launches++ };
    $scheduler->_tick;
}
is($delay, 1, 'active worker is checked again after one second');
is($launches || 0, 0, 'active worker prevents parallel launch');

done_testing();
