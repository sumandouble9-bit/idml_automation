import check_common

_BODY = r"""
    app.findGrepPreferences = NothingEnum.nothing;
    app.findGrepPreferences.findWhat = "###Insert .*? here###";
    var leftover = doc.findGrep();
    app.findGrepPreferences = NothingEnum.nothing;
    if (leftover.length > 0) {
        var samples = [];
        for (var i = 0; i < Math.min(leftover.length, 5); i++) samples.push(leftover[i].contents);
        problems.push("LEFTOVER_PLACEHOLDERS=" + leftover.length + ":" + samples.join(","));
    }
"""


def check(app, caption_map=None):
    """Flag leftover ###Insert ... here### image placeholders."""
    return check_common.run(app, _BODY)
