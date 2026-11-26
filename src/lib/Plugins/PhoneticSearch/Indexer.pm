package Plugins::PhoneticSearch::Indexer;

use strict;
use warnings;
use feature 'fc';

use DBI;
use DBD::SQLite;
use Encode qw(decode FB_DEFAULT);
use Fcntl qw(:flock);
use File::Basename qw(dirname);
use File::Path qw(make_path);
use File::Spec;
use File::Temp qw(tempfile);
use Time::HiRes qw(time);
use Unicode::Normalize qw(NFKC);

use Plugins::PhoneticSearch::Loader;

use constant MAX_RECENT_TRACKS => 5000;

my %NAME_COLUMN = (
    track  => [ 'tracks', 'title' ],
    album  => [ 'albums', 'title' ],
    artist => [ 'contributors', 'name' ],
    genre  => [ 'genres', 'name' ],
);
my %PHRASE_KIND = map { $_ => 1 } qw(artist album track);

sub new {
    my ($class, %args) = @_;
    for my $required (qw(root source index)) {
        die "$required required\n" unless defined $args{$required};
    }
    return bless {
        root   => $args{root},
        source => $args{source},
        index  => $args{index},
        loader => Plugins::PhoneticSearch::Loader->new(root => $args{root}),
    }, $class;
}

sub _source {
    my ($self) = @_;
    my $dbh = DBI->connect("dbi:SQLite:dbname=$self->{source}", '', '', {
        RaiseError => 1, PrintError => 0, AutoCommit => 1,
        sqlite_open_flags => DBD::SQLite::OPEN_READONLY(),
    }) or die DBI->errstr;
    $dbh->do('PRAGMA query_only=ON');
    $dbh->do('PRAGMA busy_timeout=1000');
    return $dbh;
}

sub _index {
    my ($self, $path) = @_;
    my $dbh = DBI->connect("dbi:SQLite:dbname=$path", '', '', {
        RaiseError => 1, PrintError => 0, AutoCommit => 1,
    }) or die DBI->errstr;
    $dbh->do('PRAGMA foreign_keys=ON');
    $dbh->do('PRAGMA busy_timeout=1000');
    $self->{loader}->load_on_handle($dbh);
    return $dbh;
}

sub _index_readonly {
    my ($self) = @_;
    die "index_missing\n" unless -f $self->{index};
    my $dbh = DBI->connect("dbi:SQLite:dbname=$self->{index}", '', '', {
        RaiseError => 1, PrintError => 0, AutoCommit => 1,
        sqlite_open_flags => DBD::SQLite::OPEN_READONLY(),
    }) or die DBI->errstr;
    $dbh->do('PRAGMA query_only=ON');
    $self->{loader}->load_on_handle($dbh);
    return $dbh;
}

sub _text {
    my ($raw) = @_;
    return undef unless defined $raw;
    return utf8::is_utf8($raw) ? $raw : decode('UTF-8', $raw, FB_DEFAULT);
}

sub _normalized {
    my ($name) = @_;
    my $normalized = fc(NFKC($name));
    $normalized =~ s/^\s+|\s+$//g;
    $normalized =~ s/\s+/ /g;
    return $normalized;
}

sub _schema {
    my ($db) = @_;
    $db->do('CREATE TABLE ps_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)');
    $db->do('CREATE TABLE ps_vocab(id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, normalized TEXT NOT NULL, UNIQUE(entity_type, normalized))');
    $db->do('CREATE TABLE ps_alias(entity_type TEXT NOT NULL, alias TEXT NOT NULL, vocab_id INTEGER NOT NULL REFERENCES ps_vocab(id), PRIMARY KEY(entity_type,alias,vocab_id))');
    $db->do('CREATE TABLE ps_entity(entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, original TEXT NOT NULL, vocab_id INTEGER NOT NULL REFERENCES ps_vocab(id), PRIMARY KEY(entity_type, entity_id))');
    $db->do('CREATE INDEX ps_entity_vocab ON ps_entity(vocab_id)');
    $db->do('CREATE INDEX ps_entity_name ON ps_entity(entity_type,original)');
    for my $kind (sort keys %PHRASE_KIND) {
        $db->do("CREATE TABLE ps_${kind}_phrase(id INTEGER PRIMARY KEY, phrase TEXT NOT NULL UNIQUE)");
        $db->do("CREATE TABLE ps_${kind}_phrase_vocab(phrase_id INTEGER NOT NULL REFERENCES ps_${kind}_phrase(id), vocab_id INTEGER NOT NULL REFERENCES ps_vocab(id), PRIMARY KEY(phrase_id,vocab_id))");
        $db->do("CREATE INDEX ps_${kind}_phrase_vocab_vocab ON ps_${kind}_phrase_vocab(vocab_id)");
        $db->do("CREATE VIRTUAL TABLE ps_spell_${kind}_phrase USING spellfix1");
    }
    for my $kind (sort keys %NAME_COLUMN) {
        $db->do("CREATE VIRTUAL TABLE ps_spell_$kind USING spellfix1");
    }
    $db->do("INSERT INTO ps_meta(key,value) VALUES ('schema','5')");
}

sub _phrases {
    my ($normalized) = @_;
    my @words = $normalized =~ /[\p{L}\p{N}]+/g;
    my %phrases;
    for my $start (0 .. $#words) {
        for my $length (1 .. 4) {
            last if $start + $length > @words;
            my $phrase = join ' ', @words[$start .. $start + $length - 1];
            $phrases{$phrase} = 1 if length($phrase) >= 3 && $phrase ne $normalized;
        }
    }
    return keys %phrases;
}

sub _meta {
    my ($db, $key) = @_;
    my ($value) = $db->selectrow_array('SELECT value FROM ps_meta WHERE key=?', undef, $key);
    return $value;
}

sub _set_meta {
    my ($db, $key, $value) = @_;
    $db->do('INSERT OR REPLACE INTO ps_meta(key,value) VALUES (?,?)', undef, $key, "$value");
}

sub _alias {
    my ($kind, $normalized) = @_;
    return undef unless $kind eq 'artist';
    my $alias = $normalized;
    $alias =~ tr/!@\$013457/iasoleast/;
    return $alias ne $normalized ? $alias : undef;
}

sub _apply {
    my ($db, $kind, $id, $name) = @_;
    my ($old_vocab) = $db->selectrow_array(
        'SELECT vocab_id FROM ps_entity WHERE entity_type=? AND entity_id=?',
        undef, $kind, $id);
    $db->do('DELETE FROM ps_entity WHERE entity_type=? AND entity_id=?', undef, $kind, $id);
    if (defined $old_vocab) {
        my ($used) = $db->selectrow_array('SELECT 1 FROM ps_entity WHERE vocab_id=? LIMIT 1', undef, $old_vocab);
        unless ($used) {
            if ($PHRASE_KIND{$kind}) {
                my $phrases = $db->selectcol_arrayref(
                    "SELECT phrase_id FROM ps_${kind}_phrase_vocab WHERE vocab_id=?", undef, $old_vocab);
                $db->do("DELETE FROM ps_${kind}_phrase_vocab WHERE vocab_id=?", undef, $old_vocab);
                for my $phrase_id (@$phrases) {
                    my ($still_used) = $db->selectrow_array(
                        "SELECT 1 FROM ps_${kind}_phrase_vocab WHERE phrase_id=? LIMIT 1", undef, $phrase_id);
                    next if $still_used;
                    $db->do("DELETE FROM ps_spell_${kind}_phrase WHERE rowid=?", undef, $phrase_id);
                    $db->do("DELETE FROM ps_${kind}_phrase WHERE id=?", undef, $phrase_id);
                }
            }
            $db->do("DELETE FROM ps_spell_$kind WHERE rowid=?", undef, $old_vocab);
            $db->do('DELETE FROM ps_alias WHERE vocab_id=?', undef, $old_vocab);
            $db->do('DELETE FROM ps_vocab WHERE id=?', undef, $old_vocab);
        }
    }
    return unless defined($name) && length($name);
    my $normalized = _normalized($name);
    return unless length($normalized);
    $db->do('INSERT OR IGNORE INTO ps_vocab(entity_type,normalized) VALUES (?,?)',
            undef, $kind, $normalized);
    my ($vocab_id) = $db->selectrow_array(
        'SELECT id FROM ps_vocab WHERE entity_type=? AND normalized=?',
        undef, $kind, $normalized);
    my $alias = _alias($kind, $normalized);
    $db->do('INSERT OR IGNORE INTO ps_alias(entity_type,alias,vocab_id) VALUES (?,?,?)',
            undef, $kind, $alias, $vocab_id) if defined $alias;
    my ($present) = $db->selectrow_array("SELECT 1 FROM ps_spell_$kind WHERE rowid=?", undef, $vocab_id);
    unless ($present) {
        $db->do("INSERT INTO ps_spell_$kind(rowid,word,rank,langid) VALUES (?,?,1,0)",
                undef, $vocab_id, $normalized);
        if ($PHRASE_KIND{$kind}) {
            for my $phrase (_phrases($normalized)) {
                $db->do("INSERT OR IGNORE INTO ps_${kind}_phrase(phrase) VALUES (?)", undef, $phrase);
                my ($phrase_id) = $db->selectrow_array(
                    "SELECT id FROM ps_${kind}_phrase WHERE phrase=?", undef, $phrase);
                $db->do("INSERT OR IGNORE INTO ps_${kind}_phrase_vocab(phrase_id,vocab_id) VALUES (?,?)",
                    undef, $phrase_id, $vocab_id);
                my ($indexed) = $db->selectrow_array(
                    "SELECT 1 FROM ps_spell_${kind}_phrase WHERE rowid=?", undef, $phrase_id);
                $db->do("INSERT INTO ps_spell_${kind}_phrase(rowid,word,rank,langid) VALUES (?,?,1,0)",
                    undef, $phrase_id, $phrase) unless $indexed;
            }
        }
    }
    $db->do('INSERT INTO ps_entity(entity_type,entity_id,original,vocab_id) VALUES (?,?,?,?)',
            undef, $kind, $id, $name, $vocab_id);
}

sub _identity {
    my ($self) = @_;
    my @stat = stat($self->{source});
    die "source_missing\n" unless @stat;
    return "$stat[0]:$stat[1]";
}

sub _lock_and_cleanup {
    my ($self) = @_;
    my $parent = dirname($self->{index});
    make_path($parent);
    my $lock_path = File::Spec->catfile($parent, 'indexer.lock');
    open my $lock, '>>', $lock_path or die "index_lock_open_failed: $!\n";
    flock($lock, LOCK_EX) or die "index_lock_failed: $!\n";
    opendir my $directory, $parent or die "stage_directory_open_failed: $!\n";
    while (my $name = readdir $directory) {
        next unless $name =~ /\Aphonetic-stage-[A-Za-z0-9_]{8}(?:-(?:journal|wal|shm))?\z/;
        my $path = File::Spec->catfile($parent, $name);
        unlink $path or die "orphan_stage_cleanup_failed: $!\n"
            if -f $path || -l $path;
    }
    closedir $directory;
    return $lock;
}

sub _snapshot {
    my ($source) = @_;
    my %found;
    $source->do('BEGIN');
    eval {
        for my $kind (sort keys %NAME_COLUMN) {
            my ($table, $column) = @{ $NAME_COLUMN{$kind} };
            my $rows = $source->selectall_arrayref("SELECT id,$column FROM $table");
            for my $row (@$rows) {
                my ($id, $name) = @$row;
                $name = _text($name);
                $found{"$kind:$id"} = [ $kind, $id, $name ] if defined($name) && length($name);
            }
        }
        $source->do('COMMIT');
        1;
    } or do {
        my $error = $@;
        eval { $source->do('ROLLBACK') };
        die $error;
    };
    return \%found;
}

sub _validate {
    my ($db, $expected_count) = @_;
    my ($integrity) = $db->selectrow_array('PRAGMA integrity_check');
    my ($count) = $db->selectrow_array('SELECT count(*) FROM ps_entity');
    die "index_invalid: integrity=$integrity count=$count expected=$expected_count\n"
        unless $integrity eq 'ok' && $count == $expected_count;
}

sub _full {
    my ($self, $source, $before_version, $before_identity) = @_;
    my $found = _snapshot($source);
    my ($watermark) = $source->selectrow_array('SELECT coalesce(max(updated_time),0) FROM tracks');
    my $parent = dirname($self->{index});
    make_path($parent);
    my ($file, $stage) = tempfile('phonetic-stage-XXXXXXXX', DIR => $parent, UNLINK => 0);
    close $file;
    my $ok = eval {
        my $index = $self->_index($stage);
        _schema($index);
        $index->begin_work;
        for my $key (sort keys %$found) {
            _apply($index, @{ $found->{$key} });
        }
        _set_meta($index, 'watermark', $watermark);
        _set_meta($index, 'last_full_epoch', time());
        _set_meta($index, 'source_identity', $before_identity);
        _set_meta($index, 'state', 'ready');
        $index->commit;
        _validate($index, scalar keys %$found);
        $index->disconnect;
        my ($after_version) = $source->selectrow_array('PRAGMA data_version');
        die "source_changed_during_rebuild\n"
            if $after_version != $before_version || $self->_identity ne $before_identity;
        rename($stage, $self->{index}) or die "stage_swap_failed: $!\n";
        1;
    };
    my $error = $@;
    unlink $stage if -e $stage;
    die $error unless $ok;
    return { mode => 'full', changes => scalar(keys %$found), watermark => $watermark };
}

sub _reconcile {
    my ($self, $source, $index, $before_version, $before_identity) = @_;
    my $found = _snapshot($source);
    my ($watermark) = $source->selectrow_array('SELECT coalesce(max(updated_time),0) FROM tracks');
    my ($after_version) = $source->selectrow_array('PRAGMA data_version');
    die "source_changed_during_reconcile\n"
        if $after_version != $before_version || $self->_identity ne $before_identity;
    my $existing = $index->selectall_arrayref(
        'SELECT entity_type,entity_id,original FROM ps_entity');
    my %prior = map { ($_->[0] . ':' . $_->[1]) => _text($_->[2]) } @$existing;
    my $changes = 0;
    $index->begin_work;
    my $ok = eval {
        for my $key (keys %prior) {
            next if exists $found->{$key};
            my ($kind, $id) = split /:/, $key, 2;
            _apply($index, $kind, $id, undef);
            ++$changes;
        }
        for my $key (sort keys %$found) {
            my ($kind, $id, $name) = @{ $found->{$key} };
            next if exists($prior{$key}) && $prior{$key} eq $name;
            _apply($index, $kind, $id, $name);
            ++$changes;
        }
        _set_meta($index, 'watermark', $watermark);
        _set_meta($index, 'last_full_epoch', time());
        _set_meta($index, 'source_identity', $before_identity);
        _set_meta($index, 'state', 'ready');
        $index->commit;
        _validate($index, scalar keys %$found);
        1;
    };
    unless ($ok) {
        my $error = $@;
        eval { $index->rollback };
        die $error;
    }
    return { mode => 'full', changes => $changes, watermark => $watermark,
             rebuilt => 0 };
}

sub _recent {
    my ($source, $watermark) = @_;
    my %found;
    my @tracks;
    my %album_ids;
    my $newest = $watermark;
    my $overflow = 0;
    $source->do('BEGIN');
    my $ok = eval {
        my $rows = $source->selectall_arrayref(
            'SELECT id,title,album,updated_time FROM tracks WHERE updated_time>=?',
            undef, $watermark > 0 ? $watermark - 1 : 0);
        if (@$rows > MAX_RECENT_TRACKS) {
            $overflow = scalar(@$rows);
        }
        else {
        for my $row (@$rows) {
            my ($id, $title, $album, $updated) = @$row;
            push @tracks, $id;
            $album_ids{$album} = 1 if defined $album;
            $newest = $updated if defined($updated) && $updated > $newest;
            $title = _text($title);
            $found{"track:$id"} = [ 'track', $id, $title ] if defined($title) && length($title);
        }
        for my $album (keys %album_ids) {
            my ($title) = $source->selectrow_array('SELECT title FROM albums WHERE id=?', undef, $album);
            $title = _text($title);
            $found{"album:$album"} = [ 'album', $album, $title ] if defined($title) && length($title);
            my $artists = $source->selectall_arrayref(
                'SELECT c.id,c.name FROM contributors c JOIN contributor_album ca ON ca.contributor=c.id WHERE ca.album=?',
                undef, $album);
            for my $artist (@$artists) {
                my ($id, $name) = @$artist;
                $name = _text($name);
                $found{"artist:$id"} = [ 'artist', $id, $name ] if defined($name) && length($name);
            }
        }
        for my $track (@tracks) {
            for my $relation (
                [ 'artist', 'contributors', 'contributor_track', 'contributor', 'name' ],
                [ 'genre', 'genres', 'genre_track', 'genre', 'name' ],
            ) {
                my ($kind, $table, $join, $foreign, $column) = @$relation;
                my $items = $source->selectall_arrayref(
                    "SELECT c.id,c.$column FROM $table c JOIN $join j ON j.$foreign=c.id WHERE j.track=?",
                    undef, $track);
                for my $item (@$items) {
                    my ($id, $name) = @$item;
                    $name = _text($name);
                    $found{"$kind:$id"} = [ $kind, $id, $name ] if defined($name) && length($name);
                }
            }
        }
        }
        $source->do('COMMIT');
        1;
    };
    unless ($ok) {
        my $error = $@;
        eval { $source->do('ROLLBACK') };
        die $error;
    }
    return (undef, $overflow, $watermark) if $overflow;
    return (\%found, scalar(@tracks), $newest);
}

sub _fast {
    my ($self, $source, $index, $watermark, $before_version, $before_identity) = @_;
    my ($found, $tracks, $newest) = _recent($source, $watermark);
    return { mode => 'needs_full', recent_tracks => $tracks } unless defined $found;
    my ($after_version) = $source->selectrow_array('PRAGMA data_version');
    die "source_changed_during_delta\n"
        if $after_version != $before_version || $self->_identity ne $before_identity;
    my $changes = 0;
    $index->begin_work;
    my $ok = eval {
        for my $key (sort keys %$found) {
            my ($kind, $id, $name) = @{ $found->{$key} };
            my ($prior) = $index->selectrow_array(
                'SELECT original FROM ps_entity WHERE entity_type=? AND entity_id=?',
                undef, $kind, $id);
            $prior = _text($prior);
            next if defined($prior) && $prior eq $name;
            _apply($index, $kind, $id, $name);
            ++$changes;
        }
        _set_meta($index, 'watermark', $newest);
        _set_meta($index, 'state', 'ready');
        $index->commit;
        1;
    };
    unless ($ok) {
        my $error = $@;
        eval { $index->rollback };
        die $error;
    }
    return { mode => 'fast', changes => $changes, recent_tracks => $tracks,
             watermark => $newest };
}

sub run {
    my ($self, %args) = @_;
    my $lock = $self->_lock_and_cleanup;
    my $source = $self->_source;
    my ($version) = $source->selectrow_array('PRAGMA data_version');
    my $identity = $self->_identity;
    my $force = $args{full} ? 1 : 0;
    my $result;
    my $ok = eval {
        if ($args{rebuild} || !-f $self->{index}) {
            $result = $self->_full($source, $version, $identity);
        }
        else {
            my $index = eval { $self->_index($self->{index}) };
            my $metadata_ok = eval { defined($index) && _meta($index, 'schema') eq '5' };
            if (!$metadata_ok) {
                $index->disconnect if $index;
                $result = $self->_full($source, $version, $identity);
            }
            else {
                my $watermark = _meta($index, 'watermark') || 0;
                my $old_identity = _meta($index, 'source_identity') || '';
                if ($old_identity ne $identity) {
                    $index->disconnect;
                    $result = $self->_full($source, $version, $identity);
                }
                elsif ($force) {
                    $result = $self->_reconcile($source, $index, $version, $identity);
                    $index->disconnect;
                }
                else {
                    $result = $self->_fast($source, $index, $watermark, $version, $identity);
                    $index->disconnect;
                    $result = $self->_full($source, $version, $identity)
                        if $result->{mode} eq 'needs_full';
                }
            }
        }
        1;
    };
    my $error = $@;
    $source->disconnect;
    die $error unless $ok;
    return $result;
}

sub verify {
    my ($self) = @_;
    my $lock = $self->_lock_and_cleanup;
    my $source = $self->_source;
    my ($before_version) = $source->selectrow_array('PRAGMA data_version');
    my $identity = $self->_identity;
    my $index = $self->_index_readonly;
    my $result;
    my $ok = eval {
        die "index_schema_mismatch\n" unless _meta($index, 'schema') eq '5';
        my $found = _snapshot($source);
        _validate($index, scalar(keys %$found));
        my $rows = $index->selectall_arrayref(
            'SELECT entity_type,entity_id,original FROM ps_entity');
        for my $row (@$rows) {
            my ($kind, $id, $name) = @$row;
            my $key = "$kind:$id";
            die "index_out_of_sync: $key\n"
                unless exists($found->{$key}) &&
                    _text($name) eq $found->{$key}->[2];
        }
        my %expected_vocab;
        for my $entity (values %$found) {
            my ($kind, undef, $name) = @$entity;
            $expected_vocab{"$kind:" . _normalized($name)} = 1;
        }
        my $vocab_rows = $index->selectall_arrayref(
            'SELECT id,entity_type,normalized FROM ps_vocab');
        die "index_vocab_mismatch\n" unless @$vocab_rows == keys %expected_vocab;
        my %expected_aliases;
        my %vocab_counts;
        my %expected_phrase_links;
        for my $row (@$vocab_rows) {
            my ($id, $kind, $normalized) = @$row;
            $normalized = _text($normalized);
            die "index_vocab_mismatch\n"
                unless delete $expected_vocab{"$kind:$normalized"};
            ++$vocab_counts{$kind};
            $expected_phrase_links{$kind} += scalar(_phrases($normalized)) if $PHRASE_KIND{$kind};
            my $alias = _alias($kind, $normalized);
            $expected_aliases{"$kind:$alias:$id"} = 1 if defined $alias;
        }
        my $alias_rows = eval { $index->selectall_arrayref(
            'SELECT entity_type,alias,vocab_id FROM ps_alias') };
        die "index_alias_mismatch\n"
            if $@ || @$alias_rows != keys %expected_aliases;
        for my $row (@$alias_rows) {
            my ($kind, $alias, $id) = @$row;
            $alias = _text($alias);
            die "index_alias_mismatch\n"
                unless delete $expected_aliases{"$kind:$alias:$id"};
        }
        for my $kind (keys %NAME_COLUMN) {
            my ($spell_count) = $index->selectrow_array(
                "SELECT count(*) FROM ps_spell_$kind");
            die "index_spell_mismatch\n"
                unless $spell_count == ($vocab_counts{$kind} || 0);
        }
        for my $kind (sort keys %PHRASE_KIND) {
            my ($phrase_links) = $index->selectrow_array("SELECT count(*) FROM ps_${kind}_phrase_vocab");
            my ($phrase_count) = $index->selectrow_array("SELECT count(*) FROM ps_${kind}_phrase");
            my ($phrase_spell_count) = $index->selectrow_array("SELECT count(*) FROM ps_spell_${kind}_phrase");
            die "index_phrase_mismatch: $kind\n"
                unless $phrase_links == ($expected_phrase_links{$kind} || 0) &&
                    $phrase_count == $phrase_spell_count;
            my ($orphan_links) = $index->selectrow_array(
                "SELECT count(*) FROM ps_${kind}_phrase_vocab pv LEFT JOIN ps_${kind}_phrase p ON p.id=pv.phrase_id LEFT JOIN ps_vocab v ON v.id=pv.vocab_id WHERE p.id IS NULL OR v.id IS NULL");
            die "index_phrase_mismatch: $kind\n" if $orphan_links;
        }
        my ($after_version) = $source->selectrow_array('PRAGMA data_version');
        die "source_changed_during_verify\n"
            if $after_version != $before_version || $self->_identity ne $identity;
        $result = { mode => 'verify', changes => 0,
                    verified => scalar(keys %$found) };
        1;
    };
    my $error = $@;
    $index->disconnect;
    $source->disconnect;
    die $error unless $ok;
    return $result;
}

1;
