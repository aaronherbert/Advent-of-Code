use strict; use warnings;
# Deliberately off by one in part 2: used to test the "wrong" verdict.
my ($a, $b) = (0, 0);
while (my $l = <STDIN>) { chomp $l; next if $l eq ''; $a += $l; $b += $l * $l; }
print "$a\n", $b + 1, "\n";
