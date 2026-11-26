package Plugins::PhoneticSearch::API;

use strict;
use warnings;

use Slim::Control::Request;
use Plugins::PhoneticSearch::Search;

my $configuration;

sub register {
    my ($class, %args) = @_;
    return if $configuration;
    $configuration = \%args;
    Slim::Control::Request::addDispatch(
        ['phoneticsearch', 'status', '?'], [0, 1, 0, \&status_query]);
    Slim::Control::Request::addDispatch(
        ['phoneticsearch', '_index', '_quantity'], [0, 1, 1, \&search_query]);
}

sub status_query {
    my ($request) = @_;
    my $status = $configuration->{status}->();
    for my $key (qw(state error last_success last_mode last_changes last_verified last_reconcile_duration_ms worker_running)) {
        $request->addResult($key, $status->{$key}) if defined $status->{$key};
    }
    $request->setStatusDone;
}

sub search_query {
    my ($request) = @_;
    my $status = $configuration->{status}->();
    if ($status->{state} ne 'ready') {
        $request->addResult('index_state', $status->{state});
        $request->addResult('error', 'index_not_ready');
        $request->setStatusDone;
        return;
    }
    my $types = $request->getParam('type');
    my @types = defined($types) && length($types) ? split(/,/, $types) : ();
    if (defined($request->getParam('mode')) && $request->getParam('mode') ne 'auto'
            || defined($request->getParam('maxdistance'))) {
        $request->addResult('error', 'invalid_parameter');
        $request->setStatusDone;
        return;
    }
    my $result = eval {
        Plugins::PhoneticSearch::Search->new(
            root => $configuration->{root},
            source => $configuration->{source},
            index => $configuration->{index},
        )->search(
            query => $request->getParam('query'),
            types => \@types,
            offset => $request->getParam('_index'),
            limit => $request->getParam('_quantity'),
        );
    };
    unless ($result) {
        my $error = $@ || 'internal_error';
        my $public = $error =~ /\A(invalid_parameter|index_not_ready|extension_unavailable)/
            ? $1 : 'internal_error';
        $request->addResult('error', $public);
        $request->addResult('index_state', $status->{state});
        $request->setStatusDone;
        $configuration->{log}->error("Phonetic search failed: $error")
            if $public eq 'internal_error';
        return;
    }
    for my $key (qw(count offset limit total_is_exact index_state)) {
        $request->addResult($key, $result->{$key});
    }
    my $i = 0;
    for my $hit (@{ $result->{results_loop} }) {
        $request->setResultLoopHash('results_loop', $i++, $hit);
    }
    $request->setStatusDone;
}

1;
