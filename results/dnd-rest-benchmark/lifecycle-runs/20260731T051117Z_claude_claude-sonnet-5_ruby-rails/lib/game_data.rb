# Static D&D 5e reference tables shared by the encounter/combat/phb/dm
# endpoints. These are gameplay constants, not persisted state.

# XP value awarded per monster, keyed by challenge rating.
CR_XP = {
  '0' => 10,
  '1/8' => 25,
  '1/4' => 50,
  '1/2' => 100,
  '1' => 200,
  '2' => 450,
  '3' => 700,
  '4' => 1100,
  '5' => 1800
}.freeze

# Encounter difficulty XP thresholds per party member level (DMG table).
# Only level 3 is supported by this benchmark's scope.
LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

# Multiplies base encounter XP based on the number of monsters, per the
# DMG encounter-multiplier table.
def multiplier_for(count)
  case count
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end
