package Plugins::PhoneticSearch::Search;

use strict;
use warnings;

use DBI;
use DBD::SQLite;

use Plugins::PhoneticSearch::Indexer;
use Plugins::PhoneticSearch::Loader;

my %SOURCE = (
    artist => [ 'contributors', 'name' ],
    album  => [ 'albums', 'title' ],
    track  => [ 'tracks', 'title' ],
    genre  => [ 'genres', 'name' ],
);
my @ORDER = qw(artist album track genre);

sub new {
    my ($class, %args) = @_;
    return bless {
        root => $args{root}, source => $args{source}, index => $args{index},
        loader => Plugins::PhoneticSearch::Loader->new(root => $args{root}),
    }, $class;
}

sub _open {
    my ($path) = @_;
    my $dbh = DBI->connect("dbi:SQLite:dbname=$path", '', '', {
        RaiseError => 1, PrintError => 0, AutoCommit => 1,
        sqlite_open_flags => DBD::SQLite::OPEN_READONLY(),
    }) or die DBI->errstr;
    return $dbh;
}

sub search {
    my ($self, %args) = @_;
    my $query = $args{query};
    die "invalid_parameter: query required\n"
        unless defined($query) && !ref($query) && length($query) && length($query) <= 256;
    my $offset = defined($args{offset}) ? $args{offset} : 0;
    my $limit = defined($args{limit}) ? $args{limit} : 20;
    die "invalid_parameter: offset/limit\n"
        unless $offset =~ /\A\d+\z/ && $offset <= 1000 &&
               $limit =~ /\A\d+\z/ && $limit >= 1 && $limit <= 100;
    my @types = $args{types} ? @{ $args{types} } : @ORDER;
    die "invalid_parameter: type\n"
        unless @types && !(grep { !exists $SOURCE{$_} } @types);
    die "index_not_ready\n" unless -f $self->{index};
    my $normalized = Plugins::PhoneticSearch::Indexer::_normalized($query);
    my $index = _open($self->{index});
    my $source = _open($self->{source});
    my %candidate;
    my $ok = eval {
        $self->{loader}->load_on_handle($index);
        for my $kind (@types) {
            my $exact = $index->selectall_arrayref(
                'SELECT entity_id,original FROM ps_entity WHERE entity_type=? AND original=? LIMIT 200',
                undef, $kind, $query);
            _add(\%candidate, $kind, $exact, 0, 0, 0);
            my $normalized_rows = $index->selectall_arrayref(
                'SELECT e.entity_id,e.original FROM ps_entity e JOIN ps_vocab v ON v.id=e.vocab_id WHERE e.entity_type=? AND v.normalized=? LIMIT 200',
                undef, $kind, $normalized);
            _add(\%candidate, $kind, $normalized_rows, 1, 0, 0);
            if ($kind eq 'artist') {
                my $aliases = $index->selectall_arrayref(
                    'SELECT e.entity_id,e.original FROM ps_alias a JOIN ps_entity e ON e.vocab_id=a.vocab_id WHERE a.entity_type=? AND a.alias=? LIMIT 200',
                    undef, $kind, $normalized);
                _add(\%candidate, $kind, $aliases, 2, 0, 0);
            }
            my $prefix = $index->selectall_arrayref(
                q{SELECT e.entity_id,e.original FROM ps_vocab v JOIN ps_entity e ON e.vocab_id=v.id WHERE v.entity_type=? AND v.normalized>=? AND v.normalized<? LIMIT 200},
                undef, $kind, $normalized, _prefix_high($normalized));
            _add(\%candidate, $kind, $prefix, 3, 0, 0);
            if (length($normalized) >= 3) {
                my @queries = ($normalized);
                if ($kind eq 'artist') {
                    push @queries, "the $normalized" if $normalized !~ /\s/;
                    if ($normalized =~ /\bdsch/) {
                        my $german_asr = $normalized;
                        $german_asr =~ s/\bdsch/j/g;
                        push @queries, $german_asr;
                    }
                }
                for my $fuzzy_query (@queries) {
                    my $words = $index->selectall_arrayref(
                        "SELECT rowid,distance,score FROM ps_spell_$kind WHERE word MATCH ? LIMIT 40",
                        undef, $fuzzy_query);
                    for my $word (@$words) {
                        my ($vocab_id, $distance, $spell_score) = @$word;
                        my $entities = $index->selectall_arrayref(
                            'SELECT entity_id,original FROM ps_entity WHERE entity_type=? AND vocab_id=? LIMIT 200',
                            undef, $kind, $vocab_id);
                        _add(\%candidate, $kind, $entities, 4, $distance, $spell_score);
                    }
                }
            }
        }
        1;
    };
    my $error = $@;
    unless ($ok) {
        $index->disconnect;
        $source->disconnect;
        die $error;
    }
    my @verified;
    for my $hit (values %candidate) {
        my ($table, $column) = @{ $SOURCE{$hit->{type}} };
        my ($current) = $source->selectrow_array(
            "SELECT $column FROM $table WHERE id=?", undef, $hit->{id});
        $current = Plugins::PhoneticSearch::Indexer::_text($current);
        next unless defined $current && $current eq $hit->{name};
        push @verified, $hit;
    }
    $index->disconnect;
    $source->disconnect;
    my %order = map { $ORDER[$_] => $_ } 0..$#ORDER;
    @verified = sort {
        $a->{class} <=> $b->{class} ||
        $a->{distance} <=> $b->{distance} ||
        $a->{spellfix_score} <=> $b->{spellfix_score} ||
        $order{$a->{type}} <=> $order{$b->{type}} ||
        $a->{id} <=> $b->{id}
    } @verified;
    my $total = scalar @verified;
    my @page = $offset < $total ? @verified[$offset ..
        ($offset + $limit - 1 < $total - 1 ? $offset + $limit - 1 : $total - 1)] : ();
    for my $hit (@page) {
        $hit->{score} = $hit->{class} == 0 ? 1.0 :
                        $hit->{class} == 1 ? 0.95 :
                        $hit->{class} == 2 ? 0.9 :
                        $hit->{class} == 3 ? 0.8 :
                        0.7 / (1 + $hit->{distance} / 100);
        $hit->{match_type} = (qw(exact normalized alias prefix phonetic))[$hit->{class}];
        delete $hit->{class};
    }
    return { count => scalar(@page), offset => int($offset), limit => int($limit),
             total_is_exact => 0, index_state => 'ready', results_loop => \@page };
}

sub _prefix_high {
    my ($value) = @_;
    my @characters = split //, $value;
    while (@characters) {
        my $code = ord(pop @characters);
        return join('', @characters) . chr($code + 1) if $code < 0x10ffff;
    }
    die "invalid_parameter: unsupported prefix\n";
}

sub _add {
    my ($candidates, $kind, $rows, $class, $distance, $score) = @_;
    for my $row (@$rows) {
        my ($id, $name) = @$row;
        $name = Plugins::PhoneticSearch::Indexer::_text($name);
        my $key = "$kind:$id";
        next if exists($candidates->{$key}) &&
            ($candidates->{$key}->{class} < $class ||
             ($candidates->{$key}->{class} == $class &&
              $candidates->{$key}->{distance} <= ($distance || 0)));
        $candidates->{$key} = {
            type => $kind, id => int($id), name => $name, class => $class,
            distance => int($distance || 0), spellfix_score => int($score || 0),
        };
    }
}

1;
