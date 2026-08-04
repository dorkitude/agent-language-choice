<?php
declare(strict_types=1);

// Fallback: no route matched.
// ---------------------------------------------------------------------------

send_json(['error' => 'not found'], 404);
