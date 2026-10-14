# twemoji-country-flags.woff

The country flags the page shows on Windows, which has no flag emoji of its own
(see `docs/js/flags.js`).

**Artwork:** [Twemoji](https://github.com/twitter/twemoji), copyright Twitter, Inc and other
contributors, licensed under [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**Font:** Twemoji Mozilla 0.7.0 from [mozilla/twemoji-colr](https://github.com/mozilla/twemoji-colr/releases/tag/v0.7.0).

**Changes made:** reduced to the country flags only (the regional indicator letters U+1F1E6–U+1F1FF and
the flags they combine into), and saved as WOFF. It was made with fontTools:

```bash
curl -LO https://github.com/mozilla/twemoji-colr/releases/download/v0.7.0/Twemoji.Mozilla.ttf
python3 -m fontTools.subset Twemoji.Mozilla.ttf --drop-tables+=FFTM \
  --unicodes=U+1F1E6-1F1FF --flavor=woff --output-file=twemoji-country-flags.woff
```

The same approach as [country-flag-emoji-polyfill](https://github.com/talkjs/country-flag-emoji-polyfill)
(MIT, copyright (c) 2022 TalkJS), whose check for missing flags `flags.js` adapts.
