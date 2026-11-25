<?php
$n = array_map('intval', preg_split('/\s+/', trim(stream_get_contents(STDIN))));
echo array_sum($n), PHP_EOL;
echo array_sum(array_map(fn($x) => $x * $x, $n)), PHP_EOL;
