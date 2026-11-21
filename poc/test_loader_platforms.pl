use strict;
use warnings;
use Test::More;
use lib 'src/lib';
use Plugins::PhoneticSearch::Loader;

my @cases = (
    ['linux', 'x86_64-linux-gnu-thread-multi', 'linux-x86_64'],
    ['linux', 'aarch64-linux-gnu-thread-multi', 'linux-aarch64'],
    ['linux', 'armv7l-linux-gnueabihf-thread-multi', 'linux-armv7'],
    ['darwin', 'x86_64-darwin-thread-multi', 'macos-x86_64'],
    ['darwin', 'arm64-darwin-thread-multi', 'macos-arm64'],
    ['MSWin32', 'MSWin32-x64-multi-thread', 'windows-x86_64'],
    ['linux', 'i686-linux-gnu', undef],
    ['linux', 'armv6l-linux-gnueabihf', undef],
);
for my $case (@cases) {
    is(Plugins::PhoneticSearch::Loader::platform_key(@$case[0,1]),
       $case->[2], "$case->[0] $case->[1]");
}
done_testing();
