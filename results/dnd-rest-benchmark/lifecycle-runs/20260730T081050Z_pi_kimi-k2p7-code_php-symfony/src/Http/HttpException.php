<?php

declare(strict_types=1);

namespace App\Http;

use RuntimeException;

/**
 * A domain exception that carries an HTTP status code.
 *
 * Throwing this from a controller lets index.php translate it into a uniform
 * JSON error response without each controller repeating the same early-return
 * boilerplate.
 */
final class HttpException extends RuntimeException
{
    public function __construct(string $message, private readonly int $status = 400)
    {
        parent::__construct($message);
    }

    public function getStatus(): int
    {
        return $this->status;
    }
}
