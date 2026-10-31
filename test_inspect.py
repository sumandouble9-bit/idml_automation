import zipfile, re

with zipfile.ZipFile('final_output_files/idml_files/1957_9788165883300.idml') as z:
    st = z.read('Resources/Styles.xml').decode('utf-8', 'replace')
    for m in re.finditer(r'<ParagraphStyle\b[^>]*Self=[^>]*>', st):
        tag = m.group(0)
        if any(k in tag.lower() for k in ['chapter', 'heading', 'part']):
            print(tag)
