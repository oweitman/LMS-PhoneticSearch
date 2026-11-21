package Plugins::PhoneticSearch::Plugin;

use strict;
use warnings;

use base qw(Slim::Plugin::Base);

use File::Basename qw(dirname);
use Slim::Utils::Log;
use Slim::Utils::Prefs;
use Plugins::PhoneticSearch::Config;

my $prefs = preferences('plugin.phoneticsearch');
$prefs->init({ reconcile_interval_seconds => Plugins::PhoneticSearch::Config::DEFAULT_INTERVAL });
my $log = Slim::Utils::Log->addLogCategory({
    category => 'plugin.phoneticsearch',
    defaultLevel => 'WARN',
    description => 'PLUGIN_PHONETICSEARCH',
});
my $scheduler;
my $action_token;

sub _newActionToken {
    open my $random, '<:raw', '/dev/urandom'
        or die "secure random source unavailable: $!\n";
    my $token = '';
    my $read = read($random, $token, 32);
    close $random;
    die "secure random source incomplete\n" unless defined($read) && $read == 32;
    return unpack('H*', $token);
}

sub getDisplayName { return 'PLUGIN_PHONETICSEARCH'; }

sub reconcileInterval {
    return Plugins::PhoneticSearch::Config::interval_or_default(
        $prefs->get('reconcile_interval_seconds')
    );
}

sub initPlugin {
    my $class = shift;
    return if main::SCANNER;
    $class->SUPER::initPlugin(@_);
    $action_token = _newActionToken();
    if ( main::WEBUI ) {
        require Plugins::PhoneticSearch::Settings;
        Plugins::PhoneticSearch::Settings->new;
    }
    my $started = eval {
        require Plugins::PhoneticSearch::Scheduler;
        $scheduler = Plugins::PhoneticSearch::Scheduler->new(
            root => dirname(__FILE__), prefs => $prefs, log => $log);
        $scheduler->start;
        require Plugins::PhoneticSearch::API;
        Plugins::PhoneticSearch::API->register(
            root => dirname(__FILE__),
            source => $scheduler->{source}, index => $scheduler->{index},
            status => sub { $scheduler->status }, log => $log);
        1;
    };
    $log->error("Indexer scheduler startup failed: $@") unless $started;
}

sub intervalChanged {
    $scheduler->interval_changed if $scheduler;
}

sub indexStatus {
    return $scheduler ? $scheduler->status : { state => 'disabled' };
}

sub actionToken { return $action_token; }

sub validActionToken {
    my ($class, $submitted) = @_;
    return 0 unless defined($action_token) && defined($submitted)
        && $submitted =~ /\A[0-9a-f]{64}\z/;
    my $difference = 0;
    for my $i (0..63) {
        $difference |= ord(substr($action_token, $i, 1)) ^
                       ord(substr($submitted, $i, 1));
    }
    return $difference == 0;
}

sub requestRebuild {
    die "scheduler_unavailable\n" unless $scheduler;
    $scheduler->request_rebuild;
}

sub requestVerify {
    die "scheduler_unavailable\n" unless $scheduler;
    $scheduler->request_verify;
}

sub requestCleanup {
    die "scheduler_unavailable\n" unless $scheduler;
    $scheduler->request_cleanup;
}

sub shutdownPlugin {
    $scheduler->stop if $scheduler;
    $scheduler = undef;
    $action_token = undef;
}

1;
