<?php
$balances = [];
$handle = fopen('php://stdin', 'r');
while (($line = fgets($handle)) !== false) {
    $parts = explode(',', rtrim($line, "\r\n"));
    if (count($parts) !== 2 || $parts[0] === '') {
        continue;
    }
    if (!preg_match('/^-?\d+$/', $parts[1])) {
        continue;
    }
    $balances[$parts[0]] = ($balances[$parts[0]] ?? 0) + intval($parts[1]);
}
ksort($balances, SORT_STRING);
foreach ($balances as $key => $value) {
    echo $key . ',' . $value . PHP_EOL;
}
?>
