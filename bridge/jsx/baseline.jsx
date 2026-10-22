// InDesign ExtendScript: baseline.jsx
// Snaps text frames to baseline grid, sets chapter start offsets,
// and ensures total page count is even (print spread compliant).

(function() {
    var idmlFile = File(arguments[0]);
    var outputFile = arguments.length > 1 ? File(arguments[1]) : idmlFile;

    if (!idmlFile.exists) return;

    app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
    var doc = app.open(idmlFile);

    try {
        // Enforce baseline grid snap across all body paragraphs
        for (var s = 0; s < doc.paragraphStyles.length; s++) {
            var pStyle = doc.paragraphStyles[s];
            if (pStyle.name === "body_text" || pStyle.name === "noindentj") {
                pStyle.alignToBaseline = true;
            }
        }

        // Ensure total page count is even for print-readiness
        if (doc.pages.length % 2 !== 0) {
            var blankPage = doc.pages.add(LocationOptions.AT_END);
            blankPage.appliedMaster = null; // Blank verso page without headers/footers
        }

        doc.exportFile(ExportFormat.INDESIGN_MARKUP, outputFile);
        doc.close(SaveOptions.NO);
    } catch (err) {
        doc.close(SaveOptions.NO);
        throw err;
    }
})();
