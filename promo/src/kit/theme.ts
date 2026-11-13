// Palette and type for the Cogi films. Cogi's colours come from site/assets/cogi.svg; the cream, ink and
// orange from the site's style.css. Goldie gets a yellow-gold so it never reads as a second Cogi.
import {loadFont} from '@remotion/fonts';
import {staticFile} from 'remotion';

export const theme = {
  cream: '#FBF1E2',
  paper: '#FFFBF4',
  sand: '#F6EBDD',
  ink: '#2B1D12',
  orange: '#E8893A',
  rust: '#C8621A',
  cogi: {dark: '#B85E1C', mid: '#D9772B', light: '#E08A3C', belly: '#FBE7C6', pink: '#F2A38A', eye: '#3A2416'},
  acorn: {nut: '#B97A3D', cap: '#6B4423', light: '#D39A5C'},
  goldie: {body: '#F4B935', belly: '#FFE08A', fin: '#FFC94D', finEdge: '#F29E4C', eye: '#2B1D12'},
  water: {top: '#CDEDEA', deep: '#9ED6D4', line: '#7CC3C1'},
  forest: {far: '#C9D4AE', mid: '#A3B886', near: '#7E9A69', deep: '#5E7A52', trunk: '#7A5233', trunkDark: '#5A3A22'},
  wood: {top: '#C98B55', edge: '#9C6234', dark: '#7A4A26'},
  sky: {top: '#FCEBD0', bottom: '#FFF6E6', sun: '#FFE3A8'},
  skin: '#F1C29A',
  sleeve: '#4F6D7A',
  fonts: {display: 'Outfit', body: 'Work Sans'},
} as const;

let loaded = false;

export const loadFonts = () => {
  if (loaded) return;
  loaded = true;
  loadFont({family: theme.fonts.display, url: staticFile('fonts/Outfit-Bold.ttf'), weight: '700'});
  loadFont({family: theme.fonts.body, url: staticFile('fonts/WorkSans-Regular.ttf'), weight: '400'});
};
