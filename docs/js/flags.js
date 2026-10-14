// Country flags on Windows. A flag is an emoji (🇮🇪 is the letters I and E as "regional
// indicators"), and Windows has no flag emoji: it shows the two letters instead. Where
// that happens this adds the class "flag-font" to <html>, which puts the flag font in
// docs/fonts/ in front of the page's fonts (see styles.css), and starts loading it so
// it is ready by the time the first results arrive. Systems that draw flags themselves
// (macOS, iOS, Android, Linux, and Firefox everywhere) keep their own and never load it.
//
// The check is adapted from country-flag-emoji-polyfill, copyright (c) 2022 TalkJS, MIT
// licence: draw the emoji, shrunk to one pixel, in white and then in black. A colour
// emoji ignores the text colour, so both come out the same (and not black); letters
// drawn instead of a flag follow the text colour.

const EMOJI_FONTS = '"Twemoji Mozilla","Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol",' +
  '"Noto Color Emoji","EmojiOne Color","Android Emoji",sans-serif';

function drawnInColour(emoji) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return true;                          // cannot tell: leave the page as it is
  ctx.textBaseline = "top";
  ctx.font = `100px ${EMOJI_FONTS}`;
  ctx.scale(0.01, 0.01);
  const pixel = colour => {
    ctx.clearRect(0, 0, 100, 100);
    ctx.fillStyle = colour;
    ctx.fillText(emoji, 0, 0);
    return ctx.getImageData(0, 0, 1, 1).data.join(",");
  };
  const white = pixel("#fff"), black = pixel("#000");
  return white === black && !black.startsWith("0,0,0,");
}

/** True when this system shows emoji in colour but not country flags (Windows). */
export function needsFlagFont() {
  try {
    return drawnInColour("😊") && !drawnInColour("🇨🇭");
  } catch {
    return false;                                 // a canvas that cannot be read: leave it
  }
}

if (needsFlagFont()) {
  document.documentElement.classList.add("flag-font");
  document.fonts?.load('1em "Country Flags"', "🇮🇪").catch(() => {});
}
