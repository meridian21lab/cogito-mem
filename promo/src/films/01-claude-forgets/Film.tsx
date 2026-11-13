// Film 01: "Claude forgets. Cogi doesn't." Every beat hangs on a word of the narration via tl.word();
// beats() computes them once for the pictures and the sound.
//
//  A  hook       Cogi photobombs the binoculars, whip to Goldie; species card; "Brilliant" punch-in, "goldfish" blank
//  B  tell/ends  the developer types; the message flies into the bowl; the chat ends, the bowl swirls, the words scatter
//  C  squirrel   whip to the tree: Cogi already has it; leaps to catch every word; files them with dates; the sign
//  D  lost       hard cut back to the bowl: a new chat and a lost goldfish
//  E  digs       Cogi digs through the pantry and finds the acorn
//  F  exact      Cogi throws it back into the bowl; it opens into the exact words
//  G  tagline    Cogi's tail wipes to the title; H the end card
import {useMemo} from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {Cogi, idleCogi, type CogiPose} from '../../cast/Cogi';
import {Goldie, idleGoldie, type GoldiePose} from '../../cast/Goldie';
import {Camera, Layer, handheld, shotTrack, type Shot} from '../../kit/Camera';
import {Captions} from '../../kit/Captions';
import {Finish} from '../../kit/Finish';
import {FORMATS, FPS, type FormatId} from '../../kit/formats';
import {EASE, ease, hop, keys, springAt, wobble} from '../../kit/motion';
import {Binoculars, LowerThird, TailWipe} from '../../kit/Overlays';
import {Music, Sfx, SoundProvider, Voice, type Mix} from '../../kit/Sound';
import {theme} from '../../kit/theme';
import {buildTimeline, type Timeline} from '../../kit/timeline';
import {FarTrees, Ground, MidTrees, Sky} from '../../world/Backdrop';
import {Bowl, MessageBubble} from '../../world/Bowl';
import {Desk, Hands, Laptop, Mug} from '../../world/Desk';
import {Bubbles, Burst, Leaves, PopBurst, Puff, SparkleBurst, rand} from '../../world/Particles';
import {TitleCard} from '../../world/Ending';
import {SmallAcorn, Tree} from '../../world/Tree';
import {script} from './script';

// The set.
const DESK_TOP = 1240;
const GROUND = 1640;
const LAPTOP = {x: 400, y: DESK_TOP};
const BOWL_AT = {x: 930, y: DESK_TOP};
const TREE = {x: 1650, y: DESK_TOP};
const SCREEN = {x: 520, y: 900};
const COGI_DESK = {x: 1400, y: DESK_TOP};
// What the developer tells the assistant: plain, a little funny, not jargon.
const MESSAGE = 'The client hates blue.';
const BUBBLE_TEXT = ['The client', 'hates blue.'];
const BUBBLE_Y = -300; // in the bowl's space, floating at the surface
// Everything else said in the chat, caught by Cogi as it flies past: [text, from the laptop?]
const SAID: [string, boolean][] = [
  ['Meeting at 3', true],
  ['Got it!', false],
  ['The client hates blue.', true],
  ['Noted!', false],
];
const OLD_TAGS = ['02 NOV', '05 NOV', '09 NOV', '11 NOV'];
const NEW_TAG = '13 NOV';

// Shots: world point at the centre of the frame, and zoom.
const S = {
  bomb: {x: 1185, y: 1060, zoom: 1.85},
  bowlClose: {x: 930, y: 1010, zoom: 1.95},
  goldieFace: {x: 950, y: 1050, zoom: 2.9},
  desk: {x: 690, y: 1010, zoom: 0.86},
  laptop: {x: 500, y: 960, zoom: 1.45},
  bowlMid: {x: 905, y: 1010, zoom: 1.35},
  tree: {x: 1630, y: 1080, zoom: 1.35},
  catch: {x: 1180, y: 1080, zoom: 1.3},
  hollow: {x: 1650, y: 1120, zoom: 2.0},
  treeBack: {x: 1620, y: 1080, zoom: 1.4},
  lost: {x: 930, y: 950, zoom: 1.8},
  dig: {x: 1650, y: 1110, zoom: 2.0},
  throw: {x: 1300, y: 1010, zoom: 0.86},
} satisfies Record<string, Shot>;

/** Every beat of the film as a frame, from the narration's word timings. */
const beats = (tl: Timeline) => {
  const w = tl.word;
  const L = (id: string) => tl.line(id);
  const k = {
    the: w('hook', 'The'),
    assistant: w('hook', 'assistant'),
    brilliant: w('brilliant', 'Brilliant'),
    helpful: w('brilliant', 'Helpful'),
    memory: w('goldfish', 'memory'),
    goldfish: w('goldfish', 'goldfish'),
    tell: L('tell').from,
    important: w('tell', 'important'),
    chat: w('ends', 'chat'),
    ends: w('ends', 'ends...'),
    poofLine: L('poof').from,
    poof: w('poof', 'poof'),
    gone: w('poof', 'Gone'),
    poofEnd: L('poof').to,
    watch: L('watch').from,
    squirrel: w('watch', 'squirrel'),
    catches: L('catches').from,
    files: L('files').from,
    date: w('files', 'date'),
    right: w('files', 'right'),
    computer: w('files', 'computer'),
    lost0: L('lost').from,
    lostChat: w('lost', 'chat'),
    lost: w('lost', 'lost'),
    again: w('lost', 'again'),
    digs0: L('digs').from,
    there: w('digs', 'there'),
    exact0: L('exact').from,
    back: w('exact', 'back'),
    belong: w('exact', 'belong'),
    tag: L('tagline').from,
  };
  const typeFrom = k.tell + 4;
  const typeTo = k.important + 12;
  const sent = typeTo + 4;
  const throwAt = k.exact0 + 4;
  return {
    ...k,
    typeFrom,
    typeTo,
    sent,
    arrive: sent + 20,
    catchFrom: SAID.map((_, i) => k.catches + 4 + i * 14),
    flight: 22,
    intoHollow: k.files - 2,
    stamps: [k.date - 4, k.date + 4, k.date + 12, k.date + 18],
    cut: k.lost0 - 16,
    throwAt,
    plop: throwAt + 30,
    wipe: k.tag - 16,
  };
};
type Beats = ReturnType<typeof beats>;

/** Arc from a to b over [f0, f1]; returns position and progress. */
const arc = (frame: number, f0: number, f1: number, a: {x: number; y: number}, b: {x: number; y: number}, height: number) => {
  const t = Math.max(0, Math.min(1, (frame - f0) / (f1 - f0)));
  return {x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t - height * 4 * t * (1 - t), t};
};

/** A spoken line in flight: a word pill for the first half, then it pops into an acorn. */
const FlyingWord = ({frame, text, x, y, t}: {frame: number; text: string; x: number; y: number; t: number}) => {
  const morph = Math.max(0, Math.min(1, (t - 0.62) / 0.14));
  const w = 26 + text.length * 17;
  return (
    <g transform={`translate(${x} ${y})`}>
      {morph < 1 ? (
        <g transform={`scale(${1 - morph * 0.8}) rotate(${Math.sin(frame / 4) * 4})`} opacity={1 - morph}>
          <rect x={-w / 2} y={-30} width={w} height={60} rx={30} fill={theme.paper} stroke={theme.ink} strokeWidth={4} />
          <text x="0" y="12" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="32" fill={theme.ink}>
            {text}
          </text>
        </g>
      ) : null}
      {morph > 0 ? <SmallAcorn x={0} y={24} s={1.5 * morph} rot={frame * 18} /> : null}
    </g>
  );
};

/** The message's letters flying apart when the bubble pops. */
const Scatter = ({frame, at, x, y}: {frame: number; at: number; x: number; y: number}) => {
  const t = frame - at;
  if (t < 0 || t > 28) return null;
  const chars = BUBBLE_TEXT.flatMap((line, li) => [...line].map((c, i) => ({c, x: (i - line.length / 2) * 16, y: li * 32 - 12})));
  return (
    <g transform={`translate(${x} ${y})`} opacity={1 - t / 28}>
      {chars.map((ch, i) =>
        ch.c === ' ' ? null : (
          <text
            key={i}
            x={ch.x + (ch.x * 0.25 + (rand(i) - 0.5) * 18) * t}
            y={ch.y + (-9 + rand(i + 40) * 6) * t + 0.55 * t * t}
            fontFamily={theme.fonts.display}
            fontWeight={700}
            fontSize={28}
            fill={theme.ink}
            transform={`rotate(${(rand(i + 7) - 0.5) * 40 * t} ${ch.x} ${ch.y})`}
          >
            {ch.c}
          </text>
        ),
      )}
    </g>
  );
};

const Scene = ({tl, b, format}: {tl: Timeline; b: Beats; format: FormatId}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // ---- camera
  const camKeys: Parameters<typeof shotTrack>[1] = [
    [0, {...S.bomb, x: S.bomb.x + 30}],
    [b.the - 2, S.bomb],
    [b.the + 10, S.bowlClose, EASE.inOut],
    [b.brilliant - 1, S.bowlClose],
    [b.brilliant + 5, {...S.bowlClose, zoom: 2.3, y: 1030}, EASE.out],
    [b.helpful - 2, {...S.bowlClose, zoom: 2.3, y: 1030}],
    [b.helpful + 6, {...S.bowlClose, zoom: 1.9, rot: -4}, EASE.out],
    [b.memory, {...S.bowlClose, zoom: 2.0}],
    [b.goldfish + 6, S.goldieFace, EASE.inOut],
    [b.goldfish + 22, S.goldieFace],
    [b.goldfish + 34, S.desk, EASE.inOut],
    [b.typeFrom, S.desk],
    [b.typeTo, S.laptop, EASE.inOut],
    [b.sent + 4, S.laptop],
    [b.arrive + 4, S.bowlMid, EASE.inOut],
    [b.chat, S.bowlMid],
    [b.poof - 6, S.bowlClose, EASE.inOut],
    [b.gone - 2, S.bowlClose],
    [b.gone + 4, S.goldieFace, EASE.out],
    [b.watch + 2, S.goldieFace],
    [b.watch + 12, S.tree, EASE.inOut],
    [b.catches - 6, S.tree],
    [b.catches + 6, S.catch, EASE.inOut],
    [b.intoHollow + 2, S.catch],
    [b.intoHollow + 20, S.hollow, EASE.inOut],
    [b.right - 4, S.hollow],
    [b.right + 14, S.treeBack, EASE.inOut],
    [b.cut - 1, {...S.treeBack, zoom: 1.5}],
    [b.cut, S.lost, EASE.linear], // a hard cut
    [b.digs0 - 12, {...S.lost, zoom: 1.9}],
    [b.digs0, S.dig, EASE.inOut],
    [b.there + 10, {...S.dig, zoom: 2.15, y: 1100}],
    [b.throwAt - 4, S.throw, EASE.inOut],
    [b.throwAt + 16, S.throw],
    [b.plop + 6, S.bowlClose, EASE.inOut],
    [b.tag, {...S.bowlClose, zoom: 2.1}],
  ];
  const shakes: [number, number][] = [[b.poof, 14], [b.lost + 2, 8], [b.there, 10], [b.plop, 9]];
  const shot = handheld(frame, shotTrack(frame, camKeys), shakes);
  const prev = handheld(frame - 1, shotTrack(frame - 1, camKeys), shakes);

  // ---- Goldie
  const gx = keys(frame, [
    [0, -110],
    [b.brilliant, 20],
    [b.goldfish, 30],
    [b.chat, 40],
    [b.ends + 20, 20],
    [b.lost0, 0],
    [b.lost - 8, -60],
    [b.lost, 112, EASE.in],
    [b.lost + 10, 70, EASE.out],
    [b.plop, 50],
    [b.belong, 10],
  ]);
  const gy = keys(frame, [
    [0, -195],
    [b.brilliant, -185],
    [b.arrive, -175],
    [b.lost0, -185],
    [b.exact0, -178],
  ]);
  const swirl = ease(frame, [b.ends - 6, b.ends + 6], [0, 1]) * (1 - ease(frame, [b.poof + 4, b.gone], [0, 1]));
  const flip1 = ease(frame, [b.brilliant, b.brilliant + 16], [0, 360], EASE.inOut);
  const flip2 = ease(frame, [b.back, b.back + 16], [0, -360], EASE.inOut);
  const wiggle = frame > b.helpful && frame < b.helpful + 18 ? Math.sin((frame - b.helpful) * 1.3) * 16 * (1 - (frame - b.helpful) / 18) : 0;
  const blankA = ease(frame, [b.goldfish + 4, b.goldfish + 10], [0, 1]) * (1 - ease(frame, [b.goldfish + 34, b.goldfish + 44], [0, 1]));
  const blankB = ease(frame, [b.gone - 4, b.gone + 2], [0, 1]) * (1 - ease(frame, [b.watch + 14, b.watch + 20], [0, 1]));
  const blankC = ease(frame, [b.again - 2, b.again + 4], [0, 1]) * (1 - ease(frame, [b.digs0, b.digs0 + 4], [0, 1]));
  const blank = Math.max(blankA, blankB, blankC);
  const happy = ease(frame, [b.plop + 6, b.plop + 14], [0, 1]);
  const lookAround = frame > b.lost0 && frame < b.lost - 8 ? [Math.sin(frame / 5) * 5, Math.cos(frame / 7) * 3] : [0, 0];
  const bonk = frame >= b.lost && frame < b.lost + 10 ? 1 - (frame - b.lost) / 10 : 0;
  const goldie: Partial<GoldiePose> = {
    ...idleGoldie(frame),
    x: gx,
    y: gy + wobble(frame, 0.3, 6, 'gy'),
    scale: 1.1,
    flip: frame > b.lost0 && frame < b.lost - 8 ? (Math.sin(frame / 9) > 0 ? 1 : -1) : 1,
    tilt: flip1 + flip2 + wiggle + swirl * frame * 9 + idleGoldie(frame).tilt!,
    beat: frame < b.brilliant ? 1.4 : 1,
    swim: frame / (frame < b.brilliant ? 14 : 24),
    blank,
    mouth: blank > 0.5 ? 'flat' : happy > 0.5 || (frame > b.brilliant && frame < b.helpful + 20) || (frame > b.arrive && frame < b.arrive + 30) ? 'grin' : 'smile',
    sparkle: Math.max(happy, frame > b.brilliant && frame < b.helpful + 20 ? 1 : 0),
    look: lookAround as [number, number],
    squash: 1 - bonk * 0.25 + (frame > b.arrive && frame < b.arrive + 12 ? Math.sin(((frame - b.arrive) / 12) * Math.PI) * 0.12 : 0),
  };

  // ---- the message: typed, sent, held in the bowl, scattered; later restored
  const typedN = Math.round(ease(frame, [b.typeFrom, b.typeTo], [0, MESSAGE.length], EASE.linear));
  const fly = arc(frame, b.sent, b.arrive, SCREEN, {x: BOWL_AT.x + 10, y: BOWL_AT.y + BUBBLE_Y}, 160);
  const inBowl = frame >= b.arrive && frame < b.poof;
  const strain = ease(frame, [b.poofLine, b.poof], [0, 1], EASE.in);
  const tremble = frame > b.chat && frame < b.poof ? Math.sin(frame * 2.1) * (2 + strain * 9) : 0;
  const restored = springAt(frame, b.plop + 4, fps, {damping: 10, stiffness: 160, mass: 0.7});

  // ---- the photobomb (0 .. "The"): Cogi sniffs the lens, then bolts
  const bolt = ease(frame, [b.the - 4, b.the + 8], [0, 1], EASE.in);
  const bomb: Partial<CogiPose> = {
    ...idleCogi(frame, 7),
    x: 1235 + bolt * 120,
    y: 1365,
    lift: -bolt * 900,
    squash: frame < b.the - 4 ? 1 + Math.sin(frame * 0.9) * 0.02 : 1.15,
    scale: 3.3,
    flip: -1,
    headRot: Math.sin(frame * 1.3) * 3,
    eye: [2, 0.5],
    brow: 0.9,
    mouth: 'o',
    earL: Math.sin(frame * 0.7) * 10,
    acorn: false,
  };

  // ---- Cogi
  const cogiAtLip = {x: TREE.x - 10, y: TREE.y};
  const hopOut = hop(frame, b.catches - 4, 14, 90);
  const hopIn = hop(frame, b.intoHollow, 16, 110);
  const caught = b.catchFrom.filter((c) => frame >= c + b.flight).length;
  const leaps = b.catchFrom.map((c) => hop(frame, c + b.flight - 8, 16, 75));
  const leap = leaps.find((h) => h.y !== 0 || h.squash !== 1) ?? {y: 0, squash: 1};
  const shelfFill = frame < b.intoHollow + 14 ? OLD_TAGS.length : Math.min(OLD_TAGS.length + 4, OLD_TAGS.length + Math.floor(ease(frame, [b.intoHollow + 14, b.date], [0, 4], EASE.linear) + 0.001));
  const tags = OLD_TAGS.length + b.stamps.filter((s) => frame >= s).length + Math.max(0, Math.min(1, (frame - (b.stamps.find((s) => frame < s) ?? 1e9) + 4) / 4));
  const digging = frame >= b.digs0 + 6 && frame < b.there;
  const found = frame >= b.there;
  const cogiX = keys(frame, [
    [0, cogiAtLip.x],
    [b.catches - 4, cogiAtLip.x],
    [b.catches + 10, COGI_DESK.x, EASE.out],
    [b.intoHollow, COGI_DESK.x],
    [b.intoHollow + 16, cogiAtLip.x, EASE.out],
  ]);
  const cheek = frame < b.catches ? 0.45 : frame < b.intoHollow + 14 ? Math.min(1, 0.2 + caught * 0.22) : Math.max(0, 1 - (frame - b.intoHollow - 14) / 20);
  const presenting = found ? springAt(frame, b.there, fps) : 0;
  const windUp = ease(frame, [b.throwAt - 6, b.throwAt], [0, 1]) * (1 - ease(frame, [b.throwAt, b.throwAt + 4], [0, 1]));
  const thrown = frame >= b.throwAt + 2;
  const tailFlick = springAt(frame, b.squirrel, fps, {damping: 6, stiffness: 120, mass: 0.6}) * (1 - ease(frame, [b.squirrel + 30, b.squirrel + 45], [0, 1]));
  const digShake = digging ? Math.sin(frame * 2.4) * 4 : 0;
  const foundHop = found ? hop(frame, b.there, 16, 70) : {y: 0, squash: 1};
  const cogi: Partial<CogiPose> = {
    ...idleCogi(frame, 3),
    x: cogiX + digShake,
    y: TREE.y,
    lift: hopOut.y + hopIn.y + leap.y + foundHop.y,
    squash: hopOut.squash * hopIn.squash * leap.squash * foundHop.squash,
    scale: 1.45,
    flip: frame >= b.catches + 2 && frame < b.intoHollow + 8 ? -1 : digging ? 1 : -1,
    lean: digging ? 24 + Math.sin(frame * 1.3) * 6 : -windUp * 18 + (thrown && frame < b.throwAt + 10 ? 14 : 0),
    tail: (digging ? Math.sin(frame * 1.7) * 30 : 0) + tailFlick * 28 + idleCogi(frame, 3).tail!,
    lid: frame > b.squirrel - 4 && frame < b.catches ? 0.5 : 0,
    mouth: frame > b.squirrel - 4 && frame < b.catches ? 'smug' : found && frame < b.throwAt ? 'grin' : cheek > 0.5 ? 'o' : frame > b.right && frame < b.lost0 ? 'smug' : 'smile',
    brow: found && frame < b.throwAt ? 0.8 : frame > b.squirrel && frame < b.catches ? 0.6 : leap.y < -20 ? 0.7 : 0,
    cheek,
    sparkle: found && frame < b.throwAt + 10 ? 1 : 0,
    paws: windUp > 0 ? -windUp : found && !thrown ? presenting * 1.6 : leap.y < -10 ? 1.2 : frame > b.right && frame < b.lost0 ? 0.6 : 0,
    acorn: frame < b.catches || (found && !thrown),
    eye: frame > b.watch && frame < b.catches ? [1.5, 0.5] : frame > b.catches && frame < b.intoHollow ? [-1.5, -1] : [0, 0],
  };

  // ---- things in flight
  const paws = {x: COGI_DESK.x - 52, y: DESK_TOP - 150};
  const flying = b.catchFrom.map((c, i) => ({
    ...arc(frame, c, c + b.flight, SAID[i][1] ? {x: 780, y: 880} : {x: BOWL_AT.x + 40, y: BOWL_AT.y - 330}, paws, 170),
    on: frame >= c && frame < c + b.flight,
    text: SAID[i][0],
  }));
  const thrownAcorn = arc(frame, b.throwAt + 2, b.plop, {x: TREE.x - 50, y: TREE.y - 160}, {x: BOWL_AT.x + 20, y: BOWL_AT.y - 290}, 280);

  // ---- thought cloud (lost)
  const cloud = springAt(frame, b.lostChat + 4, fps) * (1 - ease(frame, [b.digs0 - 14, b.digs0 - 6], [0, 1]));

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
        <Tree
          x={TREE.x}
          y={TREE.y}
          ground={GROUND}
          frame={frame}
          shelf={found ? shelfFill - 1 : shelfFill}
          tags={found ? tags - 1 : tags}
          labels={[...OLD_TAGS, NEW_TAG, NEW_TAG, NEW_TAG, NEW_TAG]}
          sign={ease(frame, [b.right, b.computer], [0, 1], EASE.back)}
          inside={1 + (found ? 0.4 : 0)}
        />
        {digging || (found && frame < b.there + 20) ? (
          <Burst
            frame={frame}
            from={b.digs0 + 8}
            to={b.there - 4}
            x={TREE.x}
            y={TREE.y - 200}
            every={4}
            render={(i) => (i % 3 === 0 ? <SmallAcorn x={0} y={0} s={0.9} /> : <path d="M 0 -16 C 13 -8 13 8 0 16 C -13 8 -13 -8 0 -16 Z" fill={i % 2 ? theme.orange : theme.forest.near} />)}
          />
        ) : null}
        <Desk x0={-400} x1={1470} top={DESK_TOP} />
        <Laptop
          x={LAPTOP.x}
          y={LAPTOP.y}
          typed={MESSAGE.slice(0, typedN)}
          caret={frame < b.sent && Math.floor(frame / 8) % 2 === 0}
          reply={springAt(frame, b.arrive - 6, fps)}
          cleared={ease(frame, [b.chat - 2, b.ends + 4], [0, 1])}
          sent={frame > b.sent ? 1 : 0}
        />
        <Hands x={LAPTOP.x} y={DESK_TOP - 28} typing={frame >= b.typeFrom && frame < b.typeTo ? frame / 3 : 0} />
        <Mug x={1215} y={DESK_TOP} frame={frame} />
        <Bowl x={BOWL_AT.x} y={BOWL_AT.y} frame={frame} slosh={swirl + bonk * 0.6 + (frame >= b.plop && frame < b.plop + 20 ? 1 - (frame - b.plop) / 20 : 0)} level={swirl * 30} swirl={swirl}>
          <Goldie pose={goldie} />
          <Bubbles frame={frame} x={gx + 70} y={gy - 20} from={b.goldfish + 2} to={b.goldfish + 3} rise={2.5} />
          <Bubbles frame={frame} x={gx + 70} y={gy - 20} from={b.plop + 10} to={b.tag} every={14} rise={2.2} seed={9} />
          {inBowl ? <MessageBubble x={10 + tremble} y={BUBBLE_Y} text={BUBBLE_TEXT} frame={frame} scale={0.82 + strain * 0.2} /> : null}
          {frame >= b.plop + 2 ? <MessageBubble x={10} y={BUBBLE_Y} text={BUBBLE_TEXT} frame={frame} scale={0.82 * restored} /> : null}
          <PopBurst frame={frame} at={b.plop + 2} x={10} y={BUBBLE_Y} r={90} color={theme.orange} />
        </Bowl>
        <PopBurst frame={frame} at={b.poof} x={BOWL_AT.x + 10} y={BOWL_AT.y + BUBBLE_Y} r={150} dur={18} />
        <Scatter frame={frame} at={b.poof} x={BOWL_AT.x + 10} y={BOWL_AT.y + BUBBLE_Y} />
        {frame >= b.sent && frame < b.arrive ? <MessageBubble x={fly.x} y={fly.y} text={BUBBLE_TEXT} frame={frame} scale={0.5 + fly.t * 0.32} /> : null}
        <Cogi pose={cogi} />
        {flying.map((a, i) => (a.on ? <FlyingWord key={i} frame={frame} text={a.text} x={a.x} y={a.y} t={a.t} /> : null))}
        {b.catchFrom.map((c, i) => (
          <Puff key={i} frame={frame} at={c + b.flight} x={paws.x} y={paws.y + leap.y} size={18} n={4} dur={12} />
        ))}
        {thrown && frame < b.plop ? (
          <g>
            {[3, 6, 9].map((d) => {
              const p = arc(frame - d, b.throwAt + 2, b.plop, {x: TREE.x - 50, y: TREE.y - 160}, {x: BOWL_AT.x + 20, y: BOWL_AT.y - 290}, 280);
              return p.t > 0 ? <circle key={d} cx={p.x} cy={p.y - 20} r={12 - d} fill={theme.paper} opacity={0.8} /> : null;
            })}
            <SmallAcorn x={thrownAcorn.x} y={thrownAcorn.y} s={2} rot={frame * 25} />
          </g>
        ) : null}
        {cloud > 0.01 ? (
          <g transform={`translate(${BOWL_AT.x - 30} ${BOWL_AT.y - 520}) scale(${cloud * 0.92})`}>
            <circle cx="70" cy="120" r="14" fill={theme.paper} />
            <circle cx="40" cy="78" r="22" fill={theme.paper} />
            <path d="M -190 0 C -210 -70 -120 -115 -60 -92 C -30 -152 70 -152 100 -92 C 170 -115 225 -40 190 10 C 210 62 130 92 70 72 C 30 102 -60 102 -95 72 C -165 92 -220 50 -190 0 Z" fill={theme.paper} />
            <text x="0" y="-22" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="40" fill={theme.ink}>
              the client hates…
            </text>
            <text x="0" y="36" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="54" fill={theme.orange}>
              {'???'.slice(0, 1 + (Math.floor(frame / 8) % 3))}
            </text>
          </g>
        ) : null}
        <SparkleBurst frame={frame} at={b.there} x={TREE.x - 20} y={TREE.y - 260} spread={150} n={7} size={40} />
        <SparkleBurst frame={frame} at={b.plop + 6} x={BOWL_AT.x} y={BOWL_AT.y - 380} spread={140} n={6} size={34} />
        {frame < b.the + 14 ? <Cogi pose={bomb} /> : null}
      </Layer>
      <Layer depth={1.3}>
        <Leaves frame={frame} x0={-200} x1={2400} y0={200} y1={1900} n={9} speed={1.6} scale={1.3} opacity={0.9} />
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
        {frame < b.wipe + 18 ? <Scene tl={tl} b={b} format={format} /> : null}
        <Binoculars from={0} to={b.the + 6} format={format} />
        <LowerThird title="The AI assistant" latin="Carassius forgetfulus" from={b.assistant - 4} to={b.memory - 6} format={format} />
        <LowerThird title="The squirrel" latin="Sciurus archivus" from={b.squirrel + 2} to={b.files - 6} format={format} />
        <TailWipe from={b.wipe} dur={18} format={format} after={<TitleCard tl={tl} format={format} />} />
        <Captions tl={tl} format={format} hide={['tagline', 'cta']} />
        <Finish leaks={[{from: b.there - 4, dur: 40}, {from: w('tagline', 'Cogi') - 6, dur: 46}]} />
      </AbsoluteFill>
      <Voice tl={tl} />
      <Music tl={tl} fadeOutFrom={tl.total - 40} fadeOutTo={tl.total - 2} />
      <Sfx name="whoosh" at={b.the - 2} take={1} db={-3} />
      <Sfx name="blub" at={b.goldfish + 4} />
      <Sfx name="whoosh" at={b.goldfish + 22} take={0} db={-4} />
      <Sfx name="type" at={b.typeFrom} db={-2} />
      <Sfx name="whoosh" at={b.sent} take={1} db={-4} />
      <Sfx name="swirl" at={b.chat - 2} db={3} />
      <Sfx name="pop" at={b.poof + 1} />
      <Sfx name="cricket" at={b.poofEnd + 2} db={-3} frames={50} />
      <Sfx name="whoosh" at={b.watch + 2} take={2} db={-3} />
      {b.catchFrom.map((c, i) => (
        <Sfx key={i} name="catch" at={c + b.flight} take={i} db={-4} frames={18} />
      ))}
      {b.stamps.slice(0, 3).map((s, i) => (
        <Sfx key={i} name="stamp" at={s + 1} take={i} db={-2} frames={18} />
      ))}
      <Sfx name="blub" at={b.lost + 1} take={1} />
      <Sfx name="whoosh" at={b.digs0 - 12} take={1} db={-4} />
      <Sfx name="dig" at={b.digs0 + 8} db={-3} frames={Math.min(90, b.there - b.digs0 - 8)} />
      <Sfx name="ding" at={b.there + 1} />
      <Sfx name="whoosh" at={b.throwAt} take={2} db={-3} />
      <Sfx name="plop" at={b.plop + 1} />
      <Sfx name="whoosh" at={b.wipe} take={0} db={-1} />
    </SoundProvider>
  );
};

/** The cover: Goldie lost for words, Cogi holding the dated acorn, and the hook in big type. No captions. */
export const Cover = ({format}: {format: FormatId}) => {
  const frame = 40;
  const {width: W} = FORMATS[format];
  const shorts = format === 'shorts';
  const shot = {x: 1150, y: shorts ? 1000 : 915, zoom: 1.12};
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
          <Tree x={TREE.x} y={TREE.y} ground={GROUND} frame={frame} shelf={8} tags={8} labels={[...OLD_TAGS, NEW_TAG, NEW_TAG, NEW_TAG, NEW_TAG]} />
          <Desk x0={-400} x1={1470} top={DESK_TOP} />
          <Mug x={1215} y={DESK_TOP} frame={frame} />
          <Bowl x={BOWL_AT.x} y={BOWL_AT.y} frame={frame}>
            <Goldie pose={{...idleGoldie(frame), x: 10, y: -185, scale: 1.25, blank: 1, mouth: 'flat', tilt: -6}} />
          </Bowl>
          <g transform={`translate(${BOWL_AT.x - 20} ${BOWL_AT.y - 500}) scale(0.8)`}>
            <circle cx="70" cy="120" r="14" fill={theme.paper} />
            <circle cx="40" cy="78" r="22" fill={theme.paper} />
            <path d="M -150 0 C -170 -70 -100 -110 -50 -90 C -20 -150 80 -150 110 -90 C 170 -110 200 -40 170 10 C 190 60 120 90 70 70 C 30 100 -60 100 -90 70 C -150 90 -180 50 -150 0 Z" fill={theme.paper} />
            <text x="10" y="30" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="90" fill={theme.orange}>
              ???
            </text>
          </g>
          <Cogi pose={{...idleCogi(frame, 3), x: COGI_DESK.x + 10, y: DESK_TOP, scale: 1.9, flip: -1, mouth: 'smug', lid: 0.5, brow: 0.7, paws: 1, acornLabel: NEW_TAG, tail: 14}} />
        </Layer>
      </Camera>
      <div style={{position: 'absolute', top: shorts ? 250 : 70, width: W, textAlign: 'center', fontFamily: theme.fonts.display, fontWeight: 700, lineHeight: 1.02}}>
        <div style={{fontSize: shorts ? 128 : 112, color: theme.ink, WebkitTextStroke: `10px ${theme.paper}`, paintOrder: 'stroke fill'}}>Your AI forgets.</div>
        <div style={{fontSize: shorts ? 140 : 122, color: theme.orange, WebkitTextStroke: `11px ${theme.ink}`, paintOrder: 'stroke fill', marginTop: 8}}>Cogi doesn’t.</div>
      </div>
      <Finish />
    </AbsoluteFill>
  );
};
