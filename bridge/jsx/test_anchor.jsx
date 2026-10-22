
    var doc = app.documents.length > 0 ? app.activeDocument : null;
    if (doc) {
        var str = 'Doc open: ' + doc.name;
        var outF = File('C:/Users/LENOVO/Desktop/idml_automation/jsx_out.txt');
        outF.open('w');
        outF.writeln(str);
        outF.close();
    }
    