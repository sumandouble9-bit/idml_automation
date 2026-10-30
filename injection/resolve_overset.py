JS = 1246973031

JS_RESOLVE_OVERSET = """
                var doc = app.activeDocument;
                var oldRuler = doc.viewPreferences.rulerOrigin;
                doc.viewPreferences.rulerOrigin = RulerOrigin.PAGE_ORIGIN;
                var pageH = doc.documentPreferences.pageHeight;
                var pageW = doc.documentPreferences.pageWidth;
                var pagesAdded = 0;
                var jams = [];

                var HEIGHT_STEP = 72;   // grow ~1 line-block per step
                var WIDTH_STEP  = 12;   // gentle width relief for over-wide unbreakable lines
                var MAX_STEPS   = 40;   // up to ~40 * 72pt (~5 pages) of forced growth

                function frameGeom(page) {
                    var top = page.marginPreferences.top;
                    var bottom = pageH - page.marginPreferences.bottom;
                    var left, right;
                    if (doc.documentPreferences.facingPages && page.side == PageSideOptions.LEFT_HAND) {
                        left  = page.marginPreferences.right;
                        right = pageW - page.marginPreferences.left;
                    } else {
                        left  = page.marginPreferences.left;
                        right = pageW - page.marginPreferences.right;
                    }
                    return [top, left, bottom, right];
                }

                function describeStuck(frame, story) {
                    var info = { idx: -1, style: "", text: "" };
                    try {
                        var prev = frame.previousTextFrame;
                        info.idx = prev.characters[-1].index + 1;
                        var par = story.characters[info.idx].paragraphs[0];
                        info.style = par.appliedParagraphStyle.name;
                        var t = par.contents.replace(/[\\r\\n\\t]+/g, " ");
                        info.text = (t.length > 140) ? t.substring(0, 140) + "..." : t;
                    } catch (e) {}
                    return info;
                }

                for (var i = 0; i < doc.stories.length; i++) {
                    var s = doc.stories[i];
                    s.recompose();
                    if (s.textContainers.length === 0) continue;
                    var lastFrame = s.textContainers[s.textContainers.length - 1];
                    if (lastFrame.constructor.name !== "TextFrame") continue;

                    var guard = 0;
                    while (lastFrame.overflows) {
                        guard++;
                        if (guard > 30000) { jams.push("ABORT|story " + i + "|guard limit reached"); break; }

                        var newPage = doc.pages.add();
                        pagesAdded++;
                        var newFrame = newPage.textFrames.add();
                        newFrame.geometricBounds = frameGeom(newPage);
                        lastFrame.nextTextFrame = newFrame;
                        lastFrame = newFrame;
                        s.recompose();

                        if (lastFrame.characters.length === 0 && lastFrame.overflows) {
                            // JAM: the next content unit cannot fit or break on a normal page.
                            var stuck = describeStuck(lastFrame, s);

                            // GENERAL ESCAPE: grow the frame until it accepts the stuck unit.
                            var steps = 0;
                            while (lastFrame.characters.length === 0 && lastFrame.overflows && steps < MAX_STEPS) {
                                var gb = lastFrame.geometricBounds;
                                var newBottom = gb[2] + HEIGHT_STEP;
                                var newRight  = Math.min(gb[3] + WIDTH_STEP, pageW - 6);
                                lastFrame.geometricBounds = [gb[0], gb[1], newBottom, newRight];
                                steps++;
                                s.recompose();
                            }
                            var fh = (lastFrame.geometricBounds[2] - lastFrame.geometricBounds[0]);

                            if (lastFrame.characters.length === 0 && lastFrame.overflows) {
                                // Still unplaceable after max growth: capture the remaining overset text.
                                var remaining = "";
                                try {
                                    var start = lastFrame.previousTextFrame.characters[-1].index + 1;
                                    remaining = s.contents.substring(start);
                                    if (remaining.length > 4000) remaining = remaining.substring(0, 4000) + " ...[truncated]";
                                    remaining = remaining.replace(/[\\r\\n\\t]+/g, " ");
                                } catch (e) {}
                                jams.push("UNRESOLVED|page~" + doc.pages.length + "|storyIdx=" + stuck.idx +
                                          "|style=" + stuck.style + "|stuck=[" + stuck.text + "]|REMAINING_TEXT=[" + remaining + "]");
                                break; // cannot proceed on this thread; stop to avoid an infinite loop
                            } else {
                                jams.push("FORCED|page~" + doc.pages.length + "|storyIdx=" + stuck.idx +
                                          "|style=" + stuck.style + "|frameHeight=" + fh.toFixed(0) + "pt|content=[" + stuck.text + "]");
                            }
                        }
                    }
                }
                doc.viewPreferences.rulerOrigin = oldRuler;

                var oversetLeft = 0;
                for (var q = 0; q < doc.stories.length; q++) {
                    var cs = doc.stories[q].textContainers;
                    for (var j = 0; j < cs.length; j++) { if (cs[j].overflows) oversetLeft++; }
                }
                "PAGES=" + pagesAdded + "|OVERSET=" + oversetLeft + "|JAMS=" + jams.length + "\\n" + jams.join("\\n");
                """


def resolve_overset(app):
    """Run on app.activeDocument. Returns (pages_added, overset_left, jam_lines)."""
    report = app.DoScript(JS_RESOLVE_OVERSET, JS)
    lines = str(report).split(chr(10))
    summary = lines[0] if lines else ''
    jam_lines = [ln for ln in lines[1:] if ln.strip()]
    pages_added, overset_left = 0, 0
    try:
        parts = dict(p.split('=', 1) for p in summary.split('|') if '=' in p)
        pages_added = int(parts.get('PAGES', '0'))
        overset_left = int(parts.get('OVERSET', '0'))
    except Exception:
        pass
    return pages_added, overset_left, jam_lines
