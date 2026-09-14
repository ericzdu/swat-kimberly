# `paper/` — LaTeX manuscript

Target: **Information Processing in Agriculture** (Elsevier, ISSN 2214-3173).
The journal mandates no specific LaTeX class — its only requirement is editable
`.tex` source, with double-column permitted for LaTeX submissions. This uses
Elsevier's CAS single-column template.

## Layout

| File | What it is |
|---|---|
| `main.tex` | The manuscript, converted from `../PAPER.md` |
| `refs.bib` | Bibliography; entries marked `INCOMPLETE` need locators |
| `highlights.txt` | Separate-file highlights (journal requires this as its own upload) |
| `cas-sc.cls`, `cas-common.sty` | Copied from `templates/` so `main.tex` builds standalone |
| `elsarticle-num.bst` | Numbered reference style, matching what IPA prints |
| `templates/` | Unmodified CTAN downloads (`els-cas-templates`, `elsarticle`); gitignored — refetch from CTAN if needed |

## Building

```bash
brew install tectonic
cd paper && tectonic -X compile main.tex   # -> main.pdf
```

or upload `paper/` to Overleaf (the `.cls` is not in TeX Live's default set,
which is why it is copied in here).

## Before submission

- [x] Abstract cut from 508 to **226 words** (cap 250). The remaining 24 words are
      reserved for the headline finding, still a `\todo` inside the abstract.
- [ ] Fill author list, affiliations, ORCID, and a `\credit{}` per author (CRediT
      is required).
- [ ] Resolve every `\todo{}` and `\pending{}`, then delete both macros and the
      `xcolor` line.
- [ ] Complete the `INCOMPLETE` bib entries.
- [ ] Competing-interest declaration (currently a `\todo`).
- [ ] Research data: the journal's Option B — deposit and cite, or state why not.
- [ ] Figures as separate files, `Figure_1` etc.; none exist yet.
- [ ] Graphical abstract, 531 × 1328 px, if wanted (encouraged, not required).
