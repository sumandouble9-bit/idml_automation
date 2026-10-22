import os
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


class IDMLPackage:
    """
    Handles unzipping, reading, modifying XML, and repackaging IDML archives
    while strictly preserving InDesign XML namespaces, structure, and the uncompressed
    mimetype entry specification.
    """

    NAMESPACES = {
        "idPkg": "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging",
        "idml": "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging",
        "x": "adobe:ns:meta/",
    }

    def __init__(self, idml_path: str):
        self.idml_path = Path(idml_path).resolve()
        if not self.idml_path.exists():
            raise FileNotFoundError(f"IDML file not found: {self.idml_path}")
        self.extract_dir = None

    def unpack(self, destination: str = None) -> Path:
        """Unpacks the IDML archive into a directory."""
        if destination is None:
            self.extract_dir = self.idml_path.parent / f"extracted_{self.idml_path.stem}"
        else:
            self.extract_dir = Path(destination).resolve()

        if self.extract_dir.exists():
            shutil.rmtree(self.extract_dir)
        self.extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(self.idml_path, "r") as z:
            z.extractall(self.extract_dir)

        return self.extract_dir

    def read_xml(self, relative_path: str) -> ET.Element:
        """Reads and parses an XML file from the extracted package."""
        if not self.extract_dir:
            raise RuntimeError("Package has not been unpacked yet.")
        file_path = self.extract_dir / relative_path
        if not file_path.exists():
            raise FileNotFoundError(f"File {relative_path} not found in package.")
        tree = ET.parse(file_path)
        return tree.getroot()

    def write_xml(self, relative_path: str, root_element: ET.Element):
        """Serializes an XML ElementTree back to the package preserving formatting."""
        if not self.extract_dir:
            raise RuntimeError("Package has not been unpacked yet.")
        file_path = self.extract_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.ElementTree(root_element)
        tree.write(file_path, encoding="utf-8", xml_declaration=True)

    def pack(self, output_idml_path: str = None) -> Path:
        """
        Packs the extracted directory into a valid .idml file.
        InDesign requires:
        1. 'mimetype' file must be first and uncompressed (Stored).
        2. All other files compressed with Deflate.
        """
        if not self.extract_dir or not self.extract_dir.exists():
            raise RuntimeError("No unpacked directory to pack.")

        if output_idml_path is None:
            out_path = self.idml_path.parent / f"{self.idml_path.stem}_formatted.idml"
        else:
            out_path = Path(output_idml_path).resolve()

        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Write zip archive with strict mimetype order
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            mimetype_path = self.extract_dir / "mimetype"
            if mimetype_path.exists():
                z.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)

            for root, _, files in os.walk(self.extract_dir):
                for file in files:
                    full_p = Path(root) / file
                    rel_p = full_p.relative_to(self.extract_dir).as_posix()
                    if rel_p == "mimetype":
                        continue
                    z.write(full_p, rel_p)

        return out_path

    def cleanup(self):
        """Removes extracted temporary directory."""
        if self.extract_dir and self.extract_dir.exists():
            shutil.rmtree(self.extract_dir)
            self.extract_dir = None
