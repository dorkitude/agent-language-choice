# Apply timestamped key-value patches

- Task ID: `kv_patch`
- Category: `stdlib-data-munging`
- Language: `php`

## Agent Prompt

```text
You are participating in a programming-language benchmark.

Target language: php
Language guidance: Use PHP. A typical run.sh can execute `php main.php`.


Implement the task below in the current working directory.

Required contract:
- Create a POSIX shell script named run.sh in the current directory.
- `./run.sh` must read from stdin and write the answer to stdout.
- Use the requested target language for the implementation.
- Use only the language standard library for this pilot task.
- Do not use network access.
- Do not edit files outside the current working directory.
- Make the solution deterministic.

Task: Apply timestamped key-value patches

Input is JSON Lines. Each line is an object with fields `ts` (integer), `op` (`set` or `delete`), `key` (string), and optionally `value` (string). Apply operations in ascending `ts`; when timestamps tie, preserve input order among tied records. `set` stores the value for the key. `delete` removes the key if present. Output the final map as lines `key=value`, sorted by key in ascending bytewise/lexicographic order. If the final map is empty, print nothing.

Finish when `./run.sh` is ready.
```

## Tests

### orders by timestamp, not input

stdin:
```text
{"ts":3,"op":"set","key":"beta","value":"late"}
{"ts":1,"op":"set","key":"alpha","value":"first"}
{"ts":2,"op":"set","key":"beta","value":"middle"}
```

expected stdout:
```text
alpha=first
beta=late
```

### delete and tied timestamp stability

stdin:
```text
{"ts":2,"op":"set","key":"b","value":"keep"}
{"ts":2,"op":"set","key":"a","value":"old"}
{"ts":2,"op":"set","key":"a","value":"new"}
{"ts":4,"op":"delete","key":"b"}
```

expected stdout:
```text
a=new
```

### empty final map

stdin:
```text
{"ts":1,"op":"set","key":"x","value":"1"}
{"ts":2,"op":"delete","key":"x"}
```

expected stdout:
```text
```
