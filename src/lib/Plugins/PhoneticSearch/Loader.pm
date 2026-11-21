package Plugins::PhoneticSearch::Loader;

use strict;
use warnings;

use Config ();
use Digest::SHA ();
use File::Spec;
use JSON::PP;
use POSIX ();

sub new {
    my ($class, %args) = @_;
    die "plugin root required\n" unless defined $args{root};
    return bless { root => File::Spec->rel2abs($args{root}) }, $class;
}

my %binary_files = (
    'linux-x86_64' => 'Bin/linux-x86_64/spellfix.so',
    'linux-aarch64' => 'Bin/linux-aarch64/spellfix.so',
    'linux-armv7' => 'Bin/linux-armv7/spellfix.so',
    'macos-x86_64' => 'Bin/macos-x86_64/spellfix.dylib',
    'macos-arm64' => 'Bin/macos-arm64/spellfix.dylib',
    'windows-x86_64' => 'Bin/windows-x86_64/spellfix.dll',
);

sub platform_key {
    my ($os, $arch) = @_;
    return 'linux-x86_64' if $os eq 'linux' && $arch =~ /\Ax86_64-linux/;
    return 'linux-aarch64' if $os eq 'linux' && $arch =~ /\A(?:aarch64|arm64)-linux/;
    return 'linux-armv7' if $os eq 'linux' && $arch =~ /\Aarmv7[a-z]*-linux/;
    return 'macos-x86_64' if $os eq 'darwin' && $arch =~ /\Ax86_64-darwin/;
    return 'macos-arm64' if $os eq 'darwin' && $arch =~ /\A(?:arm64|aarch64)-darwin/;
    return 'windows-x86_64' if $os eq 'MSWin32' && $arch =~ /(?:x86_64|x64|amd64)/i;
    return undef;
}

sub binary_path {
    my ($self) = @_;
    my $arch = $Config::Config{archname};
    my $platform = platform_key($^O, $arch);
    if (!$platform && $^O eq 'darwin') {
        my @uname = POSIX::uname();
        $platform = platform_key($^O, "$uname[4]-darwin") if @uname;
    }
    die "unsupported_platform: $^O $Config::Config{archname}\n"
        unless $platform;
    my $manifest_path = File::Spec->catfile($self->{root}, 'Bin', 'manifest.json');
    open my $manifest_file, '<', $manifest_path
        or die "extension_unavailable: cannot open manifest: $!\n";
    local $/;
    my $manifest = eval { JSON::PP->new->decode(<$manifest_file>) };
    close $manifest_file;
    die "extension_unavailable: invalid manifest: $@\n" if $@;
    my $target = $manifest->{$platform};
    die "extension_unavailable: missing $platform target\n"
        unless ref($target) eq 'HASH';
    my $relative = $target->{file};
    die "extension_unavailable: unsafe binary path\n"
        unless defined($relative) && $relative eq $binary_files{$platform};
    my $binary = File::Spec->catfile($self->{root}, split m{/}, $relative);
    open my $binary_file, '<', $binary
        or die "extension_unavailable: cannot open binary: $!\n";
    binmode $binary_file;
    my $digest = Digest::SHA->new(256)->addfile($binary_file)->hexdigest;
    close $binary_file;
    die "extension_unavailable: binary checksum mismatch\n"
        unless defined($target->{sha256}) && $digest eq lc($target->{sha256});
    return $binary;
}

sub load_on_handle {
    my ($self, $dbh) = @_;
    my $binary = $self->binary_path;
    my $ok = eval {
        $dbh->sqlite_enable_load_extension(1);
        $dbh->do('SELECT load_extension(?, ?)', undef,
                 $binary, 'sqlite3_spellfix_init');
        1;
    };
    my $error = $@;
    my $disabled = eval { $dbh->sqlite_enable_load_extension(0); 1 };
    die "extension_unavailable: could not disable SQLite loading: $@\n"
        unless $disabled;
    die "extension_unavailable: $error" unless $ok;
    return 1;
}

1;
