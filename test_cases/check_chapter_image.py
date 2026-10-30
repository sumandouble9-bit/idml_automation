import check_common

_BODY = r"""
    var bad = [];
    for (var si = 0; si < doc.stories.length; si++){
        var ps = doc.stories[si].paragraphs;
        for (var pi = 0; pi < ps.length; pi++){
            var p = ps[pi];
            var s = ""; try { s = p.appliedParagraphStyle.name.toLowerCase(); } catch(e){}
            if (s.indexOf("chapter_name") >= 0 || s.indexOf("master_chapter") >= 0){
                var n = 0; try { n = p.allPageItems.length; } catch(e){}
                if (n > 0){
                    var t = ""; try { t = p.contents.replace(/[\r\n\uFFFC]/g, "").substring(0, 20); } catch(e){}
                    if (bad.length < 8) bad.push(t);
                }
            }
        }
    }
    if (bad.length > 0) problems.push("CHAPTER_HEADING_IMAGE=" + bad.length + ":" + bad.join(","));
"""


def check(app, caption_map=None):
    """Flag chapter headings that contain an anchored image (heading won't start clean)."""
    return check_common.run(app, _BODY)
