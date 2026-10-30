import check_common

_BODY = r"""
    var oversetDetails = [];
    for (var s3 = 0; s3 < doc.stories.length; s3++) {
        var st = doc.stories[s3];
        if (!st.overflows) continue;
        var storyLen = 0, firstPage = "?", lastFramePage = "?";
        var containers = [];
        var lastFrameH = 0, lastFrameW = 0;
        var lastFrameEmpty = false, lastFrameNext = "none";
        var anchoredCount = 0, oversizedAnchored = 0;
        try { storyLen = st.characters.length; } catch (eL) {}
        try { containers = st.textContainers; } catch (eC0) {}
        try {
            if (containers.length > 0) {
                if (containers[0].parentPage) firstPage = containers[0].parentPage.name;
                var lf = containers[containers.length - 1];
                if (lf.parentPage) lastFramePage = lf.parentPage.name;
                var lb = lf.geometricBounds;
                lastFrameH = Math.round(lb[2] - lb[0]);
                lastFrameW = Math.round(lb[3] - lb[1]);
                try { lastFrameEmpty = (lf.characters.length === 0); } catch (eLE) {}
                try { lastFrameNext = lf.nextTextFrame ? "yes" : "no"; } catch (eN2) {}
            }
        } catch (eC) {}
        try {
            for (var g2 = 0; g2 < st.allPageItems.length; g2++) {
                var it = st.allPageItems[g2];
                try {
                    if (it.graphics && it.graphics.length > 0) {
                        anchoredCount++;
                        var gb = it.geometricBounds;
                        if ((gb[3] - gb[1]) > pageW || (gb[2] - gb[0]) > pageH) oversizedAnchored++;
                    }
                } catch (eIt) {}
            }
        } catch (eG3) {}

        var charsPerFrame = 2000;
        var needMore = "?";
        try {
            var used = containers.length * charsPerFrame;
            var deficit = storyLen - used;
            if (deficit > 0) needMore = String(Math.ceil(deficit / charsPerFrame));
        } catch (eD) {}

        oversetDetails.push(
            "story#" + s3 +
            " chars=" + storyLen +
            " frames=" + containers.length +
            " firstPage=" + firstPage +
            " lastPage=" + lastFramePage +
            " lastFrame(" + lastFrameW + "x" + lastFrameH + "pt empty=" + lastFrameEmpty + " threaded=" + lastFrameNext + ")" +
            " anchoredImgs=" + anchoredCount + " oversized=" + oversizedAnchored +
            " approxNeedMoreFrames=" + needMore
        );
    }
    if (oversetDetails.length > 0) problems.push("OVERSET_STORIES=" + oversetDetails.length + ":" + oversetDetails.join(";"));
"""


def check(app, caption_map=None):
    """Flag stories whose text overflows the available frames."""
    return check_common.run(app, _BODY)
