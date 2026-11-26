package Plugins::PhoneticSearch::Scheduler;

use strict;
use warnings;

use DBI;
use DBD::SQLite;
use File::Path qw(make_path remove_tree);
use File::Spec;
use JSON::PP;
use Proc::Background;
use Slim::Control::Request;
use Slim::Music::Import;
use Slim::Utils::Prefs;
use Slim::Utils::Timers;
use Time::HiRes qw(time);

sub new {
    my ($class, %args) = @_;
    my $cache = Slim::Utils::Prefs::preferences('server')->get('librarycachedir');
    die "librarycachedir unavailable\n" unless defined $cache && length $cache;
    my $directory = File::Spec->catdir($cache, 'PhoneticSearch');
    return bless {
        root => $args{root}, prefs => $args{prefs}, log => $args{log},
        source => File::Spec->catfile($cache, 'library.db'),
        directory => $directory,
        index => File::Spec->catfile($directory, 'index.db'),
        status_path => File::Spec->catfile($directory, 'worker-status.json'),
        active => 0, state => 'initializing', error => undef,
        pending => 1, force_full => 1,
    }, $class;
}

sub _identity {
    my ($self) = @_;
    my @stat = stat($self->{source});
    return @stat ? "$stat[0]:$stat[1]" : '';
}

sub _open_gate {
    my ($self) = @_;
    $self->{gate}->disconnect if $self->{gate};
    $self->{gate} = DBI->connect("dbi:SQLite:dbname=$self->{source}", '', '', {
        RaiseError => 1, PrintError => 0, AutoCommit => 1,
        sqlite_open_flags => DBD::SQLite::OPEN_READONLY(),
    }) or die DBI->errstr;
    $self->{gate}->do('PRAGMA query_only=ON');
    $self->{identity} = $self->_identity;
    ($self->{version}) = $self->{gate}->selectrow_array('PRAGMA data_version');
}

sub _timer {
    my ($self, $delay) = @_;
    return unless $self->{active};
    Slim::Utils::Timers::killTimers($self, \&_tick);
    return unless defined $delay;
    Slim::Utils::Timers::setTimer($self, time() + $delay, \&_tick);
}

sub start {
    my ($self) = @_;
    return if $self->{active};
    make_path($self->{directory});
    $self->{active} = 1;
    $self->{subscriber} = sub { $self->scan_done(@_) };
    Slim::Control::Request::subscribe($self->{subscriber}, [['rescan'], ['done']]);
    # Album and track rescans run synchronously inside the server and need not
    # emit a separate "rescan done" notification.
    $self->{targeted_subscriber} = sub { $self->scan_done(@_) };
    Slim::Control::Request::subscribe($self->{targeted_subscriber},
        [['rescan'], ['album', 'track']]);
    $self->_timer(1);
}

sub scan_done {
    my ($self) = @_;
    return unless $self->{active};
    $self->{force_full} = 1;
    $self->{pending} = 1;
    $self->{state} = 'updating';
    $self->{settle_until} = time() + 5;
    $self->_timer(1);
}

sub request_rebuild {
    my ($self) = @_;
    die "plugin_not_active\n" unless $self->{active} && !$self->{cleanup_pending};
    $self->{requested_rebuild} = 1;
    $self->{force_full} = 1;
    $self->{pending} = 1;
    $self->{state} = 'building';
    $self->_timer(0);
}

sub request_verify {
    my ($self) = @_;
    die "plugin_not_active\n" unless $self->{active} && !$self->{cleanup_pending};
    $self->{requested_verify} = 1;
    $self->{state} = 'updating';
    $self->_timer(0);
}

sub request_cleanup {
    my ($self) = @_;
    die "plugin_not_active\n" unless $self->{active};
    $self->{cleanup_pending} = 1;
    $self->{requested_rebuild} = 0;
    $self->{requested_verify} = 0;
    $self->{state} = 'cleanup_pending';
    $self->_timer(0);
}

sub _cleanup_now {
    my ($self) = @_;
    die "worker_still_running\n" if $self->{worker};
    $self->stop;
    if (-d $self->{directory}) {
        remove_tree($self->{directory}, { error => \my $errors });
        die "plugin_cache_cleanup_failed\n" if $errors && @$errors;
    }
    $self->{prefs}->remove('reconcile_interval_seconds');
    $self->{prefs}->savenow;
    my $pref_file = File::Spec->catfile(
        Slim::Utils::Prefs::dir(), 'plugin', 'phoneticsearch.prefs');
    unlink $pref_file or die "plugin_prefs_cleanup_failed: $!\n" if -f $pref_file;
    $self->{state} = 'cleanup_complete';
    $self->{error} = undef;
    $self->{cleanup_pending} = 0;
}

sub _read_worker_status {
    my ($self) = @_;
    open my $file, '<', $self->{status_path} or die "worker status missing: $!\n";
    local $/;
    my $data = JSON::PP->new->decode(<$file>);
    close $file;
    return $data;
}

sub _check_worker {
    my ($self) = @_;
    my $process = $self->{worker} or return 0;
    return 1 if $process->alive;
    my $exit = $process->wait;
    $self->{worker} = undef;
    my $result = eval { $self->_read_worker_status };
    my $error = $@;
    if (defined($exit) && $exit == 0 && $result && $result->{state} eq 'ready') {
        my $identity = $self->_identity;
        my ($version) = $self->{gate}->selectrow_array('PRAGMA data_version');
        $self->{pending} ||= $identity ne $self->{identity} ||
            $version != $self->{launch_version};
        $self->{version} = $self->{launch_version};
        $self->{force_full} = 1 if $self->{pending} && $self->{launch_full};
        $self->{force_full} = 1 if $identity ne $self->{identity};
        $self->{state} = $self->{pending} ? 'stale' : 'ready';
        $self->{error} = undef;
        $self->{retry_at} = undef;
        $self->{last_success} = $result->{completed_at};
        $self->{last_mode} = $result->{mode};
        $self->{last_changes} = $result->{changes};
        $self->{last_verified} = $result->{verified} if defined $result->{verified};
        if (($result->{operation} || '') eq 'index' &&
                defined $result->{duration_ms}) {
            $self->{last_reconcile_duration_ms} = $result->{duration_ms};
        }
        $self->{log}->info("Indexer $result->{mode}: changes=" . ($result->{changes} || 0));
    }
    elsif ($result && $result->{state} eq 'stale') {
        $self->{state} = 'stale';
        $self->{pending} = 1;
        $self->{force_full} = 1 if $self->{launch_full};
        $self->{error} = undef;
        $self->{retry_at} = undef;
        $self->{log}->info('Indexer source changed during build; retry scheduled');
    }
    elsif ($result && ($result->{operation} || '') eq 'verify' &&
            $result->{error} =~ /\A(?:index_out_of_sync|index_invalid|index_schema_mismatch|index_vocab_mismatch|index_alias_mismatch|index_spell_mismatch|index_phrase_mismatch)/) {
        $self->{state} = 'stale';
        $self->{pending} = 1;
        $self->{force_full} = 1;
        $self->{requested_rebuild} = 1;
        $self->{error} = $result->{error};
        $self->{retry_at} = undef;
    }
    else {
        $self->{state} = 'error';
        $self->{pending} = 1;
        $self->{force_full} = 1 if $self->{launch_full};
        $self->{error} = $result ? $result->{error} : $error || "worker exit $exit";
        $self->{retry_at} = time() + 60;
        $self->{log}->error("Indexer worker failed: $self->{error}");
    }
    return 0;
}

sub _launch {
    my ($self, $full, $version, $operation) = @_;
    $operation ||= 'index';
    my $script = File::Spec->catfile($self->{root}, 'Bin', 'indexer-worker.pl');
    die "worker script missing\n" unless -f $script;
    unlink $self->{status_path} if -f $self->{status_path};
    my @include = map { "-I$_" } grep { !ref($_) && -d $_ } @INC;
    open my $worker_log, '>>', File::Spec->catfile($self->{directory}, 'worker.log')
        or die "worker log open failed: $!\n";
    # LMS ties STDERR to its log trap. Proc::Background redirects STDERR in
    # the forked child, which fails while that tied handle is inherited.
    # Mirror Slim::Music::Import::_runScanner around the spawn.
    untie *STDERR;
    my $process = eval {
        Proc::Background->new(
            { stdout => $worker_log, stderr => $worker_log },
            $^X, @include, $script, $self->{root}, $self->{source},
            $self->{index}, $self->{status_path}, $full ? 1 : 0,
            $operation);
    };
    my $spawn_error = $@;
    tie *STDERR, 'Slim::Utils::Log::Trapper';
    close $worker_log;
    die $spawn_error if $spawn_error;
    die "worker spawn failed\n" unless $process;
    $self->{worker} = $process;
    $self->{launch_version} = $version;
    $self->{launch_full} = $full;
    $self->{state} = $full ? 'building' : 'updating';
    $self->{pending} = 0;
    $self->{force_full} = 0;
    $self->{requested_rebuild} = 0 if $operation eq 'rebuild';
    $self->{requested_verify} = 0 if $operation eq 'verify';
}

sub _tick {
    my ($self) = @_;
    return unless $self->{active};
    my $next;
    my $ok = eval {
        if ($self->{cleanup_pending}) {
            if ($self->_check_worker || Slim::Music::Import->stillScanning) {
                $self->{state} = 'cleanup_pending';
                $next = 1;
            }
            else {
                $self->_cleanup_now;
            }
        }
        elsif ($self->_check_worker) {
            $next = 1;
        }
        elsif (Slim::Music::Import->stillScanning ||
                ($self->{settle_until} || 0) > time()) {
            $self->{state} = 'updating';
            $self->{force_full} = 1;
            $self->{pending} = 1;
            $next = 1;
        }
        else {
            my $identity = $self->_identity;
            unless ($self->{gate} && $identity eq $self->{identity}) {
                $self->_open_gate;
                $self->{pending} = 1;
                $self->{force_full} = 1;
            }
            my ($version) = $self->{gate}->selectrow_array('PRAGMA data_version');
            my $full = $self->{force_full} || !-f $self->{index};
            if ($self->{pending} || $version != $self->{version} || $full) {
                if ($self->{retry_at} && time() < $self->{retry_at}) {
                    $next = $self->{retry_at} - time();
                }
                else {
                    $self->_launch($full, $version,
                        $self->{requested_rebuild} ? 'rebuild' : 'index');
                    $next = 1;
                }
            }
            elsif ($self->{requested_verify}) {
                $self->_launch(0, $version, 'verify');
                $next = 1;
            }
            elsif ($self->{state} ne 'ready' && !$self->{pending}) {
                $self->{state} = 'ready';
            }
        }
        1;
    };
    unless ($ok) {
        $self->{state} = 'error';
        $self->{pending} = 1;
        $self->{error} = $@ || 'scheduler tick failed';
        $self->{retry_at} = time() + 60;
        $next = 60;
        $self->{log}->error("Indexer scheduler: $self->{error}");
    }
    $self->_timer($next);
}

sub status {
    my ($self) = @_;
    my $state = Slim::Music::Import->stillScanning ? 'updating' : $self->{state};
    return {
        state => $state,
        error => $self->{error},
        last_success => $self->{last_success},
        last_mode => $self->{last_mode},
        last_changes => $self->{last_changes},
        last_verified => $self->{last_verified},
        last_reconcile_duration_ms => $self->{last_reconcile_duration_ms},
        worker_running => $self->{worker} && $self->{worker}->alive ? 1 : 0,
    };
}

sub stop {
    my ($self) = @_;
    return unless $self->{active};
    $self->{active} = 0;
    Slim::Utils::Timers::killTimers($self, \&_tick);
    Slim::Control::Request::unsubscribe($self->{subscriber});
    Slim::Control::Request::unsubscribe($self->{targeted_subscriber});
    if ($self->{worker} && $self->{worker}->alive) {
        $self->{worker}->die;
    }
    $self->{worker} = undef;
    $self->{gate}->disconnect if $self->{gate};
    $self->{gate} = undef;
    $self->{state} = 'disabled';
}

1;
