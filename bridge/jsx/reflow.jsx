// InDesign ExtendScript: reflow.jsx
// Resolves overset text by dynamically adding pages and threading text frames.

(function() {
    var idmlFile = File(arguments[0]);
    var outputFile = arguments.length > 1 ? File(arguments[1]) : idmlFile;

    if (!idmlFile.exists) {
        alert("Input IDML file does not exist: " + idmlFile.fsName);
        return;
    }

    app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
    var doc = app.open(idmlFile);

    try {
        var pageHeight = doc.documentPreferences.pageHeight;
        var pageWidth = doc.documentPreferences.pageWidth;

        // Iterate through all stories to check for overset text
        for (var s = 0; s < doc.stories.length; s++) {
            var story = doc.stories[s];
            if (story.textContainers.length === 0) continue;

            var lastFrame = story.textContainers[story.textContainers.length - 1];

            // While the last container has overset text, add a page and thread
            var maxSafety = 2000; // prevent infinite loops
            var count = 0;

            while (lastFrame.overflows && count < maxSafety) {
                count++;
                // Add new page at the end of document
                var newPage = doc.pages.add(LocationOptions.AT_END);
                if (doc.masterSpreads.length > 0) {
                    newPage.appliedMaster = doc.masterSpreads.item("A-Master");
                }

                var margins = newPage.marginPreferences;
                var top = margins.top;
                var bottom = pageHeight - margins.bottom;
                // Cap text frame above running footer margin (e.g. max 558 pt)
                if (bottom > 558) { bottom = 558; }

                var left = (newPage.side === PageSideOptions.LEFT_HAND) ? margins.right : margins.left;
                var right = pageWidth - ((newPage.side === PageSideOptions.LEFT_HAND) ? margins.left : margins.right);

                // Add text frame on new page
                var newFrame = newPage.textFrames.add({
                    geometricBounds: [top, left, bottom, right]
                });

                // Thread story to new text frame
                lastFrame.nextTextFrame = newFrame;
                lastFrame = newFrame;
            }
        }

        // Save updated IDML
        doc.exportFile(ExportFormat.INDESIGN_MARKUP, outputFile);
        doc.close(SaveOptions.NO);

    } catch (err) {
        doc.close(SaveOptions.NO);
        throw err;
    }
})();
