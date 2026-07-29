# Maintenance Stage 22: Exploration Turn Queue

The turn endpoint additionally returns a deterministic `queue`. For a
two-player campaign started in join order A then B, it is
`["player-a","dm","player-b","dm"]`; the first actor is player A and phase
is `player`. There is exactly one current actor.
