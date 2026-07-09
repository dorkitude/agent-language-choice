# Debug an existing account ledger CLI

- Task ID: `ledger_debug`
- Category: `preexisting-repo-debugging`
- Language: `java`

## Agent Prompt

```text
You are participating in a programming-language benchmark.

        Target language: java
        Language guidance: Use Java. A typical run.sh can compile with `javac` then run `java Main`.

A starter repository has already been placed in the current directory. Modify or replace it as needed, but keep the final `./run.sh` contract.


        Implement the task below in the current working directory.

        Required contract:
        - Create a POSIX shell script named run.sh in the current directory.
        - `./run.sh` must read from stdin and write the answer to stdout.
        - Use the requested target language for the implementation.
        - Use only the language standard library for this pilot task.
        - Do not use network access.
        - Do not edit files outside the current working directory.
        - Make the solution deterministic.

        Task: Debug an existing account ledger CLI

        The current repository contains a buggy CLI. It reads CSV lines from stdin with fields `account,delta_cents`. `account` is a non-empty string without commas. `delta_cents` is a signed integer. Ignore malformed lines and lines with non-integer deltas. The program must sum all deltas per account, then output one line per account as `account,balance_cents`, sorted lexicographically by account. Accounts whose final balance is zero must still be printed. Fix the existing implementation while preserving the `./run.sh` contract.

        Finish when `./run.sh` is ready.
```

## Tests

### repeated accounts accumulate

stdin:
```text
cash,100
revenue,-100
cash,25
```

expected stdout:
```text
cash,125
revenue,-100
```

### negative and zero final balances

stdin:
```text
a,5
a,-5
b,-2
b,-3
```

expected stdout:
```text
a,0
b,-5
```

### malformed rows ignored

stdin:
```text
z,10
bad
z,nope
y,-4
```

expected stdout:
```text
y,-4
z,10
```
