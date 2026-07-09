<?php
// Apply timestamped key-value patches.
// Input: JSON Lines, each with ts (int), op (set|delete), key (string),
//        and optionally value (string).
// Apply in ascending ts, ties broken by input order.
// Output final map as "key=value" lines, sorted by key bytewise.
// Empty map => no output.

$records = [];
$idx = 0;
while (($line = fgets(STDIN)) !== false) {
    $line = rtrim($line, "\r\n");
    if ($line === '') {
        continue;
    }
    $obj = json_decode($line, true);
    if (!is_array($obj)) {
        // Skip malformed lines deterministically.
        continue;
    }
    $obj['__idx'] = $idx++;
    $records[] = $obj;
}

// Stable sort by ts ascending; tie-break by original input index.
usort($records, function ($a, $b) {
    if ($a['ts'] < $b['ts']) {
        return -1;
    }
    if ($a['ts'] > $b['ts']) {
        return 1;
    }
    return $a['__idx'] <=> $b['__idx'];
});

$map = [];
foreach ($records as $rec) {
    $op = $rec['op'];
    $key = $rec['key'];
    if ($op === 'set') {
        $map[$key] = array_key_exists('value', $rec) ? (string)$rec['value'] : '';
    } elseif ($op === 'delete') {
        unset($map[$key]);
    }
    // Unknown ops are ignored.
}

// Sort keys bytewise (strcmp-style byte comparison).
ksort($map, SORT_STRING);

foreach ($map as $key => $value) {
    echo $key . '=' . $value . "\n";
}
