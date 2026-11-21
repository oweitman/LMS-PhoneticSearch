use strict;
use warnings;
use Test::More;
use lib 'src/lib';
use Plugins::PhoneticSearch::Config;

is(Plugins::PhoneticSearch::Config::interval_or_default(undef), 5, 'unset defaults to 5');
is(Plugins::PhoneticSearch::Config::interval_or_default('bad'), 5, 'invalid stored value defaults to 5');
ok(Plugins::PhoneticSearch::Config::valid_interval('5'), 'minimum accepted');
ok(Plugins::PhoneticSearch::Config::valid_interval('3600'), 'maximum accepted');
ok(!Plugins::PhoneticSearch::Config::valid_interval('4'), 'below minimum rejected');
ok(!Plugins::PhoneticSearch::Config::valid_interval('3601'), 'above maximum rejected');
ok(!Plugins::PhoneticSearch::Config::valid_interval('5.5'), 'fraction rejected');
ok(!Plugins::PhoneticSearch::Config::valid_interval('5x'), 'trailing text rejected');
ok(!Plugins::PhoneticSearch::Config::valid_interval('999999999999999999999'), 'oversized input rejected');
is(Plugins::PhoneticSearch::Config::interval_or_default('10'), 10, 'configured value used');
is(Plugins::PhoneticSearch::Config::suggested_interval(4000, 5), undef, 'no suggestion for fast cycle');
is(Plugins::PhoneticSearch::Config::suggested_interval(5000, 5), undef, 'equal duration needs no suggestion');
is(Plugins::PhoneticSearch::Config::suggested_interval(6000, 5), 8, 'long cycle suggests 25 percent headroom');
is(Plugins::PhoneticSearch::Config::suggested_interval(4000000, 5), 3600, 'suggestion respects configured maximum');

done_testing;
