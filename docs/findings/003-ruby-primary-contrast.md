# Ruby As Primary Contrast

The first full D&D REST lifecycle matrix weakened the original "Go vs
TypeScript" framing. TypeScript did not behave as the clean weak case:
`typescript-vite` passed 4/5 cells, `typescript-node` passed 3/5, and
`gpt-5.5` completed every TypeScript target. The one direct Go-over-Vite result
was `kimi-k2p7-code`, where `go-stdlib` passed and `typescript-vite` failed at
`combat-state`.

Ruby is a sharper empirical foil for the design dimensions we care about:

- `ruby-rails` passed only 2/5 cells, and the two successful cells both needed
  14 shots.
- `ruby-sinatra` passed only 2/5 cells.
- `ruby-stdlib` reached 3/5, suggesting that Ruby's framework/convention layer
  matters separately from the language runtime.

That pattern better isolates explicitness and referential locality. Go and Rust
ask agents to work through visible imports, explicit data flow, compiler errors,
and relatively local semantics. Rails asks agents to rely on convention,
autoloading, dynamically resolved constants, framework callbacks, and behavior
that may not be visible in the file being edited. Sinatra sits between those
two cases: dynamic Ruby, but less implicit framework structure than Rails.

The Rust append run complicates the story in a useful way. `rust-stdlib` passed
for `opus` and `gpt-5.5` in 11 shots each, failed for `sonnet` at `phb-rules`
after 12 shots, and failed for both open-weight models at `combat-state` after
4 shots. This suggests that compiler feedback and explicitness help only when
the model can also manage the ergonomic burden of the target. Stdlib-only Rust
is explicit, but building HTTP routing and JSON handling by hand is itself a
maintenance stressor.

## Updated Framing

Primary contrast:

- `go-stdlib`: explicit, compiled, stdlib HTTP/JSON, canonical formatting.
- `rust-stdlib`: explicit and strongly compiled, but with a steeper type/borrow
  model and no stdlib HTTP abstraction. This separates compiler-signal quality
  from ergonomic simplicity.
- `ruby-stdlib`: dynamic Ruby without Rails conventions.
- `ruby-sinatra`: dynamic Ruby with a small web framework.
- `ruby-rails`: dynamic Ruby with convention-heavy, framework-mediated
  semantics.

Secondary contrast:

- TypeScript targets remain useful for ecosystem churn, dependency-surface
  size, and framework-version volatility, but they are not currently the main
  weak case.

## Completed Append Experiment

Rust was added as an append-only target rather than rerunning the whole matrix.
The resulting 15-target dataset is summarized in
[`002-full-lifecycle-matrix.md`](002-full-lifecycle-matrix.md).

Only start a new benchmark version if the evaluator or stage prompts change.
