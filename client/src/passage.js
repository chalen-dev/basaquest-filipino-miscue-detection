// Hardcoded reference passages for this prototype.
//
// `PASSAGES` (English, Filipino) is the original single-passage-per-language
// set the app shipped with — still used for the English toggle, since the
// GOP scorer (see server/src/scorers/gopScorer.js) only supports Filipino.
//
// `PASSAGE_VARIANTS.fil` is a picker list of Filipino passages: the original
// "Ang Pagtatanggol sa Ilog" passage, a deliberately-mispronounced version of
// it (for testing whether the scorer actually catches known errors — see
// gop/test_recordings/deliberate_errors.json, which is the answer key this
// variant's errors are drawn from), and two shorter, simpler passages
// (grade1_2 / grade3_4 sourced from gop/test_recordings/) for testing against
// less demanding text.
//
// NOTE: none of these Filipino passages have been reviewed for grade-level
// appropriateness or curriculum fit — see gop/README.md and the ROADMAP for
// the known vocabulary-coverage gap against the training corpus.
export const PASSAGES = {
  en: {
    title: 'The Defense of the River',
    text:
      'Long ago, in the land now called Davao, a brave leader named Datu Bago ruled his people well. ' +
      'He welcomed traders who came by boat and helped his community grow strong. ' +
      'When soldiers from Spain arrived, Datu Bago and his warriors defended their home along the wide river. ' +
      'His courage is still remembered today.',
  },
  fil: {
    title: 'Ang Pagtatanggol sa Ilog',
    text:
      'Noong unang panahon, sa lupaing tinatawag ngayong Davao, may isang matapang na pinuno na nagngangalang Datu Bago na mahusay na namuno sa kanyang mga tao. ' +
      'Tinanggap niya ang mga mangangalakal na dumating sa pamamagitan ng bangka at tinulungan ang kanyang komunidad na lumago. ' +
      'Nang dumating ang mga sundalong Espanyol, ipinagtanggol ni Datu Bago at ng kanyang mga mandirigma ang kanilang tahanan sa tabi ng malawak na ilog. ' +
      'Ang kanyang tapang ay naaalala pa rin hanggang ngayon.',
  },
};

export const PASSAGE_VARIANTS = {
  fil: [
    {
      id: 'datu-bago-correct',
      title: 'Ang Pagtatanggol sa Ilog',
      description: 'The full passage, read correctly.',
      text: PASSAGES.fil.text,
    },
    {
      id: 'datu-bago-errors',
      title: 'Ang Pagtatanggol sa Ilog (With Errors)',
      description:
        'Same passage with 5 words deliberately misspelled — an accuracy test. Read it exactly as ' +
        'shown, mistakes included (highlighted in red below); the scorer should flag nangangalang, ' +
        'mangangarakal, ipinagtanggul, malawek, and naalala.',
      text:
        'Noong unang panahon, sa lupaing tinatawag ngayong Davao, may isang matapang na pinuno na nangangalang Datu Bago na mahusay na namuno sa kanyang mga tao. ' +
        'Tinanggap niya ang mga mangangarakal na dumating sa pamamagitan ng bangka at tinulungan ang kanyang komunidad na lumago. ' +
        'Nang dumating ang mga sundalong Espanyol, ipinagtanggul ni Datu Bago at ng kanyang mga mandirigma ang kanilang tahanan sa tabi ng malawek na ilog. ' +
        'Ang kanyang tapang ay naalala pa rin hanggang ngayon.',
      // Words to highlight in the passage card — the deliberate mistakes,
      // matched case-insensitively against each rendered word stripped of
      // punctuation (see ReadingScreen.jsx's renderPassageText).
      errorWords: ['nangangalang', 'mangangarakal', 'ipinagtanggul', 'malawek', 'naalala'],
    },
    {
      id: 'grade-1-2',
      title: 'Si Ana at si Bantay (Grade 1–2)',
      description: 'A shorter, simpler passage about a girl and her dog.',
      text:
        'Si Ana ay may aso. Ang pangalan ng aso ay Bantay. Tuwing umaga, naglalaro sila sa bakuran. ' +
        'Masaya si Ana kapag kasama niya si Bantay. Binibigyan niya ito ng pagkain at tubig bawat araw. ' +
        'Sa hapon, umuuwi sila sa bahay. Doon sila natutulog nang mahimbing.',
    },
    {
      id: 'grade-3-4',
      title: 'Ang Pamilya ni Mario (Grade 3–4)',
      description: 'A slightly longer passage about a boy who wants to become a teacher.',
      text:
        'May maliit na bahay sa tabi ng ilog. Doon nakatira ang pamilya ni Mario. ' +
        'Tuwing hapon, tumutulong siya sa kanyang ina na magluto ng hapunan. ' +
        'Pagkatapos, nagbabasa siya ng kanyang mga aralin sa tabi ng bintana. ' +
        'Gusto niyang maging guro balang araw upang matulungan ang mga bata sa kanilang nayon.',
    },
  ],
};
