# Maintenance Stage 47: Character Creation Choices

Preserve all earlier behavior. Validate race/class/background choices and
return derived defaults.

`POST /v1/play/campaigns/{id}/characters/{char_id}/build` accepts
`{"race":"elf","class":"rogue","background":"criminal","abilities":{"str":8,"dex":16,"con":12,"int":13,"wis":10,"cha":14}}`.
Only the character's owner may call it. Return 200 with validated choices and
derived defaults:

```json
{
  "character_id": "play-char-a",
  "race": "elf",
  "class": "rogue",
  "background": "criminal",
  "level": 1,
  "hp_max": 9,
  "proficiency_bonus": 2
}
```

Invalid race/class/background or ability scores outside 1-30 return 400.
Rogues use `hp_max = 8 + con_modifier` at level 1.
