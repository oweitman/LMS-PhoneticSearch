package Plugins::PhoneticSearch::Settings;

use strict;
use warnings;

use base qw(Slim::Web::Settings);

use Slim::Utils::Prefs;
use Slim::Utils::Strings qw(string);
use Plugins::PhoneticSearch::Config;

my $prefs = preferences('plugin.phoneticsearch');

sub name {
    return Slim::Web::HTTP::CSRF->protectName('PLUGIN_PHONETICSEARCH');
}

sub page {
    return Slim::Web::HTTP::CSRF->protectURI('plugins/PhoneticSearch/settings/basic.html');
}

sub prefs { return ($prefs); }

sub handler {
    my ($class, $client, $params) = @_;
    require Plugins::PhoneticSearch::Plugin;
    my $action = $params->{'phoneticsearch_action'};
    if ($params->{'saveSettings'} && defined $action) {
        if (!Plugins::PhoneticSearch::Plugin->validActionToken(
                $params->{'phoneticsearch_action_token'})) {
            $params->{'action_notice'} = string('PLUGIN_PHONETICSEARCH_ACTION_TOKEN_INVALID');
        }
        elsif ($action eq 'cleanup' &&
                ($params->{'phoneticsearch_confirm'} || '') ne 'DELETE') {
            $params->{'action_notice'} = string('PLUGIN_PHONETICSEARCH_CLEANUP_CONFIRM_INVALID');
        }
        else {
            my $ok = eval {
                if ($action eq 'verify') {
                    Plugins::PhoneticSearch::Plugin->requestVerify;
                }
                elsif ($action eq 'rebuild') {
                    Plugins::PhoneticSearch::Plugin->requestRebuild;
                }
                elsif ($action eq 'cleanup') {
                    Plugins::PhoneticSearch::Plugin->requestCleanup;
                }
                else {
                    die "invalid_action\n";
                }
                1;
            };
            $params->{'action_notice'} = string(
                $ok ? 'PLUGIN_PHONETICSEARCH_ACTION_STARTED'
                    : 'PLUGIN_PHONETICSEARCH_ACTION_FAILED');
        }
    }
    elsif ($params->{'saveSettings'}) {
        my $value = $params->{'pref_reconcile_interval_seconds'};
        if (Plugins::PhoneticSearch::Config::valid_interval($value)) {
            $prefs->set('reconcile_interval_seconds', int($value));
            Plugins::PhoneticSearch::Plugin->intervalChanged;
        }
        else {
            $params->{'warning'} = string('PLUGIN_PHONETICSEARCH_INTERVAL_INVALID');
        }
    }
    $params->{'prefs'}->{'pref_reconcile_interval_seconds'} =
        Plugins::PhoneticSearch::Config::interval_or_default(
            $prefs->get('reconcile_interval_seconds')
        );
    my $status = Plugins::PhoneticSearch::Plugin->indexStatus;
    $params->{'index_state'} = $status->{state};
    $params->{'index_error'} = $status->{error};
    $params->{'index_last_mode'} = $status->{last_mode};
    $params->{'index_last_verified'} = $status->{last_verified};
    $params->{'index_last_reconcile_duration_seconds'} =
        sprintf('%.1f', $status->{last_reconcile_duration_ms} / 1000)
            if defined $status->{last_reconcile_duration_ms};
    $params->{'index_suggested_interval_seconds'} =
        $status->{suggested_interval_seconds};
    $params->{'phoneticsearch_action_token'} =
        Plugins::PhoneticSearch::Plugin->actionToken;
    return $class->SUPER::handler($client, $params);
}

1;
