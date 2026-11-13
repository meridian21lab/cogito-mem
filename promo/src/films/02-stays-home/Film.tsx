// Film 02: "Your memory stays home." Every beat hangs on a word of the narration via tl.word(); beats()
// computes them once for the pictures and the sound.
//
//  A  hook     the binoculars open on the great migration: a V of winged chat bubbles; pull back to the cloud
//              waiting for them, mouth open; species card
//  B  chats    the cloud gulps them one by one; species card
//  C  asks     the cloud holds up "Sign up!" and "API key?", then reads the last chat through a magnifier
//  D  home     whip down to the tree: one acorn grows wings and tries to leave; Cogi leaps, catches it, tosses it back
//  E  folder   push into the hollow: the folder plate, the dated acorns, the "your computer" sign
//  F  nos      the cloud swoops in with its asks; Cogi, back turned, swats each one away with its tail (punch-ins)
//  G  private  the developer types a <private> note; it flies at Cogi, who covers its eyes; it fizzles
//  H  sulk     the cloud turns grey and rains on Cogi; Cogi opens a leaf umbrella
//  I  nothing  the cloud huffs off and the sun comes out; the same acorn tries again; Cogi's tail bats it home
//  J  tagline  Cogi's tail wipes to the shared title card and end card
import {useMemo} from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {Cloud, CloudArm, type CloudPose} from '../../cast/Cloud';
import {Cogi, idleCogi, type CogiPose} from '../../cast/Cogi';
import {Goldie, idleGoldie} from '../../cast/Goldie';
import {Camera, Layer, handheld, shotTrack, type Shot} from '../../kit/Camera';
import {Captions} from '../../kit/Captions';
import {Finish} from '../../kit/Finish';
import {FORMATS, FPS, type FormatId} from '../../kit/formats';
import {EASE, blinkAt, ease, hop, keys, springAt, wobble} from '../../kit/motion';
import {Binoculars, LowerThird, TailWipe} from '../../kit/Overlays';
import {Music, Sfx, SoundProvider, Voice, type Mix} from '../../kit/Sound';
import {theme} from '../../kit/theme';
import {buildTimeline, type Timeline} from '../../kit/timeline';
import {FarTrees, Ground, MidTrees, Sky} from '../../world/Backdrop';
import {Bowl} from '../../world/Bowl';
import {Desk, Hands, Laptop, Mug} from '../../world/Desk';
import {TitleCard} from '../../world/Ending';
import {Leaves, Puff, SparkleBurst} from '../../world/Particles';
import {ImpactStar, LeafUmbrella, Magnifier, Placard, Rain, WingedAcorn, WingedBubble} from '../../world/Props';
import {Tree, shelfSlot} from '../../world/Tree';
import {script} from './script';

// The set (as in film 01).
const DESK_TOP = 1240;
const GROUND = 1640;
const LAPTOP = {x: 400, y: DESK_TOP};
const BOWL_AT = {x: 930, y: DESK_TOP};
const TREE = {x: 1650, y: DESK_TOP};
const SCREEN = {x: 520, y: 900};
const COGI = {x: TREE.x - 10, y: DESK_TOP, scale: 1.45};
// The cloud's three stations: high in the sky, leaning in at the desk, sulking over the tree.
const CLOUD_HIGH = {x: 1150, y: 430, scale: 1};
const CLOUD_NEAR = {x: 1270, y: 880, scale: 0.78};
const CLOUD_OVER = {x: 1630, y: 690, scale: 0.72};
const READ_AT = {x: 1185, y: 630};
// The note the developer keeps private: funny, harmless, and not a secret anyone would mind.
const PRIVATE_MSG = '<private>I love Comic Sans</private>';
const PRIVATE_PILL = 'I love Comic Sans';
// The shelves: seven kept acorns with dates; slot 6 is the rebel that tries to fly off, twice.
const TAGS = ['02 NOV', '04 NOV', '06 NOV', '09 NOV', '11 NOV', '12 NOV', '13 NOV'];
const REBEL = 6;
const REBEL_AT = {x: TREE.x + shelfSlot(REBEL).x, y: TREE.y + shelfSlot(REBEL).y};

/** The V of migrating chats: offset of bubble i behind the leader, along and across the flight line. */
const FLOCK = Array.from({length: 7}, (_, i) => {
  const k = Math.ceil(i / 2);
  const side = i === 0 ? 0 : i % 2 ? -1 : 1;
  return {k, side, phase: i * 0.9};
});
const DIR = {x: 0.988, y: -0.152};
const ACROSS = {x: 0.152, y: 0.988};

// Shots: world point at the centre of the frame, and zoom.
const S = {
  flock: {x: 420, y: 560, zoom: 1.45},
  wide: {x: 850, y: 520, zoom: 0.95},
  gulp: {x: 1110, y: 500, zoom: 1.3},
  cloudClose: {x: 1150, y: 470, zoom: 1.5},
  read: {x: 1160, y: 540, zoom: 1.6},
  tree: {x: 1630, y: 1060, zoom: 1.35},
  hollow: {x: 1650, y: 1040, zoom: 1.9},
  treeBack: {x: 1600, y: 1000, zoom: 1.3},
  standoff: {x: 1470, y: 1030, zoom: 1.25},
  laptop: {x: 500, y: 960, zoom: 1.45},
  pass: {x: 1100, y: 1000, zoom: 0.86},
  peek: {x: 1600, y: 1000, zoom: 1.6},
  punch: {x: 1560, y: 1060, zoom: 1.55},
  rain: {x: 1580, y: 960, zoom: 1.15},
  batHome: {x: 1680, y: 1000, zoom: 1.5},
} satisfies Record<string, Shot>;

/** Every beat of the film as a frame, from the narration's word timings. */
const beats = (tl: Timeline) => {
  const w = tl.word;
  const L = (id: string) => tl.line(id);
  const k = {
    great: w('hook', 'great'),
    migration: w('hook', 'migration'),
    chats0: L('chats').from,
    flying: w('chats', 'flying'),
    memoryTool: w('chats', 'memory'),
    cloud: w('chats', 'cloud'),
    asks0: L('asks').from,
    account: w('asks', 'account'),
    key: w('asks', 'key'),
    reads0: L('reads').from,
    ai: w('reads', 'AI'),
    read: w('reads', 'read'),
    all: w('reads', 'all'),
    readsEnd: L('reads').to,
    home0: L('home').from,
    cogis: w('home', "Cogi's"),
    never: w('home', 'never'),
    homeW: w('home', 'home'),
    folder0: L('folder').from,
    folder: w('folder', 'folder'),
    computer: w('folder', 'computer'),
    folderEnd: L('folder').to,
    nos0: L('nos').from,
    no: [w('nos', 'No', 0), w('nos', 'No', 1), w('nos', 'No', 2)],
    nosEnd: L('nos').to,
    private0: L('private').from,
    anything: w('private', 'anything'),
    privateW: w('private', 'private'),
    cogiP: w('private', 'Cogi'),
    wont: w('private', "won't"),
    word: w('private', 'word'),
    privateEnd: L('private').to,
    sulk0: L('sulk').from,
    not: w('sulk', 'not'),
    thrilled: w('sulk', 'thrilled'),
    nothing0: L('nothing').from,
    leaves: w('nothing', 'leaves'),
    machine: w('nothing', 'machine'),
    notOne: w('nothing', 'Not'),
    acorn: w('nothing', 'acorn'),
    tag: L('tagline').from,
  };
  const catchAt = k.never + 1;
  return {
    ...k,
    gulps: FLOCK.slice(0, 6).map((_, i) => k.cloud + 4 + i * 5),
    readGulp: k.all + 2,
    liftOff: k.cogis - 4,
    catchAt,
    leap: 20,
    toss: k.homeW + 2,
    shelved: k.homeW + 16,
    swoop: k.folderEnd - 4,
    thrusts: k.no.map((n) => n - 11),
    swats: k.no.map((n) => n + 1),
    toOver: k.nosEnd + 8,
    typeFrom: k.anything - 2,
    typeTo: k.privateW + 12,
    sent: k.cogiP - 4,
    fizzle: k.word + 3,
    rainFrom: k.thrilled + 8,
    umbrella: k.thrilled + 22,
    huff: k.nothing0 + 2,
    rainTo: k.leaves + 4,
    sneak: k.notOne - 18,
    batHome: k.acorn + 1,
    reshelved: k.acorn + 15,
    wipe: k.tag - 16,
  };
};
type Beats = ReturnType<typeof beats>;

/** Arc from a to b over [f0, f1]; returns position and progress. */
const arc = (frame: number, f0: number, f1: number, a: {x: number; y: number}, b: {x: number; y: number}, height: number, easing = (t: number) => t) => {
  const t = easing(Math.max(0, Math.min(1, (frame - f0) / (f1 - f0))));
  return {x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t - height * 4 * t * (1 - t), t};
};

/** Something swatted away: launched from `at` at frame `f0`, flying left and up, spinning, falling. */
const flung = (frame: number, f0: number, at: {x: number; y: number}, seed: number) => {
  const d = frame - f0;
  return {x: at.x - d * (24 + seed * 4), y: at.y - d * (22 - seed * 3) + 0.9 * d * d, rot: -d * (18 + seed * 5), on: d >= 0 && d < 36};
};

/** A tail swat envelope: whips out fast, then swings back with a little overshoot. */
const swatEnv = (frame: number, at: number, fps: number) => {
  if (frame < at - 3) return 0;
  if (frame < at) return (frame - at + 3) / 3;
  return 1 - springAt(frame, at + 1, fps, {damping: 9, stiffness: 160, mass: 0.6});
};

/** The <private> note in flight: a pill with its tag. It never becomes an acorn. */
const PrivatePill = ({frame, x, y, s, opacity}: {frame: number; x: number; y: number; s: number; opacity: number}) => {
  const w = 30 + PRIVATE_PILL.length * 17;
  return (
    <g transform={`translate(${x} ${y}) scale(${s}) rotate(${Math.sin(frame / 4) * 4})`} opacity={opacity}>
      <rect x={-w / 2} y={-30} width={w} height={60} rx={30} fill={theme.paper} stroke={theme.ink} strokeWidth={4} />
      <text x="0" y="12" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="32" fill={theme.ink}>
        {PRIVATE_PILL}
      </text>
      <g transform={`translate(${-w / 2 + 10} -44) rotate(-8)`}>
        <rect x="0" y="0" width="132" height="34" rx="8" fill={theme.rust} />
        <text x="66" y="25" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="24" fill={theme.paper}>
          {'<private>'}
        </text>
      </g>
    </g>
  );
};

/** The brass plate over the hollow: where the folder really is. */
const Plate = ({x, y, s}: {x: number; y: number; s: number}) =>
  s > 0.01 ? (
    <g transform={`translate(${x} ${y}) scale(${s})`}>
      <rect x="-150" y="-30" width="300" height="60" rx="12" fill="#D9B46A" stroke="#9C7A3A" strokeWidth="6" />
      <circle cx="-130" cy="0" r="5" fill="#9C7A3A" />
      <circle cx="130" cy="0" r="5" fill="#9C7A3A" />
      <text x="0" y="12" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="34" fill={theme.ink}>
        ~/.cogito-mem
      </text>
    </g>
  ) : null;

const Scene = ({b, format}: {b: Beats; format: FormatId}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // ---- camera
  const camKeys: Parameters<typeof shotTrack>[1] = [
    [0, S.flock],
    [b.migration + 6, S.wide, EASE.inOut], // the cloud is waiting for them
    [b.memoryTool, {...S.wide, x: 930, zoom: 1.05}],
    [b.cloud + 6, S.gulp, EASE.inOut],
    [b.asks0 + 2, S.gulp],
    [b.account + 6, S.cloudClose, EASE.inOut],
    [b.reads0, S.cloudClose],
    [b.read - 2, S.read, EASE.inOut],
    [b.home0 - 10, {...S.read, zoom: 1.7}],
    [b.home0 + 2, S.tree, EASE.inOut], // whip down to the tree
    [b.catchAt, {x: 1630, y: 980, zoom: 1.55}],
    [b.shelved, {...S.tree, zoom: 1.42}],
    [b.folder - 6, S.hollow, EASE.inOut],
    [b.computer - 4, {...S.hollow, zoom: 2.0}],
    [b.computer + 12, S.treeBack, EASE.inOut],
    [b.swoop, S.treeBack],
    [b.thrusts[0] - 2, S.standoff, EASE.inOut],
    // a punch-in on every swat
    ...b.swats.flatMap((s, i): [number, Shot, (t: number) => number][] => [
      [s - 2, {...S.standoff, zoom: 1.25 + i * 0.03}, EASE.inOut],
      [s + 3, S.punch, EASE.out],
      [s + 16, {...S.standoff, zoom: 1.28 + i * 0.03}, EASE.inOut],
    ]),
    [b.nosEnd + 6, {...S.standoff, zoom: 1.34}],
    [b.private0 + 2, S.laptop, EASE.inOut], // whip left to the laptop
    [b.sent, {...S.laptop, zoom: 1.52}],
    [b.sent + 10, S.pass, EASE.inOut],
    [b.wont, {...S.pass, x: 1160, zoom: 0.9}],
    [b.wont + 12, S.peek, EASE.out],
    [b.privateEnd + 6, {...S.peek, zoom: 1.66}],
    [b.not - 4, S.rain, EASE.inOut],
    [b.leaves, {...S.rain, zoom: 1.2}],
    [b.machine + 12, {...S.rain, y: 900, zoom: 1.05}, EASE.inOut],
    [b.notOne - 6, S.batHome, EASE.inOut],
    [b.tag, {...S.batHome, zoom: 1.7}],
  ];
  const shakes: [number, number][] = [...b.swats.map((s): [number, number] => [s, 7]), [b.thrilled + 2, 9], [b.batHome, 6]];
  const shot = handheld(frame, shotTrack(frame, camKeys), shakes);
  const prev = handheld(frame - 1, shotTrack(frame - 1, camKeys), shakes);

  // ---- the migration: a V of winged chats flying up to the cloud
  const leader = {x: 480 + frame * 2.6, y: 540 - frame * 0.4};
  const mouthAt = (c: {x: number; y: number; scale: number}) => ({x: c.x, y: c.y + 48 * c.scale});
  const flock = FLOCK.map((f, i) => {
    const pos = {
      x: leader.x - DIR.x * f.k * 115 + ACROSS.x * f.side * f.k * 72,
      y: leader.y - DIR.y * f.k * 115 + ACROSS.y * f.side * f.k * 72,
    };
    if (i < 6) {
      const g = b.gulps[i];
      const t = ease(frame, [g - 20, g], [0, 1], EASE.in);
      const m = mouthAt(CLOUD_HIGH);
      return {x: pos.x + (m.x - pos.x) * t, y: pos.y + (m.y - pos.y) * t, s: (1 - f.k * 0.05) * (1 - t * 0.75), on: frame < g, phase: f.phase};
    }
    // the last chat is kept out to be read, then gulped too
    const t = ease(frame, [b.cloud - 6, b.cloud + 24], [0, 1], EASE.inOut);
    const hover = {x: READ_AT.x + Math.sin(frame / 9) * 6, y: READ_AT.y + Math.sin(frame / 7) * 5};
    const g = ease(frame, [b.readGulp - 6, b.readGulp], [0, 1], EASE.in);
    const m = mouthAt(CLOUD_HIGH);
    const x = pos.x + (hover.x - pos.x) * t;
    const y = pos.y + (hover.y - pos.y) * t;
    return {x: x + (m.x - x) * g, y: y + (m.y - y) * g, s: 0.85 * (1 - g * 0.75), on: frame < b.readGulp, phase: f.phase};
  });

  // ---- the cloud
  const swoopT = ease(frame, [b.swoop, b.thrusts[0] - 4], [0, 1], EASE.inOut);
  const overT = ease(frame, [b.toOver, b.sulk0], [0, 1], EASE.inOut);
  const leaveT = ease(frame, [b.leaves, b.machine + 26], [0, 1], EASE.in);
  const station = {
    x: CLOUD_HIGH.x + (CLOUD_NEAR.x - CLOUD_HIGH.x) * swoopT + (CLOUD_OVER.x - CLOUD_NEAR.x) * overT - leaveT * 760,
    y: CLOUD_HIGH.y + (CLOUD_NEAR.y - CLOUD_HIGH.y) * swoopT - Math.sin(swoopT * Math.PI) * 120 + (CLOUD_OVER.y - CLOUD_NEAR.y) * overT - leaveT * 520,
    scale: CLOUD_HIGH.scale + (CLOUD_NEAR.scale - CLOUD_HIGH.scale) * swoopT + (CLOUD_OVER.scale - CLOUD_NEAR.scale) * overT - leaveT * 0.15,
  };
  const gulpOpen = Math.max(0, ...[...b.gulps, b.readGulp].map((g) => (frame >= g - 5 && frame < g + 4 ? Math.sin(((frame - g + 5) / 9) * Math.PI) : 0)));
  const reading = frame >= b.read - 4 && frame < b.readGulp;
  const hit = Math.max(0, ...b.swats.map((s) => (frame >= s && frame < s + 12 ? 1 - (frame - s) / 12 : 0)));
  const grey = ease(frame, [b.not, b.thrilled + 6], [0, 1]);
  const puff = ease(frame, [b.nothing0 - 8, b.huff - 1], [0, 1], EASE.out) * (1 - ease(frame, [b.huff, b.huff + 3], [0, 1]));
  const eager = frame >= b.thrusts[0] - 4 && frame < b.nosEnd;
  const waiting = frame < b.gulps[0] - 5 ? 0.3 + Math.sin(frame / 6) * 0.08 : 0;
  const swatted = b.swats.filter((s) => frame >= s + 4).length;
  const cloudMouth: CloudPose['mouth'] =
    gulpOpen > 0.05 || waiting > 0 ? 'open' : hit > 0.2 ? 'o' : frame >= b.not || frame >= b.nosEnd + 2 || swatted >= 3 ? 'frown' : swatted >= 1 ? 'smile' : reading ? 'smile' : 'grin';
  const cloud: Partial<CloudPose> = {
    x: station.x + wobble(frame, 0.3, 10, 'cx'),
    y: station.y + wobble(frame, 0.25, 8, 'cy') + Math.sin(frame / 20) * 6,
    scale: station.scale,
    tilt: wobble(frame, 0.2, 2, 'ct') + (eager ? -5 : 0) + hit * 6 - leaveT * 10,
    squash: 1 + Math.sin(frame / 16) * 0.015 - gulpOpen * 0.05 + hit * 0.08 - puff * 0.06 + (frame >= b.huff && frame < b.huff + 10 ? Math.sin(((frame - b.huff) / 10) * Math.PI) * 0.1 : 0),
    look: reading
      ? [0.4 + Math.sin((frame - b.read) / 5) * 0.6, 1]
      : frame >= b.private0 && frame < b.not
        ? [0.8, 0.6]
        : frame >= b.thrusts[0] - 4 && frame < b.nosEnd
          ? [1, 0.7]
          : frame < b.cloud + 20
            ? [-1, 0.3]
            : [0, 0.2],
    blink: blinkAt(frame, 4) + (frame >= b.readGulp + 4 && frame < b.home0 - 6 ? 1 : 0),
    mouth: cloudMouth,
    open: Math.max(gulpOpen, waiting),
    brow: hit > 0.2 ? 1 : frame >= b.not ? -0.4 : eager || frame < b.read ? 0.6 : 0,
    grump: frame >= b.nosEnd + 2 ? Math.max(ease(frame, [b.nosEnd + 2, b.nosEnd + 10], [0, 0.6]), grey) : swatted >= 2 ? 0.35 : 0,
    glasses: ease(frame, [b.ai - 4, b.ai + 6], [0, 1], EASE.back) * (1 - ease(frame, [b.home0 - 4, b.home0], [0, 1])),
    grey,
    puff,
  };

  // the cloud's asks: two placards in the sky, then thrust at Cogi one by one with the magnifier
  const pop1 = springAt(frame, b.account - 3, fps, {damping: 10, stiffness: 200, mass: 0.7}) * (1 - ease(frame, [b.read - 8, b.read], [0, 1], EASE.in));
  const pop2 = springAt(frame, b.key - 3, fps, {damping: 10, stiffness: 200, mass: 0.7}) * (1 - ease(frame, [b.read - 8, b.read], [0, 1], EASE.in));
  const skyHand = (side: number, t: number) => ({x: CLOUD_HIGH.x + side * (110 + t * 80), y: CLOUD_HIGH.y + 10 - t * 70});
  const magIn = springAt(frame, b.read - 6, fps) * (1 - ease(frame, [b.readGulp, b.readGulp + 6], [0, 1], EASE.in));
  const magHand = {x: 1060 + magIn * 50, y: 560 + magIn * 210};
  const ASKS: ('signup' | 'key' | 'mag')[] = ['signup', 'key', 'mag'];
  const nearHand = {x: station.x + 150 * station.scale, y: station.y + 60 * station.scale};
  const face = {x: 1460, y: 1185};
  const thrust = ASKS.map((kind, i) => {
    const t = springAt(frame, b.thrusts[i], fps, {damping: 11, stiffness: 190, mass: 0.7});
    const back = frame >= b.swats[i] ? ease(frame, [b.swats[i], b.swats[i] + 8], [0, 1]) : 0;
    const reach = t * (1 - back);
    const hand = {x: nearHand.x + (face.x - nearHand.x) * reach, y: nearHand.y + (face.y - nearHand.y) * reach};
    const fly = flung(frame, b.swats[i], {x: face.x, y: face.y}, i);
    return {kind, hand, reach, held: frame >= b.thrusts[i] && frame < b.swats[i], fly, swatted: frame >= b.swats[i]};
  });

  // ---- Cogi
  const turnedAway = frame >= b.thrusts[0] - 6 && frame < b.nosEnd + 6;
  const turnHop = hop(frame, b.thrusts[0] - 8, 8, 26);
  const leapHop = hop(frame, b.catchAt - b.leap / 2, b.leap, 300);
  const caught = frame >= b.catchAt && frame < b.toss + 2;
  const windUp = ease(frame, [b.toss - 6, b.toss], [0, 1]) * (1 - ease(frame, [b.toss, b.toss + 4], [0, 1]));
  const swat = Math.max(0, ...b.swats.map((s) => swatEnv(frame, s, fps)));
  const cover = springAt(frame, b.wont - 4, fps, {damping: 12, stiffness: 200, mass: 0.6}) * (1 - ease(frame, [b.privateEnd + 10, b.privateEnd + 18], [0, 1]));
  const umbrella = springAt(frame, b.umbrella, fps, {damping: 10, stiffness: 170, mass: 0.7}) * (1 - ease(frame, [b.machine + 4, b.machine + 14], [0, 1], EASE.in));
  const drenched = frame >= b.rainFrom + 8 && frame < b.umbrella + 4;
  const bat = swatEnv(frame, b.batHome, fps);
  const tailFlick = springAt(frame, b.computer, fps, {damping: 6, stiffness: 120, mass: 0.6}) * (1 - ease(frame, [b.computer + 30, b.computer + 45], [0, 1]));
  const tailFlick2 = springAt(frame, b.reshelved, fps, {damping: 6, stiffness: 120, mass: 0.6}) * (1 - ease(frame, [b.reshelved + 30, b.reshelved + 44], [0, 1]));
  const idle = idleCogi(frame, 3);
  const aloof = turnedAway || (frame >= b.umbrella + 4 && frame < b.machine + 4) || (frame >= b.notOne - 8 && frame < b.tag);
  const cogi: Partial<CogiPose> = {
    ...idle,
    x: COGI.x,
    y: COGI.y,
    scale: COGI.scale,
    lift: leapHop.y + turnHop.y,
    squash: leapHop.squash * turnHop.squash * (idle.squash ?? 1) * (drenched ? 0.96 : 1),
    flip: turnedAway ? 1 : -1,
    lean: -windUp * 16 + (frame >= b.toss && frame < b.toss + 8 ? 10 : 0) - swat * 5,
    headRot: (turnedAway ? -14 : cover > 0.1 ? 16 * cover : frame >= b.notOne - 8 ? -6 : 0) + (idle.headRot ?? 0),
    tail: -(swat + bat) * 72 + (tailFlick + tailFlick2) * 26 + (drenched ? -10 : 0) + (idle.tail ?? 0),
    earL: drenched ? 22 : (idle.earL ?? 0),
    earR: drenched ? -18 : (idle.earR ?? 0),
    eye:
      frame >= b.liftOff && frame < b.catchAt
        ? [-1, -2.5]
        : frame >= b.not - 6 && frame < b.umbrella
          ? [-0.5, -2.6]
          : frame >= b.folder && frame < b.swoop
            ? [1.6, 0]
            : [0, 0],
    lid: turnedAway || frame >= b.notOne - 8 ? 0.8 : aloof ? 0.55 : drenched ? 0.35 : frame >= b.shelved && frame < b.swoop ? 0.45 : 0,
    blink: cover > 0.5 ? 1 : (idle.blink ?? 0),
    brow: frame >= b.liftOff + 2 && frame < b.catchAt ? 0.9 : drenched ? -0.5 : turnedAway ? 0.4 : 0,
    mouth: frame >= b.liftOff + 2 && frame < b.catchAt ? 'o' : caught ? 'grin' : aloof || (frame >= b.shelved && frame < b.swoop) ? 'smug' : 'smile',
    paws: windUp > 0 ? -windUp : leapHop.y < -20 && !caught ? 1.6 : caught ? 0.7 : umbrella > 0.05 ? 2 * umbrella : turnedAway ? 0.2 : 0,
    cover: cover * (1 - umbrella),
    acorn: caught,
  };

  // ---- the rebel acorn: tries to fly off (home), is tossed back; tries again (nothing), is batted home by the tail
  const flight1 = {
    x: keys(frame, [[b.liftOff, REBEL_AT.x], [b.catchAt - 8, REBEL_AT.x - 70, EASE.out], [b.catchAt, 1585, EASE.inOut]]),
    y: keys(frame, [[b.liftOff, REBEL_AT.y], [b.catchAt - 8, REBEL_AT.y - 150, EASE.out], [b.catchAt, 1125 - 300 + 60, EASE.inOut]]),
  };
  const tossArc = arc(frame, b.toss, b.shelved, {x: 1590, y: 1150}, REBEL_AT, 160, EASE.inOut);
  const sneakPath = {
    x: keys(frame, [[b.sneak, REBEL_AT.x], [b.sneak + 12, REBEL_AT.x + 110, EASE.out], [b.batHome, 1810, EASE.inOut]]),
    y: keys(frame, [[b.sneak, REBEL_AT.y], [b.sneak + 12, REBEL_AT.y - 70, EASE.out], [b.batHome, 1070, EASE.inOut]]),
  };
  const batArc = arc(frame, b.batHome, b.reshelved, {x: 1810, y: 1070}, REBEL_AT, 220, EASE.out);
  const rebelHome = frame < b.liftOff || (frame >= b.shelved && frame < b.sneak) || frame >= b.reshelved;
  const wingsOut = ease(frame, [b.liftOff, b.liftOff + 6], [0, 1], EASE.back);

  // ---- the private note
  const typedN = Math.round(ease(frame, [b.typeFrom, b.typeTo], [0, PRIVATE_MSG.length], EASE.linear));
  const pill = arc(frame, b.sent, b.fizzle, SCREEN, {x: 1400, y: 1020}, 140, EASE.inOut);
  const shelf = rebelHome ? TAGS.length : TAGS.length - 1;

  return (
    <Camera shot={shot} prev={prev} format={format}>
      <Layer depth={0.05}>
        <Sky />
      </Layer>
      <Layer depth={0.3}>
        <FarTrees />
      </Layer>
      <Layer depth={0.6}>
        <MidTrees frame={frame} />
      </Layer>
      <Layer>
        <Ground y={GROUND} frame={frame} />
        <Tree x={TREE.x} y={TREE.y} ground={GROUND} frame={frame} shelf={shelf} tags={shelf} labels={TAGS} sign={ease(frame, [b.computer - 2, b.computer + 8], [0, 1], EASE.back)} inside={1.1} />
        <Plate x={TREE.x} y={TREE.y - 448} s={springAt(frame, b.folder - 2, fps, {damping: 10, stiffness: 200, mass: 0.6})} />
        <Desk x0={-400} x1={1470} top={DESK_TOP} />
        <Laptop x={LAPTOP.x} y={LAPTOP.y} typed={PRIVATE_MSG.slice(0, typedN)} caret={frame >= b.typeFrom - 10 && frame < b.sent && Math.floor(frame / 8) % 2 === 0} sent={frame > b.sent ? 1 : 0} />
        <Hands x={LAPTOP.x} y={DESK_TOP - 28} typing={frame >= b.typeFrom && frame < b.typeTo ? frame / 3 : 0} />
        <Mug x={1215} y={DESK_TOP} frame={frame} />
        <Bowl x={BOWL_AT.x} y={BOWL_AT.y} frame={frame}>
          <Goldie pose={{...idleGoldie(frame), x: 20 + Math.sin(frame / 30) * 40, y: -190 + wobble(frame, 0.3, 6, 'gy'), scale: 1.1, flip: frame >= b.sent ? 1 : Math.sin(frame / 30 + 1) > 0 ? 1 : -1, look: frame >= b.sent && frame < b.fizzle + 10 ? [4, -3] : [0, 0], mouth: frame >= b.fizzle && frame < b.fizzle + 30 ? 'o' : 'smile'}} />
        </Bowl>
        {/* the private note flies at Cogi and fizzles before it gets there */}
        {frame >= b.sent && frame < b.fizzle ? <PrivatePill frame={frame} x={pill.x} y={pill.y} s={0.6 + pill.t * 0.4} opacity={1} /> : null}
        <Puff frame={frame} at={b.fizzle} x={1400} y={1040} size={40} n={6} dur={18} />
        <SparkleBurst frame={frame} at={b.fizzle} x={1400} y={1010} spread={70} n={5} size={26} />
        {/* the cloud's sky placards and magnifier (behind the cloud), and its arms */}
        {pop1 > 0.01 ? <CloudArm x0={CLOUD_HIGH.x - 120} y0={CLOUD_HIGH.y + 30} x1={skyHand(-1, pop1).x} y1={skyHand(-1, pop1).y} /> : null}
        {pop2 > 0.01 ? <CloudArm x0={CLOUD_HIGH.x + 120} y0={CLOUD_HIGH.y + 30} x1={skyHand(1, pop2).x} y1={skyHand(1, pop2).y} /> : null}
        {magIn > 0.01 ? <CloudArm x0={CLOUD_HIGH.x - 140} y0={CLOUD_HIGH.y + 60} x1={magHand.x} y1={magHand.y} /> : null}
        {thrust.map((t, i) =>
          t.reach > 0.02 && frame >= b.thrusts[i] ? <CloudArm key={`a${i}`} x0={station.x + 120 * station.scale} y0={station.y + 40 * station.scale} x1={t.hand.x} y1={t.hand.y} /> : null,
        )}
        <Cloud pose={cloud} id="main" />
        {pop1 > 0.01 ? <Placard x={skyHand(-1, pop1).x} y={skyHand(-1, pop1).y} kind="signup" s={0.82} rot={-10 * pop1} /> : null}
        {pop2 > 0.01 ? <Placard x={skyHand(1, pop2).x} y={skyHand(1, pop2).y} kind="key" s={0.82} rot={10 * pop2} /> : null}
        {flock.map((f, i) => (f.on ? <WingedBubble key={i} x={f.x} y={f.y} frame={frame} s={f.s} rot={-12} phase={f.phase} /> : null))}
        {magIn > 0.01 ? <Magnifier x={magHand.x} y={magHand.y} s={0.8} rot={28} /> : null}
        {/* the asks at the desk: thrust at Cogi, swatted away */}
        {thrust.map((t, i) =>
          t.held ? (
            <g key={i}>
              {t.kind === 'mag' ? <Magnifier x={t.hand.x} y={t.hand.y} s={0.75} rot={10 - 10 * t.reach} /> : <Placard x={t.hand.x} y={t.hand.y} kind={t.kind} s={0.78} rot={8 * t.reach} />}
            </g>
          ) : t.swatted && t.fly.on ? (
            <g key={i}>{t.kind === 'mag' ? <Magnifier x={t.fly.x} y={t.fly.y} s={0.75} rot={t.fly.rot} /> : <Placard x={t.fly.x} y={t.fly.y} kind={t.kind} s={0.78} rot={t.fly.rot} />}</g>
          ) : null,
        )}
        {b.swats.map((s, i) => (
          <ImpactStar key={i} frame={frame} at={s} x={face.x + 20} y={face.y - 120} r={78} rot={i * 25} />
        ))}
        {/* Cogi, the rebel acorn, the umbrella and the rain */}
        <Rain frame={frame} from={b.rainFrom} to={b.rainTo} x0={1400} x1={1730} y0={CLOUD_OVER.y + 90} y1={umbrella > 0.6 ? 850 : COGI.y - 200} />
        <LeafUmbrella x={COGI.x - 107} y={COGI.y - 140} open={umbrella} s={1.05} tilt={-6 + wobble(frame, 0.4, 3, 'um')} />
        <Cogi pose={cogi} />
        {frame >= b.liftOff && frame < b.catchAt ? <WingedAcorn x={flight1.x + Math.sin(frame / 3) * 6} y={flight1.y} frame={frame} s={1.8} rot={Math.sin(frame / 4) * 12} wings={wingsOut} /> : null}
        {frame >= b.toss + 1 && frame < b.shelved ? <WingedAcorn x={tossArc.x} y={tossArc.y} frame={frame} s={1.5} rot={tossArc.t * 400} wings={1 - tossArc.t} /> : null}
        <Puff frame={frame} at={b.shelved} x={REBEL_AT.x} y={REBEL_AT.y - 30} size={18} n={4} dur={12} />
        {frame >= b.sneak && frame < b.batHome ? (
          <WingedAcorn x={sneakPath.x + Math.sin(frame / 3) * 4} y={sneakPath.y + Math.sin(frame / 2.5) * 5} frame={frame} s={1.6} rot={Math.sin(frame / 4) * 10} wings={ease(frame, [b.sneak, b.sneak + 6], [0, 1], EASE.back)} />
        ) : null}
        {frame >= b.batHome && frame < b.reshelved ? <WingedAcorn x={batArc.x} y={batArc.y} frame={frame} s={1.5} rot={-batArc.t * 540} wings={1 - batArc.t} /> : null}
        <ImpactStar frame={frame} at={b.batHome} x={1800} y={1050} r={56} dur={9} />
        <Puff frame={frame} at={b.reshelved} x={REBEL_AT.x} y={REBEL_AT.y - 30} size={18} n={4} dur={12} />
        <Puff frame={frame} at={b.huff} x={station.x - 40} y={station.y + 60} size={34} n={6} dur={20} />
        <SparkleBurst frame={frame} at={b.machine + 4} x={COGI.x - 20} y={COGI.y - 300} spread={180} n={6} size={34} />
      </Layer>
      <Layer depth={1.3}>
        <Leaves frame={frame} x0={-200} x1={2400} y0={200} y1={1900} n={8} speed={1.6} scale={1.3} opacity={0.9} />
      </Layer>
    </Camera>
  );
};

export type FilmProps = {format: FormatId; mix: Mix | null};

export const Film = ({format, mix}: FilmProps) => {
  if (!mix) throw new Error(`No audio yet for ${script.id}: run npm run voice, sfx and music`);
  return <FilmBody format={format} mix={mix} />;
};

const FilmBody = ({format, mix}: {format: FormatId; mix: Mix}) => {
  const frame = useCurrentFrame();
  const tl = useMemo(() => buildTimeline(script, mix.voice, FPS), [mix.voice]);
  const b = useMemo(() => beats(tl), [tl]);
  const w = tl.word;
  return (
    <SoundProvider mix={mix}>
      <AbsoluteFill style={{background: theme.cream}}>
        {frame < b.wipe + 18 ? <Scene b={b} format={format} /> : null}
        <Binoculars from={0} to={b.great + 8} format={format} r0={700} />
        <LowerThird title="The chat" latin="Garrulus migratorius" from={b.great + 2} to={b.memoryTool - 4} format={format} />
        <LowerThird title="The cloud" latin="Cumulus signupensis" from={b.cloud + 6} to={b.key + 8} format={format} />
        <TailWipe from={b.wipe} dur={18} format={format} after={<TitleCard tl={tl} format={format} link={{shorts: 'Search “cogito-mem”', feed: 'Link in the first comment'}} />} />
        <Captions tl={tl} format={format} hide={['tagline', 'cta']} />
        <Finish leaks={[{from: b.machine, dur: 40}, {from: w('tagline', 'Cogi') - 6, dur: 46}]} />
      </AbsoluteFill>
      <Voice tl={tl} />
      <Music tl={tl} fadeOutFrom={tl.total - 40} fadeOutTo={tl.total - 2} />
      <Sfx name="flap" at={0} db={-6} frames={60} />
      <Sfx name="flap" at={b.chats0} db={-10} frames={50} />
      <Sfx name="whoosh" at={b.memoryTool} take={0} db={-7} />
      <Sfx name="gulp" at={b.gulps[0] + 1} db={-3} frames={22} />
      <Sfx name="gulp" at={b.gulps[4] + 1} db={-6} frames={22} />
      <Sfx name="boing" at={b.account - 2} take={0} db={-4} />
      <Sfx name="boing" at={b.key - 2} take={1} db={-4} />
      <Sfx name="pop" at={b.read - 5} db={-4} />
      <Sfx name="gulp" at={b.readGulp + 1} db={-2} />
      <Sfx name="whoosh" at={b.home0 - 9} take={1} db={-3} />
      <Sfx name="flap" at={b.liftOff} db={-9} frames={26} />
      <Sfx name="catch" at={b.catchAt + 1} take={0} db={-3} frames={18} />
      <Sfx name="catch" at={b.shelved + 1} take={1} db={-5} frames={18} />
      <Sfx name="pop" at={b.folder - 1} db={-5} />
      <Sfx name="boing" at={b.computer + 2} take={2} db={-6} />
      <Sfx name="whoosh" at={b.swoop} take={2} db={-5} />
      {b.thrusts.map((t, i) => (
        <Sfx key={`t${i}`} name="boing" at={t + 1} take={i} db={-9} />
      ))}
      {b.swats.map((s, i) => (
        <Sfx key={`s${i}`} name="swat" at={s + 1} take={i} db={-2} />
      ))}
      <Sfx name="whoosh" at={b.nosEnd + 10} take={0} db={-3} />
      <Sfx name="type" at={b.typeFrom} db={-3} />
      <Sfx name="whoosh" at={b.sent} take={1} db={-6} />
      <Sfx name="poof" at={b.fizzle + 1} db={-2} />
      <Sfx name="rumble" at={b.thrilled + 2} db={-2} />
      <Sfx name="rain" at={b.rainFrom} db={-5} frames={Math.min(105, b.rainTo - b.rainFrom + 12)} />
      <Sfx name="huff" at={b.huff + 1} db={-2} />
      <Sfx name="whoosh" at={b.leaves + 4} take={2} db={-6} />
      <Sfx name="ding" at={b.machine + 5} db={-6} />
      <Sfx name="flap" at={b.sneak} db={-11} frames={24} />
      <Sfx name="swat" at={b.batHome + 1} take={0} db={-3} />
      <Sfx name="catch" at={b.reshelved + 1} take={2} db={-4} frames={18} />
      <Sfx name="whoosh" at={b.wipe} take={0} db={-1} />
    </SoundProvider>
  );
};

/** The cover: Cogi smug under its leaf while the grey cloud rains on it; the hook in big type, the product named small. */
export const Cover = ({format}: {format: FormatId}) => {
  const frame = 30;
  const {width: W} = FORMATS[format];
  const shorts = format === 'shorts';
  const shot = shorts ? {x: 1590, y: 830, zoom: 1.5} : {x: 1560, y: 820, zoom: 1.15};
  const over = {x: 1600, y: shorts ? 735 : 700, scale: 0.8};
  return (
    <AbsoluteFill style={{background: theme.cream}}>
      <Camera shot={shot} prev={shot} format={format}>
        <Layer depth={0.05}>
          <Sky />
        </Layer>
        <Layer depth={0.3}>
          <FarTrees />
        </Layer>
        <Layer depth={0.6}>
          <MidTrees frame={frame} />
        </Layer>
        <Layer>
          <Ground y={GROUND} frame={frame} />
          <Tree x={TREE.x} y={TREE.y} ground={GROUND} frame={frame} shelf={TAGS.length} tags={TAGS.length} labels={TAGS} inside={1.1} />
          <Desk x0={-400} x1={1470} top={DESK_TOP} />
          <Mug x={1215} y={DESK_TOP} frame={frame} />
          <LeafUmbrella x={COGI.x - 40} y={COGI.y - 128} open={1} s={1.05} tilt={-8} />
          <Cogi pose={{...idleCogi(frame, 3), x: COGI.x, y: COGI.y, scale: COGI.scale, flip: -1, paws: 2, mouth: 'smug', lid: 0.55, brow: 0.5, eye: [1.5, 0], acorn: false, tail: 12}} />
          <Rain frame={frame} from={0} to={200} x0={COGI.x - 170} x1={COGI.x + 130} y0={over.y + 100} y1={COGI.y - 330} />
          <Cloud pose={{x: over.x, y: over.y, scale: over.scale, grey: 1, mouth: 'frown', grump: 1, brow: -0.4, look: [-0.3, 1]}} id="cover" />
        </Layer>
      </Camera>
      <div style={{position: 'absolute', top: shorts ? 230 : 50, width: W, textAlign: 'center', fontFamily: theme.fonts.display, fontWeight: 700, lineHeight: 1.02}}>
        <div style={{fontSize: shorts ? 128 : 108, color: theme.ink, WebkitTextStroke: `10px ${theme.paper}`, paintOrder: 'stroke fill'}}>Your memory</div>
        <div style={{fontSize: shorts ? 140 : 118, color: theme.orange, WebkitTextStroke: `11px ${theme.ink}`, paintOrder: 'stroke fill', marginTop: 8}}>stays home.</div>
      </div>
      <div style={{position: 'absolute', top: shorts ? 1610 : 1225, width: W, display: 'flex', justifyContent: 'center'}}>
        <div style={{padding: '12px 34px', borderRadius: 50, background: theme.ink, color: theme.paper, fontFamily: theme.fonts.display, fontWeight: 700, fontSize: shorts ? 46 : 40}}>
          Cogi · free memory for Claude Code
        </div>
      </div>
      <Finish />
    </AbsoluteFill>
  );
};
