import check_common

_BODY = r"""
    var missing = 0, missingNames = [];
    for (var l = 0; l < doc.links.length; l++) {
        var lk = doc.links[l];
        if (lk.status != LinkStatus.NORMAL) {
            missing++;
            if (missingNames.length < 5) missingNames.push(lk.name + "(" + lk.status + ")");
        }
    }
    if (missing > 0) problems.push("BROKEN_LINKS=" + missing + ":" + missingNames.join(","));

    var emptyFrames = 0;
    for (var r = 0; r < doc.rectangles.length; r++) {
        var rc = doc.rectangles[r];
        try {
            if (rc.graphics.length === 0) {
                var gb = rc.geometricBounds;
                var h = gb[2] - gb[0], w = gb[3] - gb[1];
                if (h > 20 && w > 20) emptyFrames++;
            }
        } catch (e) {}
    }
    if (emptyFrames > 0) problems.push("EMPTY_IMAGE_FRAMES=" + emptyFrames);
"""


def check(app, caption_map=None):
    """Flag broken links and empty image frames."""
    return check_common.run(app, _BODY)
