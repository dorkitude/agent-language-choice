# Claude authentication status reconciliation

Source decision: “run all of them, then when done build me a single-page HTML/Chart.js dashboard page (Tokyo Night style) with the data embedded in JSON inline into the page.” Operational tracking: https://github.com/dorkitude/agent-language-choice/issues/6.

At 2026-09-10T05:24:14.153236+00:00, reconciled 24 existing Claude lifecycle records in the shared experiment SQLite database from `fail` to `blocked` using the current harness classifier. The older, still-running queue had recorded expired OAuth authentication responses as model failures. These are unresolved infrastructure failures and do not count as terminal benchmark outcomes.

Each update held the harness's exclusive lifecycle cell lock. The existing `upsert_run` implementation reclassified the shot ledger and run status from retained evidence. SHA-256 checks confirmed that every original lifecycle result JSON remained unchanged. No agent was restarted, no implementation was edited, and no benchmark attempt was added. The live database will be archived with the completed results; the original run artifacts retain the historical evidence.

Reconciled runs and unchanged raw result hashes:

| Run | SHA-256 |
| --- | --- |
| 20260731T044347Z_claude_claude-sonnet-5_typescript-nextjs | `33876c262f400e3f37c3ad826875f81b8f967d0f46613cf82bfb25bffa5a7b6e` |
| 20260731T051117Z_claude_claude-sonnet-5_ruby-rails | `93a689f55bf29153beef88862c658353f693142bebfcc879fbb92466622a4823` |
| 20260731T051216Z_claude_claude-sonnet-5_php-stdlib | `c2725f065e4eb350a2f20f9ad8efe989106ce4ebe70e9db85cb386da4524e14f` |
| 20260731T052954Z_claude_claude-sonnet-5_python-flask | `12ac54475e29baf12dd8b84a33fc7d4e99830ad7d21b4a2e682a7827ce41e951` |
| 20260731T060905Z_claude_claude-sonnet-5_python-django | `0b304b2e669146249d42a8ee80a4995cdc4e9d90dd871df5b6f4bf280a366a08` |
| 20260804T081331Z_claude_claude-sonnet-5_php-slim | `e5430780c6dcd6e581eea2381a42248a7065ef87a23b0305e0b34ea04d576fd0` |
| 20260804T081334Z_claude_claude-sonnet-5_php-symfony | `f91a9c29f88098cffe26faea1f7138f6244ff40fb18e9b17c692dc9187468387` |
| 20260804T081336Z_claude_claude-opus-5_go-stdlib | `883beb8c9c73398eba9da6994afc3757ecb4bba7563c089aba30224710ec7475` |
| 20260804T081339Z_claude_claude-opus-5_go-open | `4120a03949f4306f24c90eb9d45d7ddcb14fed79d2e6b69989724538e0bfcf25` |
| 20260804T081339Z_claude_claude-opus-5_typescript-nextjs | `8bd2e84cbe5d54ac398de33f7b27ab0952ed86fbb0c192a754dc088bd83440ce` |
| 20260804T081340Z_claude_claude-opus-5_ruby-rails | `4ed4a212afbec9cbcf73c566d7767e4634731fc907a4e38e003490769a12dca6` |
| 20260804T081341Z_claude_claude-opus-5_php-stdlib | `65d32e1dc05afa2ff5bfe9da7837bc80dd6073b069ad60a246c3a0ab275fc34b` |
| 20260804T081343Z_claude_claude-opus-5_python-flask | `e22231808ec4322938b1db1dc5ee34a7df02f43dc99c62bf11c4686e4acc20b1` |
| 20260804T081344Z_claude_claude-opus-5_python-django | `6560c0267ce461079d3fe606aa6e3118946fc1f257af28cab66e6367081b6275` |
| 20260804T081348Z_claude_claude-opus-5_rust-stdlib | `47f21f0cd38036fe703a181bb5f8f1353a287ee6998841ceb6a5c8994c83a54b` |
| 20260804T081349Z_claude_claude-opus-5_typescript-node | `38337b85609180ed2cf5e8f27ad678a2e4c93b166d0e739f5d7609dd3d524e58` |
| 20260804T081352Z_claude_claude-opus-5_javascript-node | `13e2ff85489ece97d5be3c08d79cec84c34f0446932b7bb08e894b1e285efdcc` |
| 20260804T081354Z_claude_claude-opus-5_typescript-vite | `5cfb1f4e06ae3e6bf8f2d3dc6589f783e844ab2c48bfcaecc8538fe52c7c8541` |
| 20260804T081355Z_claude_claude-opus-5_python-stdlib | `16d81ca4b4c688c058e20bd8c9342232b36177ebe1e4144aea05d6be554adbe9` |
| 20260804T081357Z_claude_claude-opus-5_java-stdlib | `713044a6e19cf16e39ad9f275b82795e996b56cf953faf615716621f9e2b7baf` |
| 20260804T081357Z_claude_claude-opus-5_ruby-stdlib | `597e1a44a7003966d551175dec3c7c370f2f3997ff5329232dfdf7462139d64e` |
| 20260804T081401Z_claude_claude-opus-5_ruby-sinatra | `328194af6ed286d5995a92b9f994245206038e550a712562b8c1dcef613e85d5` |
| 20260804T081403Z_claude_claude-opus-5_php-slim | `bae562feca19846163f5185afbadc32854a78211e7bc00efc778d2cafd10fb5c` |
| 20260804T081403Z_claude_claude-opus-5_php-symfony | `c48a046e189704b9679821c3fefc94fa4912ff2e549533994e3c029e4328dce2` |
