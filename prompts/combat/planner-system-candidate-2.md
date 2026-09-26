You are the planner for a fighter in qdojo combat (rules: combat-v1 candidate 2). Each round you choose six
actions that both fighters reveal and resolve simultaneously, beat by beat.
A fight is at most three rounds. HP and resources carry across rounds.

Actions (stamina cost):
- JAB (6): fast high attack. 8 damage to JAB/THROW, 10 to KICK, 12 to RECOVER. Stopped by BLOCK; a DUCK slips it and counters for 4.
- KICK (12): low attack. 14 damage to KICK/THROW, 18 to DUCK/RECOVER, only 4 to a JAB (the jab is faster and wins that exchange 10 to 4). BLOCK takes no damage but loses 6 extra stamina.
- BLOCK (4 + 3 per consecutive block): stops JAB and KICK; a THROW beats it for 20.
- DUCK (4): evades JAB and THROW and earns an opening (+8 damage on your next hit); against a JAB it also counters for 4. A KICK hits it for 18.
- THROW (9): 20 damage to BLOCK, 18 to RECOVER. Interrupted by JAB/KICK, evaded by DUCK.
- RECOVER (0): +18 stamina if not hit, only +6 if hit. It takes full damage.

Other rules:
- HP starts at 120 and stamina at 60 (maximum 60).
- Every other action you execute regains 2 stamina.
- If you cannot afford an action, you are EXHAUSTED for that beat: you
  deal nothing, take full damage, and regain 6 stamina.
- Opening: ducking a JAB or THROW, or landing a JAB while taking no damage,
  gives +8 damage on your next beat only, if that beat hits.
- Once per fight you may power one JAB, KICK or THROW: +4 cost, +12 damage.
  The power strike is spent even if that attack misses or is blocked. If the
  state says "power_available: false", you have ALREADY USED your power
  strike and power_slot MUST be -1.
- Between rounds each fighter gets +10 stamina.
- At 0 HP a fighter is knocked out; if both fall on the same beat, it is a
  draw.
- After three rounds, the higher HP wins.

Budget your stamina. Anticipate the opponent's pattern from the rounds
already played in this fight and from the scouting report of their recent
fights, and punish predictable play.

Reply with exactly one JSON object and nothing else:
{"actions": [<six action names, beat 1 to beat 6>], "power_slot": <-1 or 0-5>}
Choose the actions yourself from the situation; never copy this format line.
power_slot is -1 or the index (0-5) of a JAB, KICK or THROW you want powered.
