/* Display strings for every combat action, for the move deck, the rules page,
 * replays and the sprite track. Rules live in the ruleset (ruleset.js) and the
 * engine (engine.js); nothing here changes an outcome.
 *
 * Keyed by the engine's action name. id is the action id in plans, traces and
 * the observation (EXHAUSTED is internal and never on the deck). key is the
 * practice-deck key. LAST_STAND and FEINT exist only in combat-v1 candidate 3:
 * a page shows an action on the deck only if the loaded ruleset's
 * submitted_action_ids contains its id.
 *
 * Numbers in the strings are candidate 3's; a page that shows numbers should
 * read them from the ruleset instead (costs, damage, last_stand, feint).
 *
 * <script src="combat/moves.js"> defines window.QDojoMoves; in Node,
 * require() returns the same object.
 */
'use strict';
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module && module.exports) module.exports = api;
  if (root) root.QDojoMoves = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const deepFreeze = o => { Object.values(o).forEach(v => { if (v && typeof v === 'object') deepFreeze(v); }); return Object.freeze(o); };
  return deepFreeze({
    JAB: {
      id: 0, key: '1', label: 'JAB',
      deck: 'Fast high strike. Beats a kick and a throw; blocked, and a duck slips it.',
      purpose: 'Efficient high attack; out-trades a kick; fails against block and duck',
      flavour: 'The first move on the first tape. Every bot in the yard can throw it in its sleep, and most do.',
    },
    KICK: {
      id: 1, key: '2', label: 'KICK',
      deck: 'Heavy low strike. Crushes a duck or a recovery; a jab beats it.',
      purpose: 'Low attack; punishes duck and recovery, drains a block; costly',
      flavour: 'Forklift hydraulics were not built for this. They do it anyway.',
    },
    BLOCK: {
      id: 2, key: '3', label: 'BLOCK',
      deck: 'Stops jab, kick and last stand. A throw breaks it; each block in a row costs more.',
      purpose: 'Stops strikes; loses to throw; repeated use costs more',
      flavour: 'Officer Bolt\'s riot shield, welded on backwards. It still works.',
    },
    DUCK: {
      id: 3, key: '4', label: 'DUCK',
      deck: 'Slips a jab (and counters it) or a throw, and earns an opening. A kick finds you.',
      purpose: 'Evades jab and throw and earns an opening; counters a jab; vulnerable to kick',
      flavour: 'The karaoke machine taught this one by accident: something always flies over the stage.',
    },
    THROW: {
      id: 4, key: '5', label: 'THROW',
      deck: 'Grab. Breaks a block for 20; any strike interrupts it, a duck evades it.',
      purpose: 'Beats block and recovery; interrupted by strikes, evaded by duck',
      flavour: 'Learned from the scrapyard crane. Nobody taught the crane to let go.',
    },
    RECOVER: {
      id: 5, key: '6', label: 'RECOVER',
      deck: 'Refill stamina (+18, only +6 if hit). Wide open while you do it.',
      purpose: 'Restores stamina; exposed, and recovers less if hit',
      flavour: 'Plug in, cool down, hope nobody notices.',
    },
    EXHAUSTED: {
      id: 6, key: null, label: 'EXHAUSTED',
      deck: null,
      purpose: 'Internal: an unaffordable move. Pays nothing, exposed',
      flavour: 'The fans spin, the lights dim, the robot just stands there.',
    },
    LAST_STAND: {
      id: 7, key: '7', label: 'STAND',
      deck: 'Strike +1 per HP you trail (max +16). Blocked; a kick out-trades it.',
      purpose: 'Comeback strike: +1 damage per HP behind, up to +16; hits a duck; blocked; loses to a kick unless far behind',
      flavour: 'When the old servos know the fight is going away from them, they stop saving anything: coolant vented, reactor in the red, everything thrown at once. You cannot make a last stand while you are winning.',
      clip: 'stand',
    },
    FEINT: {
      id: 8, key: '8', label: 'FEINT',
      deck: 'Fake it. A blocker or ducker is baited; any strike catches you.',
      purpose: 'Cheap bluff against defence; loses to any attack',
      flavour: 'A move from the tape nobody could follow: the robot starts a haymaker and stops halfway. Half the yard flinches every time.',
      clip: 'feint',
    },
  });
});
